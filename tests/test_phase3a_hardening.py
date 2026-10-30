"""Phase 3A pre-Gold hardening: overlay candidate discovery, the execution-description taxonomy, and
distinct typed failure reasons."""

from __future__ import annotations

import pytest

from src.graph.phase3a_graph import FORBIDDEN_NODES
from src.graph.registry import NodeId
from src.llm.contracts import ModelTask
from src.research.methodology import inventory as inv
from src.schemas.common import ProjectType
from src.schemas.methodology_review import (
    REQUIREMENT_CATALOG,
    Applicability,
    MethodologyIssueCode,
    MethodologyPosture,
    MethodologyReviewBounds,
    MethodologyRunIssueCode,
    MethodologyTrack,
    OverlayMateriality,
    OverlayOwnershipBasis,
    RequirementOverlay,
    StudentMethodologyExcerpt,
)
from tests.phase3a_support import (
    ENGINEERING_TEXT,
    ScriptedMethodologyModel,
    edited,
    prompt_line,
    run_stages,
    well_engineering_script,
    world,
)
from tests.test_phase3a_overlays import S_ML, S_SW, TEXT, ai_kinds, ai_script, assignment, go, overlay

E, R = MethodologyTrack.ENGINEERING, MethodologyTrack.SCIENTIFIC_RESEARCH
AI, SW = RequirementOverlay.AI_ML, RequirementOverlay.SOFTWARE_SYSTEMS
WELL = MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT


# -- 1. overlay candidate discovery -----------------------------------------------------------------------


def test_engineering_ai_project_with_no_metadata_signal_still_enters_materiality_review():
    state = world(text=TEXT)  # no domain, no models, no datasets
    assert not inv.overlay_signals(state.project)
    run = go(state, ai_script())
    o = assignment(run)
    assert o.materiality is OverlayMateriality.MATERIAL_TO_TARGET and o.signal_domains == []
    assert o.owner_track is E and ai_kinds(run.assessment_for(E))


def test_research_ai_project_with_no_domain_signal_but_a_bound_phase_2j_target_enters_review():
    run = go(world(ProjectType.SCIENTIFIC_RESEARCH, text=TEXT), edited(
        well_engineering_script(), overlay=overlay("AI_ML", claims=(), hypotheses=("H1",))))
    o = assignment(run)
    assert o.materiality is OverlayMateriality.MATERIAL_TO_TARGET and o.material_gap_hypothesis_ids
    assert o.owner_track is R and o.ownership_basis is OverlayOwnershipBasis.SINGLE_TRACK_PROJECT


def test_software_overlay_becomes_a_candidate_from_bound_text_with_empty_technical_metadata():
    state = world(text=TEXT)
    assert SW not in inv.overlay_signals(state.project)
    run = go(state, edited(well_engineering_script(),
                           overlay=overlay("SOFTWARE_SYSTEMS", excerpt=S_SW)))
    assert assignment(run, SW).materiality is OverlayMateriality.MATERIAL_TO_TARGET


def test_a_keyword_alone_never_makes_an_overlay_material():
    state = world(text=TEXT)
    from tests.phase3a_support import CLAIM_TEXT

    assert {AI, SW} <= inv.signaled_overlays(state.project, {"C-001": CLAIM_TEXT}, state.submission, [])
    # no model: a keyword is still only a question
    nothing = run_stages(state, None)
    assert {o.materiality for o in nothing.overlays} == {OverlayMateriality.MATERIALITY_UNRESOLVED}
    # a material verdict that binds no target is not accepted
    assert assignment(go(state, ai_script(claims=()))).materiality is OverlayMateriality.MATERIALITY_UNRESOLVED
    # 'no relevance' is not accepted for an overlay the inputs hint at: it needs an exact-excerpt tool-only verdict
    denied = go(state, edited(well_engineering_script(), overlay={"AI_ML": {"materiality": "NO_METHODOLOGY_RELEVANCE"}}))
    assert assignment(denied).materiality is OverlayMateriality.MATERIALITY_UNRESOLVED


