"""Phase 2F claim-evidence scoring nodes.

No model call anywhere in this module, by architecture (section 19): a
model-generated score is forbidden, and there is nothing here for one to decide.
Every node recomputes from the ``ClaimSufficiencyRun`` carried by the
``ResearchRun``, so a replay after an interrupt reproduces the same scorecards
rather than depending on values held between nodes -- the Phase 2C/2D/2E
replay-safety shape (ADR-002).

None of these nodes writes the ``project`` channel. ``ProjectState.scores``,
canonical ``ScoreRecord``s, claim status, confidence, ``evidence_ids``,
``counter_evidence_ids``, ``trust_gate`` and ``evaluation_status`` are untouched
by construction: there is no code path from here to any of them, and the
contracts in ``src/schemas/claim_evidence_score.py`` cannot express a rubric
score, a claim verdict or a trust decision even if one were attempted
(ADR-017).

The nodes are idempotent on the recomputed steps: traces, channels, reliability
and disposition are pure functions of the Phase 2E state, so re-running one
replaces its output with an identical value rather than appending to it. With
``uuid5`` scorecard ids that makes double-counting after a checkpoint resume
structurally impossible rather than merely unobserved (section 25).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.graph.contracts import AuditEvent, NodeResult, NodeStatus, WorkflowStatus
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState
from src.research.scoring.pipeline import (
    build_coverage,
    decide_status,
    readiness,
    score_assessments,
)
from src.schemas.claim_evidence_score import (
    ClaimEvidenceScoringRun,
    ClaimScoringStatus,
    ReliabilityPosture,
    ScoringIssue,
    ScoringIssueCode,
)
from src.schemas.claim_component_inventory import ComponentInventoryCompleteness
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

SCORING_DATASET_VERSION_KEY = "scoring_dataset_version"


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _emit(run: ResearchRun) -> dict[str, Any]:
    return {"research_runs": {str(run.research_run_id): run}}


def _require_run(state: EvaluationGraphState) -> ResearchRun:
    run = state.active_research_run
    if run is None:
        raise ValueError("scoring node reached without an active research run")
    return run


def _revalidated(
    run: ClaimEvidenceScoringRun, **changes: Any
) -> ClaimEvidenceScoringRun:
    """A successor scoring run, re-validated in full. Nothing mutates in place."""
    return ClaimEvidenceScoringRun.model_validate({**dict(run), **changes})


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
    code: ScoringIssueCode, node: NodeId, message: str, claim_id: str | None = None
) -> ScoringIssue:
    return ScoringIssue(code=code, node=node.value, message=message, claim_id=claim_id)


def _open_scoring(state: EvaluationGraphState) -> ClaimEvidenceScoringRun | None:
    run = state.active_research_run
    if run is None or run.claim_evidence_scoring is None:
        return None
    scoring = run.claim_evidence_scoring
    return None if scoring.is_terminal else scoring


def _scorecards(state: EvaluationGraphState) -> list[Any]:
    """The recomputed scorecards for the current state.

    Recomputing rather than threading intermediate values through state is what
    makes each node replay-safe: LangGraph re-runs an interrupted node from its
    first line, and a pure recomputation gives the identical answer (ADR-002).
    """
    run = state.active_research_run
    if run is None or run.claim_sufficiency is None:
        return []
    scoring = run.claim_evidence_scoring
    if scoring is None:
        return []
    if readiness(run.claim_sufficiency) is not None:
        return []
    return score_assessments(
        run.claim_sufficiency,
        scoring_run_id=scoring.scoring_run_id,
        research_run_id=run.research_run_id,
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def load_scoring_run(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Open a scoring run over a research run that carries Phase 2E output."""
    node = NodeId.LOAD_SCORING_RUN
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
            f"Claim evidence scoring skipped: {reason}.",
            status=NodeStatus.SKIPPED,
            warnings=[reason],
            extra={"status": WorkflowStatus.RUNNING},
        )

    if run.claim_evidence_scoring is not None and run.claim_evidence_scoring.is_terminal:
        # Idempotency guard (section 25): re-invoking a finished graph must
        # never reopen a terminal run and produce a second set of scorecards.
        return _done(
            state,
            node,
            started_at,
            f"Claim evidence scoring already finished with status "
            f"{run.claim_evidence_scoring.status.value}; not reopened.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.RUNNING},
        )

    sufficiency = run.claim_sufficiency
    not_ready = readiness(sufficiency)
    if not_ready is not None:
        code = (
            ScoringIssueCode.NO_SUFFICIENCY_ASSESSMENTS
            if not_ready is ClaimScoringStatus.NO_SUFFICIENCY_ASSESSMENTS
            else ScoringIssueCode.SUFFICIENCY_NOT_READY
        )
        message = {
            ScoringIssueCode.SUFFICIENCY_NOT_READY: (
                "claim sufficiency has not reached a COMPLETED state; scoring "
                "does not proceed as though assessments existed, because a "
                "confident zero is worse than an explicit not-ready"
            ),
            ScoringIssueCode.NO_SUFFICIENCY_ASSESSMENTS: (
                "the claim sufficiency run produced no assessment to score"
            ),
        }[code]
        scoring = ClaimEvidenceScoringRun(
            research_run_id=run.research_run_id,
            sufficiency_run_id=(
                sufficiency.sufficiency_run_id if sufficiency else None
            ),
            status=not_ready,
            dataset_version=_configurable(config).get(SCORING_DATASET_VERSION_KEY),
            errors=[_issue(code, node, message)],
            completed_at=workflow_now(),
        )
        run = run.evolve(claim_evidence_scoring=scoring)
        return _done(
            state,
            node,
            started_at,
            f"Claim evidence scoring not started: {not_ready.value}.",
            run=run,
            status=NodeStatus.SKIPPED,
            warnings=[not_ready.value],
            extra={"status": WorkflowStatus.RUNNING},
        )

    scoring = run.claim_evidence_scoring or ClaimEvidenceScoringRun(
        research_run_id=run.research_run_id,
        sufficiency_run_id=sufficiency.sufficiency_run_id,
        status=ClaimScoringStatus.RUNNING,
        dataset_version=_configurable(config).get(SCORING_DATASET_VERSION_KEY),
    )
    scoring = _revalidated(scoring, status=ClaimScoringStatus.RUNNING)
    run = run.evolve(claim_evidence_scoring=scoring)

    return _done(
        state,
        node,
        started_at,
        f"Claim evidence scoring opened over "
        f"{len(sufficiency.assessments)} sufficiency assessment(s).",
        run=run,
        extra={
            "status": WorkflowStatus.RUNNING,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_EVIDENCE_SCORING_STARTED",
                    subject=str(scoring.scoring_run_id),
                )
            ],
        },
    )


