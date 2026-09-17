"""The evidence extraction Gold dataset, its metrics, and its negative controls.

A safety suite that cannot fail proves nothing, so the last section deliberately
corrupts a correct result and asserts that each release-blocking gate notices.
"""

from __future__ import annotations

import pytest

from src.evals.evidence.cli import main as evidence_cli
from src.evals.evidence.dataset import (
    DEFAULT_EVIDENCE_DATASET_VERSION,
    build_academic_result,
    evidence_dataset_path,
    load_evidence_dataset,
)
from src.evals.evidence.metrics import (
    RELEASE_BLOCKING_EVIDENCE_METRICS,
    REQUIRED_PERFECT_METRICS,
    EvidenceExtractionMetrics,
)
from src.evals.evidence.runner import (
    PII_PROBE,
    EvidenceCaseResult,
    evaluate_evidence_gate,
    run_evidence_case,
    run_evidence_dataset,
    score_by_language,
    score_evidence_case,
)
from src.schemas.evidence_extraction import (
    ContentKind,
    ExtractedEvidence,
    NumericObservation,
)

MINIMUM_GOLD_CASES = 60
MINIMUM_TOTAL_CASES_V1_1 = 80
"""Phase 2C.1 §3: the multilingual-hardening floor, stricter than the
original MINIMUM_GOLD_CASES."""
MINIMUM_ARABIC_CASES = 8
MINIMUM_MIXED_CASES = 4

REQUIRED_CATEGORIES = {
    "exact_abstract_excerpt",
    "two_excerpts_one_abstract",
    "no_relevant_evidence",
    "metadata_only_source",
    "missing_abstract",
    "same_quote_twice",
    "ambiguous_repeated_excerpt",
    "wrong_model_offset",
    "hallucinated_quote",
    "whitespace_variation",
    "line_break_variation",
    "negation",
    "double_negation",
    "percentage",
    "decimal",
    "integer",
    "sample_size",
    "confidence_interval",
    "p_value",
    "wrong_numeric_value",
    "wrong_unit",
    "result_vs_limitation",
    "method_vs_result",
    "benchmark_comparison",
    "failure_mode",
    "dataset_description",
    "arabic_source",
    "english_source",
    "mixed_language",
    "prompt_injection_in_abstract",
    "score_manipulation",
    "claim_verification_instruction",
    "retracted_source",
    "preprint",
    "peer_review_unknown",
    "same_abstract_two_providers",
    "different_abstracts_same_source",
    "same_sentence_two_sources",
    "very_short_excerpt",
    "very_long_excerpt",
    "malformed_candidate_empty_excerpt",
    "llm_timeout",
    "llm_schema_failure",
    "partial_source_failure",
    "all_sources_no_content",
    "all_extractions_fail",
    "project_state_immutability",
    "claim_immutability",
    "score_immutability",
    "trust_gate_immutability",
    "no_automatic_claim_linkage",
    "citation_count",
    "provider_rank",
    "consensus_takeaway",
    "source_title",
    "rejection_ledger_traceability",
    "abstract_scope_preserved",
}


@pytest.fixture(scope="module")
def dataset():
    return load_evidence_dataset()


@pytest.fixture(scope="module")
def scored(dataset):
    return run_evidence_dataset(dataset)


# ===========================================================================
# Dataset integrity
# ===========================================================================


def test_the_dataset_file_exists_and_is_reviewable() -> None:
    path = evidence_dataset_path(DEFAULT_EVIDENCE_DATASET_VERSION)
    assert path.exists()
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= MINIMUM_GOLD_CASES, "one case per line, reviewable in a diff"


def test_the_dataset_meets_the_required_size(dataset) -> None:
    assert len(dataset.cases) >= MINIMUM_GOLD_CASES


def test_the_dataset_covers_every_required_adversarial_category(dataset) -> None:
    covered = set(dataset.category_counts)
    assert REQUIRED_CATEGORIES <= covered, sorted(REQUIRED_CATEGORIES - covered)


