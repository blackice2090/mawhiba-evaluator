"""Intake trust metrics.

The safety metrics are the point of this module. Accepted-field precision is
nice to know; **unsupported-known acceptance** is what decides whether the system
may be trusted to feed a research and scoring pipeline at all.

Every metric is computed deterministically from a canonical state and a Gold
expectation. No model participates in scoring its own output.
"""

from __future__ import annotations

from pydantic import Field

from src.schemas.common import MawhibaModel, UnitInterval


class MetricCounts(MawhibaModel):
    """A numerator/denominator pair, so a rate is never reported without its base."""

    matched: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)

    def add(self, matched: bool) -> None:
        self.total += 1
        if matched:
            self.matched += 1

    @property
    def rate(self) -> float | None:
        """None when nothing was measured -- distinct from a rate of 0.0."""
        return self.matched / self.total if self.total else None

    def __add__(self, other: MetricCounts) -> MetricCounts:
        return MetricCounts(
            matched=self.matched + other.matched, total=self.total + other.total
        )


class SafetyCounts(MawhibaModel):
    """Violations of a rule that must never be broken.

    Counted rather than rated: the target is zero, and a rate would dilute a
    single violation into a reassuring percentage.
    """

    violations: int = Field(default=0, ge=0)
    checked: int = Field(default=0, ge=0)

    def record(self, violated: bool) -> None:
        self.checked += 1
        if violated:
            self.violations += 1

    def __add__(self, other: SafetyCounts) -> SafetyCounts:
        return SafetyCounts(
            violations=self.violations + other.violations,
            checked=self.checked + other.checked,
        )

    @property
    def clean(self) -> bool:
        return self.violations == 0


class IntakeMetrics(MawhibaModel):
    """The full metric set for one evaluation run."""

    # --- quality ---------------------------------------------------------
    accepted_field_precision: MetricCounts = Field(default_factory=MetricCounts)
    unknown_preservation: MetricCounts = Field(default_factory=MetricCounts)
    provenance_validity: MetricCounts = Field(default_factory=MetricCounts)
    list_field_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    project_type_accuracy: MetricCounts = Field(default_factory=MetricCounts)
    domain_precision: MetricCounts = Field(default_factory=MetricCounts)
    domain_recall: MetricCounts = Field(default_factory=MetricCounts)
    conflict_precision: MetricCounts = Field(default_factory=MetricCounts)
    conflict_recall: MetricCounts = Field(default_factory=MetricCounts)
    canonical_merge_stability: MetricCounts = Field(default_factory=MetricCounts)
    student_claim_isolation: MetricCounts = Field(default_factory=MetricCounts)
    rejection_accuracy: MetricCounts = Field(default_factory=MetricCounts)

    # --- safety (target: zero violations) --------------------------------
    unsupported_known_acceptance: SafetyCounts = Field(default_factory=SafetyCounts)
    invalid_provenance_acceptance: SafetyCounts = Field(default_factory=SafetyCounts)
    student_claim_leakage: SafetyCounts = Field(default_factory=SafetyCounts)
    prompt_injection_mutation: SafetyCounts = Field(default_factory=SafetyCounts)

    cases_evaluated: int = Field(default=0, ge=0)
    cases_errored: int = Field(default=0, ge=0)

    def merge(self, other: IntakeMetrics) -> IntakeMetrics:
        """Combine two metric sets, e.g. across sharded runs."""
        merged = IntakeMetrics()
        for name in IntakeMetrics.model_fields:
            mine = getattr(self, name)
            theirs = getattr(other, name)
            if isinstance(mine, (MetricCounts, SafetyCounts)) or isinstance(mine, int):
                setattr(merged, name, mine + theirs)
        return merged

    # --- reporting --------------------------------------------------------

    @property
    def safety_metrics(self) -> dict[str, SafetyCounts]:
        return {
            "unsupported_known_acceptance": self.unsupported_known_acceptance,
            "invalid_provenance_acceptance": self.invalid_provenance_acceptance,
            "student_claim_leakage": self.student_claim_leakage,
            "prompt_injection_mutation": self.prompt_injection_mutation,
        }

    @property
    def quality_metrics(self) -> dict[str, MetricCounts]:
        return {
            name: getattr(self, name)
            for name in IntakeMetrics.model_fields
            if isinstance(getattr(self, name), MetricCounts)
        }

    @property
    def safety_clean(self) -> bool:
        """True only when every release-blocking rule held."""
        return all(counts.clean for counts in self.safety_metrics.values())

    def total_safety_violations(self) -> int:
        return sum(c.violations for c in self.safety_metrics.values())

    def to_report(self) -> dict[str, object]:
        """Machine-readable summary."""
        return {
            "cases_evaluated": self.cases_evaluated,
            "cases_errored": self.cases_errored,
            "safety_clean": self.safety_clean,
            "quality": {
                name: {
                    "matched": counts.matched,
                    "total": counts.total,
                    "rate": counts.rate,
                }
                for name, counts in self.quality_metrics.items()
            },
            "safety": {
                name: {"violations": counts.violations, "checked": counts.checked}
                for name, counts in self.safety_metrics.items()
            },
        }


CRITICAL_SAFETY_METRICS: tuple[str, ...] = (
    "unsupported_known_acceptance",
    "invalid_provenance_acceptance",
    "student_claim_leakage",
    "prompt_injection_mutation",
)
"""Metrics whose target is exactly zero violations.

A regression in any of these is release-blocking, not a quality trade-off.
"""


class MetricComparison(MawhibaModel):
    """One metric's movement against an approved baseline."""

    metric: str
    baseline: float | None = None
    current: float | None = None
    verdict: str = Field(pattern=r"^(IMPROVED|UNCHANGED|REGRESSED|NEW)$")
    critical: bool = False

    @property
    def blocking(self) -> bool:
        return self.critical and self.verdict == "REGRESSED"


__all__ = [
    "CRITICAL_SAFETY_METRICS",
    "IntakeMetrics",
    "MetricComparison",
    "MetricCounts",
    "SafetyCounts",
]
