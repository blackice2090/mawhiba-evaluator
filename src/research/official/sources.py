"""Retrieval -> SourceCandidate -> verification -> OfficialSourceSnapshot / SourceRecord.

No function here creates an ``EvidenceRecord``. A candidate becomes a source only
after deterministic checks: successful retrieval, allowlisted requested and final
URLs, non-empty content, and a content hash that recomputes identically.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from src.intake.anchors import collapse_whitespace, normalize_line_endings, normalize_unicode
from src.research.official.allowlist import canonicalize_url, check_official_url, official_domain
from src.research.official.provider import OfficialWebProvider
from src.schemas.official import (
    OfficialRetrievalResult,
    OfficialSourceSnapshot,
    RetrievalStatus,
    SourceCandidate,
    SourceRejectionReason,
    SourceVerificationDecision,
)
from src.schemas.source import SourceRecord


def content_hash(text: str) -> str:
    """SHA-256 over normalized text (HASH_NORMALIZATION_VERSION).

    Transport noise (line endings, whitespace runs, NFC) does not change the hash;
    any change in wording does.
    """
    normalized = collapse_whitespace(normalize_unicode(normalize_line_endings(text)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def candidate_from_result(result: OfficialRetrievalResult, research_run_id: UUID) -> SourceCandidate:
    success = result.status is RetrievalStatus.SUCCESS
    return SourceCandidate(
        research_run_id=research_run_id,
        requested_url=result.requested_url,
        final_url=result.final_url,
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
    provider: OfficialWebProvider, seed_urls: list[str], research_run_id: UUID
) -> list[SourceCandidate]:
    """Retrieve every seed URL once. A provider fault becomes a failed candidate."""
    candidates: list[SourceCandidate] = []
    for url in dict.fromkeys(seed_urls):
        try:
            result = provider.retrieve(url)
        except Exception as exc:  # noqa: BLE001 -- a provider fault is a retrieval outcome
            result = OfficialRetrievalResult(
                status=RetrievalStatus.NETWORK_ERROR,
                requested_url=url,
                error=f"provider raised {type(exc).__name__}",
                provider=getattr(provider, "name", "unknown"),
            )
        candidates.append(candidate_from_result(result, research_run_id))
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
    candidates: list[SourceCandidate],
) -> tuple[list[SourceVerificationDecision], list[OfficialSourceSnapshot], list[SourceRecord]]:
    """Deterministic source verification. The same version is snapshotted once."""
    decisions: list[SourceVerificationDecision] = []
    snapshots: list[OfficialSourceSnapshot] = []
    by_version: dict[tuple[str, str], str] = {}

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
        version = (canonicalize_url(url), candidate.content_hash or "")
        source_id = by_version.get(version)
        if source_id is None:
            source_id = f"SRC-{len(snapshots) + 1:03d}"
            by_version[version] = source_id
            snapshots.append(
                OfficialSourceSnapshot(
                    source_id=source_id,
                    candidate_id=candidate.candidate_id,
                    url=url,
                    canonical_url=version[0],
                    domain=official_domain(url),
                    title=candidate.title,
                    retrieved_at=candidate.retrieved_at,
                    published_at=candidate.published_at,
                    effective_at=candidate.effective_at,
                    content_hash=version[1],
                    captured_text=candidate.captured_text or "",
                )
            )
        decisions.append(
            SourceVerificationDecision(
                candidate_id=candidate.candidate_id,
                requested_url=candidate.requested_url,
                accepted=True,
                source_id=source_id,
            )
        )

    return decisions, snapshots, [s.to_source_record() for s in snapshots]


def same_requirements_version(a: OfficialSourceSnapshot, b: OfficialSourceSnapshot) -> bool:
    """Same URL and same content. Same URL with changed content is a new version."""
    return a.version_key == b.version_key
