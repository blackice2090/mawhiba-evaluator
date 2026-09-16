"""SourceRecord -- architecture 7.1, 11 (Source Quality Engine), 27 (coverage)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from urllib.parse import urlsplit, urlunsplit

from src.schemas.common import (
    DISPLAY_ID_PATTERN,
    SOURCE_ID_PATTERN,
    BranchStatus,
    MawhibaModel,
    ResearchBranch,
    UnitInterval,
    UtcDatetime,
    utc_now,
)


class SourceType(StrEnum):
    ACADEMIC_PAPER = "ACADEMIC_PAPER"
    PREPRINT = "PREPRINT"
    SYSTEMATIC_REVIEW = "SYSTEMATIC_REVIEW"
    PATENT = "PATENT"
    STANDARD = "STANDARD"
    PRODUCT_PAGE = "PRODUCT_PAGE"
    VENDOR_DOCUMENTATION = "VENDOR_DOCUMENTATION"
    DATASHEET = "DATASHEET"
    REPOSITORY = "REPOSITORY"
    OFFICIAL_COMPETITION_SOURCE = "OFFICIAL_COMPETITION_SOURCE"
    DATASET = "DATASET"
    BLOG_OR_SOCIAL = "BLOG_OR_SOCIAL"
    OTHER = "OTHER"


class SourceProvider(StrEnum):
    """Retrieval provider, kept separate from SourceType for provenance."""

    CONSENSUS = "CONSENSUS"
    OPENALEX = "OPENALEX"
    SEMANTIC_SCHOLAR = "SEMANTIC_SCHOLAR"
    EPO_OPS = "EPO_OPS"
    WIPO_PATENTSCOPE = "WIPO_PATENTSCOPE"
    USPTO = "USPTO"
    GITHUB = "GITHUB"
    TAVILY = "TAVILY"
    OPENAI_WEB_SEARCH = "OPENAI_WEB_SEARCH"
    OFFICIAL_WEB = "OFFICIAL_WEB"
    MANUAL = "MANUAL"
    STUDENT_SUBMISSION = "STUDENT_SUBMISSION"
    UNKNOWN = "UNKNOWN"


class PeerReviewStatus(StrEnum):
    PEER_REVIEWED = "PEER_REVIEWED"
    NOT_PEER_REVIEWED = "NOT_PEER_REVIEWED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(StrEnum):
    """Section N06A: a search hit is not evidence until its metadata is verified."""

    UNVERIFIED = "UNVERIFIED"
    SEARCH_RESULT_ONLY = "SEARCH_RESULT_ONLY"
    VERIFIED_METADATA = "VERIFIED_METADATA"
    VERIFIED_FULL_TEXT = "VERIFIED_FULL_TEXT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class SourceTier(StrEnum):
    """Section 11 source tiers. Tier D alone never supports a substantive judgement."""

    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"
    UNRATED = "UNRATED"


class SourceQuality(MawhibaModel):
    """Section 11. An internal ranking signal, explicitly not a scientific truth value."""

    authority: UnitInterval = 0.0
    relevance: UnitInterval = 0.0
    methodological_strength: UnitInterval = 0.0
    recency_fit: UnitInterval = 0.0
    independent_validation: UnitInterval = 0.0


class SourceIdentifierKind(StrEnum):
    """Identifier types a source can be deduplicated on.

    Title is deliberately absent: two different works share a title, and one work
    appears under slightly different titles. Deduplicating on it would merge
    distinct sources, so the contract makes that impossible to express.
    """

    CANONICAL_URL = "CANONICAL_URL"
    DOI = "DOI"
    OPENALEX_ID = "OPENALEX_ID"
    SEMANTIC_SCHOLAR_ID = "SEMANTIC_SCHOLAR_ID"
    PMID = "PMID"
    ARXIV_ID = "ARXIV_ID"
    PATENT_PUBLICATION_NUMBER = "PATENT_PUBLICATION_NUMBER"
    REPOSITORY_ID = "REPOSITORY_ID"


def canonicalize_web_url(url: str) -> str:
    """Lowercase scheme and host, drop the default port and the fragment."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").rstrip(".").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    return urlunsplit((scheme, f"{host}{port}", parts.path or "/", parts.query, ""))


