"""Phase 1A infrastructure nodes.

Every node here is pure: state in, deterministic transformation, state update.
No model call, no network, no filesystem, no clock-dependent branching. The only
non-determinism is timestamping, which never affects routing.

Replay contract: LangGraph re-executes an interrupted node from its first line
on resume. Therefore REQUEST_INPUT calls ``interrupt()`` before doing anything
else, and every node's emitted updates are absorbed idempotently by the channel
reducers in workflow_state.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langgraph.types import interrupt

from src.graph.contracts import (
    AuditEvent,
    InterruptRequest,
    InterruptType,
    NodeAttempt,
    NodeExecutionRecord,
    NodeResult,
    NodeStatus,
    WorkflowStatus,
)
from src.graph.registry import Phase1ANode
from src.graph.routing import demo_gate_missing_fields
from src.graph.state import ProjectState
from src.graph.workflow_state import EvaluationGraphState, new_thread_id
from src.workflow.clock import workflow_now
from src.workflow.errors import WorkflowError, WorkflowErrorCode, WorkflowErrorReport
from src.workflow.patches import ProjectPatch, apply_project_patch


def _completion(
    state: EvaluationGraphState,
    node: Phase1ANode,
    result: NodeResult,
    started_at: datetime,
    *,
    status: NodeStatus = NodeStatus.SUCCEEDED,
) -> dict[str, Any]:
    """Build the standard bookkeeping update for a finishing node.

    ``started_at`` is captured by the caller when it *entered this attempt*, so a
    replayed node times only its own pass and never inherits the timestamp from
    before an interrupt pause.

    Every field written here goes through a replay-safe reducer:
    ``completed_nodes`` de-duplicates, ``node_results`` is keyed by node, and
    ``node_execution_attempts`` records the replay honestly.
    """
    now = workflow_now()
    previous = state.record_for(node.value)
    attempt_number = state.attempts_for(node.value) + 1
    record = NodeExecutionRecord(
        node=node.value,
        # Lifecycle: first entry ever, not this attempt's start.
        first_started_at=previous.first_started_at if previous else started_at,
        last_completed_at=now,
        status=status,
        attempts=attempt_number,
        result=result,
    )
    return {
        "current_node": node.value,
        "completed_nodes": [node.value],
        "node_results": {node.value: record},
        "node_execution_attempts": [
            NodeAttempt(
                node=node.value,
                attempt=attempt_number,
                # Attempt timing: this pass only.
                started_at=started_at,
                completed_at=now,
                status=status,
                replayed=attempt_number > 1,
            )
        ],
        "run_updated_at": now,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def initialize_run(state: EvaluationGraphState) -> dict[str, Any]:
    """Stamp run identity and move the run into RUNNING.

    Idempotent: re-running keeps the existing thread_id rather than minting a
    new one, so a replay cannot orphan the checkpoint thread.
    """
    node = Phase1ANode.INITIALIZE_RUN
    started_at = workflow_now()
    thread_id = state.thread_id or new_thread_id(state.run_id)
    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["thread_id", "status"],
        summary="Evaluation run initialized.",
        metadata={"run_id": str(state.run_id)},
    )
    return {
        "thread_id": thread_id,
        "status": WorkflowStatus.RUNNING,
        "audit_events": [
            AuditEvent(
                run_id=state.run_id, node=node.value, event_type="RUN_INITIALIZED"
            )
        ],
        **_completion(state, node, result, started_at),
    }


def validate_project_state(state: EvaluationGraphState) -> dict[str, Any]:
    """Re-validate the canonical ProjectState before an important transition.

    Uses the Phase 0 contracts as-is. A validation failure is reported as a
    structured WorkflowError, never as a traceback in domain state.
    """
    node = Phase1ANode.VALIDATE_PROJECT_STATE
    started_at = workflow_now()
    try:
        validated = ProjectState.model_validate(state.project.model_dump())
    except ValueError as exc:
        error = WorkflowError(
            code=WorkflowErrorCode.STATE_VALIDATION_FAILED,
            node=node.value,
            message=f"canonical ProjectState is invalid: {str(exc).splitlines()[0]}",
            recoverable=False,
        )
        result = NodeResult(
            node=node.value,
            status=NodeStatus.FAILED,
            summary="ProjectState validation failed.",
            errors=[error],
        )
        return {
            "status": WorkflowStatus.FAILED,
            "errors": [error],
            **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
        }

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["project"],
        summary="Canonical ProjectState validated.",
        metadata={"claims": str(len(validated.claims))},
    )
    return {"project": validated, **_completion(state, node, result, started_at)}


def check_critical_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Evaluate the PHASE_1A_DEMO_GATE. Records the verdict; routing decides."""
    node = Phase1ANode.CHECK_CRITICAL_INPUT
    started_at = workflow_now()
    missing = demo_gate_missing_fields(state)
    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        summary=(
            "Demo gate satisfied."
            if not missing
            else f"Demo gate missing {len(missing)} field(s)."
        ),
        warnings=[f"missing: {path}" for path in missing],
        metadata={"missing_count": str(len(missing))},
    )
    return _completion(state, node, result, started_at)


