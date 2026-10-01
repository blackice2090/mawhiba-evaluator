"""Shared discovery vocabulary for product and open-source prior-art research.

Phase 2H (ADR-019) has two tracks -- commercial/public products and public
open-source repositories -- that differ in identity, chronology and provider,
but share what a *bounded, provenance-recorded discovery search* is:

* why a query was sent (``DiscoveryQueryPurpose``) and from which claim text;
* what one execution of it returned, or why it failed (``DiscoveryErrorKind``);
* what the search can honestly claim about its own coverage;
* which providers exist and how honestly each may be described;
* the explicit cutoff, if one was supplied;
* the limitations every candidate carries.

Those live here once, so the two tracks cannot drift into two dialects. What
the tracks do *not* share -- product identity, repository identity, product and
repository dates -- lives in the track modules, and is never flattened into a
generic record (section 31).

Nothing here is a novelty judgement, a copying determination or a legal
prior-art ruling, and no field could hold one.
"""

from __future__ import annotations

import re
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime

DISCOVERY_CONTRACT_VERSION = "DISCOVERY-CONTRACT-V1"
DISCOVERY_PLANNER_VERSION = "DISCOVERY-QUERY-PLAN-V1"

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
CONTENT_HASH_PATTERN = r"^[0-9a-f]{64}$"
MAX_SAFE_SUMMARY_LENGTH = 200

DISCOVERY_ID_NAMESPACE = UUID("6f1d0c52-2f4e-5b8e-9c61-3c2a7d0e4b19")
"""Namespace for deterministic Phase 2H identifiers (section 35).

Query, entity, network and candidate ids are ``uuid5`` of this namespace and a
stable key, so a rerun over identical inputs produces identical ids, and a
resumed run recognises what it already holds instead of duplicating it.
"""


def stable_id(*parts: object) -> UUID:
    """A deterministic id from stable parts. Same parts, same id, every run."""
    return uuid5(DISCOVERY_ID_NAMESPACE, "|".join(str(p) for p in parts))


def safe_summary(text: str | None) -> str:
    """A short, single-line, length-bounded summary for a ledger entry."""
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= MAX_SAFE_SUMMARY_LENGTH:
        return collapsed
    return collapsed[: MAX_SAFE_SUMMARY_LENGTH - 1] + "â€¦"


# ---------------------------------------------------------------------------
# Tracks, providers and provider honesty
# ---------------------------------------------------------------------------


class DiscoveryTrack(StrEnum):
    PRODUCT = "PRODUCT"
    OPEN_SOURCE = "OPEN_SOURCE"


class DiscoveryProvider(StrEnum):
    """Providers Phase 2H knows about. Membership is not a claim of access."""

    BRAVE_WEB_SEARCH = "BRAVE_WEB_SEARCH"
    SAFE_WEB_FETCHER = "SAFE_WEB_FETCHER"
    GITHUB_REST = "GITHUB_REST"


class DiscoveryProviderAccessStatus(StrEnum):
    """How honestly a provider may be described (sections 4, 47).

    ``IMPLEMENTED_AND_LIVE_VERIFIED`` requires a real successful request. A
    connector built from documentation alone is ``IMPLEMENTED_DOCUMENTED_ONLY``
    and is never reported as live-tested.
    """

    IMPLEMENTED_AND_LIVE_VERIFIED = "IMPLEMENTED_AND_LIVE_VERIFIED"
    IMPLEMENTED_DOCUMENTED_ONLY = "IMPLEMENTED_DOCUMENTED_ONLY"
    DEFERRED = "DEFERRED"
    UNSUPPORTED = "UNSUPPORTED"


DISPATCHABLE_ACCESS_STATUSES: frozenset[DiscoveryProviderAccessStatus] = frozenset(
    {
        DiscoveryProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED,
        DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    }
)


