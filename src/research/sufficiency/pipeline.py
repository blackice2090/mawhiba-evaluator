"""Phase 2E orchestration: groups -> profiles -> coverage -> assessments.

Wholly deterministic. Given the same claims, the same Phase 2C evidence, the
same Phase 2D alignments and the same Phase 2B logical sources, this module
produces equivalent output every time -- which is what makes the idempotency
and checkpoint-resume guarantees checkable rather than hopeful (section 24).

There is no model provider parameter anywhere in this module, and that is the
architectural decision, not an omission (section 16): every judgement Phase 2E
makes follows from structured Phase 2D output plus trusted metadata, so adding
an LLM would add a trust boundary with nothing behind it to decide.

Phase 2E.1 added the claim-component inventory step. The material component set
is now derived from each claim's own text and verified against it, so a material
part of a compound claim that no Phase 2D alignment anchored stays in the
sufficiency denominator instead of disappearing from it (ADR-016). That step is
deterministic too, and deliberately so: see
``src.research.sufficiency.inventory`` for why choosing cut points needs no
model call and what granularity that costs.
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import (
    ClaimAlignmentStatus,
    ClaimEvidenceAlignment,
    ClaimEvidenceAlignmentRun,
)
from src.schemas.claim_component_inventory import ClaimComponentInventory
from src.schemas.claim_sufficiency import (
    ClaimComponentSufficiency,
    ClaimSufficiencyAssessment,
    ClaimSufficiencyStatus,
    EvidenceContributionClass,
    EvidenceWeightProfile,
    IndependenceGroup,
    MAX_AUDIT_RATIONALE_CHARS,
    PublicationStatus,
    RetractionStatus,
    SufficiencyCoverage,
    SufficiencyOutcome,
    TraceabilityStatus,
    assessment_id_for,
)
from src.research.sufficiency.identity import build_independence_groups
from src.research.sufficiency.inventory import build_inventory
from src.research.sufficiency.policy import (
    aggregate_limitations,
    aggregate_unknowns,
    alignment_anchor_keys,
    component_sufficiency,
    content_scope_ceiling,
    decide_outcome,
    material_components,
)
from src.research.sufficiency.profiles import build_weight_profile
from src.schemas.academic import LogicalAcademicSource
from src.schemas.evidence_extraction import ExtractedEvidence

READY_ALIGNMENT_STATUSES: frozenset[ClaimAlignmentStatus] = frozenset(
    {ClaimAlignmentStatus.COMPLETED}
)
"""Only a COMPLETED Phase 2D run yields assessments.

