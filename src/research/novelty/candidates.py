"""Candidate comparison profiles -- Phase 2I sections 10-13, 20-22.

One deterministic profile per Phase 2G/2H candidate: which texts it offers,
what each text can support (``DisclosureCapacity``), which independence unit
it belongs to, and its chronology -- all read from the candidate's own phase
records, never re-interpreted. The three candidate families stay distinct.

``resolve_text`` is the single place a profile text is turned back into the
exact string it came from; anchors are always re-sliced from that string.
"""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from src.schemas.novelty_differentiation import (
    CORRELATION_GROUP_PREFIX,
    CandidateChronology,
    CandidateComparisonProfile,
    CandidateEligibility,
    CandidateRef,
    CandidateSourceQualityProfile,
    CandidateType,
    ChronologyBasis,
    ChronologyBucket,
    ComparableText,
    DisclosureCapacity,
    EligibilityReason,
    FullTextStatus,
    HistoricalVisibility,
    IndependenceUnit,
    IndependenceUnitKind,
    ScopeLimitation,
    SourceRecordKind,
    TextKind,
    novelty_id,
)
from src.schemas.open_source_prior_art import (
    OpenSourcePriorArtCandidate,
    OpenSourcePriorArtRun,
    RepositorySnapshotKind,
)
from src.schemas.patent import (
    RESOLVED_FAMILY_STATUSES,
    PatentContentType,
    PatentFamilyStatus,
    PatentPriorArtCandidate,
    PatentPriorArtRun,
    PatentTextScope,
)
from src.schemas.product_prior_art import (
    ProductIdentityStatus,
    ProductPriorArtCandidate,
    ProductPriorArtRun,
    ProductSourceRole,
)
from src.schemas.research import ResearchRun

KIND_ORDER: dict[DisclosureCapacity, int] = {
    DisclosureCapacity.MATERIAL: 0,
    DisclosureCapacity.LIMITED: 1,
    DisclosureCapacity.NON_MATERIAL: 2,
}

_BUCKETS: dict[str, ChronologyBucket] = {
    "PUBLIC_BEFORE_CUTOFF": ChronologyBucket.BEFORE_CUTOFF,
    "PUBLIC_ON_CUTOFF": ChronologyBucket.ON_CUTOFF,
    "PUBLIC_AFTER_CUTOFF": ChronologyBucket.AFTER_CUTOFF,
    "PUBLICATION_DATE_UNKNOWN": ChronologyBucket.DATE_UNKNOWN,
    "DATED_ARTIFACT_BEFORE_CUTOFF": ChronologyBucket.BEFORE_CUTOFF,
    "DATED_ARTIFACT_ON_CUTOFF": ChronologyBucket.ON_CUTOFF,
    "DATED_ARTIFACT_AFTER_CUTOFF": ChronologyBucket.AFTER_CUTOFF,
    "DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF": ChronologyBucket.BEFORE_CUTOFF,
    "DATED_REPOSITORY_ARTIFACT_ON_CUTOFF": ChronologyBucket.ON_CUTOFF,
    "DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF": ChronologyBucket.AFTER_CUTOFF,
    "ARTIFACT_DATE_UNKNOWN": ChronologyBucket.DATE_UNKNOWN,
    "NO_CUTOFF": ChronologyBucket.NO_CUTOFF,
}


def digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def bucket_for(qualification: str) -> ChronologyBucket:
    return _BUCKETS[qualification]


# ---------------------------------------------------------------------------
# Text resolution
# ---------------------------------------------------------------------------


