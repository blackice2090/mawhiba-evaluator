"""Phase 2G patent prior-art research graph.

A dedicated branch graph in the Phase 2B-2F shape. It consumes an open research
run and stops at patent prior-art *research candidates*, leaving the run
non-terminal so later branches can still write to it.

Execution path::

    START
      -> LOAD_PATENT_RESEARCH_RUN ----(no open run)-----------------> END
      -> PLAN_PATENT_QUERIES          canonical claim text -> validated CQL
      -> EXECUTE_PATENT_SEARCH        bounded, retried, never silently cut
      -> VERIFY_PATENT_PUBLICATIONS   search hit -> verified publication
      -> RESOLVE_PATENT_FAMILIES      provider families; members preserved
      -> CAPTURE_PATENT_TEXT          title / abstract / claims / description
      -> BUILD_PATENT_CANDIDATES      chronology against an explicit cutoff
      -> FINALIZE_PATENT_RESEARCH     coverage re-derived; patent run closed
      -> END

**Verification is its own node** so the trust boundary between a search hit and
a verified publication is visible in the graph, exactly as Phase 1B made the
intake boundary visible (ADR-003, ADR-018).

**No later phase.** ``NOVELTY``, ``CLOSEST_PRIOR_ART``, ``SCORING``,
``TRUST_GATE`` and the rest are listed in ``FORBIDDEN_NODES`` so a test asserts
their absence. A patent candidate is not a novelty verdict, not a patentability
opinion and not a legal prior-art ruling; the boundary is structural.

The patent provider is injected per run through
``config["configurable"]["patent_search_provider"]``, which keeps graph
construction credential-free and every standard test offline.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.patent_nodes import (
    build_patent_candidates,
    capture_patent_text,
    execute_patent_search,
    finalize_patent_research,
    load_patent_research_run,
    plan_patent_queries_node,
    resolve_patent_families,
    verify_patent_publications,
)
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2G_GRAPH_NAME = "phase2g_patent_prior_art_research"

PHASE_2G_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_PATENT_RESEARCH_RUN,
    NodeId.PLAN_PATENT_QUERIES,
    NodeId.EXECUTE_PATENT_SEARCH,
    NodeId.VERIFY_PATENT_PUBLICATIONS,
    NodeId.RESOLVE_PATENT_FAMILIES,
    NodeId.CAPTURE_PATENT_TEXT,
    NodeId.BUILD_PATENT_CANDIDATES,
    NodeId.FINALIZE_PATENT_RESEARCH,
)

FORBIDDEN_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.NOVELTY,
        NodeId.CLOSEST_PRIOR_ART,
        NodeId.GAP,
        NodeId.SCORING,
        NodeId.TRUST_GATE,
        NodeId.FINAL_VERIFIER,
        NodeId.RED_TEAM,
        NodeId.REPORT_GENERATOR,
        NodeId.CLAIM_EVIDENCE,
        NodeId.PRODUCT_RESEARCH,
        NodeId.OPEN_SOURCE_RESEARCH,
    }
)
"""Stages Phase 2G must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_PATENT_RESEARCH_RUN: load_patent_research_run,
    NodeId.PLAN_PATENT_QUERIES: plan_patent_queries_node,
    NodeId.EXECUTE_PATENT_SEARCH: execute_patent_search,
    NodeId.VERIFY_PATENT_PUBLICATIONS: verify_patent_publications,
    NodeId.RESOLVE_PATENT_FAMILIES: resolve_patent_families,
    NodeId.CAPTURE_PATENT_TEXT: capture_patent_text,
    NodeId.BUILD_PATENT_CANDIDATES: build_patent_candidates,
    NodeId.FINALIZE_PATENT_RESEARCH: finalize_patent_research,
}


def _after_load(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if run is None or run.patent_prior_art is None or run.patent_prior_art.is_terminal:
        return END
    return NodeId.PLAN_PATENT_QUERIES.value


def build_phase2g_patent_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2G graph. The provider arrives per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2G_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_PATENT_RESEARCH_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_PATENT_RESEARCH_RUN.value,
        _after_load,
        {NodeId.PLAN_PATENT_QUERIES.value: NodeId.PLAN_PATENT_QUERIES.value, END: END},
    )
    for source, target in zip(PHASE_2G_NODE_SEQUENCE[1:], PHASE_2G_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_PATENT_RESEARCH.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2G_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2G_GRAPH_NAME",
    "PHASE_2G_NODE_SEQUENCE",
    "build_phase2g_patent_graph",
]
