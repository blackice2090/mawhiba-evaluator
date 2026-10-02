"""Bounded counterevidence review (one claim, one call).

The review looks for source text that weakens a limitation, within the existing
bounded inventory only -- never a new search (section 11). Counterevidence is
never suppressed because it weakens the project. Coverage is recorded: every
inventory text visible to the claim is either examined in full or listed as
omitted (bound reached, truncated, or unreadable), and an incomplete review
can never reach ``SUPPORTED_WITHIN_BOUNDS``.
"""

from __future__ import annotations

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1, build_gap_counterevidence_user_input
from src.llm.provider import StructuredModelProvider
from src.research.gap import verify as v
from src.research.gap.dto import CounterEvidenceResponse
from src.research.gap.extract import StageOutcome
from src.research.gap.inventory import ShownText
from src.schemas.claim import ClaimRecord
from src.schemas.gap_assessment import (
    ChronologyBucket,
    ConditionMatch,
    CounterEvidenceKind,
    GapAssessmentBounds,
    GapAssessmentIssue,
    GapClaimDraft,
    GapCounterEvidence,
    GapEvidenceRole,
    GapIssueCode,
    SourceQualityVerdict,
    TemporalEffect,
    gap_id,
)

NODE = "REVIEW_GAP_COUNTEREVIDENCE"


def _issue(code: GapIssueCode, message: str, claim_id: str) -> GapAssessmentIssue:
    return GapAssessmentIssue(code=code, node=NODE, message=message[:200], claim_id=claim_id)


def coverage_split(shown: list[ShownText], omitted_ids: list, visible_ids: list) -> tuple[list, list]:
    """(examined, omitted): a text shown only as a prefix counts as omitted."""
    omitted = set(omitted_ids)
    examined = [t.item.inventory_text_id for t in shown if t.item.inventory_text_id not in omitted]
    not_examined = [i for i in visible_ids if i not in set(examined)]
    return sorted(examined, key=str), sorted(not_examined, key=str)


def unexecuted(draft: GapClaimDraft, visible_ids: list) -> GapClaimDraft:
    """No review ran: nothing was examined, so the review is incomplete."""
    return draft.model_copy(update={
        "counter_done": True, "counter_examined_text_ids": [],
        "counter_omitted_text_ids": sorted(visible_ids, key=str),
    })


