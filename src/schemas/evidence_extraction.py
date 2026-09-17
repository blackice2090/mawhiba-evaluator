"""Trusted evidence extraction contracts -- Phase 2C (ADR-011, ADR-012, ADR-013).

The trust progression continues where Phase 2B stopped:

    LogicalAcademicSource     a verified bibliographic record (Phase 2B)
    SourceContentSnapshot     actual source text, provider-attributed, hashed
    EvidenceCandidate         what a model proposed. UNTRUSTED
    === deterministic verification boundary ===
    ExtractedEvidence         an exact span proven to exist in the snapshot

Three things this module refuses to let happen.

**A paraphrase can never be evidence** (ADR-011). The stored excerpt is always a
substring of the snapshot text, sliced by code at verified offsets, so
"verbatim" holds by construction rather than by trust. A model's own wording
survives only as ``candidate_interpretation``, explicitly advisory.

**Evidence cannot support a claim** (ADR-012). There is no ``support_direction``,
no ``strength``, no ``claim_id`` anywhere in these types. Phase 2C could not
express "this supports claim C-001" even if a later edit tried to -- the field
does not exist, which is a stronger guarantee than leaving one unset.

**Abstract evidence stays abstract evidence** (ADR-013). ``content_kind`` and
``evidence_scope`` travel with every record, so nothing downstream can mistake a
sentence from an abstract for full-text-verified evidence.

These records live on the ``ResearchRun``, never in ``ProjectState``. See the
ownership note on ``ExtractedEvidence``.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.academic import AcademicProvider, AcademicSourceType
from src.schemas.common import (
    CANONICAL_SOURCE_ID_PATTERN,
    MawhibaModel,
    QueryPurpose,
    UtcDatetime,
    utc_now,
)
from src.schemas.source import PeerReviewStatus

EVIDENCE_EXTRACTION_CONTRACT_VERSION = "EVIDENCE-EXTRACTION-CONTRACT-V1"
CONTENT_SNAPSHOT_VERSION = "CONTENT-SNAPSHOT-V1"
EVIDENCE_EXTRACTOR_VERSION = "EVIDENCE-EXTRACTOR-V1"
EVIDENCE_VERIFIER_VERSION = "EVIDENCE-VERIFIER-V2"
EVIDENCE_CHUNKER_VERSION = "EVIDENCE-CHUNKER-V1"

SHA256_PATTERN = r"^[0-9a-f]{64}$"

MIN_EVIDENCE_EXCERPT_CHARS = 25
MAX_EVIDENCE_EXCERPT_CHARS = 1200
"""Excerpt bounds. A three-word fragment carries no verifiable meaning, and an
unbounded passage is quotation rather than evidence. Both are configurable."""


def content_hash(text: str) -> str:
    """SHA-256 of the snapshot text, exactly as stored.

    Deliberately hashes the raw text with no normalization: the hash answers
    "is this the same bytes we verified against?", and folding whitespace first
    would let two different snapshots share a hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


class ContentKind(StrEnum):
    """What kind of source text a snapshot holds.

    ``METADATA_ONLY`` is a state, never a snapshot: it records that a verified
    source had a title, authors and a venue but no actual content, so nothing
    could be extracted from it. A snapshot of that kind cannot be constructed.
    """

    ABSTRACT = "ABSTRACT"
    PARTIAL_TEXT = "PARTIAL_TEXT"
    FULL_TEXT = "FULL_TEXT"
    METADATA_ONLY = "METADATA_ONLY"


EXTRACTABLE_CONTENT_KINDS: frozenset[ContentKind] = frozenset(
    {ContentKind.ABSTRACT, ContentKind.PARTIAL_TEXT, ContentKind.FULL_TEXT}
)
"""The kinds evidence may come from. ``METADATA_ONLY`` is absent by design."""


class EvidenceScope(StrEnum):
    """How much of the source stands behind an evidence item.

    This is a usability ceiling, not a strength rating. Phase 2C assigns no
    evidentiary weight; a later phase decides what an abstract-only finding is
    worth.
    """

    ABSTRACT_ONLY = "ABSTRACT_ONLY"
    PARTIAL_TEXT = "PARTIAL_TEXT"
    FULL_TEXT = "FULL_TEXT"