def resolve_text(run: ResearchRun, text: ComparableText) -> str | None:
    """The exact string a profile text refers to, read from its source record."""
    kind = text.source_record_kind
    if kind is SourceRecordKind.PATENT_TEXT_SNAPSHOT and run.patent_prior_art:
        return next((s.text for s in run.patent_prior_art.snapshots if s.snapshot_id == text.source_record_id), None)
    if kind is SourceRecordKind.PATENT_CANDIDATE_FIELD and run.patent_prior_art:
        return next((c.title for c in run.patent_prior_art.candidates if c.candidate_id == text.source_record_id), None)
    if kind is SourceRecordKind.PRODUCT_SOURCE_ARTIFACT and run.product_prior_art:
        return next((a.text_snapshot for a in run.product_prior_art.artifacts if a.artifact_id == text.source_record_id), None)
    if kind is SourceRecordKind.PRODUCT_ARTIFACT_FIELD and run.product_prior_art:
        return next((a.title for a in run.product_prior_art.artifacts if a.artifact_id == text.source_record_id), None)
    if kind is SourceRecordKind.REPOSITORY_SNAPSHOT and run.open_source_prior_art:
        return next((s.text for s in run.open_source_prior_art.snapshots if s.snapshot_id == text.source_record_id), None)
    return None


def _text(
    ref: UUID, record_kind: SourceRecordKind, record_id: UUID, kind: TextKind, capacity: DisclosureCapacity,
    value: str, *, limitations: list[ScopeLimitation] | None = None, content_hash: str | None = None,
    truncated: bool = False, language: str | None = None, role: str | None = None,
) -> ComparableText:
    scopes = list(limitations or [])
    if truncated:
        scopes.append(ScopeLimitation.TEXT_TRUNCATED_UPSTREAM)
    return ComparableText(
        text_ref_id=ref, source_record_kind=record_kind, source_record_id=record_id, text_kind=kind,
        capacity=capacity, scope_limitations=scopes, content_hash=content_hash, text_digest=digest(value),
        char_count=len(value), truncated_upstream=truncated, language=language, product_source_role=role,
    )


def _bounded(texts: list[ComparableText], limit: int) -> tuple[list[ComparableText], int]:
    ordered = sorted(texts, key=lambda t: (KIND_ORDER[t.capacity], t.text_kind.value, str(t.text_ref_id)))
    return ordered[:limit], max(0, len(ordered) - limit)


def _eligibility(
    texts: list[ComparableText], invalid: list[EligibilityReason], blocked: list[EligibilityReason]
) -> tuple[CandidateEligibility, list[EligibilityReason]]:
    if invalid:
        return CandidateEligibility.INVALID_CANDIDATE_REFERENCE, invalid
    if blocked:
        return CandidateEligibility.BLOCKED_SOURCE_QUALITY, blocked
    capacities = {t.capacity for t in texts}
    if DisclosureCapacity.MATERIAL in capacities:
        return CandidateEligibility.ELIGIBLE_FOR_TECHNICAL_COMPARISON, [EligibilityReason.MATERIAL_TEXT_AVAILABLE]
    if DisclosureCapacity.LIMITED in capacities:
        return CandidateEligibility.LIMITED_TEXT_COMPARISON, [EligibilityReason.ONLY_LIMITED_TEXT_AVAILABLE]
    if texts:
        return CandidateEligibility.METADATA_ONLY_NOT_COMPARABLE, [EligibilityReason.ONLY_METADATA_TEXT_AVAILABLE]
    return CandidateEligibility.CONTENT_UNAVAILABLE, [EligibilityReason.NO_TEXT_AVAILABLE]


def _full_text_status(texts: list[ComparableText]) -> FullTextStatus:
    if any(t.capacity is DisclosureCapacity.MATERIAL and not t.truncated_upstream for t in texts):
        return FullTextStatus.COMPLETE_TEXT_AVAILABLE
    return FullTextStatus.PARTIAL_TEXT_ONLY if texts else FullTextStatus.NO_TEXT


def _limitations(upstream: list[str], omitted: int) -> list[str]:
    return list(upstream) + ([f"TEXTS_OMITTED_BY_LIMIT:{omitted}"] if omitted else [])


# ---------------------------------------------------------------------------
# Patent
# ---------------------------------------------------------------------------

_PATENT_KIND = {
    PatentContentType.CLAIMS: (TextKind.PATENT_CLAIMS, DisclosureCapacity.MATERIAL, []),
    PatentContentType.DESCRIPTION: (TextKind.PATENT_DESCRIPTION, DisclosureCapacity.MATERIAL, []),
    PatentContentType.ABSTRACT: (TextKind.PATENT_ABSTRACT, DisclosureCapacity.LIMITED, [ScopeLimitation.ABSTRACT_SCOPE_ONLY]),
}


