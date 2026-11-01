"""Phase 3B quality families.

DETERMINISTIC families are properties code can decide from the serialized run and the authored facts: each must be
exactly 1.0. MODEL-JUDGMENT families grade a bounded, scripted, possibly-wrong model judgment against the authored
``truth``: they are reported honestly and are NEVER required to be perfect. A family with no denominator is
``None`` ("not measured"), never 1.0.

Everything is re-derived from the serialized run as a plain dict; no Phase 3B validator or derivation is called.
"""

from __future__ import annotations

from typing import Any

from src.evals.experiment_review import catalog as cat
from src.evals.experiment_review import context as c
from src.evals.experiment_review.context import Ctx

DETERMINISTIC_FAMILIES = (
    "authored_contract_accuracy", "source_binding_accuracy", "run_binding", "exact_excerpt_validity",
    "visible_window_containment", "result_quarantine_occurrence_completeness", "incomplete_quarantine_fail_closed",
    "result_mutation_invariance", "execution_flags_invariant", "phase2j_id_continuity", "coverage_single_experiment_derivation",
    "stable_experiment_identity", "canonical_ordering", "deterministic_posture", "provider_failure_fail_closed",
    "call_budget_enforcement", "external_search_zero", "network_attempts_zero", "prompt_trusted_tail_isolation",
    "marker_neutralization", "replay_equivalence", "checkpoint_equivalence", "order_invariance",
    "applicability_catalog_fidelity", "conditional_resolution_needs_judgment", "issue_derivation_fidelity",
    "link_target_completeness", "metric_target_guard", "baseline_layer_separation", "sample_boundary",
    "repetition_boundary", "statistics_conditionality", "hybrid_no_average", "hybrid_no_double_count",
    "no_legacy_input_use", "no_forbidden_fields", "unknown_type_cap", "upstream_mutation_detected",
    "no_result_text_persisted", "rejected_digest_only", "raw_model_text_absent", "quarantine_hash_integrity",
    "error_stage_emitters", "terminal_status_consistency", "claims_binding",
)
MODEL_JUDGMENT_FAMILIES = (
    "experiment_segmentation_precision", "experiment_segmentation_recall", "experiment_type_accuracy",
    "conditional_applicability_accuracy", "claim_experiment_semantic_linkage", "metric_target_alignment",
    "baseline_relevance", "comparator_comparability_judgment", "confounder_bias_recognition",
    "reproducibility_sufficiency", "hybrid_ownership", "result_span_precision", "result_span_recall",
    "criterion_timing_judgment", "sample_adequacy_judgment", "missing_element_recognition",
    "metric_appropriateness_recognition",
)
ALL_REQUIRED_FAMILIES = DETERMINISTIC_FAMILIES + MODEL_JUDGMENT_FAMILIES
STAT_KINDS = ("DESCRIPTIVE_STATISTICS", "CONFIDENCE_INTERVAL", "EFFECT_SIZE", "STATISTICAL_TEST", "TEST_ASSUMPTIONS",
              "MULTIPLE_COMPARISONS", "OUTLIER_HANDLING", "POWER_OR_SAMPLE_ADEQUACY")
INCOMPLETE_MESSAGE = "result quarantine incomplete: a declared result span could not be safely quarantined"
GOOD = "ADEQUATELY_SPECIFIED_FOR_REVIEW"
RUN_LISTS = ("excerpts", "quarantine", "experiments", "links", "measurements", "baselines", "conditions",
             "phase2j_coverage", "track_postures")


def own_excerpt_ids(e: dict[str, Any]) -> set[str]:
    ids = set(e["defining_excerpt_ids"]) | set(e["ownership_excerpt_ids"])
    for r in e["requirements"]:
        ids |= set(r["excerpt_ids"]) | set(r["judgment_excerpt_ids"])
    return ids


def window_text(x: Ctx) -> str:
    return x.text[:x.window_end]


def segmented(x: Ctx) -> bool:
    """Segmentation produced an answer: a declared result span was actually handed to the quarantine."""
    return x.calls_by_task.get("segment", 0) > 0 and not str(x.flags.get("provider_failure", "")).startswith("SEGMENT:")


def declared_results(x: Ctx) -> list[str]:
    return [r for r in x.flags.get("declared_results", []) if r.strip()]


