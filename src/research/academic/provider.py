"""The academic provider seam.

Logic depends on this Protocol, never on an HTTP library and never on a
particular API. A provider is untrusted in exactly the sense Phase 2A
established for the official web provider: whatever it returns is re-validated
by code that does not belong to the provider, so a misbehaving connector cannot
create a verified source.

``BaseAcademicProvider`` holds the shape every connector shares -- transport with
bounded retries, the per-query result limit, and the result envelope -- so a
connector module contains only what is genuinely provider-specific: its request,
its DTOs and its field mapping. The deterministic fakes derive from the same
base, which is why an offline test exercises the real normalization path rather
than a simplified stand-in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from src.research.academic.http import (
    DEFAULT_RETRY_POLICY,
    NoSleep,
    RetryPolicy,
    Sleeper,
    execute_with_retries,
)
from src.research.academic.normalization import (
    NormalizedResponse,
    build_result,
    rejection,
    truncate,
)
from src.schemas.academic import (
    AcademicProvider,
    AcademicRejectionReason,
    AcademicRejectionStage,
    AcademicSearchQuery,
    AcademicSearchResult,
)
from src.workflow.clock import workflow_now

DEFAULT_RESULT_LIMIT = 10


@runtime_checkable
class AcademicSearchProvider(Protocol):
    """One academic search backend."""

    provider_name: AcademicProvider
    connector_version: str

    def search(
        self, query: AcademicSearchQuery, *, limit: int
    ) -> AcademicSearchResult: ...


class BaseAcademicProvider:
    """Transport, limit enforcement and envelope assembly, shared by connectors.

    Subclasses implement ``_fetch`` (one HTTP attempt, raising
    ``AcademicTransportError`` on failure) and ``_normalize`` (provider JSON to
    canonical candidates). Neither ever sees the retry loop or the budget.
    """

    provider_name: ClassVar[AcademicProvider]
    connector_version: ClassVar[str]

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._retry_policy = retry_policy
        # NoSleep by default: nothing in the standard suite may wait in real time.
        self._sleeper: Sleeper = sleeper if sleeper is not None else NoSleep()

    # -- provider-specific ----------------------------------------------------

    def _fetch(self, query: AcademicSearchQuery, limit: int) -> Any:
        raise NotImplementedError

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        raise NotImplementedError

    # -- shared ---------------------------------------------------------------

    def search(
        self, query: AcademicSearchQuery, *, limit: int = DEFAULT_RESULT_LIMIT
    ) -> AcademicSearchResult:
        """Run one query against this provider. Never raises for an API outcome."""
        if query.provider is not self.provider_name:
            raise ValueError(
                f"{self.provider_name.value} cannot execute a query addressed to "
                f"{query.provider.value}"
            )
        effective_limit = max(1, min(limit, query.requested_limit))
        started_at = workflow_now()
        outcome = execute_with_retries(
            lambda: self._fetch(query, effective_limit),
            provider=self.provider_name,
            policy=self._retry_policy,
            sleeper=self._sleeper,
        )
        retrieved_at = workflow_now()

        normalized = NormalizedResponse()
        if outcome.succeeded:
            normalized = self._normalize(query, outcome.payload, retrieved_at)

        # A provider that ignores the limit parameter does not get to widen the
        # budget: the cut is applied here, recorded, and is not a failure.
        kept, dropped = truncate(normalized.candidates, effective_limit)
        rejected = list(normalized.rejected)
        rejected.extend(
            rejection(
                query,
                AcademicRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED,
                stage=AcademicRejectionStage.BUDGET,
                record_id=candidate.provider_record_id,
                summary=candidate.title,
            )
            for candidate in normalized.candidates[len(kept) : len(kept) + dropped]
        )

        return build_result(
            query,
            outcome,
            started_at=started_at,
            completed_at=workflow_now(),
            raw_count=normalized.raw_count,
            candidates=kept,
            rejected=rejected,
        )


__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "AcademicSearchProvider",
    "BaseAcademicProvider",
]
