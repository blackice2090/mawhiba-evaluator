"""Claim-Evidence Alignment contracts -- Phase 2D (ADR-014).

The trust progression continues where Phase 2C stopped:

    ExtractedEvidence (Phase 2C)  a verified excerpt, proven to exist verbatim
    Existing ClaimRecord          a student assertion already in ProjectState
    AlignmentCandidate            what a model proposed. UNTRUSTED
    === deterministic verification boundary ===
    ClaimEvidenceAlignment        a structurally and provenance-verified relation

Phase 2D answers one narrow question: what semantic relationship does this
specific verified evidence item have to this specific existing claim? It does
NOT decide whether the claim is proven, and it cannot mutate the claim, its
status, its confidence, its evidence_ids or counter_evidence_ids -- those
fields do not appear anywhere in this module (ADR-014).

**Structured is not true.** A verified alignment record means the candidate
passed provenance and taxonomy-consistency checks. It never means the model's
semantic judgement is scientifically correct; nothing here can prove that.

**Anchors are exact, not fuzzy.** A claim-component anchor is trusted only when
``claim.claim[start:end] == anchor_text`` character-for-character. No
punctuation, digit, unit, negation or whitespace normalization is applied.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime, utc_now
from src.schemas.evidence_extraction import SHA256_PATTERN

CLAIM_ALIGNMENT_CONTRACT_VERSION = "CLAIM-ALIGNMENT-CONTRACT-V1"
ALIGNMENT_CLASSIFIER_VERSION = "ALIGNMENT-CLASSIFIER-V1"
ALIGNMENT_VERIFIER_VERSION = "ALIGNMENT-VERIFIER-V1"

CLAIM_ID_PATTERN = r"^C-\d{3,}$"

MAX_RATIONALE_CHARS = 400
"""A model rationale is bounded advisory text, never a scientific argument."""


# ---------------------------------------------------------------------------
# Relation taxonomy
# ---------------------------------------------------------------------------


class AlignmentRelation(StrEnum):
    """The pair-level semantic relationship between one claim and one evidence
    item. See module docstring: this is a classification, never a verdict on
    whether the claim is proven (ADR-014)."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    PARTIALLY_CONTRADICTS = "PARTIALLY_CONTRADICTS"
    MIXED = "MIXED"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_RELEVANT = "NOT_RELEVANT"


class ComponentJudgment(StrEnum):
    """The local relationship at one claim-component anchor."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    UNRESOLVED = "UNRESOLVED"
    CONTEXTUAL = "CONTEXTUAL"


class AlignmentReasonCode(StrEnum):
    """Finite, machine-readable explanation vocabulary (section 10).

    A short model rationale may supplement these, but the reason codes are the
    primary machine-readable explanation. Free-form text is never authoritative.
    """

    DIRECT_SUPPORT = "DIRECT_SUPPORT"
    DIRECT_CONTRADICTION = "DIRECT_CONTRADICTION"
    NEGATION_CONFLICT = "NEGATION_CONFLICT"
    NUMERIC_CONFLICT = "NUMERIC_CONFLICT"
    BASELINE_MISMATCH = "BASELINE_MISMATCH"
    METRIC_MISMATCH = "METRIC_MISMATCH"
    POPULATION_SCOPE_MISMATCH = "POPULATION_SCOPE_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
    CAUSAL_OVERREACH = "CAUSAL_OVERREACH"
    MODALITY_STRENGTH_MISMATCH = "MODALITY_STRENGTH_MISMATCH"
    BACKGROUND_CONTEXT_ONLY = "BACKGROUND_CONTEXT_ONLY"
    INSUFFICIENT_DETAIL = "INSUFFICIENT_DETAIL"
    NO_MATERIAL_RELATIONSHIP = "NO_MATERIAL_RELATIONSHIP"
    OTHER = "OTHER"


def _component_summary(
    components: list["ComponentAlignmentJudgment"],
) -> tuple[bool, bool, bool, bool]:
    """(has_support, has_contradiction, has_context, has_unresolved)."""
    has_support = any(c.judgment is ComponentJudgment.SUPPORTS for c in components)
    has_contradiction = any(
        c.judgment is ComponentJudgment.CONTRADICTS for c in components
    )
    has_context = any(c.judgment is ComponentJudgment.CONTEXTUAL for c in components)
    has_unresolved = any(
        c.judgment is ComponentJudgment.UNRESOLVED for c in components
    )
    return has_support, has_contradiction, has_context, has_unresolved


def relation_is_consistent(
    relation: AlignmentRelation, components: list["ComponentAlignmentJudgment"]
) -> bool:
    """The deterministic pair/component consistency rule (section 7).

    This proves structural consistency only. It never proves that the
    underlying semantic judgement is scientifically correct (section 13).
    """
    has_support, has_contradiction, has_context, has_unresolved = _component_summary(
        components
    )
    pure_support = has_support and not has_contradiction and not has_context and not has_unresolved
    pure_contradiction = (
        has_contradiction and not has_support and not has_context and not has_unresolved
    )
    partial_support = has_support and not has_contradiction and (has_context or has_unresolved)
    partial_contradiction = (
        has_contradiction and not has_support and (has_context or has_unresolved)
    )
    mixed = has_support and has_contradiction
    pure_context = has_context and not has_support and not has_contradiction and not has_unresolved
    pure_insufficient = (
        has_unresolved and not has_support and not has_contradiction and not has_context
    )
    not_relevant = not components

    return {
        AlignmentRelation.SUPPORTS: pure_support,
        AlignmentRelation.CONTRADICTS: pure_contradiction,
        AlignmentRelation.PARTIALLY_SUPPORTS: partial_support,
        AlignmentRelation.PARTIALLY_CONTRADICTS: partial_contradiction,
        AlignmentRelation.MIXED: mixed,
        AlignmentRelation.CONTEXT_ONLY: pure_context,
        AlignmentRelation.INSUFFICIENT: pure_insufficient,
        AlignmentRelation.NOT_RELEVANT: not_relevant,
    }[relation]


# ---------------------------------------------------------------------------
# Claim component anchors
# ---------------------------------------------------------------------------


class ClaimComponentAnchor(MawhibaModel):
    """An exact span into the existing claim's own text.

    Trust holds only when ``claim.claim[start:end] == text`` character for
    character, checked by code in ``src.research.alignment.verification`` --
    never trusted from the model (section 6).
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _span_holds(self) -> ClaimComponentAnchor:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if len(self.text) != self.end - self.start:
            raise ValueError("anchor text length must match the span")
        return self


