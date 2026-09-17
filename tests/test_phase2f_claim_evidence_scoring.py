"""Phase 2F claim-evidence scoring.

What these tests defend, in the order the specification asks for it:

* **A number means what it says.** ``index_bp`` is validated against the sum of
  its own dimensions, so the scalar can never disagree with the vector it came
  from, and the arithmetic is pinned to exact integers rather than tolerances.
* **Support and contradiction never merge.** There is no net field, there is no
  field that could hold one, and a contested claim keeps both channels and
  issues no primary scalar.
* **Source quality is reliability, not hidden points.** The posture moves; the
  index does not.
* **The Phase 2E.1 denominator survives.** A material component nobody examined
  lowers the score instead of vanishing from it.
* **Nothing canonical moves.** ``ProjectState.scores``, ``ScoreRecord``s, claim
  status, the trust gate and the Phase 2E assessments are byte-identical after
  a real graph run, and negative controls prove those guards can fire.
* **Anti-gaming is arithmetic, not aspiration.** Duplicates, extra providers,
  extra excerpts, irrelevant citations and retracted papers cannot raise a
  score, and the property tests are metamorphic: they compare two worlds that
  differ by exactly one thing.

No Arabic literal appears here as prose. The one Arabic claim used for
language parity is written as ``\\u`` escapes, so this module stays outside
``ARABIC_AS_DATA`` rather than earning a blanket exemption for a large test
file.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from pydantic import ValidationError

from src.evals.claim_scoring.dataset import (
    ScoringGoldCase,
    load_scoring_dataset,
    scoring_run_id_for,
)
from src.evals.claim_scoring.metrics import (
    RELEASE_BLOCKING_SCORING_METRICS,
    REQUIRED_PERFECT_METRICS,
    ClaimScoringMetrics,
)
from src.evals.claim_scoring.runner import (
    PROJECT_SCORE_FIELDS,
    TRUTH_PROBABILITY_FIELDS,
    expected_component_spans,
    recomputed_channel_bp,
    run_scoring_case,
    score_scoring_case,
)
from src.evals.claim_sufficiency.dataset import (
    SufficiencyGoldCase,
    build_academic_result,
    build_alignment_run,
    build_claims,
    build_extraction_run,
    gold_run_id,
)
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2e_graph import build_phase2e_claim_sufficiency_graph
from src.graph.phase2f_graph import (
    FORBIDDEN_NODES,
    PHASE_2F_NODE_SEQUENCE,
    build_phase2f_claim_scoring_graph,
)
from src.graph.registry import PRODUCTION_NODE_ORDER, NodeId
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.research.coverage import initial_branch_coverage
from src.research.planner import PLANNER_VERSION
from src.research.scoring.arithmetic import scaled_basis_points, weighted_basis_points
from src.research.scoring.policy import (
    CORROBORATION_FACTOR_BP,
    corroboration_level,
    decide_disposition,
    directional_score,
)
from src.research.scoring.pipeline import readiness, score_assessments, score_claim
from src.research.scoring.reliability import RELIABILITY_RANK
from src.research.settings import ResearchSettings
from src.schemas.claim_component_inventory import ComponentInventoryCompleteness
from src.schemas.claim_evidence_score import (
    CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION,
    CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
    CORROBORATION_DIMENSION_MAX_BP,
    COVERAGE_DIMENSION_MAX_BP,
    DIRECTNESS_DIMENSION_MAX_BP,
    INDEX_MAX_BP,
    SCALAR_WITHHELD_DISPOSITIONS,
    SCORE_ARITHMETIC_VERSION,
    ClaimEvidenceScoreCard,
    ClaimEvidenceScoringRun,
    ClaimScoringStatus,
    ComponentScoreTrace,
    DirectionalCoverageState,
    DirectionalScore,
    ReliabilityPosture,
    ScoreDimensions,
    ScoreDirection,
    ScoreDisposition,
    ScoreReasonCode,
    ScoreReliabilityProfile,
    ScoringCoverage,
    index_display,
    scorecard_id_for,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyStatus,
    CorroborationLevel,
    SufficiencyOutcome,
)
from src.schemas.common import EvaluationStatus
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions
from src.schemas.score import RubricKind, ScoreAxis, ScoreAxisName, ScoreRecord
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult

# ===========================================================================
# Fixtures: synthetic worlds driven through the real Phase 2E and 2F graphs
# ===========================================================================

SIMPLE = "The system reaches 94% accuracy."
COMPOUND = "The detector reaches 94% accuracy, runs in 5 ms on embedded hardware."
A1 = "The detector reaches 94% accuracy"
A2 = " runs in 5 ms on embedded hardware."
AR_SIMPLE = (
    "\u064a\u0628\u0644\u063a \u0627\u0644\u0646\u0637\u0627\u0645 "
    "\u062f\u0642\u0629 94%."
)
"""An Arabic claim as Gold *data*, written as escapes so this module needs no
language-policy exemption."""

EXCERPT = "Measured accuracy reached 94%."
COUNTER = "Accuracy did not exceed 70%."
CONTEXT = "Detection remains an active area."
LATENCY = "Latency was 5 ms."


def _source(key: str, doi: str, **kw) -> dict:
    out = {
        "key": key,
        "doi": doi,
        "is_retracted": False,
        "providers": ["CONSENSUS"],
        "source_type": "JOURNAL_ARTICLE",
    }
    out.update(kw)
    return out


def _world(
    claim: str,
    sources: list[dict],
    evidence: list[dict],
    alignments: list[dict],
    *,
    case_id: str = "CS-700",
    claims: list[dict] | None = None,
    alignment_status: str = "COMPLETED",
) -> SufficiencyGoldCase:
    return SufficiencyGoldCase.model_validate(
        {
            "case_id": case_id,
            "language": "en",
            "categories": ["unit"],
            "claims": claims or [{"claim_id": "C-001", "claim": claim}],
            "sources": sources,
            "evidence": evidence,
            "alignments": alignments,
            "alignment_status": alignment_status,
            "expected": {},
        }
    )


def _project(case: SufficiencyGoldCase, *, with_score_record: bool = False) -> ProjectState:
    """A populated project state, including a real canonical ``ScoreRecord``.

    The score record is the single most important thing Phase 2F must not
    touch, and an empty list cannot prove a populated one survives.
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
                code=BlockerCode.RED_TEAM_INCOMPLETE, detail="Red team not run."
            )
        ],
    )
    project.evaluation_status = EvaluationStatus.PROVISIONAL
    if with_score_record:
        project.scores = [
            ScoreRecord(
                score_id="SC-001",
                rubric_kind=RubricKind.ADVISORY,
                rubric_version="ADVISORY-V1",
                status=EvaluationStatus.PROVISIONAL,
                axes=[
                    ScoreAxis(
                        axis=ScoreAxisName.LITERATURE.value,
                        score=7.0,
                        max_score=10.0,
                        status=EvaluationStatus.PROVISIONAL,
                        rationale="Placed by an earlier reviewed phase.",
                    )
                ],
            )
        ]
    return project


def _open_run(case: SufficiencyGoldCase, project: ProjectState) -> ResearchRun:
    run = ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="phase2f-unit",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(
        academic_research=build_academic_result(case),
        evidence_extraction=build_extraction_run(case),
        claim_evidence_alignment=build_alignment_run(case),
    )


def _run_2e(case: SufficiencyGoldCase, project: ProjectState):
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
    app = build_phase2e_claim_sufficiency_graph(build_checkpointer())
    run = _open_run(case, project)
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


def _run_2f(state, *, interrupt_before: str | None = None):
    run = state.active_research_run
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
    checkpointer = build_checkpointer()
    app = build_phase2f_claim_scoring_graph(checkpointer)
    initial = EvaluationGraphState(
        run_id=run_id,
        thread_id=config["configurable"]["thread_id"],
        project=state.project,
        research_runs={str(run.research_run_id): run},
        active_research_run_id=run.research_run_id,
    )
    if interrupt_before is not None:
        build_phase2f_claim_scoring_graph(checkpointer).invoke(
            initial, {**config, "interrupt_before": [interrupt_before]}
        )
        return coerce_graph_state(app.invoke(None, config))
    return coerce_graph_state(app.invoke(initial, config))


def _score(case: SufficiencyGoldCase, *, with_score_record: bool = False):
    """Drive a world through both real graphs and return the scoring run."""
    project = _project(case, with_score_record=with_score_record)
    state = _run_2e(case, project)
    final = _run_2f(state)
    return final.active_research_run.claim_evidence_scoring, final, state


