"""Node execution contracts.

Every node, present and future, reports through the same shapes: what it was
given, what it produced, whether it succeeded, and what went wrong. These models
are deliberately domain-neutral -- nothing here knows about academic search,
novelty or scoring.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime, utc_now
from src.workflow.errors import WorkflowError


class WorkflowStatus(StrEnum):
    """Lifecycle of one evaluation run.

    Deliberately separate from EvaluationStatus: that enum describes how well
    evidence supports a judgement, this one describes whether the machine is
    still running. Overloading one for the other would conflate epistemics with
    execution.
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class NodeStatus(StrEnum):
    """Outcome of a single node execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    INTERRUPTED = "INTERRUPTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class InterruptType(StrEnum):
    """Why the graph stopped to ask a human (architecture section 25)."""

    MISSING_CRITICAL_INFORMATION = "MISSING_CRITICAL_INFORMATION"
    CONTRADICTORY_STUDENT_EVIDENCE = "CONTRADICTORY_STUDENT_EVIDENCE"
    AMBIGUOUS_PROJECT_INTERPRETATION = "AMBIGUOUS_PROJECT_INTERPRETATION"
    UNSAFE_OR_UNETHICAL_EXPERIMENT = "UNSAFE_OR_UNETHICAL_EXPERIMENT"
    HIGH_STAKES_FINALIZATION = "HIGH_STAKES_FINALIZATION"


class InterruptRequest(MawhibaModel):
    """The payload handed to the caller when the graph interrupts.

    Must stay JSON-serializable: it crosses the LangGraph checkpoint boundary
    and, eventually, an HTTP boundary. The message is the developer-facing
    English form; the student presentation layer adapts it later.
    """

    type: InterruptType
    node: str = Field(min_length=1)
    fields: list[str] = Field(
        default_factory=list,
        description="Dotted ProjectState paths the caller is expected to supply.",
    )
    message: str = Field(min_length=1)
    questions: list[str] = Field(
        default_factory=list,
        description="Optional developer-facing prompts, one per requested field.",
    )
    requested_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _missing_information_needs_fields(self) -> InterruptRequest:
        if self.type is InterruptType.MISSING_CRITICAL_INFORMATION and not self.fields:
            raise ValueError(
                "MISSING_CRITICAL_INFORMATION must name the fields it is waiting for"
            )
        return self

    def to_payload(self) -> dict[str, object]:
        """JSON-safe payload passed to LangGraph's interrupt()."""
        return self.model_dump(mode="json")


class NodeResult(MawhibaModel):
    """What a node reports about its own execution.

    ``state_changes`` is a summary of which state paths the node touched, not a
    copy of the data and never a dump of model reasoning.
    """

    node: str = Field(min_length=1)
    status: NodeStatus
    state_changes: list[str] = Field(
        default_factory=list,
        description="Dotted paths the node modified, for traceability.",
    )
    summary: str | None = Field(
        default=None, description="One-line developer-facing description."
    )
    warnings: list[str] = Field(default_factory=list)
    errors: list[WorkflowError] = Field(default_factory=list)
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Flat string metadata only. Never raw model reasoning.",
    )

    @model_validator(mode="after")
    def _failed_nodes_explain_themselves(self) -> NodeResult:
        if self.status is NodeStatus.FAILED and not self.errors:
            raise ValueError("a FAILED NodeResult must carry at least one error")
        return self


class NodeExecutionRecord(MawhibaModel):
    """The lifecycle record of a node, keyed by node id in graph state.

    A node that replays after an interrupt overwrites its own record rather than
    appending a second one.

    TIMING SEMANTICS -- read this before using the timestamps.

    ``first_started_at`` and ``last_completed_at`` describe the node's *lifecycle*.
    For a replayed node that lifecycle spans the human pause between the interrupt
    and the resume, so their difference is elapsed wall time, NOT compute latency.
    This model therefore exposes no ``duration_ms`` derived from them: publishing
    that number would invite it being read as node performance.

    For any performance measurement use ``NodeAttempt.duration_ms``, which is
    computed from a single attempt and never spans a pause.
    """

    node: str = Field(min_length=1)
    first_started_at: UtcDatetime = Field(
        default_factory=utc_now,
        description="When the node was first entered. Lifecycle only, not latency.",
    )
    last_completed_at: UtcDatetime | None = Field(
        default=None,
        description="When the most recent attempt finished. Lifecycle only.",
    )
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = Field(default=1, ge=1)
    result: NodeResult | None = None

    @model_validator(mode="after")
    def _terminal_status_is_timed(self) -> NodeExecutionRecord:
        terminal = {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED}
        if self.status in terminal and self.last_completed_at is None:
            raise ValueError(f"status={self.status.value} requires last_completed_at")
        if (
            self.last_completed_at is not None
            and self.last_completed_at < self.first_started_at
        ):
            raise ValueError("last_completed_at cannot precede first_started_at")
        if self.result is not None and self.result.node != self.node:
            raise ValueError("result.node must match the record's node")
        return self

    @property
    def is_complete(self) -> bool:
        return self.status is NodeStatus.SUCCEEDED

    @property
    def lifecycle_elapsed_ms(self) -> float | None:
        """Wall time from first entry to last completion.

        Named ``lifecycle_`` because for a replayed node it includes the human
        pause. Never report it as node or model latency.
        """
        if self.last_completed_at is None:
            return None
        return (self.last_completed_at - self.first_started_at).total_seconds() * 1000.0


class NodeAttempt(MawhibaModel):
    """One individual execution of a node, with its own independent timing.

    LangGraph re-executes an interrupted node from its first line on resume, so a
    node can be entered more than once. Each entry is its own attempt with its own
    identity and its own ``started_at`` -- a replay never inherits the first
    attempt's timestamp, which is what keeps a human pause out of the measurement.

    ``duration_ms`` is computed from this attempt alone and is the only timing
    value in the system suitable for performance measurement.
    """

    attempt_id: UUID = Field(default_factory=uuid4)
    node: str = Field(min_length=1)
    attempt: int = Field(ge=1, description="1-based index of this entry.")
    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None
    status: NodeStatus = NodeStatus.RUNNING
    replayed: bool = Field(
        default=False, description="True when this entry followed a resume."
    )

    @model_validator(mode="after")
    def _timing_is_coherent(self) -> NodeAttempt:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        terminal = {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED}
        if self.status in terminal and self.completed_at is None:
            raise ValueError(f"status={self.status.value} requires completed_at")
        if self.attempt > 1 and not self.replayed:
            raise ValueError("an attempt after the first must be marked replayed")
        return self

    @property
    def duration_ms(self) -> float | None:
        """Compute time of this attempt alone. Never spans an interrupt pause."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds() * 1000.0


class AuditEvent(MawhibaModel):
    """An append-only workflow event, de-duplicated by ``event_key``.

    Node replay must not produce a second copy of the same event, so the key is
    derived deterministically from the run, node and subject rather than from a
    timestamp or a counter.
    """

    run_id: UUID
    node: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    subject: str = Field(
        default="", description="What the event is about, e.g. a field path."
    )
    recorded_at: UtcDatetime = Field(default_factory=utc_now)

    @property
    def event_key(self) -> str:
        return f"{self.run_id}:{self.node}:{self.event_type}:{self.subject}"
