"""Phase 3B Gold metrics: quality families, per-language accuracy, release gates, controls.

A metric with no denominator is ``None`` ("not measured"), never 1.0. Deterministic quality families must be exactly
1.0; the MODEL-JUDGMENT families are reported honestly and are not required to be perfect. Every release gate must be
zero with a non-zero denominator; there are no synthetic denominator floors."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.evals.experiment_review.gates import GATES
from src.evals.experiment_review.quality import DETERMINISTIC_FAMILIES, MODEL_JUDGMENT_FAMILIES
from src.evals.experiment_review.runner import CaseResult

MIN_TOTAL = 450
MIN_PER_LANGUAGE = 150
MIN_FAMILIES = 220
MIN_QUALITY = 45
MIN_GATES = 150
MIN_CONTROL_ATTEMPTS = 300
MIN_CONTROL_MECHANISMS = 70
THIN = 6


@dataclass
class EvalReport:
    total: int
    languages: dict[str, int]
    categories: int
    semantic_families: int
    duplicates: int
    errored: list[str]
    failed_cases: list[str]
    quality: dict[str, float | None]
    quality_counts: dict[str, tuple[int, int]]
    model_judgment: dict[str, tuple[int, int]]
    per_language: dict[str, float | None]
    gates: dict[str, tuple[int, int]]
    controls: tuple[int, int]
    control_names: dict[str, tuple[int, int]]
    model_calls: dict[str, int] = field(default_factory=dict)
    detail: dict[str, tuple[int, int]] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    control_misses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def minimums_met(self) -> bool:
        return (self.total >= MIN_TOTAL and all(self.languages.get(k, 0) >= MIN_PER_LANGUAGE for k in ("en", "ar", "mixed"))
                and self.semantic_families >= MIN_FAMILIES and self.duplicates == 0)

    @property
    def measured_quality(self) -> int:
        return (sum(1 for f in DETERMINISTIC_FAMILIES if self.quality.get(f) is not None)
                + sum(1 for f in MODEL_JUDGMENT_FAMILIES if self.model_judgment.get(f, (0, 0))[1] > 0))

    @property
    def unmeasured(self) -> list[str]:
        return ([f for f in DETERMINISTIC_FAMILIES if self.quality.get(f) is None]
                + [f for f in MODEL_JUDGMENT_FAMILIES if self.model_judgment.get(f, (0, 0))[1] == 0])

    @property
    def gates_zero(self) -> bool:
        return all(v == 0 and d > 0 for v, d in self.gates.values()) and len(self.gates) >= MIN_GATES

    @property
    def zero_denominator_gates(self) -> list[str]:
        return [g for g, (_, d) in self.gates.items() if d == 0]

    @property
    def thin_gates(self) -> list[tuple[str, int]]:
        return sorted(((g, d) for g, (_, d) in self.gates.items() if 0 < d < THIN), key=lambda x: (x[1], x[0]))

    @property
    def quality_perfect(self) -> bool:
        return all(self.quality.get(f) == 1.0 for f in DETERMINISTIC_FAMILIES)

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
                and self.quality_perfect and self.per_language_perfect and self.controls_caught
                and not self.unmeasured and self.measured_quality >= MIN_QUALITY)


def build_report(results: list[CaseResult]) -> EvalReport:
    quality: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    gates: dict[str, list[int]] = {g: [0, 0] for g in GATES}
    per_language: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    control_names: dict[str, list[int]] = {}
    model_calls: Counter = Counter()
    caught = total_controls = 0
    failed: list[str] = []
    errored: list[str] = []
    failures: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
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
        model_calls.update(r.model_calls)
        for name, ok, how in r.controls:
            if ok is None:
                continue
            slot = control_names.setdefault(name, [0, 0])
            slot[1] += 1
            slot[0] += int(ok)
            total_controls += 1
            caught += int(ok)
            if not ok:
                misses.append({"case": r.case.case_id, "mechanism": name, "result": how})
    keys = [(c.language, c.semantic_family_id) for c in (r.case for r in results)]
    family_ids = {k[1] for k in keys}
    import json

    seen: set[str] = set()
    dup = 0
    for r in results:
        body = json.dumps({k: v for k, v in r.case.model_dump().items() if k != "case_id"}, sort_keys=True, ensure_ascii=False)
        dup += int(body in seen)
        seen.add(body)
    detail = {f: (n, d) for f, (n, d) in quality.items() if "@" in f or "#" in f}
    for f in detail:
        quality.pop(f)
    deterministic = {f: (n / d if d else None) for f, (n, d) in quality.items() if f not in MODEL_JUDGMENT_FAMILIES}
    for family in DETERMINISTIC_FAMILIES:
        deterministic.setdefault(family, None)
    return EvalReport(
        total=len(results), languages=dict(Counter(r.case.language for r in results)),
        categories=len({r.case.category for r in results}), semantic_families=len(family_ids), duplicates=dup,
        errored=errored, failed_cases=failed, quality=deterministic,
        quality_counts={f: (n, d) for f, (n, d) in quality.items() if f not in MODEL_JUDGMENT_FAMILIES},
        model_judgment={f: (quality[f][0], quality[f][1]) for f in MODEL_JUDGMENT_FAMILIES if f in quality},
        per_language={lang: (n / d if d else None) for lang, (n, d) in per_language.items()},
        gates={g: (v, d) for g, (v, d) in gates.items()}, controls=(caught, total_controls),
        control_names={k: (v[0], v[1]) for k, v in control_names.items()}, model_calls=dict(model_calls),
        detail=detail, failures=failures, control_misses=misses,
    )


__all__ = ["EvalReport", "build_report"]
