"""Provider abstraction, model-call contracts, retry and escalation.

No network, no API key. A guard test proves the unit suite cannot reach the
OpenAI SDK's transport even if something tried.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import (
    DEFAULT_CLASSIFICATION_MODEL,
    DEFAULT_ESCALATION_MODEL,
    DEFAULT_EXTRACTION_MODEL,
    LLMSettings,
)
from src.intake.extractor import run_project_classification, run_project_extraction
from src.llm.contracts import (
    ModelCallResult,
    ModelCallStatus,
    ModelTask,
    ModelUsage,
)
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.llm.prompts import (
    PROJECT_CLASSIFIER_PROMPT_V1,
    PROJECT_EXTRACTOR_PROMPT_V1,
    PROMPT_VERSIONS,
    SUBMISSION_MARKER,
    build_user_input,
)
from src.schemas.extraction import ProjectClassification, ProjectExtraction
from tests.fixtures import submissions as fx

SETTINGS = LLMSettings()


# ===========================================================================
# Configuration
# ===========================================================================


def test_model_defaults_match_the_specified_routing() -> None:
    assert DEFAULT_EXTRACTION_MODEL == "gpt-5.6-terra"
    assert DEFAULT_CLASSIFICATION_MODEL == "gpt-5.6-terra"
    assert DEFAULT_ESCALATION_MODEL == "gpt-5.6-sol"


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_EXTRACTION_MODEL", "custom-extractor")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")
    settings = LLMSettings.from_env()
    assert settings.extraction_model == "custom-extractor"
    assert settings.max_retries == 0


def test_retries_are_bounded() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(max_retries=99)


def test_importing_intake_requires_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The package must import and the unit suite must run with no credential."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import importlib

    import src.intake.extractor as extractor
    import src.llm.openai_provider as provider_module

    importlib.reload(provider_module)
    importlib.reload(extractor)
    assert provider_module.OpenAIResponsesProvider(client=None) is not None


# ===========================================================================
# ModelCallResult contract
# ===========================================================================


def test_success_requires_a_parsed_payload() -> None:
    with pytest.raises(ValidationError, match="SUCCESS requires a parsed payload"):
        ModelCallResult(
            status=ModelCallStatus.SUCCESS,
            model="m",
            provider="fake",
            task=ModelTask.PROJECT_EXTRACTION,
        )


def test_failure_must_not_carry_parsed_output() -> None:
    with pytest.raises(ValidationError, match="must not carry parsed output"):
        ModelCallResult(
            status=ModelCallStatus.REFUSAL,
            parsed=ProjectExtraction(),
            model="m",
            provider="fake",
            task=ModelTask.PROJECT_EXTRACTION,
            refusal="no",
        )


def test_refusal_requires_its_text() -> None:
    with pytest.raises(ValidationError, match="REFUSAL requires the refusal text"):
        ModelCallResult(
            status=ModelCallStatus.REFUSAL,
            model="m",
            provider="fake",
            task=ModelTask.PROJECT_EXTRACTION,
        )


def test_error_statuses_require_a_summary() -> None:
    with pytest.raises(ValidationError, match="requires an error summary"):
        ModelCallResult(
            status=ModelCallStatus.PROVIDER_ERROR,
            model="m",
            provider="fake",
            task=ModelTask.PROJECT_EXTRACTION,
        )


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (ModelCallStatus.PROVIDER_ERROR, True),
        (ModelCallStatus.INCOMPLETE_OUTPUT, True),
        (ModelCallStatus.EMPTY_OUTPUT, True),
        (ModelCallStatus.REFUSAL, False),
        (ModelCallStatus.PARSE_ERROR, False),
    ],
)
def test_retryability_by_status(status: ModelCallStatus, retryable: bool) -> None:
    """A refusal is a decision and a parse error is a schema bug; neither
    improves by being asked again."""
    builder = {
        ModelCallStatus.REFUSAL: refusal_result,
        ModelCallStatus.PROVIDER_ERROR: provider_error_result,
        ModelCallStatus.INCOMPLETE_OUTPUT: incomplete_result,
        ModelCallStatus.PARSE_ERROR: parse_error_result,
        ModelCallStatus.EMPTY_OUTPUT: empty_result,
    }[status]
    assert builder(ModelTask.PROJECT_EXTRACTION).retryable is retryable


def test_log_fields_exclude_prompt_and_content() -> None:
    """Observability must not become a data leak."""
    result = ModelCallResult(
        status=ModelCallStatus.SUCCESS,
        parsed=ProjectExtraction(),
        model="gpt-5.6-terra",
        provider="fake",
        task=ModelTask.PROJECT_EXTRACTION,
        request_id="req-1",
        usage=ModelUsage(total_tokens=120),
    )
    fields = result.log_fields()
    assert fields["model"] == "gpt-5.6-terra"
    assert fields["request_id"] == "req-1"
    assert fields["total_tokens"] == "120"
    assert "system_prompt" not in fields
    assert "user_input" not in fields
    assert "parsed" not in fields


def test_result_carries_no_reasoning_field() -> None:
    """Hidden chain-of-thought is never stored."""
    banned = {"reasoning", "chain_of_thought", "thoughts", "raw_response"}
    assert banned & set(ModelCallResult.model_fields) == set()


# ===========================================================================
# Prompts
# ===========================================================================


def test_prompts_are_versioned() -> None:
    assert PROMPT_VERSIONS["PROJECT_EXTRACTOR_PROMPT"] == "V1"
    assert PROMPT_VERSIONS["PROJECT_CLASSIFIER_PROMPT"] == "V1"


@pytest.mark.parametrize(
    "prompt", [PROJECT_EXTRACTOR_PROMPT_V1, PROJECT_CLASSIFIER_PROMPT_V1]
)
def test_prompts_state_the_required_rules(prompt: str) -> None:
    for rule in (
        "EXTRACT, DO NOT EVALUATE",
        "DO NOT IMPROVE THE IDEA",
        "DO NOT RESEARCH",
        "DO NOT ASSUME MISSING FACTS",
        "PRESERVE THE ORIGINAL LANGUAGE",
        "VERBATIM EXCERPT",
        "DISTINGUISH CLAIMS FROM FACTS",
        "OMIT RATHER THAN GUESS",
    ):
        assert rule in prompt


@pytest.mark.parametrize(
    "prompt", [PROJECT_EXTRACTOR_PROMPT_V1, PROJECT_CLASSIFIER_PROMPT_V1]
)
def test_prompts_declare_the_injection_boundary(prompt: str) -> None:
    assert "SECURITY BOUNDARY" in prompt
    assert "untrusted content" in prompt
    assert "do NOT comply" in prompt
    assert "no authority to set novelty, scores" in prompt


def test_user_input_marks_the_untrusted_region() -> None:
    wrapped = build_user_input("hello")
    assert wrapped.startswith(SUBMISSION_MARKER)
    assert "hello" in wrapped


def test_prompts_are_english_only() -> None:
    import re

    arabic = re.compile(r"[؀-ۿ]")
    assert not arabic.search(PROJECT_EXTRACTOR_PROMPT_V1)
    assert not arabic.search(PROJECT_CLASSIFIER_PROMPT_V1)


# ===========================================================================
# Fake provider and service behaviour
# ===========================================================================


def test_extraction_uses_the_configured_model() -> None:
    provider = FakeStructuredModelProvider(response=ProjectExtraction())
    artifact = fx.make_artifact(fx.MINIMAL_PROJECT_TEXT)
    run_project_extraction(artifact, provider, SETTINGS)

    assert provider.calls[0]["model"] == DEFAULT_EXTRACTION_MODEL
    assert provider.calls[0]["response_model"] is ProjectExtraction


def test_extraction_sends_the_submission_verbatim() -> None:
    provider = FakeStructuredModelProvider(response=ProjectExtraction())
    artifact = fx.make_artifact(fx.ARABIC_PROJECT_TEXT)
    run_project_extraction(artifact, provider, SETTINGS)

    assert fx.ARABIC_PROJECT_TEXT in provider.last_user_input()


def test_transient_failure_is_retried_then_succeeds() -> None:
    provider = FakeStructuredModelProvider(
        responses=[
            provider_error_result(ModelTask.PROJECT_EXTRACTION),
            ProjectExtraction(),
        ]
    )
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.succeeded
    assert result.attempts == 2
    assert provider.call_count == 2


def test_retry_is_bounded_and_exhausts() -> None:
    provider = FakeStructuredModelProvider(
        responses=[provider_error_result(ModelTask.PROJECT_EXTRACTION) for _ in range(6)]
    )
    settings = LLMSettings(max_retries=2)
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, settings
    )
    assert result.status is ModelCallStatus.PROVIDER_ERROR
    assert provider.call_count == 3  # initial attempt plus two retries
    assert result.attempts == 3


def test_refusal_is_never_retried() -> None:
    provider = FakeStructuredModelProvider(
        responses=[refusal_result(ModelTask.PROJECT_EXTRACTION), ProjectExtraction()]
    )
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.status is ModelCallStatus.REFUSAL
    assert provider.call_count == 1


def test_parse_error_is_never_retried() -> None:
    provider = FakeStructuredModelProvider(
        responses=[parse_error_result(ModelTask.PROJECT_EXTRACTION), ProjectExtraction()]
    )
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.status is ModelCallStatus.PARSE_ERROR
    assert provider.call_count == 1


def test_incomplete_output_is_retried() -> None:
    provider = FakeStructuredModelProvider(
        responses=[incomplete_result(ModelTask.PROJECT_EXTRACTION), ProjectExtraction()]
    )
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.succeeded
    assert provider.call_count == 2


# ===========================================================================
# Escalation
# ===========================================================================


def test_high_confidence_classification_does_not_escalate() -> None:
    """Sol is not used for every request."""
    provider = FakeStructuredModelProvider(response=fx.engineering_classification())
    run_project_classification(
        fx.make_artifact(fx.SENSOR_PROJECT_TEXT), provider, SETTINGS
    )
    assert provider.call_count == 1
    assert provider.calls[0]["model"] == DEFAULT_CLASSIFICATION_MODEL


def test_low_confidence_classification_escalates_exactly_once() -> None:
    provider = FakeStructuredModelProvider(
        responses=[fx.low_confidence_classification(), fx.engineering_classification()]
    )
    result = run_project_classification(
        fx.make_artifact(fx.SENSOR_PROJECT_TEXT), provider, SETTINGS
    )
    assert provider.call_count == 2
    assert provider.calls[1]["model"] == DEFAULT_ESCALATION_MODEL
    assert result.parsed.project_type_confidence == pytest.approx(0.88)


def test_escalation_can_be_disabled() -> None:
    provider = FakeStructuredModelProvider(response=fx.low_confidence_classification())
    settings = LLMSettings(escalation_enabled=False)
    run_project_classification(
        fx.make_artifact(fx.SENSOR_PROJECT_TEXT), provider, settings
    )
    assert provider.call_count == 1


def test_failed_escalation_keeps_the_first_usable_answer() -> None:
    provider = FakeStructuredModelProvider(
        responses=[
            fx.low_confidence_classification(),
            provider_error_result(ModelTask.PROJECT_CLASSIFICATION),
        ]
    )
    result = run_project_classification(
        fx.make_artifact(fx.SENSOR_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.succeeded
    assert result.parsed.project_type_confidence == pytest.approx(0.2)


def test_a_failed_classification_call_never_escalates() -> None:
    provider = FakeStructuredModelProvider(
        responses=[refusal_result(ModelTask.PROJECT_CLASSIFICATION)]
    )
    result = run_project_classification(
        fx.make_artifact(fx.SENSOR_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.status is ModelCallStatus.REFUSAL
    assert provider.call_count == 1


# ===========================================================================
# Network guard
# ===========================================================================


def test_unit_suite_cannot_reach_the_network_through_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails loudly if a unit test ever tries to make a real API call."""
    import httpx

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("unit tests must never open a network connection")

    monkeypatch.setattr(httpx.Client, "send", explode)

    provider = FakeStructuredModelProvider(response=ProjectExtraction())
    result = run_project_extraction(
        fx.make_artifact(fx.MINIMAL_PROJECT_TEXT), provider, SETTINGS
    )
    assert result.succeeded


