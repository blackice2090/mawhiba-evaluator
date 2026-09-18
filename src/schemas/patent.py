"""Patent prior-art research contracts -- Phase 2G (ADR-018).

The trust progression is explicit in the types, exactly as Phase 2B made it
explicit for academic retrieval:

    provider XML                  untrusted, never read directly by anything
    PatentSearchObservation       ONE provider's observation of ONE publication
    VerifiedPatentPublication     ONE publication, with EVERY observation kept
    PatentFamilyGroup             ONE invention family over its publications
    PatentPriorArtCandidate       a research candidate for LATER comparison

Nothing here is a novelty judgement, a patentability opinion, an infringement or
freedom-to-operate opinion, or a legal prior-art ruling. Those are outside this
system or belong to a later, separately reviewed phase (ADR-018). The vocabulary
is deliberately built so that such a conclusion cannot be *expressed*: there is
no ``novelty_score``, no ``SAME_INVENTION``, no ``INVALIDATING`` and no field
that could hold one.

Five distinctions this module refuses to collapse:

* **search hit vs verified publication**. A provider record becomes a
  ``VerifiedPatentPublication`` only after deterministic checks pass.
* **publication identity vs family identity**. ``US1234567.A1`` and
  ``US1234567.B2`` are different publications of possibly one invention; one
  family with five members is one invention, not five.
* **priority date vs publication date**. A priority date is family chronology.
  It is never evidence that anything was publicly available on that day.
* **provider rank vs relevance vs novelty**. A provider's ordering is retrieval
  metadata. It is not a similarity score and emphatically not a novelty score.
* **bounded search vs exhaustive search**. A completed Phase 2G run searched
  what its budget allowed, and says so.
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
    UtcDatetime,
)
from src.schemas.source import (
    SourceFingerprint,
    SourceIdentifierKind,
    SourceProvider,
    SourceRecord,
    SourceTier,
    SourceType,
    VerificationStatus,
)

PATENT_CONTRACT_VERSION = "PATENT-CONTRACT-V1"
PATENT_NORMALIZER_VERSION = "PATENT-NORMALIZER-V1"
PATENT_IDENTITY_VERSION = "PATENT-PUBLICATION-IDENTITY-V1"
PATENT_DEDUP_VERSION = "PATENT-DEDUP-V1"
PATENT_FAMILY_VERSION = "PATENT-FAMILY-RESOLUTION-V1"
PATENT_PLANNER_VERSION = "PATENT-QUERY-PLAN-V1"
PATENT_CHRONOLOGY_VERSION = "PATENT-CHRONOLOGY-V1"

PATENT_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
AUTHORITY_PATTERN = r"^[A-Z]{2}$"
PUBLICATION_NUMBER_PATTERN = r"^[A-Z0-9]{1,20}$"
KIND_CODE_PATTERN = r"^[A-Z][0-9]?$"
FAMILY_ID_PATTERN = r"^[0-9]{1,20}$"
CLASSIFICATION_PATTERN = r"^[A-H|Y][0-9]{2}[A-Z](?:[0-9]{1,4}(?:/[0-9]{1,6})?)?$"
CONTENT_HASH_PATTERN = r"^[0-9a-f]{64}$"
LANGUAGE_PATTERN = r"^[a-z]{2}$"

MAX_SAFE_SUMMARY_LENGTH = 200
"""Ledger summaries are bounded: an audit trail is not a second copy of the
provider response."""

MAX_PATENT_TEXT_CHARS = 200_000
"""A description can be enormous. Stored text is bounded and truncation is
recorded on the snapshot rather than applied silently."""


class PatentFacingModel(BaseModel):
    """Base for a provider response DTO. Untrusted input, never canonical state.

    ``extra="ignore"`` for the same reason Phase 2B ignores unknown academic
    keys: a patent office adds elements without warning, and a connector that
    breaks on an unknown element is a connector that breaks in production.
    Ignoring is not trusting -- every field this project uses is declared, typed
    and re-validated by code that does not belong to the provider.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Providers and access policy
# ---------------------------------------------------------------------------


class PatentProvider(StrEnum):
    """Patent data providers Phase 2G knows about.

    Being a member is not a claim that the provider is implemented, reachable or
    permitted: ``PatentProviderAccessStatus`` states that separately, and
    ``WIPO_PATENTSCOPE`` is a member precisely so the system can record that its
    public search service must never be automated.
    """

    EPO_OPS = "EPO_OPS"
    USPTO_ODP = "USPTO_ODP"
    WIPO_PATENTSCOPE = "WIPO_PATENTSCOPE"


PATENT_PROVIDER_ORDER: tuple[PatentProvider, ...] = (
    PatentProvider.EPO_OPS,
    PatentProvider.USPTO_ODP,
    PatentProvider.WIPO_PATENTSCOPE,
)
"""Deterministic dispatch and tie-break order. Not a quality ranking."""

PATENT_TO_SOURCE_PROVIDER: dict[PatentProvider, SourceProvider] = {
    PatentProvider.EPO_OPS: SourceProvider.EPO_OPS,
    PatentProvider.USPTO_ODP: SourceProvider.USPTO,
    PatentProvider.WIPO_PATENTSCOPE: SourceProvider.WIPO_PATENTSCOPE,
}


class PatentProviderAccessStatus(StrEnum):
    """How honestly a provider may be described (section 2, "provider honesty").

    ``IMPLEMENTED_AND_LIVE_VERIFIED`` requires that a real authenticated request
    was actually executed successfully. A connector whose contract was verified
    only from documentation is ``IMPLEMENTED_DOCUMENTED_ONLY`` and must never be
    reported as live-tested.
    """

    IMPLEMENTED_AND_LIVE_VERIFIED = "IMPLEMENTED_AND_LIVE_VERIFIED"
    IMPLEMENTED_DOCUMENTED_ONLY = "IMPLEMENTED_DOCUMENTED_ONLY"
    DEFERRED = "DEFERRED"
    UNSUPPORTED_BY_ACCESS_POLICY = "UNSUPPORTED_BY_ACCESS_POLICY"


IMPLEMENTED_ACCESS_STATUSES: frozenset[PatentProviderAccessStatus] = frozenset(
    {
        PatentProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED,
        PatentProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    }
)
"""The only statuses a dispatchable connector may carry."""


class PatentProviderOperation(StrEnum):
    """One capability a patent provider may or may not expose.

    Declared per provider rather than assumed, because "this office does not
    publish claims through this service" and "we did not ask" are different
    facts, and only the second is a defect.
    """

    SEARCH_PUBLICATIONS = "SEARCH_PUBLICATIONS"
    FETCH_BIBLIOGRAPHIC = "FETCH_BIBLIOGRAPHIC"
    FETCH_FAMILY = "FETCH_FAMILY"
    FETCH_ABSTRACT = "FETCH_ABSTRACT"
    FETCH_CLAIMS = "FETCH_CLAIMS"
    FETCH_DESCRIPTION = "FETCH_DESCRIPTION"
    FETCH_LEGAL_STATUS = "FETCH_LEGAL_STATUS"


class PatentProviderCapability(MawhibaModel):
    """What one provider supports, and on what documented authority.

    ``documentation_url`` and ``contract_verified_on`` are required because the
    provider-contract gate (section 2) is a standing obligation, not a one-off:
    a reader must be able to see which document a connector was built against
    and when that was checked.
    """

    provider: PatentProvider
    access_status: PatentProviderAccessStatus
    documentation_url: str = Field(min_length=1)
    contract_verified_on: str = Field(pattern=PATENT_DATE_PATTERN)
    authentication: str = Field(min_length=1)
    response_format: str = Field(min_length=1)
    operations: list[PatentProviderOperation] = Field(default_factory=list)
    live_request_observed: bool = Field(
        default=False,
        description="True only when a real authenticated request succeeded. An "
        "unauthenticated probe of a fault response is not a live verification.",
    )
    notes: str = ""

    @model_validator(mode="after")
    def _honesty_holds(self) -> PatentProviderCapability:
        live = self.access_status is PatentProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED
        if live and not self.live_request_observed:
            raise ValueError(
                "IMPLEMENTED_AND_LIVE_VERIFIED requires an observed live request"
            )
        if self.live_request_observed and not live:
            raise ValueError(
                "a provider with an observed live request must be reported as "
                "IMPLEMENTED_AND_LIVE_VERIFIED"
            )
        if (
            self.access_status is PatentProviderAccessStatus.UNSUPPORTED_BY_ACCESS_POLICY
            and self.operations
        ):
            raise ValueError(
                "a provider unsupported by access policy exposes no operations "
                "to this system"
            )
        return self

    def supports(self, operation: PatentProviderOperation) -> bool:
        return operation in self.operations

    @property
    def dispatchable(self) -> bool:
        return (
            self.access_status in IMPLEMENTED_ACCESS_STATUSES
            and PatentProviderOperation.SEARCH_PUBLICATIONS in self.operations
        )


# ---------------------------------------------------------------------------
# Query planning vocabulary
# ---------------------------------------------------------------------------


class PatentSearchStrategy(StrEnum):
    """*How* a patent query looks for prior disclosures.

    Deliberately a second, orthogonal dimension beside ``QueryPurpose`` rather
    than a competing copy of it (ADR-018). ``QueryPurpose`` answers *why* the
    system searched -- it is reused unchanged, with the PATENT branch's existing
    members. A strategy answers *how the query was shaped*, which is what makes
    the anti-confirmation-bias requirement (section 10) checkable: a plan of
    eight ``PRIOR_ART`` queries that are all exact student wording is a biased
    plan, and only the strategy dimension can show that.
    """

    EXACT_TECHNICAL_PHRASE = "EXACT_TECHNICAL_PHRASE"
    CORE_TECHNICAL_CONCEPT = "CORE_TECHNICAL_CONCEPT"
    MECHANISM_FUNCTION = "MECHANISM_FUNCTION"
    COMPONENT_COMBINATION = "COMPONENT_COMBINATION"
    SYNONYM_VARIANT = "SYNONYM_VARIANT"
    BROADER_TECHNICAL_TERMS = "BROADER_TECHNICAL_TERMS"
    CLASSIFICATION_EXPANSION = "CLASSIFICATION_EXPANSION"
    KNOWN_IDENTIFIER_LOOKUP = "KNOWN_IDENTIFIER_LOOKUP"


