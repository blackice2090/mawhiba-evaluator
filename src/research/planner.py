"""Research query planning through the existing ``StructuredModelProvider``.

Reads a PII-minimized projection of canonical state, asks the model for a
candidate plan, and returns the deterministic verdict. It never writes to
``ProjectState``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from src.config.settings import LLMSettings
from src.graph.state import ProjectState
from src.llm.contracts import ModelCallResult, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import (
    PROMPT_VERSIONS,
    RESEARCH_INPUT_MARKER,
    RESEARCH_QUERY_PLANNER_PROMPT_V1,
)
from src.llm.provider import StructuredModelProvider
from src.research.inputs import build_research_input
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.query_verification import PLANNABLE_BRANCHES, verify_query_plan
from src.schemas.research import (
    CandidateQueryPlan,
    QueryPlanLimits,
    QueryPurpose,
    ResearchInputSnapshot,
    VerifiedQueryPlan,
)

PLANNER_VERSION = f"RESEARCH_QUERY_PLANNER_PROMPT_{PROMPT_VERSIONS['RESEARCH_QUERY_PLANNER_PROMPT']}"


def build_planning_input(snapshot: ResearchInputSnapshot, limits: QueryPlanLimits) -> str:
    """Deterministic payload for the planner. Contains only the redacted snapshot."""
    payload = {
        "allowed_branches": sorted(b.value for b in PLANNABLE_BRANCHES),
        "allowed_purposes": [p.value for p in QueryPurpose],
        "limits": limits.model_dump(),
        "fields": [{"field_path": f.field_path, "values": f.values} for f in snapshot.fields],
        "student_claims": [
            {
                "field_path": f"claims.{c.claim_id}",
                "claim_type": c.claim_type,
                "text": c.text,
                "note": "student assertion, not a verified fact",
            }
            for c in snapshot.claims
        ],
    }
    return f"{RESEARCH_INPUT_MARKER}\n{json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)}"


def run_query_planning(
    snapshot: ResearchInputSnapshot,
    provider: StructuredModelProvider,
    settings: LLMSettings,
    limits: QueryPlanLimits,
) -> ModelCallResult[CandidateQueryPlan]:
    return call_structured_model_with_retries(
        provider,
        task=ModelTask.RESEARCH_QUERY_PLANNING,
        system_prompt=RESEARCH_QUERY_PLANNER_PROMPT_V1,
        user_input=build_planning_input(snapshot, limits),
        response_model=CandidateQueryPlan,
        model=settings.research_planning_model,
        max_retries=settings.max_retries,
    )


@dataclass
class PlanningOutcome:
    """Everything one planning pass produced. ``plan`` is None when no call succeeded."""

    snapshot: ResearchInputSnapshot
    planner_input: str
    call: ModelCallResult[CandidateQueryPlan] | None
    plan: VerifiedQueryPlan | None


def plan_research_queries(
    project: ProjectState,
    provider: StructuredModelProvider,
    *,
    research_run_id: UUID,
    llm_settings: LLMSettings,
    limits: QueryPlanLimits,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> PlanningOutcome:
    """Pure query planning: read state, call the model, verify. Never mutates state.

    With no trusted research input the model is not called at all -- a plan built
    from nothing could only be built from assumptions.
    """
    snapshot = build_research_input(project, privacy)
    planner_input = build_planning_input(snapshot, limits)
    if snapshot.is_empty:
        return PlanningOutcome(snapshot, planner_input, None, None)

    call = run_query_planning(snapshot, provider, llm_settings, limits)
    if not call.succeeded:
        return PlanningOutcome(snapshot, planner_input, call, None)

    plan = verify_query_plan(
        project,
        call.parsed,
        research_run_id=research_run_id,
        planner_version=PLANNER_VERSION,
        limits=limits,
        privacy=privacy,
    )
    return PlanningOutcome(snapshot, planner_input, call, plan)
