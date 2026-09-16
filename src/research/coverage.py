"""Research branch coverage and run status. Execution facts, never evidence quality."""

from __future__ import annotations

from src.schemas.academic import AcademicBranchOutcome
from src.schemas.common import ResearchBranch
from src.schemas.official import OfficialRequirementsOutcome
from src.schemas.research import BranchExecutionCoverage, ResearchRun, ResearchRunStatus

REQUIRED_RESEARCH_BRANCHES: frozenset[ResearchBranch] = frozenset(
    {ResearchBranch.OFFICIAL_REQUIREMENTS, ResearchBranch.ACADEMIC, ResearchBranch.PATENT}
)
"""Policy V1: official rules (2.4) and the academic and patent searches required
before a novelty judgement (2.3, 13). Product, open-source and standards are
relevant per project and are not required by default."""

EXECUTED_BRANCHES_PHASE_2A: frozenset[ResearchBranch] = frozenset(
    {ResearchBranch.OFFICIAL_REQUIREMENTS}
)

EXECUTED_BRANCHES: frozenset[ResearchBranch] = frozenset(
    {ResearchBranch.OFFICIAL_REQUIREMENTS, ResearchBranch.ACADEMIC}
)
"""Branches with an implemented retrieval path. Phase 2B added ACADEMIC."""

NOT_EXECUTED_NOTE = "planned only; retrieval for this branch is not implemented in Phase 2A"

ACADEMIC_NOT_RUN_NOTE = "planned only; the academic branch has not been executed for this run"


def initial_branch_coverage() -> list[BranchExecutionCoverage]:
    return [
        BranchExecutionCoverage(branch=branch, required=branch in REQUIRED_RESEARCH_BRANCHES)
        for branch in ResearchBranch
    ]


def build_branch_coverage(run: ResearchRun) -> list[BranchExecutionCoverage]:
    coverage: list[BranchExecutionCoverage] = []
    for branch in ResearchBranch:
        required = branch in REQUIRED_RESEARCH_BRANCHES
        if branch is ResearchBranch.OFFICIAL_REQUIREMENTS:
            result = run.official_requirements
            outcome = result.outcome if result else OfficialRequirementsOutcome.NOT_STARTED
            failed = outcome in (
                OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_UNAVAILABLE,
                OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED,
            )
            coverage.append(
                BranchExecutionCoverage(
                    branch=branch,
                    required=required,
                    planned=result is not None,
                    started=result is not None,
                    completed=outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED,
                    failed=failed,
                    candidate_count=len(result.candidates) if result else 0,
                    verified_source_count=len(result.snapshots) if result else 0,
                    failure_reason=outcome.value if failed else None,
                )
            )
            continue

        queries = run.query_plan.accepted_for(branch) if run.query_plan else []

        if branch is ResearchBranch.ACADEMIC:
            coverage.append(_academic_coverage(run, required, len(queries)))
            continue

        coverage.append(
            BranchExecutionCoverage(
                branch=branch,
                required=required,
                planned=bool(queries),
                query_count=len(queries),
                note=NOT_EXECUTED_NOTE if queries else None,
            )
        )
    return coverage


def _academic_coverage(
    run: ResearchRun, required: bool, planned_query_count: int
) -> BranchExecutionCoverage:
    """Operational coverage for the Phase 2B academic branch.

    Counters describe execution only. ``verified_source_count`` counts logical
    sources whose metadata verified -- it says nothing about whether any of them
    is relevant, sound or supports anything (ADR-010).
    """
    result = run.academic_research
    if result is None or result.outcome is AcademicBranchOutcome.NOT_RUN:
        return BranchExecutionCoverage(
            branch=ResearchBranch.ACADEMIC,
            required=required,
            planned=bool(planned_query_count),
            query_count=planned_query_count,
            note=ACADEMIC_NOT_RUN_NOTE if planned_query_count else None,
        )

    failed = result.outcome is AcademicBranchOutcome.FAILED
    return BranchExecutionCoverage(
        branch=ResearchBranch.ACADEMIC,
        required=required,
        planned=True,
        started=True,
        completed=not failed,
        failed=failed,
        query_count=result.budget.queries_executed,
        candidate_count=len(result.candidates),
        verified_source_count=len(result.logical_sources),
        provider_success_count=result.provider_success_count,
        provider_failure_count=result.provider_failure_count,
        provider_empty_count=result.provider_empty_count,
        failure_reason=result.outcome.value if failed else None,
        note=f"academic branch outcome {result.outcome.value}",
    )


def decide_run_status(run: ResearchRun) -> ResearchRunStatus:
    """COMPLETED only when both Phase 2A stages succeeded; never a novelty signal."""
    planning_ok = run.query_plan is not None and not run.query_plan.issues
    official_ok = run.official_requirements_checked
    if planning_ok and official_ok:
        return ResearchRunStatus.COMPLETED
    if planning_ok or official_ok:
        return ResearchRunStatus.PARTIAL
    return ResearchRunStatus.FAILED
