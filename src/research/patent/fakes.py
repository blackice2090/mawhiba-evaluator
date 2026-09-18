"""Deterministic offline patent providers -- Phase 2G section 33.

These are not simplified stand-ins. A fake replaces exactly one thing -- the
HTTP attempt -- and then runs the real OPS XML parser, the real identity rules,
the real within-response duplicate check, the real range limit and the real
envelope assembly. A behaviour that passes here is the behaviour the live
connector has.

Scripting covers what a patent office actually does:

* return an exchange-document list, as OPS XML, so parsing is exercised;
* return nothing, which is ``EMPTY`` and not a failure;
* return malformed XML, or an XML fault envelope;
* fail with a named ``PatentErrorKind``, including a fair-use rejection;
* fail for the first N attempts and then succeed, which is how the bounded
  retry path is tested without a real second passing;
* report a total far larger than the range served, which is how bounded search
  is tested;
* expose or withhold family data, claims, abstract and description per
  authority, which is how honest degradation is tested.

The XML builders here produce documents shaped like the verified OPS contract,
so a fixture cannot drift into a shape the parser would never meet in
production.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from src.research.patent.epo_ops import (
    EPO_OPS_CONNECTOR_VERSION,
    EPO_OPS_FAMILY_OPERATION,
    EPO_OPS_SEARCH_OPERATION,
    ParsedOpsFamily,
    normalize_patent_text,
    parse_ops_family_response,
    parse_ops_search_response,
    build_content_request,
    parse_ops_text_response,
)
from src.research.patent.http import PatentTransportError
from src.research.patent.identity import parse_publication_reference
from src.research.patent.provider import (
    BasePatentProvider,
    FamilyPayload,
    ParsedSearchPayload,
    TextPayload,
    text_operation_for,
)
from src.schemas.patent import (
    RETRYABLE_PATENT_ERROR_KINDS,
    PatentContentType,
    PatentErrorKind,
    PatentFamilyKind,
    PatentProvider,
    PatentProviderError,
    PatentProviderOperation,
    PatentSearchQuery,
    PublicationIdentity,
)

OPS_XML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<ops:world-patent-data xmlns:ops="http://ops.epo.org" '
    'xmlns="http://www.epo.org/exchange">'
)
OPS_XML_FOOTER = "</ops:world-patent-data>"


# ---------------------------------------------------------------------------
# Fixture records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakePatentRecord:
    """One publication as an office would publish it.

    Every field is optional except the reference, so a fixture can model the
    ordinary shortfalls: a record with no publication date, no title, no
    classifications, or a kind code the caller must not lose.
    """

    reference: str
    """A ``EP.1000000.A1``-style DOCDB reference, or a malformed one on purpose."""

    title: str = ""
    title_language: str = "en"
    publication_date: str = ""
    filing_date: str = ""
    priority_date: str = ""
    grant_date: str = ""
    applicants: tuple[str, ...] = ()
    inventors: tuple[str, ...] = ()
    ipc: tuple[str, ...] = ()
    cpc: tuple[str, ...] = ()
    family_id: str = ""
    abstract: str = ""
    abstract_language: str = "en"
    claims: str = ""
    claims_language: str = "en"
    description: str = ""
    description_language: str = "en"
    malformed: bool = False
    """When True the record is emitted without a usable document identity, which
    a correct parser must reject rather than skip silently."""

    @property
    def identity(self) -> PublicationIdentity | None:
        return parse_publication_reference(self.reference).identity


def _reference_xml(record: FakePatentRecord, container: str, date: str) -> str:
    identity = record.identity
    if identity is None or record.malformed:
        return f"<{container}></{container}>"
    kind = f"<kind>{escape(identity.kind_code)}</kind>" if identity.kind_code else ""
    date_element = f"<date>{escape(date.replace('-', ''))}</date>" if date else ""
    return (
        f"<{container}>"
        f'<document-id document-id-type="docdb">'
        f"<country>{escape(identity.authority)}</country>"
        f"<doc-number>{escape(identity.number)}</doc-number>"
        f"{kind}{date_element}"
        f"</document-id>"
        f"</{container}>"
    )


def _parties_xml(names: tuple[str, ...], container: str, tag: str) -> str:
    if not names:
        return ""
    entries = "".join(
        f'<{tag} data-format="epodoc"><{tag}-name><name>{escape(name)}</name>'
        f"</{tag}-name></{tag}>"
        for name in names
    )
    return f"<{container}>{entries}</{container}>"


def _classifications_xml(record: FakePatentRecord) -> str:
    ipc = "".join(
        f"<classification-ipcr><text>{escape(symbol)}</text></classification-ipcr>"
        for symbol in record.ipc
    )
    cpc_entries = []
    for symbol in record.cpc:
        head, _, subgroup = symbol.partition("/")
        if len(head) < 4:
            continue
        cpc_entries.append(
            "<patent-classification>"
            "<classification-scheme office='EP' scheme='CPCI'/>"
            f"<section>{escape(head[0])}</section>"
            f"<class>{escape(head[1:3])}</class>"
            f"<subclass>{escape(head[3])}</subclass>"
            f"<main-group>{escape(head[4:])}</main-group>"
            + (f"<subgroup>{escape(subgroup)}</subgroup>" if subgroup else "")
            + "</patent-classification>"
        )
    return ipc + "".join(cpc_entries)


def _priority_xml(record: FakePatentRecord) -> str:
    if not record.priority_date or record.malformed:
        return ""
    identity = record.identity
    if identity is None:
        return ""
    return (
        "<priority-claims><priority-claim>"
        f'<document-id document-id-type="docdb">'
        f"<country>{escape(identity.authority)}</country>"
        f"<doc-number>{escape(identity.number)}</doc-number>"
        f"<date>{escape(record.priority_date.replace('-', ''))}</date>"
        "</document-id></priority-claim></priority-claims>"
    )


def exchange_document_xml(record: FakePatentRecord) -> str:
    """One ``exchange-document``, shaped like the verified OPS contract."""
    identity = record.identity
    attributes = ""
    if identity is not None and not record.malformed:
        attributes = f" doc-number={quoteattr(identity.number)}"
        if record.family_id:
            attributes += f" family-id={quoteattr(record.family_id)}"

    title = (
        f"<invention-title lang={quoteattr(record.title_language)}>"
        f"{escape(record.title)}</invention-title>"
        if record.title
        else ""
    )
    grant = ""
    if record.grant_date and identity is not None and not record.malformed:
        grant = (
            "<publication-reference>"
            f'<document-id document-id-type="docdb">'
            f"<country>{escape(identity.authority)}</country>"
            f"<doc-number>{escape(identity.number)}</doc-number>"
            "<kind>B1</kind>"
            f"<date>{escape(record.grant_date.replace('-', ''))}</date>"
            "</document-id></publication-reference>"
        )
    return (
        f"<exchange-document{attributes}>"
        + _reference_xml(record, "publication-reference", record.publication_date)
        + grant
        + _reference_xml(record, "application-reference", record.filing_date)
        + _priority_xml(record)
        + "<bibliographic-data>"
        + f"<invention-title-container>{title}</invention-title-container>"
        + _parties_xml(record.applicants, "applicants", "applicant")
        + _parties_xml(record.inventors, "inventors", "inventor")
        + _classifications_xml(record)
        + "</bibliographic-data>"
        + "</exchange-document>"
    )


def search_response_xml(
    records: list[FakePatentRecord], *, total: int | None = None
) -> str:
    """A full OPS search response.

    ``total`` is the provider's own hit count. Setting it far above the number of
    records is how a fixture models the ordinary case: the office matched
    thousands and served a bounded window (section 13).
    """
    reported = total if total is not None else len(records)
    documents = "".join(exchange_document_xml(record) for record in records)
    return (
        f"{OPS_XML_HEADER}"
        f'<ops:biblio-search total-result-count="{reported}">'
        f"<ops:search-result>{documents}</ops:search-result>"
        f"</ops:biblio-search>{OPS_XML_FOOTER}"
    )


def fault_response_xml(code: str, message: str) -> str:
    """An OPS XML fault, in the exact shape the live service returns."""
    return (
        f"<error><code>{escape(code)}</code>"
        f"<message>{escape(message)}</message></error>"
    )


MALFORMED_XML = "<ops:world-patent-data><exchange-document></exchange"
"""Truncated mid-element: a real parse failure, not a well-formed empty document."""


def family_response_xml(
    family_id: str,
    members: list[FakePatentRecord],
    *,
    earliest_priority: str = "",
) -> str:
    """An OPS family response for one family.

    The family identifier is an attribute the provider supplies. No title
    appears anywhere in this document, which is why a family fixture cannot
    accidentally support title-based grouping (section 17).
    """
    entries = []
    for record in members:
        identity = record.identity
        if identity is None:
            continue
        kind = f"<kind>{escape(identity.kind_code)}</kind>" if identity.kind_code else ""
        date = (
            f"<date>{escape(record.publication_date.replace('-', ''))}</date>"
            if record.publication_date
            else ""
        )
        priority = ""
        if earliest_priority:
            priority = (
                "<priority-claim>"
                f'<document-id document-id-type="docdb">'
                f"<country>{escape(identity.authority)}</country>"
                f"<doc-number>{escape(identity.number)}</doc-number>"
                f"<date>{escape(earliest_priority.replace('-', ''))}</date>"
                "</document-id></priority-claim>"
            )
        entries.append(
            f"<ops:family-member family-id={quoteattr(family_id)}>"
            "<publication-reference>"
            f'<document-id document-id-type="docdb">'
            f"<country>{escape(identity.authority)}</country>"
            f"<doc-number>{escape(identity.number)}</doc-number>"
            f"{kind}{date}"
            "</document-id></publication-reference>"
            f"{priority}"
            "</ops:family-member>"
        )
    return (
        f"{OPS_XML_HEADER}<ops:patent-family>"
        + "".join(entries)
        + f"</ops:patent-family>{OPS_XML_FOOTER}"
    )


def text_response_xml(
    content_type: PatentContentType, text: str, language: str = "en"
) -> str:
    """An abstract, claims or description response for one publication."""
    if content_type is PatentContentType.TITLE:
        body = (
            f"<invention-title lang={quoteattr(language)}>{escape(text)}"
            "</invention-title>"
        )
    elif content_type is PatentContentType.CLAIMS:
        clauses = "".join(
            f"<claim><claim-text>{escape(part.strip())}</claim-text></claim>"
            for part in text.split("\n")
            if part.strip()
        )
        body = f"<claims lang={quoteattr(language)}>{clauses}</claims>"
    else:
        container = "abstract" if content_type is PatentContentType.ABSTRACT else "description"
        paragraphs = "".join(
            f"<p>{escape(part.strip())}</p>" for part in text.split("\n") if part.strip()
        )
        body = f"<{container} lang={quoteattr(language)}>{paragraphs}</{container}>"
    return f"{OPS_XML_HEADER}{body}{OPS_XML_FOOTER}"


# ---------------------------------------------------------------------------
# Scripting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptedPatentSearch:
    """What a fake provider does for one query."""

    records: tuple[FakePatentRecord, ...] = ()
    payload: str | None = None
    """A whole response body, for malformed-XML and fault-envelope cases."""

    total: int | None = None
    """The provider's reported hit count. ``None`` means "as many as served"."""

    failure: PatentErrorKind | None = None
    leading_failures: tuple[PatentErrorKind, ...] = ()
    http_status: int | None = None
    retry_after_seconds: float | None = None
    rejection_reason: str | None = None


