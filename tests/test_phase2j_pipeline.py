"""Phase 2J pipeline: real upstream graphs -> real Phase 2J graph, scripted untrusted model.

Covers the end-to-end path, replay/idempotency, checkpoint resume, run binding,
upstream immutability, input-order invariance and the unbound outcomes.
"""

from __future__ import annotations

import pytest

from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.schemas.gap_assessment import (
    ConditionMateriality,
    GapAssessmentRun,
    GapCorroborationLevel,
    GapKind,
    GapPosture,
    GapRunStatus,
    InsufficientReason,
    LinkageRelation,
    ProjectLinkageLevel,
)

from src.evals.research_engineering_gap.fixtures import (
    CLAIM,
    CLAIMS,
    ND_SCRIPT,
    PATENT,
    SECOND_LIMITATION,
    LIMITATION,
    extract_with,
    script as _script,
)


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-901", CLAIMS, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


@pytest.fixture(scope="module")
def supported(upstream):
    model = ScriptedGapModel({"C-001": CLAIM}, _script())
    return model, run_phase2j(upstream, model.provider())


def _gap(state) -> GapAssessmentRun:
    return state.active_research_run.research_engineering_gap


def test_full_chain_reaches_supported_within_bounds(supported):
    gap = _gap(supported[1])
    assert gap.status is GapRunStatus.COMPLETED and gap.is_terminal
    (hypothesis,) = gap.hypotheses
    assert hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert hypothesis.kind is GapKind.ENGINEERING
    assert hypothesis.linkage is ProjectLinkageLevel.FULL
    # The lone patent publication's family was not established by Phase 2G, so Phase 2I
    # marks its unit never-independent; Phase 2J inherits that unchanged (no inference).
    assert hypothesis.corroboration is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
    assert list(hypothesis.condition_materiality.values()) == [ConditionMateriality.CONDITION_REQUIRED_AND_BOUND]
    assert hypothesis.counterevidence_review_complete
    assert {link.relation for link in hypothesis.project_links} == {LinkageRelation.ADDRESSES_LIMITATION}
    assert gap.claim_assessments[0].posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert gap.external_search_calls == 0


def test_three_calls_one_per_stage(supported):
    tasks = [t.value for t, _ in supported[0].calls]
    assert tasks == ["GAP_CANDIDATE_EXTRACTION", "GAP_PROJECT_LINKAGE", "GAP_COUNTEREVIDENCE_REVIEW"]
    assert _gap(supported[1]).model_calls_performed == 3


def test_phase2j_leaves_the_research_run_open_and_the_project_untouched(upstream, supported):
    after = supported[1]
    assert not after.active_research_run.is_terminal
    assert after.project == upstream.project
    assert after.project.gap.status.value == "NOT_EVALUATED"


def test_upstream_subruns_are_unchanged(upstream, supported):
    before, after = upstream.active_research_run, supported[1].active_research_run
    for name in ("evidence_extraction", "claim_sufficiency", "claim_evidence_scoring", "patent_prior_art",
                 "product_prior_art", "open_source_prior_art", "novelty_differentiation"):
        a, b = getattr(before, name), getattr(after, name)
        assert (a.model_dump_json() if a else None) == (b.model_dump_json() if b else None), name


def test_gap_run_round_trips_through_serialization(supported):
    gap = _gap(supported[1])
    assert GapAssessmentRun.model_validate_json(gap.model_dump_json()) == gap


def test_replay_over_a_finished_run_makes_no_model_call_and_changes_nothing(supported):
    model, state = supported
    calls_before = len(model.calls)
    replay = run_phase2j(state, model.provider())
    assert len(model.calls) == calls_before
    assert _gap(replay) == _gap(state)


