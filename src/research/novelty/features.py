"""Comparison feature inventory -- Phase 2I sections 6-9.

The model proposes typed features of ONE claim; this module decides what is
admissible, from the canonical claim text alone:

* every feature anchor is located in the claim by code (first occurrence);
  text that is not literally in the claim is rejected, never repaired;
* ``COMBINATION`` is reserved -- the whole-claim combination feature is created
  here whenever there are two or more elements, so "all components found" can
  never stand in for "the claimed combination found";
* material claim text no accepted feature covers becomes an
  ``UNCOVERED_CLAIM_REMAINDER`` feature, so it stays in the denominator, and the
  inventory is recorded ``INCOMPLETE`` (the Phase 2E.1 pattern);
* when component-level comparison is unavailable -- no usable Phase 2E
  inventory, no model, a failed extraction -- the claim falls back to a single
  full-claim feature and the reason is recorded.

The Phase 2E inventory is read, never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import NOVELTY_FEATURE_EXTRACTION_PROMPT_V1, build_feature_extraction_user_input
from src.llm.provider import StructuredModelProvider
from src.research.novelty.anchoring import LocateFailure, locate
from src.research.novelty.dto import FeatureExtractionResponse
from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import (
    ClaimComponentInventory,
    claim_text_digest,
    is_material_text,
)
from src.schemas.discovery import safe_summary
from src.schemas.novelty_differentiation import (
    FEATURE_EXTRACTION_PROMPT_VERSION,
    MODEL_PROPOSABLE_TYPES,
    ComparisonFeature,
    ComparisonFeatureInventory,
    FeatureDerivation,
    FeatureRejectionReason,
    FeatureType,
    FeatureVerificationStatus,
    InventoryCompleteness,
    InventoryIssue,
    InventoryMode,
    InventoryModeReason,
    NoveltyComparisonBounds,
    RejectedFeatureProposal,
    component_id,
    novelty_id,
)


_FEATURE_LOCATE_REASON: dict[LocateFailure, FeatureRejectionReason] = {
    LocateFailure.NOT_FOUND: FeatureRejectionReason.ANCHOR_NOT_IN_CLAIM,
    LocateFailure.AMBIGUOUS: FeatureRejectionReason.AMBIGUOUS_REPEATED_ANCHOR,
    LocateFailure.INVALID_OFFSETS: FeatureRejectionReason.INVALID_OFFSETS,
    LocateFailure.INVALID_OCCURRENCE: FeatureRejectionReason.INVALID_OCCURRENCE_INDEX,
}


@dataclass
class InventoryOutcome:
    inventory: ComparisonFeatureInventory
    model_called: bool = False
    model_failed: bool = False
    schema_error: bool = False
    notes: list[str] = field(default_factory=list)


def claim_span(text: str) -> tuple[int, int]:
    """The claim without surrounding whitespace, as a span of the raw text."""
    start = len(text) - len(text.lstrip())
    return start, len(text.rstrip())


def _feature(nd_run_id: UUID, claim_id: str, feature_type: FeatureType, start: int, end: int,
             text: str, derivation: FeatureDerivation, components: list[tuple[str, int, int]]) -> ComparisonFeature:
    return ComparisonFeature(
        feature_id=novelty_id(nd_run_id, "feature", claim_id, feature_type.value, start, end),
        claim_id=claim_id,
        feature_type=feature_type,
        start=start,
        end=end,
        text=text,
        derivation=derivation,
        verification_status=(
            FeatureVerificationStatus.VERIFIED_EXACT_CLAIM_ANCHOR
            if derivation is FeatureDerivation.MODEL_PROPOSED_VERIFIED
            else FeatureVerificationStatus.DERIVED_FROM_CLAIM_TEXT
        ),
        source_component_ids=sorted(cid for cid, s, e in components if s < end and start < e),
    )


def _component_spans(inventory: ClaimComponentInventory | None) -> list[tuple[str, int, int]]:
    if inventory is None:
        return []
    return [(component_id(c.claim_id, c.start, c.end), c.start, c.end) for c in inventory.components]


def mode_reasons_for(
    claim: ClaimRecord,
    phase2e: ClaimComponentInventory | None,
    provider: StructuredModelProvider | None,
) -> list[InventoryModeReason]:
    """Why component-level comparison is unavailable, if it is. Empty = available."""
    reasons: list[InventoryModeReason] = []
    if phase2e is None:
        reasons.append(InventoryModeReason.PHASE_2E_INVENTORY_MISSING)
    else:
        if phase2e.claim_text_hash != claim_text_digest(claim.claim):
            reasons.append(InventoryModeReason.PHASE_2E_CLAIM_HASH_MISMATCH)
        if not phase2e.is_complete:
            reasons.append(InventoryModeReason.PHASE_2E_INVENTORY_NOT_COMPLETE)
    if provider is None:
        reasons.append(InventoryModeReason.MODEL_PROVIDER_MISSING)
    return reasons


def _fallback(
    nd_run_id: UUID, research_run_id: UUID, claim: ClaimRecord, phase2e: ClaimComponentInventory | None,
    reasons: list[InventoryModeReason], rejected: list[RejectedFeatureProposal], model_name: str | None,
) -> ComparisonFeatureInventory:
    start, end = claim_span(claim.claim)
    components = _component_spans(phase2e)
    feature = _feature(
        nd_run_id, claim.claim_id, FeatureType.COMBINATION, start, end, claim.claim[start:end],
        FeatureDerivation.FULL_CLAIM_FALLBACK, components,
    )
    return ComparisonFeatureInventory(
        inventory_id=novelty_id(nd_run_id, "inventory", claim.claim_id),
        nd_run_id=nd_run_id,
        research_run_id=research_run_id,
        claim_id=claim.claim_id,
        claim_text_hash=claim_text_digest(claim.claim),
        claim_text_length=len(claim.claim),
        mode=InventoryMode.FULL_CLAIM_ONLY,
        mode_reasons=reasons,
        completeness=InventoryCompleteness.COMPLETE,
        features=[feature],
        rejected_proposals=rejected,
        phase2e_component_ids=[cid for cid, _, _ in components],
        phase2e_inventory_completeness=phase2e.completeness.value if phase2e else None,
        extraction_prompt_version=FEATURE_EXTRACTION_PROMPT_VERSION if model_name else None,
        model_name=model_name,
    )


def verify_feature_proposals(
    claim: ClaimRecord, proposals: FeatureExtractionResponse, *, max_elements: int
) -> tuple[list[tuple[FeatureType, int, int]], list[RejectedFeatureProposal], bool]:
    """Deterministic admissibility of each proposed feature.

    Returns (accepted (type, start, end), rejected, limit_exceeded).
    """
    accepted: list[tuple[FeatureType, int, int]] = []
    rejected: list[RejectedFeatureProposal] = []
    limit_exceeded = False

    def reject(raw_type: str, text: str, reason: FeatureRejectionReason) -> None:
        rejected.append(
            RejectedFeatureProposal(
                claim_id=claim.claim_id,
                proposed_type=safe_summary(raw_type)[:64],
                proposed_text_summary=safe_summary(text),
                reason=reason,
            )
        )

    for proposal in proposals.features:
        raw_type = (proposal.feature_type or "").strip().upper()
        text = (proposal.text or "").strip()
        if not text:
            reject(raw_type, text, FeatureRejectionReason.EMPTY_ANCHOR)
            continue
        try:
            feature_type = FeatureType(raw_type)
        except ValueError:
            reject(raw_type, text, FeatureRejectionReason.INVALID_FEATURE_TYPE)
            continue
        if feature_type not in MODEL_PROPOSABLE_TYPES:
            reject(raw_type, text, FeatureRejectionReason.RESERVED_FEATURE_TYPE)
            continue
        located = locate(claim.claim, text, start=proposal.start, occurrence=proposal.occurrence)
        if isinstance(located, LocateFailure):
            reject(raw_type, text, _FEATURE_LOCATE_REASON[located])
            continue
        start = located.start
        if not is_material_text(text):
            reject(raw_type, text, FeatureRejectionReason.IMMATERIAL_ANCHOR)
            continue
        key = (feature_type, start, start + len(text))
        if key in accepted:
            reject(raw_type, text, FeatureRejectionReason.DUPLICATE_FEATURE)
            continue
        if len(accepted) >= max_elements:
            limit_exceeded = True
            reject(raw_type, text, FeatureRejectionReason.FEATURE_LIMIT_EXCEEDED)
            continue
        accepted.append(key)
    return accepted, rejected, limit_exceeded


def uncovered_material_spans(claim_text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Maximal runs of claim text no span covers, trimmed, that carry material text."""
    covered = [False] * len(claim_text)
    for start, end in spans:
        for index in range(start, end):
            covered[index] = True
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(claim_text):
        if covered[index]:
            index += 1
            continue
        start = index
        while index < len(claim_text) and not covered[index]:
            index += 1
        segment = claim_text[start:index]
        stripped = segment.strip()
        if stripped and is_material_text(stripped):
            offset = start + (len(segment) - len(segment.lstrip()))
            runs.append((offset, offset + len(stripped)))
    return runs


