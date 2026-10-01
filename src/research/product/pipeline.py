"""The Phase 2H product-track stage pipeline.

Each stage is a pure function from one ``ProductPriorArtRun`` to a fully
re-validated successor, and records itself in ``stage_markers`` so a replayed
stage is a no-op even when it legitimately produced nothing:

    open_product_run      capabilities, budget, cutoff -- nothing searched
    plan_product_stage    DiscoveryQuery list from canonical claim text
    search_product_stage  executions + ProductSearchObservation
    fetch_product_stage   ProductSourceArtifact via the SSRF-safe fetcher
    identity_product_stage ProductEntity: strong identity / identical content only
    candidate_product_stage ProductPriorArtCandidate with chronology
    finalize_product_stage coverage re-derived; run closed

No stage takes a claim's evidence, sufficiency, score or a patent candidate,
and no stage returns anything but a ``ProductPriorArtRun``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from src.llm.provider import StructuredModelProvider
from src.research.academic.http import Sleeper
from src.research.discovery.capabilities import BRAVE_CAPABILITY, PRODUCT_CAPABILITIES
from src.research.discovery.execution import (
    SearchPage,
    derive_coverage,
    derive_outcome,
    execute_search,
)
from src.research.discovery.planner import plan_discovery_queries
from src.research.discovery.safe_fetch import SafeWebFetcher, canonicalize_url, check_url, host_of
from src.research.patent.planner import PlannableClaim
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.product.brave import WebSearchProvider
from src.research.product.extraction import extract_page
from src.research.product.identity import build_product_candidates, resolve_entities
from src.research.product.roles import DEFAULT_HOST_REGISTRY, HostRegistry, assign_role
from src.research.settings import ProductResearchSettings
from src.schemas.discovery import (
    DISCOVERY_PLANNER_VERSION,
    NO_DISCOVERY_CUTOFF,
    DiscoveryBudget,
    DiscoveryCoverageStatus,
    DiscoveryCutoff,
    DiscoveryErrorKind,
    DiscoveryOutcome,
    DiscoveryQuery,
    DiscoveryTrack,
    stable_id,
)
from src.schemas.product_prior_art import (
    MAX_PRODUCT_SNIPPET_CHARS,
    ProductDateFacts,
    ProductFetchStatus,
    ProductPriorArtRun,
    ProductSearchObservation,
    ProductSourceArtifact,
    ProductSourceRole,
)
from src.workflow.clock import workflow_now

PRODUCT_PIPELINE_VERSION = "PRODUCT-PIPELINE-V1"


def _successor(run: ProductPriorArtRun, stage: str, **changes: Any) -> ProductPriorArtRun:
    """The validated successor. A stage that truncated anything (fetch budget,
    observation budget) downgrades complete coverage here, once, for every
    stage -- so no later stage can leave a truncated run reading complete."""
    markers = [*run.stage_markers, stage] if stage not in run.stage_markers else run.stage_markers
    merged = {**dict(run), **changes, "stage_markers": markers}
    budget = merged["budget"]
    if merged["coverage_status"] is DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS and budget.truncated:
        merged["coverage_status"] = DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return ProductPriorArtRun.model_validate(merged)


def _budget(run: ProductPriorArtRun, **changes: Any) -> DiscoveryBudget:
    return DiscoveryBudget.model_validate({**run.budget.model_dump(), **changes})


def product_budget(settings: ProductResearchSettings) -> DiscoveryBudget:
    return DiscoveryBudget(
        max_queries_per_claim=settings.max_queries_per_claim,
        max_queries_per_run=settings.max_queries_per_run,
        max_results_per_query=settings.max_results_per_query,
        max_pages_per_query=settings.max_pages_per_query,
        max_total_observations=settings.max_total_observations,
        max_detail_lookups=settings.max_product_fetches,
        max_artifact_bytes=settings.max_artifact_bytes,
        max_items_per_parent=1,
        max_network_lookups=0,
        retry_limit=settings.retry_limit,
        timeout_seconds=settings.timeout_seconds,
    )


def open_product_run(
    research_run_id: UUID,
    *,
    settings: ProductResearchSettings,
    cutoff: DiscoveryCutoff = NO_DISCOVERY_CUTOFF,
) -> ProductPriorArtRun:
    return ProductPriorArtRun(
        product_run_id=stable_id(research_run_id, "product-run"),
        research_run_id=research_run_id,
        planner_version=DISCOVERY_PLANNER_VERSION,
        provider_capabilities=list(PRODUCT_CAPABILITIES),
        search_cutoff=cutoff,
        budget=product_budget(settings),
        started_at=workflow_now(),
    )


def plan_product_stage(
    run: ProductPriorArtRun,
    claims: list[PlannableClaim],
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    model_provider: StructuredModelProvider | None = None,
    model: str = "",
) -> ProductPriorArtRun:
    if "PLAN" in run.stage_markers:
        return run
    plan = plan_discovery_queries(
        claims,
        track=DiscoveryTrack.PRODUCT,
        research_run_id=run.research_run_id,
        max_queries_per_claim=run.budget.max_queries_per_claim,
        max_queries_per_run=run.budget.max_queries_per_run,
        results_per_query=run.budget.max_results_per_query,
        privacy=privacy,
        model_provider=model_provider,
        model=model,
    )
    return _successor(
        run,
        "PLAN",
        planned_queries=plan.queries,
        rejected_queries=plan.rejected,
        excluded_claims=plan.excluded_claims,
        planner_prompt_version=(
            next((q.model_prompt_version for q in plan.queries if q.model_prompt_version), None)
        ),
        budget=_budget(
            run,
            claims_considered=plan.claims_considered,
            claims_excluded=len(plan.excluded_claims),
            queries_planned=len(plan.queries),
            queries_rejected=len(plan.rejected),
            queries_truncated=plan.budget_rejections,
        ),
    )


def _observations_factory(run: ProductPriorArtRun):
    def make(query: DiscoveryQuery, page: SearchPage, first_rank: int, now: Any) -> list[ProductSearchObservation]:
        out: list[ProductSearchObservation] = []
        for offset, hit in enumerate(page.items):
            rank = first_rank + offset
            try:
                canonical = canonicalize_url(hit.url)
                if urlsplit(canonical).scheme not in ("http", "https"):
                    continue
            except ValueError:
                continue
            out.append(
                ProductSearchObservation(
                    observation_id=stable_id(run.research_run_id, "product-obs", query.query_id, rank),
                    research_run_id=run.research_run_id,
                    query_id=query.query_id,
                    provider=query.provider,
                    retrieval_rank=rank,
                    url=hit.url,
                    canonical_url=canonical,
                    title=hit.title,
                    snippet=hit.snippet[:MAX_PRODUCT_SNIPPET_CHARS],
                    provider_date=hit.provider_date,
                    retrieved_at=now,
                )
            )
        return out

    return make


def search_product_stage(
    run: ProductPriorArtRun,
    provider: WebSearchProvider | None,
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    sleeper: Sleeper | None = None,
) -> ProductPriorArtRun:
    """Absent provider = no API key = BLOCKED_AUTH, and nothing is sent."""
    if "SEARCH" in run.stage_markers:
        return run
    if not run.planned_queries:
        return _successor(run, "SEARCH")
    if provider is None:
        return _successor(
            run, "SEARCH",
            coverage_status=DiscoveryCoverageStatus.BLOCKED_AUTH,
            outcome=DiscoveryOutcome.NOT_RUN,
        )
    outcome = execute_search(
        run.planned_queries,
        executed_keys=run.executed_query_keys,
        budget=run.budget,
        capability=BRAVE_CAPABILITY,
        authenticated=True,
        privacy=privacy,
        request_page=lambda q, page, count: provider.search(q, page=page, count=count),
        make_observations=_observations_factory(run),
        now=workflow_now,
        research_run_id=run.research_run_id,
        sleeper=sleeper,
        existing_observation_count=len(run.observations),
    )
    executions = [*run.executions, *outcome.executions]
    refused = [*run.rejected_queries, *outcome.refused]
    observations = [*run.observations, *outcome.observations]
    return _successor(
        run,
        "SEARCH",
        executions=executions,
        observations=observations,
        executed_query_keys=outcome.executed_keys,
        rejected_queries=refused,
        budget=outcome.budget,
        coverage_status=derive_coverage(executions, outcome.budget, outcome.refused),
        outcome=derive_outcome(executions),
    )


_ERROR_FOR_STATUS = {
    ProductFetchStatus.FETCH_UNSAFE: DiscoveryErrorKind.FETCH_UNSAFE,
    ProductFetchStatus.FETCH_BLOCKED: DiscoveryErrorKind.FETCH_BLOCKED,
    ProductFetchStatus.CONTENT_TOO_LARGE: DiscoveryErrorKind.CONTENT_TOO_LARGE,
    ProductFetchStatus.UNSUPPORTED_CONTENT: DiscoveryErrorKind.PARSE_ERROR,
    ProductFetchStatus.PARSE_ERROR: DiscoveryErrorKind.PARSE_ERROR,
    ProductFetchStatus.TIMEOUT: DiscoveryErrorKind.TIMEOUT,
    ProductFetchStatus.CONNECTION_ERROR: DiscoveryErrorKind.CONNECTION_ERROR,
    ProductFetchStatus.HTTP_ERROR: DiscoveryErrorKind.PROVIDER_ERROR,
}


def fetch_product_stage(
    run: ProductPriorArtRun,
    fetcher: SafeWebFetcher | None,
    *,
    registry: HostRegistry = DEFAULT_HOST_REGISTRY,
) -> ProductPriorArtRun:
    """Search observations -> fetched artifacts. Unfetched URLs stay observations.

    One artifact per canonical URL, whatever number of observations pointed
    at it. URLs beyond ``max_detail_lookups`` are recorded as truncated.
    Without a fetcher nothing is fetched and every observation stays
    observation-only.
    """
    if "FETCH" in run.stage_markers:
        return run
    if not run.observations or fetcher is None:
        truncated = len({o.canonical_url for o in run.observations}) if fetcher is None else 0
        return _successor(run, "FETCH", budget=_budget(run, detail_lookups_truncated=truncated))
    by_url: dict[str, list[ProductSearchObservation]] = {}
    for observation in sorted(run.observations, key=lambda o: (o.retrieval_rank, str(o.query_id))):
        by_url.setdefault(observation.canonical_url, []).append(observation)
    artifacts: list[ProductSourceArtifact] = []
    performed = 0
    truncated = 0
    content_truncated = 0
    for url, observations in by_url.items():
        if performed >= run.budget.max_detail_lookups:
            truncated += 1
            continue
        performed += 1
        outcome = fetcher.fetch(observations[0].url)
        artifact_id = stable_id(run.research_run_id, "product-artifact", url)
        provider_date = next((o.provider_date for o in observations if o.provider_date), None)
        retrieved = outcome.retrieved_at or workflow_now()
        final = outcome.final_url or url
        host = host_of(final)
        common = dict(
            artifact_id=artifact_id,
            research_run_id=run.research_run_id,
            observation_ids=[o.observation_id for o in observations],
            original_url=observations[0].url,
            redirect_chain=outcome.redirect_chain,
            host=host,
            retrieved_at=retrieved,
        )
        if outcome.status is not ProductFetchStatus.FETCHED:
            artifacts.append(
                ProductSourceArtifact(
                    **common,
                    final_url=None,
                    fetch_status=outcome.status,
                    error_kind=outcome.error_kind or _ERROR_FOR_STATUS[outcome.status],
                    content_type=outcome.content_type,
                    dates=ProductDateFacts(search_provider_date=provider_date, retrieved_at=retrieved),
                    detail=outcome.detail,
                )
            )
            continue
        page = extract_page(outcome.text, outcome.content_type or "")
        if not page.parse_ok:
            artifacts.append(
                ProductSourceArtifact(
                    **common,
                    final_url=None,
                    fetch_status=ProductFetchStatus.PARSE_ERROR,
                    error_kind=DiscoveryErrorKind.PARSE_ERROR,
                    content_type=outcome.content_type,
                    dates=ProductDateFacts(search_provider_date=provider_date, retrieved_at=retrieved),
                    detail="page could not be parsed",
                )
            )
            continue
        role = assign_role(host, urlsplit(final).path, registry)
        first_party = role.role in (
            ProductSourceRole.FIRST_PARTY_PRODUCT_PAGE,
            ProductSourceRole.FIRST_PARTY_DOCUMENTATION,
            ProductSourceRole.FIRST_PARTY_PRESS_RELEASE,
        )
        marketplace = role.role is ProductSourceRole.MARKETPLACE_LISTING
        content_truncated += int(page.text_truncated)
        artifacts.append(
            ProductSourceArtifact(
                **common,
                final_url=final,
                source_role=role.role,
                source_role_basis=role.basis,
                vendor_registry_entry=role.vendor_entry,
                fetch_status=ProductFetchStatus.FETCHED,
                content_type=outcome.content_type,
                content_hash=outcome.content_hash,
                byte_length=outcome.byte_length,
                text_snapshot=page.text,
                text_truncated=page.text_truncated,
                title=page.title,
                headings=page.headings,
                stated_product_names=page.product_names,
                stated_vendor_names=page.vendor_names,
                identifiers=page.identifiers,
                dates=ProductDateFacts(
                    page_published_date=page.page_published_date,
                    vendor_launch_date=page.release_date if first_party else None,
                    vendor_availability_date=page.availability_date if first_party else None,
                    marketplace_listing_date=page.release_date if marketplace else None,
                    search_provider_date=provider_date,
                    retrieved_at=retrieved,
                ),
                limitations=["CURRENT_PAGE_STATE_ONLY"],
            )
        )
    return _successor(
        run,
        "FETCH",
        artifacts=artifacts,
        budget=_budget(
            run,
            detail_lookups_performed=performed,
            detail_lookups_truncated=truncated,
            content_truncated=content_truncated,
        ),
    )


def identity_product_stage(run: ProductPriorArtRun) -> ProductPriorArtRun:
    if "IDENTITY" in run.stage_markers:
        return run
    return _successor(run, "IDENTITY", entities=resolve_entities(run.artifacts, run.research_run_id))


def candidate_product_stage(run: ProductPriorArtRun) -> ProductPriorArtRun:
    if "CANDIDATES" in run.stage_markers:
        return run
    return _successor(
        run,
        "CANDIDATES",
        candidates=build_product_candidates(
            run.entities, run.artifacts, run.observations, run.planned_queries,
            run.search_cutoff, run.research_run_id,
        ),
    )


def finalize_product_stage(run: ProductPriorArtRun) -> ProductPriorArtRun:
    """Close the run; coverage re-derived so no earlier stage can overstate it."""
    if run.is_terminal:
        return run
    coverage = run.coverage_status
    if coverage is DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS and run.budget.truncated:
        coverage = DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return _successor(run, "FINALIZE", coverage_status=coverage, completed_at=workflow_now())


def run_product_pipeline(
    research_run_id: UUID,
    claims: list[PlannableClaim],
    provider: WebSearchProvider | None,
    fetcher: SafeWebFetcher | None,
    *,
    settings: ProductResearchSettings | None = None,
    cutoff: DiscoveryCutoff = NO_DISCOVERY_CUTOFF,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    registry: HostRegistry = DEFAULT_HOST_REGISTRY,
    resume_from: ProductPriorArtRun | None = None,
) -> ProductPriorArtRun:
    run = resume_from or open_product_run(research_run_id, settings=settings or ProductResearchSettings(), cutoff=cutoff)
    run = plan_product_stage(run, claims, privacy=privacy)
    run = search_product_stage(run, provider, privacy=privacy)
    run = fetch_product_stage(run, fetcher, registry=registry)
    run = identity_product_stage(run)
    run = candidate_product_stage(run)
    return finalize_product_stage(run)


__all__ = [
    "PRODUCT_PIPELINE_VERSION",
    "candidate_product_stage",
    "fetch_product_stage",
    "finalize_product_stage",
    "identity_product_stage",
    "open_product_run",
    "plan_product_stage",
    "product_budget",
    "run_product_pipeline",
    "search_product_stage",
]
