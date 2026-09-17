"""Phase 2C evidence extraction nodes.

One model call per content snapshot, and nothing else in this branch trusts the
model for anything. Every node writes to the ``EvidenceExtractionRun`` carried by
the ``ResearchRun``, so a replay after an interrupt recomputes from state rather
than from anything held between nodes.

None of these nodes writes the ``project`` channel. Canonical project facts,
student claims, scores and the trust gate are untouched by construction: there is
no code path from here to any of them, and the contracts in
``src/schemas/evidence_extraction.py`` cannot express a claim relationship even
if one were attempted (ADR-012).

A source that fails -- no content, a model error, an unverifiable excerpt --
removes nothing from the sources that succeeded. A mixed pass is ``PARTIAL``.
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
from src.research.evidence.chunking import chunk_snapshot
from src.research.evidence.content import build_all_content_snapshots
from src.research.evidence.dedup import deduplicate_evidence
from src.research.evidence.extractor import extract_candidates
from src.research.evidence.pipeline import (
    build_coverage,
    decide_status,
    verify_candidates,
)
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.common import QueryPurpose
from src.schemas.evidence_extraction import (
    EvidenceCandidate,
    EvidenceExtractionIssue,
    EvidenceExtractionIssueCode,
    EvidenceExtractionRun,
    EvidenceExtractionStatus,
    SourceContentSnapshot,
)
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

EVIDENCE_EXTRACTION_PROVIDER_KEY = INTAKE_PROVIDER_KEY
"""Phase 2C reuses the one structured-model provider seam. There is deliberately
no second LLM framework (§29)."""

EVIDENCE_DATASET_VERSION_KEY = "evidence_dataset_version"


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
        raise ValueError("evidence node reached without an active research run")
    return run


def _revalidated(
    extraction: EvidenceExtractionRun, **changes: Any
) -> EvidenceExtractionRun:
    """A successor extraction run, re-validated in full. Nothing mutates in place."""
    return EvidenceExtractionRun.model_validate({**dict(extraction), **changes})


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
    code: EvidenceExtractionIssueCode,
    node: NodeId,
    message: str,
    source_id: str | None = None,
) -> EvidenceExtractionIssue:
    return EvidenceExtractionIssue(
        code=code, node=node.value, message=message, source_id=source_id
    )


def _purposes_by_content(
    run: ResearchRun, snapshots: list[SourceContentSnapshot]
) -> dict[UUID, QueryPurpose]:
    """The verified query purpose each source was retrieved for (§48).

    Taken from the Phase 2A plan through the Phase 2B observations, so the
    extractor's context is already PII-minimized and nothing is reconstructed.
    """
    academic = run.academic_research
    if academic is None:
        return {}
    purpose_by_query = {q.query_id: q.purpose for q in academic.selected_queries}
    purpose_by_source: dict[str, QueryPurpose] = {}
    for source in academic.logical_sources:
        for observation in source.observations:
            purpose = purpose_by_query.get(observation.query_id)
            if purpose is not None:
                purpose_by_source.setdefault(source.logical_source_id, purpose)
                break
    return {
        snapshot.content_id: purpose_by_source[snapshot.source_id]
        for snapshot in snapshots
        if snapshot.source_id in purpose_by_source
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_research_run(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open an extraction run on a research run that has verified sources."""
    node = NodeId.LOAD_RESEARCH_RUN
    started_at = workflow_now()
    run = state.active_research_run

    if run is None or run.is_terminal or run.academic_research is None:
        reason = (
            "no active research run"
            if run is None
            else "the research run is already terminal"
            if run.is_terminal
            else "the research run carries no academic retrieval result"
        )
        return _done(
            state,
            node,
            started_at,
            f"Evidence extraction skipped: {reason}.",
            status=NodeStatus.SKIPPED,
            warnings=[reason],
            extra={"status": WorkflowStatus.RUNNING},
        )

    provider = _configurable(config).get(EVIDENCE_EXTRACTION_PROVIDER_KEY)
    extraction = run.evidence_extraction or EvidenceExtractionRun(
        research_run_id=run.research_run_id,
        status=EvidenceExtractionStatus.RUNNING,
        extractor_prompt_version=PROMPT_VERSIONS["EVIDENCE_EXTRACTOR_PROMPT"],
        dataset_version=_configurable(config).get(EVIDENCE_DATASET_VERSION_KEY),
        provider_name=getattr(provider, "name", None),
        model_name=_llm_settings(config).extraction_model if provider else None,
    )
    extraction = _revalidated(extraction, status=EvidenceExtractionStatus.RUNNING)
    run = run.evolve(evidence_extraction=extraction)

    return _done(
        state,
        node,
        started_at,
        f"Evidence extraction opened over "
        f"{len(run.academic_research.logical_sources)} verified source(s).",
        run=run,
        extra={
            "status": WorkflowStatus.RUNNING,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="EVIDENCE_EXTRACTION_STARTED",
                    subject=str(extraction.evidence_extraction_run_id),
                )
            ],
        },
    )


