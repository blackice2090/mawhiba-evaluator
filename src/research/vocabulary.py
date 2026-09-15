"""Closed vocabularies used by deterministic query verification.

Kept dependency-free so both the prompts and the verifier import one source.
Changing a list is a reviewable policy change, like a trust threshold.
"""

from __future__ import annotations

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
"""Words a query may contain without a source-term or expansion-term origin.

Every other token in an accepted query must come from a declared source term
(traced to ProjectState) or a declared expansion term (explicitly not a fact).
"""

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
"""Advocacy phrasing. The research system tests the project; it does not defend it."""

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
"""Instruction-like text. Treated as content, and never allowed through as a query
or as an official requirement."""
