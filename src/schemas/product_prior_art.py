"""Product prior-art research contracts -- Phase 2H product track (ADR-019).

The trust progression is explicit in the types:

    ProductSearchObservation   a web-search hit: URL, title, snippet, rank
    ProductSourceArtifact      a safely fetched page, hashed and bounded
    ProductEntity              artifacts grouped ONLY on justified identity
    ProductPriorArtCandidate   a record for a LATER comparison phase

Four distinctions this module refuses to collapse:

* **search hit vs artifact.** An observation is what a search provider said.
  It becomes an artifact only when the page itself was fetched through the
  SSRF-safe fetcher; a snippet is never product truth.
* **listing vs manufacturer.** A source role is assigned only from a reviewed
  host registry. ``FIRST_PARTY_*`` is never inferred from a title or from
  vendor text on the page; anything unproven stays ``UNKNOWN``.
* **listing vs product.** Artifacts collapse into one entity only on a strong
  identifier or byte-identical content. A shared SKU or a similar name is a
  *probable link* between separate entities, never a merge.
* **page date vs availability.** Six date facts stay separate, every one is
  source-reported, and the retrieval date is never a historical date.

No field here can express novelty, same invention, legal prior art or a
project-score effect.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime
from src.schemas.discovery import (
    CONTENT_HASH_PATTERN,
    DATE_PATTERN,
    MAX_SAFE_SUMMARY_LENGTH,
    CandidateLimitation,
    CandidateQueryProvenance,
    DiscoveryBudget,
    DiscoveryCoverageStatus,
    DiscoveryCutoff,
    DiscoveryErrorKind,
    DiscoveryOutcome,
    DiscoveryProvider,
    DiscoveryProviderCapability,
    DiscoveryQuery,
    DiscoveryQueryExecution,
    DiscoveryTrack,
    ExcludedDiscoveryClaim,
    RejectedDiscoveryQuery,
    coverage_is_honest,
    outcome_is_honest,
    providers_are_honest,
    require_universal_limitations,
    stable_id,
)

PRODUCT_CONTRACT_VERSION = "PRODUCT-PRIOR-ART-CONTRACT-V1"
PRODUCT_IDENTITY_VERSION = "PRODUCT-IDENTITY-V1"
PRODUCT_CHRONOLOGY_VERSION = "PRODUCT-CHRONOLOGY-V1"

MAX_PRODUCT_SNIPPET_CHARS = 1_000
MAX_PRODUCT_TEXT_CHARS = 50_000


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


class ProductSearchObservation(MawhibaModel):
    """One web-search hit. Not product existence, not manufacturer truth."""

    observation_id: UUID
    research_run_id: UUID
    query_id: UUID
    provider: DiscoveryProvider
    retrieval_rank: int = Field(ge=1, description="Provider order. Metadata only.")
    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = ""
    snippet: str = Field(default="", max_length=MAX_PRODUCT_SNIPPET_CHARS)
    provider_date: str | None = Field(
        default=None,
        max_length=64,
        description="The provider's own age/date string, verbatim. A search-"
        "provider date, never the page's publication date.",
    )
    retrieved_at: UtcDatetime


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class ProductSourceRole(StrEnum):
    FIRST_PARTY_PRODUCT_PAGE = "FIRST_PARTY_PRODUCT_PAGE"
    FIRST_PARTY_DOCUMENTATION = "FIRST_PARTY_DOCUMENTATION"
    FIRST_PARTY_PRESS_RELEASE = "FIRST_PARTY_PRESS_RELEASE"
    MARKETPLACE_LISTING = "MARKETPLACE_LISTING"
    THIRD_PARTY_REVIEW = "THIRD_PARTY_REVIEW"
    THIRD_PARTY_DIRECTORY = "THIRD_PARTY_DIRECTORY"
    UNKNOWN = "UNKNOWN"


FIRST_PARTY_ROLES: frozenset[ProductSourceRole] = frozenset(
    {
        ProductSourceRole.FIRST_PARTY_PRODUCT_PAGE,
        ProductSourceRole.FIRST_PARTY_DOCUMENTATION,
        ProductSourceRole.FIRST_PARTY_PRESS_RELEASE,
    }
)


class SourceRoleBasis(StrEnum):
    """Why a role was assigned. Only a reviewed registry entry is a basis."""

    REVIEWED_VENDOR_DOMAIN = "REVIEWED_VENDOR_DOMAIN"
    KNOWN_MARKETPLACE_HOST = "KNOWN_MARKETPLACE_HOST"
    KNOWN_REVIEW_HOST = "KNOWN_REVIEW_HOST"
    KNOWN_DIRECTORY_HOST = "KNOWN_DIRECTORY_HOST"
    NO_BASIS = "NO_BASIS"


ROLE_BASES: dict[ProductSourceRole, frozenset[SourceRoleBasis]] = {
    ProductSourceRole.FIRST_PARTY_PRODUCT_PAGE: frozenset({SourceRoleBasis.REVIEWED_VENDOR_DOMAIN}),
    ProductSourceRole.FIRST_PARTY_DOCUMENTATION: frozenset({SourceRoleBasis.REVIEWED_VENDOR_DOMAIN}),
    ProductSourceRole.FIRST_PARTY_PRESS_RELEASE: frozenset({SourceRoleBasis.REVIEWED_VENDOR_DOMAIN}),
    ProductSourceRole.MARKETPLACE_LISTING: frozenset({SourceRoleBasis.KNOWN_MARKETPLACE_HOST}),
    ProductSourceRole.THIRD_PARTY_REVIEW: frozenset({SourceRoleBasis.KNOWN_REVIEW_HOST}),
    ProductSourceRole.THIRD_PARTY_DIRECTORY: frozenset({SourceRoleBasis.KNOWN_DIRECTORY_HOST}),
    ProductSourceRole.UNKNOWN: frozenset({SourceRoleBasis.NO_BASIS}),
}


class ProductFetchStatus(StrEnum):
    FETCHED = "FETCHED"
    FETCH_UNSAFE = "FETCH_UNSAFE"
    FETCH_BLOCKED = "FETCH_BLOCKED"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    PARSE_ERROR = "PARSE_ERROR"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"


class ProductIdentifierKind(StrEnum):
    GTIN = "GTIN"
    MANUFACTURER_PART_NUMBER = "MANUFACTURER_PART_NUMBER"
    MANUFACTURER_MODEL_NUMBER = "MANUFACTURER_MODEL_NUMBER"
    SKU = "SKU"
    APP_PACKAGE_ID = "APP_PACKAGE_ID"


class ProductIdentifier(MawhibaModel):
    """A structured identifier read from the page's own structured data.

    ``strong_key`` is set only when the identifier is globally scoped: a valid
    GTIN, an app package id, or an MPN/model *qualified by a stated brand*. A
    SKU is retailer-scoped and is never strong.
    """

    kind: ProductIdentifierKind
    value: str = Field(min_length=1, max_length=128)
    brand: str | None = Field(default=None, max_length=128)
    strong_key: str | None = None
    source: str = Field(
        default="STRUCTURED_DATA",
        description="Where on the page the identifier was read. Free text is never a source.",
    )

    @model_validator(mode="after")
    def _strength_is_justified(self) -> ProductIdentifier:
        if self.kind is ProductIdentifierKind.SKU and self.strong_key is not None:
            raise ValueError("a SKU is retailer-scoped and never a strong identity")
        if (
            self.kind
            in (
                ProductIdentifierKind.MANUFACTURER_PART_NUMBER,
                ProductIdentifierKind.MANUFACTURER_MODEL_NUMBER,
            )
            and self.strong_key is not None
            and not self.brand
        ):
            raise ValueError("an MPN or model number is strong only with a stated brand")
        return self


class ProductDateFacts(MawhibaModel):
    """Section 18. Distinct, source-reported dates. None is never a guess."""

    page_published_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    vendor_launch_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    vendor_availability_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    marketplace_listing_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    search_provider_date: str | None = Field(default=None, max_length=64)
    retrieved_at: UtcDatetime


class ProductDateField(StrEnum):
    PAGE_PUBLISHED_DATE = "PAGE_PUBLISHED_DATE"
    VENDOR_LAUNCH_DATE = "VENDOR_LAUNCH_DATE"
    VENDOR_AVAILABILITY_DATE = "VENDOR_AVAILABILITY_DATE"
    MARKETPLACE_LISTING_DATE = "MARKETPLACE_LISTING_DATE"


QUALIFYING_PRODUCT_DATE_FIELDS: dict[ProductDateField, str] = {
    ProductDateField.PAGE_PUBLISHED_DATE: "page_published_date",
    ProductDateField.VENDOR_LAUNCH_DATE: "vendor_launch_date",
    ProductDateField.VENDOR_AVAILABILITY_DATE: "vendor_availability_date",
    ProductDateField.MARKETPLACE_LISTING_DATE: "marketplace_listing_date",
}
"""The only fields a cutoff qualification may use. The retrieval date and the
search provider's date are deliberately absent: neither dates the artifact."""


