"""EPO Open Patent Services connector -- Phase 2G sections 2, 14, 19, 27.

The request contract in this module was verified against EPO's own developer
portal and against the live service on the date in ``EPO_OPS_VERIFIED_ON``:

    service root        https://ops.epo.org/3.2/rest-services
    authentication      POST /3.2/auth/accesstoken, HTTP Basic client
                        credentials, ``grant_type=client_credentials``; the
                        response carries a bearer token used as
                        ``Authorization: Bearer <token>``
    search              GET  {root}/published-data/search?q=<CQL>
                        paginated by the HTTP ``Range`` header, ``items=a-b``
    biblio              GET  {root}/published-data/publication/{fmt}/{ref}/biblio
    abstract            GET  {root}/published-data/publication/{fmt}/{ref}/abstract
    claims              GET  {root}/published-data/publication/{fmt}/{ref}/claims
    description         GET  {root}/published-data/publication/{fmt}/{ref}/description
    family              GET  {root}/family/publication/docdb/{ref}
                        (the INPADOC extended family service; ``equivalents``
                        is a ``published-data`` constituent, not a family one)
    response format     XML; XML ``<error><code/><message/></error>`` on fault
    fair use            403 with an ``X-Rejection-Reason`` header on a quota
                        violation

Live observation was unauthenticated: the host, the operation routing, the XML
fault envelope and the Basic-auth challenge on the token endpoint were
confirmed, and no authenticated request was executed. That is why the capability
table reports EPO OPS as ``IMPLEMENTED_DOCUMENTED_ONLY`` and never as
live-verified (section 2, "provider honesty").

Two rules this connector does not bend:

* **An unauthenticated search is not attempted.** The anonymous tier exists but
  is quota-limited and is not a contract this project builds on; a run with no
  credentials reports ``BLOCKED_AUTH`` rather than issuing requests that will be
  rejected.
* **Credentials never reach state, logs or a stored endpoint string.** The
  endpoint recorded on an observation or a snapshot is the documented operation
  path, not the URL that was sent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from src.research.patent.cql import validate_cql
from src.research.patent.chronology import build_date_set
from src.research.patent.identity import (
    build_identity,
    normalize_classification,
    normalize_family_id,
)
from src.schemas.patent import (
    MAX_PATENT_TEXT_CHARS,
    PatentContentType,
    PatentDateSet,
    PatentErrorKind,
    PatentProvider,
    PatentProviderOperation,
    PatentRejectionReason,
    PatentRejectionStage,
    PatentSearchObservation,
    PatentSearchQuery,
    PatentTextScope,
    PublicationIdentity,
    RejectedPatentRecord,
    patent_safe_summary,
)

EPO_OPS_CONNECTOR_VERSION = "EPO-OPS-CONNECTOR-V1"
EPO_OPS_DOCUMENTATION_URL = "https://developers.epo.org/"
EPO_OPS_VERIFIED_ON = "2026-09-17"

EPO_OPS_HOST = "ops.epo.org"
EPO_OPS_API_VERSION = "3.2"
EPO_OPS_SERVICE_ROOT = f"https://{EPO_OPS_HOST}/{EPO_OPS_API_VERSION}/rest-services"
EPO_OPS_AUTH_PATH = f"https://{EPO_OPS_HOST}/{EPO_OPS_API_VERSION}/auth/accesstoken"
EPO_OPS_AUTH_GRANT_TYPE = "client_credentials"

EPO_OPS_SEARCH_PATH = f"{EPO_OPS_SERVICE_ROOT}/published-data/search"
EPO_OPS_PUBLICATION_PATH = f"{EPO_OPS_SERVICE_ROOT}/published-data/publication"
EPO_OPS_FAMILY_PATH = f"{EPO_OPS_SERVICE_ROOT}/family/publication"

EPO_OPS_SEARCH_OPERATION = "GET /published-data/search"
EPO_OPS_BIBLIO_OPERATION = "GET /published-data/publication/{format}/{ref}/biblio"
EPO_OPS_ABSTRACT_OPERATION = "GET /published-data/publication/{format}/{ref}/abstract"
EPO_OPS_CLAIMS_OPERATION = "GET /published-data/publication/{format}/{ref}/claims"
EPO_OPS_DESCRIPTION_OPERATION = (
    "GET /published-data/publication/{format}/{ref}/description"
)
EPO_OPS_FAMILY_OPERATION = "GET /family/publication/docdb/{ref}"

EPO_OPS_QUERY_PARAM = "q"
EPO_OPS_RANGE_HEADER = "Range"
EPO_OPS_RANGE_UNIT = "items"
EPO_OPS_MAX_RANGE_SPAN = 100
"""OPS serves a bounded window per request; a wider Range is refused by the
service. Enforced here so a budget misconfiguration becomes a local error
rather than a rejected third-party request."""

EPO_OPS_REFERENCE_FORMAT_DOCDB = "docdb"
EPO_OPS_REFERENCE_FORMAT_EPODOC = "epodoc"

STALE_EPO_PATHS: tuple[str, ...] = (
    "/3.1/rest-services",
    "/published-data/search.json",
    "/family/publication/docdb/equivalents",
    "/equivalents",
    "/rest-services/published-data/publication/biblio",
    "&Range=",
    "?range=",
    "grant_type=password",
    "Authorization: Basic",
)
"""Values that must never appear in an outgoing EPO OPS request.