def validate_evidence_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Confirm there is something to extract from before calling anything."""
    node = NodeId.VALIDATE_EVIDENCE_INPUT
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None:
        return _done(
            state, node, started_at, "No open extraction run.", status=NodeStatus.SKIPPED
        )

    academic = run.academic_research
    sources = academic.logical_sources if academic else []
    errors = list(extraction.errors)
    warnings: list[str] = []

    if not sources:
        errors.append(
            _issue(
                EvidenceExtractionIssueCode.NO_VERIFIED_SOURCES,
                node,
                "no verified academic source to extract evidence from",
            )
        )
        warnings.append("no verified sources")

    extraction = _revalidated(extraction, errors=errors)
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Evidence input: {len(sources)} verified source(s).",
        run=run,
        warnings=warnings,
    )


def build_content_snapshots(state: EvaluationGraphState) -> dict[str, Any]:
    """Verified sources -> provider-attributed content snapshots (§4, §7)."""
    node = NodeId.BUILD_CONTENT_SNAPSHOTS
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    academic = run.academic_research
    if extraction is None or academic is None:
        return _done(
            state, node, started_at, "No open extraction run.", status=NodeStatus.SKIPPED
        )

    outcome = build_all_content_snapshots(academic, run.research_run_id)
    extraction = _revalidated(
        extraction,
        content_snapshots=outcome.snapshots,
        ineligible_sources=outcome.ineligible,
    )
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Built {len(outcome.snapshots)} content snapshot(s); "
        f"{len(outcome.ineligible)} source(s) carried no extractable content.",
        run=run,
        warnings=sorted({i.reason.value for i in outcome.ineligible}),
    )


def select_extractable_content(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Apply the per-run source budget. Truncation is recorded, not silent."""
    node = NodeId.SELECT_EXTRACTABLE_CONTENT
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None:
        return _done(
            state, node, started_at, "No open extraction run.", status=NodeStatus.SKIPPED
        )

    limit = _research_settings(config).evidence.max_sources_per_run
    selected: list[SourceContentSnapshot] = []
    seen_sources: list[str] = []
    for snapshot in extraction.content_snapshots:
        if snapshot.source_id not in seen_sources:
            if len(seen_sources) >= limit:
                continue
            seen_sources.append(snapshot.source_id)
        selected.append(snapshot)

    truncated = len(extraction.content_snapshots) - len(selected)
    errors = list(extraction.errors)
    if not selected:
        errors.append(
            _issue(
                EvidenceExtractionIssueCode.NO_ELIGIBLE_CONTENT,
                node,
                "no eligible content; evidence extraction produces nothing",
            )
        )

    extraction = _revalidated(extraction, content_snapshots=selected, errors=errors)
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Selected {len(selected)} snapshot(s) across {len(seen_sources)} source(s); "
        f"{truncated} truncated by budget.",
        run=run,
        warnings=["source budget truncated the content set"] if truncated else [],
    )


def chunk_content_if_needed(state: EvaluationGraphState) -> dict[str, Any]:
    """Deterministic chunking. Offsets always resolve to the parent snapshot."""
    node = NodeId.CHUNK_CONTENT_IF_NEEDED
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None or not extraction.content_snapshots:
        return _done(
            state, node, started_at, "No content to chunk.", status=NodeStatus.SKIPPED
        )

    chunk_counts = [len(chunk_snapshot(s)) for s in extraction.content_snapshots]
    multi = sum(1 for count in chunk_counts if count > 1)
    return _done(
        state,
        node,
        started_at,
        f"{len(chunk_counts)} snapshot(s) chunked into {sum(chunk_counts)} window(s); "
        f"{multi} required more than one.",
    )


