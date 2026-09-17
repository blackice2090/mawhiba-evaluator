"""Phase 2D claim-evidence alignment graph.

A dedicated branch graph, following the Phase 2C shape exactly. It consumes a
research run that already carries terminal Phase 2C evidence extraction, and
it stops at verified claim/evidence relations.

Execution path::

    START
      -> LOAD_ALIGNMENT_RUN --------(no open run)---------------> END
      -> VALIDATE_ALIGNMENT_INPUT       claims and accepted evidence present?
      -> GENERATE_ALIGNMENT_PAIRS       deterministic; blocked if over the limit
      -> CLASSIFY_ALIGNMENT_CANDIDATES  the model proposes. UNTRUSTED
      -> VERIFY_ALIGNMENT_CANDIDATES    exact anchors, taxonomy consistency
      -> UPDATE_ALIGNMENT_COVERAGE      operational counters
      -> FINALIZE_CLAIM_EVIDENCE_ALIGNMENT  terminal status; the run stays open
      -> END

There is no node here that changes a claim's status, confidence, evidence_ids
or counter_evidence_ids, and there never will be one in this graph: deciding
whether a claim is sufficiently proven is a later reviewed phase (ADR-014).
``TRUST_GATE``, ``SCORING`` and the other later-phase nodes are listed in
``FORBIDDEN_NODES`` so a test can assert their absence rather than trusting
review.

Every node guards on ``alignment.is_terminal``, so once ``LOAD_ALIGNMENT_RUN``
or ``GENERATE_ALIGNMENT_PAIRS`` marks the run terminal (no ready evidence
extraction, no claims, no evidence, or the pair-count safety limit), every
downstream node is a no-op rather than a special routing case.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.alignment_nodes import (
    classify_alignment_candidates,
    finalize_claim_evidence_alignment,
    generate_alignment_pairs,
    load_alignment_run,
    update_alignment_coverage,
    validate_alignment_input,
    verify_alignment_candidates,
)
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2D_GRAPH_NAME = "phase2d_claim_evidence_alignment"

PHASE_2D_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_ALIGNMENT_RUN,
    NodeId.VALIDATE_ALIGNMENT_INPUT,
    NodeId.GENERATE_ALIGNMENT_PAIRS,
    NodeId.CLASSIFY_ALIGNMENT_CANDIDATES,
    NodeId.VERIFY_ALIGNMENT_CANDIDATES,
    NodeId.UPDATE_ALIGNMENT_COVERAGE,
    NodeId.FINALIZE_CLAIM_EVIDENCE_ALIGNMENT,
)

FORBIDDEN_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.NOVELTY,
        NodeId.GAP,
        NodeId.SCORING,
        NodeId.TRUST_GATE,
        NodeId.FINAL_VERIFIER,
        NodeId.CLOSEST_PRIOR_ART,
        NodeId.RED_TEAM,
        NodeId.REPORT_GENERATOR,
        NodeId.CONTRADICTION_DETECTION,
    }
)
"""Stages Phase 2D must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_ALIGNMENT_RUN: load_alignment_run,
    NodeId.VALIDATE_ALIGNMENT_INPUT: validate_alignment_input,
    NodeId.GENERATE_ALIGNMENT_PAIRS: generate_alignment_pairs,
    NodeId.CLASSIFY_ALIGNMENT_CANDIDATES: classify_alignment_candidates,
    NodeId.VERIFY_ALIGNMENT_CANDIDATES: verify_alignment_candidates,
    NodeId.UPDATE_ALIGNMENT_COVERAGE: update_alignment_coverage,
    NodeId.FINALIZE_CLAIM_EVIDENCE_ALIGNMENT: finalize_claim_evidence_alignment,
}


def _after_load(state: EvaluationGraphState) -> str:
    """Continue only when there is an active research run to work from."""
    run = state.active_research_run
    if run is None:
        return END
    return NodeId.VALIDATE_ALIGNMENT_INPUT.value


def build_phase2d_claim_alignment_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2D graph. The model provider is injected per run."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2D_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_ALIGNMENT_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_ALIGNMENT_RUN.value,
        _after_load,
        {
            NodeId.VALIDATE_ALIGNMENT_INPUT.value: NodeId.VALIDATE_ALIGNMENT_INPUT.value,
            END: END,
        },
    )
    for source, target in zip(PHASE_2D_NODE_SEQUENCE[1:], PHASE_2D_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_CLAIM_EVIDENCE_ALIGNMENT.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2D_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2D_GRAPH_NAME",
    "PHASE_2D_NODE_SEQUENCE",
    "build_phase2d_claim_alignment_graph",
]