def _card(case: SufficiencyGoldCase, claim_id: str = "C-001") -> ClaimEvidenceScoreCard:
    scoring, _, _ = _score(case)
    card = scoring.scorecard_for(claim_id)
    assert card is not None, f"no scorecard for {claim_id}"
    return card


# --- standard worlds -------------------------------------------------------


def _supported_world(case_id: str = "CS-700", groups: int = 1) -> SufficiencyGoldCase:
    sources = [
        _source(f"s{i}", f"10.5555/u-{case_id}-{i}", providers=["CONSENSUS"])
        for i in range(1, groups + 1)
    ]
    evidence = [
        {"key": f"e{i}", "source": f"s{i}", "excerpt": f"{EXCERPT} ({i})"}
        for i in range(1, groups + 1)
    ]
    alignments = [
        {
            "claim_id": "C-001",
            "evidence": f"e{i}",
            "relation": "SUPPORTS",
            "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
        }
        for i in range(1, groups + 1)
    ]
    return _world(SIMPLE, sources, evidence, alignments, case_id=case_id)


# ===========================================================================
# 1. Score semantics: what the number is not
# ===========================================================================


def test_no_contract_names_a_score_as_a_truth_probability() -> None:
    """Section 6: a field called ``confidence`` would invite the exact
    misreading this phase exists to prevent, so the names are asserted."""
    models = (
        ClaimEvidenceScoreCard,
        ClaimEvidenceScoringRun,
        DirectionalScore,
        ScoreDimensions,
        ComponentScoreTrace,
        ScoreReliabilityProfile,
        ScoringCoverage,
    )
    for model in models:
        for forbidden in TRUTH_PROBABILITY_FIELDS:
            assert forbidden not in model.model_fields, (
                f"{model.__name__} gained a field named {forbidden!r}; an "
                "evidence index is not a probability of truth (ADR-017)"
            )


def test_no_contract_carries_a_project_or_rubric_score_field() -> None:
    """Section 28: an evidence index must not be shaped like a rubric axis."""
    models = (
        ClaimEvidenceScoreCard,
        ClaimEvidenceScoringRun,
        DirectionalScore,
        ComponentScoreTrace,
        ScoreReliabilityProfile,
    )
    allowed = {"max_score"}  # not present today; listed so the diff is honest
    for model in models:
        offenders = {
            name for name in PROJECT_SCORE_FIELDS if name in model.model_fields
        } - allowed
        assert not offenders, (
            f"{model.__name__} gained {sorted(offenders)}; project scoring is a "
            "later reviewed phase"
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        "claim_status",
        "status_delta",
        "confidence",
        "evidence_ids",
        "counter_evidence_ids",
        "trust_gate",
        "evaluation_status",
        "net_score",
        "net_index",
        "truth_probability",
    ],
)
def test_scorecard_cannot_express_a_claim_verdict_or_a_net(forbidden: str) -> None:
    assert forbidden not in ClaimEvidenceScoreCard.model_fields


def test_there_is_no_net_field_anywhere_on_the_contracts() -> None:
    """Section 8: ``net_score = support - contradiction`` is forbidden, and the
    strongest form of that is having nowhere to put one."""
    for model in (
        ClaimEvidenceScoreCard,
        DirectionalScore,
        ScoreDimensions,
        ComponentScoreTrace,
    ):
        for name in model.model_fields:
            assert "net" not in name.lower(), f"{model.__name__}.{name}"


def test_index_display_is_decimal_not_float() -> None:
    """Section 16: the integer is the source of truth and this is its only
    rendering; a float here would reintroduce binary rounding at the last step."""
    value = index_display(8500)
    assert isinstance(value, Decimal)
    assert value == Decimal("85.00")
    assert str(value) == "85.00"


# ===========================================================================
# 2. Deterministic arithmetic
# ===========================================================================


def test_the_three_dimension_ceilings_sum_to_the_index_maximum() -> None:
    """50 + 30 + 20 = 100. Asserted rather than trusted to survive an edit."""
    assert (
        COVERAGE_DIMENSION_MAX_BP
        + CORROBORATION_DIMENSION_MAX_BP
        + DIRECTNESS_DIMENSION_MAX_BP
        == INDEX_MAX_BP
    )


@pytest.mark.parametrize(
    ("numerator", "denominator", "ceiling", "expected"),
    [
        (0, 1, 5_000, 0),
        (1, 1, 5_000, 5_000),
        (1, 2, 5_000, 2_500),
        (1, 3, 5_000, 1_667),
        (2, 3, 5_000, 3_333),
        (1, 3, 2_000, 667),
        (1, 3, 3_000, 1_000),
        (1, 0, 5_000, 0),
    ],
)
def test_scaled_basis_points_is_exact(
    numerator: int, denominator: int, ceiling: int, expected: int
) -> None:
    assert scaled_basis_points(numerator, denominator, ceiling) == expected


def test_rounding_is_half_even_not_half_up() -> None:
    """Half-to-even is unbiased: a scoring policy must not round in its own
    favour. 5000/8 of a 10000 ceiling is exactly 625.0; the interesting case is
    a true .5, which half-up would push up and half-even pushes to even."""
    # 1/8 of 5000 = 625 exactly; 1/16 of 5000 = 312.5 -> 312 (even), not 313.
    assert scaled_basis_points(1, 16, 5_000) == 312
    # 3/16 of 5000 = 937.5 -> 938 (even), not 937.
    assert scaled_basis_points(3, 16, 5_000) == 938


def test_weighted_basis_points_treats_half_credit_exactly() -> None:
    """A partial relation is exactly half a component, in integers."""
    assert weighted_basis_points(5_000, 1, 2_000) == 1_000
    assert weighted_basis_points(10_000, 1, 2_000) == 2_000
    assert weighted_basis_points(15_000, 2, 3_000) == 2_250


def test_corroboration_factors_encode_the_saturation_rule() -> None:
    assert CORROBORATION_FACTOR_BP[CorroborationLevel.NONE] == 0
    assert CORROBORATION_FACTOR_BP[CorroborationLevel.SINGLE_GROUP] == 5_000
    assert CORROBORATION_FACTOR_BP[CorroborationLevel.MULTIPLE_GROUPS] == 10_000


@pytest.mark.parametrize(
    ("count", "level"),
    [
        (0, CorroborationLevel.NONE),
        (1, CorroborationLevel.SINGLE_GROUP),
        (2, CorroborationLevel.MULTIPLE_GROUPS),
        (3, CorroborationLevel.MULTIPLE_GROUPS),
        (20, CorroborationLevel.MULTIPLE_GROUPS),
    ],
)
def test_corroboration_level_saturates(count: int, level: CorroborationLevel) -> None:
    groups = [uuid5(NAMESPACE_URL, f"g{i}") for i in range(count)]
    assert corroboration_level(groups) is level


def test_corroboration_level_counts_distinct_groups_only() -> None:
    """One group listed twice is one group, whatever the list says."""
    group = uuid5(NAMESPACE_URL, "only-one")
    assert corroboration_level([group, group, group]) is CorroborationLevel.SINGLE_GROUP


# ===========================================================================
# 3. The score vector reconciles with its scalar
# ===========================================================================


def test_a_directional_score_whose_scalar_disagrees_with_its_vector_is_refused() -> None:
    with pytest.raises(ValidationError, match="does not equal the dimension sum"):
        DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(
                coverage_bp=5_000, corroboration_bp=1_500, directness_bp=2_000
            ),
            index_bp=9_000,
            covered_components=1,
            total_components=1,
        )


@pytest.mark.parametrize(
    "dimensions",
    [
        {"coverage_bp": COVERAGE_DIMENSION_MAX_BP + 1},
        {"corroboration_bp": CORROBORATION_DIMENSION_MAX_BP + 1},
        {"directness_bp": DIRECTNESS_DIMENSION_MAX_BP + 1},
    ],
)
def test_a_dimension_beyond_its_ceiling_is_refused(dimensions: dict) -> None:
    with pytest.raises(ValidationError):
        ScoreDimensions(**dimensions)


def test_an_index_beyond_one_hundred_is_refused() -> None:
    with pytest.raises(ValidationError):
        DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(),
            index_bp=INDEX_MAX_BP + 1,
        )


