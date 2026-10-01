"""SSRF-safe public web fetching -- sections 6 and 33.

Search discovery and artifact verification are separate: a search hit is only
a URL someone else returned, and this module is the single door through which
Phase 2H reads one. It refuses before connecting:

* any scheme but ``http`` / ``https``, and any port but 80 / 443;
* a URL with embedded credentials (``user:pass@host``);
* ``localhost``, ``*.localhost``, ``*.local``, ``*.internal`` and known cloud
  metadata hostnames;
* a host that is, or resolves to, a loopback, private, link-local (which
  includes ``169.254.169.254``), shared, multicast, reserved or unspecified
  address -- IPv4 or IPv6, including IPv4-mapped IPv6.

Redirects are never followed automatically. Each hop is re-checked with the
same rules before it is requested, the chain is bounded and recorded, and the
first unsafe hop ends the fetch with ``FETCH_UNSAFE``.

Bodies are read with a hard byte limit; an oversized body is refused with
``CONTENT_TOO_LARGE``, never truncated and accepted. No JavaScript is run, no
cookie is kept between requests, environment proxies are ignored, and no
credential is ever sent.

Known limitation (documented in ADR-019): name resolution happens before the
connection, so a host whose DNS answer changes between the check and the
connect (DNS rebinding) is not fully closed by this layer alone.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from src.schemas.discovery import DiscoveryErrorKind, safe_summary
from src.schemas.product_prior_art import ProductFetchStatus

USER_AGENT = "mawhiba-evaluator-prior-art-discovery/1.0"
ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
SUPPORTED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
BLOCKED_HOSTNAMES = frozenset(
    {"localhost", "metadata.google.internal", "metadata", "instance-data", "metadata.azure.com"}
)
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan", ".intranet")
TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset({"gclid", "fbclid", "msclkid", "ref_src"})


class UrlRefusal(StrEnum):
    NOT_HTTP = "NOT_HTTP"
    DISALLOWED_PORT = "DISALLOWED_PORT"
    EMBEDDED_CREDENTIALS = "EMBEDDED_CREDENTIALS"
    NO_HOST = "NO_HOST"
    BLOCKED_HOSTNAME = "BLOCKED_HOSTNAME"
    NON_PUBLIC_ADDRESS = "NON_PUBLIC_ADDRESS"
    UNRESOLVABLE_HOST = "UNRESOLVABLE_HOST"
    MALFORMED_URL = "MALFORMED_URL"


Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    """Every address the system resolves ``host`` to."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def is_public_address(raw: str) -> bool:
    """True only for a globally routable unicast address."""
    try:
        address = ipaddress.ip_address(raw.split("%")[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or (isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"))
        or not address.is_global
    )


def check_url(url: str, resolver: Resolver = system_resolver) -> UrlRefusal | None:
    """Why ``url`` must not be fetched, or None when it may be."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return UrlRefusal.MALFORMED_URL
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return UrlRefusal.NOT_HTTP
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return UrlRefusal.EMBEDDED_CREDENTIALS
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return UrlRefusal.NO_HOST
    if port is not None and port not in ALLOWED_PORTS:
        return UrlRefusal.DISALLOWED_PORT
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES) or "." not in host and ":" not in host:
        return UrlRefusal.BLOCKED_HOSTNAME
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        return None if is_public_address(host) else UrlRefusal.NON_PUBLIC_ADDRESS
    try:
        addresses = resolver(host)
    except (OSError, UnicodeError):
        return UrlRefusal.UNRESOLVABLE_HOST
    if not addresses:
        return UrlRefusal.UNRESOLVABLE_HOST
    if not all(is_public_address(a) for a in addresses):
        # Every answer must be public: one private answer is enough to reach
        # an internal service.
        return UrlRefusal.NON_PUBLIC_ADDRESS
    return None


def canonicalize_url(url: str) -> str:
    """A stable form for deduplication. Never used to fetch a different page.

    Scheme and host lower-cased, default port and fragment dropped, tracking
    parameters removed, remaining parameters kept in their order.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").rstrip(".").lower()
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PARAMS_PREFIXES)
        ]
    )
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").rstrip(".").lower() or "unknown"
    except ValueError:
        return "unknown"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    over_limit: bool = False


class FetchTransport(Protocol):
    def get(self, url: str, *, max_bytes: int, timeout: float) -> RawResponse: ...


class FetchTransportError(Exception):
    def __init__(self, kind: DiscoveryErrorKind) -> None:
        super().__init__(kind.value)
        self.kind = kind


