"""Merge verified extraction into the canonical ProjectState.

The only writer of intake data into ProjectState. Raw model output never reaches
this module -- only ``VerifiedExtraction``, whose every field has already passed
deterministic provenance checks.

Merge rules, all enforced here:

* Only supported fields can change.
* An existing KNOWN value is never silently overwritten.
* A different new value for a KNOWN field produces a CONFLICTED field and a
  ContradictionRecord, not a replacement.
* UNKNOWN may become KNOWN when a verified value supports it.
* KNOWN never reverts to UNKNOWN because a later turn omitted the field.
* A student statement becomes a student-origin claim, never verified evidence.
* The result is a freshly validated ProjectState.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from src.schemas.claim import ClaimOrigin, ClaimRecord, ClaimStatus, ClaimType
from src.schemas.common import (
    KnowledgeStatus,
    ProjectType,
    Severity,
    Tracked,
    ValueOrigin,
)
from src.schemas.extraction import (
    RejectionReason,
    TechnicalDomain,
    VerifiedClassification,
    VerifiedExtraction,
    VerifiedField,
)
from src.schemas.finding import ContradictionRecord, ContradictionStatus
from src.graph.state import ProjectState
from src.workflow.errors import (
    WorkflowError,
    WorkflowErrorCode,
    WorkflowErrorReport,
)

# Mapping from extraction field path to the (block, attribute) it updates.
TRACKED_FIELD_TARGETS: dict[str, tuple[str | None, str]] = {
    "project_name": ("identity", "project_name"),
    "problem_statement": ("problem", "statement"),
    "solution_description": ("solution", "description"),
    "architecture_description": ("technical", "architecture"),
    # Phase 1C canonical destinations. These were verified-but-homeless in
    # Phase 1B; a None block means the field sits at the ProjectState root.
    "goal": (None, "goal"),
    "student_contribution": (None, "student_contribution"),
    "current_stage": (None, "current_stage"),
    "prototype_status": ("technical", "prototype_status"),
}
"""Single-valued fields and the Tracked[str] each one owns.

