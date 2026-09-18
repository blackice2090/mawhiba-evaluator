"""Patent text snapshots -- Phase 2G sections 19, 20, 21.

A snapshot holds the office's own text for exactly one content type of exactly
one publication, with the provenance needed to defend it: which provider, which
documented operation, which language the provider declared, when it was
retrieved, how it was normalized and what it hashes to.

The rules that make a snapshot trustworthy:

* **Content types are never interchangeable.** A claims request that returns
  nothing produces a recorded absence. It never falls back to the abstract, and
  the abstract never falls back to the title (section 21). The code path for
  each type reads only that type.

* **Nothing generated is stored as patent text.** There is no summarization step
  in this module and no field to put a summary in. What is stored is the
  provider's text with whitespace normalized, which is why
  ``PatentTextSnapshot.normalization`` records the normalizer version -- the
  hash is then reproducible from the stored value (section 19).

* **Unavailable is never favourable.** Each content type gets an explicit
  ``PatentContentAvailability``, and the four reasons a type can be missing are
  kept apart: the authority does not publish it, the provider does not expose
  it, the retrieval failed, or it was not requested within budget. ``UNKNOWN``
  is a real state and is never read as "there is nothing there" (section 20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from src.research.patent.epo_ops import content_hash
from src.research.patent.provider import PatentSearchProvider, TextPayload
from src.schemas.patent import (
    PATENT_NORMALIZER_VERSION,
    PatentContentAvailability,
    PatentContentReport,
    PatentContentType,
    PatentTextSnapshot,
    VerifiedPatentPublication,
)

PATENT_SNAPSHOT_VERSION = "PATENT-SNAPSHOT-V1"

DEFAULT_CONTENT_TYPES: tuple[PatentContentType, ...] = (
    PatentContentType.ABSTRACT,
    PatentContentType.CLAIMS,
)
"""What a run fetches by default.

