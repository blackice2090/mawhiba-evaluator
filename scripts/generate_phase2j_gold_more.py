"""Remaining Phase 2J Gold scenarios (registered by importing). See generate_phase2j_gold.py."""

from __future__ import annotations

from generate_phase2j_gold_core import (
    A, C1, CAP, CUT, DIMENSIONS, ENG, EX, LK, MS, NO_LIMITATION, RES, RF, S, UQ, VC, VL, X, add, L, nd, patent, pk,
    rec, tl, trio, truth_links,
)

ACADEMIC = "Measured accuracy reached 94%"


def chain_over(P, lim, **extra):
    """The authored outcome of a complete chain over one measured limitation."""
    base = dict(lim__types=tl((lim["type"], lim["facet"])), lim__excerpts=[lim["excerpt"]], cap__excerpts=[P.cap],
                val__metric=P.metric, val__metric_origin="LIMITATION_EVIDENCE", val__baseline=None)
    base.update(extra)
    return base


PARTIAL = dict(hyp__posture="PARTIALLY_SUPPORTED", claim__posture="PARTIALLY_SUPPORTED")

# ===========================================================================
# 7. EXISTING CAPABILITY
# ===========================================================================


def s_capability(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    add(["capability-missing-cannot-be-supported"], lang, P,
        X(**chain_over(P, lim, cap__excerpts=[], hyp__missing=["EXISTING_CAPABILITY"], **PARTIAL)),
        script=S(EX([], [lim], VL(P)), [LK(lim, P)]), truth=truth_links(P, (P.short, A)))
    cap_title = CAP(P, P.title_lim, where="PATENT_TITLE")
    add(["capability-inferred-from-title-refused", "capability-title-only-not-capability"], lang, P,
        X(**chain_over(P, lim, cap__excerpts=[], hyp__missing=["EXISTING_CAPABILITY"], rejected=["INELIGIBLE_SOURCE_FOR_ROLE"],
                       **PARTIAL)),
        patent=patent(rec("EP.1000001.A1", P, title=P.title_lim)),
        script=S(EX([cap_title], [lim], VL(P)), [LK(lim, P)]), truth=truth_links(P, (P.short, A)))
    cap_abs = CAP(P, P.cap, where="PATENT_ABSTRACT")
    add(["capability-from-limited-abstract-is-eligible", "source-patent-abstract-limited-eligible"], lang, P,
        X(**chain_over(P, lim)), patent=patent(rec("EP.1000001.A1", P, abstract=P.cap)),
        script=S(EX([cap_abs], [lim], VL(P)), [LK(lim, P)]), truth=truth_links(P, (P.short, A)))


trio(s_capability)

# ===========================================================================
# 8. VALIDATION REQUIREMENT / METRICS
# ===========================================================================


def s_validation(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    no_val = dict(hyp__missing=["VALIDATION_REQUIREMENT"], val__metric=None, val__metric_origin=None, val__baseline=None, **PARTIAL)
    add(["validation-requirement-missing-cannot-be-supported"], lang, P,
        X(**chain_over(P, lim, **no_val)), script=S(EX([CAP(P)], [lim]), [LK(lim, P)]), truth=truth_links(P, (P.short, A)))
    add(["invented-metric-refused", "validation-metric-not-in-source"], lang, P,
        X(**chain_over(P, lim, rejected=["INVENTED_METRIC"], issues=["INVENTED_METRIC"], **no_val)),
        script=S(EX([CAP(P)], [lim], {"metric_source": "L1", "metric": "F1 at least 0.95"}), [LK(lim, P)]),
        truth=truth_links(P, (P.short, A)))
    add(["invented-metric-numeric-threshold-refused", "validation-no-invented-threshold"], lang, P,
        X(**chain_over(P, lim, rejected=["INVENTED_METRIC"], issues=["INVENTED_METRIC"], **no_val)),
        script=S(EX([CAP(P)], [lim], {"metric_source": "CLAIM", "metric": "95% " + P.metric}), [LK(lim, P)]),
        truth=truth_links(P, (P.short, A)))
    add(["validation-baseline-from-existing-capability"], lang, P,
        X(**chain_over(P, lim, val__baseline="92%")),
        script=S(EX([CAP(P)], [lim], {"metric_source": "L1", "metric": P.metric, "baseline_source": "C1", "baseline": "92%"}),
                 [LK(lim, P)]), truth=truth_links(P, (P.short, A)))
    add(["invented-baseline-refused"], lang, P,
        X(**chain_over(P, lim, rejected=["INVENTED_BASELINE"], issues=["INVENTED_METRIC"])),
        script=S(EX([CAP(P)], [lim], {"metric_source": "L1", "metric": P.metric, "baseline_source": "C1", "baseline": "99%"}),
                 [LK(lim, P)]), truth=truth_links(P, (P.short, A)))


trio(s_validation)

# ===========================================================================
# 9. CONDITION MATERIALITY
# ===========================================================================


def s_conditions(lang):
    P = pk(lang)
    for dim in DIMENSIONS:
        text = P.dim_sentence[dim]
        lim = L(P, text, MS, ENG, dims=[dim], conds=[(dim, P.cond[dim])])
        add([f"condition-dimension-{dim.lower().replace('_', '-')}-required-and-bound"], lang, P,
            X(**chain_over(P, lim, hyp__materiality=["CONDITION_REQUIRED_AND_BOUND"], cond__dims=[dim], cond__n=1,
                           stmt__conditions=1)),
            script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P)]), truth=truth_links(P, (text, A)))
    missing = dict(hyp__materiality=["CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"], hyp__missing=["MATERIAL_CONDITION"],
                   cond__dims=[], cond__n=0, **PARTIAL)
    lang_lim = L(P, P.dim_sentence["LANGUAGE"], MS, ENG, dims=["LANGUAGE"])
    add(["condition-required-but-missing-not-supported", "localization-language-limitation-without-condition"], lang, P,
        X(**chain_over(P, lang_lim, **missing)), script=S(EX([CAP(P)], [lang_lim], VL(P)), [LK(lang_lim, P)]),
        truth=truth_links(P, (P.dim_sentence["LANGUAGE"], A)))
    env_lim = L(P, P.short, MS, ENG, dims=["ENVIRONMENT"])
    add(["condition-environment-required-but-missing"], lang, P,
        X(**chain_over(P, env_lim, **missing)), script=S(EX([CAP(P)], [env_lim], VL(P)), [LK(env_lim, P)]),
        truth=truth_links(P, (P.short, A)))
    geo = L(P, P.dim_sentence["GEOGRAPHY"], MS, ENG, dims=["GEOGRAPHY"], conds=[("LANGUAGE", P.cond["LANGUAGE"])])
    add(["condition-bound-for-a-different-dimension-does-not-satisfy"], lang, P,
        X(**chain_over(P, geo, **{**missing, "cond__dims": ["LANGUAGE"], "cond__n": 1, "stmt__conditions": 1})),
        script=S(EX([CAP(P)], [geo], VL(P)), [LK(geo, P)]), truth=truth_links(P, (P.dim_sentence["GEOGRAPHY"], A)))


