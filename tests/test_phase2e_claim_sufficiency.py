"""Phase 2E claim sufficiency and evidence weighting.

What these tests are actually guarding, in order:

* **Nothing collapses into a scalar.** The contracts carry no numeric weight,
  and the structural scan in the eval would catch one reappearing.
* **Quantity is not independence.** Excerpts, provider observations and
  duplicate source records collapse onto canonical identity; only distinct
  canonical identities count as corroboration.
* **Unknown is not favorable.** ``UNKNOWN`` retraction and publication status
  survive into the assessment instead of being read as clean and reviewed.
* **Retracted is not normal evidence.** It stays visible and disqualified.
* **Canonical state is untouched.** A populated ``ProjectState``, the Phase 2C
  evidence and the Phase 2D alignments are byte-identical after a real graph run.
* **The gates can fire.** The negative controls at the end deliberately break
  each rule and assert the guard catches it -- a guard nothing can trip is not
  a guard.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.evals.claim_sufficiency.dataset import (
    build_academic_result,
    build_alignment_run,
    build_alignments,
    build_claims,
    build_evidence,
    build_extraction_run,
    build_logical_sources,
    gold_run_id,
    load_sufficiency_dataset,
)
from src.evals.claim_sufficiency.dataset import SufficiencyGoldCase
from src.evals.claim_sufficiency.metrics import (
    RELEASE_BLOCKING_SUFFICIENCY_METRICS,
    REQUIRED_PERFECT_METRICS,
)
from src.evals.claim_sufficiency.runner import (
    evaluate_sufficiency_gate,
    run_sufficiency_case,
    run_sufficiency_dataset,
    score_by_language,
    score_sufficiency_case,
)
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2e_graph import (
    FORBIDDEN_NODES,
    PHASE_2E_NODE_SEQUENCE,
    build_phase2e_claim_sufficiency_graph,
)
from src.graph.registry import NodeId
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.research.coverage import initial_branch_coverage
from src.research.inputs import project_state_fingerprint
from src.research.planner import PLANNER_VERSION
from src.research.sufficiency.identity import (
    build_independence_groups,
    publication_status,
    retraction_status,
)
from src.research.sufficiency.policy import decide_outcome, material_component_keys
from src.research.sufficiency.profiles import classify_contribution
from src.schemas.academic import AcademicSourceType
from src.schemas.claim import ClaimOrigin, ClaimRecord, ClaimStatus, ClaimType
from src.schemas.claim_alignment import AlignmentRelation, ClaimAlignmentStatus
from src.schemas.claim_sufficiency import (
    CLAIM_SUFFICIENCY_CONTRACT_VERSION,
    EVIDENCE_WEIGHT_PROFILE_VERSION,
    SUFFICIENCY_AGGREGATOR_VERSION,
    SUFFICIENCY_POLICY_VERSION,
    ClaimSufficiencyAssessment,
    ClaimSufficiencyRun,
    ClaimSufficiencyStatus,
    ComponentCoverage,
    ContentScopeLimitation,
    CorroborationLevel,
    EvidenceContributionClass,
    EvidenceWeightProfile,
    IndependenceGroup,
    PublicationStatus,
    RetractionStatus,
    SufficiencyOutcome,
    TraceabilityStatus,
    independence_group_id,
)
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions
from src.schemas.source import PeerReviewStatus

# ===========================================================================
# Fixtures
# ===========================================================================

EN_CLAIM = "The detector reaches 94% accuracy on the public benchmark."
ANCHOR = "94% accuracy"
SUP = "The evaluated system achieved 94% accuracy on the held-out benchmark split."
SUP2 = "An independent replication measured 94% accuracy on the same benchmark."
CON = "Accuracy never exceeded 71% in any configuration that we evaluated."


def _case(**overrides) -> SufficiencyGoldCase:
    payload = {
        "case_id": "CS-900",
        "language": "en",
        "categories": ["unit"],
        "claims": [{"claim_id": "C-901", "claim": EN_CLAIM}],
        "sources": [{"key": "s1", "doi": "10.1000/unit1"}],
        "evidence": [{"key": "e1", "source": "s1", "excerpt": SUP}],
        "alignments": [
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            }
        ],
        "expected": {},
    }
    payload.update(overrides)
    return SufficiencyGoldCase.model_validate(payload)


@pytest.fixture(scope="module")
def dataset():
    return load_sufficiency_dataset()


@pytest.fixture(scope="module")
def graded(dataset):
    """The whole Gold suite, run once. Every dataset assertion reads from this."""
    metrics, results = run_sufficiency_dataset(dataset)
    return metrics, results


@pytest.fixture
def app():
    return build_phase2e_claim_sufficiency_graph(build_checkpointer())


def _populated_project(claims: list[ClaimRecord]) -> ProjectState:
    """A populated ProjectState including a CONTRADICTED claim with counter-evidence.

    Section 25 is explicit that immutability must be proven against populated
    state: a diff of two empty lists proves nothing.
    """
    from tests.fixtures.projects import fixture_b_complete_engineering_project

    project = fixture_b_complete_engineering_project()
    contradicted = ClaimRecord(
        claim_id="C-401",
        claim="The correlator generalizes to pipes above DN200.",
        claim_type=ClaimType.FEASIBILITY,
        origin=ClaimOrigin.STUDENT,
        status=ClaimStatus.CONTRADICTED,
        counter_evidence_ids=["E-004"],
        confidence=0.15,
    )
    return project.model_copy(
        update={"claims": [*project.claims, *claims, contradicted]}
    )


def _run(case: SufficiencyGoldCase, project: ProjectState) -> ResearchRun:
    run = ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(
        academic_research=build_academic_result(case),
        evidence_extraction=build_extraction_run(case),
        claim_evidence_alignment=build_alignment_run(case),
    )


def _invoke(app, project: ProjectState, run: ResearchRun) -> EvaluationGraphState:
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    return coerce_graph_state(
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


def _sufficiency(app, case: SufficiencyGoldCase) -> ClaimSufficiencyRun:
    project = _populated_project(build_claims(case))
    state = _invoke(app, project, _run(case, project))
    return state.active_research_run.claim_sufficiency


# ===========================================================================
# 1. Contracts: no opaque scalar, no claim verdict
# ===========================================================================


def test_no_contract_carries_a_numeric_evidence_weight() -> None:
    """ADR-015: sufficiency must never collapse into one opaque number.

    Checked structurally rather than by review: any float or int field on these
    contracts would be a candidate scalar, and the assertion names the offender.
    """
    for model in (
        EvidenceWeightProfile,
        ClaimSufficiencyAssessment,
        IndependenceGroup,
    ):
        numeric = [
            name
            for name, info in model.model_fields.items()
            if info.annotation in (float, int, float | None, int | None)
        ]
        allowed = {"anchor_start", "anchor_end", "publication_year"}
        assert not (set(numeric) - allowed), (
            f"{model.__name__} gained a numeric field {sorted(set(numeric) - allowed)}; "
            "a scalar weight belongs to a later scoring phase"
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        "claim_status",
        "status",
        "confidence",
        "evidence_ids",
        "counter_evidence_ids",
        "score",
        "trust_gate",
        "evaluation_status",
    ],
)
def test_no_contract_can_express_a_claim_verdict(forbidden: str) -> None:
    """Phase 2E could not mutate claim truth even if a later edit tried.

    The field does not exist, which is a stronger guarantee than leaving one
    unset (ADR-014, ADR-015).
    """
    for model in (EvidenceWeightProfile, ClaimSufficiencyAssessment):
        assert forbidden not in model.model_fields


def test_extra_fields_are_refused_on_the_assessment() -> None:
    with pytest.raises(ValidationError):
        ClaimSufficiencyAssessment(
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            assessment_id=uuid4(),
            claim_id="C-901",
            outcome=SufficiencyOutcome.NO_DIRECT_EVIDENCE,
            evidence_weight=0.73,
        )


def test_versions_are_distinct_from_phase_2c_and_2d() -> None:
    """Section 28: Phase 2E must not reuse an upstream verifier's version."""
    from src.schemas.claim_alignment import (
        ALIGNMENT_VERIFIER_VERSION,
        CLAIM_ALIGNMENT_CONTRACT_VERSION,
    )
    from src.schemas.evidence_extraction import EVIDENCE_VERIFIER_VERSION

    mine = {
        CLAIM_SUFFICIENCY_CONTRACT_VERSION,
        SUFFICIENCY_POLICY_VERSION,
        EVIDENCE_WEIGHT_PROFILE_VERSION,
        SUFFICIENCY_AGGREGATOR_VERSION,
    }
    theirs = {
        CLAIM_ALIGNMENT_CONTRACT_VERSION,
        ALIGNMENT_VERIFIER_VERSION,
        EVIDENCE_VERIFIER_VERSION,
    }
    assert len(mine) == 4
    assert not (mine & theirs)


