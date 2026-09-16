"""Extraction and classification services.

These own model routing and the single narrow escalation rule. The bounded retry
policy itself lives in the shared LLM layer
(``src.llm.invocation.call_structured_model_with_retries``), so intake and
research share one implementation.

They return ``ModelCallResult`` objects, so a refusal or a transport failure is
data the workflow records rather than an exception that unwinds it.
"""

from __future__ import annotations

import logging

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import (
    PROJECT_CLASSIFIER_PROMPT_V1,
    PROJECT_EXTRACTOR_PROMPT_V1,
    build_user_input,
)
from src.llm.provider import StructuredModelProvider
from src.schemas.extraction import ProjectClassification, ProjectExtraction
from src.schemas.submission import StudentSubmissionArtifact

logger = logging.getLogger(__name__)


def run_project_extraction(
    artifact: StudentSubmissionArtifact,
    provider: StructuredModelProvider,
    settings: LLMSettings,
) -> ModelCallResult[ProjectExtraction]:
    """Extract intake information from one submission artifact."""
    return call_structured_model_with_retries(
        provider,
        task=ModelTask.PROJECT_EXTRACTION,
        system_prompt=PROJECT_EXTRACTOR_PROMPT_V1,
        user_input=build_user_input(artifact.original_text),
        response_model=ProjectExtraction,
        model=settings.extraction_model,
        max_retries=settings.max_retries,
    )


def run_project_classification(
    artifact: StudentSubmissionArtifact,
    provider: StructuredModelProvider,
    settings: LLMSettings,
) -> ModelCallResult[ProjectClassification]:
    """Classify project type and technical domains.

    Escalation is deliberately narrow: only when the call structurally succeeded
    but returned a project type below the configured confidence threshold does
    the stronger model get one -- exactly one -- additional attempt. Escalation
    buys reasoning quality on an ambiguous judgement; it is never used to turn an
    UNKNOWN factual field into a guessed value.
    """
    result = call_structured_model_with_retries(
        provider,
        task=ModelTask.PROJECT_CLASSIFICATION,
        system_prompt=PROJECT_CLASSIFIER_PROMPT_V1,
        user_input=build_user_input(artifact.original_text),
        response_model=ProjectClassification,
        model=settings.classification_model,
        max_retries=settings.max_retries,
    )

    if not settings.escalation_enabled or not result.succeeded:
        return result

    parsed = result.parsed
    assert parsed is not None
    if parsed.project_type_confidence >= settings.classification_escalation_threshold:
        return result

    logger.debug(
        "escalating classification: confidence %.2f below threshold %.2f",
        parsed.project_type_confidence,
        settings.classification_escalation_threshold,
    )
    escalated = call_structured_model_with_retries(
        provider,
        task=ModelTask.PROJECT_CLASSIFICATION,
        system_prompt=PROJECT_CLASSIFIER_PROMPT_V1,
        user_input=build_user_input(artifact.original_text),
        response_model=ProjectClassification,
        model=settings.escalation_model,
        max_retries=0,
    )
    # A failed escalation must not lose the usable first answer.
    return escalated if escalated.succeeded else result


__all__ = [
    "ModelCallStatus",
    "run_project_classification",
    "run_project_extraction",
]
