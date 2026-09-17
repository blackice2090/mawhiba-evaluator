"""The LLM classification step. Proposals only (section 8).

Mirrors ``src/research/evidence/extractor.py``: the least authoritative module
in the phase. It turns one claim/evidence pair into an ``AlignmentCandidate``
and stops. Whether the candidate becomes a verified alignment is decided
afterwards, by ``pipeline.py``, from the claim text and evidence excerpt alone.

Reuses the shared invocation layer rather than growing a second retry loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallResult, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import CLAIM_EVIDENCE_ALIGNMENT_PROMPT_V1, build_alignment_user_input
from src.llm.provider import StructuredModelProvider
from src.research.alignment.dto import AlignmentClassification, CandidateComponentDTO
from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import (
    ALIGNMENT_CLASSIFIER_VERSION,
    AlignmentCandidate,
    AlignmentReasonCode,
    AlignmentRelation,
    CandidateComponentAnchor,
    ComponentJudgment,
)
from src.schemas.evidence_extraction import ExtractedEvidence

logger = logging.getLogger(__name__)

ALIGNMENT_CLASSIFIER_PROMPT_VERSION = "CLAIM_EVIDENCE_ALIGNMENT_PROMPT_V1"


@dataclass
class ClassificationOutcome:
    """The candidate proposed for one pair, plus how the call went."""

    claim_id: str
    evidence_id: UUID
    candidate: AlignmentCandidate | None = None
    call: ModelCallResult | None = None
    schema_error: bool = False

    @property
    def succeeded(self) -> bool:
        return self.call is not None and self.call.succeeded


def _relation(raw: str | None) -> AlignmentRelation | None:
    if not raw:
        return None
    try:
        return AlignmentRelation(raw.strip().upper())
    except ValueError:
        return None


def _judgment(raw: str | None) -> ComponentJudgment | None:
    if not raw:
        return None
    try:
        return ComponentJudgment(raw.strip().upper())
    except ValueError:
        return None


def _reason_codes(raw: list[str]) -> list[AlignmentReasonCode]:
    codes: list[AlignmentReasonCode] = []
    for value in raw:
        try:
            codes.append(AlignmentReasonCode(value.strip().upper()))
        except ValueError:
            continue
    return codes or [AlignmentReasonCode.OTHER]


def _component(item: CandidateComponentDTO) -> CandidateComponentAnchor | None:
    judgment = _judgment(item.judgment)
    if judgment is None or not item.claimed_text:
        return None
    return CandidateComponentAnchor(
        claimed_text=item.claimed_text,
        claimed_start=item.claimed_start,
        claimed_end=item.claimed_end,
        judgment=judgment,
        reason_codes=_reason_codes(item.reason_codes),
        rationale=(item.rationale or None),
    )


def classify_pair(
    claim: ClaimRecord,
    evidence: ExtractedEvidence,
    provider: StructuredModelProvider,
    llm_settings: LLMSettings,
) -> ClassificationOutcome:
    """Ask the model to classify one claim against one verified excerpt."""
    outcome = ClassificationOutcome(claim_id=claim.claim_id, evidence_id=evidence.evidence_id)
    model = llm_settings.extraction_model

    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.CLAIM_EVIDENCE_ALIGNMENT,
        system_prompt=CLAIM_EVIDENCE_ALIGNMENT_PROMPT_V1,
        user_input=build_alignment_user_input(claim.claim, evidence.excerpt),
        response_model=AlignmentClassification,
        model=model,
        max_retries=llm_settings.max_retries,
    )
    outcome.call = call

    if not call.succeeded or call.parsed is None:
        logger.debug("alignment classification call: %s", call.log_fields())
        return outcome

    parsed = call.parsed
    if not isinstance(parsed, AlignmentClassification):
        outcome.schema_error = True
        return outcome

    relation = _relation(parsed.relation)
    if relation is None:
        # An unrecognized relation string is never coerced into a plausible
        # guess. Treated the same as any other schema violation: no candidate.
        outcome.schema_error = True
        return outcome

    components = [c for c in (_component(item) for item in parsed.components) if c]

    outcome.candidate = AlignmentCandidate(
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        relation=relation,
        components=components,
        rationale=(parsed.rationale or None),
        classifier_version=ALIGNMENT_CLASSIFIER_VERSION,
        model_name=model,
    )
    return outcome


def classify_pairs(
    pairs: list[tuple[ClaimRecord, ExtractedEvidence]],
    provider: StructuredModelProvider,
    llm_settings: LLMSettings,
) -> list[ClassificationOutcome]:
    """Classify every pair independently. One failure removes no other."""
    return [
        classify_pair(claim, evidence, provider, llm_settings)
        for claim, evidence in pairs
    ]


__all__ = [
    "ALIGNMENT_CLASSIFIER_PROMPT_VERSION",
    "ClassificationOutcome",
    "classify_pair",
    "classify_pairs",
]
