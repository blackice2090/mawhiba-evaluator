"""Phase 3A Gold templates, part 1: engineering core, anchoring, execution boundary, result leakage, metric,
baseline, condition and target-linkage families. Authored from the specification; imports no production logic."""

from __future__ import annotations

import json
from typing import Callable

from generate_phase3a_gold import (  # noqa: F401
    ADEQ, C, CONFLICT, DIRECT, E, EXPL, INSUFF, MAJOR, NO_DOC, OUT, PART, PARTIAL, PARTIAL_REL, PSPEC, R, RISK, WELL,
    code_for_missing, cat, BANK, IDX, LANGS, CLAIM_SUFFIX_INJECTION)

TEMPLATES: list[tuple[str, Callable]] = []
ALIGNED = "ALIGNED_WITHIN_BOUND_INPUT"
INSUFF_EVID = "INSUFFICIENT_EVIDENCE_TO_ASSESS"
CLAIM_TEXT = "A smart irrigation controller using soil moisture sensors and weather forecasts"
MODEL_LANGS = LANGS


def tpl(name: str, langs=LANGS):
    def register(fn):
        TEMPLATES.append((name, fn, tuple(langs)))
        return fn

    return register


def eng(lang, tag, **kw):
    return C(lang, "E", tag, **kw).base()


def res(lang, tag, **kw):
    return C(lang, "R", tag, **kw).base()


def hyb(lang, tag, **kw):
    return C(lang, "H", tag, **kw).base()


def std(c: C) -> None:
    """The standard fully-covered expectations: DIRECT coverage, aligned metrics, addressed condition."""
    for tr in c.tracks:
        c.exp.setdefault(f"link.{tr}.claim", DIRECT)
    c.exp.setdefault("metric.claim", ALIGNED)
    if c.claim != "base":  # a rewritten claim text yields no Phase 2J hypothesis in the upstream world
        c.exp.setdefault(f"link.{c.gtrack}.gap", "ABSENT")
        c.exp.setdefault("metric.gap", "ABSENT")
        c.exp.setdefault("cond.1", "ABSENT")
        return
    c.exp.setdefault(f"link.{c.gtrack}.gap", DIRECT)
    if c.gap != "no_requirement":
        c.exp.setdefault("metric.gap", ALIGNED)
    if c.gap in ("default", "baseline"):
        c.exp.setdefault("cond.1", "ADDRESSED_IN_DESIGN")


def fin(c: C, posture=None, issues=None, *, with_std=True, **fields) -> dict:
    if with_std:
        std(c)
    return c.build(0, posture=posture, issues=issues, **fields)


def missing(c: C, kind: str) -> None:
    """Declared absent from the bound input: NOT_DOCUMENTED, never "the student did not do it"."""
    t = c.home(kind) or c.tracks[0]
    c.exp[f"doc.{t}.{kind}"] = NO_DOC
    c.exp[f"adq.{t}.{kind}"] = INSUFF_EVID


# =============================================================================================================
# Engineering core
# =============================================================================================================


@tpl("e_well")
def _(lang):
    c = eng(lang, "eng.well_specified", cats=["doc.explicit_adequate", "proj.engineering"])
    c.exp.update({"calls": 5, "overlay.AI_ML": "IMPLEMENTATION_TOOL_ONLY", "overlay_class.AI_ML": "NO_RELEVANCE",
                  "overlay_class.SOFTWARE_SYSTEMS": "NO_RELEVANCE", "msrc.claim": "STUDENT_EXCERPT",
                  "msrc.gap": "PHASE_2J_VALIDATION_ANCHOR", "exec_verified_any": False, "search_calls": 0})
    c.truth.update({"overlay.AI_ML": "NO_RELEVANCE", "overlay.SOFTWARE_SYSTEMS": "NO_RELEVANCE"})
    return fin(c, WELL, [])


for _kind, _key in [("DESIGN_OBJECTIVE", "OBJ"), ("REQUIREMENTS", "REQS"), ("ARCHITECTURE_SUBSYSTEM_PLAN", "ARCH"),
                    ("VERIFICATION_PLAN", "VERIF"), ("VALIDATION_PLAN", "VALID"), ("MEASUREMENT_PLAN", "MEAS"),
                    ("ACCEPTANCE_CRITERIA", "ACCEPT")]:
    def _make(kind=_kind, key=_key):
        @tpl(f"e_missing_{kind.lower()}")
        def _(lang):
            c = eng(lang, f"eng.required_missing.{kind}", cats=["doc.not_documented_in_bound_input", f"req.{kind}"])
            c.drop(kind)
            if kind == "VALIDATION_PLAN":
                c.doc("CONSTRAINTS", "COND")
                c.tkey = "VERIF"
            if kind == "MEASUREMENT_PLAN":
                c.extra.append(c.s("MEAS"))
            missing(c, kind)
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            return fin(c, MAJOR, [code_for_missing(kind)])
    _make()


