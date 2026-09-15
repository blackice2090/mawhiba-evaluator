"""Phase 1B headless intake graph.

The first graph built from production ``NodeId`` identifiers rather than the
Phase 1A harness vocabulary. It is still not the full production evaluation
graph: it covers intake, extraction, provenance verification, merge and
classification, and stops at the same demo gate Phase 1A used.

The Phase 1A harness (`build_phase1a_graph`) is untouched and still compiles --
this is a separate graph, not a mutation of it.

Execution path::

    START
      -> INITIALIZE_RUN
      -> INGEST_SUBMISSION (INTAKE_GUARD) --(no artifact)--> END
      -> PROJECT_EXTRACTOR --(refusal / provider failure)--> END
      -> PROJECT_EXTRACTOR_VERIFIER          deterministic trust boundary
      -> PROJECT_STATE_MERGE
      -> PROJECT_TYPE_CLASSIFIER             failure here is non-fatal
      -> CLASSIFICATION_MERGE
      -> CHECK_CRITICAL_INPUT
           |-- gate satisfied ------> MARK_READY   -> END
           |-- budget spent --------> MARK_BLOCKED -> END
           `-- fields missing ------> REQUEST_INPUT
                                        (interrupt / resume)
                                      APPLY_INPUT --(rejected)--> END
                                        -> CHECK_CRITICAL_INPUT
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.intake_nodes import (
    ingest_submission,
    merge_classification_result,
    merge_project_state,
    project_extractor,
    project_type_classifier,
    verify_extraction_provenance,
)
from src.graph.nodes import apply_input, check_critical_input, initialize_run
from src.graph.nodes import mark_blocked, mark_ready, request_input
from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId, Phase1ANode
from src.graph.routing import route_after_critical_check
from src.graph.workflow_state import EvaluationGraphState
from src.graph.contracts import WorkflowStatus

PHASE_1B_GRAPH_NAME = "phase1b_trusted_intake"


def _halt_on_failure(next_node: str):
    """Build a router that ends the run when a node marked it FAILED."""

    def route(state: EvaluationGraphState) -> str:
        return END if state.status is WorkflowStatus.FAILED else next_node

    return route


def build_phase1b_intake_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 1B trusted-intake graph.

    The model provider is not a build-time dependency: it is injected per run
    through ``config['configurable']['structured_model_provider']``, which keeps
    graph construction free of credentials and lets tests supply a fake.
    """
    builder: StateGraph = StateGraph(EvaluationGraphState)

    builder.add_node(Phase1ANode.INITIALIZE_RUN.value, initialize_run)
    builder.add_node(NodeId.INTAKE_GUARD.value, ingest_submission)
    builder.add_node(NodeId.PROJECT_EXTRACTOR.value, project_extractor)
    builder.add_node(
        NodeId.PROJECT_EXTRACTOR_VERIFIER.value, verify_extraction_provenance
    )
    builder.add_node(NodeId.PROJECT_STATE_MERGE.value, merge_project_state)
    builder.add_node(NodeId.PROJECT_TYPE_CLASSIFIER.value, project_type_classifier)
    builder.add_node(NodeId.CLASSIFICATION_MERGE.value, merge_classification_result)
    builder.add_node(Phase1ANode.CHECK_CRITICAL_INPUT.value, check_critical_input)
    builder.add_node(Phase1ANode.REQUEST_INPUT.value, request_input)
    builder.add_node(Phase1ANode.APPLY_INPUT.value, apply_input)
    builder.add_node(Phase1ANode.MARK_READY.value, mark_ready)
    builder.add_node(Phase1ANode.MARK_BLOCKED.value, mark_blocked)

    builder.add_edge(START, Phase1ANode.INITIALIZE_RUN.value)
    builder.add_edge(Phase1ANode.INITIALIZE_RUN.value, NodeId.INTAKE_GUARD.value)

    # A missing artifact or a refused/failed extraction ends the run without
    # touching ProjectState.
    for source, target in (
        (NodeId.INTAKE_GUARD.value, NodeId.PROJECT_EXTRACTOR.value),
        (NodeId.PROJECT_EXTRACTOR.value, NodeId.PROJECT_EXTRACTOR_VERIFIER.value),
        (NodeId.PROJECT_EXTRACTOR_VERIFIER.value, NodeId.PROJECT_STATE_MERGE.value),
        (NodeId.PROJECT_STATE_MERGE.value, NodeId.PROJECT_TYPE_CLASSIFIER.value),
        (NodeId.CLASSIFICATION_MERGE.value, Phase1ANode.CHECK_CRITICAL_INPUT.value),
    ):
        builder.add_conditional_edges(
            source, _halt_on_failure(target), {target: target, END: END}
        )

    builder.add_edge(
        NodeId.PROJECT_TYPE_CLASSIFIER.value, NodeId.CLASSIFICATION_MERGE.value
    )

    builder.add_conditional_edges(
        Phase1ANode.CHECK_CRITICAL_INPUT.value,
        route_after_critical_check,
        {
            Phase1ANode.MARK_READY.value: Phase1ANode.MARK_READY.value,
            Phase1ANode.MARK_BLOCKED.value: Phase1ANode.MARK_BLOCKED.value,
            Phase1ANode.REQUEST_INPUT.value: Phase1ANode.REQUEST_INPUT.value,
        },
    )
    builder.add_edge(Phase1ANode.REQUEST_INPUT.value, Phase1ANode.APPLY_INPUT.value)
    builder.add_conditional_edges(
        Phase1ANode.APPLY_INPUT.value,
        _halt_on_failure(Phase1ANode.CHECK_CRITICAL_INPUT.value),
        {
            Phase1ANode.CHECK_CRITICAL_INPUT.value: Phase1ANode.CHECK_CRITICAL_INPUT.value,
            END: END,
        },
    )
    builder.add_edge(Phase1ANode.MARK_READY.value, END)
    builder.add_edge(Phase1ANode.MARK_BLOCKED.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_1B_GRAPH_NAME,
    )


__all__ = ["PHASE_1B_GRAPH_NAME", "build_phase1b_intake_graph"]
