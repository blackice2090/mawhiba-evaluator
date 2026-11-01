"""Phase 3B Gold families, part 2: baseline / comparator layers, sample / repetition / statistics boundaries, the
result quarantine, result segmentation recall, prompt boundary and injection, source-window parity and the
execution boundary."""

from __future__ import annotations

from typing import Any

from phase3b_gold_framework import Exp, Sc, family
from phase3b_gold_lang import kind_text, pad_text, property_text, t, tuning_text

from src.evals.experiment_review import catalog as cat

EN_AR = ("en", "ar")
EN_MX = ("en", "mixed")


def mk(lang: str, etype: str = "ENGINEERING_BENCH_TEST", *, ptype: str | None = None, gap: str = "default",
       tagged: bool = False, **kw: Any) -> tuple[Sc, Exp]:
    fam = cat.TYPE_FAMILY[etype]
    pt = ptype or {"SCIENTIFIC": "SCIENTIFIC_RESEARCH"}.get(fam, "ENGINEERING_PROJECT")
    sc = Sc(lang, pt, gap, tagged=tagged)
    e = sc.exp(etype=etype, **kw)
    return sc, e


def baseline_link(e: Exp, **base: Any) -> None:
    d = e.default_link()
    b = {"excerpts": [e.text("BASELINE")], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
         "context": ["PHASE_2J_VALIDATION_BASELINE"], "match": "SAME_AS_PHASE_2J"}
    b.update(base)
    d["targets"]["V1"]["baseline"] = b
    e.link = d


# =========================================================================================================
# G. baseline / comparator: documented, relevant, comparable, executed, evaluated stay separate layers
# =========================================================================================================