class DiscoveryOperation(StrEnum):
    """One operation a provider may expose. Declared, never assumed."""

    WEB_SEARCH = "WEB_SEARCH"
    FETCH_PAGE = "FETCH_PAGE"
    REPOSITORY_SEARCH = "REPOSITORY_SEARCH"
    CODE_SEARCH = "CODE_SEARCH"
    REPOSITORY_METADATA = "REPOSITORY_METADATA"
    REPOSITORY_README = "REPOSITORY_README"
    REPOSITORY_CONTENT = "REPOSITORY_CONTENT"
    REPOSITORY_RELEASES = "REPOSITORY_RELEASES"
    REPOSITORY_COMMITS = "REPOSITORY_COMMITS"


SEARCH_OPERATIONS: frozenset[DiscoveryOperation] = frozenset(
    {
        DiscoveryOperation.WEB_SEARCH,
        DiscoveryOperation.REPOSITORY_SEARCH,
        DiscoveryOperation.CODE_SEARCH,
    }
)


class DiscoveryProviderCapability(MawhibaModel):
    """What one provider supports, on what documented authority, verified when."""

    provider: DiscoveryProvider
    access_status: DiscoveryProviderAccessStatus
    documentation_urls: list[str] = Field(min_length=1)
    contract_verified_on: str = Field(pattern=DATE_PATTERN)
    authentication: str = Field(min_length=1)
    operations: list[DiscoveryOperation] = Field(default_factory=list)
    authenticated_operations: list[DiscoveryOperation] = Field(
        default_factory=list,
        description="Operations the provider documents as requiring credentials. "
        "Without credentials they are refused at dispatch, never attempted.",
    )
    live_request_observed: bool = Field(
        default=False,
        description="True only when a real successful request was executed.",
    )
    notes: str = ""

    @model_validator(mode="after")
    def _honesty_holds(self) -> DiscoveryProviderCapability:
        live = self.access_status is DiscoveryProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED
        if live != self.live_request_observed:
            raise ValueError(
                "IMPLEMENTED_AND_LIVE_VERIFIED is reported exactly when a live "
                "request was observed (provider honesty)"
            )
        if self.access_status not in DISPATCHABLE_ACCESS_STATUSES and self.operations:
            raise ValueError("a deferred or unsupported provider exposes no operations")
        if any(op not in self.operations for op in self.authenticated_operations):
            raise ValueError("an authenticated operation must be a declared operation")
        return self

    def supports(self, operation: DiscoveryOperation) -> bool:
        return (
            self.access_status in DISPATCHABLE_ACCESS_STATUSES
            and operation in self.operations
        )


# ---------------------------------------------------------------------------
# Query planning
# ---------------------------------------------------------------------------


class DiscoveryQueryPurpose(StrEnum):
    """*Why and how* a discovery query was shaped (section 10).

    A Phase 2H dimension beside the Phase 2A ``QueryPurpose`` (which stays the
    branch-level PRODUCT / OPEN_SOURCE purpose), in the same way Phase 2G's
    ``PatentSearchStrategy`` sits beside it.
    """

    EXACT_TECHNICAL_PHRASE = "EXACT_TECHNICAL_PHRASE"
    CORE_CONCEPT = "CORE_CONCEPT"
    FUNCTION_MECHANISM = "FUNCTION_MECHANISM"
    COMPONENT_COMBINATION = "COMPONENT_COMBINATION"
    SYNONYM_VARIANT = "SYNONYM_VARIANT"
    BROADER_CATEGORY = "BROADER_CATEGORY"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"
    IMPLEMENTATION_TERM = "IMPLEMENTATION_TERM"
    SOFTWARE_LIBRARY_TERM = "SOFTWARE_LIBRARY_TERM"
    KNOWN_IDENTIFIER = "KNOWN_IDENTIFIER"