# an English paraphrase that no metadata tag and none of the lexicon terms recognise
S_PARAPHRASE_ML = "The estimator learns a mapping from sensor traces to valve actions using past field logs."
S_PARAPHRASE_SW = "Every reading is kept in a durable store that field staff query from their phones."
PARAPHRASE_TEXT = ENGINEERING_TEXT + " " + S_PARAPHRASE_ML + " " + S_PARAPHRASE_SW


def test_a_paraphrase_with_no_metadata_and_no_lexicon_hit_is_still_reviewed_and_can_be_material():
    state = world(text=PARAPHRASE_TEXT)
    from tests.phase3a_support import CLAIM_TEXT

    assert not inv.overlay_signals(state.project)
    assert not inv.signaled_overlays(state.project, {"C-001": CLAIM_TEXT}, state.submission, [])
    assert set(inv.overlay_candidates(state.project)) == {AI, SW}, "discovery is complete by construction"
    script = well_engineering_script()
    script["overlay"] = {**overlay("AI_ML", excerpt=S_PARAPHRASE_ML), **overlay("SOFTWARE_SYSTEMS", excerpt=S_PARAPHRASE_SW)}
    model = ScriptedMethodologyModel(script)
    run = run_stages(state, model.provider())
    assert model.count(ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT) == 1
    for kind in (AI, SW):
        o = assignment(run, kind)
        assert o.materiality is OverlayMateriality.MATERIAL_TO_TARGET and o.owner_track is E and o.excerpt_ids
    assert ai_kinds(run.assessment_for(E))


def test_an_overlay_the_model_does_not_answer_for_is_never_silently_excluded():
    script = edited(well_engineering_script(), overlay_omit=True, overlay={})
    run = go(world(), script)
    assert {o.materiality for o in run.overlays} == {OverlayMateriality.MATERIALITY_UNRESOLVED}
    assert all(ta.overlay_blocked for ta in run.track_assessments)
    assert run.track_assessments[0].posture is MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED


def test_a_plain_project_resolves_both_overlays_safely_as_non_material_without_fabricated_evidence():
    run = go(world(), well_engineering_script())
    assert {o.overlay for o in run.overlays} == {AI, SW}
    assert all(o.materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY and not o.excerpt_ids and not o.blocks_well_specified
               for o in run.overlays)
    assert all(a.applicability is Applicability.NOT_APPLICABLE for a in run.draft.applicability
               if REQUIREMENT_CATALOG[a.kind].overlay is not RequirementOverlay.CORE)
    assert run.track_assessments[0].posture is WELL and run.model_calls_performed == 5


@pytest.mark.parametrize("kind", ["provider_error", "refusal", "refusal_leak"])
def test_provider_failure_on_an_overlay_review_never_yields_a_well_specified_posture(kind):
    run = go(world(), edited(well_engineering_script(), overlay=kind))
    assert {o.materiality for o in run.overlays} == {OverlayMateriality.MATERIALITY_UNRESOLVED}
    assert run.track_assessments[0].posture is MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED
    assert MethodologyRunIssueCode.MODEL_ERROR in {e.code for e in run.errors}
    assert prompt_line() not in run.model_dump_json()


def test_an_implementation_tool_only_overlay_without_metadata_stays_non_material_and_inactive():
    run = go(world(text=TEXT), ai_script(materiality="IMPLEMENTATION_TOOL_ONLY"))
    o = assignment(run)
    assert o.materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY and not o.blocks_well_specified
    assert all(a.applicability is Applicability.NOT_APPLICABLE
               for a in run.draft.applicability if REQUIREMENT_CATALOG[a.kind].overlay is AI)


def test_hybrid_ownership_and_no_double_counting_are_unchanged_without_metadata():
    run = go(world(ProjectType.HYBRID, text=TEXT), ai_script(hypotheses=("H1",), owner="SCIENTIFIC_RESEARCH"))
    o = assignment(run)
    assert o.owner_track is E and o.ownership_basis is OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET
    assert ai_kinds(run.assessment_for(E)) and not ai_kinds(run.assessment_for(R))


