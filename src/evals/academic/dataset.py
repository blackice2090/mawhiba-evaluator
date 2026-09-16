"""Academic retrieval Gold dataset.

``evals/academic_retrieval/<version>/cases.jsonl``. Each case describes a set of
already-verified planned queries, a synthetic identity context, and what each of
the three providers returns -- including the ways a provider misbehaves. The
expectation is authored from the provider payloads alone: what a correct
normalizer, verifier, deduplicator and merger must produce from that input.

The data is entirely synthetic. No real student, school or contact detail
appears anywhere, and the identifiers are made up rather than copied from real
papers, so a case can never be mistaken for a retrieval record.

Planned queries are constructed here rather than produced by the planner: Phase
2B is being measured, and feeding it a real planner's output would make an
academic-retrieval score depend on planner behaviour that Phase 1C and the
research-planning eval already measure.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from src.evals.research.dataset import GoldPrivacy
from src.research.settings import AcademicSearchSettings
from src.schemas.academic import AcademicErrorKind, AcademicProvider
from src.schemas.common import MawhibaModel, QueryPurpose, ResearchBranch
from src.schemas.research import (
    ProjectFieldReference,
    QueryPlanLimits,
    QueryRejectionReason,
    QueryStatus,
    ResearchQuery,
    SourceTerm,
    VerifiedQueryPlan,
)

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "academic_retrieval"
DEFAULT_ACADEMIC_DATASET_VERSION = "v1"

GOLD_PLANNER_VERSION = "ACADEMIC-GOLD-PLAN-V1"
GOLD_SOURCE_FIELD = "technical.algorithms"
"""The canonical field every Gold query is declared to derive from.

