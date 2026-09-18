"""The patent provider seam -- Phase 2G section 14.

Logic depends on this Protocol, never on an HTTP library and never on a
particular patent office. A provider is untrusted in exactly the sense Phase 2A
established: whatever it returns is re-validated by code that does not belong to
the provider, so a misbehaving connector cannot create a verified publication.

Two things this seam does differently from the academic one, because patent data
differs:

* **Capabilities are declared, not assumed** (section 14). A provider that does
  not expose claims is asked for a search and told nothing else; requesting an
  unsupported operation returns ``UNSUPPORTED_OPERATION`` rather than raising,
  so the pipeline degrades honestly instead of failing.

* **An unavailable answer is never a favourable one.** A family lookup that
  cannot run yields ``FAMILY_DATA_UNAVAILABLE``, and a claims fetch that cannot
  run yields ``NOT_SUPPORTED_BY_PROVIDER`` -- never a silent absence that a
  later phase could read as "nothing relevant there".

``BasePatentProvider`` holds the shape every connector shares -- bounded
retries, the range limit, the result envelope -- so a connector module contains
only what is genuinely provider-specific. The deterministic fakes derive from
the same base, which is why an offline test exercises the real parsing path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from src.research.patent.capabilities import capability_for
from src.research.patent.http import (
    DEFAULT_PATENT_RETRY_POLICY,
    NoSleep,
    PatentTransportError,
    PatentTransportOutcome,
    RetryPolicy,
    Sleeper,
    execute_patent_call,
)
from src.schemas.patent import (
    PATENT_ERROR_TO_SEARCH_STATUS,
    RETRYABLE_PATENT_ERROR_KINDS,
    PatentContentType,
    PatentErrorKind,
    PatentFamilyKind,
    PatentProvider,
    PatentProviderError,
    PatentProviderOperation,
    PatentRejectionReason,
    PatentRateLimitInfo,
    PatentRejectionStage,
    PatentSearchObservation,
    PatentSearchQuery,
    PatentSearchResult,
    PatentSearchStatus,
    PatentTextScope,
    PublicationIdentity,
    RejectedPatentRecord,
)
from src.workflow.clock import workflow_now

DEFAULT_PATENT_RESULT_LIMIT = 10
"""Deliberately small. Every result is a third-party request's worth of data,
and Phase 2G aims at well-provenanced coverage rather than volume (section 26)."""


@dataclass
class ParsedSearchPayload:
    """A connector's normalized view of one search response.

    ``fault`` carries a provider fault that arrived in the response *body*.
    EPO OPS answers some errors with an XML ``<error>`` envelope, and a fault
    body must never be read as "the provider found nothing": those are opposite
    facts, and collapsing them would report a broken search as an empty corpus.
    """

    observations: list[PatentSearchObservation] = field(default_factory=list)
    rejected: list[RejectedPatentRecord] = field(default_factory=list)
    raw_count: int = 0
    provider_reported_total: int | None = None
    fault: tuple[str, str] | None = None


@dataclass
class FamilyPayload:
    """A connector's normalized view of one family response.

    ``available`` is False when the provider does not offer family data for the
    authority at all, which is a different fact from a family call that failed.
    """

    available: bool = True
    family_id: str | None = None
    family_kind: PatentFamilyKind = PatentFamilyKind.UNKNOWN
    members: list[tuple[PublicationIdentity, str | None]] = field(default_factory=list)
    earliest_priority_date: str | None = None
    endpoint: str = ""
    error: PatentProviderError | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass
class TextPayload:
    """A connector's normalized view of one content-type response."""

    text: str | None = None
    language: str | None = None
    scope: PatentTextScope = PatentTextScope.COMPLETE_AS_PROVIDED
    original_char_count: int = 0
    endpoint: str = ""
    operation: PatentProviderOperation = PatentProviderOperation.FETCH_BIBLIOGRAPHIC
    supported: bool = True
    error: PatentProviderError | None = None

    @property
    def available(self) -> bool:
        return self.text is not None


