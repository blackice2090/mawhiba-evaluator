"""Claim sufficiency and evidence weighting contracts -- Phase 2E (ADR-015).

The trust progression continues where Phase 2D stopped::

    ExtractedEvidence (Phase 2C)   a verified excerpt, proven verbatim
    ClaimEvidenceAlignment (2D)    a verified claim/evidence relationship
    IndependenceGroup              one underlying logical source, canonically keyed
    EvidenceWeightProfile          one evidence item's auditable quality/contribution
    ClaimComponentSufficiency      coverage of one exact claim-component anchor
    ClaimSufficiencyAssessment     the claim-level posture under a versioned policy

Phase 2E answers exactly one question: *given all trusted aligned evidence
currently available for this claim, what is the evidence posture, and is the
available evidence sufficient under an explicit auditable policy?*

Four things this module refuses to let happen.

**Sufficiency is never one opaque number** (ADR-015). There is no
``evidence_weight: float`` anywhere here. Every judgement is a bounded enum
plus the reason codes that produced it, so "why is this claim
PARTIALLY_SUFFICIENT?" is answerable from the record alone rather than from a
scalar nobody can decompose. A scalar belongs to a later scoring phase.

**Quantity is never independence.** Corroboration is counted in
``IndependenceGroup``s keyed on canonical strong-identifier source identity
(Phase 2B's ``SourceFingerprint.logical_key``), never on titles, never per
provider observation and never per excerpt. Three providers returning one DOI
is one group; five excerpts from one abstract is one group.

**Phase 2E cannot touch a claim.** There is no ``claim_status``, no
``confidence``, no ``evidence_ids``, no ``score`` and no ``trust_gate`` field in
any type here, so the phase could not mutate canonical claim truth even if a
later edit tried to -- a stronger guarantee than leaving such a field unset
(ADR-014, ADR-015).

**Unknown stays unknown.** ``RetractionStatus.UNKNOWN`` and
``PublicationStatus.UNKNOWN`` are first-class values that are never folded into
their favorable neighbours. An unknown retraction status is not
``NOT_RETRACTED``, and an unknown publication status is not peer review.

These records live on the ``ResearchRun``, never in ``ProjectState`` -- the same
ownership boundary Phase 2C and Phase 2D established, for the same reason
(ADR-010).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, model_validator

from src.schemas.academic import AcademicSourceType
from src.schemas.claim_alignment import CLAIM_ID_PATTERN, AlignmentRelation
from src.schemas.common import (
    CANONICAL_SOURCE_ID_PATTERN,
    MawhibaModel,
    UtcDatetime,
    utc_now,
)
from src.schemas.evidence_extraction import EvidenceScope
from src.schemas.source import PeerReviewStatus, SourceIdentifierKind

CLAIM_SUFFICIENCY_CONTRACT_VERSION = "CLAIM-SUFFICIENCY-CONTRACT-V1"
"""The schema version of the records in this module."""

SUFFICIENCY_POLICY_VERSION = "SUFFICIENCY-POLICY-V1"
"""The deterministic decision policy. A semantic change requires a bump here,
never a silent threshold edit -- an archived assessment must stay readable
against the exact policy that produced it (section 28)."""

EVIDENCE_WEIGHT_PROFILE_VERSION = "EVIDENCE-WEIGHT-PROFILE-V1"
"""The per-evidence profile shape and its dimension set."""

SUFFICIENCY_AGGREGATOR_VERSION = "SUFFICIENCY-AGGREGATOR-V1"
"""The deterministic grouping/coverage computation."""

MAX_AUDIT_RATIONALE_CHARS = 600
"""Bounded, template-generated audit text. Derived from structured facts only:
no model writes it, and it is never the authoritative explanation -- the reason
codes are (section 18)."""


# ---------------------------------------------------------------------------
# Source-quality dimensions -- only what trusted metadata actually states
# ---------------------------------------------------------------------------


class RetractionStatus(StrEnum):
    """Whether the underlying work is retracted.

    ``UNKNOWN`` is not ``NOT_RETRACTED``. No provider we consume guarantees a
    retraction sweep, so silence means silence (section 19).
    """

    RETRACTED = "RETRACTED"
    NOT_RETRACTED = "NOT_RETRACTED"
    UNKNOWN = "UNKNOWN"


class PublicationStatus(StrEnum):
    """Publication/review form, read only from metadata that states it.

    Never inferred from venue prestige, title wording, provider identity or a
    URL (section 8): those correlate with quality without evidencing it.
    """

    PEER_REVIEWED_OR_FORMALLY_PUBLISHED = "PEER_REVIEWED_OR_FORMALLY_PUBLISHED"
    PREPRINT = "PREPRINT"
    OTHER_PUBLISHED = "OTHER_PUBLISHED"
    UNKNOWN = "UNKNOWN"


class TraceabilityStatus(StrEnum):
    """Whether source -> evidence -> alignment resolves inside this run.

    Anything other than ``TRACEABLE`` disqualifies the evidence from
    contributing to sufficiency. An untraceable finding cannot be audited, and
    an unauditable finding is exactly what this system exists not to assert.
    """

    TRACEABLE = "TRACEABLE"
    SOURCE_NOT_RESOLVABLE = "SOURCE_NOT_RESOLVABLE"
    EVIDENCE_NOT_IN_RUN = "EVIDENCE_NOT_IN_RUN"
    ALIGNMENT_NOT_IN_RUN = "ALIGNMENT_NOT_IN_RUN"
    CLAIM_NOT_RESOLVABLE = "CLAIM_NOT_RESOLVABLE"
    EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"


UNTRACEABLE_STATUSES: frozenset[TraceabilityStatus] = frozenset(
    s for s in TraceabilityStatus if s is not TraceabilityStatus.TRACEABLE
)


class ContentScopeLimitation(StrEnum):
    """How much of the source stands behind the evidence (section 21).

    Mirrors Phase 2C's ``EvidenceScope`` deliberately rather than reusing it:
    here it is recorded as an explicit *limitation* on what the assessment may
    claim, not as a property of the excerpt.
    """

    ABSTRACT_ONLY = "ABSTRACT_ONLY"
    PARTIAL_TEXT = "PARTIAL_TEXT"
    FULL_TEXT = "FULL_TEXT"


SCOPE_TO_LIMITATION: dict[EvidenceScope, ContentScopeLimitation] = {
    EvidenceScope.ABSTRACT_ONLY: ContentScopeLimitation.ABSTRACT_ONLY,
    EvidenceScope.PARTIAL_TEXT: ContentScopeLimitation.PARTIAL_TEXT,
    EvidenceScope.FULL_TEXT: ContentScopeLimitation.FULL_TEXT,
}


class QualityDimension(StrEnum):
    """The named dimensions a profile reports. Listed so "unknown" can be
    enumerated explicitly rather than inferred from a missing field."""

    RETRACTION = "RETRACTION"
    PUBLICATION_STATUS = "PUBLICATION_STATUS"
    TRACEABILITY = "TRACEABILITY"
    CONTENT_SCOPE = "CONTENT_SCOPE"
    PUBLICATION_YEAR = "PUBLICATION_YEAR"


class EvidenceLimitation(StrEnum):
    """An explicit caveat attached to one evidence item's contribution.

    Limitations are additive and never netted against each other: a preprint
    read only through its abstract carries both, and neither cancels out.
    """

    ABSTRACT_ONLY_SCOPE = "ABSTRACT_ONLY_SCOPE"
    PARTIAL_TEXT_SCOPE = "PARTIAL_TEXT_SCOPE"
    PREPRINT_NOT_PEER_REVIEWED = "PREPRINT_NOT_PEER_REVIEWED"
    PUBLICATION_STATUS_UNKNOWN = "PUBLICATION_STATUS_UNKNOWN"
    RETRACTION_STATUS_UNKNOWN = "RETRACTION_STATUS_UNKNOWN"
    RETRACTED_SOURCE = "RETRACTED_SOURCE"
    PUBLICATION_YEAR_UNKNOWN = "PUBLICATION_YEAR_UNKNOWN"
    SINGLE_PROVIDER_OBSERVATION = "SINGLE_PROVIDER_OBSERVATION"
    UNTRACEABLE_CHAIN = "UNTRACEABLE_CHAIN"


class SourceQualityProfile(MawhibaModel):
    """The observable quality facts about ONE logical source.

    Source-level and claim-independent by design (section 22): quality is a
    property of the paper, semantic contribution is a property of the
    claim/evidence pair, and mixing them would create a global "support weight"
    that travels between claims it was never assessed against.
    """

    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    independence_group_id: UUID
    canonical_identity: str = Field(
        min_length=1,
        description="Phase 2B ``SourceFingerprint.logical_key`` -- "
        "``KIND:normalized-identifier``. Never a title (ADR-009).",
    )
    identifier_kind: SourceIdentifierKind

    retraction_status: RetractionStatus = RetractionStatus.UNKNOWN
    publication_status: PublicationStatus = PublicationStatus.UNKNOWN
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN
    source_type: AcademicSourceType = AcademicSourceType.UNKNOWN
    publication_year: int | None = None

    provider_observation_count: int = Field(
        default=1,
        ge=1,
        description="How many providers returned this one work. Recorded for "
        "audit and deliberately NOT a corroboration multiplier: the same paper "
        "seen three times is still one study (section 9).",
    )
    unknown_dimensions: list[QualityDimension] = Field(
        default_factory=list,
        description="Dimensions this source states nothing about. Enumerated so "
        "an unknown is visible rather than absent (section 19).",
    )

    profile_version: str = EVIDENCE_WEIGHT_PROFILE_VERSION

    @property
    def is_retracted(self) -> bool:
        return self.retraction_status is RetractionStatus.RETRACTED


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------


def independence_group_id(research_run_id: UUID, canonical_identity: str) -> UUID:
    """Deterministic group id for one canonical logical source in one run.

    ``uuid5`` rather than ``uuid4``: the same inputs must produce the same group
    id on a rerun or a checkpoint resume, or idempotency could not be checked
    (section 24). Scoped by run so groups never span runs (section 23).
    """
    return uuid5(
        NAMESPACE_URL, f"sufficiency-group:{research_run_id}:{canonical_identity}"
    )


UNRESOLVED_CANONICAL_IDENTITY = "UNRESOLVED:no-canonical-source-identity"
"""Placeholder identity for a pair whose chain does not resolve.

