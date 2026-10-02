"""Novelty and differentiation assessment contracts -- Phase 2I (ADR-020).

Phase 2I compares the student's existing technical claims against the bounded,
provenance-preserving prior-art candidates Phase 2G (patents) and Phase 2H
(products, open source) discovered, and describes the technical overlap and
differentiation posture of each claim *relative to that bounded candidate set*.

The trust progression is explicit in the types:

    ComparisonFeatureInventory     the claim's features, at exact claim anchors
    CandidateComparisonProfile     what text a candidate offers, at what capacity
    CandidateDisclosureAnchor      exact candidate text, sliced by code
    ClaimCandidateComparison       verified per-feature relations for ONE pair
    ClaimDifferentiationSynthesis  the claim posture, decided in Python
    ProjectDifferentiationSummary  descriptive counts, never a score

Distinctions this module refuses to collapse, each enforced by a validator:

* **discovered vs disclosed.** A candidate is a search result; a disclosure is
  an exact excerpt of verified candidate text that code located.
* **component vs combination.** ``COMBINATION`` is a deterministic feature over
  the whole claim; full-claim overlap requires ONE candidate to disclose it.
  Every component being found is not the claimed combination being found.
* **title vs disclosure.** A title, a repository description, topics and
  release metadata can never support more than ``RELATED_CONTEXT``.
* **not found vs not there.** ``NOT_DISCLOSED`` means "not in the verified
  candidate text actually compared", and is refused when no material text was
  compared at all.
* **technical overlap vs legal novelty.** There is no novelty verdict, no
  patentability field, no anticipation label, no score and no probability
  anywhere here, and every claim posture carries the limitations saying so.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.common import MawhibaModel, UtcDatetime
from src.schemas.discovery import CONTENT_HASH_PATTERN, DATE_PATTERN, MAX_SAFE_SUMMARY_LENGTH

NOVELTY_CONTRACT_VERSION = "NOVELTY-DIFFERENTIATION-CONTRACT-V1"
COMPARISON_FEATURE_SCHEMA_VERSION = "COMPARISON-FEATURE-SCHEMA-V1"
FEATURE_EXTRACTION_PROMPT_VERSION = "NOVELTY_FEATURE_EXTRACTION_PROMPT_V1"
TECHNICAL_COMPARISON_PROMPT_VERSION = "PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1"
ANCHOR_VERIFIER_VERSION = "CANDIDATE-DISCLOSURE-ANCHOR-VERIFIER-V1"
DISCLOSURE_POLICY_VERSION = "SOURCE-TYPE-DISCLOSURE-POLICY-V1"
SYNTHESIS_POLICY_VERSION = "TECHNICAL-OVERLAP-SYNTHESIS-POLICY-V1"

NOVELTY_ID_NAMESPACE = UUID("0b6f3a5e-7d42-5c19-8e3a-2f9d4c1b7a60")

DIFFERENTIATION_QUALIFIER = "RELATIVE_TO_COMPARED_BOUNDED_CANDIDATE_SET"
"""Carried on every per-feature differentiation record. A feature not found in
the compared candidates is differentiating *relative to that set* -- never
unique, novel, unprecedented or first."""

MAX_RATIONALE_CHARS = 300


def novelty_id(*parts: object) -> UUID:
    """A deterministic id from stable parts. Same parts, same id, every rerun."""
    return uuid5(NOVELTY_ID_NAMESPACE, "|".join(str(p) for p in parts))


def component_id(claim_id: str, start: int, end: int) -> str:
    """The id of one Phase 2E inventory component. 2E components carry a span,
    not an id, so the span is the identity."""
    return f"{claim_id}:{start}-{end}"


# ---------------------------------------------------------------------------
# Bounds (section 19)
# ---------------------------------------------------------------------------


class NoveltyComparisonBounds(MawhibaModel):
    """Every limit Phase 2I applies, recorded on the run that applied it.

    A limit that removed something is never silent: the claim coverage records
    each candidate omitted by it, and partial coverage can never read complete.
    """

    max_candidates_per_claim: int = Field(default=12, ge=1, le=100)
    max_patent_groups_per_claim: int = Field(default=4, ge=0, le=50)
    max_product_groups_per_claim: int = Field(default=4, ge=0, le=50)
    max_oss_networks_per_claim: int = Field(default=4, ge=0, le=50)
    max_texts_per_candidate: int = Field(default=6, ge=1, le=20)
    max_chars_per_text: int = Field(default=6_000, ge=200, le=100_000)
    max_chars_per_comparison: int = Field(default=20_000, ge=500, le=200_000)
    max_model_comparisons: int = Field(default=60, ge=0, le=2_000)
    max_features_per_claim: int = Field(default=24, ge=2, le=64)
    model_retry_limit: int = Field(default=1, ge=0, le=5)
    model_timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)


# ---------------------------------------------------------------------------
# Feature inventory (sections 7, 8, 9)
# ---------------------------------------------------------------------------


class FeatureType(StrEnum):
    COMPONENT = "COMPONENT"
    FUNCTION = "FUNCTION"
    MECHANISM = "MECHANISM"
    RELATIONSHIP = "RELATIONSHIP"
    SEQUENCE = "SEQUENCE"
    CONSTRAINT = "CONSTRAINT"
    COMBINATION = "COMBINATION"
    OTHER_TECHNICAL_FEATURE = "OTHER_TECHNICAL_FEATURE"


RELATIONSHIP_BEARING_TYPES: frozenset[FeatureType] = frozenset(
    {
        FeatureType.RELATIONSHIP,
        FeatureType.SEQUENCE,
        FeatureType.CONSTRAINT,
        FeatureType.COMBINATION,
    }
)
"""Features that state how elements relate. Overlap on these is what separates
a partial-claim overlap from a component-only overlap."""

MODEL_PROPOSABLE_TYPES: frozenset[FeatureType] = frozenset(FeatureType) - {FeatureType.COMBINATION}
"""``COMBINATION`` is reserved: only code creates it, over the whole claim."""


class FeatureDerivation(StrEnum):
    MODEL_PROPOSED_VERIFIED = "MODEL_PROPOSED_VERIFIED"
    UNCOVERED_CLAIM_REMAINDER = "UNCOVERED_CLAIM_REMAINDER"
    DETERMINISTIC_COMBINATION = "DETERMINISTIC_COMBINATION"
    FULL_CLAIM_FALLBACK = "FULL_CLAIM_FALLBACK"


class FeatureMateriality(StrEnum):
    MATERIAL = "MATERIAL"
    IMMATERIAL = "IMMATERIAL"


class FeatureVerificationStatus(StrEnum):
    VERIFIED_EXACT_CLAIM_ANCHOR = "VERIFIED_EXACT_CLAIM_ANCHOR"
    DERIVED_FROM_CLAIM_TEXT = "DERIVED_FROM_CLAIM_TEXT"


class FeatureRejectionReason(StrEnum):
    ANCHOR_NOT_IN_CLAIM = "ANCHOR_NOT_IN_CLAIM"
    AMBIGUOUS_REPEATED_ANCHOR = "AMBIGUOUS_REPEATED_ANCHOR"
    INVALID_OFFSETS = "INVALID_OFFSETS"
    INVALID_OCCURRENCE_INDEX = "INVALID_OCCURRENCE_INDEX"
    EMPTY_ANCHOR = "EMPTY_ANCHOR"
    IMMATERIAL_ANCHOR = "IMMATERIAL_ANCHOR"
    INVALID_FEATURE_TYPE = "INVALID_FEATURE_TYPE"
    RESERVED_FEATURE_TYPE = "RESERVED_FEATURE_TYPE"
    DUPLICATE_FEATURE = "DUPLICATE_FEATURE"
    FEATURE_LIMIT_EXCEEDED = "FEATURE_LIMIT_EXCEEDED"


class InventoryMode(StrEnum):
    """``FULL_CLAIM_ONLY`` is the conservative fallback (section 6): one feature
    spanning the claim, and strong differentiation synthesis withheld."""

    COMPONENT_LEVEL = "COMPONENT_LEVEL"
    FULL_CLAIM_ONLY = "FULL_CLAIM_ONLY"


class InventoryModeReason(StrEnum):
    """Why component-level comparison was unavailable for a claim."""

    PHASE_2E_INVENTORY_MISSING = "PHASE_2E_INVENTORY_MISSING"
    PHASE_2E_INVENTORY_NOT_COMPLETE = "PHASE_2E_INVENTORY_NOT_COMPLETE"
    PHASE_2E_CLAIM_HASH_MISMATCH = "PHASE_2E_CLAIM_HASH_MISMATCH"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"
    FEATURE_EXTRACTION_FAILED = "FEATURE_EXTRACTION_FAILED"
    NO_VERIFIED_FEATURES = "NO_VERIFIED_FEATURES"


class InventoryCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class InventoryIssue(StrEnum):
    UNCOVERED_MATERIAL_TEXT = "UNCOVERED_MATERIAL_TEXT"
    FEATURE_LIMIT_EXCEEDED = "FEATURE_LIMIT_EXCEEDED"


class ComparisonFeature(MawhibaModel):
    """One material feature of one claim, at an exact claim anchor.

    ``claim.claim[start:end] == text`` holds by verification: the anchor was
    located by code in the canonical claim text, never taken from model offsets.
    """

    feature_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    feature_type: FeatureType
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1)
    derivation: FeatureDerivation
    materiality: FeatureMateriality = FeatureMateriality.MATERIAL
    verification_status: FeatureVerificationStatus
    source_component_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _anchor_and_derivation_hold(self) -> ComparisonFeature:
        from src.schemas.claim_component_inventory import is_material_text

        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("a feature anchor must be an exact, non-empty claim span")
        if self.materiality is not FeatureMateriality.MATERIAL or not is_material_text(self.text):
            raise ValueError("an accepted feature must anchor material claim text")
        combination_derivations = (
            FeatureDerivation.DETERMINISTIC_COMBINATION,
            FeatureDerivation.FULL_CLAIM_FALLBACK,
        )
        if (self.feature_type is FeatureType.COMBINATION) != (
            self.derivation in combination_derivations
        ):
            raise ValueError(
                "COMBINATION is reserved for the deterministic whole-claim feature; "
                "a model may never propose it and code never labels anything else so"
            )
        if (
            self.derivation is FeatureDerivation.UNCOVERED_CLAIM_REMAINDER
            and self.feature_type is not FeatureType.OTHER_TECHNICAL_FEATURE
        ):
            raise ValueError("an uncovered remainder is typed OTHER_TECHNICAL_FEATURE")
        expected_status = (
            FeatureVerificationStatus.VERIFIED_EXACT_CLAIM_ANCHOR
            if self.derivation is FeatureDerivation.MODEL_PROPOSED_VERIFIED
            else FeatureVerificationStatus.DERIVED_FROM_CLAIM_TEXT
        )
        if self.verification_status is not expected_status:
            raise ValueError("verification_status must match how the feature was derived")
        return self

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)

    @property
    def relationship_bearing(self) -> bool:
        return self.feature_type in RELATIONSHIP_BEARING_TYPES


class RejectedFeatureProposal(MawhibaModel):
    """A model feature proposal that did not survive verification. Audit only."""

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    proposed_type: str = Field(default="", max_length=64)
    proposed_text_summary: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)
    reason: FeatureRejectionReason


class ComparisonFeatureInventory(MawhibaModel):
    """The comparison features of ONE claim. A separate artifact from the
    Phase 2E inventory it starts from, which it never mutates."""

    inventory_id: UUID
    nd_run_id: UUID
    research_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    claim_text_length: int = Field(ge=1)
    mode: InventoryMode
    mode_reasons: list[InventoryModeReason] = Field(default_factory=list)
    completeness: InventoryCompleteness
    issues: list[InventoryIssue] = Field(default_factory=list)
    features: list[ComparisonFeature] = Field(min_length=1)
    rejected_proposals: list[RejectedFeatureProposal] = Field(default_factory=list)
    phase2e_component_ids: list[str] = Field(default_factory=list)
    phase2e_inventory_completeness: str | None = None
    extraction_prompt_version: str | None = None
    model_name: str | None = None
    feature_schema_version: str = COMPARISON_FEATURE_SCHEMA_VERSION

    @model_validator(mode="after")
    def _inventory_holds(self) -> ComparisonFeatureInventory:
        if any(f.claim_id != self.claim_id for f in self.features):
            raise ValueError("a feature belongs to a different claim")
        if any(f.end > self.claim_text_length for f in self.features):
            raise ValueError("a feature anchor runs past the end of the claim")
        ids = [f.feature_id for f in self.features]
        if len(set(ids)) != len(ids):
            raise ValueError("feature ids must be unique")
        keys = [(f.feature_type, f.start, f.end) for f in self.features]
        if len(set(keys)) != len(keys):
            raise ValueError("a feature is listed once per type and span")

        fallback = [f for f in self.features if f.derivation is FeatureDerivation.FULL_CLAIM_FALLBACK]
        combos = [f for f in self.features if f.derivation is FeatureDerivation.DETERMINISTIC_COMBINATION]
        elements = [f for f in self.features if f.feature_type is not FeatureType.COMBINATION]
        if self.mode is InventoryMode.FULL_CLAIM_ONLY:
            if not self.mode_reasons:
                raise ValueError("FULL_CLAIM_ONLY must state why component-level comparison is unavailable")
            if len(self.features) != 1 or len(fallback) != 1:
                raise ValueError("FULL_CLAIM_ONLY holds exactly one full-claim feature")
        else:
            if self.mode_reasons:
                raise ValueError("COMPONENT_LEVEL carries no fallback reason")
            if fallback:
                raise ValueError("a component-level inventory holds no full-claim fallback feature")
            if self.phase2e_inventory_completeness != "COMPLETE":
                raise ValueError("component-level comparison requires a COMPLETE Phase 2E inventory")
            # The relationship invariant (section 8): two or more elements always
            # carry the claimed combination as its own feature.
            expected_combos = 1 if len(elements) >= 2 else 0
            if len(combos) != expected_combos:
                raise ValueError(
                    "an inventory with two or more elements must carry exactly one "
                    "deterministic COMBINATION feature; all components found is not "
                    "the claimed combination found"
                )
        remainders = any(f.derivation is FeatureDerivation.UNCOVERED_CLAIM_REMAINDER for f in self.features)
        if remainders != (InventoryIssue.UNCOVERED_MATERIAL_TEXT in self.issues):
            raise ValueError("UNCOVERED_MATERIAL_TEXT is stated exactly when remainder features exist")
        if (self.completeness is InventoryCompleteness.COMPLETE) == bool(self.issues):
            raise ValueError("an inventory is COMPLETE exactly when it states no issue")
        return self

    @property
    def is_component_level(self) -> bool:
        return self.mode is InventoryMode.COMPONENT_LEVEL

    @property
    def combination_feature(self) -> ComparisonFeature | None:
        return next((f for f in self.features if f.feature_type is FeatureType.COMBINATION), None)

    def feature(self, feature_id: UUID) -> ComparisonFeature | None:
        return next((f for f in self.features if f.feature_id == feature_id), None)


# ---------------------------------------------------------------------------
# Candidate profile (sections 10-14, 20-22)
# ---------------------------------------------------------------------------


class CandidateType(StrEnum):
    """Three distinct evidence classes. Never flattened into one source type."""

    PATENT = "PATENT"
    PRODUCT = "PRODUCT"
    OPEN_SOURCE = "OPEN_SOURCE"


CANDIDATE_TYPE_ORDER: tuple[CandidateType, ...] = (
    CandidateType.PATENT,
    CandidateType.PRODUCT,
    CandidateType.OPEN_SOURCE,
)


class CandidateRef(MawhibaModel):
    """Which Phase 2G/2H candidate, in which subrun, under which identity."""

    candidate_type: CandidateType
    candidate_id: UUID
    source_run_id: UUID = Field(description="patent_run_id, product_run_id or oss_run_id.")
    identity_key: str = Field(min_length=1)

    @property
    def key(self) -> tuple[str, str]:
        return (self.candidate_type.value, str(self.candidate_id))


class SourceRecordKind(StrEnum):
    PATENT_TEXT_SNAPSHOT = "PATENT_TEXT_SNAPSHOT"
    PATENT_CANDIDATE_FIELD = "PATENT_CANDIDATE_FIELD"
    PRODUCT_SOURCE_ARTIFACT = "PRODUCT_SOURCE_ARTIFACT"
    PRODUCT_ARTIFACT_FIELD = "PRODUCT_ARTIFACT_FIELD"
    REPOSITORY_SNAPSHOT = "REPOSITORY_SNAPSHOT"


class TextKind(StrEnum):
    PATENT_CLAIMS = "PATENT_CLAIMS"
    PATENT_DESCRIPTION = "PATENT_DESCRIPTION"
    PATENT_ABSTRACT = "PATENT_ABSTRACT"
    PATENT_TITLE = "PATENT_TITLE"
    PRODUCT_PAGE_TEXT = "PRODUCT_PAGE_TEXT"
    PRODUCT_PAGE_TITLE = "PRODUCT_PAGE_TITLE"
    OSS_README = "OSS_README"
    OSS_MANIFEST = "OSS_MANIFEST"
    OSS_CODE_FRAGMENT = "OSS_CODE_FRAGMENT"
    OSS_DESCRIPTION = "OSS_DESCRIPTION"
    OSS_TOPICS = "OSS_TOPICS"
    OSS_RELEASE_METADATA = "OSS_RELEASE_METADATA"


TEXT_KIND_TYPE: dict[TextKind, CandidateType] = {
    TextKind.PATENT_CLAIMS: CandidateType.PATENT,
    TextKind.PATENT_DESCRIPTION: CandidateType.PATENT,
    TextKind.PATENT_ABSTRACT: CandidateType.PATENT,
    TextKind.PATENT_TITLE: CandidateType.PATENT,
    TextKind.PRODUCT_PAGE_TEXT: CandidateType.PRODUCT,
    TextKind.PRODUCT_PAGE_TITLE: CandidateType.PRODUCT,
    TextKind.OSS_README: CandidateType.OPEN_SOURCE,
    TextKind.OSS_MANIFEST: CandidateType.OPEN_SOURCE,
    TextKind.OSS_CODE_FRAGMENT: CandidateType.OPEN_SOURCE,
    TextKind.OSS_DESCRIPTION: CandidateType.OPEN_SOURCE,
    TextKind.OSS_TOPICS: CandidateType.OPEN_SOURCE,
    TextKind.OSS_RELEASE_METADATA: CandidateType.OPEN_SOURCE,
}

METADATA_TEXT_KINDS: frozenset[TextKind] = frozenset(
    {
        TextKind.PATENT_TITLE,
        TextKind.PRODUCT_PAGE_TITLE,
        TextKind.OSS_DESCRIPTION,
        TextKind.OSS_TOPICS,
        TextKind.OSS_RELEASE_METADATA,
    }
)
"""Titles and repository metadata. Never more than context (gates 21-23)."""


class DisclosureCapacity(StrEnum):
    """The strongest feature relation one text can support.

    MATERIAL      -> up to DISCLOSED
    LIMITED       -> up to PARTIALLY_DISCLOSED
    NON_MATERIAL  -> up to RELATED_CONTEXT
    """

    MATERIAL = "MATERIAL"
    LIMITED = "LIMITED"
    NON_MATERIAL = "NON_MATERIAL"


class ScopeLimitation(StrEnum):
    ABSTRACT_SCOPE_ONLY = "ABSTRACT_SCOPE_ONLY"
    TITLE_IS_NOT_DISCLOSURE = "TITLE_IS_NOT_DISCLOSURE"
    TEXT_TRUNCATED_UPSTREAM = "TEXT_TRUNCATED_UPSTREAM"
    TEXT_BOUNDED_FOR_COMPARISON = "TEXT_BOUNDED_FOR_COMPARISON"
    VENDOR_MARKETING_TEXT = "VENDOR_MARKETING_TEXT"
    THIRD_PARTY_OR_MARKETPLACE_TEXT = "THIRD_PARTY_OR_MARKETPLACE_TEXT"
    SOURCE_ROLE_UNKNOWN = "SOURCE_ROLE_UNKNOWN"
    README_IS_DOCUMENTATION_NOT_IMPLEMENTATION = "README_IS_DOCUMENTATION_NOT_IMPLEMENTATION"
    CODE_FRAGMENT_NOT_FULL_FILE = "CODE_FRAGMENT_NOT_FULL_FILE"
    MANIFEST_NOT_FULL_FILE = "MANIFEST_NOT_FULL_FILE"
    REPOSITORY_METADATA_NOT_IMPLEMENTATION = "REPOSITORY_METADATA_NOT_IMPLEMENTATION"
    RELEASE_METADATA_IS_CHRONOLOGY = "RELEASE_METADATA_IS_CHRONOLOGY"
    METADATA_ECHO = "METADATA_ECHO"
    MANIFEST_CANNOT_ESTABLISH_FEATURE_TYPE = "MANIFEST_CANNOT_ESTABLISH_FEATURE_TYPE"


class ComparableText(MawhibaModel):
    """One text a candidate offers for comparison, and what it can support.

    The text itself is not copied here: it stays in the Phase 2G/2H record it
    came from, and every anchor is re-sliced from that record by code.
    """

    text_ref_id: UUID
    source_record_kind: SourceRecordKind
    source_record_id: UUID
    text_kind: TextKind
    capacity: DisclosureCapacity
    scope_limitations: list[ScopeLimitation] = Field(default_factory=list)
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    text_digest: str = Field(pattern=CONTENT_HASH_PATTERN)
    char_count: int = Field(ge=1)
    truncated_upstream: bool = False
    language: str | None = None
    product_source_role: str | None = None

    @model_validator(mode="after")
    def _capacity_follows_kind(self) -> ComparableText:
        if self.text_kind in METADATA_TEXT_KINDS and self.capacity is not DisclosureCapacity.NON_MATERIAL:
            raise ValueError("a title or repository metadata text is never more than NON_MATERIAL")
        if self.capacity is DisclosureCapacity.MATERIAL and self.text_kind not in MATERIAL_CAPABLE_KINDS:
            raise ValueError(f"{self.text_kind.value} can never be a MATERIAL disclosure source")
        if self.text_kind is TextKind.PATENT_ABSTRACT and self.capacity is DisclosureCapacity.MATERIAL:
            raise ValueError("an abstract supports overlap only with an abstract-scope limitation")
        if self.text_kind is TextKind.OSS_CODE_FRAGMENT and self.capacity is DisclosureCapacity.MATERIAL:
            raise ValueError("a code-search fragment is never a full-file disclosure")
        if self.text_kind is TextKind.OSS_README and self.capacity is DisclosureCapacity.MATERIAL:
            raise ValueError("a README is documentation, never implementation proof")
        if self.text_kind is TextKind.PRODUCT_PAGE_TEXT:
            if self.product_source_role is None:
                raise ValueError("a product page text records its source role")
            if (
                self.capacity is DisclosureCapacity.MATERIAL
                and self.product_source_role != "FIRST_PARTY_DOCUMENTATION"
            ):
                raise ValueError(
                    "only verified first-party technical documentation is a MATERIAL "
                    "product disclosure; marketing and third-party text is limited"
                )
        elif self.product_source_role is not None:
            raise ValueError("only a product page text carries a product source role")
        return self


MATERIAL_CAPABLE_KINDS: frozenset[TextKind] = frozenset(
    {
        TextKind.PATENT_CLAIMS,
        TextKind.PATENT_DESCRIPTION,
        TextKind.PRODUCT_PAGE_TEXT,
        TextKind.OSS_MANIFEST,
    }
)

MANIFEST_MATERIAL_FEATURE_TYPES: frozenset[FeatureType] = frozenset(
    {FeatureType.COMPONENT, FeatureType.CONSTRAINT}
)
"""What a full-file manifest can explicitly encode: dependency / component /
package presence and declared version or configuration constraints."""

MANIFEST_LIMITED_FEATURE_TYPES: frozenset[FeatureType] = frozenset({FeatureType.OTHER_TECHNICAL_FEATURE})

_CAPACITY_RANK = {DisclosureCapacity.NON_MATERIAL: 0, DisclosureCapacity.LIMITED: 1, DisclosureCapacity.MATERIAL: 2}


def effective_capacity(
    text_kind: TextKind, base: DisclosureCapacity, feature_type: FeatureType
) -> DisclosureCapacity:
    """Disclosure capacity depends on the source AND on what is being asserted.

    A manifest listing ``opencv-python`` can disclose the COMPONENT "uses
    OpenCV"; it can never establish a mechanism, a function, a sequence, a
    relationship or the full combination, so for those it supports context at
    most. Every other text kind keeps its base capacity.
    """
    if text_kind is not TextKind.OSS_MANIFEST:
        return base
    if feature_type in MANIFEST_MATERIAL_FEATURE_TYPES:
        return base
    if feature_type in MANIFEST_LIMITED_FEATURE_TYPES:
        return base if _CAPACITY_RANK[base] <= 1 else DisclosureCapacity.LIMITED
    return DisclosureCapacity.NON_MATERIAL


class CandidateEligibility(StrEnum):
    ELIGIBLE_FOR_TECHNICAL_COMPARISON = "ELIGIBLE_FOR_TECHNICAL_COMPARISON"
    LIMITED_TEXT_COMPARISON = "LIMITED_TEXT_COMPARISON"
    METADATA_ONLY_NOT_COMPARABLE = "METADATA_ONLY_NOT_COMPARABLE"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    BLOCKED_SOURCE_QUALITY = "BLOCKED_SOURCE_QUALITY"
    INVALID_CANDIDATE_REFERENCE = "INVALID_CANDIDATE_REFERENCE"


COMPARABLE_ELIGIBILITY: frozenset[CandidateEligibility] = frozenset(
    {
        CandidateEligibility.ELIGIBLE_FOR_TECHNICAL_COMPARISON,
        CandidateEligibility.LIMITED_TEXT_COMPARISON,
    }
)


class EligibilityReason(StrEnum):
    MATERIAL_TEXT_AVAILABLE = "MATERIAL_TEXT_AVAILABLE"
    ONLY_LIMITED_TEXT_AVAILABLE = "ONLY_LIMITED_TEXT_AVAILABLE"
    ONLY_METADATA_TEXT_AVAILABLE = "ONLY_METADATA_TEXT_AVAILABLE"
    NO_TEXT_AVAILABLE = "NO_TEXT_AVAILABLE"
    PRODUCT_IDENTITY_CONFLICT = "PRODUCT_IDENTITY_CONFLICT"
    REPOSITORY_DISABLED = "REPOSITORY_DISABLED"
    SNAPSHOT_REFERENCE_UNRESOLVED = "SNAPSHOT_REFERENCE_UNRESOLVED"
    GROUP_REFERENCE_UNRESOLVED = "GROUP_REFERENCE_UNRESOLVED"


class IndependenceUnitKind(StrEnum):
    PATENT_FAMILY = "PATENT_FAMILY"
    PATENT_SINGLETON_FAMILY = "PATENT_SINGLETON_FAMILY"
    PATENT_INDEPENDENCE_UNRESOLVED = "PATENT_INDEPENDENCE_UNRESOLVED"
    PRODUCT_STRONG_ENTITY = "PRODUCT_STRONG_ENTITY"
    PRODUCT_UNRESOLVED_ENTITY = "PRODUCT_UNRESOLVED_ENTITY"
    OSS_INDEPENDENT_ROOT_NETWORK = "OSS_INDEPENDENT_ROOT_NETWORK"
    OSS_DEPENDENT_NETWORK = "OSS_DEPENDENT_NETWORK"


UNIT_KIND_TYPE: dict[IndependenceUnitKind, CandidateType] = {
    IndependenceUnitKind.PATENT_FAMILY: CandidateType.PATENT,
    IndependenceUnitKind.PATENT_SINGLETON_FAMILY: CandidateType.PATENT,
    IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED: CandidateType.PATENT,
    IndependenceUnitKind.PRODUCT_STRONG_ENTITY: CandidateType.PRODUCT,
    IndependenceUnitKind.PRODUCT_UNRESOLVED_ENTITY: CandidateType.PRODUCT,
    IndependenceUnitKind.OSS_INDEPENDENT_ROOT_NETWORK: CandidateType.OPEN_SOURCE,
    IndependenceUnitKind.OSS_DEPENDENT_NETWORK: CandidateType.OPEN_SOURCE,
}

NEVER_INDEPENDENT_UNIT_KINDS: frozenset[IndependenceUnitKind] = frozenset(
    {IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED, IndependenceUnitKind.OSS_DEPENDENT_NETWORK}
)
"""A publication whose family Phase 2G could not establish, and a fork / mirror
/ template lineage, are still compared individually, but never contribute an
independent corroboration unit."""

ALWAYS_INDEPENDENT_UNIT_KINDS: frozenset[IndependenceUnitKind] = frozenset(
    {
        IndependenceUnitKind.PATENT_FAMILY,
        IndependenceUnitKind.PATENT_SINGLETON_FAMILY,
        IndependenceUnitKind.PRODUCT_STRONG_ENTITY,
        IndependenceUnitKind.OSS_INDEPENDENT_ROOT_NETWORK,
    }
)

CORRELATION_GROUP_PREFIX = "correlation:"


class IndependenceUnit(MawhibaModel):
    """The anti-inflation unit a candidate belongs to (section 20).

    Taken from the upstream grouping only: a Phase 2G family whose status Phase
    2G established, a Phase 2H product entity, a Phase 2H repository network.
    Never a cross-type unit.

    ``correlation_group_key`` (products only) names an UNRESOLVED correlation
    group: entities Phase 2H linked by a probable or identical-content link.
    It never merges entities and never states they are one product; it only
    caps their joint contribution to independent corroboration at one.
    """

    candidate_type: CandidateType
    unit_kind: IndependenceUnitKind
    unit_key: str = Field(min_length=1)
    counts_as_independent: bool
    correlation_group_key: str | None = None

    @model_validator(mode="after")
    def _kind_matches_type(self) -> IndependenceUnit:
        if UNIT_KIND_TYPE[self.unit_kind] is not self.candidate_type:
            raise ValueError("an independence unit kind belongs to exactly one candidate type")
        if self.unit_kind in NEVER_INDEPENDENT_UNIT_KINDS and self.counts_as_independent:
            raise ValueError(
                "an unresolved patent family, a fork, a mirror or a template lineage is "
                "never an independent corroboration unit"
            )
        if self.unit_kind in ALWAYS_INDEPENDENT_UNIT_KINDS and not self.counts_as_independent:
            raise ValueError(f"a {self.unit_kind.value} unit counts as independent")
        if self.correlation_group_key is not None:
            if self.candidate_type is not CandidateType.PRODUCT:
                raise ValueError("only product entities carry an unresolved correlation group")
            if not self.correlation_group_key.startswith(CORRELATION_GROUP_PREFIX):
                raise ValueError("a correlation group key is namespaced, never an identity key")
        return self

    @property
    def key(self) -> tuple[str, str]:
        return (self.candidate_type.value, self.unit_key)

    @property
    def corroboration_key(self) -> str | None:
        """The key that counts toward independent corroboration, or None.

        Correlated product entities share one key (capped at one); everything
        else counts by its own unit. Never used to merge or re-identify."""
        if not self.counts_as_independent:
            return None
        return self.correlation_group_key or self.unit_key


class ChronologyBucket(StrEnum):
    BEFORE_CUTOFF = "BEFORE_CUTOFF"
    ON_CUTOFF = "ON_CUTOFF"
    AFTER_CUTOFF = "AFTER_CUTOFF"
    DATE_UNKNOWN = "DATE_UNKNOWN"
    NO_CUTOFF = "NO_CUTOFF"


class ChronologyBasis(StrEnum):
    PATENT_FIRST_PUBLIC_DATE = "PATENT_FIRST_PUBLIC_DATE"
    PRODUCT_SOURCE_REPORTED_DATE = "PRODUCT_SOURCE_REPORTED_DATE"
    REPOSITORY_PROVIDER_DATE = "REPOSITORY_PROVIDER_DATE"
    NO_DATE = "NO_DATE"


class HistoricalVisibility(StrEnum):
    PATENT_PUBLICATION_DATE_RECORDED = "PATENT_PUBLICATION_DATE_RECORDED"
    NOT_PROVEN_SOURCE_REPORTED_DATE = "NOT_PROVEN_SOURCE_REPORTED_DATE"
    NOT_PROVEN_PROVIDER_DATE = "NOT_PROVEN_PROVIDER_DATE"
    UNKNOWN = "UNKNOWN"


class CandidateChronology(MawhibaModel):
    """Chronology carried forward from the candidate's own phase, unchanged in
    meaning. Comparison never reads it; only the synthesis chronology split does."""

    bucket: ChronologyBucket
    basis: ChronologyBasis
    upstream_qualification: str = Field(min_length=1)
    date_field: str | None = None
    date_value: str | None = Field(default=None, pattern=DATE_PATTERN)
    cutoff_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    historical_visibility: HistoricalVisibility
    public_availability_proven: bool = False

    @model_validator(mode="after")
    def _honest(self) -> CandidateChronology:
        if self.basis in (ChronologyBasis.PRODUCT_SOURCE_REPORTED_DATE, ChronologyBasis.REPOSITORY_PROVIDER_DATE):
            if self.public_availability_proven:
                raise ValueError(
                    "a product page date or a repository date never proves historical "
                    "availability or public visibility (sections 21-22)"
                )
        if self.bucket in (ChronologyBucket.BEFORE_CUTOFF, ChronologyBucket.ON_CUTOFF, ChronologyBucket.AFTER_CUTOFF):
            if self.cutoff_date is None or self.date_value is None:
                raise ValueError("a cutoff-relative bucket needs a cutoff and a dated field")
            expected = (
                ChronologyBucket.BEFORE_CUTOFF
                if self.date_value < self.cutoff_date
                else ChronologyBucket.ON_CUTOFF
                if self.date_value == self.cutoff_date
                else ChronologyBucket.AFTER_CUTOFF
            )
            if expected is not self.bucket:
                raise ValueError("the chronology bucket contradicts its dates")
        if self.bucket is ChronologyBucket.NO_CUTOFF and self.cutoff_date is not None:
            raise ValueError("NO_CUTOFF carries no cutoff date")
        if self.bucket is ChronologyBucket.DATE_UNKNOWN and self.date_value is not None:
            raise ValueError("DATE_UNKNOWN carries no date")
        if self.public_availability_proven and self.basis is not ChronologyBasis.PATENT_FIRST_PUBLIC_DATE:
            raise ValueError("only a recorded patent publication date is a public date here")
        return self


class FullTextStatus(StrEnum):
    COMPLETE_TEXT_AVAILABLE = "COMPLETE_TEXT_AVAILABLE"
    PARTIAL_TEXT_ONLY = "PARTIAL_TEXT_ONLY"
    NO_TEXT = "NO_TEXT"


class CandidateSourceQualityProfile(MawhibaModel):
    """Structured, non-scalar source quality (section 13). There is no score."""

    identity_verified: bool
    identity_status: str = Field(min_length=1)
    source_roles: list[str] = Field(default_factory=list)
    available_text_kinds: list[TextKind] = Field(default_factory=list)
    exact_text_available: bool
    full_text_status: FullTextStatus
    chronology_known: bool
    historical_visibility_proven: bool
    candidate_group_resolved: bool
    source_limitations: list[str] = Field(default_factory=list)


class CandidateComparisonProfile(MawhibaModel):
    """Everything Phase 2I needs to know about ONE candidate before comparing it."""

    profile_id: UUID
    nd_run_id: UUID
    research_run_id: UUID
    candidate_ref: CandidateRef
    linked_claim_ids: list[str] = Field(default_factory=list)
    eligibility: CandidateEligibility
    eligibility_reasons: list[EligibilityReason] = Field(min_length=1)
    independence_unit: IndependenceUnit
    chronology: CandidateChronology
    quality: CandidateSourceQualityProfile
    texts: list[ComparableText] = Field(default_factory=list)
    disclosure_policy_version: str = DISCLOSURE_POLICY_VERSION

    @model_validator(mode="after")
    def _eligibility_follows_texts(self) -> CandidateComparisonProfile:
        if self.independence_unit.candidate_type is not self.candidate_ref.candidate_type:
            raise ValueError("a candidate's independence unit must be of its own type")
        if any(TEXT_KIND_TYPE[t.text_kind] is not self.candidate_ref.candidate_type for t in self.texts):
            raise ValueError("a candidate offers only texts of its own type (no cross-type conflation)")
        refs = [t.text_ref_id for t in self.texts]
        if len(set(refs)) != len(refs):
            raise ValueError("text references must be unique")
        capacities = {t.capacity for t in self.texts}
        e = self.eligibility
        if e is CandidateEligibility.ELIGIBLE_FOR_TECHNICAL_COMPARISON and DisclosureCapacity.MATERIAL not in capacities:
            raise ValueError("ELIGIBLE requires at least one MATERIAL text")
        if e is CandidateEligibility.LIMITED_TEXT_COMPARISON and (
            DisclosureCapacity.MATERIAL in capacities or DisclosureCapacity.LIMITED not in capacities
        ):
            raise ValueError("LIMITED_TEXT_COMPARISON means limited text and no material text")
        if e is CandidateEligibility.METADATA_ONLY_NOT_COMPARABLE and (
            not self.texts or capacities != {DisclosureCapacity.NON_MATERIAL}
        ):
            raise ValueError("METADATA_ONLY means only titles or repository metadata")
        if e is CandidateEligibility.CONTENT_UNAVAILABLE and self.texts:
            raise ValueError("CONTENT_UNAVAILABLE carries no text")
        if self.candidate_ref.candidate_type is not CandidateType.PATENT and self.quality.historical_visibility_proven:
            raise ValueError("product and repository historical visibility is never proven here")
        return self

    @property
    def comparable(self) -> bool:
        return self.eligibility in COMPARABLE_ELIGIBILITY

    def text(self, text_ref_id: UUID) -> ComparableText | None:
        return next((t for t in self.texts if t.text_ref_id == text_ref_id), None)


# ---------------------------------------------------------------------------
# Anchors and comparison (sections 14-17)
# ---------------------------------------------------------------------------


class FeatureRelation(StrEnum):
    """Per-feature relation against ONE candidate's compared text.

    ``NOT_DISCLOSED`` means not disclosed in the verified candidate text actually
    compared. It never means absent from the real-world artifact in all forms.
    """

    DISCLOSED = "DISCLOSED"
    PARTIALLY_DISCLOSED = "PARTIALLY_DISCLOSED"
    RELATED_CONTEXT = "RELATED_CONTEXT"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    INSUFFICIENT_SOURCE_TEXT = "INSUFFICIENT_SOURCE_TEXT"
    NOT_COMPARABLE = "NOT_COMPARABLE"


ANCHORED_RELATIONS: frozenset[FeatureRelation] = frozenset(
    {FeatureRelation.DISCLOSED, FeatureRelation.PARTIALLY_DISCLOSED, FeatureRelation.RELATED_CONTEXT}
)
OVERLAP_RELATIONS: frozenset[FeatureRelation] = frozenset(
    {FeatureRelation.DISCLOSED, FeatureRelation.PARTIALLY_DISCLOSED}
)
UNRESOLVED_RELATIONS: frozenset[FeatureRelation] = frozenset(
    {FeatureRelation.INSUFFICIENT_SOURCE_TEXT, FeatureRelation.NOT_COMPARABLE}
)
NEGATIVE_RELATIONS: frozenset[FeatureRelation] = frozenset(
    {FeatureRelation.NOT_DISCLOSED, FeatureRelation.RELATED_CONTEXT}
)

CAPACITY_CEILING: dict[DisclosureCapacity, FeatureRelation] = {
    DisclosureCapacity.MATERIAL: FeatureRelation.DISCLOSED,
    DisclosureCapacity.LIMITED: FeatureRelation.PARTIALLY_DISCLOSED,
    DisclosureCapacity.NON_MATERIAL: FeatureRelation.RELATED_CONTEXT,
}
RELATION_STRENGTH: dict[FeatureRelation, int] = {
    FeatureRelation.RELATED_CONTEXT: 1,
    FeatureRelation.PARTIALLY_DISCLOSED: 2,
    FeatureRelation.DISCLOSED: 3,
}
"""Ordinal for capping only. Never stored, never summed, never a score."""


class FullClaimRelation(StrEnum):
    FULL_CLAIM_TECHNICAL_OVERLAP = "FULL_CLAIM_TECHNICAL_OVERLAP"
    PARTIAL_CLAIM_TECHNICAL_OVERLAP = "PARTIAL_CLAIM_TECHNICAL_OVERLAP"
    COMPONENT_ONLY_OVERLAP = "COMPONENT_ONLY_OVERLAP"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT = "NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT"
    INSUFFICIENT_SOURCE_TEXT = "INSUFFICIENT_SOURCE_TEXT"


class ComparisonStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED_MODEL_ERROR = "FAILED_MODEL_ERROR"
    FAILED_SCHEMA_ERROR = "FAILED_SCHEMA_ERROR"
    OMITTED_BY_LIMIT = "OMITTED_BY_LIMIT"
    NOT_COMPARED_INELIGIBLE = "NOT_COMPARED_INELIGIBLE"
    NOT_EXECUTED_NO_PROVIDER = "NOT_EXECUTED_NO_PROVIDER"


FAILED_COMPARISON_STATUSES: frozenset[ComparisonStatus] = frozenset(
    {ComparisonStatus.FAILED_MODEL_ERROR, ComparisonStatus.FAILED_SCHEMA_ERROR}
)


class AnchorRejectionReason(StrEnum):
    UNKNOWN_FEATURE_REFERENCE = "UNKNOWN_FEATURE_REFERENCE"
    UNKNOWN_TEXT_REFERENCE = "UNKNOWN_TEXT_REFERENCE"
    EMPTY_EXCERPT = "EMPTY_EXCERPT"
    EXCERPT_NOT_IN_TEXT = "EXCERPT_NOT_IN_TEXT"
    CROSS_CANDIDATE_EXCERPT = "CROSS_CANDIDATE_EXCERPT"
    CLAIM_TEXT_AS_EVIDENCE = "CLAIM_TEXT_AS_EVIDENCE"
    AMBIGUOUS_REPEATED_EXCERPT = "AMBIGUOUS_REPEATED_EXCERPT"
    INVALID_OFFSETS = "INVALID_OFFSETS"
    INVALID_OCCURRENCE_INDEX = "INVALID_OCCURRENCE_INDEX"
    SYSTEM_PROMPT_DISCLOSURE = "SYSTEM_PROMPT_DISCLOSURE"
    INVALID_RELATION = "INVALID_RELATION"
    DUPLICATE_FEATURE_JUDGMENT = "DUPLICATE_FEATURE_JUDGMENT"
    ANCHOR_ON_NON_DISCLOSURE_RELATION = "ANCHOR_ON_NON_DISCLOSURE_RELATION"


class RelationResolutionReason(StrEnum):
    """Why a verified relation differs from, or stands in for, a proposal."""

    CAPPED_BY_NON_MATERIAL_SOURCE = "CAPPED_BY_NON_MATERIAL_SOURCE"
    CAPPED_BY_LIMITED_SOURCE = "CAPPED_BY_LIMITED_SOURCE"
    ANCHOR_VERIFICATION_FAILED = "ANCHOR_VERIFICATION_FAILED"
    FEATURE_NOT_JUDGED = "FEATURE_NOT_JUDGED"
    DUPLICATE_JUDGMENT = "DUPLICATE_JUDGMENT"
    INVALID_RELATION = "INVALID_RELATION"
    NEGATIVE_WITHOUT_MATERIAL_TEXT = "NEGATIVE_WITHOUT_MATERIAL_TEXT"
    NEGATIVE_WITHOUT_COMPLETE_MATERIAL_TEXT = "NEGATIVE_WITHOUT_COMPLETE_MATERIAL_TEXT"
    MODEL_INSTRUCTION_FOLLOWING = "MODEL_INSTRUCTION_FOLLOWING"


class OccurrenceResolution(StrEnum):
    """How an anchor was bound to ONE occurrence of its excerpt. Never guessed:
    a repeated excerpt without validated offsets or a validated occurrence
    index is rejected as ambiguous."""

    UNIQUE_IN_TEXT = "UNIQUE_IN_TEXT"
    VALIDATED_EXACT_OFFSETS = "VALIDATED_EXACT_OFFSETS"
    VALIDATED_OCCURRENCE_INDEX = "VALIDATED_OCCURRENCE_INDEX"


class CandidateDisclosureAnchor(MawhibaModel):
    """Exact candidate text supporting ONE feature relation (section 14).

    ``excerpt == source_text[start:end]`` holds by construction: the verifier
    located the excerpt in the exact text the model was shown and stored the
    slice. Model-supplied offsets or an occurrence index are only ever used
    after they are validated against that text.
    """

    anchor_id: UUID
    comparison_id: UUID
    feature_id: UUID
    feature_type: FeatureType
    candidate_ref: CandidateRef
    text_ref_id: UUID
    source_record_kind: SourceRecordKind
    source_record_id: UUID
    text_kind: TextKind
    excerpt: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    occurrence_index: int = Field(ge=1, description="1-based position of the bound occurrence.")
    occurrence_resolution: OccurrenceResolution
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    text_digest: str = Field(pattern=CONTENT_HASH_PATTERN)
    language: str | None = None
    truncated_upstream: bool = False
    base_capacity: DisclosureCapacity
    capacity: DisclosureCapacity
    scope_limitations: list[ScopeLimitation] = Field(default_factory=list)
    verification_status: str = Field(default="VERIFIED_EXACT_CANDIDATE_TEXT", pattern=r"^VERIFIED_EXACT_CANDIDATE_TEXT$")
    verifier_version: str = ANCHOR_VERIFIER_VERSION

    @model_validator(mode="after")
    def _span_holds(self) -> CandidateDisclosureAnchor:
        if self.end <= self.start or len(self.excerpt) != self.end - self.start:
            raise ValueError("an anchor excerpt must be the exact slice at its offsets")
        if TEXT_KIND_TYPE[self.text_kind] is not self.candidate_ref.candidate_type:
            raise ValueError("an anchor must come from its own candidate's text")
        if self.occurrence_index > self.occurrence_count:
            raise ValueError("the bound occurrence must exist in the text")
        if self.occurrence_count > 1 and self.occurrence_resolution is OccurrenceResolution.UNIQUE_IN_TEXT:
            raise ValueError("a repeated excerpt is never bound by first-occurrence guessing")
        if self.occurrence_count == 1 and self.occurrence_index != 1:
            raise ValueError("a unique excerpt is its first occurrence")
        allowed = effective_capacity(self.text_kind, self.base_capacity, self.feature_type)
        if _CAPACITY_RANK[self.capacity] > _CAPACITY_RANK[allowed]:
            raise ValueError(
                f"{self.text_kind.value} cannot support a {self.capacity.value} disclosure of a "
                f"{self.feature_type.value} feature (capacity is source- and feature-sensitive)"
            )
        if self.text_kind in METADATA_TEXT_KINDS and self.capacity is not DisclosureCapacity.NON_MATERIAL:
            raise ValueError("a title or metadata anchor is never more than context")
        if ScopeLimitation.METADATA_ECHO in self.scope_limitations and self.capacity is not DisclosureCapacity.NON_MATERIAL:
            raise ValueError("an excerpt that echoes a title or metadata is context only")
        return self


class RejectedAnchorProposal(MawhibaModel):
    """A model claim the verifier refused. Kept so refusals are auditable."""

    feature_token: str = Field(default="", max_length=32)
    text_token: str = Field(default="", max_length=32)
    excerpt_summary: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)
    reason: AnchorRejectionReason


class FeatureComparisonRecord(MawhibaModel):
    """The verified relation of ONE feature against ONE candidate."""

    feature_id: UUID
    feature_type: FeatureType
    proposed_relation: FeatureRelation | None = Field(
        default=None, description="What the model proposed, when it proposed a valid relation."
    )
    relation: FeatureRelation
    anchor_ids: list[UUID] = Field(default_factory=list)
    resolution_reasons: list[RelationResolutionReason] = Field(default_factory=list)
    model_rationale: str | None = Field(
        default=None, max_length=MAX_RATIONALE_CHARS, description="Advisory only; never evidence."
    )

    @model_validator(mode="after")
    def _anchors_match_relation(self) -> FeatureComparisonRecord:
        if (self.relation in ANCHORED_RELATIONS) != bool(self.anchor_ids):
            raise ValueError(
                "a disclosure or context relation requires a verified anchor, and a "
                "non-disclosure relation carries none (no exact anchor, no assertion)"
            )
        if self.proposed_relation in ANCHORED_RELATIONS and self.relation in ANCHORED_RELATIONS:
            if RELATION_STRENGTH[self.relation] > RELATION_STRENGTH[self.proposed_relation]:
                raise ValueError("verification can only lower a proposed relation, never raise it")
        return self


class ComparisonVector(MawhibaModel):
    """Categorical counts (section 44). Deliberately never combined into one number."""

    features_total: int = Field(ge=0)
    disclosed: int = Field(ge=0)
    partially_disclosed: int = Field(ge=0)
    related_context: int = Field(ge=0)
    not_disclosed: int = Field(ge=0)
    insufficient_source_text: int = Field(ge=0)
    not_comparable: int = Field(ge=0)
    relationship_features_total: int = Field(ge=0)
    relationship_features_disclosed: int = Field(ge=0)
    relationship_features_unresolved: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_add_up(self) -> ComparisonVector:
        parts = (
            self.disclosed + self.partially_disclosed + self.related_context
            + self.not_disclosed + self.insufficient_source_text + self.not_comparable
        )
        if parts != self.features_total:
            raise ValueError("relation counts must add up to the feature total")
        if self.relationship_features_disclosed + self.relationship_features_unresolved > self.relationship_features_total:
            raise ValueError("relationship counts exceed the relationship total")
        return self


def vector_for(records: list[FeatureComparisonRecord]) -> ComparisonVector:
    def count(relation: FeatureRelation) -> int:
        return sum(1 for r in records if r.relation is relation)

    relational = [r for r in records if r.feature_type in RELATIONSHIP_BEARING_TYPES]
    return ComparisonVector(
        features_total=len(records),
        disclosed=count(FeatureRelation.DISCLOSED),
        partially_disclosed=count(FeatureRelation.PARTIALLY_DISCLOSED),
        related_context=count(FeatureRelation.RELATED_CONTEXT),
        not_disclosed=count(FeatureRelation.NOT_DISCLOSED),
        insufficient_source_text=count(FeatureRelation.INSUFFICIENT_SOURCE_TEXT),
        not_comparable=count(FeatureRelation.NOT_COMPARABLE),
        relationship_features_total=len(relational),
        relationship_features_disclosed=sum(1 for r in relational if r.relation is FeatureRelation.DISCLOSED),
        relationship_features_unresolved=sum(1 for r in relational if r.relation in UNRESOLVED_RELATIONS),
    )


def derive_full_claim_relation(records: list[FeatureComparisonRecord]) -> FullClaimRelation:
    """The single-candidate full-claim relation, from verified per-feature relations.

    FULL requires every feature -- the deterministic COMBINATION feature
    included -- to be DISCLOSED by this ONE candidate. Matching every component
    while the combination is not disclosed is COMPONENT_ONLY at best.
    """
    relations = [r.relation for r in records]
    if records and all(r is FeatureRelation.DISCLOSED for r in relations):
        return FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP
    overlapping = [r for r in records if r.relation in OVERLAP_RELATIONS]
    if overlapping:
        if any(r.feature_type in RELATIONSHIP_BEARING_TYPES for r in overlapping):
            return FullClaimRelation.PARTIAL_CLAIM_TECHNICAL_OVERLAP
        return FullClaimRelation.COMPONENT_ONLY_OVERLAP
    if FeatureRelation.RELATED_CONTEXT in relations:
        return FullClaimRelation.CONTEXT_ONLY
    if records and all(r is FeatureRelation.NOT_DISCLOSED for r in relations):
        return FullClaimRelation.NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT
    return FullClaimRelation.INSUFFICIENT_SOURCE_TEXT


class ComparisonLimitation(StrEnum):
    COMPARED_TEXT_IS_BOUNDED = "COMPARED_TEXT_IS_BOUNDED"
    NOT_DISCLOSED_MEANS_NOT_IN_COMPARED_TEXT = "NOT_DISCLOSED_MEANS_NOT_IN_COMPARED_TEXT"
    ABSTRACT_SCOPE_ONLY = "ABSTRACT_SCOPE_ONLY"
    MARKETING_OR_THIRD_PARTY_TEXT = "MARKETING_OR_THIRD_PARTY_TEXT"
    README_OR_FRAGMENT_NOT_IMPLEMENTATION_PROOF = "README_OR_FRAGMENT_NOT_IMPLEMENTATION_PROOF"
    UPSTREAM_TEXT_TRUNCATED = "UPSTREAM_TEXT_TRUNCATED"
    NO_SAME_INVENTION_DETERMINATION = "NO_SAME_INVENTION_DETERMINATION"


UNIVERSAL_COMPARISON_LIMITATIONS: tuple[ComparisonLimitation, ...] = (
    ComparisonLimitation.COMPARED_TEXT_IS_BOUNDED,
    ComparisonLimitation.NOT_DISCLOSED_MEANS_NOT_IN_COMPARED_TEXT,
    ComparisonLimitation.NO_SAME_INVENTION_DETERMINATION,
)


class ClaimCandidateComparison(MawhibaModel):
    """ONE claim against ONE candidate: verified relations, or why there are none."""

    comparison_id: UUID
    nd_run_id: UUID
    research_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    inventory_id: UUID
    profile_id: UUID
    candidate_ref: CandidateRef
    independence_unit: IndependenceUnit
    chronology_bucket: ChronologyBucket
    status: ComparisonStatus
    feature_records: list[FeatureComparisonRecord] = Field(default_factory=list)
    anchors: list[CandidateDisclosureAnchor] = Field(default_factory=list)
    rejected_anchors: list[RejectedAnchorProposal] = Field(default_factory=list)
    full_claim_relation: FullClaimRelation | None = None
    vector: ComparisonVector | None = None
    compared_text_ref_ids: list[UUID] = Field(default_factory=list)
    compared_text_bounded: bool = False
    complete_material_feature_types: list[FeatureType] = Field(
        default_factory=list,
        description="Feature types for which complete MATERIAL-capacity text was "
        "compared. A negative (NOT_DISCLOSED) is admissible only for these: a "
        "manifest says nothing about a mechanism, and an absent text says nothing.",
    )
    model_name: str | None = None
    prompt_version: str | None = None
    limitations: list[ComparisonLimitation] = Field(default_factory=list)
    issue_detail: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)

    @model_validator(mode="after")
    def _comparison_holds(self) -> ClaimCandidateComparison:
        if self.independence_unit.candidate_type is not self.candidate_ref.candidate_type:
            raise ValueError("a comparison's independence unit must be of its candidate's type")
        verified = self.status is ComparisonStatus.VERIFIED
        if not verified:
            if self.feature_records or self.anchors or self.full_claim_relation or self.vector:
                raise ValueError(f"{self.status.value} carries no relations, anchors or full-claim relation")
            return self
        if not self.feature_records or self.vector is None or self.full_claim_relation is None:
            raise ValueError("a verified comparison carries its relations, vector and full-claim relation")
        missing = [l.value for l in UNIVERSAL_COMPARISON_LIMITATIONS if l not in self.limitations]
        if missing:
            raise ValueError(f"a verified comparison must state its limitations; missing {missing}")
        if self.prompt_version is None or self.model_name is None:
            raise ValueError("a model-assisted comparison records its prompt version and model")
        ids = [r.feature_id for r in self.feature_records]
        if len(set(ids)) != len(ids):
            raise ValueError("a feature has exactly one relation per comparison (no duplicates)")
        by_anchor = {a.anchor_id: a for a in self.anchors}
        if len(by_anchor) != len(self.anchors):
            raise ValueError("anchor ids must be unique")
        referenced = [a for r in self.feature_records for a in r.anchor_ids]
        if sorted(map(str, referenced)) != sorted(map(str, by_anchor)):
            raise ValueError("every anchor is referenced by exactly one feature relation")
        compared = set(self.compared_text_ref_ids)
        for anchor in self.anchors:
            if anchor.comparison_id != self.comparison_id:
                raise ValueError("an anchor belongs to a different comparison")
            if anchor.candidate_ref != self.candidate_ref:
                raise ValueError("cross-candidate evidence mixing: an anchor names another candidate")
            if anchor.text_ref_id not in compared:
                raise ValueError("an anchor cites a text that was not compared")
        for record in self.feature_records:
            anchors = [by_anchor[a] for a in record.anchor_ids]
            if any(a.feature_id != record.feature_id or a.feature_type is not record.feature_type for a in anchors):
                raise ValueError("an anchor supports a different feature")
            if record.relation in ANCHORED_RELATIONS:
                ceiling = max(RELATION_STRENGTH[CAPACITY_CEILING[a.capacity]] for a in anchors)
                if RELATION_STRENGTH[record.relation] > ceiling:
                    raise ValueError(
                        f"{record.relation.value} exceeds what its source text can support; "
                        "a title, metadata or limited text cannot carry a full disclosure"
                    )
            if (
                record.relation is FeatureRelation.NOT_DISCLOSED
                and record.feature_type not in self.complete_material_feature_types
            ):
                raise ValueError(
                    "NOT_DISCLOSED requires complete material candidate text to have been "
                    "compared; unavailable text is never a negative disclosure"
                )
        if self.full_claim_relation is not derive_full_claim_relation(self.feature_records):
            raise ValueError("the full-claim relation must be derived from the verified feature relations")
        if self.vector != vector_for(self.feature_records):
            raise ValueError("the comparison vector must be derived from the verified feature relations")
        return self

    @property
    def verified(self) -> bool:
        return self.status is ComparisonStatus.VERIFIED

    def adequate_for(self, feature_types: set[FeatureType]) -> bool:
        """Whether complete material text was compared for every given type."""
        return feature_types <= set(self.complete_material_feature_types)

    def record(self, feature_id: UUID) -> FeatureComparisonRecord | None:
        return next((r for r in self.feature_records if r.feature_id == feature_id), None)


# ---------------------------------------------------------------------------
# Claim synthesis (sections 23-26, 28)
# ---------------------------------------------------------------------------


class ClaimTechnicalPosture(StrEnum):
    """Descriptive only. NOVEL, NOT_NOVEL, ANTICIPATED, INVALID, PATENTABLE and
    UNPATENTABLE are absent and must stay absent (section 24)."""

    MATERIAL_TECHNICAL_OVERLAP_FOUND = "MATERIAL_TECHNICAL_OVERLAP_FOUND"
    PARTIAL_TECHNICAL_OVERLAP_ONLY = "PARTIAL_TECHNICAL_OVERLAP_ONLY"
    NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS = "NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS"
    MIXED_OVERLAP_AND_DIFFERENTIATION = "MIXED_OVERLAP_AND_DIFFERENTIATION"
    INSUFFICIENT_COMPARISON_EVIDENCE = "INSUFFICIENT_COMPARISON_EVIDENCE"
    BLOCKED_SOURCE_QUALITY = "BLOCKED_SOURCE_QUALITY"


class DifferentiationStatus(StrEnum):
    DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES = "DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES"
    PARTIALLY_DISCLOSED = "PARTIALLY_DISCLOSED"
    NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT = "NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT"
    UNRESOLVED_DUE_TO_SOURCE_LIMITATIONS = "UNRESOLVED_DUE_TO_SOURCE_LIMITATIONS"


class FeatureDifferentiation(MawhibaModel):
    """One feature's status across every verified comparison of its claim."""

    feature_id: UUID
    feature_type: FeatureType
    claim_text: str = Field(min_length=1)
    status: DifferentiationStatus
    disclosing_comparison_ids: list[UUID] = Field(default_factory=list)
    partial_comparison_ids: list[UUID] = Field(default_factory=list)
    negative_comparison_ids: list[UUID] = Field(default_factory=list)
    unresolved_comparison_ids: list[UUID] = Field(default_factory=list)
    qualifier: str = Field(default=DIFFERENTIATION_QUALIFIER, pattern=f"^{DIFFERENTIATION_QUALIFIER}$")

    @model_validator(mode="after")
    def _status_follows_comparisons(self) -> FeatureDifferentiation:
        expected = differentiation_status(
            bool(self.disclosing_comparison_ids),
            bool(self.partial_comparison_ids),
            bool(self.negative_comparison_ids),
            bool(self.unresolved_comparison_ids),
        )
        if self.status is not expected:
            raise ValueError(
                "a feature's differentiation status must follow from its comparisons; "
                "NOT_FOUND needs every compared candidate resolved negatively"
            )
        return self


