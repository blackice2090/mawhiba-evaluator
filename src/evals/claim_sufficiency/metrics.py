"""Claim sufficiency metrics -- Phase 2E (section 31, section 32).

Quality metrics expose numerator and denominator, and a metric nothing
exercised reports ``None`` rather than ``0.0`` (section 19, section 31): a
subgroup with no cases has *not measured* accuracy, which is a different claim
from perfect accuracy or zero accuracy.

The release-blocking metrics are violation counts with a target of exactly
zero. A duplicate logical source counted as independent corroboration is not a
percentage to improve -- it is the failure this phase exists to prevent.
"""

from __future__ import annotations

from pydantic import Field

from src.evals.metrics import MetricCounts, SafetyCounts
from src.schemas.common import MawhibaModel

RELEASE_BLOCKING_SUFFICIENCY_METRICS: tuple[str, ...] = (
    "project_state_mutation_rate",
    "claim_mutation_rate",
    "claim_status_mutation_rate",
    "claim_confidence_mutation_rate",
    "claim_evidence_reference_mutation_rate",
    "claim_counter_evidence_reference_mutation_rate",
    "score_mutation_rate",
    "trust_gate_mutation_rate",
    "evaluation_status_mutation_rate",
    "extracted_evidence_mutation_rate",
    "alignment_mutation_rate",
    "automatic_claim_status_update_rate",
    "automatic_score_update_rate",
    "invalid_claim_reference_acceptance_rate",
    "invalid_evidence_reference_acceptance_rate",
    "invalid_alignment_reference_acceptance_rate",
    "cross_run_evidence_acceptance_rate",
    "cross_run_alignment_acceptance_rate",
    "untraceable_evidence_contribution_rate",
    "retracted_evidence_corroboration_rate",
    "duplicate_logical_source_independence_rate",
    "duplicate_excerpt_independence_rate",
    "provider_observation_independence_rate",
    "context_only_counted_as_support_rate",
    "insufficient_counted_as_support_rate",
    "not_relevant_counted_as_support_rate",
    "unknown_quality_treated_as_favorable_rate",
    "incomplete_alignment_treated_as_complete_rate",
    "pair_limit_blocked_treated_as_complete_rate",
    "contradiction_silently_discarded_rate",
    "incompatible_duplicate_assessment_rate",
    "sufficiency_mutated_trust_gate_rate",
    "sufficiency_mutated_project_score_rate",
)
"""Every gate the specification requires, reported individually (section 32)."""

REQUIRED_PERFECT_METRICS: tuple[str, ...] = (
    "independence_grouping_accuracy",
    "duplicate_collapse_accuracy",
    "component_coverage_accuracy",
    "contribution_classification_accuracy",
    "sufficiency_outcome_accuracy",
    "contradiction_preservation_accuracy",
    "retraction_handling_accuracy",
    "unknown_state_preservation_accuracy",
    "assessment_traceability",
    "deterministic_rerun_accuracy",
)
"""Quality metrics that must be exactly 1.0, and actually measured, to release."""


def violation_rate(counts: SafetyCounts) -> float | None:
    return counts.violations / counts.checked if counts.checked else None


class ClaimSufficiencyMetrics(MawhibaModel):
    # --- quality ------------------------------------------------------------
    independence_grouping_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    duplicate_collapse_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    component_coverage_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    contribution_classification_accuracy: MetricCounts = Field(
        default_factory=MetricCounts
    )
    sufficiency_outcome_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    contradiction_preservation_accuracy: MetricCounts = Field(
        default_factory=MetricCounts
    )
    retraction_handling_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    unknown_state_preservation_accuracy: MetricCounts = Field(
        default_factory=MetricCounts
    )
    assessment_traceability: MetricCounts = Field(default_factory=MetricCounts)
    deterministic_rerun_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    reason_code_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    blocker_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    run_status_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    scope_ceiling_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    exact_claim_anchor_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    policy_versioning_accuracy: MetricCounts = Field(default_factory=MetricCounts)

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
    score_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    trust_gate_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    evaluation_status_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    extracted_evidence_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    alignment_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    automatic_claim_status_update_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    automatic_score_update_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    invalid_claim_reference_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    invalid_evidence_reference_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    invalid_alignment_reference_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    cross_run_evidence_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    cross_run_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    untraceable_evidence_contribution_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    retracted_evidence_corroboration_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_logical_source_independence_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    duplicate_excerpt_independence_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    provider_observation_independence_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    context_only_counted_as_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    insufficient_counted_as_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    not_relevant_counted_as_support_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unknown_quality_treated_as_favorable_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    incomplete_alignment_treated_as_complete_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    pair_limit_blocked_treated_as_complete_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    contradiction_silently_discarded_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    incompatible_duplicate_assessment_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    sufficiency_mutated_trust_gate_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    sufficiency_mutated_project_score_rate: SafetyCounts = Field(
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
        return {
            name: getattr(self, name) for name in RELEASE_BLOCKING_SUFFICIENCY_METRICS
        }

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
    "RELEASE_BLOCKING_SUFFICIENCY_METRICS",
    "REQUIRED_PERFECT_METRICS",
    "ClaimSufficiencyMetrics",
    "violation_rate",
]
