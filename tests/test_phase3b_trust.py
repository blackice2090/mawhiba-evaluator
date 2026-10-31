"""Phase 3B production trust-boundary tests (ADR-023): applicability, exact anchoring,
the result quarantine, the execution boundary, baselines, measurement, sample and
repetition, statistics, linkage, Phase 2J continuity and HYBRID ownership.

Every run goes through the real Phase 3B stages over a real Phase 2E-3A upstream; the
model is scripted and untrusted. These are focused production tests, not Gold."""

from __future__ import annotations

import inspect

from src.llm.contracts import ModelTask
from src.research.experiments import synthesis
from src.research.experiments.verify import QUARANTINE_PLACEHOLDER
from src.schemas.common import ProjectType
from src.schemas.experiment_review import (
    Applicability,
    ApplicabilityBasis,
    ComparabilityRollup,
    ContinuityReason,
    CoverageStatus,
    ExecutionStatus,
    ExperimentBaselineRecord,
    ExperimentPosture,
    ExperimentRequirementKind,
    ExperimentReviewRun,
    ExperimentRunIssueCode,
    ExperimentStage,
    FairnessBasis,
    FairnessProperty,
    FairnessPropertyStatus,
    MetricTargetAlignment,
    ProtocolAdequacy,
    SuccessCriterionTiming,
    TargetRelation,
    TrackOwnershipBasis,
    TYPE_FAMILY,
    adequacy_fingerprint,
    protocol_key,
)
from src.schemas.methodology_review import BaselineRelevance, DocumentationStatus, MethodologyTrack
from tests.phase3b_support import (
    P_CONDITION,
    P_CRITERION,
    P_DEFINE,
    P_METHOD,
    P_METRIC,
    P_OBJECTIVE,
    P_REPEAT,
    P_SAMPLE,
    RESULT,
    SUBMISSION,
    ScriptedExperimentModel,
    documented,
    measured,
    run_stages,
    well_link,
    world,
)

C = ExperimentRunIssueCode
K = ExperimentRequirementKind
P = ExperimentPosture
P_BASE = "The baseline is a fixed timer controller run on the same trays in the same lab."
P2_DEFINE = "Experiment 2 runs the controller on one outdoor plot for 30 days."
WITH_BASE = SUBMISSION.replace(RESULT, f"{P_BASE} {RESULT}")
MULTI = SUBMISSION.replace(RESULT, f"{P_BASE} {P2_DEFINE} {RESULT}")


def ext(xtype: str = "ENGINEERING_BENCH_TEST", missing: tuple[str, ...] = (), **extra) -> dict:
    from src.schemas.experiment_review import ExperimentType

    return {"type": xtype, "requirements": documented(ExperimentType(xtype), missing=missing, extra=extra)}


def go(script: dict, text: str = SUBMISSION, **kw) -> ExperimentReviewRun:
    return run_stages(world(text, **kw), ScriptedExperimentModel(script).provider())


def exp0(run: ExperimentReviewRun):
    return run.experiments[0]


def req(run: ExperimentReviewRun, kind: ExperimentRequirementKind, index: int = 0):
    return next(r for r in run.experiments[index].requirements if r.kind is kind)


def rejected(run: ExperimentReviewRun) -> set[ExperimentRunIssueCode]:
    return {r.code for r in run.rejected_proposals}


def link_with(**targets) -> dict:
    base = well_link()
    base["targets"].update(targets)
    return base


# -- applicability --------------------------------------------------------------------------------


def test_required_cannot_be_lowered_by_a_model_judgment():
    run = go({"applicability": {"METRIC": {"fired": [], "excerpts": [P_DEFINE]}}})
    assert C.INVENTED_REQUIREMENT in rejected(run)
    metric = req(run, K.METRIC)
    assert metric.applicability is Applicability.REQUIRED and metric.basis is ApplicabilityBasis.CATALOG_DEFAULT


def test_omitted_judgment_is_never_not_applicable():
    run = go({"applicability_omit": True})
    pending = [r for r in exp0(run).requirements if r.applicability is Applicability.CONDITIONAL]
    assert pending and all(r.basis is ApplicabilityBasis.CONDITION_UNRESOLVED for r in pending)
    assert exp0(run).posture is P.UNRESOLVED and run.project_posture is not P.WELL_SPECIFIED
    assert C.PARTIAL_MODEL_OUTPUT in {e.code for e in run.errors}


