"""Phase 1A.1 hardening tests.

Three structural risks, three guarantees:

A. Workflow execution state has exactly one owner (EvaluationGraphState).
B. A human pause across an interrupt never appears as node compute latency.
C. A checkpoint-reachable type cannot silently go unregistered with the
   serializer.
"""

from __future__ import annotations

import pkgutil
from datetime import datetime, timedelta, timezone
from enum import Enum
from importlib import import_module
from inspect import isclass
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

import src
from src.graph.contracts import NodeAttempt, NodeExecutionRecord, NodeStatus
from src.graph.persistence import (
    CHECKPOINT_ROOTS,
    CHECKPOINTED_TYPES,
    audit_serde_registration,
    build_checkpointer,
    build_serializer,
    thread_config,
    type_keys,
    unregistered_type_keys,
)
from src.graph.phase1a_graph import build_phase1a_graph
from src.graph.registry import Phase1ANode
from src.graph.state import ProjectState
from src.graph.type_discovery import discover_types_from
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.schemas.common import Tracked
from src.workflow.clock import ManualClock, SystemClock, use_clock, workflow_now

COMPLETE_ANSWER = {
    "identity.project_name": "PiezoLeak",
    "problem.statement": "Small municipal water leaks go undetected for weeks.",
    "solution.description": "An in-pipe node classifying piezo vibration signatures.",
}

HUMAN_PAUSE_SECONDS = 900.0
"""Fifteen minutes of simulated human thinking time. Never a real sleep."""


@pytest.fixture
def app() -> CompiledStateGraph:
    return build_phase1a_graph(build_checkpointer())


@pytest.fixture
def run_id() -> UUID:
    return uuid4()


@pytest.fixture
def config(run_id: UUID) -> dict:
    return thread_config(new_thread_id(run_id))


def _initial_state(run_id: UUID, config: dict) -> EvaluationGraphState:
    return EvaluationGraphState(
        run_id=run_id, thread_id=config["configurable"]["thread_id"]
    )


# ===========================================================================
# Issue A -- workflow state ownership
# ===========================================================================

WORKFLOW_EXECUTION_FIELDS = (
    "completed_nodes",
    "pending_nodes",
    "current_node",
    "node_execution_attempts",
    "node_results",
    "interrupt_request",
    "workflow_status",
    "status",
    "errors",
    "run_id",
    "thread_id",
    "workflow",
)


@pytest.mark.parametrize("field", WORKFLOW_EXECUTION_FIELDS)
def test_project_state_exposes_no_workflow_execution_field(field: str) -> None:
    """ProjectState owns project/evaluation truth, never runtime truth (ADR-002)."""
    assert field not in ProjectState.model_fields
    assert not hasattr(ProjectState(), field)


UNAMBIGUOUS_WORKFLOW_FIELDS = frozenset(
    {
        "completed_nodes",
        "pending_nodes",
        "current_node",
        "node_execution_attempts",
        "node_results",
        "interrupt_request",
        "workflow_status",
        "blocked_reason",
        "failed_nodes",
        "thread_id",
        "run_id",
    }
)
"""Names that can only mean orchestration.

Deliberately excludes ``status`` and ``errors``: those are legitimate domain
vocabulary (``NoveltyAssessment.status``), and banning them by name would test
spelling rather than ownership.
"""


def test_project_state_has_no_nested_operational_workflow_model() -> None:
    """The removal must not be worked around by a nested operational block."""
    for name, info in ProjectState.model_fields.items():
        annotation = info.annotation
        if isclass(annotation) and issubclass(annotation, BaseModel):
            leaked = set(annotation.model_fields) & UNAMBIGUOUS_WORKFLOW_FIELDS
            assert not leaked, (
                f"ProjectState.{name} re-introduces workflow execution state: {leaked}"
            )


def test_workflow_block_no_longer_exists() -> None:
    import src.schemas.project as project_module

    assert not hasattr(project_module, "WorkflowBlock")


@pytest.mark.parametrize("field", WORKFLOW_EXECUTION_FIELDS[:8])
def test_graph_state_owns_the_workflow_execution_fields(field: str) -> None:
    """Every runtime concern has exactly one home, and this is it."""
    if field == "workflow_status":
        assert "status" in EvaluationGraphState.model_fields
        return
    if field == "workflow":
        return
    assert field in EvaluationGraphState.model_fields


