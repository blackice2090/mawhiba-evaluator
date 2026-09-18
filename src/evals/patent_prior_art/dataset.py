"""Phase 2G Gold dataset: contract, loader and provider builder.

Each Gold case describes a whole synthetic patent world -- canonical claims, the
patent records an office holds, how the office's search, family and text
services behave -- plus expectations authored from that world alone. The
scripted provider below replaces only the HTTP attempt: the real OPS XML is
built, parsed by the real parser and pushed through the real Phase 2G graph.

**Never generate pipeline output and then declare it correct.** Expectations
are written from the records and the cutoff; the scorer in ``runner.py``
re-derives identity, chronology and family counts from the same records
independently of the code it grades.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from src.research.patent.fakes import (
    MALFORMED_XML,
    FakeEpoOpsProvider,
    FakePatentRecord,
    ScriptedFamily,
    ScriptedPatentSearch,
    ScriptedText,
    UnsupportedPatentProvider,
    fault_response_xml,
)
from src.research.patent.provider import BasePatentProvider
from src.schemas.common import MawhibaModel
from src.schemas.patent import (
    PatentContentType,
    PatentErrorKind,
    PatentSearchQuery,
    PatentSearchStrategy,
)

PATENT_DATASET_VERSION = "phase2g-patent-prior-art-v1"
DEFAULT_PATENT_DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "evals" / "patent_prior_art" / "v1" / "cases.jsonl"
)

MIN_TOTAL_CASES = 128
MIN_ARABIC_CASES = 24
MIN_MIXED_CASES = 16

REQUIRED_CATEGORIES: tuple[str, ...] = (
    "exact_technical_phrase_query",
    "core_technical_concept_query",
    "mechanism_function_query",
    "synonym_expansion",
    "broader_concept_query",
    "arabic_claim_to_english_query",
    "mixed_arabic_english_query",
    "prompt_injection_in_claim",
    "pii_omitted_from_query",
    "invalid_cql_rejected",
    "search_result_not_verified_publication",
    "publication_identity_normalization",
    "authority_distinction",
    "kind_code_distinction",
    "repeated_query_same_publication_deduped",
    "multiple_observations_deduped",
    "equivalent_normalized_identifiers",
    "same_family_members_grouped",
    "family_members_preserved",
    "title_similarity_not_family",
    "family_data_unavailable",
    "family_lookup_failure",
    "earliest_priority_preserved",
    "priority_not_public_date",
    "publication_before_cutoff",
    "publication_on_cutoff",
    "publication_after_cutoff",
    "no_cutoff",
    "unknown_publication_date",
    "filing_date_distinct",
    "grant_date_distinct",
    "abstract_available",
    "claims_available",
    "claims_unavailable",
    "title_only_candidate",
    "description_available",
    "multilingual_abstract",
    "content_hash_stability",
    "snapshot_provider_provenance",
    "provider_rank_metadata_only",
    "classification_preserved",
    "shared_classification_not_same_invention",
    "bounded_query_limit",
    "bounded_result_limit",
    "provider_total_exceeds_fetched",
    "partial_provider_limit_status",
    "partial_error_status",
    "auth_blocked_status",
    "timeout",
    "rate_limited",
    "transient_retry",
    "invalid_query_not_retried",
    "pagination_range",
    "stable_query_id",
    "rerun_idempotency",
    "checkpoint_resume",
    "duplicate_observation_prevention",
    "duplicate_publication_prevention",
    "family_inflation_prevention",
    "cross_run_query_rejected",
    "cross_run_publication_rejected",
    "cross_run_family_rejected",
    "project_state_immutability",
    "phase2c_2f_immutability",
    "no_novelty_score",
    "no_legal_prior_art_conclusion",
    "no_claim_status_mutation",
    "no_project_score_mutation",
    "capability_unavailable_honest",
    "patentscope_unsupported",
    "legacy_patentsview_not_used",
    "documented_only_not_live",
)
"""The 72 categories of specification section 35, as machine-checkable names."""

TAMPER_KINDS = (
    "cross_run_query",
    "cross_run_observation",
    "cross_run_publication",
    "cross_run_family",
    "duplicate_candidate",
    "unknown_family_reference",
    "fabricated_family_member",
    "complete_despite_failure",
    "cutoff_label_without_cutoff",
    "live_verified_without_request",
)
"""Negative controls: a mutation applied to a finished run that the contract
must refuse. Each proves a gate *can* fire rather than trusting that it would."""


class GoldRecord(MawhibaModel):
    ref: str
    title: str = ""
    title_language: str = "en"
    publication_date: str = ""
    filing_date: str = ""
    priority_date: str = ""
    grant_date: str = ""
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    ipc: list[str] = Field(default_factory=list)
    cpc: list[str] = Field(default_factory=list)
    family_id: str = ""
    abstract: str = ""
    abstract_language: str = "en"
    claims: str = ""
    claims_language: str = "en"
    description: str = ""
    description_language: str = "en"
    malformed: bool = False

    def fake(self) -> FakePatentRecord:
        return FakePatentRecord(
            reference=self.ref,
            title=self.title,
            title_language=self.title_language,
            publication_date=self.publication_date,
            filing_date=self.filing_date,
            priority_date=self.priority_date,
            grant_date=self.grant_date,
            applicants=tuple(self.applicants),
            inventors=tuple(self.inventors),
            ipc=tuple(self.ipc),
            cpc=tuple(self.cpc),
            family_id=self.family_id,
            abstract=self.abstract,
            abstract_language=self.abstract_language,
            claims=self.claims,
            claims_language=self.claims_language,
            description=self.description,
            description_language=self.description_language,
            malformed=self.malformed,
        )


class GoldSearch(MawhibaModel):
    """What the office's search does for a query."""

    records: list[str] = Field(default_factory=list)
    total: int | None = None
    failure: PatentErrorKind | None = None
    leading_failures: list[PatentErrorKind] = Field(default_factory=list)
    payload: Literal["MALFORMED", "FAULT_400", "FAULT_403_QUOTA", "FAULT_500"] | None = None
    rejection_reason: str | None = None
    http_status: int | None = None
    ignore_range: bool = False
    """True models an office that returns more than the requested Range, so the
    connector's own cut is exercised rather than trusted to the provider."""


