"""Research / engineering gap assessment contracts -- Phase 2J (ADR-021).

Phase 2J consumes artifacts earlier phases already verified and decides, in
Python, whether the bounded evidence supports a defensible research gap,
engineering gap or hybrid gap that the student's project actually targets. It
performs no search, mutates no upstream record and never asks a model whether a
gap is "real".

The evidence chain is explicit in the types, one record per link:

    GapEvidenceRef            an exact excerpt of an upstream verified record
    GapExistingCapability     what the compared work demonstrably does
    GapLimitation             an ADMISSIBLE, anchored limitation (never absence)
    GapCondition              the bounded condition the evidence supports
    GapProjectLink            one exactly-bound (claim feature, limitation) linkage judgment --
                              structure verified, relation model-assisted (never "verified")
    GapValidationRequirement  what would have to be measured; no threshold
    GapCounterEvidence        bounded counterevidence, never suppressed
    GapChronologyNote         inherited chronology, kept apart from support
    GapHypothesis             one proposed gap, kind and posture decided in code
    ClaimGapAssessment        the claim posture, decided in code
    ProjectGapSummary         descriptive counts, never a score

Distinctions this module refuses to collapse, each enforced structurally:

* **differentiation vs gap.** A Phase 2I differentiating feature is a project
  link, never limitation evidence. Without a verified limitation the posture
  is at most ``DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP``.
* **absence vs limitation.** ``NOT_MENTIONED``, ``FEATURE_ABSENT`` and the other
  absence bases live in ``InadmissibleLimitationBasis``, a type that no
  ``GapLimitation`` can hold.
* **student claim vs evidence.** ``GapSourceKind`` has no student/project value.
  Student text may anchor a project link or a metric, never a limitation.
* **bounded vs field-wide.** ``GapScope`` has no field-wide value and every
  canonical statement carries ``FIELD_WIDE_DISCLAIMER``.
* **gap vs methodology / result / score / novelty.** No field for any of them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.common import MawhibaModel, ProjectType, UtcDatetime
from src.schemas.discovery import CONTENT_HASH_PATTERN, MAX_SAFE_SUMMARY_LENGTH
from src.schemas.novelty_differentiation import (
    ChronologyBucket,
    DifferentiationStatus,
    FeatureType,
    IndependenceUnit,
    OccurrenceResolution,
    TextKind,
)

GAP_CONTRACT_VERSION = "RESEARCH-ENGINEERING-GAP-CONTRACT-V1"
GAP_ANCHOR_VERIFIER_VERSION = "GAP-EVIDENCE-ANCHOR-VERIFIER-V1"
GAP_SYNTHESIS_POLICY_VERSION = "GAP-POSTURE-SYNTHESIS-POLICY-V1"
GAP_CANDIDATE_PROMPT_VERSION = "GAP_CANDIDATE_EXTRACTION_PROMPT_V1"
GAP_LINKAGE_PROMPT_VERSION = "GAP_PROJECT_LINKAGE_PROMPT_V1"
GAP_COUNTEREVIDENCE_PROMPT_VERSION = "GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1"

GAP_ID_NAMESPACE = UUID("5d2e8c41-9a37-5f0b-b6e4-3c1a7f9d2e85")

FIELD_WIDE_DISCLAIMER = "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"
"""Every canonical gap statement carries this qualifier (section 13)."""

PROMPT_LEAK_REDACTION_MARKER = "[redacted: system prompt disclosure]"
"""Persisted in place of any leaked hidden-prompt text. Same marker as Phase 2I."""


def gap_id(*parts: object) -> UUID:
    """A deterministic run-bound id. Same parts, same id, every rerun."""
    return uuid5(GAP_ID_NAMESPACE, "|".join(str(p) for p in parts))


# ---------------------------------------------------------------------------
# Taxonomies (sections 7, 8, 10, 13, 14)
# ---------------------------------------------------------------------------


class GapKind(StrEnum):
    """Decided in code from verified limitation facets, never by the model.

    ``HYBRID`` requires a verified research facet AND a DIFFERENT verified
    engineering facet. ``UNRESOLVED`` is the only fallback; ``HYBRID`` never is.
    """

    RESEARCH = "RESEARCH"
    ENGINEERING = "ENGINEERING"
    HYBRID = "HYBRID"
    UNRESOLVED = "UNRESOLVED"


class GapFacet(StrEnum):
    """Which side of the gap ONE verified limitation supports."""

    RESEARCH = "RESEARCH"
    ENGINEERING = "ENGINEERING"


class GapPosture(StrEnum):
    """Descriptive, evidence-bounded. There is deliberately no
    ``GAP_ESTABLISHED``, ``NO_GAP``, ``FIELD_WIDE_GAP`` or ``NOVEL`` value."""

    SUPPORTED_WITHIN_BOUNDS = "SUPPORTED_WITHIN_BOUNDS"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP = "DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP"
    NOT_ESTABLISHED_WITHIN_BOUNDS = "NOT_ESTABLISHED_WITHIN_BOUNDS"
    COUNTEREVIDENCE_WEAKENS_GAP = "COUNTEREVIDENCE_WEAKENS_GAP"
    BLOCKED_SOURCE_QUALITY = "BLOCKED_SOURCE_QUALITY"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class GapLimitationType(StrEnum):
    """The ONLY limitation forms a ``GapLimitation`` may carry (section 8.2)."""

    EXPLICIT_LIMITATION = "EXPLICIT_LIMITATION"
    MEASURED_SHORTFALL = "MEASURED_SHORTFALL"
    SCOPE_RESTRICTION = "SCOPE_RESTRICTION"
    UNMET_REQUIREMENT = "UNMET_REQUIREMENT"
    REPORTED_FAILURE_MODE = "REPORTED_FAILURE_MODE"
    TRADEOFF = "TRADEOFF"
    UNRESOLVED_QUESTION = "UNRESOLVED_QUESTION"


class InadmissibleLimitationBasis(StrEnum):
    """Never limitation evidence by itself. A separate type, so no accepted
    limitation can hold one of these values even by accident."""

    FEATURE_ABSENT = "FEATURE_ABSENT"
    NOT_MENTIONED = "NOT_MENTIONED"
    NO_MATCH_FOUND = "NO_MATCH_FOUND"
    TITLE_ONLY_DIFFERENCE = "TITLE_ONLY_DIFFERENCE"
    STUDENT_ASSERTION_ONLY = "STUDENT_ASSERTION_ONLY"
    MARKETPLACE_ABSENCE_ONLY = "MARKETPLACE_ABSENCE_ONLY"
    LANGUAGE_ABSENCE_ONLY = "LANGUAGE_ABSENCE_ONLY"
    FUTURE_WORK_ONLY = "FUTURE_WORK_ONLY"
    DIFFERENTIATION_ONLY = "DIFFERENTIATION_ONLY"
    NO_OVERLAP_FOUND_ONLY = "NO_OVERLAP_FOUND_ONLY"


FACET_ELIGIBLE_TYPES: dict[GapFacet, frozenset[GapLimitationType]] = {
    GapFacet.RESEARCH: frozenset(
        {
            GapLimitationType.UNRESOLVED_QUESTION,
            GapLimitationType.SCOPE_RESTRICTION,
            GapLimitationType.EXPLICIT_LIMITATION,
        }
    ),
    GapFacet.ENGINEERING: frozenset(
        {
            GapLimitationType.MEASURED_SHORTFALL,
            GapLimitationType.UNMET_REQUIREMENT,
            GapLimitationType.REPORTED_FAILURE_MODE,
            GapLimitationType.TRADEOFF,
            GapLimitationType.EXPLICIT_LIMITATION,
            GapLimitationType.SCOPE_RESTRICTION,
        }
    ),
}
"""A limitation's facet must be eligible for its type. ``UNRESOLVED_QUESTION``
is research-only; a measured shortfall, unmet requirement, failure mode and
trade-off are engineering-only."""

NUMERIC_LIMITATION_TYPES: frozenset[GapLimitationType] = frozenset({GapLimitationType.MEASURED_SHORTFALL})
"""A measured shortfall must carry a digit inside its own verified excerpt."""


class GapSourceKind(StrEnum):
    """Upstream verified records a gap excerpt may come from. There is no
    student, claim, project or model value: student text is never evidence."""

    ACADEMIC_EVIDENCE = "ACADEMIC_EVIDENCE"
    """A Phase 2C ``ExtractedEvidence``; the excerpt must lie inside its verified span."""
    PRIOR_ART_TEXT = "PRIOR_ART_TEXT"
    """A Phase 2I ``ComparableText`` of a compared candidate, resolved from 2G/2H."""


class GapEvidenceRole(StrEnum):
    EXISTING_CAPABILITY = "EXISTING_CAPABILITY"
    LIMITATION = "LIMITATION"
    CONDITION = "CONDITION"
    COUNTEREVIDENCE = "COUNTEREVIDENCE"


class IndependenceBasis(StrEnum):
    """Where an excerpt's independence key came from. Inherited, never recomputed."""

    ACADEMIC_PHASE2E_GROUP = "ACADEMIC_PHASE2E_GROUP"
    ACADEMIC_UNGROUPED = "ACADEMIC_UNGROUPED"
    PRIOR_ART_PHASE2I_UNIT = "PRIOR_ART_PHASE2I_UNIT"