A profile carrying it is always ``DISQUALIFIED_UNTRACEABLE``, and no
``IndependenceGroup`` is ever created for it -- so an untraceable finding stays
visible as a refusal without ever being counted as corroboration (section 8).
"""

UNRESOLVED_SOURCE_ID = "SRC-00000000-0000-5000-8000-000000000000"
UNRESOLVED_GROUP_ID = UUID("00000000-0000-5000-8000-000000000000")
"""Sentinels for an unresolvable chain: pattern-valid so the audit record can be
stored, and deliberately absent from ``ClaimSufficiencyRun.independence_groups``."""


def weight_profile_id(sufficiency_run_id: UUID, claim_id: str, evidence_id: UUID) -> UUID:
    """Deterministic profile id for one claim/evidence pair in one pass.

    ``uuid5``, not ``uuid4``: the Phase 2E pass is recomputed by several nodes
    and by any replay, and a random id would make two identical computations
    look like two different findings (section 24).
    """
    return uuid5(
        NAMESPACE_URL, f"sufficiency-profile:{sufficiency_run_id}:{claim_id}:{evidence_id}"
    )


def assessment_id_for(sufficiency_run_id: UUID, claim_id: str) -> UUID:
    """Deterministic assessment id: one claim, one pass, one assessment."""
    return uuid5(NAMESPACE_URL, f"sufficiency-assessment:{sufficiency_run_id}:{claim_id}")


class IndependenceGroup(MawhibaModel):
    """ONE underlying study/source, however many times it was observed.

    This is the unit of corroboration, and the reason ``Quantity != Independence``
    holds structurally rather than by review. Membership is decided by canonical
    strong-identifier identity only; ``member_evidence_ids`` may hold many
    excerpts and ``source_ids`` many records, and neither count is ever read as
    a number of independent studies.
    """

    independence_group_id: UUID
    research_run_id: UUID
    canonical_identity: str = Field(min_length=1)
    identifier_kind: SourceIdentifierKind
    source_ids: list[str] = Field(min_length=1)
    member_evidence_ids: list[UUID] = Field(min_length=1)
    quality: SourceQualityProfile

    @model_validator(mode="after")
    def _identity_is_deterministic(self) -> IndependenceGroup:
        expected = independence_group_id(self.research_run_id, self.canonical_identity)
        if self.independence_group_id != expected:
            raise ValueError(
                "independence_group_id must be derived from the run and the "
                "canonical identity, not minted"
            )
        if self.quality.independence_group_id != self.independence_group_id:
            raise ValueError("the quality profile belongs to a different group")
        if self.quality.canonical_identity != self.canonical_identity:
            raise ValueError("the quality profile has a different canonical identity")
        if len(set(self.member_evidence_ids)) != len(self.member_evidence_ids):
            raise ValueError("member_evidence_ids must be unique")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        return self

    @property
    def excerpt_count(self) -> int:
        """How many excerpts this one group contributed. Never a study count."""
        return len(self.member_evidence_ids)


# ---------------------------------------------------------------------------
# Contribution
# ---------------------------------------------------------------------------


class EvidenceContributionClass(StrEnum):
    """What one verified claim/evidence pair may contribute, deterministically.

    Derived from the Phase 2D relation plus source quality and provenance --
    never proposed by a model (section 15, section 16). ``CONTEXT_ONLY`` and
    ``RELEVANT_BUT_INSUFFICIENT`` are deliberately distinct from every
    ``ELIGIBLE_*`` value: neither is weak support, and neither may be counted as
    a corroborating group (section 10).
    """

    ELIGIBLE_DIRECT_SUPPORT = "ELIGIBLE_DIRECT_SUPPORT"
    ELIGIBLE_PARTIAL_SUPPORT = "ELIGIBLE_PARTIAL_SUPPORT"
    ELIGIBLE_DIRECT_CONTRADICTION = "ELIGIBLE_DIRECT_CONTRADICTION"
    ELIGIBLE_PARTIAL_CONTRADICTION = "ELIGIBLE_PARTIAL_CONTRADICTION"
    ELIGIBLE_MIXED = "ELIGIBLE_MIXED"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    RELEVANT_BUT_INSUFFICIENT = "RELEVANT_BUT_INSUFFICIENT"
    NOT_RELEVANT = "NOT_RELEVANT"
    DISQUALIFIED_RETRACTED = "DISQUALIFIED_RETRACTED"
    DISQUALIFIED_UNTRACEABLE = "DISQUALIFIED_UNTRACEABLE"


DIRECT_SUPPORT_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT}
)
DIRECT_CONTRADICTION_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION}
)
PARTIAL_SUPPORT_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {
        EvidenceContributionClass.ELIGIBLE_PARTIAL_SUPPORT,
        EvidenceContributionClass.ELIGIBLE_MIXED,
    }
)
PARTIAL_CONTRADICTION_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {
        EvidenceContributionClass.ELIGIBLE_PARTIAL_CONTRADICTION,
        EvidenceContributionClass.ELIGIBLE_MIXED,
    }
)
DISQUALIFIED_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {
        EvidenceContributionClass.DISQUALIFIED_RETRACTED,
        EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE,
    }
)
NON_DIRECT_CLASSES: frozenset[EvidenceContributionClass] = frozenset(
    {
        EvidenceContributionClass.CONTEXT_ONLY,
        EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT,
        EvidenceContributionClass.NOT_RELEVANT,
    }
)
"""Classes that never count as a corroborating group, in either direction."""

ELIGIBLE_CLASSES: frozenset[EvidenceContributionClass] = (
    DIRECT_SUPPORT_CLASSES
    | DIRECT_CONTRADICTION_CLASSES
    | PARTIAL_SUPPORT_CLASSES
    | PARTIAL_CONTRADICTION_CLASSES
)


RELATION_TO_CONTRIBUTION: dict[AlignmentRelation, EvidenceContributionClass] = {
    AlignmentRelation.SUPPORTS: EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT,
    AlignmentRelation.PARTIALLY_SUPPORTS: (
        EvidenceContributionClass.ELIGIBLE_PARTIAL_SUPPORT
    ),
    AlignmentRelation.CONTRADICTS: (
        EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION
    ),
    AlignmentRelation.PARTIALLY_CONTRADICTS: (
        EvidenceContributionClass.ELIGIBLE_PARTIAL_CONTRADICTION
    ),
    AlignmentRelation.MIXED: EvidenceContributionClass.ELIGIBLE_MIXED,
    AlignmentRelation.CONTEXT_ONLY: EvidenceContributionClass.CONTEXT_ONLY,
    AlignmentRelation.INSUFFICIENT: EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT,
    AlignmentRelation.NOT_RELEVANT: EvidenceContributionClass.NOT_RELEVANT,
}
"""The Phase 2D relation is used as given and never rewritten (section 10).
Quality then *downgrades* a class to a ``DISQUALIFIED_*`` value; nothing in
Phase 2E can upgrade one."""

DIRECT_RELATIONS: frozenset[AlignmentRelation] = frozenset(
    {AlignmentRelation.SUPPORTS, AlignmentRelation.CONTRADICTS}
)
"""Relations that assert a direct claim relationship. Used to tell "no direct
evidence exists" apart from "direct evidence exists but was disqualified"."""


