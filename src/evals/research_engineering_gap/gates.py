"""Phase 2J release-blocking gates.

Every gate returns ``(violations, opportunities)`` for ONE case and is evaluated
from the serialized run and the upstream records, never through the Phase 2J
validators. Opportunities are real: the count of situations in the case that
could violate THIS invariant. There is no synthetic denominator floor, a case with no
opportunity adds zero, and a gate's denominator is counted from the case's own
facts, so overlap with any quality family cannot change it.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.context import Ctx

GATE_FUNCS: dict[str, Callable[[Ctx], tuple[int, int]]] = {}
GATES: list[str] = []


def gate(name: str):
    def register(fn):
        assert name not in GATE_FUNCS, name
        GATE_FUNCS[name] = fn
        GATES.append(name)
        return fn

    return register


def _count(items, opp, viol) -> tuple[int, int]:
    opportunities = violations = 0
    for item in items:
        if opp(item):
            opportunities += 1
            violations += int(bool(viol(item)))
    return violations, opportunities


def _refs(ctx: Ctx, role: str | None = None):
    return [(h, r) for h, r in ctx.all_refs() if role is None or r["role"] == role]


def _inv(ctx: Ctx, ref: dict[str, Any]) -> dict[str, Any] | None:
    return ctx.inv.get((ref["source_kind"], ref["source_record_id"]))


def _body(ctx: Ctx, ref: dict[str, Any]) -> str | None:
    inv = _inv(ctx, ref)
    return ctx.body(inv) if inv else None


def _hyps(ctx: Ctx):
    return list(ctx.d["hypotheses"])


def _accepted_excerpts(ctx: Ctx, cid: str, role: str | None = None) -> set[str]:
    h = ctx.hyps.get(cid)
    return {r["excerpt"] for r in (h["evidence_refs"] if h else []) if role is None or r["role"] == role}


def _limitation_excerpts(ctx: Ctx, cid: str) -> set[str]:
    h = ctx.hyps.get(cid)
    return {r["excerpt"] for lim in (h["limitations"] if h else []) for r in ctx.lim_refs(h, lim)}


# ---------------------------------------------------------------------------
# Provenance and anchors
# ---------------------------------------------------------------------------


@gate("excerpt_not_source_slice")
def g_slice(ctx):
    return _count(_refs(ctx), lambda x: True,
                  lambda x: (b := _body(ctx, x[1])) is None or b[x[1]["start"]:x[1]["end"]] != x[1]["excerpt"])


@gate("excerpt_offsets_invalid")
def g_offsets(ctx):
    def bad(x):
        r = x[1]
        b = _body(ctx, r)
        return b is None or not (0 <= r["start"] < r["end"] <= len(b)) or r["end"] - r["start"] != len(r["excerpt"])

    return _count(_refs(ctx), lambda x: True, bad)


@gate("repeated_excerpt_first_occurrence_guess")
def g_repeat(ctx):
    def occurrences(x):
        r = x[1]
        inv = _inv(ctx, r)
        b = ctx.body(inv) if inv else None
        return 0 if not b else b[inv["span_start"]:inv["span_end"]].count(r["excerpt"])

    return _count(_refs(ctx), lambda x: occurrences(x) > 1, lambda x: x[1]["occurrence_resolution"] == "UNIQUE_IN_TEXT")


@gate("excerpt_text_hash_mismatch")
def g_hash(ctx):
    return _count(_refs(ctx), lambda x: True,
                  lambda x: (b := _body(ctx, x[1])) is None or c.digest(b) != x[1]["text_hash"])


@gate("excerpt_outside_inventory_span")
def g_span(ctx):
    return _count(_refs(ctx), lambda x: _inv(ctx, x[1]) is not None,
                  lambda x: not (_inv(ctx, x[1])["span_start"] <= x[1]["start"] and x[1]["end"] <= _inv(ctx, x[1])["span_end"]))


@gate("excerpt_from_text_not_visible_to_claim")
def g_visible(ctx):
    return _count(_refs(ctx), lambda x: _inv(ctx, x[1]) is not None,
                  lambda x: bool(_inv(ctx, x[1])["linked_claim_ids"]) and x[0]["claim_id"] not in _inv(ctx, x[1])["linked_claim_ids"])


@gate("excerpt_outside_inventory")
def g_outside(ctx):
    return _count(_refs(ctx), lambda x: True, lambda x: _inv(ctx, x[1]) is None)


@gate("excerpt_id_not_registered")
def g_registered(ctx):
    ids = set(ctx.d["eligible_evidence_ref_ids"])
    return _count(_refs(ctx), lambda x: True, lambda x: x[1]["evidence_ref_id"] not in ids)


@gate("inherited_independence_rewritten")
def g_inherit(ctx):
    names = ("independence_basis", "independence_key", "counts_as_independent", "correlation_group_key",
             "inherited_unit", "is_review_source", "source_quality", "candidate_id", "text_kind")
    return _count(_refs(ctx), lambda x: _inv(ctx, x[1]) is not None,
                  lambda x: any(x[1][n] != _inv(ctx, x[1])[n] for n in names))


@gate("validation_anchor_not_a_slice")
def g_anchor(ctx):
    items = []
    for h in _hyps(ctx):
        req = h["validation_requirement"]
        if req:
            items += [(h, a) for a in (req["metric"], req["baseline"]) if a]

    def bad(x):
        h, a = x
        if a["origin"] == "STUDENT_CLAIM_TEXT":
            return ctx.claims[h["claim_id"]][a["start"]:a["end"]] != a["text"] or a["claim_id"] != h["claim_id"]
        ref = ctx.refs_by_id(h).get(a["evidence_ref_id"])
        return ref is None or ref["excerpt"][a["start"] - ref["start"]:a["end"] - ref["start"]] != a["text"]

    return _count(items, lambda x: True, bad)


def _all_inventory_text(ctx: Ctx) -> str:
    return "\n".join(ctx.all_bodies())


def _targeted_bodies(ctx: Ctx, p: dict[str, Any]) -> list[str]:
    """The inventory texts a proposal actually pointed at (its ``in`` kind), not every text."""
    want = p.get("in")
    out = []
    for inv in ctx.inv.values():
        kind = inv["text_kind"] or "ACADEMIC_EXCERPT"
        if want is None or kind == want:
            body = ctx.body(inv)
            if body:
                out.append(body[inv["span_start"]:inv["span_end"]])
    return out


@gate("student_claim_text_accepted_as_evidence")
def g_student(ctx):
    items = []
    for cid, claim in ctx.claims.items():
        for p in ctx.proposals(cid, "limitations") + ctx.proposals(cid, "capabilities"):
            ex = p.get("excerpt", "")
            if ex and ex in claim and not any(ex in body for body in _targeted_bodies(ctx, p)):
                items.append((cid, ex))
    return _count(items, lambda x: True, lambda x: x[1] in _accepted_excerpts(ctx, x[0]))


@gate("fabricated_excerpt_accepted")
def g_fabricated(ctx):
    items = []
    text = _all_inventory_text(ctx)
    for cid in ctx.claims:
        for kind in ("limitations", "capabilities", "conditions", "counter"):
            for p in ctx.proposals(cid, kind):
                ex = p.get("excerpt", "")
                if ex and "token" not in p and ex not in text and ex not in ctx.claims[cid]:
                    items.append((cid, ex))
    return _count(items, lambda x: True, lambda x: x[1] in _accepted_excerpts(ctx, x[0]))


@gate("fabricated_text_reference_accepted")
def g_fab_ref(ctx):
    items = [(cid, p["excerpt"]) for cid in ctx.claims for kind in ("limitations", "capabilities", "counter")
             for p in ctx.proposals(cid, kind) if p.get("token") == "T99"]
    return _count(items, lambda x: True, lambda x: x[1] in _accepted_excerpts(ctx, x[0]))


# ---------------------------------------------------------------------------
# Limitation admissibility
# ---------------------------------------------------------------------------


def _proposals_of_type(ctx: Ctx, predicate):
    return [(cid, p) for cid in ctx.claims for p in ctx.proposals(cid, "limitations") if predicate(p)]


def _basis_gate(basis: str):
    def fn(ctx):
        return _count(_proposals_of_type(ctx, lambda p: p.get("type") == basis), lambda x: True,
                      lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))

    gate(f"absence_basis_accepted_{basis.lower()}")(fn)


for _basis in c.ABSENCE_BASES:
    _basis_gate(_basis)


@gate("invalid_limitation_type_accepted")
def g_bad_type(ctx):
    ok = set(c.LIMITATION_TYPES) | set(c.ABSENCE_BASES)
    return _count(_proposals_of_type(ctx, lambda p: p.get("type") not in ok), lambda x: True,
                  lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


@gate("invalid_facet_accepted")
def g_bad_facet(ctx):
    return _count(_proposals_of_type(ctx, lambda p: p.get("facet") not in ("RESEARCH", "ENGINEERING")), lambda x: True,
                  lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


def _facet_ok(p: dict[str, Any]) -> bool:
    table = c.RESEARCH_TYPES if p.get("facet") == "RESEARCH" else c.ENGINEERING_TYPES
    return p.get("type") in table


@gate("facet_type_mismatch_accepted")
def g_facet_type(ctx):
    return _count(_proposals_of_type(ctx, lambda p: p.get("type") in c.LIMITATION_TYPES
                                     and p.get("facet") in ("RESEARCH", "ENGINEERING") and not _facet_ok(p)),
                  lambda x: True, lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


@gate("scope_restriction_without_dimension_accepted")
def g_scope(ctx):
    return _count(_proposals_of_type(ctx, lambda p: p.get("type") == "SCOPE_RESTRICTION" and not p.get("dimensions")),
                  lambda x: True, lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


@gate("measured_shortfall_without_number_accepted")
def g_number(ctx):
    return _count(_proposals_of_type(ctx, lambda p: p.get("type") == "MEASURED_SHORTFALL"
                                     and not any(ch.isdigit() for ch in p["excerpt"])),
                  lambda x: True, lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


@gate("measured_shortfall_number_outside_excerpt_accepted")
def g_number_outside(ctx):
    text = _all_inventory_text(ctx)
    return _count(_proposals_of_type(ctx, lambda p: p.get("type") == "MEASURED_SHORTFALL"
                                     and not any(ch.isdigit() for ch in p["excerpt"]) and p["excerpt"] in text
                                     and any(ch.isdigit() for ch in text)),
                  lambda x: True, lambda x: x[1]["excerpt"] in _limitation_excerpts(ctx, x[0]))


def _kind_eligible_gate(name: str, kinds: set[str]):
    def fn(ctx):
        return _count(_refs(ctx, "LIMITATION"), lambda x: x[1]["text_kind"] in kinds,
                      lambda x: x[1]["source_quality"] == "ELIGIBLE")

    gate(name)(fn)


_kind_eligible_gate("title_limitation_eligible", c.TITLE_KINDS)
_kind_eligible_gate("manifest_limitation_eligible", {"OSS_MANIFEST"})
_kind_eligible_gate("repo_metadata_limitation_eligible", c.REPO_METADATA_KINDS)


@gate("non_material_text_limitation_eligible")
def g_nonmaterial(ctx):
    def capacity(r):
        meta = ctx.nd_texts.get(r["source_record_id"])
        return meta["capacity"] if meta else None

    return _count(_refs(ctx, "LIMITATION"), lambda x: capacity(x[1]) == "NON_MATERIAL",
                  lambda x: x[1]["source_quality"] == "ELIGIBLE")


@gate("retracted_limitation_eligible")
def g_retracted(ctx):
    ex = ctx.run.evidence_extraction
    retracted = {str(e.evidence_id) for e in (ex.verified_evidence if ex else []) if e.is_retracted}
    return _count(_refs(ctx, "LIMITATION"), lambda x: x[1]["source_record_id"] in retracted,
                  lambda x: x[1]["source_quality"] == "ELIGIBLE")


@gate("ineligible_only_limitation_not_blocked")
def g_blocked(ctx):
    return _count(_hyps(ctx), lambda h: bool(h["limitations"]) and not c.eligible_limitations(ctx, h),
                  lambda h: h["existence"] != "LIMITATION_BLOCKED_SOURCE_QUALITY" or h["posture"] != "BLOCKED_SOURCE_QUALITY")


@gate("duplicate_proposition_accepted")
def g_dup_prop(ctx):
    def keys(h):
        by = ctx.refs_by_id(h)
        return [(lim["limitation_type"], frozenset((by[i]["source_record_id"], by[i]["start"], by[i]["end"])
                                                   for i in lim["evidence_ref_ids"])) for lim in h["limitations"]]

    return _count(_hyps(ctx), lambda h: len(h["limitations"]) >= 1, lambda h: len(set(keys(h))) != len(keys(h)))


# ---------------------------------------------------------------------------
# Existence / differentiation
# ---------------------------------------------------------------------------


@gate("differentiation_promoted_to_gap")
def g_diff(ctx):
    def eligible_none(cid):
        h = ctx.hyps.get(cid)
        return ctx.assess[cid]["inputs_bound"] and ctx.assess[cid]["has_differentiating_feature"] and not (
            h and c.eligible_limitations(ctx, h))

    return _count(list(ctx.claims), eligible_none,
                  lambda cid: ctx.assess[cid]["posture"] not in ("DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
                                                                 "BLOCKED_SOURCE_QUALITY"))


@gate("no_limitation_promoted_to_gap")
def g_nolim(ctx):
    def none(cid):
        h = ctx.hyps.get(cid)
        return ctx.assess[cid]["inputs_bound"] and not (h and c.eligible_limitations(ctx, h))

    return _count(list(ctx.claims), none, lambda cid: ctx.assess[cid]["posture"] in (
        "SUPPORTED_WITHIN_BOUNDS", "PARTIALLY_SUPPORTED", "COUNTEREVIDENCE_WEAKENS_GAP"))


@gate("gap_existence_misderived")
def g_exist(ctx):
    return _count(_hyps(ctx), lambda h: True, lambda h: h["existence"] != c.recompute_existence(ctx, h))


# ---------------------------------------------------------------------------
# Project-gap linkage
# ---------------------------------------------------------------------------


@gate("structural_linkage_inferred")
def g_struct(ctx):
    return _count(_hyps(ctx), lambda h: bool(c.eligible_limitations(ctx, h)) and not h["project_links"],
                  lambda h: h["linkage"] != "NONE_MATERIAL" or h["posture"] in (
                      "SUPPORTED_WITHIN_BOUNDS", "PARTIALLY_SUPPORTED", "COUNTEREVIDENCE_WEAKENS_GAP"))


def _relation_gate(relation: str):
    def fn(ctx):
        return _count(_hyps(ctx), lambda h: any(lk["relation"] == relation for lk in h["project_links"]),
                      lambda h: h["linkage"] != c.recompute_linkage(ctx, h))

    gate(f"{relation.lower()}_counted_as_addressing")(fn)


for _relation in ("UNRELATED", "RELEVANT_BUT_NOT_ADDRESSING", "INSUFFICIENT_LINKAGE_EVIDENCE"):
    _relation_gate(_relation)


@gate("partial_linkage_promoted_to_supported")
def g_partial(ctx):
    return _count(_hyps(ctx), lambda h: c.recompute_linkage(ctx, h) == "PARTIAL",
                  lambda h: h["posture"] == "SUPPORTED_WITHIN_BOUNDS")


@gate("no_material_link_supported_or_partial")
def g_nolink(ctx):
    return _count(_hyps(ctx), lambda h: bool(c.eligible_limitations(ctx, h)) and c.recompute_linkage(ctx, h) == "NONE_MATERIAL",
                  lambda h: h["posture"] in ("SUPPORTED_WITHIN_BOUNDS", "PARTIALLY_SUPPORTED",
                                             "COUNTEREVIDENCE_WEAKENS_GAP"))


@gate("linkage_level_misderived")
def g_level(ctx):
    return _count(_hyps(ctx), lambda h: True, lambda h: h["linkage"] != c.recompute_linkage(ctx, h))


def _links(ctx: Ctx):
    return [(h, lk) for h in _hyps(ctx) for lk in h["project_links"]]


@gate("link_cross_claim_accepted")
def g_xclaim(ctx):
    return _count(_links(ctx), lambda x: True, lambda x: x[1]["claim_id"] != x[0]["claim_id"])


@gate("link_unknown_limitation_accepted")
def g_unk_lim(ctx):
    return _count(_links(ctx), lambda x: True,
                  lambda x: x[1]["limitation_id"] not in {lim["limitation_id"] for lim in x[0]["limitations"]})


@gate("link_feature_unbound_accepted")
def g_feature(ctx):
    def bad(x):
        h, lk = x
        inv = ctx.nd_inventory.get(h["claim_id"], {})
        feature = next((f for f in inv.get("features", []) if f["feature_id"] == lk["feature_id"]), None)
        return feature is None or c.digest(feature["text"]) != lk["feature_text_hash"] or \
            lk["claim_text_hash"] != c.digest(ctx.claims[h["claim_id"]])

    return _count(_links(ctx), lambda x: True, bad)


@gate("link_foreign_run_accepted")
def g_foreign(ctx):
    return _count(_links(ctx), lambda x: True, lambda x: x[1]["nd_run_id"] != ctx.nd.get("nd_run_id"))


@gate("link_status_not_inherited")
def g_status(ctx):
    def bad(x):
        h, lk = x
        syn = ctx.nd_synthesis.get(h["claim_id"], {})
        status = next((f["status"] for f in syn.get("feature_differentiations", []) if f["feature_id"] == lk["feature_id"]), None)
        derived = "DIFFERENTIATING_FEATURE" if status in c.DIFFERENTIATING else (
            "FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE" if status == "DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES"
            else "FEATURE_DIFFERENTIATION_UNRESOLVED")
        return status != lk["inherited_differentiation_status"] or lk["status"] != derived

    return _count(_links(ctx), lambda x: True, bad)


@gate("duplicate_link_judgment_accepted")
def g_dup_link(ctx):
    items = []
    for cid in ctx.claims:
        seen: dict[tuple, int] = {}
        for p in ctx.proposals(cid, "links"):
            key = (p.get("feature"), p.get("limitation"))
            seen[key] = seen.get(key, 0) + 1
        items += [(cid, k) for k, n in seen.items() if n > 1]

    def bad(x):
        h = ctx.hyps.get(x[0])
        return bool(h) and sum(1 for lk in h["project_links"]) > len({(lk["feature_id"], lk["limitation_id"]) for lk in h["project_links"]})

    return _count(items, lambda x: True, bad)


@gate("link_for_unasked_pair_accepted")
def g_unasked(ctx):
    items = [cid for cid in ctx.claims if any(p.get("unasked") for p in ctx.proposals(cid, "links"))]

    def bad(cid):
        h = ctx.hyps.get(cid)
        stored = len(h["project_links"]) if h else 0
        valid = len({(p["feature"], p["limitation"]) for p in ctx.proposals(cid, "links")
                     if not p.get("unasked") and p.get("relation") in c.RELATIONS})
        return stored > valid

    return _count(items, lambda cid: True, bad)


@gate("invalid_relation_accepted")
def g_bad_relation(ctx):
    return _count(_links(ctx), lambda x: True, lambda x: x[1]["relation"] not in c.RELATIONS)


# ---------------------------------------------------------------------------
# Existing capability
# ---------------------------------------------------------------------------


@gate("supported_without_capability")
def g_nocap(ctx):
    return _count(_hyps(ctx), lambda h: not h["existing_capabilities"], lambda h: h["posture"] == "SUPPORTED_WITHIN_BOUNDS")


@gate("capability_from_ineligible_source")
def g_cap_inelig(ctx):
    return _count(_refs(ctx, "EXISTING_CAPABILITY"), lambda x: True, lambda x: x[1]["source_quality"] != "ELIGIBLE")


@gate("capability_inferred_from_metadata")
def g_cap_meta(ctx):
    items = []
    for cid in ctx.claims:
        for p in ctx.proposals(cid, "capabilities"):
            if p.get("in") in c.INELIGIBLE_KINDS:
                items.append((cid, p["excerpt"]))
    return _count(items, lambda x: True, lambda x: x[1] in _accepted_excerpts(ctx, x[0], "EXISTING_CAPABILITY"))


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


@gate("supported_with_missing_material_condition")
def g_cond_missing(ctx):
    return _count(_hyps(ctx), lambda h: "MATERIAL_CONDITION" in c.recompute_missing(ctx, h),
                  lambda h: h["posture"] == "SUPPORTED_WITHIN_BOUNDS")


@gate("synthetic_condition_introduced")
def g_synth_cond(ctx):
    items = [(h, cd) for h in _hyps(ctx) for cd in h["conditions"]]

    def bad(x):
        h, cd = x
        refs = ctx.refs_by_id(h)
        proposed = {p["excerpt"] for p in ctx.proposals(h["claim_id"], "conditions")}
        return not all(refs[i]["excerpt"] in proposed for i in cd["evidence_ref_ids"])

    return _count(items, lambda x: True, bad)


@gate("condition_materiality_misderived")
def g_materiality(ctx):
    return _count(_hyps(ctx), lambda h: bool(c.eligible_limitations(ctx, h)),
                  lambda h: h["condition_materiality"] != c.recompute_materiality(ctx, h))


@gate("unconditional_condition_requirement")
def g_uncond(ctx):
    def opp(x):
        h, lim = x
        return not lim["condition_dimensions"] and not c.narrowed(h)

    items = [(h, lim) for h in _hyps(ctx) for lim in c.eligible_limitations(ctx, h)]
    return _count(items, opp, lambda x: x[0]["condition_materiality"].get(x[1]["limitation_id"]) != "CONDITION_NOT_MATERIAL")


@gate("condition_not_anchored_to_eligible_condition_text")
def g_cond_anchor(ctx):
    items = [(h, cd) for h in _hyps(ctx) for cd in h["conditions"]]
    return _count(items, lambda x: True, lambda x: any(
        ctx.refs_by_id(x[0]).get(i, {}).get("role") != "CONDITION" or
        ctx.refs_by_id(x[0]).get(i, {}).get("source_quality") != "ELIGIBLE" for i in x[1]["evidence_ref_ids"]))


# ---------------------------------------------------------------------------
# What SUPPORTED_WITHIN_BOUNDS requires, and derivation integrity
# ---------------------------------------------------------------------------


def _supported_gate(name: str, condition: Callable[[Ctx, dict[str, Any]], bool]):
    def fn(ctx):
        return _count(_hyps(ctx), lambda h: condition(ctx, h), lambda h: h["posture"] == "SUPPORTED_WITHIN_BOUNDS")

    gate(name)(fn)


_supported_gate("supported_without_eligible_limitation", lambda ctx, h: not c.eligible_limitations(ctx, h))
_supported_gate("supported_without_validation_requirement", lambda ctx, h: h["validation_requirement"] is None)
_supported_gate("supported_with_incomplete_counterevidence_review", lambda ctx, h: not _complete(ctx, h))
_supported_gate("supported_with_material_counterevidence", lambda ctx, h: c.material_counter(h))
_supported_gate("supported_with_unresolved_gap_kind", lambda ctx, h: c.recompute_kind(ctx, h) == "UNRESOLVED")


def _complete(ctx: Ctx, h: dict[str, Any]) -> bool:
    cov = ctx.coverage.get(h["claim_id"])
    return bool(cov) and not cov["omitted_text_ids"]


@gate("hypothesis_posture_misderived")
def g_posture(ctx):
    return _count(_hyps(ctx), lambda h: True, lambda h: h["posture"] != c.recompute_posture(ctx, h))


@gate("claim_posture_misderived")
def g_claim_posture(ctx):
    return _count(list(ctx.claims), lambda cid: True, lambda cid: ctx.assess[cid]["posture"] != c.claim_posture(ctx, cid))


# ---------------------------------------------------------------------------
# Independence and corroboration
# ---------------------------------------------------------------------------


def _upstream_patent(ctx: Ctx, ref_or_inv: dict[str, Any]):
    return next((p for p in (ctx.run.patent_prior_art.candidates if ctx.run.patent_prior_art else [])
                 if str(p.candidate_id) == ref_or_inv.get("candidate_id")), None)


@gate("unresolved_patent_family_counted_independent")
def g_unres(ctx):
    def unresolved(t):
        p = _upstream_patent(ctx, t)
        return t["source_kind"] == "PRIOR_ART_TEXT" and p is not None and p.family_status.value not in (
            "VERIFIED_FAMILY", "SINGLETON_FAMILY")

    return _count(ctx.d["inventory_texts"], unresolved, lambda t: t["counts_as_independent"])


@gate("patent_family_publications_multiplied")
def g_family_mult(ctx):
    def opp(h):
        fams = [_upstream_patent(ctx, r) for lim in c.eligible_limitations(ctx, h) for r in ctx.lim_refs(h, lim)]
        keyed = [p.family_group_id for p in fams if p is not None and p.family_status.value == "VERIFIED_FAMILY"]
        return len(keyed) >= 2 and len(set(keyed)) < len(keyed)

    def bad(h):
        refs = [r for lim in c.eligible_limitations(ctx, h) for r in ctx.lim_refs(h, lim)]
        fam_ids = {str(_upstream_patent(ctx, r).family_group_id) for r in refs
                   if _upstream_patent(ctx, r) and _upstream_patent(ctx, r).family_status.value == "VERIFIED_FAMILY"}
        other = {r["independence_key"] for r in refs if not (_upstream_patent(ctx, r) and
                 _upstream_patent(ctx, r).family_status.value == "VERIFIED_FAMILY") and r["counts_as_independent"]}
        return len(units_from(ctx, h)) > len(fam_ids) + len(other)

    return _count(_hyps(ctx), opp, bad)


def units_from(ctx: Ctx, h: dict[str, Any]):
    refs = [r for lim in c.eligible_limitations(ctx, h) for r in ctx.lim_refs(h, lim) if r["source_quality"] == "ELIGIBLE"]
    return c.units_of(ctx, refs)


def _is_corr(ctx: Ctx, h: dict[str, Any]) -> bool:
    refs = [r for lim in c.eligible_limitations(ctx, h) for r in ctx.lim_refs(h, lim)]
    groups = [r["correlation_group_key"] for r in refs if r["correlation_group_key"]]
    return len(groups) >= 2 and len(set(groups)) < len(groups)


@gate("product_correlation_inflated")
def g_corr(ctx):
    return _count(_hyps(ctx), lambda h: _is_corr(ctx, h),
                  lambda h: h["corroboration"] in ("MULTI_SOURCE_CORROBORATED", "MIXED_SOURCE_CORROBORATED")
                  and len(units_from(ctx, h)) < 2)


def _oss_relation(ctx: Ctx, t: dict[str, Any]) -> str | None:
    cand = next((p for p in (ctx.run.open_source_prior_art.candidates if ctx.run.open_source_prior_art else [])
                 if str(p.candidate_id) == t.get("candidate_id")), None)
    return cand.relationship.value if cand else None


def _oss_gate(name: str, relations: set[str]):
    def fn(ctx):
        return _count(ctx.d["inventory_texts"], lambda t: t["source_kind"] == "PRIOR_ART_TEXT"
                      and _oss_relation(ctx, t) in relations, lambda t: t["counts_as_independent"])

    gate(name)(fn)


_oss_gate("oss_fork_counted_independent", {"FORK"})
_oss_gate("oss_mirror_counted_independent", {"MIRROR"})
_oss_gate("oss_template_counted_independent", {"TEMPLATE_DERIVATIVE"})


@gate("academic_ungrouped_counted_independent")
def g_acad(ctx):
    grouped = {e for g in (ctx.run.claim_sufficiency.independence_groups if ctx.run.claim_sufficiency else [])
               for e in g.member_evidence_ids}
    return _count(ctx.d["inventory_texts"], lambda t: t["source_kind"] == "ACADEMIC_EVIDENCE"
                  and not any(str(e) == t["source_record_id"] for e in grouped), lambda t: t["counts_as_independent"])


@gate("shared_source_double_counted")
def g_shared(ctx):
    def opp(h):
        per_text: dict[str, int] = {}
        for lim in c.eligible_limitations(ctx, h):
            for r in ctx.lim_refs(h, lim):
                per_text[r["source_record_id"]] = per_text.get(r["source_record_id"], 0) + 1
        return any(n >= 2 for n in per_text.values())

    return _count(_hyps(ctx), opp, lambda h: h["corroboration"] in ("MULTI_SOURCE_CORROBORATED", "MIXED_SOURCE_CORROBORATED")
                  and len(units_from(ctx, h)) < 2)


@gate("corroboration_misderived")
def g_corroboration(ctx):
    return _count(_hyps(ctx), lambda h: True, lambda h: h["corroboration"] != c.recompute_corroboration(ctx, h))


@gate("phase2e_absence_made_insufficient")
def g_2e(ctx):
    legit = {"MODEL_PROVIDER_MISSING", "MODEL_CALL_FAILED", "CLAIM_NOT_IN_PHASE_2I", "NO_FEATURE_INVENTORY",
             "NO_PHASE_2I_SYNTHESIS", "CLAIM_TEXT_HASH_MISMATCH", "MODEL_CALL_BOUND_REACHED", "NO_PHASE_2I_RUN",
             "PHASE_2I_NOT_COMPLETED"}
    return _count(list(ctx.claims), lambda cid: ctx.run.claim_sufficiency is None,
                  lambda cid: ctx.assess[cid]["posture"] == "INSUFFICIENT_INPUT"
                  and not set(ctx.assess[cid]["insufficient_reasons"]) & legit)


# ---------------------------------------------------------------------------
# HYBRID and kind
# ---------------------------------------------------------------------------


@gate("hybrid_without_two_linked_facets")
def g_hybrid_facets(ctx):
    def bad(h):
        linked = c.linked_limitations(ctx, h)
        return not ({lim["facet"] for lim in linked} >= {"RESEARCH", "ENGINEERING"})

    return _count(_hyps(ctx), lambda h: h["kind"] == "HYBRID", bad)


@gate("hybrid_from_duplicated_limitation")
def g_hybrid_dup(ctx):
    def bad(h):
        by = ctx.refs_by_id(h)
        spans = [(lim["limitation_type"], frozenset((by[i]["source_record_id"], by[i]["start"], by[i]["end"])
                                                    for i in lim["evidence_ref_ids"])) for lim in h["limitations"]]
        ids = [lim["limitation_id"] for lim in h["limitations"]]
        return len(set(spans)) != len(spans) or len(set(ids)) != len(ids)

    return _count(_hyps(ctx), lambda h: h["kind"] == "HYBRID", bad)


@gate("hybrid_with_one_side_unlinked")
def g_hybrid_unlinked(ctx):
    def opp(h):
        facets = {lim["facet"] for lim in c.eligible_limitations(ctx, h)}
        return facets >= {"RESEARCH", "ENGINEERING"} and not {l["facet"] for l in c.linked_limitations(ctx, h)} >= facets

    return _count(_hyps(ctx), opp, lambda h: h["kind"] == "HYBRID")


@gate("gap_kind_misderived")
def g_kind(ctx):
    return _count(_hyps(ctx), lambda h: True, lambda h: h["kind"] != c.recompute_kind(ctx, h))


@gate("model_proposed_kind_trusted")
def g_proposed_kind(ctx):
    return _count(_hyps(ctx), lambda h: h["model_proposed_kind"] is not None and h["model_proposed_kind"] != c.recompute_kind(ctx, h),
                  lambda h: h["kind"] == h["model_proposed_kind"])


# ---------------------------------------------------------------------------
# Counterevidence
# ---------------------------------------------------------------------------


@gate("counterevidence_coverage_not_accounted")
def g_coverage(ctx):
    def bad(h):
        cov = ctx.coverage.get(h["claim_id"])
        visible = {t["inventory_text_id"] for t in ctx.d["inventory_texts"]
                   if not t["linked_claim_ids"] or h["claim_id"] in t["linked_claim_ids"]}
        return cov is None or set(cov["examined_text_ids"]) | set(cov["omitted_text_ids"]) != visible \
            or h["counterevidence_review_complete"] != (not cov["omitted_text_ids"])

    return _count(_hyps(ctx), lambda h: True, bad)


def _valid_counter(ctx: Ctx, cid: str, p: dict[str, Any]) -> bool:
    """A counterevidence proposal production MUST record: valid enums, a real excerpt in an ELIGIBLE text
    the proposal pointed at, not the limitation's own span, and no prose production must refuse."""
    kinds = {"LIMITATION_ADDRESSED", "LIMITATION_NOT_PRESENT", "DIFFERENTIATION_UNRELATED"}
    matches_ = {"SAME_CONDITION", "DIFFERENT_CONDITION", "CONDITION_UNKNOWN"}
    if p.get("kind") not in kinds or p.get("condition_match") not in matches_ or "token" in p:
        return False
    if p.get("leak_system_prompt") or p.get("rationale"):
        return False
    ex = p["excerpt"]
    if ex in _limitation_excerpts(ctx, cid):
        return False
    for inv in ctx.d["inventory_texts"]:
        kind = inv["text_kind"] or "ACADEMIC_EXCERPT"
        if p.get("in") is not None and kind != p["in"]:
            continue
        body = ctx.body(inv)
        if not body or inv["source_quality"] != "ELIGIBLE":
            continue
        region = body[inv["span_start"]:inv["span_end"]]
        if region.count(ex) == 1 and (not inv["linked_claim_ids"] or cid in inv["linked_claim_ids"]):
            return True
    return False


