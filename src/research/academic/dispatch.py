"""Query eligibility, budget enforcement and provider dispatch.

Three responsibilities, deliberately kept apart from the connectors:

**Eligibility.** Only an ACCEPTED entry of the Phase 2A verified query plan, on
the ACADEMIC branch, with a purpose that is actually routed to academic search,
ever reaches a provider. Raw student text has no path here: the planner's
provenance rules and PII minimization are upstream, and this module re-checks
for personal data anyway, because the query is about to leave the system.

**Budget.** Four independent limits, all deterministic. Reaching one truncates
and is recorded as truncation; it is never reported as a provider failure.

**Isolation.** Providers are dispatched one at a time, and each result is
independent (ADR-008). A provider that times out contributes a failed result and
nothing else: it cannot remove, alter or invalidate a result another provider
already produced.

Execution is sequential on purpose. Correctness must not depend on concurrency;
running the three providers in parallel is a performance change for a later
phase, recorded as technical debt rather than smuggled in here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from src.research.academic.provider import AcademicSearchProvider
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext, contains_pii
from src.research.query_verification import normalize_query
from src.research.settings import AcademicSearchSettings
from src.schemas.academic import (
    ACADEMIC_SEARCH_PURPOSES,
    AcademicBranchOutcome,
    AcademicBudgetReport,
    AcademicProvider,
    AcademicQueryExclusionReason,
    AcademicRejectionReason,
    AcademicRejectionStage,
    AcademicSearchQuery,
    AcademicSearchResult,
    AcademicSourceCandidate,
    ExcludedAcademicQuery,
    RejectedAcademicCandidate,
)
from src.schemas.common import ResearchBranch
from src.schemas.research import QueryStatus, ResearchQuery, VerifiedQueryPlan

logger = logging.getLogger(__name__)

ACADEMIC_DISPATCH_VERSION = "ACADEMIC-DISPATCH-V1"


@dataclass
class QuerySelection:
    """Which planned queries will be executed, and why the rest will not."""

    eligible: list[ResearchQuery] = field(default_factory=list)
    excluded: list[ExcludedAcademicQuery] = field(default_factory=list)
    available: int = 0
    truncated: int = 0


@dataclass
class DispatchOutcome:
    """Everything the provider fan-out produced, after run-level budgets."""

    results: list[AcademicSearchResult] = field(default_factory=list)
    candidates: list[AcademicSourceCandidate] = field(default_factory=list)
    rejected: list[RejectedAcademicCandidate] = field(default_factory=list)
    returned_count: int = 0
    truncated_per_provider: int = 0
    truncated_total: int = 0


def _excluded(
    query: ResearchQuery, reason: AcademicQueryExclusionReason
) -> ExcludedAcademicQuery:
    return ExcludedAcademicQuery(
        query_id=query.query_id,
        # A query excluded for personal data is recorded without its text: the
        # ledger must never become the place the PII survives.
        query=""
        if reason is AcademicQueryExclusionReason.PII_DETECTED
        else query.query,
        candidate_branch=query.candidate_branch or (query.branch.value if query.branch else ""),
        candidate_purpose=query.candidate_purpose
        or (query.purpose.value if query.purpose else ""),
        reason=reason,
    )


def select_academic_queries(
    plan: VerifiedQueryPlan,
    settings: AcademicSearchSettings,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> QuerySelection:
    """Decide which planned queries the academic branch may execute."""
    selection = QuerySelection()
    seen: set[str] = set()

    for query in plan.queries:
        if query.status is not QueryStatus.ACCEPTED:
            selection.excluded.append(
                _excluded(query, AcademicQueryExclusionReason.QUERY_NOT_ACCEPTED)
            )
            continue
        if query.branch is not ResearchBranch.ACADEMIC:
            selection.excluded.append(
                _excluded(query, AcademicQueryExclusionReason.NOT_ACADEMIC_BRANCH)
            )
            continue
        if query.purpose not in ACADEMIC_SEARCH_PURPOSES:
            selection.excluded.append(
                _excluded(
                    query, AcademicQueryExclusionReason.PURPOSE_NOT_ROUTED_TO_ACADEMIC
                )
            )
            continue
        if not query.query.strip():
            selection.excluded.append(
                _excluded(query, AcademicQueryExclusionReason.EMPTY_QUERY)
            )
            continue
        if contains_pii(query.query, privacy):
            selection.excluded.append(
                _excluded(query, AcademicQueryExclusionReason.PII_DETECTED)
            )
            continue

        normalized = normalize_query(query.query)
        if normalized in seen:
            selection.excluded.append(
                _excluded(query, AcademicQueryExclusionReason.DUPLICATE_QUERY)
            )
            continue
        seen.add(normalized)
        selection.available += 1
        selection.eligible.append(query)

    return selection


def enforce_query_budget(
    selection: QuerySelection, settings: AcademicSearchSettings
) -> QuerySelection:
    """Cut the eligible queries down to the per-run budget.

    Truncation is recorded with its own exclusion reason, so "we chose not to
    run this query" never reads like "this query was invalid".
    """
    limit = settings.max_academic_queries_per_run
    if len(selection.eligible) <= limit:
        return selection
    return QuerySelection(
        eligible=selection.eligible[:limit],
        excluded=[
            *selection.excluded,
            *(
                _excluded(query, AcademicQueryExclusionReason.QUERY_BUDGET_EXCEEDED)
                for query in selection.eligible[limit:]
            ),
        ],
        available=selection.available,
        truncated=len(selection.eligible) - limit,
    )


def build_provider_queries(
    selection: QuerySelection, settings: AcademicSearchSettings, research_run_id: UUID
) -> list[AcademicSearchQuery]:
    """Expand each eligible query into one request per enabled provider."""
    return [
        AcademicSearchQuery(
            research_run_id=research_run_id,
            query_id=query.query_id,
            branch=ResearchBranch.ACADEMIC,
            purpose=query.purpose,
            query=query.query,
            provider=provider,
            requested_limit=settings.max_results_per_query_per_provider,
        )
        for query in selection.eligible
        for provider in settings.enabled_providers
    ]


def dispatch_academic_queries(
    queries: list[AcademicSearchQuery],
    providers: list[AcademicSearchProvider],
    settings: AcademicSearchSettings,
) -> list[AcademicSearchResult]:
    """Run every request. One result per request, whatever happened to the others.

    Sequential and side-effect free between calls: this is where ADR-008 is
    implemented, and it is implemented by there being nothing that could let one
    provider's failure touch another provider's result.
    """
    by_name = {p.provider_name: p for p in providers}
    results: list[AcademicSearchResult] = []
    for query in queries:
        provider = by_name.get(query.provider)
        if provider is None:
            logger.debug("no provider injected for %s; skipping", query.provider.value)
            continue
        results.append(
            provider.search(query, limit=settings.max_results_per_query_per_provider)
        )
    return results


def collect_candidates(
    results: list[AcademicSearchResult], settings: AcademicSearchSettings
) -> DispatchOutcome:
    """Accumulate provider candidates under the run-level budgets.

    A provider result always reports what that one call produced. The run-level
    caps are applied here, so the per-call record stays an honest account of the
    call while the truncation is visible as its own ledger entries.
    """
    outcome = DispatchOutcome(results=list(results))
    per_provider: dict[AcademicProvider, int] = {}

    for result in results:
        outcome.rejected.extend(result.rejected)
        outcome.returned_count += len(result.candidates)
        for candidate in result.candidates:
            used = per_provider.get(result.provider, 0)
            if used >= settings.max_results_per_provider_per_run:
                outcome.truncated_per_provider += 1
                outcome.rejected.append(
                    _budget_rejection(
                        candidate, AcademicRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED
                    )
                )
                continue
            if len(outcome.candidates) >= settings.max_total_academic_candidates:
                outcome.truncated_total += 1
                outcome.rejected.append(
                    _budget_rejection(
                        candidate, AcademicRejectionReason.TOTAL_CANDIDATE_LIMIT_EXCEEDED
                    )
                )
                continue
            per_provider[result.provider] = used + 1
            outcome.candidates.append(candidate)

    return outcome


def _budget_rejection(
    candidate: AcademicSourceCandidate, reason: AcademicRejectionReason
) -> RejectedAcademicCandidate:
    return RejectedAcademicCandidate(
        provider=candidate.provider,
        query_id=candidate.query_id,
        stage=AcademicRejectionStage.BUDGET,
        reason=reason,
        provider_record_identifier=candidate.provider_record_id,
        safe_summary=candidate.title,
    )


def build_budget_report(
    settings: AcademicSearchSettings,
    selection: QuerySelection,
    outcome: DispatchOutcome,
    accepted_candidates: int,
) -> AcademicBudgetReport:
    return AcademicBudgetReport(
        max_queries_per_run=settings.max_academic_queries_per_run,
        max_results_per_query_per_provider=settings.max_results_per_query_per_provider,
        max_results_per_provider_per_run=settings.max_results_per_provider_per_run,
        max_total_candidates=settings.max_total_academic_candidates,
        queries_available=selection.available,
        queries_executed=len(selection.eligible),
        queries_truncated=selection.truncated,
        candidates_returned=outcome.returned_count,
        candidates_accepted=accepted_candidates,
        candidates_truncated_per_provider=outcome.truncated_per_provider,
        candidates_truncated_total=outcome.truncated_total,
    )


def aggregate_branch_outcome(
    results: list[AcademicSearchResult], verified_source_count: int
) -> AcademicBranchOutcome:
    """The branch verdict (ADR-008).

    One provider failing while another produced sources is ``PARTIAL``, never
    ``FAILED``. A branch where every provider answered and nobody found anything
    is ``EMPTY``, which is a research finding rather than an outage.
    """
    if not results:
        return AcademicBranchOutcome.NOT_RUN
    failures = sum(1 for r in results if r.failed)
    if failures == len(results):
        # Nobody could be asked. This is the only outage.
        return AcademicBranchOutcome.FAILED
    if failures:
        return AcademicBranchOutcome.PARTIAL
    if verified_source_count == 0:
        return AcademicBranchOutcome.EMPTY
    return AcademicBranchOutcome.SUCCESS


__all__ = [
    "ACADEMIC_DISPATCH_VERSION",
    "DispatchOutcome",
    "QuerySelection",
    "aggregate_branch_outcome",
    "build_budget_report",
    "build_provider_queries",
    "collect_candidates",
    "dispatch_academic_queries",
    "enforce_query_budget",
    "select_academic_queries",
]