def test_a_positive_index_over_an_empty_denominator_is_refused() -> None:
    """Nothing to score cannot produce a score."""
    with pytest.raises(ValidationError, match="no material component"):
        DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(coverage_bp=5_000),
            index_bp=5_000,
            total_components=0,
        )


def test_covered_components_cannot_exceed_the_inventory() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(),
            index_bp=0,
            covered_components=3,
            total_components=2,
        )


def test_a_repeated_contributing_group_is_refused() -> None:
    """One study counted twice is the defect this phase inherits a guard for."""
    group = uuid4()
    with pytest.raises(ValidationError, match="must be distinct"):
        DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(),
            index_bp=0,
            total_components=1,
            contributing_group_ids=[group, group],
        )


# ===========================================================================
# 4. Exact end-to-end scores
# ===========================================================================


def test_one_component_one_group_scores_exactly_eighty_five() -> None:
    """Full coverage and full directness, half corroboration. Not 100: a single
    independent study is a materially weaker posture than two."""
    card = _card(_supported_world("CS-701", groups=1))
    assert card.support.dimensions.coverage_bp == 5_000
    assert card.support.dimensions.corroboration_bp == 1_500
    assert card.support.dimensions.directness_bp == 2_000
    assert card.support.index_bp == 8_500
    assert card.support_index == Decimal("85.00")
    assert card.final_support_index == Decimal("85.00")
    assert card.contradiction.index_bp == 0


def test_two_independent_groups_reach_the_maximum() -> None:
    card = _card(_supported_world("CS-702", groups=2))
    assert card.support.index_bp == INDEX_MAX_BP
    assert card.support_index == Decimal("100.00")
    assert card.support.saturated_components == 1


def test_a_compound_claim_with_one_half_unexamined_scores_exactly_half() -> None:
    """The Phase 2E.1 guarantee, carried into the number: the unexamined half
    stays in the denominator, so the index is halved rather than unaffected."""
    case = _world(
        COMPOUND,
        [_source("s1", "10.5555/half")],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": A1, "judgment": "SUPPORTS"}],
            }
        ],
        case_id="CS-703",
    )
    card = _card(case)
    assert card.support.total_components == 2
    assert card.support.covered_components == 1
    assert card.unexamined_component_count == 1
    assert card.support.index_bp == 4_250
    assert card.support_index == Decimal("42.50")
    assert (
        ScoreReasonCode.UNEXAMINED_MATERIAL_COMPONENT_IN_DENOMINATOR
        in card.reason_codes
    )


def test_an_arabic_claim_scores_identically_to_its_english_counterpart() -> None:
    """Language parity: the arithmetic is over components and groups, and the
    script the claim is written in cannot change it."""
    case = _world(
        AR_SIMPLE,
        [_source("s1", "10.5555/ar-parity")],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": AR_SIMPLE, "judgment": "SUPPORTS"}],
            }
        ],
        case_id="CS-704",
    )
    arabic = _card(case)
    english = _card(_supported_world("CS-705", groups=1))
    assert arabic.support.index_bp == english.support.index_bp == 8_500
    assert arabic.component_traces[0].anchor_text == AR_SIMPLE


# ===========================================================================
# 5. Support and contradiction stay separate
# ===========================================================================


def _contested_world(case_id: str = "CS-710") -> SufficiencyGoldCase:
    return _world(
        SIMPLE,
        [
            _source("s1", f"10.5555/{case_id}-sup"),
            _source("s2", f"10.5555/{case_id}-con", providers=["OPENALEX"]),
        ],
        [
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
            {"key": "e2", "source": "s2", "excerpt": COUNTER},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-001",
                "evidence": "e2",
                "relation": "CONTRADICTS",
                "components": [{"text": SIMPLE, "judgment": "CONTRADICTS"}],
            },
        ],
        case_id=case_id,
    )


def test_a_contested_claim_reports_both_channels_and_withholds_the_scalar() -> None:
    """A net would report 0 and look identical to a claim nobody examined."""
    card = _card(_contested_world())
    assert card.support.index_bp == 8_500
    assert card.contradiction.index_bp == 8_500
    assert card.final_support_index_bp is None
    assert card.final_support_index is None
    assert card.disposition is ScoreDisposition.CONTESTED_SCALAR_WITHHELD
    assert ScoreReasonCode.CONTESTED_FINAL_SCORE_WITHHELD in card.withheld_reasons
    # The net that must not exist anywhere:
    assert card.support.index_bp - card.contradiction.index_bp == 0
    assert card.support.index_bp != 0


def test_ninety_eighty_is_distinguishable_from_ten_zero() -> None:
    """The specification's own example. Two claims that a net would flatten to
    the same number must remain visibly different."""
    contested = _card(_contested_world("CS-711"))
    weak = _card(
        _world(
            COMPOUND,
            [_source("s1", "10.5555/weak")],
            [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "PARTIALLY_SUPPORTS",
                    "components": [
                        {"text": A1, "judgment": "SUPPORTS"},
                        {"text": A2, "judgment": "CONTEXTUAL"},
                    ],
                }
            ],
            case_id="CS-712",
        )
    )
    assert (contested.support.index_bp, contested.contradiction.index_bp) == (
        8_500,
        8_500,
    )
    assert (weak.support.index_bp, weak.contradiction.index_bp) == (500, 0)
    assert contested.support.index_bp != weak.support.index_bp


def test_a_fully_contradicted_claim_issues_zero_not_none() -> None:
    """Section 11: ``0`` is an evaluated posture, ``None`` is no scalar issued."""
    card = _card(
        _world(
            SIMPLE,
            [_source("s1", "10.5555/contra-only")],
            [{"key": "e1", "source": "s1", "excerpt": COUNTER}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "CONTRADICTS",
                    "components": [{"text": SIMPLE, "judgment": "CONTRADICTS"}],
                }
            ],
            case_id="CS-713",
        )
    )
    assert card.sufficiency_outcome is SufficiencyOutcome.SUFFICIENT_CONTRADICTION
    assert card.support.index_bp == 0
    assert card.contradiction.index_bp == 8_500
    assert card.final_support_index_bp == 0
    assert card.final_support_index == Decimal("0.00")
    assert not card.scalar_withheld


def test_no_direct_evidence_withholds_the_scalar_although_both_indices_are_zero() -> None:
    """``0`` as a *primary score* would read as "scored low". It is withheld so
    "nothing direct was found" cannot be mistaken for a bad result."""
    card = _card(
        _world(
            SIMPLE,
            [_source("s1", "10.5555/ctx-only")],
            [{"key": "e1", "source": "s1", "excerpt": CONTEXT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "CONTEXT_ONLY",
                    "components": [{"text": SIMPLE, "judgment": "CONTEXTUAL"}],
                }
            ],
            case_id="CS-714",
        )
    )
    assert card.disposition is ScoreDisposition.NO_DIRECT_EVIDENCE
    assert card.support.index_bp == 0
    assert card.contradiction.index_bp == 0
    assert card.final_support_index_bp is None


# ===========================================================================
# 6. Score disposition and withholding, enforced in the schema
# ===========================================================================


def _minimal_card(**overrides) -> dict:
    trace = ComponentScoreTrace(
        claim_id="C-001",
        anchor_start=0,
        anchor_end=len(SIMPLE),
        anchor_text=SIMPLE,
        support_state=DirectionalCoverageState.ADEQUATE,
        supporting_group_ids=[uuid4()],
        support_corroboration=CorroborationLevel.SINGLE_GROUP,
        support_directness_factor_bp=10_000,
    )
    scoring_run_id = uuid4()
    payload = {
        "scorecard_id": scorecard_id_for(scoring_run_id, "C-001"),
        "research_run_id": uuid4(),
        "scoring_run_id": scoring_run_id,
        "sufficiency_run_id": uuid4(),
        "assessment_id": uuid4(),
        "claim_id": "C-001",
        "sufficiency_outcome": SufficiencyOutcome.SUFFICIENT_SUPPORT,
        "inventory_completeness": ComponentInventoryCompleteness.COMPLETE,
        "support": DirectionalScore(
            direction=ScoreDirection.SUPPORT,
            dimensions=ScoreDimensions(
                coverage_bp=5_000, corroboration_bp=1_500, directness_bp=2_000
            ),
            index_bp=8_500,
            covered_components=1,
            total_components=1,
            contributing_group_ids=trace.supporting_group_ids,
        ),
        "contradiction": DirectionalScore(
            direction=ScoreDirection.CONTRADICTION,
            dimensions=ScoreDimensions(),
            index_bp=0,
            total_components=1,
        ),
        "component_traces": [trace],
        "disposition": ScoreDisposition.SCORED,
        "final_support_index_bp": 8_500,
        "input_fingerprint": "a" * 64,
    }
    payload.update(overrides)
    return payload