class DiscoveryTermDerivation(StrEnum):
    """Where a query term came from. Model-assisted terms are never canonical."""

    CANONICAL_CLAIM_TEXT = "CANONICAL_CLAIM_TEXT"
    CANONICAL_COMPONENT_TEXT = "CANONICAL_COMPONENT_TEXT"
    DETERMINISTIC_TEMPLATE = "DETERMINISTIC_TEMPLATE"
    MODEL_ASSISTED_TRANSLATION = "MODEL_ASSISTED_TRANSLATION"
    MODEL_ASSISTED_EXPANSION = "MODEL_ASSISTED_EXPANSION"
    KNOWN_IDENTIFIER_IN_CLAIM = "KNOWN_IDENTIFIER_IN_CLAIM"


MODEL_ASSISTED_TERM_DERIVATIONS: frozenset[DiscoveryTermDerivation] = frozenset(
    {
        DiscoveryTermDerivation.MODEL_ASSISTED_TRANSLATION,
        DiscoveryTermDerivation.MODEL_ASSISTED_EXPANSION,
    }
)


class QueryLanguage(StrEnum):
    EN = "en"
    AR = "ar"
    MIXED = "mixed"


class DiscoveryQueryTerm(MawhibaModel):
    """One term and its anchor in canonical claim text (section 11)."""

    term: str = Field(min_length=1)
    derivation: DiscoveryTermDerivation
    original_text: str = Field(
        min_length=1,
        description="The canonical claim or component text the term traces to. "
        "For a model-assisted term this is the verbatim source substring.",
    )
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    component_id: str | None = None


class DiscoveryQuery(MawhibaModel):
    """One planned, validated query. Planned from claims only, never from results.

    ``expansion_depth`` is pinned to zero: Phase 2H never derives a query from a
    search result, so recursive expansion cannot occur (section 10).
    """

    query_id: UUID
    research_run_id: UUID
    track: DiscoveryTrack
    provider: DiscoveryProvider
    operation: DiscoveryOperation
    purpose: DiscoveryQueryPurpose
    query_text: str = Field(min_length=1, max_length=256)
    language: QueryLanguage
    terms: list[DiscoveryQueryTerm] = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    component_ids: list[str] = Field(default_factory=list)
    requested_count: int = Field(ge=1, le=100)
    page: int = Field(default=1, ge=1, le=10)
    stable_key: str = Field(min_length=1)
    expansion_depth: int = Field(default=0, ge=0, le=0)
    model_prompt_version: str | None = None

    @model_validator(mode="after")
    def _traceable(self) -> DiscoveryQuery:
        if self.query_id != stable_id(self.research_run_id, self.stable_key):
            raise ValueError("query_id must be the stable id of its stable_key")
        if self.operation not in SEARCH_OPERATIONS and self.purpose is not (
            DiscoveryQueryPurpose.KNOWN_IDENTIFIER
        ):
            raise ValueError("only a known-identifier query may use a lookup operation")
        if {t.claim_id for t in self.terms} - set(self.claim_ids):
            raise ValueError("every term must trace to a listed claim")
        model_terms = [t for t in self.terms if t.derivation in MODEL_ASSISTED_TERM_DERIVATIONS]
        if model_terms and not self.model_prompt_version:
            raise ValueError("a model-assisted term requires the prompt version that produced it")
        expected = {
            DiscoveryTrack.PRODUCT: {DiscoveryProvider.BRAVE_WEB_SEARCH},
            DiscoveryTrack.OPEN_SOURCE: {DiscoveryProvider.GITHUB_REST},
        }[self.track]
        if self.provider not in expected:
            raise ValueError("a query's provider must belong to its track")
        return self


class DiscoveryQueryRejectionReason(StrEnum):
    PII_DETECTED = "PII_DETECTED"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"
    INVALID_QUERY = "INVALID_QUERY"
    QUERY_TOO_LONG = "QUERY_TOO_LONG"
    PROVIDER_QUALIFIER_IN_TERM = "PROVIDER_QUALIFIER_IN_TERM"
    UNTRACEABLE_TERM = "UNTRACEABLE_TERM"
    DUPLICATE_QUERY = "DUPLICATE_QUERY"
    QUERY_BUDGET_EXCEEDED = "QUERY_BUDGET_EXCEEDED"
    PROVIDER_NOT_DISPATCHABLE = "PROVIDER_NOT_DISPATCHABLE"
    OPERATION_REQUIRES_AUTHENTICATION = "OPERATION_REQUIRES_AUTHENTICATION"


