"""Phase 2I Gold dataset model and loader.

Gold expectations are AUTHORED from the case's own source text by
``scripts/generate_phase2i_gold.py``; they are never produced by running the
system and declaring the result correct. The ``script`` block is what a
possibly-misbehaving model returns, which is how every verifier gate is made to
fire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATASET_VERSION = "NOVELTY-DIFFERENTIATION-GOLD-V1"
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "evals" / "novelty_differentiation" / "v1" / "cases.jsonl"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldClaim(_Strict):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    claim: str = Field(min_length=1)


class NoveltyGoldCase(_Strict):
    case_id: str = Field(pattern=r"^NI-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    categories: list[str] = Field(min_length=1)
    description: str = ""
    claims: list[GoldClaim] = Field(min_length=1)
    cutoff: dict[str, str] | None = None
    patent: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    oss: dict[str, Any] = Field(default_factory=dict)
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Tag -> patent publication key, product URL fragment or repository full name.",
    )
    script: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, Any] = Field(default_factory=dict)
    no_model: bool = False
    drop_sufficiency: bool = False
    interrupt_before: str | None = None
    rerun: bool = False
    injection: bool = False
    credential: str | None = None
    negative_controls: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expected")
    @classmethod
    def _expected_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("every Gold case states authored expectations")
        return value


def load_cases(path: Path = DEFAULT_DATASET) -> list[NoveltyGoldCase]:
    cases: list[NoveltyGoldCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(NoveltyGoldCase.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - surfaced to the reviewer
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return cases


__all__ = ["DATASET_VERSION", "DEFAULT_DATASET", "GoldClaim", "NoveltyGoldCase", "load_cases"]
