"""Deterministic provenance verification. Where a proposal becomes evidence.

The whole of Phase 2C's trust rests here, on one rule:

    the stored excerpt is sliced out of the snapshot by code

A candidate arrives carrying the model's own string and the model's own idea of
where it sits. Neither is trusted. Verification searches the snapshot itself,
derives the offsets, and then takes ``snapshot.text[start:end]`` as the evidence.
"Verbatim" is therefore true by construction rather than by inspection: there is
no code path where a model's wording can be stored as an excerpt (ADR-011).

**Offsets are never trusted to define a span.** A model miscounts routinely, and
a confidently wrong offset looks exactly like verified provenance. A claimed
offset is used for one narrow purpose -- choosing between occurrences that code
has *already* verified are exact matches -- and never to locate text.

**Ambiguity is refused, not guessed.** When one sentence appears twice in an
abstract and nothing deterministic distinguishes them, the candidate is rejected
as ``AMBIGUOUS_SPAN``. Picking the first occurrence would produce evidence whose
offsets point somewhere the model may not have meant.

**Numbers must survive the round trip.** Every structured numeric observation is
re-checked against the verified excerpt, so 92.3% cannot be recorded as 93.2%,
milliseconds cannot become seconds, and n=40 cannot become n=400.

Matching tolerates exactly two kinds of difference, both of which are pure
transport noise rather than meaning: CRLF/LF line-ending differences, and
repeated whitespace / line-break runs. Nothing here folds quote or dash
variants, minus signs, scientific symbols, digits, decimal separators, units,
comparison operators or negation. A candidate whose only match requires a
punctuation or symbol substitution is rejected as ``EXCERPT_NOT_FOUND`` --
trust prefers rejection over an uncertain match (Phase 2C.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.schemas.evidence_extraction import (
    MAX_EVIDENCE_EXCERPT_CHARS,
    MIN_EVIDENCE_EXCERPT_CHARS,
    EvidenceRejectionReason,
    NumericObservation,
    SourceContentSnapshot,
    SpanMatchMethod,
)

VERIFICATION_VERSION = "EVIDENCE-VERIFIER-V2"

_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_ABSURD_EXCERPT_CHARS = MAX_EVIDENCE_EXCERPT_CHARS * 4
"""Guard before any regex work, so a pathological candidate cannot burn time."""


@dataclass
class SpanResolution:
    """Where an excerpt actually sits in the snapshot, or why it does not."""

    start: int | None = None
    end: int | None = None
    excerpt: str | None = None
    method: SpanMatchMethod | None = None
    reason: EvidenceRejectionReason | None = None

    @property
    def resolved(self) -> bool:
        return self.reason is None and self.start is not None


@dataclass
class NumericVerification:
    """Which numeric observations survived re-checking against the excerpt."""

    accepted: list[NumericObservation] = field(default_factory=list)
    reason: EvidenceRejectionReason | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None


# ---------------------------------------------------------------------------
# Span resolution
# ---------------------------------------------------------------------------


def _line_endings_to_lf(text: str) -> tuple[str, list[int]]:
    """Fold CRLF/CR to LF, keeping a map back to the original offsets.

    ``index_map[k]`` is the original index corresponding to position ``k`` of
    the folded text; ``index_map`` carries one trailing sentinel equal to
    ``len(text)`` so an end-of-match position always resolves.
    """
    folded_chars: list[str] = []
    index_map: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\r" and i + 1 < n and text[i + 1] == "\n":
            folded_chars.append("\n")
            index_map.append(i)
            i += 2
        elif text[i] == "\r":
            folded_chars.append("\n")
            index_map.append(i)
            i += 1
        else:
            folded_chars.append(text[i])
            index_map.append(i)
            i += 1
    index_map.append(n)
    return "".join(folded_chars), index_map


def _whitespace_pattern(excerpt: str) -> str:
    """A regex matching ``excerpt`` in the original text, tolerating only
    whitespace-run and line-break differences.

    Every whitespace run collapses to ``\\s+`` -- so a line break in the
    snapshot matches a space in the candidate and vice versa. Every other
    character, including quotes, dashes, minus signs, scientific symbols,
    digits and decimal separators, is escaped literally and must match
    exactly.
    """
    parts: list[str] = []
    previous_was_space = False
    for character in excerpt:
        if character.isspace():
            if not previous_was_space:
                parts.append(r"\s+")
            previous_was_space = True
            continue
        previous_was_space = False
        parts.append(re.escape(character))
    return "".join(parts)


def _match_method(matched: str, excerpt: str) -> SpanMatchMethod:
    """How much tolerance the match actually needed."""
    if matched == excerpt:
        return SpanMatchMethod.EXACT
    return SpanMatchMethod.NORMALIZED_WHITESPACE


def _exact_occurrences(text: str, excerpt: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = text.find(excerpt)
    while start != -1:
        spans.append((start, start + len(excerpt)))
        start = text.find(excerpt, start + 1)
    return spans


def _line_ending_occurrences(text: str, excerpt: str) -> list[tuple[int, int]]:
    """Exact match after folding CRLF/CR to LF on both sides, offsets mapped
    back to the original (unfolded) snapshot text."""
    folded_text, index_map = _line_endings_to_lf(text)
    folded_excerpt, _ = _line_endings_to_lf(excerpt)
    spans: list[tuple[int, int]] = []
    start = folded_text.find(folded_excerpt)
    while start != -1:
        end = start + len(folded_excerpt)
        spans.append((index_map[start], index_map[end]))
        start = folded_text.find(folded_excerpt, start + 1)
    return spans


def _whitespace_occurrences(text: str, excerpt: str) -> list[tuple[int, int]]:
    pattern = _whitespace_pattern(excerpt)
    if not pattern:
        return []
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _select(
    text: str,
    spans: list[tuple[int, int]],
    excerpt: str,
    claimed_start: int | None,
    method: SpanMatchMethod,
) -> SpanResolution:
    """Turn located occurrences into a resolution.

    With several occurrences, a claimed offset may pick one -- but only by
    exactly matching an occurrence code already verified. That is disambiguation
    among proven matches, not trusting the model to find text.
    """
    if not spans:
        return SpanResolution(reason=EvidenceRejectionReason.EXCERPT_NOT_FOUND)

    if len(spans) > 1:
        chosen = [span for span in spans if span[0] == claimed_start]
        if len(chosen) != 1:
            return SpanResolution(reason=EvidenceRejectionReason.AMBIGUOUS_SPAN)
        spans = chosen

    start, end = spans[0]
    matched = text[start:end]
    resolved_method = _match_method(matched, excerpt) if method is SpanMatchMethod.EXACT else method
    return SpanResolution(
        start=start,
        end=end,
        excerpt=matched,
        method=resolved_method,
    )


def resolve_span(
    snapshot: SourceContentSnapshot, excerpt: str, claimed_start: int | None = None
) -> SpanResolution:
    """Locate ``excerpt`` in the snapshot and derive its canonical offsets.

    Three escalating attempts, each recorded by ``method``:

    1. EXACT -- byte-for-byte occurrence, offsets are exact.
    2. NORMALIZED_UNICODE -- after folding CRLF/CR line endings to LF on both
       sides, mapped back to the original snapshot offsets.
    3. NORMALIZED_WHITESPACE -- after additionally tolerating whitespace-run
       and line-break differences.

    No stage tolerates quote, dash, minus-sign, scientific-symbol, digit or
    unit substitution: a candidate that only matches after such a change is
    rejected as ``EXCERPT_NOT_FOUND``, never accepted.
    """
    if not excerpt or not excerpt.strip():
        return SpanResolution(reason=EvidenceRejectionReason.EXCERPT_NOT_FOUND)
    if len(excerpt) > _ABSURD_EXCERPT_CHARS:
        return SpanResolution(reason=EvidenceRejectionReason.EXCERPT_TOO_LONG)

    text = snapshot.text

    resolution = _select(
        text, _exact_occurrences(text, excerpt), excerpt, claimed_start, SpanMatchMethod.EXACT
    )
    if resolution.resolved or resolution.reason is EvidenceRejectionReason.AMBIGUOUS_SPAN:
        return resolution

    resolution = _select(
        text,
        _line_ending_occurrences(text, excerpt),
        excerpt,
        claimed_start,
        SpanMatchMethod.NORMALIZED_UNICODE,
    )
    if resolution.resolved or resolution.reason is EvidenceRejectionReason.AMBIGUOUS_SPAN:
        return resolution

    return _select(
        text,
        _whitespace_occurrences(text, excerpt),
        excerpt,
        claimed_start,
        SpanMatchMethod.NORMALIZED_WHITESPACE,
    )


def check_excerpt_length(
    excerpt: str,
    *,
    minimum: int = MIN_EVIDENCE_EXCERPT_CHARS,
    maximum: int = MAX_EVIDENCE_EXCERPT_CHARS,
) -> EvidenceRejectionReason | None:
    """Bounds on the verified excerpt. Applied to the snapshot's own text."""
    if len(excerpt) < minimum:
        return EvidenceRejectionReason.EXCERPT_TOO_SHORT
    if len(excerpt) > maximum:
        return EvidenceRejectionReason.EXCERPT_TOO_LONG
    return None


