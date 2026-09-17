"""Evidence weight profiles -- Phase 2E (section 7, section 15).

One profile per verified claim/evidence pair. The profile is the audit unit:
it records the Phase 2D relation *as given*, the deterministically derived
contribution class, per-component coverage at exact anchors, and every quality
dimension and limitation separately.

The classification pipeline is strictly one-directional. The Phase 2D relation
sets a starting class, and quality can only ever *downgrade* it to a
``DISQUALIFIED_*`` value. Nothing here can promote ``CONTEXT_ONLY`` into weak
support or ``INSUFFICIENT`` into partial support (section 10).
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.claim import ClaimRecord
from src.schemas.claim_alignment import ClaimEvidenceAlignment, ComponentJudgment
from src.schemas.claim_sufficiency import (
    DIRECT_RELATIONS,
    RELATION_TO_CONTRIBUTION,
    SCOPE_TO_LIMITATION,
    ComponentContribution,
    ContentScopeLimitation,
    EvidenceContributionClass,
    EvidenceLimitation,
    EvidenceWeightProfile,
    IndependenceGroup,
    PublicationStatus,
    QualityDimension,
    RetractionStatus,
    TraceabilityStatus,
    UNRESOLVED_CANONICAL_IDENTITY,
    UNRESOLVED_GROUP_ID,
    UNRESOLVED_SOURCE_ID,
    weight_profile_id,
)
from src.schemas.evidence_extraction import ExtractedEvidence


def resolve_traceability(
    alignment: ClaimEvidenceAlignment,
    claim: ClaimRecord | None,
    evidence: ExtractedEvidence | None,
    group: IndependenceGroup | None,
    *,
    research_run_id: UUID,
    alignment_run_id: UUID | None,
) -> TraceabilityStatus:
    """Prove the whole source -> evidence -> alignment -> claim chain resolves.

    Checked in the order a reader would ask it, and the first failure is
    reported rather than a generic one: "the evidence is from another run" and
    "the source never resolved" are different audit findings.

    The evidence content hash is re-compared against the hash Phase 2D recorded
    on the alignment. A mismatch means the evidence changed under an alignment
    that was verified against different bytes, which makes the alignment's
    anchor judgement unverifiable -- so the pair is untraceable rather than
    silently re-blessed.
    """
    if alignment.research_run_id != research_run_id:
        return TraceabilityStatus.ALIGNMENT_NOT_IN_RUN
    if alignment_run_id is not None and alignment.alignment_run_id != alignment_run_id:
        return TraceabilityStatus.ALIGNMENT_NOT_IN_RUN
    if claim is None:
        return TraceabilityStatus.CLAIM_NOT_RESOLVABLE
    if evidence is None or evidence.research_run_id != research_run_id:
        return TraceabilityStatus.EVIDENCE_NOT_IN_RUN
    if evidence.content_hash != alignment.evidence_content_hash:
        return TraceabilityStatus.EVIDENCE_HASH_MISMATCH
    if group is None:
        return TraceabilityStatus.SOURCE_NOT_RESOLVABLE
    # Every claim anchor is re-sliced from the claim itself. Phase 2D proved
    # this already, and Phase 2E.1 proves it again rather than assuming the
    # upstream verification held: an anchor carrying text the claim does not
    # contain is invented claim text, and a judgement made at an anchor that
    # does not exist cannot be audited. Re-checking also stops a fabricated
    # anchor whose *span* happens to coincide with a real component from
    # vouching for that component (ADR-016).
    for component in alignment.components:
        anchor = component.anchor
        if anchor.claim_id != claim.claim_id:
            return TraceabilityStatus.CLAIM_ANCHOR_NOT_VERIFIABLE
        if anchor.end > len(claim.claim) or (
            claim.claim[anchor.start : anchor.end] != anchor.text
        ):
            return TraceabilityStatus.CLAIM_ANCHOR_NOT_VERIFIABLE
    return TraceabilityStatus.TRACEABLE


def classify_contribution(
    alignment: ClaimEvidenceAlignment,
    traceability: TraceabilityStatus,
    retraction: RetractionStatus,
) -> EvidenceContributionClass:
    """The bounded contribution class, derived only from structured facts.

    Order matters and is itself the policy: traceability is checked before
    retraction, because evidence we cannot trace is not evidence whose
    retraction status we can meaningfully report. Retraction is then checked
    before the relation, so a retracted paper that Phase 2D classified as
    ``SUPPORTS`` can never leave this function as a supporting class.
    """
    if traceability is not TraceabilityStatus.TRACEABLE:
        return EvidenceContributionClass.DISQUALIFIED_UNTRACEABLE
    if retraction is RetractionStatus.RETRACTED:
        return EvidenceContributionClass.DISQUALIFIED_RETRACTED
    return RELATION_TO_CONTRIBUTION[alignment.relation]


def component_contributions(
    alignment: ClaimEvidenceAlignment,
) -> list[ComponentContribution]:
    """Per-anchor coverage carried over from Phase 2D, unchanged.

    ``direct`` is true only when the *pair* relation is direct. A SUPPORTS
    component judgement inside a ``PARTIALLY_SUPPORTS`` or ``MIXED`` pair is
    partial coverage: the evidence itself did not settle the component, which is
    why Phase 2D refused to call the pair a plain SUPPORTS (section 14).
    """
    direct = alignment.relation in DIRECT_RELATIONS
    contributions: list[ComponentContribution] = []
    for component in alignment.components:
        anchor = component.anchor
        contributions.append(
            ComponentContribution(
                anchor_start=anchor.start,
                anchor_end=anchor.end,
                anchor_text=anchor.text,
                supports=component.judgment is ComponentJudgment.SUPPORTS,
                contradicts=component.judgment is ComponentJudgment.CONTRADICTS,
                contextual=component.judgment is ComponentJudgment.CONTEXTUAL,
                unresolved=component.judgment is ComponentJudgment.UNRESOLVED,
                direct=direct,
            )
        )
    return contributions


def evidence_limitations(
    scope: ContentScopeLimitation,
    retraction: RetractionStatus,
    publication: PublicationStatus,
    traceability: TraceabilityStatus,
    provider_observation_count: int,
    publication_year: int | None,
) -> list[EvidenceLimitation]:
    """Every caveat that applies, with none of them cancelling another.

    Limitations accumulate: a retracted preprint read only through its abstract
    carries three. There is no netting step and no numeric penalty, because any
    such arithmetic would be the opaque scalar this phase refuses to build
    (ADR-015).
    """
    limitations: list[EvidenceLimitation] = []
    if scope is ContentScopeLimitation.ABSTRACT_ONLY:
        limitations.append(EvidenceLimitation.ABSTRACT_ONLY_SCOPE)
    elif scope is ContentScopeLimitation.PARTIAL_TEXT:
        limitations.append(EvidenceLimitation.PARTIAL_TEXT_SCOPE)
    if retraction is RetractionStatus.RETRACTED:
        limitations.append(EvidenceLimitation.RETRACTED_SOURCE)
    elif retraction is RetractionStatus.UNKNOWN:
        limitations.append(EvidenceLimitation.RETRACTION_STATUS_UNKNOWN)
    if publication is PublicationStatus.PREPRINT:
        limitations.append(EvidenceLimitation.PREPRINT_NOT_PEER_REVIEWED)
    elif publication is PublicationStatus.UNKNOWN:
        limitations.append(EvidenceLimitation.PUBLICATION_STATUS_UNKNOWN)
    if publication_year is None:
        limitations.append(EvidenceLimitation.PUBLICATION_YEAR_UNKNOWN)
    if provider_observation_count <= 1:
        limitations.append(EvidenceLimitation.SINGLE_PROVIDER_OBSERVATION)
    if traceability is not TraceabilityStatus.TRACEABLE:
        limitations.append(EvidenceLimitation.UNTRACEABLE_CHAIN)
    return limitations


def build_weight_profile(
    alignment: ClaimEvidenceAlignment,
    claim: ClaimRecord | None,
    evidence: ExtractedEvidence | None,
    group: IndependenceGroup | None,
    *,
    research_run_id: UUID,
    sufficiency_run_id: UUID,
    alignment_run_id: UUID | None,
) -> EvidenceWeightProfile:
    """One auditable profile for one verified claim/evidence pair.

    An untraceable pair still gets a profile. Dropping it would make the
    disqualification invisible, and "we looked at this and refused it" has to
    read differently from "we never saw it" (section 20).
    """
    traceability = resolve_traceability(
        alignment,
        claim,
        evidence,
        group,
        research_run_id=research_run_id,
        alignment_run_id=alignment_run_id,
    )
    quality = group.quality if group is not None else None
    retraction = (
        quality.retraction_status if quality is not None else RetractionStatus.UNKNOWN
    )
    publication = (
        quality.publication_status if quality is not None else PublicationStatus.UNKNOWN
    )
    scope = (
        SCOPE_TO_LIMITATION[evidence.evidence_scope]
        if evidence is not None
        else ContentScopeLimitation.ABSTRACT_ONLY
    )
    contribution = classify_contribution(alignment, traceability, retraction)

    unknown: list[QualityDimension] = list(
        quality.unknown_dimensions if quality is not None else []
    )
    if traceability is not TraceabilityStatus.TRACEABLE:
        if QualityDimension.TRACEABILITY not in unknown:
            unknown.append(QualityDimension.TRACEABILITY)

    return EvidenceWeightProfile(
        profile_id=weight_profile_id(
            sufficiency_run_id, alignment.claim_id, alignment.evidence_id
        ),
        research_run_id=research_run_id,
        sufficiency_run_id=sufficiency_run_id,
        claim_id=alignment.claim_id,
        evidence_id=alignment.evidence_id,
        alignment_id=alignment.alignment_id,
        source_id=(
            evidence.source_id
            if evidence is not None
            else group.source_ids[0]
            if group is not None
            else UNRESOLVED_SOURCE_ID
        ),
        independence_group_id=(
            group.independence_group_id if group is not None else UNRESOLVED_GROUP_ID
        ),
        canonical_identity=(
            group.canonical_identity if group is not None else UNRESOLVED_CANONICAL_IDENTITY
        ),
        relation=alignment.relation,
        contribution=contribution,
        component_contributions=component_contributions(alignment),
        retraction_status=retraction,
        publication_status=publication,
        traceability=traceability,
        content_scope=scope,
        limitations=evidence_limitations(
            scope,
            retraction,
            publication,
            traceability,
            quality.provider_observation_count if quality is not None else 1,
            quality.publication_year if quality is not None else None,
        ),
        unknown_dimensions=unknown,
    )


__all__ = [
    "build_weight_profile",
    "classify_contribution",
    "component_contributions",
    "evidence_limitations",
    "resolve_traceability",
]