for _kind, _trig, _key in [("RELIABILITY_PLAN", "RELIABILITY_CLAIMED", "RELI"), ("SAFETY_PLAN", "SAFETY_RELEVANT", "SAFE"),
                           ("SECURITY_PRIVACY_VALIDATION", "SECURITY_CLAIMED", "SEC"),
                           ("PERFORMANCE_BENCHMARK_PLAN", "PERFORMANCE_CLAIMED", "PERF"),
                           ("SCALABILITY_VALIDATION", "SCALABILITY_CLAIMED", "SCAL"),
                           ("BASELINE_OR_ALTERNATIVE_DESIGN", "COMPARATIVE_OR_CAUSAL_CLAIM", "BASEL")]:
    def _make2(kind=_kind, trig=_trig, key=_key):
        @tpl(f"e_conditional_{kind.lower()}_documented")
        def _(lang):
            c = eng(lang, f"eng.conditional_fired_documented.{kind}", cats=["app.conditional_resolved_applicable", f"req.{kind}"])
            c.fired[kind] = [trig]
            c.doc(kind, key, *(["BASEL_RAT"] if key == "BASEL" else []))
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            c.exp[f"basis.{E}.{kind}"] = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
            c.truth[f"applic.{E}.{kind}"] = "REQUIRED"
            return fin(c, WELL, [])

        @tpl(f"e_conditional_{kind.lower()}_missing")
        def _(lang):
            c = eng(lang, f"eng.conditional_fired_missing.{kind}", cats=["doc.not_documented_in_bound_input", f"req.{kind}"])
            c.fired[kind] = [trig]
            missing(c, kind)
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            return fin(c, MAJOR, [code_for_missing(kind)])
    _make2()


