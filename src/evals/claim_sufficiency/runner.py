"""Claim sufficiency eval runner -- Phase 2E.

Each Gold case is driven through the **real Phase 2E graph** through a real
checkpointer, so what is measured is the shipped path: grouping, profiling,
component aggregation, policy application and finalization.

Scoring is implemented here, independently of the code it scores. The eval
never asks the pipeline whether it grouped correctly. It re-derives the
independence partition from the fixture's own identifiers, re-counts distinct
canonical identities per direction, re-checks every claim anchor against the
claim text from scratch, re-derives which contribution classes the relations
and quality facts permit, and diffs the whole project state, the Phase 2C
evidence and the Phase 2D alignments before and after.

That independence is what lets the negative controls prove the eval can fail:
breaking a rule in ``src/research/sufficiency`` does not break the metric
watching for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.evals.claim_sufficiency.dataset import (
    SufficiencyGoldCase,
    SufficiencyGoldDataset,
    build_academic_result,
    build_alignment_run,
    build_alignments,
    build_claims,
    build_evidence,
    build_extraction_run,
    build_logical_sources,
    evidence_id_for,
    gold_alignment_run_id,
    gold_run_id,
)
from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2e_graph import build_phase2e_claim_sufficiency_graph
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.sufficiency_nodes import SUFFICIENCY_DATASET_VERSION_KEY
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.research.inputs import project_state_fingerprint
from src.research.planner import PLANNER_VERSION
from src.research.settings import ResearchSettings
from src.research.sufficiency.pipeline import assess_claim, readiness
from src.schemas.claim_alignment import AlignmentRelation
from src.schemas.claim_sufficiency import (
    SUFFICIENCY_POLICY_VERSION,
    ClaimSufficiencyRun,
    ClaimSufficiencyStatus,
    ComponentCoverage,
    EvidenceContributionClass,
    RetractionStatus,
    SufficiencyOutcome,
    TraceabilityStatus,
    UNRESOLVED_GROUP_ID,
)
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions
from src.research.coverage import initial_branch_coverage
from src.schemas.common import EvaluationStatus
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult

logger = logging.getLogger(__name__)

CLAIM_VERDICT_FIELDS = (
    "claim_status",
    "status_delta",
    "confidence",
    "confidence_delta",
    "verified",
    "score",
    "score_delta",
    "evidence_ids",
    "counter_evidence_ids",
    "trust_gate",
    "evaluation_status",
    "evidence_weight",
    "weight_score",
)
"""Fields Phase 2E must not be able to set, checked structurally against the
serialized sufficiency run. ``evidence_weight`` and ``weight_score`` are in the
list specifically to catch a future edit that reintroduces the opaque scalar
ADR-015 forbids."""

NOT_READY_STATUSES = frozenset(
    {
        ClaimSufficiencyStatus.NOT_READY,
        ClaimSufficiencyStatus.NO_ASSESSABLE_CLAIMS,
        ClaimSufficiencyStatus.NO_ACCEPTED_EVIDENCE,
        ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS,
        ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE,
    }
)
"""Statuses where the pass stopped before grouping. Such a run must carry no
groups, no profiles and no assessments."""

DIRECT_SUPPORT_RELATIONS = frozenset({AlignmentRelation.SUPPORTS})
DIRECT_CONTRADICTION_RELATIONS = frozenset({AlignmentRelation.CONTRADICTS})
NON_SUPPORTING_RELATIONS = frozenset(
    {
        AlignmentRelation.CONTEXT_ONLY,
        AlignmentRelation.INSUFFICIENT,
        AlignmentRelation.NOT_RELEVANT,
    }
)


@dataclass
class SufficiencyCaseResult:
    case_id: str
    categories: list[str]
    language: str
    sufficiency_run: ClaimSufficiencyRun | None = None
    rerun_run: ClaimSufficiencyRun | None = None
    claims: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    alignments: list[Any] = field(default_factory=list)
    run_id: Any = None
    alignment_run_id: Any = None
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
    alignments_mutated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _open_run(case: SufficiencyGoldCase, project: ProjectState) -> ResearchRun:
    run = ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="sufficiency-gold",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(
        academic_research=build_academic_result(case),
        evidence_extraction=build_extraction_run(case),
        claim_evidence_alignment=build_alignment_run(case),
    )


def _populated_project(case: SufficiencyGoldCase) -> ProjectState:
    """A populated project state, so immutability is proven against real values.

    An empty-state test cannot catch the mutation of something that was never
    there (section 25). So alongside the case's claims this carries a real
    ``TrustGateResult`` with a blocker and a non-default ``evaluation_status`` --
    exactly the fields Phase 2E must leave byte-for-byte alone, and the ones a
    later scoring phase will own.
    """
    project = ProjectState()
    project.claims = build_claims(case)
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


def _run_direct_case(case: SufficiencyGoldCase) -> SufficiencyCaseResult:
    """Shapes a validated run record cannot hold, driven straight at the pipeline.

    A ``ClaimEvidenceAlignmentRun`` rightly refuses an alignment from another
    research run, so cross-run rejection is exercised by calling the real
    ``assess_claim`` with such an alignment -- still production code, entered
    below the graph rather than around it.
    """
    outcome = SufficiencyCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = _populated_project(case)
        run_id = gold_run_id(case)
        sufficiency_run_id = uuid4()
        alignments = build_alignments(case)
        evidence = build_evidence(case)
        sources = build_logical_sources(case)

        from src.research.sufficiency.identity import build_independence_groups

        groups, evidence_to_group = build_independence_groups(
            run_id, evidence, sources
        )
        group_index = {g.independence_group_id: g for g in groups}
        evidence_index = {e.evidence_id: e for e in evidence}

        assessments = []
        profiles = []
        for claim in project.claims:
            claim_alignments = [a for a in alignments if a.claim_id == claim.claim_id]
            if not claim_alignments:
                continue
            assessment, claim_profiles = assess_claim(
                claim,
                claim_alignments,
                evidence_index,
                group_index,
                evidence_to_group,
                research_run_id=run_id,
                sufficiency_run_id=sufficiency_run_id,
                alignment_run_id=gold_alignment_run_id(case),
            )
            assessments.append(assessment)
            profiles.extend(claim_profiles)

        outcome.sufficiency_run = ClaimSufficiencyRun(
            sufficiency_run_id=sufficiency_run_id,
            research_run_id=run_id,
            alignment_run_id=gold_alignment_run_id(case),
            status=ClaimSufficiencyStatus.COMPLETED,
            independence_groups=groups,
            weight_profiles=profiles,
            assessments=assessments,
            completed_at="2026-09-01T09:20:00+00:00",
        )
        outcome.claims = project.claims
        outcome.evidence = evidence
        outcome.alignments = alignments
        outcome.run_id = run_id
        outcome.alignment_run_id = gold_alignment_run_id(case)
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


def run_sufficiency_case(case: SufficiencyGoldCase) -> SufficiencyCaseResult:
    """Drive one Gold case through the real Phase 2E graph."""
    if case.direct_mode:
        return _run_direct_case(case)
    outcome = SufficiencyCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = _populated_project(case)
        before = project_state_fingerprint(project)
        claims_before = [
            (
                c.claim_id,
                c.claim,
                c.status.value,
                tuple(c.evidence_ids),
                tuple(c.counter_evidence_ids),
                c.confidence,
            )
            for c in project.claims
        ]
        scores_before = [s.model_dump() for s in project.scores]
        gate_before = project.trust_gate
        eval_status_before = project.evaluation_status

        run = _open_run(case, project)
        evidence_before = [
            e.model_dump(mode="json") for e in run.evidence_extraction.verified_evidence
        ]
        alignments_before = [
            a.model_dump(mode="json")
            for a in run.claim_evidence_alignment.alignments
        ]

        run_id = uuid4()
        config = thread_config(new_thread_id(run_id))
        config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
        config["configurable"][SUFFICIENCY_DATASET_VERSION_KEY] = "sufficiency-gold-v1"

        checkpointer = build_checkpointer()
        app = build_phase2e_claim_sufficiency_graph(checkpointer)
        initial = EvaluationGraphState(
            run_id=run_id,
            thread_id=config["configurable"]["thread_id"],
            project=project,
            research_runs={str(run.research_run_id): run},
            active_research_run_id=run.research_run_id,
        )

        if case.resume_after_node is not None:
            # Interrupt before the named node, then resume from the checkpoint:
            # the resumed half must neither lose nor duplicate work (section 24).
            interrupting = build_phase2e_claim_sufficiency_graph(checkpointer)
            interrupting.invoke(
                initial,
                {
                    **config,
                    "interrupt_before": [case.resume_after_node],
                },
            )
            state = coerce_graph_state(app.invoke(None, config))
        else:
            state = coerce_graph_state(app.invoke(initial, config))

        if case.rerun:
            state = coerce_graph_state(app.invoke(None, config))
            second = build_phase2e_claim_sufficiency_graph(build_checkpointer())
            rerun_config = thread_config(new_thread_id(uuid4()))
            rerun_config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
            rerun_state = coerce_graph_state(
                second.invoke(
                    EvaluationGraphState(
                        run_id=uuid4(),
                        thread_id=rerun_config["configurable"]["thread_id"],
                        project=_populated_project(case),
                        research_runs={str(run.research_run_id): _open_run(case, project)},
                        active_research_run_id=run.research_run_id,
                    ),
                    rerun_config,
                )
            )
            finished_rerun = rerun_state.active_research_run
            outcome.rerun_run = (
                finished_rerun.claim_sufficiency if finished_rerun else None
            )

        finished = state.active_research_run
        outcome.sufficiency_run = finished.claim_sufficiency if finished else None
        outcome.claims = state.project.claims
        outcome.evidence = (
            finished.evidence_extraction.verified_evidence
            if finished and finished.evidence_extraction
            else []
        )
        outcome.alignments = (
            finished.claim_evidence_alignment.alignments
            if finished and finished.claim_evidence_alignment
            else []
        )
        outcome.run_id = finished.research_run_id if finished else run.research_run_id
        outcome.alignment_run_id = (
            finished.claim_evidence_alignment.alignment_run_id
            if finished and finished.claim_evidence_alignment
            else None
        )

        outcome.project_mutated = project_state_fingerprint(state.project) != before
        claims_after = [
            (
                c.claim_id,
                c.claim,
                c.status.value,
                tuple(c.evidence_ids),
                tuple(c.counter_evidence_ids),
                c.confidence,
            )
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
        outcome.extracted_evidence_mutated = [
            e.model_dump(mode="json") for e in outcome.evidence
        ] != evidence_before
        outcome.alignments_mutated = [
            a.model_dump(mode="json") for a in outcome.alignments
        ] != alignments_before
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


# ---------------------------------------------------------------------------
# Independent re-derivation
# ---------------------------------------------------------------------------


def expected_independence_partition(case: SufficiencyGoldCase) -> dict[str, set[str]]:
    """Re-derive the correct grouping from the case's own identifiers.

    Deliberately written from the Gold description rather than by calling
    ``build_independence_groups``: the strongest identifier wins, DOI first,
    and a title never participates. Two source keys sharing that identifier are
    one group, so this function is the eval's own answer to the question the
    pipeline is being graded on.
    """
    priority = ("doi", "pmid", "openalex_id", "semantic_scholar_id", "arxiv_id")
    identity_by_source: dict[str, str] = {}
    for spec in case.sources:
        if spec.orphan:
            continue
        chosen = next(
            (
                f"{field_name}:{getattr(spec, field_name)}"
                for field_name in priority
                if getattr(spec, field_name)
            ),
            None,
        )
        identity_by_source[spec.key] = chosen or f"url:{spec.canonical_url}"

    partition: dict[str, set[str]] = {}
    for item in case.evidence:
        if item.missing_from_run:
            continue
        identity = identity_by_source.get(item.source)
        if identity is None:
            continue
        partition.setdefault(identity, set()).add(item.key)
    return partition


def expected_contribution(
    case: SufficiencyGoldCase, alignment_spec: Any
) -> EvidenceContributionClass:
    """Re-derive the only contribution class this input shape permits."""
    by_evidence = {e.key: e for e in case.evidence}
    by_source = {s.key: s for s in case.sources}
    item = by_evidence[alignment_spec.evidence]
    source = by_source[item.source]

    untraceable = (
        alignment_spec.foreign_run
        or alignment_spec.hash_mismatch
        or item.missing_from_run
        or source.orphan
    )
    if untraceable:
        return EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
    retracted = (
        item.is_retracted is True
        or (item.is_retracted is None and source.is_retracted is True)
    )
    if retracted:
        return EvidenceContributionClass.DISQUALIFIED_RETRACTED
    return {
        AlignmentRelation.SUPPORTS: EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT,
        AlignmentRelation.PARTIALLY_SUPPORTS: (
            EvidenceContributionClass.ELIGIBLE_PARTIAL_SUPPORT
        ),
        AlignmentRelation.CONTRADICTS: (
            EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION
        ),
        AlignmentRelation.PARTIALLY_CONTRADICTS: (
            EvidenceContributionClass.ELIGIBLE_PARTIAL_CONTRADICTION
        ),
        AlignmentRelation.MIXED: EvidenceContributionClass.ELIGIBLE_MIXED,
        AlignmentRelation.CONTEXT_ONLY: EvidenceContributionClass.CONTEXT_ONLY,
        AlignmentRelation.INSUFFICIENT: (
            EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT
        ),
        AlignmentRelation.NOT_RELEVANT: EvidenceContributionClass.NOT_RELEVANT,
    }[AlignmentRelation(alignment_spec.relation)]


def _anchor_is_real(claim_text: str, start: int, end: int, text: str) -> bool:
    if not (0 <= start < end <= len(claim_text)):
        return False
    return claim_text[start:end] == text


def _claims_a_verdict(payload: Any) -> bool:
    """Structural scan for a field the sufficiency contract must not have."""
    if isinstance(payload, dict):
        if any(name in payload for name in CLAIM_VERDICT_FIELDS):
            return True
        return any(_claims_a_verdict(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_claims_a_verdict(item) for item in payload)
    return False


def score_sufficiency_case(  # noqa: C901 -- one metric per branch, read top to bottom
    case: SufficiencyGoldCase,
    outcome: SufficiencyCaseResult,
    metrics: ClaimSufficiencyMetrics,
) -> None:
    """Score one case, re-deriving every judgement from the fixture."""
    run = outcome.sufficiency_run
    if not outcome.ok or run is None:
        metrics.cases_errored += 1
        return
    metrics.cases_evaluated += 1
    expected = case.expected
    claims = {c.claim_id: c for c in outcome.claims}
    evidence = {e.evidence_id: e for e in outcome.evidence}
    alignments = {a.alignment_id: a for a in outcome.alignments}

    # -- release-blocking: immutability -------------------------------------
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
    metrics.alignment_mutation_rate.record(outcome.alignments_mutated)

    payload = run.model_dump(mode="json")
    verdict_leak = _claims_a_verdict(payload)
    metrics.automatic_claim_status_update_rate.record(verdict_leak)
    metrics.automatic_score_update_rate.record(verdict_leak)
    metrics.sufficiency_mutated_trust_gate_rate.record(
        verdict_leak or outcome.trust_gate_mutated
    )
    metrics.sufficiency_mutated_project_score_rate.record(
        verdict_leak or outcome.scores_mutated
    )

    # -- independence grouping, re-derived independently --------------------
    partition = expected_independence_partition(case)
    key_by_evidence_id = {evidence_id_for(case, i.key): i.key for i in case.evidence}
    got_partition = {
        g.canonical_identity: {
            key_by_evidence_id.get(eid, str(eid)) for eid in g.member_evidence_ids
        }
        for g in run.independence_groups
    }
    if run.status in NOT_READY_STATUSES:
        # A pass that never reached grouping must carry no groups at all: a
        # not-ready Phase 2D state must not leave a half-built partition behind.
        metrics.independence_grouping_accuracy.add(not run.independence_groups)
    else:
        metrics.independence_grouping_accuracy.add(
            sorted(sorted(v) for v in got_partition.values())
            == sorted(sorted(v) for v in partition.values())
        )
        if expected.independence_groups is not None:
            metrics.independence_grouping_accuracy.add(
                len(run.independence_groups) == expected.independence_groups
            )

    expected_collapse = sum(len(v) for v in partition.values()) - len(partition)
    metrics.duplicate_collapse_accuracy.add(
        run.coverage.duplicate_evidence_collapsed == max(expected_collapse, 0)
        if run.assessments
        else run.coverage.duplicate_evidence_collapsed == 0
    )
    if expected.duplicate_evidence_collapsed is not None:
        metrics.duplicate_collapse_accuracy.add(
            run.coverage.duplicate_evidence_collapsed
            == expected.duplicate_evidence_collapsed
        )

    # Every evidence item in one group resolves to one canonical identity, and
    # no group holds two identities: the duplicate-independence gates.
    for group in run.independence_groups:
        metrics.duplicate_logical_source_independence_rate.record(
            len(
                {
                    identity
                    for identity, keys in partition.items()
                    if keys
                    & {
                        k
                        for k in (i.key for i in case.evidence)
                        if evidence_id_for(case, k) in set(group.member_evidence_ids)
                    }
                }
            )
            > 1
        )
        metrics.provider_observation_independence_rate.record(
            group.quality.provider_observation_count > 1
            and len(
                [
                    g
                    for g in run.independence_groups
                    if g.canonical_identity == group.canonical_identity
                ]
            )
            > 1
        )

    # -- per-alignment contribution classification --------------------------
    spec_by_pair = {
        (a.claim_id, evidence_id_for(case, a.evidence)): a for a in case.alignments
    }
    for profile in run.weight_profiles:
        spec = spec_by_pair.get((profile.claim_id, profile.evidence_id))
        if spec is not None:
            metrics.contribution_classification_accuracy.add(
                profile.contribution is expected_contribution(case, spec)
            )

        metrics.invalid_claim_reference_acceptance_rate.record(
            profile.claim_id not in claims
        )
        metrics.invalid_alignment_reference_acceptance_rate.record(
            bool(alignments) and profile.alignment_id not in alignments
        )
        item = evidence.get(profile.evidence_id)
        contributes = profile.is_eligible
        metrics.invalid_evidence_reference_acceptance_rate.record(
            contributes and item is None
        )
        metrics.cross_run_evidence_acceptance_rate.record(
            contributes and (item is None or item.research_run_id != outcome.run_id)
        )
        alignment = alignments.get(profile.alignment_id)
        metrics.cross_run_alignment_acceptance_rate.record(
            contributes
            and alignment is not None
            and alignment.research_run_id != outcome.run_id
        )
        metrics.untraceable_evidence_contribution_rate.record(
            contributes and profile.traceability is not TraceabilityStatus.TRACEABLE
        )
        metrics.retracted_evidence_corroboration_rate.record(
            contributes and profile.retraction_status is RetractionStatus.RETRACTED
        )
        metrics.context_only_counted_as_support_rate.record(
            profile.relation is AlignmentRelation.CONTEXT_ONLY and contributes
        )
        metrics.insufficient_counted_as_support_rate.record(
            profile.relation is AlignmentRelation.INSUFFICIENT and contributes
        )
        metrics.not_relevant_counted_as_support_rate.record(
            profile.relation is AlignmentRelation.NOT_RELEVANT and contributes
        )
        # Unknown must not silently read as favorable: an unknown retraction or
        # publication status must still be reported as unknown on the profile.
        metrics.unknown_quality_treated_as_favorable_rate.record(
            profile.retraction_status is RetractionStatus.UNKNOWN
            and "RETRACTION_STATUS_UNKNOWN"
            not in [limitation.value for limitation in profile.limitations]
        )
        metrics.unknown_state_preservation_accuracy.add(
            profile.retraction_status is not RetractionStatus.UNKNOWN
            or "RETRACTION_STATUS_UNKNOWN"
            in [limitation.value for limitation in profile.limitations]
        )
        metrics.retraction_handling_accuracy.add(
            profile.retraction_status is not RetractionStatus.RETRACTED
            or profile.contribution
            is EvidenceContributionClass.DISQUALIFIED_RETRACTED
        )
        metrics.policy_versioning_accuracy.add(
            profile.policy_version == SUFFICIENCY_POLICY_VERSION
        )

    # -- per-assessment -----------------------------------------------------
    if expected.assessments_total is not None:
        metrics.sufficiency_outcome_accuracy.add(
            len(run.assessments) == expected.assessments_total
        )
    claim_ids = [a.claim_id for a in run.assessments]
    metrics.incompatible_duplicate_assessment_rate.record(
        len(set(claim_ids)) != len(claim_ids)
    )

    for assessment in run.assessments:
        claim = claims.get(assessment.claim_id)
        metrics.assessment_traceability.add(
            assessment.research_run_id == outcome.run_id
            and assessment.sufficiency_run_id == run.sufficiency_run_id
            and claim is not None
            and set(assessment.profile_ids)
            <= {p.profile_id for p in run.weight_profiles}
            and set(assessment.independence_group_ids)
            <= {g.independence_group_id for g in run.independence_groups}
        )
        metrics.policy_versioning_accuracy.add(
            assessment.policy_version == SUFFICIENCY_POLICY_VERSION
            and assessment.contract_version
            and assessment.profile_version
            and assessment.aggregator_version
        )

        # Every component anchor is re-checked against the claim text.
        for component in assessment.components:
            metrics.exact_claim_anchor_accuracy.add(
                claim is not None
                and _anchor_is_real(
                    claim.claim,
                    component.anchor_start,
                    component.anchor_end,
                    component.anchor_text,
                )
            )

        expected_outcome = expected.outcomes.get(assessment.claim_id)
        if expected_outcome is not None:
            metrics.sufficiency_outcome_accuracy.add(
                assessment.outcome.value == expected_outcome
            )
        expected_coverage = expected.component_coverage.get(assessment.claim_id)
        if expected_coverage is not None:
            metrics.component_coverage_accuracy.add(
                [c.coverage.value for c in assessment.components] == expected_coverage
            )
        expected_supporting = expected.supporting_groups.get(assessment.claim_id)
        if expected_supporting is not None:
            metrics.independence_grouping_accuracy.add(
                assessment.supporting_group_count == expected_supporting
            )
        expected_contradicting = expected.contradicting_groups.get(assessment.claim_id)
        if expected_contradicting is not None:
            metrics.independence_grouping_accuracy.add(
                assessment.contradicting_group_count == expected_contradicting
            )
        required_reasons = expected.reason_codes.get(assessment.claim_id)
        if required_reasons is not None:
            got = {r.value for r in assessment.reason_codes}
            metrics.reason_code_accuracy.add(set(required_reasons) <= got)
        forbidden = expected.forbidden_reason_codes.get(assessment.claim_id)
        if forbidden is not None:
            got = {r.value for r in assessment.reason_codes}
            metrics.reason_code_accuracy.add(not (set(forbidden) & got))
        expected_blockers = expected.blockers.get(assessment.claim_id)
        if expected_blockers is not None:
            metrics.blocker_accuracy.add(
                sorted(b.value for b in assessment.blockers)
                == sorted(expected_blockers)
            )
        expected_unknown = expected.unknown_dimensions.get(assessment.claim_id)
        if expected_unknown is not None:
            metrics.unknown_state_preservation_accuracy.add(
                set(expected_unknown)
                <= {d.value for d in assessment.unknown_dimensions}
            )
        expected_limitations = expected.limitations.get(assessment.claim_id)
        if expected_limitations is not None:
            metrics.unknown_state_preservation_accuracy.add(
                set(expected_limitations)
                <= {limitation.value for limitation in assessment.limitations}
            )
        expected_ceiling = expected.content_scope_ceiling.get(assessment.claim_id)
        if expected_ceiling is not None:
            metrics.scope_ceiling_accuracy.add(
                (
                    assessment.content_scope_ceiling.value
                    if assessment.content_scope_ceiling
                    else "NONE"
                )
                == expected_ceiling
            )

        # Contradiction preservation: a claim whose input holds an eligible
        # direct contradiction must still show it, in a component or a group.
        contradicting_input = [
            spec
            for spec in case.alignments
            if spec.claim_id == assessment.claim_id
            and AlignmentRelation(spec.relation) in DIRECT_CONTRADICTION_RELATIONS
            and expected_contribution(case, spec)
            is EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION
        ]
        if contradicting_input:
            preserved = bool(assessment.contradicting_group_ids) or any(
                c.coverage
                in (
                    ComponentCoverage.CONTRADICTED,
                    ComponentCoverage.CONTESTED,
                    ComponentCoverage.PARTIAL_CONTRADICTION_ONLY,
                    ComponentCoverage.PARTIAL_MIXED,
                )
                for c in assessment.components
            )
            metrics.contradiction_preservation_accuracy.add(preserved)
            metrics.contradiction_silently_discarded_rate.record(not preserved)
            # And it must never have been averaged into a support posture.
            metrics.contradiction_silently_discarded_rate.record(
                assessment.outcome is SufficiencyOutcome.SUFFICIENT_SUPPORT
            )
        else:
            metrics.contradiction_preservation_accuracy.add(
                not assessment.contradicting_group_ids
                or bool(
                    [
                        spec
                        for spec in case.alignments
                        if spec.claim_id == assessment.claim_id
                        and AlignmentRelation(spec.relation)
                        in DIRECT_CONTRADICTION_RELATIONS
                    ]
                )
            )

        # Duplicate excerpts from one paper must not become two groups. The
        # eval re-derives how many distinct canonical identities the claim's
        # eligible evidence actually has, from the fixture's own identifiers,
        # and requires exactly that many groups -- no more, and no fewer.
        eligible_keys = {
            key_by_evidence_id.get(p.evidence_id)
            for p in run.weight_profiles
            if p.claim_id == assessment.claim_id and p.is_eligible
        }
        expected_identities = {
            identity
            for identity, keys in partition.items()
            if keys & {k for k in eligible_keys if k is not None}
        }
        eligible_groups = {
            p.independence_group_id
            for p in run.weight_profiles
            if p.claim_id == assessment.claim_id and p.is_eligible
        }
        metrics.duplicate_excerpt_independence_rate.record(
            len(eligible_groups) != len(expected_identities)
        )

    # -- not-ready / incomplete handling ------------------------------------
    from src.schemas.claim_alignment import ClaimAlignmentStatus

    alignment_status = ClaimAlignmentStatus(case.alignment_status)
    metrics.incomplete_alignment_treated_as_complete_rate.record(
        alignment_status is ClaimAlignmentStatus.PARTIAL
        and (run.alignment_universe_complete or bool(run.assessments))
    )
    metrics.pair_limit_blocked_treated_as_complete_rate.record(
        alignment_status is ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED
        and (run.alignment_universe_complete or bool(run.assessments))
    )
    if expected.status is not None:
        metrics.run_status_accuracy.add(run.status.value == expected.status)
    if not case.direct_mode:
        expected_not_ready = readiness(build_alignment_run(case))
        metrics.run_status_accuracy.add(
            (run.status is expected_not_ready)
            if expected_not_ready is not None
            else run.status
            in (
                ClaimSufficiencyStatus.COMPLETED,
                ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS,
            )
        )

    # -- contribution class inventory ---------------------------------------
    if expected.contributions:
        metrics.contribution_classification_accuracy.add(
            sorted({p.contribution.value for p in run.weight_profiles})
            == sorted(set(expected.contributions))
        )

    # -- determinism / rerun -------------------------------------------------
    # Group ids are uuid5 over (run, canonical identity), so an independent
    # second execution must reproduce them exactly.
    from src.schemas.claim_sufficiency import independence_group_id

    metrics.deterministic_rerun_accuracy.add(
        all(
            g.independence_group_id
            == independence_group_id(outcome.run_id, g.canonical_identity)
            for g in run.independence_groups
        )
    )
    if outcome.rerun_run is not None:
        second = outcome.rerun_run
        metrics.deterministic_rerun_accuracy.add(
            sorted(g.canonical_identity for g in second.independence_groups)
            == sorted(g.canonical_identity for g in run.independence_groups)
            and sorted((a.claim_id, a.outcome.value) for a in second.assessments)
            == sorted((a.claim_id, a.outcome.value) for a in run.assessments)
        )
        metrics.incompatible_duplicate_assessment_rate.record(
            len({a.claim_id for a in second.assessments}) != len(second.assessments)
        )

    # No profile may reference the unresolved sentinel group while contributing.
    for profile in run.weight_profiles:
        metrics.untraceable_evidence_contribution_rate.record(
            profile.independence_group_id == UNRESOLVED_GROUP_ID and profile.is_eligible
        )


def run_sufficiency_dataset(
    dataset: SufficiencyGoldDataset,
) -> tuple[ClaimSufficiencyMetrics, list[SufficiencyCaseResult]]:
    metrics = ClaimSufficiencyMetrics()
    results: list[SufficiencyCaseResult] = []
    for case in dataset.cases:
        outcome = run_sufficiency_case(case)
        results.append(outcome)
        score_sufficiency_case(case, outcome, metrics)
    return metrics, results


def score_by_language(
    dataset: SufficiencyGoldDataset, results: list[SufficiencyCaseResult]
) -> dict[str, ClaimSufficiencyMetrics]:
    """Per-language metrics, so an aggregate pass cannot hide a failing subgroup."""
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, ClaimSufficiencyMetrics] = {}
    for outcome in results:
        case = by_id.get(outcome.case_id)
        if case is None:
            continue
        score_sufficiency_case(
            case, outcome, grouped.setdefault(case.language, ClaimSufficiencyMetrics())
        )
    return grouped


@dataclass
class SufficiencyGateResult:
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


def evaluate_sufficiency_gate(
    metrics: ClaimSufficiencyMetrics,
) -> SufficiencyGateResult:
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return SufficiencyGateResult(
        passed=metrics.safety_clean
        and metrics.thresholds_met
        and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        thresholds_met=metrics.thresholds_met,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )


__all__ = [
    "CLAIM_VERDICT_FIELDS",
    "SufficiencyCaseResult",
    "SufficiencyGateResult",
    "evaluate_sufficiency_gate",
    "expected_contribution",
    "expected_independence_partition",
    "run_sufficiency_case",
    "run_sufficiency_dataset",
    "score_by_language",
    "score_sufficiency_case",
]