def differentiation_status(
    disclosed: bool, partial: bool, negative: bool, unresolved: bool
) -> DifferentiationStatus:
    if disclosed:
        return DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES
    if partial:
        return DifferentiationStatus.PARTIALLY_DISCLOSED
    if negative and not unresolved:
        return DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT
    return DifferentiationStatus.UNRESOLVED_DUE_TO_SOURCE_LIMITATIONS


class ComparisonCoverageStatus(StrEnum):
    COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS = "COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS"
    PARTIAL_COMPARISON_LIMIT = "PARTIAL_COMPARISON_LIMIT"
    PARTIAL_SOURCE_UNAVAILABLE = "PARTIAL_SOURCE_UNAVAILABLE"
    PARTIAL_ERROR = "PARTIAL_ERROR"
    NOT_EXECUTED = "NOT_EXECUTED"


class TypeCoverage(MawhibaModel):
    """Coverage for ONE candidate type. Types are never summed together."""

    candidate_type: CandidateType
    available: int = Field(default=0, ge=0)
    compared: int = Field(default=0, ge=0)
    omitted_by_limit: int = Field(default=0, ge=0)
    blocked_by_source_quality: int = Field(default=0, ge=0)
    not_comparable: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    not_executed: int = Field(default=0, ge=0)
    units_compared: int = Field(default=0, ge=0)
    independent_units_compared: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _adds_up(self) -> TypeCoverage:
        accounted = (
            self.compared + self.omitted_by_limit + self.blocked_by_source_quality
            + self.not_comparable + self.failed + self.not_executed
        )
        if accounted != self.available:
            raise ValueError("every available candidate is accounted for exactly once (no silent drop)")
        if self.independent_units_compared > self.units_compared or self.units_compared > self.compared:
            raise ValueError("independent units <= compared units <= compared candidates")
        return self


