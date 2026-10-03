"""Phase 2J independence and chronology: both inherited from Phase 2I, never recomputed.

Several publications of one verified family are one corroboration unit; an
unresolved family never corroborates; chronology sits in its own records and
proves neither historical publicity nor legal prior art.
"""

from __future__ import annotations

import pytest

from src.evals.research_engineering_gap.fixtures import CLAIM, CLAIMS, ND_SCRIPT, link_to, rich_extract, script
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.schemas.gap_assessment import GapCorroborationLevel, GapPosture, GapScope
from src.schemas.novelty_differentiation import ChronologyBucket, IndependenceUnitKind


def _record(ref: str, description: str, family: str | None, date: str = "2015-06-01") -> dict:
    return {"reference": ref, "title": "Irrigation", "publication_date": date, "abstract": "abs",
            "claims": "1. A controller using soil moisture sensors to irrigate.", "description": description,
            **({"family": family} if family else {})}


A1 = {"label": "L1", "type": "MEASURED_SHORTFALL", "facet": "ENGINEERING", "excerpt": "Accuracy drops to 61% at night"}
A2 = {"label": "L2", "type": "MEASURED_SHORTFALL", "facet": "ENGINEERING", "excerpt": "Recall falls to 40% at night"}
B1 = {"label": "L3", "type": "MEASURED_SHORTFALL", "facet": "ENGINEERING", "excerpt": "Latency rises to 900 ms at night"}
U1 = {"label": "L4", "type": "MEASURED_SHORTFALL", "facet": "ENGINEERING", "excerpt": "Energy use reaches 12 W at night"}
PATENTS = {"records": [
    _record("EP.2000001.A1", f"Works with soil moisture sensors. {A1['excerpt']}.", "7"),
    _record("EP.2000002.B1", f"Works with soil moisture sensors. {A2['excerpt']}.", "7"),
    _record("EP.2000003.A1", f"Works with soil moisture sensors. {B1['excerpt']}.", "8"),
    _record("EP.2000004.B1", "Works with soil moisture sensors. Nothing else is stated.", "8"),
    _record("EP.2000005.A1", f"Works with soil moisture sensors. {U1['excerpt']}.", "unavailable"),
]}
VALIDATION = {"metric_source": "CLAIM", "metric": "soil moisture sensors"}


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-905", CLAIMS, patent=PATENTS, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def _run(upstream, *limitations):
    link = link_to((limitations[0], "ADDRESSES_LIMITATION"))
    model = ScriptedGapModel({"C-001": CLAIM}, script(extract=rich_extract(*limitations, validation=VALIDATION), link=link))
    return run_phase2j(upstream, model.provider()).active_research_run.research_engineering_gap


def _units(gap) -> dict:
    return {t.independence_key: t for t in gap.inventory_texts if t.inherited_unit is not None}


def test_inventory_inherits_the_phase2i_units_unchanged(upstream):
    nd = upstream.active_research_run.novelty_differentiation
    expected = {p.independence_unit.unit_key: p.independence_unit for p in nd.candidate_profiles}
    gap = _run(upstream, A1)
    assert {k: t.inherited_unit for k, t in _units(gap).items()} == expected


def test_two_publications_of_one_verified_family_are_one_unit(upstream):
    gap = _run(upstream, A1, A2)
    hypothesis = gap.hypotheses[0]
    kinds = {t.inherited_unit.unit_kind for t in _units(gap).values()}
    assert IndependenceUnitKind.PATENT_FAMILY in kinds
    assert len(hypothesis.limitations) == 2
    assert hypothesis.corroboration is GapCorroborationLevel.SINGLE_SOURCE_DIRECT
    assert hypothesis.scope is GapScope.CANDIDATE_SET_BOUNDED


def test_two_verified_families_are_independent_corroboration(upstream):
    hypothesis = _run(upstream, A1, B1).hypotheses[0]
    assert hypothesis.corroboration is GapCorroborationLevel.MULTI_SOURCE_CORROBORATED


def test_an_unresolved_family_contributes_no_corroboration(upstream):
    alone = _run(upstream, U1).hypotheses[0]
    assert alone.corroboration is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
    with_family = _run(upstream, A1, U1).hypotheses[0]
    assert with_family.corroboration is GapCorroborationLevel.SINGLE_SOURCE_DIRECT  # the unresolved one adds nothing


def test_academic_evidence_without_a_phase2e_group_is_never_independent(upstream):
    """Phase 2E absent: nothing is inferred. ``model_copy`` skips the ResearchRun
    cross-check on purpose -- this isolates how Phase 2J treats the absence."""
    from datetime import UTC, datetime

    from src.research.gap import pipeline as gp
    from src.schemas.common import ProjectType
    from src.schemas.gap_assessment import GapAssessmentBounds

    state = upstream
    run = state.active_research_run.model_copy(update={"claim_sufficiency": None})
    claims = list(state.project.claims)
    model = ScriptedGapModel({"C-001": CLAIM}, script(
        extract=rich_extract({**A1, "excerpt": "Measured accuracy reached 94%", "in": "ACADEMIC_EXCERPT"},
                             validation=VALIDATION),
        link=link_to(({**A1, "excerpt": "Measured accuracy reached 94%"}, "ADDRESSES_LIMITATION"))))
    provider = model.provider()
    now = datetime.now(UTC)
    gap = gp.open_gap_run(run, claims, ProjectType.UNKNOWN, GapAssessmentBounds(), now)
    gap = gp.inventory_stage(gap, run)
    gap = gp.extraction_stage(gap, run, claims, provider, None)
    gap = gp.linkage_stage(gap, run, claims, provider, None)
    gap = gp.counterevidence_stage(gap, run, claims, provider, None)
    gap = gp.finalize_stage(gp.project_stage(gp.synthesis_stage(gap, run)), run, claims, now)
    academic = [t for t in gap.inventory_texts if t.source_kind.value == "ACADEMIC_EVIDENCE"]
    assert academic and all(not t.counts_as_independent for t in academic)
    assert all(t.independence_basis.value == "ACADEMIC_UNGROUPED" for t in academic)
    assert gap.hypotheses[0].corroboration is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
    assert gap.claim_assessments[0].posture is not GapPosture.INSUFFICIENT_INPUT  # absence alone is not insufficiency


