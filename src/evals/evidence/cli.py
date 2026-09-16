"""Evidence extraction eval entry point (deterministic, fake provider only).

    python -m src.evals.evidence.cli
    python -m src.evals.evidence.cli --report

No network, no credentials, no live model. The exit code is the gate: non-zero
when any release-blocking metric is non-zero, any required quality metric falls
below 1.0, or any case errored.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.evals.baseline import REPORT_ROOT
from src.evals.evidence.dataset import (
    DEFAULT_EVIDENCE_DATASET_VERSION,
    load_evidence_dataset,
)
from src.evals.evidence.metrics import REQUIRED_PERFECT_METRICS, violation_rate
from src.evals.evidence.runner import (
    evaluate_evidence_gate,
    run_evidence_dataset,
    score_by_language,
)
from src.evals.metrics import MetricCounts
from src.llm.prompts import PROMPT_VERSIONS
from src.schemas.common import utc_now
from src.schemas.evidence_extraction import (
    CONTENT_SNAPSHOT_VERSION,
    EVIDENCE_CHUNKER_VERSION,
    EVIDENCE_EXTRACTION_CONTRACT_VERSION,
    EVIDENCE_EXTRACTOR_VERSION,
    EVIDENCE_VERIFIER_VERSION,
)


def _rate(counts: MetricCounts) -> str:
    return "not measured" if counts.rate is None else f"{counts.rate:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the evidence extraction evaluation."
    )
    parser.add_argument("--dataset", default=DEFAULT_EVIDENCE_DATASET_VERSION)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    dataset = load_evidence_dataset(args.dataset)
    metrics, results = run_evidence_dataset(dataset)
    by_language = score_by_language(dataset, results)
    gate = evaluate_evidence_gate(metrics)
    provenance = {
        "dataset_version": dataset.version,
        "evidence_extraction_contract_version": EVIDENCE_EXTRACTION_CONTRACT_VERSION,
        "content_snapshot_version": CONTENT_SNAPSHOT_VERSION,
        "extractor_prompt_version": PROMPT_VERSIONS["EVIDENCE_EXTRACTOR_PROMPT"],
        "extractor_version": EVIDENCE_EXTRACTOR_VERSION,
        "verifier_version": EVIDENCE_VERIFIER_VERSION,
        "chunker_version": EVIDENCE_CHUNKER_VERSION,
        "mode": "FAKE",
    }

    print(f"Evidence extraction eval (FAKE) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(
        f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})"
    )
    print(f"  languages: {json.dumps(dataset.language_counts, sort_keys=True)}")
    for name, counts in metrics.quality_metrics.items():
        required = " [required 1.0]" if name in REQUIRED_PERFECT_METRICS else ""
        print(f"  {name}: {counts.matched}/{counts.total} = {_rate(counts)}{required}")
    print("  release-blocking:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    print("  by language:")
    for language in sorted(by_language):
        subgroup = by_language[language]
        span = subgroup.span_resolution_accuracy
        print(
            f"    {language}: cases={subgroup.cases_evaluated} "
            f"span={span.matched}/{span.total} = {_rate(span)}"
        )
        for name, counts in subgroup.safety_metrics.items():
            if counts.violations:
                print(f"      {name}: {counts.violations} violation(s)")
    print(f"  gate: {gate.summary()}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"evidence_extraction_{stamp}.json"
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
