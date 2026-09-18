"""Patent prior-art research eval entry point (deterministic, offline).

    python -m src.evals.patent_prior_art.cli
    python -m src.evals.patent_prior_art.cli --report

No network and no credentials: every case runs the real Phase 2G graph against
a scripted EPO OPS office whose XML goes through the real parser. The exit code
is the gate -- non-zero when any of the 48 release-blocking gates is non-zero,
any quality metric is below 1.0 or unmeasured, any negative control fails to
fire, any case errored, or a dataset minimum is not met.

This eval measures search mechanics, provenance and trust boundaries. It does
not, and cannot, measure novelty: Phase 2G makes no novelty, patentability or
legal prior-art determination (ADR-018).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.evals.baseline import REPORT_ROOT
from src.evals.patent_prior_art.dataset import (
    DEFAULT_PATENT_DATASET_PATH,
    load_patent_dataset,
)
from src.evals.patent_prior_art.metrics import compute_metrics
from src.evals.patent_prior_art.runner import evaluate_case
from src.research.patent.capabilities import capability_report
from src.schemas.common import utc_now
from src.schemas.patent import (
    PATENT_CHRONOLOGY_VERSION,
    PATENT_CONTRACT_VERSION,
    PATENT_FAMILY_VERSION,
    PATENT_IDENTITY_VERSION,
    PATENT_PLANNER_VERSION,
)


def _rate(value: float | None) -> str:
    return "not measured" if value is None else f"{value:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 2G patent eval.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATENT_DATASET_PATH)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    parser.add_argument("--verbose", action="store_true", help="print failing checks")
    args = parser.parse_args(argv)

    dataset = load_patent_dataset(args.dataset)
    results = [evaluate_case(case) for case in dataset.cases]
    metrics = compute_metrics(dataset, results)
    provenance = {
        "dataset_version": dataset.version,
        "contract_version": PATENT_CONTRACT_VERSION,
        "identity_version": PATENT_IDENTITY_VERSION,
        "family_version": PATENT_FAMILY_VERSION,
        "planner_version": PATENT_PLANNER_VERSION,
        "chronology_version": PATENT_CHRONOLOGY_VERSION,
        "mode": "OFFLINE_SCRIPTED_PROVIDER",
    }

    print(f"Patent prior-art research eval (OFFLINE) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(f"  cases: {metrics.total_cases} languages: {json.dumps(metrics.language_counts)}")
    print(f"  errored: {len(metrics.errored_cases)}  failed: {len(metrics.failed_cases)}")
    uncovered = [c for c, n in metrics.category_counts.items() if n == 0]
    print(
        f"  categories: {len(metrics.category_counts) - len(uncovered)}"
        f"/{len(metrics.category_counts)} covered"
    )
    print("  providers:")
    for row in capability_report():
        print(
            f"    {row['provider']}: {row['access_status']} "
            f"(live_request_observed={row['live_request_observed']})"
        )
    print("  quality (required 1.0):")
    for name, value in metrics.quality.items():
        print(f"    {name}: {_rate(value)} over {metrics.quality_denominators[name]}")
    print("  release-blocking gates:")
    for gate in metrics.gates:
        print(f"    {gate.name}: {gate.violations} / {gate.opportunities}")
    print("  negative controls (must fire):")
    for kind, (passed, total) in sorted(metrics.negative_controls.items()):
        print(f"    {kind}: {passed}/{total}")
    print("  per-language case pass rate:")
    for language, value in metrics.per_language.items():
        print(f"    {language}: {_rate(value)}")
    for problem in metrics.coverage_problems:
        print(f"  PROBLEM: {problem}")
    for line in metrics.errored_cases:
        print(f"  ERRORED {line}")
    if args.verbose:
        for result in results:
            if result.passed or result.error:
                continue
            failing = [k for k, ok in result.checks.items() if not ok]
            gates = [k for k, (v, _) in result.gates.items() if v]
            print(f"  FAILED {result.case.case_id}: checks={failing} gates={gates}")
    print(f"  result: {'PASS' if metrics.passed else 'FAIL'}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"patent_prior_art_{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "provenance": provenance,
                    "passed": metrics.passed,
                    "language_counts": metrics.language_counts,
                    "category_counts": metrics.category_counts,
                    "quality": metrics.quality,
                    "gates": {
                        g.name: {"violations": g.violations, "opportunities": g.opportunities}
                        for g in metrics.gates
                    },
                    "per_language": metrics.per_language,
                    "errored": metrics.errored_cases,
                    "failed": metrics.failed_cases,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  report: {path}")
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    sys.exit(main())
