"""Phase 2J research / engineering gap assessment nodes.

Each node is a thin wrapper over one stage in ``src.research.gap.pipeline``: it
reads the Phase 2J run on the active ``ResearchRun``, applies one stage, and
emits a successor research run with only ``research_engineering_gap`` replaced.
Nothing is held between nodes, so a node replayed after an interrupt starts from
the persisted run and reaches the same result (ADR-002); a stage that already
ran is a no-op, and a replay makes no model call.

Anchor verification and deterministic classification run INSIDE the nodes that
receive untrusted model output (``EXTRACT_GAP_CANDIDATES``,
``VERIFY_GAP_PROJECT_LINKAGE``, ``REVIEW_GAP_COUNTEREVIDENCE``): unverified model
output never reaches a checkpoint (ADR-021).

No node writes the ``project`` channel. Claims, ``ProjectState.gap``,
``ProjectState.scores``, ``trust_gate`` and ``evaluation_status`` are untouched
by construction, and so are the Phase 2C-2I artifacts on the same research run.

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``structured_model_provider`` -- absent = no claim can be assessed and every
  claim posture is INSUFFICIENT_INPUT (never "no gap");
* ``llm_settings`` -- optional model selection;
* ``research_settings`` -- ``ResearchSettings.gap`` bounds.

Phase 2J has no search provider key. ``config["configurable"]`` is never read for
one, and the graph contains no discovery node (``FORBIDDEN_NODES``).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.novelty_nodes import _done, _llm, _provider, _settings
from src.graph.contracts import NodeStatus
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState
from src.research.gap import pipeline as gp
from src.schemas.gap_assessment import GapAssessmentRun
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

GAP_MODEL_PROVIDER_KEY = "structured_model_provider"


def _with(run: ResearchRun, subrun: Any) -> ResearchRun:
    return ResearchRun.model_validate({**dict(run), "research_engineering_gap": subrun})


def load_gap_assessment_run(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Open the Phase 2J run on the active research run, or decline to."""
    node = NodeId.LOAD_GAP_ASSESSMENT_RUN
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(state, node, started_at, f"Gap assessment skipped: {reason}.",
                     status=NodeStatus.SKIPPED, warnings=[reason])
    if run.research_engineering_gap is not None:
        return _done(state, node, started_at, "Phase 2J run already exists; resumed.", status=NodeStatus.SKIPPED)
    provider = _provider(config)
    llm = _llm(config) or LLMSettings()
    opened = gp.open_gap_run(
        run, list(state.project.claims), state.project.identity.project_type, _settings(config).gap, started_at,
        provider_name=getattr(provider, "name", None) if provider is not None else None,
        model_name=llm.extraction_model if provider is not None else None,
    )
    return _done(
        state, node, started_at,
        f"Phase 2J run opened ({opened.status.value}); {len(opened.drafts)} claims bound by hash, "
        f"{len(opened.upstream_bindings)} upstream subruns fingerprinted.",
        run=_with(run, opened),
    )


def _stage(node: NodeId, apply: Any, summary: Any):
    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        run = state.active_research_run
        subrun = run.research_engineering_gap if run is not None else None
        if run is None or subrun is None or subrun.is_terminal:
            return _done(state, node, started_at, "No open Phase 2J run; nothing to do.", status=NodeStatus.SKIPPED)
        successor: GapAssessmentRun = apply(subrun, run, state, config)
        return _done(state, node, started_at, summary(successor), run=_with(run, successor))

    _node.__name__ = node.value.casefold()
    return _node


build_gap_evidence_inventory = _stage(
    NodeId.BUILD_GAP_EVIDENCE_INVENTORY,
    lambda s, r, st, c: gp.inventory_stage(s, r),
    lambda s: f"{len(s.inventory_texts)} existing upstream texts inventoried (no new evidence, no search).",
)
extract_gap_candidates = _stage(
    NodeId.EXTRACT_GAP_CANDIDATES,
    lambda s, r, st, c: gp.extraction_stage(s, r, list(st.project.claims), _provider(c), _llm(c)),
    lambda s: f"{sum(len(d.limitations) for d in s.drafts)} limitations verified at exact anchors "
              f"({s.model_calls_performed} model calls so far).",
)
verify_gap_project_linkage = _stage(
    NodeId.VERIFY_GAP_PROJECT_LINKAGE,
    lambda s, r, st, c: gp.linkage_stage(s, r, list(st.project.claims), _provider(c), _llm(c)),
    lambda s: f"{sum(len(d.project_links) for d in s.drafts)} project-linkage judgments bound "
              "(model-assisted; structure verified, semantics not).",
)
review_gap_counterevidence = _stage(
    NodeId.REVIEW_GAP_COUNTEREVIDENCE,
    lambda s, r, st, c: gp.counterevidence_stage(s, r, list(st.project.claims), _provider(c), _llm(c)),
    lambda s: f"{sum(len(d.counterevidence) for d in s.drafts)} counterevidence items; "
              f"{sum(1 for c in s.counterevidence_coverage if c.complete)}/{len(s.counterevidence_coverage)} reviews complete.",
)
synthesize_claim_gaps = _stage(
    NodeId.SYNTHESIZE_CLAIM_GAPS,
    lambda s, r, st, c: gp.synthesis_stage(s, r),
    lambda s: f"{len(s.claim_assessments)} claim postures synthesized in Python.",
)
synthesize_project_gaps = _stage(
    NodeId.SYNTHESIZE_PROJECT_GAPS,
    lambda s, r, st, c: gp.project_stage(s),
    lambda s: "Descriptive project summary built (counts only; no score).",
)


def finalize_gap_assessment(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.FINALIZE_GAP_ASSESSMENT
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.research_engineering_gap is None or run.research_engineering_gap.is_terminal:
        return _done(state, node, started_at, "No open Phase 2J run; nothing to do.", status=NodeStatus.SKIPPED)
    successor = gp.finalize_stage(run.research_engineering_gap, run, list(state.project.claims), started_at)
    return _done(
        state, node, started_at,
        "Phase 2J finished. A bounded evidence posture relative to the verified inventory -- not a field-wide "
        "absence claim, not a methodology or result judgment, not novelty or patentability, not a score.",
        run=_with(run, successor),
    )


__all__ = [
    "GAP_MODEL_PROVIDER_KEY",
    "build_gap_evidence_inventory",
    "extract_gap_candidates",
    "finalize_gap_assessment",
    "load_gap_assessment_run",
    "review_gap_counterevidence",
    "synthesize_claim_gaps",
    "synthesize_project_gaps",
    "verify_gap_project_linkage",
]
