"""EvaluationGraphState -- the LangGraph channel state.

The canonical domain model stays ``ProjectState`` (src/graph/state.py). This
model carries it through the graph together with execution bookkeeping. It
deliberately does not copy ProjectState fields: there is exactly one canonical
project state, and it lives at ``EvaluationGraphState.project``.

Channel reducers here are what make node replay after an interrupt safe. A node
that re-runs re-emits the same updates, and the reducers absorb the repetition.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import Field

from src.graph.contracts import (
    AuditEvent,
    InterruptRequest,
    NodeAttempt,
    NodeExecutionRecord,
    WorkflowStatus,
)
from src.graph.state import ProjectState
from src.schemas.common import MawhibaModel, UtcDatetime, utc_now
from src.schemas.extraction import (
    ProjectExtraction,
    VerifiedClassification,
    VerifiedExtraction,
)
from src.schemas.submission import StudentSubmissionArtifact
from src.workflow.errors import WorkflowError

THREAD_ID_PREFIX = "thr"


def new_thread_id(run_id: UUID | None = None) -> str:
    """Build an opaque LangGraph thread id.

    Derived from a UUID so it carries no student name, project title, email or
    any other PII. Stable for a given run_id, which keeps resume deterministic.
    """
    return f"{THREAD_ID_PREFIX}-{run_id or uuid4()}"


def is_safe_thread_id(thread_id: str) -> bool:
    """True when the id matches the opaque UUID-derived format."""
    if not thread_id.startswith(f"{THREAD_ID_PREFIX}-"):
        return False
    try:
        UUID(thread_id.removeprefix(f"{THREAD_ID_PREFIX}-"))
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Channel reducers -- all replay-safe
# ---------------------------------------------------------------------------

def merge_unique_ordered(left: list[str], right: list[str]) -> list[str]:
    """Append new entries, preserving order, never duplicating.

    Used for completed_nodes: a node that replays after an interrupt appears
    once, in its original position.
    """
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


def merge_node_records(
    left: dict[str, NodeExecutionRecord], right: dict[str, NodeExecutionRecord]
) -> dict[str, NodeExecutionRecord]:
    """Merge execution records by node id.

    A replaying node overwrites its own record instead of creating a second one.
    """
    merged = dict(left)
    merged.update(right)
    return merged


def append_attempts(
    left: list[NodeAttempt], right: list[NodeAttempt]
) -> list[NodeAttempt]:
    """Append attempt entries verbatim.

    Replays are appended on purpose: a second entry here is the truthful record
    that the node ran twice. Completion tracking stays clean because it uses a
    different channel.
    """
    return [*left, *right]


def merge_unique_errors(
    left: list[WorkflowError], right: list[WorkflowError]
) -> list[WorkflowError]:
    """Append errors, collapsing exact repeats produced by a replay."""
    merged = list(left)
    seen = {error.error_key for error in merged}
    for error in right:
        if error.error_key not in seen:
            merged.append(error)
            seen.add(error.error_key)
    return merged


def merge_unique_events(
    left: list[AuditEvent], right: list[AuditEvent]
) -> list[AuditEvent]:
    """Append audit events, collapsing repeats by deterministic event_key.

    This is the guard against the classic interrupt hazard: a node emitting an
    audit event, interrupting, then re-emitting the same event on resume.
    """
    merged = list(left)
    seen = {event.event_key for event in merged}
    for event in right:
        if event.event_key not in seen:
            merged.append(event)
            seen.add(event.event_key)
    return merged


# ---------------------------------------------------------------------------
# The state
# ---------------------------------------------------------------------------

class EvaluationGraphState(MawhibaModel):
    """LangGraph channel state for one evaluation run.

    ``run_id`` identifies one execution of the evaluation. ``thread_id`` is the
    LangGraph checkpoint cursor that a resume attaches to. They are not
    interchangeable: one thread can, over time, carry more than one run, and a
    run is always pinned to exactly one thread.
    """

    project: ProjectState = Field(
        default_factory=ProjectState,
        description="The single canonical domain state. Never duplicated here.",
    )

    run_id: UUID = Field(default_factory=uuid4)
    thread_id: str = Field(default="", description="Opaque UUID-derived cursor.")

    status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    current_node: str | None = None

    completed_nodes: Annotated[list[str], merge_unique_ordered] = Field(
        default_factory=list,
        description="Ordered, duplicate-safe. Replay never adds a second entry.",
    )
    pending_nodes: list[str] = Field(default_factory=list)

    node_results: Annotated[dict[str, NodeExecutionRecord], merge_node_records] = Field(
        default_factory=dict
    )
    node_execution_attempts: Annotated[list[NodeAttempt], append_attempts] = Field(
        default_factory=list,
        description="Every entry including replays. Separate from completed_nodes.",
    )

    # -- Phase 1B intake channels --------------------------------------------
    submission: StudentSubmissionArtifact | None = Field(
        default=None,
        description="The student's submission, preserved verbatim. Ground truth "
        "for every provenance check.",
    )
    candidate_extraction: ProjectExtraction | None = Field(
        default=None,
        description="Raw model output. UNTRUSTED -- never merged directly.",
    )
    verified_extraction: VerifiedExtraction | None = Field(
        default=None,
        description="Deterministic verdict on the candidate. The only thing the "
        "merge layer accepts.",
    )
    verified_classification: VerifiedClassification | None = Field(
        default=None,
        description="Anchor-verified project type and technical domains.",
    )

    interrupt_request: InterruptRequest | None = None
    pending_input: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Raw, still-unvalidated human answer captured by the resume. Cleared "
            "by APPLY_INPUT once it has passed the patch boundary."
        ),
    )
    input_requests: int = Field(
        default=0,
        ge=0,
        description="How many times the graph asked for input. Bounds the cycle.",
    )

    errors: Annotated[list[WorkflowError], merge_unique_errors] = Field(
        default_factory=list
    )
    audit_events: Annotated[list[AuditEvent], merge_unique_events] = Field(
        default_factory=list
    )

    run_started_at: UtcDatetime = Field(default_factory=utc_now)
    run_updated_at: UtcDatetime = Field(
        default_factory=utc_now,
        description=(
            "Run-level clock. Named distinctly from ProjectState.updated_at so "
            "the two are never confused at a call site."
        ),
    )

    # -- read helpers ---------------------------------------------------------

    def attempts_for(self, node: str) -> int:
        return sum(1 for attempt in self.node_execution_attempts if attempt.node == node)

    def has_completed(self, node: str) -> bool:
        return node in self.completed_nodes

    def record_for(self, node: str) -> NodeExecutionRecord | None:
        return self.node_results.get(node)

    @property
    def is_terminal(self) -> bool:
        return self.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED)


def coerce_graph_state(values: EvaluationGraphState | dict[str, object]) -> EvaluationGraphState:
    """Normalize a LangGraph result or checkpoint snapshot into the model.

    ``invoke`` and ``get_state`` return plain dictionaries of channel values; this
    is the single place that converts them back, so no caller hand-rolls it.
    The ``__interrupt__`` channel LangGraph adds to a result is not part of the
    state schema and is dropped here.
    """
    if isinstance(values, EvaluationGraphState):
        return values
    payload = {
        key: value
        for key, value in values.items()
        if key in EvaluationGraphState.model_fields
    }
    return EvaluationGraphState.model_validate(payload)
