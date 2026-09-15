"""OpenAI Responses API provider.

Uses ``client.responses.parse(..., text_format=Model)`` -- Structured Outputs
with a Pydantic schema. The model is never asked for free-form JSON, and no
regex ever touches its output: a shape the schema rejects is a PARSE_ERROR, not
something to be salvaged by string surgery.

Credentials come from the SDK's own environment handling. Nothing here reads,
stores or logs an API key.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.llm.contracts import (
    ModelCallResult,
    ModelCallStatus,
    ModelTask,
    ModelUsage,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

INCOMPLETE_STATUSES = frozenset({"incomplete", "failed", "cancelled"})


class OpenAIResponsesProvider:
    """Structured-output provider backed by the OpenAI Responses API."""

    name = "openai_responses"

    def __init__(self, client: Any | None = None) -> None:
        """Build the provider.

        The client is created lazily so that importing this module -- and
        therefore the whole package -- never requires an API key. A test that
        merely imports intake code must not fail because no credential is set.
        """
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def parse(
        self,
        *,
        task: ModelTask,
        system_prompt: str,
        user_input: str,
        response_model: type[T],
        model: str,
    ) -> ModelCallResult[T]:
        """One structured call. Never raises for a model-level outcome."""
        started = time.perf_counter()

        def elapsed_ms() -> float:
            return (time.perf_counter() - started) * 1000.0

        def failure(status: ModelCallStatus, error: str) -> ModelCallResult[T]:
            return ModelCallResult[response_model](
                status=status,
                model=model,
                provider=self.name,
                task=task,
                error=error,
                latency_ms=elapsed_ms(),
            )

        try:
            response = self.client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    # The student's text is data. The system prompt states that
                    # instructions inside it are content, not commands.
                    {"role": "user", "content": user_input},
                ],
                text_format=response_model,
            )
        except Exception as exc:  # noqa: BLE001 -- every provider fault is a status
            return failure(
                ModelCallStatus.PROVIDER_ERROR,
                f"{type(exc).__name__}: {_first_line(exc)}",
            )

        request_id = getattr(response, "id", None)
        usage = _extract_usage(response)
        status_text = getattr(response, "status", None)

        refusal = _find_refusal(response)
        if refusal:
            return ModelCallResult[response_model](
                status=ModelCallStatus.REFUSAL,
                model=model,
                provider=self.name,
                task=task,
                request_id=request_id,
                refusal=refusal,
                usage=usage,
                latency_ms=elapsed_ms(),
            )

        if status_text in INCOMPLETE_STATUSES:
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            return ModelCallResult[response_model](
                status=ModelCallStatus.INCOMPLETE_OUTPUT,
                model=model,
                provider=self.name,
                task=task,
                request_id=request_id,
                usage=usage,
                error=f"response status={status_text}, reason={reason or 'unspecified'}",
                latency_ms=elapsed_ms(),
            )

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            return ModelCallResult[response_model](
                status=ModelCallStatus.EMPTY_OUTPUT,
                model=model,
                provider=self.name,
                task=task,
                request_id=request_id,
                usage=usage,
                error="provider returned no parsed output",
                latency_ms=elapsed_ms(),
            )

        if not isinstance(parsed, response_model):
            try:
                parsed = response_model.model_validate(parsed)
            except ValidationError as exc:
                return ModelCallResult[response_model](
                    status=ModelCallStatus.PARSE_ERROR,
                    model=model,
                    provider=self.name,
                    task=task,
                    request_id=request_id,
                    usage=usage,
                    error=f"parsed output failed schema validation: {_first_line(exc)}",
                    latency_ms=elapsed_ms(),
                )

        result = ModelCallResult[response_model](
            status=ModelCallStatus.SUCCESS,
            parsed=parsed,
            model=model,
            provider=self.name,
            task=task,
            request_id=request_id,
            usage=usage,
            latency_ms=elapsed_ms(),
        )
        logger.debug("structured model call: %s", result.log_fields())
        return result


def _first_line(exc: Exception) -> str:
    """One line of an exception message. Never a traceback into domain state."""
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _extract_usage(response: Any) -> ModelUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return ModelUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


def _find_refusal(response: Any) -> str | None:
    """Locate a refusal in the Responses output structure, if present."""
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            refusal = getattr(content, "refusal", None)
            if refusal:
                return str(refusal)
    return None