def _counter_gate(name: str, match: str):
    def fn(ctx):
        items = [(cid, p) for cid in ctx.claims for p in ctx.proposals(cid, "counter")
                 if p.get("condition_match") == match and _valid_counter(ctx, cid, p) and ctx.hyps.get(cid)]

        def bad(x):
            h = ctx.hyps[x[0]]
            if match == "DIFFERENT_CONDITION":
                return not h["narrowing_counter_ids"] or h["counterevidence_scope_effect"] == "NO_SCOPE_NARROWING"
            return h["posture"] == "SUPPORTED_WITHIN_BOUNDS" or not h["counterevidence"]

        return _count(items, lambda x: True, bad)

    gate(name)(fn)


_counter_gate("same_condition_counter_ignored", "SAME_CONDITION")
_counter_gate("unknown_condition_counter_ignored", "CONDITION_UNKNOWN")
_counter_gate("different_condition_narrowing_lost", "DIFFERENT_CONDITION")


@gate("different_condition_counter_defeats_gap")
def g_diff_defeats(ctx):
    return _count(_hyps(ctx), lambda h: bool(h["counterevidence"]) and all(
        ce["condition_match"] == "DIFFERENT_CONDITION" for ce in h["counterevidence"]),
                  lambda h: h["posture"] == "COUNTEREVIDENCE_WEAKENS_GAP")


