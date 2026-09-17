"""Claim-evidence alignment eval runner.

Each Gold case is driven through the **real Phase 2D graph** with a scripted
fake provider, so what is measured is the shipped path: pair generation,
classification, deterministic verification, coverage, through a checkpoint.

Scoring is implemented here, independently of the code it scores. The eval
does not ask the verifier whether it verified correctly; it re-derives every
judgement from the produced state -- re-checking every claim anchor against the
claim text from scratch, recomputing taxonomy consistency with the same pure
function the schema uses (the canonical definition, not a mock of it), and
diffing the whole project state before and after. That independence is what
lets the negative controls prove the eval can fail: breaking a rule in
``src/research/alignment`` does not break the metric watching for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.evals.claim_alignment.dataset import (
    AlignmentGoldCase,
    AlignmentGoldDataset,
    build_claims,
    build_evidence,
    build_snapshots,
    gold_extraction_run_id,
    gold_run_id,
)
from src.evals.claim_alignment.metrics import ClaimAlignmentMetrics
from src.graph.alignment_nodes import ALIGNMENT_DATASET_VERSION_KEY, ALIGNMENT_PROVIDER_KEY
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2d_graph import build_phase2d_claim_alignment_graph
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.llm.contracts import ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.research.alignment.dto import AlignmentClassification, CandidateComponentDTO
from src.research.alignment.pipeline import verify_candidates
from src.research.alignment.verification import resolve_anchor
from src.research.coverage import initial_branch_coverage
from src.research.inputs import project_state_fingerprint
from src.research.planner import PLANNER_VERSION
from src.research.settings import ResearchSettings
from src.schemas.claim_alignment import (
    AlignmentRejectionReason,
    ClaimEvidenceAlignmentRun,
    relation_is_consistent,
)
from src.schemas.evidence_extraction import (
    EXTRACTABLE_CONTENT_KINDS,
    EvidenceExtractionRun,
    EvidenceExtractionStatus,
)
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions

logger = logging.getLogger(__name__)

FAILURE_BUILDERS = {
    "REFUSAL": refusal_result,
    "PROVIDER_ERROR": provider_error_result,
    "INCOMPLETE_OUTPUT": incomplete_result,
    "PARSE_ERROR": parse_error_result,
    "EMPTY_OUTPUT": empty_result,
}

CLAIM_VERDICT_FIELDS = (
    "claim_status",
    "confidence_delta",
    "verified",
    "score",
    "score_delta",
    "trust_gate",
)
"""Fields Phase 2D must not be able to set on an alignment record. Checked
structurally against the alignment run payload, mirroring the Phase 2C check."""


@dataclass
class AlignmentCaseResult:
    case_id: str
    categories: list[str]
    language: str
    alignment_run: ClaimEvidenceAlignmentRun | None = None
    claims: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    run_id: Any = None
    project_mutated: bool = False
    claims_mutated: bool = False
    claim_status_mutated: bool = False
    claim_confidence_mutated: bool = False
    claim_evidence_refs_mutated: bool = False
    claim_counter_evidence_refs_mutated: bool = False
    scores_mutated: bool = False
    trust_gate_mutated: bool = False
    evaluation_status_mutated: bool = False
    extracted_evidence_mutated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _scripted_response(case: AlignmentGoldCase, index: int) -> AlignmentClassification:
    scripted = case.scripted or []
    if not scripted:
        return AlignmentClassification(relation="NOT_RELEVANT", components=[])
    entry = scripted[index % len(scripted)]
    return AlignmentClassification(
        relation=entry.relation,
        components=[
            CandidateComponentDTO(
                claimed_text=c.claimed_text,
                judgment=c.judgment,
                reason_codes=c.reason_codes,
                rationale=c.rationale,
            )
            for c in entry.components
        ],
        rationale=entry.rationale,
    )


def _provider(case: AlignmentGoldCase) -> FakeStructuredModelProvider:
    if case.scripted_failure is not None:
        return FakeStructuredModelProvider(
            result=FAILURE_BUILDERS[case.scripted_failure](
                ModelTask.CLAIM_EVIDENCE_ALIGNMENT
            )
        )
    n_pairs = max(len(case.claims) * len(case.evidence), 1)
    responses = [_scripted_response(case, i) for i in range(n_pairs)]
    return FakeStructuredModelProvider(responses=responses)


def _open_run(case: AlignmentGoldCase, project: ProjectState) -> ResearchRun:
    run_id = gold_run_id(case)
    extraction = EvidenceExtractionRun(
        research_run_id=run_id,
        evidence_extraction_run_id=gold_extraction_run_id(case),
        status=EvidenceExtractionStatus.COMPLETED,
        content_snapshots=build_snapshots(case),
        verified_evidence=build_evidence(case),
        completed_at="2026-09-01T09:05:00+00:00",
    )
    run = ResearchRun(
        research_run_id=run_id,
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="alignment-gold",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(evidence_extraction=extraction)


def _run_direct_candidate_case(case: AlignmentGoldCase) -> AlignmentCaseResult:
    """Structural-reference categories: feed the verifier a raw candidate.

    Deterministic pairing can never itself produce an invalid or cross-run
    reference (every pair comes from an existing claim and an evidence item
    already in the run), so ``invalid_references`` and
    ``cross_run_reference_attempts`` coverage calls the real
    ``verify_candidate`` directly with a deliberately bad candidate -- still
    production code, just entered below the pairing step.
    """
    from uuid import UUID

    from src.schemas.claim_alignment import AlignmentCandidate

    outcome = AlignmentCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = ProjectState()
        project.claims = build_claims(case)
        run = _open_run(case, project)
        evidence = run.evidence_extraction.verified_evidence
        alignment_run_id = uuid4()

        payload = dict(case.direct_candidate or {})
        if "evidence_id" in payload and payload["evidence_id"] == "OTHER_RUN":
            payload["evidence_id"] = str(uuid4())
        candidate = AlignmentCandidate.model_validate(payload)

        from src.research.alignment.pipeline import verify_candidate

        alignment, rejection = verify_candidate(
            candidate,
            {c.claim_id: c for c in project.claims},
            {e.evidence_id: e for e in evidence},
            research_run_id=run.research_run_id,
            alignment_run_id=alignment_run_id,
            accepted_keys={},
        )
        alignment_run = ClaimEvidenceAlignmentRun(
            research_run_id=run.research_run_id,
            alignment_run_id=alignment_run_id,
            status="COMPLETED",
            alignments=[alignment] if alignment else [],
            rejected_candidates=[rejection] if rejection else [],
            completed_at="2026-09-01T09:10:00+00:00",
        )
        outcome.alignment_run = alignment_run
        outcome.claims = project.claims
        outcome.evidence = evidence
        outcome.run_id = run.research_run_id
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


def run_alignment_case(case: AlignmentGoldCase) -> AlignmentCaseResult:
    """Drive one Gold case through the real Phase 2D graph."""
    if case.direct_candidate is not None:
        return _run_direct_candidate_case(case)
    outcome = AlignmentCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = ProjectState()
        project.claims = build_claims(case)
        before = project_state_fingerprint(project)
        claims_before = [
            (c.claim_id, c.claim, c.status.value, tuple(c.evidence_ids), tuple(c.counter_evidence_ids), c.confidence)
            for c in project.claims
        ]
        scores_before = [s.model_dump() for s in project.scores]
        gate_before = project.trust_gate
        eval_status_before = project.evaluation_status

        run = _open_run(case, project)
        evidence_before = [
            e.model_dump(mode="json") for e in run.evidence_extraction.verified_evidence
        ]
        run_id = uuid4()
        config = thread_config(new_thread_id(run_id))
        config["configurable"][ALIGNMENT_PROVIDER_KEY] = _provider(case)
        config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings(
            alignment={"max_pairs_per_run": case.max_pairs_per_run or 500}
        )
        config["configurable"][ALIGNMENT_DATASET_VERSION_KEY] = "alignment-gold-v1"

        app = build_phase2d_claim_alignment_graph(build_checkpointer())
        state = coerce_graph_state(
            app.invoke(
                EvaluationGraphState(
                    run_id=run_id,
                    thread_id=config["configurable"]["thread_id"],
                    project=project,
                    research_runs={str(run.research_run_id): run},
                    active_research_run_id=run.research_run_id,
                ),
                config,
            )
        )

        finished = state.active_research_run
        alignment_run = finished.claim_evidence_alignment if finished else None
        outcome.alignment_run = alignment_run
        outcome.claims = state.project.claims
        outcome.evidence = (
            finished.evidence_extraction.verified_evidence if finished and finished.evidence_extraction else []
        )
        outcome.run_id = finished.research_run_id if finished else run.research_run_id

        outcome.project_mutated = project_state_fingerprint(state.project) != before
        claims_after = [
            (c.claim_id, c.claim, c.status.value, tuple(c.evidence_ids), tuple(c.counter_evidence_ids), c.confidence)
            for c in state.project.claims
        ]
        outcome.claims_mutated = claims_after != claims_before
        outcome.claim_status_mutated = [c[2] for c in claims_after] != [
            c[2] for c in claims_before
        ]
        outcome.claim_confidence_mutated = [c[5] for c in claims_after] != [
            c[5] for c in claims_before
        ]
        outcome.claim_evidence_refs_mutated = [c[3] for c in claims_after] != [
            c[3] for c in claims_before
        ]
        outcome.claim_counter_evidence_refs_mutated = [c[4] for c in claims_after] != [
            c[4] for c in claims_before
        ]
        outcome.scores_mutated = [
            s.model_dump() for s in state.project.scores
        ] != scores_before
        outcome.trust_gate_mutated = state.project.trust_gate != gate_before
        outcome.evaluation_status_mutated = (
            state.project.evaluation_status != eval_status_before
        )
        evidence_after = (
            [e.model_dump(mode="json") for e in finished.evidence_extraction.verified_evidence]
            if finished and finished.evidence_extraction
            else []
        )
        outcome.extracted_evidence_mutated = evidence_after != evidence_before
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


# ---------------------------------------------------------------------------
# Independent checks
# ---------------------------------------------------------------------------


def _claim_by_id(claims: list[Any], claim_id: str) -> Any | None:
    return next((c for c in claims if c.claim_id == claim_id), None)


def _evidence_by_id(evidence: list[Any], evidence_id: Any) -> Any | None:
    return next((e for e in evidence if e.evidence_id == evidence_id), None)


def _anchor_is_real(claim_text: str, start: int, end: int, text: str) -> bool:
    if not (0 <= start < end <= len(claim_text)):
        return False
    return claim_text[start:end] == text


def _is_traceable(
    alignment: Any, alignment_run: ClaimEvidenceAlignmentRun, run_id: Any
) -> bool:
    return bool(
        alignment.research_run_id == run_id
        and alignment.alignment_run_id == alignment_run.alignment_run_id
        and alignment.classifier_version
        and alignment.verifier_version
    )


def _claims_a_verdict(payload: Any) -> bool:
    """Structural scan for a claim-verdict field the schema should not have."""
    if isinstance(payload, dict):
        if any(field in payload for field in CLAIM_VERDICT_FIELDS):
            return True
        return any(_claims_a_verdict(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_claims_a_verdict(item) for item in payload)
    return False


def score_alignment_case(
    case: AlignmentGoldCase,
    outcome: AlignmentCaseResult,
    metrics: ClaimAlignmentMetrics,
) -> None:
    """Score one case, recomputing every judgement from the produced state."""
    alignment_run = getattr(outcome, "alignment_run", None)
    if not outcome.ok or alignment_run is None:
        metrics.cases_errored += 1
        return
    metrics.cases_evaluated += 1
    expected = case.expected
    alignments = list(alignment_run.alignments)
    claims = outcome.claims
    evidence = outcome.evidence

    # -- release-blocking ---------------------------------------------------
    metrics.project_state_mutation_rate.record(outcome.project_mutated)
    metrics.claim_mutation_rate.record(outcome.claims_mutated)
    metrics.claim_status_mutation_rate.record(outcome.claim_status_mutated)
    metrics.claim_confidence_mutation_rate.record(outcome.claim_confidence_mutated)
    metrics.claim_evidence_reference_mutation_rate.record(
        outcome.claim_evidence_refs_mutated
    )
    metrics.claim_counter_evidence_reference_mutation_rate.record(
        outcome.claim_counter_evidence_refs_mutated
    )
    metrics.score_mutation_rate.record(outcome.scores_mutated)
    metrics.trust_gate_mutation_rate.record(outcome.trust_gate_mutated)
    metrics.evaluation_status_mutation_rate.record(outcome.evaluation_status_mutated)
    metrics.extracted_evidence_mutation_rate.record(outcome.extracted_evidence_mutated)
    metrics.automatic_claim_support_rate.record(
        _claims_a_verdict(alignment_run.model_dump(mode="json"))
    )

    for alignment in alignments:
        claim = _claim_by_id(claims, alignment.claim_id)
        metrics.invalid_claim_reference_acceptance_rate.record(claim is None)

        item = _evidence_by_id(evidence, alignment.evidence_id)
        metrics.invalid_evidence_reference_acceptance_rate.record(item is None)
        metrics.unverified_evidence_alignment_acceptance_rate.record(
            item is None
            or not item.observations
            or not item.extractor_version
            or not item.verifier_version
        )
        metrics.cross_run_evidence_alignment_acceptance_rate.record(
            item is None or item.research_run_id != outcome.run_id
        )
        metrics.metadata_only_alignment_acceptance_rate.record(
            item is None or item.content_kind not in EXTRACTABLE_CONTENT_KINDS
        )

        forbidden = list(expected.forbidden_claim_substrings)
        anchors_real = True
        synthesis_hit = False
        for component in alignment.components:
            anchor = component.anchor
            claim_text = claim.claim if claim else ""
            real = anchor.claim_id == alignment.claim_id and _anchor_is_real(
                claim_text, anchor.start, anchor.end, anchor.text
            )
            anchors_real = anchors_real and real
            metrics.exact_claim_anchor_accuracy.add(real)
            if any(text and text in anchor.text for text in forbidden):
                synthesis_hit = True
        metrics.fabricated_claim_anchor_acceptance_rate.record(not anchors_real)
        metrics.provider_ai_synthesis_alignment_acceptance_rate.record(synthesis_hit)

        consistent = relation_is_consistent(alignment.relation, alignment.components)
        metrics.structurally_inconsistent_relationship_acceptance_rate.record(
            not consistent
        )
        metrics.component_pair_consistency_accuracy.add(consistent)

        traceable = _is_traceable(alignment, alignment_run, outcome.run_id)
        metrics.untraceable_alignment_acceptance_rate.record(not traceable)
        metrics.alignment_traceability.add(traceable)

        metrics.valid_alignment_reference_accuracy.add(
            claim is not None and item is not None
        )
        metrics.relationship_taxonomy_contract_accuracy.add(consistent)

    # -- incompatible duplicate pairs (independent re-derivation) -----------
    keys = [a.logical_key for a in alignments]
    metrics.incompatible_duplicate_pair_acceptance_rate.record(
        len(set(keys)) != len(keys)
    )

    # -- idempotency: re-verifying the same candidates adds nothing new -----
    if alignment_run.candidates:
        replay = verify_candidates(
            list(alignment_run.candidates),
            claims,
            evidence,
            research_run_id=outcome.run_id,
            alignment_run_id=alignment_run.alignment_run_id,
        )
        # Every accepted alignment is already recorded; re-verification from a
        # blank ledger must reproduce exactly the same accepted set, never more.
        metrics.checkpoint_idempotency_accuracy.add(
            sorted(a.logical_key for a in replay.alignments)
            == sorted(a.logical_key for a in alignments)
        )

    # -- quality --------------------------------------------------------------
    if expected.pairs_required is not None:
        metrics.deterministic_pair_coverage.add(
            alignment_run.coverage.pairs_required == expected.pairs_required
        )
    if expected.accepted_count is not None:
        metrics.relation_accuracy.add(len(alignments) == expected.accepted_count)
    if expected.relations is not None:
        metrics.relation_accuracy.add(
            sorted(a.relation.value for a in alignments) == sorted(expected.relations)
        )
    if expected.rejection_reasons:
        got = {r.reason.value for r in alignment_run.rejected_candidates}
        metrics.rejected_candidate_accuracy.add(set(expected.rejection_reasons) <= got)
    if expected.status is not None:
        metrics.rejected_candidate_accuracy.add(
            alignment_run.status.value == expected.status
        )


def run_alignment_dataset(
    dataset: AlignmentGoldDataset,
) -> tuple[ClaimAlignmentMetrics, list[AlignmentCaseResult]]:
    metrics = ClaimAlignmentMetrics()
    results: list[AlignmentCaseResult] = []
    for case in dataset.cases:
        outcome = run_alignment_case(case)
        results.append(outcome)
        score_alignment_case(case, outcome, metrics)
    return metrics, results


def score_by_language(
    dataset: AlignmentGoldDataset, results: list[AlignmentCaseResult]
) -> dict[str, ClaimAlignmentMetrics]:
    """Per-language metrics, so an aggregate pass cannot hide a failing subgroup."""
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, ClaimAlignmentMetrics] = {}
    for outcome in results:
        case = by_id.get(outcome.case_id)
        if case is None:
            continue
        score_alignment_case(
            case, outcome, grouped.setdefault(case.language, ClaimAlignmentMetrics())
        )
    return grouped


@dataclass
class AlignmentGateResult:
    passed: bool
    safety_clean: bool
    thresholds_met: bool
    violations: dict[str, int] = field(default_factory=dict)
    cases_errored: int = 0

    def summary(self) -> str:
        return (
            f"{'PASS' if self.passed else 'FAIL'} safety_clean={self.safety_clean} "
            f"thresholds_met={self.thresholds_met} cases_errored={self.cases_errored}"
        )


def evaluate_alignment_gate(metrics: ClaimAlignmentMetrics) -> AlignmentGateResult:
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return AlignmentGateResult(
        passed=metrics.safety_clean
        and metrics.thresholds_met
        and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        thresholds_met=metrics.thresholds_met,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )


__all__ = [
    "AlignmentCaseResult",
    "AlignmentGateResult",
    "evaluate_alignment_gate",
    "run_alignment_case",
    "run_alignment_dataset",
    "score_alignment_case",
    "score_by_language",
]
