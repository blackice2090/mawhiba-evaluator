"""Phase 3A stages over a ``MethodologyReviewRun``.

Each stage takes the persisted run and returns a validated successor. A stage that
already ran is a no-op (``stage_markers``), so a LangGraph replay never repeats a
model call, and a finished run is never reopened. Every stage is idempotent.

Stages (the graph wraps each in one node)::

    open                  bind authoritative inputs, fingerprint them
    inventory_stage       deterministic requirement inventory (closed catalog)
    overlay_stage         AI/ML and software overlay materiality and ownership
    evidence_stage        methodology evidence, exact submission excerpts
    applicability_stage   CONDITIONAL requirements resolved by closed triggers
    assess_stage          documentation status, separate from adequacy
    link_stage            metric / baseline plans, claim and gap coverage, conditions
    continuity_stage      strong coverage gated on the exact Phase 2J requirement
    synthesis_stage       issues and track postures, decided in Python
    finalize_stage        upstream fingerprints re-checked, then closed

No stage reads ``ProjectState.results`` or ``.experiments``, calls a search
connector, or writes anything but the Phase 3A run (ADR-022).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.config.settings import LLMSettings
from src.graph.state import ProjectState
from src.llm.provider import StructuredModelProvider
from src.research.methodology import evidence as evidence_impl
from src.research.methodology import inventory as inv
from src.research.methodology import linkage as link_impl
from src.research.methodology import overlays as overlay_impl
from src.research.methodology import synthesis as synth
from src.research.methodology.verify import StageLedger
from src.schemas.methodology_review import (
    Applicability,
    MethodologyDraft,
    MethodologyReviewBounds,
    MethodologyReviewRun,
    MethodologyRunIssue,
    MethodologyRunIssueCode,
    MethodologyRunStatus,
)
from src.schemas.research import ResearchRun
from src.schemas.submission import StudentSubmissionArtifact

STAGE_INVENTORY = "REQUIREMENT_INVENTORY"
STAGE_OVERLAYS = "OVERLAY_OWNERSHIP"
STAGE_EVIDENCE = "METHODOLOGY_EVIDENCE"
STAGE_APPLICABILITY = "CONDITIONAL_APPLICABILITY"
STAGE_ASSESS = "COMPONENT_ASSESSMENT"
STAGE_LINK = "TARGET_LINKAGE"
STAGE_CONTINUITY = "VALIDATION_CONTINUITY"
STAGE_SYNTHESIS = "POSTURE_SYNTHESIS"
ALL_STAGES = (STAGE_INVENTORY, STAGE_OVERLAYS, STAGE_EVIDENCE, STAGE_APPLICABILITY, STAGE_ASSESS, STAGE_LINK,
              STAGE_CONTINUITY, STAGE_SYNTHESIS)


def _evolve(run: MethodologyReviewRun, **changes: Any) -> MethodologyReviewRun:
    return MethodologyReviewRun.model_validate({**dict(run), **changes})


def _draft(run: MethodologyReviewRun, **changes: Any) -> MethodologyDraft:
    base = run.draft or MethodologyDraft(methodology_run_id=run.methodology_run_id)
    return MethodologyDraft.model_validate({**dict(base), **changes})


def _issue(code: MethodologyRunIssueCode, node: str, message: str) -> MethodologyRunIssue:
    return MethodologyRunIssue(code=code, node=node, message=message[:200])


def _done(run: MethodologyReviewRun, stage: str) -> bool:
    return stage in run.stage_markers or run.is_terminal


def _claim_texts(project: ProjectState) -> dict[str, str]:
    return {c.claim_id: c.claim for c in project.claims}


def _ledger(run: MethodologyReviewRun, submission: StudentSubmissionArtifact, bounds: MethodologyReviewBounds
            ) -> StageLedger:
    return StageLedger(run, submission.original_text, bounds, language=submission.language)


NO_PROVIDER = "no structured model provider"
BOUND_REACHED = "run-wide model call bound reached"


def _gap_texts(research_run: ResearchRun) -> list[str]:
    """Bound Phase 2J validation-requirement text: candidate-discovery input only."""
    gap = research_run.research_engineering_gap
    out: list[str] = []
    for h in (gap.hypotheses if gap is not None else []):
        req = h.validation_requirement
        if req is not None:
            out += [req.metric.text, *([req.baseline.text] if req.baseline else [])]
    return out


def _reason(run: MethodologyReviewRun, bounds: MethodologyReviewBounds, provider: Any, failure: str | None
            ) -> str | None:
    """No provider and an exhausted call bound are different conditions with different codes."""
    if failure == NO_PROVIDER and provider is not None and run.model_calls_performed >= bounds.max_model_calls:
        return BOUND_REACHED
    return failure


def _model_issue(node: str, failure: str | None) -> MethodologyRunIssue:
    # a provider's own text is never persisted: only a code and the call status
    if failure == NO_PROVIDER:
        return _issue(MethodologyRunIssueCode.MODEL_PROVIDER_MISSING, node, NO_PROVIDER)
    if failure == BOUND_REACHED:
        return _issue(MethodologyRunIssueCode.MODEL_CALL_BOUND_REACHED, node, BOUND_REACHED)
    return _issue(MethodologyRunIssueCode.MODEL_ERROR, node, f"model call did not yield a usable response: {failure}")


def _callable(run: MethodologyReviewRun, bounds: MethodologyReviewBounds,
              provider: StructuredModelProvider | None) -> StructuredModelProvider | None:
    return provider if run.model_calls_performed < bounds.max_model_calls else None


# -- open ------------------------------------------------------------------------------------------


def open_run(
    research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact | None,
    started_at: datetime, *, provider_name: str | None = None, model_name: str | None = None,
) -> MethodologyReviewRun:
    """Bind the run. Unbound inputs end it INSUFFICIENT_INPUT at once, with the reason stated."""
    run = inv.open_methodology_run(research_run, project, submission, started_at, provider_name=provider_name,
                                   model_name=model_name)
    if run.status is MethodologyRunStatus.RUNNING:
        return run
    return _evolve(run, track_assessments=synth.insufficient_assessments(run), stage_markers=list(ALL_STAGES),
                   completed_at=max(started_at, run.started_at))


# -- stages ----------------------------------------------------------------------------------------


def inventory_stage(run: MethodologyReviewRun) -> MethodologyReviewRun:
    if _done(run, STAGE_INVENTORY):
        return run
    return _evolve(run, draft=_draft(run, applicability=inv.compute_applicability(run)),
                   stage_markers=[*run.stage_markers, STAGE_INVENTORY])


def overlay_stage(
    run: MethodologyReviewRun, research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, bounds: MethodologyReviewBounds,
) -> MethodologyReviewRun:
    if _done(run, STAGE_OVERLAYS):
        return run
    ledger = _ledger(run, submission, bounds)
    outcome = overlay_impl.assess_overlays(
        run, inv.overlay_candidates(project), ledger, _callable(run, bounds, provider), llm_settings,
        _claim_texts(project),
        signaled=inv.signaled_overlays(project, _claim_texts(project), submission, _gap_texts(research_run)))
    staged = _evolve(run, overlays=outcome.assignments, excerpts=ledger.sorted_excerpts())
    errors = [*run.errors, *ledger.run_issues(overlay_impl.NODE)]
    if outcome.failure:
        errors.append(_model_issue(overlay_impl.NODE, _reason(run, bounds, provider, outcome.failure)))
    draft = _draft(
        staged, applicability=inv.compute_applicability(staged),
        model_calls_succeeded=(run.draft.model_calls_succeeded if run.draft else 0) + int(outcome.model_succeeded),
        model_calls_failed=(run.draft.model_calls_failed if run.draft else 0)
        + int(outcome.model_called and not outcome.model_succeeded))
    return _evolve(
        staged, draft=draft, rejected_proposals=ledger.merged_rejections(),
        errors=errors, model_calls_performed=run.model_calls_performed + int(outcome.model_called),
        stage_markers=[*run.stage_markers, STAGE_OVERLAYS])


def evidence_stage(
    run: MethodologyReviewRun, project: ProjectState, submission: StudentSubmissionArtifact,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, bounds: MethodologyReviewBounds,
) -> MethodologyReviewRun:
    if _done(run, STAGE_EVIDENCE):
        return run
    assert run.draft is not None
    ledger = _ledger(run, submission, bounds)
    docs, outcome = evidence_impl.extract_evidence(
        run, run.draft.applicability, ledger, _callable(run, bounds, provider), llm_settings, _claim_texts(project))
    has_candidates = any(a.track is not None and a.applicability is not Applicability.NOT_APPLICABLE
                         for a in run.draft.applicability)
    unread = has_candidates and not outcome.model_succeeded
    errors = [*run.errors, *ledger.run_issues(evidence_impl.EVIDENCE_NODE)]
    if unread and outcome.failure:
        errors.append(_model_issue(evidence_impl.EVIDENCE_NODE, _reason(run, bounds, provider, outcome.failure)))
    draft = _draft(
        run, documentation=docs, source_unread=unread,
        source_truncated=len(submission.original_text) > bounds.max_submission_chars,
        model_calls_succeeded=run.draft.model_calls_succeeded + int(outcome.model_succeeded),
        model_calls_failed=run.draft.model_calls_failed + int(outcome.model_called and not outcome.model_succeeded))
    return _evolve(
        run, draft=draft, excerpts=ledger.sorted_excerpts(), rejected_proposals=ledger.merged_rejections(),
        errors=errors, model_calls_performed=run.model_calls_performed + int(outcome.model_called),
        stage_markers=[*run.stage_markers, STAGE_EVIDENCE])


def applicability_stage(
    run: MethodologyReviewRun, project: ProjectState, submission: StudentSubmissionArtifact,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, bounds: MethodologyReviewBounds,
) -> MethodologyReviewRun:
    if _done(run, STAGE_APPLICABILITY):
        return run
    assert run.draft is not None
    ledger = _ledger(run, submission, bounds)
    pending = inv.conditional_unresolved(run.draft.applicability)
    resolved, outcome = evidence_impl.resolve_conditionals(
        run, pending, ledger, None if run.draft.source_unread else _callable(run, bounds, provider), llm_settings,
        _claim_texts(project))
    errors = [*run.errors, *ledger.run_issues(evidence_impl.APPLICABILITY_NODE)]
    if pending and outcome.failure and not run.draft.source_unread:
        errors.append(_model_issue(evidence_impl.APPLICABILITY_NODE, _reason(run, bounds, provider, outcome.failure)))
    staged = _evolve(run, excerpts=ledger.sorted_excerpts())  # judgment excerpts must exist before they are cited
    draft = _draft(
        staged, applicability=inv.compute_applicability(staged, resolved),
        model_calls_succeeded=run.draft.model_calls_succeeded + int(outcome.model_succeeded),
        model_calls_failed=run.draft.model_calls_failed + int(outcome.model_called and not outcome.model_succeeded))
    return _evolve(
        staged, draft=draft, rejected_proposals=ledger.merged_rejections(), errors=errors,
        model_calls_performed=run.model_calls_performed + int(outcome.model_called),
        stage_markers=[*run.stage_markers, STAGE_APPLICABILITY])


def assess_stage(run: MethodologyReviewRun) -> MethodologyReviewRun:
    """Documentation completed for every applicable requirement; adequacy stays its own field."""
    if _done(run, STAGE_ASSESS):
        return run
    assert run.draft is not None
    docs = synth.complete_documentation(
        run.draft.applicability, run.draft.documentation, run, source_unread=run.draft.source_unread,
        source_truncated=run.draft.source_truncated)
    return _evolve(run, draft=_draft(run, documentation=docs), stage_markers=[*run.stage_markers, STAGE_ASSESS])


def link_stage(
    run: MethodologyReviewRun, research_run: ResearchRun, project: ProjectState,
    submission: StudentSubmissionArtifact, provider: StructuredModelProvider | None,
    llm_settings: LLMSettings | None, bounds: MethodologyReviewBounds,
) -> MethodologyReviewRun:
    if _done(run, STAGE_LINK):
        return run
    assert run.draft is not None
    gap = research_run.research_engineering_gap
    assert gap is not None
    ledger = _ledger(run, submission, bounds)
    performed, succeeded, failed = run.model_calls_performed, 0, 0
    metrics, baselines, coverage, conditions, unjudged = [], [], [], [], set()
    docs = run.draft.documentation
    for ct in link_impl.targets_for(run, _claim_texts(project)):
        if run.draft.source_unread:
            may = False
        else:
            may = performed < bounds.max_model_calls
        plan = link_impl.plan_claim(run, gap, ct, ledger, provider, llm_settings, may_call=may)
        performed += int(plan.model_called)
        succeeded += int(plan.model_succeeded)
        failed += int(plan.model_called and not plan.model_succeeded)
        metrics += plan.metrics
        baselines += plan.baselines
        unjudged |= set(plan.unjudged)
        may = (not run.draft.source_unread) and performed < bounds.max_model_calls
        cov = link_impl.link_claim(
            run, gap, ct, docs, ledger, provider, llm_settings, may_call=may,
            coverage_known=not run.draft.source_unread)
        performed += int(cov.model_called)
        succeeded += int(cov.model_succeeded)
        failed += int(cov.model_called and not cov.model_succeeded)
        coverage += cov.links
        conditions += cov.conditions
        unjudged |= set(cov.unjudged)
    errors = [*run.errors, *ledger.run_issues(link_impl.PLAN_NODE)]
    if not run.draft.source_unread and (provider is None or performed >= bounds.max_model_calls)             and any(ct.claim_id for ct in link_impl.targets_for(run, _claim_texts(project))):
        errors.append(_model_issue(link_impl.PLAN_NODE, _reason(run, bounds, provider, NO_PROVIDER)))
    if failed:
        errors.append(_issue(MethodologyRunIssueCode.MODEL_ERROR, link_impl.PLAN_NODE,
                             f"{failed} target-linkage model call(s) did not yield a usable response"))
    draft = _draft(
        run, coverage=sorted(coverage, key=lambda c: str(c.link_id)),
        conditions=sorted(conditions, key=lambda c: (str(c.gap_hypothesis_id), str(c.condition_id))),
        unjudged_targets=sorted(unjudged), model_calls_succeeded=run.draft.model_calls_succeeded + succeeded,
        model_calls_failed=run.draft.model_calls_failed + failed)
    return _evolve(
        run, draft=draft, excerpts=ledger.sorted_excerpts(),
        metric_alignments=sorted(metrics, key=lambda m: str(m.record_id)),
        baselines=sorted(baselines, key=lambda b: str(b.record_id)), rejected_proposals=ledger.merged_rejections(),
        errors=errors, model_calls_performed=performed, stage_markers=[*run.stage_markers, STAGE_LINK])


def continuity_stage(run: MethodologyReviewRun) -> MethodologyReviewRun:
    if _done(run, STAGE_CONTINUITY):
        return run
    assert run.draft is not None
    coverage, _ = synth.evaluate_continuity(
        run, run.draft.coverage, run.draft.conditions, run.metric_alignments, run.baselines)
    return _evolve(run, draft=_draft(run, coverage=coverage), stage_markers=[*run.stage_markers, STAGE_CONTINUITY])


def synthesis_stage(run: MethodologyReviewRun) -> MethodologyReviewRun:
    """Issues and track postures, derived in Python from the validated records."""
    if _done(run, STAGE_SYNTHESIS):
        return run
    assert run.draft is not None
    assessments = synth.build_track_assessments(
        run, run.draft.applicability, run.draft.documentation, run.draft.coverage, run.draft.conditions)
    return _evolve(run, track_assessments=assessments, stage_markers=[*run.stage_markers, STAGE_SYNTHESIS])


def finalize_stage(
    run: MethodologyReviewRun, research_run: ResearchRun, project: ProjectState,
    submission: StudentSubmissionArtifact | None, completed_at: datetime,
) -> MethodologyReviewRun:
    """Re-check every bound upstream fingerprint, then close.

    A changed claim, submission, Phase 2I or Phase 2J record makes the run untrustworthy: it is
    INVALIDATED and holds no track posture at all, so no strong posture can survive a mutation."""
    if run.is_terminal:
        return run
    current = inv.current_fingerprints(research_run, submission, inv.bind_claims(list(project.claims)))
    mutated = [b.phase for b in run.upstream_bindings
               if b.phase not in current or current[b.phase][1] != b.fingerprint]
    done_at = max(completed_at, run.started_at)
    if mutated:
        return _evolve(
            run, status=MethodologyRunStatus.INVALIDATED_UPSTREAM_MUTATED, track_assessments=[],
            errors=[*run.errors, _issue(MethodologyRunIssueCode.UPSTREAM_MUTATED, "FINALIZE_METHODOLOGY_REVIEW",
                                        "an upstream input changed while the methodology review ran")],
            completed_at=done_at)
    return _evolve(run, status=MethodologyRunStatus.COMPLETED, completed_at=done_at)


__all__ = [
    "ALL_STAGES",
    "STAGE_APPLICABILITY",
    "STAGE_ASSESS",
    "STAGE_CONTINUITY",
    "STAGE_EVIDENCE",
    "STAGE_INVENTORY",
    "STAGE_LINK",
    "STAGE_OVERLAYS",
    "STAGE_SYNTHESIS",
    "applicability_stage",
    "assess_stage",
    "continuity_stage",
    "evidence_stage",
    "finalize_stage",
    "inventory_stage",
    "link_stage",
    "open_run",
    "overlay_stage",
    "synthesis_stage",
]
