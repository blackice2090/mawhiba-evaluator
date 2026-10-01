"""Phase 2H.1A -- the content-identity gates count real opportunities only.

A case with no byte-identical artifacts, no conflicting strong identifiers or
no verified entity must add zero to the matching denominator; there is no
synthetic per-case minimum.
"""

from __future__ import annotations

import pytest

from src.evals.product_oss_prior_art.dataset import load_cases
from src.evals.product_oss_prior_art.metrics import build_report
from src.evals.product_oss_prior_art.runner import run_case

NEW_GATES = (
    "content_hash_product_merge",
    "distinct_strong_ids_collapsed",
    "content_hash_as_verified_identity",
    "duplicate_content_relation_lost",
)

# case id -> (hash groups, conflicting-key pairs, verified entities, duplicate entity pairs)
PINNED = {
    "PH-239": (1, 2, 0, 1),
    "PH-240": (2, 0, 1, 4),
    "PH-241": (1, 0, 1, 0),
    "PH-242": (1, 0, 0, 1),
    "PH-102": (0, 1, 0, 0),
}
NO_DUPLICATES = ("PH-001", "PH-002", "PH-003")


@pytest.fixture(scope="module")
def cases():
    return {c.case_id: c for c in load_cases()}


def _den(result):
    return tuple(result.gates[g][1] for g in NEW_GATES)


@pytest.mark.parametrize("case_id", NO_DUPLICATES)
def test_case_without_duplicates_or_conflicts_contributes_zero(cases, case_id):
    result = run_case(cases[case_id])
    assert result.error is None
    den = _den(result)
    assert den[0] == 0 and den[1] == 0 and den[3] == 0


@pytest.mark.parametrize("case_id", sorted(PINNED))
def test_duplicate_and_conflict_cases_contribute_exact_counts(cases, case_id):
    result = run_case(cases[case_id])
    assert _den(result) == PINNED[case_id]
    assert all(result.gates[g][0] == 0 for g in NEW_GATES)


def test_conflicting_ids_count_only_when_a_conflict_exists(cases):
    assert _den(run_case(cases["PH-241"]))[1] == 0  # duplicates, but one strong id
    assert _den(run_case(cases["PH-102"]))[1] == 1


def test_denominators_are_deterministic_and_order_independent(cases):
    ids = sorted(PINNED)
    forward = {i: _den(run_case(cases[i])) for i in ids}
    backward = {i: _den(run_case(cases[i])) for i in reversed(ids)}
    assert forward == backward


def test_gold_has_real_nonzero_aggregate_denominator_and_zero_violations():
    report = build_report([run_case(c) for c in load_cases()])
    for gate in NEW_GATES:
        num, den = report.gates[gate]
        assert num == 0 and den > 0, gate
