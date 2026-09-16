"""Research planning Gold dataset.

``evals/research_planning/<version>/cases.jsonl``. Each case describes a trusted
canonical project, a synthetic identity context, what a (possibly misbehaving)
planner model returns, and what the system must produce regardless. Expectations
are authored from the project alone, never from model output.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from src.graph.state import ProjectState
from src.research.privacy import ResearchPrivacyContext
from src.schemas.claim import ClaimOrigin, ClaimRecord, ClaimStatus, ClaimType
from src.schemas.common import MawhibaModel, ProjectType, TechnicalDomain, Tracked, ValueOrigin

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "research_planning"
DEFAULT_RESEARCH_DATASET_VERSION = "v1"

GOLD_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
"""Fixed clock for Gold projects, so a case always materializes identically."""

SCRIPTED_FAILURES = frozenset({"REFUSAL", "PROVIDER_ERROR", "INCOMPLETE_OUTPUT", "PARSE_ERROR", "EMPTY_OUTPUT"})


class GoldClaim(MawhibaModel):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    claim: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.OTHER
    origin: ClaimOrigin = ClaimOrigin.STUDENT


class GoldProject(MawhibaModel):
    """A compact canonical project: KNOWN tracked values, lists, claims, classification."""

    known_fields: dict[str, str] = Field(default_factory=dict)
    list_fields: dict[str, list[str]] = Field(default_factory=dict)
    claims: list[GoldClaim] = Field(default_factory=list)
    domains: list[TechnicalDomain] = Field(default_factory=list)
    project_type: ProjectType = ProjectType.UNKNOWN


class GoldPrivacy(MawhibaModel):
    """Synthetic identity only. No real person is represented."""

    person_names: list[str] = Field(default_factory=list)
    school_names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    national_ids: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)

    def context(self) -> ResearchPrivacyContext:
        return ResearchPrivacyContext.from_identity(
            person_names=tuple(self.person_names),
            school_names=tuple(self.school_names),
            emails=tuple(self.emails),
            phone_numbers=tuple(self.phone_numbers),
            national_ids=tuple(self.national_ids),
            addresses=tuple(self.addresses),
        )

    @property
    def values(self) -> list[str]:
        return [
            *self.person_names, *self.school_names, *self.emails,
            *self.phone_numbers, *self.national_ids, *self.addresses,
        ]


class ResearchGoldExpectation(MawhibaModel):
    planner_called: bool = True
    accepted_queries: list[str] | None = Field(
        default=None, description="Exact accepted query strings, order-insensitive."
    )
    rejected: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Query string -> rejection reasons that must be present.",
    )
    required_families: list[str] = Field(default_factory=list)
    anti_confirmation_satisfied: bool | None = None
    duplicates_removed: int | None = None
    plan_issues: list[str] | None = None


class ResearchGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^RP-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)
    project: GoldProject
    privacy: GoldPrivacy = Field(default_factory=GoldPrivacy)
    scripted_plan: dict | None = None
    scripted_failure: str | None = None
    expected: ResearchGoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _one_script(self) -> ResearchGoldCase:
        if self.scripted_plan is not None and self.scripted_failure is not None:
            raise ValueError("a case scripts either a plan or a failure, not both")
        if self.scripted_failure is not None and self.scripted_failure not in SCRIPTED_FAILURES:
            raise ValueError(f"unknown scripted failure {self.scripted_failure}")
        return self


class ResearchGoldDataset(MawhibaModel):
    version: str
    cases: list[ResearchGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> ResearchGoldDataset:
        ids = [c.case_id for c in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self

    @property
    def language_counts(self) -> dict[str, int]:
        return dict(Counter(c.language for c in self.cases))

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(Counter(cat for c in self.cases for cat in c.categories))


def build_project(case: ResearchGoldCase) -> ProjectState:
    """Deterministically materialize the canonical project for a case."""
    project = ProjectState(
        project_id=uuid5(NAMESPACE_URL, f"research-gold:{case.case_id}:project"),
        project_version_id=uuid5(NAMESPACE_URL, f"research-gold:{case.case_id}:version"),
        created_at=GOLD_TIMESTAMP,
        updated_at=GOLD_TIMESTAMP,
    )
    for path, value in case.project.known_fields.items():
        *parents, attribute = path.split(".")
        target: object = project
        for part in parents:
            target = getattr(target, part)
        setattr(target, attribute, Tracked[str].known(
            value, origin=ValueOrigin.STUDENT_MESSAGE, location="artifact=gold"))
    for path, values in case.project.list_fields.items():
        block, attribute = path.split(".")
        setattr(getattr(project, block), attribute, list(values))
    project.claims = [
        ClaimRecord(claim_id=c.claim_id, claim=c.claim, claim_type=c.claim_type,
                    origin=c.origin, status=ClaimStatus.UNSUPPORTED)
        for c in case.project.claims
    ]
    project.identity.domain = list(case.project.domains)
    project.identity.project_type = case.project.project_type
    return ProjectState.model_validate(project.model_dump())


def research_dataset_path(version: str = DEFAULT_RESEARCH_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_research_dataset(version: str = DEFAULT_RESEARCH_DATASET_VERSION) -> ResearchGoldDataset:
    path = research_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"research planning dataset not found: {path}")
    cases: list[ResearchGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(ResearchGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(f"{path.name} line {number}: {str(exc).splitlines()[0]}") from exc
    return ResearchGoldDataset(version=version, cases=cases)
