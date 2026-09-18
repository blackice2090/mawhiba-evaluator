"""Canonical patent publication identity -- Phase 2G sections 15 and 16.

Identity is derived only from a publishing authority, a document number and a
kind code. A title never participates, which is why
``PublicationIdentity`` has no title field to participate with.

Normalization follows the DOCDB/EPODOC conventions the EPO OPS contract uses:

* the authority is a two-letter upper-case code;
* the document number is upper case with grouping separators removed;
* the kind code, where the provider states one, is upper case.

What normalization deliberately does **not** do:

* it never strips a kind code to make two records match (section 16);
* it never pads or truncates a document number to a fixed width, because a
  padded ``US0009999999`` and a real ``US9999999`` are then indistinguishable;
* it never removes a leading zero that the authority itself prints, because
  ``EP0123456`` and ``EP123456`` are different documents for some authorities.

The only thing collapsed is punctuation a provider inserted for human reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.schemas.patent import (
    AUTHORITY_PATTERN,
    CLASSIFICATION_PATTERN,
    FAMILY_ID_PATTERN,
    KIND_CODE_PATTERN,
    PATENT_DATE_PATTERN,
    PUBLICATION_NUMBER_PATTERN,
    PatentRejectionReason,
    PublicationIdentity,
)

_SEPARATORS = re.compile(r"[\s,./\\_\-()\[\]]+")
"""Grouping characters a provider or a human may insert into a number.

``PCT/US2011/012345`` and ``US 9,999,999`` are the same document numbers as
``PCTUS2011012345`` and ``US9999999``; the separators carry no identity.
"""

_AUTHORITY = re.compile(AUTHORITY_PATTERN)
_NUMBER = re.compile(PUBLICATION_NUMBER_PATTERN)
_KIND = re.compile(KIND_CODE_PATTERN)
_FAMILY = re.compile(FAMILY_ID_PATTERN)
_CLASSIFICATION = re.compile(CLASSIFICATION_PATTERN)
_DATE = re.compile(PATENT_DATE_PATTERN)
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

_EPODOC_REFERENCE = re.compile(r"^([A-Z]{2})([A-Z0-9]+?)([A-Z][0-9]?)?$")
"""An ``EP1000000A1``-style reference.

The number group is non-greedy and the kind group optional, so ``EP1000000``
parses with no kind code rather than losing its last character to one.
"""


@dataclass(frozen=True)
class IdentityResult:
    """A parsed identity, or the reason it could not be parsed."""

    identity: PublicationIdentity | None = None
    reason: PatentRejectionReason | None = None

    @property
    def ok(self) -> bool:
        return self.identity is not None


def _fold(value: str | None) -> str:
    return "" if value is None else value.strip().upper()


def normalize_authority(value: str | None) -> str:
    """The upper-case authority code, or ``""`` when it is not one."""
    folded = _fold(value)
    return folded if _AUTHORITY.match(folded) else ""


def normalize_publication_number(value: str | None) -> str:
    """The document number with grouping separators removed, or ``""``."""
    folded = _SEPARATORS.sub("", _fold(value))
    return folded if _NUMBER.match(folded) else ""


def normalize_kind_code(value: str | None) -> str | None:
    """The upper-case kind code, or ``None`` when the provider stated none.

    ``None`` is returned both for an absent value and for a malformed one. The
    caller distinguishes the two: ``build_identity`` rejects a *stated but
    malformed* kind code rather than silently dropping it, because dropping it
    would merge a grant into its own application publication (section 16).
    """
    folded = _SEPARATORS.sub("", _fold(value))
    if not folded:
        return None
    return folded if _KIND.match(folded) else None


def normalize_family_id(value: str | None) -> str | None:
    """The provider's numeric family identifier, or ``None``."""
    folded = _SEPARATORS.sub("", _fold(value))
    if not folded:
        return None
    return folded if _FAMILY.match(folded) else None


def normalize_classification(value: str | None) -> str | None:
    """An IPC/CPC symbol with the provider's display spacing removed.

    Patent offices print ``G06N  3/08`` and ``G06N3/08`` for one symbol. The
    subgroup slash is meaningful and is kept.
    """
    folded = _fold(value).replace(" ", "")
    if not folded:
        return None
    return folded if _CLASSIFICATION.match(folded) else None


