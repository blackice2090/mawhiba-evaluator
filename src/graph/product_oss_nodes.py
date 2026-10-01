"""Phase 2H product and open-source prior-art research nodes.

Each node is a thin wrapper over one stage in ``src.research.product.pipeline``
or ``src.research.open_source.pipeline``: it reads the subrun on the active
``ResearchRun``, applies exactly one stage, and emits a successor research run
with only ``product_prior_art`` or ``open_source_prior_art`` replaced. Nothing
is held between nodes, so a node replayed after an interrupt starts from the
persisted run and reaches the same result (ADR-002).

No node writes the ``project`` channel. Claims, claim status, confidence,
evidence references, ``ProjectState.scores``, ``trust_gate`` and
``evaluation_status`` are untouched by construction, and so are the Phase 2C-2G
artifacts on the same research run (ADR-019).

Runtime inputs come from ``config["configurable"]`` and are never checkpointed:

* ``product_search_provider`` -- a ``WebSearchProvider``; absent = no API key,
  the product track records ``BLOCKED_AUTH`` and sends nothing.
* ``product_fetcher`` -- a ``SafeWebFetcher``; absent = nothing is fetched and
  every hit stays an observation.
* ``product_host_registry`` -- a reviewed ``HostRegistry`` (vendor domains).
* ``github_provider`` -- a ``GitHubProvider``; absent = ``BLOCKED_AUTH``.
* ``product_oss_cutoff`` -- an explicit ``DiscoveryCutoff``; absent = ``NO_CUTOFF``.
* ``discovery_sleeper`` -- optional backoff sleeper (tests inject ``NoSleep``).
* ``structured_model_provider`` / ``llm_settings`` -- optional, for untrusted
  English expansion of Arabic claims.
* ``research_privacy`` and ``research_settings`` -- the shared research keys.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import LLMSettings
from src.graph.contracts import NodeResult, NodeStatus, WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY
from src.graph.nodes import _completion
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.registry import NodeId
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY, RESEARCH_SETTINGS_KEY
from src.graph.workflow_state import EvaluationGraphState
from src.research.open_source import pipeline as oss
from src.research.patent.pipeline import plannable_claims
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.product import pipeline as product
from src.research.product.roles import DEFAULT_HOST_REGISTRY, HostRegistry
from src.research.settings import DEFAULT_RESEARCH_SETTINGS, ResearchSettings
from src.schemas.discovery import NO_DISCOVERY_CUTOFF, DiscoveryCutoff
from src.schemas.research import ResearchRun
from src.workflow.clock import workflow_now

PRODUCT_SEARCH_PROVIDER_KEY = "product_search_provider"
PRODUCT_FETCHER_KEY = "product_fetcher"
PRODUCT_HOST_REGISTRY_KEY = "product_host_registry"
GITHUB_PROVIDER_KEY = "github_provider"
PRODUCT_OSS_CUTOFF_KEY = "product_oss_cutoff"
DISCOVERY_SLEEPER_KEY = "discovery_sleeper"
DISCOVERY_MODEL_PROVIDER_KEY = INTAKE_PROVIDER_KEY


def _cfg(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _settings(config: RunnableConfig | None) -> ResearchSettings:
    return _cfg(config).get(RESEARCH_SETTINGS_KEY) or DEFAULT_RESEARCH_SETTINGS


def _privacy(config: RunnableConfig | None) -> ResearchPrivacyContext:
    return _cfg(config).get(RESEARCH_PRIVACY_KEY) or EMPTY_PRIVACY_CONTEXT


def _cutoff(config: RunnableConfig | None) -> DiscoveryCutoff:
    cutoff = _cfg(config).get(PRODUCT_OSS_CUTOFF_KEY)
    return cutoff if isinstance(cutoff, DiscoveryCutoff) else NO_DISCOVERY_CUTOFF


def _registry(config: RunnableConfig | None) -> HostRegistry:
    registry = _cfg(config).get(PRODUCT_HOST_REGISTRY_KEY)
    return registry if isinstance(registry, HostRegistry) else DEFAULT_HOST_REGISTRY


def _done(
    state: EvaluationGraphState,
    node: NodeId,
    started_at: Any,
    summary: str,
    *,
    run: ResearchRun | None = None,
    status: NodeStatus = NodeStatus.SUCCEEDED,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = NodeResult(node=node.value, status=status, summary=summary, warnings=warnings or [])
    update: dict[str, Any] = {"status": WorkflowStatus.RUNNING}
    if run is not None:
        update["research_runs"] = {str(run.research_run_id): run}
    return {**update, **_completion(state, node, result, started_at, status=status)}


def _with(run: ResearchRun, **subruns: Any) -> ResearchRun:
    """A successor research run with only the named Phase 2H subrun(s) replaced."""
    return ResearchRun.model_validate({**dict(run), **subruns})


def _stage(node: NodeId, field: str, stage: Any, summary: str):
    def _node(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
        started_at = workflow_now()
        run = state.active_research_run
        subrun = getattr(run, field, None) if run is not None else None
        if run is None or subrun is None or subrun.is_terminal:
            return _done(state, node, started_at, "No open subrun; nothing to do.", status=NodeStatus.SKIPPED)
        successor = stage(subrun, config)
        return _done(state, node, started_at, summary.format(run=successor), run=_with(run, **{field: successor}))

    _node.__name__ = node.value.casefold()
    return _node


def load_product_oss_research_run(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Open both subruns on the active research run, or decline to."""
    node = NodeId.LOAD_PRODUCT_OSS_RESEARCH_RUN
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.is_terminal:
        reason = "no active research run" if run is None else "the research run is terminal"
        return _done(state, node, started_at, f"Product/OSS research skipped: {reason}.",
                     status=NodeStatus.SKIPPED, warnings=[reason])
    if run.product_prior_art is not None and run.open_source_prior_art is not None:
        # Idempotency (section 35): existing subruns are resumed, never replaced,
        # and a finished one is never reopened.
        return _done(state, node, started_at, "Product/OSS subruns already exist; resumed.",
                     status=NodeStatus.SKIPPED)
    settings = _settings(config)
    cutoff = _cutoff(config)
    github = _cfg(config).get(GITHUB_PROVIDER_KEY)
    changes: dict[str, Any] = {}
    if run.product_prior_art is None:
        changes["product_prior_art"] = product.open_product_run(
            run.research_run_id, settings=settings.product, cutoff=cutoff
        )
    if run.open_source_prior_art is None:
        changes["open_source_prior_art"] = oss.open_oss_run(
            run.research_run_id,
            settings=settings.open_source,
            cutoff=cutoff,
            authenticated=bool(getattr(github, "authenticated", False)),
        )
    return _done(
        state, node, started_at,
        f"Product and open-source subruns opened (cutoff {'supplied' if cutoff.supplied else 'not supplied'}).",
        run=_with(run, **changes),
    )