def review_claim(
    *, gap_run_id, claim: ClaimRecord, draft: GapClaimDraft, shown: list[ShownText], omitted_ids: list,
    visible_ids: list, provider: StructuredModelProvider, llm_settings: LLMSettings | None,
    bounds: GapAssessmentBounds,
) -> StageOutcome:
    cid = claim.claim_id
    ref_of = {r.evidence_ref_id: r for r in draft.evidence_refs}
    eligible = sorted(
        (lim for lim in draft.limitations
         if any(ref_of[i].source_quality is SourceQualityVerdict.ELIGIBLE for i in lim.evidence_ref_ids)),
        key=lambda x: str(x.limitation_id),
    )
    examined, not_examined = coverage_split(shown, omitted_ids, visible_ids)
    base = draft.model_copy(update={
        "counter_done": True, "counter_examined_text_ids": examined, "counter_omitted_text_ids": not_examined,
    })
    if not eligible or not shown:
        # Nothing to counter, or nothing visible to read: coverage is whatever was actually shown.
        return StageOutcome(base, [], [])
    limitations = [
        (f"L{i + 1}", lim.limitation_type.value, ref_of[lim.evidence_ref_ids[0]].excerpt)
        for i, lim in enumerate(eligible)
    ]
    texts = [(t.token, (t.item.text_kind.value if t.item.text_kind else "ACADEMIC_EXCERPT"), t.shown) for t in shown]
    model = (llm_settings or LLMSettings()).extraction_model
    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.GAP_COUNTEREVIDENCE_REVIEW,
        system_prompt=GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1,
        user_input=build_gap_counterevidence_user_input(limitations, texts),
        response_model=CounterEvidenceResponse,
        model=model,
        max_retries=bounds.model_retry_limit,
    )
    if not call.succeeded or not isinstance(call.parsed, CounterEvidenceResponse):
        detail = f"model call did not yield a usable response: {call.status.value}"  # provider text is never persisted
        # A failed review examined nothing: coverage is incomplete and says so.
        return StageOutcome(unexecuted(draft, visible_ids), [], [_issue(GapIssueCode.MODEL_ERROR, detail, cid)], True)

    by_token = {t.token: t for t in shown}
    shown_strings = v.shown_texts_of(by_token) + [text for _, _, text in limitations]
    limitation_spans = {(r.source_record_id, r.start, r.end) for r in ref_of.values() if r.role is GapEvidenceRole.LIMITATION}
    rejected, issues = [], []
    refs, counters = {r.evidence_ref_id: r for r in draft.evidence_refs}, list(draft.counterevidence)
    for dto in call.parsed.items[: bounds.max_counterevidence_per_claim]:
        if v.discloses_system_prompt(dto.rationale, shown_strings) or v.discloses_system_prompt(dto.excerpt, shown_strings):
            issues.append(_issue(GapIssueCode.PROMPT_LEAK_REDACTED, "hidden prompt disclosure redacted", cid))
            rejected.append(v.rejection(cid, v.R_PROMPT_DISCLOSURE))
            continue
        if v.forbidden_conclusion(dto.rationale):
            issues.append(_issue(GapIssueCode.FORBIDDEN_CONCLUSION, "forbidden conclusion in model prose", cid))
            rejected.append(v.rejection(cid, v.R_FORBIDDEN_CONCLUSION))
            continue
        try:
            kind = CounterEvidenceKind((dto.kind or "").strip().upper())
            match = ConditionMatch((dto.condition_match or "").strip().upper())
        except ValueError:
            rejected.append(v.rejection(cid, v.R_INVALID_KIND, model_text=dto.kind or ""))
            continue
        verdict = v.verify_span(
            by_token, dto.text, (dto.excerpt or "").strip(), start=dto.start, end=dto.end,
            occurrence=dto.occurrence, claim_text=claim.claim,
        )
        if isinstance(verdict, str):
            if verdict in (v.R_NOT_IN_TEXT, v.R_CLAIM_AS_EVIDENCE, v.R_UNKNOWN_TEXT):
                issues.append(_issue(GapIssueCode.FABRICATED_ANCHOR, "unverifiable excerpt rejected", cid))
            rejected.append(v.rejection(cid, verdict, model_text=dto.excerpt or ""))
            continue
        item = verdict.shown.item
        if item.source_quality is not SourceQualityVerdict.ELIGIBLE:
            rejected.append(v.rejection(cid, v.R_INELIGIBLE_SOURCE, note=item.source_quality.value))
            continue
        if (item.source_record_id, verdict.start, verdict.end) in limitation_spans:
            rejected.append(v.rejection(cid, v.R_SELF_COUNTER))
            continue
        ref = v.make_ref(gap_run_id, cid, GapEvidenceRole.COUNTEREVIDENCE, verdict)
        refs[ref.evidence_ref_id] = ref
        later = item.chronology_bucket is ChronologyBucket.AFTER_CUTOFF
        counter_id = gap_id(gap_run_id, cid, "counterevidence", kind.value, ref.evidence_ref_id)
        if any(c.counter_id == counter_id for c in counters):
            continue
        counters.append(GapCounterEvidence(
            counter_id=counter_id, kind=kind, condition_match=match, evidence_ref_ids=[ref.evidence_ref_id],
            chronology_bucket=item.chronology_bucket,
            temporal_effect=TemporalEffect.WEAKENS_CURRENT_POSTURE_ONLY if later else TemporalEffect.NOT_APPLICABLE,
        ))
    if len(call.parsed.items) > bounds.max_counterevidence_per_claim:
        rejected.append(v.rejection(cid, v.R_BOUND, note="counterevidence"))
    updated = base.model_copy(update={
        "evidence_refs": sorted(refs.values(), key=lambda r: str(r.evidence_ref_id)),
        "counterevidence": sorted(counters, key=lambda c: str(c.counter_id)),
        "rejected_count": draft.rejected_count + len(rejected),
    })
    return StageOutcome(updated, rejected, issues, model_called=True)


__all__ = ["NODE", "coverage_split", "review_claim", "unexecuted"]
