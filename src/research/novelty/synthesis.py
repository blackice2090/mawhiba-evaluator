"""Deterministic claim posture and project synthesis -- Phase 2I sections 23-28, 42.

No model is asked "is this claim novel?". The posture is a pure function of
the verified comparisons, the feature inventory and the comparison coverage,
applied in a fixed rule order (``TECHNICAL-OVERLAP-SYNTHESIS-POLICY-V1``):

1. every linked candidate blocked by source quality -> BLOCKED_SOURCE_QUALITY
2. one candidate discloses every feature incl. the combination
                                                    -> MATERIAL_TECHNICAL_OVERLAP_FOUND
3. no verified comparison                           -> INSUFFICIENT_COMPARISON_EVIDENCE
4. some feature (partially) disclosed:
     differentiation reportable and a feature not found -> MIXED_OVERLAP_AND_DIFFERENTIATION
     otherwise                                          -> PARTIAL_TECHNICAL_OVERLAP_ONLY
5. nothing disclosed:
     differentiation reportable and every feature not found
                                                    -> NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS
     otherwise                                      -> INSUFFICIENT_COMPARISON_EVIDENCE

"Differentiation reportable" requires component-level mode, a complete
inventory, complete comparison coverage within bounds, and -- in every
verified comparison -- complete MATERIAL text for each feature TYPE the claim
contains (a manifest is material for a component, never for a mechanism or the
combination). Independent corroboration is counted by ``corroboration_key``:
unresolved patent families and fork/mirror lineages contribute none, and
correlated product entities contribute one together without being merged.
Chronology statements are per candidate type and prove no publicity. Candidate
input order cannot change any of this: every collection is sorted before it is
read.
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.novelty_differentiation import (
    CANDIDATE_TYPE_ORDER,
    PROJECT_SUMMARY_LIMITATIONS,
    UNIVERSAL_SYNTHESIS_LIMITATIONS,
    CandidateComparisonProfile,
    CandidateEligibility,
    CandidateType,
    ChronologyBucket,
    ChronologySplit,
    ClaimCandidateComparison,
    ClaimComparisonCoverage,
    ClaimDifferentiationSynthesis,
    ClaimTechnicalPosture,
    ComparisonCoverageStatus,
    ComparisonFeatureInventory,
    ComparisonStatus,
    DifferentiationReporting,
    DifferentiationStatus,
    FAILED_COMPARISON_STATUSES,
    FeatureDifferentiation,
    FeatureRelation,
    FullClaimRelation,
    IndependenceUnitKind,
    InventoryCompleteness,
    InventoryMode,
    PostureReason,
    ProjectDifferentiationSummary,
    SynthesisLimitation,
    TypeCoverage,
    TypeOverlapSummary,
    differentiation_status,
    novelty_id,
)


OVERLAPPING_RELATIONS = frozenset(
    {
        FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP,
        FullClaimRelation.PARTIAL_CLAIM_TECHNICAL_OVERLAP,
        FullClaimRelation.COMPONENT_ONLY_OVERLAP,
    }
)
"""Relations that state technical overlap of any extent."""


def _sorted(comparisons: list[ClaimCandidateComparison]) -> list[ClaimCandidateComparison]:
    return sorted(comparisons, key=lambda c: str(c.comparison_id))


def claim_coverage(
    comparisons: list[ClaimCandidateComparison], profiles: dict[UUID, CandidateComparisonProfile]
) -> ClaimComparisonCoverage:
    per_type = []
    for candidate_type in CANDIDATE_TYPE_ORDER:
        mine = [c for c in comparisons if c.candidate_ref.candidate_type is candidate_type]
        verified = [c for c in mine if c.verified]
        ineligible = [c for c in mine if c.status is ComparisonStatus.NOT_COMPARED_INELIGIBLE]
        blocked = [
            c for c in ineligible
            if profiles[c.profile_id].eligibility is CandidateEligibility.BLOCKED_SOURCE_QUALITY
        ]
        units = {c.independence_unit.unit_key for c in verified}
        independent = {c.independence_unit.corroboration_key for c in verified} - {None}
        per_type.append(TypeCoverage(
            candidate_type=candidate_type,
            available=len(mine),
            compared=len(verified),
            omitted_by_limit=sum(1 for c in mine if c.status is ComparisonStatus.OMITTED_BY_LIMIT),
            blocked_by_source_quality=len(blocked),
            not_comparable=len(ineligible) - len(blocked),
            failed=sum(1 for c in mine if c.status in FAILED_COMPARISON_STATUSES),
            not_executed=sum(1 for c in mine if c.status is ComparisonStatus.NOT_EXECUTED_NO_PROVIDER),
            units_compared=len(units),
            independent_units_compared=len(independent),
        ))
    compared = sum(t.compared for t in per_type)
    flags = []
    if any(t.failed for t in per_type):
        flags.append(ComparisonCoverageStatus.PARTIAL_ERROR)
    if any(t.omitted_by_limit for t in per_type):
        flags.append(ComparisonCoverageStatus.PARTIAL_COMPARISON_LIMIT)
    if any(t.not_comparable or t.blocked_by_source_quality for t in per_type):
        flags.append(ComparisonCoverageStatus.PARTIAL_SOURCE_UNAVAILABLE)
    if compared == 0 or any(t.not_executed for t in per_type):
        status = ComparisonCoverageStatus.NOT_EXECUTED
    elif flags:
        status = flags[0]
    else:
        status = ComparisonCoverageStatus.COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS
    return ClaimComparisonCoverage(status=status, flags=flags, per_type=per_type)


def feature_differentiations(
    inventory: ComparisonFeatureInventory, verified: list[ClaimCandidateComparison]
) -> list[FeatureDifferentiation]:
    result = []
    for feature in inventory.features:
        buckets: dict[str, list[UUID]] = {"d": [], "p": [], "n": [], "u": []}
        for comparison in verified:
            record = comparison.record(feature.feature_id)
            relation = record.relation if record else FeatureRelation.NOT_COMPARABLE
            if relation is FeatureRelation.DISCLOSED:
                buckets["d"].append(comparison.comparison_id)
            elif relation is FeatureRelation.PARTIALLY_DISCLOSED:
                buckets["p"].append(comparison.comparison_id)
            elif relation is FeatureRelation.NOT_DISCLOSED or (
                relation is FeatureRelation.RELATED_CONTEXT
                and feature.feature_type in comparison.complete_material_feature_types
            ):
                buckets["n"].append(comparison.comparison_id)
            else:
                buckets["u"].append(comparison.comparison_id)
        result.append(FeatureDifferentiation(
            feature_id=feature.feature_id,
            feature_type=feature.feature_type,
            claim_text=feature.text,
            status=differentiation_status(*(bool(buckets[k]) for k in "dpnu")),
            disclosing_comparison_ids=buckets["d"],
            partial_comparison_ids=buckets["p"],
            negative_comparison_ids=buckets["n"],
            unresolved_comparison_ids=buckets["u"],
        ))
    return result


def type_summaries(verified: list[ClaimCandidateComparison]) -> list[TypeOverlapSummary]:
    summaries = []
    for candidate_type in CANDIDATE_TYPE_ORDER:
        mine = [c for c in verified if c.candidate_ref.candidate_type is candidate_type]
        full = [c for c in mine if c.full_claim_relation is FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP]
        full_units = {c.independence_unit.unit_key for c in full}
        partial_units = {
            c.independence_unit.unit_key for c in mine
            if c.full_claim_relation is FullClaimRelation.PARTIAL_CLAIM_TECHNICAL_OVERLAP
        } - full_units
        component_units = {
            c.independence_unit.unit_key for c in mine
            if c.full_claim_relation is FullClaimRelation.COMPONENT_ONLY_OVERLAP
        } - full_units - partial_units
        summaries.append(TypeOverlapSummary(
            candidate_type=candidate_type,
            full_overlap_candidates=len(full),
            full_overlap_units=len(full_units),
            full_overlap_independent_units=len({c.independence_unit.corroboration_key for c in full} - {None}),
            full_overlap_unresolved_correlation_groups=len(
                {c.independence_unit.correlation_group_key for c in full} - {None}
            ),
            partial_overlap_units=len(partial_units),
            component_only_units=len(component_units),
        ))
    return summaries


def chronology_split(overlapping: list[ClaimCandidateComparison]) -> ChronologySplit:
    """Source-type-specific chronology statements; never one generic flag."""
    by_key: dict[str, int] = {}
    for comparison in overlapping:
        key = f"{comparison.candidate_ref.candidate_type.value}:{comparison.chronology_bucket.value}"
        by_key[key] = by_key.get(key, 0) + 1

    def before(candidate_type: CandidateType) -> bool:
        return by_key.get(f"{candidate_type.value}:{ChronologyBucket.BEFORE_CUTOFF.value}", 0) > 0

    return ChronologySplit(
        overlap_by_type_bucket=dict(sorted(by_key.items())),
        patent_overlap_publication_dated_before_cutoff=before(CandidateType.PATENT),
        product_overlap_artifact_dated_before_cutoff=before(CandidateType.PRODUCT),
        oss_overlap_provider_dated_before_cutoff=before(CandidateType.OPEN_SOURCE),
    )


def reporting_for(
    inventory: ComparisonFeatureInventory, coverage: ClaimComparisonCoverage,
    verified: list[ClaimCandidateComparison],
) -> DifferentiationReporting:
    if inventory.mode is InventoryMode.FULL_CLAIM_ONLY:
        return DifferentiationReporting.WITHHELD_FULL_CLAIM_ONLY
    if inventory.completeness is not InventoryCompleteness.COMPLETE:
        return DifferentiationReporting.WITHHELD_INCOMPLETE_INVENTORY
    if not coverage.complete:
        return DifferentiationReporting.WITHHELD_PARTIAL_COVERAGE
    feature_types = {f.feature_type for f in inventory.features}
    if not verified or any(not c.adequate_for(feature_types) for c in verified):
        return DifferentiationReporting.WITHHELD_INADEQUATE_SOURCE_TEXT
    return DifferentiationReporting.STATED_WITHIN_BOUNDS


def synthesize_claim(
    nd_run_id: UUID,
    research_run_id: UUID,
    inventory: ComparisonFeatureInventory,
    comparisons: list[ClaimCandidateComparison],
    profiles: dict[UUID, CandidateComparisonProfile],
    *,
    upstream_search_partial: bool,
) -> ClaimDifferentiationSynthesis:
    comparisons = _sorted(comparisons)
    verified = [c for c in comparisons if c.verified]
    full = [c for c in verified if c.full_claim_relation is FullClaimRelation.FULL_CLAIM_TECHNICAL_OVERLAP]
    overlapping = [c for c in verified if c.full_claim_relation in OVERLAPPING_RELATIONS]
    coverage = claim_coverage(comparisons, profiles)
    differentiations = feature_differentiations(inventory, verified)
    statuses = {d.status for d in differentiations}
    reporting = reporting_for(inventory, coverage, verified)
    stated = reporting is DifferentiationReporting.STATED_WITHIN_BOUNDS
    overlap = statuses & {
        DifferentiationStatus.DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES,
        DifferentiationStatus.PARTIALLY_DISCLOSED,
    }
    not_found = DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT

    blocked_all = bool(comparisons) and all(
        profiles[c.profile_id].eligibility is CandidateEligibility.BLOCKED_SOURCE_QUALITY for c in comparisons
    )
    if blocked_all:
        posture, reason = ClaimTechnicalPosture.BLOCKED_SOURCE_QUALITY, PostureReason.ALL_LINKED_CANDIDATES_BLOCKED_BY_SOURCE_QUALITY
    elif full:
        posture, reason = ClaimTechnicalPosture.MATERIAL_TECHNICAL_OVERLAP_FOUND, PostureReason.SINGLE_CANDIDATE_DISCLOSES_FULL_COMBINATION
    elif not verified:
        posture = ClaimTechnicalPosture.INSUFFICIENT_COMPARISON_EVIDENCE
        reason = PostureReason.NO_CANDIDATES_DISCOVERED if not comparisons else PostureReason.NO_VERIFIED_COMPARISON
    elif overlap:
        if stated and not_found in statuses:
            posture, reason = ClaimTechnicalPosture.MIXED_OVERLAP_AND_DIFFERENTIATION, PostureReason.OVERLAP_WITH_DIFFERENTIATING_FEATURES
        else:
            posture, reason = ClaimTechnicalPosture.PARTIAL_TECHNICAL_OVERLAP_ONLY, PostureReason.OVERLAP_WITHOUT_FULL_COMBINATION
    elif stated and statuses == {not_found}:
        posture, reason = ClaimTechnicalPosture.NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS, PostureReason.NO_OVERLAP_IN_ADEQUATE_COMPLETE_COMPARISON
    else:
        posture, reason = ClaimTechnicalPosture.INSUFFICIENT_COMPARISON_EVIDENCE, PostureReason.NO_OVERLAP_BUT_COMPARISON_NOT_ADEQUATE

    linked_types = {c.candidate_ref.candidate_type for c in comparisons}
    limitations = list(UNIVERSAL_SYNTHESIS_LIMITATIONS)

    def add(flag: bool, limitation: SynthesisLimitation) -> None:
        if flag and limitation not in limitations:
            limitations.append(limitation)

    feature_types = {f.feature_type for f in inventory.features}
    add(any(not c.adequate_for(feature_types) or c.compared_text_bounded for c in verified) or not verified,
        SynthesisLimitation.SOURCE_TEXT_MAY_BE_INCOMPLETE)
    add(CandidateType.PRODUCT in linked_types, SynthesisLimitation.PRODUCT_HISTORICAL_AVAILABILITY_MAY_BE_UNKNOWN)
    add(CandidateType.OPEN_SOURCE in linked_types, SynthesisLimitation.OSS_HISTORICAL_VISIBILITY_MAY_BE_UNKNOWN)
    add(CandidateType.PATENT in linked_types, SynthesisLimitation.PATENT_FAMILY_GROUPING_IS_NOT_LEGAL_EQUIVALENCE)
    add(any(c.independence_unit.unit_kind is IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED for c in comparisons),
        SynthesisLimitation.PATENT_FAMILY_UNRESOLVED_NOT_INDEPENDENT)
    add(any(c.candidate_ref.candidate_type is CandidateType.PRODUCT
            and c.independence_unit.unit_kind is not IndependenceUnitKind.PRODUCT_STRONG_ENTITY for c in comparisons),
        SynthesisLimitation.PRODUCT_IDENTITY_MAY_BE_UNRESOLVED)
    add(any(c.independence_unit.correlation_group_key is not None for c in comparisons),
        SynthesisLimitation.PRODUCT_UNRESOLVED_CORRELATION_PRESENT)
    add(any(c.candidate_ref.candidate_type is CandidateType.PRODUCT
            and c.chronology_bucket is not ChronologyBucket.NO_CUTOFF for c in verified),
        SynthesisLimitation.PRODUCT_DATE_IS_SOURCE_REPORTED_NOT_HISTORICAL_PROOF)
    add(any(c.candidate_ref.candidate_type is CandidateType.OPEN_SOURCE
            and c.chronology_bucket is not ChronologyBucket.NO_CUTOFF for c in verified),
        SynthesisLimitation.OSS_DATE_IS_NOT_PUBLIC_VISIBILITY_PROOF)
    add(any(c.candidate_ref.candidate_type is CandidateType.OPEN_SOURCE
            and (not c.independence_unit.counts_as_independent
                 or profiles[c.profile_id].quality.identity_status != "ROOT_REPOSITORY") for c in comparisons),
        SynthesisLimitation.FORKS_MAY_MATERIALLY_DIVERGE)
    add(inventory.mode is InventoryMode.FULL_CLAIM_ONLY, SynthesisLimitation.COMPONENT_LEVEL_COMPARISON_UNAVAILABLE)
    add(inventory.completeness is not InventoryCompleteness.COMPLETE, SynthesisLimitation.FEATURE_INVENTORY_INCOMPLETE)
    add(not coverage.complete, SynthesisLimitation.COMPARISON_COVERAGE_PARTIAL)
    add(upstream_search_partial, SynthesisLimitation.UPSTREAM_SEARCH_PARTIAL)
    add(any(c.chronology_bucket in (ChronologyBucket.ON_CUTOFF, ChronologyBucket.AFTER_CUTOFF) for c in overlapping),
        SynthesisLimitation.POST_CUTOFF_OVERLAP_IS_NOT_PRE_CUTOFF_DISCLOSURE)
    add(any(c.chronology_bucket is ChronologyBucket.DATE_UNKNOWN for c in verified),
        SynthesisLimitation.CHRONOLOGY_UNKNOWN_FOR_SOME_CANDIDATES)
    add(not comparisons, SynthesisLimitation.NO_CANDIDATES_DISCOVERED)

    return ClaimDifferentiationSynthesis(
        synthesis_id=novelty_id(nd_run_id, "synthesis", inventory.claim_id),
        nd_run_id=nd_run_id,
        research_run_id=research_run_id,
        claim_id=inventory.claim_id,
        inventory_id=inventory.inventory_id,
        posture=posture,
        posture_reasons=[reason],
        differentiation_reporting=reporting,
        feature_differentiations=differentiations,
        coverage=coverage,
        type_summaries=type_summaries(verified),
        chronology=chronology_split(overlapping),
        compared_comparison_ids=[c.comparison_id for c in verified],
        full_overlap_comparison_ids=[c.comparison_id for c in full],
        limitations=limitations,
    )


def synthesize_project(
    nd_run_id: UUID,
    syntheses: list[ClaimDifferentiationSynthesis],
    comparisons: list[ClaimCandidateComparison],
) -> ProjectDifferentiationSummary:
    syntheses = sorted(syntheses, key=lambda s: s.claim_id)
    counts: dict[str, int] = {}
    for s in syntheses:
        counts[s.posture.value] = counts.get(s.posture.value, 0) + 1

    def claims(*postures: ClaimTechnicalPosture) -> list[str]:
        return [s.claim_id for s in syntheses if s.posture in postures]

    not_found = DifferentiationStatus.NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT
    differentiating = [
        s.claim_id for s in syntheses
        if s.differentiation_reporting is DifferentiationReporting.STATED_WITHIN_BOUNDS
        and any(f.status is not_found for f in s.feature_differentiations)
    ]
    texts: dict[str, set[str]] = {}
    for s in syntheses:
        if s.differentiation_reporting is not DifferentiationReporting.STATED_WITHIN_BOUNDS:
            continue
        for f in s.feature_differentiations:
            if f.status is not_found and f.feature_type.value != "COMBINATION":
                texts.setdefault(f.claim_text.casefold(), set()).add(s.claim_id)
    recurring = sorted(text for text, owners in texts.items() if len(owners) >= 2)

    per_type = []
    for candidate_type in CANDIDATE_TYPE_ORDER:
        rows = [s.coverage.for_type(candidate_type) for s in syntheses]
        per_type.append(TypeCoverage(
            candidate_type=candidate_type,
            available=sum(r.available for r in rows),
            compared=sum(r.compared for r in rows),
            omitted_by_limit=sum(r.omitted_by_limit for r in rows),
            blocked_by_source_quality=sum(r.blocked_by_source_quality for r in rows),
            not_comparable=sum(r.not_comparable for r in rows),
            failed=sum(r.failed for r in rows),
            not_executed=sum(r.not_executed for r in rows),
            units_compared=sum(r.units_compared for r in rows),
            independent_units_compared=sum(r.independent_units_compared for r in rows),
        ))
    verified = [c for c in comparisons if c.verified]
    chronology: dict[str, int] = {}
    types: dict[str, int] = {}
    for c in verified:
        chronology[c.chronology_bucket.value] = chronology.get(c.chronology_bucket.value, 0) + 1
        types[c.candidate_ref.candidate_type.value] = types.get(c.candidate_ref.candidate_type.value, 0) + 1
    return ProjectDifferentiationSummary(
        nd_run_id=nd_run_id,
        assessed_claim_count=len(syntheses),
        posture_counts=dict(sorted(counts.items())),
        claims_with_material_overlap=claims(ClaimTechnicalPosture.MATERIAL_TECHNICAL_OVERLAP_FOUND),
        claims_with_partial_overlap=claims(
            ClaimTechnicalPosture.PARTIAL_TECHNICAL_OVERLAP_ONLY,
            ClaimTechnicalPosture.MIXED_OVERLAP_AND_DIFFERENTIATION,
        ),
        claims_with_no_material_overlap_within_bounds=claims(
            ClaimTechnicalPosture.NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS
        ),
        claims_blocked_or_insufficient=claims(
            ClaimTechnicalPosture.BLOCKED_SOURCE_QUALITY,
            ClaimTechnicalPosture.INSUFFICIENT_COMPARISON_EVIDENCE,
        ),
        claims_with_differentiating_features=differentiating,
        recurring_differentiating_feature_texts=recurring,
        source_type_coverage=per_type,
        chronology_distribution=dict(sorted(chronology.items())),
        candidate_type_distribution=dict(sorted(types.items())),
        limitations=list(PROJECT_SUMMARY_LIMITATIONS),
    )


__all__ = [
    "chronology_split",
    "claim_coverage",
    "feature_differentiations",
    "reporting_for",
    "synthesize_claim",
    "synthesize_project",
    "type_summaries",
]
