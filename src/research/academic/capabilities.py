"""The provider capability matrix.

What each connector *actually* reads from the API contract it implements, so no
other layer has to assume. The rule this file exists to enforce is section 36:
capability is documented, never assumed. If a provider does not expose
retraction status, the matrix says so and every record from it leaves
``is_retracted`` as ``None`` -- which is not the same as ``False``.

This is a description of the implemented connectors, not a wish list. It changes
when a connector changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.research.academic.consensus import (
    CONSENSUS_API_KEY_HEADER,
    CONSENSUS_BASE_URL,
    CONSENSUS_CONNECTOR_VERSION,
    CONSENSUS_CONTRACT_REVIEWED_ON,
    CONSENSUS_MAX_PAGE_SIZE,
    CONSENSUS_PAGE_SIZE_PARAM,
    CONSENSUS_QUERY_PARAM,
    CONSENSUS_SEARCH_PATH,
)
from src.research.academic.credentials import (
    CONSENSUS_API_KEY_ENV,
    OPENALEX_API_KEY_ENV,
    SEMANTIC_SCHOLAR_API_KEY_ENV,
)
from src.research.academic.openalex import (
    OPENALEX_API_KEY_PARAM,
    OPENALEX_BASE_URL,
    OPENALEX_CONNECTOR_VERSION,
    OPENALEX_CONTRACT_REVIEWED_ON,
    OPENALEX_MAX_PAGE_SIZE,
    OPENALEX_PAGE_SIZE_PARAM,
    OPENALEX_QUERY_PARAM,
    OPENALEX_SEARCH_PATH,
)
from src.research.academic.semantic_scholar import (
    SEMANTIC_SCHOLAR_API_KEY_HEADER,
    SEMANTIC_SCHOLAR_BASE_URL,
    SEMANTIC_SCHOLAR_CONNECTOR_VERSION,
    SEMANTIC_SCHOLAR_CONTRACT_REVIEWED_ON,
    SEMANTIC_SCHOLAR_LIMIT_PARAM,
    SEMANTIC_SCHOLAR_MAX_LIMIT,
    SEMANTIC_SCHOLAR_QUERY_PARAM,
    SEMANTIC_SCHOLAR_SEARCH_PATH,
)
from src.schemas.academic import AcademicProvider


@dataclass(frozen=True)
class ProviderCapability:
    """What one connector reads, requires and sends. Never checkpointed.

    The request fields are taken from the connector's own constants rather than
    restated here, so the documented contract cannot drift away from the request
    the connector actually makes. A test asserts the two agree.
    """

    provider: AcademicProvider
    connector_version: str
    base_url: str
    search_path: str
    http_method: str
    auth_header: str | None
    auth_query_param: str | None
    required_params: tuple[str, ...]
    result_limit_param: str
    max_page_size: int
    response_envelope_key: str
    contract_reviewed_on: str
    api_key_env: str | None
    api_key_required: bool
    identifiers: tuple[str, ...]
    supplies_abstract: bool
    supplies_citation_count: bool
    supplies_open_access: bool
    supplies_retraction_status: bool
    supplies_publication_type: bool
    supplies_publication_date: bool
    supplies_relevance_score: bool
    notes: str = ""
    known_limitations: tuple[str, ...] = field(default_factory=tuple)


CONSENSUS_CAPABILITY = ProviderCapability(
    provider=AcademicProvider.CONSENSUS,
    connector_version=CONSENSUS_CONNECTOR_VERSION,
    base_url=CONSENSUS_BASE_URL,
    search_path=CONSENSUS_SEARCH_PATH,
    http_method="GET",
    auth_header=CONSENSUS_API_KEY_HEADER,
    auth_query_param=None,
    required_params=(CONSENSUS_QUERY_PARAM,),
    result_limit_param=CONSENSUS_PAGE_SIZE_PARAM,
    max_page_size=CONSENSUS_MAX_PAGE_SIZE,
    response_envelope_key="results",
    contract_reviewed_on=CONSENSUS_CONTRACT_REVIEWED_ON,
    api_key_env=CONSENSUS_API_KEY_ENV,
    api_key_required=True,
    identifiers=("doi",),
    supplies_abstract=True,
    supplies_citation_count=True,
    supplies_open_access=False,
    supplies_retraction_status=False,
    supplies_publication_type=False,
    supplies_publication_date=True,
    supplies_relevance_score=False,
    notes="Synthesized text (takeaway) is provider-generated secondary metadata; "
    "it never becomes the paper's abstract or evidence. Verified against the "
    "published QueryResult schema on 2026-09-16.",
    known_limitations=(
        "No OpenAlex, Semantic Scholar, PubMed or arXiv identifier, so a record "
        "without a DOI can only be deduplicated on its canonical URL.",
        "The result record carries no stable paper id, so provider_record_id is "
        "always None for this provider.",
        "Study type describes methodology, not publication form; only the review "
        "family is mapped to a source type.",
        "Retraction status is not exposed, so it stays None rather than False.",
        "Open-access status is a request filter, not a result field, so "
        "is_open_access stays None.",
        "A semantic relevance score exists but only when include_semantic_score "
        "is requested, which this connector does not send.",
        "The record does expose is_preprint. It is deliberately not mapped to a "
        "source type in Phase 2B: that would be new behaviour, not contract "
        "hardening, and is recorded as deferred work.",
    ),
)

OPENALEX_CAPABILITY = ProviderCapability(
    provider=AcademicProvider.OPENALEX,
    connector_version=OPENALEX_CONNECTOR_VERSION,
    base_url=OPENALEX_BASE_URL,
    search_path=OPENALEX_SEARCH_PATH,
    http_method="GET",
    auth_header=None,
    auth_query_param=OPENALEX_API_KEY_PARAM,
    required_params=(OPENALEX_QUERY_PARAM,),
    result_limit_param=OPENALEX_PAGE_SIZE_PARAM,
    max_page_size=OPENALEX_MAX_PAGE_SIZE,
    response_envelope_key="results",
    contract_reviewed_on=OPENALEX_CONTRACT_REVIEWED_ON,
    api_key_env=OPENALEX_API_KEY_ENV,
    api_key_required=False,
    identifiers=("doi", "pmid", "openalex_id", "arxiv_id"),
    supplies_abstract=True,
    supplies_citation_count=True,
    supplies_open_access=True,
    supplies_retraction_status=True,
    supplies_publication_type=True,
    supplies_publication_date=True,
    supplies_relevance_score=False,
    notes="Keyless for the free tier; an optional api_key query parameter raises "
    "the limits. The only implemented provider that states retraction status "
    "explicitly, so the only one that can report is_retracted=False.",
    known_limitations=(
        "The abstract arrives as an inverted index and is reconstructed by word "
        "position; a gap in the positions stays a gap.",
        "No relevance score is exposed, so provider_relevance stays None.",
    ),
)

SEMANTIC_SCHOLAR_CAPABILITY = ProviderCapability(
    provider=AcademicProvider.SEMANTIC_SCHOLAR,
    connector_version=SEMANTIC_SCHOLAR_CONNECTOR_VERSION,
    base_url=SEMANTIC_SCHOLAR_BASE_URL,
    search_path=SEMANTIC_SCHOLAR_SEARCH_PATH,
    http_method="GET",
    auth_header=SEMANTIC_SCHOLAR_API_KEY_HEADER,
    auth_query_param=None,
    required_params=(SEMANTIC_SCHOLAR_QUERY_PARAM,),
    result_limit_param=SEMANTIC_SCHOLAR_LIMIT_PARAM,
    max_page_size=SEMANTIC_SCHOLAR_MAX_LIMIT,
    response_envelope_key="data",
    contract_reviewed_on=SEMANTIC_SCHOLAR_CONTRACT_REVIEWED_ON,
    api_key_env=SEMANTIC_SCHOLAR_API_KEY_ENV,
    api_key_required=False,
    identifiers=("doi", "pmid", "semantic_scholar_id", "arxiv_id"),
    supplies_abstract=True,
    supplies_citation_count=True,
    supplies_open_access=True,
    supplies_retraction_status=False,
    supplies_publication_type=True,
    supplies_publication_date=True,
    supplies_relevance_score=False,
    notes="The key is optional: the public endpoint works without one at a lower "
    "rate limit. Citation counts stay provider-specific and time-stamped.",
    known_limitations=(
        "publicationTypes has no preprint member, so an arXiv paper is not "
        "classified as a preprint on the strength of its arXiv id alone.",
        "Retraction status is not exposed, so it stays None rather than False.",
    ),
)

PROVIDER_CAPABILITIES: dict[AcademicProvider, ProviderCapability] = {
    AcademicProvider.CONSENSUS: CONSENSUS_CAPABILITY,
    AcademicProvider.OPENALEX: OPENALEX_CAPABILITY,
    AcademicProvider.SEMANTIC_SCHOLAR: SEMANTIC_SCHOLAR_CAPABILITY,
}


def search_url(provider: AcademicProvider) -> str:
    """The full search URL a connector calls. Derived, never restated."""
    capability = PROVIDER_CAPABILITIES[provider]
    return f"{capability.base_url.rstrip('/')}/{capability.search_path.lstrip('/')}"


def connector_versions() -> dict[str, str]:
    """Connector versions keyed by provider, recorded on every research run."""
    return {
        provider.value: capability.connector_version
        for provider, capability in PROVIDER_CAPABILITIES.items()
    }


__all__ = [
    "CONSENSUS_CAPABILITY",
    "OPENALEX_CAPABILITY",
    "PROVIDER_CAPABILITIES",
    "SEMANTIC_SCHOLAR_CAPABILITY",
    "ProviderCapability",
    "connector_versions",
    "search_url",
]