def student_strings(x: Ctx) -> list[str]:
    out = [s for s in [*x.flags.get("protocol", []), *x.flags.get("results", []), *x.flags.get("markers", [])]
           if len(s) >= 12]
    return [*out, x.claim]


def bump_all(result, family: str, oks: list[bool]) -> None:
    for ok in oks:
        result.bump(family, ok)


def nested_records(d: dict[str, Any]) -> list[dict[str, Any]]:
    out = [r for k in RUN_LISTS for r in d[k]]
    out += [r for e in d["experiments"] for r in e["requirements"]]
    return out


def evaluate_quality(x: Ctx, result) -> None:  # noqa: C901 - one flat list of families
    d, text, flags = x.d, x.text, x.flags
    win = window_text(x)
    b = result.bump
    done = x.completed
    # authored contract accuracy
    b("authored_contract_accuracy", result.contract_ok == result.contract_total, 1)

    # -- source and binding ---------------------------------------------------------------------------------
    for e in x.excerpts:
        b("source_binding_accuracy", e["submission_content_hash"] == c.digest(text)
          and e["submission_artifact_id"] == d["submission_artifact_id"])
        b("exact_excerpt_validity", text[e["start"]:e["end"]] == e["excerpt"] and 0 <= e["start"] < e["end"] <= len(text))
        b("visible_window_containment", e["end"] <= x.window_end)
    for q in d["quarantine"]:
        b("visible_window_containment", q["end"] <= x.window_end)
        b("quarantine_hash_integrity", c.digest(text[q["start"]:q["end"]]) == q["span_hash"] and not q["consumed_by_phase3b"])
    for r in nested_records(d):
        if "experiment_run_id" in r:
            b("run_binding", r["experiment_run_id"] == x.run_id)
    for cl in d["bound_claims"]:
        b("claims_binding", cl["claim_text_hash"] == c.digest(x.claim) if cl["claim_id"] == "C-001" else True)

    # -- quarantine -------------------------------------------------------------------------------------------
    incomplete = bool(flags.get("incomplete_quarantine"))
    if incomplete:
        b("incomplete_quarantine_fail_closed", d["status"] == "INSUFFICIENT_INPUT" and d["project_posture"] is None
          and not d["experiments"] and not d["links"] and not d["phase2j_coverage"]
          and sum(x.calls_by_task.get(k, 0) for k in ("extract", "applicability", "link")) == 0
          and any(er["message"] == INCOMPLETE_MESSAGE for er in d["errors"]))
    elif segmented(x):
        spans = [(q["start"], q["end"]) for q in d["quarantine"]]
        for r in declared_results(x):
            for p in c.occurrences(win, r):
                b("result_quarantine_occurrence_completeness", any(lo <= p and p + len(r) <= hi for lo, hi in spans))
    if x.case.twin == "result":
        b("result_mutation_invariance", bool(x.twins.get("result")) and bool(x.twins.get("result_quarantine")))
    out = x.output_text()
    for r in flags.get("results", []):
        if len(r) >= 8:
            b("no_result_text_persisted", r not in out)
    for rp in d["rejected_proposals"]:
        b("rejected_digest_only", set(rp) == {"code", "stage", "response_digest"} and len(rp["response_digest"]) == 64)
    for t_ in flags.get("model_texts", []):
        b("raw_model_text_absent", t_ not in out)
    if flags.get("leaks_prompt"):
        from src.evals.experiment_review.adapter import prompt_line

        b("raw_model_text_absent", prompt_line() not in out)

    # -- execution, search, network, budget ------------------------------------------------------------------
    b("execution_flags_invariant", not d["execution_verified"] and not d["results_evaluated"]
      and not any(e["execution_verified"] or e["independently_reproduced"] or e["leakage_prevented_in_practice"]
                  for e in d["experiments"])
      and not any(bl["execution_verified"] or bl["comparison_result_evaluated"] for bl in d["baselines"])
      and not any(ex["execution_verified"] for ex in x.excerpts), 1)
    b("external_search_zero", d["external_search_calls"] == 0, 1)
    b("network_attempts_zero", d["network_attempts"] == 0 and x.network_attempts == 0, 1)
    if x.model is not None or x.case.no_model:
        mx = d["bounds"]["max_model_calls"]
        ok = d["model_calls_performed"] <= mx and x.provider_requests == d["model_calls_performed"]
        ok = ok and d["model_calls_performed"] <= 1 + 3 * d["bounds"]["max_experiments"] + 3 * d["bounds"]["max_experiments"]
        b("call_budget_enforcement", ok, 1)

    # -- phase 2J continuity ------------------------------------------------------------------------------------
    by_req = {t["validation_requirement_id"]: t for t in x.targets}
    claim_ids = {cl["claim_id"] for cl in d["bound_claims"]}
    for rec in [*d["links"], *d["measurements"], *d["baselines"]]:
        claim = rec.get("claim_id", rec.get("target_claim_id"))
        req = rec["validation_requirement_id"]
        ok = claim in claim_ids and (req is None or (req in by_req and by_req[req]["gap_hypothesis_id"] == rec["gap_hypothesis_id"]))
        b("phase2j_id_continuity", ok)
    for cd in d["conditions"]:
        t_ = by_req.get(cd["validation_requirement_id"])
        b("phase2j_id_continuity", t_ is not None and cd["condition_id"] in t_["condition_ids"])
    for cv in d["phase2j_coverage"]:
        b("phase2j_id_continuity", cv["validation_requirement_id"] in by_req)
        derived = c.derive_coverage(d, by_req[cv["validation_requirement_id"]])
        b("coverage_single_experiment_derivation", derived[0] == cv["status"] and derived[2] == cv["reasons"]
          and sorted(derived[1]) == sorted(cv["covering_experiment_ids"]))

    # -- identity, ordering ----------------------------------------------------------------------------------
    by_id = x.excerpt_by_id
    for e in d["experiments"]:
        texts = [by_id[i]["excerpt"] for i in sorted(e["defining_excerpt_ids"], key=lambda i: (by_id[i]["start"], by_id[i]["end"]))]
        b("stable_experiment_identity", e["protocol_key"] == c.protocol_key_of(texts))
    if x.case.twin == "prefix":
        b("stable_experiment_identity", bool(x.twins.get("prefix_ids")) and bool(x.twins.get("prefix_keys")), 1)
    ids = lambda rows, k: [r[k] for r in rows]  # noqa: E731
    b("canonical_ordering", ids(d["experiments"], "experiment_id") == sorted(ids(d["experiments"], "experiment_id")), 1)
    b("canonical_ordering", [(e["start"], e["end"], e["excerpt_id"]) for e in x.excerpts] ==
      sorted((e["start"], e["end"], e["excerpt_id"]) for e in x.excerpts), 1)
    b("canonical_ordering", ids(d["links"], "link_id") == sorted(ids(d["links"], "link_id")), 1)
    b("canonical_ordering", ids(d["measurements"], "binding_id") == sorted(ids(d["measurements"], "binding_id")), 1)
    b("canonical_ordering", ids(d["baselines"], "record_id") == sorted(ids(d["baselines"], "record_id")), 1)
    b("canonical_ordering", ids(d["phase2j_coverage"], "validation_requirement_id") ==
      sorted(ids(d["phase2j_coverage"], "validation_requirement_id")), 1)
    b("canonical_ordering", [tp["track"] for tp in d["track_postures"]] ==
      [t_ for t_ in ("SCIENTIFIC_RESEARCH", "ENGINEERING") if t_ in [tp["track"] for tp in d["track_postures"]]], 1)

    # -- postures ---------------------------------------------------------------------------------------------
    for e in d["experiments"]:
        if not e["requirements"]:
            continue
        ms, bs, links = c.exp_records(d, e)
        issues = c.derive_issues(e, ms, bs, links)
        b("issue_derivation_fidelity", issues == e["issues"])
        b("deterministic_posture", c.derive_exp_posture(e, issues, ms, links) == e["posture"])
    if done:
        for tp in d["track_postures"]:
            b("deterministic_posture", c.derive_track_posture(d, tp["track"]) == tp["posture"])
        b("deterministic_posture", c.derive_project_posture(d) == d["project_posture"], 1)
        b("terminal_status_consistency", d["project_posture"] is not None or not d["track_postures"], 1)
    if d["status"] == "INVALIDATED_UPSTREAM_MUTATED":
        b("terminal_status_consistency", d["project_posture"] is None and not d["experiments"], 1)
    if d["status"] != "RUNNING":
        b("terminal_status_consistency", d["completed_at"] is not None, 1)
    for er in d["errors"]:
        b("error_stage_emitters", c.STAGE_SHORT[er["node"]] in c.EMITTERS[er["code"]])

    # -- catalog fidelity, applicability -------------------------------------------------------------------
    for e in d["experiments"]:
        if not e["requirements"]:
            continue
        b("applicability_catalog_fidelity", [r["kind"] for r in e["requirements"]] == list(cat.KINDS), 1)
        for r in e["requirements"]:
            gold = cat.cell(r["kind"], e["experiment_type"])
            if r["basis"] in ("CATALOG_DEFAULT", "CATALOG_TYPE_OVERRIDE", "EXPERIMENT_TYPE_UNKNOWN") or gold in ("R", "O", "-"):
                want = {"R": "REQUIRED", "O": "OPTIONAL", "-": "NOT_APPLICABLE", "C": "CONDITIONAL"}[gold]
                b("applicability_catalog_fidelity", r["applicability"] == want or (
                    gold == "C" and r["basis"] != "CATALOG_DEFAULT" and r["basis"] != "CATALOG_TYPE_OVERRIDE"))
            if r["basis"] in ("MODEL_ASSISTED_BOUNDED_JUDGMENT",):
                b("conditional_resolution_needs_judgment", bool(r["judgment_excerpt_ids"]))
            if r["basis"] == "CONDITION_UNRESOLVED":
                b("conditional_resolution_needs_judgment", r["applicability"] == "CONDITIONAL")
            if e["experiment_type"] == "UNKNOWN":
                b("unknown_type_cap", r["applicability"] == ("REQUIRED" if r["kind"] in cat.UNIVERSAL else "CONDITIONAL"))
        if e["experiment_type"] == "UNKNOWN":
            b("unknown_type_cap", e["posture"] != "WELL_SPECIFIED")
    if flags.get("no_inference"):
        for e in d["experiments"]:
            r = x.req(e, "STATISTICAL_TEST")
            if r is not None:
                b("statistics_conditionality", r["applicability"] != "REQUIRED")
    for e in d["experiments"]:
        for r in e["requirements"]:
            if r["kind"] in STAT_KINDS:
                b("statistics_conditionality", not (r["applicability"] == "REQUIRED" and r["basis"] in
                                                     ("CATALOG_DEFAULT", "CATALOG_TYPE_OVERRIDE")))
            if r["kind"] in ("SAMPLE_SIZE", "SAMPLE_SIZE_RATIONALE") and r["excerpt_ids"]:
                bare = all(c.is_bare_quantity(by_id[i]["excerpt"]) for i in r["excerpt_ids"])
                b("sample_boundary", not (bare and (r["adequacy"] == GOOD or r["kind"] == "SAMPLE_SIZE_RATIONALE")))
        if flags.get("rep_count_only"):
            r = x.req(e, "REPETITION_INDEPENDENCE")
            if r is not None and r["applicability"] == "REQUIRED":
                b("repetition_boundary", r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT")

    # -- linkage -------------------------------------------------------------------------------------------------
    targets_n = len(claim_ids) + len(x.targets)
    for e in d["experiments"]:
        if e["requirements"] and not incomplete:
            b("link_target_completeness", len(x.links_of(e)) == targets_n)
    for lk in d["links"]:
        if lk["relation"] == "DIRECTLY_TESTS":
            tgt = (lk["claim_id"], lk["gap_hypothesis_id"], lk["validation_requirement_id"])
            b("metric_target_guard", any(m["experiment_id"] == lk["experiment_id"] and m["alignment"] == "ALIGNED_SAME_TARGET"
                                         and (m["target_claim_id"], m["gap_hypothesis_id"], m["validation_requirement_id"]) == tgt
                                         for m in d["measurements"]))
    for bl in d["baselines"]:
        b("baseline_layer_separation", not bl["execution_verified"] and not bl["comparison_result_evaluated"])
        for p in bl["comparability"]:
            if p["status"] in ("DOCUMENTED_SAME", "DOCUMENTED_DIFFERENT") and p["basis"] == "MODEL_ASSISTED_BOUNDED_JUDGMENT":
                b("baseline_layer_separation", bool(p["excerpt_ids"]))
            if p["status"] == "NOT_APPLICABLE":
                b("baseline_layer_separation", False)

    # -- hybrid ------------------------------------------------------------------------------------------------
    if x.project_type == "HYBRID" and done:
        worst_track = cat.worst([tp["posture"] for tp in d["track_postures"]]) if d["track_postures"] else None
        if worst_track:
            b("hybrid_no_average", cat.WORST_ORDER.index(d["project_posture"]) <= cat.WORST_ORDER.index(worst_track))
        seen: set[str] = set()
        for tp in d["track_postures"]:
            for eid in tp["experiment_ids"]:
                e = next(e for e in d["experiments"] if e["experiment_id"] == eid)
                b("hybrid_no_double_count", eid not in seen and e["track"] == tp["track"])
                seen.add(eid)
        for e in d["experiments"]:
            if e["track"] is None:
                b("hybrid_no_double_count", e["experiment_id"] not in seen)

    # -- prompts, legacy -------------------------------------------------------------------------------------
    students = student_strings(x)
    for p in x.all_prompts():
        tail = c.tail_of(p)
        b("prompt_trusted_tail_isolation", not any(s in tail for s in students) and not c.ARABIC.search(tail))
        b("marker_neutralization", p.count(c.MARKER_END) == 1 and p.count("===") == 2 * c.marker_lines(p))
    if x.case.legacy_leak:
        from src.evals.experiment_review.adapter import LEGACY_MARKER

        b("no_legacy_input_use", LEGACY_MARKER not in out and not any(LEGACY_MARKER in p for p in x.all_prompts()))
        b("no_legacy_input_use", bool(x.legacy_twin.get("same")) and bool(x.legacy_twin.get("prompts_same")))
    for k, _ in c.walk(d):
        b("no_forbidden_fields", not (any(f in k.lower() for f in cat.FORBIDDEN_KEY_FRAGMENTS) or k.lower() in cat.FORBIDDEN_KEY_EXACT))

    # -- replay, checkpoint, order, mutation, provider failure ------------------------------------------------
    if x.case.rerun:
        b("replay_equivalence", bool(x.replay.get("same")) and x.replay.get("extra_calls") == 0, 1)
    if x.case.interrupt_before:
        b("checkpoint_equivalence", bool(x.replay.get("resume_same")), 1)
    if x.case.twin == "order":
        b("order_invariance", bool(x.twins.get("order")) and bool(x.twins.get("ids")), 1)
    if x.case.mutate:
        b("upstream_mutation_detected", x.mutated.get("status") == "INVALIDATED_UPSTREAM_MUTATED" and x.mutated.get("kept") == 0
          and x.mutated.get("posture") is None, 1)
    pf = flags.get("provider_failure")
    if pf:
        stage, code = pf.split(":")
        strong = any(e["posture"] == "WELL_SPECIFIED" for e in d["experiments"]) or d["project_posture"] == "WELL_SPECIFIED"
        stages = sorted({c.STAGE_SHORT[er["node"]] for er in d["errors"] if er["code"] == code})
        b("provider_failure_fail_closed", not strong and stage in stages, 1)

    # -- model-judgment families (authored truth vs the produced run) ------------------------------------------
    judge(x, result)


def judge(x: Ctx, result) -> None:  # noqa: C901
    d, truth = x.d, x.case.truth
    b = result.bump
    exps = x.exps
    by_id = x.excerpt_by_id
    produced = [[by_id[i]["excerpt"] for i in e["defining_excerpt_ids"]] for e in exps]
    true_exps = truth.get("experiments")
    if true_exps:
        for te in dict.fromkeys(true_exps):
            b("experiment_segmentation_recall", any(te in p for p in produced))
        for p in produced:
            b("experiment_segmentation_precision", any(te in p for te in true_exps))
        if not produced:
            b("experiment_segmentation_precision", True, 0)
    for k, ty in truth.get("types", {}).items():
        e = x.exp(int(k))
        b("experiment_type_accuracy", e is not None and e["experiment_type"] == ty)
    for kind, trig in truth.get("fired", {}).items():
        for e in exps[:1]:
            r = x.req(e, kind)
            b("conditional_applicability_accuracy", r is not None and r["applicability"] == "REQUIRED")
    for kind in truth.get("not_applicable", []):
        for e in exps[:1]:
            r = x.req(e, kind)
            b("conditional_applicability_accuracy", r is not None and r["applicability"] == "NOT_APPLICABLE")
    e1 = x.exp(1)
    for label, rel in truth.get("links", {}).items():
        lk = x.link_for(e1, label) if e1 else None
        b("claim_experiment_semantic_linkage", lk is not None and lk["relation"] == rel)
    for label, want in truth.get("alignment", {}).items():
        m = x.meas_for(e1, label) if e1 else None
        got = m["alignment"] if m else "ABSENT"
        b("metric_target_alignment", (got == "ALIGNED_SAME_TARGET") == (want == "ALIGNED_SAME_TARGET")
          and (want != "METRIC_TARGET_MISMATCH" or got in ("METRIC_TARGET_MISMATCH", "ABSENT", "METRIC_NOT_DEFINED")))
    for label, want in truth.get("match", {}).items():
        m = x.meas_for(e1, label) if e1 else None
        b("metric_target_alignment", m is not None and m["phase2j_metric_match"] == want)
    for label, want in truth.get("baseline_relevance", {}).items():
        bl = x.baseline_for(e1, label) if e1 else None
        b("baseline_relevance", bl is not None and bl["relevance"] == want)
    for prop, want in truth.get("comparability", {}).items():
        bl = x.baseline_for(e1, "V1") if e1 else None
        hit = next((p for p in (bl["comparability"] if bl else []) if p["property"] == prop), None)
        b("comparator_comparability_judgment", hit is not None and hit["status"] == want)
    if truth.get("bias_recognised"):
        b("confounder_bias_recognition", any("BIAS_NOT_ADDRESSED_WHEN_REQUIRED" in e["issues"] for e in exps))
    if "reproducible" in truth:
        flagged = any(i in e["issues"] for e in exps for i in
                      ("REPRODUCIBILITY_INSUFFICIENT", "REPETITIONS_MISSING_WHEN_REQUIRED", "PROTOCOL_RISK_IDENTIFIED"))
        b("reproducibility_sufficiency", (not flagged) == bool(truth["reproducible"]))
    for k, track in truth.get("owners", {}).items():
        e = x.exp(int(k))
        b("hybrid_ownership", e is not None and e["track"] == track)
    for label, want in truth.get("timing", {}).items():
        m = x.meas_for(e1, label) if e1 else None
        b("criterion_timing_judgment", m is not None and m["success_criterion_timing"] == want)
    if "sample_adequate" in truth and e1:
        size, why = x.req(e1, "SAMPLE_SIZE"), x.req(e1, "SAMPLE_SIZE_RATIONALE")
        predicted = (size is not None and size["adequacy"] == GOOD and size["documentation"] == "EXPLICITLY_DOCUMENTED"
                     and (why is None or why["applicability"] != "REQUIRED" or why["documentation"] == "EXPLICITLY_DOCUMENTED"))
        b("sample_adequacy_judgment", predicted == bool(truth["sample_adequate"]))
    for kind in truth.get("missing", []):
        r = x.req(e1, kind) if e1 else None
        b("missing_element_recognition", r is not None and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT")
    if truth.get("metric_appropriate") is False and e1:
        b("metric_appropriateness_recognition", "PROTOCOL_RISK_IDENTIFIED" in e1["issues"])
    true_results = [r for r in truth.get("results", []) if r.strip()]
    if true_results or d["quarantine"]:
        win = window_text(x)
        spans = [(q["start"], q["end"]) for q in d["quarantine"]]
        occ = [(p, p + len(r)) for r in true_results for p in c.occurrences(win, r)]
        kinds = x.case.flags.get("result_kinds", {})
        lang = x.case.language
        for r in true_results:
            tags = [f"@{lang}"] + (["#repeated"] if len(c.occurrences(win, r)) > 1 else []) + (
                ["#table"] if kinds.get(r) == "RESULT_TABLE" else [])
            for p_ in c.occurrences(win, r):
                hit = any(a <= p_ and p_ + len(r) <= z for a, z in spans)
                b("result_span_recall", hit)
                for tag in tags:
                    b("result_span_recall" + tag, hit)
        for a, z in spans:
            hit = any(lo < z and a < hi for lo, hi in occ)
            b("result_span_precision", hit)
            b(f"result_span_precision@{lang}", hit)
        if not occ:
            b("result_span_recall", True, 0)
        if not spans:
            b("result_span_precision", True, 0)


__all__ = ["ALL_REQUIRED_FAMILIES", "DETERMINISTIC_FAMILIES", "MODEL_JUDGMENT_FAMILIES", "evaluate_quality"]
