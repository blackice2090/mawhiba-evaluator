"""Model-facing evidence extraction DTOs. The untrusted boundary.

These are the only shapes the extractor asks a model to produce. They are
deliberately narrow: a field that does not exist cannot be filled in wrongly.

What is absent matters as much as what is present. There is no ``supports``,
no ``contradicts``, no ``claim_id``, no ``score``, no ``confidence`` and no
``reasoning`` field, so a model cannot volunteer a claim judgement, a project
score or its chain of thought even if the source text tries to elicit one
(§23, §33).

``claimed_start`` and ``claimed_end`` are accepted because a model will offer
them anyway and recording what it said is better than discarding it -- but they
are audit data, never provenance. Verification derives the real offsets.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class CandidateNumericObservation(ModelFacingModel):
    """A number the excerpt states, copied as written."""

    raw_text: str = Field(
        description="The number exactly as it appears in the excerpt, with its "
        "unit and any sign or operator, e.g. '92.3%', '5 ms', 'n=40'."
    )
    value: float | None = Field(
        default=None, description="The numeric value, or null. Never rounded or converted."
    )
    unit: str | None = Field(
        default=None, description="The unit exactly as written, e.g. 'ms', '%'. Never converted."
    )
    metric_name: str | None = Field(
        default=None, description="What the number measures, if the excerpt names it."
    )
    comparison_operator: str | None = Field(
        default=None,
        description="One of EQUALS, APPROXIMATELY, GREATER_THAN, GREATER_OR_EQUAL, "
        "LESS_THAN, LESS_OR_EQUAL, RANGE, UNKNOWN.",
    )
    uncertainty: str | None = Field(
        default=None,
        description="A confidence interval or error, copied verbatim, e.g. "
        "'95% CI 1.2-3.4'. Null unless the excerpt states it.",
    )
    sample_size: int | None = Field(
        default=None, description="Only when the excerpt explicitly states a sample size."
    )


class CandidateEvidenceItem(ModelFacingModel):
    """One proposed piece of evidence. Untrusted until code verifies it."""

    evidence_type: str = Field(
        description="One of the evidence type values listed in the instructions. "
        "Use OTHER rather than guessing a more specific category."
    )
    verbatim_excerpt: str = Field(
        description="Copied character-for-character from the source content. An "
        "excerpt that is not literally present is rejected."
    )
    claimed_start: int | None = Field(
        default=None, description="Where you believe the excerpt starts. Optional."
    )
    claimed_end: int | None = Field(default=None, description="Optional.")
    section_hint: str | None = Field(
        default=None, description="Section label, if the content states one."
    )
    numeric_observations: list[CandidateNumericObservation] = Field(
        default_factory=list,
        description="Numbers stated inside the excerpt. Omit if none.",
    )
    interpretation: str | None = Field(
        default=None,
        description="One short neutral sentence describing what the excerpt "
        "states. Advisory only; it never replaces the excerpt.",
    )


class EvidenceExtraction(ModelFacingModel):
    """The extractor's whole response. An empty list is a valid answer."""

    evidence: list[CandidateEvidenceItem] = Field(
        default_factory=list,
        description="Evidence found in the supplied content. Return an empty "
        "list when the content contains nothing relevant.",
    )


__all__ = [
    "CandidateEvidenceItem",
    "CandidateNumericObservation",
    "EvidenceExtraction",
]
