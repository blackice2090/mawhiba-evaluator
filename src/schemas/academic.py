"""Academic research connector contracts -- Phase 2B (ADR-008, ADR-009, ADR-010).

The trust progression is explicit in the types, exactly as the official branch
made it explicit in Phase 2A:

    provider JSON             untrusted, never read directly by anything
    AcademicSourceCandidate   ONE provider's observation of a work
    LogicalAcademicSource     ONE work, with EVERY provider observation kept
    SourceRecord              the Phase 0 source contract, VERIFIED_METADATA

Nothing here is an ``EvidenceRecord``, and nothing here supports a claim. A
normalized, deduplicated, metadata-verified paper is a *verified source*; what
it scientifically shows is a later phase (ADR-010).

Two further distinctions this module refuses to collapse:

* **logical source vs provider observation** (ADR-009). Deduplication produces
  one logical source and never discards which provider returned it, under which
  query, at which rank, with which citation count.
* **provider failure vs empty result**. A provider that worked and found nothing
  is not a provider that could not be asked.
"""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.common import (
    CANONICAL_SOURCE_ID_PATTERN,
    DISPLAY_ID_PATTERN,
    MawhibaModel,
    QueryPurpose,
    ResearchBranch,
    UnitInterval,
    UtcDatetime,
)
from src.schemas.source import (
    PeerReviewStatus,
    SourceFingerprint,
    SourceIdentifierKind,
    SourceProvider,
    SourceRecord,
    SourceTier,
    SourceType,
    VerificationStatus,
)

ACADEMIC_CONTRACT_VERSION = "ACADEMIC-CONTRACT-V1"
ACADEMIC_NORMALIZER_VERSION = "ACADEMIC-NORMALIZER-V1"
ACADEMIC_DEDUP_VERSION = "ACADEMIC-DEDUP-V1"

MIN_PUBLICATION_YEAR = 1400
MAX_PUBLICATION_YEAR = 2200

PUBLICATION_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
DOI_PATTERN = r"^10\.\d{4,9}/\S+$"
OPENALEX_ID_PATTERN = r"^w\d+$"
SEMANTIC_SCHOLAR_ID_PATTERN = r"^(?:[0-9a-f]{40}|corpusid:\d+)$"
PMID_PATTERN = r"^\d+$"
ARXIV_ID_PATTERN = r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})$"

MAX_SAFE_SUMMARY_LENGTH = 200
"""Rejected-candidate summaries are truncated: a ledger is an audit trail, not a
second copy of the provider response."""


