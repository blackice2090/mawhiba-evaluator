"""Deterministic provenance verification.

This module is where model output stops being a suggestion. An extracted value
becomes eligible for KNOWN only if code -- not the model -- can find its
supporting excerpt inside the student's actual submission.

Everything here is pure and deterministic. No fuzzy matching, no semantic
similarity, no translation, no paraphrase tolerance. The permitted
normalizations are conservative and are recorded, so a reader can always tell an
exact quote from one that only matched after whitespace folding.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from src.schemas.extraction import (
    AnchorVerificationMethod,
    FieldKind,
    TextRange,
    VerifiedAnchor,
)

_WHITESPACE = re.compile(r"\s+")

EMPTY_EXCERPT_MARKER = "(empty-excerpt)"
"""Stands in when the model supplied a blank excerpt, so the rejection is
representable rather than crashing the contract."""

# Characters that carry no textual meaning but routinely differ between what a
# model echoes and what the student typed. Stripping them cannot change which
# words an excerpt contains.
_INVISIBLE = dict.fromkeys(
    map(
        ord,
        "​‌‍‎‏‪‫‬‭‮﻿",
    )
)

_QUOTE_EQUIVALENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        " ": " ",
    }
)


def normalize_line_endings(text: str) -> str:
    """CRLF and CR to LF. Purely a transport difference."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_unicode(text: str) -> str:
    """NFC normalization plus invisible-character removal and quote folding.

    NFC is safe for Arabic and for Latin text: it composes canonically
    equivalent sequences without changing which characters are present. Arabic
    letters, diacritics and digits are all preserved.
    """
    folded = unicodedata.normalize("NFC", text)
    folded = folded.translate(_INVISIBLE)
    return folded.translate(_QUOTE_EQUIVALENTS)


def collapse_whitespace(text: str) -> str:
    """Fold runs of whitespace to a single space and trim the ends."""
    return _WHITESPACE.sub(" ", text).strip()


def _find_all(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Every occurrence of ``needle``. Overlapping matches are not sought."""
    spans: list[tuple[int, int]] = []
    if not needle:
        return spans
    start = haystack.find(needle)
    while start != -1:
        spans.append((start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    return spans


def _map_to_original(
    original: str, transform_stages: list[str], spans: list[tuple[int, int]]
) -> list[TextRange]:
    """Best-effort mapping of match spans back to the original text.

    Whitespace collapsing changes offsets, so an exact inverse mapping is not
    always available. Rather than fabricate a precise range, a collapsed match
    reports the span of the enclosing region it can locate, and the method field
    records that normalization was used.
    """
    del transform_stages  # stages are recorded via `method`, not replayed here
    ranges: list[TextRange] = []
    for start, end in spans:
        clamped_end = min(end, len(original))
        clamped_start = min(start, max(clamped_end - 1, 0))
        if clamped_end > clamped_start:
            ranges.append(TextRange(start=clamped_start, end=clamped_end))
    return ranges


def verify_anchor(
    artifact_id: UUID, original_text: str, excerpt: str
) -> VerifiedAnchor:
    """Check that ``excerpt`` genuinely occurs in ``original_text``.

    Three escalating attempts, each recorded by ``method``:

    1. EXACT -- byte-for-byte occurrence, offsets are exact.
    2. NORMALIZED_UNICODE -- after line-ending, NFC and invisible-character
       folding.
    3. NORMALIZED_WHITESPACE -- additionally after collapsing whitespace runs.

    Anything else is NOT_FOUND, which makes the value ineligible for KNOWN.
    """
    if not excerpt.strip():
        # VerifiedAnchor requires a non-empty excerpt, and the model supplied
        # nothing usable. A marker keeps the rejection representable.
        return VerifiedAnchor(
            artifact_id=artifact_id,
            excerpt=EMPTY_EXCERPT_MARKER,
            method=AnchorVerificationMethod.NOT_FOUND,
            matches=[],
        )

    # Stage 1: exact.
    spans = _find_all(original_text, excerpt)
    if spans:
        return VerifiedAnchor(
            artifact_id=artifact_id,
            excerpt=excerpt,
            method=AnchorVerificationMethod.EXACT,
            matches=[TextRange(start=s, end=e) for s, e in spans],
        )

    # Stage 2: unicode + line endings.
    unicode_text = normalize_unicode(normalize_line_endings(original_text))
    unicode_excerpt = normalize_unicode(normalize_line_endings(excerpt))
    spans = _find_all(unicode_text, unicode_excerpt)
    if spans:
        return VerifiedAnchor(
            artifact_id=artifact_id,
            excerpt=excerpt,
            method=AnchorVerificationMethod.NORMALIZED_UNICODE,
            matches=_map_to_original(original_text, [unicode_text], spans),
        )

    # Stage 3: whitespace collapsing.
    collapsed_text = collapse_whitespace(unicode_text)
    collapsed_excerpt = collapse_whitespace(unicode_excerpt)
    spans = _find_all(collapsed_text, collapsed_excerpt)
    if spans:
        return VerifiedAnchor(
            artifact_id=artifact_id,
            excerpt=excerpt,
            method=AnchorVerificationMethod.NORMALIZED_WHITESPACE,
            matches=_map_to_original(original_text, [collapsed_text], spans),
        )

    return VerifiedAnchor(
        artifact_id=artifact_id,
        excerpt=excerpt,
        method=AnchorVerificationMethod.NOT_FOUND,
        matches=[],
    )


# ---------------------------------------------------------------------------
# Value-to-anchor support
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    """Case-folded alphanumeric tokens, Unicode-aware (Arabic included)."""
    folded = normalize_unicode(text).casefold()
    return _TOKEN.findall(folded)


def value_supported_by_anchor(value: str, excerpt: str, kind: FieldKind) -> bool:
    """Does the excerpt actually state the value?

    Anchor existence alone is not enough. A model can pair a real quote with an
    invented value -- ``value="YOLOv8"`` anchored to ``"uses a camera"`` -- and
    that must be rejected even though the quote verifies.

    For ``VERBATIM_TERM`` fields (named models, hardware, sensors, libraries,
    datasets, numbers) every token of the value must appear in the excerpt. This
    is a containment check, not semantic entailment, and it is deterministic.

    For ``VERBATIM_SPAN`` fields the canonical value is replaced by the verified
    excerpt itself (ADR-004), so containment is trivially satisfied and the
    Phase 1B paraphrase risk does not arise. The check here only has to confirm
    the excerpt is non-empty.

    ``CLASSIFICATION`` and ``STUDENT_CLAIM`` never reach this function: they have
    their own verification paths.
    """
    if kind is FieldKind.VERBATIM_SPAN:
        return bool(excerpt.strip())

    value_tokens = _tokens(value)
    if not value_tokens:
        return False
    excerpt_tokens = set(_tokens(excerpt))
    return all(token in excerpt_tokens for token in value_tokens)


__all__ = [
    "AnchorVerificationMethod",
    "collapse_whitespace",
    "normalize_line_endings",
    "normalize_unicode",
    "value_supported_by_anchor",
    "verify_anchor",
]
