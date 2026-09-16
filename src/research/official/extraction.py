"""Official requirement extraction with provenance, and conflict handling.

Model output from an official page is an untrusted candidate. A requirement is
accepted only when its excerpt verifies inside the snapshot text; its canonical
statement is that excerpt. A weight survives only when its exact text is inside
the verified statement -- otherwise ``official_weight`` stays ``None``.

A requirement inherits its snapshot's currency: an anchor-verified rule from a
past edition is HISTORICAL, kept and never applied.
"""

from __future__ import annotations

import re

from src.config.settings import LLMSettings
from src.intake.anchors import collapse_whitespace, normalize_unicode, verify_anchor
from src.llm.contracts import ModelCallResult, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import (
    OFFICIAL_PAGE_MARKER,
    OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT_V1,
    PROMPT_VERSIONS,
)
from src.llm.provider import StructuredModelProvider
from src.research.vocabulary import ALL_INJECTION_MARKERS
from src.schemas.official import (
    CURRENCY_TO_REQUIREMENT_STATUS,
    WEIGHT_BEARING_CATEGORIES,
    ConflictResolutionBasis,
    ConflictSide,
    OfficialRequirement,
    OfficialRequirementCategory,
    OfficialRequirementConflict,
    OfficialRequirementsExtraction,
    OfficialRequirementStatus,
    OfficialSourceSnapshot,
    RejectedOfficialRequirement,
    RequirementRejectionReason,
    WeightRejectionReason,
)

EXTRACTOR_VERSION = (
    "OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT_"
    f"{PROMPT_VERSIONS['OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT']}"
)

_PERCENT_SIGNS = "%" + chr(0x066A)
_WEIGHT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[" + _PERCENT_SIGNS + r"]?\s*$")


def build_official_extraction_input(snapshot: OfficialSourceSnapshot) -> str:
    return (
        f"source_id: {snapshot.source_id}\n"
        f"url: {snapshot.canonical_url}\n"
        f"{OFFICIAL_PAGE_MARKER}\n{snapshot.captured_text}"
    )


def run_official_extraction(
    snapshot: OfficialSourceSnapshot,
    provider: StructuredModelProvider,
    settings: LLMSettings,
) -> ModelCallResult[OfficialRequirementsExtraction]:
    return call_structured_model_with_retries(
        provider,
        task=ModelTask.OFFICIAL_REQUIREMENTS_EXTRACTION,
        system_prompt=OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT_V1,
        user_input=build_official_extraction_input(snapshot),
        response_model=OfficialRequirementsExtraction,
        model=settings.official_extraction_model,
        max_retries=settings.max_retries,
    )


def _fold(text: str) -> str:
    return collapse_whitespace(normalize_unicode(text)).casefold()


def looks_like_injection(text: str) -> bool:
    """Instruction-like text in either language. Page content is data, never a command."""
    folded = f" {_fold(text)} "
    return any(f" {marker}" in folded for marker in ALL_INJECTION_MARKERS)


def _parse_weight(text: str) -> float | None:
    match = _WEIGHT.match(normalize_unicode(text))
    return float(match.group(1)) if match else None


def verify_official_requirements(
    snapshot: OfficialSourceSnapshot, extraction: OfficialRequirementsExtraction
) -> tuple[list[OfficialRequirement], list[RejectedOfficialRequirement]]:
    accepted: list[OfficialRequirement] = []
    rejected: list[RejectedOfficialRequirement] = []
    status = CURRENCY_TO_REQUIREMENT_STATUS[snapshot.currency]

    for candidate in extraction.requirements:
        def reject(reason: RequirementRejectionReason) -> None:
            rejected.append(
                RejectedOfficialRequirement(
                    source_id=snapshot.source_id,
                    candidate_category=candidate.category,
                    candidate_statement=candidate.statement,
                    candidate_excerpt=candidate.excerpt,
                    rejection_reason=reason,
                )
            )

        try:
            category = OfficialRequirementCategory(candidate.category.strip())
        except ValueError:
            reject(RequirementRejectionReason.INVALID_CATEGORY)
            continue
        if not candidate.subject.strip():
            reject(RequirementRejectionReason.EMPTY_SUBJECT)
            continue
        if not candidate.statement.strip():
            reject(RequirementRejectionReason.EMPTY_STATEMENT)
            continue
        if not candidate.excerpt.strip():
            reject(RequirementRejectionReason.EMPTY_EXCERPT)
            continue
        anchor = verify_anchor(snapshot.snapshot_id, snapshot.captured_text, candidate.excerpt)
        if not anchor.verified:
            reject(RequirementRejectionReason.ANCHOR_NOT_FOUND)
            continue
        if looks_like_injection(candidate.excerpt) or looks_like_injection(candidate.statement):
            reject(RequirementRejectionReason.SUSPECTED_PROMPT_INJECTION)
            continue

        statement = candidate.excerpt.strip()
        weight: float | None = None
        weight_text: str | None = None
        weight_rejection: WeightRejectionReason | None = None
        raw_weight = (candidate.official_weight_text or "").strip()
        if raw_weight:
            if category not in WEIGHT_BEARING_CATEGORIES:
                weight_rejection = WeightRejectionReason.WEIGHT_NOT_ALLOWED_FOR_CATEGORY
            elif raw_weight.casefold() not in statement.casefold():
                weight_rejection = WeightRejectionReason.WEIGHT_NOT_IN_OFFICIAL_TEXT
            else:
                weight_text = raw_weight
                weight = _parse_weight(raw_weight)
                if weight is None:
                    weight_rejection = WeightRejectionReason.WEIGHT_NOT_NUMERIC

        date_text = (candidate.stated_date_text or "").strip() or None
        if date_text and date_text.casefold() not in statement.casefold():
            date_text = None

        accepted.append(
            OfficialRequirement(
                source_id=snapshot.source_id,
                snapshot_id=snapshot.snapshot_id,
                content_hash=snapshot.content_hash,
                category=category,
                subject=candidate.subject.strip(),
                statement=statement,
                model_summary=candidate.statement if candidate.statement.strip() != statement else None,
                anchor=anchor,
                official_weight=weight,
                official_weight_text=weight_text,
                weight_rejection=weight_rejection,
                stated_date_text=date_text,
                competition_edition=snapshot.competition_edition,
                status=status,
                retrieved_at=snapshot.retrieved_at,
            )
        )

    return accepted, rejected