NON_LITERAL_STRATEGIES: frozenset[PatentSearchStrategy] = frozenset(
    {
        PatentSearchStrategy.MECHANISM_FUNCTION,
        PatentSearchStrategy.SYNONYM_VARIANT,
        PatentSearchStrategy.BROADER_TECHNICAL_TERMS,
        PatentSearchStrategy.COMPONENT_COMBINATION,
        PatentSearchStrategy.CLASSIFICATION_EXPANSION,
    }
)
"""Strategies that look beyond the student's own wording.

A plan with none of these searched only what the student wrote, which is the
confirmation-bias failure section 10 forbids.
"""

PATENT_SEARCH_PURPOSES: frozenset[QueryPurpose] = frozenset(
    {
        QueryPurpose.PRIOR_ART,
        QueryPurpose.PATENT_FUNCTION,
        QueryPurpose.PATENT_MECHANISM,
        QueryPurpose.EXISTING_SOLUTIONS,
        QueryPurpose.ALTERNATIVES,
    }
)
"""The only purposes that reach a patent connector.

Identical to the PATENT entry of ``ALLOWED_PURPOSES_BY_BRANCH`` in
``src.research.query_verification``: the branch vocabulary is reused, not
re-invented.
"""


class PatentQueryDerivation(StrEnum):
    """Where a query's search terms came from.

    ``MODEL_ASSISTED_TRANSLATION`` and ``MODEL_ASSISTED_EXPANSION`` mark the only
    two paths where an untrusted model contributed vocabulary (section 11). They
    exist so a reader can tell a student's own words from a model's suggestion
    without re-reading the prompt.
    """

    CANONICAL_PROJECT_TEXT = "CANONICAL_PROJECT_TEXT"
    DETERMINISTIC_EXPANSION = "DETERMINISTIC_EXPANSION"
    MODEL_ASSISTED_TRANSLATION = "MODEL_ASSISTED_TRANSLATION"
    MODEL_ASSISTED_EXPANSION = "MODEL_ASSISTED_EXPANSION"
    VERIFIED_CLASSIFICATION = "VERIFIED_CLASSIFICATION"
    KNOWN_PUBLICATION_IDENTIFIER = "KNOWN_PUBLICATION_IDENTIFIER"


MODEL_ASSISTED_DERIVATIONS: frozenset[PatentQueryDerivation] = frozenset(
    {
        PatentQueryDerivation.MODEL_ASSISTED_TRANSLATION,
        PatentQueryDerivation.MODEL_ASSISTED_EXPANSION,
    }
)


class PatentQueryRejectionReason(StrEnum):
    """Why a patent query was refused before it could reach a provider.

    Every one of these is a *refusal*, recorded with the query it refused, so
    "we did not search for that" is always answerable with a machine-readable
    reason (section 6).
    """

    EMPTY_QUERY = "EMPTY_QUERY"
    QUERY_TOO_LONG = "QUERY_TOO_LONG"
    INVALID_QUERY_SYNTAX = "INVALID_QUERY_SYNTAX"
    UNSUPPORTED_QUERY_FIELD = "UNSUPPORTED_QUERY_FIELD"
    UNBALANCED_QUOTES = "UNBALANCED_QUOTES"
    UNBALANCED_PARENTHESES = "UNBALANCED_PARENTHESES"
    FORBIDDEN_QUERY_CHARACTER = "FORBIDDEN_QUERY_CHARACTER"
    PII_DETECTED = "PII_DETECTED"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"
    UNTRACEABLE_QUERY_TERM = "UNTRACEABLE_QUERY_TERM"
    DUPLICATE_QUERY = "DUPLICATE_QUERY"
    QUERY_BUDGET_EXCEEDED = "QUERY_BUDGET_EXCEEDED"
    NOT_PATENT_BRANCH = "NOT_PATENT_BRANCH"
    PURPOSE_NOT_ROUTED_TO_PATENT = "PURPOSE_NOT_ROUTED_TO_PATENT"
    PROVIDER_NOT_DISPATCHABLE = "PROVIDER_NOT_DISPATCHABLE"
    CLASSIFICATION_EXPANSION_CAP_REACHED = "CLASSIFICATION_EXPANSION_CAP_REACHED"


PII_SENSITIVE_REJECTIONS: frozenset[PatentQueryRejectionReason] = frozenset(
    {PatentQueryRejectionReason.PII_DETECTED}
)


class PatentClaimExclusionReason(StrEnum):
    """Why a claim or claim component got no patent query at all.

    Section 6 requires an explicit machine-readable reason for every exclusion,
    and forbids the two reasons a reader might expect: low evidence support and
    a low Phase 2F score are not on this list and cannot be expressed.
    """

    NO_TECHNICAL_CONTENT = "NO_TECHNICAL_CONTENT"
    CLAIM_TEXT_EMPTY = "CLAIM_TEXT_EMPTY"
    PII_DETECTED = "PII_DETECTED"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"
    NO_SEARCHABLE_TERMS = "NO_SEARCHABLE_TERMS"
    TRANSLATION_UNAVAILABLE = "TRANSLATION_UNAVAILABLE"
    CLAIM_BUDGET_EXCEEDED = "CLAIM_BUDGET_EXCEEDED"


# ---------------------------------------------------------------------------
# Search outcome vocabulary
# ---------------------------------------------------------------------------


class PatentSearchStatus(StrEnum):
    """Outcome of ONE provider answering ONE query.

    ``EMPTY`` is deliberately not a failure, for the same reason as Phase 2B:
    "worked, found nothing" and "could not be asked" lead to opposite research
    conclusions, and for a patent search the difference is decisive.
    """

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_QUERY = "INVALID_QUERY"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    TIMEOUT = "TIMEOUT"


SUCCESSFUL_PATENT_STATUSES: frozenset[PatentSearchStatus] = frozenset(
    {PatentSearchStatus.SUCCESS, PatentSearchStatus.PARTIAL}
)

EXECUTED_PATENT_STATUSES: frozenset[PatentSearchStatus] = frozenset(
    {*SUCCESSFUL_PATENT_STATUSES, PatentSearchStatus.EMPTY}
)
"""Statuses where the provider actually answered."""


class PatentErrorKind(StrEnum):
    """Why one provider attempt failed. Retryability is a property of the kind."""

    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    FORBIDDEN = "FORBIDDEN"
    FAIR_USE_REJECTED = "FAIR_USE_REJECTED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_QUERY = "INVALID_QUERY"
    PARSE_ERROR = "PARSE_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    UNEXPECTED = "UNEXPECTED"


RETRYABLE_PATENT_ERROR_KINDS: frozenset[PatentErrorKind] = frozenset(
    {
        PatentErrorKind.TIMEOUT,
        PatentErrorKind.CONNECTION_ERROR,
        PatentErrorKind.RATE_LIMITED,
        PatentErrorKind.SERVER_ERROR,
    }
)
"""Transport faults and explicit back-pressure only.

``INVALID_QUERY`` is deliberately absent (section 28): a deterministically
malformed CQL expression produces the identical failure on every attempt, so
retrying it is a guaranteed-useless third-party request.

``FAIR_USE_REJECTED`` is also absent. EPO OPS answers a quota violation with
403 and an ``X-Rejection-Reason`` header; retrying inside the same run would be
evading a documented limit rather than recovering from a fault (section 27).
"""

PATENT_ERROR_TO_SEARCH_STATUS: dict[PatentErrorKind, PatentSearchStatus] = {
    PatentErrorKind.TIMEOUT: PatentSearchStatus.TIMEOUT,
    PatentErrorKind.CONNECTION_ERROR: PatentSearchStatus.PROVIDER_ERROR,
    PatentErrorKind.RATE_LIMITED: PatentSearchStatus.RATE_LIMITED,
    PatentErrorKind.SERVER_ERROR: PatentSearchStatus.PROVIDER_ERROR,
    PatentErrorKind.AUTHENTICATION_ERROR: PatentSearchStatus.AUTH_ERROR,
    PatentErrorKind.FORBIDDEN: PatentSearchStatus.AUTH_ERROR,
    PatentErrorKind.FAIR_USE_REJECTED: PatentSearchStatus.RATE_LIMITED,
    PatentErrorKind.NOT_FOUND: PatentSearchStatus.PROVIDER_ERROR,
    PatentErrorKind.INVALID_QUERY: PatentSearchStatus.INVALID_QUERY,
    PatentErrorKind.PARSE_ERROR: PatentSearchStatus.INVALID_RESPONSE,
    PatentErrorKind.PROVIDER_ERROR: PatentSearchStatus.PROVIDER_ERROR,
    PatentErrorKind.UNSUPPORTED_OPERATION: PatentSearchStatus.UNSUPPORTED_OPERATION,
    PatentErrorKind.UNEXPECTED: PatentSearchStatus.PROVIDER_ERROR,
}


