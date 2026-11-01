"""Phase 3B negative controls.

A control takes a FINISHED run (the serialized dict, plus the prompts and twin results of its case), applies ONE
adversarial mutation that emulates a failed mechanism, and requires the mutation to be refused FOR THE INTENDED
REASON:

``("validator", "<message>")``  the production run contract must raise a ValidationError containing the message.
                                A rejection for any OTHER reason is a miss: a control that is caught only because
                                an unrelated earlier check fired proves nothing about its own mechanism.
``("gate", "<gate name>")``     the independent Gold gate must report a violation on the mutated context, and must
                                have reported none on the unmutated one.

A mutation with no opportunity in the case (no repeated excerpt, no baseline, ...) is "not applicable", never counted
as caught. At most ``PER_LANGUAGE`` attempts are made per mechanism and language, so a mechanism is exercised across
languages and cases and one mutation repeated many times is still ONE mechanism.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, Callable
from uuid import uuid4

from src.evals.experiment_review import catalog as cat
from src.evals.experiment_review import context as c
from src.evals.experiment_review.adapter import LEGACY_MARKER, prompt_line, validate_run
from src.evals.experiment_review.context import Ctx
from src.evals.experiment_review.gates import GATE_FUNCS

PER_LANGUAGE = 2
CONTROL_FUNCS: dict[str, tuple[Callable[[dict, Ctx], bool], tuple[str, str]]] = {}
_BUDGET: dict[tuple[str, str], int] = {}
GOOD = "ADEQUATELY_SPECIFIED_FOR_REVIEW"


def reset_control_budget() -> None:
    _BUDGET.clear()


def control(name: str, kind: str, expect: str):
    def register(fn):
        assert name not in CONTROL_FUNCS, name
        CONTROL_FUNCS[name] = (fn, (kind, expect))
        return fn

    return register


def _fake() -> str:
    return str(uuid4())


def _first(items, pred=lambda _x: True):
    return next((x for x in items if pred(x)), None)


def _with(items, pred, fn) -> bool:
    hit = _first(items, pred)
    if hit is None:
        return False
    fn(hit)
    return True


def _set(rec: dict, **kw: Any) -> bool:
    rec.update(kw)
    return True


def _reqs(d):
    return [(e, r) for e in d["experiments"] for r in e["requirements"]]


def _exp(d, i=0):
    return d["experiments"][i] if len(d["experiments"]) > i else None


# =========================================================================================================
# provenance and anchoring
# =========================================================================================================

@control("excerpt_end_offset_tamper", "validator", "must span")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], end=d["excerpts"][0]["end"] + 1)


@control("excerpt_start_offset_tamper", "validator", "must span")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], start=d["excerpts"][0]["start"] + 1)


@control("excerpt_text_not_a_source_slice", "gate", "excerpt_not_source_slice")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], excerpt="Z" + d["excerpts"][0]["excerpt"][1:])


@control("fabricated_excerpt_appended", "gate", "excerpt_not_source_slice")
def _c(d, x):
    if not d["excerpts"]:
        return False
    fake = copy.deepcopy(d["excerpts"][0])
    fake.update(excerpt="A sentence that the submission never contains.", excerpt_id=_fake(), end=fake["start"] + 45)
    d["excerpts"].append(fake)
    return True


@control("occurrence_index_beyond_count", "validator", "occurrence")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], occurrence_index=d["excerpts"][0]["occurrence_count"] + 1)


@control("repeated_excerpt_relabelled_unique", "validator", "UNIQUE")
def _c(d, x):
    return _with(d["excerpts"], lambda e: e["occurrence_count"] > 1, lambda e: e.update(occurrence_resolution="UNIQUE_IN_TEXT"))


@control("repeated_excerpt_counted_once", "gate", "repeated_excerpt_first_match_guessed")
def _c(d, x):
    return _with(d["excerpts"], lambda e: len(c.occurrences(x.text[:x.window_end], e["excerpt"])) > 1,
                 lambda e: e.update(occurrence_count=1, occurrence_index=1, occurrence_resolution="UNIQUE_IN_TEXT"))


@control("source_hash_tamper", "validator", "different submission")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], submission_content_hash="0" * 64)


@control("source_artifact_tamper", "validator", "different submission")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], submission_artifact_id=_fake())


@control("excerpt_outside_model_visible_window", "gate", "excerpt_beyond_window_any_case")
def _c(d, x):
    if not d["excerpts"]:
        return False
    x.window_override = d["excerpts"][-1]["end"] - 1
    return True


@control("excerpt_straddles_window_edge", "gate", "excerpt_straddles_window_edge")
def _c(d, x):
    if not d["excerpts"] or not x.flags.get("window"):
        return False
    e = d["excerpts"][0]
    x.window_override = e["start"] + (e["end"] - e["start"]) // 2 + 1
    x.case.flags["window"] = x.window_override
    return True


@control("excerpt_overlaps_quarantined_result", "validator", "overlap")
def _c(d, x):
    if not d["excerpts"] or not d["quarantine"]:
        return False
    q = d["quarantine"][0]
    d["excerpts"][0].update(start=q["start"], end=q["end"], excerpt=x.text[q["start"]:q["end"]])
    return True


@control("escape_character_leaks_into_canonical_excerpt", "gate", "escaped_text_leaked_into_canonical_excerpt")
def _c(d, x):
    return bool(x.flags.get("markers")) and bool(d["excerpts"]) and _set(d["excerpts"][0], excerpt=d["excerpts"][0]["excerpt"][:3] + c.ZWSP + d["excerpts"][0]["excerpt"][3:])


@control("excerpt_count_bound_exceeded", "gate", "excerpt_count_over_bound")
def _c(d, x):
    if len(d["excerpts"]) < 2:
        return False
    d["bounds"]["max_excerpts"] = len(d["excerpts"]) - 1
    x.case = x.case.model_copy(update={"bounds": {**x.case.bounds, "max_excerpts": len(d["excerpts"]) - 1}})
    return True


# =========================================================================================================
# run binding (cross-run mixing)
# =========================================================================================================

@control("cross_run_excerpt", "validator", "cross-run")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], experiment_run_id=_fake())


@control("cross_run_experiment", "validator", "derived from the run")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], experiment_run_id=_fake())


@control("cross_run_requirement", "validator", "different experiment")
def _c(d, x):
    return bool(_reqs(d)) and _set(_reqs(d)[0][1], experiment_run_id=_fake())


@control("cross_run_link", "validator", "cross-run")
def _c(d, x):
    return bool(d["links"]) and _set(d["links"][0], experiment_run_id=_fake())


@control("cross_run_measurement", "validator", "cross-run")
def _c(d, x):
    return bool(d["measurements"]) and _set(d["measurements"][0], experiment_run_id=_fake())


@control("cross_run_baseline", "validator", "cross-run")
def _c(d, x):
    return bool(d["baselines"]) and _set(d["baselines"][0], experiment_run_id=_fake())


@control("cross_run_condition", "validator", "cross-run")
def _c(d, x):
    return bool(d["conditions"]) and _set(d["conditions"][0], experiment_run_id=_fake())


@control("cross_run_coverage", "validator", "cross-run")
def _c(d, x):
    return bool(d["phase2j_coverage"]) and _set(d["phase2j_coverage"][0], experiment_run_id=_fake())


@control("cross_run_track_posture", "validator", "cross-run")
def _c(d, x):
    return bool(d["track_postures"]) and _set(d["track_postures"][0], experiment_run_id=_fake())


@control("cross_run_quarantine_span", "validator", "cross-run")
def _c(d, x):
    return bool(d["quarantine"]) and _set(d["quarantine"][0], experiment_run_id=_fake())


# =========================================================================================================
# the result quarantine
# =========================================================================================================

@control("quarantine_first_occurrence_only", "gate", "first_match_only_quarantine")
def _c(d, x):
    rs = [r for r in x.flags.get("declared_results", []) if r.strip() and len(c.occurrences(x.text[:x.window_end], r)) > 1]
    if not rs or len(d["quarantine"]) < 2:
        return False
    d["quarantine"] = d["quarantine"][:1]
    return True


@control("quarantine_dropped_entirely", "gate", "declared_result_occurrence_not_quarantined")
def _c(d, x):
    if not d["quarantine"]:
        return False
    d["quarantine"] = []
    return True


@control("quarantine_span_shifted", "gate", "quarantine_span_hash_mismatch")
def _c(d, x):
    return bool(d["quarantine"]) and d["quarantine"][0]["end"] + 1 <= len(x.text) and _set(
        d["quarantine"][0], start=d["quarantine"][0]["start"] + 1, end=d["quarantine"][0]["end"] + 1)


@control("quarantine_hash_tamper", "gate", "quarantine_span_hash_mismatch")
def _c(d, x):
    return bool(d["quarantine"]) and _set(d["quarantine"][0], span_hash="f" * 64)


@control("quarantined_value_consumed", "validator", "consumed_by_phase3b|Input should be False")
def _c(d, x):
    return bool(d["quarantine"]) and _set(d["quarantine"][0], consumed_by_phase3b=True)


@control("result_text_persisted_in_state", "gate", "result_text_persisted_canonically")
def _c(d, x):
    rs = [r for r in x.flags.get("results", []) if len(r) >= 8]
    if not rs:
        return False
    d["errors"] = [*d["errors"], {"code": "PARTIAL_MODEL_OUTPUT", "node": "EXPERIMENT_SEGMENT", "message": rs[0],
                                  "experiment_id": None}]
    return True


@control("incomplete_quarantine_reads_complete", "gate", "incomplete_quarantine_accepted_as_complete")
def _c(d, x):
    if not x.flags.get("incomplete_quarantine"):
        return False
    d["status"] = "COMPLETED"
    return True


@control("incomplete_quarantine_keeps_strong_posture", "gate", "incomplete_quarantine_strong_posture")
def _c(d, x):
    if not x.flags.get("incomplete_quarantine"):
        return False
    d["project_posture"] = "WELL_SPECIFIED"
    return True


@control("incomplete_quarantine_later_model_call", "gate", "incomplete_quarantine_later_model_call")
def _c(d, x):
    if not x.flags.get("incomplete_quarantine"):
        return False
    x.calls_by_task = {**x.calls_by_task, "extract": 1}
    return True


@control("unlocatable_result_silently_dropped", "gate", "undeclared_quarantine_failure_dropped_silently")
def _c(d, x):
    if not any(x.flags.get(k) for k in ("unlocatable_result", "empty_declared_result", "excessive_result")):
        return False
    d["errors"] = [e for e in d["errors"] if e["code"] != "PARTIAL_MODEL_OUTPUT"]
    return True


@control("result_value_reaches_a_later_prompt", "gate", "declared_result_in_later_prompt")
def _c(d, x):
    rs = [r for r in x.flags.get("declared_results", []) if r.strip()]
    later = [i for i, (t, _) in enumerate(x.prompts) if t != c.TASK_NAMES["segment"]]
    if not rs or not later:
        return False
    i = later[0]
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + "\n" + rs[0])
    return True


@control("result_withhold_placeholder_removed", "gate", "result_withhold_placeholder_missing")
def _c(d, x):
    ex = [i for i, (t, p) in enumerate(x.prompts) if t == c.TASK_NAMES["extract"] and c.PLACEHOLDER in p]
    if not ex or x.flags.get("window"):
        return False
    x.prompts[ex[0]] = (x.prompts[ex[0]][0], x.prompts[ex[0]][1].replace(c.PLACEHOLDER, ""))
    return True


@control("result_value_changes_adequacy", "gate", "result_value_changes_adequacy")
def _c(d, x):
    if x.case.twin != "result":
        return False
    x.twins["result"] = False
    return True


@control("protocol_excerpt_swallows_result", "gate", "protocol_excerpt_accepted_over_result_overlap")
def _c(d, x):
    rs = [r for r in x.flags.get("declared_results", []) if r.strip()]
    if not rs or not d["excerpts"]:
        return False
    d["excerpts"][0]["excerpt"] = d["excerpts"][0]["excerpt"] + " " + rs[0]
    return True


# =========================================================================================================
# the execution boundary, search and network
# =========================================================================================================

@control("run_execution_verified_from_prose", "validator", "execution_verified|Input should be False")
def _c(d, x):
    return _set(d, execution_verified=True)


@control("run_results_evaluated", "validator", "results_evaluated|Input should be False")
def _c(d, x):
    return _set(d, results_evaluated=True)


@control("experiment_execution_verified", "validator", "experiments.0.execution_verified|Input should be False")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], execution_verified=True)


@control("independent_reproduction_inferred", "validator", "independently_reproduced|Input should be False")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], independently_reproduced=True)


@control("leakage_prevented_in_practice_inferred", "validator", "leakage_prevented_in_practice|Input should be False")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], leakage_prevented_in_practice=True)


@control("excerpt_execution_verified", "validator", "excerpts.0.execution_verified|Input should be False")
def _c(d, x):
    return bool(d["excerpts"]) and _set(d["excerpts"][0], execution_verified=True)


@control("baseline_execution_verified", "validator", "baselines.0.execution_verified|Input should be False")
def _c(d, x):
    return bool(d["baselines"]) and _set(d["baselines"][0], execution_verified=True)


@control("baseline_comparison_result_evaluated", "validator", "comparison_result_evaluated|Input should be False")
def _c(d, x):
    return bool(d["baselines"]) and _set(d["baselines"][0], comparison_result_evaluated=True)


@control("coverage_reads_experimental_success", "validator", "result_success_evaluated|Input should be False")
def _c(d, x):
    return bool(d["phase2j_coverage"]) and _set(d["phase2j_coverage"][0], result_success_evaluated=True)


@control("external_search_allowed", "validator", "external_search_calls|Input should be 0")
def _c(d, x):
    return _set(d, external_search_calls=1)


@control("network_attempt_allowed", "validator", "network_attempts|Input should be 0")
def _c(d, x):
    return _set(d, network_attempts=1)


@control("socket_opened_during_run", "gate", "socket_opened_during_run")
def _c(d, x):
    x.network_attempts = 1
    return True


# =========================================================================================================
# identity
# =========================================================================================================

@control("protocol_key_not_the_text_hash", "gate", "protocol_key_not_text_hash")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], protocol_key="0" * 64)


@control("duplicate_experiment_recorded", "validator", "duplicate protocol")
def _c(d, x):
    if not d["experiments"]:
        return False
    d["experiments"].append(copy.deepcopy(d["experiments"][0]))
    return True


@control("revision_of_unknown_experiment", "gate", "revision_of_self_or_unknown")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], revision_of=_fake())


@control("experiment_without_defining_excerpt", "validator", "defining_excerpt_ids|at least 1 item")
def _c(d, x):
    return bool(d["experiments"]) and _set(d["experiments"][0], defining_excerpt_ids=[])


@control("experiment_id_depends_on_offsets", "gate", "experiment_id_depends_on_offsets")
def _c(d, x):
    if x.case.twin != "prefix":
        return False
    x.twins["prefix_ids"] = False
    return True


# =========================================================================================================
# applicability and the catalog
# =========================================================================================================

@control("required_row_lowered_to_not_applicable", "gate", "catalog_required_row_lowered")
def _c(d, x):
    return _with([r for e, r in _reqs(d) if cat.cell(r["kind"], e["experiment_type"]) == "R"], lambda r: True,
                 lambda r: r.update(applicability="NOT_APPLICABLE", documentation="NOT_APPLICABLE", adequacy="NOT_APPLICABLE",
                                    excerpt_ids=[]))


@control("required_row_lowered_to_conditional", "validator", "never CONDITIONAL")
def _c(d, x):
    return _with([r for e, r in _reqs(d) if cat.cell(r["kind"], e["experiment_type"]) == "R"], lambda r: True,
                 lambda r: r.update(applicability="CONDITIONAL"))


@control("model_resolution_without_judgment_excerpts", "gate", "conditional_resolved_without_judgment")
def _c(d, x):
    return _with([r for _, r in _reqs(d) if r["basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT"], lambda r: True,
                 lambda r: r.update(judgment_excerpt_ids=[]))


@control("unknown_type_universal_row_lowered", "gate", "unknown_type_universal_row_lowered")
def _c(d, x):
    return _with([r for e, r in _reqs(d) if e["experiment_type"] == "UNKNOWN" and r["kind"] in cat.UNIVERSAL], lambda r: True,
                 lambda r: r.update(applicability="CONDITIONAL"))


@control("unknown_type_reads_well", "gate", "unknown_type_reads_well")
def _c(d, x):
    return _with([e for e in d["experiments"] if e["experiment_type"] == "UNKNOWN"], lambda e: True,
                 lambda e: e.update(posture="WELL_SPECIFIED"))


@control("invented_requirement_kind", "gate", "invented_requirement_persisted")
def _c(d, x):
    return _with([r for _, r in _reqs(d)], lambda r: True, lambda r: r.update(kind="MAGIC_REQUIREMENT"))


@control("requirement_inventory_truncated", "gate", "requirement_inventory_incomplete")
def _c(d, x):
    return _with(d["experiments"], lambda e: bool(e["requirements"]), lambda e: e.update(requirements=e["requirements"][:-1]))


@control("statistics_required_by_default", "gate", "statistics_required_by_default")
def _c(d, x):
    return _with([r for _, r in _reqs(d) if r["kind"] == "STATISTICAL_TEST"], lambda r: True,
                 lambda r: r.update(applicability="REQUIRED", basis="CATALOG_DEFAULT"))


@control("statistics_required_without_trigger", "gate", "statistics_required_without_trigger_or_judgment")
def _c(d, x):
    return _with([r for _, r in _reqs(d) if r["kind"] in ("STATISTICAL_TEST", "CONFIDENCE_INTERVAL", "EFFECT_SIZE")], lambda r: True,
                 lambda r: r.update(applicability="REQUIRED", basis="MODEL_ASSISTED_BOUNDED_JUDGMENT", triggers=[]))


@control("p_value_makes_statistics_required", "gate", "p_value_presence_requires_statistics")
def _c(d, x):
    if not (x.flags.get("p_value_present") and x.flags.get("no_inference")):
        return False
    return _with([r for _, r in _reqs(d) if r["kind"] == "STATISTICAL_TEST"], lambda r: True,
                 lambda r: r.update(applicability="REQUIRED", basis="MODEL_ASSISTED_BOUNDED_JUDGMENT", triggers=["STATISTICAL_INFERENCE_CLAIMED"]))


@control("conditional_resolved_by_omission", "gate", "conditional_resolved_by_omission")
def _c(d, x):
    return bool(x.case.model_script.get("applicability_omit")) and _with(
        [r for e, r in _reqs(d) if not set(cat.TRIGGERS[r["kind"]]) & set(cat.PHASE_2J_TRIGGERS)],
        lambda r: r["applicability"] == "CONDITIONAL",
        lambda r: r.update(applicability="NOT_APPLICABLE", basis="MODEL_ASSISTED_BOUNDED_JUDGMENT"))


# =========================================================================================================
# linkage and measurement
# =========================================================================================================

@control("foreign_target_link", "gate", "link_unknown_target_accepted")
def _c(d, x):
    return bool(d["links"]) and _set(d["links"][0], claim_id="C-999")


@control("measurement_removed_directly_tests_kept", "gate", "directly_tests_without_aligned_measurement")
def _c(d, x):
    if not any(lk["relation"] == "DIRECTLY_TESTS" for lk in d["links"]):
        return False
    d["measurements"] = []
    return True


@control("metric_wrong_target_kept_directly_tests", "gate", "directly_tests_without_aligned_measurement")
def _c(d, x):
    return _with(d["measurements"], lambda m: m["alignment"] == "ALIGNED_SAME_TARGET",
                 lambda m: m.update(alignment="METRIC_TARGET_MISMATCH"))


@control("aligned_without_metric_excerpt", "gate", "aligned_without_metric_excerpt")
def _c(d, x):
    return _with(d["measurements"], lambda m: m["alignment"] == "ALIGNED_SAME_TARGET", lambda m: m.update(metric_excerpt_id=None))


@control("aligned_without_method_excerpt", "gate", "aligned_without_method_excerpt")
def _c(d, x):
    return _with(d["measurements"], lambda m: m["alignment"] == "ALIGNED_SAME_TARGET", lambda m: m.update(method_excerpt_id=None))


@control("same_as_phase2j_without_alignment", "gate", "same_as_phase2j_without_alignment")
def _c(d, x):
    return _with(d["measurements"], lambda m: m["alignment"] == "ALIGNED_SAME_TARGET",
                 lambda m: m.update(alignment="METRIC_NOT_DEFINED", phase2j_metric_match="SAME_AS_PHASE_2J"))


@control("mismatch_without_issue", "gate", "metric_mismatch_without_issue")
def _c(d, x):
    hit = _first(d["measurements"], lambda m: m["alignment"] == "ALIGNED_SAME_TARGET")
    if hit is None:
        return False
    hit["alignment"] = "METRIC_TARGET_MISMATCH"
    for e in d["experiments"]:
        if e["experiment_id"] == hit["experiment_id"]:
            e["issues"] = [i for i in e["issues"] if i != "METRIC_TARGET_MISMATCH"]
    return True


@control("post_hoc_criterion_without_issue", "gate", "post_hoc_criterion_without_issue")
def _c(d, x):
    return _with(d["measurements"], lambda m: m["success_criterion_excerpt_id"] is not None,
                 lambda m: m.update(success_criterion_timing="POST_HOC_AS_DESCRIBED"))


@control("testing_link_without_cited_protocol", "gate", "testing_link_without_cited_protocol")
def _c(d, x):
    return _with(d["links"], lambda lk: lk["relation"] in cat.TESTING, lambda lk: lk.update(excerpt_ids=[]))


@control("target_left_without_link", "gate", "target_left_without_link")
def _c(d, x):
    if not d["links"] or d["status"] != "COMPLETED":
        return False
    d["links"] = d["links"][1:]
    return True


@control("omitted_target_read_as_does_not_test", "gate", "omitted_target_read_as_does_not_test")
def _c(d, x):
    return bool(x.flags.get("omitted_target")) and _with(d["links"], lambda lk: lk["relation"] == "UNRESOLVED",
                                                         lambda lk: lk.update(relation="DOES_NOT_TEST"))


@control("link_cites_another_experiments_excerpt", "gate", "link_excerpt_from_another_experiment")
def _c(d, x):
    if len(d["experiments"]) < 2:
        return False
    other = d["experiments"][1]["defining_excerpt_ids"][0]
    me = d["experiments"][0]["experiment_id"]
    return _with(d["links"], lambda lk: lk["experiment_id"] == me and lk["relation"] in cat.TESTING, lambda lk: lk.update(excerpt_ids=[other]))


@control("metric_borrowed_from_another_experiment", "gate", "measurement_excerpt_from_another_experiment")
def _c(d, x):
    if len(d["experiments"]) < 2:
        return False
    other = d["experiments"][1]["defining_excerpt_ids"][0]
    me = d["experiments"][0]["experiment_id"]
    return _with(d["measurements"], lambda m: m["experiment_id"] == me, lambda m: m.update(metric_excerpt_id=other))


@control("condition_marked_addressed_without_excerpt", "gate", "condition_covered_without_excerpt")
def _c(d, x):
    return _with(d["conditions"], lambda cd: cd["status"] == "ADDRESSED_IN_PROTOCOL", lambda cd: cd.update(excerpt_ids=[]))


@control("foreign_target_id_accepted", "gate", "foreign_target_accepted")
def _c(d, x):
    if not x.flags.get("foreign_target") or not d["links"]:
        return False
    extra = copy.deepcopy(d["links"][0])
    extra.update(link_id=_fake())
    d["links"].append(extra)
    return True


@control("cross_run_target_id_accepted", "gate", "cross_run_target_id_accepted")
def _c(d, x):
    uid = x.flags.get("cross_run_target")
    if not uid:
        return False
    d["errors"] = [*d["errors"], {"code": "UNKNOWN_TARGET", "node": "EXPERIMENT_LINK_TARGETS", "message": uid, "experiment_id": None}]
    return True


# =========================================================================================================
# Phase 2J continuity
# =========================================================================================================

@control("coverage_forged_covered", "gate", "coverage_status_unsupported")
def _c(d, x):
    return _with(d["phase2j_coverage"], lambda cv: cv["status"] != "COVERED_BY_EXPERIMENT",
                 lambda cv: cv.update(status="COVERED_BY_EXPERIMENT", reasons=[]))


@control("mosaic_pooled_into_covered", "gate", "cross_experiment_mosaic_coverage")
def _c(d, x):
    return _with(d["phase2j_coverage"], lambda cv: cv["status"] == "PARTIALLY_COVERED" and len(cv["attempting_experiment_ids"]) > 1,
                 lambda cv: cv.update(status="COVERED_BY_EXPERIMENT", reasons=[], covering_experiment_ids=list(cv["attempting_experiment_ids"])))


@control("covering_experiment_does_not_attempt", "gate", "covering_experiment_does_not_attempt")
def _c(d, x):
    return _with(d["phase2j_coverage"], lambda cv: cv["status"] == "COVERED_BY_EXPERIMENT",
                 lambda cv: cv.update(attempting_experiment_ids=[]))


@control("noncovered_status_without_reason", "gate", "noncovered_status_without_reason")
def _c(d, x):
    return _with(d["phase2j_coverage"], lambda cv: cv["status"] != "COVERED_BY_EXPERIMENT", lambda cv: cv.update(reasons=[]))


@control("covered_baseline_ignored", "gate", "covered_baseline_required_without_relevant_baseline")
def _c(d, x):
    if not any(cv["status"] == "COVERED_BY_EXPERIMENT" for cv in d["phase2j_coverage"]) or not d["baselines"]:
        return False
    d["baselines"] = []
    return True


@control("covered_condition_ignored", "gate", "covered_with_uncovered_condition")
def _c(d, x):
    if not any(cv["status"] == "COVERED_BY_EXPERIMENT" for cv in d["phase2j_coverage"]) or not d["conditions"]:
        return False
    d["conditions"] = []
    return True


@control("covered_by_inadequate_experiment", "gate", "covered_by_inadequate_experiment")
def _c(d, x):
    hit = _first(d["phase2j_coverage"], lambda cv: cv["status"] == "COVERED_BY_EXPERIMENT")
    if hit is None:
        return False
    for e in d["experiments"]:
        if e["experiment_id"] in hit["covering_experiment_ids"]:
            e["posture"] = "MAJOR_GAPS"
    return True


@control("coverage_invented_for_hypothesis_without_requirement", "gate", "requirement_invented_for_hypothesis_without_one")
def _c(d, x):
    if not x.flags.get("no_requirement"):
        return False
    d["bound_validation_targets"] = [{"validation_requirement_id": _fake(), "gap_hypothesis_id": _fake(), "claim_id": "C-001",
                                      "metric_anchor_hash": "0" * 64, "baseline_anchor_hash": None, "condition_ids": [],
                                      "limitation_facets": []}]
    return True


@control("coverage_record_dropped", "gate", "coverage_record_count_mismatch")
def _c(d, x):
    if not d["phase2j_coverage"] or d["status"] != "COMPLETED":
        return False
    d["phase2j_coverage"] = d["phase2j_coverage"][1:]
    return True


@control("mosaic_scenario_reads_covered", "gate", "mosaic_scenario_reads_covered")
def _c(d, x):
    return bool(x.flags.get("mosaic")) and _with(d["phase2j_coverage"], lambda cv: True, lambda cv: cv.update(status="COVERED_BY_EXPERIMENT"))


# =========================================================================================================
# baseline and comparator
# =========================================================================================================

@control("baseline_name_taken_as_relevance", "gate", "baseline_name_implies_relevance")
def _c(d, x):
    return bool(x.flags.get("baseline_name_only")) and _with(d["baselines"], lambda b: True,
                                                             lambda b: b.update(relevance="RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"))


@control("global_fair_conclusion_added", "gate", "global_fairness_conclusion_field")
def _c(d, x):
    return _with(d["baselines"], lambda b: True, lambda b: b.update(fair=True))


@control("documented_comparability_without_excerpt", "gate", "documented_comparability_without_excerpt")
def _c(d, x):
    return _with([p for b in d["baselines"] for p in b["comparability"]], lambda p: p["status"] in ("DOCUMENTED_SAME", "DOCUMENTED_DIFFERENT"),
                 lambda p: p.update(excerpt_ids=[]))


@control("deterministic_basis_on_non_metric_property", "gate", "deterministic_comparability_for_non_metric_property")
def _c(d, x):
    return _with([p for b in d["baselines"] for p in b["comparability"]], lambda p: p["property"] != "SAME_EVALUATION_METRIC",
                 lambda p: p.update(basis="DETERMINISTIC_SHARED_METRIC_BINDING"))


@control("comparability_not_applicable_asserted", "gate", "comparability_not_applicable_asserted")
def _c(d, x):
    return _with([p for b in d["baselines"] for p in b["comparability"]], lambda p: True, lambda p: p.update(status="NOT_APPLICABLE"))


@control("comparability_gap_without_issue", "gate", "comparability_difference_without_issue")
def _c(d, x):
    hit = _first(d["baselines"], lambda b: any(p["status"] == "DOCUMENTED_DIFFERENT" for p in b["comparability"]) and b["baseline_excerpt_ids"])
    if hit is None:
        return False
    for e in d["experiments"]:
        if e["experiment_id"] == hit["experiment_id"]:
            e["issues"] = [i for i in e["issues"] if i != "BASELINE_COMPARABILITY_GAP"]
    return True


@control("irrelevant_baseline_without_issue", "gate", "irrelevant_baseline_without_issue")
def _c(d, x):
    hit = _first(d["baselines"], lambda b: b["relevance"] == "NOT_RELEVANT_TO_TARGET")
    if hit is None:
        return False
    for e in d["experiments"]:
        if e["experiment_id"] == hit["experiment_id"]:
            e["issues"] = [i for i in e["issues"] if i != "BASELINE_NOT_RELEVANT"]
    return True


@control("improvement_claim_baseline_absent_reads_well", "gate", "improvement_claim_without_baseline_reads_well")
def _c(d, x):
    return bool(x.flags.get("baseline_required_missing")) and _with(d["experiments"], lambda e: True, lambda e: e.update(posture="WELL_SPECIFIED", issues=[]))


@control("baseline_without_named_excerpt", "gate", "baseline_without_named_excerpt")
def _c(d, x):
    return _with(d["baselines"], lambda b: True, lambda b: b.update(baseline_excerpt_ids=[]))


# =========================================================================================================
# sample, repetition, statistics
# =========================================================================================================

@control("bare_number_rated_adequate", "gate", "bare_number_rated_adequate")
def _c(d, x):
    bare = _first(d["excerpts"], lambda e: c.is_bare_quantity(e["excerpt"]))
    if bare is None:
        return False
    return _with([r for _, r in _reqs(d) if r["kind"] == "SAMPLE_SIZE"], lambda r: True,
                 lambda r: r.update(excerpt_ids=[bare["excerpt_id"]], documentation="EXPLICITLY_DOCUMENTED", adequacy=GOOD))


@control("bare_number_documents_rationale", "gate", "bare_number_documents_sample_rationale")
def _c(d, x):
    bare = _first(d["excerpts"], lambda e: c.is_bare_quantity(e["excerpt"]))
    if bare is None or not x.flags.get("bare_n"):
        return False
    return _with([r for _, r in _reqs(d) if r["kind"] == "SAMPLE_SIZE_RATIONALE"], lambda r: True,
                 lambda r: r.update(excerpt_ids=[bare["excerpt_id"]], documentation="EXPLICITLY_DOCUMENTED", adequacy=GOOD))


@control("repetition_count_taken_as_independence", "gate", "repetition_count_implies_independence")
def _c(d, x):
    if not x.flags.get("rep_count_only"):
        return False
    rep = _first(d["excerpts"])
    return rep is not None and _with([r for _, r in _reqs(d) if r["kind"] == "REPETITION_INDEPENDENCE"], lambda r: True,
                                     lambda r: r.update(excerpt_ids=[rep["excerpt_id"]], documentation="EXPLICITLY_DOCUMENTED", adequacy=GOOD))


@control("missing_p_value_fails_case", "gate", "missing_p_value_fails_case")
def _c(d, x):
    return bool(x.flags.get("no_p_value")) and _with(d["experiments"], lambda e: True, lambda e: e.update(issues=[*e["issues"], "STATISTICS_MISSING_WHEN_REQUIRED"]))


@control("adequacy_above_documentation", "gate", "adequacy_above_documentation")
def _c(d, x):
    return _with([r for _, r in _reqs(d)], lambda r: r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT",
                 lambda r: r.update(adequacy=GOOD))


# =========================================================================================================
# postures, ownership, HYBRID
# =========================================================================================================

@control("experiment_posture_forged_up", "gate", "experiment_posture_stronger_than_derived")
def _c(d, x):
    return _with(d["experiments"], lambda e: e["requirements"] and e["posture"] in ("MAJOR_GAPS", "PARTIALLY_SPECIFIED", "UNRESOLVED"),
                 lambda e: e.update(posture="WELL_SPECIFIED"))


@control("well_specified_despite_issue", "gate", "well_specified_with_issue")
def _c(d, x):
    return _with(d["experiments"], lambda e: bool(e["issues"]), lambda e: e.update(posture="WELL_SPECIFIED"))


@control("track_posture_forged_up", "gate", "track_posture_stronger_than_derived")
def _c(d, x):
    return _with(d["track_postures"], lambda t: t["posture"] != "WELL_SPECIFIED", lambda t: t.update(posture="WELL_SPECIFIED"))


@control("project_posture_forged_well", "gate", "project_posture_stronger_than_derived")
def _c(d, x):
    return d["project_posture"] not in (None, "WELL_SPECIFIED") and _set(d, project_posture="WELL_SPECIFIED")


@control("project_well_with_untested_claim", "gate", "project_well_specified_with_untested_claim")
def _c(d, x):
    if not d["untested_claim_ids"]:
        return False
    return _set(d, project_posture="WELL_SPECIFIED")


@control("project_well_with_unowned_experiment", "gate", "project_well_specified_with_unowned_experiment")
def _c(d, x):
    return _with(d["experiments"], lambda e: e["track"] is None, lambda e: d.update(project_posture="WELL_SPECIFIED"))


@control("hybrid_tracks_averaged", "gate", "hybrid_strong_track_hides_weak_track")
def _c(d, x):
    if x.project_type != "HYBRID" or len(d["track_postures"]) < 2 or not any(t["posture"] != "WELL_SPECIFIED" for t in d["track_postures"]):
        return False
    return _set(d, project_posture="WELL_SPECIFIED")


@control("unowned_experiment_counted_in_track", "gate", "unowned_experiment_counted_in_track")
def _c(d, x):
    e = _first(d["experiments"], lambda e: e["track"] is None)
    if e is None or not d["track_postures"]:
        return False
    d["track_postures"][0]["experiment_ids"] = [*d["track_postures"][0]["experiment_ids"], e["experiment_id"]]
    return True


@control("experiment_counted_in_two_tracks", "gate", "experiment_counted_in_two_tracks")
def _c(d, x):
    if len(d["track_postures"]) < 2 or not d["track_postures"][0]["experiment_ids"]:
        return False
    d["track_postures"][1]["experiment_ids"] = [*d["track_postures"][1]["experiment_ids"], d["track_postures"][0]["experiment_ids"][0]]
    return True


@control("single_track_basis_claimed_for_hybrid", "gate", "single_track_basis_on_hybrid_project")
def _c(d, x):
    return x.project_type == "HYBRID" and _with(d["experiments"], lambda e: True, lambda e: e.update(ownership_basis="SINGLE_TRACK_PROJECT"))


@control("model_ownership_without_excerpts", "gate", "model_ownership_without_excerpts")
def _c(d, x):
    return _with(d["experiments"], lambda e: e["ownership_basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT", lambda e: e.update(ownership_excerpt_ids=[]))


@control("unresolved_ownership_keeps_a_track", "gate", "unresolved_ownership_with_track")
def _c(d, x):
    return _with(d["experiments"], lambda e: e["ownership_basis"] == "UNRESOLVED", lambda e: e.update(track="ENGINEERING"))


@control("untested_claim_dropped", "gate", "untested_claim_ids_wrong")
def _c(d, x):
    return bool(d["untested_claim_ids"]) and d["status"] == "COMPLETED" and _set(d, untested_claim_ids=[])


@control("does_not_test_experiment_made_covering", "gate", "does_not_test_experiment_covers_target")
def _c(d, x):
    e = _first(d["experiments"], lambda e: x.links_of(e) and all(lk["relation"] == "DOES_NOT_TEST" for lk in d["links"] if lk["experiment_id"] == e["experiment_id"]))
    if e is None or not d["phase2j_coverage"]:
        return False
    d["phase2j_coverage"][0]["covering_experiment_ids"] = [e["experiment_id"]]
    return True


# =========================================================================================================
# provider failures and the call bound
# =========================================================================================================

@control("provider_failure_yields_strong_posture", "gate", "provider_failure_yields_strong_posture")
def _c(d, x):
    return bool(x.flags.get("provider_failure")) and _set(d, project_posture="WELL_SPECIFIED")


@control("provider_failure_error_cleared", "gate", "provider_failure_without_stage_code")
def _c(d, x):
    if not x.flags.get("provider_failure"):
        return False
    d["errors"] = []
    return True


@control("raw_model_text_persisted", "gate", "model_text_persisted")
def _c(d, x):
    texts = x.flags.get("model_texts", [])
    if not texts:
        return False
    d["errors"] = [*d["errors"], {"code": "MODEL_REFUSED", "node": "EXPERIMENT_SEGMENT", "message": texts[0], "experiment_id": None}]
    return True


@control("hidden_prompt_persisted", "gate", "hidden_prompt_persisted")
def _c(d, x):
    if not x.flags.get("leaks_prompt"):
        return False
    d["errors"] = [*d["errors"], {"code": "PROMPT_LEAK_REDACTED", "node": "EXPERIMENT_SEGMENT", "message": prompt_line(), "experiment_id": None}]
    return True


@control("calls_exceed_recorded_bound", "validator", "model calls exceed the run bound")
def _c(d, x):
    return _set(d, model_calls_performed=d["bounds"]["max_model_calls"] + 1)


@control("provider_requests_miscounted", "gate", "provider_requests_not_counted")
def _c(d, x):
    if x.model is None:
        return False
    return _set(d, model_calls_performed=d["model_calls_performed"] + 1)


@control("hidden_retry_over_budget", "gate", "call_made_after_budget_exhausted")
def _c(d, x):
    if not any(e["code"] == "MODEL_CALL_BOUND_REACHED" for e in d["errors"]):
        return False
    x.provider_requests = d["bounds"]["max_model_calls"] + 1
    return True


@control("call_made_without_provider", "gate", "call_made_without_provider")
def _c(d, x):
    if not x.case.no_model:
        return False
    x.provider_requests = 1
    return True


@control("partial_output_ignored", "gate", "provider_failure_without_stage_code")
def _c(d, x):
    if not str(x.flags.get("provider_failure", "")).endswith("PARTIAL_MODEL_OUTPUT"):
        return False
    d["errors"] = [e for e in d["errors"] if e["code"] != "PARTIAL_MODEL_OUTPUT"]
    return True


@control("failed_extraction_requirement_sufficient", "gate", "failed_extraction_requirement_not_insufficient")
def _c(d, x):
    if not str(x.flags.get("provider_failure", "")).startswith("EXTRACT:"):
        return False
    return _with([r for _, r in _reqs(d)], lambda r: r["applicability"] != "NOT_APPLICABLE",
                 lambda r: r.update(documentation="EXPLICITLY_DOCUMENTED"))


@control("failed_linkage_target_resolved", "gate", "failed_linkage_target_not_unresolved")
def _c(d, x):
    if not str(x.flags.get("provider_failure", "")).startswith("LINK:"):
        return False
    return _with(d["links"], lambda lk: True, lambda lk: lk.update(relation="DIRECTLY_TESTS"))


@control("failed_segmentation_keeps_experiments", "gate", "failed_segmentation_kept_experiments")
def _c(d, x):
    if not str(x.flags.get("provider_failure", "")).startswith("SEGMENT:"):
        return False
    d["experiments"] = [{**{k: None for k in ()}, "experiment_id": _fake()}]
    return True


@control("refusal_retried", "gate", "refusal_retried")
def _c(d, x):
    ps = [p for p in ("segment", "extract", "applicability", "link") if x.case.model_script.get(p) == "refusal"]
    if not ps:
        return False
    x.calls_by_task = {**x.calls_by_task, ps[0]: 2}
    return True


@control("error_emitted_by_forbidden_stage", "gate", "error_emitted_by_forbidden_stage")
def _c(d, x):
    return bool(d["errors"]) and _set(d["errors"][0], code="UPSTREAM_MUTATED", node="EXPERIMENT_SEGMENT")


@control("rejection_digest_carries_text", "gate", "rejection_digest_carries_text")
def _c(d, x):
    return bool(d["rejected_proposals"]) and _set(d["rejected_proposals"][0], response_digest="a model wrote this sentence")


# =========================================================================================================
# the prompt boundary
# =========================================================================================================

def _prompt(x, pred=lambda t, p: True):
    return next((i for i, (t, p) in enumerate(x.prompts) if pred(t, p)), None)


@control("student_text_moved_to_trusted_tail", "gate", "student_text_in_trusted_tail")
def _c(d, x):
    i = _prompt(x)
    sents = [s for s in x.flags.get("protocol", []) if len(s) >= 12]
    if i is None or not sents:
        return False
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + "\n" + sents[0])
    return True


@control("forged_marker_not_escaped", "gate", "forged_marker_unescaped")
def _c(d, x):
    i = _prompt(x, lambda t, p: c.ZWSP in p)
    if i is None or not x.flags.get("markers"):
        return False
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1].replace(c.ZWSP, ""))
    return True


@control("second_end_marker_accepted", "gate", "prompt_end_marker_count_not_one")
def _c(d, x):
    i = _prompt(x)
    if i is None:
        return False
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + "\n" + c.MARKER_END)
    return True


@control("arabic_text_in_trusted_tail", "gate", "non_ascii_in_trusted_tail")
def _c(d, x):
    i = _prompt(x)
    if i is None or x.case.language == "en":
        return False
    arabic = "".join(chr(code) for code in (0x627, 0x644, 0x645, 0x62D, 0x62A, 0x648, 0x649))
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + chr(10) + arabic)
    return True


@control("claim_text_moved_after_end_marker", "gate", "student_claim_outside_untrusted_block")
def _c(d, x):
    i = _prompt(x, lambda t, p: x.claim in p)
    if i is None:
        return False
    body = x.prompts[i][1]
    x.prompts[i] = (x.prompts[i][0], body.replace(x.claim, "", 1) + "\n" + x.claim)
    return True


@control("result_value_in_trusted_tail", "gate", "result_in_trusted_tail")
def _c(d, x):
    rs = [r for r in x.flags.get("declared_results", []) if r.strip()]
    i = _prompt(x)
    if i is None or not rs:
        return False
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + "\n" + rs[0])
    return True


# =========================================================================================================
# determinism, replay, canonical order
# =========================================================================================================

@control("experiments_unordered", "gate", "experiments_not_canonical")
def _c(d, x):
    if len(d["experiments"]) < 2:
        return False
    d["experiments"].reverse()
    return True


@control("excerpts_unordered", "gate", "excerpts_not_canonical")
def _c(d, x):
    if len(d["excerpts"]) < 2:
        return False
    d["excerpts"].reverse()
    return True


@control("links_unordered", "gate", "links_not_canonical")
def _c(d, x):
    if len(d["links"]) < 2:
        return False
    d["links"].reverse()
    return True


@control("requirements_unordered", "gate", "requirements_not_in_catalog_order")
def _c(d, x):
    e = _first(d["experiments"], lambda e: len(e["requirements"]) > 2)
    if e is None:
        return False
    e["requirements"].reverse()
    return True


@control("replay_changes_the_review", "gate", "replay_changed_review")
def _c(d, x):
    if not x.case.rerun:
        return False
    x.replay["same"] = False
    return True


@control("replay_makes_a_model_call", "gate", "replay_made_model_call")
def _c(d, x):
    if not x.case.rerun:
        return False
    x.replay["extra_calls"] = 1
    return True


@control("resume_changes_the_review", "gate", "resume_changed_review")
def _c(d, x):
    if not x.case.interrupt_before:
        return False
    x.replay["resume_same"] = False
    return True


@control("model_list_order_changes_the_review", "gate", "model_order_changed_review")
def _c(d, x):
    if x.case.twin != "order":
        return False
    x.twins["order"] = False
    return True


@control("model_list_order_changes_ids", "gate", "model_order_changed_ids")
def _c(d, x):
    if x.case.twin != "order":
        return False
    x.twins["ids"] = False
    return True


@control("offset_shift_changes_adequacy", "gate", "prefix_text_changed_adequacy")
def _c(d, x):
    if x.case.twin != "prefix":
        return False
    x.twins["prefix"] = False
    return True


# =========================================================================================================
# upstream, terminal status, legacy inputs, forbidden fields
# =========================================================================================================

@control("mutated_upstream_keeps_records", "gate", "mutated_upstream_keeps_records")
def _c(d, x):
    if not x.case.mutate:
        return False
    x.mutated["kept"] = 3
    return True


@control("mutated_upstream_undetected", "gate", "upstream_mutation_not_detected")
def _c(d, x):
    if not x.case.mutate:
        return False
    x.mutated["status"] = "COMPLETED"
    return True


@control("mutated_upstream_keeps_posture", "gate", "mutated_upstream_keeps_posture")
def _c(d, x):
    if not x.case.mutate:
        return False
    x.mutated["posture"] = "WELL_SPECIFIED"
    return True


@control("insufficient_input_keeps_posture", "gate", "insufficient_input_with_posture")
def _c(d, x):
    if d["status"] != "INSUFFICIENT_INPUT" or any(e["code"] == "EXPERIMENT_BOUND_REACHED" for e in d["errors"]):
        return False
    return _set(d, project_posture="WELL_SPECIFIED")


@control("bound_reached_run_reads_complete", "gate", "bound_reached_run_reads_complete")
def _c(d, x):
    if not any(e["code"] == "EXPERIMENT_BOUND_REACHED" for e in d["errors"]):
        return False
    return _set(d, status="COMPLETED")


@control("legacy_result_reaches_a_prompt", "gate", "legacy_marker_in_model_prompt")
def _c(d, x):
    i = _prompt(x)
    if i is None or not x.case.legacy_leak:
        return False
    x.prompts[i] = (x.prompts[i][0], x.prompts[i][1] + "\n" + LEGACY_MARKER)
    return True


@control("legacy_result_reaches_the_output", "gate", "legacy_marker_in_output")
def _c(d, x):
    if not x.case.legacy_leak:
        return False
    d["errors"] = [*d["errors"], {"code": "PARTIAL_MODEL_OUTPUT", "node": "EXPERIMENT_SEGMENT", "message": LEGACY_MARKER, "experiment_id": None}]
    return True


@control("legacy_state_changes_the_review", "gate", "legacy_state_changes_review")
def _c(d, x):
    if not x.case.legacy_leak:
        return False
    x.legacy_twin["same"] = False
    return True


@control("novelty_score_field_added", "gate", "forbidden_field_in_output")
def _c(d, x):
    return _set(d, novelty_score=0.9)


@control("legal_conclusion_in_output", "gate", "legal_conclusion_text_in_output")
def _c(d, x):
    d["errors"] = [*d["errors"], {"code": "PARTIAL_MODEL_OUTPUT", "node": "EXPERIMENT_SEGMENT", "message": "this design is patentable",
                                  "experiment_id": None}]
    return True


@control("probability_field_added", "gate", "score_or_probability_field")
def _c(d, x):
    return _set(d, truth_probability=0.97)


ALL_CONTROLS: tuple[str, ...] = tuple(CONTROL_FUNCS)


def run_control(ctx: Ctx, name: str) -> tuple[bool | None, str]:
    """Apply one control to a copy of the case's finished run. ``None``: not applicable (no opportunity)."""
    fn, (kind, expect) = CONTROL_FUNCS[name]
    key = (name, ctx.case.language)
    if _BUDGET.get(key, 0) >= PER_LANGUAGE:
        return None, "budget"
    d = copy.deepcopy(ctx.d)
    mx = replace(ctx, d=d, prompts=list(ctx.prompts), twins=dict(ctx.twins), replay=dict(ctx.replay), mutated=dict(ctx.mutated),
                 legacy_twin=dict(ctx.legacy_twin), calls_by_task=dict(ctx.calls_by_task))
    if not fn(d, mx):
        return None, "not applicable"
    if kind == "validator":
        if validate_run(ctx.d) is not None:
            return None, "unmutated run does not validate"
        error = validate_run(d)
        _BUDGET[key] = _BUDGET.get(key, 0) + 1
        if error is None:
            return False, "the mutated run still validates"
        caught = all(part.lower() in error.lower() for part in expect.split("|"))
        return caught, (error.splitlines()[-2] if len(error.splitlines()) > 1 else error)[:200]
    base, mutated = GATE_FUNCS[expect](ctx)[0], GATE_FUNCS[expect](mx)[0]
    _BUDGET[key] = _BUDGET.get(key, 0) + 1
    if base:
        return None, f"gate {expect} already violated on the unmutated run"
    return mutated > 0, f"gate {expect}: {mutated} violation(s)"


__all__ = ["ALL_CONTROLS", "CONTROL_FUNCS", "reset_control_budget", "run_control"]