def patent_unit(candidate: PatentPriorArtCandidate) -> IndependenceUnit:
    """Only a family status Phase 2G established makes an independent unit.

    VERIFIED_FAMILY -> PATENT_FAMILY; SINGLETON_FAMILY -> PATENT_SINGLETON_FAMILY;
    anything else (unavailable, failed, not requested) -> unresolved and NOT
    independent: the publication is still compared, but two such publications
    are never two independent inventions.
    """
    status = candidate.family_status
    if status is PatentFamilyStatus.VERIFIED_FAMILY and candidate.family_group_id is not None:
        return IndependenceUnit(candidate_type=CandidateType.PATENT, unit_kind=IndependenceUnitKind.PATENT_FAMILY,
                                unit_key=f"family:{candidate.family_group_id}", counts_as_independent=True)
    if status is PatentFamilyStatus.SINGLETON_FAMILY:
        key = f"family:{candidate.family_group_id}" if candidate.family_group_id else f"singleton:{candidate.publication_key}"
        return IndependenceUnit(candidate_type=CandidateType.PATENT,
                                unit_kind=IndependenceUnitKind.PATENT_SINGLETON_FAMILY,
                                unit_key=key, counts_as_independent=True)
    return IndependenceUnit(candidate_type=CandidateType.PATENT,
                            unit_kind=IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED,
                            unit_key=f"publication:{candidate.publication_key}", counts_as_independent=False)


def patent_profile(
    nd_run_id: UUID, research_run_id: UUID, run: PatentPriorArtRun, candidate: PatentPriorArtCandidate,
    known_claims: set[str], max_texts: int,
) -> CandidateComparisonProfile:
    snapshots = {s.snapshot_id: s for s in run.snapshots}
    invalid: list[EligibilityReason] = []
    texts: list[ComparableText] = []
    for snapshot_id in candidate.snapshot_ids:
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None or snapshot.publication_key != candidate.publication_key:
            invalid.append(EligibilityReason.SNAPSHOT_REFERENCE_UNRESOLVED)
            continue
        if snapshot.content_type not in _PATENT_KIND:
            continue
        kind, capacity, scopes = _PATENT_KIND[snapshot.content_type]
        texts.append(_text(
            snapshot.snapshot_id, SourceRecordKind.PATENT_TEXT_SNAPSHOT, snapshot.snapshot_id, kind, capacity,
            snapshot.text, limitations=scopes, content_hash=snapshot.content_hash,
            truncated=snapshot.scope is not PatentTextScope.COMPLETE_AS_PROVIDED, language=snapshot.language,
        ))
    if candidate.title:
        texts.append(_text(
            novelty_id(candidate.candidate_id, "title"), SourceRecordKind.PATENT_CANDIDATE_FIELD,
            candidate.candidate_id, TextKind.PATENT_TITLE, DisclosureCapacity.NON_MATERIAL, candidate.title,
            limitations=[ScopeLimitation.TITLE_IS_NOT_DISCLOSURE],
        ))
    family_ids = {f.family_group_id for f in run.families}
    if candidate.family_group_id is not None and candidate.family_group_id not in family_ids:
        invalid.append(EligibilityReason.GROUP_REFERENCE_UNRESOLVED)
    texts, omitted = _bounded(texts, max_texts)
    eligibility, reasons = _eligibility(texts if not invalid else [], sorted(set(invalid)), [])
    if invalid:
        texts = []
    unit = patent_unit(candidate)
    date = candidate.dates.first_public_date
    bucket = bucket_for(candidate.time_qualification.value)
    chronology = CandidateChronology(
        bucket=bucket,
        basis=ChronologyBasis.PATENT_FIRST_PUBLIC_DATE if date else ChronologyBasis.NO_DATE,
        upstream_qualification=candidate.time_qualification.value,
        date_field=("PUBLICATION_DATE" if candidate.dates.publication_date else "GRANT_DATE") if date else None,
        date_value=date,
        cutoff_date=candidate.cutoff_date,
        historical_visibility=(
            HistoricalVisibility.PATENT_PUBLICATION_DATE_RECORDED if date else HistoricalVisibility.UNKNOWN
        ),
        public_availability_proven=bool(date),
    )
    linked = sorted({c for p in candidate.query_provenance for c in p.claim_ids} & known_claims)
    return CandidateComparisonProfile(
        profile_id=novelty_id(nd_run_id, "profile", CandidateType.PATENT.value, candidate.candidate_id),
        nd_run_id=nd_run_id, research_run_id=research_run_id,
        candidate_ref=CandidateRef(candidate_type=CandidateType.PATENT, candidate_id=candidate.candidate_id,
                                   source_run_id=run.patent_run_id, identity_key=candidate.publication_key),
        linked_claim_ids=linked, eligibility=eligibility, eligibility_reasons=reasons,
        independence_unit=unit, chronology=chronology,
        quality=CandidateSourceQualityProfile(
            identity_verified=True, identity_status=candidate.family_status.value,
            available_text_kinds=[t.text_kind for t in texts], exact_text_available=bool(texts),
            full_text_status=_full_text_status(texts), chronology_known=bool(date),
            historical_visibility_proven=bool(date),
            candidate_group_resolved=candidate.family_status in RESOLVED_FAMILY_STATUSES,
            source_limitations=_limitations([l.value for l in candidate.limitations], omitted),
        ),
        texts=texts,
    )


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