def test_a_trigger_outside_the_closed_set_or_a_phase_2j_trigger_is_refused():
    run = go({"applicability": {"CONTROL_STRATEGY": {"fired": ["PHASE_2J_BASELINE_REQUIRED"], "excerpts": [P_DEFINE]},
                                "BLINDING": {"fired": ["MADE_UP"], "excerpts": [P_DEFINE]}}})
    assert req(run, K.CONTROL_STRATEGY).applicability is Applicability.CONDITIONAL
    assert req(run, K.BLINDING).applicability is Applicability.CONDITIONAL


def test_control_strategy_is_conditional_unless_the_type_requires_it():
    bench = go({"applicability": {"CONTROL_STRATEGY": {"fired": ["ASSIGNED_INTERVENTION"], "excerpts": [P_DEFINE]}}})
    control = req(bench, K.CONTROL_STRATEGY)
    assert control.applicability is Applicability.REQUIRED and control.basis is ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT
    assert "CONTROL_MISSING_WHEN_REQUIRED" in exp0(bench).issues and exp0(bench).posture is P.MAJOR_GAPS
    assert req(go({}), K.CONTROL_STRATEGY).applicability is Applicability.NOT_APPLICABLE
    controlled = go({"extract": ext("SCIENTIFIC_CONTROLLED_EXPERIMENT")})
    assert req(controlled, K.CONTROL_STRATEGY).basis is ApplicabilityBasis.CATALOG_TYPE_OVERRIDE


def test_randomization_and_blinding_are_never_universal():
    observational = go({"extract": ext("SCIENTIFIC_OBSERVATIONAL_STUDY")})
    assert req(observational, K.RANDOMIZATION).applicability is Applicability.NOT_APPLICABLE
    assert req(observational, K.RANDOMIZATION).basis is ApplicabilityBasis.CATALOG_TYPE_OVERRIDE
    controlled = go({"extract": ext("SCIENTIFIC_CONTROLLED_EXPERIMENT"),
                     "applicability": {"RANDOMIZATION": {"fired": ["ASSIGNED_INTERVENTION"], "excerpts": [P_DEFINE]},
                                       "BLINDING": {"fired": [], "excerpts": [P_DEFINE]}}})
    assert req(controlled, K.RANDOMIZATION).applicability is Applicability.REQUIRED
    assert req(controlled, K.BLINDING).applicability is Applicability.NOT_APPLICABLE
    rated = go({"applicability": {"BLINDING": {"fired": ["SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT"],
                                               "excerpts": [P_DEFINE]}}})
    assert req(rated, K.BLINDING).applicability is Applicability.REQUIRED


def test_repetitions_and_external_validation_follow_family_and_trigger():
    assert req(go({}), K.REPETITIONS).applicability is Applicability.REQUIRED  # engineering cell R
    ai = go({"extract": ext("AI_ML_MODEL_EVALUATION"),
             "applicability": {"REPETITIONS": {"fired": ["STOCHASTIC_PROCESS"], "excerpts": [P_DEFINE]},
                               "EXTERNAL_VALIDATION": {"fired": ["GENERALIZATION_CLAIMED"], "excerpts": [P_DEFINE]}}})
    assert req(ai, K.REPETITIONS).applicability is Applicability.REQUIRED
    assert req(ai, K.EXTERNAL_VALIDATION).applicability is Applicability.REQUIRED
    external = go({"extract": ext("AI_ML_EXTERNAL_VALIDATION")})
    assert req(external, K.EXTERNAL_VALIDATION).basis is ApplicabilityBasis.CATALOG_TYPE_OVERRIDE


def test_unknown_type_is_capped_and_makes_no_applicability_call():
    model = ScriptedExperimentModel({"extract": ext("UNKNOWN")})
    run = run_stages(world(), model.provider())
    assert model.count(ModelTask.EXPERIMENT_APPLICABILITY) == 0
    assert all(r.basis is ApplicabilityBasis.EXPERIMENT_TYPE_UNKNOWN for r in exp0(run).requirements)
    assert exp0(run).posture in (P.UNRESOLVED, P.MAJOR_GAPS) and run.project_posture is not P.WELL_SPECIFIED
    invented = go({"extract": {**ext(), "type": "QUANTUM_MAGIC_TEST"}})
    assert exp0(invented).experiment_type.value == "UNKNOWN"


# -- exact anchoring ------------------------------------------------------------------------------


