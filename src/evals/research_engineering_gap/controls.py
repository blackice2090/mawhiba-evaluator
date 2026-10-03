"""Negative controls: each one SIMULATES a Phase 2J trust mechanism being disabled or
bypassed, by producing the output such a broken mechanism would emit, and the eval
must detect it.

Detection is by the contract (the run refuses to validate, and the refusal must be
for the INTENDED reason -- a regex over the error) or by a release gate firing on
the tampered run. A control that is caught for an unrelated reason is a miss.
``None`` means the control was inapplicable to the case."""

from __future__ import annotations

import copy
import re
from typing import Any, Callable
from uuid import uuid4

from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.context import Ctx
from src.schemas.gap_assessment import GapAssessmentRun

Tamper = Callable[[dict[str, Any], Ctx], dict[str, Any] | None]


def _h(d: dict[str, Any]) -> dict[str, Any] | None:
    return d["hypotheses"][0] if d["hypotheses"] else None


def _lim_ref(h: dict[str, Any]) -> dict[str, Any] | None:
    by = {r["evidence_ref_id"]: r for r in h["evidence_refs"]}
    for lim in h["limitations"]:
        for i in lim["evidence_ref_ids"]:
            return by[i]
    return None


def _inv_of(d: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any] | None:
    return next((t for t in d["inventory_texts"]
                 if t["source_kind"] == ref["source_kind"] and t["source_record_id"] == ref["source_record_id"]), None)


def _with_h(fn):
    def tamper(d, ctx):
        h = _h(d)
        return fn(d, h, ctx) if h else None

    return tamper


def _t_anchor(d, h, ctx):
    ref = _lim_ref(h)
    if ref is None:
        return None
    ref["excerpt"] = "x" * len(ref["excerpt"])
    return d


def _t_offsets(d, h, ctx):
    ref = _lim_ref(h)
    if ref is None:
        return None
    ref["start"] += 1
    ref["end"] += 1
    return d


def _t_repeat(d, h, ctx):
    ref = _lim_ref(h)
    if ref is None:
        return None
    ref["occurrence_count"], ref["occurrence_index"], ref["occurrence_resolution"] = 2, 1, "UNIQUE_IN_TEXT"
    return d


def _t_hash(d, h, ctx):
    ref = _lim_ref(h)
    if ref is None:
        return None
    ref["text_hash"] = "0" * 64
    return d


def _drop_from_coverage(d: dict[str, Any], text_id: str) -> bool:
    """Keep the coverage ledger consistent so the INTENDED check is the one that fires.
    False when the text was an OMITTED one: dropping it would change the review's completeness."""
    if any(text_id in cov["omitted_text_ids"] for cov in d["counterevidence_coverage"]):
        return False
    for cov in d["counterevidence_coverage"]:
        cov["examined_text_ids"] = [i for i in cov["examined_text_ids"] if i != text_id]
    return True


def _t_visibility(d, h, ctx):
    ref = _lim_ref(h)
    inv = _inv_of(d, ref) if ref else None
    if inv is None or not _drop_from_coverage(d, inv["inventory_text_id"]):
        return None
    inv["linked_claim_ids"] = ["C-999"]
    return d


def _t_inventory(d, h, ctx):
    ref = _lim_ref(h)
    inv = _inv_of(d, ref) if ref else None
    if inv is None or not _drop_from_coverage(d, inv["inventory_text_id"]):
        return None
    d["inventory_texts"] = [t for t in d["inventory_texts"] if t is not inv]
    return d


def _t_independence(d, h, ctx):
    ref = _lim_ref(h)
    if ref is None:
        return None
    ref["counts_as_independent"] = not ref["counts_as_independent"]
    return d


def _t_absence(d, h, ctx):
    if not h["limitations"]:
        return None
    h["limitations"][0]["limitation_type"] = "NOT_MENTIONED"
    return d


