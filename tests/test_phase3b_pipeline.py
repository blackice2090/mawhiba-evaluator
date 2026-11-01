"""Phase 3B production tests: graph, pipeline, bounds, provider failures, binding,
identity, replay and checkpoint (ADR-023). Upstream state comes from the real
Phase 2E-3A graphs; the model is a scripted, untrusted fake."""

from __future__ import annotations

import json
from uuid import uuid4

from src.graph.phase3b_graph import FORBIDDEN_NODES, PHASE_3B_NODE_SEQUENCE, build_phase3b_experiment_graph
from src.graph.registry import NodeId
from src.llm.contracts import ModelTask
from src.research.experiments import pipeline as xp
from src.schemas.common import ProjectType
from src.schemas.experiment_review import (
    ExperimentPosture,
    ExperimentReviewBounds,
    ExperimentReviewRun,
    ExperimentRunIssueCode,
    ExperimentRunStatus,
    ExperimentStage,
    adequacy_fingerprint,
    experiment_uuid,
    protocol_key,
)
from src.schemas.novelty_differentiation import OccurrenceResolution
from tests import phase3a_support as p3a
from tests.phase3b_support import (
    P_DEFINE,
    P_SETUP,
    RESULT,
    SUBMISSION,
    ScriptedExperimentModel,
    edited,
    resubmit,
    review,
    run_phase3b,
    run_stages,
    world,
)

C = ExperimentRunIssueCode
P2_DEFINE = "Experiment 2 runs the controller on one outdoor plot for 30 days."
MULTI = SUBMISSION.replace(RESULT, f"{P2_DEFINE} {RESULT}")


def codes(run: ExperimentReviewRun) -> set[ExperimentRunIssueCode]:
    return {e.code for e in run.errors}


def seg(*experiments: dict, results: tuple = ({"kind": "REPORTED_METRIC_VALUE", "span": RESULT},)) -> dict:
    return {"experiments": list(experiments), "results": list(results)}


# -- graph / pipeline -------------------------------------------------------------------------


def test_graph_happy_path_is_well_specified_bounded_and_search_free():
    model = ScriptedExperimentModel({})
    run = review(run_phase3b(world(), model.provider()))
    assert run.status is ExperimentRunStatus.COMPLETED
    assert run.project_posture is ExperimentPosture.WELL_SPECIFIED
    assert [e.posture for e in run.experiments] == [ExperimentPosture.WELL_SPECIFIED]
    assert run.model_calls_performed == 4 == len(model.calls)  # 1 + 3 per experiment
    assert run.external_search_calls == 0 and run.network_attempts == 0
    assert run.execution_verified is False and run.results_evaluated is False
    assert run.stage_markers == list(ExperimentStage)


def test_graph_wires_the_seven_approved_stages_and_no_forbidden_node():
    graph = build_phase3b_experiment_graph()
    wired = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert wired == {n.value for n in PHASE_3B_NODE_SEQUENCE}
    assert [n.value for n in PHASE_3B_NODE_SEQUENCE] == [s.value for s in ExperimentStage]
    assert not wired & {n.value for n in FORBIDDEN_NODES}
    assert NodeId.EXPERIMENT_REVIEW in FORBIDDEN_NODES and NodeId.SCORING in FORBIDDEN_NODES


def test_graph_writes_only_the_experiment_review_subrun():
    state = world()
    after = run_phase3b(state, ScriptedExperimentModel({}).provider())
    before_rr, after_rr = state.active_research_run, after.active_research_run
    assert after.project == state.project
    for name in ("research_engineering_gap", "methodology_review", "novelty_differentiation"):
        assert getattr(after_rr, name) == getattr(before_rr, name)


def test_no_experiments_segmented_is_never_well_specified():
    run = run_stages(world(), ScriptedExperimentModel({"segment": seg()}).provider())
    assert run.status is ExperimentRunStatus.COMPLETED and run.experiments == []
    assert run.phase2j_coverage[0].status.value == "NOT_COVERED"
    assert run.untested_claim_ids == ["C-001"]
    assert run.project_posture is ExperimentPosture.MAJOR_GAPS