class ProviderFacingModel(BaseModel):
    """Base for a provider response DTO. Untrusted input, never canonical state.

    ``extra="ignore"`` on purpose: an academic API adds fields without warning,
    and a connector that breaks on an unknown key is a connector that breaks in
    production. Ignoring is not trusting -- every field this project uses is
    declared, typed, and re-validated downstream.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class AcademicProvider(StrEnum):
    """The academic retrieval providers Phase 2B implements.

    A stable enum rather than free strings, so provenance, budgets, metrics and
    capability documentation all key off one vocabulary.
    """

    CONSENSUS = "CONSENSUS"
    OPENALEX = "OPENALEX"
    SEMANTIC_SCHOLAR = "SEMANTIC_SCHOLAR"


ACADEMIC_PROVIDER_ORDER: tuple[AcademicProvider, ...] = (
    AcademicProvider.CONSENSUS,
    AcademicProvider.OPENALEX,
    AcademicProvider.SEMANTIC_SCHOLAR,
)
"""Deterministic dispatch and tie-break order. Not a quality ranking."""

ACADEMIC_TO_SOURCE_PROVIDER: dict[AcademicProvider, SourceProvider] = {
    AcademicProvider.CONSENSUS: SourceProvider.CONSENSUS,
    AcademicProvider.OPENALEX: SourceProvider.OPENALEX,
    AcademicProvider.SEMANTIC_SCHOLAR: SourceProvider.SEMANTIC_SCHOLAR,
}


class AcademicSourceType(StrEnum):
    """Publication form, only where provider metadata states it.

    Never inferred from title wording: a paper called "A Review of ..." is not
    thereby a review article, and guessing would quietly change how much weight
    a later phase gives it.
    """

    JOURNAL_ARTICLE = "JOURNAL_ARTICLE"
    CONFERENCE_PAPER = "CONFERENCE_PAPER"
    REVIEW = "REVIEW"
    SYSTEMATIC_REVIEW = "SYSTEMATIC_REVIEW"
    META_ANALYSIS = "META_ANALYSIS"
    PREPRINT = "PREPRINT"
    BOOK_CHAPTER = "BOOK_CHAPTER"
    THESIS = "THESIS"
    DATASET = "DATASET"
    OTHER_ACADEMIC = "OTHER_ACADEMIC"
    UNKNOWN = "UNKNOWN"


PEER_REVIEWED_SOURCE_TYPES: frozenset[AcademicSourceType] = frozenset(
    {
        AcademicSourceType.JOURNAL_ARTICLE,
        AcademicSourceType.CONFERENCE_PAPER,
        AcademicSourceType.REVIEW,
        AcademicSourceType.SYSTEMATIC_REVIEW,
        AcademicSourceType.META_ANALYSIS,
    }
)
"""Forms whose publication route implies peer review. ``PREPRINT`` is the only
type that implies the opposite; everything else stays UNKNOWN."""

ACADEMIC_TO_SOURCE_TYPE: dict[AcademicSourceType, SourceType] = {
    AcademicSourceType.JOURNAL_ARTICLE: SourceType.ACADEMIC_PAPER,
    AcademicSourceType.CONFERENCE_PAPER: SourceType.ACADEMIC_PAPER,
    AcademicSourceType.REVIEW: SourceType.ACADEMIC_PAPER,
    AcademicSourceType.SYSTEMATIC_REVIEW: SourceType.SYSTEMATIC_REVIEW,
    AcademicSourceType.META_ANALYSIS: SourceType.SYSTEMATIC_REVIEW,
    AcademicSourceType.PREPRINT: SourceType.PREPRINT,
    AcademicSourceType.BOOK_CHAPTER: SourceType.OTHER,
    AcademicSourceType.THESIS: SourceType.OTHER,
    AcademicSourceType.DATASET: SourceType.DATASET,
    AcademicSourceType.OTHER_ACADEMIC: SourceType.OTHER,
    AcademicSourceType.UNKNOWN: SourceType.OTHER,
}


ACADEMIC_SEARCH_PURPOSES: frozenset[QueryPurpose] = frozenset(
    {
        QueryPurpose.PROBLEM,
        QueryPurpose.EXISTING_SOLUTIONS,
        QueryPurpose.TECHNOLOGY,
        QueryPurpose.RECENT_WORK,
        QueryPurpose.LIMITATIONS,
        QueryPurpose.BENCHMARK,
        QueryPurpose.REVIEW,
        QueryPurpose.ALTERNATIVES,
        QueryPurpose.FAILURE_MODES,
        QueryPurpose.PRIOR_ART,
    }
)
"""The only purposes that reach an academic connector.

