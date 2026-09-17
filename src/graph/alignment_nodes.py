"""Phase 2D claim-evidence alignment nodes.

One model call per generated claim/evidence pair. Every node writes to the
``ClaimEvidenceAlignmentRun`` carried by the ``ResearchRun``, so a replay after
an interrupt recomputes from state rather than from anything held between
nodes -- the same replay-safety shape as Phase 2C.

None of these nodes writes the ``project`` channel. Canonical claims, their
status, confidence, evidence_ids and counter_evidence_ids are untouched by
construction: there is no code path from here to any of them, and the
contracts in ``src/schemas/claim_alignment.py`` cannot express a claim
verdict even if one were attempted (ADR-014).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from src.config.settings import DEFAULT_LLM_SETTINGS, LLMSettings
from src.graph.contracts import AuditEvent, NodeResult, NodeStatus, WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY, INTAKE_SETTINGS_KEY
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.llm.prompts import PROMPT_VERSIONS
from src.research.alignment.classifier import classify_pairs
from src.research.alignment.pairing import generate_pairs
from src.research.alignment.pipeline import build_coverage, decide_status, verify_candidates
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.claim_alignment import (
    AlignmentCandidate,
    AlignmentIssue,
    AlignmentIssueCode,
    ClaimAlignmentStatus,
    ClaimEvidenceAlignmentRun,
)
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

ALIGNMENT_PROVIDER_KEY = INTAKE_PROVIDER_KEY
"""Phase 2D reuses the one structured-model provider seam (mirrors Phase 2C)."""

ALIGNMENT_DATASET_VERSION_KEY = "alignment_dataset_version"


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _llm_settings(config: RunnableConfig | None) -> LLMSettings:
    return _configurable(config).get(INTAKE_SETTINGS_KEY) or DEFAULT_LLM_SETTINGS


def _research_settings(config: RunnableConfig | None) -> ResearchSettings:
    return _configurable(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _emit(run: ResearchRun) -> dict[str, Any]:
    return {"research_runs": {str(run.research_run_id): run}}


def _require_run(state: EvaluationGraphState) -> ResearchRun:
    run = state.active_research_run
    if run is None:
        raise ValueError("alignment node reached without an active research run")
    return run


def _revalidated(
    run: ClaimEvidenceAlignmentRun, **changes: Any
) -> ClaimEvidenceAlignmentRun:
    """A successor alignment run, re-validated in full. Nothing mutates in place."""
    return ClaimEvidenceAlignmentRun.model_validate({**dict(run), **changes})


def _done(
    state: EvaluationGraphState,
    node: NodeId,
    started_at: Any,
    summary: str,
    *,
    run: ResearchRun | None = None,
    status: NodeStatus = NodeStatus.SUCCEEDED,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = NodeResult(
        node=node.value, status=status, summary=summary, warnings=warnings or []
    )
    update: dict[str, Any] = dict(extra or {})
    if run is not None:
        update.update(_emit(run))
    return {**update, **_completion(state, node, result, started_at, status=status)}


def _issue(
    code: AlignmentIssueCode, node: NodeId, message: str, claim_id: str | None = None
) -> AlignmentIssue:
    return AlignmentIssue(code=code, node=node.value, message=message, claim_id=claim_id)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_alignment_run(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open an alignment run on a research run that has evidence extraction."""
    node = NodeId.LOAD_ALIGNMENT_RUN
    started_at = workflow_now()
    run = state.active_research_run

    if run is None or run.is_terminal or run.evidence_extraction is None:
        reason = (
            "no active research run"
            if run is None
            else "the research run is already terminal"
            if run.is_terminal
            else "the research run carries no evidence extraction result"
        )
        return _done(
            state,
            node,
            started_at,
            f"Claim-evidence alignment skipped: {reason}.",
            status=NodeStatus.SKIPPED,
            warnings=[reason],
            extra={"status": WorkflowStatus.RUNNING},
        )

    if run.claim_evidence_alignment is not None and run.claim_evidence_alignment.is_terminal:
        # Idempotency guard (section 15): re-invoking a graph that already
        # finished (e.g. a re-invoke on the same thread) must never reopen a
        # terminal alignment run and reprocess its candidates a second time.
        return _done(
            state,
            node,
            started_at,
            f"Claim-evidence alignment already finished with status "
            f"{run.claim_evidence_alignment.status.value}; not reopened.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.RUNNING},
        )

    if not run.evidence_extraction.is_terminal:
        alignment = ClaimEvidenceAlignmentRun(
            research_run_id=run.research_run_id,
            status=ClaimAlignmentStatus.NOT_READY,
            errors=[
                _issue(
                    AlignmentIssueCode.EVIDENCE_EXTRACTION_NOT_READY,
                    node,
                    "evidence extraction has not reached a terminal state; "
                    "alignment does not proceed as though evidence were trusted",
                )
            ],
            completed_at=workflow_now(),
        )
        run = run.evolve(claim_evidence_alignment=alignment)
        return _done(
            state,
            node,
            started_at,
            "Claim-evidence alignment blocked: evidence extraction not ready.",
            run=run,
            status=NodeStatus.SKIPPED,
            warnings=["evidence extraction not ready"],
            extra={"status": WorkflowStatus.RUNNING},
        )

    provider = _configurable(config).get(ALIGNMENT_PROVIDER_KEY)
    alignment = run.claim_evidence_alignment or ClaimEvidenceAlignmentRun(
        research_run_id=run.research_run_id,
        status=ClaimAlignmentStatus.RUNNING,
        classifier_prompt_version=PROMPT_VERSIONS["CLAIM_EVIDENCE_ALIGNMENT_PROMPT"],
        dataset_version=_configurable(config).get(ALIGNMENT_DATASET_VERSION_KEY),
        provider_name=getattr(provider, "name", None),
        model_name=_llm_settings(config).extraction_model if provider else None,
        max_pairs_per_run=_research_settings(config).alignment.max_pairs_per_run,
    )
    alignment = _revalidated(alignment, status=ClaimAlignmentStatus.RUNNING)
    run = run.evolve(claim_evidence_alignment=alignment)

    return _done(
        state,
        node,
        started_at,
        f"Claim-evidence alignment opened over "
        f"{len(state.project.claims)} claim(s).",
        run=run,
        extra={
            "status": WorkflowStatus.RUNNING,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_EVIDENCE_ALIGNMENT_STARTED",
                    subject=str(alignment.alignment_run_id),
                )
            ],
        },
    )


