"""Transport semantics for patent connectors -- Phase 2G sections 27, 28.

This module reuses the Phase 2A.1/2B retry layer rather than growing a second
one. ``classify_http_status``, ``parse_retry_after`` and ``backoff_seconds`` in
``src.research.academic.http`` are pure functions over integers and floats; they
are imported and used directly here, so there is exactly one place in the
repository that decides what a 429 means and how long to wait for it.

What is genuinely patent-specific, and therefore lives here:

* the **error vocabulary**. ``PatentErrorKind`` distinguishes
  ``FAIR_USE_REJECTED`` from a plain 403 and ``INVALID_QUERY`` from a plain 400,
  because EPO OPS answers a quota violation with 403 plus an
  ``X-Rejection-Reason`` header and a malformed CQL expression with 400. Those
  need different handling and different reporting.

* **what is retried**. Transport faults, 429 and 5xx are retried. A
  deterministically invalid query is not, because an identical second request
  produces the identical rejection (section 28). A fair-use rejection is not
  either: retrying inside the same run would be evading a documented limit
  rather than recovering from a fault (section 27).

Waiting is injected. ``NoSleep`` is the default, so the standard suite exercises
the whole backoff path without a real second passing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.research.academic.http import (
    MAX_RETRY_AFTER_SECONDS,
    NoSleep,
    RealSleep,
    RetryPolicy,
    Sleeper,
    backoff_seconds,
    classify_http_status,
    parse_retry_after,
)
from src.schemas.academic import AcademicErrorKind
from src.schemas.patent import (
    PATENT_ERROR_TO_SEARCH_STATUS,
    RETRYABLE_PATENT_ERROR_KINDS,
    PatentErrorKind,
    PatentProvider,
    PatentProviderError,
    PatentProviderOperation,
    PatentRateLimitInfo,
    PatentSearchStatus,
)

logger = logging.getLogger(__name__)

PATENT_TRANSPORT_VERSION = "PATENT-TRANSPORT-V1"

DEFAULT_PATENT_RETRY_POLICY = RetryPolicy(max_attempts=3, base_backoff_seconds=0.5)
"""Bounded, and deliberately modest.

Section 27 forbids aggressive parallelism and evasion of provider limits. Three
attempts with exponential backoff recovers a blip; it does not hammer an office.
"""

EPO_REJECTION_HEADER = "X-Rejection-Reason"
"""The header EPO OPS sets on a fair-use rejection, e.g. ``AnonymousQuotaPerDay``.

