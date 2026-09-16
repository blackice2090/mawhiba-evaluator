"""Evidence extraction Gold dataset.

``evals/evidence_extraction/<version>/cases.jsonl``. Each case describes
synthetic source content, what a possibly-misbehaving extractor returns for it,
and what the system must produce regardless.

Expectations are authored from the **source content alone**: given this abstract
and this proposed excerpt, does an exact span exist? The scripted model output is
what a model might say, never what is correct. A case that scripts a hallucinated
quote expects a rejection, and a case that scripts a wrong number expects a
numeric-fidelity rejection, whatever the model's confidence.

All content is synthetic. No real paper, abstract, author or student identity
appears anywhere.

Source content is expressed per provider observation rather than as one merged
string, because that is the distinction Phase 2C is built around (§7): an
abstract with no provider attribution cannot become evidence anyone could trace.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.academic import (
    AcademicBudgetReport,
    AcademicBranchOutcome,
    AcademicCandidateDecision,
    AcademicIdentifiers,
    AcademicProvider,
    AcademicRetrievalResult,
    AcademicSearchQuery,
    AcademicSourceCandidate,
    AcademicSourceType,
    LogicalAcademicSource,
    ProviderObservation,
)
from src.schemas.common import MawhibaModel, QueryPurpose, ResearchBranch
from src.schemas.source import SourceFingerprint, SourceIdentifierKind

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "evidence_extraction"
DEFAULT_EVIDENCE_DATASET_VERSION = "v1"

GOLD_RETRIEVED_AT_ISO = "2026-09-01T09:00:00+00:00"
SCRIPTED_FAILURES = frozenset(
    {"REFUSAL", "PROVIDER_ERROR", "INCOMPLETE_OUTPUT", "PARSE_ERROR", "EMPTY_OUTPUT"}
)


class GoldObservation(MawhibaModel):
    """One provider's view of a source, and the text it supplied."""

    provider: str = Field(default="CONSENSUS")
    abstract: str | None = Field(
        default=None,
        description="The paper's own abstract as this provider returned it. "
        "Null models a provider that returned metadata only.",
    )
    takeaway: str | None = Field(
        default=None,
        description="Provider-generated synthesis. Must never become content (§8).",
    )
    provider_record_id: str | None = None

    @model_validator(mode="after")
    def _known_provider(self) -> GoldObservation:
        if self.provider not in AcademicProvider.__members__:
            raise ValueError(f"unknown provider {self.provider}")
        return self


class GoldSource(MawhibaModel):
    """A verified academic source the extractor will be pointed at."""

    key: str = Field(min_length=1, description="Stable local handle, e.g. 's1'.")
    title: str = Field(default="A synthetic study")
    doi: str | None = Field(default=None, description="Defaults to one derived from key.")
    publication_year: int | None = 2021
    source_type: str = Field(default="JOURNAL_ARTICLE")
    is_retracted: bool | None = None
    citation_count: int | None = None
    observations: list[GoldObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_source_type(self) -> GoldSource:
        if self.source_type not in AcademicSourceType.__members__:
            raise ValueError(f"unknown source type {self.source_type}")
        return self


class GoldEvidenceExpectation(MawhibaModel):
    """What a correct extraction must produce from the content alone."""

    status: str | None = None
    content_snapshots: int | None = Field(default=None, ge=0)
    accepted_count: int | None = Field(default=None, ge=0)
    accepted_excerpts: list[str] | None = Field(
        default=None, description="Exact verified excerpts, order-insensitive."
    )
    evidence_types: list[str] | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    ineligible_reasons: list[str] = Field(default_factory=list)
    evidence_scopes: list[str] | None = None
    retracted_evidence_count: int | None = Field(default=None, ge=0)
    preprint_evidence_count: int | None = Field(default=None, ge=0)
    numeric_raw_texts: list[str] | None = None
    forbidden_excerpt_substrings: list[str] = Field(
        default_factory=list,
        description="Text that must never appear in any accepted excerpt -- a "
        "Consensus takeaway, a title, a citation count.",
    )


class EvidenceGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^EE-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)
    purpose: str = Field(default="LIMITATIONS")
    sources: list[GoldSource] = Field(default_factory=list)
    scripted: dict | None = Field(
        default=None, description="What the extractor returns, per the DTO shape."
    )
    scripted_failure: str | None = None
    expected: GoldEvidenceExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _one_script(self) -> EvidenceGoldCase:
        if self.scripted is not None and self.scripted_failure is not None:
            raise ValueError("a case scripts either output or a failure, not both")
        if self.scripted_failure is not None and self.scripted_failure not in SCRIPTED_FAILURES:
            raise ValueError(f"unknown scripted failure {self.scripted_failure}")
        if self.purpose not in QueryPurpose.__members__:
            raise ValueError(f"unknown purpose {self.purpose}")
        return self