def test_the_dataset_is_meaningfully_multilingual(dataset) -> None:
    counts = dataset.language_counts
    assert counts.get("en", 0) >= 1
    assert counts.get("ar", 0) >= 1
    assert counts.get("mixed", 0) >= 1


def test_the_dataset_meets_phase2c1_multilingual_minimums(dataset) -> None:
    """Phase 2C.1 §3: the pre-hardening distribution (en=66, ar=3, mixed=1)
    was too thin for a meaningful multilingual trust evaluation."""
    counts = dataset.language_counts
    assert len(dataset.cases) >= MINIMUM_TOTAL_CASES_V1_1
    assert counts.get("ar", 0) >= MINIMUM_ARABIC_CASES
    assert counts.get("mixed", 0) >= MINIMUM_MIXED_CASES


def test_arabic_and_mixed_cases_cover_required_trust_behaviors(dataset) -> None:
    """Phase 2C.1 §3: Arabic/mixed content must exercise the same trust
    surface as English, not just prove the script can echo Arabic text."""
    non_english = [c for c in dataset.cases if c.language in ("ar", "mixed")]
    categories = {cat for c in non_english for cat in c.categories}
    required_substrings = (
        "negation",
        "numeric",
        "hallucination",
        "limitation_result_distinction",
        "prompt_injection",
        "technical_terminology",
        "whitespace_span",
    )
    for substring in required_substrings:
        assert any(substring in cat for cat in categories), (
            f"no ar/mixed Gold case covers {substring!r}: {sorted(categories)}"
        )
    # A valid, non-adversarial exact-evidence case in both ar and mixed.
    assert any(
        c.language == "ar" and c.expected.accepted_excerpts for c in dataset.cases
    )
    assert any(
        c.language == "mixed" and c.expected.accepted_excerpts for c in dataset.cases
    )


def test_case_structure_is_english_even_where_content_is_not(dataset) -> None:
    for case in dataset.cases:
        assert case.case_id.isascii()
        assert case.notes.isascii(), f"{case.case_id} notes must be English"
        assert all(category.isascii() for category in case.categories)
        assert case.purpose.isascii()


def test_every_gold_case_materializes_into_valid_phase2b_state(dataset) -> None:
    for case in dataset.cases:
        result = build_academic_result(case)
        assert len(result.logical_sources) == len(
            [s for s in case.sources if s.observations]
        )
        assert sorted(s.logical_source_id for s in result.logical_sources) == sorted(
            r.source_id for r in result.verified_sources
        )


def test_the_dataset_contains_no_real_identity(dataset) -> None:
    """Synthetic content only: no real paper, author or student appears."""
    for case in dataset.cases:
        for source in case.sources:
            for observation in source.observations:
                text = observation.abstract or ""
                assert "@" not in text or "example" in text


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


def test_required_metrics_are_exactly_one(scored) -> None:
    metrics, _ = scored
    for name in REQUIRED_PERFECT_METRICS:
        counts = getattr(metrics, name)
        assert counts.total > 0, f"{name} has an empty denominator"
        assert counts.rate == 1.0, f"{name}: {counts.rate}"
    assert metrics.thresholds_met is True


def test_every_release_blocking_metric_is_clean(scored) -> None:
    metrics, _ = scored
    for name in RELEASE_BLOCKING_EVIDENCE_METRICS:
        counts = getattr(metrics, name)
        assert counts.checked > 0, f"{name} was never checked"
        assert counts.violations == 0, f"{name}: {counts.violations} violation(s)"


def test_the_gate_passes(scored) -> None:
    metrics, _ = scored
    assert evaluate_evidence_gate(metrics).passed is True


def test_an_unmeasured_metric_reports_none_rather_than_zero() -> None:
    empty = EvidenceExtractionMetrics()
    assert all(c.rate is None for c in empty.quality_metrics.values())
    assert empty.thresholds_met is False, "an unmeasured metric cannot pass a threshold"