class SourceFingerprint(MawhibaModel):
    """Deterministic identity of a source, separate from its ``source_id``.

    ``source_id`` answers "which record is this?"; a fingerprint answers "is this
    the same source, and is it the same version of it?". Two records for one
    logical source share a ``logical_key``; two captures of the same content also
    share a ``content_hash``.
    """

    identifier_kind: SourceIdentifierKind
    identifier: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def normalize(cls, kind: SourceIdentifierKind, identifier: str) -> str:
        value = identifier.strip()
        if kind is SourceIdentifierKind.CANONICAL_URL:
            return canonicalize_web_url(value)
        if kind is SourceIdentifierKind.DOI:
            return value.casefold().removeprefix("https://doi.org/").removeprefix("doi:")
        return value.casefold()

    @classmethod
    def create(
        cls,
        kind: SourceIdentifierKind,
        identifier: str,
        content_hash: str | None = None,
    ) -> SourceFingerprint:
        return cls(
            identifier_kind=kind,
            identifier=cls.normalize(kind, identifier),
            content_hash=content_hash,
        )

    @classmethod
    def for_url(cls, canonical_url: str, content_hash: str | None = None) -> SourceFingerprint:
        return cls.create(SourceIdentifierKind.CANONICAL_URL, canonical_url, content_hash)

    @model_validator(mode="after")
    def _identifier_is_normalized(self) -> SourceFingerprint:
        expected = SourceFingerprint.normalize(self.identifier_kind, self.identifier)
        if self.identifier != expected:
            raise ValueError(
                f"identifier must be normalized for {self.identifier_kind.value}: "
                f"{self.identifier!r} != {expected!r}"
            )
        return self

    @property
    def logical_key(self) -> str:
        """Identity of the source itself, independent of the captured content."""
        return f"{self.identifier_kind.value}:{self.identifier}"

    @property
    def version_key(self) -> tuple[str, str | None]:
        """Identity of one captured version of that source."""
        return (self.logical_key, self.content_hash)

    def same_logical_source(self, other: SourceFingerprint) -> bool:
        return self.logical_key == other.logical_key

    def same_content_version(self, other: SourceFingerprint) -> bool:
        """True only when both captures are hashed and the hashes agree."""
        return (
            self.same_logical_source(other)
            and self.content_hash is not None
            and self.content_hash == other.content_hash
        )


class SourceRecord(MawhibaModel):
    """A retrieved, deduplicated, provenance-carrying source (7.1)."""

    source_id: str = Field(
        pattern=SOURCE_ID_PATTERN,
        description="Canonical identity. New code mints the opaque UUID form; the "
        "Phase 0 sequence form stays loadable for existing data.",
        examples=["SRC-1b4e28ba-2fa1-41d2-883f-0016d3cca427"],
    )
    display_id: str | None = Field(
        default=None,
        pattern=DISPLAY_ID_PATTERN,
        description="Human-readable sequence for reports. Never identity.",
        examples=["SRC-001"],
    )
    fingerprint: SourceFingerprint | None = Field(
        default=None, description="Deterministic dedup identity (N07)."
    )
    source_type: SourceType
    title: str | None = None
    authors_or_org: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1400, le=2200)
    journal_or_venue: str | None = None
    doi: str | None = None
    url: str | None = None
    provider: SourceProvider = SourceProvider.UNKNOWN
    retrieved_at: UtcDatetime = Field(default_factory=utc_now)
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN
    query_id: str | None = Field(default=None, pattern=r"^Q-\d{2,}$")
    branch: ResearchBranch | None = None
    content_hash: str | None = Field(
        default=None,
        description="Hash of retrieved content; required for official sources (2.4).",
    )
    version_or_publication_date: str | None = Field(
        default=None, description="2.4: official rule snapshots carry a version/date."
    )
    quality: SourceQuality = Field(default_factory=SourceQuality)
    tier: SourceTier = SourceTier.UNRATED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    duplicate_of: str | None = Field(
        default=None,
        pattern=SOURCE_ID_PATTERN,
        description="Set by N07 dedup; the surviving canonical source id.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _official_sources_need_provenance(self) -> SourceRecord:
        if self.source_type == SourceType.OFFICIAL_COMPETITION_SOURCE:
            # 2.4: every official-rules snapshot is stored with URL, retrieval
            # timestamp and a content hash.
            if not self.url or not self.content_hash:
                raise ValueError(
                    "OFFICIAL_COMPETITION_SOURCE requires both url and content_hash (2.4)"
                )
        if self.duplicate_of == self.source_id:
            raise ValueError("source cannot be a duplicate of itself")
        if (
            self.fingerprint is not None
            and self.fingerprint.content_hash is not None
            and self.content_hash is not None
            and self.fingerprint.content_hash != self.content_hash
        ):
            raise ValueError("fingerprint content_hash must match the source content_hash")
        return self


class ResearchQueryRecord(MawhibaModel):
    """Section 27 research coverage log. A branch is never 'complete' on one query."""

    query_id: str = Field(pattern=r"^Q-\d{2,}$", examples=["Q-001"])
    branch: ResearchBranch
    query: str = Field(min_length=1)
    provider: SourceProvider = SourceProvider.UNKNOWN
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    result_count: int | None = Field(default=None, ge=0)
    selected_count: int | None = Field(default=None, ge=0)
    status: BranchStatus = BranchStatus.NOT_STARTED
    error: str | None = None

    @model_validator(mode="after")
    def _check_counts_and_times(self) -> ResearchQueryRecord:
        if (
            self.result_count is not None
            and self.selected_count is not None
            and self.selected_count > self.result_count
        ):
            raise ValueError("selected_count cannot exceed result_count")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at")
        return self
