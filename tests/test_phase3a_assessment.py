"""Phase 3A production: documentation vs adequacy, target linkage, Phase 2J continuity, baseline, metric,
condition coverage, sample/control boundaries, AI/ML design risk and the result-leakage barrier."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.schemas.common import ProjectType, TechnicalDomain
from src.schemas.methodology_review import (
    BaselineRelevance,
    BaselineRelevanceContext,
    ConditionCoverageStatus,
    CoverageRelation,
    DesignAdequacy,
    DocumentationStatus,
    MethodologyIssueCode,
    MethodologyPosture,
    MethodologyRunIssueCode,
    MetricAlignmentStatus,
    MetricSource,
    RequirementKind,
    StatementMode,
)
from src.schemas.project import ExperimentRecord, ResultRecord
from tests.phase3a_support import (
    ENGINEERING_TEXT,
    S_ACCEPTANCE,
    S_MEASUREMENT,
    S_OBJECTIVE,
    S_VERIFICATION,
    ScriptedMethodologyModel,
    edited,
    run_stages,
    well_engineering_script,
    world,
)

K = RequirementKind
ML = (TechnicalDomain.MACHINE_LEARNING,)
WELL = MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
PARTIAL = MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED
MAJOR = MethodologyPosture.METHODOLOGY_HAS_MAJOR_DESIGN_GAPS
CONFLICTING = MethodologyPosture.METHODOLOGY_CONFLICTING


def go(script, state=None, **kw):
    model = ScriptedMethodologyModel(script)
    run = run_stages(state or world(), model.provider(), **kw)
    return run, model


def codes(run):
    return {i.code for ta in run.track_assessments for i in ta.issues}


def doc(run, kind):
    return next(d for ta in run.track_assessments for d in ta.documentation if d.kind is kind)


def link(run, *, gap):
    return next(c for ta in run.track_assessments for c in ta.coverage if (c.gap_hypothesis_id is not None) == gap)


# -- documentation vs adequacy ----------------------------------------------------------------------------


def test_documented_is_not_the_same_as_adequate():
    script = well_engineering_script()
    script["evidence"]["VERIFICATION_PLAN"] = {
        "documentation": "PARTIALLY_DOCUMENTED", "adequacy": "DESIGN_RISK_IDENTIFIED", "excerpts": [S_VERIFICATION]}
    run, _ = go(script)
    d = doc(run, K.VERIFICATION_PLAN)
    assert d.documentation is DocumentationStatus.PARTIALLY_DOCUMENTED and d.adequacy is DesignAdequacy.DESIGN_RISK_IDENTIFIED
    assert run.track_assessments[0].posture is PARTIAL


def test_not_documented_in_the_bound_input_is_bounded_and_never_says_the_student_did_not_do_it():
    script = well_engineering_script()
    del script["evidence"]["MEASUREMENT_PLAN"]
    run, _ = go(script)
    d = doc(run, K.MEASUREMENT_PLAN)
    assert d.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT and not d.excerpt_ids
    assert d.adequacy is DesignAdequacy.INSUFFICIENT_EVIDENCE_TO_ASSESS
    assert run.not_documented_meaning == "NOT_DOCUMENTED_IN_BOUND_INPUT_IS_NOT_EVIDENCE_OF_NON_PERFORMANCE"
    assert MethodologyIssueCode.REQUIRED_COMPONENT_NOT_DOCUMENTED in codes(run)
    assert run.track_assessments[0].posture is MAJOR


def test_conflicting_documentation_cites_both_sides_and_makes_the_track_conflicting():
    script = well_engineering_script()
    script["evidence"]["ACCEPTANCE_CRITERIA"] = {
        "documentation": "CONFLICTING_DOCUMENTATION", "adequacy": "CONFLICTING_DESIGN",
        "excerpts": [S_ACCEPTANCE, S_MEASUREMENT]}
    run, _ = go(script)
    d = doc(run, K.ACCEPTANCE_CRITERIA)
    assert d.documentation is DocumentationStatus.CONFLICTING_DOCUMENTATION and len(d.excerpt_ids) == 2
    assert MethodologyIssueCode.CONFLICTING_METHOD_DESCRIPTION in codes(run)
    assert run.track_assessments[0].posture is CONFLICTING


def test_conflict_with_one_excerpt_is_only_partial_documentation():
    script = well_engineering_script()
    script["evidence"]["ACCEPTANCE_CRITERIA"] = {
        "documentation": "CONFLICTING_DOCUMENTATION", "adequacy": "CONFLICTING_DESIGN", "excerpts": [S_ACCEPTANCE]}
    run, _ = go(script)
    assert doc(run, K.ACCEPTANCE_CRITERIA).documentation is DocumentationStatus.PARTIALLY_DOCUMENTED


def test_an_adequacy_the_documentation_cannot_reach_is_replaced_by_the_conservative_one():
    script = well_engineering_script()
    script["evidence"]["ACCEPTANCE_CRITERIA"] = {
        "documentation": "PARTIALLY_DOCUMENTED", "adequacy": "ADEQUATELY_SPECIFIED_FOR_REVIEW",
        "excerpts": [S_ACCEPTANCE]}
    run, _ = go(script)
    assert doc(run, K.ACCEPTANCE_CRITERIA).adequacy is DesignAdequacy.PARTIALLY_SPECIFIED
    assert run.track_assessments[0].posture is PARTIAL


def test_a_submission_longer_than_the_bound_reports_insufficient_coverage_not_absence():
    from src.schemas.methodology_review import MethodologyReviewBounds

    long_text = ENGINEERING_TEXT + " " + ("Filler sentence that documents nothing. " * 60)
    script = well_engineering_script()
    del script["evidence"]["MEASUREMENT_PLAN"]
    run, _ = go(script, world(text=long_text), bounds=MethodologyReviewBounds(max_submission_chars=1_000))
    assert run.draft.source_truncated
    assert doc(run, K.MEASUREMENT_PLAN).documentation is DocumentationStatus.INSUFFICIENT_SOURCE_COVERAGE
    assert MethodologyIssueCode.REQUIRED_COMPONENT_NOT_DOCUMENTED not in codes(run)


def test_a_student_execution_statement_is_captured_but_never_verified():
    script = well_engineering_script()
    script["evidence"]["VERIFICATION_PLAN"] = {"excerpts": [S_VERIFICATION], "mode": "DESCRIBED_AS_EXECUTED"}
    run, _ = go(script)
    modes = {e.statement_mode for e in run.excerpts if e.excerpt == S_VERIFICATION}
    assert modes == {StatementMode.DESCRIBED_AS_EXECUTED}
    assert all(e.execution_verified is False for e in run.excerpts)
    (ta,) = run.track_assessments
    assert ta.execution_verified is False and ta.confounding_eliminated is False
    assert ta.leakage_prevented_in_practice is False


# -- claim and gap linkage -------------------------------------------------------------------------------


def test_valid_semantic_direct_coverage_is_recorded_as_a_bounded_judgment():
    run, _ = go(well_engineering_script())
    claim_link, gap_link = link(run, gap=False), link(run, gap=True)
    assert claim_link.relation is gap_link.relation is CoverageRelation.DIRECTLY_TESTS_TARGET
    assert claim_link.judgment_basis == "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    assert K.VALIDATION_PLAN in claim_link.requirement_kinds


def test_partial_coverage_is_not_a_well_specified_track():
    script = well_engineering_script()
    script["link"]["T1"]["ENGINEERING"]["relation"] = "PARTIALLY_TESTS_TARGET"
    run, _ = go(script)
    assert link(run, gap=False).relation is CoverageRelation.PARTIALLY_TESTS_TARGET
    assert run.track_assessments[0].posture is PARTIAL


def test_a_structurally_valid_link_to_unrelated_methodology_cannot_carry_strong_coverage():
    script = well_engineering_script()
    script["link"]["T1"]["ENGINEERING"] = {"relation": "DIRECTLY_TESTS_TARGET", "excerpts": [S_OBJECTIVE]}
    run, _ = go(script)
    c = link(run, gap=False)
    assert c.relation is CoverageRelation.PARTIALLY_TESTS_TARGET, "a design objective does not test anything"
    assert run.track_assessments[0].posture is PARTIAL


def test_insufficient_semantic_linkage_is_never_strong():
    script = well_engineering_script()
    script["link"]["T1"]["ENGINEERING"] = {"relation": "INSUFFICIENT_LINKAGE_EVIDENCE", "excerpts": []}
    run, _ = go(script)
    assert link(run, gap=False).relation is CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE
    assert run.track_assessments[0].posture is PARTIAL


def test_a_testing_relation_that_cites_no_real_excerpt_degrades_to_insufficient():
    script = well_engineering_script()
    script["link"]["T1"]["ENGINEERING"] = {"relation": "DIRECTLY_TESTS_TARGET", "excerpts": ["E999"]}
    run, _ = go(script)
    assert link(run, gap=False).relation is CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE
    assert any(e.code is MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT for e in run.errors)


def test_a_judgment_about_a_nonexistent_claim_or_gap_is_rejected_and_the_target_is_unjudged():
    script = well_engineering_script()
    script["link"] = {"T9": script["link"]["T1"], "G9": script["link"]["G1"]}
    run, _ = go(script)
    assert all(c.relation is CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE
               for ta in run.track_assessments for c in ta.coverage)
    assert run.draft.unjudged_targets, "no judgment, no finding: neither positive nor negative"
    assert MethodologyIssueCode.CLAIM_METHOD_MISMATCH not in codes(run)
    assert run.track_assessments[0].posture is PARTIAL


def test_a_method_that_does_not_test_the_target_is_a_typed_mismatch_issue():
    script = well_engineering_script()
    script["link"]["T1"]["ENGINEERING"] = {"relation": "DOES_NOT_TEST_TARGET", "excerpts": []}
    script["link"]["G1"]["ENGINEERING"] = {"relation": "RELEVANT_BUT_NOT_TESTING", "excerpts": []}
    run, _ = go(script)
    assert {MethodologyIssueCode.CLAIM_METHOD_MISMATCH, MethodologyIssueCode.GAP_METHOD_MISMATCH} <= codes(run)
    assert run.track_assessments[0].posture is MAJOR


# -- Phase 2J validation continuity -----------------------------------------------------------------------


def test_the_bound_target_mirrors_the_phase_2j_requirement_and_the_metric_is_enforced():
    run, _ = go(well_engineering_script())
    (target,) = run.bound_gap_targets
    assert target.requires_metric and not target.requires_baseline and len(target.material_condition_ids) == 1
    script = well_engineering_script()
    script["metric"]["G1"] = {"status": "METRIC_NOT_DEFINED"}
    run, _ = go(script)
    assert link(run, gap=True).relation is CoverageRelation.PARTIALLY_TESTS_TARGET, "a bare requirement id is not enough"
    assert MethodologyIssueCode.METRIC_NOT_DEFINED in codes(run) and run.track_assessments[0].posture is MAJOR


def test_a_baseline_is_a_prerequisite_only_when_the_phase_2j_requirement_has_one():
    run, _ = go(well_engineering_script())
    assert not run.baselines and run.track_assessments[0].posture is WELL


S_BASELINE = "The comparator is the existing timer controller already installed on site."
S_BOTH = "We compare against the installed timer controller because it is the standard on this farm."
BASELINE_TEXT = ENGINEERING_TEXT + " " + S_BASELINE + " " + S_BOTH


def baseline_script(**baseline):
    script = well_engineering_script()
    script["applicability"].pop("BASELINE_OR_ALTERNATIVE_DESIGN")  # the Phase 2J baseline already requires it
    script["evidence"]["BASELINE_OR_ALTERNATIVE_DESIGN"] = {"excerpts": [S_BASELINE]}
    if baseline:
        script["baseline"] = {"G1": baseline}
    return script


def test_a_phase_2j_baseline_requires_a_documented_relevant_baseline_for_strong_coverage():
    state = world(text=BASELINE_TEXT, gap_variant="baseline")
    (target,) = go(baseline_script(), state)[0].bound_gap_targets
    assert target.requires_baseline
    missing, _ = go(baseline_script(), state)
    (b,) = missing.baselines
    assert b.relevance is BaselineRelevance.NO_BASELINE_DOCUMENTED and b.gap_validation_requirement_id
    assert MethodologyIssueCode.BASELINE_NOT_DOCUMENTED in codes(missing)
    assert link(missing, gap=True).relation is CoverageRelation.PARTIALLY_TESTS_TARGET
    good, _ = go(baseline_script(baseline=S_BASELINE, relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                 context=["PHASE_2J_VALIDATION_BASELINE"]), state)
    (b,) = good.baselines
    assert b.relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT and not b.rationale_documented
    assert link(good, gap=True).relation is CoverageRelation.DIRECTLY_TESTS_TARGET
    assert b.comparison_fairness_assessed is False


def test_a_baseline_name_alone_is_never_relevance():
    state = world(text=BASELINE_TEXT, gap_variant="baseline")
    run, _ = go(baseline_script(baseline=S_BASELINE, relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", context=[]), state)
    (b,) = run.baselines
    assert b.relevance is BaselineRelevance.RELEVANCE_UNRESOLVED
    assert MethodologyIssueCode.BASELINE_RELEVANCE_UNRESOLVED in codes(run)
    assert link(run, gap=True).relation is CoverageRelation.PARTIALLY_TESTS_TARGET
    # a context the target does not have is not accepted either
    state2 = world(text=BASELINE_TEXT)  # default variant: the requirement has no baseline
    run2, _ = go(edited(well_engineering_script(), baseline={"T1": {
        "baseline": S_BASELINE, "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
        "context": ["PHASE_2J_VALIDATION_BASELINE"]}}), state2)
    claim_baseline = next(b for b in run2.baselines if b.gap_validation_requirement_id is None)
    assert claim_baseline.relevance is BaselineRelevance.RELEVANCE_UNRESOLVED


def test_the_rationale_is_optional_never_fabricated_and_may_share_the_baseline_excerpt():
    state = world(text=BASELINE_TEXT, gap_variant="baseline")
    base = dict(baseline=S_BASELINE, relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                context=["PHASE_2J_VALIDATION_BASELINE"])
    run, _ = go(baseline_script(**base), state)
    assert run.baselines[0].rationale_excerpt_ids == []
    fake, _ = go(baseline_script(**base, rationale="a rationale the student never wrote"), state)
    assert fake.baselines[0].rationale_excerpt_ids == [], "a fabricated rationale is rejected, not recorded"
    both, _ = go(baseline_script(baseline=S_BOTH, relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                 context=["PHASE_2J_VALIDATION_BASELINE"], rationale=S_BOTH), state)
    (b,) = both.baselines
    assert b.baseline_excerpt_ids == b.rationale_excerpt_ids and b.rationale_documented
    assert BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT in b.relevance_context


def test_an_empty_material_condition_list_is_accepted_and_adds_no_prerequisite():
    run, _ = go(edited(well_engineering_script(), conditions={}), world(gap_variant="no_condition"))
    (target,) = run.bound_gap_targets
    assert target.material_condition_ids == [] and run.draft.conditions == []
    assert run.track_assessments[0].posture is WELL


def test_material_conditions_are_exactly_the_phase_2j_ids_and_an_uncovered_one_blocks():
    run, _ = go(well_engineering_script())
    (target,) = run.bound_gap_targets
    assert [c.condition_id for c in run.draft.conditions] == target.material_condition_ids
    script = well_engineering_script()
    script["conditions"] = {"G1:1": {"status": "NOT_ADDRESSED_IN_BOUND_INPUT", "excerpts": []}}
    run, _ = go(script)
    assert run.draft.conditions[0].status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT
    assert MethodologyIssueCode.MATERIAL_CONDITION_NOT_COVERED in codes(run)
    assert link(run, gap=True).relation is CoverageRelation.PARTIALLY_TESTS_TARGET
    assert run.track_assessments[0].posture is MAJOR
    claimed = edited(well_engineering_script(), conditions={"G1:1": {"status": "ADDRESSED_IN_DESIGN", "excerpts": []}})
    run, _ = go(claimed)
    assert run.draft.conditions[0].status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT, (
        "'addressed' without an exact excerpt is not accepted")


def test_without_a_phase_2j_validation_requirement_phase_3a_invents_no_validation_dimension():
    run, model = go(edited(well_engineering_script(), conditions={}), world(gap_variant="no_requirement"))
    (target,) = run.bound_gap_targets
    assert not (target.requires_metric or target.requires_baseline or target.material_condition_ids)
    assert [m.gap_validation_requirement_id for m in run.metric_alignments] == [None], "only the claim-level plan"
    assert not run.baselines and not run.draft.conditions
    assert not {MethodologyIssueCode.METRIC_NOT_DEFINED, MethodologyIssueCode.BASELINE_NOT_DOCUMENTED,
                MethodologyIssueCode.MATERIAL_CONDITION_NOT_COVERED} & codes(run)
    metric_call = next(u for t, u in model.calls if t.value == "METHODOLOGY_METRIC_BASELINE")
    assert "[G1]" not in metric_call


# -- metrics ------------------------------------------------------------------------------------------------


def test_a_student_metric_is_an_exact_anchor_and_a_phase_2j_metric_is_a_reference():
    run, _ = go(well_engineering_script())
    by_req = {m.gap_validation_requirement_id: m for m in run.metric_alignments}
    claim_metric, gap_metric = by_req[None], by_req[run.bound_gap_targets[0].validation_requirement_id]
    assert claim_metric.metric_source is MetricSource.STUDENT_EXCERPT and claim_metric.metric_excerpt_id
    excerpt = next(e for e in run.excerpts if e.excerpt_id == claim_metric.metric_excerpt_id)
    assert excerpt.excerpt == "moisture accuracy and water use"
    assert gap_metric.metric_source is MetricSource.PHASE_2J_VALIDATION_ANCHOR and gap_metric.metric_excerpt_id is None


def test_a_metric_that_does_not_measure_the_target_is_a_typed_mismatch_issue():
    script = well_engineering_script()
    script["metric"]["T1"] = {"status": "METRIC_TARGET_MISMATCH", "outcome": S_MEASUREMENT, "metric": "water use"}
    run, _ = go(script)
    assert MethodologyIssueCode.METRIC_TARGET_MISMATCH in codes(run)
    unbound = edited(well_engineering_script())
    unbound["metric"]["T1"] = {"status": "METRIC_TARGET_MISMATCH", "outcome": S_MEASUREMENT}
    run, _ = go(unbound)
    assert {m.status for m in run.metric_alignments if m.gap_validation_requirement_id is None} == {
        MetricAlignmentStatus.METRIC_NOT_DEFINED}, "a mismatch needs a real student metric to mismatch"


def test_a_vague_claim_gets_no_invented_metric():
    script = well_engineering_script()
    script["metric"]["T1"] = {"status": "TARGET_NOT_MEASURABLE_AS_STATED"}
    run, _ = go(script)
    (m,) = [m for m in run.metric_alignments if m.gap_validation_requirement_id is None]
    assert m.status is MetricAlignmentStatus.TARGET_NOT_MEASURABLE_AS_STATED and m.metric_source is None
    assert MethodologyIssueCode.TARGET_NOT_TESTABLE in codes(run)
    invented = well_engineering_script()
    invented["metric"]["T1"] = {"status": "ALIGNED_WITHIN_BOUND_INPUT", "outcome": S_MEASUREMENT,
                                "metric": "F1-score of 0.99 on the held-out set"}
    run, _ = go(invented)
    (m,) = [m for m in run.metric_alignments if m.gap_validation_requirement_id is None]
    assert m.status is MetricAlignmentStatus.METRIC_NOT_DEFINED and m.metric_excerpt_id is None
    assert any(r.code is MethodologyRunIssueCode.INVENTED_METRIC for r in run.rejected_proposals)
    assert all("0.99" not in e.excerpt for e in run.excerpts)


# -- sample, controls, confounding ---------------------------------------------------------------------------

S_RQ = "The research question is whether shade changes moisture retention."
S_DV = "The dependent variable is volumetric soil moisture."
S_OD = "Moisture is defined as the sensor reading averaged over ten minutes."
S_SAMPLE = "The sample is 500 soil cores from three farms."
S_DESIGN = "The study design compares shaded and unshaded plots."
S_COLLECT = "Data are collected by logging sensors."
S_MEASURE = "Measurement uses a calibrated probe."
S_N = "N = 500"
S_POWER = "A power analysis for a medium effect at 0.8 power gives 64 cores per group."
S_CONTROL = "Shaded and unshaded plots share soil type and irrigation schedule."
RESEARCH_TEXT = " ".join([S_RQ, S_DV, S_OD, S_SAMPLE, S_DESIGN, S_COLLECT, S_MEASURE, S_N, S_POWER, S_CONTROL])


def research_script(**evidence):
    ev = {"RESEARCH_QUESTION": S_RQ, "DEPENDENT_VARIABLE": S_DV, "OPERATIONAL_DEFINITIONS": S_OD, "SAMPLE": S_SAMPLE,
          "STUDY_DESIGN": S_DESIGN, "DATA_COLLECTION_METHOD": S_COLLECT, "MEASUREMENT_METHOD": S_MEASURE}
    ev.update(evidence)
    return {"evidence": {k: {"excerpts": [v] if isinstance(v, str) else v} for k, v in ev.items()},
            "applicability": {}, "metric": {}, "link": {}}


def research_world():
    return world(ProjectType.SCIENTIFIC_RESEARCH, RESEARCH_TEXT)


def test_a_bare_sample_size_never_establishes_a_sample_size_rationale():
    script = research_script(SAMPLE_SIZE_RATIONALE=S_N)
    script["applicability"] = {"SAMPLE_SIZE_RATIONALE": {"fired": ["STATISTICAL_INFERENCE"], "excerpt": S_SAMPLE}}
    run, _ = go(script, research_world())
    d = doc(run, K.SAMPLE_SIZE_RATIONALE)
    assert d.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT
    assert MethodologyIssueCode.SAMPLE_RATIONALE_NOT_DOCUMENTED in codes(run)
    assert doc(run, K.SAMPLE).documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED, "the sample itself is separate"
    assert not doc(run, K.SAMPLE_SIZE_RATIONALE).excerpt_ids


def test_a_real_sample_size_rationale_is_accepted_and_adequacy_is_still_the_models_bounded_judgment():
    script = research_script(SAMPLE_SIZE_RATIONALE=S_POWER)
    script["applicability"] = {"SAMPLE_SIZE_RATIONALE": {"fired": ["STATISTICAL_INFERENCE"], "excerpt": S_SAMPLE}}
    run, _ = go(script, research_world())
    d = doc(run, K.SAMPLE_SIZE_RATIONALE)
    assert d.documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED and len(d.excerpt_ids) == 1
    assert MethodologyIssueCode.SAMPLE_RATIONALE_NOT_DOCUMENTED not in codes(run)


def test_a_number_alone_is_never_rated_an_adequate_specification_on_any_requirement():
    script = research_script(SAMPLE=S_N)  # the model calls a bare "N = 500" adequate
    run, _ = go(script, research_world())
    d = doc(run, K.SAMPLE)
    assert d.documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED
    assert d.adequacy is DesignAdequacy.PARTIALLY_SPECIFIED
    assert run.track_assessments[0].posture is not WELL


def test_confounding_elimination_is_never_inferred():
    script = research_script(CONFOUNDER_HANDLING=S_CONTROL, CONTROLLED_VARIABLES=S_CONTROL)
    script["applicability"] = {"CONFOUNDER_HANDLING": {"fired": ["COMPARATIVE_OR_CAUSAL_CLAIM"], "excerpt": S_DESIGN}}
    run, _ = go(script, research_world())
    (ta,) = run.track_assessments
    assert ta.confounding_eliminated is False and ta.leakage_prevented_in_practice is False
    assert doc(run, K.CONFOUNDER_HANDLING).documentation is DocumentationStatus.EXPLICITLY_DOCUMENTED
    absent = research_script()
    absent["applicability"] = {"CONFOUNDER_HANDLING": {"fired": ["COMPARATIVE_OR_CAUSAL_CLAIM"], "excerpt": S_DESIGN}}
    run, _ = go(absent, research_world())
    assert MethodologyIssueCode.CONFOUNDER_HANDLING_NOT_DOCUMENTED in codes(run)


# -- AI/ML design risk and the result-leakage barrier -------------------------------------------------------

S_ML = "The model is a gradient boosted classifier trained on labelled moisture logs."
S_SPLIT = "Hyperparameters are tuned on the same held-out test set that is used for the final report."
AI_TEXT = ENGINEERING_TEXT + " " + S_ML + " " + S_SPLIT


def ai_script():
    script = well_engineering_script()
    script["overlay"] = {"AI_ML": {"materiality": "MATERIAL_TO_TARGET", "claims": ["C1"], "excerpts": [S_ML]}}
    return script


def test_a_documented_leaky_split_is_a_design_risk_and_a_missing_isolation_stays_a_risk():
    script = ai_script()
    script["evidence"]["TEST_SET_ISOLATION_FROM_TUNING"] = {
        "documentation": "EXPLICITLY_DOCUMENTED", "adequacy": "DESIGN_RISK_IDENTIFIED", "excerpts": [S_SPLIT]}
    run, _ = go(script, world(domains=ML, text=AI_TEXT))
    assert MethodologyIssueCode.DATA_LEAKAGE_RISK in codes(run)
    assert run.track_assessments[0].posture is MAJOR
    assert run.track_assessments[0].leakage_prevented_in_practice is False
    absent, _ = go(ai_script(), world(domains=ML, text=AI_TEXT))
    assert MethodologyIssueCode.TEST_SET_ISOLATION_NOT_DOCUMENTED in codes(absent)


def _canonical(run):
    return (run.track_assessments, run.draft, run.metric_alignments, run.baselines, run.overlays)


def test_reported_results_and_experiments_never_repair_or_change_the_methodology_review():
    state = world(domains=ML, text=AI_TEXT)
    plain, plain_model = go(ai_script(), state)
    boasting = state.project.model_copy(update={
        "experiments": [ExperimentRecord(experiment_id="EXP-01", objective="97 percent accuracy confirmed")],
        "results": [ResultRecord(result_id="R-01", experiment_id="EXP-01", metric="accuracy")]})
    with_results, model = go(ai_script(), state.model_copy(update={"project": boasting}))
    assert _canonical(plain) == _canonical(with_results)
    assert "97 percent" not in " ".join(u for _, u in model.calls) and "accuracy confirmed" not in " ".join(
        u for _, u in model.calls)
    assert MethodologyIssueCode.TEST_SET_ISOLATION_NOT_DOCUMENTED in codes(with_results), "success cannot repair it"
    assert with_results.track_assessments[0].posture is MAJOR


def test_a_student_sentence_about_success_or_a_working_prototype_cannot_upgrade_the_posture():
    claim = "The prototype achieved 97 percent accuracy and every experiment passed."
    gloat = edited(well_engineering_script())
    del gloat["evidence"]["MEASUREMENT_PLAN"]
    quiet, _ = go(gloat, world(text=ENGINEERING_TEXT))
    loud, _ = go(gloat, world(text=ENGINEERING_TEXT + " " + claim))
    assert [ta.posture for ta in quiet.track_assessments] == [ta.posture for ta in loud.track_assessments] == [MAJOR]


def test_no_phase_3a_production_module_reads_results_experiments_or_a_search_provider():
    root = Path(__file__).resolve().parents[1]
    sources = [*sorted((root / "src" / "research" / "methodology").glob("*.py")),
               root / "src" / "graph" / "methodology_nodes.py", root / "src" / "graph" / "phase3a_graph.py"]
    banned_attrs = {"results", "experiments", "trust_gate", "scores", "evaluation_status"}
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in banned_attrs, (path.name, node.attr)


def test_result_and_outcome_fields_cannot_enter_any_phase_3a_input_or_output_type():
    import src.research.methodology.dto as dto
    import src.schemas.methodology_review as mr

    for model in (*(getattr(dto, n) for n in dto.__all__), mr.MethodologyReviewRun, mr.MethodologyDraft):
        for name in model.model_fields:
            assert not any(f in name.casefold() for f in mr.FORBIDDEN_FIELD_FRAGMENTS), (model.__name__, name)
    with pytest.raises(Exception):
        dto.OverlayAssessmentResponse.model_validate({"overlays": [], "score": 100})
