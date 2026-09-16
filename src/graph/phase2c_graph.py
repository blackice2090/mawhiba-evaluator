"""Phase 2C evidence extraction graph.

A dedicated branch graph. It consumes a research run that already carries Phase
2B verified academic sources, and it stops at verified evidence.

Execution path::

    START
      -> LOAD_RESEARCH_RUN ----------(no open run / no academic result)---> END
      -> VALIDATE_EVIDENCE_INPUT        is there anything to extract from?
      -> BUILD_CONTENT_SNAPSHOTS        verified source -> provider-attributed text
      -> SELECT_EXTRACTABLE_CONTENT     budget; metadata-only sources drop out
      -> CHUNK_CONTENT_IF_NEEDED        deterministic, offsets keep the parent
      -> EXTRACT_EVIDENCE_CANDIDATES    the model proposes. UNTRUSTED
      -> VERIFY_EVIDENCE_PROVENANCE     exact spans derived by code (ADR-011)
      -> VERIFY_NUMERIC_FIDELITY        numbers re-checked against the excerpt
      -> DEDUPLICATE_EVIDENCE           identical spans merge, provenance kept
      -> UPDATE_EVIDENCE_COVERAGE       operational counters
      -> FINALIZE_EVIDENCE_EXTRACTION   terminal status; the research run stays open
      -> END

There is deliberately no claim-alignment node, and there never will be one in
this graph: deciding that an excerpt supports or contradicts a student claim is
the next reviewed phase (ADR-012). ``CLAIM_EVIDENCE`` is listed in
``FORBIDDEN_NODES`` so a test can assert its absence rather than trusting review.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.evidence_nodes import (
    build_content_snapshots,
    chunk_content_if_needed,
    deduplicate_evidence_node,
    extract_evidence_candidates,
    finalize_evidence_extraction,
    load_research_run,
    select_extractable_content,
    update_evidence_coverage,
    validate_evidence_input,
    verify_evidence_provenance,
    verify_numeric_fidelity,
)
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2C_GRAPH_NAME = "phase2c_evidence_extraction"

PHASE_2C_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_RESEARCH_RUN,
    NodeId.VALIDATE_EVIDENCE_INPUT,
    NodeId.BUILD_CONTENT_SNAPSHOTS,
    NodeId.SELECT_EXTRACTABLE_CONTENT,
    NodeId.CHUNK_CONTENT_IF_NEEDED,
    NodeId.EXTRACT_EVIDENCE_CANDIDATES,
    NodeId.VERIFY_EVIDENCE_PROVENANCE,
    NodeId.VERIFY_NUMERIC_FIDELITY,
    NodeId.DEDUPLICATE_EVIDENCE,
    NodeId.UPDATE_EVIDENCE_COVERAGE,
    NodeId.FINALIZE_EVIDENCE_EXTRACTION,
)

FORBIDDEN_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.CLAIM_EVIDENCE,
        NodeId.NOVELTY,
        NodeId.GAP,
        NodeId.SCORING,
        NodeId.TRUST_GATE,
        NodeId.FINAL_VERIFIER,
        NodeId.CLOSEST_PRIOR_ART,
    }
)
"""Stages Phase 2C must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_RESEARCH_RUN: load_research_run,
    NodeId.VALIDATE_EVIDENCE_INPUT: validate_evidence_input,
    NodeId.BUILD_CONTENT_SNAPSHOTS: build_content_snapshots,
    NodeId.SELECT_EXTRACTABLE_CONTENT: select_extractable_content,
    NodeId.CHUNK_CONTENT_IF_NEEDED: chunk_content_if_needed,
    NodeId.EXTRACT_EVIDENCE_CANDIDATES: extract_evidence_candidates,
    NodeId.VERIFY_EVIDENCE_PROVENANCE: verify_evidence_provenance,
    NodeId.VERIFY_NUMERIC_FIDELITY: verify_numeric_fidelity,
    NodeId.DEDUPLICATE_EVIDENCE: deduplicate_evidence_node,
    NodeId.UPDATE_EVIDENCE_COVERAGE: update_evidence_coverage,
    NodeId.FINALIZE_EVIDENCE_EXTRACTION: finalize_evidence_extraction,
}


def _after_load(state: EvaluationGraphState) -> str:
    """Continue only when an extraction run actually opened."""
    run = state.active_research_run
    if run is None or run.is_terminal or run.evidence_extraction is None:
        return END
    return NodeId.VALIDATE_EVIDENCE_INPUT.value


def build_phase2c_evidence_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2C graph. The model provider is injected per run."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2C_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_RESEARCH_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_RESEARCH_RUN.value,
        _after_load,
        {
            NodeId.VALIDATE_EVIDENCE_INPUT.value: NodeId.VALIDATE_EVIDENCE_INPUT.value,
            END: END,
        },
    )
    for source, target in zip(PHASE_2C_NODE_SEQUENCE[1:], PHASE_2C_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_EVIDENCE_EXTRACTION.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2C_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2C_GRAPH_NAME",
    "PHASE_2C_NODE_SEQUENCE",
    "build_phase2c_evidence_graph",
]