# ===========================================================================
# 2. Graph shape
# ===========================================================================


def test_graph_compiles_without_any_model_provider(app) -> None:
    """Phase 2E is deterministic: no provider key, no prompt, no model."""
    assert app is not None
    assert NodeId.CLASSIFY_ALIGNMENT_CANDIDATES not in PHASE_2E_NODE_SEQUENCE


def test_graph_wires_no_later_phase_node(app) -> None:
    wired = set(app.get_graph().nodes) - {"__start__", "__end__"}
    assert not (wired & {node.value for node in FORBIDDEN_NODES})
    assert wired == {node.value for node in PHASE_2E_NODE_SEQUENCE}


def test_sufficiency_run_has_no_model_or_prompt_field() -> None:
    """Section 16: there is nothing for a model to decide here, so there is no
    seam for one to be injected through later without a review."""
    fields = set(ClaimSufficiencyRun.model_fields)
    assert not (
        fields
        & {"model_name", "provider_name", "classifier_version", "prompt_version"}
    )


# ===========================================================================
# 3. Independence and duplicate control
# ===========================================================================


def test_three_providers_of_one_paper_are_one_group() -> None:
    case = _case(
        sources=[
            {
                "key": "s1",
                "doi": "10.1000/unit1",
                "providers": ["CONSENSUS", "OPENALEX", "SEMANTIC_SCHOLAR"],
            }
        ]
    )
    groups, index = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    assert len(groups) == 1
    assert groups[0].quality.provider_observation_count == 3
    assert len(index) == 1