class RejectedDiscoveryQuery(MawhibaModel):
    """A query that was not sent, and why. A PII refusal retains no text."""

    query_id: UUID | None = None
    track: DiscoveryTrack
    provider: DiscoveryProvider | None = None
    purpose: DiscoveryQueryPurpose | None = None
    query_text: str = ""
    claim_id: str | None = None
    reason: DiscoveryQueryRejectionReason
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _pii_retains_nothing(self) -> RejectedDiscoveryQuery:
        if self.reason is DiscoveryQueryRejectionReason.PII_DETECTED and (
            self.query_text or self.detail
        ):
            raise ValueError("a PII refusal must not retain the refused text")
        return self


class ClaimExclusionReason(StrEnum):
    CLAIM_TEXT_EMPTY = "CLAIM_TEXT_EMPTY"
    PII_DETECTED = "PII_DETECTED"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"
    NO_SEARCHABLE_TERMS = "NO_SEARCHABLE_TERMS"
    CLAIM_BUDGET_EXCEEDED = "CLAIM_BUDGET_EXCEEDED"


class ExcludedDiscoveryClaim(MawhibaModel):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    reason: ClaimExclusionReason
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)


# ---------------------------------------------------------------------------
# Execution, errors and coverage
# ---------------------------------------------------------------------------


class DiscoveryErrorKind(StrEnum):
    """Section 32. A classified failure, never a provider body."""

    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_LIMITED = "QUOTA_LIMITED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INVALID_QUERY = "INVALID_QUERY"
    FETCH_BLOCKED = "FETCH_BLOCKED"
    FETCH_UNSAFE = "FETCH_UNSAFE"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"


RETRYABLE_DISCOVERY_ERRORS: frozenset[DiscoveryErrorKind] = frozenset(
    {
        DiscoveryErrorKind.RATE_LIMITED,
        DiscoveryErrorKind.TIMEOUT,
        DiscoveryErrorKind.CONNECTION_ERROR,
        DiscoveryErrorKind.PROVIDER_ERROR,
    }
)
"""Transient kinds only. A quota, an auth failure or an unsafe URL is never
retried: an identical second request cannot change it."""


class DiscoveryExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class DiscoveryProviderError(MawhibaModel):
    kind: DiscoveryErrorKind
    attempt: int = Field(ge=1)
    retryable: bool
    http_status: int | None = None
    message: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _retryable_matches_kind(self) -> DiscoveryProviderError:
        if self.retryable != (self.kind in RETRYABLE_DISCOVERY_ERRORS):
            raise ValueError("retryable must follow the error kind")
        return self


class DiscoveryQueryExecution(MawhibaModel):
    """One provider execution of one query page. Failure is data, not an exception."""

    query_id: UUID
    research_run_id: UUID
    provider: DiscoveryProvider
    operation: DiscoveryOperation
    page: int = Field(ge=1)
    status: DiscoveryExecutionStatus
    attempts: int = Field(ge=1)
    results_requested: int = Field(ge=0)
    results_returned: int = Field(default=0, ge=0)
    results_accepted: int = Field(default=0, ge=0)
    provider_reported_total: int | None = Field(default=None, ge=0)
    provider_reports_more: bool = False
    provider_incomplete_results: bool = Field(
        default=False,
        description="GitHub's incomplete_results flag: the provider itself timed "
        "out and the page may be missing matches.",
    )
    errors: list[DiscoveryProviderError] = Field(default_factory=list)
    executed_at: UtcDatetime

    @model_validator(mode="after")
    def _status_consistent(self) -> DiscoveryQueryExecution:
        if self.status is DiscoveryExecutionStatus.FAILED:
            if not self.errors:
                raise ValueError("a failed execution must record its error")
            if self.results_accepted:
                raise ValueError("a failed execution cannot carry accepted results")
        if self.status is DiscoveryExecutionStatus.EMPTY and self.results_accepted:
            raise ValueError("EMPTY means no record was accepted")
        if self.status is DiscoveryExecutionStatus.SUCCESS and not self.results_accepted:
            raise ValueError("SUCCESS requires at least one accepted record")
        if self.results_accepted > self.results_returned:
            raise ValueError("accepted cannot exceed returned")
        return self

    @property
    def failed(self) -> bool:
        return self.status is DiscoveryExecutionStatus.FAILED

    @property
    def final_error(self) -> DiscoveryErrorKind | None:
        return self.errors[-1].kind if self.errors else None


