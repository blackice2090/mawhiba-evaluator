"""Phase 2J Gold scenarios, part 2: independence, source quality, chronology, injection,
replay and binding. See generate_phase2j_gold.py."""

from __future__ import annotations

from generate_phase2j_gold_core import (
    A, C1, CAP, CASES, CUT, DIMENSIONS, ENG, EX, GTIN_A, LK, MS, NO_LIMITATION, RES, RF, S, UQ, UR, VC, VL, X, add, L, nd,
    oss, patent, pk, prod_page, product, rec, repo, tl, trio, truth_links,
)
from generate_phase2j_gold_more import ACADEMIC, PARTIAL, chain_over

ACAD_UNITS = ["ACADEMIC_PHASE2E_GROUP:True"]
BLOCKED = dict(hyp__existence="LIMITATION_BLOCKED_SOURCE_QUALITY", hyp__posture="BLOCKED_SOURCE_QUALITY",
               claim__posture="BLOCKED_SOURCE_QUALITY", claim__existence=["LIMITATION_BLOCKED_SOURCE_QUALITY"],
               claim__linkage=["NONE_MATERIAL"], hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL",
               hyp__corroboration="NO_DIRECT_SUPPORT", hyp__scope="INSUFFICIENT_SCOPE", hyp__materiality=[],
               hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], link__n=0, link__relations=[],
               stmt__limitations=0, run__model_calls=1)
NOT_ESTABLISHED = dict(hyp__kind="UNRESOLVED", hyp__linkage="NONE_MATERIAL", hyp__posture="NOT_ESTABLISHED_WITHIN_BOUNDS",
                       claim__posture="NOT_ESTABLISHED_WITHIN_BOUNDS", claim__has_diff=False, claim__linkage=["NONE_MATERIAL"],
                       hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"], link__n=0, link__relations=[],
                       stmt__limitations=0)


def pair_over(P, lims, **extra):
    """Two limitations, both linked, validated from the claim."""
    base = dict(hyp__kind="ENGINEERING", lim__n=len(lims), lim__types=sorted(f"{x['type']}/{x['facet']}" for x in lims),
                lim__excerpts=sorted(x["excerpt"] for x in lims), lim__quality=["ELIGIBLE"] * len(lims),
                link__n=len(lims), link__relations=sorted([A] * len(lims)), stmt__limitations=len(lims),
                hyp__materiality=["CONDITION_NOT_MATERIAL"] * len(lims), val__metric=P.seg2,
                val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None, cap__excerpts=[P.cap])
    base.update(extra)
    return base


# ===========================================================================
# 11. INDEPENDENCE AND CORROBORATION (patent, academic)
# ===========================================================================


def s_independence(lang):
    P = pk(lang)
    a, b = L(P, P.short, MS, ENG, label="L1"), L(P, P.fail, RF, ENG, label="L2")
    both = S(EX([CAP(P)], [a, b], VC(P)), [LK(a, P), LK(b, P)])
    tr = truth_links(P, (P.short, A), (P.fail, A))
    r_a = rec("EP.1000001.A1", P, desc=f"{P.cap}. {P.short}.", family="7")
    r_b = rec("EP.1000002.B1", P, desc=f"{P.fail}.", family="7")
    add(["independence-two-publications-one-verified-family", "independence-record-count-is-not-corroboration"], lang, P,
        X(**pair_over(P, [a, b]), hyp__corroboration="SINGLE_SOURCE_DIRECT", indep__units=ACAD_UNITS + ["PATENT_FAMILY:True"]),
        patent=patent(r_a, r_b), script=both, truth=tr)
    f_a = rec("EP.1000003.A1", P, desc=f"{P.OTHER}.", family="8")
    f_b = rec("EP.1000004.B1", P, desc=f"{P.fail}.", family="8")
    r_c = rec("EP.1000002.B1", P, desc=f"{P.OTHER}.", family="7")
    add(["independence-two-verified-families-corroborate"], lang, P,
        X(**pair_over(P, [a, b]), hyp__corroboration="MULTI_SOURCE_CORROBORATED", indep__units=ACAD_UNITS + ["PATENT_FAMILY:True"]),
        patent=patent(r_a, r_c, f_a, f_b), script=both, truth=tr)
    one = S(EX([CAP(P)], [a], VC(P)), [LK(a, P)])
    unresolved = rec("EP.1000001.A1", P, desc=f"{P.cap}. {P.short}.", family="unavailable")
    add(["independence-unresolved-patent-family-is-not-corroboration", "independence-unresolved-supported-but-exposed"], lang, P,
        X(**pair_over(P, [a]), hyp__corroboration="UNRESOLVED_INDEPENDENCE",
          indep__units=ACAD_UNITS + ["PATENT_INDEPENDENCE_UNRESOLVED:False"]),
        patent=patent(unresolved), script=one, truth=truth_links(P, (P.short, A)))
    r_u = rec("EP.1000005.A1", P, desc=f"{P.fail}.", family="unavailable")
    add(["independence-unresolved-adds-nothing-beside-a-verified-family"], lang, P,
        X(**pair_over(P, [a, b]), hyp__corroboration="SINGLE_SOURCE_DIRECT",
          indep__units=ACAD_UNITS + ["PATENT_FAMILY:True", "PATENT_INDEPENDENCE_UNRESOLVED:False"]),
        patent=patent(r_a, rec("EP.1000002.B1", P, desc=f"{P.OTHER}.", family="7"), r_u), script=both, truth=tr)
    add(["independence-shared-source-two-limitations-not-two-units", "independence-explicit-singleton-family"], lang, P,
        X(**pair_over(P, [a, b]), hyp__corroboration="SINGLE_SOURCE_DIRECT"), script=both, truth=tr)