def request_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Interrupt and wait for a human to supply the missing fields.

    ``interrupt()`` is the FIRST statement for a reason: LangGraph replays this
    node from the top on resume, so any side effect placed above it would happen
    twice. Everything after the interrupt runs only on the resuming pass.
    """
    node = Phase1ANode.REQUEST_INPUT
    # Captured before interrupt() on purpose. Reading the clock is not a side
    # effect, and on the resumed pass this line re-executes, so the recorded
    # attempt starts when the resume began -- the human pause is never included.
    started_at = workflow_now()
    missing = demo_gate_missing_fields(state)
    request = InterruptRequest(
        type=InterruptType.MISSING_CRITICAL_INFORMATION,
        node=node.value,
        fields=missing,
        message="Additional project information is required.",
        questions=[f"Provide a value for '{path}'." for path in missing],
    )

    answer = interrupt(request.to_payload())

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        summary="Human input received.",
        metadata={"requested_fields": str(len(missing))},
    )
    return {
        "interrupt_request": request,
        "pending_input": answer,
        "input_requests": state.input_requests + 1,
        "status": WorkflowStatus.RUNNING,
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="INPUT_REQUESTED",
                subject=",".join(missing),
            )
        ],
        **_completion(state, node, result, started_at),
    }


def apply_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Apply the human answer through the validated patch boundary.

    Never mutates nested domain objects directly: the answer becomes a
    ProjectPatch, which produces a new fully validated ProjectState.
    """
    node = Phase1ANode.APPLY_INPUT
    started_at = workflow_now()
    raw = state.pending_input
    if raw is None:
        error = WorkflowError(
            code=WorkflowErrorCode.INVALID_RESUME_INPUT,
            node=node.value,
            message="APPLY_INPUT reached without a resume payload",
        )
        result = NodeResult(
            node=node.value,
            status=NodeStatus.FAILED,
            summary="No resume payload available.",
            errors=[error],
        )
        return {
            "status": WorkflowStatus.FAILED,
            "errors": [error],
            **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
        }

    try:
        patch = ProjectPatch.from_raw(raw, node=node.value)
        updated = apply_project_patch(state.project, patch, node=node.value)
    except WorkflowErrorReport as report:
        result = NodeResult(
            node=node.value,
            status=NodeStatus.FAILED,
            summary="Resume input rejected.",
            errors=[report.error],
        )
        return {
            "status": WorkflowStatus.FAILED,
            "errors": [report.error],
            "pending_input": None,
            **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
        }

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=patch.field_paths,
        summary=f"Applied {len(patch.values)} human-supplied field(s).",
    )
    return {
        "project": updated,
        "pending_input": None,
        "interrupt_request": None,
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="INPUT_APPLIED",
                subject=",".join(patch.field_paths),
            )
        ],
        **_completion(state, node, result, started_at),
    }


def mark_ready(state: EvaluationGraphState) -> dict[str, Any]:
    """Terminal success: the harness completed without unmet requirements."""
    node = Phase1ANode.MARK_READY
    started_at = workflow_now()
    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["status"],
        summary="Phase 1A demo gate satisfied; run complete.",
    )
    return {
        "status": WorkflowStatus.COMPLETED,
        "interrupt_request": None,
        "audit_events": [
            AuditEvent(run_id=state.run_id, node=node.value, event_type="RUN_COMPLETED")
        ],
        **_completion(state, node, result, started_at),
    }


def mark_blocked(state: EvaluationGraphState) -> dict[str, Any]:
    """Terminal failure: input was requested, and the gate is still unmet.

    Recoverable, because a corrected input on a new run can clear it.
    """
    node = Phase1ANode.MARK_BLOCKED
    started_at = workflow_now()
    missing = demo_gate_missing_fields(state)
    error = WorkflowError(
        code=WorkflowErrorCode.CRITICAL_INPUT_STILL_MISSING,
        node=node.value,
        message=(
            "demo gate still unmet after the permitted input request: "
            f"{missing}"
        ),
        recoverable=True,
        metadata={"missing_count": str(len(missing))},
    )
    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["status"],
        summary="Run blocked on missing critical input.",
        warnings=[f"missing: {path}" for path in missing],
    )
    return {
        "status": WorkflowStatus.FAILED,
        "errors": [error],
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="RUN_BLOCKED",
                subject=",".join(missing),
            )
        ],
        **_completion(state, node, result, started_at),
    }


PHASE_1A_NODE_FUNCTIONS = {
    Phase1ANode.INITIALIZE_RUN: initialize_run,
    Phase1ANode.VALIDATE_PROJECT_STATE: validate_project_state,
    Phase1ANode.CHECK_CRITICAL_INPUT: check_critical_input,
    Phase1ANode.REQUEST_INPUT: request_input,
    Phase1ANode.APPLY_INPUT: apply_input,
    Phase1ANode.MARK_READY: mark_ready,
    Phase1ANode.MARK_BLOCKED: mark_blocked,
}
"""Registry binding each Phase 1A node id to its implementation."""
