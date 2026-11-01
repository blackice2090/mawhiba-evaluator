"""The single, bounded model-call path for Phase 3B.

``ExperimentReviewBounds.max_model_calls`` is a hard bound on provider requests,
retries included: a call is made only while budget remains, and its retry limit
is cut to the remaining budget, so no retry loop can cross the bound. Each
failure is mapped to its own run-issue code: a missing provider, an exhausted
bound, a refusal, an invalid response and a partial response are never collapsed
into one message (ADR-023 section 5). A provider's own text is never returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallStatus, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.provider import StructuredModelProvider
from src.schemas.experiment_review import ExperimentReviewBounds, ExperimentRunIssueCode

_C = ExperimentRunIssueCode
_FAILURE_CODE: dict[ModelCallStatus, ExperimentRunIssueCode] = {
    ModelCallStatus.REFUSAL: _C.MODEL_REFUSED,
    ModelCallStatus.PARSE_ERROR: _C.MODEL_RESPONSE_INVALID,
    ModelCallStatus.INCOMPLETE_OUTPUT: _C.PARTIAL_MODEL_OUTPUT,
    ModelCallStatus.PROVIDER_ERROR: _C.MODEL_RESPONSE_INVALID,
    ModelCallStatus.EMPTY_OUTPUT: _C.MODEL_RESPONSE_INVALID,
}


@dataclass
class CallOutcome:
    parsed: Any = None
    attempts: int = 0
    failure: ExperimentRunIssueCode | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None and self.parsed is not None


def call_model(
    provider: StructuredModelProvider | None, *, task: ModelTask, prompt: str, user_input: str, response_model: type,
    llm_settings: LLMSettings | None, bounds: ExperimentReviewBounds, performed: int,
) -> CallOutcome:
    """One logical call. ``performed`` is the run's provider-request count so far."""
    if provider is None:
        return CallOutcome(failure=_C.MODEL_PROVIDER_MISSING)
    remaining = bounds.max_model_calls - performed
    if remaining < 1:
        return CallOutcome(failure=_C.MODEL_CALL_BOUND_REACHED)
    result = call_structured_model_with_retries(
        provider, task=task, system_prompt=prompt, user_input=user_input, response_model=response_model,
        model=(llm_settings or LLMSettings()).extraction_model,
        max_retries=min(bounds.model_retry_limit, remaining - 1))
    attempts = max(1, result.attempts or 1)
    if result.succeeded and isinstance(result.parsed, response_model):
        return CallOutcome(parsed=result.parsed, attempts=attempts)
    return CallOutcome(attempts=attempts, failure=_FAILURE_CODE.get(result.status, _C.MODEL_RESPONSE_INVALID))


FAILURE_MESSAGES: dict[ExperimentRunIssueCode, str] = {
    _C.MODEL_PROVIDER_MISSING: "no structured model provider",
    _C.MODEL_CALL_BOUND_REACHED: "run-wide model call bound reached",
    _C.MODEL_REFUSED: "the model refused the request",
    _C.MODEL_RESPONSE_INVALID: "the model response was not a valid structured response",
    _C.PARTIAL_MODEL_OUTPUT: "the model response was incomplete",
}


__all__ = ["FAILURE_MESSAGES", "CallOutcome", "call_model"]
