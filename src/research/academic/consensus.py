"""The Consensus connector.

Consensus is a research search engine over scientific papers. It returns
bibliographic records and, depending on the endpoint, synthesized text of its
own. This connector keeps those apart absolutely:

* the paper's own metadata becomes an ``AcademicSourceCandidate``;
* anything Consensus generated -- a one-line claim summary, a consensus meter, a
  relevance score -- is **provider-generated secondary metadata**. It is kept in
  ``raw_provider_metadata`` and in ``provider_relevance``, and it is never
  written into ``abstract``, never treated as the paper's own words, and never
  evidence (ADR-010).

Study design is likewise not publication form. Consensus reports things like
"RCT" and "cohort"; only the review family maps onto ``AcademicSourceType``,
because a randomized trial can be published as a journal article, a conference
paper or a preprint, and guessing which would invent metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import AliasChoices, Field, ValidationError

from src.research.academic.client import JsonHttpClient
from src.research.academic.credentials import CONSENSUS_API_KEY_ENV, read_api_key
from src.research.academic.http import (
    DEFAULT_RETRY_POLICY,
    AcademicTransportError,
    RetryPolicy,
    Sleeper,
)
from src.research.academic.identifiers import doi_url, normalize_doi, normalize_url
from src.research.academic.normalization import (
    NormalizedResponse,
    build_identifiers,
    candidate_base,
    clean_authors,
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
    AcademicErrorKind,
    AcademicProvider,
    AcademicRejectionReason,
    AcademicSearchQuery,
    AcademicSourceCandidate,
    AcademicSourceType,
    ProviderFacingModel,
)

CONSENSUS_CONNECTOR_VERSION = "CONSENSUS-CONNECTOR-V3"
CONSENSUS_BASE_URL = "https://api.consensus.app"
CONSENSUS_SEARCH_PATH = "v1/search"
"""The current search endpoint. ``v1/quick_search`` is deprecated upstream
(removal announced for 2027-02-07) and is deliberately not used."""

CONSENSUS_API_KEY_HEADER = "x-api-key"
"""The REST authentication header, and the only scheme the API defines.

Confirmed by two agreeing provider-owned sources on 2026-09-16: the published
OpenAPI 3.1.0 definition, whose sole security scheme is
``XApiKeyHeader`` (``apiKey`` / ``header`` / ``x-api-key``) and which applies it
to ``GET /v1/search``; and the official Get Started page, which states that
every request must include the key in the ``x-api-key`` header. Neither source
mentions ``Authorization`` or ``Bearer`` anywhere. Consensus's MCP server is a
separate product surface and says nothing about this header in either
direction, so nothing about REST authentication is inferred from it.
"""

CONSENSUS_QUERY_PARAM = "query"
CONSENSUS_PAGE_SIZE_PARAM = "page_size"
CONSENSUS_MAX_PAGE_SIZE = 1000
"""The absolute ceiling a single page can reach.

