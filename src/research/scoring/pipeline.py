"""Phase 2F orchestration: assessment -> traces -> channels -> scorecard.

Wholly deterministic and free of I/O, so the same Phase 2E state always
produces the same scorecards. The graph nodes in ``src/graph/scoring_nodes.py``
call ``score_claim`` and recompute rather than thread intermediate values, which
is what makes an interrupted node replay-safe (ADR-002).

The one input rule worth stating here: Phase 2F consumes only a **trusted,
terminal** Phase 2E run. A sufficiency pass that stopped early, or one whose
alignment universe was incomplete, is a not-ready outcome and never a scoring
pass over state nobody examined (section 5, section 27).
"""

from __future__ import annotations

from uuid import UUID

from src.research.scoring.fingerprint import scoring_input_digest
from src.research.scoring.policy import (
    channel_reasons,
    component_trace,
    decide_disposition,
    directional_score,
    final_support_index_bp,
)
from src.research.scoring.reliability import build_reliability_profile
from src.schemas.claim_evidence_score import (
    ClaimEvidenceScoreCard,
    ClaimEvidenceScoringRun,
    ClaimScoringStatus,
    ScoreDirection,
    ScoreDisposition,
    ScoreReasonCode,
    ScoringCoverage,
    scorecard_id_for,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyAssessment,
    ClaimSufficiencyRun,
    ClaimSufficiencyStatus,
    EvidenceWeightProfile,
)

READY_SUFFICIENCY_STATUSES: frozenset[ClaimSufficiencyStatus] = frozenset(
    {ClaimSufficiencyStatus.COMPLETED}
)
"""Only a ``COMPLETED`` Phase 2E run yields scorecards.

Every other terminal status means the sufficiency pass stopped before it had
assessments to score, and ``NOT_READY`` is a far more useful thing to report
than a confident ``0`` (section 27)."""


def readiness(sufficiency: ClaimSufficiencyRun | None) -> ClaimScoringStatus | None:
    """The not-ready status for this input, or ``None`` when scoring may proceed.

    Mirrors Phase 2E's own ``readiness`` over Phase 2D: the shapes are checked
    once, here, so no node has to guess whether its input is trustworthy.
    """
    if sufficiency is None:
        return ClaimScoringStatus.NOT_READY
    if sufficiency.status not in READY_SUFFICIENCY_STATUSES:
        return ClaimScoringStatus.NOT_READY
    if not sufficiency.assessments:
        return ClaimScoringStatus.NO_SUFFICIENCY_ASSESSMENTS
    return None


def profiles_for_claim(
    assessment: ClaimSufficiencyAssessment,
    profiles: list[EvidenceWeightProfile],
) -> list[EvidenceWeightProfile]:
    """This claim's Phase 2E profiles, taken by id from the assessment.

    Filtered on ``assessment.profile_ids`` rather than on ``claim_id`` alone:
    the assessment is the record of what actually contributed to that verdict,
    and scoring anything it did not reference would score evidence Phase 2E did
    not weigh.
    """
    wanted = set(assessment.profile_ids)
    return [p for p in profiles if p.profile_id in wanted]


def score_claim(
    assessment: ClaimSufficiencyAssessment,
    profiles: list[EvidenceWeightProfile],
    *,
    scoring_run_id: UUID,
    research_run_id: UUID,
    input_ready: bool = True,
) -> ClaimEvidenceScoreCard:
    """The full Phase 2F pass for ONE claim.

    Cross-run and cross-claim isolation are enforced before anything is
    computed (section 23, section 24): the same evidence may score differently
    against different claims because alignment is claim-specific, and an
    assessment from another run has no business reaching this claim's card.
    """
    if assessment.research_run_id != research_run_id:
        raise ValueError(
            "the sufficiency assessment belongs to a different research run; "
            "cross-run scoring is refused (section 24)"
        )
    claim_profiles = profiles_for_claim(assessment, profiles)
    if any(p.claim_id != assessment.claim_id for p in claim_profiles):
        raise ValueError(
            "a weight profile belongs to a different claim; an evidence "
            "contribution is claim-specific and never global (section 23)"
        )

    traces = [
        component_trace(assessment.claim_id, component)
        for component in sorted(
            assessment.components, key=lambda c: (c.anchor_start, c.anchor_end)
        )
    ]
    support = directional_score(ScoreDirection.SUPPORT, traces)
    contradiction = directional_score(ScoreDirection.CONTRADICTION, traces)
    reliability = build_reliability_profile(assessment, claim_profiles)
    disposition, withheld = decide_disposition(
        assessment, support, contradiction, input_ready=input_ready
    )

    reasons: list[ScoreReasonCode] = []
    reasons.extend(channel_reasons(ScoreDirection.SUPPORT, support))
    reasons.extend(channel_reasons(ScoreDirection.CONTRADICTION, contradiction))
    if contradiction.covered_components or contradiction.contributing_group_ids:
        reasons.append(ScoreReasonCode.CONTRADICTION_PRESENT)
    if assessment.unexamined_component_count:
        reasons.append(
            ScoreReasonCode.UNEXAMINED_MATERIAL_COMPONENT_IN_DENOMINATOR
        )
    if _duplicates_collapsed(claim_profiles):
        reasons.append(ScoreReasonCode.DUPLICATE_SOURCE_COLLAPSED)
    if _excerpts_collapsed(claim_profiles):
        reasons.append(ScoreReasonCode.DUPLICATE_EXCERPT_COLLAPSED)
    for trace in traces:
        reasons.extend(trace.reason_codes)
    reasons.extend(reliability.reason_codes)

    return ClaimEvidenceScoreCard(
        scorecard_id=scorecard_id_for(scoring_run_id, assessment.claim_id),
        research_run_id=research_run_id,
        scoring_run_id=scoring_run_id,
        sufficiency_run_id=assessment.sufficiency_run_id,
        assessment_id=assessment.assessment_id,
        claim_id=assessment.claim_id,
        sufficiency_outcome=assessment.outcome,
        inventory_completeness=assessment.inventory_completeness,
        support=support,
        contradiction=contradiction,
        component_traces=traces,
        reliability=reliability,
        disposition=disposition,
        final_support_index_bp=final_support_index_bp(disposition, support),
        reason_codes=list(dict.fromkeys(reasons)),
        withheld_reasons=list(dict.fromkeys(withheld)),
        unexamined_component_count=assessment.unexamined_component_count,
        input_fingerprint=scoring_input_digest(assessment, claim_profiles),
    )


