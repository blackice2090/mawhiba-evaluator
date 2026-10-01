"""Deterministic offline fakes for Phase 2H -- section 39.

Each fake answers from a script and records every request it received, so a
test can assert what was (and was not) sent. Script lookup for a search is by
exact query text, then purpose, then operation, then ``"*"``, which lets a
Gold case script a provider without restating planner output verbatim.

A scripted error is a ``DiscoveryErrorKind``; a list of scripted entries is
consumed one per call, which is how retries and transient failures are
scripted. Nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.research.discovery.execution import SearchPage
from src.research.discovery.safe_fetch import FetchTransportError, RawResponse
from src.research.discovery.transport import DiscoveryTransportError
from src.research.open_source.github import FileContent, RepositoryHit
from src.research.product.brave import WebSearchHit
from src.schemas.discovery import DiscoveryErrorKind, DiscoveryQuery

def _raise_if_error(entry: Any) -> None:
    if isinstance(entry, DiscoveryErrorKind):
        raise DiscoveryTransportError(entry, f"scripted {entry.value}", http_status=None)


def _lookup(script: dict[str, Any], query: DiscoveryQuery) -> Any:
    for key in (query.query_text, query.purpose.value, query.operation.value, "*"):
        if f"seq:{key}" in script:
            sequence = script[f"seq:{key}"]
            return sequence.pop(0) if len(sequence) > 1 else sequence[0]
        if key in script:
            return script[key]
    return None


@dataclass
class FakeWebSearchProvider:
    """Script values: list[dict(url,title,snippet,date)] | DiscoveryErrorKind |
    dict(pages=[...], more=bool). Pages are 1-based."""

    script: dict[str, Any] = field(default_factory=dict)
    requests: list[tuple[str, int, int]] = field(default_factory=list)

    def search(self, query: DiscoveryQuery, *, page: int, count: int) -> SearchPage:
        self.requests.append((query.query_text, page, count))
        entry = _lookup(self.script, query)
        _raise_if_error(entry)
        if entry is None:
            return SearchPage()
        if isinstance(entry, dict):
            pages = entry.get("pages", [])
            hits = pages[page - 1] if page - 1 < len(pages) else []
            more = bool(entry.get("more")) or page < len(pages)
        else:
            hits, more = entry, False
        # Every scripted hit is returned, even beyond ``count``, so a provider
        # that over-returns can be scripted and its surplus seen as truncated.
        return SearchPage(
            items=[WebSearchHit(h["url"], h.get("title", ""), h.get("snippet", ""), h.get("date")) for h in hits],
            more_available=more,
        )


@dataclass
class FakeFetchTransport:
    """routes: url -> RawResponse | DiscoveryErrorKind (TIMEOUT/CONNECTION_ERROR)."""

    routes: dict[str, Any] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def get(self, url: str, *, max_bytes: int, timeout: float) -> RawResponse:
        self.requests.append(url)
        entry = self.routes.get(url)
        if isinstance(entry, DiscoveryErrorKind):
            raise FetchTransportError(entry)
        if entry is None:
            return RawResponse(status=404, headers={"content-type": "text/html"}, body=b"")
        if len(entry.body) > max_bytes:
            return RawResponse(status=entry.status, headers=entry.headers, body=entry.body[:max_bytes], over_limit=True)
        return entry


def html_page(body: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8") -> RawResponse:
    return RawResponse(status=status, headers={"content-type": content_type}, body=body.encode("utf-8"))


def redirect(location: str, status: int = 302) -> RawResponse:
    return RawResponse(status=status, headers={"location": location}, body=b"")


@dataclass
class FakeResolver:
    """host -> addresses. An unknown host resolves to a public documentation address."""

    table: dict[str, list[str]] = field(default_factory=dict)
    default: tuple[str, ...] = ("93.184.216.34",)

    def __call__(self, host: str) -> list[str]:
        if host in self.table:
            return list(self.table[host])
        return list(self.default)


@dataclass
class FakeGitHubProvider:
    """Scripted GitHub.

    ``search``: query key -> list[dict] hits | DiscoveryErrorKind | dict(pages, total, incomplete)
    ``repos``:  full_name -> repository JSON dict | DiscoveryErrorKind
    ``readmes`` / ``contents``: full_name or "full_name:path" -> dict(path, text, sha, size)
    ``releases``: full_name -> list[dict] | DiscoveryErrorKind
    ``commits``: full_name -> dict | DiscoveryErrorKind
    """

    authenticated: bool = False
    search: dict[str, Any] = field(default_factory=dict)
    repos: dict[str, Any] = field(default_factory=dict)
    readmes: dict[str, Any] = field(default_factory=dict)
    contents: dict[str, Any] = field(default_factory=dict)
    releases: dict[str, Any] = field(default_factory=dict)
    commits: dict[str, Any] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)

    def _search(self, kind: str, query: str, page: int, count: int) -> SearchPage:
        self.requests.append((kind, query))
        entry = None
        for key in (query, f"{kind}:*", "*"):
            if f"seq:{key}" in self.search:
                sequence = self.search[f"seq:{key}"]
                entry = sequence.pop(0) if len(sequence) > 1 else sequence[0]
                break
            if key in self.search:
                entry = self.search[key]
                break
        _raise_if_error(entry)
        if entry is None:
            return SearchPage(provider_total=0)
        if isinstance(entry, dict):
            pages = entry.get("pages", [])
            hits = pages[page - 1] if page - 1 < len(pages) else []
            total = entry.get("total")
            incomplete = bool(entry.get("incomplete"))
        else:
            hits, total, incomplete = entry, len(entry), False
        fetched = sum(len(p) for p in (entry.get("pages", [])[: page - 1] if isinstance(entry, dict) else []))
        items = [
            RepositoryHit(
                repository_id=h["id"],
                node_id=h.get("node_id", f"R_{h['id']}"),
                full_name=h["full_name"],
                html_url=f"https://github.com/{h['full_name']}",
                code_path=h.get("path") if kind == "code" else None,
                code_sha=h.get("sha") if kind == "code" else None,
                fragment=h.get("fragment") if kind == "code" else None,
            )
            for h in hits
        ]
        return SearchPage(
            items=items,
            provider_total=total,
            more_available=bool(total is not None and fetched + len(hits) < total),
            incomplete_results=incomplete,
        )

    def search_repositories(self, query: str, *, page: int, count: int) -> SearchPage:
        return self._search("repo", query, page, count)

    def search_code(self, query: str, *, page: int, count: int) -> SearchPage:
        if not self.authenticated:
            raise DiscoveryTransportError(DiscoveryErrorKind.AUTHENTICATION_ERROR, "code search requires authentication")
        return self._search("code", query, page, count)

    def get_repository(self, full_name: str) -> dict[str, Any]:
        self.requests.append(("repo_meta", full_name))
        entry = self.repos.get(full_name)
        _raise_if_error(entry)
        if entry is None:
            raise DiscoveryTransportError(DiscoveryErrorKind.UNSUPPORTED_OPERATION, "not found", http_status=404)
        return dict(entry)

    def _file(self, store: dict[str, Any], key: str) -> FileContent:
        entry = store.get(key)
        _raise_if_error(entry)
        if entry is None:
            raise DiscoveryTransportError(DiscoveryErrorKind.UNSUPPORTED_OPERATION, "not found", http_status=404)
        return FileContent(path=entry["path"], sha=entry.get("sha"), size=entry.get("size"), text=entry.get("text"))

    def get_readme(self, full_name: str, ref: str | None) -> FileContent:
        self.requests.append(("readme", full_name))
        return self._file(self.readmes, full_name)

    def get_content(self, full_name: str, path: str, ref: str | None) -> FileContent:
        self.requests.append(("content", f"{full_name}:{path}"))
        return self._file(self.contents, f"{full_name}:{path}")

    def list_releases(self, full_name: str, *, count: int) -> list[dict[str, Any]]:
        self.requests.append(("releases", full_name))
        entry = self.releases.get(full_name, [])
        _raise_if_error(entry)
        return list(entry)[:count]

    def get_head_commit(self, full_name: str, ref: str | None) -> dict[str, Any] | None:
        self.requests.append(("commit", full_name))
        entry = self.commits.get(full_name)
        _raise_if_error(entry)
        return entry


def github_repo(
    rid: int,
    full_name: str,
    *,
    fork: bool = False,
    parent: tuple[int, str] | None = None,
    source: tuple[int, str] | None = None,
    mirror_url: str | None = None,
    template: tuple[int, str] | None = None,
    archived: bool = False,
    license_spdx: str | None = "MIT",
    topics: tuple[str, ...] = (),
    language: str | None = "Python",
    description: str | None = "A repository.",
    created_at: str | None = "2019-03-01T10:00:00Z",
    stars: int = 0,
    default_branch: str = "main",
) -> dict[str, Any]:
    """A GitHub repository JSON object in the documented shape."""
    payload: dict[str, Any] = {
        "id": rid,
        "node_id": f"R_{rid}",
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "fork": fork,
        "archived": archived,
        "disabled": False,
        "visibility": "public",
        "default_branch": default_branch,
        "license": None if license_spdx is None else {"key": license_spdx.lower(), "spdx_id": license_spdx, "name": license_spdx},
        "topics": list(topics),
        "language": language,
        "description": description,
        "created_at": created_at,
        "updated_at": "2025-01-01T00:00:00Z",
        "pushed_at": "2025-01-01T00:00:00Z",
        "mirror_url": mirror_url,
        "is_template": False,
        "stargazers_count": stars,
        "forks_count": 0,
        "watchers_count": stars,
    }
    if parent:
        payload["parent"] = {"id": parent[0], "full_name": parent[1]}
    if source:
        payload["source"] = {"id": source[0], "full_name": source[1]}
    if template:
        payload["template_repository"] = {"id": template[0], "full_name": template[1]}
    return payload


__all__ = [
    "FakeFetchTransport",
    "FakeGitHubProvider",
    "FakeResolver",
    "FakeWebSearchProvider",
    "github_repo",
    "html_page",
    "redirect",
]
