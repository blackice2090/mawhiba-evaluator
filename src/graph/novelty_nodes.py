"""Phase 2I novelty / differentiation nodes.

Each node is a thin wrapper over one stage in ``src.research.novelty.pipeline``:
it reads the Phase 2I run on the active ``ResearchRun``, applies one stage, and
emits a successor research run with only ``novelty_differentiation`` replaced.
Nothing is held between nodes, so a node replayed after an interrupt starts
from the persisted run and reaches the same result (ADR-002); a stage that
already ran is a no-op.

No node writes the ``project`` channel. Claims, claim status, confidence,
evidence references, ``ProjectState.scores``, ``trust_gate`` and
``evaluation_status`` are untouched by construction, and so are the Phase
2C-2H artifacts on the same research run (ADR-020).

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``structured_model_provider`` -- absent = no comparison is executed and every
  claim posture is INSUFFICIENT_COMPARISON_EVIDENCE (never "no overlap");
* ``llm_settings`` -- optional model selection;
* ``research_settings`` -- ``ResearchSettings.novelty`` bounds.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.contracts import NodeResult, NodeStatus, WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY
from src.graph.nodes import _completion
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.research.novelty import pipeline as nd
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

NOVELTY_MODEL_PROVIDER_KEY = INTAKE_PROVIDER_KEY


def _cfg(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _settings(config: RunnableConfig | None) -> ResearchSettings:
    return _cfg(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _provider(config: RunnableConfig | None) -> Any:
    return _cfg(config).get(NOVELTY_MODEL_PROVIDER_KEY)


def _llm(config: RunnableConfig | None) -> LLMSettings | None:
    llm = _cfg(config).get(LLM_SETTINGS_KEY)
    return llm if isinstance(llm, LLMSettings) else None


def _done(state: EvaluationGraphState, node: NodeId, started_at: Any, summary: str, *,
          run: ResearchRun | None = None, status: NodeStatus = NodeStatus.SUCCEEDED,
          warnings: list[str] | None = None) -> dict[str, Any]:
    result = NodeResult(node=node.value, status=status, summary=summary, warnings=warnings or [])
    update: dict[str, Any] = {"status": WorkflowStatus.RUNNING}
    if run is not None:
        update["research_runs"] = {str(run.research_run_id): run}
    return {**update, **_completion(state, node, result, started_at, status=status)}


def _with(run: ResearchRun, subrun: Any) -> ResearchRun:
    return ResearchRun.model_validate({**dict(run), "novelty_differentiation": subrun})


def load_novelty_differentiation_run(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Open the Phase 2I run on the active research run, or decline to."""
    node = NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(state, node, started_at, f"Novelty/differentiation skipped: {reason}.",
                     status=NodeStatus.SKIPPED, warnings=[reason])
    if run.novelty_differentiation is not None:
        # Section 30: an existing run is resumed, never replaced; a finished one never reopened.
        return _done(state, node, started_at, "Phase 2I run already exists; resumed.", status=NodeStatus.SKIPPED)
    provider = _provider(config)
    llm = _llm(config) or LLMSettings()
    opened = nd.open_novelty_run(
        run, _settings(config).novelty, started_at,
        provider_name=getattr(provider, "name", None) if provider is not None else None,
        model_name=llm.extraction_model if provider is not None else None,
    )
    opened = nd.claims_stage(opened, list(state.project.claims))
    return _done(state, node, started_at,
                 f"Phase 2I run opened ({opened.status.value}); {len(opened.claim_inputs)} claims bound by hash.",
                 run=_with(run, opened))


def _stage(node: NodeId, apply: Any, summary: Any):
    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        run = state.active_research_run
        subrun = run.novelty_differentiation if run is not None else None
        if run is None or subrun is None or subrun.is_terminal:
            return _done(state, node, started_at, "No open Phase 2I run; nothing to do.", status=NodeStatus.SKIPPED)
        successor = apply(subrun, run, state, config)
        return _done(state, node, started_at, summary(successor), run=_with(run, successor))

    _node.__name__ = node.value.casefold()
    return _node


build_comparison_feature_inventory = _stage(
    NodeId.BUILD_COMPARISON_FEATURE_INVENTORY,
    lambda s, r, st, c: nd.inventory_stage(s, r, list(st.project.claims), _provider(c), _llm(c)),
    lambda s: f"{len(s.inventories)} feature inventories at exact claim anchors.",
)
profile_prior_art_candidates = _stage(
    NodeId.PROFILE_PRIOR_ART_CANDIDATES,
    lambda s, r, st, c: nd.profiles_stage(s, r),
    lambda s: f"{len(s.candidate_profiles)} candidates profiled (eligibility, capacity, independence, chronology).",
)
compare_claim_candidates = _stage(
    NodeId.COMPARE_CLAIM_CANDIDATES,
    lambda s, r, st, c: nd.compare_stage(s, r, list(st.project.claims), _provider(c), _llm(c)),
    lambda s: f"{sum(1 for x in s.comparisons if x.verified)} verified comparisons "
              f"({s.model_comparisons_performed} model calls).",
)
synthesize_claim_differentiation = _stage(
    NodeId.SYNTHESIZE_CLAIM_DIFFERENTIATION,
    lambda s, r, st, c: nd.synthesis_stage(s),
    lambda s: f"{len(s.claim_syntheses)} claim postures synthesized in Python.",
)
synthesize_project_differentiation = _stage(
    NodeId.SYNTHESIZE_PROJECT_DIFFERENTIATION,
    lambda s, r, st, c: nd.project_stage(s),
    lambda s: "Descriptive project summary built (counts only; no score).",
)


def finalize_novelty_differentiation(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.FINALIZE_NOVELTY_DIFFERENTIATION
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.novelty_differentiation is None or run.novelty_differentiation.is_terminal:
        return _done(state, node, started_at, "No open Phase 2I run; nothing to do.", status=NodeStatus.SKIPPED)
    successor = nd.finalize_stage(run.novelty_differentiation, started_at)
    return _done(
        state, node, started_at,
        "Phase 2I finished. Technical overlap / differentiation relative to a bounded candidate "
        "set -- not a legal novelty, patentability, infringement or copying conclusion, not a score.",
        run=_with(run, successor),
    )


__all__ = [
    "NOVELTY_MODEL_PROVIDER_KEY",
    "build_comparison_feature_inventory",
    "compare_claim_candidates",
    "finalize_novelty_differentiation",
    "load_novelty_differentiation_run",
    "profile_prior_art_candidates",
    "synthesize_claim_differentiation",
    "synthesize_project_differentiation",
]
