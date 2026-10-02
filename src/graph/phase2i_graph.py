"""Phase 2I novelty and differentiation assessment graph.

A dedicated graph in the Phase 2B-2H shape. It consumes an open research run
carrying FINISHED Phase 2G / 2H subruns and leaves the research run
non-terminal.

Execution path::

    START
      -> LOAD_NOVELTY_DIFFERENTIATION_RUN --(no open run)---------------> END
      -> BUILD_COMPARISON_FEATURE_INVENTORY  exact claim anchors; combination feature
      -> PROFILE_PRIOR_ART_CANDIDATES        eligibility, capacity, independence, chronology
      -> COMPARE_CLAIM_CANDIDATES            untrusted model -> deterministic anchors
      -> SYNTHESIZE_CLAIM_DIFFERENTIATION    posture decided in Python
      -> SYNTHESIZE_PROJECT_DIFFERENTIATION  descriptive counts, no score
      -> FINALIZE_NOVELTY_DIFFERENTIATION
      -> END

``NOVELTY`` (a verdict node), ``CLOSEST_PRIOR_ART``, ``SCORING``, ``TRUST_GATE``,
``RED_TEAM`` and every Phase 2G / 2H discovery node are in ``FORBIDDEN_NODES``:
Phase 2I performs no new search and draws no legal conclusion.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph import novelty_nodes as n
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2I_GRAPH_NAME = "phase2i_novelty_differentiation"

PHASE_2I_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN,
    NodeId.BUILD_COMPARISON_FEATURE_INVENTORY,
    NodeId.PROFILE_PRIOR_ART_CANDIDATES,
    NodeId.COMPARE_CLAIM_CANDIDATES,
    NodeId.SYNTHESIZE_CLAIM_DIFFERENTIATION,
    NodeId.SYNTHESIZE_PROJECT_DIFFERENTIATION,
    NodeId.FINALIZE_NOVELTY_DIFFERENTIATION,
)

FORBIDDEN_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.NOVELTY,
        NodeId.CLOSEST_PRIOR_ART,
        NodeId.GAP,
        NodeId.METHODOLOGY,
        NodeId.SCORING,
        NodeId.TRUST_GATE,
        NodeId.FINAL_VERIFIER,
        NodeId.RED_TEAM,
        NodeId.REPORT_GENERATOR,
        NodeId.CLAIM_EVIDENCE,
        NodeId.LOAD_PATENT_RESEARCH_RUN,
        NodeId.PLAN_PATENT_QUERIES,
        NodeId.EXECUTE_PATENT_SEARCH,
        NodeId.VERIFY_PATENT_PUBLICATIONS,
        NodeId.RESOLVE_PATENT_FAMILIES,
        NodeId.CAPTURE_PATENT_TEXT,
        NodeId.BUILD_PATENT_CANDIDATES,
        NodeId.FINALIZE_PATENT_RESEARCH,
        NodeId.LOAD_PRODUCT_OSS_RESEARCH_RUN,
        NodeId.PLAN_PRODUCT_OSS_QUERIES,
        NodeId.EXECUTE_PRODUCT_SEARCH,
        NodeId.FETCH_PRODUCT_ARTIFACTS,
        NodeId.RESOLVE_PRODUCT_IDENTITY,
        NodeId.BUILD_PRODUCT_CANDIDATES,
        NodeId.EXECUTE_OPEN_SOURCE_SEARCH,
        NodeId.VERIFY_REPOSITORIES,
        NodeId.CAPTURE_REPOSITORY_SNAPSHOTS,
        NodeId.RESOLVE_REPOSITORY_NETWORKS,
        NodeId.BUILD_OPEN_SOURCE_CANDIDATES,
        NodeId.FINALIZE_PRODUCT_OSS_RESEARCH,
    }
)
"""Stages Phase 2I must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN: n.load_novelty_differentiation_run,
    NodeId.BUILD_COMPARISON_FEATURE_INVENTORY: n.build_comparison_feature_inventory,
    NodeId.PROFILE_PRIOR_ART_CANDIDATES: n.profile_prior_art_candidates,
    NodeId.COMPARE_CLAIM_CANDIDATES: n.compare_claim_candidates,
    NodeId.SYNTHESIZE_CLAIM_DIFFERENTIATION: n.synthesize_claim_differentiation,
    NodeId.SYNTHESIZE_PROJECT_DIFFERENTIATION: n.synthesize_project_differentiation,
    NodeId.FINALIZE_NOVELTY_DIFFERENTIATION: n.finalize_novelty_differentiation,
}


def _after_load(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if run is None or run.novelty_differentiation is None or run.novelty_differentiation.is_terminal:
        return END
    return NodeId.BUILD_COMPARISON_FEATURE_INVENTORY.value


def build_phase2i_novelty_differentiation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2I graph. The model provider arrives per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2I_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])
    builder.add_edge(START, NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN.value,
        _after_load,
        {NodeId.BUILD_COMPARISON_FEATURE_INVENTORY.value: NodeId.BUILD_COMPARISON_FEATURE_INVENTORY.value, END: END},
    )
    for source, target in zip(PHASE_2I_NODE_SEQUENCE[1:], PHASE_2I_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_NOVELTY_DIFFERENTIATION.value, END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2I_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2I_GRAPH_NAME",
    "PHASE_2I_NODE_SEQUENCE",
    "build_phase2i_novelty_differentiation_graph",
]
