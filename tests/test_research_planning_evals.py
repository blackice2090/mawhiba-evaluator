"""Research planning Gold evals, release-blocking safety gate and negative controls."""

from __future__ import annotations

import pytest

from src.evals.metrics import SafetyCounts
from src.evals.research import cli as research_cli
from src.evals.research.dataset import build_project, load_research_dataset
from src.evals.research.metrics import (
    RELEASE_BLOCKING_RESEARCH_METRICS,
    ResearchPlanningMetrics,
    violation_rate,
)
from src.evals.research.runner import evaluate_research_gate, run_research_dataset
from src.research import inputs as research_inputs
from src.research import planner as research_planner
from src.research import query_verification

REQUIRED_CATEGORIES = {
    "ai", "machine_learning", "computer_vision", "iot", "robotics", "embedded_systems", "software",
    "mixed_domain", "arabic", "mixed_language", "minimal_description", "novelty_claim",
    "performance_claim", "missing_technology", "ambiguous_technology", "prompt_injection",
    "pii_contamination", "confirmation_bias", "alternative_methods", "failure_modes",
    "query_duplication", "invalid_field_reference",
}


@pytest.fixture(scope="module")
def dataset():
    return load_research_dataset()


@pytest.fixture(scope="module")
def evaluation(dataset):
    return run_research_dataset(dataset)


def test_dataset_has_at_least_25_cases(dataset) -> None:
    assert len(dataset.cases) >= 25


def test_dataset_covers_every_required_category(dataset) -> None:
    assert REQUIRED_CATEGORIES <= set(dataset.category_counts)


def test_dataset_covers_english_arabic_and_mixed(dataset) -> None:
    assert {"en", "ar", "mixed"} <= set(dataset.language_counts)


def test_dataset_structure_is_english(dataset) -> None:
    for case in dataset.cases:
        assert case.case_id.isascii() and case.notes.isascii()
        assert all(category.isascii() for category in case.categories)
        assert all(path.isascii() for path in case.project.known_fields)
        assert all(path.isascii() for path in case.project.list_fields)


def test_synthetic_emails_use_reserved_example_domains(dataset) -> None:
    for case in dataset.cases:
        for email in case.privacy.emails:
            assert email.endswith("@example.com")


def test_gold_projects_are_deterministic(dataset) -> None:
    case = dataset.cases[0]
    assert build_project(case) == build_project(case)


def test_release_blocking_metrics_are_measured_and_zero(evaluation) -> None:
    metrics, _ = evaluation
    for name in RELEASE_BLOCKING_RESEARCH_METRICS:
        counts = getattr(metrics, name)
        assert counts.checked > 0, f"{name} was never measured"
        assert counts.violations == 0, name
    assert metrics.safety_clean


def test_quality_metrics_are_perfect_in_fake_mode(evaluation) -> None:
    metrics, _ = evaluation
    assert metrics.cases_errored == 0
    for name, counts in metrics.quality_metrics.items():
        assert counts.total > 0, f"{name} was never measured"
        assert counts.rate == 1.0, name
    assert metrics.duplicate_query_rate.violations == 0


def test_gate_passes(evaluation) -> None:
    metrics, _ = evaluation
    assert evaluate_research_gate(metrics).passed


def test_unmeasured_metrics_are_none_never_zero() -> None:
    empty = ResearchPlanningMetrics()
    assert empty.query_source_traceability.rate is None
    assert violation_rate(SafetyCounts()) is None
    report = empty.to_report()
    assert report["quality"]["query_source_traceability"]["rate"] is None
    assert report["release_blocking"]["pii_leakage_rate"]["rate"] is None


# --- negative controls: the eval must be able to fail ----------------------------------------


def test_eval_detects_pii_leakage(dataset, monkeypatch) -> None:
    monkeypatch.setattr(query_verification, "contains_pii", lambda *args, **kwargs: False)
    metrics, _ = run_research_dataset(dataset)
    assert metrics.pii_leakage_rate.violations > 0
    assert not evaluate_research_gate(metrics).passed


def test_eval_detects_invalid_field_references(dataset, monkeypatch) -> None:
    real = research_inputs.resolve_research_field

    def permissive(project, path):
        return real(project, path) or [project.model_dump_json()]

    monkeypatch.setattr(query_verification, "resolve_research_field", permissive)
    metrics, _ = run_research_dataset(dataset)
    assert metrics.invalid_field_reference_rate.violations > 0
    assert not evaluate_research_gate(metrics).passed


def test_eval_detects_project_state_mutation(dataset, monkeypatch) -> None:
    real = research_planner.build_research_input

    def mutating(project, privacy=None):
        project.technical.technologies.append("object detection")
        return real(project) if privacy is None else real(project, privacy)

    monkeypatch.setattr(research_planner, "build_research_input", mutating)
    metrics, _ = run_research_dataset(dataset)
    assert metrics.project_state_mutation_rate.violations > 0
    assert not evaluate_research_gate(metrics).passed


def test_eval_detects_untraceable_accepted_queries(dataset, monkeypatch) -> None:
    monkeypatch.setattr(query_verification, "text_tokens", lambda text: [])
    metrics, _ = run_research_dataset(dataset)
    assert metrics.untraceable_accepted_queries.violations > 0
    assert not evaluate_research_gate(metrics).passed


# --- CLI ----------------------------------------------------------------------------------------


def test_cli_passes_and_prints_provenance(capsys) -> None:
    assert research_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "gate: PASS" in out
    assert "RESEARCH_QUERY_PLANNER_PROMPT_V1" in out
    assert "RESEARCH-CONTRACT-V1" in out


def test_cli_report_is_written_to_the_report_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(research_cli, "REPORT_ROOT", tmp_path)
    assert research_cli.main(["--report"]) == 0
    reports = list(tmp_path.glob("research_planning_*.json"))
    assert len(reports) == 1
