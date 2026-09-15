"""FindingRecord and ContradictionRecord -- architecture 7.5, 18 (Contradictions),
19 (Red Team)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import (
    ConfidenceLevel,
    MawhibaModel,
    Severity,
    UtcDatetime,
)


class FindingCategory(StrEnum):
    METHODOLOGY = "METHODOLOGY"
    NOVELTY = "NOVELTY"
    GAP = "GAP"
    EXPERIMENTS = "EXPERIMENTS"
    RESULTS = "RESULTS"
    DATA = "DATA"
    CLAIMS = "CLAIMS"
    PRIOR_ART = "PRIOR_ART"
    LITERATURE = "LITERATURE"
    ARCHITECTURE = "ARCHITECTURE"
    PROBLEM = "PROBLEM"
    SAFETY_OR_ETHICS = "SAFETY_OR_ETHICS"
    STUDENT_CONTRIBUTION = "STUDENT_CONTRIBUTION"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    CITATION_INTEGRITY = "CITATION_INTEGRITY"
    OTHER = "OTHER"


class RecommendedActionType(StrEnum):
    REQUIRES_FIX = "REQUIRES_FIX"
    REQUIRES_EVIDENCE = "REQUIRES_EVIDENCE"
    REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"
    REQUIRES_ADDITIONAL_EXPERIMENT = "REQUIRES_ADDITIONAL_EXPERIMENT"
    REQUIRES_REFRAMING = "REQUIRES_REFRAMING"
    INFORMATIONAL = "INFORMATIONAL"


class FindingOrigin(StrEnum):
    """Which node produced the finding. Red Team findings are deliberately
    separable (19)."""

    METHODOLOGY_SPECIALIST = "METHODOLOGY_SPECIALIST"
    EXPERIMENT_REVIEWER = "EXPERIMENT_REVIEWER"
    CLAIM_EVIDENCE_ENGINE = "CLAIM_EVIDENCE_ENGINE"
    CONTRADICTION_DETECTOR = "CONTRADICTION_DETECTOR"
    RED_TEAM = "RED_TEAM"
    NOVELTY_ENGINE = "NOVELTY_ENGINE"
    GAP_ENGINE = "GAP_ENGINE"
    FINAL_VERIFIER = "FINAL_VERIFIER"
    OTHER = "OTHER"


class FindingRecord(MawhibaModel):
    """A defect, risk, or observation with its justification chain (7.5)."""

    finding_id: str = Field(pattern=r"^F-\d{3,}$", examples=["F-001"])
    category: FindingCategory
    severity: Severity
    finding: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="Why this matters -- never just a label.")
    evidence_ids: list[str] = Field(default_factory=list)
    affected_claim_ids: list[str] = Field(default_factory=list)
    recommended_action_type: RecommendedActionType = RecommendedActionType.INFORMATIONAL
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    origin: FindingOrigin = FindingOrigin.OTHER
    blocks_finalization: bool = Field(
        default=False,
        description="Set by the node that raised it; the trust gate also derives "
        "blocking from CRITICAL severity.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _high_confidence_needs_evidence(self) -> FindingRecord:
        if self.confidence == ConfidenceLevel.HIGH and not (
            self.evidence_ids or self.affected_claim_ids
        ):
            raise ValueError(
                "a HIGH-confidence finding must reference evidence_ids or "
                "affected_claim_ids (2.2)"
            )
        return self

    @property
    def is_blocking(self) -> bool:
        return self.blocks_finalization or self.severity == Severity.CRITICAL


class ContradictionStatus(StrEnum):
    OPEN = "OPEN"
    AWAITING_STUDENT = "AWAITING_STUDENT"
    RESOLVED = "RESOLVED"
    UNRESOLVABLE = "UNRESOLVABLE"


class ContradictionRecord(MawhibaModel):
    """Section 18: a concrete conflict between two statements/artifacts."""

    contradiction_id: str = Field(pattern=r"^CT-\d{3,}$", examples=["CT-001"])
    description: str = Field(min_length=1)
    severity: Severity
    status: ContradictionStatus = ContradictionStatus.OPEN
    conflicting_statements: list[str] = Field(default_factory=list)
    affected_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    requires_student_clarification: bool = False
    resolution: str | None = None
    resolved_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _resolution_rules(self) -> ContradictionRecord:
        if len(self.conflicting_statements) < 2:
            raise ValueError("a contradiction needs at least 2 conflicting statements")
        if self.status == ContradictionStatus.RESOLVED and not self.resolution:
            raise ValueError("a RESOLVED contradiction must state its resolution")
        if self.status != ContradictionStatus.RESOLVED and self.resolved_at is not None:
            raise ValueError("resolved_at is only valid for RESOLVED contradictions")
        return self

    @property
    def is_unresolved_critical(self) -> bool:
        return (
            self.severity == Severity.CRITICAL
            and self.status != ContradictionStatus.RESOLVED
        )


class MissingInformationRecord(MawhibaModel):
    """Section 24: the agent asks only when MISSING + CRITICAL + NOT_RETRIEVABLE."""

    field_path: str = Field(min_length=1, examples=["methodology.baseline"])
    description: str = Field(min_length=1)
    severity: Severity = Severity.HIGH
    retrievable_externally: bool = False
    question_for_student: str | None = None
    blocks_axes: list[str] = Field(
        default_factory=list, description="Score axis names this missing field blocks."
    )

    @model_validator(mode="after")
    def _ask_only_when_warranted(self) -> MissingInformationRecord:
        if self.question_for_student and self.retrievable_externally:
            raise ValueError(
                "do not ask the student for information that is retrievable "
                "externally (24)"
            )
        return self

    @property
    def is_critical(self) -> bool:
        return self.severity == Severity.CRITICAL
