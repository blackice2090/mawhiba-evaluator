"""Project-gap linkage judgment and verification (one claim, one call).

Linkage is the second half of a project gap: a limitation can exist in existing
work without the student's feature targeting it. The model proposes a typed
relation per (feature, limitation) pair; code verifies identity, provenance and
references. The relation itself stays ``MODEL_ASSISTED_BOUNDED_JUDGMENT`` --
validated IDs prove the record is correctly bound, never that the judgment is
right (ADR-021).

Only DIFFERENTIATING Phase 2I features are put to the model: a feature a
compared candidate already discloses cannot materially distinguish the project,
so asking about it would only create a link that could never count.
"""

from __future__ import annotations

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import GAP_PROJECT_LINKAGE_PROMPT_V1, build_gap_linkage_user_input
from src.llm.provider import StructuredModelProvider
from src.research.gap import verify as v
from src.research.gap.extract import StageOutcome
from src.research.gap.dto import LinkageResponse
from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import claim_text_digest
from src.schemas.gap_assessment import (
    DIFFERENTIATING_STATUSES,
    GapAssessmentBounds,
    GapAssessmentIssue,
    GapClaimDraft,
    GapIssueCode,
    GapProjectLink,
    InsufficientReason,
    LinkageRelation,
    RejectedGapProposal,
    SourceQualityVerdict,
    gap_id,
    link_status_for,
)
from src.schemas.novelty_differentiation import (
    ClaimDifferentiationSynthesis,
    ComparisonFeature,
    ComparisonFeatureInventory,
    NoveltyDifferentiationRun,
)
from hashlib import sha256

NODE = "VERIFY_GAP_PROJECT_LINKAGE"


def differentiating_features(
    inventory: ComparisonFeatureInventory | None, synthesis: ClaimDifferentiationSynthesis | None
) -> list[tuple[ComparisonFeature, object]]:
    """(feature, inherited Phase 2I status) for every differentiating feature."""
    if inventory is None or synthesis is None:
        return []
    status_of = {d.feature_id: d.status for d in synthesis.feature_differentiations}
    pairs = [(f, status_of[f.feature_id]) for f in inventory.features
             if status_of.get(f.feature_id) in DIFFERENTIATING_STATUSES]
    return sorted(pairs, key=lambda p: (p[0].start, p[0].end, str(p[0].feature_id)))


def _issue(code: GapIssueCode, message: str, claim_id: str) -> GapAssessmentIssue:
    return GapAssessmentIssue(code=code, node=NODE, message=message[:200], claim_id=claim_id)


