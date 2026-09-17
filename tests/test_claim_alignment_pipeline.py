"""Phase 2D deterministic verifier and pairing unit tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.research.alignment.pairing import generate_pairs
from src.research.alignment.pipeline import verify_candidate, verify_candidates
from src.research.alignment.verification import resolve_anchor
from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import (
    AlignmentCandidate,
    AlignmentRejectionReason,
    AlignmentRelation,
    CandidateComponentAnchor,
    ComponentJudgment,
)
from src.schemas.evidence_extraction import (
    ContentKind,
    EvidenceContentObservation,
    EvidenceScope,
    ExtractedEvidence,
    ExtractedEvidenceType,
    ExtractionMethod,
    SpanMatchMethod,
    content_hash,
)
from src.schemas.academic import AcademicProvider


def _claim(claim_id: str = "C-001", text: str = "Our system achieves 95% accuracy on the test set."):
    return ClaimRecord(claim_id=claim_id, claim=text)


def _evidence(research_run_id, text: str = "achieved 95% accuracy on the held-out set") -> ExtractedEvidence:
    content_id = uuid4()
    digest = content_hash(text)
    return ExtractedEvidence(
        research_run_id=research_run_id,
        extraction_run_id=uuid4(),
        source_id=f"SRC-{uuid4()}",
        content_id=content_id,
        content_hash=digest,
        content_kind=ContentKind.ABSTRACT,
        evidence_scope=EvidenceScope.ABSTRACT_ONLY,
        evidence_type=ExtractedEvidenceType.EXPERIMENTAL_RESULT,
        excerpt=text,
        verified_start=0,
        verified_end=len(text),
        match_method=SpanMatchMethod.EXACT,
        observations=[
            EvidenceContentObservation(
                content_id=content_id,
                provider=AcademicProvider.CONSENSUS,
                content_hash=digest,
                content_kind=ContentKind.ABSTRACT,
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        ],
        extraction_method=ExtractionMethod.DETERMINISTIC_FIXTURE,
    )


def _candidate(claim_id, evidence_id, relation, claimed_text, judgment) -> AlignmentCandidate:
    return AlignmentCandidate(
        claim_id=claim_id,
        evidence_id=evidence_id,
        relation=relation,
        components=[
            CandidateComponentAnchor(
                claimed_text=claimed_text, judgment=judgment, reason_codes=["DIRECT_SUPPORT"]
            )
        ]
        if relation is not AlignmentRelation.NOT_RELEVANT
        else [],
    )


class TestResolveAnchor:
    def test_exact_match(self):
        result = resolve_anchor("hello brave new world", "brave new", None)
        assert result.resolved
        assert result.text == "brave new"

    def test_not_found(self):
        result = resolve_anchor("hello world", "goodbye", None)
        assert not result.resolved

    def test_ambiguous_uses_claimed_start_when_valid(self):
        text = "abc abc abc"
        result = resolve_anchor(text, "abc", 4)
        assert result.resolved
        assert result.start == 4
        assert result.ambiguous


class TestVerifyCandidate:
    def test_accepts_valid_support(self):
        run_id = uuid4()
        claim = _claim()
        evidence = _evidence(run_id)
        candidate = _candidate(
            claim.claim_id,
            evidence.evidence_id,
            AlignmentRelation.SUPPORTS,
            "achieves 95% accuracy on the test set",
            ComponentJudgment.SUPPORTS,
        )
        alignment, rejection = verify_candidate(
            candidate,
            {claim.claim_id: claim},
            {evidence.evidence_id: evidence},
            research_run_id=run_id,
            alignment_run_id=uuid4(),
            accepted_keys={},
        )
        assert rejection is None
        assert alignment is not None
        assert alignment.relation is AlignmentRelation.SUPPORTS

    def test_unknown_claim_rejected(self):
        run_id = uuid4()
        evidence = _evidence(run_id)
        candidate = _candidate(
            "C-999", evidence.evidence_id, AlignmentRelation.SUPPORTS, "x", ComponentJudgment.SUPPORTS
        )
        alignment, rejection = verify_candidate(
            candidate, {}, {evidence.evidence_id: evidence},
            research_run_id=run_id, alignment_run_id=uuid4(), accepted_keys={},
        )
        assert alignment is None
        assert rejection.reason is AlignmentRejectionReason.UNKNOWN_CLAIM

    def test_unknown_evidence_rejected(self):
        run_id = uuid4()
        claim = _claim()
        candidate = _candidate(
            claim.claim_id, uuid4(), AlignmentRelation.SUPPORTS, "x", ComponentJudgment.SUPPORTS
        )
        alignment, rejection = verify_candidate(
            candidate, {claim.claim_id: claim}, {},
            research_run_id=run_id, alignment_run_id=uuid4(), accepted_keys={},
        )
        assert alignment is None
        assert rejection.reason is AlignmentRejectionReason.UNKNOWN_EVIDENCE

    def test_cross_run_evidence_rejected(self):
        run_id = uuid4()
        other_run_id = uuid4()
        claim = _claim()
        evidence = _evidence(other_run_id)
        candidate = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.SUPPORTS,
            "x", ComponentJudgment.SUPPORTS,
        )
        alignment, rejection = verify_candidate(
            candidate, {claim.claim_id: claim}, {evidence.evidence_id: evidence},
            research_run_id=run_id, alignment_run_id=uuid4(), accepted_keys={},
        )
        assert alignment is None
        assert rejection.reason is AlignmentRejectionReason.EVIDENCE_OUTSIDE_RUN

    def test_fabricated_anchor_rejected(self):
        run_id = uuid4()
        claim = _claim()
        evidence = _evidence(run_id)
        candidate = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.SUPPORTS,
            "this text never appears in the claim", ComponentJudgment.SUPPORTS,
        )
        alignment, rejection = verify_candidate(
            candidate, {claim.claim_id: claim}, {evidence.evidence_id: evidence},
            research_run_id=run_id, alignment_run_id=uuid4(), accepted_keys={},
        )
        assert alignment is None
        assert rejection.reason is AlignmentRejectionReason.FABRICATED_ANCHOR

    def test_structurally_inconsistent_rejected(self):
        run_id = uuid4()
        claim = _claim()
        evidence = _evidence(run_id)
        candidate = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.CONTRADICTS,
            "achieves 95% accuracy on the test set", ComponentJudgment.SUPPORTS,
        )
        alignment, rejection = verify_candidate(
            candidate, {claim.claim_id: claim}, {evidence.evidence_id: evidence},
            research_run_id=run_id, alignment_run_id=uuid4(), accepted_keys={},
        )
        assert alignment is None
        assert rejection.reason is AlignmentRejectionReason.STRUCTURALLY_INCONSISTENT

    def test_duplicate_incompatible_pair_rejected(self):
        run_id = uuid4()
        claim = _claim()
        evidence = _evidence(run_id)
        first = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.SUPPORTS,
            "achieves 95% accuracy on the test set", ComponentJudgment.SUPPORTS,
        )
        outcome = verify_candidates(
            [first], [claim], [evidence], research_run_id=run_id, alignment_run_id=uuid4()
        )
        assert len(outcome.alignments) == 1

        second = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.CONTRADICTS,
            "achieves 95% accuracy on the test set", ComponentJudgment.CONTRADICTS,
        )
        combined = verify_candidates(
            [first, second], [claim], [evidence],
            research_run_id=run_id, alignment_run_id=outcome.alignments[0].alignment_run_id,
        )
        assert len(combined.alignments) == 1
        assert any(
            r.reason is AlignmentRejectionReason.DUPLICATE_INCOMPATIBLE_PAIR
            for r in combined.rejected
        )

    def test_identical_duplicate_is_idempotent_noop(self):
        run_id = uuid4()
        claim = _claim()
        evidence = _evidence(run_id)
        candidate = _candidate(
            claim.claim_id, evidence.evidence_id, AlignmentRelation.SUPPORTS,
            "achieves 95% accuracy on the test set", ComponentJudgment.SUPPORTS,
        )
        outcome = verify_candidates(
            [candidate, candidate], [claim], [evidence],
            research_run_id=run_id, alignment_run_id=uuid4(),
        )
        assert len(outcome.alignments) == 1
        assert not outcome.rejected


class TestGeneratePairs:
    def test_claim_major_stable_order(self):
        claims = [_claim("C-001"), _claim("C-002")]
        run_id = uuid4()
        evidence = [_evidence(run_id), _evidence(run_id)]
        outcome = generate_pairs(claims, evidence)
        assert not outcome.blocked
        assert len(outcome.pairs) == 4
        assert outcome.pairs[0].claim_id == "C-001"
        assert outcome.pairs[2].claim_id == "C-002"

    def test_hard_limit_blocks_without_truncating(self):
        claims = [_claim(f"C-{i:03d}") for i in range(1, 6)]
        run_id = uuid4()
        evidence = [_evidence(run_id) for _ in range(5)]
        outcome = generate_pairs(claims, evidence, max_pairs_per_run=10)
        assert outcome.blocked
        assert outcome.required_count == 25
        assert outcome.pairs == []