class HttpxFetchTransport:
    """Live transport: one fresh client per request, so no cookie survives."""

    def get(self, url: str, *, max_bytes: int, timeout: float) -> RawResponse:
        import httpx

        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=timeout,
                trust_env=False,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html, text/plain"},
            ) as client:
                with client.stream("GET", url) as response:
                    chunks: list[bytes] = []
                    size = 0
                    over = False
                    if not response.is_redirect:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                over = True
                                break
                            chunks.append(chunk)
                    return RawResponse(
                        status=response.status_code,
                        headers={k.lower(): v for k, v in response.headers.items()},
                        body=b"".join(chunks),
                        over_limit=over,
                    )
        except httpx.TimeoutException as exc:
            raise FetchTransportError(DiscoveryErrorKind.TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise FetchTransportError(DiscoveryErrorKind.CONNECTION_ERROR) from exc


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


@dataclass
class FetchOutcome:
    status: ProductFetchStatus
    original_url: str
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    content_type: str | None = None
    text: str = ""
    byte_length: int | None = None
    content_hash: str | None = None
    error_kind: DiscoveryErrorKind | None = None
    refusal: UrlRefusal | None = None
    http_status: int | None = None
    retrieved_at: datetime | None = None
    requests_sent: list[str] = field(default_factory=list)

    @property
    def detail(self) -> str:
        if self.refusal is not None:
            return safe_summary(f"refused: {self.refusal.value}")
        if self.http_status is not None and self.status is not ProductFetchStatus.FETCHED:
            return safe_summary(f"HTTP {self.http_status}")
        return ""


_STATUS_FOR_ERROR: dict[DiscoveryErrorKind, ProductFetchStatus] = {
    DiscoveryErrorKind.TIMEOUT: ProductFetchStatus.TIMEOUT,
    DiscoveryErrorKind.CONNECTION_ERROR: ProductFetchStatus.CONNECTION_ERROR,
}


class SafeWebFetcher:
    """The only product-page fetcher. Every hop is checked before it is sent."""

    def __init__(
        self,
        transport: FetchTransport | None = None,
        *,
        resolver: Resolver = system_resolver,
        max_redirects: int = 3,
        max_bytes: int = 2_000_000,
        timeout_seconds: float = 15.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or HttpxFetchTransport()
        self._resolver = resolver
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self._clock = clock

    def _now(self) -> datetime:
        from src.workflow.clock import workflow_now

        return self._clock() if self._clock else workflow_now()

    def fetch(self, url: str) -> FetchOutcome:
        outcome = FetchOutcome(status=ProductFetchStatus.FETCH_UNSAFE, original_url=url)
        outcome.retrieved_at = self._now()
        current = url
        for hop in range(self.max_redirects + 1):
            refusal = check_url(current, self._resolver)
            if refusal is not None:
                outcome.status = ProductFetchStatus.FETCH_UNSAFE
                outcome.error_kind = DiscoveryErrorKind.FETCH_UNSAFE
                outcome.refusal = refusal
                return outcome
            outcome.requests_sent.append(current)
            try:
                response = self._transport.get(
                    current, max_bytes=self.max_bytes, timeout=self.timeout_seconds
                )
            except FetchTransportError as exc:
                outcome.status = _STATUS_FOR_ERROR.get(exc.kind, ProductFetchStatus.CONNECTION_ERROR)
                outcome.error_kind = exc.kind
                return outcome
            headers = {k.lower(): v for k, v in response.headers.items()}
            if 300 <= response.status < 400 and response.status != 304:
                location = headers.get("location")
                if not location:
                    return self._fail(outcome, ProductFetchStatus.HTTP_ERROR, DiscoveryErrorKind.PROVIDER_ERROR, response.status)
                target = urljoin(current, location)
                outcome.redirect_chain.append(target)
                current = target
                continue
            outcome.http_status = response.status
            if response.status in (401, 403, 451):
                return self._fail(outcome, ProductFetchStatus.FETCH_BLOCKED, DiscoveryErrorKind.FETCH_BLOCKED, response.status)
            if response.status == 429:
                return self._fail(outcome, ProductFetchStatus.FETCH_BLOCKED, DiscoveryErrorKind.RATE_LIMITED, response.status)
            if response.status != 200:
                return self._fail(outcome, ProductFetchStatus.HTTP_ERROR, DiscoveryErrorKind.PROVIDER_ERROR, response.status)
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            declared = headers.get("content-length", "")
            if response.over_limit or len(response.body) > self.max_bytes or (
                declared.isdigit() and int(declared) > self.max_bytes
            ):
                return self._fail(outcome, ProductFetchStatus.CONTENT_TOO_LARGE, DiscoveryErrorKind.CONTENT_TOO_LARGE, 200)
            if content_type not in SUPPORTED_CONTENT_TYPES:
                outcome.content_type = content_type or None
                return self._fail(outcome, ProductFetchStatus.UNSUPPORTED_CONTENT, DiscoveryErrorKind.PARSE_ERROR, 200)
            try:
                text = response.body.decode(_charset(headers.get("content-type", "")) or "utf-8")
            except (UnicodeDecodeError, LookupError):
                return self._fail(outcome, ProductFetchStatus.PARSE_ERROR, DiscoveryErrorKind.PARSE_ERROR, 200)
            outcome.status = ProductFetchStatus.FETCHED
            outcome.final_url = current
            outcome.content_type = content_type
            outcome.text = text
            outcome.byte_length = len(response.body)
            outcome.content_hash = hashlib.sha256(response.body).hexdigest()
            return outcome
        # The chain is longer than the bound: refused, never followed further.
        return self._fail(outcome, ProductFetchStatus.FETCH_BLOCKED, DiscoveryErrorKind.FETCH_BLOCKED, None)

    @staticmethod
    def _fail(
        outcome: FetchOutcome,
        status: ProductFetchStatus,
        kind: DiscoveryErrorKind,
        http_status: int | None,
    ) -> FetchOutcome:
        outcome.status = status
        outcome.error_kind = kind
        outcome.http_status = http_status
        outcome.text = ""
        outcome.content_hash = None
        return outcome


def _charset(content_type: str) -> str | None:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip().strip('"')
    return None


__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "BLOCKED_HOSTNAMES",
    "FetchOutcome",
    "FetchTransport",
    "FetchTransportError",
    "HttpxFetchTransport",
    "RawResponse",
    "Resolver",
    "SafeWebFetcher",
    "UrlRefusal",
    "canonicalize_url",
    "check_url",
    "host_of",
    "is_public_address",
    "system_resolver",
]
