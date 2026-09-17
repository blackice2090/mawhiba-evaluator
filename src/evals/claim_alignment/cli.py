"""Claim-evidence alignment eval entry point (deterministic, fake provider only).

    python -m src.evals.claim_alignment.cli
    python -m src.evals.claim_alignment.cli --report

No network, no credentials, no live model. The exit code is the gate:
non-zero when any release-blocking metric is non-zero, any required quality
metric falls below 1.0, or any case errored.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.evals.baseline import REPORT_ROOT
from src.evals.claim_alignment.dataset import (
    DEFAULT_ALIGNMENT_DATASET_VERSION,
    load_alignment_dataset,
)
from src.evals.claim_alignment.metrics import REQUIRED_PERFECT_METRICS
from src.evals.claim_alignment.runner import (
    evaluate_alignment_gate,
    run_alignment_dataset,
    score_by_language,
)
from src.evals.metrics import MetricCounts
from src.llm.prompts import PROMPT_VERSIONS
from src.schemas.claim_alignment import (
    ALIGNMENT_CLASSIFIER_VERSION,
    ALIGNMENT_VERIFIER_VERSION,
    CLAIM_ALIGNMENT_CONTRACT_VERSION,
)
from src.schemas.common import utc_now


def _rate(counts: MetricCounts) -> str:
    return "not measured" if counts.rate is None else f"{counts.rate:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the claim-evidence alignment evaluation."
    )
    parser.add_argument("--dataset", default=DEFAULT_ALIGNMENT_DATASET_VERSION)
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    dataset = load_alignment_dataset(args.dataset)
    metrics, results = run_alignment_dataset(dataset)
    by_language = score_by_language(dataset, results)
    gate = evaluate_alignment_gate(metrics)
    provenance = {
        "dataset_version": dataset.version,
        "claim_alignment_contract_version": CLAIM_ALIGNMENT_CONTRACT_VERSION,
        "classifier_prompt_version": PROMPT_VERSIONS["CLAIM_EVIDENCE_ALIGNMENT_PROMPT"],
        "classifier_version": ALIGNMENT_CLASSIFIER_VERSION,
        "verifier_version": ALIGNMENT_VERIFIER_VERSION,
        "mode": "FAKE",
    }

    print(f"Claim-evidence alignment eval (FAKE) -- dataset {dataset.version}")
    print(f"  provenance: {json.dumps(provenance, sort_keys=True)}")
    print(
        f"  cases evaluated: {metrics.cases_evaluated} (errored {metrics.cases_errored})"
    )
    print(f"  languages: {json.dumps(dataset.language_counts, sort_keys=True)}")
    print(f"  categories: {json.dumps(dataset.category_counts, sort_keys=True)}")
    for name, counts in metrics.quality_metrics.items():
        required = " [required 1.0]" if name in REQUIRED_PERFECT_METRICS else ""
        print(f"  {name}: {counts.matched}/{counts.total} = {_rate(counts)}{required}")
    print("  release-blocking:")
    for name, counts in metrics.safety_metrics.items():
        print(f"    {name}: {counts.violations} violation(s) / {counts.checked} checked")
    per_language_quality = (
        "valid_alignment_reference_accuracy",
        "exact_claim_anchor_accuracy",
        "relationship_taxonomy_contract_accuracy",
        "component_pair_consistency_accuracy",
        "alignment_traceability",
    )
    print("  by language:")
    for language in sorted(by_language):
        subgroup = by_language[language]
        print(f"    {language}: cases={subgroup.cases_evaluated}")
        for name in per_language_quality:
            counts = getattr(subgroup, name)
            print(f"      {name}: {counts.matched}/{counts.total} = {_rate(counts)}")
        print(
            f"      safety_clean={subgroup.safety_clean} "
            f"total_violations={sum(c.violations for c in subgroup.safety_metrics.values())}"
        )
    print(f"  gate: {gate.summary()}")

    if args.report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = REPORT_ROOT / f"claim_evidence_alignment_{stamp}.json"
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
