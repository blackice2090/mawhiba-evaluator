"""Phase 2H offline eval CLI.

    ./.venv/Scripts/python.exe -m src.evals.product_oss_prior_art.cli [--dataset PATH] [--case PH-001] [--verbose]

Deterministic and offline: every provider is a scripted fake. Writes a JSON
report to the git-ignored ``eval_reports/`` and exits non-zero unless the eval
passes (all quality families 1.0, all gates zero with real denominators, every
negative control rejected, no errored case, minimums met).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.evals.product_oss_prior_art.dataset import DATASET_VERSION, DEFAULT_DATASET, load_cases
from src.evals.product_oss_prior_art.metrics import build_report
from src.evals.product_oss_prior_art.runner import run_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases(args.dataset)
    if args.case:
        cases = [c for c in cases if c.case_id in set(args.case)]
    started = time.perf_counter()
    results = [run_case(case) for case in cases]
    report = build_report(results)
    elapsed = time.perf_counter() - started

    print(f"Phase 2H product/OSS prior-art eval ({DATASET_VERSION}) -- {report.total} cases in {elapsed:.1f}s")
    print(f"  languages: {report.languages}; categories: {report.categories}; minimums met: {report.minimums_met}")
    print(f"  errored: {len(report.errored)}; failed cases: {len(report.failed_cases)}")
    print("  quality:")
    for family, value in sorted(report.quality.items()):
        num, den = report.quality_counts.get(family, (0, 0))
        shown = "None (not measured)" if value is None else f"{value:.4f}"
        print(f"    {family:34s} {shown}  ({num}/{den})")
    print("  per-language contract accuracy:")
    for lang, value in sorted(report.per_language.items()):
        print(f"    {lang:6s} {value:.4f}")
    print("  release-blocking gates (violations/denominator):")
    for index, (gate, (num, den)) in enumerate(report.gates.items(), start=1):
        flag = "" if num == 0 and den > 0 else "  <-- FAIL"
        print(f"    {index:2d}. {gate:48s} {num}/{den}{flag}")
    print(f"  negative controls rejected: {report.controls[0]}/{report.controls[1]}")
    shown = report.failures if args.verbose else report.failures[:25]
    for failure in shown:
        print(f"    FAIL {failure['case']} {failure['key']}: expected {failure['expected']!r} got {failure['actual']!r}")
    for result in results:
        if result.error:
            print(f"    ERROR {result.case.case_id}: {result.error.splitlines()[0]}")
            if args.verbose:
                print(result.error)
        for name, rejected in result.controls:
            if not rejected:
                print(f"    CONTROL ACCEPTED {result.case.case_id}: {name}")

    out = Path("eval_reports")
    out.mkdir(exist_ok=True)
    (out / "phase2h_product_oss_prior_art.json").write_text(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "total": report.total,
                "languages": report.languages,
                "categories": report.categories,
                "errored": report.errored,
                "failed_cases": report.failed_cases,
                "quality": report.quality,
                "quality_counts": report.quality_counts,
                "per_language": report.per_language,
                "gates": report.gates,
                "controls": report.controls,
                "failures": report.failures,
                "passed": report.passed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"RESULT: {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
