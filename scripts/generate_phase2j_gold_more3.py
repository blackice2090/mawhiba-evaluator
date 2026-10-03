"""Phase 2J Gold scenarios, part 3: prompt injection and model prose, replay, run binding.
See generate_phase2j_gold.py."""

from __future__ import annotations

from generate_phase2j_gold_core import (
    A, C1, CAP, EL, ENG, EX, LK, MS, NO_HYP, NO_LIMITATION, RES, S, VC, VL, X, add, L, pk, trio, truth_links,
)
from generate_phase2j_gold_more import chain_over
from generate_phase2j_gold_more2 import NOT_ESTABLISHED, pair_over

FORBIDDEN_PROSE = "This project is novel and patentable."
INSUFFICIENT = dict(NO_HYP, claim__posture="INSUFFICIENT_INPUT", claim__existence=[], claim__linkage=[], rejected=[],
                    run__model_calls=1)
NO_LINK = dict(NOT_ESTABLISHED, claim__posture="DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP", claim__has_diff=True,
               hyp__missing=["FULL_PROJECT_LINKAGE", "RESOLVED_GAP_KIND"])


def s_injection(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    link = [LK(lim, P)]
    tr = truth_links(P, (P.short, A))
    std = chain_over(P, lim)
    quoted = L(P, P.inj, EL, RES)
    add(["injection-instruction-like-source-text-is-inert-evidence", "injection-source-text-eligible-when-anchored"], lang, P,
        X(**pair_over(P, [quoted], hyp__kind="RESEARCH")), script=S(EX([CAP(P)], [quoted], VC(P)), [LK(quoted, P)]),
        truth={**truth_links(P, (P.inj, A)), "injection": [P.inj]})
    leaking = L(P, P.short, MS, ENG, leak_system_prompt=True)
    add(["leak-hidden-prompt-in-rationale-refused", "injection-model-leaks-system-prompt"], lang, P,
        X(**NO_LIMITATION, rejected=["SYSTEM_PROMPT_DISCLOSURE"], issues=["PROMPT_LEAK_REDACTED"], run__model_calls=1),
        script=S(EX([CAP(P)], [leaking], VC(P))))
    label_leak = L(P, P.short, MS, ENG, label="$LEAK")
    add(["leak-hidden-prompt-in-label-never-persisted"], lang, P, X(**std),
        script=S(EX([CAP(P)], [label_leak], {"metric_source": "$LEAK", "metric": P.metric}), [LK(label_leak, P)]),
        truth=tr)
    type_leak = L(P, P.short, "$LEAK", ENG)
    add(["leak-hidden-prompt-in-type-field-refused", "off-contract-invalid-limitation-type-leak"], lang, P,
        X(**NO_LIMITATION, rejected=["INVALID_LIMITATION_TYPE"], issues=["OFF_CONTRACT_OUTPUT"], run__model_calls=1),
        script=S(EX([CAP(P)], [type_leak], VC(P))))
    add(["leak-hidden-prompt-in-metric-refused", "invented-metric-from-leak"], lang, P,
        X(**{**std, "val__metric": None, "val__metric_origin": None}, rejected=["INVENTED_METRIC"],
          issues=["INVENTED_METRIC"], hyp__missing=["VALIDATION_REQUIREMENT"], hyp__posture="PARTIALLY_SUPPORTED",
          claim__posture="PARTIALLY_SUPPORTED"),
        script=S(EX([CAP(P)], [lim], {"metric_source": "L1", "metric": "$LEAK"}), link), truth=tr)
    for kind, cat in (("refusal_leak", "leak-hidden-prompt-in-provider-refusal-never-persisted"),
                      ("error_leak", "leak-hidden-prompt-in-provider-error-never-persisted")):
        add([cat, "model-call-failure-is-insufficient-not-no-gap"], lang, P,
            X(**INSUFFICIENT, claim__reasons=["MODEL_CALL_FAILED"], issues=["MODEL_ERROR"]),
            script={"extract": {C1: kind}, "link": {C1: []}, "counter": {C1: []}})
    add(["off-contract-forbidden-typed-field-is-a-failed-call", "off-contract-forbidden-score-field"], lang, P,
        X(**INSUFFICIENT, claim__reasons=["MODEL_CALL_FAILED"], issues=["MODEL_ERROR"]),
        script={"extract": {C1: "parse_error"}, "link": {C1: []}, "counter": {C1: []}})
    bad = L(P, P.short, MS, ENG, rationale=FORBIDDEN_PROSE)
    add(["forbidden-conclusion-in-model-prose-refused"], lang, P,
        X(**NO_LIMITATION, rejected=["FORBIDDEN_CONCLUSION"], issues=["FORBIDDEN_CONCLUSION"], run__model_calls=1),
        script=S(EX([CAP(P)], [bad], VC(P))))
    add(["model-proposed-kind-is-recorded-never-trusted"], lang, P, X(**std),
        script=S(EX([CAP(P)], [lim], VL(P), proposed_kind="HYBRID"), link), truth=tr)
    add(["model-prose-noncanonical-same-typed-facts-same-output"], lang, P, X(**std, prose__same=True), twin="prose",
        script=S(EX([CAP(P)], [lim], VL(P)), link), truth=tr)
    add(["model-prose-cannot-override-posture-on-unlinked-limitation"], lang, P,
        X(**{**std, **NO_LINK, "link__relations": ["UNRELATED"], "link__n": 1}, prose__same=True), twin="prose",
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, "UNRELATED")]), truth=truth_links(P, (P.short, "UNRELATED")))
    leak_link = LK(lim, P, leak_system_prompt=True)
    add(["leak-hidden-prompt-in-linkage-rationale-refused"], lang, P,
        X(**{**std, **NO_LINK}, rejected=["SYSTEM_PROMPT_DISCLOSURE"], issues=["PROMPT_LEAK_REDACTED"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [leak_link]), truth=tr)
    add(["forbidden-conclusion-in-linkage-prose-refused"], lang, P,
        X(**{**std, **NO_LINK}, rejected=["FORBIDDEN_CONCLUSION"], issues=["FORBIDDEN_CONCLUSION"]),
        script=S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P, rationale=FORBIDDEN_PROSE)]), truth=tr)
    leak_counter = {"kind": "LIMITATION_ADDRESSED", "condition_match": "SAME_CONDITION", "excerpt": P.counter_same,
                    "leak_system_prompt": True}
    add(["leak-hidden-prompt-in-counterevidence-rationale-refused"], lang, P,
        X(**std, rejected=["SYSTEM_PROMPT_DISCLOSURE"], issues=["PROMPT_LEAK_REDACTED"]),
        script=S(EX([CAP(P)], [lim], VL(P)), link, [leak_counter]), truth=tr)


