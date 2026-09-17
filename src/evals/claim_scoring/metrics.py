"""Claim-evidence scoring metrics -- Phase 2F (section 31, section 32).

Quality metrics expose numerator and denominator, and a metric nothing
exercised reports ``None`` rather than ``0.0``: a subgroup with no cases has
*not measured* accuracy, which is a different claim from perfect accuracy or
zero accuracy (section 31). The same distinction the phase makes about scores
themselves.

The release-blocking metrics are violation counts with a target of exactly zero.
"A contradiction increased the support index" is not a percentage to improve --
it is the failure this phase exists to prevent, and one occurrence blocks the
release.
"""

from __future__ import annotations

from pydantic import Field

from src.evals.metrics import MetricCounts, SafetyCounts
from src.schemas.common import MawhibaModel

RELEASE_BLOCKING_SCORING_METRICS: tuple[str, ...] = (
    # --- canonical state immutability (section 22) -------------------------
    "project_state_mutation_rate",
    "claim_mutation_rate",
    "claim_status_mutation_rate",
    "claim_confidence_mutation_rate",
    "claim_evidence_reference_mutation_rate",
    "claim_counter_evidence_reference_mutation_rate",
    "canonical_score_record_mutation_rate",
    "trust_gate_mutation_rate",
    "evaluation_status_mutation_rate",
    "extracted_evidence_mutation_rate",
    "alignment_mutation_rate",
    "sufficiency_assessment_mutation_rate",
    "automatic_project_score_update_rate",
    "automatic_claim_status_update_rate",
    # --- input integrity and isolation (sections 5, 23, 24) ----------------
    "invalid_sufficiency_assessment_acceptance_rate",
    "cross_run_assessment_acceptance_rate",
    "cross_claim_scorecard_contamination_rate",
    # --- anti-gaming: duplicates must never inflate (section 14) -----------
    "duplicate_logical_source_inflated_support_rate",
    "duplicate_logical_source_inflated_contradiction_rate",
    "duplicate_excerpt_inflated_support_rate",
    "duplicate_excerpt_inflated_contradiction_rate",
    "provider_observation_inflated_support_rate",
    "provider_observation_inflated_contradiction_rate",
    # --- anti-gaming: non-support must never count as support --------------
    "context_only_counted_as_direct_support_rate",
    "insufficient_counted_as_direct_support_rate",
    "not_relevant_counted_as_direct_support_rate",
    "retracted_source_counted_as_eligible_support_rate",
    "unknown_quality_treated_as_favorable_rate",
    # --- the Phase 2E.1 denominator must survive (ADR-016) -----------------
    "unexamined_component_omitted_from_denominator_rate",
    "incomplete_inventory_received_full_scalar_rate",
    # --- withholding must actually withhold (sections 11, 12) --------------
    "contested_claim_received_final_scalar_rate",
    "blocked_source_quality_received_final_scalar_rate",
    "not_ready_claim_received_final_scalar_rate",
    # --- the two channels must stay separate (section 8) -------------------
    "support_contradiction_collapsed_into_net_rate",
    "contradiction_increased_support_index_rate",
    "duplicate_evidence_increased_support_index_rate",
    "irrelevant_evidence_increased_support_index_rate",
    "retraction_increased_support_or_reliability_rate",
    "unknown_metadata_improved_reliability_rate",
    # --- arithmetic and contract integrity (sections 16, 21) ---------------
    "out_of_range_score_acceptance_rate",
    "aggregate_score_arithmetic_mismatch_rate",
    "invalid_score_disposition_acceptance_rate",
    "missing_scoring_policy_version_rate",
    "unstable_identical_input_fingerprint_rate",
    "fingerprint_unchanged_on_relevant_input_change_rate",
    "incompatible_duplicate_scorecard_acceptance_rate",
    # --- the boundary this phase must not cross (sections 6, 28) -----------
    "score_written_into_official_project_scoring_rate",
    "score_typed_as_truth_probability_rate",
)
"""All 48 gates the specification requires, reported individually (section 32).

Grouped by the failure each one watches for, and deliberately not merged: "a
duplicate excerpt inflated the support index" and "a retracted source counted as
eligible support" are different defects with different fixes, and a report that
folded them together would hide which one fired."""

REQUIRED_PERFECT_METRICS: tuple[str, ...] = (
    "support_index_accuracy",
    "contradiction_index_accuracy",
    "coverage_dimension_accuracy",
    "corroboration_dimension_accuracy",
    "directness_dimension_accuracy",
    "score_disposition_accuracy",
    "final_scalar_issuance_accuracy",
    "reliability_profile_accuracy",
    "score_bound_accuracy",
    "arithmetic_reconciliation_accuracy",
    "input_fingerprint_accuracy",
    "idempotency_accuracy",
    "score_traceability",
    "policy_version_accuracy",
    "component_denominator_accuracy",
    "duplicate_invariance_accuracy",
    "monotonicity_invariant_accuracy",
)
"""Quality metrics that must be exactly 1.0, and actually measured, to release."""


def violation_rate(counts: SafetyCounts) -> float | None:
    return counts.violations / counts.checked if counts.checked else None


def _counts() -> MetricCounts:
    return MetricCounts()


