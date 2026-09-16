"""Shared structured-model invocation with a bounded retry policy.

Every layer that calls a model -- intake, research, and whatever follows --
invokes it through this one function. The retry policy is a property of the LLM
layer, not of any caller, so no caller reimplements it and no caller depends on
another caller's internals.

Retried: transient transport faults and truncation.
Never retried: a refusal (a deliberate model decision; repeating it burns money
and changes nothing) and a parse error (the schema contract is wrong, and no
number of attempts makes a bad schema valid).
"""

from __future__ import annotations

import logging

from src.llm.contracts import ModelCallResult, ModelTask
from src.llm.provider import StructuredModelProvider

logger = logging.getLogger(__name__)


def call_structured_model_with_retries(
    provider: StructuredModelProvider,
    *,
    task: ModelTask,
    system_prompt: str,
    user_input: str,
    response_model: type,
    model: str,
    max_retries: int,
) -> ModelCallResult:
    """Call the provider, retrying only what a retry can plausibly fix.

    Returns the last ``ModelCallResult`` with ``attempts`` set to the number of
    calls made. Never raises for a model-level outcome.
    """
    attempt = 0
    result: ModelCallResult | None = None

    while attempt <= max_retries:
        attempt += 1
        result = provider.parse(
            task=task,
            system_prompt=system_prompt,
            user_input=user_input,
            response_model=response_model,
            model=model,
        )
        result = result.model_copy(update={"attempts": attempt})

        if result.succeeded or not result.retryable:
            break

    assert result is not None  # the loop always runs at least once
    logger.debug("structured model call: %s", result.log_fields())
    return result


__all__ = ["call_structured_model_with_retries"]