_ROLE_POLICY: dict[ProductSourceRole, tuple[DisclosureCapacity, list[ScopeLimitation]]] = {
    ProductSourceRole.FIRST_PARTY_DOCUMENTATION: (DisclosureCapacity.MATERIAL, []),
    ProductSourceRole.FIRST_PARTY_PRODUCT_PAGE: (DisclosureCapacity.LIMITED, [ScopeLimitation.VENDOR_MARKETING_TEXT]),
    ProductSourceRole.FIRST_PARTY_PRESS_RELEASE: (DisclosureCapacity.LIMITED, [ScopeLimitation.VENDOR_MARKETING_TEXT]),
    ProductSourceRole.MARKETPLACE_LISTING: (DisclosureCapacity.LIMITED, [ScopeLimitation.THIRD_PARTY_OR_MARKETPLACE_TEXT]),
    ProductSourceRole.THIRD_PARTY_REVIEW: (DisclosureCapacity.LIMITED, [ScopeLimitation.THIRD_PARTY_OR_MARKETPLACE_TEXT]),
    ProductSourceRole.THIRD_PARTY_DIRECTORY: (DisclosureCapacity.LIMITED, [ScopeLimitation.THIRD_PARTY_OR_MARKETPLACE_TEXT]),
    ProductSourceRole.UNKNOWN: (DisclosureCapacity.LIMITED, [ScopeLimitation.SOURCE_ROLE_UNKNOWN]),
}


def product_clusters(run: ProductPriorArtRun) -> dict[UUID, set[UUID]]:
    """Entity -> every entity it is linked to by a probable or duplicate-content
    link, transitively. An unresolved correlation for anti-inflation only:
    nothing here merges entities or asserts they are one product."""
    parent = {e.entity_id: e.entity_id for e in run.entities}

    def find(x: UUID) -> UUID:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for entity in run.entities:
        for link in entity.probable_links:
            if link.other_entity_id in parent:
                parent[find(entity.entity_id)] = find(link.other_entity_id)
    groups: dict[UUID, set[UUID]] = {}
    for entity_id in parent:
        groups.setdefault(find(entity_id), set()).add(entity_id)
    return {entity_id: groups[find(entity_id)] for entity_id in parent}


