"""Deterministic academic source verification.

What Phase 2B verifies is *source identity and metadata consistency*:

    the record has a well-formed, normalized strong identifier
    its canonical URL, if any, is a real http(s) URL
    it is traceable to a research run and a planned query
    it carries no student identity

What Phase 2B does **not** verify is anything scientific. Normalizing a DOI does
not make a paper sound, relevant or true; a verified academic source is a
verified *bibliographic record* and nothing more (ADR-010).

A record that fails goes to the rejection ledger with a named reason. Nothing is
repaired, guessed or dropped silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.research.academic.identifiers import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_pmid,
    normalize_semantic_scholar_id,
    normalize_url,
)
from src.research.academic.normalization import rejection
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext, contains_pii
from src.schemas.academic import (
    AcademicCandidateDecision,
    AcademicRejectionReason,
    AcademicRejectionStage,
    AcademicSearchQuery,
    AcademicSourceCandidate,
    RejectedAcademicCandidate,
)

ACADEMIC_VERIFICATION_VERSION = "ACADEMIC-VERIFICATION-V1"

_IDENTIFIER_CHECKS = (
    ("doi", normalize_doi, AcademicRejectionReason.INVALID_DOI),
    ("pmid", normalize_pmid, AcademicRejectionReason.INVALID_PMID),
    ("openalex_id", normalize_openalex_id, AcademicRejectionReason.INVALID_OPENALEX_ID),
    (
        "semantic_scholar_id",
        normalize_semantic_scholar_id,
        AcademicRejectionReason.INVALID_SEMANTIC_SCHOLAR_ID,
    ),
    ("arxiv_id", normalize_arxiv_id, AcademicRejectionReason.INVALID_ARXIV_ID),
)


@dataclass
class VerificationOutcome:
    """Accepted candidates, plus the audit trail for everything refused."""

    accepted: list[AcademicSourceCandidate] = field(default_factory=list)
    rejected: list[RejectedAcademicCandidate] = field(default_factory=list)
    decisions: list[AcademicCandidateDecision] = field(default_factory=list)


def check_candidate(
    candidate: AcademicSourceCandidate,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> AcademicRejectionReason | None:
    """The first rule this candidate breaks, or ``None`` when it is verifiable."""
    for name, normalizer, reason in _IDENTIFIER_CHECKS:
        value = getattr(candidate.identifiers, name)
        if value is None:
            continue
        # Idempotence: a stored identifier must already be its own normal form,
        # so nothing further down can be comparing two spellings of one work.
        if normalizer(value).value != value:
            return reason

    if candidate.canonical_url is not None:
        url = normalize_url(candidate.canonical_url)
        if url.value != candidate.canonical_url:
            return AcademicRejectionReason.INVALID_URL

    if candidate.identity is None:
        return AcademicRejectionReason.MISSING_IDENTIFIER

    # Defence in depth. Student identity never reaches a provider, so a provider
    # cannot echo it back -- and if one ever did, it stops here rather than
    # being stored.
    texts = [candidate.title, candidate.abstract or "", candidate.venue or "", *candidate.authors]
    if any(contains_pii(text, privacy) for text in texts if text):
        return AcademicRejectionReason.PII_DETECTED

    return None


def verify_academic_candidates(
    candidates: list[AcademicSourceCandidate],
    queries: dict[str, AcademicSearchQuery] | None = None,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> VerificationOutcome:
    """Verify every candidate independently.

    One unverifiable record never invalidates the rest: verification is per
    candidate, exactly as normalization is per provider record.
    """
    queries = queries or {}
    outcome = VerificationOutcome()
    for candidate in candidates:
        reason = check_candidate(candidate, privacy)
        if reason is None:
            outcome.accepted.append(candidate)
            continue
        query = queries.get(str(candidate.query_id))
        if query is not None:
            outcome.rejected.append(
                rejection(
                    query,
                    reason,
                    stage=AcademicRejectionStage.VERIFICATION,
                    record_id=candidate.provider_record_id,
                    summary=candidate.title,
                )
            )
        else:
            outcome.rejected.append(
                RejectedAcademicCandidate(
                    provider=candidate.provider,
                    query_id=candidate.query_id,
                    stage=AcademicRejectionStage.VERIFICATION,
                    reason=reason,
                    provider_record_identifier=candidate.provider_record_id,
                )
            )
        outcome.decisions.append(
            AcademicCandidateDecision(
                candidate_id=candidate.candidate_id,
                provider=candidate.provider,
                query_id=candidate.query_id,
                accepted=False,
                rejection_reason=reason,
            )
        )
    return outcome


__all__ = [
    "ACADEMIC_VERIFICATION_VERSION",
    "VerificationOutcome",
    "check_candidate",
    "verify_academic_candidates",
]