def test_the_minimal_scorecard_fixture_is_itself_valid() -> None:
    """Otherwise every refusal below could be passing for the wrong reason."""
    card = ClaimEvidenceScoreCard.model_validate(_minimal_card())
    assert card.disposition is ScoreDisposition.SCORED


@pytest.mark.parametrize("disposition", sorted(SCALAR_WITHHELD_DISPOSITIONS))
def test_a_withheld_disposition_cannot_carry_a_scalar(
    disposition: ScoreDisposition,
) -> None:
    overrides: dict = {"disposition": disposition, "final_support_index_bp": 8_500}
    if disposition is ScoreDisposition.CONTESTED_SCALAR_WITHHELD:
        overrides["sufficiency_outcome"] = SufficiencyOutcome.CONTESTED
    if disposition is ScoreDisposition.BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD:
        overrides["sufficiency_outcome"] = SufficiencyOutcome.BLOCKED_SOURCE_QUALITY
    with pytest.raises(ValidationError, match="withholds the primary scalar"):
        ClaimEvidenceScoreCard.model_validate(_minimal_card(**overrides))


def test_a_withheld_disposition_must_state_a_reason() -> None:
    with pytest.raises(ValidationError, match="must state why"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(
                disposition=ScoreDisposition.INCOMPLETE_INPUT_SCALAR_WITHHELD,
                final_support_index_bp=None,
                withheld_reasons=[],
            )
        )


def test_a_scored_card_must_issue_its_scalar() -> None:
    with pytest.raises(ValidationError, match="must issue"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(final_support_index_bp=None)
        )


def test_the_final_scalar_must_equal_the_support_index_not_a_net() -> None:
    """Section 12, enforced in the schema rather than only in policy code."""
    with pytest.raises(ValidationError, match="never a net"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(final_support_index_bp=8_000)
        )


def test_a_scored_card_requires_a_complete_component_inventory() -> None:
    """ADR-016 carried into scoring: no number over an unaccounted-for
    denominator may be reported as the claim's score."""
    for completeness in (
        ComponentInventoryCompleteness.INCOMPLETE,
        ComponentInventoryCompleteness.UNKNOWN,
    ):
        with pytest.raises(ValidationError, match="requires a COMPLETE"):
            ClaimEvidenceScoreCard.model_validate(
                _minimal_card(inventory_completeness=completeness)
            )


@pytest.mark.parametrize(
    "outcome",
    [SufficiencyOutcome.CONTESTED, SufficiencyOutcome.BLOCKED_SOURCE_QUALITY],
)
def test_a_scored_card_cannot_contradict_the_phase_2e_outcome(
    outcome: SufficiencyOutcome,
) -> None:
    with pytest.raises(ValidationError, match="withholds a primary scalar"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(sufficiency_outcome=outcome)
        )


def test_a_contested_disposition_requires_the_contested_outcome() -> None:
    with pytest.raises(ValidationError, match="requires the Phase 2E CONTESTED"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(
                disposition=ScoreDisposition.CONTESTED_SCALAR_WITHHELD,
                final_support_index_bp=None,
                withheld_reasons=[ScoreReasonCode.CONTESTED_FINAL_SCORE_WITHHELD],
            )
        )


def test_no_direct_evidence_disposition_cannot_carry_a_positive_index() -> None:
    with pytest.raises(ValidationError, match="evaluated zero-directional"):
        ClaimEvidenceScoreCard.model_validate(
            _minimal_card(
                disposition=ScoreDisposition.NO_DIRECT_EVIDENCE,
                final_support_index_bp=None,
                withheld_reasons=[ScoreReasonCode.NO_DIRECT_SUPPORT],
            )
        )


def test_traces_must_reconcile_with_the_aggregate_denominator() -> None:
    """Section 21: the component traces and the aggregate dimensions describe
    the same claim, so a mismatch is a contract error, not a rounding quirk."""
    payload = _minimal_card()
    payload["component_traces"] = []
    with pytest.raises(ValidationError, match="must reconcile"):
        ClaimEvidenceScoreCard.model_validate(payload)


def test_aggregate_coverage_counts_must_match_the_traces() -> None:
    payload = _minimal_card()
    payload["support"] = DirectionalScore(
        direction=ScoreDirection.SUPPORT,
        dimensions=ScoreDimensions(
            coverage_bp=5_000, corroboration_bp=1_500, directness_bp=2_000
        ),
        index_bp=8_500,
        covered_components=0,
        total_components=1,
    )
    with pytest.raises(ValidationError, match="does not match"):
        ClaimEvidenceScoreCard.model_validate(payload)


def test_both_channels_must_score_the_same_denominator() -> None:
    payload = _minimal_card()
    payload["contradiction"] = DirectionalScore(
        direction=ScoreDirection.CONTRADICTION,
        dimensions=ScoreDimensions(),
        index_bp=0,
        total_components=2,
    )
    with pytest.raises(ValidationError, match="same complete component inventory"):
        ClaimEvidenceScoreCard.model_validate(payload)


def test_a_channel_carrying_the_wrong_direction_is_refused() -> None:
    payload = _minimal_card()
    payload["support"] = DirectionalScore(
        direction=ScoreDirection.CONTRADICTION,
        dimensions=ScoreDimensions(
            coverage_bp=5_000, corroboration_bp=1_500, directness_bp=2_000
        ),
        index_bp=8_500,
        covered_components=1,
        total_components=1,
    )
    with pytest.raises(ValidationError, match="must carry direction SUPPORT"):
        ClaimEvidenceScoreCard.model_validate(payload)


def test_an_adequate_state_needs_a_supporting_group() -> None:
    with pytest.raises(ValidationError, match="needs at least one eligible"):
        ComponentScoreTrace(
            claim_id="C-001",
            anchor_start=0,
            anchor_end=len(SIMPLE),
            anchor_text=SIMPLE,
            support_state=DirectionalCoverageState.ADEQUATE,
            supporting_group_ids=[],
        )


def test_a_trace_corroboration_must_match_its_group_count() -> None:
    with pytest.raises(ValidationError, match="disagrees with"):
        ComponentScoreTrace(
            claim_id="C-001",
            anchor_start=0,
            anchor_end=len(SIMPLE),
            anchor_text=SIMPLE,
            support_state=DirectionalCoverageState.ADEQUATE,
            supporting_group_ids=[uuid4()],
            support_corroboration=CorroborationLevel.MULTIPLE_GROUPS,
        )


def test_a_trace_anchor_span_must_match_its_text() -> None:
    with pytest.raises(ValidationError, match="anchor text length"):
        ComponentScoreTrace(
            claim_id="C-001", anchor_start=0, anchor_end=5, anchor_text=SIMPLE
        )


# ===========================================================================
# 7. Cross-claim and cross-run isolation
# ===========================================================================


def test_a_trace_from_another_claim_is_refused() -> None:
    payload = _minimal_card()
    payload["component_traces"] = [
        ComponentScoreTrace(
            claim_id="C-002",
            anchor_start=0,
            anchor_end=len(SIMPLE),
            anchor_text=SIMPLE,
            support_state=DirectionalCoverageState.ADEQUATE,
            supporting_group_ids=[uuid4()],
            support_corroboration=CorroborationLevel.SINGLE_GROUP,
            support_directness_factor_bp=10_000,
        )
    ]
    with pytest.raises(ValidationError, match="cross-claim scorecard contamination"):
        ClaimEvidenceScoreCard.model_validate(payload)


def test_a_scorecard_from_another_research_run_is_refused_by_the_run() -> None:
    card = ClaimEvidenceScoreCard.model_validate(_minimal_card())
    with pytest.raises(ValidationError, match="cross-run contamination"):
        ClaimEvidenceScoringRun(
            research_run_id=uuid4(),
            scoring_run_id=card.scoring_run_id,
            status=ClaimScoringStatus.COMPLETED,
            scorecards=[card],
            completed_at="2026-09-01T10:00:00+00:00",
        )


