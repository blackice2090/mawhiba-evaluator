"""Product identity, listing anti-inflation and candidates -- sections 16-20.

Grouping rule, the whole of it:

* Two fetched artifacts join one entity when they share a strong identifier
  key, or when their bytes are identical (one document served at two URLs).
* Nothing else merges. A shared retailer SKU, the same stated brand and
  product name, or the same unqualified model number is recorded as a
  *probable link* between two entities that stay separate.
* An entity whose artifacts carry two different strong keys (possible only via
  identical content) is never a verified identity; the conflict is recorded.

So twelve marketplace listings of one GTIN are one product, three listings of
a similar title are three entities with probable links, and the reader sees
both an upper bound (entities) and a lower bound (linked clusters).
"""

from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from src.schemas.discovery import (
    UNIVERSAL_DISCOVERY_LIMITATIONS,
    CandidateLimitation,
    CandidateQueryProvenance,
    DiscoveryCutoff,
    DiscoveryQuery,
    stable_id,
)
from src.schemas.product_prior_art import (
    FIRST_PARTY_ROLES,
    QUALIFYING_PRODUCT_DATE_FIELDS,
    ArtifactGroupingBasis,
    ProbableLinkBasis,
    ProbableProductLink,
    ProductArtifactSummary,
    ProductChronology,
    ProductCutoffQualification,
    ProductDateField,
    ProductEntity,
    ProductIdentifierKind,
    ProductIdentityStatus,
    ProductPriorArtCandidate,
    ProductSearchObservation,
    ProductSourceArtifact,
    ProductSourceRole,
)


def _fold(text: str) -> str:
    return re.sub(r"[^0-9a-z\u0600-\u06ff]+", "", text.casefold())


KEY_PRECEDENCE = ("gtin:", "app:", "manufacturer_part_number:", "manufacturer_model_number:")
"""Which strong key names an entity when its artifacts carry several kinds."""


def _same_kind_conflicts(members: list[ProductSourceArtifact]) -> list[str]:
    keys = sorted({k for a in members for k in a.strong_keys})
    conflicting: list[str] = []
    for prefix in KEY_PRECEDENCE:
        of_kind = [k for k in keys if k.startswith(prefix)]
        if len(of_kind) > 1:
            conflicting.extend(of_kind)
    return conflicting


def _canonical_key(members: list[ProductSourceArtifact]) -> str | None:
    keys = sorted({k for a in members for k in a.strong_keys})
    for prefix in KEY_PRECEDENCE:
        for key in keys:
            if key.startswith(prefix):
                return key
    return None


