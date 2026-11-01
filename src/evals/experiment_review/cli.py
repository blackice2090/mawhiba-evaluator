"""Phase 3B offline Gold eval. Deterministic: real upstream graphs, a scripted untrusted model, no network.

    ./.venv/Scripts/python.exe -m src.evals.experiment_review.cli
    ./.venv/Scripts/python.exe -m src.evals.experiment_review.cli --verbose
    ./.venv/Scripts/python.exe -m src.evals.experiment_review.cli --case GE-001 --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from src.evals.experiment_review.controls import ALL_CONTROLS, reset_control_budget
from src.evals.experiment_review.dataset import DEFAULT_DATASET, load_cases
from src.evals.experiment_review.metrics import EvalReport, build_report
from src.evals.experiment_review.quality import DETERMINISTIC_FAMILIES, MODEL_JUDGMENT_FAMILIES
from src.evals.experiment_review.runner import run_case

REPORT_DIR = Path(__file__).resolve().parents[3] / "eval_reports"


def run_all(path: Path = DEFAULT_DATASET, only: set[str] | None = None) -> tuple[list, EvalReport]:
    reset_control_budget()
    cases = [c for c in load_cases(path) if not only or c.case_id in only]
    results = [run_case(c) for c in cases]
    return results, build_report(results)


_CACHE: dict[str, tuple[list, EvalReport]] = {}


def cached_run() -> tuple[list, EvalReport]:
    """The full Gold run, computed once per process (the eval tests share it)."""
    if "full" not in _CACHE:
        _CACHE["full"] = run_all()
    return _CACHE["full"]


def _ratio(n: int, d: int) -> str:
    return "n/a" if not d else f"{n / d:.4f}"


def render(report: EvalReport, verbose: bool = False, results: list | None = None) -> str:
    cases = [r.case for r in results] if results else []
    fam: dict[str, set[str]] = defaultdict(set)
    for c in cases:
        fam[c.semantic_family_id].add(c.language)
    parity = sum(1 for v in fam.values() if len(v) > 1)
    lines = [
        f"cases={report.total} languages={report.languages} raw_categories={report.categories} "
        f"semantic_families={report.semantic_families} (multilingual families={parity}) exact_duplicates={report.duplicates}",
        f"errored={report.errored} failed_cases={report.failed_cases}",
        f"quality_families_measured={report.measured_quality} (deterministic {len(DETERMINISTIC_FAMILIES)} + "
        f"model-judgment {len(MODEL_JUDGMENT_FAMILIES)}) unmeasured={report.unmeasured}",
        "deterministic families (must be exactly 1.0):",
    ]
    for family in DETERMINISTIC_FAMILIES:
        n, d = report.quality_counts.get(family, (0, 0))
        lines.append(f"  {family:50s} {report.quality.get(family)!s:8s} {n}/{d}")
    lines.append("model-judgment families (reported honestly, never forced):")
    for family in MODEL_JUDGMENT_FAMILIES:
        n, d = report.model_judgment.get(family, (0, 0))
        lines.append(f"  {family:50s} {_ratio(n, d):8s} {n}/{d}")
    if report.detail:
        lines.append("result-span detail (per language / repeated / table):")
        for key, (n, d) in sorted(report.detail.items()):
            lines.append(f"  {key:50s} {_ratio(n, d):8s} {n}/{d}")
    lines.append(f"per_language_contract_accuracy={report.per_language}")
    lines.append(f"model_calls={report.model_calls}")
    lines.append(f"release gates={len(report.gates)} zero_denominator={report.zero_denominator_gates} "
                 f"total_violations={sum(v for v, _ in report.gates.values())}")
    lines.append(f"violations={ {g: v for g, (v, d) in report.gates.items() if v} }")
    lines.append(f"thin_gates(<6 real opportunities)={report.thin_gates}")
    if verbose:
        for g, (v, d) in report.gates.items():
            lines.append(f"  gate {g}: violations={v} opportunities={d}")
    lines.append(f"negative controls caught={report.controls[0]}/{report.controls[1]} mechanisms={len(report.control_names)}")
    for name, (n, d) in sorted(report.control_names.items()):
        if verbose or n != d or d == 0:
            lines.append(f"  control {name}: {n}/{d}")
    for name in ALL_CONTROLS:
        if name not in report.control_names:
            lines.append(f"  control {name}: NEVER APPLICABLE")
    for m in report.control_misses[:25]:
        lines.append(f"  CONTROL MISS {m}")
    lines.append(f"minimums_met={report.minimums_met} gates_zero={report.gates_zero} quality_perfect={report.quality_perfect} "
                 f"per_language_perfect={report.per_language_perfect} controls_caught={report.controls_caught} "
                 f"PASSED={report.passed}")
    lines.append("PASS" if report.passed else "FAIL")
    for f in report.failures[:60]:
        lines.append(f"FAIL {f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--verbose", action="store_true", help="print every release gate and every control")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    results, report = run_all(args.dataset, set(args.case) or None)
    print(render(report, args.verbose, results))
    for r in results:
        if r.error:
            print(f"ERROR {r.case.case_id}\n{r.error}")
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "phase3b_gold.json").write_text(json.dumps(
        {"total": report.total, "languages": report.languages, "categories": report.categories,
         "semantic_families": report.semantic_families, "quality": report.quality_counts,
         "model_judgment": report.model_judgment, "detail": report.detail, "gates": report.gates,
         "controls": report.controls, "control_names": report.control_names, "passed": report.passed,
         "model_calls": report.model_calls, "failures": report.failures}, indent=2, default=str), encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
