"""Claim-evidence scoring eval runner -- Phase 2F.

Each Gold case is driven through the **real Phase 2E graph and then the real
Phase 2F graph**, through a real checkpointer, so what is measured is the
shipped path: component traces, both channels, reliability, disposition,
scorecards and finalization.

Scoring is implemented here, independently of the code it scores. The eval
never asks the pipeline whether it added up correctly. It

* re-derives the material component denominator from the claim's own text with
  its own materiality rule, so an omitted component is caught by arithmetic
  rather than by trusting the inventory;
* re-implements the point allocation from the policy text in
  ``recomputed_channel_bp`` and compares it against the stored index, so a
  change to ``src/research/scoring/policy.py`` does not change the number the
  metric expects;
* recomputes each channel from that channel's traces **alone**, which is what
  proves the contradiction index did not leak into the support index;
* re-checks every claim anchor against the claim text from scratch;
* diffs the whole project state, the canonical score records, the Phase 2C
  evidence, the Phase 2D alignments and the Phase 2E sufficiency run before and
  after.

That independence is what lets the negative controls prove the eval can fail:
breaking a rule in ``src/research/scoring`` does not break the metric watching
for it.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any
from uuid import uuid4

from src.evals.claim_scoring.dataset import (
    ScoringGoldCase,
    ScoringGoldDataset,
    scoring_run_id_for,
    world_run_id,
)
from src.evals.claim_scoring.metrics import ClaimScoringMetrics
from src.evals.claim_sufficiency.dataset import (
    build_academic_result,
    build_alignment_run,
    build_alignments,
    build_claims,
    build_extraction_run,
)
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2e_graph import build_phase2e_claim_sufficiency_graph
from src.graph.phase2f_graph import build_phase2f_claim_scoring_graph
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.scoring_nodes import SCORING_DATASET_VERSION_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.research.coverage import initial_branch_coverage
from src.research.inputs import project_state_fingerprint
from src.research.planner import PLANNER_VERSION
from src.research.settings import ResearchSettings
from src.schemas.claim_evidence_score import (
    CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
    CORROBORATION_DIMENSION_MAX_BP,
    COVERAGE_DIMENSION_MAX_BP,
    DIRECTNESS_DIMENSION_MAX_BP,
    INDEX_MAX_BP,
    ClaimEvidenceScoringRun,
    ClaimScoringStatus,
    DirectionalCoverageState,
    ReliabilityPosture,
    ScoreDisposition,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyStatus,
    EvidenceContributionClass,
    RetractionStatus,
)
from src.schemas.common import EvaluationStatus
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult

logger = logging.getLogger(__name__)

PROJECT_SCORE_FIELDS = (
    "score",
    "score_delta",
    "total_score",
    "axis",
    "axes",
    "rubric",
    "rubric_kind",
    "weight",
    "max_score",
)
"""Field names that would mean Phase 2F had produced project/rubric scoring,
checked structurally against the serialized scoring run. An evidence index is
not a rubric axis and not an official judging score (section 28)."""

TRUTH_PROBABILITY_FIELDS = (
    "truth_probability",
    "probability",
    "confidence_percentage",
    "confidence",
    "certainty",
    "likelihood",
    "p_true",
    "belief",
)
"""Names that would type an evidence index as a probability of truth. The gate
is structural because the misreading this phase most fears is a *naming*
mistake: a field called ``confidence`` invites exactly the interpretation
section 6 forbids."""

NOT_READY_STATUSES = frozenset(
    {
        ClaimScoringStatus.NOT_READY,
        ClaimScoringStatus.NO_SCORABLE_CLAIMS,
        ClaimScoringStatus.NO_SUFFICIENCY_ASSESSMENTS,
    }
)


@dataclass
class ScoringCaseResult:
    case_id: str
    categories: list[str]
    language: str
    scoring_run: ClaimEvidenceScoringRun | None = None
    rerun_run: ClaimEvidenceScoringRun | None = None
    stable_rerun_run: ClaimEvidenceScoringRun | None = None
    sufficiency_run: Any = None
    claims: list[Any] = field(default_factory=list)
    project_mutated: bool = False
    claims_mutated: bool = False
    claim_status_mutated: bool = False
    claim_confidence_mutated: bool = False
    claim_evidence_refs_mutated: bool = False
    claim_counter_evidence_refs_mutated: bool = False
    score_records_mutated: bool = False
    trust_gate_mutated: bool = False
    evaluation_status_mutated: bool = False
    extracted_evidence_mutated: bool = False
    alignments_mutated: bool = False
    sufficiency_mutated: bool = False
    cross_run_refused: bool | None = None
    unknown_inventory_card: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Independent re-derivation
# ---------------------------------------------------------------------------


def _is_material(text: str) -> bool:
    """Materiality, re-implemented from ADR-016 rather than imported.

    A span is material when it holds at least one character that is neither
    whitespace nor Unicode punctuation/symbol. Written out here so the eval's
    denominator does not come from the code it grades.
    """
    return any(
        not character.isspace()
        and not unicodedata.category(character).startswith(("P", "S"))
        for character in text
    )


def expected_component_spans(
    claim_text: str, anchors: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Re-derive the material component partition from the claim's own text.

    Independently of ``src/research/sufficiency/inventory.py``: cut at every
    anchor boundary plus the claim's ends, keep the material segments, and trim
    surrounding whitespace. If this disagrees with the engine, one of the two is
    wrong and the metric says so rather than the inventory vouching for itself.
    """
    cuts = {0, len(claim_text)}
    for start, end in anchors:
        if 0 <= start < end <= len(claim_text):
            cuts.add(start)
            cuts.add(end)
    ordered = sorted(cuts)
    spans: list[tuple[int, int]] = []
    for start, end in zip(ordered, ordered[1:]):
        segment = claim_text[start:end]
        if not _is_material(segment):
            continue
        lead = len(segment) - len(segment.lstrip())
        trail = len(segment) - len(segment.rstrip())
        spans.append((start + lead, end - trail))
    return spans


