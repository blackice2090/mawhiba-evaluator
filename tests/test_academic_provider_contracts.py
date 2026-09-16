"""Phase 2B.1 — provider API contract regression tests.

These tests assert the **exact outgoing request** each live connector builds:
the URL, the query parameters and the authentication mechanism. They exist
because a stale endpoint or a stale parameter spelling is invisible in every
other test we have — the deterministic fakes replace the HTTP attempt, so an
offline suite can be perfectly green while the live connector calls a path that
no longer exists or sends a parameter the provider ignores.

Each provider therefore gets:

* a positive assertion on the exact path and parameter names;
* a negative assertion naming the specific stale value that must never return.

No network is touched: the recording client below stands in for ``httpx`` and
captures what the connector would have sent.

Contract sources, reviewed 2026-09-16 — see the contract table in
`docs/phase2b_academic_research_connectors.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.research.academic.capabilities import PROVIDER_CAPABILITIES, search_url
from src.research.academic.consensus import (
    CONSENSUS_API_KEY_HEADER,
    CONSENSUS_BASE_URL,
    CONSENSUS_MAX_PAGE_SIZE,
    CONSENSUS_PAGE_SIZE_PARAM,
    CONSENSUS_SEARCH_PATH,
    ConsensusProvider,
    ConsensusSearchResponse,
)
from src.research.academic.credentials import (
    CONSENSUS_API_KEY_ENV,
    OPENALEX_API_KEY_ENV,
    OPENALEX_CONTACT_EMAIL_ENV,
    SEMANTIC_SCHOLAR_API_KEY_ENV,
)
from src.research.academic.http import classify_http_status
from src.research.academic.openalex import (
    OPENALEX_API_KEY_PARAM,
    OPENALEX_MAILTO_PARAM,
    OPENALEX_MAX_PAGE_SIZE,
    OPENALEX_PAGE_SIZE_PARAM,
    OPENALEX_QUERY_PARAM,
    OpenAlexProvider,
    OpenAlexSearchResponse,
)
from src.research.academic.semantic_scholar import (
    SEMANTIC_SCHOLAR_API_KEY_HEADER,
    SEMANTIC_SCHOLAR_FIELD_NAMES,
    SEMANTIC_SCHOLAR_FIELDS,
    SEMANTIC_SCHOLAR_FIELDS_PARAM,
    SEMANTIC_SCHOLAR_LIMIT_PARAM,
    SEMANTIC_SCHOLAR_MAX_LIMIT,
    SEMANTIC_SCHOLAR_QUERY_PARAM,
    SemanticScholarPaper,
    SemanticScholarProvider,
    SemanticScholarSearchResponse,
)
from src.schemas.academic import (
    RETRYABLE_ERROR_KINDS,
    AcademicErrorKind,
    AcademicProvider,
    AcademicSearchQuery,
    AcademicSearchStatus,
)
from src.schemas.common import QueryPurpose

QUERY_TEXT = "YOLOv8 plant disease"
CONNECTOR_DIR = Path(__file__).resolve().parents[1] / "src" / "research" / "academic"


# ---------------------------------------------------------------------------
# A recording stand-in for httpx
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {"content-type": "application/json"}
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> dict:
        return self._payload


class RecordingClient:
    """Captures the exact request a connector builds. Never opens a socket."""

    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self.calls: list[dict] = []
        self._payload = payload if payload is not None else {}
        self._status_code = status_code

    def get(self, url, params=None, headers=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        return _Response(self._payload, self._status_code)

    @property
    def call(self) -> dict:
        assert len(self.calls) == 1, f"expected exactly one request, got {len(self.calls)}"
        return self.calls[0]


def _query(provider: AcademicProvider, limit: int = 7) -> AcademicSearchQuery:
    return AcademicSearchQuery(
        research_run_id=uuid4(),
        query_id=uuid4(),
        purpose=QueryPurpose.TECHNOLOGY,
        query=QUERY_TEXT,
        provider=provider,
        requested_limit=limit,
    )


def _no_credentials(monkeypatch) -> None:
    for name in (
        CONSENSUS_API_KEY_ENV,
        SEMANTIC_SCHOLAR_API_KEY_ENV,
        OPENALEX_API_KEY_ENV,
        OPENALEX_CONTACT_EMAIL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


# ===========================================================================
# Consensus
# ===========================================================================


def test_consensus_calls_the_current_search_endpoint(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    client = RecordingClient({"results": []})

    ConsensusProvider(client=client).search(_query(AcademicProvider.CONSENSUS), limit=7)

    call = client.call
    # The literal is asserted independently of the constants, so changing a
    # constant fails here rather than quietly redefining what "correct" means.
    assert call["url"] == "https://api.consensus.app/v1/search"
    assert CONSENSUS_BASE_URL == "https://api.consensus.app"
    assert CONSENSUS_SEARCH_PATH == "v1/search"
    assert call["params"] == {"query": QUERY_TEXT, "page_size": 7}
    assert call["headers"][CONSENSUS_API_KEY_HEADER] == "test-consensus-key"


def test_consensus_rest_authentication_is_the_x_api_key_header(monkeypatch) -> None:
    """The REST scheme, pinned. Verified 2026-09-16 from two provider sources.

    The published OpenAPI 3.1.0 definition declares exactly one security scheme
    -- ``XApiKeyHeader`` (apiKey, in header, name ``x-api-key``) -- and applies
    it to ``GET /v1/search``. The official Get Started page states the same and
    shows a matching curl example. Neither mentions ``Authorization`` or
    ``Bearer``; Consensus's MCP server is a separate surface and its
    authentication is never a source for the REST contract.

    This test fails if a bearer scheme is ever introduced here without that
    change being evidenced against the REST documentation.
    """
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    client = RecordingClient({"results": []})

    ConsensusProvider(client=client).search(_query(AcademicProvider.CONSENSUS), limit=7)

    headers = client.call["headers"]
    assert CONSENSUS_API_KEY_HEADER == "x-api-key"
    assert headers["x-api-key"] == "test-consensus-key"
    # No alternative or speculative scheme, and no sending of both.
    lowered = {name.lower() for name in headers}
    assert "authorization" not in lowered, "the REST API defines no bearer scheme"
    assert "x-api-key-header" not in lowered
    assert "api-key" not in lowered
    assert "apikey" not in lowered
    assert sum(1 for name in lowered if "api" in name and "key" in name) == 1


def test_a_consensus_key_never_leaves_the_authentication_header(monkeypatch) -> None:
    """The credential appears in exactly one place and nowhere else."""
    _no_credentials(monkeypatch)
    secret = "super-secret-consensus-value"
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, secret)
    client = RecordingClient(
        {
            "results": [
                {
                    "title": "A paper",
                    "doi": "10.1234/abcd",
                    "publish_year": 2021,
                    "journal_name": "Plant Science",
                    "url": "https://example.org/p",
                }
            ]
        }
    )

    result = ConsensusProvider(client=client).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )
    call = client.call

    assert call["headers"][CONSENSUS_API_KEY_HEADER] == secret
    assert secret not in call["url"], "never in the URL"
    assert secret not in json.dumps(call["params"]), "never in a query parameter"
    assert secret not in result.model_dump_json(), "never in AcademicSearchResult"
    candidate = result.candidates[0]
    assert secret not in candidate.model_dump_json(), "never in a source candidate"
    assert secret not in (candidate.raw_provider_metadata or ""), (
        "never in raw_provider_metadata"
    )

    failing = RecordingClient({}, status_code=500)
    errored = ConsensusProvider(client=failing).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )
    assert errored.errors, "the failure path is what is being checked"
    assert all(secret not in error.message for error in errored.errors)
    assert secret not in errored.model_dump_json(), "never in error serialization"


def test_consensus_reads_the_published_result_record_fields() -> None:
    """The DTO names match the published QueryResult schema, verified 2026-09-16."""
    from src.research.academic.consensus import ConsensusPaper

    published = {
        "abstract",
        "authors",
        "citation_count",
        "doi",
        "journal_name",
        "publish_date",
        "publish_year",
        "publisher_name",
        "semantic_score",
        "study_type",
        "takeaway",
        "title",
        "url",
    }
    assert published <= set(ConsensusPaper.model_fields), sorted(
        published - set(ConsensusPaper.model_fields)
    )


def test_consensus_does_not_use_the_stale_endpoint_or_parameter(monkeypatch) -> None:
    """The Phase 2B implementation sent `search/papers?...&size`. Neither may return."""
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    client = RecordingClient({"results": []})

    ConsensusProvider(client=client).search(_query(AcademicProvider.CONSENSUS), limit=7)

    call = client.call
    assert "search/papers" not in call["url"]
    assert "quick_search" not in call["url"], "the deprecated endpoint is never called"
    assert "size" not in call["params"], "the result-size parameter is page_size"
    assert "X-API-Key" not in call["headers"]


def test_consensus_never_sends_the_deprecated_quick_search_path() -> None:
    """A source-level guard, so the stale path cannot creep back in as a constant."""
    source = (CONNECTOR_DIR / "consensus.py").read_text(encoding="utf-8")
    assert 'CONSENSUS_SEARCH_PATH = "v1/search"' in source
    assert "search/papers" not in source.replace(
        "``v1/quick_search`` is deprecated", ""
    ).replace("quick_search", "")


def test_consensus_clamps_to_the_documented_page_size(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    client = RecordingClient({"results": []})
    provider = ConsensusProvider(client=client)
    query = _query(AcademicProvider.CONSENSUS, limit=200)

    provider.search(query, limit=200)

    assert client.call["params"][CONSENSUS_PAGE_SIZE_PARAM] <= CONSENSUS_MAX_PAGE_SIZE


def test_consensus_parses_the_documented_response_envelope() -> None:
    envelope = ConsensusSearchResponse.model_validate(
        {
            "results": [{"title": "A paper"}],
            "page": 0,
            "page_size": 20,
            "is_end": True,
            "next_page": None,
        }
    )
    assert len(envelope.results) == 1
    assert envelope.page_size == 20
    assert envelope.is_end is True


def test_consensus_reads_the_documented_paper_field_names() -> None:
    """publish_year, journal_name and takeaway are the documented spellings."""
    from datetime import datetime, timezone

    from src.research.academic.consensus import normalize_consensus_response

    candidate = normalize_consensus_response(
        _query(AcademicProvider.CONSENSUS),
        {
            "results": [
                {
                    "title": "A paper",
                    "doi": "10.1234/abcd",
                    "publish_year": 2021,
                    "journal_name": "Plant Science",
                    "citation_count": 4,
                    "abstract": "The paper's own abstract.",
                    "takeaway": "Consensus's own one-line synthesis.",
                    "url": "https://example.org/p",
                }
            ]
        },
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    ).candidates[0]

    assert candidate.publication_year == 2021
    assert candidate.venue == "Plant Science"
    assert candidate.citation_count == 4
    assert candidate.abstract == "The paper's own abstract."
    # The provider's synthesis is secondary metadata, never the abstract.
    assert "synthesis" not in (candidate.abstract or "")
    assert "synthesis" in (candidate.raw_provider_metadata or "")


def test_consensus_without_a_key_makes_no_request(monkeypatch) -> None:
    """A missing required key fails before the network, naming no secret."""
    _no_credentials(monkeypatch)
    client = RecordingClient({"results": []})

    result = ConsensusProvider(client=client).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )

    assert client.calls == []
    assert result.status is AcademicSearchStatus.AUTH_ERROR


# ===========================================================================
# OpenAlex
# ===========================================================================


def test_openalex_calls_works_with_the_documented_parameters(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    client = RecordingClient({"meta": {}, "results": []})

    OpenAlexProvider(client=client).search(_query(AcademicProvider.OPENALEX), limit=7)

    call = client.call
    assert call["url"] == "https://api.openalex.org/works"
    assert call["params"] == {OPENALEX_QUERY_PARAM: QUERY_TEXT, "per_page": 7}


def test_openalex_never_sends_the_hyphenated_page_size(monkeypatch) -> None:
    """`per-page` is an undocumented legacy alias. It must not be reintroduced."""
    _no_credentials(monkeypatch)
    client = RecordingClient({"meta": {}, "results": []})

    OpenAlexProvider(client=client).search(_query(AcademicProvider.OPENALEX), limit=7)

    assert "per-page" not in client.call["params"]
    assert OPENALEX_PAGE_SIZE_PARAM == "per_page"
    assert "per-page" not in (CONNECTOR_DIR / "openalex.py").read_text(
        encoding="utf-8"
    ).replace("``per-page`` is a legacy alias the API still accepts;", "")


def test_openalex_sends_the_key_and_contact_only_when_configured(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    bare = RecordingClient({"meta": {}, "results": []})
    OpenAlexProvider(client=bare).search(_query(AcademicProvider.OPENALEX), limit=7)
    assert OPENALEX_API_KEY_PARAM not in bare.call["params"]
    assert OPENALEX_MAILTO_PARAM not in bare.call["params"]

    monkeypatch.setenv(OPENALEX_API_KEY_ENV, "test-openalex-key")
    monkeypatch.setenv(OPENALEX_CONTACT_EMAIL_ENV, "research@example.org")
    configured = RecordingClient({"meta": {}, "results": []})
    provider = OpenAlexProvider(client=configured)
    result = provider.search(_query(AcademicProvider.OPENALEX), limit=7)

    assert configured.call["params"][OPENALEX_API_KEY_PARAM] == "test-openalex-key"
    assert configured.call["params"][OPENALEX_MAILTO_PARAM] == "research@example.org"
    assert provider.has_credentials is True
    # The key travels in the URL because that is the documented mechanism; it
    # must still never reach stored state.
    assert "test-openalex-key" not in result.model_dump_json()


def test_openalex_clamps_to_the_documented_page_size(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    client = RecordingClient({"meta": {}, "results": []})
    provider = OpenAlexProvider(client=client)

    provider.search(_query(AcademicProvider.OPENALEX, limit=200), limit=200)

    assert client.call["params"][OPENALEX_PAGE_SIZE_PARAM] == OPENALEX_MAX_PAGE_SIZE


def test_openalex_parses_the_documented_response_envelope() -> None:
    envelope = OpenAlexSearchResponse.model_validate(
        {"meta": {"count": 1, "page": 1, "per_page": 2}, "results": [{"id": "W1"}]}
    )
    assert len(envelope.results) == 1


# ===========================================================================
# Semantic Scholar
# ===========================================================================


def test_semantic_scholar_calls_the_graph_search_endpoint(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    monkeypatch.setenv(SEMANTIC_SCHOLAR_API_KEY_ENV, "test-s2-key")
    client = RecordingClient({"total": 0, "data": []})

    SemanticScholarProvider(client=client).search(
        _query(AcademicProvider.SEMANTIC_SCHOLAR), limit=7
    )

    call = client.call
    assert call["url"] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert call["params"] == {
        SEMANTIC_SCHOLAR_QUERY_PARAM: QUERY_TEXT,
        SEMANTIC_SCHOLAR_LIMIT_PARAM: 7,
        SEMANTIC_SCHOLAR_FIELDS_PARAM: SEMANTIC_SCHOLAR_FIELDS,
    }
    assert call["headers"][SEMANTIC_SCHOLAR_API_KEY_HEADER] == "test-s2-key"


def test_semantic_scholar_works_without_a_key(monkeypatch) -> None:
    """The public endpoint is keyless at a lower rate limit."""
    _no_credentials(monkeypatch)
    client = RecordingClient({"total": 0, "data": []})

    provider = SemanticScholarProvider(client=client)
    result = provider.search(_query(AcademicProvider.SEMANTIC_SCHOLAR), limit=7)

    assert provider.has_credentials is False
    assert SEMANTIC_SCHOLAR_API_KEY_HEADER not in client.call["headers"]
    assert result.status is AcademicSearchStatus.EMPTY


def test_semantic_scholar_requests_exactly_the_fields_its_parser_reads() -> None:
    """The request contract and the DTO cannot drift apart."""
    assert set(SEMANTIC_SCHOLAR_FIELD_NAMES) == set(SemanticScholarPaper.model_fields)
    assert SEMANTIC_SCHOLAR_FIELDS == ",".join(SEMANTIC_SCHOLAR_FIELD_NAMES)
    assert " " not in SEMANTIC_SCHOLAR_FIELDS, "a fields list takes no spaces"


def test_semantic_scholar_clamps_to_the_documented_limit(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    client = RecordingClient({"total": 0, "data": []})
    provider = SemanticScholarProvider(client=client)

    provider.search(_query(AcademicProvider.SEMANTIC_SCHOLAR, limit=200), limit=200)

    assert client.call["params"][SEMANTIC_SCHOLAR_LIMIT_PARAM] == SEMANTIC_SCHOLAR_MAX_LIMIT


def test_semantic_scholar_parses_the_documented_response_envelope() -> None:
    envelope = SemanticScholarSearchResponse.model_validate(
        {"total": 1, "offset": 0, "next": 1, "data": [{"paperId": "abc"}]}
    )
    assert len(envelope.data) == 1


# ===========================================================================
# Cross-provider
# ===========================================================================


@pytest.mark.parametrize(
    ("provider", "factory", "payload"),
    [
        (AcademicProvider.CONSENSUS, ConsensusProvider, {"results": []}),
        (AcademicProvider.OPENALEX, OpenAlexProvider, {"meta": {}, "results": []}),
        (
            AcademicProvider.SEMANTIC_SCHOLAR,
            SemanticScholarProvider,
            {"total": 0, "data": []},
        ),
    ],
    ids=lambda value: getattr(value, "value", None) or "",
)
def test_the_capability_matrix_matches_the_request_actually_sent(
    provider, factory, payload, monkeypatch
) -> None:
    """The documented contract table cannot drift from the real request."""
    _no_credentials(monkeypatch)
    capability = PROVIDER_CAPABILITIES[provider]
    if capability.api_key_env and capability.api_key_required:
        monkeypatch.setenv(capability.api_key_env, "test-key")
    client = RecordingClient(payload)

    factory(client=client).search(_query(provider), limit=7)

    call = client.call
    assert call["url"] == search_url(provider)
    assert capability.http_method == "GET"
    for name in capability.required_params:
        assert name in call["params"], f"{provider.value} must send {name}"
    assert capability.result_limit_param in call["params"]
    assert call["params"][capability.result_limit_param] == 7
    if capability.auth_header and capability.api_key_required:
        assert capability.auth_header in call["headers"]


@pytest.mark.parametrize(
    ("provider", "factory", "payload"),
    [
        (AcademicProvider.CONSENSUS, ConsensusProvider, {"results": []}),
        (AcademicProvider.OPENALEX, OpenAlexProvider, {"meta": {}, "results": []}),
        (
            AcademicProvider.SEMANTIC_SCHOLAR,
            SemanticScholarProvider,
            {"total": 0, "data": []},
        ),
    ],
    ids=lambda value: getattr(value, "value", None) or "",
)
def test_a_header_credential_never_appears_in_the_request_url(
    provider, factory, payload, monkeypatch
) -> None:
    _no_credentials(monkeypatch)
    capability = PROVIDER_CAPABILITIES[provider]
    if capability.api_key_env:
        monkeypatch.setenv(capability.api_key_env, "super-secret-value")
    client = RecordingClient(payload)

    result = factory(client=client).search(_query(provider), limit=7)

    assert "super-secret-value" not in client.call["url"]
    if capability.auth_header is not None:
        assert "super-secret-value" not in json.dumps(client.call["params"])
    assert "super-secret-value" not in result.model_dump_json()


def test_every_capability_records_when_its_contract_was_reviewed() -> None:
    for provider, capability in PROVIDER_CAPABILITIES.items():
        assert capability.contract_reviewed_on == "2026-09-16", provider.value
        assert capability.base_url.startswith("https://")
        assert not capability.search_path.startswith("/")
        assert capability.max_page_size >= 1


# ===========================================================================
# HTTP status semantics
# ===========================================================================


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (400, AcademicErrorKind.BAD_REQUEST, False),
        (401, AcademicErrorKind.AUTH_ERROR, False),
        (402, AcademicErrorKind.PAYMENT_REQUIRED, False),
        (403, AcademicErrorKind.FORBIDDEN, False),
        (404, AcademicErrorKind.NOT_FOUND, False),
        (422, AcademicErrorKind.UNPROCESSABLE_REQUEST, False),
        (429, AcademicErrorKind.RATE_LIMITED, True),
        (500, AcademicErrorKind.SERVER_ERROR, True),
        (502, AcademicErrorKind.SERVER_ERROR, True),
        (503, AcademicErrorKind.SERVER_ERROR, True),
        (504, AcademicErrorKind.SERVER_ERROR, True),
    ],
)
def test_documented_status_codes_map_to_named_kinds(status, kind, retryable) -> None:
    assert classify_http_status(status) is kind
    assert (kind in RETRYABLE_ERROR_KINDS) is retryable


def test_quota_exhaustion_is_reported_distinctly_from_a_rejected_key(
    monkeypatch,
) -> None:
    """402 and 401 are different facts, even though neither can be retried."""
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")

    quota = ConsensusProvider(client=RecordingClient({}, status_code=402)).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )
    rejected = ConsensusProvider(client=RecordingClient({}, status_code=401)).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )

    assert quota.errors[0].kind is AcademicErrorKind.PAYMENT_REQUIRED
    assert rejected.errors[0].kind is AcademicErrorKind.AUTH_ERROR
    # Same branch-level fact: this provider cannot be used right now.
    assert quota.status is rejected.status is AcademicSearchStatus.AUTH_ERROR
    assert quota.attempts == 1, "a payment problem is never retried"


def test_an_unprocessable_query_is_not_retried(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    client = RecordingClient({}, status_code=422)

    result = ConsensusProvider(client=client).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )

    assert result.errors[0].kind is AcademicErrorKind.UNPROCESSABLE_REQUEST
    assert result.status is AcademicSearchStatus.PROVIDER_ERROR
    assert len(client.calls) == 1


def test_a_rate_limit_is_retried_with_the_provider_retry_after(monkeypatch) -> None:
    _no_credentials(monkeypatch)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    from src.research.academic.http import NoSleep

    class _RetryAfterClient(RecordingClient):
        def get(self, url, params=None, headers=None):
            response = super().get(url, params=params, headers=headers)
            response.status_code = 429
            response.headers["retry-after"] = "3"
            return response

    sleeper = NoSleep()
    client = _RetryAfterClient({})
    result = ConsensusProvider(client=client, sleeper=sleeper).search(
        _query(AcademicProvider.CONSENSUS), limit=7
    )

    assert result.status is AcademicSearchStatus.RATE_LIMITED
    assert result.rate_limit.retry_after_seconds == 3.0
    assert result.attempts == 3
    assert sleeper.waits == [3.0, 3.0], "Retry-After is honoured, nothing really sleeps"


def test_the_contract_tests_open_no_socket(monkeypatch) -> None:
    """The guard on this file: every request above goes to a recording client."""
    import httpx

    _no_credentials(monkeypatch)

    def explode(*args, **kwargs):
        raise AssertionError("a contract test must never open a network connection")

    monkeypatch.setattr(httpx.Client, "send", explode)
    monkeypatch.setenv(CONSENSUS_API_KEY_ENV, "test-consensus-key")
    for factory, payload in (
        (ConsensusProvider, {"results": []}),
        (OpenAlexProvider, {"meta": {}, "results": []}),
        (SemanticScholarProvider, {"total": 0, "data": []}),
    ):
        provider = factory(client=RecordingClient(payload))
        provider.search(_query(provider.provider_name), limit=7)