CONTENT_KIND_TO_SCOPE: dict[ContentKind, EvidenceScope] = {
    ContentKind.ABSTRACT: EvidenceScope.ABSTRACT_ONLY,
    ContentKind.PARTIAL_TEXT: EvidenceScope.PARTIAL_TEXT,
    ContentKind.FULL_TEXT: EvidenceScope.FULL_TEXT,
}


class SourceContentSnapshot(MawhibaModel):
    """A hashed, provider-attributed capture of real source text.

    The provider attribution is not decoration. An abstract merged across
    providers has no single origin, so evidence could not be traced back to who
    supplied the words; snapshots are therefore built per provider observation
    and only ever deduplicated when the text is byte-identical (§7).
    """

    content_id: UUID = Field(default_factory=uuid4)
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    research_run_id: UUID
    content_kind: ContentKind
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=SHA256_PATTERN)
    content_version: str = CONTENT_SNAPSHOT_VERSION

    provider: AcademicProvider
    provider_record_id: str | None = None
    provider_url: str | None = None
    canonical_url: str | None = None
    retrieved_at: UtcDatetime

    # Source integrity, carried so evidence never loses it (§9).
    publication_year: int | None = None
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    is_retracted: bool | None = None
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN

    section_label: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _snapshot_is_extractable_and_hashed(self) -> SourceContentSnapshot:
        if self.content_kind not in EXTRACTABLE_CONTENT_KINDS:
            raise ValueError(
                f"{self.content_kind.value} is not extractable content; a snapshot "
                "exists only for text evidence can be verified against"
            )
        if self.content_hash != content_hash(self.text):
            raise ValueError("content_hash does not match the snapshot text")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end cannot precede page_start")
        return self

    @property
    def scope(self) -> EvidenceScope:
        return CONTENT_KIND_TO_SCOPE[self.content_kind]


class IneligibleContentReason(StrEnum):
    """Why a verified source produced no snapshot. Not a failure."""

    NO_ABSTRACT = "NO_ABSTRACT"
    METADATA_ONLY = "METADATA_ONLY"
    CONTENT_TOO_SHORT = "CONTENT_TOO_SHORT"
    PROVIDER_SYNTHESIS_ONLY = "PROVIDER_SYNTHESIS_ONLY"


class IneligibleSource(MawhibaModel):
    """A verified source that carried no extractable content."""

    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    reason: IneligibleContentReason
    note: str | None = None


# ---------------------------------------------------------------------------
# Evidence vocabulary
# ---------------------------------------------------------------------------


class ExtractedEvidenceType(StrEnum):
    """What kind of statement an excerpt makes.

    Distinct from the Phase 0 ``EvidenceType``, which mixes in claim-relational
    ideas. These describe the excerpt on its own terms, because Phase 2C has no
    claim to relate it to. ``OTHER`` is always preferable to overclassification.
    """

    PROBLEM_EVIDENCE = "PROBLEM_EVIDENCE"
    EXISTING_SOLUTION = "EXISTING_SOLUTION"
    METHOD = "METHOD"
    TECHNICAL_MECHANISM = "TECHNICAL_MECHANISM"
    EXPERIMENTAL_RESULT = "EXPERIMENTAL_RESULT"
    BENCHMARK_RESULT = "BENCHMARK_RESULT"
    LIMITATION = "LIMITATION"
    FAILURE_MODE = "FAILURE_MODE"
    COMPARISON = "COMPARISON"
    DATASET_DESCRIPTION = "DATASET_DESCRIPTION"
    SAMPLE_OR_POPULATION = "SAMPLE_OR_POPULATION"
    PRIOR_WORK_FEATURE = "PRIOR_WORK_FEATURE"
    SAFETY_FINDING = "SAFETY_FINDING"
    OTHER = "OTHER"


class ComparisonOperator(StrEnum):
    EQUALS = "EQUALS"
    APPROXIMATELY = "APPROXIMATELY"
    GREATER_THAN = "GREATER_THAN"
    GREATER_OR_EQUAL = "GREATER_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_OR_EQUAL = "LESS_OR_EQUAL"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