class PatentSearchCoverageStatus(StrEnum):
    """How much of the intended search actually happened (section 13).

    ``COMPLETE_WITHIN_CONFIGURED_BOUNDS`` is the strongest statement this phase
    can make, and it says exactly what it means: every planned query ran inside
    its budget. It is **not** a claim that all relevant patents were found, and
    no member of this enum can express that claim.
    """

    NOT_EXECUTED = "NOT_EXECUTED"
    COMPLETE_WITHIN_CONFIGURED_BOUNDS = "COMPLETE_WITHIN_CONFIGURED_BOUNDS"
    PARTIAL_PROVIDER_LIMIT = "PARTIAL_PROVIDER_LIMIT"
    PARTIAL_ERROR = "PARTIAL_ERROR"
    BLOCKED_AUTH = "BLOCKED_AUTH"


PARTIAL_COVERAGE_STATUSES: frozenset[PatentSearchCoverageStatus] = frozenset(
    {
        PatentSearchCoverageStatus.PARTIAL_PROVIDER_LIMIT,
        PatentSearchCoverageStatus.PARTIAL_ERROR,
        PatentSearchCoverageStatus.BLOCKED_AUTH,
    }
)


class PatentBranchOutcome(StrEnum):
    """Aggregate verdict for the PATENT branch.

    One provider failing never downgrades this past ``PARTIAL`` while another
    provider's results survive (the Phase 2B isolation rule, ADR-008).
    """

    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class PatentRejectionReason(StrEnum):
    """Why one provider record did not become, or stay, a verified publication."""

    MALFORMED_RECORD = "MALFORMED_RECORD"
    MISSING_PUBLICATION_IDENTITY = "MISSING_PUBLICATION_IDENTITY"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"
    INVALID_PUBLICATION_NUMBER = "INVALID_PUBLICATION_NUMBER"
    INVALID_KIND_CODE = "INVALID_KIND_CODE"
    MISSING_TITLE = "MISSING_TITLE"
    INVALID_DATE_FORMAT = "INVALID_DATE_FORMAT"
    INCONSISTENT_DATE_ORDER = "INCONSISTENT_DATE_ORDER"
    INVALID_CLASSIFICATION = "INVALID_CLASSIFICATION"
    INVALID_FAMILY_IDENTIFIER = "INVALID_FAMILY_IDENTIFIER"
    DUPLICATE_PROVIDER_RECORD = "DUPLICATE_PROVIDER_RECORD"
    PROVIDER_RESULT_LIMIT_EXCEEDED = "PROVIDER_RESULT_LIMIT_EXCEEDED"
    TOTAL_RESULT_LIMIT_EXCEEDED = "TOTAL_RESULT_LIMIT_EXCEEDED"
    VERIFIED_PUBLICATION_LIMIT_EXCEEDED = "VERIFIED_PUBLICATION_LIMIT_EXCEEDED"
    CROSS_RUN_RECORD = "CROSS_RUN_RECORD"
    UNKNOWN_QUERY_REFERENCE = "UNKNOWN_QUERY_REFERENCE"
    PII_DETECTED = "PII_DETECTED"


BUDGET_PATENT_REJECTIONS: frozenset[PatentRejectionReason] = frozenset(
    {
        PatentRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED,
        PatentRejectionReason.TOTAL_RESULT_LIMIT_EXCEEDED,
        PatentRejectionReason.VERIFIED_PUBLICATION_LIMIT_EXCEEDED,
    }
)
"""Budget truncation: recorded, auditable, and never a provider failure."""


class PatentRejectionStage(StrEnum):
    NORMALIZATION = "NORMALIZATION"
    BUDGET = "BUDGET"
    VERIFICATION = "VERIFICATION"
    FAMILY_RESOLUTION = "FAMILY_RESOLUTION"


# ---------------------------------------------------------------------------
# Publication identity (sections 15, 16)
# ---------------------------------------------------------------------------


class PublicationIdentity(MawhibaModel):
    """Canonical identity of ONE patent publication.

    DOCDB-shaped: authority, document number, kind code. The kind code is part
    of the identity on purpose (section 16) -- ``US9999999.A1`` is the
    application publication and ``US9999999.B2`` the grant, and collapsing them
    would make one document look like corroboration of the other.

    A missing kind code is represented as ``None`` and kept distinct from every
    present kind code: it means the provider did not state one, never that the
    publication has none. Two records that differ only in that one states ``A1``
    and the other states nothing are therefore *not* merged.

    Title is absent and unrepresentable here, which is what makes title-only
    publication identity impossible to express (section 15).
    """

    authority: str = Field(
        pattern=AUTHORITY_PATTERN,
        description="Two-letter publishing authority code, e.g. EP, US, WO, SA.",
    )
    number: str = Field(
        pattern=PUBLICATION_NUMBER_PATTERN,
        description="Document number, normalized: upper case, separators removed.",
    )
    kind_code: str | None = Field(
        default=None,
        pattern=KIND_CODE_PATTERN,
        description="None means the provider stated no kind code. Never coerced.",
    )

    @property
    def canonical_key(self) -> str:
        """The deterministic, reproducible identity string.

        ``.-`` marks an absent kind code rather than omitting the segment, so an
        unknown kind can never collide with a stated one.
        """
        return f"{self.authority}.{self.number}.{self.kind_code or '-'}"

    @property
    def docdb_reference(self) -> str:
        """The DOCDB reference form EPO OPS accepts, e.g. ``EP.1000000.A1``."""
        return self.canonical_key if self.kind_code else f"{self.authority}.{self.number}"

    @property
    def epodoc_reference(self) -> str:
        """The EPODOC reference form, e.g. ``EP1000000A1``."""
        return f"{self.authority}{self.number}{self.kind_code or ''}"

    def same_publication(self, other: PublicationIdentity) -> bool:
        return self.canonical_key == other.canonical_key

    def fingerprint(self, content_hash: str | None = None) -> SourceFingerprint:
        return SourceFingerprint.create(
            SourceIdentifierKind.PATENT_PUBLICATION_NUMBER,
            self.canonical_key,
            content_hash,
        )


# ---------------------------------------------------------------------------
# Dates and chronology (sections 8, 9)
# ---------------------------------------------------------------------------


class PatentDateSet(MawhibaModel):
    """The four patent dates, kept strictly distinct (section 8).

    There is deliberately no ``date`` field and no "effective date": every
    consumer must name which chronology it means, because substituting one for
    another is exactly the error this phase is built to prevent.
    """

    earliest_priority_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)
    filing_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)
    publication_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)
    grant_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)

    @model_validator(mode="after")
    def _chronology_is_possible(self) -> PatentDateSet:
        """Reject an impossible ordering rather than silently storing it.

        Only orderings that cannot occur are rejected: a priority date after the
        filing date of the same document, a publication before filing, or a
        grant before publication. Equal dates are allowed -- same-day filing and
        priority is ordinary for a first filing.
        """
        if (
            self.earliest_priority_date
            and self.filing_date
            and self.earliest_priority_date > self.filing_date
        ):
            raise ValueError("earliest_priority_date cannot follow filing_date")
        if (
            self.filing_date
            and self.publication_date
            and self.filing_date > self.publication_date
        ):
            raise ValueError("filing_date cannot follow publication_date")
        if (
            self.publication_date
            and self.grant_date
            and self.publication_date > self.grant_date
        ):
            raise ValueError("publication_date cannot follow grant_date")
        return self

    @property
    def first_public_date(self) -> str | None:
        """The earliest date this record shows the document was public.

        The publication date when there is one; the grant date only when there
        is no earlier publication (section 8). A priority date and a filing date
        are never returned here: neither is evidence of public availability.
        """
        return self.publication_date or self.grant_date

    @property
    def has_public_date(self) -> bool:
        return self.first_public_date is not None


class PatentTimeQualification(StrEnum):
    """Descriptive chronology against an optionally supplied cutoff (section 9).

    Every member is a statement about *dates*. None of them is a legal
    determination, and the three names the specification forbids --
    ``LEGAL_PRIOR_ART``, ``INVALIDATING_PRIOR_ART``, ``NOVELTY_DESTROYING`` --
    are absent and must stay absent: a later phase may reason about novelty, but
    it may not do so by reading a label this phase invented (ADR-018).
    """

    PUBLIC_BEFORE_CUTOFF = "PUBLIC_BEFORE_CUTOFF"
    PUBLIC_ON_CUTOFF = "PUBLIC_ON_CUTOFF"
    PUBLIC_AFTER_CUTOFF = "PUBLIC_AFTER_CUTOFF"
    PUBLICATION_DATE_UNKNOWN = "PUBLICATION_DATE_UNKNOWN"
    NO_CUTOFF = "NO_CUTOFF"


CUTOFF_RELATIVE_QUALIFICATIONS: frozenset[PatentTimeQualification] = frozenset(
    {
        PatentTimeQualification.PUBLIC_BEFORE_CUTOFF,
        PatentTimeQualification.PUBLIC_ON_CUTOFF,
        PatentTimeQualification.PUBLIC_AFTER_CUTOFF,
    }
)
"""Qualifications that require a cutoff to have been supplied.

A run with no cutoff can only produce ``NO_CUTOFF``, which is what stops the
system quietly substituting today's date, the submission date or a priority
date for a cutoff nobody gave it (section 7).
"""


class PatentSearchCutoff(MawhibaModel):
    """An explicitly supplied evaluation cutoff, or the absence of one.

    ``source`` is required whenever a date is present: section 7 forbids
    inventing a cutoff, so a cutoff that cannot name the workflow contract that
    supplied it is not a cutoff.
    """

    cutoff_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)
    source: str = Field(
        default="",
        max_length=MAX_SAFE_SUMMARY_LENGTH,
        description="The calling workflow contract that supplied the date.",
    )

    @model_validator(mode="after")
    def _a_cutoff_names_its_source(self) -> PatentSearchCutoff:
        if self.cutoff_date and not self.source.strip():
            raise ValueError("a supplied cutoff date must name its source contract")
        if not self.cutoff_date and self.source.strip():
            raise ValueError("a source without a date is not a cutoff")
        return self

    @property
    def supplied(self) -> bool:
        return self.cutoff_date is not None


