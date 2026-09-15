"""ClaimRecord -- architecture 7.3 and 17 (Claim-Evidence Engine).

Core invariant (2.2): SUPPORTED and VERIFIED require evidence; CONTRADICTED
requires counter-evidence. No evidence -> no strong claim.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UnitInterval


class ClaimStatus(StrEnum):
    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    PLAUSIBLE = "PLAUSIBLE"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


STRONG_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.SUPPORTED, ClaimStatus.VERIFIED}
)
"""Statuses that may not be reached without evidence (2.2)."""


class ClaimType(StrEnum):
    PERFORMANCE = "PERFORMANCE"
    NOVELTY = "NOVELTY"
    FEASIBILITY = "FEASIBILITY"
    IMPACT = "IMPACT"
    COST = "COST"
    SAFETY = "SAFETY"
    METHODOLOGY = "METHODOLOGY"
    PROBLEM_IMPORTANCE = "PROBLEM_IMPORTANCE"
    CONTRIBUTION = "CONTRIBUTION"
    OTHER = "OTHER"


class ClaimOrigin(StrEnum):
    STUDENT = "STUDENT"
    STUDENT_FILE = "STUDENT_FILE"
    AGENT_DERIVED = "AGENT_DERIVED"
    EXTERNAL = "EXTERNAL"


class RequiredEvidenceKind(StrEnum):
    """What a claim of this type needs before it can be raised (17)."""

    BASELINE = "BASELINE"
    TEST_DATA = "TEST_DATA"
    METRIC = "METRIC"
    REPEATED_MEASUREMENTS = "REPEATED_MEASUREMENTS"
    SAME_EVALUATION_SETTING = "SAME_EVALUATION_SETTING"
    INDEPENDENT_VALIDATION = "INDEPENDENT_VALIDATION"
    PRIOR_ART_SEARCH = "PRIOR_ART_SEARCH"
    STATISTICAL_TEST = "STATISTICAL_TEST"
    SAMPLE_SIZE = "SAMPLE_SIZE"
    REFERENCE_INSTRUMENT = "REFERENCE_INSTRUMENT"
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    COST_DATA = "COST_DATA"
    OTHER = "OTHER"


class ClaimRecord(MawhibaModel):
    """A single evaluable assertion plus its evidence graph edges (7.3)."""

    claim_id: str = Field(pattern=r"^C-\d{3,}$", examples=["C-001"])
    claim: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.OTHER
    origin: ClaimOrigin = ClaimOrigin.STUDENT
    status: ClaimStatus = ClaimStatus.UNSUPPORTED
    evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    required_evidence: list[RequiredEvidenceKind] = Field(default_factory=list)
    missing_evidence: list[RequiredEvidenceKind] = Field(default_factory=list)
    confidence: UnitInterval = 0.0
    is_critical: bool = Field(
        default=False,
        description="Critical claims gate finalization when unsupported (21).",
    )
    source_location: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _enforce_evidence_rules(self) -> ClaimRecord:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        if len(set(self.counter_evidence_ids)) != len(self.counter_evidence_ids):
            raise ValueError("counter_evidence_ids must be unique")
        overlap = set(self.evidence_ids) & set(self.counter_evidence_ids)
        if overlap:
            raise ValueError(
                f"evidence cannot both support and contradict a claim: {sorted(overlap)}"
            )

        # 2.2 No Evidence -> No Strong Claim.
        if self.status in STRONG_CLAIM_STATUSES and not self.evidence_ids:
            raise ValueError(
                f"status={self.status.value} requires at least one evidence_id (2.2)"
            )
        if self.status == ClaimStatus.CONTRADICTED and not self.counter_evidence_ids:
            raise ValueError(
                "status=CONTRADICTED requires at least one counter_evidence_id"
            )
        if self.status == ClaimStatus.UNSUPPORTED and self.evidence_ids:
            raise ValueError(
                "status=UNSUPPORTED must have no evidence_ids; use PLAUSIBLE or "
                "SUPPORTED instead"
            )

        # A claim still missing its required evidence cannot be a strong claim.
        if self.status in STRONG_CLAIM_STATUSES and self.missing_evidence:
            raise ValueError(
                f"status={self.status.value} is not allowed while missing_evidence "
                f"is non-empty: {[m.value for m in self.missing_evidence]}"
            )
        if not set(self.missing_evidence).issubset(set(self.required_evidence)):
            raise ValueError("missing_evidence must be a subset of required_evidence")

        # Confidence must not outrun the status.
        if self.status == ClaimStatus.UNSUPPORTED and self.confidence > 0.25:
            raise ValueError("UNSUPPORTED claims cannot carry confidence above 0.25")
        return self

    @property
    def is_strong(self) -> bool:
        return self.status in STRONG_CLAIM_STATUSES

    @property
    def is_traceable(self) -> bool:
        """A claim is traceable if its status is justified by linked evidence
        or it honestly declares itself unsupported."""
        if self.status in STRONG_CLAIM_STATUSES:
            return bool(self.evidence_ids)
        if self.status == ClaimStatus.CONTRADICTED:
            return bool(self.counter_evidence_ids)
        return True