trio(s_independence)


def s_academic(lang):
    P = pk(lang)
    acad = L(P, ACADEMIC, MS, ENG, where="ACADEMIC_EXCERPT")
    script = S(EX([CAP(P)], [acad], VC(P)), [LK(acad, P)])
    # Phase 2E absent -> Phase 2I falls back to ONE full-claim feature (FULL_CLAIM_ONLY), so the
    # differentiating feature the model can link is the whole claim text.
    script_no_2e = S(EX([CAP(P)], [acad], VC(P)), [LK(acad, P, feature=P.claim)])
    over = dict(hyp__scope="SINGLE_SOURCE_BOUNDED", lim__excerpts=[ACADEMIC], lim__types=tl((MS, ENG)),
                cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None)
    add(["academic-phase2e-group-is-independent-corroboration-unit"], lang, P,
        X(**over, hyp__corroboration="SINGLE_SOURCE_DIRECT"), script=script, truth=truth_links(P, (ACADEMIC, A)))
    add(["academic-phase2e-absent-is-unresolved-independence", "phase2e-absence-is-not-insufficient-input"], lang, P,
        X(**over, hyp__corroboration="UNRESOLVED_INDEPENDENCE", indep__units=["ACADEMIC_UNGROUPED:False",
                                                                              "PATENT_SINGLETON_FAMILY:True"]),
        drop_sufficiency=True, script=script_no_2e, truth=truth_links(P, (ACADEMIC, A)))
    lim = L(P, P.short, MS, ENG)
    add(["phase2e-absent-patent-chain-still-assessed"], lang, P,
        X(**chain_over(P, lim), indep__units=["ACADEMIC_UNGROUPED:False", "PATENT_SINGLETON_FAMILY:True"]),
        drop_sufficiency=True, script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, feature=P.claim)]),
        truth=truth_links(P, (P.short, A)))


trio(s_academic)

# ===========================================================================
# 12. PRODUCT AND OPEN-SOURCE SOURCES
# ===========================================================================

U1, U2 = "https://aqua.example.com/spec", "https://aqua.example.com/spec-b"


def product_case(P, *, pages, vendor="DOCUMENTATION", **kw):
    return dict(patent={"records": []}, product=product(pages, vendor_kind=vendor), **kw)