class ComponentContribution(MawhibaModel):
    """What one evidence item contributes at one exact claim-component anchor."""

    anchor_start: int = Field(ge=0)
    anchor_end: int = Field(ge=1)
    anchor_text: str = Field(min_length=1)
    supports: bool = False
    contradicts: bool = False
    contextual: bool = False
    unresolved: bool = False
    direct: bool = Field(
        default=False,
        description="True only when the pair relation is itself direct "
        "(SUPPORTS/CONTRADICTS). A SUPPORTS component inside a "
        "PARTIALLY_SUPPORTS pair is partial coverage, never full (section 14).",
    )

    @model_validator(mode="after")
    def _span_holds(self) -> ComponentContribution:
        if self.anchor_end <= self.anchor_start:
            raise ValueError("anchor_end must be after anchor_start")
        if len(self.anchor_text) != self.anchor_end - self.anchor_start:
            raise ValueError("anchor text length must match the span")
        return self

    @property
    def component_key(self) -> tuple[int, int, str]:
        return (self.anchor_start, self.anchor_end, self.anchor_text)


class EvidenceWeightProfile(MawhibaModel):
    """One evidence item's auditable contribution to one claim (section 7).

    **Multi-dimensional on purpose** (ADR-015). Every dimension stays readable
    as itself: relation, contribution class, component coverage, retraction,
    publication status, traceability, scope, limitations and unknowns. There is
    no field here that combines them, because any such field would be the one
    number that hides the nine facts a reviewer needs.

    **References, never copies.** The excerpt text lives on the Phase 2C
    ``ExtractedEvidence`` and is not duplicated here (section 7): two copies of
    an excerpt are two things that can disagree.
    """

    profile_id: UUID
    research_run_id: UUID
    sufficiency_run_id: UUID

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    evidence_id: UUID
    alignment_id: UUID
    source_id: str = Field(pattern=CANONICAL_SOURCE_ID_PATTERN)
    independence_group_id: UUID
    canonical_identity: str = Field(min_length=1)

    relation: AlignmentRelation
    contribution: EvidenceContributionClass
    component_contributions: list[ComponentContribution] = Field(default_factory=list)

    retraction_status: RetractionStatus = RetractionStatus.UNKNOWN
    publication_status: PublicationStatus = PublicationStatus.UNKNOWN
    traceability: TraceabilityStatus = TraceabilityStatus.TRACEABLE
    content_scope: ContentScopeLimitation = ContentScopeLimitation.ABSTRACT_ONLY

    limitations: list[EvidenceLimitation] = Field(default_factory=list)
    unknown_dimensions: list[QualityDimension] = Field(default_factory=list)

    profile_version: str = EVIDENCE_WEIGHT_PROFILE_VERSION
    policy_version: str = SUFFICIENCY_POLICY_VERSION
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _quality_and_class_agree(self) -> EvidenceWeightProfile:
        if (
            self.retraction_status is RetractionStatus.RETRACTED
            and self.contribution not in DISQUALIFIED_CLASSES
        ):
            raise ValueError(
                "retracted evidence cannot carry a contributing class; it stays "
                "visible as DISQUALIFIED_RETRACTED (section 20)"
            )
        if (
            self.traceability in UNTRACEABLE_STATUSES
            and self.contribution is not EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
        ):
            raise ValueError(
                "untraceable evidence cannot contribute to sufficiency (section 8)"
            )
        keys = [c.component_key for c in self.component_contributions]
        if len(set(keys)) != len(keys):
            raise ValueError("a component anchor appears twice in one profile")
        return self

    @property
    def is_eligible(self) -> bool:
        return self.contribution in ELIGIBLE_CLASSES


