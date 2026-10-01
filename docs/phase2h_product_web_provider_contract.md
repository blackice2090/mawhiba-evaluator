# Phase 2H -- Product Web Search and Safe Fetcher Contracts

## Brave Search API (web search)

**Status:** `IMPLEMENTED_DOCUMENTED_ONLY`. Verified on 2026-10-01 against
https://api-dashboard.search.brave.com/app/documentation/web-search/get-started.
No live request has been observed; the live test is gated behind
`RUN_BRAVE_SEARCH_TESTS=1` with `BRAVE_SEARCH_API_KEY`.

Connector: `src/research/product/brave.py` (`BraveWebSearchProvider`). It sits
behind the replaceable `WebSearchProvider` protocol.

| item | contract |
|---|---|
| endpoint | `GET https://api.search.brave.com/res/v1/web/search` |
| auth | `X-Subscription-Token: <key>` (required; never a bearer header, never in the URL) |
| query params | `q`; `count` (max 20); `offset` (zero-based page index, max 9); `search_lang` (`en`/`ar` when the query language is unambiguous; omitted for mixed); `country` not sent |
| response | `web.results[]`: `title`, `url`, `description`, optional `age` / `page_age`; `query.more_results_available` |
| errors | 429 is `RATE_LIMITED`. If a comma-separated `X-RateLimit-Remaining` ends in `0`, it is `QUOTA_LIMITED` (not retried). 401/403 is `AUTHENTICATION_ERROR`, 5xx is `PROVIDER_ERROR`, and malformed JSON is `PARSE_ERROR` |

The verified page did not state the rate-limit header formats, so they are read
defensively and the connector relies on the status code.

A Brave result is a **discovery observation**. The snippet is the provider's
excerpt, not product truth. `age`/`page_age` is kept verbatim as
`search_provider_date` and is never used for chronology.

## Safe web fetcher

**Status:** `IMPLEMENTED_DOCUMENTED_ONLY` (project-owned; HTTP semantics per RFC 9110).

Connector: `src/research/discovery/safe_fetch.py` (`SafeWebFetcher`).

| rule | behaviour |
|---|---|
| schemes | `http`, `https` only |
| ports | 80, 443 only |
| credentials | URLs with `user:pass@` refused |
| hostnames | `localhost`, `*.localhost`, `*.local`, `*.internal`, `*.home.arpa`, `*.lan`, `*.intranet`, single-label names, metadata hostnames refused |
| addresses | literal or resolved: every address must be globally routable; loopback, private, link-local (incl. `169.254.169.254`), CGNAT `100.64/10`, multicast, reserved, unspecified and IPv4-mapped IPv6 refused |
| redirects | manual; each hop rechecked before it is sent; chain bounded (`max_redirects`); recorded |
| size | streamed under `max_artifact_bytes`; above it the result is `CONTENT_TOO_LARGE`, never truncated and accepted |
| content | `text/html`, `application/xhtml+xml`, `text/plain` only; anything else is `UNSUPPORTED_CONTENT` |
| state | fresh client per fetch (no cookie persistence), `trust_env=False` (no environment proxies), no credentials, no JavaScript |
| record | original URL, final URL, redirect chain, content type, retrieval time, SHA-256 of the body, bounded text |

Known limitation: names are resolved before connecting, so DNS rebinding
between check and connect is not fully closed by this layer alone.
