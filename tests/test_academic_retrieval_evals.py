"""The academic retrieval Gold dataset, its metrics, and its negative controls.

A safety suite that cannot fail proves nothing, so the last section deliberately
corrupts a correct result and asserts that each release-blocking metric notices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.evals.academic.cli import main as academic_cli
from src.evals.academic.dataset import (
    DEFAULT_ACADEMIC_DATASET_VERSION,
    academic_dataset_path,
    build_query_plan,
    gold_run_id,
    load_academic_dataset,
)
from src.evals.academic.metrics import (
    RELEASE_BLOCKING_ACADEMIC_METRICS,
    AcademicRetrievalMetrics,
)
from src.evals.academic.runner import (
    AcademicCaseResult,
    evaluate_academic_gate,
    run_academic_case,
    run_academic_dataset,
    score_academic_case,
    score_by_language,
)
from src.schemas.academic import (
    AcademicBudgetReport,
    AcademicIdentifiers,
    AcademicProvider,
    AcademicRetrievalResult,
    LogicalAcademicSource,
    ProviderObservation,
)
from src.schemas.common import new_source_id
from src.schemas.research import QueryStatus
from src.schemas.source import SourceFingerprint, SourceIdentifierKind

MINIMUM_GOLD_CASES = 40
RETRIEVED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)

REQUIRED_CATEGORIES = {
    "same_doi_all_providers",
    "doi_formatting",
    "title_is_not_identity",
    "missing_doi",
    "openalex_only_identifier",
    "semantic_scholar_only_identifier",
    "preprint",
    "review",
    "conference_paper",
    "unknown_source_type",
    "retracted_source",
    "retraction_unknown",
    "conflicting_years",
    "conflicting_titles",
    "citation_disagreement",
    "empty_result",
    "timeout",
    "rate_limit",
    "auth_failure",
    "all_providers_fail",
    "malformed_record",
    "within_provider_duplicate",
    "pii_contamination",
    "prompt_injection",
    "arabic_query",
    "mixed_language_query",
    "query_budget_truncation",
    "provider_result_limit",
    "project_state_immutability",
    "no_evidence_creation",
    "no_claim_mutation",
}


@pytest.fixture(scope="module")
def dataset():
    return load_academic_dataset()


@pytest.fixture(scope="module")
def scored(dataset):
    metrics, results = run_academic_dataset(dataset)
    return metrics, results


# ===========================================================================
# Dataset integrity
# ===========================================================================


def test_the_dataset_file_exists_and_is_reviewable() -> None:
    path = academic_dataset_path(DEFAULT_ACADEMIC_DATASET_VERSION)
    assert path.exists()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= MINIMUM_GOLD_CASES, "one case per line, reviewable in a diff"


def test_the_dataset_meets_the_required_size(dataset) -> None:
    assert len(dataset.cases) >= MINIMUM_GOLD_CASES


def test_the_dataset_covers_every_required_edge_case(dataset) -> None:
    covered = set(dataset.category_counts)
    assert REQUIRED_CATEGORIES <= covered, sorted(REQUIRED_CATEGORIES - covered)


def test_the_dataset_covers_more_than_one_language(dataset) -> None:
    counts = dataset.language_counts
    assert counts.get("ar", 0) >= 1
    assert counts.get("mixed", 0) >= 1
    assert counts.get("en", 0) >= 1


def test_case_structure_is_english_even_where_values_are_not(dataset) -> None:
    for case in dataset.cases:
        assert case.case_id.isascii()
        assert case.notes.isascii(), f"{case.case_id} notes must be English"
        assert all(category.isascii() for category in case.categories)
        assert all(planned.purpose.isascii() for planned in case.queries)


def test_every_gold_plan_is_internally_consistent(dataset) -> None:
    for case in dataset.cases:
        plan = build_query_plan(case)
        assert plan.research_run_id == gold_run_id(case)
        for query in plan.queries:
            if query.status is QueryStatus.ACCEPTED:
                assert query.source_terms
                assert {r.field_path for r in query.derived_from} == {
                    t.field_path for t in query.source_terms
                }


def test_the_dataset_contains_no_real_contact_details(dataset) -> None:
    """Synthetic identity only: every address is an example domain."""
    for case in dataset.cases:
        for email in case.privacy.emails:
            assert email.endswith((".example", "example.com", "example.edu", "example.org"))


# ===========================================================================
# Running the dataset
# ===========================================================================


def test_every_case_runs_without_erroring(scored) -> None:
    metrics, _ = scored
    assert metrics.cases_errored == 0
    assert metrics.cases_evaluated >= MINIMUM_GOLD_CASES


def test_every_quality_metric_matches_the_gold_expectation(scored) -> None:
    metrics, _ = scored
    for name, counts in metrics.quality_metrics.items():
        assert counts.total > 0, f"{name} was never exercised"
        assert counts.matched == counts.total, f"{name}: {counts.matched}/{counts.total}"


def test_every_release_blocking_metric_is_clean(scored) -> None:
    metrics, _ = scored
    for name in RELEASE_BLOCKING_ACADEMIC_METRICS:
        counts = getattr(metrics, name)
        assert counts.checked > 0, f"{name} was never checked"
        assert counts.violations == 0, f"{name}: {counts.violations} violation(s)"


def test_the_gate_passes(scored) -> None:
    metrics, _ = scored
    assert evaluate_academic_gate(metrics).passed is True


def test_metrics_report_numerator_and_denominator(scored) -> None:
    metrics, _ = scored
    report = metrics.to_report()
    for entry in report["quality"].values():
        assert set(entry) == {"matched", "total", "rate"}
    for entry in report["release_blocking"].values():
        assert set(entry) == {"violations", "checked", "rate"}


def test_an_unmeasured_metric_reports_none_rather_than_zero() -> None:
    empty = AcademicRetrievalMetrics()
    assert all(c.rate is None for c in empty.quality_metrics.values())


def test_every_language_subgroup_is_independently_clean(dataset, scored) -> None:
    _, results = scored
    by_language = score_by_language(dataset, results)
    assert set(by_language) >= {"ar", "en", "mixed"}
    for language, metrics in by_language.items():
        assert metrics.safety_clean, f"{language} subgroup has a violation"


def test_the_run_is_deterministic(dataset) -> None:
    case = dataset.cases[0]
    first, second = run_academic_case(case), run_academic_case(case)
    assert [s.fingerprint.logical_key for s in first.result.logical_sources] == [
        s.fingerprint.logical_key for s in second.result.logical_sources
    ]
    assert first.result.outcome is second.result.outcome
    assert first.result.budget.model_dump() == second.result.budget.model_dump()


def test_the_cli_runs_offline_and_returns_the_gate(monkeypatch, capsys) -> None:
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("the eval must never open a network connection")

    monkeypatch.setattr(httpx.Client, "send", explode)
    assert academic_cli([]) == 0
    output = capsys.readouterr().out
    assert "gate: PASS" in output
    assert "release-blocking" in output


# ===========================================================================
# Negative controls -- the eval must be capable of failing
# ===========================================================================


def _clean_case_and_result(dataset):
    case = next(c for c in dataset.cases if c.case_id == "AR-001")
    return case, run_academic_case(case)


def _violations(case, outcome, name: str) -> int:
    metrics = AcademicRetrievalMetrics()
    score_academic_case(case, outcome, metrics)
    return getattr(metrics, name).violations


def _corrupted(outcome: AcademicCaseResult, **changes) -> AcademicCaseResult:
    return AcademicCaseResult(
        case_id=outcome.case_id,
        categories=outcome.categories,
        language=outcome.language,
        result=changes.get("result", outcome.result),
        dispatched_queries=changes.get("dispatched_queries", outcome.dispatched_queries),
        project_mutated=changes.get("project_mutated", outcome.project_mutated),
        claims_mutated=changes.get("claims_mutated", outcome.claims_mutated),
        state_payload=changes.get("state_payload", outcome.state_payload),
    )


def test_the_clean_case_is_a_valid_control(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    for name in RELEASE_BLOCKING_ACADEMIC_METRICS:
        assert _violations(case, outcome, name) == 0


def test_negative_control_pii_leakage_is_detected(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    leaked = _corrupted(
        outcome, dispatched_queries=["plant disease study by Zayn Alqahtani"]
    )
    case_with_identity = case.model_copy(
        update={"privacy": case.privacy.model_copy(update={"person_names": ["Zayn Alqahtani"]})}
    )
    assert _violations(case_with_identity, leaked, "pii_leakage_rate") >= 1


def test_negative_control_project_state_mutation_is_detected(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    assert (
        _violations(case, _corrupted(outcome, project_mutated=True), "project_state_mutation_rate")
        == 1
    )


def test_negative_control_evidence_creation_is_detected(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    poisoned = dict(outcome.state_payload)
    poisoned["smuggled"] = {
        "evidence_id": "E-001",
        "source_id": "SRC-001",
        "statement": "the paper supports the claim",
    }
    assert (
        _violations(
            case, _corrupted(outcome, state_payload=poisoned), "evidence_creation_violation_rate"
        )
        == 1
    )


def test_negative_control_claim_mutation_is_detected(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    assert (
        _violations(case, _corrupted(outcome, claims_mutated=True), "claim_mutation_violation_rate")
        == 1
    )


def _logical_source(result: AcademicRetrievalResult, observations) -> LogicalAcademicSource:
    return LogicalAcademicSource(
        logical_source_id=new_source_id(),
        research_run_id=result.research_run_id,
        fingerprint=SourceFingerprint.create(SourceIdentifierKind.DOI, "10.1234/aaaa"),
        identifiers=AcademicIdentifiers(doi="10.1234/aaaa"),
        title="Deep learning for plant disease detection",
        observations=observations,
        first_retrieved_at=RETRIEVED_AT,
    )


def test_negative_control_a_wrong_doi_merge_is_detected(dataset) -> None:
    """Two observations stating different DOIs are not one source."""
    case, outcome = _clean_case_and_result(dataset)
    result = outcome.result
    good = result.logical_sources[0]
    observations = [
        good.observations[0],
        good.observations[1].model_copy(
            update={"identifiers": AcademicIdentifiers(doi="10.1234/zzzz")}
        ),
    ]
    forged = result.model_copy(
        update={
            "logical_sources": [_logical_source(result, observations)],
            "verified_sources": [],
        }
    )
    assert (
        _violations(case, _corrupted(outcome, result=forged), "invalid_strong_identifier_merge")
        == 1
    )


def test_negative_control_provider_provenance_loss_is_detected(dataset) -> None:
    """Dropping an observation loses the answer to 'which providers found this?'."""
    case, outcome = _clean_case_and_result(dataset)
    result = outcome.result
    good = result.logical_sources[0]
    assert len(good.observations) == 3
    stripped = result.model_copy(
        update={
            "logical_sources": [
                good.model_copy(update={"observations": good.observations[:1]})
            ]
        }
    )
    assert (
        _violations(case, _corrupted(outcome, result=stripped), "provider_provenance_loss") == 1
    )


def test_negative_control_an_untraceable_source_is_detected(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    result = outcome.result
    good = result.logical_sources[0]
    orphaned = good.model_copy(
        update={
            "observations": [
                good.observations[0].model_copy(update={"query_id": uuid4()})
            ]
        }
    )
    forged = result.model_copy(update={"logical_sources": [orphaned]})
    assert (
        _violations(case, _corrupted(outcome, result=forged), "untraceable_verified_source") == 1
    )


def test_a_forged_result_is_still_rejected_by_the_gate(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    metrics = AcademicRetrievalMetrics()
    score_academic_case(case, _corrupted(outcome, project_mutated=True), metrics)
    gate = evaluate_academic_gate(metrics)
    assert gate.passed is False
    assert gate.violations["project_state_mutation_rate"] == 1


def test_budget_report_still_reports_its_limits_when_nothing_truncated(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    budget = outcome.result.budget
    assert isinstance(budget, AcademicBudgetReport)
    assert budget.truncated is False
    assert budget.max_queries_per_run >= 1
    assert budget.candidates_accepted == len(outcome.result.candidates)


def test_every_observation_names_its_provider(dataset) -> None:
    case, outcome = _clean_case_and_result(dataset)
    source = outcome.result.logical_sources[0]
    assert [o.provider for o in source.observations] == list(
        (AcademicProvider.CONSENSUS, AcademicProvider.OPENALEX, AcademicProvider.SEMANTIC_SCHOLAR)
    )
    assert all(isinstance(o, ProviderObservation) for o in source.observations)