def product_profile(
    nd_run_id: UUID, research_run_id: UUID, run: ProductPriorArtRun, candidate: ProductPriorArtCandidate,
    known_claims: set[str], max_texts: int, clusters: dict[UUID, set[UUID]],
) -> CandidateComparisonProfile:
    artifacts = {a.artifact_id: a for a in run.artifacts}
    entity = next((e for e in run.entities if e.entity_id == candidate.entity_id), None)
    invalid: list[EligibilityReason] = []
    blocked: list[EligibilityReason] = []
    texts: list[ComparableText] = []
    if entity is None:
        invalid.append(EligibilityReason.GROUP_REFERENCE_UNRESOLVED)
    for summary in candidate.artifacts:
        artifact = artifacts.get(summary.artifact_id)
        if artifact is None:
            invalid.append(EligibilityReason.SNAPSHOT_REFERENCE_UNRESOLVED)
            continue
        if not artifact.fetched:
            continue
        if artifact.text_snapshot:
            capacity, scopes = _ROLE_POLICY[artifact.source_role]
            texts.append(_text(
                artifact.artifact_id, SourceRecordKind.PRODUCT_SOURCE_ARTIFACT, artifact.artifact_id,
                TextKind.PRODUCT_PAGE_TEXT, capacity, artifact.text_snapshot, limitations=scopes,
                content_hash=artifact.content_hash, truncated=artifact.text_truncated,
                role=artifact.source_role.value,
            ))
        if artifact.title:
            texts.append(_text(
                novelty_id(artifact.artifact_id, "title"), SourceRecordKind.PRODUCT_ARTIFACT_FIELD,
                artifact.artifact_id, TextKind.PRODUCT_PAGE_TITLE, DisclosureCapacity.NON_MATERIAL, artifact.title,
                limitations=[ScopeLimitation.TITLE_IS_NOT_DISCLOSURE],
            ))
    if entity is not None and entity.conflicting_strong_keys:
        blocked.append(EligibilityReason.PRODUCT_IDENTITY_CONFLICT)
    texts, omitted = _bounded(texts, max_texts)
    invalid = sorted(set(invalid))
    eligibility, reasons = _eligibility(texts if not invalid else [], invalid, blocked)
    if invalid:
        texts = []
    cluster = clusters.get(candidate.entity_id, {candidate.entity_id})
    strong = candidate.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY
    # Every ProductEntity stays its own unit, exactly as Phase 2H(.1) resolved
    # it. Probable / identical-content links only attach an UNRESOLVED
    # correlation group that caps joint corroboration at one.
    unit = IndependenceUnit(
        candidate_type=CandidateType.PRODUCT,
        unit_kind=(IndependenceUnitKind.PRODUCT_STRONG_ENTITY if strong
                   else IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY),
        unit_key=f"entity:{candidate.entity_id}",
        counts_as_independent=True,
        correlation_group_key=(
            f"{CORRELATION_GROUP_PREFIX}{min(str(e) for e in cluster)}" if len(cluster) > 1 else None
        ),
    )
    c = candidate.chronology
    dated = c.date_value is not None
    chronology = CandidateChronology(
        bucket=bucket_for(c.qualification.value),
        basis=ChronologyBasis.PRODUCT_SOURCE_REPORTED_DATE if dated else ChronologyBasis.NO_DATE,
        upstream_qualification=c.qualification.value,
        date_field=c.date_field_used.value if c.date_field_used else None,
        date_value=c.date_value, cutoff_date=c.cutoff_date,
        historical_visibility=(
            HistoricalVisibility.NOT_PROVEN_SOURCE_REPORTED_DATE if dated else HistoricalVisibility.UNKNOWN
        ),
        public_availability_proven=False,
    )
    return CandidateComparisonProfile(
        profile_id=novelty_id(nd_run_id, "profile", CandidateType.PRODUCT.value, candidate.candidate_id),
        nd_run_id=nd_run_id, research_run_id=research_run_id,
        candidate_ref=CandidateRef(candidate_type=CandidateType.PRODUCT, candidate_id=candidate.candidate_id,
                                   source_run_id=run.product_run_id,
                                   identity_key=candidate.identity_key or f"entity:{candidate.entity_id}"),
        linked_claim_ids=sorted(set(candidate.claim_ids) & known_claims),
        eligibility=eligibility, eligibility_reasons=reasons, independence_unit=unit, chronology=chronology,
        quality=CandidateSourceQualityProfile(
            identity_verified=strong, identity_status=candidate.identity_status.value,
            source_roles=sorted({r.value for r in candidate.source_roles}),
            available_text_kinds=[t.text_kind for t in texts], exact_text_available=bool(texts),
            full_text_status=_full_text_status(texts), chronology_known=dated,
            historical_visibility_proven=False, candidate_group_resolved=strong,
            source_limitations=_limitations([l.value for l in candidate.limitations], omitted),
        ),
        texts=texts,
    )


