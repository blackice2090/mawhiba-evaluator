"""Verified academic source -> source content snapshot.

This is the boundary that stops metadata becoming evidence. A Phase 2B logical
source carries a title, authors, a venue, a citation count and a provider rank;
none of those is source content, and none of them may reach an extractor.

Only one field qualifies today: the paper's own ``abstract``, as a specific
provider returned it.

**Provider attribution is structural, not decorative.** ``LogicalAcademicSource``
exposes a *merged* abstract -- the first non-empty one across providers -- and
that string has no single origin. Extracting evidence from it would produce
evidence nobody could attribute. Snapshots are therefore built from the
per-provider ``AcademicSourceCandidate`` records, each of which knows exactly
which provider supplied its text (§7).

**Consensus synthesis is not content.** Consensus's ``takeaway`` is its own
one-line synthesis of a paper, not the paper's words. Phase 2B stores it only
inside ``raw_provider_metadata``; nothing here reads that field, so a synthesis
has no path to becoming an ``ABSTRACT`` snapshot (§8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.schemas.academic import (
    AcademicRetrievalResult,
    AcademicSourceCandidate,
    LogicalAcademicSource,
)
from src.schemas.evidence_extraction import (
    ContentKind,
    IneligibleContentReason,
    IneligibleSource,
    SourceContentSnapshot,
    content_hash,
)

MIN_CONTENT_CHARS = 40
"""Below this an abstract field holds a stub, not extractable prose.

A 20-character "abstract" is routinely a truncation marker or a placeholder.
Treating it as content would invite excerpts that verify trivially and mean
nothing.
"""


@dataclass
class ContentBuildOutcome:
    """Snapshots that can be extracted from, and sources that cannot."""

    snapshots: list[SourceContentSnapshot] = field(default_factory=list)
    ineligible: list[IneligibleSource] = field(default_factory=list)

    @property
    def eligible_source_ids(self) -> set[str]:
        return {snapshot.source_id for snapshot in self.snapshots}


def _candidates_by_source(
    result: AcademicRetrievalResult,
) -> dict[str, list[AcademicSourceCandidate]]:
    """Group accepted candidates under the logical source they resolved to.

    Uses the Phase 2B decision ledger rather than re-deriving identity, so
    content attribution can never disagree with the dedup that produced the
    logical source.
    """
    by_candidate = {c.candidate_id: c for c in result.candidates}
    grouped: dict[str, list[AcademicSourceCandidate]] = {}
    for decision in result.decisions:
        if not decision.accepted or decision.logical_source_id is None:
            continue
        candidate = by_candidate.get(decision.candidate_id)
        if candidate is not None:
            grouped.setdefault(decision.logical_source_id, []).append(candidate)
    return grouped


def _abstract_text(candidate: AcademicSourceCandidate) -> str | None:
    """The paper's own abstract, or nothing.

    Reads exactly one field. ``raw_provider_metadata`` -- where a Consensus
    takeaway lives -- is never consulted.
    """
    text = (candidate.abstract or "").strip()
    return text or None


def build_content_snapshots(
    source: LogicalAcademicSource,
    candidates: list[AcademicSourceCandidate],
    research_run_id: UUID,
) -> tuple[list[SourceContentSnapshot], IneligibleSource | None]:
    """One snapshot per provider that supplied real abstract text.

    Returns the snapshots and, when there are none, the reason why -- which is
    an outcome rather than a failure (§6).
    """
    snapshots: list[SourceContentSnapshot] = []
    saw_short_text = False

    for candidate in candidates:
        text = _abstract_text(candidate)
        if text is None:
            continue
        if len(text) < MIN_CONTENT_CHARS:
            saw_short_text = True
            continue
        snapshots.append(
            SourceContentSnapshot(
                source_id=source.logical_source_id,
                research_run_id=research_run_id,
                content_kind=ContentKind.ABSTRACT,
                text=text,
                content_hash=content_hash(text),
                provider=candidate.provider,
                provider_record_id=candidate.provider_record_id,
                provider_url=candidate.provider_url,
                canonical_url=candidate.canonical_url or source.canonical_url,
                retrieved_at=candidate.retrieved_at,
                publication_year=source.publication_year,
                source_type=source.source_type,
                is_retracted=source.is_retracted,
                peer_review_status=source.peer_review_status,
            )
        )

    if snapshots:
        return snapshots, None

    reason = (
        IneligibleContentReason.CONTENT_TOO_SHORT
        if saw_short_text
        else IneligibleContentReason.METADATA_ONLY
    )
    return [], IneligibleSource(
        source_id=source.logical_source_id,
        reason=reason,
        note="a verified source with no extractable content yields no evidence",
    )


def build_all_content_snapshots(
    result: AcademicRetrievalResult, research_run_id: UUID
) -> ContentBuildOutcome:
    """Build the content boundary for every verified academic source."""
    outcome = ContentBuildOutcome()
    grouped = _candidates_by_source(result)

    for source in result.logical_sources:
        snapshots, ineligible = build_content_snapshots(
            source, grouped.get(source.logical_source_id, []), research_run_id
        )
        outcome.snapshots.extend(snapshots)
        if ineligible is not None:
            outcome.ineligible.append(ineligible)

    return outcome


__all__ = [
    "MIN_CONTENT_CHARS",
    "ContentBuildOutcome",
    "build_all_content_snapshots",
    "build_content_snapshots",
]