def s_product(lang):
    P = pk(lang)
    body = f"{P.cap}. {P.short}. {P.fail}."
    lim = L(P, P.short, MS, ENG, where="PRODUCT_PAGE_TEXT")
    cap = CAP(P, where="PRODUCT_PAGE_TEXT")
    script = S(EX([cap], [lim], VL(P)), [LK(lim, P)])
    tr = truth_links(P, (P.short, A))
    chain = chain_over(P, lim)
    add(["source-product-first-party-documentation-eligible", "independence-product-strong-entity",
         "chronology-product-artifact-date-unknown"], lang, P,
        X(**chain, chron__buckets=["DATE_UNKNOWN"], indep__units=ACAD_UNITS + ["PRODUCT_STRONG_ENTITY:True"]),
        **product_case(P, pages={U1: prod_page(body)}), script=script, truth=tr)
    add(["independence-product-unresolved-entity-still-a-unit"], lang, P,
        X(**chain, indep__units=ACAD_UNITS + ["PRODUCT_UNRESOLVED_ENTITY:True"]),
        **product_case(P, pages={U1: prod_page(body, gtin=None)}), script=script, truth=tr)
    twin_a = L(P, P.short, MS, ENG, label="L1", where="PRODUCT_PAGE_TEXT", nth_text=1)
    twin_b = L(P, P.short, MS, ENG, label="L2", where="PRODUCT_PAGE_TEXT", nth_text=2)
    add(["independence-product-correlation-group-counts-once", "independence-product-duplicate-content-not-two-products"],
        lang, P,
        X(**pair_over(P, [twin_a, twin_b], link__n=1, link__relations=[A], stmt__limitations=1),
          hyp__corroboration="SINGLE_SOURCE_DIRECT", indep__units=ACAD_UNITS + ["PRODUCT_UNRESOLVED_ENTITY:True+corr"]),
        **product_case(P, pages={U1: prod_page(body, gtin=None), U2: prod_page(body, gtin=None)}),
        script=S(EX([cap], [twin_a, twin_b], VC(P)), [LK(twin_a, P)]), truth=tr)
    add(["source-product-unknown-role-limited-text-cannot-differentiate"], lang, P,
        X(**NOT_ESTABLISHED, lim__types=tl((MS, ENG)), lim__excerpts=[P.short], lim__quality=["ELIGIBLE"],
          cap__excerpts=[P.cap], val__metric=P.metric, val__metric_origin="LIMITATION_EVIDENCE", val__baseline=None,
          run__model_calls=2, indep__units=ACAD_UNITS + ["PRODUCT_STRONG_ENTITY:True"]),
        **product_case(P, pages={U1: prod_page(body)}, vendor=None), script=script, truth=tr)
    title_lim = L(P, P.title_lim_x, MS, ENG, where="PRODUCT_PAGE_TITLE")
    add(["source-product-title-only-limitation-blocked", "source-title-only-source"], lang, P,
        X(**BLOCKED, lim__types=tl((MS, ENG)), lim__excerpts=[P.title_lim_x], lim__quality=["INELIGIBLE_METADATA_TEXT"],
          cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None,
          indep__units=ACAD_UNITS + ["PRODUCT_STRONG_ENTITY:True"]),
        **product_case(P, pages={U1: prod_page(P.cap + ".", title=P.title_lim)}),
        script=S(EX([cap], [title_lim], VC(P)), []))
    for published, bucket, cats in (
        ("2018-05-01", "BEFORE_CUTOFF", ["chronology-product-artifact-before-cutoff", "chronology-source-reported-date-not-availability-proof"]),
        ("2020-01-01", "ON_CUTOFF", ["chronology-product-artifact-on-cutoff"]),
        ("2022-05-01", "AFTER_CUTOFF", ["chronology-product-artifact-after-cutoff"]),
    ):
        add(cats, lang, P, X(**chain, chron__buckets=[bucket], indep__units=ACAD_UNITS + ["PRODUCT_STRONG_ENTITY:True"]),
            **product_case(P, pages={U1: prod_page(body, published=published)}), script=script, truth=tr)


trio(s_product)

MANIFEST = {"acme/fall:requirements.txt": {"path": "requirements.txt", "text": "unrelated-package==1.0"}}


def readme(P, text=None):
    return {"acme/fall": {"path": "README.md", "text": text if text is not None else f"# {P.cap}. {P.short}. {P.fail}.", "sha": "a"}}


def oss_case(P, repos, **kw):
    return dict(patent={"records": []}, oss=oss(repos, **kw))


