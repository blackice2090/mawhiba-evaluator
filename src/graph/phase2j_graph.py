"""Phase 2J research / engineering gap assessment graph.

A dedicated graph in the Phase 2B-2I shape. It consumes an open research run
carrying a FINISHED Phase 2I run (and the Phase 2C-2H artifacts it rests on) and
leaves the research run non-terminal.

Execution path::

    START
      -> LOAD_GAP_ASSESSMENT_RUN       bind + fingerprint upstream  --(no open run)--> END
      -> BUILD_GAP_EVIDENCE_INVENTORY  existing texts only, no search
      -> EXTRACT_GAP_CANDIDATES        untrusted model -> exact anchors, in one boundary
      -> VERIFY_GAP_PROJECT_LINKAGE    model-assisted relation; structure verified
      -> REVIEW_GAP_COUNTEREVIDENCE    bounded; coverage recorded
      -> SYNTHESIZE_CLAIM_GAPS         kind, scope, posture decided in Python
      -> SYNTHESIZE_PROJECT_GAPS       descriptive counts, no score
      -> FINALIZE_GAP_ASSESSMENT       upstream fingerprints and claim hashes re-checked
      -> END

``GAP`` (the node that would write ``ProjectState.gap``), ``NOVELTY``,
``CLOSEST_PRIOR_ART``, ``METHODOLOGY``, ``EXPERIMENT_REVIEW``, ``SCORING``,
``TRUST_GATE``, ``RED_TEAM`` and every Phase 2G / 2H discovery node are in
``FORBIDDEN_NODES``: Phase 2J performs no new search, judges no methodology and
draws no legal conclusion.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph import gap_nodes as n
from src.graph.persistence import build_checkpointer
from src.graph.phase2i_graph import FORBIDDEN_NODES as _PHASE_2I_FORBIDDEN
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2J_GRAPH_NAME = "phase2j_research_engineering_gap"

PHASE_2J_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_GAP_ASSESSMENT_RUN,
    NodeId.BUILD_GAP_EVIDENCE_INVENTORY,
    NodeId.EXTRACT_GAP_CANDIDATES,
    NodeId.VERIFY_GAP_PROJECT_LINKAGE,
    NodeId.REVIEW_GAP_COUNTEREVIDENCE,
    NodeId.SYNTHESIZE_CLAIM_GAPS,
    NodeId.SYNTHESIZE_PROJECT_GAPS,
    NodeId.FINALIZE_GAP_ASSESSMENT,
)

FORBIDDEN_NODES: frozenset[NodeId] = (
    _PHASE_2I_FORBIDDEN
    | frozenset(
        {
            NodeId.NOVELTY,
            NodeId.GAP,
            NodeId.METHODOLOGY,
            NodeId.EXPERIMENT_REVIEW,
            NodeId.LOAD_NOVELTY_DIFFERENTIATION_RUN,
            NodeId.BUILD_COMPARISON_FEATURE_INVENTORY,
            NodeId.PROFILE_PRIOR_ART_CANDIDATES,
            NodeId.COMPARE_CLAIM_CANDIDATES,
            NodeId.SYNTHESIZE_CLAIM_DIFFERENTIATION,
            NodeId.SYNTHESIZE_PROJECT_DIFFERENTIATION,
            NodeId.FINALIZE_NOVELTY_DIFFERENTIATION,
        }
    )
)
"""Stages Phase 2J must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_GAP_ASSESSMENT_RUN: n.load_gap_assessment_run,
    NodeId.BUILD_GAP_EVIDENCE_INVENTORY: n.build_gap_evidence_inventory,
    NodeId.EXTRACT_GAP_CANDIDATES: n.extract_gap_candidates,
    NodeId.VERIFY_GAP_PROJECT_LINKAGE: n.verify_gap_project_linkage,
    NodeId.REVIEW_GAP_COUNTEREVIDENCE: n.review_gap_counterevidence,
    NodeId.SYNTHESIZE_CLAIM_GAPS: n.synthesize_claim_gaps,
    NodeId.SYNTHESIZE_PROJECT_GAPS: n.synthesize_project_gaps,
    NodeId.FINALIZE_GAP_ASSESSMENT: n.finalize_gap_assessment,
}


def _after_load(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if run is None or run.research_engineering_gap is None or run.research_engineering_gap.is_terminal:
        return END
    return NodeId.BUILD_GAP_EVIDENCE_INVENTORY.value


def build_phase2j_gap_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the Phase 2J graph. The model provider arrives per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2J_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])
    builder.add_edge(START, NodeId.LOAD_GAP_ASSESSMENT_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_GAP_ASSESSMENT_RUN.value,
        _after_load,
        {NodeId.BUILD_GAP_EVIDENCE_INVENTORY.value: NodeId.BUILD_GAP_EVIDENCE_INVENTORY.value, END: END},
    )
    for source, target in zip(PHASE_2J_NODE_SEQUENCE[1:], PHASE_2J_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_GAP_ASSESSMENT.value, END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2J_GRAPH_NAME,
    )


__all__ = ["FORBIDDEN_NODES", "PHASE_2J_GRAPH_NAME", "PHASE_2J_NODE_SEQUENCE", "build_phase2j_gap_graph"]