def test_multiple_experiments_are_separate_records_with_their_own_links():
    script = {
        "segment": seg({"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]}),
        "link": {"Experiment 2": {"targets": {"T1": {"relation": "DOES_NOT_TEST"},
                                              "V1": {"relation": "DOES_NOT_TEST"}}}},
    }
    model = ScriptedExperimentModel(script)
    run = run_stages(world(MULTI), model.provider())
    assert len(run.experiments) == 2 and run.model_calls_performed == 1 + 3 * 2
    by_key = {e.protocol_key: e for e in run.experiments}
    second = by_key[protocol_key([P2_DEFINE])]
    assert "EXPERIMENT_DOES_NOT_TEST_TARGET" in second.issues
    assert run.phase2j_coverage[0].covering_experiment_ids == [by_key[protocol_key([P_DEFINE])].experiment_id]


def test_experiment_bound_reached_is_never_read_as_complete():
    script = {"segment": seg({"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]})}
    run = run_stages(world(MULTI), ScriptedExperimentModel(script).provider(),
                     bounds=ExperimentReviewBounds(max_experiments=1, max_model_calls=4))
    assert len(run.experiments) == 1 and C.EXPERIMENT_BOUND_REACHED in codes(run)
    assert run.status is ExperimentRunStatus.INSUFFICIENT_INPUT and run.project_posture is None


def test_model_call_bound_is_a_hard_bound_including_retries():
    run = run_stages(world(), ScriptedExperimentModel({}).provider(), bounds=ExperimentReviewBounds(max_model_calls=0))
    assert C.MODEL_CALL_BOUND_REACHED in codes(run) and run.model_calls_performed == 0
    assert run.project_posture is not ExperimentPosture.WELL_SPECIFIED
    failing = ScriptedExperimentModel({"segment": seg({"label": "X1", "excerpts": [P_DEFINE]}),
                                       "extract": "provider_error", "link": "provider_error"})
    bounds = ExperimentReviewBounds(max_experiments=1, max_model_calls=4, model_retry_limit=3)
    run = run_stages(world(), failing.provider(), bounds=bounds)
    assert run.model_calls_performed == len(failing.calls) <= 4
    assert C.MODEL_CALL_BOUND_REACHED in codes(run)


def test_provider_missing_fails_closed():
    run = run_stages(world(), None)
    assert codes(run) == {C.MODEL_PROVIDER_MISSING} and run.experiments == []
    assert run.project_posture is ExperimentPosture.MAJOR_GAPS


def test_each_provider_failure_has_its_own_code_and_never_yields_well():
    for kind, code in (("refusal", C.MODEL_REFUSED), ("parse_error", C.MODEL_RESPONSE_INVALID),
                       ("incomplete", C.PARTIAL_MODEL_OUTPUT), ("provider_error", C.MODEL_RESPONSE_INVALID)):
        run = run_stages(world(), ScriptedExperimentModel({"extract": kind}).provider(),
                         bounds=ExperimentReviewBounds(model_retry_limit=0))
        exp = run.experiments[0]
        assert code in codes(run), kind
        assert exp.experiment_type.value == "UNKNOWN" and exp.posture is ExperimentPosture.INSUFFICIENT_EVIDENCE
        assert run.project_posture is not ExperimentPosture.WELL_SPECIFIED


def test_partial_link_failure_leaves_targets_unresolved_not_untested():
    run = run_stages(world(), ScriptedExperimentModel({"link": "refusal"}).provider())
    assert {link.relation.value for link in run.links} == {"UNRESOLVED"}
    assert run.experiments[0].posture is ExperimentPosture.UNRESOLVED
    assert run.phase2j_coverage[0].status.value == "UNRESOLVED"
    assert run.project_posture is not ExperimentPosture.WELL_SPECIFIED


def test_checkpoint_resume_is_equivalent_and_makes_no_extra_model_call():
    straight = ScriptedExperimentModel({})
    resumed = ScriptedExperimentModel({})
    a = review(run_phase3b(world(), straight.provider()))
    b = review(run_phase3b(world(), resumed.provider(), interrupt_before=NodeId.EXPERIMENT_LINK_TARGETS.value))
    assert adequacy_fingerprint(a) == adequacy_fingerprint(b)
    assert len(straight.calls) == len(resumed.calls) == b.model_calls_performed


def test_replaying_any_stage_on_a_finished_run_is_a_no_op():
    model = ScriptedExperimentModel({})
    state = world()
    run = run_stages(state, model.provider())
    n = len(model.calls)
    sub, rr, llm, bounds = state.submission, state.active_research_run, None, ExperimentReviewBounds()
    assert xp.segment_stage(run, sub, model.provider(), llm, bounds) == run
    assert xp.extract_stage(run, sub, model.provider(), llm, bounds) == run
    assert xp.link_stage(run, rr, state.project, sub, model.provider(), llm, bounds) == run
    assert xp.finalize_stage(run, rr, state.project, sub, run.started_at) == run
    assert len(model.calls) == n


def test_checkpoint_json_round_trip_is_equal():
    run = run_stages(world(), ScriptedExperimentModel({}).provider())
    assert ExperimentReviewRun.model_validate_json(run.model_dump_json()) == run
    assert ExperimentReviewRun.model_validate(json.loads(run.model_dump_json())) == run


# -- binding -------------------------------------------------------------------------------------


def test_missing_phase_3a_run_is_source_binding_missing():
    state = world()
    rr = state.active_research_run.model_copy(update={"methodology_review": None})
    run = run_stages(state.model_copy(update={"research_runs": {str(rr.research_run_id): rr}}),
                     ScriptedExperimentModel({}).provider())
    assert run.status is ExperimentRunStatus.INSUFFICIENT_INPUT and codes(run) == {C.SOURCE_BINDING_MISSING}
    assert run.project_posture is None and run.experiments == []


def test_submission_hash_mismatch_with_phase_3a_is_rejected_at_bind():
    state = resubmit(world(), SUBMISSION + " An extra unrelated sentence.")
    run = run_stages(state, ScriptedExperimentModel({}).provider())
    assert run.status is ExperimentRunStatus.INSUFFICIENT_INPUT and C.SOURCE_BINDING_MISSING in codes(run)


def test_project_type_mismatch_is_project_type_unbound():
    state = p3a.with_project(world(), ProjectType.SCIENTIFIC_RESEARCH)
    run = run_stages(state, ScriptedExperimentModel({}).provider())
    assert run.status is ExperimentRunStatus.INSUFFICIENT_INPUT and C.PROJECT_TYPE_UNBOUND in codes(run)


def test_unknown_claim_hypothesis_and_cross_run_ids_are_refused():
    link = {"targets": {"T9": {"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE]},
                        "V7": {"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE]},
                        str(uuid4()): {"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE]}}}
    run = run_stages(world(), ScriptedExperimentModel({"link": link}).provider())
    assert {C.UNKNOWN_TARGET, C.CROSS_RUN_REFERENCE} <= {r.code for r in run.rejected_proposals}
    assert C.UNKNOWN_TARGET in codes(run) and C.CROSS_RUN_REFERENCE in codes(run)
    assert {link.relation.value for link in run.links} == {"UNRESOLVED"}  # the real targets stay unjudged


def test_upstream_drift_between_bind_and_finalize_invalidates_the_run():
    state = world()
    changed = state.project.model_copy(update={"claims": [
        state.project.claims[0].model_copy(update={"claim": "A different claim text"})]})
    run = run_stages(state, ScriptedExperimentModel({}).provider(), final_project=changed)
    assert run.status is ExperimentRunStatus.INVALIDATED_UPSTREAM_MUTATED and C.UPSTREAM_MUTATED in codes(run)
    assert run.experiments == [] and run.track_postures == [] and run.project_posture is None


def test_stale_submission_at_finalize_invalidates_the_run():
    state = world()
    stale = resubmit(state, SUBMISSION.replace("12 soil trays", "13 soil trays")).submission
    run = run_stages(state, ScriptedExperimentModel({}).provider(), final_submission=stale)
    assert run.status is ExperimentRunStatus.INVALIDATED_UPSTREAM_MUTATED


# -- identity --------------------------------------------------------------------------------------


def test_experiment_id_is_derived_from_run_and_protocol_text():
    run = run_stages(world(), ScriptedExperimentModel({}).provider())
    exp = run.experiments[0]
    assert exp.protocol_key == protocol_key([P_DEFINE])
    assert exp.experiment_id == experiment_uuid(run.experiment_run_id, exp.protocol_key)


def test_unrelated_text_and_result_changes_do_not_change_identity():
    base = run_stages(world(), ScriptedExperimentModel({}).provider())
    shifted_text = "Background: irrigation wastes water in many regions. " + SUBMISSION
    shifted = run_stages(world(shifted_text), ScriptedExperimentModel({}).provider())
    assert [e.experiment_id for e in shifted.experiments] == [e.experiment_id for e in base.experiments]
    assert shifted.excerpts[0].start != base.excerpts[0].start
    assert adequacy_fingerprint(shifted) == adequacy_fingerprint(base)


def test_repeated_defining_text_needs_a_validated_disambiguator():
    text = SUBMISSION.replace(RESULT, f"{P_DEFINE} {RESULT}")
    guess = run_stages(world(text), ScriptedExperimentModel({}).provider())
    assert guess.experiments == [] and C.AMBIGUOUS_EXCERPT in codes(guess)
    second = {"excerpt": P_DEFINE, "occurrence": 2}
    run = run_stages(world(text), ScriptedExperimentModel({"segment": seg({"label": "X1", "excerpts": [second]})})
                     .provider())
    defining = next(e for e in run.excerpts if e.excerpt_id == run.experiments[0].defining_excerpt_ids[0])
    assert defining.occurrence_index == 2 and defining.start == text.rindex(P_DEFINE)
    assert defining.occurrence_resolution is OccurrenceResolution.VALIDATED_OCCURRENCE_INDEX


def test_one_protocol_described_in_two_places_is_one_record_in_document_order():
    script = {"segment": seg({"label": "X1", "excerpts": [P_SETUP, P_DEFINE]})}
    run = run_stages(world(), ScriptedExperimentModel(script).provider())
    assert len(run.experiments) == 1
    exp = run.experiments[0]
    assert exp.protocol_key == protocol_key([P_DEFINE, P_SETUP]) and len(exp.defining_excerpt_ids) == 2


def test_identical_protocol_listed_twice_is_one_experiment():
    script = {"segment": seg({"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P_DEFINE]})}
    run = run_stages(world(), ScriptedExperimentModel(script).provider())
    assert len(run.experiments) == 1


def test_a_changed_protocol_is_a_new_experiment_naming_its_revision():
    script = {"segment": seg({"label": "X1", "excerpts": [P_DEFINE]},
                             {"label": "X2", "excerpts": [P2_DEFINE], "revision_of": "X1"})}
    run = run_stages(world(MULTI), ScriptedExperimentModel(script).provider())
    first = next(e for e in run.experiments if e.protocol_key == protocol_key([P_DEFINE]))
    second = next(e for e in run.experiments if e.protocol_key == protocol_key([P2_DEFINE]))
    assert second.revision_of == first.experiment_id and first.revision_of is None
    assert first.experiment_id != second.experiment_id


def test_model_list_order_never_reaches_canonical_state():
    a = run_stages(world(), ScriptedExperimentModel({}).provider())
    b = run_stages(world(), ScriptedExperimentModel({"reverse": True}).provider())
    assert a == b
    script = {"segment": seg({"label": "X2", "excerpts": [P2_DEFINE]}, {"label": "X1", "excerpts": [P_DEFINE]})}
    rev = {"segment": seg({"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]})}
    assert run_stages(world(MULTI), ScriptedExperimentModel(script).provider()) == run_stages(
        world(MULTI), ScriptedExperimentModel(edited(rev, reverse=True)).provider())