NO_SEARCH_CUTOFF = PatentSearchCutoff()
"""The default. Chronology is still recorded; nothing is qualified against a
cutoff that was never given."""


# ---------------------------------------------------------------------------
# Text snapshots (sections 19, 20, 21)
# ---------------------------------------------------------------------------


class PatentContentType(StrEnum):
    """Which part of a patent document a snapshot holds.

    Kept strictly distinct (section 21). A later novelty phase will weigh claims
    differently from an abstract and an abstract differently from a title, so
    these must never be interchangeable, and no code path may relabel one as
    another.
    """

    TITLE = "TITLE"
    ABSTRACT = "ABSTRACT"
    CLAIMS = "CLAIMS"
    DESCRIPTION = "DESCRIPTION"


class PatentContentAvailability(StrEnum):
    """Whether a content type could be obtained, and why not when it could not.

    ``UNKNOWN`` is first-class and is never read as favourable: "we do not know
    whether this office publishes claims here" is not "there are no claims".
    """

    AVAILABLE = "AVAILABLE"
    NOT_PUBLISHED_BY_AUTHORITY = "NOT_PUBLISHED_BY_AUTHORITY"
    NOT_SUPPORTED_BY_PROVIDER = "NOT_SUPPORTED_BY_PROVIDER"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    NOT_REQUESTED = "NOT_REQUESTED"
    UNKNOWN = "UNKNOWN"


class PatentTextScope(StrEnum):
    """How much of the content type the snapshot actually holds.

    ``TRUNCATED`` exists so a bounded description can be stored honestly instead
    of being presented as the whole document.
    """

    COMPLETE_AS_PROVIDED = "COMPLETE_AS_PROVIDED"
    TRUNCATED = "TRUNCATED"
    PARTIAL_AS_PROVIDED = "PARTIAL_AS_PROVIDED"


class PatentTextSnapshot(MawhibaModel):
    """Verbatim provider text for ONE content type of ONE publication.

    The text is stored exactly as the provider supplied it, with only whitespace
    normalization recorded by ``normalization``. It is never a machine summary:
    section 19 forbids calling a generated summary a patent abstract, and this
    contract has nowhere to put one -- there is no ``summary`` field.
    """

    snapshot_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    publication_key: str = Field(min_length=1)
    provider: PatentProvider
    content_type: PatentContentType
    language: str | None = Field(
        default=None,
        pattern=LANGUAGE_PATTERN,
        description="The language the provider declared. None means it declared "
        "none; the language is never guessed from the text.",
    )
    text: str = Field(min_length=1, max_length=MAX_PATENT_TEXT_CHARS)
    content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    scope: PatentTextScope = PatentTextScope.COMPLETE_AS_PROVIDED
    normalization: str = Field(
        default=PATENT_NORMALIZER_VERSION,
        min_length=1,
        description="Which normalization produced ``text`` from the provider "
        "bytes, so the hash is reproducible.",
    )
    provider_operation: PatentProviderOperation
    provider_endpoint: str = Field(
        min_length=1,
        description="The documented operation path this text came from. Never a "
        "URL carrying credentials.",
    )
    retrieved_at: UtcDatetime
    original_char_count: int = Field(
        ge=1, description="Characters the provider supplied, before any bounding."
    )

    @model_validator(mode="after")
    def _scope_matches_length(self) -> PatentTextSnapshot:
        truncated = len(self.text) < self.original_char_count
        if truncated and self.scope is PatentTextScope.COMPLETE_AS_PROVIDED:
            raise ValueError(
                "a snapshot shorter than the provider text cannot claim to be "
                "complete as provided"
            )
        if self.scope is PatentTextScope.TRUNCATED and not truncated:
            raise ValueError("TRUNCATED requires text shorter than the provider text")
        return self


class PatentContentReport(MawhibaModel):
    """What text exists for one publication, per content type (section 20).

    Absence is explicit. Claims being unavailable is recorded as such and never
    filled in from the title or the abstract; a candidate with nothing but a
    title says so through ``title_only``.
    """

    title: PatentContentAvailability = PatentContentAvailability.UNKNOWN
    abstract: PatentContentAvailability = PatentContentAvailability.UNKNOWN
    claims: PatentContentAvailability = PatentContentAvailability.UNKNOWN
    description: PatentContentAvailability = PatentContentAvailability.UNKNOWN

    def availability(self, content_type: PatentContentType) -> PatentContentAvailability:
        return {
            PatentContentType.TITLE: self.title,
            PatentContentType.ABSTRACT: self.abstract,
            PatentContentType.CLAIMS: self.claims,
            PatentContentType.DESCRIPTION: self.description,
        }[content_type]

    @property
    def available_types(self) -> list[PatentContentType]:
        return [
            content_type
            for content_type in PatentContentType
            if self.availability(content_type) is PatentContentAvailability.AVAILABLE
        ]

    @property
    def claims_available(self) -> bool:
        return self.claims is PatentContentAvailability.AVAILABLE

    @property
    def title_only(self) -> bool:
        return self.available_types == [PatentContentType.TITLE]


# ---------------------------------------------------------------------------
# Family (sections 17, 18)
# ---------------------------------------------------------------------------


class PatentFamilyKind(StrEnum):
    """Which family notion a provider stated, where it stated one.

    ``UNKNOWN`` is kept because a provider may return a family identifier
    without naming the family definition behind it, and guessing which one would
    silently change what "same family" means.
    """

    SIMPLE = "SIMPLE"
    EXTENDED_INPADOC = "EXTENDED_INPADOC"
    DOCDB_SIMPLE = "DOCDB_SIMPLE"
    UNKNOWN = "UNKNOWN"


class PatentFamilyStatus(StrEnum):
    """How family membership was established for one publication (section 18).

    ``FAMILY_DATA_UNAVAILABLE`` and ``FAMILY_RESOLUTION_FAILED`` are distinct on
    purpose: the provider not offering family data for an authority is not the
    same as a family call that broke, and only the second is worth retrying.
    Neither ever becomes a fabricated family.
    """

    VERIFIED_FAMILY = "VERIFIED_FAMILY"
    SINGLETON_FAMILY = "SINGLETON_FAMILY"
    FAMILY_DATA_UNAVAILABLE = "FAMILY_DATA_UNAVAILABLE"
    FAMILY_RESOLUTION_FAILED = "FAMILY_RESOLUTION_FAILED"
    NOT_REQUESTED = "NOT_REQUESTED"


RESOLVED_FAMILY_STATUSES: frozenset[PatentFamilyStatus] = frozenset(
    {PatentFamilyStatus.VERIFIED_FAMILY, PatentFamilyStatus.SINGLETON_FAMILY}
)
"""Statuses where a family identity is actually known."""


class PatentFamilyMemberRef(MawhibaModel):
    """One publication's membership in a family, as the provider reported it.

    A member reference is kept even when the member itself was never retrieved
    as a publication in this run: the family is then honestly larger than what
    was fetched, which is information a later phase needs.
    """

    publication_key: str = Field(min_length=1)
    identity: PublicationIdentity
    retrieved_in_run: bool = Field(
        default=False,
        description="True when this run holds a verified publication for the "
        "member. False means the family says it exists; nothing was fetched.",
    )
    member_publication_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)


class PatentFamilyGroup(MawhibaModel):
    """ONE patent family over its publications (section 17).

    This is the anti-inflation unit. Five members of one family are one entry
    here, so a later phase counting *inventions* counts families; and no member
    is discarded, so a later phase comparing *documents* still has all five with
    their own kind codes, dates, jurisdictions and text.

    ``family_id`` comes from the provider's family service. It is never derived
    from a title, and there is no field here that a title could be written into
    (section 17).
    """

    family_group_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    family_id: str | None = Field(
        default=None,
        pattern=FAMILY_ID_PATTERN,
        description="The provider's family identifier. None when the family "
        "could not be established; never a placeholder.",
    )
    family_kind: PatentFamilyKind = PatentFamilyKind.UNKNOWN
    status: PatentFamilyStatus
    provider: PatentProvider | None = Field(
        default=None, description="Which provider's family service stated this."
    )
    provider_operation: PatentProviderOperation | None = None
    provider_endpoint: str | None = None
    members: list[PatentFamilyMemberRef] = Field(default_factory=list)
    earliest_priority_date: str | None = Field(
        default=None,
        pattern=PATENT_DATE_PATTERN,
        description="Only when the provider supplied it. Family chronology, and "
        "explicitly not a public-availability date (section 8).",
    )
    retrieved_at: UtcDatetime | None = None
    note: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> PatentFamilyGroup:
        resolved = self.status in RESOLVED_FAMILY_STATUSES
        if resolved and not self.members:
            raise ValueError(f"{self.status.value} requires at least one member")
        if self.status is PatentFamilyStatus.VERIFIED_FAMILY:
            if self.family_id is None:
                raise ValueError("VERIFIED_FAMILY requires a provider family identifier")
            if self.provider is None:
                raise ValueError("VERIFIED_FAMILY requires the stating provider")
        if self.status is PatentFamilyStatus.SINGLETON_FAMILY and len(self.members) != 1:
            raise ValueError("a singleton family holds exactly one member")
        if not resolved and self.family_id is not None:
            raise ValueError(
                f"{self.status.value} must not carry a family identifier: unknown "
                "family membership stays unknown (section 18)"
            )
        keys = [m.publication_key for m in self.members]
        if len(set(keys)) != len(keys):
            raise ValueError("a family lists each member publication once")
        return self

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def retrieved_member_count(self) -> int:
        return sum(1 for m in self.members if m.retrieved_in_run)

    @property
    def counts_as_independent_invention(self) -> int:
        """One family is one candidate invention, however many members it has.

        A family whose identity could not be established counts as one too: it
        is a document group of unknown extent, and inflating it to its member
        count would be exactly the error section 17 forbids.
        """
        return 1