class DiscoveryCoverageStatus(StrEnum):
    """Section 13. No member says exhaustive, because no search is."""

    COMPLETE_WITHIN_CONFIGURED_BOUNDS = "COMPLETE_WITHIN_CONFIGURED_BOUNDS"
    PARTIAL_PROVIDER_LIMIT = "PARTIAL_PROVIDER_LIMIT"
    PARTIAL_ERROR = "PARTIAL_ERROR"
    BLOCKED_AUTH = "BLOCKED_AUTH"
    NOT_EXECUTED = "NOT_EXECUTED"


class DiscoveryOutcome(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class DiscoveryBudget(MawhibaModel):
    """Configured limits beside the counts they cut off (sections 13, 34).

    ``truncated`` is true when any limit removed anything; a run whose budget
    is truncated can never report complete coverage.
    """

    max_queries_per_claim: int = Field(ge=1)
    max_queries_per_run: int = Field(ge=1)
    max_results_per_query: int = Field(ge=1)
    max_pages_per_query: int = Field(ge=1)
    max_total_observations: int = Field(ge=1)
    max_detail_lookups: int = Field(ge=0, description="Product fetches or repository metadata lookups.")
    max_artifact_bytes: int = Field(ge=1)
    max_items_per_parent: int = Field(
        ge=1, description="Code hits per repository; artifacts per observation URL is always one."
    )
    max_network_lookups: int = Field(ge=0)
    retry_limit: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0.0)

    claims_considered: int = Field(default=0, ge=0)
    claims_excluded: int = Field(default=0, ge=0)
    queries_planned: int = Field(default=0, ge=0)
    queries_rejected: int = Field(default=0, ge=0)
    queries_executed: int = Field(default=0, ge=0)
    queries_failed: int = Field(default=0, ge=0)
    queries_retried: int = Field(default=0, ge=0)
    queries_truncated: int = Field(default=0, ge=0)
    queries_reused_from_checkpoint: int = Field(default=0, ge=0)
    pages_requested: int = Field(default=0, ge=0)
    results_returned: int = Field(default=0, ge=0)
    results_accepted: int = Field(default=0, ge=0)
    results_truncated: int = Field(default=0, ge=0)
    pages_truncated: int = Field(default=0, ge=0)
    detail_lookups_performed: int = Field(default=0, ge=0)
    detail_lookups_truncated: int = Field(default=0, ge=0)
    items_truncated_per_parent: int = Field(default=0, ge=0)
    network_lookups_performed: int = Field(default=0, ge=0)
    network_lookups_truncated: int = Field(default=0, ge=0)
    content_truncated: int = Field(default=0, ge=0)
    provider_reported_total_seen: int | None = Field(default=None, ge=0)

    @property
    def truncated(self) -> bool:
        return bool(
            self.queries_truncated
            or self.results_truncated
            or self.pages_truncated
            or self.detail_lookups_truncated
            or self.items_truncated_per_parent
            or self.network_lookups_truncated
        )


# ---------------------------------------------------------------------------
# Cutoff and candidate limitations
# ---------------------------------------------------------------------------


