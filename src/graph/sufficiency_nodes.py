"""Phase 2E claim-sufficiency nodes.

No model call anywhere in this module, by architecture (section 16). Every node
recomputes from the ``ClaimSufficiencyRun`` carried by the ``ResearchRun``, so a
replay after an interrupt reproduces the same state rather than depending on
anything held between nodes -- the Phase 2C/2D replay-safety shape.

None of these nodes writes the ``project`` channel. Claim status, confidence,
``evidence_ids``, ``counter_evidence_ids``, scores, ``trust_gate`` and
``evaluation_status`` are untouched by construction: there is no code path from
here to any of them, and the contracts in ``src/schemas/claim_sufficiency.py``
cannot express a claim verdict, a score or a trust decision even if one were
attempted (ADR-014, ADR-015).

The nodes are deliberately idempotent on the recomputed steps: grouping,
profiling and coverage are pure functions of their inputs, so re-running one
replaces its output with an identical value rather than appending to it. That is
why a checkpoint resume cannot double-count evidence (section 24).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.graph.contracts import AuditEvent, NodeResult, NodeStatus, WorkflowStatus
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.research.sufficiency.identity import build_independence_groups
from src.research.sufficiency.pipeline import (
    READY_ALIGNMENT_STATUSES,
    assess_claim,
    build_coverage,
    decide_status,
    readiness,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyRun,
    ClaimSufficiencyStatus,
    SufficiencyIssue,
    SufficiencyIssueCode,
)
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

SUFFICIENCY_DATASET_VERSION_KEY = "sufficiency_dataset_version"


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _research_settings(config: RunnableConfig | None) -> ResearchSettings:
    return _configurable(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _emit(run: ResearchRun) -> dict[str, Any]:
    return {"research_runs": {str(run.research_run_id): run}}


def _require_run(state: EvaluationGraphState) -> ResearchRun:
    run = state.active_research_run
    if run is None:
        raise ValueError("sufficiency node reached without an active research run")
    return run


def _revalidated(run: ClaimSufficiencyRun, **changes: Any) -> ClaimSufficiencyRun:
    """A successor sufficiency run, re-validated in full. Nothing mutates in place."""
    return ClaimSufficiencyRun.model_validate({**dict(run), **changes})


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
    code: SufficiencyIssueCode, node: NodeId, message: str, claim_id: str | None = None
) -> SufficiencyIssue:
    return SufficiencyIssue(
        code=code, node=node.value, message=message, claim_id=claim_id
    )


def _open_sufficiency(state: EvaluationGraphState) -> ClaimSufficiencyRun | None:
    run = state.active_research_run
    if run is None or run.claim_sufficiency is None:
        return None
    sufficiency = run.claim_sufficiency
    return None if sufficiency.is_terminal else sufficiency


def _claims(state: EvaluationGraphState, config: RunnableConfig | None) -> list[Any]:
    limit = _research_settings(config).sufficiency.max_claims_per_run
    return list(state.project.claims)[:limit]


def _evidence(run: ResearchRun) -> list[Any]:
    return (
        list(run.evidence_extraction.verified_evidence)
        if run.evidence_extraction
        else []
    )


def _logical_sources(run: ResearchRun) -> list[Any]:
    return (
        list(run.academic_research.logical_sources) if run.academic_research else []
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_sufficiency_run(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open a sufficiency run over a research run that carries Phase 2D output."""
    node = NodeId.LOAD_SUFFICIENCY_RUN
    started_at = workflow_now()
    run = state.active_research_run

    if run is None or run.is_terminal:
        reason = (
            "no active research run"
            if run is None
            else "the research run is already terminal"
        )
        return _done(
            state,
            node,
            started_at,
            f"Claim sufficiency skipped: {reason}.",
            status=NodeStatus.SKIPPED,
            warnings=[reason],
            extra={"status": WorkflowStatus.RUNNING},
        )

    if run.claim_sufficiency is not None and run.claim_sufficiency.is_terminal:
        # Idempotency guard (section 24): re-invoking a finished graph must
        # never reopen a terminal run and produce a second set of assessments.
        return _done(
            state,
            node,
            started_at,
            f"Claim sufficiency already finished with status "
            f"{run.claim_sufficiency.status.value}; not reopened.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.RUNNING},
        )

    alignment = run.claim_evidence_alignment
    not_ready = readiness(alignment)
    if not_ready is not None:
        code = {
            ClaimSufficiencyStatus.NOT_READY: SufficiencyIssueCode.ALIGNMENT_NOT_READY,
            ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE: (
                SufficiencyIssueCode.ALIGNMENT_INCOMPLETE
            ),
            ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS: (
                SufficiencyIssueCode.NO_VERIFIED_ALIGNMENTS
            ),
        }[not_ready]
        message = {
            SufficiencyIssueCode.ALIGNMENT_NOT_READY: (
                "claim-evidence alignment has not reached a usable terminal state; "
                "sufficiency does not proceed as though alignment were complete"
            ),
            SufficiencyIssueCode.ALIGNMENT_INCOMPLETE: (
                "claim-evidence alignment did not classify every required pair; "
                "sufficiency is not asserted over an incomplete alignment universe"
            ),
            SufficiencyIssueCode.NO_VERIFIED_ALIGNMENTS: (
                "no verified claim-evidence alignment is available to assess"
            ),
        }[code]
        sufficiency = ClaimSufficiencyRun(
            research_run_id=run.research_run_id,
            alignment_run_id=alignment.alignment_run_id if alignment else None,
            status=not_ready,
            dataset_version=_configurable(config).get(SUFFICIENCY_DATASET_VERSION_KEY),
            alignment_universe_complete=bool(
                alignment and alignment.status in READY_ALIGNMENT_STATUSES
            ),
            errors=[_issue(code, node, message)],
            completed_at=workflow_now(),
        )
        run = run.evolve(claim_sufficiency=sufficiency)
        return _done(
            state,
            node,
            started_at,
            f"Claim sufficiency not started: {not_ready.value}.",
            run=run,
            status=NodeStatus.SKIPPED,
            warnings=[not_ready.value],
            extra={"status": WorkflowStatus.RUNNING},
        )

    sufficiency = run.claim_sufficiency or ClaimSufficiencyRun(
        research_run_id=run.research_run_id,
        alignment_run_id=alignment.alignment_run_id,
        status=ClaimSufficiencyStatus.RUNNING,
        dataset_version=_configurable(config).get(SUFFICIENCY_DATASET_VERSION_KEY),
        alignment_universe_complete=alignment.status in READY_ALIGNMENT_STATUSES,
    )
    sufficiency = _revalidated(sufficiency, status=ClaimSufficiencyStatus.RUNNING)
    run = run.evolve(claim_sufficiency=sufficiency)

    return _done(
        state,
        node,
        started_at,
        f"Claim sufficiency opened over {len(alignment.alignments)} verified "
        f"alignment(s).",
        run=run,
        extra={
            "status": WorkflowStatus.RUNNING,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_SUFFICIENCY_STARTED",
                    subject=str(sufficiency.sufficiency_run_id),
                )
            ],
        },
    )