def test_many_excerpts_of_one_paper_are_one_group() -> None:
    case = _case(
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s1", "excerpt": SUP2},
            {"key": "e3", "source": "s1", "excerpt": CON},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2", "e3")
        ],
    )
    groups, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    assert len(groups) == 1
    assert groups[0].excerpt_count == 3


def test_two_records_sharing_a_doi_are_one_group() -> None:
    case = _case(
        sources=[
            {"key": "s1", "doi": "10.1000/same"},
            {"key": "s2", "doi": "10.1000/same", "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": SUP2},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2")
        ],
    )
    groups, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    assert len(groups) == 1
    assert groups[0].canonical_identity == "DOI:10.1000/same"
    assert sorted(groups[0].source_ids) == sorted(groups[0].source_ids)
    assert len(groups[0].source_ids) == 2


def test_identical_titles_with_different_dois_stay_two_groups() -> None:
    """ADR-009: a title must never merge two canonical identities."""
    same = "Accuracy of embedded detectors on public benchmarks"
    case = _case(
        sources=[
            {"key": "s1", "doi": "10.1000/a", "title": same},
            {"key": "s2", "doi": "10.1000/b", "title": same, "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": SUP2},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2")
        ],
    )
    groups, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    assert len(groups) == 2


def test_group_ids_are_deterministic_across_executions() -> None:
    case = _case()
    first, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    second, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    assert [g.independence_group_id for g in first] == [
        g.independence_group_id for g in second
    ]
    assert first[0].independence_group_id == independence_group_id(
        gold_run_id(case), first[0].canonical_identity
    )


def test_group_ids_are_scoped_to_their_run() -> None:
    """Section 23: two runs cannot share a group, so groups cannot span runs."""
    assert independence_group_id(uuid4(), "DOI:10.1/x") != independence_group_id(
        uuid4(), "DOI:10.1/x"
    )


def test_a_minted_group_id_is_refused() -> None:
    case = _case()
    groups, _ = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    with pytest.raises(ValidationError, match="must be derived"):
        groups[0].model_copy(update={"independence_group_id": uuid4()}).model_validate(
            {**dict(groups[0]), "independence_group_id": uuid4()}
        )


# ===========================================================================
# 4. Source quality: only what metadata states
# ===========================================================================


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        (AcademicSourceType.PREPRINT, PublicationStatus.PREPRINT),
        (
            AcademicSourceType.JOURNAL_ARTICLE,
            PublicationStatus.PEER_REVIEWED_OR_FORMALLY_PUBLISHED,
        ),
        (AcademicSourceType.THESIS, PublicationStatus.OTHER_PUBLISHED),
        (AcademicSourceType.UNKNOWN, PublicationStatus.UNKNOWN),
    ],
)
def test_publication_status_reads_only_the_publication_form(
    source_type: AcademicSourceType, expected: PublicationStatus
) -> None:
    assert publication_status(source_type, PeerReviewStatus.UNKNOWN) is expected


def test_unknown_retraction_is_not_not_retracted() -> None:
    """Section 19: silence means silence, never a clean bill of health."""
    assert retraction_status(None, None) is RetractionStatus.UNKNOWN


def test_either_retraction_signal_marks_retracted() -> None:
    """A missed retraction is the expensive error, so the strictest signal wins."""
    case = _case(sources=[{"key": "s1", "doi": "10.1000/r", "is_retracted": True}])
    source = build_logical_sources(case)[0]
    evidence = build_evidence(case)[0]
    assert retraction_status(source, evidence) is RetractionStatus.RETRACTED
    assert retraction_status(source, None) is RetractionStatus.RETRACTED


# ===========================================================================
# 5. Contribution classification
# ===========================================================================


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (AlignmentRelation.SUPPORTS, EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT),
        (
            AlignmentRelation.PARTIALLY_SUPPORTS,
            EvidenceContributionClass.ELIGIBLE_PARTIAL_SUPPORT,
        ),
        (
            AlignmentRelation.CONTRADICTS,
            EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION,
        ),
        (
            AlignmentRelation.PARTIALLY_CONTRADICTS,
            EvidenceContributionClass.ELIGIBLE_PARTIAL_CONTRADICTION,
        ),
        (AlignmentRelation.MIXED, EvidenceContributionClass.ELIGIBLE_MIXED),
        (AlignmentRelation.CONTEXT_ONLY, EvidenceContributionClass.CONTEXT_ONLY),
        (
            AlignmentRelation.INSUFFICIENT,
            EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT,
        ),
        (AlignmentRelation.NOT_RELEVANT, EvidenceContributionClass.NOT_RELEVANT),
    ],
)
def test_relation_maps_to_its_contribution_unchanged(
    relation: AlignmentRelation, expected: EvidenceContributionClass
) -> None:
    """Section 10: the Phase 2D relation is used as given and never rewritten."""
    alignment = build_alignments(
        _case(
            alignments=[
                {
                    "claim_id": "C-901",
                    "evidence": "e1",
                    "relation": relation.value,
                    "components": (
                        []
                        if relation is AlignmentRelation.NOT_RELEVANT
                        else _components_for(relation)
                    ),
                }
            ]
        )
    )[0]
    assert (
        classify_contribution(
            alignment, TraceabilityStatus.TRACEABLE, RetractionStatus.NOT_RETRACTED
        )
        is expected
    )


