"""Official Mawhiba requirements contracts -- Phase 2A, architecture 2.4 and N03.

The trust progression for the official branch is explicit in the types:

    OfficialRetrievalResult   what a web provider returned      (not persisted)
    SourceCandidate           a retrieved page, NOT yet trusted
    OfficialSourceSnapshot    allowlisted, hashed, verified page
    SourceRecord              the Phase 0 source contract built from a snapshot
    OfficialRequirement       an anchor-verified requirement inside a snapshot

Nothing here is an ``EvidenceRecord``. Retrieval produces candidates;
verification produces sources; evidence extraction is a later stage (ADR-007).

Phase 2A.1 additionally separates five things that are easy to conflate:
official authority, publication date, competition edition, retrieval date, and
current status. A page can be official without being current.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.common import (
    CANONICAL_SOURCE_ID_PATTERN,
    DISPLAY_ID_PATTERN,
    MawhibaModel,
    ResearchBranch,
    UtcDatetime,
    utc_now,
)
from src.schemas.extraction import ModelFacingModel, VerifiedAnchor
from src.schemas.source import (
    SourceFingerprint,
    SourceRecord,
    SourceType,
    VerificationStatus,
)

HASH_NORMALIZATION_VERSION = "TEXT-NORMALIZATION-V1"
"""Line endings to LF, NFC, invisible characters removed, quotes folded,
whitespace runs collapsed. Wording changes always change the hash."""

MIN_COMPETITION_EDITION = 2000
MAX_COMPETITION_EDITION = 2100


class CriteriaAuthority(StrEnum):
    """Hard boundary between official criteria and the agent's own rubric."""

    OFFICIAL_MAWHIBA_CRITERIA = "OFFICIAL_MAWHIBA_CRITERIA"
    AGENT_ADVISORY_RUBRIC = "AGENT_ADVISORY_RUBRIC"


class OfficialPageKind(StrEnum):
    """What role an official page plays, declared by a reviewer in configuration.

    The distinction exists because officialness says nothing about currency: a
    genuine 2025 registration page is official and out of date at the same time.
    """

    EVERGREEN_SERVICE_PAGE = "EVERGREEN_SERVICE_PAGE"
    CURRENT_EVENT_PAGE = "CURRENT_EVENT_PAGE"
    HISTORICAL_EVENT_PAGE = "HISTORICAL_EVENT_PAGE"
    DISCOVERY_PAGE = "DISCOVERY_PAGE"


class EditionSource(StrEnum):
    """Where a competition edition came from. Never from the retrieval date."""

    NONE = "NONE"
    SEED_DECLARATION = "SEED_DECLARATION"
    PAGE_TITLE = "PAGE_TITLE"


class OfficialCurrency(StrEnum):
    """Whether verified official content applies to the edition under evaluation."""

    CURRENT_EDITION = "CURRENT_EDITION"
    EVERGREEN = "EVERGREEN"
    HISTORICAL_EDITION = "HISTORICAL_EDITION"
    UNDETERMINED = "UNDETERMINED"


class OfficialSeed(MawhibaModel):
    """One configured official URL and the role a reviewer assigned to it."""

    url: str = Field(min_length=1)
    kind: OfficialPageKind = OfficialPageKind.EVERGREEN_SERVICE_PAGE
    competition_edition: int | None = Field(
        default=None, ge=MIN_COMPETITION_EDITION, le=MAX_COMPETITION_EDITION
    )
    note: str | None = None

    @model_validator(mode="after")
    def _edition_matches_kind(self) -> OfficialSeed:
        event_page = self.kind in (
            OfficialPageKind.CURRENT_EVENT_PAGE,
            OfficialPageKind.HISTORICAL_EVENT_PAGE,
        )
        if event_page and self.competition_edition is None:
            raise ValueError(f"{self.kind.value} must declare its competition_edition")
        if not event_page and self.competition_edition is not None:
            raise ValueError(
                f"{self.kind.value} describes no single edition and must not declare one"
            )
        return self


