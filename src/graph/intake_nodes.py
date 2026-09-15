"""Phase 1B intake nodes.

These are the first nodes that call a model. The trust boundary lives between
`PROJECT_EXTRACTOR` (untrusted candidate output) and
`VERIFY_EXTRACTION_PROVENANCE` (deterministic verdict) -- nothing the model says
reaches `ProjectState` without passing through the latter and then the merge.

The provider is injected through the graph's runtime config, so the whole path
is testable with `FakeStructuredModelProvider` and no network.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from src.config.settings import DEFAULT_LLM_SETTINGS, LLMSettings
from src.graph.contracts import (
    AuditEvent,
    NodeResult,
    NodeStatus,
    WorkflowStatus,
)
from src.graph.nodes import _completion
from src.graph.registry import NodeId
from src.graph.workflow_state import EvaluationGraphState
from src.intake.extractor import run_project_classification, run_project_extraction
from src.intake.merge import merge_classification, merge_intake_extraction
from src.intake.verification import verify_classification, verify_extraction
from src.llm.contracts import ModelCallStatus
from src.llm.provider import StructuredModelProvider
from src.schemas.submission import StudentSubmissionArtifact
from src.workflow.clock import workflow_now
from src.workflow.errors import WorkflowError, WorkflowErrorCode, WorkflowErrorReport

logger = logging.getLogger(__name__)

INTAKE_PROVIDER_KEY = "structured_model_provider"
INTAKE_SETTINGS_KEY = "llm_settings"


def _provider_from_config(config: RunnableConfig | None) -> StructuredModelProvider:
    """Pull the injected provider out of the LangGraph runtime config."""
    configurable = (config or {}).get("configurable", {})
    provider = configurable.get(INTAKE_PROVIDER_KEY)
    if provider is None:
        raise WorkflowErrorReport(
            WorkflowError(
                code=WorkflowErrorCode.NODE_EXECUTION_FAILED,
                node=NodeId.PROJECT_EXTRACTOR.value,
                message=(
                    "no structured model provider was injected; pass one via "
                    f"config['configurable']['{INTAKE_PROVIDER_KEY}']"
                ),
                recoverable=False,
            )
        )
    return provider


def _settings_from_config(config: RunnableConfig | None) -> LLMSettings:
    configurable = (config or {}).get("configurable", {})
    return configurable.get(INTAKE_SETTINGS_KEY) or DEFAULT_LLM_SETTINGS


def _model_failure_error(node: str, result: Any) -> WorkflowError:
    """Turn a non-SUCCESS model outcome into structured workflow state.

    A refusal is explicitly NOT "the project information is unknown". It is an
    execution outcome, carried as such so a UI can distinguish "the student did
    not say" from "the model would not answer".
    """
    code = (
        WorkflowErrorCode.MODEL_REFUSAL
        if result.status is ModelCallStatus.REFUSAL
        else WorkflowErrorCode.MODEL_CALL_FAILED
    )
    detail = result.refusal if result.status is ModelCallStatus.REFUSAL else result.error
    return WorkflowError(
        code=code,
        node=node,
        message=f"{result.status.value}: {detail or 'no detail supplied'}",
        recoverable=result.retryable,
        metadata={
            "model": result.model,
            "provider": result.provider,
            "status": result.status.value,
            "attempts": str(result.attempts),
            **({"request_id": result.request_id} if result.request_id else {}),
        },
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def ingest_submission(state: EvaluationGraphState) -> dict[str, Any]:
    """Confirm a submission artifact is present and preserved verbatim.

    The artifact is placed on the state by the caller. This node does not parse,
    clean or normalize it -- the original text is the ground truth that every
    later provenance check is made against.
    """
    node = NodeId.INTAKE_GUARD
    started_at = workflow_now()
    artifact = state.submission

    if artifact is None:
        error = WorkflowError(
            code=WorkflowErrorCode.NO_SUBMISSION,
            node=node.value,
            message="intake reached INGEST_SUBMISSION with no submission artifact",
            recoverable=True,
        )
        result = NodeResult(
            node=node.value,
            status=NodeStatus.FAILED,
            summary="No submission artifact supplied.",
            errors=[error],
        )
        return {
            "status": WorkflowStatus.FAILED,
            "errors": [error],
            **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
        }

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["submission"],
        summary="Submission artifact accepted and preserved verbatim.",
        # The submission body is never logged; the hash identifies it instead.
        metadata={
            "artifact": str(artifact.artifact_id),
            "content_hash": artifact.short_hash,
            "characters": str(len(artifact.original_text)),
        },
    )
    return {
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="SUBMISSION_INGESTED",
                subject=artifact.short_hash,
            )
        ],
        **_completion(state, node, result, started_at),
    }


def project_extractor(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Call the model for candidate extraction. Output is NOT trusted here."""
    node = NodeId.PROJECT_EXTRACTOR
    started_at = workflow_now()
    artifact = _require_submission(state, node.value)

    provider = _provider_from_config(config)
    settings = _settings_from_config(config)
    call = run_project_extraction(artifact, provider, settings)

    if not call.succeeded:
        error = _model_failure_error(node.value, call)
        result = NodeResult(
            node=node.value,
            status=NodeStatus.FAILED,
            summary=f"Extraction did not succeed ({call.status.value}).",
            errors=[error],
            metadata=call.log_fields(),
        )
        return {
            "status": WorkflowStatus.FAILED,
            "errors": [error],
            # ProjectState is deliberately untouched on a failed call.
            **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
        }

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["candidate_extraction"],
        summary="Candidate extraction received; not yet trusted.",
        metadata=call.log_fields(),
    )
    return {
        "candidate_extraction": call.parsed,
        **_completion(state, node, result, started_at),
    }


