"""Cross-provider identity resolution and conservative metadata merging.

The decision this module implements is ADR-009:

> Deduplication produces **one logical source** while preserving **every provider
> observation**.

Two rules make that safe.

**Identity comes from strong identifiers only.** Candidates join a group when
they share a DOI, a PMID, an OpenAlex id, a Semantic Scholar id, an arXiv id or
a canonical URL. They never join on a title. Two papers with the same title are
routinely different papers, and one paper routinely appears under two slightly
different titles, so a title cannot decide identity in either direction. With no
shared identifier, both candidates survive as separate logical sources -- an
avoidable duplicate is a cosmetic problem, while a wrong merge silently fuses
two works and every later judgement about them.

**A conflicting identifier blocks the merge.** If two candidates agree on an
arXiv id but state different DOIs, they are not merged. The DOI disagreement is
evidence that at least one record is wrong, and guessing which would be exactly
the invalid merge the safety gate forbids.

Merging is then conservative. Missing metadata is filled from another provider;
disagreeing metadata leaves the merged field unknown and records a
``MetadataConflict`` holding every provider's reading. Retraction is the one
documented exception: a single provider reporting ``is_retracted=True`` makes the
merged value ``True``, because a retracted paper that looks clean is a far worse
failure than a clean paper flagged for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.schemas.academic import (
    ACADEMIC_PROVIDER_ORDER,
    AcademicCandidateDecision,
    AcademicIdentifiers,
    AcademicSourceCandidate,
    AcademicSourceType,
    CitationObservation,
    ConflictValue,
    LogicalAcademicSource,
    MetadataConflict,
    ProviderObservation,
)
from src.schemas.common import new_source_id
from src.schemas.source import SourceFingerprint, SourceIdentifierKind

ACADEMIC_MERGE_VERSION = "ACADEMIC-MERGE-V1"

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _comparable(text: str | None) -> str:
    """Case- and punctuation-insensitive form, used only to detect disagreement.

    Never used for identity: two records whose comparable titles match are still
    only merged when they share an identifier.
    """
    if not text:
        return ""
    return _NON_WORD.sub(" ", text).casefold().strip()


@dataclass
class CandidateGroup:
    """Candidates that provably describe one work."""

    members: list[AcademicSourceCandidate] = field(default_factory=list)
    identities: dict[SourceIdentifierKind, str] = field(default_factory=dict)

    def conflicts_with(self, identities: dict[SourceIdentifierKind, str]) -> bool:
        return any(
            kind in self.identities and self.identities[kind] != value
            for kind, value in identities.items()
        )

    def matches(self, identities: dict[SourceIdentifierKind, str]) -> bool:
        return any(self.identities.get(kind) == value for kind, value in identities.items())

    def absorb(
        self,
        candidate: AcademicSourceCandidate,
        identities: dict[SourceIdentifierKind, str],
    ) -> None:
        self.members.append(candidate)
        for kind, value in identities.items():
            self.identities.setdefault(kind, value)

    @property
    def ordered_members(self) -> list[AcademicSourceCandidate]:
        """Members in dispatch order, insertion order breaking ties.

        A stable order is what makes the merged record reproducible: the same
        candidates always yield the same primary observation.
        """
        return sorted(
            self.members,
            key=lambda c: (ACADEMIC_PROVIDER_ORDER.index(c.provider), self.members.index(c)),
        )


def group_candidates(
    candidates: list[AcademicSourceCandidate],
) -> list[CandidateGroup]:
    """Partition candidates into logical sources. Deterministic and order-stable."""
    groups: list[CandidateGroup] = []
    for candidate in candidates:
        identities = candidate.identity_map()
        compatible = [
            group
            for group in groups
            if group.matches(identities) and not group.conflicts_with(identities)
        ]
        if not compatible:
            group = CandidateGroup()
            group.absorb(candidate, identities)
            groups.append(group)
            continue

        target = compatible[0]
        target.absorb(candidate, identities)
        # This candidate may bridge two groups (for example a record carrying
        # both the DOI of one and the arXiv id of the other). They join only if
        # nothing they both state disagrees.
        for other in compatible[1:]:
            if target.conflicts_with(other.identities):
                continue
            for member in other.members:
                target.absorb(member, member.identity_map())
            groups.remove(other)
    return groups


def _first(values: list[tuple[AcademicSourceCandidate, object]]) -> object:
    return values[0][1] if values else None


def _agree(
    members: list[AcademicSourceCandidate],
    field_name: str,
    getter,
    *,
    missing: object = None,
) -> tuple[object, MetadataConflict | None]:
    """Merge one field conservatively.

    Every member that states a value is consulted. All agreeing, or only one
    speaking, gives that value. Any disagreement leaves the field unknown and
    returns the conflict, so the disagreement is visible instead of resolved by
    whichever provider happened to be first.
    """
    stated = [(m, getter(m)) for m in members if getter(m) is not missing and getter(m) is not None]
    if not stated:
        return None, None
    distinct = {str(value) for _, value in stated}
    if len(distinct) == 1:
        return stated[0][1], None
    if len({m.provider for m, _ in stated}) < 2:
        # One provider contradicting itself across two records: keep the first
        # reading rather than inventing a cross-provider conflict.
        return _first(stated), None
    return None, MetadataConflict(
        field_name=field_name,
        values=[
            ConflictValue(provider=member.provider, value=str(value))
            for member, value in stated
        ],
    )


def _merge_retraction(
    members: list[AcademicSourceCandidate],
) -> tuple[bool | None, MetadataConflict | None]:
    """Sticky-true. A retraction reported by any provider survives the merge."""
    stated = [(m, m.is_retracted) for m in members if m.is_retracted is not None]
    if not stated:
        return None, None
    values = {value for _, value in stated}
    if len(values) == 1:
        return stated[0][1], None
    return True, MetadataConflict(
        field_name="is_retracted",
        values=[
            ConflictValue(provider=member.provider, value=str(value))
            for member, value in stated
        ],
        resolved_value="True",
    )


def _merge_titles(
    members: list[AcademicSourceCandidate],
) -> tuple[str, MetadataConflict | None]:
    """Keep the primary provider's title; report a materially different one.

    Unlike a year, a title is required, so it is never blanked. Differences in
    case, punctuation or spacing are not material and produce no conflict.
    """
    primary = members[0].title
    comparable = {_comparable(m.title) for m in members}
    if len(comparable) == 1 or len({m.provider for m in members}) < 2:
        return primary, None
    return primary, MetadataConflict(
        field_name="title",
        values=[ConflictValue(provider=m.provider, value=m.title) for m in members],
        resolved_value=primary,
    )


def _merge_authors(
    members: list[AcademicSourceCandidate],
) -> tuple[list[str], MetadataConflict | None]:
    """Keep the primary provider's author list; report a materially different one."""
    stated = [m for m in members if m.authors]
    if not stated:
        return [], None
    primary = list(stated[0].authors)
    comparable = {
        tuple(sorted(_comparable(name) for name in m.authors)) for m in stated
    }
    if len(comparable) == 1 or len({m.provider for m in stated}) < 2:
        return primary, None
    return primary, MetadataConflict(
        field_name="authors",
        values=[
            ConflictValue(provider=m.provider, value="; ".join(m.authors)) for m in stated
        ],
        resolved_value="; ".join(primary),
    )


