"""Phase 1A workflow infrastructure tests.

Everything here runs with no OpenAI key, no network and no external credentials.
If any test in this file needed one, Phase 1A would be incorrectly scoped.

Persistence note: InMemorySaver validates checkpoint semantics -- that state is
written, restored on resume, and isolated per thread. It does NOT prove durable
persistence across process restarts. That is tested later with PostgreSQL.
"""

from __future__ import annotations

import warnings
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.graph.contracts import (
    InterruptType,
    NodeStatus,
    WorkflowStatus,
)
from src.graph.persistence import (
    CHECKPOINTED_TYPES,
    CheckpointerKind,
    build_checkpointer,
    thread_config,
)
from src.graph.phase1a_graph import PHASE_1A_GRAPH_NAME, build_phase1a_graph
from src.graph.registry import (
    PARALLEL_RESEARCH_NODES,
    PRODUCTION_NODE_ORDER,
    NodeId,
    Phase1ANode,
)
from src.graph.routing import (
    MAX_INPUT_REQUESTS,
    PHASE_1A_DEMO_GATE,
    demo_gate_missing_fields,
    route_after_critical_check,
)
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    is_safe_thread_id,
    merge_unique_ordered,
    new_thread_id,
)
from src.schemas.common import KnowledgeStatus, Tracked, ValueOrigin
from src.workflow.errors import WorkflowErrorCode, WorkflowErrorReport

