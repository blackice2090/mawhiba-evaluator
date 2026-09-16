"""Phase 2A research nodes.

None of these nodes writes the ``project`` channel. Research reads canonical
state; its results live in a ``ResearchRun`` on the graph state (ADR-006). A
planning or official-branch failure is a research outcome recorded on the run,
not a workflow failure -- the workflow still completes and says what did not.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import DEFAULT_LLM_SETTINGS, LLMSettings
from src.graph.contracts import AuditEvent, NodeResult, NodeStatus, WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY, INTAKE_SETTINGS_KEY
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.state import ProjectState
from src.graph.workflow_state import EvaluationGraphState, new_thread_id
from src.research.coverage import build_branch_coverage, decide_run_status, initial_branch_coverage
from src.research.inputs import build_research_input
from src.research.official.extraction import (
    EXTRACTOR_VERSION,
    detect_official_conflicts,
    run_official_extraction,
    verify_official_requirements,
)
from src.research.official.sources import retrieve_official_candidates, verify_official_candidates
from src.research.planner import PLANNER_VERSION, run_query_planning
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.query_verification import verify_query_plan
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.common import ResearchBranch
from src.schemas.official import (
    ConflictResolutionBasis,
    OfficialRequirementsOutcome,
    OfficialRequirementsResult,
)
from src.schemas.research import (
    ResearchIssue,
    ResearchIssueCode,
    ResearchRun,
    ResearchRunStatus,
    ResearchRunVersions,
)
from src.workflow.clock import workflow_now
from src.workflow.errors import WorkflowError, WorkflowErrorCode

OFFICIAL_WEB_PROVIDER_KEY = "official_web_provider"
RESEARCH_SETTINGS_KEY = "research_settings"
RESEARCH_PRIVACY_KEY = "research_privacy"
RESEARCH_DATASET_VERSION_KEY = "research_dataset_version"

OFFICIAL = ResearchBranch.OFFICIAL_REQUIREMENTS


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _llm_settings(config: RunnableConfig | None) -> LLMSettings:
    return _configurable(config).get(INTAKE_SETTINGS_KEY) or DEFAULT_LLM_SETTINGS


def _research_settings(config: RunnableConfig | None) -> ResearchSettings:
    return _configurable(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _privacy(config: RunnableConfig | None) -> ResearchPrivacyContext:
    return _configurable(config).get(RESEARCH_PRIVACY_KEY) or EMPTY_PRIVACY_CONTEXT


def _emit(run: ResearchRun) -> dict[str, Any]:
    return {"research_runs": {str(run.research_run_id): run}}


def _issue(
    code: ResearchIssueCode, node: NodeId, message: str, branch: ResearchBranch | None = None
) -> ResearchIssue:
    return ResearchIssue(code=code, node=node.value, message=message, branch=branch)


def _require_run(state: EvaluationGraphState) -> ResearchRun:
    run = state.active_research_run
    if run is None:
        raise ValueError("research node reached without an active research run")
    return run


def _revalidated(result: OfficialRequirementsResult, **changes: Any) -> OfficialRequirementsResult:
    return OfficialRequirementsResult.model_validate({**dict(result), **changes})


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
    result = NodeResult(node=node.value, status=status, summary=summary, warnings=warnings or [])
    update: dict[str, Any] = dict(extra or {})
    if run is not None:
        update.update(_emit(run))
    return {**update, **_completion(state, node, result, started_at, status=status)}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_project_state(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Validate canonical state and open (or, on replay, reuse) a research run."""
    node = NodeId.LOAD_PROJECT_STATE
    started_at = workflow_now()
    try:
        project = ProjectState.model_validate(state.project.model_dump())
    except ValueError as exc:
        error = WorkflowError(
            code=WorkflowErrorCode.STATE_VALIDATION_FAILED,
            node=node.value,
            message=f"canonical ProjectState is invalid: {str(exc).splitlines()[0]}",
            recoverable=False,
        )
        result = NodeResult(node=node.value, status=NodeStatus.FAILED,
                            summary="ProjectState validation failed.", errors=[error])
        return {"status": WorkflowStatus.FAILED, "errors": [error],
                **_completion(state, node, result, started_at, status=NodeStatus.FAILED)}

    existing = state.active_research_run
    if (
        existing is not None
        and not existing.is_terminal
        and existing.project_version_id == project.project_version_id
    ):
        run = existing
    else:
        cfg = _configurable(config)
        model_provider = cfg.get(INTAKE_PROVIDER_KEY)
        web_provider = cfg.get(OFFICIAL_WEB_PROVIDER_KEY)
        run = ResearchRun(
            project_id=project.project_id,
            project_version_id=project.project_version_id,
            planner_version=PLANNER_VERSION,
            versions=ResearchRunVersions(
                planner_prompt_version=PLANNER_VERSION,
                official_extractor_prompt_version=EXTRACTOR_VERSION,
                provider=getattr(model_provider, "name", None),
                model=_llm_settings(config).research_planning_model if model_provider else None,
                official_web_provider=getattr(web_provider, "name", None),
                dataset_version=cfg.get(RESEARCH_DATASET_VERSION_KEY),
            ),
            status=ResearchRunStatus.PLANNING,
            branch_coverage=initial_branch_coverage(),
            started_at=started_at,
        )

    return _done(
        state, node, started_at, "Research run opened.", run=run,
        extra={
            "thread_id": state.thread_id or new_thread_id(state.run_id),
            "status": WorkflowStatus.RUNNING,
            "active_research_run_id": run.research_run_id,
            "audit_events": [AuditEvent(run_id=state.run_id, node=node.value,
                                        event_type="RESEARCH_RUN_STARTED",
                                        subject=str(run.research_run_id))],
        },
    )


