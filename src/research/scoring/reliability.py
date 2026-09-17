"""``SCORE-RELIABILITY-PROFILE-V1`` -- Phase 2F (section 10).

Source quality is reported beside the score and **never inside it**.

The temptation this module exists to refuse: publication and retraction
metadata are obviously relevant to how much an index deserves to be believed,
so the easy move is to multiply the score by 0.8 for a preprint. That would be
a score change nobody can audit -- the number moves and the reason is buried in
a coefficient. ``LIMITED_RELIABILITY`` printed next to an unchanged index is a
statement a reviewer can read, check against the metadata, and disagree with.

So this profile adds no points and subtracts none. It counts the facts Phase 2E
recorded and maps them onto a finite posture:

``INDETERMINATE``
    Nothing contributed, or nothing that contributed states its publication
    form. The honest answer, and deliberately the *lowest* rank -- it is the
    absence of the facts the other values are made of, not a middle value.

``LIMITED_RELIABILITY``
    A contributing group is a preprint, or some contributing group leaves
    publication or retraction status unknown.

``MODERATE_RELIABILITY``
    Every contributing group states formal publication and a retraction fact,
    but the content behind the evidence is not full text -- which, under
    ADR-013, is the normal case for abstract-only academic evidence.

``HIGHER_RELIABILITY``
    Every contributing group is peer-reviewed or formally published, every one
    states a retraction fact, and the evidence rests on full text.

The ladder is ordered so **unknown can never improve it**: replacing a known
favorable fact with ``UNKNOWN`` moves a card from ``HIGHER``/``MODERATE`` to
``LIMITED``, and making every fact unknown moves it to ``INDETERMINATE``. Peer
review is never inferred -- from venue, title, provider or URL -- and
``HIGHER_RELIABILITY`` is refused by the schema itself unless a contributing
group's metadata actually states formal publication.
"""

from __future__ import annotations

from src.schemas.claim_evidence_score import (
    ReliabilityPosture,
    ScoreReasonCode,
    ScoreReliabilityProfile,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyAssessment,
    ContentScopeLimitation,
    EvidenceWeightProfile,
    PublicationStatus,
    RetractionStatus,
    TraceabilityStatus,
    UNTRACEABLE_STATUSES,
)

RELIABILITY_RANK: dict[ReliabilityPosture, int] = {
    ReliabilityPosture.INDETERMINATE: 0,
    ReliabilityPosture.LIMITED_RELIABILITY: 1,
    ReliabilityPosture.MODERATE_RELIABILITY: 2,
    ReliabilityPosture.HIGHER_RELIABILITY: 3,
}
"""An explicit ordering, so "unknown must not improve reliability" is a
comparison a test can make rather than a claim a reviewer has to trust."""


def build_reliability_profile(
    assessment: ClaimSufficiencyAssessment,
    profiles: list[EvidenceWeightProfile],
) -> ScoreReliabilityProfile:
    """Derive the reliability posture for one claim's scorecard.

    ``profiles`` are the Phase 2E weight profiles for this claim only. Group
    identity, not profile count, decides every count here: two excerpts from one
    paper are one group and must not read as two corroborating sources
    (section 10, ADR-009).
    """
    eligible = [p for p in profiles if p.is_eligible]
    contributing_groups = {p.independence_group_id for p in eligible}

    def groups_where(predicate) -> set:
        return {p.independence_group_id for p in eligible if predicate(p)}

    peer_reviewed = groups_where(
        lambda p: p.publication_status
        is PublicationStatus.PEER_REVIEWED_OR_FORMALLY_PUBLISHED
    )
    preprint = groups_where(
        lambda p: p.publication_status is PublicationStatus.PREPRINT
    )
    unknown_publication = groups_where(
        lambda p: p.publication_status is PublicationStatus.UNKNOWN
    )
    unknown_retraction = groups_where(
        lambda p: p.retraction_status is RetractionStatus.UNKNOWN
    )
    retracted = {
        p.independence_group_id
        for p in profiles
        if p.retraction_status is RetractionStatus.RETRACTED
    }
    untraceable = [p for p in profiles if p.traceability in UNTRACEABLE_STATUSES]
    disqualified = {
        p.independence_group_id for p in profiles if not p.is_eligible
    }

    ceiling = assessment.content_scope_ceiling
    posture = _posture(
        contributing=len(contributing_groups),
        peer_reviewed=len(peer_reviewed),
        preprint=len(preprint),
        unknown_publication=len(unknown_publication),
        unknown_retraction=len(unknown_retraction),
        ceiling=ceiling,
    )

    reasons: list[ScoreReasonCode] = []
    if ceiling is ContentScopeLimitation.ABSTRACT_ONLY:
        reasons.append(ScoreReasonCode.ABSTRACT_ONLY_RELIABILITY_LIMITATION)
    if preprint:
        reasons.append(ScoreReasonCode.PREPRINT_RELIABILITY_LIMITATION)
    if unknown_publication:
        reasons.append(ScoreReasonCode.UNKNOWN_PUBLICATION_STATUS)
    if unknown_retraction:
        reasons.append(ScoreReasonCode.UNKNOWN_RETRACTION_STATUS)
    if retracted:
        reasons.append(ScoreReasonCode.RETRACTED_SOURCE_EXCLUDED)
    if untraceable:
        reasons.append(ScoreReasonCode.UNTRACEABLE_SOURCE_EXCLUDED)

    return ScoreReliabilityProfile(
        posture=posture,
        retracted_group_count=len(retracted),
        untraceable_profile_count=len(untraceable),
        preprint_group_count=len(preprint),
        peer_reviewed_group_count=len(peer_reviewed),
        unknown_publication_group_count=len(unknown_publication),
        unknown_retraction_group_count=len(unknown_retraction),
        disqualified_group_count=len(disqualified),
        contributing_group_count=len(contributing_groups),
        content_scope_ceiling=ceiling,
        unknown_dimensions=list(assessment.unknown_dimensions),
        reason_codes=list(dict.fromkeys(reasons)),
        profile_version=ScoreReliabilityProfile.model_fields[
            "profile_version"
        ].default,
    )


def _posture(
    *,
    contributing: int,
    peer_reviewed: int,
    preprint: int,
    unknown_publication: int,
    unknown_retraction: int,
    ceiling: ContentScopeLimitation | None,
) -> ReliabilityPosture:
    """The ladder, in precedence order. See the module docstring for the why."""
    if contributing == 0:
        return ReliabilityPosture.INDETERMINATE
    if unknown_publication == contributing:
        # Nothing that contributed states what form it was published in.
        return ReliabilityPosture.INDETERMINATE
    if preprint:
        return ReliabilityPosture.LIMITED_RELIABILITY
    if unknown_publication or unknown_retraction:
        return ReliabilityPosture.LIMITED_RELIABILITY
    if peer_reviewed == contributing and ceiling is ContentScopeLimitation.FULL_TEXT:
        return ReliabilityPosture.HIGHER_RELIABILITY
    return ReliabilityPosture.MODERATE_RELIABILITY


def traceability_is_clean(profiles: list[EvidenceWeightProfile]) -> bool:
    """True when every profile's chain resolves inside this run."""
    return all(p.traceability is TraceabilityStatus.TRACEABLE for p in profiles)


__all__ = [
    "RELIABILITY_RANK",
    "build_reliability_profile",
    "traceability_is_clean",
]
