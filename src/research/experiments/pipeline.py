"""Phase 3B stages over an ``ExperimentReviewRun`` (ADR-023).

Each stage takes the persisted run and returns a validated successor. A stage that
already ran is a no-op (``stage_markers``), so a LangGraph replay never repeats a
model call, and a finished run is never reopened.

    open_run              EXPERIMENT_BIND_INPUTS            deterministic   0 calls
    segment_stage         EXPERIMENT_SEGMENT                model           1 call
    extract_stage         EXPERIMENT_EXTRACT_PROTOCOL       model           1 per experiment
    applicability_stage   EXPERIMENT_RESOLVE_APPLICABILITY  model           <= 1 per experiment
    link_stage            EXPERIMENT_LINK_TARGETS           model           1 per experiment
    synthesis_stage       EXPERIMENT_SYNTHESIZE             deterministic   0 calls
    finalize_stage        EXPERIMENT_FINALIZE               deterministic   0 calls

Every successor is canonicalized and re-validated, and every experiment's issues
and posture are re-derived from its records, so model list order and model
labels never reach canonical state. No stage reads ``ProjectState.results`` or
``ProjectState.experiments``, calls a search connector, or writes anything but
the Phase 3B run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.config.settings import LLMSettings
from src.graph.state import ProjectState
from src.llm.provider import StructuredModelProvider
from src.research.experiments import binding, linkage, protocol, segment, synthesis
from src.research.experiments.verify import ExperimentLedger, SourceWindow, quarantine_incomplete
from src.research.methodology.inventory import bind_claims
from src.schemas.experiment_review import (
    ExperimentReviewBounds,
    ExperimentReviewRun,
    ExperimentRunIssue,
    ExperimentRunIssueCode,
    ExperimentRunStatus,
    ExperimentStage,
    canonicalize,
    text_hash,
)
from src.schemas.research import ResearchRun
from src.schemas.submission import StudentSubmissionArtifact

_S = ExperimentStage


def settle(run: ExperimentReviewRun, **changes: Any) -> ExperimentReviewRun:
    """Apply changes, re-derive every experiment's issues and posture, canonicalize, validate."""
    draft = ExperimentReviewRun.model_construct(**{**dict(run), **changes})
    experiments = [synthesis.rederive_experiment(e, draft) for e in draft.experiments]
    draft = ExperimentReviewRun.model_construct(**{**dict(draft), "experiments": experiments})
    return ExperimentReviewRun.model_validate(dict(canonicalize(draft)))


def _done(run: ExperimentReviewRun, stage: ExperimentStage) -> bool:
    return stage in run.stage_markers or run.is_terminal


def _skip(run: ExperimentReviewRun, stage: ExperimentStage) -> ExperimentReviewRun:
    """Fail closed after an incomplete result quarantine: the stage makes no model call (an
    unquarantined result may be in the source) and records nothing but that it was passed."""
    return settle(run, stage_markers=[*run.stage_markers, stage])


def _ledger(run: ExperimentReviewRun, submission: StudentSubmissionArtifact, bounds: ExperimentReviewBounds,
            stage: ExperimentStage) -> ExperimentLedger:
    return ExperimentLedger(run, submission.original_text, bounds, stage)


def _fold(run: ExperimentReviewRun, ledger: ExperimentLedger, stage: ExperimentStage, attempts: int,
          **changes: Any) -> ExperimentReviewRun:
    return settle(run, excerpts=ledger.sorted_excerpts(), rejected_proposals=ledger.merged_rejections(),
                  errors=ledger.run_issues(), model_calls_performed=run.model_calls_performed + attempts,
                  stage_markers=[*run.stage_markers, stage], **changes)


def _in_document_order(run: ExperimentReviewRun) -> list:
    first = {e.excerpt_id: e.start for e in run.excerpts}
    return sorted(run.experiments, key=lambda e: (first[e.defining_excerpt_ids[0]], str(e.experiment_id)))


def claim_texts(project: ProjectState) -> dict[str, str]:
    return {c.claim_id: c.claim for c in project.claims}


