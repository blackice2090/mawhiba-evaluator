"""A populated upstream world for Phase 2G, built through the real graphs.

Section 31 requires immutability to be proven on *populated* fixtures: an empty
evidence list, an empty alignment run and an empty score list cannot show that
Phase 2G leaves them alone. So every Phase 2G eval case and the immutability
tests start from a research run that already carries real Phase 2B sources,
Phase 2C evidence, Phase 2D alignments, a Phase 2E sufficiency run and a
Phase 2F scoring run -- produced by driving the real Phase 2E and Phase 2F
graphs over a synthetic Phase 2B-2D world -- plus a canonical ``ScoreRecord``,
a populated ``TrustGateResult`` and a set evaluation status on the project.

Then the Phase 2G graph runs over that state, and the before/after snapshots
are compared field by field.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.evals.claim_sufficiency.dataset import (
    SufficiencyGoldCase,
    build_academic_result,
    build_alignment_run,
    build_claims,
    build_extraction_run,
    gold_run_id,
)
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2e_graph import build_phase2e_claim_sufficiency_graph
from src.graph.phase2f_graph import build_phase2f_claim_scoring_graph
from src.graph.phase2g_graph import build_phase2g_patent_graph
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY, RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.graph.patent_nodes import PATENT_CUTOFF_KEY, PATENT_PROVIDER_KEY
from src.research.coverage import initial_branch_coverage
from src.research.planner import PLANNER_VERSION
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.settings import ResearchSettings
from src.schemas.common import EvaluationStatus
from src.schemas.patent import NO_SEARCH_CUTOFF, PatentSearchCutoff
from src.schemas.research import ResearchRun, ResearchRunStatus, ResearchRunVersions
from src.schemas.score import RubricKind, ScoreAxis, ScoreAxisName, ScoreRecord
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult

UPSTREAM_EXCERPT = "Measured accuracy reached 94%."
"""The one Phase 2C excerpt every upstream world carries. Its content is
irrelevant to Phase 2G; its presence is what the immutability checks need."""


def upstream_case(case_id: str, claims: list[dict[str, str]]) -> SufficiencyGoldCase:
    """A Phase 2B-2D world with one supporting alignment per claim.

    The upstream Gold model requires a ``CS-`` identifier, so the Phase 2G case
    number is carried into one (``PG-012`` -> ``CS-90012``) rather than
    loosening that dataset's contract.
    """
    digits = "".join(ch for ch in case_id if ch.isdigit()) or "0"
    upstream_id = f"CS-9{int(digits):04d}"
    sources = [
        {
            "key": f"s{index}",
            "doi": f"10.5555/patent-{upstream_id.casefold()}-{index}",
            "is_retracted": False,
            "providers": ["CONSENSUS"],
            "source_type": "JOURNAL_ARTICLE",
        }
        for index, _ in enumerate(claims, start=1)
    ]
    evidence = [
        {"key": f"e{index}", "source": f"s{index}", "excerpt": f"{UPSTREAM_EXCERPT} ({index})"}
        for index, _ in enumerate(claims, start=1)
    ]
    alignments = [
        {
            "claim_id": claim["claim_id"],
            "evidence": f"e{index}",
            "relation": "SUPPORTS",
            "components": [{"text": claim["claim"], "judgment": "SUPPORTS"}],
        }
        for index, claim in enumerate(claims, start=1)
    ]
    return SufficiencyGoldCase.model_validate(
        {
            "case_id": upstream_id,
            "language": "en",
            "categories": ["phase2g-upstream"],
            "claims": claims,
            "sources": sources,
            "evidence": evidence,
            "alignments": alignments,
            "alignment_status": "COMPLETED",
            "expected": {},
        }
    )


def populated_project(case: SufficiencyGoldCase) -> ProjectState:
    """Claims, a canonical score record, a trust verdict and a status."""
    project = ProjectState()
    project.claims = build_claims(case)
    project.trust_gate = TrustGateResult(
        search_coverage=0.8,
        source_quality=0.75,
        claim_traceability=0.9,
        contradictions_resolved=True,
        novelty_search_complete=False,
        methodology_review_complete=True,
        red_team_complete=False,
        closest_prior_art_identified=False,
        sources_verified=True,
        official_requirements_checked=True,
        final_verifier_passed=False,
        score_status=EvaluationStatus.PROVISIONAL,
        finalization_allowed=False,
        blockers=[
            TrustBlocker(code=BlockerCode.RED_TEAM_INCOMPLETE, detail="Red team not run.")
        ],
    )
    project.evaluation_status = EvaluationStatus.PROVISIONAL
    project.scores = [
        ScoreRecord(
            score_id="SC-001",
            rubric_kind=RubricKind.ADVISORY,
            rubric_version="ADVISORY-V1",
            status=EvaluationStatus.PROVISIONAL,
            axes=[
                ScoreAxis(
                    axis=ScoreAxisName.LITERATURE.value,
                    score=7.0,
                    max_score=10.0,
                    status=EvaluationStatus.PROVISIONAL,
                    rationale="Placed by an earlier reviewed phase.",
                )
            ],
        )
    ]
    return project


def _open_run(case: SufficiencyGoldCase, project: ProjectState) -> ResearchRun:
    run = ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="phase2g-world",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(
        academic_research=build_academic_result(case),
        evidence_extraction=build_extraction_run(case),
        claim_evidence_alignment=build_alignment_run(case),
    )


def _invoke(app: Any, state: EvaluationGraphState, config: dict) -> EvaluationGraphState:
    return coerce_graph_state(app.invoke(state, config))


def _fresh_state(project: ProjectState, run: ResearchRun, config: dict) -> EvaluationGraphState:
    return EvaluationGraphState(
        run_id=uuid4(),
        thread_id=config["configurable"]["thread_id"],
        project=project,
        research_runs={str(run.research_run_id): run},
        active_research_run_id=run.research_run_id,
    )


def _config(**configurable: Any) -> dict:
    config = thread_config(new_thread_id(uuid4()))
    config["configurable"][RESEARCH_SETTINGS_KEY] = configurable.pop(
        "settings", ResearchSettings()
    )
    config["configurable"].update(configurable)
    return config


def build_upstream_state(case_id: str, claims: list[dict[str, str]]) -> EvaluationGraphState:
    """Run the real Phase 2E then Phase 2F graphs over a synthetic world."""
    case = upstream_case(case_id, claims)
    project = populated_project(case)
    run = _open_run(case, project)
    config = _config()
    after_2e = _invoke(
        build_phase2e_claim_sufficiency_graph(build_checkpointer()),
        _fresh_state(project, run, config),
        config,
    )
    config = _config()
    return _invoke(
        build_phase2f_claim_scoring_graph(build_checkpointer()),
        _fresh_state(after_2e.project, after_2e.active_research_run, config),
        config,
    )


def run_phase2g(
    state: EvaluationGraphState,
    provider: Any,
    *,
    cutoff: PatentSearchCutoff = NO_SEARCH_CUTOFF,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    settings: ResearchSettings | None = None,
    model_provider: Any = None,
    llm_settings: Any = None,
    interrupt_before: str | None = None,
) -> EvaluationGraphState:
    """Run the real Phase 2G graph over an upstream state.

    ``interrupt_before`` stops the graph at a node and resumes it from the
    checkpoint, which is how checkpoint/resume idempotency is exercised on the
    real graph rather than on the stage functions alone.
    """
    configurable: dict[str, Any] = {
        "settings": settings or ResearchSettings(),
        PATENT_CUTOFF_KEY: cutoff,
        RESEARCH_PRIVACY_KEY: privacy,
    }
    if provider is not None:
        configurable[PATENT_PROVIDER_KEY] = provider
    if model_provider is not None:
        from src.graph.patent_nodes import LLM_SETTINGS_KEY, PATENT_MODEL_PROVIDER_KEY

        configurable[PATENT_MODEL_PROVIDER_KEY] = model_provider
        configurable[LLM_SETTINGS_KEY] = llm_settings
    config = _config(**configurable)
    checkpointer = build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config)
    if interrupt_before is not None:
        build_phase2g_patent_graph(checkpointer).invoke(
            initial, {**config, "interrupt_before": [interrupt_before]}
        )
        return coerce_graph_state(
            build_phase2g_patent_graph(checkpointer).invoke(None, config)
        )
    return _invoke(build_phase2g_patent_graph(checkpointer), initial, config)


__all__ = [
    "UPSTREAM_EXCERPT",
    "build_upstream_state",
    "populated_project",
    "run_phase2g",
    "upstream_case",
]
