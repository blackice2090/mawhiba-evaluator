"""Tests for sources, findings, contradictions and missing information
(architecture 7.1, 7.4, 7.5, 11, 18, 24, 27)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.common import ConfidenceLevel, ResearchBranch, Severity
from src.schemas.finding import (
    ContradictionRecord,
    ContradictionStatus,
    FindingCategory,
    FindingRecord,
    MissingInformationRecord,
)
from src.schemas.prior_art import (
    PriorArtKind,
    PriorArtRecord,
    SimilarityDimensions,
)
from src.schemas.source import (
    ResearchQueryRecord,
    SourceProvider,
    SourceRecord,
    SourceType,
)


# --- sources ---------------------------------------------------------------

def test_official_source_requires_url_and_content_hash() -> None:
    """2.4: every official-rules snapshot is stored with URL + hash."""
    with pytest.raises(ValidationError, match="requires both url and content_hash"):
        SourceRecord(
            source_id="SRC-001",
            source_type=SourceType.OFFICIAL_COMPETITION_SOURCE,
            url="https://example.org/rules",
        )


def test_official_source_with_full_provenance_is_accepted() -> None:
    source = SourceRecord(
        source_id="SRC-001",
        source_type=SourceType.OFFICIAL_COMPETITION_SOURCE,
        url="https://example.org/rules",
        content_hash="sha256:abc",
        version_or_publication_date="2026-01-15",
        provider=SourceProvider.OPENAI_WEB_SEARCH,
    )
    assert source.retrieved_at.tzinfo is not None


def test_source_cannot_be_its_own_duplicate() -> None:
    with pytest.raises(ValidationError, match="duplicate of itself"):
        SourceRecord(
            source_id="SRC-001",
            source_type=SourceType.ACADEMIC_PAPER,
            duplicate_of="SRC-001",
        )


def test_source_id_format_is_enforced() -> None:
    with pytest.raises(ValidationError):
        SourceRecord(source_id="001", source_type=SourceType.ACADEMIC_PAPER)


def test_source_quality_stays_within_the_unit_interval() -> None:
    with pytest.raises(ValidationError):
        SourceRecord(
            source_id="SRC-001",
            source_type=SourceType.ACADEMIC_PAPER,
            quality={"authority": 1.5},
        )


def test_query_selected_count_cannot_exceed_results() -> None:
    with pytest.raises(ValidationError, match="cannot exceed result_count"):
        ResearchQueryRecord(
            query_id="Q-001",
            branch=ResearchBranch.ACADEMIC,
            query="x",
            result_count=3,
            selected_count=5,
        )


# --- prior art -------------------------------------------------------------

def test_unassessed_similarity_dimension_is_none_not_zero() -> None:
    """None = not assessed; 0.0 = assessed and dissimilar. Not the same thing."""
    dims = SimilarityDimensions(problem=0.0)
    assert dims.problem == 0.0
    assert dims.method is None
    assert dims.assessed_dimensions == {"problem": 0.0}
    assert dims.max_similarity == 0.0


def test_high_novelty_threat_requires_an_assessment() -> None:
    with pytest.raises(ValidationError, match="at least one assessed"):
        PriorArtRecord(
            prior_art_id="PA-001",
            source_id="SRC-001",
            kind=PriorArtKind.PATENT,
            novelty_threat=Severity.HIGH,
        )


# --- findings --------------------------------------------------------------

def test_high_confidence_finding_requires_a_reference() -> None:
    with pytest.raises(ValidationError, match="must reference evidence_ids"):
        FindingRecord(
            finding_id="F-001",
            category=FindingCategory.METHODOLOGY,
            severity=Severity.HIGH,
            finding="leakage",
            reason="train and test overlap",
            confidence=ConfidenceLevel.HIGH,
        )


def test_critical_finding_is_blocking_by_default() -> None:
    finding = FindingRecord(
        finding_id="F-001",
        category=FindingCategory.DATA,
        severity=Severity.CRITICAL,
        finding="Test set overlaps the training set.",
        reason="Reported accuracy is not measured on held-out data.",
    )
    assert finding.is_blocking


def test_low_severity_finding_is_not_blocking() -> None:
    finding = FindingRecord(
        finding_id="F-002",
        category=FindingCategory.OTHER,
        severity=Severity.LOW,
        finding="Figure captions are inconsistent.",
        reason="Minor presentation issue.",
    )
    assert not finding.is_blocking


# --- contradictions --------------------------------------------------------

def test_contradiction_needs_two_sides() -> None:
    with pytest.raises(ValidationError, match="at least 2 conflicting statements"):
        ContradictionRecord(
            contradiction_id="CT-001",
            description="x",
            severity=Severity.HIGH,
            conflicting_statements=["only one"],
        )


def test_resolved_contradiction_must_state_its_resolution() -> None:
    with pytest.raises(ValidationError, match="must state its resolution"):
        ContradictionRecord(
            contradiction_id="CT-001",
            description="x",
            severity=Severity.HIGH,
            status=ContradictionStatus.RESOLVED,
            conflicting_statements=["a", "b"],
        )


def test_open_critical_contradiction_is_flagged() -> None:
    contradiction = ContradictionRecord(
        contradiction_id="CT-001",
        description="accuracy differs between artifacts",
        severity=Severity.CRITICAL,
        status=ContradictionStatus.OPEN,
        conflicting_statements=["95%", "87%"],
    )
    assert contradiction.is_unresolved_critical


# --- missing information ---------------------------------------------------

def test_do_not_ask_the_student_for_externally_retrievable_facts() -> None:
    """24: the agent searches for competition rules; it does not ask."""
    with pytest.raises(ValidationError, match="retrievable externally"):
        MissingInformationRecord(
            field_path="competition.rules",
            description="official weighting unknown",
            retrievable_externally=True,
            question_for_student="What are the competition rules?",
        )


def test_asking_for_non_retrievable_critical_information_is_allowed() -> None:
    record = MissingInformationRecord(
        field_path="methodology.baseline",
        description="no baseline reported",
        severity=Severity.CRITICAL,
        retrievable_externally=False,
        question_for_student="What baseline did you compare against?",
    )
    assert record.is_critical
