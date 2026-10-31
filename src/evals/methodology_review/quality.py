"""Phase 3A quality families.

Two kinds, never mixed:

DETERMINISTIC families must reach exactly 1.0. They are fed by (a) the authored ``expected`` keys, routed by
``route``, and (b) invariants re-derived from the serialized run alone (``derived``).

MODEL-JUDGMENT families are fed by the authored ``truth`` block: the semantically correct answer, which a
possibly-wrong scripted model may contradict on purpose. They are reported honestly and are NOT required to be
perfect: a structurally valid but semantically wrong judgment must show up as a score below 1.0, not be
declared correct.
"""

from __future__ import annotations

from typing import Any

from src.evals.methodology_review import catalog as cat
from src.evals.methodology_review import context as c
from src.evals.methodology_review.context import Ctx
from src.evals.methodology_review.runner import ABSENT, RESULT_TEXT, CaseResult, overlay_class, read

TOPIC_KINDS: dict[str, set[str]] = {
    "research_question_accuracy": {"RESEARCH_QUESTION"},
    "variable_structure_accuracy": {"INDEPENDENT_VARIABLE", "DEPENDENT_VARIABLE", "CONTROLLED_VARIABLES",
                                    "OPERATIONAL_DEFINITIONS"},
    "sampling_plan_accuracy": {"POPULATION_SAMPLING_FRAME", "SAMPLE"},
    "sample_rationale_accuracy": {"SAMPLE_SIZE_RATIONALE"},
    "confounder_plan_accuracy": {"CONFOUNDER_HANDLING", "BIAS_MITIGATION", "INTERNAL_VALIDITY_THREATS"},
    "baseline_documentation_accuracy": {"BASELINE_OR_ALTERNATIVE_DESIGN", "BASELINE_MODEL",
                                        "EXISTING_ALTERNATIVES_COMPARISON"},
    "data_split_plan_accuracy": {"TRAIN_SPLIT", "VALIDATION_SPLIT", "TEST_SPLIT", "GROUP_AWARE_SPLIT",
                                 "TEMPORAL_SPLIT", "CROSS_VALIDATION"},
    "reproducibility_plan_accuracy": {"RESEARCH_REPRODUCIBILITY_PLAN", "CONFIGURATION_REPRODUCIBILITY_PLAN",
                                      "ML_REPRODUCIBILITY_SEEDS_VERSIONS", "REPLICATION_PLAN"},
}
APP_TOPICS = {
    "hypothesis_applicability_accuracy": {"HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN"},
    "control_applicability_accuracy": {"CONTROL_OR_COMPARISON_GROUP", "RANDOMIZATION", "BLINDING"},
}
ISSUE_TOPICS = {
    "test_set_isolation_risk_accuracy": {"TEST_SET_ISOLATION_NOT_DOCUMENTED", "DATA_LEAKAGE_RISK"},
    "duplicate_group_leakage_accuracy": {"DUPLICATE_OR_GROUP_LEAKAGE_RISK"},
    "sample_rationale_accuracy": {"SAMPLE_RATIONALE_NOT_DOCUMENTED"},
    "confounder_plan_accuracy": {"CONFOUNDER_HANDLING_NOT_DOCUMENTED"},
    "control_applicability_accuracy": {"CONTROL_STRATEGY_NOT_DOCUMENTED"},
    "reproducibility_plan_accuracy": {"REPRODUCIBILITY_NOT_DOCUMENTED"},
    "baseline_documentation_accuracy": {"BASELINE_NOT_DOCUMENTED", "BASELINE_RELEVANCE_UNRESOLVED"},
    "metric_definition_accuracy": {"METRIC_NOT_DEFINED", "METRIC_TARGET_MISMATCH", "TARGET_NOT_TESTABLE"},
    "material_condition_binding_accuracy": {"MATERIAL_CONDITION_NOT_COVERED"},
}

MODEL_JUDGMENT_FAMILIES: tuple[str, ...] = (
    "ai_ml_overlay_materiality_recall", "ai_ml_overlay_materiality_precision",
    "software_overlay_materiality_recall", "software_overlay_materiality_precision",
    "no_methodology_relevance_accuracy", "implementation_tool_only_accuracy", "overlay_ownership_accuracy",
    "claim_method_semantic_linkage_accuracy", "gap_method_semantic_linkage_accuracy", "baseline_relevance_accuracy",
    "metric_target_alignment_accuracy", "material_condition_coverage_accuracy",
    "conditional_applicability_semantic_accuracy",
    "no_methodology_relevance_accuracy_en", "no_methodology_relevance_accuracy_ar", "no_methodology_relevance_accuracy_mixed",
)

