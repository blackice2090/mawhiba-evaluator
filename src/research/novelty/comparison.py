"""Claim-candidate technical comparison -- Phase 2I sections 14-19.

Chain (section 17)::

    verified candidate content + exact claim features
      -> untrusted structured comparison (one model call per claim/candidate)
      -> deterministic anchor / reference validation      (this module)
      -> verified ClaimCandidateComparison

The model only proposes per-feature relations with quoted excerpts. Code
decides what survives:

* every excerpt is located in the exact candidate text the model was shown,
  under the label it named; a repeated excerpt binds only through validated
  offsets or a validated occurrence index (no first-occurrence guessing);
* capacity is source- AND feature-sensitive (a manifest can disclose a
  component, never a mechanism or the combination);
* a disclosure without a verified anchor is NOT_COMPARABLE, never a negative;
  a negative needs complete material text for that feature type;
* candidate text that *reads like* an instruction is inert data and stays
  admissible evidence when exactly anchored. What is refused is model
  *behaviour*: invalid relations, fabricated or foreign excerpts, and output
  that discloses the system prompt;
* the full-claim relation is derived in Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallStatus, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1, build_comparison_user_input
from src.llm.provider import StructuredModelProvider
from src.research.novelty.anchoring import LocateFailure, locate
from src.research.novelty.candidates import resolve_text
from src.research.novelty.dto import TechnicalComparisonResponse
from src.schemas.discovery import safe_summary
from src.schemas.novelty_differentiation import (
    ANCHORED_RELATIONS,
    CAPACITY_CEILING,
    MAX_RATIONALE_CHARS,
    RELATION_STRENGTH,
    TECHNICAL_COMPARISON_PROMPT_VERSION,
    UNIVERSAL_COMPARISON_LIMITATIONS,
    AnchorRejectionReason,
    CandidateComparisonProfile,
    CandidateDisclosureAnchor,
    ClaimCandidateComparison,
    ComparableText,
    ComparisonFeatureInventory,
    ComparisonLimitation,
    ComparisonStatus,
    DisclosureCapacity,
    FeatureComparisonRecord,
    FeatureRelation,
    FeatureType,
    NoveltyComparisonBounds,
    RejectedAnchorProposal,
    RelationResolutionReason,
    ScopeLimitation,
    TextKind,
    derive_full_claim_relation,
    effective_capacity,
    novelty_id,
    vector_for,
)
from src.schemas.research import ResearchRun

_LOCATE_REASON: dict[LocateFailure, AnchorRejectionReason] = {
    LocateFailure.AMBIGUOUS: AnchorRejectionReason.AMBIGUOUS_REPEATED_EXCERPT,
    LocateFailure.INVALID_OFFSETS: AnchorRejectionReason.INVALID_OFFSETS,
    LocateFailure.INVALID_OCCURRENCE: AnchorRejectionReason.INVALID_OCCURRENCE_INDEX,
}

_PROMPT_FRAGMENT_MIN_CHARS = 40
_PROMPT_FRAGMENTS: tuple[str, ...] = tuple(
    line.strip().casefold()
    for line in PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1.splitlines()
    if len(line.strip()) >= _PROMPT_FRAGMENT_MIN_CHARS
)


def discloses_system_prompt(text: str | None, candidate_texts: list[str]) -> bool:
    """Model output reproducing a line of the hidden system prompt that the
    candidate text itself does not contain. That is instruction-following
    behaviour (section 33), not source data."""
    if not text:
        return False
    folded = text.casefold()
    sources = [t.casefold() for t in candidate_texts]
    return any(fragment in folded and not any(fragment in s for s in sources) for fragment in _PROMPT_FRAGMENTS)


@dataclass
class ShownText:
    token: str
    meta: ComparableText
    shown: str
    bounded: bool


@dataclass
class ComparisonContext:
    """What the model was shown for one pair, so verification checks exactly that."""

    feature_tokens: dict[str, UUID]
    texts: dict[str, ShownText]
    bounded: bool

    def complete_material_types(self) -> list[FeatureType]:
        """Feature types for which a complete MATERIAL-capacity text was shown."""
        complete = [t for t in self.texts.values() if not t.bounded and not t.meta.truncated_upstream]
        return [
            ft for ft in FeatureType
            if any(effective_capacity(t.meta.text_kind, t.meta.capacity, ft) is DisclosureCapacity.MATERIAL
                   for t in complete)
        ]

    def any_material_types(self) -> set[FeatureType]:
        return {
            ft for ft in FeatureType
            if any(effective_capacity(t.meta.text_kind, t.meta.capacity, ft) is DisclosureCapacity.MATERIAL
                   for t in self.texts.values())
        }


def comparison_id_for(nd_run_id: UUID, claim_id: str, profile: CandidateComparisonProfile) -> UUID:
    ref = profile.candidate_ref
    return novelty_id(nd_run_id, "comparison", claim_id, ref.candidate_type.value, ref.candidate_id)


def build_context(
    research_run: ResearchRun, inventory: ComparisonFeatureInventory, profile: CandidateComparisonProfile,
    bounds: NoveltyComparisonBounds,
) -> ComparisonContext:
    feature_tokens = {f"F{i}": f.feature_id for i, f in enumerate(inventory.features, start=1)}
    texts: dict[str, ShownText] = {}
    budget = bounds.max_chars_per_comparison
    any_bounded = False
    for meta in profile.texts:
        if budget <= 0:
            any_bounded = True
            break
        full = resolve_text(research_run, meta)
        if not full:
            continue
        shown = full[: min(bounds.max_chars_per_text, budget)]
        bounded = len(shown) < len(full)
        any_bounded |= bounded
        budget -= len(shown)
        token = f"T{len(texts) + 1}"
        texts[token] = ShownText(token, meta, shown, bounded)
    return ComparisonContext(feature_tokens=feature_tokens, texts=texts, bounded=any_bounded)


def _limitations(context: ComparisonContext) -> list[ComparisonLimitation]:
    found = list(UNIVERSAL_COMPARISON_LIMITATIONS)
    kinds = {t.meta.text_kind for t in context.texts.values()}
    if TextKind.PATENT_ABSTRACT in kinds:
        found.append(ComparisonLimitation.ABSTRACT_SCOPE_ONLY)
    if any(
        t.meta.text_kind is TextKind.PRODUCT_PAGE_TEXT and t.meta.capacity is not DisclosureCapacity.MATERIAL
        for t in context.texts.values()
    ):
        found.append(ComparisonLimitation.MARKETING_OR_THIRD_PARTY_TEXT)
    if kinds & {TextKind.OSS_README, TextKind.OSS_CODE_FRAGMENT, TextKind.OSS_MANIFEST}:
        found.append(ComparisonLimitation.README_OR_FRAGMENT_NOT_IMPLEMENTATION_PROOF)
    if any(t.meta.truncated_upstream for t in context.texts.values()):
        found.append(ComparisonLimitation.UPSTREAM_TEXT_TRUNCATED)
    return found


def unexecuted(
    nd_run_id: UUID, research_run_id: UUID, inventory: ComparisonFeatureInventory,
    profile: CandidateComparisonProfile, status: ComparisonStatus, detail: str = "",
    model: str | None = None,
) -> ClaimCandidateComparison:
    return ClaimCandidateComparison(
        comparison_id=comparison_id_for(nd_run_id, inventory.claim_id, profile),
        nd_run_id=nd_run_id,
        research_run_id=research_run_id,
        claim_id=inventory.claim_id,
        inventory_id=inventory.inventory_id,
        profile_id=profile.profile_id,
        candidate_ref=profile.candidate_ref,
        independence_unit=profile.independence_unit,
        chronology_bucket=profile.chronology.bucket,
        status=status,
        model_name=model,
        prompt_version=TECHNICAL_COMPARISON_PROMPT_VERSION if model else None,
        issue_detail=safe_summary(detail),
    )


@dataclass
class ForeignTexts:
    """Texts the excerpt must NOT come from: the claim, and every other candidate."""

    claim_text: str
    other_candidate_texts: list[str] = field(default_factory=list)


@dataclass
class ComparisonOutcome:
    comparison: ClaimCandidateComparison
    model_called: bool = False
    fabricated_anchor_count: int = 0
    instruction_following_count: int = 0


def _record(feature, relation: FeatureRelation, reasons: list[RelationResolutionReason], *,
            proposed: FeatureRelation | None = None, anchors: list[UUID] | None = None,
            rationale: str | None = None) -> FeatureComparisonRecord:
    return FeatureComparisonRecord(
        feature_id=feature.feature_id, feature_type=feature.feature_type, proposed_relation=proposed,
        relation=relation, anchor_ids=anchors or [], resolution_reasons=reasons, model_rationale=rationale,
    )


def verify_response(
    *,
    nd_run_id: UUID,
    research_run_id: UUID,
    inventory: ComparisonFeatureInventory,
    profile: CandidateComparisonProfile,
    context: ComparisonContext,
    response: TechnicalComparisonResponse,
    foreign: ForeignTexts,
    model: str,
) -> ComparisonOutcome:
    """Turn one untrusted comparison response into a verified comparison."""
    comparison_id = comparison_id_for(nd_run_id, inventory.claim_id, profile)
    rejected: list[RejectedAnchorProposal] = []
    fabricated = 0
    instruction_following = 0
    shown_texts = [t.shown for t in context.texts.values()]
    metadata_texts = [t.shown for t in context.texts.values() if t.meta.capacity is DisclosureCapacity.NON_MATERIAL]
    complete_types = context.complete_material_types()
    material_types = context.any_material_types()

    def reject(feature: str, text: str, excerpt: str, reason: AnchorRejectionReason) -> None:
        # A rejected system-prompt disclosure is refused AND not persisted: the
        # ledger records that it happened, never the disclosed text itself.
        summary = (
            "[redacted: system prompt disclosure]"
            if reason is AnchorRejectionReason.SYSTEM_PROMPT_DISCLOSURE
            else safe_summary(excerpt)
        )
        rejected.append(RejectedAnchorProposal(
            feature_token=feature[:32], text_token=text[:32], excerpt_summary=summary, reason=reason,
        ))

    by_feature: dict[UUID, list] = {}
    token_of = {v: k for k, v in context.feature_tokens.items()}
    for judgment in response.judgments:
        token = (judgment.feature or "").strip().upper()
        feature_id = context.feature_tokens.get(token)
        if feature_id is None:
            reject(token, "", "", AnchorRejectionReason.UNKNOWN_FEATURE_REFERENCE)
            continue
        by_feature.setdefault(feature_id, []).append(judgment)

    anchors: list[CandidateDisclosureAnchor] = []
    records: list[FeatureComparisonRecord] = []
    for feature in inventory.features:
        judgments = by_feature.get(feature.feature_id, [])
        ftoken = token_of[feature.feature_id]
        if not judgments:
            records.append(_record(feature, FeatureRelation.NOT_COMPARABLE, [RelationResolutionReason.FEATURE_NOT_JUDGED]))
            continue
        if len(judgments) > 1:
            reject(ftoken, "", "", AnchorRejectionReason.DUPLICATE_FEATURE_JUDGMENT)
            records.append(_record(feature, FeatureRelation.NOT_COMPARABLE, [RelationResolutionReason.DUPLICATE_JUDGMENT]))
            continue
        judgment = judgments[0]
        raw_rationale = (judgment.rationale or "").strip()
        if discloses_system_prompt(raw_rationale, shown_texts) or any(
            discloses_system_prompt(e.excerpt, shown_texts) for e in judgment.evidence
        ):
            instruction_following += 1
            reject(ftoken, "", raw_rationale, AnchorRejectionReason.SYSTEM_PROMPT_DISCLOSURE)
            records.append(_record(feature, FeatureRelation.NOT_COMPARABLE,
                                   [RelationResolutionReason.MODEL_INSTRUCTION_FOLLOWING]))
            continue
        rationale = raw_rationale[:MAX_RATIONALE_CHARS] or None
        try:
            proposed = FeatureRelation((judgment.relation or "").strip().upper())
        except ValueError:
            reject(ftoken, "", judgment.relation or "", AnchorRejectionReason.INVALID_RELATION)
            records.append(_record(feature, FeatureRelation.NOT_COMPARABLE, [RelationResolutionReason.INVALID_RELATION]))
            continue

        if proposed not in ANCHORED_RELATIONS:
            for item in judgment.evidence:
                reject(ftoken, item.text, item.excerpt, AnchorRejectionReason.ANCHOR_ON_NON_DISCLOSURE_RELATION)
            relation, reasons = proposed, []
            if proposed is FeatureRelation.NOT_DISCLOSED and feature.feature_type not in complete_types:
                relation = FeatureRelation.INSUFFICIENT_SOURCE_TEXT
                reasons = [
                    RelationResolutionReason.NEGATIVE_WITHOUT_COMPLETE_MATERIAL_TEXT
                    if feature.feature_type in material_types
                    else RelationResolutionReason.NEGATIVE_WITHOUT_MATERIAL_TEXT
                ]
            records.append(_record(feature, relation, reasons, proposed=proposed, rationale=rationale))
            continue

        feature_anchors: list[CandidateDisclosureAnchor] = []
        for item in judgment.evidence:
            ttoken = (item.text or "").strip().upper()
            excerpt = (item.excerpt or "").strip()
            shown = context.texts.get(ttoken)
            if shown is None:
                reject(ftoken, ttoken, excerpt, AnchorRejectionReason.UNKNOWN_TEXT_REFERENCE)
                fabricated += 1
                continue
            if not excerpt:
                reject(ftoken, ttoken, excerpt, AnchorRejectionReason.EMPTY_EXCERPT)
                continue
            located = locate(shown.shown, excerpt, start=item.start, end=item.end, occurrence=item.occurrence)
            if located is LocateFailure.NOT_FOUND:
                fabricated += 1
                if excerpt in foreign.claim_text:
                    reason = AnchorRejectionReason.CLAIM_TEXT_AS_EVIDENCE
                elif any(excerpt in other for other in foreign.other_candidate_texts):
                    reason = AnchorRejectionReason.CROSS_CANDIDATE_EXCERPT
                else:
                    reason = AnchorRejectionReason.EXCERPT_NOT_IN_TEXT
                reject(ftoken, ttoken, excerpt, reason)
                continue
            if isinstance(located, LocateFailure):
                reject(ftoken, ttoken, excerpt, _LOCATE_REASON[located])
                continue
            meta = shown.meta
            capacity = effective_capacity(meta.text_kind, meta.capacity, feature.feature_type)
            scopes = list(meta.scope_limitations)
            if capacity is not meta.capacity:
                scopes.append(ScopeLimitation.MANIFEST_CANNOT_ESTABLISH_FEATURE_TYPE)
            if shown.bounded:
                scopes.append(ScopeLimitation.TEXT_BOUNDED_FOR_COMPARISON)
            if capacity is not DisclosureCapacity.NON_MATERIAL and any(excerpt in m for m in metadata_texts):
                capacity = DisclosureCapacity.NON_MATERIAL
                scopes.append(ScopeLimitation.METADATA_ECHO)
            anchor_id = novelty_id(comparison_id, "anchor", feature.feature_id, meta.text_ref_id, located.start, located.end)
            if any(a.anchor_id == anchor_id for a in feature_anchors):
                continue
            feature_anchors.append(CandidateDisclosureAnchor(
                anchor_id=anchor_id, comparison_id=comparison_id, feature_id=feature.feature_id,
                feature_type=feature.feature_type, candidate_ref=profile.candidate_ref,
                text_ref_id=meta.text_ref_id, source_record_kind=meta.source_record_kind,
                source_record_id=meta.source_record_id, text_kind=meta.text_kind, excerpt=excerpt,
                start=located.start, end=located.end, occurrence_count=located.occurrence_count,
                occurrence_index=located.occurrence_index, occurrence_resolution=located.resolution,
                content_hash=meta.content_hash, text_digest=meta.text_digest, language=meta.language,
                truncated_upstream=meta.truncated_upstream, base_capacity=meta.capacity, capacity=capacity,
                scope_limitations=scopes,
            ))
        if not feature_anchors:
            records.append(_record(feature, FeatureRelation.NOT_COMPARABLE,
                                   [RelationResolutionReason.ANCHOR_VERIFICATION_FAILED],
                                   proposed=proposed, rationale=rationale))
            continue
        strongest = max(feature_anchors, key=lambda a: RELATION_STRENGTH[CAPACITY_CEILING[a.capacity]])
        cap = CAPACITY_CEILING[strongest.capacity]
        relation, reasons = proposed, []
        if RELATION_STRENGTH[proposed] > RELATION_STRENGTH[cap]:
            relation = cap
            reasons = [
                RelationResolutionReason.CAPPED_BY_NON_MATERIAL_SOURCE
                if strongest.capacity is DisclosureCapacity.NON_MATERIAL
                else RelationResolutionReason.CAPPED_BY_LIMITED_SOURCE
            ]
        anchors.extend(feature_anchors)
        records.append(_record(feature, relation, reasons, proposed=proposed,
                               anchors=[a.anchor_id for a in feature_anchors], rationale=rationale))

    comparison = ClaimCandidateComparison(
        comparison_id=comparison_id, nd_run_id=nd_run_id, research_run_id=research_run_id,
        claim_id=inventory.claim_id, inventory_id=inventory.inventory_id, profile_id=profile.profile_id,
        candidate_ref=profile.candidate_ref, independence_unit=profile.independence_unit,
        chronology_bucket=profile.chronology.bucket, status=ComparisonStatus.VERIFIED,
        feature_records=records, anchors=anchors, rejected_anchors=rejected,
        full_claim_relation=derive_full_claim_relation(records), vector=vector_for(records),
        compared_text_ref_ids=[t.meta.text_ref_id for t in context.texts.values()],
        compared_text_bounded=context.bounded, complete_material_feature_types=complete_types,
        model_name=model, prompt_version=TECHNICAL_COMPARISON_PROMPT_VERSION, limitations=_limitations(context),
    )
    return ComparisonOutcome(comparison, model_called=True, fabricated_anchor_count=fabricated,
                             instruction_following_count=instruction_following)


def compare_pair(
    *,
    nd_run_id: UUID,
    research_run: ResearchRun,
    inventory: ComparisonFeatureInventory,
    profile: CandidateComparisonProfile,
    provider: StructuredModelProvider,
    llm_settings: LLMSettings | None,
    bounds: NoveltyComparisonBounds,
    foreign: ForeignTexts,
) -> ComparisonOutcome:
    """One model call for one claim/candidate pair, then deterministic verification."""
    run_id = research_run.research_run_id
    model = (llm_settings or LLMSettings()).extraction_model
    context = build_context(research_run, inventory, profile, bounds)
    by_id = {f.feature_id: f for f in inventory.features}
    features = [(token, by_id[fid].feature_type.value, by_id[fid].text) for token, fid in context.feature_tokens.items()]
    texts = [(t.token, t.meta.text_kind.value, t.shown) for t in context.texts.values()]
    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.PRIOR_ART_TECHNICAL_COMPARISON,
        system_prompt=PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1,
        user_input=build_comparison_user_input(features, texts),
        response_model=TechnicalComparisonResponse,
        model=model,
        max_retries=bounds.model_retry_limit,
    )
    if not call.succeeded:
        status = (
            ComparisonStatus.FAILED_SCHEMA_ERROR
            if call.status is ModelCallStatus.PARSE_ERROR
            else ComparisonStatus.FAILED_MODEL_ERROR
        )
        detail = f"{call.status.value}: {call.error or call.refusal or ''}"
        return ComparisonOutcome(unexecuted(nd_run_id, run_id, inventory, profile, status, detail, model), model_called=True)
    if not isinstance(call.parsed, TechnicalComparisonResponse):
        return ComparisonOutcome(
            unexecuted(nd_run_id, run_id, inventory, profile, ComparisonStatus.FAILED_SCHEMA_ERROR,
                       "response did not match the comparison schema", model),
            model_called=True,
        )
    return verify_response(
        nd_run_id=nd_run_id, research_run_id=run_id, inventory=inventory, profile=profile,
        context=context, response=call.parsed, foreign=foreign, model=model,
    )


__all__ = [
    "ComparisonContext",
    "ComparisonOutcome",
    "ForeignTexts",
    "build_context",
    "compare_pair",
    "comparison_id_for",
    "discloses_system_prompt",
    "unexecuted",
    "verify_response",
]