def declared_anchor_spans(case: ScoringGoldCase, claim_id: str) -> list[tuple[int, int]]:
    """Every verified Phase 2D anchor for one claim, from the fixture itself."""
    suff = case.as_sufficiency_case()
    claim_text = {c.claim_id: c.claim for c in case.claims}[claim_id]
    spans: list[tuple[int, int]] = []
    for alignment in build_alignments(suff):
        if alignment.claim_id != claim_id:
            continue
        for component in alignment.components:
            anchor = component.anchor
            if claim_text[anchor.start : anchor.end] == anchor.text:
                spans.append((anchor.start, anchor.end))
    return spans


def _quantize(exact: Decimal) -> int:
    with localcontext() as context:
        context.prec = 28
        return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def recomputed_channel_bp(traces: list[Any], direction: str) -> tuple[int, int, int]:
    """Re-implement the point allocation from the policy text (section 9).

    Returns ``(coverage_bp, corroboration_bp, directness_bp)``.

    Written from ``CLAIM-EVIDENCE-SCORING-POLICY-V1`` as documented, not by
    calling it. Crucially it reads **only** this direction's fields, so if the
    engine ever let the contradiction channel influence the support index the
    two would diverge and the metric would fire.
    """
    total = len(traces)
    if total == 0:
        return (0, 0, 0)
    if direction == "SUPPORT":
        states = [t.support_state for t in traces]
        levels = [t.support_corroboration for t in traces]
        directness = [t.support_directness_factor_bp for t in traces]
    else:
        states = [t.contradiction_state for t in traces]
        levels = [t.contradiction_corroboration for t in traces]
        directness = [t.contradiction_directness_factor_bp for t in traces]

    covered = sum(1 for s in states if s is DirectionalCoverageState.ADEQUATE)
    factor = {"NONE": 0, "SINGLE_GROUP": 5_000, "MULTIPLE_GROUPS": 10_000}
    corroboration_sum = sum(factor[level.value] for level in levels)
    directness_sum = sum(directness)

    coverage_bp = _quantize(
        Decimal(covered) / Decimal(total) * Decimal(COVERAGE_DIMENSION_MAX_BP)
    )
    corroboration_bp = _quantize(
        Decimal(corroboration_sum)
        / (Decimal(total) * Decimal(10_000))
        * Decimal(CORROBORATION_DIMENSION_MAX_BP)
    )
    directness_bp = _quantize(
        Decimal(directness_sum)
        / (Decimal(total) * Decimal(10_000))
        * Decimal(DIRECTNESS_DIMENSION_MAX_BP)
    )
    return (coverage_bp, corroboration_bp, directness_bp)


def expected_reliability_rank(posture: ReliabilityPosture) -> int:
    """The reliability ordering, restated here so the monotonicity gate is
    independent of ``src/research/scoring/reliability.py``."""
    return {
        ReliabilityPosture.INDETERMINATE: 0,
        ReliabilityPosture.LIMITED_RELIABILITY: 1,
        ReliabilityPosture.MODERATE_RELIABILITY: 2,
        ReliabilityPosture.HIGHER_RELIABILITY: 3,
    }[posture]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _populated_project(case: ScoringGoldCase) -> ProjectState:
    """A populated project state, so immutability is proven against real values.

    An empty-state test cannot catch the mutation of something that was never
    there. So alongside the case's claims this carries a real
    ``TrustGateResult`` with a blocker and a non-default ``evaluation_status``
    -- exactly the fields Phase 2F must leave byte-for-byte alone, and the ones
    a later project-scoring phase will own (section 22).

    ``ProjectState.scores`` stays empty on purpose: the canonical score list is
    the single most important thing Phase 2F must not write, and an empty list
    that is still empty afterwards is the cleanest possible proof. A populated
    ``ScoreRecord`` is covered by the targeted test module, where a real rubric
    record is diffed field by field.
    """
    project = ProjectState()
    project.claims = build_claims(case.as_sufficiency_case())
    project.trust_gate = TrustGateResult(
        search_coverage=0.8,
        source_quality=0.75,
        claim_traceability=0.9,
        contradictions_resolved=True,
        novelty_search_complete=True,
        methodology_review_complete=True,
        red_team_complete=False,
        closest_prior_art_identified=True,
        sources_verified=True,
        official_requirements_checked=True,
        final_verifier_passed=False,
        score_status=EvaluationStatus.PROVISIONAL,
        finalization_allowed=False,
        blockers=[
            TrustBlocker(
                code=BlockerCode.RED_TEAM_INCOMPLETE,
                detail="Red team pass has not been run yet.",
            )
        ],
    )
    project.evaluation_status = EvaluationStatus.PROVISIONAL
    return project