def patent_failure(
    kind: PatentErrorKind,
    *,
    http_status: int | None = None,
    retry_after_seconds: float | None = None,
    rejection_reason: str | None = None,
) -> ScriptedPatentSearch:
    """A provider that cannot be asked."""
    return ScriptedPatentSearch(
        failure=kind,
        http_status=http_status,
        retry_after_seconds=retry_after_seconds,
        rejection_reason=rejection_reason,
    )


EMPTY_PATENT_SEARCH = ScriptedPatentSearch()
"""A provider that worked and found nothing. Not a failure."""


@dataclass(frozen=True)
class ScriptedFamily:
    """What the family service does for one publication."""

    family_id: str = ""
    members: tuple[FakePatentRecord, ...] = ()
    earliest_priority: str = ""
    available: bool = True
    """False models an authority the provider offers no family data for."""

    failure: PatentErrorKind | None = None
    payload: str | None = None


@dataclass(frozen=True)
class ScriptedText:
    """What one content-type fetch does for one publication."""

    text: str = ""
    language: str = "en"
    supported: bool = True
    """False models a provider operation this system may not call at all."""

    published: bool = True
    """False models an authority that does not publish this constituent."""

    failure: PatentErrorKind | None = None


class FakeEpoOpsProvider(BasePatentProvider):
    """An offline EPO OPS connector.

    Everything except the HTTP attempt is the shipped code path: the real
    ``parse_ops_search_response``, the real family and text parsers, the real
    range enforcement and the real envelope assembly.
    """

    provider_name = PatentProvider.EPO_OPS
    connector_version = EPO_OPS_CONNECTOR_VERSION

    def __init__(
        self,
        scripts: Mapping[str, ScriptedPatentSearch] | None = None,
        *,
        families: Mapping[str, ScriptedFamily] | None = None,
        texts: Mapping[tuple[str, PatentContentType], ScriptedText] | None = None,
        default_search: ScriptedPatentSearch | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._scripts = dict(scripts or {})
        self._families = dict(families or {})
        self._texts = dict(texts or {})
        self._default_search = default_search
        self._attempts: dict[str, int] = {}
        self.fetch_calls: list[tuple[str, str]] = []
        """``(query expression, range header)`` per attempt. Inspected by the
        eval to prove what actually went to the provider -- which is how PII
        leakage into a query is measured rather than assumed."""

        self.family_calls: list[str] = []
        self.text_calls: list[tuple[str, str]] = []

    # -- search ---------------------------------------------------------------

    def _search_endpoint(self) -> str:
        return EPO_OPS_SEARCH_OPERATION

    def _script_for(self, query: PatentSearchQuery) -> ScriptedPatentSearch:
        return self._scripts.get(
            query.query_expression,
            self._default_search if self._default_search is not None else EMPTY_PATENT_SEARCH,
        )

    def _fetch_search(self, query: PatentSearchQuery, limit: int) -> Any:
        from src.research.patent.epo_ops import range_header

        self.fetch_calls.append(
            (query.query_expression, range_header(query.requested_range_start, limit))
        )
        script = self._script_for(query)
        attempt = self._attempts.get(query.query_expression, 0)
        self._attempts[query.query_expression] = attempt + 1

        if attempt < len(script.leading_failures):
            raise _scripted_error(script, script.leading_failures[attempt])
        if script.failure is not None:
            raise _scripted_error(script, script.failure)
        if script.payload is not None:
            return script.payload
        return search_response_xml(list(script.records), total=script.total)

    def _parse_search(
        self, query: PatentSearchQuery, payload: Any, retrieved_at: datetime
    ) -> ParsedSearchPayload:
        parsed = parse_ops_search_response(query, payload, retrieved_at)
        return ParsedSearchPayload(
            observations=parsed.observations,
            rejected=parsed.rejected,
            raw_count=parsed.raw_count,
            provider_reported_total=parsed.provider_reported_total,
            fault=parsed.fault,
        )

    # -- family ---------------------------------------------------------------

    def fetch_family(self, identity: PublicationIdentity) -> FamilyPayload:
        if not self.supports(PatentProviderOperation.FETCH_FAMILY):
            return FamilyPayload(available=False)
        key = identity.canonical_key
        self.family_calls.append(key)
        script = self._families.get(key)
        if script is None or not script.available:
            return FamilyPayload(available=False, endpoint=EPO_OPS_FAMILY_OPERATION)
        if script.failure is not None:
            return FamilyPayload(
                endpoint=EPO_OPS_FAMILY_OPERATION,
                error=PatentProviderError(
                    provider=self.provider_name,
                    kind=script.failure,
                    retryable=script.failure in RETRYABLE_PATENT_ERROR_KINDS,
                    attempt=1,
                    operation=PatentProviderOperation.FETCH_FAMILY,
                    message=f"scripted family failure {script.failure.value}",
                ),
            )
        payload = (
            script.payload
            if script.payload is not None
            else family_response_xml(
                script.family_id,
                list(script.members),
                earliest_priority=script.earliest_priority,
            )
        )
        return _fake_family_payload(parse_ops_family_response(payload))

    # -- text -----------------------------------------------------------------

    def fetch_text(
        self, identity: PublicationIdentity, content_type: PatentContentType
    ) -> TextPayload:
        operation = text_operation_for(content_type)
        if not self.supports(operation):
            return TextPayload(supported=False, operation=operation)
        key = identity.canonical_key
        self.text_calls.append((key, content_type.value))
        # The documented operation, exactly as the live client records it --
        # never the concrete URL that was sent (section 27).
        endpoint = build_content_request(identity, content_type).documented_operation
        script = self._texts.get((key, content_type))
        if script is None or not script.published:
            return TextPayload(endpoint=endpoint, operation=operation)
        if not script.supported:
            return TextPayload(supported=False, operation=operation, endpoint=endpoint)
        if script.failure is not None:
            return TextPayload(
                endpoint=endpoint,
                operation=operation,
                error=PatentProviderError(
                    provider=self.provider_name,
                    kind=script.failure,
                    retryable=script.failure in RETRYABLE_PATENT_ERROR_KINDS,
                    attempt=1,
                    operation=operation,
                    message=f"scripted text failure {script.failure.value}",
                ),
            )
        raw, language = parse_ops_text_response(
            text_response_xml(content_type, script.text, script.language), content_type
        )
        if raw is None:
            return TextPayload(endpoint=endpoint, operation=operation)
        text, scope, original = normalize_patent_text(raw)
        return TextPayload(
            text=text,
            language=language,
            scope=scope,
            original_char_count=original,
            endpoint=endpoint,
            operation=operation,
        )


def _scripted_error(
    script: ScriptedPatentSearch, kind: PatentErrorKind
) -> PatentTransportError:
    return PatentTransportError(
        kind,
        f"scripted {kind.value}",
        http_status=script.http_status,
        retry_after_seconds=script.retry_after_seconds,
        rejection_reason=script.rejection_reason,
        operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
    )


def _fake_family_payload(parsed: ParsedOpsFamily) -> FamilyPayload:
    if parsed.fault is not None:
        return FamilyPayload(endpoint=EPO_OPS_FAMILY_OPERATION, members=[])
    return FamilyPayload(
        available=True,
        family_id=parsed.family_id,
        family_kind=PatentFamilyKind.EXTENDED_INPADOC,
        members=list(parsed.members),
        earliest_priority_date=parsed.earliest_priority_date,
        endpoint=EPO_OPS_FAMILY_OPERATION,
    )


class UnsupportedPatentProvider(BasePatentProvider):
    """A provider this system may not call, as a dispatchable object.

    Exists so the honest-degradation path has something to exercise: dispatching
    to it yields ``UNSUPPORTED_OPERATION``, which is what must happen if anyone
    ever wires PATENTSCOPE or a legacy PatentsView endpoint into a run.
    """

    provider_name = PatentProvider.WIPO_PATENTSCOPE
    connector_version = "UNSUPPORTED-PROVIDER-V1"

    def _search_endpoint(self) -> str:
        return "not applicable: no authorized programmatic search contract"


FAKE_PATENT_PROVIDER_CLASSES: dict[PatentProvider, type[BasePatentProvider]] = {
    PatentProvider.EPO_OPS: FakeEpoOpsProvider,
}


__all__ = [
    "EMPTY_PATENT_SEARCH",
    "FAKE_PATENT_PROVIDER_CLASSES",
    "MALFORMED_XML",
    "OPS_XML_FOOTER",
    "OPS_XML_HEADER",
    "FakeEpoOpsProvider",
    "FakePatentRecord",
    "ScriptedFamily",
    "ScriptedPatentSearch",
    "ScriptedText",
    "UnsupportedPatentProvider",
    "exchange_document_xml",
    "family_response_xml",
    "fault_response_xml",
    "patent_failure",
    "search_response_xml",
    "text_response_xml",
]
