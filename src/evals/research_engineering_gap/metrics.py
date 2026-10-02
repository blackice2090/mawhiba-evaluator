"""Phase 2J metrics: quality families, per-language accuracy and release gates.

A metric with no denominator is ``None`` ("not measured"), never 1.0. Deterministic
quality families must be exactly 1.0; the MODEL-JUDGMENT families are reported
honestly and are not required to be perfect (a structurally valid but semantically
wrong model judgment is in the dataset on purpose). Every release gate must be zero
with a non-zero denominator; there are no synthetic denominator floors."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.evals.research_engineering_gap.gates import GATES
from src.evals.research_engineering_gap.quality import MODEL_JUDGMENT_FAMILIES
from src.evals.research_engineering_gap.runner import CaseResult

REQUIRED_QUALITY_FAMILIES: tuple[str, ...] = (
    "existing_capability_accuracy", "limitation_admissibility_accuracy", "limitation_anchor_accuracy",
    "limitation_type_accuracy", "source_quality_handling_accuracy", "absence_rejection_accuracy",
    "gap_existence_accuracy", "research_gap_kind_accuracy", "engineering_gap_kind_accuracy", "hybrid_gap_accuracy",
    "unresolved_gap_kind_accuracy", "proposition_distinctness_accuracy", "project_link_binding_accuracy",
    "linkage_level_accuracy", "condition_materiality_accuracy", "condition_binding_accuracy",
    "validation_requirement_accuracy", "metric_noninvention_accuracy", "academic_independence_accuracy",
    "patent_independence_accuracy", "product_independence_accuracy", "oss_independence_accuracy",
    "corroboration_accuracy", "scope_accuracy", "counterevidence_detection_accuracy",
    "counterevidence_coverage_accuracy", "counterevidence_condition_relation_accuracy",
    "counterevidence_scope_effect_accuracy", "chronology_separation_accuracy",
    "historical_publicity_boundary_accuracy", "legal_boundary_accuracy", "hypothesis_posture_accuracy",
    "claim_posture_accuracy", "bounded_statement_accuracy", "differentiation_not_gap_accuracy",
    "localization_not_gap_accuracy", "boundedness_accuracy", "prompt_injection_resistance",
    "model_prose_noncanonicality", "no_new_search_accuracy", "upstream_immutability_accuracy",
    "replay_idempotency_accuracy", "cross_run_isolation_accuracy", "input_order_invariance_accuracy",
    "issue_reporting_accuracy",
)
"""``per_language_contract_accuracy`` is the final family, reported per language below."""

MIN_TOTAL = 240
MIN_PER_LANGUAGE = 80
MIN_CATEGORIES = 100
MIN_QUALITY = 28
MIN_GATES = 84
MIN_CONTROL_ATTEMPTS = 120
MIN_CONTROL_MECHANISMS = 32


@dataclass
class EvalReport:
    total: int
    languages: dict[str, int]
    categories: int
    errored: list[str]
    failed_cases: list[str]
    quality: dict[str, float | None]
    quality_counts: dict[str, tuple[int, int]]
    model_judgment: dict[str, tuple[int, int]]
    per_language: dict[str, float | None]
    gates: dict[str, tuple[int, int]]
    controls: tuple[int, int]
    control_names: dict[str, tuple[int, int]]
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def minimums_met(self) -> bool:
        return (self.total >= MIN_TOTAL and all(self.languages.get(k, 0) >= MIN_PER_LANGUAGE for k in ("en", "ar", "mixed"))
                and self.categories >= MIN_CATEGORIES)

    @property
    def measured_quality(self) -> int:
        return sum(1 for v in self.quality.values() if v is not None) + len(self.per_language and ["x"] or [])

    @property
    def gates_zero(self) -> bool:
        return all(v == 0 and d > 0 for v, d in self.gates.values()) and len(self.gates) >= MIN_GATES

    @property
    def zero_denominator_gates(self) -> list[str]:
        return [g for g, (_, d) in self.gates.items() if d == 0]

    @property
    def quality_perfect(self) -> bool:
        return all(self.quality.get(f) == 1.0 for f in REQUIRED_QUALITY_FAMILIES)

    @property
    def per_language_perfect(self) -> bool:
        return bool(self.per_language) and all(v == 1.0 for v in self.per_language.values())

    @property
    def controls_caught(self) -> bool:
        return (self.controls[1] >= MIN_CONTROL_ATTEMPTS and self.controls[0] == self.controls[1]
                and len(self.control_names) >= MIN_CONTROL_MECHANISMS
                and all(n[0] == n[1] and n[1] > 0 for n in self.control_names.values()))

    @property
    def passed(self) -> bool:
        return (self.minimums_met and not self.errored and not self.failed_cases and self.gates_zero
                and self.quality_perfect and self.per_language_perfect and self.controls_caught)


def build_report(results: list[CaseResult], mechanisms: tuple[str, ...] = ()) -> EvalReport:
    quality: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    gates: dict[str, list[int]] = {g: [0, 0] for g in GATES}
    per_language: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    control_names: dict[str, list[int]] = {m: [0, 0] for m in mechanisms}
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
            quality[family][0] += num
            quality[family][1] += den
        for g, (v, d) in r.gates.items():
            gates[g][0] += v
            gates[g][1] += d
        per_language[r.case.language][0] += r.contract_ok
        per_language[r.case.language][1] += r.contract_total
        for name, ok, how in r.controls:
            if ok is None:
                continue
            slot = control_names.setdefault(name, [0, 0])
            slot[1] += 1
            slot[0] += int(ok)
            total_controls += 1
            caught += int(ok)
            if not ok:
                failures.append({"case": r.case.case_id, "key": f"control:{name}", "expected": "caught", "actual": how})
    required = {f: (n / d if d else None) for f, (n, d) in quality.items() if f not in MODEL_JUDGMENT_FAMILIES}
    for family in REQUIRED_QUALITY_FAMILIES:
        required.setdefault(family, None)
    return EvalReport(
        total=len(results),
        languages=dict(Counter(r.case.language for r in results)),
        categories=len({c for r in results for c in r.case.categories}),
        errored=errored, failed_cases=failed,
        quality=required,
        quality_counts={f: (n, d) for f, (n, d) in quality.items() if f not in MODEL_JUDGMENT_FAMILIES},
        model_judgment={f: (quality[f][0], quality[f][1]) for f in MODEL_JUDGMENT_FAMILIES if f in quality},
        per_language={lang: (n / d if d else None) for lang, (n, d) in per_language.items()},
        gates={g: (v, d) for g, (v, d) in gates.items()},
        controls=(caught, total_controls),
        control_names={k: (v[0], v[1]) for k, v in control_names.items()},
        failures=failures,
    )


__all__ = ["REQUIRED_QUALITY_FAMILIES", "EvalReport", "build_report"]