def s_oss(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG, where="OSS_README")
    cap = CAP(P, where="OSS_README")
    script = S(EX([cap], [lim], VL(P)), [LK(lim, P)])
    tr = truth_links(P, (P.short, A))
    chain = chain_over(P, lim)
    root = repo(901, "acme/fall", description="repo")
    add(["independence-oss-independent-root", "source-oss-readme-limited-eligible"], lang, P,
        X(**chain, indep__units=ACAD_UNITS + ["OSS_INDEPENDENT_ROOT_NETWORK:True"]),
        **oss_case(P, [root], readmes=readme(P), contents=MANIFEST), script=script, truth=tr)
    a = L(P, P.short, MS, ENG, label="L1", where="OSS_README", nth_text=1)
    b = L(P, P.short, MS, ENG, label="L2", where="OSS_README", nth_text=2)
    fork = repo(902, "octo/fall", fork=True, parent=(901, "acme/fall"), source=(901, "acme/fall"), description="fork")
    readmes2 = {**readme(P), "octo/fall": {"path": "README.md", "text": f"# {P.cap}. {P.short}. {P.fail}.", "sha": "b"}}
    manifests2 = {**MANIFEST, "octo/fall:requirements.txt": {"path": "requirements.txt", "text": "unrelated-package==1.0"}}
    add(["independence-oss-fork-is-not-an-independent-root", "independence-oss-fork-network-anti-inflation"], lang, P,
        X(**pair_over(P, [a, b], link__n=1, link__relations=[A], stmt__limitations=1),
          hyp__corroboration="SINGLE_SOURCE_DIRECT",
          indep__units=ACAD_UNITS + ["OSS_DEPENDENT_NETWORK:False", "OSS_INDEPENDENT_ROOT_NETWORK:True"]),
        **oss_case(P, [root, fork], readmes=readmes2, contents=manifests2),
        script=S(EX([cap], [a, b], VC(P)), [LK(a, P)]), truth=tr)
    mirror = repo(903, "acme/fall", mirror_url="https://example.org/fall.git", description="mirror")
    add(["independence-oss-mirror-is-not-an-independent-root"], lang, P,
        X(**chain, hyp__corroboration="UNRESOLVED_INDEPENDENCE", indep__units=ACAD_UNITS + ["OSS_DEPENDENT_NETWORK:False"]),
        **oss_case(P, [mirror], readmes=readme(P), contents=MANIFEST), script=script, truth=tr)
    derived = repo(121, "acme/fall", template=[120, "tpl/base"], description="derivative")
    add(["independence-oss-template-derivative-is-not-an-independent-root"], lang, P,
        X(**chain, hyp__corroboration="UNRESOLVED_INDEPENDENCE", indep__units=ACAD_UNITS + ["OSS_DEPENDENT_NETWORK:False"]),
        **oss_case(P, [derived], readmes=readme(P), contents=MANIFEST), script=script, truth=tr)
    manifest_lim = L(P, P.fail, RF, ENG, where="OSS_MANIFEST")
    add(["source-oss-manifest-token-match-is-not-a-limitation", "source-oss-manifest-never-limitation-evidence"], lang, P,
        X(**BLOCKED, lim__types=tl((RF, ENG)), lim__excerpts=[P.fail], lim__quality=["INELIGIBLE_METADATA_TEXT"],
          cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None,
          indep__units=ACAD_UNITS + ["OSS_INDEPENDENT_ROOT_NETWORK:True"]),
        **oss_case(P, [root], readmes=readme(P, f"# {P.cap}."), contents={"acme/fall:requirements.txt": {
            "path": "requirements.txt", "text": P.fail}}),
        script=S(EX([cap], [manifest_lim], VC(P)), []))
    desc_lim = L(P, P.fail, RF, ENG, where="OSS_DESCRIPTION")
    add(["source-oss-repository-description-is-metadata-not-limitation", "source-repository-metadata-not-evidence"], lang, P,
        X(**BLOCKED, lim__types=tl((RF, ENG)), lim__excerpts=[P.fail], lim__quality=["INELIGIBLE_METADATA_TEXT"],
          cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None,
          indep__units=ACAD_UNITS + ["OSS_INDEPENDENT_ROOT_NETWORK:True"]),
        **oss_case(P, [repo(901, "acme/fall", description=P.fail)], readmes=readme(P, f"# {P.cap}."), contents=MANIFEST),
        script=S(EX([cap], [desc_lim], VC(P)), []))
    frag = L(P, P.fail, RF, ENG, where="OSS_CODE_FRAGMENT")
    code = [{"id": 901, "full_name": "acme/fall", "path": "src/main.py", "fragment": f"# {P.fail}"}]
    add(["source-oss-code-fragment-limited-eligible"], lang, P,
        X(**pair_over(P, [frag]), indep__units=ACAD_UNITS + ["OSS_INDEPENDENT_ROOT_NETWORK:True"]),
        **oss_case(P, [root], readmes=readme(P, f"# {P.cap}."), contents=MANIFEST, code=code),
        script=S(EX([cap], [frag], VC(P)), [LK(frag, P)]), truth=truth_links(P, (P.fail, A)))
    for repo_kw, extra, bucket, cat in (
        ({"created_at": "2018-03-01T10:00:00Z"}, {}, "BEFORE_CUTOFF", "chronology-oss-created-at-not-public-since"),
        ({"created_at": None}, {"commits": {"acme/fall": {"sha": "b" * 40, "commit": {
            "author": {"date": "2017-01-01T00:00:00Z"}, "committer": {"date": "2017-01-02T00:00:00Z"}}}}}, "BEFORE_CUTOFF",
         "chronology-oss-commit-date-not-availability-proof"),
        ({"created_at": "2018-03-01T10:00:00Z"}, {"releases": {"acme/fall": [{"id": 1, "tag_name": "v1.0",
         "created_at": "2021-03-01T00:00:00Z", "published_at": "2021-03-02T00:00:00Z"}]}}, "AFTER_CUTOFF",
         "chronology-oss-release-date-after-cutoff"),
    ):
        add([cat], lang, P, X(**chain, chron__buckets=[bucket], indep__units=ACAD_UNITS + ["OSS_INDEPENDENT_ROOT_NETWORK:True"]),
            **oss_case(P, [repo(901, "acme/fall", description="repo", **repo_kw)], readmes=readme(P), contents=MANIFEST, **extra),
            script=script, truth=tr)


