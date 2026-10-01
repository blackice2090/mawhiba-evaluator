"""Provider honesty table for Phase 2H -- sections 3, 4, 5, 6.

Every value here was checked against the provider's own current documentation
on ``contract_verified_on``. None was verified by a live request in this phase,
so every implemented provider is ``IMPLEMENTED_DOCUMENTED_ONLY``; the live
integration tests (``RUN_GITHUB_PRIOR_ART_TESTS``, ``RUN_BRAVE_SEARCH_TESTS``)
exist to change that, and a skipped live test is NOT RUN, never PASS.
"""

from __future__ import annotations

from src.schemas.discovery import (
    DiscoveryOperation,
    DiscoveryProvider,
    DiscoveryProviderAccessStatus,
    DiscoveryProviderCapability,
)

CONTRACT_VERIFIED_ON = "2026-10-01"

GITHUB_API_VERSION = "2026-03-10"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_ACCEPT = "application/vnd.github+json"
GITHUB_TEXT_MATCH_ACCEPT = "application/vnd.github.text-match+json"
GITHUB_SEARCH_RESULT_CAP = 1000
"""GitHub returns at most 1,000 results per search, whatever total_count says."""
GITHUB_MAX_PER_PAGE = 100

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_AUTH_HEADER = "X-Subscription-Token"
BRAVE_MAX_COUNT = 20
BRAVE_MAX_OFFSET = 9
"""Brave's ``offset`` is a zero-based page index, at most 9."""

GITHUB_CAPABILITY = DiscoveryProviderCapability(
    provider=DiscoveryProvider.GITHUB_REST,
    access_status=DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    documentation_urls=[
        "https://docs.github.com/en/rest/search/search",
        "https://docs.github.com/en/rest/repos/repos#get-a-repository",
        "https://docs.github.com/en/rest/repos/contents#get-a-repository-readme",
        "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
    ],
    contract_verified_on=CONTRACT_VERIFIED_ON,
    authentication=(
        "Optional bearer token for repository search and metadata (60 requests/hour "
        "unauthenticated, 5,000 authenticated); REQUIRED for code search. Header "
        f"X-GitHub-Api-Version: {GITHUB_API_VERSION}."
    ),
    operations=[
        DiscoveryOperation.REPOSITORY_SEARCH,
        DiscoveryOperation.CODE_SEARCH,
        DiscoveryOperation.REPOSITORY_METADATA,
        DiscoveryOperation.REPOSITORY_README,
        DiscoveryOperation.REPOSITORY_CONTENT,
        DiscoveryOperation.REPOSITORY_RELEASES,
        DiscoveryOperation.REPOSITORY_COMMITS,
    ],
    authenticated_operations=[DiscoveryOperation.CODE_SEARCH],
    notes=(
        "Search: 30 req/min authenticated, 10 req/min unauthenticated; code search "
        "10 req/min, default branch only, files under 384 KB; at most 1,000 results "
        "per search; per_page max 100. Primary and secondary limits return 403 or "
        "429; honour retry-after, otherwise x-ratelimit-reset."
    ),
)

BRAVE_CAPABILITY = DiscoveryProviderCapability(
    provider=DiscoveryProvider.BRAVE_WEB_SEARCH,
    access_status=DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    documentation_urls=[
        "https://api-dashboard.search.brave.com/app/documentation/web-search/get-started",
    ],
    contract_verified_on=CONTRACT_VERIFIED_ON,
    authentication=f"API key in the {BRAVE_AUTH_HEADER} header; required.",
    operations=[DiscoveryOperation.WEB_SEARCH],
    authenticated_operations=[DiscoveryOperation.WEB_SEARCH],
    notes=(
        "GET /res/v1/web/search with q, country, search_lang, ui_lang, count "
        "(max 20), offset (page index, max 9). Results under web.results with "
        "title, url, description, optional age/page_age; query.more_results_available. "
        "429 on rate or quota limits. Rate-limit header formats were not stated on "
        "the verified page and are read defensively."
    ),
)

SAFE_FETCHER_CAPABILITY = DiscoveryProviderCapability(
    provider=DiscoveryProvider.SAFE_WEB_FETCHER,
    access_status=DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    documentation_urls=["https://www.rfc-editor.org/rfc/rfc9110"],
    contract_verified_on=CONTRACT_VERIFIED_ON,
    authentication="None. Never sends cookies or credentials.",
    operations=[DiscoveryOperation.FETCH_PAGE],
    notes=(
        "Project-owned HTTP(S) fetcher: manual redirects revalidated per hop, "
        "private/loopback/link-local/metadata targets refused, size and time bounded, "
        "no JavaScript, no cookie persistence."
    ),
)

PRODUCT_CAPABILITIES: tuple[DiscoveryProviderCapability, ...] = (
    BRAVE_CAPABILITY,
    SAFE_FETCHER_CAPABILITY,
)
OPEN_SOURCE_CAPABILITIES: tuple[DiscoveryProviderCapability, ...] = (GITHUB_CAPABILITY,)

__all__ = [
    "BRAVE_AUTH_HEADER",
    "BRAVE_CAPABILITY",
    "BRAVE_MAX_COUNT",
    "BRAVE_MAX_OFFSET",
    "BRAVE_WEB_SEARCH_URL",
    "CONTRACT_VERIFIED_ON",
    "GITHUB_ACCEPT",
    "GITHUB_API_BASE",
    "GITHUB_API_VERSION",
    "GITHUB_CAPABILITY",
    "GITHUB_MAX_PER_PAGE",
    "GITHUB_SEARCH_RESULT_CAP",
    "GITHUB_TEXT_MATCH_ACCEPT",
    "OPEN_SOURCE_CAPABILITIES",
    "PRODUCT_CAPABILITIES",
    "SAFE_FETCHER_CAPABILITY",
]