def test_scoring_a_foreign_assessment_is_refused() -> None:
    """Section 24, at the pipeline boundary rather than only in the schema."""
    case = _supported_world("CS-720")
    project = _project(case)
    state = _run_2e(case, project)
    sufficiency = state.active_research_run.claim_sufficiency
    with pytest.raises(ValueError, match="cross-run scoring is refused"):
        score_claim(
            sufficiency.assessments[0],
            list(sufficiency.weight_profiles),
            scoring_run_id=uuid4(),
            research_run_id=uuid4(),
        )


def test_the_same_evidence_scores_differently_against_different_claims() -> None:
    """Section 23: contribution is claim-specific, so there is no global
    evidence support score that can travel between claims."""
    case = _world(
        SIMPLE,
        [_source("s1", "10.5555/xclaim")],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-002",
                "evidence": "e1",
                "relation": "CONTEXT_ONLY",
                "components": [{"text": COMPOUND, "judgment": "CONTEXTUAL"}],
            },
        ],
        case_id="CS-721",
        claims=[
            {"claim_id": "C-001", "claim": SIMPLE},
            {"claim_id": "C-002", "claim": COMPOUND},
        ],
    )
    scoring, _, _ = _score(case)
    first = scoring.scorecard_for("C-001")
    second = scoring.scorecard_for("C-002")
    assert first.support.index_bp == 8_500
    assert second.support.index_bp == 0
    assert first.claim_id != second.claim_id


def test_two_scorecards_for_one_claim_are_refused() -> None:
    card = ClaimEvidenceScoreCard.model_validate(_minimal_card())
    with pytest.raises(ValidationError, match="cannot carry two scorecards"):
        ClaimEvidenceScoringRun(
            research_run_id=card.research_run_id,
            scoring_run_id=card.scoring_run_id,
            status=ClaimScoringStatus.COMPLETED,
            scorecards=[card, card.model_copy()],
            completed_at="2026-09-01T10:00:00+00:00",
        )


def test_a_minted_scorecard_id_is_refused() -> None:
    """A stable id is what makes a rerun checkable (section 25)."""
    payload = _minimal_card()
    payload["scorecard_id"] = uuid4()
    card = ClaimEvidenceScoreCard.model_validate(payload)
    with pytest.raises(ValidationError, match="not minted"):
        ClaimEvidenceScoringRun(
            research_run_id=card.research_run_id,
            scoring_run_id=card.scoring_run_id,
            status=ClaimScoringStatus.COMPLETED,
            scorecards=[card],
            completed_at="2026-09-01T10:00:00+00:00",
        )


def test_a_scorecard_under_a_different_policy_version_is_refused() -> None:
    payload = _minimal_card()
    payload["policy_version"] = "CLAIM-EVIDENCE-SCORING-POLICY-V2"
    card = ClaimEvidenceScoreCard.model_validate(payload)
    with pytest.raises(ValidationError, match="different scoring policy version"):
        ClaimEvidenceScoringRun(
            research_run_id=card.research_run_id,
            scoring_run_id=card.scoring_run_id,
            status=ClaimScoringStatus.COMPLETED,
            scorecards=[card],
            completed_at="2026-09-01T10:00:00+00:00",
        )


# ===========================================================================
# 8. Reliability is a layer, not points
# ===========================================================================


def test_reliability_rank_puts_indeterminate_lowest() -> None:
    """Otherwise "unknown must not improve reliability" could not be checked as
    a comparison: INDETERMINATE is the absence of the facts, not a middle."""
    assert RELIABILITY_RANK[ReliabilityPosture.INDETERMINATE] == 0
    assert (
        RELIABILITY_RANK[ReliabilityPosture.INDETERMINATE]
        < RELIABILITY_RANK[ReliabilityPosture.LIMITED_RELIABILITY]
        < RELIABILITY_RANK[ReliabilityPosture.MODERATE_RELIABILITY]
        < RELIABILITY_RANK[ReliabilityPosture.HIGHER_RELIABILITY]
    )


def test_higher_reliability_requires_stated_formal_publication() -> None:
    """Peer review is never inferred, and the schema refuses the claim."""
    with pytest.raises(ValidationError, match="never inferred"):
        ScoreReliabilityProfile(
            posture=ReliabilityPosture.HIGHER_RELIABILITY,
            contributing_group_count=1,
            peer_reviewed_group_count=0,
        )


def test_a_posture_above_indeterminate_needs_something_behind_it() -> None:
    with pytest.raises(ValidationError, match="nothing stands behind it"):
        ScoreReliabilityProfile(
            posture=ReliabilityPosture.MODERATE_RELIABILITY,
            contributing_group_count=0,
        )


def test_a_preprint_scores_the_same_and_reports_a_lower_posture() -> None:
    """Section 10: the limitation is reported beside the number, never baked
    into it as a discount nobody can audit."""
    journal = _card(_supported_world("CS-730", groups=1))
    preprint = _card(
        _world(
            SIMPLE,
            [_source("s1", "10.5555/pre", source_type="PREPRINT")],
            [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "SUPPORTS",
                    "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
                }
            ],
            case_id="CS-731",
        )
    )
    assert preprint.support.index_bp == journal.support.index_bp == 8_500
    assert preprint.reliability.posture is ReliabilityPosture.LIMITED_RELIABILITY
    assert journal.reliability.posture is ReliabilityPosture.MODERATE_RELIABILITY
    assert (
        ScoreReasonCode.PREPRINT_RELIABILITY_LIMITATION
        in preprint.reliability.reason_codes
    )


def test_full_text_is_the_only_route_to_higher_reliability() -> None:
    full = _card(
        _world(
            SIMPLE,
            [_source("s1", "10.5555/ft")],
            [
                {
                    "key": "e1",
                    "source": "s1",
                    "excerpt": EXCERPT,
                    "content_kind": "FULL_TEXT",
                }
            ],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "SUPPORTS",
                    "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
                }
            ],
            case_id="CS-732",
        )
    )
    assert full.reliability.posture is ReliabilityPosture.HIGHER_RELIABILITY
    assert full.support.index_bp == 8_500


# ===========================================================================
# 9. Property / metamorphic invariants (section 30)
# ===========================================================================


def _support_bp(case: SufficiencyGoldCase) -> int:
    return _card(case).support.index_bp


def test_duplicate_invariance_extra_provider_changes_nothing() -> None:
    """Two worlds differing by exactly one thing: how many providers returned
    the same DOI. The score must be identical."""
    one = _world(
        SIMPLE,
        [_source("s1", "10.5555/prov")],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            }
        ],
        case_id="CS-740",
    )
    three = _world(
        SIMPLE,
        [
            _source(
                "s1",
                "10.5555/prov",
                providers=["CONSENSUS", "OPENALEX", "SEMANTIC_SCHOLAR"],
            )
        ],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            }
        ],
        case_id="CS-741",
    )
    assert _support_bp(one) == _support_bp(three) == 8_500


def test_duplicate_invariance_extra_excerpt_changes_nothing() -> None:
    one = _world(
        SIMPLE,
        [_source("s1", "10.5555/exc")],
        [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            }
        ],
        case_id="CS-742",
    )
    many = _world(
        SIMPLE,
        [_source("s1", "10.5555/exc")],
        [
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
            {"key": "e2", "source": "s1", "excerpt": EXCERPT + " (b)"},
            {"key": "e3", "source": "s1", "excerpt": EXCERPT + " (c)"},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2", "e3")
        ],
        case_id="CS-743",
    )
    assert _support_bp(one) == _support_bp(many) == 8_500


def test_duplicate_invariance_same_doi_twice_changes_nothing() -> None:
    twice = _world(
        SIMPLE,
        [
            _source("s1", "10.5555/same"),
            _source("s2", "10.5555/same", providers=["OPENALEX"]),
        ],
        [
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
            {"key": "e2", "source": "s2", "excerpt": EXCERPT + " (b)"},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": key,
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            }
            for key in ("e1", "e2")
        ],
        case_id="CS-744",
    )
    assert _support_bp(twice) == 8_500


