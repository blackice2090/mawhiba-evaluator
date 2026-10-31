"""Phase 3A negative controls.

A control takes a FINISHED run (as the serialized dict), applies one adversarial mutation, and requires the
mutation to be refused FOR THE INTENDED REASON:

``("validator", "<message>")``  the production run contract must raise a ValidationError containing the message.
                                A rejection for any OTHER reason is a miss: a control that is caught only because
                                an unrelated earlier check fired proves nothing about its own mechanism.
``("gate", "<gate name>")``     the independent Gold gate must report a violation on the mutated context, and must
                                have reported none on the unmutated one.

A mutation with no opportunity in the case (no repeated excerpt, no baseline, ...) is "not applicable", never
counted as caught.
"""

from __future__ import annotations

import copy
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from src.evals.methodology_review import catalog as cat
from src.evals.methodology_review.context import Ctx
from src.evals.methodology_review.gates import GATE_FUNCS
from src.evals.methodology_review.runner import RESULT_TEXT
from src.evals.methodology_review.world import prompt_line

MAX_ATTEMPTS_PER_MECHANISM = 6
CONTROL_FUNCS: dict[str, tuple[Callable[[dict, Ctx], bool], tuple[str, str]]] = {}
ALL_CONTROLS: tuple[str, ...] = ()
_BUDGET: dict[str, int] = {}


def reset_control_budget() -> None:
    _BUDGET.clear()


def control(name: str, kind: str, expect: str):
    def register(fn):
        assert name not in CONTROL_FUNCS, name
        CONTROL_FUNCS[name] = (fn, (kind, expect))
        return fn

    return register


def _tracks(d):
    return d["track_assessments"]


def _docs(d):
    return [(t, x) for t in _tracks(d) for x in t["documentation"]]


def _apps(d):
    return [(t, x) for t in _tracks(d) for x in t["applicability"]]


def _links(d):
    return [(t, x) for t in _tracks(d) for x in t["coverage"]]


def _conds(d):
    return [(t, x) for t in _tracks(d) for x in t["conditions"]]


def _issues(d):
    return [(t, x) for t in _tracks(d) for x in t["issues"]]


def _strong(d):
    return [(t, x) for t, x in _links(d) if x["relation"] == "DIRECTLY_TESTS_TARGET"]


def _first(items, pred=lambda _x: True):
    return next((x for x in items if pred(x)), None)


def _completed(d):
    return d["status"] == "COMPLETED"


def _all_records(d):
    """Every nested track-record list, so a mutation can be applied to both the draft and the assessment copy."""
    return d


def _fake() -> str:
    return str(uuid4())


# -- helpers that mutate in place and return True when applied ------------------------------------------------


def _set(rec, key, value) -> bool:
    rec[key] = value
    return True


def _with(items, pred, fn) -> bool:
    hit = _first(items, pred)
    if hit is None:
        return False
    fn(hit)
    return True


# =========================================================================================================
# Validator controls: provenance and binding
# =========================================================================================================

@control("excerpt_end_offset_tamper", "validator", "offsets must span exactly its text")
def _c1(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "end", d["excerpts"][0]["end"] + 1)


@control("excerpt_start_offset_tamper", "validator", "offsets must span exactly its text")
def _c2(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "start", d["excerpts"][0]["start"] + 1)


@control("occurrence_index_beyond_count", "validator", "occurrence_index exceeds occurrence_count")
def _c3(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "occurrence_index", d["excerpts"][0]["occurrence_count"] + 1)


@control("repeated_excerpt_relabelled_unique", "validator", "never UNIQUE_IN_TEXT")
def _c4(d, x):
    return _with(d["excerpts"], lambda e: e["occurrence_count"] > 1,
                 lambda e: e.update(occurrence_resolution="UNIQUE_IN_TEXT"))


@control("unique_excerpt_count_inflated", "validator", "never UNIQUE_IN_TEXT")
def _c5(d, x):
    return _with(d["excerpts"], lambda e: e["occurrence_count"] == 1, lambda e: e.update(occurrence_count=2))


@control("source_hash_tamper", "validator", "cut from a different submission")
def _c6(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "submission_content_hash", "0" * 64)


@control("source_artifact_tamper", "validator", "cut from a different submission")
def _c7(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "submission_artifact_id", _fake())


@control("cross_run_excerpt", "validator", "cross-run mixing")
def _c8(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "methodology_run_id", _fake())


@control("cross_run_documentation", "validator", "cross-run mixing")
def _c9(d, x):
    return _with(_docs(d), lambda t: True, lambda t: t[1].update(methodology_run_id=_fake()))


@control("cross_run_coverage", "validator", "cross-run mixing")
def _c10(d, x):
    return _with(_links(d), lambda t: True, lambda t: t[1].update(methodology_run_id=_fake()))


@control("cross_run_overlay", "validator", "cross-run mixing")
def _c11(d, x):
    return bool(d["overlays"]) and _set(d["overlays"][0], "methodology_run_id", _fake())


@control("cross_run_baseline", "validator", "cross-run mixing")
def _c12(d, x):
    return bool(d["baselines"]) and _set(d["baselines"][0], "methodology_run_id", _fake())


@control("duplicate_excerpt_id", "validator", "excerpt ids are unique")
def _c13(d, x):
    if not d["excerpts"]:
        return False
    d["excerpts"].append(copy.deepcopy(d["excerpts"][0]))
    return True


@control("documentation_cites_fabricated_excerpt", "validator", "fabricated reference")
def _c14(d, x):
    return _with(_docs(d), lambda t: t[1]["excerpt_ids"], lambda t: t[1].update(excerpt_ids=[_fake()]))


@control("coverage_cites_fabricated_excerpt", "validator", "fabricated reference")
def _c15(d, x):
    return _with(_links(d), lambda t: t[1]["excerpt_ids"], lambda t: t[1].update(excerpt_ids=[_fake()]))


