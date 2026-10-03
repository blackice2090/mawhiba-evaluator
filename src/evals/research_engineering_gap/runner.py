"""Phase 2J Gold runner: runs each case through the REAL upstream graphs and the REAL
Phase 2J graph (scripted untrusted model, no network), summarizes the serialized
run independently, compares it with the AUTHORED expectations, and computes the
quality families, release gates and negative controls.

The summary is read from the run's JSON dict and the upstream records; it never
calls a Phase 2J validator or derive function (context.py re-implements the
policy rules)."""

from __future__ import annotations

import copy
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.context import Ctx
from src.evals.research_engineering_gap.dataset import GapGoldCase
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.schemas.gap_assessment import GapAssessmentBounds


# ---------------------------------------------------------------------------
# Phase 2I script (case input) and upstream
# ---------------------------------------------------------------------------


def build_nd_script(case: GapGoldCase) -> dict[str, Any]:
    nd = case.nd
    features = nd.get("features", {})
    script: dict[str, Any] = {"features": features}
    mode = nd.get("mode", "differentiating")
    if mode == "differentiating":
        script["default_relation"] = "NOT_DISCLOSED"
        return script
    comparisons = []
    for claim in case.claims:
        texts = [f["text"] for f in features.get(claim.claim_id, [])]
        disclosed = texts if mode == "disclose_all" else list(nd.get("disclose", []))
        judgments = [{"feature": t, "relation": "DISCLOSED", "evidence": [{"excerpt": t, "in": "PATENT_CLAIMS"}]}
                     for t in disclosed]
        if mode == "disclose_all":
            judgments.append({"feature": "COMBINATION", "relation": "DISCLOSED",
                              "evidence": [{"excerpt": claim.claim, "in": "PATENT_CLAIMS"}]})
        comparisons.append({"candidate": "", "claim_id": claim.claim_id, "judgments": judgments,
                            "rest": "NOT_DISCLOSED"})
    script["comparisons"] = comparisons
    return script


def build_upstream(case: GapGoldCase):
    claims = [x.model_dump() for x in case.claims]
    state = build_phase2i_world(
        case.case_id, claims, patent=case.patent or None,
        product=case.product or {"provider": False, "fetcher": False},
        oss=case.oss or {"provider": False}, cutoff=case.cutoff, nd_script=build_nd_script(case),
        drop_sufficiency=case.drop_sufficiency,
    )
    if case.retract_academic:
        run = state.active_research_run
        extraction = run.evidence_extraction
        retracted = [e.model_copy(update={"is_retracted": True}) for e in extraction.verified_evidence]
        run = run.model_copy(update={"evidence_extraction": extraction.model_copy(update={"verified_evidence": retracted})})
        state = state.model_copy(update={"research_runs": {str(run.research_run_id): run}})
    return state


# ---------------------------------------------------------------------------
# Twin scripts
# ---------------------------------------------------------------------------


def _with_prose(script: dict[str, Any], prose: str) -> dict[str, Any]:
    """The same TYPED facts with free prose injected everywhere prose can go."""
    out = copy.deepcopy(script)

    def inject(item: Any) -> None:
        if isinstance(item, dict):
            item["rationale"] = prose
            for nested in item.get("conditions", []):
                nested["rationale"] = prose

    for spec in out.get("extract", {}).values():
        if isinstance(spec, dict):
            for item in [*spec.get("capabilities", []), *spec.get("limitations", [])]:
                inject(item)
            spec["proposed_kind"] = "HYBRID"
    for key in ("link", "counter"):
        for items in out.get(key, {}).values():
            for item in items if isinstance(items, list) else []:
                inject(item)
    return out