class ComponentAlignmentJudgment(MawhibaModel):
    """One local judgement at one claim-component anchor."""

    anchor: ClaimComponentAnchor
    judgment: ComponentJudgment
    reason_codes: list[AlignmentReasonCode] = Field(min_length=1)
    rationale: str | None = Field(default=None, max_length=MAX_RATIONALE_CHARS)


# ---------------------------------------------------------------------------
# Candidates -- untrusted
# ---------------------------------------------------------------------------


class CandidateComponentAnchor(MawhibaModel):
    """A proposed claim-component anchor. Untrusted until verified."""

    claimed_text: str = Field(min_length=1)
    claimed_start: int | None = Field(default=None, ge=0)
    claimed_end: int | None = Field(default=None, ge=0)
    judgment: ComponentJudgment
    reason_codes: list[AlignmentReasonCode] = Field(default_factory=list)
    rationale: str | None = Field(default=None, max_length=MAX_RATIONALE_CHARS)


class AlignmentCandidate(MawhibaModel):
    """What a model proposed for one claim/evidence pair. Untrusted (section 8)."""

    candidate_id: UUID = Field(default_factory=uuid4)
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    evidence_id: UUID
    relation: AlignmentRelation
    components: list[CandidateComponentAnchor] = Field(default_factory=list)
    rationale: str | None = Field(default=None, max_length=MAX_RATIONALE_CHARS)
    classifier_version: str = ALIGNMENT_CLASSIFIER_VERSION
    model_name: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)


class AlignmentRejectionReason(StrEnum):
    """Why a candidate did not become a verified alignment. Stable, auditable."""

    UNKNOWN_CLAIM = "UNKNOWN_CLAIM"
    UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"
    EVIDENCE_OUTSIDE_RUN = "EVIDENCE_OUTSIDE_RUN"
    EVIDENCE_NOT_ACCEPTED = "EVIDENCE_NOT_ACCEPTED"
    EVIDENCE_PROVENANCE_INVALID = "EVIDENCE_PROVENANCE_INVALID"
    FABRICATED_ANCHOR = "FABRICATED_ANCHOR"
    ANCHOR_OUT_OF_RANGE = "ANCHOR_OUT_OF_RANGE"
    ANCHOR_TEXT_MISMATCH = "ANCHOR_TEXT_MISMATCH"
    INVALID_RELATION = "INVALID_RELATION"
    STRUCTURALLY_INCONSISTENT = "STRUCTURALLY_INCONSISTENT"
    DUPLICATE_INCOMPATIBLE_PAIR = "DUPLICATE_INCOMPATIBLE_PAIR"
    METADATA_ONLY_EVIDENCE = "METADATA_ONLY_EVIDENCE"
    PROVIDER_SYNTHESIS_EVIDENCE = "PROVIDER_SYNTHESIS_EVIDENCE"
    CROSS_RUN_REFERENCE = "CROSS_RUN_REFERENCE"
    MODEL_SCHEMA_ERROR = "MODEL_SCHEMA_ERROR"
    NO_COMPONENTS = "NO_COMPONENTS"
    OTHER = "OTHER"


