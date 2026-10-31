"""Phase 3A Gold / offline evaluation: dataset integrity, denominators, controls, non-vacuity, determinism."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from src.evals.methodology_review import controls as ctl
from src.evals.methodology_review import gates as gt
from src.evals.methodology_review import metrics as mt
from src.evals.methodology_review import runner
from src.evals.methodology_review.cli import cached_run, render
from src.evals.methodology_review.dataset import DEFAULT_DATASET, MethodGoldCase, load_cases
from src.evals.methodology_review.quality import DETERMINISTIC_FAMILIES, MODEL_JUDGMENT_FAMILIES

ROOT = Path(__file__).resolve().parents[1]
GEN_FILES = sorted((ROOT / "scripts").glob("*phase3a_gold*.py")) + [ROOT / "scripts" / "generate_phase3a_gold.py"]
PROHIBITED = ("src.research.methodology", "src.schemas.methodology_review", "src.graph.methodology_nodes",
              "src.graph.phase3a_graph", "src.evals.methodology_review.world", "src.evals.methodology_review.runner",
              "src.evals.methodology_review.quality", "src.evals.methodology_review.gates",
              "src.evals.methodology_review.controls")


def test_schema_valid_and_minimums():
    cases = load_cases()
    assert all(isinstance(c, MethodGoldCase) for c in cases)
    langs = {k: sum(1 for c in cases if c.language == k) for k in ("en", "ar", "mixed")}
    assert len(cases) >= 450 and all(v >= 150 for v in langs.values())
    assert len({c for case in cases for c in case.categories}) >= 220
    for pt in ("SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT", "HYBRID"):
        assert {c.language for c in cases if c.project_type == pt} == {"en", "ar", "mixed"}


def test_no_exact_duplicate_cases():
    seen = set()
    for c in load_cases():
        key = hashlib.sha256(json.dumps([c.project_type, c.domains, c.gap_variant, c.claim_variant, c.submission, c.script,
                                         c.expected, c.flags, c.mutate, c.twin, c.rerun, c.interrupt_before, c.bounds, c.results_leak, c.no_model], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert key not in seen, c.case_id
        seen.add(key)


def test_generator_imports_no_production_logic():
    for path in GEN_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not name.startswith(PROHIBITED), (path.name, name)


def test_dataset_covers_required_variants():
    text = " ".join(" ".join(c.categories) for c in load_cases())
    for needle in ("overlay.implementation_tool_only", "overlay.unsupported_negative_verdict", "link.DOES_NOT_TEST_TARGET",
                   "doc.conflicting", "doc.partial", "doc.insufficient_source_coverage", "continuity.requirement_absent",
                   "baseline.name_only", "condition.missing", "fail.provider_missing", "replay.idempotent",
                   "immutability.upstream_mutation", "hybrid.unresolved_ownership", "leak.working_prototype",
                   "anchor.repeated_ambiguous", "exec.student_described"):
        assert needle in text, needle


def test_full_offline_run_passes():
    results, report = cached_run()
    assert not report.errored and not report.failed_cases, report.failures[:5]
    assert report.passed
    assert report.measured_quality >= 45
    assert set(report.per_language) == {"en", "ar", "mixed"}
    assert all(report.quality[f] == 1.0 for f in DETERMINISTIC_FAMILIES)
    assert all(report.model_judgment[f][1] > 0 for f in MODEL_JUDGMENT_FAMILIES)


def test_every_gate_has_real_denominator_and_zero_violations():
    _, report = cached_run()
    assert len(report.gates) >= mt.MIN_GATES
    assert not report.zero_denominator_gates
    assert all(v == 0 for v, _ in report.gates.values())


def test_no_denominator_floors_in_eval_code():
    for path in (ROOT / "src" / "evals" / "methodology_review").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"max\(\s*1\s*,", src), path.name
        assert "opportunity_floor" not in src


def test_gate_denominators_are_counted_from_case_facts():
    results, _ = cached_run()
    for name in ("replay_duplicates_model_calls", "result_text_reaches_model_prompt"):
        opps = sum(r.gates[name][1] for r in results if not r.error)
        flagged = sum(1 for r in results if (name.startswith("replay") and r.case.rerun)
                      or (name.startswith("result") and r.case.results_leak))
        assert opps == flagged


def test_negative_controls_minimums_and_intended_reason():
    _, report = cached_run()
    assert report.controls[1] >= mt.MIN_CONTROL_ATTEMPTS and report.controls[0] == report.controls[1]
    assert len(report.control_names) >= mt.MIN_CONTROL_MECHANISMS
    assert not report.control_misses


def _run_cases(match: str, lang: str = "en"):
    out = []
    for case in load_cases():
        if match in case.description and case.language == lang:
            out.append(runner.run_case(case.model_copy(update={"controls": []})))
    assert out
    return out


def _violations(results, gate):
    return sum(r.gates[gate][0] for r in results)


def test_non_vacuity_first_match_protection(monkeypatch):
    import src.research.methodology.verify as verify
    from src.research.novelty.anchoring import Located
    from src.schemas.novelty_differentiation import OccurrenceResolution

    real = verify.locate

    def guessing(text, excerpt, **kw):
        pos = text.find(excerpt)
        return Located(pos, pos + len(excerpt), 1, 1, OccurrenceResolution.UNIQUE_IN_TEXT) \
            if pos >= 0 else real(text, excerpt, **kw)

    monkeypatch.setattr(verify, "locate", guessing)
    results = _run_cases("a_repeated_excerpt_ambiguous_rejected")
    assert _violations(results, "repeated_excerpt_first_match_guessed") > 0


def test_non_vacuity_overlay_negative_guard(monkeypatch):
    import src.research.methodology.overlays as ov

    real = ov._judge

    def lenient(run, overlay, domains, dto, ledger, c_labels, h_labels, targets, signaled):
        dto = dto.model_copy(update={"claims": list(c_labels), "hypotheses": list(h_labels)})  # completeness check disabled
        return real(run, overlay, domains, dto, ledger, c_labels, h_labels, targets, signaled)

    monkeypatch.setattr(ov, "_judge", lenient)
    results = _run_cases("o_ai_negative_omitting_a_bound_target_is_not_accepted")
    assert _violations(results, "unsupported_no_relevance_accepted") > 0


def test_non_vacuity_result_leakage_barrier(monkeypatch):
    import src.research.methodology.pipeline as pl

    original = pl._claim_texts
    monkeypatch.setattr(pl, "_claim_texts", lambda project: {k: v + " " + runner.RESULT_TEXT for k, v in original(project).items()})
    results = _run_cases("r_leak_results_field_cannot_move_posture")
    assert _violations(results, "result_text_reaches_model_prompt") > 0


def test_non_vacuity_posture_enforcement(monkeypatch):
    import src.research.methodology.synthesis as syn
    import src.schemas.methodology_review as mr

    well = mr.MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
    monkeypatch.setattr(mr, "derive_track_posture", lambda **k: well)
    monkeypatch.setattr(syn, "derive_track_posture", lambda **k: well)
    results = _run_cases("e_missing_verification_plan")
    assert _violations(results, "posture_not_derived") > 0


def test_non_vacuity_phase2j_continuity(monkeypatch):
    import src.research.methodology.synthesis as syn
    import src.schemas.methodology_review as mr

    monkeypatch.setattr(mr, "_require_phase_2j_continuity", lambda *a, **k: None)
    monkeypatch.setattr(syn, "_require_phase_2j_continuity", lambda *a, **k: None)
    monkeypatch.setattr(syn, "evaluate_continuity", lambda run, cov, conds, metrics, baselines: (cov, 0))
    results = _run_cases("k_material_condition_not_addressed")
    assert _violations(results, "strong_coverage_with_unaddressed_condition") > 0


def test_gate_and_control_registries_are_distinct_from_quality():
    assert len(set(gt.GATES)) == len(gt.GATES) >= 140
    assert len(ctl.ALL_CONTROLS) >= 60
    assert not set(gt.GATES) & set(DETERMINISTIC_FAMILIES)


def test_deterministic_repeat_run_and_verbose_output():
    case = next(c for c in load_cases() if "e_well" in c.description and c.language == "en")
    a, b = runner.run_case(case), runner.run_case(case)
    assert a.gates == b.gates and dict(a.quality) == dict(b.quality)
    _, report = cached_run()
    assert "gate " in render(report, verbose=True)


def test_no_network_or_external_search():
    results, _ = cached_run()
    assert all(r.ctx.network_attempts == 0 and r.ctx.d["external_search_calls"] == 0 for r in results if not r.error)
    for path in (ROOT / "src" / "research" / "methodology").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "src.research.academic" not in src and "httpx" not in src


def _families():
    fam = {}
    for c in load_cases():
        fam.setdefault(c.semantic_family, []).append(c)
    return fam


def test_semantic_family_is_language_neutral_and_shared_by_translations():
    fam = _families()
    assert "" not in fam
    assert all("[" not in name and not name.endswith(("_en", "_ar", "_mixed")) for name in fam)
    shared = [v for v in fam.values() if len({c.language for c in v}) == 3]
    assert shared and all(len(v) == 3 for v in shared)


def test_normalized_semantic_families_meet_the_category_minimum():
    fam = _families()
    assert len(fam) >= 220
    # renaming a family per language cannot satisfy the minimum: counting families per language-stripped name
    stripped = {re.sub(r"_(en|ar|mixed)$", "", n) for n in fam}
    assert len(stripped) == len(fam)


def test_each_language_has_enough_cases_and_non_translation_cases():
    fam = _families()
    cases = load_cases()
    for lang in ("en", "ar", "mixed"):
        assert sum(1 for c in cases if c.language == lang) >= 150
    for lang in ("ar", "mixed"):
        assert any({c.language for c in v} == {lang} for v in fam.values())
