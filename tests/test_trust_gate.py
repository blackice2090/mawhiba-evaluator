"""Tests for the Trust Gate (architecture 21, 40).

The gate must be deterministic: same state in, same verdict out, with no LLM
involved.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.common import BranchStatus, EvaluationStatus, ResearchBranch, Severity
from src.schemas.finding import ContradictionStatus
from src.schemas.prior_art import BranchCoverage
from src.schemas.source import VerificationStatus
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult
from src.trust.models import (
    DEFAULT_TRUST_POLICY,
    TrustPolicy,
    compute_claim_traceability,
    compute_search_coverage,
    compute_source_quality,
    evaluate_trust_gate,
)


def _pass_all(state, **overrides):
    """Run the gate with every externally-supplied flag set to pass."""
    kwargs = dict(
        red_team_complete=True,
        final_verifier_passed=True,
        official_requirements_checked=True,
    )
    kwargs.update(overrides)
    return evaluate_trust_gate(state, **kwargs)


# --- schema-level invariants ----------------------------------------------

def test_finalization_cannot_coexist_with_blockers() -> None:
    with pytest.raises(ValidationError, match="cannot be True while blockers"):
        TrustGateResult(
            finalization_allowed=True,
            blockers=[
                TrustBlocker(
                    code=BlockerCode.NOVELTY_SEARCH_INCOMPLETE, detail="patent missing"
                )
            ],
        )


def test_resolved_flag_cannot_contradict_the_count() -> None:
    with pytest.raises(ValidationError, match="contradicts a non-zero"):
        TrustGateResult(
            contradictions_resolved=True,
            unresolved_critical_contradiction_count=1,
        )


# --- metric computation ----------------------------------------------------

def test_search_coverage_counts_only_required_branches(project_b) -> None:
    assert compute_search_coverage(project_b) == 1.0


def test_search_coverage_is_zero_when_nothing_ran(project_a) -> None:
    assert compute_search_coverage(project_a) == 0.0


def test_source_quality_is_zero_without_sources(project_a) -> None:
    assert compute_source_quality(project_a) == 0.0


def test_source_quality_is_the_mean_of_signals(project_b) -> None:
    assert 0.0 < compute_source_quality(project_b) <= 1.0


def test_claim_traceability_is_full_for_the_complete_project(project_b) -> None:
    assert compute_claim_traceability(project_b) == 1.0


def test_claim_traceability_counts_honest_unsupported_claims(project_a) -> None:
    """An UNSUPPORTED claim is traceable: it correctly declares it has nothing."""
    assert compute_claim_traceability(project_a) == 1.0


# --- fixture A: the gate must refuse -------------------------------------

def test_incomplete_project_is_blocked(project_a) -> None:
    result = _pass_all(project_a)
    assert result.finalization_allowed is False
    assert result.blockers


def test_incomplete_novelty_search_blocks_finalization(project_a) -> None:
    """13: no strong novelty judgement before the required branches complete."""
    result = _pass_all(project_a)
    assert result.has_blocker(BlockerCode.NOVELTY_SEARCH_INCOMPLETE)
    assert result.novelty_search_complete is False


def test_unresolved_critical_contradiction_blocks_finalization(project_a) -> None:
    result = _pass_all(project_a)
    assert result.has_blocker(BlockerCode.UNRESOLVED_CRITICAL_CONTRADICTION)
    assert result.unresolved_critical_contradiction_count == 1
    assert result.contradictions_resolved is False


def test_critical_missing_information_blocks_finalization(project_a) -> None:
    result = _pass_all(project_a)
    assert result.has_blocker(BlockerCode.CRITICAL_INFORMATION_MISSING)
    assert result.critical_missing_count == 2


def test_missing_prior_art_blocks_finalization(project_a) -> None:
    result = _pass_all(project_a)
    assert result.has_blocker(BlockerCode.CLOSEST_PRIOR_ART_NOT_IDENTIFIED)


def test_incomplete_project_reports_insufficient_evidence(project_a) -> None:
    """2.6: abstention is the correct output, not a fabricated score."""
    result = _pass_all(project_a)
    assert result.score_status is EvaluationStatus.INSUFFICIENT_EVIDENCE


def test_every_blocker_explains_itself(project_a) -> None:
    for blocker in _pass_all(project_a).blockers:
        assert blocker.detail.strip()


# --- fixture B: the gate may pass ----------------------------------------

def test_complete_project_passes_when_all_stages_reported_done(project_b) -> None:
    result = _pass_all(project_b)
    assert result.blockers == []
    assert result.finalization_allowed is True
    assert result.score_status is EvaluationStatus.FINAL


def test_missing_red_team_blocks_an_otherwise_complete_project(project_b) -> None:
    """19: the red team pass is not optional."""
    result = _pass_all(project_b, red_team_complete=False)
    assert result.finalization_allowed is False
    assert result.has_blocker(BlockerCode.RED_TEAM_INCOMPLETE)


def test_missing_final_verifier_blocks(project_b) -> None:
    result = _pass_all(project_b, final_verifier_passed=False)
    assert result.has_blocker(BlockerCode.FINAL_VERIFIER_NOT_PASSED)


def test_unchecked_official_requirements_block(project_b) -> None:
    """2.4: an official rule is never asserted without official evidence."""
    result = _pass_all(project_b, official_requirements_checked=False)
    assert result.has_blocker(
        BlockerCode.OFFICIAL_RULE_ASSERTED_WITHOUT_OFFICIAL_EVIDENCE
    )


def test_unverified_cited_source_blocks_finalization(project_b) -> None:
    project_b.sources[0].verification_status = VerificationStatus.SEARCH_RESULT_ONLY
    result = _pass_all(project_b)
    assert result.has_blocker(BlockerCode.INVENTED_OR_UNVERIFIED_CITATION)
    assert result.unverified_source_count == 1


def test_reopened_critical_contradiction_blocks_a_complete_project(project_b) -> None:
    from src.schemas.finding import ContradictionRecord

    project_b.contradictions = [
        ContradictionRecord(
            contradiction_id="CT-010",
            description="Sample size 40 in the log, 25 in the poster.",
            severity=Severity.CRITICAL,
            status=ContradictionStatus.OPEN,
            conflicting_statements=["log: n=40", "poster: n=25"],
            affected_claim_ids=["C-001"],
        )
    ]
    result = _pass_all(project_b)
    assert result.finalization_allowed is False
    assert result.has_blocker(BlockerCode.UNRESOLVED_CRITICAL_CONTRADICTION)


def test_resolved_contradiction_does_not_block(project_b) -> None:
    from src.schemas.finding import ContradictionRecord
    from tests.fixtures.projects import FIXED_TIME

    project_b.contradictions = [
        ContradictionRecord(
            contradiction_id="CT-011",
            description="Sample size mismatch.",
            severity=Severity.CRITICAL,
            status=ContradictionStatus.RESOLVED,
            conflicting_statements=["log: n=40", "poster: n=25"],
            resolution="Student confirmed n=40; poster was an early draft.",
            resolved_at=FIXED_TIME,
        )
    ]
    result = _pass_all(project_b)
    assert result.finalization_allowed is True


def test_dropping_a_required_branch_blocks_novelty(project_b) -> None:
    project_b.novelty.branch_coverage = [
        BranchCoverage(
            branch=ResearchBranch.ACADEMIC,
            required=True,
            status=BranchStatus.COMPLETED,
            query_ids=["Q-001"],
        ),
        BranchCoverage(
            branch=ResearchBranch.PATENT,
            required=True,
            status=BranchStatus.FAILED,
            failure_reason="EPO OPS timed out",
        ),
    ]
    result = _pass_all(project_b)
    assert result.has_blocker(BlockerCode.NOVELTY_SEARCH_INCOMPLETE)
    assert result.search_coverage == 0.5


def test_strong_novelty_without_differentiator_is_blocked(project_b) -> None:
    """13: level 4/5 needs closest prior art AND a clear differentiator."""
    project_b.novelty.level = 5
    project_b.novelty.differentiators = []
    result = _pass_all(project_b)
    assert result.has_blocker(BlockerCode.NOVELTY_SEARCH_INCOMPLETE)


def test_critical_finding_blocks_finalization(project_b) -> None:
    project_b.findings[0].severity = Severity.CRITICAL
    result = _pass_all(project_b)
    assert result.has_blocker(BlockerCode.CRITICAL_FINDING_UNADDRESSED)


def test_incomplete_methodology_review_blocks(project_b) -> None:
    project_b.methodology.review_status = EvaluationStatus.PROVISIONAL
    result = _pass_all(project_b)
    assert result.has_blocker(BlockerCode.METHODOLOGY_REVIEW_INCOMPLETE)


# --- determinism and policy ------------------------------------------------

def test_gate_is_deterministic(project_b) -> None:
    first = _pass_all(project_b)
    second = _pass_all(project_b)
    assert first.model_dump(exclude={"evaluated_at"}) == second.model_dump(
        exclude={"evaluated_at"}
    )


def test_policy_thresholds_are_honoured(project_b) -> None:
    strict = TrustPolicy(version="TEST-STRICT", min_source_quality=0.99)
    result = evaluate_trust_gate(
        project_b,
        strict,
        red_team_complete=True,
        final_verifier_passed=True,
        official_requirements_checked=True,
    )
    assert result.has_blocker(BlockerCode.SOURCE_QUALITY_BELOW_THRESHOLD)
    assert result.policy_version == "TEST-STRICT"


def test_relaxed_policy_can_skip_optional_stages(project_b) -> None:
    relaxed = TrustPolicy(
        version="TEST-RELAXED",
        require_red_team=False,
        require_final_verifier=False,
        require_official_requirements_check=False,
    )
    result = evaluate_trust_gate(project_b, relaxed)
    assert result.finalization_allowed is True


def test_default_policy_demands_full_claim_traceability() -> None:
    assert DEFAULT_TRUST_POLICY.min_claim_traceability == 1.0
