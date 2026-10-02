"""Phase 2J offline Gold eval: dataset minimums, authoring integrity, the full report, and
negative controls that genuinely depend on the mechanism they claim to test."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from src.evals.research_engineering_gap import controls as ctl
from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.cli import cached_run
from src.evals.research_engineering_gap.dataset import DEFAULT_DATASET, load_cases
from src.evals.research_engineering_gap.gates import GATES
from src.evals.research_engineering_gap.metrics import (
    MIN_CATEGORIES, MIN_CONTROL_ATTEMPTS, MIN_CONTROL_MECHANISMS, MIN_PER_LANGUAGE, MIN_QUALITY, MIN_TOTAL,
    REQUIRED_QUALITY_FAMILIES,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run():
    return cached_run()


def test_dataset_meets_the_minimums_without_padding():
    cases = load_cases(DEFAULT_DATASET)
    languages = {lang: sum(1 for x in cases if x.language == lang) for lang in ("en", "ar", "mixed")}
    categories = {cat for x in cases for cat in x.categories}
    assert len(cases) >= MIN_TOTAL and all(n >= MIN_PER_LANGUAGE for n in languages.values())
    assert len(categories) >= MIN_CATEGORIES
    # every case is a distinct opportunity: no two cases share both script and source
    keys = {(x.language, str(x.claims), str(x.cutoff), str(x.patent), str(x.product), str(x.oss), str(x.nd), str(x.script),
             str(x.bounds), x.retract_academic, x.drop_sufficiency, x.mutate, x.no_model, x.twin, x.rerun,
             x.interrupt_before, str(x.truth)) for x in cases}
    assert len(keys) == len(cases)


def test_every_required_semantic_family_is_covered():
    cats = {cat for x in load_cases() for cat in x.categories}
    required = {
        *(f"absence-basis-{b.lower().replace('_', '-')}" for b in c.ABSENCE_BASES),
        *(f"condition-dimension-{d.lower().replace('_', '-')}-required-and-bound" for d in (
            "POPULATION", "ENVIRONMENT", "HARDWARE", "RESOURCE", "SCALE", "GEOGRAPHY", "LANGUAGE",
            "OPERATING_REGIME", "DATASET_DOMAIN")),
        "linkage-partially-addresses-downgrades-to-partial", "linkage-relevant-but-not-addressing-never-supported",
        "linkage-unrelated-never-supported", "linkage-insufficient-evidence-never-supported",
        "differentiation-without-gap-no-eligible-limitation", "differentiation-without-gap-limitation-unlinked",
        "hybrid-same-exact-span-genuinely-dual-propositions", "hybrid-same-span-false-hybrid-model-judgment",
        "proposition-duplicate-relabelled-copy-refused", "hybrid-one-side-materially-linked-only",
        "counterevidence-same-condition-weakens-and-does-not-narrow",
        "counterevidence-different-condition-exposes-unbound-condition",
        "counterevidence-different-condition-with-bound-condition-stays-supported",
        "counterevidence-after-cutoff-different-condition-current-only-narrowing",
        "counterevidence-unknown-condition-weakens-and-stays-visible", "counterevidence-none-no-synthetic-narrowing",
        "counterevidence-review-incomplete-text-bound-cannot-be-supported",
        "independence-two-publications-one-verified-family", "independence-unresolved-patent-family-is-not-corroboration",
        "independence-product-correlation-group-counts-once", "independence-oss-fork-is-not-an-independent-root",
        "independence-oss-mirror-is-not-an-independent-root", "independence-oss-template-derivative-is-not-an-independent-root",
        "academic-phase2e-absent-is-unresolved-independence", "phase2e-absence-is-not-insufficient-input",
        "source-oss-manifest-token-match-is-not-a-limitation", "source-patent-title-only-limitation-blocked",
        "source-retracted-academic-limitation-blocked", "injection-instruction-like-source-text-is-inert-evidence",
        "leak-hidden-prompt-in-provider-refusal-never-persisted", "model-prose-noncanonical-same-typed-facts-same-output",
        "replay-over-a-finished-run-makes-no-model-call", "resume-from-checkpoint-matches-uninterrupted-run",
        "binding-claim-text-edited-after-binding-is-unbound", "binding-upstream-subrun-mutated-downgrades-the-run",
        "chronology-patent-publication-before-cutoff", "chronology-patent-publication-after-cutoff",
        "chronology-patent-publication-date-unknown", "chronology-product-artifact-date-unknown",
        "chronology-oss-release-date-after-cutoff", "numeric-shortfall-missing-number",
        "invented-metric-refused", "capability-missing-cannot-be-supported", "capability-inferred-from-title-refused",
    }
    assert required <= cats, sorted(required - cats)


def test_the_gold_generator_never_calls_phase2j_to_derive_expectations():
    """Expectations are authored from source text and policy: the generator imports no Phase 2J code."""
    forbidden = ("src.research.gap", "src.graph.gap_nodes", "src.graph.phase2j_graph", "src.schemas.gap_assessment",
                 "src.evals.research_engineering_gap")
    for path in sorted((ROOT / "scripts").glob("generate_phase2j_gold*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(f) for m in modules for f in forbidden), (path.name, modules)


def test_the_scorer_re_derives_independently_of_the_phase2j_validators():
    for name in ("context.py", "gates.py", "quality.py"):
        tree = ast.parse((ROOT / "src" / "evals" / "research_engineering_gap" / name).read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not {m for m in modules if m.startswith(("src.research.gap", "src.schemas.gap_assessment"))}, name


def test_there_are_at_least_28_distinct_measured_quality_metrics(run):
    _, report = run
    measured = [f for f in REQUIRED_QUALITY_FAMILIES if report.quality.get(f) is not None]
    assert len(measured) >= MIN_QUALITY and set(measured) == set(REQUIRED_QUALITY_FAMILIES)
    for family in REQUIRED_QUALITY_FAMILIES:
        numerator, denominator = report.quality_counts[family]
        assert denominator > 0 and report.quality[family] == numerator / denominator


def test_the_full_gold_eval_passes(run):
    results, report = run
    assert report.errored == [] and report.failed_cases == [], report.failures[:5]
    assert report.minimums_met and report.quality_perfect and report.per_language_perfect
    assert set(report.per_language) == {"en", "ar", "mixed"}
    assert report.gates_zero and report.controls_caught
    assert report.passed


def test_model_judgment_metrics_are_reported_honestly_not_forced_to_one(run):
    _, report = run
    judged = report.model_judgment
    assert set(judged) == {"semantic_linkage_accuracy", "same_span_proposition_judgment_accuracy",
                           "limitation_semantic_admissibility_accuracy", "counterevidence_recall_accuracy"}
    for family, (numerator, denominator) in judged.items():
        assert denominator > 0, family
    # seeded wrong model judgments exist on purpose, and nothing hard-codes them correct
    assert judged["semantic_linkage_accuracy"][0] < judged["semantic_linkage_accuracy"][1]
    assert judged["same_span_proposition_judgment_accuracy"][0] < judged["same_span_proposition_judgment_accuracy"][1]
    assert judged["counterevidence_recall_accuracy"][0] < judged["counterevidence_recall_accuracy"][1]


def test_negative_controls_meet_the_minimums_and_are_all_caught(run):
    _, report = run
    attempts, caught = report.controls[1], report.controls[0]
    assert attempts >= MIN_CONTROL_ATTEMPTS and caught == attempts
    assert len(report.control_names) >= MIN_CONTROL_MECHANISMS
    assert all(n == d > 0 for n, d in report.control_names.values()), report.control_names


def _ctx(run, category: str):
    results, _ = run
    return next(r.ctx for r in results if category in r.case.categories)


def test_controls_are_not_vacuous_each_depends_on_its_mechanism(run, monkeypatch):
    """Disable the production mechanism a control targets and the control is no longer caught."""
    import src.schemas.gap_assessment as ga

    ctl.reset_control_budget()
    dup = _ctx(run, "limitation-measured-shortfall-supported-chain")
    assert ctl.run_control(dup, "duplicate_proposition_admitted")[0] is True
    ctl.reset_control_budget()
    monkeypatch.setattr(ga, "proposition_key", lambda limitation, refs: (str(limitation.limitation_id), frozenset()))
    assert ctl.run_control(dup, "duplicate_proposition_admitted")[0] is False
    monkeypatch.undo()

    ctl.reset_control_budget()
    partial = _ctx(run, "linkage-partially-addresses-downgrades-to-partial")
    assert ctl.run_control(partial, "partial_linkage_promoted_to_supported")[0] is True
    ctl.reset_control_budget()
    monkeypatch.setattr(ga, "derive_hypothesis_posture", lambda **kw: ga.GapPosture.SUPPORTED_WITHIN_BOUNDS)
    assert ctl.run_control(partial, "partial_linkage_promoted_to_supported")[0] is False
    monkeypatch.undo()

    ctl.reset_control_budget()
    measured = _ctx(run, "limitation-unmet-requirement-supported-chain")
    monkeypatch.setattr(ga, "NUMERIC_LIMITATION_TYPES", frozenset())
    assert ctl.run_control(measured, "numeric_shortfall_verification_disabled")[0] is False
    monkeypatch.undo()
    ctl.reset_control_budget()
    assert ctl.run_control(measured, "numeric_shortfall_verification_disabled")[0] is True
    ctl.reset_control_budget()


def test_a_contract_control_is_caught_for_its_intended_reason_not_any_reason(run):
    ctl.reset_control_budget()
    ctx = _ctx(run, "limitation-measured-shortfall-supported-chain")
    tamper, (kind, pattern) = ctl.CONTROLS["structural_linkage_inferred"]
    d = tamper(copy.deepcopy(ctx.d), ctx)
    # this run's linkage is already FULL, so the tamper is inapplicable here
    assert d is None
    other = _ctx(run, "linkage-unrelated-never-supported")
    d = tamper(copy.deepcopy(other.d), other)
    message = ctl.contract_error(d)
    assert message is not None and "derived in code" in message and kind == "contract"
    ctl.reset_control_budget()


def test_the_eval_uses_no_network(monkeypatch):
    """A single case re-run with every network primitive refusing: scripted fakes only."""
    import socket

    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("network attempted")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    from src.evals.research_engineering_gap.runner import run_case

    ctl.reset_control_budget()
    result = run_case(load_cases()[0])
    assert result.error is None and result.failures == []
    ctl.reset_control_budget()
