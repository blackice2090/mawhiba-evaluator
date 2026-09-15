"""Live official web provider over httpx.

Used only by explicit opt-in (RUN_OFFICIAL_WEB_TESTS=1 or a production caller).
Redirects are followed manually so every hop is checked against the allowlist;
automatic redirect following could land on a third-party host unobserved.
"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from src.intake.anchors import collapse_whitespace
from src.research.official.allowlist import check_official_url
from src.schemas.official import OfficialRetrievalResult, RetrievalStatus

USER_AGENT = "mawhiba-evaluator-official-requirements/1.0"
SUPPORTED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td",
     "th", "section", "article", "header", "footer", "table", "main", "nav"}
)


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self.published_raw: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            values = dict(attrs)
            key = (values.get("property") or values.get("name") or "").lower()
            if key == "article:published_time" and values.get("content"):
                self.published_raw = values["content"]
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        (self.title_parts if self._in_title else self.parts).append(data)


def _explicit_datetime(raw: str | None) -> datetime | None:
    """Only a timezone-aware ISO timestamp is accepted. Nothing is guessed."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def extract_page_text(html: str) -> tuple[str, str | None, datetime | None]:
    """Visible text, title and explicit publication time of an HTML page."""
    parser = _PageTextParser()
    parser.feed(html)
    parser.close()
    lines = [collapse_whitespace(line) for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    title = collapse_whitespace("".join(parser.title_parts)) or None
    return text, title, _explicit_datetime(parser.published_raw)


class HttpOfficialWebProvider:
    name = "http_official_web"

    def __init__(
        self,
        client: Any | None = None,
        *,
        timeout_seconds: float = 15.0,
        max_redirects: int = 3,
        max_bytes: int = 2_000_000,
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds
        self._max_redirects = max_redirects
        self._max_bytes = max_bytes

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    def _failure(
        self,
        status: RetrievalStatus,
        url: str,
        current: str,
        error: str,
        http_status: int | None = None,
    ) -> OfficialRetrievalResult:
        return OfficialRetrievalResult(
            status=status,
            requested_url=url,
            final_url=current,
            http_status=http_status,
            error=error,
            provider=self.name,
        )

    def retrieve(self, url: str) -> OfficialRetrievalResult:
        import httpx

        if check_official_url(url) is not None:
            return self._failure(
                RetrievalStatus.BLOCKED_NOT_ALLOWLISTED, url, url,
                "requested URL is not on the official allowlist",
            )

        current = url
        for _ in range(self._max_redirects + 1):
            try:
                response = self.client.get(current)
            except httpx.TimeoutException as exc:
                return self._failure(RetrievalStatus.TIMEOUT, url, current, type(exc).__name__)
            except httpx.HTTPError as exc:
                return self._failure(RetrievalStatus.NETWORK_ERROR, url, current, type(exc).__name__)

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return self._failure(
                        RetrievalStatus.HTTP_ERROR, url, current,
                        "redirect without a location", response.status_code,
                    )
                target = urljoin(current, location)
                if check_official_url(target) is not None:
                    return self._failure(
                        RetrievalStatus.BLOCKED_NOT_ALLOWLISTED, url, target,
                        "redirect left the official allowlist",
                    )
                current = target
                continue

            if response.status_code != 200:
                return self._failure(
                    RetrievalStatus.HTTP_ERROR, url, current,
                    f"HTTP {response.status_code}", response.status_code,
                )
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in SUPPORTED_CONTENT_TYPES:
                return self._failure(
                    RetrievalStatus.UNSUPPORTED_CONTENT, url, current,
                    f"unsupported content type {content_type or 'unknown'}", 200,
                )
            if len(response.content) > self._max_bytes:
                return self._failure(
                    RetrievalStatus.TOO_LARGE, url, current, "response exceeds max_bytes", 200
                )

            if content_type == "text/plain":
                text, title, published = response.text, None, None
            else:
                text, title, published = extract_page_text(response.text)
            if not text.strip():
                return self._failure(
                    RetrievalStatus.EMPTY_CONTENT, url, current, "page has no visible text", 200
                )
            return OfficialRetrievalResult(
                status=RetrievalStatus.SUCCESS,
                requested_url=url,
                final_url=current,
                http_status=200,
                content_type=content_type,
                title=title,
                text=text,
                published_at=published,
                provider=self.name,
            )

        return self._failure(RetrievalStatus.HTTP_ERROR, url, current, "too many redirects")