Its presence is what distinguishes a quota rejection from an authorization
failure, since both arrive as HTTP 403.
"""

_ACADEMIC_TO_PATENT_KIND: dict[AcademicErrorKind, PatentErrorKind] = {
    AcademicErrorKind.TIMEOUT: PatentErrorKind.TIMEOUT,
    AcademicErrorKind.CONNECTION_ERROR: PatentErrorKind.CONNECTION_ERROR,
    AcademicErrorKind.RATE_LIMITED: PatentErrorKind.RATE_LIMITED,
    AcademicErrorKind.SERVER_ERROR: PatentErrorKind.SERVER_ERROR,
    AcademicErrorKind.AUTH_ERROR: PatentErrorKind.AUTHENTICATION_ERROR,
    AcademicErrorKind.PAYMENT_REQUIRED: PatentErrorKind.FORBIDDEN,
    AcademicErrorKind.FORBIDDEN: PatentErrorKind.FORBIDDEN,
    AcademicErrorKind.NOT_FOUND: PatentErrorKind.NOT_FOUND,
    AcademicErrorKind.BAD_REQUEST: PatentErrorKind.INVALID_QUERY,
    AcademicErrorKind.UNPROCESSABLE_REQUEST: PatentErrorKind.INVALID_QUERY,
    AcademicErrorKind.INVALID_RESPONSE: PatentErrorKind.PARSE_ERROR,
    AcademicErrorKind.SCHEMA_INCOMPATIBLE: PatentErrorKind.PARSE_ERROR,
    AcademicErrorKind.UNEXPECTED: PatentErrorKind.UNEXPECTED,
}


def classify_patent_status(
    status: int, *, rejection_reason: str | None = None
) -> PatentErrorKind | None:
    """The patent failure kind for an HTTP status, or ``None`` on success.

    Delegates the status taxonomy to the shared classifier and then applies the
    one patent-specific refinement: a 403 carrying a provider rejection reason
    is a fair-use rejection, not an authorization failure. The distinction
    matters because the operator response differs -- wait and reduce volume
    versus fix the credentials.
    """
    academic_kind = classify_http_status(status)
    if academic_kind is None:
        return None
    if status == 403 and rejection_reason:
        return PatentErrorKind.FAIR_USE_REJECTED
    return _ACADEMIC_TO_PATENT_KIND[academic_kind]


class PatentTransportError(Exception):
    """A provider attempt that failed. Carries the classified kind, not a body.

    The message is written by this project. A provider response body is never
    echoed into it: an OPS fault can include the request, and a request carries
    an ``Authorization`` header (section 27).
    """

    def __init__(
        self,
        kind: PatentErrorKind,
        message: str,
        *,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        rejection_reason: str | None = None,
        operation: PatentProviderOperation | None = None,
    ) -> None:
        super().__init__(f"[{kind.value}] {message}")
        self.kind = kind
        self.message = message
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.rejection_reason = rejection_reason
        self.operation = operation

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_PATENT_ERROR_KINDS


@dataclass
class PatentTransportOutcome:
    """The result of trying one provider call up to the retry bound."""

    payload: Any = None
    succeeded: bool = False
    attempts: int = 0
    failure_kind: PatentErrorKind | None = None
    errors: list[PatentProviderError] = field(default_factory=list)
    rate_limit: PatentRateLimitInfo | None = None
    waits: list[float] = field(default_factory=list)

    @property
    def status(self) -> PatentSearchStatus | None:
        """The envelope status for a failure, or ``None`` when the call worked."""
        if self.succeeded or self.failure_kind is None:
            return None
        return PATENT_ERROR_TO_SEARCH_STATUS[self.failure_kind]

    @property
    def retried(self) -> bool:
        return self.attempts > 1


def execute_patent_call(
    call: Callable[[], Any],
    *,
    provider: PatentProvider,
    operation: PatentProviderOperation,
    policy: RetryPolicy = DEFAULT_PATENT_RETRY_POLICY,
    sleeper: Sleeper | None = None,
) -> PatentTransportOutcome:
    """Call a provider, retrying only what a retry can plausibly fix.

    Never raises for a provider-level outcome: a failure is data, so one broken
    provider or one broken query cannot abort the branch or corrupt the
    observations another query already produced (section 28).
    """
    sleeper = sleeper if sleeper is not None else NoSleep()
    outcome = PatentTransportOutcome()

    while outcome.attempts < policy.max_attempts:
        outcome.attempts += 1
        try:
            outcome.payload = call()
        except PatentTransportError as exc:
            outcome.failure_kind = exc.kind
            outcome.errors.append(
                PatentProviderError(
                    provider=provider,
                    kind=exc.kind,
                    retryable=exc.retryable,
                    attempt=outcome.attempts,
                    http_status=exc.http_status,
                    operation=exc.operation or operation,
                    message=exc.message,
                )
            )
            if exc.kind in (
                PatentErrorKind.RATE_LIMITED,
                PatentErrorKind.FAIR_USE_REJECTED,
            ):
                outcome.rate_limit = PatentRateLimitInfo(
                    provider=provider,
                    limited=True,
                    http_status=exc.http_status,
                    retry_after_seconds=exc.retry_after_seconds,
                    rejection_reason=exc.rejection_reason,
                    attempts=outcome.attempts,
                )
            if not exc.retryable or outcome.attempts >= policy.max_attempts:
                break
            wait = backoff_seconds(policy, outcome.attempts, exc.retry_after_seconds)
            outcome.waits.append(wait)
            sleeper.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001 -- a provider fault is an outcome
            outcome.failure_kind = PatentErrorKind.UNEXPECTED
            outcome.errors.append(
                PatentProviderError(
                    provider=provider,
                    kind=PatentErrorKind.UNEXPECTED,
                    retryable=False,
                    attempt=outcome.attempts,
                    operation=operation,
                    message=f"provider raised {type(exc).__name__}",
                )
            )
            break

        outcome.succeeded = True
        outcome.failure_kind = None
        break

    logger.debug(
        "patent provider call: provider=%s operation=%s attempts=%s succeeded=%s kind=%s",
        provider.value,
        operation.value,
        outcome.attempts,
        outcome.succeeded,
        outcome.failure_kind.value if outcome.failure_kind else None,
    )
    return outcome


__all__ = [
    "DEFAULT_PATENT_RETRY_POLICY",
    "EPO_REJECTION_HEADER",
    "MAX_RETRY_AFTER_SECONDS",
    "PATENT_TRANSPORT_VERSION",
    "NoSleep",
    "PatentTransportError",
    "PatentTransportOutcome",
    "RealSleep",
    "RetryPolicy",
    "Sleeper",
    "backoff_seconds",
    "classify_patent_status",
    "execute_patent_call",
    "parse_retry_after",
]
