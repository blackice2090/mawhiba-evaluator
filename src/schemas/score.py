"""ScoreRecord -- architecture 7.6 and 20 (Deterministic Scoring Engine).

The LLM never sums a score. It produces structured per-axis assessments and
Python computes the total; these schemas are the contract between the two.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import (
    ConfidenceLevel,
    EvaluationStatus,
    MawhibaModel,
    UnitInterval,
    UtcDatetime,
    utc_now,
)


class RubricKind(StrEnum):
    """Section 20 rubric priority. OFFICIAL only when verified official weights exist."""

    OFFICIAL = "OFFICIAL"
    ADVISORY = "ADVISORY"


class ScoreAxisName(StrEnum):
    """Advisory v1 axes (20). Official rubrics may define their own axis names,
    which is why ScoreAxis.axis is a plain string."""

    PROBLEM_AND_IMPORTANCE = "problem_and_importance"
    SCIENTIFIC_TECHNICAL_BASE = "scientific_technical_base"
    LITERATURE = "literature"
    NOVELTY = "novelty"
    GAP = "gap"
    METHODOLOGY = "methodology"
    EXPERIMENTS = "experiments"
    RESULTS = "results"
    JURY_DEFENSIBILITY = "jury_defensibility"


class ScoreAxis(MawhibaModel):
    """One scored axis with its full justification chain (7.6)."""

    axis: str = Field(min_length=1)
    score: float | None = Field(
        default=None,
        ge=0.0,
        description="None means the axis was not scored -- never silently 0.",
    )
    max_score: float = Field(gt=0.0)
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    completeness: UnitInterval = Field(
        default=0.0, description="Fraction of required inputs actually available."
    )
    confidence: ConfidenceLevel = ConfidenceLevel.VERY_LOW
    provisional: bool = True
    status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    rationale: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _score_within_bounds(self) -> ScoreAxis:
        if self.score is not None and self.score > self.max_score:
            raise ValueError(
                f"score {self.score} exceeds max_score {self.max_score} for "
                f"axis '{self.axis}'"
            )
        if self.score is not None and self.status == EvaluationStatus.NOT_EVALUATED:
            raise ValueError("a scored axis cannot have status NOT_EVALUATED")
        if self.status == EvaluationStatus.FINAL:
            if self.provisional:
                raise ValueError("a FINAL axis cannot be marked provisional")
            if self.score is None:
                raise ValueError("a FINAL axis requires a score")
        if self.status == EvaluationStatus.INSUFFICIENT_EVIDENCE and self.score is not None:
            raise ValueError(
                "an INSUFFICIENT_EVIDENCE axis must not carry a score (2.6)"
            )
        if self.confidence == ConfidenceLevel.HIGH and not self.evidence_ids:
            raise ValueError("a HIGH-confidence axis requires evidence_ids (2.2)")
        return self


class ScoreRecord(MawhibaModel):
    """A complete scoring run over one project version (7.6, 20).

    ``total`` stays ``None`` unless every axis is scored -- a partial sum would
    misrepresent the evaluation.
    """

    score_id: str = Field(pattern=r"^SC-\d{3,}$", examples=["SC-001"])
    rubric_version: str = Field(min_length=1, examples=["ADVISORY-V1"])
    rubric_kind: RubricKind = RubricKind.ADVISORY
    official: bool = False
    axes: list[ScoreAxis] = Field(default_factory=list)
    total: float | None = None
    max_total: float | None = None
    status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    computed_at: UtcDatetime = Field(default_factory=utc_now)
    computed_by: str = Field(
        default="deterministic_scoring_engine",
        description="20: Python computes the score, never the LLM.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_totals_and_labels(self) -> ScoreRecord:
        names = [a.axis for a in self.axes]
        if len(set(names)) != len(names):
            raise ValueError("axis names must be unique within a ScoreRecord")

        # Official vs advisory must never disagree (7.6 keeps them as two fields).
        if self.official != (self.rubric_kind == RubricKind.OFFICIAL):
            raise ValueError(
                "official flag must match rubric_kind "
                f"(official={self.official}, rubric_kind={self.rubric_kind.value})"
            )
        expected_prefix = "OFFICIAL" if self.official else "ADVISORY"
        if not self.rubric_version.upper().startswith(expected_prefix):
            raise ValueError(
                f"rubric_version '{self.rubric_version}' must start with "
                f"'{expected_prefix}' to match the official flag"
            )

        computed_max = sum(a.max_score for a in self.axes) if self.axes else None
        if self.max_total is not None and computed_max is not None:
            if abs(self.max_total - computed_max) > 1e-9:
                raise ValueError(
                    f"max_total {self.max_total} != sum of axis max_scores {computed_max}"
                )

        scored = [a for a in self.axes if a.score is not None]
        if self.total is not None:
            if len(scored) != len(self.axes) or not self.axes:
                raise ValueError(
                    "total may only be set when every axis carries a score; "
                    "leave it None for a partial evaluation"
                )
            expected = sum(a.score for a in scored)
            if abs(self.total - expected) > 1e-9:
                raise ValueError(
                    f"total {self.total} does not equal the sum of axis scores {expected}"
                )
            if computed_max is not None and self.total > computed_max + 1e-9:
                raise ValueError(f"total {self.total} exceeds max total {computed_max}")

        if self.status == EvaluationStatus.FINAL:
            if self.total is None:
                raise ValueError("a FINAL ScoreRecord requires a total")
            if any(a.provisional for a in self.axes):
                raise ValueError("a FINAL ScoreRecord cannot contain provisional axes")
        return self

    @property
    def is_final(self) -> bool:
        return self.status == EvaluationStatus.FINAL

    def axis(self, name: str) -> ScoreAxis | None:
        return next((a for a in self.axes if a.axis == name), None)