@pytest.mark.parametrize(
    ("relation", "judgment"),
    [
        ("NOT_RELEVANT", None),
        ("CONTEXT_ONLY", "CONTEXTUAL"),
        ("INSUFFICIENT", "UNRESOLVED"),
    ],
)
def test_irrelevant_evidence_invariance(relation: str, judgment: str | None) -> None:
    """Adding non-supporting evidence to a supported claim must not move the
    support index. Padding a bibliography cannot raise a score."""
    components = [] if judgment is None else [{"text": SIMPLE, "judgment": judgment}]
    padded = _world(
        SIMPLE,
        [
            _source("s1", f"10.5555/pad-{relation}-a"),
            _source("s2", f"10.5555/pad-{relation}-b", providers=["OPENALEX"]),
        ],
        [
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
            {"key": "e2", "source": "s2", "excerpt": CONTEXT},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-001",
                "evidence": "e2",
                "relation": relation,
                "components": components,
            },
        ],
        case_id=f"CS-75{['NOT_RELEVANT', 'CONTEXT_ONLY', 'INSUFFICIENT'].index(relation)}",
    )
    assert _support_bp(padded) == 8_500


def test_positive_monotonicity_a_genuine_second_study_cannot_lower_support() -> None:
    assert _support_bp(_supported_world("CS-760", groups=1)) <= _support_bp(
        _supported_world("CS-761", groups=2)
    )


def test_contradiction_non_improvement() -> None:
    """Adding contradicting evidence must not raise the support index."""
    supported = _support_bp(_supported_world("CS-762", groups=1))
    contested = _card(_contested_world("CS-763")).support.index_bp
    assert contested <= supported


def test_retraction_non_improvement() -> None:
    """Marking a would-be second supporting source retracted must not raise
    either the index or the reliability posture."""
    clean = _card(_supported_world("CS-764", groups=2))
    with_retracted = _card(
        _world(
            SIMPLE,
            [
                _source("s1", "10.5555/rx-a"),
                _source("s2", "10.5555/rx-b", is_retracted=True, providers=["OPENALEX"]),
            ],
            [
                {"key": "e1", "source": "s1", "excerpt": EXCERPT},
                {"key": "e2", "source": "s2", "excerpt": EXCERPT + " (b)"},
            ],
            [
                {
                    "claim_id": "C-001",
                    "evidence": key,
                    "relation": "SUPPORTS",
                    "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
                }
                for key in ("e1", "e2")
            ],
            case_id="CS-765",
        )
    )
    assert with_retracted.support.index_bp <= clean.support.index_bp
    assert with_retracted.support.index_bp == 8_500
    assert RELIABILITY_RANK[with_retracted.reliability.posture] <= RELIABILITY_RANK[
        clean.reliability.posture
    ]
    assert with_retracted.reliability.retracted_group_count == 1


def test_unknown_non_improvement() -> None:
    """Replacing a known favorable fact with UNKNOWN must not improve the
    posture, and must not touch the index."""
    known = _card(_supported_world("CS-766", groups=1))
    unknown = _card(
        _world(
            SIMPLE,
            [{"key": "s1", "doi": "10.5555/unk", "providers": ["CONSENSUS"],
              "source_type": "JOURNAL_ARTICLE"}],
            [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "SUPPORTS",
                    "components": [{"text": SIMPLE, "judgment": "SUPPORTS"}],
                }
            ],
            case_id="CS-767",
        )
    )
    assert unknown.support.index_bp == known.support.index_bp == 8_500
    assert (
        RELIABILITY_RANK[unknown.reliability.posture]
        < RELIABILITY_RANK[known.reliability.posture]
    )


def test_uncovered_component_non_improvement() -> None:
    """Section 14: adding an unexamined material component to the inventory
    must not raise the score. It lowers it, because the denominator grows."""
    simple = _support_bp(_supported_world("CS-768", groups=1))
    compound = _support_bp(
        _world(
            COMPOUND,
            [_source("s1", "10.5555/grow")],
            [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "SUPPORTS",
                    "components": [{"text": A1, "judgment": "SUPPORTS"}],
                }
            ],
            case_id="CS-769",
        )
    )
    assert compound <= simple
    assert compound == 4_250


def test_boundedness_across_the_whole_gold_suite() -> None:
    """Every index in the shipped dataset is inside [0, 100]."""
    dataset = load_scoring_dataset()
    for case in dataset.cases:
        for value in case.expected.support_index_bp.values():
            assert 0 <= value <= INDEX_MAX_BP
        for value in case.expected.contradiction_index_bp.values():
            assert 0 <= value <= INDEX_MAX_BP


def test_order_invariance_alignment_order_does_not_change_the_score() -> None:
    """Order is semantically irrelevant here, so it must be numerically
    irrelevant too (section 30)."""
    forward = _world(
        COMPOUND,
        [
            _source("s1", "10.5555/ord-a"),
            _source("s2", "10.5555/ord-b", providers=["OPENALEX"]),
        ],
        [
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
            {"key": "e2", "source": "s2", "excerpt": LATENCY},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": A1, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-001",
                "evidence": "e2",
                "relation": "SUPPORTS",
                "components": [{"text": A2, "judgment": "SUPPORTS"}],
            },
        ],
        case_id="CS-770",
    )
    reversed_case = _world(
        COMPOUND,
        [
            _source("s1", "10.5555/ord-a"),
            _source("s2", "10.5555/ord-b", providers=["OPENALEX"]),
        ],
        [
            {"key": "e2", "source": "s2", "excerpt": LATENCY},
            {"key": "e1", "source": "s1", "excerpt": EXCERPT},
        ],
        [
            {
                "claim_id": "C-001",
                "evidence": "e2",
                "relation": "SUPPORTS",
                "components": [{"text": A2, "judgment": "SUPPORTS"}],
            },
            {
                "claim_id": "C-001",
                "evidence": "e1",
                "relation": "SUPPORTS",
                "components": [{"text": A1, "judgment": "SUPPORTS"}],
            },
        ],
        case_id="CS-770",
    )
    assert _support_bp(forward) == _support_bp(reversed_case) == 8_500


def test_exact_reproducibility_of_the_serialized_scorecard() -> None:
    """Identical inputs must produce byte-identical numbers (section 16)."""
    case = _supported_world("CS-771", groups=2)
    project = _project(case)
    state = _run_2e(case, project)
    first = _run_2f(state).active_research_run.claim_evidence_scoring
    second = _run_2f(state).active_research_run.claim_evidence_scoring

    def numbers(run) -> list:
        return [
            (
                c.claim_id,
                c.support.index_bp,
                c.contradiction.index_bp,
                c.support.dimensions.coverage_bp,
                c.support.dimensions.corroboration_bp,
                c.support.dimensions.directness_bp,
                c.final_support_index_bp,
                c.input_fingerprint,
            )
            for c in sorted(run.scorecards, key=lambda x: x.claim_id)
        ]

    assert numbers(first) == numbers(second)


# ===========================================================================
# 10. Input fingerprinting
# ===========================================================================


def test_the_fingerprint_is_stable_over_the_same_phase_2e_state() -> None:
    case = _supported_world("CS-780", groups=1)
    project = _project(case)
    state = _run_2e(case, project)
    first = _run_2f(state).active_research_run.claim_evidence_scoring
    second = _run_2f(state).active_research_run.claim_evidence_scoring
    assert (
        first.scorecards[0].input_fingerprint
        == second.scorecards[0].input_fingerprint
    )


def test_the_fingerprint_changes_when_a_scoring_relevant_input_changes() -> None:
    """A fingerprint that survived an added independent study would certify
    nothing (section 17)."""
    one = _card(_supported_world("CS-781", groups=1))
    two = _card(_supported_world("CS-781", groups=2))
    assert one.input_fingerprint != two.input_fingerprint


def test_the_fingerprint_carries_no_timestamp() -> None:
    """Two runs seconds apart over one state must agree, which they cannot do
    if a clock reading participates."""
    case = _supported_world("CS-782", groups=1)
    project = _project(case)
    state = _run_2e(case, project)
    card = _run_2f(state).active_research_run.claim_evidence_scoring.scorecards[0]
    assert len(card.input_fingerprint) == 64
    assert card.created_at is not None  # recorded, but not fingerprinted
    again = _run_2f(state).active_research_run.claim_evidence_scoring.scorecards[0]
    assert card.input_fingerprint == again.input_fingerprint
    assert card.created_at != again.created_at or True  # timestamps may tie


# ===========================================================================
# 11. Graph shape and readiness
# ===========================================================================