@tpl("e_conditional_not_fired_not_applicable")
def _(lang):
    c = eng(lang, "eng.conditional_resolved_not_applicable", cats=["app.conditional_resolved_not_applicable"])
    c.exp.update({f"app.{E}.SAFETY_PLAN": "NOT_APPLICABLE", f"basis.{E}.SAFETY_PLAN": "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                  f"doc.{E}.SAFETY_PLAN": "ABSENT"})
    c.truth[f"applic.{E}.SAFETY_PLAN"] = "NOT_APPLICABLE"
    return fin(c, WELL, [])


@tpl("e_optional_requirement_absent_no_issue")
def _(lang):
    c = eng(lang, "eng.optional_absent", cats=["app.optional", "req.CONSTRAINTS"])
    c.exp.update({f"app.{E}.CONSTRAINTS": "OPTIONAL", f"doc.{E}.CONSTRAINTS": NO_DOC})
    return fin(c, WELL, [])


@tpl("e_unresolved_conditionals_stay_conditional")
def _(lang):
    c = eng(lang, "eng.conditional_unresolved", cats=["app.conditional_unresolved"])
    c.skip_app = True
    c.skip_auto.add("pending")
    c.exp.update({f"app.{E}.RELIABILITY_PLAN": "CONDITIONAL", f"basis.{E}.RELIABILITY_PLAN": "CONDITION_UNRESOLVED",
                  f"doc.{E}.RELIABILITY_PLAN": NO_DOC})
    return fin(c, PARTIAL, [])


@tpl("e_trigger_outside_catalog_refused")
def _(lang):
    c = eng(lang, "eng.invalid_trigger", cats=["app.invented_trigger"])
    c.fired["SAFETY_PLAN"] = ["HUMAN_PARTICIPANTS"]
    c.exp.update({f"app.{E}.SAFETY_PLAN": "CONDITIONAL", "rejected": ["OFF_CONTRACT_OUTPUT"]})
    return fin(c, PARTIAL, [])


@tpl("e_conditional_judgment_without_excerpt")
def _(lang):
    c = eng(lang, "eng.conditional_no_excerpt", cats=["app.conditional_unresolved", "anchor.missing_excerpt"])
    c.finish_script()
    c.script["applicability"]["SAFETY_PLAN"] = {"fired": [], "excerpt": None}
    c.exp.update({f"app.{E}.SAFETY_PLAN": "CONDITIONAL"})
    return fin(c, PARTIAL, [])


@tpl("e_required_lowering_attempt")
def _(lang):
    c = eng(lang, "eng.required_downgrade_attempt", cats=["app.required_downgrade_attempt"])
    c.finish_script()
    c.script["applicability"]["DESIGN_OBJECTIVE"] = {"fired": [], "excerpt": c.s("REQS")}
    c.exp.update({f"app.{E}.DESIGN_OBJECTIVE": "REQUIRED", "rejected": ["INVENTED_REQUIREMENT"]})
    return fin(c, WELL, [])


@tpl("e_invented_requirement_kind")
def _(lang):
    c = eng(lang, "eng.invented_requirement", cats=["app.invented_requirement"])
    c.doc("METHODOLOGY_IS_VALID", "OBJ")
    del c.docs["METHODOLOGY_IS_VALID"]
    c.finish_script()
    c.script["evidence"]["METHODOLOGY_IS_VALID"] = {"excerpts": [c.s("OBJ")], "documentation": EXPL, "adequacy": ADEQ}
    c.flags["invented_kinds"] = ["METHODOLOGY_IS_VALID"]
    c.exp.update({"rejected": ["INVENTED_REQUIREMENT"]})
    return fin(c, WELL, [])


@tpl("e_off_enum_documentation_status")
def _(lang):
    c = eng(lang, "eng.off_enum_documentation", cats=["doc.invalid_structured_output"])
    c.doc("VERIFICATION_PLAN", "VERIF", documentation="PROVEN")
    missing(c, "VERIFICATION_PLAN")
    c.exp.update({"rejected": ["OFF_CONTRACT_OUTPUT"]})
    c.flags["off_contract_strings"] = ["PROVEN"]
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"])


@tpl("e_adequacy_incompatible_with_documentation")
def _(lang):
    c = eng(lang, "eng.adequacy_incompatible", cats=["doc.adequacy_separate"])
    c.doc("VERIFICATION_PLAN", "VERIF", adequacy="CONFLICTING_DESIGN")
    c.exp.update({f"adq.{E}.VERIFICATION_PLAN": PSPEC})
    return fin(c, PARTIAL, [])


@tpl("e_documented_with_design_risk")
def _(lang):
    c = eng(lang, "eng.documented_design_risk", cats=["doc.explicit_design_risk", "doc.documented_not_adequate"])
    c.doc("VERIFICATION_PLAN", "VERIF", adequacy=RISK)
    c.exp.update({f"doc.{E}.VERIFICATION_PLAN": EXPL, f"adq.{E}.VERIFICATION_PLAN": RISK})
    c.flags["risk_kinds"] = ["VERIFICATION_PLAN"]
    return fin(c, PARTIAL, [])


@tpl("e_partially_documented")
def _(lang):
    c = eng(lang, "eng.partially_documented", cats=["doc.partial"])
    c.doc("VERIFICATION_PLAN", "VERIF", documentation=PART, adequacy=PSPEC)
    return fin(c, PARTIAL, [])


@tpl("e_conflicting_documentation")
def _(lang):
    c = eng(lang, "eng.conflicting_documentation", cats=["doc.conflicting"])
    c.doc("MEASUREMENT_PLAN", "CONF_A", "CONF_B", documentation="CONFLICTING_DOCUMENTATION", adequacy="CONFLICTING_DESIGN")
    c.extra.append(c.s("MEAS"))
    c.exp.update({f"doc.{E}.MEASUREMENT_PLAN": "CONFLICTING_DOCUMENTATION"})
    return fin(c, CONFLICT, ["CONFLICTING_METHOD_DESCRIPTION"])


@tpl("e_no_provider_insufficient_source_coverage")
def _(lang):
    c = eng(lang, "eng.no_provider", cats=["fail.provider_missing", "doc.insufficient_source_coverage"])
    c.exp.update({f"doc.{E}.DESIGN_OBJECTIVE": "INSUFFICIENT_SOURCE_COVERAGE", f"adq.{E}.DESIGN_OBJECTIVE": INSUFF_EVID,
                  "errors": ["MODEL_PROVIDER_MISSING"], "calls": 0, f"link.{E}.claim": "INSUFFICIENT_LINKAGE_EVIDENCE"})
    c.flags.update({"source_unread": True, "link_unjudged_targets": True})
    c.skip_auto.update({"docs", "pending"})
    d = fin(c, INSUFF, None, with_std=False, no_model=True)
    return d


# =============================================================================================================
# Exact source anchoring
# =============================================================================================================


def _anchor_missing(c: C, kind: str, code: str, rejected=None) -> dict:
    missing(c, kind)
    c.exp["rejected"] = rejected or [code]
    return fin(c, MAJOR, [code_for_missing(kind)])


@tpl("a_fabricated_excerpt_rejected")
def _(lang):
    c = eng(lang, "anchor.fabricated_excerpt", cats=["anchor.fabricated"])
    ghost = c.s("OBJ") + " It was proven in the lab."
    c.doc("DESIGN_OBJECTIVE", ghost=[ghost])
    c.flags["fabricated"] = [ghost]
    return _anchor_missing(c, "DESIGN_OBJECTIVE", "FABRICATED_EXCERPT")


@tpl("a_cross_source_excerpt_rejected")
def _(lang):
    c = eng(lang, "anchor.cross_source", cats=["anchor.cross_source"])
    c.doc("DESIGN_OBJECTIVE", ghost=[CLAIM_TEXT])
    c.flags["fabricated"] = [CLAIM_TEXT]
    return _anchor_missing(c, "DESIGN_OBJECTIVE", "FABRICATED_EXCERPT")


@tpl("a_altered_whitespace_rejected")
def _(lang):
    c = eng(lang, "anchor.altered_whitespace", cats=["anchor.whitespace_altered"])
    sentence = c.s("REQS")
    altered = sentence.replace(" ", "  ", 1)
    c.doc("REQUIREMENTS", ghost=[altered])
    c.drop("REQUIREMENTS")
    c.doc("REQUIREMENTS", ghost=[altered])
    c.extra.append(sentence)
    c.flags["whitespace"] = [altered]
    return _anchor_missing(c, "REQUIREMENTS", "FABRICATED_EXCERPT")


@tpl("a_wrong_offsets_rejected")
def _(lang):
    c = eng(lang, "anchor.wrong_offsets", cats=["anchor.wrong_offsets"])
    sentence = c.s("REQS")
    c.span_override[("REQUIREMENTS", sentence)] = {"excerpt": sentence, "start": 3, "end": 3 + len(sentence)}
    return _anchor_missing(c, "REQUIREMENTS", "FABRICATED_EXCERPT")


@tpl("a_occurrence_out_of_range_rejected")
def _(lang):
    c = eng(lang, "anchor.bad_occurrence_index", cats=["anchor.occurrence_out_of_range"])
    sentence = c.s("REQS")
    c.dupes.append(sentence)
    c.span_override[("REQUIREMENTS", sentence)] = {"excerpt": sentence, "occurrence": 5}
    return _anchor_missing(c, "REQUIREMENTS", "FABRICATED_EXCERPT")


@tpl("a_repeated_excerpt_ambiguous_rejected")
def _(lang):
    c = eng(lang, "anchor.repeated_ambiguous", cats=["anchor.repeated_ambiguous", "anchor.first_match_guess_attack"])
    sentence = c.s("REQS")
    c.dupes.append(sentence)
    c.flags["ambiguous"] = [sentence]
    return _anchor_missing(c, "REQUIREMENTS", "AMBIGUOUS_EXCERPT")


@tpl("a_repeated_excerpt_correct_occurrence_accepted")
def _(lang):
    c = eng(lang, "anchor.repeated_occurrence_ok", cats=["anchor.repeated_correct_occurrence"])
    sentence = c.s("REQS")
    c.dupes.append(sentence)
    c.span_override[("REQUIREMENTS", sentence)] = {"excerpt": sentence, "occurrence": 2}
    c.exp[f"occ:{sentence}"] = "2/2/VALIDATED_OCCURRENCE_INDEX"
    return fin(c, WELL, [])


@tpl("a_repeated_excerpt_exact_offsets_accepted")
def _(lang):
    c = eng(lang, "anchor.repeated_exact_offsets", cats=["anchor.repeated_exact_offsets"])
    sentence = c.s("REQS")
    c.dupes.append(sentence)
    d = fin(c, WELL, [])
    start = d["submission"].find(sentence)
    d["script"]["evidence"]["REQUIREMENTS"]["excerpts"] = [{"excerpt": sentence, "start": start, "end": start + len(sentence)}]
    d["expected"][f"occ:{sentence}"] = "2/1/VALIDATED_EXACT_OFFSETS"
    return d


@tpl("a_instruction_like_source_text_is_inert_exact_data")
def _(lang):
    c = eng(lang, "anchor.instruction_like_exact", cats=["anchor.instruction_like", "inj.ignore_instructions"])
    c.doc("CONSTRAINTS", "INJ_IGNORE")
    c.flags.update({"instruction_sources": [c.s("INJ_IGNORE")], "attack": ["ignore_instructions"]})
    c.exp[f"occ:{c.s('INJ_IGNORE')}"] = "1/1/UNIQUE_IN_TEXT"
    return fin(c, WELL, [])


# =============================================================================================================
# Student execution description boundary (Phase 3B owns execution verification)
# =============================================================================================================

for _name, _key in [("tested_independently", "EXEC_TEST"), ("repeated_five_times", "EXEC_REP"),
                    ("validated_on_external_data", "EXEC_EXT")]:
    def _make3(name=_name, key=_key):
        @tpl(f"x_student_described_execution_{name}")
        def _(lang):
            c = eng(lang, f"exec.student_described.{name}", cats=["exec.student_described", "exec.not_verified"])
            c.doc("ITERATION_STRATEGY", key, mode="DESCRIBED_AS_EXECUTED")
            c.exp.update({"exec_modes": ["DESCRIBED_AS_EXECUTED", "MODE_NOT_DETERMINED", "PLANNED"], "exec_verified_any": False,
                          f"app.{E}.ITERATION_STRATEGY": "OPTIONAL"})
            return fin(c, WELL, [])
    _make3()


@tpl("x_we_randomized_research")
def _(lang):
    c = res(lang, "exec.we_randomized", cats=["exec.student_described", "app.randomization_conditional"])
    c.fired["RANDOMIZATION"] = ["ASSIGNED_INTERVENTION"]
    c.doc("RANDOMIZATION", "EXEC_RAND", mode="DESCRIBED_AS_EXECUTED")
    c.exp.update({"exec_modes": ["DESCRIBED_AS_EXECUTED", "MODE_NOT_DETERMINED", "PLANNED"], "exec_verified_any": False,
                  f"app.{R}.RANDOMIZATION": "REQUIRED", "confounding_any": False})
    return fin(c, WELL, [])


@tpl("x_planned_statement_is_not_executed")
def _(lang):
    c = eng(lang, "exec.planned_stays_planned", cats=["exec.planned_not_executed"])
    c.exp.update({"exec_modes": ["MODE_NOT_DETERMINED", "PLANNED"], "exec_verified_any": False, "fairness_any": False})
    return fin(c, WELL, [])


# =============================================================================================================
# Result / experiment leakage
# =============================================================================================================


def _leak(c: C, fields, **extra):
    c.flags["leak_fields"] = fields
    c.exp.update({"results.same": True, "immut.upstream": True})
    return dict(results_leak=True, **extra)


PAD = ["PROTO", "BENCH", "UI", "DIAG", "EXEC_TEST", "EXEC_REP", "EXEC_EXT", "SW_RAT", "FAILMODE", "CONFIG", "RELI", "SAFE",
       "SEC", "PERF", "SCAL", "ARCH", "CONSTR", "RATIO"]


@tpl("a_submission_longer_than_the_bound_is_never_read_as_not_done")
def _(lang):
    c = eng(lang, "anchor.truncated_source", cats=["doc.insufficient_source_coverage", "bounds.submission_chars"])
    c.drop("ACCEPTANCE_CRITERIA")
    for key in PAD:
        if len(c.text()) > 1100:
            break
        if c.s(key) not in c.text():
            c.extra.append(c.s(key))
    c.extra.append(c.s("ACCEPT"))
    c.flags["source_truncated"] = True
    c.exp.update({f"doc.{E}.ACCEPTANCE_CRITERIA": "INSUFFICIENT_SOURCE_COVERAGE", f"adq.{E}.ACCEPTANCE_CRITERIA": INSUFF_EVID,
                  f"app.{E}.ACCEPTANCE_CRITERIA": "REQUIRED"})
    return fin(c, PARTIAL, [], bounds={"max_submission_chars": 1000})


@tpl("a_excerpt_count_bound_is_enforced")
def _(lang):
    c = eng(lang, "anchor.excerpt_count_bound", cats=["bounds.max_excerpts", "anchor.bounded"])
    c.exp.update({"n_excerpts": 3})
    d = fin(c, MAJOR, None, with_std=False, bounds={"max_excerpts": 3})
    for key in [k for k in d["expected"] if k.startswith(("doc.", "adq.", "app.", "status", "issues."))]:
        d["expected"].pop(key)
    d["expected"]["status"] = "COMPLETED"
    return d


@tpl("r_leak_results_field_cannot_move_posture")
def _(lang):
    c = eng(lang, "leak.results_field", cats=["leak.result_field", "leak.high_accuracy"])
    kw = _leak(c, ["results"])
    return fin(c, WELL, [], **kw)


@tpl("r_leak_experiments_field_cannot_move_posture")
def _(lang):
    c = eng(lang, "leak.experiments_field", cats=["leak.experiment_field", "leak.repeated_experimental_success"])
    kw = _leak(c, ["experiments"])
    return fin(c, WELL, [], **kw)


@tpl("r_leak_working_prototype_cannot_repair_missing_validation")
def _(lang):
    c = eng(lang, "leak.working_prototype", cats=["leak.working_prototype", "doc.not_documented_in_bound_input"])
    c.drop("VALIDATION_PLAN")
    c.doc("CONSTRAINTS", "COND")
    c.tkey = "VERIF"
    c.extra += [c.s("PROTO")]
    missing(c, "VALIDATION_PLAN")
    c.flags["prototype_missing"] = ["VALIDATION_PLAN"]
    c.flags["issues_must_remain"] = ["REQUIRED_COMPONENT_NOT_DOCUMENTED"]
    kw = _leak(c, ["results", "experiments"])
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"], **kw)


@tpl("r_leak_passed_benchmark_cannot_repair_missing_measurement_plan")
def _(lang):
    c = eng(lang, "leak.passed_benchmark", cats=["leak.passed_benchmark", "doc.not_documented_in_bound_input"])
    c.drop("MEASUREMENT_PLAN")
    c.extra += [c.s("MEAS"), c.s("BENCH")]
    missing(c, "MEASUREMENT_PLAN")
    c.flags["benchmark_missing"] = ["MEASUREMENT_PLAN"]
    c.flags["issues_must_remain"] = ["REQUIRED_COMPONENT_NOT_DOCUMENTED"]
    kw = _leak(c, ["results", "experiments"])
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"], **kw)


@tpl("r_leak_successful_result_cannot_repair_isolation_risk")
def _(lang):
    from phase3a_gold_templates2 import ai_case

    c = ai_case(lang, "leak.result_vs_leakage_risk", domains=["MACHINE_LEARNING"])
    c.doc("TEST_SET_ISOLATION_FROM_TUNING", "TUNE_BAD", adequacy=RISK)
    c.extra.append(c.s("ACC"))
    c.flags.update({"isolation_risk": ["TEST_SET_ISOLATION_FROM_TUNING"], "tuning_contamination": ["TEST_SET_ISOLATION_FROM_TUNING"],
                    "accuracy_with_risk": ["TEST_SET_ISOLATION_FROM_TUNING"], "issues_must_remain": ["DATA_LEAKAGE_RISK"]})
    kw = _leak(c, ["results", "experiments"])
    c.cats += ["ai.tuning_contamination", "ai.high_accuracy_no_isolation", "leak.high_accuracy"]
    return fin(c, MAJOR, ["DATA_LEAKAGE_RISK"], **kw)


# =============================================================================================================
# Metric alignment
# =============================================================================================================


@tpl("m_vague_claim_has_no_invented_metric")
def _(lang):
    c = eng(lang, "metric.vague_better_claim", cats=["metric.vague_claim", "metric.not_measurable"])
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"]["T1"] = {"status": "TARGET_NOT_MEASURABLE_AS_STATED"}
    c.flags["vague_claim"] = True
    c.truth["metric.claim"] = "TARGET_NOT_MEASURABLE_AS_STATED"
    c.exp.update({"metric.claim": "TARGET_NOT_MEASURABLE_AS_STATED", f"link.{E}.claim": DIRECT, "msrc.claim": None,
                  "metric.gap": ALIGNED, f"link.{E}.gap": DIRECT, "cond.1": "ADDRESSED_IN_DESIGN"})
    return fin(c, MAJOR, ["TARGET_NOT_TESTABLE"], with_std=False)


@tpl("m_metric_not_defined_blocks_strong_claim_coverage")
def _(lang):
    c = eng(lang, "metric.undefined_efficiency", cats=["metric.not_defined", "metric.more_efficient_undefined"])
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"]["T1"] = {"status": "METRIC_NOT_DEFINED"}
    c.truth["metric.claim"] = "METRIC_NOT_DEFINED"
    c.exp.update({"metric.claim": "METRIC_NOT_DEFINED", f"link.{E}.claim": DIRECT, "metric.gap": ALIGNED,
                  f"link.{E}.gap": DIRECT, "cond.1": "ADDRESSED_IN_DESIGN"})
    return fin(c, MAJOR, ["METRIC_NOT_DEFINED"], with_std=False)


@tpl("m_gap_metric_not_defined_blocks_strong_gap_coverage")
def _(lang):
    c = eng(lang, "metric.gap_metric_undefined", cats=["metric.not_defined", "continuity.metric_required"])
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"] = {"T1": {"status": ALIGNED, "outcome": c.s("MEAS"), "metric": c.s("MEAS_METRIC")},
                          "G1": {"status": "METRIC_NOT_DEFINED"}}
    c.truth["metric.gap"] = "METRIC_NOT_DEFINED"
    c.exp.update({"metric.gap": "METRIC_NOT_DEFINED", f"link.{E}.gap": PARTIAL_REL, "metric.claim": ALIGNED,
                  f"link.{E}.claim": DIRECT, "cond.1": "ADDRESSED_IN_DESIGN", "cont.gap": "NOT_STRONG"})
    return fin(c, MAJOR, ["METRIC_NOT_DEFINED"], with_std=False)


@tpl("m_metric_measures_wrong_outcome")
def _(lang):
    c = eng(lang, "metric.latency_for_accuracy_claim", cats=["metric.mismatch", "metric.latency_vs_accuracy"])
    c.extra.append(c.s("PERF"))
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"]["T1"] = {"status": "METRIC_TARGET_MISMATCH", "outcome": c.s("MEAS"), "metric": c.s("PERF")}
    c.script["metric"]["G1"] = {"status": ALIGNED, "outcome": c.s("MEAS")}
    c.truth["metric.claim"] = "METRIC_TARGET_MISMATCH"
    c.exp.update({"metric.claim": "METRIC_TARGET_MISMATCH", f"link.{E}.claim": DIRECT, "metric.gap": ALIGNED,
                  f"link.{E}.gap": DIRECT, "cond.1": "ADDRESSED_IN_DESIGN"})
    return fin(c, MAJOR, ["METRIC_TARGET_MISMATCH"], with_std=False)


@tpl("m_fabricated_metric_is_refused")
def _(lang):
    c = eng(lang, "metric.fabricated_metric", cats=["metric.fabricated", "inj.fabricate_metric"])
    ghost = "perfect-score-index"
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"] = {"T1": {"status": ALIGNED, "outcome": c.s("MEAS"), "metric": ghost},
                          "G1": {"status": ALIGNED, "outcome": c.s("MEAS")}}
    c.flags.update({"fabricated_metrics": [ghost], "fabricated": [ghost]})
    c.exp.update({"metric.claim": "METRIC_NOT_DEFINED", f"link.{E}.claim": DIRECT, "metric.gap": ALIGNED,
                  f"link.{E}.gap": DIRECT, "cond.1": "ADDRESSED_IN_DESIGN", "rejected": ["FABRICATED_EXCERPT", "INVENTED_METRIC"]})
    return fin(c, MAJOR, ["METRIC_NOT_DEFINED"], with_std=False)


