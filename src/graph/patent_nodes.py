"""Phase 2G patent prior-art research nodes.

Each node is a thin wrapper over one stage in ``src.research.patent.pipeline``:
it reads the ``PatentPriorArtRun`` carried by the active ``ResearchRun``, applies
exactly one stage, and emits a successor research run. Nothing is held between
nodes, so a node replayed after an interrupt starts from the persisted run and
reaches the same result (ADR-002).

None of these nodes writes the ``project`` channel. Claims, claim status,
confidence, evidence references, ``ProjectState.scores``, ``trust_gate`` and
``evaluation_status`` are untouched by construction, and so are the Phase 2C
evidence, Phase 2D alignments, Phase 2E sufficiency and Phase 2F scorecards on
the same research run: the only field a node replaces is
``ResearchRun.patent_prior_art`` (ADR-018).

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``patent_search_provider`` -- a ``PatentSearchProvider``. Absent means no
  credentials; the run records ``BLOCKED_AUTH`` and sends nothing.
* ``patent_search_cutoff`` -- an explicit ``PatentSearchCutoff``. Absent means
  ``NO_CUTOFF``; no date is ever substituted (section 7).
* ``structured_model_provider`` -- optional, for untrusted English expansion of
  Arabic claim text (section 11).
* ``research_privacy`` and ``research_settings`` -- the shared research keys.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.contracts import NodeResult, NodeStatus, WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY, RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.research.patent.pipeline import (
    DEFAULT_PATENT_PROVIDER,
    candidate_stage,
    execute_stage,
    family_stage,
    finalize_stage,
    open_patent_run,
    plan_stage,
    plannable_claims,
    snapshot_stage,
    verify_stage,
)
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.patent import NO_SEARCH_CUTOFF, PatentPriorArtRun, PatentSearchCutoff
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

PATENT_PROVIDER_KEY = "patent_search_provider"
PATENT_CUTOFF_KEY = "patent_search_cutoff"
PATENT_MODEL_PROVIDER_KEY = INTAKE_PROVIDER_KEY
LLM_SETTINGS_KEY = "llm_settings"


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _settings(config: RunnableConfig | None) -> ResearchSettings:
    return _configurable(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _privacy(config: RunnableConfig | None) -> ResearchPrivacyContext:
    return _configurable(config).get(RESEARCH_PRIVACY_KEY) or EMPTY_PRIVACY_CONTEXT


def _provider(config: RunnableConfig | None) -> Any:
    return _configurable(config).get(PATENT_PROVIDER_KEY)


def _cutoff(config: RunnableConfig | None) -> PatentSearchCutoff:
    cutoff = _configurable(config).get(PATENT_CUTOFF_KEY)
    return cutoff if isinstance(cutoff, PatentSearchCutoff) else NO_SEARCH_CUTOFF


def _open_patent_run(state: EvaluationGraphState) -> PatentPriorArtRun | None:
    run = state.active_research_run
    if run is None or run.patent_prior_art is None:
        return None
    patent = run.patent_prior_art
    return None if patent.is_terminal else patent


def _with_patent(run: ResearchRun, patent: PatentPriorArtRun) -> ResearchRun:
    """A successor research run with only ``patent_prior_art`` replaced."""
    return ResearchRun.model_validate({**dict(run), "patent_prior_art": patent})


def _done(
    state: EvaluationGraphState,
    node: NodeId,
    started_at: Any,
    summary: str,
    *,
    run: ResearchRun | None = None,
    status: NodeStatus = NodeStatus.SUCCEEDED,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = NodeResult(
        node=node.value, status=status, summary=summary, warnings=warnings or []
    )
    update: dict[str, Any] = {"status": WorkflowStatus.RUNNING}
    if run is not None:
        update["research_runs"] = {str(run.research_run_id): run}
    return {**update, **_completion(state, node, result, started_at, status=status)}


def _stage_node(node: NodeId, stage: Any, summary: str):
    """Build a node that applies one stage to the open patent run."""

    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        patent = _open_patent_run(state)
        if patent is None:
            return _done(
                state,
                node,
                started_at,
                "No open patent run; nothing to do.",
                status=NodeStatus.SKIPPED,
            )
        successor = stage(patent, config)
        run = state.active_research_run
        assert run is not None
        return _done(
            state,
            node,
            started_at,
            summary.format(run=successor),
            run=_with_patent(run, successor),
        )

    _node.__name__ = node.value.casefold()
    return _node


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_patent_research_run(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open a patent run on the active research run, or decline to."""
    node = NodeId.LOAD_PATENT_RESEARCH_RUN
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(
            state, node, started_at, f"Patent research skipped: {reason}.",
            status=NodeStatus.SKIPPED, warnings=[reason],
        )
    if run.patent_prior_art is not None:
        # Idempotency (section 29): an existing patent run is resumed, never
        # replaced. A finished one is never reopened.
        state_word = "finished" if run.patent_prior_art.is_terminal else "in progress"
        return _done(
            state, node, started_at,
            f"Patent run already {state_word}; resumed rather than reopened.",
            status=NodeStatus.SKIPPED,
        )
    # The run is addressed to the injected connector's provider, so a
    # connector this system may not dispatch to is refused at the dispatch
    # gate with a named reason rather than silently re-addressed (section 2).
    injected = _provider(config)
    patent = open_patent_run(
        run.research_run_id,
        settings=_settings(config).patent,
        cutoff=_cutoff(config),
        provider=getattr(injected, "provider_name", DEFAULT_PATENT_PROVIDER),
    )
    return _done(
        state, node, started_at,
        f"Patent run opened (cutoff {'supplied' if patent.search_cutoff.supplied else 'not supplied'}).",
        run=_with_patent(run, patent),
    )