def test_the_two_models_share_no_field_at_all() -> None:
    overlap = set(EvaluationGraphState.model_fields) & set(ProjectState.model_fields)
    assert overlap == set()


def test_project_state_still_owns_the_domain() -> None:
    """The correction removes runtime state only; domain ownership is unchanged."""
    for field in (
        "identity",
        "problem",
        "solution",
        "technical",
        "methodology",
        "experiments",
        "results",
        "claims",
        "sources",
        "evidence",
        "prior_art",
        "novelty",
        "gap",
        "risks",
        "scores",
        "missing_critical_information",
        "contradictions",
        "current_mode",
    ):
        assert field in ProjectState.model_fields


def test_domain_state_survives_creation_and_round_trip(project_b) -> None:
    restored = ProjectState.model_validate_json(project_b.model_dump_json())
    assert restored == project_b


def test_domain_state_survives_checkpoint_and_resume(
    app: CompiledStateGraph, run_id: UUID, config: dict, project_b
) -> None:
    state = EvaluationGraphState(
        run_id=run_id,
        thread_id=config["configurable"]["thread_id"],
        project=project_b,
    )
    app.invoke(state, config)
    restored = coerce_graph_state(app.get_state(config).values)

    assert restored.project == project_b
    assert ProjectState.model_validate(restored.project.model_dump()) == project_b


def test_all_phase1a_graph_paths_still_work(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """The happy path, the interrupt path and the resume path all survive."""
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    assert state.completed_nodes == [
        Phase1ANode.INITIALIZE_RUN.value,
        Phase1ANode.VALIDATE_PROJECT_STATE.value,
        Phase1ANode.CHECK_CRITICAL_INPUT.value,
        Phase1ANode.REQUEST_INPUT.value,
        Phase1ANode.APPLY_INPUT.value,
        Phase1ANode.MARK_READY.value,
    ]


# ===========================================================================
# Issue B -- attempt-level timing
# ===========================================================================

def test_manual_clock_is_deterministic_and_ordered() -> None:
    clock = ManualClock(tick=timedelta(milliseconds=5))
    first, second = clock.now(), clock.now()
    assert second > first
    assert (second - first) == timedelta(milliseconds=5)


def test_manual_clock_rejects_a_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ManualClock(start=datetime(2026, 1, 1))


def test_clock_injection_is_scoped() -> None:
    clock = ManualClock()
    with use_clock(clock):
        assert workflow_now() == clock.peek()
    assert isinstance(SystemClock().now(), datetime)


def test_attempt_duration_uses_only_its_own_timestamps() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempt = NodeAttempt(
        node="N",
        attempt=1,
        started_at=start,
        completed_at=start + timedelta(milliseconds=250),
        status=NodeStatus.SUCCEEDED,
    )
    assert attempt.duration_ms == 250.0


def test_incomplete_attempt_has_no_duration() -> None:
    assert NodeAttempt(node="N", attempt=1).duration_ms is None


def test_attempt_rejects_completion_before_start() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="cannot precede started_at"):
        NodeAttempt(
            node="N", attempt=1, started_at=start, completed_at=start - timedelta(seconds=1)
        )


def test_a_later_attempt_must_declare_itself_a_replay() -> None:
    with pytest.raises(ValidationError, match="must be marked replayed"):
        NodeAttempt(node="N", attempt=2, replayed=False)


def test_execution_record_exposes_no_latency_field() -> None:
    """Lifecycle timing must not be published under a name meaning latency."""
    assert "duration_ms" not in NodeExecutionRecord.model_fields
    assert not hasattr(NodeExecutionRecord, "duration_ms")
    assert hasattr(NodeExecutionRecord, "lifecycle_elapsed_ms")


def test_execution_record_uses_explicit_lifecycle_names() -> None:
    assert "first_started_at" in NodeExecutionRecord.model_fields
    assert "last_completed_at" in NodeExecutionRecord.model_fields
    assert "started_at" not in NodeExecutionRecord.model_fields
    assert "completed_at" not in NodeExecutionRecord.model_fields


