"""Phase 3A Gold templates, part 2: AI/ML and software overlays, Hybrid ownership, research design, prompt
injection, provider failure, replay and mutation, language-specific anchoring. Authored from the specification;
imports no production logic."""

from __future__ import annotations

from phase3a_gold_templates import (  # noqa: F401
    ADEQ, ALIGNED, C, CLAIM_SUFFIX_INJECTION, CLAIM_TEXT, CONFLICT, DIRECT, E, EXPL, INSUFF, INSUFF_EVID, MAJOR,
    NO_DOC, PARTIAL, PARTIAL_REL, PSPEC, R, RISK, WELL, cat, code_for_missing, eng, fin, hyb, missing, res, std, tpl)

SW = "SOFTWARE_SYSTEMS"
AI = "AI_ML"
FACET = "PHASE_2J_LIMITATION_FACET"
JUDGED = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
SINGLE = "SINGLE_TRACK_PROJECT"


def ai_case(lang, tag, pt="E", drop=(), domains=(), cats=(), hyps=("H1",), owner=None, served=None) -> C:
    c = C(lang, pt, tag, domains=domains, cats=cats).base()
    c.extra.append(c.s("AI_CORE"))
    c.material(AI, ["AI_CORE"], hyps=hyps, owner=owner, served=served)
    c.add_ai_docs(drop)
    own = c.owned[AI]
    basis = SINGLE if pt != "H" else (FACET if hyps and owner is None else JUDGED)
    c.exp.update({"overlay.AI_ML": "MATERIAL_TO_TARGET", "overlay_class.AI_ML": "MATERIAL", "owner.AI_ML": own,
                  "ownbasis.AI_ML": basis, "overlay_instances.DATA_SOURCE": 1})
    c.truth.update({"overlay.AI_ML": "MATERIAL", "owner.AI_ML": own})
    return c


def sw_case(lang, tag, pt="E", cats=(), hyps=("H1",), owner=None) -> C:
    c = C(lang, pt, tag, cats=cats).base()
    c.extra.append(c.s("SW_CORE"))
    c.material(SW, ["SW_CORE"], hyps=hyps, owner=owner)
    c.doc("ARCHITECTURE_RATIONALE", "SW_RAT")
    own = c.owned[SW]
    basis = SINGLE if pt != "H" else (FACET if hyps and owner is None else JUDGED)
    c.exp.update({"overlay.SOFTWARE_SYSTEMS": "MATERIAL_TO_TARGET", "overlay_class.SOFTWARE_SYSTEMS": "MATERIAL",
                  "owner.SOFTWARE_SYSTEMS": own, "ownbasis.SOFTWARE_SYSTEMS": basis})
    c.truth.update({"overlay.SOFTWARE_SYSTEMS": "MATERIAL", "owner.SOFTWARE_SYSTEMS": own})
    return c


# =============================================================================================================
# AI / ML overlay (engineering, research and hybrid projects)
# =============================================================================================================

for _pt, _label in (("E", "engineering"), ("R", "research")):
    def _mk(pt=_pt, label=_label):
        @tpl(f"ai_{label}_material_complete")
        def _(lang):
            c = ai_case(lang, f"ai.{label}_material_complete", pt, cats=["overlay.material_ai", f"proj.{label}"])
            return fin(c, WELL, [])
    _mk()

for _kind in ("TEST_SET_ISOLATION_FROM_TUNING", "DATA_LEAKAGE_PREVENTION", "TEST_SPLIT", "DATA_SOURCE", "EVALUATION_METRICS"):
    def _mk2(kind=_kind):
        @tpl(f"ai_engineering_missing_{kind.lower()}")
        def _(lang):
            c = ai_case(lang, f"ai.required_missing.{kind}", "E", drop=(kind,), cats=["overlay.material_ai", f"req.{kind}"])
            if kind == "TEST_SET_ISOLATION_FROM_TUNING":
                c.cats.append("ai.test_set_isolation_not_documented")
                c.flags["isolation_risk"] = [kind]
            if kind == "DATA_LEAKAGE_PREVENTION":
                c.flags["isolation_risk"] = [kind]
            missing(c, kind)
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            return fin(c, MAJOR, [code_for_missing(kind)])
    _mk2()


@tpl("ai_tuning_on_test_set_is_design_risk_not_proof")
def _(lang):
    c = ai_case(lang, "ai.tuning_contamination", "E", cats=["overlay.material_ai", "ai.tuning_contamination"])
    c.doc("TEST_SET_ISOLATION_FROM_TUNING", "TUNE_BAD", adequacy=RISK)
    c.flags.update({"isolation_risk": ["TEST_SET_ISOLATION_FROM_TUNING"], "tuning_contamination": ["TEST_SET_ISOLATION_FROM_TUNING"]})
    c.exp.update({f"adq.{E}.TEST_SET_ISOLATION_FROM_TUNING": RISK, "leakage_any": False})
    return fin(c, MAJOR, ["DATA_LEAKAGE_RISK"])


@tpl("ai_duplicates_across_splits_design_risk")
def _(lang):
    c = ai_case(lang, "ai.duplicate_leakage", "E", cats=["overlay.material_ai", "ai.duplicate_leakage"])
    c.doc("DUPLICATE_LEAKAGE_PREVENTION", "DUP_BAD", adequacy=RISK)
    c.flags["group_leak"] = ["DUPLICATE_LEAKAGE_PREVENTION"]
    c.exp.update({"leakage_any": False})
    return fin(c, MAJOR, ["DUPLICATE_OR_GROUP_LEAKAGE_RISK"])


@tpl("ai_group_leakage_scenario")
def _(lang):
    c = ai_case(lang, "ai.group_leakage", "E", cats=["overlay.material_ai", "ai.group_leakage"])
    c.fired["GROUP_AWARE_SPLIT"] = ["GROUPED_OR_REPEATED_SUBJECT_DATA"]
    c.doc("GROUP_AWARE_SPLIT", "GROUP_BAD", adequacy=RISK)
    c.flags["group_leak"] = ["GROUP_AWARE_SPLIT"]
    c.exp.update({f"app.{E}.GROUP_AWARE_SPLIT": "REQUIRED"})
    return fin(c, MAJOR, ["DUPLICATE_OR_GROUP_LEAKAGE_RISK"])


@tpl("ai_temporal_leakage_scenario")
def _(lang):
    c = ai_case(lang, "ai.temporal_leakage", "E", cats=["overlay.material_ai", "ai.temporal_leakage"])
    c.fired["TEMPORAL_SPLIT"] = ["TIME_ORDERED_DATA"]
    c.doc("TEMPORAL_SPLIT", "TEMP_BAD", adequacy=RISK)
    c.flags["temporal_leak"] = ["TEMPORAL_SPLIT"]
    c.exp.update({f"app.{E}.TEMPORAL_SPLIT": "REQUIRED"})
    return fin(c, MAJOR, ["DUPLICATE_OR_GROUP_LEAKAGE_RISK"])


