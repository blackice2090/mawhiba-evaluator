"""Live Phase 2H provider tests -- NEVER run without being asked.

    RUN_GITHUB_PRIOR_ART_TESTS=1 [GITHUB_TOKEN=...]  pytest tests/test_product_oss_live_integration.py
    RUN_BRAVE_SEARCH_TESTS=1 BRAVE_SEARCH_API_KEY=... pytest tests/test_product_oss_live_integration.py

Harmless public queries only. A skipped test here is NOT RUN, never PASS, and
no provider may be reported IMPLEMENTED_AND_LIVE_VERIFIED on a skip.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.research.open_source.github import GitHubRestProvider
from src.research.product.brave import BraveWebSearchProvider
from src.schemas.discovery import (
    DiscoveryOperation,
    DiscoveryProvider,
    DiscoveryQuery,
    DiscoveryQueryPurpose,
    DiscoveryQueryTerm,
    DiscoveryTermDerivation,
    DiscoveryTrack,
    QueryLanguage,
    stable_id,
)

github_live = pytest.mark.skipif(
    os.environ.get("RUN_GITHUB_PRIOR_ART_TESTS") != "1", reason="live GitHub tests not enabled"
)
brave_live = pytest.mark.skipif(
    os.environ.get("RUN_BRAVE_SEARCH_TESTS") != "1" or not os.environ.get("BRAVE_SEARCH_API_KEY"),
    reason="live Brave tests not enabled or no key",
)


@github_live
def test_live_github_repository_search_and_metadata():
    provider = GitHubRestProvider(os.environ.get("GITHUB_TOKEN") or None)
    page = provider.search_repositories("soil moisture sensor arduino", page=1, count=3)
    assert page.items and page.provider_total is not None
    repo = provider.get_repository(page.items[0].full_name)
    assert repo["id"] == page.items[0].repository_id


@brave_live
def test_live_brave_web_search():
    run = uuid4()
    text = "soil moisture sensor irrigation controller"
    query = DiscoveryQuery(
        query_id=stable_id(run, "live"), research_run_id=run, track=DiscoveryTrack.PRODUCT,
        provider=DiscoveryProvider.BRAVE_WEB_SEARCH, operation=DiscoveryOperation.WEB_SEARCH,
        purpose=DiscoveryQueryPurpose.CORE_CONCEPT, query_text=text, language=QueryLanguage.EN,
        terms=[DiscoveryQueryTerm(term=text, derivation=DiscoveryTermDerivation.CANONICAL_CLAIM_TEXT, original_text=text, claim_id="C-001")],
        claim_ids=["C-001"], requested_count=5, stable_key="live",
    )
    page = BraveWebSearchProvider(os.environ["BRAVE_SEARCH_API_KEY"]).search(query, page=1, count=5)
    assert page.items
