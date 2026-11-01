"""Phase 3B release-blocking gates.

Every gate returns ``(violations, opportunities)`` for ONE case and is evaluated from the serialized run, the
upstream records and the AUTHORED case facts (``case.flags``), never through a Phase 3B validator or derivation
function. Opportunities are real: the count of situations in the case that could violate THIS invariant. There is
no synthetic denominator floor: a case with no opportunity adds zero, and a gate's denominator is counted from the
case's own facts.

``_g(name, items, opp, viol)``: ``items(x)`` lists the situations of case context ``x``; ``opp(x, item)`` selects
the real opportunities among them; ``viol(x, item)`` says the unsafe behaviour happened.
"""

from __future__ import annotations

from typing import Any, Callable

from src.evals.experiment_review import catalog as cat
from src.evals.experiment_review import context as c
from src.evals.experiment_review.context import Ctx
from src.evals.experiment_review.quality import (
    INCOMPLETE_MESSAGE,
    STAT_KINDS,
    segmented,
    declared_results,
    own_excerpt_ids,
    student_strings,
    window_text,
)

GATE_FUNCS: dict[str, Callable[[Ctx], tuple[int, int]]] = {}
GATES: list[str] = []
GOOD = "ADEQUATELY_SPECIFIED_FOR_REVIEW"
RANK = {p: i for i, p in enumerate(cat.WORST_ORDER)}


def _g(name: str, items: Callable[[Ctx], Any], opp: Callable[[Ctx, Any], bool] | None,
       viol: Callable[[Ctx, Any], Any]) -> None:
    assert name not in GATE_FUNCS, name

    def fn(x: Ctx) -> tuple[int, int]:
        opportunities = violations = 0
        for item in items(x):
            if opp is None or opp(x, item):
                opportunities += 1
                violations += int(bool(viol(x, item)))
        return violations, opportunities

    GATE_FUNCS[name] = fn
    GATES.append(name)


def F(x: Ctx, name: str, default: Any = None) -> Any:
    return x.case.flags.get(name, default)


def _by_req(x: Ctx) -> dict[str, dict[str, Any]]:
    return {t["validation_requirement_id"]: t for t in x.targets}


def _claims(x: Ctx) -> set[str]:
    return {cl["claim_id"] for cl in x.d["bound_claims"]}


def _reqs(x: Ctx):
    return [(e, r) for e in x.d["experiments"] for r in e["requirements"]]


def _assessed(x: Ctx):
    return [e for e in x.d["experiments"] if e["requirements"]]


def _target_key(rec: dict[str, Any]) -> tuple:
    return (rec.get("claim_id", rec.get("target_claim_id")), rec["gap_hypothesis_id"], rec["validation_requirement_id"])


def _target_known(x: Ctx, rec: dict[str, Any]) -> bool:
    claim, hyp, req = _target_key(rec)
    if claim not in _claims(x):
        return False
    if req is None:
        return hyp is None
    t = _by_req(x).get(req)
    return t is not None and t["gap_hypothesis_id"] == hyp and t["claim_id"] == claim


def _stage_ran(x: Ctx) -> bool:
    return not F(x, "incomplete_quarantine") and x.d["status"] in ("COMPLETED",)


def _aligned_for(x: Ctx, link: dict[str, Any]) -> bool:
    return any(m["experiment_id"] == link["experiment_id"] and m["alignment"] == "ALIGNED_SAME_TARGET"
               and _target_key(m) == _target_key(link) for m in x.d["measurements"])


# =========================================================================================================
# source and provenance
# =========================================================================================================

_g("excerpt_not_source_slice", lambda x: x.excerpts, None, lambda x, e: x.text[e["start"]:e["end"]] != e["excerpt"])
_g("excerpt_offsets_invalid", lambda x: x.excerpts, None,
   lambda x, e: not (0 <= e["start"] < e["end"] <= len(x.text)) or e["end"] - e["start"] != len(e["excerpt"]))
_g("repeated_excerpt_first_match_guessed", lambda x: x.excerpts, lambda x, e: len(c.occurrences(window_text(x), e["excerpt"])) > 1,
   lambda x, e: e["occurrence_resolution"] == "UNIQUE_IN_TEXT")
_g("unique_excerpt_marked_repeated", lambda x: x.excerpts, lambda x, e: len(c.occurrences(window_text(x), e["excerpt"])) == 1,
   lambda x, e: e["occurrence_count"] != 1)
_g("excerpt_content_hash_mismatch", lambda x: x.excerpts, None, lambda x, e: e["submission_content_hash"] != c.digest(x.text))
_g("cross_run_excerpt_accepted", lambda x: x.excerpts, None, lambda x, e: e["experiment_run_id"] != x.run_id)
_g("cross_submission_excerpt_accepted", lambda x: x.excerpts, None,
   lambda x, e: e["submission_artifact_id"] != x.d["submission_artifact_id"])
_g("fabricated_excerpt_accepted", lambda x: F(x, "fabricated", []), None,
   lambda x, s: any(e["excerpt"] == s for e in x.excerpts))
_g("ambiguous_span_without_disambiguator_accepted", lambda x: F(x, "ambiguous", []), None,
   lambda x, s: any(e["excerpt"] == s for e in x.excerpts))
_g("excerpt_over_length_bound", lambda x: x.excerpts, None, lambda x, e: len(e["excerpt"]) > x.d["bounds"]["max_excerpt_chars"])
_g("excerpt_count_over_bound", lambda x: [len(x.excerpts)], lambda x, n: "max_excerpts" in x.case.bounds,
   lambda x, n: n > x.d["bounds"]["max_excerpts"])
_g("excerpt_outside_visible_window", lambda x: x.excerpts, lambda x, e: bool(F(x, "window")),
   lambda x, e: e["end"] > x.window_end)
_g("excerpt_straddles_window_edge", lambda x: x.excerpts, lambda x, e: bool(F(x, "window")),
   lambda x, e: e["start"] < x.window_end < e["end"])
_g("excerpt_beyond_window_any_case", lambda x: x.excerpts, None, lambda x, e: e["end"] > x.window_end)
_g("quarantine_span_outside_window", lambda x: x.d["quarantine"], None, lambda x, q: q["end"] > x.window_end)
_g("excerpt_overlaps_quarantined_result", lambda x: [(e, q) for e in x.excerpts for q in x.d["quarantine"]], None,
   lambda x, p: p[0]["start"] < p[1]["end"] and p[1]["start"] < p[0]["end"])
_g("escaped_text_leaked_into_canonical_excerpt", lambda x: x.excerpts, lambda x, e: bool(F(x, "markers")),
   lambda x, e: c.ZWSP in e["excerpt"] and c.ZWSP not in x.text)

# =========================================================================================================
# run binding
# =========================================================================================================

for _name, _get in [
    ("experiment", lambda x: x.d["experiments"]), ("requirement", lambda x: [r for _, r in _reqs(x)]),
    ("link", lambda x: x.d["links"]), ("measurement", lambda x: x.d["measurements"]),
    ("baseline", lambda x: x.d["baselines"]), ("condition", lambda x: x.d["conditions"]),
    ("coverage", lambda x: x.d["phase2j_coverage"]), ("track_posture", lambda x: x.d["track_postures"]),
    ("quarantine_span", lambda x: x.d["quarantine"]),
]:
    _g(f"cross_run_{_name}_accepted", _get, None, lambda x, r: r["experiment_run_id"] != x.run_id)

