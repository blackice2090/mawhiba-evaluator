"""Claim-evidence scoring eval entry point (deterministic, no model at all).

    python -m src.evals.claim_scoring.cli
    python -m src.evals.claim_scoring.cli --report

No network, no credentials, no model -- not even a fake provider, because
Phase 2F makes no model call by architecture (section 19) and a model-generated
score is forbidden. The exit code is the gate: non-zero when any
release-blocking metric is non-zero, any required quality metric falls below
1.0, or any case errored.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.evals.baseline import REPORT_ROOT
from src.evals.claim_scoring.dataset import (
    DEFAULT_SCORING_DATASET_VERSION,
    load_scoring_dataset,
)
from src.evals.claim_scoring.metrics import REQUIRED_PERFECT_METRICS
from src.evals.claim_scoring.runner import (
    evaluate_scoring_gate,
    run_scoring_dataset,
    score_by_language,
)
from src.evals.metrics import MetricCounts
from src.schemas.claim_evidence_score import (
    CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION,
    CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
    SCORE_ARITHMETIC_VERSION,
    SCORE_RELIABILITY_PROFILE_VERSION,
)
from src.schemas.common import utc_now


def _rate(counts: MetricCounts) -> str:
    return "not measured" if counts.rate is None else f"{counts.rate:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the claim-evidence scoring evaluation."
    )
    parser.add_argument("--dataset", default=DEFAULT_SCORING_DATASET_VERSION)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    dataset = load_scoring_dataset(args.dataset)
    metrics, results = run_scoring_dataset(dataset)
    by_language = score_by_language(dataset, results)
    gate = evaluate_scoring_gate(metrics)
    provenance = {
        "dataset_version": dataset.version,
        "score_schema_version": CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION,
        "scoring_policy_version": CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
        "arithmetic_version": SCORE_ARITHMETIC_VERSION,
        "reliability_profile_version": SCORE_RELIABILITY_PROFILE_VERSION,
        "mode": "DETERMINISTIC",
    }

    print(f"Claim evidence scoring eval (DETERMINISTIC) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(
        f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})"
    )
    print(f"  languages: {json.dumps(dataset.language_counts, sort_keys=True)}")
    print(f"  dispositions: {json.dumps(dataset.disposition_counts, sort_keys=True)}")
    print(f"  reliability: {json.dumps(dataset.reliability_counts, sort_keys=True)}")
    print(f"  categories: {json.dumps(dataset.category_counts, sort_keys=True)}")
    for name, counts in metrics.quality_metrics.items():
        required = " [required 1.0]" if name in REQUIRED_PERFECT_METRICS else ""
        print(f"  {name}: {counts.matched}/{counts.total} = {_rate(counts)}{required}")
    print("  release-blocking:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print("  by language:")
    for language in sorted(by_language):
        subgroup = by_language[language]
        print(f"    {language}: cases={subgroup.cases_evaluated}")
        for name in REQUIRED_PERFECT_METRICS:
            counts = getattr(subgroup, name)
            print(f"      {name}: {counts.matched}/{counts.total} = {_rate(counts)}")
        print(
            f"      safety_clean={subgroup.safety_clean} "
            f"total_violations="
            f"{sum(c.violations for c in subgroup.safety_metrics.values())}"
        )
    print(f"  gate: {gate.summary()}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"claim_evidence_scoring_{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "provenance": provenance,
                    "metrics": metrics.to_report(),
                    "by_language": {k: v.to_report() for k, v in by_language.items()},
                    "gate": {
                        "passed": gate.passed,
                        "safety_clean": gate.safety_clean,
                        "thresholds_met": gate.thresholds_met,
                        "violations": gate.violations,
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  report: {path}")

    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