class GapCorroborationLevel(StrEnum):
    SINGLE_SOURCE_DIRECT = "SINGLE_SOURCE_DIRECT"
    MULTI_SOURCE_CORROBORATED = "MULTI_SOURCE_CORROBORATED"
    MIXED_SOURCE_CORROBORATED = "MIXED_SOURCE_CORROBORATED"
    UNRESOLVED_INDEPENDENCE = "UNRESOLVED_INDEPENDENCE"
    NO_DIRECT_SUPPORT = "NO_DIRECT_SUPPORT"


class GapScope(StrEnum):
    """The safe breadth of a gap statement. No field-wide value exists."""

    SINGLE_SOURCE_BOUNDED = "SINGLE_SOURCE_BOUNDED"
    MULTI_SOURCE_BOUNDED = "MULTI_SOURCE_BOUNDED"
    CANDIDATE_SET_BOUNDED = "CANDIDATE_SET_BOUNDED"
    REVIEW_SYNTHESIS_BOUNDED = "REVIEW_SYNTHESIS_BOUNDED"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"


class ConditionDimension(StrEnum):
    POPULATION = "POPULATION"
    ENVIRONMENT = "ENVIRONMENT"
    OPERATING_REGIME = "OPERATING_REGIME"
    DATASET_DOMAIN = "DATASET_DOMAIN"
    HARDWARE = "HARDWARE"
    RESOURCE = "RESOURCE"
    SCALE = "SCALE"
    GEOGRAPHY = "GEOGRAPHY"
    LANGUAGE = "LANGUAGE"