def plan_patent_queries_node(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Plan queries from canonical claim text and the Phase 2E inventory."""
    node = NodeId.PLAN_PATENT_QUERIES
    started_at = workflow_now()
    patent = _open_patent_run(state)
    run = state.active_research_run
    if patent is None or run is None:
        return _done(state, node, started_at, "No open patent run; nothing to do.",
                     status=NodeStatus.SKIPPED)

    components: dict[str, list[str]] = {}
    if run.claim_sufficiency is not None:
        for assessment in run.claim_sufficiency.assessments:
            components[assessment.claim_id] = [
                c.text for c in assessment.component_inventory.components
            ]
    claims = plannable_claims(list(state.project.claims), components)
    model_provider = _configurable(config).get(PATENT_MODEL_PROVIDER_KEY)
    llm = _configurable(config).get(LLM_SETTINGS_KEY)
    model = (
        (llm.research_planning_model if isinstance(llm, LLMSettings) else "")
        if model_provider is not None
        else ""
    )
    successor = plan_stage(
        patent,
        claims,
        privacy=_privacy(config),
        model_provider=model_provider if model else None,
        model=model,
    )
    return _done(
        state, node, started_at,
        f"{len(successor.planned_queries)} patent queries planned; "
        f"{len(successor.excluded_claims)} claims excluded with a reason.",
        run=_with_patent(run, successor),
    )


execute_patent_search = _stage_node(
    NodeId.EXECUTE_PATENT_SEARCH,
    lambda patent, config: execute_stage(
        patent, _provider(config), privacy=_privacy(config)
    ),
    "Patent search: coverage {run.coverage_status.value}.",
)
verify_patent_publications = _stage_node(
    NodeId.VERIFY_PATENT_PUBLICATIONS,
    lambda patent, config: verify_stage(patent, privacy=_privacy(config)),
    "Search observations verified into bibliographic publications.",
)
resolve_patent_families = _stage_node(
    NodeId.RESOLVE_PATENT_FAMILIES,
    lambda patent, config: family_stage(patent, _provider(config)),
    "Families resolved; {run.independent_family_count} independent families.",
)
capture_patent_text = _stage_node(
    NodeId.CAPTURE_PATENT_TEXT,
    lambda patent, config: snapshot_stage(
        patent,
        _provider(config),
        fetch_description=_settings(config).patent.fetch_description,
    ),
    "Patent text snapshots captured.",
)
build_patent_candidates = _stage_node(
    NodeId.BUILD_PATENT_CANDIDATES,
    lambda patent, config: candidate_stage(patent),
    "Patent prior-art research candidates built.",
)
finalize_patent_research = _stage_node(
    NodeId.FINALIZE_PATENT_RESEARCH,
    lambda patent, config: finalize_stage(patent),
    "Patent research finished: outcome {run.outcome.value}, coverage "
    "{run.coverage_status.value}. Bounded search; not a novelty or legal opinion.",
)


__all__ = [
    "LLM_SETTINGS_KEY",
    "PATENT_CUTOFF_KEY",
    "PATENT_MODEL_PROVIDER_KEY",
    "PATENT_PROVIDER_KEY",
    "build_patent_candidates",
    "capture_patent_text",
    "execute_patent_search",
    "finalize_patent_research",
    "load_patent_research_run",
    "plan_patent_queries_node",
    "resolve_patent_families",
    "verify_patent_publications",
]
