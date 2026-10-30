"""Phase 3A production: overlay materiality, ownership and double counting (hardened architecture A)."""

from __future__ import annotations

from src.schemas.common import ProjectType, TechnicalDomain
from src.schemas.methodology_review import (
    REQUIREMENT_CATALOG,
    Applicability,
    ApplicabilityBasis,
    MethodologyIssueCode,
    MethodologyPosture,
    MethodologyRunIssueCode,
    MethodologyTrack,
    OverlayMateriality,
    OverlayOwnershipBasis,
    RequirementKind,
    RequirementOverlay,
)
from tests.phase3a_support import (
    ENGINEERING_TEXT,
    ScriptedMethodologyModel,
    edited,
    run_stages,
    well_engineering_script,
    world,
)

E, R = MethodologyTrack.ENGINEERING, MethodologyTrack.SCIENTIFIC_RESEARCH
AI, SW = RequirementOverlay.AI_ML, RequirementOverlay.SOFTWARE_SYSTEMS
ML = (TechnicalDomain.MACHINE_LEARNING,)
S_ML = "The model is a gradient boosted classifier trained on labelled moisture logs."
S_SW = "The platform stores readings in a relational database behind a web interface."
TEXT = ENGINEERING_TEXT + " " + S_ML + " " + S_SW


def overlay(name, materiality="MATERIAL_TO_TARGET", *, claims=("C1",), hypotheses=(), excerpt=S_ML, owner=None,
            served=()):
    return {name: {"materiality": materiality, "claims": list(claims), "hypotheses": list(hypotheses),
                   "excerpts": [excerpt] if excerpt else [], "owner_track": owner, "served_tracks": list(served)}}


def ai_script(**overlay_args):
    return edited(well_engineering_script(), overlay=overlay("AI_ML", **overlay_args))


def go(state, script):
    return run_stages(state, ScriptedMethodologyModel(script).provider())


def ai_kinds(assessment):
    return {a.kind for a in assessment.applicability if REQUIREMENT_CATALOG[a.kind].overlay is AI}


def assignment(run, overlay_kind=AI):
    return next(o for o in run.overlays if o.overlay is overlay_kind)


def test_a_domain_word_alone_is_not_materiality_or_ownership():
    run = go(world(domains=ML, text=TEXT), {})  # a provider that answers nothing
    o = assignment(run)
    assert o.materiality is OverlayMateriality.MATERIALITY_UNRESOLVED and o.owner_track is None
    assert o.signal_domains == list(ML) and o.blocks_well_specified


def test_engineering_only_ai_project_cannot_escape_ai_ml_requirements():
    run = go(world(domains=ML, text=TEXT), ai_script())
    o = assignment(run)
    assert o.owner_track is E and o.ownership_basis is OverlayOwnershipBasis.SINGLE_TRACK_PROJECT
    (ta,) = run.track_assessments
    required = {a.kind for a in ta.applicability if a.applicability is Applicability.REQUIRED}
    assert {RequirementKind.TEST_SET_ISOLATION_FROM_TUNING, RequirementKind.DATA_LEAKAGE_PREVENTION,
            RequirementKind.TEST_SPLIT, RequirementKind.LABELS} <= required
    assert {i.code for i in ta.issues} >= {MethodologyIssueCode.TEST_SET_ISOLATION_NOT_DOCUMENTED,
                                           MethodologyIssueCode.DATA_LEAKAGE_RISK}
    assert ta.posture is MethodologyPosture.METHODOLOGY_HAS_MAJOR_DESIGN_GAPS


def test_scientific_research_ai_project_is_owned_by_the_research_track():
    run = go(world(ProjectType.SCIENTIFIC_RESEARCH, domains=ML, text=TEXT), ai_script())
    o = assignment(run)
    assert o.owner_track is R and o.ownership_basis is OverlayOwnershipBasis.SINGLE_TRACK_PROJECT
    assert RequirementKind.TEST_SPLIT in ai_kinds(run.assessment_for(R))


def test_hybrid_ownership_follows_the_phase_2j_facet_of_the_served_hypothesis():
    run = go(world(ProjectType.HYBRID, domains=ML, text=TEXT),
             ai_script(hypotheses=("H1",), owner="SCIENTIFIC_RESEARCH", served=("SCIENTIFIC_RESEARCH",)))
    o = assignment(run)
    # the hypothesis' one Phase 2J facet is ENGINEERING: the model's research preference is ignored
    assert o.owner_track is E and o.ownership_basis is OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET
    assert E in o.served_tracks, "the owner always serves itself"
    assert RequirementKind.TEST_SPLIT in ai_kinds(run.assessment_for(E))
    assert not ai_kinds(run.assessment_for(R)), "no research-track shortcut and no double counting"


def test_hybrid_ownership_by_bounded_judgment_can_be_the_research_track():
    run = go(world(ProjectType.HYBRID, domains=ML, text=TEXT),
             ai_script(owner="SCIENTIFIC_RESEARCH", served=("SCIENTIFIC_RESEARCH", "ENGINEERING")))
    o = assignment(run)
    assert o.owner_track is R and o.ownership_basis is OverlayOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT
    assert o.served_tracks == [R, E] or set(o.served_tracks) == {R, E}
    assert ai_kinds(run.assessment_for(R)) and not ai_kinds(run.assessment_for(E))


