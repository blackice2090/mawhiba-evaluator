"""Phase 2J offline Gold eval. Deterministic: real upstream graphs, scripted model, no network.

    ./.venv/Scripts/python.exe -m src.evals.research_engineering_gap.cli
    ./.venv/Scripts/python.exe -m src.evals.research_engineering_gap.cli --case GP-001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.evals.research_engineering_gap.controls import ALL_CONTROLS, reset_control_budget
from src.evals.research_engineering_gap.dataset import DEFAULT_DATASET, load_cases
from src.evals.research_engineering_gap.metrics import REQUIRED_QUALITY_FAMILIES, EvalReport, build_report
from src.evals.research_engineering_gap.runner import run_case

REPORT_DIR = Path(__file__).resolve().parents[3] / "eval_reports"


def run_all(path: Path = DEFAULT_DATASET, only: set[str] | None = None) -> tuple[list, EvalReport]:
    reset_control_budget()
    cases = [c for c in load_cases(path) if not only or c.case_id in only]
    results = [run_case(c) for c in cases]
    return results, build_report(results, ALL_CONTROLS)


_CACHE: dict[str, tuple[list, EvalReport]] = {}


def cached_run() -> tuple[list, EvalReport]:
    """The full Gold run, computed once per process (the eval tests share it)."""
    if "full" not in _CACHE:
        _CACHE["full"] = run_all()
    return _CACHE["full"]


def render(report: EvalReport, verbose: bool = False) -> str:
    lines = [
        f"cases={report.total} languages={report.languages} categories={report.categories}",
        f"errored={report.errored} failed={report.failed_cases}",
        f"quality_families_measured={sum(1 for v in report.quality.values() if v is not None)}/"
        f"{len(REQUIRED_QUALITY_FAMILIES)} (+ per-language {sorted(report.per_language)})",
    ]
    for family in REQUIRED_QUALITY_FAMILIES:
        n, d = report.quality_counts.get(family, (0, 0))
        lines.append(f"  {family:50s} {report.quality.get(family)!s:6s} {n}/{d}")
    lines.append("model-judgment families (reported honestly, not required perfect):")
    for family, (n, d) in report.model_judgment.items():
        lines.append(f"  {family:50s} {n}/{d}")
    lines.append(f"per_language_contract_accuracy={report.per_language}")
    lines.append(f"gates={len(report.gates)} zero_denominator={report.zero_denominator_gates} "
                 f"violations={ {g: v for g, (v, d) in report.gates.items() if v} }")
    if verbose:
        for g, (v, d) in report.gates.items():
            lines.append(f"  gate {g:60s} {v}/{d}")
    lines.append(f"controls caught={report.controls[0]}/{report.controls[1]} mechanisms={len(report.control_names)}")
    for name, (n, d) in sorted(report.control_names.items()):
        if n != d or d == 0:
            lines.append(f"  control {name}: {n}/{d}")
    lines.append(f"minimums_met={report.minimums_met} gates_zero={report.gates_zero} quality_perfect={report.quality_perfect} "
                 f"controls_caught={report.controls_caught} PASSED={report.passed}")
    for f in report.failures[:40]:
        lines.append(f"FAIL {f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # failure rows carry Arabic data
    results, report = run_all(args.dataset, set(args.case) or None)
    print(render(report, args.verbose))
    for r in results:
        if r.error:
            print(f"ERROR {r.case.case_id}\n{r.error}")
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "phase2j_gold.json").write_text(json.dumps(
        {"total": report.total, "languages": report.languages, "categories": report.categories,
         "quality": report.quality_counts, "model_judgment": report.model_judgment, "gates": report.gates,
         "controls": report.controls, "control_names": report.control_names, "passed": report.passed,
         "failures": report.failures}, indent=2, default=str), encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
