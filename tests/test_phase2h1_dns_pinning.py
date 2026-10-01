"""Phase 2H.1 -- DNS-rebinding / DNS TOCTOU closure in the safe fetcher.

Every test drives the real ``HttpxFetchTransport`` (a real httpcore
connection pool) through ``PinnedNetworkBackend``. The socket layer is
replaced by a recording connector, so nothing touches the network and every
attempted destination IP is observable. The invariant under test: no
connection is ever made to an address that was not validated as public in
the same resolution that chose it.
"""

from __future__ import annotations

import ssl

import pytest

from src.research.discovery.safe_fetch import (
    HttpxFetchTransport,
    PinnedNetworkBackend,
    SafeWebFetcher,
    UnsafeDestinationError,
    UrlRefusal,
)
from src.schemas.discovery import DiscoveryErrorKind
from src.schemas.product_prior_art import ProductFetchStatus

PUBLIC = "93.184.216.34"
PUBLIC_2 = "93.184.216.35"
PAGE = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 13\r\n\r\n<p>public</p>"


class SequencedResolver:
    """Answers with the next scripted list each time it is asked -- a rebinding DNS server."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    def __call__(self, host: str) -> list[str]:
        self.calls.append(host)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class FakeStream:
    def __init__(self, ip: str, response: bytes, log: dict) -> None:
        self.ip = ip
        self._response = response
        self.log = log

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.log.setdefault("written", b"")
        self.log["written"] += buffer

    def close(self) -> None:
        self.log["closed"] = True

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.log["sni"] = server_hostname
        self.log["ssl_context"] = ssl_context
        return self

    def get_extra_info(self, info: str):
        if info == "server_addr":
            return (self.log.get("peer_override", self.ip), 443)
        return None


class RecordingConnector:
    def __init__(self, responses: dict[str, bytes] | None = None, peer_override: str | None = None) -> None:
        self.responses = responses or {}
        self.attempted: list[str] = []
        self.logs: list[dict] = []
        self.peer_override = peer_override

    def __call__(self, *, host, port, timeout=None, local_address=None, socket_options=None):
        self.attempted.append(host)
        log: dict = {"ip": host, "port": port}
        if self.peer_override:
            log["peer_override"] = self.peer_override
        self.logs.append(log)
        return FakeStream(host, self.responses.get(host, PAGE), log)


def _fetch(url: str, resolver, connector) -> tuple:
    transport = HttpxFetchTransport(resolver, connector)
    fetcher = SafeWebFetcher(transport, resolver=resolver)
    return fetcher.fetch(url), transport


@pytest.mark.parametrize(
    "rebound",
    [
        pytest.param(["127.0.0.1"], id="loopback"),
        pytest.param(["10.0.0.5"], id="rfc1918-10"),
        pytest.param(["192.168.1.1"], id="rfc1918-192"),
        pytest.param(["172.16.0.9"], id="rfc1918-172"),
        pytest.param(["169.254.169.254"], id="metadata-link-local"),
        pytest.param(["::ffff:10.0.0.1"], id="ipv4-mapped-ipv6-private"),
        pytest.param(["::ffff:127.0.0.1"], id="ipv4-mapped-ipv6-loopback"),
        pytest.param(["::1"], id="ipv6-loopback"),
        pytest.param(["fe80::1"], id="ipv6-link-local"),
        pytest.param([PUBLIC, "10.0.0.5"], id="mixed-public-and-private"),
    ],
)
def test_rebinding_after_preflight_never_contacts_private_address(rebound):
    resolver = SequencedResolver([PUBLIC], rebound)
    connector = RecordingConnector()
    outcome, _ = _fetch("https://shop.example.com/p", resolver, connector)
    assert resolver.calls == ["shop.example.com", "shop.example.com"]
    assert connector.attempted == [], "a private destination was contacted"
    assert outcome.status is ProductFetchStatus.FETCH_UNSAFE
    assert outcome.error_kind is DiscoveryErrorKind.FETCH_UNSAFE
    assert outcome.refusal is UrlRefusal.NON_PUBLIC_ADDRESS
    assert outcome.text == "" and outcome.content_hash is None


def test_redirect_target_rebinding_is_refused_at_connect():
    redirect = b"HTTP/1.1 302 Found\r\nLocation: https://cdn.example.net/x\r\nContent-Length: 0\r\n\r\n"
    answers = {
        "shop.example.com": [[PUBLIC]],
        # Public at the hop's preflight check, private at its connect.
        "cdn.example.net": [[PUBLIC_2], ["192.168.0.10"]],
    }

    def resolver(host: str) -> list[str]:
        queue = answers[host]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    connector = RecordingConnector({PUBLIC: redirect})
    outcome, _ = _fetch("https://shop.example.com/p", resolver, connector)
    assert connector.attempted == [PUBLIC]
    assert "192.168.0.10" not in connector.attempted
    assert outcome.redirect_chain == ["https://cdn.example.net/x"]
    assert outcome.status is ProductFetchStatus.FETCH_UNSAFE
    assert outcome.refusal is UrlRefusal.NON_PUBLIC_ADDRESS


def test_redirect_to_private_target_refused_before_any_connect():
    redirect = b"HTTP/1.1 301 Moved\r\nLocation: http://10.1.1.1/admin\r\nContent-Length: 0\r\n\r\n"
    connector = RecordingConnector({PUBLIC: redirect})
    outcome, _ = _fetch("https://shop.example.com/p", SequencedResolver([PUBLIC]), connector)
    assert connector.attempted == [PUBLIC]
    assert outcome.status is ProductFetchStatus.FETCH_UNSAFE


def test_normal_public_host_is_fetched_and_pinned_to_the_validated_ip():
    resolver = SequencedResolver([PUBLIC])
    connector = RecordingConnector()
    outcome, transport = _fetch("https://shop.example.com/p", resolver, connector)
    assert outcome.status is ProductFetchStatus.FETCHED
    assert outcome.text == "<p>public</p>"
    assert connector.attempted == [PUBLIC]
    assert transport.last_backend.connected == [("shop.example.com", PUBLIC, 443)]


def test_tls_and_host_identity_use_the_original_hostname_not_the_ip():
    connector = RecordingConnector()
    outcome, _ = _fetch("https://shop.example.com/p?q=1", SequencedResolver([PUBLIC]), connector)
    assert outcome.status is ProductFetchStatus.FETCHED
    log = connector.logs[0]
    assert log["ip"] == PUBLIC
    assert log["sni"] == "shop.example.com"
    context = log["ssl_context"]
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    request = log["written"].decode("latin-1")
    assert request.startswith("GET /p?q=1 HTTP/1.1\r\n")
    assert "\r\nHost: shop.example.com\r\n" in request
    assert PUBLIC not in request


def test_plain_http_is_pinned_and_skips_tls():
    connector = RecordingConnector()
    outcome, _ = _fetch("http://shop.example.com/p", SequencedResolver([PUBLIC]), connector)
    assert outcome.status is ProductFetchStatus.FETCHED
    assert connector.logs[0]["port"] == 80
    assert "sni" not in connector.logs[0]


def test_peer_address_mismatch_after_connect_is_refused():
    connector = RecordingConnector(peer_override="10.0.0.1")
    outcome, _ = _fetch("https://shop.example.com/p", SequencedResolver([PUBLIC]), connector)
    assert outcome.status is ProductFetchStatus.FETCH_UNSAFE
    assert connector.logs[0].get("closed") is True
    assert "written" not in connector.logs[0], "a request was sent to an unverified peer"


def test_backend_refuses_without_validated_answers():
    backend = PinnedNetworkBackend(lambda h: [], RecordingConnector())
    with pytest.raises(UnsafeDestinationError) as unresolved:
        backend.connect_tcp("shop.example.com", 443)
    assert unresolved.value.refusal is UrlRefusal.UNRESOLVABLE_HOST
    with pytest.raises(UnsafeDestinationError) as port:
        PinnedNetworkBackend(lambda h: [PUBLIC], RecordingConnector()).connect_tcp("shop.example.com", 8080)
    assert port.value.refusal is UrlRefusal.DISALLOWED_PORT
    with pytest.raises(UnsafeDestinationError):
        PinnedNetworkBackend(lambda h: [PUBLIC], RecordingConnector()).connect_tcp("metadata.google.internal", 80)
    with pytest.raises(UnsafeDestinationError):
        PinnedNetworkBackend(lambda h: [PUBLIC], RecordingConnector()).connect_unix_socket("/tmp/x")


def test_resolution_happens_only_inside_the_connect_step():
    """The connector receives IP literals only: it can never re-resolve a name."""
    connector = RecordingConnector()
    PinnedNetworkBackend(lambda h: [PUBLIC_2, PUBLIC], connector).connect_tcp("shop.example.com", 443)
    assert connector.attempted == [PUBLIC_2]