class ProductSourceArtifact(MawhibaModel):
    """A fetched page, or the record of why it could not be fetched."""

    artifact_id: UUID
    research_run_id: UUID
    observation_ids: list[UUID] = Field(min_length=1)
    original_url: str = Field(min_length=1)
    final_url: str | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    host: str = Field(min_length=1)
    source_role: ProductSourceRole = ProductSourceRole.UNKNOWN
    source_role_basis: SourceRoleBasis = SourceRoleBasis.NO_BASIS
    vendor_registry_entry: str | None = Field(
        default=None, description="The reviewed vendor-domain entry behind a first-party role."
    )
    fetch_status: ProductFetchStatus
    error_kind: DiscoveryErrorKind | None = None
    content_type: str | None = None
    retrieved_at: UtcDatetime
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    byte_length: int | None = Field(default=None, ge=0)
    text_snapshot: str = Field(default="", max_length=MAX_PRODUCT_TEXT_CHARS)
    text_truncated: bool = False
    title: str = Field(default="", max_length=512)
    headings: list[str] = Field(default_factory=list)
    stated_product_names: list[str] = Field(default_factory=list)
    stated_vendor_names: list[str] = Field(default_factory=list)
    identifiers: list[ProductIdentifier] = Field(default_factory=list)
    dates: ProductDateFacts
    limitations: list[str] = Field(default_factory=list)
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _consistent(self) -> ProductSourceArtifact:
        if self.source_role_basis not in ROLE_BASES[self.source_role]:
            raise ValueError(
                f"{self.source_role.value} cannot rest on {self.source_role_basis.value}"
            )
        if self.source_role in FIRST_PARTY_ROLES and not self.vendor_registry_entry:
            raise ValueError("a first-party role requires its reviewed vendor-domain entry")
        fetched = self.fetch_status is ProductFetchStatus.FETCHED
        if fetched:
            if self.content_hash is None or self.final_url is None or self.content_type is None:
                raise ValueError("a fetched artifact records its final URL, content type and hash")
            if self.error_kind is not None:
                raise ValueError("a fetched artifact carries no error")
        else:
            if self.text_snapshot or self.content_hash or self.identifiers:
                raise ValueError("an unfetched artifact holds no content, hash or identifiers")
            if self.error_kind is None:
                raise ValueError("an unfetched artifact must state its error kind")
            if self.source_role in FIRST_PARTY_ROLES:
                raise ValueError("an unfetched page cannot be a verified first-party source")
        return self

    @property
    def fetched(self) -> bool:
        return self.fetch_status is ProductFetchStatus.FETCHED

    @property
    def strong_keys(self) -> list[str]:
        return sorted({i.strong_key for i in self.identifiers if i.strong_key})


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------


