"""Extraction contracts.

Two layers live here, and the split is the whole point:

*Model-facing DTOs* (``ExtractedValue``, ``ProjectExtraction``,
``ProjectClassification``) are what the LLM is asked to produce. They are
**untrusted candidates**. Nothing in them is believed on arrival.

*Verified contracts* (``TextRange``, ``VerifiedAnchor``, ``VerifiedField``,
``VerifiedExtraction``) are what deterministic code produces after checking each
candidate against the student's actual submission. Only these can reach
ProjectState.

The model never produces a ProjectState, and never produces a KnowledgeStatus.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.common import (
    ExtractionMode,
    MawhibaModel,
    ProjectType,
    TechnicalDomain,
    UnitInterval,
)

__all_domain_note__ = """TechnicalDomain is imported, not redefined.

Phase 1B declared a second taxonomy here and projected it lossily onto the Phase 0
enum. Phase 1C removes that duplication: the classifier DTO and
ProjectState.identity.domain are now the same enum (ADR-005)."""

# ---------------------------------------------------------------------------
# Model-facing DTOs -- untrusted candidate output
# ---------------------------------------------------------------------------


class ModelFacingModel(BaseModel):
    """Base for schemas sent to the LLM as a Structured Output format.

    Kept separate from MawhibaModel: these need a plain, strict-friendly shape
    with no custom validators that could reject a model response before the
    trust layer has a chance to record *why* it was rejected.
    """

    model_config = ConfigDict(extra="forbid")


class ExtractedValue(ModelFacingModel):
    """One candidate value plus the verbatim excerpt that supports it.

    ``excerpt`` must be copied character-for-character out of the student's
    submission. The model is never asked for character offsets -- those are
    derived deterministically by code, because a model can miscount and a
    miscounted offset would look like verified provenance.
    """

    value: str = Field(description="The extracted value, as stated by the student.")
    excerpt: str = Field(
        description="Verbatim quote from the submission supporting this value."
    )
    confidence: float = Field(
        description="Model's own confidence, 0.0-1.0. Advisory only; it never "
        "determines truth status."
    )


class ExtractedClaim(ModelFacingModel):
    """A performance/impact assertion made by the student.

    Extracted as a claim, never as a result. ``claim_type`` maps onto the Phase 0
    ClaimType vocabulary during merge.
    """

    statement: str
    excerpt: str
    claim_type: str = Field(
        description="One of PERFORMANCE, IMPACT, COST, NOVELTY, FEASIBILITY, "
        "SAFETY, CONTRIBUTION, PROBLEM_IMPORTANCE, OTHER."
    )
    confidence: float


class ExtractedConflict(ModelFacingModel):
    """Two incompatible statements about the same fact inside the submission."""

    subject: str = Field(description="What the two statements disagree about.")
    first_statement: str
    first_excerpt: str
    second_statement: str
    second_excerpt: str


class ProjectExtraction(ModelFacingModel):
    """The Phase 1B intake extraction DTO.

    Deliberately NOT a ProjectState: the model produces a narrow, intake-shaped
    payload, and code decides what that means for the canonical state.

    Every field is optional or a list, because absence is a legitimate and
    expected outcome. The model is instructed to omit rather than guess.
    """

    project_name: ExtractedValue | None = None
    problem_statement: ExtractedValue | None = None
    beneficiaries: list[ExtractedValue] = Field(default_factory=list)
    solution_description: ExtractedValue | None = None
    goal: ExtractedValue | None = None
    architecture_description: ExtractedValue | None = None
    student_contribution: ExtractedValue | None = None
    current_stage: ExtractedValue | None = None
    prototype_status: ExtractedValue | None = None

    claimed_innovation: list[ExtractedValue] = Field(default_factory=list)
    technologies: list[ExtractedValue] = Field(default_factory=list)
    hardware: list[ExtractedValue] = Field(default_factory=list)
    software: list[ExtractedValue] = Field(default_factory=list)
    sensors: list[ExtractedValue] = Field(default_factory=list)
    algorithms: list[ExtractedValue] = Field(default_factory=list)
    datasets: list[ExtractedValue] = Field(default_factory=list)
    data_sources: list[ExtractedValue] = Field(default_factory=list)
    baseline_mentions: list[ExtractedValue] = Field(default_factory=list)
    metric_mentions: list[ExtractedValue] = Field(default_factory=list)

    result_claims: list[ExtractedClaim] = Field(default_factory=list)
    conflicts: list[ExtractedConflict] = Field(default_factory=list)


class DomainAssignment(ModelFacingModel):
    """One inferred domain with the excerpt that justifies it."""

    domain: TechnicalDomain
    excerpt: str
    confidence: float


class ProjectClassification(ModelFacingModel):
    """Classifier DTO (architecture N02).

    ``rationale`` is a one-sentence justification, not a reasoning trace. The
    prompt and a length bound both enforce that.
    """

    project_type: ProjectType
    project_type_confidence: float
    project_type_excerpt: str = Field(
        description="Verbatim excerpt supporting the type. Empty string if UNKNOWN."
    )
    rationale: str = Field(
        description="One short sentence. Never step-by-step reasoning."
    )
    domains: list[DomainAssignment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Verified contracts -- produced by deterministic code, trusted
# ---------------------------------------------------------------------------


class AnchorVerificationMethod(StrEnum):
    """How the excerpt was matched against the artifact.

    Recorded so a later reader can tell an exact quote from one that only
    matched after whitespace folding.
    """

    EXACT = "EXACT"
    NORMALIZED_WHITESPACE = "NORMALIZED_WHITESPACE"
    NORMALIZED_UNICODE = "NORMALIZED_UNICODE"
    NOT_FOUND = "NOT_FOUND"


class TextRange(MawhibaModel):
    """A half-open character range inside an artifact's original text."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> TextRange:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start