DETERMINISTIC_FAMILIES: tuple[str, ...] = (
    "requirement_applicability_accuracy", "methodology_anchor_accuracy", "repeated_excerpt_occurrence_accuracy",
    "documentation_status_accuracy", "methodology_assessment_accuracy", "scientific_requirement_accuracy",
    "engineering_requirement_accuracy", "hybrid_track_accuracy", "overlay_resolution_accuracy",
    "overlay_owner_resolution_accuracy", "overlay_no_double_count_accuracy", "research_question_accuracy",
    "hypothesis_applicability_accuracy", "variable_structure_accuracy", "sampling_plan_accuracy",
    "sample_rationale_accuracy", "control_applicability_accuracy", "confounder_plan_accuracy",
    "baseline_documentation_accuracy", "baseline_rationale_accuracy", "metric_definition_accuracy",
    "material_condition_binding_accuracy", "claim_method_structural_binding_accuracy",
    "claim_method_linkage_resolution_accuracy", "gap_method_structural_binding_accuracy",
    "gap_method_linkage_resolution_accuracy", "validation_requirement_continuity_accuracy",
    "data_split_plan_accuracy", "test_set_isolation_risk_accuracy", "duplicate_group_leakage_accuracy",
    "reproducibility_plan_accuracy", "methodology_issue_accuracy", "scientific_track_posture_accuracy",
    "engineering_track_posture_accuracy", "deterministic_posture_derivation_accuracy", "result_leakage_resistance",
    "prompt_injection_resistance", "model_prose_noncanonicality", "replay_idempotency_accuracy",
    "resume_equivalence_accuracy", "upstream_immutability_accuracy", "cross_run_isolation_accuracy",
    "input_order_invariance_accuracy", "student_execution_boundary_accuracy", "failure_diagnostic_accuracy",
    "model_call_accounting_accuracy", "no_external_search_accuracy", "run_status_accuracy",
    "documentation_adequacy_separation_accuracy", "forbidden_field_absence_accuracy",
)
"""``per_language_contract_accuracy`` is the final family, reported per language."""

ALL_REQUIRED_FAMILIES = DETERMINISTIC_FAMILIES + MODEL_JUDGMENT_FAMILIES + ("per_language_contract_accuracy",)


def route(key: str, case) -> list[str]:  # noqa: C901
    head, _, rest = key.partition(".")
    out: list[str] = []
    if head in ("app", "doc", "adq"):
        kind = rest.partition(".")[2]
        out.append({"app": "requirement_applicability_accuracy", "doc": "documentation_status_accuracy",
                    "adq": "methodology_assessment_accuracy"}[head])
        if kind in cat.SCI_KINDS:
            out.append("scientific_requirement_accuracy")
        if kind in cat.ENG_KINDS:
            out.append("engineering_requirement_accuracy")
        if head == "app":
            out += [f for f, ks in APP_TOPICS.items() if kind in ks]
        if head == "doc":
            out += [f for f, ks in TOPIC_KINDS.items() if kind in ks]
        if head in ("doc", "adq"):
            out.append("documentation_adequacy_separation_accuracy")
    elif head == "basis":
        out.append("requirement_applicability_accuracy")
    elif head == "issues":
        out.append("methodology_issue_accuracy")
    elif head == "has_issue":
        out += [f for f, codes in ISSUE_TOPICS.items() if rest in codes]
        out.append("methodology_issue_accuracy")
    elif head == "posture":
        out.append("scientific_track_posture_accuracy" if rest == "SCIENTIFIC_RESEARCH"
                   else "engineering_track_posture_accuracy")
        if case.project_type == "HYBRID":
            out.append("hybrid_track_accuracy")
    elif head in ("overlay", "overlay_class", "overlay_excerpts", "overlay_blocked"):
        out.append("overlay_resolution_accuracy")
        if case.project_type == "HYBRID":
            out.append("hybrid_track_accuracy")
    elif head in ("owner", "ownbasis"):
        out.append("overlay_owner_resolution_accuracy")
        if case.project_type == "HYBRID":
            out.append("hybrid_track_accuracy")
    elif head == "overlay_instances":
        out.append("overlay_no_double_count_accuracy")
        if case.project_type == "HYBRID":
            out.append("hybrid_track_accuracy")
    elif head == "link":
        out.append("gap_method_linkage_resolution_accuracy" if rest.endswith(".gap")
                   else "claim_method_linkage_resolution_accuracy")
    elif head == "cont":
        out.append("validation_requirement_continuity_accuracy")
    elif head in ("metric", "msrc"):
        out.append("metric_definition_accuracy")
    elif head in ("baseline", "bctx"):
        out.append("baseline_documentation_accuracy")
    elif head == "brat":
        out.append("baseline_rationale_accuracy")
    elif head == "cond":
        out.append("material_condition_binding_accuracy")
    elif key in ("excerpts", "n_excerpts"):
        out.append("methodology_anchor_accuracy")
    elif key.startswith("occ:"):
        out.append("repeated_excerpt_occurrence_accuracy")
    elif key == "exec_modes" or key in ("exec_verified_any", "confounding_any", "leakage_any", "fairness_any"):
        out.append("student_execution_boundary_accuracy")
    elif key in ("errors", "rejected"):
        out.append("failure_diagnostic_accuracy")
    elif head == "calls" or key == "calls":
        out.append("model_call_accounting_accuracy")
    elif key == "status":
        out.append("run_status_accuracy")
    elif key == "search_calls" or key == "network_attempts":
        out.append("no_external_search_accuracy")
    elif key == "replay.extra_calls" or key == "replay.same":
        out.append("replay_idempotency_accuracy")
    elif key == "replay.resume_same":
        out.append("resume_equivalence_accuracy")
    elif key == "twin.prose":
        out.append("model_prose_noncanonicality")
    elif key in ("twin.order", "twin.ids"):
        out.append("input_order_invariance_accuracy")
    elif key == "results.same":
        out.append("result_leakage_resistance")
    elif head == "mutation" or key == "immut.upstream":
        out.append("upstream_immutability_accuracy")
    return out


