"""Phase 1A infrastructure harness graph.

THIS IS NOT THE PRODUCTION EVALUATION GRAPH.

It exists to prove that the workflow infrastructure is correct before any
intelligence is added: that a graph compiles, that canonical state survives the
node boundary, that checkpoints persist, that interrupt and resume work on one
thread, that routing is conditional and deterministic, and that a replayed node
does not duplicate its effects.

No node here calls a model or an external service. The production graph, built
from ``NodeId``, arrives in later phases.

Execution path::

    START
      -> INITIALIZE_RUN
      -> VALIDATE_PROJECT_STATE ---(invalid)---> END
      -> CHECK_CRITICAL_INPUT
           |-- gate satisfied ------------------> MARK_READY -> END
           |-- input already requested ---------> MARK_BLOCKED -> END
           `-- fields missing ------------------> REQUEST_INPUT
                                                    (interrupt)
                                                    (resume)
                                                  APPLY_INPUT ---(rejected)---> END
                                                    -> VALIDATE_PROJECT_STATE
                                                    -> CHECK_CRITICAL_INPUT ...
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.nodes import (
    apply_input,
    check_critical_input,
    initialize_run,
    mark_blocked,
    mark_ready,
    request_input,
    validate_project_state,
)
from src.graph.persistence import build_checkpointer
from src.graph.registry import Phase1ANode
from src.graph.routing import (
    route_after_apply_input,
    route_after_critical_check,
    route_after_validation,
)
from src.graph.workflow_state import EvaluationGraphState

PHASE_1A_GRAPH_NAME = "phase1a_infrastructure_harness"


def build_phase1a_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 1A harness graph.

    The checkpointer is injected, never constructed inline, so a durable saver
    can replace the in-memory one without touching this function.
    """
    builder: StateGraph = StateGraph(EvaluationGraphState)

    builder.add_node(Phase1ANode.INITIALIZE_RUN.value, initialize_run)
    builder.add_node(Phase1ANode.VALIDATE_PROJECT_STATE.value, validate_project_state)
    builder.add_node(Phase1ANode.CHECK_CRITICAL_INPUT.value, check_critical_input)
    builder.add_node(Phase1ANode.REQUEST_INPUT.value, request_input)
    builder.add_node(Phase1ANode.APPLY_INPUT.value, apply_input)
    builder.add_node(Phase1ANode.MARK_READY.value, mark_ready)
    builder.add_node(Phase1ANode.MARK_BLOCKED.value, mark_blocked)

    builder.add_edge(START, Phase1ANode.INITIALIZE_RUN.value)
    builder.add_edge(
        Phase1ANode.INITIALIZE_RUN.value, Phase1ANode.VALIDATE_PROJECT_STATE.value
    )

    builder.add_conditional_edges(
        Phase1ANode.VALIDATE_PROJECT_STATE.value,
        route_after_validation,
        {Phase1ANode.CHECK_CRITICAL_INPUT.value: Phase1ANode.CHECK_CRITICAL_INPUT.value, END: END},
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
        route_after_apply_input,
        {
            Phase1ANode.VALIDATE_PROJECT_STATE.value: Phase1ANode.VALIDATE_PROJECT_STATE.value,
            END: END,
        },
    )

    builder.add_edge(Phase1ANode.MARK_READY.value, END)
    builder.add_edge(Phase1ANode.MARK_BLOCKED.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_1A_GRAPH_NAME,
    )


__all__ = ["PHASE_1A_GRAPH_NAME", "build_phase1a_graph"]
