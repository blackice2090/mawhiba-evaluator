"""Phase 2A research foundation graph.

Consumes an already-trusted canonical ``ProjectState``. It never writes the
``project`` channel, and it performs no academic, patent, product, open-source
or standards retrieval -- those branches receive verified plans only.

Execution path::

    START
      -> LOAD_PROJECT_STATE ---------(invalid state)---> END
      -> VALIDATE_RESEARCH_INPUT
      -> RESEARCH_QUERY_PLANNER            model -> candidate plan (untrusted)
      -> VERIFY_QUERY_PLAN                 deterministic query verification
      -> OFFICIAL_REQUIREMENTS_RETRIEVAL   provider -> SourceCandidate (untrusted)
      -> VERIFY_OFFICIAL_SOURCES           allowlist + hash -> snapshot / SourceRecord
      -> EXTRACT_OFFICIAL_REQUIREMENTS     model -> anchor-verified requirements
      -> UPDATE_RESEARCH_COVERAGE          coverage + terminal run status
      -> END

A node with nothing to do records SKIPPED; research failures are recorded on the
ResearchRun and never stop the remaining stages.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.contracts import WorkflowStatus
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.research_nodes import (
    extract_official_requirements,
    load_project_state,
    official_requirements_retrieval,
    research_query_planner,
    update_research_coverage,
    validate_research_input,
    verify_official_sources,
    verify_query_plan_node,
)
from src.graph.workflow_state import EvaluationGraphState

PHASE_2A_GRAPH_NAME = "phase2a_research_foundation"

PHASE_2A_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_PROJECT_STATE,
    NodeId.VALIDATE_RESEARCH_INPUT,
    NodeId.RESEARCH_QUERY_PLANNER,
    NodeId.VERIFY_QUERY_PLAN,
    NodeId.OFFICIAL_REQUIREMENTS_RETRIEVAL,
    NodeId.VERIFY_OFFICIAL_SOURCES,
    NodeId.EXTRACT_OFFICIAL_REQUIREMENTS,
    NodeId.UPDATE_RESEARCH_COVERAGE,
)

_NODE_FUNCTIONS = {
    NodeId.LOAD_PROJECT_STATE: load_project_state,
    NodeId.VALIDATE_RESEARCH_INPUT: validate_research_input,
    NodeId.RESEARCH_QUERY_PLANNER: research_query_planner,
    NodeId.VERIFY_QUERY_PLAN: verify_query_plan_node,
    NodeId.OFFICIAL_REQUIREMENTS_RETRIEVAL: official_requirements_retrieval,
    NodeId.VERIFY_OFFICIAL_SOURCES: verify_official_sources,
    NodeId.EXTRACT_OFFICIAL_REQUIREMENTS: extract_official_requirements,
    NodeId.UPDATE_RESEARCH_COVERAGE: update_research_coverage,
}


def _after_load(state: EvaluationGraphState) -> str:
    if state.status is WorkflowStatus.FAILED:
        return END
    return NodeId.VALIDATE_RESEARCH_INPUT.value


def build_phase2a_research_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2A graph. Providers are injected per run via config."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2A_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_PROJECT_STATE.value)
    builder.add_conditional_edges(
        NodeId.LOAD_PROJECT_STATE.value,
        _after_load,
        {NodeId.VALIDATE_RESEARCH_INPUT.value: NodeId.VALIDATE_RESEARCH_INPUT.value, END: END},
    )
    for source, target in zip(PHASE_2A_NODE_SEQUENCE[1:], PHASE_2A_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.UPDATE_RESEARCH_COVERAGE.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2A_GRAPH_NAME,
    )


__all__ = ["PHASE_2A_GRAPH_NAME", "PHASE_2A_NODE_SEQUENCE", "build_phase2a_research_graph"]
