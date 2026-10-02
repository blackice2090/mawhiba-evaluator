"""Phase 2J evidence semantics: exact anchors, admissible limitations, source quality,
fabrication, invented metrics, prompt injection as inert data. Pipeline level, real
upstream graphs, scripted untrusted model."""

from __future__ import annotations

import pytest

from src.evals.research_engineering_gap.fixtures import (
    BATTERY,
    CAPABILITY,
    CLAIM,
    CLAIMS,
    NIGHT,
    ND_SCRIPT,
    RICH_PATENT,
    UNTESTED,
    link_to,
    rich_extract,
    script,
)
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.llm.prompts import GAP_CANDIDATE_EXTRACTION_PROMPT_V1
from src.schemas.gap_assessment import (
    GapIssueCode,
    GapPosture,
    InadmissibleLimitationBasis,
    OccurrenceResolution,
    SourceQualityVerdict,
)

LINK_NIGHT = link_to((NIGHT, "ADDRESSES_LIMITATION"))


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-902", CLAIMS, patent=RICH_PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def _run(upstream, extract, link=None, counter=None):
    model = ScriptedGapModel({"C-001": CLAIM}, script(extract=extract, link=link or LINK_NIGHT, counter=counter))
    state = run_phase2j(upstream, model.provider())
    return model, state.active_research_run.research_engineering_gap


def _reasons(gap) -> list[str]:
    return [r.reason for r in gap.rejected_proposals]


def test_exact_excerpt_binds_with_a_validated_unique_span(upstream):
    _, gap = _run(upstream, rich_extract(NIGHT))
    (ref,) = [r for r in gap.hypotheses[0].evidence_refs if r.role.value == "LIMITATION"]
    assert ref.excerpt == "Accuracy drops to 61% at night"
    assert ref.occurrence_resolution is OccurrenceResolution.UNIQUE_IN_TEXT
    assert not gap.rejected_proposals


def test_fabricated_excerpt_is_rejected_and_never_becomes_a_gap(upstream):
    fabricated = {**NIGHT, "excerpt": "Accuracy drops to 12% at midday"}
    _, gap = _run(upstream, rich_extract(fabricated))
    assert not gap.hypotheses
    assert "EXCERPT_NOT_IN_TEXT" in _reasons(gap)
    assert any(e.code is GapIssueCode.FABRICATED_ANCHOR for e in gap.errors)
    assert gap.claim_assessments[0].posture is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP


def test_student_claim_text_is_never_evidence(upstream):
    claim_as_source = {**NIGHT, "excerpt": "weather forecasts", "type": "EXPLICIT_LIMITATION", "facet": "RESEARCH",
                       "in": "ACADEMIC_EXCERPT"}
    _, gap = _run(upstream, rich_extract(claim_as_source))
    assert not gap.hypotheses
    assert "CLAIM_TEXT_AS_EVIDENCE" in _reasons(gap)


@pytest.mark.parametrize("basis", [b.value for b in InadmissibleLimitationBasis])
def test_absence_type_basis_is_refused_and_recorded(upstream, basis):
    _, gap = _run(upstream, rich_extract({**NIGHT, "type": basis}))
    assert not gap.hypotheses
    rejected = [r for r in gap.rejected_proposals if r.reason == "INADMISSIBLE_LIMITATION_BASIS"]
    assert rejected and rejected[0].inadmissible_basis is InadmissibleLimitationBasis(basis)


def test_repeated_excerpt_needs_a_validated_disambiguator(upstream):
    repeated = {"label": "L2", "type": "UNRESOLVED_QUESTION", "facet": "RESEARCH", "excerpt": "arid farms",
                "in": "PATENT_DESCRIPTION"}
    _, rejected = _run(upstream, rich_extract(repeated))
    assert "AMBIGUOUS_REPEATED_EXCERPT" in _reasons(rejected) and not rejected.hypotheses
    assert any(e.code is GapIssueCode.AMBIGUOUS_ANCHOR for e in rejected.errors)
    _, second = _run(upstream, rich_extract({**repeated, "occurrence": 2}))
    (ref,) = [r for r in second.hypotheses[0].evidence_refs if r.role.value == "LIMITATION"]
    assert ref.occurrence_resolution is OccurrenceResolution.VALIDATED_OCCURRENCE_INDEX
    assert (ref.occurrence_index, ref.occurrence_count) == (2, 2)
    _, bad = _run(upstream, rich_extract({**repeated, "occurrence": 9}))
    assert "INVALID_OCCURRENCE_INDEX" in _reasons(bad)
    _, offsets = _run(upstream, rich_extract({**repeated, "start": 3, "end": 13}))
    assert "INVALID_OFFSETS" in _reasons(offsets)


def test_measured_shortfall_without_a_number_is_refused(upstream):
    _, gap = _run(upstream, rich_extract({**BATTERY, "type": "MEASURED_SHORTFALL"}))
    assert not gap.hypotheses and "MEASURED_SHORTFALL_WITHOUT_NUMBER" in _reasons(gap)


def test_facet_must_fit_the_limitation_type(upstream):
    _, gap = _run(upstream, rich_extract({**UNTESTED, "facet": "ENGINEERING"}))
    assert not gap.hypotheses and "FACET_INELIGIBLE_FOR_TYPE" in _reasons(gap)


