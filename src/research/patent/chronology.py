"""Patent date semantics and cutoff qualification -- Phase 2G sections 7-9.

Two rules carry this module, and both exist because the errors they prevent are
invisible once made:

1. **Only a publication date, or a grant date with no earlier publication, is a
   public-availability date.** A priority date and a filing date are chronology
   about the application, not about the public. Substituting one would make a
   document look available years before anyone could read it.

2. **A cutoff is qualified against only when a cutoff was supplied.** With no
   cutoff the answer is ``NO_CUTOFF`` -- never today's date, never the
   submission date, never the document's own priority date (section 7).

Nothing here is a legal determination. ``PUBLIC_BEFORE_CUTOFF`` means the
publication date precedes a date the calling workflow named, and that is all it
means (ADR-018).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.patent.identity import normalize_patent_date
from src.schemas.patent import (
    PatentDateSet,
    PatentSearchCutoff,
    PatentTimeQualification,
)


@dataclass(frozen=True)
class ChronologyResult:
    """A publication's place on the date line, and what decided it."""

    qualification: PatentTimeQualification
    first_public_date: str | None
    cutoff_date: str | None
    public_date_field: str | None = None
    """Which date field supplied ``first_public_date``: ``publication_date`` or
    ``grant_date``. Recorded so a reader never has to guess which one was used,
    and so a test can prove a grant date was not preferred over an earlier
    publication (section 8)."""


def build_date_set(
    *,
    priority: str | None = None,
    filing: str | None = None,
    publication: str | None = None,
    grant: str | None = None,
) -> PatentDateSet | None:
    """Normalize four provider dates into a date set, or ``None`` if impossible.

    ``None`` means the combination cannot occur -- a priority date after filing,
    a publication before filing, a grant before publication. The caller records
    ``INCONSISTENT_DATE_ORDER`` rather than storing an impossible chronology.

    An unparseable individual date simply stays unknown: one malformed field
    must not discard three good ones.
    """
    try:
        return PatentDateSet(
            earliest_priority_date=normalize_patent_date(priority),
            filing_date=normalize_patent_date(filing),
            publication_date=normalize_patent_date(publication),
            grant_date=normalize_patent_date(grant),
        )
    except ValueError:
        return None


def first_public_date(dates: PatentDateSet) -> tuple[str | None, str | None]:
    """The earliest date the record shows the document was public, and its field.

    The publication date wins whenever there is one, so a grant date can never
    be presented as the first public date of a document that was published
    earlier as an application (section 8).
    """
    if dates.publication_date:
        return (dates.publication_date, "publication_date")
    if dates.grant_date:
        return (dates.grant_date, "grant_date")
    return (None, None)


def qualify_against_cutoff(
    dates: PatentDateSet, cutoff: PatentSearchCutoff
) -> ChronologyResult:
    """Place a publication on the date line relative to an optional cutoff.

    The order of the checks is the safety property. The absence of a cutoff is
    decided **first**, so no code path can reach a before/after label without a
    supplied cutoff; an unknown publication date is decided **second**, so an
    unknown date can never fall through into ``PUBLIC_BEFORE_CUTOFF``.
    """
    public_date, field = first_public_date(dates)

    if not cutoff.supplied:
        return ChronologyResult(
            qualification=PatentTimeQualification.NO_CUTOFF,
            first_public_date=public_date,
            cutoff_date=None,
            public_date_field=field,
        )

    if public_date is None:
        return ChronologyResult(
            qualification=PatentTimeQualification.PUBLICATION_DATE_UNKNOWN,
            first_public_date=None,
            cutoff_date=cutoff.cutoff_date,
            public_date_field=None,
        )

    cutoff_date = cutoff.cutoff_date
    assert cutoff_date is not None  # guaranteed by PatentSearchCutoff
    if public_date < cutoff_date:
        qualification = PatentTimeQualification.PUBLIC_BEFORE_CUTOFF
    elif public_date == cutoff_date:
        qualification = PatentTimeQualification.PUBLIC_ON_CUTOFF
    else:
        qualification = PatentTimeQualification.PUBLIC_AFTER_CUTOFF

    return ChronologyResult(
        qualification=qualification,
        first_public_date=public_date,
        cutoff_date=cutoff_date,
        public_date_field=field,
    )


def earliest_priority(dates: list[PatentDateSet]) -> str | None:
    """The earliest priority date across a family's members, where stated.

    Family chronology only. This value is never returned by
    ``first_public_date`` and never reaches ``qualify_against_cutoff``: the
    types make the mistake awkward, and this docstring makes it explicit.
    """
    stated = [d.earliest_priority_date for d in dates if d.earliest_priority_date]
    return min(stated) if stated else None


__all__ = [
    "ChronologyResult",
    "build_date_set",
    "earliest_priority",
    "first_public_date",
    "qualify_against_cutoff",
]