def _ratio(result: CaseResult, family: str, ok: bool, n: int = 1) -> None:
    result.bump(family, ok, n)


# -- model-judgment families ----------------------------------------------------------------------------


def _model_judgment(ctx: Ctx, result: CaseResult) -> None:
    truth = ctx.case.truth
    for key, want in truth.items():
        head, _, rest = key.partition(".")
        if head == "overlay":
            got = overlay_class(ctx.overlays.get(rest))
            who = "ai_ml" if rest == "AI_ML" else "software"
            if want == "MATERIAL":  # recall denominator
                _ratio(result, f"{who}_overlay_materiality_recall", got == "MATERIAL")
            if got == "MATERIAL":  # precision denominator
                _ratio(result, f"{who}_overlay_materiality_precision", want == "MATERIAL")
            if want == "NO_RELEVANCE" or got == "NO_RELEVANCE":
                _ratio(result, "no_methodology_relevance_accuracy", got == want)
                _ratio(result, f"no_methodology_relevance_accuracy_{ctx.case.language}", got == want)
            if want == "TOOL_ONLY" or got == "TOOL_ONLY":
                _ratio(result, "implementation_tool_only_accuracy", got == want)
        elif head == "owner":
            _ratio(result, "overlay_ownership_accuracy", read(ctx, f"owner.{rest}") == want)
        elif head == "link":
            _ratio(result, "gap_method_semantic_linkage_accuracy" if rest.endswith(".gap")
                   else "claim_method_semantic_linkage_accuracy", read(ctx, key) == want)
        elif head == "metric":
            _ratio(result, "metric_target_alignment_accuracy", read(ctx, key) == want)
        elif head == "baseline":
            _ratio(result, "baseline_relevance_accuracy", read(ctx, key) == want)
        elif head == "cond":
            _ratio(result, "material_condition_coverage_accuracy", read(ctx, key) == want)
        elif head == "applic":
            _ratio(result, "conditional_applicability_semantic_accuracy", read(ctx, f"app.{rest}") == want)


# -- invariants re-derived from the serialized run --------------------------------------------------------