def test_every_stored_excerpt_is_the_exact_submission_slice():
    state = world()
    run = run_stages(state, ScriptedExperimentModel({}).provider())
    assert run.excerpts and all(e.matches(state.submission.original_text) for e in run.excerpts)


def test_fabricated_excerpt_is_refused_and_absence_is_a_gap():
    run = go({"extract": ext(OBJECTIVE={"excerpts": ["The objective is to win the competition."]},
                             HYPOTHESIS_OR_VALIDATION_OBJECTIVE={"excerpts": ["Invented text."]})})
    assert C.EXACT_EXCERPT_MISMATCH in rejected(run)
    assert req(run, K.OBJECTIVE).documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    assert "OBJECTIVE_MISSING" in exp0(run).issues and exp0(run).posture is P.MAJOR_GAPS


def test_repeated_excerpt_and_invalid_offsets_are_refused():
    text = SUBMISSION.replace(RESULT, f"{P_OBJECTIVE} {RESULT}")
    run = go({}, text)
    assert C.AMBIGUOUS_EXCERPT in rejected(run)
    assert req(run, K.OBJECTIVE).documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    offsets = go({"extract": ext(METRIC={"excerpts": [{"excerpt": P_METRIC, "start": 0, "end": len(P_METRIC)}]})})
    assert C.EXACT_EXCERPT_MISMATCH in rejected(offsets)
    explicit = text.rindex(P_OBJECTIVE)
    ok = go({"extract": ext(OBJECTIVE={"excerpts": [{"excerpt": P_OBJECTIVE, "start": explicit,
                                                     "end": explicit + len(P_OBJECTIVE)}]})}, text)
    assert req(ok, K.OBJECTIVE).documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED


# -- result quarantine ------------------------------------------------------------------------------


def test_result_value_change_leaves_adequacy_and_every_posture_unchanged():
    def run_for(value: str) -> ExperimentReviewRun:
        res = RESULT.replace("97", value)
        script = {"segment": {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}],
                              "results": [{"kind": "REPORTED_METRIC_VALUE", "span": res}]}}
        return go(script, SUBMISSION.replace(RESULT, res))

    high, low = run_for("97"), run_for("41")
    assert adequacy_fingerprint(high) == adequacy_fingerprint(low)
    assert [e.posture for e in high.experiments] == [e.posture for e in low.experiments]
    assert [t.posture for t in high.track_postures] == [t.posture for t in low.track_postures]
    assert high.project_posture is low.project_posture
    assert high.quarantine[0].span_hash != low.quarantine[0].span_hash


def test_quarantine_stores_no_text_and_later_calls_never_see_it():
    model = ScriptedExperimentModel({})
    run = run_stages(world(), model.provider())
    assert len(run.quarantine) == 1 and RESULT not in run.model_dump_json()
    extraction = next(u for t, u in model.calls if t is ModelTask.EXPERIMENT_PROTOCOL_EXTRACTION)
    assert RESULT not in extraction and QUARANTINE_PLACEHOLDER in extraction
    assert all(RESULT not in u for t, u in model.calls if t is not ModelTask.EXPERIMENT_SEGMENTATION)


def test_result_table_and_conclusion_cannot_become_protocol_evidence():
    table = "| run | accuracy |\n| 1 | 97 |"
    conclusion = "We conclude the controller is better than any timer."
    text = SUBMISSION.replace(RESULT, f"{table} {conclusion}")
    script = {"segment": {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}],
                          "results": [{"kind": "RESULT_TABLE", "span": table}, {"kind": "CONCLUSION", "span": conclusion}]},
              "extract": ext(METRIC={"excerpts": [table]}, SUCCESS_CRITERION={"excerpts": [conclusion]})}
    run = go(script, text)
    assert {q.kind.value for q in run.quarantine} == {"RESULT_TABLE", "CONCLUSION"}
    assert C.RESULT_LEAKAGE_ATTEMPT in rejected(run) and C.RESULT_LEAKAGE_ATTEMPT in {e.code for e in run.errors}
    assert req(run, K.METRIC).documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    assert "METRIC_MISSING" in exp0(run).issues


def test_defining_span_overlapping_a_result_is_cut_by_the_quarantine():
    script = {"segment": {"experiments": [{"label": "X1", "excerpts": [RESULT]}],
                          "results": [{"kind": "REPORTED_METRIC_VALUE", "span": "97 percent of the time"}]}}
    run = go(script)
    assert run.experiments == [] and C.RESULT_LEAKAGE_ATTEMPT in rejected(run)
    assert all(r.stage is ExperimentStage.SEGMENT_EXPERIMENTS for r in run.rejected_proposals)


