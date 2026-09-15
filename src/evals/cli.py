"""Intake eval entry point.

    python -m src.evals.cli                 # deterministic fake-provider run
    python -m src.evals.cli --live          # requires RUN_OPENAI_INTAKE_EVALS=1
    python -m src.evals.cli --approve-baseline

Live mode never runs implicitly. An API key being present is deliberately not
enough: a developer with a key in their environment must not incur cost by
running the eval.
"""

from __future__ import annotations

import argparse
import os
import sys

from src.config.settings import LLMSettings
from src.evals.baseline import (
    EvalBaseline,
    RunProvenance,
    evaluate_gate,
    load_baseline,
    write_baseline,
    write_report,
)
from src.evals.dataset import DEFAULT_DATASET_VERSION, load_gold_dataset
from src.evals.runner import run_dataset

LIVE_FLAG = "RUN_OPENAI_INTAKE_EVALS"
MAX_CASES_VAR = "OPENAI_EVAL_MAX_CASES"
MODEL_VAR = "OPENAI_EVAL_MODEL"
DEFAULT_LIVE_CASE_CAP = 10
"""Live runs default to a small capped subset. A full live sweep is opt-in."""


def live_enabled() -> bool:
    return os.getenv(LIVE_FLAG) == "1"


def _live_settings() -> LLMSettings:
    """Settings for a live run.

    Escalation is off by default so a low-confidence classification cannot
    silently reach the more expensive model during an eval sweep.
    """
    model = os.getenv(MODEL_VAR)
    overrides: dict[str, object] = {"escalation_enabled": False, "max_retries": 1}
    if model:
        overrides["extraction_model"] = model
        overrides["classification_model"] = model
    return LLMSettings(**overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the intake trust evaluation.")
    parser.add_argument("--live", action="store_true", help="use the real OpenAI provider")
    parser.add_argument("--dataset", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument(
        "--approve-baseline",
        action="store_true",
        help="overwrite the approved baseline with this run (explicit action)",
    )
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    if args.live and not live_enabled():
        print(f"Live intake eval: NOT RUN (set {LIVE_FLAG}=1 to enable)")
        return 0

    dataset = load_gold_dataset(args.dataset)
    settings = _live_settings() if args.live else LLMSettings(
        escalation_enabled=False, max_retries=0
    )

    max_cases = args.max_cases
    if args.live and max_cases is None:
        max_cases = int(os.getenv(MAX_CASES_VAR, str(DEFAULT_LIVE_CASE_CAP)))

    metrics, _ = run_dataset(
        dataset, settings=settings, live=args.live, max_cases=max_cases
    )

    provenance = RunProvenance(
        dataset_version=dataset.version,
        provider="openai_responses" if args.live else "fake",
        model=settings.extraction_model if args.live else "fake",
        mode="LIVE" if args.live else "FAKE",
    )
    gate = evaluate_gate(metrics, load_baseline(args.dataset))

    print(f"Intake eval ({provenance.mode}) -- dataset {dataset.version}")
    print(f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})")
    for name, counts in metrics.quality_metrics.items():
        if counts.rate is not None:
            print(f"  {name}: {counts.matched}/{counts.total} = {counts.rate:.3f}")
    print("  safety:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print(f"  gate: {gate.summary()}")

    if args.report or args.live:
        print(f"  report: {write_report(metrics, provenance, gate)}")

    if args.approve_baseline:
        baseline = EvalBaseline.from_metrics(
            metrics, provenance, note="approved via --approve-baseline"
        )
        print(f"  baseline updated: {write_baseline(baseline, args.dataset, approve=True)}")

    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
