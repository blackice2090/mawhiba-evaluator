"""Deterministic verification of a model-generated query plan.

A candidate plan is untrusted. A query is accepted only when code can show that
every project-specific word traces to trusted canonical ``ProjectState`` or is an
explicitly declared expansion term, that no personal data is present, and that
the budget and duplicate rules hold. Nothing here writes to ``ProjectState``.
"""

from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

from src.graph.state import ProjectState
from src.intake.anchors import collapse_whitespace, normalize_unicode, value_supported_by_anchor
from src.research.inputs import resolve_research_field
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext, contains_pii
from src.research.vocabulary import (
    CONFIRMATION_BIAS_MARKERS,
    INJECTION_MARKERS,
    QUERY_CONNECTOR_TOKENS,
)
from src.schemas.common import ExtractionMode, ResearchBranch
from src.schemas.research import (
    CHALLENGE_PURPOSES,
    CandidateQuery,
    CandidateQueryPlan,
    ProjectFieldReference,
    QueryPlanLimits,
    QueryPurpose,
    QueryRejectionReason,
    QueryStatus,
    ResearchIssueCode,
    ResearchQuery,
    SourceTerm,
    VerifiedQueryPlan,
)

R = QueryRejectionReason
P = QueryPurpose

PLANNABLE_BRANCHES: frozenset[ResearchBranch] = frozenset(
    {
        ResearchBranch.ACADEMIC,
        ResearchBranch.PATENT,
        ResearchBranch.PRODUCT,
        ResearchBranch.OPEN_SOURCE,
        ResearchBranch.STANDARDS,
    }
)
"""OFFICIAL_REQUIREMENTS is URL-seeded retrieval, never query-planned."""

_GENERAL_PURPOSES = frozenset(
    {
        P.PROBLEM, P.EXISTING_SOLUTIONS, P.TECHNOLOGY, P.RECENT_WORK, P.LIMITATIONS,
        P.BENCHMARK, P.REVIEW, P.ALTERNATIVES, P.FAILURE_MODES, P.COMPETING_METHODS,
        P.PRIOR_ART,
    }
)

ALLOWED_PURPOSES_BY_BRANCH: dict[ResearchBranch, frozenset[QueryPurpose]] = {
    ResearchBranch.ACADEMIC: _GENERAL_PURPOSES,
    ResearchBranch.PATENT: frozenset(
        {P.PRIOR_ART, P.PATENT_FUNCTION, P.PATENT_MECHANISM, P.EXISTING_SOLUTIONS, P.ALTERNATIVES}
    ),
    ResearchBranch.PRODUCT: frozenset(
        {P.PRODUCT, P.EXISTING_SOLUTIONS, P.ALTERNATIVES, P.LIMITATIONS, P.COMPETING_METHODS,
         P.FAILURE_MODES, P.PRIOR_ART}
    ),
    ResearchBranch.OPEN_SOURCE: frozenset(
        {P.OPEN_SOURCE, P.EXISTING_SOLUTIONS, P.ALTERNATIVES, P.PRIOR_ART, P.BENCHMARK}
    ),
    ResearchBranch.STANDARDS: frozenset(
        {P.TECHNOLOGY, P.BENCHMARK, P.LIMITATIONS, P.FAILURE_MODES}
    ),
}

SOLUTION_ORIENTED_PURPOSES: frozenset[QueryPurpose] = frozenset(
    {
        P.TECHNOLOGY, P.EXISTING_SOLUTIONS, P.PRIOR_ART, P.RECENT_WORK, P.PRODUCT,
        P.OPEN_SOURCE, P.PATENT_FUNCTION, P.PATENT_MECHANISM,
    }
)
"""A plan containing any of these must also contain a challenge query."""

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_REPEATED_PUNCTUATION = re.compile(r"([^\w\s])\1+")
_EDGE_PUNCTUATION = re.compile(r"^[^\w]+|[^\w]+$")


def normalize_query(query: str) -> str:
    """Safe normalization for duplicate detection only.

    Whitespace trimming and folding, Unicode NFC, case folding, repeated
    punctuation, and punctuation at the very ends. Different words are never merged.
    """
    folded = _REPEATED_PUNCTUATION.sub(r"\1", normalize_unicode(query))
    folded = collapse_whitespace(folded).casefold()
    return _EDGE_PUNCTUATION.sub("", folded)


def text_tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize_unicode(text).casefold())


def term_in_text(term: str, text: str) -> bool:
    """Every token of ``term`` occurs in ``text``. Containment, not similarity."""
    return value_supported_by_anchor(term, text, ExtractionMode.VERBATIM_TERM)


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    padded = f" {normalize_query(text)} "
    return any(f" {marker}" in padded for marker in markers)


def _parse_branch(raw: str) -> ResearchBranch | None:
    try:
        return ResearchBranch(raw.strip())
    except ValueError:
        return None


def _parse_purpose(raw: str) -> QueryPurpose | None:
    try:
        return QueryPurpose(raw.strip())
    except ValueError:
        return None