# ---------------------------------------------------------------------------
# Search input
# ---------------------------------------------------------------------------


class PatentQueryTerm(MawhibaModel):
    """One search term, with where it came from.

    ``original_text`` preserves the student's own wording even when the term
    sent to the provider is an English expansion of it (section 11). Nothing
    here is a claim mutation: the canonical claim is untouched, and this is a
    record of what was searched.
    """

    term: str = Field(min_length=1, description="The term as sent to the provider.")
    derivation: PatentQueryDerivation
    original_text: str = Field(
        default="",
        description="The canonical project text this term derives from, verbatim.",
    )
    claim_id: str | None = Field(default=None, pattern=r"^C-\d{3,}$")
    component_id: str | None = None

    @model_validator(mode="after")
    def _model_terms_keep_the_original(self) -> PatentQueryTerm:
        if self.derivation in MODEL_ASSISTED_DERIVATIONS and not self.original_text.strip():
            raise ValueError(
                "a model-assisted term must preserve the original project text "
                "it was derived from (section 11)"
            )
        return self


class PatentSearchQuery(MawhibaModel):
    """The only thing a patent connector may be asked to search for.

    Built from the project's own technical content, addressed to one provider,
    and carrying its provider-syntax expression already validated. The branch is
    pinned to PATENT and the purpose to one the PATENT branch allows, so a query
    from another branch cannot reach a patent connector even by mistake.
    """

    research_run_id: UUID
    query_id: UUID = Field(default_factory=uuid4)
    branch: ResearchBranch = ResearchBranch.PATENT
    purpose: QueryPurpose
    strategy: PatentSearchStrategy
    provider: PatentProvider
    query_expression: str = Field(
        min_length=1,
        description="The provider-syntax expression, already validated against "
        "that provider's documented query language.",
    )
    normalized_expression: str = Field(
        min_length=1, description="Folded form, for duplicate detection only."
    )
    terms: list[PatentQueryTerm] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    requested_range_start: int = Field(default=1, ge=1)
    requested_limit: int = Field(ge=1, le=100)
    planner_version: str = Field(default=PATENT_PLANNER_VERSION, min_length=1)

    @model_validator(mode="after")
    def _patent_branch_only(self) -> PatentSearchQuery:
        if self.branch is not ResearchBranch.PATENT:
            raise ValueError("a patent search query must carry branch=PATENT")
        if self.purpose not in PATENT_SEARCH_PURPOSES:
            raise ValueError(f"{self.purpose.value} is not routed to patent providers")
        return self

    @property
    def stable_key(self) -> str:
        """Identity of the *intent* of this query, independent of its UUID.

        Section 29: a stable plan must produce stable query identities, so a
        resumed run recognizes a query it already executed instead of paying for
        it twice.
        """
        return (
            f"{self.provider.value}|{self.purpose.value}|{self.strategy.value}|"
            f"{self.normalized_expression}|{self.requested_range_start}|"
            f"{self.requested_limit}"
        )

    @property
    def uses_model_assisted_terms(self) -> bool:
        return any(t.derivation in MODEL_ASSISTED_DERIVATIONS for t in self.terms)


class RejectedPatentQuery(MawhibaModel):
    """A planned patent query that was refused, and why.

    A PII refusal keeps no text: the ledger records that a query was refused,
    never the personal data that caused it (the Phase 2B rule, section 12).
    """

    query_id: UUID = Field(default_factory=uuid4)
    provider: PatentProvider | None = None
    purpose: QueryPurpose | None = None
    strategy: PatentSearchStrategy | None = None
    query_expression: str = ""
    reason: PatentQueryRejectionReason
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _pii_is_never_stored(self) -> RejectedPatentQuery:
        if self.reason in PII_SENSITIVE_REJECTIONS and (
            self.query_expression or self.detail
        ):
            raise ValueError("a PII-refused query must retain neither text nor detail")
        return self


class ExcludedPatentClaim(MawhibaModel):
    """A claim or component that got no patent query, with a machine-readable why."""

    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    component_id: str | None = None
    reason: PatentClaimExclusionReason
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _pii_is_never_stored(self) -> ExcludedPatentClaim:
        if self.reason is PatentClaimExclusionReason.PII_DETECTED and self.detail:
            raise ValueError("a PII exclusion must not retain the offending text")
        return self


# ---------------------------------------------------------------------------
# Provider results and observations (section 15)
# ---------------------------------------------------------------------------


class PatentRateLimitInfo(MawhibaModel):
    """Rate limiting and fair-use rejection, represented explicitly."""

    provider: PatentProvider
    limited: bool = True
    http_status: int | None = Field(default=None, ge=100, le=599)
    retry_after_seconds: float | None = Field(default=None, ge=0.0)
    rejection_reason: str | None = Field(
        default=None,
        max_length=MAX_SAFE_SUMMARY_LENGTH,
        description="The provider's own rejection label where it supplies one, "
        "e.g. the EPO OPS X-Rejection-Reason header value.",
    )
    attempts: int = Field(default=1, ge=1)


class PatentProviderError(MawhibaModel):
    """One failed attempt against one provider.

    ``message`` is a developer-facing English summary written by this project,
    never a raw provider body: a body can echo the request, and an echoed
    request can carry a token (section 27).
    """

    provider: PatentProvider
    kind: PatentErrorKind
    retryable: bool
    attempt: int = Field(ge=1)
    http_status: int | None = Field(default=None, ge=100, le=599)
    operation: PatentProviderOperation | None = None
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _retryability_matches_kind(self) -> PatentProviderError:
        if self.retryable != (self.kind in RETRYABLE_PATENT_ERROR_KINDS):
            raise ValueError(
                f"retryable={self.retryable} contradicts kind {self.kind.value}"
            )
        return self


class PatentSearchObservation(MawhibaModel):
    """ONE provider's record of ONE patent publication (section 15).

    Untrusted: an observation is not a verified publication and never evidence.
    It is also never discarded by deduplication -- three providers returning one
    document produce one verified publication carrying three observations, which
    is what makes "who independently returned this?" answerable.

    ``provider_rank`` and ``provider_relevance`` are retrieval metadata and
    nothing else (section 24). There is no ``novelty_score`` here and no field
    one could be written into.
    """

    observation_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    query_id: UUID
    branch: ResearchBranch = ResearchBranch.PATENT
    provider: PatentProvider
    provider_operation: PatentProviderOperation = (
        PatentProviderOperation.SEARCH_PUBLICATIONS
    )
    provider_endpoint: str = Field(min_length=1)

    identity: PublicationIdentity
    title: str = Field(default="", description="As supplied. Never an identity input.")
    title_language: str | None = Field(default=None, pattern=LANGUAGE_PATTERN)
    dates: PatentDateSet = Field(default_factory=PatentDateSet)
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    ipc_classifications: list[str] = Field(default_factory=list)
    cpc_classifications: list[str] = Field(default_factory=list)
    family_id: str | None = Field(default=None, pattern=FAMILY_ID_PATTERN)
    provider_record_id: str | None = None
    provider_rank: int | None = Field(
        default=None,
        ge=0,
        description="The provider's ordering. Retrieval metadata, never validity "
        "and never similarity (section 24).",
    )
    provider_relevance: float | None = Field(
        default=None,
        ge=0.0,
        description="The provider's own retrieval score where it supplies one. "
        "Stored as provider-generated metadata; never renamed a novelty score.",
    )
    retrieved_at: UtcDatetime
    raw_provider_metadata: str | None = Field(
        default=None,
        description="Compact provider text for audit. Carries no credentials and "
        "no request headers.",
    )

    @model_validator(mode="after")
    def _patent_branch_only(self) -> PatentSearchObservation:
        if self.branch is not ResearchBranch.PATENT:
            raise ValueError("a patent observation must carry branch=PATENT")
        return self

    @property
    def publication_key(self) -> str:
        return self.identity.canonical_key


class RejectedPatentRecord(MawhibaModel):
    """Auditable ledger entry for a provider record that was refused."""

    provider: PatentProvider
    query_id: UUID | None = None
    stage: PatentRejectionStage
    reason: PatentRejectionReason
    provider_record_identifier: str | None = None
    safe_summary: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _pii_rejections_keep_no_text(self) -> RejectedPatentRecord:
        if self.reason is PatentRejectionReason.PII_DETECTED and self.safe_summary:
            raise ValueError("a PII rejection must not retain the offending text")
        return self


