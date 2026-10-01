"""GitHub REST connector -- section 4.

Contract (verified 2026-10-01 against docs.github.com; documented-only until a
live request succeeds):

    Accept: application/vnd.github+json
    X-GitHub-Api-Version: 2026-03-10
    GET /search/repositories?q&per_page(<=100)&page   -> total_count, incomplete_results, items[]
    GET /search/code?q&per_page&page                   -> AUTHENTICATION REQUIRED
        items[]: name, path, sha, repository{id,node_id,full_name,html_url}, text_matches[].fragment
        (text-match fragments need Accept: application/vnd.github.text-match+json)
    GET /repos/{owner}/{repo}                          -> id, node_id, fork, parent, source,
        archived, disabled, visibility, default_branch, license{spdx_id}, topics,
        created_at, updated_at, pushed_at, mirror_url, is_template, template_repository
    GET /repos/{owner}/{repo}/readme[?ref]             -> path, sha, size, encoding=base64, content
    GET /repos/{owner}/{repo}/contents/{path}[?ref]    -> same shape; content empty above 1 MB
    GET /repos/{owner}/{repo}/releases?per_page        -> id, tag_name, created_at, published_at
    GET /repos/{owner}/{repo}/commits?sha&per_page=1   -> sha, commit.author.date, commit.committer.date

Search returns at most 1,000 results. Rate limits: 60/h unauthenticated,
5,000/h authenticated; search 10/min unauthenticated, 30/min authenticated,
code search 10/min. 403/429 with ``retry-after`` or ``x-ratelimit-remaining: 0``
is a rate limit; any other 403 is an authorization failure.

The token lives only on the instance and in the ``Authorization`` header. It
is never placed on the run, logged, or echoed into an error.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from src.research.discovery.capabilities import (
    GITHUB_ACCEPT,
    GITHUB_API_BASE,
    GITHUB_API_VERSION,
    GITHUB_MAX_PER_PAGE,
    GITHUB_SEARCH_RESULT_CAP,
    GITHUB_TEXT_MATCH_ACCEPT,
)
from src.research.discovery.execution import SearchPage
from src.research.discovery.transport import (
    DiscoveryTransportError,
    classify_status,
    retry_after_from,
)
from src.schemas.discovery import DiscoveryErrorKind


@dataclass(frozen=True)
class RepositoryHit:
    repository_id: int
    node_id: str | None
    full_name: str
    html_url: str
    code_path: str | None = None
    code_sha: str | None = None
    fragment: str | None = None


@dataclass(frozen=True)
class FileContent:
    path: str
    sha: str | None
    size: int | None
    text: str | None
    """Decoded text, or None when the provider did not return inline content."""


class GitHubProvider(Protocol):
    authenticated: bool

    def search_repositories(self, query: str, *, page: int, count: int) -> SearchPage: ...
    def search_code(self, query: str, *, page: int, count: int) -> SearchPage: ...
    def get_repository(self, full_name: str) -> dict[str, Any]: ...
    def get_readme(self, full_name: str, ref: str | None) -> FileContent: ...
    def get_content(self, full_name: str, path: str, ref: str | None) -> FileContent: ...
    def list_releases(self, full_name: str, *, count: int) -> list[dict[str, Any]]: ...
    def get_head_commit(self, full_name: str, ref: str | None) -> dict[str, Any] | None: ...


def _hit(item: dict[str, Any], repo: dict[str, Any] | None = None) -> RepositoryHit | None:
    repo = repo if repo is not None else item
    rid = repo.get("id")
    full_name = repo.get("full_name")
    if not isinstance(rid, int) or rid < 1 or not isinstance(full_name, str) or "/" not in full_name:
        return None
    return RepositoryHit(
        repository_id=rid,
        node_id=repo.get("node_id") if isinstance(repo.get("node_id"), str) else None,
        full_name=full_name,
        html_url=str(repo.get("html_url") or ""),
    )


def parse_repository_search(payload: Any, *, fetched_before: int, count: int) -> SearchPage:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "search response has no items list")
    hits = [h for h in (_hit(i) for i in payload["items"] if isinstance(i, dict)) if h is not None]
    total = payload.get("total_count") if isinstance(payload.get("total_count"), int) else None
    # A total above GITHUB_SEARCH_RESULT_CAP is still "more": the matches past
    # the cap exist but can never be retrieved, so the search stays partial.
    return SearchPage(
        items=hits,
        provider_total=total,
        more_available=bool(total is not None and fetched_before + len(payload["items"]) < total),
        incomplete_results=bool(payload.get("incomplete_results")),
    )


def parse_code_search(payload: Any, *, fetched_before: int, count: int) -> SearchPage:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "search response has no items list")
    hits: list[RepositoryHit] = []
    for item in payload["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("repository"), dict):
            continue
        base = _hit(item, item["repository"])
        if base is None or not isinstance(item.get("path"), str):
            continue
        fragments = [
            m.get("fragment") for m in item.get("text_matches") or [] if isinstance(m, dict) and isinstance(m.get("fragment"), str)
        ]
        hits.append(
            RepositoryHit(
                repository_id=base.repository_id,
                node_id=base.node_id,
                full_name=base.full_name,
                html_url=base.html_url,
                code_path=item["path"],
                code_sha=item.get("sha") if isinstance(item.get("sha"), str) else None,
                fragment=fragments[0][:2000] if fragments else None,
            )
        )
    total = payload.get("total_count") if isinstance(payload.get("total_count"), int) else None
    return SearchPage(
        items=hits,
        provider_total=total,
        more_available=bool(total is not None and fetched_before + len(payload["items"]) < total),
        incomplete_results=bool(payload.get("incomplete_results")),
    )


def decode_content(payload: Any, max_bytes: int) -> FileContent:
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "content response has no path")
    size = payload.get("size") if isinstance(payload.get("size"), int) else None
    text: str | None = None
    if payload.get("encoding") == "base64" and isinstance(payload.get("content"), str) and payload["content"]:
        try:
            raw = base64.b64decode(payload["content"], validate=False)
        except (binascii.Error, ValueError) as exc:
            raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "content is not base64") from exc
        text = raw[:max_bytes].decode("utf-8", errors="replace")
    return FileContent(path=payload["path"], sha=payload.get("sha"), size=size, text=text)


class GitHubRestProvider:
    """Live GitHub REST connector. Unauthenticated use is allowed; code search is not."""

    provider_name = "GITHUB_REST"

    def __init__(
        self,
        token: str | None = None,
        client: Any | None = None,
        *,
        timeout_seconds: float = 20.0,
        max_content_bytes: int = 200_000,
    ) -> None:
        self._token = token or None
        self._client = client
        self._timeout = timeout_seconds
        self._max_content_bytes = max_content_bytes

    def __repr__(self) -> str:
        return f"GitHubRestProvider(authenticated={self.authenticated})"

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout, trust_env=False, follow_redirects=False)
        return self._client

    def _headers(self, accept: str = GITHUB_ACCEPT) -> dict[str, str]:
        headers = {"Accept": accept, "X-GitHub-Api-Version": GITHUB_API_VERSION}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None, accept: str = GITHUB_ACCEPT) -> Any:
        import httpx

        url = f"{GITHUB_API_BASE}{path}"
        for _ in range(3):
            try:
                response = self.client.get(url, params=params, headers=self._headers(accept))
            except httpx.TimeoutException as exc:
                raise DiscoveryTransportError(DiscoveryErrorKind.TIMEOUT, "request timed out") from exc
            except httpx.HTTPError as exc:
                raise DiscoveryTransportError(DiscoveryErrorKind.CONNECTION_ERROR, type(exc).__name__) from exc
            if response.status_code in (301, 302, 307, 308):
                # Renamed or transferred repositories redirect. Only an
                # api.github.com target is followed; identity is still the id.
                location = response.headers.get("location", "")
                if not location.startswith(GITHUB_API_BASE + "/"):
                    raise DiscoveryTransportError(DiscoveryErrorKind.FETCH_UNSAFE, "redirect left api.github.com")
                url, params = location, None
                continue
            headers = dict(response.headers)
            kind = classify_status(response.status_code, headers)
            if kind is not None:
                raise DiscoveryTransportError(
                    kind, f"HTTP {response.status_code}",
                    http_status=response.status_code, retry_after_seconds=retry_after_from(headers),
                )
            try:
                return response.json()
            except ValueError as exc:
                raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "malformed JSON") from exc
        raise DiscoveryTransportError(DiscoveryErrorKind.PROVIDER_ERROR, "too many redirects")

    @staticmethod
    def _repo_path(full_name: str) -> str:
        owner, _, name = full_name.partition("/")
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def search_repositories(self, query: str, *, page: int, count: int) -> SearchPage:
        per_page = min(count, GITHUB_MAX_PER_PAGE)
        payload = self._get("/search/repositories", {"q": query, "per_page": per_page, "page": page})
        return parse_repository_search(payload, fetched_before=(page - 1) * per_page, count=per_page)

    def search_code(self, query: str, *, page: int, count: int) -> SearchPage:
        if not self.authenticated:
            raise DiscoveryTransportError(DiscoveryErrorKind.AUTHENTICATION_ERROR, "code search requires authentication")
        per_page = min(count, GITHUB_MAX_PER_PAGE)
        payload = self._get(
            "/search/code", {"q": query, "per_page": per_page, "page": page}, accept=GITHUB_TEXT_MATCH_ACCEPT
        )
        return parse_code_search(payload, fetched_before=(page - 1) * per_page, count=per_page)

    def get_repository(self, full_name: str) -> dict[str, Any]:
        payload = self._get(self._repo_path(full_name))
        if not isinstance(payload, dict):
            raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "repository is not an object")
        return payload

    def get_readme(self, full_name: str, ref: str | None) -> FileContent:
        return decode_content(
            self._get(f"{self._repo_path(full_name)}/readme", {"ref": ref} if ref else None),
            self._max_content_bytes,
        )

    def get_content(self, full_name: str, path: str, ref: str | None) -> FileContent:
        return decode_content(
            self._get(f"{self._repo_path(full_name)}/contents/{quote(path)}", {"ref": ref} if ref else None),
            self._max_content_bytes,
        )

    def list_releases(self, full_name: str, *, count: int) -> list[dict[str, Any]]:
        payload = self._get(f"{self._repo_path(full_name)}/releases", {"per_page": min(count, 100)})
        if not isinstance(payload, list):
            raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "releases is not a list")
        return [r for r in payload if isinstance(r, dict)]

    def get_head_commit(self, full_name: str, ref: str | None) -> dict[str, Any] | None:
        params: dict[str, Any] = {"per_page": 1}
        if ref:
            params["sha"] = ref
        payload = self._get(f"{self._repo_path(full_name)}/commits", params)
        if not isinstance(payload, list):
            raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "commits is not a list")
        return payload[0] if payload and isinstance(payload[0], dict) else None


__all__ = [
    "FileContent",
    "GitHubProvider",
    "GitHubRestProvider",
    "RepositoryHit",
    "decode_content",
    "parse_code_search",
    "parse_repository_search",
]