def test_every_language_subgroup_is_independently_clean(dataset, scored) -> None:
    _, results = scored
    by_language = score_by_language(dataset, results)
    assert set(by_language) >= {"ar", "en", "mixed"}
    for language, metrics in by_language.items():
        assert metrics.safety_clean, f"{language} subgroup has a violation"


def test_the_run_is_deterministic(dataset) -> None:
    case = dataset.cases[0]
    first, second = run_evidence_case(case), run_evidence_case(case)
    assert [e.excerpt for e in first.extraction.verified_evidence] == [
        e.excerpt for e in second.extraction.verified_evidence
    ]
    assert first.extraction.status is second.extraction.status
    assert first.extraction.coverage.model_dump() == second.extraction.coverage.model_dump()


def test_the_cli_runs_offline_and_returns_the_gate(monkeypatch, capsys) -> None:
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("the eval must never open a network connection")

    monkeypatch.setattr(httpx.Client, "send", explode)
    assert evidence_cli([]) == 0
    output = capsys.readouterr().out
    assert "gate: PASS" in output
    assert "release-blocking" in output


# ===========================================================================
# Negative controls -- the eval must be capable of failing
# ===========================================================================


def _clean(dataset):
    case = next(c for c in dataset.cases if c.case_id == "EE-001")
    return case, run_evidence_case(case)


def _violations(case, outcome, name: str) -> int:
    metrics = EvidenceExtractionMetrics()
    score_evidence_case(case, outcome, metrics)
    return getattr(metrics, name).violations


def _corrupted(outcome: EvidenceCaseResult, **changes) -> EvidenceCaseResult:
    return EvidenceCaseResult(
        case_id=outcome.case_id,
        categories=outcome.categories,
        language=outcome.language,
        extraction=changes.get("extraction", outcome.extraction),
        project_mutated=changes.get("project_mutated", outcome.project_mutated),
        claims_mutated=changes.get("claims_mutated", outcome.claims_mutated),
        scores_mutated=changes.get("scores_mutated", outcome.scores_mutated),
        trust_gate_mutated=changes.get(
            "trust_gate_mutated", outcome.trust_gate_mutated
        ),
        state_payload=changes.get("state_payload", outcome.state_payload),
        extraction_payload=changes.get(
            "extraction_payload", outcome.extraction_payload
        ),
        snapshot_texts=changes.get("snapshot_texts", outcome.snapshot_texts),
    )


def _with_evidence(outcome: EvidenceCaseResult, evidence: ExtractedEvidence):
    extraction = outcome.extraction.model_copy(update={"verified_evidence": [evidence]})
    return _corrupted(outcome, extraction=extraction)


def test_the_clean_case_is_a_valid_control(dataset) -> None:
    case, outcome = _clean(dataset)
    for name in RELEASE_BLOCKING_EVIDENCE_METRICS:
        assert _violations(case, outcome, name) == 0


def test_negative_control_a_fabricated_quote_is_detected(dataset) -> None:
    """An excerpt that is not the snapshot's own text must be caught."""
    case, outcome = _clean(dataset)
    good = outcome.extraction.verified_evidence[0]
    forged = good.model_copy(
        update={
            "excerpt": "X" * len(good.excerpt),
            "verified_start": good.verified_start,
            "verified_end": good.verified_end,
        }
    )
    assert (
        _violations(case, _with_evidence(outcome, forged),
                    "hallucinated_excerpt_acceptance_rate") == 1
    )


def test_negative_control_a_wrong_number_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    good = outcome.extraction.verified_evidence[0]
    forged = good.model_copy(
        update={
            "numeric_observations": [
                NumericObservation(raw_text="99.9%", value=99.9, unit="%")
            ]
        }
    )
    assert (
        _violations(case, _with_evidence(outcome, forged),
                    "invalid_numeric_acceptance_rate") == 1
    )