@gate("narrowing_ids_mismatch")
def g_narrow_ids(ctx):
    def bad(h):
        want = sorted(ce["counter_id"] for ce in h["counterevidence"] if ce["condition_match"] == "DIFFERENT_CONDITION")
        return sorted(h["narrowing_counter_ids"]) != want or h["counterevidence_scope_effect"] != c.recompute_scope_effect(h)

    return _count(_hyps(ctx), lambda h: True, bad)


@gate("after_cutoff_counter_rewritten_historically")
def g_after(ctx):
    def opp(h):
        return any(ce["chronology_bucket"] == "AFTER_CUTOFF" for ce in h["counterevidence"])

    def bad(h):
        after = [ce for ce in h["counterevidence"] if ce["chronology_bucket"] == "AFTER_CUTOFF"]
        notes = {n["evidence_ref_id"]: n for n in h["chronology"]}
        limitation_notes = [notes[r["evidence_ref_id"]] for lim in h["limitations"] for r in ctx.lim_refs(h, lim)
                            if r["evidence_ref_id"] in notes]
        wrong_effect = any(ce["temporal_effect"] != "WEAKENS_CURRENT_POSTURE_ONLY" for ce in after)
        rewrote = any(n["historical_publicity_inferred"] or n["legal_prior_art_established"] for n in notes.values())
        shifted = any(n["bucket"] == "AFTER_CUTOFF" and not _note_after(ctx, h, n) for n in limitation_notes)
        return wrong_effect or rewrote or shifted

    return _count(_hyps(ctx), opp, bad)


