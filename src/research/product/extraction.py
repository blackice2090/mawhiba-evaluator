"""Deterministic extraction from a fetched product page -- sections 15, 16, 18.

Read only: the HTML title, h1-h3 headings, visible text (bounded), schema.org
JSON-LD ``Product`` / ``SoftwareApplication`` objects, and explicit page-date
meta tags. Identifiers come ONLY from structured data, never from free text or
from a title: a model number mentioned in a review paragraph is not the page
asserting an identity.

Every date is source-reported. Nothing here decides that a product existed or
was available on any date.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from src.intake.anchors import collapse_whitespace
from src.schemas.product_prior_art import (
    MAX_PRODUCT_TEXT_CHARS,
    ProductIdentifier,
    ProductIdentifierKind,
)

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe"})
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td",
     "th", "section", "article", "header", "footer", "table", "main", "nav"}
)
_HEADINGS = frozenset({"h1", "h2", "h3"})
_DATE_META = {
    "article:published_time": "page_published",
    "datepublished": "page_published",
    "og:published_time": "page_published",
}
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_PACKAGE_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$")
MAX_HEADINGS = 20
MAX_JSON_LD_BLOCKS = 10
MAX_JSON_LD_CHARS = 200_000


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self._heading: list[str] | None = None
        self._json_ld: list[str] | None = None
        self.title: list[str] = []
        self.parts: list[str] = []
        self.headings: list[str] = []
        self.json_ld: list[str] = []
        self.meta_dates: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_ld = []
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key in _DATE_META and values.get("content"):
                self.meta_dates.setdefault(_DATE_META[key], values["content"])
        elif tag in _HEADINGS:
            self._heading = []
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_ld is not None:
            if len(self.json_ld) < MAX_JSON_LD_BLOCKS:
                self.json_ld.append("".join(self._json_ld)[:MAX_JSON_LD_CHARS])
            self._json_ld = None
            return
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _HEADINGS and self._heading is not None:
            text = collapse_whitespace("".join(self._heading))
            if text and len(self.headings) < MAX_HEADINGS:
                self.headings.append(text[:300])
            self._heading = None
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._json_ld is not None:
            self._json_ld.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.title.append(data)
            return
        if self._heading is not None:
            self._heading.append(data)
        self.parts.append(data)


@dataclass
class PageExtraction:
    title: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    text_truncated: bool = False
    product_names: list[str] = field(default_factory=list)
    vendor_names: list[str] = field(default_factory=list)
    identifiers: list[ProductIdentifier] = field(default_factory=list)
    page_published_date: str | None = None
    release_date: str | None = None
    availability_date: str | None = None
    parse_ok: bool = True


def iso_date(raw: Any) -> str | None:
    """YYYY-MM-DD from an explicit ISO-shaped value; nothing else is parsed."""
    if not isinstance(raw, str):
        return None
    match = _ISO_DATE.match(raw.strip())
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def gtin_key(raw: str) -> str | None:
    """A strong key for a GTIN with a valid check digit, else None."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) not in (8, 12, 13, 14) or len(digits) != len(raw.strip().replace(" ", "")):
        return None
    padded = digits.zfill(14)
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(padded[:-1]))
    if (10 - total % 10) % 10 != int(padded[-1]):
        return None
    return f"gtin:{padded}"


def _fold(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


def _name(value: Any) -> str | None:
    if isinstance(value, str):
        return collapse_whitespace(value)[:128] or None
    if isinstance(value, dict):
        return _name(value.get("name"))
    if isinstance(value, list) and value:
        return _name(value[0])
    return None


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    stack = [node]
    while stack and len(found) < 50:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, dict):
            kind = current.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(k in ("Product", "SoftwareApplication", "MobileApplication", "ProductModel") for k in kinds):
                found.append(current)
            if "@graph" in current:
                stack.append(current["@graph"])
    return found


def _identifiers(obj: dict[str, Any]) -> tuple[list[ProductIdentifier], str | None]:
    brand = _name(obj.get("brand")) or _name(obj.get("manufacturer"))
    out: list[ProductIdentifier] = []
    for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"):
        value = obj.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            text = str(value).strip()
            out.append(ProductIdentifier(kind=ProductIdentifierKind.GTIN, value=text[:128], brand=brand, strong_key=gtin_key(text)))
    for key, kind in (("mpn", ProductIdentifierKind.MANUFACTURER_PART_NUMBER), ("model", ProductIdentifierKind.MANUFACTURER_MODEL_NUMBER)):
        value = obj.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("identifier")
        if isinstance(value, str) and value.strip():
            folded = _fold(value)
            strong = f"{kind.value.lower()}:{_fold(brand)}:{folded}" if brand and folded else None
            out.append(ProductIdentifier(kind=kind, value=value.strip()[:128], brand=brand, strong_key=strong))
    sku = obj.get("sku")
    if isinstance(sku, (str, int)) and str(sku).strip():
        out.append(ProductIdentifier(kind=ProductIdentifierKind.SKU, value=str(sku).strip()[:128], brand=brand))
    kinds = obj.get("@type") if isinstance(obj.get("@type"), list) else [obj.get("@type")]
    if any(k in ("SoftwareApplication", "MobileApplication") for k in kinds):
        package = obj.get("identifier")
        if isinstance(package, str) and _PACKAGE_ID.match(package.strip()):
            out.append(
                ProductIdentifier(
                    kind=ProductIdentifierKind.APP_PACKAGE_ID,
                    value=package.strip(),
                    brand=brand,
                    strong_key=f"app:{package.strip().lower()}",
                )
            )
    return out, brand


def extract_page(html: str, content_type: str) -> PageExtraction:
    if content_type == "text/plain":
        text = html.strip()
        return PageExtraction(
            text=text[:MAX_PRODUCT_TEXT_CHARS], text_truncated=len(text) > MAX_PRODUCT_TEXT_CHARS
        )
    parser = _Parser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 -- malformed markup is data, not a crash
        return PageExtraction(parse_ok=False)
    lines = [collapse_whitespace(line) for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    result = PageExtraction(
        title=collapse_whitespace("".join(parser.title))[:512],
        headings=parser.headings,
        text=text[:MAX_PRODUCT_TEXT_CHARS],
        text_truncated=len(text) > MAX_PRODUCT_TEXT_CHARS,
        page_published_date=iso_date(parser.meta_dates.get("page_published")),
    )
    for block in parser.json_ld:
        try:
            data = json.loads(block)
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict) and result.page_published_date is None:
            result.page_published_date = iso_date(data.get("datePublished"))
        for obj in _objects(data):
            identifiers, brand = _identifiers(obj)
            result.identifiers.extend(identifiers)
            name = _name(obj.get("name"))
            if name and name not in result.product_names:
                result.product_names.append(name)
            if brand and brand not in result.vendor_names:
                result.vendor_names.append(brand)
            result.release_date = result.release_date or iso_date(obj.get("releaseDate")) or iso_date(obj.get("datePublished"))
            offers = obj.get("offers")
            for offer in offers if isinstance(offers, list) else [offers]:
                if isinstance(offer, dict):
                    result.availability_date = result.availability_date or iso_date(offer.get("availabilityStarts"))
    unique: dict[tuple[str, str], ProductIdentifier] = {}
    for identifier in result.identifiers:
        unique.setdefault((identifier.kind.value, identifier.value), identifier)
    result.identifiers = list(unique.values())
    if not text and not result.title and not parser.json_ld:
        result.parse_ok = False
    return result


__all__ = ["PageExtraction", "extract_page", "gtin_key", "iso_date"]