def resolve_entities(artifacts: list[ProductSourceArtifact], research_run_id: UUID) -> list[ProductEntity]:
    fetched = sorted((a for a in artifacts if a.fetched), key=lambda a: str(a.artifact_id))
    parent = {a.artifact_id: a.artifact_id for a in fetched}

    def find(x: UUID) -> UUID:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb, key=str)] = min(ra, rb, key=str)

    by_key: dict[str, list[UUID]] = defaultdict(list)
    by_hash: dict[str, list[UUID]] = defaultdict(list)
    for artifact in fetched:
        for key in artifact.strong_keys:
            by_key[key].append(artifact.artifact_id)
        by_hash[artifact.content_hash or ""].append(artifact.artifact_id)
    for ids in [*by_key.values(), *by_hash.values()]:
        for other in ids[1:]:
            union(ids[0], other)

    groups: dict[UUID, list[ProductSourceArtifact]] = defaultdict(list)
    for artifact in fetched:
        groups[find(artifact.artifact_id)].append(artifact)

    # A group holding two different keys of the same kind (two GTINs, two
    # brand+MPN values) is ambiguous. It is never merged on identifiers:
    # its members fall back to identical-content grouping only.
    settled: list[tuple[list[ProductSourceArtifact], list[str]]] = []
    for members in groups.values():
        conflicts = _same_kind_conflicts(members)
        if not conflicts or len(members) == 1:
            settled.append((members, conflicts))
            continue
        by_content: dict[str, list[ProductSourceArtifact]] = defaultdict(list)
        for artifact in members:
            by_content[artifact.content_hash or ""].append(artifact)
        settled.extend((part, _same_kind_conflicts(part)) for part in by_content.values())

    drafts: list[dict] = []
    for members, conflicts in settled:
        ids = {a.artifact_id for a in members}
        by_strong = len(members) > 1 and not conflicts and any(
            len(ids & set(key_ids)) > 1 for key_ids in by_key.values()
        )
        by_content = len(members) > len({a.content_hash for a in members})
        if len(members) == 1:
            basis = ArtifactGroupingBasis.SINGLE_ARTIFACT
        elif by_strong and by_content:
            basis = ArtifactGroupingBasis.STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT
        elif by_strong:
            basis = ArtifactGroupingBasis.SHARED_STRONG_IDENTIFIER
        else:
            basis = ArtifactGroupingBasis.IDENTICAL_CONTENT_HASH
        identity_key = None if conflicts else _canonical_key(members)
        entity_seed = identity_key or "artifacts:" + ",".join(sorted(str(a.artifact_id) for a in members))
        drafts.append(
            {
                "entity_id": stable_id(research_run_id, "product-entity", entity_seed),
                "members": members,
                "identity_key": identity_key,
                "conflicts": conflicts,
                "basis": basis,
            }
        )

    # Probable links: non-destructive, between separate entities only.
    signatures: dict[tuple[ProbableLinkBasis, str], set[UUID]] = defaultdict(set)
    for draft in drafts:
        for artifact in draft["members"]:
            for identifier in artifact.identifiers:
                if identifier.kind is ProductIdentifierKind.SKU:
                    signatures[(ProbableLinkBasis.SHARED_RETAILER_SKU, _fold(identifier.value))].add(draft["entity_id"])
                elif identifier.strong_key is None and identifier.kind in (
                    ProductIdentifierKind.MANUFACTURER_MODEL_NUMBER,
                    ProductIdentifierKind.MANUFACTURER_PART_NUMBER,
                ):
                    signatures[(ProbableLinkBasis.SAME_UNQUALIFIED_MODEL_NUMBER, _fold(identifier.value))].add(draft["entity_id"])
            for vendor in artifact.stated_vendor_names:
                for name in artifact.stated_product_names:
                    signatures[(ProbableLinkBasis.SAME_STATED_BRAND_AND_PRODUCT_NAME, f"{_fold(vendor)}|{_fold(name)}")].add(draft["entity_id"])
    links: dict[UUID, dict[UUID, ProbableLinkBasis]] = defaultdict(dict)
    for (basis, value), entity_ids in sorted(signatures.items(), key=lambda kv: (kv[0][0].value, kv[0][1])):
        if not value.strip("|") or len(entity_ids) < 2:
            continue
        for a in entity_ids:
            for b in entity_ids:
                if a != b:
                    links[a].setdefault(b, basis)

    entities: list[ProductEntity] = []
    for draft in sorted(drafts, key=lambda d: str(d["entity_id"])):
        members = draft["members"]
        identity_key = draft["identity_key"]
        own_links = [
            ProbableProductLink(other_entity_id=other, basis=basis)
            for other, basis in sorted(links[draft["entity_id"]].items(), key=lambda kv: str(kv[0]))
        ]
        if identity_key is not None and not draft["conflicts"]:
            status = ProductIdentityStatus.VERIFIED_STRONG_IDENTITY
        elif own_links:
            status = ProductIdentityStatus.PROBABLE_IDENTITY
        else:
            status = ProductIdentityStatus.UNRESOLVED_IDENTITY
        strong = [
            i for a in members for i in a.identifiers if identity_key and i.strong_key == identity_key
        ]
        unique_strong = list({(i.kind, i.value): i for i in strong}.values())
        entities.append(
            ProductEntity(
                entity_id=draft["entity_id"],
                research_run_id=research_run_id,
                identity_status=status,
                identity_key=identity_key if status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY else None,
                grouping_basis=draft["basis"],
                artifact_ids=sorted((a.artifact_id for a in members), key=str),
                strong_identifiers=unique_strong if status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY else [],
                conflicting_strong_keys=draft["conflicts"],
                probable_links=own_links,
                stated_product_names=sorted({n for a in members for n in a.stated_product_names}),
                stated_vendor_names=sorted({n for a in members for n in a.stated_vendor_names}),
            )
        )
    return entities


def qualify(
    artifacts: list[ProductSourceArtifact], cutoff: DiscoveryCutoff
) -> ProductChronology:
    """Earliest source-reported qualifying date across an entity's artifacts."""
    dated: list[tuple[str, ProductDateField, UUID]] = []
    for artifact in artifacts:
        for field, attribute in QUALIFYING_PRODUCT_DATE_FIELDS.items():
            value = getattr(artifact.dates, attribute)
            if value is not None:
                dated.append((value, field, artifact.artifact_id))
    earliest = min(dated, key=lambda d: (d[0], d[1].value, str(d[2]))) if dated else None
    if not cutoff.supplied:
        qualification = ProductCutoffQualification.NO_CUTOFF
    elif earliest is None:
        qualification = ProductCutoffQualification.ARTIFACT_DATE_UNKNOWN
    elif earliest[0] < cutoff.cutoff_date:
        qualification = ProductCutoffQualification.DATED_ARTIFACT_BEFORE_CUTOFF
    elif earliest[0] == cutoff.cutoff_date:
        qualification = ProductCutoffQualification.DATED_ARTIFACT_ON_CUTOFF
    else:
        qualification = ProductCutoffQualification.DATED_ARTIFACT_AFTER_CUTOFF
    return ProductChronology(
        qualification=qualification,
        date_field_used=earliest[1] if earliest else None,
        date_value=earliest[0] if earliest else None,
        date_artifact_id=earliest[2] if earliest else None,
        cutoff_date=cutoff.cutoff_date,
    )