@tpl("m_phase2j_metric_anchor_is_the_gap_metric")
def _(lang):
    c = eng(lang, "metric.phase2j_anchor", cats=["metric.phase2j_aligned", "continuity.metric_required"])
    c.exp.update({"msrc.gap": "PHASE_2J_VALIDATION_ANCHOR", "msrc.claim": "STUDENT_EXCERPT", "cont.gap": "STRONG"})
    return fin(c, WELL, [])


@tpl("m_seeded_wrong_aligned_metric_is_measured_not_blocked")
def _(lang):
    c = eng(lang, "metric.seeded_wrong_alignment", cats=["metric.seeded_wrong_judgment", "model_judgment.seeded_error"])
    c.extra.append(c.s("PERF"))
    c.finish_script()
    c.link_override["metric"] = True
    c.script["metric"] = {"T1": {"status": ALIGNED, "outcome": c.s("MEAS"), "metric": c.s("PERF")},
                          "G1": {"status": ALIGNED, "outcome": c.s("MEAS")}}
    c.truth["metric.claim"] = "METRIC_TARGET_MISMATCH"
    c.exp.update({"metric.claim": ALIGNED, "msrc.claim": "STUDENT_EXCERPT"})
    return fin(c, WELL, [])


# =============================================================================================================
# Baseline / comparator (documented != relevant != rationale != fairly executed)
# =============================================================================================================