class EvidenceGoldDataset(MawhibaModel):
    version: str
    cases: list[EvidenceGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> EvidenceGoldDataset:
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


# ---------------------------------------------------------------------------
# Deterministic materialization
# ---------------------------------------------------------------------------


def gold_run_id(case: EvidenceGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"evidence-gold:{case.case_id}:run")


def gold_query_id(case: EvidenceGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"evidence-gold:{case.case_id}:query")


def _source_id(case: EvidenceGoldCase, source: GoldSource) -> str:
    return f"SRC-{uuid5(NAMESPACE_URL, f'evidence-gold:{case.case_id}:{source.key}')}"


def _retrieved_at():
    from datetime import datetime

    return datetime.fromisoformat(GOLD_RETRIEVED_AT_ISO)


def build_academic_result(case: EvidenceGoldCase) -> AcademicRetrievalResult:
    """Materialize the Phase 2B state a case starts from, deterministically.

    Built directly rather than by running the academic graph: Phase 2C is what is
    being measured, and re-deriving retrieval would make an evidence score depend
    on connector behaviour the Phase 2B eval already covers.
    """
    run_id = gold_run_id(case)
    query_id = gold_query_id(case)
    retrieved_at = _retrieved_at()

    candidates: list[AcademicSourceCandidate] = []
    decisions: list[AcademicCandidateDecision] = []
    logical_sources: list[LogicalAcademicSource] = []

    for index, source in enumerate(case.sources, start=1):
        source_id = _source_id(case, source)
        doi = source.doi or f"10.5555/{case.case_id.lower()}-{source.key}"
        identifiers = AcademicIdentifiers(doi=doi)
        source_type = AcademicSourceType(source.source_type)
        observations: list[ProviderObservation] = []

        for observation in source.observations:
            provider = AcademicProvider(observation.provider)
            raw = {"takeaway": observation.takeaway} if observation.takeaway else None
            candidate = AcademicSourceCandidate(
                research_run_id=run_id,
                query_id=query_id,
                provider=provider,
                source_type=source_type,
                title=source.title,
                abstract=observation.abstract,
                publication_year=source.publication_year,
                identifiers=identifiers,
                canonical_url=f"https://doi.org/{doi}",
                provider_url=f"https://example.org/{source.key}",
                citation_count=source.citation_count,
                is_retracted=source.is_retracted,
                provider_record_id=observation.provider_record_id,
                retrieved_at=retrieved_at,
                raw_provider_metadata=json.dumps(raw, sort_keys=True) if raw else None,
            )
            candidates.append(candidate)
            decisions.append(
                AcademicCandidateDecision(
                    candidate_id=candidate.candidate_id,
                    provider=provider,
                    query_id=query_id,
                    accepted=True,
                    logical_source_id=source_id,
                )
            )
            observations.append(
                ProviderObservation(
                    provider=provider,
                    candidate_id=candidate.candidate_id,
                    query_id=query_id,
                    research_run_id=run_id,
                    provider_record_id=observation.provider_record_id,
                    provider_url=candidate.provider_url,
                    canonical_url=candidate.canonical_url,
                    identifiers=identifiers,
                    title=source.title,
                    publication_year=source.publication_year,
                    source_type=source_type,
                    is_retracted=source.is_retracted,
                    citation_count=source.citation_count,
                    retrieved_at=retrieved_at,
                )
            )

        if not observations:
            continue

        logical_sources.append(
            LogicalAcademicSource(
                logical_source_id=source_id,
                display_id=f"SRC-{index:03d}",
                research_run_id=run_id,
                fingerprint=SourceFingerprint.create(SourceIdentifierKind.DOI, doi),
                identifiers=identifiers,
                title=source.title,
                abstract=next(
                    (o.abstract for o in source.observations if o.abstract), None
                ),
                publication_year=source.publication_year,
                source_type=source_type,
                is_retracted=source.is_retracted,
                canonical_url=f"https://doi.org/{doi}",
                observations=observations,
                first_retrieved_at=retrieved_at,
            )
        )

    budget = AcademicBudgetReport(
        max_queries_per_run=4,
        max_results_per_query_per_provider=10,
        max_results_per_provider_per_run=30,
        max_total_candidates=90,
        queries_available=1,
        queries_executed=1,
        candidates_returned=len(candidates),
        candidates_accepted=len(candidates),
    )
    selected = [
        AcademicSearchQuery(
            research_run_id=run_id,
            query_id=query_id,
            branch=ResearchBranch.ACADEMIC,
            purpose=QueryPurpose(case.purpose),
            query="synthetic gold query",
            provider=AcademicProvider.CONSENSUS,
            requested_limit=10,
        )
    ]

    return AcademicRetrievalResult(
        research_run_id=run_id,
        outcome=(
            AcademicBranchOutcome.SUCCESS
            if logical_sources
            else AcademicBranchOutcome.EMPTY
        ),
        providers=list(AcademicProvider),
        budget=budget,
        selected_queries=selected,
        candidates=candidates,
        decisions=decisions,
        logical_sources=logical_sources,
        verified_sources=[s.to_source_record() for s in logical_sources],
    )


def evidence_dataset_path(version: str = DEFAULT_EVIDENCE_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_evidence_dataset(
    version: str = DEFAULT_EVIDENCE_DATASET_VERSION,
) -> EvidenceGoldDataset:
    path = evidence_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"evidence extraction dataset not found: {path}")
    cases: list[EvidenceGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(EvidenceGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {number}: {str(exc).splitlines()[0]}"
            ) from exc
    return EvidenceGoldDataset(version=version, cases=cases)


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_EVIDENCE_DATASET_VERSION",
    "EvidenceGoldCase",
    "EvidenceGoldDataset",
    "GoldEvidenceExpectation",
    "GoldObservation",
    "GoldSource",
    "build_academic_result",
    "evidence_dataset_path",
    "gold_query_id",
    "gold_run_id",
    "load_evidence_dataset",
]
