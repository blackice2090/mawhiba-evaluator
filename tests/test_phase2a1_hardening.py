"""Phase 2A.1 hardening: documented baseline discrepancy and the vocabulary policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.vocabulary import (
    ALL_CONFIRMATION_BIAS_MARKERS,
    ALL_INJECTION_MARKERS,
    ALL_QUERY_CONNECTOR_TOKENS,
    ARABIC_CONFIRMATION_BIAS_MARKERS,
    ARABIC_INJECTION_MARKERS,
    ARABIC_QUERY_CONNECTOR_TOKENS,
    ARABIC_VOCABULARY_PATH,
    ARABIC_VOCABULARY_VERSION,
    CONFIRMATION_BIAS_MARKERS,
    INJECTION_MARKERS,
    MAX_REVIEWED_CONNECTOR_TOKENS,
    QUERY_CONNECTOR_TOKENS,
)

ROOT = Path(__file__).resolve().parents[1]
HARDENING_DOC = ROOT / "docs" / "phase2a1_hardening.md"
EXECUTION_SPEC = ROOT / "docs" / "phase2a_execution_spec.md"


# --- the 630 vs 631 baseline discrepancy ------------------------------------------------


def test_the_baseline_test_count_discrepancy_is_documented() -> None:
    text = HARDENING_DOC.read_text(encoding="utf-8")
    assert "630 passed" in text and "631 passed" in text
    assert "test_developer_surfaces_contain_no_arabic[PHASE_2A_EXECUTION.md]" in text
    assert "rglob" in text


def test_the_language_guard_scans_the_filesystem_not_git() -> None:
    """The documented cause: one more Markdown file on disk is one more test case.

    An untracked file must still be scanned, or the language policy could be
    bypassed simply by not committing a file yet.
    """
    from tests.test_language_policy import _tracked_source_files

    probe = ROOT / "_phase2a1_probe.md"
    before = set(_tracked_source_files())
    assert probe not in before
    probe.write_text("# probe\n", encoding="utf-8")
    try:
        after = set(_tracked_source_files())
        assert after - before == {probe}
    finally:
        probe.unlink(missing_ok=True)
    assert probe not in set(_tracked_source_files())


def test_the_execution_spec_is_tracked_documentation_not_loose_in_the_root() -> None:
    assert EXECUTION_SPEC.exists()
    assert not (ROOT / "PHASE_2A_EXECUTION.md").exists()


# --- reviewed search vocabulary policy ---------------------------------------------------


def test_each_language_vocabulary_stays_small_enough_to_review() -> None:
    assert 0 < len(QUERY_CONNECTOR_TOKENS) <= MAX_REVIEWED_CONNECTOR_TOKENS
    assert 0 < len(ARABIC_QUERY_CONNECTOR_TOKENS) <= MAX_REVIEWED_CONNECTOR_TOKENS


def test_connector_tokens_are_single_words_without_digits() -> None:
    for token in ALL_QUERY_CONNECTOR_TOKENS:
        assert token == token.strip() and " " not in token, token
        assert not any(ch.isdigit() for ch in token), token
        assert token == token.casefold(), token


def test_the_arabic_vocabulary_is_versioned_reviewed_data() -> None:
    payload = json.loads(ARABIC_VOCABULARY_PATH.read_text(encoding="utf-8"))
    assert payload["language"] == "ar"
    assert payload["version"] == ARABIC_VOCABULARY_VERSION == "AR-SEARCH-VOCABULARY-V1"
    assert payload["note"].isascii()
    assert set(payload) == {"language", "version", "note", "connector_tokens",
                            "confirmation_bias_markers", "injection_markers"}


def test_the_vocabulary_module_itself_stays_english() -> None:
    """Arabic is data: it lives in the JSON file, never in developer prose."""
    source = (ROOT / "src" / "research" / "vocabulary.py").read_text(encoding="utf-8")
    assert source.isascii()


def test_both_languages_are_enforced_together() -> None:
    assert QUERY_CONNECTOR_TOKENS < ALL_QUERY_CONNECTOR_TOKENS
    assert ARABIC_QUERY_CONNECTOR_TOKENS < ALL_QUERY_CONNECTOR_TOKENS
    assert set(CONFIRMATION_BIAS_MARKERS) | set(ARABIC_CONFIRMATION_BIAS_MARKERS) == set(
        ALL_CONFIRMATION_BIAS_MARKERS
    )
    assert set(INJECTION_MARKERS) | set(ARABIC_INJECTION_MARKERS) == set(ALL_INJECTION_MARKERS)
    assert ARABIC_CONFIRMATION_BIAS_MARKERS and ARABIC_INJECTION_MARKERS


@pytest.mark.parametrize("markers", [ALL_CONFIRMATION_BIAS_MARKERS, ALL_INJECTION_MARKERS])
def test_markers_are_lowercase_and_stripped_of_padding(markers) -> None:
    for marker in markers:
        assert marker == marker.casefold()
        assert not marker.startswith(" ")