MAX_REJECTION_SUMMARY_CHARS = 200


class RejectedAlignmentCandidate(MawhibaModel):
    """Audit record for a refused candidate. Carries no secrets, no excerpts."""

    candidate_id: UUID
    claim_id: str | None = None
    evidence_id: UUID | None = None
    reason: AlignmentRejectionReason
    safe_summary: str = Field(default="", max_length=MAX_REJECTION_SUMMARY_CHARS)
    verifier_version: str = ALIGNMENT_VERIFIER_VERSION


# ---------------------------------------------------------------------------
# Verified alignment
# ---------------------------------------------------------------------------


class ClaimEvidenceAlignment(MawhibaModel):
    """A verified claim/evidence relationship. References, never duplicates.

    **What this record means**: this verified evidence item has been classified
    as having this semantic relationship to this existing claim, and the
    relationship passed deterministic structural/provenance verification.

    **What it does NOT mean**: the claim is verified, supported, or sufficiently
    proven. It carries no claim status, no confidence delta and no evidence_ids
    mutation -- those fields do not exist here (ADR-014).
    """

    alignment_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    alignment_run_id: UUID

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    evidence_id: UUID
    evidence_content_hash: str = Field(pattern=SHA256_PATTERN)

    relation: AlignmentRelation
    components: list[ComponentAlignmentJudgment] = Field(
        default_factory=list,
        description="Empty only for NOT_RELEVANT, where no material component "
        "was identified (section 12 mapping).",
    )
    rationale: str | None = Field(
        default=None,
        max_length=MAX_RATIONALE_CHARS,
        description="Bounded, explicitly non-evidentiary model explanation. "
        "Never itself becomes scientific evidence (section 9).",
    )

    contract_version: str = CLAIM_ALIGNMENT_CONTRACT_VERSION
    classifier_version: str = ALIGNMENT_CLASSIFIER_VERSION
    verifier_version: str = ALIGNMENT_VERIFIER_VERSION
    model_name: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _consistent(self) -> ClaimEvidenceAlignment:
        if any(c.anchor.claim_id != self.claim_id for c in self.components):
            raise ValueError("a component anchor belongs to a different claim")
        if not relation_is_consistent(self.relation, self.components):
            raise ValueError(
                f"relation {self.relation.value} is not consistent with its "
                "component judgments"
            )
        return self

    @property
    def logical_key(self) -> tuple[str, str]:
        """Alignment identity: one claim, one evidence item (section 15)."""
        return (self.claim_id, str(self.evidence_id))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class ClaimAlignmentStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_ALIGNABLE_CLAIMS = "NO_ALIGNABLE_CLAIMS"
    NO_ALIGNABLE_EVIDENCE = "NO_ALIGNABLE_EVIDENCE"
    BLOCKED_PAIR_LIMIT_EXCEEDED = "BLOCKED_PAIR_LIMIT_EXCEEDED"
    NOT_READY = "NOT_READY"


TERMINAL_ALIGNMENT_STATUSES: frozenset[ClaimAlignmentStatus] = frozenset(
    {
        ClaimAlignmentStatus.PARTIAL,
        ClaimAlignmentStatus.COMPLETED,
        ClaimAlignmentStatus.FAILED,
        ClaimAlignmentStatus.NO_ALIGNABLE_CLAIMS,
        ClaimAlignmentStatus.NO_ALIGNABLE_EVIDENCE,
        ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED,
        ClaimAlignmentStatus.NOT_READY,
    }
)


class AlignmentIssueCode(StrEnum):
    NO_CLAIMS = "NO_CLAIMS"
    NO_ACCEPTED_EVIDENCE = "NO_ACCEPTED_EVIDENCE"
    EVIDENCE_EXTRACTION_NOT_READY = "EVIDENCE_EXTRACTION_NOT_READY"
    PAIR_LIMIT_EXCEEDED = "PAIR_LIMIT_EXCEEDED"
    CLASSIFIER_PROVIDER_MISSING = "CLASSIFIER_PROVIDER_MISSING"
    CLASSIFIER_MODEL_FAILED = "CLASSIFIER_MODEL_FAILED"


class AlignmentIssue(MawhibaModel):
    code: AlignmentIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1)
    claim_id: str | None = None