def test_no_derivation_function_accepts_result_or_quarantine_input():
    banned = ("result", "quarantine", "value", "outcome", "accuracy")
    for name, fn in inspect.getmembers(synthesis, inspect.isfunction):
        if fn.__module__ == synthesis.__name__:
            assert not any(b in p for p in inspect.signature(fn).parameters for b in banned), name


# -- execution boundary -----------------------------------------------------------------------------


def test_described_execution_is_recorded_and_never_verified():
    ran = go({"extract": {**ext(), "execution": "EXECUTION_DESCRIBED"}})
    planned = go({"extract": {**ext(), "execution": "PLANNED_ONLY"}})
    exp = exp0(ran)
    assert exp.execution_status is ExecutionStatus.EXECUTION_DESCRIBED
    assert (exp.execution_verified, exp.independently_reproduced, exp.leakage_prevented_in_practice) == (
        False, False, False)
    assert ran.execution_verified is False and ran.execution_boundary == "EXECUTION_DESCRIBED_IS_NOT_EXECUTION_VERIFIED"
    assert exp.posture is exp0(planned).posture and ran.project_posture is planned.project_posture


# -- baseline / comparator --------------------------------------------------------------------------


IMPROVEMENT = {"BASELINE": {"fired": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "excerpts": [P_DEFINE]},
               "BASELINE_CONFIGURATION": {"fired": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "excerpts": [P_DEFINE]}}


def test_improvement_claim_without_a_baseline_is_a_major_gap():
    run = go({"applicability": IMPROVEMENT})
    assert req(run, K.BASELINE).applicability is Applicability.REQUIRED
    assert "BASELINE_MISSING_WHEN_REQUIRED" in exp0(run).issues and exp0(run).posture is P.MAJOR_GAPS


def _baseline_run(baseline: dict, **comparability) -> ExperimentReviewRun:
    script = {"extract": ext(BASELINE={"excerpts": [P_BASE]}, BASELINE_CONFIGURATION={"excerpts": [P_BASE]}),
              "applicability": IMPROVEMENT,
              "link": link_with(T1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE], "measurement": measured(),
                                    "baseline": baseline})}
    return go(script, WITH_BASE)


def test_baseline_name_alone_is_not_relevance_and_never_fair():
    run = _baseline_run({"excerpts": [P_BASE], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"})
    record = run.baselines[0]
    assert record.relevance is BaselineRelevance.RELEVANCE_UNRESOLVED
    family = TYPE_FAMILY[exp0(run).experiment_type]
    assert record.rollup(family) is ComparabilityRollup.COMPARABILITY_NOT_ESTABLISHED
    assert "FAIR" not in {r.value for r in ComparabilityRollup}
    assert not [f for f in ExperimentBaselineRecord.model_fields if "fair" in f]
    assert record.execution_verified is False and record.comparison_result_evaluated is False


def test_relevant_baseline_and_per_property_comparability():
    run = _baseline_run({"excerpts": [P_BASE], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                         "context": ["TARGET_CLAIM_TEXT"],
                         "comparability": {"SAME_HARDWARE": ("DOCUMENTED_DIFFERENT", [P_BASE]),
                                           "SAME_INPUT_SET": ("NOT_APPLICABLE", [])}})
    record = run.baselines[0]
    assert record.relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT
    props = {p.property: p for p in record.comparability}
    assert props[FairnessProperty.SAME_INPUT_SET].status is FairnessPropertyStatus.UNRESOLVED  # never the model's NA
    assert "BASELINE_COMPARABILITY_GAP" in exp0(run).issues


def test_only_same_metric_is_deterministic_and_only_through_the_aligned_binding():
    run = _baseline_run({"excerpts": [P_BASE], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                         "context": ["TARGET_CLAIM_TEXT"],
                         "comparability": {"SAME_ENVIRONMENT": ("DOCUMENTED_SAME", [P_BASE])}})
    props = {p.property: p for p in run.baselines[0].comparability}
    metric = props[FairnessProperty.SAME_EVALUATION_METRIC]
    assert metric.basis is FairnessBasis.DETERMINISTIC_SHARED_METRIC_BINDING
    assert all(p.basis is not FairnessBasis.DETERMINISTIC_SHARED_METRIC_BINDING
               for prop, p in props.items() if prop is not FairnessProperty.SAME_EVALUATION_METRIC)
    unaligned = _baseline_run({"excerpts": [P_BASE]}).baselines[0]
    assert unaligned.comparability[0].basis is FairnessBasis.DETERMINISTIC_SHARED_METRIC_BINDING
    no_measure = go({"extract": ext(BASELINE={"excerpts": [P_BASE]}), "applicability": IMPROVEMENT,
                     "link": link_with(T1={"relation": "PARTIALLY_TESTS", "excerpts": [P_DEFINE],
                                           "baseline": {"excerpts": [P_BASE]}})}, WITH_BASE)
    assert no_measure.baselines[0].comparability == []


# -- measurement / metric ---------------------------------------------------------------------------


def test_metric_without_method_is_not_alignment_and_cannot_directly_test():
    run = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE],
                                    "measurement": measured(method=None)})})
    v1 = next(m for m in run.measurements if m.validation_requirement_id is not None)
    assert v1.alignment is MetricTargetAlignment.MEASUREMENT_METHOD_NOT_DEFINED
    link = next(lk for lk in run.links if lk.validation_requirement_id is not None)
    assert link.relation is TargetRelation.PARTIALLY_TESTS
    cov = run.phase2j_coverage[0]
    assert cov.status is CoverageStatus.PARTIALLY_COVERED and ContinuityReason.METRIC_TARGET_MISMATCH in cov.reasons