class ProductIdentityStatus(StrEnum):
    VERIFIED_STRONG_IDENTITY = "VERIFIED_STRONG_IDENTITY"
    PROBABLE_IDENTITY = "PROBABLE_IDENTITY"
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"


class ArtifactGroupingBasis(StrEnum):
    """Why more than one artifact sits in one entity. Titles are not a basis."""

    SINGLE_ARTIFACT = "SINGLE_ARTIFACT"
    SHARED_STRONG_IDENTIFIER = "SHARED_STRONG_IDENTIFIER"
    IDENTICAL_CONTENT_HASH = "IDENTICAL_CONTENT_HASH"
    STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT = "STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT"


class ProbableLinkBasis(StrEnum):
    SHARED_RETAILER_SKU = "SHARED_RETAILER_SKU"
    SAME_STATED_BRAND_AND_PRODUCT_NAME = "SAME_STATED_BRAND_AND_PRODUCT_NAME"
    SAME_UNQUALIFIED_MODEL_NUMBER = "SAME_UNQUALIFIED_MODEL_NUMBER"


class ProbableProductLink(MawhibaModel):
    """A non-destructive link to another entity. Both entities stay separate."""

    other_entity_id: UUID
    basis: ProbableLinkBasis
    detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)


class ProductEntity(MawhibaModel):
    entity_id: UUID
    research_run_id: UUID
    identity_status: ProductIdentityStatus
    identity_key: str | None = None
    grouping_basis: ArtifactGroupingBasis
    artifact_ids: list[UUID] = Field(min_length=1)
    strong_identifiers: list[ProductIdentifier] = Field(default_factory=list)
    conflicting_strong_keys: list[str] = Field(default_factory=list)
    probable_links: list[ProbableProductLink] = Field(default_factory=list)
    stated_product_names: list[str] = Field(default_factory=list)
    stated_vendor_names: list[str] = Field(default_factory=list)
    identity_version: str = PRODUCT_IDENTITY_VERSION

    @model_validator(mode="after")
    def _identity_justified(self) -> ProductEntity:
        status = self.identity_status
        if status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY:
            if not self.identity_key or not self.strong_identifiers:
                raise ValueError("strong identity requires a strong key and its identifier")
            if self.conflicting_strong_keys:
                raise ValueError("conflicting strong identifiers cannot be a verified identity")
            if any(i.strong_key != self.identity_key for i in self.strong_identifiers):
                raise ValueError("every strong identifier must carry the entity's key")
        elif self.identity_key is not None:
            raise ValueError("only a verified strong identity carries an identity key")
        if status is ProductIdentityStatus.PROBABLE_IDENTITY and not self.probable_links:
            raise ValueError("PROBABLE_IDENTITY requires at least one probable link")
        if status is ProductIdentityStatus.UNRESOLVED_IDENTITY and self.probable_links:
            raise ValueError("an entity with probable links is PROBABLE_IDENTITY")
        multi = len(self.artifact_ids) > 1
        if multi == (self.grouping_basis is ArtifactGroupingBasis.SINGLE_ARTIFACT):
            raise ValueError("grouping_basis must justify exactly the artifacts grouped")
        if self.grouping_basis in (
            ArtifactGroupingBasis.SHARED_STRONG_IDENTIFIER,
            ArtifactGroupingBasis.STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT,
        ) and status is not ProductIdentityStatus.VERIFIED_STRONG_IDENTITY:
            raise ValueError("a strong-identifier grouping requires a verified strong identity")
        if any(l.other_entity_id == self.entity_id for l in self.probable_links):
            raise ValueError("an entity cannot link to itself")
        return self


