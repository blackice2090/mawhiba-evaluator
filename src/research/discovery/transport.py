"""Bounded retry for Phase 2H providers -- section 32.

Reuses the Phase 2B backoff arithmetic (``RetryPolicy``, ``backoff_seconds``,
``parse_retry_after``, ``NoSleep``) rather than restating it; what differs is
the error vocabulary, so classification lives here.

Only transient kinds are retried. A provider failure is returned as data, so
one failing query never aborts the track and never discards another query's
success.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.research.academic.http import (
    NoSleep,
    RetryPolicy,
    Sleeper,
    backoff_seconds,
    parse_retry_after,
)
from src.schemas.discovery import (
    RETRYABLE_DISCOVERY_ERRORS,
    DiscoveryErrorKind,
    DiscoveryProviderError,
    safe_summary,
)


class DiscoveryTransportError(Exception):
    """A classified provider failure. Never carries a provider body or a credential."""

    def __init__(
        self,
        kind: DiscoveryErrorKind,
        message: str = "",
        *,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(f"[{kind.value}] {message}")
        self.kind = kind
        self.message = safe_summary(message)
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


def classify_status(
    status: int, headers: dict[str, str] | None = None
) -> DiscoveryErrorKind | None:
    """The failure kind for an HTTP status, or None for success.

    403 is ambiguous on GitHub: it is both "forbidden" and a rate limit. It is
    a rate limit only when the provider says so -- ``retry-after`` present or
    ``x-ratelimit-remaining`` at zero -- and an authentication error otherwise.
    A 429 whose remaining quota header reads zero for a long window is a quota
    limit, not a transient rate limit.
    """
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if 200 <= status < 300:
        return None
    if status == 401:
        return DiscoveryErrorKind.AUTHENTICATION_ERROR
    if status == 403:
        remaining = headers.get("x-ratelimit-remaining", "").split(",")[0].strip()
        if "retry-after" in headers or remaining == "0":
            return DiscoveryErrorKind.RATE_LIMITED
        return DiscoveryErrorKind.AUTHENTICATION_ERROR
    if status == 429:
        parts = [p.strip() for p in headers.get("x-ratelimit-remaining", "").split(",")]
        if len(parts) > 1 and parts[-1] == "0":
            return DiscoveryErrorKind.QUOTA_LIMITED
        return DiscoveryErrorKind.RATE_LIMITED
    if status == 402:
        return DiscoveryErrorKind.QUOTA_LIMITED
    if status in (400, 422):
        return DiscoveryErrorKind.INVALID_QUERY
    if status == 404:
        # Not found: the resource does not exist at this address. Not transient.
        return DiscoveryErrorKind.UNSUPPORTED_OPERATION
    if status >= 500:
        return DiscoveryErrorKind.PROVIDER_ERROR
    return DiscoveryErrorKind.PROVIDER_ERROR


def retry_after_from(headers: dict[str, str] | None) -> float | None:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    return parse_retry_after(headers.get("retry-after"))


@dataclass
class CallOutcome:
    payload: Any = None
    succeeded: bool = False
    attempts: int = 0
    errors: list[DiscoveryProviderError] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)

    @property
    def final_error(self) -> DiscoveryErrorKind | None:
        return self.errors[-1].kind if self.errors and not self.succeeded else None


def call_with_retries(
    call: Callable[[], Any],
    *,
    max_attempts: int,
    policy: RetryPolicy | None = None,
    sleeper: Sleeper | None = None,
) -> CallOutcome:
    """Call once, retrying only transient failures, never more than ``max_attempts``."""
    policy = policy or RetryPolicy(max_attempts=max_attempts)
    sleeper = sleeper if sleeper is not None else NoSleep()
    outcome = CallOutcome()
    while outcome.attempts < max_attempts:
        outcome.attempts += 1
        try:
            outcome.payload = call()
        except DiscoveryTransportError as exc:
            retryable = exc.kind in RETRYABLE_DISCOVERY_ERRORS
            outcome.errors.append(
                DiscoveryProviderError(
                    kind=exc.kind,
                    attempt=outcome.attempts,
                    retryable=retryable,
                    http_status=exc.http_status,
                    message=exc.message,
                )
            )
            if not retryable or outcome.attempts >= max_attempts:
                break
            wait = backoff_seconds(policy, outcome.attempts, exc.retry_after_seconds)
            outcome.waits.append(wait)
            sleeper.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001 -- a provider fault is an outcome
            outcome.errors.append(
                DiscoveryProviderError(
                    kind=DiscoveryErrorKind.PROVIDER_ERROR,
                    attempt=outcome.attempts,
                    retryable=True,
                    message=f"provider raised {type(exc).__name__}",
                )
            )
            if outcome.attempts >= max_attempts:
                break
            continue
        outcome.succeeded = True
        break
    return outcome


__all__ = [
    "CallOutcome",
    "DiscoveryTransportError",
    "call_with_retries",
    "classify_status",
    "retry_after_from",
]