def _note_after(ctx: Ctx, h: dict[str, Any], note: dict[str, Any]) -> bool:
    ref = ctx.refs_by_id(h).get(note["evidence_ref_id"])
    meta = ctx.nd_texts.get(ref["source_record_id"]) if ref else None
    if meta is None:
        return True
    profile = next((p for p in ctx.nd["candidate_profiles"] if any(t["text_ref_id"] == meta["text_ref_id"] for t in p["texts"])), None)
    return bool(profile) and profile["chronology"]["bucket"] == "AFTER_CUTOFF"


@gate("counter_from_ineligible_source_accepted")
def g_counter_inelig(ctx):
    return _count(_refs(ctx, "COUNTEREVIDENCE"), lambda x: True, lambda x: x[1]["source_quality"] != "ELIGIBLE")


@gate("counter_is_the_limitation_span_accepted")
def g_counter_self(ctx):
    def bad(x):
        h, r = x
        spans = {(q["source_record_id"], q["start"], q["end"]) for lim in h["limitations"] for q in ctx.lim_refs(h, lim)}
        return (r["source_record_id"], r["start"], r["end"]) in spans

    return _count(_refs(ctx, "COUNTEREVIDENCE"), lambda x: True, bad)


@gate("valid_counterevidence_omitted")
def g_counter_omitted(ctx):
    items = [(cid, p) for cid in ctx.claims for p in ctx.proposals(cid, "counter")
             if _valid_counter(ctx, cid, p) and ctx.hyps.get(cid)]
    return _count(items, lambda x: True, lambda x: x[1]["excerpt"] not in _accepted_excerpts(ctx, x[0], "COUNTEREVIDENCE"))