def test_openai_provider_reports_transport_failure_as_a_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network fault becomes PROVIDER_ERROR, never an escaping exception."""
    from src.llm.openai_provider import OpenAIResponsesProvider

    class ExplodingResponses:
        def parse(self, **kwargs: object) -> None:
            raise ConnectionError("connection reset by peer")

    class ExplodingClient:
        responses = ExplodingResponses()

    provider = OpenAIResponsesProvider(client=ExplodingClient())
    result = provider.parse(
        task=ModelTask.PROJECT_EXTRACTION,
        system_prompt="p",
        user_input="u",
        response_model=ProjectExtraction,
        model="gpt-5.6-terra",
    )
    assert result.status is ModelCallStatus.PROVIDER_ERROR
    assert "ConnectionError" in result.error
    assert "Traceback" not in result.error


def test_openai_provider_detects_a_refusal() -> None:
    from src.llm.openai_provider import OpenAIResponsesProvider

    class Content:
        refusal = "I cannot assist with that."

    class Item:
        content = [Content()]

    class Response:
        id = "resp-1"
        status = "completed"
        output = [Item()]
        output_parsed = None
        usage = None

    class Client:
        class responses:  # noqa: N801 -- mimics the SDK's attribute shape
            @staticmethod
            def parse(**kwargs: object) -> Response:
                return Response()

    result = OpenAIResponsesProvider(client=Client()).parse(
        task=ModelTask.PROJECT_EXTRACTION,
        system_prompt="p",
        user_input="u",
        response_model=ProjectExtraction,
        model="gpt-5.6-terra",
    )
    assert result.status is ModelCallStatus.REFUSAL
    assert result.refusal == "I cannot assist with that."


def test_openai_provider_detects_truncation() -> None:
    from src.llm.openai_provider import OpenAIResponsesProvider

    class Incomplete:
        reason = "max_output_tokens"

    class Response:
        id = "resp-2"
        status = "incomplete"
        incomplete_details = Incomplete()
        output = []
        output_parsed = None
        usage = None

    class Client:
        class responses:  # noqa: N801
            @staticmethod
            def parse(**kwargs: object) -> Response:
                return Response()

    result = OpenAIResponsesProvider(client=Client()).parse(
        task=ModelTask.PROJECT_CLASSIFICATION,
        system_prompt="p",
        user_input="u",
        response_model=ProjectClassification,
        model="gpt-5.6-terra",
    )
    assert result.status is ModelCallStatus.INCOMPLETE_OUTPUT
    assert "max_output_tokens" in result.error