class NumericObservation(MawhibaModel):
    """A number the excerpt actually states.

    ``raw_text`` is the anchor: verification requires it to appear in the
    verified excerpt, which is what stops 92.3% from being recorded as 93.2%.
    Units are preserved exactly as written and never converted (§19).
    """

    raw_text: str = Field(min_length=1)
    value: float | None = None
    unit: str | None = None
    metric_name: str | None = None
    comparison_operator: ComparisonOperator = ComparisonOperator.UNKNOWN
    uncertainty: str | None = Field(
        default=None, description="Confidence interval or error, verbatim. Never derived."
    )
    sample_size: int | None = Field(
        default=None, ge=0, description="Only when the excerpt states it explicitly."
    )


class ExtractionMethod(StrEnum):
    LLM_STRUCTURED_EXTRACTION = "LLM_STRUCTURED_EXTRACTION"
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"


# ---------------------------------------------------------------------------
# Candidates -- untrusted
# ---------------------------------------------------------------------------


class EvidenceCandidate(MawhibaModel):
    """What a model proposed. Untrusted until deterministic verification.

    ``claimed_start`` and ``claimed_end`` are recorded for audit and are never
    used to define a span. A model miscounts offsets routinely, and a wrong
    offset that looked authoritative would be provenance theatre.
    """

    candidate_id: UUID = Field(default_factory=uuid4)
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    content_id: UUID
    evidence_type: ExtractedEvidenceType = ExtractedEvidenceType.OTHER
    verbatim_excerpt: str = ""
    claimed_start: int | None = Field(default=None, ge=0)
    claimed_end: int | None = Field(default=None, ge=0)
    section_hint: str | None = None
    page_hint: int | None = Field(default=None, ge=1)
    numeric_observations: list[NumericObservation] = Field(default_factory=list)
    candidate_interpretation: str | None = Field(
        default=None,
        description="The model's own wording. Advisory metadata only: it never "
        "replaces the excerpt and never becomes a claim (§22).",
    )
    extraction_method: ExtractionMethod = ExtractionMethod.LLM_STRUCTURED_EXTRACTION
    extractor_version: str = EVIDENCE_EXTRACTOR_VERSION
    model_name: str | None = None
    query_purpose: QueryPurpose | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)


class EvidenceRejectionReason(StrEnum):
    """Why a candidate did not become evidence. Stable and auditable."""

    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    CONTENT_NOT_FOUND = "CONTENT_NOT_FOUND"
    CONTENT_NOT_ELIGIBLE = "CONTENT_NOT_ELIGIBLE"
    EXCERPT_NOT_FOUND = "EXCERPT_NOT_FOUND"
    AMBIGUOUS_SPAN = "AMBIGUOUS_SPAN"
    EXCERPT_TOO_SHORT = "EXCERPT_TOO_SHORT"
    EXCERPT_TOO_LONG = "EXCERPT_TOO_LONG"
    INVALID_NUMERIC_OBSERVATION = "INVALID_NUMERIC_OBSERVATION"
    INVALID_UNIT_FIDELITY = "INVALID_UNIT_FIDELITY"
    INVALID_SOURCE_REFERENCE = "INVALID_SOURCE_REFERENCE"
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    MODEL_SCHEMA_ERROR = "MODEL_SCHEMA_ERROR"
    PII_VIOLATION = "PII_VIOLATION"
    OTHER = "OTHER"


DETERMINISTIC_REJECTION_REASONS: frozenset[EvidenceRejectionReason] = frozenset(
    {
        EvidenceRejectionReason.EXCERPT_NOT_FOUND,
        EvidenceRejectionReason.AMBIGUOUS_SPAN,
        EvidenceRejectionReason.INVALID_NUMERIC_OBSERVATION,
        EvidenceRejectionReason.INVALID_UNIT_FIDELITY,
    }
)
"""Provenance verdicts a retry cannot change. Never retried (§54)."""

MAX_REJECTION_SUMMARY_CHARS = 200


class RejectedEvidenceCandidate(MawhibaModel):
    """Audit record for a refused candidate. Carries no secrets and no PII."""

    candidate_id: UUID
    source_id: str | None = None
    content_id: UUID | None = None
    reason: EvidenceRejectionReason
    safe_summary: str = Field(default="", max_length=MAX_REJECTION_SUMMARY_CHARS)
    verifier_version: str = EVIDENCE_VERIFIER_VERSION

    @model_validator(mode="after")
    def _pii_rejections_keep_no_text(self) -> RejectedEvidenceCandidate:
        if self.reason is EvidenceRejectionReason.PII_VIOLATION and self.safe_summary:
            raise ValueError("a PII rejection must not retain the offending text")
        return self


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class SpanMatchMethod(StrEnum):
    """How the excerpt was located. Recorded so a reader can tell them apart.

    Every method yields exact offsets into the snapshot, and the stored excerpt
    is always sliced from the snapshot at those offsets. The distinction is how
    the *search* succeeded, not how faithful the result is.
    """

    EXACT = "EXACT"
    NORMALIZED_UNICODE = "NORMALIZED_UNICODE"
    NORMALIZED_WHITESPACE = "NORMALIZED_WHITESPACE"