def plan_product_oss_queries(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    """Plan both tracks from canonical claim text and the Phase 2E inventory."""
    node = NodeId.PLAN_PRODUCT_OSS_QUERIES
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.product_prior_art is None or run.open_source_prior_art is None:
        return _done(state, node, started_at, "No open subruns; nothing to do.", status=NodeStatus.SKIPPED)
    components: dict[str, list[str]] = {}
    if run.claim_sufficiency is not None:
        for assessment in run.claim_sufficiency.assessments:
            components[assessment.claim_id] = [c.text for c in assessment.component_inventory.components]
    claims = plannable_claims(list(state.project.claims), components)
    model_provider = _cfg(config).get(DISCOVERY_MODEL_PROVIDER_KEY)
    llm = _cfg(config).get(LLM_SETTINGS_KEY)
    model = llm.research_planning_model if (model_provider is not None and isinstance(llm, LLMSettings)) else ""
    kwargs = dict(privacy=_privacy(config), model_provider=model_provider if model else None, model=model)
    changes: dict[str, Any] = {}
    if not run.product_prior_art.is_terminal:
        changes["product_prior_art"] = product.plan_product_stage(run.product_prior_art, claims, **kwargs)
    if not run.open_source_prior_art.is_terminal:
        changes["open_source_prior_art"] = oss.plan_oss_stage(run.open_source_prior_art, claims, **kwargs)
    successor = _with(run, **changes)
    return _done(
        state, node, started_at,
        f"{len(successor.product_prior_art.planned_queries)} product and "
        f"{len(successor.open_source_prior_art.planned_queries)} open-source queries planned.",
        run=successor,
    )


def _sleeper(config: RunnableConfig) -> Any:
    return _cfg(config).get(DISCOVERY_SLEEPER_KEY)


execute_product_search = _stage(
    NodeId.EXECUTE_PRODUCT_SEARCH, "product_prior_art",
    lambda r, c: product.search_product_stage(
        r, _cfg(c).get(PRODUCT_SEARCH_PROVIDER_KEY), privacy=_privacy(c), sleeper=_sleeper(c)
    ),
    "Product search: coverage {run.coverage_status.value}.",
)
fetch_product_artifacts = _stage(
    NodeId.FETCH_PRODUCT_ARTIFACTS, "product_prior_art",
    lambda r, c: product.fetch_product_stage(r, _cfg(c).get(PRODUCT_FETCHER_KEY), registry=_registry(c)),
    "{run.budget.detail_lookups_performed} product pages fetched through the safe fetcher.",
)
resolve_product_identity = _stage(
    NodeId.RESOLVE_PRODUCT_IDENTITY, "product_prior_art",
    lambda r, c: product.identity_product_stage(r),
    "{run.distinct_product_count_upper_bound} product entities (strong identity or identical content only).",
)
build_product_candidates = _stage(
    NodeId.BUILD_PRODUCT_CANDIDATES, "product_prior_art",
    lambda r, c: product.candidate_product_stage(r),
    "{run.distinct_product_count_upper_bound} product candidates built.",
)
execute_open_source_search = _stage(
    NodeId.EXECUTE_OPEN_SOURCE_SEARCH, "open_source_prior_art",
    lambda r, c: oss.search_oss_stage(r, _cfg(c).get(GITHUB_PROVIDER_KEY), privacy=_privacy(c), sleeper=_sleeper(c)),
    "Open-source search: coverage {run.coverage_status.value}.",
)
verify_repositories = _stage(
    NodeId.VERIFY_REPOSITORIES, "open_source_prior_art",
    lambda r, c: oss.verify_oss_stage(r, _cfg(c).get(GITHUB_PROVIDER_KEY), settings=_settings(c).open_source, sleeper=_sleeper(c)),
    "{run.budget.detail_lookups_performed} repositories verified by stable id.",
)
capture_repository_snapshots = _stage(
    NodeId.CAPTURE_REPOSITORY_SNAPSHOTS, "open_source_prior_art",
    lambda r, c: oss.snapshot_oss_stage(r, _cfg(c).get(GITHUB_PROVIDER_KEY), settings=_settings(c).open_source, sleeper=_sleeper(c)),
    "Repository snapshots captured.",
)
resolve_repository_networks = _stage(
    NodeId.RESOLVE_REPOSITORY_NETWORKS, "open_source_prior_art",
    lambda r, c: oss.network_oss_stage(r, _cfg(c).get(GITHUB_PROVIDER_KEY), sleeper=_sleeper(c)),
    "{run.independent_root_count} independent root lineages.",
)
build_open_source_candidates = _stage(
    NodeId.BUILD_OPEN_SOURCE_CANDIDATES, "open_source_prior_art",
    lambda r, c: oss.candidate_oss_stage(r),
    "Open-source candidates built.",
)


def finalize_product_oss_research(state: EvaluationGraphState, config: RunnableConfig) -> dict[str, Any]:
    node = NodeId.FINALIZE_PRODUCT_OSS_RESEARCH
    started_at = workflow_now()
    run = state.active_research_run
    if run is None or run.product_prior_art is None or run.open_source_prior_art is None:
        return _done(state, node, started_at, "No open subruns; nothing to do.", status=NodeStatus.SKIPPED)
    successor = _with(
        run,
        product_prior_art=product.finalize_product_stage(run.product_prior_art),
        open_source_prior_art=oss.finalize_oss_stage(run.open_source_prior_art),
    )
    return _done(
        state, node, started_at,
        "Product and open-source discovery finished. Bounded search; candidates only -- "
        "not a novelty, copying or legal opinion.",
        run=successor,
    )


__all__ = [
    "DISCOVERY_MODEL_PROVIDER_KEY",
    "DISCOVERY_SLEEPER_KEY",
    "GITHUB_PROVIDER_KEY",
    "PRODUCT_FETCHER_KEY",
    "PRODUCT_HOST_REGISTRY_KEY",
    "PRODUCT_OSS_CUTOFF_KEY",
    "PRODUCT_SEARCH_PROVIDER_KEY",
    "build_open_source_candidates",
    "build_product_candidates",
    "capture_repository_snapshots",
    "execute_open_source_search",
    "execute_product_search",
    "fetch_product_artifacts",
    "finalize_product_oss_research",
    "load_product_oss_research_run",
    "plan_product_oss_queries",
    "resolve_product_identity",
    "resolve_repository_networks",
    "verify_repositories",
]