def validate_scoring_input(state: EvaluationGraphState) -> dict[str, Any]:
    """Confirm the Phase 2E state Phase 2F is about to score is trustworthy."""
    node = NodeId.VALIDATE_SCORING_INPUT
    started_at = workflow_now()
    run = _require_run(state)
    scoring = _open_scoring(state)
    if scoring is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    sufficiency = run.claim_sufficiency
    assessments = list(sufficiency.assessments) if sufficiency else []
    errors = list(scoring.errors)
    warnings: list[str] = []

    if not state.project.claims:
        errors.append(_issue(ScoringIssueCode.NO_CLAIMS, node, "no claim to score"))
        warnings.append("no claims")

    foreign = [
        a for a in assessments if a.research_run_id != run.research_run_id
    ]
    for assessment in foreign:
        errors.append(
            _issue(
                ScoringIssueCode.CROSS_RUN_ASSESSMENT_EXCLUDED,
                node,
                "a sufficiency assessment belongs to another research run and is "
                "excluded from scoring",
                assessment.claim_id,
            )
        )
    if foreign:
        warnings.append(f"{len(foreign)} cross-run assessment(s) excluded")

    if sufficiency is not None and not sufficiency.alignment_universe_complete:
        errors.append(
            _issue(
                ScoringIssueCode.INCOMPLETE_SUFFICIENCY_INPUT,
                node,
                "Phase 2D did not classify every required pair, so no primary "
                "scalar is issuable for any claim in this run",
            )
        )
        warnings.append("incomplete alignment universe")

    incomplete = [
        a
        for a in assessments
        if a.inventory_completeness is not ComponentInventoryCompleteness.COMPLETE
    ]
    for assessment in incomplete:
        errors.append(
            _issue(
                ScoringIssueCode.INCOMPLETE_COMPONENT_INVENTORY,
                node,
                f"component inventory is "
                f"{assessment.inventory_completeness.value}; the primary scalar "
                "is withheld because part of the material proposition was never "
                "accounted for",
                assessment.claim_id,
            )
        )
    if incomplete:
        warnings.append(
            f"{len(incomplete)} claim(s) have a non-COMPLETE component inventory"
        )

    scoring = _revalidated(scoring, errors=errors)
    run = run.evolve(claim_evidence_scoring=scoring)
    return _done(
        state,
        node,
        started_at,
        f"Scoring input: {len(state.project.claims)} claim(s), "
        f"{len(assessments)} assessment(s), {len(incomplete)} with a "
        f"non-COMPLETE component inventory.",
        run=run,
        warnings=warnings,
    )


