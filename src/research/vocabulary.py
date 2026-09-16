"""Closed vocabularies used by deterministic query verification.

Two reviewed, language-specific lists: English below, Arabic in
``data/search_vocabulary_ar.json``. Arabic lives in a data file because the
developer layer is English-only (language policy); the file is small, reviewed and
diffable, which is the point -- an uncontrolled stopword list would let arbitrary
words into queries without provenance.

Changing a list is a reviewable policy change, like a trust threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

QUERY_CONNECTOR_TOKENS: frozenset[str] = frozenset(
    {
        # grammatical connectors
        "a", "an", "the", "of", "for", "in", "on", "with", "without", "and", "or",
        "to", "by", "from", "under", "vs", "versus", "using", "based", "via",
        # search-intent words tied to query purposes
        "problem", "problems", "challenge", "challenges", "existing", "solution",
        "solutions", "system", "systems", "technology", "technologies", "recent",
        "advances", "work", "state", "art", "limitation", "limitations",
        "drawback", "drawbacks", "benchmark", "benchmarks", "comparison",
        "compared", "evaluation", "review", "reviews", "survey", "systematic",
        "alternative", "alternatives", "failure", "failures", "mode", "modes",
        "case", "cases", "competing", "method", "methods", "approach",
        "approaches", "prior", "patent", "patents", "function", "mechanism",
        "product", "products", "commercial", "open", "source", "implementation",
        "implementations", "repository", "repositories", "standard", "standards",
        "specification", "specifications",
    }
)
"""English words a query may contain without a source-term or expansion-term origin."""

CONFIRMATION_BIAS_MARKERS: tuple[str, ...] = (
    "advantages of",
    "benefits of",
    "why ",
    "proves",
    "proof that",
    "best ",
    "superior",
    "better than",
    "success of",
)
"""English advocacy phrasing. The research system tests the project; it does not defend it."""

INJECTION_MARKERS: tuple[str, ...] = (
    "ignore your",
    "ignore all",
    "ignore previous",
    "ignore the above",
    "disregard",
    "system prompt",
    "system instructions",
    "you are now",
    "set novelty",
    "novelty level",
    "give a score",
    "score of 100",
)
"""English instruction-like text. Treated as content, never allowed through as a
query or as an official requirement."""

ARABIC_VOCABULARY_PATH = Path(__file__).resolve().parent / "data" / "search_vocabulary_ar.json"

_ARABIC = json.loads(ARABIC_VOCABULARY_PATH.read_text(encoding="utf-8"))

ARABIC_VOCABULARY_VERSION: str = _ARABIC["version"]
ARABIC_QUERY_CONNECTOR_TOKENS: frozenset[str] = frozenset(_ARABIC["connector_tokens"])
ARABIC_CONFIRMATION_BIAS_MARKERS: tuple[str, ...] = tuple(_ARABIC["confirmation_bias_markers"])
ARABIC_INJECTION_MARKERS: tuple[str, ...] = tuple(_ARABIC["injection_markers"])

ALL_QUERY_CONNECTOR_TOKENS: frozenset[str] = QUERY_CONNECTOR_TOKENS | ARABIC_QUERY_CONNECTOR_TOKENS
ALL_CONFIRMATION_BIAS_MARKERS: tuple[str, ...] = (
    *CONFIRMATION_BIAS_MARKERS,
    *ARABIC_CONFIRMATION_BIAS_MARKERS,
)
ALL_INJECTION_MARKERS: tuple[str, ...] = (*INJECTION_MARKERS, *ARABIC_INJECTION_MARKERS)

MAX_REVIEWED_CONNECTOR_TOKENS = 80
"""Per language. A vocabulary that grows past a reviewable size stops being a
reviewed list and becomes an unbounded allowance."""
