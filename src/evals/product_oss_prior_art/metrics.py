"""Phase 2H metrics: quality families, per-language accuracy and safety gates.

A metric with no denominator is reported as ``None`` ("not measured"), never as
1.0. Every required quality family must be exactly 1.0 and every
release-blocking gate exactly zero, each with a non-zero denominator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.evals.product_oss_prior_art.runner import GATES, CaseResult

REQUIRED_QUALITY_FAMILIES: tuple[str, ...] = (
    "query_provenance", "multilingual_query_plan", "pii_minimization", "observation_artifact_separation",
    "safe_fetch", "product_identity", "weak_identity_non_collapse", "listing_anti_inflation",
    "product_chronology", "repository_identity", "code_hit_dedupe", "fork_network_grouping",
    "fork_preservation", "oss_chronology", "snapshot_provenance", "provider_capability_error",
    "bounded_status", "idempotency", "candidate_traceability", "legal_novelty_boundary",
    "source_role", "license_metadata", "immutability",
)

MIN_TOTAL = 160
MIN_ARABIC = 32
MIN_MIXED = 24
MIN_CATEGORIES = 78


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
    failures: list[dict[str, Any]] = field(default_factory=list)

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
    def passed(self) -> bool:
        return (
            not self.errored
            and not self.failed_cases
            and self.minimums_met
            and self.gates_zero
            and self.quality_perfect
            and self.controls[0] == self.controls[1] > 0
        )


def build_report(results: list[CaseResult]) -> EvalReport:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    language_cases: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    gates = {g: [0, 0] for g in GATES}
    controls = [0, 0]
    failures: list[dict[str, Any]] = []
    for result in results:
        for family, key, ok, expected, actual in result.checks:
            counts[family][0] += int(ok)
            counts[family][1] += 1
            if not ok:
                failures.append({"case": result.case.case_id, "key": key, "expected": expected, "actual": actual})
        for gate, (num, den) in result.gates.items():
            gates[gate][0] += num
            gates[gate][1] += den
        for name, rejected in result.controls:
            controls[0] += int(rejected)
            controls[1] += 1
        language_cases[result.case.language][0] += int(result.passed)
        language_cases[result.case.language][1] += 1
    return EvalReport(
        total=len(results),
        languages=dict(Counter(r.case.language for r in results)),
        categories=len({c for r in results for c in r.case.categories}),
        errored=[r.case.case_id for r in results if r.error],
        failed_cases=[r.case.case_id for r in results if not r.passed and not r.error],
        quality={f: (counts[f][0] / counts[f][1] if counts[f][1] else None) for f in sorted(set(counts) | set(REQUIRED_QUALITY_FAMILIES))},
        quality_counts={f: (counts[f][0], counts[f][1]) for f in counts},
        per_language={lang: (v[0] / v[1] if v[1] else None) for lang, v in language_cases.items()},
        gates={g: (v[0], v[1]) for g, v in gates.items()},
        controls=(controls[0], controls[1]),
        failures=failures,
    )


__all__ = ["MIN_ARABIC", "MIN_CATEGORIES", "MIN_MIXED", "MIN_TOTAL", "REQUIRED_QUALITY_FAMILIES", "EvalReport", "build_report"]