Claims because a later comparison phase needs them most, the abstract because it
is the most widely available. The description is not fetched by default: it is
enormous, costly, and only useful once a candidate has been narrowed down.
"""


@dataclass
class SnapshotOutcome:
    """The snapshots a run captured, and what each publication ended up with."""

    snapshots: list[PatentTextSnapshot] = field(default_factory=list)
    reports: dict[str, PatentContentReport] = field(default_factory=dict)
    snapshot_ids: dict[str, list[UUID]] = field(default_factory=dict)
    fetches_performed: int = 0

    @property
    def claims_available_count(self) -> int:
        return sum(1 for report in self.reports.values() if report.claims_available)

    @property
    def title_only_count(self) -> int:
        return sum(1 for report in self.reports.values() if report.title_only)


def _availability(payload: TextPayload) -> PatentContentAvailability:
    """Turn a provider payload into an explicit availability statement.

    Every branch names a distinct fact. There is no branch that returns
    ``AVAILABLE`` without text, and none that silently returns ``UNKNOWN`` for
    a provider that actually answered.
    """
    if not payload.supported:
        return PatentContentAvailability.NOT_SUPPORTED_BY_PROVIDER
    if payload.error is not None:
        return PatentContentAvailability.RETRIEVAL_FAILED
    if payload.available:
        return PatentContentAvailability.AVAILABLE
    return PatentContentAvailability.NOT_PUBLISHED_BY_AUTHORITY


def build_snapshot(
    publication: VerifiedPatentPublication,
    content_type: PatentContentType,
    payload: TextPayload,
    *,
    provider_name: str,
    research_run_id: UUID,
    retrieved_at: datetime,
) -> PatentTextSnapshot | None:
    """One snapshot, or ``None`` when there is no text to snapshot.

    The hash is computed over the stored text, so a stability check compares the
    value that is actually on the record rather than bytes nobody kept.
    """
    if not payload.available or payload.text is None:
        return None
    from src.schemas.patent import PatentProvider

    return PatentTextSnapshot(
        research_run_id=research_run_id,
        publication_key=publication.publication_key,
        provider=PatentProvider(provider_name),
        content_type=content_type,
        language=payload.language,
        text=payload.text,
        content_hash=content_hash(payload.text),
        scope=payload.scope,
        normalization=PATENT_NORMALIZER_VERSION,
        provider_operation=payload.operation,
        provider_endpoint=payload.endpoint or "unknown operation",
        retrieved_at=retrieved_at,
        original_char_count=max(payload.original_char_count, len(payload.text)),
    )


def capture_snapshots(
    publications: list[VerifiedPatentPublication],
    provider: PatentSearchProvider | None,
    research_run_id: UUID,
    *,
    content_types: tuple[PatentContentType, ...] = DEFAULT_CONTENT_TYPES,
    retrieved_at: datetime | None = None,
    max_publications: int | None = None,
) -> SnapshotOutcome:
    """Capture text snapshots for a run's publications.

    A publication whose title came back in the search already has title
    metadata, so ``TITLE`` availability is derived from the record rather than
    re-fetched. Everything else is fetched per content type, and each result --
    including each absence -- is recorded.

    With no provider, every publication reports ``NOT_REQUESTED`` for the
    fetched types. A run that could not ask is never presented as a run that
    asked and found nothing.
    """
    outcome = SnapshotOutcome()
    from src.workflow.clock import workflow_now

    stamp = retrieved_at or workflow_now()
    considered = (
        publications if max_publications is None else publications[:max_publications]
    )
    skipped = publications[len(considered) :]

    for publication in considered:
        key = publication.publication_key
        report_values: dict[str, PatentContentAvailability] = {
            "title": (
                PatentContentAvailability.AVAILABLE
                if publication.title
                else PatentContentAvailability.NOT_PUBLISHED_BY_AUTHORITY
            ),
            "abstract": PatentContentAvailability.NOT_REQUESTED,
            "claims": PatentContentAvailability.NOT_REQUESTED,
            "description": PatentContentAvailability.NOT_REQUESTED,
        }
        ids: list[UUID] = []

        if provider is not None:
            for content_type in content_types:
                if content_type is PatentContentType.TITLE:
                    continue
                payload = provider.fetch_text(publication.identity, content_type)
                outcome.fetches_performed += 1
                report_values[content_type.value.casefold()] = _availability(payload)
                snapshot = build_snapshot(
                    publication,
                    content_type,
                    payload,
                    provider_name=getattr(provider, "provider_name").value,
                    research_run_id=research_run_id,
                    retrieved_at=stamp,
                )
                if snapshot is not None:
                    outcome.snapshots.append(snapshot)
                    ids.append(snapshot.snapshot_id)

        outcome.reports[key] = PatentContentReport(**report_values)
        outcome.snapshot_ids[key] = ids

    for publication in skipped:
        outcome.reports[publication.publication_key] = PatentContentReport(
            title=(
                PatentContentAvailability.AVAILABLE
                if publication.title
                else PatentContentAvailability.NOT_PUBLISHED_BY_AUTHORITY
            ),
            abstract=PatentContentAvailability.NOT_REQUESTED,
            claims=PatentContentAvailability.NOT_REQUESTED,
            description=PatentContentAvailability.NOT_REQUESTED,
        )
        outcome.snapshot_ids[publication.publication_key] = []

    return outcome


def apply_snapshots(
    publications: list[VerifiedPatentPublication], outcome: SnapshotOutcome
) -> list[VerifiedPatentPublication]:
    """Attach content reports and snapshot references. Nothing is mutated."""
    return [
        publication.model_copy(
            update={
                "content": outcome.reports.get(
                    publication.publication_key, PatentContentReport()
                ),
                "snapshot_ids": outcome.snapshot_ids.get(
                    publication.publication_key, []
                ),
            }
        )
        for publication in publications
    ]


def hashes_are_stable(
    first: list[PatentTextSnapshot], second: list[PatentTextSnapshot]
) -> bool:
    """Whether two captures of the same texts produced the same hashes.

    Keyed on publication and content type rather than on snapshot id, because
    the id is fresh per capture by design while the hash must not be.
    """

    def index(snapshots: list[PatentTextSnapshot]) -> dict[tuple[str, str], str]:
        return {
            (s.publication_key, s.content_type.value): s.content_hash
            for s in snapshots
        }

    return index(first) == index(second)


__all__ = [
    "DEFAULT_CONTENT_TYPES",
    "PATENT_SNAPSHOT_VERSION",
    "SnapshotOutcome",
    "apply_snapshots",
    "build_snapshot",
    "capture_snapshots",
    "hashes_are_stable",
]