class RetrievalStatus(StrEnum):
    """Outcome of one official web retrieval. An execution fact, not a rule."""

    SUCCESS = "SUCCESS"
    BLOCKED_NOT_ALLOWLISTED = "BLOCKED_NOT_ALLOWLISTED"
    HTTP_ERROR = "HTTP_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    TOO_LARGE = "TOO_LARGE"
    EMPTY_CONTENT = "EMPTY_CONTENT"


class OfficialRetrievalResult(MawhibaModel):
    """What an ``OfficialWebProvider`` returns. Consumed inside a node only."""

    status: RetrievalStatus
    requested_url: str = Field(min_length=1)
    final_url: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = None
    title: str | None = None
    text: str | None = None
    published_at: UtcDatetime | None = Field(
        default=None, description="Only from explicit page metadata. Never guessed."
    )
    effective_at: UtcDatetime | None = Field(
        default=None, description="Only from explicit page metadata. Never guessed."
    )
    retrieved_at: UtcDatetime = Field(default_factory=utc_now)
    provider: str = Field(min_length=1)
    error: str | None = None

    @model_validator(mode="after")
    def _status_matches_payload(self) -> OfficialRetrievalResult:
        if self.status is RetrievalStatus.SUCCESS:
            if not self.text:
                raise ValueError("a SUCCESS retrieval requires text")
        else:
            if self.text:
                raise ValueError(f"status={self.status.value} must not carry text")
            if not self.error:
                raise ValueError(f"status={self.status.value} requires an error summary")
        return self


class SourceCandidate(MawhibaModel):
    """A retrieved page. Untrusted: not a source, and never evidence."""

    candidate_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    branch: ResearchBranch = ResearchBranch.OFFICIAL_REQUIREMENTS
    requested_url: str = Field(min_length=1)
    final_url: str | None = None
    page_kind: OfficialPageKind = OfficialPageKind.DISCOVERY_PAGE
    declared_edition: int | None = Field(
        default=None, ge=MIN_COMPETITION_EDITION, le=MAX_COMPETITION_EDITION
    )
    retrieval_status: RetrievalStatus
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = None
    title: str | None = None
    captured_text: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    published_at: UtcDatetime | None = None
    effective_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    provider: str = Field(min_length=1)
    error: str | None = None

    @model_validator(mode="after")
    def _success_carries_content(self) -> SourceCandidate:
        if self.retrieval_status is RetrievalStatus.SUCCESS:
            if not self.captured_text or not self.content_hash:
                raise ValueError("a successful candidate requires captured_text and content_hash")
        elif self.captured_text is not None:
            raise ValueError("a failed retrieval must not carry captured_text")
        return self


class SourceRejectionReason(StrEnum):
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    INSECURE_SCHEME = "INSECURE_SCHEME"
    DOMAIN_NOT_ALLOWLISTED = "DOMAIN_NOT_ALLOWLISTED"
    REDIRECT_NOT_ALLOWLISTED = "REDIRECT_NOT_ALLOWLISTED"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"


class SourceVerificationDecision(MawhibaModel):
    """The deterministic verdict on one candidate, accepted or not."""

    candidate_id: UUID
    requested_url: str = Field(min_length=1)
    accepted: bool
    rejection_reason: SourceRejectionReason | None = None
    source_id: str | None = Field(default=None, pattern=CANONICAL_SOURCE_ID_PATTERN)
    display_id: str | None = Field(default=None, pattern=DISPLAY_ID_PATTERN)

    @model_validator(mode="after")
    def _consistent(self) -> SourceVerificationDecision:
        if self.accepted and (self.rejection_reason is not None or self.source_id is None):
            raise ValueError("an accepted candidate needs a source_id and no rejection reason")
        if not self.accepted and (self.rejection_reason is None or self.source_id is not None):
            raise ValueError("a rejected candidate needs a reason and no source_id")
        return self