def _single_newest(sides: list[tuple[OfficialRequirement, object]]) -> OfficialRequirement | None:
    """The one requirement whose source is strictly newest, or None."""
    values = [value for _, value in sides]
    if any(value is None for value in values):
        return None
    newest = max(values)
    winners = [req for req, value in sides if value == newest]
    return winners[0] if len({req.source_id for req in winners}) == 1 else None


def detect_official_conflicts(
    requirements: list[OfficialRequirement], snapshots: list[OfficialSourceSnapshot]
) -> tuple[list[OfficialRequirement], list[OfficialRequirementConflict]]:
    """Preserve disagreements between official sources.

    Items conflict when they share a category and subject, come from different
    sources, and state different text or weights. Resolution is explicit and
    ordered: a newer competition edition, then a newer effective date, then a newer
    publication date. Otherwise the conflict stays unresolved and every side is
    marked CONFLICTED. Nothing is discarded.
    """
    by_source = {s.source_id: s for s in snapshots}
    groups: dict[tuple[OfficialRequirementCategory, str], list[OfficialRequirement]] = {}
    for requirement in requirements:
        groups.setdefault((requirement.category, _fold(requirement.subject)), []).append(requirement)

    new_status: dict[object, OfficialRequirementStatus] = {}
    conflicts: list[OfficialRequirementConflict] = []

    for (category, _), items in groups.items():
        if len({r.source_id for r in items}) < 2:
            continue
        if len({(_fold(r.statement), r.official_weight) for r in items}) < 2:
            continue

        by_edition = _single_newest([(r, r.competition_edition) for r in items])
        by_effective = _single_newest([(r, by_source[r.source_id].effective_at) for r in items])
        by_published = _single_newest([(r, by_source[r.source_id].published_at) for r in items])
        if by_edition is not None:
            basis, preferred = ConflictResolutionBasis.NEWER_COMPETITION_EDITION, by_edition
        elif by_effective is not None:
            basis, preferred = ConflictResolutionBasis.NEWER_EFFECTIVE_DATE, by_effective
        elif by_published is not None:
            basis, preferred = ConflictResolutionBasis.NEWER_PUBLICATION_DATE, by_published
        else:
            basis, preferred = ConflictResolutionBasis.UNRESOLVED, None

        for item in items:
            if item.status is OfficialRequirementStatus.HISTORICAL:
                continue  # already known to belong to a past edition
            if preferred is None:
                new_status[item.requirement_id] = OfficialRequirementStatus.CONFLICTED
            elif item.source_id != preferred.source_id:
                new_status[item.requirement_id] = OfficialRequirementStatus.SUPERSEDED

        conflicts.append(
            OfficialRequirementConflict(
                category=category,
                subject=items[0].subject,
                sides=[
                    ConflictSide(
                        requirement_id=r.requirement_id,
                        source_id=r.source_id,
                        statement=r.statement,
                        official_weight=r.official_weight,
                        competition_edition=r.competition_edition,
                        effective_at=by_source[r.source_id].effective_at,
                        published_at=by_source[r.source_id].published_at,
                    )
                    for r in items
                ],
                resolution_basis=basis,
                preferred_requirement_id=preferred.requirement_id if preferred else None,
            )
        )

    updated = [
        OfficialRequirement.model_validate(
            {**r.model_dump(), "status": new_status[r.requirement_id]}
        )
        if r.requirement_id in new_status
        else r
        for r in requirements
    ]
    return updated, conflicts