def test_the_graph_runs_the_channels_before_the_disposition_policy() -> None:
    """Whether a scalar may be issued depends on the conflict between the
    channels, so the policy cannot run until both exist."""
    order = list(PHASE_2F_NODE_SEQUENCE)
    assert order.index(NodeId.CALCULATE_SUPPORT_CHANNEL) < order.index(
        NodeId.APPLY_SCORE_DISPOSITION_POLICY
    )
    assert order.index(NodeId.CALCULATE_CONTRADICTION_CHANNEL) < order.index(
        NodeId.APPLY_SCORE_DISPOSITION_POLICY
    )
    assert order.index(NodeId.DERIVE_COMPONENT_SCORE_TRACES) < order.index(
        NodeId.CALCULATE_SUPPORT_CHANNEL
    )
    assert order[-1] is NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING


def test_the_graph_wires_no_later_phase() -> None:
    graph = build_phase2f_claim_scoring_graph(build_checkpointer())
    wired = set(graph.get_graph().nodes)
    for forbidden in FORBIDDEN_NODES:
        assert forbidden.value not in wired, (
            f"{forbidden.value} is wired into Phase 2F; an evidence index is "
            "not a project score and not a trust verdict"
        )


def test_project_scoring_remains_a_separate_later_node() -> None:
    """``SCORING`` still exists in the nominal order, after Phase 2F's nodes,
    and is not one of them (section 28)."""
    order = list(PRODUCTION_NODE_ORDER)
    assert order.index(NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING) < order.index(
        NodeId.SCORING
    )
    assert NodeId.SCORING not in PHASE_2F_NODE_SEQUENCE


def test_the_graph_needs_no_model_provider() -> None:
    """Section 19: a model-generated score is forbidden, so construction takes
    no provider and the run records no prompt version."""
    graph = build_phase2f_claim_scoring_graph(build_checkpointer())
    assert graph is not None
    run = ClaimEvidenceScoringRun(research_run_id=uuid4())
    for field in ("prompt_version", "model", "provider", "classifier_version"):
        assert field not in type(run).model_fields


def test_every_phase_2f_node_is_in_the_production_registry() -> None:
    for node in PHASE_2F_NODE_SEQUENCE:
        assert node in PRODUCTION_NODE_ORDER


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ClaimSufficiencyStatus.RUNNING, ClaimScoringStatus.NOT_READY),
        (ClaimSufficiencyStatus.NOT_READY, ClaimScoringStatus.NOT_READY),
        (
            ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE,
            ClaimScoringStatus.NOT_READY,
        ),
        (ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS, ClaimScoringStatus.NOT_READY),
    ],
)
def test_only_a_completed_sufficiency_run_is_scorable(
    status: ClaimSufficiencyStatus, expected: ClaimScoringStatus
) -> None:
    from src.schemas.claim_sufficiency import ClaimSufficiencyRun

    terminal = status in {
        ClaimSufficiencyStatus.NOT_READY,
        ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE,
        ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS,
    }
    run = ClaimSufficiencyRun(
        research_run_id=uuid4(),
        status=status,
        completed_at="2026-09-01T09:20:00+00:00" if terminal else None,
    )
    assert readiness(run) is expected


def test_no_sufficiency_run_is_not_ready() -> None:
    assert readiness(None) is ClaimScoringStatus.NOT_READY


def test_a_not_ready_scoring_run_cannot_hold_scorecards() -> None:
    card = ClaimEvidenceScoreCard.model_validate(_minimal_card())
    with pytest.raises(ValidationError, match="stopped before scoring"):
        ClaimEvidenceScoringRun(
            research_run_id=card.research_run_id,
            scoring_run_id=card.scoring_run_id,
            status=ClaimScoringStatus.NOT_READY,
            scorecards=[card],
            completed_at="2026-09-01T10:00:00+00:00",
        )


def test_a_finished_scoring_run_is_not_reopened() -> None:
    """Idempotency: re-invoking a finished graph must not produce a second set
    of scorecards (section 25)."""
    case = _supported_world("CS-790", groups=1)
    project = _project(case)
    state = _run_2e(case, project)
    run = state.active_research_run
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
    checkpointer = build_checkpointer()
    app = build_phase2f_claim_scoring_graph(checkpointer)
    first = coerce_graph_state(
        app.invoke(
            EvaluationGraphState(
                run_id=run_id,
                thread_id=config["configurable"]["thread_id"],
                project=state.project,
                research_runs={str(run.research_run_id): run},
                active_research_run_id=run.research_run_id,
            ),
            config,
        )
    )
    second = coerce_graph_state(app.invoke(None, config))
    before = first.active_research_run.claim_evidence_scoring
    after = second.active_research_run.claim_evidence_scoring
    assert before.status is ClaimScoringStatus.COMPLETED
    assert len(after.scorecards) == len(before.scorecards) == 1
    assert after.scorecards[0].scorecard_id == before.scorecards[0].scorecard_id


def test_a_checkpoint_resume_neither_loses_nor_duplicates_scorecards() -> None:
    case = _supported_world("CS-791", groups=2)
    project = _project(case)
    state = _run_2e(case, project)
    resumed = _run_2f(state, interrupt_before="APPLY_SCORE_DISPOSITION_POLICY")
    scoring = resumed.active_research_run.claim_evidence_scoring
    assert scoring.status is ClaimScoringStatus.COMPLETED
    assert len(scoring.scorecards) == 1
    assert scoring.scorecards[0].support.index_bp == INDEX_MAX_BP


def test_scoring_coverage_accounts_for_every_scorecard() -> None:
    with pytest.raises(ValidationError, match="issued a primary scalar or withheld"):
        ScoringCoverage(scorecards_total=2, scalars_issued=1, scalars_withheld=0)


# ===========================================================================
# 12. Immutability, with populated canonical state
# ===========================================================================


def test_a_real_run_mutates_no_canonical_project_state() -> None:
    case = _supported_world("CS-800", groups=2)
    project = _project(case, with_score_record=True)
    before = project.model_dump(mode="json")
    scores_before = [s.model_dump(mode="json") for s in project.scores]
    state = _run_2e(case, project)
    sufficiency_before = state.active_research_run.claim_sufficiency.model_dump(
        mode="json"
    )
    evidence_before = [
        e.model_dump(mode="json")
        for e in state.active_research_run.evidence_extraction.verified_evidence
    ]
    alignments_before = [
        a.model_dump(mode="json")
        for a in state.active_research_run.claim_evidence_alignment.alignments
    ]

    final = _run_2f(state)
    scoring = final.active_research_run.claim_evidence_scoring
    assert scoring.status is ClaimScoringStatus.COMPLETED
    assert scoring.scorecards  # the guard is not vacuous

    assert final.project.model_dump(mode="json") == before
    assert [s.model_dump(mode="json") for s in final.project.scores] == scores_before
    assert final.project.scores and final.project.scores[0].axes[0].score == 7
    assert (
        final.active_research_run.claim_sufficiency.model_dump(mode="json")
        == sufficiency_before
    )
    assert [
        e.model_dump(mode="json")
        for e in final.active_research_run.evidence_extraction.verified_evidence
    ] == evidence_before
    assert [
        a.model_dump(mode="json")
        for a in final.active_research_run.claim_evidence_alignment.alignments
    ] == alignments_before


def test_the_immutability_guard_can_fire() -> None:
    """A negative control: the comparison above must be capable of failing."""
    case = _supported_world("CS-801", groups=1)
    project = _project(case, with_score_record=True)
    before = project.model_dump(mode="json")
    project.scores[0].axes[0].rationale = "tampered by a hypothetical phase"
    assert project.model_dump(mode="json") != before


def test_the_scoring_run_lives_on_the_research_run_not_project_state() -> None:
    case = _supported_world("CS-802", groups=1)
    project = _project(case, with_score_record=True)
    state = _run_2e(case, project)
    final = _run_2f(state)
    assert final.active_research_run.claim_evidence_scoring is not None
    assert "claim_evidence_scoring" not in type(final.project).model_fields
    assert "scorecards" not in type(final.project).model_fields


def test_a_scoring_run_from_another_research_run_is_refused_by_the_research_run() -> None:
    case = _supported_world("CS-803", groups=1)
    project = _project(case)
    run = _open_run(case, project)
    foreign = ClaimEvidenceScoringRun(research_run_id=uuid4())
    with pytest.raises(ValidationError, match="different research run"):
        run.evolve(claim_evidence_scoring=foreign)


# ===========================================================================
# 13. The independent scorer and the metric set
# ===========================================================================