``PARTIAL`` means some required pair was never classified, so the alignment
universe is incomplete and sufficiency over it would be a claim about evidence
that was never examined (section 27). ``BLOCKED_PAIR_LIMIT_EXCEEDED`` is the
same problem with a different cause. Both are reported as
``BLOCKED_ALIGNMENT_INCOMPLETE`` rather than quietly assessed.
"""

INCOMPLETE_ALIGNMENT_STATUSES: frozenset[ClaimAlignmentStatus] = frozenset(
    {
        ClaimAlignmentStatus.PARTIAL,
        ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED,
    }
)

EMPTY_ALIGNMENT_STATUSES: frozenset[ClaimAlignmentStatus] = frozenset(
    {
        ClaimAlignmentStatus.NO_ALIGNABLE_CLAIMS,
        ClaimAlignmentStatus.NO_ALIGNABLE_EVIDENCE,
    }
)


def readiness(
    alignment: ClaimEvidenceAlignmentRun | None,
) -> ClaimSufficiencyStatus | None:
    """The not-ready status for this Phase 2D run, or ``None`` when ready.

    Each cause keeps its own status. "Phase 2D never finished" and "Phase 2D
    finished and found no relationship" are different facts about a project, and
    collapsing them would let a pipeline failure read as an evidence finding.
    """
    if alignment is None or not alignment.is_terminal:
        return ClaimSufficiencyStatus.NOT_READY
    if alignment.status in INCOMPLETE_ALIGNMENT_STATUSES:
        return ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE
    if alignment.status in EMPTY_ALIGNMENT_STATUSES:
        return ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS
    if alignment.status not in READY_ALIGNMENT_STATUSES:
        return ClaimSufficiencyStatus.NOT_READY
    if not alignment.alignments:
        return ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS
    return None


def _audit_rationale(
    outcome: SufficiencyOutcome,
    components: list[ClaimComponentSufficiency],
    profiles: list[EvidenceWeightProfile],
    supporting: int,
    contradicting: int,
    inventory: ClaimComponentInventory,
) -> str:
    """Template text assembled from the structured facts, never model prose."""
    adequate = sum(1 for c in components if c.is_adequately_evidenced)
    eligible = sum(1 for p in profiles if p.is_eligible)
    disqualified = sum(
        1
        for p in profiles
        if p.contribution
        in (
            EvidenceContributionClass.DISQUALIFIED_RETRACTED,
            EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE,
        )
    )
    unexamined = len(inventory.unanchored_components)
    text = (
        f"{outcome.value} under SUFFICIENCY-POLICY-V1: "
        f"component inventory {inventory.completeness.value}; "
        f"{adequate}/{len(components)} material component(s) adequately "
        f"evidenced, {unexamined} unexamined by any alignment anchor; "
        f"{supporting} independent supporting group(s), "
        f"{contradicting} independent contradicting group(s); "
        f"{eligible} eligible and {disqualified} disqualified evidence item(s) "
        f"across {len(profiles)} aligned item(s). "
        "Policy-based evidence posture, not universal scientific proof, and not "
        "a claim status, score or trust verdict."
    )
    return text[:MAX_AUDIT_RATIONALE_CHARS]


def assess_claim(
    claim: ClaimRecord,
    alignments: list[ClaimEvidenceAlignment],
    evidence_index: dict[UUID, ExtractedEvidence],
    group_index: dict[UUID, IndependenceGroup],
    evidence_to_group: dict[UUID, UUID],
    *,
    research_run_id: UUID,
    sufficiency_run_id: UUID,
    alignment_run_id: UUID | None,
    universe_complete: bool = True,
) -> tuple[ClaimSufficiencyAssessment, list[EvidenceWeightProfile]]:
    """One claim's assessment, from that claim's alignments only.

    Cross-claim isolation is structural here (section 22): the only alignments
    this function can see are the ones the caller filtered to this claim, and
    nothing about another claim's outcome is an input. The same evidence item
    can therefore be ``SUPPORTS`` for one claim and ``NOT_RELEVANT`` for another
    without the two interfering.
    """
    profiles: list[EvidenceWeightProfile] = []
    seen_pairs: set[tuple[str, UUID]] = set()
    for alignment in alignments:
        pair = (alignment.claim_id, alignment.evidence_id)
        if pair in seen_pairs:
            # Phase 2D already forbids two alignments per pair; refusing again
            # here keeps a hand-built or replayed run from duplicating profiles.
            continue
        seen_pairs.add(pair)
        evidence = evidence_index.get(alignment.evidence_id)
        group_id = evidence_to_group.get(alignment.evidence_id)
        group = group_index.get(group_id) if group_id is not None else None
        profiles.append(
            build_weight_profile(
                alignment,
                claim,
                evidence,
                group,
                research_run_id=research_run_id,
                sufficiency_run_id=sufficiency_run_id,
                alignment_run_id=alignment_run_id,
            )
        )

    # The material component set is derived from the claim's own text, with the
    # Phase 2D anchors only choosing where the partition is cut. That is the
    # Phase 2E.1 fix: an unanchored material part of the claim is a component
    # here, so it stays in the denominator instead of disappearing (ADR-016).
    inventory = build_inventory(
        claim, alignment_anchor_keys(profiles), claim_id=claim.claim_id
    )
    components = [
        component_sufficiency(claim.claim_id, component, profiles)
        for component in material_components(inventory)
    ]
    outcome, blockers, reasons = decide_outcome(
        components, profiles, inventory, universe_complete=universe_complete
    )

    supporting = sorted(
        {
            group
            for component in components
            for group in component.supporting_group_ids
        },
        key=str,
    )
    contradicting = sorted(
        {
            group
            for component in components
            for group in component.contradicting_group_ids
        },
        key=str,
    )
    contextual = sorted(
        {
            p.independence_group_id
            for p in profiles
            if p.contribution is EvidenceContributionClass.CONTEXT_ONLY
        },
        key=str,
    )
    insufficient = sorted(
        {
            p.independence_group_id
            for p in profiles
            if p.contribution is EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT
        },
        key=str,
    )
    disqualified = sorted(
        {
            p.independence_group_id
            for p in profiles
            if p.contribution
            in (
                EvidenceContributionClass.DISQUALIFIED_RETRACTED,
                EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE,
            )
            and p.independence_group_id in group_index
        },
        key=str,
    )
    all_groups = sorted(
        {p.independence_group_id for p in profiles if p.independence_group_id in group_index},
        key=str,
    )

    assessment = ClaimSufficiencyAssessment(
        assessment_id=assessment_id_for(sufficiency_run_id, claim.claim_id),
        research_run_id=research_run_id,
        sufficiency_run_id=sufficiency_run_id,
        claim_id=claim.claim_id,
        outcome=outcome,
        component_inventory=inventory,
        components=components,
        profile_ids=[p.profile_id for p in profiles],
        independence_group_ids=all_groups,
        supporting_group_ids=supporting,
        contradicting_group_ids=contradicting,
        contextual_group_ids=contextual,
        insufficient_group_ids=insufficient,
        disqualified_group_ids=disqualified,
        blockers=blockers,
        reason_codes=reasons,
        unknown_dimensions=aggregate_unknowns(profiles),
        limitations=aggregate_limitations(profiles),
        content_scope_ceiling=content_scope_ceiling(profiles),
        audit_rationale=_audit_rationale(
            outcome,
            components,
            profiles,
            len(supporting),
            len(contradicting),
            inventory,
        ),
    )
    return assessment, profiles


def assess_claims(
    claims: list[ClaimRecord],
    alignment: ClaimEvidenceAlignmentRun,
    evidence_items: list[ExtractedEvidence],
    logical_sources: list[LogicalAcademicSource],
    *,
    research_run_id: UUID,
    sufficiency_run_id: UUID,
) -> tuple[
    list[IndependenceGroup], list[EvidenceWeightProfile], list[ClaimSufficiencyAssessment]
]:
    """Run the whole deterministic pass for every claim with an alignment.

    A claim with no verified alignment gets no assessment. That is deliberate:
    an assessment asserts that evidence was examined for that claim, and
    manufacturing ``NO_DIRECT_EVIDENCE`` records for claims Phase 2D never
    reached would say the wrong thing.
    """
    groups, evidence_to_group = build_independence_groups(
        research_run_id, evidence_items, logical_sources
    )
    group_index = {g.independence_group_id: g for g in groups}
    evidence_index = {
        e.evidence_id: e for e in evidence_items if e.research_run_id == research_run_id
    }
    universe_complete = alignment.status in READY_ALIGNMENT_STATUSES

    assessments: list[ClaimSufficiencyAssessment] = []
    profiles: list[EvidenceWeightProfile] = []
    for claim in claims:
        claim_alignments = alignment.alignments_for_claim(claim.claim_id)
        if not claim_alignments:
            continue
        assessment, claim_profiles = assess_claim(
            claim,
            claim_alignments,
            evidence_index,
            group_index,
            evidence_to_group,
            research_run_id=research_run_id,
            sufficiency_run_id=sufficiency_run_id,
            alignment_run_id=alignment.alignment_run_id,
            universe_complete=universe_complete,
        )
        assessments.append(assessment)
        profiles.extend(claim_profiles)
    return groups, profiles, assessments


def build_coverage(
    *,
    claims_total: int,
    accepted_evidence_total: int,
    verified_alignments_total: int,
    groups: list[IndependenceGroup],
    profiles: list[EvidenceWeightProfile],
    assessments: list[ClaimSufficiencyAssessment],
) -> SufficiencyCoverage:
    """Operational counters. Describes execution, never project quality."""
    evidence_items = {e for g in groups for e in g.member_evidence_ids}
    outcome_counts: dict[str, int] = {}
    for assessment in assessments:
        outcome_counts[assessment.outcome.value] = (
            outcome_counts.get(assessment.outcome.value, 0) + 1
        )
    contribution_counts: dict[str, int] = {}
    for profile in profiles:
        contribution_counts[profile.contribution.value] = (
            contribution_counts.get(profile.contribution.value, 0) + 1
        )
    return SufficiencyCoverage(
        claims_total=claims_total,
        claims_assessed=len(assessments),
        accepted_evidence_total=accepted_evidence_total,
        verified_alignments_total=verified_alignments_total,
        evidence_items_total=len(evidence_items),
        independence_groups_total=len(groups),
        duplicate_evidence_collapsed=max(len(evidence_items) - len(groups), 0),
        profiles_total=len(profiles),
        disqualified_profiles_total=sum(
            1
            for p in profiles
            if p.contribution
            in (
                EvidenceContributionClass.DISQUALIFIED_RETRACTED,
                EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE,
            )
        ),
        retracted_profiles_total=sum(
            1 for p in profiles if p.retraction_status is RetractionStatus.RETRACTED
        ),
        untraceable_profiles_total=sum(
            1 for p in profiles if p.traceability is not TraceabilityStatus.TRACEABLE
        ),
        preprint_profiles_total=sum(
            1 for p in profiles if p.publication_status is PublicationStatus.PREPRINT
        ),
        abstract_only_profiles_total=sum(
            1 for p in profiles if p.content_scope.value == "ABSTRACT_ONLY"
        ),
        unknown_retraction_profiles_total=sum(
            1 for p in profiles if p.retraction_status is RetractionStatus.UNKNOWN
        ),
        unknown_publication_profiles_total=sum(
            1 for p in profiles if p.publication_status is PublicationStatus.UNKNOWN
        ),
        outcome_counts=outcome_counts,
        contribution_counts=contribution_counts,
    )


def decide_status(
    assessments: list[ClaimSufficiencyAssessment],
) -> ClaimSufficiencyStatus:
    """The terminal status of a pass that got as far as assessing.

    ``COMPLETED`` describes execution only. A completed pass whose every claim
    is ``NO_DIRECT_EVIDENCE`` ran perfectly and found nothing, and those two
    facts must stay separately readable.
    """
    if not assessments:
        return ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS
    return ClaimSufficiencyStatus.COMPLETED


__all__ = [
    "EMPTY_ALIGNMENT_STATUSES",
    "INCOMPLETE_ALIGNMENT_STATUSES",
    "READY_ALIGNMENT_STATUSES",
    "assess_claim",
    "assess_claims",
    "build_coverage",
    "decide_status",
    "readiness",
]
