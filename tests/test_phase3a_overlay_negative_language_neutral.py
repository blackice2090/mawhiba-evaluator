"""The NO_METHODOLOGY_RELEVANCE acceptance contract is language-neutral: complete bounded review of every bound
claim and hypothesis, identical in English, Arabic, mixed text, with or without metadata or lexicon hits."""

from __future__ import annotations

import pytest

from src.schemas.methodology_review import OverlayMateriality as M
from tests.fixtures.phase3a_submissions import AR_VERIFICATION, MIXED_CONSTRAINT
from tests.phase3a_support import (
    ENGINEERING_TEXT, ScriptedMethodologyModel, edited, run_stages, well_engineering_script, world)

AI, SW = "AI_ML", "SOFTWARE_SYSTEMS"
TEXTS = {
    "en": ENGINEERING_TEXT,
    "ar": ENGINEERING_TEXT + " " + AR_VERIFICATION,
    "mixed": ENGINEERING_TEXT + " " + MIXED_CONSTRAINT,
    "lexicon_hit": ENGINEERING_TEXT + " The software uses a trained model and a database.",
    "unseen_synonym": ENGINEERING_TEXT + " An estimator learns valve actions from past logs.",
}


def run(text, overlay_spec=None, domains=(), script_edit=None):
    script = well_engineering_script()
    if overlay_spec is not None:
        script = edited(script, overlay=overlay_spec)
    state = world(text=text, domains=domains)
    return run_stages(state, ScriptedMethodologyModel(script).provider())


def of(run_, name):
    return next(o for o in run_.overlays if o.overlay.value == name)


COMPLETE = {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": ["H1"]}


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_complete_bounded_negative_resolves_non_material_in_every_language_mode(key):
    r = run(TEXTS[key], {AI: COMPLETE, SW: COMPLETE})
    for name in (AI, SW):
        o = of(r, name)
        assert o.materiality is M.IMPLEMENTATION_TOOL_ONLY and not o.excerpt_ids


@pytest.mark.parametrize("key", sorted(TEXTS))
@pytest.mark.parametrize("spec", [
    {"materiality": "NO_METHODOLOGY_RELEVANCE"},
    {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": []},
    {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": [], "hypotheses": ["H1"]},
    {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1", "C9"], "hypotheses": ["H1"]},
    {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": ["C1"], "hypotheses": ["H1", "H9"]},
])
def test_incomplete_or_foreign_negative_is_unresolved_identically_everywhere(key, spec):
    r = run(TEXTS[key], {AI: spec})
    assert of(r, AI).materiality is M.MATERIALITY_UNRESOLVED


def test_metadata_does_not_change_the_negative_contract():
    for domains in ((), ("MACHINE_LEARNING",)):
        assert of(run(TEXTS["en"], {AI: COMPLETE}, domains), AI).materiality is M.IMPLEMENTATION_TOOL_ONLY
        assert of(run(TEXTS["en"], {AI: {"materiality": "NO_METHODOLOGY_RELEVANCE"}}, domains), AI
                  ).materiality is M.MATERIALITY_UNRESOLVED


def test_keyword_text_alone_never_establishes_material():
    r = run(TEXTS["lexicon_hit"], {AI: {"materiality": "MATERIAL_TO_TARGET", "claims": ["C1"]}})
    assert of(r, AI).materiality is M.MATERIALITY_UNRESOLVED


def test_provider_omission_refusal_and_error_stay_unresolved():
    state = world(text=TEXTS["en"])
    omitted = run_stages(state, ScriptedMethodologyModel(edited(well_engineering_script(), overlay_omit=True)).provider())
    assert {o.materiality for o in omitted.overlays} == {M.MATERIALITY_UNRESOLVED}
    for kind in ("refusal", "provider_error"):
        script = edited(well_engineering_script(), overlay=kind)
        r = run_stages(state, ScriptedMethodologyModel(script).provider())
        assert {o.materiality for o in r.overlays} == {M.MATERIALITY_UNRESOLVED}
    assert {o.materiality for o in run_stages(state, None).overlays} == {M.MATERIALITY_UNRESOLVED}


def test_a_wrong_but_complete_negative_is_accepted_structurally_and_left_to_measurement():
    """The model says 'no relevance' about a project whose text really uses ML: structurally valid, so it is
    accepted; Gold measures it as a model-judgment error (it is never reclassified as deterministic truth)."""
    r = run(TEXTS["unseen_synonym"], {AI: COMPLETE})
    assert of(r, AI).materiality is M.IMPLEMENTATION_TOOL_ONLY
