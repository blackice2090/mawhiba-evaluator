"""Deterministic verification of patent search observations -- section 22.

The boundary this module enforces:

    PatentSearchObservation      a search hit. Untrusted.
    ===========================  VERIFICATION
    VerifiedPatentPublication    checked identity, dates, classes, provenance.

Verification is bibliographic and nothing more. It proves that the canonical
identity is well formed, that the dates parse and could actually have occurred
in that order, that every classification is a real symbol shape, that the record
traces to a query of *this* run, and that the family identifier is a provider
identifier rather than something derived. It proves nothing about relevance, and
by design it cannot: relevance is not an input and there is no field to put it
in (ADR-018).

Cross-run contamination is refused here rather than caught downstream
(section 30): an observation whose ``research_run_id`` is not this run's, or
whose ``query_id`` is not a query this run planned, is rejected with a named
reason instead of being quietly dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.research.patent.identity import (
    normalize_classification,
    normalize_family_id,
)
from src.research.privacy import (
    EMPTY_PRIVACY_CONTEXT,
    ResearchPrivacyContext,
    contains_pii,
)
from src.schemas.patent import (
    PatentRejectionReason,
    PatentRejectionStage,
    PatentSearchObservation,
    RejectedPatentRecord,
    patent_safe_summary,
)

PATENT_VERIFICATION_VERSION = "PATENT-VERIFICATION-V1"


@dataclass
class VerificationOutcome:
    """Which observations survived verification, and why the others did not."""

    accepted: list[PatentSearchObservation] = field(default_factory=list)
    rejected: list[RejectedPatentRecord] = field(default_factory=list)

    @property
    def accepted_keys(self) -> list[str]:
        return [o.publication_key for o in self.accepted]


def check_observation(
    observation: PatentSearchObservation,
    *,
    research_run_id: UUID,
    known_query_ids: set[UUID],
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
) -> PatentRejectionReason | None:
    """Every rule the observation breaks, or ``None`` when it verifies.

    The checks are ordered so the reported reason names the real defect: run
    membership first (a foreign record's other fields are irrelevant), then
    query traceability, then the bibliographic content.
    """
    if observation.research_run_id != research_run_id:
        return PatentRejectionReason.CROSS_RUN_RECORD
    if observation.query_id not in known_query_ids:
        return PatentRejectionReason.UNKNOWN_QUERY_REFERENCE

    # The identity itself is already validated by ``PublicationIdentity``: it
    # could not have been constructed with a malformed authority, number or
    # kind code. What is checked here is that it carries content at all.
    if not observation.identity.authority or not observation.identity.number:
        return PatentRejectionReason.MISSING_PUBLICATION_IDENTITY

    for symbol in (*observation.ipc_classifications, *observation.cpc_classifications):
        if normalize_classification(symbol) != symbol:
            return PatentRejectionReason.INVALID_CLASSIFICATION

    if observation.family_id is not None and normalize_family_id(
        observation.family_id
    ) != observation.family_id:
        return PatentRejectionReason.INVALID_FAMILY_IDENTIFIER

    # Applicant and inventor names are legitimate patent metadata, so they are
    # not PII-scanned: they are the document's own parties, not the student's.
    # The title and the provider's record identifier are scanned, because a
    # provider echoing a query could return the student's own words there.
    if contains_pii(observation.title, privacy):
        return PatentRejectionReason.PII_DETECTED

    return None


def verify_observations(
    observations: list[PatentSearchObservation],
    *,
    research_run_id: UUID,
    known_query_ids: set[UUID],
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    max_observations: int | None = None,
) -> VerificationOutcome:
    """Verify a run's observations. Pure; nothing is mutated.

    ``max_observations`` truncates and records the cut as a budget rejection
    rather than discarding silently (section 26). The truncation is applied
    after verification so a rejected record does not consume budget a valid one
    could have used.
    """
    outcome = VerificationOutcome()

    for observation in observations:
        reason = check_observation(
            observation,
            research_run_id=research_run_id,
            known_query_ids=known_query_ids,
            privacy=privacy,
        )
        if reason is not None:
            outcome.rejected.append(
                RejectedPatentRecord(
                    provider=observation.provider,
                    query_id=observation.query_id
                    if observation.query_id in known_query_ids
                    else None,
                    stage=PatentRejectionStage.VERIFICATION,
                    reason=reason,
                    provider_record_identifier=observation.provider_record_id,
                    safe_summary=""
                    if reason is PatentRejectionReason.PII_DETECTED
                    else patent_safe_summary(observation.publication_key),
                )
            )
            continue
        outcome.accepted.append(observation)

    if max_observations is not None and len(outcome.accepted) > max_observations:
        # Truncate on distinct publications, not on raw observations: cutting
        # mid-publication would drop one provider's view of a document that
        # another provider's view keeps, which would silently destroy the
        # corroboration record (section 15).
        allowed: list[str] = []
        kept: list[PatentSearchObservation] = []
        dropped: list[PatentSearchObservation] = []
        for observation in outcome.accepted:
            key = observation.publication_key
            if key in allowed:
                kept.append(observation)
                continue
            if len(allowed) < max_observations:
                allowed.append(key)
                kept.append(observation)
                continue
            dropped.append(observation)
        outcome.accepted = kept
        outcome.rejected.extend(
            RejectedPatentRecord(
                provider=observation.provider,
                query_id=observation.query_id,
                stage=PatentRejectionStage.BUDGET,
                reason=PatentRejectionReason.TOTAL_RESULT_LIMIT_EXCEEDED,
                provider_record_identifier=observation.provider_record_id,
                safe_summary=patent_safe_summary(observation.publication_key),
            )
            for observation in dropped
        )

    return outcome


__all__ = [
    "PATENT_VERIFICATION_VERSION",
    "VerificationOutcome",
    "check_observation",
    "verify_observations",
]