Provenance is verified by Phase 2A and re-measured by the research-planning
eval; here it only has to be present and internally consistent.
"""


class GoldPlannedQuery(MawhibaModel):
    """One entry of the verified query plan a case starts from."""

    key: str = Field(min_length=1, description="Stable local handle, e.g. 'q1'.")
    purpose: str = Field(default="TECHNOLOGY")
    query: str = Field(min_length=1)
    branch: str = Field(default="ACADEMIC")
    accepted: bool = Field(
        default=True,
        description="False models a query the Phase 2A verifier rejected, which "
        "academic retrieval must refuse to execute.",
    )
    source_term: str = Field(
        default="",
        description="Defaults to the first word of the query. Only has to be "
        "present and consistent for the plan to validate.",
    )


class GoldProviderScript(MawhibaModel):
    """What one provider does, in raw provider JSON."""

    records: list[dict] = Field(default_factory=list)
    payload: dict | None = Field(
        default=None,
        description="A whole response envelope, for malformed-envelope cases.",
    )
    failure: str | None = Field(default=None, description="An AcademicErrorKind.")
    leading_failures: list[str] = Field(
        default_factory=list,
        description="Attempts that fail before the records are served.",
    )
    http_status: int | None = None
    retry_after_seconds: float | None = None

    @model_validator(mode="after")
    def _known_failures(self) -> GoldProviderScript:
        for value in ([self.failure] if self.failure else []) + self.leading_failures:
            if value not in AcademicErrorKind.__members__:
                raise ValueError(f"unknown failure kind {value}")
        return self


class GoldBudget(MawhibaModel):
    """Budget overrides for a case. Absent fields keep the shipped defaults."""

    enabled_providers: list[str] | None = None
    max_academic_queries_per_run: int | None = None
    max_results_per_query_per_provider: int | None = None
    max_results_per_provider_per_run: int | None = None
    max_total_academic_candidates: int | None = None

    def settings(self) -> AcademicSearchSettings:
        base = AcademicSearchSettings()
        changes = {
            name: value
            for name, value in self.model_dump().items()
            if value is not None and name != "enabled_providers"
        }
        if self.enabled_providers is not None:
            changes["enabled_providers"] = [
                AcademicProvider(name) for name in self.enabled_providers
            ]
        return AcademicSearchSettings.model_validate({**dict(base), **changes})


class GoldExpectedSource(MawhibaModel):
    """One logical source the run must produce, identified by its fingerprint."""

    identifier_kind: str
    identifier: str
    providers: list[str] = Field(min_length=1)
    title: str | None = None
    publication_year: int | None = Field(
        default=None, description="None means the merge must leave the year unknown."
    )
    source_type: str | None = None
    is_retracted: bool | None = None
    is_preprint: bool | None = None
    citation_counts: dict[str, int] = Field(
        default_factory=dict, description="Provider -> count, never merged into one."
    )
    conflict_fields: list[str] = Field(default_factory=list)


class AcademicGoldExpectation(MawhibaModel):
    branch_outcome: str
    logical_source_count: int = Field(ge=0)
    candidate_count: int | None = Field(default=None, ge=0)
    queries_executed: int | None = Field(default=None, ge=0)
    excluded_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    provider_statuses: dict[str, list[str]] = Field(default_factory=dict)
    budget_truncated: bool | None = None
    sources: list[GoldExpectedSource] = Field(default_factory=list)


class AcademicGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^AR-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)
    queries: list[GoldPlannedQuery] = Field(min_length=1)
    privacy: GoldPrivacy = Field(default_factory=GoldPrivacy)
    providers: dict[str, GoldProviderScript] = Field(default_factory=dict)
    budget: GoldBudget | None = None
    expected: AcademicGoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _providers_are_known(self) -> AcademicGoldCase:
        for name in self.providers:
            if name not in AcademicProvider.__members__:
                raise ValueError(f"unknown provider {name}")
        return self

    def settings(self) -> AcademicSearchSettings:
        return self.budget.settings() if self.budget else AcademicSearchSettings()


class AcademicGoldDataset(MawhibaModel):
    version: str
    cases: list[AcademicGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> AcademicGoldDataset:
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


def gold_run_id(case: AcademicGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"academic-gold:{case.case_id}:run")


def gold_query_id(case: AcademicGoldCase, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"academic-gold:{case.case_id}:query:{key}")


def build_query_plan(case: AcademicGoldCase) -> VerifiedQueryPlan:
    """Materialize the case's verified query plan, deterministically."""
    run_id = gold_run_id(case)
    queries: list[ResearchQuery] = []
    for planned in case.queries:
        term = planned.source_term or planned.query.split()[0]
        accepted = planned.accepted
        queries.append(
            ResearchQuery(
                query_id=gold_query_id(case, planned.key),
                research_run_id=run_id,
                branch=ResearchBranch(planned.branch),
                candidate_branch=planned.branch,
                purpose=QueryPurpose(planned.purpose),
                candidate_purpose=planned.purpose,
                query=planned.query,
                normalized_query=planned.query.casefold(),
                derived_from=[ProjectFieldReference(field_path=GOLD_SOURCE_FIELD)]
                if accepted
                else [],
                source_terms=[SourceTerm(term=term, field_path=GOLD_SOURCE_FIELD)]
                if accepted
                else [],
                status=QueryStatus.ACCEPTED if accepted else QueryStatus.REJECTED,
                rejection_reasons=[]
                if accepted
                else [QueryRejectionReason.NO_SOURCE_TERMS],
                planner_version=GOLD_PLANNER_VERSION,
            )
        )
    return VerifiedQueryPlan(
        research_run_id=run_id,
        planner_version=GOLD_PLANNER_VERSION,
        limits=QueryPlanLimits(),
        queries=queries,
        anti_confirmation_satisfied=True,
    )


def academic_dataset_path(version: str = DEFAULT_ACADEMIC_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_academic_dataset(
    version: str = DEFAULT_ACADEMIC_DATASET_VERSION,
) -> AcademicGoldDataset:
    path = academic_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"academic retrieval dataset not found: {path}")
    cases: list[AcademicGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(AcademicGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {number}: {str(exc).splitlines()[0]}"
            ) from exc
    return AcademicGoldDataset(version=version, cases=cases)


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_ACADEMIC_DATASET_VERSION",
    "GOLD_PLANNER_VERSION",
    "AcademicGoldCase",
    "AcademicGoldDataset",
    "AcademicGoldExpectation",
    "GoldBudget",
    "GoldExpectedSource",
    "GoldPlannedQuery",
    "GoldProviderScript",
    "academic_dataset_path",
    "build_query_plan",
    "gold_query_id",
    "gold_run_id",
    "load_academic_dataset",
]