class OfficialSourceSnapshot(MawhibaModel):
    """A verified, content-hashed capture of one official page (2.4).

    Its ``fingerprint`` carries the deterministic identity: the same canonical URL
    with the same content hash is the same requirements version, and the same URL
    with a different hash is a different version of the same logical source.
    """

    snapshot_id: UUID = Field(default_factory=uuid4)
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    display_id: str | None = Field(default=None, pattern=DISPLAY_ID_PATTERN)
    candidate_id: UUID
    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    title: str | None = None
    retrieved_at: UtcDatetime
    published_at: UtcDatetime | None = None
    effective_at: UtcDatetime | None = None
    page_kind: OfficialPageKind = OfficialPageKind.DISCOVERY_PAGE
    competition_edition: int | None = Field(
        default=None, ge=MIN_COMPETITION_EDITION, le=MAX_COMPETITION_EDITION
    )
    edition_source: EditionSource = EditionSource.NONE
    currency: OfficialCurrency = OfficialCurrency.UNDETERMINED
    assessed_against_edition: int | None = Field(
        default=None,
        ge=MIN_COMPETITION_EDITION,
        le=MAX_COMPETITION_EDITION,
        description="The edition under evaluation when currency was assessed.",
    )
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_normalization: str = HASH_NORMALIZATION_VERSION
    fingerprint: SourceFingerprint
    captured_text: str = Field(min_length=1)
    verification_status: VerificationStatus = VerificationStatus.VERIFIED_FULL_TEXT
    authority: CriteriaAuthority = CriteriaAuthority.OFFICIAL_MAWHIBA_CRITERIA

    @model_validator(mode="after")
    def _only_verified_official_snapshots_exist(self) -> OfficialSourceSnapshot:
        if self.verification_status is not VerificationStatus.VERIFIED_FULL_TEXT:
            raise ValueError("an official snapshot exists only after verification")
        if self.authority is not CriteriaAuthority.OFFICIAL_MAWHIBA_CRITERIA:
            raise ValueError("an official snapshot cannot carry advisory authority")
        if self.fingerprint.identifier != self.canonical_url:
            raise ValueError("fingerprint identifier must be the canonical URL")
        if self.fingerprint.content_hash != self.content_hash:
            raise ValueError("fingerprint content_hash must match the snapshot hash")
        if (self.competition_edition is None) != (self.edition_source is EditionSource.NONE):
            raise ValueError("a competition edition must state where it came from")
        if self.currency is OfficialCurrency.CURRENT_EDITION and self.competition_edition is None:
            raise ValueError("CURRENT_EDITION requires a known competition edition")
        return self

    @property
    def version_key(self) -> tuple[str, str | None]:
        return self.fingerprint.version_key

    @property
    def date_indicator(self) -> UtcDatetime | None:
        return self.effective_at or self.published_at

    @property
    def is_usable_as_current(self) -> bool:
        """Evergreen guidance, or content for the edition under evaluation."""
        return self.currency in (OfficialCurrency.CURRENT_EDITION, OfficialCurrency.EVERGREEN)

    def to_source_record(self) -> SourceRecord:
        """The Phase 0 ``SourceRecord`` for this snapshot. Never an evidence record."""
        from src.schemas.source import SourceProvider, SourceTier

        return SourceRecord(
            source_id=self.source_id,
            display_id=self.display_id,
            fingerprint=self.fingerprint,
            source_type=SourceType.OFFICIAL_COMPETITION_SOURCE,
            title=self.title,
            url=self.canonical_url,
            provider=SourceProvider.OFFICIAL_WEB,
            retrieved_at=self.retrieved_at,
            branch=ResearchBranch.OFFICIAL_REQUIREMENTS,
            content_hash=self.content_hash,
            version_or_publication_date=(
                self.published_at.isoformat() if self.published_at else None
            ),
            tier=SourceTier.TIER_A,
            verification_status=VerificationStatus.VERIFIED_FULL_TEXT,
        )