@runtime_checkable
class PatentSearchProvider(Protocol):
    """One patent search backend.

    ``search`` never raises for a provider-level outcome. ``fetch_family`` and
    ``fetch_text`` are optional in behaviour rather than in the Protocol: a
    provider that does not support an operation says so in the payload, which is
    what lets the pipeline treat unsupported and failed as the distinct facts
    they are (section 14).
    """

    provider_name: PatentProvider
    connector_version: str

    def search(
        self, query: PatentSearchQuery, *, limit: int
    ) -> PatentSearchResult: ...

    def fetch_family(self, identity: PublicationIdentity) -> FamilyPayload: ...

    def fetch_text(
        self, identity: PublicationIdentity, content_type: PatentContentType
    ) -> TextPayload: ...


class BasePatentProvider:
    """Transport, range enforcement and envelope assembly, shared by connectors.

    Subclasses implement ``_fetch_search`` (one HTTP attempt, raising
    ``PatentTransportError`` on failure) and ``_parse_search`` (provider XML to
    canonical observations). Neither ever sees the retry loop or the budget.
    """

    provider_name: ClassVar[PatentProvider]
    connector_version: ClassVar[str]

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy = DEFAULT_PATENT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._retry_policy = retry_policy
        # NoSleep by default: nothing in the standard suite may wait in real time.
        self._sleeper: Sleeper = sleeper if sleeper is not None else NoSleep()

    # -- provider-specific ----------------------------------------------------

    def _fetch_search(self, query: PatentSearchQuery, limit: int) -> Any:
        raise NotImplementedError

    def _parse_search(
        self, query: PatentSearchQuery, payload: Any, retrieved_at: datetime
    ) -> ParsedSearchPayload:
        raise NotImplementedError

    def _search_endpoint(self) -> str:
        raise NotImplementedError

    # -- optional capabilities ------------------------------------------------

    def supports(self, operation: PatentProviderOperation) -> bool:
        return capability_for(self.provider_name).supports(operation)

    def fetch_family(self, identity: PublicationIdentity) -> FamilyPayload:
        """Family data for one publication.

        The default is an honest "this provider does not offer it here", which
        is what a connector without a family service should report rather than
        an empty family that reads like a singleton.
        """
        if not self.supports(PatentProviderOperation.FETCH_FAMILY):
            return FamilyPayload(available=False)
        raise NotImplementedError

    def fetch_text(
        self, identity: PublicationIdentity, content_type: PatentContentType
    ) -> TextPayload:
        """Text for one content type of one publication."""
        operation = _TEXT_OPERATIONS[content_type]
        if not self.supports(operation):
            return TextPayload(supported=False, operation=operation)
        raise NotImplementedError

    # -- shared ---------------------------------------------------------------

    def search(
        self, query: PatentSearchQuery, *, limit: int = DEFAULT_PATENT_RESULT_LIMIT
    ) -> PatentSearchResult:
        """Run one query against this provider. Never raises for an API outcome."""
        if query.provider is not self.provider_name:
            raise ValueError(
                f"{self.provider_name.value} cannot execute a query addressed to "
                f"{query.provider.value}"
            )
        endpoint = self._search_endpoint()
        started_at = workflow_now()

        if not self.supports(PatentProviderOperation.SEARCH_PUBLICATIONS):
            return _unsupported_result(query, self.provider_name, endpoint, started_at)

        effective_limit = max(1, min(limit, query.requested_limit))
        outcome = execute_patent_call(
            lambda: self._fetch_search(query, effective_limit),
            provider=self.provider_name,
            operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
            policy=self._retry_policy,
            sleeper=self._sleeper,
        )
        retrieved_at = workflow_now()

        parsed = ParsedSearchPayload()
        if outcome.succeeded:
            parsed = self._parse_search(query, outcome.payload, retrieved_at)
            if parsed.fault is not None:
                # A fault in the body is a failed call, whatever the HTTP status
                # was. Classified from the provider's own fault code rather than
                # guessed, and never reported as EMPTY.
                from src.research.patent.epo_ops import error_kind_for_fault

                code, message = parsed.fault
                return _fault_result(
                    query,
                    self.provider_name,
                    endpoint,
                    started_at,
                    attempts=outcome.attempts,
                    kind=error_kind_for_fault(code, message),
                    code=code,
                    requested_limit=effective_limit,
                )

        # A provider that ignores the requested range does not get to widen the
        # budget: the cut is applied here, recorded, and is not a failure.
        kept = parsed.observations[:effective_limit]
        dropped = parsed.observations[effective_limit:]
        rejected = [
            *parsed.rejected,
            *(
                RejectedPatentRecord(
                    provider=self.provider_name,
                    query_id=query.query_id,
                    stage=PatentRejectionStage.BUDGET,
                    reason=PatentRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED,
                    provider_record_identifier=observation.provider_record_id,
                    safe_summary=observation.publication_key,
                )
                for observation in dropped
            ),
        ]

        return build_patent_result(
            query,
            outcome,
            provider=self.provider_name,
            endpoint=endpoint,
            started_at=started_at,
            completed_at=workflow_now(),
            raw_count=parsed.raw_count,
            observations=kept,
            rejected=rejected,
            provider_reported_total=parsed.provider_reported_total,
            requested_limit=effective_limit,
        )


