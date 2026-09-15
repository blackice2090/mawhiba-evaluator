"""Research planning metrics.

Every metric exposes its numerator and denominator. An unmeasured metric reports
``None``, never zero. Release-blocking metrics are violation counts with a target
of exactly zero.
"""

from __future__ import annotations

from pydantic import Field

from src.evals.metrics import MetricCounts, SafetyCounts
from src.schemas.common import MawhibaModel

RELEASE_BLOCKING_RESEARCH_METRICS: tuple[str, ...] = (
    "pii_leakage_rate",
    "invalid_field_reference_rate",
    "project_state_mutation_rate",
    "untraceable_accepted_queries",
)


def violation_rate(counts: SafetyCounts) -> float | None:
    return counts.violations / counts.checked if counts.checked else None


class ResearchPlanningMetrics(MawhibaModel):
    # --- quality ---------------------------------------------------------
    query_source_traceability: MetricCounts = Field(default_factory=MetricCounts)
    required_query_family_coverage: MetricCounts = Field(default_factory=MetricCounts)
    accepted_query_set_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    rejection_reason_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    anti_confirmation_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    duplicate_removal_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    plan_issue_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    planner_invocation_accuracy: MetricCounts = Field(default_factory=MetricCounts)

    # --- rates reported as violations -------------------------------------
    duplicate_query_rate: SafetyCounts = Field(default_factory=SafetyCounts)

    # --- release-blocking (target: zero) ---------------------------------
    pii_leakage_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    invalid_field_reference_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    project_state_mutation_rate: SafetyCounts = Field(default_factory=SafetyCounts)
    untraceable_accepted_queries: SafetyCounts = Field(default_factory=SafetyCounts)

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
        return {name: getattr(self, name) for name in RELEASE_BLOCKING_RESEARCH_METRICS}

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
            "duplicate_query_rate": {
                "violations": self.duplicate_query_rate.violations,
                "checked": self.duplicate_query_rate.checked,
                "rate": violation_rate(self.duplicate_query_rate),
            },
            "release_blocking": {
                name: {"violations": c.violations, "checked": c.checked, "rate": violation_rate(c)}
                for name, c in self.safety_metrics.items()
            },
        }
