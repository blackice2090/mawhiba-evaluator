"""Approved metric baselines and the regression gate.

A baseline is an explicitly approved snapshot of what the intake layer scored.
Future prompt, model or code changes are compared against it, so a quality
change is a reviewed decision rather than something noticed months later.

The approved baseline is **never** overwritten automatically. Updating it is a
deliberate developer action (``write_baseline(..., approve=True)``), because a
baseline that silently tracks current behaviour records nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from src.evals.metrics import (
    CRITICAL_SAFETY_METRICS,
    IntakeMetrics,
    MetricComparison,
)
from src.llm.prompts import PROMPT_VERSIONS
from src.schemas.common import MawhibaModel, UtcDatetime, utc_now

BASELINE_ROOT = Path(__file__).resolve().parents[2] / "evals" / "intake" / "baselines"
REPORT_ROOT = Path(__file__).resolve().parents[2] / "eval_reports"

REGRESSION_TOLERANCE = 1e-9
"""Quality metrics are exact ratios in fake mode, so any drop is a real drop."""


class RunProvenance(MawhibaModel):
    """What produced a result.

    Recorded so a score can be reproduced later: a number without its prompt
    version, model and dataset version is not a measurement, it is a rumour.
    """

    dataset_version: str
    extractor_prompt_version: str = Field(
        default_factory=lambda: PROMPT_VERSIONS["PROJECT_EXTRACTOR_PROMPT"]
    )
    classifier_prompt_version: str = Field(
        default_factory=lambda: PROMPT_VERSIONS["PROJECT_CLASSIFIER_PROMPT"]
    )
    provider: str = "fake"
    model: str = "fake"
    mode: str = Field(default="FAKE", pattern=r"^(FAKE|LIVE)$")
    code_version: str | None = Field(
        default=None, description="Git revision when available."
    )
    recorded_at: UtcDatetime = Field(default_factory=utc_now)


class EvalBaseline(MawhibaModel):
    """An approved snapshot of intake metrics."""

    provenance: RunProvenance
    quality_rates: dict[str, float] = Field(default_factory=dict)
    safety_violations: dict[str, int] = Field(default_factory=dict)
    cases_evaluated: int = 0
    approved: bool = Field(
        default=False,
        description="Only an explicitly approved file is a baseline. An "
        "unapproved snapshot is a draft.",
    )
    note: str = ""

    @classmethod
    def from_metrics(
        cls, metrics: IntakeMetrics, provenance: RunProvenance, *, note: str = ""
    ) -> EvalBaseline:
        return cls(
            provenance=provenance,
            quality_rates={
                name: counts.rate
                for name, counts in metrics.quality_metrics.items()
                if counts.rate is not None
            },
            safety_violations={
                name: counts.violations
                for name, counts in metrics.safety_metrics.items()
            },
            cases_evaluated=metrics.cases_evaluated,
            note=note,
        )


def baseline_path(version: str = "v1") -> Path:
    return BASELINE_ROOT / f"{version}.json"


def load_baseline(version: str = "v1") -> EvalBaseline | None:
    """Load the approved baseline, or None when none has been approved yet."""
    path = baseline_path(version)
    if not path.exists():
        return None
    return EvalBaseline.model_validate(json.loads(path.read_text(encoding="utf-8")))


def write_baseline(
    baseline: EvalBaseline, version: str = "v1", *, approve: bool = False
) -> Path:
    """Write a baseline file.

    ``approve`` must be passed explicitly. Without it the file is marked as a
    draft, so an accidental write cannot quietly become the approved reference.
    """
    path = baseline_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = baseline.model_copy(update={"approved": approve})
    path.write_text(
        json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def compare_to_baseline(
    metrics: IntakeMetrics, baseline: EvalBaseline
) -> list[MetricComparison]:
    """Classify every metric as IMPROVED, UNCHANGED, REGRESSED or NEW."""
    comparisons: list[MetricComparison] = []

    for name, counts in metrics.quality_metrics.items():
        if counts.rate is None:
            continue
        previous = baseline.quality_rates.get(name)
        if previous is None:
            verdict = "NEW"
        elif counts.rate > previous + REGRESSION_TOLERANCE:
            verdict = "IMPROVED"
        elif counts.rate < previous - REGRESSION_TOLERANCE:
            verdict = "REGRESSED"
        else:
            verdict = "UNCHANGED"
        comparisons.append(
            MetricComparison(
                metric=name, baseline=previous, current=counts.rate, verdict=verdict
            )
        )

    for name, counts in metrics.safety_metrics.items():
        previous = baseline.safety_violations.get(name)
        current = float(counts.violations)
        if previous is None:
            verdict = "NEW"
        elif current > previous:
            verdict = "REGRESSED"
        elif current < previous:
            verdict = "IMPROVED"
        else:
            verdict = "UNCHANGED"
        comparisons.append(
            MetricComparison(
                metric=name,
                baseline=float(previous) if previous is not None else None,
                current=current,
                verdict=verdict,
                critical=name in CRITICAL_SAFETY_METRICS,
            )
        )

    return comparisons


class GateResult(MawhibaModel):
    """The verdict of the regression gate."""

    passed: bool
    safety_clean: bool
    blocking: list[str] = Field(default_factory=list)
    regressed: list[str] = Field(default_factory=list)
    improved: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    new_metrics: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{'PASS' if self.passed else 'FAIL'} "
            f"safety_clean={self.safety_clean} "
            f"blocking={len(self.blocking)} regressed={len(self.regressed)} "
            f"improved={len(self.improved)}"
        )


def evaluate_gate(
    metrics: IntakeMetrics, baseline: EvalBaseline | None
) -> GateResult:
    """Run the regression gate.

    Two independent failure conditions:

    1. Any safety violation at all -- the hard targets are zero, regardless of
       what the baseline said.
    2. A regression in a critical safety metric relative to the baseline.

    A quality regression is reported but does not block, because a deliberate
    precision/recall trade is a decision for a reviewer, not for a gate.
    """
    safety_clean = metrics.safety_clean
    result = GateResult(passed=safety_clean, safety_clean=safety_clean)

    if baseline is None:
        result.new_metrics = sorted(metrics.quality_metrics)
        return result

    for comparison in compare_to_baseline(metrics, baseline):
        if comparison.blocking:
            result.blocking.append(comparison.metric)
        if comparison.verdict == "REGRESSED":
            result.regressed.append(comparison.metric)
        elif comparison.verdict == "IMPROVED":
            result.improved.append(comparison.metric)
        elif comparison.verdict == "UNCHANGED":
            result.unchanged.append(comparison.metric)
        else:
            result.new_metrics.append(comparison.metric)

    result.passed = safety_clean and not result.blocking
    return result


def write_report(
    metrics: IntakeMetrics, provenance: RunProvenance, gate: GateResult
) -> Path:
    """Write a timestamped machine-readable report.

    Reports land in ``eval_reports/`` which is git-ignored: a generated
    measurement is not a source artifact.
    """
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = provenance.recorded_at.strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_ROOT / f"intake_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "provenance": provenance.model_dump(mode="json"),
                "metrics": metrics.to_report(),
                "gate": gate.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path
