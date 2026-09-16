"""Deterministic normalization of academic identifiers.

Every identifier a provider returns is reduced to one canonical spelling before
anything compares, deduplicates or stores it. Normalization is purely
syntactic -- prefix stripping, case folding, a format check -- and nothing here
ever derives an identifier from a title, an author list or a URL guess. An
identifier that does not match its canonical format is *invalid*, which is a
different fact from *absent*, and the two are reported separately so the
rejection ledger can say which happened.

The canonical spellings:

    DOI                  10.1234/abcd            lowercase, no resolver prefix
    PMID                 32123456                digits only
    OpenAlex work id     w2741809807             lowercase ``w`` + digits
    Semantic Scholar id  40 hex chars, or corpusid:<digits>
    arXiv id             2103.00020 / cs.lg/0309136   version suffix removed
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.schemas.academic import (
    ARXIV_ID_PATTERN,
    DOI_PATTERN,
    OPENALEX_ID_PATTERN,
    PMID_PATTERN,
    SEMANTIC_SCHOLAR_ID_PATTERN,
)
from src.schemas.source import canonicalize_web_url

ACADEMIC_IDENTIFIER_VERSION = "ACADEMIC-IDENTIFIERS-V1"

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://www.doi.org/",
    "doi.org/",
    "dx.doi.org/",
    "doi:",
    "doi ",
    "info:doi/",
)

_ARXIV_PREFIXES = (
    "https://arxiv.org/abs/",
    "http://arxiv.org/abs/",
    "https://arxiv.org/pdf/",
    "http://arxiv.org/pdf/",
    "arxiv.org/abs/",
    "arxiv:",
    "arxiv ",
)

_PMID_PREFIXES = (
    "https://pubmed.ncbi.nlm.nih.gov/",
    "http://pubmed.ncbi.nlm.nih.gov/",
    "https://www.ncbi.nlm.nih.gov/pubmed/",
    "pubmed:",
    "pmid:",
    "pmid ",
)

_OPENALEX_PREFIXES = (
    "https://openalex.org/",
    "http://openalex.org/",
    "https://api.openalex.org/works/",
    "http://api.openalex.org/works/",
    "openalex:",
)

_SEMANTIC_SCHOLAR_PREFIXES = (
    "https://www.semanticscholar.org/paper/",
    "https://api.semanticscholar.org/graph/v1/paper/",
    "https://api.semanticscholar.org/",
)

_ARXIV_VERSION = re.compile(r"v\d+$")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class NormalizedIdentifier:
    """The outcome of normalizing one identifier.

    ``provided`` records that the provider said *something*, which is what makes
    "the provider gave us a broken DOI" distinguishable from "the provider gave
    us no DOI". Only the first is a rejection.
    """

    value: str | None = None
    provided: bool = False

    @property
    def invalid(self) -> bool:
        return self.provided and self.value is None


ABSENT = NormalizedIdentifier()


def _prepare(raw: object, prefixes: tuple[str, ...]) -> tuple[str, bool]:
    """Fold, strip known prefixes, and report whether anything was supplied."""
    if raw is None:
        return "", False
    text = str(raw).strip()
    if not text:
        return "", False
    folded = text.casefold()
    for prefix in prefixes:
        if folded.startswith(prefix):
            folded = folded[len(prefix) :]
            break
    return folded.strip().strip("/"), True


def _checked(value: str, provided: bool, pattern: str) -> NormalizedIdentifier:
    if not provided:
        return ABSENT
    return NormalizedIdentifier(
        value=value if re.fullmatch(pattern, value) else None, provided=True
    )


def normalize_doi(raw: object) -> NormalizedIdentifier:
    """``https://doi.org/10.X/AB``, ``doi:10.X/AB`` and ``10.x/ab`` all agree."""
    value, provided = _prepare(raw, _DOI_PREFIXES)
    # A DOI legitimately contains slashes, so only a trailing one is noise.
    return _checked(value, provided, DOI_PATTERN)


def normalize_pmid(raw: object) -> NormalizedIdentifier:
    value, provided = _prepare(raw, _PMID_PREFIXES)
    return _checked(value, provided, PMID_PATTERN)


def normalize_openalex_id(raw: object) -> NormalizedIdentifier:
    value, provided = _prepare(raw, _OPENALEX_PREFIXES)
    return _checked(value, provided, OPENALEX_ID_PATTERN)


def normalize_semantic_scholar_id(raw: object) -> NormalizedIdentifier:
    """The 40-character paper id, or the ``corpusid:<digits>`` form."""
    value, provided = _prepare(raw, _SEMANTIC_SCHOLAR_PREFIXES)
    value = value.replace("corpus_id:", "corpusid:").replace("corpusid: ", "corpusid:")
    return _checked(value, provided, SEMANTIC_SCHOLAR_ID_PATTERN)


def normalize_arxiv_id(raw: object) -> NormalizedIdentifier:
    """Canonical arXiv id with the version suffix removed.

    ``2103.00020v2`` and ``2103.00020`` are the same work at two revisions. This
    project deduplicates the work, so the version is dropped from the identity;
    the provider's original string stays in ``raw_provider_metadata``.
    """
    value, provided = _prepare(raw, _ARXIV_PREFIXES)
    if value.endswith(".pdf"):
        value = value[: -len(".pdf")]
    value = _ARXIV_VERSION.sub("", value)
    return _checked(value, provided, ARXIV_ID_PATTERN)


def normalize_url(raw: object) -> NormalizedIdentifier:
    """Canonicalize an http(s) URL. Any other scheme is invalid, not absent."""
    if raw is None:
        return ABSENT
    text = str(raw).strip()
    if not text:
        return ABSENT
    parts = urlsplit(text)
    if parts.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parts.hostname:
        return NormalizedIdentifier(value=None, provided=True)
    return NormalizedIdentifier(value=canonicalize_web_url(text), provided=True)


def doi_url(doi: str) -> str:
    """The canonical resolver URL for a DOI. Derived, never invented."""
    return f"https://doi.org/{doi}"


__all__ = [
    "ABSENT",
    "ACADEMIC_IDENTIFIER_VERSION",
    "NormalizedIdentifier",
    "doi_url",
    "normalize_arxiv_id",
    "normalize_doi",
    "normalize_openalex_id",
    "normalize_pmid",
    "normalize_semantic_scholar_id",
    "normalize_url",
]