class SourceQualityVerdict(StrEnum):
    """Whether ONE excerpt may carry a limitation. Ineligible values block."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_RETRACTED = "INELIGIBLE_RETRACTED"
    INELIGIBLE_METADATA_TEXT = "INELIGIBLE_METADATA_TEXT"
    INELIGIBLE_NON_MATERIAL_CAPACITY = "INELIGIBLE_NON_MATERIAL_CAPACITY"


# ---------------------------------------------------------------------------
# Anchored evidence (section 9)
# ---------------------------------------------------------------------------


class GapEvidenceRef(MawhibaModel):
    """An exact excerpt of ONE upstream verified record, located by code.

    ``text_hash`` is the upstream hash of the text the offsets index into
    (Phase 2C ``content_hash`` or Phase 2I ``text_digest``); code re-checks it
    against the resolved text, so a stale or foreign text cannot bind.
    """

    evidence_ref_id: UUID
    source_kind: GapSourceKind
    source_record_id: UUID = Field(description="2C evidence_id, or 2I text_ref_id.")
    upstream_run_id: UUID = Field(description="2C extraction run, or 2I nd_run.")
    candidate_id: UUID | None = None
    text_kind: TextKind | None = None
    text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    excerpt: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    occurrence_index: int = Field(ge=1)
    occurrence_resolution: OccurrenceResolution
    role: GapEvidenceRole
    independence_basis: IndependenceBasis
    independence_key: str = Field(min_length=1)
    counts_as_independent: bool
    correlation_group_key: str | None = None
    inherited_unit: IndependenceUnit | None = None
    source_quality: SourceQualityVerdict
    is_review_source: bool = False
    language: str | None = None
    verifier_version: str = GAP_ANCHOR_VERIFIER_VERSION

    @model_validator(mode="after")
    def _anchor_and_inheritance_hold(self) -> GapEvidenceRef:
        if self.end - self.start != len(self.excerpt):
            raise ValueError("an excerpt's offsets must span exactly the excerpt (section 9)")
        if self.occurrence_index > self.occurrence_count:
            raise ValueError("occurrence_index cannot exceed occurrence_count")
        if self.occurrence_count > 1 and self.occurrence_resolution is OccurrenceResolution.UNIQUE_IN_TEXT:
            raise ValueError("a repeated excerpt is never bound as unique (first-occurrence guessing)")
        check_inherited_independence(self)
        return self


def check_inherited_independence(o: Any) -> None:
    """Shared by an excerpt and by the inventory text it was cut from."""
    prior_art = o.source_kind is GapSourceKind.PRIOR_ART_TEXT
    if prior_art != (o.independence_basis is IndependenceBasis.PRIOR_ART_PHASE2I_UNIT):
        raise ValueError("prior-art text inherits a Phase 2I unit; academic evidence inherits 2E")
    if prior_art:
        if o.inherited_unit is None or o.candidate_id is None or o.text_kind is None:
            raise ValueError("prior-art text carries its candidate, text kind and inherited unit")
        unit = o.inherited_unit
        if (
            o.independence_key != unit.unit_key
            or o.counts_as_independent != unit.counts_as_independent
            or o.correlation_group_key != unit.correlation_group_key
        ):
            raise ValueError("a Phase 2I independence unit is inherited unchanged (section 10)")
        if o.is_review_source:
            raise ValueError("only academic evidence can be a review source")
    else:
        if o.inherited_unit is not None or o.candidate_id is not None or o.text_kind is not None:
            raise ValueError("academic evidence carries no prior-art fields")
        if o.correlation_group_key is not None:
            raise ValueError("correlation groups are a Phase 2H product concept")
        if o.independence_basis is IndependenceBasis.ACADEMIC_UNGROUPED and o.counts_as_independent:
            raise ValueError("evidence Phase 2E did not group is never independent corroboration")


class GapInventoryText(MawhibaModel):
    """One upstream text the run may cite, with everything an excerpt inherits.

    The inventory is the "no new evidence" boundary: an excerpt whose source
    record is not here cannot exist. ``span_start``/``span_end`` bound where
    in ``text_hash``'s text an excerpt may lie (a Phase 2C verified span, or
    the whole of a prior-art text).
    """

    inventory_text_id: UUID
    source_kind: GapSourceKind
    source_record_id: UUID
    upstream_run_id: UUID
    candidate_id: UUID | None = None
    text_kind: TextKind | None = None
    text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=1)
    language: str | None = None
    source_quality: SourceQualityVerdict
    independence_basis: IndependenceBasis
    independence_key: str = Field(min_length=1)
    counts_as_independent: bool
    correlation_group_key: str | None = None
    inherited_unit: IndependenceUnit | None = None
    is_review_source: bool = False
    chronology_bucket: ChronologyBucket | None = None
    chronology_basis: str | None = None
    linked_claim_ids: list[str] = Field(
        default_factory=list, description="Empty = visible to every claim (academic evidence)."
    )

    @model_validator(mode="after")
    def _holds(self) -> GapInventoryText:
        if self.span_end <= self.span_start:
            raise ValueError("an inventory span is non-empty")
        check_inherited_independence(self)
        if (self.chronology_bucket is None) != (self.chronology_basis is None):
            raise ValueError("chronology bucket and basis travel together")
        return self

    def visible_to(self, claim_id: str) -> bool:
        return not self.linked_claim_ids or claim_id in self.linked_claim_ids


class GapAssessmentBounds(MawhibaModel):
    """Every dimension of a run is bounded (a bounded run never reads complete)."""

    max_texts_per_claim: int = Field(default=24, ge=1, le=200)
    max_chars_per_text: int = Field(default=4_000, ge=200, le=50_000)
    max_chars_per_call: int = Field(default=40_000, ge=1_000, le=400_000)
    max_limitations_per_claim: int = Field(default=12, ge=1, le=50)
    max_capabilities_per_claim: int = Field(default=8, ge=1, le=50)
    max_conditions_per_limitation: int = Field(default=4, ge=1, le=20)
    max_counterevidence_per_claim: int = Field(default=8, ge=1, le=50)
    max_link_pairs_per_claim: int = Field(default=60, ge=1, le=400)
    max_model_calls: int = Field(default=150, ge=0, le=5_000)
    model_retry_limit: int = Field(default=1, ge=0, le=5)


class CounterevidenceCoverage(MawhibaModel):
    """Which inventory texts the counterevidence review actually saw."""

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    examined_text_ids: list[UUID] = Field(default_factory=list)
    omitted_text_ids: list[UUID] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.omitted_text_ids

    @model_validator(mode="after")
    def _disjoint(self) -> CounterevidenceCoverage:
        if set(self.examined_text_ids) & set(self.omitted_text_ids):
            raise ValueError("a text is examined or omitted, never both")
        return self


# ---------------------------------------------------------------------------
# The gap chain (section 8)
# ---------------------------------------------------------------------------


class GapExistingCapability(MawhibaModel):
    capability_id: UUID
    evidence_ref_ids: list[UUID] = Field(min_length=1)


class GapLimitation(MawhibaModel):
    """An admissible limitation, anchored. ``limitation_type`` is typed so an
    absence basis cannot be stored here.

    ``condition_dimensions`` lists the dimensions the limitation statement is
    explicitly specific to (model-proposed, recorded). A ``SCOPE_RESTRICTION``
    is condition-specific by definition and must name at least one.
    """

    limitation_id: UUID
    limitation_type: GapLimitationType
    facet: GapFacet
    evidence_ref_ids: list[UUID] = Field(min_length=1)
    condition_dimensions: list[ConditionDimension] = Field(default_factory=list)

    @model_validator(mode="after")
    def _facet_eligible(self) -> GapLimitation:
        if self.limitation_type not in FACET_ELIGIBLE_TYPES[self.facet]:
            raise ValueError(f"{self.limitation_type} cannot support a {self.facet} facet (section 7)")
        if self.limitation_type is GapLimitationType.SCOPE_RESTRICTION and not self.condition_dimensions:
            raise ValueError("a scope restriction is condition-specific and names its dimension")
        if len(set(self.condition_dimensions)) != len(self.condition_dimensions):
            raise ValueError("condition dimensions are listed once")
        return self


class GapCondition(MawhibaModel):
    """A bounded condition, anchored to source evidence, bound to the limitations
    it conditions. No free-text condition."""

    condition_id: UUID
    dimension: ConditionDimension
    limitation_ids: list[UUID] = Field(min_length=1)
    evidence_ref_ids: list[UUID] = Field(min_length=1)


class ConditionMateriality(StrEnum):
    """Derived per limitation (section 8.3, "when material")."""

    CONDITION_REQUIRED_AND_BOUND = "CONDITION_REQUIRED_AND_BOUND"
    CONDITION_NOT_MATERIAL = "CONDITION_NOT_MATERIAL"
    CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED = "CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"


def condition_materiality(
    limitation: GapLimitation, conditions: list[GapCondition], *, narrowed: bool = False
) -> ConditionMateriality:
    """Every dimension the limitation is specific to needs an anchored condition
    of that dimension bound to that limitation. Nothing is synthesized.

    ``narrowed``: different-condition counterevidence exists, which shows the
    limitation may hold only under some condition. A limitation that declared no
    dimension is then condition-material too, and needs SOME anchored condition
    bound to it; none is invented for it."""
    bound = {c.dimension for c in conditions if limitation.limitation_id in c.limitation_ids}
    if not limitation.condition_dimensions:
        if narrowed and not bound:
            return ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED
        if narrowed:
            return ConditionMateriality.CONDITION_REQUIRED_AND_BOUND
        return ConditionMateriality.CONDITION_NOT_MATERIAL
    if set(limitation.condition_dimensions) <= bound:
        return ConditionMateriality.CONDITION_REQUIRED_AND_BOUND
    return ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED


class ProjectLinkStatus(StrEnum):
    DIFFERENTIATING_FEATURE = "DIFFERENTIATING_FEATURE"
    """The Phase 2I status is NOT_FOUND or PARTIALLY_DISCLOSED."""
    FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE = "FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE"
    FEATURE_DIFFERENTIATION_UNRESOLVED = "FEATURE_DIFFERENTIATION_UNRESOLVED"


DIFFERENTIATING_STATUSES: frozenset[DifferentiationStatus] = frozenset(
    {DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT, DifferentiationStatus.PARTIALLY_DISCLOSED}
)


def link_status_for(status: DifferentiationStatus) -> ProjectLinkStatus:
    if status in DIFFERENTIATING_STATUSES:
        return ProjectLinkStatus.DIFFERENTIATING_FEATURE
    if status is DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES:
        return ProjectLinkStatus.FEATURE_DISCLOSED_BY_COMPARED_CANDIDATE
    return ProjectLinkStatus.FEATURE_DIFFERENTIATION_UNRESOLVED


class LinkageRelation(StrEnum):
    """Does ONE project feature materially target ONE limitation?

    Model-assisted bounded judgment, never objective truth: validated IDs and
    hashes prove referential integrity only, never that the relation is right.
    """

    ADDRESSES_LIMITATION = "ADDRESSES_LIMITATION"
    PARTIALLY_ADDRESSES_LIMITATION = "PARTIALLY_ADDRESSES_LIMITATION"
    RELEVANT_BUT_NOT_ADDRESSING = "RELEVANT_BUT_NOT_ADDRESSING"
    UNRELATED = "UNRELATED"
    INSUFFICIENT_LINKAGE_EVIDENCE = "INSUFFICIENT_LINKAGE_EVIDENCE"


MATERIAL_LINKAGE_RELATIONS: frozenset[LinkageRelation] = frozenset(
    {LinkageRelation.ADDRESSES_LIMITATION, LinkageRelation.PARTIALLY_ADDRESSES_LIMITATION}
)

LINKAGE_JUDGMENT_BASIS = "MODEL_ASSISTED_BOUNDED_JUDGMENT"


class GapProjectLink(MawhibaModel):
    """ONE (claim feature, limitation) linkage judgment.

    Identity is exact: the claim and its text hash, the Phase 2I run, the
    feature and its text hash, and a limitation on the same hypothesis. The
    Phase 2I differentiation status is copied unchanged and ``status`` derived
    from it. ``relation`` is a model-assisted judgment, labeled as such.
    """

    link_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    nd_run_id: UUID
    feature_id: UUID
    feature_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    feature_type: FeatureType
    limitation_id: UUID
    inherited_differentiation_status: DifferentiationStatus
    status: ProjectLinkStatus
    relation: LinkageRelation
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = LINKAGE_JUDGMENT_BASIS

    @model_validator(mode="after")
    def _status_inherited(self) -> GapProjectLink:
        if self.status is not link_status_for(self.inherited_differentiation_status):
            raise ValueError("a link status is derived from the Phase 2I status, never asserted")
        return self

    @property
    def is_material(self) -> bool:
        """A differentiating feature that addresses (fully or partially)."""
        return self.status is ProjectLinkStatus.DIFFERENTIATING_FEATURE and self.relation in MATERIAL_LINKAGE_RELATIONS


class ProjectLinkageLevel(StrEnum):
    """Derived per hypothesis over its eligible limitations."""

    FULL = "FULL"
    """Some eligible limitation is ADDRESSED by a differentiating feature."""
    PARTIAL = "PARTIAL"
    """Only PARTIALLY_ADDRESSES links exist."""
    NONE_MATERIAL = "NONE_MATERIAL"
    """No differentiating feature addresses any eligible limitation."""


class GapExistence(StrEnum):
    """Gap existence, kept apart from project linkage."""

    LIMITATION_SUPPORTED = "LIMITATION_SUPPORTED"
    LIMITATION_BLOCKED_SOURCE_QUALITY = "LIMITATION_BLOCKED_SOURCE_QUALITY"
    NO_ELIGIBLE_LIMITATION = "NO_ELIGIBLE_LIMITATION"


class ValidationAnchorOrigin(StrEnum):
    """Where a metric or baseline text was sliced from. Nothing else exists."""

    STUDENT_CLAIM_TEXT = "STUDENT_CLAIM_TEXT"
    LIMITATION_EVIDENCE = "LIMITATION_EVIDENCE"
    EXISTING_CAPABILITY_EVIDENCE = "EXISTING_CAPABILITY_EVIDENCE"


class ValidationAnchor(MawhibaModel):
    origin: ValidationAnchorOrigin
    text: str = Field(min_length=1)
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID_PATTERN)
    evidence_ref_id: UUID | None = None
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _one_origin(self) -> ValidationAnchor:
        if self.end - self.start != len(self.text):
            raise ValueError("a validation anchor spans exactly its text")
        student = self.origin is ValidationAnchorOrigin.STUDENT_CLAIM_TEXT
        if student != (self.claim_id is not None) or student == (self.evidence_ref_id is not None):
            raise ValueError("a validation anchor is sliced from exactly one claim or one evidence ref")
        return self


class GapValidationRequirement(MawhibaModel):
    """What would have to be measured to test the gap. Descriptive only.

    There is deliberately no threshold, target, pass mark or success field:
    a numeric success threshold cannot be stored (section 8.5). Methodology
    adequacy is Phase 3A/3B.
    """

    requirement_id: UUID
    metric: ValidationAnchor
    baseline: ValidationAnchor | None = None
    condition_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _origins_allowed(self) -> GapValidationRequirement:
        if self.metric.origin is ValidationAnchorOrigin.EXISTING_CAPABILITY_EVIDENCE:
            raise ValueError("a metric comes from student material or the limitation evidence")
        if self.baseline is not None and self.baseline.origin is ValidationAnchorOrigin.LIMITATION_EVIDENCE:
            raise ValueError("a baseline comes from student material or the existing-capability evidence")
        return self


class CounterEvidenceKind(StrEnum):
    LIMITATION_ADDRESSED = "LIMITATION_ADDRESSED"
    LIMITATION_NOT_PRESENT = "LIMITATION_NOT_PRESENT"
    DIFFERENTIATION_UNRELATED = "DIFFERENTIATION_UNRELATED"


class ConditionMatch(StrEnum):
    SAME_CONDITION = "SAME_CONDITION"
    DIFFERENT_CONDITION = "DIFFERENT_CONDITION"
    CONDITION_UNKNOWN = "CONDITION_UNKNOWN"


class TemporalEffect(StrEnum):
    """Later evidence may weaken the CURRENT posture only (section 12)."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    WEAKENS_CURRENT_POSTURE_ONLY = "WEAKENS_CURRENT_POSTURE_ONLY"