def _kind_eligible(kinds: set[str]):
    def tamper(d, h, ctx):
        for lim in h["limitations"]:
            for ref in ctx_refs(h, lim):
                if ref["text_kind"] in kinds and ref["source_quality"] != "ELIGIBLE":
                    ref["source_quality"] = "ELIGIBLE"
                    inv = _inv_of(d, ref)
                    if inv:
                        inv["source_quality"] = "ELIGIBLE"
                    return d
        return None

    return tamper


def ctx_refs(h: dict[str, Any], lim: dict[str, Any]) -> list[dict[str, Any]]:
    by = {r["evidence_ref_id"]: r for r in h["evidence_refs"]}
    return [by[i] for i in lim["evidence_ref_ids"] if i in by]


def _t_numeric(d, h, ctx):
    for lim in h["limitations"]:
        if lim["facet"] == "ENGINEERING" and not any(any(ch.isdigit() for ch in r["excerpt"]) for r in ctx_refs(h, lim)):
            lim["limitation_type"] = "MEASURED_SHORTFALL"
            return d
    return None


def _t_facet(d, h, ctx):
    for lim in h["limitations"]:
        if lim["limitation_type"] in ("MEASURED_SHORTFALL", "UNMET_REQUIREMENT", "REPORTED_FAILURE_MODE", "TRADEOFF"):
            lim["facet"] = "RESEARCH"
            return d
        if lim["limitation_type"] == "UNRESOLVED_QUESTION":
            lim["facet"] = "ENGINEERING"
            return d
    return None


def _t_scope_dim(d, h, ctx):
    for lim in h["limitations"]:
        if not lim["condition_dimensions"]:
            lim["limitation_type"] = "SCOPE_RESTRICTION"
            return d
    return None


def _t_dup_prop(d, h, ctx):
    if not h["limitations"]:
        return None
    dup = copy.deepcopy(h["limitations"][0])
    dup["limitation_id"] = str(uuid4())
    h["limitations"].append(dup)
    return d


def _t_hybrid_relabel(d, h, ctx):
    for lim in h["limitations"]:
        if lim["limitation_type"] in ("EXPLICIT_LIMITATION", "SCOPE_RESTRICTION"):
            dup = copy.deepcopy(lim)
            dup["limitation_id"] = str(uuid4())
            dup["facet"] = "RESEARCH" if lim["facet"] == "ENGINEERING" else "ENGINEERING"
            h["limitations"].append(dup)
            h["kind"] = "HYBRID"
            return d
    return None


def _t_struct_link(d, h, ctx):
    if h["linkage"] == "FULL":
        return None
    h["linkage"] = "FULL"
    return d


def _t_semantic(d, h, ctx):
    if h["linkage"] == "FULL":
        return None
    for lk in h["project_links"]:
        if lk["relation"] not in ("ADDRESSES_LIMITATION", "PARTIALLY_ADDRESSES_LIMITATION") and lk["status"] == "DIFFERENTIATING_FEATURE":
            lk["relation"] = "ADDRESSES_LIMITATION"
            return d
    return None


def _t_partial_supported(d, h, ctx):
    if h["linkage"] != "PARTIAL":
        return None
    h["posture"] = "SUPPORTED_WITHIN_BOUNDS"
    return d


def _on_link(field: str, value):
    def tamper(d, h, ctx):
        if not h["project_links"]:
            return None
        h["project_links"][0][field] = value() if callable(value) else value
        return d

    return tamper


def _t_link_status(d, h, ctx):
    if not h["project_links"]:
        return None
    lk = h["project_links"][0]
    lk["status"] = "FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE" if lk["status"] == "DIFFERENTIATING_FEATURE" else "DIFFERENTIATING_FEATURE"
    return d


def _t_no_capability(d, h, ctx):
    if h["posture"] != "SUPPORTED_WITHIN_BOUNDS" or not h["existing_capabilities"]:
        return None
    h["existing_capabilities"] = []
    return d


def _t_materiality(d, h, ctx):
    for k, v in h["condition_materiality"].items():
        if v == "CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED":
            h["condition_materiality"][k] = "CONDITION_NOT_MATERIAL"
            return d
    return None