_TEXT_OPERATIONS: dict[PatentContentType, PatentProviderOperation] = {
    PatentContentType.TITLE: PatentProviderOperation.FETCH_BIBLIOGRAPHIC,
    PatentContentType.ABSTRACT: PatentProviderOperation.FETCH_ABSTRACT,
    PatentContentType.CLAIMS: PatentProviderOperation.FETCH_CLAIMS,
    PatentContentType.DESCRIPTION: PatentProviderOperation.FETCH_DESCRIPTION,
}


def text_operation_for(content_type: PatentContentType) -> PatentProviderOperation:
    return _TEXT_OPERATIONS[content_type]


def _unsupported_result(
    query: PatentSearchQuery,
    provider: PatentProvider,
    endpoint: str,
    started_at: datetime,
) -> PatentSearchResult:
    """The envelope for an operation the provider does not expose.

    A distinct status rather than a generic error: "this provider cannot be
    asked this" is a capability fact, and reporting it as a provider failure
    would make an access-policy boundary look like an outage.
    """
    return PatentSearchResult(
        provider=provider,
        query_id=query.query_id,
        research_run_id=query.research_run_id,
        status=PatentSearchStatus.UNSUPPORTED_OPERATION,
        provider_endpoint=endpoint,
        requested_range_start=query.requested_range_start,
        requested_limit=query.requested_limit,
        errors=[
            PatentProviderError(
                provider=provider,
                kind=PatentErrorKind.UNSUPPORTED_OPERATION,
                retryable=False,
                attempt=1,
                operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
                message=f"{provider.value} exposes no publication search to this system",
            )
        ],
        started_at=started_at,
        completed_at=workflow_now(),
    )


def _fault_result(
    query: PatentSearchQuery,
    provider: PatentProvider,
    endpoint: str,
    started_at: datetime,
    *,
    attempts: int,
    kind: PatentErrorKind,
    code: str,
    requested_limit: int,
) -> PatentSearchResult:
    """The envelope for a provider fault delivered in the response body.

    ``rate_limit`` is populated for a fair-use rejection so the run records the
    back-pressure it met, exactly as it would for an HTTP 429.
    """
    status = PATENT_ERROR_TO_SEARCH_STATUS[kind]
    rate_limit = (
        PatentRateLimitInfo(
            provider=provider,
            limited=True,
            rejection_reason=f"provider fault code {code}" if code else None,
            attempts=attempts,
        )
        if status is PatentSearchStatus.RATE_LIMITED
        else None
    )
    return PatentSearchResult(
        provider=provider,
        query_id=query.query_id,
        research_run_id=query.research_run_id,
        status=status,
        attempts=attempts,
        provider_endpoint=endpoint,
        requested_range_start=query.requested_range_start,
        requested_limit=requested_limit,
        rate_limit=rate_limit,
        errors=[
            PatentProviderError(
                provider=provider,
                kind=kind,
                retryable=kind in RETRYABLE_PATENT_ERROR_KINDS,
                attempt=attempts,
                operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
                message=f"provider returned fault code {code or 'unknown'}",
            )
        ],
        started_at=started_at,
        completed_at=workflow_now(),
    )


