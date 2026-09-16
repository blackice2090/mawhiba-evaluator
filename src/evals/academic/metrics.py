"""Academic retrieval metrics.

Every quality metric exposes its numerator and denominator, and a metric that
nothing exercised reports ``None`` rather than ``0.0`` -- "not measured" and
"measured at zero" are different statements about a release.

The release-blocking metrics are violation counts with a target of exactly zero.
They are counted rather than rated on purpose: a single wrong merge or a single
leaked identifier is not a percentage, it is a defect.
"""

from __future__ import annotations

from pydantic import Field

from src.evals.metrics import MetricCounts, SafetyCounts
from src.schemas.common import MawhibaModel

RELEASE_BLOCKING_ACADEMIC_METRICS: tuple[str, ...] = (
    "pii_leakage_rate",
    "project_state_mutation_rate",
    "evidence_creation_violation_rate",
    "claim_mutation_violation_rate",
    "untraceable_verified_source",
    "invalid_strong_identifier_merge",
    "provider_provenance_loss",
)


def violation_rate(counts: SafetyCounts) -> float | None:
    return counts.violations / counts.checked if counts.checked else None


class AcademicRetrievalMetrics(MawhibaModel):
    # --- quality ---------------------------------------------------------
    identifier_normalization_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    cross_provider_dedup_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    provider_observation_preservation: MetricCounts = Field(default_factory=MetricCounts)
    metadata_merge_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    rejected_candidate_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    provider_failure_isolation_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    budget_enforcement_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    source_traceability: MetricCounts = Field(default_factory=MetricCounts)

    # --- release-blocking (target: zero) ---------------------------------
    pii_leakage_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    project_state_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    evidence_creation_violation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    claim_mutation_violation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    untraceable_verified_source: SafetyCounts = Field(default_factory=SafetyCounts)
    invalid_strong_identifier_merge: SafetyCounts = Field(default_factory=SafetyCounts)
    provider_provenance_loss: SafetyCounts = Field(default_factory=SafetyCounts)

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
            name: getattr(self, name) for name in RELEASE_BLOCKING_ACADEMIC_METRICS
        }

    @property
    def safety_clean(self) -> bool:
        return all(counts.clean for counts in self.safety_metrics.values())

    def to_report(self) -> dict[str, object]:
        return {
            "cases_evaluated": self.cases_evaluated,
            "cases_errored": self.cases_errored,
            "safety_clean": self.safety_clean,
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
    "RELEASE_BLOCKING_ACADEMIC_METRICS",
    "AcademicRetrievalMetrics",
    "violation_rate",
]