# ---------------------------------------------------------------------------
# Open source
# ---------------------------------------------------------------------------


def _oss_policy(kind: RepositorySnapshotKind, full_file: bool, truncated: bool):
    if kind is RepositorySnapshotKind.MANIFEST:
        if full_file and not truncated:
            return TextKind.OSS_MANIFEST, DisclosureCapacity.MATERIAL, []
        return TextKind.OSS_MANIFEST, DisclosureCapacity.LIMITED, [ScopeLimitation.MANIFEST_NOT_FULL_FILE]
    return {
        RepositorySnapshotKind.README: (TextKind.OSS_README, DisclosureCapacity.LIMITED,
                                        [ScopeLimitation.README_IS_DOCUMENTATION_NOT_IMPLEMENTATION]),
        RepositorySnapshotKind.CODE_SEARCH_FRAGMENT: (TextKind.OSS_CODE_FRAGMENT, DisclosureCapacity.LIMITED,
                                                      [ScopeLimitation.CODE_FRAGMENT_NOT_FULL_FILE]),
        RepositorySnapshotKind.DESCRIPTION: (TextKind.OSS_DESCRIPTION, DisclosureCapacity.NON_MATERIAL,
                                             [ScopeLimitation.REPOSITORY_METADATA_NOT_IMPLEMENTATION]),
        RepositorySnapshotKind.TOPICS: (TextKind.OSS_TOPICS, DisclosureCapacity.NON_MATERIAL,
                                        [ScopeLimitation.REPOSITORY_METADATA_NOT_IMPLEMENTATION]),
        RepositorySnapshotKind.RELEASE_METADATA: (TextKind.OSS_RELEASE_METADATA, DisclosureCapacity.NON_MATERIAL,
                                                  [ScopeLimitation.RELEASE_METADATA_IS_CHRONOLOGY]),
    }[kind]


