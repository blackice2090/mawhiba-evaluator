"""Production regressions found by the Phase 3B Gold evaluation (classified PRODUCTION_IMPLEMENTATION_DEFECT).

Each test pins a defect that only the independent Gold gates could see: the focused production tests never read the
recorded bounds back."""

from __future__ import annotations

from src.schemas.experiment_review import ExperimentReviewBounds, ExperimentRunStatus
from tests.phase3b_support import SUBMISSION, ScriptedExperimentModel, review, run_phase3b, run_stages, world


def test_the_run_records_the_bounds_the_stages_actually_use():
    """The run once recorded the DEFAULT bounds whatever bounds the stages ran with, so finalize re-checked the
    source window and the run validator re-checked the experiment and call bounds against the wrong limits."""
    bounds = ExperimentReviewBounds(max_submission_chars=1_000 + len(SUBMISSION), max_experiments=3, max_model_calls=10,
                                    model_retry_limit=0)
    run = run_stages(world(), ScriptedExperimentModel({}).provider(), bounds=bounds)
    assert run.bounds == bounds
    assert run.status is ExperimentRunStatus.COMPLETED


def test_the_graph_records_the_configured_bounds():
    bounds = ExperimentReviewBounds(max_experiments=2, max_model_calls=8, model_retry_limit=0)
    state = run_phase3b(world(), ScriptedExperimentModel({}).provider(), bounds=bounds)
    assert review(state).bounds == bounds


def test_a_run_that_cannot_bind_still_records_its_bounds():
    bounds = ExperimentReviewBounds(max_experiments=2, max_model_calls=8)
    state = run_phase3b(world(), None, bounds=bounds)
    assert review(state).bounds == bounds


def test_the_validator_enforces_the_recorded_call_bound():
    """A run that made more provider requests than its OWN bound is refused by the run contract."""
    import pytest
    from pydantic import ValidationError

    from src.schemas.experiment_review import ExperimentReviewRun

    bounds = ExperimentReviewBounds(max_experiments=1, max_model_calls=4)
    run = run_stages(world(), ScriptedExperimentModel({}).provider(), bounds=bounds)
    assert run.model_calls_performed <= bounds.max_model_calls
    forged = run.model_dump(mode="json") | {"model_calls_performed": 5}
    with pytest.raises(ValidationError):
        ExperimentReviewRun.model_validate(forged)
