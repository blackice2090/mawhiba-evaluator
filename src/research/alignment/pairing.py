"""Deterministic claim/evidence pair generation (section 12).

Completeness over heuristic ranking: every existing claim is paired with every
accepted Phase 2C evidence item in the current run, in stable order. No
title-only or embedding-only preselection, because that could silently omit
contradictory evidence -- exactly what this phase must not do.

A hard safety limit prevents pathological Cartesian growth. Hitting it is
never silent: the caller gets the full required count and the limit, and the
run is marked ``BLOCKED_PAIR_LIMIT_EXCEEDED`` rather than silently truncated.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import AlignmentPair
from src.schemas.evidence_extraction import ExtractedEvidence

DEFAULT_MAX_PAIRS_PER_RUN = 500
"""Reviewable configuration, not a magic number (section 12)."""


@dataclass
class PairGenerationOutcome:
    pairs: list[AlignmentPair]
    required_count: int
    blocked: bool


def generate_pairs(
    claims: list[ClaimRecord],
    evidence: list[ExtractedEvidence],
    *,
    max_pairs_per_run: int = DEFAULT_MAX_PAIRS_PER_RUN,
) -> PairGenerationOutcome:
    """Every claim x every accepted evidence item, in stable order.

    Stable order: claims in their existing list order, evidence in their
    existing list order, claim-major. Deterministic across replays and across
    checkpoint resume.
    """
    required = len(claims) * len(evidence)
    if required > max_pairs_per_run:
        return PairGenerationOutcome(pairs=[], required_count=required, blocked=True)

    pairs = [
        AlignmentPair(claim_id=claim.claim_id, evidence_id=item.evidence_id)
        for claim in claims
        for item in evidence
    ]
    return PairGenerationOutcome(pairs=pairs, required_count=required, blocked=False)


__all__ = ["DEFAULT_MAX_PAIRS_PER_RUN", "PairGenerationOutcome", "generate_pairs"]
