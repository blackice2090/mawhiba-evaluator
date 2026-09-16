"""Strict official-domain allowlist.

Exact host matching only. There is no wildcard subdomain rule: a subdomain is
official only when it is listed here after being confirmed as Mawhiba-controlled.
Lookalike hosts, userinfo tricks, non-HTTPS schemes and non-default ports are all
rejected, so a third-party page can never receive official source status.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from src.schemas.official import SourceRejectionReason

OFFICIAL_DOMAIN_ALLOWLIST: frozenset[str] = frozenset(
    {"mawhiba.sa", "www.mawhiba.sa", "mawhiba2.mawhiba.sa"}
)
"""Exact hosts confirmed to be Mawhiba-controlled.

``mawhiba2.mawhiba.sa`` serves the current Mawhiba service experience, including
the National Olympiad for Scientific Creativity service page, so omitting it made
the system reject a legitimate official source.

There is deliberately no ``*.mawhiba.sa`` rule: a wildcard would admit any
present or future subdomain, including one that is delegated, parked or
compromised, on nothing more than a name pattern. A new host joins this set only
after a reviewer confirms ownership, which is a cheap, auditable step.
"""

OFFICIAL_ROOT_URL = "https://www.mawhiba.sa/"
"""Discovery entry point. Not a rules page, and not a default seed."""

OFFICIAL_IBDAA_SERVICE_URL = (
    "https://mawhiba2.mawhiba.sa/services/"
    "the-national-olympiad-for-scientific-creativity-ibdaa/"
)
"""The National Olympiad for Scientific Creativity service page.

An evergreen service page: it describes the programme rather than one edition's
event. Edition-specific pages must be configured explicitly, with their edition
declared, and are never assumed current.
"""

DEFAULT_OFFICIAL_SEED_URL = OFFICIAL_IBDAA_SERVICE_URL
"""Backwards-compatible alias for the default seed URL."""


def _host(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def check_official_url(url: str) -> SourceRejectionReason | None:
    """None when the URL is an allowlisted official HTTPS URL, else the reason."""
    candidate = url.strip()
    if "\\" in candidate or any(ch.isspace() for ch in candidate):
        return SourceRejectionReason.DOMAIN_NOT_ALLOWLISTED
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError:
        return SourceRejectionReason.DOMAIN_NOT_ALLOWLISTED
    if parts.scheme.lower() != "https":
        return SourceRejectionReason.INSECURE_SCHEME
    if parts.username is not None or parts.password is not None:
        return SourceRejectionReason.DOMAIN_NOT_ALLOWLISTED
    if port not in (None, 443):
        return SourceRejectionReason.DOMAIN_NOT_ALLOWLISTED
    if _host(candidate) not in OFFICIAL_DOMAIN_ALLOWLIST:
        return SourceRejectionReason.DOMAIN_NOT_ALLOWLISTED
    return None


def is_official_url(url: str) -> bool:
    return check_official_url(url) is None


def official_domain(url: str) -> str:
    host = _host(url)
    if host is None or host not in OFFICIAL_DOMAIN_ALLOWLIST:
        raise ValueError(f"not an official Mawhiba URL: {url!r}")
    return host


def canonicalize_url(url: str) -> str:
    """Lowercase scheme and host, drop the default port and the fragment."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").rstrip(".").lower()
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))