def _components_for(relation: AlignmentRelation) -> list[dict]:
    """The component shape Phase 2D's own consistency rule requires."""
    return {
        AlignmentRelation.SUPPORTS: [{"text": ANCHOR, "judgment": "SUPPORTS"}],
        AlignmentRelation.CONTRADICTS: [{"text": ANCHOR, "judgment": "CONTRADICTS"}],
        AlignmentRelation.PARTIALLY_SUPPORTS: [
            {"text": ANCHOR, "judgment": "SUPPORTS"},
            {"text": "public benchmark", "judgment": "CONTEXTUAL"},
        ],
        AlignmentRelation.PARTIALLY_CONTRADICTS: [
            {"text": ANCHOR, "judgment": "CONTRADICTS"},
            {"text": "public benchmark", "judgment": "UNRESOLVED"},
        ],
        AlignmentRelation.MIXED: [
            {"text": ANCHOR, "judgment": "SUPPORTS"},
            {"text": "public benchmark", "judgment": "CONTRADICTS"},
        ],
        AlignmentRelation.CONTEXT_ONLY: [{"text": ANCHOR, "judgment": "CONTEXTUAL"}],
        AlignmentRelation.INSUFFICIENT: [{"text": ANCHOR, "judgment": "UNRESOLVED"}],
    }[relation]


def test_retraction_outranks_a_supporting_relation() -> None:
    alignment = build_alignments(_case())[0]
    assert (
        classify_contribution(
            alignment, TraceabilityStatus.TRACEABLE, RetractionStatus.RETRACTED
        )
        is EvidenceContributionClass.DISQUALIFIED_RETRACTED
    )


def test_traceability_outranks_retraction() -> None:
    """Evidence we cannot trace is not evidence whose retraction status means
    anything, so the traceability verdict is reported."""
    alignment = build_alignments(_case())[0]
    assert (
        classify_contribution(
            alignment,
            TraceabilityStatus.EVIDENCE_NOT_IN_RUN,
            RetractionStatus.RETRACTED,
        )
        is EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
    )


def test_a_retracted_profile_cannot_carry_a_contributing_class() -> None:
    with pytest.raises(ValidationError, match="retracted evidence cannot"):
        EvidenceWeightProfile(
            profile_id=uuid4(),
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            claim_id="C-901",
            evidence_id=uuid4(),
            alignment_id=uuid4(),
            source_id="SRC-00000000-0000-5000-8000-000000000001",
            independence_group_id=uuid4(),
            canonical_identity="DOI:10.1/x",
            relation=AlignmentRelation.SUPPORTS,
            contribution=EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT,
            retraction_status=RetractionStatus.RETRACTED,
        )


def test_an_untraceable_profile_cannot_contribute() -> None:
    with pytest.raises(ValidationError, match="untraceable evidence cannot"):
        EvidenceWeightProfile(
            profile_id=uuid4(),
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            claim_id="C-901",
            evidence_id=uuid4(),
            alignment_id=uuid4(),
            source_id="SRC-00000000-0000-5000-8000-000000000001",
            independence_group_id=uuid4(),
            canonical_identity="DOI:10.1/x",
            relation=AlignmentRelation.SUPPORTS,
            contribution=EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT,
            traceability=TraceabilityStatus.SOURCE_NOT_RESOLVABLE,
        )


# ===========================================================================
# 6. Policy outcomes through the real graph
# ===========================================================================


def test_one_supporting_source_is_sufficient_and_says_so(app) -> None:
    run = _sufficiency(app, _case())
    assessment = run.assessment_for("C-901")
    assert assessment.outcome is SufficiencyOutcome.SUFFICIENT_SUPPORT
    assert assessment.supporting_group_count == 1
    assert assessment.components[0].corroboration is CorroborationLevel.SINGLE_GROUP
    assert "SINGLE_INDEPENDENT_SOURCE_ONLY" in [
        r.value for r in assessment.reason_codes
    ]


def test_support_and_contradiction_stay_contested(app) -> None:
    """Section 12: do not average the conflict away."""
    case = _case(
        sources=[
            {"key": "s1", "doi": "10.1000/a"},
            {"key": "s2", "doi": "10.1000/b", "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": CON},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-901",
                "evidence": "e2",
                "relation": "CONTRADICTS",
                "components": [{"text": ANCHOR, "judgment": "CONTRADICTS"}],
            },
        ],
    )
    assessment = _sufficiency(app, case).assessment_for("C-901")
    assert assessment.outcome is SufficiencyOutcome.CONTESTED
    assert assessment.supporting_group_count == 1
    assert assessment.contradicting_group_count == 1
    assert assessment.components[0].coverage is ComponentCoverage.CONTESTED


def test_context_only_is_never_weak_support(app) -> None:
    case = _case(
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "CONTEXT_ONLY",
                "components": [{"text": ANCHOR, "judgment": "CONTEXTUAL"}],
            }
        ]
    )
    assessment = _sufficiency(app, case).assessment_for("C-901")
    assert assessment.outcome is SufficiencyOutcome.NO_DIRECT_EVIDENCE
    assert assessment.supporting_group_count == 0
    assert assessment.content_scope_ceiling is None


