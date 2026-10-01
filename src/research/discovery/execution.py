"""Bounded, recorded search execution shared by both tracks -- sections 13, 32, 34, 35.

One loop, two tracks. For every planned query that has not already run:

1. re-check it at the dispatch gate (PII, injection, qualifier, provider
   capability, authentication) -- a gate only the planner runs is a gate a
   future caller can bypass;
2. request pages up to ``max_pages_per_query`` and ``max_total_observations``;
3. record every page as a ``DiscoveryQueryExecution`` -- success, empty or
   failed -- with attempts and classified errors;
4. record every cut-off: a provider-reported remainder, a page budget, a total
   budget. Nothing is truncated silently, so nothing partial reads complete.

Idempotency: each page has a stable key (``<query stable key>#p<page>``);
a key already in ``executed_query_keys`` is never re-sent, which is what makes
a run resumed from a checkpoint duplicate nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.research.academic.http import Sleeper
from src.research.discovery.planner import query_refusal
from src.research.discovery.transport import call_with_retries
from src.research.privacy import ResearchPrivacyContext
from src.schemas.discovery import (
    DiscoveryBudget,
    DiscoveryCoverageStatus,
    DiscoveryErrorKind,
    DiscoveryExecutionStatus,
    DiscoveryOutcome,
    DiscoveryProviderCapability,
    DiscoveryQuery,
    DiscoveryQueryExecution,
    DiscoveryQueryRejectionReason,
    RejectedDiscoveryQuery,
    safe_summary,
)


@dataclass
class SearchPage:
    """A provider page, already parsed. Items are provider-shaped, untrusted."""

    items: list[Any] = field(default_factory=list)
    more_available: bool = False
    provider_total: int | None = None
    incomplete_results: bool = False


@dataclass
class SearchOutcome:
    executions: list[DiscoveryQueryExecution]
    observations: list[Any]
    executed_keys: list[str]
    refused: list[RejectedDiscoveryQuery]
    budget: DiscoveryBudget


def page_key(query: DiscoveryQuery, page: int) -> str:
    return f"{query.stable_key}#p{page}"


def dispatch_refusal(
    query: DiscoveryQuery,
    capability: DiscoveryProviderCapability | None,
    privacy: ResearchPrivacyContext,
    authenticated: bool,
) -> RejectedDiscoveryQuery | None:
    def refuse(reason: DiscoveryQueryRejectionReason, detail: str = "") -> RejectedDiscoveryQuery:
        pii = reason is DiscoveryQueryRejectionReason.PII_DETECTED
        return RejectedDiscoveryQuery(
            query_id=query.query_id,
            track=query.track,
            provider=query.provider,
            purpose=query.purpose,
            query_text="" if pii else query.query_text,
            claim_id=query.claim_ids[0],
            reason=reason,
            detail="" if pii else safe_summary(detail),
        )

    if capability is None or not capability.supports(query.operation):
        return refuse(DiscoveryQueryRejectionReason.PROVIDER_NOT_DISPATCHABLE, "operation not declared")
    if query.operation in capability.authenticated_operations and not authenticated:
        return refuse(DiscoveryQueryRejectionReason.OPERATION_REQUIRES_AUTHENTICATION, "credentials required")
    reason = query_refusal(query.query_text, privacy)
    if reason is not None:
        return refuse(reason)
    return None


def execute_search(
    queries: list[DiscoveryQuery],
    *,
    executed_keys: list[str],
    budget: DiscoveryBudget,
    capability: DiscoveryProviderCapability | None,
    authenticated: bool,
    privacy: ResearchPrivacyContext,
    request_page: Callable[[DiscoveryQuery, int, int], SearchPage],
    make_observations: Callable[[DiscoveryQuery, SearchPage, int, datetime], list[Any]],
    now: Callable[[], datetime],
    research_run_id: Any,
    sleeper: Sleeper | None = None,
    existing_observation_count: int = 0,
) -> SearchOutcome:
    counts = budget.model_dump()
    executed = list(executed_keys)
    executions: list[DiscoveryQueryExecution] = []
    observations: list[Any] = []
    refused: list[RejectedDiscoveryQuery] = []
    total = existing_observation_count

    for query in queries:
        if page_key(query, 1) in executed:
            counts["queries_reused_from_checkpoint"] += 1
            continue
        refusal = dispatch_refusal(query, capability, privacy, authenticated)
        if refusal is not None:
            refused.append(refusal)
            counts["queries_rejected"] += 1
            executed.append(page_key(query, 1))
            continue
        if total >= budget.max_total_observations:
            counts["queries_truncated"] += 1
            continue

        fetched = 0
        for page in range(1, budget.max_pages_per_query + 1):
            remaining = budget.max_total_observations - total
            if remaining <= 0:
                counts["results_truncated"] += 1
                break
            count = min(query.requested_count, budget.max_results_per_query, remaining)
            outcome = call_with_retries(
                lambda: request_page(query, page, count),
                max_attempts=budget.retry_limit,
                sleeper=sleeper,
            )
            counts["pages_requested"] += 1
            executed.append(page_key(query, page))
            if outcome.attempts > 1:
                counts["queries_retried"] += 1
            if not outcome.succeeded:
                counts["queries_failed"] += 1
                executions.append(
                    DiscoveryQueryExecution(
                        query_id=query.query_id,
                        research_run_id=research_run_id,
                        provider=query.provider,
                        operation=query.operation,
                        page=page,
                        status=DiscoveryExecutionStatus.FAILED,
                        attempts=outcome.attempts,
                        results_requested=count,
                        errors=outcome.errors,
                        executed_at=now(),
                    )
                )
                break
            result: SearchPage = outcome.payload
            returned = len(result.items)
            items = result.items[:count]
            over = returned - len(items)
            page_observations = make_observations(query, SearchPage(items=items), (page - 1) * count + 1, now())
            accepted = len(page_observations)
            observations.extend(page_observations)
            total += accepted
            fetched += returned
            counts["results_returned"] += returned
            counts["results_accepted"] += accepted
            counts["results_truncated"] += over
            if result.provider_total is not None:
                seen = counts.get("provider_reported_total_seen") or 0
                counts["provider_reported_total_seen"] = max(seen, result.provider_total)
            more = result.more_available or (
                result.provider_total is not None and result.provider_total > fetched
            )
            if page == 1:
                counts["queries_executed"] += 1
            executions.append(
                DiscoveryQueryExecution(
                    query_id=query.query_id,
                    research_run_id=research_run_id,
                    provider=query.provider,
                    operation=query.operation,
                    page=page,
                    status=DiscoveryExecutionStatus.SUCCESS if accepted else DiscoveryExecutionStatus.EMPTY,
                    attempts=outcome.attempts,
                    results_requested=count,
                    results_returned=returned,
                    results_accepted=accepted,
                    provider_reported_total=result.provider_total,
                    provider_reports_more=more,
                    provider_incomplete_results=result.incomplete_results,
                    errors=outcome.errors,
                    executed_at=now(),
                )
            )
            if not more or not returned:
                break
            if page >= budget.max_pages_per_query:
                # The provider says more exists than the page budget allows:
                # recorded, so the search can never read as complete.
                counts["pages_truncated"] += 1
                break
    return SearchOutcome(
        executions=executions,
        observations=observations,
        executed_keys=executed,
        refused=refused,
        budget=DiscoveryBudget.model_validate(counts),
    )


def derive_coverage(
    executions: list[DiscoveryQueryExecution],
    budget: DiscoveryBudget,
    refused_at_dispatch: list[RejectedDiscoveryQuery],
) -> DiscoveryCoverageStatus:
    """What the search can honestly claim about itself. Never exhaustive.

    A query refused at the dispatch gate did not run, so the search is
    error-partial; when every refusal was for missing credentials and nothing
    ran at all, the search was blocked on authentication.
    """
    if not executions:
        if refused_at_dispatch:
            if all(
                r.reason is DiscoveryQueryRejectionReason.OPERATION_REQUIRES_AUTHENTICATION
                for r in refused_at_dispatch
            ):
                return DiscoveryCoverageStatus.BLOCKED_AUTH
            return DiscoveryCoverageStatus.PARTIAL_ERROR
        if budget.queries_truncated:
            return DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
        return DiscoveryCoverageStatus.NOT_EXECUTED
    answered = [e for e in executions if not e.failed]
    auth = [e for e in executions if e.final_error is DiscoveryErrorKind.AUTHENTICATION_ERROR]
    if auth and not answered:
        return DiscoveryCoverageStatus.BLOCKED_AUTH
    if refused_at_dispatch or any(e.failed for e in executions):
        return DiscoveryCoverageStatus.PARTIAL_ERROR
    if budget.truncated or any(e.provider_reports_more or e.provider_incomplete_results for e in executions):
        return DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS


def derive_outcome(executions: list[DiscoveryQueryExecution]) -> DiscoveryOutcome:
    if not executions:
        return DiscoveryOutcome.NOT_RUN
    succeeded = any(e.status is DiscoveryExecutionStatus.SUCCESS for e in executions)
    failed = any(e.failed for e in executions)
    if succeeded and failed:
        return DiscoveryOutcome.PARTIAL
    if succeeded:
        return DiscoveryOutcome.SUCCESS
    if failed:
        return DiscoveryOutcome.FAILED
    return DiscoveryOutcome.EMPTY


__all__ = [
    "SearchOutcome",
    "SearchPage",
    "derive_coverage",
    "derive_outcome",
    "dispatch_refusal",
    "execute_search",
    "page_key",
]