trio(s_injection)


def s_replay(lang):
    P = pk(lang)
    lim = L(P, P.short, MS, ENG)
    script = S(EX([CAP(P)], [lim], VL(P)), [LK(lim, P)])
    tr = truth_links(P, (P.short, A))
    std = chain_over(P, lim)
    add(["replay-over-a-finished-run-makes-no-model-call"], lang, P, X(**std, replay__extra_calls=0, replay__same=True),
        rerun=True, script=script, truth=tr)
    add(["resume-from-checkpoint-matches-uninterrupted-run"], lang, P, X(**std, resume__same=True),
        interrupt_before="VERIFY_GAP_PROJECT_LINKAGE", script=script, truth=tr)
    a, b = L(P, P.short, MS, ENG, label="L1"), L(P, P.fail, "REPORTED_FAILURE_MODE", ENG, label="L2")
    add(["input-order-invariance-and-deterministic-ids"], lang, P,
        X(**pair_over(P, [a, b]), order__same=True, ids__same=True), twin="order",
        script=S(EX([CAP(P)], [a, b], VC(P)), [LK(a, P), LK(b, P)]), truth=truth_links(P, (P.short, A), (P.fail, A)))
    stale = {"run.status": "COMPLETED", "run.search_calls": 0, "hyp.exists": False, "bind.mutation_detected": True,
             "claim.posture": "INSUFFICIENT_INPUT"}
    add(["binding-claim-text-edited-after-binding-is-unbound"], lang, P,
        {**stale, "claim.reasons": ["CLAIM_TEXT_HASH_MISMATCH"], "run.issues": ["STALE_UPSTREAM_HASH"]},
        mutate="claim_edit", script=script)
    add(["binding-upstream-subrun-mutated-downgrades-the-run"], lang, P,
        {**stale, "run.status": "INSUFFICIENT_INPUT", "claim.reasons": ["UPSTREAM_MUTATED"], "run.issues": ["UPSTREAM_MUTATED"]},
        mutate="upstream_mutation", script=script)
    add(["no-provider-is-insufficient-input-never-no-gap"], lang, P,
        X(**NO_HYP, claim__posture="INSUFFICIENT_INPUT", claim__reasons=["MODEL_PROVIDER_MISSING"], claim__existence=[],
          claim__linkage=[], rejected=[], run__model_calls=0, run__issues=["MODEL_PROVIDER_MISSING"]),
        no_model=True, script={})
    add(["model-call-bound-reached-is-insufficient-input"], lang, P,
        X(**NO_HYP, claim__posture="INSUFFICIENT_INPUT", claim__reasons=["MODEL_CALL_BOUND_REACHED"], claim__existence=[],
          claim__linkage=[], rejected=[], run__model_calls=0),
        bounds={"max_model_calls": 0}, script=script)
    add(["extraction-call-failure-is-insufficient-input"], lang, P,
        X(**INSUFFICIENT, claim__reasons=["MODEL_CALL_FAILED"], issues=["MODEL_ERROR"]),
        script={"extract": {C1: "provider_error"}, "link": {C1: []}, "counter": {C1: []}})
    add(["linkage-call-failure-is-insufficient-input"], lang, P,
        X(**NO_HYP, claim__posture="INSUFFICIENT_INPUT", claim__reasons=["MODEL_CALL_FAILED"], claim__existence=[],
          claim__linkage=[], rejected=[], issues=["MODEL_ERROR"], run__model_calls=2),
        script={"extract": {C1: EX([CAP(P)], [lim], VL(P))}, "link": {C1: "provider_error"}, "counter": {C1: []}})
    claims = [{"claim_id": C1, "claim": P.claim}, {"claim_id": "C-002", "claim": P.claim2}]
    add(["multi-claim-claims-assessed-independently", "binding-no-cross-claim-leakage"], lang, P,
        X(**std, **{"C-002:claim.posture": "INSUFFICIENT_INPUT", "run.claims": 2, "run.hypotheses": 1}),
        claims=claims, script=script, truth=tr)


trio(s_replay)