_g("submission_hash_unbound", lambda x: [x.d["submission_content_hash"]], lambda x, h: bool(x.text) and bool(h),
   lambda x, h: h != c.digest(x.text))
_g("claim_hash_unbound", lambda x: x.d["bound_claims"], None, lambda x, cl: cl["claim_text_hash"] != c.digest(x.claim))
_g("upstream_binding_missing", lambda x: [{b["phase"] for b in x.d["upstream_bindings"]}],
   lambda x, ph: bool(x.text) and x.d["status"] in ("COMPLETED", "INVALIDATED_UPSTREAM_MUTATED"),
   lambda x, ph: not {"STUDENT_SUBMISSION", "PROJECT_CLAIMS", "PHASE_2J_GAP", "PHASE_3A_METHODOLOGY"} <= ph)

# =========================================================================================================
# target identity and unknown ids
# =========================================================================================================

_g("link_unknown_target_accepted", lambda x: x.d["links"], None, lambda x, r: not _target_known(x, r))
_g("measurement_unknown_target_accepted", lambda x: x.d["measurements"], None, lambda x, r: not _target_known(x, r))
_g("baseline_unknown_target_accepted", lambda x: x.d["baselines"], None, lambda x, r: not _target_known(x, r))
_g("condition_unknown_requirement_accepted", lambda x: x.d["conditions"], None,
   lambda x, r: r["validation_requirement_id"] not in _by_req(x))
_g("condition_unbound_condition_id_accepted", lambda x: x.d["conditions"], None,
   lambda x, r: r["condition_id"] not in _by_req(x).get(r["validation_requirement_id"], {"condition_ids": []})["condition_ids"])
_g("coverage_unknown_requirement_accepted", lambda x: x.d["phase2j_coverage"], None,
   lambda x, r: r["validation_requirement_id"] not in _by_req(x))
_g("coverage_unknown_experiment_accepted", lambda x: x.d["phase2j_coverage"], None,
   lambda x, r: not set(r["attempting_experiment_ids"] + r["covering_experiment_ids"]) <= {e["experiment_id"] for e in x.d["experiments"]})
_g("track_posture_unknown_experiment_accepted", lambda x: x.d["track_postures"], None,
   lambda x, r: not set(r["experiment_ids"]) <= {e["experiment_id"] for e in x.d["experiments"]})
_g("dangling_excerpt_reference", lambda x: [i for e in x.d["experiments"] for i in own_excerpt_ids(e)]
   + [i for r in x.d["links"] for i in r["excerpt_ids"]]
   + [i for r in x.d["conditions"] for i in r["excerpt_ids"]]
   + [i for b in x.d["baselines"] for i in b["baseline_excerpt_ids"]], None,
   lambda x, i: i not in x.excerpt_by_id)
_g("link_excerpt_from_another_experiment", lambda x: [(e, i) for e in _assessed(x) for lk in x.links_of(e) for i in lk["excerpt_ids"]],
   None, lambda x, p: p[1] not in own_excerpt_ids(p[0]))
_g("measurement_excerpt_from_another_experiment", lambda x: [
    (e, i) for e in _assessed(x) for m in x.d["measurements"] if m["experiment_id"] == e["experiment_id"]
    for i in (m["method_excerpt_id"], m["metric_excerpt_id"], m["unit_excerpt_id"], m["success_criterion_excerpt_id"]) if i],
   None, lambda x, p: p[1] not in own_excerpt_ids(p[0]))
_g("condition_excerpt_from_another_experiment", lambda x: [
    (e, i) for e in _assessed(x) for cd in x.conds_of(e) for i in cd["excerpt_ids"]
    if any(lk["validation_requirement_id"] == cd["validation_requirement_id"] and lk["relation"] in cat.TESTING
           for lk in x.links_of(e))], None,
   lambda x, p: p[1] not in own_excerpt_ids(p[0]))
_g("baseline_excerpt_from_another_experiment", lambda x: [
    (e, i) for e in _assessed(x) for b in x.d["baselines"] if b["experiment_id"] == e["experiment_id"]
    for i in b["baseline_excerpt_ids"]], None, lambda x, p: p[1] not in own_excerpt_ids(p[0]))
_g("cross_run_target_id_accepted", lambda x: [F(x, "cross_run_target")] if F(x, "cross_run_target") else [], None,
   lambda x, u: u in x.output_text())
_g("foreign_target_accepted", lambda x: [F(x, "foreign_target")] if F(x, "foreign_target") else [], None,
   lambda x, u: any(len(x.links_of(e)) > len(_claims(x)) + len(x.targets) for e in _assessed(x)))

# =========================================================================================================
# identity
# =========================================================================================================

_g("duplicate_protocol_key", lambda x: [e["protocol_key"] for e in x.d["experiments"]], None,
   lambda x, k: [e["protocol_key"] for e in x.d["experiments"]].count(k) > 1)
_g("duplicate_experiment_id", lambda x: [e["experiment_id"] for e in x.d["experiments"]], None,
   lambda x, k: [e["experiment_id"] for e in x.d["experiments"]].count(k) > 1)
_g("shared_defining_excerpt", lambda x: [i for e in x.d["experiments"] for i in e["defining_excerpt_ids"]], None,
   lambda x, i: sum(i in e["defining_excerpt_ids"] for e in x.d["experiments"]) > 1)
_g("protocol_key_not_text_hash", lambda x: x.d["experiments"], None, lambda x, e: e["protocol_key"] != c.protocol_key_of(
    [x.excerpt_by_id[i]["excerpt"] for i in sorted(e["defining_excerpt_ids"], key=lambda i: x.excerpt_by_id[i]["start"])]))
_g("experiment_count_over_bound", lambda x: [len(x.d["experiments"])], lambda x, n: "max_experiments" in x.case.bounds,
   lambda x, n: n > x.d["bounds"]["max_experiments"])
_g("revision_of_self_or_unknown", lambda x: [e for e in x.d["experiments"] if e["revision_of"]], None,
   lambda x, e: e["revision_of"] == e["experiment_id"] or e["revision_of"] not in {y["experiment_id"] for y in x.d["experiments"]})
_g("experiment_without_defining_excerpt", lambda x: x.d["experiments"], None, lambda x, e: not e["defining_excerpt_ids"])
_g("experiment_id_depends_on_offsets", lambda x: [x.twins], lambda x, t: x.case.twin == "prefix",
   lambda x, t: not t.get("prefix_ids") or not t.get("prefix_keys"))

# =========================================================================================================
# the result quarantine
# =========================================================================================================

_g("result_text_persisted_canonically", lambda x: [r for r in F(x, "results", []) if len(r) >= 8], None,
   lambda x, r: r in x.output_text())
_g("declared_result_occurrence_not_quarantined",
   lambda x: [(r, p) for r in declared_results(x) for p in c.occurrences(window_text(x), r)],
   lambda x, i: not F(x, "incomplete_quarantine") and segmented(x),
   lambda x, i: not any(q["start"] <= i[1] and i[1] + len(i[0]) <= q["end"] for q in x.d["quarantine"]))
_g("first_match_only_quarantine", lambda x: [r for r in declared_results(x) if len(c.occurrences(window_text(x), r)) > 1],
   lambda x, r: not F(x, "incomplete_quarantine") and segmented(x),
   lambda x, r: sum(1 for q in x.d["quarantine"] if x.text[q["start"]:q["end"]] == r) < len(c.occurrences(window_text(x), r)))