The API documents two separate limits: a query returns at most 1000 results in
total (``(page + 1) * page_size <= 1000``), and the effective per-page maximum
is **plan-dependent** and capped server-side, echoed back as ``page_size`` in
the response. This constant is therefore an upper bound that stops a
misconfiguration, not a promise about any one plan. The configured budget sits
far below it, so it is never the binding constraint.
"""

CONSENSUS_CONTRACT_REVIEWED_ON = "2026-09-16"

CONSENSUS_STUDY_TYPES: dict[str, AcademicSourceType] = {
    "systematic review": AcademicSourceType.SYSTEMATIC_REVIEW,
    "systematic-review": AcademicSourceType.SYSTEMATIC_REVIEW,
    "meta-analysis": AcademicSourceType.META_ANALYSIS,
    "meta analysis": AcademicSourceType.META_ANALYSIS,
    "literature review": AcademicSourceType.REVIEW,
    "review": AcademicSourceType.REVIEW,
}
"""The only study types that are also publication forms."""

CONSENSUS_PUBLICATION_TYPES: dict[str, AcademicSourceType] = {
    "journal article": AcademicSourceType.JOURNAL_ARTICLE,
    "journal-article": AcademicSourceType.JOURNAL_ARTICLE,
    "conference paper": AcademicSourceType.CONFERENCE_PAPER,
    "conference-paper": AcademicSourceType.CONFERENCE_PAPER,
    "proceedings": AcademicSourceType.CONFERENCE_PAPER,
    "preprint": AcademicSourceType.PREPRINT,
    "book chapter": AcademicSourceType.BOOK_CHAPTER,
    "thesis": AcademicSourceType.THESIS,
    "dataset": AcademicSourceType.DATASET,
}


# ---------------------------------------------------------------------------
# Provider DTOs -- untrusted boundary
# ---------------------------------------------------------------------------


class ConsensusPaper(ProviderFacingModel):
    """One record of a Consensus search response.

    Loosely typed where this project does its own cleaning (year, counts,
    flags), so a malformed value produces a *named* rejection rather than a
    schema error that says only "the record was broken".
    """

    paper_id: str | None = Field(
        default=None, validation_alias=AliasChoices("paper_id", "id")
    )
    title: str | None = None
    abstract: str | None = None
    authors: list[Any] = Field(default_factory=list)
    publish_year: Any = Field(
        default=None, validation_alias=AliasChoices("publish_year", "year")
    )
    publish_date: Any = Field(
        default=None, validation_alias=AliasChoices("publish_date", "publication_date")
    )
    journal_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("journal_name", "journal", "venue"),
    )
    publisher_name: str | None = Field(
        default=None, validation_alias=AliasChoices("publisher_name", "publisher")
    )
    doi: str | None = None
    url: str | None = None
    citation_count: Any = Field(
        default=None, validation_alias=AliasChoices("citation_count", "citations")
    )
    is_open_access: Any = None
    is_retracted: Any = None
    study_type: str | None = None
    publication_type: str | None = None
    semantic_score: Any = Field(
        default=None, validation_alias=AliasChoices("semantic_score", "relevance_score")
    )
    takeaway: str | None = Field(
        default=None,
        validation_alias=AliasChoices("takeaway", "consensus_summary", "claim", "summary"),
        description="Consensus's own one-line synthesis of the paper. "
        "Provider-generated secondary metadata: never the paper's abstract, "
        "never the paper's own words, and never evidence (ADR-010).",
    )


class ConsensusSearchResponse(ProviderFacingModel):
    """The envelope. Records stay raw so each one can be validated on its own.

    ``results`` is the documented field; the other spellings are tolerated
    aliases rather than assumptions, so a rename upstream degrades to an empty
    page instead of a crash. Pagination fields are declared because the response
    echoes them; Phase 2B requests a single page and does not follow ``next_page``.
    """

    results: list[Any] = Field(
        default_factory=list,
        validation_alias=AliasChoices("results", "papers", "data"),
    )
    page: Any = None
    page_size: Any = None
    is_end: Any = None
    next_page: Any = None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _source_type(paper: ConsensusPaper) -> AcademicSourceType:
    declared = (paper.publication_type or "").strip().casefold()
    if declared in CONSENSUS_PUBLICATION_TYPES:
        return CONSENSUS_PUBLICATION_TYPES[declared]
    study = (paper.study_type or "").strip().casefold()
    return CONSENSUS_STUDY_TYPES.get(study, AcademicSourceType.UNKNOWN)


def _relevance(value: Any) -> float | None:
    """Consensus's own ranking signal, kept only as retrieval metadata.

    Returned only when ``include_semantic_score`` is requested, which this
    connector does not send, so in practice it stays ``None``. Read anyway, so a
    caller that enables it later gets it recorded rather than dropped.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if 0.0 <= score <= 1.0 else None