class GapCounterEvidence(MawhibaModel):
    counter_id: UUID
    kind: CounterEvidenceKind
    condition_match: ConditionMatch
    evidence_ref_ids: list[UUID] = Field(min_length=1)
    chronology_bucket: ChronologyBucket | None = None
    temporal_effect: TemporalEffect = TemporalEffect.NOT_APPLICABLE

    @property
    def is_material(self) -> bool:
        """Different-condition counterevidence narrows scope; it does not defeat."""
        return self.condition_match is not ConditionMatch.DIFFERENT_CONDITION

    @model_validator(mode="after")
    def _temporal_honest(self) -> GapCounterEvidence:
        later = self.chronology_bucket is ChronologyBucket.AFTER_CUTOFF
        if later != (self.temporal_effect is TemporalEffect.WEAKENS_CURRENT_POSTURE_ONLY):
            raise ValueError("after-cutoff counterevidence weakens the current posture only")
        return self


class GapChronologyNote(MawhibaModel):
    """Inherited chronology for one excerpt, stored apart from gap support.

    Chronology is never historical publicity and never legal prior art; both
    booleans are pinned false by type.
    """

    evidence_ref_id: UUID
    bucket: ChronologyBucket
    upstream_basis: str = Field(min_length=1)
    historical_publicity_inferred: Literal[False] = False
    legal_prior_art_established: Literal[False] = False


# ---------------------------------------------------------------------------
# Deterministic policy (section 15) -- the single source of these rules
# ---------------------------------------------------------------------------


def materially_linked(limitations: list[GapLimitation], links: list[GapProjectLink]) -> list[GapLimitation]:
    """Limitations some differentiating feature addresses, fully or partially."""
    targeted = {link.limitation_id for link in links if link.is_material}
    return [lim for lim in limitations if lim.limitation_id in targeted]


def proposition_key(
    limitation: GapLimitation, refs: dict[UUID, GapEvidenceRef]
) -> tuple[str, frozenset[tuple[str, int, int]]]:
    """The narrowest deterministic identity of a limitation PROPOSITION: its
    type over the exact upstream spans it cites (record id + offsets, so a
    re-minted ref id over the same span is the same span). The facet is
    deliberately excluded, so relabelling a copy does not make it distinct.
    Semantic distinctness beyond this is a model-assisted judgment."""
    spans = frozenset(
        (str(refs[i].source_record_id), refs[i].start, refs[i].end) for i in limitation.evidence_ref_ids if i in refs
    )
    return (limitation.limitation_type.value, spans)


def derive_kind(linked: list[GapLimitation]) -> GapKind:
    """Over ELIGIBLE, MATERIALLY LINKED limitations only.

    ``HYBRID`` needs a research limitation and an engineering limitation that
    are different records. They MAY share a source or an excerpt: one passage
    can state an open question and a measured shortfall. Distinct propositions
    are enforced upstream by ``GapHypothesis`` (``proposition_key`` unique), so
    a relabelled copy of one limitation never reaches this function as two.
    """
    research = {lim.limitation_id for lim in linked if lim.facet is GapFacet.RESEARCH}
    engineering = {lim.limitation_id for lim in linked if lim.facet is GapFacet.ENGINEERING}
    if research and engineering:
        # A duplicated id carrying both facets is one ambiguous record, not two.
        distinct_pair = any(r != e for r in research for e in engineering)
        return GapKind.HYBRID if distinct_pair and not research & engineering else GapKind.UNRESOLVED
    if research:
        return GapKind.RESEARCH
    if engineering:
        return GapKind.ENGINEERING
    return GapKind.UNRESOLVED


def derive_linkage(eligible: list[GapLimitation], links: list[GapProjectLink]) -> ProjectLinkageLevel:
    ids = {lim.limitation_id for lim in eligible}
    material = [link for link in links if link.is_material and link.limitation_id in ids]
    if any(link.relation is LinkageRelation.ADDRESSES_LIMITATION for link in material):
        return ProjectLinkageLevel.FULL
    if material:
        return ProjectLinkageLevel.PARTIAL
    return ProjectLinkageLevel.NONE_MATERIAL


def derive_corroboration(refs: list[GapEvidenceRef]) -> GapCorroborationLevel:
    """Over ELIGIBLE limitation excerpts only. A correlation group counts once;
    a never-independent unit contributes nothing (section 10)."""
    if not refs:
        return GapCorroborationLevel.NO_DIRECT_SUPPORT
    units: set[str] = set()
    kinds: set[GapSourceKind] = set()
    for ref in refs:
        if not ref.counts_as_independent:
            continue
        units.add(ref.correlation_group_key or f"{ref.source_kind}:{ref.independence_key}")
        kinds.add(ref.source_kind)
    if not units:
        return GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
    if len(units) == 1:
        return GapCorroborationLevel.SINGLE_SOURCE_DIRECT
    if len(kinds) > 1:
        return GapCorroborationLevel.MIXED_SOURCE_CORROBORATED
    return GapCorroborationLevel.MULTI_SOURCE_CORROBORATED


def derive_scope(refs: list[GapEvidenceRef], corroboration: GapCorroborationLevel) -> GapScope:
    if not refs:
        return GapScope.INSUFFICIENT_SCOPE
    if any(r.is_review_source for r in refs):
        return GapScope.REVIEW_SYNTHESIS_BOUNDED
    if all(r.source_kind is GapSourceKind.PRIOR_ART_TEXT for r in refs):
        return GapScope.CANDIDATE_SET_BOUNDED
    if corroboration in (GapCorroborationLevel.MULTI_SOURCE_CORROBORATED, GapCorroborationLevel.MIXED_SOURCE_CORROBORATED):
        return GapScope.MULTI_SOURCE_BOUNDED
    return GapScope.SINGLE_SOURCE_BOUNDED