def extract_evidence_candidates(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """The one model call per snapshot. Everything it returns stays untrusted."""
    node = NodeId.EXTRACT_EVIDENCE_CANDIDATES
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None or not extraction.content_snapshots:
        return _done(
            state,
            node,
            started_at,
            "No content to extract from.",
            status=NodeStatus.SKIPPED,
        )

    provider = _configurable(config).get(EVIDENCE_EXTRACTION_PROVIDER_KEY)
    if provider is None:
        extraction = _revalidated(
            extraction,
            errors=[
                *extraction.errors,
                _issue(
                    EvidenceExtractionIssueCode.EXTRACTION_PROVIDER_MISSING,
                    node,
                    "no structured model provider injected; no evidence is invented",
                ),
            ],
        )
        run = run.evolve(evidence_extraction=extraction)
        return _done(
            state,
            node,
            started_at,
            "Extraction skipped: no model provider.",
            run=run,
            status=NodeStatus.SKIPPED,
            warnings=["no model provider"],
        )

    settings = _research_settings(config)
    llm_settings = _llm_settings(config)
    purposes = _purposes_by_content(run, list(extraction.content_snapshots))

    candidates: list[EvidenceCandidate] = []
    errors = list(extraction.errors)
    attempts = 0
    failures = 0

    for snapshot in extraction.content_snapshots:
        attempts += 1
        outcome = extract_candidates(
            snapshot,
            provider,
            llm_settings,
            research_purpose=purposes.get(snapshot.content_id),
        )
        if not outcome.succeeded or outcome.schema_error:
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
                    EvidenceExtractionIssueCode.EXTRACTION_MODEL_FAILED,
                    node,
                    f"extraction failed for one source: {detail}",
                    snapshot.source_id,
                )
            )
            continue
        # Over-extraction is truncated rather than trusted wholesale.
        candidates.extend(
            outcome.candidates[: settings.evidence.max_candidates_per_snapshot]
        )

    extraction = _revalidated(extraction, candidates=candidates, errors=errors)
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"{attempts} extraction attempt(s) produced {len(candidates)} untrusted "
        f"candidate(s); {failures} failed.",
        run=run,
        warnings=["one or more extractions failed"] if failures else [],
    )


def verify_evidence_provenance(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """The trust boundary: exact spans, derived by code, or nothing (ADR-011)."""
    node = NodeId.VERIFY_EVIDENCE_PROVENANCE
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None or not extraction.candidates:
        return _done(
            state, node, started_at, "No candidate to verify.", status=NodeStatus.SKIPPED
        )

    bounds = _research_settings(config).evidence
    outcome = verify_candidates(
        list(extraction.candidates),
        list(extraction.content_snapshots),
        research_run_id=run.research_run_id,
        extraction_run_id=extraction.evidence_extraction_run_id,
        min_chars=bounds.min_evidence_excerpt_chars,
        max_chars=bounds.max_evidence_excerpt_chars,
    )
    extraction = _revalidated(
        extraction,
        verification_results=outcome.results,
        verified_evidence=outcome.evidence,
        rejected_candidates=[*extraction.rejected_candidates, *outcome.rejected],
    )
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Verified {len(outcome.evidence)} excerpt(s); rejected "
        f"{len(outcome.rejected)} candidate(s).",
        run=run,
        warnings=sorted({r.reason.value for r in outcome.rejected}),
    )


def verify_numeric_fidelity(state: EvaluationGraphState) -> dict[str, Any]:
    """Report the numeric outcome.

    The numeric check runs inside provenance verification, because a number that
    fails fidelity invalidates the whole candidate rather than just a field. This
    node makes the result separately visible, which is why the spec lists it as
    its own stage.
    """
    node = NodeId.VERIFY_NUMERIC_FIDELITY
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None:
        return _done(
            state, node, started_at, "No open extraction run.", status=NodeStatus.SKIPPED
        )

    numeric_rejections = [
        r
        for r in extraction.rejected_candidates
        if r.reason.value in ("INVALID_NUMERIC_OBSERVATION", "INVALID_UNIT_FIDELITY")
    ]
    verified_numbers = sum(
        len(e.numeric_observations) for e in extraction.verified_evidence
    )
    return _done(
        state,
        node,
        started_at,
        f"{verified_numbers} numeric observation(s) verified against their "
        f"excerpts; {len(numeric_rejections)} candidate(s) rejected on fidelity.",
        warnings=sorted({r.reason.value for r in numeric_rejections}),
    )


