"""Phase 2G eval metrics: quality rates, 48 release-blocking gates, per language.

A subgroup with no denominator reports ``None`` -- "not measured" -- never zero
(section 36). A gate reports its violations and its opportunities separately,
so a zero is a measured zero over a stated denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.evals.patent_prior_art.dataset import (
    MIN_ARABIC_CASES,
    MIN_MIXED_CASES,
    MIN_TOTAL_CASES,
    REQUIRED_CATEGORIES,
    PatentGoldDataset,
)
from src.evals.patent_prior_art.runner import CaseResult

RELEASE_BLOCKING_PATENT_GATES: tuple[str, ...] = (
    "project_state_mutation",
    "claim_mutation",
    "claim_status_mutation",
    "claim_confidence_mutation",
    "evidence_reference_mutation",
    "project_score_mutation",
    "trust_gate_mutation",
    "evaluation_status_mutation",
    "phase2c_evidence_mutation",
    "phase2d_alignment_mutation",
    "phase2e_sufficiency_mutation",
    "phase2f_scorecard_mutation",
    "pii_query_leakage",
    "invalid_query_accepted",
    "unverified_observation_as_publication",
    "invalid_identity_accepted",
    "title_only_publication_dedupe",
    "kind_code_collapsed",
    "duplicate_observation_inflation",
    "duplicate_query_hit_inflation",
    "family_member_counted_independent",
    "title_only_family_grouping",
    "fabricated_family_accepted",
    "priority_date_as_public_date",
    "filing_date_as_public_date",
    "grant_date_as_first_public_date",
    "after_cutoff_labeled_before",
    "unknown_date_labeled_before",
    "no_cutoff_run_labeled",
    "claims_unavailable_as_available",
    "title_or_abstract_as_claims",
    "provider_rank_as_novelty_score",
    "novelty_score_produced",
    "legal_prior_art_conclusion",
    "patentability_conclusion",
    "patentscope_automation_enabled",
    "legacy_patentsview_assumed",
    "documented_only_reported_live",
    "credentials_persisted",
    "provider_limit_silently_truncated",
    "partial_search_reported_complete",
    "failed_query_reported_successful",
    "cross_run_query_accepted",
    "cross_run_publication_accepted",
    "cross_run_family_accepted",
    "incompatible_duplicate_candidate_accepted",
    "automatic_claim_status_update",
    "automatic_score_update",
)
"""Specification section 37, in its order. All must be zero."""

QUALITY_METRICS: tuple[str, ...] = (
    "query_provenance_accuracy",
    "query_plan_contract_accuracy",
    "multilingual_query_plan_accuracy",
    "pii_minimization_accuracy",
    "publication_identity_accuracy",
    "provider_observation_dedupe_accuracy",
    "patent_family_grouping_accuracy",
    "family_member_preservation_accuracy",
    "chronology_date_field_accuracy",
    "cutoff_qualification_accuracy",
    "text_snapshot_provenance_accuracy",
    "claims_availability_accuracy",
    "bounded_search_status_accuracy",
    "provider_error_handling_accuracy",
    "provider_capability_handling_accuracy",
    "checkpoint_idempotency_accuracy",
    "candidate_traceability",
    "legal_boundary_terminology_accuracy",
)
"""Specification section 36. Every one is required to be exactly 1.0."""


@dataclass
class GateResult:
    name: str
    violations: int
    opportunities: int

    @property
    def rate(self) -> float | None:
        return None if self.opportunities == 0 else self.violations / self.opportunities


@dataclass
class PatentEvalMetrics:
    total_cases: int
    language_counts: dict[str, int]
    category_counts: dict[str, int]
    errored_cases: list[str]
    failed_cases: list[str]
    quality: dict[str, float | None]
    quality_denominators: dict[str, int]
    gates: list[GateResult]
    per_language: dict[str, float | None]
    negative_controls: dict[str, tuple[int, int]]
    coverage_problems: list[str] = field(default_factory=list)

    @property
    def gates_clear(self) -> bool:
        return all(g.violations == 0 for g in self.gates) and all(
            g.opportunities > 0 for g in self.gates
        )

    @property
    def quality_perfect(self) -> bool:
        return all(value == 1.0 for value in self.quality.values())

    @property
    def negative_controls_fire(self) -> bool:
        return all(passed == total for passed, total in self.negative_controls.values())

    @property
    def passed(self) -> bool:
        return (
            not self.errored_cases
            and not self.coverage_problems
            and self.gates_clear
            and self.quality_perfect
            and self.negative_controls_fire
        )


def compute_metrics(
    dataset: PatentGoldDataset, results: list[CaseResult]
) -> PatentEvalMetrics:
    language_counts = {
        language: len(dataset.by_language(language)) for language in ("en", "ar", "mixed")
    }
    category_counts = dataset.category_counts
    problems: list[str] = []
    if len(dataset.cases) < MIN_TOTAL_CASES:
        problems.append(f"only {len(dataset.cases)} cases; {MIN_TOTAL_CASES} required")
    if language_counts["ar"] < MIN_ARABIC_CASES:
        problems.append(f"only {language_counts['ar']} Arabic cases; {MIN_ARABIC_CASES} required")
    if language_counts["mixed"] < MIN_MIXED_CASES:
        problems.append(
            f"only {language_counts['mixed']} mixed cases; {MIN_MIXED_CASES} required"
        )
    missing = [c for c in REQUIRED_CATEGORIES if category_counts.get(c, 0) == 0]
    if missing:
        problems.append(f"categories without a case: {missing}")

    quality: dict[str, float | None] = {}
    denominators: dict[str, int] = {}
    for name in QUALITY_METRICS:
        outcomes = [r.checks[name] for r in results if name in r.checks and r.error is None]
        denominators[name] = len(outcomes)
        quality[name] = (sum(outcomes) / len(outcomes)) if outcomes else None
    for name, value in quality.items():
        if value is None:
            problems.append(f"quality metric {name} has no denominator")

    gates = []
    for name in RELEASE_BLOCKING_PATENT_GATES:
        violations = sum(r.gates.get(name, (0, 0))[0] for r in results)
        opportunities = sum(r.gates.get(name, (0, 0))[1] for r in results)
        gates.append(GateResult(name, violations, opportunities))

    per_language: dict[str, float | None] = {}
    for language in ("en", "ar", "mixed"):
        subset = [r for r in results if r.case.language == language]
        per_language[language] = (
            sum(1 for r in subset if r.passed) / len(subset) if subset else None
        )

    negative: dict[str, tuple[int, int]] = {}
    for result in results:
        for key, ok in result.checks.items():
            if key.startswith("negative_control:"):
                kind = key.split(":", 1)[1]
                passed, total = negative.get(kind, (0, 0))
                negative[kind] = (passed + int(ok), total + 1)

    return PatentEvalMetrics(
        total_cases=len(dataset.cases),
        language_counts=language_counts,
        category_counts=category_counts,
        errored_cases=[f"{r.case.case_id}: {r.error}" for r in results if r.error],
        failed_cases=[r.case.case_id for r in results if not r.passed and not r.error],
        quality=quality,
        quality_denominators=denominators,
        gates=gates,
        per_language=per_language,
        negative_controls=negative,
        coverage_problems=problems,
    )


__all__ = [
    "QUALITY_METRICS",
    "RELEASE_BLOCKING_PATENT_GATES",
    "GateResult",
    "PatentEvalMetrics",
    "compute_metrics",
]
