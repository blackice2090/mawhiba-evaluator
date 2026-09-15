"""Tests for the Zero Assumption primitives (architecture 2.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from src.schemas.common import (
    ConfidenceLevel,
    KnowledgeStatus,
    Tracked,
    UtcDatetime,
    ValueOrigin,
    utc_now,
)


class _Stamped(BaseModel):
    at: UtcDatetime


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _Stamped(at=datetime(2026, 1, 1, 12, 0, 0))


def test_aware_datetime_is_normalized_to_utc() -> None:
    plus_three = timezone(timedelta(hours=3))
    stamped = _Stamped(at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_three))
    assert stamped.at.tzinfo == timezone.utc
    assert stamped.at.hour == 9


def test_utc_now_is_aware() -> None:
    assert utc_now().tzinfo is not None


def test_unknown_carries_no_value() -> None:
    """The point of Tracked: absence is explicit, not a silent None."""
    field = Tracked[str].unknown("student never mentioned the dataset")
    assert field.value is None
    assert field.status is KnowledgeStatus.UNKNOWN
    assert not field.is_known


def test_unknown_with_a_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not carry a value"):
        Tracked[str](value="guessed", status=KnowledgeStatus.UNKNOWN)


def test_known_without_a_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires a value"):
        Tracked[str](value=None, status=KnowledgeStatus.KNOWN)


def test_agent_inference_can_never_be_known() -> None:
    """2.1: the model's own guess is never promoted to KNOWN."""
    with pytest.raises(ValidationError, match="agent inference can never be KNOWN"):
        Tracked[str](
            value="probably a CNN",
            status=KnowledgeStatus.KNOWN,
            origin=ValueOrigin.AGENT_INFERENCE,
        )


def test_agent_inference_is_allowed_as_non_critical() -> None:
    field = Tracked[str].inferred("probably a CNN", note="from the word 'classifies'")
    assert field.status is KnowledgeStatus.INFERRED_NON_CRITICAL
    assert not field.is_known


def test_conflicted_requires_two_values() -> None:
    with pytest.raises(ValidationError, match="at least 2 conflicting_values"):
        Tracked[str].conflicted(["95%"])


def test_conflicted_keeps_both_sides_and_adopts_neither() -> None:
    field = Tracked[str].conflicted(["95%", "87%"], note="poster vs report")
    assert field.value is None
    assert field.conflicting_values == ["95%", "87%"]
    assert field.status is KnowledgeStatus.CONFLICTED


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, ConfidenceLevel.VERY_LOW),
        (0.24, ConfidenceLevel.VERY_LOW),
        (0.25, ConfidenceLevel.LOW),
        (0.49, ConfidenceLevel.LOW),
        (0.5, ConfidenceLevel.MEDIUM),
        (0.74, ConfidenceLevel.MEDIUM),
        (0.75, ConfidenceLevel.HIGH),
        (1.0, ConfidenceLevel.HIGH),
    ],
)
def test_confidence_level_from_score(score: float, expected: ConfidenceLevel) -> None:
    assert ConfidenceLevel.from_score(score) is expected


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_confidence_outside_unit_interval_is_rejected(score: float) -> None:
    with pytest.raises(ValueError, match=r"within \[0,1\]"):
        ConfidenceLevel.from_score(score)