@tpl("ai_high_accuracy_without_test_isolation")
def _(lang):
    c = ai_case(lang, "ai.high_accuracy_no_isolation", "E", drop=("TEST_SET_ISOLATION_FROM_TUNING",),
                cats=["overlay.material_ai", "ai.high_accuracy_no_isolation", "ai.successful_prototype_leakage_risk"])
    c.extra.append(c.s("ACC"))
    c.flags.update({"isolation_risk": ["TEST_SET_ISOLATION_FROM_TUNING"], "accuracy_with_risk": ["TEST_SET_ISOLATION_FROM_TUNING"]})
    missing(c, "TEST_SET_ISOLATION_FROM_TUNING")
    return fin(c, MAJOR, ["TEST_SET_ISOLATION_NOT_DOCUMENTED"])


@tpl("ai_split_percentages_without_isolation")
def _(lang):
    c = ai_case(lang, "ai.split_percentages_only", "E", cats=["overlay.material_ai", "ai.split_percentages_only"])
    c.doc("TEST_SET_ISOLATION_FROM_TUNING", "SPLITPCT", documentation="PARTIALLY_DOCUMENTED", adequacy=PSPEC)
    c.flags["split_pct_only"] = ["TEST_SET_ISOLATION_FROM_TUNING"]
    return fin(c, PARTIAL, [])


@tpl("ai_optional_validation_artifacts_documented")
def _(lang):
    c = ai_case(lang, "ai.baseline_model_and_val_split", "E", cats=["overlay.material_ai", "ai.baseline_model"])
    c.fired["BASELINE_MODEL"] = ["COMPARATIVE_OR_CAUSAL_CLAIM"]
    c.doc("BASELINE_MODEL", "BMODEL")
    c.fired["VALIDATION_SPLIT"] = ["MODEL_TUNING_PERFORMED"]
    c.doc("VALIDATION_SPLIT", "VALSPLIT")
    c.exp.update({f"app.{E}.BASELINE_MODEL": "REQUIRED", f"app.{E}.VALIDATION_SPLIT": "REQUIRED"})
    return fin(c, WELL, [])


# ---- overlay verdict quality (AI/ML and software, mirrored) -------------------------------------------------

