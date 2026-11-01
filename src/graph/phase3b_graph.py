"""Phase 3B experiment review graph.

A dedicated graph in the Phase 2B-3A shape. It consumes an open research run
carrying FINISHED Phase 2J and Phase 3A runs, the verbatim student submission and
the claims, and leaves the research run non-terminal. It has no human interrupt.

Execution path (the seven approved stages, ADR-023)::

    START
      -> EXPERIMENT_BIND_INPUTS            bind + fingerprint inputs   --(no open run)--> END
      -> EXPERIMENT_SEGMENT                protocol spans + result quarantine (1 model call)
      -> EXPERIMENT_EXTRACT_PROTOCOL       type + requirement excerpts (1 call per experiment)
      -> EXPERIMENT_RESOLVE_APPLICABILITY  catalog first; conditional triggers only (<= 1 per experiment)
      -> EXPERIMENT_LINK_TARGETS           targets, measurement, baseline, conditions (1 per experiment)
      -> EXPERIMENT_SYNTHESIZE             issues, coverage, track postures in Python
      -> EXPERIMENT_FINALIZE               upstream fingerprints re-checked, project posture
      -> END

``EXPERIMENT_REVIEW`` (the node that would write ``ProjectState.experiments``),
``METHODOLOGY``, ``SCORING``, ``TRUST_GATE``, ``RED_TEAM`` and every discovery,
Phase 2J and Phase 3A node are in ``FORBIDDEN_NODES``: Phase 3B performs no search,
verifies no execution, evaluates no result and draws no legal conclusion.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph import experiment_nodes as n
from src.graph.persistence import build_checkpointer
from src.graph.phase3a_graph import FORBIDDEN_NODES as _PHASE_3A_FORBIDDEN
from src.graph.phase3a_graph import PHASE_3A_NODE_SEQUENCE
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_3B_GRAPH_NAME = "phase3b_experiment_review"

PHASE_3B_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.EXPERIMENT_BIND_INPUTS,
    NodeId.EXPERIMENT_SEGMENT,
    NodeId.EXPERIMENT_EXTRACT_PROTOCOL,
    NodeId.EXPERIMENT_RESOLVE_APPLICABILITY,
    NodeId.EXPERIMENT_LINK_TARGETS,
    NodeId.EXPERIMENT_SYNTHESIZE,
    NodeId.EXPERIMENT_FINALIZE,
)

FORBIDDEN_NODES: frozenset[NodeId] = _PHASE_3A_FORBIDDEN | frozenset(PHASE_3A_NODE_SEQUENCE)
"""Stages Phase 3B must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.EXPERIMENT_BIND_INPUTS: n.bind_experiment_inputs,
    NodeId.EXPERIMENT_SEGMENT: n.segment_experiments,
    NodeId.EXPERIMENT_EXTRACT_PROTOCOL: n.extract_experiment_protocol,
    NodeId.EXPERIMENT_RESOLVE_APPLICABILITY: n.resolve_experiment_applicability,
    NodeId.EXPERIMENT_LINK_TARGETS: n.link_experiment_targets,
    NodeId.EXPERIMENT_SYNTHESIZE: n.synthesize_experiment_review,
    NodeId.EXPERIMENT_FINALIZE: n.finalize_experiment_review,
}


def _after_bind(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if run is None or run.experiment_review is None or run.experiment_review.is_terminal:
        return END
    return NodeId.EXPERIMENT_SEGMENT.value


def build_phase3b_experiment_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the Phase 3B graph. The model provider arrives per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_3B_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])
    builder.add_edge(START, NodeId.EXPERIMENT_BIND_INPUTS.value)
    builder.add_conditional_edges(
        NodeId.EXPERIMENT_BIND_INPUTS.value, _after_bind,
        {NodeId.EXPERIMENT_SEGMENT.value: NodeId.EXPERIMENT_SEGMENT.value, END: END})
    for source, target in zip(PHASE_3B_NODE_SEQUENCE[1:], PHASE_3B_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.EXPERIMENT_FINALIZE.value, END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(), name=PHASE_3B_GRAPH_NAME)


__all__ = ["FORBIDDEN_NODES", "PHASE_3B_GRAPH_NAME", "PHASE_3B_NODE_SEQUENCE", "build_phase3b_experiment_graph"]