class ClaimComparisonCoverage(MawhibaModel):
    status: ComparisonCoverageStatus
    flags: list[ComparisonCoverageStatus] = Field(default_factory=list)
    per_type: list[TypeCoverage] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _honest(self) -> ClaimComparisonCoverage:
        if [t.candidate_type for t in self.per_type] != list(CANDIDATE_TYPE_ORDER):
            raise ValueError("per-type coverage lists PATENT, PRODUCT, OPEN_SOURCE once each")
        compared = sum(t.compared for t in self.per_type)
        omitted = sum(t.omitted_by_limit for t in self.per_type)
        failed = sum(t.failed for t in self.per_type)
        unavailable = sum(t.not_comparable + t.blocked_by_source_quality for t in self.per_type)
        not_executed = sum(t.not_executed for t in self.per_type)
        expected_flags = []
        if failed:
            expected_flags.append(ComparisonCoverageStatus.PARTIAL_ERROR)
        if omitted:
            expected_flags.append(ComparisonCoverageStatus.PARTIAL_COMPARISON_LIMIT)
        if unavailable:
            expected_flags.append(ComparisonCoverageStatus.PARTIAL_SOURCE_UNAVAILABLE)
        if self.flags != expected_flags:
            raise ValueError("coverage flags must be derived from the per-type counts")
        if compared == 0 or not_executed:
            expected = ComparisonCoverageStatus.NOT_EXECUTED
        elif expected_flags:
            expected = expected_flags[0]
        else:
            expected = ComparisonCoverageStatus.COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS
        if self.status is not expected:
            raise ValueError("partial comparison coverage can never be reported complete")
        return self

    @property
    def complete(self) -> bool:
        return self.status is ComparisonCoverageStatus.COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS

    def for_type(self, candidate_type: CandidateType) -> TypeCoverage:
        return next(t for t in self.per_type if t.candidate_type is candidate_type)