def test_a_metric_aligned_for_one_target_never_carries_another():
    run = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE]})})
    v1 = next(lk for lk in run.links if lk.validation_requirement_id is not None)
    assert v1.relation is TargetRelation.PARTIALLY_TESTS
    assert run.phase2j_coverage[0].status is not CoverageStatus.COVERED_BY_EXPERIMENT
    mismatch = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE],
                                         "measurement": measured(alignment="METRIC_TARGET_MISMATCH")})})
    assert "METRIC_TARGET_MISMATCH" in exp0(mismatch).issues and exp0(mismatch).posture is P.MAJOR_GAPS


def test_another_experiments_metric_cannot_be_cited():
    script = {"segment": {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]}],
                          "results": [{"kind": "REPORTED_METRIC_VALUE", "span": RESULT}]},
              "extract": {"Experiment 2": {"type": "ENGINEERING_FIELD_TEST",
                                           "requirements": {"OBJECTIVE": {"excerpts": [P2_DEFINE]}}}},
              "link": {"Experiment 2": link_with()}}
    run = go(script, MULTI)
    second = next(e for e in run.experiments if e.protocol_key == protocol_key([P2_DEFINE]))
    own = [lk for lk in run.links if lk.experiment_id == second.experiment_id]
    assert all(lk.relation is not TargetRelation.DIRECTLY_TESTS for lk in own)
    assert not [m for m in run.measurements if m.experiment_id == second.experiment_id and m.metric_excerpt_id]
    assert second.experiment_id not in run.phase2j_coverage[0].covering_experiment_ids


def test_success_criterion_timing():
    pre = go({})
    assert all(m.success_criterion_timing is SuccessCriterionTiming.PRE_SPECIFIED_AS_DESCRIBED for m in pre.measurements)
    post = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE],
                                     "measurement": measured(timing="POST_HOC_AS_DESCRIBED")})})
    assert "SUCCESS_CRITERION_POST_HOC" in exp0(post).issues and exp0(post).posture is P.MAJOR_GAPS
    assert ContinuityReason.COVERING_PROTOCOL_INADEQUATE in post.phase2j_coverage[0].reasons
    none = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE],
                                     "measurement": measured(criterion=None, timing="POST_HOC_AS_DESCRIBED")})})
    assert all(m.success_criterion_timing is not SuccessCriterionTiming.POST_HOC_AS_DESCRIBED for m in none.measurements)


# -- sample / repetitions -------------------------------------------------------------------------------


BARE = "N = 500"
WITH_N = SUBMISSION.replace(RESULT, f"Sample size: {BARE}. {RESULT}")


