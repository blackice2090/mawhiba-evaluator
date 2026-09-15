"""Deterministic routing for the Phase 1A harness graph.

The completeness rule here is a demonstration gate, not the project's intake
policy. It exists to exercise conditional routing and the interrupt path with a
rule that depends only on Phase 0 contracts.
"""

from __future__ import annotations

from langgraph.graph import END

from src.graph.contracts import WorkflowStatus
from src.graph.registry import Phase1ANode
from src.graph.workflow_state import EvaluationGraphState
from src.workflow.patches import PatchableField, missing_patchable_fields

PHASE_1A_DEMO_GATE: tuple[PatchableField, ...] = (
    PatchableField.PROJECT_NAME,
    PatchableField.PROBLEM_STATEMENT,
    PatchableField.SOLUTION_DESCRIPTION,
)
"""PHASE_1A_DEMO_GATE -- infrastructure demonstration only.

This is NOT the final project-intake completeness policy. The real policy is
decided by N00/N01 and by section 24 (ask only when MISSING + CRITICAL +
NOT_RETRIEVABLE_EXTERNALLY), and arrives in a later phase. Three fields were
chosen because they already exist as Tracked values in Phase 0 and need no new
contract.
"""

MAX_INPUT_REQUESTS = 1
"""How many times the harness graph will ask for input before giving up.

Bounds the APPLY_INPUT -> VALIDATE -> CHECK cycle so an unhelpful answer cannot
loop forever.
"""


def demo_gate_missing_fields(state: EvaluationGraphState) -> list[str]:
    """Dotted paths the demo gate still considers missing."""
    return [
        field.value
        for field in missing_patchable_fields(state.project, PHASE_1A_DEMO_GATE)
    ]


def route_after_validation(state: EvaluationGraphState) -> str:
    """Branch: stop on a failed validation, otherwise continue to the gate."""
    if state.status is WorkflowStatus.FAILED:
        return END
    return Phase1ANode.CHECK_CRITICAL_INPUT.value


def route_after_apply_input(state: EvaluationGraphState) -> str:
    """Branch: a rejected resume payload ends the run, otherwise re-validate."""
    if state.status is WorkflowStatus.FAILED:
        return END
    return Phase1ANode.VALIDATE_PROJECT_STATE.value


def route_after_critical_check(state: EvaluationGraphState) -> str:
    """Branch: enough information, ask the human, or stop asking.

    Pure function of the state, so routing is replayable and testable without
    running the graph.
    """
    if not demo_gate_missing_fields(state):
        return Phase1ANode.MARK_READY.value
    if state.input_requests >= MAX_INPUT_REQUESTS:
        return Phase1ANode.MARK_BLOCKED.value
    return Phase1ANode.REQUEST_INPUT.value


__all__ = [
    "MAX_INPUT_REQUESTS",
    "PHASE_1A_DEMO_GATE",
    "demo_gate_missing_fields",
    "route_after_apply_input",
    "route_after_critical_check",
    "route_after_validation",
]
