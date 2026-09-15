"""The single boundary for applying human-supplied input to ProjectState.

Deliberately NOT a generic JSON Patch endpoint. Only an explicit allowlist of
fields can be set, every write goes through Pydantic validation, and every
applied value keeps Zero-Assumption semantics: it is recorded as KNOWN with a
student origin, never as an inferred or invented value.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.graph.state import ProjectState
from src.schemas.common import MawhibaModel, Tracked, ValueOrigin
from src.workflow.errors import WorkflowError, WorkflowErrorCode, WorkflowErrorReport


class PatchableField(StrEnum):
    """Dotted ProjectState paths a human may fill in during a resume.

    Intentionally small. Widening this set is a reviewable decision, not an
    accident of a permissive API.
    """

    PROJECT_NAME = "identity.project_name"
    PROBLEM_STATEMENT = "problem.statement"
    SOLUTION_DESCRIPTION = "solution.description"


_FIELD_LOCATIONS: dict[PatchableField, tuple[str, str]] = {
    PatchableField.PROJECT_NAME: ("identity", "project_name"),
    PatchableField.PROBLEM_STATEMENT: ("problem", "statement"),
    PatchableField.SOLUTION_DESCRIPTION: ("solution", "description"),
}


class ProjectPatch(MawhibaModel):
    """A validated set of human-supplied values.

    Values are stored verbatim. Student text may be Arabic; the field names,
    origins and statuses around it stay English (structured data layer).
    """

    values: dict[PatchableField, str] = Field(default_factory=dict)
    origin: ValueOrigin = ValueOrigin.STUDENT_MESSAGE
    location: str | None = Field(
        default=None, description="Where the answer came from, e.g. a message id."
    )

    @model_validator(mode="after")
    def _reject_empty_and_inferred(self) -> ProjectPatch:
        if not self.values:
            raise ValueError("a ProjectPatch must set at least one field")
        for field, value in self.values.items():
            if not value.strip():
                raise ValueError(f"{field.value} cannot be blank")
        if self.origin is ValueOrigin.AGENT_INFERENCE:
            raise ValueError(
                "a human-input patch cannot carry AGENT_INFERENCE origin: applied "
                "values are recorded as KNOWN, and inference is never knowledge"
            )
        return self

    @classmethod
    def from_raw(
        cls, raw: dict[str, object], *, node: str = "APPLY_INPUT"
    ) -> ProjectPatch:
        """Build a patch from untrusted input, e.g. a resume payload.

        Unknown or non-string fields raise a structured WorkflowErrorReport
        rather than a bare pydantic error, so the caller gets a domain error.
        """
        if not isinstance(raw, dict):
            raise WorkflowErrorReport(
                WorkflowError(
                    code=WorkflowErrorCode.INVALID_RESUME_INPUT,
                    node=node,
                    message="resume payload must be an object of field/value pairs",
                )
            )
        supported = {field.value for field in PatchableField}
        values: dict[str, str] = {}
        for key, value in raw.items():
            if key not in supported:
                raise WorkflowErrorReport(
                    WorkflowError(
                        code=WorkflowErrorCode.UNSUPPORTED_PATCH_FIELD,
                        node=node,
                        message=(
                            f"field '{key}' is not patchable; supported fields are "
                            f"{sorted(supported)}"
                        ),
                        recoverable=True,
                        metadata={"field": str(key)},
                    )
                )
            if not isinstance(value, str):
                raise WorkflowErrorReport(
                    WorkflowError(
                        code=WorkflowErrorCode.INVALID_RESUME_INPUT,
                        node=node,
                        message=f"field '{key}' must be a string",
                        metadata={"field": str(key)},
                    )
                )
            values[key] = value
        try:
            return cls(values=values)  # type: ignore[arg-type]
        except ValueError as exc:
            raise WorkflowErrorReport(
                WorkflowError(
                    code=WorkflowErrorCode.INVALID_RESUME_INPUT,
                    node=node,
                    message=str(exc).splitlines()[0],
                )
            ) from exc

    @property
    def field_paths(self) -> list[str]:
        return sorted(field.value for field in self.values)


def apply_project_patch(
    project: ProjectState, patch: ProjectPatch, *, node: str = "APPLY_INPUT"
) -> ProjectState:
    """Return a new, fully validated ProjectState with the patch applied.

    The input state is not mutated. The result is re-validated end to end, so a
    patch can never leave the canonical state in a shape the Phase 0 contracts
    would reject.
    """
    updated = project.model_copy(deep=True)
    for field, value in patch.values.items():
        block_name, attribute = _FIELD_LOCATIONS[field]
        block = getattr(updated, block_name)
        setattr(
            block,
            attribute,
            Tracked[str].known(value, origin=patch.origin, location=patch.location),
        )

    try:
        # Re-validate the whole state: nested assignment validates the block, but
        # only a full pass re-checks cross-record referential integrity.
        return ProjectState.model_validate(updated.model_dump())
    except ValueError as exc:
        raise WorkflowErrorReport(
            WorkflowError(
                code=WorkflowErrorCode.STATE_VALIDATION_FAILED,
                node=node,
                message=(
                    "applying the patch produced an invalid ProjectState: "
                    f"{str(exc).splitlines()[0]}"
                ),
                recoverable=False,
            )
        ) from exc


def missing_patchable_fields(
    project: ProjectState, required: tuple[PatchableField, ...]
) -> list[PatchableField]:
    """Which required fields are not yet KNOWN.

    Zero-Assumption aware: UNKNOWN, CONFLICTED and INFERRED_NON_CRITICAL all
    count as missing. Only a genuinely KNOWN value satisfies the requirement.
    """
    missing: list[PatchableField] = []
    for field in required:
        block_name, attribute = _FIELD_LOCATIONS[field]
        tracked: Tracked[str] = getattr(getattr(project, block_name), attribute)
        if not tracked.is_known:
            missing.append(field)
    return missing
