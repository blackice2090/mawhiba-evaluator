"""The Phase 2G stage pipeline -- sections 4, 13, 26, 29, 30.

Each stage is a pure function from one ``PatentPriorArtRun`` to its successor,
re-validated in full by the contract on every step. The graph nodes in
``src.graph.patent_nodes`` are thin wrappers over these functions, and the
offline eval drives the same functions through the real graph, so there is one
implementation of the pipeline rather than a production path and a test path:

    open_patent_run          budget, capabilities, cutoff -- nothing searched
    plan_stage               PatentSearchQuery list from canonical claim text
    execute_stage            PatentSearchResult + PatentSearchObservation
    verify_stage             VerifiedPatentPublication + SourceRecord
    family_stage             PatentFamilyGroup, members preserved
    snapshot_stage           PatentTextSnapshot per content type
    candidate_stage          PatentPriorArtCandidate with chronology
    finalize_stage           coverage + outcome recomputed; run closed

What no stage takes as input, and therefore cannot act on: a claim's evidence,
its Phase 2E sufficiency, its Phase 2F score, the trust gate, or the evaluation
status. What no stage returns: anything but a ``PatentPriorArtRun``. The run is
additive to the ``ResearchRun`` and nothing else (section 31, ADR-018).

Idempotency (section 29) has two layers. Inside one invocation, every stage
that already produced its output returns the run unchanged, so a replayed node
cannot double anything. Across invocations, ``execute_stage`` skips any query
whose ``stable_key`` is already in ``executed_query_keys``, so a run resumed
from a checkpoint mid-search never re-sends a query that already answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from src.llm.provider import StructuredModelProvider
from src.research.patent.candidates import build_candidates
from src.research.patent.capabilities import (
    PATENT_PROVIDER_CAPABILITIES,
    capability_for,
    connector_versions,
)
from src.research.patent.cql import validate_cql
from src.research.patent.dedup import resolve_publications
from src.research.patent.family import apply_families, resolve_families
from src.research.patent.planner import (
    PATENT_PLANNER_PROMPT_VERSION,
    PlannableClaim,
    PlannableComponent,
    plan_patent_queries,
)
from src.research.patent.provider import PatentSearchProvider
from src.research.patent.snapshots import (
    DEFAULT_CONTENT_TYPES,
    apply_snapshots,
    capture_snapshots,
)
from src.research.patent.verification import verify_observations
from src.research.privacy import (
    EMPTY_PRIVACY_CONTEXT,
    ResearchPrivacyContext,
    contains_pii,
)
from src.research.settings import PatentResearchSettings
from src.schemas.patent import (
    NO_SEARCH_CUTOFF,
    PatentBranchOutcome,
    PatentBudgetReport,
    PatentContentType,
    PatentPriorArtRun,
    PatentProvider,
    PatentQueryRejectionReason,
    PatentRejectionReason,
    PatentSearchCoverageStatus,
    PatentSearchCutoff,
    PatentSearchQuery,
    PatentSearchResult,
    PatentSearchStatus,
    RejectedPatentQuery,
    SUCCESSFUL_PATENT_STATUSES,
    patent_safe_summary,
)
from src.workflow.clock import workflow_now

PATENT_PIPELINE_VERSION = "PATENT-PIPELINE-V1"

DEFAULT_PATENT_PROVIDER = PatentProvider.EPO_OPS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _successor(run: PatentPriorArtRun, **changes: Any) -> PatentPriorArtRun:
    """A new run with ``changes``, re-validated in full. Nothing mutates."""
    return PatentPriorArtRun.model_validate({**dict(run), **changes})


def _budget(run: PatentPriorArtRun, **changes: Any) -> PatentBudgetReport:
    return PatentBudgetReport.model_validate({**dict(run.budget), **changes})


def budget_from_settings(settings: PatentResearchSettings) -> PatentBudgetReport:
    return PatentBudgetReport(
        max_queries_per_claim=settings.max_queries_per_claim,
        max_queries_per_run=settings.max_queries_per_run,
        max_results_per_query=settings.max_results_per_query,
        max_pages_per_query=settings.max_pages_per_query,
        max_total_provider_results=settings.max_total_provider_results,
        max_verified_publications=settings.max_verified_publications,
        max_family_lookups=settings.max_family_lookups,
        max_classification_expansions=settings.max_classification_expansions,
        retry_limit=settings.retry_limit,
        timeout_seconds=settings.timeout_seconds,
    )


def plannable_claims(
    claims: Sequence[Any],
    component_texts: dict[str, list[str]] | None = None,
) -> list[PlannableClaim]:
    """Read-only projections of canonical claims for the planner.

    ``claims`` are ``ClaimRecord``-shaped objects; only ``claim_id`` and the
    claim text are read. ``component_texts`` carries the Phase 2E inventory's
    component texts where a run has one. Nothing is written back: the result
    holds copies, and a ``PlannableClaim`` is frozen.
    """
    component_texts = component_texts or {}
    projected: list[PlannableClaim] = []
    for claim in claims:
        texts = component_texts.get(claim.claim_id, [])
        projected.append(
            PlannableClaim(
                claim_id=claim.claim_id,
                text=claim.claim,
                components=tuple(
                    PlannableComponent(
                        component_id=f"{claim.claim_id}#{index}", text=text
                    )
                    for index, text in enumerate(texts, start=1)
                ),
            )
        )
    return projected


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def open_patent_run(
    research_run_id: UUID,
    *,
    settings: PatentResearchSettings,
    cutoff: PatentSearchCutoff = NO_SEARCH_CUTOFF,
    provider: PatentProvider = DEFAULT_PATENT_PROVIDER,
) -> PatentPriorArtRun:
    """A fresh patent run: budget, provider honesty table and cutoff, no search.

    Every provider's capability is recorded, dispatchable or not, so the run
    itself shows that PATENTSCOPE was unsupported by access policy and USPTO
    deferred -- not merely that they were absent (section 2).
    """
    return PatentPriorArtRun(
        research_run_id=research_run_id,
        providers=[provider],
        provider_capabilities=list(PATENT_PROVIDER_CAPABILITIES.values()),
        connector_versions=connector_versions(),
        search_cutoff=cutoff,
        budget=budget_from_settings(settings),
        started_at=workflow_now(),
    )


def plan_stage(
    run: PatentPriorArtRun,
    claims: list[PlannableClaim],
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    model_provider: StructuredModelProvider | None = None,
    model: str = "",
) -> PatentPriorArtRun:
    """Plan queries from canonical claim text. A no-op once a plan exists."""
    if run.planned_queries or run.excluded_claims or run.rejected_queries:
        return run
    provider = run.providers[0] if run.providers else DEFAULT_PATENT_PROVIDER
    budget = run.budget
    plan = plan_patent_queries(
        claims,
        research_run_id=run.research_run_id,
        provider=provider,
        max_queries_per_claim=budget.max_queries_per_claim,
        max_queries_per_run=budget.max_queries_per_run,
        results_per_query=min(budget.max_results_per_query, 100),
        privacy=privacy,
        model_provider=model_provider,
        model=model,
    )
    rejected_budget = sum(
        1
        for r in plan.rejected
        if r.reason is PatentQueryRejectionReason.QUERY_BUDGET_EXCEEDED
    )
    claim_budget = sum(
        1 for e in plan.excluded_claims if e.reason.value == "CLAIM_BUDGET_EXCEEDED"
    )
    return _successor(
        run,
        planned_queries=plan.queries,
        rejected_queries=plan.rejected,
        excluded_claims=plan.excluded_claims,
        planner_prompt_version=(
            PATENT_PLANNER_PROMPT_VERSION if plan.model_assisted else None
        ),
        budget=_budget(
            run,
            claims_considered=plan.claims_considered,
            claims_excluded=len(plan.excluded_claims),
            queries_planned=len(plan.queries),
            queries_rejected=len(plan.rejected),
            queries_truncated=rejected_budget + claim_budget,
        ),
    )


def _dispatch_refusal(
    query: PatentSearchQuery, privacy: ResearchPrivacyContext
) -> RejectedPatentQuery | None:
    """The last gate before a third-party request (sections 12, 28).

    The planner already validated the expression; this re-validates because a
    gate that runs only in the planner is a gate a future caller can bypass.
    It also refuses a provider this system may not dispatch to at all.
    """
    if not capability_for(query.provider).dispatchable:
        return RejectedPatentQuery(
            query_id=query.query_id,
            provider=query.provider,
            purpose=query.purpose,
            strategy=query.strategy,
            query_expression=query.query_expression,
            reason=PatentQueryRejectionReason.PROVIDER_NOT_DISPATCHABLE,
            detail=patent_safe_summary(
                capability_for(query.provider).access_status.value
            ),
        )
    if contains_pii(query.query_expression, privacy):
        return RejectedPatentQuery(
            query_id=query.query_id,
            provider=query.provider,
            purpose=query.purpose,
            strategy=query.strategy,
            reason=PatentQueryRejectionReason.PII_DETECTED,
        )
    validated = validate_cql(query.query_expression)
    if not validated.ok:
        return RejectedPatentQuery(
            query_id=query.query_id,
            provider=query.provider,
            purpose=query.purpose,
            strategy=query.strategy,
            query_expression=query.query_expression,
            reason=validated.reason or PatentQueryRejectionReason.INVALID_QUERY_SYNTAX,
            detail=validated.detail,
        )
    return None


def execute_stage(
    run: PatentPriorArtRun,
    provider: PatentSearchProvider | None,
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> PatentPriorArtRun:
    """Send each planned query once, within budget, and record everything.

    With no provider -- no credentials -- nothing is sent and the run records
    ``BLOCKED_AUTH``: an unauthenticated search against a quota-limited anonymous
    tier is not a contract this project builds on (section 27).
    """
    budget = run.budget
    if not run.planned_queries:
        return run
    if provider is None:
        return _successor(
            run,
            coverage_status=PatentSearchCoverageStatus.BLOCKED_AUTH,
            outcome=PatentBranchOutcome.FAILED,
        )

    executed = list(run.executed_query_keys)
    results = list(run.provider_results)
    observations = list(run.observations)
    rejected_records = list(run.rejected_records)
    refused = list(run.rejected_queries)
    planned = list(run.planned_queries)
    counts = {
        "queries_executed": budget.queries_executed,
        "queries_failed": budget.queries_failed,
        "queries_retried": budget.queries_retried,
        "queries_reused_from_checkpoint": 0,
        "queries_truncated": budget.queries_truncated,
        "queries_rejected": budget.queries_rejected,
        "pages_requested": budget.pages_requested,
        "results_returned": budget.results_returned,
        "results_accepted": budget.results_accepted,
        "results_truncated_per_query": budget.results_truncated_per_query,
        "results_truncated_total": budget.results_truncated_total,
    }
    reported_seen = budget.provider_reported_total_seen
    dispatch_refused = 0

    for query in list(planned):
        if query.stable_key in executed:
            counts["queries_reused_from_checkpoint"] += 1
            continue
        refusal = _dispatch_refusal(query, privacy)
        if refusal is not None:
            refused.append(refusal)
            counts["queries_rejected"] += 1
            dispatch_refused += 1
            executed.append(query.stable_key)
            continue
        if counts["results_returned"] >= budget.max_total_provider_results:
            counts["queries_truncated"] += 1
            continue

        page_query = query
        for page in range(budget.max_pages_per_query):
            remaining_total = budget.max_total_provider_results - counts["results_returned"]
            if remaining_total <= 0:
                counts["results_truncated_total"] += 1
                break
            limit = min(page_query.requested_limit, remaining_total)
            result = provider.search(page_query, limit=limit)
            counts["pages_requested"] += 1
            executed.append(page_query.stable_key)
            results.append(result)
            observations.extend(result.observations)
            rejected_records.extend(result.rejected)
            counts["results_returned"] += result.accepted_count + result.rejected_count
            counts["results_accepted"] += result.accepted_count
            counts["results_truncated_per_query"] += sum(
                1
                for r in result.rejected
                if r.reason is PatentRejectionReason.PROVIDER_RESULT_LIMIT_EXCEEDED
            )
            if result.attempts > 1:
                counts["queries_retried"] += 1
            if result.failed:
                counts["queries_failed"] += 1
                break
            if page == 0:
                counts["queries_executed"] += 1
            if result.provider_reported_total is not None:
                reported_seen = max(reported_seen or 0, result.provider_reported_total)

            fetched_to = result.requested_range_start + result.requested_limit - 1
            total = result.provider_reported_total
            more = total is not None and total > fetched_to and result.accepted_count
            if not more:
                break
            if page + 1 >= budget.max_pages_per_query:
                # The provider says more matched than the page budget allows.
                # Recorded as truncation, so the run can never read as complete.
                counts["results_truncated_per_query"] += total - fetched_to
                break
            page_query = query.model_copy(
                update={
                    "query_id": _derived_page_id(query, page + 1),
                    "requested_range_start": fetched_to + 1,
                }
            )
            planned.append(page_query)

    successor = _successor(
        run,
        planned_queries=planned,
        executed_query_keys=executed,
        provider_results=results,
        observations=observations,
        rejected_records=rejected_records,
        rejected_queries=refused,
        budget=_budget(run, **counts, provider_reported_total_seen=reported_seen),
        coverage_status=_coverage(
            results, run.budget, counts, reported_seen, dispatch_refused
        ),
        outcome=_outcome(results),
    )
    return successor


def _derived_page_id(query: PatentSearchQuery, page: int) -> UUID:
    """A deterministic id for a follow-up Range window of one query."""
    from uuid import uuid5

    return uuid5(query.query_id, f"page-{page}")


def _coverage(
    results: list[PatentSearchResult],
    budget: PatentBudgetReport,
    counts: dict[str, int],
    reported_seen: int | None,
    dispatch_refused: int = 0,
) -> PatentSearchCoverageStatus:
    """What the search can honestly claim about its own coverage (section 13).

    A planned query refused at the dispatch gate is a query that did not run,
    so it is an error-partial search; a budget cut is a limit-partial one.
    Neither may read as complete.
    """
    if not results:
        if dispatch_refused:
            return PatentSearchCoverageStatus.PARTIAL_ERROR
        if counts.get("queries_truncated"):
            return PatentSearchCoverageStatus.PARTIAL_PROVIDER_LIMIT
        return PatentSearchCoverageStatus.NOT_EXECUTED
    auth_failed = [r for r in results if r.status is PatentSearchStatus.AUTH_ERROR]
    answered = [r for r in results if r.executed]
    if auth_failed and not answered:
        return PatentSearchCoverageStatus.BLOCKED_AUTH
    if dispatch_refused or any(r.failed for r in results):
        return PatentSearchCoverageStatus.PARTIAL_ERROR
    truncated = any(
        counts.get(name)
        for name in (
            "queries_truncated",
            "results_truncated_per_query",
            "results_truncated_total",
        )
    ) or (budget.publications_truncated or budget.family_lookups_truncated)
    returned = counts.get("results_returned", 0)
    if truncated or (reported_seen is not None and reported_seen > returned):
        return PatentSearchCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS


def _outcome(results: list[PatentSearchResult]) -> PatentBranchOutcome:
    if not results:
        return PatentBranchOutcome.NOT_RUN
    succeeded = [r for r in results if r.status in SUCCESSFUL_PATENT_STATUSES]
    failed = [r for r in results if r.failed]
    if succeeded and failed:
        return PatentBranchOutcome.PARTIAL
    if succeeded:
        return PatentBranchOutcome.SUCCESS
    if failed:
        return PatentBranchOutcome.FAILED
    return PatentBranchOutcome.EMPTY


def verify_stage(
    run: PatentPriorArtRun,
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> PatentPriorArtRun:
    """Search observations -> verified publications. Nothing unverified crosses."""
    if run.publications or not run.observations:
        return run
    verification = verify_observations(
        run.observations,
        research_run_id=run.research_run_id,
        known_query_ids={q.query_id for q in run.planned_queries},
        privacy=privacy,
    )
    dedup = resolve_publications(
        verification.accepted,
        run.research_run_id,
        max_publications=run.budget.max_verified_publications,
    )
    kept_keys = {p.publication_key for p in dedup.publications}
    truncated_records = [
        record
        for record in verification.accepted
        if record.publication_key not in kept_keys
    ]
    from src.schemas.patent import PatentRejectionStage, RejectedPatentRecord

    budget_rejections = [
        RejectedPatentRecord(
            provider=o.provider,
            query_id=o.query_id,
            stage=PatentRejectionStage.BUDGET,
            reason=PatentRejectionReason.VERIFIED_PUBLICATION_LIMIT_EXCEEDED,
            provider_record_identifier=o.provider_record_id,
            safe_summary=patent_safe_summary(o.publication_key),
        )
        for o in truncated_records
    ]
    budget = _budget(run, publications_truncated=dedup.truncated)
    coverage = run.coverage_status
    if dedup.truncated and coverage is PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS:
        coverage = PatentSearchCoverageStatus.PARTIAL_PROVIDER_LIMIT
    # The kept observations stay on the run; rejected ones are dropped from the
    # observation list but remain on the ledger, so a verified publication can
    # never reference an observation that failed verification.
    kept_observations = [
        o for o in verification.accepted if o.publication_key in kept_keys
    ]
    return _successor(
        run,
        observations=kept_observations,
        rejected_records=[
            *run.rejected_records,
            *verification.rejected,
            *budget_rejections,
        ],
        publications=dedup.publications,
        verified_sources=[p.to_source_record() for p in dedup.publications],
        budget=budget,
        coverage_status=coverage,
    )


def family_stage(
    run: PatentPriorArtRun,
    provider: PatentSearchProvider | None,
    *,
    retrieved_at: datetime | None = None,
) -> PatentPriorArtRun:
    """Group publications into provider-stated families. Members are kept."""
    if run.families or not run.publications:
        return run
    resolution = resolve_families(
        run.publications,
        provider,
        run.research_run_id,
        max_lookups=run.budget.max_family_lookups if provider is not None else 0,
        retrieved_at=retrieved_at or workflow_now(),
    )
    return _successor(
        run,
        families=resolution.families,
        publications=apply_families(run.publications, resolution),
        budget=_budget(
            run,
            family_lookups_performed=resolution.lookups_performed,
            family_lookups_truncated=resolution.lookups_truncated
            if provider is not None
            else 0,
        ),
    )


def snapshot_stage(
    run: PatentPriorArtRun,
    provider: PatentSearchProvider | None,
    *,
    fetch_description: bool = False,
    retrieved_at: datetime | None = None,
) -> PatentPriorArtRun:
    """Capture per-content-type text; record every absence explicitly."""
    if run.snapshots or not run.publications:
        return run
    if any(p.content.title is not p.content.title.UNKNOWN for p in run.publications):
        return run
    content_types = DEFAULT_CONTENT_TYPES + (
        (PatentContentType.DESCRIPTION,) if fetch_description else ()
    )
    outcome = capture_snapshots(
        run.publications,
        provider,
        run.research_run_id,
        content_types=content_types,
        retrieved_at=retrieved_at or workflow_now(),
    )
    return _successor(
        run,
        snapshots=outcome.snapshots,
        publications=apply_snapshots(run.publications, outcome),
    )


def candidate_stage(run: PatentPriorArtRun) -> PatentPriorArtRun:
    """Verified publications -> research candidates with a date line."""
    if run.candidates or not run.publications:
        return run
    outcome = build_candidates(
        run.publications,
        queries=run.planned_queries,
        families=run.families,
        cutoff=run.search_cutoff,
    )
    return _successor(run, candidates=outcome.candidates)


def finalize_stage(run: PatentPriorArtRun) -> PatentPriorArtRun:
    """Close the run. Coverage is re-derived so no earlier step can overstate it."""
    if run.is_terminal:
        return run
    coverage = run.coverage_status
    if coverage is PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS and (
        run.budget.truncated
    ):
        coverage = PatentSearchCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return _successor(run, coverage_status=coverage, completed_at=workflow_now())


def run_patent_pipeline(
    research_run_id: UUID,
    claims: list[PlannableClaim],
    provider: PatentSearchProvider | None,
    *,
    settings: PatentResearchSettings | None = None,
    cutoff: PatentSearchCutoff = NO_SEARCH_CUTOFF,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    model_provider: StructuredModelProvider | None = None,
    model: str = "",
    resume_from: PatentPriorArtRun | None = None,
) -> PatentPriorArtRun:
    """Every stage in order. Used by tests and tools; the graph runs the same
    stage functions one node at a time."""
    run = resume_from or open_patent_run(
        research_run_id, settings=settings or PatentResearchSettings(), cutoff=cutoff
    )
    run = plan_stage(
        run, claims, privacy=privacy, model_provider=model_provider, model=model
    )
    run = execute_stage(run, provider, privacy=privacy)
    run = verify_stage(run, privacy=privacy)
    run = family_stage(run, provider)
    run = snapshot_stage(
        run,
        provider,
        fetch_description=(settings or PatentResearchSettings()).fetch_description,
    )
    run = candidate_stage(run)
    return finalize_stage(run)


__all__ = [
    "DEFAULT_PATENT_PROVIDER",
    "PATENT_PIPELINE_VERSION",
    "budget_from_settings",
    "candidate_stage",
    "execute_stage",
    "family_stage",
    "finalize_stage",
    "open_patent_run",
    "plan_stage",
    "plannable_claims",
    "run_patent_pipeline",
    "snapshot_stage",
    "verify_stage",
]
