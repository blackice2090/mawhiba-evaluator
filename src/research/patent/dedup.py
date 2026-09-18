"""Observation-to-publication identity resolution -- Phase 2G sections 15, 16.

The decision this module implements:

> Deduplication produces **one verified publication per canonical publication
> identity** while preserving **every provider observation**.

Three rules make that safe.

**Identity is the canonical publication key and nothing else.** Two observations
merge when their ``authority.number.kind`` agree. They never merge on a title:
``PublicationIdentity`` has no title field, so title-based publication identity
is unrepresentable rather than merely discouraged (section 15).

**A different kind code is a different publication.** ``EP1000000.A1`` and
``EP1000000.B1`` stay separate records under one family, because they are the
application publication and the grant. Collapsing them would make a document
look like independent corroboration of itself (section 16). An observation that
states *no* kind code is also kept separate from one that states ``A1``: absent
is not a wildcard.

**Duplicates never inflate a count.** The same publication returned by three
providers, by two queries, or twice in one response yields one publication with
three observations. The observation list is what makes "who returned this, and
under which query?" answerable, and a first-observation-wins merge would have
destroyed it.

Metadata merging is conservative in the same way Phase 2B's is: a missing field
is filled from another observation, and a disagreeing field keeps the first
observation's value in dispatch order while the disagreement stays visible in
the observations themselves. Dates are the one place where the rule is stricter
-- a conflicting date is left *unknown* rather than chosen, because a guessed
publication date could move a document across a cutoff (section 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.research.patent.chronology import build_date_set
from src.schemas.common import new_source_id
from src.schemas.patent import (
    PATENT_PROVIDER_ORDER,
    PatentDateSet,
    PatentFamilyStatus,
    PatentSearchObservation,
    VerifiedPatentPublication,
)
from src.schemas.source import VerificationStatus

PATENT_MERGE_VERSION = "PATENT-MERGE-V1"


@dataclass
class ObservationGroup:
    """Observations that provably describe one publication."""

    publication_key: str
    observations: list[PatentSearchObservation] = field(default_factory=list)

    @property
    def ordered(self) -> list[PatentSearchObservation]:
        """Observations in deterministic provider order, then retrieval order.

        Deterministic so two runs over the same data produce byte-identical
        publications, which is what makes the idempotency check meaningful.
        """
        return sorted(
            self.observations,
            key=lambda o: (
                PATENT_PROVIDER_ORDER.index(o.provider),
                o.retrieved_at,
                str(o.observation_id),
            ),
        )

    @property
    def providers(self) -> list[str]:
        return [o.provider.value for o in self.ordered]


def group_observations(
    observations: list[PatentSearchObservation],
) -> list[ObservationGroup]:
    """Group observations by canonical publication identity.

    Grouping is exact-key only. There is no similarity step, no fuzzy match and
    no title comparison anywhere in this function.
    """
    groups: dict[str, ObservationGroup] = {}
    for observation in observations:
        key = observation.publication_key
        groups.setdefault(key, ObservationGroup(publication_key=key)).observations.append(
            observation
        )
    return [groups[key] for key in sorted(groups)]


def _first(values: list[str | None]) -> str | None:
    """The first stated value, or ``None``. Used for fill-in, never for conflict."""
    return next((v for v in values if v), None)


def _agreed(values: list[str | None]) -> str | None:
    """The value every observation that states one agrees on, else ``None``.

    Disagreement yields ``None`` -- unknown -- rather than a choice. Applied to
    dates specifically: leaving a contested publication date unknown makes the
    candidate ``PUBLICATION_DATE_UNKNOWN``, which is honest, whereas picking one
    would place the document on a date line nobody verified.
    """
    stated = {v for v in values if v}
    return stated.pop() if len(stated) == 1 else None


def merge_dates(observations: list[PatentSearchObservation]) -> PatentDateSet:
    """One date set from several observations, conflicts left unknown.

    A merged set that turns out impossible -- which cross-provider disagreement
    can produce -- falls back to the first observation's own dates, because a
    single provider's internally consistent chronology is preferable to a
    synthesized impossible one.
    """
    merged = build_date_set(
        priority=_agreed([o.dates.earliest_priority_date for o in observations]),
        filing=_agreed([o.dates.filing_date for o in observations]),
        publication=_agreed([o.dates.publication_date for o in observations]),
        grant=_agreed([o.dates.grant_date for o in observations]),
    )
    return merged if merged is not None else observations[0].dates


def _merged_classifications(
    observations: list[PatentSearchObservation], attribute: str
) -> list[str]:
    """Union of classification symbols, in first-seen order.

    A union rather than an intersection: a classification one office recorded
    and another omitted is still a real classification of the document, and
    classifications are metadata that cannot by themselves establish identity
    (section 25).
    """
    merged: list[str] = []
    for observation in observations:
        for symbol in getattr(observation, attribute):
            if symbol not in merged:
                merged.append(symbol)
    return merged


def _merged_parties(
    observations: list[PatentSearchObservation], attribute: str
) -> list[str]:
    merged: list[str] = []
    for observation in observations:
        for name in getattr(observation, attribute):
            if name not in merged:
                merged.append(name)
    return merged


def build_publication(
    group: ObservationGroup, research_run_id: UUID
) -> VerifiedPatentPublication:
    """One verified publication from one observation group.

    Every observation is carried onto the record. The family fields are left
    unresolved here: family resolution is a separate, provider-backed step, and
    inferring a family from the observations' ``family_id`` alone would be a
    grouping this module did not verify (section 17).
    """
    observations = group.ordered
    primary = observations[0]
    titles = [o.title for o in observations if o.title]
    languages = [o.title_language for o in observations if o.title_language]

    return VerifiedPatentPublication(
        publication_id=new_source_id(),
        research_run_id=research_run_id,
        identity=primary.identity,
        fingerprint=primary.identity.fingerprint(),
        title=_first(titles) or "",
        title_language=_first(languages),
        dates=merge_dates(observations),
        applicants=_merged_parties(observations, "applicants"),
        inventors=_merged_parties(observations, "inventors"),
        ipc_classifications=_merged_classifications(observations, "ipc_classifications"),
        cpc_classifications=_merged_classifications(observations, "cpc_classifications"),
        family_status=PatentFamilyStatus.NOT_REQUESTED,
        observations=observations,
        verification_status=VerificationStatus.VERIFIED_METADATA,
        first_retrieved_at=min(o.retrieved_at for o in observations),
    )


@dataclass
class DedupOutcome:
    """The verified publications, and what deduplication actually collapsed."""

    publications: list[VerifiedPatentPublication] = field(default_factory=list)
    observation_count: int = 0
    duplicate_observations_merged: int = 0
    truncated: int = 0

    @property
    def publication_count(self) -> int:
        return len(self.publications)

    @property
    def multi_provider_count(self) -> int:
        return sum(1 for p in self.publications if len(p.providers) > 1)


def resolve_publications(
    observations: list[PatentSearchObservation],
    research_run_id: UUID,
    *,
    max_publications: int | None = None,
) -> DedupOutcome:
    """Resolve verified observations into verified publications.

    ``max_publications`` truncates whole publications and records the count;
    every observation of a kept publication is kept, so a limit never leaves a
    publication with a partial provenance record.
    """
    groups = group_observations(observations)
    outcome = DedupOutcome(observation_count=len(observations))

    kept = groups
    if max_publications is not None and len(groups) > max_publications:
        kept = groups[:max_publications]
        outcome.truncated = len(groups) - max_publications

    outcome.publications = [build_publication(group, research_run_id) for group in kept]
    outcome.duplicate_observations_merged = sum(
        len(group.observations) - 1 for group in kept
    )
    return outcome


__all__ = [
    "PATENT_MERGE_VERSION",
    "DedupOutcome",
    "ObservationGroup",
    "build_publication",
    "group_observations",
    "merge_dates",
    "resolve_publications",
]