A negative assertion, mirroring the Phase 2B.1 contract tests: the stale API
version, a JSON suffix the service does not serve, a family path missing its
reference, the ``published-data`` ``equivalents`` constituent (a simple family,
not the INPADOC family service this connector is built on), pagination smuggled into the query string instead of the ``Range``
header, a password grant OPS does not offer, and Basic credentials on a REST
operation (Basic belongs on the token endpoint alone).
"""

_OPS_NS = {
    "ops": "http://ops.epo.org",
    "ex": "http://www.epo.org/exchange",
    "ft": "http://www.epo.org/fulltext",
}

_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------


def range_header(start: int, limit: int) -> str:
    """The OPS pagination header value, ``items=<start>-<end>``.

    OPS paginates by an inclusive one-based item range in an HTTP header, not by
    a page-number query parameter. Getting this wrong is silent: a ``page=2``
    parameter is simply ignored and the first window comes back again, which
    would look like a corpus with one page in it.
    """
    if start < 1:
        raise ValueError("an OPS item range starts at 1")
    if limit < 1:
        raise ValueError("an OPS item range needs at least one item")
    if limit > EPO_OPS_MAX_RANGE_SPAN:
        raise ValueError(
            f"an OPS item range spans at most {EPO_OPS_MAX_RANGE_SPAN} items"
        )
    return f"{EPO_OPS_RANGE_UNIT}={start}-{start + limit - 1}"


def publication_operation_path(
    identity: PublicationIdentity,
    content_type: PatentContentType,
    *,
    reference_format: str = EPO_OPS_REFERENCE_FORMAT_DOCDB,
) -> str:
    """The documented operation path for one content type of one publication."""
    constituent = {
        PatentContentType.TITLE: "biblio",
        PatentContentType.ABSTRACT: "abstract",
        PatentContentType.CLAIMS: "claims",
        PatentContentType.DESCRIPTION: "description",
    }[content_type]
    reference = (
        identity.docdb_reference
        if reference_format == EPO_OPS_REFERENCE_FORMAT_DOCDB
        else identity.epodoc_reference
    )
    return f"{EPO_OPS_PUBLICATION_PATH}/{reference_format}/{reference}/{constituent}"


def family_operation_path(identity: PublicationIdentity) -> str:
    """The documented family-service path for one publication.

    Always DOCDB: the family service is keyed on DOCDB references, and an
    EPODOC reference here returns a fault rather than a family.
    """
    return (
        f"{EPO_OPS_FAMILY_PATH}/{EPO_OPS_REFERENCE_FORMAT_DOCDB}/"
        f"{identity.docdb_reference}"
    )


@dataclass(frozen=True)
class EpoOpsRequest:
    """One outgoing OPS request, as this connector would issue it.

    Constructed and asserted by the contract tests without any network access,
    which is how the request contract stays pinned. It carries no credentials:
    the bearer token is added by the transport at send time and is never part of
    a request object that could be logged or stored.
    """

    method: str
    url: str
    operation: PatentProviderOperation
    documented_operation: str
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def accepts_xml(self) -> bool:
        return self.headers.get("Accept") == "application/xml"


def build_search_request(query: PatentSearchQuery) -> EpoOpsRequest:
    """The bibliographic search request for one planned query.

    The CQL expression is re-validated here even though the planner validated
    it: this is the last point before a third-party request, and a validator
    that runs only in the planner is a validator a future caller can bypass.
    """
    validated = validate_cql(query.query_expression)
    if not validated.ok:
        raise ValueError(
            f"refusing to send an invalid CQL expression: "
            f"{validated.reason.value if validated.reason else 'unknown'}"
        )
    return EpoOpsRequest(
        method="GET",
        url=EPO_OPS_SEARCH_PATH,
        operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
        documented_operation=EPO_OPS_SEARCH_OPERATION,
        params={EPO_OPS_QUERY_PARAM: validated.expression},
        headers={
            "Accept": "application/xml",
            EPO_OPS_RANGE_HEADER: range_header(
                query.requested_range_start, query.requested_limit
            ),
        },
    )


def build_content_request(
    identity: PublicationIdentity, content_type: PatentContentType
) -> EpoOpsRequest:
    """The request for one content type of one publication."""
    operation = {
        PatentContentType.TITLE: (
            PatentProviderOperation.FETCH_BIBLIOGRAPHIC,
            EPO_OPS_BIBLIO_OPERATION,
        ),
        PatentContentType.ABSTRACT: (
            PatentProviderOperation.FETCH_ABSTRACT,
            EPO_OPS_ABSTRACT_OPERATION,
        ),
        PatentContentType.CLAIMS: (
            PatentProviderOperation.FETCH_CLAIMS,
            EPO_OPS_CLAIMS_OPERATION,
        ),
        PatentContentType.DESCRIPTION: (
            PatentProviderOperation.FETCH_DESCRIPTION,
            EPO_OPS_DESCRIPTION_OPERATION,
        ),
    }[content_type]
    return EpoOpsRequest(
        method="GET",
        url=publication_operation_path(identity, content_type),
        operation=operation[0],
        documented_operation=operation[1],
        headers={"Accept": "application/xml"},
    )


def build_family_request(identity: PublicationIdentity) -> EpoOpsRequest:
    """The family-service request for one publication."""
    return EpoOpsRequest(
        method="GET",
        url=family_operation_path(identity),
        operation=PatentProviderOperation.FETCH_FAMILY,
        documented_operation=EPO_OPS_FAMILY_OPERATION,
        headers={"Accept": "application/xml"},
    )


def build_token_request() -> EpoOpsRequest:
    """The OAuth token request.

    HTTP Basic belongs here and nowhere else: the consumer key and secret
    authenticate this one call, and every REST operation afterwards carries the
    bearer token instead. ``headers`` deliberately holds no ``Authorization``
    value -- the credentials are supplied by the transport at send time so they
    cannot be captured in a request object, a log line or checkpoint state.
    """
    return EpoOpsRequest(
        method="POST",
        url=EPO_OPS_AUTH_PATH,
        operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
        documented_operation="POST /auth/accesstoken",
        params={"grant_type": EPO_OPS_AUTH_GRANT_TYPE},
        headers={
            "Accept": "application/xml",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def normalize_patent_text(raw: str) -> tuple[str, PatentTextScope, int]:
    """Whitespace-normalize provider text and bound its length.

    Returns the text, its scope and the original character count. Only runs of
    spaces and tabs are collapsed and excess blank lines reduced; **no words are
    changed, removed or reordered**, so a stored claim text is the office's
    wording. Bounding is recorded as ``TRUNCATED`` rather than applied silently
    (section 19).
    """
    collapsed = _BLANK_LINES.sub("\n\n", _WHITESPACE.sub(" ", raw.replace("\r\n", "\n")))
    normalized = "\n".join(line.strip() for line in collapsed.split("\n")).strip()
    original = len(normalized)
    if original <= MAX_PATENT_TEXT_CHARS:
        return (normalized, PatentTextScope.COMPLETE_AS_PROVIDED, original)
    return (normalized[:MAX_PATENT_TEXT_CHARS], PatentTextScope.TRUNCATED, original)


def content_hash(text: str) -> str:
    """SHA-256 of the normalized text, as stored.

    Hashing the stored text rather than the provider bytes is deliberate: the
    hash then answers "is this the same snapshot?" for the value that is
    actually on the record, which is what a stability check needs.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_ops_fault(payload: str | bytes) -> tuple[str, str] | None:
    """The ``(code, message)`` of an OPS XML fault, or ``None``.

    OPS reports errors as an XML document rather than an HTTP body this project
    can ignore, so a 200 carrying a fault is still a failure.
    """
    try:
        root = _root(payload)
    except ElementTree.ParseError:
        return None
    if root is None or _local(root.tag) != "error":
        return None
    code = _text(root, "code")
    message = _text(root, "message")
    return (code or "", message or "")