def _t_condition_removed(d, h, ctx):
    if not h["conditions"] or "CONDITION_REQUIRED_AND_BOUND" not in h["condition_materiality"].values():
        return None
    h["conditions"] = []
    if h["validation_requirement"]:
        h["validation_requirement"]["condition_ids"] = []
    return d


def _t_synthetic_condition(d, h, ctx):
    if not h["limitations"]:
        return None
    h["conditions"].append({"condition_id": str(uuid4()), "dimension": "ENVIRONMENT",
                            "limitation_ids": [h["limitations"][0]["limitation_id"]], "evidence_ref_ids": [str(uuid4())]})
    return d


def _t_corroboration(d, h, ctx):
    if h["corroboration"] in ("MULTI_SOURCE_CORROBORATED", "MIXED_SOURCE_CORROBORATED"):
        return None
    h["corroboration"] = "MULTI_SOURCE_CORROBORATED"
    return d


def _dependent_counted(candidate_type: str, relations: set[str] | None = None):
    def tamper(d, h, ctx):
        for ref in h["evidence_refs"]:
            unit = ref["inherited_unit"]
            if unit and unit["candidate_type"] == candidate_type and not ref["counts_as_independent"]:
                if relations and ctx_rel(ctx, ref) not in relations:
                    continue
                ref["counts_as_independent"] = True
                return d
        return None

    return tamper


def ctx_rel(ctx: Ctx, ref: dict[str, Any]) -> str | None:
    cand = next((p for p in (ctx.run.open_source_prior_art.candidates if ctx.run.open_source_prior_art else [])
                 if str(p.candidate_id) == ref.get("candidate_id")), None)
    return cand.relationship.value if cand else None


def _t_corr_collapse(d, h, ctx):
    groups = [r["correlation_group_key"] for r in h["evidence_refs"] if r["correlation_group_key"]]
    if len(groups) < 2 or len(set(groups)) == len(groups):
        return None
    h["corroboration"] = "MULTI_SOURCE_CORROBORATED"
    return d


def _t_counter_suppressed(d, h, ctx):
    if h["posture"] != "COUNTEREVIDENCE_WEAKENS_GAP":
        return None
    h["counterevidence"] = []
    return d


def _t_coverage(d, h, ctx):
    if h["counterevidence_review_complete"]:
        return None
    h["counterevidence_review_complete"] = True
    return d


def _t_diff_defeats(d, h, ctx):
    if not h["counterevidence"] or any(ce["condition_match"] != "DIFFERENT_CONDITION" for ce in h["counterevidence"]):
        return None
    h["posture"] = "COUNTEREVIDENCE_WEAKENS_GAP"
    return d


def _t_narrowing_lost(d, h, ctx):
    if h["counterevidence_scope_effect"] != "NARROWED_BY_DIFFERENT_CONDITION":
        return None
    h["counterevidence_scope_effect"] = "NO_SCOPE_NARROWING"
    return d


def _t_after_cutoff(d, h, ctx):
    for ce in h["counterevidence"]:
        if ce["chronology_bucket"] == "AFTER_CUTOFF":
            ce["temporal_effect"] = "NOT_APPLICABLE"
            return d
    return None


def _t_publicity(d, h, ctx):
    if not h["chronology"]:
        return None
    h["chronology"][0]["historical_publicity_inferred"] = True
    return d


def _t_legal_key(d, h, ctx):
    h["patentable"] = True
    return d


def _t_field_wide(d, h, ctx):
    h["scope"] = "FIELD_WIDE"
    return d


def _t_score_key(d, h, ctx):
    h["score"] = 0.9
    return d


def _t_prompt_summary(d, ctx):
    line = c.prompt_lines()[0]
    d["rejected_proposals"].append({"claim_id": next(iter(ctx.claims)), "reason": "INVALID_FACET", "inadmissible_basis": None,
                                    "safe_summary": line})
    return d


def _t_provider_text(d, ctx):
    d["errors"].append({"code": "MODEL_ERROR", "node": "EXTRACT_GAP_CANDIDATES", "message": c.prompt_lines()[0][:200],
                        "claim_id": next(iter(ctx.claims))})
    return d


