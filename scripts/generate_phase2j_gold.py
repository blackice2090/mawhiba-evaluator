"""One-off generator for the Phase 2J Gold dataset (``cases.jsonl``).

    ./.venv/Scripts/python.exe scripts/generate_phase2j_gold.py

Expectations are AUTHORED here from each case's own source text and the Phase 2J policy.
They are never produced by running the system. Arabic appears only as DATA (claims and
source text, in generate_phase2j_gold_core.py and below).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from generate_phase2j_gold_core import (
    A, BASES, C1, CAP, CASES, DIMENSIONS, ENG, EL, EX, LK, MS, NO_LIMITATION, RES, RF, S, SR, TO, UQ, UR, VC, VL, X, add, L,
    nd, patent, pk, rec, tl, trio, truth_links,
)

OUT = Path(__file__).resolve().parents[1] / "evals" / "research_engineering_gap" / "v1" / "cases.jsonl"
# ===========================================================================
# 1. VALID LIMITATION TYPES -> a complete, supported chain
# ===========================================================================


def v_case(lang, cat, text_key, ltype, facet, kind, *, metric="L", dims=None, cond=None, extra_cats=()):
    P = pk(lang)
    text = P.dim_sentence[dims[0]] if (dims and text_key is None) else getattr(P, text_key)
    conds = [(dims[0], P.cond[dims[0]])] if cond == "dim" else ([(dims[0], getattr(P, cond))] if cond else None)
    lim = L(P, text, ltype, facet, dims=dims, conds=conds)
    val = VL(P) if metric == "L" else VC(P)
    over = dict(
        hyp__kind=kind, lim__types=tl((ltype, facet)), lim__excerpts=[text], cap__excerpts=[P.cap],
        val__metric=P.metric if metric == "L" else P.seg2,
        val__metric_origin="LIMITATION_EVIDENCE" if metric == "L" else "STUDENT_CLAIM_TEXT", val__baseline=None,
    )
    if conds:
        over.update(hyp__materiality=["CONDITION_REQUIRED_AND_BOUND"], cond__dims=[dims[0]], cond__n=1, stmt__conditions=1)
    add([cat, *extra_cats], lang, P, X(**over), script=S(EX([CAP(P)], [lim], val), [LK(lim, P)]),
        truth=truth_links(P, (text, A)))


def s_valid(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    add(["limitation-measured-shortfall-supported-chain", "condition-not-material-no-synthetic-condition",
         "counterevidence-none-no-synthetic-narrowing", "hybrid-not-claimed-single-limitation",
         "chronology-patent-publication-before-cutoff", "chronology-separate-from-gap-support"], lang, P,
        X(hyp__kind="ENGINEERING", lim__types=tl((MS, ENG)), lim__excerpts=[P.short], cap__excerpts=[P.cap],
          val__metric=P.metric, val__metric_origin="LIMITATION_EVIDENCE", val__baseline=None, run__model_calls=3),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P)]), truth=truth_links(P, (P.short, A)))
    v_case(lang, "limitation-reported-failure-mode-supported-chain", "fail", RF, ENG, "ENGINEERING", metric="C")
    v_case(lang, "limitation-tradeoff-supported-chain", "trade", TO, ENG, "ENGINEERING", metric="C")
    v_case(lang, "limitation-unmet-requirement-supported-chain", "unmet", UR, ENG, "ENGINEERING", metric="C")
    v_case(lang, "limitation-unresolved-question-research-supported-chain", "unres", UQ, RES, "RESEARCH", metric="C",
           extra_cats=["research-genuine-unresolved-question"])
    v_case(lang, "limitation-explicit-engineering-supported-chain", "expl", EL, ENG, "ENGINEERING", metric="C")
    v_case(lang, "limitation-explicit-research-supported-chain", "expl", EL, RES, "RESEARCH", metric="C")
    v_case(lang, "limitation-scope-restriction-bound-condition-supported-chain", "scope", SR, RES, "RESEARCH", metric="C",
           dims=["SCALE"], cond="scope_cond", extra_cats=["research-bounded-unresolved-scope"])
    v_case(lang, "limitation-bounded-unresolved-question-population", "unres_pop", UQ, RES, "RESEARCH", metric="C",
           dims=["POPULATION"], cond="pop_cond", extra_cats=["research-bounded-unresolved-question"])


trio(s_valid)

# ===========================================================================
# 2. ABSENCE-LIKE NON-EVIDENCE
# ===========================================================================

BASIS_CATS = {
    "NOT_MENTIONED": ["absence-basis-not-mentioned"],
    "FEATURE_ABSENT": ["absence-basis-feature-absent"],
    "NO_MATCH_FOUND": ["absence-basis-no-match-found"],
    "TITLE_ONLY_DIFFERENCE": ["absence-basis-title-only-difference"],
    "STUDENT_ASSERTION_ONLY": ["absence-basis-student-assertion-only", "student-claim-not-evidence"],
    "MARKETPLACE_ABSENCE_ONLY": ["absence-basis-marketplace-absence-only", "marketplace-absence-not-gap"],
    "LANGUAGE_ABSENCE_ONLY": ["absence-basis-language-absence-only", "localization-language-absence-not-gap"],
    "FUTURE_WORK_ONLY": ["absence-basis-future-work-only", "future-work-only-not-gap"],
    "DIFFERENTIATION_ONLY": ["absence-basis-differentiation-only", "differentiation-only-not-gap"],
    "NO_OVERLAP_FOUND_ONLY": ["absence-basis-no-overlap-found-only", "no-overlap-found-not-gap"],
}


def s_absence(lang):
    P = pk(lang)
    for basis in BASES:
        text = getattr(P, basis)
        lim = L(P, text, basis, ENG)
        add(BASIS_CATS[basis], lang, P,
            X(**NO_LIMITATION, rejected=["INADMISSIBLE_LIMITATION_BASIS"], issues=["OFF_CONTRACT_OUTPUT"], run__model_calls=1),
            script=S(EX([CAP(P)], [lim], VC(P))), truth={"inadmissible": {C1: [text]}})


trio(s_absence)


def s_numeric(lang):
    P = pk(lang)
    lim = L(P, P.unmet, MS, ENG)
    add(["numeric-shortfall-missing-number", "numeric-value-outside-the-limitation-excerpt"], lang, P,
        X(**NO_LIMITATION, rejected=["MEASURED_SHORTFALL_WITHOUT_NUMBER"], run__model_calls=1),
        script=S(EX([CAP(P)], [lim], VC(P))))
    bad_type = L(P, P.fail, "NOT_A_REAL_TYPE", ENG)
    add("off-contract-invalid-limitation-type", lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_LIMITATION_TYPE"], issues=["OFF_CONTRACT_OUTPUT"], run__model_calls=1),
        script=S(EX([CAP(P)], [bad_type], VC(P))))
    bad_facet = L(P, P.fail, RF, "BOTH")
    add("off-contract-invalid-facet", lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_FACET"], issues=["OFF_CONTRACT_OUTPUT"], run__model_calls=1),
        script=S(EX([CAP(P)], [bad_facet], VC(P))))
    mismatch = L(P, P.fail, RF, RES)
    add("facet-type-mismatch-refused", lang, P,
        X(**NO_LIMITATION, rejected=["FACET_INELIGIBLE_FOR_TYPE"], run__model_calls=1),
        script=S(EX([CAP(P)], [mismatch], VC(P))))
    scope_nodim = L(P, P.scope, SR, RES)
    add("scope-restriction-without-dimension-refused", lang, P,
        X(**NO_LIMITATION, rejected=["SCOPE_RESTRICTION_WITHOUT_DIMENSION"], run__model_calls=1),
        script=S(EX([CAP(P)], [scope_nodim], VC(P))))
    bad_dim = L(P, P.scope, SR, RES, dims=["COLOUR"])
    add("off-contract-invalid-condition-dimension", lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_CONDITION_DIMENSION"], issues=["OFF_CONTRACT_OUTPUT"], run__model_calls=1),
        script=S(EX([CAP(P)], [bad_dim], VC(P))))


trio(s_numeric)

# ===========================================================================
# 3. FALSE / CONTRADICTED RESEARCH PROPOSITIONS
# ===========================================================================


def s_research_false(lang):
    P = pk(lang)
    lim = L(P, P.NO_MATCH_FOUND, UQ, RES)
    add(["research-false-unresolved-question-from-missing-search", "gap-existence-without-linkage"], lang, P,
        X(hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
          hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND", "VALIDATION_REQUIREMENT"],
          claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP", claim__linkage=["NONE_MATERIAL"],
          link__n=0, link__relations=[], stmt__limitations=0, lim__excerpts=[P.NO_MATCH_FOUND], lim__types=tl((UQ, RES))),
        script=S(EX([CAP(P)], [lim]), []), truth={"inadmissible": {C1: [P.NO_MATCH_FOUND]}})
    lim2 = L(P, P.unres, UQ, RES)
    counter = [{"kind": "LIMITATION_NOT_PRESENT", "condition_match": "SAME_CONDITION", "excerpt": P.contra}]
    add(["research-proposition-contradicted-by-source", "counterevidence-same-condition-weakens"], lang, P,
        X(hyp__kind="RESEARCH", hyp__posture="COUNTEREVIDENCE_WEAKENS_GAP", claim__posture="COUNTEREVIDENCE_WEAKENS_GAP",
          counter__n=1, counter__kinds=["LIMITATION_NOT_PRESENT"], counter__matches=["SAME_CONDITION"],
          lim__excerpts=[P.unres], lim__types=tl((UQ, RES)), val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT",
          val__baseline=None, cap__excerpts=[P.cap]),
        script=S(EX([CAP(P)], [lim2], VC(P)), [LK(lim2, P)], counter), truth=truth_links(P, (P.unres, A)))


trio(s_research_false)

# ===========================================================================
# 4. HYBRID
# ===========================================================================


def hybrid_over(P, lims, **extra):
    return dict(hyp__kind="HYBRID", lim__n=len(lims), lim__types=sorted(f"{x['type']}/{x['facet']}" for x in lims),
                lim__excerpts=sorted(x["excerpt"] for x in lims), link__n=len(lims),
                link__relations=sorted([A] * len(lims)), stmt__limitations=len(lims), val__metric=P.seg2,
                val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None, cap__excerpts=[P.cap],
                hyp__materiality=["CONDITION_NOT_MATERIAL"] * len(lims), lim__quality=["ELIGIBLE"] * len(lims), **extra)


def s_hybrid(lang):
    P = pk(lang)
    r, e = L(P, P.unres, UQ, RES, label="L1"), L(P, P.short, MS, ENG, label="L2")
    add(["hybrid-distinct-propositions-same-source-different-spans", "hybrid-research-plus-engineering-both-linked"], lang, P,
        X(**hybrid_over(P, [r, e])), script=S(EX([CAP(P)], [r, e], VC(P)), [LK(r, P), LK(e, P)]),
        truth=truth_links(P, (P.unres, A), (P.short, A)))
    # two different source records
    rec1 = rec("EP.1000001.A1", P, desc=f"{P.cap}. {P.unres}.", family="555")
    rec2 = rec("EP.1000002.A1", P, desc=f"{P.short}.", family="556")
    add("hybrid-distinct-propositions-different-sources", lang, P,
        X(**hybrid_over(P, [r, e]), hyp__corroboration="MULTI_SOURCE_CORROBORATED"),
        patent=patent(rec1, rec2), script=S(EX([CAP(P)], [r, e], VC(P)), [LK(r, P), LK(e, P)]),
        truth=truth_links(P, (P.unres, A), (P.short, A)))
    d1, d2 = (L(P, P.dual, UQ, RES, label="L1"), L(P, P.dual, MS, ENG, label="L2"))
    add(["hybrid-same-exact-span-genuinely-dual-propositions", "proposition-key-distinct-types-same-span"], lang, P,
        X(**hybrid_over(P, [d1, d2])),
        script=S(EX([CAP(P)], [d1, d2], VC(P)), [LK(d1, P, limitation_type=UQ), LK(d2, P, limitation_type=MS)]),
        truth={**truth_links(P, (P.dual, A)), "propositions": {C1: {"distinct": 2}}})
    add(["hybrid-one-side-materially-linked-only", "hybrid-not-manufactured-when-one-side-unlinked"], lang, P,
        X(hyp__kind="ENGINEERING", lim__n=2, lim__types=tl((UQ, RES), (MS, ENG)), lim__excerpts=sorted([P.unres, P.short]),
          link__n=2, link__relations=sorted([A, "UNRELATED"]), stmt__limitations=1, val__metric=P.seg2,
          val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None, cap__excerpts=[P.cap],
          hyp__materiality=["CONDITION_NOT_MATERIAL", "CONDITION_NOT_MATERIAL"], lim__quality=["ELIGIBLE", "ELIGIBLE"]),
        script=S(EX([CAP(P)], [r, e], VC(P)), [LK(r, P, "UNRELATED"), LK(e, P)]),
        truth=truth_links(P, (P.unres, "UNRELATED"), (P.short, A)))
    x1, x2 = L(P, P.expl, EL, ENG, label="L1"), L(P, P.expl, EL, RES, label="L2")
    add(["proposition-duplicate-relabelled-copy-refused", "hybrid-not-manufactured-by-relabelling"], lang, P,
        X(hyp__kind="ENGINEERING", lim__types=tl((EL, ENG)), lim__excerpts=[P.expl], rejected=["DUPLICATE_PROPOSITION"],
          val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None, cap__excerpts=[P.cap]),
        script=S(EX([CAP(P)], [x1, x2], VC(P)), [LK(x1, P)]), truth=truth_links(P, (P.expl, A)))
    f1, f2 = L(P, P.short, MS, ENG, label="L1"), L(P, P.short, UQ, RES, label="L2")
    add(["hybrid-same-span-false-hybrid-model-judgment", "proposition-mislabelled-twice-different-types"], lang, P,
        X(**hybrid_over(P, [f1, f2])),
        script=S(EX([CAP(P)], [f1, f2], VC(P)), [LK(f1, P, limitation_type=MS), LK(f2, P, limitation_type=UQ)]),
        truth={**truth_links(P, (P.short, A)), "propositions": {C1: {"distinct": 1}}})
    g1, g2 = L(P, P.short, MS, ENG, label="L1"), L(P, P.short, RF, ENG, label="L2")
    add(["proposition-same-span-two-engineering-types-model-judgment"], lang, P,
        X(hyp__kind="ENGINEERING", lim__n=2, lim__types=tl((MS, ENG), (RF, ENG)), lim__excerpts=[P.short, P.short],
          link__n=2, link__relations=[A, A], stmt__limitations=2, val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT",
          val__baseline=None, cap__excerpts=[P.cap], hyp__materiality=["CONDITION_NOT_MATERIAL"] * 2,
          lim__quality=["ELIGIBLE"] * 2),
        script=S(EX([CAP(P)], [g1, g2], VC(P)), [LK(g1, P, limitation_type=MS), LK(g2, P, limitation_type=RF)]),
        truth={**truth_links(P, (P.short, A)), "propositions": {C1: {"distinct": 1}}})


trio(s_hybrid)

# ===========================================================================
# 5. PROJECT-GAP LINKAGE
# ===========================================================================


def s_linkage(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    base = dict(lim__types=tl((MS, ENG)), lim__excerpts=[P.short], cap__excerpts=[P.cap], val__metric=P.metric,
                val__metric_origin="LIMITATION_EVIDENCE", val__baseline=None)
    add(["linkage-partially-addresses-downgrades-to-partial"], lang, P,
        X(**base, hyp__linkage="PARTIAL", hyp__posture="PARTIALLY_SUPPORTED", hyp__missing=["FULL_PROJECT_LINKAGE"],
          claim__posture="PARTIALLY_SUPPORTED", claim__linkage=["PARTIAL"], link__relations=["PARTIALLY_ADDRESSES_LIMITATION"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, "PARTIALLY_ADDRESSES_LIMITATION")]),
        truth=truth_links(P, (P.short, "PARTIALLY_ADDRESSES_LIMITATION")))
    for relation, cat in (("RELEVANT_BUT_NOT_ADDRESSING", "linkage-relevant-but-not-addressing-never-supported"),
                          ("UNRELATED", "linkage-unrelated-never-supported"),
                          ("INSUFFICIENT_LINKAGE_EVIDENCE", "linkage-insufficient-evidence-never-supported")):
        add([cat, "differentiation-without-gap-limitation-unlinked", "linkage-structurally-valid-semantically-no"], lang, P,
            X(**base, hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
              hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
              claim__linkage=["NONE_MATERIAL"], link__relations=[relation], stmt__limitations=0),
            script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, relation)]), truth=truth_links(P, (P.short, relation)))
    add(["linkage-semantic-model-error-accepted-structurally", "linkage-semantic-accuracy-measured"], lang, P,
        X(**base), script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, A)]), truth=truth_links(P, (P.short, "UNRELATED")))
    add(["linkage-duplicate-judgment-dropped"], lang, P,
        X(**base, hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
          hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
          claim__linkage=["NONE_MATERIAL"], link__n=0, link__relations=[], stmt__limitations=0, rejected=["DUPLICATE_JUDGMENT"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, A), LK(lim, P, A)]))
    add(["linkage-fabricated-feature-id-refused", "off-contract-unasked-pair"], lang, P,
        X(**base, rejected=["UNKNOWN_LABEL"], issues=["FABRICATED_REFERENCE", "OFF_CONTRACT_OUTPUT"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, A),
                                              {"feature": "an invented feature", "limitation": P.short, "relation": A, "unasked": True}]),
        truth=truth_links(P, (P.short, A)))
    add(["linkage-fabricated-limitation-id-refused"], lang, P,
        X(**base, hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
          hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
          claim__linkage=["NONE_MATERIAL"], link__n=0, link__relations=[], stmt__limitations=0, rejected=["UNKNOWN_LABEL"],
          issues=["FABRICATED_REFERENCE", "OFF_CONTRACT_OUTPUT"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [{"feature": P.f3, "limitation": "L77", "relation": A, "unasked": True}]))
    add(["linkage-invalid-relation-value-refused", "off-contract-invalid-relation"], lang, P,
        X(**base, hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
          hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP",
          claim__linkage=["NONE_MATERIAL"], link__n=0, link__relations=[], stmt__limitations=0,
          rejected=["INVALID_RELATION"], issues=["OFF_CONTRACT_OUTPUT"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, "ADDRESSES_ALL")]))


trio(s_linkage)

# ===========================================================================
# 6. DIFFERENTIATION WITHOUT GAP
# ===========================================================================


def s_diff(lang):
    P = pk(lang)
    add(["differentiation-without-gap-no-eligible-limitation"], lang, P,
        X(**NO_LIMITATION, run__model_calls=1), script=S(EX([CAP(P)], [])))
    add(["differentiation-absent-no-limitation-not-established"], lang, P,
        X(**{**NO_LIMITATION, "claim__posture": "NOT_ESTABLISHED_WITHIN_BOUNDS"}, claim__has_diff=False, run__model_calls=1),
        nd=nd(P, "disclose_all"), script=S(EX([CAP(P)], [])))
    lim = L(P, P.short, MS, ENG)
    add(["differentiation-absent-limitation-without-differentiating-feature"], lang, P,
        X(hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
          hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND", "VALIDATION_REQUIREMENT"],
          claim__posture="NOT_ESTABLISHED_WITHIN_BOUNDS", claim__has_diff=False, claim__linkage=["NONE_MATERIAL"],
          link__n=0, link__relations=[], stmt__limitations=0, lim__types=tl((MS, ENG)), lim__excerpts=[P.short],
          run__model_calls=2),
        nd=nd(P, "disclose_all"), script=S(EX([CAP(P)], [lim]), []))


trio(s_diff)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    import generate_phase2j_gold_more  # noqa: F401  (registers the remaining scenarios)
    import generate_phase2j_gold_more2  # noqa: F401
    import generate_phase2j_gold_more3  # noqa: F401

    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False, sort_keys=False) for c in CASES) + "\n", encoding="utf-8")
    langs = Counter(c["language"] for c in CASES)
    cats = {x for c in CASES for x in c["categories"]}
    print(f"{len(CASES)} cases {dict(langs)} {len(cats)} categories -> {OUT}")


if __name__ == "__main__":
    main()