def test_hybrid_overlay_requirements_are_counted_once():
    run = go(world(ProjectType.HYBRID, domains=ML, text=TEXT),
             ai_script(owner="ENGINEERING", served=("SCIENTIFIC_RESEARCH", "ENGINEERING")))
    counted = [(ta.track, a.kind) for ta in run.track_assessments for a in ta.applicability
               if REQUIREMENT_CATALOG[a.kind].overlay is AI]
    assert len(counted) == len(set(counted)) == len({k for _, k in counted})
    assert {t for t, _ in counted} == {E}


def test_unresolved_hybrid_ownership_stays_conditional_and_blocks_every_track():
    run = go(world(ProjectType.HYBRID, domains=ML, text=TEXT), ai_script())  # claims only, no owner offered
    o = assignment(run)
    assert o.materiality is OverlayMateriality.MATERIAL_TO_TARGET and o.owner_track is None
    assert o.ownership_basis is OverlayOwnershipBasis.UNRESOLVED and o.blocks_well_specified
    unowned = [a for a in run.draft.applicability if a.basis is ApplicabilityBasis.OVERLAY_OWNERSHIP_UNRESOLVED]
    assert unowned and all(a.track is None and a.applicability is Applicability.CONDITIONAL for a in unowned)
    assert all(ta.overlay_blocked for ta in run.track_assessments)
    assert not any(ta.posture is MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
                   for ta in run.track_assessments)
    assert not any(ai_kinds(ta) for ta in run.track_assessments), "counted in no track while unowned"


def test_unresolved_materiality_blocks_a_posture_that_would_otherwise_be_well_specified():
    clean = go(world(), well_engineering_script())
    assert clean.track_assessments[0].posture is MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
    blocked = go(world(domains=ML, text=TEXT), edited(well_engineering_script(),
                                                      overlay=overlay("AI_ML", "MATERIALITY_UNRESOLVED")))
    (ta,) = blocked.track_assessments
    assert ta.overlay_blocked and ta.posture is MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED


def test_implementation_only_overlay_is_not_forced_but_needs_exact_evidence():
    tool = go(world(domains=ML, text=TEXT), ai_script(materiality="IMPLEMENTATION_TOOL_ONLY"))
    o = assignment(tool)
    assert o.materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY and o.owner_track is None
    assert not o.blocks_well_specified and not ai_kinds(tool.track_assessments[0]) or all(
        a.applicability is Applicability.NOT_APPLICABLE for a in tool.track_assessments[0].applicability
        if REQUIREMENT_CATALOG[a.kind].overlay is AI)
    evasive = go(world(domains=ML, text=TEXT), ai_script(materiality="IMPLEMENTATION_TOOL_ONLY", excerpt=None))
    assert assignment(evasive).materiality is OverlayMateriality.MATERIALITY_UNRESOLVED, (
        "a tool-only verdict without an exact excerpt cannot make an AI project escape review")


def test_material_overlay_without_a_bound_target_or_excerpt_is_unresolved():
    no_target = go(world(domains=ML, text=TEXT), ai_script(claims=()))
    no_excerpt = go(world(domains=ML, text=TEXT), ai_script(excerpt=None))
    fabricated = go(world(domains=ML, text=TEXT), ai_script(excerpt="a sentence the student never wrote"))
    for run in (no_target, no_excerpt, fabricated):
        assert assignment(run).materiality is OverlayMateriality.MATERIALITY_UNRESOLVED
    assert any(r.code is MethodologyRunIssueCode.FABRICATED_EXCERPT for r in fabricated.rejected_proposals)


def test_materiality_cannot_be_invented_from_nothing():
    # the model calls the overlay material, but the excerpt it cites is not in the submission
    run = go(world(), edited(well_engineering_script(), overlay=overlay("AI_ML")))
    assert assignment(run).materiality is OverlayMateriality.MATERIALITY_UNRESOLVED
    assert any(r.code is MethodologyRunIssueCode.FABRICATED_EXCERPT for r in run.rejected_proposals)
    assert not any(a.applicability is Applicability.REQUIRED for ta in run.track_assessments
                   for a in ta.applicability if REQUIREMENT_CATALOG[a.kind].overlay is AI)


def test_software_overlay_material_in_a_research_only_project_is_owned_by_research():
    state = world(ProjectType.SCIENTIFIC_RESEARCH, domains=(TechnicalDomain.SOFTWARE_ENGINEERING,), text=TEXT)
    run = go(state, edited(well_engineering_script(), overlay=overlay("SOFTWARE_SYSTEMS", excerpt=S_SW)))
    o = assignment(run, SW)
    assert o.owner_track is R and o.ownership_basis is OverlayOwnershipBasis.SINGLE_TRACK_PROJECT
    sw = {a.kind for a in run.assessment_for(R).applicability if REQUIREMENT_CATALOG[a.kind].overlay is SW}
    assert RequirementKind.EXISTING_ALTERNATIVES_COMPARISON in sw


def test_software_used_only_as_a_tool_does_not_force_the_overlay():
    state = world(ProjectType.SCIENTIFIC_RESEARCH, domains=(TechnicalDomain.SOFTWARE_ENGINEERING,), text=TEXT)
    run = go(state, edited(well_engineering_script(),
                           overlay=overlay("SOFTWARE_SYSTEMS", "IMPLEMENTATION_TOOL_ONLY", excerpt=S_SW)))
    o = assignment(run, SW)
    assert o.materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY and not o.blocks_well_specified
