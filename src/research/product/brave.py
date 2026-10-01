"""Brave Search API web-search connector -- section 5.

Contract (verified 2026-10-01 against the official get-started documentation;
documented-only until a live request succeeds):

    GET https://api.search.brave.com/res/v1/web/search
    X-Subscription-Token: <key>          required
    q, count (<= 20), offset (page index <= 9), search_lang, country
    -> web.results[]: title, url, description, age?, page_age?
       query.more_results_available

A Brave result is a *discovery observation*. The snippet is the provider's
excerpt, never product truth, and ``age``/``page_age`` are a search-provider
date, never the page's publication date (section 18).

The key lives only on the connector instance. It is never placed on the run,
never logged and never echoed into an error.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.research.discovery.capabilities import (
    BRAVE_AUTH_HEADER,
    BRAVE_MAX_COUNT,
    BRAVE_MAX_OFFSET,
    BRAVE_WEB_SEARCH_URL,
)
from src.research.discovery.execution import SearchPage
from src.research.discovery.transport import (
    DiscoveryTransportError,
    classify_status,
    retry_after_from,
)
from src.schemas.discovery import DiscoveryErrorKind, DiscoveryQuery, QueryLanguage


class WebSearchHit:
    __slots__ = ("url", "title", "snippet", "provider_date")

    def __init__(self, url: str, title: str = "", snippet: str = "", provider_date: str | None = None) -> None:
        self.url = url
        self.title = title
        self.snippet = snippet
        self.provider_date = provider_date


class WebSearchProvider(Protocol):
    """Anything that can answer one page of one web query."""

    def search(self, query: DiscoveryQuery, *, page: int, count: int) -> SearchPage: ...


def parse_brave_response(payload: Any) -> SearchPage:
    """Brave JSON -> SearchPage of ``WebSearchHit``. Unknown keys are ignored."""
    if not isinstance(payload, dict):
        raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "response is not an object")
    web = payload.get("web") or {}
    results = web.get("results") if isinstance(web, dict) else None
    if results is None:
        results = []
    if not isinstance(results, list):
        raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "web.results is not a list")
    hits: list[WebSearchHit] = []
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        date = item.get("page_age") or item.get("age")
        hits.append(
            WebSearchHit(
                url=item["url"],
                title=str(item.get("title") or "")[:512],
                snippet=str(item.get("description") or "")[:1000],
                provider_date=str(date)[:64] if date else None,
            )
        )
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    return SearchPage(items=hits, more_available=bool(query.get("more_results_available")))


class BraveWebSearchProvider:
    provider_name = "BRAVE_WEB_SEARCH"

    def __init__(self, api_key: str, client: Any | None = None, *, timeout_seconds: float = 15.0) -> None:
        if not api_key:
            raise ValueError("a Brave Search API key is required")
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        return "BraveWebSearchProvider(api_key=<redacted>)"

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout, trust_env=False)
        return self._client

    @staticmethod
    def build_params(query: DiscoveryQuery, *, page: int, count: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": query.query_text,
            "count": min(count, BRAVE_MAX_COUNT),
            "offset": min(page - 1, BRAVE_MAX_OFFSET),
        }
        if query.language is QueryLanguage.AR:
            params["search_lang"] = "ar"
        elif query.language is QueryLanguage.EN:
            params["search_lang"] = "en"
        return params

    def search(self, query: DiscoveryQuery, *, page: int, count: int) -> SearchPage:
        import httpx

        if page - 1 > BRAVE_MAX_OFFSET:
            raise DiscoveryTransportError(DiscoveryErrorKind.UNSUPPORTED_OPERATION, "offset beyond provider maximum")
        try:
            response = self.client.get(
                BRAVE_WEB_SEARCH_URL,
                params=self.build_params(query, page=page, count=count),
                headers={"Accept": "application/json", BRAVE_AUTH_HEADER: self._api_key},
            )
        except httpx.TimeoutException as exc:
            raise DiscoveryTransportError(DiscoveryErrorKind.TIMEOUT, "request timed out") from exc
        except httpx.HTTPError as exc:
            raise DiscoveryTransportError(DiscoveryErrorKind.CONNECTION_ERROR, type(exc).__name__) from exc
        headers = dict(response.headers)
        kind = classify_status(response.status_code, headers)
        if kind is not None:
            raise DiscoveryTransportError(
                kind, f"HTTP {response.status_code}",
                http_status=response.status_code, retry_after_seconds=retry_after_from(headers),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "malformed JSON") from exc
        return parse_brave_response(payload)


__all__ = ["BraveWebSearchProvider", "WebSearchHit", "WebSearchProvider", "parse_brave_response"]