class EvidenceVerificationResult(MawhibaModel):
    """The deterministic verdict on one candidate, with its reasons."""

    candidate_id: UUID
    accepted: bool
    verified_source_id: str | None = Field(
        default=None, pattern=CANONICAL_SOURCE_ID_PATTERN
    )
    verified_content_id: UUID | None = None
    verified_start: int | None = Field(default=None, ge=0)
    verified_end: int | None = Field(default=None, ge=0)
    verified_excerpt: str | None = None
    match_method: SpanMatchMethod | None = None
    issues: list[EvidenceRejectionReason] = Field(default_factory=list)
    verifier_version: str = EVIDENCE_VERIFIER_VERSION

    @model_validator(mode="after")
    def _consistent(self) -> EvidenceVerificationResult:
        if self.accepted:
            if self.issues:
                raise ValueError("an accepted candidate cannot carry issues")
            missing = [
                name
                for name in (
                    "verified_source_id",
                    "verified_content_id",
                    "verified_start",
                    "verified_end",
                    "verified_excerpt",
                    "match_method",
                )
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"an accepted candidate must record {missing}")
            if self.verified_end <= self.verified_start:
                raise ValueError("verified_end must be after verified_start")
            if len(self.verified_excerpt) != self.verified_end - self.verified_start:
                raise ValueError("verified excerpt length must match the verified span")
        elif not self.issues:
            raise ValueError("a rejected candidate must state at least one issue")
        return self


# ---------------------------------------------------------------------------
# Verified evidence
# ---------------------------------------------------------------------------


class EvidenceContentObservation(MawhibaModel):
    """Which provider's content snapshot carried this exact text.

    The same ADR-009 shape as a provider observation on a logical source: when
    two providers supply byte-identical abstract text, the evidence collapses to
    one item and every observation survives, so "who gave us these words?" stays
    answerable.
    """

    content_id: UUID
    provider: AcademicProvider
    provider_record_id: str | None = None
    provider_url: str | None = None
    content_hash: str = Field(pattern=SHA256_PATTERN)
    content_kind: ContentKind
    retrieved_at: UtcDatetime