# ---------------------------------------------------------------------------
# Component coverage
# ---------------------------------------------------------------------------


class ComponentCoverage(StrEnum):
    """Coverage of one material claim component, from independent groups.

    ``CONTESTED`` is a terminal state for a component, never a midpoint between
    supported and contradicted: averaging a real disagreement away is precisely
    the failure this taxonomy prevents (section 12).
    """

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    CONTESTED = "CONTESTED"
    PARTIAL_SUPPORT_ONLY = "PARTIAL_SUPPORT_ONLY"
    PARTIAL_CONTRADICTION_ONLY = "PARTIAL_CONTRADICTION_ONLY"
    PARTIAL_MIXED = "PARTIAL_MIXED"
    UNRESOLVED_RELEVANT = "UNRESOLVED_RELEVANT"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    NO_EVIDENCE = "NO_EVIDENCE"
    BLOCKED_SOURCE_QUALITY = "BLOCKED_SOURCE_QUALITY"


ADEQUATELY_EVIDENCED_COVERAGE: frozenset[ComponentCoverage] = frozenset(
    {ComponentCoverage.SUPPORTED, ComponentCoverage.CONTRADICTED}
)
"""Coverage states the policy accepts as adequate for one component. Partial,
contextual and unresolved states are deliberately absent."""


class CorroborationLevel(StrEnum):
    """How many *independent groups* back a component, as a bounded label.

    Reported rather than scored: ``SINGLE_GROUP`` is a materially different
    epistemic situation from ``MULTIPLE_GROUPS`` and the distinction must survive
    into the report instead of being summed away (section 13).
    """

    NONE = "NONE"
    SINGLE_GROUP = "SINGLE_GROUP"
    MULTIPLE_GROUPS = "MULTIPLE_GROUPS"


