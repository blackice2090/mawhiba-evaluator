"""The LLM extraction step. Proposals only.

This is the one place in Phase 2C where a model speaks, and it is deliberately
the least authoritative module in the phase. It turns a content snapshot into
``EvidenceCandidate`` objects and stops. Whether any of them is evidence is
decided afterwards, by ``verification.py``, from the snapshot text alone.

Reuses the shared invocation layer (`src/llm/invocation.py`) rather than growing
a second retry loop, exactly as Phase 2A.1 established -- transport faults and
truncation are retried to the bound, refusals and parse errors never are.

Nothing here stores chain-of-thought: the model-facing DTO has no field for it,
and only structured candidate fields are carried forward (§33).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallResult, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import EVIDENCE_EXTRACTOR_PROMPT_V1, build_evidence_user_input
from src.llm.provider import StructuredModelProvider
from src.research.evidence.dto import (
    CandidateEvidenceItem,
    CandidateNumericObservation,
    EvidenceExtraction,
)
from src.schemas.common import QueryPurpose
from src.schemas.evidence_extraction import (
    EVIDENCE_EXTRACTOR_VERSION,
    ComparisonOperator,
    EvidenceCandidate,
    ExtractedEvidenceType,
    ExtractionMethod,
    NumericObservation,
    SourceContentSnapshot,
)

logger = logging.getLogger(__name__)

EVIDENCE_EXTRACTOR_PROMPT_VERSION = "EVIDENCE_EXTRACTOR_PROMPT_V1"


@dataclass
class ExtractionOutcome:
    """Candidates from one snapshot, plus how the call went."""

    snapshot: SourceContentSnapshot
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    call: ModelCallResult | None = None
    schema_error: bool = False

    @property
    def succeeded(self) -> bool:
        return self.call is not None and self.call.succeeded


def _evidence_type(raw: str | None) -> ExtractedEvidenceType:
    """Map the model's string onto the enum. Unknown becomes OTHER, not a guess."""
    if not raw:
        return ExtractedEvidenceType.OTHER
    try:
        return ExtractedEvidenceType(raw.strip().upper())
    except ValueError:
        return ExtractedEvidenceType.OTHER


def _operator(raw: str | None) -> ComparisonOperator:
    if not raw:
        return ComparisonOperator.UNKNOWN
    try:
        return ComparisonOperator(raw.strip().upper())
    except ValueError:
        return ComparisonOperator.UNKNOWN


def _numeric(observation: CandidateNumericObservation) -> NumericObservation | None:
    """Carry a proposed number across, unchanged. Verification judges it later."""
    raw = (observation.raw_text or "").strip()
    if not raw:
        return None
    return NumericObservation(
        raw_text=raw,
        value=observation.value,
        unit=(observation.unit or None),
        metric_name=(observation.metric_name or None),
        comparison_operator=_operator(observation.comparison_operator),
        uncertainty=(observation.uncertainty or None),
        sample_size=observation.sample_size,
    )


def _candidate(
    item: CandidateEvidenceItem,
    snapshot: SourceContentSnapshot,
    *,
    model_name: str | None,
    purpose: QueryPurpose | None,
) -> EvidenceCandidate:
    numeric = [n for n in (_numeric(o) for o in item.numeric_observations) if n]
    return EvidenceCandidate(
        source_id=snapshot.source_id,
        content_id=snapshot.content_id,
        evidence_type=_evidence_type(item.evidence_type),
        verbatim_excerpt=item.verbatim_excerpt or "",
        claimed_start=item.claimed_start,
        claimed_end=item.claimed_end,
        section_hint=(item.section_hint or None),
        numeric_observations=numeric,
        candidate_interpretation=(item.interpretation or None),
        extraction_method=ExtractionMethod.LLM_STRUCTURED_EXTRACTION,
        extractor_version=EVIDENCE_EXTRACTOR_VERSION,
        model_name=model_name,
        query_purpose=purpose,
    )


def extract_candidates(
    snapshot: SourceContentSnapshot,
    provider: StructuredModelProvider,
    llm_settings: LLMSettings,
    *,
    research_purpose: QueryPurpose | None = None,
) -> ExtractionOutcome:
    """Ask the model for evidence in one snapshot. Never raises for a model outcome."""
    outcome = ExtractionOutcome(snapshot=snapshot)
    model = llm_settings.extraction_model

    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.EVIDENCE_EXTRACTION,
        system_prompt=EVIDENCE_EXTRACTOR_PROMPT_V1,
        user_input=build_evidence_user_input(
            snapshot.text,
            research_purpose=research_purpose.value if research_purpose else None,
        ),
        response_model=EvidenceExtraction,
        model=model,
        max_retries=llm_settings.max_retries,
    )
    outcome.call = call

    if not call.succeeded or call.parsed is None:
        logger.debug("evidence extraction call: %s", call.log_fields())
        return outcome

    parsed = call.parsed
    if not isinstance(parsed, EvidenceExtraction):
        # Structured does not mean correct: a provider that hands back the wrong
        # shape is a schema failure, not evidence.
        outcome.schema_error = True
        return outcome

    outcome.candidates = [
        _candidate(item, snapshot, model_name=model, purpose=research_purpose)
        for item in parsed.evidence
    ]
    return outcome


def extract_all_candidates(
    snapshots: list[SourceContentSnapshot],
    provider: StructuredModelProvider,
    llm_settings: LLMSettings,
    *,
    purposes: dict[UUID, QueryPurpose] | None = None,
) -> list[ExtractionOutcome]:
    """Extract from every snapshot independently.

    One snapshot's model failure removes nothing from another's candidates
    (§53): each call is its own outcome, and the caller aggregates.
    """
    purposes = purposes or {}
    return [
        extract_candidates(
            snapshot,
            provider,
            llm_settings,
            research_purpose=purposes.get(snapshot.content_id),
        )
        for snapshot in snapshots
    ]


__all__ = [
    "EVIDENCE_EXTRACTOR_PROMPT_VERSION",
    "ExtractionOutcome",
    "extract_all_candidates",
    "extract_candidates",
]