def _t_prose_field(d, h, ctx):
    h["rationale"] = "free model prose"
    return d


def _t_proposed_kind(d, h, ctx):
    if h["kind"] == "HYBRID":
        return None
    h["model_proposed_kind"] = "HYBRID"
    h["kind"] = "HYBRID"
    return d


def _t_run_binding(d, h, ctx):
    h["research_run_id"] = str(uuid4())
    return d


def _t_search(d, ctx):
    d["external_search_calls"] = 3
    return d


def _t_posture(d, h, ctx):
    h["posture"] = "PARTIALLY_SUPPORTED" if h["posture"] != "PARTIALLY_SUPPORTED" else "SUPPORTED_WITHIN_BOUNDS"
    return d


def _t_dup_hyp(d, h, ctx):
    d["hypotheses"].append(copy.deepcopy(h))
    return d


def _t_statement(d, h, ctx):
    h["bounded_statement"]["condition_ids"] = [str(uuid4())]
    return d


def _t_chron_support(d, h, ctx):
    if not h["limitations"]:
        return None
    h["limitations"][0]["chronology"] = "BEFORE_CUTOFF"
    return d


def _tamper_h(fn):
    return _with_h(fn)


# name -> (tamper(d, ctx), detector). Detector: ("contract", regex) | ("gate", name) | ("fn", callable(ctx)->bool)
CONTROLS: dict[str, tuple[Tamper, tuple]] = {
    "anchor_verification_disabled": (_tamper_h(_t_anchor), ("gate", "excerpt_not_source_slice")),
    "offset_validation_disabled": (_tamper_h(_t_offsets), ("gate", "excerpt_not_source_slice")),
    "repeated_anchor_first_occurrence_guessing": (_tamper_h(_t_repeat), ("contract", "first-occurrence")),
    "content_hash_verification_disabled": (_tamper_h(_t_hash), ("gate", "excerpt_text_hash_mismatch")),
    "claim_visibility_check_disabled": (_tamper_h(_t_visibility), ("contract", "cross-claim leakage")),
    "inventory_boundary_disabled": (_tamper_h(_t_inventory), ("contract", "outside the bounded inventory")),
    "independence_inheritance_disabled": (_tamper_h(_t_independence), ("contract", "inherit")),
    "absence_basis_admitted": (_tamper_h(_t_absence), ("contract", "limitation_type")),
    "title_text_made_limitation_eligible": (_tamper_h(_kind_eligible(c.TITLE_KINDS)), ("gate", "title_limitation_eligible")),
    "manifest_made_limitation_eligible": (_tamper_h(_kind_eligible({"OSS_MANIFEST"})), ("gate", "manifest_limitation_eligible")),
    "repo_metadata_made_limitation_eligible": (_tamper_h(_kind_eligible(c.REPO_METADATA_KINDS)),
                                               ("gate", "repo_metadata_limitation_eligible")),
    "numeric_shortfall_verification_disabled": (_tamper_h(_t_numeric), ("contract", "number")),
    "facet_type_check_disabled": (_tamper_h(_t_facet), ("contract", "cannot support")),
    "scope_dimension_check_disabled": (_tamper_h(_t_scope_dim), ("contract", "condition-specific")),
    "duplicate_proposition_admitted": (_tamper_h(_t_dup_prop), ("contract", "same proposition")),
    "hybrid_relabel_inflation": (_tamper_h(_t_hybrid_relabel), ("contract", "same proposition")),
    "structural_linkage_inferred": (_tamper_h(_t_struct_link), ("contract", "derived in code")),
    "semantic_linkage_validation_disabled": (_tamper_h(_t_semantic), ("contract", "derived in code")),
    "partial_linkage_promoted_to_supported": (_tamper_h(_t_partial_supported), ("contract", "derived in code")),
    "cross_claim_linkage_accepted": (_tamper_h(_on_link("claim_id", "C-999")), ("contract", "cross-claim")),
    "foreign_run_linkage_accepted": (_tamper_h(_on_link("nd_run_id", lambda: str(uuid4()))), ("contract", "Phase 2I run")),
    "fabricated_limitation_linkage_accepted": (_tamper_h(_on_link("limitation_id", lambda: str(uuid4()))),
                                               ("contract", "fabricated limitation")),
    "link_status_asserted": (_tamper_h(_t_link_status), ("contract", "derived from the Phase 2I status")),
    "capability_requirement_removed": (_tamper_h(_t_no_capability), ("contract", "derived in code")),
    "condition_materiality_disabled": (_tamper_h(_t_materiality), ("contract", "derived in code")),
    "condition_binding_disabled": (_tamper_h(_t_condition_removed), ("contract", "derived in code")),
    "synthetic_condition_injected": (_tamper_h(_t_synthetic_condition), ("contract", "not on the hypothesis")),
    "independence_grouping_disabled": (_tamper_h(_t_corroboration), ("contract", "derived in code")),
    "unresolved_patent_family_counted": (_tamper_h(_dependent_counted("PATENT")), ("contract", "inherited unchanged")),
    "oss_fork_or_mirror_counted_independent": (_tamper_h(_dependent_counted("OPEN_SOURCE")), ("contract", "inherited unchanged")),
    "product_correlation_collapse_disabled": (_tamper_h(_t_corr_collapse), ("contract", "derived in code")),
    "counterevidence_suppressed": (_tamper_h(_t_counter_suppressed), ("contract", "derived in code")),
    "counterevidence_coverage_bypassed": (_tamper_h(_t_coverage), ("contract", "derived in code|coverage")),
    "different_condition_defeats_gap": (_tamper_h(_t_diff_defeats), ("contract", "derived in code")),
    "narrowing_lost": (_tamper_h(_t_narrowing_lost), ("contract", "derived in code")),
    "after_cutoff_counterevidence_rewritten": (_tamper_h(_t_after_cutoff), ("contract", "after-cutoff")),
    "chronology_publicity_inferred": (_tamper_h(_t_publicity), ("contract", "historical_publicity_inferred|False")),
    "legal_conclusion_injected": (_tamper_h(_t_legal_key), ("contract", "Extra inputs")),
    "field_wide_scope_injected": (_tamper_h(_t_field_wide), ("contract", "scope")),
    "score_field_injected": (_tamper_h(_t_score_key), ("contract", "Extra inputs")),
    "prompt_leak_redaction_disabled": (_t_prompt_summary, ("fn", lambda ctx: _hits(ctx) > 0)),
    "provider_text_persisted": (_t_provider_text, ("fn", lambda ctx: _hits(ctx) > 0)),
    "model_prose_isolation_disabled": (_tamper_h(_t_prose_field), ("contract", "Extra inputs")),
    "proposed_kind_trusted": (_tamper_h(_t_proposed_kind), ("contract", "derived in code")),
    "run_binding_disabled": (_tamper_h(_t_run_binding), ("contract", "different run")),
    "external_search_invoked": (_t_search, ("contract", "external_search_calls|Input should be 0")),
    "deterministic_synthesis_disabled": (_tamper_h(_t_posture), ("contract", "derived in code")),
    "duplicate_hypothesis_admitted": (_tamper_h(_t_dup_hyp), ("contract", "unique")),
    "bounded_statement_not_rebuilt": (_tamper_h(_t_statement), ("contract", "derived in code")),
    "chronology_leaked_into_support": (_tamper_h(_t_chron_support), ("contract", "Extra inputs")),
}