def build_patent_result(
    query: PatentSearchQuery,
    outcome: PatentTransportOutcome,
    *,
    provider: PatentProvider,
    endpoint: str,
    started_at: datetime,
    completed_at: datetime,
    raw_count: int,
    observations: list[PatentSearchObservation],
    rejected: list[RejectedPatentRecord],
    provider_reported_total: int | None,
    requested_limit: int,
) -> PatentSearchResult:
    """Assemble the provider-neutral envelope for one query.

    The status is derived from what actually happened rather than asserted by
    the connector: a transport failure keeps its classified status, a success
    with rejected records is ``PARTIAL``, a success with nothing at all is
    ``EMPTY`` -- and ``EMPTY`` is not a failure (section 28).
    """
    failure_status = outcome.status
    if failure_status is not None:
        return PatentSearchResult(
            provider=provider,
            query_id=query.query_id,
            research_run_id=query.research_run_id,
            status=failure_status,
            attempts=outcome.attempts,
            provider_endpoint=endpoint,
            requested_range_start=query.requested_range_start,
            requested_limit=requested_limit,
            raw_count=0,
            rejected_count=0,
            rate_limit=outcome.rate_limit,
            errors=list(outcome.errors),
            started_at=started_at,
            completed_at=completed_at,
        )

    if not observations:
        # No usable record. Distinguished by whether anything was returned at
        # all: a response of five malformed records is not "found nothing".
        if rejected or raw_count:
            return PatentSearchResult(
                provider=provider,
                query_id=query.query_id,
                research_run_id=query.research_run_id,
                status=PatentSearchStatus.INVALID_RESPONSE,
                attempts=outcome.attempts,
                provider_endpoint=endpoint,
                requested_range_start=query.requested_range_start,
                requested_limit=requested_limit,
                raw_count=raw_count,
                rejected_count=len(rejected),
                rejected=rejected,
                provider_reported_total=provider_reported_total,
                errors=[
                    PatentProviderError(
                        provider=provider,
                        kind=PatentErrorKind.PARSE_ERROR,
                        retryable=False,
                        attempt=outcome.attempts,
                        operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
                        message=(
                            f"{raw_count} record(s) returned, none usable; "
                            f"{len(rejected)} rejected"
                        ),
                    )
                ],
                started_at=started_at,
                completed_at=completed_at,
            )
        return PatentSearchResult(
            provider=provider,
            query_id=query.query_id,
            research_run_id=query.research_run_id,
            status=PatentSearchStatus.EMPTY,
            attempts=outcome.attempts,
            provider_endpoint=endpoint,
            requested_range_start=query.requested_range_start,
            requested_limit=requested_limit,
            provider_reported_total=provider_reported_total,
            started_at=started_at,
            completed_at=completed_at,
        )

    return PatentSearchResult(
        provider=provider,
        query_id=query.query_id,
        research_run_id=query.research_run_id,
        status=PatentSearchStatus.PARTIAL if rejected else PatentSearchStatus.SUCCESS,
        attempts=outcome.attempts,
        provider_endpoint=endpoint,
        requested_range_start=query.requested_range_start,
        requested_limit=requested_limit,
        raw_count=raw_count,
        accepted_count=len(observations),
        rejected_count=len(rejected),
        provider_reported_total=provider_reported_total,
        observations=observations,
        rejected=rejected,
        started_at=started_at,
        completed_at=completed_at,
    )


__all__ = [
    "DEFAULT_PATENT_RESULT_LIMIT",
    "BasePatentProvider",
    "FamilyPayload",
    "ParsedSearchPayload",
    "PatentSearchProvider",
    "TextPayload",
    "build_patent_result",
    "text_operation_for",
]
