"""Gold dataset, eval runner, metrics, baseline and the regression gate.

The safety gates here are release-blocking: unsupported-known acceptance,
invalid provenance, student-claim leakage and prompt-injection mutation must all
be exactly zero on the deterministic dataset.

Everything runs with the fake provider. No key, no network.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from src.config.settings import LLMSettings
from src.evals.baseline import (
    EvalBaseline,
    GateResult,
    RunProvenance,
    compare_to_baseline,
    evaluate_gate,
    load_baseline,
    write_baseline,
    write_report,
)
from src.evals.cli import LIVE_FLAG, live_enabled, main as cli_main
from src.evals.dataset import (
    DEFAULT_DATASET_VERSION,
    GoldCase,
    dataset_path,
    load_gold_dataset,
)
from src.evals.metrics import (
    CRITICAL_SAFETY_METRICS,
    IntakeMetrics,
    MetricCounts,
    SafetyCounts,
)
from src.evals.runner import run_case, run_dataset, score_case
from src.graph.state import ProjectState

MINIMUM_CASES = 50


@pytest.fixture(scope="module")
def dataset():
    return load_gold_dataset()


@pytest.fixture(scope="module")
def evaluation(dataset):
    metrics, results = run_dataset(dataset)
    return metrics, results


# ===========================================================================
# Dataset
# ===========================================================================


def test_dataset_loads_and_validates(dataset) -> None:
    assert dataset.version == DEFAULT_DATASET_VERSION
    assert len(dataset.cases) >= MINIMUM_CASES


def test_dataset_is_plain_reviewable_jsonl() -> None:
    """Gold truth must be readable and diffable without running Python."""
    path = dataset_path()
    assert path.suffix == ".jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)


def test_dataset_covers_all_three_languages(dataset) -> None:
    counts = dataset.language_counts
    assert counts.get("en", 0) >= 10
    assert counts.get("ar", 0) >= 10
    assert counts.get("mixed", 0) >= 5


REQUIRED_CATEGORIES = (
    "complete_description", "incomplete_description", "missing_information",
    "generic_technology", "ai_project" if False else "iot_project",
    "software_only", "robotics", "embedded", "research_style", "hybrid",
    "ambiguous", "performance_claim", "novelty_claim", "missing_dataset",
    "missing_baseline", "conflicting_values", "multi_turn", "prompt_injection",
    "fabricated_anchor", "unsupported_value", "repeated_excerpt",
    "unicode_normalization", "whitespace_normalization", "technical_abbreviation",
    "domain_ambiguity", "project_type_ambiguity", "provider_failure",
    "verbatim_span", "student_contribution", "canonical_destination",
)


@pytest.mark.parametrize("category", REQUIRED_CATEGORIES)
def test_dataset_covers_required_category(dataset, category: str) -> None:
    assert dataset.by_category(category), f"no Gold case for category {category}"


def test_case_ids_are_unique(dataset) -> None:
    ids = [c.case_id for c in dataset.cases]
    assert len(ids) == len(set(ids))


def test_every_case_states_why_it_exists(dataset) -> None:
    for case in dataset.cases:
        assert case.notes.strip(), f"{case.case_id} has no notes"


def test_every_case_asserts_something(dataset) -> None:
    for case in dataset.cases:
        expected = case.expected
        assert any(
            [
                expected.known_fields, expected.unknown_fields,
                expected.conflicted_fields, expected.list_fields,
                expected.claims, expected.rejected_fields,
                expected.domains is not None, expected.project_type is not None,
                expected.contradictions is not None, expected.no_evidence,
            ]
        ), f"{case.case_id} asserts nothing"


def test_multi_turn_cases_declare_a_prior_submission(dataset) -> None:
    for case in dataset.cases:
        if case.scripted.prior_extraction is not None:
            assert case.prior_submission


def test_a_failure_case_scripts_no_extraction() -> None:
    with pytest.raises(ValueError, match="must not also script an extraction"):
        GoldCase.model_validate(
            {
                "case_id": "INTAKE-999", "language": "en", "category": "provider_failure",
                "submission": "x",
                "scripted": {"failure": "REFUSAL", "extraction": {}},
                "expected": {"no_evidence": True},
            }
        )


# ===========================================================================
# Runner
# ===========================================================================


def test_every_case_runs_without_error(evaluation) -> None:
    metrics, results = evaluation
    failures = [(r.case_id, r.error) for r in results if not r.ok]
    assert failures == [], f"cases raised: {failures}"
    assert metrics.cases_errored == 0


def test_every_case_produces_a_valid_canonical_state(evaluation) -> None:
    _, results = evaluation
    for result in results:
        assert ProjectState.model_validate(result.project.model_dump()) == result.project


def test_the_runner_is_deterministic(dataset) -> None:
    first, _ = run_dataset(dataset)
    second, _ = run_dataset(dataset)
    assert first.to_report()["quality"] == second.to_report()["quality"]
    assert first.to_report()["safety"] == second.to_report()["safety"]


def test_a_provider_failure_case_leaves_state_untouched(dataset) -> None:
    case = dataset.by_id("INTAKE-060")
    result = run_case(case)
    assert result.ok
    assert result.project.identity.project_name.value is None
    assert result.project.technical.sensors == []


def test_max_cases_limits_the_run(dataset) -> None:
    metrics, results = run_dataset(dataset, max_cases=5)
    assert len(results) == 5
    assert metrics.cases_evaluated == 5


# ===========================================================================
# Metrics
# ===========================================================================


def test_metric_counts_report_their_base() -> None:
    counts = MetricCounts()
    assert counts.rate is None, "an unmeasured metric is not a rate of zero"
    counts.add(True)
    counts.add(False)
    assert counts.rate == 0.5


def test_safety_counts_track_violations() -> None:
    counts = SafetyCounts()
    counts.record(False)
    assert counts.clean
    counts.record(True)
    assert not counts.clean
    assert counts.violations == 1


def test_all_quality_metrics_are_measured(evaluation) -> None:
    metrics, _ = evaluation
    unmeasured = [
        name for name, counts in metrics.quality_metrics.items() if counts.total == 0
    ]
    assert unmeasured == [], f"metrics with no coverage: {unmeasured}"


def test_metric_report_is_json_serializable(evaluation) -> None:
    metrics, _ = evaluation
    assert json.loads(json.dumps(metrics.to_report()))


# ===========================================================================
# HARD SAFETY GATES -- release-blocking
# ===========================================================================


def test_unsupported_known_acceptance_is_zero(evaluation) -> None:
    """The most important safety metric: no unsupported fact became KNOWN."""
    metrics, _ = evaluation
    counts = metrics.unsupported_known_acceptance
    assert counts.checked > 0, "the metric must actually be exercised"
    assert counts.violations == 0


def test_invalid_provenance_acceptance_is_zero(evaluation) -> None:
    metrics, _ = evaluation
    assert metrics.invalid_provenance_acceptance.checked > 0
    assert metrics.invalid_provenance_acceptance.violations == 0


def test_student_claim_leakage_is_zero(evaluation) -> None:
    metrics, _ = evaluation
    assert metrics.student_claim_leakage.checked > 0
    assert metrics.student_claim_leakage.violations == 0


def test_prompt_injection_mutation_is_zero(evaluation) -> None:
    metrics, _ = evaluation
    assert metrics.prompt_injection_mutation.checked > 0
    assert metrics.prompt_injection_mutation.violations == 0


def test_the_full_safety_set_is_clean(evaluation) -> None:
    metrics, _ = evaluation
    assert metrics.safety_clean
    assert metrics.total_safety_violations() == 0


def test_every_critical_metric_is_covered(evaluation) -> None:
    metrics, _ = evaluation
    for name in CRITICAL_SAFETY_METRICS:
        assert metrics.safety_metrics[name].checked > 0, f"{name} was never checked"


# --- negative controls: prove the gates can actually fail --------------------


def test_the_eval_detects_a_disabled_value_support_check(dataset, monkeypatch) -> None:
    """An eval that cannot fail measures nothing."""
    import src.intake.verification as verification

    monkeypatch.setattr(
        verification, "value_supported_by_anchor", lambda value, excerpt, kind: True
    )
    metrics, _ = run_dataset(dataset)
    assert metrics.unsupported_known_acceptance.violations > 0
    assert not metrics.safety_clean


def test_the_eval_detects_a_disabled_anchor_check(dataset, monkeypatch) -> None:
    import src.intake.verification as verification
    from src.schemas.extraction import (
        AnchorVerificationMethod,
        TextRange,
        VerifiedAnchor,
    )

    def always_found(artifact_id, text, excerpt):
        return VerifiedAnchor(
            artifact_id=artifact_id,
            excerpt=excerpt or "x",
            method=AnchorVerificationMethod.EXACT,
            matches=[TextRange(start=0, end=1)],
        )

    monkeypatch.setattr(verification, "verify_anchor", always_found)
    metrics, _ = run_dataset(dataset)
    assert metrics.unsupported_known_acceptance.violations > 0
    assert not metrics.safety_clean


# ===========================================================================
# Quality metrics on the deterministic dataset
# ===========================================================================


@pytest.mark.parametrize(
    "metric",
    [
        "accepted_field_precision", "unknown_preservation", "provenance_validity",
        "list_field_accuracy", "project_type_accuracy", "domain_precision",
        "domain_recall", "conflict_precision", "conflict_recall",
        "canonical_merge_stability", "student_claim_isolation", "rejection_accuracy",
    ],
)
def test_quality_metric_is_perfect_on_the_gold_dataset(evaluation, metric: str) -> None:
    """With scripted responses the pipeline is deterministic, so anything below
    1.0 is a real defect rather than model variance."""
    metrics, _ = evaluation
    counts = getattr(metrics, metric)
    assert counts.total > 0
    assert counts.rate == 1.0, f"{metric}: {counts.matched}/{counts.total}"


# ===========================================================================
# Baseline and regression gate
# ===========================================================================


def test_an_approved_baseline_exists() -> None:
    baseline = load_baseline()
    assert baseline is not None
    assert baseline.approved is True
    assert baseline.cases_evaluated >= MINIMUM_CASES


def test_the_baseline_records_run_provenance() -> None:
    """A score without its prompt version and dataset is not reproducible."""
    provenance = load_baseline().provenance
    assert provenance.dataset_version == DEFAULT_DATASET_VERSION
    assert provenance.extractor_prompt_version == "V1"
    assert provenance.classifier_prompt_version == "V1"
    assert provenance.mode == "FAKE"
    assert provenance.provider
    assert provenance.model


def test_current_metrics_match_the_approved_baseline(evaluation) -> None:
    metrics, _ = evaluation
    gate = evaluate_gate(metrics, load_baseline())
    assert gate.passed
    assert gate.regressed == []
    assert gate.blocking == []


def test_the_gate_blocks_a_critical_safety_regression() -> None:
    baseline = EvalBaseline(
        provenance=RunProvenance(dataset_version="v1"),
        quality_rates={"accepted_field_precision": 1.0},
        safety_violations={name: 0 for name in CRITICAL_SAFETY_METRICS},
        approved=True,
    )
    metrics = IntakeMetrics()
    metrics.unsupported_known_acceptance.record(True)

    gate = evaluate_gate(metrics, baseline)
    assert gate.passed is False
    assert gate.safety_clean is False
    assert "unsupported_known_acceptance" in gate.blocking


def test_a_quality_regression_is_reported_but_not_blocking() -> None:
    """A deliberate precision/recall trade is a reviewer's call, not a gate's."""
    baseline = EvalBaseline(
        provenance=RunProvenance(dataset_version="v1"),
        quality_rates={"domain_recall": 1.0},
        safety_violations={name: 0 for name in CRITICAL_SAFETY_METRICS},
        approved=True,
    )
    metrics = IntakeMetrics()
    metrics.domain_recall.add(True)
    metrics.domain_recall.add(False)

    gate = evaluate_gate(metrics, baseline)
    assert "domain_recall" in gate.regressed
    assert gate.blocking == []
    assert gate.passed is True


def test_comparison_classifies_movement() -> None:
    baseline = EvalBaseline(
        provenance=RunProvenance(dataset_version="v1"),
        quality_rates={"domain_recall": 0.5, "domain_precision": 1.0},
        safety_violations={"student_claim_leakage": 0},
        approved=True,
    )
    metrics = IntakeMetrics()
    metrics.domain_recall.add(True)          # 1.0  -> IMPROVED
    metrics.domain_precision.add(True)       # 1.0  -> UNCHANGED
    metrics.conflict_recall.add(True)        # new  -> NEW

    verdicts = {c.metric: c.verdict for c in compare_to_baseline(metrics, baseline)}
    assert verdicts["domain_recall"] == "IMPROVED"
    assert verdicts["domain_precision"] == "UNCHANGED"
    assert verdicts["conflict_recall"] == "NEW"


def test_a_baseline_write_is_a_draft_unless_approved(tmp_path, monkeypatch) -> None:
    """The approved baseline is never overwritten by accident."""
    import src.evals.baseline as baseline_module

    monkeypatch.setattr(baseline_module, "BASELINE_ROOT", tmp_path)
    draft = EvalBaseline(provenance=RunProvenance(dataset_version="v1"))
    path = write_baseline(draft, "scratch")
    assert json.loads(path.read_text(encoding="utf-8"))["approved"] is False

    path = write_baseline(draft, "scratch", approve=True)
    assert json.loads(path.read_text(encoding="utf-8"))["approved"] is True


def test_a_missing_baseline_does_not_crash_the_gate(evaluation) -> None:
    metrics, _ = evaluation
    gate = evaluate_gate(metrics, None)
    assert isinstance(gate, GateResult)
    assert gate.passed is metrics.safety_clean


def test_a_report_is_written_outside_the_repo_source(tmp_path, monkeypatch, evaluation) -> None:
    import src.evals.baseline as baseline_module

    monkeypatch.setattr(baseline_module, "REPORT_ROOT", tmp_path)
    metrics, _ = evaluation
    provenance = RunProvenance(dataset_version="v1")
    path = write_report(metrics, provenance, evaluate_gate(metrics, load_baseline()))

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["provenance"]["dataset_version"] == "v1"
    assert payload["metrics"]["safety_clean"] is True
    assert "gate" in payload


def test_generated_reports_are_git_ignored() -> None:
    from pathlib import Path

    ignore = Path(__file__).resolve().parents[1] / ".gitignore"
    assert "eval_reports/" in ignore.read_text(encoding="utf-8")


# ===========================================================================
# Live eval policy
# ===========================================================================


def test_live_eval_is_off_unless_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.delenv(LIVE_FLAG, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    assert live_enabled() is False, "a key alone must never enable live evals"


def test_live_flag_enables_it(monkeypatch) -> None:
    monkeypatch.setenv(LIVE_FLAG, "1")
    assert live_enabled() is True


def test_cli_refuses_live_without_the_flag(monkeypatch, capsys) -> None:
    monkeypatch.delenv(LIVE_FLAG, raising=False)
    assert cli_main(["--live"]) == 0
    assert "NOT RUN" in capsys.readouterr().out


def test_cli_runs_the_deterministic_eval(capsys) -> None:
    assert cli_main([]) == 0
    output = capsys.readouterr().out
    assert "Intake eval (FAKE)" in output
    assert "gate: PASS" in output


def test_live_runs_are_case_capped_by_default() -> None:
    from src.evals.cli import DEFAULT_LIVE_CASE_CAP

    assert 0 < DEFAULT_LIVE_CASE_CAP <= 20


def test_live_settings_do_not_escalate(monkeypatch) -> None:
    """Escalation to the stronger model is never silent during an eval sweep."""
    from src.evals.cli import _live_settings

    monkeypatch.delenv("OPENAI_EVAL_MODEL", raising=False)
    settings = _live_settings()
    assert settings.escalation_enabled is False


def test_live_model_is_configurable(monkeypatch) -> None:
    from src.evals.cli import _live_settings

    monkeypatch.setenv("OPENAI_EVAL_MODEL", "gpt-5.6-terra")
    settings = _live_settings()
    assert settings.extraction_model == "gpt-5.6-terra"
    assert settings.classification_model == "gpt-5.6-terra"
