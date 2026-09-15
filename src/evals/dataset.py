"""Gold intake dataset loading.

The dataset lives in JSONL under ``evals/intake/<version>/cases.jsonl`` so a
reviewer can read and diff the expectations without running Python. Gold truth
is never hidden inside test logic.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel

DATASET_ROOT = Path(__file__).resolve().parents[2] / "evals" / "intake"
DEFAULT_DATASET_VERSION = "v1"


class GoldExpectation(MawhibaModel):
    """What the system must produce for a case, independent of any model output."""

    known_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Canonical dotted path -> exact expected KNOWN value. For a "
        "VERBATIM_SPAN field this is the source span, not a paraphrase.",
    )
    unknown_fields: list[str] = Field(
        default_factory=list,
        description="Paths that must remain UNKNOWN. The fabrication defence.",
    )
    conflicted_fields: list[str] = Field(default_factory=list)
    list_fields: dict[str, list[str]] = Field(default_factory=dict)
    claims: list[dict[str, str]] = Field(default_factory=list)
    domains: list[str] | None = None
    project_type: str | None = None
    contradictions: int | None = None
    rejected_fields: list[str] = Field(default_factory=list)
    no_evidence: bool = False


class ScriptedResponses(MawhibaModel):
    """What the fake provider returns for a case.

    May be adversarial on purpose: a hallucinated value, a mismatched anchor, a
    refusal. The Gold expectation says what must happen anyway.
    """

    extraction: dict | None = None
    prior_extraction: dict | None = None
    classification: dict | None = None
    failure: str | None = Field(
        default=None,
        description="REFUSAL | PROVIDER_ERROR | INCOMPLETE_OUTPUT | PARSE_ERROR. "
        "Replaces `extraction` when set.",
    )

    @model_validator(mode="after")
    def _failure_replaces_extraction(self) -> ScriptedResponses:
        if self.failure and self.extraction is not None:
            raise ValueError("a failure case must not also script an extraction")
        return self


class GoldCase(MawhibaModel):
    """One reviewable evaluation case."""

    case_id: str = Field(pattern=r"^INTAKE-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    category: str = Field(min_length=1)
    submission: str = Field(min_length=1)
    prior_submission: str | None = None
    scripted: ScriptedResponses
    expected: GoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _multi_turn_needs_a_prior(self) -> GoldCase:
        if self.scripted.prior_extraction is not None and self.prior_submission is None:
            raise ValueError(
                "a case scripting a prior extraction must supply prior_submission"
            )
        return self


class GoldDataset(MawhibaModel):
    """A versioned set of cases."""

    version: str
    cases: list[GoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> GoldDataset:
        ids = [case.case_id for case in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self

    def by_category(self, category: str) -> list[GoldCase]:
        return [c for c in self.cases if c.category == category]

    def by_id(self, case_id: str) -> GoldCase | None:
        return next((c for c in self.cases if c.case_id == case_id), None)

    @property
    def language_counts(self) -> dict[str, int]:
        return dict(Counter(c.language for c in self.cases))

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(Counter(c.category for c in self.cases))


def dataset_path(version: str = DEFAULT_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_gold_dataset(version: str = DEFAULT_DATASET_VERSION) -> GoldDataset:
    """Load and validate a Gold dataset version."""
    path = dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"gold dataset not found: {path}")

    cases: list[GoldCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(GoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {line_number}: {str(exc).splitlines()[0]}"
            ) from exc

    return GoldDataset(version=version, cases=cases)
