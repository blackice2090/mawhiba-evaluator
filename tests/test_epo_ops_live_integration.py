"""Optional live EPO OPS smoke test -- Phase 2G section 34.

Runs only when explicitly requested **and** credentials are present:

    RUN_EPO_OPS_TESTS=1
    EPO_OPS_CONSUMER_KEY=...
    EPO_OPS_CONSUMER_SECRET=...

The flag alone is not enough: without credentials the connector would report
``BLOCKED_AUTH``, which obeys every contract here, and letting that pass would
report EPO OPS as live-verified when it was never contacted. So a missing
credential **skips**.

Assertions are structural only -- the authenticated request is accepted, the
XML parses, and what comes back obeys this project's contracts. Nothing depends
on which documents the office returns today, so this is never a Gold baseline.

A pass here is the evidence required before ``EPO_OPS_CAPABILITY`` may be moved
to ``IMPLEMENTED_AND_LIVE_VERIFIED``. That move is a reviewed change, never an
automatic one.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.research.patent.client import EpoOpsClient, EpoOpsCredentials
from src.research.patent.planner import PlannableClaim, plan_patent_queries
from src.schemas.patent import (
    EXECUTED_PATENT_STATUSES,
    PatentContentType,
    PublicationIdentity,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EPO_OPS_TESTS") != "1",
    reason="live EPO OPS test; set RUN_EPO_OPS_TESTS=1 and credentials to run",
)


@pytest.fixture(scope="module")
def client() -> EpoOpsClient:
    credentials = EpoOpsCredentials.from_environment()
    if credentials is None:
        pytest.skip("RUN_EPO_OPS_TESTS=1 but EPO_OPS_CONSUMER_KEY/SECRET are not set")
    return EpoOpsClient(credentials)


def test_live_bibliographic_search_parses_under_the_contract(client: EpoOpsClient) -> None:
    plan = plan_patent_queries(
        [PlannableClaim(claim_id="C-001", text="A solar tracker rotates photovoltaic panels.")],
        research_run_id=uuid4(),
        max_queries_per_claim=1,
        results_per_query=5,
    )
    result = client.search(plan.queries[0], limit=5)
    assert result.status in EXECUTED_PATENT_STATUSES, result.errors
    assert result.provider_endpoint == "GET /published-data/search"
    for observation in result.observations:
        assert observation.identity.canonical_key
        assert observation.provider_rank is not None
    dumped = result.model_dump_json()
    assert "Bearer" not in dumped and "Authorization" not in dumped


def test_live_family_of_a_known_publication(client: EpoOpsClient) -> None:
    payload = client.fetch_family(
        PublicationIdentity(authority="EP", number="1000000", kind_code="A1")
    )
    assert not payload.failed, payload.error
    assert payload.endpoint == "GET /family/publication/docdb/{ref}"


def test_live_abstract_of_a_known_publication(client: EpoOpsClient) -> None:
    payload = client.fetch_text(
        PublicationIdentity(authority="EP", number="1000000", kind_code="A1"),
        PatentContentType.ABSTRACT,
    )
    assert payload.error is None