class PatentSearchResult(MawhibaModel):
    """Provider-neutral envelope for ONE provider answering ONE query.

    ``provider_reported_total`` is the count the provider says matched, which is
    routinely far larger than ``requested_limit``. Recording both is what makes
    "this was a bounded search" a fact on the record rather than a caveat in
    prose (section 13).
    """

    provider: PatentProvider
    query_id: UUID
    research_run_id: UUID
    status: PatentSearchStatus
    attempts: int = Field(default=1, ge=1)
    provider_endpoint: str = Field(min_length=1)
    requested_range_start: int = Field(default=1, ge=1)
    requested_limit: int = Field(ge=1, le=100)

    raw_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    provider_reported_total: int | None = Field(
        default=None,
        ge=0,
        description="The provider's own total-hits figure where supplied. None "
        "means it supplied none, never that the total equals what was fetched.",
    )

    observations: list[PatentSearchObservation] = Field(default_factory=list)
    rejected: list[RejectedPatentRecord] = Field(default_factory=list)
    rate_limit: PatentRateLimitInfo | None = None
    errors: list[PatentProviderError] = Field(default_factory=list)

    started_at: UtcDatetime
    completed_at: UtcDatetime

    @model_validator(mode="after")
    def _status_matches_payload(self) -> PatentSearchResult:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.accepted_count != len(self.observations):
            raise ValueError("accepted_count must match the observations returned")
        if any(o.provider is not self.provider for o in self.observations):
            raise ValueError("an observation belongs to a different provider")
        if any(o.query_id != self.query_id for o in self.observations):
            raise ValueError("an observation belongs to a different query")
        if any(o.research_run_id != self.research_run_id for o in self.observations):
            raise ValueError("an observation belongs to a different research run")

        if self.status in SUCCESSFUL_PATENT_STATUSES:
            if not self.observations:
                raise ValueError(f"{self.status.value} requires at least one observation")
            if (self.status is PatentSearchStatus.PARTIAL) != (self.rejected_count > 0):
                raise ValueError("PARTIAL is exactly a success with rejected records")
        elif self.observations:
            raise ValueError(f"{self.status.value} must not carry observations")

        if self.status is PatentSearchStatus.EMPTY and (self.raw_count or self.errors):
            raise ValueError("EMPTY means the provider answered with no records")
        if self.status is PatentSearchStatus.RATE_LIMITED and self.rate_limit is None:
            raise ValueError("RATE_LIMITED requires rate_limit information")
        if (
            self.status
            in (
                PatentSearchStatus.TIMEOUT,
                PatentSearchStatus.AUTH_ERROR,
                PatentSearchStatus.PROVIDER_ERROR,
                PatentSearchStatus.RATE_LIMITED,
                PatentSearchStatus.INVALID_RESPONSE,
                PatentSearchStatus.INVALID_QUERY,
                PatentSearchStatus.UNSUPPORTED_OPERATION,
            )
            and not self.errors
        ):
            raise ValueError(f"{self.status.value} requires at least one error")
        return self

    @property
    def executed(self) -> bool:
        """The provider answered, even if it found nothing."""
        return self.status in EXECUTED_PATENT_STATUSES

    @property
    def failed(self) -> bool:
        return not self.executed

    @property
    def truncated_by_range(self) -> bool:
        """The provider says more matched than this bounded request fetched."""
        return (
            self.provider_reported_total is not None
            and self.provider_reported_total > self.accepted_count + self.rejected_count
        )


# ---------------------------------------------------------------------------
# Verified publication (section 22)
# ---------------------------------------------------------------------------


class VerifiedPatentPublication(MawhibaModel):
    """ONE patent publication that passed deterministic verification.

    *Verified* means bibliographically verified: the canonical identity is well
    formed, the dates parse and order possibly, the classifications are well
    formed, every observation traces to a query of this run, and the text
    snapshots hash to what is stored. It says nothing about what the patent
    discloses and nothing about the student's invention (section 22, ADR-018).

    Deliberately absent, and unrepresentable: any similarity score, any novelty
    verdict, any "same invention" flag, any legal status conclusion.
    """

    publication_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    display_id: str | None = Field(default=None, pattern=DISPLAY_ID_PATTERN)
    research_run_id: UUID
    identity: PublicationIdentity
    fingerprint: SourceFingerprint

    title: str = Field(default="")
    title_language: str | None = Field(default=None, pattern=LANGUAGE_PATTERN)
    dates: PatentDateSet = Field(default_factory=PatentDateSet)
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    ipc_classifications: list[str] = Field(default_factory=list)
    cpc_classifications: list[str] = Field(default_factory=list)

    family_group_id: UUID | None = None
    family_status: PatentFamilyStatus = PatentFamilyStatus.NOT_REQUESTED

    observations: list[PatentSearchObservation] = Field(min_length=1)
    content: PatentContentReport = Field(default_factory=PatentContentReport)
    snapshot_ids: list[UUID] = Field(default_factory=list)

    verification_status: VerificationStatus = VerificationStatus.VERIFIED_METADATA
    identity_version: str = Field(default=PATENT_IDENTITY_VERSION, min_length=1)
    first_retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def _identity_and_provenance_hold(self) -> VerifiedPatentPublication:
        if self.verification_status not in (
            VerificationStatus.VERIFIED_METADATA,
            VerificationStatus.VERIFIED_FULL_TEXT,
        ):
            raise ValueError(
                "a verified publication carries a verified metadata or full-text "
                "status; a search hit is not a verified publication (section 22)"
            )
        expected = self.identity.fingerprint()
        if self.fingerprint.identifier_kind is not expected.identifier_kind:
            raise ValueError(
                "fingerprint must use PATENT_PUBLICATION_NUMBER identity, never a title"
            )
        if self.fingerprint.identifier != expected.identifier:
            raise ValueError(
                "fingerprint identifier must be the normalized canonical publication key"
            )
        if any(o.research_run_id != self.research_run_id for o in self.observations):
            raise ValueError("an observation belongs to a different research run")
        if any(
            not o.identity.same_publication(self.identity) for o in self.observations
        ):
            raise ValueError(
                "every observation of a publication must state the same canonical "
                "identity, kind code included (section 16)"
            )
        if (
            self.family_status is PatentFamilyStatus.VERIFIED_FAMILY
            and self.family_group_id is None
        ):
            raise ValueError("VERIFIED_FAMILY requires a resolved family group")
        return self

    @property
    def publication_key(self) -> str:
        return self.identity.canonical_key

    @property
    def providers(self) -> list[PatentProvider]:
        """Which providers independently returned this publication, in order."""
        seen = {o.provider for o in self.observations}
        return [p for p in PATENT_PROVIDER_ORDER if p in seen]

    @property
    def query_ids(self) -> list[UUID]:
        return list(dict.fromkeys(o.query_id for o in self.observations))

    def to_source_record(self) -> SourceRecord:
        """The Phase 0 ``SourceRecord`` for this publication. Never evidence.

        ``tier`` stays ``UNRATED`` and ``quality`` at its default: coming back
        from a patent office proves retrieval, not relevance and not quality.
        """
        return SourceRecord(
            source_id=self.publication_id,
            display_id=self.display_id,
            fingerprint=self.fingerprint,
            source_type=SourceType.PATENT,
            title=self.title or self.publication_key,
            authors_or_org=list(self.applicants),
            year=int(self.dates.first_public_date[:4])
            if self.dates.first_public_date
            else None,
            provider=PATENT_TO_SOURCE_PROVIDER[self.observations[0].provider],
            retrieved_at=self.first_retrieved_at,
            branch=ResearchBranch.PATENT,
            tier=SourceTier.UNRATED,
            verification_status=self.verification_status,
        )


# ---------------------------------------------------------------------------
# Prior-art candidate (section 23)
# ---------------------------------------------------------------------------


class PatentCandidateLimitation(StrEnum):
    """What this candidate does *not* establish, stated on the candidate itself.

    Carried as data rather than left to documentation, because a candidate will
    be read by a later phase and by a human reviewer, and the limitation that
    matters most is the one attached to the record they are looking at.
    """

    NOVELTY_NOT_ASSESSED = "NOVELTY_NOT_ASSESSED"
    PATENTABILITY_NOT_ASSESSED = "PATENTABILITY_NOT_ASSESSED"
    LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED = "LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED"
    BOUNDED_SEARCH_NOT_EXHAUSTIVE = "BOUNDED_SEARCH_NOT_EXHAUSTIVE"
    CLAIMS_TEXT_UNAVAILABLE = "CLAIMS_TEXT_UNAVAILABLE"
    ABSTRACT_ONLY_TEXT = "ABSTRACT_ONLY_TEXT"
    TITLE_ONLY_METADATA = "TITLE_ONLY_METADATA"
    PUBLICATION_DATE_UNKNOWN = "PUBLICATION_DATE_UNKNOWN"
    FAMILY_MEMBERSHIP_UNKNOWN = "FAMILY_MEMBERSHIP_UNKNOWN"
    NO_CUTOFF_SUPPLIED = "NO_CUTOFF_SUPPLIED"
    CLASSIFICATION_OVERLAP_IS_NOT_IDENTITY = "CLASSIFICATION_OVERLAP_IS_NOT_IDENTITY"
    FAMILY_SCOPE_VARIES_BY_JURISDICTION = "FAMILY_SCOPE_VARIES_BY_JURISDICTION"


UNIVERSAL_CANDIDATE_LIMITATIONS: tuple[PatentCandidateLimitation, ...] = (
    PatentCandidateLimitation.NOVELTY_NOT_ASSESSED,
    PatentCandidateLimitation.PATENTABILITY_NOT_ASSESSED,
    PatentCandidateLimitation.LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED,
    PatentCandidateLimitation.BOUNDED_SEARCH_NOT_EXHAUSTIVE,
)
"""Limitations that hold for every Phase 2G candidate without exception.

A validator requires all four, so a candidate cannot be constructed that omits
the statement that novelty was not assessed.
"""


class PatentQueryProvenance(MawhibaModel):
    """Which query found this publication, and how that query was shaped."""

    query_id: UUID
    provider: PatentProvider
    purpose: QueryPurpose
    strategy: PatentSearchStrategy
    provider_rank: int | None = Field(default=None, ge=0)
    claim_ids: list[str] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)


