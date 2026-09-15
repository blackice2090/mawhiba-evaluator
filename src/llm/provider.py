"""The provider seam.

Extraction logic depends on this Protocol, never on the OpenAI SDK. That is what
lets the entire trust layer be tested deterministically with no key and no
network, and what will let a second provider be added without touching intake.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from src.llm.contracts import ModelCallResult, ModelTask

T = TypeVar("T", bound=BaseModel)


class StructuredModelProvider(Protocol):
    """Anything that can turn a prompt into a validated Pydantic object.

    Implementations must never raise for a model-level outcome: a refusal, a
    truncation or a transport failure all come back as a ``ModelCallResult`` with
    the corresponding status, so the workflow can record the outcome rather than
    unwinding through an exception.
    """

    name: str

    def parse(
        self,
        *,
        task: ModelTask,
        system_prompt: str,
        user_input: str,
        response_model: type[T],
        model: str,
    ) -> ModelCallResult[T]: ...
