"""Turn an untrusted ``ProjectExtraction`` into a ``VerifiedExtraction``.

Every candidate field is put through the same gate: the excerpt must occur in
the artifact, and the excerpt must actually state the value. Rejections are
recorded with a reason rather than dropped, so "the model proposed X and we
refused it" stays observable.
"""

from __future__ import annotations

from src.intake.anchors import value_supported_by_anchor, verify_anchor
from src.schemas.extraction import (
    DomainAssignment,
    ExtractedClaim,
    ExtractedConflict,
    ExtractedValue,
    FieldKind,
    ProjectClassification,
    ProjectExtraction,
    RejectionReason,
    TechnicalDomain,
    VerifiedClaim,
    VerifiedClassification,
    VerifiedConflict,
    VerifiedExtraction,
    VerifiedField,
)
from src.schemas.common import ProjectType
from src.schemas.extraction import MAX_RATIONALE_LENGTH
from src.schemas.submission import StudentSubmissionArtifact

ACCEPTED_EXTRACTION_MODES: frozenset[FieldKind] = frozenset(
    {FieldKind.VERBATIM_SPAN, FieldKind.VERBATIM_TERM}
)
"""Modes a canonical factual field may be extracted under.

CLASSIFICATION and STUDENT_CLAIM have their own paths; a factual field arriving
under either is rejected rather than quietly reinterpreted.
"""

SINGLE_VALUE_FIELDS: dict[str, FieldKind] = {
    "project_name": FieldKind.VERBATIM_TERM,
    "problem_statement": FieldKind.VERBATIM_SPAN,
    "solution_description": FieldKind.VERBATIM_SPAN,
    "goal": FieldKind.VERBATIM_SPAN,
    "architecture_description": FieldKind.VERBATIM_SPAN,
    "student_contribution": FieldKind.VERBATIM_SPAN,
    "current_stage": FieldKind.VERBATIM_SPAN,
    "prototype_status": FieldKind.VERBATIM_SPAN,
}
"""Single-valued intake fields and the extraction mode each is governed by.

Every factual narrative field is VERBATIM_SPAN (ADR-004): its canonical value is
the verified source span, not the model's summary. Phase 1B treated these as
free narrative, which left room for a subtly wrong paraphrase anchored to a real
passage.
"""

LIST_VALUE_FIELDS: dict[str, FieldKind] = {
    "beneficiaries": FieldKind.VERBATIM_SPAN,
    "claimed_innovation": FieldKind.VERBATIM_SPAN,
    "technologies": FieldKind.VERBATIM_TERM,
    "hardware": FieldKind.VERBATIM_TERM,
    "software": FieldKind.VERBATIM_TERM,
    "sensors": FieldKind.VERBATIM_TERM,
    "algorithms": FieldKind.VERBATIM_TERM,
    "datasets": FieldKind.VERBATIM_TERM,
    "data_sources": FieldKind.VERBATIM_TERM,
    "baseline_mentions": FieldKind.VERBATIM_TERM,
    "metric_mentions": FieldKind.VERBATIM_TERM,
}
"""List-valued intake fields.

Concrete named things are VERBATIM_TERM so a value the excerpt does not name is
rejected. Beneficiaries and claimed innovations are stated in prose, so they are
VERBATIM_SPAN: the student's wording is kept rather than the model's.
"""

ALL_EXTRACTION_FIELDS: dict[str, FieldKind] = {
    **SINGLE_VALUE_FIELDS,
    **LIST_VALUE_FIELDS,
}


def _clamp_confidence(value: float) -> float | None:
    """Keep an out-of-range model confidence from breaking the contract.

    A model reporting 1.7 is reporting nonsense; the value is dropped rather
    than clipped into a number that looks meaningful.
    """
    return value if 0.0 <= value <= 1.0 else None


def _verify_value(
    artifact: StudentSubmissionArtifact,
    field_path: str,
    candidate: ExtractedValue,
    kind: FieldKind,
) -> VerifiedField:
    """Apply the full gate to one candidate value.

    For a VERBATIM_SPAN field the accepted canonical value is the **verified
    excerpt**, not the model's paraphrase. The paraphrase is retained as
    ``model_summary`` -- derived metadata, clearly labelled, never canonical
    (ADR-004). This is what closes the Phase 1B gap where a subtly wrong summary
    could ride in on a genuine anchor.
    """
    anchor = verify_anchor(artifact.artifact_id, artifact.original_text, candidate.excerpt)
    confidence = _clamp_confidence(candidate.confidence)

    def reject(reason: RejectionReason) -> VerifiedField:
        return VerifiedField(
            field_path=field_path,
            value=candidate.value,
            model_summary=candidate.value,
            kind=kind,
            anchor=anchor,
            accepted=False,
            rejection_reason=reason,
            model_confidence=confidence,
        )

    if kind not in ACCEPTED_EXTRACTION_MODES:
        return reject(RejectionReason.UNSUPPORTED_EXTRACTION_MODE)
    if not candidate.value.strip():
        return reject(RejectionReason.EMPTY_VALUE)
    if not candidate.excerpt.strip():
        return reject(RejectionReason.EMPTY_EXCERPT)
    if not anchor.verified:
        return reject(RejectionReason.ANCHOR_NOT_FOUND)
    if not value_supported_by_anchor(candidate.value, candidate.excerpt, kind):
        return reject(RejectionReason.VALUE_NOT_SUPPORTED_BY_ANCHOR)

    if kind is FieldKind.VERBATIM_SPAN:
        # The source span is the fact. The model only located it.
        canonical_value = candidate.excerpt.strip()
        summary = candidate.value if candidate.value != canonical_value else None
    else:
        canonical_value = candidate.value
        summary = None

    return VerifiedField(
        field_path=field_path,
        value=canonical_value,
        model_summary=summary,
        kind=kind,
        anchor=anchor,
        accepted=True,
        model_confidence=confidence,
    )


