"""Phase 3B Gold families, part 1: experiment types, segmentation and identity, missing protocol elements,
conditional applicability, target linkage and Phase 2J continuity."""

from __future__ import annotations

from typing import Any

from phase3b_gold_framework import GAPS, PTYPE_FOR_FAMILY, Exp, Sc, family
from phase3b_gold_lang import kind_text, t

from src.evals.experiment_review import catalog as cat

EN_AR = ("en", "ar")
EN_MX = ("en", "mixed")


def mk(lang: str, etype: str | None = None, *, flavor: str = "eng", ptype: str | None = None, gap: str = "default",
       tagged: bool = False, **kw: Any) -> tuple[Sc, Exp]:
    et = etype or {"eng": "ENGINEERING_BENCH_TEST"}.get(flavor)
    fam = cat.TYPE_FAMILY[et] if et else "ENGINEERING"
    sc = Sc(lang, ptype or PTYPE_FOR_FAMILY[fam], gap, tagged=tagged)
    e = sc.exp(flavor=flavor, etype=et, **kw)
    return sc, e


# =========================================================================================================
# A. every experiment type, fully documented
# =========================================================================================================


def _well(etype: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang, etype)
        sc.result("RES_POS")
        sc.truth = {"types": {"1": etype}}
        sc.expect(**{"x1__link__T1": "DIRECTLY_TESTS", "x1__meas__T1": "ALIGNED_SAME_TARGET", "x1__ndef": 1})
        return sc.finish()

    return build


for _i, _t in enumerate(cat.TYPES):
    family(f"type.well.{_t}", "experiment_type", EN_AR if _i % 2 else EN_MX)(_well(_t))

# =========================================================================================================
# B. a required protocol element is missing
# =========================================================================================================

MISSING = [
    ("ENGINEERING_BENCH_TEST", k) for k in (
        "OBJECTIVE", "SETUP", "ENVIRONMENT", "INPUTS", "OUTPUTS", "DEPENDENT_VARIABLE", "SAMPLE_DEFINITION",
        "SAMPLE_SIZE", "REPETITIONS", "MEASUREMENT_METHOD", "METRIC", "SUCCESS_CRITERION", "PROTOCOL_DETAIL",
        "TARGET_BINDING", "HYPOTHESIS_OR_VALIDATION_OBJECTIVE", "OPERATING_CONDITIONS")
] + [
    ("AI_ML_MODEL_EVALUATION", k) for k in (
        "TRAIN_TEST_SEPARATION", "TEST_SET_INDEPENDENCE", "DUPLICATE_LEAKAGE_CONTROL", "SEED_OR_REPEATABILITY")
] + [
    ("SOFTWARE_BENCHMARK", "WORKLOAD"), ("SOFTWARE_BENCHMARK", "WARM_UP"), ("SOFTWARE_BENCHMARK", "VERSION_INFORMATION"),
    ("SCIENTIFIC_CONTROLLED_EXPERIMENT", "CONTROL_STRATEGY"), ("SCIENTIFIC_CONTROLLED_EXPERIMENT", "CONFOUNDERS"),
    ("SCIENTIFIC_CONTROLLED_EXPERIMENT", "INDEPENDENT_VARIABLE"), ("SCIENTIFIC_CONTROLLED_EXPERIMENT", "SAMPLE_IDENTITY"),
    ("ENGINEERING_STRESS_TEST", "STRESS_AND_EDGE_CASES"), ("ENGINEERING_STRESS_TEST", "FAILURE_MODES"),
    ("ENGINEERING_COMPARATIVE_TEST", "BASELINE"), ("ENGINEERING_COMPARATIVE_TEST", "BASELINE_CONFIGURATION"),
    ("AI_ML_EXTERNAL_VALIDATION", "EXTERNAL_VALIDATION"), ("SOFTWARE_SECURITY_TEST", "SECURITY_TEST_CONDITIONS"),
    ("SOFTWARE_USABILITY_TEST", "INCLUSION_EXCLUSION_RULES"), ("AI_ML_ABLATION", "INDEPENDENT_VARIABLE"),
    ("AI_ML_ABLATION", "CONTROLLED_VARIABLES"), ("ENGINEERING_FIELD_TEST", "OPERATING_CONDITIONS"),
]


def _missing(etype: str, kind: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang, etype, missing=(kind,))
        sc.result("RES_POS")
        sc.expect(**{f"x1__doc__{kind}": "NOT_DOCUMENTED_IN_BOUND_INPUT", f"x1__app__{kind}": "REQUIRED"})
        sc.truth = {"missing": [kind]}
        return sc.finish()

    return build


for _i, (_t, _k) in enumerate(MISSING):
    family(f"missing.{_t}.{_k}", "missing_protocol_element", EN_AR if _i % 2 else EN_MX)(_missing(_t, _k))


@family("missing.many_required", "missing_protocol_element")
def _many(lang: str) -> dict:
    sc, e = mk(lang, missing=("SETUP", "INPUTS", "METRIC", "ENVIRONMENT"))
    sc.result("RES_POS")
    return sc.finish()


