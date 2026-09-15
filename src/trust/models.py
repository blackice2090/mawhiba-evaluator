"""Trust policy -- architecture 21 (Trust Gate) and 40 (Definition of Trusted Result).

Everything here is deterministic: given the same ProjectState, ``evaluate_trust_gate``
returns the same TrustGateResult. No model call, no randomness, no clock-dependent
branching. That is what makes the most important layer of the system testable.
"""

from __future__ import annotations

from pydantic import Field

from src.graph.state import ProjectState
from src.schemas.claim import ClaimStatus
from src.schemas.common import (
    EvaluationStatus,
    MawhibaModel,
    Severity,
    UnitInterval,
)
from src.schemas.source import VerificationStatus
from src.schemas.trust import BlockerCode, TrustBlocker, TrustGateResult


class TrustPolicy(MawhibaModel):
    """Configurable thresholds for the trust gate.

    Thresholds are policy, not physics -- they live in config so that changing
    them is a reviewable, versioned event (34 regression testing).
    """

    version: str = Field(default="TRUST-POLICY-V1", min_length=1)

    min_search_coverage: UnitInterval = 0.70
    min_source_quality: UnitInterval = 0.50
    min_claim_traceability: UnitInterval = 1.0
    max_critical_missing: int = Field(default=0, ge=0)

    require_official_requirements_check: bool = True
    require_methodology_review: bool = True
    require_red_team: bool = True
    require_final_verifier: bool = True
    require_closest_prior_art: bool = True

    strong_novelty_min_level: int = Field(default=4, ge=0, le=5)
    """At or above this level, the full novelty precondition list applies (13)."""


DEFAULT_TRUST_POLICY = TrustPolicy()


# ---------------------------------------------------------------------------
# Deterministic metric computation
# ---------------------------------------------------------------------------

def compute_search_coverage(state: ProjectState) -> float:
    """Fraction of required research branches that are satisfied (27)."""
    coverage = state.novelty.branch_coverage
    required = [c for c in coverage if c.required]
    if not required:
        return 0.0
    return sum(1.0 for c in required if c.is_satisfied) / len(required)


def compute_source_quality(state: ProjectState) -> float:
    """Mean of the per-source quality signals over non-duplicate sources (11)."""
    sources = [s for s in state.sources if s.duplicate_of is None]
    if not sources:
        return 0.0
    per_source = [
        (
            s.quality.authority
            + s.quality.relevance
            + s.quality.methodological_strength
            + s.quality.recency_fit
            + s.quality.independent_validation
        )
        / 5.0
        for s in sources
    ]
    return sum(per_source) / len(per_source)


def compute_claim_traceability(state: ProjectState) -> float:
    """Fraction of claims whose status is justified by linked evidence (2.2, 17)."""
    if not state.claims:
        return 0.0
    return sum(1.0 for c in state.claims if c.is_traceable) / len(state.claims)


def untraceable_claims(state: ProjectState) -> list[str]:
    return [c.claim_id for c in state.claims if not c.is_traceable]


def unverified_sources(state: ProjectState) -> list[str]:
    """Sources that were used but never verified (21 hard blocker #1/#2)."""
    unverified_states = {
        VerificationStatus.UNVERIFIED,
        VerificationStatus.SEARCH_RESULT_ONLY,
        VerificationStatus.VERIFICATION_FAILED,
    }
    cited_source_ids = {
        e.source_id
        for c in state.claims
        if c.status in (ClaimStatus.SUPPORTED, ClaimStatus.VERIFIED)
        for e in state.evidence
        if e.evidence_id in c.evidence_ids
    }
    return [
        s.source_id
        for s in state.sources
        if s.source_id in cited_source_ids
        and s.verification_status in unverified_states
    ]