_g("quarantine_span_hash_mismatch", lambda x: x.d["quarantine"], None,
   lambda x, q: c.digest(x.text[q["start"]:q["end"]]) != q["span_hash"])
_g("quarantined_value_consumed", lambda x: x.d["quarantine"], None, lambda x, q: q["consumed_by_phase3b"])
_g("quarantine_kind_outside_taxonomy", lambda x: x.d["quarantine"], None, lambda x, q: q["kind"] not in (
    "REPORTED_METRIC_VALUE", "STATISTICAL_OUTCOME", "RESULT_TABLE", "CONCLUSION", "SUCCESS_OR_FAILURE_STATEMENT",
    "CAUSAL_OR_GENERALIZATION_STATEMENT", "NEGATIVE_OUTCOME_STATEMENT"))
_g("incomplete_quarantine_accepted_as_complete", lambda x: [x.d] if F(x, "incomplete_quarantine") else [], None,
   lambda x, d: d["status"] != "INSUFFICIENT_INPUT" or d["project_posture"] is not None or d["experiments"] or d["links"]
   or d["phase2j_coverage"] or d["track_postures"])
_g("incomplete_quarantine_strong_posture", lambda x: [x.d] if F(x, "incomplete_quarantine") else [], None,
   lambda x, d: d["project_posture"] == "WELL_SPECIFIED" or any(e["posture"] == "WELL_SPECIFIED" for e in d["experiments"]))
_g("incomplete_quarantine_later_model_call", lambda x: [x] if F(x, "incomplete_quarantine") else [], None,
   lambda x, _: sum(x.calls_by_task.get(k, 0) for k in ("extract", "applicability", "link")) > 0)
_g("undeclared_quarantine_failure_dropped_silently",
   lambda x: [k for k in ("unlocatable_result", "empty_declared_result", "excessive_result") if F(x, k)], None,
   lambda x, k: not any(er["message"] == INCOMPLETE_MESSAGE and er["code"] == "PARTIAL_MODEL_OUTPUT" for er in x.d["errors"]))
_g("declared_result_in_later_prompt", lambda x: [(r, p) for r in declared_results(x) for p in x.later_prompts()], None,
   lambda x, i: i[0] in i[1])
_g("result_withhold_placeholder_missing", lambda x: [p for t, p in x.prompts if t == c.TASK_NAMES["extract"]],
   lambda x, p: bool(x.d["quarantine"]) and not F(x, "window") and bool(declared_results(x)),
   lambda x, p: c.PLACEHOLDER not in p)
_g("result_in_trusted_tail", lambda x: [(r, p) for r in declared_results(x) for p in x.all_prompts()], None,
   lambda x, i: i[0] in c.tail_of(i[1]))
_g("result_value_changes_adequacy", lambda x: [x.twins], lambda x, t: x.case.twin == "result",
   lambda x, t: not t.get("result"))
_g("result_value_changes_quarantine_shape", lambda x: [x.twins], lambda x, t: x.case.twin == "result",
   lambda x, t: not t.get("result_quarantine"))
_g("result_value_changes_identity", lambda x: [x.twins], lambda x, t: x.case.twin == "result",
   lambda x, t: not t.get("result_keys"))
_g("protocol_excerpt_accepted_over_result_overlap", lambda x: [e for e in x.excerpts], lambda x, e: bool(declared_results(x)),
   lambda x, e: any(r in e["excerpt"] for r in declared_results(x)))

# =========================================================================================================
# the prompt boundary
# =========================================================================================================

_g("prompt_end_marker_count_not_one", lambda x: x.all_prompts(), None, lambda x, p: p.count(c.MARKER_END) != 1)
_g("forged_marker_unescaped", lambda x: x.all_prompts(), lambda x, p: bool(F(x, "markers")),
   lambda x, p: p.count("===") != 2 * c.marker_lines(p))
_g("student_text_in_trusted_tail", lambda x: [(s, p) for s in student_strings(x) for p in x.all_prompts()], None,
   lambda x, i: i[0] in c.tail_of(i[1]))
_g("non_ascii_in_trusted_tail", lambda x: x.all_prompts(), lambda x, p: x.case.language in ("ar", "mixed"),
   lambda x, p: bool(c.ARABIC.search(c.tail_of(p))))
_g("raw_forged_marker_in_untrusted_block", lambda x: [(m, p) for m in F(x, "markers", []) if "===" in m
                                                       for p in x.all_prompts()], None,
   lambda x, i: i[0] in c.untrusted_part(i[1]))
_g("marker_text_followed_as_instruction", lambda x: [x] if F(x, "attack") else [], None,
   lambda x, _: x.d["execution_verified"] or any(e["execution_verified"] for e in x.d["experiments"]))
_g("hidden_prompt_persisted", lambda x: [1] if F(x, "leaks_prompt") else [], None,
   lambda x, _: __import__("src.evals.experiment_review.adapter", fromlist=["prompt_line"]).prompt_line() in x.output_text())
_g("model_text_persisted", lambda x: F(x, "model_texts", []), None, lambda x, t: t in x.output_text())
_g("student_claim_outside_untrusted_block", lambda x: [p for p in x.all_prompts() if x.claim in p], None,
   lambda x, p: p.find(x.claim) > p.find(c.MARKER_END))

# =========================================================================================================
# the execution boundary
# =========================================================================================================

_g("run_execution_verified", lambda x: [x.d], None, lambda x, d: d["execution_verified"])
_g("run_results_evaluated", lambda x: [x.d], None, lambda x, d: d["results_evaluated"])
_g("experiment_execution_verified", lambda x: x.d["experiments"], None, lambda x, e: e["execution_verified"])
_g("independent_reproduction_inferred", lambda x: x.d["experiments"], None, lambda x, e: e["independently_reproduced"])
_g("leakage_prevention_inferred", lambda x: x.d["experiments"], None, lambda x, e: e["leakage_prevented_in_practice"])
_g("excerpt_execution_verified", lambda x: x.excerpts, None, lambda x, e: e["execution_verified"])
_g("baseline_execution_verified", lambda x: x.d["baselines"], None, lambda x, b: b["execution_verified"])
_g("baseline_comparison_result_evaluated", lambda x: x.d["baselines"], None, lambda x, b: b["comparison_result_evaluated"])
_g("coverage_result_success_evaluated", lambda x: x.d["phase2j_coverage"], None, lambda x, cv: cv["result_success_evaluated"])
_g("execution_prose_turned_into_verification", lambda x: [x] if F(x, "exec_prose") else [], None,
   lambda x, _: x.d["execution_verified"] or any(e["execution_verified"] or e["independently_reproduced"]
                                                  or e["leakage_prevented_in_practice"] for e in x.d["experiments"]))

# =========================================================================================================
# linkage and measurement
# =========================================================================================================

_g("directly_tests_without_aligned_measurement", lambda x: [lk for lk in x.d["links"] if lk["relation"] == "DIRECTLY_TESTS"],
   None, lambda x, lk: not _aligned_for(x, lk))
_g("aligned_without_metric_excerpt", lambda x: [m for m in x.d["measurements"] if m["alignment"] == "ALIGNED_SAME_TARGET"], None,
   lambda x, m: m["metric_excerpt_id"] is None)
_g("aligned_without_method_excerpt", lambda x: [m for m in x.d["measurements"] if m["alignment"] == "ALIGNED_SAME_TARGET"], None,
   lambda x, m: m["method_excerpt_id"] is None)