Every intake field now has a semantic owner: nothing verified is dropped, and
nothing is filed under a category it does not belong to.
"""

LIST_FIELD_TARGETS: dict[str, tuple[str, str]] = {
    "beneficiaries": ("problem", "beneficiaries"),
    "claimed_innovation": ("solution", "claimed_innovation"),
    "hardware": ("technical", "hardware"),
    "software": ("technical", "software"),
    "sensors": ("technical", "sensors"),
    "algorithms": ("technical", "algorithms"),
    "datasets": ("technical", "datasets"),
    # A technology is frequently neither software nor hardware (LoRa, Edge
    # Computing, Kalman Filtering, Digital Twin). Phase 1B routed all of them
    # into `software`, which was a lossy misclassification.
    "technologies": ("technical", "technologies"),
    "data_sources": ("technical", "data_sources"),
    "baseline_mentions": ("methodology", "baseline"),
    "metric_mentions": ("methodology", "metrics"),
}
"""List-valued fields. Appended to, never replaced, and de-duplicated."""

UNMAPPED_FIELDS: frozenset[str] = frozenset()
"""Empty since Phase 1C: every verified intake field has a canonical owner."""

CLAIM_TYPE_ALIASES: dict[str, ClaimType] = {member.value: member for member in ClaimType}


@dataclass
class MergeReport:
    """What the merge actually did. Observability, not domain state."""

    applied_fields: list[str] = dataclass_field(default_factory=list)
    conflicted_fields: list[str] = dataclass_field(default_factory=list)
    preserved_fields: list[str] = dataclass_field(default_factory=list)
    appended_values: list[str] = dataclass_field(default_factory=list)
    created_claims: list[str] = dataclass_field(default_factory=list)
    created_contradictions: list[str] = dataclass_field(default_factory=list)
    unmapped_fields: list[str] = dataclass_field(default_factory=list)
    rejected_fields: list[str] = dataclass_field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.applied_fields
            or self.appended_values
            or self.created_claims
            or self.created_contradictions
            or self.conflicted_fields
        )

    def summary(self) -> str:
        return (
            f"applied={len(self.applied_fields)} "
            f"appended={len(self.appended_values)} "
            f"claims={len(self.created_claims)} "
            f"conflicts={len(self.conflicted_fields) + len(self.created_contradictions)} "
            f"preserved={len(self.preserved_fields)} "
            f"rejected={len(self.rejected_fields)}"
        )


def _next_id(existing: list[str], prefix: str, width: int = 3) -> str:
    used = set(existing)
    index = 1
    while f"{prefix}-{index:0{width}d}" in used:
        index += 1
    return f"{prefix}-{index:0{width}d}"


def _anchor_location(verified: VerifiedField) -> str:
    """Provenance recorded on the Tracked value.

    Carries the artifact id, the verification method and the match ranges, so
    "where did this come from?" is answerable from the state alone.
    """
    ranges = ",".join(f"{m.start}:{m.end}" for m in verified.anchor.matches)
    return (
        f"artifact={verified.anchor.artifact_id} "
        f"method={verified.anchor.method.value} "
        f"ranges=[{ranges}]"
    )


def merge_intake_extraction(
    project: ProjectState,
    extraction: VerifiedExtraction,
    *,
    node: str = "MERGE_PROJECT_STATE",
) -> tuple[ProjectState, MergeReport]:
    """Fold a verified extraction into the canonical state.

    Returns a new, fully validated ProjectState and a report of what changed.
    The input state is never mutated.
    """
    updated = project.model_copy(deep=True)
    report = MergeReport()

    report.rejected_fields = [f.field_path for f in extraction.rejected_fields]

    for verified in extraction.accepted_fields:
        path = verified.field_path
        if path in UNMAPPED_FIELDS:
            report.unmapped_fields.append(path)
            continue
        if path in TRACKED_FIELD_TARGETS:
            _merge_tracked_field(updated, verified, report)
        elif path in LIST_FIELD_TARGETS:
            _merge_list_field(updated, verified, report)
        elif path == "identity.domain":
            continue  # classification merge owns this
        else:
            report.unmapped_fields.append(path)

    _merge_claims(updated, extraction, report)
    _merge_conflicts(updated, extraction, report)

    return _revalidate(updated, node), report


def _merge_tracked_field(
    project: ProjectState, verified: VerifiedField, report: MergeReport
) -> None:
    block_name, attribute = TRACKED_FIELD_TARGETS[verified.field_path]
    block = project if block_name is None else getattr(project, block_name)
    current: Tracked[str] = getattr(block, attribute)
    new_value = verified.value

    if current.status is KnowledgeStatus.KNOWN:
        if current.value == new_value:
            report.preserved_fields.append(verified.field_path)
            return
        # A KNOWN value is never silently overwritten. Two supported but
        # different values is a conflict for a human to resolve, not a
        # last-writer-wins update.
        setattr(
            block,
            attribute,
            Tracked[str].conflicted(
                [str(current.value), new_value],
                note=(
                    f"conflicting values for {verified.field_path}; "
                    f"latest from {_anchor_location(verified)}"
                ),
            ),
        )
        report.conflicted_fields.append(verified.field_path)
        _record_field_contradiction(
            project, verified.field_path, str(current.value), new_value, report
        )
        return

    if current.status is KnowledgeStatus.CONFLICTED:
        if new_value not in current.conflicting_values:
            setattr(
                block,
                attribute,
                Tracked[str].conflicted(
                    [*current.conflicting_values, new_value], note=current.note
                ),
            )
            report.conflicted_fields.append(verified.field_path)
        else:
            report.preserved_fields.append(verified.field_path)
        return

    # UNKNOWN or INFERRED_NON_CRITICAL may be promoted by a verified value.
    setattr(
        block,
        attribute,
        Tracked[str].known(
            new_value,
            origin=ValueOrigin.STUDENT_MESSAGE,
            location=_anchor_location(verified),
        ),
    )
    report.applied_fields.append(verified.field_path)


def _record_field_contradiction(
    project: ProjectState,
    field_path: str,
    first: str,
    second: str,
    report: MergeReport,
) -> None:
    """Surface a singleton-field conflict as a reviewable contradiction.

    A CONFLICTED Tracked value records that the disagreement exists; a
    ContradictionRecord is what makes it actionable and blocks finalization
    through the trust gate.
    """
    description = f"Conflicting values for {field_path}."
    if any(c.description == description for c in project.contradictions):
        return
    contradiction_id = _next_id(
        [c.contradiction_id for c in project.contradictions], "CT"
    )
    project.contradictions.append(
        ContradictionRecord(
            contradiction_id=contradiction_id,
            description=description,
            severity=Severity.HIGH,
            status=ContradictionStatus.OPEN,
            conflicting_statements=[first, second],
            requires_student_clarification=True,
        )
    )
    report.created_contradictions.append(contradiction_id)


def _merge_list_field(
    project: ProjectState, verified: VerifiedField, report: MergeReport
) -> None:
    block_name, attribute = LIST_FIELD_TARGETS[verified.field_path]
    block = getattr(project, block_name)
    current: list[str] = list(getattr(block, attribute))

    if verified.value in current:
        report.preserved_fields.append(verified.field_path)
        return

    current.append(verified.value)
    setattr(block, attribute, current)
    report.appended_values.append(f"{verified.field_path}={verified.value}")


def _merge_claims(
    project: ProjectState, extraction: VerifiedExtraction, report: MergeReport
) -> None:
    """Student assertions become student-origin claims, never evidence.

    A performance statement arrives UNSUPPORTED with no evidence_ids, because
    nothing external has verified it. The Phase 0 contract already forbids
    SUPPORTED without evidence; this merge never tries.
    """
    existing_statements = {claim.claim for claim in project.claims}

    for verified in extraction.accepted_claims:
        if verified.statement in existing_statements:
            continue
        claim_id = _next_id([c.claim_id for c in project.claims], "C")
        project.claims.append(
            ClaimRecord(
                claim_id=claim_id,
                claim=verified.statement,
                claim_type=CLAIM_TYPE_ALIASES.get(
                    verified.claim_type.upper(), ClaimType.OTHER
                ),
                origin=ClaimOrigin.STUDENT,
                status=ClaimStatus.UNSUPPORTED,
                evidence_ids=[],
                confidence=0.0,
                source_location=(
                    f"artifact={verified.anchor.artifact_id} "
                    f"method={verified.anchor.method.value}"
                ),
                notes="Student assertion captured at intake, in the student's own "
                "words; not independently verified.",
            )
        )
        existing_statements.add(verified.statement)
        report.created_claims.append(claim_id)


def _merge_conflicts(
    project: ProjectState, extraction: VerifiedExtraction, report: MergeReport
) -> None:
    """Record conflicts the model found inside a single submission."""
    existing = {c.description for c in project.contradictions}

    for verified in extraction.accepted_conflicts:
        description = f"Conflicting statements about {verified.subject}."
        if description in existing:
            continue
        contradiction_id = _next_id(
            [c.contradiction_id for c in project.contradictions], "CT"
        )
        project.contradictions.append(
            ContradictionRecord(
                contradiction_id=contradiction_id,
                description=description,
                severity=Severity.HIGH,
                status=ContradictionStatus.OPEN,
                conflicting_statements=[
                    verified.first_statement,
                    verified.second_statement,
                ],
                requires_student_clarification=True,
            )
        )
        existing.add(description)
        report.created_contradictions.append(contradiction_id)


def merge_classification(
    project: ProjectState,
    classification: VerifiedClassification,
    *,
    node: str = "MERGE_CLASSIFICATION",
) -> tuple[ProjectState, MergeReport]:
    """Fold a verified classification into the canonical state.

    Classification is the one inference permitted at intake, and it touches only
    ``identity.project_type`` and ``identity.domain`` -- never a factual field.
    An already-classified project is not silently reclassified.
    """
    updated = project.model_copy(deep=True)
    report = MergeReport()

    if classification.project_type is not ProjectType.UNKNOWN:
        if updated.identity.project_type is ProjectType.UNKNOWN:
            updated.identity.project_type = classification.project_type
            updated.identity.project_type_confidence = (
                classification.project_type_confidence
            )
            report.applied_fields.append("identity.project_type")
        elif updated.identity.project_type is classification.project_type:
            report.preserved_fields.append("identity.project_type")
        else:
            # Reclassification is a material change; keep the existing value and
            # surface the disagreement rather than flip-flopping.
            report.conflicted_fields.append("identity.project_type")

    # One taxonomy end to end: no projection, no loss (ADR-005).
    current_domains = list(updated.identity.domain)
    for domain in classification.accepted_domains:
        if domain in current_domains:
            continue
        current_domains.append(domain)
        report.appended_values.append(f"identity.domain={domain.value}")
    updated.identity.domain = current_domains

    report.rejected_fields = [
        d.value for d in classification.domains if not d.accepted
    ]

    return _revalidate(updated, node), report


def _revalidate(project: ProjectState, node: str) -> ProjectState:
    """Full re-validation. A merge can never leave an invalid canonical state."""
    try:
        return ProjectState.model_validate(project.model_dump())
    except ValueError as exc:
        raise WorkflowErrorReport(
            WorkflowError(
                code=WorkflowErrorCode.STATE_VALIDATION_FAILED,
                node=node,
                message=(
                    "merging intake output produced an invalid ProjectState: "
                    f"{str(exc).splitlines()[0]}"
                ),
                recoverable=False,
            )
        ) from exc