def target_texts(research_run: ResearchRun) -> linkage.TargetText:
    """Bound Phase 2J text shown to the linkage model as context; never persisted."""
    texts = linkage.TargetText()
    gap = research_run.research_engineering_gap
    for h in gap.hypotheses if gap is not None else []:
        req = h.validation_requirement
        if req is None:
            continue
        texts.metric[req.requirement_id] = req.metric.text
        if req.baseline is not None:
            texts.baseline[req.requirement_id] = req.baseline.text
        for c in h.conditions:
            texts.condition[c.condition_id] = c.dimension.value
    return texts


# -- stages -----------------------------------------------------------------------------------------


def open_run(research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact | None,
             started_at: datetime, *, provider_name: str | None = None, model_name: str | None = None,
             ) -> ExperimentReviewRun:
    return binding.open_experiment_run(research_run, project, submission, started_at, provider_name=provider_name,
                                       model_name=model_name)


def segment_stage(run: ExperimentReviewRun, submission: StudentSubmissionArtifact,
                  provider: StructuredModelProvider | None, llm: LLMSettings | None, bounds: ExperimentReviewBounds,
                  ) -> ExperimentReviewRun:
    if _done(run, _S.SEGMENT_EXPERIMENTS):
        return run
    ledger = _ledger(run, submission, bounds, _S.SEGMENT_EXPERIMENTS)
    outcome = segment.segment(ledger, provider, llm)
    return _fold(run, ledger, _S.SEGMENT_EXPERIMENTS, outcome.attempts, quarantine=outcome.quarantine,
                 experiments=outcome.experiments)


def extract_stage(run: ExperimentReviewRun, submission: StudentSubmissionArtifact,
                  provider: StructuredModelProvider | None, llm: LLMSettings | None, bounds: ExperimentReviewBounds,
                  ) -> ExperimentReviewRun:
    if _done(run, _S.EXTRACT_PROTOCOL):
        return run
    if quarantine_incomplete(run):
        return _skip(run, _S.EXTRACT_PROTOCOL)
    ledger = _ledger(run, submission, bounds, _S.EXTRACT_PROTOCOL)
    performed, records = run.model_calls_performed, []
    for record in _in_document_order(run):
        assessed, outcome = protocol.extract_protocol(ledger, record, provider, llm, performed)
        performed += outcome.attempts
        records.append(assessed)
    return _fold(run, ledger, _S.EXTRACT_PROTOCOL, performed - run.model_calls_performed, experiments=records)


def applicability_stage(run: ExperimentReviewRun, project: ProjectState, submission: StudentSubmissionArtifact,
                        provider: StructuredModelProvider | None, llm: LLMSettings | None,
                        bounds: ExperimentReviewBounds) -> ExperimentReviewRun:
    if _done(run, _S.RESOLVE_APPLICABILITY):
        return run
    if quarantine_incomplete(run):
        return _skip(run, _S.RESOLVE_APPLICABILITY)
    ledger = _ledger(run, submission, bounds, _S.RESOLVE_APPLICABILITY)
    texts = claim_texts(project)
    claims = [(t.label, texts.get(t.claim_id, "")) for t in linkage.target_set(ledger) if t.validation is None]
    facts = linkage.phase2j_facts(run.bound_validation_targets)
    performed, records = run.model_calls_performed, []
    for record in _in_document_order(run):
        judged, outcome = protocol.resolve_conditionals(ledger, record, claims, provider, llm, performed, facts)
        performed += outcome.attempts if outcome is not None else 0
        records.append(judged)
    return _fold(run, ledger, _S.RESOLVE_APPLICABILITY, performed - run.model_calls_performed, experiments=records)


def link_stage(run: ExperimentReviewRun, research_run: ResearchRun, project: ProjectState,
               submission: StudentSubmissionArtifact, provider: StructuredModelProvider | None,
               llm: LLMSettings | None, bounds: ExperimentReviewBounds) -> ExperimentReviewRun:
    if _done(run, _S.LINK_TARGETS):
        return run
    if quarantine_incomplete(run):
        return _skip(run, _S.LINK_TARGETS)
    ledger = _ledger(run, submission, bounds, _S.LINK_TARGETS)
    texts, context = claim_texts(project), target_texts(research_run)
    performed, records, links, measurements, baselines, conditions = run.model_calls_performed, [], [], [], [], []
    for record in _in_document_order(run):
        result = linkage.link_experiment(ledger, record, texts, context, provider, llm, performed)
        performed += result.outcome.attempts
        records.append(result.record)
        links += result.links
        measurements += result.measurements
        baselines += result.baselines
        conditions += result.conditions
    return _fold(run, ledger, _S.LINK_TARGETS, performed - run.model_calls_performed, experiments=records,
                 links=links, measurements=measurements, baselines=baselines, conditions=conditions)