trio(s_conditions)

# ===========================================================================
# 10. COUNTEREVIDENCE
# ===========================================================================


def counter(P, text, match, kind="LIMITATION_ADDRESSED", **kw):
    return {"kind": kind, "condition_match": match, "excerpt": text, **kw}


def s_counter(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    std = chain_over(P, lim)
    link = [LK(lim, P)]
    tr = truth_links(P, (P.short, A))
    weak = dict(hyp__posture="COUNTEREVIDENCE_WEAKENS_GAP", claim__posture="COUNTEREVIDENCE_WEAKENS_GAP", counter__n=1,
                counter__kinds=["LIMITATION_ADDRESSED"])
    add(["counterevidence-same-condition-weakens-and-does-not-narrow"], lang, P,
        X(**std, **weak, counter__matches=["SAME_CONDITION"]),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_same, "SAME_CONDITION")]), truth=tr)
    add(["counterevidence-unknown-condition-weakens-and-stays-visible"], lang, P,
        X(**std, **weak, counter__matches=["CONDITION_UNKNOWN"], hyp__scope_effect="CONDITION_RELATION_UNRESOLVED",
          stmt__scope_effect="CONDITION_RELATION_UNRESOLVED"),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_unknown, "CONDITION_UNKNOWN")]), truth=tr)
    narrowed = dict(counter__n=1, counter__kinds=["LIMITATION_ADDRESSED"], counter__matches=["DIFFERENT_CONDITION"],
                    narrowing__n=1, hyp__scope_effect="NARROWED_BY_DIFFERENT_CONDITION",
                    stmt__scope_effect="NARROWED_BY_DIFFERENT_CONDITION")
    add(["counterevidence-different-condition-exposes-unbound-condition", "counterevidence-different-condition-narrows"],
        lang, P,
        X(**std, **narrowed, **PARTIAL, hyp__missing=["MATERIAL_CONDITION"],
          hyp__materiality=["CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"]),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_diff, "DIFFERENT_CONDITION")]), truth=tr)
    bound = L(P, P.short, MS, ENG, dims=["ENVIRONMENT"], conds=[("ENVIRONMENT", P.cond["ENVIRONMENT"])])
    add(["counterevidence-different-condition-with-bound-condition-stays-supported"], lang, P,
        X(**chain_over(P, bound, hyp__materiality=["CONDITION_REQUIRED_AND_BOUND"], cond__dims=["ENVIRONMENT"], cond__n=1,
                       stmt__conditions=1), **narrowed),
        script=S(EX([CAP(P)], [bound], VL(P)), [LK(bound, P)], [counter(P, P.counter_diff, "DIFFERENT_CONDITION")]), truth=tr)
    add(["counterevidence-omitted-by-model-recall-measured"], lang, P,
        X(**std), script=S(EX([CAP(P)], [lim], VL(P)), link, []),
        truth={**tr, "counter": {C1: [P.counter_same]}})
    add(["counterevidence-unknown-condition-ignored-by-model-recall-measured"], lang, P,
        X(**std), script=S(EX([CAP(P)], [lim], VL(P)), link, []),
        truth={**tr, "counter": {C1: [P.counter_unknown]}})
    add(["counterevidence-review-incomplete-text-bound-cannot-be-supported", "counterevidence-candidate-set-skipped"], lang, P,
        X(**{**std, "cap__excerpts": [ACADEMIC]}, hyp__review_complete=False,
          hyp__missing=["COMPLETE_COUNTEREVIDENCE_REVIEW"], **PARTIAL),
        bounds={"max_chars_per_text": 200},
        script=S(EX([CAP(P, ACADEMIC, where="ACADEMIC_EXCERPT")], [lim], VL(P)), link, []), truth=tr)
    add(["counterevidence-review-call-failed-cannot-be-supported"], lang, P,
        X(**std, hyp__review_complete=False, hyp__missing=["COMPLETE_COUNTEREVIDENCE_REVIEW"], issues=["MODEL_ERROR"], **PARTIAL),
        script={"extract": {C1: EX([CAP(P)], [lim], VL(P))}, "link": {C1: link}, "counter": {C1: "provider_error"}}, truth=tr)
    add(["counterevidence-from-title-is-ineligible-and-not-counted"], lang, P,
        X(**std, rejected=["INELIGIBLE_SOURCE_FOR_ROLE"]),
        patent=patent(rec("EP.1000001.A1", P, title=P.counter_same)),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_same, "SAME_CONDITION", **{"in": "PATENT_TITLE"})]), truth=tr)
    add(["counterevidence-cannot-be-the-limitation-itself"], lang, P,
        X(**std, rejected=["COUNTEREVIDENCE_IS_THE_LIMITATION_SPAN"]),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.short, "SAME_CONDITION", kind="LIMITATION_NOT_PRESENT")]),
        truth=tr)
    add(["counterevidence-invalid-kind-refused", "off-contract-invalid-counterevidence-kind"], lang, P,
        X(**std, rejected=["INVALID_COUNTEREVIDENCE_KIND"], issues=["OFF_CONTRACT_OUTPUT"]),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_same, "SAME_CONDITION", kind="UNSURE")]), truth=tr)


