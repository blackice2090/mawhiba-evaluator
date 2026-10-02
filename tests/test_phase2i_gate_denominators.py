"""Phase 2I safety-gate denominator integrity.

Quality-metric families may overlap: one relation judgment can legitimately feed
"relation-kind accuracy" and "patent disclosure accuracy". Safety-gate
opportunity counts may not. A gate denominator is the number of real
opportunities that gate checked -- exactly once each, independent of how many
quality families an expectation belongs to, independent of candidate order, and
never floored: a case with no relevant opportunity contributes zero.
"""

from __future__ import annotations

import copy

import pytest

from src.evals.novelty_differentiation.dataset import load_cases
from src.evals.novelty_differentiation.metrics import build_report
from src.evals.novelty_differentiation.runner import GATE_FUNCS, GATES, Ctx, run_case

CASES = load_cases()


def pick(category: str, lang: str = "en"):
    return next(c for c in CASES if category in c.categories and c.language == lang)


@pytest.fixture(scope="module")
def singleton():
    result = run_case(pick("p-family-singleton-established-by-phase2g"))
    assert result.error is None, result.error
    return result


@pytest.fixture(scope="module")
def relation_case():
    result = run_case(pick("p-claims-disclose-component"))
    assert result.error is None, result.error
    return result


@pytest.fixture(scope="module")
def mosaic():
    result = run_case(pick("t-cross-candidate-mosaic-not-single-candidate-full-overlap"))
    assert result.error is None, result.error
    return result


@pytest.fixture(scope="module")
def empty():
    result = run_case(pick("n-no-candidate-found-not-novel"))
    assert result.error is None, result.error
    return result


def anchors(d):
    return [a for c in d["comparisons"] for a in c["anchors"]]


# A. one real opportunity contributes exactly once --------------------------


def test_one_anchor_is_one_opportunity_for_each_anchor_gate(singleton):
    d = singleton.ctx.d
    actual = len(anchors(d))
    assert actual == 5, "the fixture's single full overlap carries exactly five anchors"
    for gate in ("fabricated_candidate_excerpt_accepted", "wrong_snapshot_anchor_accepted"):
        assert singleton.gates[gate] == (0, actual), gate


def test_denominators_equal_independently_counted_opportunities(singleton):
    d = singleton.ctx.d
    comparisons, profiles, syntheses = d["comparisons"], d["candidate_profiles"], d["claim_syntheses"]
    verified = [c for c in comparisons if c["status"] == "VERIFIED"]
    features = sum(len(i["features"]) for i in d["inventories"])
    anchored_records = sum(1 for c in verified for r in c["feature_records"]
                           if r["relation"] in ("DISCLOSED", "PARTIALLY_DISCLOSED", "RELATED_CONTEXT"))
    expected = {
        "project_state_mutation": 1,
        "fabricated_claim_feature_accepted": features,
        "fabricated_candidate_excerpt_accepted": len(anchors(d)),
        "wrong_snapshot_anchor_accepted": len(anchors(d)),
        "candidate_identity_lost": len(comparisons),
        "candidate_type_semantics_conflated": len(profiles),
        "source_quality_collapsed_into_opaque_numeric_weight": len(profiles),
        "model_relation_accepted_without_deterministic_anchor_validation": anchored_records,
        "final_posture_without_traceable_basis": len(syntheses),
        "no_legal_novelty_limitation_omitted": len(syntheses) + 1,  # each posture + the project summary
        "bounded_comparison_limitation_omitted": len(syntheses) + len(verified),
        "provider_credential_persisted": 0,  # the case configures no credential
        # every verified comparison is checked for prompt leakage; the case sets
        # no injection flag, so there is no extra structural opportunity
        "prompt_injection_followed": len(verified),
    }
    for gate, count in expected.items():
        assert singleton.gates[gate][1] == count, f"{gate}: {singleton.gates[gate]} != {count}"


# B. overlapping quality-family membership never changes a gate ---------------


def test_quality_family_membership_does_not_change_gate_denominators(relation_case):
    case = relation_case.case
    assert any(key.startswith("rel.") for key in case.expected)
    reduced = run_case(case.model_copy(update={"expected": {"status": "COMPLETED"}}))
    assert reduced.error is None
    assert reduced.gates == relation_case.gates
    # ...while the quality side really is attributed to several families: one
    # authored relation feeds relation-kind accuracy AND source disclosure accuracy.
    attributed = {f for f, (_, den) in relation_case.quality.items() if den}
    assert {"patent_disclosure_accuracy", "component_relation_accuracy"} <= attributed
    q = relation_case.quality
    # Every authored pair is counted once in its source family and once in its
    # relation-kind family: 5 pairs = 3 component-type + 2 combination-type.
    assert q["patent_disclosure_accuracy"][1] == q["component_relation_accuracy"][1] + q["combination_relation_accuracy"][1] == 5
    assert sum(den for _, den in relation_case.quality.values()) > sum(den for _, den in reduced.quality.values())


# C. candidate input order never changes a denominator ------------------------


def test_candidate_order_does_not_change_any_gate(mosaic):
    ctx = mosaic.ctx
    assert len(ctx.d["comparisons"]) >= 2
    shuffled = copy.deepcopy(ctx.d)
    for key in ("comparisons", "candidate_profiles", "inventories", "claim_syntheses"):
        shuffled[key] = list(reversed(shuffled[key]))
    clone = Ctx(**{**ctx.__dict__, "d": shuffled})
    for gate in GATES:
        assert GATE_FUNCS[gate](clone) == mosaic.gates[gate], gate


# D / E. zero relevant opportunities contributes zero, with no synthetic floor ---


def test_a_case_with_no_candidates_contributes_zero_to_candidate_gates(empty):
    for gate in (
        "fabricated_candidate_excerpt_accepted", "wrong_snapshot_anchor_accepted", "candidate_identity_lost",
        "candidate_type_semantics_conflated", "source_quality_collapsed_into_opaque_numeric_weight",
        "model_relation_accepted_without_deterministic_anchor_validation", "bounded_no_overlap_reported_worldwide_novelty",
        "material_overlap_reported_legal_anticipation", "post_cutoff_represented_as_pre_cutoff_disclosure",
    ):
        assert empty.gates[gate] == (0, 0), gate
    # ...but the gates this case genuinely exercises are still counted exactly.
    assert empty.gates["no_candidate_found_reported_novel"] == (0, 1)


def test_report_applies_no_denominator_floor(empty):
    report = build_report([empty])
    assert report.gates["candidate_identity_lost"] == (0, 0)
    assert not report.gates_zero, "a gate with no opportunity must read as unmeasured, never as passing"


def test_gate_count_matches_the_specification():
    assert len(GATES) == 78 and len(set(GATES)) == 78


# G. gate 68 scope: Phase 2I-owned output only ---------------------------------


def test_injection_score_check_ignores_upstream_phase2f_scoring_and_counts_each_class_once():
    from src.evals.novelty_differentiation.dataset import load_cases
    from src.evals.novelty_differentiation.runner import FORBIDDEN_KEYS, has_key

    case = next(c for c in load_cases() if c.injection)
    result = run_case(case)
    assert result.error is None
    ctx = result.ctx
    # The run legitimately carries Phase 2F scoring upstream; it is outside the check.
    assert ctx.run.claim_evidence_scoring is not None
    assert not has_key(ctx.d, FORBIDDEN_KEYS["score"])  # Phase 2I-owned output only
    violations, denominator = result.gates["prompt_injection_followed"]
    assert violations == 0
    # leak class: one opportunity per verified comparison; structural class: one per injection case
    assert denominator == len(ctx.verified()) + 1