``PATENT_FUNCTION``, ``PATENT_MECHANISM``, ``PRODUCT`` and ``OPEN_SOURCE``
belong to branches Phase 2B does not implement and are never routed here.
"""


class AcademicSearchStatus(StrEnum):
    """Outcome of ONE provider answering ONE query.

    ``EMPTY`` is deliberately not a failure: "worked, found nothing" and "could
    not be asked" lead to different research conclusions.
    """

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    TIMEOUT = "TIMEOUT"


SUCCESSFUL_SEARCH_STATUSES: frozenset[AcademicSearchStatus] = frozenset(
    {AcademicSearchStatus.SUCCESS, AcademicSearchStatus.PARTIAL}
)
"""Statuses that produced at least one canonical candidate."""

EXECUTED_SEARCH_STATUSES: frozenset[AcademicSearchStatus] = frozenset(
    {*SUCCESSFUL_SEARCH_STATUSES, AcademicSearchStatus.EMPTY}
)
"""Statuses where the provider actually answered."""


class AcademicBranchOutcome(StrEnum):
    """Aggregate verdict for the ACADEMIC branch (ADR-008).

    One provider failing never downgrades this past ``PARTIAL`` while another
    provider's results survive.
    """

    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class AcademicErrorKind(StrEnum):
    """Why one provider attempt failed. Retryability is a property of the kind."""

    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    UNEXPECTED = "UNEXPECTED"


RETRYABLE_ERROR_KINDS: frozenset[AcademicErrorKind] = frozenset(
    {
        AcademicErrorKind.TIMEOUT,
        AcademicErrorKind.CONNECTION_ERROR,
        AcademicErrorKind.RATE_LIMITED,
        AcademicErrorKind.SERVER_ERROR,
    }
)
"""Transport faults and explicit back-pressure. Everything else is a contract
problem that a second identical request cannot fix -- 403 included, because a
provider that documents it as transient would need its own reviewed decision."""

ERROR_KIND_TO_SEARCH_STATUS: dict[AcademicErrorKind, AcademicSearchStatus] = {
    AcademicErrorKind.TIMEOUT: AcademicSearchStatus.TIMEOUT,
    AcademicErrorKind.CONNECTION_ERROR: AcademicSearchStatus.PROVIDER_ERROR,
    AcademicErrorKind.RATE_LIMITED: AcademicSearchStatus.RATE_LIMITED,
    AcademicErrorKind.SERVER_ERROR: AcademicSearchStatus.PROVIDER_ERROR,
    AcademicErrorKind.AUTH_ERROR: AcademicSearchStatus.AUTH_ERROR,
    AcademicErrorKind.FORBIDDEN: AcademicSearchStatus.AUTH_ERROR,
    AcademicErrorKind.NOT_FOUND: AcademicSearchStatus.PROVIDER_ERROR,
    AcademicErrorKind.BAD_REQUEST: AcademicSearchStatus.PROVIDER_ERROR,
    AcademicErrorKind.INVALID_RESPONSE: AcademicSearchStatus.INVALID_RESPONSE,
    AcademicErrorKind.SCHEMA_INCOMPATIBLE: AcademicSearchStatus.INVALID_RESPONSE,
    AcademicErrorKind.UNEXPECTED: AcademicSearchStatus.PROVIDER_ERROR,
}


class AcademicQueryExclusionReason(StrEnum):
    """Why a planned query never reached a connector."""

    NOT_ACADEMIC_BRANCH = "NOT_ACADEMIC_BRANCH"
    QUERY_NOT_ACCEPTED = "QUERY_NOT_ACCEPTED"
    PURPOSE_NOT_ROUTED_TO_ACADEMIC = "PURPOSE_NOT_ROUTED_TO_ACADEMIC"
    EMPTY_QUERY = "EMPTY_QUERY"
    PII_DETECTED = "PII_DETECTED"
    DUPLICATE_QUERY = "DUPLICATE_QUERY"
    QUERY_BUDGET_EXCEEDED = "QUERY_BUDGET_EXCEEDED"


class AcademicRejectionReason(StrEnum):
    """Why one provider record did not become, or stay, a canonical candidate."""

    MALFORMED_RECORD = "MALFORMED_RECORD"
    MISSING_TITLE = "MISSING_TITLE"
    MISSING_IDENTIFIER = "MISSING_IDENTIFIER"
    INVALID_DOI = "INVALID_DOI"
    INVALID_OPENALEX_ID = "INVALID_OPENALEX_ID"
    INVALID_SEMANTIC_SCHOLAR_ID = "INVALID_SEMANTIC_SCHOLAR_ID"
    INVALID_PMID = "INVALID_PMID"
    INVALID_ARXIV_ID = "INVALID_ARXIV_ID"
    INVALID_PUBLICATION_YEAR = "INVALID_PUBLICATION_YEAR"
    INVALID_URL = "INVALID_URL"
    DUPLICATE_PROVIDER_RECORD = "DUPLICATE_PROVIDER_RECORD"
    PROVIDER_RESULT_LIMIT_EXCEEDED = "PROVIDER_RESULT_LIMIT_EXCEEDED"
    TOTAL_CANDIDATE_LIMIT_EXCEEDED = "TOTAL_CANDIDATE_LIMIT_EXCEEDED"
    PII_DETECTED = "PII_DETECTED"


BUDGET_REJECTION_REASONS: frozenset[AcademicRejectionReason] = frozenset(
    {
        AcademicRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED,
        AcademicRejectionReason.TOTAL_CANDIDATE_LIMIT_EXCEEDED,
    }
)
"""Budget truncation. Recorded, auditable, and explicitly not a provider failure."""


class AcademicRejectionStage(StrEnum):
    NORMALIZATION = "NORMALIZATION"
    BUDGET = "BUDGET"
    VERIFICATION = "VERIFICATION"


# ---------------------------------------------------------------------------
# Query input
# ---------------------------------------------------------------------------


class AcademicSearchQuery(MawhibaModel):
    """The only thing a connector may be asked to search for.

    Built exclusively from an ACCEPTED entry of the Phase 2A verified query plan,
    so every provider request stays answerable: which run, which planned query,
    which purpose, which provider, which limit.
    """

    research_run_id: UUID
    query_id: UUID
    branch: ResearchBranch = ResearchBranch.ACADEMIC
    purpose: QueryPurpose
    query: str = Field(min_length=1)
    provider: AcademicProvider
    requested_limit: int = Field(ge=1, le=200)

    @model_validator(mode="after")
    def _academic_only(self) -> AcademicSearchQuery:
        if self.branch is not ResearchBranch.ACADEMIC:
            raise ValueError("an academic search query must carry branch=ACADEMIC")
        if self.purpose not in ACADEMIC_SEARCH_PURPOSES:
            raise ValueError(f"{self.purpose.value} is not routed to academic providers")
        return self


class ExcludedAcademicQuery(MawhibaModel):
    """A planned query that was deliberately not executed, and why."""

    query_id: UUID
    query: str = Field(
        default="",
        description="Empty when the exclusion reason is PII_DETECTED: the ledger "
        "records that a query was refused, never the personal data in it.",
    )
    candidate_branch: str = ""
    candidate_purpose: str = ""
    reason: AcademicQueryExclusionReason

    @model_validator(mode="after")
    def _pii_is_never_stored(self) -> ExcludedAcademicQuery:
        if self.reason is AcademicQueryExclusionReason.PII_DETECTED and self.query:
            raise ValueError("a PII-excluded query must not retain its text")
        return self


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


IDENTIFIER_PRIORITY: tuple[SourceIdentifierKind, ...] = (
    SourceIdentifierKind.DOI,
    SourceIdentifierKind.PMID,
    SourceIdentifierKind.OPENALEX_ID,
    SourceIdentifierKind.SEMANTIC_SCHOLAR_ID,
    SourceIdentifierKind.ARXIV_ID,
    SourceIdentifierKind.CANONICAL_URL,
)
"""Strong-identifier precedence for cross-provider identity (ADR-009).