def normalize_patent_date(value: str | None) -> str | None:
    """An ISO ``YYYY-MM-DD`` date, accepting the compact ``YYYYMMDD`` EPO form.

    Returns ``None`` for anything else, including a partial date. A year-only
    or month-only patent date is not widened to the first of the period: a
    guessed day could move a publication across a cutoff (section 9).
    """
    folded = (value or "").strip()
    if not folded:
        return None
    if _DATE.match(folded):
        return folded if _is_real_date(folded) else None
    compact = _COMPACT_DATE.match(folded)
    if compact:
        candidate = "-".join(compact.groups())
        return candidate if _is_real_date(candidate) else None
    return None


def _is_real_date(iso: str) -> bool:
    """True for a calendar date that exists.

    ``0000-00-00`` is a real value in patent data for "unknown", and it must not
    become a date that sorts before every cutoff.
    """
    from datetime import date

    try:
        date.fromisoformat(iso)
    except ValueError:
        return False
    return True


def build_identity(
    *,
    authority: str | None,
    number: str | None,
    kind_code: str | None = None,
) -> IdentityResult:
    """Build a canonical identity, or say precisely why it is unusable."""
    folded_authority = normalize_authority(authority)
    if not folded_authority:
        if not _fold(authority):
            return IdentityResult(reason=PatentRejectionReason.MISSING_PUBLICATION_IDENTITY)
        return IdentityResult(reason=PatentRejectionReason.INVALID_AUTHORITY)

    folded_number = normalize_publication_number(number)
    if not folded_number:
        if not _fold(number):
            return IdentityResult(reason=PatentRejectionReason.MISSING_PUBLICATION_IDENTITY)
        return IdentityResult(reason=PatentRejectionReason.INVALID_PUBLICATION_NUMBER)

    stated_kind = _SEPARATORS.sub("", _fold(kind_code))
    folded_kind = normalize_kind_code(kind_code)
    if stated_kind and folded_kind is None:
        # Stated but unusable. Refused rather than dropped: an A1 silently
        # becoming "no kind code" would merge with the B1 grant.
        return IdentityResult(reason=PatentRejectionReason.INVALID_KIND_CODE)

    return IdentityResult(
        identity=PublicationIdentity(
            authority=folded_authority, number=folded_number, kind_code=folded_kind
        )
    )


def parse_publication_reference(reference: str | None) -> IdentityResult:
    """Parse a ``EP.1000000.A1``, ``EP1000000A1`` or ``EP 1 000 000 A1`` string.

    Used for the known-identifier lookup strategy and for reading a provider's
    family-member references, both of which supply one string rather than three
    fields.
    """
    raw = _fold(reference)
    if not raw:
        return IdentityResult(reason=PatentRejectionReason.MISSING_PUBLICATION_IDENTITY)

    dotted = [part for part in raw.split(".") if part]
    if len(dotted) >= 2:
        return build_identity(
            authority=dotted[0],
            number=dotted[1],
            kind_code=dotted[2] if len(dotted) > 2 else None,
        )

    compact = _SEPARATORS.sub("", raw)
    match = _EPODOC_REFERENCE.match(compact)
    if match is None:
        return IdentityResult(reason=PatentRejectionReason.INVALID_PUBLICATION_NUMBER)
    authority, number, kind = match.groups()
    if not any(ch.isdigit() for ch in number):
        # ``ABCD`` would otherwise parse as authority ``AB`` plus number ``C``.
        return IdentityResult(reason=PatentRejectionReason.INVALID_PUBLICATION_NUMBER)
    return build_identity(authority=authority, number=number, kind_code=kind)


def same_publication(left: PublicationIdentity, right: PublicationIdentity) -> bool:
    """Whether two identities are the same publication. Kind code included."""
    return left.same_publication(right)


__all__ = [
    "IdentityResult",
    "build_identity",
    "normalize_authority",
    "normalize_classification",
    "normalize_family_id",
    "normalize_kind_code",
    "normalize_patent_date",
    "normalize_publication_number",
    "parse_publication_reference",
    "same_publication",
]
