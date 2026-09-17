"""Independence grouping and source quality -- Phase 2E (section 8, section 9).

This module answers the release-critical question of Phase 2E: **how many
independent studies actually stand behind this claim?**

The answer is never "how many evidence items are there". Three providers
returning one DOI is one study. Five excerpts from one abstract is one study.
Two Phase 2B source records that resolve to the same canonical identifier are
one study. The grouping key is Phase 2B's ``SourceFingerprint.logical_key``
(``KIND:normalized-identifier``), which is built from strong identifiers only
and can never be a title (ADR-009) -- so title-similarity collapse is not
merely avoided here, it is unexpressible.

Nothing in this module infers a quality fact. A source that states no
retraction status gets ``UNKNOWN``, not ``NOT_RETRACTED``; a source whose
publication form is unstated gets ``UNKNOWN``, not peer review.
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.academic import (
    AcademicSourceType,
    LogicalAcademicSource,
    PEER_REVIEWED_SOURCE_TYPES,
)
from src.schemas.claim_sufficiency import (
    IndependenceGroup,
    PublicationStatus,
    QualityDimension,
    RetractionStatus,
    SourceQualityProfile,
    independence_group_id,
)
from src.schemas.evidence_extraction import ExtractedEvidence
from src.schemas.source import PeerReviewStatus

OTHER_PUBLISHED_SOURCE_TYPES: frozenset[AcademicSourceType] = frozenset(
    {
        AcademicSourceType.BOOK_CHAPTER,
        AcademicSourceType.THESIS,
        AcademicSourceType.DATASET,
        AcademicSourceType.OTHER_ACADEMIC,
    }
)
"""Forms that are published but whose route implies nothing about peer review.

Deliberately not folded into either neighbour: a thesis is not a preprint, and
it is not a peer-reviewed journal article.
"""


def retraction_status(
    source: LogicalAcademicSource | None, evidence: ExtractedEvidence | None = None
) -> RetractionStatus:
    """Resolve retraction from every trusted copy of the fact.

    ``True`` from *either* the merged logical source or the content snapshot the
    evidence came from is enough to mark ``RETRACTED``. The asymmetry is
    deliberate: a missed retraction is the expensive error, and the two records
    can legitimately disagree when one provider learned of the retraction first.
    ``UNKNOWN`` survives only when neither side states anything.
    """
    flags = [
        flag
        for flag in (
            source.is_retracted if source is not None else None,
            evidence.is_retracted if evidence is not None else None,
        )
        if flag is not None
    ]
    if not flags:
        return RetractionStatus.UNKNOWN
    if any(flags):
        return RetractionStatus.RETRACTED
    return RetractionStatus.NOT_RETRACTED


def publication_status(
    source_type: AcademicSourceType, peer_review: PeerReviewStatus
) -> PublicationStatus:
    """Map stated publication metadata onto the Phase 2E vocabulary.

    Reads only the publication *form* and the peer-review status Phase 2B
    derived from it. Venue name, publisher prestige, provider identity and URL
    are never consulted -- they correlate with review without evidencing it
    (section 8).
    """
    if source_type is AcademicSourceType.PREPRINT:
        return PublicationStatus.PREPRINT
    if (
        source_type in PEER_REVIEWED_SOURCE_TYPES
        or peer_review is PeerReviewStatus.PEER_REVIEWED
    ):
        return PublicationStatus.PEER_REVIEWED_OR_FORMALLY_PUBLISHED
    if source_type in OTHER_PUBLISHED_SOURCE_TYPES:
        return PublicationStatus.OTHER_PUBLISHED
    return PublicationStatus.UNKNOWN


def build_quality_profile(
    source: LogicalAcademicSource,
    group_id: UUID,
    evidence_items: list[ExtractedEvidence],
) -> SourceQualityProfile:
    """The observable quality facts about one logical source.

    ``unknown_dimensions`` is populated explicitly rather than left to a reader
    to infer from ``UNKNOWN`` enum values, so a report can enumerate what is not
    known about a source without re-deriving it (section 19).
    """
    retraction = retraction_status(source, evidence_items[0] if evidence_items else None)
    publication = publication_status(source.source_type, source.peer_review_status)

    unknown: list[QualityDimension] = []
    if retraction is RetractionStatus.UNKNOWN:
        unknown.append(QualityDimension.RETRACTION)
    if publication is PublicationStatus.UNKNOWN:
        unknown.append(QualityDimension.PUBLICATION_STATUS)
    if source.publication_year is None:
        unknown.append(QualityDimension.PUBLICATION_YEAR)

    return SourceQualityProfile(
        source_id=source.logical_source_id,
        independence_group_id=group_id,
        canonical_identity=source.fingerprint.logical_key,
        identifier_kind=source.fingerprint.identifier_kind,
        retraction_status=retraction,
        publication_status=publication,
        peer_review_status=source.peer_review_status,
        source_type=source.source_type,
        publication_year=source.publication_year,
        provider_observation_count=len(source.providers),
        unknown_dimensions=unknown,
    )


def build_independence_groups(
    research_run_id: UUID,
    evidence_items: list[ExtractedEvidence],
    logical_sources: list[LogicalAcademicSource],
) -> tuple[list[IndependenceGroup], dict[UUID, UUID]]:
    """Group evidence by canonical logical source.

    Returns the groups and an ``evidence_id -> independence_group_id`` index.
    Evidence whose source does not resolve to a logical source in *this* run is
    deliberately left out of the index: it is untraceable, and the caller turns
    that into ``DISQUALIFIED_UNTRACEABLE`` rather than inventing a group for it.
    That also enforces cross-run isolation for free -- a source from another run
    is not in ``logical_sources`` and therefore never groups (section 23).

    Two distinct ``source_id``s that share a canonical identity collapse into
    one group. This is the DOI/strong-identifier duplicate collapse, and it
    happens here rather than being trusted to Phase 2B's merge, so a pair of
    records that escaped that merge still cannot inflate corroboration.
    """
    by_source = {s.logical_source_id: s for s in logical_sources if s.research_run_id == research_run_id}

    identity_members: dict[str, list[ExtractedEvidence]] = {}
    identity_sources: dict[str, list[str]] = {}
    index: dict[UUID, UUID] = {}

    for evidence in evidence_items:
        if evidence.research_run_id != research_run_id:
            continue
        source = by_source.get(evidence.source_id)
        if source is None:
            continue
        identity = source.fingerprint.logical_key
        identity_members.setdefault(identity, []).append(evidence)
        sources = identity_sources.setdefault(identity, [])
        if evidence.source_id not in sources:
            sources.append(evidence.source_id)
        index[evidence.evidence_id] = independence_group_id(research_run_id, identity)

    groups: list[IndependenceGroup] = []
    for identity in sorted(identity_members):
        members = identity_members[identity]
        group_id = independence_group_id(research_run_id, identity)
        # The quality profile is taken from the first source record in the
        # group; every record in a group is the same work by canonical
        # identity, and retraction folds in the strictest signal above.
        representative = by_source[identity_sources[identity][0]]
        groups.append(
            IndependenceGroup(
                independence_group_id=group_id,
                research_run_id=research_run_id,
                canonical_identity=identity,
                identifier_kind=representative.fingerprint.identifier_kind,
                source_ids=list(identity_sources[identity]),
                member_evidence_ids=[e.evidence_id for e in members],
                quality=build_quality_profile(representative, group_id, members),
            )
        )
    return groups, index


__all__ = [
    "OTHER_PUBLISHED_SOURCE_TYPES",
    "build_independence_groups",
    "build_quality_profile",
    "publication_status",
    "retraction_status",
]