def _hits(ctx: Ctx) -> int:
    import json

    blob = json.dumps(ctx.d, ensure_ascii=False)
    return sum(1 for line in c.prompt_lines() if line in blob)


# Controls that tamper the case context rather than the serialized run.
def _ctl_replay(ctx: Ctx):
    if "rerun_calls" not in ctx.replay:
        return None
    from src.evals.research_engineering_gap.gates import GATE_FUNCS

    clone = ctx.clone(replay={**ctx.replay, "rerun_calls": 2})
    return GATE_FUNCS["replay_made_a_model_call"](clone)[0] > 0


def _ctl_fingerprint(ctx: Ctx):
    if not ctx.case.mutate:
        return None
    from src.evals.research_engineering_gap.gates import GATE_FUNCS

    clone = ctx.clone(mutated={"detected": False})
    gate = "claim_mutation_after_binding_accepted" if ctx.case.mutate == "claim_edit" else "upstream_mutation_accepted"
    return GATE_FUNCS[gate](clone)[0] > 0


def _ctl_upstream(field_name: str, gate_name: str):
    def control(ctx: Ctx):
        sub = getattr(ctx.run, field_name)
        if sub is None:
            return None
        from src.evals.research_engineering_gap.gates import GATE_FUNCS

        from datetime import timedelta

        tampered = ctx.run.model_copy(update={field_name: sub.model_copy(update={"started_at": sub.started_at + timedelta(seconds=1)})})
        clone = ctx.clone(run=tampered)
        return GATE_FUNCS[gate_name](clone)[0] > 0

    return control


