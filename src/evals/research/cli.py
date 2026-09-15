"""Research planning eval entry point (deterministic, fake provider only).

    python -m src.evals.research.cli
    python -m src.evals.research.cli --report
"""

from __future__ import annotations

import argparse
import json
import sys

from src.evals.baseline import REPORT_ROOT
from src.evals.metrics import MetricCounts
from src.evals.research.dataset import DEFAULT_RESEARCH_DATASET_VERSION, load_research_dataset
from src.evals.research.metrics import violation_rate
from src.evals.research.runner import EVAL_LLM_SETTINGS, evaluate_research_gate, run_research_dataset
from src.research.planner import PLANNER_VERSION
from src.schemas.common import utc_now
from src.schemas.research import RESEARCH_CONTRACT_VERSION


def _rate(counts: MetricCounts) -> str:
    return "not measured" if counts.rate is None else f"{counts.rate:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the research planning evaluation.")
    parser.add_argument("--dataset", default=DEFAULT_RESEARCH_DATASET_VERSION)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    dataset = load_research_dataset(args.dataset)
    metrics, _ = run_research_dataset(dataset)
    gate = evaluate_research_gate(metrics)
    provenance = {
        "dataset_version": dataset.version,
        "planner_prompt_version": PLANNER_VERSION,
        "research_contract_version": RESEARCH_CONTRACT_VERSION,
        "provider": "fake",
        "model": EVAL_LLM_SETTINGS.research_planning_model,
        "mode": "FAKE",
    }

    print(f"Research planning eval (FAKE) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})")
    for name, counts in metrics.quality_metrics.items():
        print(f"  {name}: {counts.matched}/{counts.total} = {_rate(counts)}")
    dup = metrics.duplicate_query_rate
    print(f"  duplicate_query_rate: {dup.violations}/{dup.checked} = {violation_rate(dup)}")
    print("  release-blocking:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print(f"  gate: {gate.summary()}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"research_planning_{stamp}.json"
        path.write_text(
            json.dumps({"provenance": provenance, "metrics": metrics.to_report(),
                        "gate": {"passed": gate.passed, "violations": gate.violations}},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  report: {path}")

    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
