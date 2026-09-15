"""Tests for PROJECT_STATE and its referential integrity (architecture 6)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.graph.state import ProjectState
from src.schemas.claim import ClaimRecord, ClaimStatus
from src.schemas.common import (
    BranchStatus,
    EvaluationStatus,
    KnowledgeStatus,
    OperatingMode,
    ProjectType,
    ResearchBranch,
)
from src.schemas.evidence import EvidenceRecord, EvidenceType
from src.schemas.prior_art import BranchCoverage, NoveltyAssessment
from src.schemas.source import SourceRecord, SourceType
from src.schemas.project import ProjectIdentity


def test_empty_state_is_valid_and_claims_nothing() -> None:
    state = ProjectState()
    assert state.current_mode is OperatingMode.EVALUATOR
    assert state.identity.project_type is ProjectType.UNKNOWN
    assert state.evaluation_status is EvaluationStatus.NOT_EVALUATED
    assert state.identity.project_name.status is KnowledgeStatus.UNKNOWN
    assert state.novelty.level is None
    assert state.scores == []


def test_valid_complete_state_round_trips_through_json(project_b) -> None:
    payload = project_b.model_dump_json()
    restored = ProjectState.model_validate(json.loads(payload))
    assert restored == project_b


def test_fixture_a_round_trips_through_json(project_a) -> None:
    restored = ProjectState.model_validate(json.loads(project_a.model_dump_json()))
    assert restored == project_a


def test_unknown_type_cannot_carry_a_classification_confidence() -> None:
    with pytest.raises(ValidationError, match="must not carry a classification"):
        ProjectIdentity(
            project_type=ProjectType.UNKNOWN, project_type_confidence=0.9
        )


def test_evidence_pointing_at_an_unknown_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="references unknown source"):
        ProjectState(
            evidence=[
                EvidenceRecord(
                    evidence_id="E-001",
                    source_id="SRC-999",
                    evidence_type=EvidenceType.BASELINE,
                    statement="x",
                )
            ]
        )


def test_claim_pointing_at_unknown_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="references unknown ids"):
        ProjectState(
            claims=[
                ClaimRecord(
                    claim_id="C-001",
                    claim="x",
                    status=ClaimStatus.SUPPORTED,
                    evidence_ids=["E-404"],
                )
            ]
        )


def test_duplicate_source_ids_are_rejected() -> None:
    src = dict(source_id="SRC-001", source_type=SourceType.OTHER)
    with pytest.raises(ValidationError, match="duplicate source_id"):
        ProjectState(sources=[SourceRecord(**src), SourceRecord(**src)])


def test_novelty_pointing_at_unknown_prior_art_is_rejected() -> None:
    with pytest.raises(ValidationError, match="references unknown ids"):
        ProjectState(
            novelty=NoveltyAssessment(
                status=EvaluationStatus.PROVISIONAL,
                level=3,
                closest_prior_art_ids=["PA-999"],
            )
        )


def test_novelty_level_is_bounded_to_zero_through_five() -> None:
    for level in (0, 5):
        assert (
            NoveltyAssessment(
                level=level, status=EvaluationStatus.PROVISIONAL
            ).level
            == level
        )
    for bad in (-1, 6):
        with pytest.raises(ValidationError):
            NoveltyAssessment(level=bad, status=EvaluationStatus.PROVISIONAL)


def test_novelty_level_requires_an_evaluation_to_have_happened() -> None:
    with pytest.raises(ValidationError, match="cannot be set while status=NOT_EVALUATED"):
        NoveltyAssessment(level=4, status=EvaluationStatus.NOT_EVALUATED)


def test_completed_branch_needs_at_least_one_query() -> None:
    """27: a branch is never 'complete' on the strength of zero queries."""
    with pytest.raises(ValidationError, match="at least one query_id"):
        BranchCoverage(
            branch=ResearchBranch.PATENT,
            required=True,
            status=BranchStatus.COMPLETED,
        )


def test_failed_branch_must_say_why() -> None:
    with pytest.raises(ValidationError, match="must state a failure_reason"):
        BranchCoverage(branch=ResearchBranch.PATENT, status=BranchStatus.FAILED)


# --- fixture-specific behaviour -------------------------------------------

def test_fixture_a_represents_missing_data_without_inventing_it(project_a) -> None:
    assert project_a.solution.technical_principle.status is KnowledgeStatus.UNKNOWN
    assert project_a.solution.technical_principle.value is None
    assert project_a.methodology.baseline == []
    assert project_a.methodology.review_status is EvaluationStatus.INSUFFICIENT_EVIDENCE
    assert len(project_a.critical_missing_information) == 2


def test_fixture_a_represents_a_conflict_without_picking_a_side(project_a) -> None:
    accuracy = project_a.results[0].value
    assert accuracy.status is KnowledgeStatus.CONFLICTED
    assert accuracy.value is None
    assert set(accuracy.conflicting_values) == {"95%", "87%"}
    assert project_a.unresolved_critical_contradictions


def test_fixture_a_keeps_its_claims_unsupported(project_a) -> None:
    assert all(c.status is ClaimStatus.UNSUPPORTED for c in project_a.claims)
    assert all(not c.is_strong for c in project_a.claims)


def test_fixture_b_chains_claim_to_evidence_to_source(project_b) -> None:
    for claim in project_b.claims:
        if claim.is_strong:
            assert project_b.sources_for_claim(claim.claim_id)


def test_fixture_b_has_a_full_score_and_a_provisional_status(project_b) -> None:
    score = project_b.scores[0]
    assert score.total == 68.0
    assert score.max_total == 100.0
    assert score.status is EvaluationStatus.PROVISIONAL
    assert not score.is_final


def test_fixture_b_records_its_research_queries(project_b) -> None:
    assert {q.query_id for q in project_b.research_queries} == {"Q-001", "Q-002", "Q-003"}
    assert all(q.status is BranchStatus.COMPLETED for q in project_b.research_queries)


def test_state_exposes_the_highest_open_severity(project_b) -> None:
    from src.schemas.common import Severity

    assert project_b.max_open_severity() is Severity.MEDIUM