def novelty_search_complete(state: ProjectState, policy: TrustPolicy) -> bool:
    """Section 13 novelty trust gate.

    A strong novelty judgement (level >= strong_novelty_min_level) additionally
    requires identified closest prior art and at least one stated differentiator.
    """
    novelty = state.novelty
    if novelty.unsatisfied_required_branches():
        return False
    if not novelty.branch_coverage:
        return False
    level = novelty.level
    if level is not None and level >= policy.strong_novelty_min_level:
        if not novelty.closest_prior_art_ids or not novelty.differentiators:
            return False
    return True


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def evaluate_trust_gate(
    state: ProjectState,
    policy: TrustPolicy = DEFAULT_TRUST_POLICY,
    *,
    methodology_review_complete: bool | None = None,
    red_team_complete: bool = False,
    final_verifier_passed: bool = False,
    official_requirements_checked: bool = False,
) -> TrustGateResult:
    """Deterministically decide whether this evaluation may be finalized.

    Flags that no schema can derive from the state alone (red team ran, final
    verifier passed) are passed in explicitly by the workflow rather than
    guessed.
    """
    blockers: list[TrustBlocker] = []

    search_coverage = compute_search_coverage(state)
    source_quality = compute_source_quality(state)
    claim_traceability = compute_claim_traceability(state)

    if methodology_review_complete is None:
        methodology_review_complete = (
            state.methodology.review_status == EvaluationStatus.FINAL
        )

    unresolved = state.unresolved_critical_contradictions
    critical_missing = state.critical_missing_information
    bad_sources = unverified_sources(state)
    bad_claims = untraceable_claims(state)
    novelty_ok = novelty_search_complete(state, policy)
    prior_art_identified = bool(state.novelty.closest_prior_art_ids)

    # --- hard blockers (21) -------------------------------------------------
    if bad_sources:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.INVENTED_OR_UNVERIFIED_CITATION,
                detail=(
                    "sources cited by SUPPORTED/VERIFIED claims are not verified: "
                    f"{sorted(bad_sources)}"
                ),
                related_ids=sorted(bad_sources),
            )
        )

    if unresolved:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.UNRESOLVED_CRITICAL_CONTRADICTION,
                detail=f"{len(unresolved)} unresolved critical contradiction(s)",
                related_ids=[c.contradiction_id for c in unresolved],
            )
        )

    if not novelty_ok:
        unsatisfied = state.novelty.unsatisfied_required_branches()
        blockers.append(
            TrustBlocker(
                code=BlockerCode.NOVELTY_SEARCH_INCOMPLETE,
                detail=(
                    "novelty search preconditions not met; unsatisfied required "
                    f"branches: {[b.value for b in unsatisfied] or 'none recorded'}"
                ),
                related_ids=[b.value for b in unsatisfied],
            )
        )

    if bad_claims:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.MISSING_EVIDENCE_FOR_HIGH_CONFIDENCE_CLAIM,
                detail=f"claims without justifying evidence: {sorted(bad_claims)}",
                related_ids=sorted(bad_claims),
            )
        )

    if policy.require_closest_prior_art and not prior_art_identified:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.CLOSEST_PRIOR_ART_NOT_IDENTIFIED,
                detail="no closest prior art identified before judging novelty (12)",
            )
        )

    if len(critical_missing) > policy.max_critical_missing:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.CRITICAL_INFORMATION_MISSING,
                detail=(
                    f"{len(critical_missing)} critical field(s) missing, policy allows "
                    f"{policy.max_critical_missing}"
                ),
                related_ids=[m.field_path for m in critical_missing],
            )
        )

    if search_coverage < policy.min_search_coverage:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.SEARCH_COVERAGE_BELOW_THRESHOLD,
                detail=(
                    f"search coverage {search_coverage:.2f} < "
                    f"{policy.min_search_coverage:.2f}"
                ),
                severity=Severity.HIGH,
            )
        )

    if source_quality < policy.min_source_quality:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.SOURCE_QUALITY_BELOW_THRESHOLD,
                detail=(
                    f"mean source quality {source_quality:.2f} < "
                    f"{policy.min_source_quality:.2f}"
                ),
                severity=Severity.HIGH,
            )
        )

    if claim_traceability < policy.min_claim_traceability:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.CLAIM_TRACEABILITY_BELOW_THRESHOLD,
                detail=(
                    f"claim traceability {claim_traceability:.2f} < "
                    f"{policy.min_claim_traceability:.2f}"
                ),
            )
        )

    for finding in state.blocking_findings:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.CRITICAL_FINDING_UNADDRESSED,
                detail=f"{finding.finding_id}: {finding.finding}",
                severity=finding.severity,
                related_ids=[finding.finding_id],
            )
        )

    if policy.require_methodology_review and not methodology_review_complete:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.METHODOLOGY_REVIEW_INCOMPLETE,
                detail="methodology review has not reached FINAL (N12)",
                severity=Severity.HIGH,
            )
        )

    if policy.require_red_team and not red_team_complete:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.RED_TEAM_INCOMPLETE,
                detail="independent red team pass has not completed (19)",
                severity=Severity.HIGH,
            )
        )

    if policy.require_official_requirements_check and not official_requirements_checked:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.OFFICIAL_RULE_ASSERTED_WITHOUT_OFFICIAL_EVIDENCE,
                detail="official requirements were never checked against an official source (N03)",
                severity=Severity.HIGH,
            )
        )

    if policy.require_final_verifier and not final_verifier_passed:
        blockers.append(
            TrustBlocker(
                code=BlockerCode.FINAL_VERIFIER_NOT_PASSED,
                detail="final verifier has not passed (N19)",
                severity=Severity.HIGH,
            )
        )

    finalization_allowed = not blockers
    if finalization_allowed:
        score_status = EvaluationStatus.FINAL
    elif critical_missing or not state.claims:
        score_status = EvaluationStatus.INSUFFICIENT_EVIDENCE
    else:
        score_status = EvaluationStatus.PROVISIONAL

    return TrustGateResult(
        search_coverage=search_coverage,
        source_quality=source_quality,
        claim_traceability=claim_traceability,
        contradictions_resolved=not unresolved,
        novelty_search_complete=novelty_ok,
        methodology_review_complete=methodology_review_complete,
        red_team_complete=red_team_complete,
        closest_prior_art_identified=prior_art_identified,
        sources_verified=not bad_sources,
        official_requirements_checked=official_requirements_checked,
        final_verifier_passed=final_verifier_passed,
        critical_missing_count=len(critical_missing),
        unresolved_critical_contradiction_count=len(unresolved),
        unverified_source_count=len(bad_sources),
        untraceable_claim_count=len(bad_claims),
        score_status=score_status,
        finalization_allowed=finalization_allowed,
        blockers=blockers,
        policy_version=policy.version,
    )