class ExtractedEvidence(MawhibaModel):
    """An exact span proven to exist in a versioned source content snapshot.

    **Ownership.** This lives on the ``ResearchRun``, not in
    ``ProjectState.evidence``. The canonical ``EvidenceRecord`` requires its
    ``source_id`` to resolve inside ``ProjectState.sources``, and Phase 2B
    deliberately keeps verified academic sources on the research run instead
    (ADR-010). Writing here would therefore have meant either breaking
    referential integrity or moving source ownership -- both forbidden. The
    promotion boundary into canonical evidence is a later reviewed phase.

    **What is deliberately absent.** No ``support_direction``, no ``strength``,
    no ``claim_id``. Phase 2C cannot express a claim relationship, which is a
    stronger guarantee than leaving such a field unset (ADR-012).
    """

    evidence_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    extraction_run_id: UUID
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)

    content_id: UUID = Field(description="The snapshot the verified span indexes into.")
    content_hash: str = Field(pattern=SHA256_PATTERN)
    content_kind: ContentKind
    evidence_scope: EvidenceScope

    evidence_type: ExtractedEvidenceType
    excerpt: str = Field(
        min_length=1,
        description="Sliced from the snapshot at the verified offsets. Verbatim "
        "by construction, never the model's string (ADR-011).",
    )
    verified_start: int = Field(ge=0)
    verified_end: int = Field(ge=1)
    match_method: SpanMatchMethod

    numeric_observations: list[NumericObservation] = Field(default_factory=list)
    candidate_interpretation: str | None = Field(
        default=None, description="Advisory model wording. Never the evidence."
    )
    section_hint: str | None = None
    page_hint: int | None = Field(default=None, ge=1)
    query_purpose: QueryPurpose | None = None

    observations: list[EvidenceContentObservation] = Field(min_length=1)

    publication_year: int | None = None
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    is_retracted: bool | None = None
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN

    extraction_method: ExtractionMethod
    extractor_version: str = EVIDENCE_EXTRACTOR_VERSION
    verifier_version: str = EVIDENCE_VERIFIER_VERSION
    model_name: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _span_and_scope_hold(self) -> ExtractedEvidence:
        if self.verified_end <= self.verified_start:
            raise ValueError("verified_end must be after verified_start")
        if len(self.excerpt) != self.verified_end - self.verified_start:
            raise ValueError("excerpt length must match the verified span")
        if CONTENT_KIND_TO_SCOPE[self.content_kind] is not self.evidence_scope:
            raise ValueError(
                f"{self.content_kind.value} content cannot carry scope "
                f"{self.evidence_scope.value} (ADR-013)"
            )
        if not any(o.content_id == self.content_id for o in self.observations):
            raise ValueError("the span's content_id must be among the observations")
        if any(o.content_hash != self.content_hash for o in self.observations):
            raise ValueError(
                "every observation of one evidence item must share its content hash"
            )
        return self

    @property
    def logical_key(self) -> tuple[str, str, int, int, str]:
        """Evidence identity: source, exact content, exact span, type (§12)."""
        return (
            self.source_id,
            self.content_hash,
            self.verified_start,
            self.verified_end,
            self.evidence_type.value,
        )

    @property
    def providers(self) -> list[AcademicProvider]:
        seen = {o.provider for o in self.observations}
        return [p for p in AcademicProvider if p in seen]

    @property
    def is_abstract_scoped(self) -> bool:
        return self.evidence_scope is EvidenceScope.ABSTRACT_ONLY


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class EvidenceExtractionStatus(StrEnum):
    """Execution state. ``INSUFFICIENT_CONTENT`` is an outcome, not a crash."""

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INSUFFICIENT_CONTENT = "INSUFFICIENT_CONTENT"


TERMINAL_EXTRACTION_STATUSES: frozenset[EvidenceExtractionStatus] = frozenset(
    {
        EvidenceExtractionStatus.PARTIAL,
        EvidenceExtractionStatus.COMPLETED,
        EvidenceExtractionStatus.FAILED,
        EvidenceExtractionStatus.INSUFFICIENT_CONTENT,
    }
)


class EvidenceExtractionIssueCode(StrEnum):
    NO_ACADEMIC_RESULT = "NO_ACADEMIC_RESULT"
    NO_VERIFIED_SOURCES = "NO_VERIFIED_SOURCES"
    NO_ELIGIBLE_CONTENT = "NO_ELIGIBLE_CONTENT"
    EXTRACTION_PROVIDER_MISSING = "EXTRACTION_PROVIDER_MISSING"
    EXTRACTION_MODEL_FAILED = "EXTRACTION_MODEL_FAILED"


class EvidenceExtractionIssue(MawhibaModel):
    code: EvidenceExtractionIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_id: str | None = None


class EvidenceExtractionCoverage(MawhibaModel):
    """Operational counters. Describes execution, never project quality."""

    verified_sources_total: int = Field(default=0, ge=0)
    sources_with_eligible_content: int = Field(default=0, ge=0)
    sources_without_eligible_content: int = Field(default=0, ge=0)
    content_snapshots_total: int = Field(default=0, ge=0)
    extraction_attempts: int = Field(default=0, ge=0)
    candidates_total: int = Field(default=0, ge=0)
    accepted_evidence_total: int = Field(default=0, ge=0)
    rejected_candidates_total: int = Field(default=0, ge=0)
    abstract_evidence_count: int = Field(default=0, ge=0)
    partial_text_evidence_count: int = Field(default=0, ge=0)
    full_text_evidence_count: int = Field(default=0, ge=0)
    retracted_source_evidence_count: int = Field(default=0, ge=0)
    preprint_evidence_count: int = Field(default=0, ge=0)
    model_failures: int = Field(default=0, ge=0)
    verification_failures: int = Field(default=0, ge=0)