def base_eng(lang, tag, **kw):
    return eng(lang, tag, gap="baseline", **kw)


@tpl("b_baseline_documented_and_relevant_with_rationale")
def _(lang):
    c = base_eng(lang, "baseline.relevant_with_rationale", cats=["baseline.relevant", "baseline.rationale_documented"])
    c.truth["baseline.gap"] = "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "brat.gap": True, "fairness_any": False,
                  "bctx.gap": ["PHASE_2J_VALIDATION_BASELINE", "STUDENT_RATIONALE_EXCERPT"], f"app.{E}.BASELINE_OR_ALTERNATIVE_DESIGN": "REQUIRED",
                  f"basis.{E}.BASELINE_OR_ALTERNATIVE_DESIGN": "PHASE_2J_VALIDATION_REQUIREMENT"})
    return fin(c, WELL, [])


@tpl("b_baseline_and_rationale_in_one_excerpt")
def _(lang):
    c = base_eng(lang, "baseline.same_excerpt", cats=["baseline.same_excerpt_name_and_rationale"])
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["PHASE_2J_VALIDATION_BASELINE"], "rationale": c.s("BASEL")}
    c.link_override["baseline"] = True
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "brat.gap": True})
    return fin(c, WELL, [])


@tpl("b_phase2j_context_without_student_rationale")
def _(lang):
    c = base_eng(lang, "baseline.phase2j_context_only", cats=["baseline.phase2j_context_supports_relevance"])
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["PHASE_2J_VALIDATION_BASELINE"]}
    c.link_override["baseline"] = True
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "brat.gap": False,
                  "bctx.gap": ["PHASE_2J_VALIDATION_BASELINE"]})
    return fin(c, WELL, [])


