"""Phase 3B Gold families, part 3: provider failures, the model-call bound, canonical determinism, HYBRID ownership,
upstream binding and mutation, legacy ProjectState inputs, no external activity and domain scenarios."""

from __future__ import annotations

from typing import Any

from phase3b_gold_framework import Exp, Sc, family
from phase3b_gold_lang import kind_text as kt
from phase3b_gold_lang import t

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


FAIL_CODE = {"refusal": "MODEL_REFUSED", "parse_error": "MODEL_RESPONSE_INVALID", "provider_error": "MODEL_RESPONSE_INVALID",
             "empty": "MODEL_RESPONSE_INVALID", "incomplete": "PARTIAL_MODEL_OUTPUT"}
ATTEMPTS = {"refusal": 1, "parse_error": 1, "provider_error": 2, "empty": 2, "incomplete": 2}
STAGE_SHORT = {"segment": "SEGMENT", "extract": "EXTRACT", "applicability": "APPLICABILITY", "link": "LINK"}


# =========================================================================================================
# M. provider failure semantics, stage by stage
# =========================================================================================================


def _failure(stage: str, kind: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"STATISTICAL_TEST": ["STATISTICAL_INFERENCE_CLAIMED"]})
        sc.result("RES_POS")
        sc.script = {stage: kind}
        code, n = FAIL_CODE[kind], ATTEMPTS[kind]
        sc.flags["provider_failure"] = f"{STAGE_SHORT[stage]}:{code}"
        sc.flags["model_texts"] = ["I cannot help with that request.", "parsed output failed schema validation",
                                   "APIConnectionError: connection reset", "output truncated"]
        common = {"errors": [code], f"run_issue_stage.{code}": [STAGE_SHORT[stage]], "status": "COMPLETED"}
        if stage == "segment":
            sc.expect(**common, n_exp=0, n_quar=0, calls=n, posture="MAJOR_GAPS", **{"cov.V1": "NOT_COVERED"})
        elif stage == "extract":
            e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]},
                                  "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]}}, "conditions": {}}
            sc.expect(**common, calls=1 + n + 1, x1__type="UNKNOWN", x1__posture="INSUFFICIENT_EVIDENCE",
                      x1__doc__OBJECTIVE="INSUFFICIENT_SOURCE_COVERAGE", x1__adq__OBJECTIVE="INSUFFICIENT_EVIDENCE_TO_ASSESS",
                      posture="INSUFFICIENT_EVIDENCE")
        elif stage == "applicability":
            sc.expect(**common, calls=1 + 1 + n + 1, x1__type="SCIENTIFIC_CONTROLLED_EXPERIMENT",
                      x1__app__BLINDING="CONDITIONAL", x1__posture="UNRESOLVED", posture="UNRESOLVED")
        else:
            sc.expect(**common, calls=1 + 1 + 1 + n, x1__link__T1="UNRESOLVED", x1__link__V1="UNRESOLVED",
                      x1__posture="UNRESOLVED", **{"cov.V1": "UNRESOLVED"}, posture="UNRESOLVED")
        return sc.finish(standard=False)

    return build


_FAILS = [("segment", "refusal"), ("segment", "parse_error"), ("segment", "incomplete"), ("segment", "provider_error"),
          ("extract", "refusal"), ("extract", "parse_error"), ("extract", "incomplete"), ("extract", "empty"),
          ("applicability", "refusal"), ("applicability", "parse_error"), ("applicability", "incomplete"),
          ("link", "refusal"), ("link", "parse_error"), ("link", "provider_error")]
for _i, (_st, _k) in enumerate(_FAILS):
    family(f"provider.{_st}.{_k}", "provider_failure", EN_AR if _i % 2 else EN_MX)(_failure(_st, _k))