def validate_sufficiency_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Confirm claims, accepted evidence and verified sources are all present."""
    node = NodeId.VALIDATE_SUFFICIENCY_INPUT
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = _open_sufficiency(state)
    if sufficiency is None:
        return _done(
            state, node, started_at, "No open sufficiency run.", status=NodeStatus.SKIPPED
        )

    claims = state.project.claims
    evidence = _evidence(run)
    sources = _logical_sources(run)
    errors = list(sufficiency.errors)
    warnings: list[str] = []

    if not claims:
        errors.append(_issue(SufficiencyIssueCode.NO_CLAIMS, node, "no claim to assess"))
        warnings.append("no claims")
    if not evidence:
        errors.append(
            _issue(
                SufficiencyIssueCode.NO_ACCEPTED_EVIDENCE,
                node,
                "no accepted Phase 2C evidence to weigh",
            )
        )
        warnings.append("no accepted evidence")
    if not sources:
        # Without Phase 2B logical sources nothing has a canonical identity, so
        # every item is untraceable rather than ungrouped-but-trusted.
        errors.append(
            _issue(
                SufficiencyIssueCode.ACADEMIC_SOURCES_UNAVAILABLE,
                node,
                "no verified academic source is available; evidence cannot be "
                "grouped by canonical identity and cannot contribute",
            )
        )
        warnings.append("no verified academic sources")

    sufficiency = _revalidated(sufficiency, errors=errors)
    run = run.evolve(claim_sufficiency=sufficiency)
    return _done(
        state,
        node,
        started_at,
        f"Sufficiency input: {len(claims)} claim(s), {len(evidence)} evidence "
        f"item(s), {len(sources)} verified source(s).",
        run=run,
        warnings=warnings,
    )


def build_independence_group_set(state: EvaluationGraphState) -> dict[str, Any]:
    """Collapse every evidence item onto its canonical logical source.

    The release-critical step (section 9). Recomputed from scratch and assigned
    rather than appended, so a replay yields the identical group set -- the
    deterministic ``uuid5`` group ids make that checkable.
    """
    node = NodeId.BUILD_INDEPENDENCE_GROUPS
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = _open_sufficiency(state)
    if sufficiency is None:
        return _done(
            state, node, started_at, "No open sufficiency run.", status=NodeStatus.SKIPPED
        )

    groups, index = build_independence_groups(
        run.research_run_id, _evidence(run), _logical_sources(run)
    )
    sufficiency = _revalidated(sufficiency, independence_groups=groups)
    run = run.evolve(claim_sufficiency=sufficiency)
    collapsed = max(len(index) - len(groups), 0)
    return _done(
        state,
        node,
        started_at,
        f"{len(index)} evidence item(s) collapsed onto {len(groups)} "
        f"independent source group(s); {collapsed} duplicate(s) did not become "
        f"corroboration.",
        run=run,
    )


def build_evidence_weight_profiles(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """One multi-dimensional profile per verified claim/evidence pair.

    Profiles and assessments are produced by the same deterministic pass, so
    they cannot disagree about what contributed. This node stores the profiles;
    ``APPLY_SUFFICIENCY_POLICY`` stores the assessments built alongside them.
    """
    node = NodeId.BUILD_EVIDENCE_WEIGHT_PROFILES
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = _open_sufficiency(state)
    if sufficiency is None:
        return _done(
            state, node, started_at, "No open sufficiency run.", status=NodeStatus.SKIPPED
        )

    profiles, _ = _assess(state, run, sufficiency, config)
    sufficiency = _revalidated(sufficiency, weight_profiles=profiles)
    run = run.evolve(claim_sufficiency=sufficiency)
    eligible = sum(1 for p in profiles if p.is_eligible)
    return _done(
        state,
        node,
        started_at,
        f"Built {len(profiles)} evidence weight profile(s); {eligible} eligible "
        f"to contribute.",
        run=run,
    )


def aggregate_claim_component_coverage(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Aggregate per-component coverage at the exact Phase 2D anchors.

    Reported here and stored with the assessments: a component's coverage is
    part of its claim's assessment record, never a free-floating judgement.
    """
    node = NodeId.AGGREGATE_CLAIM_COMPONENT_COVERAGE
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = _open_sufficiency(state)
    if sufficiency is None:
        return _done(
            state, node, started_at, "No open sufficiency run.", status=NodeStatus.SKIPPED
        )

    _, assessments = _assess(state, run, sufficiency, config)
    components = sum(len(a.components) for a in assessments)
    adequate = sum(
        1 for a in assessments for c in a.components if c.is_adequately_evidenced
    )
    return _done(
        state,
        node,
        started_at,
        f"Aggregated {components} material claim component(s) across "
        f"{len(assessments)} claim(s); {adequate} adequately evidenced.",
    )


