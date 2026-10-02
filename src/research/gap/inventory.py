"""Phase 2J evidence inventory, text resolution and exact anchoring.

The inventory is the "no new evidence" boundary (section 4.2). It is built
only from records earlier phases already verified:

* Phase 2C ``ExtractedEvidence`` -- an excerpt of a content snapshot; its
  independence comes from a Phase 2E ``IndependenceGroup`` when one exists and
  is otherwise UNGROUPED, which is never independent (nothing is inferred);
* Phase 2I ``ComparableText`` of every comparable candidate -- its independence
  unit and chronology are copied unchanged from the Phase 2I profile.

Nothing here searches, fetches or parses a new source. Source quality is a
deterministic verdict per text, never a model judgment: titles and repository
metadata, non-material capacity and retracted sources cannot carry a
limitation.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from src.research.novelty.anchoring import LocateFailure, Located, locate
from src.research.novelty.candidates import resolve_text as resolve_prior_art_text
from src.schemas.academic import AcademicSourceType
from src.schemas.gap_assessment import (
    GapAssessmentBounds,
    GapInventoryText,
    GapIssueCode,
    GapSourceKind,
    IndependenceBasis,
    SourceQualityVerdict,
    gap_id,
)
from src.schemas.novelty_differentiation import (
    COMPARABLE_ELIGIBILITY,
    METADATA_TEXT_KINDS,
    DisclosureCapacity,
    NoveltyDifferentiationRun,
    TextKind,
)
from src.schemas.research import ResearchRun

REVIEW_SOURCE_TYPES: frozenset[AcademicSourceType] = frozenset(
    {AcademicSourceType.REVIEW, AcademicSourceType.SYSTEMATIC_REVIEW, AcademicSourceType.META_ANALYSIS}
)


def canonical_order(item: GapInventoryText) -> tuple[str, str, int, str]:
    """Content first, identifiers last: the same texts select the same way in a
    new research run whose record ids differ (replay and input-order invariance)."""
    return (item.source_kind.value, item.text_hash, item.span_start, str(item.source_record_id))


def gap_run_id_for(research_run_id: UUID) -> UUID:
    return gap_id(research_run_id, "gap-assessment")


def digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InventoryIssue:
    code: GapIssueCode
    message: str


LIMITATION_INELIGIBLE_TEXT_KINDS: frozenset[TextKind] = METADATA_TEXT_KINDS | {TextKind.OSS_MANIFEST}
"""Titles, repository metadata and manifests. A manifest is structured package
metadata: it lists dependencies and fields, it does not state a limitation."""


def prior_art_quality(text_kind: TextKind, capacity: DisclosureCapacity) -> SourceQualityVerdict:
    """A title, repository metadata or manifest is never limitation evidence, and
    neither is a text Phase 2I rated non-material for disclosure (section 8.2)."""
    if text_kind in LIMITATION_INELIGIBLE_TEXT_KINDS:
        return SourceQualityVerdict.INELIGIBLE_METADATA_TEXT
    if capacity is DisclosureCapacity.NON_MATERIAL:
        return SourceQualityVerdict.INELIGIBLE_NON_MATERIAL_CAPACITY
    return SourceQualityVerdict.ELIGIBLE


def build_inventory(
    research_run: ResearchRun, nd: NoveltyDifferentiationRun, gap_run_id: UUID
) -> tuple[list[GapInventoryText], list[InventoryIssue]]:
    """Every upstream text the run may cite, in a canonical order."""
    items: list[GapInventoryText] = []
    issues: list[InventoryIssue] = []
    extraction = research_run.evidence_extraction
    if extraction is not None:
        snapshots = {s.content_id: s for s in extraction.content_snapshots}
        groups = research_run.claim_sufficiency.independence_groups if research_run.claim_sufficiency else []
        group_of = {evidence_id: g for g in groups for evidence_id in g.member_evidence_ids}
        for evidence in extraction.verified_evidence:
            snapshot = snapshots.get(evidence.content_id)
            if (
                snapshot is None
                or digest(snapshot.text) != evidence.content_hash
                or snapshot.text[evidence.verified_start : evidence.verified_end] != evidence.excerpt
            ):
                issues.append(InventoryIssue(GapIssueCode.INVALID_INPUT, "a verified evidence item no longer matches its snapshot"))
                continue
            group = group_of.get(evidence.evidence_id)
            quality = (
                SourceQualityVerdict.INELIGIBLE_RETRACTED if evidence.is_retracted else SourceQualityVerdict.ELIGIBLE
            )
            items.append(GapInventoryText(
                inventory_text_id=gap_id(gap_run_id, GapSourceKind.ACADEMIC_EVIDENCE.value, evidence.evidence_id),
                source_kind=GapSourceKind.ACADEMIC_EVIDENCE,
                source_record_id=evidence.evidence_id,
                upstream_run_id=evidence.extraction_run_id,
                text_hash=evidence.content_hash,
                span_start=evidence.verified_start,
                span_end=evidence.verified_end,
                source_quality=quality,
                independence_basis=(
                    IndependenceBasis.ACADEMIC_PHASE2E_GROUP if group else IndependenceBasis.ACADEMIC_UNGROUPED
                ),
                independence_key=group.canonical_identity if group else f"source:{evidence.source_id}",
                counts_as_independent=group is not None,
                is_review_source=evidence.source_type in REVIEW_SOURCE_TYPES,
            ))
    for profile in nd.candidate_profiles:
        if profile.eligibility not in COMPARABLE_ELIGIBILITY:
            continue
        for text in profile.texts:
            body = resolve_prior_art_text(research_run, text)
            if body is None or digest(body) != text.text_digest:
                issues.append(InventoryIssue(GapIssueCode.INVALID_INPUT, "a compared candidate text no longer resolves"))
                continue
            unit = profile.independence_unit
            items.append(GapInventoryText(
                inventory_text_id=gap_id(gap_run_id, GapSourceKind.PRIOR_ART_TEXT.value, text.text_ref_id),
                source_kind=GapSourceKind.PRIOR_ART_TEXT,
                source_record_id=text.text_ref_id,
                upstream_run_id=nd.nd_run_id,
                candidate_id=profile.candidate_ref.candidate_id,
                text_kind=text.text_kind,
                text_hash=text.text_digest,
                span_start=0,
                span_end=len(body),
                language=text.language,
                source_quality=prior_art_quality(text.text_kind, text.capacity),
                independence_basis=IndependenceBasis.PRIOR_ART_PHASE2I_UNIT,
                independence_key=unit.unit_key,
                counts_as_independent=unit.counts_as_independent,
                correlation_group_key=unit.correlation_group_key,
                inherited_unit=unit,
                chronology_bucket=profile.chronology.bucket,
                chronology_basis=profile.chronology.basis.value,
                linked_claim_ids=sorted(profile.linked_claim_ids),
            ))
    by_id: dict[UUID, GapInventoryText] = {}
    for item in items:
        existing = by_id.get(item.inventory_text_id)
        if existing is None:
            by_id[item.inventory_text_id] = item
        elif item.linked_claim_ids != existing.linked_claim_ids:
            # One text offered through several candidates: visible to the union, one record.
            merged = sorted({*existing.linked_claim_ids, *item.linked_claim_ids})
            by_id[item.inventory_text_id] = existing.model_copy(update={"linked_claim_ids": merged})
    ordered = sorted(by_id.values(), key=canonical_order)
    return ordered, issues


def full_text(research_run: ResearchRun, nd: NoveltyDifferentiationRun, item: GapInventoryText) -> str | None:
    """The exact string ``item``'s offsets index into, re-read from its source
    record and hash-checked. ``None`` when the source record is gone or changed."""
    if item.source_kind is GapSourceKind.ACADEMIC_EVIDENCE:
        extraction = research_run.evidence_extraction
        if extraction is None:
            return None
        evidence = next((e for e in extraction.verified_evidence if e.evidence_id == item.source_record_id), None)
        snapshot = next((s for s in extraction.content_snapshots if evidence and s.content_id == evidence.content_id), None)
        body = snapshot.text if snapshot else None
    else:
        body = None
        for profile in nd.candidate_profiles:
            text = profile.text(item.source_record_id)
            if text is not None:
                body = resolve_prior_art_text(research_run, text)
                break
    return body if body is not None and digest(body) == item.text_hash else None


@dataclass(frozen=True)
class ShownText:
    token: str
    item: GapInventoryText
    shown: str
    offset: int
    """Absolute offset of ``shown[0]`` inside the full text."""
    bounded: bool

    def absolute(self, located: Located) -> tuple[int, int]:
        return located.start + self.offset, located.end + self.offset


def select_texts(
    visible: list[GapInventoryText],
    resolve: dict[UUID, str | None],
    bounds: GapAssessmentBounds,
) -> tuple[list[ShownText], list[UUID]]:
    """Deterministic, bounded selection. Returns (shown, omitted_text_ids).

    A text shown only as a prefix, or not shown at all, is NOT covered: the
    counterevidence review reads an incomplete view and says so.
    """
    shown: list[ShownText] = []
    omitted: list[UUID] = []
    budget = bounds.max_chars_per_call
    for item in sorted(visible, key=canonical_order):
        body = resolve.get(item.inventory_text_id)
        if body is None:
            omitted.append(item.inventory_text_id)
            continue
        region = body[item.span_start : item.span_end]
        text = region[: bounds.max_chars_per_text]
        cut = len(text) < len(region)
        if len(shown) >= bounds.max_texts_per_claim or len(text) > budget:
            omitted.append(item.inventory_text_id)
            continue
        budget -= len(text)
        shown.append(ShownText(
            token=f"T{len(shown) + 1}", item=item, shown=text, offset=item.span_start, bounded=cut,
        ))
        if cut:
            omitted.append(item.inventory_text_id)
    return shown, omitted


def locate_in_shown(
    shown: ShownText, excerpt: str, *, start: int | None = None, end: int | None = None,
    occurrence: int | None = None,
) -> Located | LocateFailure:
    """Exact location inside what the model was shown, never first-occurrence guessing."""
    return locate(shown.shown, excerpt, start=start, end=end, occurrence=occurrence)


__all__ = [
    "InventoryIssue",
    "ShownText",
    "LIMITATION_INELIGIBLE_TEXT_KINDS",
    "build_inventory",
    "canonical_order",
    "digest",
    "full_text",
    "gap_run_id_for",
    "locate_in_shown",
    "prior_art_quality",
    "select_texts",
]
