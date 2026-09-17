"""The versioned deterministic sufficiency policy -- Phase 2E (section 14).

``SUFFICIENCY-POLICY-V1``, stated in full so it can be reviewed as a policy
rather than reverse-engineered from code.

**Per material claim component.** A component is *adequately evidenced* only by
direct coverage from eligible independence groups:

1. ``SUPPORTED``     -- at least one eligible independence group contributes a
   direct ``SUPPORTS`` judgement at that exact anchor, and no eligible group
   contributes a direct ``CONTRADICTS`` judgement there.
2. ``CONTRADICTED``  -- the mirror image.
3. ``CONTESTED``     -- eligible groups contribute direct support *and* direct
   contradiction at the same component. The conflict is preserved, never
   averaged (section 12).
4. ``PARTIAL_*``     -- only partial contributions (``PARTIALLY_SUPPORTS``,
   ``PARTIALLY_CONTRADICTS``, ``MIXED``) reach the component. Partial coverage
   alone can never make a component adequately evidenced (section 14).
5. ``UNRESOLVED_RELEVANT`` / ``CONTEXT_ONLY`` / ``NO_EVIDENCE`` -- relevant but
   undecided, contextual only, or nothing at all.
6. ``BLOCKED_SOURCE_QUALITY`` -- every group that reached this component with a
   *direct* relation was disqualified by retraction or traceability.

Corroboration is reported, not scored: one eligible direct group is
``SINGLE_GROUP``, two or more is ``MULTIPLE_GROUPS``. A single group satisfies
this policy's bar for component adequacy, and the fact that it stood alone
survives into the assessment as ``SINGLE_INDEPENDENT_SOURCE_ONLY`` -- rather
than the alternative of refusing single-source sufficiency and thereby making
every honest single-study finding indistinguishable from no finding at all.
A later scoring phase can weigh that reason code; this phase must not hide it.

**Per claim.** Material components are the distinct exact anchors Phase 2D
produced for that claim. A claim with no anchors at all has no component to
cover, which is why it can never reach ``SUFFICIENT_SUPPORT``.

1. ``BLOCKED_SOURCE_QUALITY``  -- direct alignments exist, but every one of them
   was disqualified.
2. ``CONTESTED``               -- some component is ``CONTESTED``, or one
   component is ``SUPPORTED`` while another is ``CONTRADICTED``.
3. ``SUFFICIENT_SUPPORT``      -- every material component is ``SUPPORTED``.
4. ``SUFFICIENT_CONTRADICTION``-- every material component is ``CONTRADICTED``.
5. ``PARTIALLY_SUFFICIENT``    -- at least one material component is adequately
   evidenced and at least one is not.
6. ``NO_DIRECT_EVIDENCE``      -- no direct supporting/contradicting alignment
   is available at all. Contextual, insufficient and not-relevant material may
   exist.
7. ``INSUFFICIENT_EVIDENCE``   -- relevant direct-ish evidence exists but meets
   none of the bars above.

Unknown never helps. An unknown retraction status does not disqualify evidence,
and it does not clear it either: the evidence contributes, carrying
``UNKNOWN_RETRACTION_STATUS`` on the assessment so the gap is visible (section
19). The same holds for unknown publication status.

Retracted evidence stays in the record as ``DISQUALIFIED_RETRACTED``, is never
counted as positive corroboration, and is never deleted (section 20).
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.claim_sufficiency import (
    ADEQUATELY_EVIDENCED_COVERAGE,
    ClaimComponentSufficiency,
    ComponentCoverage,
    ContentScopeLimitation,
    CorroborationLevel,
    EvidenceContributionClass,
    EvidenceLimitation,
    EvidenceWeightProfile,
    PublicationStatus,
    QualityDimension,
    RetractionStatus,
    SufficiencyBlocker,
    SufficiencyOutcome,
    SufficiencyReasonCode,
    TraceabilityStatus,
)
from src.schemas.claim_sufficiency import DIRECT_RELATIONS

SCOPE_STRENGTH: dict[ContentScopeLimitation, int] = {
    ContentScopeLimitation.ABSTRACT_ONLY: 0,
    ContentScopeLimitation.PARTIAL_TEXT: 1,
    ContentScopeLimitation.FULL_TEXT: 2,
}


def _sorted_unique(values: list[UUID]) -> list[UUID]:
    """Stable, deduplicated group ids -- identical inputs, identical output."""
    return sorted(set(values), key=str)


# ---------------------------------------------------------------------------
# Component coverage
# ---------------------------------------------------------------------------


def component_sufficiency(
    claim_id: str,
    component_key: tuple[int, int, str],
    profiles: list[EvidenceWeightProfile],
) -> ClaimComponentSufficiency:
    """Aggregate every profile touching one exact component anchor.

    Group ids, not profile counts, are collected on every axis. Two excerpts
    from one paper land in the same group id and therefore collapse to one
    entry, which is where ``More excerpts != More independent sources`` becomes
    arithmetic rather than aspiration.
    """
    start, end, text = component_key
    supporting: list[UUID] = []
    contradicting: list[UUID] = []
    partial_supporting: list[UUID] = []
    partial_contradicting: list[UUID] = []
    contextual: list[UUID] = []
    unresolved: list[UUID] = []
    disqualified: list[UUID] = []
    direct_relation_seen = False

    for profile in profiles:
        contribution = next(
            (c for c in profile.component_contributions if c.component_key == component_key),
            None,
        )
        if contribution is None:
            continue
        group_id = profile.independence_group_id

        if profile.contribution in (
            EvidenceContributionClass.DISQUALIFIED_RETRACTED,
            EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE,
        ):
            disqualified.append(group_id)
            if profile.relation in DIRECT_RELATIONS:
                direct_relation_seen = True
            continue

        if profile.contribution is EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT:
            direct_relation_seen = True
            if contribution.supports:
                supporting.append(group_id)
        elif (
            profile.contribution
            is EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION
        ):
            direct_relation_seen = True
            if contribution.contradicts:
                contradicting.append(group_id)
        elif profile.contribution in (
            EvidenceContributionClass.ELIGIBLE_PARTIAL_SUPPORT,
            EvidenceContributionClass.ELIGIBLE_PARTIAL_CONTRADICTION,
            EvidenceContributionClass.ELIGIBLE_MIXED,
        ):
            if contribution.supports:
                partial_supporting.append(group_id)
            if contribution.contradicts:
                partial_contradicting.append(group_id)
            if contribution.contextual:
                contextual.append(group_id)
            if contribution.unresolved:
                unresolved.append(group_id)
        elif profile.contribution is EvidenceContributionClass.CONTEXT_ONLY:
            contextual.append(group_id)
        elif profile.contribution is EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT:
            unresolved.append(group_id)
        # NOT_RELEVANT contributes to nothing, by definition (section 10).

    supporting = _sorted_unique(supporting)
    contradicting = _sorted_unique(contradicting)
    partial_supporting = _sorted_unique(partial_supporting)
    partial_contradicting = _sorted_unique(partial_contradicting)
    contextual = _sorted_unique(contextual)
    unresolved = _sorted_unique(unresolved)
    disqualified = _sorted_unique(disqualified)

    reasons: list[SufficiencyReasonCode] = []
    if supporting and contradicting:
        coverage = ComponentCoverage.CONTESTED
        reasons.append(SufficiencyReasonCode.SUPPORT_AND_CONTRADICTION_PRESENT)
    elif supporting:
        coverage = ComponentCoverage.SUPPORTED
    elif contradicting:
        coverage = ComponentCoverage.CONTRADICTED
        reasons.append(SufficiencyReasonCode.MATERIAL_CONTRADICTION_PRESENT)
    elif partial_supporting and partial_contradicting:
        coverage = ComponentCoverage.PARTIAL_MIXED
        reasons.append(SufficiencyReasonCode.SUPPORT_AND_CONTRADICTION_PRESENT)
    elif partial_supporting:
        coverage = ComponentCoverage.PARTIAL_SUPPORT_ONLY
        reasons.append(SufficiencyReasonCode.PARTIAL_SUPPORT_ONLY)
    elif partial_contradicting:
        coverage = ComponentCoverage.PARTIAL_CONTRADICTION_ONLY
        reasons.append(SufficiencyReasonCode.PARTIAL_CONTRADICTION_ONLY)
    elif disqualified and direct_relation_seen:
        coverage = ComponentCoverage.BLOCKED_SOURCE_QUALITY
        reasons.append(SufficiencyReasonCode.ALL_DIRECT_EVIDENCE_DISQUALIFIED)
    elif unresolved:
        coverage = ComponentCoverage.UNRESOLVED_RELEVANT
        reasons.append(SufficiencyReasonCode.RELEVANT_BUT_INSUFFICIENT)
    elif contextual:
        coverage = ComponentCoverage.CONTEXT_ONLY
        reasons.append(SufficiencyReasonCode.CONTEXT_ONLY_AVAILABLE)
    else:
        coverage = ComponentCoverage.NO_EVIDENCE
        reasons.append(SufficiencyReasonCode.NO_DIRECT_ALIGNMENT)

    direct_groups = supporting or contradicting
    if coverage in ADEQUATELY_EVIDENCED_COVERAGE:
        if len(direct_groups) == 1:
            corroboration = CorroborationLevel.SINGLE_GROUP
            reasons.append(SufficiencyReasonCode.SINGLE_INDEPENDENT_SOURCE_ONLY)
        else:
            corroboration = CorroborationLevel.MULTIPLE_GROUPS
            reasons.append(
                SufficiencyReasonCode.MULTIPLE_INDEPENDENT_SUPPORTING_SOURCES
                if supporting
                else SufficiencyReasonCode.MULTIPLE_INDEPENDENT_CONTRADICTING_SOURCES
            )
    else:
        corroboration = CorroborationLevel.NONE

    return ClaimComponentSufficiency(
        claim_id=claim_id,
        anchor_start=start,
        anchor_end=end,
        anchor_text=text,
        coverage=coverage,
        corroboration=corroboration,
        supporting_group_ids=supporting,
        contradicting_group_ids=contradicting,
        partial_supporting_group_ids=partial_supporting,
        partial_contradicting_group_ids=partial_contradicting,
        contextual_group_ids=contextual,
        unresolved_group_ids=unresolved,
        disqualified_group_ids=disqualified,
        reason_codes=list(dict.fromkeys(reasons)),
    )


def material_component_keys(
    profiles: list[EvidenceWeightProfile],
) -> list[tuple[int, int, str]]:
    """The distinct exact claim-component anchors Phase 2D identified.

    Sorted by span so the component order of an assessment is stable across
    reruns. Anchors are taken verbatim from Phase 2D, never re-derived: they
    were already proven to satisfy ``claim.claim[start:end] == anchor_text``
    there, and re-deriving them here would be a second, weaker source of truth.
    """
    keys = {
        contribution.component_key
        for profile in profiles
        for contribution in profile.component_contributions
    }
    return sorted(keys)


# ---------------------------------------------------------------------------
# Claim outcome
# ---------------------------------------------------------------------------


def _quality_reasons(profiles: list[EvidenceWeightProfile]) -> list[SufficiencyReasonCode]:
    reasons: list[SufficiencyReasonCode] = []
    if any(p.retraction_status is RetractionStatus.RETRACTED for p in profiles):
        reasons.append(SufficiencyReasonCode.RETRACTED_SOURCE_EXCLUDED)
    if any(p.publication_status is PublicationStatus.PREPRINT for p in profiles):
        reasons.append(SufficiencyReasonCode.PREPRINT_LIMITATION)
    if any(p.traceability is not TraceabilityStatus.TRACEABLE for p in profiles):
        reasons.append(SufficiencyReasonCode.TRACEABILITY_FAILURE)
    if any(
        p.content_scope is ContentScopeLimitation.ABSTRACT_ONLY
        and p.is_eligible
        for p in profiles
    ):
        reasons.append(SufficiencyReasonCode.ABSTRACT_ONLY_SCOPE)
    if any(p.publication_status is PublicationStatus.UNKNOWN for p in profiles):
        reasons.append(SufficiencyReasonCode.UNKNOWN_PUBLICATION_STATUS)
    if any(p.retraction_status is RetractionStatus.UNKNOWN for p in profiles):
        reasons.append(SufficiencyReasonCode.UNKNOWN_RETRACTION_STATUS)
    return reasons


def duplicate_collapse_occurred(profiles: list[EvidenceWeightProfile]) -> bool:
    """True when more evidence items than groups reached this claim.

    Reported as ``INDEPENDENCE_COLLAPSED_DUPLICATES`` so a reader can see that
    the duplicate control actually fired, rather than having to trust that it
    would have.
    """
    groups = {p.independence_group_id for p in profiles if p.is_eligible}
    items = {p.evidence_id for p in profiles if p.is_eligible}
    return len(items) > len(groups)


def decide_outcome(
    components: list[ClaimComponentSufficiency],
    profiles: list[EvidenceWeightProfile],
    *,
    universe_complete: bool = True,
) -> tuple[SufficiencyOutcome, list[SufficiencyBlocker], list[SufficiencyReasonCode]]:
    """Apply ``SUFFICIENCY-POLICY-V1`` to one claim's aggregated coverage."""
    blockers: list[SufficiencyBlocker] = []
    reasons: list[SufficiencyReasonCode] = []

    direct_profiles = [p for p in profiles if p.relation in DIRECT_RELATIONS]
    direct_eligible = [
        p
        for p in direct_profiles
        if p.contribution
        in (
            EvidenceContributionClass.ELIGIBLE_DIRECT_SUPPORT,
            EvidenceContributionClass.ELIGIBLE_DIRECT_CONTRADICTION,
        )
    ]

    if not universe_complete:
        blockers.append(SufficiencyBlocker.INCOMPLETE_ALIGNMENT_UNIVERSE)
        reasons.append(SufficiencyReasonCode.INCOMPLETE_ALIGNMENT_UNIVERSE)

    # Direct evidence existed but nothing survived quality: that is a distinct
    # posture from having found nothing (section 12).
    if direct_profiles and not direct_eligible:
        retracted = all(
            p.contribution is EvidenceContributionClass.DISQUALIFIED_RETRACTED
            for p in direct_profiles
        )
        untraceable = all(
            p.contribution is EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
            for p in direct_profiles
        )
        blockers.append(
            SufficiencyBlocker.ALL_DIRECT_EVIDENCE_RETRACTED
            if retracted
            else SufficiencyBlocker.ALL_DIRECT_EVIDENCE_UNTRACEABLE
            if untraceable
            else SufficiencyBlocker.ALL_DIRECT_EVIDENCE_DISQUALIFIED
        )
        reasons.append(SufficiencyReasonCode.ALL_DIRECT_EVIDENCE_DISQUALIFIED)
        reasons.extend(_quality_reasons(profiles))
        return (
            SufficiencyOutcome.BLOCKED_SOURCE_QUALITY,
            blockers,
            list(dict.fromkeys(reasons)),
        )

    adequate = [c for c in components if c.is_adequately_evidenced]
    supported = [c for c in components if c.coverage is ComponentCoverage.SUPPORTED]
    contradicted = [
        c for c in components if c.coverage is ComponentCoverage.CONTRADICTED
    ]
    contested = [c for c in components if c.coverage is ComponentCoverage.CONTESTED]

    if components and len(adequate) == len(components):
        reasons.append(SufficiencyReasonCode.FULL_COMPONENT_COVERAGE)
    elif adequate:
        reasons.append(SufficiencyReasonCode.PARTIAL_COMPONENT_COVERAGE)
    else:
        reasons.append(SufficiencyReasonCode.NO_COMPONENT_COVERAGE)

    if duplicate_collapse_occurred(profiles):
        reasons.append(SufficiencyReasonCode.INDEPENDENCE_COLLAPSED_DUPLICATES)
    for component in components:
        reasons.extend(component.reason_codes)
    reasons.extend(_quality_reasons(profiles))
    reasons = list(dict.fromkeys(reasons))

    if contested or (supported and contradicted):
        return SufficiencyOutcome.CONTESTED, blockers, reasons

    if components and len(supported) == len(components):
        outcome = (
            SufficiencyOutcome.PARTIALLY_SUFFICIENT
            if not universe_complete
            else SufficiencyOutcome.SUFFICIENT_SUPPORT
        )
        return outcome, blockers, reasons
    if components and len(contradicted) == len(components):
        outcome = (
            SufficiencyOutcome.PARTIALLY_SUFFICIENT
            if not universe_complete
            else SufficiencyOutcome.SUFFICIENT_CONTRADICTION
        )
        return outcome, blockers, reasons
    if adequate:
        return SufficiencyOutcome.PARTIALLY_SUFFICIENT, blockers, reasons

    if not direct_eligible:
        if not profiles or all(
            p.contribution
            in (
                EvidenceContributionClass.NOT_RELEVANT,
                EvidenceContributionClass.CONTEXT_ONLY,
                EvidenceContributionClass.RELEVANT_BUT_INSUFFICIENT,
            )
            for p in profiles
        ):
            reasons.append(SufficiencyReasonCode.NO_DIRECT_ALIGNMENT)
            return (
                SufficiencyOutcome.NO_DIRECT_EVIDENCE,
                blockers,
                list(dict.fromkeys(reasons)),
            )

    return SufficiencyOutcome.INSUFFICIENT_EVIDENCE, blockers, reasons