def build_product_candidates(
    entities: list[ProductEntity],
    artifacts: list[ProductSourceArtifact],
    observations: list[ProductSearchObservation],
    queries: list[DiscoveryQuery],
    cutoff: DiscoveryCutoff,
    research_run_id: UUID,
) -> list[ProductPriorArtCandidate]:
    by_artifact = {a.artifact_id: a for a in artifacts}
    by_observation = {o.observation_id: o for o in observations}
    by_query = {q.query_id: q for q in queries}
    candidates: list[ProductPriorArtCandidate] = []
    for entity in entities:
        members = [by_artifact[a] for a in entity.artifact_ids]
        observation_ids = sorted({o for a in members for o in a.observation_ids}, key=str)
        provenance: dict[UUID, CandidateQueryProvenance] = {}
        for observation_id in observation_ids:
            observation = by_observation[observation_id]
            query = by_query[observation.query_id]
            existing = provenance.get(query.query_id)
            if existing is None or observation.retrieval_rank < existing.retrieval_rank:
                provenance[query.query_id] = CandidateQueryProvenance(
                    query_id=query.query_id,
                    purpose=query.purpose,
                    operation=query.operation,
                    language=query.language,
                    claim_ids=query.claim_ids,
                    component_ids=query.component_ids,
                    retrieval_rank=observation.retrieval_rank,
                )
        chronology = qualify(members, cutoff)
        roles = sorted({a.source_role for a in members}, key=str)
        limitations = list(UNIVERSAL_DISCOVERY_LIMITATIONS) + [
            CandidateLimitation.CURRENT_AVAILABILITY_NOT_HISTORICAL,
            CandidateLimitation.DATES_ARE_SOURCE_REPORTED,
        ]
        if entity.identity_status is ProductIdentityStatus.UNRESOLVED_IDENTITY:
            limitations.append(CandidateLimitation.PRODUCT_IDENTITY_UNRESOLVED)
        if entity.identity_status is ProductIdentityStatus.PROBABLE_IDENTITY:
            limitations.append(CandidateLimitation.PRODUCT_IDENTITY_PROBABLE_ONLY)
        if ProductSourceRole.UNKNOWN in roles:
            limitations.append(CandidateLimitation.SOURCE_ROLE_UNKNOWN)
        if not set(roles) & FIRST_PARTY_ROLES:
            limitations.append(CandidateLimitation.NO_FIRST_PARTY_SOURCE)
        if not cutoff.supplied:
            limitations.append(CandidateLimitation.NO_CUTOFF_SUPPLIED)
        if chronology.date_value is None:
            limitations.append(CandidateLimitation.ARTIFACT_DATE_UNKNOWN)
        queries_used = list(provenance.values())
        candidates.append(
            ProductPriorArtCandidate(
                candidate_id=stable_id(research_run_id, "product-candidate", entity.entity_id),
                research_run_id=research_run_id,
                entity_id=entity.entity_id,
                identity_status=entity.identity_status,
                identity_key=entity.identity_key,
                artifacts=[
                    ProductArtifactSummary(
                        artifact_id=a.artifact_id,
                        final_url=a.final_url or a.original_url,
                        host=a.host,
                        source_role=a.source_role,
                        content_hash=a.content_hash or "",
                        dates=a.dates,
                    )
                    for a in members
                ],
                source_roles=roles,
                stated_product_names=entity.stated_product_names,
                stated_vendor_names=entity.stated_vendor_names,
                strong_identifiers=entity.strong_identifiers,
                probable_link_entity_ids=[l.other_entity_id for l in entity.probable_links],
                chronology=chronology,
                query_provenance=sorted(queries_used, key=lambda p: str(p.query_id)),
                observation_ids=observation_ids,
                claim_ids=sorted({c for p in queries_used for c in p.claim_ids}),
                component_ids=sorted({c for p in queries_used for c in p.component_ids}),
                limitations=limitations,
            )
        )
    return candidates


__all__ = ["build_product_candidates", "qualify", "resolve_entities"]