def validate_alignment_input(
    state: EvaluationGraphState,
) -> dict[str, Any]:
    """Confirm there are claims and accepted evidence before calling anything."""
    node = NodeId.VALIDATE_ALIGNMENT_INPUT
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None or alignment.is_terminal:
        return _done(
            state, node, started_at, "No open alignment run.", status=NodeStatus.SKIPPED
        )

    claims = state.project.claims
    evidence = (
        run.evidence_extraction.verified_evidence if run.evidence_extraction else []
    )
    errors = list(alignment.errors)
    warnings: list[str] = []

    if not claims:
        errors.append(
            _issue(AlignmentIssueCode.NO_CLAIMS, node, "no existing claim to align")
        )
        warnings.append("no claims")
    if not evidence:
        errors.append(
            _issue(
                AlignmentIssueCode.NO_ACCEPTED_EVIDENCE,
                node,
                "no accepted Phase 2C evidence to align",
            )
        )
        warnings.append("no accepted evidence")

    alignment = _revalidated(alignment, errors=errors)
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"Alignment input: {len(claims)} claim(s), {len(evidence)} accepted "
        f"evidence item(s).",
        run=run,
        warnings=warnings,
    )


def generate_alignment_pairs(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Every claim x every accepted evidence item, deterministically (section 12)."""
    node = NodeId.GENERATE_ALIGNMENT_PAIRS
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None or alignment.is_terminal:
        return _done(
            state, node, started_at, "No open alignment run.", status=NodeStatus.SKIPPED
        )

    claims = state.project.claims
    evidence = (
        run.evidence_extraction.verified_evidence if run.evidence_extraction else []
    )
    if not claims or not evidence:
        return _done(
            state,
            node,
            started_at,
            "No pairs to generate: missing claims or evidence.",
            status=NodeStatus.SKIPPED,
        )

    limit = _research_settings(config).alignment.max_pairs_per_run
    outcome = generate_pairs(claims, evidence, max_pairs_per_run=limit)

    if outcome.blocked:
        errors = [
            *alignment.errors,
            _issue(
                AlignmentIssueCode.PAIR_LIMIT_EXCEEDED,
                node,
                f"required {outcome.required_count} pair(s) exceeds the safety "
                f"limit of {limit}; alignment is blocked rather than truncated",
            ),
        ]
        alignment = _revalidated(
            alignment,
            errors=errors,
            status=ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED,
            completed_at=workflow_now(),
        )
        run = run.evolve(claim_evidence_alignment=alignment)
        return _done(
            state,
            node,
            started_at,
            f"Blocked: {outcome.required_count} required pair(s) exceeds limit "
            f"{limit}.",
            run=run,
            warnings=["pair limit exceeded"],
            extra={"status": WorkflowStatus.COMPLETED},
        )

    alignment = _revalidated(alignment, pairs=outcome.pairs)
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"Generated {len(outcome.pairs)} deterministic claim/evidence pair(s).",
        run=run,
    )


def classify_alignment_candidates(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """The one model call per pair. Everything it returns stays untrusted."""
    node = NodeId.CLASSIFY_ALIGNMENT_CANDIDATES
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None or alignment.is_terminal or not alignment.pairs:
        return _done(
            state,
            node,
            started_at,
            "No pairs to classify.",
            status=NodeStatus.SKIPPED,
        )

    provider = _configurable(config).get(ALIGNMENT_PROVIDER_KEY)
    if provider is None:
        alignment = _revalidated(
            alignment,
            errors=[
                *alignment.errors,
                _issue(
                    AlignmentIssueCode.CLASSIFIER_PROVIDER_MISSING,
                    node,
                    "no structured model provider injected; no relation is invented",
                ),
            ],
        )
        run = run.evolve(claim_evidence_alignment=alignment)
        return _done(
            state,
            node,
            started_at,
            "Classification skipped: no model provider.",
            run=run,
            status=NodeStatus.SKIPPED,
            warnings=["no model provider"],
        )

    claim_index = {c.claim_id: c for c in state.project.claims}
    evidence_index = {
        e.evidence_id: e
        for e in (run.evidence_extraction.verified_evidence if run.evidence_extraction else [])
    }
    llm_settings = _llm_settings(config)

    resolved_pairs = [
        (claim_index[p.claim_id], evidence_index[p.evidence_id])
        for p in alignment.pairs
        if p.claim_id in claim_index and p.evidence_id in evidence_index
    ]

    outcomes = classify_pairs(resolved_pairs, provider, llm_settings)
    candidates: list[AlignmentCandidate] = []
    errors = list(alignment.errors)
    failures = 0
    for outcome in outcomes:
        if not outcome.succeeded or outcome.schema_error or outcome.candidate is None:
            failures += 1
            detail = (
                "schema mismatch"
                if outcome.schema_error
                else outcome.call.status.value
                if outcome.call
                else "no result"
            )
            errors.append(
                _issue(
                    AlignmentIssueCode.CLASSIFIER_MODEL_FAILED,
                    node,
                    f"classification failed for one pair: {detail}",
                    outcome.claim_id,
                )
            )
            continue
        candidates.append(outcome.candidate)

    alignment = _revalidated(alignment, candidates=candidates, errors=errors)
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"{len(resolved_pairs)} pair(s) classified into {len(candidates)} "
        f"untrusted candidate(s); {failures} failed.",
        run=run,
        warnings=["one or more classifications failed"] if failures else [],
    )


def verify_alignment_candidates(state: EvaluationGraphState) -> dict[str, Any]:
    """The trust boundary: exact anchors and taxonomy consistency, or nothing."""
    node = NodeId.VERIFY_ALIGNMENT_CANDIDATES
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None or alignment.is_terminal or not alignment.candidates:
        return _done(
            state, node, started_at, "No candidate to verify.", status=NodeStatus.SKIPPED
        )

    claims = state.project.claims
    evidence = (
        run.evidence_extraction.verified_evidence if run.evidence_extraction else []
    )
    outcome = verify_candidates(
        list(alignment.candidates),
        claims,
        evidence,
        research_run_id=run.research_run_id,
        alignment_run_id=alignment.alignment_run_id,
    )
    alignment = _revalidated(
        alignment,
        alignments=[*alignment.alignments, *outcome.alignments],
        rejected_candidates=[*alignment.rejected_candidates, *outcome.rejected],
    )
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"Verified {len(outcome.alignments)} alignment(s); rejected "
        f"{len(outcome.rejected)} candidate(s).",
        run=run,
        warnings=sorted({r.reason.value for r in outcome.rejected}),
    )


def update_alignment_coverage(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Operational counters for the pass. Never a claim-sufficiency statement."""
    node = NodeId.UPDATE_ALIGNMENT_COVERAGE
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None or alignment.is_terminal:
        return _done(
            state, node, started_at, "No open alignment run.", status=NodeStatus.SKIPPED
        )

    evidence = (
        run.evidence_extraction.verified_evidence if run.evidence_extraction else []
    )
    model_failures = sum(
        1
        for issue in alignment.errors
        if issue.code is AlignmentIssueCode.CLASSIFIER_MODEL_FAILED
    )
    coverage = build_coverage(
        claims_total=len(state.project.claims),
        accepted_evidence_total=len(evidence),
        pairs_required=len(state.project.claims) * len(evidence),
        pairs_generated=len(alignment.pairs),
        candidates=list(alignment.candidates),
        alignments=list(alignment.alignments),
        rejected=list(alignment.rejected_candidates),
        model_failures=model_failures,
    )
    alignment = _revalidated(alignment, coverage=coverage)
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"Coverage: {coverage.accepted_alignments_total} alignment(s) from "
        f"{coverage.pairs_classified} classified pair(s).",
        run=run,
    )