def deduplicate_evidence_node(state: EvaluationGraphState) -> dict[str, Any]:
    """Collapse identical verified spans, preserving every observation (§36)."""
    node = NodeId.DEDUPLICATE_EVIDENCE
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None or not extraction.verified_evidence:
        return _done(
            state,
            node,
            started_at,
            "No evidence to deduplicate.",
            status=NodeStatus.SKIPPED,
        )

    before = len(extraction.verified_evidence)
    evidence, collapsed = deduplicate_evidence(list(extraction.verified_evidence))
    extraction = _revalidated(
        extraction,
        verified_evidence=evidence,
        rejected_candidates=[*extraction.rejected_candidates, *collapsed],
    )
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"{before} verified item(s) resolved into {len(evidence)}; "
        f"{len(collapsed)} identical span(s) merged.",
        run=run,
    )


def update_evidence_coverage(state: EvaluationGraphState) -> dict[str, Any]:
    """Operational counters for the pass. Never a quality statement."""
    node = NodeId.UPDATE_EVIDENCE_COVERAGE
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None:
        return _done(
            state, node, started_at, "No open extraction run.", status=NodeStatus.SKIPPED
        )

    academic = run.academic_research
    attempts = len(extraction.content_snapshots)
    model_failures = sum(
        1
        for issue in extraction.errors
        if issue.code is EvidenceExtractionIssueCode.EXTRACTION_MODEL_FAILED
    )

    coverage = build_coverage(
        verified_sources_total=len(academic.logical_sources) if academic else 0,
        snapshots=list(extraction.content_snapshots),
        ineligible=list(extraction.ineligible_sources),
        extraction_attempts=attempts,
        candidates=list(extraction.candidates),
        evidence=list(extraction.verified_evidence),
        rejected=list(extraction.rejected_candidates),
        model_failures=model_failures,
    )
    extraction = _revalidated(extraction, coverage=coverage)
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Coverage: {coverage.accepted_evidence_total} evidence item(s) from "
        f"{coverage.sources_with_eligible_content} source(s) with content; "
        f"{coverage.sources_without_eligible_content} without.",
        run=run,
    )


def finalize_evidence_extraction(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Set the terminal status. The research run itself deliberately stays open.

    Phase 2A's ``UPDATE_RESEARCH_COVERAGE`` is what makes a research run
    terminal. Evidence extraction is one stage among several, and freezing the
    run here would block whatever a later phase writes.
    """
    node = NodeId.FINALIZE_EVIDENCE_EXTRACTION
    started_at = workflow_now()
    run = _require_run(state)
    extraction = run.evidence_extraction
    if extraction is None:
        return _done(
            state,
            node,
            started_at,
            "No open extraction run.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )

    provider_available = (
        _configurable(config).get(EVIDENCE_EXTRACTION_PROVIDER_KEY) is not None
    )
    status = decide_status(extraction.coverage, provider_available=provider_available)
    extraction = _revalidated(
        extraction, status=status, completed_at=workflow_now()
    )
    run = run.evolve(evidence_extraction=extraction)
    return _done(
        state,
        node,
        started_at,
        f"Evidence extraction finished with status {status.value}.",
        run=run,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="EVIDENCE_EXTRACTION_FINISHED",
                    subject=status.value,
                )
            ],
        },
    )


__all__ = [
    "EVIDENCE_DATASET_VERSION_KEY",
    "EVIDENCE_EXTRACTION_PROVIDER_KEY",
    "build_content_snapshots",
    "chunk_content_if_needed",
    "deduplicate_evidence_node",
    "extract_evidence_candidates",
    "finalize_evidence_extraction",
    "load_research_run",
    "select_extractable_content",
    "update_evidence_coverage",
    "validate_evidence_input",
    "verify_evidence_provenance",
    "verify_numeric_fidelity",
]