def validate_research_input(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.VALIDATE_RESEARCH_INPUT
    started_at = workflow_now()
    run = _require_run(state)
    snapshot = build_research_input(state.project, _privacy(config))
    errors = list(run.errors)
    warnings: list[str] = []
    if snapshot.is_empty:
        errors.append(_issue(ResearchIssueCode.INSUFFICIENT_RESEARCH_INPUT, node,
                             "no trusted canonical research input; planning is skipped"))
        warnings.append("no trusted research input")
    run = run.evolve(research_input=snapshot, errors=errors)
    return _done(state, node, started_at,
                 f"Research input: {len(snapshot.fields)} field(s), {len(snapshot.claims)} claim(s), "
                 f"{snapshot.redaction_count} redaction(s).", run=run, warnings=warnings)


def research_query_planner(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.RESEARCH_QUERY_PLANNER
    started_at = workflow_now()
    run = _require_run(state)
    snapshot = run.research_input
    if snapshot is None or snapshot.is_empty:
        return _done(state, node, started_at, "Planning skipped: no trusted input.",
                     status=NodeStatus.SKIPPED)

    provider = _configurable(config).get(INTAKE_PROVIDER_KEY)
    if provider is None:
        run = run.evolve(errors=[*run.errors, _issue(
            ResearchIssueCode.PLANNER_PROVIDER_MISSING, node, "no structured model provider injected")])
        return _done(state, node, started_at, "Planning skipped: no model provider.", run=run,
                     status=NodeStatus.SKIPPED, warnings=["no model provider"])

    call = run_query_planning(snapshot, provider, _llm_settings(config), _research_settings(config).limits)
    if not call.succeeded:
        detail = call.refusal or call.error or "no detail"
        run = run.evolve(errors=[*run.errors, _issue(
            ResearchIssueCode.PLANNER_MODEL_FAILED, node, f"{call.status.value}: {detail}")])
        return _done(state, node, started_at, f"Planner call failed ({call.status.value}).",
                     run=run, warnings=[call.status.value], extra={"candidate_query_plan": None})

    return _done(state, node, started_at,
                 f"Candidate plan received ({len(call.parsed.queries)} queries); not yet trusted.",
                 extra={"candidate_query_plan": call.parsed})


def verify_query_plan_node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.VERIFY_QUERY_PLAN
    started_at = workflow_now()
    run = _require_run(state)
    candidate = state.candidate_query_plan
    if candidate is None:
        return _done(state, node, started_at, "No candidate plan to verify.", status=NodeStatus.SKIPPED)

    plan = verify_query_plan(
        state.project,
        candidate,
        research_run_id=run.research_run_id,
        planner_version=PLANNER_VERSION,
        limits=_research_settings(config).limits,
        privacy=_privacy(config),
    )
    issues = [_issue(code, node, f"query plan issue: {code.value}") for code in plan.issues]
    run = run.evolve(query_plan=plan, status=ResearchRunStatus.RUNNING, errors=[*run.errors, *issues])
    return _done(state, node, started_at,
                 f"Accepted {len(plan.accepted_queries)} query(ies); rejected {len(plan.rejected_queries)}; "
                 f"duplicates removed {plan.duplicates_removed}.",
                 run=run, warnings=[i.message for i in issues])


def official_requirements_retrieval(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.OFFICIAL_REQUIREMENTS_RETRIEVAL
    started_at = workflow_now()
    run = _require_run(state)
    official_settings = _research_settings(config).official
    seeds = official_settings.seeds
    target_edition = official_settings.target_edition
    provider = _configurable(config).get(OFFICIAL_WEB_PROVIDER_KEY)

    if provider is None:
        result = OfficialRequirementsResult(
            outcome=OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_UNAVAILABLE,
            seeds=seeds,
            target_edition=target_edition,
        )
        run = run.evolve(status=ResearchRunStatus.RUNNING, official_requirements=result, errors=[
            *run.errors,
            _issue(ResearchIssueCode.OFFICIAL_WEB_PROVIDER_MISSING, node, "no official web provider injected", OFFICIAL),
            _issue(ResearchIssueCode.OFFICIAL_REQUIREMENTS_UNAVAILABLE, node,
                   "official requirements were not retrieved; no fallback to model knowledge", OFFICIAL),
        ])
        return _done(state, node, started_at, "Official retrieval unavailable: no provider.",
                     run=run, warnings=["OFFICIAL_REQUIREMENTS_UNAVAILABLE"])

    candidates = retrieve_official_candidates(provider, seeds, run.research_run_id)
    result = OfficialRequirementsResult(
        seeds=seeds,
        target_edition=target_edition,
        web_provider=provider.name,
        candidates=candidates,
    )
    run = run.evolve(status=ResearchRunStatus.RUNNING, official_requirements=result)
    return _done(state, node, started_at, f"Retrieved {len(candidates)} source candidate(s); not yet trusted.",
                 run=run)


def verify_official_sources(state: EvaluationGraphState) -> dict[str, Any]:
    node = NodeId.VERIFY_OFFICIAL_SOURCES
    started_at = workflow_now()
    run = _require_run(state)
    result = run.official_requirements
    if result is None or result.outcome is not OfficialRequirementsOutcome.NOT_STARTED:
        return _done(state, node, started_at, "No candidates to verify.", status=NodeStatus.SKIPPED)

    decisions, snapshots, records = verify_official_candidates(
        result.candidates, target_edition=result.target_edition
    )
    errors = list(run.errors)
    outcome = OfficialRequirementsOutcome.NOT_STARTED
    if not snapshots:
        outcome = OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_UNAVAILABLE
        errors.append(_issue(ResearchIssueCode.OFFICIAL_REQUIREMENTS_UNAVAILABLE, node,
                             "no candidate passed official source verification", OFFICIAL))
    result = _revalidated(result, decisions=decisions, snapshots=snapshots,
                          verified_sources=records, outcome=outcome)
    run = run.evolve(official_requirements=result, errors=errors)
    rejected = [d for d in decisions if not d.accepted]
    return _done(state, node, started_at,
                 f"Verified {len(snapshots)} official snapshot(s); rejected {len(rejected)} candidate(s).",
                 run=run, warnings=[f"rejected {d.requested_url}: {d.rejection_reason.value}" for d in rejected])


def extract_official_requirements(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.EXTRACT_OFFICIAL_REQUIREMENTS
    started_at = workflow_now()
    run = _require_run(state)
    result = run.official_requirements
    if result is None or not result.snapshots or result.outcome is not OfficialRequirementsOutcome.NOT_STARTED:
        return _done(state, node, started_at, "No verified official snapshot to extract from.",
                     status=NodeStatus.SKIPPED)

    provider = _configurable(config).get(INTAKE_PROVIDER_KEY)
    settings = _llm_settings(config)
    errors = list(run.errors)
    accepted, rejected, failed = [], [], []

    if provider is not None:
        for snapshot in result.snapshots:
            call = run_official_extraction(snapshot, provider, settings)
            if not call.succeeded:
                failed.append(snapshot.source_id)
                errors.append(_issue(ResearchIssueCode.OFFICIAL_EXTRACTION_FAILED, node,
                                     f"{snapshot.source_id}: {call.status.value}", OFFICIAL))
                continue
            ok, bad = verify_official_requirements(snapshot, call.parsed)
            accepted.extend(ok)
            rejected.extend(bad)
    else:
        errors.append(_issue(ResearchIssueCode.OFFICIAL_EXTRACTION_FAILED, node,
                             "no structured model provider injected", OFFICIAL))

    metadata = {
        "extractor_prompt_version": EXTRACTOR_VERSION,
        "extraction_provider": getattr(provider, "name", None),
        "extraction_model": settings.official_extraction_model if provider else None,
    }
    if provider is None or len(failed) == len(result.snapshots):
        result = _revalidated(result, outcome=OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED,
                              **metadata)
    else:
        requirements, conflicts = detect_official_conflicts(accepted, result.snapshots)
        for conflict in conflicts:
            if conflict.resolution_basis is ConflictResolutionBasis.UNRESOLVED:
                errors.append(_issue(ResearchIssueCode.OFFICIAL_SOURCE_CONFLICT, node,
                                     f"unresolved official conflict: {conflict.subject}", OFFICIAL))
        result = _revalidated(result, outcome=OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED,
                              requirements=requirements, rejected_requirements=rejected,
                              conflicts=conflicts, **metadata)

    run = run.evolve(official_requirements=result, errors=errors)
    return _done(state, node, started_at,
                 f"Official outcome {result.outcome.value}: {len(result.requirements)} requirement(s), "
                 f"{len(result.rejected_requirements)} rejected, {len(result.conflicts)} conflict(s).", run=run)


def update_research_coverage(state: EvaluationGraphState) -> dict[str, Any]:
    node = NodeId.UPDATE_RESEARCH_COVERAGE
    started_at = workflow_now()
    run = _require_run(state)
    coverage = build_branch_coverage(run)
    final = run.evolve(branch_coverage=coverage)
    status = decide_run_status(final)
    final = final.evolve(status=status, completed_at=workflow_now())
    return _done(
        state, node, started_at, f"Research run finished with status {status.value}.", run=final,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [AuditEvent(run_id=state.run_id, node=node.value,
                                        event_type="RESEARCH_RUN_FINISHED", subject=status.value)],
        },
    )