def test_retracted_support_blocks_rather_than_disappearing(app) -> None:
    """Section 20: visible, disqualified, never silently deleted."""
    case = _case(sources=[{"key": "s1", "doi": "10.1000/r", "is_retracted": True}])
    run = _sufficiency(app, case)
    assessment = run.assessment_for("C-901")
    assert assessment.outcome is SufficiencyOutcome.BLOCKED_SOURCE_QUALITY
    assert [b.value for b in assessment.blockers] == [
        "ALL_DIRECT_EVIDENCE_RETRACTED"
    ]
    # The refused item is still on the record, with its reason.
    profile = run.profiles_for("C-901")[0]
    assert profile.contribution is EvidenceContributionClass.DISQUALIFIED_RETRACTED
    assert profile.relation is AlignmentRelation.SUPPORTS


def test_abstract_only_scope_is_preserved_not_upgraded(app) -> None:
    assessment = _sufficiency(app, _case()).assessment_for("C-901")
    assert assessment.content_scope_ceiling is ContentScopeLimitation.ABSTRACT_ONLY
    assert assessment.is_abstract_only


def test_a_compound_claim_needs_every_component(app) -> None:
    compound = "The detector reaches 94% accuracy and runs in 5 ms on embedded hardware."
    case = _case(
        claims=[{"claim_id": "C-901", "claim": compound}],
        sources=[
            {"key": "s1", "doi": "10.1000/a"},
            {"key": "s2", "doi": "10.1000/b", "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": SUP2},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-901",
                "evidence": "e2",
                "relation": "INSUFFICIENT",
                "components": [{"text": "runs in 5 ms", "judgment": "UNRESOLVED"}],
            },
        ],
    )
    assessment = _sufficiency(app, case).assessment_for("C-901")
    assert assessment.outcome is SufficiencyOutcome.PARTIALLY_SUFFICIENT
    assert [c.coverage for c in assessment.components] == [
        ComponentCoverage.SUPPORTED,
        ComponentCoverage.UNRESOLVED_RELEVANT,
    ]


def test_sufficient_support_is_refused_without_full_coverage() -> None:
    """The contract itself forbids the overclaim, not only the policy."""
    group = uuid4()
    with pytest.raises(ValidationError, match="requires every material component"):
        ClaimSufficiencyAssessment(
            assessment_id=uuid4(),
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            claim_id="C-901",
            outcome=SufficiencyOutcome.SUFFICIENT_SUPPORT,
            components=[],
            independence_group_ids=[group],
            supporting_group_ids=[group],
        )


def test_contested_is_refused_from_one_side_only() -> None:
    group = uuid4()
    with pytest.raises(ValidationError, match="CONTESTED requires both"):
        ClaimSufficiencyAssessment(
            assessment_id=uuid4(),
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            claim_id="C-901",
            outcome=SufficiencyOutcome.CONTESTED,
            independence_group_ids=[group],
            supporting_group_ids=[group],
        )


def test_no_direct_evidence_cannot_carry_direct_groups() -> None:
    group = uuid4()
    with pytest.raises(ValidationError, match="NO_DIRECT_EVIDENCE cannot carry"):
        ClaimSufficiencyAssessment(
            assessment_id=uuid4(),
            research_run_id=uuid4(),
            sufficiency_run_id=uuid4(),
            claim_id="C-901",
            outcome=SufficiencyOutcome.NO_DIRECT_EVIDENCE,
            independence_group_ids=[group],
            supporting_group_ids=[group],
        )


def test_an_incomplete_universe_cannot_carry_sufficiency() -> None:
    """Section 27, enforced by the run contract as well as by the graph."""
    case = _case()
    project = _populated_project(build_claims(case))
    run_id = gold_run_id(case)
    from src.research.sufficiency.pipeline import assess_claims

    sufficiency_run_id = uuid4()
    groups, profiles, assessments = assess_claims(
        build_claims(case),
        build_alignment_run(case),
        build_evidence(case),
        build_logical_sources(case),
        research_run_id=run_id,
        sufficiency_run_id=sufficiency_run_id,
    )
    assert assessments[0].outcome is SufficiencyOutcome.SUFFICIENT_SUPPORT
    with pytest.raises(ValidationError, match="incomplete alignment universe"):
        ClaimSufficiencyRun(
            sufficiency_run_id=sufficiency_run_id,
            research_run_id=run_id,
            status=ClaimSufficiencyStatus.COMPLETED,
            alignment_universe_complete=False,
            independence_groups=groups,
            weight_profiles=profiles,
            assessments=assessments,
            completed_at="2026-09-01T10:00:00+00:00",
        )
    assert project is not None


# ===========================================================================
# 7. Not-ready behavior
# ===========================================================================


@pytest.mark.parametrize(
    ("alignment_status", "expected"),
    [
        ("PARTIAL", ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE),
        (
            "BLOCKED_PAIR_LIMIT_EXCEEDED",
            ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE,
        ),
        ("RUNNING", ClaimSufficiencyStatus.NOT_READY),
        ("FAILED", ClaimSufficiencyStatus.NOT_READY),
        ("NOT_READY", ClaimSufficiencyStatus.NOT_READY),
        ("NO_ALIGNABLE_CLAIMS", ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS),
        ("NO_ALIGNABLE_EVIDENCE", ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS),
    ],
)
def test_each_not_ready_cause_keeps_its_own_status(
    app, alignment_status: str, expected: ClaimSufficiencyStatus
) -> None:
    """A pipeline gap must never read as an evidence finding (section 27)."""
    case = _case(alignment_status=alignment_status, alignments=[])
    run = _sufficiency(app, case)
    assert run.status is expected
    assert run.assessments == []
    assert run.independence_groups == []


