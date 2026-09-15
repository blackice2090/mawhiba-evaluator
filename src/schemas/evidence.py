"""EvidenceRecord -- architecture 7.2. Evidence is the only bridge between a
SourceRecord and a ClaimRecord."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime


class EvidenceType(StrEnum):
    PRIOR_ART = "PRIOR_ART"
    BASELINE = "BASELINE"
    BENCHMARK = "BENCHMARK"
    EXPERIMENTAL_RESULT = "EXPERIMENTAL_RESULT"
    METHODOLOGY = "METHODOLOGY"
    PROBLEM_VALIDATION = "PROBLEM_VALIDATION"
    OFFICIAL_RULE = "OFFICIAL_RULE"
    TECHNICAL_SPECIFICATION = "TECHNICAL_SPECIFICATION"
    DATASET_PROPERTY = "DATASET_PROPERTY"
    STUDENT_STATEMENT = "STUDENT_STATEMENT"
    OTHER = "OTHER"


class SupportDirection(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class EvidenceStrength(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    ANECDOTAL = "ANECDOTAL"


class EvidenceLocation(MawhibaModel):
    """Where inside the source the evidence sits. Enables 'why did you say that?'."""

    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    quote_or_extract: str | None = None
    line_range: str | None = None


class EvidenceRecord(MawhibaModel):
    """An atomic, source-anchored statement (7.2).

    Every evidence record must point at a source -- there is no free-floating
    evidence in this system.
    """

    evidence_id: str = Field(pattern=r"^E-\d{3,}$", examples=["E-001"])
    source_id: str = Field(
        pattern=r"^SRC-\d{3,}$",
        description="Mandatory: evidence without a source is not evidence (2.2).",
    )
    evidence_type: EvidenceType
    statement: str = Field(min_length=1)
    support_direction: SupportDirection = SupportDirection.NEUTRAL
    strength: EvidenceStrength = EvidenceStrength.WEAK
    location: EvidenceLocation = Field(default_factory=EvidenceLocation)
    verified: bool = Field(
        default=False,
        description="True only after the source metadata/content was checked (N06A).",
    )
    verified_at: UtcDatetime | None = None
    extracted_by_node: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _verified_requires_anchor(self) -> EvidenceRecord:
        if self.verified:
            loc = self.location
            if not (loc.quote_or_extract or loc.section or loc.page is not None):
                raise ValueError(
                    "verified evidence must carry a location anchor "
                    "(quote_or_extract, section, or page)"
                )
        if self.verified_at is not None and not self.verified:
            raise ValueError("verified_at set while verified is False")
        if self.strength == EvidenceStrength.STRONG and not self.verified:
            raise ValueError("STRONG evidence requires verified=True (2.2)")
        return self
