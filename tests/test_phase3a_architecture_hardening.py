"""Phase 3A architecture-hardening contract tests (PHASE_3A_ARCHITECTURE_HARDENING.md).

1. AI/ML and software/systems overlay ownership is complete and deterministic.
2. Strong gap coverage follows the exact bound Phase 2J validation requirement.
3. Baseline relevance does not require an invented student rationale contract.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import src.schemas.methodology_review as mr
from src.schemas.common import ProjectType, TechnicalDomain
from src.schemas.gap_assessment import GapFacet
from src.schemas.methodology_review import (
    Applicability,
    ApplicabilityBasis,
    ApplicabilityTrigger,
    BaselineComparatorRecord,
    BaselineRelevance,
    BaselineRelevanceContext,
    BoundGapTarget,
    MethodologyPosture,
    MethodologyRunStatus,
    MetricAlignment,
    MetricAlignmentStatus,
    OverlayAssignment,
    OverlayMateriality,
    OverlayOwnershipBasis,
    RequirementOverlay,
    methodology_id,
    resolve_applicability,
    tracks_for,
)
from tests.test_phase3a_contracts import (
    ALL_X,
    CLAIM,
    COND,
    HYP,
    RUN,
    VREQ,
    X_BASELINE,
    X_OUTCOME,
    X_RELEVANCE,
    E,
    K,
    R,
    aligned_metric,
    app,
    doc,
    excerpt,
    link,
    req_metric,
    run,
    track,
    well_research_track,
)

AI = RequirementOverlay.AI_ML
SW = RequirementOverlay.SOFTWARE_SYSTEMS


def overlay(ov=AI, owner=R, basis=OverlayOwnershipBasis.SINGLE_TRACK_PROJECT, served=None,
            materiality=OverlayMateriality.MATERIAL_TO_TARGET, gaps=(), claims=(CLAIM,)):
    material = materiality is OverlayMateriality.MATERIAL_TO_TARGET
    return OverlayAssignment(
        methodology_run_id=RUN, overlay=ov, signal_domains=[TechnicalDomain.MACHINE_LEARNING],
        materiality=materiality, material_claim_ids=list(claims) if material else [],
        material_gap_hypothesis_ids=list(gaps), excerpt_ids=[X_OUTCOME.excerpt_id] if material else [],
        owner_track=owner, ownership_basis=basis,
        served_tracks=([owner] if owner else []) if served is None else served,
    )


def eng_track(*extra_apps, docs=()):
    kinds = (K.DESIGN_OBJECTIVE, K.REQUIREMENTS, K.ARCHITECTURE_SUBSYSTEM_PLAN, K.VERIFICATION_PLAN,
             K.VALIDATION_PLAN, K.MEASUREMENT_PLAN, K.ACCEPTANCE_CRITERIA)
    return track(E, apps=[*(app(k, E) for k in kinds), *extra_apps],
                 docs=[*(doc(k, E) for k in kinds), *docs], coverage=[link(kinds=(K.VALIDATION_PLAN,), track=E)])


def research_with(*extra_apps, docs=(), coverage=None):
    base = well_research_track()
    return track(apps=[*base.applicability, *extra_apps], docs=[*base.documentation, *docs],
                 coverage=base.coverage if coverage is None else coverage)


# -- 1. overlay ownership -------------------------------------------------------


def test_engineering_only_ai_project_receives_ai_ml_requirements():
    eng = tracks_for(ProjectType.ENGINEERING_PROJECT)
    assert resolve_applicability(K.TEST_SET_ISOLATION_FROM_TUNING, eng, {AI: E}, frozenset()) == (
        E, Applicability.REQUIRED, ApplicabilityBasis.CATALOG_DEFAULT)
    t = eng_track(app(K.TEST_SET_ISOLATION_FROM_TUNING, E))
    assert t.posture is MethodologyPosture.METHODOLOGY_HAS_MAJOR_DESIGN_GAPS  # required and not documented
    r = run(ProjectType.ENGINEERING_PROJECT, [t], overlays=[overlay(owner=E)])
    assert r.overlays[0].counts_in is E


def test_scientific_research_ai_project_receives_ai_ml_requirements():
    research = tracks_for(ProjectType.SCIENTIFIC_RESEARCH)
    assert resolve_applicability(K.TEST_SPLIT, research, {AI: R}, frozenset())[:2] == (R, Applicability.REQUIRED)
    r = run(tracks_=[research_with(app(K.TEST_SPLIT))], overlays=[overlay()])
    assert r.assessment_for(R).posture is MethodologyPosture.METHODOLOGY_HAS_MAJOR_DESIGN_GAPS


def test_overlay_is_never_activated_or_owned_by_domain_alone():
    with pytest.raises(ValidationError, match="domain alone"):
        OverlayAssignment(methodology_run_id=RUN, overlay=AI, signal_domains=[TechnicalDomain.MACHINE_LEARNING],
                          materiality=OverlayMateriality.MATERIAL_TO_TARGET, owner_track=R,
                          ownership_basis=OverlayOwnershipBasis.SINGLE_TRACK_PROJECT, served_tracks=[R])
    tool = overlay(owner=None, basis=OverlayOwnershipBasis.NOT_MATERIAL,
                   materiality=OverlayMateriality.IMPLEMENTATION_TOOL_ONLY, served=[])
    assert tool.counts_in is None and not tool.blocks_well_specified
    assert resolve_applicability(K.TEST_SPLIT, (R,), {}, frozenset())[1] is Applicability.NOT_APPLICABLE
    assert not hasattr(mr, "overlay_track"), "no blanket 'research when present' rule"


def test_hybrid_ai_requirement_cannot_be_assigned_to_the_wrong_track():
    target = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, limitation_facets=[GapFacet.ENGINEERING])
    hybrid = [well_research_track(), eng_track()]
    with pytest.raises(ValidationError, match="facet"):
        run(ProjectType.HYBRID, hybrid, gap_targets=[target],
            overlays=[overlay(owner=R, basis=OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET, gaps=[HYP])])
    with pytest.raises(ValidationError, match="single-track"):
        run(ProjectType.HYBRID, hybrid, overlays=[overlay(owner=R)])
    owned = overlay(owner=E, basis=OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET, gaps=[HYP])
    with pytest.raises(ValidationError, match="owner track"):
        run(ProjectType.HYBRID, [research_with(app(K.TEST_SPLIT)), eng_track()], gap_targets=[target],
            overlays=[owned])
    right = eng_track(app(K.TEST_SPLIT, E), docs=[doc(K.TEST_SPLIT, E)])
    r = run(ProjectType.HYBRID, [well_research_track(), right], gap_targets=[target], overlays=[owned])
    assert r.overlays[0].counts_in is E


def test_hybrid_overlay_requirement_is_not_double_counted():
    shared = overlay(owner=E, basis=OverlayOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT, served=[R, E])
    with pytest.raises(ValidationError, match="owner track"):
        run(ProjectType.HYBRID, [research_with(app(K.TEST_SPLIT)), eng_track(app(K.TEST_SPLIT, E))],
            overlays=[shared])
    # the served, non-owner track may cite the owner's documented requirement without counting it
    cite = research_with(coverage=[link(kinds=(K.MEASUREMENT_METHOD, K.TEST_SPLIT))])
    eng = eng_track(app(K.TEST_SPLIT, E), docs=[doc(K.TEST_SPLIT, E)])
    r = run(ProjectType.HYBRID, [cite, eng], overlays=[shared])
    counted = [a.track for ta in r.track_assessments for a in ta.applicability if a.kind is K.TEST_SPLIT]
    assert counted == [E]
    # a track that is not served cannot borrow it
    unserved = overlay(owner=E, basis=OverlayOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT, served=[E])
    with pytest.raises(ValidationError, match="strong coverage"):
        run(ProjectType.HYBRID, [cite, eng], overlays=[unserved])


def test_hybrid_unresolved_ownership_stays_conditional_and_blocks_well_specified():
    assert resolve_applicability(K.TEST_SPLIT, (R, E), {AI: None}, frozenset()) == (
        None, Applicability.CONDITIONAL, ApplicabilityBasis.OVERLAY_OWNERSHIP_UNRESOLVED)
    unresolved = overlay(owner=None, basis=OverlayOwnershipBasis.UNRESOLVED, served=[R, E])
    assert unresolved.blocks_well_specified and unresolved.counts_in is None
    with pytest.raises(ValidationError, match="forbids a well-specified"):
        run(ProjectType.HYBRID, [well_research_track(), eng_track()], overlays=[unresolved])


def test_software_overlay_without_an_engineering_track_is_owned_by_research():
    research = tracks_for(ProjectType.SCIENTIFIC_RESEARCH)
    fired = frozenset({ApplicabilityTrigger.SECURITY_CLAIMED})
    assert resolve_applicability(K.SECURITY_VALIDATION_PLAN, research, {SW: R}, fired)[:2] == (
        R, Applicability.REQUIRED)
    assert run(overlays=[overlay(ov=SW, owner=R)]).overlays[0].counts_in is R
    with pytest.raises(ValidationError, match="does not have"):
        run(overlays=[overlay(ov=SW, owner=E)])


# -- 2. exact Phase 2J validation-requirement continuity -----------------------


def gap_world(target, *, metrics=(), baselines=(), conditions=()):
    base = well_research_track()
    t = track(apps=base.applicability, docs=base.documentation, coverage=[link(hyp=HYP)], conditions=list(conditions))
    return run(tracks_=[t], gap_targets=[target], metrics=list(metrics), baselines=list(baselines))


def relevant_baseline(req=VREQ):
    return BaselineComparatorRecord(
        record_id=methodology_id(RUN, "baseline"), methodology_run_id=RUN, target_claim_id=CLAIM,
        gap_validation_requirement_id=req, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
        relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
        relevance_context=[BaselineRelevanceContext.PHASE_2J_VALIDATION_BASELINE],
    )


def test_bound_target_mirrors_the_actual_phase_2j_requirement():
    from tests.test_phase2j_contracts import _full_hypothesis

    h = _full_hypothesis()
    t = BoundGapTarget.from_hypothesis(h)
    req = h.validation_requirement
    assert (t.validation_requirement_id, t.requires_metric) == (req.requirement_id, True)
    assert t.requires_baseline is False and req.baseline is None
    assert t.material_condition_ids == req.condition_ids
    assert t.limitation_facets == [GapFacet.ENGINEERING]
    none = BoundGapTarget.from_hypothesis(h.model_copy(update={"validation_requirement": None}))
    assert (none.requires_metric, none.requires_baseline, none.material_condition_ids) == (False, False, [])
    with pytest.raises(ValidationError):
        BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, requires_baseline=True)
    with pytest.raises(ValidationError):  # Phase 2J's metric is mandatory, so it cannot be dropped
        BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ)


def test_required_phase_2j_metric_cannot_be_omitted():
    target = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ, requires_metric=True)
    with pytest.raises(ValidationError, match="required metric"):
        gap_world(target, metrics=[aligned_metric()])  # aligned, but not to the Phase 2J metric
    assert gap_world(target, metrics=[req_metric()]).status is MethodologyRunStatus.COMPLETED


def test_required_phase_2j_baseline_cannot_be_omitted():
    target = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ,
                            requires_metric=True, requires_baseline=True)
    with pytest.raises(ValidationError, match="required baseline"):
        gap_world(target, metrics=[req_metric()])
    assert gap_world(target, metrics=[req_metric()], baselines=[relevant_baseline()]).status


def test_required_phase_2j_material_condition_cannot_be_ignored():
    target = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ,
                            requires_metric=True, material_condition_ids=[COND])
    with pytest.raises(ValidationError, match="material condition"):
        gap_world(target, metrics=[req_metric()])


def test_phase_3a_invents_no_dimension_the_phase_2j_requirement_does_not_require():
    no_baseline = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ,
                                 requires_metric=True)
    assert gap_world(no_baseline, metrics=[req_metric()]).status  # no baseline demanded
    no_requirement = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM)
    assert gap_world(no_requirement).status  # no metric, baseline or condition invented


def test_structural_binding_without_semantic_coverage_is_insufficient():
    target = BoundGapTarget(gap_hypothesis_id=HYP, claim_id=CLAIM, validation_requirement_id=VREQ,
                            requires_metric=True, requires_baseline=True)
    bound_only = MetricAlignment(  # bound to the requirement by id, with no metric plan behind it
        record_id=methodology_id(RUN, "bound-only"), methodology_run_id=RUN, target_claim_id=CLAIM,
        gap_validation_requirement_id=VREQ, status=MetricAlignmentStatus.METRIC_NOT_DEFINED)
    with pytest.raises(ValidationError, match="required metric"):
        gap_world(target, metrics=[bound_only], baselines=[relevant_baseline()])
    with pytest.raises(ValidationError, match="required metric"):
        gap_world(target, metrics=[req_metric(MetricAlignmentStatus.METRIC_TARGET_MISMATCH)],
                  baselines=[relevant_baseline()])
    unresolved = relevant_baseline().model_copy(update={"relevance": BaselineRelevance.RELEVANCE_UNRESOLVED})
    with pytest.raises(ValidationError, match="required baseline"):
        gap_world(target, metrics=[req_metric()], baselines=[unresolved])
    with pytest.raises(ValidationError, match="cross-claim"):
        gap_world(target, metrics=[req_metric(req=methodology_id("foreign", "req"))])


# -- 3. baseline relevance and rationale -----------------------------------------

BASE = dict(record_id=RUN, methodology_run_id=RUN, target_claim_id=CLAIM)


def test_baseline_can_be_documented_without_relevance_established():
    b = BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
                                 relevance=BaselineRelevance.RELEVANCE_UNRESOLVED)
    assert b.baseline_excerpt_ids and not b.rationale_documented
    assert run(baselines=[b]).baselines[0].relevance is BaselineRelevance.RELEVANCE_UNRESOLVED


def test_relevance_needs_permitted_context_never_the_baseline_name_alone():
    with pytest.raises(ValidationError, match="name alone"):
        BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
                                 relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT)
    with pytest.raises(ValidationError):
        BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
                                 relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
                                 relevance_context=["BASELINE_NAME"])
    assert "BASELINE_NAME" not in {c.name for c in BaselineRelevanceContext}
    via_claim = BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
                                         relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
                                         relevance_context=[BaselineRelevanceContext.TARGET_CLAIM_TEXT])
    assert not via_claim.rationale_documented, "relevance does not require a student rationale"


def test_student_rationale_supports_relevance_but_is_never_fabricated():
    with pytest.raises(ValidationError, match="never fabricated"):
        BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
                                 relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
                                 relevance_context=[BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT])
    with_rationale = BaselineComparatorRecord(
        **BASE, baseline_excerpt_ids=[X_BASELINE.excerpt_id],
        relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
        relevance_context=[BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT],
        rationale_excerpt_ids=[X_RELEVANCE.excerpt_id])
    assert with_rationale.rationale_documented
    fabricated = with_rationale.model_copy(update={"rationale_excerpt_ids": [methodology_id("made", "up")]})
    with pytest.raises(ValidationError, match="fabricated"):
        run(baselines=[fabricated])


def test_one_exact_excerpt_may_carry_both_baseline_and_rationale():
    both = excerpt("We compare against a threshold baseline because it is the method clinics use today.")
    b = BaselineComparatorRecord(**BASE, baseline_excerpt_ids=[both.excerpt_id],
                                 relevance=BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT,
                                 relevance_context=[BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT],
                                 rationale_excerpt_ids=[both.excerpt_id])
    assert run(excerpts=[*ALL_X, both], baselines=[b]).baselines[0].rationale_documented


def test_no_baseline_relevance_judgment_implies_fair_execution():
    b = relevant_baseline()
    assert b.comparison_fairness_assessed is False
    with pytest.raises(ValidationError):
        BaselineComparatorRecord.model_validate({**b.model_dump(), "comparison_fairness_assessed": True})
    assert not any("FAIR" in m.name or "EXECUTED" in m.name for m in BaselineRelevance)
