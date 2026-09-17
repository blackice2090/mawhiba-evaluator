"""Model-facing claim-evidence alignment DTOs. The untrusted boundary.

Deliberately narrow, following the Phase 2C dto.py pattern: there is no
``claim_status``, no ``confidence``, no ``evidence_ids`` and no ``score``
anywhere here, so the model cannot volunteer a claim verdict or a project score
even if the claim or evidence text tries to elicit one.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.extraction import ModelFacingModel


class CandidateComponentDTO(ModelFacingModel):
    """One proposed claim-component judgment. Untrusted until code verifies it."""

    claimed_text: str = Field(
        description="Copied character-for-character from the claim text supplied "
        "to you. An anchor that is not literally present is rejected."
    )
    claimed_start: int | None = Field(
        default=None, description="Where you believe the span starts. Optional."
    )
    claimed_end: int | None = Field(default=None, description="Optional.")
    judgment: str = Field(
        description="One of SUPPORTS, CONTRADICTS, UNRESOLVED, CONTEXTUAL."
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="One or more of the listed reason codes for this component.",
    )
    rationale: str | None = Field(
        default=None,
        description="One short neutral sentence. Advisory only; never evidence.",
    )


class AlignmentClassification(ModelFacingModel):
    """The classifier's whole response for one claim/evidence pair."""

    relation: str = Field(
        description="One of SUPPORTS, CONTRADICTS, PARTIALLY_SUPPORTS, "
        "PARTIALLY_CONTRADICTS, MIXED, CONTEXT_ONLY, INSUFFICIENT, NOT_RELEVANT."
    )
    components: list[CandidateComponentDTO] = Field(
        default_factory=list,
        description="One entry per claim component judged. Empty only for "
        "NOT_RELEVANT.",
    )
    rationale: str | None = Field(
        default=None,
        description="One short neutral sentence summarizing the whole pair. "
        "Advisory only; never evidence.",
    )


__all__ = ["AlignmentClassification", "CandidateComponentDTO"]
