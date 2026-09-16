"""The OpenAlex connector.

OpenAlex is an open bibliographic catalogue. Everything it returns is
bibliographic metadata about a work -- catalogue coverage is not peer review,
and a high ``cited_by_count`` is not quality (section 42).

Two OpenAlex specifics are worth naming:

* **The abstract arrives inverted.** ``abstract_inverted_index`` maps each word
  to its positions; reconstruction is a deterministic re-ordering of words the
  provider supplied, not a paraphrase.
* **Retraction is explicit.** ``is_retracted`` is a real boolean, so this is the
  one provider that can answer the retraction question with ``False`` rather
  than leaving it unknown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import AliasChoices, Field, ValidationError

from src.research.academic.client import JsonHttpClient
from src.research.academic.credentials import read_contact_email
from src.research.academic.http import DEFAULT_RETRY_POLICY, RetryPolicy, Sleeper
from src.research.academic.identifiers import (
    doi_url,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_pmid,
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

OPENALEX_CONNECTOR_VERSION = "OPENALEX-CONNECTOR-V1"
OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_SEARCH_PATH = "works"

OPENALEX_WORK_TYPES: dict[str, AcademicSourceType] = {
    "article": AcademicSourceType.JOURNAL_ARTICLE,
    "journal-article": AcademicSourceType.JOURNAL_ARTICLE,
    "proceedings-article": AcademicSourceType.CONFERENCE_PAPER,
    "review": AcademicSourceType.REVIEW,
    "preprint": AcademicSourceType.PREPRINT,
    "book-chapter": AcademicSourceType.BOOK_CHAPTER,
    "dissertation": AcademicSourceType.THESIS,
    "dataset": AcademicSourceType.DATASET,
    "report": AcademicSourceType.OTHER_ACADEMIC,
    "book": AcademicSourceType.OTHER_ACADEMIC,
}

MAX_ABSTRACT_WORDS = 4000
"""An inverted index is attacker-influenced input; reconstruction stays bounded."""


# ---------------------------------------------------------------------------
# Provider DTOs -- untrusted boundary
# ---------------------------------------------------------------------------


class OpenAlexSource(ProviderFacingModel):
    display_name: str | None = None
    host_organization_name: str | None = None
    type: str | None = None


class OpenAlexLocation(ProviderFacingModel):
    source: OpenAlexSource | None = None
    landing_page_url: str | None = None
    version: str | None = None


class OpenAlexAuthor(ProviderFacingModel):
    display_name: str | None = None


class OpenAlexAuthorship(ProviderFacingModel):
    author: OpenAlexAuthor | None = None


class OpenAlexOpenAccess(ProviderFacingModel):
    is_oa: Any = None


class OpenAlexWork(ProviderFacingModel):
    id: str | None = None
    doi: str | None = None
    ids: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(
        default=None, validation_alias=AliasChoices("title", "display_name")
    )
    publication_year: Any = None
    publication_date: Any = None
    type: str | None = None
    type_crossref: str | None = None
    cited_by_count: Any = None
    is_retracted: Any = None
    is_paratext: Any = None
    open_access: OpenAlexOpenAccess | None = None
    primary_location: OpenAlexLocation | None = None
    authorships: list[Any] = Field(default_factory=list)
    abstract_inverted_index: dict[str, Any] | None = None


class OpenAlexSearchResponse(ProviderFacingModel):
    results: list[Any] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def reconstruct_abstract(inverted: dict[str, Any] | None) -> str | None:
    """Rebuild an abstract from OpenAlex's inverted index.

    Deterministic and lossless in word order: every word comes from the
    provider, placed at the position the provider gave it. A gap in the
    positions leaves a gap; nothing is invented to fill it.
    """
    if not inverted:
        return None
    placed: dict[int, str] = {}
    for word, positions in inverted.items():
        if not isinstance(positions, (list, tuple)):
            continue
        for position in positions:
            if isinstance(position, int) and 0 <= position < MAX_ABSTRACT_WORDS:
                placed[position] = str(word)
    if not placed:
        return None
    return clean_text(" ".join(placed[index] for index in sorted(placed)))


def _source_type(work: OpenAlexWork) -> AcademicSourceType:
    for declared in (work.type, work.type_crossref):
        mapped = OPENALEX_WORK_TYPES.get((declared or "").strip().casefold())
        if mapped is not None:
            return mapped
    return AcademicSourceType.UNKNOWN


def _authors(work: OpenAlexWork) -> list[str]:
    names: list[str] = []
    for entry in work.authorships:
        try:
            authorship = OpenAlexAuthorship.model_validate(entry)
        except ValidationError:
            continue
        name = clean_text(authorship.author.display_name if authorship.author else None)
        if name:
            names.append(name)
    return names


def normalize_openalex_response(
    query: AcademicSearchQuery, payload: Any, *, retrieved_at: datetime
) -> NormalizedResponse:
    """OpenAlex JSON to canonical candidates. One bad record is one rejection."""
    try:
        envelope = OpenAlexSearchResponse.model_validate(payload)
    except ValidationError:
        return NormalizedResponse(
            raw_count=1,
            rejected=[
                rejection(
                    query,
                    AcademicRejectionReason.MALFORMED_RECORD,
                    summary="response envelope did not match the OpenAlex contract",
                )
            ],
        )

    response = NormalizedResponse(raw_count=len(envelope.results))
    for rank, record in enumerate(envelope.results):
        try:
            work = OpenAlexWork.model_validate(record)
        except ValidationError:
            response.rejected.append(
                rejection(query, AcademicRejectionReason.MALFORMED_RECORD)
            )
            continue

        title = clean_text(work.title)
        if not title:
            response.rejected.append(
                rejection(query, AcademicRejectionReason.MISSING_TITLE, record_id=work.id)
            )
            continue

        identifiers, invalid = build_identifiers(
            {
                "doi": normalize_doi(work.doi or work.ids.get("doi")),
                "pmid": normalize_pmid(work.ids.get("pmid")),
                "openalex_id": normalize_openalex_id(work.id or work.ids.get("openalex")),
                "arxiv_id": normalize_arxiv_id(work.ids.get("arxiv")),
            }
        )
        if invalid is not None:
            response.rejected.append(
                rejection(query, invalid, record_id=work.id, summary=title)
            )
            continue

        year, bad_year = clean_year(work.publication_year)
        if bad_year:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.INVALID_PUBLICATION_YEAR,
                    record_id=work.id,
                    summary=title,
                )
            )
            continue

        location = work.primary_location or OpenAlexLocation()
        url = normalize_url(location.landing_page_url)
        if url.invalid:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.INVALID_URL,
                    record_id=work.id,
                    summary=title,
                )
            )
            continue

        if identifiers.is_empty and not url.value:
            response.rejected.append(
                rejection(
                    query,
                    AcademicRejectionReason.MISSING_IDENTIFIER,
                    record_id=work.id,
                    summary=title,
                )
            )
            continue

        response.candidates.append(
            AcademicSourceCandidate(
                **candidate_base(query, retrieved_at),
                source_type=_source_type(work),
                publication_type=clean_text(work.type),
                title=title,
                abstract=reconstruct_abstract(work.abstract_inverted_index),
                authors=_authors(work),
                publication_year=year,
                publication_date=clean_date(work.publication_date),
                venue=clean_text(location.source.display_name if location.source else None),
                publisher=clean_text(
                    location.source.host_organization_name if location.source else None
                ),
                identifiers=identifiers,
                canonical_url=doi_url(identifiers.doi) if identifiers.doi else url.value,
                provider_url=url.value,
                citation_count=clean_count(work.cited_by_count),
                is_open_access=clean_flag(
                    work.open_access.is_oa if work.open_access else None
                ),
                is_retracted=clean_flag(work.is_retracted),
                provider_rank=rank,
                provider_record_id=clean_text(work.id),
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


class OpenAlexProvider(BaseAcademicProvider):
    """Live OpenAlex connector. Keyless; used only by explicit opt-in."""

    provider_name: ClassVar[AcademicProvider] = AcademicProvider.OPENALEX
    connector_version: ClassVar[str] = OPENALEX_CONNECTOR_VERSION

    def __init__(
        self,
        *,
        client: Any | None = None,
        base_url: str = OPENALEX_BASE_URL,
        timeout_seconds: float = 15.0,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy, sleeper=sleeper)
        # A contact address is configuration, not a credential: OpenAlex uses it
        # to route requests to its polite pool.
        self._contact_email = read_contact_email()
        self._http = JsonHttpClient(base_url, client=client, timeout_seconds=timeout_seconds)

    def _fetch(self, query: AcademicSearchQuery, limit: int) -> Any:
        params: dict[str, Any] = {"search": query.query, "per-page": limit}
        if self._contact_email:
            params["mailto"] = self._contact_email
        return self._http.get_json(OPENALEX_SEARCH_PATH, params)

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_openalex_response(query, payload, retrieved_at=retrieved_at)


__all__ = [
    "MAX_ABSTRACT_WORDS",
    "OPENALEX_BASE_URL",
    "OPENALEX_CONNECTOR_VERSION",
    "OPENALEX_SEARCH_PATH",
    "OPENALEX_WORK_TYPES",
    "OpenAlexProvider",
    "OpenAlexSearchResponse",
    "OpenAlexWork",
    "normalize_openalex_response",
    "reconstruct_abstract",
]
