"""Phase 3B experiment review nodes.

Each node is a thin wrapper over one stage in ``src.research.experiments.pipeline``:
it reads the Phase 3B run on the active ``ResearchRun``, applies one stage, and
emits a successor research run with only ``experiment_review`` replaced. Nothing
is held between nodes, so a node replayed after an interrupt starts from the
persisted run and reaches the same result (ADR-002); a stage that already ran is a
no-op, and a replay makes no model call. Transient model DTOs never leave a stage.

Verification runs INSIDE the node that receives untrusted model output: unverified
model output never reaches a checkpoint (ADR-023).

No node writes the ``project`` channel. Claims, ``ProjectState.experiments``,
``ProjectState.results``, ``ProjectState.scores``, ``trust_gate`` and
``evaluation_status`` are untouched by construction, and so are the Phase 2A-3A
artifacts on the same research run.

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``structured_model_provider`` -- absent = nothing can be segmented
  (``MODEL_PROVIDER_MISSING``), never "no experiments";
* ``llm_settings`` -- optional model selection;
* ``research_settings`` -- ``ResearchSettings.experiment`` bounds.

Phase 3B has no search provider key and the graph contains no discovery node.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.contracts import NodeStatus
from src.graph.novelty_nodes import _done, _llm, _provider, _settings
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState
from src.research.experiments import pipeline as xp
from src.schemas.experiment_review import ExperimentReviewRun
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

EXPERIMENT_MODEL_PROVIDER_KEY = "structured_model_provider"


def _with(run: ResearchRun, subrun: Any) -> ResearchRun:
    return ResearchRun.model_validate({**dict(run), "experiment_review": subrun})


def _bounds(config: RunnableConfig):
    return _settings(config).experiment


def bind_experiment_inputs(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Open the Phase 3B run on the active research run, or decline to."""
    node = NodeId.EXPERIMENT_BIND_INPUTS
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(state, node, started_at, f"Experiment review skipped: {reason}.",
                     status=NodeStatus.SKIPPED, warnings=[reason])
    if run.experiment_review is not None:
        return _done(state, node, started_at, "Phase 3B run already exists; resumed.", status=NodeStatus.SKIPPED)
    provider = _provider(config)
    llm = _llm(config) or LLMSettings()
    opened = xp.open_run(
        run, state.project, state.submission, started_at,
        provider_name=getattr(provider, "name", None) if provider is not None else None,
        model_name=llm.extraction_model if provider is not None else None, bounds=_bounds(config))
    return _done(
        state, node, started_at,
        f"Phase 3B run opened ({opened.status.value}); {len(opened.bound_claims)} claims and "
        f"{len(opened.bound_validation_targets)} Phase 2J validation requirements bound by id and hash.",
        run=_with(run, opened))


def _stage(node: NodeId, apply: Any, summary: Any):
    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        run = state.active_research_run
        subrun = run.experiment_review if run is not None else None
        if run is None or subrun is None or subrun.is_terminal:
            return _done(state, node, started_at, "No open Phase 3B run; nothing to do.", status=NodeStatus.SKIPPED)
        successor: ExperimentReviewRun = apply(subrun, run, state, config)
        return _done(state, node, started_at, summary(successor), run=_with(run, successor))

    _node.__name__ = node.value.casefold()
    return _node


segment_experiments = _stage(
    NodeId.EXPERIMENT_SEGMENT,
    lambda s, r, st, c: xp.segment_stage(s, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.experiments)} experiment protocol(s) segmented, {len(s.quarantine)} result span(s) "
              "quarantined (offsets and hash only).",
)
extract_experiment_protocol = _stage(
    NodeId.EXPERIMENT_EXTRACT_PROTOCOL,
    lambda s, r, st, c: xp.extract_stage(s, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.excerpts)} exact protocol excerpts bound ({s.model_calls_performed} model calls so far).",
)
resolve_experiment_applicability = _stage(
    NodeId.EXPERIMENT_RESOLVE_APPLICABILITY,
    lambda s, r, st, c: xp.applicability_stage(s, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: "Conditional protocol requirements resolved only through their closed triggers "
              "(an unresolved one stays CONDITIONAL; REQUIRED is never lowered).",
)
link_experiment_targets = _stage(
    NodeId.EXPERIMENT_LINK_TARGETS,
    lambda s, r, st, c: xp.link_stage(s, r, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.links)} target links, {len(s.measurements)} measurement bindings, {len(s.baselines)} "
              "baseline records (model-assisted; structure verified, semantics not).",
)
synthesize_experiment_review = _stage(
    NodeId.EXPERIMENT_SYNTHESIZE,
    lambda s, r, st, c: xp.synthesis_stage(s),
    lambda s: f"{len(s.phase2j_coverage)} Phase 2J coverage record(s) and {len(s.track_postures)} track posture(s) "
              "derived in Python (no result value read).",
)


def finalize_experiment_review(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.EXPERIMENT_FINALIZE
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.experiment_review is None or run.experiment_review.is_terminal:
        return _done(state, node, started_at, "No open Phase 3B run; nothing to do.", status=NodeStatus.SKIPPED)
    successor = xp.finalize_stage(run.experiment_review, run, state.project, state.submission, started_at)
    return _done(
        state, node, started_at,
        f"Phase 3B finished ({successor.status.value}). A protocol-level posture over the documented experiments "
        "-- not an execution, result, novelty or legal judgment, and not a score.",
        run=_with(run, successor))


__all__ = [
    "EXPERIMENT_MODEL_PROVIDER_KEY",
    "bind_experiment_inputs",
    "extract_experiment_protocol",
    "finalize_experiment_review",
    "link_experiment_targets",
    "resolve_experiment_applicability",
    "segment_experiments",
    "synthesize_experiment_review",
]
