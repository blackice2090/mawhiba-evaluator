"""Source-role assignment from a reviewed host registry -- section 15.

A role is a statement about *who published the page*. It is assigned only from
the page's final host against reviewed configuration:

* ``FIRST_PARTY_*`` requires a ``VendorDomain`` entry a reviewer supplied for
  this run. A page's title, brand field or "official site" wording is never
  proof: anyone can write a vendor's name.
* marketplace, review and directory roles come from the small built-in host
  lists below (extendable by configuration).
* everything else is ``UNKNOWN``. Unknown stays unknown.

Hosts match exactly or as a dot-delimited subdomain, so ``evil-amazon.com``
never matches ``amazon.com``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from src.schemas.product_prior_art import ProductSourceRole, SourceRoleBasis

DEFAULT_MARKETPLACE_HOSTS: frozenset[str] = frozenset(
    {"amazon.com", "amazon.sa", "amazon.ae", "ebay.com", "aliexpress.com", "alibaba.com",
     "noon.com", "etsy.com", "walmart.com", "bestbuy.com", "jarir.com", "extra.com"}
)
DEFAULT_REVIEW_HOSTS: frozenset[str] = frozenset(
    {"theverge.com", "techradar.com", "cnet.com", "engadget.com", "wired.com", "tomsguide.com"}
)
DEFAULT_DIRECTORY_HOSTS: frozenset[str] = frozenset(
    {"producthunt.com", "crunchbase.com", "g2.com", "capterra.com", "alternativeto.net"}
)


class VendorPageKind(StrEnum):
    PRODUCT_PAGE = "PRODUCT_PAGE"
    DOCUMENTATION = "DOCUMENTATION"
    PRESS_RELEASE = "PRESS_RELEASE"


_KIND_ROLE = {
    VendorPageKind.PRODUCT_PAGE: ProductSourceRole.FIRST_PARTY_PRODUCT_PAGE,
    VendorPageKind.DOCUMENTATION: ProductSourceRole.FIRST_PARTY_DOCUMENTATION,
    VendorPageKind.PRESS_RELEASE: ProductSourceRole.FIRST_PARTY_PRESS_RELEASE,
}


@dataclass(frozen=True)
class VendorDomain:
    """A reviewer-confirmed statement that ``host`` belongs to ``vendor``."""

    host: str
    vendor: str
    kind: VendorPageKind = VendorPageKind.PRODUCT_PAGE
    path_prefix: str = "/"


@dataclass(frozen=True)
class HostRegistry:
    vendor_domains: tuple[VendorDomain, ...] = ()
    marketplace_hosts: frozenset[str] = DEFAULT_MARKETPLACE_HOSTS
    review_hosts: frozenset[str] = DEFAULT_REVIEW_HOSTS
    directory_hosts: frozenset[str] = field(default=DEFAULT_DIRECTORY_HOSTS)


DEFAULT_HOST_REGISTRY = HostRegistry()


def host_matches(host: str, registered: str) -> bool:
    host = host.lower().rstrip(".")
    registered = registered.lower().rstrip(".")
    return host == registered or host.endswith("." + registered)


@dataclass(frozen=True)
class RoleAssignment:
    role: ProductSourceRole
    basis: SourceRoleBasis
    vendor_entry: str | None = None


def assign_role(host: str, path: str, registry: HostRegistry = DEFAULT_HOST_REGISTRY) -> RoleAssignment:
    for entry in registry.vendor_domains:
        if host_matches(host, entry.host) and (path or "/").startswith(entry.path_prefix):
            return RoleAssignment(
                _KIND_ROLE[entry.kind],
                SourceRoleBasis.REVIEWED_VENDOR_DOMAIN,
                f"{entry.vendor}@{entry.host}{entry.path_prefix}",
            )
    for hosts, role, basis in (
        (registry.marketplace_hosts, ProductSourceRole.MARKETPLACE_LISTING, SourceRoleBasis.KNOWN_MARKETPLACE_HOST),
        (registry.review_hosts, ProductSourceRole.THIRD_PARTY_REVIEW, SourceRoleBasis.KNOWN_REVIEW_HOST),
        (registry.directory_hosts, ProductSourceRole.THIRD_PARTY_DIRECTORY, SourceRoleBasis.KNOWN_DIRECTORY_HOST),
    ):
        if any(host_matches(host, h) for h in hosts):
            return RoleAssignment(role, basis)
    return RoleAssignment(ProductSourceRole.UNKNOWN, SourceRoleBasis.NO_BASIS)


__all__ = [
    "DEFAULT_HOST_REGISTRY",
    "DEFAULT_MARKETPLACE_HOSTS",
    "HostRegistry",
    "RoleAssignment",
    "VendorDomain",
    "VendorPageKind",
    "assign_role",
    "host_matches",
]
