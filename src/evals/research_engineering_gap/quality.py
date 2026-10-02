"""Quality families re-derived from the run itself (not from authored expectation keys).

Each family reports a real numerator and denominator; a family with no
opportunity is ``None`` (unmeasured), never perfect. The model-judgment families
(semantic linkage, same-span proposition judgment) compare the model's response
with the case's ``truth`` annotations and are REPORTED honestly: a structurally
valid but semantically wrong judgment lowers them, by design."""

from __future__ import annotations

from typing import Any

from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.context import Ctx

MODEL_JUDGMENT_FAMILIES = ("semantic_linkage_accuracy", "same_span_proposition_judgment_accuracy",
                           "limitation_semantic_admissibility_accuracy", "counterevidence_recall_accuracy")


def expected_prior_art_quality(kind: str, capacity: str) -> str:
    if kind in c.INELIGIBLE_KINDS:
        return "INELIGIBLE_METADATA_TEXT"
    return "INELIGIBLE_NON_MATERIAL_CAPACITY" if capacity == "NON_MATERIAL" else "ELIGIBLE"


def derived_quality(ctx: Ctx, result) -> None:
    d = ctx.d
    bump = result.bump
    for h, ref in ctx.all_refs():
        inv = ctx.inv.get((ref["source_kind"], ref["source_record_id"]))
        body = ctx.body(inv) if inv else None
        if ref["role"] == "LIMITATION":
            bump("limitation_anchor_accuracy", body is not None and body[ref["start"]:ref["end"]] == ref["excerpt"])
        if inv is not None:
            if ref["source_kind"] == "PRIOR_ART_TEXT":
                meta = ctx.nd_texts.get(ref["source_record_id"])
                bump("source_quality_handling_accuracy",
                     meta is not None and ref["source_quality"] == expected_prior_art_quality(meta["text_kind"], meta["capacity"]))
            else:
                ex = ctx.run.evidence_extraction
                ev = next((e for e in ex.verified_evidence if str(e.evidence_id) == ref["source_record_id"]), None) if ex else None
                want = "INELIGIBLE_RETRACTED" if ev is not None and ev.is_retracted else "ELIGIBLE"
                bump("source_quality_handling_accuracy", ev is not None and ref["source_quality"] == want)
    for h in d["hypotheses"]:
        bump("hypothesis_posture_accuracy", h["posture"] == c.recompute_posture(ctx, h))
        bump("gap_existence_accuracy", h["existence"] == c.recompute_existence(ctx, h))
        bump("linkage_level_accuracy", h["linkage"] == c.recompute_linkage(ctx, h))
        bump("condition_materiality_accuracy", h["condition_materiality"] == c.recompute_materiality(ctx, h))
        bump("corroboration_accuracy", h["corroboration"] == c.recompute_corroboration(ctx, h))
        bump("counterevidence_scope_effect_accuracy", h["counterevidence_scope_effect"] == c.recompute_scope_effect(h))
        stmt = h["bounded_statement"]
        want_lims = sorted(lim["limitation_id"] for lim in c.linked_limitations(ctx, h))
        want_conds = sorted(cd["condition_id"] for cd in h["conditions"]
                            if set(cd["limitation_ids"]) & set(want_lims))
        bump("bounded_statement_accuracy", stmt["limitation_ids"] == want_lims and stmt["condition_ids"] == want_conds
             and stmt["scope_effect"] == c.recompute_scope_effect(h))
        bump("boundedness_accuracy", h["statement_qualifier"] == stmt["qualifier"] == "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"
             and h["scope"] in ("SINGLE_SOURCE_BOUNDED", "MULTI_SOURCE_BOUNDED", "CANDIDATE_SET_BOUNDED",
                                "REVIEW_SYNTHESIS_BOUNDED", "INSUFFICIENT_SCOPE"))
        for n in h["chronology"]:
            bump("historical_publicity_boundary_accuracy",
                 n["historical_publicity_inferred"] is False and n["legal_prior_art_established"] is False)
            bump("chronology_separation_accuracy", n["bucket"] in ("BEFORE_CUTOFF", "ON_CUTOFF", "AFTER_CUTOFF",
                                                                  "DATE_UNKNOWN", "NO_CUTOFF"))
        for lk in h["project_links"]:
            bump("project_link_binding_accuracy", _link_bound(ctx, h, lk))
        bump("counterevidence_coverage_accuracy", _coverage_ok(ctx, h))
        bump("model_prose_noncanonicality", _no_free_text(h))
    for a in d["claim_assessments"]:
        bump("claim_posture_accuracy", a["posture"] == c.claim_posture(ctx, a["claim_id"]))
    forbidden_keys = c.FORBIDDEN_KEYS["score"] | c.FORBIDDEN_KEYS["legal"]
    for h in d["hypotheses"]:
        bump("legal_boundary_accuracy", not any(k in forbidden_keys for k, _ in c.walk(h))
             and not any(v in c.FORBIDDEN_VALUES for _, v in c.walk(h) if isinstance(v, str)))
    bump("no_new_search_accuracy", d["external_search_calls"] == 0)
    bump("upstream_immutability_accuracy", _upstream_ok(ctx))
    _independence(ctx, bump)
    _model_judgment(ctx, bump)
    if ctx.case.language:
        pass


