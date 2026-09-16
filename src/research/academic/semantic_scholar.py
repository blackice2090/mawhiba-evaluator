"""The Semantic Scholar connector.

Semantic Scholar returns a stable ``paperId`` plus an ``externalIds`` map, which
makes it the richest source of cross-provider identity in Phase 2B: one record
can carry the DOI, the PubMed id and the arXiv id at once.

``citationCount`` is provider-specific and time-sensitive. It is stored as an
observation with the provider and the retrieval time attached, never merged into
a single number and never used as a ranking or quality signal.

``publicationTypes`` is a list, so a record can be both a journal article and a
review. The mapping resolves that with a fixed precedence -- the most specific
publication form wins -- rather than taking whichever element came first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import Field, ValidationError

from src.research.academic.client import JsonHttpClient
from src.research.academic.credentials import (
    SEMANTIC_SCHOLAR_API_KEY_ENV,
    read_api_key,
)
from src.research.academic.http import DEFAULT_RETRY_POLICY, RetryPolicy, Sleeper
from src.research.academic.identifiers import (
    doi_url,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmid,
    normalize_semantic_scholar_id,
    normalize_url,
)
from src.research.academic.normalization import (
    NormalizedResponse,
    build_identifiers,
    candidate_base,
    clean_count,
    clean_date,
    clean_flag,
    clean_text,
    clean_year,
    drop_within_provider_duplicates,
    raw_metadata,
    rejection,
)
from src.research.academic.provider import BaseAcademicProvider
from src.schemas.academic import (
    AcademicProvider,
    AcademicRejectionReason,
    AcademicSearchQuery,
    AcademicSourceCandidate,
    AcademicSourceType,
    ProviderFacingModel,
)

SEMANTIC_SCHOLAR_CONNECTOR_VERSION = "SEMANTIC-SCHOLAR-CONNECTOR-V1"
SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_SEARCH_PATH = "paper/search"

SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,externalIds,title,abstract,authors,year,venue,publicationVenue,"
    "publicationTypes,publicationDate,citationCount,url,isOpenAccess"
)

SEMANTIC_SCHOLAR_TYPES: dict[str, AcademicSourceType] = {
    "metaanalysis": AcademicSourceType.META_ANALYSIS,
    "review": AcademicSourceType.REVIEW,
    "conference": AcademicSourceType.CONFERENCE_PAPER,
    "journalarticle": AcademicSourceType.JOURNAL_ARTICLE,
    "book": AcademicSourceType.BOOK_CHAPTER,
    "booksection": AcademicSourceType.BOOK_CHAPTER,
    "thesis": AcademicSourceType.THESIS,
    "dataset": AcademicSourceType.DATASET,
}

SOURCE_TYPE_PRECEDENCE: tuple[AcademicSourceType, ...] = (
    AcademicSourceType.SYSTEMATIC_REVIEW,
    AcademicSourceType.META_ANALYSIS,
    AcademicSourceType.REVIEW,
    AcademicSourceType.CONFERENCE_PAPER,
    AcademicSourceType.JOURNAL_ARTICLE,
    AcademicSourceType.BOOK_CHAPTER,
    AcademicSourceType.THESIS,
    AcademicSourceType.DATASET,
    AcademicSourceType.PREPRINT,
    AcademicSourceType.OTHER_ACADEMIC,
)
"""Most specific publication form first. Applied when a record declares several."""


# ---------------------------------------------------------------------------
# Provider DTOs -- untrusted boundary
# ---------------------------------------------------------------------------


class SemanticScholarAuthor(ProviderFacingModel):
    name: str | None = None


class SemanticScholarVenue(ProviderFacingModel):
    name: str | None = None
    publisher: str | None = None


class SemanticScholarPaper(ProviderFacingModel):
    paperId: str | None = None  # noqa: N815 -- the provider's own spelling
    externalIds: dict[str, Any] = Field(default_factory=dict)  # noqa: N815
    title: str | None = None
    abstract: str | None = None
    authors: list[Any] = Field(default_factory=list)
    year: Any = None
    venue: str | None = None
    publicationVenue: SemanticScholarVenue | None = None  # noqa: N815
    publicationTypes: list[Any] | None = None  # noqa: N815
    publicationDate: Any = None  # noqa: N815
    citationCount: Any = None  # noqa: N815
    url: str | None = None
    isOpenAccess: Any = None  # noqa: N815


class SemanticScholarSearchResponse(ProviderFacingModel):
    data: list[Any] = Field(default_factory=list)
    total: Any = None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _source_type(paper: SemanticScholarPaper) -> AcademicSourceType:
    """The most specific declared publication form, or UNKNOWN.

    Nothing is inferred from the venue string or from the presence of an arXiv
    id: a paper can hold an arXiv preprint *and* a journal publication, and
    calling the record a preprint on that basis would be a guess.
    """
    declared = {
        SEMANTIC_SCHOLAR_TYPES[key]
        for key in (
            str(value).strip().casefold().replace("-", "").replace(" ", "")
            for value in (paper.publicationTypes or [])
        )
        if key in SEMANTIC_SCHOLAR_TYPES
    }
    for source_type in SOURCE_TYPE_PRECEDENCE:
        if source_type in declared:
            return source_type
    return AcademicSourceType.UNKNOWN


def _authors(paper: SemanticScholarPaper) -> list[str]:
    names: list[str] = []
    for entry in paper.authors:
        try:
            author = SemanticScholarAuthor.model_validate(entry)
        except ValidationError:
            continue
        name = clean_text(author.name)
        if name:
            names.append(name)
    return names


def normalize_semantic_scholar_response(
    query: AcademicSearchQuery, payload: Any, *, retrieved_at: datetime
) -> NormalizedResponse:
    """Semantic Scholar JSON to candidates. One bad record is one rejection."""
    try:
        envelope = SemanticScholarSearchResponse.model_validate(payload)
    except ValidationError:
        return NormalizedResponse(
            raw_count=1,
            rejected=[
                rejection(
                    query,
                    AcademicRejectionReason.MALFORMED_RECORD,
                    summary="response envelope did not match the Semantic Scholar contract",
                )
            ],
        )

    response = NormalizedResponse(raw_count=len(envelope.data))
    for rank, record in enumerate(envelope.data):
        try:
            paper = SemanticScholarPaper.model_validate(record)
        except ValidationError:
            response.rejected.append(
                rejection(query, AcademicRejectionReason.MALFORMED_RECORD)
            )
            continue

        title = clean_text(paper.title)
        if not title:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.MISSING_TITLE,
                    record_id=paper.paperId,
                )
            )
            continue

        external = {str(k).strip().casefold(): v for k, v in paper.externalIds.items()}
        identifiers, invalid = build_identifiers(
            {
                "doi": normalize_doi(external.get("doi")),
                "pmid": normalize_pmid(external.get("pubmed")),
                "semantic_scholar_id": normalize_semantic_scholar_id(paper.paperId),
                "arxiv_id": normalize_arxiv_id(external.get("arxiv")),
            }
        )
        if invalid is not None:
            response.rejected.append(
                rejection(query, invalid, record_id=paper.paperId, summary=title)
            )
            continue

        year, bad_year = clean_year(paper.year)
        if bad_year:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.INVALID_PUBLICATION_YEAR,
                    record_id=paper.paperId,
                    summary=title,
                )
            )
            continue

        url = normalize_url(paper.url)
        if url.invalid:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.INVALID_URL,
                    record_id=paper.paperId,
                    summary=title,
                )
            )
            continue

        if identifiers.is_empty and not url.value:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.MISSING_IDENTIFIER,
                    record_id=paper.paperId,
                    summary=title,
                )
            )
            continue

        venue = paper.publicationVenue or SemanticScholarVenue()
        response.candidates.append(
            AcademicSourceCandidate(
                **candidate_base(query, retrieved_at),
                source_type=_source_type(paper),
                publication_type=clean_text(
                    ", ".join(str(t) for t in (paper.publicationTypes or []))
                ),
                title=title,
                abstract=clean_text(paper.abstract),
                authors=_authors(paper),
                publication_year=year,
                publication_date=clean_date(paper.publicationDate),
                venue=clean_text(paper.venue or venue.name),
                publisher=clean_text(venue.publisher),
                identifiers=identifiers,
                canonical_url=doi_url(identifiers.doi) if identifiers.doi else url.value,
                provider_url=url.value,
                citation_count=clean_count(paper.citationCount),
                is_open_access=clean_flag(paper.isOpenAccess),
                provider_rank=rank,
                provider_record_id=clean_text(paper.paperId),
                raw_provider_metadata=raw_metadata(record),
            )
        )

    response.candidates, duplicates = drop_within_provider_duplicates(
        query, response.candidates
    )
    response.rejected.extend(duplicates)
    return response


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class SemanticScholarProvider(BaseAcademicProvider):
    """Live Semantic Scholar connector. Used only by explicit opt-in.

    The API key is optional: the public endpoint works without one at a lower
    rate limit. When present it is read from ``SEMANTIC_SCHOLAR_API_KEY``, held
    privately, and sent as a header -- never logged, stored or serialized.
    """

    provider_name: ClassVar[AcademicProvider] = AcademicProvider.SEMANTIC_SCHOLAR
    connector_version: ClassVar[str] = SEMANTIC_SCHOLAR_CONNECTOR_VERSION

    def __init__(
        self,
        *,
        client: Any | None = None,
        base_url: str = SEMANTIC_SCHOLAR_BASE_URL,
        timeout_seconds: float = 15.0,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy, sleeper=sleeper)
        self._api_key = read_api_key(SEMANTIC_SCHOLAR_API_KEY_ENV)
        self._http = JsonHttpClient(
            base_url,
            client=client,
            timeout_seconds=timeout_seconds,
            headers={"x-api-key": self._api_key} if self._api_key else {},
        )

    @property
    def has_credentials(self) -> bool:
        """Whether a key is configured. Never exposes the key itself."""
        return self._api_key is not None

    def _fetch(self, query: AcademicSearchQuery, limit: int) -> Any:
        return self._http.get_json(
            SEMANTIC_SCHOLAR_SEARCH_PATH,
            {"query": query.query, "limit": limit, "fields": SEMANTIC_SCHOLAR_FIELDS},
        )

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_semantic_scholar_response(
            query, payload, retrieved_at=retrieved_at
        )


__all__ = [
    "SEMANTIC_SCHOLAR_BASE_URL",
    "SEMANTIC_SCHOLAR_CONNECTOR_VERSION",
    "SEMANTIC_SCHOLAR_FIELDS",
    "SEMANTIC_SCHOLAR_SEARCH_PATH",
    "SEMANTIC_SCHOLAR_TYPES",
    "SemanticScholarPaper",
    "SemanticScholarProvider",
    "SemanticScholarSearchResponse",
    "normalize_semantic_scholar_response",
]