# ---------------------------------------------------------------------------
# Numeric fidelity
# ---------------------------------------------------------------------------


def _literals(text: str) -> list[float]:
    """Every number written in the text, as written."""
    values: list[float] = []
    for match in _NUMBER.finditer(text):
        try:
            values.append(float(match.group(0).replace(",", "")))
        except ValueError:  # pragma: no cover -- the pattern guarantees a number
            continue
    return values


def _unit_stated(unit: str, raw_text: str) -> bool:
    """The unit must appear as its own token, not inside a longer one.

    This is what separates ``5 ms`` from ``5 s``: the ``s`` in ``ms`` is part of
    another unit, so a candidate claiming seconds does not verify.
    """
    return (
        re.search(rf"(?<![A-Za-z]){re.escape(unit)}(?![A-Za-z])", raw_text) is not None
    )


def verify_numeric_observations(
    observations: list[NumericObservation], verified_excerpt: str
) -> NumericVerification:
    """Re-check every number against the excerpt code proved (§18).

    A missing observation is not inferred and a present one is not adjusted: any
    disagreement rejects the whole candidate, because a candidate that got one
    number wrong has not earned trust in the others.
    """
    result = NumericVerification()

    for observation in observations:
        if not _whitespace_occurrences(verified_excerpt, observation.raw_text):
            result.reason = EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION
            return NumericVerification(reason=result.reason)

        literals = _literals(observation.raw_text)
        if observation.value is not None and observation.value not in literals:
            return NumericVerification(
                reason=EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION
            )
        if observation.sample_size is not None and float(
            observation.sample_size
        ) not in literals:
            return NumericVerification(
                reason=EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION
            )
        if observation.unit and not _unit_stated(observation.unit, observation.raw_text):
            return NumericVerification(
                reason=EvidenceRejectionReason.INVALID_UNIT_FIDELITY
            )
        if observation.uncertainty and not _whitespace_occurrences(
            verified_excerpt, observation.uncertainty
        ):
            return NumericVerification(
                reason=EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION
            )

        result.accepted.append(observation)

    return result


__all__ = [
    "VERIFICATION_VERSION",
    "NumericVerification",
    "SpanResolution",
    "check_excerpt_length",
    "resolve_span",
    "verify_numeric_observations",
]
