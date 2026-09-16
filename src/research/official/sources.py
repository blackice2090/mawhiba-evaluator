"""Retrieval -> SourceCandidate -> verification -> OfficialSourceSnapshot / SourceRecord.

No function here creates an ``EvidenceRecord``. A candidate becomes a source only
after deterministic checks: successful retrieval, allowlisted requested and final
URLs, non-empty content, and a content hash that recomputes identically.

Currency is assessed separately from verification: a page can pass every check and
still describe a past competition edition.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from uuid import UUID

from src.intake.anchors import collapse_whitespace, normalize_line_endings, normalize_unicode
from src.research.official.allowlist import canonicalize_url, check_official_url, official_domain
from src.research.official.provider import OfficialWebProvider
from src.schemas.common import new_source_id
from src.schemas.official import (
    EditionSource,
    OfficialCurrency,
    OfficialPageKind,
    OfficialRetrievalResult,
    OfficialSeed,
    OfficialSourceSnapshot,
    RetrievalStatus,
    SourceCandidate,
    SourceRejectionReason,
    SourceVerificationDecision,
)
from src.schemas.source import SourceFingerprint, SourceRecord

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def content_hash(text: str) -> str:
    """SHA-256 over normalized text (HASH_NORMALIZATION_VERSION).

    Transport noise (line endings, whitespace runs, NFC) does not change the hash;
    any change in wording does.
    """
    normalized = collapse_whitespace(normalize_unicode(normalize_line_endings(text)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text)


def title_edition(title: str | None) -> int | None:
    """The single competition year a page title states, or None.

    Two years in one title is ambiguous, so it yields nothing rather than a guess.
    """
    if not title:
        return None
    years = {int(year) for year in _YEAR.findall(_ascii_digits(normalize_unicode(title)))}
    return years.pop() if len(years) == 1 else None


def assess_currency(
    page_kind: OfficialPageKind,
    declared_edition: int | None,
    title: str | None,
    target_edition: int | None,
) -> tuple[int | None, EditionSource, OfficialCurrency]:
    """Decide which edition a verified official page speaks for.

    The retrieval date is never an input: a page fetched today is not thereby the
    current edition. Without a configured ``target_edition`` an edition-specific
    page is UNDETERMINED rather than current.
    """
    hint = title_edition(title)

    if page_kind is OfficialPageKind.EVERGREEN_SERVICE_PAGE:
        if hint is not None:
            # A service page naming one year is not behaving like an evergreen page.
            return hint, EditionSource.PAGE_TITLE, OfficialCurrency.UNDETERMINED
        return None, EditionSource.NONE, OfficialCurrency.EVERGREEN

    if page_kind is OfficialPageKind.DISCOVERY_PAGE:
        if hint is not None:
            return hint, EditionSource.PAGE_TITLE, OfficialCurrency.UNDETERMINED
        return None, EditionSource.NONE, OfficialCurrency.UNDETERMINED

    edition, source = declared_edition, EditionSource.SEED_DECLARATION
    if hint is not None and hint != edition:
        # The page contradicts the reviewer's declaration; neither is assumed right.
        return edition, source, OfficialCurrency.UNDETERMINED
    if page_kind is OfficialPageKind.HISTORICAL_EVENT_PAGE:
        return edition, source, OfficialCurrency.HISTORICAL_EDITION
    if target_edition is None:
        return edition, source, OfficialCurrency.UNDETERMINED
    if edition == target_edition:
        return edition, source, OfficialCurrency.CURRENT_EDITION
    if edition is not None and edition < target_edition:
        return edition, source, OfficialCurrency.HISTORICAL_EDITION
    return edition, source, OfficialCurrency.UNDETERMINED


def candidate_from_result(
    result: OfficialRetrievalResult, research_run_id: UUID, seed: OfficialSeed | None = None
) -> SourceCandidate:
    success = result.status is RetrievalStatus.SUCCESS
    return SourceCandidate(
        research_run_id=research_run_id,
        requested_url=result.requested_url,
        final_url=result.final_url,
        page_kind=seed.kind if seed else OfficialPageKind.DISCOVERY_PAGE,
        declared_edition=seed.competition_edition if seed else None,
        retrieval_status=result.status,
        http_status=result.http_status,
        content_type=result.content_type,
        title=result.title,
        captured_text=result.text if success else None,
        content_hash=content_hash(result.text) if success and result.text else None,
        published_at=result.published_at,
        effective_at=result.effective_at,
        retrieved_at=result.retrieved_at,
        provider=result.provider,
        error=result.error,
    )


def retrieve_official_candidates(
    provider: OfficialWebProvider, seeds: list[OfficialSeed], research_run_id: UUID
) -> list[SourceCandidate]:
    """Retrieve every seed once. A provider fault becomes a failed candidate."""
    candidates: list[SourceCandidate] = []
    seen: set[str] = set()
    for seed in seeds:
        if seed.url in seen:
            continue
        seen.add(seed.url)
        try:
            result = provider.retrieve(seed.url)
        except Exception as exc:  # noqa: BLE001 -- a provider fault is a retrieval outcome
            result = OfficialRetrievalResult(
                status=RetrievalStatus.NETWORK_ERROR,
                requested_url=seed.url,
                error=f"provider raised {type(exc).__name__}",
                provider=getattr(provider, "name", "unknown"),
            )
        candidates.append(candidate_from_result(result, research_run_id, seed))
    return candidates


def _rejection(candidate: SourceCandidate) -> SourceRejectionReason | None:
    if candidate.retrieval_status is not RetrievalStatus.SUCCESS:
        return SourceRejectionReason.RETRIEVAL_FAILED
    requested = check_official_url(candidate.requested_url)
    if requested is not None:
        return requested
    if candidate.final_url and check_official_url(candidate.final_url) is not None:
        return SourceRejectionReason.REDIRECT_NOT_ALLOWLISTED
    if not candidate.captured_text or not candidate.captured_text.strip():
        return SourceRejectionReason.EMPTY_CONTENT
    if content_hash(candidate.captured_text) != candidate.content_hash:
        return SourceRejectionReason.CONTENT_HASH_MISMATCH
    return None


def verify_official_candidates(
    candidates: list[SourceCandidate], *, target_edition: int | None = None
) -> tuple[list[SourceVerificationDecision], list[OfficialSourceSnapshot], list[SourceRecord]]:
    """Deterministic source verification. The same content version is snapshotted once.

    ``source_id`` is globally unique and opaque; ``display_id`` is the readable
    sequence for reports and is never identity.
    """
    decisions: list[SourceVerificationDecision] = []
    snapshots: list[OfficialSourceSnapshot] = []
    by_version: dict[tuple[str, str | None], tuple[str, str]] = {}

    for candidate in candidates:
        reason = _rejection(candidate)
        if reason is not None:
            decisions.append(
                SourceVerificationDecision(
                    candidate_id=candidate.candidate_id,
                    requested_url=candidate.requested_url,
                    accepted=False,
                    rejection_reason=reason,
                )
            )
            continue

        url = candidate.final_url or candidate.requested_url
        canonical = canonicalize_url(url)
        fingerprint = SourceFingerprint.for_url(canonical, candidate.content_hash)
        known = by_version.get(fingerprint.version_key)
        if known is None:
            source_id, display_id = new_source_id(), f"SRC-{len(snapshots) + 1:03d}"
            by_version[fingerprint.version_key] = (source_id, display_id)
            edition, edition_source, currency = assess_currency(
                candidate.page_kind, candidate.declared_edition, candidate.title, target_edition
            )
            snapshots.append(
                OfficialSourceSnapshot(
                    source_id=source_id,
                    display_id=display_id,
                    candidate_id=candidate.candidate_id,
                    url=url,
                    canonical_url=canonical,
                    domain=official_domain(url),
                    title=candidate.title,
                    retrieved_at=candidate.retrieved_at,
                    published_at=candidate.published_at,
                    effective_at=candidate.effective_at,
                    page_kind=candidate.page_kind,
                    competition_edition=edition,
                    edition_source=edition_source,
                    currency=currency,
                    assessed_against_edition=target_edition,
                    content_hash=candidate.content_hash or "",
                    fingerprint=fingerprint,
                    captured_text=candidate.captured_text or "",
                )
            )
        else:
            source_id, display_id = known
        decisions.append(
            SourceVerificationDecision(
                candidate_id=candidate.candidate_id,
                requested_url=candidate.requested_url,
                accepted=True,
                source_id=source_id,
                display_id=display_id,
            )
        )

    return decisions, snapshots, [s.to_source_record() for s in snapshots]


def same_requirements_version(a: OfficialSourceSnapshot, b: OfficialSourceSnapshot) -> bool:
    """Same URL and same content. Same URL with changed content is a new version."""
    return a.fingerprint.same_content_version(b.fingerprint)


def same_logical_source(a: OfficialSourceSnapshot, b: OfficialSourceSnapshot) -> bool:
    """Same canonical URL, whatever the captured content was."""
    return a.fingerprint.same_logical_source(b.fingerprint)
