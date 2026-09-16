"""Phase 2B academic research nodes.

None of these nodes writes the ``project`` channel, and none of them calls a
model. Academic retrieval is entirely deterministic: given the same verified
query plan and the same provider responses, it produces the same candidates, the
same logical sources and the same coverage. That is what makes an academic
result auditable and what makes prompt injection in a provider abstract a
non-event -- there is no prompt in this branch to inject into.

Every node stores its output on the ``AcademicRetrievalResult`` carried by the
``ResearchRun``, so a replay after an interrupt recomputes from data already on
the state rather than from anything held in memory between nodes.

A provider failure is a research outcome recorded on the run, never a workflow
failure: the branch still completes and says what did not work.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.graph.contracts import AuditEvent, NodeResult, NodeStatus, WorkflowStatus
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY, RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.research.academic.capabilities import connector_versions
from src.research.academic.dedup import resolve_logical_sources
from src.research.academic.dispatch import (
    DispatchOutcome,
    aggregate_branch_outcome,
    build_budget_report,
    build_provider_queries,
    collect_candidates,
    dispatch_academic_queries,
    enforce_query_budget,
    select_academic_queries,
)
from src.research.academic.provider import AcademicSearchProvider
from src.research.academic.verification import verify_academic_candidates
from src.research.coverage import build_branch_coverage
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.academic import (
    AcademicBranchOutcome,
    AcademicBudgetReport,
    AcademicRetrievalResult,
    AcademicSearchQuery,
    AcademicSourceCandidate,
)
from src.schemas.common import ResearchBranch
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

ACADEMIC_PROVIDERS_KEY = "academic_search_providers"
"""Runtime config key. Providers are injected per run, exactly as the model and
official web providers are, which is what keeps graph construction
credential-free and the standard suite offline."""

ACADEMIC = ResearchBranch.ACADEMIC


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _research_settings(config: RunnableConfig | None) -> ResearchSettings:
    return _configurable(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _privacy(config: RunnableConfig | None) -> ResearchPrivacyContext:
    return _configurable(config).get(RESEARCH_PRIVACY_KEY) or EMPTY_PRIVACY_CONTEXT


def _providers(config: RunnableConfig | None) -> list[AcademicSearchProvider]:
    return list(_configurable(config).get(ACADEMIC_PROVIDERS_KEY) or [])


def _emit(run: ResearchRun) -> dict[str, Any]:
    return {"research_runs": {str(run.research_run_id): run}}


def _require_run(state: EvaluationGraphState) -> ResearchRun:
    run = state.active_research_run
    if run is None:
        raise ValueError("academic node reached without an active research run")
    return run


def _revalidated(
    result: AcademicRetrievalResult, **changes: Any
) -> AcademicRetrievalResult:
    """A successor result, re-validated in full. Nothing is mutated in place.

    The branch outcome is recomputed on every step from what is known at that
    step, so the stored outcome always describes the stored content rather than
    lagging a stage behind it. The final value is the one computed once logical
    sources exist.
    """
    merged: dict[str, Any] = {**dict(result), **changes}
    if "outcome" not in changes:
        sources = merged["logical_sources"] or merged["candidates"]
        merged["outcome"] = aggregate_branch_outcome(
            list(merged["provider_results"]), len(sources)
        )
    return AcademicRetrievalResult.model_validate(merged)


def _done(
    state: EvaluationGraphState,
    node: NodeId,
    started_at: Any,
    summary: str,
    *,
    run: ResearchRun | None = None,
    status: NodeStatus = NodeStatus.SUCCEEDED,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = NodeResult(
        node=node.value, status=status, summary=summary, warnings=warnings or []
    )
    update: dict[str, Any] = dict(extra or {})
    if run is not None:
        update.update(_emit(run))
    return {**update, **_completion(state, node, result, started_at, status=status)}


def _empty_budget(settings: ResearchSettings) -> AcademicBudgetReport:
    academic = settings.academic
    return AcademicBudgetReport(
        max_queries_per_run=academic.max_academic_queries_per_run,
        max_results_per_query_per_provider=academic.max_results_per_query_per_provider,
        max_results_per_provider_per_run=academic.max_results_per_provider_per_run,
        max_total_candidates=academic.max_total_academic_candidates,
    )


def _accepted_candidates(
    result: AcademicRetrievalResult,
) -> list[AcademicSourceCandidate]:
    """Candidates that survived verification, derived from the stored decisions.

    Derived rather than stored separately so a replay cannot produce a set that
    disagrees with the decision ledger.
    """
    refused = {d.candidate_id for d in result.decisions if not d.accepted}
    return [c for c in result.candidates if c.candidate_id not in refused]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_verified_query_plan(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open the academic branch on an existing, still-open research run.

    Academic retrieval consumes the Phase 2A verified query plan and nothing
    else. With no run, no plan or a run already finished, the branch records
    that it did not execute instead of inventing a reason to search.
    """
    node = NodeId.LOAD_VERIFIED_QUERY_PLAN
    started_at = workflow_now()
    run = state.active_research_run
    settings = _research_settings(config)

    if run is None or run.query_plan is None or run.is_terminal:
        reason = (
            "no active research run"
            if run is None
            else "the research run is already terminal"
            if run.is_terminal
            else "the research run carries no verified query plan"
        )
        return _done(
            state,
            node,
            started_at,
            f"Academic branch skipped: {reason}.",
            status=NodeStatus.SKIPPED,
            warnings=[reason],
            extra={"status": WorkflowStatus.RUNNING},
        )

    result = run.academic_research or AcademicRetrievalResult(
        research_run_id=run.research_run_id,
        providers=list(settings.academic.enabled_providers),
        connector_versions=connector_versions(),
        budget=_empty_budget(settings),
    )
    run = run.evolve(academic_research=result)
    return _done(
        state,
        node,
        started_at,
        f"Academic branch opened over {len(run.query_plan.accepted_queries)} "
        f"accepted planned query(ies).",
        run=run,
        extra={
            "status": WorkflowStatus.RUNNING,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="ACADEMIC_BRANCH_STARTED",
                    subject=str(run.research_run_id),
                )
            ],
        },
    )


