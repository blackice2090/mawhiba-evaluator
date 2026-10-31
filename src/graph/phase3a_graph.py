"""Phase 3A methodology review graph.

A dedicated graph in the Phase 2B-2J shape. It consumes an open research run
carrying a FINISHED Phase 2J run, the verbatim student submission and the claims,
and leaves the research run non-terminal. It has no human interrupt.

Execution path::

    START
      -> LOAD_METHODOLOGY_REVIEW_RUN            bind + fingerprint inputs  --(no open run)--> END
      -> BUILD_METHODOLOGY_REQUIREMENT_INVENTORY  closed catalog, deterministic
      -> RESOLVE_METHODOLOGY_OVERLAYS           AI/ML + software materiality and ownership
      -> EXTRACT_METHODOLOGY_EVIDENCE           untrusted model -> exact submission excerpts
      -> RESOLVE_METHODOLOGY_APPLICABILITY      CONDITIONAL requirements, closed triggers only
      -> ASSESS_METHODOLOGY_COMPONENTS          documentation status, separate from adequacy
      -> LINK_METHODOLOGY_TO_TARGETS            metric, baseline, coverage, conditions
      -> EVALUATE_VALIDATION_CONTINUITY         exact Phase 2J requirement, nothing invented
      -> SYNTHESIZE_METHODOLOGY_POSTURE         issues and postures decided in Python
      -> FINALIZE_METHODOLOGY_REVIEW            upstream fingerprints re-checked
      -> END

``METHODOLOGY`` (the node that would write ``ProjectState.methodology``),
``EXPERIMENT_REVIEW`` (Phase 3B), ``NOVELTY``, ``GAP``, ``SCORING``, ``TRUST_GATE``,
``RED_TEAM`` and every Phase 2G / 2H discovery node are in ``FORBIDDEN_NODES``:
Phase 3A performs no search, judges no execution or result, and draws no legal
conclusion.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph import methodology_nodes as n
from src.graph.persistence import build_checkpointer
from src.graph.phase2j_graph import FORBIDDEN_NODES as _PHASE_2J_FORBIDDEN
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_3A_GRAPH_NAME = "phase3a_methodology_review"

PHASE_3A_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_METHODOLOGY_REVIEW_RUN,
    NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY,
    NodeId.RESOLVE_METHODOLOGY_OVERLAYS,
    NodeId.EXTRACT_METHODOLOGY_EVIDENCE,
    NodeId.RESOLVE_METHODOLOGY_APPLICABILITY,
    NodeId.ASSESS_METHODOLOGY_COMPONENTS,
    NodeId.LINK_METHODOLOGY_TO_TARGETS,
    NodeId.EVALUATE_VALIDATION_CONTINUITY,
    NodeId.SYNTHESIZE_METHODOLOGY_POSTURE,
    NodeId.FINALIZE_METHODOLOGY_REVIEW,
)

FORBIDDEN_NODES: frozenset[NodeId] = (
    _PHASE_2J_FORBIDDEN
    | frozenset(
        {
            NodeId.METHODOLOGY,
            NodeId.EXPERIMENT_REVIEW,
            NodeId.CLAIM_EVIDENCE,
            NodeId.CONTRADICTION_DETECTION,
            NodeId.LOAD_GAP_ASSESSMENT_RUN,
            NodeId.BUILD_GAP_EVIDENCE_INVENTORY,
            NodeId.EXTRACT_GAP_CANDIDATES,
            NodeId.VERIFY_GAP_PROJECT_LINKAGE,
            NodeId.REVIEW_GAP_COUNTEREVIDENCE,
            NodeId.SYNTHESIZE_CLAIM_GAPS,
            NodeId.SYNTHESIZE_PROJECT_GAPS,
            NodeId.FINALIZE_GAP_ASSESSMENT,
        }
    )
)
"""Stages Phase 3A must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_METHODOLOGY_REVIEW_RUN: n.load_methodology_review_run,
    NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY: n.build_methodology_requirement_inventory,
    NodeId.RESOLVE_METHODOLOGY_OVERLAYS: n.resolve_methodology_overlays,
    NodeId.EXTRACT_METHODOLOGY_EVIDENCE: n.extract_methodology_evidence,
    NodeId.RESOLVE_METHODOLOGY_APPLICABILITY: n.resolve_methodology_applicability,
    NodeId.ASSESS_METHODOLOGY_COMPONENTS: n.assess_methodology_components,
    NodeId.LINK_METHODOLOGY_TO_TARGETS: n.link_methodology_to_targets,
    NodeId.EVALUATE_VALIDATION_CONTINUITY: n.evaluate_validation_continuity,
    NodeId.SYNTHESIZE_METHODOLOGY_POSTURE: n.synthesize_methodology_posture,
    NodeId.FINALIZE_METHODOLOGY_REVIEW: n.finalize_methodology_review,
}


def _after_load(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if run is None or run.methodology_review is None or run.methodology_review.is_terminal:
        return END
    return NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY.value


def build_phase3a_methodology_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the Phase 3A graph. The model provider arrives per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_3A_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])
    builder.add_edge(START, NodeId.LOAD_METHODOLOGY_REVIEW_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_METHODOLOGY_REVIEW_RUN.value,
        _after_load,
        {NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY.value: NodeId.BUILD_METHODOLOGY_REQUIREMENT_INVENTORY.value,
         END: END},
    )
    for source, target in zip(PHASE_3A_NODE_SEQUENCE[1:], PHASE_3A_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_METHODOLOGY_REVIEW.value, END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_3A_GRAPH_NAME,
    )


__all__ = ["FORBIDDEN_NODES", "PHASE_3A_GRAPH_NAME", "PHASE_3A_NODE_SEQUENCE", "build_phase3a_methodology_graph"]