def derive_component_score_traces(state: EvaluationGraphState) -> dict[str, Any]:
    """Derive one deterministic score trace per material claim component.

    Reported here and stored with the scorecards: a component's points are part
    of its claim's card, never a free-floating number. Every component of the
    complete Phase 2E inventory gets a trace, including one no alignment ever
    anchored -- that component contributes nothing to either numerator and
    still counts in both denominators (section 14, ADR-016).
    """
    node = NodeId.DERIVE_COMPONENT_SCORE_TRACES
    started_at = workflow_now()
    _require_run(state)
    if _open_scoring(state) is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    traces = sum(len(c.component_traces) for c in cards)
    unexamined = sum(c.unexamined_component_count for c in cards)
    warnings: list[str] = []
    if unexamined:
        warnings.append(
            f"{unexamined} material claim component(s) are unexamined and remain "
            "in the score denominator."
        )
    return _done(
        state,
        node,
        started_at,
        f"Derived {traces} component score trace(s) across {len(cards)} "
        f"claim(s); {unexamined} unexamined component(s) kept in the denominator.",
        warnings=warnings,
    )


def calculate_support_channel(state: EvaluationGraphState) -> dict[str, Any]:
    """Compute the support index for every claim, as its own channel."""
    node = NodeId.CALCULATE_SUPPORT_CHANNEL
    started_at = workflow_now()
    _require_run(state)
    if _open_scoring(state) is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    covered = sum(c.support.covered_components for c in cards)
    total = sum(c.support.total_components for c in cards)
    return _done(
        state,
        node,
        started_at,
        f"Support channel computed for {len(cards)} claim(s): {covered}/{total} "
        f"material component(s) adequately supported.",
    )


def calculate_contradiction_channel(state: EvaluationGraphState) -> dict[str, Any]:
    """Compute the contradiction index, always, and never netted against support.

    Computed for every claim including fully supported ones (section 13): a
    contradiction index of 0 that was actually calculated is a different fact
    from one nobody looked for.
    """
    node = NodeId.CALCULATE_CONTRADICTION_CHANNEL
    started_at = workflow_now()
    _require_run(state)
    if _open_scoring(state) is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    with_contradiction = sum(1 for c in cards if c.has_contradiction)
    warnings: list[str] = []
    if with_contradiction:
        warnings.append(
            f"{with_contradiction} claim(s) carry contradicting evidence, "
            "reported as its own channel and never subtracted from support."
        )
    return _done(
        state,
        node,
        started_at,
        f"Contradiction channel computed for {len(cards)} claim(s); "
        f"{with_contradiction} carry material contradiction.",
        warnings=warnings,
    )


def derive_score_reliability(state: EvaluationGraphState) -> dict[str, Any]:
    """Derive the reliability posture beside each score -- never inside it."""
    node = NodeId.DERIVE_SCORE_RELIABILITY
    started_at = workflow_now()
    _require_run(state)
    if _open_scoring(state) is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    indeterminate = sum(
        1
        for c in cards
        if c.reliability.posture is ReliabilityPosture.INDETERMINATE
    )
    warnings: list[str] = []
    if indeterminate:
        warnings.append(
            f"{indeterminate} claim(s) have INDETERMINATE reliability: the "
            "contributing sources state nothing about publication form."
        )
    return _done(
        state,
        node,
        started_at,
        f"Reliability posture derived for {len(cards)} claim(s); "
        f"{indeterminate} INDETERMINATE.",
        warnings=warnings,
    )


