"""Phase 2G provider-contract tests -- the patent analogue of Phase 2B.1.

These pin the exact outgoing EPO OPS request contract, name every stale value
that must never come back, and prove the provider-honesty table cannot overstate
itself. No test here touches the network: the live client is exercised against
an in-memory transport that records what it was asked to send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from src.research.patent.capabilities import (
    EPO_OPS_CAPABILITY,
    PATENT_PROVIDER_CAPABILITIES,
    USPTO_ODP_CAPABILITY,
    WIPO_PATENTSCOPE_CAPABILITY,
    dispatchable_providers,
)
from src.research.patent.client import EpoOpsClient, EpoOpsCredentials
from src.research.patent.epo_ops import (
    EPO_OPS_AUTH_PATH,
    EPO_OPS_FAMILY_OPERATION,
    EPO_OPS_SEARCH_PATH,
    STALE_EPO_PATHS,
    build_content_request,
    build_family_request,
    build_search_request,
    build_token_request,
    range_header,
)
from src.research.patent.fakes import search_response_xml, FakePatentRecord
from src.research.patent.http import RetryPolicy
from src.schemas.patent import (
    PatentContentType,
    PatentErrorKind,
    PatentProvider,
    PatentProviderAccessStatus,
    PatentProviderCapability,
    PatentProviderOperation,
    PatentQueryTerm,
    PatentSearchQuery,
    PatentSearchStatus,
    PatentSearchStrategy,
    PublicationIdentity,
)
from src.schemas.common import QueryPurpose
from uuid import uuid4

IDENTITY = PublicationIdentity(authority="EP", number="1000000", kind_code="A1")


def _query(expression: str = 'ti = "solar tracker"', start: int = 1, limit: int = 10) -> PatentSearchQuery:
    return PatentSearchQuery(
        research_run_id=uuid4(),
        purpose=QueryPurpose.PRIOR_ART,
        strategy=PatentSearchStrategy.EXACT_TECHNICAL_PHRASE,
        provider=PatentProvider.EPO_OPS,
        query_expression=expression,
        normalized_expression=expression.casefold(),
        terms=[PatentQueryTerm(term="solar tracker", derivation="CANONICAL_PROJECT_TEXT")],
        requested_range_start=start,
        requested_limit=limit,
    )


# ---------------------------------------------------------------------------
# Exact request contract
# ---------------------------------------------------------------------------


def test_search_request_is_cql_over_published_data_with_a_range_header() -> None:
    request = build_search_request(_query(start=11, limit=10))
    assert request.method == "GET"
    assert request.url == "https://ops.epo.org/3.2/rest-services/published-data/search"
    assert request.url == EPO_OPS_SEARCH_PATH
    assert request.params == {"q": 'ti = "solar tracker"'}
    assert request.headers == {"Accept": "application/xml", "Range": "items=11-20"}
    assert "Authorization" not in request.headers


def test_family_request_is_the_inpadoc_family_service_without_equivalents() -> None:
    """The INPADOC family service is ``/family/publication/docdb/{ref}``.

    ``equivalents`` is a ``published-data`` constituent (the simple family),
    not a family-service constituent; the recovered connector briefly combined
    the two, which is the regression this test pins.
    """
    request = build_family_request(IDENTITY)
    assert request.url == (
        "https://ops.epo.org/3.2/rest-services/family/publication/docdb/EP.1000000.A1"
    )
    assert request.documented_operation == "GET /family/publication/docdb/{ref}"
    assert EPO_OPS_FAMILY_OPERATION == request.documented_operation
    assert "equivalents" not in request.url


@pytest.mark.parametrize(
    ("content_type", "constituent", "operation"),
    [
        (PatentContentType.TITLE, "biblio", PatentProviderOperation.FETCH_BIBLIOGRAPHIC),
        (PatentContentType.ABSTRACT, "abstract", PatentProviderOperation.FETCH_ABSTRACT),
        (PatentContentType.CLAIMS, "claims", PatentProviderOperation.FETCH_CLAIMS),
        (PatentContentType.DESCRIPTION, "description", PatentProviderOperation.FETCH_DESCRIPTION),
    ],
)
def test_content_requests_use_one_constituent_each(
    content_type: PatentContentType, constituent: str, operation: PatentProviderOperation
) -> None:
    request = build_content_request(IDENTITY, content_type)
    assert request.url == (
        "https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/"
        f"EP.1000000.A1/{constituent}"
    )
    assert request.operation is operation
    assert request.documented_operation.startswith("GET /published-data/publication/")


def test_token_request_is_client_credentials_and_carries_no_secret() -> None:
    request = build_token_request()
    assert request.method == "POST"
    assert request.url == "https://ops.epo.org/3.2/auth/accesstoken" == EPO_OPS_AUTH_PATH
    assert request.params == {"grant_type": "client_credentials"}
    assert "Authorization" not in request.headers


def test_no_stale_value_appears_in_any_outgoing_request() -> None:
    requests = [
        build_search_request(_query()),
        build_family_request(IDENTITY),
        build_token_request(),
        *(build_content_request(IDENTITY, c) for c in PatentContentType),
    ]
    for request in requests:
        rendered = f"{request.method} {request.url} {request.params} {request.headers}"
        for stale in STALE_EPO_PATHS:
            assert stale not in rendered, (stale, rendered)


def test_range_header_is_bounded_and_one_based() -> None:
    assert range_header(1, 25) == "items=1-25"
    for start, limit in ((0, 10), (1, 0), (1, 101)):
        with pytest.raises(ValueError):
            range_header(start, limit)


def test_an_invalid_cql_expression_never_becomes_a_request() -> None:
    with pytest.raises(ValueError):
        build_search_request(_query("ti = solar; drop"))


# ---------------------------------------------------------------------------
# Provider honesty
# ---------------------------------------------------------------------------


def test_epo_ops_is_documented_only_until_a_live_request_succeeds() -> None:
    assert EPO_OPS_CAPABILITY.access_status is PatentProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY
    assert EPO_OPS_CAPABILITY.live_request_observed is False
    assert EPO_OPS_CAPABILITY.documentation_url.startswith("https://developers.epo.org")


def test_uspto_is_deferred_and_no_legacy_patentsview_contract_exists() -> None:
    assert USPTO_ODP_CAPABILITY.access_status is PatentProviderAccessStatus.DEFERRED
    assert USPTO_ODP_CAPABILITY.operations == []
    assert not USPTO_ODP_CAPABILITY.dispatchable
    import src.research.patent as package
    from pathlib import Path

    for source in Path(package.__file__).parent.glob("*.py"):
        text = source.read_text(encoding="utf-8").casefold()
        assert "search.patentsview.org/api" not in text
        assert "api.patentsview.org" not in text


def test_patentscope_is_unsupported_by_access_policy_and_exposes_nothing() -> None:
    assert (
        WIPO_PATENTSCOPE_CAPABILITY.access_status
        is PatentProviderAccessStatus.UNSUPPORTED_BY_ACCESS_POLICY
    )
    assert WIPO_PATENTSCOPE_CAPABILITY.operations == []
    with pytest.raises(ValidationError):
        PatentProviderCapability.model_validate(
            {
                **dict(WIPO_PATENTSCOPE_CAPABILITY),
                "operations": [PatentProviderOperation.SEARCH_PUBLICATIONS],
            }
        )


def test_only_epo_ops_is_dispatchable() -> None:
    assert dispatchable_providers() == [PatentProvider.EPO_OPS]
    assert set(PATENT_PROVIDER_CAPABILITIES) == set(PatentProvider)


def test_live_verified_requires_an_observed_request_and_vice_versa() -> None:
    with pytest.raises(ValidationError):
        PatentProviderCapability.model_validate(
            {
                **dict(EPO_OPS_CAPABILITY),
                "access_status": PatentProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED,
            }
        )
    with pytest.raises(ValidationError):
        PatentProviderCapability.model_validate(
            {**dict(EPO_OPS_CAPABILITY), "live_request_observed": True}
        )


# ---------------------------------------------------------------------------
# The live client against an in-memory transport (no network)
# ---------------------------------------------------------------------------

KEY = "consumer-key-sentinel-7Q2"
SECRET = "consumer-secret-sentinel-9Z4"
TOKEN = "access-token-sentinel-abcdefghijklmnop"


@dataclass
class _Response:
    status_code: int
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        if self.body is None:
            raise ValueError("not json")
        return self.body


@dataclass
class _Transport:
    search_responses: list[_Response]
    posts: list[dict[str, Any]] = field(default_factory=list)
    gets: list[dict[str, Any]] = field(default_factory=list)

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.posts.append({"url": url, **kwargs})
        return _Response(200, body={"access_token": TOKEN, "expires_in": "1199"})

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.gets.append({"url": url, **kwargs})
        return self.search_responses.pop(0)


def _client(responses: list[_Response]) -> tuple[EpoOpsClient, _Transport]:
    transport = _Transport(search_responses=responses)
    client = EpoOpsClient(
        EpoOpsCredentials(consumer_key=KEY, consumer_secret=SECRET),
        client=transport,
        retry_policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.0),
    )
    return client, transport


def _ok(records: int = 1) -> _Response:
    xml = search_response_xml(
        [FakePatentRecord(f"EP.{1000000 + i}.A1", title="Solar tracker") for i in range(records)]
    )
    return _Response(200, text=xml)


def test_basic_auth_only_on_the_token_endpoint_and_bearer_on_rest() -> None:
    client, transport = _client([_ok(), _ok()])
    client.search(_query(), limit=10)
    client.search(_query('ti = "light sensor"'), limit=10)
    assert len(transport.posts) == 1, "the bearer token must be reused, not re-fetched"
    post = transport.posts[0]
    assert post["url"] == EPO_OPS_AUTH_PATH
    assert post["auth"] == (KEY, SECRET)
    assert post["data"] == {"grant_type": "client_credentials"}
    for get in transport.gets:
        assert get["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert get["headers"]["Range"] == "items=1-10"
        assert "auth" not in get


def test_no_credential_or_token_reaches_the_result_state() -> None:
    client, _ = _client([_ok(2)])
    result = client.search(_query(), limit=10)
    dumped = result.model_dump_json()
    for secret in (KEY, SECRET, TOKEN, "Bearer", "Authorization"):
        assert secret not in dumped
    assert result.provider_endpoint == "GET /published-data/search"
    assert "sentinel" not in repr(EpoOpsCredentials(consumer_key=KEY, consumer_secret=SECRET))


def test_fair_use_rejection_is_not_retried_and_is_not_an_auth_failure() -> None:
    client, transport = _client(
        [_Response(403, headers={"X-Rejection-Reason": "IndividualQuotaPerHour"})]
    )
    result = client.search(_query(), limit=10)
    assert result.status is PatentSearchStatus.RATE_LIMITED
    assert result.attempts == 1
    assert result.errors[0].kind is PatentErrorKind.FAIR_USE_REJECTED
    assert result.rate_limit is not None
    assert result.rate_limit.rejection_reason == "IndividualQuotaPerHour"
    assert len(transport.gets) == 1


def test_a_server_error_is_retried_then_succeeds() -> None:
    client, transport = _client([_Response(503), _ok()])
    result = client.search(_query(), limit=10)
    assert result.status is PatentSearchStatus.SUCCESS
    assert result.attempts == 2
    assert len(transport.gets) == 2


def test_a_bad_request_is_an_invalid_query_and_never_retried() -> None:
    client, transport = _client([_Response(400)])
    result = client.search(_query(), limit=10)
    assert result.status is PatentSearchStatus.INVALID_QUERY
    assert result.attempts == 1
    assert len(transport.gets) == 1


def test_a_fault_envelope_in_a_200_body_is_a_failure_not_an_empty_search() -> None:
    fault = "<error><code>500</code><message>Internal error</message></error>"
    client, _ = _client([_Response(200, text=fault)] * 3)
    result = client.search(_query(), limit=10)
    assert result.status is not PatentSearchStatus.EMPTY
    assert result.failed


def test_credentials_come_from_the_environment_or_not_at_all(monkeypatch) -> None:
    monkeypatch.delenv("EPO_OPS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_CONSUMER_SECRET", raising=False)
    assert EpoOpsCredentials.from_environment() is None
    monkeypatch.setenv("EPO_OPS_CONSUMER_KEY", KEY)
    monkeypatch.setenv("EPO_OPS_CONSUMER_SECRET", SECRET)
    credentials = EpoOpsCredentials.from_environment()
    assert credentials is not None and credentials.consumer_key == KEY