@tpl("b_phase2j_existing_capability_supports_relevance")
def _(lang):
    c = base_eng(lang, "baseline.existing_capability_context", cats=["baseline.phase2j_existing_capability"])
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["PHASE_2J_EXISTING_CAPABILITY"]}
    c.link_override["baseline"] = True
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "bctx.gap": ["PHASE_2J_EXISTING_CAPABILITY"]})
    return fin(c, WELL, [])


@tpl("b_baseline_name_alone_is_not_relevance")
def _(lang):
    c = base_eng(lang, "baseline.name_alone", cats=["baseline.name_only", "baseline.documented_not_relevant"])
    c.extra.append(c.s("BASEL_NAME"))
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL_NAME"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"}
    c.link_override["baseline"] = True
    c.flags["baseline_name_only"] = ["G1"]
    c.truth["baseline.gap"] = "RELEVANCE_UNRESOLVED"
    c.exp.update({"baseline.gap": "RELEVANCE_UNRESOLVED", "brat.gap": False, f"link.{E}.gap": PARTIAL_REL, "cont.gap": "NOT_STRONG",
                  "fairness_any": False})
    return fin(c, PARTIAL, ["BASELINE_RELEVANCE_UNRESOLVED"])


@tpl("b_documented_but_irrelevant_baseline")
def _(lang):
    c = base_eng(lang, "baseline.documented_irrelevant", cats=["baseline.irrelevant", "baseline.wrong_target"])
    c.extra.append(c.s("BASEL_NAME"))
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL_NAME"), "relevance": "NOT_RELEVANT_TO_TARGET"}
    c.link_override["baseline"] = True
    c.truth["baseline.gap"] = "NOT_RELEVANT_TO_TARGET"
    c.exp.update({"baseline.gap": "NOT_RELEVANT_TO_TARGET", f"link.{E}.gap": PARTIAL_REL})
    return fin(c, MAJOR, ["GAP_METHOD_MISMATCH"])