class SufficiencyReasonCode(StrEnum):
    """The authoritative, finite explanation vocabulary (section 18).

    Structured reason codes rather than free text, because a report has to be
    able to say *why* mechanically -- and because free-form rationale invites a
    model to explain a judgement it did not make.
    """

    FULL_COMPONENT_COVERAGE = "FULL_COMPONENT_COVERAGE"
    PARTIAL_COMPONENT_COVERAGE = "PARTIAL_COMPONENT_COVERAGE"
    NO_COMPONENT_COVERAGE = "NO_COMPONENT_COVERAGE"
    SINGLE_INDEPENDENT_SOURCE_ONLY = "SINGLE_INDEPENDENT_SOURCE_ONLY"
    MULTIPLE_INDEPENDENT_SUPPORTING_SOURCES = "MULTIPLE_INDEPENDENT_SUPPORTING_SOURCES"
    MULTIPLE_INDEPENDENT_CONTRADICTING_SOURCES = (
        "MULTIPLE_INDEPENDENT_CONTRADICTING_SOURCES"
    )
    MATERIAL_CONTRADICTION_PRESENT = "MATERIAL_CONTRADICTION_PRESENT"
    SUPPORT_AND_CONTRADICTION_PRESENT = "SUPPORT_AND_CONTRADICTION_PRESENT"
    PARTIAL_SUPPORT_ONLY = "PARTIAL_SUPPORT_ONLY"
    PARTIAL_CONTRADICTION_ONLY = "PARTIAL_CONTRADICTION_ONLY"
    RETRACTED_SOURCE_EXCLUDED = "RETRACTED_SOURCE_EXCLUDED"
    PREPRINT_LIMITATION = "PREPRINT_LIMITATION"
    ABSTRACT_ONLY_SCOPE = "ABSTRACT_ONLY_SCOPE"
    TRACEABILITY_FAILURE = "TRACEABILITY_FAILURE"
    NO_DIRECT_ALIGNMENT = "NO_DIRECT_ALIGNMENT"
    CONTEXT_ONLY_AVAILABLE = "CONTEXT_ONLY_AVAILABLE"
    RELEVANT_BUT_INSUFFICIENT = "RELEVANT_BUT_INSUFFICIENT"
    NOT_RELEVANT_ONLY = "NOT_RELEVANT_ONLY"
    INDEPENDENCE_COLLAPSED_DUPLICATES = "INDEPENDENCE_COLLAPSED_DUPLICATES"
    UNKNOWN_PUBLICATION_STATUS = "UNKNOWN_PUBLICATION_STATUS"
    UNKNOWN_RETRACTION_STATUS = "UNKNOWN_RETRACTION_STATUS"
    ALL_DIRECT_EVIDENCE_DISQUALIFIED = "ALL_DIRECT_EVIDENCE_DISQUALIFIED"
    INCOMPLETE_ALIGNMENT_UNIVERSE = "INCOMPLETE_ALIGNMENT_UNIVERSE"


class SufficiencyBlocker(StrEnum):
    """A condition that prevents a normal sufficiency posture.

    A blocker is recorded, never applied silently: "all direct evidence for this
    claim is retracted" must read differently from "no evidence was found".
    """

    ALL_DIRECT_EVIDENCE_RETRACTED = "ALL_DIRECT_EVIDENCE_RETRACTED"
    ALL_DIRECT_EVIDENCE_UNTRACEABLE = "ALL_DIRECT_EVIDENCE_UNTRACEABLE"
    ALL_DIRECT_EVIDENCE_DISQUALIFIED = "ALL_DIRECT_EVIDENCE_DISQUALIFIED"
    INCOMPLETE_ALIGNMENT_UNIVERSE = "INCOMPLETE_ALIGNMENT_UNIVERSE"