class GoldFamily(MawhibaModel):
    family_id: str = ""
    members: list[str] = Field(default_factory=list)
    earliest_priority: str = ""
    available: bool = True
    failure: PatentErrorKind | None = None


class GoldText(MawhibaModel):
    published: bool = True
    failure: PatentErrorKind | None = None


class GoldExpected(MawhibaModel):
    outcome: str
    coverage_status: str
    publication_keys: list[str] = Field(default_factory=list)
    independent_family_count: int = 0
    family_status: dict[str, str] = Field(default_factory=dict)
    family_members: dict[str, list[str]] = Field(default_factory=dict)
    time_qualification: dict[str, str] = Field(default_factory=dict)
    claims_availability: dict[str, str] = Field(default_factory=dict)
    abstract_availability: dict[str, str] = Field(default_factory=dict)
    description_availability: dict[str, str] = Field(default_factory=dict)
    title_only: list[str] = Field(default_factory=list)
    excluded_claims: dict[str, str] = Field(default_factory=dict)
    min_queries: int = 0
    max_queries: int | None = None
    required_strategies: list[str] = Field(default_factory=list)
    model_assisted: bool = False
    rejected_query_reasons: list[str] = Field(default_factory=list)
    search_error_kinds: list[str] = Field(default_factory=list)
    max_attempts: int | None = None
    retried: bool | None = None
    pages_requested: int | None = None


class PatentGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^PG-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    categories: list[str] = Field(min_length=1)
    description: str = ""
    claims: list[dict[str, str]] = Field(min_length=1)
    privacy: dict[str, list[str]] = Field(default_factory=dict)
    cutoff: str | None = None
    provider: Literal["EPO_OPS", "NONE", "WIPO_PATENTSCOPE"] = "EPO_OPS"
    settings: dict[str, Any] = Field(default_factory=dict)
    model_terms: list[dict[str, str]] | None = None
    records: list[GoldRecord] = Field(default_factory=list)
    search_default: GoldSearch = Field(default_factory=GoldSearch)
    search_by_strategy: dict[PatentSearchStrategy, GoldSearch] = Field(default_factory=dict)
    families: dict[str, GoldFamily] = Field(default_factory=dict)
    texts: dict[str, dict[PatentContentType, GoldText]] = Field(default_factory=dict)
    resume_before: str | None = None
    rerun: bool = False
    tamper: list[str] = Field(default_factory=list)
    expected: GoldExpected

    @model_validator(mode="after")
    def _references_resolve(self) -> PatentGoldCase:
        refs = {r.ref for r in self.records}
        searches = [self.search_default, *self.search_by_strategy.values()]
        for search in searches:
            unknown = [r for r in search.records if r not in refs]
            if unknown:
                raise ValueError(f"{self.case_id}: search names unknown records {unknown}")
        for family in self.families.values():
            unknown = [r for r in family.members if r not in refs]
            if unknown:
                raise ValueError(f"{self.case_id}: family names unknown records {unknown}")
        unknown_tamper = [t for t in self.tamper if t not in TAMPER_KINDS]
        if unknown_tamper:
            raise ValueError(f"{self.case_id}: unknown tamper kinds {unknown_tamper}")
        unknown_categories = [c for c in self.categories if c not in REQUIRED_CATEGORIES]
        if unknown_categories:
            raise ValueError(f"{self.case_id}: unknown categories {unknown_categories}")
        return self

    def record(self, ref: str) -> GoldRecord:
        return next(r for r in self.records if r.ref == ref)


@dataclass(frozen=True)
class PatentGoldDataset:
    cases: tuple[PatentGoldCase, ...]
    version: str = PATENT_DATASET_VERSION

    def by_language(self, language: str) -> list[PatentGoldCase]:
        return [c for c in self.cases if c.language == language]

    @property
    def category_counts(self) -> dict[str, int]:
        counts = {category: 0 for category in REQUIRED_CATEGORIES}
        for case in self.cases:
            for category in case.categories:
                counts[category] += 1
        return counts


