"""Phase 3B Gold / offline evaluation: dataset integrity, authoring independence, metrics, gates, controls and
permanent non-vacuity checks. Offline: real upstream graphs, a scripted untrusted model, no network."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from src.evals.experiment_review import controls as ctl
from src.evals.experiment_review import gates as gt
from src.evals.experiment_review import metrics as mt
from src.evals.experiment_review import runner
from src.evals.experiment_review.cli import cached_run, render
from src.evals.experiment_review.dataset import DEFAULT_DATASET, ExperimentGoldCase, load_cases
from src.evals.experiment_review.quality import DETERMINISTIC_FAMILIES, MODEL_JUDGMENT_FAMILIES

ROOT = Path(__file__).resolve().parents[1]
GOLD_PKG = ROOT / "src" / "evals" / "experiment_review"
GEN_FILES = sorted((ROOT / "scripts").glob("phase3b_gold_*.py")) + [ROOT / "scripts" / "generate_phase3b_gold.py"]
# every Gold module except the approved execution adapter must stay free of production semantics
SCORING_FILES = [p for p in GOLD_PKG.glob("*.py") if p.name != "adapter.py"]
PRODUCTION = ("src.research.experiments", "src.schemas.experiment_review", "src.graph.experiment_nodes",
              "src.graph.phase3b_graph")
RUNNERS = ("src.evals.experiment_review.adapter", "src.evals.experiment_review.runner",
           "src.evals.experiment_review.quality", "src.evals.experiment_review.gates",
           "src.evals.experiment_review.controls", "src.evals.experiment_review.context")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


# -- dataset ---------------------------------------------------------------------------------------------------


def test_schema_valid_and_minimums():
    cases = load_cases()
    assert all(isinstance(c, ExperimentGoldCase) for c in cases)
    langs = {k: sum(1 for c in cases if c.language == k) for k in ("en", "ar", "mixed")}
    assert len(cases) >= 450 and all(v >= 150 for v in langs.values()), langs
    for pt in ("SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT", "HYBRID"):
        assert {c.language for c in cases if c.project_type == pt} == {"en", "ar", "mixed"}


def test_normalized_semantic_families_meet_the_minimum_and_are_language_neutral():
    cases = load_cases()
    fam: dict[str, set[str]] = {}
    for c in cases:
        fam.setdefault(c.semantic_family_id, set()).add(c.language)
    assert len(fam) >= 220
    assert all(not name.endswith(("_en", "_ar", "_mixed")) and "[" not in name for name in fam)
    assert sum(1 for v in fam.values() if len(v) == 3) >= 150  # translations share one family
    # renaming a family per language cannot satisfy the minimum
    assert len({re.sub(r"[_.](en|ar|mixed)$", "", n) for n in fam}) == len(fam)
    for lang in ("ar", "mixed"):
        assert any(v == {lang} or v == {"ar", "mixed"} for v in fam.values())  # not only literal translations


def test_no_exact_duplicate_cases():
    seen = set()
    for c in load_cases():
        body = c.model_dump()
        body.pop("case_id")
        key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert key not in seen, c.case_id
        seen.add(key)


def test_generator_is_deterministic_and_matches_the_committed_dataset():
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_phase3b_gold as gen

    first, second = gen.render(gen.build_cases()), gen.render(gen.build_cases())
    assert first == second
    assert first.encode("utf-8") == DEFAULT_DATASET.read_bytes().replace(b"\r\n", b"\n")


def test_every_case_has_authored_expectations_and_truth_free_of_model_output_markers():
    for c in load_cases():
        assert c.expected, c.case_id
        assert "chain_of_thought" not in json.dumps(c.model_dump()).lower()


def test_dataset_covers_the_required_scenario_families():
    ids = " ".join(c.semantic_family_id for c in load_cases())
    for needle in ("seg.one_experiment", "seg.no_experiment", "seg.same_protocol_repeated", "seg.changed_protocol",
                   "seg.repeated_defining", "type.well.AI_ML", "type.well.SOFTWARE", "applic.stat_test",
                   "missing.AI_ML_MODEL_EVALUATION.TRAIN_TEST_SEPARATION", "link.directly_tests_without_measurement",
                   "link.foreign_target_id", "link.cross_run_target_id", "cont.mosaic_three", "cont.metric_anchored",
                   "baseline.name_only", "baseline.difference.SAME_HARDWARE", "baseline.execution_described",
                   "sample.bare_number", "repetition.count_does_not_establish", "stats.p_value_present",
                   "quarantine.repeated_result_all_occurrences", "quarantine.declared_result_cannot_be_located",
                   "quarantine.mutation.numeric", "resultspans.paraphrased_missed", "injection.in_protocol_text.INJ_END",
                   "injection.already_escaped", "window.defining_excerpt_straddles", "window.result_straddling",
                   "execution.exec_ran", "provider.missing_provider", "provider.link.refusal", "bound.zero_budget",
                   "determinism.resume_before", "hybrid.strong_track_never_hides", "upstream.claim_edit",
                   "legacy.results_and_experiments", "safety.no_search_no_network", "lang.arabic_diacritized"):
        assert needle in ids, needle


# -- authoring independence ------------------------------------------------------------------------------------


def test_generator_imports_no_production_logic_and_no_runner():
    for path in GEN_FILES:
        for name in _imports(path):
            assert not name.startswith(PRODUCTION), (path.name, name)
            assert not name.startswith(RUNNERS), (path.name, name)
            assert name not in ("src.evals.experiment_review.dataset",), (path.name, name)


def test_gold_scoring_modules_import_no_phase3b_production_semantics():
    for path in SCORING_FILES:
        for name in _imports(path):
            assert not name.startswith(PRODUCTION), (path.name, name)


def test_only_the_adapter_touches_the_production_runtime():
    adapter = _imports(GOLD_PKG / "adapter.py")
    assert any(n.startswith("src.research.experiments") for n in adapter)
    # the adapter exposes no catalog, posture or continuity function to the scorer
    src = (GOLD_PKG / "adapter.py").read_text(encoding="utf-8")
    for banned in ("derive_experiment_posture", "derive_phase2j_coverage", "derive_experiment_issues",
                   "EXPERIMENT_CATALOG", "resolve_applicability"):
        assert banned not in src, banned


# -- metrics, gates, controls ----------------------------------------------------------------------------------


def test_full_offline_run_passes():
    results, report = cached_run()
    assert not report.errored and not report.failed_cases, report.failures[:5]
    assert report.passed
    assert report.measured_quality >= 45
    assert set(report.per_language) == {"en", "ar", "mixed"} and report.per_language_perfect


def test_deterministic_metrics_are_exactly_one_and_nothing_is_unmeasured():
    _, report = cached_run()
    assert len(DETERMINISTIC_FAMILIES) + len(MODEL_JUDGMENT_FAMILIES) >= 45
    assert not report.unmeasured
    for family in DETERMINISTIC_FAMILIES:
        n, d = report.quality_counts[family]
        assert d > 0 and n == d, family
    assert all(report.quality[f] == 1.0 for f in DETERMINISTIC_FAMILIES)


def test_model_judgment_metrics_are_measured_and_reported_not_forced():
    _, report = cached_run()
    for family in MODEL_JUDGMENT_FAMILIES:
        n, d = report.model_judgment[family]
        assert d > 0, family
    # honest: at least one semantic family really is below 1.0, because wrong judgments are seeded on purpose
    assert any(n < d for n, d in report.model_judgment.values())
    text = render(report)
    for family in MODEL_JUDGMENT_FAMILIES:
        assert family in text


def test_every_gate_has_real_denominator_and_zero_violations():
    _, report = cached_run()
    assert len(report.gates) >= mt.MIN_GATES >= 150
    assert not report.zero_denominator_gates, report.zero_denominator_gates
    assert all(v == 0 for v, _ in report.gates.values()), {g: v for g, (v, _) in report.gates.items() if v}


def test_no_denominator_floors_in_eval_code():
    """A denominator is counted from real opportunities. No eval module may floor one."""
    for path in GOLD_PKG.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"max\(\s*1\s*,", src), path.name
        assert not re.search(r",\s*1\s*\)\s*#?\s*(denominator|opportunit)", src), path.name
        assert not re.search(r"(denominator|opportunities)\s*=\s*max\(", src), path.name
        assert "opportunity_floor" not in src and "denominator_floor" not in src, path.name


def test_thin_gates_are_reported_with_their_denominators():
    _, report = cached_run()
    for name, d in report.thin_gates:
        assert 0 < d < mt.THIN
    assert "thin_gates" in render(report)


def test_gate_denominators_are_counted_from_case_facts():
    results, _ = cached_run()
    for name, flag in (("replay_made_model_call", "rerun"), ("resume_changed_review", "interrupt_before"),
                       ("legacy_state_changes_review", "legacy_leak")):
        opps = sum(r.gates[name][1] for r in results if not r.error)
        flagged = sum(1 for r in results if bool(getattr(r.case, flag)))
        assert opps == flagged, name


def test_negative_controls_minimums_and_intended_reason():
    _, report = cached_run()
    assert report.controls[1] >= mt.MIN_CONTROL_ATTEMPTS >= 300 and report.controls[0] == report.controls[1]
    assert len(report.control_names) >= mt.MIN_CONTROL_MECHANISMS >= 70
    assert not report.control_misses
    assert all(n == d and d > 0 for n, d in report.control_names.values())
    # a mechanism is one mutation kind: 20 repeats of one mutation are one mechanism
    assert len(set(ctl.ALL_CONTROLS)) == len(ctl.ALL_CONTROLS)
    assert set(report.control_names) == set(ctl.ALL_CONTROLS), set(ctl.ALL_CONTROLS) - set(report.control_names)


def test_every_validator_control_names_the_field_or_reason_it_expects():
    for name, (_, (kind, expect)) in ctl.CONTROL_FUNCS.items():
        assert kind in ("validator", "gate")
        if kind == "gate":
            assert expect in gt.GATE_FUNCS, name
        else:
            assert expect.strip(), name


def test_registries_are_distinct_from_quality():
    assert len(set(gt.GATES)) == len(gt.GATES) >= 150
    assert not set(gt.GATES) & set(DETERMINISTIC_FAMILIES)


def test_verbose_cli_output():
    results, report = cached_run()
    out = render(report, verbose=True, results=results)
    for needle in ("cases=", "semantic_families=", "deterministic families", "model-judgment families", "release gates=",
                   "thin_gates", "negative controls caught=", "gate ", "control ", "PASS"):
        assert needle in out, needle


def test_no_network_or_external_search():
    results, _ = cached_run()
    ran = [r for r in results if not r.error]
    assert all(r.ctx.network_attempts == 0 and r.ctx.d["external_search_calls"] == 0 and r.ctx.d["network_attempts"] == 0
               for r in ran)
    for path in (ROOT / "src" / "research" / "experiments").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(httpx|requests|socket|urllib)", src, flags=re.M), path.name
        assert "src.research.academic" not in src


def test_deterministic_repeat_run_of_one_case():
    case = next(c for c in load_cases() if c.semantic_family_id == "type.well.ENGINEERING_BENCH_TEST" and c.language == "en")
    a, b = runner.run_case(case), runner.run_case(case)
    assert a.gates == b.gates and dict(a.quality) == dict(b.quality)


# -- non-vacuity: disable ONE production mechanism and require the intended gate to fire --------------------------


def _one(family: str, lang: str = "en"):
    return next(c for c in load_cases() if c.semantic_family_id == family and c.language == lang).model_copy(
        update={"negative_control_tags": []})


def _violations(case, *gates: str) -> dict[str, int]:
    result = runner.run_case(case)
    assert result.error is None, result.error
    return {g: result.gates[g][0] for g in gates}


def _clean(case, *gates: str) -> None:
    assert all(v == 0 for v in _violations(case, *gates).values())


def test_non_vacuity_exact_anchoring(monkeypatch):
    import src.research.experiments.verify as verify
    from src.research.novelty.anchoring import Located

    case = _one("seg.repeated_defining_without_occurrence")
    gates = ("ambiguous_span_without_disambiguator_accepted", "repeated_excerpt_first_match_guessed")
    _clean(case, *gates)
    real = verify.locate

    def guessing(text, excerpt, **kw):
        pos = text.find(excerpt)
        if pos < 0:
            return real(text, excerpt, **kw)
        from src.schemas.novelty_differentiation import OccurrenceResolution

        return Located(pos, pos + len(excerpt), 1, 1, OccurrenceResolution.UNIQUE_IN_TEXT)

    monkeypatch.setattr(verify, "locate", guessing)
    v = _violations(case, *gates)
    assert v["ambiguous_span_without_disambiguator_accepted"] > 0


def test_non_vacuity_phase2j_continuity_and_mosaic(monkeypatch):
    import src.research.experiments.synthesis as syn
    import src.schemas.experiment_review as er

    case = _one("cont.mosaic_three_experiments_never_covered")
    gates = ("mosaic_scenario_reads_covered", "coverage_status_unsupported", "cross_experiment_mosaic_coverage")
    _clean(case, *gates)

    def pooled(target, **kw):
        attempting = sorted({lk.experiment_id for lk in kw["links"] if lk.validation_requirement_id == target.validation_requirement_id
                             and lk.relation in er.TESTING_RELATIONS}, key=str)
        return er.CoverageStatus.COVERED_BY_EXPERIMENT, attempting, []

    monkeypatch.setattr(er, "derive_phase2j_coverage", pooled)
    monkeypatch.setattr(syn, "derive_phase2j_coverage", pooled)
    v = _violations(case, *gates)
    assert v["mosaic_scenario_reads_covered"] > 0 and v["coverage_status_unsupported"] > 0


def test_non_vacuity_result_quarantine_fail_closed(monkeypatch):
    import src.research.experiments.pipeline as pl

    case = _one("quarantine.declared_result_cannot_be_located")
    gates = ("incomplete_quarantine_accepted_as_complete", "incomplete_quarantine_later_model_call")
    _clean(case, *gates)
    monkeypatch.setattr(pl, "quarantine_incomplete", lambda run: False)
    v = _violations(case, *gates)
    assert v["incomplete_quarantine_later_model_call"] > 0 or v["incomplete_quarantine_accepted_as_complete"] > 0


def test_non_vacuity_metric_target_alignment_guard(monkeypatch):
    import src.research.experiments.linkage as lk
    import src.schemas.experiment_review as er

    case = _one("link.directly_tests_without_measurement")
    gates = ("directly_tests_without_aligned_measurement",)
    _clean(case, *gates)
    monkeypatch.setattr(lk, "directly_tests_supported", lambda link, measurements: True)
    monkeypatch.setattr(er, "directly_tests_supported", lambda link, measurements: True)
    result = runner.run_case(case)
    fired = result.gates["directly_tests_without_aligned_measurement"][0] > 0
    refused = result.error is not None and "aligned" in result.error.lower()
    assert fired or refused  # the guard is the ONLY thing standing between this input and a strong link


def test_non_vacuity_deterministic_posture_precedence(monkeypatch):
    import src.research.experiments.synthesis as syn
    import src.schemas.experiment_review as er

    case = _one("missing.ENGINEERING_BENCH_TEST.SETUP")
    gates = ("well_specified_with_issue", "experiment_posture_stronger_than_derived")
    _clean(case, *gates)
    well = er.ExperimentPosture.WELL_SPECIFIED
    monkeypatch.setattr(er, "derive_experiment_posture", lambda **k: well)
    monkeypatch.setattr(syn, "derive_experiment_posture", lambda **k: well)
    v = _violations(case, *gates)
    assert v["well_specified_with_issue"] > 0 and v["experiment_posture_stronger_than_derived"] > 0


def test_non_vacuity_baseline_required_guard_for_improvement_claim(monkeypatch):
    import src.schemas.experiment_review as er

    case = _one("applic.improvement_claim_baseline_absent")
    gates = ("required_missing_requirement_without_issue", "improvement_claim_without_baseline_reads_well")
    _clean(case, *gates)
    patched = {k: v for k, v in er.MISSING_REQUIREMENT_ISSUE.items() if k.value not in ("BASELINE", "BASELINE_CONFIGURATION")}
    monkeypatch.setattr(er, "MISSING_REQUIREMENT_ISSUE", patched)
    v = _violations(case, *gates)
    assert v["required_missing_requirement_without_issue"] > 0


def test_non_vacuity_prompt_marker_escaping(monkeypatch):
    import src.llm.prompts as prompts

    case = _one("injection.in_protocol_text.INJ_END")
    gates = ("forged_marker_unescaped", "prompt_end_marker_count_not_one")
    _clean(case, *gates)
    monkeypatch.setattr(prompts, "escape_untrusted", lambda text: text)
    result = runner.run_case(case)
    fired = result.gates["forged_marker_unescaped"][0] > 0 or result.gates["prompt_end_marker_count_not_one"][0] > 0
    assert fired


def test_non_vacuity_prompt_trusted_tail_isolation(monkeypatch):
    import src.llm.prompts as prompts
    import src.research.experiments.linkage as lk
    import src.research.experiments.protocol as pr
    import src.research.experiments.segment as sg

    case = _one("type.well.ENGINEERING_BENCH_TEST")
    gates = ("student_text_in_trusted_tail",)
    _clean(case, *gates)
    real = prompts.build_experiment_user_input

    def leaky(**kw):
        body = real(**kw)
        return body + "\n" + (kw.get("submission_text") or " ".join(t for _, t in kw.get("excerpts") or []))

    for module in (sg, pr, lk):
        monkeypatch.setattr(module, "build_experiment_user_input", leaky)
    assert _violations(case, *gates)["student_text_in_trusted_tail"] > 0


def test_non_vacuity_visible_window_containment(monkeypatch):
    import src.research.experiments.verify as verify

    case = _one("window.defining_excerpt_straddles_window_end")
    gates = ("excerpt_beyond_window_any_case", "excerpt_straddles_window_edge", "excerpt_outside_visible_window")
    _clean(case, *gates)
    monkeypatch.setattr(verify.SourceWindow, "of", classmethod(lambda cls, text, bounds: cls(0, len(text))))
    result = runner.run_case(case)
    assert result.gates["excerpt_beyond_window_any_case"][0] > 0


def test_non_vacuity_all_occurrence_result_quarantine(monkeypatch):
    import src.research.experiments.segment as sg

    case = _one("quarantine.repeated_result_all_occurrences")
    gates = ("first_match_only_quarantine", "declared_result_occurrence_not_quarantined")
    _clean(case, *gates)
    real = sg.occurrences
    monkeypatch.setattr(sg, "occurrences", lambda text, needle: real(text, needle)[:1])
    v = _violations(case, *gates)
    assert v["first_match_only_quarantine"] > 0 and v["declared_result_occurrence_not_quarantined"] > 0


def test_non_vacuity_recorded_bounds(monkeypatch):
    """The defect Gold itself found: the run recorded default bounds whatever the stages used."""
    import src.research.experiments.binding as binding

    case = _one("window.protocol_inside_result_after_window")
    gates = ("excerpt_outside_visible_window", "excerpt_beyond_window_any_case")
    _clean(case, *gates)
    real = binding.open_experiment_run
    monkeypatch.setattr(binding, "open_experiment_run", lambda *a, **k: real(*a, **{**k, "bounds": None}))
    result = runner.run_case(case)
    assert result.error is None or "bounds" in result.error.lower() or result.gates
    from src.evals.experiment_review.adapter import bounds_of

    state_bounds = result.ctx.d["bounds"]["max_submission_chars"]
    assert state_bounds != bounds_of(case.bounds).max_submission_chars  # the recorded window is the wrong one again