_g("same_as_phase2j_without_alignment", lambda x: [m for m in x.d["measurements"] if m["phase2j_metric_match"] == "SAME_AS_PHASE_2J"],
   None, lambda x, m: m["alignment"] != "ALIGNED_SAME_TARGET")
_g("metric_anchor_on_claim_target", lambda x: [m for m in x.d["measurements"] if m["validation_requirement_id"] is None], None,
   lambda x, m: m["phase2j_metric_match"] != "NO_PHASE_2J_ANCHOR")
_g("metric_wrong_target_counted_as_covered", lambda x: [
    (cv, m) for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT" for m in x.d["measurements"]
    if m["validation_requirement_id"] == cv["validation_requirement_id"] and m["experiment_id"] in cv["covering_experiment_ids"]],
   None, lambda x, p: p[1]["alignment"] == "METRIC_TARGET_MISMATCH" or p[1]["phase2j_metric_match"] != "SAME_AS_PHASE_2J")
_g("testing_link_without_cited_protocol", lambda x: [lk for lk in x.d["links"] if lk["relation"] in cat.TESTING], None,
   lambda x, lk: not lk["excerpt_ids"])
_g("nontesting_link_cites_protocol", lambda x: [lk for lk in x.d["links"] if lk["relation"] not in cat.TESTING], None,
   lambda x, lk: bool(lk["excerpt_ids"]))
_g("target_left_without_link", lambda x: [(e, t) for e in _assessed(x) for t in
                                          [(cl, None, None) for cl in _claims(x)] + [(t_["claim_id"], t_["gap_hypothesis_id"], t_["validation_requirement_id"]) for t_ in x.targets]],
   lambda x, i: _stage_ran(x) or x.d["status"] == "COMPLETED",
   lambda x, i: not any(_target_key(lk) == i[1] for lk in x.links_of(i[0])))
_g("omitted_target_read_as_does_not_test", lambda x: [lk for lk in x.d["links"]] if F(x, "omitted_target") else [], None,
   lambda x, lk: lk["relation"] == "DOES_NOT_TEST")
_g("metric_mismatch_without_issue", lambda x: [(e, m) for e in x.d["experiments"] for m in x.d["measurements"]
                                                if m["experiment_id"] == e["experiment_id"] and m["alignment"] == "METRIC_TARGET_MISMATCH"],
   None, lambda x, p: "METRIC_TARGET_MISMATCH" not in p[0]["issues"])
_g("post_hoc_criterion_without_issue", lambda x: [(e, m) for e in x.d["experiments"] for m in x.d["measurements"]
                                                   if m["experiment_id"] == e["experiment_id"] and m["success_criterion_timing"] == "POST_HOC_AS_DESCRIBED"],
   None, lambda x, p: "SUCCESS_CRITERION_POST_HOC" not in p[0]["issues"] or p[0]["posture"] not in ("MAJOR_GAPS", "INSUFFICIENT_EVIDENCE"))
_g("criterion_timing_without_criterion", lambda x: x.d["measurements"], None,
   lambda x, m: m["success_criterion_excerpt_id"] is None and m["success_criterion_timing"] != "TIMING_NOT_DOCUMENTED")
_g("metric_borrowed_from_another_experiment", lambda x: [(e, m) for e in _assessed(x) for m in x.d["measurements"]
                                                          if m["experiment_id"] == e["experiment_id"] and m["metric_excerpt_id"]],
   lambda x, p: bool(F(x, "metric_from_other_experiment")), lambda x, p: p[1]["metric_excerpt_id"] not in own_excerpt_ids(p[0]))
_g("condition_covered_without_excerpt", lambda x: [cd for cd in x.d["conditions"] if cd["status"] != "NOT_ADDRESSED_IN_BOUND_INPUT"], None,
   lambda x, cd: not cd["excerpt_ids"])

# =========================================================================================================
# Phase 2J continuity
# =========================================================================================================

_g("coverage_status_unsupported", lambda x: x.d["phase2j_coverage"], None,
   lambda x, cv: c.derive_coverage(x.d, _by_req(x)[cv["validation_requirement_id"]])[0] != cv["status"])
_g("covered_without_directly_tests_link", lambda x: [(cv, eid) for cv in x.d["phase2j_coverage"]
                                                     if cv["status"] == "COVERED_BY_EXPERIMENT" for eid in cv["covering_experiment_ids"]], None,
   lambda x, p: not any(lk["experiment_id"] == p[1] and lk["validation_requirement_id"] == p[0]["validation_requirement_id"]
                        and lk["relation"] == "DIRECTLY_TESTS" for lk in x.d["links"]))
_g("covered_baseline_required_without_relevant_baseline",
   lambda x: [(cv, eid) for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT" for eid in cv["covering_experiment_ids"]
              if _by_req(x)[cv["validation_requirement_id"]]["baseline_anchor_hash"] is not None], None,
   lambda x, p: not any(b["experiment_id"] == p[1] and b["validation_requirement_id"] == p[0]["validation_requirement_id"]
                        and b["relevance"] == "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT" for b in x.d["baselines"]))
_g("covered_with_uncovered_condition",
   lambda x: [(cv, eid) for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT" for eid in cv["covering_experiment_ids"]
              if _by_req(x)[cv["validation_requirement_id"]]["condition_ids"]], None,
   lambda x, p: not set(_by_req(x)[p[0]["validation_requirement_id"]]["condition_ids"]) <= {
       cd["condition_id"] for cd in x.d["conditions"] if cd["experiment_id"] == p[1] and cd["status"] == "ADDRESSED_IN_PROTOCOL"})