class OfficialRequirementCategory(StrEnum):
    ELIGIBILITY = "ELIGIBILITY"
    PROJECT_CATEGORIES = "PROJECT_CATEGORIES"
    SUBMISSION_REQUIREMENTS = "SUBMISSION_REQUIREMENTS"
    COMPETITION_STAGES = "COMPETITION_STAGES"
    RESEARCH_ETHICS = "RESEARCH_ETHICS"
    EXPERIMENT_RESTRICTIONS = "EXPERIMENT_RESTRICTIONS"
    JUDGING_CRITERIA = "JUDGING_CRITERIA"
    SCORING_WEIGHTS = "SCORING_WEIGHTS"
    DEADLINES = "DEADLINES"
    FORMS_AND_INSTRUCTIONS = "FORMS_AND_INSTRUCTIONS"


WEIGHT_BEARING_CATEGORIES: frozenset[OfficialRequirementCategory] = frozenset(
    {OfficialRequirementCategory.JUDGING_CRITERIA, OfficialRequirementCategory.SCORING_WEIGHTS}
)


class OfficialRequirementStatus(StrEnum):
    """Retrieval today is never enough to call a requirement current."""

    VERIFIED_CURRENT = "VERIFIED_CURRENT"
    VERIFIED_EVERGREEN = "VERIFIED_EVERGREEN"
    VERIFIED_CURRENCY_UNKNOWN = "VERIFIED_CURRENCY_UNKNOWN"
    HISTORICAL = "HISTORICAL"
    CONFLICTED = "CONFLICTED"
    SUPERSEDED = "SUPERSEDED"
    UNVERIFIED = "UNVERIFIED"


APPLICABLE_REQUIREMENT_STATUSES: frozenset[OfficialRequirementStatus] = frozenset(
    {OfficialRequirementStatus.VERIFIED_CURRENT, OfficialRequirementStatus.VERIFIED_EVERGREEN}
)
"""Statuses that may inform an evaluation of the edition under assessment.
Historical and superseded requirements are kept, never applied, never discarded."""

CURRENCY_TO_REQUIREMENT_STATUS: dict[OfficialCurrency, OfficialRequirementStatus] = {
    OfficialCurrency.CURRENT_EDITION: OfficialRequirementStatus.VERIFIED_CURRENT,
    OfficialCurrency.EVERGREEN: OfficialRequirementStatus.VERIFIED_EVERGREEN,
    OfficialCurrency.HISTORICAL_EDITION: OfficialRequirementStatus.HISTORICAL,
    OfficialCurrency.UNDETERMINED: OfficialRequirementStatus.VERIFIED_CURRENCY_UNKNOWN,
}


class RequirementRejectionReason(StrEnum):
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    INVALID_CATEGORY = "INVALID_CATEGORY"
    EMPTY_STATEMENT = "EMPTY_STATEMENT"
    EMPTY_SUBJECT = "EMPTY_SUBJECT"
    EMPTY_EXCERPT = "EMPTY_EXCERPT"
    ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"


class WeightRejectionReason(StrEnum):
    """Why a proposed official weight was dropped to None."""

    WEIGHT_NOT_IN_OFFICIAL_TEXT = "WEIGHT_NOT_IN_OFFICIAL_TEXT"
    WEIGHT_NOT_NUMERIC = "WEIGHT_NOT_NUMERIC"
    WEIGHT_NOT_ALLOWED_FOR_CATEGORY = "WEIGHT_NOT_ALLOWED_FOR_CATEGORY"


class CandidateOfficialRequirement(ModelFacingModel):
    """Model-facing DTO. Untrusted until its excerpt verifies in the snapshot."""

    category: str = Field(description="One of the OfficialRequirementCategory values.")
    subject: str = Field(description="Short English label of what the rule is about.")
    statement: str = Field(description="The requirement, as the official page states it.")
    excerpt: str = Field(description="Verbatim quote from the official page text.")
    official_weight_text: str | None = Field(
        default=None,
        description="The weight exactly as written in the excerpt, e.g. '20%'. "
        "Null unless the official text explicitly states a weight.",
    )
    stated_date_text: str | None = Field(
        default=None, description="A date exactly as written in the excerpt, or null."
    )