def test_checkpoint_resume_matches_an_uninterrupted_run(upstream):
    first = ScriptedGapModel({"C-001": CLAIM}, _script())
    straight = _gap(run_phase2j(upstream, first.provider()))
    second = ScriptedGapModel({"C-001": CLAIM}, _script())
    resumed = _gap(run_phase2j(upstream, second.provider(), interrupt_before="VERIFY_GAP_PROJECT_LINKAGE"))
    assert len(second.calls) == len(first.calls) == 3
    assert [h.model_dump(mode="json") for h in resumed.hypotheses] == [h.model_dump(mode="json") for h in straight.hypotheses]
    assert [a.posture for a in resumed.claim_assessments] == [a.posture for a in straight.claim_assessments]


def test_order_of_proposed_items_does_not_change_the_result(upstream):
    results = []
    for limitations in ([LIMITATION, SECOND_LIMITATION], [SECOND_LIMITATION, LIMITATION]):
        extract = extract_with(limitations=limitations, validation=None)
        model = ScriptedGapModel({"C-001": CLAIM}, _script(extract=extract))
        results.append(_gap(run_phase2j(upstream, model.provider())).hypotheses[0])
    first, second = results
    assert [x.limitation_id for x in first.limitations] == [x.limitation_id for x in second.limitations]
    assert first.posture == second.posture and first.kind == second.kind


def test_no_provider_is_insufficient_input_never_no_gap(upstream):
    gap = _gap(run_phase2j(upstream, None))
    (assessment,) = gap.claim_assessments
    assert assessment.posture is GapPosture.INSUFFICIENT_INPUT
    assert InsufficientReason.MODEL_PROVIDER_MISSING in assessment.insufficient_reasons
    assert not gap.hypotheses and gap.model_calls_performed == 0


def test_missing_phase_2i_is_insufficient_input_for_every_claim(upstream):
    from src.schemas.research import ResearchRun

    run = upstream.active_research_run
    bare = ResearchRun.model_validate({**dict(run), "novelty_differentiation": None})
    state = upstream.model_copy(update={"research_runs": {str(bare.research_run_id): bare}})
    gap = _gap(run_phase2j(state, ScriptedGapModel({"C-001": CLAIM}, _script()).provider()))
    assert gap.status is GapRunStatus.INSUFFICIENT_INPUT and gap.is_terminal
    assert [a.posture for a in gap.claim_assessments] == [GapPosture.INSUFFICIENT_INPUT]
    assert gap.claim_assessments[0].insufficient_reasons == [InsufficientReason.NO_PHASE_2I_RUN]


def test_extraction_failure_is_insufficient_not_no_gap(upstream):
    model = ScriptedGapModel({"C-001": CLAIM}, {"extract": {"C-001": "provider_error"}})
    (assessment,) = _gap(run_phase2j(upstream, model.provider())).claim_assessments
    assert assessment.posture is GapPosture.INSUFFICIENT_INPUT
    assert InsufficientReason.MODEL_CALL_FAILED in assessment.insufficient_reasons


def test_two_claims_are_assessed_independently_and_in_a_stable_order():
    other = "A battery powered pump controller"
    claims = [{"claim_id": "C-002", "claim": other}, *CLAIMS]  # deliberately not sorted
    world = build_phase2i_world("PJ-909", claims, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)
    model = ScriptedGapModel({"C-001": CLAIM, "C-002": other}, _script())  # no script for C-002 -> its call fails
    gap = _gap(run_phase2j(world, model.provider()))
    assert [a.claim_id for a in gap.claim_assessments] == ["C-001", "C-002"]
    by_claim = {a.claim_id: a for a in gap.claim_assessments}
    assert by_claim["C-001"].posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert by_claim["C-002"].posture is GapPosture.INSUFFICIENT_INPUT
    assert InsufficientReason.MODEL_CALL_FAILED in by_claim["C-002"].insufficient_reasons
    assert [h.claim_id for h in gap.hypotheses] == ["C-001"]
    assert gap.project_summary.claim_posture_counts == {"INSUFFICIENT_INPUT": 1, "SUPPORTED_WITHIN_BOUNDS": 1}
    # an excerpt cut for one claim can never appear on another (no cross-claim leakage)
    assert {r.evidence_ref_id for r in gap.hypotheses[0].evidence_refs} <= set(gap.eligible_evidence_ref_ids)
