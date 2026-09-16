"""Phase 2B academic research graph.

A dedicated branch graph, deliberately isolated. It consumes an open
``ResearchRun`` that already carries a Phase 2A verified query plan, and it
performs academic retrieval only -- there is no patent, product, open-source or
standards retrieval here, and no model call anywhere in it.

Execution path::

    START
      -> LOAD_VERIFIED_QUERY_PLAN ------(no open run / no plan)---> END
      -> SELECT_ACADEMIC_QUERIES        eligibility: branch, purpose, PII
      -> ENFORCE_ACADEMIC_BUDGET        query budget -> one request per provider
      -> DISPATCH_ACADEMIC_PROVIDERS    isolated provider calls (ADR-008)
      -> NORMALIZE_ACADEMIC_RESULTS     candidates under the run-level budgets
      -> VERIFY_ACADEMIC_CANDIDATES     deterministic metadata verification
      -> DEDUPLICATE_ACADEMIC_SOURCES   strong-identifier identity (ADR-009)
      -> MERGE_PROVIDER_OBSERVATIONS    conservative merge + branch outcome
      -> UPDATE_ACADEMIC_COVERAGE       coverage counters; the run stays open
      -> END

The run is deliberately left non-terminal: the academic branch is one of
several, and freezing the run here would block every branch that comes after it.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.academic_nodes import (
    deduplicate_academic_sources,
    dispatch_academic_providers,
    enforce_academic_budget,
    load_verified_query_plan,
    merge_provider_observations,
    normalize_academic_results,
    select_academic_queries_node,
    update_academic_coverage,
    verify_academic_candidates_node,
)
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState

PHASE_2B_GRAPH_NAME = "phase2b_academic_research"

PHASE_2B_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_VERIFIED_QUERY_PLAN,
    NodeId.SELECT_ACADEMIC_QUERIES,
    NodeId.ENFORCE_ACADEMIC_BUDGET,
    NodeId.DISPATCH_ACADEMIC_PROVIDERS,
    NodeId.NORMALIZE_ACADEMIC_RESULTS,
    NodeId.VERIFY_ACADEMIC_CANDIDATES,
    NodeId.DEDUPLICATE_ACADEMIC_SOURCES,
    NodeId.MERGE_PROVIDER_OBSERVATIONS,
    NodeId.UPDATE_ACADEMIC_COVERAGE,
)

FORBIDDEN_BRANCH_NODES: frozenset[NodeId] = frozenset(
    {NodeId.PATENT_RESEARCH, NodeId.PRODUCT_RESEARCH, NodeId.OPEN_SOURCE_RESEARCH}
)
"""Branches Phase 2B does not implement. A test asserts none of them is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_VERIFIED_QUERY_PLAN: load_verified_query_plan,
    NodeId.SELECT_ACADEMIC_QUERIES: select_academic_queries_node,
    NodeId.ENFORCE_ACADEMIC_BUDGET: enforce_academic_budget,
    NodeId.DISPATCH_ACADEMIC_PROVIDERS: dispatch_academic_providers,
    NodeId.NORMALIZE_ACADEMIC_RESULTS: normalize_academic_results,
    NodeId.VERIFY_ACADEMIC_CANDIDATES: verify_academic_candidates_node,
    NodeId.DEDUPLICATE_ACADEMIC_SOURCES: deduplicate_academic_sources,
    NodeId.MERGE_PROVIDER_OBSERVATIONS: merge_provider_observations,
    NodeId.UPDATE_ACADEMIC_COVERAGE: update_academic_coverage,
}


def _after_load(state: EvaluationGraphState) -> str:
    """Continue only when the branch actually opened on an open run with a plan."""
    run = state.active_research_run
    if run is None or run.is_terminal or run.academic_research is None:
        return END
    return NodeId.SELECT_ACADEMIC_QUERIES.value


def build_phase2b_academic_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2B graph. Providers are injected per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2B_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_VERIFIED_QUERY_PLAN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_VERIFIED_QUERY_PLAN.value,
        _after_load,
        {
            NodeId.SELECT_ACADEMIC_QUERIES.value: NodeId.SELECT_ACADEMIC_QUERIES.value,
            END: END,
        },
    )
    for source, target in zip(PHASE_2B_NODE_SEQUENCE[1:], PHASE_2B_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.UPDATE_ACADEMIC_COVERAGE.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2B_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_BRANCH_NODES",
    "PHASE_2B_GRAPH_NAME",
    "PHASE_2B_NODE_SEQUENCE",
    "build_phase2b_academic_graph",
]