# ---------------------------------------------------------------------------
# Chronology and candidate
# ---------------------------------------------------------------------------


class ProductCutoffQualification(StrEnum):
    """Section 19. Chronology only -- never a legal prior-art ruling."""

    DATED_ARTIFACT_BEFORE_CUTOFF = "DATED_ARTIFACT_BEFORE_CUTOFF"
    DATED_ARTIFACT_ON_CUTOFF = "DATED_ARTIFACT_ON_CUTOFF"
    DATED_ARTIFACT_AFTER_CUTOFF = "DATED_ARTIFACT_AFTER_CUTOFF"
    ARTIFACT_DATE_UNKNOWN = "ARTIFACT_DATE_UNKNOWN"
    NO_CUTOFF = "NO_CUTOFF"


PRODUCT_CUTOFF_RELATIVE: frozenset[ProductCutoffQualification] = frozenset(
    {
        ProductCutoffQualification.DATED_ARTIFACT_BEFORE_CUTOFF,
        ProductCutoffQualification.DATED_ARTIFACT_ON_CUTOFF,
        ProductCutoffQualification.DATED_ARTIFACT_AFTER_CUTOFF,
    }
)


class ProductChronology(MawhibaModel):
    """Which source-reported date was used, from which artifact, against what."""

    qualification: ProductCutoffQualification
    date_field_used: ProductDateField | None = None
    date_value: str | None = Field(default=None, pattern=DATE_PATTERN)
    date_artifact_id: UUID | None = None
    cutoff_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    source_reported_only: bool = Field(default=True, description="Always true in Phase 2H.")
    proves_historical_availability: bool = Field(default=False, description="Always false.")

    @model_validator(mode="after")
    def _consistent(self) -> ProductChronology:
        if not self.source_reported_only or self.proves_historical_availability:
            raise ValueError(
                "a product date is source-reported and never proves historical availability"
            )
        dated = self.date_field_used is not None
        if dated != (self.date_value is not None) or dated != (self.date_artifact_id is not None):
            raise ValueError("a used date carries its field, value and artifact together")
        if self.qualification in PRODUCT_CUTOFF_RELATIVE:
            if self.cutoff_date is None or not dated:
                raise ValueError("a cutoff-relative qualification needs a cutoff and a dated field")
            expected = (
                ProductCutoffQualification.DATED_ARTIFACT_BEFORE_CUTOFF
                if self.date_value < self.cutoff_date
                else ProductCutoffQualification.DATED_ARTIFACT_ON_CUTOFF
                if self.date_value == self.cutoff_date
                else ProductCutoffQualification.DATED_ARTIFACT_AFTER_CUTOFF
            )
            if expected is not self.qualification:
                raise ValueError("the qualification contradicts the dates it was derived from")
        if self.qualification is ProductCutoffQualification.NO_CUTOFF and self.cutoff_date:
            raise ValueError("NO_CUTOFF carries no cutoff date")
        if self.qualification is ProductCutoffQualification.ARTIFACT_DATE_UNKNOWN and (
            dated or self.cutoff_date is None
        ):
            raise ValueError("ARTIFACT_DATE_UNKNOWN means a cutoff exists and no artifact date does")
        return self