class ClaimScoringMetrics(MawhibaModel):
    # --- quality ------------------------------------------------------------
    support_index_accuracy: MetricCounts = Field(default_factory=_counts)
    contradiction_index_accuracy: MetricCounts = Field(default_factory=_counts)
    coverage_dimension_accuracy: MetricCounts = Field(default_factory=_counts)
    corroboration_dimension_accuracy: MetricCounts = Field(default_factory=_counts)
    directness_dimension_accuracy: MetricCounts = Field(default_factory=_counts)
    score_disposition_accuracy: MetricCounts = Field(default_factory=_counts)
    final_scalar_issuance_accuracy: MetricCounts = Field(default_factory=_counts)
    reliability_profile_accuracy: MetricCounts = Field(default_factory=_counts)
    score_bound_accuracy: MetricCounts = Field(default_factory=_counts)
    arithmetic_reconciliation_accuracy: MetricCounts = Field(default_factory=_counts)
    input_fingerprint_accuracy: MetricCounts = Field(default_factory=_counts)
    idempotency_accuracy: MetricCounts = Field(default_factory=_counts)
    score_traceability: MetricCounts = Field(default_factory=_counts)
    policy_version_accuracy: MetricCounts = Field(default_factory=_counts)
    component_denominator_accuracy: MetricCounts = Field(default_factory=_counts)
    duplicate_invariance_accuracy: MetricCounts = Field(default_factory=_counts)
    monotonicity_invariant_accuracy: MetricCounts = Field(default_factory=_counts)
    run_status_accuracy: MetricCounts = Field(default_factory=_counts)
    reason_code_accuracy: MetricCounts = Field(default_factory=_counts)
    withheld_reason_accuracy: MetricCounts = Field(default_factory=_counts)
    unexamined_component_accuracy: MetricCounts = Field(default_factory=_counts)
    saturation_accuracy: MetricCounts = Field(default_factory=_counts)
    exact_claim_anchor_accuracy: MetricCounts = Field(default_factory=_counts)
    zero_versus_none_accuracy: MetricCounts = Field(default_factory=_counts)

    # --- release-blocking (target: zero) ------------------------------------
    project_state_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    claim_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    claim_status_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    claim_confidence_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    claim_evidence_reference_mutation_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    claim_counter_evidence_reference_mutation_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    canonical_score_record_mutation_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    trust_gate_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    evaluation_status_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    extracted_evidence_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    alignment_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    sufficiency_assessment_mutation_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    automatic_project_score_update_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    automatic_claim_status_update_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    invalid_sufficiency_assessment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    cross_run_assessment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    cross_claim_scorecard_contamination_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_logical_source_inflated_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_logical_source_inflated_contradiction_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_excerpt_inflated_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_excerpt_inflated_contradiction_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    provider_observation_inflated_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    provider_observation_inflated_contradiction_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    context_only_counted_as_direct_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    insufficient_counted_as_direct_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    not_relevant_counted_as_direct_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    retracted_source_counted_as_eligible_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unknown_quality_treated_as_favorable_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unexamined_component_omitted_from_denominator_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    incomplete_inventory_received_full_scalar_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    contested_claim_received_final_scalar_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    blocked_source_quality_received_final_scalar_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    not_ready_claim_received_final_scalar_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    support_contradiction_collapsed_into_net_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    contradiction_increased_support_index_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_evidence_increased_support_index_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    irrelevant_evidence_increased_support_index_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    retraction_increased_support_or_reliability_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unknown_metadata_improved_reliability_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    out_of_range_score_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    aggregate_score_arithmetic_mismatch_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    invalid_score_disposition_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    missing_scoring_policy_version_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unstable_identical_input_fingerprint_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    fingerprint_unchanged_on_relevant_input_change_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    incompatible_duplicate_scorecard_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    score_written_into_official_project_scoring_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    score_typed_as_truth_probability_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )

    cases_evaluated: int = Field(default=0, ge=0)
    cases_errored: int = Field(default=0, ge=0)

    @property
    def quality_metrics(self) -> dict[str, MetricCounts]:
        return {
            name: getattr(self, name)
            for name in type(self).model_fields
            if isinstance(getattr(self, name), MetricCounts)
        }

    @property
    def safety_metrics(self) -> dict[str, SafetyCounts]:
        return {name: getattr(self, name) for name in RELEASE_BLOCKING_SCORING_METRICS}

    @property
    def safety_clean(self) -> bool:
        return all(counts.clean for counts in self.safety_metrics.values())

    @property
    def thresholds_met(self) -> bool:
        """Every required metric is exactly 1.0, and actually measured."""
        for name in REQUIRED_PERFECT_METRICS:
            counts = getattr(self, name)
            if counts.total == 0 or counts.rate != 1.0:
                return False
        return True

    def to_report(self) -> dict[str, object]:
        return {
            "cases_evaluated": self.cases_evaluated,
            "cases_errored": self.cases_errored,
            "safety_clean": self.safety_clean,
            "thresholds_met": self.thresholds_met,
            "quality": {
                name: {"matched": c.matched, "total": c.total, "rate": c.rate}
                for name, c in self.quality_metrics.items()
            },
            "release_blocking": {
                name: {
                    "violations": c.violations,
                    "checked": c.checked,
                    "rate": violation_rate(c),
                }
                for name, c in self.safety_metrics.items()
            },
        }


__all__ = [
    "RELEASE_BLOCKING_SCORING_METRICS",
    "REQUIRED_PERFECT_METRICS",
    "ClaimScoringMetrics",
    "violation_rate",
]
