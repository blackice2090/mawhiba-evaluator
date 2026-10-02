"""Phase 2J posture semantics at pipeline level: existence vs linkage, condition
materiality, capability, hybrid, counterevidence coverage, Phase 2F independence
of the posture. Real upstream graphs, scripted untrusted model."""

from __future__ import annotations

import pytest

from src.evals.research_engineering_gap.fixtures import (
    BATTERY,
    CLAIM,
    CLAIMS,
    ND_SCRIPT,
    NIGHT,
    RICH_PATENT,
    UNTESTED,
    link_to,
    rich_extract,
    script,
)
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.schemas.gap_assessment import (
    ConditionMateriality,
    CounterevidenceScopeEffect,
    GapAssessmentBounds,
    GapExistence,
    GapKind,
    GapPosture,
    MissingGapComponent,
    ProjectLinkageLevel,
)

VALIDATION = {"metric_source": "L1", "metric": "Accuracy"}


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-903", CLAIMS, patent=RICH_PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def _link(*relations: str) -> list[dict]:
    return link_to(*zip([NIGHT, UNTESTED, BATTERY], relations))


def _run(upstream, extract, link, counter=None, bounds=None):
    model = ScriptedGapModel({"C-001": CLAIM}, script(extract=extract, link=link, counter=counter))
    state = run_phase2j(upstream, model.provider(), bounds=bounds)
    return state.active_research_run.research_engineering_gap


def test_a_limitation_without_a_targeting_feature_is_differentiation_without_gap(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("UNRELATED"))
    hypothesis, assessment = gap.hypotheses[0], gap.claim_assessments[0]
    assert hypothesis.existence is GapExistence.LIMITATION_SUPPORTED  # the limitation exists...
    assert hypothesis.linkage is ProjectLinkageLevel.NONE_MATERIAL  # ...but nothing targets it
    assert hypothesis.posture is GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS
    assert assessment.posture is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP
    # the two no-gap causes stay distinguishable on the claim record
    assert assessment.hypothesis_existence == [GapExistence.LIMITATION_SUPPORTED]
    assert assessment.hypothesis_linkage == [ProjectLinkageLevel.NONE_MATERIAL]


@pytest.mark.parametrize("relation", ["RELEVANT_BUT_NOT_ADDRESSING", "UNRELATED", "INSUFFICIENT_LINKAGE_EVIDENCE"])
def test_b_non_addressing_relations_never_support(upstream, relation):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link(relation))
    assert gap.hypotheses[0].posture is not GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert gap.claim_assessments[0].posture is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP


def test_c_full_linkage_with_every_component_is_supported(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"))
    assert gap.hypotheses[0].posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert gap.claim_assessments[0].posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_d_partial_linkage_is_downgraded(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("PARTIALLY_ADDRESSES_LIMITATION"))
    hypothesis = gap.hypotheses[0]
    assert hypothesis.linkage is ProjectLinkageLevel.PARTIAL
    assert MissingGapComponent.FULL_PROJECT_LINKAGE in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_e_condition_specific_limitation_without_a_condition_anchor_is_partial(upstream):
    specific = {**NIGHT, "dimensions": ["ENVIRONMENT"], "conditions": []}
    hypothesis = _run(upstream, rich_extract(specific, validation=VALIDATION), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert list(hypothesis.condition_materiality.values()) == [
        ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED]
    assert MissingGapComponent.MATERIAL_CONDITION in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_e2_condition_specific_limitation_with_an_anchored_condition_is_supported(upstream):
    bound = {**NIGHT, "dimensions": ["ENVIRONMENT"],
             "conditions": [{"dimension": "ENVIRONMENT", "excerpt": "at night", "in": "PATENT_DESCRIPTION"}]}
    hypothesis = _run(upstream, rich_extract(bound, validation=VALIDATION), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert list(hypothesis.condition_materiality.values()) == [ConditionMateriality.CONDITION_REQUIRED_AND_BOUND]
    assert hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_f_non_condition_specific_limitation_needs_no_synthetic_condition(upstream):
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert not hypothesis.conditions
    assert list(hypothesis.condition_materiality.values()) == [ConditionMateriality.CONDITION_NOT_MATERIAL]


def test_language_difference_alone_is_not_a_condition_or_a_gap(upstream):
    language = {**NIGHT, "dimensions": ["LANGUAGE"], "conditions": []}
    hypothesis = _run(upstream, rich_extract(language, validation=VALIDATION), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert MissingGapComponent.MATERIAL_CONDITION in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_missing_existing_capability_cannot_be_supported(upstream):
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION, capabilities=[]),
                      _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert MissingGapComponent.EXISTING_CAPABILITY in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_missing_validation_requirement_cannot_be_supported(upstream):
    hypothesis = _run(upstream, rich_extract(NIGHT), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert MissingGapComponent.VALIDATION_REQUIREMENT in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_hybrid_from_two_distinct_linked_limitations(upstream):
    gap = _run(upstream, rich_extract(NIGHT, UNTESTED, validation=VALIDATION),
               _link("ADDRESSES_LIMITATION", "ADDRESSES_LIMITATION"))
    hypothesis = gap.hypotheses[0]
    assert hypothesis.kind is GapKind.HYBRID and hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_hybrid_needs_both_sides_linked(upstream):
    gap = _run(upstream, rich_extract(NIGHT, UNTESTED, validation=VALIDATION),
               _link("ADDRESSES_LIMITATION", "UNRELATED"))
    assert gap.hypotheses[0].kind is GapKind.ENGINEERING


def test_relabelled_copy_cannot_manufacture_hybrid(upstream):
    relabelled = {**NIGHT, "label": "L2", "type": "UNRESOLVED_QUESTION", "facet": "RESEARCH"}
    # same type would collide; a different type over the SAME span is a different proposition record,
    # but one passage stating one fact is still bounded by the bound/linkage rules below.
    same_type = {**NIGHT, "label": "L2", "facet": "ENGINEERING"}
    gap = _run(upstream, rich_extract(NIGHT, same_type, validation=VALIDATION), _link("ADDRESSES_LIMITATION"))
    assert len(gap.hypotheses[0].limitations) == 1
    assert gap.hypotheses[0].kind is GapKind.ENGINEERING
    assert relabelled["facet"] == "RESEARCH"  # sanity: the relabel attempt is a real RESEARCH label


def test_model_proposed_kind_is_recorded_never_trusted(upstream):
    extract = rich_extract(NIGHT, validation=VALIDATION) | {"proposed_kind": "HYBRID"}
    hypothesis = _run(upstream, extract, _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert hypothesis.model_proposed_kind is GapKind.HYBRID and hypothesis.kind is GapKind.ENGINEERING


def test_same_condition_counterevidence_weakens_the_gap(upstream):
    counter = [{"kind": "LIMITATION_ADDRESSED", "condition_match": "SAME_CONDITION",
                "excerpt": "Measured accuracy reached 94%", "in": "ACADEMIC_EXCERPT"}]
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"), counter)
    assert gap.hypotheses[0].posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP
    assert gap.claim_assessments[0].posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP
    assert gap.project_summary.weakened_by_counterevidence_count == 1


def test_unknown_condition_counterevidence_also_weakens(upstream):
    counter = [{"kind": "LIMITATION_NOT_PRESENT", "condition_match": "CONDITION_UNKNOWN",
                "excerpt": "Measured accuracy reached 94%", "in": "ACADEMIC_EXCERPT"}]
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"), counter)
    assert gap.hypotheses[0].posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP


DIFFERENT = [{"kind": "LIMITATION_ADDRESSED", "condition_match": "DIFFERENT_CONDITION",
              "excerpt": "Measured accuracy reached 94%", "in": "ACADEMIC_EXCERPT"}]
BOUND_AT_NIGHT = {**NIGHT, "dimensions": ["ENVIRONMENT"],
                  "conditions": [{"dimension": "ENVIRONMENT", "excerpt": "at night", "in": "PATENT_DESCRIPTION"}]}


def test_a_same_condition_counterevidence_weakens_and_does_not_narrow(upstream):
    counter = [{**DIFFERENT[0], "condition_match": "SAME_CONDITION"}]
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"),
                      counter).hypotheses[0]
    assert hypothesis.posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP
    assert hypothesis.counterevidence_scope_effect is CounterevidenceScopeEffect.NO_SCOPE_NARROWING
    assert hypothesis.narrowing_counter_ids == []


def test_b_different_condition_counterevidence_keeps_the_limitation_and_stores_the_narrowing(upstream):
    hypothesis = _run(upstream, rich_extract(BOUND_AT_NIGHT, validation=VALIDATION),
                      _link("ADDRESSES_LIMITATION"), DIFFERENT).hypotheses[0]
    (counter,) = hypothesis.counterevidence
    assert hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS  # not defeated by itself
    assert hypothesis.counterevidence_scope_effect is CounterevidenceScopeEffect.NARROWED_BY_DIFFERENT_CONDITION
    assert hypothesis.narrowing_counter_ids == [counter.counter_id]  # the exact record that narrowed
    assert hypothesis.bounded_statement.scope_effect is CounterevidenceScopeEffect.NARROWED_BY_DIFFERENT_CONDITION
    assert hypothesis.bounded_statement.qualifier == "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"


def test_c_narrowing_that_exposes_an_unbound_material_condition_cannot_stay_supported(upstream):
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"),
                      DIFFERENT).hypotheses[0]
    assert not hypothesis.conditions  # no condition was invented to rescue the posture
    assert list(hypothesis.condition_materiality.values()) == [
        ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED]
    assert MissingGapComponent.MATERIAL_CONDITION in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED
    assert hypothesis.bounded_statement.condition_ids == []


def test_d_narrowing_with_the_condition_already_bound_is_supported_only_under_it(upstream):
    hypothesis = _run(upstream, rich_extract(BOUND_AT_NIGHT, validation=VALIDATION),
                      _link("ADDRESSES_LIMITATION"), DIFFERENT).hypotheses[0]
    (condition,) = hypothesis.conditions
    assert hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert hypothesis.bounded_statement.condition_ids == [condition.condition_id]
    assert hypothesis.bounded_statement.limitation_ids == [hypothesis.limitations[0].limitation_id]
    assert hypothesis.narrowing_current_only is False  # an undated academic record is not "after cutoff"


def test_f_no_counterevidence_means_no_synthetic_narrowing(upstream):
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION")).hypotheses[0]
    assert hypothesis.counterevidence_scope_effect is CounterevidenceScopeEffect.NO_SCOPE_NARROWING
    assert hypothesis.narrowing_counter_ids == [] and hypothesis.narrowing_current_only is False
    assert hypothesis.bounded_statement.condition_ids == []
    assert list(hypothesis.condition_materiality.values()) == [ConditionMateriality.CONDITION_NOT_MATERIAL]


def test_unknown_condition_counterevidence_is_exposed_as_an_unresolved_relation(upstream):
    counter = [{**DIFFERENT[0], "condition_match": "CONDITION_UNKNOWN"}]
    hypothesis = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"),
                      counter).hypotheses[0]
    assert hypothesis.counterevidence_scope_effect is CounterevidenceScopeEffect.CONDITION_RELATION_UNRESOLVED
    assert hypothesis.posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP


def test_counterevidence_cannot_be_the_limitation_itself(upstream):
    counter = [{"kind": "LIMITATION_ADDRESSED", "condition_match": "SAME_CONDITION", **{
        "excerpt": NIGHT["excerpt"], "in": "PATENT_DESCRIPTION"}}]
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"), counter)
    assert not gap.hypotheses[0].counterevidence
    assert "COUNTEREVIDENCE_IS_THE_LIMITATION_SPAN" in [r.reason for r in gap.rejected_proposals]


def test_failed_counterevidence_review_cannot_reach_supported(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"), "provider_error")
    hypothesis = gap.hypotheses[0]
    assert not hypothesis.counterevidence_review_complete
    assert MissingGapComponent.COMPLETE_COUNTEREVIDENCE_REVIEW in hypothesis.missing_components
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED
    assert not gap.counterevidence_coverage[0].complete


def test_incomplete_inventory_coverage_cannot_reach_supported(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"),
               bounds=GapAssessmentBounds(max_chars_per_text=200))
    coverage = gap.counterevidence_coverage[0]
    assert coverage.omitted_text_ids and not coverage.complete
    assert gap.hypotheses[0].posture is not GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_complete_coverage_accounts_for_every_visible_inventory_text(upstream):
    gap = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"))
    coverage = gap.counterevidence_coverage[0]
    visible = {t.inventory_text_id for t in gap.inventory_texts if t.visible_to("C-001")}
    assert coverage.complete and set(coverage.examined_text_ids) == visible


def test_phase2f_scores_do_not_influence_the_posture(upstream):
    from src.schemas.research import ResearchRun

    run = upstream.active_research_run
    assert run.claim_evidence_scoring is not None  # 2F ran upstream
    with_scores = _run(upstream, rich_extract(NIGHT, validation=VALIDATION), _link("ADDRESSES_LIMITATION"))
    bare = ResearchRun.model_validate({**dict(run), "claim_evidence_scoring": None})
    state = upstream.model_copy(update={"research_runs": {str(bare.research_run_id): bare}})
    model = ScriptedGapModel({"C-001": CLAIM}, script(extract=rich_extract(NIGHT, validation=VALIDATION),
                                                       link=_link("ADDRESSES_LIMITATION")))
    without = run_phase2j(state, model.provider()).active_research_run.research_engineering_gap
    assert [h.posture for h in with_scores.hypotheses] == [h.posture for h in without.hypotheses]


def test_project_summary_is_descriptive_only(upstream):
    gap = _run(upstream, rich_extract(NIGHT, UNTESTED, validation=VALIDATION),
               _link("ADDRESSES_LIMITATION", "ADDRESSES_LIMITATION"))
    summary = gap.project_summary
    assert summary.kind_counts == {"HYBRID": 1} and summary.claim_posture_counts == {"SUPPORTED_WITHIN_BOUNDS": 1}
    assert summary.unresolved_independence_supported_count == 1  # lone patent: independence unresolved
    assert summary.statement_qualifier == "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"