def oss_profile(
    nd_run_id: UUID, research_run_id: UUID, run: OpenSourcePriorArtRun, candidate: OpenSourcePriorArtCandidate,
    known_claims: set[str], max_texts: int,
) -> CandidateComparisonProfile:
    snapshots = {s.snapshot_id: s for s in run.snapshots}
    invalid: list[EligibilityReason] = []
    blocked: list[EligibilityReason] = []
    texts: list[ComparableText] = []
    for snapshot_id in candidate.snapshot_ids:
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None or snapshot.repository_key != candidate.repository_key:
            invalid.append(EligibilityReason.SNAPSHOT_REFERENCE_UNRESOLVED)
            continue
        if not snapshot.text.strip():
            continue
        kind, capacity, scopes = _oss_policy(snapshot.kind, snapshot.is_full_file, snapshot.truncated)
        texts.append(_text(
            snapshot.snapshot_id, SourceRecordKind.REPOSITORY_SNAPSHOT, snapshot.snapshot_id, kind, capacity,
            snapshot.text, limitations=scopes, content_hash=snapshot.content_hash, truncated=snapshot.truncated,
            language=snapshot.language,
        ))
    repository = run.repository(candidate.repository_key)
    network = next((n for n in run.networks if n.network_id == candidate.network_id), None)
    if repository is None or network is None:
        invalid.append(EligibilityReason.GROUP_REFERENCE_UNRESOLVED)
    elif repository.disabled:
        blocked.append(EligibilityReason.REPOSITORY_DISABLED)
    texts, omitted = _bounded(texts, max_texts)
    invalid = sorted(set(invalid))
    eligibility, reasons = _eligibility(texts if not invalid else [], invalid, blocked)
    if invalid:
        texts = []
    # Independent only when THIS candidate is the independent root. A fork or
    # mirror found inside an independent-root network shares its network key
    # but never contributes an independent corroboration unit by itself.
    independent = bool(network and network.independent_root and candidate.counts_as_independent_root)
    unit = IndependenceUnit(
        candidate_type=CandidateType.OPEN_SOURCE,
        unit_kind=(IndependenceUnitKind.OSS_INDEPENDENT_ROOT_NETWORK if independent
                   else IndependenceUnitKind.OSS_DEPENDENT_NETWORK),
        unit_key=f"network:{candidate.network_id}", counts_as_independent=independent,
    )
    c = candidate.chronology
    dated = c.date_value is not None
    chronology = CandidateChronology(
        bucket=bucket_for(c.qualification.value),
        basis=ChronologyBasis.REPOSITORY_PROVIDER_DATE if dated else ChronologyBasis.NO_DATE,
        upstream_qualification=c.qualification.value,
        date_field=c.date_field_used.value if c.date_field_used else None,
        date_value=c.date_value, cutoff_date=c.cutoff_date,
        historical_visibility=HistoricalVisibility.NOT_PROVEN_PROVIDER_DATE if dated else HistoricalVisibility.UNKNOWN,
        public_availability_proven=False,
    )
    return CandidateComparisonProfile(
        profile_id=novelty_id(nd_run_id, "profile", CandidateType.OPEN_SOURCE.value, candidate.candidate_id),
        nd_run_id=nd_run_id, research_run_id=research_run_id,
        candidate_ref=CandidateRef(candidate_type=CandidateType.OPEN_SOURCE, candidate_id=candidate.candidate_id,
                                   source_run_id=run.oss_run_id, identity_key=candidate.repository_key),
        linked_claim_ids=sorted(set(candidate.claim_ids) & known_claims),
        eligibility=eligibility, eligibility_reasons=reasons, independence_unit=unit, chronology=chronology,
        quality=CandidateSourceQualityProfile(
            identity_verified=True, identity_status=candidate.relationship.value,
            available_text_kinds=[t.text_kind for t in texts], exact_text_available=bool(texts),
            full_text_status=_full_text_status(texts), chronology_known=dated,
            historical_visibility_proven=False,
            candidate_group_resolved=bool(network and network.root_metadata_checked),
            source_limitations=_limitations([l.value for l in candidate.limitations], omitted),
        ),
        texts=texts,
    )


def build_profiles(
    nd_run_id: UUID, research_run: ResearchRun, known_claims: set[str], max_texts: int,
    *, patent: bool = True, product: bool = True, oss: bool = True,
) -> list[CandidateComparisonProfile]:
    """Every candidate of every consumed subrun, in a deterministic order."""
    run_id = research_run.research_run_id
    profiles: list[CandidateComparisonProfile] = []
    if patent and research_run.patent_prior_art is not None:
        p = research_run.patent_prior_art
        profiles += [patent_profile(nd_run_id, run_id, p, c, known_claims, max_texts) for c in p.candidates]
    if product and research_run.product_prior_art is not None:
        p = research_run.product_prior_art
        clusters = product_clusters(p)
        profiles += [product_profile(nd_run_id, run_id, p, c, known_claims, max_texts, clusters) for c in p.candidates]
    if oss and research_run.open_source_prior_art is not None:
        o = research_run.open_source_prior_art
        profiles += [oss_profile(nd_run_id, run_id, o, c, known_claims, max_texts) for c in o.candidates]
    return sorted(profiles, key=profile_sort_key)


def profile_sort_key(profile: CandidateComparisonProfile) -> tuple[int, str, str, str]:
    ref = profile.candidate_ref
    order = {CandidateType.PATENT: 0, CandidateType.PRODUCT: 1, CandidateType.OPEN_SOURCE: 2}[ref.candidate_type]
    return (order, profile.independence_unit.unit_key, ref.identity_key, str(ref.candidate_id))


__all__ = [
    "build_profiles",
    "bucket_for",
    "digest",
    "oss_profile",
    "patent_profile",
    "product_clusters",
    "product_profile",
    "profile_sort_key",
    "resolve_text",
]