def test_bare_quantity_is_never_adequate_and_never_a_rationale():
    script = {"extract": ext("SCIENTIFIC_CONTROLLED_EXPERIMENT", SAMPLE_SIZE={"excerpts": [BARE]},
                             SAMPLE_SIZE_RATIONALE={"excerpts": [BARE]}),
              "applicability": {"SAMPLE_SIZE_RATIONALE": {"fired": ["STATISTICAL_INFERENCE_CLAIMED"],
                                                          "excerpts": [P_DEFINE]}}}
    run = go(script, WITH_N)
    assert req(run, K.SAMPLE_SIZE).adequacy is ProtocolAdequacy.PARTIALLY_SPECIFIED
    rationale = req(run, K.SAMPLE_SIZE_RATIONALE)
    assert rationale.applicability is Applicability.REQUIRED
    assert rationale.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    assert exp0(run).posture is not P.WELL_SPECIFIED


def test_a_worded_rationale_is_accepted_and_small_is_not_rejected():
    rationale = "Twelve trays are enough because each one covers a separate band of the sensor range."
    script = {"extract": ext("SCIENTIFIC_CONTROLLED_EXPERIMENT", SAMPLE_SIZE_RATIONALE={"excerpts": [rationale]}),
              "applicability": {"SAMPLE_SIZE_RATIONALE": {"fired": ["SAMPLED_POPULATION"], "excerpts": [P_SAMPLE]}}}
    run = go(script, SUBMISSION.replace(RESULT, f"{rationale} {RESULT}"))
    assert req(run, K.SAMPLE_SIZE_RATIONALE).documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED


def test_repeated_measurement_is_not_independent_replication():
    script = {"applicability": {"REPETITION_INDEPENDENCE": {"fired": ["REPLICATION_RELIED_ON"],
                                                            "excerpts": [P_REPEAT]}}}
    run = go(script)
    assert req(run, K.REPETITIONS).documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED
    independence = req(run, K.REPETITION_INDEPENDENCE)
    assert independence.applicability is Applicability.REQUIRED
    assert independence.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    assert "REPETITIONS_MISSING_WHEN_REQUIRED" in exp0(run).issues
    replicated = go({**script, "extract": ext(REPETITION_INDEPENDENCE={"excerpts": [P_REPEAT]})})
    assert "REPETITIONS_MISSING_WHEN_REQUIRED" not in exp0(replicated).issues


# -- statistics --------------------------------------------------------------------------------------


STATS = (K.STATISTICAL_TEST, K.TEST_ASSUMPTIONS, K.CONFIDENCE_INTERVAL, K.EFFECT_SIZE)


def test_statistics_are_not_applicable_without_a_trigger():
    run = go({})
    assert all(req(run, k).applicability is Applicability.NOT_APPLICABLE for k in STATS)
    assert exp0(run).posture is P.WELL_SPECIFIED


def test_claimed_inference_requires_statistics_and_a_missing_one_is_a_gap():
    fired = {k.value: {"fired": ["STATISTICAL_INFERENCE_CLAIMED"], "excerpts": [P_DEFINE]} for k in STATS}
    run = go({"applicability": fired})
    assert all(req(run, k).applicability is Applicability.REQUIRED for k in STATS)
    assert "STATISTICS_MISSING_WHEN_REQUIRED" in exp0(run).issues
    assert exp0(run).posture is P.PARTIALLY_SPECIFIED


def test_missing_uncertainty_where_applicable_and_an_inappropriate_test():
    run = go({"applicability": {"MEASUREMENT_UNCERTAINTY": {"fired": ["QUANTITATIVE_MEASUREMENT"],
                                                            "excerpts": [P_METHOD]}}})
    assert "ERROR_SOURCES_MISSING_WHEN_REQUIRED" in exp0(run).issues
    risky = go({"extract": ext(STATISTICAL_TEST={"excerpts": [P_METHOD], "adequacy": "PROTOCOL_RISK_IDENTIFIED"}),
                "applicability": {"STATISTICAL_TEST": {"fired": ["STATISTICAL_INFERENCE_CLAIMED"],
                                                       "excerpts": [P_METHOD]}}})
    assert "PROTOCOL_RISK_IDENTIFIED" in exp0(risky).issues


def test_software_benchmark_requires_workload_warm_up_and_repetitions():
    run = go({"extract": ext("SOFTWARE_BENCHMARK")})
    for kind in (K.WORKLOAD, K.WARM_UP, K.REPETITIONS):
        assert req(run, kind).applicability is Applicability.REQUIRED


# -- linkage ---------------------------------------------------------------------------------------


