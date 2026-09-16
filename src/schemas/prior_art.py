"""PriorArtRecord -- architecture 7.4, 12 (Closest Prior Art Engine), 13 (Novelty)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import (
    SOURCE_ID_PATTERN,
    BranchStatus,
    ConfidenceLevel,
    EvaluationStatus,
    MawhibaModel,
    NoveltyLevel,
    ResearchBranch,
    Severity,
    UnitInterval,
)


class PriorArtKind(StrEnum):
    ACADEMIC = "ACADEMIC"
    PATENT = "PATENT"
    PRODUCT = "PRODUCT"
    OPEN_SOURCE = "OPEN_SOURCE"
    STANDARD = "STANDARD"
    OTHER = "OTHER"


class SimilarityDimensions(MawhibaModel):
    """Section 12: novelty is judged per-dimension, not by 'is there the same project?'.

    Every dimension is optional -- ``None`` means "not assessed", which is
    different from 0.0 ("assessed, no similarity").
    """

    problem: UnitInterval | None = None
    method: UnitInterval | None = None
    architecture: UnitInterval | None = None
    hardware: UnitInterval | None = None
    algorithm: UnitInterval | None = None
    deployment: UnitInterval | None = None
    evaluation: UnitInterval | None = None
    dataset: UnitInterval | None = None
    technical_principle: UnitInterval | None = None
    sensor_configuration: UnitInterval | None = None

    @property
    def assessed_dimensions(self) -> dict[str, float]:
        return {
            name: value
            for name, value in self.model_dump().items()
            if value is not None
        }

    @property
    def max_similarity(self) -> float | None:
        assessed = self.assessed_dimensions
        return max(assessed.values()) if assessed else None


class PriorArtRecord(MawhibaModel):
    """One closest-prior-art candidate anchored to a source (7.4)."""

    prior_art_id: str = Field(pattern=r"^PA-\d{3,}$", examples=["PA-001"])
    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    kind: PriorArtKind
    title: str | None = None
    similarity_dimensions: SimilarityDimensions = Field(
        default_factory=SimilarityDimensions
    )
    shared_features: list[str] = Field(default_factory=list)
    different_features: list[str] = Field(default_factory=list)
    novelty_threat: Severity = Field(
        default=Severity.LOW,
        description="How strongly this work threatens the project's novelty claim.",
    )
    rank: int | None = Field(
        default=None, ge=1, description="Position in the Top-K closest list (12)."
    )
    evidence_ids: list[str] = Field(default_factory=list)
    review_notes: str | None = None

    @model_validator(mode="after")
    def _threat_needs_assessment(self) -> PriorArtRecord:
        if self.novelty_threat in (Severity.CRITICAL, Severity.HIGH):
            if not self.similarity_dimensions.assessed_dimensions:
                raise ValueError(
                    "a HIGH/CRITICAL novelty threat requires at least one assessed "
                    "similarity dimension (12)"
                )
        return self


class BranchCoverage(MawhibaModel):
    """Per-branch search coverage, consumed by the novelty trust gate (13, 27)."""

    branch: ResearchBranch
    required: bool = True
    status: BranchStatus = BranchStatus.NOT_STARTED
    query_ids: list[str] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    coverage: UnitInterval = 0.0
    failure_reason: str | None = None

    @model_validator(mode="after")
    def _consistency(self) -> BranchCoverage:
        if self.status == BranchStatus.COMPLETED and not self.query_ids:
            # 27: a branch is never complete on the strength of zero queries.
            raise ValueError("a COMPLETED branch must reference at least one query_id")
        if self.status == BranchStatus.FAILED and not self.failure_reason:
            raise ValueError("a FAILED branch must state a failure_reason")
        if self.required and self.status == BranchStatus.NOT_REQUIRED:
            raise ValueError("a required branch cannot have status NOT_REQUIRED")
        return self

    @property
    def is_satisfied(self) -> bool:
        """Satisfied = completed, or legitimately not required."""
        return self.status in (BranchStatus.COMPLETED, BranchStatus.NOT_REQUIRED) or (
            not self.required
        )


class NoveltyAssessment(MawhibaModel):
    """Section 13 novelty engine output. Levels 4/5 have extra preconditions that
    the trust gate -- not this schema -- enforces."""

    level: NoveltyLevel | None = None
    status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    confidence: UnitInterval | None = None
    confidence_level: ConfidenceLevel | None = None
    rationale: str | None = None
    closest_prior_art_ids: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    branch_coverage: list[BranchCoverage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _level_requires_evaluation(self) -> NoveltyAssessment:
        if self.level is not None and self.status == EvaluationStatus.NOT_EVALUATED:
            raise ValueError("a novelty level cannot be set while status=NOT_EVALUATED")
        if self.status == EvaluationStatus.FINAL and self.level is None:
            raise ValueError("status=FINAL requires a novelty level")
        if (
            self.status == EvaluationStatus.FINAL
            and self.level is not None
            and self.level >= 4
            and not self.closest_prior_art_ids
        ):
            raise ValueError(
                "a FINAL novelty level of 4/5 requires identified closest prior art (13)"
            )
        branches = [c.branch for c in self.branch_coverage]
        if len(set(branches)) != len(branches):
            raise ValueError("branch_coverage must have one entry per branch")
        return self

    def unsatisfied_required_branches(self) -> list[ResearchBranch]:
        return [c.branch for c in self.branch_coverage if c.required and not c.is_satisfied]


class GapAssessment(MawhibaModel):
    """Section 14 Gap Engine. Unproven gaps stay GAP_NOT_ESTABLISHED via status."""

    research_gap: str | None = None
    engineering_gap: str | None = None
    status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    strength: ConfidenceLevel | None = None
    confidence: UnitInterval | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _final_gap_needs_statement_and_evidence(self) -> GapAssessment:
        if self.status == EvaluationStatus.FINAL:
            if not (self.research_gap or self.engineering_gap):
                raise ValueError("a FINAL gap assessment requires a stated gap (14)")
            if not self.evidence_ids:
                raise ValueError("a FINAL gap assessment requires evidence_ids (14)")
        return self

    @property
    def is_established(self) -> bool:
        return self.status == EvaluationStatus.FINAL
