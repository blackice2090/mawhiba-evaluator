"""Optional live official Mawhiba retrieval test.

Skipped unless RUN_OFFICIAL_WEB_TESTS=1 is set explicitly. Internet access alone is
deliberately not enough. Assertions are structural and never depend on the wording
of the live page, so CI can never depend on Mawhiba's current content.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.research.official.allowlist import DEFAULT_OFFICIAL_SEED_URL, check_official_url
from src.research.official.http_provider import HttpOfficialWebProvider
from src.research.official.sources import candidate_from_result, verify_official_candidates
from src.schemas.official import RetrievalStatus, SourceRejectionReason

RUN_LIVE = os.getenv("RUN_OFFICIAL_WEB_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE, reason="live official web test; set RUN_OFFICIAL_WEB_TESTS=1 to enable"
)


@pytest.fixture(scope="module")
def live_result():
    return HttpOfficialWebProvider().retrieve(DEFAULT_OFFICIAL_SEED_URL)


def test_live_retrieval_is_verified_or_explicitly_unavailable(live_result) -> None:
    decisions, snapshots, _ = verify_official_candidates([candidate_from_result(live_result, uuid4())])
    if live_result.status is RetrievalStatus.SUCCESS:
        assert snapshots, f"verification rejected live page: {decisions[0].rejection_reason}"
        assert len(snapshots[0].content_hash) == 64
        assert check_official_url(snapshots[0].url) is None
    else:
        assert snapshots == []
        assert decisions[0].rejection_reason is SourceRejectionReason.RETRIEVAL_FAILED


def test_live_retrieval_never_leaves_the_allowlist(live_result) -> None:
    if live_result.status is RetrievalStatus.SUCCESS:
        assert check_official_url(live_result.final_url) is None