trio(s_oss)

# ===========================================================================
# 13. SOURCE QUALITY, ANCHORS
# ===========================================================================


def s_quality(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    link = [LK(lim, P)]
    acad = L(P, ACADEMIC, MS, ENG, where="ACADEMIC_EXCERPT")
    add(["source-retracted-academic-limitation-blocked"], lang, P,
        X(**BLOCKED, lim__types=tl((MS, ENG)), lim__excerpts=[ACADEMIC], lim__quality=["INELIGIBLE_RETRACTED"],
          cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None,
          indep__units=ACAD_UNITS + ["PATENT_SINGLETON_FAMILY:True"]),
        retract_academic=True, script=S(EX([CAP(P)], [acad], VC(P)), []))
    title_lim = L(P, P.title_lim_x, MS, ENG, where="PATENT_TITLE")
    add(["source-patent-title-only-limitation-blocked", "source-title-only-source"], lang, P,
        X(**BLOCKED, lim__types=tl((MS, ENG)), lim__excerpts=[P.title_lim_x], lim__quality=["INELIGIBLE_METADATA_TEXT"],
          cap__excerpts=[P.cap], val__metric=P.seg2, val__metric_origin="STUDENT_CLAIM_TEXT", val__baseline=None),
        patent=patent(rec("EP.1000001.A1", P, title=P.title_lim)), script=S(EX([CAP(P)], [title_lim], VC(P)), []))
    add(["source-ineligible-limitation-beside-eligible-is-ignored"], lang, P,
        X(**chain_over(P, lim, lim__n=2, lim__types=tl((MS, ENG), (MS, ENG)), lim__excerpts=sorted([P.short, P.title_lim_x]),
                       lim__quality=["ELIGIBLE", "INELIGIBLE_METADATA_TEXT"],
                       hyp__materiality=["CONDITION_NOT_MATERIAL"]),),
        patent=patent(rec("EP.1000001.A1", P, title=P.title_lim)),
        script=S(EX([CAP(P)], [lim, L(P, P.title_lim_x, MS, ENG, label="L2", where="PATENT_TITLE")], VL(P)), link),
        truth=truth_links(P, (P.short, A)))
    claims_lim = L(P, P.fail, RF, ENG, where="PATENT_CLAIMS")
    add(["source-patent-claims-text-eligible"], lang, P,
        X(**pair_over(P, [claims_lim])), patent=patent(rec("EP.1000001.A1", P, claims=f"1. {P.claim}. 2. {P.fail}.")),
        script=S(EX([CAP(P)], [claims_lim], VC(P)), [LK(claims_lim, P)]), truth=truth_links(P, (P.fail, A)))
    from_claim = L(P, P.seg2, UR, ENG, where="ACADEMIC_EXCERPT")
    add(["student-claim-text-as-limitation-evidence-refused", "student-claim-not-evidence"], lang, P,
        X(**NO_LIMITATION, rejected=["CLAIM_TEXT_AS_EVIDENCE"], issues=["FABRICATED_ANCHOR"], run__model_calls=1),
        script=S(EX([CAP(P)], [from_claim], VC(P))), truth={"inadmissible": {C1: [P.seg2]}})
    fake = L(P, P.short.replace("61", "12"), MS, ENG)
    add(["fabricated-limitation-excerpt-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["EXCERPT_NOT_IN_TEXT"], issues=["FABRICATED_ANCHOR"], run__model_calls=1),
        script=S(EX([CAP(P)], [fake], VC(P))))
    bad_token = L(P, P.short, MS, ENG, token="T99")
    add(["fabricated-text-reference-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["UNKNOWN_TEXT_REFERENCE"], issues=["FABRICATED_ANCHOR", "OFF_CONTRACT_OUTPUT"], run__model_calls=1),
        script=S(EX([CAP(P)], [bad_token], VC(P))))
    rep = L(P, P.rep_phrase, UQ, RES)
    add(["repeated-excerpt-ambiguous-without-disambiguator-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["AMBIGUOUS_REPEATED_EXCERPT"], issues=["AMBIGUOUS_ANCHOR"], run__model_calls=1),
        script=S(EX([CAP(P)], [rep], VC(P))))
    rep2 = L(P, P.rep_phrase, UQ, RES, occurrence=2)
    add(["repeated-excerpt-bound-by-validated-occurrence-index"], lang, P,
        X(**pair_over(P, [rep2], hyp__kind="RESEARCH")),
        script=S(EX([CAP(P)], [rep2], VC(P)), [LK(rep2, P)]), truth=truth_links(P, (P.rep_phrase, A)))
    add(["repeated-excerpt-invalid-occurrence-index-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_OCCURRENCE_INDEX"], run__model_calls=1),
        script=S(EX([CAP(P)], [L(P, P.rep_phrase, UQ, RES, occurrence=9)], VC(P))))
    add(["anchor-invalid-offsets-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_OFFSETS"], issues=[], run__model_calls=1),
        script=S(EX([CAP(P)], [L(P, P.short, MS, ENG, start=3, end=9)], VC(P))))


trio(s_quality)

# ===========================================================================
# 14. CHRONOLOGY (patent dates), separate from gap support
# ===========================================================================


def s_chronology(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    script = S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P)])
    tr = truth_links(P, (P.short, A))
    chain = chain_over(P, lim)
    cases = (
        ("2020-01-01", {}, CUT, "ON_CUTOFF", "chronology-patent-publication-on-cutoff"),
        ("2022-03-04", {}, CUT, "AFTER_CUTOFF", "chronology-patent-publication-after-cutoff"),
        (None, {}, CUT, "DATE_UNKNOWN", "chronology-patent-publication-date-unknown"),
        ("2015-06-01", {}, None, "NO_CUTOFF", "chronology-no-cutoff-supplied"),
        ("2021-05-01", {"filing_date": "2018-01-01", "priority_date": "2017-01-01"}, CUT, "AFTER_CUTOFF",
         "chronology-publication-date-governs-over-filing-and-priority"),
        (None, {"filing_date": "2016-01-01", "priority_date": "2015-01-01"}, CUT, "DATE_UNKNOWN",
         "chronology-filing-and-priority-are-not-public-dates"),
    )
    for date, extra, cutoff, bucket, cat in cases:
        add([cat, "chronology-separate-from-gap-support"], lang, P, X(**chain, chron__buckets=[bucket]),
            cutoff=cutoff, patent=patent(rec("EP.1000001.A1", P, date=date, **extra)), script=script, truth=tr)


trio(s_chronology)