def _root(payload: str | bytes) -> ElementTree.Element | None:
    if isinstance(payload, ElementTree.Element):  # pragma: no cover - defensive
        return payload
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not data.strip():
        return None
    if _DECLARATION.search(data):
        # Provider XML is untrusted. OPS documents never declare a DOCTYPE or
        # an entity, so a response that does is refused before the parser can
        # expand anything (entity-expansion and external-entity attacks).
        raise ElementTree.ParseError("XML declaring a DOCTYPE or ENTITY is refused")
    return ElementTree.fromstring(data)


_DECLARATION = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ElementTree.Element, local_name: str) -> str:
    for child in element.iter():
        if _local(child.tag) == local_name and child.text:
            return child.text.strip()
    return ""


def _find_all(element: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    return [child for child in element.iter() if _local(child.tag) == local_name]


def _either(
    first: ElementTree.Element | None, second: ElementTree.Element | None
) -> ElementTree.Element | None:
    """``first`` when present, else ``second``.

    Never ``first or second``: an ElementTree element with no child elements is
    *falsy*, so ``or`` would silently discard a perfectly present element -- an
    ``invention-title`` has no children, and ``english or titles[0]`` would
    never prefer the English title.
    """
    return first if first is not None else second


def _document_id(
    element: ElementTree.Element, kind: str
) -> ElementTree.Element | None:
    """The ``document-id`` child of the requested ``document-id-type``.

    DOCDB is what identity is built from: it splits country, doc-number and kind
    into separate elements, so the kind code does not have to be sliced off a
    concatenated string.
    """
    for candidate in _find_all(element, "document-id"):
        if candidate.get("document-id-type") == kind:
            return candidate
    return None


def _identity_from_element(
    element: ElementTree.Element,
) -> tuple[PublicationIdentity | None, PatentRejectionReason | None]:
    reference = _either(_document_id(element, "docdb"), _document_id(element, "epodoc"))
    if reference is None:
        return (None, PatentRejectionReason.MISSING_PUBLICATION_IDENTITY)
    result = build_identity(
        authority=_text(reference, "country"),
        number=_text(reference, "doc-number"),
        kind_code=_text(reference, "kind") or None,
    )
    return (result.identity, result.reason)


def _title(element: ElementTree.Element) -> tuple[str, str | None]:
    """The invention title and its declared language.

    English is preferred where the document carries several titles, because the
    query vocabulary is English; the language is recorded either way and never
    guessed from the characters.
    """
    titles = _find_all(element, "invention-title")
    if not titles:
        return ("", None)
    english = next((t for t in titles if (t.get("lang") or "").lower() == "en"), None)
    chosen = _either(english, titles[0])
    language = (chosen.get("lang") or "").lower() or None
    return ((chosen.text or "").strip(), language if language and len(language) == 2 else None)


def _dates(
    element: ElementTree.Element, identity: PublicationIdentity | None = None
) -> PatentDateSet | None:
    """The four dates, each read from its own OPS element.

    Each date comes from the element that means that date and from nowhere else.
    There is deliberately no fallback chain: a missing publication date stays
    missing rather than being filled from the filing date (section 8).

    The publication date is read only from the publication reference that
    carries the document's *own* kind code. A record can list a later grant
    reference as well; falling through to it when the document's own reference
    has no date would present the grant date as the publication date, which is
    the substitution section 8 forbids.
    """
    publication = _own_publication_date(element, identity)
    filing = _date_of(element, "application-reference")
    priority = _earliest_priority(element)
    # A grant date is read only from a *separate* grant reference. The
    # document's own reference is never re-read as a grant, even for a
    # B-kind document: what a B kind code means is authority-dependent, and an
    # inferred grant date is exactly the substitution section 8 forbids. Where
    # no separate grant reference exists, the grant date stays unknown.
    own_kind = identity.kind_code if identity is not None else None
    grant = ""
    for candidate in _find_all(element, "publication-reference"):
        reference = _document_id(candidate, "docdb")
        if reference is None:
            continue
        kind = _text(reference, "kind").upper()
        if kind.startswith("B") and kind != own_kind:
            grant = _text(reference, "date")
            break
    return build_date_set(
        priority=priority or None,
        filing=filing or None,
        publication=publication or None,
        grant=grant or None,
    )


def _own_publication_date(
    element: ElementTree.Element, identity: PublicationIdentity | None
) -> str:
    for candidate in _find_all(element, "publication-reference"):
        reference = _either(_document_id(candidate, "docdb"), _document_id(candidate, "epodoc"))
        if reference is None:
            continue
        kind = _text(reference, "kind").upper() or None
        if identity is None or kind == identity.kind_code:
            # The first reference of the document's own kind is its own
            # publication. Its date, or no date at all.
            return _text(reference, "date")
    return ""


def _date_of(element: ElementTree.Element, container: str) -> str:
    for candidate in _find_all(element, container):
        reference = _either(_document_id(candidate, "docdb"), _document_id(candidate, "epodoc"))
        if reference is not None:
            date = _text(reference, "date")
            if date:
                return date
    return ""


def _earliest_priority(element: ElementTree.Element) -> str:
    dates: list[str] = []
    for claim in _find_all(element, "priority-claim"):
        # ``is not None``, never truthiness: see ``_either``.
        reference = _document_id(claim, "docdb")
        if reference is not None and _text(reference, "date"):
            dates.append(_text(reference, "date"))
    return min(dates) if dates else ""


def _parties(element: ElementTree.Element, container: str, name_tag: str) -> list[str]:
    """Applicant or inventor names, deduplicated, in document order.

    OPS repeats each party once per name format (``epodoc`` and ``original``),
    so a naive read doubles every name.
    """
    names: list[str] = []
    for parties in _find_all(element, container):
        for party in _find_all(parties, name_tag):
            if party.get("data-format") not in (None, "epodoc"):
                continue
            name = _text(party, "name")
            if name and name not in names:
                names.append(name)
    return names


def _classifications(element: ElementTree.Element) -> tuple[list[str], list[str]]:
    """IPC and CPC symbols, normalized, malformed ones dropped.

    Classifications are metadata (section 25): a malformed symbol is not worth
    rejecting a whole publication over, and keeping an unparseable string would
    make a later expansion step search for nonsense.
    """
    ipc: list[str] = []
    for node in (
        *_find_all(element, "classification-ipcr"),
        *_find_all(element, "classification-ipc"),
    ):
        symbol = normalize_classification(_text(node, "text") or (node.text or ""))
        if symbol and symbol not in ipc:
            ipc.append(symbol)

    cpc: list[str] = []
    for node in _find_all(element, "patent-classification"):
        # OPS states the scheme either as element text or as a ``scheme``
        # attribute on an empty ``classification-scheme`` element, and both
        # forms occur. A node that names no scheme at all is kept: a CPC
        # container is the common case, and dropping an unlabelled symbol
        # would silently lose a classification.
        declared = [
            *(child.get("scheme", "") for child in _find_all(node, "classification-scheme")),
            _text(node, "classification-scheme"),
        ]
        scheme = " ".join(value for value in declared if value).upper()
        if scheme and "CPC" not in scheme:
            continue
        parts = [
            _text(node, "section"),
            _text(node, "class"),
            _text(node, "subclass"),
            _text(node, "main-group"),
        ]
        subgroup = _text(node, "subgroup")
        if not all(parts):
            continue
        raw = "".join(parts) + (f"/{subgroup}" if subgroup else "")
        symbol = normalize_classification(raw)
        if symbol and symbol not in cpc:
            cpc.append(symbol)
    return (ipc, cpc)


@dataclass
class ParsedOpsSearch:
    """What one OPS search response yielded, before any budget is applied."""

    observations: list[PatentSearchObservation] = field(default_factory=list)
    rejected: list[RejectedPatentRecord] = field(default_factory=list)
    raw_count: int = 0
    provider_reported_total: int | None = None
    fault: tuple[str, str] | None = None


def parse_ops_search_response(
    query: PatentSearchQuery, payload: str | bytes, retrieved_at: datetime
) -> ParsedOpsSearch:
    """Turn one OPS search response into observations and a rejection ledger.

    Every record is normalized and validated independently: one malformed
    ``exchange-document`` produces one ledger entry, not a lost response
    (section 28). Deduplication *within* one response is applied here, because a
    provider repeating a record in one window must not look like two
    independent hits (section 15).
    """
    parsed = ParsedOpsSearch()

    def reject(reason: PatentRejectionReason, record_id: str | None, summary: str) -> None:
        parsed.rejected.append(
            RejectedPatentRecord(
                provider=PatentProvider.EPO_OPS,
                query_id=query.query_id,
                stage=PatentRejectionStage.NORMALIZATION,
                reason=reason,
                provider_record_identifier=record_id,
                safe_summary=patent_safe_summary(summary),
            )
        )

    try:
        root = _root(payload)
    except ElementTree.ParseError as exc:
        reject(PatentRejectionReason.MALFORMED_RECORD, None, f"unparseable XML: {exc.msg}")
        return parsed
    if root is None:
        reject(PatentRejectionReason.MALFORMED_RECORD, None, "empty response body")
        return parsed

    fault = parse_ops_fault(root)
    if fault is not None:
        parsed.fault = fault
        return parsed

    for result in _find_all(root, "biblio-search"):
        total = result.get("total-result-count")
        if total and total.isdigit():
            parsed.provider_reported_total = int(total)
            break

    documents = _find_all(root, "exchange-document")
    parsed.raw_count = len(documents)
    seen: set[str] = set()

    for rank, document in enumerate(documents):
        record_id = document.get("doc-number") or None
        identity, reason = _identity_from_element(document)
        if identity is None:
            reject(
                reason or PatentRejectionReason.MISSING_PUBLICATION_IDENTITY,
                record_id,
                "publication identity could not be built",
            )
            continue

        key = identity.canonical_key
        if key in seen:
            reject(PatentRejectionReason.DUPLICATE_PROVIDER_RECORD, record_id, key)
            continue

        dates = _dates(document, identity)
        if dates is None:
            reject(PatentRejectionReason.INCONSISTENT_DATE_ORDER, record_id, key)
            continue

        title, title_language = _title(document)
        ipc, cpc = _classifications(document)
        seen.add(key)
        parsed.observations.append(
            PatentSearchObservation(
                research_run_id=query.research_run_id,
                query_id=query.query_id,
                provider=PatentProvider.EPO_OPS,
                provider_operation=PatentProviderOperation.SEARCH_PUBLICATIONS,
                provider_endpoint=EPO_OPS_SEARCH_OPERATION,
                identity=identity,
                title=title,
                title_language=title_language,
                dates=dates,
                applicants=_parties(document, "applicants", "applicant"),
                inventors=_parties(document, "inventors", "inventor"),
                ipc_classifications=ipc,
                cpc_classifications=cpc,
                family_id=normalize_family_id(document.get("family-id")),
                provider_record_id=record_id,
                provider_rank=rank,
                retrieved_at=retrieved_at,
            )
        )
    return parsed


@dataclass
class ParsedOpsFamily:
    """One OPS family response: the members it named, and any fault."""

    family_id: str | None = None
    members: list[tuple[PublicationIdentity, str | None]] = field(default_factory=list)
    earliest_priority_date: str | None = None
    fault: tuple[str, str] | None = None


def parse_ops_family_response(payload: str | bytes) -> ParsedOpsFamily:
    """Read the family members and family identifier from an OPS family response.

    The family identifier comes from the provider and from nowhere else. There
    is no title anywhere in this function, which is what makes title-derived
    family identity impossible here rather than merely discouraged (section 17).
    """
    parsed = ParsedOpsFamily()
    try:
        root = _root(payload)
    except ElementTree.ParseError:
        parsed.fault = ("", "unparseable family XML")
        return parsed
    if root is None:
        parsed.fault = ("", "empty family response")
        return parsed

    fault = parse_ops_fault(root)
    if fault is not None:
        parsed.fault = fault
        return parsed

    priorities: list[str] = []
    for member in _find_all(root, "family-member"):
        parsed.family_id = parsed.family_id or normalize_family_id(
            member.get("family-id")
        )
        publication = next(
            (
                candidate
                for candidate in _find_all(member, "publication-reference")
            ),
            None,
        )
        if publication is None:
            continue
        identity, _ = _identity_from_element(publication)
        if identity is None:
            continue
        reference = _document_id(publication, "docdb")
        raw_date = _text(reference, "date") if reference is not None else ""
        from src.research.patent.identity import normalize_patent_date

        member_date = normalize_patent_date(raw_date)
        priority = _earliest_priority(member)
        if priority:
            normalized_priority = normalize_patent_date(priority)
            if normalized_priority:
                priorities.append(normalized_priority)
        parsed.members.append((identity, member_date))

    parsed.earliest_priority_date = min(priorities) if priorities else None
    return parsed


def parse_ops_text_response(
    payload: str | bytes, content_type: PatentContentType
) -> tuple[str, str | None] | tuple[None, None]:
    """The text and declared language for one content type, or ``(None, None)``.

    Reads only the element that holds the requested content type. A claims
    request that comes back without claims yields ``None``; it never falls back
    to the abstract or the title, which section 21 forbids outright.
    """
    try:
        root = _root(payload)
    except ElementTree.ParseError:
        return (None, None)
    if root is None or parse_ops_fault(root) is not None:
        return (None, None)

    container = {
        PatentContentType.TITLE: "invention-title",
        PatentContentType.ABSTRACT: "abstract",
        PatentContentType.CLAIMS: "claims",
        PatentContentType.DESCRIPTION: "description",
    }[content_type]

    nodes = _find_all(root, container)
    if not nodes:
        return (None, None)
    english = next((n for n in nodes if (n.get("lang") or "").lower() == "en"), None)
    chosen = _either(english, nodes[0])
    language = (chosen.get("lang") or "").lower() or None

    if content_type is PatentContentType.TITLE:
        text = (chosen.text or "").strip()
    else:
        paragraphs = [
            " ".join(part.strip() for part in node.itertext() if part.strip())
            for node in _find_all(chosen, "p")
        ] or [
            " ".join(part.strip() for part in node.itertext() if part.strip())
            for node in _find_all(chosen, "claim-text")
        ]
        text = "\n".join(p for p in paragraphs if p) or " ".join(
            part.strip() for part in chosen.itertext() if part.strip()
        )

    text = text.strip()
    if not text:
        return (None, None)
    return (text, language if language and len(language) == 2 else None)


def error_kind_for_fault(code: str, message: str) -> PatentErrorKind:
    """Classify an OPS XML fault when no HTTP status is available.

    An OPS fault carries its own numeric code, so a fault body is classified
    from the provider's own vocabulary rather than guessed.
    """
    folded = message.casefold()
    if "fair use" in folded or "quota" in folded:
        return PatentErrorKind.FAIR_USE_REJECTED
    if code.startswith("4"):
        if code == "403":
            return PatentErrorKind.FORBIDDEN
        if code == "401":
            return PatentErrorKind.AUTHENTICATION_ERROR
        if code == "404":
            return PatentErrorKind.NOT_FOUND
        if code == "400":
            return PatentErrorKind.INVALID_QUERY
        return PatentErrorKind.PROVIDER_ERROR
    if code.startswith("5"):
        return PatentErrorKind.SERVER_ERROR
    return PatentErrorKind.PROVIDER_ERROR


__all__ = [
    "EPO_OPS_ABSTRACT_OPERATION",
    "EPO_OPS_API_VERSION",
    "EPO_OPS_AUTH_GRANT_TYPE",
    "EPO_OPS_AUTH_PATH",
    "EPO_OPS_BIBLIO_OPERATION",
    "EPO_OPS_CLAIMS_OPERATION",
    "EPO_OPS_CONNECTOR_VERSION",
    "EPO_OPS_DESCRIPTION_OPERATION",
    "EPO_OPS_DOCUMENTATION_URL",
    "EPO_OPS_FAMILY_OPERATION",
    "EPO_OPS_FAMILY_PATH",
    "EPO_OPS_HOST",
    "EPO_OPS_MAX_RANGE_SPAN",
    "EPO_OPS_PUBLICATION_PATH",
    "EPO_OPS_QUERY_PARAM",
    "EPO_OPS_RANGE_HEADER",
    "EPO_OPS_RANGE_UNIT",
    "EPO_OPS_REFERENCE_FORMAT_DOCDB",
    "EPO_OPS_REFERENCE_FORMAT_EPODOC",
    "EPO_OPS_SEARCH_OPERATION",
    "EPO_OPS_SEARCH_PATH",
    "EPO_OPS_SERVICE_ROOT",
    "EPO_OPS_VERIFIED_ON",
    "STALE_EPO_PATHS",
    "EpoOpsRequest",
    "ParsedOpsFamily",
    "ParsedOpsSearch",
    "build_content_request",
    "build_family_request",
    "build_search_request",
    "build_token_request",
    "content_hash",
    "error_kind_for_fault",
    "family_operation_path",
    "normalize_patent_text",
    "parse_ops_family_response",
    "parse_ops_fault",
    "parse_ops_search_response",
    "parse_ops_text_response",
    "publication_operation_path",
    "range_header",
]
