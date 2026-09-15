"""Tests for the Claim-Evidence contract (architecture 2.2, 7.2, 7.3, 17)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.claim import (
    ClaimOrigin,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    RequiredEvidenceKind,
)
from src.schemas.evidence import (
    EvidenceLocation,
    EvidenceRecord,
    EvidenceStrength,
    EvidenceType,
    SupportDirection,
)


# --- evidence -------------------------------------------------------------

def test_evidence_requires_a_source() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="E-001",
            evidence_type=EvidenceType.BASELINE,
            statement="something",
        )


def test_evidence_source_id_format_is_enforced() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="E-001",
            source_id="not-a-source",
            evidence_type=EvidenceType.BASELINE,
            statement="something",
        )


def test_verified_evidence_needs_a_location_anchor() -> None:
    with pytest.raises(ValidationError, match="location anchor"):
        EvidenceRecord(
            evidence_id="E-001",
            source_id="SRC-001",
            evidence_type=EvidenceType.BASELINE,
            statement="baseline is 0.35 L/min",
            verified=True,
        )


def test_strong_evidence_must_be_verified() -> None:
    with pytest.raises(ValidationError, match="STRONG evidence requires verified"):
        EvidenceRecord(
            evidence_id="E-001",
            source_id="SRC-001",
            evidence_type=EvidenceType.BASELINE,
            statement="baseline is 0.35 L/min",
            strength=EvidenceStrength.STRONG,
            location=EvidenceLocation(page=7),
            verified=False,
        )


# --- claims ---------------------------------------------------------------

def test_unsupported_claim_without_evidence_is_valid() -> None:
    """The honest default: a student assertion with nothing behind it."""
    claim = ClaimRecord(
        claim_id="C-001",
        claim="The system is more accurate than existing solutions.",
        claim_type=ClaimType.PERFORMANCE,
        origin=ClaimOrigin.STUDENT,
        status=ClaimStatus.UNSUPPORTED,
        required_evidence=[
            RequiredEvidenceKind.BASELINE,
            RequiredEvidenceKind.METRIC,
        ],
        missing_evidence=[
            RequiredEvidenceKind.BASELINE,
            RequiredEvidenceKind.METRIC,
        ],
    )
    assert claim.evidence_ids == []
    assert not claim.is_strong
    assert claim.is_traceable


@pytest.mark.parametrize("status", [ClaimStatus.SUPPORTED, ClaimStatus.VERIFIED])
def test_strong_claim_without_evidence_is_rejected(status: ClaimStatus) -> None:
    """2.2: No Evidence -> No Strong Claim."""
    with pytest.raises(ValidationError, match="requires at least one evidence_id"):
        ClaimRecord(
            claim_id="C-001",
            claim="The system is more accurate.",
            status=status,
            evidence_ids=[],
        )


def test_verified_claim_with_evidence_is_accepted() -> None:
    claim = ClaimRecord(
        claim_id="C-001",
        claim="Prototype detects leaks at 0.18 L/min versus a 0.35 L/min baseline.",
        claim_type=ClaimType.PERFORMANCE,
        status=ClaimStatus.VERIFIED,
        evidence_ids=["E-001", "E-002"],
        required_evidence=[
            RequiredEvidenceKind.BASELINE,
            RequiredEvidenceKind.METRIC,
        ],
        missing_evidence=[],
        confidence=0.85,
    )
    assert claim.is_strong
    assert claim.is_traceable


def test_strong_claim_with_outstanding_missing_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="missing_evidence is non-empty"):
        ClaimRecord(
            claim_id="C-001",
            claim="The system is more accurate.",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=["E-001"],
            required_evidence=[RequiredEvidenceKind.BASELINE],
            missing_evidence=[RequiredEvidenceKind.BASELINE],
        )


def test_unsupported_claim_may_not_carry_evidence() -> None:
    with pytest.raises(ValidationError, match="must have no evidence_ids"):
        ClaimRecord(
            claim_id="C-001",
            claim="x",
            status=ClaimStatus.UNSUPPORTED,
            evidence_ids=["E-001"],
        )


def test_contradicted_claim_requires_counter_evidence() -> None:
    with pytest.raises(ValidationError, match="requires at least one counter_evidence_id"):
        ClaimRecord(
            claim_id="C-001",
            claim="x",
            status=ClaimStatus.CONTRADICTED,
            counter_evidence_ids=[],
        )


def test_contradicted_claim_with_counter_evidence_is_accepted() -> None:
    claim = ClaimRecord(
        claim_id="C-001",
        claim="The dataset was externally validated.",
        status=ClaimStatus.CONTRADICTED,
        counter_evidence_ids=["E-009"],
    )
    assert claim.is_traceable
    assert not claim.is_strong


def test_evidence_cannot_both_support_and_contradict() -> None:
    with pytest.raises(ValidationError, match="both support and contradict"):
        ClaimRecord(
            claim_id="C-001",
            claim="x",
            status=ClaimStatus.SUPPORTED,
            evidence_ids=["E-001"],
            counter_evidence_ids=["E-001"],
        )


def test_missing_evidence_must_be_subset_of_required() -> None:
    with pytest.raises(ValidationError, match="subset of required_evidence"):
        ClaimRecord(
            claim_id="C-001",
            claim="x",
            status=ClaimStatus.PLAUSIBLE,
            required_evidence=[RequiredEvidenceKind.BASELINE],
            missing_evidence=[RequiredEvidenceKind.METRIC],
        )


def test_unsupported_claim_cannot_carry_high_confidence() -> None:
    with pytest.raises(ValidationError, match="confidence above 0.25"):
        ClaimRecord(
            claim_id="C-001",
            claim="x",
            status=ClaimStatus.UNSUPPORTED,
            confidence=0.9,
        )


def test_confidence_outside_unit_interval_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClaimRecord(
            claim_id="C-001", claim="x", status=ClaimStatus.PLAUSIBLE, confidence=1.5
        )


def test_plausible_claim_sits_between_unsupported_and_supported() -> None:
    """A claim with weak but non-zero backing (2.2)."""
    claim = ClaimRecord(
        claim_id="C-003",
        claim="The device can run a full year on one charge.",
        claim_type=ClaimType.FEASIBILITY,
        status=ClaimStatus.PLAUSIBLE,
        evidence_ids=["E-004"],
        required_evidence=[RequiredEvidenceKind.REPEATED_MEASUREMENTS],
        missing_evidence=[RequiredEvidenceKind.REPEATED_MEASUREMENTS],
        confidence=0.3,
    )
    assert not claim.is_strong


def test_evidence_and_claim_link_through_source(project_b) -> None:
    """Claim -> Evidence -> Source is the provenance chain the report relies on."""
    sources = project_b.sources_for_claim("C-001")
    assert {s.source_id for s in sources} == {"SRC-001"}


def test_support_direction_is_recorded(project_b) -> None:
    e3 = project_b.evidence_by_id("E-003")
    assert e3 is not None
    assert e3.support_direction is SupportDirection.NEUTRAL
