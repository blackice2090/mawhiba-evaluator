"""Model-facing Phase 2J DTOs. The untrusted boundary.

Deliberately narrow, following the Phase 2C/2D/2I dto.py pattern. There is no
``gap``, ``score``, ``verdict``, ``confidence``, ``novel``, ``posture`` and no
numeric target anywhere here, so the model cannot volunteer a gap conclusion or
a threshold even when claim or source text tries to elicit one. All it can do
is point at exact source text and name a limitation form, a facet, a condition
dimension, a linkage relation or a counterevidence kind. Code decides what
those pointers mean (ADR-021).

Optional ``start``/``end``/``occurrence`` exist ONLY to disambiguate an excerpt
that occurs more than once. They are never trusted: code validates them
against the exact text, and a repeated excerpt without a valid disambiguator is
rejected as ambiguous rather than bound to its first occurrence.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class SpanDTO(ModelFacingModel):
    text: str = Field(description="The source text label, e.g. T1.")
    excerpt: str = Field(description="Copied character for character from that text.")
    start: int | None = Field(default=None, description="Offset in that text. Only when the excerpt repeats.")
    end: int | None = Field(default=None, description="End offset. Only when the excerpt repeats.")
    occurrence: int | None = Field(default=None, description="1-based occurrence. Only when the excerpt repeats.")
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class CapabilityDTO(SpanDTO):
    label: str = Field(description="C1, C2, ...")


class ConditionDTO(SpanDTO):
    dimension: str = Field(
        description="POPULATION, ENVIRONMENT, OPERATING_REGIME, DATASET_DOMAIN, HARDWARE, RESOURCE, SCALE, "
        "GEOGRAPHY or LANGUAGE."
    )


class LimitationDTO(SpanDTO):
    label: str = Field(description="L1, L2, ...")
    limitation_type: str = Field(
        description="EXPLICIT_LIMITATION, MEASURED_SHORTFALL, SCOPE_RESTRICTION, UNMET_REQUIREMENT, "
        "REPORTED_FAILURE_MODE, TRADEOFF or UNRESOLVED_QUESTION."
    )
    facet: str = Field(description="RESEARCH or ENGINEERING. Exactly one.")
    condition_dimensions: list[str] = Field(default_factory=list)
    conditions: list[ConditionDTO] = Field(default_factory=list)


class ValidationDTO(ModelFacingModel):
    metric_source: str = Field(description="CLAIM, or a limitation label such as L1.")
    metric: str = Field(description="Copied character for character from the named source.")
    metric_start: int | None = None
    metric_occurrence: int | None = None
    baseline_source: str | None = Field(default=None, description="CLAIM, or a capability label such as C1.")
    baseline: str | None = None
    baseline_start: int | None = None
    baseline_occurrence: int | None = None


class GapExtractionResponse(ModelFacingModel):
    capabilities: list[CapabilityDTO] = Field(default_factory=list)
    limitations: list[LimitationDTO] = Field(default_factory=list)
    validation: ValidationDTO | None = None
    proposed_kind: str | None = Field(default=None, description="RESEARCH, ENGINEERING or HYBRID. Advisory only.")


class LinkJudgmentDTO(ModelFacingModel):
    feature: str = Field(description="The feature label, e.g. F1.")
    limitation: str = Field(description="The limitation label, e.g. L1.")
    relation: str = Field(
        description="ADDRESSES_LIMITATION, PARTIALLY_ADDRESSES_LIMITATION, RELEVANT_BUT_NOT_ADDRESSING, "
        "UNRELATED or INSUFFICIENT_LINKAGE_EVIDENCE."
    )
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory, never persisted.")


class LinkageResponse(ModelFacingModel):
    judgments: list[LinkJudgmentDTO] = Field(default_factory=list)


class CounterEvidenceDTO(SpanDTO):
    kind: str = Field(description="LIMITATION_ADDRESSED, LIMITATION_NOT_PRESENT or DIFFERENTIATION_UNRELATED.")
    condition_match: str = Field(description="SAME_CONDITION, DIFFERENT_CONDITION or CONDITION_UNKNOWN.")


class CounterEvidenceResponse(ModelFacingModel):
    items: list[CounterEvidenceDTO] = Field(default_factory=list)


__all__ = [
    "CapabilityDTO",
    "ConditionDTO",
    "CounterEvidenceDTO",
    "CounterEvidenceResponse",
    "GapExtractionResponse",
    "LimitationDTO",
    "LinkJudgmentDTO",
    "LinkageResponse",
    "SpanDTO",
    "ValidationDTO",
]