def apply_score_disposition_policy(state: EvaluationGraphState) -> dict[str, Any]:
    """Decide, per claim, whether a primary scalar may be issued at all."""
    node = NodeId.APPLY_SCORE_DISPOSITION_POLICY
    started_at = workflow_now()
    _require_run(state)
    scoring = _open_scoring(state)
    if scoring is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    withheld = sum(1 for c in cards if c.scalar_withheld)
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.disposition.value] = counts.get(card.disposition.value, 0) + 1
    warnings: list[str] = []
    if withheld:
        warnings.append(
            f"{withheld} claim(s) withhold a primary scalar; the directional "
            "indices remain available for all of them."
        )
    return _done(
        state,
        node,
        started_at,
        f"Applied {scoring.policy_version} disposition policy to {len(cards)} "
        f"claim(s): {counts}.",
        warnings=warnings,
    )


def build_claim_evidence_scorecards(state: EvaluationGraphState) -> dict[str, Any]:
    """Store one scorecard per scored claim, with its coverage counters."""
    node = NodeId.BUILD_CLAIM_EVIDENCE_SCORECARDS
    started_at = workflow_now()
    run = _require_run(state)
    scoring = _open_scoring(state)
    if scoring is None:
        return _done(
            state, node, started_at, "No open scoring run.", status=NodeStatus.SKIPPED
        )

    cards = _scorecards(state)
    sufficiency = run.claim_sufficiency
    coverage = build_coverage(
        claims_total=len(state.project.claims),
        assessments_total=len(sufficiency.assessments) if sufficiency else 0,
        scorecards=cards,
    )
    scoring = _revalidated(scoring, scorecards=cards, coverage=coverage)
    run = run.evolve(claim_evidence_scoring=scoring)
    return _done(
        state,
        node,
        started_at,
        f"Built {len(cards)} claim evidence scorecard(s): "
        f"{coverage.scalars_issued} primary scalar(s) issued, "
        f"{coverage.scalars_withheld} withheld.",
        run=run,
    )


def finalize_claim_evidence_scoring(state: EvaluationGraphState) -> dict[str, Any]:
    """Set the terminal status. The research run itself stays open.

    Left non-terminal deliberately, exactly as Phase 2B/2C/2D/2E do, so later
    reviewed branches can still write to the same run. Nothing here touches
    ``ProjectState.scores``: promoting an evidence index into project scoring is
    a later explicit phase (section 28, ADR-017).
    """
    node = NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING
    started_at = workflow_now()
    run = _require_run(state)
    scoring = run.claim_evidence_scoring
    if scoring is None:
        return _done(
            state,
            node,
            started_at,
            "No open scoring run.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )
    if scoring.is_terminal:
        return _done(
            state,
            node,
            started_at,
            f"Claim evidence scoring already finished with status "
            f"{scoring.status.value}.",
            status=NodeStatus.SKIPPED,
            extra={"status": WorkflowStatus.COMPLETED},
        )

    status = decide_status(list(scoring.scorecards))
    scoring = _revalidated(scoring, status=status, completed_at=workflow_now())
    run = run.evolve(claim_evidence_scoring=scoring)
    return _done(
        state,
        node,
        started_at,
        f"Claim evidence scoring finished with status {status.value}.",
        run=run,
        extra={
            "status": WorkflowStatus.COMPLETED,
            "audit_events": [
                AuditEvent(
                    run_id=state.run_id,
                    node=node.value,
                    event_type="CLAIM_EVIDENCE_SCORING_FINISHED",
                    subject=status.value,
                )
            ],
        },
    )


__all__ = [
    "SCORING_DATASET_VERSION_KEY",
    "apply_score_disposition_policy",
    "build_claim_evidence_scorecards",
    "calculate_contradiction_channel",
    "calculate_support_channel",
    "derive_component_score_traces",
    "derive_score_reliability",
    "finalize_claim_evidence_scoring",
    "load_scoring_run",
    "validate_scoring_input",
]