class PatentPriorArtCandidate(MawhibaModel):
    """A patent document a LATER phase should compare against the project.

    This is the Phase 2G output and the end of the Phase 2G pipeline. It is a
    *research candidate*: a document that a bounded, provenance-recorded search
    surfaced, verified bibliographically, grouped into its family and placed on a
    date line. Whether it is the same invention, whether it affects novelty, and
    whether it is legal prior art in any jurisdiction are all outside this phase
    (ADR-018).

    The fields that would let this record overstate itself do not exist:
    no ``novelty_score``, no ``similarity``, no ``same_invention``, no
    ``invalidating``, no ``patentable``.
    """

    candidate_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    publication_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    publication_key: str = Field(min_length=1)
    identity: PublicationIdentity

    family_group_id: UUID | None = None
    family_id: str | None = Field(default=None, pattern=FAMILY_ID_PATTERN)
    family_status: PatentFamilyStatus = PatentFamilyStatus.NOT_REQUESTED

    title: str = Field(default="")
    dates: PatentDateSet = Field(default_factory=PatentDateSet)
    time_qualification: PatentTimeQualification
    cutoff_date: str | None = Field(default=None, pattern=PATENT_DATE_PATTERN)

    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    ipc_classifications: list[str] = Field(default_factory=list)
    cpc_classifications: list[str] = Field(default_factory=list)

    content: PatentContentReport = Field(default_factory=PatentContentReport)
    snapshot_ids: list[UUID] = Field(default_factory=list)
    query_provenance: list[PatentQueryProvenance] = Field(min_length=1)
    observation_ids: list[UUID] = Field(min_length=1)
    limitations: list[PatentCandidateLimitation] = Field(min_length=4)
    contract_version: str = Field(default=PATENT_CONTRACT_VERSION, min_length=1)

    @model_validator(mode="after")
    def _limitations_and_chronology_hold(self) -> PatentPriorArtCandidate:
        stated = set(self.limitations)
        missing = [
            limitation.value
            for limitation in UNIVERSAL_CANDIDATE_LIMITATIONS
            if limitation not in stated
        ]
        if missing:
            raise ValueError(
                "every patent candidate must state its universal limitations; "
                f"missing {missing}"
            )
        if self.publication_key != self.identity.canonical_key:
            raise ValueError("publication_key must be the canonical identity key")

        cutoff_relative = self.time_qualification in CUTOFF_RELATIVE_QUALIFICATIONS
        if cutoff_relative and self.cutoff_date is None:
            raise ValueError(
                f"{self.time_qualification.value} requires the cutoff it was "
                "qualified against (section 7)"
            )
        if self.time_qualification is PatentTimeQualification.NO_CUTOFF and self.cutoff_date:
            raise ValueError("NO_CUTOFF must not carry a cutoff date")
        if (
            self.time_qualification is PatentTimeQualification.PUBLICATION_DATE_UNKNOWN
            and self.dates.has_public_date
        ):
            raise ValueError(
                "PUBLICATION_DATE_UNKNOWN contradicts a known first public date"
            )
        if cutoff_relative and not self.dates.has_public_date:
            raise ValueError(
                "a cutoff-relative qualification requires a known first public "
                "date; a priority or filing date is not one (section 8)"
            )
        if (
            self.family_id is not None
            and self.family_status not in RESOLVED_FAMILY_STATUSES
        ):
            raise ValueError(
                "a family identifier requires a resolved family status (section 18)"
            )
        if (
            self.family_status is PatentFamilyStatus.VERIFIED_FAMILY
            and self.family_group_id is None
        ):
            raise ValueError("VERIFIED_FAMILY requires a resolved family group")
        return self


# ---------------------------------------------------------------------------
# Budget and run (sections 13, 26)
# ---------------------------------------------------------------------------


class PatentBudgetReport(MawhibaModel):
    """What the budget allowed, what ran, and exactly what it cut off.

    Section 26 forbids silent truncation, so every limit has both its
    configured value and the count it removed. A run that hit a limit can never
    also report complete coverage: ``PatentPriorArtRun`` enforces that.
    """

    max_queries_per_claim: int = Field(ge=1)
    max_queries_per_run: int = Field(ge=1)
    max_results_per_query: int = Field(ge=1)
    max_pages_per_query: int = Field(ge=1)
    max_total_provider_results: int = Field(ge=1)
    max_verified_publications: int = Field(ge=1)
    max_family_lookups: int = Field(ge=0)
    max_classification_expansions: int = Field(ge=0)
    retry_limit: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0.0)

    claims_considered: int = Field(default=0, ge=0)
    claims_excluded: int = Field(default=0, ge=0)
    queries_planned: int = Field(default=0, ge=0)
    queries_executed: int = Field(default=0, ge=0)
    queries_rejected: int = Field(default=0, ge=0)
    queries_truncated: int = Field(default=0, ge=0)
    queries_reused_from_checkpoint: int = Field(default=0, ge=0)
    queries_failed: int = Field(default=0, ge=0)
    queries_retried: int = Field(default=0, ge=0)

    pages_requested: int = Field(default=0, ge=0)
    results_returned: int = Field(default=0, ge=0)
    results_accepted: int = Field(default=0, ge=0)
    results_truncated_per_query: int = Field(default=0, ge=0)
    results_truncated_total: int = Field(default=0, ge=0)
    publications_truncated: int = Field(default=0, ge=0)
    family_lookups_performed: int = Field(default=0, ge=0)
    family_lookups_truncated: int = Field(default=0, ge=0)
    classification_expansions_performed: int = Field(default=0, ge=0)
    classification_expansions_truncated: int = Field(default=0, ge=0)
    provider_reported_total_seen: int | None = Field(default=None, ge=0)

    @property
    def truncated(self) -> bool:
        return bool(
            self.queries_truncated
            or self.results_truncated_per_query
            or self.results_truncated_total
            or self.publications_truncated
            or self.family_lookups_truncated
            or self.classification_expansions_truncated
        )

    @property
    def provider_total_exceeds_fetched(self) -> bool:
        return (
            self.provider_reported_total_seen is not None
            and self.provider_reported_total_seen > self.results_returned
        )