def _reordered(script: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(script)
    for spec in out.get("extract", {}).values():
        if isinstance(spec, dict):
            spec["limitations"] = list(reversed(spec.get("limitations", [])))
            spec["capabilities"] = list(reversed(spec.get("capabilities", [])))
    for key in ("link", "counter"):
        for cid, items in list(out.get(key, {}).items()):
            if isinstance(items, list):
                out[key][cid] = list(reversed(items))
    return out


# ---------------------------------------------------------------------------
# Summary (independent of Phase 2J code)
# ---------------------------------------------------------------------------


def _hyp_summary(ctx: Ctx, cid: str) -> dict[str, Any]:
    h = ctx.hyps.get(cid)
    s: dict[str, Any] = {"hyp.exists": h is not None}
    if h is None:
        return s
    lims = h["limitations"]
    by = ctx.refs_by_id(h)
    lim_refs = [r for lim in lims for r in ctx.lim_refs(h, lim)]
    stmt = h["bounded_statement"]
    s.update({
        "hyp.posture": h["posture"], "hyp.kind": h["kind"], "hyp.existence": h["existence"],
        "hyp.linkage": h["linkage"], "hyp.corroboration": h["corroboration"], "hyp.scope": h["scope"],
        "hyp.scope_effect": h["counterevidence_scope_effect"], "hyp.review_complete": h["counterevidence_review_complete"],
        "hyp.missing": sorted(h["missing_components"]),
        "hyp.materiality": sorted(h["condition_materiality"].values()),
        "lim.types": sorted(f"{lim['limitation_type']}/{lim['facet']}" for lim in lims),
        "lim.excerpts": sorted(r["excerpt"] for r in lim_refs),
        "lim.quality": sorted(r["source_quality"] for r in lim_refs),
        "lim.n": len(lims),
        "cap.excerpts": sorted(by[i]["excerpt"] for cap in h["existing_capabilities"] for i in cap["evidence_ref_ids"]),
        "cond.dims": sorted(cd["dimension"] for cd in h["conditions"]),
        "cond.n": len(h["conditions"]),
        "link.relations": sorted(lk["relation"] for lk in h["project_links"]),
        "link.n": len(h["project_links"]),
        "counter.kinds": sorted(ce["kind"] for ce in h["counterevidence"]),
        "counter.matches": sorted(ce["condition_match"] for ce in h["counterevidence"]),
        "counter.n": len(h["counterevidence"]),
        "narrowing.n": len(h["narrowing_counter_ids"]),
        "narrowing.current_only": h["narrowing_current_only"],
        "chron.buckets": sorted({n["bucket"] for n in h["chronology"]}),
        "chron.counter_buckets": sorted({ce["chronology_bucket"] for ce in h["counterevidence"] if ce["chronology_bucket"]}),
        "stmt.limitations": len(stmt["limitation_ids"]), "stmt.conditions": len(stmt["condition_ids"]),
        "stmt.scope_effect": stmt["scope_effect"],
        "val.metric": h["validation_requirement"]["metric"]["text"] if h["validation_requirement"] else None,
        "val.metric_origin": h["validation_requirement"]["metric"]["origin"] if h["validation_requirement"] else None,
        "val.baseline": (h["validation_requirement"]["baseline"] or {}).get("text") if h["validation_requirement"] else None,
    })
    return s


def summarize_claim(ctx: Ctx, cid: str) -> dict[str, Any]:
    a = ctx.assess[cid]
    d = ctx.d
    s: dict[str, Any] = {
        "claim.posture": a["posture"], "claim.reasons": sorted(a["insufficient_reasons"]),
        "claim.has_diff": a["has_differentiating_feature"], "claim.existence": a["hypothesis_existence"],
        "claim.linkage": a["hypothesis_linkage"], "claim.rejected_n": a["rejected_proposal_count"],
    }
    s.update(_hyp_summary(ctx, cid))
    rejected = [r for r in d["rejected_proposals"] if r["claim_id"] == cid]
    s["rejected"] = sorted({r["reason"] for r in rejected})
    s["issues"] = sorted({e["code"] for e in d["errors"] if e.get("claim_id") == cid})
    visible = [t for t in d["inventory_texts"] if not t["linked_claim_ids"] or cid in t["linked_claim_ids"]]
    s["indep.units"] = sorted({f"{(t['inherited_unit'] or {}).get('unit_kind') or t['independence_basis']}:"
                               f"{t['counts_as_independent']}{'+corr' if t['correlation_group_key'] else ''}"
                               for t in visible})
    return s


def summarize(ctx: Ctx) -> dict[str, Any]:
    d = ctx.d
    s: dict[str, Any] = {
        "run.status": d["status"], "run.model_calls": d["model_calls_performed"],
        "run.search_calls": d["external_search_calls"],
        "run.issues": sorted({e["code"] for e in d["errors"] if not e.get("claim_id")}),
        "run.claims": len(d["claim_assessments"]), "run.hypotheses": len(d["hypotheses"]),
    }
    for cid in ctx.claims:
        for key, value in summarize_claim(ctx, cid).items():
            s[key if cid == next(iter(ctx.claims)) else f"{cid}:{key}"] = value
    first = next(iter(ctx.claims))
    for cid in list(ctx.claims)[1:]:
        s[f"{cid}:claim.posture"] = ctx.assess[cid]["posture"]
    if ctx.replay:
        s["replay.extra_calls"] = ctx.replay.get("rerun_calls")
        s["replay.same"] = ctx.replay.get("same")
        if "resumed_same" in ctx.replay:
            s["resume.same"] = ctx.replay["resumed_same"]
    if ctx.twins:
        for name in ("prose", "order"):
            if name in ctx.twins:
                s[f"{name}.same"] = ctx.twins[name]["same"]
        if "ids" in ctx.twins:
            s["ids.same"] = ctx.twins["ids"]
    s["immut.upstream_identical"] = upstream_identical(ctx)
    s["bind.mutation_detected"] = ctx.mutated.get("detected")
    return s


UPSTREAM_FIELDS = ("evidence_extraction", "claim_sufficiency", "claim_evidence_scoring", "patent_prior_art",
                   "product_prior_art", "open_source_prior_art", "novelty_differentiation")


def upstream_identical(ctx: Ctx) -> bool:
    for name in UPSTREAM_FIELDS:
        a, b = getattr(ctx.prior, name), getattr(ctx.run, name)
        if (a.model_dump_json() if a is not None else None) != (b.model_dump_json() if b is not None else None):
            return False
    return ctx.before.project.model_dump_json() == ctx.after.project.model_dump_json()


def matches(expected: Any, actual: Any) -> bool:
    return expected == actual


def check_expected(key: str, expected: Any, summary: dict[str, Any]) -> tuple[bool, Any]:
    if key.endswith(".includes"):
        base = summary.get(key[: -len(".includes")]) or []
        return set(expected) <= set(base), base
    if key.endswith(".excludes"):
        base = summary.get(key[: -len(".excludes")]) or []
        return not set(expected) & set(base), base
    actual = summary.get(key)
    return matches(expected, actual), actual


# ---------------------------------------------------------------------------
# Quality families
# ---------------------------------------------------------------------------

EXPECT_FAMILIES: dict[str, tuple[str, ...]] = {
    "cap.excerpts": ("existing_capability_accuracy",),
    "lim.excerpts": ("limitation_anchor_accuracy",),
    "lim.n": ("limitation_anchor_accuracy",),
    "lim.types": ("limitation_type_accuracy",),
    "lim.quality": ("source_quality_handling_accuracy",),
    "rejected": ("limitation_admissibility_accuracy",),
    "rejected.includes": ("limitation_admissibility_accuracy",),
    "rejected.excludes": ("limitation_admissibility_accuracy",),
    "claim.existence": ("gap_existence_accuracy",),
    "hyp.existence": ("gap_existence_accuracy",),
    "hyp.linkage": ("linkage_level_accuracy",),
    "claim.linkage": ("linkage_level_accuracy",),
    "link.n": ("project_link_binding_accuracy",),
    "link.relations": ("project_link_binding_accuracy",),
    "hyp.materiality": ("condition_materiality_accuracy",),
    "cond.dims": ("condition_binding_accuracy",),
    "cond.n": ("condition_binding_accuracy",),
    "val.metric": ("validation_requirement_accuracy",),
    "val.metric_origin": ("validation_requirement_accuracy",),
    "val.baseline": ("validation_requirement_accuracy",),
    "hyp.corroboration": ("corroboration_accuracy",),
    "hyp.scope": ("scope_accuracy",),
    "counter.kinds": ("counterevidence_detection_accuracy",),
    "counter.n": ("counterevidence_detection_accuracy",),
    "counter.matches": ("counterevidence_detection_accuracy", "counterevidence_condition_relation_accuracy"),
    "hyp.review_complete": ("counterevidence_coverage_accuracy",),
    "hyp.scope_effect": ("counterevidence_scope_effect_accuracy",),
    "narrowing.n": ("counterevidence_scope_effect_accuracy",),
    "narrowing.current_only": ("counterevidence_scope_effect_accuracy",),
    "chron.buckets": ("chronology_separation_accuracy",),
    "chron.counter_buckets": ("chronology_separation_accuracy",),
    "hyp.posture": ("hypothesis_posture_accuracy",),
    "claim.posture": ("claim_posture_accuracy",),
    "claim.reasons": ("claim_posture_accuracy",),
    "claim.has_diff": ("claim_posture_accuracy",),
    "stmt.limitations": ("bounded_statement_accuracy",),
    "stmt.conditions": ("bounded_statement_accuracy",),
    "stmt.scope_effect": ("bounded_statement_accuracy",),
    "replay.extra_calls": ("replay_idempotency_accuracy",),
    "replay.same": ("replay_idempotency_accuracy",),
    "resume.same": ("replay_idempotency_accuracy",),
    "prose.same": ("model_prose_noncanonicality",),
    "order.same": ("input_order_invariance_accuracy",),
    "ids.same": ("input_order_invariance_accuracy",),
    "immut.upstream_identical": ("upstream_immutability_accuracy",),
    "bind.mutation_detected": ("cross_run_isolation_accuracy",),
    "run.search_calls": ("no_new_search_accuracy",),
    "issues": ("issue_reporting_accuracy",),
    "run.issues": ("issue_reporting_accuracy",),
    "indep.units": (),
}


def families_for(key: str, expected: Any, case: GapGoldCase) -> list[str]:
    bare = key.split(":", 1)[-1]
    out = list(EXPECT_FAMILIES.get(bare, ()))
    cats = case.categories
    if bare == "hyp.kind":
        out.append({"RESEARCH": "research_gap_kind_accuracy", "ENGINEERING": "engineering_gap_kind_accuracy",
                    "HYBRID": "hybrid_gap_accuracy"}.get(expected, "unresolved_gap_kind_accuracy"))
    if bare == "indep.units":
        text = " ".join(expected) if isinstance(expected, list) else ""
        for token, fam in (("ACADEMIC", "academic_independence_accuracy"), ("PATENT", "patent_independence_accuracy"),
                           ("PRODUCT", "product_independence_accuracy"), ("OSS", "oss_independence_accuracy")):
            if token in text:
                out.append(fam)
    if bare in ("lim.n", "hyp.kind", "lim.types") and any(x.startswith(("hybrid", "proposition")) for x in cats):
        out.append("proposition_distinctness_accuracy")
    if bare in ("rejected", "rejected.includes") and any(x.startswith("absence-basis") for x in cats):
        out.append("absence_rejection_accuracy")
    if bare in ("rejected", "rejected.includes", "val.metric", "issues") and any(x.startswith("invented-metric") for x in cats):
        out.append("metric_noninvention_accuracy")
    if bare in ("claim.posture", "hyp.posture") and expected in ("DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
                                                                  "NOT_ESTABLISHED_WITHIN_BOUNDS"):
        out.append("differentiation_not_gap_accuracy")
    if bare in ("claim.posture", "hyp.posture", "hyp.missing") and any(x.startswith("localization") for x in cats):
        out.append("localization_not_gap_accuracy")
    if bare in ("rejected", "rejected.includes", "issues", "issues.includes", "claim.reasons", "run.issues") and any(
            x.startswith("injection") or x.startswith("leak") or x.startswith("off-contract") for x in cats):
        out.append("prompt_injection_resistance")
    return out


@dataclass
class CaseResult:
    case: GapGoldCase
    summary: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    gates: dict[str, tuple[int, int]] = field(default_factory=dict)
    controls: list[tuple[str, bool | None, str]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    contract_ok: int = 0
    contract_total: int = 0
    error: str | None = None
    ctx: Any = None

    def bump(self, family: str, ok: bool) -> None:
        self.quality[family][1] += 1
        self.quality[family][0] += int(ok)


# ---------------------------------------------------------------------------
# Run one case
# ---------------------------------------------------------------------------


def _bounds(case: GapGoldCase) -> GapAssessmentBounds | None:
    return GapAssessmentBounds(**case.bounds) if case.bounds else None


def _gap_dict(state) -> dict[str, Any]:
    return state.active_research_run.research_engineering_gap.model_dump(mode="json")


def run_mutation_case(case: GapGoldCase, before, claims: dict[str, str], model) -> tuple[Any, dict[str, Any]]:
    """Run the stages by hand, mutate the world (a claim, or an upstream subrun) before
    FINALIZE, and report whether the mutation was detected."""
    from src.research.gap import pipeline as gp
    from src.schemas.common import ProjectType

    run = before.active_research_run
    claim_list = list(before.project.claims)
    provider = model.provider() if model else None
    now = datetime.now(UTC)
    bounds = _bounds(case) or GapAssessmentBounds()
    gap = gp.open_gap_run(run, claim_list, ProjectType.UNKNOWN, bounds, now)
    gap = gp.inventory_stage(gap, run)
    gap = gp.extraction_stage(gap, run, claim_list, provider, None)
    gap = gp.linkage_stage(gap, run, claim_list, provider, None)
    gap = gp.counterevidence_stage(gap, run, claim_list, provider, None)
    gap = gp.project_stage(gp.synthesis_stage(gap, run))
    final_run, final_claims = run, claim_list
    if case.mutate == "claim_edit":
        final_claims = [x.model_copy(update={"claim": x.claim + " and a battery"}) for x in claim_list]
    elif case.mutate == "upstream_mutation":
        nd = run.novelty_differentiation
        final_run = run.model_copy(update={"novelty_differentiation": nd.model_copy(update={"model_comparisons_performed": 999})})
    final = gp.finalize_stage(gap, final_run, final_claims, now)
    detected = any(a.insufficient_reasons for a in final.claim_assessments) and (
        case.mutate != "upstream_mutation" or final.status.value == "INSUFFICIENT_INPUT")
    return final, {"detected": detected}


def run_case(case: GapGoldCase) -> CaseResult:
    from src.evals.research_engineering_gap.controls import run_control
    from src.evals.research_engineering_gap.gates import GATE_FUNCS, GATES
    from src.evals.research_engineering_gap.quality import derived_quality

    result = CaseResult(case=case)
    try:
        before = build_upstream(case)
        claims = {x.claim_id: x.claim for x in case.claims}
        model = None if case.no_model else ScriptedGapModel(claims, case.script)
        provider = model.provider() if model else None
        bounds = _bounds(case)
        mutated: dict[str, Any] = {}
        if case.mutate:
            final, mutated = run_mutation_case(case, before, claims, model)
            d = final.model_dump(mode="json")
            after = before
        else:
            after = run_phase2j(before, provider, bounds=bounds, interrupt_before=case.interrupt_before)
            d = _gap_dict(after)
        run = after.active_research_run
        prior = before.active_research_run
        ctx = Ctx(case=case, before=before, after=after, run=run, prior=prior, d=d, claims=claims, model=model,
                  provider=provider, mutated=mutated)
        if case.rerun and not case.mutate:
            again_model = ScriptedGapModel(claims, case.script)
            again = run_phase2j(after, again_model.provider(), bounds=bounds)
            ctx.replay = {"rerun_calls": len(again_model.calls),
                          "same": c.strip_times(d) == c.strip_times(_gap_dict(again))}
        if case.interrupt_before and not case.mutate:
            plain_model = ScriptedGapModel(claims, case.script)
            plain = run_phase2j(before, plain_model.provider(), bounds=bounds)
            ctx.replay = {**ctx.replay, "resumed_same": c.strip_times(d) == c.strip_times(_gap_dict(plain))}
        if case.twin == "prose":
            twin = ScriptedGapModel(claims, _with_prose(case.script, case.prose))
            twin_d = _gap_dict(run_phase2j(before, twin.provider(), bounds=bounds))
            ctx.twins["prose"] = {"d": twin_d, "same": _canonical(d) == _canonical(twin_d)}
        if case.twin == "order":
            twin = ScriptedGapModel(claims, _reordered(case.script))
            twin_d = _gap_dict(run_phase2j(before, twin.provider(), bounds=bounds))
            ctx.twins["order"] = {"d": twin_d, "same": _canonical(d) == _canonical(twin_d)}
            ctx.twins["ids"] = ([h["hypothesis_id"] for h in d["hypotheses"]] ==
                                [h["hypothesis_id"] for h in twin_d["hypotheses"]])
        result.ctx = ctx
        result.summary = summarize(ctx)
        for key, expected in case.expected.items():
            ok, actual = check_expected(key, expected, result.summary)
            result.contract_total += 1
            result.contract_ok += int(ok)
            if not ok:
                result.failures.append({"case": case.case_id, "key": key, "expected": expected, "actual": actual})
            for family in families_for(key, expected, case):
                result.bump(family, ok)
        derived_quality(ctx, result)
        for name in GATES:
            result.gates[name] = GATE_FUNCS[name](ctx)
        from src.evals.research_engineering_gap.controls import ALL_CONTROLS

        for name in (ALL_CONTROLS if "*" in case.controls else case.controls):
            caught, how = run_control(ctx, name)
            result.controls.append((name, caught, how))
            if caught is not None:
                attempts, accepted = ctx.controls.get(name, (0, 0))
                ctx.controls[name] = (attempts + 1, accepted + (0 if caught else 1))
    except Exception:  # pragma: no cover - surfaced to the reviewer
        result.error = traceback.format_exc()
    return result


def _canonical(d: dict[str, Any]) -> Any:
    """The run without time stamps and without the advisory model-proposed kind."""
    clean = c.strip_times(d)

    def drop(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: drop(v) for k, v in value.items() if k != "model_proposed_kind"}
        if isinstance(value, list):
            return [drop(v) for v in value]
        return value

    return drop(clean)


__all__ = ["CaseResult", "build_upstream", "run_case", "summarize"]