def finalize_claim_evidence_alignment(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Set the terminal status. The research run itself stays open."""
    node = NodeId.FINALIZE_CLAIM_EVIDENCE_ALIGNMENT
    started_at = workflow_now()
    run = _require_run(state)
    alignment = run.claim_evidence_alignment
    if alignment is None:
        return _done(
            state,
            node,
            started_at,
            "No open alignment run.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )
    if alignment.is_terminal:
        return _done(
            state,
            node,
            started_at,
            f"Claim-evidence alignment already finished with status "
            f"{alignment.status.value}.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )

    provider_available = _configurable(config).get(ALIGNMENT_PROVIDER_KEY) is not None
    status = decide_status(
        alignment.coverage, provider_available=provider_available, blocked=False
    )
    alignment = _revalidated(alignment, status=status, completed_at=workflow_now())
    run = run.evolve(claim_evidence_alignment=alignment)
    return _done(
        state,
        node,
        started_at,
        f"Claim-evidence alignment finished with status {status.value}.",
        run=run,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_EVIDENCE_ALIGNMENT_FINISHED",
                    subject=status.value,
                )
            ],
        },
    )


__all__ = [
    "ALIGNMENT_DATASET_VERSION_KEY",
    "ALIGNMENT_PROVIDER_KEY",
    "classify_alignment_candidates",
    "finalize_claim_evidence_alignment",
    "generate_alignment_pairs",
    "load_alignment_run",
    "update_alignment_coverage",
    "validate_alignment_input",
    "verify_alignment_candidates",
]