class TypeOverlapSummary(MawhibaModel):
    """Overlap for ONE candidate type, counted in independence units."""

    candidate_type: CandidateType
    full_overlap_candidates: int = Field(default=0, ge=0)
    full_overlap_units: int = Field(default=0, ge=0)
    full_overlap_independent_units: int = Field(
        default=0, ge=0,
        description="Independent corroboration units: unresolved patent families and "
        "fork/mirror lineages contribute none; correlated product entities one in total.",
    )
    full_overlap_unresolved_correlation_groups: int = Field(
        default=0, ge=0,
        description="Products only: unresolved correlation groups among the full "
        "overlaps. Exposed, never merged.",
    )
    partial_overlap_units: int = Field(default=0, ge=0)
    component_only_units: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _units_never_exceed_documents(self) -> TypeOverlapSummary:
        if self.full_overlap_independent_units > self.full_overlap_units or (
            self.full_overlap_units > self.full_overlap_candidates
        ):
            raise ValueError("independent units <= units <= candidate documents (anti-inflation)")
        if self.full_overlap_unresolved_correlation_groups and self.candidate_type is not CandidateType.PRODUCT:
            raise ValueError("only products carry unresolved correlation groups")
        return self


class ChronologySplit(MawhibaModel):
    """Where technical overlaps sit in time, per candidate type (section 21).

    "Overlap" means a verified full-claim, partial-claim or component-only
    relation: an open-source candidate can never reach a full-claim overlap
    (no source file is captured upstream), so keying chronology to full overlap
    alone would make it unsayable for that type.

    Deliberately NOT one generic "disclosed before cutoff" flag. Each type
    states only what its own chronology can say:

    * patent  -- "technical overlap found in a patent publication dated before
      cutoff". A publication date, still no legal prior-art or anticipation.
    * product -- "the overlapping artifact carries a source-reported date before
      cutoff". Never historical public availability.
    * open source -- "the overlapping repository carries a provider date before
      cutoff". created_at / release / commit dates never prove public
      visibility on that date.

    Technical relation != chronology != historical-publicity proof != legal
    prior-art conclusion: the proof fields below are pinned to False.
    """

    overlap_by_type_bucket: dict[str, int] = Field(
        default_factory=dict, description="Keys are 'TYPE:BUCKET', e.g. 'PATENT:BEFORE_CUTOFF'."
    )
    patent_overlap_publication_dated_before_cutoff: bool = False
    product_overlap_artifact_dated_before_cutoff: bool = False
    oss_overlap_provider_dated_before_cutoff: bool = False
    product_historical_availability_proven: bool = False
    oss_historical_public_visibility_proven: bool = False
    legal_prior_art_established: bool = False

    @model_validator(mode="after")
    def _type_specific_statements(self) -> ChronologySplit:
        for key in self.overlap_by_type_bucket:
            type_name, _, bucket = key.partition(":")
            if type_name not in CandidateType.__members__ or bucket not in ChronologyBucket.__members__:
                raise ValueError(f"unknown chronology key {key!r}")
        if (
            self.product_historical_availability_proven
            or self.oss_historical_public_visibility_proven
            or self.legal_prior_art_established
        ):
            raise ValueError(
                "Phase 2I never proves product availability, repository public visibility "
                "or legal prior art from a date"
            )
        for candidate_type, flag in (
            (CandidateType.PATENT, self.patent_overlap_publication_dated_before_cutoff),
            (CandidateType.PRODUCT, self.product_overlap_artifact_dated_before_cutoff),
            (CandidateType.OPEN_SOURCE, self.oss_overlap_provider_dated_before_cutoff),
        ):
            before = self.overlap_by_type_bucket.get(f"{candidate_type.value}:BEFORE_CUTOFF", 0)
            if flag != (before > 0):
                raise ValueError(
                    "a before-cutoff statement for a type requires a BEFORE_CUTOFF overlap "
                    "of that same type; on/after-cutoff and unknown dates never support one"
                )
        return self

    def count(self, candidate_type: CandidateType, bucket: ChronologyBucket) -> int:
        return self.overlap_by_type_bucket.get(f"{candidate_type.value}:{bucket.value}", 0)


