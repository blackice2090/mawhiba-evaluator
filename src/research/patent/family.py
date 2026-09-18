"""Patent family resolution -- Phase 2G sections 17, 18.

Family handling is release-critical, and it has two opposite failure modes that
this module must avoid at the same time.

**Inflation.** One invention filed in five jurisdictions is five publications.
Counted as five independent prior-art candidates it would look like five
separate teams reaching the same result, which is a materially different picture
from one applicant filing abroad. So family members are grouped, and
``PatentPriorArtRun.independent_family_count`` counts families rather than
documents.

**Loss.** The five members are *not* discarded. They carry different kind codes,
different jurisdictions, different publication dates and different claim text,
and a later comparison phase needs all of it. So grouping is a layer *over* the
publication records, never a replacement for them.

Family identity comes from the provider's family service. It is never derived
from a title, and never from a shared classification -- a CPC symbol two
documents share is metadata, not identity (section 25). Where the provider
cannot tell us, the family stays ``FAMILY_DATA_UNAVAILABLE`` or
``FAMILY_RESOLUTION_FAILED``, and a contract validator forbids a family
identifier on either: unknown family membership remains unknown (section 18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from src.research.patent.provider import FamilyPayload, PatentSearchProvider
from src.schemas.patent import (
    PatentFamilyGroup,
    PatentFamilyKind,
    PatentFamilyMemberRef,
    PatentFamilyStatus,
    PatentProvider,
    PatentProviderOperation,
    VerifiedPatentPublication,
    patent_safe_summary,
)

PATENT_FAMILY_RESOLUTION_VERSION = "PATENT-FAMILY-RESOLUTION-V1"

FAMILY_DATA_UNAVAILABLE_NOTE = (
    "the provider exposes no family data for this authority; membership unknown"
)
FAMILY_RESOLUTION_FAILED_NOTE = "the family lookup failed; membership unknown"
FAMILY_NOT_REQUESTED_NOTE = "family lookup not performed within this run's budget"


@dataclass
class FamilyResolution:
    """The families resolved for a run, and the per-publication assignment."""

    families: list[PatentFamilyGroup] = field(default_factory=list)
    assignment: dict[str, UUID] = field(default_factory=dict)
    """publication key -> family group id. Absent means unresolved."""

    status: dict[str, PatentFamilyStatus] = field(default_factory=dict)
    """publication key -> family status. Always populated for every publication."""

    lookups_performed: int = 0
    lookups_truncated: int = 0

    @property
    def independent_family_count(self) -> int:
        """Candidate inventions: one per resolved family, one per unresolved doc.

        An unresolved publication counts as one on its own. That is deliberately
        conservative in the *un*-inflating direction only: it never merges two
        documents on a guess, and it never turns one family into many.
        """
        grouped = len({group_id for group_id in self.assignment.values()})
        ungrouped = sum(1 for key in self.status if key not in self.assignment)
        return grouped + ungrouped


def _member_refs(
    payload: FamilyPayload, known_keys: set[str]
) -> list[PatentFamilyMemberRef]:
    """Family members as references, flagging which this run actually holds.

    A member the run never fetched is still recorded. The family is then
    honestly larger than the documents in hand, which is information a later
    phase needs and which discarding would hide (section 17).
    """
    refs: list[PatentFamilyMemberRef] = []
    seen: set[str] = set()
    for identity, member_date in payload.members:
        key = identity.canonical_key
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            PatentFamilyMemberRef(
                publication_key=key,
                identity=identity,
                retrieved_in_run=key in known_keys,
                member_publication_date=member_date,
            )
        )
    return refs


def _unresolved_group(
    research_run_id: UUID,
    status: PatentFamilyStatus,
    *,
    provider: PatentProvider | None,
    endpoint: str | None,
    note: str,
    retrieved_at: datetime | None,
) -> PatentFamilyGroup:
    """A family group that records a failure honestly.

    It carries no ``family_id`` and no members, which the contract validator
    requires: a group that could not be established must not look like one that
    was (section 18).
    """
    return PatentFamilyGroup(
        research_run_id=research_run_id,
        status=status,
        provider=provider,
        provider_operation=PatentProviderOperation.FETCH_FAMILY,
        provider_endpoint=endpoint,
        note=patent_safe_summary(note),
        retrieved_at=retrieved_at,
    )


def resolve_families(
    publications: list[VerifiedPatentPublication],
    provider: PatentSearchProvider | None,
    research_run_id: UUID,
    *,
    max_lookups: int = 0,
    retrieved_at: datetime | None = None,
) -> FamilyResolution:
    """Resolve families for a run's publications.

    One lookup per *family*, not per publication: once a family is known, every
    member already in hand is assigned from the same response. That is both the
    correct semantics and a real reduction in requests against a fair-use
    limited service (section 27).

    With no provider, or no family budget, every publication gets an explicit
    ``NOT_REQUESTED`` status rather than an absent one.
    """
    resolution = FamilyResolution()
    known_keys = {p.publication_key for p in publications}
    by_family_id: dict[str, UUID] = {}

    if provider is None or max_lookups <= 0:
        for publication in publications:
            resolution.status[publication.publication_key] = (
                PatentFamilyStatus.NOT_REQUESTED
            )
        if publications:
            resolution.lookups_truncated = len(publications) if max_lookups <= 0 else 0
        return resolution

    for publication in publications:
        key = publication.publication_key
        if key in resolution.assignment:
            continue

        if resolution.lookups_performed >= max_lookups:
            resolution.status[key] = PatentFamilyStatus.NOT_REQUESTED
            resolution.lookups_truncated += 1
            continue

        payload = provider.fetch_family(publication.identity)
        resolution.lookups_performed += 1

        if not payload.available:
            resolution.status[key] = PatentFamilyStatus.FAMILY_DATA_UNAVAILABLE
            resolution.families.append(
                _unresolved_group(
                    research_run_id,
                    PatentFamilyStatus.FAMILY_DATA_UNAVAILABLE,
                    provider=getattr(provider, "provider_name", None),
                    endpoint=payload.endpoint or None,
                    note=FAMILY_DATA_UNAVAILABLE_NOTE,
                    retrieved_at=retrieved_at,
                )
            )
            continue

        if payload.failed or not payload.members or not payload.family_id:
            # A failure, an empty family response and a response with no family
            # identifier are all "we do not know". None of them may become a
            # singleton: a singleton is a positive statement that this document
            # stands alone (section 18).
            resolution.status[key] = PatentFamilyStatus.FAMILY_RESOLUTION_FAILED
            resolution.families.append(
                _unresolved_group(
                    research_run_id,
                    PatentFamilyStatus.FAMILY_RESOLUTION_FAILED,
                    provider=getattr(provider, "provider_name", None),
                    endpoint=payload.endpoint or None,
                    note=FAMILY_RESOLUTION_FAILED_NOTE,
                    retrieved_at=retrieved_at,
                )
            )
            continue

        existing = by_family_id.get(payload.family_id)
        if existing is not None:
            resolution.assignment[key] = existing
            group = next(
                g for g in resolution.families if g.family_group_id == existing
            )
            resolution.status[key] = group.status
            continue

        members = _member_refs(payload, known_keys)
        if key not in {member.publication_key for member in members}:
            # The provider answered with a family that does not list the very
            # publication it was asked about. Accepting it would attach this
            # document to a family nobody showed it belongs to -- fabricated
            # membership (section 18) -- so the answer is "we do not know".
            resolution.status[key] = PatentFamilyStatus.FAMILY_RESOLUTION_FAILED
            resolution.families.append(
                _unresolved_group(
                    research_run_id,
                    PatentFamilyStatus.FAMILY_RESOLUTION_FAILED,
                    provider=getattr(provider, "provider_name", None),
                    endpoint=payload.endpoint or None,
                    note="family response does not list the requested publication",
                    retrieved_at=retrieved_at,
                )
            )
            continue
        status = (
            PatentFamilyStatus.SINGLETON_FAMILY
            if len(members) == 1
            else PatentFamilyStatus.VERIFIED_FAMILY
        )
        group = PatentFamilyGroup(
            research_run_id=research_run_id,
            family_id=payload.family_id,
            family_kind=payload.family_kind or PatentFamilyKind.UNKNOWN,
            status=status,
            provider=getattr(provider, "provider_name", None),
            provider_operation=PatentProviderOperation.FETCH_FAMILY,
            provider_endpoint=payload.endpoint or None,
            members=members,
            earliest_priority_date=payload.earliest_priority_date,
            retrieved_at=retrieved_at,
        )
        resolution.families.append(group)
        by_family_id[payload.family_id] = group.family_group_id

        # Assign every member this run already holds, so a second lookup for a
        # sibling publication is never issued.
        for member in members:
            if member.publication_key in known_keys:
                resolution.assignment[member.publication_key] = group.family_group_id
                resolution.status[member.publication_key] = status

    for publication in publications:
        resolution.status.setdefault(
            publication.publication_key, PatentFamilyStatus.NOT_REQUESTED
        )
    return resolution


def apply_families(
    publications: list[VerifiedPatentPublication], resolution: FamilyResolution
) -> list[VerifiedPatentPublication]:
    """Attach the resolved family to each publication. Nothing is mutated."""
    return [
        publication.model_copy(
            update={
                "family_group_id": resolution.assignment.get(publication.publication_key),
                "family_status": resolution.status.get(
                    publication.publication_key, PatentFamilyStatus.NOT_REQUESTED
                ),
            }
        )
        for publication in publications
    ]


def family_of(
    publication: VerifiedPatentPublication, families: list[PatentFamilyGroup]
) -> PatentFamilyGroup | None:
    if publication.family_group_id is None:
        return None
    return next(
        (f for f in families if f.family_group_id == publication.family_group_id), None
    )


__all__ = [
    "FAMILY_DATA_UNAVAILABLE_NOTE",
    "FAMILY_NOT_REQUESTED_NOTE",
    "FAMILY_RESOLUTION_FAILED_NOTE",
    "PATENT_FAMILY_RESOLUTION_VERSION",
    "FamilyResolution",
    "apply_families",
    "family_of",
    "resolve_families",
]
