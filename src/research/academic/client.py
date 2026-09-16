"""A minimal JSON HTTP client for academic connectors.

One place turns transport reality into the project's failure vocabulary, so the
three connectors classify a timeout, a 429 and a non-JSON body identically.

``httpx`` is imported inside the methods, exactly as the official web provider
does it, so importing a connector module costs nothing and the standard suite
never touches the network.
"""

from __future__ import annotations

from typing import Any

from src.research.academic.http import (
    AcademicTransportError,
    classify_http_status,
    parse_retry_after,
)
from src.schemas.academic import AcademicErrorKind

USER_AGENT = "mawhiba-evaluator-academic-research/1.0"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 8_000_000


class JsonHttpClient:
    """GET JSON from one API. Raises ``AcademicTransportError``, nothing else.

    An error message is composed here from the status code alone. A provider
    body is never echoed into it: a body can repeat the request, and a request
    can carry an API key.
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: Any | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        headers: dict[str, str] | None = None,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        self._headers.update(headers or {})
        self._max_bytes = max_bytes

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)
        return self._client

    def get_json(self, path: str, params: dict[str, Any]) -> Any:
        import httpx

        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            response = self.client.get(url, params=params, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise AcademicTransportError(
                AcademicErrorKind.TIMEOUT, f"request timed out ({type(exc).__name__})"
            ) from exc
        except httpx.HTTPError as exc:
            raise AcademicTransportError(
                AcademicErrorKind.CONNECTION_ERROR,
                f"transport failure ({type(exc).__name__})",
            ) from exc

        status = int(response.status_code)
        kind = classify_http_status(status)
        if kind is not None:
            raise AcademicTransportError(
                kind,
                f"provider returned HTTP {status}",
                http_status=status,
                retry_after_seconds=parse_retry_after(
                    response.headers.get("retry-after")
                ),
            )

        content = response.content
        if len(content) > self._max_bytes:
            raise AcademicTransportError(
                AcademicErrorKind.INVALID_RESPONSE,
                "response exceeds the configured size limit",
                http_status=status,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AcademicTransportError(
                AcademicErrorKind.INVALID_RESPONSE,
                "response body is not valid JSON",
                http_status=status,
            ) from exc


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "MAX_RESPONSE_BYTES", "USER_AGENT", "JsonHttpClient"]