def verify_extraction(
    artifact: StudentSubmissionArtifact, extraction: ProjectExtraction
) -> VerifiedExtraction:
    """Verify every candidate in an extraction against the artifact."""
    fields: list[VerifiedField] = []

    for field_path, kind in SINGLE_VALUE_FIELDS.items():
        candidate = getattr(extraction, field_path)
        if candidate is not None:
            fields.append(_verify_value(artifact, field_path, candidate, kind))

    for field_path, kind in LIST_VALUE_FIELDS.items():
        for candidate in getattr(extraction, field_path):
            fields.append(_verify_value(artifact, field_path, candidate, kind))

    claims = [_verify_claim(artifact, claim) for claim in extraction.result_claims]
    conflicts = [
        _verify_conflict(artifact, conflict) for conflict in extraction.conflicts
    ]

    return VerifiedExtraction(
        artifact_id=artifact.artifact_id,
        fields=fields,
        claims=claims,
        conflicts=conflicts,
    )


def _verify_claim(
    artifact: StudentSubmissionArtifact, candidate: ExtractedClaim
) -> VerifiedClaim:
    """A claim is recorded in the student's own words.

    The canonical statement is the verified excerpt, not the model's rendering
    of it (ADR-004) -- attributing a paraphrase to the student would misquote
    them. The claim remains an assertion, never evidence.
    """
    anchor = verify_anchor(artifact.artifact_id, artifact.original_text, candidate.excerpt)

    if not candidate.statement.strip():
        reason = RejectionReason.EMPTY_VALUE
    elif not candidate.excerpt.strip():
        reason = RejectionReason.EMPTY_EXCERPT
    elif not anchor.verified:
        reason = RejectionReason.ANCHOR_NOT_FOUND
    else:
        reason = None

    statement = (
        candidate.excerpt.strip()
        if reason is None
        else (candidate.statement or "(empty)")
    )
    return VerifiedClaim(
        statement=statement,
        claim_type=candidate.claim_type,
        anchor=anchor,
        accepted=reason is None,
        rejection_reason=reason,
        model_summary=candidate.statement,
    )


def _verify_conflict(
    artifact: StudentSubmissionArtifact, candidate: ExtractedConflict
) -> VerifiedConflict:
    """Both sides of a conflict must be anchored, or the conflict is not real."""
    first = verify_anchor(
        artifact.artifact_id, artifact.original_text, candidate.first_excerpt
    )
    second = verify_anchor(
        artifact.artifact_id, artifact.original_text, candidate.second_excerpt
    )
    accepted = first.verified and second.verified
    return VerifiedConflict(
        subject=candidate.subject or "(unspecified)",
        first_statement=candidate.first_statement,
        second_statement=candidate.second_statement,
        first_anchor=first,
        second_anchor=second,
        accepted=accepted,
        rejection_reason=None if accepted else RejectionReason.ANCHOR_NOT_FOUND,
    )


def verify_classification(
    artifact: StudentSubmissionArtifact, classification: ProjectClassification
) -> VerifiedClassification:
    """Verify a classification's supporting anchors.

    A project type whose excerpt does not verify falls back to UNKNOWN. The
    classifier does not get to assert a type on its own authority, even though
    classification is the one place where inference is permitted at all.
    """
    project_type = classification.project_type
    confidence = _clamp_confidence(classification.project_type_confidence)
    type_anchor = None

    if project_type is not ProjectType.UNKNOWN:
        type_anchor = verify_anchor(
            artifact.artifact_id,
            artifact.original_text,
            classification.project_type_excerpt,
        )
        if not type_anchor.verified:
            project_type = ProjectType.UNKNOWN
            confidence = None
            type_anchor = None

    if project_type is ProjectType.UNKNOWN:
        confidence = None

    domains = [
        _verify_domain(artifact, assignment) for assignment in classification.domains
    ]

    rationale = classification.rationale.strip()[:MAX_RATIONALE_LENGTH]

    return VerifiedClassification(
        artifact_id=artifact.artifact_id,
        project_type=project_type,
        project_type_confidence=confidence,
        type_anchor=type_anchor,
        rationale=rationale,
        domains=domains,
    )


def _verify_domain(
    artifact: StudentSubmissionArtifact, assignment: DomainAssignment
) -> VerifiedField:
    """A domain is an inference, so only its anchor must verify.

    The domain label itself will never appear verbatim ("COMPUTER_VISION" is not
    something a student writes), so containment is not applicable -- this is the
    INFERRED_NON_CRITICAL path, and it is confined to classification.
    """
    anchor = verify_anchor(
        artifact.artifact_id, artifact.original_text, assignment.excerpt
    )
    confidence = _clamp_confidence(assignment.confidence)

    accepted = anchor.verified and assignment.domain is not TechnicalDomain.UNKNOWN
    return VerifiedField(
        field_path="identity.domain",
        value=assignment.domain.value,
        kind=FieldKind.CLASSIFICATION,
        anchor=anchor,
        accepted=accepted,
        rejection_reason=None if accepted else RejectionReason.ANCHOR_NOT_FOUND,
        model_confidence=confidence,
    )
