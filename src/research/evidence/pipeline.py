"""Candidate -> verified evidence, and the coverage that describes the pass.

The order of checks here is the order in which a candidate can fail, and each
failure has its own named reason so the ledger says what went wrong rather than
that something did:

    the referenced content exists      -> CONTENT_NOT_FOUND / INVALID_SOURCE_REFERENCE
    the excerpt is a usable length     -> EXCERPT_TOO_SHORT / EXCERPT_TOO_LONG
    the excerpt exists in the snapshot -> EXCERPT_NOT_FOUND / AMBIGUOUS_SPAN
    the numbers survive re-checking    -> INVALID_NUMERIC_OBSERVATION / INVALID_UNIT_FIDELITY

Length is checked against the **verified** excerpt, not the model's string: the
snapshot's own text is the authority on how long the evidence actually is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.research.evidence.verification import (
    check_excerpt_length,
    resolve_span,
    verify_numeric_observations,
)
from src.schemas.academic import AcademicSourceType
from src.schemas.evidence_extraction import (
    CONTENT_KIND_TO_SCOPE,
    EVIDENCE_VERIFIER_VERSION,
    MAX_EVIDENCE_EXCERPT_CHARS,
    MIN_EVIDENCE_EXCERPT_CHARS,
    EvidenceCandidate,
    EvidenceContentObservation,
    EvidenceExtractionCoverage,
    EvidenceExtractionStatus,
    EvidenceRejectionReason,
    EvidenceScope,
    EvidenceVerificationResult,
    ExtractedEvidence,
    IneligibleSource,
    RejectedEvidenceCandidate,
    SourceContentSnapshot,
)


@dataclass
class VerificationOutcome:
    """Everything the verification pass decided."""

    results: list[EvidenceVerificationResult] = field(default_factory=list)
    evidence: list[ExtractedEvidence] = field(default_factory=list)
    rejected: list[RejectedEvidenceCandidate] = field(default_factory=list)


def _reject(
    candidate: EvidenceCandidate,
    reason: EvidenceRejectionReason,
    summary: str = "",
) -> tuple[EvidenceVerificationResult, RejectedEvidenceCandidate]:
    return (
        EvidenceVerificationResult(
            candidate_id=candidate.candidate_id,
            accepted=False,
            issues=[reason],
            verifier_version=EVIDENCE_VERIFIER_VERSION,
        ),
        RejectedEvidenceCandidate(
            candidate_id=candidate.candidate_id,
            source_id=candidate.source_id,
            content_id=candidate.content_id,
            reason=reason,
            safe_summary=""
            if reason is EvidenceRejectionReason.PII_VIOLATION
            else summary[:200],
        ),
    )


def _observation(snapshot: SourceContentSnapshot) -> EvidenceContentObservation:
    return EvidenceContentObservation(
        content_id=snapshot.content_id,
        provider=snapshot.provider,
        provider_record_id=snapshot.provider_record_id,
        provider_url=snapshot.provider_url,
        content_hash=snapshot.content_hash,
        content_kind=snapshot.content_kind,
        retrieved_at=snapshot.retrieved_at,
    )


def verify_candidate(
    candidate: EvidenceCandidate,
    snapshots: dict[UUID, SourceContentSnapshot],
    *,
    research_run_id: UUID,
    extraction_run_id: UUID,
    min_chars: int = MIN_EVIDENCE_EXCERPT_CHARS,
    max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS,
) -> tuple[
    EvidenceVerificationResult,
    ExtractedEvidence | None,
    RejectedEvidenceCandidate | None,
]:
    """Decide one candidate. The whole trust boundary of Phase 2C, per item."""
    snapshot = snapshots.get(candidate.content_id)
    if snapshot is None:
        result, rejection = _reject(
            candidate,
            EvidenceRejectionReason.CONTENT_NOT_FOUND,
            "candidate references a content snapshot that does not exist",
        )
        return result, None, rejection

    if snapshot.source_id != candidate.source_id:
        result, rejection = _reject(
            candidate,
            EvidenceRejectionReason.INVALID_SOURCE_REFERENCE,
            "candidate source does not own the referenced content",
        )
        return result, None, rejection

    span = resolve_span(snapshot, candidate.verbatim_excerpt, candidate.claimed_start)
    if not span.resolved:
        result, rejection = _reject(
            candidate,
            span.reason or EvidenceRejectionReason.EXCERPT_NOT_FOUND,
            "the excerpt could not be uniquely located in the snapshot",
        )
        return result, None, rejection

    length_issue = check_excerpt_length(
        span.excerpt or "", minimum=min_chars, maximum=max_chars
    )
    if length_issue is not None:
        result, rejection = _reject(
            candidate, length_issue, "verified excerpt is outside the configured bounds"
        )
        return result, None, rejection

    numeric = verify_numeric_observations(
        candidate.numeric_observations, span.excerpt or ""
    )
    if not numeric.ok:
        result, rejection = _reject(
            candidate,
            numeric.reason or EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION,
            "a stated number or unit does not appear in the verified excerpt",
        )
        return result, None, rejection

    result = EvidenceVerificationResult(
        candidate_id=candidate.candidate_id,
        accepted=True,
        verified_source_id=snapshot.source_id,
        verified_content_id=snapshot.content_id,
        verified_start=span.start,
        verified_end=span.end,
        verified_excerpt=span.excerpt,
        match_method=span.method,
        verifier_version=EVIDENCE_VERIFIER_VERSION,
    )
    evidence = ExtractedEvidence(
        research_run_id=research_run_id,
        extraction_run_id=extraction_run_id,
        source_id=snapshot.source_id,
        content_id=snapshot.content_id,
        content_hash=snapshot.content_hash,
        content_kind=snapshot.content_kind,
        evidence_scope=CONTENT_KIND_TO_SCOPE[snapshot.content_kind],
        evidence_type=candidate.evidence_type,
        # Sliced from the snapshot, never taken from the candidate (ADR-011).
        excerpt=snapshot.text[span.start : span.end],
        verified_start=span.start,
        verified_end=span.end,
        match_method=span.method,
        numeric_observations=numeric.accepted,
        candidate_interpretation=candidate.candidate_interpretation,
        section_hint=candidate.section_hint or snapshot.section_label,
        page_hint=candidate.page_hint or snapshot.page_start,
        query_purpose=candidate.query_purpose,
        observations=[_observation(snapshot)],
        publication_year=snapshot.publication_year,
        source_type=snapshot.source_type,
        is_retracted=snapshot.is_retracted,
        peer_review_status=snapshot.peer_review_status,
        extraction_method=candidate.extraction_method,
        extractor_version=candidate.extractor_version,
        verifier_version=EVIDENCE_VERIFIER_VERSION,
        model_name=candidate.model_name,
    )
    return result, evidence, None


def verify_candidates(
    candidates: list[EvidenceCandidate],
    snapshots: list[SourceContentSnapshot],
    *,
    research_run_id: UUID,
    extraction_run_id: UUID,
    min_chars: int = MIN_EVIDENCE_EXCERPT_CHARS,
    max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS,
) -> VerificationOutcome:
    """Verify every candidate independently. One rejection affects no other."""
    index = {snapshot.content_id: snapshot for snapshot in snapshots}
    outcome = VerificationOutcome()

    for candidate in candidates:
        result, evidence, rejection = verify_candidate(
            candidate,
            index,
            research_run_id=research_run_id,
            extraction_run_id=extraction_run_id,
            min_chars=min_chars,
            max_chars=max_chars,
        )
        outcome.results.append(result)
        if evidence is not None:
            outcome.evidence.append(evidence)
        if rejection is not None:
            outcome.rejected.append(rejection)

    return outcome


# ---------------------------------------------------------------------------
# Coverage and status
# ---------------------------------------------------------------------------


def build_coverage(
    *,
    verified_sources_total: int,
    snapshots: list[SourceContentSnapshot],
    ineligible: list[IneligibleSource],
    extraction_attempts: int,
    candidates: list[EvidenceCandidate],
    evidence: list[ExtractedEvidence],
    rejected: list[RejectedEvidenceCandidate],
    model_failures: int,
) -> EvidenceExtractionCoverage:
    """Operational counters only. Says nothing about project or source quality."""
    verification_failures = sum(
        1
        for entry in rejected
        if entry.reason is not EvidenceRejectionReason.DUPLICATE_EVIDENCE
    )
    return EvidenceExtractionCoverage(
        verified_sources_total=verified_sources_total,
        sources_with_eligible_content=len({s.source_id for s in snapshots}),
        sources_without_eligible_content=len({s.source_id for s in ineligible}),
        content_snapshots_total=len(snapshots),
        extraction_attempts=extraction_attempts,
        candidates_total=len(candidates),
        accepted_evidence_total=len(evidence),
        rejected_candidates_total=len(rejected),
        abstract_evidence_count=sum(
            1 for e in evidence if e.evidence_scope is EvidenceScope.ABSTRACT_ONLY
        ),
        partial_text_evidence_count=sum(
            1 for e in evidence if e.evidence_scope is EvidenceScope.PARTIAL_TEXT
        ),
        full_text_evidence_count=sum(
            1 for e in evidence if e.evidence_scope is EvidenceScope.FULL_TEXT
        ),
        retracted_source_evidence_count=sum(
            1 for e in evidence if e.is_retracted is True
        ),
        preprint_evidence_count=sum(
            1 for e in evidence if e.source_type is AcademicSourceType.PREPRINT
        ),
        model_failures=model_failures,
        verification_failures=verification_failures,
    )


def decide_status(
    coverage: EvidenceExtractionCoverage, *, provider_available: bool
) -> EvidenceExtractionStatus:
    """The run verdict.

    ``INSUFFICIENT_CONTENT`` is the honest answer when verified sources existed
    but none carried extractable text -- a research finding about coverage, not
    a crash (§28). ``PARTIAL`` is the honest answer when some sources produced
    evidence and others failed, because a mixed outcome is mixed (§53).
    """
    if not provider_available:
        return EvidenceExtractionStatus.FAILED
    if coverage.content_snapshots_total == 0:
        return EvidenceExtractionStatus.INSUFFICIENT_CONTENT
    if coverage.model_failures and not coverage.candidates_total:
        # Nobody could be asked successfully. The only genuine outage.
        return EvidenceExtractionStatus.FAILED
    if coverage.model_failures or coverage.verification_failures:
        return EvidenceExtractionStatus.PARTIAL
    # Zero evidence from a clean pass is a finding about the literature, not a
    # failure: the extractor ran and the content held nothing extractable.
    return EvidenceExtractionStatus.COMPLETED


__all__ = [
    "VerificationOutcome",
    "build_coverage",
    "decide_status",
    "verify_candidate",
    "verify_candidates",
]