class OfficialRequirementsExtraction(ModelFacingModel):
    requirements: list[CandidateOfficialRequirement] = Field(default_factory=list)


class OfficialRequirement(MawhibaModel):
    """An anchor-verified official requirement. The statement is the source span."""

    requirement_id: UUID = Field(default_factory=uuid4)
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    snapshot_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    category: OfficialRequirementCategory
    subject: str = Field(min_length=1)
    statement: str = Field(min_length=1, description="The verified official excerpt.")
    model_summary: str | None = Field(default=None, description="Derived, never canonical.")
    anchor: VerifiedAnchor
    official_weight: float | None = Field(default=None, ge=0.0)
    official_weight_text: str | None = None
    weight_rejection: WeightRejectionReason | None = None
    stated_date_text: str | None = None
    competition_edition: int | None = Field(
        default=None, ge=MIN_COMPETITION_EDITION, le=MAX_COMPETITION_EDITION
    )
    authority: CriteriaAuthority = CriteriaAuthority.OFFICIAL_MAWHIBA_CRITERIA
    status: OfficialRequirementStatus
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def _weights_are_never_invented(self) -> OfficialRequirement:
        if not self.anchor.verified:
            raise ValueError("an official requirement requires a verified anchor")
        if self.authority is not CriteriaAuthority.OFFICIAL_MAWHIBA_CRITERIA:
            raise ValueError("an official requirement cannot carry advisory authority")
        if self.status is OfficialRequirementStatus.UNVERIFIED:
            raise ValueError("an accepted requirement cannot be UNVERIFIED")
        if self.official_weight is not None:
            if self.category not in WEIGHT_BEARING_CATEGORIES:
                raise ValueError("official_weight is only valid for judging/scoring criteria")
            if not self.official_weight_text or (
                self.official_weight_text.casefold() not in self.statement.casefold()
            ):
                raise ValueError(
                    "official_weight requires its text to appear in the verified official "
                    "statement; weights are never invented (N03)"
                )
        if self.stated_date_text and self.stated_date_text.casefold() not in self.statement.casefold():
            raise ValueError("stated_date_text must appear in the verified statement")
        return self

    @property
    def is_applicable(self) -> bool:
        return self.status in APPLICABLE_REQUIREMENT_STATUSES


class RejectedOfficialRequirement(MawhibaModel):
    """Audit record of a candidate requirement deterministic code refused."""

    source_id: str
    candidate_category: str
    candidate_statement: str
    candidate_excerpt: str
    rejection_reason: RequirementRejectionReason


