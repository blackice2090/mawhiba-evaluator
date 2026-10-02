"""Phase 2J architecture-gate contract tests.

Smallest, model-free checks that pin the gap-assessment semantics before any
pipeline exists:

1. absence, differentiation and student assertion can never be limitation evidence;
2. GapKind is derived from verified facets; HYBRID is never a fallback;
3. GapPosture is derived in code; the three "no gap" postures are distinct;
4. corroboration is inherited from 2E / 2I units, never recomputed or inflated;
5. scope is always bounded; no field-wide value exists;
6. counterevidence is material unless the condition differs;
7. chronology never becomes publicity or a legal conclusion;
8. anchors are exact; a repeated excerpt is never bound as unique;
9. the validation requirement has no threshold and only anchored metric text;
10. run binding, no new evidence, no search, no forbidden fields, checkpointable.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

import src.schemas.gap_assessment as gap_module
from src.graph.type_discovery import discover_types_from
from src.graph.workflow_state import EvaluationGraphState
from src.schemas.common import ProjectType
from src.schemas.gap_assessment import (
    FIELD_WIDE_DISCLAIMER,
    FORBIDDEN_FIELD_FRAGMENTS,
    ClaimGapAssessment,
    ConditionMateriality,
    CounterevidenceCoverage,
    ConditionDimension,
    ConditionMatch,
    CounterEvidenceKind,
    GapAssessmentRun,
    GapChronologyNote,
    GapCondition,
    GapCorroborationLevel,
    GapCounterEvidence,
    GapEvidenceRef,
    GapEvidenceRole,
    GapExistence,
    GapInventoryText,
    GapExistingCapability,
    GapFacet,
    GapHypothesis,
    GapKind,
    GapLimitation,
    GapLimitationType,
    GapPosture,
    GapProjectLink,
    GapScope,
    GapSourceKind,
    GapValidationRequirement,
    InadmissibleLimitationBasis,
    IndependenceBasis,
    LinkageRelation,
    MissingGapComponent,
    ProjectLinkageLevel,
    ProjectLinkStatus,
    SourceQualityVerdict,
    ValidationAnchor,
    ValidationAnchorOrigin,
    derive_claim_posture,
    derive_corroboration,
    derive_kind,
    derive_scope,
    materially_linked,
    link_status_for,
)
from src.schemas.novelty_differentiation import (
    CandidateType,
    ChronologyBucket,
    DifferentiationStatus,
    FeatureType,
    IndependenceUnit,
    IndependenceUnitKind,
    OccurrenceResolution,
    TextKind,
)

HASH = "a" * 64
RUN, GAP, ND = uuid4(), uuid4(), uuid4()
CLAIM = "C-001"
NOW = datetime(2026, 10, 2, tzinfo=UTC)


def _academic(role: GapEvidenceRole, excerpt: str = "accuracy drops to 61% in low light", *, key: str = "doi:10.1/a",
              grouped: bool = True, quality=SourceQualityVerdict.ELIGIBLE, review: bool = False, start: int = 0,
              count: int = 1, resolution=OccurrenceResolution.UNIQUE_IN_TEXT) -> GapEvidenceRef:
    return GapEvidenceRef(
        evidence_ref_id=uuid4(), source_kind=GapSourceKind.ACADEMIC_EVIDENCE, source_record_id=uuid4(),
        upstream_run_id=uuid4(), text_hash=HASH, excerpt=excerpt, start=start, end=start + len(excerpt),
        occurrence_count=count, occurrence_index=1, occurrence_resolution=resolution, role=role,
        independence_basis=IndependenceBasis.ACADEMIC_PHASE2E_GROUP if grouped else IndependenceBasis.ACADEMIC_UNGROUPED,
        independence_key=key, counts_as_independent=grouped, source_quality=quality, is_review_source=review,
    )


def _unit(kind: IndependenceUnitKind, key: str, ctype: CandidateType, corr: str | None = None) -> IndependenceUnit:
    return IndependenceUnit(
        candidate_type=ctype, unit_kind=kind, unit_key=key,
        counts_as_independent=kind not in {IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED,
                                           IndependenceUnitKind.OSS_DEPENDENT_NETWORK,
                                           IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY} or corr is not None,
        correlation_group_key=corr,
    )


def _prior_art(unit: IndependenceUnit, role=GapEvidenceRole.LIMITATION, excerpt: str = "fails above 40 C",
               text_kind=TextKind.PATENT_DESCRIPTION) -> GapEvidenceRef:
    return GapEvidenceRef(
        evidence_ref_id=uuid4(), source_kind=GapSourceKind.PRIOR_ART_TEXT, source_record_id=uuid4(),
        upstream_run_id=ND, candidate_id=uuid4(), text_kind=text_kind, text_hash=HASH, excerpt=excerpt,
        start=0, end=len(excerpt), occurrence_count=1, occurrence_index=1,
        occurrence_resolution=OccurrenceResolution.UNIQUE_IN_TEXT, role=role,
        independence_basis=IndependenceBasis.PRIOR_ART_PHASE2I_UNIT, independence_key=unit.unit_key,
        counts_as_independent=unit.counts_as_independent, correlation_group_key=unit.correlation_group_key,
        inherited_unit=unit, source_quality=SourceQualityVerdict.ELIGIBLE,
    )


LIM_ID = UUID("00000000-0000-0000-0000-00000000000a")


def _link(status=DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT, *, limitation_id: UUID = LIM_ID,
          relation: LinkageRelation = LinkageRelation.ADDRESSES_LIMITATION, feature_id: UUID | None = None):
    return GapProjectLink(
        link_id=uuid4(), claim_id=CLAIM, claim_text_hash=HASH, nd_run_id=ND, feature_id=feature_id or uuid4(),
        feature_text_hash=HASH, feature_type=FeatureType.MECHANISM, limitation_id=limitation_id,
        inherited_differentiation_status=status, status=link_status_for(status), relation=relation,
    )


SUPPORTED = dict(
    existence=GapExistence.LIMITATION_SUPPORTED, linkage=ProjectLinkageLevel.FULL,
    condition_materiality={str(LIM_ID): ConditionMateriality.CONDITION_REQUIRED_AND_BOUND},
    kind=GapKind.ENGINEERING, corroboration=GapCorroborationLevel.SINGLE_SOURCE_DIRECT,
    scope=GapScope.SINGLE_SOURCE_BOUNDED, missing_components=[], posture=GapPosture.SUPPORTED_WITHIN_BOUNDS,
)


def _full_hypothesis(**overrides):
    """A complete chain: capability, condition-specific limitation bound to its
    condition, a differentiating feature that ADDRESSES it, and a requirement."""
    cap = _academic(GapEvidenceRole.EXISTING_CAPABILITY, "detects pests with 92% accuracy")
    lim = _academic(GapEvidenceRole.LIMITATION)
    cond = _academic(GapEvidenceRole.CONDITION, "in low light")
    refs = [cap, lim, cond]
    condition = GapCondition(condition_id=uuid4(), dimension=ConditionDimension.ENVIRONMENT,
                             limitation_ids=[LIM_ID], evidence_ref_ids=[cond.evidence_ref_id])
    fields = dict(
        hypothesis_id=uuid4(), gap_run_id=GAP, research_run_id=RUN, claim_id=CLAIM, evidence_refs=refs,
        existing_capabilities=[GapExistingCapability(capability_id=uuid4(), evidence_ref_ids=[cap.evidence_ref_id])],
        limitations=[GapLimitation(limitation_id=LIM_ID, limitation_type=GapLimitationType.MEASURED_SHORTFALL,
                                   facet=GapFacet.ENGINEERING, evidence_ref_ids=[lim.evidence_ref_id],
                                   condition_dimensions=[ConditionDimension.ENVIRONMENT])],
        conditions=[condition],
        project_links=[_link()],
        validation_requirement=GapValidationRequirement(
            requirement_id=uuid4(),
            metric=ValidationAnchor(origin=ValidationAnchorOrigin.LIMITATION_EVIDENCE, text="accuracy",
                                    evidence_ref_id=lim.evidence_ref_id, start=0, end=8),
            condition_ids=[condition.condition_id],
        ),
        counterevidence_review_complete=True,
        **SUPPORTED,
    )
    fields.update(overrides)
    return GapHypothesis(**fields)


FILLED = ("counterevidence_scope_effect", "narrowing_counter_ids", "narrowing_current_only", "bounded_statement")


def _dump(h: GapHypothesis) -> dict:
    """A hypothesis as input, with the four fields the model fills in left unset
    (a changed hypothesis must recompute them, not carry the old values)."""
    return {**h.model_dump(), **{name: None for name in FILLED}}


def _rebuild(h: GapHypothesis, **changes) -> GapHypothesis:
    return GapHypothesis(**{**_dump(h), **changes})


# -- 1. absence / differentiation / student assertion are never evidence ------


def test_absence_bases_cannot_be_limitation_types():
    assert not {b.value for b in InadmissibleLimitationBasis} & {t.value for t in GapLimitationType}
    for basis in InadmissibleLimitationBasis:
        with pytest.raises(ValidationError):
            GapLimitation(limitation_id=uuid4(), limitation_type=basis.value, facet=GapFacet.RESEARCH,
                          evidence_ref_ids=[uuid4()])


def test_student_text_has_no_evidence_source_kind():
    assert {k.value for k in GapSourceKind} == {"ACADEMIC_EVIDENCE", "PRIOR_ART_TEXT"}


def test_no_limitation_means_differentiation_is_not_a_gap():
    assert derive_claim_posture(inputs_bound=True, hypothesis_postures=[], has_differentiating_feature=True) \
        is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP
    assert derive_claim_posture(inputs_bound=True, hypothesis_postures=[], has_differentiating_feature=False) \
        is GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS
    assert derive_claim_posture(inputs_bound=False, hypothesis_postures=[], has_differentiating_feature=True) \
        is GapPosture.INSUFFICIENT_INPUT


def test_unestablished_hypothesis_does_not_mask_differentiation_posture():
    posture = derive_claim_posture(inputs_bound=True, hypothesis_postures=[GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS],
                                   has_differentiating_feature=True)
    assert posture is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP


# -- 2. GapKind ---------------------------------------------------------------


def _lim(t: GapLimitationType, f: GapFacet) -> GapLimitation:
    return GapLimitation(limitation_id=uuid4(), limitation_type=t, facet=f, evidence_ref_ids=[uuid4()])


def test_hybrid_needs_two_distinct_verified_facets():
    research = _lim(GapLimitationType.UNRESOLVED_QUESTION, GapFacet.RESEARCH)
    engineering = _lim(GapLimitationType.MEASURED_SHORTFALL, GapFacet.ENGINEERING)
    assert derive_kind([research, engineering]) is GapKind.HYBRID
    assert derive_kind([research]) is GapKind.RESEARCH
    assert derive_kind([engineering]) is GapKind.ENGINEERING
    assert derive_kind([]) is GapKind.UNRESOLVED


def test_facet_must_be_eligible_for_limitation_type():
    with pytest.raises(ValidationError):
        _lim(GapLimitationType.UNRESOLVED_QUESTION, GapFacet.ENGINEERING)
    with pytest.raises(ValidationError):
        _lim(GapLimitationType.MEASURED_SHORTFALL, GapFacet.RESEARCH)


# -- 3. posture derived in code ------------------------------------------------


def test_full_chain_is_supported_within_bounds():
    h = _full_hypothesis()
    assert h.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert h.statement_qualifier == FIELD_WIDE_DISCLAIMER


def test_asserted_posture_is_refused():
    with pytest.raises(ValidationError, match="derived in code"):
        _full_hypothesis(project_links=[])  # SUPPORTED asserted, link missing


UNLINKED = dict(
    linkage=ProjectLinkageLevel.NONE_MATERIAL, kind=GapKind.UNRESOLVED,
    missing_components=[MissingGapComponent.FULL_PROJECT_LINKAGE, MissingGapComponent.RESOLVED_GAP_KIND],
    posture=GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS,
)


def test_feature_already_disclosed_is_not_a_material_link():
    link = _link(DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES)
    h = _full_hypothesis(project_links=[link], **{**SUPPORTED, **UNLINKED})
    assert h.project_links[0].status is ProjectLinkStatus.FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE
    assert h.existence is GapExistence.LIMITATION_SUPPORTED


# -- correction: project-gap linkage is a typed relation, not structural -------


@pytest.mark.parametrize("relation", [LinkageRelation.UNRELATED, LinkageRelation.RELEVANT_BUT_NOT_ADDRESSING,
                                      LinkageRelation.INSUFFICIENT_LINKAGE_EVIDENCE])
def test_a_b_valid_limitation_with_non_addressing_feature_is_never_supported(relation):
    links = [_link(relation=relation)]
    with pytest.raises(ValidationError, match="derived in code"):
        _full_hypothesis(project_links=links)  # SUPPORTED asserted
    h = _full_hypothesis(project_links=links, **{**SUPPORTED, **UNLINKED})
    assert h.existence is GapExistence.LIMITATION_SUPPORTED  # the gap exists...
    assert h.posture is GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS  # ...but is not a project gap
    claim = derive_claim_posture(inputs_bound=True, hypothesis_postures=[h.posture], has_differentiating_feature=True)
    assert claim is GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP


def test_c_positive_material_linkage_with_all_components_is_supported():
    h = _full_hypothesis()
    assert (h.linkage, h.posture) == (ProjectLinkageLevel.FULL, GapPosture.SUPPORTED_WITHIN_BOUNDS)
    assert h.project_links[0].judgment_basis == "MODEL_ASSISTED_BOUNDED_JUDGMENT"


def test_d_partially_addressing_is_downgraded():
    h = _full_hypothesis(project_links=[_link(relation=LinkageRelation.PARTIALLY_ADDRESSES_LIMITATION)],
                         **{**SUPPORTED, "linkage": ProjectLinkageLevel.PARTIAL,
                            "missing_components": [MissingGapComponent.FULL_PROJECT_LINKAGE],
                            "posture": GapPosture.PARTIALLY_SUPPORTED})
    assert h.posture is GapPosture.PARTIALLY_SUPPORTED


def test_link_must_target_a_limitation_on_the_hypothesis():
    with pytest.raises(ValidationError, match="fabricated limitation"):
        _full_hypothesis(project_links=[_link(limitation_id=uuid4())])
    foreign = _link().model_copy(update={"claim_id": "C-999"})
    with pytest.raises(ValidationError, match="cross-claim"):
        _full_hypothesis(project_links=[foreign])
    fid = uuid4()
    with pytest.raises(ValidationError, match="one linkage judgment"):
        _full_hypothesis(project_links=[_link(feature_id=fid), _link(feature_id=fid)])


def test_e_condition_specific_limitation_without_condition_is_not_supported():
    h = _full_hypothesis()
    req = h.validation_requirement.model_copy(update={"condition_ids": []})
    with pytest.raises(ValidationError, match="derived in code"):
        _rebuild(h, conditions=[], validation_requirement=req.model_dump())
    partial = _rebuild(
        h, conditions=[], validation_requirement=req.model_dump(),
        condition_materiality={str(LIM_ID): ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED},
        missing_components=[MissingGapComponent.MATERIAL_CONDITION], posture=GapPosture.PARTIALLY_SUPPORTED,
    )
    assert partial.posture is GapPosture.PARTIALLY_SUPPORTED


def test_f_non_condition_specific_limitation_needs_no_synthetic_condition():
    h = _full_hypothesis()
    lim = h.limitations[0].model_copy(update={"condition_dimensions": []})
    req = h.validation_requirement.model_copy(update={"condition_ids": []})
    ok = _rebuild(h, limitations=[lim.model_dump()], conditions=[], validation_requirement=req.model_dump(),
                  condition_materiality={str(LIM_ID): ConditionMateriality.CONDITION_NOT_MATERIAL})
    assert ok.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert ok.statement_qualifier == FIELD_WIDE_DISCLAIMER


def test_scope_restriction_is_always_condition_specific():
    with pytest.raises(ValidationError, match="condition-specific"):
        GapLimitation(limitation_id=uuid4(), limitation_type=GapLimitationType.SCOPE_RESTRICTION,
                      facet=GapFacet.RESEARCH, evidence_ref_ids=[uuid4()])


def test_g_missing_phase2e_is_unresolved_independence_not_insufficient_input():
    h = _full_hypothesis()
    lim_ref = next(r for r in h.evidence_refs if r.role is GapEvidenceRole.LIMITATION)
    ungrouped = GapEvidenceRef(**{**lim_ref.model_dump(), "independence_basis": IndependenceBasis.ACADEMIC_UNGROUPED,
                                  "counts_as_independent": False})
    refs = [ungrouped if r is lim_ref else r for r in h.evidence_refs]
    ok = _rebuild(h, evidence_refs=[r.model_dump() for r in refs],
                  corroboration=GapCorroborationLevel.UNRESOLVED_INDEPENDENCE)
    assert ok.corroboration is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
    assert ok.scope is GapScope.SINGLE_SOURCE_BOUNDED
    assert ok.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS
    assert derive_claim_posture(inputs_bound=True, hypothesis_postures=[ok.posture],
                                has_differentiating_feature=True) is GapPosture.SUPPORTED_WITHIN_BOUNDS


PASSAGE = "whether it generalizes to arid farms remains untested; recall falls to 54% on edge devices"
R_ID = UUID("00000000-0000-0000-0000-0000000000b1")
E_ID = UUID("00000000-0000-0000-0000-0000000000e1")


def _hybrid(lim_refs: list[GapEvidenceRef], research_ref: GapEvidenceRef, engineering_ref: GapEvidenceRef,
            *, research_type=GapLimitationType.UNRESOLVED_QUESTION,
            engineering_type=GapLimitationType.MEASURED_SHORTFALL, links=None, **expect):
    cap = _academic(GapEvidenceRole.EXISTING_CAPABILITY, "detects pests with 92% accuracy", key="doi:cap")
    lims = [
        GapLimitation(limitation_id=R_ID, limitation_type=research_type, facet=GapFacet.RESEARCH,
                      evidence_ref_ids=[research_ref.evidence_ref_id]),
        GapLimitation(limitation_id=E_ID, limitation_type=engineering_type, facet=GapFacet.ENGINEERING,
                      evidence_ref_ids=[engineering_ref.evidence_ref_id]),
    ]
    fields = dict(
        hypothesis_id=uuid4(), gap_run_id=GAP, research_run_id=RUN, claim_id=CLAIM, evidence_refs=[cap, *lim_refs],
        existing_capabilities=[GapExistingCapability(capability_id=uuid4(), evidence_ref_ids=[cap.evidence_ref_id])],
        limitations=lims,
        project_links=links if links is not None else [_link(limitation_id=R_ID), _link(limitation_id=E_ID)],
        validation_requirement=GapValidationRequirement(
            requirement_id=uuid4(),
            metric=ValidationAnchor(origin=ValidationAnchorOrigin.STUDENT_CLAIM_TEXT, text="recall",
                                    claim_id=CLAIM, start=0, end=6),
        ),
        counterevidence_review_complete=True,
        existence=GapExistence.LIMITATION_SUPPORTED, linkage=ProjectLinkageLevel.FULL,
        condition_materiality={str(R_ID): ConditionMateriality.CONDITION_NOT_MATERIAL,
                               str(E_ID): ConditionMateriality.CONDITION_NOT_MATERIAL},
        kind=GapKind.HYBRID, corroboration=GapCorroborationLevel.SINGLE_SOURCE_DIRECT,
        scope=GapScope.SINGLE_SOURCE_BOUNDED, missing_components=[], posture=GapPosture.SUPPORTED_WITHIN_BOUNDS,
    )
    fields.update(expect)
    return GapHypothesis(**fields)


def test_refine_a_one_excerpt_two_distinct_propositions_may_be_hybrid():
    passage = _academic(GapEvidenceRole.LIMITATION, PASSAGE, key="doi:shared")
    h = _hybrid([passage], passage, passage)
    assert h.kind is GapKind.HYBRID and h.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_refine_b_same_source_two_exact_spans_may_be_hybrid():
    record = uuid4()
    first = PASSAGE.split("; ")[0]
    second = PASSAGE.split("; ")[1]
    research_ref = GapEvidenceRef(**{**_academic(GapEvidenceRole.LIMITATION, first, key="doi:shared").model_dump(),
                                     "source_record_id": record})
    engineering_ref = GapEvidenceRef(**{
        **_academic(GapEvidenceRole.LIMITATION, second, key="doi:shared", start=len(first) + 2).model_dump(),
        "source_record_id": record})
    h = _hybrid([research_ref, engineering_ref], research_ref, engineering_ref)
    assert h.kind is GapKind.HYBRID


def test_refine_c_relabelled_copy_cannot_manufacture_hybrid():
    passage = _academic(GapEvidenceRole.LIMITATION, PASSAGE, key="doi:shared")
    with pytest.raises(ValidationError, match="same proposition"):
        _hybrid([passage], passage, passage, research_type=GapLimitationType.EXPLICIT_LIMITATION,
                engineering_type=GapLimitationType.EXPLICIT_LIMITATION)
    # a re-minted ref id over the identical span is the same span
    clone = GapEvidenceRef(**{**passage.model_dump(), "evidence_ref_id": uuid4()})
    with pytest.raises(ValidationError, match="same proposition"):
        _hybrid([passage, clone], passage, clone, research_type=GapLimitationType.EXPLICIT_LIMITATION,
                engineering_type=GapLimitationType.EXPLICIT_LIMITATION)


def test_refine_d_one_limitation_cannot_hold_two_facets():
    assert GapLimitation.model_fields["facet"].annotation is GapFacet
    with pytest.raises(ValidationError):
        GapLimitation(limitation_id=uuid4(), limitation_type=GapLimitationType.EXPLICIT_LIMITATION,
                      facet=[GapFacet.RESEARCH, GapFacet.ENGINEERING], evidence_ref_ids=[uuid4()])
    same = uuid4()
    r = GapLimitation(limitation_id=same, limitation_type=GapLimitationType.EXPLICIT_LIMITATION,
                      facet=GapFacet.RESEARCH, evidence_ref_ids=[uuid4()])
    e = GapLimitation(limitation_id=same, limitation_type=GapLimitationType.EXPLICIT_LIMITATION,
                      facet=GapFacet.ENGINEERING, evidence_ref_ids=[uuid4()])
    assert derive_kind([r, e]) is GapKind.UNRESOLVED  # one id, two labels: ambiguous


def test_refine_e_only_one_side_linked_is_not_hybrid():
    passage = _academic(GapEvidenceRole.LIMITATION, PASSAGE, key="doi:shared")
    links = [_link(limitation_id=E_ID), _link(limitation_id=R_ID, relation=LinkageRelation.UNRELATED)]
    with pytest.raises(ValidationError, match="derived in code"):
        _hybrid([passage], passage, passage, links=links)
    h = _hybrid([passage], passage, passage, links=links, kind=GapKind.ENGINEERING)
    assert h.kind is GapKind.ENGINEERING


def test_refine_f_shared_source_does_not_imply_corroboration():
    record = uuid4()
    a = GapEvidenceRef(**{**_academic(GapEvidenceRole.LIMITATION, "remains untested", key="doi:shared").model_dump(),
                          "source_record_id": record})
    b = GapEvidenceRef(**{**_academic(GapEvidenceRole.LIMITATION, "falls to 54%", key="doi:shared",
                                      start=40).model_dump(), "source_record_id": record})
    h = _hybrid([a, b], a, b)
    assert h.corroboration is GapCorroborationLevel.SINGLE_SOURCE_DIRECT  # two propositions, one unit
    assert all(r.independence_key == "doi:shared" for r in (a, b))
    fam = _unit(IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED, "pub:EP1A1", CandidateType.PATENT)
    assert derive_corroboration([_prior_art(fam), _prior_art(fam)]) is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE


def test_i_hybrid_needs_both_sides_materially_linked():
    research = _lim(GapLimitationType.UNRESOLVED_QUESTION, GapFacet.RESEARCH)
    engineering = _lim(GapLimitationType.MEASURED_SHORTFALL, GapFacet.ENGINEERING)
    only_eng = [_link(limitation_id=engineering.limitation_id),
                _link(limitation_id=research.limitation_id, relation=LinkageRelation.UNRELATED)]
    assert derive_kind(materially_linked([research, engineering], only_eng)) is GapKind.ENGINEERING
    both = [_link(limitation_id=engineering.limitation_id), _link(limitation_id=research.limitation_id)]
    assert derive_kind(materially_linked([research, engineering], both)) is GapKind.HYBRID


def test_measured_shortfall_needs_a_number_in_its_excerpt():
    lim = _academic(GapEvidenceRole.LIMITATION, "accuracy is lower in low light")
    with pytest.raises(ValidationError, match="number"):
        _full_hypothesis(
            evidence_refs=[lim],
            existing_capabilities=[], conditions=[], project_links=[], validation_requirement=None,
            limitations=[GapLimitation(limitation_id=uuid4(), limitation_type=GapLimitationType.MEASURED_SHORTFALL,
                                       facet=GapFacet.ENGINEERING, evidence_ref_ids=[lim.evidence_ref_id])],
        )


def test_retracted_only_limitation_is_blocked_source_quality():
    lim = _academic(GapEvidenceRole.LIMITATION, quality=SourceQualityVerdict.INELIGIBLE_RETRACTED)
    h = GapHypothesis(
        hypothesis_id=uuid4(), gap_run_id=GAP, research_run_id=RUN, claim_id=CLAIM, evidence_refs=[lim],
        limitations=[GapLimitation(limitation_id=uuid4(), limitation_type=GapLimitationType.EXPLICIT_LIMITATION,
                                   facet=GapFacet.ENGINEERING, evidence_ref_ids=[lim.evidence_ref_id])],
        counterevidence_review_complete=True,
        existence=GapExistence.LIMITATION_BLOCKED_SOURCE_QUALITY, linkage=ProjectLinkageLevel.NONE_MATERIAL,
        kind=GapKind.UNRESOLVED, corroboration=GapCorroborationLevel.NO_DIRECT_SUPPORT,
        scope=GapScope.INSUFFICIENT_SCOPE,
        missing_components=[MissingGapComponent.EXISTING_CAPABILITY, MissingGapComponent.FULL_PROJECT_LINKAGE,
                            MissingGapComponent.VALIDATION_REQUIREMENT, MissingGapComponent.RESOLVED_GAP_KIND],
        posture=GapPosture.BLOCKED_SOURCE_QUALITY,
    )
    assert h.posture is GapPosture.BLOCKED_SOURCE_QUALITY


# -- 4. corroboration inherited, never inflated -------------------------------


def test_one_patent_family_is_one_unit():
    fam = _unit(IndependenceUnitKind.PATENT_FAMILY, "family:123", CandidateType.PATENT)
    refs = [_prior_art(fam), _prior_art(fam), _prior_art(fam)]
    assert derive_corroboration(refs) is GapCorroborationLevel.SINGLE_SOURCE_DIRECT


def test_unresolved_family_and_forks_never_corroborate():
    unresolved = _unit(IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED, "pub:EP1A1", CandidateType.PATENT)
    fork = _unit(IndependenceUnitKind.OSS_DEPENDENT_NETWORK, "github:2", CandidateType.OPEN_SOURCE)
    assert derive_corroboration([_prior_art(unresolved), _prior_art(fork, text_kind=TextKind.OSS_README)]) \
        is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE


def test_product_correlation_group_counts_once():
    a = _unit(IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY, "product:a", CandidateType.PRODUCT, "correlation:g1")
    b = _unit(IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY, "product:b", CandidateType.PRODUCT, "correlation:g1")
    refs = [_prior_art(a, text_kind=TextKind.PRODUCT_PAGE_TEXT), _prior_art(b, text_kind=TextKind.PRODUCT_PAGE_TEXT)]
    assert derive_corroboration(refs) is GapCorroborationLevel.SINGLE_SOURCE_DIRECT


def test_inherited_unit_cannot_be_rewritten():
    fam = _unit(IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED, "pub:EP1A1", CandidateType.PATENT)
    ref = _prior_art(fam)
    with pytest.raises(ValidationError, match="inherited unchanged"):
        GapEvidenceRef(**{**ref.model_dump(), "counts_as_independent": True})


def test_ungrouped_academic_evidence_is_never_independent():
    with pytest.raises(ValidationError):
        GapEvidenceRef(**{**_academic(GapEvidenceRole.LIMITATION, grouped=False).model_dump(),
                          "counts_as_independent": True})


def test_mixed_and_multi_source():
    a = _academic(GapEvidenceRole.LIMITATION, key="doi:1")
    b = _academic(GapEvidenceRole.LIMITATION, key="doi:2")
    fam = _prior_art(_unit(IndependenceUnitKind.PATENT_FAMILY, "family:1", CandidateType.PATENT))
    assert derive_corroboration([a, b]) is GapCorroborationLevel.MULTI_SOURCE_CORROBORATED
    assert derive_corroboration([a, fam]) is GapCorroborationLevel.MIXED_SOURCE_CORROBORATED
    assert derive_corroboration([a, _academic(GapEvidenceRole.LIMITATION, key="doi:1")]) \
        is GapCorroborationLevel.SINGLE_SOURCE_DIRECT


# -- 5. scope always bounded ---------------------------------------------------


def test_scope_has_no_field_wide_value_and_follows_refs():
    assert not any("FIELD" in s.value or "GLOBAL" in s.value for s in GapScope)
    assert not any("FIELD" in p.value or p.value in {"GAP_ESTABLISHED", "NO_GAP"} for p in GapPosture)
    single = [_academic(GapEvidenceRole.LIMITATION)]
    assert derive_scope(single, derive_corroboration(single)) is GapScope.SINGLE_SOURCE_BOUNDED
    review = [_academic(GapEvidenceRole.LIMITATION, review=True)]
    assert derive_scope(review, derive_corroboration(review)) is GapScope.REVIEW_SYNTHESIS_BOUNDED
    pa = [_prior_art(_unit(IndependenceUnitKind.PATENT_FAMILY, "family:1", CandidateType.PATENT))]
    assert derive_scope(pa, derive_corroboration(pa)) is GapScope.CANDIDATE_SET_BOUNDED
    assert derive_scope([], GapCorroborationLevel.NO_DIRECT_SUPPORT) is GapScope.INSUFFICIENT_SCOPE


# -- 6. counterevidence --------------------------------------------------------


def _with_counter(match: ConditionMatch, bucket=None):
    h = _full_hypothesis()
    ref = _academic(GapEvidenceRole.COUNTEREVIDENCE, "works in low light at 90%", key="doi:9")
    counter = GapCounterEvidence(
        counter_id=uuid4(), kind=CounterEvidenceKind.LIMITATION_ADDRESSED, condition_match=match,
        evidence_ref_ids=[ref.evidence_ref_id], chronology_bucket=bucket,
        temporal_effect="WEAKENS_CURRENT_POSTURE_ONLY" if bucket is ChronologyBucket.AFTER_CUTOFF else "NOT_APPLICABLE",
    )
    return h, ref, counter


def test_material_counterevidence_weakens_and_cannot_be_hidden():
    h, ref, counter = _with_counter(ConditionMatch.SAME_CONDITION)
    data = {**_dump(h), "evidence_refs": [*h.evidence_refs, ref], "counterevidence": [counter]}
    with pytest.raises(ValidationError, match="derived in code"):
        GapHypothesis(**data)  # still claims SUPPORTED
    weakened = GapHypothesis(**{**data, "posture": GapPosture.COUNTEREVIDENCE_WEAKENS_GAP})
    assert weakened.posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP


def test_different_condition_counterevidence_does_not_defeat():
    h, ref, counter = _with_counter(ConditionMatch.DIFFERENT_CONDITION)
    kept = GapHypothesis(**{**_dump(h), "evidence_refs": [*h.evidence_refs, ref], "counterevidence": [counter]})
    assert kept.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_later_counterevidence_only_weakens_current_posture():
    with pytest.raises(ValidationError):
        GapCounterEvidence(counter_id=uuid4(), kind=CounterEvidenceKind.LIMITATION_ADDRESSED,
                           condition_match=ConditionMatch.SAME_CONDITION, evidence_ref_ids=[uuid4()],
                           chronology_bucket=ChronologyBucket.AFTER_CUTOFF)


# -- 7. chronology -------------------------------------------------------------


def test_chronology_never_proves_publicity_or_legal_status():
    with pytest.raises(ValidationError):
        GapChronologyNote(evidence_ref_id=uuid4(), bucket=ChronologyBucket.BEFORE_CUTOFF,
                          upstream_basis="PATENT_FIRST_PUBLIC_DATE", historical_publicity_inferred=True)
    with pytest.raises(ValidationError):
        GapChronologyNote(evidence_ref_id=uuid4(), bucket=ChronologyBucket.BEFORE_CUTOFF,
                          upstream_basis="PATENT_FIRST_PUBLIC_DATE", legal_prior_art_established=True)


# -- 8. anchors ---------------------------------------------------------------


def test_repeated_excerpt_is_never_bound_as_unique():
    with pytest.raises(ValidationError, match="first-occurrence"):
        _academic(GapEvidenceRole.LIMITATION, count=2)
    ok = _academic(GapEvidenceRole.LIMITATION, count=2, resolution=OccurrenceResolution.VALIDATED_EXACT_OFFSETS)
    assert ok.occurrence_count == 2


def test_offsets_must_span_excerpt():
    ref = _academic(GapEvidenceRole.LIMITATION)
    with pytest.raises(ValidationError):
        GapEvidenceRef(**{**ref.model_dump(), "end": ref.end + 1})


# -- 9. validation requirement -------------------------------------------------


def test_validation_requirement_has_no_threshold_and_metric_is_a_subspan():
    assert not any("threshold" in f or "target" in f for f in GapValidationRequirement.model_fields)
    h = _full_hypothesis()
    bad = h.validation_requirement.model_copy(
        update={"metric": ValidationAnchor(origin=ValidationAnchorOrigin.LIMITATION_EVIDENCE, text="F1 >= 0.95",
                                           evidence_ref_id=h.limitations[0].evidence_ref_ids[0], start=0, end=10)}
    )
    with pytest.raises(ValidationError, match="subspan"):
        GapHypothesis(**{**_dump(h), "validation_requirement": bad.model_dump()})


# -- 10. run binding, no search, forbidden fields, checkpoint -----------------


def _inventory(hypotheses) -> list[GapInventoryText]:
    seen, out = set(), []
    for h in hypotheses:
        for r in h.evidence_refs:
            key = (r.source_kind, r.source_record_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(GapInventoryText(
                inventory_text_id=uuid4(), source_kind=r.source_kind, source_record_id=r.source_record_id,
                upstream_run_id=r.upstream_run_id, candidate_id=r.candidate_id, text_kind=r.text_kind,
                text_hash=r.text_hash, span_start=0, span_end=r.end + 10, language=r.language,
                source_quality=r.source_quality, independence_basis=r.independence_basis,
                independence_key=r.independence_key, counts_as_independent=r.counts_as_independent,
                correlation_group_key=r.correlation_group_key, inherited_unit=r.inherited_unit,
                is_review_source=r.is_review_source,
            ))
    return out


def _run(**kw) -> GapAssessmentRun:
    hypotheses = kw.get("hypotheses", [])
    inventory = kw.pop("inventory_texts", None) or _inventory(hypotheses)
    claims = {h.claim_id for h in hypotheses}
    coverage = kw.pop("counterevidence_coverage", None) or [
        CounterevidenceCoverage(claim_id=c, examined_text_ids=[t.inventory_text_id for t in inventory])
        for c in sorted(claims)
    ]
    return GapAssessmentRun(gap_run_id=GAP, research_run_id=RUN, nd_run_id=ND, started_at=NOW,
                            inventory_texts=inventory, counterevidence_coverage=coverage, **kw)


def test_run_rejects_cross_run_and_out_of_inventory_evidence():
    h = _full_hypothesis()
    inventory = [r.evidence_ref_id for r in h.evidence_refs]
    assert _run(hypotheses=[h], eligible_evidence_ref_ids=inventory).hypotheses
    with pytest.raises(ValidationError, match="no new evidence"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=inventory[:1])
    foreign = GapHypothesis(**{**_dump(h), "research_run_id": uuid4()})
    with pytest.raises(ValidationError, match="cross-run"):
        _run(hypotheses=[foreign], eligible_evidence_ref_ids=inventory)
    with pytest.raises(ValidationError):
        _run(external_search_calls=1)


def test_claim_assessment_posture_is_derived():
    with pytest.raises(ValidationError, match="derived in code"):
        ClaimGapAssessment(assessment_id=uuid4(), gap_run_id=GAP, research_run_id=RUN, claim_id=CLAIM,
                           claim_text_hash=HASH, inputs_bound=True, has_differentiating_feature=True,
                           canonical_project_type=ProjectType.ENGINEERING_PROJECT,
                           posture=GapPosture.SUPPORTED_WITHIN_BOUNDS)


def _phase2j_models() -> list[type[BaseModel]]:
    return [obj for _, obj in inspect.getmembers(gap_module, inspect.isclass)
            if issubclass(obj, BaseModel) and obj.__module__ == gap_module.__name__]


def test_no_forbidden_field_on_any_phase2j_model():
    for model in _phase2j_models():
        for name in model.model_fields:
            assert not any(frag in name for frag in FORBIDDEN_FIELD_FRAGMENTS), (model.__name__, name)


def test_schema_module_imports_no_connector_or_network():
    tree = ast.parse(inspect.getsource(gap_module))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert all(m.startswith(("src.schemas", "__future__", "enum", "typing", "uuid", "pydantic")) for m in imported)


def test_gap_run_is_checkpoint_reachable_and_round_trips():
    discovered = set(discover_types_from(EvaluationGraphState))
    for model in (GapAssessmentRun, GapHypothesis, GapEvidenceRef, ClaimGapAssessment, GapProjectLink):
        assert model in discovered, model.__name__
    h = _full_hypothesis()
    run = _run(hypotheses=[h], eligible_evidence_ref_ids=[r.evidence_ref_id for r in h.evidence_refs])
    assert GapAssessmentRun.model_validate_json(run.model_dump_json()) == run
    assert isinstance(run.gap_run_id, UUID)


# -- implementation-gate contracts: inventory binding, coverage, unbound reasons ----


def test_excerpt_from_a_text_outside_the_inventory_is_refused():
    h = _full_hypothesis()
    ids = [r.evidence_ref_id for r in h.evidence_refs]
    inventory = _inventory([h])[:-1]  # drop one source text
    with pytest.raises(ValidationError, match="outside the bounded inventory"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=ids, inventory_texts=inventory,
             counterevidence_coverage=[CounterevidenceCoverage(
                 claim_id=CLAIM, examined_text_ids=[t.inventory_text_id for t in inventory])])


def test_excerpt_must_inherit_its_inventory_texts_independence_unchanged():
    h = _full_hypothesis()
    ids = [r.evidence_ref_id for r in h.evidence_refs]
    inventory = [t.model_copy(update={"counts_as_independent": not t.counts_as_independent,
                                      "independence_basis": IndependenceBasis.ACADEMIC_PHASE2E_GROUP})
                 for t in _inventory([h])]
    with pytest.raises(ValidationError):
        _run(hypotheses=[h], eligible_evidence_ref_ids=ids, inventory_texts=inventory)


def test_excerpt_must_lie_inside_its_inventory_span_and_hash():
    h = _full_hypothesis()
    ids = [r.evidence_ref_id for r in h.evidence_refs]
    narrow = [t.model_copy(update={"span_start": 0, "span_end": 1}) for t in _inventory([h])]
    with pytest.raises(ValidationError, match="disagrees with its inventory text"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=ids, inventory_texts=narrow)


def test_a_text_visible_to_another_claim_cannot_be_cited():
    h = _full_hypothesis()
    ids = [r.evidence_ref_id for r in h.evidence_refs]
    inventory = [t.model_copy(update={"linked_claim_ids": ["C-999"]}) for t in _inventory([h])]
    with pytest.raises(ValidationError, match="cross-claim leakage"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=ids, inventory_texts=inventory,
             counterevidence_coverage=[CounterevidenceCoverage(claim_id=CLAIM)])


def test_counterevidence_coverage_must_account_for_every_visible_text():
    h = _full_hypothesis()
    inventory = _inventory([h])
    with pytest.raises(ValidationError, match="account for every inventory text"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=[r.evidence_ref_id for r in h.evidence_refs],
             inventory_texts=inventory,
             counterevidence_coverage=[CounterevidenceCoverage(
                 claim_id=CLAIM, examined_text_ids=[inventory[0].inventory_text_id])])


def test_a_hypothesis_must_copy_its_claims_coverage_completeness():
    h = _full_hypothesis()
    inventory = _inventory([h])
    incomplete = CounterevidenceCoverage(claim_id=CLAIM, omitted_text_ids=[t.inventory_text_id for t in inventory])
    with pytest.raises(ValidationError, match="copies its claim's counterevidence coverage"):
        _run(hypotheses=[h], eligible_evidence_ref_ids=[r.evidence_ref_id for r in h.evidence_refs],
             inventory_texts=inventory, counterevidence_coverage=[incomplete])


def test_incomplete_counterevidence_review_can_never_be_supported():
    with pytest.raises(ValidationError, match="derived in code"):
        _full_hypothesis(counterevidence_review_complete=False)  # SUPPORTED asserted
    h = _full_hypothesis(
        counterevidence_review_complete=False,
        missing_components=[MissingGapComponent.COMPLETE_COUNTEREVIDENCE_REVIEW],
        posture=GapPosture.PARTIALLY_SUPPORTED,
    )
    assert h.posture is GapPosture.PARTIALLY_SUPPORTED


def test_a_claim_is_unbound_exactly_when_it_states_why():
    from src.schemas.gap_assessment import InsufficientReason

    common = dict(assessment_id=uuid4(), gap_run_id=GAP, research_run_id=RUN, claim_id=CLAIM, claim_text_hash=HASH,
                  has_differentiating_feature=False, canonical_project_type=ProjectType.UNKNOWN)
    ok = ClaimGapAssessment(**common, inputs_bound=False, insufficient_reasons=[InsufficientReason.NO_PHASE_2I_RUN],
                            posture=GapPosture.INSUFFICIENT_INPUT)
    assert ok.posture is GapPosture.INSUFFICIENT_INPUT
    with pytest.raises(ValidationError, match="states why"):
        ClaimGapAssessment(**common, inputs_bound=False, posture=GapPosture.INSUFFICIENT_INPUT)
    with pytest.raises(ValidationError, match="states why"):
        ClaimGapAssessment(**common, inputs_bound=True, insufficient_reasons=[InsufficientReason.NO_PHASE_2I_RUN],
                           posture=GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS)


def test_the_hypothesis_builder_and_the_validator_share_one_rule():
    from src.schemas.gap_assessment import build_hypothesis

    h = _full_hypothesis()
    rebuilt = build_hypothesis(**{k: getattr(h, k) for k in type(h).model_fields if k not in {
        "existence", "linkage", "condition_materiality", "kind", "corroboration", "scope", "missing_components",
        "posture"}})
    assert rebuilt == h


# -- hardening: counterevidence scope effect ----------------------------------


def _counter(match: ConditionMatch, bucket=None):
    ref = _academic(GapEvidenceRole.COUNTEREVIDENCE, "works in low light at 90%", key="doi:9")
    return ref, GapCounterEvidence(
        counter_id=uuid4(), kind=CounterEvidenceKind.LIMITATION_ADDRESSED, condition_match=match,
        evidence_ref_ids=[ref.evidence_ref_id], chronology_bucket=bucket,
        temporal_effect="WEAKENS_CURRENT_POSTURE_ONLY" if bucket is ChronologyBucket.AFTER_CUTOFF else "NOT_APPLICABLE")


def test_scope_effect_is_derived_from_the_condition_relation_of_the_counterevidence():
    from src.schemas.gap_assessment import CounterevidenceScopeEffect as E, derive_scope_effect

    assert derive_scope_effect([]) == (E.NO_SCOPE_NARROWING, [], False)
    _, same = _counter(ConditionMatch.SAME_CONDITION)
    assert derive_scope_effect([same])[0] is E.NO_SCOPE_NARROWING  # weakens, does not narrow
    _, different = _counter(ConditionMatch.DIFFERENT_CONDITION)
    assert derive_scope_effect([different]) == (E.NARROWED_BY_DIFFERENT_CONDITION, [different.counter_id], False)
    _, later = _counter(ConditionMatch.DIFFERENT_CONDITION, ChronologyBucket.AFTER_CUTOFF)
    assert derive_scope_effect([later])[2] is True
    assert derive_scope_effect([later, different])[2] is False  # one before-cutoff narrowing is not current-only
    _, unknown = _counter(ConditionMatch.CONDITION_UNKNOWN)
    assert derive_scope_effect([unknown, different])[0] is E.CONDITION_RELATION_UNRESOLVED


def test_a_stored_scope_effect_or_statement_that_disagrees_is_refused():
    from src.schemas.gap_assessment import CounterevidenceScopeEffect as E

    ref, different = _counter(ConditionMatch.DIFFERENT_CONDITION)
    h = _full_hypothesis()
    base = {**_dump(h), "evidence_refs": [*h.evidence_refs, ref], "counterevidence": [different]}
    ok = GapHypothesis(**base)
    assert ok.counterevidence_scope_effect is E.NARROWED_BY_DIFFERENT_CONDITION
    with pytest.raises(ValidationError, match="derived in code"):
        GapHypothesis(**{**base, "counterevidence_scope_effect": E.NO_SCOPE_NARROWING})
    with pytest.raises(ValidationError, match="derived in code"):
        GapHypothesis(**{**base, "narrowing_counter_ids": []})
    with pytest.raises(ValidationError, match="derived in code"):
        GapHypothesis(**{**base, "bounded_statement": ok.bounded_statement.model_copy(
            update={"condition_ids": []}).model_dump()})
    assert GapHypothesis.model_validate_json(ok.model_dump_json()) == ok  # round trip keeps the derived values


def test_the_bounded_statement_has_no_prose_field():
    from src.schemas.gap_assessment import GapBoundedStatement

    assert not any(info.annotation is str for info in GapBoundedStatement.model_fields.values())