def load_patent_dataset(path: Path = DEFAULT_PATENT_DATASET_PATH) -> PatentGoldDataset:
    cases: list[PatentGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(PatentGoldCase.model_validate(json.loads(line)))
        except Exception as exc:  # noqa: BLE001 -- report the line, then fail
            raise ValueError(f"{path.name}:{number}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids in the Phase 2G Gold dataset")
    return PatentGoldDataset(cases=tuple(cases))


# ---------------------------------------------------------------------------
# Scripted provider
# ---------------------------------------------------------------------------


def _scripted(case: PatentGoldCase, search: GoldSearch) -> ScriptedPatentSearch:
    payload = None
    if search.payload == "MALFORMED":
        payload = MALFORMED_XML
    elif search.payload == "FAULT_400":
        payload = fault_response_xml("400", "Invalid query")
    elif search.payload == "FAULT_403_QUOTA":
        payload = fault_response_xml(
            "403", "This request has been rejected due to the violation of Fair Use policy"
        )
    elif search.payload == "FAULT_500":
        payload = fault_response_xml("500", "Server error")
    return ScriptedPatentSearch(
        records=tuple(case.record(ref).fake() for ref in search.records),
        payload=payload,
        total=search.total,
        failure=search.failure,
        leading_failures=tuple(search.leading_failures),
        http_status=search.http_status,
        rejection_reason=search.rejection_reason,
    )


class GoldPatentProvider(FakeEpoOpsProvider):
    """A scripted EPO OPS office whose search answers by query strategy.

    Gold authors cannot know the exact CQL a planner will build, and must not
    need to: an expectation tied to an expression would test the planner's
    wording rather than the pipeline's behaviour. So a case scripts what the
    office returns for each *strategy*, with a default for the rest.
    """

    def __init__(self, case: PatentGoldCase, **kwargs: Any) -> None:
        super().__init__(
            families={
                case.record(ref).fake().identity.canonical_key: ScriptedFamily(
                    family_id=family.family_id,
                    members=tuple(case.record(m).fake() for m in family.members),
                    earliest_priority=family.earliest_priority,
                    available=family.available,
                    failure=family.failure,
                )
                for ref, family in case.families.items()
                if case.record(ref).fake().identity is not None
            },
            texts=_texts(case),
            **kwargs,
        )
        self._case = case
        self._by_strategy = {
            strategy: _scripted(case, search)
            for strategy, search in case.search_by_strategy.items()
        }
        self._default = _scripted(case, case.search_default)

    def _script_for(self, query: PatentSearchQuery) -> ScriptedPatentSearch:
        strategy = query.strategy
        script = self._by_strategy.get(strategy, self._default)
        gold = self._case.search_by_strategy.get(strategy, self._case.search_default)
        if gold.ignore_range or script.payload is not None or script.failure is not None:
            return script
        # An office honours the requested Range window: records a..b only, with
        # its own total still reporting everything that matched.
        offset = query.requested_range_start - 1
        window = script.records[offset : offset + query.requested_limit]
        return ScriptedPatentSearch(
            records=window,
            total=script.total if script.total is not None else len(script.records),
            leading_failures=script.leading_failures,
            http_status=script.http_status,
            retry_after_seconds=script.retry_after_seconds,
            rejection_reason=script.rejection_reason,
        )


def _texts(case: PatentGoldCase) -> dict[tuple[str, PatentContentType], ScriptedText]:
    texts: dict[tuple[str, PatentContentType], ScriptedText] = {}
    for record in case.records:
        fake = record.fake()
        if fake.identity is None:
            continue
        key = fake.identity.canonical_key
        overrides = case.texts.get(record.ref, {})
        for content_type, text, language in (
            (PatentContentType.ABSTRACT, record.abstract, record.abstract_language),
            (PatentContentType.CLAIMS, record.claims, record.claims_language),
            (PatentContentType.DESCRIPTION, record.description, record.description_language),
        ):
            override = overrides.get(content_type)
            if override is not None and override.failure is not None:
                texts[(key, content_type)] = ScriptedText(failure=override.failure)
            elif text:
                texts[(key, content_type)] = ScriptedText(
                    text=text,
                    language=language,
                    published=override.published if override else True,
                )
    return texts


def build_provider(case: PatentGoldCase) -> BasePatentProvider | None:
    if case.provider == "NONE":
        return None
    if case.provider == "WIPO_PATENTSCOPE":
        return UnsupportedPatentProvider()
    return GoldPatentProvider(case)


__all__ = [
    "DEFAULT_PATENT_DATASET_PATH",
    "MIN_ARABIC_CASES",
    "MIN_MIXED_CASES",
    "MIN_TOTAL_CASES",
    "PATENT_DATASET_VERSION",
    "REQUIRED_CATEGORIES",
    "TAMPER_KINDS",
    "GoldExpected",
    "GoldFamily",
    "GoldPatentProvider",
    "GoldRecord",
    "GoldSearch",
    "GoldText",
    "PatentGoldCase",
    "PatentGoldDataset",
    "build_provider",
    "load_patent_dataset",
]
