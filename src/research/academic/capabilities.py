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

from src.research.academic.consensus import CONSENSUS_CONNECTOR_VERSION
from src.research.academic.credentials import (
    CONSENSUS_API_KEY_ENV,
    SEMANTIC_SCHOLAR_API_KEY_ENV,
)
from src.research.academic.openalex import OPENALEX_CONNECTOR_VERSION
from src.research.academic.semantic_scholar import SEMANTIC_SCHOLAR_CONNECTOR_VERSION
from src.schemas.academic import AcademicProvider


@dataclass(frozen=True)
class ProviderCapability:
    """What one connector reads and requires. Plain data, never checkpointed."""

    provider: AcademicProvider
    connector_version: str
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
    api_key_env=CONSENSUS_API_KEY_ENV,
    api_key_required=True,
    identifiers=("doi",),
    supplies_abstract=True,
    supplies_citation_count=True,
    supplies_open_access=True,
    supplies_retraction_status=False,
    supplies_publication_type=True,
    supplies_publication_date=True,
    supplies_relevance_score=True,
    notes="Synthesized text and relevance are provider-generated secondary "
    "metadata; they never become the paper's abstract or evidence.",
    known_limitations=(
        "No OpenAlex, Semantic Scholar, PubMed or arXiv identifier, so a record "
        "without a DOI can only be deduplicated on its canonical URL.",
        "Study type describes methodology, not publication form; only the review "
        "family is mapped to a source type.",
        "Retraction status is not exposed, so it stays None rather than False.",
    ),
)

OPENALEX_CAPABILITY = ProviderCapability(
    provider=AcademicProvider.OPENALEX,
    connector_version=OPENALEX_CONNECTOR_VERSION,
    api_key_env=None,
    api_key_required=False,
    identifiers=("doi", "pmid", "openalex_id", "arxiv_id"),
    supplies_abstract=True,
    supplies_citation_count=True,
    supplies_open_access=True,
    supplies_retraction_status=True,
    supplies_publication_type=True,
    supplies_publication_date=True,
    supplies_relevance_score=False,
    notes="Keyless. The only implemented provider that states retraction status "
    "explicitly, so it is the only one that can report is_retracted=False.",
    known_limitations=(
        "The abstract arrives as an inverted index and is reconstructed by word "
        "position; a gap in the positions stays a gap.",
        "No relevance score is exposed, so provider_relevance stays None.",
    ),
)

SEMANTIC_SCHOLAR_CAPABILITY = ProviderCapability(
    provider=AcademicProvider.SEMANTIC_SCHOLAR,
    connector_version=SEMANTIC_SCHOLAR_CONNECTOR_VERSION,
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
]