def _merge_source_type(
    members: list[AcademicSourceCandidate],
) -> tuple[AcademicSourceType, MetadataConflict | None]:
    """UNKNOWN counts as "not stated", so it never overrides a real type."""
    value, conflict = _agree(
        members,
        "source_type",
        lambda m: m.source_type,
        missing=AcademicSourceType.UNKNOWN,
    )
    if conflict is not None:
        return AcademicSourceType.UNKNOWN, conflict
    return value if value is not None else AcademicSourceType.UNKNOWN, None


def merge_group(
    group: CandidateGroup, research_run_id, *, display_index: int
) -> LogicalAcademicSource:
    """Assemble one logical source from one group of candidates."""
    members = group.ordered_members
    primary = members[0]

    identifiers = AcademicIdentifiers()
    for member in members:
        identifiers = identifiers.merged_with(member.identifiers)

    conflicts: list[MetadataConflict] = []

    def take(field_name: str, getter, missing: object = None):
        value, conflict = _agree(members, field_name, getter, missing=missing)
        if conflict is not None:
            conflicts.append(conflict)
        return value

    title, title_conflict = _merge_titles(members)
    if title_conflict is not None:
        conflicts.append(title_conflict)
    authors, author_conflict = _merge_authors(members)
    if author_conflict is not None:
        conflicts.append(author_conflict)
    source_type, type_conflict = _merge_source_type(members)
    if type_conflict is not None:
        conflicts.append(type_conflict)
    retracted, retraction_conflict = _merge_retraction(members)
    if retraction_conflict is not None:
        conflicts.append(retraction_conflict)

    year = take("publication_year", lambda m: m.publication_year)
    publication_date = take("publication_date", lambda m: m.publication_date)
    venue = take("venue", lambda m: m.venue)
    publisher = take("publisher", lambda m: m.publisher)
    open_access = take("is_open_access", lambda m: m.is_open_access)

    canonical_url = next((m.canonical_url for m in members if m.canonical_url), None)
    strongest = identifiers.strongest() or (
        (SourceIdentifierKind.CANONICAL_URL, canonical_url) if canonical_url else None
    )
    if strongest is None:  # pragma: no cover -- verification rejects these first
        raise ValueError("a candidate group without any identifier cannot be merged")

    # An abstract is coverage, not a fact: providers legitimately hold different
    # lengths of the same text, so the first available one is kept and no
    # conflict is raised.
    abstract = next((m.abstract for m in members if m.abstract), None)

    return LogicalAcademicSource(
        logical_source_id=new_source_id(),
        display_id=f"SRC-{display_index:03d}",
        research_run_id=research_run_id,
        fingerprint=SourceFingerprint.create(*strongest),
        identifiers=identifiers,
        title=title,
        abstract=abstract,
        authors=authors,
        publication_year=year,
        publication_date=publication_date,
        venue=venue,
        publisher=publisher,
        source_type=source_type,
        is_open_access=open_access,
        is_retracted=retracted,
        canonical_url=canonical_url,
        observations=[
            ProviderObservation(
                provider=member.provider,
                candidate_id=member.candidate_id,
                query_id=member.query_id,
                research_run_id=member.research_run_id,
                provider_record_id=member.provider_record_id,
                provider_url=member.provider_url,
                canonical_url=member.canonical_url,
                identifiers=member.identifiers,
                title=member.title,
                publication_year=member.publication_year,
                source_type=member.source_type,
                is_retracted=member.is_retracted,
                is_open_access=member.is_open_access,
                citation_count=member.citation_count,
                provider_rank=member.provider_rank,
                provider_relevance=member.provider_relevance,
                retrieved_at=member.retrieved_at,
            )
            for member in members
        ],
        citation_observations=[
            CitationObservation(
                provider=member.provider,
                count=member.citation_count,
                retrieved_at=member.retrieved_at,
            )
            for member in members
            if member.citation_count is not None
        ],
        conflicts=conflicts,
        first_retrieved_at=min(member.retrieved_at for member in members),
    )


def resolve_logical_sources(
    candidates: list[AcademicSourceCandidate], research_run_id
) -> tuple[list[LogicalAcademicSource], list[AcademicCandidateDecision]]:
    """Group, merge, and record which logical source each candidate landed in."""
    groups = group_candidates(candidates)
    sources: list[LogicalAcademicSource] = []
    decisions: list[AcademicCandidateDecision] = []
    for index, group in enumerate(groups, start=1):
        source = merge_group(group, research_run_id, display_index=index)
        sources.append(source)
        decisions.extend(
            AcademicCandidateDecision(
                candidate_id=member.candidate_id,
                provider=member.provider,
                query_id=member.query_id,
                accepted=True,
                logical_source_id=source.logical_source_id,
            )
            for member in group.ordered_members
        )
    return sources, decisions


__all__ = [
    "ACADEMIC_MERGE_VERSION",
    "CandidateGroup",
    "group_candidates",
    "merge_group",
    "resolve_logical_sources",
]
