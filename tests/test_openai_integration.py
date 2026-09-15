"""Optional live OpenAI integration test.

Skipped unless RUN_OPENAI_INTEGRATION_TESTS=1 is set explicitly. The presence of
an API key alone is deliberately NOT enough to trigger it -- a developer with a
key in their environment must never incur cost by running `pytest`.

Cost safety: the whole module makes at most two model calls, on a two-sentence
submission.

Assertions are structural, never on the model's exact wording: the point is that
the trust machinery holds, not that a particular phrasing appears.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.config.settings import LLMSettings
from src.graph.state import ProjectState
from src.intake.extractor import run_project_classification, run_project_extraction
from src.intake.merge import merge_classification, merge_intake_extraction
from src.intake.verification import verify_classification, verify_extraction
from src.schemas.common import KnowledgeStatus
from src.schemas.extraction import ProjectClassification, ProjectExtraction
from src.schemas.submission import StudentSubmissionArtifact

RUN_LIVE = os.getenv("RUN_OPENAI_INTEGRATION_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="live OpenAI test; set RUN_OPENAI_INTEGRATION_TESTS=1 to enable",
)

TINY_SUBMISSION = (
    "Our project is called LeakFinder. It uses one pressure sensor to detect "
    "water leaks in home pipes."
)


@pytest.fixture(scope="module")
def artifact() -> StudentSubmissionArtifact:
    return StudentSubmissionArtifact(project_id=uuid4(), original_text=TINY_SUBMISSION)


@pytest.fixture(scope="module")
def live_extraction(artifact: StudentSubmissionArtifact) -> ProjectExtraction:
    """One extraction call, shared by every assertion in this module."""
    from src.llm.openai_provider import OpenAIResponsesProvider

    result = run_project_extraction(
        artifact, OpenAIResponsesProvider(), LLMSettings(max_retries=0)
    )
    assert result.succeeded, f"live extraction failed: {result.status} {result.error}"
    return result.parsed


@pytest.fixture(scope="module")
def live_classification(artifact: StudentSubmissionArtifact) -> ProjectClassification:
    """One classification call, with escalation disabled to bound cost."""
    from src.llm.openai_provider import OpenAIResponsesProvider

    result = run_project_classification(
        artifact,
        OpenAIResponsesProvider(),
        LLMSettings(max_retries=0, escalation_enabled=False),
    )
    assert result.succeeded, f"live classification failed: {result.status}"
    return result.parsed


def test_live_extraction_returns_valid_structured_output(
    live_extraction: ProjectExtraction,
) -> None:
    assert isinstance(live_extraction, ProjectExtraction)
    ProjectExtraction.model_validate(live_extraction.model_dump())


def test_live_extraction_supplies_real_provenance(
    artifact: StudentSubmissionArtifact, live_extraction: ProjectExtraction
) -> None:
    """Every accepted field must be anchored in the real submission."""
    verified = verify_extraction(artifact, live_extraction)
    for field in verified.accepted_fields:
        assert field.anchor.verified
        assert field.anchor.matches


def test_live_extraction_invents_no_field(
    artifact: StudentSubmissionArtifact, live_extraction: ProjectExtraction
) -> None:
    """The submission names no dataset, metric or baseline, so none may appear."""
    verified = verify_extraction(artifact, live_extraction)
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.technical.datasets == []
    assert project.methodology.baseline == []
    assert project.methodology.metrics == []
    assert project.methodology.hypothesis.status is KnowledgeStatus.UNKNOWN


def test_live_extraction_merges_into_a_valid_canonical_state(
    artifact: StudentSubmissionArtifact, live_extraction: ProjectExtraction
) -> None:
    verified = verify_extraction(artifact, live_extraction)
    project, _ = merge_intake_extraction(ProjectState(), verified)
    assert ProjectState.model_validate(project.model_dump()) == project


def test_live_classification_is_anchored_and_merges(
    artifact: StudentSubmissionArtifact, live_classification: ProjectClassification
) -> None:
    verified = verify_classification(artifact, live_classification)
    project, _ = merge_classification(ProjectState(), verified)

    if verified.type_anchor is not None:
        assert verified.type_anchor.verified
    for domain in verified.domains:
        if domain.accepted:
            assert domain.anchor.verified
    assert ProjectState.model_validate(project.model_dump()) == project


def test_live_run_creates_no_evidence_or_scores(
    artifact: StudentSubmissionArtifact, live_extraction: ProjectExtraction
) -> None:
    """The evaluation boundary holds against a real model too."""
    verified = verify_extraction(artifact, live_extraction)
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.evidence == []
    assert project.sources == []
    assert project.scores == []
    assert project.novelty.level is None