# -- 2. execution descriptions -------------------------------------------------------------------------------


def test_past_tense_execution_descriptions_do_not_create_a_defect_or_downgrade_a_well_specified_track():
    script = well_engineering_script()
    for spec in script["evidence"].values():
        spec["mode"] = "DESCRIBED_AS_EXECUTED"
    run = run_stages(world(), ScriptedMethodologyModel(script).provider())
    (ta,) = run.track_assessments
    assert ta.posture is WELL and not ta.issues
    assert {e.statement_mode.value for e in run.excerpts} >= {"DESCRIBED_AS_EXECUTED"}
    assert all(e.execution_verified is False for e in run.excerpts)


def test_execution_can_never_be_verified_in_phase_3a_and_no_output_implies_it():
    run = run_stages(world(), ScriptedMethodologyModel(well_engineering_script()).provider())
    with pytest.raises(Exception):
        StudentMethodologyExcerpt.model_validate({**run.excerpts[0].model_dump(), "execution_verified": True})
    with pytest.raises(Exception):
        type(run.track_assessments[0]).model_validate({**run.track_assessments[0].model_dump(), "execution_verified": True})
    assert '"execution_verified":true' not in run.model_dump_json().replace(" ", "")


def test_the_dead_execution_issue_kind_is_gone_and_phase_3b_owns_execution_verification():
    assert not any("EXECUTION" in c.value for c in MethodologyIssueCode)
    assert NodeId.EXPERIMENT_REVIEW in FORBIDDEN_NODES


# -- 3. distinct failure reasons -----------------------------------------------------------------------------


def _codes(run):
    return {e.code for e in run.errors}


def test_bound_reached_and_provider_unavailable_have_distinct_typed_codes():
    state = world()
    model = ScriptedMethodologyModel(well_engineering_script())
    bounded = run_stages(state, model.provider(), bounds=MethodologyReviewBounds(max_model_calls=0))
    missing = run_stages(state, None)
    assert model.calls == []
    assert MethodologyRunIssueCode.MODEL_CALL_BOUND_REACHED in _codes(bounded)
    assert MethodologyRunIssueCode.MODEL_PROVIDER_MISSING not in _codes(bounded)
    assert MethodologyRunIssueCode.MODEL_PROVIDER_MISSING in _codes(missing)
    assert MethodologyRunIssueCode.MODEL_CALL_BOUND_REACHED not in _codes(missing)
    for run in (bounded, missing):
        assert run.track_assessments[0].posture is MethodologyPosture.INSUFFICIENT_INPUT


def test_a_bound_reached_mid_run_is_reported_and_never_yields_a_positive_posture():
    model = ScriptedMethodologyModel(well_engineering_script())
    run = run_stages(world(), model.provider(), bounds=MethodologyReviewBounds(max_model_calls=1))
    assert len(model.calls) == 1 and run.model_calls_performed == 1
    assert MethodologyRunIssueCode.MODEL_CALL_BOUND_REACHED in _codes(run)
    assert run.track_assessments[0].posture is not WELL


def test_raw_provider_text_is_not_persisted_in_either_failure_and_replay_is_deterministic():
    leaking = {t: "refusal_leak" for t in ("overlay", "evidence", "applicability", "metric", "link")}
    a = run_stages(world(), ScriptedMethodologyModel(leaking).provider())
    b = run_stages(world(), ScriptedMethodologyModel(leaking).provider())
    bounded = run_stages(world(), ScriptedMethodologyModel(leaking).provider(),
                         bounds=MethodologyReviewBounds(max_model_calls=0))
    for run in (a, bounded):
        assert prompt_line() not in run.model_dump_json()
    assert (a.track_assessments, a.draft, a.errors) == (b.track_assessments, b.draft, b.errors)
