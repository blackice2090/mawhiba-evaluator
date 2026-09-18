"""Patent provider capabilities and access policy -- Phase 2G section 2.

This module is the machine-readable form of the provider-contract gate. Each
entry names the official documentation it was verified against, the date of that
verification, the authentication method, and the operations this project uses.

It reads the connector constants rather than restating them, exactly as
``ProviderCapability`` does for the academic connectors, so the capability table
and the connector cannot drift apart. ``tests/test_patent_provider_contracts.py``
asserts the exact outgoing request contract against the same constants.

Three honesty rules are enforced here rather than left to prose:

* **EPO OPS is documented-only until a real authenticated request succeeds.**
  The unauthenticated probes that confirmed the service host, the operation
  paths, the XML fault shape and the Basic-auth token endpoint are *not* a live
  verification, and ``live_request_observed`` stays False accordingly.

* **PatentsView is not assumed to exist.** Its search API was retired when
  PatentsView moved to the USPTO Open Data Portal, and the replacement search
  functionality has no announced launch. USPTO is therefore ``DEFERRED`` with no
  operations, and no connector is written against a legacy contract.

* **PATENTSCOPE's public search service is never automated.** WIPO's terms of
  use forbid automated queries, robots, web scraping and bulk downloading from
  it. The provider is ``UNSUPPORTED_BY_ACCESS_POLICY`` and, by the capability
  validator, can expose no operations at all -- so there is nothing for a
  connector to call even if someone wrote one.
"""

from __future__ import annotations

from src.research.patent.epo_ops import (
    EPO_OPS_AUTH_PATH,
    EPO_OPS_BIBLIO_OPERATION,
    EPO_OPS_CLAIMS_OPERATION,
    EPO_OPS_CONNECTOR_VERSION,
    EPO_OPS_DESCRIPTION_OPERATION,
    EPO_OPS_DOCUMENTATION_URL,
    EPO_OPS_FAMILY_OPERATION,
    EPO_OPS_SEARCH_PATH,
    EPO_OPS_SERVICE_ROOT,
    EPO_OPS_VERIFIED_ON,
)
from src.schemas.patent import (
    PatentProvider,
    PatentProviderAccessStatus,
    PatentProviderCapability,
    PatentProviderOperation,
)

USPTO_ODP_DOCUMENTATION_URL = "https://data.uspto.gov/support/transition-guide/patentsview"
USPTO_ODP_VERIFIED_ON = "2026-09-17"

WIPO_PATENTSCOPE_DOCUMENTATION_URL = (
    "https://www.wipo.int/en/web/patentscope/data/terms_patentscope"
)
WIPO_PATENTSCOPE_VERIFIED_ON = "2026-09-17"


EPO_OPS_CAPABILITY = PatentProviderCapability(
    provider=PatentProvider.EPO_OPS,
    access_status=PatentProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
    documentation_url=EPO_OPS_DOCUMENTATION_URL,
    contract_verified_on=EPO_OPS_VERIFIED_ON,
    authentication=(
        "OAuth2 client_credentials. Consumer key and secret from the EPO "
        "developer portal are sent as HTTP Basic credentials to "
        f"POST {EPO_OPS_AUTH_PATH}; the returned bearer token authorizes the "
        "REST operations."
    ),
    response_format="XML (EPO OPS exchange documents; XML faults on error)",
    operations=[
        PatentProviderOperation.SEARCH_PUBLICATIONS,
        PatentProviderOperation.FETCH_BIBLIOGRAPHIC,
        PatentProviderOperation.FETCH_FAMILY,
        PatentProviderOperation.FETCH_ABSTRACT,
        PatentProviderOperation.FETCH_CLAIMS,
        PatentProviderOperation.FETCH_DESCRIPTION,
    ],
    live_request_observed=False,
    notes=(
        "Service root "
        f"{EPO_OPS_SERVICE_ROOT}. Bibliographic search is CQL over "
        f"{EPO_OPS_SEARCH_PATH}; family via {EPO_OPS_FAMILY_OPERATION}; "
        f"biblio, abstract, claims and description via "
        f"{EPO_OPS_BIBLIO_OPERATION}, {EPO_OPS_CLAIMS_OPERATION} and "
        f"{EPO_OPS_DESCRIPTION_OPERATION}. Claims and description coverage is "
        "authority-dependent and is never assumed. The service host, these "
        "operation paths, the XML fault envelope and the Basic-auth token "
        "endpoint were observed live unauthenticated; no authenticated request "
        "was executed, so this stays IMPLEMENTED_DOCUMENTED_ONLY."
    ),
)