class MissingGapComponent(StrEnum):
    EXISTING_CAPABILITY = "EXISTING_CAPABILITY"
    MATERIAL_CONDITION = "MATERIAL_CONDITION"
    FULL_PROJECT_LINKAGE = "FULL_PROJECT_LINKAGE"
    VALIDATION_REQUIREMENT = "VALIDATION_REQUIREMENT"
    RESOLVED_GAP_KIND = "RESOLVED_GAP_KIND"
    COMPLETE_COUNTEREVIDENCE_REVIEW = "COMPLETE_COUNTEREVIDENCE_REVIEW"


def derive_existence(eligible: int, ineligible: int) -> GapExistence:
    if eligible:
        return GapExistence.LIMITATION_SUPPORTED
    return GapExistence.LIMITATION_BLOCKED_SOURCE_QUALITY if ineligible else GapExistence.NO_ELIGIBLE_LIMITATION


def derive_hypothesis_posture(
    *,
    existence: GapExistence,
    linkage: ProjectLinkageLevel,
    material_counterevidence: bool,
    missing: list[MissingGapComponent],
) -> GapPosture:
    """Ordered rules for ONE hypothesis (section 14): gap existence, then
    project linkage, then counterevidence, then completeness.

    A limitation that exists but that no differentiating feature materially
    addresses is not a PROJECT gap: ``NOT_ESTABLISHED_WITHIN_BOUNDS``, while
    ``existence`` still records the limitation. ``PARTIALLY_ADDRESSES`` is
    never full linkage: it adds ``FULL_PROJECT_LINKAGE`` to ``missing``.
    """
    if existence is GapExistence.LIMITATION_BLOCKED_SOURCE_QUALITY:
        return GapPosture.BLOCKED_SOURCE_QUALITY
    if existence is GapExistence.NO_ELIGIBLE_LIMITATION or linkage is ProjectLinkageLevel.NONE_MATERIAL:
        return GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS
    if material_counterevidence:
        return GapPosture.COUNTEREVIDENCE_WEAKENS_GAP
    return GapPosture.PARTIALLY_SUPPORTED if missing else GapPosture.SUPPORTED_WITHIN_BOUNDS


CLAIM_POSTURE_PRECEDENCE: tuple[GapPosture, ...] = (
    GapPosture.SUPPORTED_WITHIN_BOUNDS,
    GapPosture.PARTIALLY_SUPPORTED,
    GapPosture.COUNTEREVIDENCE_WEAKENS_GAP,
    GapPosture.BLOCKED_SOURCE_QUALITY,
    GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS,
)
"""Selection order for the headline claim posture only. Never stored as a
rank, never a score; every hypothesis posture stays visible."""


def derive_claim_posture(
    *, inputs_bound: bool, hypothesis_postures: list[GapPosture], has_differentiating_feature: bool
) -> GapPosture:
    """Section 14 / gate question 18-19.

    * ``INSUFFICIENT_INPUT``  -- upstream cannot be safely bound to this run.
    * ``DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP`` -- bound; no hypothesis is
      SUPPORTED / PARTIAL / WEAKENED / BLOCKED -- either no eligible limitation
      exists, or one exists but no differentiating feature materially
      addresses it -- and Phase 2I shows a differentiating feature.
    * ``NOT_ESTABLISHED_WITHIN_BOUNDS`` -- the same, with no differentiating
      feature.
    """
    if not inputs_bound:
        return GapPosture.INSUFFICIENT_INPUT
    for posture in CLAIM_POSTURE_PRECEDENCE[:4]:
        if posture in hypothesis_postures:
            return posture
    if has_differentiating_feature:
        return GapPosture.DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP
    return GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS


class CounterevidenceScopeEffect(StrEnum):
    """What the counterevidence does to the SAFE SCOPE of the statement, apart
    from GapScope (which is the breadth of the supporting evidence set)."""

    NO_SCOPE_NARROWING = "NO_SCOPE_NARROWING"
    NARROWED_BY_DIFFERENT_CONDITION = "NARROWED_BY_DIFFERENT_CONDITION"
    CONDITION_RELATION_UNRESOLVED = "CONDITION_RELATION_UNRESOLVED"


class GapBoundedStatement(MawhibaModel):
    """The canonical Phase 2J conclusion for one hypothesis, as TYPED records.

    Built only from verified fields (ids of eligible, materially linked
    limitations, the conditions bound to them, the counterevidence that narrowed
    the scope). There is no prose field: nothing a model wrote can reach it, and
    a renderer composes any sentence from these values.
    """

    kind: GapKind
    scope: GapScope
    corroboration: GapCorroborationLevel
    limitation_ids: list[UUID] = Field(default_factory=list)
    condition_ids: list[UUID] = Field(default_factory=list)
    scope_effect: CounterevidenceScopeEffect
    narrowing_counter_ids: list[UUID] = Field(default_factory=list)
    narrowing_current_only: bool = False
    qualifier: Literal["BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"] = "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"


def derive_scope_effect(
    counterevidence: list[GapCounterEvidence],
) -> tuple[CounterevidenceScopeEffect, list[UUID], bool]:
    """(effect, ids of the counterevidence that narrowed, narrowing is current-only).

    UNRESOLVED outranks NARROWED as the label (the less certain fact is the one
    to expose); the narrowing ids stay listed either way. Same-condition
    counterevidence weakens the posture; it does not narrow the scope."""
    narrowing = sorted(
        (c for c in counterevidence if c.condition_match is ConditionMatch.DIFFERENT_CONDITION),
        key=lambda c: str(c.counter_id),
    )
    unresolved = any(c.condition_match is ConditionMatch.CONDITION_UNKNOWN for c in counterevidence)
    if unresolved:
        effect = CounterevidenceScopeEffect.CONDITION_RELATION_UNRESOLVED
    elif narrowing:
        effect = CounterevidenceScopeEffect.NARROWED_BY_DIFFERENT_CONDITION
    else:
        effect = CounterevidenceScopeEffect.NO_SCOPE_NARROWING
    current_only = bool(narrowing) and all(c.chronology_bucket is ChronologyBucket.AFTER_CUTOFF for c in narrowing)
    return effect, [c.counter_id for c in narrowing], current_only


# ---------------------------------------------------------------------------
# Hypothesis / claim / project (sections 14, 17)
# ---------------------------------------------------------------------------


class GapHypothesis(MawhibaModel):
    """One proposed gap. Every derived field is recomputed by the validator."""

    hypothesis_id: UUID
    gap_run_id: UUID
    research_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    evidence_refs: list[GapEvidenceRef] = Field(min_length=1)
    existing_capabilities: list[GapExistingCapability] = Field(default_factory=list)
    limitations: list[GapLimitation] = Field(default_factory=list)
    conditions: list[GapCondition] = Field(default_factory=list)
    project_links: list[GapProjectLink] = Field(default_factory=list)
    validation_requirement: GapValidationRequirement | None = None
    counterevidence: list[GapCounterEvidence] = Field(default_factory=list)
    chronology: list[GapChronologyNote] = Field(default_factory=list)
    counterevidence_review_complete: bool = Field(
        description="Set from the run's counterevidence coverage: every eligible inventory text for this claim "
        "was shown to the review. An incomplete review can never reach SUPPORTED_WITHIN_BOUNDS."
    )
    model_proposed_kind: GapKind | None = Field(default=None, description="Recorded, never trusted.")
    existence: GapExistence
    linkage: ProjectLinkageLevel
    condition_materiality: dict[str, ConditionMateriality] = Field(
        default_factory=dict, description="Per eligible limitation id; derived."
    )
    kind: GapKind
    corroboration: GapCorroborationLevel
    scope: GapScope
    missing_components: list[MissingGapComponent] = Field(default_factory=list)
    posture: GapPosture
    counterevidence_scope_effect: CounterevidenceScopeEffect | None = Field(
        default=None, description="Derived. Left unset on input it is computed; set on input it must match."
    )
    narrowing_counter_ids: list[UUID] | None = Field(default=None, description="Derived; see above.")
    narrowing_current_only: bool | None = Field(default=None, description="Derived; see above.")
    bounded_statement: GapBoundedStatement | None = Field(default=None, description="Derived; see above.")
    statement_qualifier: str = Field(default=FIELD_WIDE_DISCLAIMER, pattern=f"^{FIELD_WIDE_DISCLAIMER}$")
    policy_version: str = GAP_SYNTHESIS_POLICY_VERSION

    @model_validator(mode="after")
    def _derived_fields_hold(self) -> GapHypothesis:
        derived = derive_hypothesis_fields(self)
        stored = {name: getattr(self, name) for name in DERIVED_HYPOTHESIS_FIELDS}
        if stored != derived:
            raise ValueError(
                "existence, linkage, condition materiality, kind, corroboration, scope, "
                "missing components and posture are derived in code"
            )
        effect, narrowing_ids, current_only = derive_scope_effect(self.counterevidence)
        statement = derive_bounded_statement(self, derived, effect, narrowing_ids, current_only)
        for name, value in (
            ("counterevidence_scope_effect", effect),
            ("narrowing_counter_ids", narrowing_ids),
            ("narrowing_current_only", current_only),
            ("bounded_statement", statement),
        ):
            given = getattr(self, name)
            if given is None:
                setattr(self, name, value)
            elif given != value:
                raise ValueError(f"{name} is derived in code")
        return self