class SynthesisLimitation(StrEnum):
    BOUNDED_SEARCH_NOT_EXHAUSTIVE = "BOUNDED_SEARCH_NOT_EXHAUSTIVE"
    BOUNDED_COMPARISON_NOT_EXHAUSTIVE = "BOUNDED_COMPARISON_NOT_EXHAUSTIVE"
    NO_LEGAL_NOVELTY_CONCLUSION = "NO_LEGAL_NOVELTY_CONCLUSION"
    TECHNICAL_OVERLAP_IS_NOT_LEGAL_ANTICIPATION = "TECHNICAL_OVERLAP_IS_NOT_LEGAL_ANTICIPATION"
    NO_MATCH_FOUND_IS_NOT_PROOF_OF_NOVELTY = "NO_MATCH_FOUND_IS_NOT_PROOF_OF_NOVELTY"
    NO_PATENTABILITY_INFRINGEMENT_FTO_OR_COPYING_CONCLUSION = (
        "NO_PATENTABILITY_INFRINGEMENT_FTO_OR_COPYING_CONCLUSION"
    )
    NOT_A_PROJECT_OR_OFFICIAL_SCORE = "NOT_A_PROJECT_OR_OFFICIAL_SCORE"
    SOURCE_TEXT_MAY_BE_INCOMPLETE = "SOURCE_TEXT_MAY_BE_INCOMPLETE"
    PRODUCT_HISTORICAL_AVAILABILITY_MAY_BE_UNKNOWN = "PRODUCT_HISTORICAL_AVAILABILITY_MAY_BE_UNKNOWN"
    OSS_HISTORICAL_VISIBILITY_MAY_BE_UNKNOWN = "OSS_HISTORICAL_VISIBILITY_MAY_BE_UNKNOWN"
    PATENT_FAMILY_GROUPING_IS_NOT_LEGAL_EQUIVALENCE = "PATENT_FAMILY_GROUPING_IS_NOT_LEGAL_EQUIVALENCE"
    PRODUCT_IDENTITY_MAY_BE_UNRESOLVED = "PRODUCT_IDENTITY_MAY_BE_UNRESOLVED"
    PRODUCT_UNRESOLVED_CORRELATION_PRESENT = "PRODUCT_UNRESOLVED_CORRELATION_PRESENT"
    PATENT_FAMILY_UNRESOLVED_NOT_INDEPENDENT = "PATENT_FAMILY_UNRESOLVED_NOT_INDEPENDENT"
    PRODUCT_DATE_IS_SOURCE_REPORTED_NOT_HISTORICAL_PROOF = "PRODUCT_DATE_IS_SOURCE_REPORTED_NOT_HISTORICAL_PROOF"
    OSS_DATE_IS_NOT_PUBLIC_VISIBILITY_PROOF = "OSS_DATE_IS_NOT_PUBLIC_VISIBILITY_PROOF"
    FORKS_MAY_MATERIALLY_DIVERGE = "FORKS_MAY_MATERIALLY_DIVERGE"
    COMPONENT_LEVEL_COMPARISON_UNAVAILABLE = "COMPONENT_LEVEL_COMPARISON_UNAVAILABLE"
    FEATURE_INVENTORY_INCOMPLETE = "FEATURE_INVENTORY_INCOMPLETE"
    COMPARISON_COVERAGE_PARTIAL = "COMPARISON_COVERAGE_PARTIAL"
    UPSTREAM_SEARCH_PARTIAL = "UPSTREAM_SEARCH_PARTIAL"
    POST_CUTOFF_OVERLAP_IS_NOT_PRE_CUTOFF_DISCLOSURE = "POST_CUTOFF_OVERLAP_IS_NOT_PRE_CUTOFF_DISCLOSURE"
    CHRONOLOGY_UNKNOWN_FOR_SOME_CANDIDATES = "CHRONOLOGY_UNKNOWN_FOR_SOME_CANDIDATES"
    NO_CANDIDATES_DISCOVERED = "NO_CANDIDATES_DISCOVERED"