def test_an_incomplete_alignment_run_is_never_marked_complete(app) -> None:
    run = _sufficiency(app, _case(alignment_status="PARTIAL"))
    assert run.alignment_universe_complete is False
    assert not run.assessments


# ===========================================================================
# 8. Immutability against populated state
# ===========================================================================


def test_populated_project_state_survives_the_graph_untouched(app) -> None:
    case = _case()
    project = _populated_project(build_claims(case))
    before, before_hash = project.model_dump(), project_state_fingerprint(project)

    state = _invoke(app, project, _run(case, project))

    assert state.project.model_dump() == before
    assert project_state_fingerprint(state.project) == before_hash
    assert state.active_research_run.claim_sufficiency.assessments


def test_phase2c_evidence_and_phase2d_alignments_survive_untouched(app) -> None:
    case = _case()
    project = _populated_project(build_claims(case))
    run = _run(case, project)
    evidence_before = [
        e.model_dump(mode="json") for e in run.evidence_extraction.verified_evidence
    ]
    alignments_before = [
        a.model_dump(mode="json") for a in run.claim_evidence_alignment.alignments
    ]

    finished = _invoke(app, project, run).active_research_run

    assert [
        e.model_dump(mode="json") for e in finished.evidence_extraction.verified_evidence
    ] == evidence_before
    assert [
        a.model_dump(mode="json") for a in finished.claim_evidence_alignment.alignments
    ] == alignments_before
    assert finished.claim_evidence_alignment.status is ClaimAlignmentStatus.COMPLETED


def test_the_research_run_is_left_open_for_later_branches(app) -> None:
    case = _case()
    project = _populated_project(build_claims(case))
    finished = _invoke(app, project, _run(case, project)).active_research_run
    assert not finished.is_terminal
    assert finished.claim_sufficiency.is_terminal
    assert finished.claim_sufficiency_ran


def test_a_mutation_of_populated_state_would_be_detected(app) -> None:
    """Negative control for the immutability check itself.

    If the guard could not see a change, every immutability metric above would
    be vacuous.
    """
    case = _case()
    project = _populated_project(build_claims(case))
    before = project_state_fingerprint(project)
    tampered = project.model_copy(
        update={
            "claims": [
                project.claims[0].model_copy(update={"confidence": 0.99}),
                *project.claims[1:],
            ]
        }
    )
    assert project_state_fingerprint(tampered) != before


# ===========================================================================
# 9. Idempotency
# ===========================================================================


def test_reinvoking_a_finished_graph_does_not_duplicate_assessments(app) -> None:
    case = _case()
    project = _populated_project(build_claims(case))
    run = _run(case, project)
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    first = coerce_graph_state(
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
    before = first.active_research_run.claim_sufficiency
    second = coerce_graph_state(app.invoke(None, config))
    after = second.active_research_run.claim_sufficiency

    assert after.sufficiency_run_id == before.sufficiency_run_id
    assert len(after.assessments) == len(before.assessments) == 1
    assert [a.assessment_id for a in after.assessments] == [
        a.assessment_id for a in before.assessments
    ]


def test_two_independent_passes_agree(app) -> None:
    case = _case()
    outcomes = []
    for _ in range(2):
        project = _populated_project(build_claims(case))
        fresh = build_phase2e_claim_sufficiency_graph(build_checkpointer())
        run = _invoke(fresh, project, _run(case, project)).active_research_run
        sufficiency = run.claim_sufficiency
        outcomes.append(
            (
                sorted(g.canonical_identity for g in sufficiency.independence_groups),
                sorted((a.claim_id, a.outcome.value) for a in sufficiency.assessments),
                sufficiency.coverage.duplicate_evidence_collapsed,
            )
        )
    assert outcomes[0] == outcomes[1]


def test_a_claim_cannot_carry_two_assessments_in_one_run() -> None:
    case = _case()
    from src.research.sufficiency.pipeline import assess_claims

    sufficiency_run_id = uuid4()
    groups, profiles, assessments = assess_claims(
        build_claims(case),
        build_alignment_run(case),
        build_evidence(case),
        build_logical_sources(case),
        research_run_id=gold_run_id(case),
        sufficiency_run_id=sufficiency_run_id,
    )
    with pytest.raises(ValidationError, match="two sufficiency assessments"):
        ClaimSufficiencyRun(
            sufficiency_run_id=sufficiency_run_id,
            research_run_id=gold_run_id(case),
            status=ClaimSufficiencyStatus.COMPLETED,
            independence_groups=groups,
            weight_profiles=profiles,
            assessments=[*assessments, *assessments],
            completed_at="2026-09-01T10:00:00+00:00",
        )


def test_a_pair_cannot_carry_two_weight_profiles() -> None:
    case = _case()
    from src.research.sufficiency.pipeline import assess_claims

    sufficiency_run_id = uuid4()
    groups, profiles, _ = assess_claims(
        build_claims(case),
        build_alignment_run(case),
        build_evidence(case),
        build_logical_sources(case),
        research_run_id=gold_run_id(case),
        sufficiency_run_id=sufficiency_run_id,
    )
    with pytest.raises(ValidationError, match="two weight profiles"):
        ClaimSufficiencyRun(
            sufficiency_run_id=sufficiency_run_id,
            research_run_id=gold_run_id(case),
            status=ClaimSufficiencyStatus.COMPLETED,
            independence_groups=groups,
            weight_profiles=[
                *profiles,
                *[p.model_copy(update={"profile_id": uuid4()}) for p in profiles],
            ],
            completed_at="2026-09-01T10:00:00+00:00",
        )


# ===========================================================================
# 10. Cross-claim isolation
# ===========================================================================


def test_one_evidence_item_can_differ_per_claim(app) -> None:
    """Section 22: semantic contribution is claim-specific."""
    case = _case(
        claims=[
            {"claim_id": "C-901", "claim": EN_CLAIM},
            {"claim_id": "C-902", "claim": EN_CLAIM},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-902",
                "evidence": "e1",
                "relation": "NOT_RELEVANT",
                "components": [],
            },
        ],
    )
    run = _sufficiency(app, case)
    assert run.assessment_for("C-901").outcome is SufficiencyOutcome.SUFFICIENT_SUPPORT
    assert run.assessment_for("C-902").outcome is SufficiencyOutcome.NO_DIRECT_EVIDENCE
    # One logical source; the same group id under two different postures.
    assert len(run.independence_groups) == 1