def normalize_consensus_response(
    query: AcademicSearchQuery, payload: Any, *, retrieved_at: datetime
) -> NormalizedResponse:
    """Consensus JSON to canonical candidates. One bad record is one rejection."""
    try:
        envelope = ConsensusSearchResponse.model_validate(payload)
    except ValidationError:
        return NormalizedResponse(
            raw_count=1,
            rejected=[
                rejection(
                    query,
                    AcademicRejectionReason.MALFORMED_RECORD,
                    summary="response envelope did not match the Consensus contract",
                )
            ],
        )

    response = NormalizedResponse(raw_count=len(envelope.results))
    for rank, record in enumerate(envelope.results):
        try:
            paper = ConsensusPaper.model_validate(record)
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
                    record_id=paper.paper_id,
                )
            )
            continue

        identifiers, invalid = build_identifiers({"doi": normalize_doi(paper.doi)})
        if invalid is not None:
            response.rejected.append(
                rejection(query, invalid, record_id=paper.paper_id, summary=title)
            )
            continue

        year, bad_year = clean_year(paper.publish_year)
        if bad_year:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.INVALID_PUBLICATION_YEAR,
                    record_id=paper.paper_id,
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
                    record_id=paper.paper_id,
                    summary=title,
                )
            )
            continue

        if identifiers.is_empty and not url.value:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.MISSING_IDENTIFIER,
                    record_id=paper.paper_id,
                    summary=title,
                )
            )
            continue

        response.candidates.append(
            AcademicSourceCandidate(
                **candidate_base(query, retrieved_at),
                source_type=_source_type(paper),
                publication_type=clean_text(paper.publication_type or paper.study_type),
                title=title,
                # The paper's own abstract only. Consensus's synthesized text
                # stays in raw_provider_metadata.
                abstract=clean_text(paper.abstract),
                authors=clean_authors(paper.authors),
                publication_year=year,
                publication_date=clean_date(paper.publish_date),
                venue=clean_text(paper.journal_name),
                publisher=clean_text(paper.publisher_name),
                identifiers=identifiers,
                canonical_url=doi_url(identifiers.doi) if identifiers.doi else url.value,
                provider_url=url.value,
                citation_count=clean_count(paper.citation_count),
                is_open_access=clean_flag(paper.is_open_access),
                is_retracted=clean_flag(paper.is_retracted),
                provider_rank=rank,
                provider_relevance=_relevance(paper.semantic_score),
                provider_record_id=clean_text(paper.paper_id),
                raw_provider_metadata=raw_metadata(record),
            )
        )

    response.candidates, duplicates = drop_within_provider_duplicates(
        query, response.candidates
    )
    response.rejected.extend(duplicates)
    return response


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class ConsensusProvider(BaseAcademicProvider):
    """Live Consensus connector. Used only by explicit opt-in.

    The API key is read from ``CONSENSUS_API_KEY`` at construction and held in a
    private attribute. It is sent as a request header and appears nowhere else --
    not in an error, not in a ledger entry, not on graph state.
    """

    provider_name: ClassVar[AcademicProvider] = AcademicProvider.CONSENSUS
    connector_version: ClassVar[str] = CONSENSUS_CONNECTOR_VERSION

    def __init__(
        self,
        *,
        client: Any | None = None,
        base_url: str = CONSENSUS_BASE_URL,
        timeout_seconds: float = 15.0,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy, sleeper=sleeper)
        self._api_key = read_api_key(CONSENSUS_API_KEY_ENV)
        self._http = JsonHttpClient(
            base_url,
            client=client,
            timeout_seconds=timeout_seconds,
            headers={CONSENSUS_API_KEY_HEADER: self._api_key} if self._api_key else {},
        )

    @property
    def has_credentials(self) -> bool:
        """Whether a key is configured. Never exposes the key itself."""
        return self._api_key is not None

    def _fetch(self, query: AcademicSearchQuery, limit: int) -> Any:
        if self._api_key is None:
            raise AcademicTransportError(
                AcademicErrorKind.AUTH_ERROR,
                f"{CONSENSUS_API_KEY_ENV} is not configured",
            )
        return self._http.get_json(
            CONSENSUS_SEARCH_PATH,
            {
                CONSENSUS_QUERY_PARAM: query.query,
                CONSENSUS_PAGE_SIZE_PARAM: min(limit, CONSENSUS_MAX_PAGE_SIZE),
            },
        )

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_consensus_response(query, payload, retrieved_at=retrieved_at)


__all__ = [
    "CONSENSUS_API_KEY_HEADER",
    "CONSENSUS_BASE_URL",
    "CONSENSUS_CONTRACT_REVIEWED_ON",
    "CONSENSUS_MAX_PAGE_SIZE",
    "CONSENSUS_PAGE_SIZE_PARAM",
    "CONSENSUS_QUERY_PARAM",
    "CONSENSUS_CONNECTOR_VERSION",
    "CONSENSUS_SEARCH_PATH",
    "ConsensusPaper",
    "ConsensusProvider",
    "ConsensusSearchResponse",
    "normalize_consensus_response",
]