@family("provider.missing_provider", "provider_failure")
def _pm(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.flags["provider_failure"] = "SEGMENT:MODEL_PROVIDER_MISSING"
    sc.expect(calls=0, n_exp=0, errors=["MODEL_PROVIDER_MISSING"], **{"run_issue_stage.MODEL_PROVIDER_MISSING": ["SEGMENT"]},
              status="COMPLETED", posture="MAJOR_GAPS", stages_called={})
    return sc.finish(standard=False, no_model=True)


@family("provider.no_failure_yields_well_specified_only_when_every_stage_passes", "provider_failure", EN_AR)
def _pw(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(**{"x1__posture": "WELL_SPECIFIED", "posture": "WELL_SPECIFIED", "errors": []})
    return sc.finish()


@family("provider.refusal_text_never_persisted", "provider_failure")
def _pr(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"link": "refusal"}
    sc.flags["model_texts"] = ["I cannot help with that request."]
    sc.flags["provider_failure"] = "LINK:MODEL_REFUSED"
    sc.expect(errors=["MODEL_REFUSED"], x1__link__T1="UNRESOLVED", calls=4)
    return sc.finish(standard=False)


# =========================================================================================================
# N. the model-call bound
# =========================================================================================================


@family("bound.one_experiment_uses_four_calls", "call_bound")
def _cb1(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(calls=4, stages_called={"segment": 1, "extract": 1, "applicability": 1, "link": 1}, search=0, network=0,
              socket_attempts=0)
    return sc.finish()


@family("bound.max_experiments_exactly_at_bound", "call_bound")
def _cb2(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    sc.exp("eng")
    sc.exp("eng")
    sc.result("RES_POS")
    sc.bounds = {"max_experiments": 3, "max_model_calls": 10}
    sc.expect(calls=10, n_exp=3)
    return sc.finish()


@family("bound.zero_budget_makes_no_call", "call_bound")
def _cb3(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.bounds = {"max_model_calls": 0}
    sc.flags["provider_failure"] = "SEGMENT:MODEL_CALL_BOUND_REACHED"
    sc.expect(calls=0, n_exp=0, errors=["MODEL_CALL_BOUND_REACHED"], stages_called={}, status="COMPLETED",
              posture="MAJOR_GAPS", **{"run_issue_stage.MODEL_CALL_BOUND_REACHED": ["SEGMENT"]})
    return sc.finish(standard=False)


@family("bound.retries_count_as_provider_requests", "call_bound")
def _cb4(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"fail_first": {"segment": 1}}
    sc.expect(calls=5, stages_called={"segment": 2, "extract": 1, "applicability": 1, "link": 1}, errors=[])
    return sc.finish()


@family("bound.exhausted_budget_stops_without_hidden_retry", "call_bound")
def _cb5(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.bounds = {"max_experiments": 1, "max_model_calls": 4}
    sc.script = {"fail_first": {"segment": 1, "extract": 1}}
    sc.flags["provider_failure"] = "APPLICABILITY:MODEL_CALL_BOUND_REACHED"
    sc.expect(calls=4, stages_called={"segment": 2, "extract": 2}, errors=["MODEL_CALL_BOUND_REACHED"],
              **{"run_issue_stage.MODEL_CALL_BOUND_REACHED": ["APPLICABILITY", "LINK"]},
              x1__posture="UNRESOLVED", posture="UNRESOLVED", status="COMPLETED")
    return sc.finish(standard=False)


@family("bound.retry_limit_zero_means_single_attempt", "call_bound", EN_AR)
def _cb6(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.bounds = {"model_retry_limit": 0}
    sc.script = {"link": "provider_error"}
    sc.flags["provider_failure"] = "LINK:MODEL_RESPONSE_INVALID"
    sc.expect(calls=4, errors=["MODEL_RESPONSE_INVALID"], x1__link__T1="UNRESOLVED")
    return sc.finish(standard=False)


@family("bound.refusal_is_not_retried", "call_bound", EN_MX)
def _cb7(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"extract": "refusal"}
    sc.flags["provider_failure"] = "EXTRACT:MODEL_REFUSED"
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]}}, "conditions": {}}
    sc.expect(stages_called={"segment": 1, "extract": 1, "link": 1}, errors=["MODEL_REFUSED"], calls=3)
    return sc.finish(standard=False)


# =========================================================================================================
# O. canonical determinism: order, replay, resume
# =========================================================================================================


@family("determinism.reordered_model_lists_two_experiments", "canonical_determinism")
def _d1(lang: str) -> dict:
    sc, e1 = mk(lang, tagged=True)
    sc.exp("eng")
    sc.result("RES_POS")
    sc.expect(**{"twin.order": True, "twin.ids": True, "n_exp": 2})
    return sc.finish(twin="order")


@family("determinism.reordered_defining_excerpts", "canonical_determinism")
def _d2(lang: str) -> dict:
    sc, e = mk(lang)
    again = sc.say(t("DEF_AGAIN", lang, n=1))
    sc.result("RES_POS")
    sc.segment_override = {"experiments": [{"label": "X1", "excerpts": [e.define, again]}],
                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": sc.results[0]["text"]}]}
    sc.expect(**{"twin.order": True, "twin.ids": True, "x1__ndef": 2})
    return sc.finish(twin="order")


@family("determinism.reordered_targets_and_conditions", "canonical_determinism")
def _d3(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(**{"twin.order": True, "twin.ids": True, "x1__nlinks": 2})
    return sc.finish(twin="order")


@family("determinism.reordered_baseline_comparability", "canonical_determinism")
def _d4(lang: str) -> dict:
    from phase3b_gold_lang import property_text

    props = ["SAME_HARDWARE", "SAME_PREPROCESSING", "SAME_INPUT_SET"]
    texts = [property_text(p, True, lang) for p in props]
    sc, e = mk(lang, gap="baseline", extra_docs={"BASELINE_CONFIGURATION": [t("BASE_CFG", lang), *texts]})
    sc.result("RES_POS")
    d = e.default_link()
    d["targets"]["V1"]["baseline"]["comparability"] = {p: ("DOCUMENTED_SAME", [x]) for p, x in zip(props, texts)}
    e.link = d
    sc.expect(**{"twin.order": True, "twin.ids": True, "x1__blprop__V1__SAME_HARDWARE": "DOCUMENTED_SAME"})
    return sc.finish(twin="order")


@family("determinism.repeated_exact_evidence_collapses", "canonical_determinism")
def _d5(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    obj = e.docs["OBJECTIVE"][0]
    e.docs["OBJECTIVE"] = [obj, obj]
    sc.expect(**{"x1__nex__OBJECTIVE": 1, "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("determinism.replay_makes_no_call_and_changes_nothing", "canonical_determinism")
def _d6(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(**{"replay.same": True, "replay.extra_calls": 0})
    return sc.finish(rerun=True)


def _resume(node: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang)
        sc.result("RES_POS")
        sc.expect(**{"replay.resume_same": True})
        return sc.finish(interrupt_before=node)

    return build


for _i, _n in enumerate(["EXPERIMENT_EXTRACT_PROTOCOL", "EXPERIMENT_RESOLVE_APPLICABILITY", "EXPERIMENT_LINK_TARGETS",
                         "EXPERIMENT_SYNTHESIZE", "EXPERIMENT_FINALIZE"]):
    family(f"determinism.resume_before.{_n}", "checkpoint_determinism", EN_AR if _i % 2 else EN_MX)(_resume(_n))


@family("determinism.resume_with_quarantine_in_flight", "checkpoint_determinism")
def _d7(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.result("RES_TABLE", "RESULT_TABLE")
    sc.expect(**{"replay.resume_same": True, "replay.same": True, "replay.extra_calls": 0, "n_quar": 2})
    return sc.finish(interrupt_before="EXPERIMENT_EXTRACT_PROTOCOL", rerun=True)


# =========================================================================================================
# P. HYBRID ownership: no averaging, no double counting
# =========================================================================================================


def hyb(lang: str, gap: str = "default") -> Sc:
    return Sc(lang, "HYBRID", gap, tagged=True)


def sci_second(sc: Sc, *, owner: str | None = "SCIENTIFIC_RESEARCH", weak: bool = False, etype: str = "SCIENTIFIC_CONTROLLED_EXPERIMENT",
              with_excerpts: bool = True) -> Exp:
    e2 = sc.exp(etype=etype, v1="DOES_NOT_TEST", missing=("OBJECTIVE", "HYPOTHESIS_OR_VALIDATION_OBJECTIVE") if weak else ())
    if owner is not None:
        e2.extract_extra = {"owner": owner, "owner_excerpts": [e2.define] if with_excerpts else []}
    e2.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": e2.measured()},
                           "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}}, "conditions": {}}
    return e2


def eng_first(sc: Sc, etype: str = "ENGINEERING_BENCH_TEST") -> Exp:
    return sc.exp(etype=etype)


@family("hybrid.two_tracks_each_owned_and_well", "hybrid_ownership")
def _h1(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    sci_second(sc)
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "ENGINEERING", "2": "SCIENTIFIC_RESEARCH"}}
    sc.expect(n_exp=2, x1__track="ENGINEERING", x1__ownbasis="PHASE_2J_LIMITATION_FACET", x2__track="SCIENTIFIC_RESEARCH",
              x2__ownbasis="MODEL_ASSISTED_BOUNDED_JUDGMENT", x1__posture="WELL_SPECIFIED", x2__posture="WELL_SPECIFIED",
              **{"track.ENGINEERING": "WELL_SPECIFIED", "track.SCIENTIFIC_RESEARCH": "WELL_SPECIFIED"},
              posture="WELL_SPECIFIED", trackn__ENGINEERING=1, trackn__SCIENTIFIC_RESEARCH=1, status="COMPLETED", calls=7)
    return sc.finish(standard=False)


@family("hybrid.strong_track_never_hides_weak_track", "hybrid_ownership")
def _h2(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    sci_second(sc, weak=True)
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "ENGINEERING", "2": "SCIENTIFIC_RESEARCH"}}
    sc.expect(x1__posture="WELL_SPECIFIED", x2__posture="MAJOR_GAPS", **{"track.ENGINEERING": "WELL_SPECIFIED",
              "track.SCIENTIFIC_RESEARCH": "MAJOR_GAPS"}, posture="MAJOR_GAPS", status="COMPLETED")
    return sc.finish(standard=False)


@family("hybrid.unresolved_ownership_counted_in_no_track", "hybrid_ownership")
def _h3(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    sci_second(sc, owner=None)
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "ENGINEERING", "2": "SCIENTIFIC_RESEARCH"}}
    sc.expect(x2__track=None, x2__ownbasis="UNRESOLVED", trackn__ENGINEERING=1, trackn__SCIENTIFIC_RESEARCH=0,
              **{"track.SCIENTIFIC_RESEARCH": "INSUFFICIENT_EVIDENCE"}, posture="INSUFFICIENT_EVIDENCE", status="COMPLETED")
    return sc.finish(standard=False)


@family("hybrid.model_owner_without_excerpts_is_refused", "hybrid_ownership")
def _h4(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    sci_second(sc, with_excerpts=False)
    sc.result("RES_POS")
    sc.expect(x2__track=None, x2__ownbasis="UNRESOLVED", errors=["PARTIAL_MODEL_OUTPUT"], trackn__SCIENTIFIC_RESEARCH=0,
              status="COMPLETED")
    return sc.finish(standard=False)


@family("hybrid.facet_overrides_model_ownership", "hybrid_ownership")
def _h5(lang: str) -> dict:
    sc = hyb(lang)
    e = sc.exp(etype="ENGINEERING_BENCH_TEST")
    e.extract_extra = {"owner": "SCIENTIFIC_RESEARCH", "owner_excerpts": [e.define]}
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "ENGINEERING"}}
    sc.expect(x1__track="ENGINEERING", x1__ownbasis="PHASE_2J_LIMITATION_FACET", status="COMPLETED",
              **{"track.SCIENTIFIC_RESEARCH": "INSUFFICIENT_EVIDENCE"}, posture="INSUFFICIENT_EVIDENCE")
    return sc.finish(standard=False)


@family("hybrid.model_ownership_when_no_requirement_gives_a_facet", "hybrid_ownership")
def _h6(lang: str) -> dict:
    """No Phase 2J requirement, so no facet can decide: the bounded model proposals (with excerpts) decide."""
    sc = hyb(lang, gap="no_requirement")
    e1 = sc.exp(etype="SCIENTIFIC_CONTROLLED_EXPERIMENT")
    e1.extract_extra = {"owner": "SCIENTIFIC_RESEARCH", "owner_excerpts": [e1.define]}
    e2 = sc.exp(etype="ENGINEERING_BENCH_TEST")
    e2.extract_extra = {"owner": "ENGINEERING", "owner_excerpts": [e2.define]}
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "SCIENTIFIC_RESEARCH", "2": "ENGINEERING"}}
    sc.expect(x1__track="SCIENTIFIC_RESEARCH", x1__ownbasis="MODEL_ASSISTED_BOUNDED_JUDGMENT", x2__track="ENGINEERING",
              x2__ownbasis="MODEL_ASSISTED_BOUNDED_JUDGMENT", **{"track.SCIENTIFIC_RESEARCH": "WELL_SPECIFIED",
              "track.ENGINEERING": "WELL_SPECIFIED"}, posture="WELL_SPECIFIED", status="COMPLETED", **{"bound.targets": 0})
    return sc.finish(standard=False)


@family("hybrid.ai_plus_engineering", "hybrid_ownership")
def _h7(lang: str) -> dict:
    sc = hyb(lang)
    sc.exp(etype="AI_ML_MODEL_EVALUATION")
    e2 = sc.exp(etype="ENGINEERING_BENCH_TEST", v1="DOES_NOT_TEST")
    e2.extract_extra = {"owner": "ENGINEERING", "owner_excerpts": [e2.define]}
    e2.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": e2.measured()},
                           "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}}, "conditions": {}}
    sci = sci_second(sc, etype="SCIENTIFIC_OBSERVATIONAL_STUDY")
    sc.result("RES_POS")
    sc.truth = {"owners": {"1": "ENGINEERING", "2": "ENGINEERING", "3": "SCIENTIFIC_RESEARCH"}}
    sc.expect(x1__track="ENGINEERING", x2__track="ENGINEERING", x3__track="SCIENTIFIC_RESEARCH", trackn__ENGINEERING=2,
              trackn__SCIENTIFIC_RESEARCH=1, posture="WELL_SPECIFIED", status="COMPLETED", calls=10, n_exp=3)
    return sc.finish(standard=False)


@family("hybrid.partially_specified_track_is_not_averaged_with_well_track", "hybrid_ownership", EN_AR)
def _h8(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    e2 = sci_second(sc)
    e2.missing.add("OUTPUTS")
    sc.exps[-1].docs.pop("OUTPUTS")
    sc.result("RES_POS")
    sc.expect(x1__posture="WELL_SPECIFIED", x2__posture="PARTIALLY_SPECIFIED", **{"track.ENGINEERING": "WELL_SPECIFIED",
              "track.SCIENTIFIC_RESEARCH": "PARTIALLY_SPECIFIED"}, posture="PARTIALLY_SPECIFIED", status="COMPLETED")
    return sc.finish(standard=False)


@family("hybrid.two_experiments_one_track_not_double_counted", "hybrid_ownership", EN_MX)
def _h9(lang: str) -> dict:
    sc = hyb(lang)
    eng_first(sc)
    e2 = sc.exp(etype="ENGINEERING_BENCH_TEST", v1="DOES_NOT_TEST")
    e2.extract_extra = {"owner": "ENGINEERING", "owner_excerpts": [e2.define]}
    e2.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e2.define], "measurement": e2.measured()},
                           "V1": {"relation": "DOES_NOT_TEST", "excerpts": []}}, "conditions": {}}
    sc.result("RES_POS")
    sc.expect(trackn__ENGINEERING=2, trackn__SCIENTIFIC_RESEARCH=0, ownedby__ENGINEERING=[
        "MODEL_ASSISTED_BOUNDED_JUDGMENT", "PHASE_2J_LIMITATION_FACET"], status="COMPLETED")
    return sc.finish(standard=False)


# =========================================================================================================
# Q. upstream binding and mutation
# =========================================================================================================


def _mutation(mutate: str):
    def build(lang: str) -> dict:
        sc, e = mk(lang)
        sc.result("RES_POS")
        sc.expect(**{"mutation.status": "INVALIDATED_UPSTREAM_MUTATED", "mutation.kept": 0, "mutation.posture": None,
                     "mutation.codes": ["UPSTREAM_MUTATED"]})
        sc.flags["mutation"] = mutate
        return sc.finish(standard=False, mutate=mutate)

    return build


for _i, _m in enumerate(["claim_edit", "upstream_2j", "upstream_3a", "submission_edit", "submission_removed"]):
    family(f"upstream.{_m}_invalidates_the_run", "upstream_mutation", EN_AR if _i % 2 else EN_MX)(_mutation(_m))


@family("bind.no_submission_ends_insufficient_input", "binding")
def _bn(lang: str) -> dict:
    sc, e = mk(lang)
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, calls=0, n_exp=0, errors=["SOURCE_BINDING_MISSING"])
    case = sc.finish(standard=False)
    case["submission"] = None
    case["flags"]["no_submission"] = True
    return case