def _relation(rel: str) -> ExperimentReviewRun:
    return go({"link": {"targets": {"T1": {"relation": rel, "excerpts": [P_DEFINE]},
                                    "V1": {"relation": rel, "excerpts": [P_DEFINE]}}}})


def test_partial_supporting_does_not_test_and_unresolved_relations():
    partial = _relation("PARTIALLY_TESTS")
    assert partial.phase2j_coverage[0].status is CoverageStatus.PARTIALLY_COVERED
    supporting = _relation("SUPPORTING_VALIDATION")
    assert supporting.phase2j_coverage[0].status is CoverageStatus.NOT_COVERED
    assert supporting.untested_claim_ids == ["C-001"] and supporting.project_posture is P.MAJOR_GAPS
    off = _relation("DOES_NOT_TEST")
    assert "EXPERIMENT_DOES_NOT_TEST_TARGET" in exp0(off).issues and exp0(off).posture is P.PARTIALLY_SPECIFIED
    assert off.phase2j_coverage[0].status is CoverageStatus.NOT_COVERED
    unresolved = _relation("UNRESOLVED")
    assert unresolved.phase2j_coverage[0].status is CoverageStatus.UNRESOLVED


def test_a_testing_relation_without_cited_protocol_is_unresolved():
    run = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "measurement": measured()})})
    assert next(lk for lk in run.links if lk.validation_requirement_id).relation is TargetRelation.UNRESOLVED


# -- Phase 2J continuity ------------------------------------------------------------------------------


def test_full_coverage_by_one_experiment():
    run = go({})
    cov = run.phase2j_coverage[0]
    assert cov.status is CoverageStatus.COVERED_BY_EXPERIMENT and cov.covering_experiment_ids == [
        exp0(run).experiment_id]
    assert cov.result_success_evaluated is False


def test_metric_and_condition_mismatch_are_partial():
    metric = go({"link": link_with(V1={"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE],
                                       "measurement": measured(match="DIFFERENT_FROM_PHASE_2J")})})
    assert ContinuityReason.METRIC_TARGET_MISMATCH in metric.phase2j_coverage[0].reasons
    cond = go({"link": {**well_link(), "conditions": {"K1": {"status": "NOT_ADDRESSED_IN_BOUND_INPUT"}}}})
    assert cond.phase2j_coverage[0].reasons == [ContinuityReason.MATERIAL_CONDITION_UNCOVERED]


def test_absent_coverage_and_a_hypothesis_without_requirement():
    absent = go({"link": {"targets": {"T1": {"relation": "DOES_NOT_TEST"}, "V1": {"relation": "DOES_NOT_TEST"}}}})
    assert absent.phase2j_coverage[0].reasons == [ContinuityReason.PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED]
    none = go({"link": {"targets": {"T1": well_link()["targets"]["T1"]}}}, gap_variant="no_requirement")
    assert none.bound_validation_targets == [] and none.phase2j_coverage == []


def _baseline_link(metric_match: str, baseline_match: str | None, *, condition: bool = True,
                   cite: str = P_DEFINE) -> dict:
    v1 = {"relation": "DIRECTLY_TESTS", "excerpts": [cite], "measurement": measured(match=metric_match)}
    if baseline_match is not None:
        v1["baseline"] = {"excerpts": [P_BASE], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                          "context": ["PHASE_2J_VALIDATION_BASELINE"], "match": baseline_match}
    out = link_with(V1=v1)
    if not condition:
        out["conditions"] = {}
    return out


BASELINE_EXTRACT = ext(BASELINE={"excerpts": [P_BASE]}, BASELINE_CONFIGURATION={"excerpts": [P_BASE]})


def test_phase_2j_baseline_is_required_and_matched():
    run = go({"extract": BASELINE_EXTRACT, "link": _baseline_link("SAME_AS_PHASE_2J", "SAME_AS_PHASE_2J")},
             WITH_BASE, gap_variant="baseline")
    assert req(run, K.BASELINE).basis is ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT
    assert run.phase2j_coverage[0].status is CoverageStatus.COVERED_BY_EXPERIMENT
    mismatch = go({"extract": BASELINE_EXTRACT, "link": _baseline_link("SAME_AS_PHASE_2J", "DIFFERENT_FROM_PHASE_2J")},
                  WITH_BASE, gap_variant="baseline")
    assert mismatch.phase2j_coverage[0].reasons == [ContinuityReason.BASELINE_TARGET_MISMATCH]