def link_claim(
    *, gap_run_id, nd: NoveltyDifferentiationRun, claim: ClaimRecord, draft: GapClaimDraft,
    features: list[tuple[ComparisonFeature, object]], provider: StructuredModelProvider,
    llm_settings: LLMSettings | None, bounds: GapAssessmentBounds,
) -> StageOutcome:
    cid = claim.claim_id
    eligible = [
        lim for lim in draft.limitations
        if any(r.evidence_ref_id in lim.evidence_ref_ids and r.source_quality is SourceQualityVerdict.ELIGIBLE
               for r in draft.evidence_refs)
    ]
    eligible.sort(key=lambda x: str(x.limitation_id))
    rejected: list[RejectedGapProposal] = []
    if not eligible or not features:
        return StageOutcome(draft.model_copy(update={"linkage_done": True}), rejected, [])

    feature_tokens = {f"F{i + 1}": f for i, (f, _) in enumerate(features)}
    limitation_tokens = {f"L{i + 1}": lim for i, lim in enumerate(eligible)}
    pairs = [(ft, lt) for ft in feature_tokens for lt in limitation_tokens][: bounds.max_link_pairs_per_claim]
    if len(feature_tokens) * len(limitation_tokens) > bounds.max_link_pairs_per_claim:
        rejected.append(v.rejection(cid, v.R_BOUND, note="link pairs"))
    used_features = {ft for ft, _ in pairs}
    used_limitations = {lt for _, lt in pairs}
    ref_of = {r.evidence_ref_id: r for r in draft.evidence_refs}
    shown_features = [(t, feature_tokens[t].feature_type.value, feature_tokens[t].text) for t in feature_tokens if t in used_features]
    shown_limitations = [
        (t, lim.limitation_type.value, ref_of[lim.evidence_ref_ids[0]].excerpt)
        for t, lim in limitation_tokens.items() if t in used_limitations
    ]
    model = (llm_settings or LLMSettings()).extraction_model
    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.GAP_PROJECT_LINKAGE,
        system_prompt=GAP_PROJECT_LINKAGE_PROMPT_V1,
        user_input=build_gap_linkage_user_input(shown_features, shown_limitations, pairs),
        response_model=LinkageResponse,
        model=model,
        max_retries=bounds.model_retry_limit,
    )
    if not call.succeeded or not isinstance(call.parsed, LinkageResponse):
        detail = f"model call did not yield a usable response: {call.status.value}"  # provider text is never persisted
        failed = draft.model_copy(update={
            "insufficient_reasons": [*draft.insufficient_reasons, InsufficientReason.MODEL_CALL_FAILED],
            "linkage_done": True,
        })
        return StageOutcome(failed, rejected, [_issue(GapIssueCode.MODEL_ERROR, detail, cid)], model_called=True)

    issues: list[GapAssessmentIssue] = []
    claim_hash = claim_text_digest(claim.claim)
    asked = set(pairs)
    shown_strings = [text for _, _, text in shown_features] + [text for _, _, text in shown_limitations]
    judged: dict[tuple[str, str], list] = {}
    for judgment in call.parsed.judgments:
        key = ((judgment.feature or "").strip().upper(), (judgment.limitation or "").strip().upper())
        if v.discloses_system_prompt(judgment.rationale, shown_strings):
            issues.append(_issue(GapIssueCode.PROMPT_LEAK_REDACTED, "hidden prompt disclosure redacted", cid))
            rejected.append(v.rejection(cid, v.R_PROMPT_DISCLOSURE))
            continue
        if v.forbidden_conclusion(judgment.rationale):
            issues.append(_issue(GapIssueCode.FORBIDDEN_CONCLUSION, "forbidden conclusion in model prose", cid))
            rejected.append(v.rejection(cid, v.R_FORBIDDEN_CONCLUSION))
            continue
        if key not in asked:
            rejected.append(v.rejection(cid, v.R_UNKNOWN_LABEL, model_text="/".join(key)))
            issues.append(_issue(GapIssueCode.FABRICATED_REFERENCE, "judgment on a pair that was not asked", cid))
            continue
        judged.setdefault(key, []).append(judgment)

    links: list[GapProjectLink] = []
    for key, items in sorted(judged.items()):
        if len(items) > 1:
            rejected.append(v.rejection(cid, v.R_DUPLICATE_JUDGMENT, note="/".join(key)))
            continue
        try:
            relation = LinkageRelation((items[0].relation or "").strip().upper())
        except ValueError:
            rejected.append(v.rejection(cid, v.R_INVALID_RELATION, model_text=items[0].relation or ""))
            continue
        feature, status = next((f, s) for f, s in features if f is feature_tokens[key[0]])
        limitation = limitation_tokens[key[1]]
        links.append(GapProjectLink(
            link_id=gap_id(gap_run_id, cid, "link", feature.feature_id, limitation.limitation_id),
            claim_id=cid, claim_text_hash=claim_hash, nd_run_id=nd.nd_run_id,
            feature_id=feature.feature_id,
            feature_text_hash=sha256(feature.text.encode("utf-8")).hexdigest(),
            feature_type=feature.feature_type, limitation_id=limitation.limitation_id,
            inherited_differentiation_status=status,  # type: ignore[arg-type]
            status=link_status_for(status),  # type: ignore[arg-type]
            relation=relation,
        ))
    updated = draft.model_copy(update={
        "project_links": sorted(links, key=lambda x: str(x.link_id)),
        "rejected_count": draft.rejected_count + len(rejected),
        "linkage_done": True,
    })
    return StageOutcome(updated, rejected, issues, model_called=True)


__all__ = ["NODE", "differentiating_features", "link_claim"]
