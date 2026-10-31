"""Model-facing Phase 3B DTOs. The untrusted boundary.

Deliberately narrow, in the Phase 3A ``dto.py`` shape. Every field is a label, an
enum choice written as a string, or a pointer at exact submission text. There is
no ``posture``, ``score``, ``verdict``, ``result value``, ``confidence``, free-text
metric, baseline, condition or id field, so the model cannot volunteer a
conclusion even when the submission tries to elicit one. ``extra="forbid"``
rejects a schema escape outright. Code decides what each pointer means (ADR-023).

Only segmentation and protocol extraction point at new submission text; the
applicability and linkage calls cite labels (E1, T1, V1, K1, ...) of records
code already verified, so they can never introduce an excerpt or an id. These
DTOs are transient: none is ever written to a checkpoint.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class SpanDTO(ModelFacingModel):
    excerpt: str = Field(description="Copied character for character from the submission.")
    start: int | None = Field(default=None, description="Offset in the submission. Only when the excerpt repeats.")
    end: int | None = Field(default=None, description="End offset. Only when the excerpt repeats.")
    occurrence: int | None = Field(default=None, description="1-based occurrence. Only when the excerpt repeats.")


# -- segmentation ------------------------------------------------------------------------


class ExperimentSegmentDTO(ModelFacingModel):
    label: str = Field(description="X1, X2, ... in document order.")
    defining_excerpts: list[SpanDTO] = Field(default_factory=list)
    revision_of: str | None = Field(default=None, description="The label of the earlier protocol this one changes.")
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class ResultSpanDTO(ModelFacingModel):
    kind: str = Field(description="A result kind shown.")
    span: SpanDTO


class SegmentationResponse(ModelFacingModel):
    experiments: list[ExperimentSegmentDTO] = Field(default_factory=list)
    results: list[ResultSpanDTO] = Field(default_factory=list)


# -- protocol extraction -----------------------------------------------------------------


class ProtocolRequirementDTO(ModelFacingModel):
    kind: str = Field(description="Exactly a requirement kind shown.")
    documentation: str = Field(
        description="EXPLICITLY_DOCUMENTED, PARTIALLY_DOCUMENTED or CONFLICTING_DOCUMENTATION."
    )
    adequacy: str = Field(
        description="ADEQUATELY_SPECIFIED_FOR_REVIEW, PARTIALLY_SPECIFIED, PROTOCOL_RISK_IDENTIFIED or "
        "CONFLICTING_PROTOCOL."
    )
    excerpts: list[SpanDTO] = Field(default_factory=list)
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class ProtocolExtractionResponse(ModelFacingModel):
    experiment_type: str = Field(default="UNKNOWN", description="Exactly an experiment type shown, or UNKNOWN.")
    execution_status: str = Field(
        default="EXECUTION_STATUS_NOT_DOCUMENTED",
        description="PLANNED_ONLY, EXECUTION_DESCRIBED or EXECUTION_STATUS_NOT_DOCUMENTED.",
    )
    owner_track: str | None = Field(default=None, description="SCIENTIFIC_RESEARCH or ENGINEERING. Two tracks only.")
    owner_excerpts: list[SpanDTO] = Field(default_factory=list)
    requirements: list[ProtocolRequirementDTO] = Field(default_factory=list)


# -- conditional applicability -----------------------------------------------------------


class ApplicabilityJudgmentDTO(ModelFacingModel):
    kind: str = Field(description="Exactly a conditional requirement kind shown.")
    fired_triggers: list[str] = Field(default_factory=list, description="A subset of the triggers listed.")
    excerpts: list[str] = Field(default_factory=list, description="Excerpt labels, e.g. E1.")
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class ApplicabilityResponse(ModelFacingModel):
    judgments: list[ApplicabilityJudgmentDTO] = Field(default_factory=list)


# -- target linkage ----------------------------------------------------------------------


class MeasurementDTO(ModelFacingModel):
    method: str | None = None
    metric: str | None = None
    unit: str | None = None
    success_criterion: str | None = None
    alignment: str = "ALIGNMENT_UNRESOLVED"
    phase2j_metric_match: str = "MATCH_UNRESOLVED"
    criterion_timing: str = "TIMING_NOT_DOCUMENTED"


class ComparabilityDTO(ModelFacingModel):
    property: str
    status: str
    excerpts: list[str] = Field(default_factory=list)


class BaselineDTO(ModelFacingModel):
    excerpts: list[str] = Field(default_factory=list, description="Excerpt labels naming the baseline.")
    relevance: str = "RELEVANCE_UNRESOLVED"
    context: list[str] = Field(default_factory=list)
    rationale_excerpts: list[str] = Field(default_factory=list)
    phase2j_baseline_match: str = "MATCH_UNRESOLVED"
    execution_status: str = "EXECUTION_STATUS_NOT_DOCUMENTED"
    comparability: list[ComparabilityDTO] = Field(default_factory=list)


class TargetJudgmentDTO(ModelFacingModel):
    target: str = Field(description="T1, ... or V1, ...")
    relation: str
    excerpts: list[str] = Field(default_factory=list)
    measurement: MeasurementDTO | None = None
    baseline: BaselineDTO | None = None
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class ConditionJudgmentDTO(ModelFacingModel):
    condition: str = Field(description="Condition label, e.g. K1.")
    status: str
    excerpts: list[str] = Field(default_factory=list)


class LinkageResponse(ModelFacingModel):
    targets: list[TargetJudgmentDTO] = Field(default_factory=list)
    conditions: list[ConditionJudgmentDTO] = Field(default_factory=list)


__all__ = [
    "ApplicabilityJudgmentDTO",
    "ApplicabilityResponse",
    "BaselineDTO",
    "ComparabilityDTO",
    "ConditionJudgmentDTO",
    "ExperimentSegmentDTO",
    "LinkageResponse",
    "MeasurementDTO",
    "ProtocolExtractionResponse",
    "ProtocolRequirementDTO",
    "ResultSpanDTO",
    "SegmentationResponse",
    "SpanDTO",
    "TargetJudgmentDTO",
]