def _link_bound(ctx: Ctx, h: dict[str, Any], lk: dict[str, Any]) -> bool:
    cid = h["claim_id"]
    inv = ctx.nd_inventory.get(cid)
    feature = next((f for f in (inv or {}).get("features", []) if f["feature_id"] == lk["feature_id"]), None)
    syn = ctx.nd_synthesis.get(cid)
    status = next((x["status"] for x in (syn or {}).get("feature_differentiations", [])
                   if x["feature_id"] == lk["feature_id"]), None)
    return (lk["claim_id"] == cid and lk["limitation_id"] in {x["limitation_id"] for x in h["limitations"]}
            and feature is not None and c.digest(feature["text"]) == lk["feature_text_hash"]
            and lk["claim_text_hash"] == c.digest(ctx.claims[cid]) and lk["nd_run_id"] == ctx.d["nd_run_id"]
            and status == lk["inherited_differentiation_status"])


def _coverage_ok(ctx: Ctx, h: dict[str, Any]) -> bool:
    cov = ctx.coverage.get(h["claim_id"])
    visible = {t["inventory_text_id"] for t in ctx.d["inventory_texts"]
               if not t["linked_claim_ids"] or h["claim_id"] in t["linked_claim_ids"]}
    return (cov is not None and set(cov["examined_text_ids"]) | set(cov["omitted_text_ids"]) == visible
            and h["counterevidence_review_complete"] == (not cov["omitted_text_ids"]))


def _no_free_text(h: dict[str, Any]) -> bool:
    """Every string on a canonical record is a source slice, an enum, an id or a pinned constant."""
    for key, value in c.walk(h):
        if isinstance(value, str) and key not in c.ALLOWED_STRING_FIELDS and not _looks_structural(value):
            return False
    return True


def _looks_structural(value: str) -> bool:
    return value.isupper() or value.replace("-", "").replace(":", "").replace("_", "").replace(".", "").isalnum() \
        or value.startswith(("family:", "network:", "entity:", "publication:", "singleton:", "source:", "doi:", "correlation:"))


def _upstream_ok(ctx: Ctx) -> bool:
    from src.evals.research_engineering_gap.runner import upstream_identical

    return upstream_identical(ctx)


def _independence(ctx: Ctx, bump) -> None:
    run = ctx.run
    ex = run.evidence_extraction
    grouped = {e for g in (run.claim_sufficiency.independence_groups if run.claim_sufficiency else [])
               for e in g.member_evidence_ids}
    patent = {str(p.candidate_id): p for p in (run.patent_prior_art.candidates if run.patent_prior_art else [])}
    oss = {str(p.candidate_id): p for p in (run.open_source_prior_art.candidates if run.open_source_prior_art else [])}
    networks = {n.network_id: n for n in (run.open_source_prior_art.networks if run.open_source_prior_art else [])}
    for inv in ctx.d["inventory_texts"]:
        if inv["source_kind"] == "ACADEMIC_EVIDENCE":
            ev = next((e for e in ex.verified_evidence if str(e.evidence_id) == inv["source_record_id"]), None) if ex else None
            bump("academic_independence_accuracy", ev is not None and inv["counts_as_independent"] == (ev.evidence_id in grouped))
            continue
        cid = inv["candidate_id"]
        unit = inv["inherited_unit"]
        if unit["candidate_type"] == "PATENT" and cid in patent:
            cand = patent[cid]
            want = cand.family_status.value in ("VERIFIED_FAMILY", "SINGLETON_FAMILY")
            bump("patent_independence_accuracy", inv["counts_as_independent"] == want)
        elif unit["candidate_type"] == "OPEN_SOURCE" and cid in oss:
            cand = oss[cid]
            net = networks.get(cand.network_id)
            want = bool(net and net.independent_root and cand.counts_as_independent_root)
            bump("oss_independence_accuracy", inv["counts_as_independent"] == want)
        elif unit["candidate_type"] == "PRODUCT":
            bump("product_independence_accuracy", inv["counts_as_independent"] is True)


def _model_judgment(ctx: Ctx, bump) -> None:
    truth = ctx.case.truth
    for cid, per in (truth.get("links") or {}).items():
        h = ctx.hyps.get(cid)
        stored = {}
        if h:
            lim_text = {lim["limitation_id"]: [r["excerpt"] for r in ctx.lim_refs(h, lim)] for lim in h["limitations"]}
            for lk in h["project_links"]:
                for ex in lim_text.get(lk["limitation_id"], []):
                    stored[ex] = lk["relation"]
        # The semantic accuracy of the judgments the model produced AND the system stored. A judgment the
        # system refused (a leak, a forbidden conclusion) or never asked for is not a semantic judgment.
        for excerpt, relation in per.items():
            if excerpt in stored:
                bump("semantic_linkage_accuracy", stored[excerpt] == relation)
    for cid, spec in (truth.get("propositions") or {}).items():
        h = ctx.hyps.get(cid)
        n = len(h["limitations"]) if h else 0
        bump("same_span_proposition_judgment_accuracy", n == spec["distinct"])
    for cid, excerpts in (truth.get("counter") or {}).items():
        h = ctx.hyps.get(cid)
        recorded = {r["excerpt"] for r in (h["evidence_refs"] if h else []) if r["role"] == "COUNTEREVIDENCE"}
        for excerpt in excerpts:
            bump("counterevidence_recall_accuracy", excerpt in recorded)
    for cid, excerpts in (truth.get("inadmissible") or {}).items():
        h = ctx.hyps.get(cid)
        accepted = {r["excerpt"] for lim in (h["limitations"] if h else []) for r in ctx.lim_refs(h, lim)}
        for excerpt in excerpts:
            bump("limitation_semantic_admissibility_accuracy", excerpt not in accepted)


__all__ = ["MODEL_JUDGMENT_FAMILIES", "derived_quality"]