class ProductArtifactSummary(MawhibaModel):
    """Per-artifact facts carried on the candidate unchanged."""

    artifact_id: UUID
    final_url: str
    host: str
    source_role: ProductSourceRole
    content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    dates: ProductDateFacts


class ProductPriorArtCandidate(MawhibaModel):
    """A product a LATER novelty phase should inspect. Not a verdict of any kind.

    The fields that would let this record overstate itself do not exist.
    """

    candidate_id: UUID
    research_run_id: UUID
    candidate_type: str = Field(default="PRODUCT", pattern=r"^PRODUCT$")
    entity_id: UUID
    identity_status: ProductIdentityStatus
    identity_key: str | None = None
    artifacts: list[ProductArtifactSummary] = Field(min_length=1)
    source_roles: list[ProductSourceRole] = Field(min_length=1)
    stated_product_names: list[str] = Field(default_factory=list)
    stated_vendor_names: list[str] = Field(default_factory=list)
    strong_identifiers: list[ProductIdentifier] = Field(default_factory=list)
    probable_link_entity_ids: list[UUID] = Field(default_factory=list)
    chronology: ProductChronology
    query_provenance: list[CandidateQueryProvenance] = Field(min_length=1)
    observation_ids: list[UUID] = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    component_ids: list[str] = Field(default_factory=list)
    limitations: list[CandidateLimitation] = Field(min_length=6)
    contract_version: str = PRODUCT_CONTRACT_VERSION

    @model_validator(mode="after")
    def _limitations_hold(self) -> ProductPriorArtCandidate:
        require_universal_limitations(self.limitations)
        if self.candidate_id != stable_id(self.research_run_id, "product-candidate", self.entity_id):
            raise ValueError("candidate_id must be the stable id of its entity")
        if CandidateLimitation.CURRENT_AVAILABILITY_NOT_HISTORICAL not in self.limitations:
            raise ValueError("a product candidate must state that current availability is not historical")
        if (self.identity_status is ProductIdentityStatus.UNRESOLVED_IDENTITY) != (
            CandidateLimitation.PRODUCT_IDENTITY_UNRESOLVED in self.limitations
        ):
            raise ValueError("PRODUCT_IDENTITY_UNRESOLVED is stated exactly for an unresolved identity")
        if sorted(set(self.source_roles), key=str) != sorted(
            {a.source_role for a in self.artifacts}, key=str
        ):
            raise ValueError("source_roles must be exactly the artifacts' roles")
        return self


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class ProductPriorArtRun(MawhibaModel):
    """Everything the PRODUCT track produced in one research run.

    Lives on ``ResearchRun.product_prior_art``, never in ``ProjectState``.
    """

    product_run_id: UUID
    research_run_id: UUID
    track: DiscoveryTrack = DiscoveryTrack.PRODUCT
    outcome: DiscoveryOutcome = DiscoveryOutcome.NOT_RUN
    coverage_status: DiscoveryCoverageStatus = DiscoveryCoverageStatus.NOT_EXECUTED
    contract_version: str = PRODUCT_CONTRACT_VERSION
    identity_version: str = PRODUCT_IDENTITY_VERSION
    chronology_version: str = PRODUCT_CHRONOLOGY_VERSION
    planner_version: str = Field(min_length=1)
    planner_prompt_version: str | None = None
    provider_capabilities: list[DiscoveryProviderCapability] = Field(min_length=1)
    search_cutoff: DiscoveryCutoff
    budget: DiscoveryBudget

    planned_queries: list[DiscoveryQuery] = Field(default_factory=list)
    executed_query_keys: list[str] = Field(default_factory=list)
    rejected_queries: list[RejectedDiscoveryQuery] = Field(default_factory=list)
    excluded_claims: list[ExcludedDiscoveryClaim] = Field(default_factory=list)
    executions: list[DiscoveryQueryExecution] = Field(default_factory=list)
    observations: list[ProductSearchObservation] = Field(default_factory=list)
    artifacts: list[ProductSourceArtifact] = Field(default_factory=list)
    entities: list[ProductEntity] = Field(default_factory=list)
    candidates: list[ProductPriorArtCandidate] = Field(default_factory=list)
    stage_markers: list[str] = Field(
        default_factory=list,
        description="Stages already applied. What makes a replayed stage a no-op "
        "even when it legitimately produced nothing.",
    )

    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _internally_consistent(self) -> ProductPriorArtRun:
        run_id = self.research_run_id
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        for label, items in (
            ("query", self.planned_queries),
            ("execution", self.executions),
            ("observation", self.observations),
            ("artifact", self.artifacts),
            ("entity", self.entities),
            ("candidate", self.candidates),
        ):
            if any(item.research_run_id != run_id for item in items):
                raise ValueError(f"a {label} belongs to a different research run (section 36)")
        if any(q.track is not DiscoveryTrack.PRODUCT for q in self.planned_queries):
            raise ValueError("a product run holds only product queries")

        query_ids = [q.query_id for q in self.planned_queries]
        if len(set(query_ids)) != len(query_ids):
            raise ValueError("query ids must be unique")
        known_queries = set(query_ids)
        if any(e.query_id not in known_queries for e in self.executions):
            raise ValueError("an execution references an unknown query")
        if any(o.query_id not in known_queries for o in self.observations):
            raise ValueError("an observation references an unknown query")

        observation_ids = [o.observation_id for o in self.observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("observation ids must be unique")
        known_observations = set(observation_ids)

        artifact_ids = [a.artifact_id for a in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact ids must be unique")
        if any(o not in known_observations for a in self.artifacts for o in a.observation_ids):
            raise ValueError("an artifact references an unknown observation")
        by_artifact = {a.artifact_id: a for a in self.artifacts}

        entity_ids = [e.entity_id for e in self.entities]
        if len(set(entity_ids)) != len(entity_ids):
            raise ValueError("entity ids must be unique")
        known_entities = set(entity_ids)
        grouped: list[UUID] = []
        for entity in self.entities:
            for artifact_id in entity.artifact_ids:
                artifact = by_artifact.get(artifact_id)
                if artifact is None:
                    raise ValueError("an entity references an unknown artifact")
                if not artifact.fetched:
                    raise ValueError("only a fetched artifact can belong to a product entity")
            grouped.extend(entity.artifact_ids)
            if any(l.other_entity_id not in known_entities for l in entity.probable_links):
                raise ValueError("a probable link references an entity outside this run")
            if entity.identity_status is ProductIdentityStatus.VERIFIED_STRONG_IDENTITY:
                keys = {k for a in entity.artifact_ids for k in by_artifact[a].strong_keys}
                if entity.identity_key not in keys:
                    raise ValueError("a strong identity must be read from its artifacts")
            if len(entity.artifact_ids) > 1:
                _require_justified_grouping(entity, by_artifact)
        if len(set(grouped)) != len(grouped):
            raise ValueError("an artifact belongs to at most one entity")
        identity_keys = [e.identity_key for e in self.entities if e.identity_key is not None]
        if len(set(identity_keys)) != len(identity_keys):
            raise ValueError(
                "one strong identity is one product entity; a second entity with the "
                "same key would inflate the product count (section 17)"
            )

        candidate_entities = [c.entity_id for c in self.candidates]
        if len(set(candidate_entities)) != len(candidate_entities):
            raise ValueError("an entity has at most one candidate per run (section 35)")
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("candidate ids must be unique")
        by_entity = {e.entity_id: e for e in self.entities}
        for candidate in self.candidates:
            entity = by_entity.get(candidate.entity_id)
            if entity is None:
                raise ValueError("a candidate references an unknown entity")
            if (
                candidate.identity_status is not entity.identity_status
                or candidate.identity_key != entity.identity_key
                or sorted(a.artifact_id for a in candidate.artifacts) != sorted(entity.artifact_ids)
            ):
                raise ValueError("a candidate must carry its entity's identity and artifacts unchanged")
            for summary in candidate.artifacts:
                artifact = by_artifact[summary.artifact_id]
                if (
                    summary.source_role is not artifact.source_role
                    or summary.content_hash != artifact.content_hash
                    or summary.dates != artifact.dates
                ):
                    raise ValueError("a candidate must carry each artifact's role, hash and dates unchanged")
            if any(o not in known_observations for o in candidate.observation_ids):
                raise ValueError("a candidate references an unknown observation")
            if any(p.query_id not in known_queries for p in candidate.query_provenance):
                raise ValueError("a candidate references an unknown query")
            chronology = candidate.chronology
            if chronology.cutoff_date not in (None, self.search_cutoff.cutoff_date):
                raise ValueError("a candidate was qualified against a different cutoff")
            if not self.search_cutoff.supplied and chronology.qualification.value != "NO_CUTOFF":
                raise ValueError("a run with no supplied cutoff can only produce NO_CUTOFF")
            if self.search_cutoff.supplied and chronology.qualification.value == "NO_CUTOFF":
                raise ValueError("a supplied cutoff must be applied")
            if chronology.date_artifact_id is not None:
                if chronology.date_artifact_id not in entity.artifact_ids:
                    raise ValueError("a chronology date must come from the candidate's own artifacts")
                field = QUALIFYING_PRODUCT_DATE_FIELDS[chronology.date_field_used]
                if getattr(by_artifact[chronology.date_artifact_id].dates, field) != chronology.date_value:
                    raise ValueError("a chronology date must equal the artifact's source-reported date")

        coverage_is_honest(self.coverage_status, self.budget, self.executions)
        outcome_is_honest(self.outcome, self.executions, bool(self.observations))
        providers_are_honest(self.provider_capabilities, {e.provider for e in self.executions})
        return self

    @property
    def is_terminal(self) -> bool:
        return self.completed_at is not None

    @property
    def fetched_artifacts(self) -> list[ProductSourceArtifact]:
        return [a for a in self.artifacts if a.fetched]

    @property
    def distinct_product_count_upper_bound(self) -> int:
        """Entities: strong identity and identical content collapse; nothing else."""
        return len(self.entities)

    @property
    def distinct_product_count_lower_bound(self) -> int:
        """Entities with probable links counted once per linked cluster."""
        parent = {e.entity_id: e.entity_id for e in self.entities}

        def find(x: UUID) -> UUID:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for entity in self.entities:
            for link in entity.probable_links:
                parent[find(entity.entity_id)] = find(link.other_entity_id)
        return len({find(e) for e in parent})


def _require_justified_grouping(
    entity: ProductEntity, by_artifact: dict[UUID, ProductSourceArtifact]
) -> None:
    """Re-derive that a multi-artifact entity is connected only by strong
    identifiers or identical content -- never by a title (section 16)."""
    ids = list(entity.artifact_ids)
    reached = {ids[0]}
    frontier = [ids[0]]
    while frontier:
        current = by_artifact[frontier.pop()]
        for other_id in ids:
            if other_id in reached:
                continue
            other = by_artifact[other_id]
            shares_key = bool(set(current.strong_keys) & set(other.strong_keys))
            same_content = current.content_hash == other.content_hash
            if shares_key or same_content:
                reached.add(other_id)
                frontier.append(other_id)
    if reached != set(ids):
        raise ValueError(
            "a product entity groups artifacts that share neither a strong "
            "identifier nor identical content (section 16)"
        )


__all__ = [
    "FIRST_PARTY_ROLES",
    "MAX_PRODUCT_SNIPPET_CHARS",
    "MAX_PRODUCT_TEXT_CHARS",
    "PRODUCT_CHRONOLOGY_VERSION",
    "PRODUCT_CONTRACT_VERSION",
    "PRODUCT_CUTOFF_RELATIVE",
    "PRODUCT_IDENTITY_VERSION",
    "QUALIFYING_PRODUCT_DATE_FIELDS",
    "ROLE_BASES",
    "ArtifactGroupingBasis",
    "ProbableLinkBasis",
    "ProbableProductLink",
    "ProductArtifactSummary",
    "ProductChronology",
    "ProductCutoffQualification",
    "ProductDateFacts",
    "ProductDateField",
    "ProductEntity",
    "ProductFetchStatus",
    "ProductIdentifier",
    "ProductIdentifierKind",
    "ProductIdentityStatus",
    "ProductPriorArtCandidate",
    "ProductPriorArtRun",
    "ProductSearchObservation",
    "ProductSourceArtifact",
    "ProductSourceRole",
    "SourceRoleBasis",
]
