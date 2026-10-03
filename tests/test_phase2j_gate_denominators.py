"""Phase 2J release-gate denominator integrity.

A gate's denominator is the number of REAL opportunities in the case for THAT invariant,
counted from the case's own facts. It has no floor (no ``max(total, 1)``), a case with no
opportunity adds zero, and neither quality-family overlap nor input order can move it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.evals.research_engineering_gap import context as c
from src.evals.research_engineering_gap.cli import cached_run
from src.evals.research_engineering_gap.gates import GATE_FUNCS, GATES
from src.evals.research_engineering_gap.metrics import MIN_GATES

ROOT = Path(__file__).resolve().parents[1]
EVAL_SOURCES = sorted((ROOT / "src" / "evals" / "research_engineering_gap").glob("*.py"))


@pytest.fixture(scope="module")
def run():
    return cached_run()


def _by_id(results, case_id):
    return next(r for r in results if r.case.case_id == case_id)


def _with_category(results, category):
    return [r for r in results if category in r.case.categories]


def test_there_are_at_least_84_distinct_gates():
    assert len(GATES) == len(set(GATES)) >= MIN_GATES


def test_no_synthetic_denominator_floor_exists_in_the_eval_code():
    pattern = re.compile(r"max\([^)]*,\s*1\)|or 1\b|\+ 1e-|max\(1,")
    for path in EVAL_SOURCES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not pattern.search(line), f"{path.name}:{number}: {line.strip()}"


def test_a_each_real_opportunity_contributes_exactly_once(run):
    results, _ = run
    for result in results:
        d = result.ctx.d
        refs = sum(len(h["evidence_refs"]) for h in d["hypotheses"])
        links = sum(len(h["project_links"]) for h in d["hypotheses"])
        assert result.gates["excerpt_not_source_slice"][1] == refs
        assert result.gates["excerpt_text_hash_mismatch"][1] == refs
        assert result.gates["link_cross_claim_accepted"][1] == links
        assert result.gates["duplicate_hypothesis_accepted"][1] == len(d["hypotheses"])
        assert result.gates["external_search_invoked"] == (0, 1)


def test_b_quality_family_overlap_cannot_change_a_gate_denominator(run):
    results, _ = run
    result = _by_id(results, "GP-001")
    before = {g: GATE_FUNCS[g](result.ctx) for g in GATES}
    for family in list(result.quality):
        result.quality[family][1] += 1000  # inflate every family's opportunity count
    result.ctx.case.categories.append("an-extra-overlapping-category")
    after = {g: GATE_FUNCS[g](result.ctx) for g in GATES}
    result.ctx.case.categories.pop()
    for family in list(result.quality):
        result.quality[family][1] -= 1000
    assert before == after == result.gates


def test_c_input_order_cannot_change_a_gate_denominator(run):
    results, _ = run
    ordered = _with_category(results, "input-order-invariance-and-deterministic-ids")
    assert ordered
    for result in ordered:
        reversed_d = result.ctx.twins["order"]["d"]
        clone = result.ctx.clone(d=reversed_d)
        for name in GATES:
            assert GATE_FUNCS[name](clone)[1] == result.gates[name][1], name


def test_d_a_case_with_no_opportunity_adds_exactly_zero(run):
    results, _ = run
    empties = _with_category(results, "no-provider-is-insufficient-input-never-no-gap")
    assert empties
    for result in empties:
        for name in ("excerpt_not_source_slice", "excerpt_text_hash_mismatch", "link_cross_claim_accepted",
                     "supported_without_capability", "corroboration_misderived"):
            assert result.gates[name] == (0, 0), name
        for name, (violations, opportunities) in result.gates.items():
            assert 0 <= violations <= opportunities or opportunities == 0 == violations, name


def test_e_aggregate_denominators_equal_independently_counted_opportunities(run):
    results, report = run
    assert report.gates["excerpt_not_source_slice"][1] == sum(
        len(h["evidence_refs"]) for r in results for h in r.ctx.d["hypotheses"])
    assert report.gates["link_cross_claim_accepted"][1] == sum(
        len(h["project_links"]) for r in results for h in r.ctx.d["hypotheses"])
    assert report.gates["external_search_invoked"][1] == len(results)
    assert report.gates["duplicate_hypothesis_accepted"][1] == sum(len(r.ctx.d["hypotheses"]) for r in results)
    for basis in c.ABSENCE_BASES:
        scripted = sum(1 for r in results for cid in r.ctx.claims for p in r.ctx.proposals(cid, "limitations")
                       if p.get("type") == basis)
        assert report.gates[f"absence_basis_accepted_{basis.lower()}"][1] == scripted > 0, basis
    assert report.gates["replay_made_a_model_call"][1] == sum(1 for r in results if r.case.rerun)
    assert report.gates["claim_mutation_after_binding_accepted"][1] == sum(1 for r in results if r.case.mutate == "claim_edit")
    assert report.gates["model_prose_changed_canonical_output"][1] == sum(1 for r in results if r.case.twin == "prose")


def test_f_every_required_gate_has_a_real_non_zero_denominator_and_no_violation(run):
    _, report = run
    assert report.zero_denominator_gates == []
    assert {g: v for g, (v, _) in report.gates.items() if v} == {}
    assert report.gates_zero


def test_gate_denominators_are_not_a_function_of_the_quality_report(run):
    """Denominators come from case facts only: re-evaluating after the report exists changes nothing."""
    results, report = run
    for result in results[:25]:
        assert {g: GATE_FUNCS[g](result.ctx) for g in GATES} == result.gates
