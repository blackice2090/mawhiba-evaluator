"""TrustGateResult -- architecture 21 (Trust Gate) and 40 (Definition of Trusted
Result).

The trust gate is deliberately free of LLM reasoning: it is a pure data
structure plus deterministic predicates, so it can be unit-tested and replayed.
The policy that *computes* one of these lives in ``src/trust/models.py``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from src.schemas.common import (
    EvaluationStatus,
    MawhibaModel,
    Severity,
    UnitInterval,
    UtcDatetime,
    utc_now,
)


class BlockerCode(StrEnum):
    """Section 21 hard blockers, as closed machine-readable codes."""

    INVENTED_OR_UNVERIFIED_CITATION = "INVENTED_OR_UNVERIFIED_CITATION"
    UNVERIFIED_DOI_USED_AS_CONFIRMED = "UNVERIFIED_DOI_USED_AS_CONFIRMED"
    UNRESOLVED_CRITICAL_CONTRADICTION = "UNRESOLVED_CRITICAL_CONTRADICTION"
    NOVELTY_SEARCH_INCOMPLETE = "NOVELTY_SEARCH_INCOMPLETE"
    MISSING_EVIDENCE_FOR_HIGH_CONFIDENCE_CLAIM = (
        "MISSING_EVIDENCE_FOR_HIGH_CONFIDENCE_CLAIM"
    )
    OFFICIAL_RULE_ASSERTED_WITHOUT_OFFICIAL_EVIDENCE = (
        "OFFICIAL_RULE_ASSERTED_WITHOUT_OFFICIAL_EVIDENCE"
    )
    CLOSEST_PRIOR_ART_NOT_IDENTIFIED = "CLOSEST_PRIOR_ART_NOT_IDENTIFIED"
    METHODOLOGY_REVIEW_INCOMPLETE = "METHODOLOGY_REVIEW_INCOMPLETE"
    RED_TEAM_INCOMPLETE = "RED_TEAM_INCOMPLETE"
    CRITICAL_INFORMATION_MISSING = "CRITICAL_INFORMATION_MISSING"
    SEARCH_COVERAGE_BELOW_THRESHOLD = "SEARCH_COVERAGE_BELOW_THRESHOLD"
    SOURCE_QUALITY_BELOW_THRESHOLD = "SOURCE_QUALITY_BELOW_THRESHOLD"
    CLAIM_TRACEABILITY_BELOW_THRESHOLD = "CLAIM_TRACEABILITY_BELOW_THRESHOLD"
    CRITICAL_FINDING_UNADDRESSED = "CRITICAL_FINDING_UNADDRESSED"
    SCORE_NOT_DETERMINISTIC = "SCORE_NOT_DETERMINISTIC"
    FINAL_VERIFIER_NOT_PASSED = "FINAL_VERIFIER_NOT_PASSED"


class TrustBlocker(MawhibaModel):
    """One reason finalization is refused. Always carries a human-readable detail
    so the report can answer 'why can't you finalize?'."""

    code: BlockerCode
    detail: str = Field(min_length=1)
    severity: Severity = Severity.CRITICAL
    related_ids: list[str] = Field(
        default_factory=list,
        description="Claim/evidence/source/contradiction ids that triggered it.",
    )


class TrustGateResult(MawhibaModel):
    """Section 21. Snapshot of whether the evaluation may be finalized.

    Every numeric field is a measured ratio produced by deterministic code --
    no model opinion is stored here.
    """

    # --- measured coverage / quality signals -------------------------------
    search_coverage: UnitInterval = 0.0
    source_quality: UnitInterval = 0.0
    claim_traceability: UnitInterval = 0.0

    # --- boolean completion flags -----------------------------------------
    contradictions_resolved: bool = False
    novelty_search_complete: bool = False
    methodology_review_complete: bool = False
    red_team_complete: bool = False
    closest_prior_art_identified: bool = False
    sources_verified: bool = False
    official_requirements_checked: bool = False
    final_verifier_passed: bool = False

    # --- counts ------------------------------------------------------------
    critical_missing_count: int = Field(default=0, ge=0)
    unresolved_critical_contradiction_count: int = Field(default=0, ge=0)
    unverified_source_count: int = Field(default=0, ge=0)
    untraceable_claim_count: int = Field(default=0, ge=0)

    # --- verdict -----------------------------------------------------------
    score_status: EvaluationStatus = EvaluationStatus.PROVISIONAL
    finalization_allowed: bool = False
    blockers: list[TrustBlocker] = Field(default_factory=list)
    evaluated_at: UtcDatetime = Field(default_factory=utc_now)
    policy_version: str = Field(default="TRUST-POLICY-V1")

    @model_validator(mode="after")
    def _verdict_consistency(self) -> TrustGateResult:
        if self.finalization_allowed and self.blockers:
            raise ValueError(
                "finalization_allowed cannot be True while blockers are present (21)"
            )
        if self.finalization_allowed and self.score_status not in (
            EvaluationStatus.FINAL,
            EvaluationStatus.PROVISIONAL,
        ):
            raise ValueError(
                f"finalization_allowed is incompatible with score_status="
                f"{self.score_status.value}"
            )
        if (
            self.contradictions_resolved
            and self.unresolved_critical_contradiction_count > 0
        ):
            raise ValueError(
                "contradictions_resolved=True contradicts a non-zero "
                "unresolved_critical_contradiction_count"
            )
        return self

    @property
    def blocker_codes(self) -> set[BlockerCode]:
        return {b.code for b in self.blockers}

    def has_blocker(self, code: BlockerCode) -> bool:
        return code in self.blocker_codes