def synthesis_stage(run: ExperimentReviewRun) -> ExperimentReviewRun:
    """Phase 2J coverage, track postures and untested claims, derived in Python."""
    if _done(run, _S.SYNTHESIZE):
        return run
    coverage = synthesis.coverage_records(run)
    staged = settle(run, phase2j_coverage=coverage)
    return settle(staged, track_postures=synthesis.track_records(staged, coverage),
                  untested_claim_ids=synthesis.untested_claims(staged),
                  stage_markers=[*run.stage_markers, _S.SYNTHESIZE])


def _source_intact(run: ExperimentReviewRun, submission: StudentSubmissionArtifact | None) -> bool:
    if submission is None:
        return not run.excerpts and not run.quarantine
    text = submission.original_text
    window = SourceWindow.of(text, run.bounds)  # the same window the model was shown
    return all(e.matches(text) and window.contains(e.start, e.end) for e in run.excerpts) and all(
        window.contains(q.start, q.end) and text_hash(text[q.start:q.end]) == q.span_hash for q in run.quarantine)


def finalize_stage(run: ExperimentReviewRun, research_run: ResearchRun, project: ProjectState,
                   submission: StudentSubmissionArtifact | None, completed_at: datetime) -> ExperimentReviewRun:
    """Re-check every bound upstream fingerprint and the source/quarantine integrity, then close.

    A changed claim, submission, Phase 2J or Phase 3A record makes the run untrustworthy: it is
    INVALIDATED and keeps no experiment, coverage or posture, so nothing strong survives a mutation.
    A run whose experiment set was truncated by the bound is never read as complete."""
    if run.is_terminal:
        return run
    if _S.SYNTHESIZE not in run.stage_markers:
        run = synthesis_stage(run)
    current = binding.current_fingerprints(research_run, submission, bind_claims(list(project.claims)))
    mutated = [b.phase for b in run.upstream_bindings
               if b.phase not in current or current[b.phase][1] != b.fingerprint]
    done_at = max(completed_at, run.started_at)
    markers = [*run.stage_markers, _S.FINALIZE]
    if mutated or not _source_intact(run, submission):
        issue = ExperimentRunIssue(code=ExperimentRunIssueCode.UPSTREAM_MUTATED, node=_S.FINALIZE,
                                   message="an upstream input changed while the experiment review ran")
        return settle(run, status=ExperimentRunStatus.INVALIDATED_UPSTREAM_MUTATED, experiments=[], links=[],
                      measurements=[], baselines=[], conditions=[], phase2j_coverage=[], track_postures=[],
                      untested_claim_ids=[], errors=[*run.errors, issue], stage_markers=markers,
                      completed_at=done_at)
    if quarantine_incomplete(run):
        # A declared result span could not be quarantined, so a result may be visible to protocol
        # judgments. Nothing derived from them is kept and no posture is issued.
        return settle(run, status=ExperimentRunStatus.INSUFFICIENT_INPUT, experiments=[], links=[],
                      measurements=[], baselines=[], conditions=[], phase2j_coverage=[], track_postures=[],
                      untested_claim_ids=[], project_posture=None, stage_markers=markers, completed_at=done_at)
    if any(e.code is ExperimentRunIssueCode.EXPERIMENT_BOUND_REACHED for e in run.errors):
        return settle(run, status=ExperimentRunStatus.INSUFFICIENT_INPUT, stage_markers=markers, completed_at=done_at)
    return settle(run, status=ExperimentRunStatus.COMPLETED, project_posture=synthesis.project_posture(run),
                  stage_markers=markers, completed_at=done_at)


__all__ = [
    "applicability_stage",
    "claim_texts",
    "extract_stage",
    "finalize_stage",
    "link_stage",
    "open_run",
    "segment_stage",
    "settle",
    "synthesis_stage",
    "target_texts",
]