class AlignmentPair(MawhibaModel):
    """One deterministically generated claim/evidence pair, before classification."""

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    evidence_id: UUID


class AlignmentCoverage(MawhibaModel):
    """Operational counters. Describes execution, never claim sufficiency."""

    claims_total: int = Field(default=0, ge=0)
    accepted_evidence_total: int = Field(default=0, ge=0)
    pairs_required: int = Field(default=0, ge=0)
    pairs_generated: int = Field(default=0, ge=0)
    pairs_classified: int = Field(default=0, ge=0)
    candidates_total: int = Field(default=0, ge=0)
    accepted_alignments_total: int = Field(default=0, ge=0)
    rejected_candidates_total: int = Field(default=0, ge=0)
    model_failures: int = Field(default=0, ge=0)
    verification_failures: int = Field(default=0, ge=0)
    relation_counts: dict[str, int] = Field(default_factory=dict)


class ClaimEvidenceAlignmentRun(MawhibaModel):
    """Everything one claim-evidence alignment pass produced.

    Lives on the ``ResearchRun`` (section 3), never in ``ProjectState``: the
    same ownership boundary Phase 2C established, and for the same reason --
    this is research-execution truth, not canonical project truth.
    """

    alignment_run_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    status: ClaimAlignmentStatus = ClaimAlignmentStatus.NOT_STARTED

    contract_version: str = CLAIM_ALIGNMENT_CONTRACT_VERSION
    classifier_prompt_version: str | None = None
    classifier_version: str = ALIGNMENT_CLASSIFIER_VERSION
    verifier_version: str = ALIGNMENT_VERIFIER_VERSION
    dataset_version: str | None = None
    model_name: str | None = None
    provider_name: str | None = None

    max_pairs_per_run: int = Field(default=500, ge=1)
    pairs: list[AlignmentPair] = Field(default_factory=list)
    candidates: list[AlignmentCandidate] = Field(default_factory=list)
    alignments: list[ClaimEvidenceAlignment] = Field(default_factory=list)
    rejected_candidates: list[RejectedAlignmentCandidate] = Field(default_factory=list)
    coverage: AlignmentCoverage = Field(default_factory=AlignmentCoverage)
    errors: list[AlignmentIssue] = Field(default_factory=list)

    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ClaimEvidenceAlignmentRun:
        if any(a.research_run_id != self.research_run_id for a in self.alignments):
            raise ValueError("an alignment belongs to a different research run")
        if any(a.alignment_run_id != self.alignment_run_id for a in self.alignments):
            raise ValueError("an alignment belongs to a different alignment run")

        alignment_ids = [a.alignment_id for a in self.alignments]
        if len(set(alignment_ids)) != len(alignment_ids):
            raise ValueError("alignment ids must be unique")

        keys = [a.logical_key for a in self.alignments]
        if len(set(keys)) != len(keys):
            raise ValueError(
                "a claim/evidence pair cannot carry two incompatible alignments"
            )

        if (
            self.status is ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED
            and self.alignments
        ):
            raise ValueError("BLOCKED_PAIR_LIMIT_EXCEEDED cannot carry alignments")
        if self.status is ClaimAlignmentStatus.NOT_STARTED and (
            self.pairs or self.candidates or self.alignments
        ):
            raise ValueError("NOT_STARTED must not carry pairs, candidates or alignments")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ALIGNMENT_STATUSES

    def alignments_for_claim(self, claim_id: str) -> list[ClaimEvidenceAlignment]:
        return [a for a in self.alignments if a.claim_id == claim_id]


__all__ = [
    "ALIGNMENT_CLASSIFIER_VERSION",
    "ALIGNMENT_VERIFIER_VERSION",
    "CLAIM_ALIGNMENT_CONTRACT_VERSION",
    "CLAIM_ID_PATTERN",
    "MAX_RATIONALE_CHARS",
    "MAX_REJECTION_SUMMARY_CHARS",
    "TERMINAL_ALIGNMENT_STATUSES",
    "AlignmentCandidate",
    "AlignmentCoverage",
    "AlignmentIssue",
    "AlignmentIssueCode",
    "AlignmentPair",
    "AlignmentReasonCode",
    "AlignmentRejectionReason",
    "AlignmentRelation",
    "CandidateComponentAnchor",
    "ClaimAlignmentStatus",
    "ClaimComponentAnchor",
    "ClaimEvidenceAlignment",
    "ClaimEvidenceAlignmentRun",
    "ComponentAlignmentJudgment",
    "ComponentJudgment",
    "RejectedAlignmentCandidate",
    "relation_is_consistent",
]
