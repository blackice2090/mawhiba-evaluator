"""Provider-neutral normalization helpers.

Each connector owns its own DTOs and its own field mapping; everything that must
behave identically across providers lives here: identifier validation, text and
date hygiene, within-response duplicate detection, and the rules that turn a
batch of accepted and rejected records into one ``AcademicSearchResult``.

Two invariants this module exists to hold:

* **One bad record does not discard a good response.** Records are validated one
  at a time, and a rejection is written to the ledger rather than raised.
* **A status describes what happened, not what we wish had happened.** A provider
  that answered with nothing is ``EMPTY``; a provider whose every record was
  malformed is ``INVALID_RESPONSE``; neither is ``PROVIDER_ERROR``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime
from typing import Any
from uuid import UUID

from src.research.academic.http import TransportOutcome
from src.schemas.academic import (
    MAX_PUBLICATION_YEAR,
    MIN_PUBLICATION_YEAR,
    PUBLICATION_DATE_PATTERN,
    AcademicIdentifiers,
    AcademicRejectionReason,
    AcademicRejectionStage,
    AcademicSearchQuery,
    AcademicSearchResult,
    AcademicSearchStatus,
    AcademicSourceCandidate,
    RejectedAcademicCandidate,
    safe_summary,
)
from src.research.academic.identifiers import NormalizedIdentifier

_WHITESPACE = re.compile(r"\s+")
_DATE = re.compile(PUBLICATION_DATE_PATTERN)

INVALID_IDENTIFIER_REASONS: dict[str, AcademicRejectionReason] = {
    "doi": AcademicRejectionReason.INVALID_DOI,
    "pmid": AcademicRejectionReason.INVALID_PMID,
    "openalex_id": AcademicRejectionReason.INVALID_OPENALEX_ID,
    "semantic_scholar_id": AcademicRejectionReason.INVALID_SEMANTIC_SCHOLAR_ID,
    "arxiv_id": AcademicRejectionReason.INVALID_ARXIV_ID,
}


@dataclass
class NormalizedResponse:
    """What one provider response reduced to, before budget and verification."""

    raw_count: int = 0
    candidates: list[AcademicSourceCandidate] = dc_field(default_factory=list)
    rejected: list[RejectedAcademicCandidate] = dc_field(default_factory=list)


def clean_text(value: object) -> str | None:
    """Collapse whitespace; empty becomes ``None``.

    Content is otherwise untouched. Provider text is data: an abstract that
    contains instruction-like wording stays exactly as the provider sent it and
    is never interpreted (section 38).
    """
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def clean_authors(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    cleaned = [clean_text(v) for v in values]
    return [name for name in cleaned if name]


def clean_year(value: object) -> tuple[int | None, bool]:
    """``(year, invalid)``. A year outside the contract range is invalid, not None."""
    if value is None or value == "":
        return None, False
    try:
        year = int(str(value).strip())
    except ValueError:
        return None, True
    if not MIN_PUBLICATION_YEAR <= year <= MAX_PUBLICATION_YEAR:
        return None, True
    return year, False


def clean_date(value: object) -> str | None:
    """An ISO ``YYYY-MM-DD`` date, or ``None``. Nothing is reformatted or guessed."""
    text = clean_text(value)
    if text and _DATE.fullmatch(text[:10]) and len(text) >= 10:
        return text[:10]
    return None


def clean_count(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        count = int(str(value).strip())
    except ValueError:
        return None
    return count if count >= 0 else None


def clean_flag(value: object) -> bool | None:
    """Only a real boolean. Anything else stays unknown rather than becoming False."""
    return value if isinstance(value, bool) else None


def raw_metadata(payload: Any) -> str | None:
    """Compact, key-sorted JSON of the provider record.

    Sorted so the checkpoint payload is byte-stable across runs; compact so a
    ledger entry stays small. Credentials never appear here because only the
    response body is passed in, never the request.
    """
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def build_identifiers(
    fields: dict[str, NormalizedIdentifier],
) -> tuple[AcademicIdentifiers, AcademicRejectionReason | None]:
    """Assemble validated identifiers, or name the first invalid one.

    Priority of the reported reason follows ``INVALID_IDENTIFIER_REASONS``
    insertion order, so a record with two broken identifiers always reports the
    same one.
    """
    for name, reason in INVALID_IDENTIFIER_REASONS.items():
        outcome = fields.get(name)
        if outcome is not None and outcome.invalid:
            return AcademicIdentifiers(), reason
    return (
        AcademicIdentifiers(
            **{
                name: outcome.value
                for name, outcome in fields.items()
                if name in INVALID_IDENTIFIER_REASONS and outcome.value
            }
        ),
        None,
    )


def rejection(
    query: AcademicSearchQuery,
    reason: AcademicRejectionReason,
    *,
    stage: AcademicRejectionStage = AcademicRejectionStage.NORMALIZATION,
    record_id: str | None = None,
    summary: str | None = None,
) -> RejectedAcademicCandidate:
    """One ledger entry. Never carries the full provider payload."""
    return RejectedAcademicCandidate(
        provider=query.provider,
        query_id=query.query_id,
        stage=stage,
        reason=reason,
        provider_record_identifier=record_id,
        safe_summary=""
        if reason is AcademicRejectionReason.PII_DETECTED
        else safe_summary(summary),
    )


def drop_within_provider_duplicates(
    query: AcademicSearchQuery, candidates: list[AcademicSourceCandidate]
) -> tuple[list[AcademicSourceCandidate], list[RejectedAcademicCandidate]]:
    """Collapse records one provider returned twice in one response.

    Only an identical strong identity counts as a repeat. Two records with the
    same title and no identifier are kept: they may be two different works
    (ADR-009), and this project never deduplicates on a title.
    """
    kept: list[AcademicSourceCandidate] = []
    rejected: list[RejectedAcademicCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        identity = candidate.identity
        if identity is None:
            kept.append(candidate)
            continue
        key = (identity[0].value, identity[1])
        if key in seen:
            rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.DUPLICATE_PROVIDER_RECORD,
                    record_id=candidate.provider_record_id,
                    summary=candidate.title,
                )
            )
            continue
        seen.add(key)
        kept.append(candidate)
    return kept, rejected


def decide_status(
    raw_count: int, accepted: int, rejected: int
) -> AcademicSearchStatus:
    """The envelope status for a provider that answered."""
    if raw_count == 0:
        return AcademicSearchStatus.EMPTY
    if accepted == 0:
        return AcademicSearchStatus.INVALID_RESPONSE
    return (
        AcademicSearchStatus.PARTIAL if rejected else AcademicSearchStatus.SUCCESS
    )


def build_result(
    query: AcademicSearchQuery,
    outcome: TransportOutcome,
    *,
    started_at: datetime,
    completed_at: datetime,
    raw_count: int = 0,
    candidates: list[AcademicSourceCandidate] | None = None,
    rejected: list[RejectedAcademicCandidate] | None = None,
) -> AcademicSearchResult:
    """One provider's answer to one query, as the branch will consume it."""
    candidates = candidates or []
    rejected = rejected or []
    failure_status = outcome.status
    if failure_status is not None:
        candidates, raw_count = [], 0

    return AcademicSearchResult(
        provider=query.provider,
        query_id=query.query_id,
        research_run_id=query.research_run_id,
        status=failure_status
        or decide_status(raw_count, len(candidates), len(rejected)),
        attempts=max(outcome.attempts, 1),
        requested_limit=query.requested_limit,
        raw_count=raw_count,
        accepted_count=len(candidates),
        rejected_count=len(rejected),
        candidates=candidates,
        rejected=rejected,
        rate_limit=outcome.rate_limit,
        errors=list(outcome.errors),
        started_at=started_at,
        completed_at=completed_at,
    )


def candidate_base(query: AcademicSearchQuery, retrieved_at: datetime) -> dict[str, Any]:
    """The provenance fields every candidate carries, whatever the provider."""
    return {
        "research_run_id": query.research_run_id,
        "query_id": query.query_id,
        "provider": query.provider,
        "retrieved_at": retrieved_at,
    }


def truncate(records: list[Any], limit: int) -> tuple[list[Any], int]:
    """Apply a result limit. Returns the kept records and how many were cut."""
    if limit >= len(records):
        return records, 0
    return records[:limit], len(records) - limit


def as_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


__all__ = [
    "INVALID_IDENTIFIER_REASONS",
    "NormalizedResponse",
    "as_uuid",
    "build_identifiers",
    "build_result",
    "candidate_base",
    "clean_authors",
    "clean_count",
    "clean_date",
    "clean_flag",
    "clean_text",
    "clean_year",
    "decide_status",
    "drop_within_provider_duplicates",
    "raw_metadata",
    "rejection",
    "truncate",
]
