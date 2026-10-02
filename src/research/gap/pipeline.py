"""Phase 2J stages over a ``GapAssessmentRun``.

Each stage takes the persisted run and returns a validated successor. A stage
that already ran is a no-op (``stage_markers``), so a LangGraph replay after an
interrupt never repeats a model call, and a finished run is never reopened.

No stage reads or writes anything but the Phase 2J run: claims, Phase 2C
evidence, the Phase 2E groups and the Phase 2G/2H/2I records are inputs only,
and an upstream fingerprint taken at bind time is re-checked at finalize so a
mutation cannot pass unnoticed. No stage searches: the only inputs are the
bounded inventory built from existing artifacts (section 4.2).
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.provider import StructuredModelProvider
from src.research.gap import counter as counter_stage_impl
from src.research.gap import extract as extract_impl
from src.research.gap import linkage as linkage_impl
from src.research.gap.verify import off_contract_issue
from src.research.gap.inventory import build_inventory, full_text, gap_run_id_for, select_texts
from src.research.gap.synthesis import assess_claim, build_claim_hypothesis, summarize, unbound_draft
from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import claim_text_digest, is_material_text
from src.schemas.common import ProjectType
from src.schemas.gap_assessment import (
    DIFFERENTIATING_STATUSES,
    CounterevidenceCoverage,
    GapAssessmentBounds,
    GapAssessmentIssue,
    GapAssessmentRun,
    GapClaimDraft,
    GapIssueCode,
    GapRunStatus,
    GapRunVersions,
    InsufficientReason,
    RejectedGapProposal,
    UpstreamBinding,
    UpstreamPhase,
)
from src.schemas.novelty_differentiation import ClaimEligibilityStatus, NoveltyRunStatus
from src.schemas.research import ResearchRun

STAGE_INVENTORY = "EVIDENCE_INVENTORY"
STAGE_EXTRACTION = "CANDIDATE_EXTRACTION"
STAGE_LINKAGE = "PROJECT_LINKAGE"
STAGE_COUNTEREVIDENCE = "COUNTEREVIDENCE_REVIEW"
STAGE_SYNTHESIS = "CLAIM_SYNTHESIS"
STAGE_PROJECT = "PROJECT_SYNTHESIS"

MAX_RECORDED_REJECTIONS = 500


def _evolve(run: GapAssessmentRun, **changes: Any) -> GapAssessmentRun:
    return GapAssessmentRun.model_validate({**dict(run), **changes})


def _marked(run: GapAssessmentRun, stage: str) -> list[str]:
    return [*run.stage_markers, stage]


def _issue(code: GapIssueCode, node: str, message: str, claim_id: str | None = None) -> GapAssessmentIssue:
    return GapAssessmentIssue(code=code, node=node, message=message[:200], claim_id=claim_id)


def fingerprint(model: Any) -> str:
    """A content hash of one upstream subrun, taken at bind and re-checked at finalize."""
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def bindings_for(research_run: ResearchRun) -> list[UpstreamBinding]:
    """Every consumed upstream subrun, fingerprinted. Absent subruns are not bound."""
    pairs: list[tuple[UpstreamPhase, Any, UUID | None]] = [
        (UpstreamPhase.PHASE_2C_EVIDENCE, research_run.evidence_extraction,
         getattr(research_run.evidence_extraction, "evidence_extraction_run_id", None)),
        (UpstreamPhase.PHASE_2E_SUFFICIENCY, research_run.claim_sufficiency,
         getattr(research_run.claim_sufficiency, "sufficiency_run_id", None)),
        (UpstreamPhase.PHASE_2G_PATENT, research_run.patent_prior_art,
         getattr(research_run.patent_prior_art, "patent_run_id", None)),
        (UpstreamPhase.PHASE_2H_PRODUCT, research_run.product_prior_art,
         getattr(research_run.product_prior_art, "product_run_id", None)),
        (UpstreamPhase.PHASE_2H_OPEN_SOURCE, research_run.open_source_prior_art,
         getattr(research_run.open_source_prior_art, "oss_run_id", None)),
        (UpstreamPhase.PHASE_2I_NOVELTY_DIFFERENTIATION, research_run.novelty_differentiation,
         getattr(research_run.novelty_differentiation, "nd_run_id", None)),
    ]
    return [
        UpstreamBinding(phase=phase, upstream_run_id=run_id, fingerprint=fingerprint(subrun))
        for phase, subrun, run_id in pairs
        if subrun is not None and run_id is not None
    ]


def _claim_index(claims: list[ClaimRecord]) -> list[ClaimRecord]:
    seen: dict[str, ClaimRecord] = {}
    for claim in sorted(claims, key=lambda c: c.claim_id):
        seen.setdefault(claim.claim_id, claim)
    return list(seen.values())


def _upstream_reason(research_run: ResearchRun) -> InsufficientReason | None:
    """Why Phase 2I cannot be consumed at all, or None when it can."""
    nd = research_run.novelty_differentiation
    if nd is None:
        return InsufficientReason.NO_PHASE_2I_RUN
    if nd.research_run_id != research_run.research_run_id:
        return InsufficientReason.UPSTREAM_RUN_MISMATCH
    if not nd.is_terminal or nd.status is not NoveltyRunStatus.COMPLETED:
        return InsufficientReason.PHASE_2I_NOT_COMPLETED
    if research_run.evidence_extraction is not None and (
        research_run.evidence_extraction.research_run_id != research_run.research_run_id
    ):
        return InsufficientReason.UPSTREAM_RUN_MISMATCH
    return None


def _claim_reason(research_run: ResearchRun, claim: ClaimRecord) -> InsufficientReason | None:
    nd = research_run.novelty_differentiation
    assert nd is not None
    given = next((c for c in nd.claim_inputs if c.claim_id == claim.claim_id), None)
    if given is None:
        return InsufficientReason.CLAIM_NOT_IN_PHASE_2I
    if given.claim_text_hash != claim_text_digest(claim.claim):
        return InsufficientReason.CLAIM_TEXT_HASH_MISMATCH
    if given.status is not ClaimEligibilityStatus.ELIGIBLE or not any(
        i.claim_id == claim.claim_id for i in nd.inventories
    ):
        return InsufficientReason.NO_FEATURE_INVENTORY
    if not any(s.claim_id == claim.claim_id for s in nd.claim_syntheses):
        return InsufficientReason.NO_PHASE_2I_SYNTHESIS
    return None


def _has_differentiating(research_run: ResearchRun, claim_id: str) -> bool:
    nd = research_run.novelty_differentiation
    synthesis = next((s for s in nd.claim_syntheses if s.claim_id == claim_id), None) if nd else None
    return bool(synthesis and any(d.status in DIFFERENTIATING_STATUSES for d in synthesis.feature_differentiations))


def open_gap_run(
    research_run: ResearchRun, claims: list[ClaimRecord], project_type: ProjectType,
    bounds: GapAssessmentBounds, started_at: datetime, *, provider_name: str | None = None,
    model_name: str | None = None,
) -> GapAssessmentRun:
    """Bind the Phase 2J run to the upstream artifacts it will consume.

    When Phase 2I cannot be consumed the run is terminal at once: every claim is
    ``INSUFFICIENT_INPUT`` with the reason stated, never "no gap".
    """
    nd = research_run.novelty_differentiation
    gap_run_id = gap_run_id_for(research_run.research_run_id)
    reason = _upstream_reason(research_run)
    indexed = _claim_index(claims)
    drafts: list[GapClaimDraft] = []
    for claim in indexed:
        claim_reason = reason or _claim_reason(research_run, claim)
        draft = GapClaimDraft(claim_id=claim.claim_id, claim_text_hash=claim_text_digest(claim.claim))
        if claim_reason is not None:
            draft = unbound_draft(claim.claim_id, draft.claim_text_hash, claim_reason)
        else:
            draft = draft.model_copy(update={"has_differentiating_feature": _has_differentiating(research_run, claim.claim_id)})
        drafts.append(draft)
    base = GapAssessmentRun(
        gap_run_id=gap_run_id,
        research_run_id=research_run.research_run_id,
        nd_run_id=nd.nd_run_id if nd is not None and reason is None else None,
        status=GapRunStatus.RUNNING if reason is None else GapRunStatus.INSUFFICIENT_INPUT,
        versions=GapRunVersions(model_provider=provider_name, model_name=model_name),
        bounds=bounds,
        canonical_project_type=project_type,
        upstream_bindings=bindings_for(research_run),
        drafts=drafts,
        started_at=started_at,
        errors=[] if reason is None else [_issue(GapIssueCode.INVALID_INPUT, "OPEN", f"Phase 2I not consumable: {reason.value}")],
    )
    if reason is None:
        return base
    return _terminal_unbound(base, started_at)


def _terminal_unbound(run: GapAssessmentRun, completed_at: datetime) -> GapAssessmentRun:
    """Every claim unbound, no hypotheses: used when Phase 2I cannot be consumed
    and when finalize detects an upstream mutation."""
    assessments = [
        assess_claim(gap_run_id=run.gap_run_id, research_run_id=run.research_run_id, draft=d, hypothesis=None,
                     project_type=run.canonical_project_type)
        for d in run.drafts
    ]
    return _evolve(
        run, status=GapRunStatus.INSUFFICIENT_INPUT, hypotheses=[], claim_assessments=assessments,
        eligible_evidence_ref_ids=[], counterevidence_coverage=[],
        project_summary=summarize(run.gap_run_id, assessments, []),
        stage_markers=[STAGE_INVENTORY, STAGE_EXTRACTION, STAGE_LINKAGE, STAGE_COUNTEREVIDENCE, STAGE_SYNTHESIS, STAGE_PROJECT],
        completed_at=max(completed_at, run.started_at),
    )


def _resolve_all(research_run: ResearchRun, run: GapAssessmentRun) -> dict[UUID, str | None]:
    nd = research_run.novelty_differentiation
    assert nd is not None
    return {t.inventory_text_id: full_text(research_run, nd, t) for t in run.inventory_texts}


def inventory_stage(run: GapAssessmentRun, research_run: ResearchRun) -> GapAssessmentRun:
    if STAGE_INVENTORY in run.stage_markers or run.is_terminal:
        return run
    nd = research_run.novelty_differentiation
    assert nd is not None
    items, issues = build_inventory(research_run, nd, run.gap_run_id)
    errors = list(run.errors)
    if issues:
        errors.append(_issue(GapIssueCode.INVALID_INPUT, STAGE_INVENTORY, f"{len(issues)} upstream text(s) skipped: unreadable or changed"))
    return _evolve(run, inventory_texts=items, errors=errors, stage_markers=_marked(run, STAGE_INVENTORY))


def _replace(drafts: list[GapClaimDraft], updated: GapClaimDraft) -> list[GapClaimDraft]:
    return [updated if d.claim_id == updated.claim_id else d for d in drafts]


def _record(run_rejected: list[RejectedGapProposal], new: list[RejectedGapProposal]) -> list[RejectedGapProposal]:
    return [*run_rejected, *new][:MAX_RECORDED_REJECTIONS]


def extraction_stage(
    run: GapAssessmentRun, research_run: ResearchRun, claims: list[ClaimRecord],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> GapAssessmentRun:
    if STAGE_EXTRACTION in run.stage_markers or run.is_terminal:
        return run
    by_id = {c.claim_id: c for c in _claim_index(claims)}
    resolved = _resolve_all(research_run, run)
    drafts, errors, rejected = list(run.drafts), list(run.errors), list(run.rejected_proposals)
    performed = run.model_calls_performed
    missing_reported = False
    for draft in sorted(run.drafts, key=lambda d: d.claim_id):
        if draft.insufficient_reasons or draft.extraction_done:
            continue
        claim = by_id[draft.claim_id]
        if provider is None:
            drafts = _replace(drafts, draft.model_copy(update={
                "insufficient_reasons": [*draft.insufficient_reasons, InsufficientReason.MODEL_PROVIDER_MISSING]}))
            if not missing_reported:
                errors.append(_issue(GapIssueCode.MODEL_PROVIDER_MISSING, STAGE_EXTRACTION,
                                     "no structured model provider; no claim can be assessed"))
                missing_reported = True
            continue
        visible = [t for t in run.inventory_texts if t.visible_to(draft.claim_id)]
        shown, _ = select_texts(visible, resolved, run.bounds)
        if not shown:
            drafts = _replace(drafts, draft.model_copy(update={"extraction_done": True}))
            continue
        if performed >= run.bounds.max_model_calls:
            drafts = _replace(drafts, draft.model_copy(update={
                "insufficient_reasons": [InsufficientReason.MODEL_CALL_BOUND_REACHED], "extraction_done": True}))
            continue
        outcome = extract_impl.extract_claim(
            gap_run_id=run.gap_run_id, claim=claim, draft=draft, shown=shown, provider=provider,
            llm_settings=llm_settings, bounds=run.bounds,
        )
        performed += 1
        drafts = _replace(drafts, outcome.draft)
        errors.extend(outcome.issues)
        errors.extend(off_contract_issue(STAGE_EXTRACTION, draft.claim_id, outcome.rejected))
        rejected = _record(rejected, outcome.rejected)
    return _evolve(run, drafts=drafts, errors=errors, rejected_proposals=rejected,
                   model_calls_performed=performed, stage_markers=_marked(run, STAGE_EXTRACTION))


def linkage_stage(
    run: GapAssessmentRun, research_run: ResearchRun, claims: list[ClaimRecord],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> GapAssessmentRun:
    if STAGE_LINKAGE in run.stage_markers or run.is_terminal:
        return run
    nd = research_run.novelty_differentiation
    assert nd is not None
    by_id = {c.claim_id: c for c in _claim_index(claims)}
    drafts, errors, rejected = list(run.drafts), list(run.errors), list(run.rejected_proposals)
    performed = run.model_calls_performed
    for draft in sorted(run.drafts, key=lambda d: d.claim_id):
        if draft.insufficient_reasons or draft.linkage_done or provider is None:
            continue
        inventory = next((i for i in nd.inventories if i.claim_id == draft.claim_id), None)
        synthesis = next((s for s in nd.claim_syntheses if s.claim_id == draft.claim_id), None)
        features = linkage_impl.differentiating_features(inventory, synthesis)
        if draft.limitations and features and performed >= run.bounds.max_model_calls:
            drafts = _replace(drafts, draft.model_copy(update={
                "insufficient_reasons": [InsufficientReason.MODEL_CALL_BOUND_REACHED], "linkage_done": True}))
            continue
        outcome = linkage_impl.link_claim(
            gap_run_id=run.gap_run_id, nd=nd, claim=by_id[draft.claim_id], draft=draft, features=features,
            provider=provider, llm_settings=llm_settings, bounds=run.bounds,
        )
        performed += int(outcome.model_called)
        drafts = _replace(drafts, outcome.draft)
        errors.extend(outcome.issues)
        errors.extend(off_contract_issue(STAGE_LINKAGE, draft.claim_id, outcome.rejected))
        rejected = _record(rejected, outcome.rejected)
    return _evolve(run, drafts=drafts, errors=errors, rejected_proposals=rejected,
                   model_calls_performed=performed, stage_markers=_marked(run, STAGE_LINKAGE))


def counterevidence_stage(
    run: GapAssessmentRun, research_run: ResearchRun, claims: list[ClaimRecord],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> GapAssessmentRun:
    if STAGE_COUNTEREVIDENCE in run.stage_markers or run.is_terminal:
        return run
    by_id = {c.claim_id: c for c in _claim_index(claims)}
    resolved = _resolve_all(research_run, run)
    drafts, errors, rejected = list(run.drafts), list(run.errors), list(run.rejected_proposals)
    coverage = list(run.counterevidence_coverage)
    performed = run.model_calls_performed
    for draft in sorted(run.drafts, key=lambda d: d.claim_id):
        if draft.insufficient_reasons or draft.counter_done or not draft.limitations:
            continue
        visible = [t for t in run.inventory_texts if t.visible_to(draft.claim_id)]
        visible_ids = [t.inventory_text_id for t in visible]
        shown, omitted = select_texts(visible, resolved, run.bounds)
        if provider is None or performed >= run.bounds.max_model_calls:
            updated, outcome_issues, outcome_rejected = counter_stage_impl.unexecuted(draft, visible_ids), [], []
            if provider is not None:
                outcome_issues = [_issue(GapIssueCode.INVALID_INPUT, STAGE_COUNTEREVIDENCE,
                                         "run-wide model call bound reached; counterevidence review not executed",
                                         draft.claim_id)]
        else:
            outcome = counter_stage_impl.review_claim(
                gap_run_id=run.gap_run_id, claim=by_id[draft.claim_id], draft=draft, shown=shown,
                omitted_ids=omitted, visible_ids=visible_ids, provider=provider, llm_settings=llm_settings,
                bounds=run.bounds,
            )
            performed += int(outcome.model_called)
            updated, outcome_issues, outcome_rejected = outcome.draft, outcome.issues, outcome.rejected
        drafts = _replace(drafts, updated)
        errors.extend(outcome_issues)
        errors.extend(off_contract_issue(STAGE_COUNTEREVIDENCE, draft.claim_id, outcome_rejected))
        rejected = _record(rejected, outcome_rejected)
        coverage.append(CounterevidenceCoverage(
            claim_id=draft.claim_id, examined_text_ids=updated.counter_examined_text_ids,
            omitted_text_ids=updated.counter_omitted_text_ids,
        ))
    return _evolve(run, drafts=drafts, errors=errors, rejected_proposals=rejected,
                   counterevidence_coverage=sorted(coverage, key=lambda c: c.claim_id),
                   model_calls_performed=performed, stage_markers=_marked(run, STAGE_COUNTEREVIDENCE))


def synthesis_stage(run: GapAssessmentRun, research_run: ResearchRun) -> GapAssessmentRun:
    """Classification and the claim posture, decided in Python."""
    if STAGE_SYNTHESIS in run.stage_markers or run.is_terminal:
        return run
    inventory = {(t.source_kind, t.source_record_id): t for t in run.inventory_texts}
    hypotheses, assessments = [], []
    for draft in sorted(run.drafts, key=lambda d: d.claim_id):
        hypothesis = None if draft.insufficient_reasons else build_claim_hypothesis(
            gap_run_id=run.gap_run_id, research_run_id=run.research_run_id, draft=draft, inventory=inventory)
        if hypothesis is not None:
            hypotheses.append(hypothesis)
        assessments.append(assess_claim(
            gap_run_id=run.gap_run_id, research_run_id=run.research_run_id, draft=draft, hypothesis=hypothesis,
            project_type=run.canonical_project_type))
    ref_ids = sorted({r.evidence_ref_id for h in hypotheses for r in h.evidence_refs}, key=str)
    return _evolve(run, hypotheses=hypotheses, claim_assessments=assessments, eligible_evidence_ref_ids=ref_ids,
                   stage_markers=_marked(run, STAGE_SYNTHESIS))


def project_stage(run: GapAssessmentRun) -> GapAssessmentRun:
    if STAGE_PROJECT in run.stage_markers or run.is_terminal:
        return run
    summary = summarize(run.gap_run_id, run.claim_assessments, run.hypotheses)
    return _evolve(run, project_summary=summary, stage_markers=_marked(run, STAGE_PROJECT))


def finalize_stage(
    run: GapAssessmentRun, research_run: ResearchRun, claims: list[ClaimRecord], completed_at: datetime
) -> GapAssessmentRun:
    """Re-check the upstream fingerprints and the claim texts, then close.

    A changed upstream subrun, or a claim whose text no longer matches the hash
    the assessment was bound to, makes the result untrustworthy: the affected
    claims become ``INSUFFICIENT_INPUT`` rather than keeping a stale posture.
    """
    if run.is_terminal:
        return run
    current = {b.phase: b.fingerprint for b in bindings_for(research_run)}
    if any(current.get(b.phase) != b.fingerprint for b in run.upstream_bindings):
        mutated = [
            d.model_copy(update={"insufficient_reasons": [InsufficientReason.UPSTREAM_MUTATED]}) for d in run.drafts
        ]
        errors = [*run.errors, _issue(GapIssueCode.UPSTREAM_MUTATED, "FINALIZE_GAP_ASSESSMENT",
                                      "an upstream subrun changed while the gap assessment ran")]
        return _terminal_unbound(_evolve(run, drafts=mutated, errors=errors), completed_at)
    hashes = {c.claim_id: claim_text_digest(c.claim) for c in _claim_index(claims)}
    stale = {a.claim_id for a in run.claim_assessments if hashes.get(a.claim_id) != a.claim_text_hash}
    if stale:
        drafts = [
            d.model_copy(update={"insufficient_reasons": [InsufficientReason.CLAIM_TEXT_HASH_MISMATCH]})
            if d.claim_id in stale else d
            for d in run.drafts
        ]
        errors = [*run.errors, _issue(GapIssueCode.STALE_UPSTREAM_HASH, "FINALIZE_GAP_ASSESSMENT",
                                      "a claim text changed after it was bound")]
        rebuilt = _evolve(run, drafts=drafts, errors=errors, stage_markers=[
            m for m in run.stage_markers if m not in (STAGE_SYNTHESIS, STAGE_PROJECT)])
        rebuilt = synthesis_stage(_evolve(rebuilt, hypotheses=[], claim_assessments=[]), research_run)
        run = project_stage(rebuilt)
    return _evolve(run, status=GapRunStatus.COMPLETED, completed_at=max(completed_at, run.started_at))


__all__ = [
    "STAGE_COUNTEREVIDENCE",
    "STAGE_EXTRACTION",
    "STAGE_INVENTORY",
    "STAGE_LINKAGE",
    "STAGE_PROJECT",
    "STAGE_SYNTHESIS",
    "bindings_for",
    "counterevidence_stage",
    "extraction_stage",
    "finalize_stage",
    "fingerprint",
    "inventory_stage",
    "linkage_stage",
    "open_gap_run",
    "project_stage",
    "synthesis_stage",
]