trio(s_counter)


def two_records(P, first_desc, second_desc, second_date, **kw):
    return patent(rec("EP.1000001.A1", P, desc=first_desc, family="555"),
                  rec("EP.1000002.A1", P, desc=second_desc, family="556", date=second_date, **kw))


def s_counter_sources(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    std = chain_over(P, lim)
    link = [LK(lim, P)]
    tr = truth_links(P, (P.short, A))
    first = f"{P.cap}. {P.short}."
    units = ["ACADEMIC_PHASE2E_GROUP:True", "PATENT_SINGLETON_FAMILY:True"]
    add(["counterevidence-later-source-weakens-the-gap", "chronology-counter-before-cutoff"], lang, P,
        X(**std, hyp__posture="COUNTEREVIDENCE_WEAKENS_GAP", claim__posture="COUNTEREVIDENCE_WEAKENS_GAP", counter__n=1,
          counter__kinds=["LIMITATION_ADDRESSED"], counter__matches=["SAME_CONDITION"],
          chron__buckets=["BEFORE_CUTOFF"], chron__counter_buckets=["BEFORE_CUTOFF"], indep__units=units),
        patent=two_records(P, first, f"{P.counter_same}.", "2016-03-01"),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_same, "SAME_CONDITION")]), truth=tr)
    after = dict(chron__buckets=["AFTER_CUTOFF", "BEFORE_CUTOFF"], chron__counter_buckets=["AFTER_CUTOFF"], indep__units=units)
    add(["counterevidence-after-cutoff-same-condition-weakens-current-posture"], lang, P,
        X(**std, hyp__posture="COUNTEREVIDENCE_WEAKENS_GAP", claim__posture="COUNTEREVIDENCE_WEAKENS_GAP", counter__n=1,
          counter__kinds=["LIMITATION_ADDRESSED"], counter__matches=["SAME_CONDITION"], **after),
        patent=two_records(P, first, f"{P.counter_same}.", "2023-01-01"),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_same, "SAME_CONDITION")]), truth=tr)
    add(["counterevidence-after-cutoff-different-condition-current-only-narrowing", "chronology-no-retroactive-rewrite"],
        lang, P,
        X(**std, **PARTIAL, hyp__missing=["MATERIAL_CONDITION"], hyp__materiality=["CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"],
          counter__n=1, counter__kinds=["LIMITATION_ADDRESSED"], counter__matches=["DIFFERENT_CONDITION"], narrowing__n=1,
          narrowing__current_only=True, hyp__scope_effect="NARROWED_BY_DIFFERENT_CONDITION",
          stmt__scope_effect="NARROWED_BY_DIFFERENT_CONDITION", **after),
        patent=two_records(P, first, f"{P.counter_diff}.", "2023-01-01"),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [counter(P, P.counter_diff, "DIFFERENT_CONDITION")]), truth=tr)
    bound = L(P, P.short, MS, ENG, dims=["ENVIRONMENT"], conds=[("ENVIRONMENT", P.cond["ENVIRONMENT"])])
    add(["counterevidence-after-cutoff-different-condition-bound-stays-supported"], lang, P,
        X(**chain_over(P, bound, hyp__materiality=["CONDITION_REQUIRED_AND_BOUND"], cond__dims=["ENVIRONMENT"], cond__n=1,
                       stmt__conditions=1), counter__n=1, counter__kinds=["LIMITATION_ADDRESSED"],
          counter__matches=["DIFFERENT_CONDITION"], narrowing__n=1, narrowing__current_only=True,
          hyp__scope_effect="NARROWED_BY_DIFFERENT_CONDITION", stmt__scope_effect="NARROWED_BY_DIFFERENT_CONDITION", **after),
        patent=two_records(P, first, f"{P.counter_diff}.", "2023-01-01"),
        script=S(EX([CAP(P)], [bound], VL(P)), [LK(bound, P)], [counter(P, P.counter_diff, "DIFFERENT_CONDITION")]), truth=tr)
    add(["counterevidence-after-cutoff-ignored-by-model-recall-measured"], lang, P,
        X(**std, chron__buckets=["BEFORE_CUTOFF"], indep__units=units),
        patent=two_records(P, first, f"{P.counter_same}.", "2023-01-01"),
        script=S(EX([CAP(P)], [lim], VL(P)), link, []), truth={**tr, "counter": {C1: [P.counter_same]}})


trio(s_counter_sources)