@family("bind.unknown_project_type_ends_insufficient_input", "binding")
def _bu(lang: str) -> dict:
    sc, e = mk(lang, ptype="UNKNOWN")
    sc.result("RES_POS")
    sc.expect(status="INSUFFICIENT_INPUT", posture=None, calls=0, n_exp=0, errors=["PROJECT_TYPE_UNBOUND", "SOURCE_BINDING_MISSING"])
    return sc.finish(standard=False)


# =========================================================================================================
# R. legacy ProjectState results / experiments, and external activity
# =========================================================================================================


@family("legacy.results_and_experiments_are_not_inputs", "legacy_inputs")
def _lg1(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.expect(**{"legacy.same": True, "legacy.prompts_same": True, "x1__posture": "WELL_SPECIFIED"})
    return sc.finish(legacy_leak=True)


@family("legacy.state_ignored_even_when_provider_fails", "legacy_inputs", EN_AR)
def _lg2(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"link": "refusal"}
    sc.flags["model_texts"] = ["I cannot help with that request."]
    sc.expect(**{"legacy.same": True, "legacy.prompts_same": True, "errors": ["MODEL_REFUSED"]})
    return sc.finish(standard=False, legacy_leak=True)


@family("safety.no_search_no_network", "external_activity")
def _ns(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION")
    sc.result("RES_POS")
    sc.expect(search=0, network=0, socket_attempts=0)
    return sc.finish()


@family("safety.no_search_no_network_with_provider_failure", "external_activity", EN_AR)
def _ns2(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS")
    sc.script = {"extract": "provider_error"}
    e.link = {"targets": {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]},
                          "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [e.define]}}, "conditions": {}}
    sc.expect(search=0, network=0, socket_attempts=0, errors=["MODEL_RESPONSE_INVALID"])
    return sc.finish(standard=False)


# =========================================================================================================
# S. domain scenarios (engineering, AI/ML, software)
# =========================================================================================================


@family("domain.engineering.prototype_turns_on_once", "engineering_scenario")
def _e1(lang: str) -> dict:
    sc, e = mk(lang, missing=("REPETITIONS", "SAMPLE_SIZE"))
    sc.say(t("EXEC_LAUNCH", lang))
    sc.result("RES_POS")
    sc.flags["exec_prose"] = True
    sc.expect(x1__issues=["REPETITIONS_MISSING_WHEN_REQUIRED", "SAMPLE_MISSING"], x1__posture="MAJOR_GAPS")
    return sc.finish()


@family("domain.engineering.requirement_traceability_missing", "engineering_scenario")
def _e2(lang: str) -> dict:
    sc, e = mk(lang, missing=("REQUIREMENT_TRACEABILITY",))
    sc.result("RES_POS")
    sc.expect(x1__issues=["TARGET_NOT_BOUND"], x1__posture="MAJOR_GAPS")
    return sc.finish()


@family("domain.ai.cross_validation_is_optional", "ai_scenario", EN_AR)
def _a1(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", extra_docs={"CROSS_VALIDATION": [kt("CROSS_VALIDATION", lang)]})
    sc.result("RES_POS")
    sc.expect(**{"x1__app__CROSS_VALIDATION": "OPTIONAL", "x1__doc__CROSS_VALIDATION": "EXPLICITLY_DOCUMENTED",
                 "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("domain.ai.error_analysis_is_optional_and_absent", "ai_scenario", EN_MX)
def _a2(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION")
    sc.result("RES_POS")
    sc.expect(**{"x1__app__ERROR_ANALYSIS": "OPTIONAL", "x1__doc__ERROR_ANALYSIS": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("domain.ai.imbalanced_labels_protocol_risk", "ai_scenario")
def _a3(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", fired={"CLASS_IMBALANCE": ["IMBALANCED_LABELS"]},
               adequacy={"CLASS_IMBALANCE": "PROTOCOL_RISK_IDENTIFIED"})
    sc.result("RES_POS")
    e.extra_issues = ["PROTOCOL_RISK_IDENTIFIED"]
    sc.truth = {"metric_appropriate": False}
    sc.expect(x1__issues=["PROTOCOL_RISK_IDENTIFIED"], x1__posture="PARTIALLY_SPECIFIED")
    return sc.finish()


@family("domain.ai.train_test_leakage_described", "ai_scenario")
def _a4(lang: str) -> dict:
    sc, e = mk(lang, "AI_ML_MODEL_EVALUATION", adequacy={"TRAIN_TEST_SEPARATION": "PROTOCOL_RISK_IDENTIFIED"})
    sc.result("RES_POS")
    e.extra_issues = ["PROTOCOL_RISK_IDENTIFIED"]
    sc.flags["leakage_prevented_claimed"] = False
    sc.expect(x1__issues=["PROTOCOL_RISK_IDENTIFIED"], exec_flags_false=True, x1__posture="PARTIALLY_SPECIFIED")
    return sc.finish()


@family("domain.software.single_run_only", "software_scenario")
def _w1(lang: str) -> dict:
    sc, e = mk(lang, "SOFTWARE_BENCHMARK", missing=("REPETITIONS", "WARM_UP"))
    sc.result("RES_POS")
    sc.expect(x1__issues=["REPETITIONS_MISSING_WHEN_REQUIRED", "REQUIRED_PROTOCOL_ELEMENT_MISSING"], x1__posture="MAJOR_GAPS")
    return sc.finish()


@family("domain.software.workload_mismatch_flagged_as_risk", "software_scenario", EN_AR)
def _w2(lang: str) -> dict:
    sc, e = mk(lang, "SOFTWARE_LOAD_TEST", adequacy={"WORKLOAD": "PROTOCOL_RISK_IDENTIFIED"})
    sc.result("RES_POS")
    e.extra_issues = ["PROTOCOL_RISK_IDENTIFIED"]
    sc.expect(x1__issues=["PROTOCOL_RISK_IDENTIFIED"], x1__posture="PARTIALLY_SPECIFIED")
    return sc.finish()


@family("domain.software.screenshot_is_not_evidence_of_a_protocol", "software_scenario")
def _w3(lang: str) -> dict:
    sc, e = mk(lang, "SOFTWARE_USABILITY_TEST", missing=("INCLUSION_EXCLUSION_RULES", "SAMPLE_DEFINITION"))
    sc.say(t("EXEC_SCREENSHOT", lang))
    sc.result("RES_POS")
    sc.flags["exec_prose"] = True
    sc.expect(x1__posture="MAJOR_GAPS", exec_flags_false=True)
    return sc.finish()