def _open_world_run(case: ScoringGoldCase, project: ProjectState) -> ResearchRun:
    suff = case.as_sufficiency_case()
    run = ResearchRun(
        research_run_id=world_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="scoring-gold",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(
        academic_research=build_academic_result(suff),
        evidence_extraction=build_extraction_run(suff),
        claim_evidence_alignment=build_alignment_run(suff),
    )


def _run_phase2e(case: ScoringGoldCase, project: ProjectState, run: ResearchRun):
    """Produce the real Phase 2E state this case's scoring pass consumes."""
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
    app = build_phase2e_claim_sufficiency_graph(build_checkpointer())
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
    return state


def _blank_sufficiency(run: ResearchRun) -> ResearchRun:
    """Replace Phase 2E with a run that never completed (section 27)."""
    from src.schemas.claim_sufficiency import (
        ClaimSufficiencyRun,
        SufficiencyIssue,
        SufficiencyIssueCode,
    )

    return run.evolve(
        claim_sufficiency=ClaimSufficiencyRun(
            research_run_id=run.research_run_id,
            status=ClaimSufficiencyStatus.NOT_READY,
            errors=[
                SufficiencyIssue(
                    code=SufficiencyIssueCode.ALIGNMENT_NOT_READY,
                    node="LOAD_SUFFICIENCY_RUN",
                    message="synthetic not-ready Phase 2E state",
                )
            ],
            completed_at="2026-09-01T09:20:00+00:00",
        )
    )


def _run_direct_case(case: ScoringGoldCase) -> ScoringCaseResult:
    """Shapes a validated run record cannot hold, driven at the pipeline.

    A ``ClaimEvidenceScoringRun`` rightly refuses a scorecard from another
    research run, so cross-run rejection is exercised by calling the real
    ``score_claim`` with such an assessment and asserting it raises -- still
    production code, entered below the graph rather than around it.
    """
    from src.research.scoring.pipeline import score_claim

    outcome = ScoringCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = _populated_project(case)
        run = _open_world_run(case, project)
        state = _run_phase2e(case, project, run)
        sufficiency = state.active_research_run.claim_sufficiency
        outcome.sufficiency_run = sufficiency
        outcome.claims = state.project.claims

        assessment = sufficiency.assessments[0]
        if case.direct_kind == "cross_run":
            refused = False
            try:
                score_claim(
                    assessment,
                    list(sufficiency.weight_profiles),
                    scoring_run_id=scoring_run_id_for(case),
                    research_run_id=uuid4(),  # a different research run
                )
            except ValueError:
                refused = True
            outcome.cross_run_refused = refused
        else:
            outcome.unknown_inventory_card = _score_unknown_inventory(
                case, assessment
            )
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


def _score_unknown_inventory(case: ScoringGoldCase, assessment: Any) -> Any:
    """Score a claim whose component inventory is UNKNOWN (section 27).

    Unreachable through the graph: the graph only assesses claims it resolved,
    so ``CLAIM_NOT_RESOLVABLE`` never arises there. Built directly instead --
    still production code, entered below the graph -- because "we could not read
    the claim" must withhold a scalar just as firmly as "part of it is
    unexamined", and an unreachable-through-the-graph path is exactly the kind
    that rots unwatched.
    """
    from src.research.scoring.pipeline import score_claim
    from src.research.sufficiency.inventory import build_inventory
    from src.schemas.claim_sufficiency import ClaimSufficiencyAssessment

    unknown = build_inventory(None, [], claim_id=assessment.claim_id)
    downgraded = ClaimSufficiencyAssessment.model_validate(
        {
            **dict(assessment),
            "outcome": "INSUFFICIENT_EVIDENCE",
            "component_inventory": unknown,
            "components": [],
            "blockers": ["UNKNOWN_COMPONENT_INVENTORY"],
            "reason_codes": ["UNKNOWN_COMPONENT_INVENTORY"],
        }
    )
    return score_claim(
        downgraded,
        [],
        scoring_run_id=scoring_run_id_for(case),
        research_run_id=assessment.research_run_id,
    )


def run_scoring_case(case: ScoringGoldCase) -> ScoringCaseResult:
    """Drive one Gold case through Phase 2E and then the real Phase 2F graph."""
    if case.direct_mode:
        return _run_direct_case(case)
    outcome = ScoringCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = _populated_project(case)
        before = project_state_fingerprint(project)
        claims_before = _claim_tuple(project.claims)
        scores_before = [s.model_dump(mode="json") for s in project.scores]
        gate_before = project.trust_gate
        eval_status_before = project.evaluation_status

        world = _open_world_run(case, project)
        state = _run_phase2e(case, project, world)
        scored_run = state.active_research_run
        if case.sufficiency_not_ready:
            scored_run = _blank_sufficiency(scored_run)
        outcome.sufficiency_run = scored_run.claim_sufficiency

        sufficiency_before = (
            scored_run.claim_sufficiency.model_dump(mode="json")
            if scored_run.claim_sufficiency
            else None
        )
        evidence_before = [
            e.model_dump(mode="json")
            for e in scored_run.evidence_extraction.verified_evidence
        ]
        alignments_before = [
            a.model_dump(mode="json")
            for a in scored_run.claim_evidence_alignment.alignments
        ]

        run_id = uuid4()
        config = thread_config(new_thread_id(run_id))
        config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
        config["configurable"][SCORING_DATASET_VERSION_KEY] = "scoring-gold-v1"

        checkpointer = build_checkpointer()
        app = build_phase2f_claim_scoring_graph(checkpointer)
        initial = EvaluationGraphState(
            run_id=run_id,
            thread_id=config["configurable"]["thread_id"],
            project=state.project,
            research_runs={str(scored_run.research_run_id): scored_run},
            active_research_run_id=scored_run.research_run_id,
        )

        if case.resume_after_node is not None:
            # Interrupt before the named node, then resume from the checkpoint:
            # the resumed half must neither lose nor duplicate scorecards.
            interrupting = build_phase2f_claim_scoring_graph(checkpointer)
            interrupting.invoke(
                initial, {**config, "interrupt_before": [case.resume_after_node]}
            )
            final_state = coerce_graph_state(app.invoke(None, config))
        else:
            final_state = coerce_graph_state(app.invoke(initial, config))

        if case.rerun:
            final_state = coerce_graph_state(app.invoke(None, config))

            # Fingerprint *stability*: score the identical Phase 2E state again
            # on a fresh thread. Identical scoring-relevant inputs must give an
            # identical fingerprint. Note this is deliberately not the
            # independent-world rerun below: a second Phase 2E pass mints a new
            # sufficiency run id, so its assessment ids differ, so its
            # fingerprints *must* differ -- the fingerprint covers the
            # assessment identity by design (section 17).
            stable = build_phase2f_claim_scoring_graph(build_checkpointer())
            stable_config = thread_config(new_thread_id(uuid4()))
            stable_config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
            stable_state = coerce_graph_state(
                stable.invoke(
                    EvaluationGraphState(
                        run_id=uuid4(),
                        thread_id=stable_config["configurable"]["thread_id"],
                        project=state.project,
                        research_runs={str(scored_run.research_run_id): scored_run},
                        active_research_run_id=scored_run.research_run_id,
                    ),
                    stable_config,
                )
            )
            stable_finished = stable_state.active_research_run
            outcome.stable_rerun_run = (
                stable_finished.claim_evidence_scoring if stable_finished else None
            )

            second = build_phase2f_claim_scoring_graph(build_checkpointer())
            rerun_config = thread_config(new_thread_id(uuid4()))
            rerun_config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
            rerun_project = _populated_project(case)
            rerun_world = _open_world_run(case, rerun_project)
            rerun_state = _run_phase2e(case, rerun_project, rerun_world)
            rerun_run = rerun_state.active_research_run
            if case.sufficiency_not_ready:
                rerun_run = _blank_sufficiency(rerun_run)
            rerun_final = coerce_graph_state(
                second.invoke(
                    EvaluationGraphState(
                        run_id=uuid4(),
                        thread_id=rerun_config["configurable"]["thread_id"],
                        project=rerun_state.project,
                        research_runs={str(rerun_run.research_run_id): rerun_run},
                        active_research_run_id=rerun_run.research_run_id,
                    ),
                    rerun_config,
                )
            )
            finished_rerun = rerun_final.active_research_run
            outcome.rerun_run = (
                finished_rerun.claim_evidence_scoring if finished_rerun else None
            )

        finished = final_state.active_research_run
        outcome.scoring_run = finished.claim_evidence_scoring if finished else None
        outcome.claims = final_state.project.claims

        outcome.project_mutated = (
            project_state_fingerprint(final_state.project) != before
        )
        claims_after = _claim_tuple(final_state.project.claims)
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
        outcome.claim_counter_evidence_refs_mutated = [
            c[4] for c in claims_after
        ] != [c[4] for c in claims_before]
        outcome.score_records_mutated = [
            s.model_dump(mode="json") for s in final_state.project.scores
        ] != scores_before
        outcome.trust_gate_mutated = final_state.project.trust_gate != gate_before
        outcome.evaluation_status_mutated = (
            final_state.project.evaluation_status != eval_status_before
        )
        outcome.extracted_evidence_mutated = [
            e.model_dump(mode="json")
            for e in finished.evidence_extraction.verified_evidence
        ] != evidence_before
        outcome.alignments_mutated = [
            a.model_dump(mode="json")
            for a in finished.claim_evidence_alignment.alignments
        ] != alignments_before
        sufficiency_after = (
            finished.claim_sufficiency.model_dump(mode="json")
            if finished.claim_sufficiency
            else None
        )
        outcome.sufficiency_mutated = sufficiency_after != sufficiency_before
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


def _claim_tuple(claims: list[Any]) -> list[tuple]:
    return [
        (
            c.claim_id,
            c.claim,
            c.status.value,
            tuple(c.evidence_ids),
            tuple(c.counter_evidence_ids),
            c.confidence,
        )
        for c in claims
    ]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_scoring_case(
    case: ScoringGoldCase,
    outcome: ScoringCaseResult,
    metrics: ClaimScoringMetrics,
    dataset: ScoringGoldDataset | None = None,
) -> None:
    """Grade one case, recording every quality metric and safety gate."""
    metrics.cases_evaluated += 1
    if not outcome.ok:
        metrics.cases_errored += 1
        return

    expected = case.expected

    # --- canonical state immutability (section 22) -------------------------
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
    metrics.canonical_score_record_mutation_rate.record(outcome.score_records_mutated)
    metrics.trust_gate_mutation_rate.record(outcome.trust_gate_mutated)
    metrics.evaluation_status_mutation_rate.record(outcome.evaluation_status_mutated)
    metrics.extracted_evidence_mutation_rate.record(outcome.extracted_evidence_mutated)
    metrics.alignment_mutation_rate.record(outcome.alignments_mutated)
    metrics.sufficiency_assessment_mutation_rate.record(outcome.sufficiency_mutated)
    metrics.automatic_project_score_update_rate.record(outcome.score_records_mutated)
    metrics.automatic_claim_status_update_rate.record(outcome.claim_status_mutated)

    if case.direct_mode:
        if case.direct_kind == "cross_run":
            # Cross-run isolation: the pipeline must refuse, not silently score.
            metrics.cross_run_assessment_acceptance_rate.record(
                outcome.cross_run_refused is not True
            )
            return
        # UNKNOWN completeness must withhold the scalar exactly as INCOMPLETE
        # does, and must never be read as COMPLETE (ADR-016).
        card = outcome.unknown_inventory_card
        withheld = card is not None and card.final_support_index_bp is None
        metrics.incomplete_inventory_received_full_scalar_rate.record(not withheld)
        metrics.final_scalar_issuance_accuracy.add(withheld)
        metrics.zero_versus_none_accuracy.add(withheld)
        if card is not None:
            expected_disposition = case.expected.disposition.get(card.claim_id)
            if expected_disposition is not None:
                metrics.score_disposition_accuracy.add(
                    card.disposition.value == expected_disposition
                )
            metrics.arithmetic_reconciliation_accuracy.add(
                card.support.index_bp == card.support.dimensions.total_bp
                and card.support.index_bp == 0
            )
            metrics.score_bound_accuracy.add(
                0 <= card.support.index_bp <= INDEX_MAX_BP
            )
            metrics.policy_version_accuracy.add(
                card.policy_version == CLAIM_EVIDENCE_SCORING_POLICY_VERSION
            )
            metrics.input_fingerprint_accuracy.add(len(card.input_fingerprint) == 64)
            metrics.component_denominator_accuracy.add(
                card.support.total_components == 0
            )
        return

    scoring = outcome.scoring_run
    if scoring is None:
        metrics.invalid_sufficiency_assessment_acceptance_rate.record(True)
        return

    metrics.missing_scoring_policy_version_rate.record(
        scoring.policy_version != CLAIM_EVIDENCE_SCORING_POLICY_VERSION
    )
    if expected.status is not None:
        metrics.run_status_accuracy.add(scoring.status.value == expected.status)
    if expected.scorecards_total is not None:
        metrics.component_denominator_accuracy.add(
            len(scoring.scorecards) == expected.scorecards_total
        )

    if scoring.status in NOT_READY_STATUSES:
        # A not-ready pass must hold no scorecard and therefore no scalar.
        metrics.not_ready_claim_received_final_scalar_rate.record(
            bool(scoring.scorecards)
        )
        metrics.final_scalar_issuance_accuracy.add(not scoring.scorecards)
        return

    serialized = scoring.model_dump(mode="json")
    flat = _flatten_keys(serialized)
    metrics.score_written_into_official_project_scoring_rate.record(
        any(name in flat for name in PROJECT_SCORE_FIELDS)
    )
    metrics.score_typed_as_truth_probability_rate.record(
        any(name in flat for name in TRUTH_PROBABILITY_FIELDS)
    )

    claim_text = {c.claim_id: c.claim for c in case.claims}

    for card in scoring.scorecards:
        cid = card.claim_id
        traces = list(card.component_traces)

        # --- the denominator, re-derived from the claim's own text ---------
        recomputed = expected_component_spans(
            claim_text[cid], declared_anchor_spans(case, cid)
        )
        present = sorted((t.anchor_start, t.anchor_end) for t in traces)
        metrics.unexamined_component_omitted_from_denominator_rate.record(
            sorted(recomputed) != present
        )
        if cid in expected.total_components:
            metrics.component_denominator_accuracy.add(
                card.support.total_components == expected.total_components[cid]
            )

        # --- exact anchors -------------------------------------------------
        for trace in traces:
            metrics.exact_claim_anchor_accuracy.add(
                claim_text[cid][trace.anchor_start : trace.anchor_end]
                == trace.anchor_text
            )
        metrics.cross_claim_scorecard_contamination_rate.record(
            any(t.claim_id != cid for t in traces)
        )

        # --- arithmetic, re-implemented from the policy text ---------------
        s_dims = recomputed_channel_bp(traces, "SUPPORT")
        c_dims = recomputed_channel_bp(traces, "CONTRADICTION")
        stored_s = (
            card.support.dimensions.coverage_bp,
            card.support.dimensions.corroboration_bp,
            card.support.dimensions.directness_bp,
        )
        stored_c = (
            card.contradiction.dimensions.coverage_bp,
            card.contradiction.dimensions.corroboration_bp,
            card.contradiction.dimensions.directness_bp,
        )
        metrics.coverage_dimension_accuracy.add(s_dims[0] == stored_s[0])
        metrics.corroboration_dimension_accuracy.add(s_dims[1] == stored_s[1])
        metrics.directness_dimension_accuracy.add(s_dims[2] == stored_s[2])
        metrics.coverage_dimension_accuracy.add(c_dims[0] == stored_c[0])
        metrics.corroboration_dimension_accuracy.add(c_dims[1] == stored_c[1])
        metrics.directness_dimension_accuracy.add(c_dims[2] == stored_c[2])

        reconciles = (
            card.support.index_bp == sum(stored_s)
            and card.contradiction.index_bp == sum(stored_c)
        )
        metrics.arithmetic_reconciliation_accuracy.add(reconciles)
        metrics.aggregate_score_arithmetic_mismatch_rate.record(not reconciles)

        # Recomputing each channel from its own traces alone is what proves the
        # contradiction index did not leak into the support index.
        metrics.contradiction_increased_support_index_rate.record(
            card.support.index_bp != sum(s_dims)
        )

        in_range = (
            0 <= card.support.index_bp <= INDEX_MAX_BP
            and 0 <= card.contradiction.index_bp <= INDEX_MAX_BP
            and stored_s[0] <= COVERAGE_DIMENSION_MAX_BP
            and stored_s[1] <= CORROBORATION_DIMENSION_MAX_BP
            and stored_s[2] <= DIRECTNESS_DIMENSION_MAX_BP
        )
        metrics.score_bound_accuracy.add(in_range)
        metrics.out_of_range_score_acceptance_rate.record(not in_range)

        # --- exact expected numbers, authored from the input ---------------
        if cid in expected.support_index_bp:
            metrics.support_index_accuracy.add(
                card.support.index_bp == expected.support_index_bp[cid]
            )
        if cid in expected.contradiction_index_bp:
            metrics.contradiction_index_accuracy.add(
                card.contradiction.index_bp == expected.contradiction_index_bp[cid]
            )
        if cid in expected.support_dimensions_bp:
            metrics.support_index_accuracy.add(
                list(stored_s) == expected.support_dimensions_bp[cid]
            )
        if cid in expected.contradiction_dimensions_bp:
            metrics.contradiction_index_accuracy.add(
                list(stored_c) == expected.contradiction_dimensions_bp[cid]
            )
        if cid in expected.covered_components:
            metrics.coverage_dimension_accuracy.add(
                card.support.covered_components == expected.covered_components[cid]
            )
        if cid in expected.contradicted_components:
            metrics.coverage_dimension_accuracy.add(
                card.contradiction.covered_components
                == expected.contradicted_components[cid]
            )
        if cid in expected.saturated_components:
            metrics.saturation_accuracy.add(
                card.support.saturated_components
                == expected.saturated_components[cid]
            )
        if cid in expected.contributing_groups:
            metrics.saturation_accuracy.add(
                len(card.support.contributing_group_ids)
                == expected.contributing_groups[cid]
            )
        if cid in expected.unexamined_components:
            metrics.unexamined_component_accuracy.add(
                card.unexamined_component_count
                == expected.unexamined_components[cid]
            )

        # --- disposition and the zero/None distinction ---------------------
        if cid in expected.disposition:
            metrics.score_disposition_accuracy.add(
                card.disposition.value == expected.disposition[cid]
            )
        withheld_expected = cid in expected.final_withheld
        issued_expected = cid in expected.final_support_index_bp
        if withheld_expected or issued_expected:
            correct = (
                card.final_support_index_bp is None
                if withheld_expected
                else card.final_support_index_bp
                == expected.final_support_index_bp[cid]
            )
            metrics.final_scalar_issuance_accuracy.add(correct)
            metrics.zero_versus_none_accuracy.add(correct)

        issued = card.final_support_index_bp is not None
        metrics.contested_claim_received_final_scalar_rate.record(
            card.sufficiency_outcome.value == "CONTESTED" and issued
        )
        metrics.blocked_source_quality_received_final_scalar_rate.record(
            card.sufficiency_outcome.value == "BLOCKED_SOURCE_QUALITY" and issued
        )
        metrics.incomplete_inventory_received_full_scalar_rate.record(
            card.inventory_completeness.value != "COMPLETE" and issued
        )
        metrics.invalid_score_disposition_acceptance_rate.record(
            issued and card.disposition is not ScoreDisposition.SCORED
        )
        # A net would make 90/80 read like 10/0. The issued scalar must be the
        # support index itself, and must not equal the difference unless the
        # contradiction channel is genuinely zero.
        collapsed = issued and (
            card.final_support_index_bp != card.support.index_bp
            or (
                card.contradiction.index_bp > 0
                and card.final_support_index_bp
                == card.support.index_bp - card.contradiction.index_bp
            )
        )
        metrics.support_contradiction_collapsed_into_net_rate.record(collapsed)

        # --- reliability ---------------------------------------------------
        if cid in expected.reliability:
            metrics.reliability_profile_accuracy.add(
                card.reliability.posture.value == expected.reliability[cid]
            )
        metrics.unknown_quality_treated_as_favorable_rate.record(
            (
                card.reliability.unknown_publication_group_count
                or card.reliability.unknown_retraction_group_count
            )
            and card.reliability.posture is ReliabilityPosture.HIGHER_RELIABILITY
        )
        metrics.unknown_metadata_improved_reliability_rate.record(
            card.reliability.unknown_publication_group_count
            == card.reliability.contributing_group_count
            and card.reliability.contributing_group_count > 0
            and expected_reliability_rank(card.reliability.posture) > 0
        )
        # "Retraction must not *increase* support or reliability" is a claim
        # about a retracted group earning something -- not about a retracted
        # source merely existing. A retracted paper sitting beside a clean one
        # is the normal case, and it must leave the clean one's score alone.
        retracted_groups = {
            p.independence_group_id
            for p in (
                outcome.sufficiency_run.weight_profiles
                if outcome.sufficiency_run
                else []
            )
            if p.claim_id == cid and p.retraction_status is RetractionStatus.RETRACTED
        }
        credited = set(card.support.contributing_group_ids) | set(
            card.contradiction.contributing_group_ids
        )
        metrics.retraction_increased_support_or_reliability_rate.record(
            bool(retracted_groups & credited)
            or bool(
                retracted_groups
                and card.reliability.contributing_group_count
                and card.reliability.retracted_group_count
                > card.reliability.contributing_group_count
                + card.reliability.disqualified_group_count
            )
        )

        # --- reason codes --------------------------------------------------
        codes = {r.value for r in card.reason_codes}
        if cid in expected.reason_codes:
            metrics.reason_code_accuracy.add(
                set(expected.reason_codes[cid]) <= codes
            )
        if cid in expected.forbidden_reason_codes:
            metrics.reason_code_accuracy.add(
                not (set(expected.forbidden_reason_codes[cid]) & codes)
            )
        if cid in expected.withheld_reasons:
            metrics.withheld_reason_accuracy.add(
                set(expected.withheld_reasons[cid])
                <= {r.value for r in card.withheld_reasons}
            )

        # --- traceability --------------------------------------------------
        assessment = (
            outcome.sufficiency_run.assessments if outcome.sufficiency_run else []
        )
        by_claim = {a.claim_id: a for a in assessment}
        source = by_claim.get(cid)
        metrics.score_traceability.add(
            source is not None
            and card.assessment_id == source.assessment_id
            and card.sufficiency_outcome is source.outcome
            and card.inventory_completeness is source.inventory_completeness
        )
        metrics.policy_version_accuracy.add(
            card.policy_version == CLAIM_EVIDENCE_SCORING_POLICY_VERSION
            and bool(card.schema_version)
            and bool(card.arithmetic_version)
        )

        # --- non-support must never become direct support ------------------
        profiles = [
            p
            for p in (
                outcome.sufficiency_run.weight_profiles
                if outcome.sufficiency_run
                else []
            )
            if p.claim_id == cid
        ]
        _record_non_support_gates(metrics, card, profiles)

    # --- duplicate invariance and fingerprint pairing ----------------------
    _record_duplicate_gates(case, outcome, metrics)
    _record_fingerprint_gates(case, outcome, metrics, dataset)
    _record_idempotency(outcome, metrics)


def _record_non_support_gates(
    metrics: ClaimScoringMetrics, card: Any, profiles: list[Any]
) -> None:
    """Context, insufficient, not-relevant and retracted must earn nothing.

    Checked against the *card* rather than against the policy: if only
    non-supporting classes reached a component, that component must not be
    adequately supported, whatever the policy code believes.
    """
    classes = {p.contribution for p in profiles}
    covered = card.support.covered_components

    only_context = classes and classes <= {EvidenceContributionClass.CONTEXT_ONLY}
    only_insufficient = classes and classes <= {
        EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT
    }
    only_not_relevant = classes and classes <= {
        EvidenceContributionClass.NOT_RELEVANT
    }
    metrics.context_only_counted_as_direct_support_rate.record(
        bool(only_context and covered)
    )
    metrics.insufficient_counted_as_direct_support_rate.record(
        bool(only_insufficient and covered)
    )
    metrics.not_relevant_counted_as_direct_support_rate.record(
        bool(only_not_relevant and covered)
    )
    metrics.irrelevant_evidence_increased_support_index_rate.record(
        bool(
            classes
            and classes
            <= {
                EvidenceContributionClass.CONTEXT_ONLY,
                EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT,
                EvidenceContributionClass.NOT_RELEVANT,
            }
            and card.support.index_bp
        )
    )

    retracted_groups = {
        p.independence_group_id
        for p in profiles
        if p.retraction_status is RetractionStatus.RETRACTED
    }
    contributing = set(card.support.contributing_group_ids)
    metrics.retracted_source_counted_as_eligible_support_rate.record(
        bool(retracted_groups & contributing)
    )


def _record_duplicate_gates(
    case: ScoringGoldCase, outcome: ScoringCaseResult, metrics: ClaimScoringMetrics
) -> None:
    """A duplicate source, excerpt or provider must not raise either channel.

    Re-derived from the fixture: the number of *distinct canonical identities*
    is the most corroborating groups any channel may report. If a card claims
    more contributing groups than the world holds distinct works, something
    counted a duplicate as a study.
    """
    identities = set()
    for spec in case.sources:
        if spec.orphan:
            continue
        strongest = (
            spec.doi
            or spec.openalex_id
            or spec.semantic_scholar_id
            or spec.arxiv_id
            or spec.pmid
            or spec.canonical_url
        )
        identities.add(strongest)
    ceiling = len(identities)
    scoring = outcome.scoring_run
    if scoring is None:
        return
    inflated_support = any(
        len(c.support.contributing_group_ids) > ceiling for c in scoring.scorecards
    )
    inflated_contradiction = any(
        len(c.contradiction.contributing_group_ids) > ceiling
        for c in scoring.scorecards
    )
    excerpt_ceiling = ceiling
    excerpt_inflated = any(
        len(c.support.contributing_group_ids) > excerpt_ceiling
        for c in scoring.scorecards
    )
    provider_inflated = any(
        len(c.support.contributing_group_ids) > ceiling for c in scoring.scorecards
    )

    metrics.duplicate_logical_source_inflated_support_rate.record(inflated_support)
    metrics.duplicate_logical_source_inflated_contradiction_rate.record(
        inflated_contradiction
    )
    metrics.duplicate_excerpt_inflated_support_rate.record(excerpt_inflated)
    metrics.duplicate_excerpt_inflated_contradiction_rate.record(
        inflated_contradiction
    )
    metrics.provider_observation_inflated_support_rate.record(provider_inflated)
    metrics.provider_observation_inflated_contradiction_rate.record(
        inflated_contradiction
    )
    metrics.duplicate_evidence_increased_support_index_rate.record(inflated_support)
    metrics.duplicate_invariance_accuracy.add(
        not (inflated_support or inflated_contradiction)
    )
    metrics.monotonicity_invariant_accuracy.add(
        all(
            c.support.saturated_components <= c.support.total_components
            for c in scoring.scorecards
        )
    )


def _record_fingerprint_gates(
    case: ScoringGoldCase,
    outcome: ScoringCaseResult,
    metrics: ClaimScoringMetrics,
    dataset: ScoringGoldDataset | None,
) -> None:
    """Fingerprint stability on a rerun, and sensitivity across a case pair."""
    scoring = outcome.scoring_run
    if scoring is None:
        return
    if outcome.stable_rerun_run is not None:
        mine = {c.claim_id: c.input_fingerprint for c in scoring.scorecards}
        theirs = {
            c.claim_id: c.input_fingerprint
            for c in outcome.stable_rerun_run.scorecards
        }
        stable = bool(mine) and mine == theirs
        metrics.unstable_identical_input_fingerprint_rate.record(not stable)
        metrics.input_fingerprint_accuracy.add(stable)
    else:
        metrics.input_fingerprint_accuracy.add(
            all(len(c.input_fingerprint) == 64 for c in scoring.scorecards)
        )

    if case.fingerprint_pair is None or dataset is None:
        return
    partner_id, mode = case.fingerprint_pair.split(":")
    partner = dataset.by_id(partner_id)
    if partner is None:
        return
    partner_result = run_scoring_case(partner)
    if partner_result.scoring_run is None:
        return
    mine = {c.claim_id: c.input_fingerprint for c in scoring.scorecards}
    theirs = {
        c.claim_id: c.input_fingerprint for c in partner_result.scoring_run.scorecards
    }
    shared = set(mine) & set(theirs)
    if not shared:
        return
    identical = all(mine[k] == theirs[k] for k in shared)
    if mode == "same":
        metrics.unstable_identical_input_fingerprint_rate.record(not identical)
        metrics.input_fingerprint_accuracy.add(identical)
    else:
        metrics.fingerprint_unchanged_on_relevant_input_change_rate.record(identical)
        metrics.input_fingerprint_accuracy.add(not identical)


def _record_idempotency(
    outcome: ScoringCaseResult, metrics: ClaimScoringMetrics
) -> None:
    """A rerun must reproduce identical scorecards, ids included."""
    scoring = outcome.scoring_run
    if scoring is None:
        return
    claim_ids = [c.claim_id for c in scoring.scorecards]
    no_duplicates = len(set(claim_ids)) == len(claim_ids)
    metrics.incompatible_duplicate_scorecard_acceptance_rate.record(not no_duplicates)

    if outcome.rerun_run is None:
        metrics.idempotency_accuracy.add(no_duplicates)
        return
    mine = _comparable(scoring)
    theirs = _comparable(outcome.rerun_run)
    metrics.idempotency_accuracy.add(no_duplicates and mine == theirs)


def _comparable(scoring: ClaimEvidenceScoringRun) -> list[dict[str, Any]]:
    """A scoring run's scorecards without the fields a rerun may legitimately
    change: the run id, the ids derived from it, and the creation timestamp."""
    out: list[dict[str, Any]] = []
    for card in sorted(scoring.scorecards, key=lambda c: c.claim_id):
        payload = card.model_dump(mode="json")
        for volatile in (
            "scorecard_id",
            "scoring_run_id",
            "sufficiency_run_id",
            "assessment_id",
            "created_at",
            "input_fingerprint",
        ):
            payload.pop(volatile, None)
        out.append(_strip_uuids(payload))
    return out


def _strip_uuids(value: Any) -> Any:
    """Drop group-id values, which are keyed on the run id and so differ
    between two independent runs of the same world."""
    if isinstance(value, dict):
        return {
            k: _strip_uuids(v)
            for k, v in value.items()
            if not k.endswith("group_ids")
        }
    if isinstance(value, list):
        return [_strip_uuids(v) for v in value]
    return value


def _flatten_keys(value: Any, out: set[str] | None = None) -> set[str]:
    out = set() if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(key)
            _flatten_keys(item, out)
    elif isinstance(value, list):
        for item in value:
            _flatten_keys(item, out)
    return out


# ---------------------------------------------------------------------------
# Dataset driver
# ---------------------------------------------------------------------------


def run_scoring_dataset(
    dataset: ScoringGoldDataset,
) -> tuple[ClaimScoringMetrics, list[ScoringCaseResult]]:
    metrics = ClaimScoringMetrics()
    results: list[ScoringCaseResult] = []
    for case in dataset.cases:
        outcome = run_scoring_case(case)
        results.append(outcome)
        score_scoring_case(case, outcome, metrics, dataset)
    return metrics, results


def score_by_language(
    dataset: ScoringGoldDataset, results: list[ScoringCaseResult]
) -> dict[str, ClaimScoringMetrics]:
    """Per-language metrics, so an aggregate pass cannot hide a failing subgroup."""
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, ClaimScoringMetrics] = {}
    for outcome in results:
        case = by_id.get(outcome.case_id)
        if case is None:
            continue
        score_scoring_case(
            case,
            outcome,
            grouped.setdefault(case.language, ClaimScoringMetrics()),
            dataset,
        )
    return grouped


@dataclass
class ScoringGateResult:
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


def evaluate_scoring_gate(metrics: ClaimScoringMetrics) -> ScoringGateResult:
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return ScoringGateResult(
        passed=metrics.safety_clean
        and metrics.thresholds_met
        and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        thresholds_met=metrics.thresholds_met,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )


__all__ = [
    "PROJECT_SCORE_FIELDS",
    "TRUTH_PROBABILITY_FIELDS",
    "ScoringCaseResult",
    "ScoringGateResult",
    "declared_anchor_spans",
    "evaluate_scoring_gate",
    "expected_component_spans",
    "expected_reliability_rank",
    "recomputed_channel_bp",
    "run_scoring_case",
    "run_scoring_dataset",
    "score_by_language",
    "score_scoring_case",
]
