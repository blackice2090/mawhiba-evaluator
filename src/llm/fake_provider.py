"""Deterministic provider for tests.

Every trust rule in Phase 1B is exercised through this: hallucinated values,
refusals, truncation, retry exhaustion. Scripting the model's output is the only
way to test "what happens when the model lies" reliably.

It also guarantees the unit suite makes no network call -- there is no client
here to make one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from src.llm.contracts import (
    ModelCallResult,
    ModelCallStatus,
    ModelTask,
    ModelUsage,
)

T = TypeVar("T", bound=BaseModel)

ResponseFactory = Callable[[ModelTask, str], "ModelCallResult"]


class FakeStructuredModelProvider:
    """Returns scripted results and records what it was asked.

    Construct with either a single response, a queue of responses consumed in
    order, or a callable for input-dependent behaviour.
    """

    name = "fake"

    def __init__(
        self,
        response: BaseModel | None = None,
        *,
        responses: Sequence[BaseModel | ModelCallResult] | None = None,
        result: ModelCallResult | None = None,
        results: Sequence[ModelCallResult] | None = None,
        factory: ResponseFactory | None = None,
    ) -> None:
        self._single = response
        self._queue: list[BaseModel | ModelCallResult] = list(
            responses or results or ([result] if result is not None else [])
        )
        self._factory = factory
        self.calls: list[dict[str, object]] = []

    # -- inspection helpers ---------------------------------------------------

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def last_system_prompt(self) -> str:
        return str(self.calls[-1]["system_prompt"])

    def last_user_input(self) -> str:
        return str(self.calls[-1]["user_input"])

    def calls_for(self, task: ModelTask) -> list[dict[str, object]]:
        return [call for call in self.calls if call["task"] is task]

    # -- provider protocol ----------------------------------------------------

    def parse(
        self,
        *,
        task: ModelTask,
        system_prompt: str,
        user_input: str,
        response_model: type[T],
        model: str,
    ) -> ModelCallResult[T]:
        self.calls.append(
            {
                "task": task,
                "system_prompt": system_prompt,
                "user_input": user_input,
                "response_model": response_model,
                "model": model,
            }
        )

        if self._factory is not None:
            return self._factory(task, user_input)

        if self._queue:
            nxt = self._queue.pop(0)
        elif self._single is not None:
            nxt = self._single
        else:
            return ModelCallResult[response_model](
                status=ModelCallStatus.EMPTY_OUTPUT,
                model=model,
                provider=self.name,
                task=task,
                error="fake provider has no scripted response left",
            )

        if isinstance(nxt, ModelCallResult):
            return nxt

        return ModelCallResult[response_model](
            status=ModelCallStatus.SUCCESS,
            parsed=nxt,
            model=model,
            provider=self.name,
            task=task,
            request_id="fake-request",
            usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )


# ---------------------------------------------------------------------------
# Failure helpers -- readable one-liners for provider-failure tests
# ---------------------------------------------------------------------------


def refusal_result(
    task: ModelTask, message: str = "I cannot help with that request."
) -> ModelCallResult:
    return ModelCallResult(
        status=ModelCallStatus.REFUSAL,
        model="fake-model",
        provider="fake",
        task=task,
        refusal=message,
    )


def provider_error_result(
    task: ModelTask, message: str = "APIConnectionError: connection reset"
) -> ModelCallResult:
    return ModelCallResult(
        status=ModelCallStatus.PROVIDER_ERROR,
        model="fake-model",
        provider="fake",
        task=task,
        error=message,
    )


def incomplete_result(task: ModelTask) -> ModelCallResult:
    return ModelCallResult(
        status=ModelCallStatus.INCOMPLETE_OUTPUT,
        model="fake-model",
        provider="fake",
        task=task,
        error="response status=incomplete, reason=max_output_tokens",
    )


def parse_error_result(task: ModelTask) -> ModelCallResult:
    return ModelCallResult(
        status=ModelCallStatus.PARSE_ERROR,
        model="fake-model",
        provider="fake",
        task=task,
        error="parsed output failed schema validation",
    )


def empty_result(task: ModelTask) -> ModelCallResult:
    return ModelCallResult(
        status=ModelCallStatus.EMPTY_OUTPUT,
        model="fake-model",
        provider="fake",
        task=task,
        error="provider returned no parsed output",
    )