# ---------------------------------------------------------------------------
# Chronology, legal, field-wide, scores
# ---------------------------------------------------------------------------


def _notes(ctx: Ctx):
    return [(h, n) for h in _hyps(ctx) for n in h["chronology"]]


@gate("chronology_treated_as_publicity_proof")
def g_publicity(ctx):
    return _count(_notes(ctx), lambda x: True, lambda x: x[1]["historical_publicity_inferred"] is not False)


@gate("chronology_treated_as_legal_prior_art")
def g_legal_art(ctx):
    return _count(_notes(ctx), lambda x: True, lambda x: x[1]["legal_prior_art_established"] is not False)


@gate("chronology_inside_gap_support_fields")
def g_chron_support(ctx):
    names = ("chronology", "bucket", "historical_publicity_inferred", "legal_prior_art_established")

    def bad(h):
        for key in ("limitations", "existing_capabilities", "conditions", "project_links", "validation_requirement",
                    "bounded_statement"):
            if any(k in names for k, _ in c.walk({key: h[key]})):
                return True
        return False

    return _count(_hyps(ctx), lambda h: bool(h["chronology"]), bad)


@gate("chronology_bucket_rewritten")
def g_bucket(ctx):
    def bad(x):
        h, n = x
        ref = ctx.refs_by_id(h).get(n["evidence_ref_id"])
        meta = ctx.nd_texts.get(ref["source_record_id"]) if ref else None
        profile = next((p for p in ctx.nd["candidate_profiles"]
                        if meta and any(t["text_ref_id"] == meta["text_ref_id"] for t in p["texts"])), None)
        return profile is None or profile["chronology"]["bucket"] != n["bucket"]

    return _count(_notes(ctx), lambda x: True, bad)


