"""Phase 3B Gold dataset model and loader.

Gold expectations are AUTHORED by ``scripts/generate_phase3b_gold.py`` from each case's own submission text and
the approved Phase 3B contract (``catalog.py``, hand-transcribed); they are never produced by running the system
and declaring the result correct. Five things are kept apart in every case:

``project_type`` / ``phase2j_world`` / ``claims`` / ``submission``
    the authoritative CASE INPUT;
``model_script``
    the SCRIPTED MODEL RESPONSE -- what a possibly-misbehaving untrusted model returns. It may be wrong on
    purpose; that is how every verifier gate is made to fire;
``expected``
    the deterministic behaviour that is CORRECT given that response, authored from the contract;
``truth``
    the separate MODEL-JUDGMENT ground truth (is the experiment really of this type? does it really test the
    target?), so a structurally valid but semantically wrong judgment is measured, not declared correct;
``flags``
    authored facts about the case that a release gate needs (the result texts, the injected markers, ...).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATASET_VERSION = "EXPERIMENT-REVIEW-GOLD-V1"
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "evals" / "experiment_review" / "v1" / "cases.jsonl"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentGoldCase(_Strict):
    case_id: str = Field(pattern=r"^GE-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    semantic_family_id: str = Field(min_length=3, description="Language-neutral scenario identity.")
    category: str = Field(min_length=3, description="Raw category label (several families may share one).")
    project_type: Literal["SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT", "HYBRID", "UNKNOWN"]
    submission: str | None = None
    claims: list[dict[str, str]] = Field(min_length=1)
    phase2j_world: dict[str, Any] = Field(default_factory=dict)
    phase3a_context: dict[str, Any] = Field(default_factory=dict)
    model_script: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, Any] = Field(default_factory=dict)
    no_model: bool = False
    legacy_leak: bool = Field(default=False, description="Legacy results/experiments sit in ProjectState.")
    interrupt_before: str | None = None
    rerun: bool = False
    twin: Literal["order", "prefix", "result"] | None = None
    twin_data: dict[str, Any] = Field(default_factory=dict)
    mutate: Literal["claim_edit", "upstream_2j", "upstream_3a", "submission_edit", "submission_removed"] | None = None
    flags: dict[str, Any] = Field(default_factory=dict)
    truth: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    negative_control_tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("expected")
    @classmethod
    def _expected_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("every Gold case states authored expectations")
        return value


def load_cases(path: Path = DEFAULT_DATASET) -> list[ExperimentGoldCase]:
    cases: list[ExperimentGoldCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(ExperimentGoldCase.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - surfaced to the reviewer
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return cases


__all__ = ["DATASET_VERSION", "DEFAULT_DATASET", "ExperimentGoldCase", "load_cases"]