def apply_sufficiency_policy(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Apply the versioned policy and store one assessment per assessed claim."""
    node = NodeId.APPLY_SUFFICIENCY_POLICY
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = _open_sufficiency(state)
    if sufficiency is None:
        return _done(
            state, node, started_at, "No open sufficiency run.", status=NodeStatus.SKIPPED
        )

    profiles, assessments = _assess(state, run, sufficiency, config)
    alignment = run.claim_evidence_alignment
    coverage = build_coverage(
        claims_total=len(state.project.claims),
        accepted_evidence_total=len(_evidence(run)),
        verified_alignments_total=len(alignment.alignments) if alignment else 0,
        groups=list(sufficiency.independence_groups),
        profiles=profiles,
        assessments=assessments,
    )
    sufficiency = _revalidated(
        sufficiency,
        weight_profiles=profiles,
        assessments=assessments,
        coverage=coverage,
    )
    run = run.evolve(claim_sufficiency=sufficiency)
    return _done(
        state,
        node,
        started_at,
        f"Applied {sufficiency.policy_version} to {len(assessments)} claim(s): "
        f"{coverage.outcome_counts}.",
        run=run,
    )


def finalize_claim_sufficiency(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Set the terminal status. The research run itself stays open.

    Left non-terminal deliberately, exactly as Phase 2B/2C/2D do, so later
    reviewed branches can still write to the same run.
    """
    node = NodeId.FINALIZE_CLAIM_SUFFICIENCY
    started_at = workflow_now()
    run = _require_run(state)
    sufficiency = run.claim_sufficiency
    if sufficiency is None:
        return _done(
            state,
            node,
            started_at,
            "No open sufficiency run.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )
    if sufficiency.is_terminal:
        return _done(
            state,
            node,
            started_at,
            f"Claim sufficiency already finished with status "
            f"{sufficiency.status.value}.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )

    status = decide_status(list(sufficiency.assessments))
    sufficiency = _revalidated(
        sufficiency, status=status, completed_at=workflow_now()
    )
    run = run.evolve(claim_sufficiency=sufficiency)
    return _done(
        state,
        node,
        started_at,
        f"Claim sufficiency finished with status {status.value}.",
        run=run,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_SUFFICIENCY_FINISHED",
                    subject=status.value,
                )
            ],
        },
    )