@gate("field_wide_scope_emitted")
def g_fieldwide(ctx):
    allowed = {"SINGLE_SOURCE_BOUNDED", "MULTI_SOURCE_BOUNDED", "CANDIDATE_SET_BOUNDED", "REVIEW_SYNTHESIS_BOUNDED",
               "INSUFFICIENT_SCOPE"}
    return _count(_hyps(ctx), lambda h: True, lambda h: h["scope"] not in allowed or h["bounded_statement"]["scope"] not in allowed)


@gate("statement_missing_field_wide_qualifier")
def g_qualifier(ctx):
    q = "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"
    return _count(_hyps(ctx), lambda h: True, lambda h: h["statement_qualifier"] != q or h["bounded_statement"]["qualifier"] != q)


@gate("legal_conclusion_emitted")
def g_legal(ctx):
    bad_keys = c.FORBIDDEN_KEYS["legal"]

    def bad(h):
        return any(k in bad_keys for k, _ in c.walk(h)) or any(
            isinstance(v, str) and v in c.FORBIDDEN_VALUES for _, v in c.walk(h))

    return _count(_hyps(ctx), lambda h: True, bad)


@gate("project_score_leaked_into_phase2j")
def g_score_leak(ctx):
    bad_keys = c.FORBIDDEN_KEYS["score"]
    return _count([ctx.d], lambda d: True, lambda d: any(k in bad_keys for k, _ in c.walk(d)))


