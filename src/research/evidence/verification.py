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

Matching tolerates exactly two kinds of difference, both of which are transport
noise rather than meaning: whitespace runs and typographic quote/dash variants.
Nothing here folds case, strips negation, normalizes digits, or touches units.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.intake.anchors import normalize_unicode
from src.schemas.evidence_extraction import (
    MAX_EVIDENCE_EXCERPT_CHARS,
    MIN_EVIDENCE_EXCERPT_CHARS,
    EvidenceRejectionReason,
    NumericObservation,
    SourceContentSnapshot,
    SpanMatchMethod,
)

VERIFICATION_VERSION = "EVIDENCE-VERIFIER-V1"

_TYPOGRAPHIC_EQUIVALENTS: dict[str, str] = {
    "'": "'‘’′",
    '"': '"“”″',
    "-": "-‐‑‒–—",
}
"""Characters a provider, a PDF extractor and a model spell differently.

Folding these cannot change which words an excerpt contains, which is the test
every tolerance here has to pass.
"""

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


def _tolerant_pattern(excerpt: str) -> str:
    """A regex matching ``excerpt`` in original text, tolerating noise only.

    Whitespace runs become ``\\s+`` so a line break in the snapshot matches a
    space in the candidate, and typographic variants become character classes.
    Every other character is escaped literally -- digits, units, negation words
    and scientific symbols all have to match exactly.
    """
    parts: list[str] = []
    previous_was_space = False
    for character in normalize_unicode(excerpt):
        if character.isspace():
            if not previous_was_space:
                parts.append(r"\s+")
            previous_was_space = True
            continue
        previous_was_space = False
        equivalents = _TYPOGRAPHIC_EQUIVALENTS.get(character)
        parts.append(
            f"[{re.escape(equivalents)}]" if equivalents else re.escape(character)
        )
    return "".join(parts)


def _match_method(matched: str, excerpt: str) -> SpanMatchMethod:
    """How much tolerance the match actually needed."""
    if matched == excerpt:
        return SpanMatchMethod.EXACT
    if normalize_unicode(matched) == normalize_unicode(excerpt):
        return SpanMatchMethod.NORMALIZED_UNICODE
    return SpanMatchMethod.NORMALIZED_WHITESPACE


def _exact_occurrences(text: str, excerpt: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = text.find(excerpt)
    while start != -1:
        spans.append((start, start + len(excerpt)))
        start = text.find(excerpt, start + 1)
    return spans


def _tolerant_occurrences(text: str, excerpt: str) -> list[tuple[int, int]]:
    pattern = _tolerant_pattern(excerpt)
    if not pattern:
        return []
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _select(
    text: str,
    spans: list[tuple[int, int]],
    excerpt: str,
    claimed_start: int | None,
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
    return SpanResolution(
        start=start,
        end=end,
        excerpt=matched,
        method=_match_method(matched, excerpt),
    )


def resolve_span(
    snapshot: SourceContentSnapshot, excerpt: str, claimed_start: int | None = None
) -> SpanResolution:
    """Locate ``excerpt`` in the snapshot and derive its canonical offsets."""
    if not excerpt or not excerpt.strip():
        return SpanResolution(reason=EvidenceRejectionReason.EXCERPT_NOT_FOUND)
    if len(excerpt) > _ABSURD_EXCERPT_CHARS:
        return SpanResolution(reason=EvidenceRejectionReason.EXCERPT_TOO_LONG)

    text = snapshot.text
    resolution = _select(text, _exact_occurrences(text, excerpt), excerpt, claimed_start)
    if resolution.resolved or resolution.reason is EvidenceRejectionReason.AMBIGUOUS_SPAN:
        return resolution

    return _select(text, _tolerant_occurrences(text, excerpt), excerpt, claimed_start)


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
        if not _tolerant_occurrences(verified_excerpt, observation.raw_text):
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
        if observation.uncertainty and not _tolerant_occurrences(
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
