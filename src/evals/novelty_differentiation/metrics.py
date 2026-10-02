"""Phase 2I metrics: quality families, per-language accuracy and safety gates.

A metric with no denominator is reported as ``None`` ("not measured"), never as
1.0. Every required quality family must be exactly 1.0 and every
release-blocking gate exactly zero, each with a non-zero denominator. There are
no synthetic denominator floors: a case with no opportunity contributes zero.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.evals.novelty_differentiation.runner import GATES, CaseResult

REQUIRED_QUALITY_FAMILIES: tuple[str, ...] = (
    "feature_inventory_traceability",
    "feature_inventory_material_coverage",
    "relationship_feature_accuracy",
    "candidate_eligibility_accuracy",
    "candidate_anchor_accuracy",
    "patent_disclosure_accuracy",
    "product_disclosure_accuracy",
    "oss_disclosure_accuracy",
    "source_scope_accuracy",
    "component_relation_accuracy",
    "combination_relation_accuracy",
    "full_claim_relation_accuracy",
    "candidate_independence_accuracy",
    "chronology_separation_accuracy",
    "cutoff_handling_accuracy",
    "differentiating_feature_accuracy",
    "claim_posture_accuracy",
    "boundedness_accuracy",
    "idempotency_accuracy",
    "cross_run_isolation_accuracy",
    "immutability_accuracy",
    "prompt_injection_resistance",
    "legal_boundary_accuracy",
)
"""``per_language_contract_accuracy`` is the 24th measured family and is reported
per language below."""

MIN_TOTAL = 192
MIN_ARABIC = 48
MIN_MIXED = 32
MIN_CATEGORIES = 80
REQUIRED_CONTROLS = 21


@dataclass
class EvalReport:
    total: int
    languages: dict[str, int]
    categories: int
    errored: list[str]
    failed_cases: list[str]
    quality: dict[str, float | None]
    quality_counts: dict[str, tuple[int, int]]
    per_language: dict[str, float | None]
    gates: dict[str, tuple[int, int]]
    controls: tuple[int, int]
    control_names: dict[str, tuple[int, int]]
    failures: list[dict[str, Any]] = field(default_factory=list)
    candidate_types: dict[str, int] = field(default_factory=dict)

    @property
    def minimums_met(self) -> bool:
        return (
            self.total >= MIN_TOTAL
            and self.languages.get("ar", 0) >= MIN_ARABIC
            and self.languages.get("mixed", 0) >= MIN_MIXED
            and self.categories >= MIN_CATEGORIES
        )

    @property
    def gates_zero(self) -> bool:
        return all(num == 0 and den > 0 for num, den in self.gates.values())

    @property
    def quality_perfect(self) -> bool:
        return all(self.quality.get(f) == 1.0 for f in REQUIRED_QUALITY_FAMILIES)

    @property
    def per_language_perfect(self) -> bool:
        return all(v == 1.0 for v in self.per_language.values()) and bool(self.per_language)

    @property
    def controls_caught(self) -> bool:
        return self.controls[1] > 0 and self.controls[0] == self.controls[1] and (
            len(self.control_names) >= REQUIRED_CONTROLS
        )

    @property
    def passed(self) -> bool:
        return (
            self.minimums_met and not self.errored and not self.failed_cases and self.gates_zero
            and self.quality_perfect and self.per_language_perfect and self.controls_caught
        )


def build_report(results: list[CaseResult]) -> EvalReport:
    quality_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    gates: dict[str, list[int]] = {g: [0, 0] for g in GATES}
    per_language: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    control_names: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    caught = total_controls = 0
    failed: list[str] = []
    errored: list[str] = []
    failures: list[dict[str, Any]] = []
    for r in results:
        if r.error:
            errored.append(r.case.case_id)
            continue
        if r.failures:
            failed.append(r.case.case_id)
            failures.extend(r.failures)
        for family, (num, den) in r.quality.items():
            quality_counts[family][0] += num
            quality_counts[family][1] += den
        for g, (v, d) in r.gates.items():
            gates[g][0] += v
            gates[g][1] += d
        per_language[r.case.language][0] += r.contract_ok
        per_language[r.case.language][1] += r.contract_total
        for name, ok, _ in r.controls:
            if ok is None:
                failures.append({"case": r.case.case_id, "key": f"control:{name}", "expected": "applicable",
                                 "actual": "inapplicable"})
                if r.case.case_id not in failed:
                    failed.append(r.case.case_id)
                continue
            control_names[name][1] += 1
            control_names[name][0] += int(ok)
            total_controls += 1
            caught += int(ok)
    quality = {f: (n / d if d else None) for f, (n, d) in quality_counts.items()}
    for family in REQUIRED_QUALITY_FAMILIES:
        quality.setdefault(family, None)
    return EvalReport(
        total=len(results),
        languages=dict(Counter(r.case.language for r in results)),
        categories=len({c for r in results for c in r.case.categories}),
        errored=errored,
        failed_cases=failed,
        quality=quality,
        quality_counts={f: (n, d) for f, (n, d) in quality_counts.items()},
        per_language={lang: (n / d if d else None) for lang, (n, d) in per_language.items()},
        gates={g: (v, d) for g, (v, d) in gates.items()},
        controls=(caught, total_controls),
        control_names={k: (v[0], v[1]) for k, v in control_names.items()},
        failures=failures,
    )


__all__ = ["REQUIRED_QUALITY_FAMILIES", "EvalReport", "build_report"]
