"""Phase 2H provider-contract tests: exact outgoing requests, no network.

Pins what the GitHub and Brave connectors send, with negative assertions on
values that must never appear (a credential in a URL, a bearer header on
Brave, a missing API-version header on GitHub).
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import httpx
import pytest

from src.research.discovery.capabilities import (
    BRAVE_CAPABILITY,
    GITHUB_API_VERSION,
    GITHUB_CAPABILITY,
    SAFE_FETCHER_CAPABILITY,
)
from src.research.discovery.transport import DiscoveryTransportError, classify_status
from src.research.open_source.github import GitHubRestProvider
from src.research.product.brave import BraveWebSearchProvider
from src.schemas.discovery import (
    DiscoveryErrorKind,
    DiscoveryOperation,
    DiscoveryProvider,
    DiscoveryProviderAccessStatus,
    DiscoveryProviderCapability,
    DiscoveryQuery,
    DiscoveryQueryPurpose,
    DiscoveryQueryTerm,
    DiscoveryTermDerivation,
    DiscoveryTrack,
    QueryLanguage,
    stable_id,
)

TOKEN = "ghp_SECRETSECRETSECRET"
BRAVE_KEY = "BSA-secret-key-123"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _query(text="soil moisture", language=QueryLanguage.EN, track=DiscoveryTrack.PRODUCT):
    run = uuid4()
    provider = DiscoveryProvider.BRAVE_WEB_SEARCH if track is DiscoveryTrack.PRODUCT else DiscoveryProvider.GITHUB_REST
    op = DiscoveryOperation.WEB_SEARCH if track is DiscoveryTrack.PRODUCT else DiscoveryOperation.REPOSITORY_SEARCH
    key = f"{track}|{text}"
    return DiscoveryQuery(
        query_id=stable_id(run, key), research_run_id=run, track=track, provider=provider, operation=op,
        purpose=DiscoveryQueryPurpose.CORE_CONCEPT, query_text=text, language=language,
        terms=[DiscoveryQueryTerm(term=text, derivation=DiscoveryTermDerivation.CANONICAL_CLAIM_TEXT, original_text=text, claim_id="C-001")],
        claim_ids=["C-001"], requested_count=10, stable_key=key,
    )


# -- capabilities -------------------------------------------------------------


def test_every_provider_is_documented_only_until_live_verified():
    for capability in (GITHUB_CAPABILITY, BRAVE_CAPABILITY, SAFE_FETCHER_CAPABILITY):
        assert capability.access_status is DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY
        assert capability.live_request_observed is False
        assert capability.contract_verified_on == "2026-10-01"
        assert all(url.startswith("https://") for url in capability.documentation_urls)


def test_live_verified_status_requires_an_observed_request():
    with pytest.raises(ValueError, match="live request"):
        DiscoveryProviderCapability(
            provider=DiscoveryProvider.GITHUB_REST,
            access_status=DiscoveryProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED,
            documentation_urls=["https://docs.github.com"], contract_verified_on="2026-10-01",
            authentication="x", operations=[DiscoveryOperation.REPOSITORY_SEARCH],
        )


def test_code_search_is_declared_authenticated_only():
    assert GITHUB_CAPABILITY.authenticated_operations == [DiscoveryOperation.CODE_SEARCH]


# -- GitHub -------------------------------------------------------------------


def test_github_repository_search_request_contract():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"total_count": 1, "incomplete_results": False,
                                         "items": [{"id": 7, "node_id": "R_7", "full_name": "o/r", "html_url": "https://github.com/o/r"}]})

    page = GitHubRestProvider(client=_client(handler)).search_repositories("soil moisture", page=2, count=150)
    request = seen[0]
    assert request.url.host == "api.github.com" and request.url.path == "/search/repositories"
    assert dict(request.url.params) == {"q": "soil moisture", "per_page": "100", "page": "2"}
    assert request.headers["X-GitHub-Api-Version"] == GITHUB_API_VERSION == "2026-03-10"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert "authorization" not in request.headers
    assert page.items[0].repository_id == 7 and page.provider_total == 1


def test_github_token_only_in_authorization_header():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"total_count": 0, "incomplete_results": False, "items": []})

    provider = GitHubRestProvider(TOKEN, client=_client(handler))
    provider.search_repositories("x", page=1, count=5)
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(seen[0].url)
    assert TOKEN not in repr(provider)


def test_github_code_search_refused_without_token_and_sent_with_text_match_accept():
    with pytest.raises(DiscoveryTransportError) as raised:
        GitHubRestProvider(client=_client(lambda r: httpx.Response(500))).search_code("x", page=1, count=5)
    assert raised.value.kind is DiscoveryErrorKind.AUTHENTICATION_ERROR
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"total_count": 1, "incomplete_results": True, "items": [
            {"name": "a.py", "path": "src/a.py", "sha": "abc", "repository": {"id": 9, "node_id": "R_9", "full_name": "o/r"},
             "text_matches": [{"fragment": "def moisture():"}]}]})

    page = GitHubRestProvider(TOKEN, client=_client(handler)).search_code("moisture", page=1, count=5)
    assert seen[0].url.path == "/search/code"
    assert seen[0].headers["Accept"] == "application/vnd.github.text-match+json"
    assert page.items[0].code_path == "src/a.py" and page.items[0].fragment == "def moisture():"
    assert page.incomplete_results is True


def test_github_rename_redirect_followed_only_within_api_host():
    def handler(request):
        if request.url.path == "/repos/old/name":
            return httpx.Response(301, headers={"location": "https://api.github.com/repositories/42"})
        return httpx.Response(200, json={"id": 42, "full_name": "new/name"})

    assert GitHubRestProvider(client=_client(handler)).get_repository("old/name")["id"] == 42

    def evil(request):
        return httpx.Response(301, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(DiscoveryTransportError) as raised:
        GitHubRestProvider(client=_client(evil)).get_repository("old/name")
    assert raised.value.kind is DiscoveryErrorKind.FETCH_UNSAFE


def test_github_readme_is_base64_decoded_and_bounded():
    text = "# Title\n" + "x" * 50

    def handler(request):
        assert request.url.path == "/repos/o/r/readme" and dict(request.url.params) == {"ref": "main"}
        return httpx.Response(200, json={"path": "README.md", "sha": "s", "size": len(text), "encoding": "base64",
                                         "content": base64.b64encode(text.encode()).decode()})

    content = GitHubRestProvider(client=_client(handler), max_content_bytes=10).get_readme("o/r", "main")
    assert content.text == text[:10] and content.size == len(text)


@pytest.mark.parametrize(
    ("status", "headers", "kind"),
    [
        (401, {}, DiscoveryErrorKind.AUTHENTICATION_ERROR),
        (403, {}, DiscoveryErrorKind.AUTHENTICATION_ERROR),
        (403, {"x-ratelimit-remaining": "0"}, DiscoveryErrorKind.RATE_LIMITED),
        (403, {"retry-after": "30"}, DiscoveryErrorKind.RATE_LIMITED),
        (429, {}, DiscoveryErrorKind.RATE_LIMITED),
        (429, {"X-RateLimit-Remaining": "1, 0"}, DiscoveryErrorKind.QUOTA_LIMITED),
        (422, {}, DiscoveryErrorKind.INVALID_QUERY),
        (404, {}, DiscoveryErrorKind.UNSUPPORTED_OPERATION),
        (502, {}, DiscoveryErrorKind.PROVIDER_ERROR),
    ],
)
def test_status_classification(status, headers, kind):
    assert classify_status(status, headers) is kind


def test_github_error_never_echoes_body():
    def handler(request):
        return httpx.Response(401, text=f"bad credentials {TOKEN}")

    with pytest.raises(DiscoveryTransportError) as raised:
        GitHubRestProvider(TOKEN, client=_client(handler)).search_repositories("x", page=1, count=1)
    assert TOKEN not in str(raised.value)


# -- Brave --------------------------------------------------------------------


def test_brave_request_contract():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"query": {"more_results_available": True}, "web": {"results": [
            {"title": "T", "url": "https://a.example/p", "description": "snippet", "page_age": "2020-01-02T00:00:00"}]}})

    page = BraveWebSearchProvider(BRAVE_KEY, client=_client(handler)).search(_query(), page=3, count=50)
    request = seen[0]
    assert str(request.url).startswith("https://api.search.brave.com/res/v1/web/search?")
    assert dict(request.url.params) == {"q": "soil moisture", "count": "20", "offset": "2", "search_lang": "en"}
    assert request.headers["X-Subscription-Token"] == BRAVE_KEY
    assert "authorization" not in request.headers
    assert BRAVE_KEY not in str(request.url)
    assert page.items[0].provider_date == "2020-01-02T00:00:00" and page.more_available


def test_brave_arabic_and_mixed_language_params():
    assert BraveWebSearchProvider.build_params(_query(language=QueryLanguage.AR), page=1, count=5)["search_lang"] == "ar"
    assert "search_lang" not in BraveWebSearchProvider.build_params(_query(language=QueryLanguage.MIXED), page=1, count=5)


def test_brave_rate_limit_and_malformed_json():
    with pytest.raises(DiscoveryTransportError) as raised:
        BraveWebSearchProvider(BRAVE_KEY, client=_client(lambda r: httpx.Response(429, headers={"retry-after": "2"}))).search(_query(), page=1, count=5)
    assert raised.value.kind is DiscoveryErrorKind.RATE_LIMITED and raised.value.retry_after_seconds == 2.0
    with pytest.raises(DiscoveryTransportError) as raised:
        BraveWebSearchProvider(BRAVE_KEY, client=_client(lambda r: httpx.Response(200, text="{not json"))).search(_query(), page=1, count=5)
    assert raised.value.kind is DiscoveryErrorKind.PARSE_ERROR


def test_brave_requires_key_and_hides_it():
    with pytest.raises(ValueError):
        BraveWebSearchProvider("")
    assert BRAVE_KEY not in repr(BraveWebSearchProvider(BRAVE_KEY))


def test_brave_offset_beyond_documented_maximum_is_refused():
    with pytest.raises(DiscoveryTransportError) as raised:
        BraveWebSearchProvider(BRAVE_KEY, client=_client(lambda r: httpx.Response(200, json={}))).search(_query(), page=11, count=5)
    assert raised.value.kind is DiscoveryErrorKind.UNSUPPORTED_OPERATION


def test_contract_payloads_round_trip_json():
    assert json.loads(GITHUB_CAPABILITY.model_dump_json())["provider"] == "GITHUB_REST"