def build_inventory(
    nd_run_id: UUID,
    research_run_id: UUID,
    claim: ClaimRecord,
    phase2e: ClaimComponentInventory | None,
    provider: StructuredModelProvider | None,
    llm_settings: LLMSettings | None,
    bounds: NoveltyComparisonBounds,
) -> InventoryOutcome:
    """Build ONE claim's comparison feature inventory."""
    reasons = mode_reasons_for(claim, phase2e, provider)
    if reasons:
        return InventoryOutcome(_fallback(nd_run_id, research_run_id, claim, phase2e, reasons, [], None))

    assert provider is not None and phase2e is not None
    model = (llm_settings or LLMSettings()).extraction_model
    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.NOVELTY_FEATURE_EXTRACTION,
        system_prompt=NOVELTY_FEATURE_EXTRACTION_PROMPT_V1,
        user_input=build_feature_extraction_user_input(claim.claim, [c.text for c in phase2e.components]),
        response_model=FeatureExtractionResponse,
        model=model,
        max_retries=bounds.model_retry_limit,
    )
    if not call.succeeded or not isinstance(call.parsed, FeatureExtractionResponse):
        schema_error = call.succeeded or call.status.value == "PARSE_ERROR"
        inventory = _fallback(
            nd_run_id, research_run_id, claim, phase2e,
            [InventoryModeReason.FEATURE_EXTRACTION_FAILED], [], model,
        )
        return InventoryOutcome(inventory, model_called=True, model_failed=not schema_error, schema_error=schema_error)

    accepted, rejected, limit_exceeded = verify_feature_proposals(
        claim, call.parsed, max_elements=bounds.max_features_per_claim - 1
    )
    if not accepted:
        inventory = _fallback(
            nd_run_id, research_run_id, claim, phase2e,
            [InventoryModeReason.NO_VERIFIED_FEATURES], rejected, model,
        )
        return InventoryOutcome(inventory, model_called=True)

    components = _component_spans(phase2e)
    features = [
        _feature(nd_run_id, claim.claim_id, t, s, e, claim.claim[s:e],
                 FeatureDerivation.MODEL_PROPOSED_VERIFIED, components)
        for t, s, e in accepted
    ]
    issues: list[InventoryIssue] = []
    remainders = uncovered_material_spans(claim.claim, [(s, e) for _, s, e in accepted])
    for start, end in remainders:
        features.append(
            _feature(nd_run_id, claim.claim_id, FeatureType.OTHER_TECHNICAL_FEATURE, start, end,
                     claim.claim[start:end], FeatureDerivation.UNCOVERED_CLAIM_REMAINDER, components)
        )
    if remainders:
        issues.append(InventoryIssue.UNCOVERED_MATERIAL_TEXT)
    if limit_exceeded:
        issues.append(InventoryIssue.FEATURE_LIMIT_EXCEEDED)
    if len(features) >= 2:
        start, end = claim_span(claim.claim)
        features.append(
            _feature(nd_run_id, claim.claim_id, FeatureType.COMBINATION, start, end, claim.claim[start:end],
                     FeatureDerivation.DETERMINISTIC_COMBINATION, components)
        )
    features.sort(key=lambda f: (f.feature_type is FeatureType.COMBINATION, f.start, f.end, f.feature_type.value))
    inventory = ComparisonFeatureInventory(
        inventory_id=novelty_id(nd_run_id, "inventory", claim.claim_id),
        nd_run_id=nd_run_id,
        research_run_id=research_run_id,
        claim_id=claim.claim_id,
        claim_text_hash=claim_text_digest(claim.claim),
        claim_text_length=len(claim.claim),
        mode=InventoryMode.COMPONENT_LEVEL,
        completeness=InventoryCompleteness.INCOMPLETE if issues else InventoryCompleteness.COMPLETE,
        issues=issues,
        features=features,
        rejected_proposals=rejected,
        phase2e_component_ids=[cid for cid, _, _ in components],
        phase2e_inventory_completeness=phase2e.completeness.value,
        extraction_prompt_version=FEATURE_EXTRACTION_PROMPT_VERSION,
        model_name=model,
    )
    return InventoryOutcome(inventory, model_called=True)


__all__ = [
    "InventoryOutcome",
    "build_inventory",
    "claim_span",
    "mode_reasons_for",
    "uncovered_material_spans",
    "verify_feature_proposals",
]