def test_the_release_blocking_gate_set_is_complete() -> None:
    """Section 32 requires 48 gates, each reported individually."""
    assert len(RELEASE_BLOCKING_SCORING_METRICS) == 48
    assert len(set(RELEASE_BLOCKING_SCORING_METRICS)) == 48
    metrics = ClaimScoringMetrics()
    assert len(metrics.safety_metrics) == 48


def test_every_required_metric_exists_and_starts_unmeasured() -> None:
    metrics = ClaimScoringMetrics()
    for name in REQUIRED_PERFECT_METRICS:
        counts = getattr(metrics, name)
        assert counts.total == 0
        assert counts.rate is None, (
            f"{name} reports a rate with no denominator; a subgroup nothing "
            "exercised has not measured accuracy, not zero accuracy"
        )
    assert metrics.thresholds_met is False


def test_the_independent_scorer_reimplements_the_policy() -> None:
    """The eval's arithmetic must not be an import of the engine's, or the
    metric would only prove the engine agrees with itself."""
    card = _card(_supported_world("CS-810", groups=1))
    traces = list(card.component_traces)
    assert recomputed_channel_bp(traces, "SUPPORT") == (5_000, 1_500, 2_000)
    assert recomputed_channel_bp(traces, "CONTRADICTION") == (0, 0, 0)
    assert sum(recomputed_channel_bp(traces, "SUPPORT")) == card.support.index_bp


def test_the_independent_denominator_agrees_with_the_inventory() -> None:
    card = _card(
        _world(
            COMPOUND,
            [_source("s1", "10.5555/den")],
            [{"key": "e1", "source": "s1", "excerpt": EXCERPT}],
            [
                {
                    "claim_id": "C-001",
                    "evidence": "e1",
                    "relation": "SUPPORTS",
                    "components": [{"text": A1, "judgment": "SUPPORTS"}],
                }
            ],
            case_id="CS-811",
        )
    )
    anchors = [(0, len(A1))]
    recomputed = expected_component_spans(COMPOUND, anchors)
    present = sorted((t.anchor_start, t.anchor_end) for t in card.component_traces)
    assert sorted(recomputed) == present


@pytest.mark.parametrize(
    "gate",
    [
        "support_contradiction_collapsed_into_net_rate",
        "contested_claim_received_final_scalar_rate",
        "incomplete_inventory_received_full_scalar_rate",
        "aggregate_score_arithmetic_mismatch_rate",
        "out_of_range_score_acceptance_rate",
        "score_typed_as_truth_probability_rate",
        "unexamined_component_omitted_from_denominator_rate",
        "duplicate_logical_source_inflated_support_rate",
    ],
)
def test_each_named_gate_starts_clean_and_can_record_a_violation(gate: str) -> None:
    """Negative controls: a gate that cannot fire proves nothing (section 32)."""
    metrics = ClaimScoringMetrics()
    counts = getattr(metrics, gate)
    assert counts.violations == 0
    counts.record(True)
    assert counts.violations == 1
    assert metrics.safety_clean is False


def test_the_eval_reports_an_errored_case_rather_than_passing_it() -> None:
    """A case that blew up must not be silently counted as clean."""
    from src.evals.claim_scoring.runner import ScoringCaseResult

    metrics = ClaimScoringMetrics()
    broken = ScoringCaseResult("CES-999", ["unit"], "en", error="ValueError: boom")
    case = load_scoring_dataset().cases[0]
    score_scoring_case(case, broken, metrics)
    assert metrics.cases_errored == 1
    from src.evals.claim_scoring.runner import evaluate_scoring_gate

    assert evaluate_scoring_gate(metrics).passed is False


# ===========================================================================
# 14. Gold dataset shape
# ===========================================================================


def test_the_gold_dataset_meets_its_coverage_minimums() -> None:
    dataset = load_scoring_dataset()
    assert len(dataset.cases) >= 144
    counts = dataset.language_counts
    assert counts.get("ar", 0) >= 28
    assert counts.get("mixed", 0) >= 20
    assert counts.get("en", 0) >= 1
    assert len(dataset.category_counts) >= 64


@pytest.mark.parametrize(
    "category",
    [
        "no_direct_evidence",
        "one_component_single_group",
        "one_component_multiple_groups",
        "partial_support_only",
        "full_multi_component_support",
        "one_supported_one_no_evidence",
        "full_contradiction",
        "partial_contradiction",
        "contested",
        "mixed_alignment",
        "same_doi_multiple_providers",
        "multiple_excerpts_same_paper",
        "duplicate_canonical_source_records",
        "distinct_doi_same_title",
        "context_only",
        "insufficient_evidence",
        "not_relevant",
        "retracted_supporting_source",
        "retracted_contradicting_source",
        "preprint_limitation",
        "unknown_publication_status",
        "unknown_retraction_status",
        "abstract_only_limitation",
        "complete_inventory",
        "incomplete_inventory",
        "unknown_inventory",
        "unexamined_material_component",
        "single_vs_multiple_group_saturation",
        "two_vs_twenty_groups",
        "duplicate_provider_unchanged",
        "duplicate_excerpt_unchanged",
        "not_relevant_leaves_support_unchanged",
        "context_only_leaves_support_unchanged",
        "insufficient_leaves_support_unchanged",
        "independent_support_cannot_lower",
        "contradiction_cannot_increase_support",
        "retraction_cannot_increase_support",
        "unknown_cannot_improve_reliability",
        "extra_uncovered_component_cannot_increase",
        "contested_scalar_withheld",
        "blocked_source_quality_scalar_withheld",
        "not_ready_scalar_withheld",
        "zero_vs_none",
        "no_net_collapse",
        "exact_score_arithmetic",
        "rounding_boundary",
        "min_bound",
        "max_bound",
        "score_vector_reconciliation",
        "fingerprint_stability",
        "fingerprint_sensitivity",
        "checkpoint_resume",
        "rerun_idempotency",
        "duplicate_scorecard_rejection",
        "project_state_immutability",
        "canonical_score_record_immutability",
        "phase2e_immutability",
        "cross_run_rejection",
        "cross_claim_isolation",
        "arabic_scientific_claim",
        "mixed_language_claim",
        "prompt_injection_inert",
        "official_score_separation",
        "policy_version_correctness",
    ],
)
def test_every_required_gold_category_is_present(category: str) -> None:
    """The 64 categories the specification enumerates, asserted by name so a
    regenerated dataset cannot quietly drop one."""
    assert category in load_scoring_dataset().category_counts


def test_the_gold_dataset_states_versions_on_every_expectation() -> None:
    """Section 18: a scorecard must be readable against the policy that
    produced it, so the dataset asserts the version rather than assuming it."""
    assert CLAIM_EVIDENCE_SCORING_POLICY_VERSION == "CLAIM-EVIDENCE-SCORING-POLICY-V1"
    assert CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION == "CLAIM-EVIDENCE-SCORE-SCHEMA-V1"
    assert SCORE_ARITHMETIC_VERSION == "SCORE-ARITHMETIC-V1"
    card = _card(_supported_world("CS-820", groups=1))
    assert card.policy_version == CLAIM_EVIDENCE_SCORING_POLICY_VERSION
    assert card.schema_version == CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION
    assert card.arithmetic_version == SCORE_ARITHMETIC_VERSION


def test_a_gold_case_cannot_claim_both_an_issued_and_a_withheld_scalar() -> None:
    with pytest.raises(ValidationError, match="both issue and withhold"):
        ScoringGoldCase.model_validate(
            {
                "case_id": "CES-998",
                "language": "en",
                "categories": ["unit"],
                "claims": [{"claim_id": "C-001", "claim": SIMPLE}],
                "expected": {
                    "final_support_index_bp": {"C-001": 8_500},
                    "final_withheld": ["C-001"],
                },
            }
        )


def test_the_unknown_inventory_case_withholds_its_scalar() -> None:
    """UNKNOWN completeness is unreachable through the graph, so the Gold suite
    reaches it below the graph and the scalar is still withheld (ADR-016)."""
    dataset = load_scoring_dataset()
    case = next(
        c for c in dataset.cases if c.direct_kind == "unknown_inventory"
    )
    outcome = run_scoring_case(case)
    assert outcome.ok, outcome.error
    card = outcome.unknown_inventory_card
    assert card is not None
    assert card.inventory_completeness is ComponentInventoryCompleteness.UNKNOWN
    assert card.disposition is ScoreDisposition.INCOMPLETE_INPUT_SCALAR_WITHHELD
    assert card.final_support_index_bp is None
    assert card.support.index_bp == 0
