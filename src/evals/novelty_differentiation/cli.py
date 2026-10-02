"""Phase 2I offline eval CLI.

    ./.venv/Scripts/python.exe -m src.evals.novelty_differentiation.cli [--dataset PATH] [--case NI-001] [--verbose]

Deterministic and offline: every upstream provider and the structured model are
scripted fakes. Writes a JSON report to the git-ignored ``eval_reports/`` and
exits non-zero unless the eval passes (all quality families 1.0, all gates zero
with real denominators, every negative control caught, no errored case,
dataset minimums met).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.evals.novelty_differentiation.dataset import DATASET_VERSION, DEFAULT_DATASET, load_cases
from src.evals.novelty_differentiation.metrics import REQUIRED_QUALITY_FAMILIES, build_report
from src.evals.novelty_differentiation.runner import run_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # claims may be Arabic data

    cases = load_cases(args.dataset)
    if args.case:
        cases = [c for c in cases if c.case_id in set(args.case)]
    started = time.perf_counter()
    results = [run_case(case) for case in cases]
    report = build_report(results)
    elapsed = time.perf_counter() - started

    print(f"Phase 2I novelty/differentiation eval ({DATASET_VERSION}) -- {report.total} cases in {elapsed:.1f}s")
    print(f"  languages: {report.languages}; categories: {report.categories}; minimums met: {report.minimums_met}")
    print(f"  errored: {len(report.errored)}; failed cases: {len(report.failed_cases)}")
    print("  quality:")
    for family in REQUIRED_QUALITY_FAMILIES:
        value = report.quality.get(family)
        num, den = report.quality_counts.get(family, (0, 0))
        shown = "None (not measured)" if value is None else f"{value:.4f}"
        print(f"    {family:38s} {shown}  ({num}/{den})")
    print("  per_language_contract_accuracy:")
    for lang, value in sorted(report.per_language.items()):
        print(f"    {lang:6s} {value:.4f}")
    print("  release-blocking gates (violations/denominator):")
    for index, (gate, (num, den)) in enumerate(report.gates.items(), start=1):
        flag = "" if num == 0 and den > 0 else "  <-- FAIL"
        print(f"    {index:2d}. {gate:62s} {num}/{den}{flag}")
    print(f"  negative controls caught: {report.controls[0]}/{report.controls[1]} "
          f"({len(report.control_names)} distinct)")
    shown = report.failures if args.verbose else report.failures[:25]
    for failure in shown:
        print(f"    FAIL {failure['case']} {failure['key']}: expected {failure['expected']!r} got {failure['actual']!r}")
    for result in results:
        if result.error:
            print(f"    ERROR {result.case.case_id}: {result.error.strip().splitlines()[-1]}")
            if args.verbose:
                print(result.error)
        for name, ok, how in result.controls:
            if ok is False:
                print(f"    CONTROL NOT CAUGHT {result.case.case_id}: {name}")
    out = Path("eval_reports")
    out.mkdir(exist_ok=True)
    (out / "phase2i_novelty_differentiation.json").write_text(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "total": report.total,
                "languages": report.languages,
                "categories": report.categories,
                "quality": report.quality,
                "per_language": report.per_language,
                "gates": {g: {"violations": v, "denominator": d} for g, (v, d) in report.gates.items()},
                "controls": {"caught": report.controls[0], "total": report.controls[1], "names": report.control_names},
                "failed_cases": report.failed_cases,
                "errored": report.errored,
                "passed": report.passed,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("PASS" if report.passed else "FAIL")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