class DiscoveryCutoff(MawhibaModel):
    """An explicitly supplied comparison date. Never inferred, never defaulted."""

    cutoff_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    source: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _named_source(self) -> DiscoveryCutoff:
        if self.cutoff_date is not None and not self.source:
            raise ValueError("a supplied cutoff must name its source")
        if self.cutoff_date is None and self.source:
            raise ValueError("a cutoff source without a cutoff date is meaningless")
        return self

    @property
    def supplied(self) -> bool:
        return self.cutoff_date is not None


NO_DISCOVERY_CUTOFF = DiscoveryCutoff()


class CandidateLimitation(StrEnum):
    """What a Phase 2H candidate does NOT establish, stated on the record itself."""

    NOVELTY_NOT_ASSESSED = "NOVELTY_NOT_ASSESSED"
    SAME_INVENTION_NOT_DETERMINED = "SAME_INVENTION_NOT_DETERMINED"
    LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED = "LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED"
    BOUNDED_SEARCH_NOT_EXHAUSTIVE = "BOUNDED_SEARCH_NOT_EXHAUSTIVE"
    LATER_NOVELTY_COMPARISON_REQUIRED = "LATER_NOVELTY_COMPARISON_REQUIRED"
    NO_COPYING_DETERMINATION = "NO_COPYING_DETERMINATION"
    NO_CUTOFF_SUPPLIED = "NO_CUTOFF_SUPPLIED"
    ARTIFACT_DATE_UNKNOWN = "ARTIFACT_DATE_UNKNOWN"
    # product
    CURRENT_AVAILABILITY_NOT_HISTORICAL = "CURRENT_AVAILABILITY_NOT_HISTORICAL"
    DATES_ARE_SOURCE_REPORTED = "DATES_ARE_SOURCE_REPORTED"
    PRODUCT_IDENTITY_UNRESOLVED = "PRODUCT_IDENTITY_UNRESOLVED"
    PRODUCT_IDENTITY_PROBABLE_ONLY = "PRODUCT_IDENTITY_PROBABLE_ONLY"
    SOURCE_ROLE_UNKNOWN = "SOURCE_ROLE_UNKNOWN"
    NO_FIRST_PARTY_SOURCE = "NO_FIRST_PARTY_SOURCE"
    # open source
    CREATED_AT_NOT_PROVEN_PUBLIC_SINCE = "CREATED_AT_NOT_PROVEN_PUBLIC_SINCE"
    COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY = "COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY"
    LICENSE_IS_NOT_REUSE_PERMISSION = "LICENSE_IS_NOT_REUSE_PERMISSION"
    LICENSE_UNKNOWN = "LICENSE_UNKNOWN"
    FORK_MAY_DIVERGE_FROM_ROOT = "FORK_MAY_DIVERGE_FROM_ROOT"
    NOT_AN_INDEPENDENT_ROOT = "NOT_AN_INDEPENDENT_ROOT"
    CODE_FRAGMENT_NOT_FULL_FILE = "CODE_FRAGMENT_NOT_FULL_FILE"
    ARCHIVED_REPOSITORY = "ARCHIVED_REPOSITORY"


UNIVERSAL_DISCOVERY_LIMITATIONS: tuple[CandidateLimitation, ...] = (
    CandidateLimitation.NOVELTY_NOT_ASSESSED,
    CandidateLimitation.SAME_INVENTION_NOT_DETERMINED,
    CandidateLimitation.LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED,
    CandidateLimitation.BOUNDED_SEARCH_NOT_EXHAUSTIVE,
    CandidateLimitation.LATER_NOVELTY_COMPARISON_REQUIRED,
    CandidateLimitation.NO_COPYING_DETERMINATION,
)
"""Required on every product and open-source candidate by validator."""


def require_universal_limitations(limitations: list[CandidateLimitation]) -> None:
    missing = [l.value for l in UNIVERSAL_DISCOVERY_LIMITATIONS if l not in limitations]
    if missing:
        raise ValueError(f"a discovery candidate must state its universal limitations; missing {missing}")


