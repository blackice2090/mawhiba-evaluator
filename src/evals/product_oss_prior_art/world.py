"""A populated upstream world for Phase 2H, built through the real graphs.

Section 37 requires immutability on *populated* fixtures. Every Phase 2H case
therefore starts from a research run carrying real Phase 2B sources, Phase 2C
evidence, Phase 2D alignments, a Phase 2E sufficiency run, a Phase 2F scoring
run (all via the Phase 2G world builder) AND a finished Phase 2G patent run
produced by the real Phase 2G graph against a scripted EPO OPS office, plus a
canonical ``ScoreRecord``, a ``TrustGateResult`` and an evaluation status.

Then the real Phase 2H graph runs, and before/after snapshots are compared.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.evals.patent_prior_art.world import (
    _config,
    _fresh_state,
    _invoke,
    build_upstream_state,
    run_phase2g,
)
from src.graph.persistence import build_checkpointer
from src.graph.phase2h_graph import build_phase2h_product_oss_graph
from src.graph.product_oss_nodes import (
    DISCOVERY_SLEEPER_KEY,
    GITHUB_PROVIDER_KEY,
    PRODUCT_FETCHER_KEY,
    PRODUCT_HOST_REGISTRY_KEY,
    PRODUCT_OSS_CUTOFF_KEY,
    PRODUCT_SEARCH_PROVIDER_KEY,
)
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY
from src.graph.workflow_state import EvaluationGraphState, coerce_graph_state
from src.research.academic.http import NoSleep
from src.research.patent.fakes import FakeEpoOpsProvider, FakePatentRecord, ScriptedPatentSearch
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.product.roles import DEFAULT_HOST_REGISTRY, HostRegistry
from src.research.settings import ResearchSettings
from src.schemas.discovery import NO_DISCOVERY_CUTOFF, DiscoveryCutoff

UPSTREAM_PATENT = FakePatentRecord(
    reference="EP.1000001.A1",
    title="Upstream patent record",
    publication_date="2015-06-01",
    abstract="An upstream abstract present only to populate the Phase 2G run.",
)


def build_phase2h_upstream(case_id: str, claims: list[dict[str, str]]) -> EvaluationGraphState:
    """Phase 2E + 2F (real graphs) and then a real, finished Phase 2G run."""
    state = build_upstream_state(case_id, claims)
    office = FakeEpoOpsProvider(default_search=ScriptedPatentSearch(records=(UPSTREAM_PATENT,)))
    return run_phase2g(state, office)


def run_phase2h(
    state: EvaluationGraphState,
    *,
    web: Any = None,
    fetcher: Any = None,
    github: Any = None,
    cutoff: DiscoveryCutoff = NO_DISCOVERY_CUTOFF,
    registry: HostRegistry = DEFAULT_HOST_REGISTRY,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    settings: ResearchSettings | None = None,
    interrupt_before: str | None = None,
) -> EvaluationGraphState:
    """Run the real Phase 2H graph over an upstream state.

    ``interrupt_before`` stops the graph at a node and resumes it from the
    checkpoint, exercising resume idempotency on the real graph.
    """
    configurable: dict[str, Any] = {
        "settings": settings or ResearchSettings(),
        PRODUCT_OSS_CUTOFF_KEY: cutoff,
        PRODUCT_HOST_REGISTRY_KEY: registry,
        RESEARCH_PRIVACY_KEY: privacy,
        DISCOVERY_SLEEPER_KEY: NoSleep(),
    }
    for key, value in ((PRODUCT_SEARCH_PROVIDER_KEY, web), (PRODUCT_FETCHER_KEY, fetcher), (GITHUB_PROVIDER_KEY, github)):
        if value is not None:
            configurable[key] = value
    config = _config(**configurable)
    checkpointer = build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config)
    if interrupt_before is not None:
        build_phase2h_product_oss_graph(checkpointer).invoke(initial, {**config, "interrupt_before": [interrupt_before]})
        return coerce_graph_state(build_phase2h_product_oss_graph(checkpointer).invoke(None, config))
    return _invoke(build_phase2h_product_oss_graph(checkpointer), initial, config)


def rerun_phase2h(state: EvaluationGraphState, **kwargs: Any) -> EvaluationGraphState:
    """Invoke the graph again over a state that already carries Phase 2H subruns."""
    return run_phase2h(state, **kwargs)


__all__ = ["UPSTREAM_PATENT", "build_phase2h_upstream", "rerun_phase2h", "run_phase2h"]