def check_candidate_query(
    project: ProjectState,
    candidate: CandidateQuery,
    limits: QueryPlanLimits,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> list[QueryRejectionReason]:
    """Every rule the candidate breaks, in a stable order. Empty means valid."""
    reasons: list[QueryRejectionReason] = []
    branch = _parse_branch(candidate.branch)
    purpose = _parse_purpose(candidate.purpose)
    query = candidate.query.strip()
    terms = [t.term.strip() for t in candidate.source_terms]
    expansions = [e.strip() for e in candidate.expansion_terms]

    if branch is None:
        reasons.append(R.INVALID_BRANCH)
    elif branch not in PLANNABLE_BRANCHES:
        reasons.append(R.BRANCH_NOT_PLANNABLE)
    if purpose is None:
        reasons.append(R.INVALID_PURPOSE)
    elif branch in ALLOWED_PURPOSES_BY_BRANCH and purpose not in ALLOWED_PURPOSES_BY_BRANCH[branch]:
        reasons.append(R.PURPOSE_NOT_ALLOWED_FOR_BRANCH)

    if not query:
        reasons.append(R.EMPTY_QUERY)
    elif len(query) > limits.max_query_length:
        reasons.append(R.QUERY_TOO_LONG)

    if any(contains_pii(text, privacy) for text in (query, *terms, *expansions)):
        reasons.append(R.PII_DETECTED)
    if _has_marker(query, INJECTION_MARKERS) or any(
        _has_marker(e, INJECTION_MARKERS) for e in expansions
    ):
        reasons.append(R.SUSPECTED_PROMPT_INJECTION)
    if _has_marker(query, CONFIRMATION_BIAS_MARKERS):
        reasons.append(R.CONFIRMATION_BIASED_PHRASING)

    if not candidate.source_terms:
        reasons.append(R.NO_SOURCE_TERMS)
    for source in candidate.source_terms:
        resolved = resolve_research_field(project, source.field_path.strip())
        if resolved is None:
            reasons.append(R.INVALID_FIELD_REFERENCE)
        elif not source.term.strip() or not any(
            term_in_text(source.term, value) for value in resolved
        ):
            reasons.append(R.SOURCE_TERM_NOT_IN_FIELD)
        if query and source.term.strip() and not term_in_text(source.term, query):
            reasons.append(R.SOURCE_TERM_NOT_IN_QUERY)

    if len(expansions) > limits.max_expansion_terms_per_query:
        reasons.append(R.TOO_MANY_EXPANSION_TERMS)
    if any(not e for e in expansions):
        reasons.append(R.EMPTY_EXPANSION_TERM)

    allowed = set(QUERY_CONNECTOR_TOKENS)
    for text in (*terms, *expansions):
        allowed.update(text_tokens(text))
    if query and any(token not in allowed for token in text_tokens(query)):
        reasons.append(R.UNTRACEABLE_QUERY_TOKEN)

    return list(dict.fromkeys(reasons))


def verify_query_plan(
    project: ProjectState,
    candidate: CandidateQueryPlan,
    *,
    research_run_id: UUID,
    planner_version: str,
    limits: QueryPlanLimits,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> VerifiedQueryPlan:
    """Turn an untrusted candidate plan into a verified plan. Pure."""
    seen: set[tuple[ResearchBranch, str]] = set()
    per_branch: Counter[ResearchBranch] = Counter()
    accepted_total = 0
    duplicates = 0
    queries: list[ResearchQuery] = []

    for item in candidate.queries:
        reasons = check_candidate_query(project, item, limits, privacy)
        branch = _parse_branch(item.branch)
        purpose = _parse_purpose(item.purpose)
        normalized = normalize_query(item.query)

        if not reasons and branch is not None:
            key = (branch, normalized)
            if key in seen:
                reasons = [R.DUPLICATE_QUERY]
                duplicates += 1
            elif per_branch[branch] >= limits.max_queries_per_branch:
                reasons = [R.BRANCH_BUDGET_EXCEEDED]
            elif accepted_total >= limits.max_total_queries:
                reasons = [R.TOTAL_BUDGET_EXCEEDED]
            else:
                seen.add(key)
                per_branch[branch] += 1
                accepted_total += 1

        source_terms = [
            SourceTerm(term=t.term.strip(), field_path=t.field_path.strip())
            for t in item.source_terms
            if t.term.strip() and t.field_path.strip()
        ]
        queries.append(
            ResearchQuery(
                research_run_id=research_run_id,
                branch=branch,
                candidate_branch=item.branch,
                purpose=purpose,
                candidate_purpose=item.purpose,
                query=item.query.strip(),
                normalized_query=normalized,
                derived_from=[
                    ProjectFieldReference(field_path=path)
                    for path in dict.fromkeys(t.field_path for t in source_terms)
                ],
                source_terms=source_terms,
                expansion_terms=[e.strip() for e in item.expansion_terms if e.strip()],
                status=QueryStatus.REJECTED if reasons else QueryStatus.ACCEPTED,
                rejection_reasons=reasons,
                planner_version=planner_version,
            )
        )

    accepted = [q for q in queries if q.status is QueryStatus.ACCEPTED]
    challenge_count = sum(1 for q in accepted if q.purpose in CHALLENGE_PURPOSES)
    solution_oriented = any(q.purpose in SOLUTION_ORIENTED_PURPOSES for q in accepted)
    anti_confirmation = bool(accepted) and (challenge_count > 0 or not solution_oriented)

    issues: list[ResearchIssueCode] = []
    if not accepted:
        issues.append(ResearchIssueCode.QUERY_PLAN_EMPTY)
    elif not anti_confirmation:
        issues.append(ResearchIssueCode.QUERY_PLAN_CONFIRMATION_ONLY)

    return VerifiedQueryPlan(
        research_run_id=research_run_id,
        planner_version=planner_version,
        limits=limits,
        queries=queries,
        duplicates_removed=duplicates,
        challenge_query_count=challenge_count,
        anti_confirmation_satisfied=anti_confirmation,
        issues=issues,
    )
