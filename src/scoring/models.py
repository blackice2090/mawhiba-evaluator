"""Rubric definitions -- architecture 20 (Deterministic Scoring Engine).

Phase 0 scope: the rubric *contract* and the arithmetic invariants only. The
engine that fills axis scores from node assessments lands in Phase 1; what is
guaranteed here is that no score can ever exceed its axis maximum and that
totals are computed, never asserted.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from src.schemas.common import (
    ConfidenceLevel,
    EvaluationStatus,
    MawhibaModel,
    UnitInterval,
)
from src.schemas.score import (
    RubricKind,
    ScoreAxis,
    ScoreAxisName,
    ScoreRecord,
)


class RubricAxisDefinition(MawhibaModel):
    """One axis of a rubric: its weight and what it needs to be scorable."""

    axis: str = Field(min_length=1)
    max_score: float = Field(gt=0.0)
    description: str = ""
    required_inputs: list[str] = Field(
        default_factory=list,
        description="State paths that must be present before the axis is scorable.",
    )


class Rubric(MawhibaModel):
    """A versioned rubric. OFFICIAL rubrics may only be built from verified
    official weights (2.4, 20); otherwise ADVISORY is used and labelled as such."""

    version: str = Field(min_length=1)
    kind: RubricKind
    axes: list[RubricAxisDefinition] = Field(min_length=1)
    source_id: str | None = Field(
        default=None,
        pattern=r"^SRC-\d{3,}$",
        description="Required for OFFICIAL rubrics: the official source it came from.",
    )

    @model_validator(mode="after")
    def _validate(self) -> Rubric:
        names = [a.axis for a in self.axes]
        if len(set(names)) != len(names):
            raise ValueError("rubric axis names must be unique")
        expected_prefix = "OFFICIAL" if self.kind == RubricKind.OFFICIAL else "ADVISORY"
        if not self.version.upper().startswith(expected_prefix):
            raise ValueError(
                f"rubric version '{self.version}' must start with '{expected_prefix}'"
            )
        if self.kind == RubricKind.OFFICIAL and self.source_id is None:
            raise ValueError(
                "an OFFICIAL rubric requires a source_id proving the official "
                "weights were retrieved, never invented (2.4 / N03)"
            )
        return self

    @property
    def max_total(self) -> float:
        return sum(a.max_score for a in self.axes)

    def axis(self, name: str) -> RubricAxisDefinition | None:
        return next((a for a in self.axes if a.axis == name), None)

    def blank_score_record(self, score_id: str) -> ScoreRecord:
        """Build an un-evaluated ScoreRecord shaped by this rubric.

        Axes start with ``score=None`` and ``NOT_EVALUATED`` -- never 0 -- so a
        missing evaluation is never mistaken for a zero (2.1).
        """
        return ScoreRecord(
            score_id=score_id,
            rubric_version=self.version,
            rubric_kind=self.kind,
            official=self.kind == RubricKind.OFFICIAL,
            max_total=self.max_total,
            status=EvaluationStatus.NOT_EVALUATED,
            axes=[
                ScoreAxis(
                    axis=a.axis,
                    score=None,
                    max_score=a.max_score,
                    completeness=0.0,
                    confidence=ConfidenceLevel.VERY_LOW,
                    provisional=True,
                    status=EvaluationStatus.NOT_EVALUATED,
                    missing_inputs=list(a.required_inputs),
                )
                for a in self.axes
            ],
        )


ADVISORY_RUBRIC_V1 = Rubric(
    version="ADVISORY-V1",
    kind=RubricKind.ADVISORY,
    axes=[
        RubricAxisDefinition(
            axis=ScoreAxisName.PROBLEM_AND_IMPORTANCE.value,
            max_score=10,
            description="Is the problem real, sized, and measurable? (N04)",
            required_inputs=["problem.statement", "problem.validation_status"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.SCIENTIFIC_TECHNICAL_BASE.value,
            max_score=10,
            description="Soundness of the underlying technical principle.",
            required_inputs=["solution.technical_principle"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.LITERATURE.value,
            max_score=10,
            description="Breadth and quality of retrieved, verified sources.",
            required_inputs=["sources"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.NOVELTY.value,
            max_score=15,
            description="Novelty level backed by closest prior art (13).",
            required_inputs=["novelty.level", "prior_art"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.GAP.value,
            max_score=10,
            description="An established, evidence-backed gap (14).",
            required_inputs=["gap.status"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.METHODOLOGY.value,
            max_score=15,
            description="Methodology fit for the project type (N12).",
            required_inputs=["methodology.review_status"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.EXPERIMENTS.value,
            max_score=15,
            description="Do the experiments test the claim or only the device? (N13)",
            required_inputs=["experiments"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.RESULTS.value,
            max_score=10,
            description="Results traceable to measurements and baselines.",
            required_inputs=["results"],
        ),
        RubricAxisDefinition(
            axis=ScoreAxisName.JURY_DEFENSIBILITY.value,
            max_score=5,
            description="Can the student defend the work under questioning?",
            required_inputs=["claims"],
        ),
    ],
)
"""Advisory v1 rubric (20). Total = 100."""

ADVISORY_V1_MAX_TOTAL: float = 100.0


class ScoringInput(MawhibaModel):
    """What a node hands the deterministic scorer for one axis.

    The LLM supplies the qualitative assessment; Python decides the number and
    whether the axis may leave provisional status (20).
    """

    axis: str = Field(min_length=1)
    raw_assessment: str = Field(min_length=1)
    suggested_fraction: UnitInterval | None = Field(
        default=None,
        description="Model's suggested fraction of max_score. Advisory only; the "
        "engine may clamp or refuse it.",
    )
    completeness: UnitInterval = 0.0
    confidence: ConfidenceLevel = ConfidenceLevel.VERY_LOW
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_confident_score_without_evidence(self) -> ScoringInput:
        if self.suggested_fraction is not None and not self.evidence_ids:
            if self.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM):
                raise ValueError(
                    "a MEDIUM/HIGH confidence axis assessment requires evidence_ids (2.2)"
                )
        return self
