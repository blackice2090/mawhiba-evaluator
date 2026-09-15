"""Phase 2A research and official-requirements contracts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from src.graph.state import ProjectState
from src.graph.type_discovery import discover_types_from
from src.graph.workflow_state import EvaluationGraphState, merge_research_runs
from src.schemas.common import EvaluationStatus, ResearchBranch
from src.schemas.extraction import AnchorVerificationMethod, TextRange, VerifiedAnchor
from src.schemas.official import (
    ConflictResolutionBasis,
    ConflictSide,
    CriteriaAuthority,
    OfficialRequirement,
    OfficialRequirementCategory,
    OfficialRequirementConflict,
    OfficialRequirementsOutcome,
    OfficialRequirementsResult,
    OfficialRequirementStatus,
    OfficialSourceSnapshot,
    RetrievalStatus,
    SourceCandidate,
)
from src.schemas.prior_art import BranchCoverage
from src.schemas.research import (
    BranchExecutionCoverage,
    ProjectFieldReference,
    QueryPlanLimits,
    QueryPurpose,
    QueryRejectionReason,
    QueryStatus,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunVersions,
    SourceTerm,
)
from src.schemas.source import SourceType, SourceTier, VerificationStatus

HASH = "a" * 64
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _run(**changes) -> ResearchRun:
    return ResearchRun(
        project_id=uuid4(),
        project_version_id=uuid4(),
        planner_version="P1",
        versions=ResearchRunVersions(planner_prompt_version="P1", official_extractor_prompt_version="E1"),
        **changes,
    )


def _anchor(excerpt: str) -> VerifiedAnchor:
    return VerifiedAnchor(
        artifact_id=uuid4(), excerpt=excerpt, method=AnchorVerificationMethod.EXACT,
        matches=[TextRange(start=0, end=len(excerpt))],
    )


def _requirement(**changes) -> OfficialRequirement:
    base = dict(
        source_id="SRC-001", snapshot_id=uuid4(), content_hash=HASH,
        category=OfficialRequirementCategory.JUDGING_CRITERIA, subject="innovation",
        statement="Innovation 30%", anchor=_anchor("Innovation 30%"),
        status=OfficialRequirementStatus.VERIFIED_BUT_DATE_UNKNOWN, retrieved_at=NOW,
    )
    base.update(changes)
    return OfficialRequirement(**base)


# --- branches and statuses ---------------------------------------------------


def test_research_branches_are_the_stable_six() -> None:
    assert {b.value for b in ResearchBranch} == {
        "OFFICIAL_REQUIREMENTS", "ACADEMIC", "PATENT", "PRODUCT", "OPEN_SOURCE", "STANDARDS",
    }


def test_legacy_official_branch_value_still_loads() -> None:
    assert ResearchBranch("OFFICIAL") is ResearchBranch.OFFICIAL_REQUIREMENTS
    assert ResearchBranch.OFFICIAL is ResearchBranch.OFFICIAL_REQUIREMENTS
    coverage = BranchCoverage.model_validate({"branch": "OFFICIAL", "required": False})
    assert coverage.branch is ResearchBranch.OFFICIAL_REQUIREMENTS


def test_unknown_branch_value_is_still_rejected() -> None:
    with pytest.raises(ValueError):
        ResearchBranch("MARKET")


def test_research_run_status_is_its_own_vocabulary() -> None:
    assert {s.value for s in ResearchRunStatus} == {
        "NOT_STARTED", "PLANNING", "RUNNING", "PARTIAL", "COMPLETED", "FAILED",
    }
    assert ResearchRunStatus is not EvaluationStatus


def test_query_purpose_taxonomy_covers_the_required_families() -> None:
    required = {
        "PROBLEM", "EXISTING_SOLUTIONS", "TECHNOLOGY", "RECENT_WORK", "LIMITATIONS", "BENCHMARK",
        "REVIEW", "ALTERNATIVES", "FAILURE_MODES", "PRIOR_ART", "PATENT_FUNCTION",
        "PATENT_MECHANISM", "PRODUCT", "OPEN_SOURCE",
    }
    assert required <= {p.value for p in QueryPurpose}


@pytest.mark.parametrize(
    "enum_cls",
    [ResearchBranch, ResearchRunStatus, QueryPurpose, QueryStatus, QueryRejectionReason,
     OfficialRequirementCategory, OfficialRequirementStatus, OfficialRequirementsOutcome,
     RetrievalStatus, CriteriaAuthority, ConflictResolutionBasis],
)
def test_phase2a_enum_values_are_ascii_upper_snake_case(enum_cls) -> None:
    for member in enum_cls:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", member.value), f"{enum_cls.__name__}.{member.name}"


# --- ResearchRun ---------------------------------------------------------------


def test_terminal_status_requires_completed_at() -> None:
    with pytest.raises(ValidationError, match="completed_at"):
        _run(status=ResearchRunStatus.COMPLETED)
    with pytest.raises(ValidationError, match="completed_at"):
        _run(status=ResearchRunStatus.RUNNING, completed_at=NOW)


def test_research_run_is_frozen() -> None:
    run = _run()
    with pytest.raises(ValidationError):
        run.status = ResearchRunStatus.RUNNING


def test_evolve_revalidates_the_successor() -> None:
    run = _run()
    with pytest.raises(ValidationError):
        run.evolve(status=ResearchRunStatus.COMPLETED)
    assert run.evolve(status=ResearchRunStatus.RUNNING).status is ResearchRunStatus.RUNNING
    assert run.status is ResearchRunStatus.NOT_STARTED


def test_a_terminal_run_cannot_be_changed() -> None:
    done = _run(status=ResearchRunStatus.COMPLETED, started_at=NOW, completed_at=NOW)
    with pytest.raises(ValueError, match="immutable"):
        done.evolve(status=ResearchRunStatus.FAILED)


def test_reducer_never_overwrites_a_terminal_run() -> None:
    done = _run(status=ResearchRunStatus.COMPLETED, started_at=NOW, completed_at=NOW)
    forged = ResearchRun.model_validate({**dict(done), "status": ResearchRunStatus.FAILED})
    merged = merge_research_runs({str(done.research_run_id): done}, {str(done.research_run_id): forged})
    assert merged[str(done.research_run_id)].status is ResearchRunStatus.COMPLETED


def test_reducer_accepts_a_new_run_beside_an_old_one() -> None:
    old = _run(status=ResearchRunStatus.COMPLETED, started_at=NOW, completed_at=NOW)
    new = _run()
    merged = merge_research_runs({str(old.research_run_id): old}, {str(new.research_run_id): new})
    assert set(merged) == {str(old.research_run_id), str(new.research_run_id)}


def test_coverage_has_one_entry_per_branch() -> None:
    entry = BranchExecutionCoverage(branch=ResearchBranch.ACADEMIC)
    with pytest.raises(ValidationError, match="one entry per branch"):
        _run(branch_coverage=[entry, entry])


# --- queries and coverage ---------------------------------------------------------


def test_accepted_query_must_trace_to_a_source_term() -> None:
    with pytest.raises(ValidationError, match="source term"):
        ResearchQuery(research_run_id=uuid4(), branch=ResearchBranch.ACADEMIC,
                      purpose=QueryPurpose.TECHNOLOGY, query="YOLOv8", status=QueryStatus.ACCEPTED,
                      planner_version="P1")


def test_derived_from_must_match_the_source_term_fields() -> None:
    with pytest.raises(ValidationError, match="derived_from"):
        ResearchQuery(research_run_id=uuid4(), branch=ResearchBranch.ACADEMIC,
                      purpose=QueryPurpose.TECHNOLOGY, query="YOLOv8", status=QueryStatus.ACCEPTED,
                      source_terms=[SourceTerm(term="YOLOv8", field_path="technical.algorithms")],
                      derived_from=[ProjectFieldReference(field_path="problem.statement")],
                      planner_version="P1")


def test_rejected_query_must_say_why() -> None:
    with pytest.raises(ValidationError, match="reason"):
        ResearchQuery(research_run_id=uuid4(), status=QueryStatus.REJECTED, planner_version="P1")


@pytest.mark.parametrize(
    "fields",
    [
        {"completed": True, "failed": True, "started": True, "planned": True, "failure_reason": "x"},
        {"completed": True},
        {"started": True},
        {"failed": True, "started": True, "planned": True},
        {"candidate_count": 1, "verified_source_count": 2},
    ],
)
def test_branch_coverage_is_internally_consistent(fields) -> None:
    with pytest.raises(ValidationError):
        BranchExecutionCoverage(branch=ResearchBranch.ACADEMIC, **fields)


def test_query_budget_is_bounded() -> None:
    with pytest.raises(ValidationError):
        QueryPlanLimits(max_queries_per_branch=10, max_total_queries=5)
    with pytest.raises(ValidationError):
        QueryPlanLimits(max_query_length=5)


# --- structural separation from ProjectState ----------------------------------------------


def test_project_state_has_no_field_that_can_hold_expansion_terms() -> None:
    """Release-blocking: expansion terms have no home in canonical state."""
    reachable = discover_types_from(ProjectState)
    for model in reachable:
        if isinstance(model, type) and issubclass(model, BaseModel):
            assert "expansion_terms" not in model.model_fields, model.__name__
    names = {t.__name__ for t in reachable}
    for research_type in ("ResearchQuery", "ResearchRun", "VerifiedQueryPlan", "ResearchInputSnapshot",
                          "OfficialRequirement", "SourceCandidate", "CandidateQueryPlan"):
        assert research_type not in names


def test_research_runs_live_on_graph_state_not_project_state() -> None:
    assert "research_runs" in EvaluationGraphState.model_fields
    assert not {"research_runs", "active_research_run_id", "candidate_query_plan"} & set(ProjectState.model_fields)


# --- official contracts -----------------------------------------------------------------


def test_official_weight_must_appear_in_the_verified_statement() -> None:
    assert _requirement(official_weight=30.0, official_weight_text="30%").official_weight == 30.0
    with pytest.raises(ValidationError, match="never invented"):
        _requirement(official_weight=15.0, official_weight_text="15%")
    with pytest.raises(ValidationError, match="never invented"):
        _requirement(official_weight=30.0)


def test_official_weight_only_on_judging_or_scoring_items() -> None:
    with pytest.raises(ValidationError, match="judging"):
        _requirement(category=OfficialRequirementCategory.DEADLINES,
                     official_weight=30.0, official_weight_text="30%")


def test_missing_official_weight_is_none_not_zero() -> None:
    assert _requirement().official_weight is None


def test_official_requirement_can_never_carry_advisory_authority() -> None:
    with pytest.raises(ValidationError, match="advisory"):
        _requirement(authority=CriteriaAuthority.AGENT_ADVISORY_RUBRIC)


def test_accepted_requirement_cannot_be_unverified() -> None:
    with pytest.raises(ValidationError, match="UNVERIFIED"):
        _requirement(status=OfficialRequirementStatus.UNVERIFIED)


def test_source_candidate_success_requires_content_and_hash() -> None:
    with pytest.raises(ValidationError):
        SourceCandidate(research_run_id=uuid4(), requested_url="https://www.mawhiba.sa/",
                        retrieval_status=RetrievalStatus.SUCCESS, retrieved_at=NOW, provider="p")
    with pytest.raises(ValidationError):
        SourceCandidate(research_run_id=uuid4(), requested_url="https://www.mawhiba.sa/",
                        retrieval_status=RetrievalStatus.TIMEOUT, captured_text="x",
                        retrieved_at=NOW, provider="p")


def _snapshot(**changes) -> OfficialSourceSnapshot:
    base = dict(source_id="SRC-001", candidate_id=uuid4(), url="https://www.mawhiba.sa/x",
                canonical_url="https://www.mawhiba.sa/x", domain="www.mawhiba.sa",
                retrieved_at=NOW, content_hash=HASH, captured_text="Rules")
    base.update(changes)
    return OfficialSourceSnapshot(**base)


def test_snapshot_exists_only_when_verified() -> None:
    with pytest.raises(ValidationError):
        _snapshot(verification_status=VerificationStatus.SEARCH_RESULT_ONLY)


def test_snapshot_builds_an_official_tier_a_source_record_not_evidence() -> None:
    record = _snapshot().to_source_record()
    assert record.source_type is SourceType.OFFICIAL_COMPETITION_SOURCE
    assert record.tier is SourceTier.TIER_A
    assert record.content_hash == HASH
    assert record.version_or_publication_date is None
    assert record.branch is ResearchBranch.OFFICIAL_REQUIREMENTS


def test_outcome_must_match_content() -> None:
    with pytest.raises(ValidationError, match="VERIFIED"):
        OfficialRequirementsResult(outcome=OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED)
    snapshot = _snapshot()
    with pytest.raises(ValidationError, match="UNAVAILABLE"):
        OfficialRequirementsResult(
            outcome=OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_UNAVAILABLE,
            snapshots=[snapshot], verified_sources=[snapshot.to_source_record()],
        )


def test_only_a_verified_outcome_counts_as_checked() -> None:
    snapshot = _snapshot()
    for outcome in OfficialRequirementsOutcome:
        kwargs = {}
        if outcome in (OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED,
                       OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED):
            kwargs = {"snapshots": [snapshot], "verified_sources": [snapshot.to_source_record()]}
        result = OfficialRequirementsResult(outcome=outcome, **kwargs)
        assert result.official_requirements_checked == (
            outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED
        )


def test_conflict_preserves_both_sides_and_explicit_resolution() -> None:
    a, b = uuid4(), uuid4()
    sides = [ConflictSide(requirement_id=a, source_id="SRC-001", statement="x"),
             ConflictSide(requirement_id=b, source_id="SRC-002", statement="y")]
    unresolved = OfficialRequirementConflict(category=OfficialRequirementCategory.DEADLINES,
                                             subject="deadline", sides=sides)
    assert unresolved.preferred_requirement_id is None
    with pytest.raises(ValidationError):
        OfficialRequirementConflict(category=OfficialRequirementCategory.DEADLINES, subject="d",
                                    sides=sides, preferred_requirement_id=a)
    with pytest.raises(ValidationError, match="two sources"):
        OfficialRequirementConflict(category=OfficialRequirementCategory.DEADLINES, subject="d",
                                    sides=[sides[0], sides[0]])