@gate("project_score_mutated")
def g_scores(ctx):
    a = ctx.before.project.model_dump(mode="json")["scores"]
    b = ctx.after.project.model_dump(mode="json")["scores"]
    return (0 if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else 1), 1


@gate("project_state_mutated")
def g_project(ctx):
    return (0 if ctx.before.project.model_dump_json() == ctx.after.project.model_dump_json() else 1), 1


@gate("claim_mutated")
def g_claim(ctx):
    old = {x.claim_id: x.claim for x in ctx.before.project.claims}
    new = {x.claim_id: x.claim for x in ctx.after.project.claims}
    return sum(1 for k, v in old.items() if new.get(k) != v) + (len(new) - len(old)), len(old)


@gate("trust_gate_or_evaluation_status_mutated")
def g_trust(ctx):
    b, a = ctx.before.project, ctx.after.project
    bad = (b.trust_gate != a.trust_gate) + (b.evaluation_status != a.evaluation_status)
    return int(bool(bad)), 1


@gate("gap_assessment_written_to_project_state")
def g_project_gap(ctx):
    return int(ctx.before.project.gap != ctx.after.project.gap), 1


# ---------------------------------------------------------------------------
# Prompt injection, model prose, hidden prompt
# ---------------------------------------------------------------------------


def _placements(script: Any, path: tuple = ()) -> list[tuple[str, ...]]:
    """Every place the script puts a hidden-prompt leak, as the key path."""
    out: list[tuple[str, ...]] = []
    if script == "$LEAK":
        out.append(path)
    elif isinstance(script, dict):
        for k, v in script.items():
            if k == "leak_system_prompt" and v:
                out.append((*path, "rationale"))
            out += _placements(v, (*path, k))
    elif isinstance(script, list):
        for v in script:
            out += _placements(v, path)
    elif isinstance(script, str) and script in ("refusal_leak", "error_leak"):
        out.append((*path, script))
    return out


def _persisted_prompt_hits(ctx: Ctx) -> int:
    blob = json.dumps(ctx.d, ensure_ascii=False)
    return sum(1 for line in c.prompt_lines() if line in blob)


def _leak_gate(name: str, fields: set[str]):
    def fn(ctx):
        n = sum(1 for p in _placements(ctx.case.script) if p and p[-1] in fields)
        return (min(_persisted_prompt_hits(ctx), n) if n else 0), n

    gate(name)(fn)


_leak_gate("hidden_prompt_persisted_from_rationale", {"rationale"})
_leak_gate("hidden_prompt_persisted_from_label", {"label"})
_leak_gate("hidden_prompt_persisted_from_type_field", {"type", "facet", "relation", "kind", "condition_match",
                                                        "dimension"})
_leak_gate("hidden_prompt_persisted_from_metric", {"metric", "baseline"})
_leak_gate("provider_text_persisted", {"refusal_leak", "error_leak"})


@gate("hidden_prompt_persisted_anywhere")
def g_prompt_any(ctx):
    n = len(_placements(ctx.case.script))
    return (_persisted_prompt_hits(ctx) if n else 0), n


@gate("rejection_ledger_persists_model_text")
def g_ledger(ctx):
    scripted: set[str] = set()
    for _, v in c.walk(ctx.case.script):
        if isinstance(v, str) and len(v) >= 8 and " " in v:
            scripted.add(v)

    def bad(r):
        s = r["safe_summary"]
        return any(v in s for v in scripted) and not s.startswith("[redacted")

    return _count(ctx.d["rejected_proposals"], lambda r: True, bad)


