"""Candidate -> verified alignment, and the coverage that describes the pass.

The order of checks mirrors ``src/research/evidence/pipeline.py``, each with
its own named reason (section 13):

    the claim and evidence both exist and are eligible -> UNKNOWN_*, EVIDENCE_*
    every proposed anchor exists in the claim text     -> FABRICATED_ANCHOR
    the pair-level relation matches its components     -> STRUCTURALLY_INCONSISTENT
    the pair has not already been decided differently  -> DUPLICATE_INCOMPATIBLE_PAIR

Verification success means the candidate is structurally and provenance-valid.
It never means the underlying scientific claim is proven (section 13, 23).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.research.alignment.verification import resolve_anchor
from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import (
    ALIGNMENT_VERIFIER_VERSION,
    AlignmentCandidate,
    AlignmentCoverage,
    AlignmentRejectionReason,
    ClaimAlignmentStatus,
    ClaimComponentAnchor,
    ClaimEvidenceAlignment,
    ComponentAlignmentJudgment,
    RejectedAlignmentCandidate,
    relation_is_consistent,
)
from src.schemas.evidence_extraction import EXTRACTABLE_CONTENT_KINDS, ExtractedEvidence


@dataclass
class VerificationOutcome:
    alignments: list[ClaimEvidenceAlignment] = field(default_factory=list)
    rejected: list[RejectedAlignmentCandidate] = field(default_factory=list)


def _reject(
    candidate: AlignmentCandidate,
    reason: AlignmentRejectionReason,
    summary: str = "",
) -> RejectedAlignmentCandidate:
    return RejectedAlignmentCandidate(
        candidate_id=candidate.candidate_id,
        claim_id=candidate.claim_id,
        evidence_id=candidate.evidence_id,
        reason=reason,
        safe_summary=summary[:200],
        verifier_version=ALIGNMENT_VERIFIER_VERSION,
    )


def verify_candidate(
    candidate: AlignmentCandidate,
    claims: dict[str, ClaimRecord],
    evidence_by_id: dict[UUID, ExtractedEvidence],
    *,
    research_run_id: UUID,
    alignment_run_id: UUID,
    accepted_keys: dict[tuple[str, str], ClaimEvidenceAlignment],
) -> tuple[ClaimEvidenceAlignment | None, RejectedAlignmentCandidate | None]:
    """Decide one candidate. The whole trust boundary of Phase 2D, per item."""
    claim = claims.get(candidate.claim_id)
    if claim is None:
        return None, _reject(
            candidate,
            AlignmentRejectionReason.UNKNOWN_CLAIM,
            "candidate references a claim id that does not exist in this project",
        )

    evidence = evidence_by_id.get(candidate.evidence_id)
    if evidence is None:
        return None, _reject(
            candidate,
            AlignmentRejectionReason.UNKNOWN_EVIDENCE,
            "candidate references an evidence id not accepted in this run",
        )

    if evidence.research_run_id != research_run_id:
        return None, _reject(
            candidate,
            AlignmentRejectionReason.EVIDENCE_OUTSIDE_RUN,
            "candidate references evidence from a different research run",
        )

    if (
        not evidence.observations
        or not evidence.extractor_version
        or not evidence.verifier_version
        or evidence.content_kind not in EXTRACTABLE_CONTENT_KINDS
    ):
        return None, _reject(
            candidate,
            AlignmentRejectionReason.EVIDENCE_PROVENANCE_INVALID,
            "evidence lacks valid Phase 2C provenance",
        )

    if not candidate.components and candidate.relation.value != "NOT_RELEVANT":
        return None, _reject(
            candidate,
            AlignmentRejectionReason.NO_COMPONENTS,
            "a relation other than NOT_RELEVANT requires at least one component",
        )

    components: list[ComponentAlignmentJudgment] = []
    for proposed in candidate.components:
        if not proposed.reason_codes:
            return None, _reject(
                candidate,
                AlignmentRejectionReason.OTHER,
                "a component judgment must carry at least one reason code",
            )
        resolution = resolve_anchor(claim.claim, proposed.claimed_text, proposed.claimed_start)
        if not resolution.resolved:
            return None, _reject(
                candidate,
                AlignmentRejectionReason.FABRICATED_ANCHOR,
                "a proposed claim anchor does not exist verbatim in the claim text",
            )
        anchor = ClaimComponentAnchor(
            claim_id=claim.claim_id,
            start=resolution.start,
            end=resolution.end,
            text=resolution.text,
        )
        components.append(
            ComponentAlignmentJudgment(
                anchor=anchor,
                judgment=proposed.judgment,
                reason_codes=proposed.reason_codes,
                rationale=proposed.rationale,
            )
        )

    if not relation_is_consistent(candidate.relation, components):
        return None, _reject(
            candidate,
            AlignmentRejectionReason.STRUCTURALLY_INCONSISTENT,
            "the relation is not consistent with its component judgments",
        )

    key = (candidate.claim_id, str(candidate.evidence_id))
    existing = accepted_keys.get(key)
    if existing is not None:
        if existing.relation == candidate.relation and [
            (c.anchor.start, c.anchor.end, c.judgment) for c in existing.components
        ] == [(c.anchor.start, c.anchor.end, c.judgment) for c in components]:
            # Identical re-derivation (replay/idempotent retry): no new record,
            # no rejection either -- this is not an error, it is a repeat.
            return None, None
        return None, _reject(
            candidate,
            AlignmentRejectionReason.DUPLICATE_INCOMPATIBLE_PAIR,
            "this claim/evidence pair already carries a different verified relation",
        )

    alignment = ClaimEvidenceAlignment(
        research_run_id=research_run_id,
        alignment_run_id=alignment_run_id,
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        evidence_content_hash=evidence.content_hash,
        relation=candidate.relation,
        components=components,
        rationale=candidate.rationale,
        classifier_version=candidate.classifier_version,
        verifier_version=ALIGNMENT_VERIFIER_VERSION,
        model_name=candidate.model_name,
    )
    return alignment, None


def verify_candidates(
    candidates: list[AlignmentCandidate],
    claims: list[ClaimRecord],
    evidence: list[ExtractedEvidence],
    *,
    research_run_id: UUID,
    alignment_run_id: UUID,
) -> VerificationOutcome:
    """Verify every candidate, in order. Duplicates are resolved deterministically."""
    claim_index = {c.claim_id: c for c in claims}
    evidence_index = {e.evidence_id: e for e in evidence}
    outcome = VerificationOutcome()
    accepted_keys: dict[tuple[str, str], ClaimEvidenceAlignment] = {}

    for candidate in candidates:
        alignment, rejection = verify_candidate(
            candidate,
            claim_index,
            evidence_index,
            research_run_id=research_run_id,
            alignment_run_id=alignment_run_id,
            accepted_keys=accepted_keys,
        )
        if alignment is not None:
            outcome.alignments.append(alignment)
            accepted_keys[alignment.logical_key] = alignment
        if rejection is not None:
            outcome.rejected.append(rejection)

    return outcome


# ---------------------------------------------------------------------------
# Coverage and status
# ---------------------------------------------------------------------------


def build_coverage(
    *,
    claims_total: int,
    accepted_evidence_total: int,
    pairs_required: int,
    pairs_generated: int,
    candidates: list[AlignmentCandidate],
    alignments: list[ClaimEvidenceAlignment],
    rejected: list[RejectedAlignmentCandidate],
    model_failures: int,
) -> AlignmentCoverage:
    """Operational counters only. Never a statement about claim sufficiency."""
    verification_failures = sum(
        1
        for entry in rejected
        if entry.reason is not AlignmentRejectionReason.DUPLICATE_INCOMPATIBLE_PAIR
    )
    relation_counts: dict[str, int] = {}
    for alignment in alignments:
        relation_counts[alignment.relation.value] = (
            relation_counts.get(alignment.relation.value, 0) + 1
        )
    return AlignmentCoverage(
        claims_total=claims_total,
        accepted_evidence_total=accepted_evidence_total,
        pairs_required=pairs_required,
        pairs_generated=pairs_generated,
        pairs_classified=len(candidates),
        candidates_total=len(candidates),
        accepted_alignments_total=len(alignments),
        rejected_candidates_total=len(rejected),
        model_failures=model_failures,
        verification_failures=verification_failures,
        relation_counts=relation_counts,
    )


def decide_status(
    coverage: AlignmentCoverage, *, provider_available: bool, blocked: bool
) -> ClaimAlignmentStatus:
    """The run verdict, mirroring the Phase 2C decision shape (section 13, 18)."""
    if blocked:
        return ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED
    if coverage.claims_total == 0:
        return ClaimAlignmentStatus.NO_ALIGNABLE_CLAIMS
    if coverage.accepted_evidence_total == 0:
        return ClaimAlignmentStatus.NO_ALIGNABLE_EVIDENCE
    if not provider_available:
        return ClaimAlignmentStatus.FAILED
    if coverage.pairs_generated == 0:
        return ClaimAlignmentStatus.NO_ALIGNABLE_EVIDENCE
    if coverage.model_failures and not coverage.candidates_total:
        return ClaimAlignmentStatus.FAILED
    if coverage.model_failures or coverage.verification_failures:
        return ClaimAlignmentStatus.PARTIAL
    return ClaimAlignmentStatus.COMPLETED


__all__ = [
    "VerificationOutcome",
    "build_coverage",
    "decide_status",
    "verify_candidate",
    "verify_candidates",
]
