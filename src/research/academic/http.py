"""Shared transport semantics for academic connectors.

Phase 2A.1 moved the model retry loop to one place because three callers had
begun to grow their own. The same reasoning applies here: the three academic
connectors differ in their endpoints and their JSON, not in what a 429 means, so
retry classification, bounded backoff and the failure envelope live here once.

What is retried is a property of the failure kind, not of the connector:

    retried      timeout, connection reset, 429, 500, 502, 503, 504
    not retried  400, 401, 403, 404, malformed JSON, schema incompatibility

403 is deliberately non-retryable. A provider that documents it as transient
would need its own reviewed decision; guessing would turn an authorization
problem into a retry storm.

Waiting is injected. ``NoSleep`` is the default, so the standard suite exercises
the full backoff path -- including ``Retry-After`` -- without a single real
second passing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.schemas.academic import (
    ERROR_KIND_TO_SEARCH_STATUS,
    RETRYABLE_ERROR_KINDS,
    AcademicErrorKind,
    AcademicProvider,
    AcademicProviderError,
    AcademicSearchStatus,
    RateLimitInfo,
)

logger = logging.getLogger(__name__)

ACADEMIC_TRANSPORT_VERSION = "ACADEMIC-TRANSPORT-V1"

MAX_RETRY_AFTER_SECONDS = 60.0
"""A provider may ask for any wait; this project never honours an unbounded one."""


class Sleeper(Protocol):
    """Anything that can wait between attempts."""

    def sleep(self, seconds: float) -> None: ...


class NoSleep:
    """Deterministic test sleeper: records the waits, never performs them."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)


class RealSleep:
    """Production sleeper."""

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry. There is no unbounded mode and no infinite loop."""

    max_attempts: int = 3
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0
    honour_retry_after: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("backoff seconds cannot be negative")


DEFAULT_RETRY_POLICY = RetryPolicy()


class AcademicTransportError(Exception):
    """A provider attempt that failed. Carries the classified kind, not a body.

    The message is written by this project. A provider response body is never
    echoed into it: a body can contain an echoed request, and an echoed request
    can contain an API key.
    """

    def __init__(
        self,
        kind: AcademicErrorKind,
        message: str,
        *,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(f"[{kind.value}] {message}")
        self.kind = kind
        self.message = message
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_ERROR_KINDS


def classify_http_status(status: int) -> AcademicErrorKind | None:
    """The failure kind for an HTTP status, or ``None`` when it is a success."""
    if 200 <= status < 300:
        return None
    if status == 400:
        return AcademicErrorKind.BAD_REQUEST
    if status == 401:
        return AcademicErrorKind.AUTH_ERROR
    if status == 403:
        return AcademicErrorKind.FORBIDDEN
    if status == 404:
        return AcademicErrorKind.NOT_FOUND
    if status == 429:
        return AcademicErrorKind.RATE_LIMITED
    if status >= 500:
        return AcademicErrorKind.SERVER_ERROR
    return AcademicErrorKind.UNEXPECTED


def parse_retry_after(raw: object) -> float | None:
    """Seconds from a ``Retry-After`` header, bounded. Only the seconds form.

    The HTTP-date form is deliberately unsupported: interpreting it needs a
    clock, and a wrong clock turns a short pause into a long stall.
    """
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def backoff_seconds(policy: RetryPolicy, attempt: int, retry_after: float | None) -> float:
    """Wait before attempt ``attempt + 1``. Exponential, capped, no jitter.

    No jitter on purpose: identical inputs must produce identical waits so the
    deterministic suite can assert them.
    """
    if retry_after is not None and policy.honour_retry_after:
        return min(retry_after, policy.max_backoff_seconds)
    return min(policy.base_backoff_seconds * (2 ** (attempt - 1)), policy.max_backoff_seconds)


@dataclass
class TransportOutcome:
    """The result of trying one provider call up to the retry bound."""

    payload: Any = None
    succeeded: bool = False
    attempts: int = 0
    failure_kind: AcademicErrorKind | None = None
    errors: list[AcademicProviderError] = field(default_factory=list)
    rate_limit: RateLimitInfo | None = None
    waits: list[float] = field(default_factory=list)

    @property
    def status(self) -> AcademicSearchStatus | None:
        """The envelope status for a failure, or ``None`` when the call worked."""
        if self.succeeded or self.failure_kind is None:
            return None
        return ERROR_KIND_TO_SEARCH_STATUS[self.failure_kind]


def execute_with_retries(
    call: Callable[[], Any],
    *,
    provider: AcademicProvider,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    sleeper: Sleeper | None = None,
) -> TransportOutcome:
    """Call a provider, retrying only what a retry can plausibly fix.

    Never raises for a provider-level outcome: a failure is data, so one broken
    provider cannot abort the branch (ADR-008).
    """
    sleeper = sleeper if sleeper is not None else NoSleep()
    outcome = TransportOutcome()

    while outcome.attempts < policy.max_attempts:
        outcome.attempts += 1
        try:
            outcome.payload = call()
        except AcademicTransportError as exc:
            outcome.failure_kind = exc.kind
            outcome.errors.append(
                AcademicProviderError(
                    provider=provider,
                    kind=exc.kind,
                    retryable=exc.retryable,
                    attempt=outcome.attempts,
                    http_status=exc.http_status,
                    message=exc.message,
                )
            )
            if exc.kind is AcademicErrorKind.RATE_LIMITED:
                outcome.rate_limit = RateLimitInfo(
                    provider=provider,
                    limited=True,
                    http_status=exc.http_status,
                    retry_after_seconds=exc.retry_after_seconds,
                    attempts=outcome.attempts,
                )
            if not exc.retryable or outcome.attempts >= policy.max_attempts:
                break
            wait = backoff_seconds(policy, outcome.attempts, exc.retry_after_seconds)
            outcome.waits.append(wait)
            sleeper.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001 -- a provider fault is an outcome
            outcome.failure_kind = AcademicErrorKind.UNEXPECTED
            outcome.errors.append(
                AcademicProviderError(
                    provider=provider,
                    kind=AcademicErrorKind.UNEXPECTED,
                    retryable=False,
                    attempt=outcome.attempts,
                    message=f"provider raised {type(exc).__name__}",
                )
            )
            break

        outcome.succeeded = True
        outcome.failure_kind = None
        break

    logger.debug(
        "academic provider call: provider=%s attempts=%s succeeded=%s kind=%s",
        provider.value,
        outcome.attempts,
        outcome.succeeded,
        outcome.failure_kind.value if outcome.failure_kind else None,
    )
    return outcome


__all__ = [
    "ACADEMIC_TRANSPORT_VERSION",
    "DEFAULT_RETRY_POLICY",
    "AcademicTransportError",
    "NoSleep",
    "RealSleep",
    "RetryPolicy",
    "Sleeper",
    "TransportOutcome",
    "backoff_seconds",
    "classify_http_status",
    "execute_with_retries",
    "parse_retry_after",
]