UNIVERSAL_SYNTHESIS_LIMITATIONS: tuple[SynthesisLimitation, ...] = (
    SynthesisLimitation.BOUNDED_SEARCH_NOT_EXHAUSTIVE,
    SynthesisLimitation.BOUNDED_COMPARISON_NOT_EXHAUSTIVE,
    SynthesisLimitation.NO_LEGAL_NOVELTY_CONCLUSION,
    SynthesisLimitation.TECHNICAL_OVERLAP_IS_NOT_LEGAL_ANTICIPATION,
    SynthesisLimitation.NO_MATCH_FOUND_IS_NOT_PROOF_OF_NOVELTY,
    SynthesisLimitation.NO_PATENTABILITY_INFRINGEMENT_FTO_OR_COPYING_CONCLUSION,
    SynthesisLimitation.NOT_A_PROJECT_OR_OFFICIAL_SCORE,
)

PROJECT_SUMMARY_LIMITATIONS: tuple[SynthesisLimitation, ...] = (
    *UNIVERSAL_SYNTHESIS_LIMITATIONS,
    SynthesisLimitation.SOURCE_TEXT_MAY_BE_INCOMPLETE,
    SynthesisLimitation.PRODUCT_HISTORICAL_AVAILABILITY_MAY_BE_UNKNOWN,
    SynthesisLimitation.OSS_HISTORICAL_VISIBILITY_MAY_BE_UNKNOWN,
    SynthesisLimitation.PATENT_FAMILY_GROUPING_IS_NOT_LEGAL_EQUIVALENCE,
    SynthesisLimitation.PRODUCT_IDENTITY_MAY_BE_UNRESOLVED,
    SynthesisLimitation.FORKS_MAY_MATERIALLY_DIVERGE,
)
"""Section 45: every project summary carries all of these."""