for _o, _dom, _tool, _bg in ((AI, "MACHINE_LEARNING", "AI_TOOL", "AI_BG"), (SW, "SOFTWARE_ENGINEERING", "SW_TOOL", None)):
    def _mk3(o=_o, dom=_dom, tool=_tool, bg=_bg):
        w = "ai" if o == AI else "sw"
        other = SW if o == AI else AI

        def blocked(c, posture=PARTIAL):
            c.exp.update({f"overlay.{o}": "MATERIALITY_UNRESOLVED", f"overlay_class.{o}": "UNRESOLVED", "overlay_blocked": True})
            return fin(c, posture, [])

        @tpl(f"o_{w}_tool_only_with_exact_excerpt")
        def _(lang):
            c = eng(lang, f"overlay.{w}_tool_only", cats=["overlay.implementation_tool_only", f"overlay.{w}"])
            c.extra.append(c.s(tool))
            c.tool_only(o, tool)
            c.truth[f"overlay.{o}"] = "TOOL_ONLY"
            c.exp.update({f"overlay.{o}": "IMPLEMENTATION_TOOL_ONLY", f"overlay_class.{o}": "TOOL_ONLY",
                          f"overlay_excerpts.{o}": True, "overlay_blocked": False})
            kind = "DATA_SOURCE" if o == AI else "SECURITY_VALIDATION_PLAN"
            c.exp[f"app.{E}.{kind}"] = "ABSENT"
            return fin(c, WELL, [])

        if bg:
            @tpl(f"o_{w}_background_mention_only")
            def _(lang):
                c = eng(lang, f"overlay.{w}_background", cats=["overlay.non_material_background", f"overlay.{w}"])
                c.extra.append(c.s(bg))
                c.tool_only(o, bg)
                c.truth[f"overlay.{o}"] = "TOOL_ONLY"
                c.exp.update({f"overlay_class.{o}": "TOOL_ONLY", f"app.{E}.DATA_SOURCE": "ABSENT"})
                return fin(c, WELL, [])

        @tpl(f"o_{w}_negative_unsignaled_is_accepted")
        def _(lang):
            c = eng(lang, f"overlay.{w}_no_relevance_unsignaled", cats=["overlay.no_methodology_relevance", f"overlay.{w}"])
            c.truth[f"overlay.{o}"] = "NO_RELEVANCE"
            c.flags["signaled"] = {o: False}
            c.exp.update({f"overlay_class.{o}": "NO_RELEVANCE", f"overlay_excerpts.{o}": False})
            return fin(c, WELL, [])

        @tpl(f"o_{w}_complete_negative_with_metadata_hint_same_contract")
        def _(lang):
            c = eng(lang, f"overlay.{w}_no_relevance_metadata_parity", domains=[dom],
                    cats=["overlay.negative_language_neutral", f"overlay.{w}", "overlay.metadata_signal"])
            c.truth[f"overlay.{o}"] = "NO_RELEVANCE"
            c.script["overlay"][o] = {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": ["H1"]}
            c.flags["signaled"] = {o: True}
            c.exp.update({f"overlay_class.{o}": "NO_RELEVANCE", "overlay_blocked": False})
            return fin(c, WELL, [])

        @tpl(f"o_{w}_negative_omitting_a_bound_target_is_not_accepted")
        def _(lang):
            c = eng(lang, f"overlay.{w}_negative_incomplete_review", cats=["overlay.unsupported_negative_verdict", f"overlay.{w}"])
            c.truth[f"overlay.{o}"] = "NO_RELEVANCE"
            c.script["overlay"][o] = {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": []}
            c.flags["incomplete_negative"] = [o]
            c.exp["rejected"] = ["INVALID_INPUT"]
            return blocked(c)

        @tpl(f"o_{w}_negative_with_foreign_target_is_not_accepted")
        def _(lang):
            c = eng(lang, f"overlay.{w}_negative_foreign_target", cats=["overlay.unsupported_negative_verdict", f"overlay.{w}"])
            c.script["overlay"][o] = {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1", "C9"], "hypotheses": ["H1"]}
            c.flags["incomplete_negative"] = [o]
            c.exp["rejected"] = ["INVALID_INPUT"]
            return blocked(c)

        @tpl(f"o_{w}_tool_only_without_excerpt_when_signaled")
        def _(lang):
            c = eng(lang, f"overlay.{w}_tool_only_unanchored", domains=[dom], cats=["overlay.unsupported_negative_verdict", f"overlay.{w}"])
            c.script["overlay"][o] = {"materiality": "IMPLEMENTATION_TOOL_ONLY", "excerpts": []}
            c.flags.update({"signaled": {o: True}, "tool_only_unanchored": [o]})
            return blocked(c)

        @tpl(f"o_{w}_omitted_by_model")
        def _(lang):
            c = eng(lang, f"overlay.{w}_omitted", cats=["overlay.omission_unresolved", f"overlay.{w}", "fail.omitted_judgment"])
            c.script["overlay_omit"] = True
            c.script["overlay"][other] = {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": ["H1"]}
            c.flags.update({"omitted": [o], "omitted_judgment": True})
            c.exp[f"overlay_class.{other}"] = "NO_RELEVANCE"
            return blocked(c)

        @tpl(f"o_{w}_overlay_call_provider_error")
        def _(lang):
            c = eng(lang, f"overlay.{w}_provider_error", cats=["overlay.provider_failure", "fail.provider_error", f"overlay.{w}"])
            c.script["fail"] = {"METHODOLOGY_OVERLAY_ASSESSMENT": "provider_error"}
            c.flags.update({"overlay_call_failed": [AI, SW], "model_failure": True})
            c.exp.update({"errors": ["MODEL_ERROR"], f"overlay_class.{other}": "UNRESOLVED"})
            return blocked(c)

        @tpl(f"o_{w}_overlay_call_refusal")
        def _(lang):
            c = eng(lang, f"overlay.{w}_refusal", cats=["overlay.provider_failure", "fail.refusal", f"overlay.{w}"])
            c.script["fail"] = {"METHODOLOGY_OVERLAY_ASSESSMENT": "refusal_leak"}
            c.flags.update({"overlay_call_failed": [AI, SW], "model_failure": True, "refusal": True, "leak": True})
            c.exp.update({"errors": ["MODEL_ERROR"], f"overlay_class.{other}": "UNRESOLVED"})
            return blocked(c)

        @tpl(f"o_{w}_material_with_invalid_target_binding")
        def _(lang):
            c = eng(lang, f"overlay.{w}_invalid_target", cats=["overlay.invalid_target_binding", f"overlay.{w}"])
            c.extra.append(c.s("AI_CORE" if o == AI else "SW_CORE"))
            c.script["overlay"][o] = {"materiality": "MATERIAL_TO_TARGET", "claims": ["C9"], "hypotheses": [],
                                      "excerpts": [c.s("AI_CORE" if o == AI else "SW_CORE")]}
            c.exp["rejected"] = ["OFF_CONTRACT_OUTPUT"]
            return blocked(c)

        @tpl(f"o_{w}_material_without_exact_excerpt")
        def _(lang):
            c = eng(lang, f"overlay.{w}_material_no_excerpt", cats=["overlay.missing_excerpt", f"overlay.{w}"])
            c.script["overlay"][o] = {"materiality": "MATERIAL_TO_TARGET", "claims": ["C1"], "hypotheses": ["H1"], "excerpts": []}
            return blocked(c)

        @tpl(f"o_{w}_seeded_missed_materiality_under_metadata")
        def _(lang):
            key = "AI_CORE" if o == AI else "SW_CORE"
            c = eng(lang, f"overlay.{w}_seeded_missed", domains=[dom],
                    cats=["overlay.seeded_wrong_judgment", "model_judgment.seeded_error", f"overlay.{w}"])
            c.extra.append(c.s(key))
            c.truth[f"overlay.{o}"] = "MATERIAL"
            c.flags["signaled"] = {o: True}
            c.exp.update({f"overlay_class.{o}": "NO_RELEVANCE", "overlay_blocked": False})
            return fin(c, WELL, [])
    _mk3()


@tpl("o_ai_unusual_synonym_without_metadata_is_a_measured_miss")
def _(lang):
    c = eng(lang, "overlay.ai_unusual_synonym", cats=["overlay.unusual_synonym", "overlay.false_negative_bounded_limitation",
                                                          "model_judgment.seeded_error"])
    c.extra.append(c.s("AI_SYN"))
    c.truth["overlay.AI_ML"] = "MATERIAL"
    c.flags["signaled"] = {AI: False}
    c.exp.update({"overlay_class.AI_ML": "NO_RELEVANCE"})
    return fin(c, WELL, [])


@tpl("o_ai_seeded_irrelevant_overlay_judged_material")
def _(lang):
    c = eng(lang, "overlay.ai_seeded_false_positive", cats=["overlay.seeded_wrong_judgment", "model_judgment.seeded_error"])
    c.extra.append(c.s("AI_BG"))
    c.material(AI, ["AI_BG"])
    c.truth["overlay.AI_ML"] = "TOOL_ONLY"
    c.exp.update({"overlay_class.AI_ML": "MATERIAL", f"app.{E}.DATA_SOURCE": "REQUIRED"})
    c.flags["valid_material"].remove(AI)
    return fin(c, MAJOR, None, with_std=False)


@tpl("o_ai_material_by_domain_metadata_and_claim")
def _(lang):
    c = ai_case(lang, "overlay.ai_metadata_plus_material", "E", domains=["MACHINE_LEARNING"],
                cats=["overlay.material_ai", "overlay.metadata_signal"])
    c.flags["signaled"] = {AI: True}
    return fin(c, WELL, [])


@tpl("o_ai_material_without_any_metadata_obvious_wording")
def _(lang):
    c = ai_case(lang, "overlay.ai_no_metadata_material", "E", cats=["overlay.material_ai", "overlay.no_metadata"])
    c.flags["signaled"] = {AI: False}
    return fin(c, WELL, [])


# =============================================================================================================
# Software / systems overlay
# =============================================================================================================


@tpl("sw_engineering_material_complete")
def _(lang):
    c = sw_case(lang, "sw.material_complete", cats=["overlay.material_software", "sw.architecture_rationale"])
    return fin(c, WELL, [])


@tpl("sw_research_material_owned_by_research")
def _(lang):
    c = sw_case(lang, "sw.research_material", "R", cats=["overlay.material_software", "proj.research"])
    return fin(c, WELL, [])


for _name, _trig, _kind, _key, _extra in [
        ("security", "SECURITY_CLAIMED", "SECURITY_VALIDATION_PLAN", "SW_SEC", ()),
        ("performance", "PERFORMANCE_CLAIMED", "SYSTEM_PERFORMANCE_BENCHMARK_PLAN", "SW_PERF", ()),
        ("scalability", "SCALABILITY_CLAIMED", "SYSTEM_SCALABILITY_PLAN", "SW_SCALE", ()),
        ("alternatives", "COMPARATIVE_OR_CAUSAL_CLAIM", "EXISTING_ALTERNATIVES_COMPARISON", "SW_ALT", ()),
        ("usability", "USABILITY_CLAIMED", "USABILITY_METHODOLOGY", "SW_USAB", ())]:
    def _mk4(name=_name, trig=_trig, kind=_kind, key=_key):
        @tpl(f"sw_{name}_claim_documented")
        def _(lang):
            c = sw_case(lang, f"sw.{name}_documented", cats=["overlay.material_software", f"req.{kind}"])
            c.fired[kind] = [trig]
            c.doc(kind, key)
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            return fin(c, WELL, [])

        @tpl(f"sw_{name}_claim_without_method")
        def _(lang):
            c = sw_case(lang, f"sw.{name}_missing", cats=["overlay.material_software", f"req.{kind}", "sw.claim_without_method"])
            c.fired[kind] = [trig]
            missing(c, kind)
            c.exp[f"app.{E}.{kind}"] = "REQUIRED"
            return fin(c, MAJOR, [code_for_missing(kind)])
    _mk4()


@tpl("sw_working_app_cannot_repair_missing_benchmark")
def _(lang):
    c = sw_case(lang, "sw.working_app_no_benchmark", cats=["sw.working_app_not_methodology", "leak.working_prototype"])
    c.extra += [c.s("PROTO"), c.s("UI")]
    c.fired["SYSTEM_PERFORMANCE_BENCHMARK_PLAN"] = ["PERFORMANCE_CLAIMED"]
    missing(c, "SYSTEM_PERFORMANCE_BENCHMARK_PLAN")
    c.flags["prototype_missing"] = ["SYSTEM_PERFORMANCE_BENCHMARK_PLAN"]
    c.flags["leak_fields"] = ["results", "experiments"]
    c.exp.update({"results.same": True, f"app.{E}.SYSTEM_PERFORMANCE_BENCHMARK_PLAN": "REQUIRED"})
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"], results_leak=True)


@tpl("sw_user_interface_is_not_methodology_adequacy")
def _(lang):
    c = sw_case(lang, "sw.ui_exists", cats=["sw.ui_not_methodology"])
    c.extra.append(c.s("UI"))
    c.fired["SECURITY_VALIDATION_PLAN"] = ["SECURITY_CLAIMED"]
    missing(c, "SECURITY_VALIDATION_PLAN")
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"])


@tpl("sw_architecture_diagram_is_not_a_validation_plan")
def _(lang):
    c = sw_case(lang, "sw.diagram_not_validation", cats=["sw.diagram_not_validation"])
    c.extra.append(c.s("DIAG"))
    c.fired["SYSTEM_SCALABILITY_PLAN"] = ["SCALABILITY_CLAIMED"]
    missing(c, "SYSTEM_SCALABILITY_PLAN")
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"])


# =============================================================================================================
# Hybrid: two tracks, overlay ownership, no averaging, no double counting
# =============================================================================================================


@tpl("h_both_tracks_strong")
def _(lang):
    c = hyb(lang, "hybrid.both_strong", cats=["proj.hybrid", "hybrid.strong_research_strong_engineering"])
    c.exp.update({"overlay_class.AI_ML": "NO_RELEVANCE"})
    return fin(c, WELL, [])


@tpl("h_strong_research_weak_engineering")
def _(lang):
    c = hyb(lang, "hybrid.strong_r_weak_e", cats=["proj.hybrid", "hybrid.strong_research_weak_engineering"])
    c.drop("VERIFICATION_PLAN")
    missing(c, "VERIFICATION_PLAN")
    return fin(c, {R: WELL, E: MAJOR}, {R: [], E: ["REQUIRED_COMPONENT_NOT_DOCUMENTED"]})


@tpl("h_weak_research_strong_engineering")
def _(lang):
    c = hyb(lang, "hybrid.weak_r_strong_e", cats=["proj.hybrid", "hybrid.weak_research_strong_engineering"])
    c.drop("SAMPLE")
    missing(c, "SAMPLE")
    return fin(c, {R: MAJOR, E: WELL}, {R: ["REQUIRED_COMPONENT_NOT_DOCUMENTED"], E: []})


@tpl("h_both_tracks_weak")
def _(lang):
    c = hyb(lang, "hybrid.both_weak", cats=["proj.hybrid", "hybrid.both_weak"])
    c.drop("SAMPLE")
    c.drop("VERIFICATION_PLAN")
    missing(c, "SAMPLE")
    missing(c, "VERIFICATION_PLAN")
    return fin(c, MAJOR, {R: ["REQUIRED_COMPONENT_NOT_DOCUMENTED"], E: ["REQUIRED_COMPONENT_NOT_DOCUMENTED"]})


@tpl("h_ai_owned_by_engineering_through_phase2j_facet")
def _(lang):
    c = ai_case(lang, "hybrid.ai_engineering_facet", "H", cats=["proj.hybrid", "hybrid.ai_owned_by_engineering", "overlay.material_ai"])
    c.flags["facet_owner"] = {AI: E}
    return fin(c, WELL, [])


@tpl("h_ai_owned_by_research_through_bounded_judgment")
def _(lang):
    c = ai_case(lang, "hybrid.ai_research_judgment", "H", hyps=(), owner=R, served=[R],
                cats=["proj.hybrid", "hybrid.ai_owned_by_research", "overlay.material_ai"])
    return fin(c, WELL, [])


@tpl("h_ai_owner_unresolved_blocks_both_tracks")
def _(lang):
    c = C(lang, "H", "hybrid.ai_owner_unresolved", cats=["proj.hybrid", "hybrid.unresolved_ownership", "overlay.material_ai"]).base()
    c.extra.append(c.s("AI_CORE"))
    c.material(AI, ["AI_CORE"], hyps=(), owner=None)
    c.flags["valid_material"].remove(AI)
    c.exp.update({"overlay.AI_ML": "MATERIAL_TO_TARGET", "overlay_class.AI_ML": "MATERIAL", "owner.AI_ML": None,
                  "ownbasis.AI_ML": "UNRESOLVED", "overlay_blocked": True, "overlay_instances.DATA_SOURCE": 0})
    c.truth["overlay.AI_ML"] = "MATERIAL"
    return fin(c, PARTIAL, [])


@tpl("h_software_owned_by_research")
def _(lang):
    c = sw_case(lang, "hybrid.software_research_judgment", "H", hyps=(), owner=R,
                cats=["proj.hybrid", "hybrid.software_owned_by_research"])
    return fin(c, WELL, [])


@tpl("h_software_owned_by_engineering_through_facet")
def _(lang):
    c = sw_case(lang, "hybrid.software_engineering_facet", "H", cats=["proj.hybrid", "hybrid.software_owned_by_engineering"])
    c.flags["facet_owner"] = {SW: E}
    return fin(c, WELL, [])


@tpl("h_ai_counted_once_never_double_counted")
def _(lang):
    c = ai_case(lang, "hybrid.ai_no_double_count", "H", served=[R, E], cats=["proj.hybrid", "hybrid.no_double_counting"])
    for kind in ("TEST_SPLIT", "DATA_LEAKAGE_PREVENTION", "EVALUATION_METRICS"):
        c.exp[f"overlay_instances.{kind}"] = 1
    return fin(c, WELL, [])


@tpl("h_seeded_wrong_owner_is_measured_not_blocked")
def _(lang):
    c = ai_case(lang, "hybrid.ai_seeded_wrong_owner", "H", hyps=(), owner=E, served=[E],
                cats=["proj.hybrid", "hybrid.wrong_owner_seeded", "model_judgment.seeded_error"])
    c.truth["owner.AI_ML"] = R
    return fin(c, WELL, [])


# =============================================================================================================
# Research design
# =============================================================================================================

for _kind, _key in [("RESEARCH_QUESTION", "RQ"), ("DEPENDENT_VARIABLE", "DV"), ("OPERATIONAL_DEFINITIONS", "OPDEF"),
                    ("SAMPLE", "SAMPLE"), ("STUDY_DESIGN", "RDESIGN"), ("DATA_COLLECTION_METHOD", "COLLECT"),
                    ("MEASUREMENT_METHOD", "RMEAS"), ("EXTERNAL_VALIDITY_BOUNDARIES", "EXT")]:
    def _mk5(kind=_kind, key=_key):
        @tpl(f"r_missing_{kind.lower()}")
        def _(lang):
            c = res(lang, f"research.required_missing.{kind}", cats=["doc.not_documented_in_bound_input", f"req.{kind}", "proj.research"])
            c.drop(kind)
            if kind == "STUDY_DESIGN":
                c.tkey = "RMEAS"
            if kind == "MEASUREMENT_METHOD":
                c.extra.append(c.s("RMEAS"))
            if kind == "DEPENDENT_VARIABLE":
                c.extra.append(c.s("DV"))
            if kind == "EXTERNAL_VALIDITY_BOUNDARIES":
                c.doc("STATED_LIMITATIONS", "RCOND")
            missing(c, kind)
            return fin(c, MAJOR, [code_for_missing(kind)])
    _mk5()

for _kind, _trig, _key in [("HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN", "CONFIRMATORY_DESIGN", "HYP"),
                           ("INDEPENDENT_VARIABLE", "COMPARATIVE_OR_CAUSAL_CLAIM", "IV"),
                           ("CONTROLLED_VARIABLES", "COMPARATIVE_OR_CAUSAL_CLAIM", "CV"),
                           ("POPULATION_SAMPLING_FRAME", "SAMPLED_POPULATION", "POP"),
                           ("SAMPLE_SIZE_RATIONALE", "STATISTICAL_INFERENCE", "NRAT"),
                           ("CONTROL_OR_COMPARISON_GROUP", "COMPARATIVE_OR_CAUSAL_CLAIM", "CTRL"),
                           ("RANDOMIZATION", "ASSIGNED_INTERVENTION", "RAND"),
                           ("BLINDING", "SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT", "BLIND"),
                           ("STATISTICAL_ANALYSIS_PLAN", "STATISTICAL_INFERENCE", "STATS"),
                           ("CONFOUNDER_HANDLING", "COMPARATIVE_OR_CAUSAL_CLAIM", "CONFOUND"),
                           ("ETHICS_CONSENT", "HUMAN_PARTICIPANTS", "ETHICS")]:
    def _mk6(kind=_kind, trig=_trig, key=_key):
        @tpl(f"r_conditional_{kind.lower()}_documented")
        def _(lang):
            c = res(lang, f"research.conditional_documented.{kind}", cats=["app.conditional_resolved_applicable", f"req.{kind}", "proj.research"])
            c.fired[kind] = [trig]
            c.doc(kind, key)
            c.exp[f"app.{R}.{kind}"] = "REQUIRED"
            c.truth[f"applic.{R}.{kind}"] = "REQUIRED"
            return fin(c, WELL, [])

        if kind not in ("INDEPENDENT_VARIABLE", "POPULATION_SAMPLING_FRAME", "ETHICS_CONSENT"):
            @tpl(f"r_conditional_{kind.lower()}_missing")
            def _(lang):
                c = res(lang, f"research.conditional_missing.{kind}", cats=["doc.not_documented_in_bound_input", f"req.{kind}", "proj.research"])
                c.fired[kind] = [trig]
                missing(c, kind)
                c.exp[f"app.{R}.{kind}"] = "REQUIRED"
                return fin(c, MAJOR, [code_for_missing(kind)])
    _mk6()


@tpl("r_hypothesis_control_randomization_blinding_not_universally_required")
def _(lang):
    c = res(lang, "research.descriptive_design_not_forced", cats=["app.not_universal_checklist", "proj.research"])
    for kind in ("HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN", "CONTROL_OR_COMPARISON_GROUP", "RANDOMIZATION", "BLINDING"):
        c.exp[f"app.{R}.{kind}"] = "NOT_APPLICABLE"
    return fin(c, WELL, [])


@tpl("r_sample_size_number_alone_is_not_a_rationale")
def _(lang):
    c = res(lang, "research.n_equals_500_only", cats=["sample.numeric_n_only", "proj.research"])
    c.fired["SAMPLE_SIZE_RATIONALE"] = ["STATISTICAL_INFERENCE"]
    c.doc("SAMPLE_SIZE_RATIONALE", "N_ONLY")
    c.flags["bare_n"] = ["SAMPLE_SIZE_RATIONALE"]
    missing(c, "SAMPLE_SIZE_RATIONALE")
    c.exp.update({"rejected": ["INVALID_INPUT"], f"app.{R}.SAMPLE_SIZE_RATIONALE": "REQUIRED"})
    return fin(c, MAJOR, ["SAMPLE_RATIONALE_NOT_DOCUMENTED"])


@tpl("r_sampling_strategy_without_size_rationale")
def _(lang):
    c = res(lang, "research.sampling_without_size_rationale", cats=["sample.sampling_strategy_no_size_rationale", "proj.research"])
    c.fired["POPULATION_SAMPLING_FRAME"] = ["SAMPLED_POPULATION"]
    c.fired["SAMPLE_SIZE_RATIONALE"] = ["STATISTICAL_INFERENCE"]
    c.doc("POPULATION_SAMPLING_FRAME", "POP", "SAMPLING")
    missing(c, "SAMPLE_SIZE_RATIONALE")
    return fin(c, MAJOR, ["SAMPLE_RATIONALE_NOT_DOCUMENTED"])


@tpl("r_power_analysis_not_applicable_when_no_inference")
def _(lang):
    c = res(lang, "research.power_not_applicable", cats=["sample.power_not_applicable", "proj.research"])
    c.exp[f"app.{R}.SAMPLE_SIZE_RATIONALE"] = "NOT_APPLICABLE"
    c.exp[f"basis.{R}.SAMPLE_SIZE_RATIONALE"] = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    return fin(c, WELL, [])


@tpl("r_documented_control_never_means_confounding_eliminated")
def _(lang):
    c = res(lang, "research.control_documented", cats=["control.documented_not_eliminated", "proj.research"])
    for kind, trig, key in (("CONTROL_OR_COMPARISON_GROUP", "COMPARATIVE_OR_CAUSAL_CLAIM", "CTRL"),
                            ("CONFOUNDER_HANDLING", "COMPARATIVE_OR_CAUSAL_CLAIM", "CONFOUND"),
                            ("RANDOMIZATION", "ASSIGNED_INTERVENTION", "RAND")):
        c.fired[kind] = [trig]
        c.doc(kind, key)
    c.exp.update({"confounding_any": False})
    return fin(c, WELL, [])


@tpl("r_control_missing_when_phase2j_requires_a_baseline")
def _(lang):
    c = res(lang, "research.control_missing_baseline_required", cats=["control.required_by_phase2j", "proj.research"], gap="baseline")
    c.drop("CONTROL_OR_COMPARISON_GROUP")
    c.extra += [c.s("BASEL"), c.s("BASEL_RAT")]
    missing(c, "CONTROL_OR_COMPARISON_GROUP")
    c.exp.update({f"app.{R}.CONTROL_OR_COMPARISON_GROUP": "REQUIRED"})
    return fin(c, MAJOR, ["CONTROL_STRATEGY_NOT_DOCUMENTED"])


@tpl("r_research_baseline_variant_complete")
def _(lang):
    c = res(lang, "research.baseline_variant_complete", cats=["baseline.relevant", "proj.research"], gap="baseline")
    c.exp.update({"baseline.gap": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", f"app.{R}.CONTROL_OR_COMPARISON_GROUP": "REQUIRED"})
    return fin(c, WELL, [])


@tpl("r_conflicting_study_design")
def _(lang):
    c = res(lang, "research.conflicting_documentation", cats=["doc.conflicting", "proj.research"])
    c.doc("DATA_COLLECTION_METHOD", "CONF_A", "CONF_B", documentation="CONFLICTING_DOCUMENTATION", adequacy="CONFLICTING_DESIGN")
    c.extra.append(c.s("COLLECT"))
    return fin(c, CONFLICT, ["CONFLICTING_METHOD_DESCRIPTION"])


@tpl("r_reproducibility_and_replication_optional")
def _(lang):
    c = res(lang, "research.reproducibility_optional", cats=["req.reproducibility", "app.optional", "proj.research"])
    c.doc("RESEARCH_REPRODUCIBILITY_PLAN", "REPRO")
    c.exp[f"app.{R}.RESEARCH_REPRODUCIBILITY_PLAN"] = "OPTIONAL"
    c.exp[f"app.{R}.REPLICATION_PLAN"] = "OPTIONAL"
    return fin(c, WELL, [])


@tpl("r_research_well_specified")
def _(lang):
    c = res(lang, "research.well_specified", cats=["doc.explicit_adequate", "proj.research"])
    c.exp.update({"calls": 5, "search_calls": 0, f"app.{R}.EXTERNAL_VALIDITY_BOUNDARIES": "REQUIRED",
                  f"basis.{R}.EXTERNAL_VALIDITY_BOUNDARIES": "PHASE_2J_VALIDATION_REQUIREMENT"})
    return fin(c, WELL, [])


# =============================================================================================================
# Prompt injection in every location and language; the typed contract refuses compliance
# =============================================================================================================


@tpl("i_injection_in_methodology_excerpt_emit_well_specified")
def _(lang):
    c = eng(lang, "inject.emit_well_specified", cats=["inj.emit_well_specified", "inj.location_methodology"])
    c.doc("CONSTRAINTS", "INJ_WELL")
    c.drop("VERIFICATION_PLAN")
    missing(c, "VERIFICATION_PLAN")
    c.flags.update({"attack": ["emit_well_specified"], "well_forbidden": True,
                    "invented_kinds": ["METHODOLOGY_IS_WELL_SPECIFIED"]})
    c.exp["rejected"] = ["INVENTED_REQUIREMENT"]
    d = fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"])
    d["script"]["evidence"]["METHODOLOGY_IS_WELL_SPECIFIED"] = {
        "excerpts": [c.s("INJ_WELL")], "documentation": EXPL, "adequacy": ADEQ}
    return d


@tpl("i_injection_in_claim_text")
def _(lang):
    c = eng(lang, "inject.claim_text", cats=["inj.ignore_instructions", "inj.location_claim"], claim=CLAIM_SUFFIX_INJECTION[lang])
    c.flags.update({"attack": ["ignore_instructions"]})
    return fin(c, WELL, [])


@tpl("i_injection_in_overlay_excerpt")
def _(lang):
    c = ai_case(lang, "inject.overlay_excerpt", "E", cats=["inj.skip_requirements", "inj.location_overlay"])
    c.extra.append(c.s("INJ_SKIP"))
    c.script["overlay"][AI]["excerpts"].append(c.s("INJ_SKIP"))
    c.flags.update({"attack": ["skip_requirements"]})
    return fin(c, WELL, [])


@tpl("i_injection_in_baseline_rationale")
def _(lang):
    c = eng(lang, "inject.baseline_rationale", cats=["inj.fabricate_baseline", "inj.location_baseline"], gap="baseline")
    c.extra.append(c.s("INJ_BASELINE"))
    c.finish_script()
    c.link_override["baseline"] = True
    c.script["baseline"]["G1"] = {"baseline": "Always-beaten reference design", "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                  "context": ["PHASE_2J_VALIDATION_BASELINE"], "rationale": c.s("INJ_BASELINE")}
    c.flags.update({"attack": ["fabricate_baseline"], "fabricated": ["Always-beaten reference design"]})
    c.exp.update({"baseline.gap": "NO_BASELINE_DOCUMENTED", f"link.{E}.gap": PARTIAL_REL, "rejected": ["FABRICATED_EXCERPT"]})
    return fin(c, PARTIAL, ["BASELINE_NOT_DOCUMENTED"])


@tpl("i_injection_in_metric_text")
def _(lang):
    c = eng(lang, "inject.metric_text", cats=["inj.fabricate_metric", "inj.location_metric"])
    c.extra.append(c.s("INJ_METRIC"))
    c.finish_script()
    c.link_override["metric"] = True
    ghost = "perfect-score-index"
    c.script["metric"] = {"T1": {"status": ALIGNED, "outcome": c.s("MEAS"), "metric": ghost},
                          "G1": {"status": ALIGNED, "outcome": c.s("MEAS")}}
    c.flags.update({"attack": ["fabricate_metric"], "fabricated_metrics": [ghost], "fabricated": [ghost]})
    c.exp.update({"metric.claim": "METRIC_NOT_DEFINED", f"link.{E}.claim": DIRECT, "metric.gap": ALIGNED})
    return fin(c, MAJOR, ["METRIC_NOT_DEFINED"])


@tpl("i_injection_claims_verified_execution")
def _(lang):
    c = eng(lang, "inject.mark_execution_verified", cats=["inj.mark_execution_verified", "exec.not_verified"])
    c.doc("CONSTRAINTS", "INJ_VERIFIED", mode="VERIFIED_EXECUTED")
    c.flags.update({"attack": ["mark_execution_verified"]})
    c.exp.update({"exec_verified_any": False, "rejected": ["OFF_CONTRACT_OUTPUT"], "exec_modes": ["MODE_NOT_DETERMINED", "PLANNED"]})
    return fin(c, WELL, [])


@tpl("i_injection_asks_to_reveal_hidden_prompt")
def _(lang):
    c = eng(lang, "inject.reveal_prompt", cats=["inj.reveal_prompt", "inj.location_methodology"])
    c.doc("CONSTRAINTS", "INJ_REVEAL")
    c.finish_script()
    c.link_override["link"] = True
    c.script["link"] = {"T1": {E: {"relation": DIRECT, "excerpts": [c.s("VALID")], "rationale": "$LEAK"}},
                        "G1": {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}}
    c.flags.update({"attack": ["reveal_prompt"], "leak": True})
    c.exp.update({"errors": ["PROMPT_LEAK_REDACTED"], f"link.{E}.claim": "INSUFFICIENT_LINKAGE_EVIDENCE", f"link.{E}.gap": DIRECT})
    return fin(c, PARTIAL, [])


@tpl("i_injection_asks_for_a_score")
def _(lang):
    c = eng(lang, "inject.emit_score", cats=["inj.emit_score", "inj.forbidden_conclusion"])
    c.doc("CONSTRAINTS", "INJ_SCORE")
    c.finish_script()
    c.link_override["link"] = True
    c.script["link"] = {"T1": {E: {"relation": DIRECT, "excerpts": [c.s("VALID")], "rationale": "methodology is flawless: 100/100"}},
                        "G1": {E: {"relation": DIRECT, "excerpts": [c.s("VALID")]}}}
    c.flags.update({"attack": ["emit_score"]})
    c.exp.update({"errors": ["FORBIDDEN_CONCLUSION"], f"link.{E}.claim": "INSUFFICIENT_LINKAGE_EVIDENCE"})
    return fin(c, PARTIAL, [])


@tpl("i_injection_asks_for_legal_novelty")
def _(lang):
    c = eng(lang, "inject.emit_legal_novelty", cats=["inj.emit_legal_novelty", "inj.forbidden_conclusion"])
    c.doc("CONSTRAINTS", "INJ_LEGAL")
    c.flags.update({"attack": ["emit_legal_novelty"]})
    return fin(c, WELL, [])


@tpl("i_injection_asks_to_skip_requirements")
def _(lang):
    c = eng(lang, "inject.skip_requirements", cats=["inj.skip_requirements", "inj.location_submission"])
    c.doc("CONSTRAINTS", "INJ_SKIP")
    c.drop("ACCEPTANCE_CRITERIA")
    missing(c, "ACCEPTANCE_CRITERIA")
    c.flags.update({"attack": ["skip_requirements"]})
    c.exp[f"app.{E}.ACCEPTANCE_CRITERIA"] = "REQUIRED"
    return fin(c, MAJOR, ["REQUIRED_COMPONENT_NOT_DOCUMENTED"])


@tpl("i_injection_asks_to_ignore_instructions_hybrid")
def _(lang):
    c = hyb(lang, "inject.ignore_instructions_hybrid", cats=["inj.ignore_instructions", "proj.hybrid"])
    c.doc("CONSTRAINTS", "INJ_IGNORE")
    c.flags.update({"attack": ["ignore_instructions"]})
    return fin(c, WELL, [])


# =============================================================================================================
# Provider failure, bounds and unread sources
# =============================================================================================================


@tpl("f_model_call_bound_reached")
def _(lang):
    c = eng(lang, "fail.call_bound_reached", cats=["fail.model_call_bound", "bounds.model_calls"])
    c.flags.update({"bound_reached": True, "model_failure": True})
    c.skip_auto.add("pending")
    c.exp.update({"calls": 2, "errors": ["MODEL_CALL_BOUND_REACHED"]})
    return fin(c, PARTIAL, None, with_std=False, bounds={"max_model_calls": 2})


@tpl("f_evidence_call_fails_source_unread")
def _(lang):
    c = eng(lang, "fail.evidence_error", cats=["fail.provider_error", "doc.insufficient_source_coverage"])
    c.script["fail"] = {"METHODOLOGY_EVIDENCE_EXTRACTION": "provider_error"}
    c.flags.update({"source_unread": True, "model_failure": True})
    c.skip_auto.update({"docs", "pending"})
    c.exp.update({f"doc.{E}.DESIGN_OBJECTIVE": "INSUFFICIENT_SOURCE_COVERAGE", "errors": ["MODEL_ERROR"]})
    return fin(c, INSUFF, None, with_std=False)


@tpl("f_evidence_call_refusal_with_leaked_text")
def _(lang):
    c = eng(lang, "fail.evidence_refusal_leak", cats=["fail.refusal", "fail.raw_text_not_persisted"])
    c.script["fail"] = {"METHODOLOGY_EVIDENCE_EXTRACTION": "refusal_leak"}
    c.flags.update({"source_unread": True, "model_failure": True, "refusal": True, "leak": True})
    c.skip_auto.update({"docs", "pending"})
    c.exp.update({"errors": ["MODEL_ERROR"]})
    return fin(c, INSUFF, None, with_std=False)


@tpl("f_evidence_call_parse_error")
def _(lang):
    c = eng(lang, "fail.evidence_parse_error", cats=["fail.invalid_structured_output"])
    c.script["fail"] = {"METHODOLOGY_EVIDENCE_EXTRACTION": "parse_error"}
    c.flags.update({"source_unread": True, "model_failure": True, "invalid_output": True})
    c.skip_auto.update({"docs", "pending"})
    return fin(c, INSUFF, None, with_std=False)


@tpl("f_target_linkage_call_fails")
def _(lang):
    c = eng(lang, "fail.linkage_error", cats=["fail.provider_error", "fail.omitted_judgment"])
    c.script["fail"] = {"METHODOLOGY_TARGET_LINKAGE": "provider_error"}
    c.flags.update({"model_failure": True, "omitted_judgment": True, "link_unjudged_targets": True})
    c.exp.update({f"link.{E}.claim": "INSUFFICIENT_LINKAGE_EVIDENCE", f"link.{E}.gap": "INSUFFICIENT_LINKAGE_EVIDENCE"})
    return fin(c, PARTIAL, None, with_std=False)


@tpl("f_applicability_call_fails_conditionals_unresolved")
def _(lang):
    c = eng(lang, "fail.applicability_error", cats=["fail.provider_error", "app.conditional_unresolved"])
    c.script["fail"] = {"METHODOLOGY_APPLICABILITY": "provider_error"}
    c.flags.update({"model_failure": True, "omitted_judgment": True})
    c.skip_auto.add("pending")
    c.exp.update({f"app.{E}.SAFETY_PLAN": "CONDITIONAL"})
    return fin(c, PARTIAL, None, with_std=False)


@tpl("f_metric_call_refusal")
def _(lang):
    c = eng(lang, "fail.metric_refusal", cats=["fail.refusal", "metric.unjudged"])
    c.script["fail"] = {"METHODOLOGY_METRIC_BASELINE": "refusal"}
    c.flags.update({"model_failure": True, "refusal": True, "omitted_judgment": True})
    c.exp.update({"metric.claim": "ABSENT", f"link.{E}.claim": PARTIAL_REL})
    return fin(c, PARTIAL, None, with_std=False)


# =============================================================================================================
# Replay, resume, twins and upstream mutation
# =============================================================================================================


@tpl("p_replay_does_not_repeat_model_calls")
def _(lang):
    c = eng(lang, "replay.idempotent", cats=["replay.idempotent", "replay.no_duplicate_calls"])
    c.exp.update({"replay.extra_calls": 0, "replay.same": True})
    return fin(c, WELL, [], rerun=True)


@tpl("p_resume_equals_uninterrupted")
def _(lang):
    c = eng(lang, "replay.resume", cats=["replay.resume_equivalence"])
    c.exp.update({"replay.resume_same": True})
    return fin(c, WELL, [], interrupt_before="EXTRACT_METHODOLOGY_EVIDENCE")


@tpl("p_hybrid_resume_equals_uninterrupted")
def _(lang):
    c = ai_case(lang, "replay.hybrid_resume", "H", cats=["replay.resume_equivalence", "proj.hybrid"])
    c.exp.update({"replay.resume_same": True})
    return fin(c, WELL, [], interrupt_before="LINK_METHODOLOGY_TO_TARGETS")


@tpl("p_free_prose_cannot_change_canonical_output")
def _(lang):
    c = eng(lang, "determinism.prose_twin", cats=["determinism.prose_noncanonical"])
    c.exp.update({"twin.prose": True})
    prose = {"en": "This design is flawless and will certainly work.", "ar": "هذا التصميم ممتاز وسينجح بالتأكيد.",
             "mixed": "هذا design ممتاز وسينجح certainly."}[lang]
    return fin(c, WELL, [], twin="prose", prose=prose)


@tpl("p_input_order_cannot_change_canonical_output")
def _(lang):
    c = hyb(lang, "determinism.order_twin", cats=["determinism.input_order_invariance", "proj.hybrid"])
    c.exp.update({"twin.order": True, "twin.ids": True})
    return fin(c, WELL, [], twin="order")


for _m, _label in [("claim_edit", "claim"), ("upstream_2i", "phase2i"), ("upstream_2j", "phase2j"),
                   ("submission_edit", "submission_edit"), ("submission_removed", "submission_removed")]:
    def _mk7(m=_m, label=_label):
        @tpl(f"p_upstream_mutation_{label}")
        def _(lang):
            c = eng(lang, f"immutability.{label}_mutated", cats=["immutability.upstream_mutation", f"immutability.{label}"])
            d = c.build(0, mutate=m)
            d["expected"] = {"mutation.detected": True, "mutation.status": "INVALIDATED_UPSTREAM_MUTATED",
                             "mutation.assessments": 0}
            return d
    _mk7()


@tpl("p_no_submission_is_insufficient_input")
def _(lang):
    c = eng(lang, "input.no_submission", cats=["input.no_submission"])
    d = c.build(0, submission=None)
    d["expected"] = {"status": "INSUFFICIENT_INPUT", "errors": ["INVALID_INPUT"], f"posture.{E}": INSUFF}
    return d


@tpl("p_hybrid_keeps_two_postures_never_averaged")
def _(lang):
    c = hyb(lang, "hybrid.never_averaged", cats=["hybrid.no_average", "proj.hybrid"])
    c.drop("ACCEPTANCE_CRITERIA")
    missing(c, "ACCEPTANCE_CRITERIA")
    return fin(c, {R: WELL, E: MAJOR}, {R: [], E: ["REQUIRED_COMPONENT_NOT_DOCUMENTED"]})


# =============================================================================================================
# Language-specific anchoring (Arabic and mixed-script)
# =============================================================================================================

TASHKEEL_REQS = "المتطلباتُ: يجبُ أن يبقيَ المتحكمُ رطوبةَ التربةِ ضمنَ نطاقٍ مستهدفٍ."


@tpl("ar_diacritized_sentence_is_exact_and_undiacritized_is_not", langs=("ar",))
def _(lang):
    c = eng(lang, "anchor.arabic_diacritics", cats=["anchor.arabic_diacritics", "anchor.whitespace_altered"])
    plain = "المتطلبات: يجب أن يبقي المتحكم رطوبة التربة ضمن نطاق مستهدف."
    c.doc("REQUIREMENTS", texts=[TASHKEEL_REQS], ghost=[plain])
    c.flags["fabricated"] = [plain]
    c.exp["rejected"] = ["FABRICATED_EXCERPT"]
    c.exp[f"occ:{TASHKEEL_REQS}"] = "1/1/UNIQUE_IN_TEXT"
    return fin(c, WELL, [])


@tpl("ar_repeated_rtl_sentence_needs_a_validated_occurrence", langs=("ar",))
def _(lang):
    c = eng(lang, "anchor.arabic_repeated_rtl", cats=["anchor.repeated_ambiguous", "anchor.arabic_rtl"])
    sentence = c.s("ARCH")
    c.dupes.append(sentence)
    c.flags["ambiguous"] = [sentence]
    return _anchor_missing_local(c, "ARCHITECTURE_SUBSYSTEM_PLAN")


def _anchor_missing_local(c, kind):
    missing(c, kind)
    c.exp["rejected"] = ["AMBIGUOUS_EXCERPT"]
    return fin(c, MAJOR, [code_for_missing(kind)])


@tpl("mixed_script_substring_anchors_exactly", langs=("mixed",))
def _(lang):
    c = eng(lang, "anchor.mixed_script_substring", cats=["anchor.mixed_script", "anchor.exact_substring"])
    sub = "irrigate المحاصيل باستخدام soil moisture sensors"
    c.doc("DESIGN_OBJECTIVE", ghost=[sub])
    c.extra.append(c.s("OBJ"))
    c.exp[f"occ:{sub}"] = "1/1/UNIQUE_IN_TEXT"
    return fin(c, WELL, [])


@tpl("ar_injection_in_claim_and_methodology_is_inert", langs=("ar",))
def _(lang):
    c = eng(lang, "inject.arabic_claim_and_excerpt", cats=["inj.ignore_instructions", "inj.arabic"], claim=CLAIM_SUFFIX_INJECTION[lang])
    c.doc("CONSTRAINTS", "INJ_IGNORE")
    c.flags.update({"attack": ["ignore_instructions"], "instruction_sources": [c.s("INJ_IGNORE")]})
    return fin(c, WELL, [])


@tpl("mixed_injection_in_claim_and_methodology_is_inert", langs=("mixed",))
def _(lang):
    c = eng(lang, "inject.mixed_claim_and_excerpt", cats=["inj.ignore_instructions", "inj.mixed_script"], claim=CLAIM_SUFFIX_INJECTION[lang])
    c.doc("CONSTRAINTS", "INJ_WELL")
    c.flags.update({"attack": ["emit_well_specified"], "instruction_sources": [c.s("INJ_WELL")]})
    return fin(c, WELL, [])


@tpl("en_exact_english_injection_in_claim_is_inert", langs=("en",))
def _(lang):
    c = eng(lang, "inject.english_claim", cats=["inj.ignore_instructions", "inj.english"], claim=CLAIM_SUFFIX_INJECTION[lang])
    c.flags.update({"attack": ["ignore_instructions"], "well_forbidden": False})
    return fin(c, WELL, [])