DERIVED_HYPOTHESIS_FIELDS: tuple[str, ...] = (
    "existence",
    "linkage",
    "condition_materiality",
    "kind",
    "corroboration",
    "scope",
    "missing_components",
    "posture",
)


def _refs_of(refs: list[GapEvidenceRef], ids: list[UUID], role: GapEvidenceRole) -> list[GapEvidenceRef]:
    by_id = {r.evidence_ref_id: r for r in refs}
    out = []
    for ref_id in ids:
        ref = by_id.get(ref_id)
        if ref is None:
            raise ValueError("a gap component references an excerpt that is not on the hypothesis")
        if ref.role is not role:
            raise ValueError(f"an excerpt used as {role} must carry that role")
        out.append(ref)
    return out


def derive_hypothesis_fields(h: Any) -> dict[str, Any]:
    """The ONE place every derived hypothesis field is computed (section 15).

    ``h`` needs the structural attributes of a hypothesis (``claim_id``,
    ``evidence_refs``, ``existing_capabilities``, ``limitations``,
    ``conditions``, ``project_links``, ``validation_requirement``,
    ``counterevidence``, ``chronology``). The model validator and the pipeline
    builder both call this, so a stored posture can never drift from the rule.
    Raises ``ValueError`` for any structural violation.
    """
    ids = [r.evidence_ref_id for r in h.evidence_refs]
    if len(set(ids)) != len(ids):
        raise ValueError("evidence ref ids are unique")
    for cap in h.existing_capabilities:
        _refs_of(h.evidence_refs, cap.evidence_ref_ids, GapEvidenceRole.EXISTING_CAPABILITY)
    for cond in h.conditions:
        _refs_of(h.evidence_refs, cond.evidence_ref_ids, GapEvidenceRole.CONDITION)
    for counter in h.counterevidence:
        _refs_of(h.evidence_refs, counter.evidence_ref_ids, GapEvidenceRole.COUNTEREVIDENCE)
    eligible_refs: dict[UUID, GapEvidenceRef] = {}
    eligible_limitations: list[GapLimitation] = []
    ineligible = 0
    for lim in h.limitations:
        refs = _refs_of(h.evidence_refs, lim.evidence_ref_ids, GapEvidenceRole.LIMITATION)
        ok = [r for r in refs if r.source_quality is SourceQualityVerdict.ELIGIBLE]
        if lim.limitation_type in NUMERIC_LIMITATION_TYPES and not any(
            any(ch.isdigit() for ch in r.excerpt) for r in refs
        ):
            raise ValueError("a measured shortfall needs a number in its own verified excerpt")
        if ok:
            eligible_limitations.append(lim)
            eligible_refs.update({r.evidence_ref_id: r for r in ok})
        else:
            ineligible += 1
    limitation_ids = {lim.limitation_id for lim in h.limitations}
    if len(limitation_ids) != len(h.limitations):
        raise ValueError("limitation ids are unique")
    by_ref = {r.evidence_ref_id: r for r in h.evidence_refs}
    keys = [proposition_key(lim, by_ref) for lim in h.limitations]
    if len(set(keys)) != len(keys):
        raise ValueError(
            "two limitation records state the same proposition (same type over the same exact spans); "
            "a relabelled copy cannot add a facet or manufacture HYBRID"
        )
    for cond in h.conditions:
        if not set(cond.limitation_ids) <= limitation_ids:
            raise ValueError("a condition conditions a limitation on this hypothesis")
    pairs: set[tuple[UUID, UUID]] = set()
    for link in h.project_links:
        if link.claim_id != h.claim_id:
            raise ValueError("a project link belongs to the hypothesis claim (no cross-claim linkage)")
        if link.limitation_id not in limitation_ids:
            raise ValueError("a project link targets a limitation on this hypothesis (no fabricated limitation)")
        if (link.feature_id, link.limitation_id) in pairs:
            raise ValueError("one linkage judgment per feature and limitation")
        pairs.add((link.feature_id, link.limitation_id))
    if len({(link.nd_run_id, link.claim_text_hash) for link in h.project_links}) > 1:
        raise ValueError("every link binds the same Phase 2I run and claim text")
    if h.validation_requirement is not None:
        known_conditions = {c.condition_id for c in h.conditions}
        if not set(h.validation_requirement.condition_ids) <= known_conditions:
            raise ValueError("a validation requirement may only cite verified conditions")
        for anchor in (h.validation_requirement.metric, h.validation_requirement.baseline):
            if anchor is None or anchor.evidence_ref_id is None:
                if anchor is not None and anchor.claim_id != h.claim_id:
                    raise ValueError("student-material anchors come from the hypothesis claim")
                continue
            role = (
                GapEvidenceRole.LIMITATION
                if anchor.origin is ValidationAnchorOrigin.LIMITATION_EVIDENCE
                else GapEvidenceRole.EXISTING_CAPABILITY
            )
            (ref,) = _refs_of(h.evidence_refs, [anchor.evidence_ref_id], role)
            if not (ref.start <= anchor.start and anchor.end <= ref.end) or ref.excerpt[
                anchor.start - ref.start : anchor.end - ref.start
            ] != anchor.text:
                raise ValueError("an evidence-derived metric or baseline is an exact subspan of its excerpt")
    if any(n.evidence_ref_id not in set(ids) for n in h.chronology):
        raise ValueError("a chronology note references an excerpt on the hypothesis")

    existence = derive_existence(len(eligible_limitations), ineligible)
    linkage = derive_linkage(eligible_limitations, h.project_links)
    linked = materially_linked(eligible_limitations, h.project_links)
    narrowed = any(c.condition_match is ConditionMatch.DIFFERENT_CONDITION for c in h.counterevidence)
    materiality = {
        str(lim.limitation_id): condition_materiality(lim, h.conditions, narrowed=narrowed)
        for lim in eligible_limitations
    }
    kind = derive_kind(linked)
    corroboration = derive_corroboration(list(eligible_refs.values()))
    scope = derive_scope(list(eligible_refs.values()), corroboration)
    missing: list[MissingGapComponent] = []
    if not h.existing_capabilities:
        missing.append(MissingGapComponent.EXISTING_CAPABILITY)
    if any(
        materiality[str(lim.limitation_id)] is ConditionMateriality.CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED
        for lim in linked
    ):
        missing.append(MissingGapComponent.MATERIAL_CONDITION)
    if linkage is not ProjectLinkageLevel.FULL:
        missing.append(MissingGapComponent.FULL_PROJECT_LINKAGE)
    if h.validation_requirement is None:
        missing.append(MissingGapComponent.VALIDATION_REQUIREMENT)
    if kind is GapKind.UNRESOLVED:
        missing.append(MissingGapComponent.RESOLVED_GAP_KIND)
    if not h.counterevidence_review_complete:
        missing.append(MissingGapComponent.COMPLETE_COUNTEREVIDENCE_REVIEW)
    posture = derive_hypothesis_posture(
        existence=existence,
        linkage=linkage,
        material_counterevidence=any(c.is_material for c in h.counterevidence),
        missing=missing,
    )
    return {
        "existence": existence,
        "linkage": linkage,
        "condition_materiality": materiality,
        "kind": kind,
        "corroboration": corroboration,
        "scope": scope,
        "missing_components": missing,
        "posture": posture,
    }


