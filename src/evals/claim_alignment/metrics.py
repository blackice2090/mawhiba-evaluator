"""Claim-evidence alignment metrics.

Quality metrics expose numerator and denominator; a metric nothing exercised
reports ``None`` rather than ``0.0`` (section 21). The release-blocking metrics
are violation counts with a target of exactly zero (section 22): an accepted
fabricated anchor is not a percentage, it is the failure this phase exists to
prevent.
"""

from __future__ import annotations

from pydantic import Field

from src.evals.metrics import MetricCounts, SafetyCounts
from src.schemas.common import MawhibaModel

RELEASE_BLOCKING_ALIGNMENT_METRICS: tuple[str, ...] = (
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
    "automatic_claim_support_rate",
    "invalid_claim_reference_acceptance_rate",
    "invalid_evidence_reference_acceptance_rate",
    "unverified_evidence_alignment_acceptance_rate",
    "cross_run_evidence_alignment_acceptance_rate",
    "fabricated_claim_anchor_acceptance_rate",
    "untraceable_alignment_acceptance_rate",
    "metadata_only_alignment_acceptance_rate",
    "provider_ai_synthesis_alignment_acceptance_rate",
    "structurally_inconsistent_relationship_acceptance_rate",
    "incompatible_duplicate_pair_acceptance_rate",
)

REQUIRED_PERFECT_METRICS: tuple[str, ...] = (
    "valid_alignment_reference_accuracy",
    "exact_claim_anchor_accuracy",
    "relationship_taxonomy_contract_accuracy",
    "component_pair_consistency_accuracy",
    "alignment_traceability",
)
"""Quality metrics that must be exactly 1.0 to release (section 21, 27)."""


def violation_rate(counts: SafetyCounts) -> float | None:
    return counts.violations / counts.checked if counts.checked else None


class ClaimAlignmentMetrics(MawhibaModel):
    # --- quality ------------------------------------------------------------
    valid_alignment_reference_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    exact_claim_anchor_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    relationship_taxonomy_contract_accuracy: MetricCounts = Field(
        default_factory=MetricCounts
    )
    component_pair_consistency_accuracy: MetricCounts = Field(
        default_factory=MetricCounts
    )
    alignment_traceability: MetricCounts = Field(default_factory=MetricCounts)
    deterministic_pair_coverage: MetricCounts = Field(default_factory=MetricCounts)
    checkpoint_idempotency_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    rejected_candidate_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    relation_accuracy: MetricCounts = Field(default_factory=MetricCounts)

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
    automatic_claim_support_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    invalid_claim_reference_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    invalid_evidence_reference_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    unverified_evidence_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    cross_run_evidence_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    fabricated_claim_anchor_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    untraceable_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    metadata_only_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    provider_ai_synthesis_alignment_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    structurally_inconsistent_relationship_acceptance_rate: SafetyCounts = Field(
        default_factory=SafetyCounts
    )
    incompatible_duplicate_pair_acceptance_rate: SafetyCounts = Field(
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
        return {name: getattr(self, name) for name in RELEASE_BLOCKING_ALIGNMENT_METRICS}

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
    "RELEASE_BLOCKING_ALIGNMENT_METRICS",
    "REQUIRED_PERFECT_METRICS",
    "ClaimAlignmentMetrics",
    "violation_rate",
]
