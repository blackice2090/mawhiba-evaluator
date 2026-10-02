"""Model-call contracts.

Raw SDK objects never reach domain logic. Everything a provider returns is
wrapped in ``ModelCallResult``, which distinguishes success from the several
distinct ways a structured call can fail -- because "refused", "truncated" and
"the network broke" need different handling, and collapsing them into one
exception would hide that.

Nothing here stores hidden reasoning or raw model traces.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.common import UtcDatetime, utc_now

T = TypeVar("T", bound=BaseModel)


class ModelTask(StrEnum):
    """What a call is for. Drives model selection and observability."""

    PROJECT_EXTRACTION = "PROJECT_EXTRACTION"
    PROJECT_CLASSIFICATION = "PROJECT_CLASSIFICATION"
    RESEARCH_QUERY_PLANNING = "RESEARCH_QUERY_PLANNING"
    OFFICIAL_REQUIREMENTS_EXTRACTION = "OFFICIAL_REQUIREMENTS_EXTRACTION"
    EVIDENCE_EXTRACTION = "EVIDENCE_EXTRACTION"
    CLAIM_EVIDENCE_ALIGNMENT = "CLAIM_EVIDENCE_ALIGNMENT"
    NOVELTY_FEATURE_EXTRACTION = "NOVELTY_FEATURE_EXTRACTION"
    PRIOR_ART_TECHNICAL_COMPARISON = "PRIOR_ART_TECHNICAL_COMPARISON"


class ModelCallStatus(StrEnum):
    """Outcome of one structured model call.

    These are execution outcomes, not statements about the project. A REFUSAL is
    emphatically not "the project information is unknown" -- it means the call
    did not happen successfully and must be visible as such.
    """

    SUCCESS = "SUCCESS"
    REFUSAL = "REFUSAL"
    PARSE_ERROR = "PARSE_ERROR"
    INCOMPLETE_OUTPUT = "INCOMPLETE_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"


RETRYABLE_STATUSES: frozenset[ModelCallStatus] = frozenset(
    {
        ModelCallStatus.PROVIDER_ERROR,
        ModelCallStatus.INCOMPLETE_OUTPUT,
        ModelCallStatus.EMPTY_OUTPUT,
    }
)
"""Statuses worth retrying.

A REFUSAL is a deliberate model decision and retrying it is both futile and
costly. A PARSE_ERROR means the schema contract is wrong, which a retry cannot
fix either.
"""


class ModelUsage(BaseModel):
    """Token accounting, when the provider reports it."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelCallResult(BaseModel, Generic[T]):
    """The single shape every provider returns.

    Generic over the parsed schema so callers get typed output without touching
    the SDK.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: ModelCallStatus
    parsed: T | None = None
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    task: ModelTask
    request_id: str | None = None
    refusal: str | None = Field(
        default=None, description="The model's refusal text, when it refused."
    )
    error: str | None = Field(
        default=None,
        description="Developer-facing English error summary. Never a traceback.",
    )
    usage: ModelUsage | None = None
    attempts: int = Field(default=1, ge=1)
    latency_ms: float | None = Field(default=None, ge=0.0)
    called_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _status_matches_payload(self) -> ModelCallResult[T]:
        if self.status is ModelCallStatus.SUCCESS and self.parsed is None:
            raise ValueError("SUCCESS requires a parsed payload")
        if self.status is not ModelCallStatus.SUCCESS and self.parsed is not None:
            raise ValueError(f"status={self.status.value} must not carry parsed output")
        if self.status is ModelCallStatus.REFUSAL and not self.refusal:
            raise ValueError("REFUSAL requires the refusal text")
        if (
            self.status
            in (
                ModelCallStatus.PROVIDER_ERROR,
                ModelCallStatus.PARSE_ERROR,
                ModelCallStatus.INCOMPLETE_OUTPUT,
                ModelCallStatus.EMPTY_OUTPUT,
            )
            and not self.error
        ):
            raise ValueError(f"status={self.status.value} requires an error summary")
        return self

    @property
    def succeeded(self) -> bool:
        return self.status is ModelCallStatus.SUCCESS

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_STATUSES

    def log_fields(self) -> dict[str, str]:
        """Safe-to-log summary.

        Deliberately excludes the prompt, the student's submission and the
        parsed content -- observability must not become a data leak.
        """
        fields = {
            "task": self.task.value,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "attempts": str(self.attempts),
        }
        if self.request_id:
            fields["request_id"] = self.request_id
        if self.latency_ms is not None:
            fields["latency_ms"] = f"{self.latency_ms:.1f}"
        if self.usage and self.usage.total_tokens is not None:
            fields["total_tokens"] = str(self.usage.total_tokens)
        return fields