def verify_extraction_provenance(state: EvaluationGraphState) -> dict[str, Any]:
    """The trust boundary. Pure, deterministic, no model involved."""
    node = NodeId.PROJECT_EXTRACTOR_VERIFIER
    started_at = workflow_now()
    artifact = _require_submission(state, node.value)
    candidate = state.candidate_extraction

    if candidate is None:
        return _fail(
            state,
            node,
            started_at,
            WorkflowError(
                code=WorkflowErrorCode.NODE_EXECUTION_FAILED,
                node=node.value,
                message="verification reached without a candidate extraction",
                recoverable=False,
            ),
        )

    verified = verify_extraction(artifact, candidate)
    rejected = verified.rejected_fields

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["verified_extraction"],
        summary=(
            f"Verified {len(verified.accepted_fields)} field(s); "
            f"rejected {len(rejected)}."
        ),
        warnings=[
            f"rejected {f.field_path}: {f.rejection_reason.value}" for f in rejected
        ],
        metadata={
            "accepted": str(len(verified.accepted_fields)),
            "rejected": str(len(rejected)),
            "claims": str(len(verified.accepted_claims)),
            "conflicts": str(len(verified.accepted_conflicts)),
        },
    )
    return {
        "verified_extraction": verified,
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="EXTRACTION_VERIFIED",
                subject=artifact.short_hash,
            )
        ],
        **_completion(state, node, result, started_at),
    }


def merge_project_state(state: EvaluationGraphState) -> dict[str, Any]:
    """Fold the verified extraction into canonical state."""
    node = NodeId.PROJECT_STATE_MERGE
    started_at = workflow_now()
    verified = state.verified_extraction

    if verified is None:
        return _fail(
            state,
            node,
            started_at,
            WorkflowError(
                code=WorkflowErrorCode.NODE_EXECUTION_FAILED,
                node=node.value,
                message="merge reached without a verified extraction",
                recoverable=False,
            ),
        )

    try:
        project, report = merge_intake_extraction(state.project, verified, node=node.value)
    except WorkflowErrorReport as failure:
        return _fail(state, node, started_at, failure.error)

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=[*report.applied_fields, *report.conflicted_fields],
        summary=f"Merged verified extraction: {report.summary()}.",
        warnings=[f"unmapped field: {path}" for path in report.unmapped_fields],
        metadata={"merge": report.summary()},
    )
    return {
        "project": project,
        "audit_events": [
            AuditEvent(
                run_id=state.run_id,
                node=node.value,
                event_type="EXTRACTION_MERGED",
                subject=",".join(sorted(report.applied_fields)) or "no-field-change",
            )
        ],
        **_completion(state, node, result, started_at),
    }


def project_type_classifier(
    state: EvaluationGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Classify project type and technical domains.

    A classification failure is not fatal to intake: extraction already
    succeeded, and an unclassified project is a legitimate UNKNOWN. The failure
    is recorded and the run continues.
    """
    node = NodeId.PROJECT_TYPE_CLASSIFIER
    started_at = workflow_now()
    artifact = _require_submission(state, node.value)

    provider = _provider_from_config(config)
    settings = _settings_from_config(config)
    call = run_project_classification(artifact, provider, settings)

    if not call.succeeded:
        error = _model_failure_error(node.value, call)
        result = NodeResult(
            node=node.value,
            status=NodeStatus.SUCCEEDED,
            summary=(
                f"Classification unavailable ({call.status.value}); "
                "project type remains UNKNOWN."
            ),
            warnings=[error.message],
            metadata=call.log_fields(),
        )
        return {"errors": [error], **_completion(state, node, result, started_at)}

    verified = verify_classification(artifact, call.parsed)
    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=["verified_classification"],
        summary=f"Classified as {verified.project_type.value}.",
        metadata={
            **call.log_fields(),
            "project_type": verified.project_type.value,
            "domains": str(len(verified.accepted_domains)),
        },
    )
    return {
        "verified_classification": verified,
        **_completion(state, node, result, started_at),
    }


def merge_classification_result(state: EvaluationGraphState) -> dict[str, Any]:
    """Fold the verified classification into canonical state."""
    node = NodeId.CLASSIFICATION_MERGE
    started_at = workflow_now()
    verified = state.verified_classification

    if verified is None:
        result = NodeResult(
            node=node.value,
            status=NodeStatus.SKIPPED,
            summary="No classification to merge; project type remains UNKNOWN.",
        )
        return _completion(state, node, result, started_at, status=NodeStatus.SKIPPED)

    try:
        project, report = merge_classification(state.project, verified, node=node.value)
    except WorkflowErrorReport as failure:
        return _fail(state, node, started_at, failure.error)

    result = NodeResult(
        node=node.value,
        status=NodeStatus.SUCCEEDED,
        state_changes=[*report.applied_fields, *report.appended_values],
        summary=f"Merged classification: {report.summary()}.",
        metadata={"merge": report.summary()},
    )
    return {"project": project, **_completion(state, node, result, started_at)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_submission(
    state: EvaluationGraphState, node: str
) -> StudentSubmissionArtifact:
    if state.submission is None:
        raise WorkflowErrorReport(
            WorkflowError(
                code=WorkflowErrorCode.NO_SUBMISSION,
                node=node,
                message="node requires a submission artifact but none is present",
                recoverable=False,
            )
        )
    return state.submission


def _fail(
    state: EvaluationGraphState, node: NodeId, started_at: Any, error: WorkflowError
) -> dict[str, Any]:
    result = NodeResult(
        node=node.value,
        status=NodeStatus.FAILED,
        summary=error.message,
        errors=[error],
    )
    return {
        "status": WorkflowStatus.FAILED,
        "errors": [error],
        **_completion(state, node, result, started_at, status=NodeStatus.FAILED),
    }