def derive_bounded_statement(
    h: Any, derived: dict[str, Any], effect: CounterevidenceScopeEffect, narrowing_ids: list[UUID], current_only: bool
) -> GapBoundedStatement:
    """The typed canonical conclusion, from verified records only."""
    refs = {r.evidence_ref_id: r for r in h.evidence_refs}
    eligible = [
        lim for lim in h.limitations
        if any(refs[i].source_quality is SourceQualityVerdict.ELIGIBLE for i in lim.evidence_ref_ids)
    ]
    linked = materially_linked(eligible, h.project_links)
    linked_ids = {lim.limitation_id for lim in linked}
    return GapBoundedStatement(
        kind=derived["kind"], scope=derived["scope"], corroboration=derived["corroboration"],
        limitation_ids=sorted((lim.limitation_id for lim in linked), key=str),
        condition_ids=sorted((c.condition_id for c in h.conditions if linked_ids & set(c.limitation_ids)), key=str),
        scope_effect=effect, narrowing_counter_ids=narrowing_ids, narrowing_current_only=current_only,
    )


class _Parts:
    """Attribute bag over hypothesis parts, so derivation can run before the
    model exists."""

    def __init__(self, **parts: Any) -> None:
        self.__dict__.update(parts)


def build_hypothesis(**parts: Any) -> GapHypothesis:
    """Construct a hypothesis whose derived fields come from the single rule."""
    defaults: dict[str, Any] = {
        "existing_capabilities": [], "limitations": [], "conditions": [], "project_links": [],
        "counterevidence": [], "chronology": [], "validation_requirement": None,
        "counterevidence_review_complete": False,
    }
    probe = _Parts(**{**defaults, **parts})
    return GapHypothesis(**{**parts, **derive_hypothesis_fields(probe)})


class InsufficientReason(StrEnum):
    """Why a claim could not be assessed. Each makes ``inputs_bound`` False."""

    NO_PHASE_2I_RUN = "NO_PHASE_2I_RUN"
    PHASE_2I_NOT_COMPLETED = "PHASE_2I_NOT_COMPLETED"
    CLAIM_NOT_IN_PHASE_2I = "CLAIM_NOT_IN_PHASE_2I"
    CLAIM_TEXT_HASH_MISMATCH = "CLAIM_TEXT_HASH_MISMATCH"
    NO_FEATURE_INVENTORY = "NO_FEATURE_INVENTORY"
    NO_PHASE_2I_SYNTHESIS = "NO_PHASE_2I_SYNTHESIS"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    MODEL_CALL_BOUND_REACHED = "MODEL_CALL_BOUND_REACHED"
    UPSTREAM_MUTATED = "UPSTREAM_MUTATED"
    UPSTREAM_RUN_MISMATCH = "UPSTREAM_RUN_MISMATCH"


class ClaimGapAssessment(MawhibaModel):
    assessment_id: UUID
    gap_run_id: UUID
    research_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    inputs_bound: bool
    insufficient_reasons: list[InsufficientReason] = Field(default_factory=list)
    has_differentiating_feature: bool
    hypothesis_ids: list[UUID] = Field(default_factory=list)
    hypothesis_postures: list[GapPosture] = Field(default_factory=list)
    hypothesis_existence: list[GapExistence] = Field(
        default_factory=list, description="Copied; shows a limitation that exists but is not project-linked."
    )
    hypothesis_linkage: list[ProjectLinkageLevel] = Field(default_factory=list)
    rejected_proposal_count: int = Field(default=0, ge=0)
    canonical_project_type: ProjectType
    kind_project_type_note: bool = Field(
        default=False, description="A gap kind differing from the canonical project type is recorded, never rewritten."
    )
    posture: GapPosture

    @model_validator(mode="after")
    def _posture_derived(self) -> ClaimGapAssessment:
        if not len(self.hypothesis_ids) == len(self.hypothesis_postures) == len(self.hypothesis_existence) == len(
            self.hypothesis_linkage
        ):
            raise ValueError("one posture per hypothesis")
        if self.inputs_bound != (not self.insufficient_reasons):
            raise ValueError("a claim is unbound exactly when it states why")
        if not self.inputs_bound and self.hypothesis_ids:
            raise ValueError("an unbound claim has no hypotheses")
        expected = derive_claim_posture(
            inputs_bound=self.inputs_bound,
            hypothesis_postures=self.hypothesis_postures,
            has_differentiating_feature=self.has_differentiating_feature,
        )
        if self.posture is not expected:
            raise ValueError("the claim posture is derived in code")
        return self


class RejectedGapProposal(MawhibaModel):
    """A model proposal code refused. No raw model text is persisted."""

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    reason: str = Field(min_length=1, max_length=64)
    inadmissible_basis: InadmissibleLimitationBasis | None = None
    safe_summary: str = Field(default="", max_length=MAX_SAFE_SUMMARY_LENGTH)


class ProjectGapSummary(MawhibaModel):
    """Descriptive counts only. No score, readiness, ranking or verdict field."""

    gap_run_id: UUID
    assessed_claim_count: int = Field(ge=0)
    hypothesis_count: int = Field(ge=0)
    kind_counts: dict[str, int] = Field(default_factory=dict)
    posture_counts: dict[str, int] = Field(default_factory=dict)
    claim_posture_counts: dict[str, int] = Field(default_factory=dict)
    single_source_supported_count: int = Field(default=0, ge=0)
    corroborated_supported_count: int = Field(default=0, ge=0)
    unresolved_independence_supported_count: int = Field(default=0, ge=0)
    weakened_by_counterevidence_count: int = Field(default=0, ge=0)
    lacking_validation_requirement_count: int = Field(default=0, ge=0)
    statement_qualifier: str = Field(default=FIELD_WIDE_DISCLAIMER, pattern=f"^{FIELD_WIDE_DISCLAIMER}$")


# ---------------------------------------------------------------------------
# The run (sections 4, 5, 16, 18)
# ---------------------------------------------------------------------------


class UpstreamPhase(StrEnum):
    PHASE_2C_EVIDENCE = "PHASE_2C_EVIDENCE"
    PHASE_2E_SUFFICIENCY = "PHASE_2E_SUFFICIENCY"
    PHASE_2F_SCORING = "PHASE_2F_SCORING"
    PHASE_2G_PATENT = "PHASE_2G_PATENT"
    PHASE_2H_PRODUCT = "PHASE_2H_PRODUCT"
    PHASE_2H_OPEN_SOURCE = "PHASE_2H_OPEN_SOURCE"
    PHASE_2I_NOVELTY_DIFFERENTIATION = "PHASE_2I_NOVELTY_DIFFERENTIATION"


class UpstreamBinding(MawhibaModel):
    """A content fingerprint of one upstream subrun taken at bind time and
    re-checked at finalize. A mismatch is an upstream mutation."""

    phase: UpstreamPhase
    upstream_run_id: UUID
    fingerprint: str = Field(pattern=CONTENT_HASH_PATTERN)


class GapRunStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class GapIssueCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    CROSS_RUN_REFERENCE = "CROSS_RUN_REFERENCE"
    STALE_UPSTREAM_HASH = "STALE_UPSTREAM_HASH"
    UPSTREAM_MUTATED = "UPSTREAM_MUTATED"
    FABRICATED_REFERENCE = "FABRICATED_REFERENCE"
    FABRICATED_ANCHOR = "FABRICATED_ANCHOR"
    AMBIGUOUS_ANCHOR = "AMBIGUOUS_ANCHOR"
    INADMISSIBLE_LIMITATION_BASIS = "INADMISSIBLE_LIMITATION_BASIS"
    FORBIDDEN_CONCLUSION = "FORBIDDEN_CONCLUSION"
    SOURCE_INSTRUCTION_FOLLOWED = "SOURCE_INSTRUCTION_FOLLOWED"
    OFF_CONTRACT_OUTPUT = "OFF_CONTRACT_OUTPUT"
    PROMPT_LEAK_REDACTED = "PROMPT_LEAK_REDACTED"
    INVENTED_METRIC = "INVENTED_METRIC"
    INVENTED_THRESHOLD = "INVENTED_THRESHOLD"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"


