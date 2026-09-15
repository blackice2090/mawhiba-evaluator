"""Structured workflow errors.

An error is domain state, not a string. Python tracebacks belong in developer
logs and test output, never in ProjectState or in a checkpoint payload.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from src.schemas.common import MawhibaModel, UtcDatetime, utc_now


class WorkflowErrorCode(StrEnum):
    """Closed set of workflow-level failure codes.

    These describe infrastructure failures, not evaluation findings. Evaluation
    problems are FindingRecord / TrustBlocker, which live in the domain layer.
    """

    STATE_VALIDATION_FAILED = "STATE_VALIDATION_FAILED"
    INVALID_RESUME_INPUT = "INVALID_RESUME_INPUT"
    CRITICAL_INPUT_STILL_MISSING = "CRITICAL_INPUT_STILL_MISSING"
    NODE_EXECUTION_FAILED = "NODE_EXECUTION_FAILED"
    UNSUPPORTED_PATCH_FIELD = "UNSUPPORTED_PATCH_FIELD"
    CHECKPOINTER_UNAVAILABLE = "CHECKPOINTER_UNAVAILABLE"
    ROUTING_FAILED = "ROUTING_FAILED"

    # Phase 1B -- intake and model execution outcomes.
    NO_SUBMISSION = "NO_SUBMISSION"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    MODEL_REFUSAL = "MODEL_REFUSAL"


class WorkflowError(MawhibaModel):
    """One structured workflow failure."""

    code: WorkflowErrorCode
    node: str = Field(min_length=1)
    message: str = Field(
        min_length=1,
        description="Developer-facing English message. Never a raw traceback.",
    )
    recoverable: bool = Field(
        default=True,
        description="True when a resume or a corrected input can clear this error.",
    )
    occurred_at: UtcDatetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Flat string metadata only, so the error stays serializable.",
    )

    @property
    def error_key(self) -> str:
        """Stable identity used to de-duplicate errors across node replays."""
        return f"{self.node}:{self.code.value}:{self.message}"


class WorkflowErrorReport(Exception):
    """Raised when workflow infrastructure cannot continue.

    Carries a WorkflowError so the caller receives structured data rather than
    having to parse an exception string.
    """

    def __init__(self, error: WorkflowError) -> None:
        super().__init__(f"[{error.code.value}] {error.node}: {error.message}")
        self.error = error