class PostureReason(StrEnum):
    """Which synthesis rule fired. Every posture is explained by one of these."""

    ALL_LINKED_CANDIDATES_BLOCKED_BY_SOURCE_QUALITY = "ALL_LINKED_CANDIDATES_BLOCKED_BY_SOURCE_QUALITY"
    SINGLE_CANDIDATE_DISCLOSES_FULL_COMBINATION = "SINGLE_CANDIDATE_DISCLOSES_FULL_COMBINATION"
    NO_VERIFIED_COMPARISON = "NO_VERIFIED_COMPARISON"
    NO_CANDIDATES_DISCOVERED = "NO_CANDIDATES_DISCOVERED"
    OVERLAP_WITH_DIFFERENTIATING_FEATURES = "OVERLAP_WITH_DIFFERENTIATING_FEATURES"
    OVERLAP_WITHOUT_FULL_COMBINATION = "OVERLAP_WITHOUT_FULL_COMBINATION"
    NO_OVERLAP_IN_ADEQUATE_COMPLETE_COMPARISON = "NO_OVERLAP_IN_ADEQUATE_COMPLETE_COMPARISON"
    NO_OVERLAP_BUT_COMPARISON_NOT_ADEQUATE = "NO_OVERLAP_BUT_COMPARISON_NOT_ADEQUATE"


class DifferentiationReporting(StrEnum):
    STATED_WITHIN_BOUNDS = "STATED_WITHIN_BOUNDS"
    WITHHELD_FULL_CLAIM_ONLY = "WITHHELD_FULL_CLAIM_ONLY"
    WITHHELD_INCOMPLETE_INVENTORY = "WITHHELD_INCOMPLETE_INVENTORY"
    WITHHELD_PARTIAL_COVERAGE = "WITHHELD_PARTIAL_COVERAGE"
    WITHHELD_INADEQUATE_SOURCE_TEXT = "WITHHELD_INADEQUATE_SOURCE_TEXT"


STRONG_POSTURES: frozenset[ClaimTechnicalPosture] = frozenset(
    {
        ClaimTechnicalPosture.MIXED_OVERLAP_AND_DIFFERENTIATION,
        ClaimTechnicalPosture.NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS,
    }
)
"""Postures that state differentiation. Withheld whenever reporting is withheld."""


class ClaimDifferentiationSynthesis(MawhibaModel):
    """The descriptive technical posture of ONE claim, synthesized in Python."""

    synthesis_id: UUID
    nd_run_id: UUID
    research_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    inventory_id: UUID
    posture: ClaimTechnicalPosture
    posture_reasons: list[PostureReason] = Field(min_length=1)
    differentiation_reporting: DifferentiationReporting
    feature_differentiations: list[FeatureDifferentiation] = Field(min_length=1)
    coverage: ClaimComparisonCoverage
    type_summaries: list[TypeOverlapSummary] = Field(min_length=3, max_length=3)
    chronology: ChronologySplit
    compared_comparison_ids: list[UUID] = Field(default_factory=list)
    full_overlap_comparison_ids: list[UUID] = Field(default_factory=list)
    limitations: list[SynthesisLimitation] = Field(min_length=len(UNIVERSAL_SYNTHESIS_LIMITATIONS))
    policy_version: str = SYNTHESIS_POLICY_VERSION

    @model_validator(mode="after")
    def _posture_is_justified(self) -> ClaimDifferentiationSynthesis:
        missing = [l.value for l in UNIVERSAL_SYNTHESIS_LIMITATIONS if l not in self.limitations]
        if missing:
            raise ValueError(f"every claim posture states its limitations; missing {missing}")
        if [t.candidate_type for t in self.type_summaries] != list(CANDIDATE_TYPE_ORDER):
            raise ValueError("type summaries list PATENT, PRODUCT, OPEN_SOURCE once each")
        if not set(self.full_overlap_comparison_ids) <= set(self.compared_comparison_ids):
            raise ValueError("a full overlap must be one of the compared comparisons")
        statuses = {f.status for f in self.feature_differentiations}
        posture = self.posture
        material = posture is ClaimTechnicalPosture.MATERIAL_TECHNICAL_OVERLAP_FOUND
        if material != bool(self.full_overlap_comparison_ids):
            raise ValueError(
                "MATERIAL_TECHNICAL_OVERLAP_FOUND requires a single candidate disclosing "
                "the full combination, and such a candidate always yields it"
            )
        if posture in STRONG_POSTURES and self.differentiation_reporting is not DifferentiationReporting.STATED_WITHIN_BOUNDS:
            raise ValueError("a differentiation posture cannot be stated while differentiation is withheld")
        if posture in STRONG_POSTURES and not self.coverage.complete:
            raise ValueError("partial comparison coverage can never yield a differentiation posture")
        if posture is ClaimTechnicalPosture.NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS and statuses != {
            DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT
        }:
            raise ValueError("no-material-overlap requires every feature resolved as not found")
        if posture is ClaimTechnicalPosture.MIXED_OVERLAP_AND_DIFFERENTIATION and not (
            DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT in statuses
            and statuses & {
                DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES,
                DifferentiationStatus.PARTIALLY_DISCLOSED,
            }
        ):
            raise ValueError("MIXED requires both an overlapping and a not-found feature")
        if posture is ClaimTechnicalPosture.PARTIAL_TECHNICAL_OVERLAP_ONLY and not statuses & {
            DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES,
            DifferentiationStatus.PARTIALLY_DISCLOSED,
        }:
            raise ValueError("PARTIAL_TECHNICAL_OVERLAP_ONLY requires an overlapping feature")
        if posture in (
            ClaimTechnicalPosture.PARTIAL_TECHNICAL_OVERLAP_ONLY,
            ClaimTechnicalPosture.MIXED_OVERLAP_AND_DIFFERENTIATION,
            ClaimTechnicalPosture.NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS,
        ) and not self.compared_comparison_ids:
            raise ValueError("an overlap or no-overlap posture requires verified comparisons")
        return self


class ProjectDifferentiationSummary(MawhibaModel):
    """Descriptive project-level counts (section 27). No percentage, no score,
    no pass/fail, no ranking -- and no field that could hold one."""

    nd_run_id: UUID
    assessed_claim_count: int = Field(ge=0)
    posture_counts: dict[str, int] = Field(default_factory=dict)
    claims_with_material_overlap: list[str] = Field(default_factory=list)
    claims_with_partial_overlap: list[str] = Field(default_factory=list)
    claims_with_no_material_overlap_within_bounds: list[str] = Field(default_factory=list)
    claims_blocked_or_insufficient: list[str] = Field(default_factory=list)
    claims_with_differentiating_features: list[str] = Field(default_factory=list)
    recurring_differentiating_feature_texts: list[str] = Field(default_factory=list)
    source_type_coverage: list[TypeCoverage] = Field(min_length=3, max_length=3)
    chronology_distribution: dict[str, int] = Field(default_factory=dict)
    candidate_type_distribution: dict[str, int] = Field(default_factory=dict)
    limitations: list[SynthesisLimitation] = Field(min_length=len(PROJECT_SUMMARY_LIMITATIONS))
    policy_version: str = SYNTHESIS_POLICY_VERSION

    @model_validator(mode="after")
    def _descriptive_and_limited(self) -> ProjectDifferentiationSummary:
        missing = [l.value for l in PROJECT_SUMMARY_LIMITATIONS if l not in self.limitations]
        if missing:
            raise ValueError(f"a project summary states every section-45 limitation; missing {missing}")
        if any(k not in ClaimTechnicalPosture.__members__ for k in self.posture_counts):
            raise ValueError("posture counts use only the descriptive posture taxonomy")
        if sum(self.posture_counts.values()) != self.assessed_claim_count:
            raise ValueError("posture counts must add up to the assessed claim count")
        if any(k not in ChronologyBucket.__members__ for k in self.chronology_distribution):
            raise ValueError("unknown chronology bucket")
        if any(k not in CandidateType.__members__ for k in self.candidate_type_distribution):
            raise ValueError("unknown candidate type")
        if [t.candidate_type for t in self.source_type_coverage] != list(CANDIDATE_TYPE_ORDER):
            raise ValueError("source-type coverage lists PATENT, PRODUCT, OPEN_SOURCE once each")
        return self


# ---------------------------------------------------------------------------
# Run (sections 5, 30, 31, 35, 36)
# ---------------------------------------------------------------------------


class NoveltyRunStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    NO_PRIOR_ART_RUNS = "NO_PRIOR_ART_RUNS"
    NO_ELIGIBLE_CLAIMS = "NO_ELIGIBLE_CLAIMS"


class NoveltyIssueCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    SOURCE_CONTENT_UNAVAILABLE = "SOURCE_CONTENT_UNAVAILABLE"
    SOURCE_QUALITY_BLOCKED = "SOURCE_QUALITY_BLOCKED"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_SCHEMA_ERROR = "MODEL_SCHEMA_ERROR"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"
    FABRICATED_ANCHOR = "FABRICATED_ANCHOR"
    CROSS_RUN_REFERENCE = "CROSS_RUN_REFERENCE"
    COMPARISON_LIMIT_REACHED = "COMPARISON_LIMIT_REACHED"
    TIMEOUT = "TIMEOUT"
    SYNTHESIS_BLOCKED = "SYNTHESIS_BLOCKED"


class NoveltyIssue(MawhibaModel):
    code: NoveltyIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)
    claim_id: str | None = None
    candidate_id: UUID | None = None


class ClaimEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_EMPTY_TEXT = "INELIGIBLE_EMPTY_TEXT"
    INELIGIBLE_DUPLICATE_ID = "INELIGIBLE_DUPLICATE_ID"


class ClaimInput(MawhibaModel):
    """A canonical claim as Phase 2I saw it. Bound by hash, never repaired."""

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    status: ClaimEligibilityStatus
    linked_candidate_count: int = Field(default=0, ge=0)


class NoveltyRunVersions(MawhibaModel):
    contract_version: str = NOVELTY_CONTRACT_VERSION
    feature_schema_version: str = COMPARISON_FEATURE_SCHEMA_VERSION
    feature_extraction_prompt_version: str = FEATURE_EXTRACTION_PROMPT_VERSION
    comparison_prompt_version: str = TECHNICAL_COMPARISON_PROMPT_VERSION
    anchor_verifier_version: str = ANCHOR_VERIFIER_VERSION
    disclosure_policy_version: str = DISCLOSURE_POLICY_VERSION
    synthesis_policy_version: str = SYNTHESIS_POLICY_VERSION
    model_provider: str | None = None
    model_name: str | None = None