class ClaimComponentSufficiency(MawhibaModel):
    """Coverage of ONE material claim component, by independent group.

    The anchor is the exact Phase 2D span (``claim.claim[start:end] ==
    anchor_text``), carried unchanged. Support for one component is never read
    as support for the compound claim (section 11).
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    anchor_start: int = Field(ge=0)
    anchor_end: int = Field(ge=1)
    anchor_text: str = Field(min_length=1)

    coverage: ComponentCoverage
    corroboration: CorroborationLevel = CorroborationLevel.NONE

    supporting_group_ids: list[UUID] = Field(default_factory=list)
    contradicting_group_ids: list[UUID] = Field(default_factory=list)
    partial_supporting_group_ids: list[UUID] = Field(default_factory=list)
    partial_contradicting_group_ids: list[UUID] = Field(default_factory=list)
    contextual_group_ids: list[UUID] = Field(default_factory=list)
    unresolved_group_ids: list[UUID] = Field(default_factory=list)
    disqualified_group_ids: list[UUID] = Field(default_factory=list)

    reason_codes: list[SufficiencyReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _span_and_counts_hold(self) -> ClaimComponentSufficiency:
        if self.anchor_end <= self.anchor_start:
            raise ValueError("anchor_end must be after anchor_start")
        if len(self.anchor_text) != self.anchor_end - self.anchor_start:
            raise ValueError("anchor text length must match the span")
        for name in (
            "supporting_group_ids",
            "contradicting_group_ids",
            "partial_supporting_group_ids",
            "partial_contradicting_group_ids",
            "contextual_group_ids",
            "unresolved_group_ids",
            "disqualified_group_ids",
        ):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must hold distinct independence groups")
        expected = {
            0: CorroborationLevel.NONE,
            1: CorroborationLevel.SINGLE_GROUP,
        }.get(
            len(self.supporting_group_ids) or len(self.contradicting_group_ids),
            CorroborationLevel.MULTIPLE_GROUPS,
        )
        if self.coverage in ADEQUATELY_EVIDENCED_COVERAGE and self.corroboration is not expected:
            raise ValueError(
                "corroboration level must match the number of independent "
                "direct groups"
            )
        return self

    @property
    def component_key(self) -> tuple[int, int, str]:
        return (self.anchor_start, self.anchor_end, self.anchor_text)

    @property
    def is_adequately_evidenced(self) -> bool:
        return self.coverage in ADEQUATELY_EVIDENCED_COVERAGE


# ---------------------------------------------------------------------------
# Claim-level assessment
# ---------------------------------------------------------------------------


class SufficiencyOutcome(StrEnum):
    """The claim-level evidence posture under the versioned policy (section 12).

    Every value is deliberately distinct, and none of them is a claim status, a
    score or a trust verdict. ``SUFFICIENT_SUPPORT`` means *this policy's bar for
    adequate independent positive coverage was met by currently available
    trusted evidence* -- it is not universal scientific proof, and it does not
    change ``ClaimRecord.status`` (ADR-014, ADR-015).
    """

    SUFFICIENT_SUPPORT = "SUFFICIENT_SUPPORT"
    SUFFICIENT_CONTRADICTION = "SUFFICIENT_CONTRADICTION"
    CONTESTED = "CONTESTED"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_DIRECT_EVIDENCE = "NO_DIRECT_EVIDENCE"
    BLOCKED_SOURCE_QUALITY = "BLOCKED_SOURCE_QUALITY"


class ClaimSufficiencyAssessment(MawhibaModel):
    """The Phase 2E verdict for ONE claim, with everything that produced it.

    **Not a claim mutation.** This record sits beside the claim and references
    it by id. It has no status, confidence, evidence-reference, score or
    trust-gate field, so promoting it into canonical claim truth is a later
    reviewed phase and cannot happen by accident here (ADR-015).

    **Counts are group counts.** ``supporting_group_count`` counts independence
    groups, never evidence items, never provider observations and never
    excerpts. ``profile_count`` is the evidence-item count and is reported
    separately precisely so the two can never be confused.
    """

    assessment_id: UUID
    research_run_id: UUID
    sufficiency_run_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)

    outcome: SufficiencyOutcome
    components: list[ClaimComponentSufficiency] = Field(default_factory=list)
    profile_ids: list[UUID] = Field(default_factory=list)

    independence_group_ids: list[UUID] = Field(default_factory=list)
    supporting_group_ids: list[UUID] = Field(default_factory=list)
    contradicting_group_ids: list[UUID] = Field(default_factory=list)
    contextual_group_ids: list[UUID] = Field(default_factory=list)
    insufficient_group_ids: list[UUID] = Field(default_factory=list)
    disqualified_group_ids: list[UUID] = Field(default_factory=list)

    blockers: list[SufficiencyBlocker] = Field(default_factory=list)
    reason_codes: list[SufficiencyReasonCode] = Field(default_factory=list)
    unknown_dimensions: list[QualityDimension] = Field(default_factory=list)
    limitations: list[EvidenceLimitation] = Field(default_factory=list)
    content_scope_ceiling: ContentScopeLimitation | None = Field(
        default=None,
        description="The strongest content scope any contributing evidence had. "
        "``None`` when nothing contributed -- never silently FULL_TEXT.",
    )

    audit_rationale: str = Field(
        default="",
        max_length=MAX_AUDIT_RATIONALE_CHARS,
        description="Template text derived from the structured facts above. "
        "Convenience for a reader; the reason codes are authoritative.",
    )

    contract_version: str = CLAIM_SUFFICIENCY_CONTRACT_VERSION
    policy_version: str = SUFFICIENCY_POLICY_VERSION
    profile_version: str = EVIDENCE_WEIGHT_PROFILE_VERSION
    aggregator_version: str = SUFFICIENCY_AGGREGATOR_VERSION
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _consistent(self) -> ClaimSufficiencyAssessment:
        if any(c.claim_id != self.claim_id for c in self.components):
            raise ValueError("a component sufficiency belongs to a different claim")
        keys = [c.component_key for c in self.components]
        if len(set(keys)) != len(keys):
            raise ValueError("a component anchor appears twice in one assessment")

        groups = set(self.independence_group_ids)
        for name in (
            "supporting_group_ids",
            "contradicting_group_ids",
            "contextual_group_ids",
            "insufficient_group_ids",
            "disqualified_group_ids",
        ):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must hold distinct independence groups")
            if not set(values) <= groups:
                raise ValueError(
                    f"{name} references a group missing from independence_group_ids"
                )

        # An outcome must not outrun its component evidence.
        if self.outcome is SufficiencyOutcome.SUFFICIENT_SUPPORT:
            if not self.components or not all(
                c.coverage is ComponentCoverage.SUPPORTED for c in self.components
            ):
                raise ValueError(
                    "SUFFICIENT_SUPPORT requires every material component to be "
                    "SUPPORTED (section 11)"
                )
            if not self.supporting_group_ids:
                raise ValueError(
                    "SUFFICIENT_SUPPORT requires at least one eligible supporting "
                    "independence group"
                )
        if self.outcome is SufficiencyOutcome.SUFFICIENT_CONTRADICTION:
            if not self.components or not all(
                c.coverage is ComponentCoverage.CONTRADICTED for c in self.components
            ):
                raise ValueError(
                    "SUFFICIENT_CONTRADICTION requires every material component to "
                    "be CONTRADICTED"
                )
            if not self.contradicting_group_ids:
                raise ValueError(
                    "SUFFICIENT_CONTRADICTION requires at least one eligible "
                    "contradicting independence group"
                )
        if self.outcome is SufficiencyOutcome.CONTESTED and not (
            self.supporting_group_ids and self.contradicting_group_ids
        ):
            raise ValueError(
                "CONTESTED requires both supporting and contradicting independent "
                "groups; a conflict is never inferred from one side"
            )
        if self.outcome is SufficiencyOutcome.BLOCKED_SOURCE_QUALITY and not self.blockers:
            raise ValueError("BLOCKED_SOURCE_QUALITY must state its blocker")
        if self.outcome is SufficiencyOutcome.NO_DIRECT_EVIDENCE and (
            self.supporting_group_ids or self.contradicting_group_ids
        ):
            raise ValueError(
                "NO_DIRECT_EVIDENCE cannot carry direct supporting or "
                "contradicting groups"
            )
        return self

    @property
    def profile_count(self) -> int:
        """Evidence items considered. Never an independent-source count."""
        return len(self.profile_ids)

    @property
    def supporting_group_count(self) -> int:
        return len(self.supporting_group_ids)

    @property
    def contradicting_group_count(self) -> int:
        return len(self.contradicting_group_ids)

    @property
    def independence_group_count(self) -> int:
        return len(self.independence_group_ids)

    @property
    def is_abstract_only(self) -> bool:
        return self.content_scope_ceiling is ContentScopeLimitation.ABSTRACT_ONLY


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class ClaimSufficiencyStatus(StrEnum):
    """Execution state of one sufficiency pass.

    The not-ready values are outcomes, not crashes (section 27), and they are
    kept distinct so "Phase 2D never ran" cannot be reported as "no evidence
    supports this project".
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_ASSESSABLE_CLAIMS = "NO_ASSESSABLE_CLAIMS"
    NO_ACCEPTED_EVIDENCE = "NO_ACCEPTED_EVIDENCE"
    NO_VERIFIED_ALIGNMENTS = "NO_VERIFIED_ALIGNMENTS"
    BLOCKED_ALIGNMENT_INCOMPLETE = "BLOCKED_ALIGNMENT_INCOMPLETE"
    NOT_READY = "NOT_READY"


