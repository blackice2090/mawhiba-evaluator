"""Deterministic claim-anchor resolution (section 6).

Exact matching only. No punctuation, digit, unit, negation, mathematical
symbol or whitespace normalization -- a candidate anchor is trusted only when
it is byte-identical to a substring of the claim's own text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnchorResolution:
    resolved: bool
    start: int | None = None
    end: int | None = None
    text: str | None = None
    ambiguous: bool = False


def resolve_anchor(
    claim_text: str, claimed_text: str, claimed_start: int | None
) -> AnchorResolution:
    """Locate ``claimed_text`` inside ``claim_text``, exactly.

    A model-supplied ``claimed_start`` is used only to disambiguate between
    multiple identical occurrences; it is never trusted to define the span by
    itself (mirrors the Phase 2C rule for evidence offsets).
    """
    if not claimed_text:
        return AnchorResolution(resolved=False)

    occurrences: list[int] = []
    start_search = 0
    while True:
        index = claim_text.find(claimed_text, start_search)
        if index == -1:
            break
        occurrences.append(index)
        start_search = index + 1

    if not occurrences:
        return AnchorResolution(resolved=False)

    if len(occurrences) == 1:
        start = occurrences[0]
    elif claimed_start is not None and claimed_start in occurrences:
        start = claimed_start
    else:
        # Ambiguous: more than one identical occurrence and no way to pin one
        # down. Deterministic, not guessed -- always the first occurrence, so
        # the outcome is stable across replays.
        start = occurrences[0]

    end = start + len(claimed_text)
    return AnchorResolution(
        resolved=True,
        start=start,
        end=end,
        text=claim_text[start:end],
        ambiguous=len(occurrences) > 1,
    )


__all__ = ["AnchorResolution", "resolve_anchor"]
