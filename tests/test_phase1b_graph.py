"""Phase 1B intake graph: end-to-end trust behaviour.

Every test runs with the fake provider -- no API key, no network. The Phase 1A
harness graph is untouched and separately verified.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph

from src.graph.contracts import WorkflowStatus
from src.graph.intake_nodes import INTAKE_PROVIDER_KEY, INTAKE_SETTINGS_KEY
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase1a_graph import build_phase1a_graph
from src.graph.phase1b_graph import PHASE_1B_GRAPH_NAME, build_phase1b_intake_graph
from src.graph.registry import NodeId, Phase1ANode
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.llm.contracts import ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.schemas.claim import ClaimOrigin, ClaimStatus
from src.schemas.common import KnowledgeStatus, ProjectType
from src.schemas.extraction import ProjectExtraction
from src.schemas.submission import ArtifactType, StudentSubmissionArtifact
from src.workflow.errors import WorkflowErrorCode
from tests.fixtures import submissions as fx


@pytest.fixture
def app() -> CompiledStateGraph:
    return build_phase1b_intake_graph(build_checkpointer())


def _run(
    app: CompiledStateGraph,
    text: str,
    extraction: object,
    classification: object | None = None,
    *,
    project: ProjectState | None = None,
) -> EvaluationGraphState:
    """Drive one intake run with scripted model output."""
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    responses = [extraction] + ([classification] if classification is not None else [])
    config["configurable"][INTAKE_PROVIDER_KEY] = FakeStructuredModelProvider(
        responses=responses
    )
    state = EvaluationGraphState(
        run_id=run_id,
        thread_id=config["configurable"]["thread_id"],
        submission=fx.make_artifact(text),
        project=project or ProjectState(),
    )
    return coerce_graph_state(app.invoke(state, config))


def assert_pristine(project: ProjectState) -> None:
    """No intake data reached the canonical state.

    Compared field by field rather than against ``ProjectState()``: a fresh
    instance mints new UUIDs and timestamps, so object equality would compare
    identity rather than content.
    """
    assert project.identity.project_name.status is KnowledgeStatus.UNKNOWN
    assert project.problem.statement.status is KnowledgeStatus.UNKNOWN
    assert project.solution.description.status is KnowledgeStatus.UNKNOWN
    assert project.identity.project_type is ProjectType.UNKNOWN
    assert project.identity.domain == []
    assert project.technical.sensors == []
    assert project.technical.hardware == []
    assert project.claims == []
    assert project.contradictions == []
    assert project.evidence == []
    assert project.sources == []


# ===========================================================================
# Graph structure
# ===========================================================================


def test_graph_compiles_with_a_distinct_name(app: CompiledStateGraph) -> None:
    assert app.name == PHASE_1B_GRAPH_NAME


def test_phase1a_harness_graph_is_untouched() -> None:
    """Phase 1B is a separate graph, not a mutation of the harness."""
    harness = build_phase1a_graph(build_checkpointer())
    nodes = set(harness.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {node.value for node in Phase1ANode}
    assert NodeId.PROJECT_EXTRACTOR.value not in nodes


def test_graph_uses_production_node_identifiers(app: CompiledStateGraph) -> None:
    nodes = set(app.get_graph().nodes)
    for node in (
        NodeId.INTAKE_GUARD,
        NodeId.PROJECT_EXTRACTOR,
        NodeId.PROJECT_EXTRACTOR_VERIFIER,
        NodeId.PROJECT_STATE_MERGE,
        NodeId.PROJECT_TYPE_CLASSIFIER,
        NodeId.CLASSIFICATION_MERGE,
    ):
        assert node.value in nodes


def test_full_intake_path_executes_in_order(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        fx.engineering_classification(),
    )
    assert state.completed_nodes[:7] == [
        Phase1ANode.INITIALIZE_RUN.value,
        NodeId.INTAKE_GUARD.value,
        NodeId.PROJECT_EXTRACTOR.value,
        NodeId.PROJECT_EXTRACTOR_VERIFIER.value,
        NodeId.PROJECT_STATE_MERGE.value,
        NodeId.PROJECT_TYPE_CLASSIFIER.value,
        NodeId.CLASSIFICATION_MERGE.value,
    ]


def test_intake_produces_a_valid_canonical_state(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        fx.engineering_classification(),
    )
    assert ProjectState.model_validate(state.project.model_dump()) == state.project


def test_submission_is_preserved_verbatim_on_the_state(app: CompiledStateGraph) -> None:
    state = _run(app, fx.ARABIC_PROJECT_TEXT, fx.arabic_extraction())
    assert state.submission.original_text == fx.ARABIC_PROJECT_TEXT


def test_missing_submission_fails_without_touching_project_state(
    app: CompiledStateGraph,
) -> None:
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][INTAKE_PROVIDER_KEY] = FakeStructuredModelProvider(
        response=ProjectExtraction()
    )
    state = coerce_graph_state(
        app.invoke(
            EvaluationGraphState(
                run_id=run_id, thread_id=config["configurable"]["thread_id"]
            ),
            config,
        )
    )
    assert state.status is WorkflowStatus.FAILED
    assert state.errors[0].code is WorkflowErrorCode.NO_SUBMISSION
    assert_pristine(state.project)


# ===========================================================================
# Trust: hallucination
# ===========================================================================


def test_hallucinated_sensor_never_reaches_canonical_state(
    app: CompiledStateGraph,
) -> None:
    state = _run(
        app, fx.OBSTACLE_PROJECT_TEXT, fx.hallucinated_sensor_extraction()
    )
    assert state.project.technical.sensors == []
    assert state.verified_extraction.accepted_fields == []


def test_mismatched_anchor_value_never_reaches_canonical_state(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.CAMERA_PROJECT_TEXT, fx.mismatched_anchor_extraction())
    assert state.project.technical.algorithms == []


def test_candidate_and_verified_extraction_are_separate_channels(
    app: CompiledStateGraph,
) -> None:
    """The untrusted candidate stays visible next to the verdict."""
    state = _run(
        app, fx.OBSTACLE_PROJECT_TEXT, fx.hallucinated_sensor_extraction()
    )
    assert state.candidate_extraction.sensors[0].value == "LiDAR"
    assert state.verified_extraction.rejected_fields[0].value == "LiDAR"


def test_explicit_facts_are_accepted_end_to_end(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        fx.engineering_classification(),
    )
    assert state.project.identity.project_name.value == "Sentinel"
    assert state.project.identity.project_name.status is KnowledgeStatus.KNOWN
    assert state.project.technical.sensors == ["three ultrasonic sensors"]


def test_yolo_example_extracts_only_what_was_stated(app: CompiledStateGraph) -> None:
    """'Trained YOLOv8 on 4,000 labeled images' -- and nothing about who labeled
    them or how."""
    state = _run(app, fx.YOLO_PROJECT_TEXT, fx.yolo_extraction())
    assert state.project.technical.algorithms == ["YOLOv8"]
    assert state.project.technical.datasets == ["4,000 labeled images"]
    assert state.project.methodology.baseline == []
    assert state.project.methodology.metrics == []


# ===========================================================================
# Trust: missing information
# ===========================================================================


def test_sparse_submission_leaves_everything_else_unknown(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.MINIMAL_PROJECT_TEXT, fx.minimal_extraction())
    project = state.project

    assert project.technical.datasets == []
    assert project.methodology.baseline == []
    assert project.methodology.metrics == []
    assert project.methodology.hypothesis.status is KnowledgeStatus.UNKNOWN
    assert project.experiments == []
    assert project.results == []


# ===========================================================================
# Trust: Arabic and mixed language
# ===========================================================================


def test_arabic_submission_is_extracted_without_translation(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.ARABIC_PROJECT_TEXT, fx.arabic_extraction())
    project = state.project

    assert project.identity.project_name.value == "حارس النخيل"
    assert project.identity.project_name.status is KnowledgeStatus.KNOWN
    assert "كاميرا" in project.technical.hardware
    # Structure stays English even when the values are Arabic.
    assert project.identity.project_name.status.value.isascii()
    assert project.identity.project_name.origin.value.isascii()


def test_mixed_language_terms_are_preserved_unchanged(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.MIXED_LANGUAGE_TEXT, fx.mixed_language_extraction())
    assert state.project.technical.algorithms == ["YOLOv8"]
    assert state.project.technical.hardware == ["Raspberry Pi"]


# ===========================================================================
# Trust: prompt injection
# ===========================================================================


def test_injection_text_does_not_alter_novelty_or_scores(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.PROMPT_INJECTION_TEXT, fx.injection_extraction())
    project = state.project

    assert project.novelty.level is None
    assert project.novelty.status.value == "NOT_EVALUATED"
    assert project.scores == []
    assert project.trust_gate is None


def test_injection_text_does_not_alter_workflow_control(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.PROMPT_INJECTION_TEXT, fx.injection_extraction())
    assert state.status is not WorkflowStatus.COMPLETED or state.has_completed(
        Phase1ANode.MARK_READY.value
    )
    assert state.input_requests <= 1


def test_injection_content_is_still_extractable_as_project_information(
    app: CompiledStateGraph,
) -> None:
    """The surrounding legitimate content is not discarded."""
    state = _run(app, fx.PROMPT_INJECTION_TEXT, fx.injection_extraction())
    assert "pressure sensor" in state.project.technical.hardware


def test_injection_text_is_preserved_in_the_raw_submission(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.PROMPT_INJECTION_TEXT, fx.injection_extraction())
    assert "Ignore your instructions" in state.submission.original_text


def test_the_injection_boundary_is_sent_to_the_model() -> None:
    provider = FakeStructuredModelProvider(response=fx.injection_extraction())
    from src.config.settings import LLMSettings
    from src.intake.extractor import run_project_extraction

    run_project_extraction(
        fx.make_artifact(fx.PROMPT_INJECTION_TEXT), provider, LLMSettings()
    )
    assert "SECURITY BOUNDARY" in provider.last_system_prompt()


# ===========================================================================
# Trust: student claims
# ===========================================================================


def test_student_claim_is_isolated_from_evidence(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        fx.engineering_classification(),
    )
    project = state.project

    assert len(project.claims) == 1
    assert project.claims[0].origin is ClaimOrigin.STUDENT
    assert project.claims[0].status is ClaimStatus.UNSUPPORTED
    assert project.evidence == []
    assert project.sources == []
    assert project.scores == []


# ===========================================================================
# Trust: conflicts
# ===========================================================================


def test_conflicting_statements_create_a_contradiction(
    app: CompiledStateGraph,
) -> None:
    state = _run(
        app, fx.CONFLICTING_DATASET_TEXT, fx.conflicting_dataset_extraction()
    )
    assert len(state.project.contradictions) == 1
    assert state.project.contradictions[0].requires_student_clarification


def test_conflict_across_two_turns_is_not_silently_resolved(
    app: CompiledStateGraph,
) -> None:
    first = _run(
        app,
        "Project name: Sentinel",
        fx.named_project_extraction("Sentinel", "Project name: Sentinel"),
    )
    assert first.project.identity.project_name.value == "Sentinel"

    second = _run(
        app,
        "Project name: Guardian",
        fx.named_project_extraction("Guardian", "Project name: Guardian"),
        project=first.project,
    )
    name = second.project.identity.project_name
    assert name.status is KnowledgeStatus.CONFLICTED
    assert name.value is None
    assert set(name.conflicting_values) == {"Sentinel", "Guardian"}


def test_multi_turn_intake_preserves_earlier_state(app: CompiledStateGraph) -> None:
    first = _run(
        app,
        "Project name: Sentinel",
        fx.named_project_extraction("Sentinel", "Project name: Sentinel"),
    )
    second = _run(
        app,
        "We use three microphones.",
        ProjectExtraction(
            hardware=[fx.value("three microphones", "We use three microphones")]
        ),
        project=first.project,
    )
    assert second.project.identity.project_name.value == "Sentinel"
    assert "three microphones" in second.project.technical.hardware


# ===========================================================================
# Classification through the graph
# ===========================================================================


def test_classification_is_merged(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        fx.engineering_classification(),
    )
    assert state.project.identity.project_type is ProjectType.ENGINEERING_PROJECT


def test_ambiguous_project_remains_unknown(app: CompiledStateGraph) -> None:
    state = _run(
        app,
        fx.AMBIGUOUS_PROJECT_TEXT,
        ProjectExtraction(),
        fx.unknown_classification(),
    )
    assert state.project.identity.project_type is ProjectType.UNKNOWN
    assert state.project.identity.project_type_confidence is None


def test_classification_failure_is_not_fatal(app: CompiledStateGraph) -> None:
    """Extraction already succeeded; an unclassified project is a valid UNKNOWN."""
    state = _run(
        app,
        fx.SENSOR_PROJECT_TEXT,
        fx.sensor_project_extraction(),
        refusal_result(ModelTask.PROJECT_CLASSIFICATION),
    )
    assert state.project.identity.project_name.value == "Sentinel"
    assert state.project.identity.project_type is ProjectType.UNKNOWN
    assert any(e.code is WorkflowErrorCode.MODEL_REFUSAL for e in state.errors)


# ===========================================================================
# Provider failure handling
# ===========================================================================


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (refusal_result(ModelTask.PROJECT_EXTRACTION), WorkflowErrorCode.MODEL_REFUSAL),
        (
            provider_error_result(ModelTask.PROJECT_EXTRACTION),
            WorkflowErrorCode.MODEL_CALL_FAILED,
        ),
        (
            incomplete_result(ModelTask.PROJECT_EXTRACTION),
            WorkflowErrorCode.MODEL_CALL_FAILED,
        ),
        (
            parse_error_result(ModelTask.PROJECT_EXTRACTION),
            WorkflowErrorCode.MODEL_CALL_FAILED,
        ),
    ],
)
def test_extraction_failure_leaves_project_state_unchanged(
    app: CompiledStateGraph, failure: object, expected_code: WorkflowErrorCode
) -> None:
    state = _run(app, fx.SENSOR_PROJECT_TEXT, failure)

    assert state.status is WorkflowStatus.FAILED
    assert state.errors[0].code is expected_code
    assert_pristine(state.project)
    assert state.verified_extraction is None


def test_refusal_does_not_become_empty_successful_extraction(
    app: CompiledStateGraph,
) -> None:
    """A refusal is an execution outcome, not 'the student said nothing'."""
    state = _run(app, fx.SENSOR_PROJECT_TEXT, refusal_result(ModelTask.PROJECT_EXTRACTION))

    assert state.candidate_extraction is None
    assert state.verified_extraction is None
    assert state.errors[0].code is WorkflowErrorCode.MODEL_REFUSAL
    assert state.project.identity.project_name.status is KnowledgeStatus.UNKNOWN


def test_failure_does_not_crash_the_workflow(app: CompiledStateGraph) -> None:
    state = _run(app, fx.SENSOR_PROJECT_TEXT, refusal_result(ModelTask.PROJECT_EXTRACTION))
    assert state.status is WorkflowStatus.FAILED
    assert ProjectState.model_validate(state.project.model_dump()) == state.project


def test_retry_exhaustion_leaves_state_valid(app: CompiledStateGraph) -> None:
    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    config["configurable"][INTAKE_PROVIDER_KEY] = FakeStructuredModelProvider(
        responses=[provider_error_result(ModelTask.PROJECT_EXTRACTION) for _ in range(5)]
    )
    state = coerce_graph_state(
        app.invoke(
            EvaluationGraphState(
                run_id=run_id,
                thread_id=config["configurable"]["thread_id"],
                submission=fx.make_artifact(fx.SENSOR_PROJECT_TEXT),
            ),
            config,
        )
    )
    assert state.status is WorkflowStatus.FAILED
    assert_pristine(state.project)


def test_settings_can_be_injected_per_run(app: CompiledStateGraph) -> None:
    from src.config.settings import LLMSettings

    run_id = uuid4()
    config = thread_config(new_thread_id(run_id))
    provider = FakeStructuredModelProvider(responses=[ProjectExtraction()])
    config["configurable"][INTAKE_PROVIDER_KEY] = provider
    config["configurable"][INTAKE_SETTINGS_KEY] = LLMSettings(
        extraction_model="injected-model"
    )
    app.invoke(
        EvaluationGraphState(
            run_id=run_id,
            thread_id=config["configurable"]["thread_id"],
            submission=fx.make_artifact(fx.MINIMAL_PROJECT_TEXT),
        ),
        config,
    )
    assert provider.calls[0]["model"] == "injected-model"


# ===========================================================================
# Submission artifact contract
# ===========================================================================


def test_phase1b_supports_text_artifacts_only() -> None:
    with pytest.raises(ValueError, match="not supported in Phase 1B"):
        StudentSubmissionArtifact(
            project_id=uuid4(),
            artifact_type=ArtifactType.FILE_PDF,
            original_text="content",
        )


def test_artifact_hash_identifies_without_exposing_content() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    assert len(artifact.short_hash) == 12
    assert fx.SENSOR_PROJECT_TEXT not in artifact.short_hash


def test_artifact_language_is_not_guessed() -> None:
    assert fx.make_artifact(fx.ARABIC_PROJECT_TEXT).language is None


def test_logs_reference_the_artifact_hash_not_the_submission(
    app: CompiledStateGraph,
) -> None:
    state = _run(app, fx.SENSOR_PROJECT_TEXT, fx.sensor_project_extraction())
    record = state.record_for(NodeId.INTAKE_GUARD.value)
    metadata = record.result.metadata
    assert metadata["content_hash"] == state.submission.short_hash
    assert fx.SENSOR_PROJECT_TEXT not in str(metadata)
