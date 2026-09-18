"""Patent prior-art candidate construction -- Phase 2G sections 23, 24, 32.

This is the end of the Phase 2G pipeline. A candidate says:

> a bounded, provenance-recorded patent search surfaced this document; its
> bibliographic metadata verified; here is its family, its date line and what
> text we hold.

It does not say, and cannot be made to say, that the document is the same
invention, that it affects novelty, or that it is legal prior art anywhere
(ADR-018).

Two mechanisms enforce that rather than merely asking for it.

**The contract has no field for a conclusion.** There is no ``novelty_score``,
no ``similarity``, no ``same_invention`` and no ``invalidating`` on
``PatentPriorArtCandidate``. A provider's retrieval rank is carried on
``PatentQueryProvenance.provider_rank``, named for what it is, and it is never
copied into anything that reads like a judgement (section 24).

**Every candidate states its own limitations.** The four universal ones --
novelty not assessed, patentability not assessed, legal status not determined,
bounded search -- are required by the contract validator, so a candidate that
omits them cannot be constructed. The conditional ones are derived here from
what the record actually shows: no claims text, abstract only, title only,
unknown publication date, unknown family, no cutoff supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.research.patent.chronology import qualify_against_cutoff
from src.schemas.patent import (
    UNIVERSAL_CANDIDATE_LIMITATIONS,
    PatentCandidateLimitation,
    PatentContentReport,
    PatentContentType,
    PatentFamilyGroup,
    PatentFamilyStatus,
    PatentPriorArtCandidate,
    PatentQueryProvenance,
    PatentSearchCutoff,
    PatentSearchQuery,
    PatentTimeQualification,
    RESOLVED_FAMILY_STATUSES,
    VerifiedPatentPublication,
)

PATENT_CANDIDATE_VERSION = "PATENT-CANDIDATE-V1"


def derive_limitations(
    publication: VerifiedPatentPublication,
    *,
    time_qualification: PatentTimeQualification,
    cutoff_supplied: bool,
) -> list[PatentCandidateLimitation]:
    """What this candidate does not establish, derived from the record itself.

    The universal four come first and are never conditional. The rest are read
    off the content report, the date line and the family status, so a candidate
    that is weaker than it looks says so on its own face rather than relying on
    a reader to check four other fields.
    """
    limitations = list(UNIVERSAL_CANDIDATE_LIMITATIONS)
    content = publication.content

    if not content.claims_available:
        limitations.append(PatentCandidateLimitation.CLAIMS_TEXT_UNAVAILABLE)
    if content.title_only:
        limitations.append(PatentCandidateLimitation.TITLE_ONLY_METADATA)
    elif (
        PatentContentType.ABSTRACT in content.available_types
        and not content.claims_available
        and PatentContentType.DESCRIPTION not in content.available_types
    ):
        # Abstract-only is called out explicitly, exactly as Phase 2C marks
        # abstract-only evidence: a comparison made against an abstract is a
        # weaker comparison than one made against claims, and the later phase
        # that weighs them must be able to see which it has (ADR-013).
        limitations.append(PatentCandidateLimitation.ABSTRACT_ONLY_TEXT)

    if time_qualification is PatentTimeQualification.PUBLICATION_DATE_UNKNOWN or (
        not publication.dates.has_public_date
    ):
        limitations.append(PatentCandidateLimitation.PUBLICATION_DATE_UNKNOWN)
    if not cutoff_supplied:
        limitations.append(PatentCandidateLimitation.NO_CUTOFF_SUPPLIED)

    if publication.family_status not in RESOLVED_FAMILY_STATUSES:
        limitations.append(PatentCandidateLimitation.FAMILY_MEMBERSHIP_UNKNOWN)
    elif publication.family_status is PatentFamilyStatus.VERIFIED_FAMILY:
        # A resolved family groups documents of one invention; it does not make
        # their claim scope identical across jurisdictions, and a later phase
        # must not read one member's claims as another's (section 17).
        limitations.append(PatentCandidateLimitation.FAMILY_SCOPE_VARIES_BY_JURISDICTION)

    if publication.ipc_classifications or publication.cpc_classifications:
        limitations.append(
            PatentCandidateLimitation.CLASSIFICATION_OVERLAP_IS_NOT_IDENTITY
        )

    return list(dict.fromkeys(limitations))


def build_query_provenance(
    publication: VerifiedPatentPublication,
    queries: dict[str, PatentSearchQuery],
) -> list[PatentQueryProvenance]:
    """Which queries found this publication, and how each was shaped.

    One entry per observation, so a document found by three queries records all
    three. ``provider_rank`` is carried through as provider-generated retrieval
    metadata and nothing else (section 24).
    """
    provenance: list[PatentQueryProvenance] = []
    for observation in publication.observations:
        query = queries.get(str(observation.query_id))
        if query is None:
            continue
        provenance.append(
            PatentQueryProvenance(
                query_id=observation.query_id,
                provider=observation.provider,
                purpose=query.purpose,
                strategy=query.strategy,
                provider_rank=observation.provider_rank,
                claim_ids=list(query.claim_ids),
                component_ids=list(query.component_ids),
            )
        )
    return provenance


@dataclass
class CandidateOutcome:
    """The candidates a run produced, and what could not become one."""

    candidates: list[PatentPriorArtCandidate] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    """``(publication key, reason)`` for a publication that produced no
    candidate. Recorded rather than dropped, so the count is explainable."""

    @property
    def before_cutoff_count(self) -> int:
        return sum(
            1
            for c in self.candidates
            if c.time_qualification is PatentTimeQualification.PUBLIC_BEFORE_CUTOFF
        )

    @property
    def unknown_date_count(self) -> int:
        return sum(
            1
            for c in self.candidates
            if c.time_qualification is PatentTimeQualification.PUBLICATION_DATE_UNKNOWN
        )

    @property
    def independent_family_count(self) -> int:
        """Candidate inventions rather than candidate documents (section 17)."""
        grouped = {c.family_group_id for c in self.candidates if c.family_group_id}
        ungrouped = sum(1 for c in self.candidates if c.family_group_id is None)
        return len(grouped) + ungrouped


def build_candidates(
    publications: list[VerifiedPatentPublication],
    *,
    queries: list[PatentSearchQuery],
    families: list[PatentFamilyGroup],
    cutoff: PatentSearchCutoff,
) -> CandidateOutcome:
    """Turn verified publications into prior-art candidates.

    Every publication that traces to at least one planned query becomes exactly
    one candidate. A publication whose query provenance cannot be reconstructed
    produces none: a candidate that cannot say why it was found is not auditable,
    and section 23 requires the provenance.
    """
    outcome = CandidateOutcome()
    by_id = {str(q.query_id): q for q in queries}
    family_by_group = {f.family_group_id: f for f in families}

    for publication in publications:
        provenance = build_query_provenance(publication, by_id)
        if not provenance:
            outcome.skipped.append(
                (publication.publication_key, "no traceable query provenance")
            )
            continue

        chronology = qualify_against_cutoff(publication.dates, cutoff)
        family = family_by_group.get(publication.family_group_id or None)
        family_id = (
            family.family_id
            if family is not None and family.status in RESOLVED_FAMILY_STATUSES
            else None
        )

        outcome.candidates.append(
            PatentPriorArtCandidate(
                research_run_id=publication.research_run_id,
                publication_id=publication.publication_id,
                publication_key=publication.publication_key,
                identity=publication.identity,
                family_group_id=publication.family_group_id,
                family_id=family_id,
                family_status=publication.family_status,
                title=publication.title,
                dates=publication.dates,
                time_qualification=chronology.qualification,
                cutoff_date=chronology.cutoff_date,
                applicants=list(publication.applicants),
                inventors=list(publication.inventors),
                ipc_classifications=list(publication.ipc_classifications),
                cpc_classifications=list(publication.cpc_classifications),
                content=publication.content or PatentContentReport(),
                snapshot_ids=list(publication.snapshot_ids),
                query_provenance=provenance,
                observation_ids=[o.observation_id for o in publication.observations],
                limitations=derive_limitations(
                    publication,
                    time_qualification=chronology.qualification,
                    cutoff_supplied=cutoff.supplied,
                ),
            )
        )
    return outcome


__all__ = [
    "PATENT_CANDIDATE_VERSION",
    "CandidateOutcome",
    "build_candidates",
    "build_query_provenance",
    "derive_limitations",
]