def select_academic_queries_node(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Decide which planned queries the academic branch is allowed to execute."""
    node = NodeId.SELECT_ACADEMIC_QUERIES
    started_at = workflow_now()
    run = _require_run(state)
    if run.academic_research is None or run.query_plan is None:
        return _done(
            state, node, started_at, "No open academic branch.", status=NodeStatus.SKIPPED
        )

    settings = _research_settings(config)
    selection = select_academic_queries(
        run.query_plan, settings.academic, _privacy(config)
    )
    result = _revalidated(
        run.academic_research,
        excluded_queries=selection.excluded,
        budget=_revalidate_budget(
            run.academic_research.budget, queries_available=selection.available
        ),
    )
    run = run.evolve(academic_research=result)
    return _done(
        state,
        node,
        started_at,
        f"Eligible academic queries: {selection.available}; "
        f"excluded {len(selection.excluded)}.",
        run=run,
        warnings=sorted({e.reason.value for e in selection.excluded}),
    )


def _revalidate_budget(budget: AcademicBudgetReport, **changes: Any) -> AcademicBudgetReport:
    return AcademicBudgetReport.model_validate({**dict(budget), **changes})


def enforce_academic_budget(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Apply the per-run query budget and build one request per provider.

    Budget exhaustion is truncation, recorded as such. It is never a provider
    failure and never a branch failure.
    """
    node = NodeId.ENFORCE_ACADEMIC_BUDGET
    started_at = workflow_now()
    run = _require_run(state)
    if run.academic_research is None or run.query_plan is None:
        return _done(
            state, node, started_at, "No open academic branch.", status=NodeStatus.SKIPPED
        )

    settings = _research_settings(config)
    selection = enforce_query_budget(
        select_academic_queries(run.query_plan, settings.academic, _privacy(config)),
        settings.academic,
    )
    provider_queries = build_provider_queries(
        selection, settings.academic, run.research_run_id
    )
    result = _revalidated(
        run.academic_research,
        selected_queries=provider_queries,
        excluded_queries=selection.excluded,
        budget=build_budget_report(
            settings.academic, selection, DispatchOutcome(), accepted_candidates=0
        ),
    )
    run = run.evolve(academic_research=result)
    warnings = ["query budget truncated the plan"] if selection.truncated else []
    return _done(
        state,
        node,
        started_at,
        f"Executing {len(selection.eligible)} query(ies) across "
        f"{len(settings.academic.enabled_providers)} provider(s); "
        f"{selection.truncated} truncated by budget.",
        run=run,
        warnings=warnings,
    )


def dispatch_academic_providers(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Run every request. One provider's failure never removes another's result."""
    node = NodeId.DISPATCH_ACADEMIC_PROVIDERS
    started_at = workflow_now()
    run = _require_run(state)
    result = run.academic_research
    if result is None or not result.selected_queries:
        return _done(
            state,
            node,
            started_at,
            "No academic query to dispatch.",
            status=NodeStatus.SKIPPED,
        )

    providers = _providers(config)
    if not providers:
        return _done(
            state,
            node,
            started_at,
            "Academic retrieval skipped: no provider injected.",
            status=NodeStatus.SKIPPED,
            warnings=["no academic provider injected; no fallback to model knowledge"],
        )

    settings = _research_settings(config)
    results = dispatch_academic_queries(
        list(result.selected_queries), providers, settings.academic
    )
    result = _revalidated(result, provider_results=results)
    run = run.evolve(academic_research=result)
    failures = sorted(
        {r.status.value for r in results if r.failed}
    )
    return _done(
        state,
        node,
        started_at,
        f"{len(results)} provider call(s): {result.provider_success_count} with "
        f"records, {result.provider_empty_count} empty, "
        f"{result.provider_failure_count} failed.",
        run=run,
        warnings=failures,
    )


def normalize_academic_results(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Accumulate normalized candidates under the run-level budgets."""
    node = NodeId.NORMALIZE_ACADEMIC_RESULTS
    started_at = workflow_now()
    run = _require_run(state)
    result = run.academic_research
    if result is None or not result.provider_results:
        return _done(
            state,
            node,
            started_at,
            "No provider result to normalize.",
            status=NodeStatus.SKIPPED,
        )

    settings = _research_settings(config)
    outcome = collect_candidates(list(result.provider_results), settings.academic)
    budget = _revalidate_budget(
        result.budget,
        candidates_returned=outcome.returned_count,
        candidates_accepted=len(outcome.candidates),
        candidates_truncated_per_provider=outcome.truncated_per_provider,
        candidates_truncated_total=outcome.truncated_total,
    )
    result = _revalidated(
        result,
        candidates=outcome.candidates,
        rejected_candidates=outcome.rejected,
        budget=budget,
    )
    run = run.evolve(academic_research=result)
    return _done(
        state,
        node,
        started_at,
        f"Normalized {len(outcome.candidates)} candidate(s); rejected "
        f"{len(outcome.rejected)} provider record(s).",
        run=run,
        warnings=["candidate budget truncated the results"] if budget.truncated else [],
    )


def verify_academic_candidates_node(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Deterministic source verification. Metadata only, never science."""
    node = NodeId.VERIFY_ACADEMIC_CANDIDATES
    started_at = workflow_now()
    run = _require_run(state)
    result = run.academic_research
    if result is None or not result.candidates:
        return _done(
            state,
            node,
            started_at,
            "No candidate to verify.",
            status=NodeStatus.SKIPPED,
        )

    queries: dict[str, AcademicSearchQuery] = {
        str(q.query_id): q for q in result.selected_queries
    }
    outcome = verify_academic_candidates(
        list(result.candidates), queries, _privacy(config)
    )
    result = _revalidated(
        result,
        decisions=outcome.decisions,
        rejected_candidates=[*result.rejected_candidates, *outcome.rejected],
    )
    run = run.evolve(academic_research=result)
    return _done(
        state,
        node,
        started_at,
        f"Verified {len(outcome.accepted)} candidate(s); rejected "
        f"{len(outcome.rejected)}.",
        run=run,
        warnings=sorted({r.reason.value for r in outcome.rejected}),
    )


def deduplicate_academic_sources(state: EvaluationGraphState) -> dict[str, Any]:
    """Resolve cross-provider identity into logical sources (ADR-009)."""
    node = NodeId.DEDUPLICATE_ACADEMIC_SOURCES
    started_at = workflow_now()
    run = _require_run(state)
    result = run.academic_research
    if result is None or not result.candidates:
        return _done(
            state,
            node,
            started_at,
            "No candidate to deduplicate.",
            status=NodeStatus.SKIPPED,
        )

    accepted = _accepted_candidates(result)
    sources, decisions = resolve_logical_sources(accepted, run.research_run_id)
    rejected_decisions = [d for d in result.decisions if not d.accepted]
    result = _revalidated(
        result,
        logical_sources=sources,
        verified_sources=[s.to_source_record() for s in sources],
        decisions=[*rejected_decisions, *decisions],
    )
    run = run.evolve(academic_research=result)
    duplicates = len(accepted) - len(sources)
    return _done(
        state,
        node,
        started_at,
        f"{len(accepted)} verified candidate(s) resolved into {len(sources)} "
        f"logical source(s); {duplicates} cross-provider duplicate(s) merged.",
        run=run,
    )


def merge_provider_observations(state: EvaluationGraphState) -> dict[str, Any]:
    """Finish the merge and decide the branch outcome.

    Deduplication already attached every provider observation to its logical
    source; this node records what the merge produced and sets the aggregate
    verdict, so the branch outcome is a separate, inspectable step rather than a
    side effect of identity resolution.
    """
    node = NodeId.MERGE_PROVIDER_OBSERVATIONS
    started_at = workflow_now()
    run = _require_run(state)
    result = run.academic_research
    if result is None:
        return _done(
            state, node, started_at, "No open academic branch.", status=NodeStatus.SKIPPED
        )

    outcome = aggregate_branch_outcome(
        list(result.provider_results), len(result.logical_sources)
    )
    result = _revalidated(result, outcome=outcome)
    run = run.evolve(academic_research=result)
    multi_provider = sum(1 for s in result.logical_sources if len(s.providers) > 1)
    conflicts = result.conflicts
    return _done(
        state,
        node,
        started_at,
        f"Branch outcome {outcome.value}: {len(result.logical_sources)} logical "
        f"source(s), {multi_provider} observed by more than one provider, "
        f"{len(conflicts)} metadata conflict(s).",
        run=run,
        warnings=sorted({c.field_name for c in conflicts}),
    )


def update_academic_coverage(state: EvaluationGraphState) -> dict[str, Any]:
    """Refresh branch coverage. The research run deliberately stays open.

    Phase 2A's ``UPDATE_RESEARCH_COVERAGE`` is what makes a run terminal. The
    academic branch is one of several, so finishing it must not freeze the run
    that the patent, product and open-source branches will later write to.
    """
    node = NodeId.UPDATE_ACADEMIC_COVERAGE
    started_at = workflow_now()
    run = _require_run(state)
    run = run.evolve(branch_coverage=build_branch_coverage(run))
    coverage = run.coverage_for(ACADEMIC)
    outcome = (
        run.academic_research.outcome
        if run.academic_research
        else AcademicBranchOutcome.NOT_RUN
    )
    return _done(
        state,
        node,
        started_at,
        f"Academic coverage updated: {coverage.verified_source_count if coverage else 0} "
        f"verified source(s) from {coverage.query_count if coverage else 0} query(ies).",
        run=run,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="ACADEMIC_BRANCH_FINISHED",
                    subject=outcome.value,
                )
            ],
        },
    )


__all__ = [
    "ACADEMIC_PROVIDERS_KEY",
    "deduplicate_academic_sources",
    "dispatch_academic_providers",
    "enforce_academic_budget",
    "load_verified_query_plan",
    "merge_provider_observations",
    "normalize_academic_results",
    "select_academic_queries_node",
    "update_academic_coverage",
    "verify_academic_candidates_node",
]
