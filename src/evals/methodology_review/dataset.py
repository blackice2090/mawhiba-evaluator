"""Phase 3A Gold dataset model and loader.

Gold expectations are AUTHORED by ``scripts/generate_phase3a_gold.py`` from each case's own submission text
and the approved Phase 3A policy; they are never produced by running the system and declaring the result
correct. Four things are kept apart in every case:

``project_type`` / ``domains`` / ``gap_variant`` / ``claim_variant`` / ``submission``
    the authoritative CASE INPUT;
``script``
    the SCRIPTED MODEL RESPONSE -- what a possibly-misbehaving untrusted model returns. It may be wrong on
    purpose; that is how every verifier gate is made to fire;
``expected``
    the deterministic behaviour that is CORRECT given that response, authored from policy;
``truth``
    the separate MODEL-JUDGMENT ground truth (is the overlay really material? does the passage really test the
    target?), so a structurally valid but semantically wrong judgment is measured honestly, not declared correct.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATASET_VERSION = "METHODOLOGY-REVIEW-GOLD-V1"
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "evals" / "methodology_review" / "v1" / "cases.jsonl"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MethodGoldCase(_Strict):
    case_id: str = Field(pattern=r"^GM-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    categories: list[str] = Field(min_length=1)
    description: str = ""
    semantic_family: str = Field(default="", description="Language-neutral mechanism identity shared by translated variants.")
    project_type: Literal["SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT", "HYBRID", "UNKNOWN"]
    domains: list[str] = Field(default_factory=list)
    gap_variant: Literal["default", "baseline", "no_condition", "no_requirement"] = "default"
    claim_variant: str = Field(default="base", description="'base', or text appended to the canonical claim.")
    submission: str | None = None
    script: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, Any] = Field(default_factory=dict)
    no_model: bool = False
    results_leak: bool = Field(default=False, description="Successful results/experiments sit in ProjectState.")
    interrupt_before: str | None = None
    rerun: bool = False
    twin: Literal["prose", "order"] | None = None
    mutate: Literal["claim_edit", "upstream_2i", "upstream_2j", "submission_edit", "submission_removed"] | None = None
    prose: str = Field(default="", description="Free prose a twin run injects into every rationale (data, any language).")
    flags: dict[str, Any] = Field(default_factory=dict, description="Authored facts about the case a gate needs.")
    controls: list[str] = Field(default_factory=list)
    truth: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expected")
    @classmethod
    def _expected_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("every Gold case states authored expectations")
        return value


def load_cases(path: Path = DEFAULT_DATASET) -> list[MethodGoldCase]:
    cases: list[MethodGoldCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(MethodGoldCase.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - surfaced to the reviewer
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return cases


__all__ = ["DATASET_VERSION", "DEFAULT_DATASET", "MethodGoldCase", "load_cases"]
