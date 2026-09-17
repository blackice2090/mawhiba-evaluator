"""Conservative evidence deduplication.

One rule, applied narrowly: two evidence items collapse only when they are the
**same span of the same bytes of the same source**, carrying the same evidence
type. That is the identity defined in §12 -- source, content hash, verified
offsets, type -- and nothing weaker.

What this deliberately does not do:

* **No semantic collapsing.** Two excerpts that say similar things are two
  findings. Merging them would silently halve the apparent evidence base.
* **No cross-source collapsing.** The same sentence appearing in two different
  papers is two pieces of evidence, and the fact that two independent papers say
  it is itself information a later phase needs.
* **No provenance loss.** When identical content did arrive from two providers,
  the items merge and every ``EvidenceContentObservation`` survives -- the same
  logical-item / provider-observation shape ADR-009 established for sources.
"""

from __future__ import annotations

from src.schemas.evidence_extraction import (
    EvidenceRejectionReason,
    ExtractedEvidence,
    RejectedEvidenceCandidate,
)


def _merge_observations(
    primary: ExtractedEvidence, duplicate: ExtractedEvidence
) -> ExtractedEvidence:
    """Fold a duplicate's provider observations into the surviving item."""
    known = {o.content_id for o in primary.observations}
    additions = [o for o in duplicate.observations if o.content_id not in known]
    if not additions:
        return primary
    return ExtractedEvidence.model_validate(
        {**dict(primary), "observations": [*primary.observations, *additions]}
    )


def deduplicate_evidence(
    evidence: list[ExtractedEvidence],
) -> tuple[list[ExtractedEvidence], list[RejectedEvidenceCandidate]]:
    """Collapse identical spans, preserving every observation.

    Order-stable: the first occurrence survives and later ones fold into it, so
    the same inputs always produce the same evidence ids and the same ordering.
    """
    surviving: dict[tuple, ExtractedEvidence] = {}
    order: list[tuple] = []
    collapsed: list[RejectedEvidenceCandidate] = []

    for item in evidence:
        key = item.logical_key
        existing = surviving.get(key)
        if existing is None:
            surviving[key] = item
            order.append(key)
            continue

        surviving[key] = _merge_observations(existing, item)
        collapsed.append(
            RejectedEvidenceCandidate(
                candidate_id=item.evidence_id,
                source_id=item.source_id,
                content_id=item.content_id,
                reason=EvidenceRejectionReason.DUPLICATE_EVIDENCE,
                safe_summary="identical verified span already recorded for this source",
            )
        )

    return [surviving[key] for key in order], collapsed


__all__ = ["deduplicate_evidence"]
