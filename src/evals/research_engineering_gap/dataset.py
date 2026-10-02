"""Phase 2J Gold dataset model and loader.

Gold expectations are AUTHORED from each case's own source text and the Phase 2J
policy by ``scripts/generate_phase2j_gold.py``; they are never produced by
running the system and declaring the result correct. Three things are kept apart
in every case:

``patent`` / ``product`` / ``oss`` / ``claims``
    the authoritative CASE INPUT -- source text and claim text;
``script``
    the SCRIPTED MODEL RESPONSE -- what a possibly-misbehaving untrusted model
    returns. It may be wrong on purpose; that is how every verifier gate is made
    to fire;
``expected``
    the deterministic behaviour that is CORRECT given that response, authored
    from policy. ``truth`` carries the separate model-judgment ground truth
    (the correct linkage relation, whether a passage is one proposition or
    two), so a structurally valid but semantically wrong model judgment is
    measured honestly instead of being declared correct.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATASET_VERSION = "RESEARCH-ENGINEERING-GAP-GOLD-V1"
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "evals" / "research_engineering_gap" / "v1" / "cases.jsonl"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldClaim(_Strict):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    claim: str = Field(min_length=1)


class GapGoldCase(_Strict):
    case_id: str = Field(pattern=r"^GP-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    categories: list[str] = Field(min_length=1)
    description: str = ""
    claims: list[GoldClaim] = Field(min_length=1)
    cutoff: dict[str, str] | None = None
    patent: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    oss: dict[str, Any] = Field(default_factory=dict)
    nd: dict[str, Any] = Field(default_factory=dict, description="The Phase 2I script: features and disclosure mode.")
    script: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, Any] = Field(default_factory=dict)
    no_model: bool = False
    drop_sufficiency: bool = False
    retract_academic: bool = False
    interrupt_before: str | None = None
    rerun: bool = False
    twin: Literal["prose", "order"] | None = None
    mutate: Literal["claim_edit", "upstream_mutation"] | None = None
    prose: str = Field(default="", description="Free prose a twin run injects into every rationale (data, any language).")
    controls: list[str] = Field(default_factory=list)
    truth: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expected")
    @classmethod
    def _expected_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("every Gold case states authored expectations")
        return value


def load_cases(path: Path = DEFAULT_DATASET) -> list[GapGoldCase]:
    cases: list[GapGoldCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(GapGoldCase.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - surfaced to the reviewer
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return cases


__all__ = ["DATASET_VERSION", "DEFAULT_DATASET", "GapGoldCase", "GoldClaim", "load_cases"]