@gate("instruction_like_source_rejected_as_evidence")
def g_inert(ctx):
    markers = ctx.case.truth.get("injection", [])
    items = [(cid, p["excerpt"]) for cid in ctx.claims for p in ctx.proposals(cid, "limitations")
             if p.get("excerpt") in markers and p.get("type") in c.LIMITATION_TYPES]
    return _count(items, lambda x: True, lambda x: x[1] not in _limitation_excerpts(ctx, x[0]))


@gate("prompt_injection_followed")
def g_injection(ctx):
    markers = ctx.case.truth.get("injection", [])
    items = [t for t in ctx.d["inventory_texts"] if any(m in (ctx.body(t) or "") for m in markers)]

    def bad(_):
        blob = json.dumps({k: v for k, v in ctx.d.items() if k not in ("inventory_texts",)}, ensure_ascii=False)
        # a marker may appear only as a verified excerpt; never as a value in another field
        stripped = blob
        for h, r in ctx.all_refs():
            stripped = stripped.replace(json.dumps(r["excerpt"], ensure_ascii=False), "")
        return any(m in stripped for m in markers) or any(v in c.FORBIDDEN_VALUES for _, v in c.walk(ctx.d)
                                                          if isinstance(v, str))

    return _count(items, lambda t: True, bad)


@gate("off_contract_output_unreported")
def g_off_contract(ctx):
    def off(cid):
        n = 0
        for p in ctx.proposals(cid, "limitations"):
            if p.get("type") not in c.LIMITATION_TYPES or p.get("facet") not in ("RESEARCH", "ENGINEERING"):
                n += 1
        n += sum(1 for p in ctx.proposals(cid, "links") if p.get("relation") not in c.RELATIONS or p.get("unasked"))
        n += sum(1 for p in ctx.proposals(cid, "counter") if p.get("kind") not in (
            "LIMITATION_ADDRESSED", "LIMITATION_NOT_PRESENT", "DIFFERENTIATION_UNRELATED"))
        return n

    return _count(list(ctx.claims), lambda cid: off(cid) > 0 and ctx.assess[cid]["inputs_bound"],
                  lambda cid: "OFF_CONTRACT_OUTPUT" not in {e["code"] for e in ctx.d["errors"] if e.get("claim_id") == cid})


@gate("forbidden_typed_field_made_a_usable_response")
def g_typed_field(ctx):
    items = [cid for cid in ctx.claims if ctx.case.script.get("extract", {}).get(cid) == "parse_error"]
    return _count(items, lambda cid: True, lambda cid: ctx.assess[cid]["posture"] != "INSUFFICIENT_INPUT"
                  or "MODEL_CALL_FAILED" not in ctx.assess[cid]["insufficient_reasons"])


@gate("model_prose_changed_canonical_output")
def g_prose(ctx):
    if "prose" not in ctx.twins:
        return 0, 0
    return int(not ctx.twins["prose"]["same"]), 1


@gate("model_prose_in_canonical_record")
def g_prose_record(ctx):
    from src.evals.research_engineering_gap.quality import _no_free_text

    return _count(_hyps(ctx), lambda h: True, lambda h: not _no_free_text(h))


# ---------------------------------------------------------------------------
# Replay, binding, immutability, search
# ---------------------------------------------------------------------------


@gate("replay_made_a_model_call")
def g_replay_calls(ctx):
    return (int(bool(ctx.replay.get("rerun_calls"))), 1) if "rerun_calls" in ctx.replay else (0, 0)


@gate("replay_changed_the_result")
def g_replay_same(ctx):
    return (int(not ctx.replay["same"]), 1) if "same" in ctx.replay else (0, 0)


@gate("resume_changed_the_result")
def g_resume(ctx):
    return (int(not ctx.replay["resumed_same"]), 1) if "resumed_same" in ctx.replay else (0, 0)


@gate("input_order_changed_the_result")
def g_order(ctx):
    return (int(not ctx.twins["order"]["same"]), 1) if "order" in ctx.twins else (0, 0)


@gate("ids_not_deterministic")
def g_ids(ctx):
    return (int(not ctx.twins["ids"]), 1) if "ids" in ctx.twins else (0, 0)


@gate("claim_mutation_after_binding_accepted")
def g_claim_edit(ctx):
    return (int(not ctx.mutated["detected"]), 1) if ctx.case.mutate == "claim_edit" else (0, 0)


@gate("upstream_mutation_accepted")
def g_up_mut(ctx):
    return (int(not ctx.mutated["detected"]), 1) if ctx.case.mutate == "upstream_mutation" else (0, 0)


@gate("cross_run_hypothesis_or_assessment_accepted")
def g_xrun(ctx):
    rid = str(ctx.run.research_run_id)
    items = [*ctx.d["hypotheses"], *ctx.d["claim_assessments"]]
    return _count(items, lambda x: True, lambda x: x["research_run_id"] != rid or x["gap_run_id"] != ctx.d["gap_run_id"])


@gate("gap_run_bound_to_foreign_research_or_phase2i_run")
def g_run_binding(ctx):
    nd = ctx.run.novelty_differentiation
    bad = ctx.d["research_run_id"] != str(ctx.run.research_run_id) or (
        ctx.d["nd_run_id"] is not None and (nd is None or ctx.d["nd_run_id"] != str(nd.nd_run_id)))
    return int(bad), 1


def _upstream_gate(name: str, field_name: str):
    def fn(ctx):
        a, b = getattr(ctx.prior, field_name), getattr(ctx.run, field_name)
        if a is None and b is None:
            return 0, 0
        same = (a.model_dump_json() if a is not None else None) == (b.model_dump_json() if b is not None else None)
        return int(not same), 1

    gate(name)(fn)


for _name, _field in (("phase2c_evidence_mutated", "evidence_extraction"), ("phase2e_sufficiency_mutated", "claim_sufficiency"),
                      ("phase2f_scoring_mutated", "claim_evidence_scoring"), ("phase2g_patent_mutated", "patent_prior_art"),
                      ("phase2h_product_mutated", "product_prior_art"), ("phase2h_open_source_mutated", "open_source_prior_art"),
                      ("phase2i_novelty_mutated", "novelty_differentiation")):
    _upstream_gate(_name, _field)


@gate("duplicate_hypothesis_accepted")
def g_dup_hyp(ctx):
    ids = [h["hypothesis_id"] for h in ctx.d["hypotheses"]]
    return (len(ids) - len(set(ids))), len(ids)


@gate("external_search_invoked")
def g_search(ctx):
    return int(ctx.d["external_search_calls"] != 0), 1


__all__ = ["GATES", "GATE_FUNCS"]
