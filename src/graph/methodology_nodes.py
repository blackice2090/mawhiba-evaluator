"""Phase 3A methodology review nodes.

Each node is a thin wrapper over one stage in ``src.research.methodology.pipeline``:
it reads the Phase 3A run on the active ``ResearchRun``, applies one stage, and
emits a successor research run with only ``methodology_review`` replaced. Nothing
is held between nodes, so a node replayed after an interrupt starts from the
persisted run and reaches the same result (ADR-002); a stage that already ran is a
no-op, and a replay makes no model call. Transient model DTOs never leave a stage.

Verification runs INSIDE the node that receives untrusted model output: unverified
model output never reaches a checkpoint (ADR-022).

No node writes the ``project`` channel. Claims, ``ProjectState.methodology``,
``ProjectState.scores``, ``trust_gate`` and ``evaluation_status`` are untouched by
construction, and so are the Phase 2A-2J artifacts on the same research run.

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``structured_model_provider`` -- absent = nothing can be read and every
  requirement is INSUFFICIENT_SOURCE_COVERAGE (never "not done");
* ``llm_settings`` -- optional model selection;
* ``research_settings`` -- ``ResearchSettings.methodology`` bounds.

Phase 3A has no search provider key. ``config["configurable"]`` is never read for
one, and the graph contains no discovery node (``FORBIDDEN_NODES``).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.contracts import NodeStatus
from src.graph.novelty_nodes import _done, _llm, _provider, _settings
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState
from src.research.methodology import pipeline as mp
from src.schemas.methodology_review import MethodologyReviewRun
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

METHODOLOGY_MODEL_PROVIDER_KEY = "structured_model_provider"


def _with(run: ResearchRun, subrun: Any) -> ResearchRun:
    return ResearchRun.model_validate({**dict(run), "methodology_review": subrun})


def load_methodology_review_run(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Open the Phase 3A run on the active research run, or decline to."""
    node = NodeId.LOAD_METHODOLOGY_REVIEW_RUN
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(state, node, started_at, f"Methodology review skipped: {reason}.",
                     status=NodeStatus.SKIPPED, warnings=[reason])
    if run.methodology_review is not None:
        return _done(state, node, started_at, "Phase 3A run already exists; resumed.", status=NodeStatus.SKIPPED)
    provider = _provider(config)
    llm = _llm(config) or LLMSettings()
    opened = mp.open_run(
        run, state.project, state.submission, started_at,
        provider_name=getattr(provider, "name", None) if provider is not None else None,
        model_name=llm.extraction_model if provider is not None else None,
    )
    return _done(
        state, node, started_at,
        f"Phase 3A run opened ({opened.status.value}); {len(opened.bound_claims)} claims bound by hash, "
        f"{len(opened.upstream_bindings)} upstream inputs fingerprinted.",
        run=_with(run, opened),
    )


def _stage(node: NodeId, apply: Any, summary: Any):
    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        run = state.active_research_run
        subrun = run.methodology_review if run is not None else None
        if run is None or subrun is None or subrun.is_terminal:
            return _done(state, node, started_at, "No open Phase 3A run; nothing to do.", status=NodeStatus.SKIPPED)
        successor: MethodologyReviewRun = apply(subrun, run, state, config)
        return _done(state, node, started_at, summary(successor), run=_with(run, successor))

    _node.__name__ = node.value.casefold()
    return _node


def _bounds(config: RunnableConfig):
    return _settings(config).methodology


build_methodology_requirement_inventory = _stage(
    NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY,
    lambda s, r, st, c: mp.inventory_stage(s),
    lambda s: f"{len(s.draft.applicability) if s.draft else 0} catalog requirements resolved (closed catalog; "
              "no model, no search).",
)
resolve_methodology_overlays = _stage(
    NodeId.RESOLVE_METHODOLOGY_OVERLAYS,
    lambda s, r, st, c: mp.overlay_stage(s, r, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.overlays)} overlay assignment(s); {sum(1 for o in s.overlays if o.blocks_well_specified)} "
              "unresolved (model-assisted; materiality rests on exact excerpts).",
)
extract_methodology_evidence = _stage(
    NodeId.EXTRACT_METHODOLOGY_EVIDENCE,
    lambda s, r, st, c: mp.evidence_stage(s, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.excerpts)} exact submission excerpts bound ({s.model_calls_performed} model calls so far).",
)
resolve_methodology_applicability = _stage(
    NodeId.RESOLVE_METHODOLOGY_APPLICABILITY,
    lambda s, r, st, c: mp.applicability_stage(s, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: "Conditional requirements resolved only through their closed trigger sets "
              "(an unresolved one stays CONDITIONAL).",
)
assess_methodology_components = _stage(
    NodeId.ASSESS_METHODOLOGY_COMPONENTS,
    lambda s, r, st, c: mp.assess_stage(s),
    lambda s: f"{len(s.draft.documentation) if s.draft else 0} documentation records "
              "(documentation status is separate from design adequacy).",
)
link_methodology_to_targets = _stage(
    NodeId.LINK_METHODOLOGY_TO_TARGETS,
    lambda s, r, st, c: mp.link_stage(s, r, st.project, st.submission, _provider(c), _llm(c), _bounds(c)),
    lambda s: f"{len(s.draft.coverage) if s.draft else 0} coverage links, {len(s.metric_alignments)} metric plans, "
              f"{len(s.baselines)} baseline records (model-assisted; structure verified, semantics not).",
)
evaluate_validation_continuity = _stage(
    NodeId.EVALUATE_VALIDATION_CONTINUITY,
    lambda s, r, st, c: mp.continuity_stage(s),
    lambda s: "Strong coverage gated on the exact bound Phase 2J requirement (no dimension invented).",
)
synthesize_methodology_posture = _stage(
    NodeId.SYNTHESIZE_METHODOLOGY_POSTURE,
    lambda s, r, st, c: mp.synthesis_stage(s),
    lambda s: f"{len(s.track_assessments)} track posture(s) derived in Python from validated records.",
)


def finalize_methodology_review(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.FINALIZE_METHODOLOGY_REVIEW
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.methodology_review is None or run.methodology_review.is_terminal:
        return _done(state, node, started_at, "No open Phase 3A run; nothing to do.", status=NodeStatus.SKIPPED)
    successor = mp.finalize_stage(run.methodology_review, run, state.project, state.submission, started_at)
    return _done(
        state, node, started_at,
        "Phase 3A finished. A design-level posture over the documented methodology -- not an execution, result, "
        "novelty or legal judgment, and not a score.",
        run=_with(run, successor),
    )


__all__ = [
    "METHODOLOGY_MODEL_PROVIDER_KEY",
    "assess_methodology_components",
    "build_methodology_requirement_inventory",
    "evaluate_validation_continuity",
    "extract_methodology_evidence",
    "finalize_methodology_review",
    "link_methodology_to_targets",
    "load_methodology_review_run",
    "resolve_methodology_applicability",
    "resolve_methodology_overlays",
    "synthesize_methodology_posture",
]