def _duplicates_collapsed(profiles: list[EvidenceWeightProfile]) -> bool:
    """True when two source records or providers resolved to one group.

    Reported as a reason code so the collapse is visible in the card: it is
    exactly the corroboration inflation that did *not* happen.
    """
    identities = {p.canonical_identity for p in profiles}
    sources = {p.source_id for p in profiles}
    return len(sources) > len(identities)


def _excerpts_collapsed(profiles: list[EvidenceWeightProfile]) -> bool:
    """True when one independence group contributed more than one excerpt."""
    groups = [p.independence_group_id for p in profiles]
    return len(groups) > len(set(groups))


def score_assessments(
    sufficiency: ClaimSufficiencyRun,
    *,
    scoring_run_id: UUID,
    research_run_id: UUID,
) -> list[ClaimEvidenceScoreCard]:
    """Score every assessment in a trusted Phase 2E run, in claim order.

    Deterministic ordering by ``claim_id``, so two runs over the same state
    serialize identically (section 25).
    """
    profiles = list(sufficiency.weight_profiles)
    input_ready = sufficiency.alignment_universe_complete
    return [
        score_claim(
            assessment,
            profiles,
            scoring_run_id=scoring_run_id,
            research_run_id=research_run_id,
            input_ready=input_ready,
        )
        for assessment in sorted(
            sufficiency.assessments, key=lambda a: a.claim_id
        )
    ]


def build_coverage(
    *,
    claims_total: int,
    assessments_total: int,
    scorecards: list[ClaimEvidenceScoreCard],
) -> ScoringCoverage:
    """Operational counters for one pass."""
    issued = sum(1 for c in scorecards if not c.scalar_withheld)
    disposition_counts: dict[str, int] = {}
    reliability_counts: dict[str, int] = {}
    for card in scorecards:
        disposition_counts[card.disposition.value] = (
            disposition_counts.get(card.disposition.value, 0) + 1
        )
        key = card.reliability.posture.value
        reliability_counts[key] = reliability_counts.get(key, 0) + 1
    return ScoringCoverage(
        claims_total=claims_total,
        assessments_total=assessments_total,
        scorecards_total=len(scorecards),
        scalars_issued=issued,
        scalars_withheld=len(scorecards) - issued,
        components_scored=sum(len(c.component_traces) for c in scorecards),
        unexamined_components_total=sum(
            c.unexamined_component_count for c in scorecards
        ),
        contested_total=sum(
            1
            for c in scorecards
            if c.disposition is ScoreDisposition.CONTESTED_SCALAR_WITHHELD
        ),
        blocked_source_quality_total=sum(
            1
            for c in scorecards
            if c.disposition
            is ScoreDisposition.BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD
        ),
        incomplete_input_total=sum(
            1
            for c in scorecards
            if c.disposition is ScoreDisposition.INCOMPLETE_INPUT_SCALAR_WITHHELD
        ),
        disposition_counts=dict(sorted(disposition_counts.items())),
        reliability_counts=dict(sorted(reliability_counts.items())),
    )


def decide_status(scorecards: list[ClaimEvidenceScoreCard]) -> ClaimScoringStatus:
    """The terminal status of a pass that reached scoring."""
    if not scorecards:
        return ClaimScoringStatus.NO_SCORABLE_CLAIMS
    return ClaimScoringStatus.COMPLETED


__all__ = [
    "READY_SUFFICIENCY_STATUSES",
    "build_coverage",
    "decide_status",
    "profiles_for_claim",
    "readiness",
    "score_assessments",
    "score_claim",
]
