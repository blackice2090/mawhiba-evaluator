"""Model-facing Phase 3A DTOs. The untrusted boundary.

Deliberately narrow, in the Phase 2J ``dto.py`` shape. Every field is a label, an
enum choice written as a string, or a pointer at exact submission text. There is
no ``posture``, ``score``, ``verdict``, ``result``, ``confidence`` or free-text
metric/baseline/condition field, so the model cannot volunteer a conclusion even
when the submission tries to elicit one. ``extra="forbid"`` rejects a schema
escape outright. Code decides what each pointer means (ADR-022).

``start``/``end``/``occurrence`` exist ONLY to disambiguate an excerpt that occurs
more than once; code validates them against the exact submission text. These
DTOs are transient: none is ever written to a checkpoint.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class SubmissionSpanDTO(ModelFacingModel):
    excerpt: str = Field(description="Copied character for character from the submission.")
    start: int | None = Field(default=None, description="Offset in the submission. Only when the excerpt repeats.")
    end: int | None = Field(default=None, description="End offset. Only when the excerpt repeats.")
    occurrence: int | None = Field(default=None, description="1-based occurrence. Only when the excerpt repeats.")
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class OverlayJudgmentDTO(ModelFacingModel):
    overlay: str = Field(description="AI_ML or SOFTWARE_SYSTEMS.")
    materiality: str = Field(
        description="MATERIAL_TO_TARGET, IMPLEMENTATION_TOOL_ONLY, MATERIALITY_UNRESOLVED or NO_METHODOLOGY_RELEVANCE."
    )
    claims: list[str] = Field(default_factory=list, description="Claim labels, e.g. C1.")
    hypotheses: list[str] = Field(default_factory=list, description="Hypothesis labels, e.g. H1.")
    excerpts: list[SubmissionSpanDTO] = Field(default_factory=list)
    owner_track: str | None = Field(
        default=None, description="SCIENTIFIC_RESEARCH or ENGINEERING. Two-track projects only."
    )
    served_tracks: list[str] = Field(default_factory=list)


class OverlayAssessmentResponse(ModelFacingModel):
    overlays: list[OverlayJudgmentDTO] = Field(default_factory=list)


class ExcerptDTO(SubmissionSpanDTO):
    statement_mode: str = Field(
        default="MODE_NOT_DETERMINED", description="PLANNED, DESCRIBED_AS_EXECUTED or MODE_NOT_DETERMINED."
    )


class RequirementEvidenceDTO(ModelFacingModel):
    kind: str = Field(description="Exactly a requirement kind shown.")
    documentation: str = Field(
        description="EXPLICITLY_DOCUMENTED, PARTIALLY_DOCUMENTED or CONFLICTING_DOCUMENTATION."
    )
    adequacy: str = Field(
        description="ADEQUATELY_SPECIFIED_FOR_REVIEW, PARTIALLY_SPECIFIED, DESIGN_RISK_IDENTIFIED or "
        "CONFLICTING_DESIGN."
    )
    excerpts: list[ExcerptDTO] = Field(default_factory=list)


class EvidenceExtractionResponse(ModelFacingModel):
    requirements: list[RequirementEvidenceDTO] = Field(default_factory=list)


class ApplicabilityJudgmentDTO(ModelFacingModel):
    kind: str = Field(description="Exactly a conditional requirement kind shown.")
    fired_triggers: list[str] = Field(
        default_factory=list, description="A subset of the triggers listed for that kind."
    )
    excerpt: SubmissionSpanDTO | None = None


class ApplicabilityResponse(ModelFacingModel):
    judgments: list[ApplicabilityJudgmentDTO] = Field(default_factory=list)


class MetricJudgmentDTO(ModelFacingModel):
    target: str = Field(description="T1 or a hypothesis label G1, ...")
    status: str = Field(
        description="ALIGNED_WITHIN_BOUND_INPUT, METRIC_TARGET_MISMATCH, METRIC_NOT_DEFINED or "
        "TARGET_NOT_MEASURABLE_AS_STATED."
    )
    outcome: SubmissionSpanDTO | None = None
    metric_excerpt: SubmissionSpanDTO | None = None


class BaselineJudgmentDTO(ModelFacingModel):
    target: str
    baseline: SubmissionSpanDTO | None = None
    relevance: str = Field(
        default="RELEVANCE_UNRESOLVED",
        description="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT, RELEVANCE_UNRESOLVED or NOT_RELEVANT_TO_TARGET.",
    )
    context: list[str] = Field(default_factory=list)
    rationale_excerpt: SubmissionSpanDTO | None = None


class MetricBaselineResponse(ModelFacingModel):
    metrics: list[MetricJudgmentDTO] = Field(default_factory=list)
    baselines: list[BaselineJudgmentDTO] = Field(default_factory=list)


class CoverageJudgmentDTO(ModelFacingModel):
    target: str = Field(description="T1 or a hypothesis label G1, ...")
    track: str = Field(description="SCIENTIFIC_RESEARCH or ENGINEERING.")
    relation: str = Field(
        description="DIRECTLY_TESTS_TARGET, PARTIALLY_TESTS_TARGET, RELEVANT_BUT_NOT_TESTING, DOES_NOT_TEST_TARGET "
        "or INSUFFICIENT_LINKAGE_EVIDENCE."
    )
    excerpts: list[str] = Field(default_factory=list, description="Excerpt labels, e.g. E1.")
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class ConditionJudgmentDTO(ModelFacingModel):
    condition: str = Field(description="Condition label, e.g. K1.")
    status: str = Field(
        description="ADDRESSED_IN_DESIGN, PARTIALLY_ADDRESSED or NOT_ADDRESSED_IN_BOUND_INPUT."
    )
    excerpts: list[str] = Field(default_factory=list)
    rationale: str | None = None


class TargetLinkageResponse(ModelFacingModel):
    coverage: list[CoverageJudgmentDTO] = Field(default_factory=list)
    conditions: list[ConditionJudgmentDTO] = Field(default_factory=list)


__all__ = [
    "ApplicabilityJudgmentDTO",
    "ApplicabilityResponse",
    "BaselineJudgmentDTO",
    "ConditionJudgmentDTO",
    "CoverageJudgmentDTO",
    "EvidenceExtractionResponse",
    "ExcerptDTO",
    "MetricBaselineResponse",
    "MetricJudgmentDTO",
    "OverlayAssessmentResponse",
    "OverlayJudgmentDTO",
    "RequirementEvidenceDTO",
    "SubmissionSpanDTO",
    "TargetLinkageResponse",
]