class GapAssessmentIssue(MawhibaModel):
    code: GapIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)
    claim_id: str | None = None


class GapRunVersions(MawhibaModel):
    contract_version: str = GAP_CONTRACT_VERSION
    anchor_verifier_version: str = GAP_ANCHOR_VERIFIER_VERSION
    synthesis_policy_version: str = GAP_SYNTHESIS_POLICY_VERSION
    candidate_prompt_version: str = GAP_CANDIDATE_PROMPT_VERSION
    linkage_prompt_version: str = GAP_LINKAGE_PROMPT_VERSION
    counterevidence_prompt_version: str = GAP_COUNTEREVIDENCE_PROMPT_VERSION
    model_provider: str | None = None
    model_name: str | None = None


class GapClaimDraft(MawhibaModel):
    """A claim's verified-but-unsynthesized parts, carried between stages.

    Holds only code-verified records (the untrusted model response never
    crosses a checkpoint boundary). Each stage appends its own part; synthesis
    turns the draft into a ``GapHypothesis`` through ``build_hypothesis``.
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    insufficient_reasons: list[InsufficientReason] = Field(default_factory=list)
    has_differentiating_feature: bool = False
    extraction_done: bool = False
    linkage_done: bool = False
    counter_done: bool = False
    evidence_refs: list[GapEvidenceRef] = Field(default_factory=list)
    existing_capabilities: list[GapExistingCapability] = Field(default_factory=list)
    limitations: list[GapLimitation] = Field(default_factory=list)
    conditions: list[GapCondition] = Field(default_factory=list)
    project_links: list[GapProjectLink] = Field(default_factory=list)
    counterevidence: list[GapCounterEvidence] = Field(default_factory=list)
    validation_requirement: GapValidationRequirement | None = None
    model_proposed_kind: GapKind | None = None
    counter_examined_text_ids: list[UUID] = Field(default_factory=list)
    counter_omitted_text_ids: list[UUID] = Field(default_factory=list)
    rejected_count: int = Field(default=0, ge=0)


class GapAssessmentRun(MawhibaModel):
    gap_run_id: UUID
    research_run_id: UUID
    nd_run_id: UUID | None = None
    status: GapRunStatus = GapRunStatus.NOT_STARTED
    versions: GapRunVersions = Field(default_factory=GapRunVersions)
    bounds: GapAssessmentBounds = Field(default_factory=GapAssessmentBounds)
    canonical_project_type: ProjectType = ProjectType.UNKNOWN
    upstream_bindings: list[UpstreamBinding] = Field(default_factory=list)
    inventory_texts: list[GapInventoryText] = Field(
        default_factory=list, description="Every upstream text an excerpt may be cut from (no new evidence)."
    )
    counterevidence_coverage: list[CounterevidenceCoverage] = Field(default_factory=list)
    drafts: list[GapClaimDraft] = Field(default_factory=list)
    eligible_evidence_ref_ids: list[UUID] = Field(
        default_factory=list, description="Every verified excerpt id the run accepted; hypotheses may cite no other."
    )
    hypotheses: list[GapHypothesis] = Field(default_factory=list)
    claim_assessments: list[ClaimGapAssessment] = Field(default_factory=list)
    rejected_proposals: list[RejectedGapProposal] = Field(default_factory=list)
    project_summary: ProjectGapSummary | None = None
    model_calls_performed: int = Field(default=0, ge=0)
    external_search_calls: Literal[0] = 0
    errors: list[GapAssessmentIssue] = Field(default_factory=list)
    stage_markers: list[str] = Field(default_factory=list)
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _bound_and_consistent(self) -> GapAssessmentRun:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        phases = [b.phase for b in self.upstream_bindings]
        if len(set(phases)) != len(phases):
            raise ValueError("one binding per upstream phase")
        if any(h.research_run_id != self.research_run_id or h.gap_run_id != self.gap_run_id for h in self.hypotheses):
            raise ValueError("a hypothesis belongs to a different run (cross-run mixing)")
        if any(
            a.research_run_id != self.research_run_id or a.gap_run_id != self.gap_run_id
            for a in self.claim_assessments
        ):
            raise ValueError("a claim assessment belongs to a different run (cross-run mixing)")
        hyp = {h.hypothesis_id: h for h in self.hypotheses}
        if len(hyp) != len(self.hypotheses):
            raise ValueError("hypothesis ids are unique; a replay must not duplicate them")
        claims = [a.claim_id for a in self.claim_assessments]
        if len(set(claims)) != len(claims):
            raise ValueError("one assessment per claim")
        eligible = set(self.eligible_evidence_ref_ids)
        inventory = {(t.source_kind, t.source_record_id): t for t in self.inventory_texts}
        if len(inventory) != len(self.inventory_texts):
            raise ValueError("an upstream text is inventoried once")
        coverage = {c.claim_id: c for c in self.counterevidence_coverage}
        if len(coverage) != len(self.counterevidence_coverage):
            raise ValueError("one counterevidence coverage record per claim")
        for c in self.counterevidence_coverage:
            visible = {t.inventory_text_id for t in self.inventory_texts if t.visible_to(c.claim_id)}
            if set(c.examined_text_ids) | set(c.omitted_text_ids) != visible:
                raise ValueError("counterevidence coverage must account for every inventory text visible to the claim")
        for h in self.hypotheses:
            cov = coverage.get(h.claim_id)
            if cov is None or cov.complete != h.counterevidence_review_complete:
                raise ValueError("a hypothesis copies its claim's counterevidence coverage completeness")
            for link in h.project_links:
                if link.nd_run_id != self.nd_run_id:
                    raise ValueError("a project link references a foreign Phase 2I run")
            for ref in h.evidence_refs:
                if ref.evidence_ref_id not in eligible:
                    raise ValueError("an excerpt outside the bounded evidence inventory (no new evidence)")
                text = inventory.get((ref.source_kind, ref.source_record_id))
                if text is None:
                    raise ValueError("an excerpt cut from a text outside the bounded inventory (no new evidence)")
                if not text.visible_to(h.claim_id):
                    raise ValueError("an excerpt cut from a text not visible to the claim (cross-claim leakage)")
                if (
                    ref.text_hash != text.text_hash
                    or ref.upstream_run_id != text.upstream_run_id
                    or not (text.span_start <= ref.start and ref.end <= text.span_end)
                ):
                    raise ValueError("an excerpt's hash, run or span disagrees with its inventory text")
                inherited = ("independence_basis", "independence_key", "counts_as_independent",
                             "correlation_group_key", "inherited_unit", "is_review_source", "candidate_id",
                             "text_kind", "source_quality", "language")
                if any(getattr(ref, f) != getattr(text, f) for f in inherited):
                    raise ValueError("an excerpt inherits its inventory text's independence and quality unchanged")
        for a in self.claim_assessments:
            owned = [hyp.get(i) for i in a.hypothesis_ids]
            if any(h is None or h.claim_id != a.claim_id for h in owned):
                raise ValueError("a claim assessment cites a hypothesis of another claim")
            copied = [(h.posture, h.existence, h.linkage) for h in owned]  # type: ignore[union-attr]
            if copied != list(zip(a.hypothesis_postures, a.hypothesis_existence, a.hypothesis_linkage)):
                raise ValueError("a claim assessment copies its hypotheses' posture, existence and linkage unchanged")
        if self.status is GapRunStatus.COMPLETED and {h.claim_id for h in self.hypotheses} - set(claims):
            raise ValueError("every hypothesis claim has an assessment")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in (GapRunStatus.COMPLETED, GapRunStatus.INSUFFICIENT_INPUT) and self.completed_at is not None

    def assessment_for(self, claim_id: str) -> ClaimGapAssessment | None:
        return next((a for a in self.claim_assessments if a.claim_id == claim_id), None)


FORBIDDEN_FIELD_FRAGMENTS: tuple[str, ...] = (
    "score",
    "probability",
    "confidence",
    "readiness",
    "novel",
    "patentab",
    "methodology",
    "experiment_valid",
    "result_valid",
    "threshold",
    "rank",
    "verdict",
    "legal_novelty",
)
"""No Phase 2J field name may contain any of these (section 17, 20)."""