class NoveltyDifferentiationRun(MawhibaModel):
    """Everything Phase 2I produced in one research run.

    Lives on ``ResearchRun.novelty_differentiation``, never in ``ProjectState``.
    It references claims, Phase 2E inventories and Phase 2G/2H candidates and
    mutates none of them: no field here can hold a claim status, a confidence,
    an evidence reference, a project score, a trust verdict, a novelty verdict
    or a legal conclusion (ADR-020).
    """

    nd_run_id: UUID
    research_run_id: UUID
    status: NoveltyRunStatus = NoveltyRunStatus.NOT_STARTED
    versions: NoveltyRunVersions = Field(default_factory=NoveltyRunVersions)
    bounds: NoveltyComparisonBounds = Field(default_factory=NoveltyComparisonBounds)

    patent_run_id: UUID | None = None
    product_run_id: UUID | None = None
    oss_run_id: UUID | None = None
    sufficiency_run_id: UUID | None = None
    upstream_search_partial: list[CandidateType] = Field(default_factory=list)

    claim_inputs: list[ClaimInput] = Field(default_factory=list)
    inventories: list[ComparisonFeatureInventory] = Field(default_factory=list)
    candidate_profiles: list[CandidateComparisonProfile] = Field(default_factory=list)
    comparisons: list[ClaimCandidateComparison] = Field(default_factory=list)
    claim_syntheses: list[ClaimDifferentiationSynthesis] = Field(default_factory=list)
    project_summary: ProjectDifferentiationSummary | None = None
    model_comparisons_performed: int = Field(default=0, ge=0)
    errors: list[NoveltyIssue] = Field(default_factory=list)
    stage_markers: list[str] = Field(default_factory=list)

    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _internally_consistent(self) -> NoveltyDifferentiationRun:
        run_id, nd = self.research_run_id, self.nd_run_id
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        for label, items in (
            ("inventory", self.inventories),
            ("candidate profile", self.candidate_profiles),
            ("comparison", self.comparisons),
            ("claim synthesis", self.claim_syntheses),
        ):
            if any(i.research_run_id != run_id for i in items):
                raise ValueError(f"a {label} belongs to a different research run (section 31)")
            if any(i.nd_run_id != nd for i in items):
                raise ValueError(f"a {label} belongs to a different Phase 2I run (section 31)")

        claim_ids = [c.claim_id for c in self.claim_inputs]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("a claim is input once")
        known_claims = set(claim_ids)
        inventories = {i.claim_id: i for i in self.inventories}
        if len(inventories) != len(self.inventories):
            raise ValueError("a claim has at most one feature inventory per run")
        if not set(inventories) <= known_claims:
            raise ValueError("an inventory references a claim that is not a run input")
        by_inventory_id = {i.inventory_id: i for i in self.inventories}

        profiles = {p.profile_id: p for p in self.candidate_profiles}
        if len(profiles) != len(self.candidate_profiles):
            raise ValueError("profile ids must be unique")
        candidate_keys = [p.candidate_ref.key for p in self.candidate_profiles]
        if len(set(candidate_keys)) != len(candidate_keys):
            raise ValueError("a candidate has exactly one comparison profile")
        source_runs = {
            CandidateType.PATENT: self.patent_run_id,
            CandidateType.PRODUCT: self.product_run_id,
            CandidateType.OPEN_SOURCE: self.oss_run_id,
        }
        for profile in self.candidate_profiles:
            if profile.candidate_ref.source_run_id != source_runs[profile.candidate_ref.candidate_type]:
                raise ValueError("a candidate profile references a foreign prior-art subrun (section 31)")
            if not set(profile.linked_claim_ids) <= known_claims:
                raise ValueError("a candidate is linked to a claim that is not a run input")

        pair_keys = [(c.claim_id, c.candidate_ref.key) for c in self.comparisons]
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError("a claim/candidate pair is compared once; a replay must not duplicate it")
        by_comparison = {c.comparison_id: c for c in self.comparisons}
        if len(by_comparison) != len(self.comparisons):
            raise ValueError("comparison ids must be unique")
        verified = 0
        for comparison in self.comparisons:
            inventory = by_inventory_id.get(comparison.inventory_id)
            if inventory is None or inventory.claim_id != comparison.claim_id:
                raise ValueError("a comparison references an unknown feature inventory")
            profile = profiles.get(comparison.profile_id)
            if profile is None or profile.candidate_ref != comparison.candidate_ref:
                raise ValueError("a comparison references an unknown candidate profile")
            if comparison.independence_unit != profile.independence_unit:
                raise ValueError("a comparison must carry its candidate's independence unit unchanged")
            if comparison.chronology_bucket is not profile.chronology.bucket:
                raise ValueError("a comparison must carry its candidate's chronology unchanged")
            if comparison.verified:
                verified += 1
                feature_ids = {f.feature_id for f in inventory.features}
                if {r.feature_id for r in comparison.feature_records} != feature_ids:
                    raise ValueError("a verified comparison relates every inventory feature exactly once")
                text_ids = {t.text_ref_id for t in profile.texts}
                if not set(comparison.compared_text_ref_ids) <= text_ids:
                    raise ValueError("a comparison cites a text its candidate does not offer (wrong snapshot)")
                if not profile.comparable:
                    raise ValueError("an ineligible candidate cannot carry a verified comparison")
        if verified > self.model_comparisons_performed:
            raise ValueError("verified comparisons cannot exceed model comparisons performed")
        if self.model_comparisons_performed > self.bounds.max_model_comparisons:
            raise ValueError("model comparisons exceeded the configured bound")

        syntheses = [s.claim_id for s in self.claim_syntheses]
        if len(set(syntheses)) != len(syntheses):
            raise ValueError("a claim has at most one synthesis per run")
        for synthesis in self.claim_syntheses:
            inventory = inventories.get(synthesis.claim_id)
            if inventory is None or inventory.inventory_id != synthesis.inventory_id:
                raise ValueError("a synthesis references an unknown feature inventory")
            if {f.feature_id for f in synthesis.feature_differentiations} != {f.feature_id for f in inventory.features}:
                raise ValueError("a synthesis accounts for every inventory feature exactly once")
            for comparison_id in synthesis.compared_comparison_ids:
                comparison = by_comparison.get(comparison_id)
                if comparison is None:
                    raise ValueError("a synthesis references an unknown comparison id (section 31)")
                if comparison.claim_id != synthesis.claim_id or not comparison.verified:
                    raise ValueError("a synthesis may only cite its own claim's verified comparisons")
            for fd in synthesis.feature_differentiations:
                for comparison_id in (
                    *fd.disclosing_comparison_ids, *fd.partial_comparison_ids,
                    *fd.negative_comparison_ids, *fd.unresolved_comparison_ids,
                ):
                    if comparison_id not in synthesis.compared_comparison_ids:
                        raise ValueError("a feature differentiation cites a comparison outside its synthesis")
            for comparison_id in synthesis.full_overlap_comparison_ids:
                if by_comparison[comparison_id].full_claim_relation is not FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP:
                    raise ValueError("a cited full overlap must be a verified full-claim overlap")
        if self.project_summary is not None:
            if self.project_summary.nd_run_id != nd:
                raise ValueError("the project summary belongs to a different Phase 2I run")
            if self.project_summary.assessed_claim_count != len(self.claim_syntheses):
                raise ValueError("the project summary must count exactly the synthesized claims")

        if self.status is NoveltyRunStatus.NOT_STARTED and (
            self.inventories or self.comparisons or self.claim_syntheses
        ):
            raise ValueError("NOT_STARTED carries no inventories, comparisons or syntheses")
        if self.status is NoveltyRunStatus.NO_PRIOR_ART_RUNS and self.comparisons:
            raise ValueError("NO_PRIOR_ART_RUNS cannot carry comparisons")
        if self.status is NoveltyRunStatus.COMPLETED and self.completed_at is None:
            raise ValueError("a COMPLETED run records completed_at")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.completed_at is not None

    def inventory_for(self, claim_id: str) -> ComparisonFeatureInventory | None:
        return next((i for i in self.inventories if i.claim_id == claim_id), None)

    def synthesis_for(self, claim_id: str) -> ClaimDifferentiationSynthesis | None:
        return next((s for s in self.claim_syntheses if s.claim_id == claim_id), None)

    def comparisons_for(self, claim_id: str) -> list[ClaimCandidateComparison]:
        return [c for c in self.comparisons if c.claim_id == claim_id]

    def profile(self, profile_id: UUID) -> CandidateComparisonProfile | None:
        return next((p for p in self.candidate_profiles if p.profile_id == profile_id), None)


__all__ = [
    "ANCHORED_RELATIONS",
    "ANCHOR_VERIFIER_VERSION",
    "CANDIDATE_TYPE_ORDER",
    "CAPACITY_CEILING",
    "COMPARABLE_ELIGIBILITY",
    "COMPARISON_FEATURE_SCHEMA_VERSION",
    "DIFFERENTIATION_QUALIFIER",
    "DISCLOSURE_POLICY_VERSION",
    "FAILED_COMPARISON_STATUSES",
    "FEATURE_EXTRACTION_PROMPT_VERSION",
    "MATERIAL_CAPABLE_KINDS",
    "METADATA_TEXT_KINDS",
    "MODEL_PROPOSABLE_TYPES",
    "NEGATIVE_RELATIONS",
    "NOVELTY_CONTRACT_VERSION",
    "OVERLAP_RELATIONS",
    "PROJECT_SUMMARY_LIMITATIONS",
    "RELATIONSHIP_BEARING_TYPES",
    "RELATION_STRENGTH",
    "STRONG_POSTURES",
    "SYNTHESIS_POLICY_VERSION",
    "TECHNICAL_COMPARISON_PROMPT_VERSION",
    "TEXT_KIND_TYPE",
    "UNIVERSAL_COMPARISON_LIMITATIONS",
    "UNIVERSAL_SYNTHESIS_LIMITATIONS",
    "UNRESOLVED_RELATIONS",
    "AnchorRejectionReason",
    "CandidateChronology",
    "CandidateComparisonProfile",
    "CandidateDisclosureAnchor",
    "CandidateEligibility",
    "CandidateRef",
    "CandidateSourceQualityProfile",
    "CandidateType",
    "ChronologyBasis",
    "ChronologyBucket",
    "ChronologySplit",
    "ClaimCandidateComparison",
    "ClaimComparisonCoverage",
    "ClaimDifferentiationSynthesis",
    "ClaimEligibilityStatus",
    "ClaimInput",
    "ClaimTechnicalPosture",
    "ComparableText",
    "ComparisonCoverageStatus",
    "ComparisonFeature",
    "ComparisonFeatureInventory",
    "ComparisonLimitation",
    "ComparisonStatus",
    "ComparisonVector",
    "DifferentiationReporting",
    "DifferentiationStatus",
    "DisclosureCapacity",
    "EligibilityReason",
    "FeatureComparisonRecord",
    "FeatureDerivation",
    "FeatureDifferentiation",
    "FeatureMateriality",
    "FeatureRejectionReason",
    "FeatureRelation",
    "FeatureType",
    "FeatureVerificationStatus",
    "FullClaimRelation",
    "FullTextStatus",
    "HistoricalVisibility",
    "IndependenceUnit",
    "IndependenceUnitKind",
    "InventoryCompleteness",
    "InventoryIssue",
    "InventoryMode",
    "InventoryModeReason",
    "NoveltyComparisonBounds",
    "NoveltyDifferentiationRun",
    "NoveltyIssue",
    "NoveltyIssueCode",
    "NoveltyRunStatus",
    "NoveltyRunVersions",
    "PostureReason",
    "ProjectDifferentiationSummary",
    "RejectedAnchorProposal",
    "RejectedFeatureProposal",
    "RelationResolutionReason",
    "ScopeLimitation",
    "SourceRecordKind",
    "SynthesisLimitation",
    "TextKind",
    "TypeCoverage",
    "TypeOverlapSummary",
    "component_id",
    "derive_full_claim_relation",
    "differentiation_status",
    "novelty_id",
    "vector_for",
]
