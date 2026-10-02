"""Phase 2I offline Gold eval, run through pytest.

Runs every Gold case once (real 2E -> 2F -> 2G -> 2H -> 2I graphs against
scripted providers and a scripted structured model; no network) and asserts the
release conditions: dataset minimums, no errored case, every authored
expectation met, every quality family exactly 1.0, every release-blocking gate
zero WITH a real non-zero denominator, and every negative control caught.
"""

from __future__ import annotations

import pytest

from src.evals.novelty_differentiation.dataset import DEFAULT_DATASET, load_cases
from src.evals.novelty_differentiation.metrics import (
    MIN_ARABIC,
    MIN_CATEGORIES,
    MIN_MIXED,
    MIN_TOTAL,
    REQUIRED_CONTROLS,
    REQUIRED_QUALITY_FAMILIES,
    build_report,
)
from src.evals.novelty_differentiation.runner import CONTROLS, GATES, SPECIAL_CONTROLS, run_case


@pytest.fixture(scope="module")
def cases():
    return load_cases(DEFAULT_DATASET)


@pytest.fixture(scope="module")
def results(cases):
    return [run_case(case) for case in cases]


@pytest.fixture(scope="module")
def report(results):
    return build_report(results)


def test_dataset_meets_the_specified_minimums(report):
    assert report.total >= MIN_TOTAL
    assert report.languages.get("ar", 0) >= MIN_ARABIC
    assert report.languages.get("mixed", 0) >= MIN_MIXED
    assert report.categories >= MIN_CATEGORIES


def test_dataset_covers_patent_product_and_open_source(cases):
    tracks = {"PATENT": 0, "PRODUCT": 0, "OPEN_SOURCE": 0}
    for case in cases:
        tracks["PATENT"] += bool(case.patent.get("records"))
        tracks["PRODUCT"] += bool(case.product.get("pages"))
        tracks["OPEN_SOURCE"] += bool(case.oss.get("repos"))
    assert all(count >= 20 for count in tracks.values()), tracks


def test_no_case_errored_and_every_authored_expectation_held(report):
    assert report.errored == []
    assert report.failed_cases == [], report.failures[:10]


def test_every_required_quality_family_is_measured_and_perfect(report):
    for family in REQUIRED_QUALITY_FAMILIES:
        assert report.quality[family] is not None, f"{family} has no denominator (not measured)"
        assert report.quality[family] == 1.0, f"{family}: {report.quality_counts[family]}"
    assert report.per_language_perfect


def test_every_release_blocking_gate_is_zero_with_a_real_denominator(report):
    assert len(report.gates) == 78
    for gate, (violations, denominator) in report.gates.items():
        assert denominator > 0, f"{gate} has no Gold opportunities (safeguard F)"
        assert violations == 0, f"{gate}: {violations}/{denominator}"


def test_every_negative_control_is_caught(report, results):
    assert report.controls[1] > 0 and report.controls[0] == report.controls[1]
    assert len(report.control_names) >= REQUIRED_CONTROLS
    attempted = set(report.control_names)
    assert set(CONTROLS) | set(SPECIAL_CONTROLS) == attempted, sorted((set(CONTROLS) | set(SPECIAL_CONTROLS)) ^ attempted)
    for result in results:
        for name, caught, _ in result.controls:
            assert caught is True, f"{result.case.case_id}: control {name} was not caught"


def test_the_whole_eval_passes(report):
    assert report.passed


def test_every_gate_listed_in_the_runner_is_reported(report):
    assert list(report.gates) == GATES
