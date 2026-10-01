"""Phase 2H Gold dataset: reviewable JSONL cases and their offline fakes.

A case describes a whole synthetic world: canonical claims, an optional
privacy context and cutoff, scripted web-search results, scripted product
pages (served through the real SSRF-safe fetcher via a fake transport and a
fake resolver), and a scripted GitHub. Expectations are authored from that
world, never generated from system output. Schema: ``evals/product_oss_prior_art/v1/schema.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.research.discovery.fakes import (
    FakeFetchTransport,
    FakeGitHubProvider,
    FakeResolver,
    FakeWebSearchProvider,
    github_repo,
    html_page,
    redirect,
)
from src.research.discovery.safe_fetch import RawResponse, SafeWebFetcher
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.product.roles import HostRegistry, VendorDomain, VendorPageKind
from src.research.settings import OpenSourceResearchSettings, ProductResearchSettings, ResearchSettings
from src.schemas.discovery import NO_DISCOVERY_CUTOFF, DiscoveryCutoff, DiscoveryErrorKind

DATASET_VERSION = "phase2h-gold-v1"
DEFAULT_DATASET = Path("evals/product_oss_prior_art/v1/cases.jsonl")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldClaim(_Strict):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    claim: str


class GoldPrivacy(_Strict):
    person_names: list[str] = Field(default_factory=list)
    school_names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class GoldPage(_Strict):
    """One scripted URL. ``kind``: html | redirect | error | status."""

    kind: Literal["html", "redirect", "error", "status"] = "html"
    title: str = "Page"
    body: str = "<p>text</p>"
    json_ld: list[dict[str, Any]] = Field(default_factory=list)
    meta_published: str | None = None
    content_type: str = "text/html; charset=utf-8"
    location: str | None = None
    error: str | None = None
    status: int = 200
    pad_bytes: int = 0
    raw: str | None = None


class GoldVendor(_Strict):
    host: str
    vendor: str
    kind: Literal["PRODUCT_PAGE", "DOCUMENTATION", "PRESS_RELEASE"] = "PRODUCT_PAGE"


class GoldProduct(_Strict):
    provider: bool = True
    fetcher: bool = True
    web: dict[str, Any] = Field(default_factory=dict)
    pages: dict[str, GoldPage] = Field(default_factory=dict)
    resolver: dict[str, list[str]] = Field(default_factory=dict)
    vendors: list[GoldVendor] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class GoldOss(_Strict):
    provider: bool = True
    authenticated: bool = False
    token: str | None = None
    search: dict[str, Any] = Field(default_factory=dict)
    repos: dict[str, dict[str, Any]] = Field(default_factory=dict)
    readmes: dict[str, Any] = Field(default_factory=dict)
    contents: dict[str, Any] = Field(default_factory=dict)
    releases: dict[str, Any] = Field(default_factory=dict)
    commits: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProductOssGoldCase(_Strict):
    case_id: str = Field(pattern=r"^PH-\d{3,}$")
    language: Literal["en", "ar", "mixed"]
    tracks: list[Literal["product", "oss"]] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    description: str = ""
    claims: list[GoldClaim] = Field(min_length=1)
    privacy: GoldPrivacy | None = None
    cutoff: dict[str, str] | None = None
    product: GoldProduct = Field(default_factory=GoldProduct)
    oss: GoldOss = Field(default_factory=GoldOss)
    interrupt_before: str | None = None
    rerun: bool = False
    negative_controls: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expected")
    @classmethod
    def _expected_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("every Gold case states authored expectations")
        return value


def load_cases(path: Path = DEFAULT_DATASET) -> list[ProductOssGoldCase]:
    cases = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(ProductOssGoldCase.model_validate_json(line))
            except Exception as exc:  # pragma: no cover - surfaced to the reviewer
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    return cases


# ---------------------------------------------------------------------------
# World construction
# ---------------------------------------------------------------------------


def _error(name: str | None) -> DiscoveryErrorKind:
    return DiscoveryErrorKind(name or "PROVIDER_ERROR")


def _script(value: Any) -> Any:
    """JSON script -> fake script: {"error": KIND} becomes a DiscoveryErrorKind."""
    if isinstance(value, dict) and set(value) == {"error"}:
        return _error(value["error"])
    if isinstance(value, list):
        return [_script(v) for v in value]
    if isinstance(value, dict):
        return {k: _script(v) for k, v in value.items()}
    return value


def render_page(page: GoldPage) -> RawResponse | DiscoveryErrorKind:
    if page.kind == "redirect":
        return redirect(page.location or "/", status=page.status if 300 <= page.status < 400 else 302)
    if page.kind == "error":
        return _error(page.error)
    if page.raw is not None:
        return html_page(page.raw, content_type=page.content_type, status=page.status)
    ld = "".join(f'<script type="application/ld+json">{json.dumps(obj)}</script>' for obj in page.json_ld)
    meta = f'<meta property="article:published_time" content="{page.meta_published}">' if page.meta_published else ""
    padding = f"<p>{'x' * page.pad_bytes}</p>" if page.pad_bytes else ""
    html = f"<html><head><title>{page.title}</title>{meta}{ld}</head><body><h1>{page.title}</h1>{page.body}{padding}</body></html>"
    return html_page(html, content_type=page.content_type, status=page.status)


class CaseWorld:
    """The fakes and configuration for one case. Records every request."""

    def __init__(self, case: ProductOssGoldCase) -> None:
        self.case = case
        self.web = FakeWebSearchProvider(_script(case.product.web)) if case.product.provider else None
        self.transport = FakeFetchTransport({url: render_page(page) for url, page in case.product.pages.items()})
        self.resolver = FakeResolver(case.product.resolver)
        settings = ProductResearchSettings(**case.product.settings)
        self.product_settings = settings
        self.fetcher = (
            SafeWebFetcher(
                self.transport, resolver=self.resolver, max_redirects=settings.max_redirects,
                max_bytes=settings.max_artifact_bytes,
            )
            if case.product.fetcher
            else None
        )
        self.registry = HostRegistry(
            vendor_domains=tuple(VendorDomain(v.host, v.vendor, VendorPageKind(v.kind)) for v in case.product.vendors)
        )
        oss = case.oss
        self.github = (
            FakeGitHubProvider(
                authenticated=oss.authenticated,
                search=_script(oss.search),
                repos={name: (_error(spec["error"]) if "error" in spec else github_repo(**spec)) for name, spec in oss.repos.items()},
                readmes=_script(oss.readmes),
                contents=_script(oss.contents),
                releases=_script(oss.releases),
                commits=_script(oss.commits),
            )
            if oss.provider
            else None
        )
        if self.github is not None and oss.token:
            # A credential-bearing attribute: section 43 gate 61 checks it never
            # reaches the persisted state.
            self.github.token = oss.token  # type: ignore[attr-defined]
        self.oss_settings = OpenSourceResearchSettings(**oss.settings)
        self.settings = ResearchSettings(product=settings, open_source=self.oss_settings)
        self.cutoff = (
            DiscoveryCutoff(cutoff_date=case.cutoff["date"], source=case.cutoff.get("source", "gold"))
            if case.cutoff
            else NO_DISCOVERY_CUTOFF
        )
        self.privacy = (
            ResearchPrivacyContext.from_identity(
                person_names=tuple(case.privacy.person_names),
                school_names=tuple(case.privacy.school_names),
                emails=tuple(case.privacy.emails),
            )
            if case.privacy
            else EMPTY_PRIVACY_CONTEXT
        )


__all__ = [
    "DATASET_VERSION",
    "DEFAULT_DATASET",
    "CaseWorld",
    "GoldClaim",
    "GoldOss",
    "GoldPage",
    "GoldProduct",
    "ProductOssGoldCase",
    "load_cases",
    "render_page",
]