_g("covered_by_inadequate_experiment",
   lambda x: [(cv, eid) for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT" for eid in cv["covering_experiment_ids"]], None,
   lambda x, p: next(e for e in x.d["experiments"] if e["experiment_id"] == p[1])["posture"] not in ("WELL_SPECIFIED", "PARTIALLY_SPECIFIED"))
_g("covering_experiment_does_not_attempt", lambda x: x.d["phase2j_coverage"], None,
   lambda x, cv: not set(cv["covering_experiment_ids"]) <= set(cv["attempting_experiment_ids"]))
_g("cross_experiment_mosaic_coverage", lambda x: [cv for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT"], None,
   lambda x, cv: not any(c.single_experiment_covers(x.d, _by_req(x)[cv["validation_requirement_id"]], e)[0]
                         for e in x.d["experiments"] if e["experiment_id"] in cv["covering_experiment_ids"]))
_g("mosaic_scenario_reads_covered", lambda x: x.d["phase2j_coverage"], lambda x, cv: bool(F(x, "mosaic")),
   lambda x, cv: cv["status"] == "COVERED_BY_EXPERIMENT")
_g("requirement_invented_for_hypothesis_without_one", lambda x: [x.d] if F(x, "no_requirement") else [], None,
   lambda x, d: bool(d["phase2j_coverage"]) or bool(d["bound_validation_targets"]))
_g("coverage_record_count_mismatch", lambda x: [x.d], lambda x, d: d["status"] in ("COMPLETED",),
   lambda x, d: len(d["phase2j_coverage"]) != len(d["bound_validation_targets"]))
_g("noncovered_status_without_reason", lambda x: [cv for cv in x.d["phase2j_coverage"] if cv["status"] != "COVERED_BY_EXPERIMENT"], None,
   lambda x, cv: not cv["reasons"])
_g("covered_status_with_reason", lambda x: [cv for cv in x.d["phase2j_coverage"] if cv["status"] == "COVERED_BY_EXPERIMENT"], None,
   lambda x, cv: bool(cv["reasons"]))
_g("unresolved_link_reported_as_not_covered", lambda x: [cv for cv in x.d["phase2j_coverage"]
                                                         if not any(lk["relation"] in cat.TESTING and lk["validation_requirement_id"] == cv["validation_requirement_id"] for lk in x.d["links"])
                                                         and any(lk["relation"] == "UNRESOLVED" and lk["validation_requirement_id"] == cv["validation_requirement_id"] for lk in x.d["links"])],
   None, lambda x, cv: cv["status"] != "UNRESOLVED")
_g("attempting_includes_non_testing_experiment", lambda x: x.d["phase2j_coverage"], None,
   lambda x, cv: any(not any(lk["experiment_id"] == eid and lk["validation_requirement_id"] == cv["validation_requirement_id"]
                             and lk["relation"] in cat.TESTING for lk in x.d["links"]) for eid in cv["attempting_experiment_ids"]))
_g("coverage_better_than_single_experiment_evidence", lambda x: x.d["phase2j_coverage"], None,
   lambda x, cv: cat.WORST_ORDER.index(cat.COVERAGE_POSTURE[cv["status"]]) > cat.WORST_ORDER.index(
       cat.COVERAGE_POSTURE[c.derive_coverage(x.d, _by_req(x)[cv["validation_requirement_id"]])[0]]))

# =========================================================================================================
# baseline and comparator
# =========================================================================================================

_g("baseline_name_implies_relevance", lambda x: x.d["baselines"], lambda x, b: bool(F(x, "baseline_name_only")),
   lambda x, b: b["relevance"] == "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT")
_g("global_fairness_conclusion_field", lambda x: [k for k, _ in c.walk(x.d)], None,
   lambda x, k: k.lower() in ("fair", "is_fair", "comparison_fair", "fairness", "comparison_fairness") or "fair_comparison" in k.lower())
_g("documented_comparability_without_excerpt", lambda x: [(b, p) for b in x.d["baselines"] for p in b["comparability"]
                                                           if p["status"] in ("DOCUMENTED_SAME", "DOCUMENTED_DIFFERENT")], None,
   lambda x, i: not i[1]["excerpt_ids"])
_g("deterministic_comparability_for_non_metric_property", lambda x: [p for b in x.d["baselines"] for p in b["comparability"]
                                                                       if p["basis"] == "DETERMINISTIC_SHARED_METRIC_BINDING"], None,
   lambda x, p: p["property"] != "SAME_EVALUATION_METRIC")
_g("deterministic_metric_property_without_aligned_binding", lambda x: [(b, p) for b in x.d["baselines"] for p in b["comparability"]
                                                                        if p["basis"] == "DETERMINISTIC_SHARED_METRIC_BINDING"], None,
   lambda x, i: not any(m["experiment_id"] == i[0]["experiment_id"] and m["alignment"] == "ALIGNED_SAME_TARGET"
                        and m["validation_requirement_id"] == i[0]["validation_requirement_id"] for m in x.d["measurements"]))
_g("baseline_without_named_excerpt", lambda x: x.d["baselines"], None, lambda x, b: not b["baseline_excerpt_ids"])
_g("comparability_difference_without_issue", lambda x: [(e, b) for e in x.d["experiments"] for b in x.d["baselines"]
                                                         if b["experiment_id"] == e["experiment_id"] and b["baseline_excerpt_ids"]
                                                         and any(p["status"] == "DOCUMENTED_DIFFERENT" for p in b["comparability"])], None,
   lambda x, p: "BASELINE_COMPARABILITY_GAP" not in p[0]["issues"])
_g("baseline_required_but_undocumented_without_issue", lambda x: [(e, r) for e, r in _reqs(x) if r["kind"] in ("BASELINE", "BASELINE_CONFIGURATION")
                                                                   and r["applicability"] == "REQUIRED" and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT"], None,
   lambda x, p: "BASELINE_MISSING_WHEN_REQUIRED" not in p[0]["issues"])
_g("improvement_claim_without_baseline_reads_well", lambda x: [e for e in x.d["experiments"]] if F(x, "baseline_required_missing") else [], None,
   lambda x, e: e["posture"] in ("WELL_SPECIFIED", "PARTIALLY_SPECIFIED"))
_g("comparability_not_applicable_asserted", lambda x: [p for b in x.d["baselines"] for p in b["comparability"]], None,
   lambda x, p: p["status"] == "NOT_APPLICABLE")
_g("irrelevant_baseline_without_issue", lambda x: [(e, b) for e in x.d["experiments"] for b in x.d["baselines"]
                                                    if b["experiment_id"] == e["experiment_id"] and b["relevance"] == "NOT_RELEVANT_TO_TARGET"], None,
   lambda x, p: "BASELINE_NOT_RELEVANT" not in p[0]["issues"])
_g("baseline_anchor_on_target_without_baseline", lambda x: [b for b in x.d["baselines"]], None,
   lambda x, b: b["phase2j_baseline_match"] != "NO_PHASE_2J_ANCHOR" and (
       b["validation_requirement_id"] is None or _by_req(x).get(b["validation_requirement_id"], {"baseline_anchor_hash": None})["baseline_anchor_hash"] is None))

# =========================================================================================================
# sample, repetition and statistics
# =========================================================================================================

_g("bare_number_documents_sample_rationale", lambda x: [r for _, r in _reqs(x) if r["kind"] == "SAMPLE_SIZE_RATIONALE" and r["excerpt_ids"]], None,
   lambda x, r: all(c.is_bare_quantity(x.excerpt_by_id[i]["excerpt"]) for i in r["excerpt_ids"]))
_g("bare_number_rated_adequate", lambda x: [r for _, r in _reqs(x) if r["excerpt_ids"] and r["kind"] in ("SAMPLE_SIZE", "SAMPLE_DEFINITION")], None,
   lambda x, r: all(c.is_bare_quantity(x.excerpt_by_id[i]["excerpt"]) for i in r["excerpt_ids"]) and r["adequacy"] == GOOD)
_g("bare_number_scenario_reads_adequate", lambda x: [e for e in x.d["experiments"]] if F(x, "bare_n") else [], None,
   lambda x, e: e["posture"] == "WELL_SPECIFIED")
_g("repetition_count_implies_independence", lambda x: [(e, r) for e, r in _reqs(x) if r["kind"] == "REPETITION_INDEPENDENCE" and r["applicability"] == "REQUIRED"]
   if F(x, "rep_count_only") else [], None, lambda x, p: p[1]["documentation"] != "NOT_DOCUMENTED_IN_BOUND_INPUT")
_g("statistics_required_by_default", lambda x: [r for _, r in _reqs(x) if r["kind"] in STAT_KINDS], None,
   lambda x, r: r["applicability"] == "REQUIRED" and r["basis"] in ("CATALOG_DEFAULT", "CATALOG_TYPE_OVERRIDE"))
_g("statistics_required_without_trigger_or_judgment", lambda x: [r for _, r in _reqs(x) if r["kind"] in STAT_KINDS and r["applicability"] == "REQUIRED"], None,
   lambda x, r: not r["triggers"] or not r["judgment_excerpt_ids"])
_g("statistics_issue_without_required_statistics",
   lambda x: [e for e in x.d["experiments"] if "STATISTICS_MISSING_WHEN_REQUIRED" in e["issues"]], None,
   lambda x, e: not any(r["kind"] in STAT_KINDS and r["applicability"] == "REQUIRED" and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT"
                        for r in e["requirements"]))
_g("p_value_presence_requires_statistics", lambda x: [e for e in x.d["experiments"]] if F(x, "p_value_present") and F(x, "no_inference") else [], None,
   lambda x, e: (x.req(e, "STATISTICAL_TEST") or {"applicability": "NOT_APPLICABLE"})["applicability"] == "REQUIRED")
_g("missing_p_value_fails_case", lambda x: [x.d] if F(x, "no_p_value") else [], None,
   lambda x, d: d["status"] != "COMPLETED" or any("STATISTICS_MISSING_WHEN_REQUIRED" in e["issues"] for e in d["experiments"]))
_g("p_value_improves_posture", lambda x: [e for e in x.d["experiments"]] if F(x, "p_value_present") else [], None,
   lambda x, e: e["posture"] == "WELL_SPECIFIED" and bool(e["issues"]))
_g("conditional_resolved_without_judgment", lambda x: [r for _, r in _reqs(x) if r["basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT"], None,
   lambda x, r: not r["judgment_excerpt_ids"])
_g("conditional_resolved_by_omission", lambda x: [r for e, r in _reqs(x) if cat.cell(r["kind"], e["experiment_type"]) == "C"
                                                    and not set(cat.TRIGGERS[r["kind"]]) & set(cat.PHASE_2J_TRIGGERS)],
   lambda x, r: bool(x.case.model_script.get("applicability_omit")), lambda x, r: r["applicability"] != "CONDITIONAL")
_g("catalog_required_row_lowered", lambda x: [(e, r) for e, r in _reqs(x) if cat.cell(r["kind"], e["experiment_type"]) == "R"], None,
   lambda x, p: p[1]["applicability"] != "REQUIRED")
_g("catalog_not_applicable_row_raised", lambda x: [(e, r) for e, r in _reqs(x) if cat.cell(r["kind"], e["experiment_type"]) == "-"], None,
   lambda x, p: p[1]["applicability"] != "NOT_APPLICABLE")
_g("requirement_inventory_incomplete", lambda x: _assessed(x), None, lambda x, e: [r["kind"] for r in e["requirements"]] != list(cat.KINDS))
_g("invented_requirement_persisted", lambda x: [r for _, r in _reqs(x)], None, lambda x, r: r["kind"] not in cat.KINDS)
_g("documentation_excerpt_overlaps_other_kind_result", lambda x: [(r, q) for _, r in _reqs(x) for q in x.d["quarantine"] if r["excerpt_ids"]], None,
   lambda x, p: any(x.excerpt_by_id[i]["start"] < p[1]["end"] and p[1]["start"] < x.excerpt_by_id[i]["end"] for i in p[0]["excerpt_ids"]))
_g("adequacy_above_documentation", lambda x: [r for _, r in _reqs(x)], None,
   lambda x, r: r["adequacy"] == GOOD and r["documentation"] != "EXPLICITLY_DOCUMENTED")
_g("documented_requirement_without_excerpt", lambda x: [r for _, r in _reqs(x) if r["documentation"] in ("EXPLICITLY_DOCUMENTED", "PARTIALLY_DOCUMENTED", "CONFLICTING_DOCUMENTATION")],
   None, lambda x, r: not r["excerpt_ids"])
_g("optional_requirement_makes_issue", lambda x: [(e, r) for e, r in _reqs(x) if r["applicability"] == "OPTIONAL" and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT"],
   None, lambda x, p: cat.missing_issue(p[1]["kind"]) in p[0]["issues"] and not any(
       q["applicability"] == "REQUIRED" and q["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT" and cat.missing_issue(q["kind"]) == cat.missing_issue(p[1]["kind"])
       for q in p[0]["requirements"]))

# =========================================================================================================
# postures, ownership, HYBRID
# =========================================================================================================


def _derived_exp(x: Ctx, e: dict[str, Any]) -> str:
    ms, bs, links = c.exp_records(x.d, e)
    return c.derive_exp_posture(e, c.derive_issues(e, ms, bs, links), ms, links)


_g("experiment_posture_stronger_than_derived", lambda x: _assessed(x), None,
   lambda x, e: RANK[e["posture"]] > RANK[_derived_exp(x, e)])
_g("experiment_posture_weaker_than_derived", lambda x: _assessed(x), None, lambda x, e: RANK[e["posture"]] < RANK[_derived_exp(x, e)])
_g("track_posture_stronger_than_derived", lambda x: x.d["track_postures"], None,
   lambda x, tp: RANK[tp["posture"]] > RANK[c.derive_track_posture(x.d, tp["track"])])
_g("project_posture_stronger_than_derived", lambda x: [x.d] if x.completed else [], None,
   lambda x, d: RANK[d["project_posture"]] > RANK[c.derive_project_posture(d)])
_g("project_posture_weaker_than_derived", lambda x: [x.d] if x.completed else [], None,
   lambda x, d: RANK[d["project_posture"]] < RANK[c.derive_project_posture(d)])
_g("well_specified_with_issue", lambda x: [e for e in x.d["experiments"] if e["posture"] == "WELL_SPECIFIED"], None, lambda x, e: bool(e["issues"]))
_g("well_specified_with_conditional_row", lambda x: [e for e in x.d["experiments"] if e["posture"] == "WELL_SPECIFIED"], None,
   lambda x, e: any(r["applicability"] == "CONDITIONAL" for r in e["requirements"]))
_g("well_specified_with_inadequate_required_row", lambda x: [e for e in x.d["experiments"] if e["posture"] == "WELL_SPECIFIED"], None,
   lambda x, e: any(r["applicability"] == "REQUIRED" and r["adequacy"] != GOOD for r in e["requirements"]))
_g("well_specified_without_aligned_directly_tests", lambda x: [e for e in x.d["experiments"] if e["posture"] == "WELL_SPECIFIED"], None,
   lambda x, e: not any(lk["relation"] == "DIRECTLY_TESTS" and _aligned_for(x, lk) for lk in x.links_of(e)))
_g("project_well_specified_on_incomplete_run", lambda x: [x.d] if x.d["project_posture"] == "WELL_SPECIFIED" else [], None,
   lambda x, d: d["status"] != "COMPLETED")
_g("project_well_specified_with_unowned_experiment", lambda x: [x.d] if x.d["project_posture"] == "WELL_SPECIFIED" else [], None,
   lambda x, d: any(e["track"] is None for e in d["experiments"]))
_g("project_well_specified_with_untested_claim", lambda x: [x.d] if x.d["project_posture"] == "WELL_SPECIFIED" else [], None,
   lambda x, d: bool(d["untested_claim_ids"]))
_g("project_well_specified_with_uncovered_requirement", lambda x: [x.d] if x.d["project_posture"] == "WELL_SPECIFIED" else [], None,
   lambda x, d: any(cv["status"] != "COVERED_BY_EXPERIMENT" for cv in d["phase2j_coverage"]))
_g("project_well_specified_without_experiment", lambda x: [x.d] if x.d["project_posture"] == "WELL_SPECIFIED" else [], None,
   lambda x, d: not d["experiments"])
_g("hybrid_track_posture_averaged", lambda x: [x.d] if x.project_type == "HYBRID" and x.completed and x.d["track_postures"] else [], None,
   lambda x, d: RANK[d["project_posture"]] > min(RANK[tp["posture"]] for tp in d["track_postures"]))
_g("hybrid_strong_track_hides_weak_track", lambda x: [x.d] if x.project_type == "HYBRID" and x.completed and len(x.d["track_postures"]) > 1 else [], None,
   lambda x, d: d["project_posture"] == "WELL_SPECIFIED" and any(tp["posture"] != "WELL_SPECIFIED" for tp in d["track_postures"]))
_g("unowned_experiment_counted_in_track", lambda x: [e for e in x.d["experiments"] if e["track"] is None], None,
   lambda x, e: any(e["experiment_id"] in tp["experiment_ids"] for tp in x.d["track_postures"]))
_g("experiment_counted_in_two_tracks", lambda x: [e for e in x.d["experiments"]], None,
   lambda x, e: sum(e["experiment_id"] in tp["experiment_ids"] for tp in x.d["track_postures"]) > 1)
_g("track_member_has_other_track", lambda x: [(tp, e) for tp in x.d["track_postures"] for e in x.d["experiments"] if e["experiment_id"] in tp["experiment_ids"]],
   None, lambda x, p: p[1]["track"] != p[0]["track"])
_g("owned_experiment_missing_from_its_track", lambda x: [e for e in x.d["experiments"] if e["track"] is not None], lambda x, e: x.completed,
   lambda x, e: not any(e["experiment_id"] in tp["experiment_ids"] and tp["track"] == e["track"] for tp in x.d["track_postures"]))
_g("single_track_basis_on_hybrid_project", lambda x: [e for e in x.d["experiments"]], lambda x, e: x.project_type == "HYBRID",
   lambda x, e: e["ownership_basis"] == "SINGLE_TRACK_PROJECT")
_g("single_track_project_not_single_track_owned", lambda x: [e for e in x.d["experiments"]], lambda x, e: x.project_type in ("SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT"),
   lambda x, e: e["ownership_basis"] != "SINGLE_TRACK_PROJECT" or e["track"] != cat.PROJECT_TRACKS[x.project_type][0])
_g("facet_ownership_without_matching_facet", lambda x: [e for e in x.d["experiments"] if e["ownership_basis"] == "PHASE_2J_LIMITATION_FACET"], None,
   lambda x, e: not any(cat.FACET_TRACK[f] == e["track"] for t in x.targets for f in t["limitation_facets"]))
_g("model_ownership_without_excerpts", lambda x: [e for e in x.d["experiments"] if e["ownership_basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT"], None,
   lambda x, e: not e["ownership_excerpt_ids"] or e["track"] is None)
_g("unresolved_ownership_with_track", lambda x: [e for e in x.d["experiments"] if e["ownership_basis"] == "UNRESOLVED"], None,
   lambda x, e: e["track"] is not None)
_g("track_posture_missing_for_inherited_track", lambda x: [x.d] if x.completed else [], None,
   lambda x, d: sorted(tp["track"] for tp in d["track_postures"]) != sorted(d["tracks"]))
_g("tracks_not_inherited_from_project_type", lambda x: [x.d["tracks"]] if x.d["tracks"] or x.d["status"] != "INSUFFICIENT_INPUT" else [], None,
   lambda x, tr: sorted(tr) != sorted(cat.PROJECT_TRACKS[x.project_type]))
_g("unknown_type_reads_well", lambda x: [e for e in x.d["experiments"] if e["experiment_type"] == "UNKNOWN"], None,
   lambda x, e: e["posture"] == "WELL_SPECIFIED")
_g("unknown_type_universal_row_lowered", lambda x: [r for e, r in _reqs(x) if e["experiment_type"] == "UNKNOWN" and r["kind"] in cat.UNIVERSAL], None,
   lambda x, r: r["applicability"] != "REQUIRED")
_g("unknown_type_conditional_row_resolved", lambda x: [r for e, r in _reqs(x) if e["experiment_type"] == "UNKNOWN" and r["kind"] not in cat.UNIVERSAL], None,
   lambda x, r: r["applicability"] != "CONDITIONAL")
_g("untested_claim_ids_wrong", lambda x: [x.d] if x.completed else [], None,
   lambda x, d: sorted(d["untested_claim_ids"]) != sorted(_claims(x) - {lk["claim_id"] for lk in d["links"] if lk["relation"] in cat.TESTING}))
_g("does_not_test_experiment_covers_target", lambda x: [e for e in x.d["experiments"] if x.links_of(e) and all(lk["relation"] == "DOES_NOT_TEST" for lk in x.links_of(e))], None,
   lambda x, e: any(e["experiment_id"] in cv["covering_experiment_ids"] for cv in x.d["phase2j_coverage"]) or "EXPERIMENT_DOES_NOT_TEST_TARGET" not in e["issues"])
_g("conflicting_documentation_without_issue", lambda x: [(e, r) for e, r in _reqs(x) if r["documentation"] == "CONFLICTING_DOCUMENTATION"], None,
   lambda x, p: "CONFLICTING_PROTOCOL_DESCRIPTION" not in p[0]["issues"])
_g("required_missing_requirement_without_issue", lambda x: [(e, r) for e, r in _reqs(x) if r["applicability"] == "REQUIRED" and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT"], None,
   lambda x, p: cat.missing_issue(p[1]["kind"]) not in p[0]["issues"])
_g("high_severity_issue_not_major", lambda x: [e for e in x.d["experiments"] if any(cat.is_major(i) for i in e["issues"])], None,
   lambda x, e: e["posture"] not in ("MAJOR_GAPS", "INSUFFICIENT_EVIDENCE"))

# =========================================================================================================
# provider failures and the model-call bound
# =========================================================================================================

_g("provider_failure_yields_strong_posture", lambda x: [x.d] if F(x, "provider_failure") else [], None,
   lambda x, d: d["project_posture"] == "WELL_SPECIFIED" or any(e["posture"] == "WELL_SPECIFIED" for e in d["experiments"]))
_g("provider_failure_without_stage_code", lambda x: [F(x, "provider_failure")] if F(x, "provider_failure") else [], None,
   lambda x, pf: pf.split(":")[0] not in sorted({c.STAGE_SHORT[er["node"]] for er in x.d["errors"] if er["code"] == pf.split(":")[1]}))
_g("failed_extraction_requirement_not_insufficient", lambda x: [e for e in x.d["experiments"]],
   lambda x, e: F(x, "provider_failure", "").startswith("EXTRACT:"),
   lambda x, e: e["experiment_type"] != "UNKNOWN" or any(r["applicability"] != "NOT_APPLICABLE" and r["documentation"] != "INSUFFICIENT_SOURCE_COVERAGE" for r in e["requirements"]))
_g("failed_linkage_target_not_unresolved", lambda x: x.d["links"], lambda x, lk: F(x, "provider_failure", "").startswith("LINK:"),
   lambda x, lk: lk["relation"] != "UNRESOLVED")
_g("failed_applicability_row_resolved", lambda x: [r for _, r in _reqs(x)], lambda x, r: F(x, "provider_failure", "").startswith("APPLICABILITY:"),
   lambda x, r: r["basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT")
_g("failed_segmentation_kept_experiments", lambda x: [x.d], lambda x, d: F(x, "provider_failure", "").startswith("SEGMENT:"),
   lambda x, d: bool(d["experiments"]) or bool(d["quarantine"]))
_g("calls_exceed_bound", lambda x: [x.d], None,
   lambda x, d: d["model_calls_performed"] > d["bounds"]["max_model_calls"])
_g("provider_requests_not_counted", lambda x: [x.d], lambda x, d: x.model is not None or x.case.no_model,
   lambda x, d: d["model_calls_performed"] != x.provider_requests)
_g("call_made_without_provider", lambda x: [x.d], lambda x, d: x.case.no_model, lambda x, d: x.provider_requests != 0 or d["model_calls_performed"] != 0)
_g("call_made_after_budget_exhausted", lambda x: [x.d], lambda x, d: any(er["code"] == "MODEL_CALL_BOUND_REACHED" for er in d["errors"]),
   lambda x, d: x.provider_requests > d["bounds"]["max_model_calls"])
_g("refusal_retried", lambda x: [p for p in ("segment", "extract", "applicability", "link") if x.case.model_script.get(p) == "refusal"], None,
   lambda x, p: x.calls_by_task.get(p, 0) != 1)
_g("error_emitted_by_forbidden_stage", lambda x: x.d["errors"], None, lambda x, er: c.STAGE_SHORT[er["node"]] not in c.EMITTERS[er["code"]])
_g("rejection_digest_carries_text", lambda x: x.d["rejected_proposals"], None,
   lambda x, rp: set(rp) != {"code", "stage", "response_digest"} or len(rp["response_digest"]) != 64)
_g("retry_limit_exceeded", lambda x: [x.d], lambda x, d: "model_retry_limit" in x.case.bounds,
   lambda x, d: x.calls_by_task.get("segment", 0) > 1 + int(x.case.bounds["model_retry_limit"]))
_g("budget_too_small_run_completes_strong", lambda x: [x.d], lambda x, d: any(er["code"] == "MODEL_CALL_BOUND_REACHED" for er in d["errors"]),
   lambda x, d: d["project_posture"] == "WELL_SPECIFIED")

# =========================================================================================================
# search, network, legacy inputs
# =========================================================================================================

_g("external_search_attempted", lambda x: [x.d], None, lambda x, d: d["external_search_calls"] != 0)
_g("network_attempted_in_run", lambda x: [x.d], None, lambda x, d: d["network_attempts"] != 0)
_g("socket_opened_during_run", lambda x: [x.network_attempts], None, lambda x, n: n != 0)
_g("legacy_marker_in_model_prompt", lambda x: x.all_prompts(), lambda x, p: x.case.legacy_leak,
   lambda x, p: __import__("src.evals.experiment_review.adapter", fromlist=["LEGACY_MARKER"]).LEGACY_MARKER in p)
_g("legacy_marker_in_output", lambda x: [x.output_text()], lambda x, o: x.case.legacy_leak,
   lambda x, o: __import__("src.evals.experiment_review.adapter", fromlist=["LEGACY_MARKER"]).LEGACY_MARKER in o)
_g("legacy_state_changes_review", lambda x: [x.legacy_twin], lambda x, t: x.case.legacy_leak and not x.case.mutate,
   lambda x, t: not t.get("same") or not t.get("prompts_same"))

# =========================================================================================================
# determinism, replay, canonical ordering
# =========================================================================================================

_g("replay_made_model_call", lambda x: [x.replay], lambda x, r: x.case.rerun, lambda x, r: r.get("extra_calls") != 0)
_g("replay_changed_review", lambda x: [x.replay], lambda x, r: x.case.rerun, lambda x, r: not r.get("same"))
_g("resume_changed_review", lambda x: [x.replay], lambda x, r: bool(x.case.interrupt_before), lambda x, r: not r.get("resume_same"))
_g("model_order_changed_review", lambda x: [x.twins], lambda x, t: x.case.twin == "order", lambda x, t: not t.get("order"))
_g("model_order_changed_ids", lambda x: [x.twins], lambda x, t: x.case.twin == "order", lambda x, t: not t.get("ids"))
_g("prefix_text_changed_adequacy", lambda x: [x.twins], lambda x, t: x.case.twin == "prefix", lambda x, t: not t.get("prefix"))
_g("experiments_not_canonical", lambda x: [x.d["experiments"]], None,
   lambda x, rows: [r["experiment_id"] for r in rows] != sorted(r["experiment_id"] for r in rows))
_g("excerpts_not_canonical", lambda x: [x.excerpts], None,
   lambda x, rows: [(r["start"], r["end"], r["excerpt_id"]) for r in rows] != sorted((r["start"], r["end"], r["excerpt_id"]) for r in rows))
_g("quarantine_not_canonical", lambda x: [x.d["quarantine"]], None,
   lambda x, rows: [(r["start"], r["end"], r["span_id"]) for r in rows] != sorted((r["start"], r["end"], r["span_id"]) for r in rows))
_g("links_not_canonical", lambda x: [x.d["links"]], None, lambda x, rows: [r["link_id"] for r in rows] != sorted(r["link_id"] for r in rows))
_g("measurements_not_canonical", lambda x: [x.d["measurements"]], None,
   lambda x, rows: [r["binding_id"] for r in rows] != sorted(r["binding_id"] for r in rows))
_g("baselines_not_canonical", lambda x: [x.d["baselines"]], None, lambda x, rows: [r["record_id"] for r in rows] != sorted(r["record_id"] for r in rows))
_g("coverage_not_canonical", lambda x: [x.d["phase2j_coverage"]], None,
   lambda x, rows: [r["validation_requirement_id"] for r in rows] != sorted(r["validation_requirement_id"] for r in rows))
_g("requirements_not_in_catalog_order", lambda x: _assessed(x), None,
   lambda x, e: [r["kind"] for r in e["requirements"]] != [k for k in cat.KINDS])

# =========================================================================================================
# upstream, terminal status, forbidden fields
# =========================================================================================================

_g("mutated_upstream_keeps_records", lambda x: [x.mutated] if x.case.mutate else [], None, lambda x, m: m.get("kept") != 0)
_g("mutated_upstream_keeps_posture", lambda x: [x.mutated] if x.case.mutate else [], None, lambda x, m: m.get("posture") is not None)
_g("upstream_mutation_not_detected", lambda x: [x.mutated] if x.case.mutate else [], None,
   lambda x, m: m.get("status") != "INVALIDATED_UPSTREAM_MUTATED")
_g("insufficient_input_with_posture", lambda x: [x.d] if x.d["status"] == "INSUFFICIENT_INPUT" else [], None,
   lambda x, d: d["project_posture"] is not None and not any(er["code"] == "EXPERIMENT_BOUND_REACHED" for er in d["errors"]))
_g("bound_reached_run_reads_complete", lambda x: [x.d] if any(er["code"] == "EXPERIMENT_BOUND_REACHED" for er in x.d["errors"]) else [], None,
   lambda x, d: d["status"] == "COMPLETED" or d["project_posture"] is not None)
_g("completed_run_without_project_posture", lambda x: [x.d] if x.completed and x.d["track_postures"] else [], None,
   lambda x, d: d["project_posture"] is None)
_g("run_not_terminal", lambda x: [x.d], None, lambda x, d: d["status"] in ("RUNNING", "NOT_STARTED"))
_g("forbidden_field_in_output", lambda x: [k for k, _ in c.walk(x.d)], None,
   lambda x, k: any(f in k.lower() for f in cat.FORBIDDEN_KEY_FRAGMENTS) or k.lower() in cat.FORBIDDEN_KEY_EXACT)
_g("legal_conclusion_text_in_output", lambda x: list(c.LEGAL_MARKERS), None, lambda x, w: w in x.output_text().lower())
_g("score_or_probability_field", lambda x: [k for k, _ in c.walk(x.d)], None,
   lambda x, k: any(f in k.lower() for f in ("score", "probability", "confidence", "similarity")))


__all__ = ["GATES", "GATE_FUNCS"]