TERMINAL_SUFFICIENCY_STATUSES: frozenset[ClaimSufficiencyStatus] = frozenset(
    {
        ClaimSufficiencyStatus.COMPLETED,
        ClaimSufficiencyStatus.FAILED,
        ClaimSufficiencyStatus.NO_ASSESSABLE_CLAIMS,
        ClaimSufficiencyStatus.NO_ACCEPTED_EVIDENCE,
        ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS,
        ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE,
        ClaimSufficiencyStatus.NOT_READY,
    }
)


class SufficiencyIssueCode(StrEnum):
    NO_CLAIMS = "NO_CLAIMS"
    NO_ACCEPTED_EVIDENCE = "NO_ACCEPTED_EVIDENCE"
    NO_VERIFIED_ALIGNMENTS = "NO_VERIFIED_ALIGNMENTS"
    ALIGNMENT_NOT_READY = "ALIGNMENT_NOT_READY"
    ALIGNMENT_INCOMPLETE = "ALIGNMENT_INCOMPLETE"
    ALIGNMENT_PAIR_LIMIT_BLOCKED = "ALIGNMENT_PAIR_LIMIT_BLOCKED"
    EVIDENCE_EXTRACTION_NOT_READY = "EVIDENCE_EXTRACTION_NOT_READY"
    ACADEMIC_SOURCES_UNAVAILABLE = "ACADEMIC_SOURCES_UNAVAILABLE"
    UNTRACEABLE_EVIDENCE_EXCLUDED = "UNTRACEABLE_EVIDENCE_EXCLUDED"
    CROSS_RUN_REFERENCE_EXCLUDED = "CROSS_RUN_REFERENCE_EXCLUDED"


class SufficiencyIssue(MawhibaModel):
    code: SufficiencyIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1)
    claim_id: str | None = None


class SufficiencyCoverage(MawhibaModel):
    """Operational counters for the pass.

    ``independence_groups_total`` and ``evidence_items_total`` are both here on
    purpose: their difference is the duplicate collapse this phase performs, and
    a reader must be able to see it.
    """

    claims_total: int = Field(default=0, ge=0)
    claims_assessed: int = Field(default=0, ge=0)
    accepted_evidence_total: int = Field(default=0, ge=0)
    verified_alignments_total: int = Field(default=0, ge=0)
    evidence_items_total: int = Field(default=0, ge=0)
    independence_groups_total: int = Field(default=0, ge=0)
    duplicate_evidence_collapsed: int = Field(
        default=0,
        ge=0,
        description="Evidence items beyond the first in their group. Exactly the "
        "corroboration inflation that did NOT happen.",
    )
    profiles_total: int = Field(default=0, ge=0)
    disqualified_profiles_total: int = Field(default=0, ge=0)
    retracted_profiles_total: int = Field(default=0, ge=0)
    untraceable_profiles_total: int = Field(default=0, ge=0)
    preprint_profiles_total: int = Field(default=0, ge=0)
    abstract_only_profiles_total: int = Field(default=0, ge=0)
    unknown_retraction_profiles_total: int = Field(default=0, ge=0)
    unknown_publication_profiles_total: int = Field(default=0, ge=0)
    outcome_counts: dict[str, int] = Field(default_factory=dict)
    contribution_counts: dict[str, int] = Field(default_factory=dict)


