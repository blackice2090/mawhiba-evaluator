"""Deterministic synthesis (``EXPERIMENT_SYNTHESIZE``). No model, no result input.

Every function here takes validated Phase 3B records only. None takes the
quarantine, a result value, model prose or a model-proposed posture, so a
reported outcome can neither raise nor lower an issue, a coverage status or a
posture (ADR-023 section 5). Each posture is computed by the schema's own
derivation functions, which the run validator re-runs: a label this module did
not derive cannot be persisted.
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.experiment_review import (
    TESTING_RELATIONS,
    CoverageStatus,
    ExperimentPosture,
    ExperimentRecord,
    ExperimentReviewRun,
    Phase2JCoverage,
    TrackPostureRecord,
    coverage_track,
    derive_experiment_issues,
    derive_experiment_posture,
    derive_phase2j_coverage,
    derive_project_posture,
    derive_track_posture,
)


def _of(records: list, experiment_id: UUID) -> list:  # noqa: ANN001
    return [r for r in records if r.experiment_id == experiment_id]


def rederive_experiment(record: ExperimentRecord, run: ExperimentReviewRun) -> ExperimentRecord:
    """Issues and posture of one experiment, from its own records only."""
    if not record.requirements:
        return record
    ms, bs, ls = (_of(run.measurements, record.experiment_id), _of(run.baselines, record.experiment_id),
                  _of(run.links, record.experiment_id))
    issues = derive_experiment_issues(experiment_type=record.experiment_type, requirements=record.requirements,
                                      measurements=ms, baselines=bs, links=ls)
    posture = derive_experiment_posture(experiment_type=record.experiment_type, requirements=record.requirements,
                                        issues=issues, measurements=ms, links=ls)
    return record.model_copy(update={"issues": issues, "posture": posture})


def coverage_records(run: ExperimentReviewRun) -> list[Phase2JCoverage]:
    postures = {e.experiment_id: e.posture for e in run.experiments if e.requirements}
    out = []
    for target in run.bound_validation_targets:
        status, covering, reasons = derive_phase2j_coverage(
            target, experiment_postures=postures, links=run.links, measurements=run.measurements,
            baselines=run.baselines, conditions=run.conditions)
        attempting = sorted({link.experiment_id for link in run.links
                             if link.validation_requirement_id == target.validation_requirement_id
                             and link.relation in TESTING_RELATIONS}, key=str)
        out.append(Phase2JCoverage(
            experiment_run_id=run.experiment_run_id, validation_requirement_id=target.validation_requirement_id,
            gap_hypothesis_id=target.gap_hypothesis_id, claim_id=target.claim_id,
            attempting_experiment_ids=attempting, covering_experiment_ids=covering, status=status, reasons=reasons))
    return sorted(out, key=lambda c: str(c.validation_requirement_id))


def _ownership(run: ExperimentReviewRun, coverage: list[Phase2JCoverage]
               ) -> tuple[dict, list[CoverageStatus]]:
    targets = {t.validation_requirement_id: t for t in run.bound_validation_targets}
    owned: dict = {t: [] for t in run.tracks}
    unowned: list[CoverageStatus] = []
    for cov in sorted(coverage, key=lambda c: str(c.validation_requirement_id)):
        owner = coverage_track(targets[cov.validation_requirement_id], run.tracks)
        if owner is None:
            unowned.append(cov.status)
        else:
            owned[owner].append(cov)
    return owned, unowned


def track_records(run: ExperimentReviewRun, coverage: list[Phase2JCoverage]) -> list[TrackPostureRecord]:
    """One posture per inherited track: the worst of its own experiments and its own coverage.
    An experiment with unresolved ownership counts in no track; nothing is averaged."""
    owned, _ = _ownership(run, coverage)
    out = []
    for track in run.tracks:
        exps = sorted((e for e in run.experiments if e.track is track), key=lambda e: str(e.experiment_id))
        covs = owned[track]
        out.append(TrackPostureRecord(
            experiment_run_id=run.experiment_run_id, track=track, experiment_ids=[e.experiment_id for e in exps],
            validation_requirement_ids=[c.validation_requirement_id for c in covs],
            posture=derive_track_posture([e.posture for e in exps if e.requirements], [c.status for c in covs])))
    return out


def untested_claims(run: ExperimentReviewRun) -> list[str]:
    tested = {link.claim_id for link in run.links if link.relation in TESTING_RELATIONS}
    return sorted({c.claim_id for c in run.bound_claims} - tested)


def project_posture(run: ExperimentReviewRun) -> ExperimentPosture:
    """Worst of the tracks and of unowned coverage; unowned experiments cap at UNRESOLVED and an
    untested bound claim at PARTIALLY_SPECIFIED. The model never chooses it."""
    _, unowned = _ownership(run, run.phase2j_coverage)
    return derive_project_posture(
        [tp.posture for tp in run.track_postures],
        unowned_experiments=any(e.track is None for e in run.experiments),
        unowned_coverage=unowned, untested_claims=bool(untested_claims(run)))


__all__ = ["coverage_records", "project_posture", "rederive_experiment", "track_records", "untested_claims"]