def test_title_text_is_never_limitation_evidence(upstream):
    in_title = {**NIGHT, "excerpt": "accuracy drops to 61% at night", "in": "PATENT_TITLE"}
    _, gap = _run(upstream, rich_extract(in_title))
    (hypothesis,) = gap.hypotheses
    (ref,) = [r for r in hypothesis.evidence_refs if r.role.value == "LIMITATION"]
    assert ref.source_quality is SourceQualityVerdict.INELIGIBLE_METADATA_TEXT
    assert hypothesis.posture is GapPosture.BLOCKED_SOURCE_QUALITY
    assert gap.claim_assessments[0].posture is GapPosture.BLOCKED_SOURCE_QUALITY


def test_capability_cannot_be_inferred_from_a_title(upstream):
    title_capability = {"label": "C1", "excerpt": "Irrigation accuracy drops to 61% at night", "in": "PATENT_TITLE"}
    _, gap = _run(upstream, rich_extract(NIGHT, capabilities=[title_capability]))
    assert "INELIGIBLE_SOURCE_FOR_ROLE" in _reasons(gap)
    assert not gap.hypotheses[0].existing_capabilities
    assert gap.hypotheses[0].posture is GapPosture.PARTIALLY_SUPPORTED


def test_invented_metric_is_refused_and_the_gap_stays_partial(upstream):
    extract = rich_extract(NIGHT, validation={"metric_source": "L1", "metric": "F1 at least 0.95"})
    _, gap = _run(upstream, extract)
    assert "INVENTED_METRIC" in _reasons(gap)
    assert any(e.code is GapIssueCode.INVENTED_METRIC for e in gap.errors)
    hypothesis = gap.hypotheses[0]
    assert hypothesis.validation_requirement is None
    assert hypothesis.posture is GapPosture.PARTIALLY_SUPPORTED


def test_metric_and_baseline_come_from_the_claim_or_verified_excerpts(upstream):
    validation = {"metric_source": "L1", "metric": "Accuracy", "baseline_source": "C1", "baseline": "94%"}
    _, gap = _run(upstream, rich_extract(NIGHT, validation=validation))
    requirement = gap.hypotheses[0].validation_requirement
    assert requirement.metric.origin.value == "LIMITATION_EVIDENCE" and requirement.baseline.text == "94%"
    claim_metric = {"metric_source": "CLAIM", "metric": "soil moisture sensors"}
    _, from_claim = _run(upstream, rich_extract(NIGHT, validation=claim_metric))
    assert from_claim.hypotheses[0].validation_requirement.metric.origin.value == "STUDENT_CLAIM_TEXT"
    invented_threshold = {"metric_source": "CLAIM", "metric": "95% accuracy"}
    _, none = _run(upstream, rich_extract(NIGHT, validation=invented_threshold))
    assert none.hypotheses[0].validation_requirement is None and "INVENTED_METRIC" in _reasons(none)


def test_duplicate_proposition_is_refused_not_double_counted(upstream):
    duplicate = {**NIGHT, "label": "L9"}
    _, gap = _run(upstream, rich_extract(NIGHT, duplicate))
    assert len(gap.hypotheses[0].limitations) == 1 and "DUPLICATE_PROPOSITION" in _reasons(gap)


def test_bounds_cap_the_number_of_accepted_limitations(upstream):
    from src.schemas.gap_assessment import GapAssessmentBounds

    model = ScriptedGapModel({"C-001": CLAIM}, script(extract=rich_extract(NIGHT, UNTESTED, BATTERY), link=LINK_NIGHT))
    state = run_phase2j(upstream, model.provider(), bounds=GapAssessmentBounds(max_limitations_per_claim=1))
    gap = state.active_research_run.research_engineering_gap
    assert len(gap.hypotheses[0].limitations) == 1 and "BOUND_EXCEEDED" in _reasons(gap)


def test_manifests_titles_and_repository_metadata_are_never_limitation_sources():
    """Stale-semantics regression: structured package metadata cannot state a limitation."""
    from src.research.gap.inventory import prior_art_quality
    from src.schemas.novelty_differentiation import DisclosureCapacity, TextKind

    for kind in (TextKind.OSS_MANIFEST, TextKind.PATENT_TITLE, TextKind.PRODUCT_PAGE_TITLE, TextKind.OSS_DESCRIPTION,
                 TextKind.OSS_TOPICS, TextKind.OSS_RELEASE_METADATA):
        for capacity in DisclosureCapacity:
            assert prior_art_quality(kind, capacity) is not SourceQualityVerdict.ELIGIBLE
    assert prior_art_quality(TextKind.PATENT_DESCRIPTION, DisclosureCapacity.MATERIAL) is SourceQualityVerdict.ELIGIBLE
    assert prior_art_quality(TextKind.OSS_README, DisclosureCapacity.LIMITED) is SourceQualityVerdict.ELIGIBLE
    assert prior_art_quality(TextKind.PATENT_DESCRIPTION, DisclosureCapacity.NON_MATERIAL) is not SourceQualityVerdict.ELIGIBLE