COMPLETE_ANSWER = {
    "identity.project_name": "PiezoLeak",
    "problem.statement": "Small municipal water leaks go undetected for weeks.",
    "solution.description": "An in-pipe node classifying piezo vibration signatures.",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checkpointer() -> BaseCheckpointSaver:
    return build_checkpointer(CheckpointerKind.IN_MEMORY)


@pytest.fixture
def app(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return build_phase1a_graph(checkpointer)


@pytest.fixture
def run_id() -> UUID:
    return uuid4()


@pytest.fixture
def config(run_id: UUID) -> dict:
    return thread_config(new_thread_id(run_id))


def _initial_state(run_id: UUID, config: dict, project: ProjectState | None = None):
    return EvaluationGraphState(
        run_id=run_id,
        thread_id=config["configurable"]["thread_id"],
        project=project if project is not None else ProjectState(),
    )


def _complete_project() -> ProjectState:
    project = ProjectState()
    project.identity.project_name = Tracked[str].known(
        "PiezoLeak", origin=ValueOrigin.STUDENT_FILE
    )
    project.problem.statement = Tracked[str].known(
        "Small municipal water leaks go undetected.", origin=ValueOrigin.STUDENT_FILE
    )
    project.solution.description = Tracked[str].known(
        "An in-pipe piezo vibration node.", origin=ValueOrigin.STUDENT_FILE
    )
    return project


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def test_graph_compiles(app: CompiledStateGraph) -> None:
    assert app is not None
    assert app.name == PHASE_1A_GRAPH_NAME


def test_graph_registers_every_phase1a_node(app: CompiledStateGraph) -> None:
    graph_nodes = set(app.get_graph().nodes) - {"__start__", "__end__"}
    assert graph_nodes == {node.value for node in Phase1ANode}


def test_graph_builds_without_an_explicit_checkpointer() -> None:
    """The default path still injects a saver rather than running unsaved."""
    assert build_phase1a_graph() is not None


def test_production_node_registry_is_complete() -> None:
    """Section 8-23 identifiers are declared, even though they do not run yet."""
    assert len(PRODUCTION_NODE_ORDER) == len(NodeId)
    assert set(PRODUCTION_NODE_ORDER) == set(NodeId)
    assert PARALLEL_RESEARCH_NODES.issubset(set(NodeId))


def test_phase1a_nodes_are_distinct_from_production_nodes() -> None:
    """The harness must never be mistaken for the production evaluation graph."""
    assert {n.value for n in Phase1ANode}.isdisjoint({n.value for n in NodeId})


# ---------------------------------------------------------------------------
# thread_id / run_id
# ---------------------------------------------------------------------------

def test_thread_id_is_opaque_and_uuid_derived(run_id: UUID) -> None:
    thread_id = new_thread_id(run_id)
    assert thread_id == f"thr-{run_id}"
    assert is_safe_thread_id(thread_id)


def test_thread_id_is_stable_for_a_run_id(run_id: UUID) -> None:
    assert new_thread_id(run_id) == new_thread_id(run_id)


def test_thread_ids_are_unique_without_a_run_id() -> None:
    assert new_thread_id() != new_thread_id()


@pytest.mark.parametrize(
    "unsafe",
    [
        "thr-Ahmed Al-Otaibi",
        "thr-student@example.org",
        "thr-Smart Crop Disease Detector",
        "project-1",
        "thr-not-a-uuid",
        "",
    ],
)
def test_pii_bearing_thread_ids_are_rejected(unsafe: str) -> None:
    """Names, titles and email addresses must never become a thread id."""
    assert not is_safe_thread_id(unsafe)


def test_run_id_and_thread_id_are_separate_concepts(run_id: UUID) -> None:
    state = EvaluationGraphState(run_id=run_id, thread_id=new_thread_id(run_id))
    assert str(state.run_id) != state.thread_id
    assert str(run_id) in state.thread_id


# ---------------------------------------------------------------------------
# Happy path -- no interrupt
# ---------------------------------------------------------------------------

def test_happy_path_completes_without_interrupt(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    result = app.invoke(_initial_state(run_id, config, _complete_project()), config)
    assert "__interrupt__" not in result

    state = coerce_graph_state(result)
    assert state.status is WorkflowStatus.COMPLETED
    assert state.completed_nodes == [
        Phase1ANode.INITIALIZE_RUN.value,
        Phase1ANode.VALIDATE_PROJECT_STATE.value,
        Phase1ANode.CHECK_CRITICAL_INPUT.value,
        Phase1ANode.MARK_READY.value,
    ]
    assert state.errors == []


def test_happy_path_never_requests_input(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    state = coerce_graph_state(
        app.invoke(_initial_state(run_id, config, _complete_project()), config)
    )
    assert state.input_requests == 0
    assert state.interrupt_request is None
    assert Phase1ANode.REQUEST_INPUT.value not in state.completed_nodes


def test_every_executed_node_records_a_result(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    state = coerce_graph_state(
        app.invoke(_initial_state(run_id, config, _complete_project()), config)
    )
    for node in state.completed_nodes:
        record = state.record_for(node)
        assert record is not None
        assert record.status is NodeStatus.SUCCEEDED
        assert record.last_completed_at is not None
        assert record.result is not None


# ---------------------------------------------------------------------------
# Interrupt path
# ---------------------------------------------------------------------------

def test_incomplete_project_interrupts(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    result = app.invoke(_initial_state(run_id, config), config)
    assert "__interrupt__" in result

    payload = result["__interrupt__"][0].value
    assert payload["type"] == InterruptType.MISSING_CRITICAL_INFORMATION.value
    assert payload["node"] == Phase1ANode.REQUEST_INPUT.value
    assert set(payload["fields"]) == {field.value for field in PHASE_1A_DEMO_GATE}
    assert payload["message"] == "Additional project information is required."


def test_interrupt_payload_is_json_serializable(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    import json

    result = app.invoke(_initial_state(run_id, config), config)
    payload = result["__interrupt__"][0].value
    assert json.loads(json.dumps(payload)) == payload


def test_graph_halts_at_the_interrupting_node(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    snapshot = app.get_state(config)
    assert snapshot.next == (Phase1ANode.REQUEST_INPUT.value,)


def test_no_side_effects_are_committed_before_the_interrupt(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """REQUEST_INPUT calls interrupt() first, so it commits nothing on pass one."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.get_state(config).values)
    assert Phase1ANode.REQUEST_INPUT.value not in state.completed_nodes
    assert state.input_requests == 0
    assert [event.event_type for event in state.audit_events] == ["RUN_INITIALIZED"]


# ---------------------------------------------------------------------------
# Persistence / checkpoint semantics
# ---------------------------------------------------------------------------

def test_checkpoint_exists_after_the_interrupt(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    snapshot = app.get_state(config)
    assert snapshot.config["configurable"]["checkpoint_id"]
    assert snapshot.values["completed_nodes"]


def test_checkpoint_preserves_the_canonical_project(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    project = ProjectState()
    project.identity.project_name = Tracked[str].known("Partial project")
    app.invoke(_initial_state(run_id, config, project), config)

    restored = coerce_graph_state(app.get_state(config).values)
    assert restored.project.identity.project_name.value == "Partial project"
    assert restored.run_id == run_id


def test_checkpoint_history_accumulates(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    assert len(list(app.get_state_history(config))) > 1


def test_every_checkpointed_type_is_registered_with_the_serializer() -> None:
    names = {t.__name__ for t in CHECKPOINTED_TYPES}
    for expected in ("ProjectState", "EvaluationGraphState", "Tracked", "WorkflowError"):
        assert expected in names


def test_graph_execution_emits_no_serialization_warnings(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """An unregistered type warns today and is blocked in future LangGraph."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        app.invoke(_initial_state(run_id, config), config)
        app.invoke(Command(resume=COMPLETE_ANSWER), config)


def test_requesting_an_unimplemented_checkpointer_fails_loudly() -> None:
    with pytest.raises(WorkflowErrorReport) as exc:
        build_checkpointer(CheckpointerKind.POSTGRES)
    assert exc.value.error.code is WorkflowErrorCode.CHECKPOINTER_UNAVAILABLE


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def test_resume_completes_the_graph(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert state.status is WorkflowStatus.COMPLETED
    assert state.has_completed(Phase1ANode.MARK_READY.value)


def test_resume_restores_previous_state(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    project = ProjectState()
    project.identity.project_name = Tracked[str].known("Preserved name")
    app.invoke(_initial_state(run_id, config, project), config)

    state = coerce_graph_state(
        app.invoke(
            Command(
                resume={
                    "problem.statement": "A stated problem.",
                    "solution.description": "A described solution.",
                }
            ),
            config,
        )
    )
    assert state.project.identity.project_name.value == "Preserved name"
    assert state.run_id == run_id


def test_resume_applies_supplied_data_through_the_patch_boundary(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    assert state.project.problem.statement.value == COMPLETE_ANSWER["problem.statement"]
    assert state.project.problem.statement.status is KnowledgeStatus.KNOWN
    assert state.project.problem.statement.origin is ValueOrigin.STUDENT_MESSAGE


def test_resume_clears_the_interrupt_request(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert state.interrupt_request is None
    assert state.pending_input is None


def test_resume_on_a_different_thread_does_not_load_the_first_project(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """Thread isolation: one project's checkpoint must not leak into another."""
    first = ProjectState()
    first.identity.project_name = Tracked[str].known("First project")
    app.invoke(_initial_state(run_id, config, first), config)

    other_run = uuid4()
    other_config = thread_config(new_thread_id(other_run))
    second = ProjectState()
    second.identity.project_name = Tracked[str].known("Second project")
    app.invoke(_initial_state(other_run, other_config, second), other_config)

    other_state = coerce_graph_state(app.get_state(other_config).values)
    assert other_state.project.identity.project_name.value == "Second project"
    assert other_state.run_id == other_run

    original = coerce_graph_state(app.get_state(config).values)
    assert original.project.identity.project_name.value == "First project"
    assert original.run_id == run_id


def test_an_unknown_thread_has_no_state(app: CompiledStateGraph) -> None:
    snapshot = app.get_state(thread_config(new_thread_id()))
    assert snapshot.values in ({}, None) or not snapshot.values.get("completed_nodes")


# ---------------------------------------------------------------------------
# Invalid resume data
# ---------------------------------------------------------------------------

def test_unsupported_resume_field_is_rejected_safely(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """No generic JSON Patch: an unlisted path is refused, not applied."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"scores": "100"}), config)
    )
    assert state.status is WorkflowStatus.FAILED
    assert state.errors[0].code is WorkflowErrorCode.UNSUPPORTED_PATCH_FIELD
    assert state.errors[0].recoverable is True


def test_blank_resume_value_is_rejected(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"problem.statement": "   "}), config)
    )
    assert state.status is WorkflowStatus.FAILED
    assert state.errors[0].code is WorkflowErrorCode.INVALID_RESUME_INPUT


def test_non_string_resume_value_is_rejected(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"problem.statement": 42}), config)
    )
    assert state.status is WorkflowStatus.FAILED
    assert state.errors[0].code is WorkflowErrorCode.INVALID_RESUME_INPUT


def test_rejected_resume_leaves_the_canonical_project_untouched(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"scores": "100"}), config)
    )
    assert state.project.identity.project_name.status is KnowledgeStatus.UNKNOWN
    assert state.project.scores == []


def test_errors_never_carry_a_traceback(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """Tracebacks belong in developer logs, never in domain state."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"scores": "100"}), config)
    )
    for error in state.errors:
        assert "Traceback" not in error.message
        assert "\n" not in error.message


# ---------------------------------------------------------------------------
# Partial resume and the bounded retry
# ---------------------------------------------------------------------------

def test_partial_resume_blocks_after_the_permitted_request(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """An incomplete answer must terminate, not loop forever."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"problem.statement": "Only the problem."}), config)
    )
    assert state.status is WorkflowStatus.FAILED
    assert state.has_completed(Phase1ANode.MARK_BLOCKED.value)
    assert state.errors[0].code is WorkflowErrorCode.CRITICAL_INPUT_STILL_MISSING
    assert state.input_requests == MAX_INPUT_REQUESTS


def test_partial_resume_keeps_what_was_supplied(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(
        app.invoke(Command(resume={"problem.statement": "Only the problem."}), config)
    )
    assert state.project.problem.statement.value == "Only the problem."
    assert state.project.solution.description.status is KnowledgeStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Idempotency / replay
# ---------------------------------------------------------------------------

def test_replayed_nodes_never_duplicate_completion_entries(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert len(state.completed_nodes) == len(set(state.completed_nodes))


def test_completion_order_is_preserved_across_a_resume(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert state.completed_nodes == [
        Phase1ANode.INITIALIZE_RUN.value,
        Phase1ANode.VALIDATE_PROJECT_STATE.value,
        Phase1ANode.CHECK_CRITICAL_INPUT.value,
        Phase1ANode.REQUEST_INPUT.value,
        Phase1ANode.APPLY_INPUT.value,
        Phase1ANode.MARK_READY.value,
    ]


def test_audit_events_are_not_duplicated_by_replay(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    keys = [event.event_key for event in state.audit_events]
    assert len(keys) == len(set(keys))
    assert [event.event_type for event in state.audit_events] == [
        "RUN_INITIALIZED",
        "INPUT_REQUESTED",
        "INPUT_APPLIED",
        "RUN_COMPLETED",
    ]


def test_node_execution_records_are_keyed_not_appended(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert set(state.node_results) == set(state.completed_nodes)


def test_replays_are_recorded_as_attempts_not_as_completions(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """completed_nodes is a set; node_execution_attempts is an honest log."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    validate = Phase1ANode.VALIDATE_PROJECT_STATE.value
    assert state.completed_nodes.count(validate) == 1
    assert state.attempts_for(validate) == 2
    assert any(
        attempt.node == validate and attempt.replayed
        for attempt in state.node_execution_attempts
    )
    assert state.record_for(validate).attempts == 2


def test_initialize_run_keeps_its_thread_id_on_replay(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """A replay must not mint a new thread id and orphan the checkpoint."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert state.thread_id == config["configurable"]["thread_id"]


def test_errors_are_deduplicated_across_replays() -> None:
    from src.workflow.errors import WorkflowError

    from src.graph.workflow_state import merge_unique_errors

    error = WorkflowError(
        code=WorkflowErrorCode.INVALID_RESUME_INPUT, node="APPLY_INPUT", message="bad"
    )
    assert len(merge_unique_errors([error], [error.model_copy()])) == 1


def test_merge_unique_ordered_is_stable_and_deduplicating() -> None:
    assert merge_unique_ordered(["A", "B"], ["B", "C", "A"]) == ["A", "B", "C"]
    assert merge_unique_ordered([], []) == []


# ---------------------------------------------------------------------------
# Canonical model integrity
# ---------------------------------------------------------------------------

def test_project_state_remains_valid_after_execution(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert ProjectState.model_validate(state.project.model_dump()) == state.project


def test_graph_state_never_duplicates_project_fields() -> None:
    """One canonical domain state: the wrapper must not shadow ProjectState."""
    overlap = set(EvaluationGraphState.model_fields) & set(ProjectState.model_fields)
    assert overlap == set()


def test_graph_state_round_trips_through_json(run_id: UUID) -> None:
    state = EvaluationGraphState(run_id=run_id, thread_id=new_thread_id(run_id))
    restored = EvaluationGraphState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_completed_state_round_trips_through_json(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert EvaluationGraphState.model_validate_json(state.model_dump_json()) == state


def test_coerce_graph_state_drops_the_interrupt_channel(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    result = app.invoke(_initial_state(run_id, config), config)
    assert "__interrupt__" in result
    assert coerce_graph_state(result).status is WorkflowStatus.RUNNING


# ---------------------------------------------------------------------------
# Routing purity
# ---------------------------------------------------------------------------

def test_routing_is_a_pure_function_of_state(run_id: UUID) -> None:
    empty = EvaluationGraphState(run_id=run_id)
    assert route_after_critical_check(empty) == Phase1ANode.REQUEST_INPUT.value
    assert route_after_critical_check(empty) == Phase1ANode.REQUEST_INPUT.value


def test_routing_sends_a_satisfied_gate_to_mark_ready(run_id: UUID) -> None:
    state = EvaluationGraphState(run_id=run_id, project=_complete_project())
    assert route_after_critical_check(state) == Phase1ANode.MARK_READY.value


def test_routing_blocks_once_the_request_budget_is_spent(run_id: UUID) -> None:
    state = EvaluationGraphState(run_id=run_id, input_requests=MAX_INPUT_REQUESTS)
    assert route_after_critical_check(state) == Phase1ANode.MARK_BLOCKED.value


def test_demo_gate_treats_conflicted_values_as_missing(run_id: UUID) -> None:
    """Zero-Assumption: a CONFLICTED value is not a known value."""
    project = _complete_project()
    project.problem.statement = Tracked[str].conflicted(["A problem", "Another problem"])
    state = EvaluationGraphState(run_id=run_id, project=project)
    assert demo_gate_missing_fields(state) == ["problem.statement"]


def test_demo_gate_treats_inferred_values_as_missing(run_id: UUID) -> None:
    project = _complete_project()
    project.solution.description = Tracked[str].inferred("Probably a mobile app")
    state = EvaluationGraphState(run_id=run_id, project=project)
    assert demo_gate_missing_fields(state) == ["solution.description"]
