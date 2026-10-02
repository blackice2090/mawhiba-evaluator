"""Exact-text location without guessing -- Phase 2I section 14 (correction 6).

An excerpt that occurs once is bound to that occurrence. An excerpt that occurs
more than once is bound ONLY through a disambiguator that code validates
against the exact text: offsets with ``text[start:end] == excerpt``, or a
1-based occurrence index within range. Supplied offsets that do not slice to
the excerpt are rejected even when the excerpt is unique. There is no silent
first-occurrence fallback anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.schemas.novelty_differentiation import OccurrenceResolution


class LocateFailure(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID_OFFSETS = "INVALID_OFFSETS"
    INVALID_OCCURRENCE = "INVALID_OCCURRENCE"


@dataclass(frozen=True)
class Located:
    start: int
    end: int
    occurrence_index: int
    occurrence_count: int
    resolution: OccurrenceResolution


def occurrences(text: str, excerpt: str) -> list[int]:
    """Every start position of ``excerpt`` in ``text``, overlapping included."""
    positions: list[int] = []
    index = text.find(excerpt)
    while index >= 0:
        positions.append(index)
        index = text.find(excerpt, index + 1)
    return positions


def locate(
    text: str, excerpt: str, *, start: int | None = None, end: int | None = None, occurrence: int | None = None
) -> Located | LocateFailure:
    positions = occurrences(text, excerpt) if excerpt else []
    if not positions:
        return LocateFailure.NOT_FOUND
    count = len(positions)
    if start is not None or end is not None:
        if start is None:
            return LocateFailure.INVALID_OFFSETS
        stop = end if end is not None else start + len(excerpt)
        if not (0 <= start < stop <= len(text)) or text[start:stop] != excerpt:
            return LocateFailure.INVALID_OFFSETS
        return Located(start, stop, positions.index(start) + 1, count, OccurrenceResolution.VALIDATED_EXACT_OFFSETS)
    if occurrence is not None:
        if not 1 <= occurrence <= count:
            return LocateFailure.INVALID_OCCURRENCE
        begin = positions[occurrence - 1]
        return Located(begin, begin + len(excerpt), occurrence, count, OccurrenceResolution.VALIDATED_OCCURRENCE_INDEX)
    if count == 1:
        return Located(positions[0], positions[0] + len(excerpt), 1, 1, OccurrenceResolution.UNIQUE_IN_TEXT)
    return LocateFailure.AMBIGUOUS


__all__ = ["LocateFailure", "Located", "locate", "occurrences"]