class ConflictResolutionBasis(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    NEWER_COMPETITION_EDITION = "NEWER_COMPETITION_EDITION"
    NEWER_EFFECTIVE_DATE = "NEWER_EFFECTIVE_DATE"
    NEWER_PUBLICATION_DATE = "NEWER_PUBLICATION_DATE"


class ConflictSide(MawhibaModel):
    requirement_id: UUID
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    statement: str
    official_weight: float | None = None
    competition_edition: int | None = Field(
        default=None, ge=MIN_COMPETITION_EDITION, le=MAX_COMPETITION_EDITION
    )
    effective_at: UtcDatetime | None = None
    published_at: UtcDatetime | None = None


class OfficialRequirementConflict(MawhibaModel):
    """Two official sources disagree. Both sides are always preserved."""

    conflict_id: UUID = Field(default_factory=uuid4)
    category: OfficialRequirementCategory
    subject: str = Field(min_length=1)
    sides: list[ConflictSide] = Field(min_length=2)
    resolution_basis: ConflictResolutionBasis = ConflictResolutionBasis.UNRESOLVED
    preferred_requirement_id: UUID | None = None

    @model_validator(mode="after")
    def _resolution_is_explicit(self) -> OfficialRequirementConflict:
        if len({side.source_id for side in self.sides}) < 2:
            raise ValueError("a conflict needs sides from at least two sources")
        unresolved = self.resolution_basis is ConflictResolutionBasis.UNRESOLVED
        if unresolved != (self.preferred_requirement_id is None):
            raise ValueError("only a resolved conflict names a preferred requirement")
        if self.preferred_requirement_id is not None and self.preferred_requirement_id not in {
            side.requirement_id for side in self.sides
        }:
            raise ValueError("the preferred requirement must be one of the sides")
        return self


class OfficialRequirementsOutcome(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    OFFICIAL_REQUIREMENTS_VERIFIED = "OFFICIAL_REQUIREMENTS_VERIFIED"
    OFFICIAL_REQUIREMENTS_UNAVAILABLE = "OFFICIAL_REQUIREMENTS_UNAVAILABLE"
    OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED = "OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED"


class OfficialRequirementsResult(MawhibaModel):
    """Everything the OFFICIAL_REQUIREMENTS branch produced in one research run."""

    outcome: OfficialRequirementsOutcome = OfficialRequirementsOutcome.NOT_STARTED
    seeds: list[OfficialSeed] = Field(default_factory=list)
    target_edition: int | None = Field(
        default=None,
        ge=MIN_COMPETITION_EDITION,
        le=MAX_COMPETITION_EDITION,
        description="The competition edition being evaluated, if configured. Never "
        "inferred from the retrieval date.",
    )
    web_provider: str | None = None
    candidates: list[SourceCandidate] = Field(default_factory=list)
    decisions: list[SourceVerificationDecision] = Field(default_factory=list)
    snapshots: list[OfficialSourceSnapshot] = Field(default_factory=list)
    verified_sources: list[SourceRecord] = Field(default_factory=list)
    requirements: list[OfficialRequirement] = Field(default_factory=list)
    rejected_requirements: list[RejectedOfficialRequirement] = Field(default_factory=list)
    conflicts: list[OfficialRequirementConflict] = Field(default_factory=list)
    extractor_prompt_version: str | None = None
    extraction_provider: str | None = None
    extraction_model: str | None = None

    @model_validator(mode="after")
    def _outcome_matches_content(self) -> OfficialRequirementsResult:
        outcome = self.outcome
        if outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED and not self.snapshots:
            raise ValueError("VERIFIED requires at least one verified snapshot")
        if outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_UNAVAILABLE and (
            self.snapshots or self.requirements
        ):
            raise ValueError("UNAVAILABLE must not carry snapshots or requirements")
        if outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED and (
            not self.snapshots or self.requirements
        ):
            raise ValueError("EXTRACTION_FAILED keeps snapshots and carries no requirements")

        snapshot_ids = [s.source_id for s in self.snapshots]
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("snapshot source_ids must be unique")
        if sorted(snapshot_ids) != sorted(s.source_id for s in self.verified_sources):
            raise ValueError("every snapshot has exactly one verified SourceRecord")
        if any(r.source_id not in snapshot_ids for r in self.requirements):
            raise ValueError("a requirement references an unknown snapshot")
        return self

    @property
    def seed_urls(self) -> list[str]:
        return [seed.url for seed in self.seeds]

    @property
    def official_requirements_checked(self) -> bool:
        """True only when official content was actually retrieved and verified."""
        return self.outcome is OfficialRequirementsOutcome.OFFICIAL_REQUIREMENTS_VERIFIED

    @property
    def applicable_requirements(self) -> list[OfficialRequirement]:
        """Current-edition and evergreen requirements. Historical ones are kept
        in ``requirements`` but never applied."""
        return [r for r in self.requirements if r.is_applicable]

    def snapshot_for(self, source_id: str) -> OfficialSourceSnapshot | None:
        return next((s for s in self.snapshots if s.source_id == source_id), None)