CONTEXT_CONTROLS: dict[str, Callable[[Ctx], bool | None]] = {
    "replay_guard_disabled": _ctl_replay,
    "upstream_fingerprint_check_disabled": _ctl_fingerprint,
    "upstream_phase2i_mutated": _ctl_upstream("novelty_differentiation", "phase2i_novelty_mutated"),
    "upstream_phase2g_mutated": _ctl_upstream("patent_prior_art", "phase2g_patent_mutated"),
    "upstream_phase2c_mutated": _ctl_upstream("evidence_extraction", "phase2c_evidence_mutated"),
}


def contract_error(d: dict[str, Any]) -> str | None:
    try:
        GapAssessmentRun.model_validate(d)
    except Exception as exc:
        return str(exc)
    return None


MAX_ATTEMPTS_PER_MECHANISM_AND_LANGUAGE = 4
_BUDGET: dict[tuple[str, str], int] = {}


def reset_control_budget() -> None:
    _BUDGET.clear()


def _spent(name: str, language: str) -> bool:
    return _BUDGET.get((name, language), 0) >= MAX_ATTEMPTS_PER_MECHANISM_AND_LANGUAGE


def _spend(name: str, language: str) -> None:
    """A mechanism is attempted on at most N applicable cases per language, so every language
    is exercised and the eval stays fast. Applicability is decided BEFORE the budget is spent."""
    _BUDGET[(name, language)] = _BUDGET.get((name, language), 0) + 1


def run_control(ctx: Ctx, name: str) -> tuple[bool | None, str]:
    """(caught?, how). ``None``: the control was inapplicable to the case (or its budget is spent)."""
    if _spent(name, ctx.case.language):
        return None, ""
    if name in CONTEXT_CONTROLS:
        caught = CONTEXT_CONTROLS[name](ctx)
        if caught is not None:
            _spend(name, ctx.case.language)
        return caught, "gate"
    tamper, (kind, spec) = CONTROLS[name]
    try:
        d = tamper(copy.deepcopy(ctx.d), ctx)
    except (KeyError, IndexError, StopIteration):
        return None, ""
    if d is None:
        return None, ""
    _spend(name, ctx.case.language)
    message = contract_error(d)
    if kind == "contract":
        return (message is not None and re.search(spec, message) is not None), "contract"
    if message is not None and kind != "fn":
        # the gate is the intended detector; the contract refusing first is still a refusal, but for
        # a different reason -- count it only when the gate also fires on the dict as given
        pass
    clone = ctx.clone(d=d)
    try:
        if kind == "gate":
            from src.evals.research_engineering_gap.gates import GATE_FUNCS

            return GATE_FUNCS[spec](clone)[0] > 0, "gate"
        return bool(spec(clone)), "fn"
    except Exception:
        return True, "gate"


ALL_CONTROLS: tuple[str, ...] = (*CONTROLS, *CONTEXT_CONTROLS)

__all__ = ["ALL_CONTROLS", "CONTEXT_CONTROLS", "CONTROLS", "reset_control_budget", "run_control"]