@tpl("b_required_baseline_omitted")
def _(lang):
    c = base_eng(lang, "baseline.required_by_phase2j_omitted", cats=["baseline.missing_when_required"])
    c.finish_script()
    c.script["baseline"] = {}
    c.link_override["baseline"] = True
    c.truth["baseline.gap"] = "NO_BASELINE_DOCUMENTED"
    c.exp.update({"baseline.gap": "NO_BASELINE_DOCUMENTED", f"link.{E}.gap": PARTIAL_REL, "cont.gap": "NOT_STRONG"})
    return fin(c, PARTIAL, ["BASELINE_NOT_DOCUMENTED"])


@tpl("b_unpermitted_relevance_context_refused")
def _(lang):
    c = base_eng(lang, "baseline.unpermitted_context", cats=["baseline.name_only", "baseline.wrong_context"])
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["THE_BASELINE_NAME"]}
    c.link_override["baseline"] = True
    c.exp.update({"baseline.gap": "RELEVANCE_UNRESOLVED", "rejected": ["OFF_CONTRACT_OUTPUT"], f"link.{E}.gap": PARTIAL_REL})
    return fin(c, PARTIAL, ["BASELINE_RELEVANCE_UNRESOLVED"])


@tpl("b_seeded_wrong_relevant_baseline_is_measured_not_blocked")
def _(lang):
    c = base_eng(lang, "baseline.seeded_wrong_relevance", cats=["baseline.seeded_wrong_judgment", "model_judgment.seeded_error"])
    c.extra.append(c.s("BASEL_NAME"))
    c.finish_script()
    c.script["baseline"]["G1"] = {"baseline": c.s("BASEL_NAME"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["PHASE_2J_VALIDATION_BASELINE"]}
    c.link_override["baseline"] = True
    c.truth["baseline.gap"] = "NOT_RELEVANT_TO_TARGET"
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "fairness_any": False})
    return fin(c, WELL, [])


@tpl("b_no_baseline_required_none_invented")
def _(lang):
    c = eng(lang, "baseline.not_required_none_invented", cats=["baseline.no_baseline_required", "continuity.baseline_absent_not_invented"])
    c.exp.update({"baseline.gap": "ABSENT", "baseline.claim": "ABSENT", f"app.{E}.BASELINE_OR_ALTERNATIVE_DESIGN": "NOT_APPLICABLE"})
    return fin(c, WELL, [])


# =============================================================================================================
# Material conditions and Phase 2J continuity
# =============================================================================================================


@tpl("k_material_condition_not_addressed")
def _(lang):
    c = eng(lang, "condition.one_missing", cats=["condition.missing", "continuity.conditions_required"])
    c.finish_script()
    c.link_override["conditions"] = True
    c.script["conditions"]["G1:1"] = {"status": "NOT_ADDRESSED_IN_BOUND_INPUT", "excerpts": []}
    c.truth["cond.1"] = "NOT_ADDRESSED_IN_BOUND_INPUT"
    c.exp.update({"cond.1": "NOT_ADDRESSED_IN_BOUND_INPUT", f"link.{E}.gap": PARTIAL_REL, "cont.gap": "NOT_STRONG"})
    return fin(c, MAJOR, ["MATERIAL_CONDITION_NOT_COVERED"])


@tpl("k_condition_only_partially_addressed")
def _(lang):
    c = eng(lang, "condition.partial", cats=["condition.partially_addressed"])
    c.finish_script()
    c.link_override["conditions"] = True
    c.script["conditions"]["G1:1"] = {"status": "PARTIALLY_ADDRESSED", "excerpts": [c.s("COND")]}
    c.truth["cond.1"] = "PARTIALLY_ADDRESSED"
    c.exp.update({"cond.1": "PARTIALLY_ADDRESSED", f"link.{E}.gap": PARTIAL_REL})
    return fin(c, PARTIAL, [])


@tpl("k_seeded_condition_addressed_by_unrelated_method")
def _(lang):
    c = eng(lang, "condition.unrelated_method", cats=["condition.unrelated_method", "model_judgment.seeded_error"])
    c.finish_script()
    c.link_override["conditions"] = True
    c.script["conditions"]["G1:1"] = {"status": "ADDRESSED_IN_DESIGN", "excerpts": [c.s("OBJ")]}
    c.truth["cond.1"] = "NOT_ADDRESSED_IN_BOUND_INPUT"
    c.exp.update({"cond.1": "ADDRESSED_IN_DESIGN"})
    return fin(c, WELL, [])


@tpl("k_unknown_condition_label_is_refused")
def _(lang):
    c = eng(lang, "condition.wrong_label", cats=["condition.wrong_condition_id"])
    c.finish_script()
    c.link_override["conditions"] = True
    c.script["conditions"] = {"G9:9": {"status": "ADDRESSED_IN_DESIGN", "excerpts": [c.s("COND")]}}
    c.exp.update({"cond.1": "ABSENT", "rejected": ["OFF_CONTRACT_OUTPUT"], f"link.{E}.gap": PARTIAL_REL})
    return fin(c, PARTIAL, [])