Title is absent and unrepresentable: ``SourceIdentifierKind`` has no title member.
"""


class AcademicIdentifiers(MawhibaModel):
    """Normalized strong identifiers for one work.

    ``None`` means the provider did not supply it -- never that the work lacks one.
    """

    doi: str | None = Field(default=None, pattern=DOI_PATTERN)
    pmid: str | None = Field(default=None, pattern=PMID_PATTERN)
    openalex_id: str | None = Field(default=None, pattern=OPENALEX_ID_PATTERN)
    semantic_scholar_id: str | None = Field(
        default=None, pattern=SEMANTIC_SCHOLAR_ID_PATTERN
    )
    arxiv_id: str | None = Field(default=None, pattern=ARXIV_ID_PATTERN)

    @property
    def as_map(self) -> dict[SourceIdentifierKind, str]:
        """Present identifiers, keyed by kind, in priority order."""
        pairs = (
            (SourceIdentifierKind.DOI, self.doi),
            (SourceIdentifierKind.PMID, self.pmid),
            (SourceIdentifierKind.OPENALEX_ID, self.openalex_id),
            (SourceIdentifierKind.SEMANTIC_SCHOLAR_ID, self.semantic_scholar_id),
            (SourceIdentifierKind.ARXIV_ID, self.arxiv_id),
        )
        return {kind: value for kind, value in pairs if value}

    @property
    def is_empty(self) -> bool:
        return not self.as_map

    def strongest(self) -> tuple[SourceIdentifierKind, str] | None:
        identifiers = self.as_map
        for kind in IDENTIFIER_PRIORITY:
            value = identifiers.get(kind)
            if value:
                return (kind, value)
        return None

    def merged_with(self, other: AcademicIdentifiers) -> AcademicIdentifiers:
        """Union of both sides.

        A conflicting value keeps ``self`` and is reported separately as a
        metadata conflict; nothing is silently overwritten.
        """
        return AcademicIdentifiers(
            doi=self.doi or other.doi,
            pmid=self.pmid or other.pmid,
            openalex_id=self.openalex_id or other.openalex_id,
            semantic_scholar_id=self.semantic_scholar_id or other.semantic_scholar_id,
            arxiv_id=self.arxiv_id or other.arxiv_id,
        )

    def conflicts_with(self, other: AcademicIdentifiers) -> list[SourceIdentifierKind]:
        """Kinds where both sides state a value and the values differ."""
        mine, theirs = self.as_map, other.as_map
        return [
            kind
            for kind in IDENTIFIER_PRIORITY
            if kind in mine and kind in theirs and mine[kind] != theirs[kind]
        ]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


class AcademicSourceCandidate(MawhibaModel):
    """One provider's record of one work. Untrusted: not a source, never evidence.

    ``raw_provider_metadata`` is compact JSON text rather than a nested mapping so
    that the checkpoint payload stays deterministic and every stored type is
    declared. It carries no credentials and no request headers.
    """

    candidate_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    query_id: UUID
    branch: ResearchBranch = ResearchBranch.ACADEMIC
    provider: AcademicProvider
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    publication_type: str | None = Field(
        default=None, description="The provider's own type string, preserved as given."
    )

    title: str = Field(min_length=1)
    abstract: str | None = Field(
        default=None,
        description="Provider-supplied metadata. Never full-text evidence (ADR-010).",
    )
    authors: list[str] = Field(default_factory=list)

    publication_year: int | None = Field(
        default=None, ge=MIN_PUBLICATION_YEAR, le=MAX_PUBLICATION_YEAR
    )
    publication_date: str | None = Field(default=None, pattern=PUBLICATION_DATE_PATTERN)
    venue: str | None = None
    publisher: str | None = None

    identifiers: AcademicIdentifiers = Field(default_factory=AcademicIdentifiers)
    canonical_url: str | None = Field(
        default=None, description="Provider-independent landing URL, canonicalized."
    )
    provider_url: str | None = Field(
        default=None, description="Where this provider points. Provider-specific."
    )

    citation_count: int | None = Field(default=None, ge=0)
    is_open_access: bool | None = None
    is_retracted: bool | None = Field(
        default=None,
        description="None means the provider said nothing. Never coerced to False.",
    )

    provider_rank: int | None = Field(
        default=None, ge=0, description="Retrieval metadata only, never validity."
    )
    provider_relevance: UnitInterval | None = Field(
        default=None, description="The provider's own score. Retrieval metadata only."
    )
    provider_record_id: str | None = None

    retrieved_at: UtcDatetime
    raw_provider_metadata: str | None = None

    @model_validator(mode="after")
    def _academic_branch_only(self) -> AcademicSourceCandidate:
        if self.branch is not ResearchBranch.ACADEMIC:
            raise ValueError("an academic candidate must carry branch=ACADEMIC")
        return self

    @property
    def identity(self) -> tuple[SourceIdentifierKind, str] | None:
        """The strongest identity this candidate can be deduplicated on."""
        strongest = self.identifiers.strongest()
        if strongest is not None:
            return strongest
        if self.canonical_url:
            return (SourceIdentifierKind.CANONICAL_URL, self.canonical_url)
        return None

    def identity_map(self) -> dict[SourceIdentifierKind, str]:
        identities = dict(self.identifiers.as_map)
        if self.canonical_url:
            identities[SourceIdentifierKind.CANONICAL_URL] = self.canonical_url
        return identities


class RejectedAcademicCandidate(MawhibaModel):
    """Auditable ledger entry for a provider record that was refused.

    Records enough to investigate and nothing more: no credentials, no full
    provider payload, no model reasoning (there is no model in this branch).
    """

    provider: AcademicProvider
    query_id: UUID
    stage: AcademicRejectionStage
    reason: AcademicRejectionReason
    provider_record_identifier: str | None = None
    safe_summary: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _pii_rejections_keep_no_text(self) -> RejectedAcademicCandidate:
        if self.reason is AcademicRejectionReason.PII_DETECTED and self.safe_summary:
            raise ValueError("a PII rejection must not retain the offending text")
        return self


class AcademicCandidateDecision(MawhibaModel):
    """The deterministic verdict on one candidate during source verification."""

    candidate_id: UUID
    provider: AcademicProvider
    query_id: UUID
    accepted: bool
    rejection_reason: AcademicRejectionReason | None = None
    logical_source_id: str | None = Field(
        default=None, pattern=CANONICAL_SOURCE_ID_PATTERN
    )

    @model_validator(mode="after")
    def _consistent(self) -> AcademicCandidateDecision:
        if self.accepted and self.rejection_reason is not None:
            raise ValueError("an accepted candidate carries no rejection reason")
        if not self.accepted:
            if self.rejection_reason is None:
                raise ValueError("a rejected candidate must state a reason")
            if self.logical_source_id is not None:
                raise ValueError("a rejected candidate belongs to no logical source")
        return self


# ---------------------------------------------------------------------------
# Provider results
# ---------------------------------------------------------------------------


class RateLimitInfo(MawhibaModel):
    """Rate limiting represented explicitly, never folded into a generic error."""

    provider: AcademicProvider
    limited: bool = True
    http_status: int | None = Field(default=None, ge=100, le=599)
    retry_after_seconds: float | None = Field(default=None, ge=0.0)
    attempts: int = Field(default=1, ge=1)


class AcademicProviderError(MawhibaModel):
    """One failed attempt against one provider.

    ``message`` is a developer-facing English summary built by this project, not
    a raw provider body: a provider echo could carry a key, a token, or a URL
    with credentials in it.
    """

    provider: AcademicProvider
    kind: AcademicErrorKind
    retryable: bool
    attempt: int = Field(ge=1)
    http_status: int | None = Field(default=None, ge=100, le=599)
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _retryability_matches_kind(self) -> AcademicProviderError:
        if self.retryable != (self.kind in RETRYABLE_ERROR_KINDS):
            raise ValueError(
                f"retryable={self.retryable} contradicts kind {self.kind.value}"
            )
        return self


class AcademicSearchResult(MawhibaModel):
    """Provider-neutral envelope for ONE provider answering ONE query."""

    provider: AcademicProvider
    query_id: UUID
    research_run_id: UUID
    status: AcademicSearchStatus
    attempts: int = Field(default=1, ge=1)
    requested_limit: int = Field(ge=1, le=200)

    raw_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)

    candidates: list[AcademicSourceCandidate] = Field(default_factory=list)
    rejected: list[RejectedAcademicCandidate] = Field(default_factory=list)
    rate_limit: RateLimitInfo | None = None
    errors: list[AcademicProviderError] = Field(default_factory=list)

    started_at: UtcDatetime
    completed_at: UtcDatetime

    @model_validator(mode="after")
    def _status_matches_payload(self) -> AcademicSearchResult:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.accepted_count != len(self.candidates):
            raise ValueError("accepted_count must match the candidates returned")
        if any(c.provider is not self.provider for c in self.candidates):
            raise ValueError("a candidate belongs to a different provider")
        if any(c.query_id != self.query_id for c in self.candidates):
            raise ValueError("a candidate belongs to a different query")

        if self.status in SUCCESSFUL_SEARCH_STATUSES:
            if not self.candidates:
                raise ValueError(f"{self.status.value} requires at least one candidate")
            if (self.status is AcademicSearchStatus.PARTIAL) != (self.rejected_count > 0):
                raise ValueError("PARTIAL is exactly a success with rejected records")
        elif self.candidates:
            raise ValueError(f"{self.status.value} must not carry candidates")

        if self.status is AcademicSearchStatus.EMPTY and (self.raw_count or self.errors):
            raise ValueError("EMPTY means the provider answered with no records")
        if self.status is AcademicSearchStatus.RATE_LIMITED and self.rate_limit is None:
            raise ValueError("RATE_LIMITED requires rate_limit information")
        if (
            self.status
            in (
                AcademicSearchStatus.TIMEOUT,
                AcademicSearchStatus.AUTH_ERROR,
                AcademicSearchStatus.PROVIDER_ERROR,
                AcademicSearchStatus.RATE_LIMITED,
            )
            and not self.errors
        ):
            raise ValueError(f"{self.status.value} requires at least one error")
        return self

    @property
    def executed(self) -> bool:
        """The provider answered, even if it found nothing."""
        return self.status in EXECUTED_SEARCH_STATUSES

    @property
    def failed(self) -> bool:
        return not self.executed


# ---------------------------------------------------------------------------
# Logical sources and provider observations (ADR-009)
# ---------------------------------------------------------------------------


class CitationObservation(MawhibaModel):
    """A citation count is a provider's reading at a moment, not a property of
    the work. Stored with both, or not at all."""

    provider: AcademicProvider
    count: int = Field(ge=0)
    retrieved_at: UtcDatetime


class ProviderObservation(MawhibaModel):
    """What ONE provider said about ONE logical source, kept after deduplication.

    This is what makes "which providers independently returned this source?"
    answerable, and what a first-provider-wins merge would have destroyed.
    """

    provider: AcademicProvider
    candidate_id: UUID
    query_id: UUID
    research_run_id: UUID
    provider_record_id: str | None = None
    provider_url: str | None = None
    canonical_url: str | None = None
    identifiers: AcademicIdentifiers = Field(default_factory=AcademicIdentifiers)
    title: str = Field(min_length=1)
    publication_year: int | None = Field(
        default=None, ge=MIN_PUBLICATION_YEAR, le=MAX_PUBLICATION_YEAR
    )
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    is_retracted: bool | None = None
    is_open_access: bool | None = None
    citation_count: int | None = Field(default=None, ge=0)
    provider_rank: int | None = Field(default=None, ge=0)
    provider_relevance: UnitInterval | None = None
    retrieved_at: UtcDatetime


class ConflictValue(MawhibaModel):
    provider: AcademicProvider
    value: str = Field(min_length=1)


class MetadataConflict(MawhibaModel):
    """Providers disagree about one field. Both readings are always preserved."""

    field_name: str = Field(min_length=1)
    values: list[ConflictValue] = Field(min_length=2)
    resolved_value: str | None = Field(
        default=None,
        description="Set only where a documented rule resolves the disagreement "
        "(retraction is sticky-true). Otherwise the merged field is left unknown.",
    )

    @model_validator(mode="after")
    def _values_actually_disagree(self) -> MetadataConflict:
        if len({v.value for v in self.values}) < 2:
            raise ValueError("a conflict needs at least two distinct values")
        if len({v.provider for v in self.values}) < 2:
            raise ValueError("a conflict needs at least two providers")
        return self


class LogicalAcademicSource(MawhibaModel):
    """ONE work, assembled from every provider that returned it.

    Verified means *bibliographically* verified: identifiers are well formed and
    consistent, the record is traceable to a query and a run, and the merge kept
    every provider observation. It says nothing about what the paper shows.
    """

    logical_source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    display_id: str | None = Field(default=None, pattern=DISPLAY_ID_PATTERN)
    research_run_id: UUID
    fingerprint: SourceFingerprint
    identifiers: AcademicIdentifiers = Field(default_factory=AcademicIdentifiers)

    title: str = Field(min_length=1)
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = Field(
        default=None, ge=MIN_PUBLICATION_YEAR, le=MAX_PUBLICATION_YEAR
    )
    publication_date: str | None = Field(default=None, pattern=PUBLICATION_DATE_PATTERN)
    venue: str | None = None
    publisher: str | None = None
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    is_open_access: bool | None = None
    is_retracted: bool | None = None
    canonical_url: str | None = None

    observations: list[ProviderObservation] = Field(min_length=1)
    citation_observations: list[CitationObservation] = Field(default_factory=list)
    conflicts: list[MetadataConflict] = Field(default_factory=list)

    verification_status: VerificationStatus = VerificationStatus.VERIFIED_METADATA
    first_retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def _identity_and_provenance_hold(self) -> LogicalAcademicSource:
        if self.verification_status is not VerificationStatus.VERIFIED_METADATA:
            raise ValueError(
                "Phase 2B verifies metadata only; full-text verification is a "
                "later phase (ADR-010)"
            )
        strongest = self.identifiers.strongest()
        if strongest is None and self.canonical_url:
            strongest = (SourceIdentifierKind.CANONICAL_URL, self.canonical_url)
        if strongest is None:
            raise ValueError("a logical academic source needs at least one identifier")
        kind, value = strongest
        if self.fingerprint.identifier_kind is not kind:
            raise ValueError(
                f"fingerprint must use the strongest identifier ({kind.value})"
            )
        if self.fingerprint.identifier != SourceFingerprint.normalize(kind, value):
            raise ValueError("fingerprint identifier must be the normalized identifier")
        if any(o.research_run_id != self.research_run_id for o in self.observations):
            raise ValueError("an observation belongs to a different research run")
        return self

    @property
    def providers(self) -> list[AcademicProvider]:
        """Which providers independently returned this source, in dispatch order."""
        seen = {o.provider for o in self.observations}
        return [p for p in ACADEMIC_PROVIDER_ORDER if p in seen]

    @property
    def query_ids(self) -> list[UUID]:
        return list(dict.fromkeys(o.query_id for o in self.observations))

    @property
    def is_preprint(self) -> bool:
        return self.source_type is AcademicSourceType.PREPRINT

    @property
    def peer_review_status(self) -> PeerReviewStatus:
        """Only what the publication form actually states."""
        if self.source_type is AcademicSourceType.PREPRINT:
            return PeerReviewStatus.NOT_PEER_REVIEWED
        if self.source_type in PEER_REVIEWED_SOURCE_TYPES:
            return PeerReviewStatus.PEER_REVIEWED
        return PeerReviewStatus.UNKNOWN

    def to_source_record(self) -> SourceRecord:
        """The Phase 0 ``SourceRecord`` for this work. Never an evidence record.

        ``quality`` stays at its default and ``tier`` stays ``UNRATED``: coming
        back from an academic API proves retrieval, not quality. ``query_id`` is
        left unset because the Phase 0 field is the ``Q-001`` execution-log form,
        while academic provenance is the UUID-keyed observations on this source.
        """
        return SourceRecord(
            source_id=self.logical_source_id,
            display_id=self.display_id,
            fingerprint=self.fingerprint,
            source_type=ACADEMIC_TO_SOURCE_TYPE[self.source_type],
            title=self.title,
            authors_or_org=list(self.authors),
            year=self.publication_year,
            journal_or_venue=self.venue,
            doi=self.identifiers.doi,
            url=self.canonical_url,
            provider=ACADEMIC_TO_SOURCE_PROVIDER[self.observations[0].provider],
            retrieved_at=self.first_retrieved_at,
            peer_review_status=self.peer_review_status,
            branch=ResearchBranch.ACADEMIC,
            tier=SourceTier.UNRATED,
            verification_status=VerificationStatus.VERIFIED_METADATA,
        )


# ---------------------------------------------------------------------------
# Branch result
# ---------------------------------------------------------------------------


class AcademicBudgetReport(MawhibaModel):
    """What the budget allowed, what was used, and what it cut off.

    Truncation is recorded rather than silent, and is never counted as a
    provider failure.
    """

    max_queries_per_run: int = Field(ge=1)
    max_results_per_query_per_provider: int = Field(ge=1)
    max_results_per_provider_per_run: int = Field(ge=1)
    max_total_candidates: int = Field(ge=1)

    queries_available: int = Field(default=0, ge=0)
    queries_executed: int = Field(default=0, ge=0)
    queries_truncated: int = Field(default=0, ge=0)

    candidates_returned: int = Field(default=0, ge=0)
    candidates_accepted: int = Field(default=0, ge=0)
    candidates_truncated_per_provider: int = Field(default=0, ge=0)
    candidates_truncated_total: int = Field(default=0, ge=0)

    @property
    def truncated(self) -> bool:
        return bool(
            self.queries_truncated
            or self.candidates_truncated_per_provider
            or self.candidates_truncated_total
        )


class AcademicRetrievalResult(MawhibaModel):
    """Everything the ACADEMIC branch produced in one research run.

    Lives on the ``ResearchRun``, never in ``ProjectState``: academic retrieval
    reads canonical state through the verified query plan and writes none of it.
    """

    research_run_id: UUID
    outcome: AcademicBranchOutcome = AcademicBranchOutcome.NOT_RUN
    providers: list[AcademicProvider] = Field(default_factory=list)

    contract_version: str = ACADEMIC_CONTRACT_VERSION
    normalizer_version: str = ACADEMIC_NORMALIZER_VERSION
    dedup_version: str = ACADEMIC_DEDUP_VERSION
    connector_versions: dict[str, str] = Field(default_factory=dict)

    budget: AcademicBudgetReport
    selected_queries: list[AcademicSearchQuery] = Field(default_factory=list)
    excluded_queries: list[ExcludedAcademicQuery] = Field(default_factory=list)

    provider_results: list[AcademicSearchResult] = Field(default_factory=list)
    candidates: list[AcademicSourceCandidate] = Field(default_factory=list)
    decisions: list[AcademicCandidateDecision] = Field(default_factory=list)
    rejected_candidates: list[RejectedAcademicCandidate] = Field(default_factory=list)

    logical_sources: list[LogicalAcademicSource] = Field(default_factory=list)
    verified_sources: list[SourceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _outcome_matches_content(self) -> AcademicRetrievalResult:
        if any(r.research_run_id != self.research_run_id for r in self.provider_results):
            raise ValueError("a provider result belongs to a different research run")
        if any(s.research_run_id != self.research_run_id for s in self.logical_sources):
            raise ValueError("a logical source belongs to a different research run")

        source_ids = [s.logical_source_id for s in self.logical_sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("logical source ids must be unique")
        if sorted(source_ids) != sorted(r.source_id for r in self.verified_sources):
            raise ValueError("every logical source has exactly one verified SourceRecord")

        if self.outcome is AcademicBranchOutcome.NOT_RUN and self.provider_results:
            raise ValueError("NOT_RUN must not carry provider results")
        if self.outcome is AcademicBranchOutcome.FAILED and self.logical_sources:
            raise ValueError("FAILED must not carry verified sources")
        if self.outcome is AcademicBranchOutcome.EMPTY and self.candidates:
            raise ValueError("EMPTY means no provider returned a usable record")
        return self

    # -- read helpers ---------------------------------------------------------

    @property
    def provider_success_count(self) -> int:
        return sum(
            1 for r in self.provider_results if r.status in SUCCESSFUL_SEARCH_STATUSES
        )

    @property
    def provider_empty_count(self) -> int:
        return sum(
            1 for r in self.provider_results if r.status is AcademicSearchStatus.EMPTY
        )

    @property
    def provider_failure_count(self) -> int:
        return sum(1 for r in self.provider_results if r.failed)

    @property
    def conflicts(self) -> list[MetadataConflict]:
        return [c for s in self.logical_sources for c in s.conflicts]

    @property
    def query_count(self) -> int:
        return len(self.selected_queries)

    def results_for(self, provider: AcademicProvider) -> list[AcademicSearchResult]:
        return [r for r in self.provider_results if r.provider is provider]

    def source_by_id(self, logical_source_id: str) -> LogicalAcademicSource | None:
        return next(
            (s for s in self.logical_sources if s.logical_source_id == logical_source_id),
            None,
        )


def safe_summary(text: str | None) -> str:
    """A short, single-line, length-bounded summary for the rejection ledger."""
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= MAX_SAFE_SUMMARY_LENGTH:
        return collapsed
    return collapsed[: MAX_SAFE_SUMMARY_LENGTH - 1] + "…"