class EvidenceExtractionRun(MawhibaModel):
    """Everything one evidence-extraction pass produced, in one typed record."""

    evidence_extraction_run_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    status: EvidenceExtractionStatus = EvidenceExtractionStatus.NOT_STARTED

    contract_version: str = EVIDENCE_EXTRACTION_CONTRACT_VERSION
    content_snapshot_version: str = CONTENT_SNAPSHOT_VERSION
    extractor_prompt_version: str | None = None
    extractor_version: str = EVIDENCE_EXTRACTOR_VERSION
    verifier_version: str = EVIDENCE_VERIFIER_VERSION
    chunker_version: str = EVIDENCE_CHUNKER_VERSION
    dataset_version: str | None = None
    model_name: str | None = None
    provider_name: str | None = None

    content_snapshots: list[SourceContentSnapshot] = Field(default_factory=list)
    ineligible_sources: list[IneligibleSource] = Field(default_factory=list)
    candidates: list[EvidenceCandidate] = Field(default_factory=list)
    verification_results: list[EvidenceVerificationResult] = Field(default_factory=list)
    verified_evidence: list[ExtractedEvidence] = Field(default_factory=list)
    rejected_candidates: list[RejectedEvidenceCandidate] = Field(default_factory=list)
    coverage: EvidenceExtractionCoverage = Field(
        default_factory=EvidenceExtractionCoverage
    )
    errors: list[EvidenceExtractionIssue] = Field(default_factory=list)

    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> EvidenceExtractionRun:
        if any(s.research_run_id != self.research_run_id for s in self.content_snapshots):
            raise ValueError("a content snapshot belongs to a different research run")
        if any(e.research_run_id != self.research_run_id for e in self.verified_evidence):
            raise ValueError("an evidence item belongs to a different research run")
        if any(
            e.extraction_run_id != self.evidence_extraction_run_id
            for e in self.verified_evidence
        ):
            raise ValueError("an evidence item belongs to a different extraction run")

        evidence_ids = [e.evidence_id for e in self.verified_evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence ids must be unique")

        snapshot_ids = {s.content_id for s in self.content_snapshots}
        for evidence in self.verified_evidence:
            for observation in evidence.observations:
                if observation.content_id not in snapshot_ids:
                    raise ValueError(
                        f"evidence {evidence.evidence_id} references unknown content "
                        f"{observation.content_id}"
                    )

        if (
            self.status is EvidenceExtractionStatus.INSUFFICIENT_CONTENT
            and self.verified_evidence
        ):
            raise ValueError("INSUFFICIENT_CONTENT cannot carry verified evidence")
        if self.status is EvidenceExtractionStatus.NOT_STARTED and (
            self.candidates or self.verified_evidence
        ):
            raise ValueError("NOT_STARTED must not carry candidates or evidence")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_EXTRACTION_STATUSES

    def snapshots_for(self, source_id: str) -> list[SourceContentSnapshot]:
        return [s for s in self.content_snapshots if s.source_id == source_id]

    def evidence_for(self, source_id: str) -> list[ExtractedEvidence]:
        return [e for e in self.verified_evidence if e.source_id == source_id]


__all__ = [
    "CONTENT_KIND_TO_SCOPE",
    "CONTENT_SNAPSHOT_VERSION",
    "DETERMINISTIC_REJECTION_REASONS",
    "EVIDENCE_CHUNKER_VERSION",
    "EVIDENCE_EXTRACTION_CONTRACT_VERSION",
    "EVIDENCE_EXTRACTOR_VERSION",
    "EVIDENCE_VERIFIER_VERSION",
    "EXTRACTABLE_CONTENT_KINDS",
    "MAX_EVIDENCE_EXCERPT_CHARS",
    "MIN_EVIDENCE_EXCERPT_CHARS",
    "ComparisonOperator",
    "ContentKind",
    "EvidenceCandidate",
    "EvidenceContentObservation",
    "EvidenceExtractionCoverage",
    "EvidenceExtractionIssue",
    "EvidenceExtractionIssueCode",
    "EvidenceExtractionRun",
    "EvidenceExtractionStatus",
    "EvidenceRejectionReason",
    "EvidenceScope",
    "EvidenceVerificationResult",
    "ExtractedEvidence",
    "ExtractedEvidenceType",
    "ExtractionMethod",
    "IneligibleContentReason",
    "IneligibleSource",
    "NumericObservation",
    "RejectedEvidenceCandidate",
    "SourceContentSnapshot",
    "SpanMatchMethod",
    "content_hash",
]