class CandidateQueryProvenance(MawhibaModel):
    """Which query surfaced a record. ``retrieval_rank`` is metadata only."""

    query_id: UUID
    purpose: DiscoveryQueryPurpose
    operation: DiscoveryOperation
    language: QueryLanguage
    claim_ids: list[str] = Field(min_length=1)
    component_ids: list[str] = Field(default_factory=list)
    retrieval_rank: int = Field(ge=1)


def coverage_is_honest(
    coverage: DiscoveryCoverageStatus,
    budget: DiscoveryBudget,
    executions: list[DiscoveryQueryExecution],
) -> None:
    if coverage is DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS:
        if budget.truncated:
            raise ValueError("a truncated search cannot report complete coverage (section 34)")
        if any(e.failed for e in executions):
            raise ValueError("a search with a failed query cannot report complete coverage")
        if any(e.provider_reports_more or e.provider_incomplete_results for e in executions):
            raise ValueError("a provider-reported remainder cannot read as complete coverage")
    if coverage is DiscoveryCoverageStatus.NOT_EXECUTED and executions:
        raise ValueError("NOT_EXECUTED must not carry executions")


def outcome_is_honest(
    outcome: DiscoveryOutcome,
    executions: list[DiscoveryQueryExecution],
    has_observations: bool,
) -> None:
    if outcome is DiscoveryOutcome.NOT_RUN and executions:
        raise ValueError("NOT_RUN must not carry executions")
    if outcome is DiscoveryOutcome.EMPTY and has_observations:
        raise ValueError("EMPTY means no record was accepted")
    if outcome is DiscoveryOutcome.FAILED and has_observations:
        raise ValueError("FAILED must not carry observations")
    if outcome is DiscoveryOutcome.SUCCESS and any(e.failed for e in executions):
        raise ValueError("SUCCESS cannot hide a failed query; that is PARTIAL")


def providers_are_honest(
    capabilities: list[DiscoveryProviderCapability], dispatched: set[DiscoveryProvider]
) -> None:
    by_provider = {c.provider: c for c in capabilities}
    for provider in dispatched:
        capability = by_provider.get(provider)
        if capability is None or not capability.operations:
            raise ValueError(f"{provider.value} was dispatched without a dispatchable capability")


__all__ = [
    "CONTENT_HASH_PATTERN",
    "DATE_PATTERN",
    "DISCOVERY_CONTRACT_VERSION",
    "DISCOVERY_PLANNER_VERSION",
    "DISPATCHABLE_ACCESS_STATUSES",
    "MAX_SAFE_SUMMARY_LENGTH",
    "MODEL_ASSISTED_TERM_DERIVATIONS",
    "NO_DISCOVERY_CUTOFF",
    "RETRYABLE_DISCOVERY_ERRORS",
    "SEARCH_OPERATIONS",
    "UNIVERSAL_DISCOVERY_LIMITATIONS",
    "CandidateLimitation",
    "CandidateQueryProvenance",
    "ClaimExclusionReason",
    "DiscoveryBudget",
    "DiscoveryCoverageStatus",
    "DiscoveryCutoff",
    "DiscoveryErrorKind",
    "DiscoveryExecutionStatus",
    "DiscoveryOperation",
    "DiscoveryOutcome",
    "DiscoveryProvider",
    "DiscoveryProviderAccessStatus",
    "DiscoveryProviderCapability",
    "DiscoveryProviderError",
    "DiscoveryQuery",
    "DiscoveryQueryExecution",
    "DiscoveryQueryPurpose",
    "DiscoveryQueryRejectionReason",
    "DiscoveryQueryTerm",
    "DiscoveryTermDerivation",
    "DiscoveryTrack",
    "ExcludedDiscoveryClaim",
    "QueryLanguage",
    "RejectedDiscoveryQuery",
    "coverage_is_honest",
    "outcome_is_honest",
    "providers_are_honest",
    "require_universal_limitations",
    "safe_summary",
    "stable_id",
]
