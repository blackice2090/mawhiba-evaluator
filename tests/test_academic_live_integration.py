"""Optional live academic connector smoke tests.

Each provider has its own opt-in flag and is skipped unless that flag is set to
``1``. Having credentials in the environment is deliberately not enough, and
internet access is deliberately not enough: a live test runs only when someone
asks for it by name.

    RUN_CONSENSUS_TESTS=1
    RUN_OPENALEX_TESTS=1
    RUN_SEMANTIC_SCHOLAR_TESTS=1

Assertions are structural only -- that the request is accepted, that the
response parses, and that whatever comes back obeys this project's contracts.
Nothing here depends on which papers a provider returns today, so these tests
are never a Gold baseline and CI never depends on a third-party service.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.research.academic.consensus import ConsensusProvider
from src.research.academic.credentials import (
    CONSENSUS_API_KEY_ENV,
    SEMANTIC_SCHOLAR_API_KEY_ENV,
)
from src.research.academic.openalex import OpenAlexProvider
from src.research.academic.semantic_scholar import SemanticScholarProvider
from src.schemas.academic import (
    AcademicProvider,
    AcademicSearchQuery,
    AcademicSearchResult,
    AcademicSearchStatus,
    AcademicSourceType,
)
from src.schemas.common import QueryPurpose

LIVE_QUERY = "convolutional neural network plant disease detection"

RUN_CONSENSUS = os.getenv("RUN_CONSENSUS_TESTS") == "1"
RUN_OPENALEX = os.getenv("RUN_OPENALEX_TESTS") == "1"
RUN_SEMANTIC_SCHOLAR = os.getenv("RUN_SEMANTIC_SCHOLAR_TESTS") == "1"


def _query(provider: AcademicProvider) -> AcademicSearchQuery:
    return AcademicSearchQuery(
        research_run_id=uuid4(),
        query_id=uuid4(),
        purpose=QueryPurpose.TECHNOLOGY,
        query=LIVE_QUERY,
        provider=provider,
        requested_limit=3,
    )


def _assert_contract_holds(result: AcademicSearchResult, provider: AcademicProvider) -> None:
    """Whatever the provider said, the envelope must obey the contract."""
    assert isinstance(result, AcademicSearchResult)
    assert result.provider is provider
    assert result.status in set(AcademicSearchStatus)
    assert result.attempts >= 1
    assert len(result.candidates) <= result.requested_limit

    for candidate in result.candidates:
        assert candidate.provider is provider
        assert candidate.title.strip()
        assert candidate.identity is not None, "a stored candidate is identifiable"
        assert candidate.source_type in set(AcademicSourceType)
        assert candidate.retrieved_at is not None
        if candidate.identifiers.doi:
            assert candidate.identifiers.doi.startswith("10.")
            assert candidate.identifiers.doi.islower()

    payload = result.model_dump_json()
    for name in (CONSENSUS_API_KEY_ENV, SEMANTIC_SCHOLAR_API_KEY_ENV):
        key = os.getenv(name)
        if key:
            assert key not in payload, "a credential must never reach stored state"


@pytest.mark.skipif(
    not RUN_CONSENSUS, reason="live Consensus test; set RUN_CONSENSUS_TESTS=1 to enable"
)
def test_live_consensus_search_parses() -> None:
    result = ConsensusProvider().search(_query(AcademicProvider.CONSENSUS), limit=3)
    _assert_contract_holds(result, AcademicProvider.CONSENSUS)


@pytest.mark.skipif(
    not RUN_OPENALEX, reason="live OpenAlex test; set RUN_OPENALEX_TESTS=1 to enable"
)
def test_live_openalex_search_parses() -> None:
    result = OpenAlexProvider().search(_query(AcademicProvider.OPENALEX), limit=3)
    _assert_contract_holds(result, AcademicProvider.OPENALEX)


@pytest.mark.skipif(
    not RUN_SEMANTIC_SCHOLAR,
    reason="live Semantic Scholar test; set RUN_SEMANTIC_SCHOLAR_TESTS=1 to enable",
)
def test_live_semantic_scholar_search_parses() -> None:
    result = SemanticScholarProvider().search(
        _query(AcademicProvider.SEMANTIC_SCHOLAR), limit=3
    )
    _assert_contract_holds(result, AcademicProvider.SEMANTIC_SCHOLAR)


def test_live_tests_are_opt_in_by_name_not_by_credentials() -> None:
    """This one always runs: it is the guard on the guards.

    A live test must never start because a key happens to be present in the
    environment, and never because CI has network access.
    """
    assert RUN_CONSENSUS == (os.getenv("RUN_CONSENSUS_TESTS") == "1")
    assert RUN_OPENALEX == (os.getenv("RUN_OPENALEX_TESTS") == "1")
    assert RUN_SEMANTIC_SCHOLAR == (os.getenv("RUN_SEMANTIC_SCHOLAR_TESTS") == "1")
    if os.getenv(CONSENSUS_API_KEY_ENV) and os.getenv("RUN_CONSENSUS_TESTS") != "1":
        assert RUN_CONSENSUS is False
