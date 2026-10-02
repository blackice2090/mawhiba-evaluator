"""Pins the full-claim relation labels and the chronology-qualified overlap boundary.

``COMPONENT_ONLY_OVERLAP`` is the taxonomy label for a standalone feature overlap
(component, function, mechanism, other) where no relationship-bearing feature
overlaps and the combination is not established. Overlap on a relationship-bearing
feature (relationship, sequence, constraint) is ``PARTIAL_CLAIM_TECHNICAL_OVERLAP``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.research.novelty.synthesis import OVERLAPPING_RELATIONS
from src.schemas.novelty_differentiation import (
    FeatureComparisonRecord,
    FeatureRelation,
    FeatureType,
    FullClaimRelation,
    derive_full_claim_relation,
)

R = FeatureRelation


def _rec(ftype: FeatureType, relation: FeatureRelation) -> FeatureComparisonRecord:
    anchored = relation in (R.DISCLOSED, R.PARTIALLY_DISCLOSED, R.RELATED_CONTEXT)
    return FeatureComparisonRecord(
        feature_id=uuid4(), feature_type=ftype, relation=relation, anchor_ids=[uuid4()] if anchored else []
    )


def test_chronology_qualified_overlap_is_exactly_the_three_material_relations():
    assert OVERLAPPING_RELATIONS == {
        FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP,
        FullClaimRelation.PARTIAL_CLAIM_TECHNICAL_OVERLAP,
        FullClaimRelation.COMPONENT_ONLY_OVERLAP,
    }
    for non_overlap in (
        FullClaimRelation.CONTEXT_ONLY,
        FullClaimRelation.NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT,
        FullClaimRelation.INSUFFICIENT_SOURCE_TEXT,
    ):
        assert non_overlap not in OVERLAPPING_RELATIONS


@pytest.mark.parametrize("ftype", [FeatureType.COMPONENT, FeatureType.FUNCTION, FeatureType.MECHANISM])
def test_standalone_feature_overlap_without_the_combination_is_component_only(ftype):
    records = [_rec(ftype, R.DISCLOSED), _rec(FeatureType.COMBINATION, R.NOT_DISCLOSED)]
    assert derive_full_claim_relation(records) is FullClaimRelation.COMPONENT_ONLY_OVERLAP


@pytest.mark.parametrize("ftype", [FeatureType.RELATIONSHIP, FeatureType.SEQUENCE, FeatureType.CONSTRAINT])
def test_relationship_bearing_overlap_is_partial_not_component_only(ftype):
    records = [_rec(ftype, R.DISCLOSED), _rec(FeatureType.COMBINATION, R.NOT_DISCLOSED)]
    assert derive_full_claim_relation(records) is FullClaimRelation.PARTIAL_CLAIM_TECHNICAL_OVERLAP


def test_all_components_disclosed_but_combination_not_is_never_full():
    records = [_rec(FeatureType.COMPONENT, R.DISCLOSED), _rec(FeatureType.COMPONENT, R.DISCLOSED),
               _rec(FeatureType.COMBINATION, R.NOT_DISCLOSED)]
    assert derive_full_claim_relation(records) is FullClaimRelation.COMPONENT_ONLY_OVERLAP


def test_context_only_and_unresolved_are_not_overlap():
    context = [_rec(FeatureType.COMPONENT, R.RELATED_CONTEXT)]
    assert derive_full_claim_relation(context) is FullClaimRelation.CONTEXT_ONLY
    none = [_rec(FeatureType.COMPONENT, R.NOT_DISCLOSED)]
    assert derive_full_claim_relation(none) is FullClaimRelation.NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT
    unresolved = [_rec(FeatureType.COMPONENT, R.INSUFFICIENT_SOURCE_TEXT)]
    assert derive_full_claim_relation(unresolved) is FullClaimRelation.INSUFFICIENT_SOURCE_TEXT
    for records in (context, none, unresolved):
        assert derive_full_claim_relation(records) not in OVERLAPPING_RELATIONS
