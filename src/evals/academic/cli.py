"""Academic retrieval eval entry point (deterministic, fake providers only).

    python -m src.evals.academic.cli
    python -m src.evals.academic.cli --report

No network, no credentials, no API keys. The exit code is the gate: non-zero
when any release-blocking metric is non-zero or any case errored.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.evals.academic.dataset import (
    DEFAULT_ACADEMIC_DATASET_VERSION,
    load_academic_dataset,
)
from src.evals.academic.metrics import violation_rate
from src.evals.academic.runner import (
    evaluate_academic_gate,
    run_academic_dataset,
    score_by_language,
)
from src.evals.baseline import REPORT_ROOT
from src.evals.metrics import MetricCounts
from src.research.academic.capabilities import connector_versions
from src.schemas.academic import (
    ACADEMIC_CONTRACT_VERSION,
    ACADEMIC_DEDUP_VERSION,
    ACADEMIC_NORMALIZER_VERSION,
)
from src.schemas.common import utc_now


def _rate(counts: MetricCounts) -> str:
    return "not measured" if counts.rate is None else f"{counts.rate:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the academic retrieval evaluation."
    )
    parser.add_argument("--dataset", default=DEFAULT_ACADEMIC_DATASET_VERSION)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    dataset = load_academic_dataset(args.dataset)
    metrics, results = run_academic_dataset(dataset)
    by_language = score_by_language(dataset, results)
    gate = evaluate_academic_gate(metrics)
    provenance = {
        "dataset_version": dataset.version,
        "academic_contract_version": ACADEMIC_CONTRACT_VERSION,
        "normalizer_version": ACADEMIC_NORMALIZER_VERSION,
        "dedup_version": ACADEMIC_DEDUP_VERSION,
        "connector_versions": connector_versions(),
        "mode": "FAKE",
    }

    print(f"Academic retrieval eval (FAKE) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})")
    print(f"  languages: {json.dumps(dataset.language_counts, sort_keys=True)}")
    for name, counts in metrics.quality_metrics.items():
        print(f"  {name}: {counts.matched}/{counts.total} = {_rate(counts)}")
    print("  release-blocking:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print("  by language:")
    for language in sorted(by_language):
        subgroup = by_language[language]
        dedup = subgroup.cross_provider_dedup_accuracy
        print(
            f"    {language}: cases={subgroup.cases_evaluated} "
            f"dedup={dedup.matched}/{dedup.total} = {_rate(dedup)}"
        )
        for name, counts in subgroup.safety_metrics.items():
            print(f"      {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print(f"  gate: {gate.summary()}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"academic_retrieval_{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "provenance": provenance,
                    "metrics": metrics.to_report(),
                    "by_language": {k: v.to_report() for k, v in by_language.items()},
                    "gate": {"passed": gate.passed, "violations": gate.violations},
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
