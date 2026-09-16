"""The shared structured-model invocation layer.

Retry, refusal and truncation behaviour live in one place, and both intake and
research use that one place -- research must not depend on an intake private.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.config.settings import LLMSettings
from src.intake import extractor
from src.llm import invocation
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.llm.invocation import call_structured_model_with_retries
from src.research import planner
from src.research.official import extraction
from src.schemas.extraction import ProjectExtraction

ROOT = Path(__file__).resolve().parents[1]
TASK = ModelTask.RESEARCH_QUERY_PLANNING


def _call(provider: FakeStructuredModelProvider, max_retries: int = 2) -> ModelCallResult:
    return call_structured_model_with_retries(
        provider,
        task=TASK,
        system_prompt="system",
        user_input="input",
        response_model=ProjectExtraction,
        model="fake-model",
        max_retries=max_retries,
    )


# --- shared, public, one implementation ---------------------------------------------


def test_the_helper_is_public() -> None:
    assert hasattr(invocation, "call_structured_model_with_retries")
    assert invocation.call_structured_model_with_retries.__name__ == "call_structured_model_with_retries"


def test_intake_and_research_share_one_retry_implementation() -> None:
    shared = invocation.call_structured_model_with_retries
    assert extractor.call_structured_model_with_retries is shared
    assert planner.call_structured_model_with_retries is shared
    assert extraction.call_structured_model_with_retries is shared


def test_no_private_retry_helper_remains_anywhere() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        assert "_call_with_retries" not in path.read_text(encoding="utf-8"), path


def test_research_does_not_import_from_intake_extractor() -> None:
    """Dependency direction: research depends on the LLM layer, never on intake internals."""
    for path in (ROOT / "src" / "research").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "src.intake.extractor", path


def test_only_one_module_implements_the_retry_loop() -> None:
    implementations = [
        path
        for path in (ROOT / "src").rglob("*.py")
        if "while attempt <= max_retries" in path.read_text(encoding="utf-8")
    ]
    assert implementations == [ROOT / "src" / "llm" / "invocation.py"]


# --- preserved semantics -------------------------------------------------------------


def test_success_on_the_first_attempt_is_not_retried() -> None:
    provider = FakeStructuredModelProvider(response=ProjectExtraction())
    result = _call(provider)
    assert result.succeeded and result.attempts == 1 and provider.call_count == 1


@pytest.mark.parametrize(
    "builder", [provider_error_result, incomplete_result, empty_result]
)
def test_transient_failures_are_retried_to_the_bound(builder) -> None:
    provider = FakeStructuredModelProvider(results=[builder(TASK), builder(TASK), builder(TASK)])
    result = _call(provider, max_retries=2)
    assert provider.call_count == 3
    assert result.attempts == 3 and not result.succeeded


@pytest.mark.parametrize("builder", [refusal_result, parse_error_result])
def test_refusals_and_parse_errors_are_never_retried(builder) -> None:
    provider = FakeStructuredModelProvider(results=[builder(TASK), builder(TASK)])
    result = _call(provider, max_retries=2)
    assert provider.call_count == 1 and result.attempts == 1
    assert result.status in (ModelCallStatus.REFUSAL, ModelCallStatus.PARSE_ERROR)


def test_a_retry_can_recover() -> None:
    provider = FakeStructuredModelProvider(
        responses=[provider_error_result(TASK), ProjectExtraction()]
    )
    result = _call(provider)
    assert result.succeeded and result.attempts == 2


def test_zero_retries_makes_exactly_one_call() -> None:
    provider = FakeStructuredModelProvider(results=[provider_error_result(TASK)])
    assert _call(provider, max_retries=0).attempts == 1
    assert provider.call_count == 1


def test_the_prompt_and_model_reach_the_provider_unchanged() -> None:
    provider = FakeStructuredModelProvider(response=ProjectExtraction())
    _call(provider)
    call = provider.calls[-1]
    assert call["system_prompt"] == "system" and call["user_input"] == "input"
    assert call["model"] == "fake-model" and call["task"] is TASK


def test_fake_provider_determinism_is_preserved() -> None:
    first = FakeStructuredModelProvider(response=ProjectExtraction())
    second = FakeStructuredModelProvider(response=ProjectExtraction())
    assert _call(first).model_dump(exclude={"called_at", "latency_ms"}) == _call(second).model_dump(
        exclude={"called_at", "latency_ms"}
    )


def test_intake_still_routes_through_the_shared_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A regression guard: intake behaviour is unchanged by the refactor."""
    from tests.fixtures import submissions as fx

    provider = FakeStructuredModelProvider(
        responses=[provider_error_result(ModelTask.PROJECT_EXTRACTION), ProjectExtraction()]
    )
    result = extractor.run_project_extraction(
        fx.make_artifact("Our project uses one sensor."), provider, LLMSettings(max_retries=1)
    )
    assert result.succeeded and result.attempts == 2 and provider.call_count == 2