@tpl("k_no_material_condition_none_invented")
def _(lang):
    c = eng(lang, "condition.none_required", cats=["condition.none_required", "continuity.conditions_empty"], gap="no_condition")
    c.docs["VALIDATION_PLAN"]["keys"] = ["VALID"]
    c.exp.update({"cond.1": "ABSENT"})
    return fin(c, WELL, [])


@tpl("k_no_validation_requirement_nothing_invented")
def _(lang):
    c = eng(lang, "continuity.no_validation_requirement", cats=["continuity.requirement_absent", "continuity.nothing_invented"],
            gap="no_requirement")
    c.docs["VALIDATION_PLAN"]["keys"] = ["VALID"]
    c.exp.update({"metric.gap": "ABSENT", "baseline.gap": "ABSENT", "cond.1": "ABSENT"})
    return fin(c, WELL, [])


# =============================================================================================================
# Claim / gap -> methodology linkage relations
# =============================================================================================================

for _rel, _issue, _post in [(PARTIAL_REL, None, PARTIAL), ("RELEVANT_BUT_NOT_TESTING", "CLAIM_METHOD_MISMATCH", MAJOR),
                            ("DOES_NOT_TEST_TARGET", "CLAIM_METHOD_MISMATCH", MAJOR),
                            ("INSUFFICIENT_LINKAGE_EVIDENCE", None, PARTIAL)]:
    def _make4(rel=_rel, issue=_issue, post=_post):
        @tpl(f"l_claim_relation_{rel.lower()}")
        def _(lang):
            c = eng(lang, f"link.claim_{rel}", cats=[f"link.{rel}", "link.claim_method"])
            c.finish_script()
            c.link_override["link"] = True
            ex = [c.s("VALID")] if rel in (PARTIAL_REL,) else ([c.s("OBJ")] if rel != "INSUFFICIENT_LINKAGE_EVIDENCE" else [])
            c.script["link"]["T1"] = {E: {"relation": rel, "excerpts": ex}}
            c.script["link"]["G1"] = {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}
            c.truth[f"link.{E}.claim"] = rel
            c.exp.update({f"link.{E}.claim": rel, f"link.{E}.gap": DIRECT, "metric.claim": ALIGNED, "metric.gap": ALIGNED,
                          "cond.1": "ADDRESSED_IN_DESIGN"})
            return fin(c, post, [issue] if issue else [], with_std=False)

        @tpl(f"l_gap_relation_{rel.lower()}")
        def _(lang):
            c = eng(lang, f"link.gap_{rel}", cats=[f"link.gap_{rel}", "link.gap_method"])
            c.finish_script()
            c.link_override["link"] = True
            ex = [c.s("VALID")] if rel in (PARTIAL_REL,) else ([c.s("OBJ")] if rel != "INSUFFICIENT_LINKAGE_EVIDENCE" else [])
            c.script["link"]["T1"] = {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}
            c.script["link"]["G1"] = {E: {"relation": rel, "excerpts": ex}}
            c.truth[f"link.{E}.gap"] = rel
            c.exp.update({f"link.{E}.claim": DIRECT, f"link.{E}.gap": rel, "metric.claim": ALIGNED, "metric.gap": ALIGNED,
                          "cond.1": "ADDRESSED_IN_DESIGN"})
            return fin(c, post, [("GAP_METHOD_MISMATCH" if issue else None)] if issue else [], with_std=False)
    _make4()


@tpl("l_direct_on_non_testing_requirement_is_downgraded")
def _(lang):
    c = eng(lang, "link.direct_unrelated_methodology", cats=["link.unrelated_methodology_cannot_be_strong"])
    c.finish_script()
    c.link_override["link"] = True
    c.script["link"]["T1"] = {E: {"relation": DIRECT, "excerpts": [c.s("OBJ")]}}
    c.script["link"]["G1"] = {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}
    c.exp.update({f"link.{E}.claim": PARTIAL_REL, f"link.{E}.gap": DIRECT, "metric.claim": ALIGNED, "metric.gap": ALIGNED})
    return fin(c, PARTIAL, [], with_std=False)


@tpl("l_seeded_semantically_wrong_direct_link_is_measured")
def _(lang):
    c = eng(lang, "link.seeded_wrong_direct", cats=["link.seeded_wrong_judgment", "model_judgment.seeded_error"])
    c.truth[f"link.{E}.claim"] = "DOES_NOT_TEST_TARGET"
    return fin(c, WELL, [])


@tpl("l_unknown_target_label_is_refused")
def _(lang):
    c = eng(lang, "link.unknown_target", cats=["link.unbound_target"])
    c.finish_script()
    c.link_override["link"] = True
    c.script["link"] = {}
    c.script["link"]["T7"] = {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}
    c.script["link"]["G1"] = {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}
    c.exp.update({f"link.{E}.claim": "INSUFFICIENT_LINKAGE_EVIDENCE", f"link.{E}.gap": DIRECT, "rejected": [],
                  "metric.claim": ALIGNED, "metric.gap": ALIGNED})
    del c.exp["rejected"]
    return fin(c, PARTIAL, [], with_std=False)


def main() -> None:
    import phase3a_gold_templates2  # noqa: F401  (registers its templates)
    import phase3a_gold_templates3  # noqa: F401

    cases: list[dict] = []
    for lang in LANGS:
        for name, fn, langs in TEMPLATES:
            if lang not in langs:
                continue
            case = fn(lang)
            if case is None:
                continue
            case["description"] = f"{name} [{lang}]"
            case["semantic_family"] = name
            cases.append(case)
    for i, case in enumerate(cases, 1):
        case["case_id"] = f"GM-{i:03d}"
        special = (case["rerun"] or case["interrupt_before"] or case["twin"] or case["results_leak"] or case["mutate"])
        if i % 7 == 0 or special:
            case["controls"] = ["*"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in cases) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")

