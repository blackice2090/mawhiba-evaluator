"""Phase 3B input binding (``EXPERIMENT_BIND_INPUTS``). Deterministic; no model.

Only authoritative inputs are bound (``ExperimentUpstreamPhase``): the verbatim
submission (artifact id and content hash), the claims (by text hash), the
finished Phase 2J run (its validation requirements copied by id and anchor hash)
and the finished Phase 3A run (context only). Each is fingerprinted here and
re-checked at finalize. ``ProjectState.results`` and the legacy
``ProjectState.experiments`` are never read: they hold outcome data and claim
support by construction (ADR-023 section 1).

Anything missing, stale or bound to another run ends the review
``INSUFFICIENT_INPUT`` at once, with the reason stated: it is never reviewed over
inputs nobody can trace.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from src.graph.state import ProjectState
from src.research.methodology.inventory import bind_claims
from src.schemas.common import ProjectType
from src.schemas.experiment_review import (
    BoundValidationTarget,
    ExperimentReviewRun,
    ExperimentRunIssue,
    ExperimentRunIssueCode,
    ExperimentRunStatus,
    ExperimentRunVersions,
    ExperimentStage,
    ExperimentUpstreamBinding,
    ExperimentUpstreamPhase,
    experiment_uuid,
    text_hash,
    tracks_for,
    upstream_fingerprint,
)
from src.schemas.methodology_review import BoundClaim
from src.schemas.research import ResearchRun
from src.schemas.submission import StudentSubmissionArtifact

NODE = ExperimentStage.BIND_INPUTS


def experiment_run_id_for(research_run_id: UUID) -> UUID:
    return experiment_uuid("run", research_run_id)


def claims_fingerprint(bound: list[BoundClaim]) -> str:
    canonical = json.dumps([[c.claim_id, c.claim_text_hash] for c in sorted(bound, key=lambda c: c.claim_id)],
                           separators=(",", ":"), ensure_ascii=False)
    return text_hash(canonical)


def current_fingerprints(
    research_run: ResearchRun, submission: StudentSubmissionArtifact | None, bound: list[BoundClaim],
) -> dict[ExperimentUpstreamPhase, tuple[UUID, str]]:
    """Every authoritative upstream Phase 3B relies on, fingerprinted. Absent ones are omitted."""
    out: dict[ExperimentUpstreamPhase, tuple[UUID, str]] = {}
    if submission is not None:
        out[ExperimentUpstreamPhase.STUDENT_SUBMISSION] = (submission.artifact_id, submission.content_hash)
    out[ExperimentUpstreamPhase.PROJECT_CLAIMS] = (
        experiment_uuid("claims", research_run.research_run_id), claims_fingerprint(bound))
    gap = research_run.research_engineering_gap
    if gap is not None:
        out[ExperimentUpstreamPhase.PHASE_2J_GAP] = (gap.gap_run_id, upstream_fingerprint(gap))
    review = research_run.methodology_review
    if review is not None:
        out[ExperimentUpstreamPhase.PHASE_3A_METHODOLOGY] = (review.methodology_run_id, upstream_fingerprint(review))
    return out


def _issue(code: ExperimentRunIssueCode, message: str) -> ExperimentRunIssue:
    return ExperimentRunIssue(code=code, node=NODE, message=message[:200])


def binding_problems(
    research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact | None,
) -> list[ExperimentRunIssue]:
    """Every reason the inputs cannot be bound. Empty means bindable."""
    missing = ExperimentRunIssueCode.SOURCE_BINDING_MISSING
    errors: list[ExperimentRunIssue] = []
    gap = research_run.research_engineering_gap
    review = research_run.methodology_review
    gap_ok = gap is not None and gap.research_run_id == research_run.research_run_id and gap.is_terminal
    if not gap_ok:
        errors.append(_issue(missing, "no finished Phase 2J run on this research run"))
    if review is None or review.research_run_id != research_run.research_run_id or not review.is_terminal:
        errors.append(_issue(missing, "no finished Phase 3A run on this research run"))
    elif gap_ok and review.gap_run_id != gap.gap_run_id:  # type: ignore[union-attr]
        errors.append(_issue(missing, "the Phase 3A run was built over a different Phase 2J run"))
    if submission is None:
        errors.append(_issue(missing, "no student submission is bound"))
    elif review is not None and review.submission_content_hash != submission.content_hash:
        errors.append(_issue(missing, "the submission differs from the one Phase 3A reviewed (stale artifact)"))
    if not project.claims:
        errors.append(_issue(missing, "the project has no claims to review against"))
    project_type = project.identity.project_type
    if gap_ok:
        if project_type is ProjectType.UNKNOWN or gap.canonical_project_type is ProjectType.UNKNOWN \
                or not tracks_for(project_type):
            errors.append(_issue(ExperimentRunIssueCode.PROJECT_TYPE_UNBOUND, "the canonical project type is unbound"))
        elif gap.canonical_project_type is not project_type or (
                review is not None and review.canonical_project_type is not project_type):
            errors.append(_issue(ExperimentRunIssueCode.PROJECT_TYPE_UNBOUND,
                                 "the upstream project types differ from the project identity"))
    return errors


def bound_targets(research_run: ResearchRun, claims: list[BoundClaim]) -> list[BoundValidationTarget]:
    """Phase 2J validation requirements copied by id and anchor hash. A hypothesis without a
    requirement yields none: nothing is invented (ADR-023 section 8)."""
    gap = research_run.research_engineering_gap
    if gap is None:
        return []
    ids = {c.claim_id for c in claims}
    out = [BoundValidationTarget.from_hypothesis(h) for h in gap.hypotheses if h.claim_id in ids]
    return sorted((t for t in out if t is not None), key=lambda t: str(t.validation_requirement_id))


def open_experiment_run(
    research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact | None,
    started_at: datetime, *, provider_name: str | None = None, model_name: str | None = None,
) -> ExperimentReviewRun:
    """Bind the run to its authoritative inputs, or end it INSUFFICIENT_INPUT with the reason stated."""
    errors = binding_problems(research_run, project, submission)
    run_id = experiment_run_id_for(research_run.research_run_id)
    claims = bind_claims(list(project.claims))
    bindings = [ExperimentUpstreamBinding(phase=phase, upstream_id=upstream_id, fingerprint=fp)
                for phase, (upstream_id, fp) in current_fingerprints(research_run, submission, claims).items()]
    if errors:
        return ExperimentReviewRun(
            experiment_run_id=run_id, research_run_id=research_run.research_run_id,
            status=ExperimentRunStatus.INSUFFICIENT_INPUT,
            versions=ExperimentRunVersions(model_provider=provider_name, model_name=model_name),
            upstream_bindings=bindings, bound_claims=claims, errors=errors, stage_markers=list(ExperimentStage),
            started_at=started_at, completed_at=started_at)
    gap, review = research_run.research_engineering_gap, research_run.methodology_review
    assert gap is not None and review is not None and submission is not None
    project_type = project.identity.project_type
    return ExperimentReviewRun(
        experiment_run_id=run_id, research_run_id=research_run.research_run_id, gap_run_id=gap.gap_run_id,
        methodology_run_id=review.methodology_run_id, status=ExperimentRunStatus.RUNNING,
        versions=ExperimentRunVersions(model_provider=provider_name, model_name=model_name),
        canonical_project_type=project_type, tracks=list(tracks_for(project_type)),
        submission_artifact_id=submission.artifact_id, submission_content_hash=submission.content_hash,
        upstream_bindings=bindings, bound_claims=claims, bound_validation_targets=bound_targets(research_run, claims),
        stage_markers=[NODE], started_at=started_at)


__all__ = [
    "bound_targets",
    "binding_problems",
    "claims_fingerprint",
    "current_fingerprints",
    "experiment_run_id_for",
    "open_experiment_run",
]