def test_negative_control_a_wrong_unit_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    good = outcome.extraction.verified_evidence[0]
    forged = good.model_copy(
        update={
            "numeric_observations": [
                NumericObservation(raw_text="5 kilometres", value=5.0, unit="km")
            ]
        }
    )
    assert (
        _violations(case, _with_evidence(outcome, forged),
                    "invalid_numeric_acceptance_rate") == 1
    )


def test_negative_control_project_state_mutation_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    assert (
        _violations(case, _corrupted(outcome, project_mutated=True),
                    "project_state_mutation_rate") == 1
    )


def test_negative_control_claim_mutation_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    assert (
        _violations(case, _corrupted(outcome, claims_mutated=True),
                    "claim_mutation_rate") == 1
    )


def test_negative_control_score_mutation_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    assert (
        _violations(case, _corrupted(outcome, scores_mutated=True),
                    "score_mutation_rate") == 1
    )


def test_negative_control_trust_gate_mutation_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    assert (
        _violations(case, _corrupted(outcome, trust_gate_mutated=True),
                    "trust_gate_mutation_rate") == 1
    )


def test_negative_control_untraceable_evidence_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    good = outcome.extraction.verified_evidence[0]
    orphaned = good.model_copy(update={"content_hash": "0" * 64,
                                       "observations": [
                                           good.observations[0].model_copy(
                                               update={"content_hash": "0" * 64}
                                           )
                                       ]})
    assert (
        _violations(case, _with_evidence(outcome, orphaned),
                    "untraceable_evidence_rate") == 1
    )


def test_negative_control_metadata_only_evidence_is_detected(dataset) -> None:
    """Evidence whose content kind is not extractable must be caught."""
    case, outcome = _clean(dataset)
    good = outcome.extraction.verified_evidence[0]
    forged = good.model_copy(update={"content_kind": ContentKind.METADATA_ONLY})
    assert (
        _violations(case, _with_evidence(outcome, forged),
                    "metadata_only_evidence_rate") == 1
    )


def test_negative_control_consensus_takeaway_as_evidence_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    takeaway = "CONSENSUS SYNTHESIS: detectors work well."
    good = outcome.extraction.verified_evidence[0]
    forged = good.model_copy(update={"excerpt": takeaway,
                                     "verified_end": good.verified_start + len(takeaway)})
    doctored = case.model_copy(
        update={
            "expected": case.expected.model_copy(
                update={"forbidden_excerpt_substrings": [takeaway]}
            )
        }
    )
    assert (
        _violations(doctored, _with_evidence(outcome, forged),
                    "provider_synthesis_evidence_rate") == 1
    )


def test_negative_control_automatic_claim_support_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    poisoned = outcome.extraction.model_dump(mode="json")
    poisoned["verified_evidence"][0]["support_direction"] = "SUPPORTS"

    metrics = EvidenceExtractionMetrics()
    from src.evals.evidence.runner import _claims_a_relationship

    assert _claims_a_relationship(poisoned) is True
    assert _claims_a_relationship(outcome.extraction.model_dump(mode="json")) is False
    del metrics


def test_negative_control_pii_leakage_is_detected(dataset) -> None:
    case, outcome = _clean(dataset)
    leaked = _corrupted(
        outcome,
        extraction_payload=f"stored text mentioning {PII_PROBE[0]} directly",
    )
    assert _violations(case, leaked, "pii_leakage_rate") >= 1


def test_a_forged_result_is_rejected_by_the_gate(dataset) -> None:
    case, outcome = _clean(dataset)
    metrics = EvidenceExtractionMetrics()
    score_evidence_case(case, _corrupted(outcome, project_mutated=True), metrics)
    gate = evaluate_evidence_gate(metrics)
    assert gate.passed is False
    assert gate.violations["project_state_mutation_rate"] == 1
