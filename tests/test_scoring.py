"""Tests for the scoring contract (architecture 7.6, 20)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.common import ConfidenceLevel, EvaluationStatus
from src.schemas.score import RubricKind, ScoreAxis, ScoreAxisName, ScoreRecord
from src.scoring.models import (
    ADVISORY_RUBRIC_V1,
    ADVISORY_V1_MAX_TOTAL,
    Rubric,
    RubricAxisDefinition,
    ScoringInput,
)


def test_advisory_v1_totals_one_hundred() -> None:
    assert ADVISORY_RUBRIC_V1.max_total == ADVISORY_V1_MAX_TOTAL


def test_advisory_v1_weights_match_the_architecture() -> None:
    expected = {
        ScoreAxisName.PROBLEM_AND_IMPORTANCE.value: 10,
        ScoreAxisName.SCIENTIFIC_TECHNICAL_BASE.value: 10,
        ScoreAxisName.LITERATURE.value: 10,
        ScoreAxisName.NOVELTY.value: 15,
        ScoreAxisName.GAP.value: 10,
        ScoreAxisName.METHODOLOGY.value: 15,
        ScoreAxisName.EXPERIMENTS.value: 15,
        ScoreAxisName.RESULTS.value: 10,
        ScoreAxisName.JURY_DEFENSIBILITY.value: 5,
    }
    assert {a.axis: a.max_score for a in ADVISORY_RUBRIC_V1.axes} == expected


def test_score_above_max_score_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds max_score"):
        ScoreAxis(
            axis="novelty",
            score=16.0,
            max_score=15.0,
            status=EvaluationStatus.PROVISIONAL,
        )


def test_score_equal_to_max_score_is_accepted() -> None:
    axis = ScoreAxis(
        axis="novelty",
        score=15.0,
        max_score=15.0,
        status=EvaluationStatus.PROVISIONAL,
    )
    assert axis.score == 15.0


def test_negative_score_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ScoreAxis(axis="novelty", score=-1.0, max_score=15.0)


def test_unevaluated_axis_keeps_score_none_not_zero() -> None:
    """2.1: an unscored axis is not a zero."""
    record = ADVISORY_RUBRIC_V1.blank_score_record("SC-001")
    assert all(a.score is None for a in record.axes)
    assert all(a.status is EvaluationStatus.NOT_EVALUATED for a in record.axes)
    assert record.total is None


def test_blank_record_max_total_matches_rubric() -> None:
    record = ADVISORY_RUBRIC_V1.blank_score_record("SC-001")
    assert record.max_total == ADVISORY_V1_MAX_TOTAL


def test_total_must_equal_the_sum_of_axes(project_b) -> None:
    score = project_b.scores[0]
    assert score.total == sum(a.score for a in score.axes)


def test_wrong_total_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not equal the sum"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="ADVISORY-V1",
            axes=[
                ScoreAxis(
                    axis="novelty",
                    score=5.0,
                    max_score=15.0,
                    status=EvaluationStatus.PROVISIONAL,
                )
            ],
            total=12.0,
        )


def test_total_is_refused_while_an_axis_is_unscored() -> None:
    with pytest.raises(ValidationError, match="every axis carries a score"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="ADVISORY-V1",
            axes=[
                ScoreAxis(
                    axis="novelty",
                    score=5.0,
                    max_score=15.0,
                    status=EvaluationStatus.PROVISIONAL,
                ),
                ScoreAxis(axis="gap", score=None, max_score=10.0),
            ],
            total=5.0,
        )


def test_official_and_advisory_are_distinguishable(project_b) -> None:
    score = project_b.scores[0]
    assert score.official is False
    assert score.rubric_kind is RubricKind.ADVISORY
    assert project_b.official_score is None
    assert project_b.advisory_score is score


def test_official_flag_must_match_rubric_kind() -> None:
    with pytest.raises(ValidationError, match="official flag must match rubric_kind"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="OFFICIAL-2026",
            rubric_kind=RubricKind.OFFICIAL,
            official=False,
        )


def test_official_flag_must_match_rubric_version_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'OFFICIAL'"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="ADVISORY-V1",
            rubric_kind=RubricKind.OFFICIAL,
            official=True,
        )


def test_official_rubric_requires_an_official_source() -> None:
    """2.4 / N03: official weights are retrieved, never invented."""
    with pytest.raises(ValidationError, match="requires a source_id"):
        Rubric(
            version="OFFICIAL-2026",
            kind=RubricKind.OFFICIAL,
            axes=[RubricAxisDefinition(axis="novelty", max_score=20)],
        )


def test_official_rubric_with_a_source_is_accepted() -> None:
    rubric = Rubric(
        version="OFFICIAL-2026",
        kind=RubricKind.OFFICIAL,
        source_id="SRC-001",
        axes=[
            RubricAxisDefinition(axis="novelty", max_score=20),
            RubricAxisDefinition(axis="methodology", max_score=30),
        ],
    )
    assert rubric.max_total == 50
    assert rubric.blank_score_record("SC-002").official is True


def test_final_record_rejects_provisional_axes() -> None:
    with pytest.raises(ValidationError, match="cannot contain provisional axes"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="ADVISORY-V1",
            status=EvaluationStatus.FINAL,
            axes=[
                ScoreAxis(
                    axis="novelty",
                    score=5.0,
                    max_score=15.0,
                    provisional=True,
                    status=EvaluationStatus.PROVISIONAL,
                )
            ],
            total=5.0,
        )


def test_insufficient_evidence_axis_carries_no_score() -> None:
    """2.6: abstention, not a fabricated number."""
    with pytest.raises(ValidationError, match="must not carry a score"):
        ScoreAxis(
            axis="novelty",
            score=0.0,
            max_score=15.0,
            status=EvaluationStatus.INSUFFICIENT_EVIDENCE,
        )


def test_high_confidence_axis_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="HIGH-confidence axis requires evidence"):
        ScoreAxis(
            axis="novelty",
            score=12.0,
            max_score=15.0,
            confidence=ConfidenceLevel.HIGH,
            status=EvaluationStatus.PROVISIONAL,
        )


def test_duplicate_axis_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="axis names must be unique"):
        ScoreRecord(
            score_id="SC-001",
            rubric_version="ADVISORY-V1",
            axes=[
                ScoreAxis(axis="novelty", max_score=15.0),
                ScoreAxis(axis="novelty", max_score=15.0),
            ],
        )


def test_scoring_input_refuses_confident_suggestion_without_evidence() -> None:
    with pytest.raises(ValidationError, match="requires evidence_ids"):
        ScoringInput(
            axis="novelty",
            raw_assessment="looks quite novel",
            suggested_fraction=0.8,
            confidence=ConfidenceLevel.HIGH,
        )


def test_scoring_input_allows_low_confidence_suggestion_without_evidence() -> None:
    payload = ScoringInput(
        axis="novelty",
        raw_assessment="cannot tell yet",
        suggested_fraction=0.2,
        confidence=ConfidenceLevel.LOW,
    )
    assert payload.evidence_ids == []
