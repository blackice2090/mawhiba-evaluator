"""PII minimization for research.

Queries are about the project, never the student. Detection is deterministic:
regular patterns for emails, phone numbers and national IDs, plus an explicit
identity context supplied by the caller (student name, school, address, ...).

The identity context is deliberately a plain dataclass passed through runtime
config: it is never stored on graph state and therefore never checkpointed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from src.intake.anchors import collapse_whitespace, normalize_unicode

REDACTION_TOKEN = "[REDACTED]"

_EMAIL = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")
_DIGIT_RUN = re.compile(r"\+?\d[\d\s\-().]*\d")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

MIN_PHONE_DIGITS = 9
NAME_TOKEN_MIN_LENGTH = 3


class PiiKind(StrEnum):
    EMAIL = "EMAIL"
    PHONE_NUMBER = "PHONE_NUMBER"
    NATIONAL_ID = "NATIONAL_ID"
    PERSON_NAME = "PERSON_NAME"
    SCHOOL_NAME = "SCHOOL_NAME"
    ADDRESS = "ADDRESS"
    OTHER_IDENTIFIER = "OTHER_IDENTIFIER"


@dataclass(frozen=True)
class PiiEntry:
    kind: PiiKind
    value: str


@dataclass(frozen=True)
class PiiFinding:
    kind: PiiKind
    matched: str


@dataclass(frozen=True)
class ResearchPrivacyContext:
    """Known identity strings that must never reach a research provider."""

    entries: tuple[PiiEntry, ...] = field(default_factory=tuple)

    @classmethod
    def from_identity(
        cls,
        *,
        person_names: tuple[str, ...] = (),
        school_names: tuple[str, ...] = (),
        emails: tuple[str, ...] = (),
        phone_numbers: tuple[str, ...] = (),
        national_ids: tuple[str, ...] = (),
        addresses: tuple[str, ...] = (),
        other_identifiers: tuple[str, ...] = (),
    ) -> ResearchPrivacyContext:
        groups = (
            (PiiKind.PERSON_NAME, person_names),
            (PiiKind.SCHOOL_NAME, school_names),
            (PiiKind.EMAIL, emails),
            (PiiKind.PHONE_NUMBER, phone_numbers),
            (PiiKind.NATIONAL_ID, national_ids),
            (PiiKind.ADDRESS, addresses),
            (PiiKind.OTHER_IDENTIFIER, other_identifiers),
        )
        return cls(
            tuple(
                PiiEntry(kind, value.strip())
                for kind, values in groups
                for value in values
                if value and value.strip()
            )
        )


EMPTY_PRIVACY_CONTEXT = ResearchPrivacyContext()


def _ascii_digits(text: str) -> str:
    return "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text
    )


def _fold(text: str) -> str:
    return collapse_whitespace(_ascii_digits(normalize_unicode(text)).casefold())


def _digits_only(text: str) -> str:
    return "".join(ch for ch in _ascii_digits(text) if ch.isdigit())


def _pattern_findings(folded: str) -> list[PiiFinding]:
    findings = [PiiFinding(PiiKind.EMAIL, m.group(0)) for m in _EMAIL.finditer(folded)]
    for match in _DIGIT_RUN.finditer(folded):
        digits = _digits_only(match.group(0))
        if len(digits) == 10 and digits[0] in "12":
            findings.append(PiiFinding(PiiKind.NATIONAL_ID, match.group(0)))
        elif len(digits) >= MIN_PHONE_DIGITS:
            findings.append(PiiFinding(PiiKind.PHONE_NUMBER, match.group(0)))
    return findings


def _name_tokens(value: str) -> list[str]:
    return [t for t in _TOKEN.findall(_fold(value)) if len(t) >= NAME_TOKEN_MIN_LENGTH]


def detect_pii(text: str, context: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT) -> list[PiiFinding]:
    """Every PII finding in ``text``. Empty means nothing was detected."""
    if not text:
        return []
    folded = _fold(text)
    findings = _pattern_findings(folded)
    text_tokens = set(_TOKEN.findall(folded))
    text_digits = _digits_only(text)

    for entry in context.entries:
        value = _fold(entry.value)
        if not value:
            continue
        if entry.kind is PiiKind.PERSON_NAME:
            hits = [t for t in _name_tokens(entry.value) if t in text_tokens]
            findings.extend(PiiFinding(entry.kind, hit) for hit in hits)
            continue
        if len(value) >= NAME_TOKEN_MIN_LENGTH and value in folded:
            findings.append(PiiFinding(entry.kind, value))
            continue
        entry_digits = _digits_only(entry.value)
        if len(entry_digits) >= 6 and entry_digits in text_digits:
            findings.append(PiiFinding(entry.kind, entry_digits))
    return findings


def contains_pii(text: str, context: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT) -> bool:
    return bool(detect_pii(text, context))


def redact_pii(
    text: str, context: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT
) -> tuple[str, int]:
    """Replace detected PII with a redaction token. Returns (text, redactions)."""
    redacted = normalize_unicode(text)
    count = 0

    def substitute(pattern: re.Pattern[str], value: str) -> str:
        nonlocal count
        result, n = pattern.subn(REDACTION_TOKEN, value)
        count += n
        return result

    redacted = substitute(_EMAIL, redacted)

    def digit_run(match: re.Match[str]) -> str:
        nonlocal count
        if len(_digits_only(match.group(0))) >= MIN_PHONE_DIGITS:
            count += 1
            return REDACTION_TOKEN
        return match.group(0)

    redacted = _DIGIT_RUN.sub(digit_run, redacted)

    for entry in context.entries:
        if entry.kind is PiiKind.PERSON_NAME:
            for token in _name_tokens(entry.value):
                pattern = re.compile(
                    rf"(?<![^\W_]){re.escape(token)}(?![^\W_])", re.IGNORECASE
                )
                redacted = substitute(pattern, redacted)
            continue
        words = [re.escape(w) for w in normalize_unicode(entry.value).split()]
        if not words or len("".join(words)) < NAME_TOKEN_MIN_LENGTH:
            continue
        redacted = substitute(re.compile(r"\s+".join(words), re.IGNORECASE), redacted)

    return redacted, count
