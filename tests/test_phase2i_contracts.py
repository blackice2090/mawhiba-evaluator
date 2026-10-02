"""Phase 2I contract tests -- the six architecture-gate corrections.

Smallest, model-free checks of the schema and helper semantics:

1. an unresolved patent family is never an independent unit;
2. product entities are never merged; correlation only caps corroboration;
3. manifest disclosure capacity is feature-sensitive;
4. instruction-like candidate text is inert data, not invalid evidence;
5. chronology statements are source-type specific and prove no publicity;
6. a repeated excerpt is never bound by first-occurrence guessing.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.research.novelty.anchoring import LocateFailure, locate
from src.research.novelty.comparison import discloses_system_prompt
from src.research.novelty.synthesis import chronology_split, type_summaries
from src.schemas.novelty_differentiation import (
    AnchorRejectionReason,
    CandidateDisclosureAnchor,
    CandidateRef,
    CandidateType,
    ChronologyBucket,
    ChronologySplit,
    DisclosureCapacity,
    FeatureType,
    FullClaimRelation,
    IndependenceUnit,
    IndependenceUnitKind,
    OccurrenceResolution,
    SourceRecordKind,
    TextKind,
    effective_capacity,
)

HASH = "a" * 64


def _unit(kind: IndependenceUnitKind, key: str, independent: bool, ctype: CandidateType, corr: str | None = None):
    return IndependenceUnit(candidate_type=ctype, unit_kind=kind, unit_key=key,
                            counts_as_independent=independent, correlation_group_key=corr)


def _comparison(ctype: CandidateType, unit: IndependenceUnit, relation=FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP,
                bucket=ChronologyBucket.NO_CUTOFF):
    return SimpleNamespace(
        candidate_ref=SimpleNamespace(candidate_type=ctype), independence_unit=unit,
        full_claim_relation=relation, chronology_bucket=bucket,
    )


# -- 1. patent family independence ------------------------------------------


def test_unresolved_patent_family_unit_can_never_be_independent():
    with pytest.raises(ValidationError, match="never an independent"):
        _unit(IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED, "publication:EP.1.A1", True, CandidateType.PATENT)
    with pytest.raises(ValidationError, match="counts as independent"):
        _unit(IndependenceUnitKind.PATENT_FAMILY, "family:x", False, CandidateType.PATENT)


def test_two_overlapping_unresolved_family_publications_yield_zero_independent_units():
    comparisons = [
        _comparison(CandidateType.PATENT, _unit(IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED,
                                                f"publication:EP.{n}.A1", False, CandidateType.PATENT))
        for n in (1, 2)
    ]
    patent = type_summaries(comparisons)[0]
    assert patent.full_overlap_candidates == 2
    assert patent.full_overlap_units == 2
    assert patent.full_overlap_independent_units == 0


def test_patent_unit_follows_only_the_phase2g_established_family_status():
    from src.research.novelty.candidates import patent_unit
    from src.schemas.patent import PatentFamilyStatus

    group = uuid4()
    def cand(status, group_id=None):
        return SimpleNamespace(family_status=status, family_group_id=group_id, publication_key="EP.1.A1")
    assert patent_unit(cand(PatentFamilyStatus.VERIFIED_FAMILY, group)).unit_kind is IndependenceUnitKind.PATENT_FAMILY
    assert patent_unit(cand(PatentFamilyStatus.SINGLETON_FAMILY, group)).unit_kind is IndependenceUnitKind.PATENT_SINGLETON_FAMILY
    for status in (PatentFamilyStatus.FAMILY_DATA_UNAVAILABLE, PatentFamilyStatus.FAMILY_RESOLUTION_FAILED,
                   PatentFamilyStatus.NOT_REQUESTED):
        unit = patent_unit(cand(status, group))
        assert unit.unit_kind is IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED
        assert not unit.counts_as_independent and unit.corroboration_key is None


# -- 2. product identity / independence -------------------------------------


def test_no_merged_product_unit_kind_exists():
    assert "PRODUCT_LINKED_CLUSTER" not in IndependenceUnitKind.__members__


def test_correlated_product_entities_stay_separate_units_but_corroborate_once():
    a = _unit(IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY, "entity:a", True, CandidateType.PRODUCT, "correlation:a")
    b = _unit(IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY, "entity:b", True, CandidateType.PRODUCT, "correlation:a")
    assert a.unit_key != b.unit_key and a.unit_kind is not IndependenceUnitKind.PRODUCT_STRONG_ENTITY
    product = type_summaries([_comparison(CandidateType.PRODUCT, a), _comparison(CandidateType.PRODUCT, b)])[1]
    assert product.full_overlap_units == 2
    assert product.full_overlap_independent_units == 1
    assert product.full_overlap_unresolved_correlation_groups == 1


def test_correlation_group_is_product_only_and_never_an_identity_key():
    with pytest.raises(ValidationError, match="only product"):
        _unit(IndependenceUnitKind.PATENT_FAMILY, "family:x", True, CandidateType.PATENT, "correlation:x")
    with pytest.raises(ValidationError, match="namespaced"):
        _unit(IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY, "entity:a", True, CandidateType.PRODUCT, "gtin:123")


# -- 3. manifest capacity is feature-sensitive ------------------------------


@pytest.mark.parametrize(
    ("feature_type", "expected"),
    [
        (FeatureType.COMPONENT, DisclosureCapacity.MATERIAL),
        (FeatureType.CONSTRAINT, DisclosureCapacity.MATERIAL),
        (FeatureType.OTHER_TECHNICAL_FEATURE, DisclosureCapacity.LIMITED),
        (FeatureType.MECHANISM, DisclosureCapacity.NON_MATERIAL),
        (FeatureType.FUNCTION, DisclosureCapacity.NON_MATERIAL),
        (FeatureType.SEQUENCE, DisclosureCapacity.NON_MATERIAL),
        (FeatureType.RELATIONSHIP, DisclosureCapacity.NON_MATERIAL),
        (FeatureType.COMBINATION, DisclosureCapacity.NON_MATERIAL),
    ],
)
def test_manifest_capacity_depends_on_feature_type(feature_type, expected):
    assert effective_capacity(TextKind.OSS_MANIFEST, DisclosureCapacity.MATERIAL, feature_type) is expected


def _anchor(**over):
    ref = CandidateRef(candidate_type=CandidateType.OPEN_SOURCE, candidate_id=uuid4(),
                       source_run_id=uuid4(), identity_key="github:1")
    fields = dict(
        anchor_id=uuid4(), comparison_id=uuid4(), feature_id=uuid4(), feature_type=FeatureType.COMPONENT,
        candidate_ref=ref, text_ref_id=uuid4(), source_record_kind=SourceRecordKind.REPOSITORY_SNAPSHOT,
        source_record_id=uuid4(), text_kind=TextKind.OSS_MANIFEST, excerpt="opencv-python", start=0, end=13,
        occurrence_count=1, occurrence_index=1, occurrence_resolution=OccurrenceResolution.UNIQUE_IN_TEXT,
        text_digest=HASH, base_capacity=DisclosureCapacity.MATERIAL, capacity=DisclosureCapacity.MATERIAL,
    )
    fields.update(over)
    return CandidateDisclosureAnchor(**fields)


def test_manifest_anchor_cannot_materially_disclose_a_mechanism_or_combination():
    assert _anchor().capacity is DisclosureCapacity.MATERIAL
    for feature_type in (FeatureType.MECHANISM, FeatureType.COMBINATION, FeatureType.SEQUENCE):
        with pytest.raises(ValidationError, match="source- and feature-sensitive"):
            _anchor(feature_type=feature_type)
    assert _anchor(feature_type=FeatureType.MECHANISM, capacity=DisclosureCapacity.NON_MATERIAL)


def test_non_manifest_kinds_keep_their_base_capacity():
    for feature_type in FeatureType:
        assert effective_capacity(TextKind.PATENT_CLAIMS, DisclosureCapacity.MATERIAL, feature_type) is DisclosureCapacity.MATERIAL


# -- 4. instruction-like candidate text is inert data -----------------------


def test_instruction_like_text_is_not_a_rejection_reason():
    assert "SUSPECTED_PROMPT_INJECTION" not in AnchorRejectionReason.__members__
    text = 'The filter detects payloads such as "ignore previous instructions" before the model sees them.'
    located = locate(text, "ignore previous instructions")
    assert not isinstance(located, LocateFailure)
    assert text[located.start:located.end] == "ignore previous instructions"


def test_system_prompt_disclosure_is_model_behaviour_and_is_detected():
    from src.llm.prompts import PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1

    leaked = next(l for l in PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1.splitlines() if len(l.strip()) >= 40)
    assert discloses_system_prompt(f"My instructions say: {leaked}", ["unrelated candidate text"])
    # The same words genuinely present in the candidate text are data, not leakage.
    assert not discloses_system_prompt(leaked, [f"quoted: {leaked}"])
    assert not discloses_system_prompt("ignore previous instructions", ["x"])


# -- 5. chronology is source-type specific ----------------------------------


def test_chronology_statements_are_per_type():
    unit = _unit(IndependenceUnitKind.PRODUCT_STRONG_ENTITY, "entity:p", True, CandidateType.PRODUCT)
    split = chronology_split([_comparison(CandidateType.PRODUCT, unit, bucket=ChronologyBucket.BEFORE_CUTOFF)])
    assert split.product_overlap_artifact_dated_before_cutoff
    assert not split.patent_overlap_publication_dated_before_cutoff
    assert not split.product_historical_availability_proven and not split.legal_prior_art_established


@pytest.mark.parametrize(
    "field", ["product_historical_availability_proven", "oss_historical_public_visibility_proven",
              "legal_prior_art_established"],
)
def test_no_date_ever_proves_publicity_or_legal_prior_art(field):
    with pytest.raises(ValidationError, match="never proves"):
        ChronologySplit(**{field: True})


def test_after_cutoff_or_unknown_never_supports_a_before_cutoff_statement():
    with pytest.raises(ValidationError, match="same type"):
        ChronologySplit(overlap_by_type_bucket={"PATENT:AFTER_CUTOFF": 1},
                        patent_overlap_publication_dated_before_cutoff=True)
    with pytest.raises(ValidationError, match="same type"):
        ChronologySplit(overlap_by_type_bucket={"PRODUCT:BEFORE_CUTOFF": 1},
                        patent_overlap_publication_dated_before_cutoff=True)


# -- 6. exact anchors never guess an occurrence -----------------------------

REPEATED = "uses a thermal camera. Later, uses a thermal camera again."


def test_repeated_excerpt_with_valid_occurrence_index_binds_that_occurrence():
    located = locate(REPEATED, "uses a thermal camera", occurrence=2)
    assert located.occurrence_index == 2 and located.occurrence_count == 2
    assert located.start == REPEATED.rfind("uses a thermal camera")
    assert located.resolution is OccurrenceResolution.VALIDATED_OCCURRENCE_INDEX


def test_repeated_excerpt_with_exact_offsets_binds_that_occurrence():
    start = REPEATED.rfind("uses a thermal camera")
    located = locate(REPEATED, "uses a thermal camera", start=start, end=start + 21)
    assert located.occurrence_index == 2
    assert located.resolution is OccurrenceResolution.VALIDATED_EXACT_OFFSETS


def test_repeated_excerpt_without_disambiguation_is_rejected_as_ambiguous():
    assert locate(REPEATED, "uses a thermal camera") is LocateFailure.AMBIGUOUS


def test_invalid_offsets_and_occurrences_are_rejected_even_for_unique_text():
    assert locate(REPEATED, "uses a thermal camera", start=1, end=22) is LocateFailure.INVALID_OFFSETS
    assert locate(REPEATED, "uses a thermal camera", occurrence=3) is LocateFailure.INVALID_OCCURRENCE
    assert locate("only once here", "once", start=0, end=4) is LocateFailure.INVALID_OFFSETS
    assert locate("absent", "missing") is LocateFailure.NOT_FOUND


def test_anchor_contract_refuses_first_occurrence_guessing():
    with pytest.raises(ValidationError, match="first-occurrence"):
        _anchor(occurrence_count=2, occurrence_index=1, occurrence_resolution=OccurrenceResolution.UNIQUE_IN_TEXT)
