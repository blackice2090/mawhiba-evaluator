"""Model-facing Phase 2I DTOs. The untrusted boundary.

Deliberately narrow, following the Phase 2C/2D dto.py pattern. There is no
``novel``, no ``score``, no ``verdict``, no ``confidence`` and no overall
relation anywhere here, so the model cannot volunteer a novelty conclusion or a
score even when claim or candidate text tries to elicit one. The only thing a
comparison response can say is a per-feature relation with quoted evidence.

Optional ``start``/``end``/``occurrence`` exist ONLY to disambiguate an excerpt
that occurs more than once. They are never trusted: code validates them
against the exact text, and a repeated excerpt without a valid disambiguator is
rejected as ambiguous rather than bound to its first occurrence.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class ProposedFeatureDTO(ModelFacingModel):
    text: str = Field(description="Copied character for character from the claim.")
    feature_type: str = Field(
        description="COMPONENT, FUNCTION, MECHANISM, RELATIONSHIP, SEQUENCE, "
        "CONSTRAINT or OTHER_TECHNICAL_FEATURE."
    )
    start: int | None = Field(
        default=None, description="Character offset in the claim. Only needed when the text repeats."
    )
    occurrence: int | None = Field(
        default=None, description="1-based occurrence of the text in the claim. Only when it repeats."
    )
    rationale: str | None = Field(default=None, description="One short neutral sentence.")


class FeatureExtractionResponse(ModelFacingModel):
    features: list[ProposedFeatureDTO] = Field(default_factory=list)


class EvidenceDTO(ModelFacingModel):
    text: str = Field(description="The candidate text label, e.g. T1.")
    excerpt: str = Field(description="Copied character for character from that text.")
    start: int | None = Field(default=None, description="Offset in that text. Only when the excerpt repeats.")
    end: int | None = Field(default=None, description="End offset. Only when the excerpt repeats.")
    occurrence: int | None = Field(default=None, description="1-based occurrence. Only when it repeats.")


class FeatureJudgmentDTO(ModelFacingModel):
    feature: str = Field(description="The feature label, e.g. F1.")
    relation: str = Field(
        description="DISCLOSED, PARTIALLY_DISCLOSED, RELATED_CONTEXT, NOT_DISCLOSED, "
        "INSUFFICIENT_SOURCE_TEXT or NOT_COMPARABLE."
    )
    evidence: list[EvidenceDTO] = Field(default_factory=list)
    rationale: str | None = Field(default=None, description="One short neutral sentence. Advisory only.")


class TechnicalComparisonResponse(ModelFacingModel):
    judgments: list[FeatureJudgmentDTO] = Field(default_factory=list)


__all__ = [
    "EvidenceDTO",
    "FeatureExtractionResponse",
    "FeatureJudgmentDTO",
    "ProposedFeatureDTO",
    "TechnicalComparisonResponse",
]
