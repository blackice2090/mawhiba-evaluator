"""Phase 2D schema/taxonomy tests: relation consistency, anchors, provenance."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.claim_alignment import (
    AlignmentRelation,
    ClaimComponentAnchor,
    ClaimEvidenceAlignment,
    ClaimEvidenceAlignmentRun,
    ComponentAlignmentJudgment,
    ComponentJudgment,
    relation_is_consistent,
)


def _anchor(text: str = "abc", start: int = 0) -> ClaimComponentAnchor:
    return ClaimComponentAnchor(claim_id="C-001", start=start, end=start + len(text), text=text)


def _judgment(judgment: ComponentJudgment, text: str = "abc") -> ComponentAlignmentJudgment:
    return ComponentAlignmentJudgment(
        anchor=_anchor(text), judgment=judgment, reason_codes=["OTHER"]
    )


def _alignment(relation: AlignmentRelation, components: list[ComponentAlignmentJudgment]):
    return ClaimEvidenceAlignment(
        research_run_id=uuid4(),
        alignment_run_id=uuid4(),
        claim_id="C-001",
        evidence_id=uuid4(),
        evidence_content_hash="a" * 64,
        relation=relation,
        components=components,
    )


class TestClaimComponentAnchor:
    def test_exact_span_holds(self):
        anchor = _anchor("hello world")
        assert anchor.text == "hello world"

    def test_length_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            ClaimComponentAnchor(claim_id="C-001", start=0, end=5, text="too long text")

    def test_end_before_start_rejected(self):
        with pytest.raises(ValidationError):
            ClaimComponentAnchor(claim_id="C-001", start=5, end=3, text="ab")


class TestRelationConsistency:
    def test_pure_support(self):
        assert relation_is_consistent(
            AlignmentRelation.SUPPORTS, [_judgment(ComponentJudgment.SUPPORTS)]
        )

    def test_pure_support_rejects_partial_label(self):
        assert not relation_is_consistent(
            AlignmentRelation.PARTIALLY_SUPPORTS, [_judgment(ComponentJudgment.SUPPORTS)]
        )

    def test_support_plus_unresolved_is_partial(self):
        components = [
            _judgment(ComponentJudgment.SUPPORTS, "a"),
            _judgment(ComponentJudgment.UNRESOLVED, "b"),
        ]
        assert relation_is_consistent(AlignmentRelation.PARTIALLY_SUPPORTS, components)
        assert not relation_is_consistent(AlignmentRelation.SUPPORTS, components)

    def test_support_and_contradiction_is_mixed_only(self):
        components = [
            _judgment(ComponentJudgment.SUPPORTS, "a"),
            _judgment(ComponentJudgment.CONTRADICTS, "b"),
        ]
        assert relation_is_consistent(AlignmentRelation.MIXED, components)
        assert not relation_is_consistent(AlignmentRelation.SUPPORTS, components)
        assert not relation_is_consistent(AlignmentRelation.PARTIALLY_SUPPORTS, components)

    def test_context_only_requires_pure_context(self):
        assert relation_is_consistent(
            AlignmentRelation.CONTEXT_ONLY, [_judgment(ComponentJudgment.CONTEXTUAL)]
        )
        assert not relation_is_consistent(
            AlignmentRelation.INSUFFICIENT, [_judgment(ComponentJudgment.CONTEXTUAL)]
        )

    def test_insufficient_requires_pure_unresolved(self):
        assert relation_is_consistent(
            AlignmentRelation.INSUFFICIENT, [_judgment(ComponentJudgment.UNRESOLVED)]
        )

    def test_not_relevant_requires_empty_components(self):
        assert relation_is_consistent(AlignmentRelation.NOT_RELEVANT, [])
        assert not relation_is_consistent(
            AlignmentRelation.NOT_RELEVANT, [_judgment(ComponentJudgment.CONTEXTUAL)]
        )

    def test_context_and_unresolved_mix_is_never_consistent(self):
        """An ambiguous mix (context + unresolved, no support/contradiction)
        must not silently pass as either CONTEXT_ONLY or INSUFFICIENT."""
        components = [
            _judgment(ComponentJudgment.CONTEXTUAL, "a"),
            _judgment(ComponentJudgment.UNRESOLVED, "b"),
        ]
        for relation in AlignmentRelation:
            assert not relation_is_consistent(relation, components)


class TestClaimEvidenceAlignmentConstruction:
    def test_consistent_alignment_constructs(self):
        alignment = _alignment(
            AlignmentRelation.SUPPORTS, [_judgment(ComponentJudgment.SUPPORTS)]
        )
        assert alignment.relation is AlignmentRelation.SUPPORTS

    def test_inconsistent_relation_rejected(self):
        with pytest.raises(ValidationError):
            _alignment(
                AlignmentRelation.CONTRADICTS, [_judgment(ComponentJudgment.SUPPORTS)]
            )

    def test_component_from_another_claim_rejected(self):
        bad_anchor = ClaimComponentAnchor(claim_id="C-999", start=0, end=3, text="abc")
        bad = ComponentAlignmentJudgment(
            anchor=bad_anchor, judgment=ComponentJudgment.SUPPORTS, reason_codes=["OTHER"]
        )
        with pytest.raises(ValidationError):
            _alignment(AlignmentRelation.SUPPORTS, [bad])

    def test_not_relevant_allows_empty_components(self):
        alignment = _alignment(AlignmentRelation.NOT_RELEVANT, [])
        assert alignment.components == []


class TestClaimEvidenceAlignmentRun:
    def test_duplicate_pair_rejected(self):
        research_run_id = uuid4()
        alignment_run_id = uuid4()
        evidence_id = uuid4()
        one = ClaimEvidenceAlignment(
            research_run_id=research_run_id,
            alignment_run_id=alignment_run_id,
            claim_id="C-001",
            evidence_id=evidence_id,
            evidence_content_hash="a" * 64,
            relation=AlignmentRelation.SUPPORTS,
            components=[_judgment(ComponentJudgment.SUPPORTS)],
        )
        two = one.model_copy(update={"alignment_id": uuid4()})
        with pytest.raises(ValidationError):
            ClaimEvidenceAlignmentRun(
                research_run_id=research_run_id,
                alignment_run_id=alignment_run_id,
                status="COMPLETED",
                alignments=[one, two],
                completed_at="2026-01-01T00:00:00+00:00",
            )

    def test_not_started_cannot_carry_alignments(self):
        alignment = _alignment(
            AlignmentRelation.SUPPORTS, [_judgment(ComponentJudgment.SUPPORTS)]
        )
        with pytest.raises(ValidationError):
            ClaimEvidenceAlignmentRun(
                research_run_id=alignment.research_run_id,
                alignment_run_id=alignment.alignment_run_id,
                status="NOT_STARTED",
                alignments=[alignment],
            )
