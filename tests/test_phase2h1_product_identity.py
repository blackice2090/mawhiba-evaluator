"""Phase 2H.1 -- byte-identical content must not prove product identity.

Content equality is artifact-level duplication. Only a validated strong
identifier (valid GTIN, app package id, brand-qualified MPN/model) may merge
listings into one ``ProductEntity``. Identical bytes are kept as a visible,
non-destructive ``IDENTICAL_CONTENT_HASH`` link between entities that stay
separate, and the run contract refuses both a content-only merge and a
dropped duplicate relation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.research.product.identity import resolve_entities
from src.schemas.product_prior_art import (
    ArtifactGroupingBasis,
    ProbableLinkBasis,
    ProductIdentityStatus,
    ProductPriorArtRun,
)
from tests.test_phase2h_product_oss_prior_art import GTIN, _ld, _page, _product

GTIN_B = "5901234123457"
A, B, C = "https://a.example.com/1", "https://b.example.com/2", "https://c.example.com/3"


def _hits(*urls):
    return [{"url": u} for u in urls]


def _content_links(entity):
    return {l.other_entity_id for l in entity.probable_links if l.basis is ProbableLinkBasis.IDENTICAL_CONTENT_HASH}


# 1. Byte-identical pages carrying different strong product identifiers.


def test_identical_bytes_with_different_strong_ids_remain_distinct_at_resolver():
    """Same hash, different GTINs: built directly, since a real page's
    identifiers always come from its bytes."""
    run, _ = _product(_hits(A, B), {A: _page("One", ld=_ld()), B: _page("Two", ld=_ld(gtin=GTIN_B, name="Two"))})
    first, second = sorted(run.artifacts, key=lambda a: a.original_url)
    forged = second.model_copy(update={"content_hash": first.content_hash})
    entities = resolve_entities([first, forged], run.research_run_id)
    assert len(entities) == 2
    assert {e.identity_key for e in entities} == {"gtin:0" + GTIN, "gtin:0" + GTIN_B}
    assert all(e.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY for e in entities)
    assert all(len(e.artifact_ids) == 1 for e in entities)
    a, b = entities
    assert _content_links(a) == {b.entity_id} and _content_links(b) == {a.entity_id}


def test_duplicated_page_carrying_two_gtins_is_never_collapsed():
    bundle = _page("Bundle", ld=_ld() + _ld(name="Other", gtin=GTIN_B))
    run, _ = _product(_hits(A, B), {A: bundle, B: bundle})
    assert len(run.entities) == 2
    assert all(e.identity_status is not ProductIdentityStatus.VERIFIED_STRONG_IDENTITY for e in run.entities)
    assert all(e.conflicting_strong_keys for e in run.entities)
    assert all(e.grouping_basis is ArtifactGroupingBasis.SINGLE_ARTIFACT for e in run.entities)


# 2. Byte-identical pages with no strong identifier.


def test_identical_bytes_without_strong_ids_are_not_verified_identity():
    page = _page("Same", ld=_ld(gtin=None, brand=None))
    run, _ = _product(_hits(A, B, C), {A: page, B: page, C: page})
    assert len(run.entities) == 3
    assert not any(e.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY for e in run.entities)
    assert all(e.identity_key is None and not e.strong_identifiers for e in run.entities)
    for entity in run.entities:
        assert _content_links(entity) == {e.entity_id for e in run.entities} - {entity.entity_id}
    assert run.distinct_product_count_upper_bound == 3
    assert run.distinct_product_count_lower_bound == 1


# 3. Duplicate URLs/content of the same strong product id: collapse because of the id.


def test_duplicate_content_with_same_strong_id_collapses_on_the_id():
    page = _page("Aqua", ld=_ld())
    run, _ = _product(_hits(A, B), {A: page, B: page})
    assert len(run.entities) == 1
    entity = run.entities[0]
    assert entity.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY
    assert entity.identity_key == "gtin:0" + GTIN
    assert entity.grouping_basis is ArtifactGroupingBasis.STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT
    assert len(entity.artifact_ids) == 2


def test_same_strong_id_on_different_pages_still_collapses():
    run, _ = _product(_hits(A, B), {A: _page("Shop A", ld=_ld()), B: _page("Shop B", body="<p>other</p>", ld=_ld())})
    assert len(run.entities) == 1
    assert run.entities[0].grouping_basis is ArtifactGroupingBasis.SHARED_STRONG_IDENTIFIER


def test_removing_the_strong_id_removes_the_merge():
    """The id, not the hash, is what merged them."""
    page = _page("Aqua", ld=_ld())
    run, _ = _product(_hits(A, B), {A: page, B: page})
    stripped = [a.model_copy(update={"identifiers": []}) for a in run.artifacts if a.fetched]
    entities = resolve_entities(stripped, run.research_run_id)
    assert len(entities) == 2
    assert not any(e.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY for e in entities)


# 4. Identical boilerplate / placeholder content across separate product pages.


@pytest.mark.parametrize(
    "placeholder",
    [
        "<p>Product coming soon.</p>",
        "<p>Page not available in your region.</p>",
        "<html></html>",
    ],
)
def test_identical_boilerplate_never_collapses_product_identity(placeholder):
    page = _page("Store", body=placeholder)
    run, _ = _product(_hits(A, B), {A: page, B: page})
    assert len(run.entities) == 2
    assert not any(len(e.artifact_ids) > 1 for e in run.entities)
    assert run.distinct_product_count_upper_bound == 2


# Contract: the run refuses a content-only merge and a dropped duplicate relation.


def _identical_pair():
    page = _page("Same", ld=_ld(gtin=None, brand=None))
    run, _ = _product(_hits(A, B), {A: page, B: page})
    return run


def test_contract_rejects_content_only_merge():
    run = _identical_pair()
    a, b = run.entities
    for basis in ArtifactGroupingBasis:
        if basis is ArtifactGroupingBasis.SINGLE_ARTIFACT:
            continue
        merged = a.model_copy(update={"artifact_ids": [*a.artifact_ids, *b.artifact_ids], "grouping_basis": basis,
                                      "probable_links": []})
        with pytest.raises(ValueError):
            ProductPriorArtRun.model_validate({**dict(run), "entities": [merged], "candidates": []})
        with pytest.raises(ValueError, match="multi-artifact entity requires a verified strong identity"):
            type(a).model_validate({**merged.model_dump(), "identity_status": "UNRESOLVED_IDENTITY"})


def test_contract_rejects_dropped_duplicate_relation():
    run = _identical_pair()
    # A consistent forgery: links dropped and status lowered to match.
    stripped = [e.model_copy(update={"probable_links": [], "identity_status": ProductIdentityStatus.UNRESOLVED_IDENTITY})
                for e in run.entities]
    with pytest.raises(ValueError, match="IDENTICAL_CONTENT_HASH"):
        ProductPriorArtRun.model_validate({**dict(run), "entities": stripped, "candidates": []})


def test_contract_rejects_verified_entity_with_conflicting_keys():
    bundle = _page("Bundle", ld=_ld() + _ld(name="Other", gtin=GTIN_B))
    run, _ = _product(_hits(A, B), {A: bundle, B: bundle})
    a, b = run.entities
    identifier = next(i for art in run.artifacts for i in art.identifiers if i.strong_key == "gtin:0" + GTIN)
    forged = a.model_copy(update={
        "artifact_ids": [*a.artifact_ids, *b.artifact_ids], "identity_status": ProductIdentityStatus.VERIFIED_STRONG_IDENTITY,
        "identity_key": "gtin:0" + GTIN, "strong_identifiers": [identifier], "conflicting_strong_keys": [],
        "probable_links": [], "grouping_basis": ArtifactGroupingBasis.STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT,
    })
    with pytest.raises(ValueError, match="different strong identifiers of one kind"):
        ProductPriorArtRun.model_validate({**dict(run), "entities": [forged], "candidates": []})


def test_contract_rederives_grouping_from_strong_keys_not_bytes():
    """A forged identity consistent at the entity level still fails the run's
    independent re-derivation when its members share bytes but no key."""
    plain = _page("Same", ld=_ld(gtin=None, brand=None))
    run, _ = _product(_hits(A, B, C), {A: plain, B: plain, C: _page("Keyed", ld=_ld())})
    keyed = next(e for e in run.entities if e.identity_key)
    duplicate = next(e for e in run.entities if not e.identity_key)
    forged = keyed.model_copy(update={"artifact_ids": [*keyed.artifact_ids, *duplicate.artifact_ids],
                                      "grouping_basis": ArtifactGroupingBasis.SHARED_STRONG_IDENTIFIER, "probable_links": []})
    rest = [e for e in run.entities if e.entity_id not in (keyed.entity_id, duplicate.entity_id)]
    with pytest.raises(ValueError, match="do not share a strong identifier"):
        ProductPriorArtRun.model_validate({**dict(run), "entities": [forged, *rest], "candidates": []})


def test_retired_content_grouping_basis_is_gone():
    assert "IDENTICAL_CONTENT_HASH" not in {b.value for b in ArtifactGroupingBasis}
    assert ProbableLinkBasis.IDENTICAL_CONTENT_HASH.value == "IDENTICAL_CONTENT_HASH"


def test_uuid_stability_of_split_entities_is_deterministic():
    page = _page("Same", ld=_ld(gtin=None, brand=None))
    run, _ = _product(_hits(A, B), {A: page, B: page})
    again = resolve_entities(run.artifacts, run.research_run_id)
    assert [e.entity_id for e in again] == [e.entity_id for e in run.entities]
    assert uuid4() not in {e.entity_id for e in again}