class PatentPriorArtRun(MawhibaModel):
    """Everything the PATENT branch produced in one research run.

    Lives on the ``ResearchRun``, never in ``ProjectState``, for exactly the
    reason every phase since 2B has: patent research reads canonical state
    through a verified plan and writes none of it (ADR-010, ADR-018). It cannot
    mutate a claim, a score or a trust verdict, because no such field exists
    anywhere in this module.
    """

    patent_run_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    outcome: PatentBranchOutcome = PatentBranchOutcome.NOT_RUN
    coverage_status: PatentSearchCoverageStatus = PatentSearchCoverageStatus.NOT_EXECUTED

    contract_version: str = PATENT_CONTRACT_VERSION
    normalizer_version: str = PATENT_NORMALIZER_VERSION
    identity_version: str = PATENT_IDENTITY_VERSION
    dedup_version: str = PATENT_DEDUP_VERSION
    family_version: str = PATENT_FAMILY_VERSION
    planner_version: str = PATENT_PLANNER_VERSION
    chronology_version: str = PATENT_CHRONOLOGY_VERSION
    connector_versions: dict[str, str] = Field(default_factory=dict)
    planner_prompt_version: str | None = Field(
        default=None,
        description="Set only when model-assisted query expansion actually ran. "
        "None means every term was derived deterministically.",
    )

    providers: list[PatentProvider] = Field(default_factory=list)
    provider_capabilities: list[PatentProviderCapability] = Field(default_factory=list)
    search_cutoff: PatentSearchCutoff = Field(default_factory=PatentSearchCutoff)
    budget: PatentBudgetReport

    planned_queries: list[PatentSearchQuery] = Field(default_factory=list)
    executed_query_keys: list[str] = Field(
        default_factory=list,
        description="Stable keys of queries already executed in this run. What "
        "makes a resumed run idempotent instead of duplicating requests.",
    )
    rejected_queries: list[RejectedPatentQuery] = Field(default_factory=list)
    excluded_claims: list[ExcludedPatentClaim] = Field(default_factory=list)

    provider_results: list[PatentSearchResult] = Field(default_factory=list)
    observations: list[PatentSearchObservation] = Field(default_factory=list)
    rejected_records: list[RejectedPatentRecord] = Field(default_factory=list)

    publications: list[VerifiedPatentPublication] = Field(default_factory=list)
    families: list[PatentFamilyGroup] = Field(default_factory=list)
    snapshots: list[PatentTextSnapshot] = Field(default_factory=list)
    candidates: list[PatentPriorArtCandidate] = Field(default_factory=list)
    verified_sources: list[SourceRecord] = Field(default_factory=list)

    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = Field(
        default=None,
        description="Set once by the finalize step. A completed patent run is "
        "never reopened, which is what makes re-invoking the graph idempotent.",
    )

    @model_validator(mode="after")
    def _internally_consistent(self) -> PatentPriorArtRun:
        run_id = self.research_run_id
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at")

        # -- cross-run isolation (section 30) --------------------------------
        for label, items in (
            ("planned query", self.planned_queries),
            ("provider result", self.provider_results),
            ("observation", self.observations),
            ("publication", self.publications),
            ("family", self.families),
            ("snapshot", self.snapshots),
            ("candidate", self.candidates),
        ):
            if any(item.research_run_id != run_id for item in items):
                raise ValueError(f"a {label} belongs to a different research run")

        # -- referential integrity ------------------------------------------
        query_ids = {q.query_id for q in self.planned_queries}
        if any(o.query_id not in query_ids for o in self.observations):
            raise ValueError("an observation references an unknown query")
        if any(r.query_id not in query_ids for r in self.provider_results):
            raise ValueError("a provider result references an unknown query")

        publication_keys = {p.publication_key for p in self.publications}
        publication_ids = {p.publication_id for p in self.publications}
        if len(publication_keys) != len(self.publications):
            raise ValueError("publication identities must be unique (section 16)")
        if len(publication_ids) != len(self.publications):
            raise ValueError("publication ids must be unique")

        family_ids = {f.family_group_id for f in self.families}
        if any(
            p.family_group_id is not None and p.family_group_id not in family_ids
            for p in self.publications
        ):
            raise ValueError("a publication references a family absent from this run")

        snapshot_ids = {s.snapshot_id for s in self.snapshots}
        if any(s.publication_key not in publication_keys for s in self.snapshots):
            raise ValueError("a snapshot references an unknown publication")
        for publication in self.publications:
            unknown = [i for i in publication.snapshot_ids if i not in snapshot_ids]
            if unknown:
                raise ValueError("a publication references an unknown text snapshot")

        observation_ids = {o.observation_id for o in self.observations}
        candidate_publications = [c.publication_id for c in self.candidates]
        if len(set(candidate_publications)) != len(candidate_publications):
            raise ValueError(
                "a publication has at most one prior-art candidate per run; a "
                "second one would count one document twice (section 29)"
            )
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("candidate ids must be unique")
        by_publication = {p.publication_id: p for p in self.publications}
        for candidate in self.candidates:
            publication = by_publication.get(candidate.publication_id)
            if publication is not None and (
                candidate.publication_key != publication.publication_key
                or candidate.dates != publication.dates
                or candidate.family_group_id != publication.family_group_id
            ):
                raise ValueError(
                    "a candidate must carry its verified publication's identity, "
                    "dates and family unchanged"
                )
        for candidate in self.candidates:
            if candidate.publication_id not in publication_ids:
                raise ValueError("a candidate references an unverified publication")
            if any(o not in observation_ids for o in candidate.observation_ids):
                raise ValueError("a candidate references an unknown observation")
            if any(p.query_id not in query_ids for p in candidate.query_provenance):
                raise ValueError("a candidate references an unknown query")
            if (
                candidate.family_group_id is not None
                and candidate.family_group_id not in family_ids
            ):
                raise ValueError("a candidate references a family absent from this run")

        for member_owner in self.families:
            for member in member_owner.members:
                if member.retrieved_in_run and member.publication_key not in publication_keys:
                    raise ValueError(
                        "a family member marked retrieved has no verified publication"
                    )

        if sorted(publication_ids) != sorted(r.source_id for r in self.verified_sources):
            raise ValueError(
                "every verified publication has exactly one verified SourceRecord"
            )

        # -- cutoff semantics (section 7) ------------------------------------
        if not self.search_cutoff.supplied:
            offenders = sorted(
                {
                    c.time_qualification.value
                    for c in self.candidates
                    if c.time_qualification in CUTOFF_RELATIVE_QUALIFICATIONS
                }
            )
            if offenders:
                raise ValueError(
                    "a run with no supplied cutoff cannot qualify a publication "
                    f"against one: {offenders} (section 7)"
                )
        if any(
            c.cutoff_date not in (None, self.search_cutoff.cutoff_date)
            for c in self.candidates
        ):
            raise ValueError("a candidate was qualified against a different cutoff")

        # -- coverage honesty (sections 13, 26) ------------------------------
        complete = (
            self.coverage_status is PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS
        )
        if complete:
            if self.budget.truncated:
                raise ValueError(
                    "a truncated search cannot report complete coverage (section 26)"
                )
            if any(r.failed for r in self.provider_results):
                raise ValueError(
                    "a search with a failed provider query cannot report complete "
                    "coverage (section 13)"
                )
        if (
            self.coverage_status is PatentSearchCoverageStatus.NOT_EXECUTED
            and self.provider_results
        ):
            raise ValueError("NOT_EXECUTED must not carry provider results")

        # -- outcome honesty --------------------------------------------------
        if self.outcome is PatentBranchOutcome.NOT_RUN and self.provider_results:
            raise ValueError("NOT_RUN must not carry provider results")
        if self.outcome is PatentBranchOutcome.FAILED and self.publications:
            raise ValueError("FAILED must not carry verified publications")
        if self.outcome is PatentBranchOutcome.EMPTY and self.observations:
            raise ValueError("EMPTY means no provider returned a usable record")

        # -- provider honesty (section 2) -------------------------------------
        dispatched = {r.provider for r in self.provider_results}
        by_provider = {c.provider: c for c in self.provider_capabilities}
        for provider in dispatched:
            capability = by_provider.get(provider)
            if capability is None:
                raise ValueError(
                    f"{provider.value} was dispatched without a declared capability"
                )
            if not capability.dispatchable:
                raise ValueError(
                    f"{provider.value} is not dispatchable under its declared "
                    f"access status {capability.access_status.value} (section 2)"
                )
        return self

    # -- read helpers ---------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return self.completed_at is not None

    @property
    def provider_success_count(self) -> int:
        return sum(
            1 for r in self.provider_results if r.status in SUCCESSFUL_PATENT_STATUSES
        )

    @property
    def provider_empty_count(self) -> int:
        return sum(1 for r in self.provider_results if r.status is PatentSearchStatus.EMPTY)

    @property
    def provider_failure_count(self) -> int:
        return sum(1 for r in self.provider_results if r.failed)

    @property
    def independent_family_count(self) -> int:
        """Candidate inventions, not candidate documents (section 17).

        A family contributes one however many members it has. A publication
        whose family could not be resolved contributes one on its own, because
        an unknown family is not evidence of a shared one.
        """
        grouped = {p.family_group_id for p in self.publications if p.family_group_id}
        ungrouped = sum(1 for p in self.publications if p.family_group_id is None)
        return len(grouped) + ungrouped

    @property
    def claims_available_count(self) -> int:
        return sum(1 for p in self.publications if p.content.claims_available)

    @property
    def bounded_search(self) -> bool:
        """Always true. Phase 2G never performs an exhaustive corpus search."""
        return True

    def publication_by_key(self, publication_key: str) -> VerifiedPatentPublication | None:
        return next(
            (p for p in self.publications if p.publication_key == publication_key), None
        )

    def family_by_group_id(self, family_group_id: UUID) -> PatentFamilyGroup | None:
        return next(
            (f for f in self.families if f.family_group_id == family_group_id), None
        )

    def snapshots_for(self, publication_key: str) -> list[PatentTextSnapshot]:
        return [s for s in self.snapshots if s.publication_key == publication_key]

    def results_for(self, provider: PatentProvider) -> list[PatentSearchResult]:
        return [r for r in self.provider_results if r.provider is provider]


def patent_safe_summary(text: str | None) -> str:
    """A short, single-line, length-bounded summary for a rejection ledger."""
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= MAX_SAFE_SUMMARY_LENGTH:
        return collapsed
    return collapsed[: MAX_SAFE_SUMMARY_LENGTH - 1] + "…"


__all__ = [
    "AUTHORITY_PATTERN",
    "BUDGET_PATENT_REJECTIONS",
    "CLASSIFICATION_PATTERN",
    "CUTOFF_RELATIVE_QUALIFICATIONS",
    "EXECUTED_PATENT_STATUSES",
    "FAMILY_ID_PATTERN",
    "IMPLEMENTED_ACCESS_STATUSES",
    "KIND_CODE_PATTERN",
    "MAX_PATENT_TEXT_CHARS",
    "MAX_SAFE_SUMMARY_LENGTH",
    "MODEL_ASSISTED_DERIVATIONS",
    "NON_LITERAL_STRATEGIES",
    "NO_SEARCH_CUTOFF",
    "PARTIAL_COVERAGE_STATUSES",
    "PATENT_CHRONOLOGY_VERSION",
    "PATENT_CONTRACT_VERSION",
    "PATENT_DATE_PATTERN",
    "PATENT_DEDUP_VERSION",
    "PATENT_ERROR_TO_SEARCH_STATUS",
    "PATENT_FAMILY_VERSION",
    "PATENT_IDENTITY_VERSION",
    "PATENT_NORMALIZER_VERSION",
    "PATENT_PLANNER_VERSION",
    "PATENT_PROVIDER_ORDER",
    "PATENT_SEARCH_PURPOSES",
    "PATENT_TO_SOURCE_PROVIDER",
    "PUBLICATION_NUMBER_PATTERN",
    "RESOLVED_FAMILY_STATUSES",
    "RETRYABLE_PATENT_ERROR_KINDS",
    "SUCCESSFUL_PATENT_STATUSES",
    "UNIVERSAL_CANDIDATE_LIMITATIONS",
    "ExcludedPatentClaim",
    "PatentBranchOutcome",
    "PatentBudgetReport",
    "PatentCandidateLimitation",
    "PatentClaimExclusionReason",
    "PatentContentAvailability",
    "PatentContentReport",
    "PatentContentType",
    "PatentDateSet",
    "PatentErrorKind",
    "PatentFacingModel",
    "PatentFamilyGroup",
    "PatentFamilyKind",
    "PatentFamilyMemberRef",
    "PatentFamilyStatus",
    "PatentPriorArtCandidate",
    "PatentPriorArtRun",
    "PatentProvider",
    "PatentProviderCapability",
    "PatentProviderError",
    "PatentProviderOperation",
    "PatentProviderAccessStatus",
    "PatentQueryDerivation",
    "PatentQueryProvenance",
    "PatentQueryRejectionReason",
    "PatentQueryTerm",
    "PatentRateLimitInfo",
    "PatentRejectionReason",
    "PatentRejectionStage",
    "PatentSearchCoverageStatus",
    "PatentSearchCutoff",
    "PatentSearchObservation",
    "PatentSearchQuery",
    "PatentSearchResult",
    "PatentSearchStatus",
    "PatentSearchStrategy",
    "PatentTextScope",
    "PatentTextSnapshot",
    "PatentTimeQualification",
    "PublicationIdentity",
    "RejectedPatentQuery",
    "RejectedPatentRecord",
    "VerifiedPatentPublication",
    "patent_safe_summary",
]
