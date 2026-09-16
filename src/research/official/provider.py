"""The official web provider seam, plus a deterministic fake.

Official-requirements logic depends on this Protocol, never on an HTTP library.
A provider is untrusted: whatever it returns is re-checked by source verification,
including the allowlist, so a misbehaving provider cannot create an official source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from src.schemas.official import OfficialRetrievalResult, RetrievalStatus


class OfficialWebProvider(Protocol):
    """Retrieves one URL. Never raises for a retrieval outcome."""

    name: str

    def retrieve(self, url: str) -> OfficialRetrievalResult: ...


FAKE_RETRIEVED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeOfficialPage:
    text: str
    title: str | None = None
    final_url: str | None = None
    published_at: datetime | None = None
    effective_at: datetime | None = None
    content_type: str = "text/html"


class FakeOfficialWebProvider:
    """Scripted pages keyed by URL. Records every URL it was asked for.

    It deliberately does not enforce the allowlist: tests need a provider that
    can misbehave so the verifier's own enforcement is exercised.
    """

    name = "fake_official_web"

    def __init__(
        self,
        pages: Mapping[str, FakeOfficialPage | RetrievalStatus] | None = None,
        *,
        retrieved_at: datetime = FAKE_RETRIEVED_AT,
    ) -> None:
        self._pages = dict(pages or {})
        self._retrieved_at = retrieved_at
        self.calls: list[str] = []

    def retrieve(self, url: str) -> OfficialRetrievalResult:
        self.calls.append(url)
        page = self._pages.get(url)
        if page is None:
            return OfficialRetrievalResult(
                status=RetrievalStatus.HTTP_ERROR,
                requested_url=url,
                http_status=404,
                error="fake provider has no page for this URL",
                retrieved_at=self._retrieved_at,
                provider=self.name,
            )
        if isinstance(page, RetrievalStatus):
            return OfficialRetrievalResult(
                status=page,
                requested_url=url,
                error=f"scripted retrieval failure: {page.value}",
                retrieved_at=self._retrieved_at,
                provider=self.name,
            )
        return OfficialRetrievalResult(
            status=RetrievalStatus.SUCCESS,
            requested_url=url,
            final_url=page.final_url or url,
            http_status=200,
            content_type=page.content_type,
            title=page.title,
            text=page.text,
            published_at=page.published_at,
            effective_at=page.effective_at,
            retrieved_at=self._retrieved_at,
            provider=self.name,
        )
