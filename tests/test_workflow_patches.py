"""Tests for the human-input patch boundary and structured workflow errors.

Arabic source-preservation through this boundary is asserted in
tests/test_language_policy.py, which is the module permitted to hold Arabic
sample values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.graph.state import ProjectState
from src.schemas.common import KnowledgeStatus, Tracked, ValueOrigin
from src.workflow.errors import (
    WorkflowError,
    WorkflowErrorCode,
    WorkflowErrorReport,
)
from src.workflow.patches import (
    PatchableField,
    ProjectPatch,
    apply_project_patch,
    missing_patchable_fields,
)


# --- patch construction ----------------------------------------------------

def test_patch_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError, match="at least one field"):
        ProjectPatch(values={})


def test_patch_rejects_a_blank_value() -> None:
    with pytest.raises(ValidationError, match="cannot be blank"):
        ProjectPatch(values={PatchableField.PROBLEM_STATEMENT: "   "})


def test_patch_rejects_agent_inference_as_the_origin() -> None:
    """Human input is KNOWN; inference is never promoted to knowledge (2.1)."""
    with pytest.raises(ValidationError, match="cannot carry AGENT_INFERENCE"):
        ProjectPatch(
            values={PatchableField.PROBLEM_STATEMENT: "A problem"},
            origin=ValueOrigin.AGENT_INFERENCE,
        )


def test_from_raw_rejects_an_unlisted_field() -> None:
    """Explicitly not a generic JSON Patch endpoint."""
    with pytest.raises(WorkflowErrorReport) as exc:
        ProjectPatch.from_raw({"novelty.level": "5"})
    assert exc.value.error.code is WorkflowErrorCode.UNSUPPORTED_PATCH_FIELD


@pytest.mark.parametrize(
    "path",
    ["scores", "claims", "trust_gate", "project_id", "identity.project_type"],
)
def test_from_raw_refuses_to_patch_evaluation_outputs(path: str) -> None:
    """A human answer may fill inputs, never write evaluation conclusions."""
    with pytest.raises(WorkflowErrorReport):
        ProjectPatch.from_raw({path: "anything"})


def test_from_raw_rejects_a_non_string_value() -> None:
    with pytest.raises(WorkflowErrorReport) as exc:
        ProjectPatch.from_raw({"problem.statement": ["a", "b"]})
    assert exc.value.error.code is WorkflowErrorCode.INVALID_RESUME_INPUT


def test_from_raw_rejects_a_non_mapping_payload() -> None:
    with pytest.raises(WorkflowErrorReport) as exc:
        ProjectPatch.from_raw("problem.statement=x")  # type: ignore[arg-type]
    assert exc.value.error.code is WorkflowErrorCode.INVALID_RESUME_INPUT


def test_from_raw_accepts_supported_fields() -> None:
    patch = ProjectPatch.from_raw({"problem.statement": "A real problem."})
    assert patch.field_paths == ["problem.statement"]


# --- applying --------------------------------------------------------------

def test_apply_produces_a_known_tracked_value() -> None:
    patch = ProjectPatch(
        values={PatchableField.PROBLEM_STATEMENT: "Leaks go undetected."},
        location="chat:message-7",
    )
    updated = apply_project_patch(ProjectState(), patch)

    assert updated.problem.statement.value == "Leaks go undetected."
    assert updated.problem.statement.status is KnowledgeStatus.KNOWN
    assert updated.problem.statement.origin is ValueOrigin.STUDENT_MESSAGE
    assert updated.problem.statement.location == "chat:message-7"


def test_apply_does_not_mutate_the_input_state() -> None:
    original = ProjectState()
    apply_project_patch(
        original, ProjectPatch(values={PatchableField.PROJECT_NAME: "New name"})
    )
    assert original.identity.project_name.status is KnowledgeStatus.UNKNOWN


def test_apply_returns_a_fully_validated_state() -> None:
    updated = apply_project_patch(
        ProjectState(), ProjectPatch(values={PatchableField.PROJECT_NAME: "Name"})
    )
    assert ProjectState.model_validate(updated.model_dump()) == updated


def test_apply_preserves_unrelated_state(project_b) -> None:
    updated = apply_project_patch(
        project_b, ProjectPatch(values={PatchableField.PROJECT_NAME: "Renamed"})
    )
    assert updated.identity.project_name.value == "Renamed"
    assert len(updated.claims) == len(project_b.claims)
    assert updated.scores[0].total == project_b.scores[0].total


def test_apply_overwrites_a_conflicted_value_with_the_human_answer() -> None:
    project = ProjectState()
    project.problem.statement = Tracked[str].conflicted(["A", "B"])
    updated = apply_project_patch(
        project, ProjectPatch(values={PatchableField.PROBLEM_STATEMENT: "The real one"})
    )
    assert updated.problem.statement.status is KnowledgeStatus.KNOWN
    assert updated.problem.statement.conflicting_values == []


# --- missing field detection ----------------------------------------------

def test_missing_fields_reports_every_unknown_field() -> None:
    required = tuple(PatchableField)
    assert set(missing_patchable_fields(ProjectState(), required)) == set(required)


def test_missing_fields_is_empty_once_all_are_known() -> None:
    project = ProjectState()
    project.identity.project_name = Tracked[str].known("N")
    project.problem.statement = Tracked[str].known("P")
    project.solution.description = Tracked[str].known("S")
    assert missing_patchable_fields(project, tuple(PatchableField)) == []


@pytest.mark.parametrize(
    "tracked",
    [
        Tracked[str].unknown(),
        Tracked[str].conflicted(["A", "B"]),
        Tracked[str].inferred("a guess"),
    ],
)
def test_only_a_known_value_satisfies_a_requirement(tracked: Tracked[str]) -> None:
    """UNKNOWN, CONFLICTED and INFERRED all count as missing (2.1)."""
    project = ProjectState()
    project.problem.statement = tracked
    assert missing_patchable_fields(project, (PatchableField.PROBLEM_STATEMENT,)) == [
        PatchableField.PROBLEM_STATEMENT
    ]


# --- structured errors -----------------------------------------------------

def test_error_requires_a_message() -> None:
    with pytest.raises(ValidationError):
        WorkflowError(
            code=WorkflowErrorCode.ROUTING_FAILED, node="CHECK_CRITICAL_INPUT", message=""
        )


def test_error_key_is_stable_for_identical_errors() -> None:
    first = WorkflowError(
        code=WorkflowErrorCode.ROUTING_FAILED, node="N", message="same"
    )
    second = WorkflowError(
        code=WorkflowErrorCode.ROUTING_FAILED, node="N", message="same"
    )
    assert first.error_key == second.error_key


def test_error_metadata_stays_flat_and_serializable() -> None:
    error = WorkflowError(
        code=WorkflowErrorCode.NODE_EXECUTION_FAILED,
        node="N",
        message="failed",
        metadata={"attempt": "2"},
    )
    assert error.model_dump_json()


def test_error_report_carries_structured_data_not_just_a_string() -> None:
    error = WorkflowError(
        code=WorkflowErrorCode.INVALID_RESUME_INPUT, node="APPLY_INPUT", message="bad"
    )
    report = WorkflowErrorReport(error)
    assert report.error is error
    assert "INVALID_RESUME_INPUT" in str(report)