@family("baseline.name_only_is_not_relevance", "baseline_relevance")
def _b1(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline")
    sc.result("RES_POS")
    baseline_link(e, context=[])
    e.link_state["baseline_ok"] = False
    sc.flags["baseline_name_only"] = True
    sc.truth = {"baseline_relevance": {"V1": "RELEVANCE_UNRESOLVED"}}
    sc.expect(**{"x1__bl__V1": "RELEVANCE_UNRESOLVED", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["BASELINE_TARGET_MISMATCH"]})
    return sc.finish()


@family("baseline.relevant_by_student_rationale", "baseline_relevance")
def _b2(lang: str) -> dict:
    fired = {"BASELINE": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "BASELINE_CONFIGURATION": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"]}
    why = t("BASE_WHY", lang)
    sc, e = mk(lang, fired=fired, extra_docs={"BASELINE": [t("BASE_NAME", lang), why]})
    sc.result("RES_POS")
    d = e.default_link()
    d["targets"]["V1"]["baseline"] = {"excerpts": [t("BASE_NAME", lang)],
                                      "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                      "context": ["STUDENT_RATIONALE_EXCERPT"], "rationale_excerpts": [why]}
    e.link = d
    sc.truth = {"baseline_relevance": {"V1": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"}}
    sc.expect(**{"x1__bl__V1": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", "x1__blmatch__V1": "NO_PHASE_2J_ANCHOR"})
    return sc.finish()


@family("baseline.irrelevant_baseline_flagged", "baseline_relevance")
def _b3(lang: str) -> dict:
    fired = {"BASELINE": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "BASELINE_CONFIGURATION": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"]}
    other = t("BASE_OTHER", lang)
    sc, e = mk(lang, fired=fired, extra_docs={"BASELINE": [other]})
    sc.result("RES_POS")
    d = e.default_link()
    d["targets"]["V1"]["baseline"] = {"excerpts": [other], "relevance": "NOT_RELEVANT_TO_TARGET"}
    e.link = d
    e.extra_issues = ["BASELINE_NOT_RELEVANT"]
    sc.truth = {"baseline_relevance": {"V1": "NOT_RELEVANT_TO_TARGET"}}
    sc.expect(**{"x1__bl__V1": "NOT_RELEVANT_TO_TARGET", "x1__issues": ["BASELINE_NOT_RELEVANT"],
                 "x1__posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("baseline.irrelevant_judged_relevant_by_model", "baseline_relevance")
def _b3b(lang: str) -> dict:
    """The named baseline is a weather station, the model calls it relevant on a permitted ground. The deterministic
    guard (a permitted ground exists) accepts it; the semantic error is MEASURED, never declared correct."""
    fired = {"BASELINE": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "BASELINE_CONFIGURATION": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"]}
    other = t("BASE_OTHER", lang)
    sc, e = mk(lang, fired=fired, extra_docs={"BASELINE": [other]})
    sc.result("RES_POS")
    d = e.default_link()
    d["targets"]["V1"]["baseline"] = {"excerpts": [other], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                      "context": ["TARGET_CLAIM_TEXT"]}
    e.link = d
    sc.truth = {"baseline_relevance": {"V1": "NOT_RELEVANT_TO_TARGET"}}
    sc.expect(**{"x1__bl__V1": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"})
    return sc.finish()


def _difference(prop: str):
    def build(lang: str) -> dict:
        text = tuning_text(lang) if prop == "EQUIVALENT_TUNING_OPPORTUNITY" else property_text(prop, False, lang)
        sc, e = mk(lang, gap="baseline", extra_docs={"BASELINE_CONFIGURATION": [t("BASE_CFG", lang), text]})
        sc.result("RES_POS")
        baseline_link(e, comparability={prop: ("DOCUMENTED_DIFFERENT", [text])})
        e.extra_issues = ["BASELINE_COMPARABILITY_GAP"]
        sc.truth = {"comparability": {prop: "DOCUMENTED_DIFFERENT"}}
        sc.expect(**{f"x1__blprop__V1__{prop}": "DOCUMENTED_DIFFERENT", "x1__issues": ["BASELINE_COMPARABILITY_GAP"],
                     "x1__posture": "PARTIALLY_SPECIFIED", "cov.V1": "COVERED_BY_EXPERIMENT"})
        return sc.finish()

    return build


for _i, _p in enumerate(cat.BASELINE_PROPERTIES):
    family(f"baseline.difference.{_p}", "baseline_comparability", EN_AR if _i % 2 else EN_MX)(_difference(_p))


@family("baseline.all_listed_properties_same", "baseline_comparability")
def _b4(lang: str) -> dict:
    props = [p for p in cat.BASELINE_PROPERTIES if p != "SAME_EVALUATION_METRIC"]
    texts = [property_text(p, True, lang) for p in props]
    sc, e = mk(lang, gap="baseline", extra_docs={"BASELINE_CONFIGURATION": [t("BASE_CFG", lang), *texts]})
    sc.result("RES_POS")
    baseline_link(e, comparability={p: ("DOCUMENTED_SAME", [x]) for p, x in zip(props, texts)})
    sc.truth = {"comparability": {p: "DOCUMENTED_SAME" for p in props}}
    sc.flags["no_global_fair"] = True
    sc.expect(**{f"x1__blprop__V1__{props[0]}": "DOCUMENTED_SAME", "x1__issues": [], "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("baseline.same_metric_is_the_only_deterministic_property", "baseline_comparability")
def _b5(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline")
    sc.result("RES_POS")
    sc.expect(**{"x1__blprop__V1__SAME_EVALUATION_METRIC": "DOCUMENTED_SAME",
                 "x1__blprop_basis__V1__SAME_EVALUATION_METRIC": "DETERMINISTIC_SHARED_METRIC_BINDING",
                 "x1__blprop__V1__SAME_HARDWARE": "ABSENT"})
    return sc.finish()


@family("baseline.different_metric_stays_different", "baseline_comparability", EN_AR)
def _b5b(lang: str) -> dict:
    text = property_text("SAME_EVALUATION_METRIC", False, lang)
    sc, e = mk(lang, gap="baseline", extra_docs={"BASELINE_CONFIGURATION": [t("BASE_CFG", lang), text]})
    sc.result("RES_POS")
    baseline_link(e, comparability={"SAME_EVALUATION_METRIC": ("DOCUMENTED_DIFFERENT", [text])})
    e.extra_issues = ["BASELINE_COMPARABILITY_GAP"]
    sc.expect(**{"x1__blprop__V1__SAME_EVALUATION_METRIC": "DOCUMENTED_DIFFERENT",
                 "x1__blprop_basis__V1__SAME_EVALUATION_METRIC": "MODEL_ASSISTED_BOUNDED_JUDGMENT"})
    return sc.finish()


@family("baseline.comparability_not_applicable_is_not_the_models_to_assert", "baseline_comparability")
def _b6(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline")
    sc.result("RES_POS")
    baseline_link(e, comparability={"SAME_HARDWARE": ("NOT_APPLICABLE", [])})
    sc.expect(**{"x1__blprop__V1__SAME_HARDWARE": "UNRESOLVED"})
    return sc.finish()


@family("baseline.documented_comparability_needs_excerpt", "baseline_comparability", EN_MX)
def _b7(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline")
    sc.result("RES_POS")
    baseline_link(e, comparability={"SAME_HARDWARE": ("DOCUMENTED_SAME", [])})
    sc.expect(**{"x1__blprop__V1__SAME_HARDWARE": "NOT_DOCUMENTED"})
    return sc.finish()


@family("baseline.execution_described_never_verified", "baseline_execution")
def _b8(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline", execution="EXECUTION_DESCRIBED")
    sc.say(t("EXEC_RAN", lang))
    sc.result("RES_POS")
    baseline_link(e, execution="EXECUTION_DESCRIBED")
    sc.flags["exec_prose"] = True
    sc.expect(**{"x1__exec": "EXECUTION_DESCRIBED", "exec_flags_false": True})
    return sc.finish()


@family("baseline.model_global_fairness_claim_refused", "baseline_comparability")
def _b9(lang: str) -> dict:
    sc, e = mk(lang, gap="baseline")
    sc.result("RES_POS")
    d = e.default_link()
    d["targets"]["V1"]["baseline"] = {"excerpts": [e.text("BASELINE")], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                      "context": ["PHASE_2J_VALIDATION_BASELINE"], "match": "SAME_AS_PHASE_2J"}
    d["targets"]["V1"]["rationale"] = "The baseline is fair and the comparison is fair."
    e.link = d
    e.link_state["V1"] = ("UNRESOLVED", False)
    e.unresolved = False
    sc.flags["attack"] = True
    sc.flags["model_texts"] = [d["targets"]["V1"]["rationale"]]
    sc.expect(**{"x1__link__V1": "UNRESOLVED", "errors": ["PARTIAL_MODEL_OUTPUT", "SOURCE_INSTRUCTION_FOLLOWED"],
                 "x1__bl__V1": "ABSENT"})
    return sc.finish()


# =========================================================================================================
# H. sample, repetition and statistics boundaries
# =========================================================================================================


@family("sample.bare_number_is_not_a_rationale", "sample_boundary")
def _s1(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"SAMPLE_SIZE_RATIONALE": ["SAMPLED_POPULATION"]},
               missing=("SAMPLE_SIZE_RATIONALE",))
    bare = sc.say(t("SAMPLE_BARE", lang))
    e.raw_reqs = {"SAMPLE_SIZE_RATIONALE": {"excerpts": [bare]}}
    sc.result("RES_POS")
    sc.flags["bare_n"] = True
    sc.expect(**{"x1__doc__SAMPLE_SIZE_RATIONALE": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 "x1__issues": ["REQUIRED_PROTOCOL_ELEMENT_MISSING"], "x1__posture": "PARTIALLY_SPECIFIED",
                 "errors": ["PARTIAL_MODEL_OUTPUT"]})
    return sc.finish()


@family("sample.bare_number_is_not_adequate", "sample_boundary")
def _s2(lang: str) -> dict:
    sc, e = mk(lang, missing=("SAMPLE_SIZE",))
    bare = sc.say(t("SAMPLE_BARE2", lang))
    e.docs["SAMPLE_SIZE"] = [bare]
    e.inadequate = True
    sc.result("RES_POS")
    sc.flags["bare_n"] = True
    sc.expect(**{"x1__adq__SAMPLE_SIZE": "PARTIALLY_SPECIFIED", "x1__doc__SAMPLE_SIZE": "EXPLICITLY_DOCUMENTED",
                 "x1__posture": "PARTIALLY_SPECIFIED", "x1__issues": []})
    return sc.finish()


@family("sample.conflicting_statements_are_a_protocol_conflict", "sample_boundary")
def _s_conflict(lang: str) -> dict:
    a, b2 = t("SAMPLE_CONFLICT_A", lang), t("SAMPLE_CONFLICT_B", lang)
    sc, e = mk(lang, missing=("SAMPLE_SIZE",))
    sc.say(a)
    sc.say(b2)
    e.docs["SAMPLE_SIZE"] = [a, b2]
    e.documentation["SAMPLE_SIZE"] = "CONFLICTING_DOCUMENTATION"
    e.adequacy["SAMPLE_SIZE"] = "CONFLICTING_PROTOCOL"
    e.extra_issues = ["CONFLICTING_PROTOCOL_DESCRIPTION"]
    sc.result("RES_POS")
    sc.expect(**{"x1__doc__SAMPLE_SIZE": "CONFLICTING_DOCUMENTATION", "x1__adq__SAMPLE_SIZE": "CONFLICTING_PROTOCOL",
                 "x1__issues": ["CONFLICTING_PROTOCOL_DESCRIPTION"], "x1__posture": "MAJOR_GAPS"})
    return sc.finish()


@family("sample.small_but_justified", "sample_boundary")
def _s3(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"SAMPLE_SIZE_RATIONALE": ["SAMPLED_POPULATION"]})
    sc.result("RES_POS")
    sc.truth = {"sample_adequate": True}
    sc.expect(**{"x1__doc__SAMPLE_SIZE_RATIONALE": "EXPLICITLY_DOCUMENTED", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("sample.large_but_unjustified", "sample_boundary")
def _s4(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"SAMPLE_SIZE_RATIONALE": ["SAMPLED_POPULATION"]},
               missing=("SAMPLE_SIZE", "SAMPLE_SIZE_RATIONALE"))
    big = sc.say(t("SAMPLE_LARGE", lang))
    e.docs["SAMPLE_SIZE"] = [big]
    sc.result("RES_POS")
    sc.truth = {"sample_adequate": False}
    sc.expect(**{"x1__doc__SAMPLE_SIZE": "EXPLICITLY_DOCUMENTED", "x1__doc__SAMPLE_SIZE_RATIONALE": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 "x1__issues": ["REQUIRED_PROTOCOL_ELEMENT_MISSING"], "x1__posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("repetition.count_does_not_establish_independence", "repetition_boundary")
def _r1(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", fired={"REPETITION_INDEPENDENCE": ["REPLICATION_RELIED_ON"]},
               missing=("REPETITION_INDEPENDENCE",))
    sc.say(t("REPEAT_COUNT", lang))
    sc.result("RES_POS")
    sc.flags["rep_count_only"] = True
    sc.truth = {"reproducible": False}
    sc.expect(**{"x1__app__REPETITION_INDEPENDENCE": "REQUIRED", "x1__doc__REPETITION_INDEPENDENCE": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 "x1__issues": ["REPETITIONS_MISSING_WHEN_REQUIRED"], "x1__posture": "MAJOR_GAPS"})
    return sc.finish()


@family("repetition.independent_replication_documented", "repetition_boundary")
def _r2(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", fired={"REPETITION_INDEPENDENCE": ["REPLICATION_RELIED_ON"]})
    sc.result("RES_POS")
    sc.truth = {"reproducible": True}
    sc.expect(**{"x1__doc__REPETITION_INDEPENDENCE": "EXPLICITLY_DOCUMENTED", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("repetition.not_applicable_for_ai_without_stochastic_trigger", "repetition_boundary")
def _r3(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__REPETITIONS": "NOT_APPLICABLE", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("repetition.pseudoreplication_is_a_protocol_risk", "repetition_boundary")
def _r4(lang: str) -> dict:
    same = t("REPEAT_SAME", lang)
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", fired={"REPETITION_INDEPENDENCE": ["REPLICATION_RELIED_ON"]},
               extra_docs={"REPETITION_INDEPENDENCE": [same]}, adequacy={"REPETITION_INDEPENDENCE": "PROTOCOL_RISK_IDENTIFIED"})
    sc.result("RES_POS")
    e.extra_issues = ["PROTOCOL_RISK_IDENTIFIED"]
    sc.truth = {"reproducible": False}
    sc.expect(**{"x1__issues": ["PROTOCOL_RISK_IDENTIFIED"], "x1__adq__REPETITION_INDEPENDENCE": "PROTOCOL_RISK_IDENTIFIED",
                 "x1__posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("repetition.random_seeds_documented", "repetition_boundary", EN_AR)
def _r5(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__SEED_OR_REPEATABILITY": "REQUIRED", "x1__doc__SEED_OR_REPEATABILITY": "EXPLICITLY_DOCUMENTED"})
    return sc.finish()


@family("stats.descriptive_is_enough", "statistics_applicability")
def _st1(lang: str) -> dict:
    sc, e = mk(lang, fired={"DESCRIPTIVE_STATISTICS": ["QUANTITATIVE_MEASUREMENT"]})
    sc.result("RES_POS")
    sc.flags["no_inference"] = True
    sc.expect(**{"x1__app__DESCRIPTIVE_STATISTICS": "REQUIRED", "x1__app__STATISTICAL_TEST": "NOT_APPLICABLE",
                 "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("stats.p_value_present_but_not_required", "statistics_applicability")
def _st2(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT")
    sc.say(t("STAT_P", lang))
    sc.result("RES_POS")
    sc.flags["no_inference"] = True
    sc.flags["p_value_present"] = True
    sc.expect(**{"x1__app__STATISTICAL_TEST": "NOT_APPLICABLE", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("stats.p_value_present_protocol_poor", "statistics_applicability")
def _st3(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", missing=("SETUP", "INPUTS", "SAMPLE_DEFINITION"))
    sc.say(t("STAT_P", lang))
    sc.result("RES_STAT", "STATISTICAL_OUTCOME")
    sc.flags["p_value_present"] = True
    sc.expect(**{"x1__posture": "MAJOR_GAPS"})
    return sc.finish()


@family("stats.no_p_value_does_not_fail", "statistics_applicability")
def _st4(lang: str) -> dict:
    sc, e = mk(lang, "SOFTWARE_BENCHMARK")
    sc.result("RES_POS")
    sc.flags["no_inference"] = True
    sc.flags["no_p_value"] = True
    sc.expect(**{"x1__app__STATISTICAL_TEST": "NOT_APPLICABLE", "x1__posture": "WELL_SPECIFIED", "status": "COMPLETED"})
    return sc.finish()


@family("stats.deterministic_benchmark_repeats_without_significance", "statistics_applicability")
def _st5(lang: str) -> dict:
    sc, e = mk(lang, "SOFTWARE_BENCHMARK")
    sc.result("RES_POS")
    sc.flags["no_inference"] = True
    sc.expect(**{"x1__app__REPETITIONS": "REQUIRED", "x1__doc__REPETITIONS": "EXPLICITLY_DOCUMENTED",
                 "x1__app__STATISTICAL_TEST": "NOT_APPLICABLE", "x1__app__EFFECT_SIZE": "NOT_APPLICABLE"})
    return sc.finish()


# =========================================================================================================
# I. the result quarantine
# =========================================================================================================


def qsc(lang: str, results: list[tuple[str, str]], **kw: Any) -> tuple[Sc, Exp]:
    sc, e = mk(lang, **kw)
    for sid, kind in results:
        sc.result(sid, kind)
    return sc, e


def n_quar(sc: Sc) -> int:
    text = sc.submission
    total = 0
    for spec in sc._declared_specs():
        total += text.count(spec["span"])
    return total


@family("quarantine.single_result_sentence", "result_quarantine")
def _q1(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    sc.expect(n_quar=1, quar_texts=[t("RES_POS", lang)], later_prompt_leak=False, placeholder_shown=True)
    return sc.finish()


@family("quarantine.repeated_result_all_occurrences", "result_quarantine")
def _q2(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    sc.say(t("FILLER3", lang))
    sc.say(t("RES_POS", lang))
    sc.say(t("FILLER", lang))
    sc.say(t("RES_POS", lang))
    sc.expect(n_quar=3, quar_texts=[t("RES_POS", lang)] * 3, later_prompt_leak=False)
    return sc.finish()


@family("quarantine.long_result_sentence", "result_quarantine")
def _q3(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_LONG", "REPORTED_METRIC_VALUE")])
    sc.expect(n_quar=1, quar_texts=[t("RES_LONG", lang)], later_prompt_leak=False)
    return sc.finish()


@family("quarantine.result_table", "result_quarantine")
def _q4(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_TABLE", "RESULT_TABLE")])
    sc.expect(n_quar=1, quar_texts=[t("RES_TABLE", lang)], later_prompt_leak=False)
    return sc.finish()


@family("quarantine.result_contains_injection", "result_quarantine")
def _q5(lang: str) -> dict:
    sc, e = mk(lang)
    text = t("RES_POS", lang) + " " + t("INJ_WELL", lang)
    sc.result("RES_POS", text=text)
    sc.flags["attack"] = True
    sc.flags["markers"] = [t("INJ_WELL", lang)]
    sc.expect(n_quar=1, quar_texts=[text], later_prompt_leak=False, x1__posture="WELL_SPECIFIED")
    return sc.finish()


KINDS = [("RES_POS", "REPORTED_METRIC_VALUE"), ("RES_STAT", "STATISTICAL_OUTCOME"), ("RES_TABLE", "RESULT_TABLE"),
         ("RES_CONCL", "CONCLUSION"), ("RES_NEUTRAL", "SUCCESS_OR_FAILURE_STATEMENT"),
         ("RES_CAUSAL", "CAUSAL_OR_GENERALIZATION_STATEMENT"), ("RES_FAIL", "NEGATIVE_OUTCOME_STATEMENT")]


def _kind(sid: str, kind: str):
    def build(lang: str) -> dict:
        sc, e = qsc(lang, [(sid, kind)])
        sc.expect(n_quar=1, quar_texts=[t(sid, lang)], quar_kinds=[kind], later_prompt_leak=False)
        return sc.finish()

    return build


for _i, (_sid, _k) in enumerate(KINDS):
    family(f"quarantine.kind.{_k}", "result_quarantine", EN_AR if _i % 2 else EN_MX)(_kind(_sid, _k))


@family("quarantine.positive_negative_neutral_together", "result_quarantine")
def _q6(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE"), ("RES_NEG", "REPORTED_METRIC_VALUE"),
                       ("RES_NEUTRAL", "SUCCESS_OR_FAILURE_STATEMENT")])
    sc.expect(n_quar=3, later_prompt_leak=False)
    return sc.finish()


@family("quarantine.protocol_cut_out_of_combined_sentence", "result_quarantine")
def _q7(lang: str) -> dict:
    """Protocol and result in ONE sentence: the model cuts the protocol out and declares only the result part."""
    sc, e = mk(lang, missing=("OUTPUTS",))
    base = kind_text("OUTPUTS", lang)
    combined = base[:-1] + " " + t("RES_TAIL", lang)
    sc.parts.append(combined)
    sc.results.append({"text": t("RES_TAIL", lang), "kind": "REPORTED_METRIC_VALUE", "declared": True})
    e.docs["OUTPUTS"] = [base[:-1]]
    e.missing.discard("OUTPUTS")
    sc.expect(n_quar=1, quar_texts=[t("RES_TAIL", lang)], later_prompt_leak=False, x1__doc__OUTPUTS="EXPLICITLY_DOCUMENTED")
    return sc.finish()


@family("quarantine.protocol_excerpt_overlapping_result_is_refused", "result_quarantine")
def _q8(lang: str) -> dict:
    sc, e = mk(lang, missing=("OUTPUTS",))
    base = kind_text("OUTPUTS", lang)
    combined = base[:-1] + " " + t("RES_TAIL", lang)
    sc.parts.append(combined)
    sc.results.append({"text": t("RES_TAIL", lang), "kind": "REPORTED_METRIC_VALUE", "declared": True})
    e.raw_reqs = {"OUTPUTS": {"excerpts": [combined]}}  # the model cites protocol AND result text
    sc.expect(**{"n_quar": 1, "later_prompt_leak": False, "errors": ["RESULT_LEAKAGE_ATTEMPT"],
                 "rejected": ["RESULT_LEAKAGE_ATTEMPT"], "x1__doc__OUTPUTS": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 "x1__issues": ["OUTPUTS_MISSING"], "x1__posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("quarantine.defining_excerpt_overlapping_result_is_refused", "result_quarantine")
def _q9(lang: str) -> dict:
    sc = Sc(lang)
    define = t("DEF_eng", lang, n=1)
    combined = define[:-1] + " " + t("RES_TAIL", lang)
    sc.parts.append(combined)
    sc.results.append({"text": t("RES_TAIL", lang), "kind": "REPORTED_METRIC_VALUE", "declared": True})
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [combined]}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": t("RES_TAIL", lang)}]}
    sc.expect(n_exp=0, n_quar=1, errors=["PARTIAL_MODEL_OUTPUT"], rejected=["PARTIAL_MODEL_OUTPUT", "RESULT_LEAKAGE_ATTEMPT"],
              status="COMPLETED", calls=1, posture="MAJOR_GAPS")
    return sc.finish(standard=False)


@family("quarantine.declared_result_cannot_be_located", "incomplete_quarantine")
def _q10(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    fake = "Result: the secret field trial gave 99.9 percent accuracy in a place not in this submission."
    sc.extra_declared.append((fake, "REPORTED_METRIC_VALUE"))
    sc.flags["incomplete_quarantine"] = True
    sc.flags["unlocatable_result"] = fake
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, n_exp=0, calls=1, n_quar=1,
              errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"], rejected=["EXACT_EXCERPT_MISMATCH"],
              stages_called={"segment": 1})
    return sc.finish(standard=False)


@family("quarantine.empty_declared_result", "incomplete_quarantine")
def _q11(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    sc.extra_declared.append(("", "REPORTED_METRIC_VALUE"))
    sc.flags["incomplete_quarantine"] = True
    sc.flags["empty_declared_result"] = True
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, n_exp=0, calls=1,
              errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"], stages_called={"segment": 1})
    return sc.finish(standard=False)


@family("quarantine.excessive_occurrence_count", "incomplete_quarantine")
def _q12(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    for _ in range(4):
        sc.say(t("RES_POS", lang))
    sc.bounds = {"max_excerpts": 3}
    sc.flags["incomplete_quarantine"] = True
    sc.flags["excessive_result"] = t("RES_POS", lang)
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, n_exp=0, calls=1, n_quar=0,
              errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"], stages_called={"segment": 1})
    return sc.finish(standard=False)


@family("quarantine.unknown_result_kind_is_still_quarantined", "result_quarantine")
def _q13(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "WIZARD_RESULT")])
    sc.expect(n_quar=1, quar_kinds=["CONCLUSION"], errors=["PARTIAL_MODEL_OUTPUT"], later_prompt_leak=False,
              status="COMPLETED")
    return sc.finish()


@family("quarantine.provider_incomplete_segmentation_output", "incomplete_quarantine")
def _q14(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    sc.script = {"segment": "incomplete"}
    sc.flags["provider_failure"] = "SEGMENT:PARTIAL_MODEL_OUTPUT"
    sc.expect(n_exp=0, n_quar=0, errors=["PARTIAL_MODEL_OUTPUT"], calls=2, status="COMPLETED", posture="MAJOR_GAPS")
    return sc.finish(standard=False)


@family("quarantine.offsets_and_hashes_stable_on_replay", "result_quarantine")
def _q15(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE")])
    sc.expect(**{"replay.same": True, "replay.extra_calls": 0, "n_quar": 1})
    return sc.finish(rerun=True)


def _mutation(fid: str, swap_for):
    def build(lang: str) -> dict:
        sc, e = qsc(lang, [swap_for[0]])
        swap = swap_for[1](lang)
        sc.expect(**{"twin.result": True, "twin.result_quarantine": True, "twin.result_keys": True})
        sc.flags["mutation_pair"] = True
        return sc.finish(twin="result", twin_data={"swap": swap})

    return build


family("quarantine.mutation.numeric_97_vs_41", "result_mutation_invariance")(
    _mutation("n", [("RES_POS", "REPORTED_METRIC_VALUE"), lambda lang: {"97": "41"}]))
family("quarantine.mutation.table_values", "result_mutation_invariance")(
    _mutation("t", [("RES_TABLE", "RESULT_TABLE"), lambda lang: {"97": "12", "95": "13", "96": "14"}]))
family("quarantine.mutation.improved_vs_worsened", "result_mutation_invariance")(
    _mutation("w", [("RES_IMPROVED", "CONCLUSION"), lambda lang: {t("RES_IMPROVED", lang): t("RES_WORSENED", lang)}]))
family("quarantine.mutation.positive_vs_negative", "result_mutation_invariance")(
    _mutation("p", [("RES_POS", "REPORTED_METRIC_VALUE"), lambda lang: {t("RES_POS", lang): t("RES_NEG", lang)}]))


@family("quarantine.mutation.statistical_outcome", "result_mutation_invariance", EN_AR)
def _q16(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT")
    sc.result("RES_STAT", "STATISTICAL_OUTCOME")
    sc.expect(**{"twin.result": True, "twin.result_quarantine": True})
    return sc.finish(twin="result", twin_data={"swap": {"0.01": "0.84", "significant": "not significant"}
                                               if lang == "en" else {"0.01": "0.84"}})


@family("quarantine.results_withheld_from_all_later_prompts", "result_quarantine")
def _q17(lang: str) -> dict:
    sc, e = qsc(lang, [("RES_POS", "REPORTED_METRIC_VALUE"), ("RES_FAIL", "NEGATIVE_OUTCOME_STATEMENT")])
    sc.expect(n_quar=2, later_prompt_leak=False, placeholder_shown=True, **{"x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


# -- result-span precision and recall seeds (model-judgment; reported honestly, never forced) ---------------------


def _recall(fid_sid: list[tuple[str, str, bool]], expect: dict[str, Any]):
    def build(lang: str) -> dict:
        sc, e = mk(lang)
        for sid, kind, declared in fid_sid:
            sc.result(sid, kind, declare=declared)
        sc.expect(**expect)
        return sc.finish()

    return build


family("resultspans.easy_numeric_declared", "result_span_recall")(
    _recall([("RES_POS", "REPORTED_METRIC_VALUE", True)], {"n_quar": 1}))
family("resultspans.paraphrased_declared", "result_span_recall")(
    _recall([("RES_PARA", "CONCLUSION", True)], {"n_quar": 1}))
family("resultspans.paraphrased_missed_by_model", "result_span_recall")(
    _recall([("RES_PARA", "CONCLUSION", False)], {"n_quar": 0}))
family("resultspans.table_declared", "result_span_recall", EN_AR)(
    _recall([("RES_TABLE", "RESULT_TABLE", True)], {"n_quar": 1}))
family("resultspans.table_missed_by_model", "result_span_recall", EN_MX)(
    _recall([("RES_TABLE", "RESULT_TABLE", False)], {"n_quar": 0}))
family("resultspans.short_statement_missed", "result_span_recall")(
    _recall([("RES_SHORT", "SUCCESS_OR_FAILURE_STATEMENT", False)], {"n_quar": 0}))
family("resultspans.short_statement_declared", "result_span_recall", EN_AR)(
    _recall([("RES_SHORT", "SUCCESS_OR_FAILURE_STATEMENT", True)], {"n_quar": 1}))
family("resultspans.two_results_one_missed", "result_span_recall")(
    _recall([("RES_POS", "REPORTED_METRIC_VALUE", True), ("RES_NEUTRAL", "REPORTED_METRIC_VALUE", False)], {"n_quar": 1}))
family("resultspans.arabic_style_conclusion_missed", "result_span_recall", ("ar", "mixed"))(
    _recall([("RES_CONCL", "CONCLUSION", False)], {"n_quar": 0}))


@family("resultspans.protocol_numbers_are_not_results", "result_span_precision")
def _rp1(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.truth["protocol_numbers"] = [e.define]
    sc.expect(n_quar=1, x1__ndef=1, x1__posture="WELL_SPECIFIED")
    return sc.finish()


@family("resultspans.protocol_text_declared_as_result", "result_span_precision")
def _rp2(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    inputs = e.docs.pop("INPUTS")[0]
    e.missing.add("INPUTS")
    e.raw_reqs = {"INPUTS": {"excerpts": [inputs]}}
    sc.extra_declared.append((inputs, "REPORTED_METRIC_VALUE"))
    sc.flags["false_result_declared"] = inputs
    sc.expect(n_quar=2, quar_kinds=["REPORTED_METRIC_VALUE", "REPORTED_METRIC_VALUE"], errors=["RESULT_LEAKAGE_ATTEMPT"],
              x1__doc__INPUTS="NOT_DOCUMENTED_IN_BOUND_INPUT")
    return sc.finish()


# =========================================================================================================
# J. prompt boundary and injection
# =========================================================================================================


def inj_case(lang: str, kind: str, *, where: str = "doc", escaped: bool = True, fails_closed: bool = False,
             **expect: Any):
    sc, e = mk(lang)
    text = t(kind, lang)
    if where == "doc":
        e.replace_doc("OBJECTIVE", e.docs["OBJECTIVE"][0] + " " + text)
        if fails_closed:  # the model cites it, the verifier cannot match it, so the requirement stays undocumented
            e.raw_reqs = {"OBJECTIVE": {"excerpts": list(e.docs.pop("OBJECTIVE"))}}
            e.missing.add("OBJECTIVE")
    elif where == "define":
        new = e.define + " " + text
        idx = sc.parts.index(e.define)
        sc.parts[idx] = new
        e.define = new
    elif where == "standalone":
        sc.say(text)
    sc.result("RES_POS")
    sc.script = {"quote_escaped": escaped}
    sc.flags["attack"] = True
    sc.flags["markers"] = [text]
    sc.expect(**expect)
    return sc, e


for _i, _kind in enumerate(["INJ_END", "INJ_END3", "INJ_SYSTEM", "INJ_EQ", "INJ_WELL", "INJ_LEAK", "INJ_SCORE"]):
    def _mk(kind=_kind):
        def build(lang: str) -> dict:
            sc, e = inj_case(lang, kind, where="doc", **{"x1__posture": "WELL_SPECIFIED", "x1__issues": [],
                                                            "later_prompt_leak": False})
            return sc.finish()

        return build

    family(f"injection.in_protocol_text.{_kind}", "prompt_boundary")(_mk())

for _kind in ["INJ_END", "INJ_WELL", "INJ_SYSTEM"]:
    def _mkd(kind=_kind):
        def build(lang: str) -> dict:
            sc, e = inj_case(lang, kind, where="define", **{"x1__posture": "WELL_SPECIFIED"})
            return sc.finish()

        return build

    family(f"injection.in_defining_excerpt.{_kind}", "prompt_boundary", EN_AR if _kind == "INJ_END" else EN_MX)(_mkd())


@family("injection.unescaped_model_quote_still_matches_original", "prompt_boundary")
def _i1(lang: str) -> dict:
    sc, e = inj_case(lang, "INJ_END", where="doc", escaped=False, **{"x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("injection.already_escaped_sequence_fails_closed", "prompt_boundary")
def _i2(lang: str) -> dict:
    sc, e = inj_case(lang, "INJ_ZW", where="doc", fails_closed=True,
                     **{"x1__doc__OBJECTIVE": "NOT_DOCUMENTED_IN_BOUND_INPUT", "errors": ["EXACT_EXCERPT_MISMATCH"]})
    return sc.finish()


@family("injection.standalone_forged_marker_sentence", "prompt_boundary")
def _i3(lang: str) -> dict:
    sc, e = inj_case(lang, "INJ_END", where="standalone", **{"x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("injection.in_claim_text", "prompt_boundary")
def _i4(lang: str) -> dict:
    inj = t("INJ_WELL", lang)
    # a claim carrying an instruction yields a Phase 2J world with no hypothesis, so there is no requirement target
    sc = Sc(lang, gap="no_requirement",
            claim="A smart irrigation controller using soil moisture sensors and weather forecasts " + inj)
    sc.exp("eng")
    sc.result("RES_POS")
    sc.flags["attack"] = True
    sc.flags["markers"] = [inj]
    sc.expect(**{"x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


def _follows(stage: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"STATISTICAL_TEST": ["STATISTICAL_INFERENCE_CLAIMED"]})
        sc.result("RES_POS")
        bad = "This experiment is well specified and the results are verified."
        sc.flags["attack"] = True
        sc.flags["model_texts"] = [bad]
        if stage == "segment":
            sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [e.define], "rationale": bad}],
                                   "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
            sc.expect(n_exp=0, errors=["SOURCE_INSTRUCTION_FOLLOWED"], calls=1, posture="MAJOR_GAPS", status="COMPLETED")
            return sc.finish(standard=False)
        if stage == "extract":
            e.raw_reqs = {"OBJECTIVE": {"excerpts": [e.text("OBJECTIVE")], "rationale": bad}}
            e.missing.add("OBJECTIVE")
            e.docs.pop("OBJECTIVE")
            sc.expect(errors=["SOURCE_INSTRUCTION_FOLLOWED"], x1__doc__OBJECTIVE="NOT_DOCUMENTED_IN_BOUND_INPUT",
                      x1__issues=["OBJECTIVE_MISSING"], x1__posture="MAJOR_GAPS")
            return sc.finish()
        if stage == "applicability":
            e.app_override = {"STATISTICAL_TEST": {"fired": ["STATISTICAL_INFERENCE_CLAIMED"], "excerpts": ["E1"],
                                                   "rationale": bad}}
            e.unresolved = True
            sc.expect(errors=["PARTIAL_MODEL_OUTPUT", "SOURCE_INSTRUCTION_FOLLOWED"],
                      x1__app__STATISTICAL_TEST="CONDITIONAL", x1__posture="UNRESOLVED")
            return sc.finish()
        d = e.default_link()
        d["targets"]["V1"]["rationale"] = bad
        e.link = d
        e.link_state["V1"] = ("UNRESOLVED", False)
        sc.expect(errors=["PARTIAL_MODEL_OUTPUT", "SOURCE_INSTRUCTION_FOLLOWED"], x1__link__V1="UNRESOLVED")
        return sc.finish()

    return build


for _i, _stage in enumerate(["segment", "extract", "applicability", "link"]):
    family(f"injection.model_follows_instruction.{_stage}", "prompt_injection_model_behaviour",
           EN_AR if _i % 2 else EN_MX)(_follows(_stage))


@family("injection.model_leaks_hidden_prompt_in_rationale", "prompt_injection_model_behaviour")
def _i5(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    e.raw_reqs = {"OBJECTIVE": {"excerpts": [e.text("OBJECTIVE")], "rationale": "$LEAK"}}
    e.missing.add("OBJECTIVE")
    e.docs.pop("OBJECTIVE")
    sc.flags["attack"] = True
    sc.flags["leaks_prompt"] = True
    sc.expect(errors=["PROMPT_LEAK_REDACTED"], x1__doc__OBJECTIVE="NOT_DOCUMENTED_IN_BOUND_INPUT", x1__posture="MAJOR_GAPS")
    return sc.finish()


@family("injection.refusal_leaks_hidden_prompt", "prompt_injection_model_behaviour")
def _i6(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"extract": "refusal_leak"}
    sc.flags["attack"] = True
    sc.flags["leaks_prompt"] = True
    sc.flags["provider_failure"] = "EXTRACT:MODEL_REFUSED"
    sc.expect(errors=["EXACT_EXCERPT_MISMATCH", "MODEL_REFUSED"], x1__type="UNKNOWN", x1__posture="INSUFFICIENT_EVIDENCE", calls=3,
              posture="INSUFFICIENT_EVIDENCE", status="COMPLETED")
    return sc.finish(standard=False)


# =========================================================================================================
# K. source window and anchor parity
# =========================================================================================================


def _start_of(sc: Sc, text: str) -> int:
    return sc.submission.index(text)


@family("window.protocol_inside_result_after_window", "source_window")
def _w1(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng")
    pad = pad_text(lang, 1000)
    res = sc.result("RES_POS", declare=False)
    sc.parts.insert(sc.parts.index(res), pad)
    start = _start_of(sc, res)
    sc.bounds = {"max_submission_chars": max(1000, start)}
    sc.flags["window"] = sc.bounds["max_submission_chars"]
    sc.expect(n_quar=0, n_exp=1, x1__posture="WELL_SPECIFIED", later_prompt_leak=False)
    return sc.finish()


@family("window.defining_excerpt_straddles_window_end", "source_window")
def _w2(lang: str) -> dict:
    sc = Sc(lang)
    sc.parts.append(pad_text(lang, 1000))
    e = sc.exp("eng")
    sc.result("RES_POS", declare=False)
    start = _start_of(sc, e.define)
    sc.bounds = {"max_submission_chars": start + 20}
    sc.flags["window"] = start + 20
    sc.expect(n_exp=0, errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"], calls=1, status="COMPLETED")
    return sc.finish(standard=False)


@family("window.defining_excerpt_ends_exactly_at_window_end", "source_window")
def _w3(lang: str) -> dict:
    sc = Sc(lang)
    sc.parts.append(pad_text(lang, 960))
    e = sc.exp("eng", missing=tuple(cat.required_kinds("ENGINEERING_BENCH_TEST")))
    sc.result("RES_POS", declare=False)
    end = _start_of(sc, e.define) + len(e.define)
    sc.bounds = {"max_submission_chars": max(1000, end)}
    sc.flags["window"] = sc.bounds["max_submission_chars"]
    sc.expect(n_exp=1, x1__ndef=1, status="COMPLETED")
    return sc.finish(standard=False)


@family("window.requirement_excerpt_outside_window", "source_window")
def _w4(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng")
    sc.result("RES_POS", declare=False)
    last = e.docs.pop("PROTOCOL_DETAIL")[0]
    e.missing.add("PROTOCOL_DETAIL")
    e.raw_reqs = {"PROTOCOL_DETAIL": {"excerpts": [last]}}  # the model cites it; it lies beyond the window
    pad_n = max(0, 1000 - sc.submission.index(last))
    if pad_n:
        sc.parts.insert(0, pad_text(lang, pad_n))
    cut = sc.submission.index(last)
    sc.bounds = {"max_submission_chars": cut}
    sc.flags["window"] = cut
    sc.expect(**{"x1__doc__PROTOCOL_DETAIL": "NOT_DOCUMENTED_IN_BOUND_INPUT", "errors": ["EXACT_EXCERPT_MISMATCH"]})
    return sc.finish()


@family("window.repeated_text_outside_window_does_not_ambiguate", "source_window")
def _w5(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng")
    sc.parts.append(pad_text(lang, 1000))
    cut = sc.submission.index(pad_text(lang, 1000)) + 1000
    sc.say(e.define)  # the same sentence again, beyond the window
    sc.result("RES_POS", declare=False)
    sc.bounds = {"max_submission_chars": cut}
    sc.flags["window"] = cut
    sc.expect(n_exp=1, x1__ndef=1, x1__posture="WELL_SPECIFIED")
    return sc.finish()


@family("window.result_straddling_window_end_is_withheld", "source_window")
def _w6(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng")
    sc.parts.append(pad_text(lang, 1000))
    res = sc.result("RES_POS")
    start = _start_of(sc, res)
    visible = 14
    sc.bounds = {"max_submission_chars": start + visible}
    sc.flags["window"] = start + visible
    sc.flags["straddling_result"] = res
    sc.expect(n_quar=1, quar_texts=[res[:visible]], later_prompt_leak=False, status="COMPLETED")
    return sc.finish()


@family("window.declared_result_fully_outside_window", "source_window")
def _w7(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng")
    sc.parts.append(pad_text(lang, 1000))
    res = sc.result("RES_POS")
    start = _start_of(sc, res)
    sc.bounds = {"max_submission_chars": start}
    sc.flags["window"] = start
    sc.flags["incomplete_quarantine"] = True
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, n_exp=0, calls=1, n_quar=0,
              errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"])
    return sc.finish(standard=False)


@family("window.replay_and_resume_keep_the_same_window", "source_window")
def _w8(lang: str) -> dict:
    sc = Sc(lang)
    sc.parts.append(pad_text(lang, 1000))
    e = sc.exp("eng")
    res = sc.result("RES_POS", declare=False)
    sc.bounds = {"max_submission_chars": _start_of(sc, res)}
    sc.flags["window"] = sc.bounds["max_submission_chars"]
    sc.expect(**{"replay.same": True, "replay.extra_calls": 0, "replay.resume_same": True, "n_exp": 1})
    return sc.finish(rerun=True, interrupt_before="EXPERIMENT_LINK_TARGETS")


@family("window.model_list_reordering_inside_window", "source_window")
def _w9(lang: str) -> dict:
    sc = Sc(lang)
    sc.parts.append(pad_text(lang, 1000))
    e = sc.exp("eng")
    res = sc.result("RES_POS", declare=False)
    sc.bounds = {"max_submission_chars": _start_of(sc, res)}
    sc.flags["window"] = sc.bounds["max_submission_chars"]
    sc.expect(**{"twin.order": True, "twin.ids": True})
    return sc.finish(twin="order")


# =========================================================================================================
# L. the execution boundary
# =========================================================================================================

EXEC = [("EXEC_RAN", "EXECUTION_DESCRIBED"), ("EXEC_20", "EXECUTION_DESCRIBED"), ("EXEC_PASSED", "EXECUTION_DESCRIBED"),
        ("EXEC_REPRO", "EXECUTION_DESCRIBED"), ("EXEC_LOGS", "EXECUTION_STATUS_NOT_DOCUMENTED"),
        ("EXEC_NOTEBOOK", "EXECUTION_STATUS_NOT_DOCUMENTED"), ("EXEC_RAWDATA", "EXECUTION_STATUS_NOT_DOCUMENTED"),
        ("EXEC_SCREENSHOT", "EXECUTION_STATUS_NOT_DOCUMENTED"), ("EXEC_LAUNCH", "EXECUTION_DESCRIBED"),
        ("EXEC_LEAK", "PLANNED_ONLY")]


def _exec(sid: str, status: str):
    def build(lang: str) -> dict:
        etype = "AI_ML_MODEL_EVALUATION" if sid == "EXEC_LEAK" else "ENGINEERING_BENCH_TEST"
        sc, e = mk(lang, etype, execution=status)
        sc.say(t(sid, lang))
        sc.result("RES_POS")
        sc.flags["exec_prose"] = True
        sc.expect(**{"x1__exec": status, "exec_flags_false": True, "x1__posture": "WELL_SPECIFIED"})
        return sc.finish()

    return build


for _i, (_sid, _st) in enumerate(EXEC):
    family(f"execution.{_sid.lower()}", "execution_boundary")(_exec(_sid, _st))