# ===========================================================================
# 11. Gold dataset invariants
# ===========================================================================


def test_gold_dataset_meets_its_coverage_minimums(dataset) -> None:
    counts = dataset.language_counts
    assert len(dataset.cases) >= 120
    assert counts.get("ar", 0) >= 24
    assert counts.get("mixed", 0) >= 16
    assert counts.get("en", 0) >= 1


def test_gold_dataset_covers_every_sufficiency_outcome(dataset) -> None:
    covered = set(dataset.outcome_counts)
    assert covered == {o.value for o in SufficiencyOutcome}


@pytest.mark.parametrize(
    "category",
    [
        "one_direct_supporting_source",
        "two_independent_supporting_sources",
        "same_paper_two_providers",
        "multiple_excerpts_same_paper",
        "doi_duplicate_collapse",
        "strong_identifier_duplicate_collapse",
        "title_similarity_not_collapsed",
        "direct_contradiction_one_source",
        "multiple_contradictory_sources",
        "support_and_contradiction_contested",
        "compound_claim_full_coverage",
        "compound_claim_partial_coverage",
        "partial_support_only",
        "partial_contradiction_only",
        "mixed_relation",
        "context_only_evidence",
        "insufficient_relationship_only",
        "not_relevant_evidence_only",
        "no_direct_evidence",
        "retracted_supporting_paper",
        "retracted_contradicting_paper",
        "preprint_only_support",
        "preprint_plus_published_support",
        "unknown_publication_status",
        "unknown_retraction_status",
        "abstract_only_limitation",
        "untraceable_evidence_rejection",
        "cross_run_evidence_rejection",
        "cross_run_alignment_rejection",
        "incomplete_phase2d_run",
        "pair_limit_blocked",
        "checkpoint_resume",
        "rerun_idempotency",
        "duplicate_assessment_prevention",
        "project_state_immutability",
        "phase2c_immutability",
        "phase2d_immutability",
        "arabic_scientific_evidence",
        "mixed_arabic_english_technical_evidence",
        "same_evidence_different_claims",
        "contradiction_one_component",
        "support_one_component_missing_other",
        "all_components_one_source",
        "all_components_across_independent",
        "source_with_multiple_provider_observations",
        "missing_doi_same_identity",
        "unknown_not_favorable",
        "reason_code_correctness",
    ],
)
def test_gold_dataset_covers_every_required_category(dataset, category: str) -> None:
    """Section 29's 48 required adversarial/behaviour categories, each named."""
    assert dataset.category_counts.get(category, 0) >= 1


def test_gold_cases_anchor_only_verbatim_claim_text(dataset) -> None:
    """A Gold case cannot encode an anchor that is not in its claim."""
    for case in dataset.cases:
        text = {c.claim_id: c.claim for c in case.claims}
        for alignment in case.alignments:
            for component in alignment.components:
                assert component.text in text[alignment.claim_id]


# ===========================================================================
# 12. The suite gate
# ===========================================================================


def test_the_gold_suite_passes_its_gate(graded) -> None:
    metrics, _ = graded
    gate = evaluate_sufficiency_gate(metrics)
    assert gate.cases_errored == 0, "no Gold case may error"
    assert gate.violations == dict.fromkeys(RELEASE_BLOCKING_SUFFICIENCY_METRICS, 0)
    assert gate.passed, gate.summary()


@pytest.mark.parametrize("name", REQUIRED_PERFECT_METRICS)
def test_every_required_quality_metric_is_measured_and_perfect(graded, name) -> None:
    metrics, _ = graded
    counts = getattr(metrics, name)
    assert counts.total > 0, f"{name} was never exercised"
    assert counts.rate == 1.0, f"{name} = {counts.rate}"


@pytest.mark.parametrize("language", ["en", "ar", "mixed"])
def test_no_language_subgroup_hides_a_failure(dataset, graded, language) -> None:
    _, results = graded
    subgroups = score_by_language(dataset, results)
    subgroup = subgroups[language]
    assert subgroup.cases_evaluated > 0
    assert subgroup.safety_clean