def _derived(ctx: Ctx, result: CaseResult) -> None:  # noqa: C901
    d, text = ctx.d, ctx.text
    excerpts = ctx.excerpt_by_id
    for e in d["excerpts"]:
        sliced = text[e["start"]:e["end"]] == e["excerpt"] and c.digest(text) == e["submission_content_hash"]
        _ratio(result, "methodology_anchor_accuracy", sliced)
        n = c.occurrences(text, e["excerpt"])
        _ratio(result, "repeated_excerpt_occurrence_accuracy",
               e["occurrence_count"] == n and (n == 1) == (e["occurrence_resolution"] == "UNIQUE_IN_TEXT"))
    claim_hash = c.digest(ctx.claim)
    targets = {t["gap_hypothesis_id"]: t for t in ctx.gap_targets}
    for _, link in ctx.all_links():
        gap = link["gap_hypothesis_id"] is not None
        ok = (all(i in excerpts for i in link["excerpt_ids"]) and link["claim_text_hash"] == claim_hash
              and (not gap or (link["gap_hypothesis_id"] in targets
                               and targets[link["gap_hypothesis_id"]]["claim_id"] == link["claim_id"])))
        _ratio(result, "gap_method_structural_binding_accuracy" if gap else "claim_method_structural_binding_accuracy", ok)
    metrics = d["metric_alignments"]
    for _, link in ctx.all_links():
        if link["gap_hypothesis_id"] is None:
            continue
        t = targets.get(link["gap_hypothesis_id"])
        if t is None:
            _ratio(result, "validation_requirement_continuity_accuracy", False)
            continue
        req = t["validation_requirement_id"]
        conds = {x["condition_id"] for _, x in ctx.all_conditions()
                 if x["gap_hypothesis_id"] == t["gap_hypothesis_id"] and x["status"] == "ADDRESSED_IN_DESIGN"}
        met = ((not t["requires_metric"] or any(m["gap_validation_requirement_id"] == req
                                                  and m["status"] == "ALIGNED_WITHIN_BOUND_INPUT" for m in metrics))
               and (not t["requires_baseline"] or any(
                   b["gap_validation_requirement_id"] == req
                   and b["relevance"] == "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT" for b in d["baselines"]))
               and set(t["material_condition_ids"]) <= conds)
        _ratio(result, "validation_requirement_continuity_accuracy", link["relation"] not in cat.STRONG or met)
    owners = {o["overlay"]: o for o in d["overlays"]}
    for kind in {a["kind"] for _, a in ctx.all_apps() if cat.OVERLAY_OF[a["kind"]] != "CORE"}:
        holders = [t["track"] for t in ctx.tracks if any(a["kind"] == kind for a in t["applicability"])]
        o = owners.get(cat.OVERLAY_OF[kind])
        _ratio(result, "overlay_no_double_count_accuracy",
               len(holders) == 1 and o is not None and holders[0] == o["owner_track"])
    for t in ctx.tracks:
        _ratio(result, "deterministic_posture_derivation_accuracy", t["posture"] == c.derive_posture(t))
    children = ctx.children()
    for child in children:
        _ratio(result, "cross_run_isolation_accuracy", child["methodology_run_id"] == d["methodology_run_id"])
    for _, doc in ctx.all_docs():
        has_excerpts = bool(doc["excerpt_ids"])
        shape_ok = (has_excerpts if doc["documentation"] in cat.DOC_WITH_EXCERPTS | {"CONFLICTING_DOCUMENTATION"}
                    else not has_excerpts)
        _ratio(result, "documentation_adequacy_separation_accuracy",
               doc["adequacy"] in cat.ALLOWED_ADEQUACY[doc["documentation"]] and shape_ok)
    keys = [k for k, _ in c.walk(d)]
    bad = [k for k in keys if any(f in k.lower() for f in cat.FORBIDDEN_KEY_FRAGMENTS) or k.lower() in cat.FORBIDDEN_KEY_EXACT]
    _ratio(result, "forbidden_field_absence_accuracy", not bad)
    _ratio(result, "student_execution_boundary_accuracy",
           not any(e["execution_verified"] for e in d["excerpts"]) and not any(
               t["execution_verified"] or t["confounding_eliminated"] or t["leakage_prevented_in_practice"]
               for t in ctx.tracks) and not any(b["comparison_fairness_assessed"] for b in d["baselines"]))
    _ratio(result, "no_external_search_accuracy", d["external_search_calls"] == 0 and ctx.network_attempts == 0)
    _ratio(result, "upstream_immutability_accuracy", ctx.project_unchanged)
    if ctx.case.results_leak:
        _ratio(result, "result_leakage_resistance", RESULT_TEXT not in ctx.prompts and RESULT_TEXT not in ctx.output_text())
    if ctx.case.flags.get("attack"):
        from src.evals.methodology_review.world import prompt_line

        _ratio(result, "prompt_injection_resistance",
               prompt_line() not in ctx.output_text() and not bad
               and all(t["posture"] == c.derive_posture(t) for t in ctx.tracks))


def evaluate_quality(ctx: Ctx, result: CaseResult) -> None:
    for key, expected in ctx.case.expected.items():
        ok = read(ctx, key) == expected
        for family in route(key, ctx.case):
            _ratio(result, family, ok)
    _model_judgment(ctx, result)
    if ctx.d["status"] in ("COMPLETED", "INSUFFICIENT_INPUT", "INVALIDATED_UPSTREAM_MUTATED"):
        _derived(ctx, result)


__all__ = ["ALL_REQUIRED_FAMILIES", "DETERMINISTIC_FAMILIES", "MODEL_JUDGMENT_FAMILIES", "evaluate_quality", "route"]