def test_interrupt_pause_is_excluded_from_attempt_timing(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """The core timing guarantee, with a simulated 15-minute human pause."""
    clock = ManualClock(tick=timedelta(milliseconds=1))

    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        clock.advance(HUMAN_PAUSE_SECONDS)  # the human goes away and comes back
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    pause_ms = HUMAN_PAUSE_SECONDS * 1000.0
    for attempt in state.node_execution_attempts:
        assert attempt.duration_ms is not None
        assert attempt.duration_ms < pause_ms, (
            f"{attempt.node} attempt {attempt.attempt} absorbed the human pause"
        )


def test_replayed_node_attempts_have_distinct_identities_and_times(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """VALIDATE_PROJECT_STATE genuinely executes twice across the resume."""
    clock = ManualClock(tick=timedelta(milliseconds=1))
    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        clock.advance(HUMAN_PAUSE_SECONDS)
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    node = Phase1ANode.VALIDATE_PROJECT_STATE.value
    attempts = [a for a in state.node_execution_attempts if a.node == node]

    assert len(attempts) == 2
    assert attempts[0].attempt_id != attempts[1].attempt_id
    assert attempts[0].started_at != attempts[1].started_at
    assert attempts[1].started_at > attempts[0].started_at
    assert attempts[0].replayed is False
    assert attempts[1].replayed is True
    assert [a.attempt for a in attempts] == [1, 2]


def test_a_replayed_attempt_does_not_inherit_the_first_start_time(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """The exact regression Phase 1A.1 fixes."""
    clock = ManualClock(tick=timedelta(milliseconds=1))
    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        clock.advance(HUMAN_PAUSE_SECONDS)
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    node = Phase1ANode.VALIDATE_PROJECT_STATE.value
    first, second = [a for a in state.node_execution_attempts if a.node == node]

    assert second.started_at > first.completed_at
    assert second.duration_ms < HUMAN_PAUSE_SECONDS * 1000.0


def test_request_input_times_only_the_resumed_pass(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """The interrupted pass commits nothing; the recorded attempt is the resume.

    REQUEST_INPUT captures its attempt start before interrupt(), so the line
    re-executes on resume and the timestamp belongs to the resumed pass.
    """
    clock = ManualClock(tick=timedelta(milliseconds=1))
    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        pause_started = clock.peek()
        clock.advance(HUMAN_PAUSE_SECONDS)
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    attempts = [
        a for a in state.node_execution_attempts if a.node == Phase1ANode.REQUEST_INPUT.value
    ]
    assert len(attempts) == 1
    assert attempts[0].started_at > pause_started
    assert attempts[0].duration_ms < HUMAN_PAUSE_SECONDS * 1000.0


def test_lifecycle_elapsed_may_span_the_pause_and_is_named_accordingly(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """Lifecycle timing legitimately includes the pause -- hence its name."""
    clock = ManualClock(tick=timedelta(milliseconds=1))
    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        clock.advance(HUMAN_PAUSE_SECONDS)
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    record = state.record_for(Phase1ANode.VALIDATE_PROJECT_STATE.value)
    assert record.attempts == 2
    assert record.lifecycle_elapsed_ms > HUMAN_PAUSE_SECONDS * 1000.0


def test_completion_remains_deduplicated_under_the_new_timing(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    clock = ManualClock()
    with use_clock(clock):
        app.invoke(_initial_state(run_id, config), config)
        clock.advance(HUMAN_PAUSE_SECONDS)
        state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))

    assert len(state.completed_nodes) == len(set(state.completed_nodes))
    assert state.completed_nodes.count(Phase1ANode.VALIDATE_PROJECT_STATE.value) == 1


def test_all_attempt_ids_are_unique_across_a_run(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    app.invoke(_initial_state(run_id, config), config)
    state = coerce_graph_state(app.invoke(Command(resume=COMPLETE_ANSWER), config))
    ids = [a.attempt_id for a in state.node_execution_attempts]
    assert len(ids) == len(set(ids))


# ===========================================================================
# Issue C -- serializer registration completeness
# ===========================================================================

def _project_model_and_enum_types() -> set[type]:
    """Every Pydantic model and enum defined under the ``src`` package.

    Walks the package rather than a hand-maintained list. All modules under
    ``src`` are pure declarations, so importing them has no side effects.
    """
    found: set[type] = set()
    for info in pkgutil.walk_packages(src.__path__, prefix="src."):
        module = import_module(info.name)
        for obj in vars(module).values():
            if (
                isclass(obj)
                and issubclass(obj, (BaseModel, Enum))
                and obj.__module__ == info.name
            ):
                found.add(obj)
    return found


NON_CHECKPOINTED_TYPES: frozenset[str] = frozenset(
    {
        # Configuration and policy: constructed per process, never checkpointed.
        "ContractSettings",
        "Rubric",
        "RubricAxisDefinition",
        "ScoreAxisName",
        "ScoringInput",
        "TrustPolicy",
        # Phase 3A requirement catalog row: import-time policy (REQUIREMENT_CATALOG);
        # a run persists the resolved RequirementApplicability, never the row.
        "CatalogEntry",
        # Workflow-layer input contracts: validated and discarded at the
        # boundary; only their effect on ProjectState is persisted.
        "ProjectPatch",
        "PatchableField",
        # Node identifiers: persisted as plain strings, not as enum members.
        "NodeId",
        "Phase1ANode",
        "CheckpointerKind",
        # Base classes and protocols.
        "MawhibaModel",
        "Clock",
        "SystemClock",
        "ManualClock",
        # Phase 1B model-call layer: a ModelCallResult is consumed inside the
        # node that made the call and never stored on the graph state, so it
        # never crosses the checkpoint boundary.
        "ModelCallResult",
        "ModelCallStatus",
        "ModelTask",
        "ModelUsage",
        "ModelFacingModel",
        "LLMSettings",
        # Classifier DTOs: only the VERIFIED form reaches the state. The raw
        # candidate classification is deliberately not persisted -- unlike the
        # extraction candidate, it has no diagnostic value once verified.
        "ProjectClassification",
        "DomainAssignment",
        # A derived audit view over VerifiedExtraction.rejected_fields, which is
        # itself checkpointed. Storing the ledger too would duplicate persisted
        # data and let the two disagree.
        "RejectedExtraction",
        # Phase 1C evaluation layer. Evals run outside the graph entirely and
        # never touch a checkpoint; their models are offline measurement
        # artifacts, not workflow state.
        "GoldCase",
        "GoldDataset",
        "GoldExpectation",
        "ScriptedResponses",
        "IntakeMetrics",
        "MetricCounts",
        "SafetyCounts",
        "MetricComparison",
        "EvalBaseline",
        "RunProvenance",
        "GateResult",
        # Phase 2A research configuration: per-process policy, never checkpointed.
        "ResearchSettings",
        "OfficialRequirementsSettings",
        # Phase 2A provider-facing DTOs: a web retrieval result is consumed inside
        # OFFICIAL_REQUIREMENTS_RETRIEVAL and persisted as a SourceCandidate; the
        # raw official extraction is consumed inside EXTRACT_OFFICIAL_REQUIREMENTS
        # and only its verified form is persisted.
        "OfficialRetrievalResult",
        "OfficialRequirementsExtraction",
        "CandidateOfficialRequirement",
        # Phase 2A research planning eval layer: offline measurement artifacts
        # that run outside the graph and never touch a checkpoint.
        "GoldClaim",
        "GoldPrivacy",
        "GoldProject",
        "ResearchGoldCase",
        "ResearchGoldDataset",
        "ResearchGoldExpectation",
        "ResearchPlanningMetrics",
        # Student identity context for PII minimization. Deliberately never placed
        # on graph state, so personal data can never reach a checkpoint.
        "PiiKind",
        # Phase 2B academic retrieval configuration: per-process policy. The
        # budget that a run actually ran under IS checkpointed, as the
        # AcademicBudgetReport on the AcademicRetrievalResult.
        "AcademicSearchSettings",
        # Phase 2B provider-facing DTOs. Each one is the untrusted boundary of a
        # single academic API: it is validated inside its connector, mapped to
        # canonical AcademicSourceCandidates, and discarded. Only the canonical
        # form is persisted, plus the record's compact JSON on the candidate.
        "ProviderFacingModel",
        "ConsensusPaper",
        "ConsensusSearchResponse",
        "OpenAlexAuthor",
        "OpenAlexAuthorship",
        "OpenAlexLocation",
        "OpenAlexOpenAccess",
        "OpenAlexSearchResponse",
        "OpenAlexSource",
        "OpenAlexWork",
        "SemanticScholarAuthor",
        "SemanticScholarPaper",
        "SemanticScholarSearchResponse",
        "SemanticScholarVenue",
        # Phase 2B academic retrieval eval layer: offline measurement artifacts
        # that run outside any evaluation and never touch a checkpoint.
        "AcademicGoldCase",
        "AcademicGoldDataset",
        "AcademicGoldExpectation",
        "AcademicRetrievalMetrics",
        "GoldBudget",
        "GoldExpectedSource",
        "GoldPlannedQuery",
        "GoldProviderScript",
        # Phase 2C evidence extraction configuration: per-process policy. The
        # bounds a run actually applied are recorded on the extraction run.
        "EvidenceExtractionSettings",
        # Phase 2C model-facing DTOs. The untrusted boundary of the extraction
        # call: validated inside the extractor, mapped to EvidenceCandidates and
        # discarded. Only the canonical, verified form is persisted.
        "CandidateEvidenceItem",
        "CandidateNumericObservation",
        "EvidenceExtraction",
        # Phase 2C evidence extraction eval layer: offline measurement artifacts
        # that run outside any evaluation and never touch a checkpoint.
        "EvidenceExtractionMetrics",
        "EvidenceGoldCase",
        "EvidenceGoldDataset",
        "GoldEvidenceExpectation",
        "GoldObservation",
        "GoldSource",
        # Phase 2D claim-evidence alignment configuration: per-process policy.
        # The limit a run actually applied is recorded on the alignment run.
        "ClaimAlignmentSettings",
        # Phase 2D model-facing DTOs. The untrusted boundary of the
        # classification call: validated inside the classifier, mapped to
        # AlignmentCandidates and discarded. Only the canonical, verified form
        # is persisted.
        "AlignmentClassification",
        "CandidateComponentDTO",
        # Phase 2I novelty/differentiation eval layer: an offline measurement
        # artifact that runs outside any evaluation and never touches a checkpoint.
        "NoveltyGoldCase",
        # Phase 2I model-facing DTOs. The untrusted boundary of the feature
        # extraction and technical comparison calls: validated inside the
        # verifier, mapped to ComparisonFeatures / CandidateDisclosureAnchors
        # and discarded. Only the verified canonical form is persisted.
        "EvidenceDTO",
        "FeatureExtractionResponse",
        "FeatureJudgmentDTO",
        "ProposedFeatureDTO",
        "TechnicalComparisonResponse",
        # Phase 2J gap eval layer: an offline measurement artifact that runs outside any
        # evaluation and never touches a checkpoint.
        "GapGoldCase",
        # Phase 2J model-facing DTOs. The untrusted boundary of the gap
        # candidate extraction, project-linkage and counterevidence calls:
        # validated inside the verifier in the same node, mapped to exact
        # GapEvidenceRefs / GapLimitations / GapProjectLinks and discarded.
        # Only the verified canonical form is persisted.
        "CapabilityDTO",
        "ConditionDTO",
        "CounterEvidenceDTO",
        "CounterEvidenceResponse",
        "GapExtractionResponse",
        "LimitationDTO",
        "LinkJudgmentDTO",
        "LinkageResponse",
        "SpanDTO",
        "ValidationDTO",
        # Phase 3A model-facing DTOs: the untrusted overlay, evidence, applicability,
        # metric/baseline and linkage responses are verified inside the stage that
        # receives them and mapped to exact StudentMethodologyExcerpts, typed enum
        # judgments and deterministic ids, then discarded. Only the verified canonical
        # form reaches a checkpoint; no DTO field (prose, rationale, offsets) is stored.
        "ApplicabilityJudgmentDTO",
        "ApplicabilityResponse",
        "BaselineJudgmentDTO",
        "ConditionJudgmentDTO",
        "CoverageJudgmentDTO",
        "EvidenceExtractionResponse",
        "ExcerptDTO",
        "MetricBaselineResponse",
        "MetricJudgmentDTO",
        "OverlayAssessmentResponse",
        "OverlayJudgmentDTO",
        "RequirementEvidenceDTO",
        "SubmissionSpanDTO",
        "TargetLinkageResponse",
        # Phase 3A run bounds: configuration read per run from ResearchSettings.methodology,
        # like GapAssessmentBounds; never part of the persisted run.
        "MethodologyReviewBounds",
        # Phase 2I anchor-location outcome: a transient return value of the
        # exact-text locator; the verified occurrence is persisted instead as
        # OccurrenceResolution on the anchor.
        "LocateFailure",
        # Phase 2D claim-evidence alignment eval layer: offline measurement
        # artifacts that run outside any evaluation and never touch a checkpoint.
        "AlignmentGoldCase",
        "AlignmentGoldDataset",
        "AlignmentGoldExpectation",
        "ClaimAlignmentMetrics",
        "GoldComponent",
        "GoldEvidenceItem",
        "GoldScriptedResponse",
        # Phase 2E claim sufficiency configuration: per-process policy. The
        # versioned sufficiency POLICY is not a setting at all -- it lives in
        # src/research/sufficiency/policy.py and is identified on every stored
        # assessment by policy_version, which IS checkpointed.
        "ClaimSufficiencySettings",
        # Phase 2E claim sufficiency eval layer: offline measurement artifacts
        # that run outside the graph and never touch a checkpoint. Phase 2E
        # makes no model call, so there are no model-facing DTOs to exclude
        # here -- the production contracts are all checkpoint-reachable from
        # ResearchRun.claim_sufficiency and register automatically.
        "ClaimSufficiencyMetrics",
        "GoldAlignment",
        "GoldEvidence",
        "SufficiencyGoldCase",
        "SufficiencyGoldDataset",
        "SufficiencyGoldExpectation",
        # Phase 2F claim-evidence scoring eval layer: the same shape as the
        # Phase 2E block above. Phase 2F also makes no model call, so again
        # there are no model-facing DTOs to exclude, and every production
        # contract is checkpoint-reachable from
        # ResearchRun.claim_evidence_scoring and registers automatically.
        "ClaimScoringMetrics",
        "ScoringGoldCase",
        "ScoringGoldDataset",
        "ScoringGoldExpectation",
        # Phase 2G patent prior-art research. Every production contract is
        # checkpoint-reachable from ResearchRun.patent_prior_art and registers
        # automatically. Excluded here:
        # - the untrusted model-facing expansion DTOs, which the planner
        #   re-validates term by term and never stores (the Phase 1B rule);
        # - the provider-response base class, which is transport input and is
        #   never canonical state;
        # - the per-process patent search budget settings, whose effective
        #   values ARE checkpointed on PatentPriorArtRun.budget;
        # - the offline Gold eval layer, which runs outside the graph.
        "CandidatePatentExpansion",
        "CandidatePatentTerm",
        "PatentFacingModel",
        "PatentResearchSettings",
        "GoldExpected",
        "GoldFamily",
        "GoldRecord",
        "GoldSearch",
        "GoldText",
        "PatentGoldCase",
        # Phase 2H product and open-source prior-art research. Every production
        # contract is checkpoint-reachable from ResearchRun.product_prior_art and
        # ResearchRun.open_source_prior_art and registers automatically.
        # Excluded here:
        # - the untrusted model-facing expansion DTOs, re-validated term by term
        #   and never stored (the Phase 1B rule);
        # - the per-process budget settings, whose effective values ARE
        #   checkpointed on each subrun's DiscoveryBudget;
        # - the safe fetcher's URL-refusal reason and the reviewed host
        #   registry's page-kind enum, which are fetcher/configuration
        #   vocabulary: the run stores the resulting fetch status and source role;
        # - the offline Gold eval layer, which runs outside the graph.
        "CandidateDiscoveryExpansion",
        "CandidateDiscoveryTerm",
        "ProductResearchSettings",
        "OpenSourceResearchSettings",
        "UrlRefusal",
        "VendorPageKind",
        "GoldOss",
        "GoldPage",
        "GoldProduct",
        "GoldVendor",
        "ProductOssGoldCase",
        "_Strict",
    }
)
"""Types that legitimately never cross the checkpoint boundary.

This list exists so the completeness test can distinguish "deliberately not
checkpointed" from "forgotten". Adding a new checkpoint-reachable model requires
no edit here; adding an unreachable one requires a deliberate entry plus a
reason, which is the point.
"""


def test_discovery_finds_the_canonical_roots() -> None:
    names = {t.__name__ for t in CHECKPOINTED_TYPES}
    assert "EvaluationGraphState" in names
    assert "ProjectState" in names


def test_discovery_resolves_pydantic_generics() -> None:
    """``Tracked[str]`` is a distinct class from ``Tracked``; both need registering."""
    names = {t.__name__ for t in CHECKPOINTED_TYPES}
    assert "Tracked" in names
    assert "Tracked[str]" in names


def test_discovery_is_deterministic() -> None:
    assert discover_types_from(*CHECKPOINT_ROOTS) == CHECKPOINTED_TYPES


def test_discovery_reaches_deeply_nested_models() -> None:
    """Four levels down: state -> project -> scores -> axes."""
    names = {t.__name__ for t in CHECKPOINTED_TYPES}
    for expected in ("ScoreRecord", "ScoreAxis", "SourceQuality", "EvidenceLocation"):
        assert expected in names


def test_every_project_type_is_registered_or_explicitly_excluded() -> None:
    """The guarantee: a new schema cannot silently go unregistered.

    A newly added model is either reachable from the checkpoint roots -- and so
    discovered automatically -- or it fails here until someone states, with a
    reason, that it is not checkpointed.
    """
    registered = {t.__name__ for t in CHECKPOINTED_TYPES}
    unaccounted = sorted(
        t.__name__
        for t in _project_model_and_enum_types()
        if t.__name__ not in registered and t.__name__ not in NON_CHECKPOINTED_TYPES
    )
    assert unaccounted == [], (
        "these types are neither checkpoint-reachable nor declared "
        f"non-checkpointed: {unaccounted}"
    )


def test_exclusion_list_contains_no_stale_entries() -> None:
    """A type that became checkpoint-reachable must leave the exclusion list."""
    registered = {t.__name__ for t in CHECKPOINTED_TYPES}
    stale = sorted(NON_CHECKPOINTED_TYPES & registered)
    assert stale == [], f"these are now checkpointed and must be removed: {stale}"


def test_a_fully_populated_state_round_trips_with_no_unregistered_type(
    project_b,
) -> None:
    """Serialize the richest state available and audit for registration gaps."""
    state = EvaluationGraphState(
        run_id=uuid4(), thread_id=new_thread_id(), project=project_b
    )
    serde = build_serializer()
    with audit_serde_registration() as events:
        restored = serde.loads_typed(serde.dumps_typed(state))

    assert unregistered_type_keys(events) == set()
    assert restored == state
    assert isinstance(restored, EvaluationGraphState)


def test_the_audit_actually_detects_a_missing_registration(project_b) -> None:
    """Negative control: without it, the completeness test proves nothing.

    A blocked enum silently re-validates from its string value, so equality
    alone cannot detect a gap. The serde event hook can.
    """
    state = EvaluationGraphState(
        run_id=uuid4(), thread_id=new_thread_id(), project=project_b
    )
    incomplete = tuple(t for t in CHECKPOINTED_TYPES if t.__name__ != "ClaimStatus")
    serde = JsonPlusSerializer(allowed_msgpack_modules=None).with_msgpack_allowlist(
        incomplete
    )
    with audit_serde_registration() as events:
        serde.loads_typed(serde.dumps_typed(state))

    assert ("src.schemas.claim", "ClaimStatus") in unregistered_type_keys(events)


def test_graph_execution_registers_every_type_it_touches(
    app: CompiledStateGraph, run_id: UUID, config: dict
) -> None:
    """End to end: a full interrupt/resume cycle raises no registration event."""
    with audit_serde_registration() as events:
        app.invoke(_initial_state(run_id, config), config)
        app.invoke(Command(resume=COMPLETE_ANSWER), config)
    assert unregistered_type_keys(events) == set()


def test_serializer_is_built_in_strict_mode() -> None:
    """The allowlist must be the whole permission set, not an addition to a
    permissive default that would merely warn."""
    state = EvaluationGraphState(run_id=uuid4(), thread_id=new_thread_id())
    state.project.identity.project_name = Tracked[str].known("N")

    empty = JsonPlusSerializer(allowed_msgpack_modules=None)
    with audit_serde_registration() as events:
        empty.loads_typed(empty.dumps_typed(state))
    assert unregistered_type_keys(events), "strict mode should report unregistered types"


def test_registration_keys_are_module_qualified() -> None:
    keys = type_keys(CHECKPOINTED_TYPES)
    assert all(module.startswith("src.") for module, _ in keys)
    assert len(keys) == len(CHECKPOINTED_TYPES)


def test_no_manual_module_list_remains_as_the_correctness_mechanism() -> None:
    import src.graph.persistence as persistence

    assert not hasattr(persistence, "CHECKPOINTED_MODULES")
    assert not hasattr(persistence, "discover_checkpointed_types")
