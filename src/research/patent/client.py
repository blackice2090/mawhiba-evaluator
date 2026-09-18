"""The live EPO OPS client -- Phase 2G sections 2, 27.

The only module in Phase 2G that performs network I/O. Everything it returns
goes through the same parsers the offline fakes use, so what an offline test
proves about normalization holds for the live connector too.

Credential handling, stated once and enforced here:

* the consumer key and secret come from the environment through
  ``EpoOpsCredentials``, never from a file in the repository and never from
  graph state;
* HTTP Basic authenticates the token endpoint only; every REST operation carries
  the bearer token;
* no token, key or secret is ever logged, put into an exception message, stored
  on an observation, or written into a recorded endpoint string -- the endpoints
  recorded on state are the documented operation paths;
* a response body is never echoed into an error message, because an OPS fault
  can quote the request that produced it (section 27).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.research.patent.epo_ops import (
    EPO_OPS_AUTH_GRANT_TYPE,
    EPO_OPS_AUTH_PATH,
    EPO_OPS_CONNECTOR_VERSION,
    EPO_OPS_RANGE_HEADER,
    EPO_OPS_SEARCH_OPERATION,
    ParsedOpsFamily,
    build_content_request,
    build_family_request,
    build_search_request,
    content_hash,
    error_kind_for_fault,
    normalize_patent_text,
    parse_ops_family_response,
    parse_ops_fault,
    parse_ops_search_response,
    parse_ops_text_response,
)
from src.research.patent.http import (
    DEFAULT_PATENT_RETRY_POLICY,
    EPO_REJECTION_HEADER,
    PatentTransportError,
    RetryPolicy,
    Sleeper,
    classify_patent_status,
    execute_patent_call,
    parse_retry_after,
)
from src.research.patent.provider import (
    BasePatentProvider,
    FamilyPayload,
    ParsedSearchPayload,
    TextPayload,
    text_operation_for,
)
from src.schemas.patent import (
    PatentContentType,
    PatentErrorKind,
    PatentFamilyKind,
    PatentProvider,
    PatentProviderOperation,
    PatentSearchQuery,
    PublicationIdentity,
)
from src.workflow.clock import workflow_now

logger = logging.getLogger(__name__)

EPO_OPS_KEY_ENV = "EPO_OPS_CONSUMER_KEY"
EPO_OPS_SECRET_ENV = "EPO_OPS_CONSUMER_SECRET"

DEFAULT_EPO_TIMEOUT_SECONDS = 30.0

TOKEN_EXPIRY_MARGIN_SECONDS = 60.0
"""Refresh a little early. A token that expires mid-request would surface as an
authentication failure and be misread as a credential problem."""


@dataclass(frozen=True)
class EpoOpsCredentials:
    """EPO developer-portal consumer credentials.

    A frozen dataclass passed through runtime config rather than a field on any
    Pydantic model, for the same reason ``ResearchPrivacyContext`` is: it must
    never be checkpointed. ``__repr__`` is overridden so a stray log line or a
    debugger cannot print the secret.
    """

    consumer_key: str
    consumer_secret: str

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return "EpoOpsCredentials(consumer_key='***', consumer_secret='***')"

    __str__ = __repr__

    @classmethod
    def from_environment(cls) -> EpoOpsCredentials | None:
        """Credentials from the environment, or ``None`` when unset.

        ``None`` is the ordinary case: the standard suite runs without
        credentials, and a run without them reports ``BLOCKED_AUTH`` rather than
        issuing anonymous requests against a quota-limited tier.
        """
        key = (os.environ.get(EPO_OPS_KEY_ENV) or "").strip()
        secret = (os.environ.get(EPO_OPS_SECRET_ENV) or "").strip()
        if not key or not secret:
            return None
        return cls(consumer_key=key, consumer_secret=secret)


@dataclass
class _Token:
    value: str
    expires_at: datetime

    def valid_at(self, now: datetime) -> bool:
        return now < self.expires_at - timedelta(seconds=TOKEN_EXPIRY_MARGIN_SECONDS)


def _transport_error_from_response(
    status_code: int, headers: Any, operation: PatentProviderOperation
) -> PatentTransportError:
    """Classify an HTTP failure without touching the response body."""
    rejection = None
    try:
        rejection = headers.get(EPO_REJECTION_HEADER)
    except AttributeError:  # pragma: no cover - defensive
        rejection = None
    kind = classify_patent_status(status_code, rejection_reason=rejection)
    retry_after = None
    try:
        retry_after = parse_retry_after(headers.get("Retry-After"))
    except AttributeError:  # pragma: no cover - defensive
        retry_after = None
    return PatentTransportError(
        kind or PatentErrorKind.PROVIDER_ERROR,
        f"EPO OPS answered HTTP {status_code}",
        http_status=status_code,
        retry_after_seconds=retry_after,
        rejection_reason=rejection,
        operation=operation,
    )


class EpoOpsClient(BasePatentProvider):
    """The live EPO OPS connector.

    Constructed with credentials; a run without them does not construct one.
    ``httpx`` is imported lazily inside the request path so that importing this
    module -- which the capability table does -- never pulls in a transport.
    """

    provider_name = PatentProvider.EPO_OPS
    connector_version = EPO_OPS_CONNECTOR_VERSION

    def __init__(
        self,
        credentials: EpoOpsCredentials,
        *,
        timeout_seconds: float = DEFAULT_EPO_TIMEOUT_SECONDS,
        retry_policy: RetryPolicy = DEFAULT_PATENT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
        client: Any = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy, sleeper=sleeper)
        self._credentials = credentials
        self._timeout = timeout_seconds
        self._client = client
        self._token: _Token | None = None

    # -- transport ------------------------------------------------------------

    def _http(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _bearer_token(self) -> str:
        """A valid bearer token, fetched or reused.

        Reused until shortly before expiry: a token request per search would
        double the request count against a fair-use limited service for no
        benefit (section 27).
        """
        now = workflow_now()
        if self._token is not None and self._token.valid_at(now):
            return self._token.value

        response = self._http().post(
            EPO_OPS_AUTH_PATH,
            data={"grant_type": EPO_OPS_AUTH_GRANT_TYPE},
            headers={"Accept": "application/json"},
            auth=(self._credentials.consumer_key, self._credentials.consumer_secret),
        )
        if response.status_code >= 400:
            raise _transport_error_from_response(
                response.status_code,
                response.headers,
                PatentProviderOperation.SEARCH_PUBLICATIONS,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise PatentTransportError(
                PatentErrorKind.PARSE_ERROR,
                "EPO OPS token response was not JSON",
            ) from exc
        token = str(body.get("access_token") or "").strip()
        if not token:
            raise PatentTransportError(
                PatentErrorKind.AUTHENTICATION_ERROR,
                "EPO OPS token response carried no access token",
            )
        try:
            lifetime = float(body.get("expires_in") or 0.0)
        except (TypeError, ValueError):
            lifetime = 0.0
        self._token = _Token(
            value=token,
            expires_at=now + timedelta(seconds=max(lifetime, TOKEN_EXPIRY_MARGIN_SECONDS * 2)),
        )
        return token

    def _get(
        self, url: str, *, params: dict[str, str], headers: dict[str, str],
        operation: PatentProviderOperation,
    ) -> str:
        """One authorized GET. Returns the body text, or raises a classified error."""
        sent = {**headers, "Authorization": f"Bearer {self._bearer_token()}"}
        response = self._http().get(url, params=params or None, headers=sent)
        if response.status_code >= 400:
            raise _transport_error_from_response(
                response.status_code, response.headers, operation
            )
        body = response.text
        fault = parse_ops_fault(body)
        if fault is not None:
            code, message = fault
            # A 200 carrying an OPS fault is still a failure. The provider's own
            # message is short and fault-specific, so it is safe to classify
            # from -- but it is not stored, only classified.
            raise PatentTransportError(
                error_kind_for_fault(code, message),
                f"EPO OPS returned fault code {code or 'unknown'}",
                operation=operation,
            )
        return body

    # -- search ---------------------------------------------------------------

    def _search_endpoint(self) -> str:
        return EPO_OPS_SEARCH_OPERATION

    def _fetch_search(self, query: PatentSearchQuery, limit: int) -> Any:
        request = build_search_request(
            query.model_copy(update={"requested_limit": limit})
        )
        return self._get(
            request.url,
            params=request.params,
            headers={
                "Accept": "application/xml",
                EPO_OPS_RANGE_HEADER: request.headers[EPO_OPS_RANGE_HEADER],
            },
            operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
        )

    def _parse_search(
        self, query: PatentSearchQuery, payload: Any, retrieved_at: datetime
    ) -> ParsedSearchPayload:
        parsed = parse_ops_search_response(query, payload, retrieved_at)
        return ParsedSearchPayload(
            observations=parsed.observations,
            rejected=parsed.rejected,
            raw_count=parsed.raw_count,
            provider_reported_total=parsed.provider_reported_total,
            fault=parsed.fault,
        )

    # -- family ---------------------------------------------------------------

    def fetch_family(self, identity: PublicationIdentity) -> FamilyPayload:
        if not self.supports(PatentProviderOperation.FETCH_FAMILY):
            return FamilyPayload(available=False)
        request = build_family_request(identity)
        outcome = execute_patent_call(
            lambda: self._get(
                request.url,
                params={},
                headers={"Accept": "application/xml"},
                operation=PatentProviderOperation.FETCH_FAMILY,
            ),
            provider=self.provider_name,
            operation=PatentProviderOperation.FETCH_FAMILY,
            policy=self._retry_policy,
            sleeper=self._sleeper,
        )
        if not outcome.succeeded:
            return FamilyPayload(
                endpoint=request.documented_operation,
                error=outcome.errors[-1] if outcome.errors else None,
            )
        return _family_payload(
            parse_ops_family_response(outcome.payload), request.documented_operation
        )

    # -- text -----------------------------------------------------------------

    def fetch_text(
        self, identity: PublicationIdentity, content_type: PatentContentType
    ) -> TextPayload:
        operation = text_operation_for(content_type)
        if not self.supports(operation):
            return TextPayload(supported=False, operation=operation)
        request = build_content_request(identity, content_type)
        outcome = execute_patent_call(
            lambda: self._get(
                request.url,
                params={},
                headers={"Accept": "application/xml"},
                operation=operation,
            ),
            provider=self.provider_name,
            operation=operation,
            policy=self._retry_policy,
            sleeper=self._sleeper,
        )
        if not outcome.succeeded:
            return TextPayload(
                endpoint=request.documented_operation,
                operation=operation,
                error=outcome.errors[-1] if outcome.errors else None,
            )
        raw, language = parse_ops_text_response(outcome.payload, content_type)
        if raw is None:
            # The provider answered and this authority does not publish this
            # constituent. Recorded as an absence, never substituted.
            return TextPayload(
                endpoint=request.documented_operation, operation=operation
            )
        text, scope, original = normalize_patent_text(raw)
        return TextPayload(
            text=text,
            language=language,
            scope=scope,
            original_char_count=original,
            endpoint=request.documented_operation,
            operation=operation,
        )


def _family_payload(parsed: ParsedOpsFamily, endpoint: str) -> FamilyPayload:
    if parsed.fault is not None:
        return FamilyPayload(endpoint=endpoint, available=True, members=[])
    return FamilyPayload(
        available=True,
        family_id=parsed.family_id,
        family_kind=PatentFamilyKind.EXTENDED_INPADOC,
        members=list(parsed.members),
        earliest_priority_date=parsed.earliest_priority_date,
        endpoint=endpoint,
    )


def snapshot_hash(text: str) -> str:
    """Re-exported so callers hash exactly as the connector does."""
    return content_hash(text)


__all__ = [
    "DEFAULT_EPO_TIMEOUT_SECONDS",
    "EPO_OPS_KEY_ENV",
    "EPO_OPS_SECRET_ENV",
    "EpoOpsClient",
    "EpoOpsCredentials",
    "snapshot_hash",
]