def _assess(
    state: EvaluationGraphState,
    run: ResearchRun,
    sufficiency: ClaimSufficiencyRun,
    config: RunnableConfig | None,
) -> tuple[list[Any], list[Any]]:
    """The shared deterministic pass, recomputed by every node that needs it.

    Recomputing rather than threading intermediate values through state is what
    makes each node replay-safe: LangGraph re-runs an interrupted node from its
    first line, and a pure recomputation gives the identical answer (ADR-002).
    """
    alignment = run.claim_evidence_alignment
    if alignment is None:
        return [], []
    groups = list(sufficiency.independence_groups)
    group_index = {g.independence_group_id: g for g in groups}
    evidence_to_group = {
        evidence_id: g.independence_group_id
        for g in groups
        for evidence_id in g.member_evidence_ids
    }
    evidence_index = {
        e.evidence_id: e
        for e in _evidence(run)
        if e.research_run_id == run.research_run_id
    }
    universe_complete = alignment.status in READY_ALIGNMENT_STATUSES

    profiles: list[Any] = []
    assessments: list[Any] = []
    for claim in _claims(state, config):
        claim_alignments = alignment.alignments_for_claim(claim.claim_id)
        if not claim_alignments:
            continue
        assessment, claim_profiles = assess_claim(
            claim,
            claim_alignments,
            evidence_index,
            group_index,
            evidence_to_group,
            research_run_id=run.research_run_id,
            sufficiency_run_id=sufficiency.sufficiency_run_id,
            alignment_run_id=alignment.alignment_run_id,
            universe_complete=universe_complete,
        )
        assessments.append(assessment)
        profiles.extend(claim_profiles)
    return profiles, assessments


__all__ = [
    "SUFFICIENCY_DATASET_VERSION_KEY",
    "aggregate_claim_component_coverage",
    "apply_sufficiency_policy",
    "build_evidence_weight_profiles",
    "build_independence_group_set",
    "finalize_claim_sufficiency",
    "load_sufficiency_run",
    "validate_sufficiency_input",
]