USPTO_ODP_CAPABILITY = PatentProviderCapability(
    provider=PatentProvider.USPTO_ODP,
    access_status=PatentProviderAccessStatus.DEFERRED,
    documentation_url=USPTO_ODP_DOCUMENTATION_URL,
    contract_verified_on=USPTO_ODP_VERIFIED_ON,
    authentication="USPTO Open Data Portal API key (ODP keys; PatentSearch keys do not carry over)",
    response_format="JSON",
    operations=[],
    live_request_observed=False,
    notes=(
        "PatentsView migrated to the USPTO Open Data Portal on 2026-03-20 and "
        "the search.patentsview.org PatentSearch API was shut down on that "
        "date. USPTO states that PatentsView API functions will be "
        "reintroduced on ODP in updated form with no launch estimate, and only "
        "bulk datasets are currently exposed. No stable documented search "
        "contract usable by this Phase exists, so no connector is implemented "
        "and no legacy PatentsView endpoint is assumed to be active. Phase 2G "
        "is deliberately not blocked on this provider."
    ),
)

WIPO_PATENTSCOPE_CAPABILITY = PatentProviderCapability(
    provider=PatentProvider.WIPO_PATENTSCOPE,
    access_status=PatentProviderAccessStatus.UNSUPPORTED_BY_ACCESS_POLICY,
    documentation_url=WIPO_PATENTSCOPE_DOCUMENTATION_URL,
    contract_verified_on=WIPO_PATENTSCOPE_VERIFIED_ON,
    authentication="not applicable: no authorized programmatic search contract for this system",
    response_format="not applicable",
    operations=[],
    live_request_observed=False,
    notes=(
        "The PATENTSCOPE database terms of use forbid automated queries, "
        "automatic robots, web scraping, and bulk acquisition or downloading "
        "from the public search service, and treat more than a low rate of "
        "search actions from one address as excessive use. WIPO sells separate "
        "PCT raw-data products under their own terms. PATENTSCOPE is therefore "
        "documented as a manual reference research source only, and is never "
        "implemented as an automated search connector here. A future automated "
        "connector would require an explicitly authorized contract and its own "
        "reviewed decision."
    ),
)


PATENT_PROVIDER_CAPABILITIES: dict[PatentProvider, PatentProviderCapability] = {
    PatentProvider.EPO_OPS: EPO_OPS_CAPABILITY,
    PatentProvider.USPTO_ODP: USPTO_ODP_CAPABILITY,
    PatentProvider.WIPO_PATENTSCOPE: WIPO_PATENTSCOPE_CAPABILITY,
}


def capability_for(provider: PatentProvider) -> PatentProviderCapability:
    return PATENT_PROVIDER_CAPABILITIES[provider]


def dispatchable_providers() -> list[PatentProvider]:
    """Providers a Phase 2G run may actually call.

    Derived from the access statuses rather than configured separately, so
    enabling an unsupported provider in settings cannot make it dispatchable.
    """
    return [
        provider
        for provider, capability in PATENT_PROVIDER_CAPABILITIES.items()
        if capability.dispatchable
    ]


def supports(provider: PatentProvider, operation: PatentProviderOperation) -> bool:
    return capability_for(provider).supports(operation)


def connector_versions() -> dict[str, str]:
    """Connector versions, for run provenance. Only implemented connectors."""
    return {PatentProvider.EPO_OPS.value: EPO_OPS_CONNECTOR_VERSION}


def capability_report() -> list[dict[str, object]]:
    """The provider table in reportable form, for the eval CLI and docs."""
    return [
        {
            "provider": capability.provider.value,
            "access_status": capability.access_status.value,
            "documentation_url": capability.documentation_url,
            "contract_verified_on": capability.contract_verified_on,
            "authentication": capability.authentication,
            "response_format": capability.response_format,
            "operations": [o.value for o in capability.operations],
            "live_request_observed": capability.live_request_observed,
            "dispatchable": capability.dispatchable,
        }
        for capability in PATENT_PROVIDER_CAPABILITIES.values()
    ]


__all__ = [
    "EPO_OPS_CAPABILITY",
    "PATENT_PROVIDER_CAPABILITIES",
    "USPTO_ODP_CAPABILITY",
    "USPTO_ODP_DOCUMENTATION_URL",
    "WIPO_PATENTSCOPE_CAPABILITY",
    "WIPO_PATENTSCOPE_DOCUMENTATION_URL",
    "capability_for",
    "capability_report",
    "connector_versions",
    "dispatchable_providers",
    "supports",
]
