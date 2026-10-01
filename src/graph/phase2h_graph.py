"""Phase 2H product and open-source prior-art research graph.

A dedicated branch graph in the Phase 2B-2G shape. It consumes an open
research run and stops at discovery *candidates*, leaving the research run
non-terminal so later branches can still write to it.

Execution path::

    START
      -> LOAD_PRODUCT_OSS_RESEARCH_RUN --(no open run)------------------> END
      -> PLAN_PRODUCT_OSS_QUERIES       canonical claim text -> validated queries
      -> EXECUTE_PRODUCT_SEARCH         web discovery observations, bounded
      -> FETCH_PRODUCT_ARTIFACTS        SSRF-safe fetch; observation -> artifact
      -> RESOLVE_PRODUCT_IDENTITY       strong identity / identical content only
      -> BUILD_PRODUCT_CANDIDATES       chronology against an explicit cutoff
      -> EXECUTE_OPEN_SOURCE_SEARCH     repository + code discovery, bounded
      -> VERIFY_REPOSITORIES            hit -> repository keyed on stable id
      -> CAPTURE_REPOSITORY_SNAPSHOTS   README / manifests / releases / fragments
      -> RESOLVE_REPOSITORY_NETWORKS    provider-declared fork / mirror / template
      -> BUILD_OPEN_SOURCE_CANDIDATES   chronology; independent-root flag
      -> FINALIZE_PRODUCT_OSS_RESEARCH  coverage re-derived; both subruns closed
      -> END

The two trust boundaries -- fetch (search hit -> artifact) and verification
(code/repository hit -> verified repository) -- are their own nodes so the
boundary is visible in the graph (ADR-003, ADR-019).

**No later phase.** ``NOVELTY``, ``CLOSEST_PRIOR_ART``, ``SCORING`` and the
rest are in ``FORBIDDEN_NODES``, and so is every Phase 2G patent node: a patent
candidate is never an automatic product or repository match.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph import product_oss_nodes as n
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2H_GRAPH_NAME = "phase2h_product_oss_prior_art_research"

PHASE_2H_NODE_SEQUENCE: tuple[NodeId, ...] = (
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
        NodeId.LOAD_PATENT_RESEARCH_RUN,
        NodeId.PLAN_PATENT_QUERIES,
        NodeId.EXECUTE_PATENT_SEARCH,
        NodeId.VERIFY_PATENT_PUBLICATIONS,
        NodeId.RESOLVE_PATENT_FAMILIES,
        NodeId.CAPTURE_PATENT_TEXT,
        NodeId.BUILD_PATENT_CANDIDATES,
        NodeId.FINALIZE_PATENT_RESEARCH,
    }
)
"""Stages Phase 2H must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_PRODUCT_OSS_RESEARCH_RUN: n.load_product_oss_research_run,
    NodeId.PLAN_PRODUCT_OSS_QUERIES: n.plan_product_oss_queries,
    NodeId.EXECUTE_PRODUCT_SEARCH: n.execute_product_search,
    NodeId.FETCH_PRODUCT_ARTIFACTS: n.fetch_product_artifacts,
    NodeId.RESOLVE_PRODUCT_IDENTITY: n.resolve_product_identity,
    NodeId.BUILD_PRODUCT_CANDIDATES: n.build_product_candidates,
    NodeId.EXECUTE_OPEN_SOURCE_SEARCH: n.execute_open_source_search,
    NodeId.VERIFY_REPOSITORIES: n.verify_repositories,
    NodeId.CAPTURE_REPOSITORY_SNAPSHOTS: n.capture_repository_snapshots,
    NodeId.RESOLVE_REPOSITORY_NETWORKS: n.resolve_repository_networks,
    NodeId.BUILD_OPEN_SOURCE_CANDIDATES: n.build_open_source_candidates,
    NodeId.FINALIZE_PRODUCT_OSS_RESEARCH: n.finalize_product_oss_research,
}


def _after_load(state: EvaluationGraphState) -> str:
    run = state.active_research_run
    if (
        run is None
        or run.product_prior_art is None
        or run.open_source_prior_art is None
        or (run.product_prior_art.is_terminal and run.open_source_prior_art.is_terminal)
    ):
        return END
    return NodeId.PLAN_PRODUCT_OSS_QUERIES.value


def build_phase2h_product_oss_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2H graph. Providers arrive per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2H_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])
    builder.add_edge(START, NodeId.LOAD_PRODUCT_OSS_RESEARCH_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_PRODUCT_OSS_RESEARCH_RUN.value,
        _after_load,
        {NodeId.PLAN_PRODUCT_OSS_QUERIES.value: NodeId.PLAN_PRODUCT_OSS_QUERIES.value, END: END},
    )
    for source, target in zip(PHASE_2H_NODE_SEQUENCE[1:], PHASE_2H_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_PRODUCT_OSS_RESEARCH.value, END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2H_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2H_GRAPH_NAME",
    "PHASE_2H_NODE_SEQUENCE",
    "build_phase2h_product_oss_graph",
]