def test_mosaic_coverage_across_experiments_is_never_covered():
    script = {
        "segment": {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]}],
                    "results": [{"kind": "REPORTED_METRIC_VALUE", "span": RESULT}]},
        "extract": {"*": BASELINE_EXTRACT},
        "link": {"Experiment 1": _baseline_link("SAME_AS_PHASE_2J", None),                    # metric + condition only
                 "Experiment 2": _baseline_link("DIFFERENT_FROM_PHASE_2J", "SAME_AS_PHASE_2J",  # baseline only
                                                condition=False, cite=P2_DEFINE)},
    }
    run = go(script, MULTI, gap_variant="baseline")
    cov = run.phase2j_coverage[0]
    assert len(cov.attempting_experiment_ids) == 2 and cov.covering_experiment_ids == []
    assert cov.status is CoverageStatus.PARTIALLY_COVERED
    assert {ContinuityReason.BASELINE_TARGET_MISMATCH, ContinuityReason.METRIC_TARGET_MISMATCH} <= set(cov.reasons)
    assert run.project_posture is not P.WELL_SPECIFIED


# -- HYBRID ownership ----------------------------------------------------------------------------------


HY = ProjectType.HYBRID


def test_single_track_ownership_is_deterministic():
    run = go({})
    assert exp0(run).ownership_basis is TrackOwnershipBasis.SINGLE_TRACK_PROJECT
    assert exp0(run).track is MethodologyTrack.ENGINEERING


def _hybrid(x2_extract: dict, x2_link: dict | None = None) -> ExperimentReviewRun:
    script = {"segment": {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}, {"label": "X2", "excerpts": [P2_DEFINE]}],
                          "results": [{"kind": "REPORTED_METRIC_VALUE", "span": RESULT}]},
              "extract": {"Experiment 2": x2_extract},
              "link": {"Experiment 2": x2_link or {"targets": {"T1": {"relation": "PARTIALLY_TESTS",
                                                                      "excerpts": [P2_DEFINE]},
                                                               "V1": {"relation": "DOES_NOT_TEST"}}}}}
    return go(script, MULTI, project_type=HY)


def _by_text(run: ExperimentReviewRun, text: str):
    return next(e for e in run.experiments if e.protocol_key == protocol_key([text]))


def test_hybrid_facet_model_and_unresolved_ownership_without_double_counting():
    run = _hybrid({**ext(), "owner": "SCIENTIFIC_RESEARCH", "owner_excerpts": [P2_DEFINE]})
    first, second = _by_text(run, P_DEFINE), _by_text(run, P2_DEFINE)
    assert first.ownership_basis is TrackOwnershipBasis.PHASE_2J_LIMITATION_FACET
    assert first.track is MethodologyTrack.ENGINEERING
    assert second.ownership_basis is TrackOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT
    assert second.track is MethodologyTrack.SCIENTIFIC_RESEARCH
    owned = [x for t in run.track_postures for x in t.experiment_ids]
    assert sorted(owned, key=str) == sorted([first.experiment_id, second.experiment_id], key=str)
    unresolved = _hybrid(ext())
    orphan = _by_text(unresolved, P2_DEFINE)
    assert orphan.track is None and orphan.ownership_basis is TrackOwnershipBasis.UNRESOLVED
    assert all(orphan.experiment_id not in t.experiment_ids for t in unresolved.track_postures)
    assert unresolved.project_posture in (P.UNRESOLVED, P.MAJOR_GAPS, P.INSUFFICIENT_EVIDENCE)


def test_a_strong_track_never_hides_a_weak_one():
    run = _hybrid({**ext(missing=("OBJECTIVE", "HYPOTHESIS_OR_VALIDATION_OBJECTIVE")), "owner": "SCIENTIFIC_RESEARCH",
                   "owner_excerpts": [P2_DEFINE]})
    tracks = {t.track: t.posture for t in run.track_postures}
    assert _by_text(run, P_DEFINE).posture is P.WELL_SPECIFIED
    assert tracks[MethodologyTrack.SCIENTIFIC_RESEARCH] is P.MAJOR_GAPS
    assert run.project_posture is P.MAJOR_GAPS


def test_conditions_are_anchored_to_this_experiments_own_excerpts():
    run = go({})
    cond = run.conditions[0]
    texts = {e.excerpt_id: e.excerpt for e in run.excerpts}
    assert [texts[i] for i in cond.excerpt_ids] == [P_CONDITION]
    assert P_CRITERION in texts.values()