@family("type.unknown_stays_unresolved", "unknown_type")
def _unknown(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST")
    e.type = "UNKNOWN"
    e.required = [k for k in cat.KINDS if k in cat.UNIVERSAL]
    e.docs = {k: v for k, v in e.docs.items() if k in cat.UNIVERSAL}
    e.unresolved = True
    sc.result("RES_POS")
    sc.expect(**{"x1__type": "UNKNOWN", "x1__posture": "UNRESOLVED", "x1__app__OBJECTIVE": "REQUIRED",
                 "x1__basis__OBJECTIVE": "EXPERIMENT_TYPE_UNKNOWN", "x1__app__STATISTICAL_TEST": "CONDITIONAL",
                 "x1__app__BLINDING": "CONDITIONAL", "x1__issues": [], "calls": 3, "posture": "UNRESOLVED",
                 "track.ENGINEERING": "UNRESOLVED", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["COVERING_PROTOCOL_INADEQUATE", "MATERIAL_CONDITION_UNCOVERED"],
                 "status": "COMPLETED"})
    sc.truth = {"types": {"1": "ENGINEERING_BENCH_TEST"}}
    return sc.finish(standard=False)


@family("type.invalid_taxonomy_value", "unknown_type")
def _badtype(lang: str) -> dict:
    sc, e = mk(lang)
    e.type = "WIZARD_TEST"
    e.extract_extra = {}
    sc.result("RES_POS")
    sc.expect(**{"x1__type": "UNKNOWN", "x1__posture": "UNRESOLVED", "errors": ["PARTIAL_MODEL_OUTPUT"],
                 "x1__app__STATISTICAL_TEST": "CONDITIONAL", "status": "COMPLETED", "calls": 3})
    sc.truth = {"types": {"1": "ENGINEERING_BENCH_TEST"}}
    return sc.finish(standard=False)


@family("type.model_misclassifies", "experiment_type", EN_AR)
def _misclass(lang: str) -> dict:
    """The text is an observational study; the scripted model calls it a controlled experiment. The type
    judgment is bounded and measured, never proven (model-judgment ground truth in ``truth``)."""
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", flavor="obs", ptype="SCIENTIFIC_RESEARCH")
    e.define  # the text is the observational definition
    sc.result("RES_POS")
    sc.truth = {"types": {"1": "SCIENTIFIC_OBSERVATIONAL_STUDY"}}
    return sc.finish()


@family("type.confounding_bias_recognised", "scientific_bias")
def _confound(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", missing=("CONFOUNDERS", "MEASUREMENT_BIAS"))
    sc.result("RES_POS")
    sc.truth = {"bias_recognised": True}
    sc.expect(**{"x1__issues": ["BIAS_NOT_ADDRESSED_WHEN_REQUIRED"]})
    return sc.finish()


@family("type.reproducibility_detail_missing", "reproducibility")
def _repro(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST", missing=("PROTOCOL_DETAIL",))
    sc.result("RES_POS")
    sc.truth = {"reproducible": False}
    return sc.finish()


@family("type.reported_high_weak_protocol", "result_vs_protocol")
def _high_weak(lang: str) -> dict:
    sc, e = mk(lang, missing=("SAMPLE_SIZE", "SAMPLE_DEFINITION", "SETUP"))
    sc.result("RES_POS")
    sc.expect(**{"x1__posture": "MAJOR_GAPS"})
    return sc.finish()


@family("type.reported_poor_adequate_protocol", "result_vs_protocol")
def _poor_ok(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_NEG")
    sc.expect(**{"x1__posture": "WELL_SPECIFIED", "posture": "WELL_SPECIFIED"})
    return sc.finish()


# =========================================================================================================
# C. segmentation and identity
# =========================================================================================================


@family("seg.one_experiment", "segmentation")
def _seg1(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(n_exp=1, x1__ndef=1, trackn__ENGINEERING=1)
    return sc.finish()


@family("seg.no_experiment_requirement_uncovered", "segmentation")
def _seg0(lang: str) -> dict:
    sc = Sc(lang)
    sc.say(t("FILLER", lang))
    sc.say(t("FILLER3", lang))
    sc.result("RES_POS")
    sc.expect(n_exp=0, status="COMPLETED", calls=1, posture="MAJOR_GAPS", **{"cov.V1": "NOT_COVERED"},
              untested=["C-001"], **{"track.ENGINEERING": "MAJOR_GAPS"})
    return sc.finish(standard=False)


@family("seg.no_experiment_no_requirement", "segmentation")
def _seg0b(lang: str) -> dict:
    sc = Sc(lang, gap="no_requirement")
    sc.say(t("FILLER2", lang))
    sc.expect(n_exp=0, status="COMPLETED", calls=1, posture="INSUFFICIENT_EVIDENCE", untested=["C-001"],
              **{"track.ENGINEERING": "INSUFFICIENT_EVIDENCE"})
    return sc.finish(standard=False)


@family("seg.two_distinct_experiments", "segmentation")
def _seg2(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng")
    sc.result("RES_POS")
    e2.fired = {}
    sc.expect(n_exp=2, covering__V1=2, attempting__V1=2)
    return sc.finish()


@family("seg.three_distinct_experiments", "segmentation", EN_AR)
def _seg3(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    sc.exp("eng")
    sc.exp("eng")
    sc.result("RES_POS")
    sc.expect(n_exp=3, covering__V1=3)
    return sc.finish()


@family("seg.same_protocol_repeated_verbatim", "segmentation_identity")
def _seg_rep(lang: str) -> dict:
    """The defining sentence appears twice and the model reports two experiments: one protocol, recorded once."""
    sc, e = mk(lang)
    sc.say(e.define)
    sc.result("RES_POS")
    sc.segment_override = {"experiments": [
        {"label": "X1", "excerpts": [{"excerpt": e.define, "occurrence": 1}]},
        {"label": "X2", "excerpts": [{"excerpt": e.define, "occurrence": 2}]}],
        "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.expect(n_exp=1, x1__ndef=1)
    return sc.finish()


@family("seg.same_protocol_described_twice", "segmentation_identity")
def _seg_two_places(lang: str) -> dict:
    sc, e = mk(lang)
    again = sc.say(t("DEF_AGAIN", lang, n=1))
    sc.result("RES_POS")
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [e.define, again]}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.expect(n_exp=1, x1__ndef=2)
    return sc.finish()


@family("seg.changed_protocol_is_new_experiment", "segmentation_identity")
def _seg_rev(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng", define=t("DEF_REV", lang, n=2))
    sc.result("RES_POS")
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [e1.define]},
                                           {"label": "X2", "excerpts": [e2.define], "revision_of": "X1"}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.expect(n_exp=2, x1__revision=False, x2__revision=True)
    sc.expect(**{"covering.V1": 2})
    return sc.finish()


@family("seg.same_metric_different_experiment", "segmentation_identity")
def _seg_same_metric(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng", extra_docs={"METRIC": list(e1.docs["METRIC"])})
    sc.result("RES_POS")
    sc.expect(n_exp=2, x1__ndef=1, x2__ndef=1)
    sc.expect(**{"covering.V1": 2})
    return sc.finish()


@family("seg.same_claim_two_experiments", "segmentation")
def _seg_same_claim(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng", v1="DOES_NOT_TEST")
    e2.link = {"targets": {"T1": {"relation": "SUPPORTING_VALIDATION", "excerpts": []},
                           "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}}, "conditions": {}}
    e2.link_state = {"T1": ("SUPPORTING_VALIDATION", False), "V1": ("DOES_NOT_TEST", False)}
    e2.tested = False
    sc.result("RES_POS")
    sc.expect(n_exp=2, x1__posture="WELL_SPECIFIED", x2__posture="PARTIALLY_SPECIFIED")
    sc.expect(**{"covering.V1": 1, "attempting.V1": 1})
    return sc.finish()


@family("seg.one_experiment_two_targets", "segmentation")
def _seg_targets(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(x1__nlinks=2, x1__link__T1="DIRECTLY_TESTS", x1__link__V1="DIRECTLY_TESTS")
    return sc.finish()


@family("seg.unrelated_text_before_experiment", "segmentation_identity")
def _seg_before(lang: str) -> dict:
    sc = Sc(lang)
    sc.say(t("FILLER", lang))
    sc.say(t("FILLER2", lang))
    sc.exp("eng")
    sc.result("RES_POS")
    sc.expect(**{"twin.prefix": True, "twin.prefix_ids": True})
    return sc.finish(twin="prefix", twin_data={"prefix": t("FILLER3", lang) + " "})


@family("seg.offset_shift_keeps_identity", "segmentation_identity")
def _seg_shift(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(**{"twin.prefix": True, "twin.prefix_ids": True, "twin.prefix_keys": True})
    return sc.finish(twin="prefix", twin_data={"prefix": " ".join(t(x, lang) for x in ("FILLER", "FILLER2", "FILLER3")) + " "})


@family("seg.repeated_defining_with_occurrence", "segmentation_identity")
def _seg_occ(lang: str) -> dict:
    sc, e = mk(lang)
    sc.say(e.define)  # the defining sentence is repeated verbatim later
    sc.result("RES_POS")
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [{"excerpt": e.define, "occurrence": 1}]}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.expect(n_exp=1, x1__ndef=1)
    sc.flags["ambiguous"] = []
    return sc.finish()


@family("seg.repeated_defining_without_occurrence", "segmentation_identity")
def _seg_amb(lang: str) -> dict:
    sc, e = mk(lang)
    sc.say(e.define)
    sc.result("RES_POS")
    sc.flags["ambiguous"] = [e.define]
    sc.expect(n_exp=0, errors=["AMBIGUOUS_EXCERPT", "PARTIAL_MODEL_OUTPUT"], rejected=["AMBIGUOUS_EXCERPT",
              "PARTIAL_MODEL_OUTPUT"], posture="MAJOR_GAPS", calls=1, status="COMPLETED")
    return sc.finish(standard=False)


@family("seg.experiment_bound_reached", "segmentation_bound")
def _seg_bound(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    sc.exp("eng")
    sc.exp("eng")
    sc.result("RES_POS")
    sc.bounds = {"max_experiments": 2}
    sc.expect(n_exp=2, status="INSUFFICIENT_INPUT", posture=None, errors=["EXPERIMENT_BOUND_REACHED"])
    return sc.finish(standard=False)


@family("seg.fabricated_defining_excerpt", "segmentation_provenance")
def _seg_fab(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    fake = "Experiment 7 was run in a secret laboratory that is not in the submission."
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [e.define]},
                                           {"label": "X2", "excerpts": [fake]}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.flags["fabricated"] = [fake]
    sc.expect(n_exp=1, errors=["EXACT_EXCERPT_MISMATCH", "PARTIAL_MODEL_OUTPUT"])
    return sc.finish()


# =========================================================================================================
# D. conditional applicability (statistics, bias, instruments, AI/ML, repetition)
# =========================================================================================================

# (family id, experiment type, kind, fired triggers, documented?)
APPL = [
    ("stat_test.fired", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "STATISTICAL_TEST", ["STATISTICAL_INFERENCE_CLAIMED"], True),
    ("stat_test.fired_undocumented", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "STATISTICAL_TEST", ["STATISTICAL_INFERENCE_CLAIMED"], False),
    ("confidence_interval.fired", "ENGINEERING_BENCH_TEST", "CONFIDENCE_INTERVAL", ["GENERALIZATION_CLAIMED"], True),
    ("confidence_interval.fired_undocumented", "ENGINEERING_BENCH_TEST", "CONFIDENCE_INTERVAL", ["STATISTICAL_INFERENCE_CLAIMED"], False),
    ("effect_size.fired", "AI_ML_MODEL_EVALUATION", "EFFECT_SIZE", ["STATISTICAL_INFERENCE_CLAIMED"], True),
    ("test_assumptions.fired", "SOFTWARE_BENCHMARK", "TEST_ASSUMPTIONS", ["STATISTICAL_INFERENCE_CLAIMED"], True),
    ("multiple_comparisons.fired", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "MULTIPLE_COMPARISONS", ["MULTIPLE_COMPARISONS_MADE"], True),
    ("multiple_comparisons.fired_undocumented", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "MULTIPLE_COMPARISONS", ["MULTIPLE_COMPARISONS_MADE"], False),
    ("outlier_handling.fired", "ENGINEERING_BENCH_TEST", "OUTLIER_HANDLING", ["QUANTITATIVE_MEASUREMENT"], True),
    ("power.fired", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "POWER_OR_SAMPLE_ADEQUACY", ["STATISTICAL_INFERENCE_CLAIMED"], True),
    ("blinding.fired", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "BLINDING", ["SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT"], True),
    ("blinding.fired_undocumented", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "BLINDING", ["HUMAN_PARTICIPANTS"], False),
    ("randomization.fired", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "RANDOMIZATION", ["ASSIGNED_INTERVENTION"], True),
    ("randomization.fired_undocumented", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "RANDOMIZATION", ["ASSIGNED_INTERVENTION"], False),
    ("calibration.fired", "ENGINEERING_BENCH_TEST", "CALIBRATION", ["PHYSICAL_INSTRUMENT"], True),
    ("calibration.fired_undocumented", "ENGINEERING_BENCH_TEST", "CALIBRATION", ["PHYSICAL_INSTRUMENT"], False),
    ("resolution.fired_undocumented", "ENGINEERING_BENCH_TEST", "MEASUREMENT_RESOLUTION", ["PHYSICAL_INSTRUMENT"], False),
    ("uncertainty.fired_undocumented", "ENGINEERING_FIELD_TEST", "MEASUREMENT_UNCERTAINTY", ["QUANTITATIVE_MEASUREMENT"], False),
    ("tolerance.fired", "ENGINEERING_BENCH_TEST", "TOLERANCE", ["QUANTITATIVE_MEASUREMENT"], True),
    ("tuning_isolation.fired", "AI_ML_MODEL_EVALUATION", "TUNING_ISOLATION", ["MODEL_TUNING_PERFORMED"], True),
    ("tuning_isolation.fired_undocumented", "AI_ML_MODEL_EVALUATION", "TUNING_ISOLATION", ["MODEL_TUNING_PERFORMED"], False),
    ("benchmark_contamination.fired_undocumented", "AI_ML_MODEL_EVALUATION", "BENCHMARK_CONTAMINATION", ["PUBLIC_BENCHMARK_USED"], False),
    ("class_imbalance.fired", "AI_ML_MODEL_EVALUATION", "CLASS_IMBALANCE", ["IMBALANCED_LABELS"], True),
    ("repetitions.stochastic_ai", "AI_ML_MODEL_EVALUATION", "REPETITIONS", ["STOCHASTIC_PROCESS"], True),
    ("repetitions.stochastic_ai_undocumented", "AI_ML_MODEL_EVALUATION", "REPETITIONS", ["STOCHASTIC_PROCESS"], False),
    ("repetition_independence.fired", "AI_ML_MODEL_EVALUATION", "REPETITION_INDEPENDENCE", ["REPLICATION_RELIED_ON"], True),
    ("safety_controls.fired_undocumented", "ENGINEERING_FIELD_TEST", "SAFETY_CONTROLS", ["SAFETY_RELEVANT"], False),
    ("privacy.fired_undocumented", "SOFTWARE_USABILITY_TEST", "PRIVACY_CONSTRAINTS", ["PERSONAL_DATA_PROCESSED"], False),
    ("human_constraints.fired", "SOFTWARE_USABILITY_TEST", "HUMAN_ANIMAL_DATA_CONSTRAINTS", ["HUMAN_PARTICIPANTS"], True),
    ("external_validation.fired_undocumented", "SCIENTIFIC_CONTROLLED_EXPERIMENT", "EXTERNAL_VALIDATION", ["GENERALIZATION_CLAIMED"], False),
    ("selection_bias.fired_undocumented", "AI_ML_MODEL_EVALUATION", "SELECTION_BIAS", ["DATASET_USED"], False),
]


def _appl(etype: str, kind: str, fired: list[str], documented: bool):
    def build(lang: str) -> dict:
        sc, e = mk(lang, etype, fired={kind: fired}, missing=() if documented else (kind,))
        sc.result("RES_POS")
        expect = {f"x1__app__{kind}": "REQUIRED", f"x1__basis__{kind}": "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                  f"x1__triggers__{kind}": sorted(fired),
                  f"x1__doc__{kind}": "EXPLICITLY_DOCUMENTED" if documented else "NOT_DOCUMENTED_IN_BOUND_INPUT"}
        sc.expect(**expect)
        sc.truth = {"fired": {kind: fired}}
        return sc.finish()

    return build


for _i, (_f, _t, _k, _fi, _d) in enumerate(APPL):
    family(f"applic.{_f}.{_t}", "conditional_applicability", EN_AR if _i % 2 else EN_MX)(_appl(_t, _k, _fi, _d))

NOT_FIRED = [("STATISTICAL_TEST", "SCIENTIFIC_CONTROLLED_EXPERIMENT"), ("BLINDING", "SCIENTIFIC_CONTROLLED_EXPERIMENT"),
             ("CALIBRATION", "ENGINEERING_BENCH_TEST"), ("CLASS_IMBALANCE", "AI_ML_MODEL_EVALUATION"),
             ("RANDOMIZATION", "SCIENTIFIC_CONTROLLED_EXPERIMENT"), ("MULTIPLE_COMPARISONS", "SOFTWARE_BENCHMARK"),
             ("CONFIDENCE_INTERVAL", "SIMULATION"), ("EFFECT_SIZE", "OTHER_BOUNDED_EXPERIMENT")]


def _not_fired(kind: str, etype: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang, etype)
        sc.result("RES_POS")
        sc.expect(**{f"x1__app__{kind}": "NOT_APPLICABLE", f"x1__basis__{kind}": "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                     f"x1__doc__{kind}": "NOT_APPLICABLE", f"x1__posture": "WELL_SPECIFIED"})
        sc.flags["no_inference"] = True
        sc.truth = {"not_applicable": [kind]}
        return sc.finish()

    return build


for _i, (_k, _t) in enumerate(NOT_FIRED):
    family(f"applic.not_fired.{_k}.{_t}", "conditional_applicability_not_triggered",
           EN_AR if _i % 2 else EN_MX)(_not_fired(_k, _t))


@family("applic.omitted_judgment_stays_conditional", "conditional_applicability")
def _omit(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", omit_app=True)
    sc.result("RES_POS")
    sc.expect(**{"x1__app__STATISTICAL_TEST": "CONDITIONAL", "x1__app__BLINDING": "CONDITIONAL",
                 "x1__posture": "UNRESOLVED", "x1__basis__STATISTICAL_TEST": "CONDITION_UNRESOLVED"})
    return sc.finish()


@family("applic.judgment_without_excerpts", "conditional_applicability")
def _noex(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT")
    e.app_override = {"STATISTICAL_TEST": {"fired": ["STATISTICAL_INFERENCE_CLAIMED"], "excerpts": []}}
    e.unresolved = True
    sc.result("RES_POS")
    sc.expect(**{"x1__app__STATISTICAL_TEST": "CONDITIONAL", "x1__judged__STATISTICAL_TEST": False,
                 "x1__posture": "UNRESOLVED"})
    return sc.finish()


@family("applic.trigger_outside_closed_set", "conditional_applicability")
def _outside(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT")
    e.app_override = {"STATISTICAL_TEST": {"fired": ["HUMAN_PARTICIPANTS"], "excerpts": ["E1"]}}
    e.unresolved = True
    sc.result("RES_POS")
    sc.expect(**{"x1__app__STATISTICAL_TEST": "CONDITIONAL", "x1__posture": "UNRESOLVED",
                 "errors": ["PARTIAL_MODEL_OUTPUT"], "rejected": ["PARTIAL_MODEL_OUTPUT"]})
    return sc.finish()


@family("applic.judgment_for_unasked_kind", "conditional_applicability")
def _unasked(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST")
    e.app_override = {"OBJECTIVE": {"fired": [], "excerpts": ["E1"]}}  # OBJECTIVE is REQUIRED, never asked
    sc.result("RES_POS")
    sc.expect(**{"x1__app__OBJECTIVE": "REQUIRED", "x1__basis__OBJECTIVE": "CATALOG_DEFAULT",
                 "errors": ["INVENTED_REQUIREMENT"]})
    return sc.finish()


@family("applic.invented_requirement_kind", "invented_requirement")
def _invented(lang: str) -> dict:
    sc, e = mk(lang)
    e.docs = {**e.docs, "MAGIC_REQUIREMENT": [t("DETAIL", lang)]}
    sc.result("RES_POS")
    sc.expect(**{"errors": ["INVENTED_REQUIREMENT"], "rejected": ["INVENTED_REQUIREMENT"], "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("applic.required_row_never_lowered", "conditional_applicability")
def _never_lower(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST")
    e.app_override = {"OBJECTIVE": {"fired": [], "excerpts": ["E1"]}, "SETUP": {"fired": [], "excerpts": ["E1"]}}
    sc.result("RES_POS")
    sc.expect(**{"x1__app__OBJECTIVE": "REQUIRED", "x1__app__SETUP": "REQUIRED"})
    return sc.finish()


@family("applic.phase2j_baseline_trigger", "conditional_applicability")
def _p2j_base(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST", gap="baseline")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__BASELINE": "REQUIRED", "x1__basis__BASELINE": "PHASE_2J_VALIDATION_REQUIREMENT",
                 "x1__triggers__BASELINE": ["PHASE_2J_BASELINE_REQUIRED"], "x1__bl__V1": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                 "x1__blmatch__V1": "SAME_AS_PHASE_2J"})
    return sc.finish()


@family("applic.no_phase2j_baseline_not_required", "conditional_applicability")
def _p2j_nobase(lang: str) -> dict:
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__BASELINE": "NOT_APPLICABLE", "x1__doc__BASELINE": "NOT_APPLICABLE"})
    return sc.finish()


@family("applic.improvement_claim_requires_baseline", "baseline_required_guard")
def _improve(lang: str) -> dict:
    fired = {"BASELINE": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "BASELINE_CONFIGURATION": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"]}
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST", fired=fired)
    sc.result("RES_POS")
    sc.flags["improvement_claim"] = True
    sc.expect(**{"x1__app__BASELINE": "REQUIRED", "x1__basis__BASELINE": "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                 "x1__doc__BASELINE": "EXPLICITLY_DOCUMENTED"})
    return sc.finish()


@family("applic.improvement_claim_baseline_absent", "baseline_required_guard")
def _improve_missing(lang: str) -> dict:
    fired = {"BASELINE": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"], "BASELINE_CONFIGURATION": ["IMPROVEMENT_OR_COMPARATIVE_CLAIM"]}
    sc, e = mk(lang, "ENGINEERING_BENCH_TEST", fired=fired, missing=("BASELINE", "BASELINE_CONFIGURATION"))
    sc.result("RES_POS")
    sc.flags["improvement_claim"] = True
    sc.flags["baseline_required_missing"] = True
    sc.expect(**{"x1__issues": ["BASELINE_MISSING_WHEN_REQUIRED"], "x1__posture": "MAJOR_GAPS",
                 "x1__doc__BASELINE": "NOT_DOCUMENTED_IN_BOUND_INPUT"})
    return sc.finish()


@family("applic.control_required_for_assigned_intervention", "baseline_required_guard", EN_AR)
def _control(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_OBSERVATIONAL_STUDY", ptype="SCIENTIFIC_RESEARCH",
               fired={"CONTROL_STRATEGY": ["ASSIGNED_INTERVENTION"]}, missing=("CONTROL_STRATEGY",))
    sc.result("RES_POS")
    sc.expect(**{"x1__issues": ["CONTROL_MISSING_WHEN_REQUIRED"], "x1__posture": "MAJOR_GAPS",
                 "x1__app__RANDOMIZATION": "NOT_APPLICABLE", "x1__basis__RANDOMIZATION": "CATALOG_TYPE_OVERRIDE"})
    return sc.finish()


@family("applic.catalog_override_observational_no_randomization", "conditional_applicability", EN_MX)
def _obs_rand(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_OBSERVATIONAL_STUDY", ptype="SCIENTIFIC_RESEARCH")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__RANDOMIZATION": "NOT_APPLICABLE", "x1__basis__RANDOMIZATION": "CATALOG_TYPE_OVERRIDE",
                 "x1__app__CONTROL_STRATEGY": "NOT_APPLICABLE"})
    return sc.finish()


# =========================================================================================================
# E. target linkage and measurement alignment
# =========================================================================================================


def _link_case(lang: str, *, etype: str = "ENGINEERING_BENCH_TEST", gap: str = "default", **kw: Any):
    sc, e = mk(lang, etype, gap=gap, **kw)
    sc.result("RES_POS")
    return sc, e


@family("link.directly_tests_aligned", "claim_experiment_linkage")
def _l1(lang: str) -> dict:
    sc, e = _link_case(lang)
    sc.expect(**{"x1__link__T1": "DIRECTLY_TESTS", "x1__link__V1": "DIRECTLY_TESTS", "x1__meas__T1": "ALIGNED_SAME_TARGET",
                 "x1__meas__V1": "ALIGNED_SAME_TARGET", "x1__match__V1": "SAME_AS_PHASE_2J",
                 "x1__match__T1": "NO_PHASE_2J_ANCHOR", "x1__timing__T1": "PRE_SPECIFIED_AS_DESCRIBED"})
    sc.truth = {"links": {"T1": "DIRECTLY_TESTS", "V1": "DIRECTLY_TESTS"}, "alignment": {"T1": "ALIGNED_SAME_TARGET"}}
    return sc.finish()


@family("link.directly_tests_without_measurement", "metric_target_guard")
def _l2(lang: str) -> dict:
    sc, e = _link_case(lang)
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    e.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e.tested = False
    sc.flags["guard"] = "directly_without_measurement"
    sc.expect(**{"x1__link__T1": "PARTIALLY_TESTS", "x1__link__V1": "PARTIALLY_TESTS", "x1__meas__T1": "ABSENT",
                 "x1__posture": "PARTIALLY_SPECIFIED"})
    sc.truth = {"links": {"T1": "DIRECTLY_TESTS"}}
    return sc.finish()


@family("link.metric_without_method", "metric_target_guard")
def _l3(lang: str) -> dict:
    sc, e = _link_case(lang)
    m = e.measured(method=None)
    m.pop("method", None)
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": m},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": m}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    e.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e.tested = False
    sc.expect(**{"x1__meas__T1": "MEASUREMENT_METHOD_NOT_DEFINED", "x1__link__T1": "PARTIALLY_TESTS"})
    return sc.finish()


@family("link.method_without_metric", "metric_target_guard")
def _l4(lang: str) -> dict:
    sc, e = _link_case(lang)
    m = e.measured()
    m.pop("metric", None)
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": m},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": m}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    e.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e.tested = False
    sc.expect(**{"x1__meas__T1": "METRIC_NOT_DEFINED", "x1__link__T1": "PARTIALLY_TESTS"})
    return sc.finish()


@family("link.metric_wrong_target", "metric_target_alignment")
def _l5(lang: str) -> dict:
    sc, e = _link_case(lang, extra_docs={"METRIC": [t("METRIC_OTHER", lang)], "MEASUREMENT_METHOD": [t("METHOD_OTHER", lang)]})
    mm = {"method": t("METHOD_OTHER", lang), "metric": t("METRIC_OTHER", lang), "criterion": e.text("SUCCESS_CRITERION"),
          "alignment": "METRIC_TARGET_MISMATCH", "match": "DIFFERENT_FROM_PHASE_2J"}
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    e.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e.meas_issue = ["METRIC_TARGET_MISMATCH"]
    e.tested = False
    sc.flags["metric_wrong_target"] = True
    sc.truth = {"alignment": {"V1": "METRIC_TARGET_MISMATCH"}, "match": {"V1": "DIFFERENT_FROM_PHASE_2J"}}
    sc.expect(**{"x1__meas__V1": "METRIC_TARGET_MISMATCH", "x1__match__V1": "DIFFERENT_FROM_PHASE_2J",
                 "x1__link__V1": "PARTIALLY_TESTS", "x1__posture": "MAJOR_GAPS", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["COVERING_PROTOCOL_INADEQUATE", "METRIC_TARGET_MISMATCH",
                                   "PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"]})
    return sc.finish()


@family("link.metric_wrong_target_model_misses", "metric_target_alignment")
def _l5b(lang: str) -> dict:
    """The experiment measures energy use, not the Phase 2J accuracy metric; the scripted model wrongly says it
    is the same target. The deterministic guards accept an aligned binding; the semantic error is MEASURED."""
    sc, e = _link_case(lang, extra_docs={"METRIC": [t("METRIC_OTHER", lang)], "MEASUREMENT_METHOD": [t("METHOD_OTHER", lang)]})
    mm = {"method": t("METHOD_OTHER", lang), "metric": t("METRIC_OTHER", lang), "criterion": e.text("SUCCESS_CRITERION")}
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    sc.truth = {"alignment": {"V1": "METRIC_TARGET_MISMATCH"}, "match": {"V1": "DIFFERENT_FROM_PHASE_2J"},
                "links": {"V1": "PARTIALLY_TESTS"}}
    return sc.finish()


@family("link.metric_from_other_experiment_refused", "metric_target_alignment")
def _l6(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng")
    sc.result("RES_POS")
    m = e2.measured(metric=e1.text("METRIC"))
    e2.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": m},
                           "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": m}},
               "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e2.text("OPERATING_CONDITIONS")]}}}
    e2.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e2.tested = False
    sc.flags["metric_from_other_experiment"] = True
    sc.expect(**{"x2__meas__T1": "METRIC_NOT_DEFINED", "x2__link__T1": "PARTIALLY_TESTS", "x1__posture": "WELL_SPECIFIED",
                 "errors": ["EXACT_EXCERPT_MISMATCH"], "rejected": ["EXACT_EXCERPT_MISMATCH"],
                 "cov.V1": "COVERED_BY_EXPERIMENT"})
    return sc.finish()


@family("link.excerpt_label_from_other_experiment", "metric_target_alignment", EN_AR)
def _l6b(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng")
    sc.result("RES_POS")
    e2.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e1.define], "measurement": e2.measured()},
                           "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": e2.measured()}},
               "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e2.text("OPERATING_CONDITIONS")]}}}
    e2.link_state["T1"] = ("UNRESOLVED", False)
    sc.expect(**{"x2__link__T1": "UNRESOLVED", "x2__link__V1": "DIRECTLY_TESTS", "errors": ["EXACT_EXCERPT_MISMATCH"]})
    return sc.finish()


@family("link.omitted_requirement_target_unresolved", "claim_experiment_linkage")
def _l7(lang: str) -> dict:
    sc, e = _link_case(lang)
    d = e.default_link()
    del d["targets"]["V1"]
    e.link = d
    e.link_state["V1"] = ("UNRESOLVED", False)
    sc.flags["omitted_target"] = True
    sc.expect(**{"x1__link__V1": "UNRESOLVED", "cov.V1": "UNRESOLVED", "covreasons.V1": ["LINKAGE_UNRESOLVED"],
                 "errors": ["PARTIAL_MODEL_OUTPUT"], "posture": "UNRESOLVED", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("link.omitted_claim_target_unresolved", "claim_experiment_linkage")
def _l8(lang: str) -> dict:
    sc, e = _link_case(lang)
    d = e.default_link()
    del d["targets"]["T1"]
    e.link = d
    e.link_state["T1"] = ("UNRESOLVED", False)
    sc.flags["omitted_target"] = True
    sc.expect(**{"x1__link__T1": "UNRESOLVED", "x1__link__V1": "DIRECTLY_TESTS", "errors": ["PARTIAL_MODEL_OUTPUT"],
                 "x1__posture": "WELL_SPECIFIED", "untested": []})
    return sc.finish()


@family("link.foreign_target_id", "target_identity")
def _l9(lang: str) -> dict:
    sc, e = _link_case(lang)
    d = e.default_link()
    d["targets"]["T9"] = {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": e.measured()}
    e.link = d
    sc.flags["foreign_target"] = "T9"
    sc.expect(**{"errors": ["UNKNOWN_TARGET"], "rejected": ["UNKNOWN_TARGET"], "x1__nlinks": 2,
                 "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("link.cross_run_target_id", "target_identity")
def _l10(lang: str) -> dict:
    sc, e = _link_case(lang)
    d = e.default_link()
    d["targets"]["6f1c2a9e-8b7d-4c3a-9e21-3d5f7a8b9c01"] = {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]}
    e.link = d
    sc.flags["cross_run_target"] = "6f1c2a9e-8b7d-4c3a-9e21-3d5f7a8b9c01"
    sc.expect(**{"errors": ["CROSS_RUN_REFERENCE"], "rejected": ["CROSS_RUN_REFERENCE"], "x1__nlinks": 2})
    return sc.finish()


@family("link.does_not_test_target", "claim_experiment_linkage")
def _l11(lang: str) -> dict:
    sc, e = _link_case(lang, v1="DOES_NOT_TEST")
    e.link = {"targets": {"T1": {"relation": "DOES_NOT_TEST", "excerpts": []}, "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}},
              "conditions": {}}
    e.link_state = {"T1": ("DOES_NOT_TEST", False), "V1": ("DOES_NOT_TEST", False)}
    e.extra_issues = ["EXPERIMENT_DOES_NOT_TEST_TARGET"]
    e.tested = False
    sc.truth = {"links": {"T1": "DOES_NOT_TEST", "V1": "DOES_NOT_TEST"}}
    sc.expect(**{"x1__posture": "PARTIALLY_SPECIFIED", "cov.V1": "NOT_COVERED", "posture": "MAJOR_GAPS",
                 "untested": ["C-001"], "covreasons.V1": ["PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"]})
    return sc.finish()


@family("link.supporting_validation_only", "claim_experiment_linkage")
def _l12(lang: str) -> dict:
    sc, e = _link_case(lang, v1="SUPPORTING_VALIDATION")
    e.link = {"targets": {"T1": {"relation": "SUPPORTING_VALIDATION", "excerpts": []},
                          "V1": {"relation": "SUPPORTING_VALIDATION", "excerpts": []}}, "conditions": {}}
    e.link_state = {"T1": ("SUPPORTING_VALIDATION", False), "V1": ("SUPPORTING_VALIDATION", False)}
    e.tested = False
    sc.truth = {"links": {"T1": "SUPPORTING_VALIDATION", "V1": "SUPPORTING_VALIDATION"}}
    sc.expect(**{"x1__posture": "PARTIALLY_SPECIFIED", "cov.V1": "NOT_COVERED", "untested": ["C-001"]})
    return sc.finish()


@family("link.partially_tests_with_aligned_measurement", "claim_experiment_linkage")
def _l13(lang: str) -> dict:
    sc, e = _link_case(lang, v1="PARTIALLY_TESTS")
    d = e.default_link()
    d["targets"]["T1"]["relation"] = "PARTIALLY_TESTS"
    e.link = d
    e.link_state = {"T1": ("PARTIALLY_TESTS", True), "V1": ("PARTIALLY_TESTS", True)}
    e.tested = False
    sc.truth = {"links": {"T1": "PARTIALLY_TESTS", "V1": "PARTIALLY_TESTS"}}
    sc.expect(**{"x1__posture": "PARTIALLY_SPECIFIED", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"]})
    return sc.finish()


@family("link.all_unresolved", "claim_experiment_linkage")
def _l14(lang: str) -> dict:
    sc, e = _link_case(lang, v1="UNRESOLVED")
    e.link = {"targets": {"T1": {"relation": "UNRESOLVED", "excerpts": []}, "V1": {"relation": "UNRESOLVED", "excerpts": []}},
              "conditions": {}}
    e.link_state = {"T1": ("UNRESOLVED", False), "V1": ("UNRESOLVED", False)}
    e.unresolved = True
    e.tested = False
    sc.expect(**{"x1__posture": "UNRESOLVED", "cov.V1": "UNRESOLVED", "untested": ["C-001"]})
    return sc.finish()


@family("link.testing_relation_without_excerpts", "claim_experiment_linkage")
def _l15(lang: str) -> dict:
    sc, e = _link_case(lang)
    d = e.default_link()
    d["targets"]["T1"]["excerpts"] = []
    e.link = d
    e.link_state["T1"] = ("UNRESOLVED", False)
    sc.expect(**{"x1__link__T1": "UNRESOLVED", "x1__lnex__V1": 1, "x1__link__V1": "DIRECTLY_TESTS"})
    return sc.finish()


def _unrelated(model_right: bool):
    def build(lang: str) -> dict:
        sc = Sc(lang)
        e = sc.exp("eng", define=t("DEF_other", lang, n=1), v1="DOES_NOT_TEST" if model_right else "DIRECTLY_TESTS")
        sc.result("RES_POS")
        if model_right:
            e.link = {"targets": {"T1": {"relation": "DOES_NOT_TEST", "excerpts": []},
                                  "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}}, "conditions": {}}
            e.link_state = {"T1": ("DOES_NOT_TEST", False), "V1": ("DOES_NOT_TEST", False)}
            e.extra_issues = ["EXPERIMENT_DOES_NOT_TEST_TARGET"]
            e.tested = False
            sc.expect(**{"x1__link__T1": "DOES_NOT_TEST", "cov.V1": "NOT_COVERED"})
        else:
            sc.expect(**{"x1__link__T1": "DIRECTLY_TESTS"})
        sc.truth = {"links": {"T1": "DOES_NOT_TEST", "V1": "DOES_NOT_TEST"}}
        return sc.finish()

    return build


family("link.unrelated_experiment_model_correct", "claim_experiment_linkage")(_unrelated(True))
family("link.unrelated_experiment_model_wrong", "claim_experiment_linkage")(_unrelated(False))


@family("link.sophisticated_unrelated_target", "claim_experiment_linkage", EN_AR)
def _l16(lang: str) -> dict:
    sc = Sc(lang)
    e = sc.exp("eng", define=t("DEF_other", lang, n=1), v1="DOES_NOT_TEST")
    sc.result("RES_POS")
    e.link = {"targets": {"T1": {"relation": "DOES_NOT_TEST", "excerpts": []}, "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}},
              "conditions": {}}
    e.link_state = {"T1": ("DOES_NOT_TEST", False), "V1": ("DOES_NOT_TEST", False)}
    e.extra_issues = ["EXPERIMENT_DOES_NOT_TEST_TARGET"]
    e.tested = False
    sc.truth = {"links": {"T1": "DOES_NOT_TEST"}}
    sc.expect(**{"x1__posture": "PARTIALLY_SPECIFIED", "posture": "MAJOR_GAPS"})
    return sc.finish()


@family("link.correct_target_weak_protocol", "claim_experiment_linkage")
def _l17(lang: str) -> dict:
    sc, e = _link_case(lang, missing=("SETUP", "INPUTS", "OUTPUTS", "ENVIRONMENT"))
    sc.expect(**{"x1__posture": "MAJOR_GAPS", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["COVERING_PROTOCOL_INADEQUATE"], "x1__link__V1": "DIRECTLY_TESTS"})
    return sc.finish()


@family("link.unit_mismatch_flagged", "measurement")
def _l18(lang: str) -> dict:
    sc, e = _link_case(lang, extra_docs={"UNITS": [t("UNIT", lang)], "METRIC": [t("METRIC_OTHER", lang)],
                                         "MEASUREMENT_METHOD": [t("METHOD_OTHER", lang)]},
                       fired={"UNITS": ["QUANTITATIVE_MEASUREMENT"]})
    mm = {"method": t("METHOD_OTHER", lang), "metric": t("METRIC_OTHER", lang), "unit": t("UNIT", lang),
          "criterion": e.text("SUCCESS_CRITERION"), "alignment": "METRIC_TARGET_MISMATCH", "match": "DIFFERENT_FROM_PHASE_2J"}
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    e.link_state = {"T1": ("PARTIALLY_TESTS", False), "V1": ("PARTIALLY_TESTS", False)}
    e.meas_issue = ["METRIC_TARGET_MISMATCH"]
    e.tested = False
    sc.truth = {"alignment": {"V1": "METRIC_TARGET_MISMATCH"}}
    sc.expect(**{"x1__meas__V1": "METRIC_TARGET_MISMATCH"})
    return sc.finish()


@family("link.unit_mismatch_missed_by_model", "measurement")
def _l18b(lang: str) -> dict:
    sc, e = _link_case(lang, extra_docs={"UNITS": [t("UNIT", lang)], "METRIC": [t("METRIC_OTHER", lang)],
                                         "MEASUREMENT_METHOD": [t("METHOD_OTHER", lang)]},
                       fired={"UNITS": ["QUANTITATIVE_MEASUREMENT"]})
    mm = {"method": t("METHOD_OTHER", lang), "metric": t("METRIC_OTHER", lang), "unit": t("UNIT", lang),
          "criterion": e.text("SUCCESS_CRITERION")}
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
    sc.truth = {"alignment": {"V1": "METRIC_TARGET_MISMATCH"}}
    return sc.finish()


@family("measure.success_criterion_missing", "measurement")
def _m1(lang: str) -> dict:
    sc, e = _link_case(lang, missing=("SUCCESS_CRITERION",))
    sc.expect(**{"x1__issues": ["SUCCESS_CRITERION_MISSING"], "x1__posture": "MAJOR_GAPS", "x1__timing__T1": "TIMING_NOT_DOCUMENTED"})
    return sc.finish()


def _timing(sid: str, model_says: str, truth: str, issues: list[str], posture: str):
    def build(lang: str) -> dict:
        crit = t(sid, lang)
        sc, e = _link_case(lang, extra_docs={"SUCCESS_CRITERION": [crit]})
        mm = e.measured(timing=model_says, criterion=crit)
        e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm},
                              "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}},
                  "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}}}
        e.extra_issues = list(issues)
        sc.truth = {"timing": {"T1": truth}}
        sc.expect(**{"x1__timing__T1": model_says, "x1__posture": posture})
        return sc.finish()

    return build


family("measure.criterion_pre_specified", "success_criterion_timing")(
    _timing("CRITERION", "PRE_SPECIFIED_AS_DESCRIBED", "PRE_SPECIFIED_AS_DESCRIBED", [], "WELL_SPECIFIED"))
family("measure.criterion_set_after_results", "success_criterion_timing")(
    _timing("CRITERION_POST", "POST_HOC_AS_DESCRIBED", "POST_HOC_AS_DESCRIBED", ["SUCCESS_CRITERION_POST_HOC"], "MAJOR_GAPS"))
family("measure.criterion_timing_ambiguous", "success_criterion_timing")(
    _timing("CRITERION_AMBIG", "TIMING_NOT_DOCUMENTED", "TIMING_NOT_DOCUMENTED", [], "WELL_SPECIFIED"))
family("measure.criterion_post_hoc_missed_by_model", "success_criterion_timing")(
    _timing("CRITERION_POST", "PRE_SPECIFIED_AS_DESCRIBED", "POST_HOC_AS_DESCRIBED", [], "WELL_SPECIFIED"))
family("measure.criterion_pre_over_flagged", "success_criterion_timing", EN_AR)(
    _timing("CRITERION", "POST_HOC_AS_DESCRIBED", "PRE_SPECIFIED_AS_DESCRIBED", ["SUCCESS_CRITERION_POST_HOC"], "MAJOR_GAPS"))


# =========================================================================================================
# F. Phase 2J continuity
# =========================================================================================================


def _cont_case(lang: str, gap: str = "default", **kw: Any):
    sc, e = mk(lang, gap=gap, **kw)
    sc.result("RES_POS")
    return sc, e


def _set_link(e: Exp, targets: dict[str, Any], conditions: dict[str, Any] | None = None) -> None:
    d = e.default_link()
    d["targets"].update(targets)
    if conditions is not None:
        d["conditions"] = conditions
    e.link = d


@family("cont.exact_validation_requirement_match", "phase2j_continuity")
def _c1(lang: str) -> dict:
    sc, e = _cont_case(lang)
    sc.expect(**{"cov.V1": "COVERED_BY_EXPERIMENT", "covering.V1": 1, "covreasons.V1": [], "bound.targets": 1})
    return sc.finish()


@family("cont.hypothesis_without_validation_requirement", "phase2j_continuity")
def _c2(lang: str) -> dict:
    sc, e = _cont_case(lang, gap="no_requirement")
    sc.flags["no_requirement"] = True
    sc.expect(**{"bound.targets": 0, "x1__link__T1": "DIRECTLY_TESTS", "x1__link__V1": "ABSENT", "x1__nlinks": 1,
                 "posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("cont.metric_match_same_target", "phase2j_continuity")
def _c3(lang: str) -> dict:
    sc, e = _cont_case(lang)
    sc.expect(**{"x1__match__V1": "SAME_AS_PHASE_2J", "cov.V1": "COVERED_BY_EXPERIMENT"})
    return sc.finish()


@family("cont.metric_anchored_to_other_target", "phase2j_continuity")
def _c4(lang: str) -> dict:
    sc, e = _cont_case(lang)
    mm = e.measured(match="DIFFERENT_FROM_PHASE_2J")
    _set_link(e, {"V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": mm}})
    e.link_state["match_ok"] = False
    sc.flags["metric_wrong_target"] = True
    sc.truth = {"match": {"V1": "DIFFERENT_FROM_PHASE_2J"}}
    sc.expect(**{"x1__match__V1": "DIFFERENT_FROM_PHASE_2J", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["METRIC_TARGET_MISMATCH"], "x1__posture": "WELL_SPECIFIED", "posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("cont.baseline_match_same_target", "phase2j_continuity")
def _c5(lang: str) -> dict:
    sc, e = _cont_case(lang, gap="baseline")
    sc.expect(**{"cov.V1": "COVERED_BY_EXPERIMENT", "x1__blmatch__V1": "SAME_AS_PHASE_2J"})
    return sc.finish()


@family("cont.baseline_from_another_target", "phase2j_continuity")
def _c6(lang: str) -> dict:
    sc, e = _cont_case(lang, gap="baseline")
    d = e.default_link()
    d["targets"]["V1"]["baseline"]["match"] = "DIFFERENT_FROM_PHASE_2J"
    e.link = d
    e.link_state["baseline_ok"] = False
    sc.expect(**{"cov.V1": "PARTIALLY_COVERED", "covreasons.V1": ["BASELINE_TARGET_MISMATCH"],
                 "x1__blmatch__V1": "DIFFERENT_FROM_PHASE_2J", "posture": "PARTIALLY_SPECIFIED"})
    return sc.finish()


@family("cont.baseline_required_but_not_linked", "phase2j_continuity")
def _c7(lang: str) -> dict:
    sc, e = _cont_case(lang, gap="baseline")
    d = e.default_link()
    del d["targets"]["V1"]["baseline"]
    e.link = d
    e.link_state["baseline_ok"] = False
    sc.expect(**{"cov.V1": "PARTIALLY_COVERED", "covreasons.V1": ["BASELINE_TARGET_MISMATCH"], "x1__bl__V1": "ABSENT"})
    return sc.finish()


@family("cont.baseline_not_relevant", "phase2j_continuity")
def _c8(lang: str) -> dict:
    sc, e = _cont_case(lang, gap="baseline", extra_docs={"BASELINE": [t("BASE_OTHER", lang)]})
    d = e.default_link()
    d["targets"]["V1"]["baseline"] = {"excerpts": [t("BASE_OTHER", lang)], "relevance": "NOT_RELEVANT_TO_TARGET",
                                      "match": "SAME_AS_PHASE_2J"}
    e.link = d
    e.link_state["baseline_ok"] = False
    e.extra_issues = ["BASELINE_NOT_RELEVANT"]
    sc.truth = {"baseline_relevance": {"V1": "NOT_RELEVANT_TO_TARGET"}}
    sc.expect(**{"x1__bl__V1": "NOT_RELEVANT_TO_TARGET", "x1__issues": ["BASELINE_NOT_RELEVANT"],
                 "x1__posture": "PARTIALLY_SPECIFIED", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["BASELINE_TARGET_MISMATCH"]})
    return sc.finish()


@family("cont.material_condition_covered", "phase2j_continuity")
def _c9(lang: str) -> dict:
    sc, e = _cont_case(lang)
    sc.expect(**{"x1__cond": "ADDRESSED_IN_PROTOCOL", "cov.V1": "COVERED_BY_EXPERIMENT"})
    return sc.finish()


@family("cont.material_condition_omitted", "phase2j_continuity")
def _c10(lang: str) -> dict:
    sc, e = _cont_case(lang)
    _set_link(e, {}, conditions={})
    e.link_state["cond_ok"] = False
    sc.expect(**{"x1__cond": "ABSENT", "cov.V1": "PARTIALLY_COVERED", "covreasons.V1": ["MATERIAL_CONDITION_UNCOVERED"]})
    return sc.finish()


@family("cont.material_condition_only_partially_addressed", "phase2j_continuity", EN_AR)
def _c11(lang: str) -> dict:
    sc, e = _cont_case(lang)
    _set_link(e, {}, conditions={"K1": {"status": "PARTIALLY_ADDRESSED", "excerpts": [e.text("OPERATING_CONDITIONS")]}})
    e.link_state["cond_ok"] = False
    sc.expect(**{"x1__cond": "PARTIALLY_ADDRESSED", "cov.V1": "PARTIALLY_COVERED",
                 "covreasons.V1": ["MATERIAL_CONDITION_UNCOVERED"]})
    return sc.finish()


@family("cont.requirement_covered_by_exactly_one_of_two", "phase2j_continuity")
def _c12(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    e2 = sc.exp("eng")
    sc.result("RES_POS")
    d = e2.default_link()
    d["conditions"] = {}
    e2.link = d
    e2.link_state["cond_ok"] = False
    sc.expect(**{"cov.V1": "COVERED_BY_EXPERIMENT", "covering.V1": 1, "attempting.V1": 2, "x2__cond": "ABSENT"})
    return sc.finish()


@family("cont.requirement_not_covered", "phase2j_continuity")
def _c13(lang: str) -> dict:
    sc, e = _cont_case(lang, v1="DOES_NOT_TEST")
    d = e.default_link()
    d["targets"]["V1"] = {"relation": "DOES_NOT_TEST", "excerpts": []}
    d["conditions"] = {}
    e.link = d
    e.link_state["V1"] = ("DOES_NOT_TEST", False)
    sc.expect(**{"cov.V1": "NOT_COVERED", "covreasons.V1": ["PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"],
                 "attempting.V1": 0, "x1__link__T1": "DIRECTLY_TESTS"})
    return sc.finish()


@family("cont.requirement_unresolved", "phase2j_continuity")
def _c14(lang: str) -> dict:
    sc, e = _cont_case(lang, v1="UNRESOLVED")
    d = e.default_link()
    d["targets"]["V1"] = {"relation": "UNRESOLVED", "excerpts": []}
    d["conditions"] = {}
    e.link = d
    e.link_state["V1"] = ("UNRESOLVED", False)
    sc.expect(**{"cov.V1": "UNRESOLVED", "covreasons.V1": ["LINKAGE_UNRESOLVED"], "posture": "UNRESOLVED"})
    return sc.finish()


@family("cont.mosaic_three_experiments_never_covered", "phase2j_mosaic")
def _mosaic3(lang: str) -> dict:
    """Metric in experiment A, baseline in B, condition in C: no pooling, never COVERED."""
    sc, a = mk(lang, gap="baseline", tagged=True)
    b = sc.exp("eng")
    c = sc.exp("eng")
    sc.result("RES_POS")
    sc.flags["mosaic"] = True

    def spec(e: Exp, *, match: str, baseline: bool, cond: bool) -> dict:
        t1 = {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": e.measured()}
        v1 = {"relation": "DIRECTLY_TESTS", "excerpts": [e.define], "measurement": e.measured(match=match)}
        if baseline:
            v1["baseline"] = {"excerpts": [e.text("BASELINE")], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                              "context": ["PHASE_2J_VALIDATION_BASELINE"], "match": "SAME_AS_PHASE_2J"}
        conds = {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [e.text("OPERATING_CONDITIONS")]}} if cond else {}
        return {"targets": {"T1": t1, "V1": v1}, "conditions": conds}

    a.link = spec(a, match="SAME_AS_PHASE_2J", baseline=False, cond=False)
    b.link = spec(b, match="DIFFERENT_FROM_PHASE_2J", baseline=True, cond=False)
    c.link = spec(c, match="MATCH_UNRESOLVED", baseline=False, cond=True)
    sc.expect(**{"cov.V1": "PARTIALLY_COVERED", "covering.V1": 0, "attempting.V1": 3,
                 "covreasons.V1": ["BASELINE_TARGET_MISMATCH", "MATERIAL_CONDITION_UNCOVERED", "METRIC_TARGET_MISMATCH"],
                 "n_exp": 3, "posture": "PARTIALLY_SPECIFIED", "status": "COMPLETED", "calls": 10})
    return sc.finish(standard=False)


@family("cont.mosaic_metric_and_condition_split", "phase2j_mosaic")
def _mosaic2(lang: str) -> dict:
    sc, a = mk(lang, tagged=True)
    b = sc.exp("eng")
    sc.result("RES_POS")
    sc.flags["mosaic"] = True
    t1a = {"relation": "DIRECTLY_TESTS", "excerpts": [a.define], "measurement": a.measured()}
    a.link = {"targets": {"T1": t1a, "V1": dict(t1a)}, "conditions": {}}
    t1b = {"relation": "DIRECTLY_TESTS", "excerpts": [b.define], "measurement": b.measured(match="MATCH_UNRESOLVED")}
    b.link = {"targets": {"T1": t1b, "V1": dict(t1b)},
              "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [b.text("OPERATING_CONDITIONS")]}}}
    sc.expect(**{"cov.V1": "PARTIALLY_COVERED", "covering.V1": 0, "attempting.V1": 2,
                 "covreasons.V1": ["MATERIAL_CONDITION_UNCOVERED", "METRIC_TARGET_MISMATCH"], "n_exp": 2,
                 "status": "COMPLETED", "calls": 7})
    return sc.finish(standard=False)


@family("cont.covering_experiment_protocol_inadequate", "phase2j_continuity", EN_AR)
def _c15(lang: str) -> dict:
    sc, e = _cont_case(lang, missing=("SETUP", "INPUTS", "ENVIRONMENT"))
    sc.expect(**{"cov.V1": "PARTIALLY_COVERED", "covreasons.V1": ["COVERING_PROTOCOL_INADEQUATE"],
                 "x1__posture": "MAJOR_GAPS"})
    return sc.finish()