class ClaimSufficiencyRun(MawhibaModel):
    """Everything one claim-sufficiency pass produced.

    Lives on the ``ResearchRun`` (section 4), never in ``ProjectState``: the
    ownership boundary Phase 2C and 2D established, for the same reason. This is
    research-evaluation truth -- an auditable analytical artifact -- not
    canonical project truth.

    **Fully deterministic, by design** (section 16). There is no model provider,
    no prompt version and no classifier version on this run, because Phase 2E
    makes no model call: every judgement here follows from Phase 2D's structured
    output plus trusted metadata, and adding an LLM would add a trust boundary
    with nothing to decide behind it.
    """

    sufficiency_run_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    alignment_run_id: UUID | None = None
    status: ClaimSufficiencyStatus = ClaimSufficiencyStatus.NOT_STARTED

    contract_version: str = CLAIM_SUFFICIENCY_CONTRACT_VERSION
    policy_version: str = SUFFICIENCY_POLICY_VERSION
    profile_version: str = EVIDENCE_WEIGHT_PROFILE_VERSION
    aggregator_version: str = SUFFICIENCY_AGGREGATOR_VERSION
    dataset_version: str | None = None

    alignment_universe_complete: bool = Field(
        default=True,
        description="False when Phase 2D did not classify every required pair. "
        "Sufficiency is never asserted over an incomplete universe (section 27).",
    )

    independence_groups: list[IndependenceGroup] = Field(default_factory=list)
    weight_profiles: list[EvidenceWeightProfile] = Field(default_factory=list)
    assessments: list[ClaimSufficiencyAssessment] = Field(default_factory=list)
    coverage: SufficiencyCoverage = Field(default_factory=SufficiencyCoverage)
    errors: list[SufficiencyIssue] = Field(default_factory=list)

    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ClaimSufficiencyRun:
        for group in self.independence_groups:
            if group.research_run_id != self.research_run_id:
                raise ValueError("an independence group belongs to a different run")
        group_ids = [g.independence_group_id for g in self.independence_groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("independence group ids must be unique")
        known_groups = set(group_ids)

        profile_ids = [p.profile_id for p in self.weight_profiles]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("weight profile ids must be unique")
        for profile in self.weight_profiles:
            if profile.research_run_id != self.research_run_id:
                raise ValueError("a weight profile belongs to a different research run")
            if profile.sufficiency_run_id != self.sufficiency_run_id:
                raise ValueError("a weight profile belongs to a different sufficiency run")
            if profile.independence_group_id not in known_groups:
                # The one permitted exception: an untraceable pair keeps an
                # audit profile but has no group, precisely so it cannot be
                # counted as an independent source.
                if profile.independence_group_id != UNRESOLVED_GROUP_ID or (
                    profile.contribution
                    is not EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
                ):
                    raise ValueError(
                        f"profile {profile.profile_id} references unknown "
                        f"independence group {profile.independence_group_id}"
                    )
        # One claim/evidence pair yields exactly one profile (section 24).
        pair_keys = [(p.claim_id, p.evidence_id) for p in self.weight_profiles]
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError(
                "a claim/evidence pair cannot carry two weight profiles; a rerun "
                "must not duplicate them"
            )

        known_profiles = set(profile_ids)
        claim_ids = [a.claim_id for a in self.assessments]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError(
                "a claim cannot carry two sufficiency assessments in one run "
                "(section 24)"
            )
        for assessment in self.assessments:
            if assessment.research_run_id != self.research_run_id:
                raise ValueError("an assessment belongs to a different research run")
            if assessment.sufficiency_run_id != self.sufficiency_run_id:
                raise ValueError("an assessment belongs to a different sufficiency run")
            if not set(assessment.profile_ids) <= known_profiles:
                raise ValueError(
                    f"assessment for {assessment.claim_id} references an unknown "
                    "weight profile"
                )
            if not set(assessment.independence_group_ids) <= known_groups:
                raise ValueError(
                    f"assessment for {assessment.claim_id} references an unknown "
                    "independence group"
                )
            if not self.alignment_universe_complete and assessment.outcome in (
                SufficiencyOutcome.SUFFICIENT_SUPPORT,
                SufficiencyOutcome.SUFFICIENT_CONTRADICTION,
            ):
                raise ValueError(
                    "sufficiency cannot be asserted over an incomplete alignment "
                    "universe (section 27)"
                )

        if self.status is ClaimSufficiencyStatus.NOT_STARTED and (
            self.independence_groups or self.weight_profiles or self.assessments
        ):
            raise ValueError(
                "NOT_STARTED must not carry groups, profiles or assessments"
            )
        if (
            self.status is ClaimSufficiencyStatus.BLOCKED_ALIGNMENT_INCOMPLETE
            and self.assessments
        ):
            raise ValueError(
                "BLOCKED_ALIGNMENT_INCOMPLETE cannot carry assessments"
            )
        if self.status in (
            ClaimSufficiencyStatus.NO_ASSESSABLE_CLAIMS,
            ClaimSufficiencyStatus.NO_ACCEPTED_EVIDENCE,
            ClaimSufficiencyStatus.NO_VERIFIED_ALIGNMENTS,
            ClaimSufficiencyStatus.NOT_READY,
        ) and self.assessments:
            raise ValueError(f"{self.status.value} cannot carry assessments")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_SUFFICIENCY_STATUSES

    def assessment_for(self, claim_id: str) -> ClaimSufficiencyAssessment | None:
        return next((a for a in self.assessments if a.claim_id == claim_id), None)

    def profiles_for(self, claim_id: str) -> list[EvidenceWeightProfile]:
        return [p for p in self.weight_profiles if p.claim_id == claim_id]

    def group(self, group_id: UUID) -> IndependenceGroup | None:
        return next(
            (g for g in self.independence_groups if g.independence_group_id == group_id),
            None,
        )


__all__ = [
    "ADEQUATELY_EVIDENCED_COVERAGE",
    "CLAIM_SUFFICIENCY_CONTRACT_VERSION",
    "DIRECT_CONTRADICTION_CLASSES",
    "DIRECT_RELATIONS",
    "DIRECT_SUPPORT_CLASSES",
    "DISQUALIFIED_CLASSES",
    "ELIGIBLE_CLASSES",
    "EVIDENCE_WEIGHT_PROFILE_VERSION",
    "MAX_AUDIT_RATIONALE_CHARS",
    "NON_DIRECT_CLASSES",
    "PARTIAL_CONTRADICTION_CLASSES",
    "PARTIAL_SUPPORT_CLASSES",
    "RELATION_TO_CONTRIBUTION",
    "SCOPE_TO_LIMITATION",
    "SUFFICIENCY_AGGREGATOR_VERSION",
    "SUFFICIENCY_POLICY_VERSION",
    "TERMINAL_SUFFICIENCY_STATUSES",
    "UNRESOLVED_CANONICAL_IDENTITY",
    "UNRESOLVED_GROUP_ID",
    "UNRESOLVED_SOURCE_ID",
    "UNTRACEABLE_STATUSES",
    "ClaimComponentSufficiency",
    "ClaimSufficiencyAssessment",
    "ClaimSufficiencyRun",
    "ClaimSufficiencyStatus",
    "ComponentContribution",
    "ComponentCoverage",
    "ContentScopeLimitation",
    "CorroborationLevel",
    "EvidenceContributionClass",
    "EvidenceLimitation",
    "EvidenceWeightProfile",
    "IndependenceGroup",
    "PublicationStatus",
    "QualityDimension",
    "RetractionStatus",
    "SourceQualityProfile",
    "SufficiencyBlocker",
    "SufficiencyCoverage",
    "SufficiencyIssue",
    "SufficiencyIssueCode",
    "SufficiencyOutcome",
    "SufficiencyReasonCode",
    "TraceabilityStatus",
    "assessment_id_for",
    "independence_group_id",
    "weight_profile_id",
]