def content_scope_ceiling(
    profiles: list[EvidenceWeightProfile],
) -> ContentScopeLimitation | None:
    """The strongest scope any *contributing* evidence had.

    ``None`` when nothing contributed. Never defaults to ``FULL_TEXT``: claiming
    full-text verification nothing provided is exactly the overreach ADR-013
    exists to prevent (section 21).
    """
    eligible = [p.content_scope for p in profiles if p.is_eligible]
    if not eligible:
        return None
    return max(eligible, key=lambda scope: SCOPE_STRENGTH[scope])


def aggregate_limitations(
    profiles: list[EvidenceWeightProfile],
) -> list[EvidenceLimitation]:
    """The union of every contributing item's caveats, in enum order."""
    present = {
        limitation for profile in profiles for limitation in profile.limitations
    }
    return [limitation for limitation in EvidenceLimitation if limitation in present]


def aggregate_unknowns(
    profiles: list[EvidenceWeightProfile],
) -> list[QualityDimension]:
    """Every dimension no contributing source states, in enum order."""
    present = {
        dimension for profile in profiles for dimension in profile.unknown_dimensions
    }
    return [dimension for dimension in QualityDimension if dimension in present]


__all__ = [
    "SCOPE_STRENGTH",
    "aggregate_limitations",
    "aggregate_unknowns",
    "component_sufficiency",
    "content_scope_ceiling",
    "decide_outcome",
    "duplicate_collapse_occurred",
    "material_component_keys",
]
