"""Research branch coverage and run status. Execution facts, never evidence quality."""

from __future__ import annotations

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

NOT_EXECUTED_NOTE = "planned only; retrieval for this branch is not implemented in Phase 2A"


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


def decide_run_status(run: ResearchRun) -> ResearchRunStatus:
    """COMPLETED only when both Phase 2A stages succeeded; never a novelty signal."""
    planning_ok = run.query_plan is not None and not run.query_plan.issues
    official_ok = run.official_requirements_checked
    if planning_ok and official_ok:
        return ResearchRunStatus.COMPLETED
    if planning_ok or official_ok:
        return ResearchRunStatus.PARTIAL
    return ResearchRunStatus.FAILED