class VerifiedAnchor(MawhibaModel):
    """A provenance anchor that deterministic code has checked.

    Multiple matches are recorded rather than collapsed: an excerpt appearing
    twice is not invalid, and inventing one exact location would be a fabricated
    precision.
    """

    artifact_id: UUID
    excerpt: str = Field(min_length=1)
    method: AnchorVerificationMethod
    matches: list[TextRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _found_means_matched(self) -> VerifiedAnchor:
        if self.method is AnchorVerificationMethod.NOT_FOUND and self.matches:
            raise ValueError("NOT_FOUND anchors cannot carry matches")
        if self.method is not AnchorVerificationMethod.NOT_FOUND and not self.matches:
            raise ValueError(f"method={self.method.value} requires at least one match")
        return self

    @property
    def verified(self) -> bool:
        return self.method is not AnchorVerificationMethod.NOT_FOUND

    @property
    def occurrence_count(self) -> int:
        return len(self.matches)


FieldKind = ExtractionMode
"""Backwards-compatible alias.

Phase 1B called this ``FieldKind`` with two members. Phase 1C promoted it to the
shared ``ExtractionMode`` vocabulary (ADR-004) and added VERBATIM_SPAN and
STUDENT_CLAIM. The alias keeps existing imports working against one enum.
"""


class RejectionReason(StrEnum):
    """Why a candidate field failed verification. Closed and machine-readable."""

    ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"
    VALUE_NOT_SUPPORTED_BY_ANCHOR = "VALUE_NOT_SUPPORTED_BY_ANCHOR"
    EMPTY_VALUE = "EMPTY_VALUE"
    EMPTY_EXCERPT = "EMPTY_EXCERPT"
    UNSUPPORTED_FIELD = "UNSUPPORTED_FIELD"
    # Phase 1C additions.
    NARRATIVE_NOT_VERBATIM = "NARRATIVE_NOT_VERBATIM"
    UNSUPPORTED_EXTRACTION_MODE = "UNSUPPORTED_EXTRACTION_MODE"
    INVALID_CANONICAL_DESTINATION = "INVALID_CANONICAL_DESTINATION"
    CONFLICT = "CONFLICT"


class VerifiedField(MawhibaModel):
    """One candidate field after deterministic verification.

    ``accepted`` is decided by code alone. The model's ``confidence`` is carried
    along for observability and never participates in that decision.
    """

    field_path: str = Field(min_length=1)
    value: str = Field(
        description="The canonical value. For a VERBATIM_SPAN field this IS the "
        "source span, never an LLM paraphrase (ADR-004)."
    )
    model_summary: str | None = Field(
        default=None,
        description="The model's own phrasing, kept as DERIVED metadata for "
        "debugging and future search. Never canonical, never overwrites the "
        "student's wording.",
    )
    kind: FieldKind
    anchor: VerifiedAnchor
    accepted: bool
    rejection_reason: RejectionReason | None = None
    model_confidence: UnitInterval | None = Field(
        default=None,
        description="Advisory only. Never used to decide `accepted`.",
    )

    @model_validator(mode="after")
    def _accepted_means_verified(self) -> VerifiedField:
        if self.accepted:
            if not self.anchor.verified:
                raise ValueError("an accepted field requires a verified anchor")
            if self.rejection_reason is not None:
                raise ValueError("an accepted field cannot carry a rejection reason")
        elif self.rejection_reason is None:
            raise ValueError("a rejected field must state its rejection reason")
        return self


class VerifiedClaim(MawhibaModel):
    """A student claim after anchor verification. Always student-origin."""

    statement: str = Field(
        min_length=1,
        description="The student's own words -- the verified excerpt, not a "
        "paraphrase. Misquoting an attributed claim is itself a distortion.",
    )
    model_summary: str | None = Field(
        default=None, description="The model's rendering. Derived, never canonical."
    )
    claim_type: str
    anchor: VerifiedAnchor
    accepted: bool
    rejection_reason: RejectionReason | None = None


class VerifiedConflict(MawhibaModel):
    """Two incompatible student statements, both anchor-verified."""

    subject: str = Field(min_length=1)
    first_statement: str
    second_statement: str
    first_anchor: VerifiedAnchor
    second_anchor: VerifiedAnchor
    accepted: bool
    rejection_reason: RejectionReason | None = None


class RejectedExtraction(MawhibaModel):
    """An audit record of a model candidate that deterministic code refused.

    Kept so a false positive can be debugged without polluting ProjectState.
    Carries the candidate value and its anchor verdict, never hidden reasoning
    and never anything that could be mistaken for a project fact.
    """

    field: str = Field(min_length=1)
    candidate_value: str
    artifact_id: UUID
    anchor: VerifiedAnchor
    rejection_code: RejectionReason
    mode: ExtractionMode
    model_confidence: UnitInterval | None = None

    @classmethod
    def from_field(cls, verified: VerifiedField) -> RejectedExtraction:
        if verified.accepted or verified.rejection_reason is None:
            raise ValueError("only a rejected field can enter the ledger")
        return cls(
            field=verified.field_path,
            candidate_value=verified.value,
            artifact_id=verified.anchor.artifact_id,
            anchor=verified.anchor,
            rejection_code=verified.rejection_reason,
            mode=verified.kind,
            model_confidence=verified.model_confidence,
        )


class VerifiedExtraction(MawhibaModel):
    """The complete deterministic verdict on one extraction.

    This, not ``ProjectExtraction``, is what the merge layer consumes.
    """

    artifact_id: UUID
    fields: list[VerifiedField] = Field(default_factory=list)
    claims: list[VerifiedClaim] = Field(default_factory=list)
    conflicts: list[VerifiedConflict] = Field(default_factory=list)

    @property
    def accepted_fields(self) -> list[VerifiedField]:
        return [f for f in self.fields if f.accepted]

    @property
    def rejected_fields(self) -> list[VerifiedField]:
        return [f for f in self.fields if not f.accepted]

    @property
    def accepted_claims(self) -> list[VerifiedClaim]:
        return [c for c in self.claims if c.accepted]

    @property
    def accepted_conflicts(self) -> list[VerifiedConflict]:
        return [c for c in self.conflicts if c.accepted]

    def accepted_for(self, field_path: str) -> list[VerifiedField]:
        return [f for f in self.accepted_fields if f.field_path == field_path]

    @property
    def ledger(self) -> list[RejectedExtraction]:
        """Every refused candidate, as audit records."""
        return [RejectedExtraction.from_field(f) for f in self.rejected_fields]


class VerifiedClassification(MawhibaModel):
    """Classification after anchor verification.

    A type whose excerpt does not verify falls back to UNKNOWN rather than being
    accepted on the model's say-so.
    """

    artifact_id: UUID
    project_type: ProjectType
    project_type_confidence: UnitInterval | None = None
    type_anchor: VerifiedAnchor | None = None
    rationale: str = ""
    domains: list[VerifiedField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unknown_type_carries_no_confidence(self) -> VerifiedClassification:
        if (
            self.project_type is ProjectType.UNKNOWN
            and self.project_type_confidence is not None
        ):
            raise ValueError(
                "UNKNOWN project_type must not carry a confidence (Zero Assumption)"
            )
        return self

    @property
    def accepted_domains(self) -> list[TechnicalDomain]:
        return [TechnicalDomain(d.value) for d in self.domains if d.accepted]


MAX_RATIONALE_LENGTH = 400
"""Rationale is a sentence, not a reasoning trace. Truncated beyond this."""