def test_a_metric_with_no_denominator_reports_not_measured() -> None:
    """Section 19: an unexercised metric is None, never 0.0."""
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics, violation_rate

    fresh = ClaimSufficiencyMetrics()
    assert fresh.independence_grouping_accuracy.rate is None
    assert violation_rate(fresh.project_state_mutation_rate) is None
    assert not fresh.thresholds_met


# ===========================================================================
# 13. Negative controls -- each gate must be able to fire
# ===========================================================================


def test_negative_control_duplicate_group_is_caught() -> None:
    """If two groups shared a canonical identity, the grouping metric must fail."""
    case = _case(
        sources=[
            {"key": "s1", "doi": "10.1000/same"},
            {"key": "s2", "doi": "10.1000/same", "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": SUP2},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2")
        ],
        expected={"independence_groups": 2},
    )
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    metrics = ClaimSufficiencyMetrics()
    score_sufficiency_case(case, run_sufficiency_case(case), metrics)
    assert metrics.independence_grouping_accuracy.rate != 1.0


def test_negative_control_wrong_expected_outcome_is_caught() -> None:
    case = _case(expected={"outcomes": {"C-901": "NO_DIRECT_EVIDENCE"}})
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    metrics = ClaimSufficiencyMetrics()
    score_sufficiency_case(case, run_sufficiency_case(case), metrics)
    assert metrics.sufficiency_outcome_accuracy.rate != 1.0


def test_negative_control_a_retracted_contribution_trips_its_gate() -> None:
    """Hand-build the forbidden state the schema would reject, and confirm the
    eval's own gate -- not just the validator -- would see it."""
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    metrics = ClaimSufficiencyMetrics()
    metrics.retracted_evidence_corroboration_rate.record(True)
    assert not metrics.safety_clean
    assert evaluate_sufficiency_gate(metrics).passed is False


def test_negative_control_a_mutated_project_trips_its_gate() -> None:
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    for name in RELEASE_BLOCKING_SUFFICIENCY_METRICS:
        metrics = ClaimSufficiencyMetrics()
        getattr(metrics, name).record(True)
        assert not metrics.safety_clean, f"{name} cannot fire"
        assert not evaluate_sufficiency_gate(metrics).passed


def test_negative_control_an_errored_case_fails_the_gate() -> None:
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    metrics = ClaimSufficiencyMetrics()
    metrics.cases_errored = 1
    assert not evaluate_sufficiency_gate(metrics).passed


def test_negative_control_an_unmeasured_required_metric_fails_the_gate() -> None:
    """Section 31: 1.0 over an empty denominator is not a pass."""
    from src.evals.claim_sufficiency.metrics import ClaimSufficiencyMetrics

    metrics = ClaimSufficiencyMetrics()
    for name in REQUIRED_PERFECT_METRICS[:-1]:
        getattr(metrics, name).add(True)
    assert not metrics.thresholds_met


def test_negative_control_decide_outcome_sees_a_contradiction() -> None:
    """The policy function itself must not be able to return SUFFICIENT_SUPPORT
    while an eligible direct contradiction is present."""
    compound = "The detector reaches 94% accuracy and runs in 5 ms on embedded hardware."
    case = _case(
        claims=[{"claim_id": "C-901", "claim": compound}],
        sources=[
            {"key": "s1", "doi": "10.1000/a"},
            {"key": "s2", "doi": "10.1000/b", "providers": ["OPENALEX"]},
        ],
        evidence=[
            {"key": "e1", "source": "s1", "excerpt": SUP},
            {"key": "e2", "source": "s2", "excerpt": CON},
        ],
        alignments=[
            {
                "claim_id": "C-901",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": ANCHOR, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-901",
                "evidence": "e2",
                "relation": "CONTRADICTS",
                "components": [{"text": ANCHOR, "judgment": "CONTRADICTS"}],
            },
        ],
    )
    from src.research.sufficiency.pipeline import assess_claim

    groups, index = build_independence_groups(
        gold_run_id(case), build_evidence(case), build_logical_sources(case)
    )
    profiles_run = uuid4()
    assessment, profiles = assess_claim(
        build_claims(case)[0],
        build_alignments(case),
        {e.evidence_id: e for e in build_evidence(case)},
        {g.independence_group_id: g for g in groups},
        index,
        research_run_id=gold_run_id(case),
        sufficiency_run_id=profiles_run,
        alignment_run_id=None,
    )
    outcome, _, _ = decide_outcome(assessment.components, profiles)
    assert outcome is SufficiencyOutcome.CONTESTED
    assert material_component_keys(profiles)


def test_negative_control_unknown_is_not_silently_favorable(app) -> None:
    """An unknown retraction status must be reported, not quietly cleared."""
    run = _sufficiency(app, _case())
    profile = run.profiles_for("C-901")[0]
    assert profile.retraction_status is RetractionStatus.UNKNOWN
    assert "RETRACTION_STATUS_UNKNOWN" in [
        limitation.value for limitation in profile.limitations
    ]
    assert "UNKNOWN_RETRACTION_STATUS" in [
        r.value for r in run.assessment_for("C-901").reason_codes
    ]