def test_chronology_is_recorded_apart_from_support_and_proves_nothing(upstream):
    gap = _run(upstream, A1)
    notes = gap.hypotheses[0].chronology
    assert notes and {n.bucket for n in notes} == {ChronologyBucket.BEFORE_CUTOFF}
    assert all(n.upstream_basis == "PATENT_FIRST_PUBLIC_DATE" for n in notes)
    assert all(n.historical_publicity_inferred is False and n.legal_prior_art_established is False for n in notes)
    assert "historical_publicity_inferred" in gap.hypotheses[0].chronology[0].model_dump()
    assert not any("chronology" in name for name in type(gap.hypotheses[0].limitations[0]).model_fields)


def test_a_missing_cutoff_stays_no_cutoff_not_before_or_after():
    world = build_phase2i_world("PJ-906", CLAIMS, patent=PATENTS, cutoff=None, nd_script=ND_SCRIPT)
    gap = _run(world, A1)
    assert {n.bucket for n in gap.hypotheses[0].chronology} == {ChronologyBucket.NO_CUTOFF}


def test_later_counterevidence_weakens_only_the_current_posture():
    patents = {"records": [
        _record("EP.2000001.A1", f"Works with soil moisture sensors. {A1['excerpt']}.", "7", "2015-06-01"),
        _record("EP.2000002.B1", "Works with soil moisture sensors. Accuracy now stays above 95% at night.", "7",
                "2023-01-01"),
    ]}
    world = build_phase2i_world("PJ-907", CLAIMS, patent=patents, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)
    counter = [{"kind": "LIMITATION_ADDRESSED", "condition_match": "SAME_CONDITION",
                "excerpt": "Accuracy now stays above 95% at night"}]
    model = ScriptedGapModel({"C-001": CLAIM}, script(
        extract=rich_extract(A1, validation=VALIDATION), link=link_to((A1, "ADDRESSES_LIMITATION")), counter=counter))
    gap = run_phase2j(world, model.provider()).active_research_run.research_engineering_gap
    (hypothesis,) = gap.hypotheses
    (item,) = hypothesis.counterevidence
    assert item.chronology_bucket is ChronologyBucket.AFTER_CUTOFF
    assert item.temporal_effect.value == "WEAKENS_CURRENT_POSTURE_ONLY"
    assert hypothesis.posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP
    assert "legal" not in item.model_dump_json().casefold()


def test_after_cutoff_different_condition_counterevidence_is_a_current_scope_effect_only():
    patents = {"records": [
        _record("EP.2000001.A1", f"Works with soil moisture sensors. {A1['excerpt']}.", "7", "2015-06-01"),
        _record("EP.2000002.B1", "Works with soil moisture sensors. Accuracy now stays above 95% in daylight.", "7",
                "2023-01-01"),
    ]}
    world = build_phase2i_world("PJ-910", CLAIMS, patent=patents, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)
    counter = [{"kind": "LIMITATION_ADDRESSED", "condition_match": "DIFFERENT_CONDITION",
                "excerpt": "Accuracy now stays above 95% in daylight"}]
    model = ScriptedGapModel({"C-001": CLAIM}, script(
        extract=rich_extract(A1, validation=VALIDATION), link=link_to((A1, "ADDRESSES_LIMITATION")), counter=counter))
    hypothesis = run_phase2j(world, model.provider()).active_research_run.research_engineering_gap.hypotheses[0]
    (item,) = hypothesis.counterevidence
    assert hypothesis.narrowing_counter_ids == [item.counter_id]
    assert hypothesis.narrowing_current_only is True
    assert hypothesis.bounded_statement.narrowing_current_only is True
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED  # the narrowing exposed an unbound condition, now
    # chronology stays separate and unrewritten: the limitation's own note is still before the cutoff
    by_ref = {n.evidence_ref_id: n for n in hypothesis.chronology}
    limitation_ref = next(r.evidence_ref_id for r in hypothesis.evidence_refs if r.role.value == "LIMITATION")
    assert by_ref[limitation_ref].bucket is ChronologyBucket.BEFORE_CUTOFF
    assert by_ref[item.evidence_ref_ids[0]].bucket is ChronologyBucket.AFTER_CUTOFF
    assert all(n.historical_publicity_inferred is False and n.legal_prior_art_established is False
               for n in hypothesis.chronology)
    assert "chronology" not in type(hypothesis.bounded_statement).model_fields