@control("metric_outcome_fabricated_excerpt", "validator", "fabricated reference")
def _c16(d, x):
    return _with(d["metric_alignments"], lambda m: m["outcome_excerpt_id"], lambda m: m.update(outcome_excerpt_id=_fake()))


@control("baseline_cites_fabricated_excerpt", "validator", "fabricated reference")
def _c17(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"], lambda b: b.update(baseline_excerpt_ids=[_fake()]))


@control("condition_cites_fabricated_excerpt", "validator", "fabricated reference")
def _c18(d, x):
    return _with(_conds(d), lambda t: t[1]["excerpt_ids"], lambda t: t[1].update(excerpt_ids=[_fake()]))


@control("overlay_cites_fabricated_excerpt", "validator", "fabricated reference")
def _c19(d, x):
    return _with(d["overlays"], lambda o: o["excerpt_ids"], lambda o: o.update(excerpt_ids=[_fake()]))


@control("applicability_judgment_fabricated_excerpt", "validator", "fabricated reference")
def _c20(d, x):
    return _with(_apps(d), lambda t: t[1]["judgment_excerpt_ids"], lambda t: t[1].update(judgment_excerpt_ids=[_fake()]))


@control("tracks_reclassified", "validator", "never reclassified")
def _c21(d, x):
    d["tracks"] = list(reversed(d["tracks"])) if len(d["tracks"]) > 1 else d["tracks"] + [
        "ENGINEERING" if d["tracks"] == ["SCIENTIFIC_RESEARCH"] else "SCIENTIFIC_RESEARCH"]
    return True


# =========================================================================================================
# Validator controls: applicability
# =========================================================================================================

@control("required_downgraded_not_applicable", "validator", "CATALOG_DEFAULT must equal the catalog default")
def _c22(d, x):
    return _with(_apps(d), lambda t: t[1]["basis"] == "CATALOG_DEFAULT" and t[1]["applicability"] == "REQUIRED",
                 lambda t: t[1].update(applicability="NOT_APPLICABLE"))


@control("required_lowered_by_model_resolution", "validator", "REQUIRED is never lowered")
def _c23(d, x):
    def lower(t):
        t[1].update(basis="MODEL_ASSISTED_BOUNDED_JUDGMENT", applicability="NOT_APPLICABLE", triggers=[],
                    judgment_excerpt_ids=[d["excerpts"][0]["excerpt_id"]] if d["excerpts"] else [_fake()])
    return _with(_apps(d), lambda t: t[1]["basis"] == "CATALOG_DEFAULT" and t[1]["applicability"] == "REQUIRED"
                 and t[1]["kind"] in cat.ALWAYS_REQUIRED and bool(d["excerpts"]), lower)


@control("invented_requirement_in_applicability", "validator", "Input should be")
def _c24(d, x):
    return _with(_apps(d), lambda t: True, lambda t: t[1].update(kind="METHODOLOGY_IS_VALID"))


@control("invented_requirement_in_documentation", "validator", "Input should be")
def _c25(d, x):
    return _with(_docs(d), lambda t: True, lambda t: t[1].update(kind="PERFECT_EXPERIMENT"))


@control("trigger_outside_catalog", "validator", "outside the requirement's catalog triggers")
def _c26(d, x):
    return _with(_apps(d), lambda t: t[1]["basis"] in ("DETERMINISTIC_TRIGGER", "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                                                          "PHASE_2J_VALIDATION_REQUIREMENT") and t[1]["triggers"],
                 lambda t: t[1].update(triggers=["PERSONAL_DATA_PROCESSED", "TIME_ORDERED_DATA",
                                                 "IMBALANCED_LABELS", "SAFETY_RELEVANT"]
                                       if t[1]["kind"] not in cat.AI_KINDS else ["ASSIGNED_INTERVENTION"]))


@control("required_resolution_without_trigger", "validator", "names the trigger(s) that fired")
def _c27(d, x):
    return _with(_apps(d), lambda t: t[1]["basis"] in ("MODEL_ASSISTED_BOUNDED_JUDGMENT", "PHASE_2J_VALIDATION_REQUIREMENT")
                 and t[1]["applicability"] == "REQUIRED", lambda t: t[1].update(triggers=[]))


@control("model_judgment_without_bound_context", "validator", "must bind its source context")
def _c28(d, x):
    return _with(_apps(d), lambda t: t[1]["basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT",
                 lambda t: t[1].update(judgment_excerpt_ids=[]))


@control("core_requirement_moved_to_other_track", "validator", "CORE requirement keeps its catalog track")
def _c29(d, x):
    other = {"SCIENTIFIC_RESEARCH": "ENGINEERING", "ENGINEERING": "SCIENTIFIC_RESEARCH"}
    return _with(_apps(d), lambda t: cat.OVERLAY_OF[t[1]["kind"]] == "CORE" and t[1]["basis"] == "CATALOG_DEFAULT",
                 lambda t: t[1].update(track=other[t[1]["track"]]))


@control("unresolved_condition_made_required", "validator", "unresolved condition stays CONDITIONAL")
def _c30(d, x):
    return _with(_apps(d), lambda t: t[1]["basis"] == "CONDITION_UNRESOLVED", lambda t: t[1].update(applicability="REQUIRED"))


# =========================================================================================================
# Validator controls: metric, baseline, condition, coverage
# =========================================================================================================

@control("invented_student_metric_without_excerpt", "validator", "student metric is a bound student excerpt")
def _c31(d, x):
    return _with(d["metric_alignments"], lambda m: m["metric_source"] == "STUDENT_EXCERPT",
                 lambda m: m.update(metric_excerpt_id=None))


@control("aligned_metric_without_outcome", "validator", "alignment needs a bound measurable outcome")
def _c32(d, x):
    return _with(d["metric_alignments"], lambda m: m["status"] == "ALIGNED_WITHIN_BOUND_INPUT",
                 lambda m: m.update(outcome_excerpt_id=None))


@control("phase2j_metric_with_student_excerpt", "validator", "Phase 2J metric is a bound validation requirement")
def _c33(d, x):
    return _with(d["metric_alignments"], lambda m: m["metric_source"] == "PHASE_2J_VALIDATION_ANCHOR" and d["excerpts"],
                 lambda m: m.update(metric_excerpt_id=d["excerpts"][0]["excerpt_id"]))


@control("metric_reference_without_source", "validator", "metric reference needs its source")
def _c34(d, x):
    return _with(d["metric_alignments"], lambda m: m["metric_excerpt_id"], lambda m: m.update(metric_source=None))


@control("mismatch_without_metric", "validator", "mismatch needs a metric to mismatch")
def _c35(d, x):
    return _with(d["metric_alignments"], lambda m: m["metric_source"] is None,
                 lambda m: m.update(status="METRIC_TARGET_MISMATCH"))


@control("undefined_metric_with_metric", "validator", "METRIC_NOT_DEFINED binds no metric")
def _c36(d, x):
    return _with(d["metric_alignments"], lambda m: m["metric_source"] is not None,
                 lambda m: m.update(status="METRIC_NOT_DEFINED"))


@control("baseline_relevance_from_name_alone", "validator", "never on the baseline's name alone")
def _c37(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"],
                 lambda b: b.update(relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", relevance_context=[],
                                    rationale_excerpt_ids=[]))


@control("baseline_rationale_fabricated", "validator", "cited exactly when its excerpt is bound")
def _c38(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"] and not b["rationale_excerpt_ids"],
                 lambda b: b.update(relevance_context=["STUDENT_RATIONALE_EXCERPT"]))


@control("no_baseline_with_bound_excerpt", "validator", "exactly when no baseline excerpt is bound")
def _c39(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"], lambda b: b.update(relevance="NO_BASELINE_DOCUMENTED"))


@control("phase2j_baseline_context_without_requirement", "validator", "names its validation requirement")
def _c40(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"] and b["gap_validation_requirement_id"] is None,
                 lambda b: b.update(relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                    relevance_context=["PHASE_2J_VALIDATION_BASELINE"]))


@control("fair_comparison_marked_assessed", "validator", "Input should be False")
def _c41(d, x):
    return _with(d["baselines"], lambda b: True, lambda b: b.update(comparison_fairness_assessed=True))


@control("condition_addressed_without_excerpt", "validator", "addressed condition cites its excerpt")
def _c42(d, x):
    return _with(_conds(d), lambda t: t[1]["status"] != "NOT_ADDRESSED_IN_BOUND_INPUT",
                 lambda t: t[1].update(excerpt_ids=[]))


@control("unaddressed_condition_with_excerpt", "validator", "addressed condition cites its excerpt")
def _c43(d, x):
    return _with(_conds(d), lambda t: t[1]["status"] == "NOT_ADDRESSED_IN_BOUND_INPUT" and d["excerpts"],
                 lambda t: t[1].update(excerpt_ids=[d["excerpts"][0]["excerpt_id"]]))


@control("invented_condition_id", "validator", "names a condition its Phase 2J hypothesis does not carry")
def _c44(d, x):
    return not [s for s in _strong(d) if s[1]["gap_hypothesis_id"]] and _with(
        _conds(d), lambda t: True, lambda t: t[1].update(condition_id=_fake()))


@control("gap_coverage_without_hypothesis", "validator", "names its Phase 2J hypothesis")
def _c45(d, x):
    return _with(_links(d), lambda t: t[1]["target_kind"] == "GAP_HYPOTHESIS", lambda t: t[1].update(gap_hypothesis_id=None))


@control("testing_relation_without_excerpt", "validator", "cites the methodology excerpt that tests")
def _c46(d, x):
    return _with(_links(d), lambda t: t[1]["relation"] in ("DIRECTLY_TESTS_TARGET", "PARTIALLY_TESTS_TARGET"),
                 lambda t: t[1].update(excerpt_ids=[]))


@control("strong_coverage_on_non_testing_requirement", "validator", "strong coverage must rest on a design")
def _c47(d, x):
    return _with(_strong(d), lambda t: True, lambda t: t[1].update(requirement_kinds=["RESEARCH_QUESTION"]))


@control("coverage_stale_claim_hash", "validator", "unbound or stale claim")
def _c48(d, x):
    return _with(_links(d), lambda t: True, lambda t: t[1].update(claim_text_hash="1" * 64))


@control("coverage_crosses_to_foreign_gap", "validator", "crosses to another claim's gap")
def _c49(d, x):
    return _with(_links(d), lambda t: t[1]["gap_hypothesis_id"], lambda t: t[1].update(gap_hypothesis_id=_fake()))


@control("strong_gap_without_aligned_metric", "validator", "aligned to the Phase 2J required metric")
def _c50(d, x):
    def unalign(t):
        for m in d["metric_alignments"]:
            if m["gap_validation_requirement_id"]:
                m.update(status="METRIC_NOT_DEFINED", metric_source=None, metric_excerpt_id=None)
    return _with(_strong(d), lambda t: t[1]["gap_hypothesis_id"], unalign)


@control("strong_gap_without_relevant_baseline", "validator", "relevant documented plan for the Phase 2J required baseline")
def _c51(d, x):
    def unrelevant(t):
        for b in d["baselines"]:
            if b["gap_validation_requirement_id"]:
                b.update(relevance="RELEVANCE_UNRESOLVED", relevance_context=[], rationale_excerpt_ids=[])
    return _with(_strong(d), lambda t: t[1]["gap_hypothesis_id"] and any(
        b["gap_validation_requirement_id"] for b in d["baselines"]), unrelevant)


@control("strong_gap_with_uncovered_condition", "validator", "uncovered Phase 2J material condition prevents strong coverage")
def _c52(d, x):
    def uncover(t):
        for _, k in _conds(d):
            k.update(status="NOT_ADDRESSED_IN_BOUND_INPUT", excerpt_ids=[])
    return not any(t["posture"] == cat.POSTURE_WELL for t in _tracks(d)) and _with(
        _strong(d), lambda t: t[1]["gap_hypothesis_id"] and _conds(d), uncover)


@control("strong_claim_without_aligned_metric", "validator", "strong claim coverage needs an aligned metric")
def _c53(d, x):
    def unalign(t):
        for m in d["metric_alignments"]:
            m.update(status="METRIC_NOT_DEFINED", metric_source=None, metric_excerpt_id=None)
    return not [s for s in _strong(d) if s[1]["gap_hypothesis_id"]] and _with(
        _strong(d), lambda t: not t[1]["gap_hypothesis_id"], unalign)


@control("strong_coverage_on_undocumented_requirement", "validator", "rests only on requirements this track documents")
def _c54(d, x):
    def swap(t):
        documented = {dd["kind"] for dd in t[0]["documentation"] if dd["documentation"] in cat.DOC_WITH_EXCERPTS}
        wanted = next(k for k in sorted(cat.TESTS_TARGET) if cat.HOME_TRACK[k] == t[0]["track"] and k not in documented)
        t[1].update(requirement_kinds=[wanted])
    return _with(_strong(d), lambda t: any(cat.HOME_TRACK[k] == t[0]["track"] and k not in {
        dd["kind"] for dd in t[0]["documentation"] if dd["documentation"] in cat.DOC_WITH_EXCERPTS}
        for k in cat.TESTS_TARGET), swap)


# =========================================================================================================
# Validator controls: overlays
# =========================================================================================================

def _material(d):
    return [o for o in d["overlays"] if o["materiality"] == "MATERIAL_TO_TARGET"]


@control("material_overlay_without_excerpt", "validator", "materiality rests on bound targets and excerpts")
def _c55(d, x):
    return _with(_material(d), lambda o: True, lambda o: o.update(excerpt_ids=[]))


@control("material_overlay_without_target", "validator", "materiality rests on bound targets and excerpts")
def _c56(d, x):
    return _with(_material(d), lambda o: True, lambda o: o.update(material_claim_ids=[], material_gap_hypothesis_ids=[]))


@control("tool_only_overlay_given_owner", "validator", "implementation-only overlay is owned by no track")
def _c57(d, x):
    return _with(d["overlays"], lambda o: o["materiality"] == "IMPLEMENTATION_TOOL_ONLY" and d["tracks"],
                 lambda o: o.update(owner_track=d["tracks"][0]))


@control("unresolved_overlay_given_owner", "validator", "unresolved materiality has no owner")
def _c58(d, x):
    return _with(d["overlays"], lambda o: o["materiality"] == "MATERIALITY_UNRESOLVED" and d["tracks"],
                 lambda o: o.update(owner_track=d["tracks"][0]))


@control("material_overlay_without_owner", "validator", "material overlay has an owner unless its ownership is UNRESOLVED")
def _c59(d, x):
    return _with(_material(d), lambda o: o["owner_track"] is not None, lambda o: o.update(owner_track=None))


@control("hybrid_blanket_owner_basis", "validator", "single-track project owns its overlays")
def _c60(d, x):
    return _with(_material(d), lambda o: len(d["tracks"]) > 1 and o["owner_track"],
                 lambda o: o.update(ownership_basis="SINGLE_TRACK_PROJECT"))


@control("single_track_facet_owner_basis", "validator", "single-track project owns its overlays")
def _c61(d, x):
    return _with(_material(d), lambda o: len(d["tracks"]) == 1 and o["owner_track"],
                 lambda o: o.update(ownership_basis="MODEL_ASSISTED_BOUNDED_JUDGMENT"))


@control("overlay_serves_foreign_track", "validator", "serves a track the project type does not have")
def _c62(d, x):
    return _with(d["overlays"], lambda o: len(d["tracks"]) == 1 and o["materiality"] != "IMPLEMENTATION_TOOL_ONLY",
                 lambda o: o.update(
        served_tracks=[*o["served_tracks"], "ENGINEERING" if d["tracks"] == ["SCIENTIFIC_RESEARCH"] else "SCIENTIFIC_RESEARCH"]))


@control("two_assignments_for_one_overlay", "validator", "one assignment per overlay")
def _c63(d, x):
    if not d["overlays"]:
        return False
    d["overlays"].append(copy.deepcopy(d["overlays"][0]))
    return True


@control("overlay_requirement_counted_in_foreign_track", "validator", "counted only in its owner track")
def _c64(d, x):
    def move(t):
        other = _first(_tracks(d), lambda ta: ta["track"] != t[0]["track"])
        copy_ = copy.deepcopy(t[1])
        copy_["track"] = other["track"]
        other["applicability"].append(copy_)
    return _with(_apps(d), lambda t: cat.OVERLAY_OF[t[1]["kind"]] != "CORE" and len(_tracks(d)) > 1
                 and t[1]["applicability"] == "OPTIONAL", move)


@control("overlay_requirement_counted_twice", "validator", "counted once (no double counting)")
def _c65(d, x):
    return _with(_apps(d), lambda t: cat.OVERLAY_OF[t[1]["kind"]] != "CORE",
                 lambda t: t[0]["applicability"].append(copy.deepcopy(t[1])))


@control("blocked_overlay_with_well_specified_track", "validator", "forbids a well-specified track")
def _c66(d, x):
    return _with(d["overlays"], lambda o: any(t["posture"] == cat.POSTURE_WELL for t in _tracks(d)),
                 lambda o: o.update(materiality="MATERIALITY_UNRESOLVED", owner_track=None, ownership_basis="UNRESOLVED",
                                    excerpt_ids=[], material_claim_ids=[], material_gap_hypothesis_ids=[], served_tracks=[]))


# =========================================================================================================
# Validator controls: posture, issues, documentation shape, run shape
# =========================================================================================================

@control("posture_forged_well_specified", "validator", "posture must be derived in code")
def _c67(d, x):
    return _with(_tracks(d), lambda t: t["posture"] != cat.POSTURE_WELL, lambda t: t.update(posture=cat.POSTURE_WELL))


@control("posture_forged_conflicting", "validator", "posture must be derived in code")
def _c68(d, x):
    return _with(_tracks(d), lambda t: t["posture"] != cat.POSTURE_CONFLICT, lambda t: t.update(posture=cat.POSTURE_CONFLICT))


@control("issue_severity_forged", "validator", "severity is fixed by the issue class")
def _c69(d, x):
    return _with(_issues(d), lambda t: t[1]["severity"] != "LOW", lambda t: t[1].update(severity="LOW"))


@control("blocking_issue_removed", "validator", "posture must be derived in code")
def _c70(d, x):
    return _with(_tracks(d), lambda t: any(i["severity"] == "HIGH" for i in t["issues"]) and t["posture"] == cat.POSTURE_MAJOR
                 and not any(dd["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT" for dd in t["documentation"])
                 and all(a["kind"] in {dd["kind"] for dd in t["documentation"]} for a in t["applicability"]
                         if a["applicability"] == "REQUIRED"),
                 lambda t: t.update(issues=[i for i in t["issues"] if i["severity"] != "HIGH"]))


@control("documented_without_excerpt", "validator", "documented requires a bound excerpt")
def _c71(d, x):
    return _with(_docs(d), lambda t: t[1]["documentation"] in cat.DOC_WITH_EXCERPTS, lambda t: t[1].update(excerpt_ids=[]))


@control("not_documented_with_excerpt", "validator", "cites no excerpt")
def _c72(d, x):
    return _with(_docs(d), lambda t: t[1]["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT" and d["excerpts"],
                 lambda t: t[1].update(excerpt_ids=[d["excerpts"][0]["excerpt_id"]]))


@control("adequacy_unreachable_from_documentation", "validator", "is not reachable from")
def _c73(d, x):
    return _with(_docs(d), lambda t: t[1]["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 lambda t: t[1].update(adequacy="ADEQUATELY_SPECIFIED_FOR_REVIEW"))


@control("conflicting_documentation_single_side", "validator", "conflicting documentation cites both sides")
def _c74(d, x):
    return _with(_docs(d), lambda t: t[1]["documentation"] == "EXPLICITLY_DOCUMENTED", lambda t: t[1].update(
        documentation="CONFLICTING_DOCUMENTATION", adequacy="CONFLICTING_DESIGN", excerpt_ids=t[1]["excerpt_ids"][:1]))


@control("excerpt_cited_twice_in_one_requirement", "validator", "an excerpt is cited once")
def _c75(d, x):
    return _with(_docs(d), lambda t: t[1]["excerpt_ids"], lambda t: t[1].update(excerpt_ids=t[1]["excerpt_ids"] * 2))


@control("numeric_n_as_rationale", "validator", "bare number is not a rationale")
def _c76(d, x):
    def bare(t):
        e = d["excerpts"][[ex["excerpt_id"] for ex in d["excerpts"]].index(t[1]["excerpt_ids"][0])]
        e["excerpt"] = "N = 500"
        e["end"] = e["start"] + 7
    return _with(_docs(d), lambda t: t[1]["kind"] in ("SAMPLE_SIZE_RATIONALE", "DESIGN_RATIONALE", "ARCHITECTURE_RATIONALE")
                 and t[1]["excerpt_ids"] and t[1]["documentation"] in cat.DOC_WITH_EXCERPTS, bare)


@control("documentation_for_inapplicable_requirement", "validator", "recorded only for an applicable requirement")
def _c77(d, x):
    def add(t):
        applicable = {a["kind"] for a in t["applicability"] if a["applicability"] != "NOT_APPLICABLE"}
        kind = next(k for k in sorted(cat.KINDS) if cat.HOME_TRACK[k] == t["track"] and k not in applicable)
        t["documentation"].append({"methodology_run_id": d["methodology_run_id"], "kind": kind, "track": t["track"],
                                   "documentation": "NOT_DOCUMENTED_IN_BOUND_INPUT",
                                   "adequacy": "INSUFFICIENT_EVIDENCE_TO_ASSESS", "excerpt_ids": []})
    return _with(_tracks(d), lambda t: any(cat.HOME_TRACK[k] == t["track"] and k not in {
        a["kind"] for a in t["applicability"] if a["applicability"] != "NOT_APPLICABLE"} for k in cat.KINDS), add)


@control("record_in_wrong_track_assessment", "validator", "holds only its own track's records")
def _c78(d, x):
    other = {"SCIENTIFIC_RESEARCH": "ENGINEERING", "ENGINEERING": "SCIENTIFIC_RESEARCH"}
    return _with(_tracks(d), lambda t: t["issues"], lambda t: t["issues"][0].update(track=other[t["track"]]))


@control("claim_bound_twice", "validator", "a claim is bound once")
def _c79(d, x):
    if not d["bound_claims"]:
        return False
    d["bound_claims"].append(copy.deepcopy(d["bound_claims"][0]))
    return True


@control("gap_target_for_unbound_claim", "validator", "gap target names an unbound claim")
def _c80(d, x):
    return _with(d["bound_gap_targets"], lambda t: True, lambda t: t.update(claim_id="C-999"))


@control("baseline_for_unbound_claim", "validator", "baseline targets an unbound claim")
def _c81(d, x):
    return _with(d["baselines"], lambda b: True, lambda b: b.update(target_claim_id="C-999"))


@control("baseline_cites_foreign_requirement", "validator", "requirement of another claim")
def _c82(d, x):
    return _with(d["baselines"], lambda b: b["gap_validation_requirement_id"], lambda b: b.update(gap_validation_requirement_id=_fake()))


@control("metric_cites_foreign_requirement", "validator", "requirement of another claim")
def _c83(d, x):
    return _with(d["metric_alignments"], lambda m: m["gap_validation_requirement_id"],
                 lambda m: m.update(gap_validation_requirement_id=_fake()))


@control("duplicate_upstream_binding", "validator", "one binding per upstream phase")
def _c84(d, x):
    if not d["upstream_bindings"]:
        return False
    d["upstream_bindings"].append(copy.deepcopy(d["upstream_bindings"][0]))
    return True


@control("excerpts_without_submission", "validator", "excerpts require a bound submission")
def _c85(d, x):
    return bool(d["excerpts"]) and _set(d, "submission_artifact_id", None)


@control("completed_run_missing_track", "validator", "exactly one assessment per inherited track")
def _c86(d, x):
    return _completed(d) and bool(_tracks(d)) and (_set(d, "track_assessments", _tracks(d)[:-1]) or True)


@control("completed_before_started", "validator", "completed_at cannot precede started_at")
def _c87(d, x):
    return _set(d, "completed_at", "1999-01-01T00:00:00Z") if d.get("completed_at") else False


@control("execution_verified_excerpt", "validator", "Input should be False")
def _c88(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], "execution_verified", True)


@control("execution_verified_assessment", "validator", "Input should be False")
def _c89(d, x):
    return _with(_tracks(d), lambda t: True, lambda t: t.update(execution_verified=True))


@control("confounding_eliminated_flag", "validator", "Input should be False")
def _c90(d, x):
    return _with(_tracks(d), lambda t: True, lambda t: t.update(confounding_eliminated=True))


@control("leakage_prevented_flag", "validator", "Input should be False")
def _c91(d, x):
    return _with(_tracks(d), lambda t: True, lambda t: t.update(leakage_prevented_in_practice=True))


@control("external_search_increment", "validator", "Input should be 0")
def _c92(d, x):
    return _set(d, "external_search_calls", 1)


@control("not_documented_meaning_altered", "validator", "Input should be")
def _c93(d, x):
    return _set(d, "not_documented_meaning", "NOT_DOCUMENTED_MEANS_NOT_DONE")


@control("forbidden_score_field", "validator", "Extra inputs are not permitted")
def _c94(d, x):
    return _with(_tracks(d), lambda t: True, lambda t: t.update(score=100))


@control("forbidden_legal_field", "validator", "Extra inputs are not permitted")
def _c95(d, x):
    return _set(d, "patentability_conclusion", "PATENTABLE")


@control("forbidden_result_field", "validator", "Extra inputs are not permitted")
def _c96(d, x):
    return _with(d["excerpts"], lambda e: True, lambda e: e.update(result_value="98.7"))


# =========================================================================================================
# Gate controls: semantics the contract cannot see, caught by the independent Gold gate
# =========================================================================================================

@control("excerpt_text_altered_same_length", "gate", "excerpt_not_source_slice")
def _g1(d, x):
    def alter(e):
        e["excerpt"] = ("Z" * len(e["excerpt"]))
    return _with(d["excerpts"], lambda e: True, alter)


@control("first_match_guess_label", "gate", "repeated_excerpt_first_match_guessed")
def _g2(d, x):
    return _with(d["excerpts"], lambda e: e["occurrence_count"] > 1, lambda e: e.update(occurrence_resolution="UNIQUE_IN_TEXT"))


@control("all_hashes_consistently_wrong", "gate", "excerpt_content_hash_mismatch")
def _g3(d, x):
    if not d["excerpts"]:
        return False
    for e in d["excerpts"]:
        e["submission_content_hash"] = "2" * 64
    d["submission_content_hash"] = "2" * 64
    return True


@control("planned_statement_relabelled_executed", "gate", "planned_statement_marked_executed")
def _g4(d, x):
    return _with(d["excerpts"], lambda e: x.scripted_mode(e["excerpt"]) == "PLANNED",
                 lambda e: e.update(statement_mode="DESCRIBED_AS_EXECUTED"))


@control("hidden_prompt_text_persisted", "gate", "hidden_prompt_text_in_output")
def _g5(d, x):
    return _set(d, "errors", [*d["errors"], {"code": "MODEL_ERROR", "node": "N", "message": prompt_line(), "claim_id": None}])


@control("provider_raw_text_persisted", "gate", "provider_raw_text_in_output")
def _g6(d, x):
    return _set(d, "errors", [*d["errors"], {"code": "MODEL_ERROR", "node": "N",
                                             "message": "APIConnectionError: connection reset", "claim_id": None}])


@control("legal_conclusion_emitted", "gate", "legal_novelty_conclusion_emitted")
def _g7(d, x):
    return _set(d, "errors", [*d["errors"], {"code": "MODEL_ERROR", "node": "N", "message": "the design is patentable",
                                             "claim_id": None}])


@control("prompt_following_score_key", "gate", "forbidden_field_name_emitted")
def _g8(d, x):
    return _set(d, "score", 100)


@control("result_text_persisted", "gate", "result_text_reaches_output")
def _g9(d, x):
    return x.case.results_leak and _set(d, "errors", [*d["errors"], {
        "code": "MODEL_ERROR", "node": "N", "message": RESULT_TEXT, "claim_id": None}])


@control("posture_forged_in_place", "gate", "posture_not_derived")
def _g10(d, x):
    return _with(_tracks(d), lambda t: t["posture"] != cat.POSTURE_WELL, lambda t: t.update(posture=cat.POSTURE_WELL))


@control("well_specified_with_major_issue_injected", "gate", "well_specified_with_major_issue")
def _g11(d, x):
    def inject(t):
        t["issues"].append({"issue_id": _fake(), "methodology_run_id": d["methodology_run_id"],
                            "code": "METRIC_NOT_DEFINED", "severity": "HIGH", "track": t["track"],
                            "requirement_kind": None, "claim_id": None, "gap_hypothesis_id": None, "condition_id": None})
    return _with(_tracks(d), lambda t: t["posture"] == cat.POSTURE_WELL, inject)


@control("baseline_relevant_without_context", "gate", "baseline_name_establishes_relevance")
def _g12(d, x):
    return _with(d["baselines"], lambda b: b["baseline_excerpt_ids"], lambda b: b.update(
        relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT", relevance_context=[], rationale_excerpt_ids=[]))


@control("strong_gap_coverage_metric_flipped", "gate", "strong_gap_coverage_without_aligned_metric")
def _g13(d, x):
    def flip(t):
        for m in d["metric_alignments"]:
            if m["gap_validation_requirement_id"]:
                m["status"] = "METRIC_NOT_DEFINED"
    return _with(_strong(d), lambda t: t[1]["gap_hypothesis_id"], flip)


@control("strong_gap_coverage_condition_dropped", "gate", "strong_coverage_with_unaddressed_condition")
def _g14(d, x):
    def drop(t):
        for _, k in _conds(d):
            k["status"] = "NOT_ADDRESSED_IN_BOUND_INPUT"
    return _with(_strong(d), lambda t: t[1]["gap_hypothesis_id"] and _conds(d), drop)


@control("confounding_eliminated_claimed", "gate", "confounding_marked_eliminated")
def _g15(d, x):
    return _with(_tracks(d), lambda t: any(dd["kind"] in ("CONFOUNDER_HANDLING", "CONTROLLED_VARIABLES",
                                                          "CONTROL_OR_COMPARISON_GROUP", "RANDOMIZATION", "BLINDING")
                                           and dd["documentation"] in cat.DOC_WITH_EXCERPTS for dd in t["documentation"]),
                 lambda t: t.update(confounding_eliminated=True))


@control("material_overlay_flipped_non_material", "gate", "material_ai_overlay_silently_excluded")
def _g16(d, x):
    return _with(d["overlays"], lambda o: o["overlay"] == "AI_ML" and o["materiality"] == "MATERIAL_TO_TARGET"
                 and "AI_ML" in x.case.flags.get("valid_material", []),
                 lambda o: o.update(materiality="IMPLEMENTATION_TOOL_ONLY", excerpt_ids=[], owner_track=None,
                                    ownership_basis="NOT_MATERIAL", served_tracks=[], material_claim_ids=[],
                                    material_gap_hypothesis_ids=[]))


@control("material_software_overlay_flipped_non_material", "gate", "material_software_overlay_silently_excluded")
def _g17(d, x):
    return _with(d["overlays"], lambda o: o["overlay"] == "SOFTWARE_SYSTEMS" and o["materiality"] == "MATERIAL_TO_TARGET"
                 and "SOFTWARE_SYSTEMS" in x.case.flags.get("valid_material", []),
                 lambda o: o.update(materiality="IMPLEMENTATION_TOOL_ONLY", excerpt_ids=[], owner_track=None,
                                    ownership_basis="NOT_MATERIAL", served_tracks=[], material_claim_ids=[],
                                    material_gap_hypothesis_ids=[]))


@control("unsupported_negative_accepted", "gate", "unsupported_no_relevance_accepted")
def _g18(d, x):
    return _with(d["overlays"], lambda o: o["materiality"] == "MATERIALITY_UNRESOLVED"
                 and o["overlay"] in x.case.flags.get("incomplete_negative", []),
                 lambda o: o.update(materiality="IMPLEMENTATION_TOOL_ONLY", ownership_basis="NOT_MATERIAL"))


@control("omitted_overlay_closed_non_material", "gate", "overlay_omission_treated_non_material")
def _g19(d, x):
    return _with(d["overlays"], lambda o: o["overlay"] in x.case.flags.get("omitted", []),
                 lambda o: o.update(materiality="IMPLEMENTATION_TOOL_ONLY", ownership_basis="NOT_MATERIAL"))


@control("hybrid_overlay_requirement_double_counted", "gate", "hybrid_overlay_double_counted")
def _g20(d, x):
    def dup(t):
        other = _first(_tracks(d), lambda ta: ta["track"] != t[0]["track"])
        other["applicability"].append({**copy.deepcopy(t[1]), "track": other["track"]})
    return _with(_apps(d), lambda t: cat.OVERLAY_OF[t[1]["kind"]] != "CORE" and len(_tracks(d)) > 1, dup)


@control("not_documented_given_excerpt_in_place", "gate", "not_documented_with_excerpt")
def _g21(d, x):
    return _with(_docs(d), lambda t: t[1]["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT" and d["excerpts"],
                 lambda t: t[1].update(excerpt_ids=[d["excerpts"][0]["excerpt_id"]]))


@control("cross_run_child_in_place", "gate", "cross_run_record_accepted")
def _g22(d, x):
    return _with(_docs(d), lambda t: True, lambda t: t[1].update(methodology_run_id=_fake()))


@control("stage_marker_dropped", "gate", "stage_marker_missing")
def _g23(d, x):
    return _completed(d) and _set(d, "stage_markers", d["stage_markers"][:-1])


@control("track_assessment_dropped_in_place", "gate", "completed_run_track_set_wrong")
def _g24(d, x):
    return _completed(d) and len(_tracks(d)) > 0 and _set(d, "track_assessments", _tracks(d)[:-1])


@control("issue_severity_forged_in_place", "gate", "issue_severity_not_fixed_by_class")
def _g25(d, x):
    return _with(_issues(d), lambda t: t[1]["severity"] != "LOW", lambda t: t[1].update(severity="LOW"))


@control("model_call_bound_exceeded", "gate", "model_calls_exceed_bound")
def _g26(d, x):
    return _set(d, "model_calls_performed", int(x.case.bounds.get("max_model_calls", 80)) + 1)


@control("excerpt_cited_outside_run_in_place", "gate", "documentation_cites_excerpt_outside_run")
def _g27(d, x):
    return _with(_docs(d), lambda t: t[1]["excerpt_ids"], lambda t: t[1].update(excerpt_ids=[_fake()]))


@control("strong_coverage_stale_hash_in_place", "gate", "coverage_stale_claim_hash")
def _g28(d, x):
    return _with(_links(d), lambda t: True, lambda t: t[1].update(claim_text_hash="3" * 64))


@control("project_requirement_invented_in_place", "gate", "invented_requirement_accepted")
def _g29(d, x):
    kinds = x.case.flags.get("invented_kinds", [])
    return bool(kinds) and bool(_tracks(d)) and (_tracks(d)[0]["applicability"].append(
        {**copy.deepcopy(_tracks(d)[0]["applicability"][0]), "kind": kinds[0]}) or True)


# Context-level controls: the mutation lives in the evaluation context, not the run dict.

@control("replay_duplicate_call", "gate", "replay_duplicates_model_calls")
def _x1(d, x):
    return x.case.rerun and (x.replay.update(extra_calls=3) or True)


@control("replay_changes_run", "gate", "replay_changes_the_run")
def _x2(d, x):
    return x.case.rerun and (x.replay.update(same=False) or True)


@control("resume_differs", "gate", "resume_differs_from_uninterrupted")
def _x3(d, x):
    return bool(x.case.interrupt_before) and (x.replay.update(resume_same=False) or True)


@control("prose_changes_canonical", "gate", "free_prose_changes_canonical_output")
def _x4(d, x):
    return x.case.twin == "prose" and (x.twins.update(prose=False) or True)


@control("order_changes_canonical", "gate", "input_order_changes_canonical_output")
def _x5(d, x):
    return x.case.twin == "order" and (x.twins.update(order=False) or True)


@control("nondeterministic_ids", "gate", "nondeterministic_id")
def _x6(d, x):
    return x.case.twin == "order" and (x.twins.update(ids=False) or True)


@control("result_changes_posture", "gate", "result_field_changes_posture")
def _x7(d, x):
    return x.case.results_leak and "results" in x.case.flags.get("leak_fields", ["results", "experiments"]) and (
        x.results_twin.update(same=False) or True)


@control("experiment_changes_posture", "gate", "experiment_field_changes_posture")
def _x8(d, x):
    return x.case.results_leak and "experiments" in x.case.flags.get("leak_fields", ["results", "experiments"]) and (
        x.results_twin.update(same=False) or True)


@control("result_text_in_prompt", "gate", "result_text_reaches_model_prompt")
def _x9(d, x):
    return x.case.results_leak and (setattr(x, "prompts", x.prompts + RESULT_TEXT) or True)


@control("network_attempt_recorded", "gate", "network_attempted_during_run")
def _x10(d, x):
    return setattr(x, "network_attempts", 2) or True


@control("search_calls_incremented_in_place", "gate", "external_search_invoked")
def _x11(d, x):
    return _set(d, "external_search_calls", 1)


@control("upstream_mutation_ignored", "gate", "upstream_mutation_accepted")
def _x12(d, x):
    # the mutated world "was accepted": a mutate case whose run nevertheless COMPLETED with its assessments
    return bool(x.case.mutate) and _set(d, "status", "COMPLETED") and _set(d, "track_assessments", [{"x": 1}]) is True


@control("project_state_mutated", "gate", "project_state_mutated")
def _x13(d, x):
    return not x.case.mutate and (setattr(x, "project_unchanged", False) or True)


ALL_CONTROLS = tuple(CONTROL_FUNCS)


def _mutated_ctx(ctx: Ctx, d: dict) -> Ctx:
    twin = copy.copy(ctx)
    twin.d = d
    twin.replay = dict(ctx.replay)
    twin.twins = dict(ctx.twins)
    twin.results_twin = dict(ctx.results_twin)
    return twin


def run_control(ctx: Ctx, name: str) -> tuple[bool | None, str]:
    """(caught, how). ``caught`` is None when the case offers no opportunity or the mechanism budget is spent."""
    from src.schemas.methodology_review import MethodologyReviewRun

    mutate, (kind, expect) = CONTROL_FUNCS[name]
    if _BUDGET.get(name, 0) >= MAX_ATTEMPTS_PER_MECHANISM:
        return None, "budget"
    mutated = _mutated_ctx(ctx, copy.deepcopy(ctx.d))
    try:
        applied = mutate(mutated.d, mutated)
    except (StopIteration, KeyError, IndexError, TypeError, ValueError):
        applied = False
    if not applied:
        return None, "no opportunity"
    _BUDGET[name] = _BUDGET.get(name, 0) + 1
    if kind == "validator":
        try:
            MethodologyReviewRun.model_validate(mutated.d)
        except ValidationError as exc:
            message = str(exc)
            return (expect in message), (f"rejected for the intended reason: {expect}" if expect in message
                                         else f"rejected for ANOTHER reason: {message[:300]}")
        return False, "ACCEPTED by the production contract"
    before = GATE_FUNCS[expect](ctx)
    after = GATE_FUNCS[expect](mutated)
    if before[0] != 0:
        return False, f"gate {expect} already violated before the mutation"
    return after[0] > 0, f"gate {expect}: {after[0]}/{after[1]}"


__all__ = ["ALL_CONTROLS", "CONTROL_FUNCS", "MAX_ATTEMPTS_PER_MECHANISM", "reset_control_budget", "run_control"]
