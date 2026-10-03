"""Deterministic verification shared by every Phase 2J model stage.

The model only ever points at text. These helpers decide, in code, whether a
pointer is real: the excerpt must lie in a text the model was actually shown,
at exactly one validated occurrence. Nothing is fuzzy-matched, paraphrased,
translated or first-occurrence guessed (ADR-021).
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from src.llm.prompts import (
    GAP_CANDIDATE_EXTRACTION_PROMPT_V1,
    GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1,
    GAP_PROJECT_LINKAGE_PROMPT_V1,
)
from src.research.gap.inventory import ShownText, locate_in_shown
from src.research.novelty.anchoring import LocateFailure
from src.schemas.discovery import MAX_SAFE_SUMMARY_LENGTH
from src.schemas.gap_assessment import (
    PROMPT_LEAK_REDACTION_MARKER,
    GapEvidenceRef,
    GapEvidenceRole,
    RejectedGapProposal,
    gap_id,
)

R_UNKNOWN_TEXT = "UNKNOWN_TEXT_REFERENCE"
R_EMPTY_EXCERPT = "EMPTY_EXCERPT"
R_NOT_IN_TEXT = "EXCERPT_NOT_IN_TEXT"
R_CLAIM_AS_EVIDENCE = "CLAIM_TEXT_AS_EVIDENCE"
R_AMBIGUOUS = "AMBIGUOUS_REPEATED_EXCERPT"
R_INVALID_OFFSETS = "INVALID_OFFSETS"
R_INVALID_OCCURRENCE = "INVALID_OCCURRENCE_INDEX"
R_PROMPT_DISCLOSURE = "SYSTEM_PROMPT_DISCLOSURE"
R_FORBIDDEN_CONCLUSION = "FORBIDDEN_CONCLUSION"
R_INELIGIBLE_SOURCE = "INELIGIBLE_SOURCE_FOR_ROLE"
R_INVALID_TYPE = "INVALID_LIMITATION_TYPE"
R_INVALID_FACET = "INVALID_FACET"
R_FACET_TYPE = "FACET_INELIGIBLE_FOR_TYPE"
R_INVALID_DIMENSION = "INVALID_CONDITION_DIMENSION"
R_SCOPE_NEEDS_DIMENSION = "SCOPE_RESTRICTION_WITHOUT_DIMENSION"
R_SHORTFALL_NO_NUMBER = "MEASURED_SHORTFALL_WITHOUT_NUMBER"
R_DUPLICATE_PROPOSITION = "DUPLICATE_PROPOSITION"
R_DUPLICATE_LABEL = "DUPLICATE_LABEL"
R_INADMISSIBLE_BASIS = "INADMISSIBLE_LIMITATION_BASIS"
R_INVENTED_METRIC = "INVENTED_METRIC"
R_INVENTED_BASELINE = "INVENTED_BASELINE"
R_UNKNOWN_LABEL = "UNKNOWN_LABEL"
R_INVALID_RELATION = "INVALID_RELATION"
R_INVALID_KIND = "INVALID_COUNTEREVIDENCE_KIND"
R_BOUND = "BOUND_EXCEEDED"
R_DUPLICATE_JUDGMENT = "DUPLICATE_JUDGMENT"
R_SELF_COUNTER = "COUNTEREVIDENCE_IS_THE_LIMITATION_SPAN"

_FRAGMENT_MIN_CHARS = 40
_PROMPT_FRAGMENTS: tuple[str, ...] = tuple(
    line.strip().casefold()
    for prompt in (
        GAP_CANDIDATE_EXTRACTION_PROMPT_V1, GAP_PROJECT_LINKAGE_PROMPT_V1, GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1,
    )
    for line in prompt.splitlines()
    if len(line.strip()) >= _FRAGMENT_MIN_CHARS
)

FORBIDDEN_CONCLUSION_MARKERS: tuple[str, ...] = (
    "is novel",
    "not novel",
    "is patentable",
    "unpatentable",
    "will win",
    "definitely a new",
    "no one has studied",
    "no existing product",
    "methodology is valid",
    "experiment proves",
    "proves the gap",
    "level 4",
    "level 5",
    "score of",
    "readiness",
)
"""English phrases a rationale must never carry (section 20). A rationale that
does is the model following an instruction rather than classifying text; it is
refused. Nothing from a rationale is ever persisted as a finding."""


OFF_CONTRACT_REASONS: frozenset[str] = frozenset({
    R_INVALID_TYPE, R_INVALID_FACET, R_INVALID_DIMENSION, R_UNKNOWN_LABEL, R_INVALID_RELATION, R_INVALID_KIND,
    R_INADMISSIBLE_BASIS, R_UNKNOWN_TEXT,
})
"""Rejections that mean the model answered OUTSIDE the typed contract: a value no
enum holds, a label or text that was never shown, an absence basis. This is how
instruction-following is detected without reading prose, so it works in every
language."""


def off_contract_issue(node: str, claim_id: str, rejected: list[RejectedGapProposal]) -> list:
    from src.schemas.gap_assessment import GapAssessmentIssue, GapIssueCode

    count = sum(1 for r in rejected if r.reason in OFF_CONTRACT_REASONS)
    if not count:
        return []
    return [GapAssessmentIssue(code=GapIssueCode.OFF_CONTRACT_OUTPUT, node=node, claim_id=claim_id,
                               message=f"{count} model output(s) outside the typed contract were refused")]


def discloses_system_prompt(text: str | None, shown_texts: list[str]) -> bool:
    """Model output reproducing a line of the hidden prompt that no shown text
    itself contains. That is instruction-following (section 19), not source data."""
    if not text:
        return False
    folded = text.casefold()
    sources = [t.casefold() for t in shown_texts]
    return any(f in folded and not any(f in s for s in sources) for f in _PROMPT_FRAGMENTS)


def forbidden_conclusion(text: str | None) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in FORBIDDEN_CONCLUSION_MARKERS)


def rejection(
    claim_id: str, reason: str, *, model_text: str = "", note: str = "", basis=None
) -> RejectedGapProposal:
    """A refused proposal. NO model-originated text is ever persisted.

    ``note`` is a code-originated constant (a bound name, an enum value);
    ``model_text`` is whatever the model wrote and is stored only as a length
    and a digest -- so a leaked hidden prompt, in any language and in any field,
    cannot reach a checkpoint through the rejection ledger. A system-prompt
    disclosure additionally carries the redaction marker."""
    if reason == R_PROMPT_DISCLOSURE:
        text = PROMPT_LEAK_REDACTION_MARKER
    elif note:
        text = note[:MAX_SAFE_SUMMARY_LENGTH]
    elif model_text:
        text = f"model text withheld: sha256={sha256(model_text.encode('utf-8')).hexdigest()[:16]} chars={len(model_text)}"
    else:
        text = ""
    return RejectedGapProposal(claim_id=claim_id, reason=reason, inadmissible_basis=basis, safe_summary=text)


@dataclass(frozen=True)
class VerifiedSpan:
    shown: ShownText
    start: int
    end: int
    occurrence_count: int
    occurrence_index: int
    resolution: object
    excerpt: str


_LOCATE_REASON = {
    LocateFailure.AMBIGUOUS: R_AMBIGUOUS,
    LocateFailure.INVALID_OFFSETS: R_INVALID_OFFSETS,
    LocateFailure.INVALID_OCCURRENCE: R_INVALID_OCCURRENCE,
}


def verify_span(
    by_token: dict[str, ShownText], token: str, excerpt: str, *, start: int | None, end: int | None,
    occurrence: int | None, claim_text: str,
) -> VerifiedSpan | str:
    """The verified span, or the rejection reason. Never raises."""
    key = (token or "").strip().upper()
    shown = by_token.get(key)
    if shown is None:
        return R_UNKNOWN_TEXT
    if not excerpt:
        return R_EMPTY_EXCERPT
    located = locate_in_shown(shown, excerpt, start=start, end=end, occurrence=occurrence)
    if located is LocateFailure.NOT_FOUND:
        return R_CLAIM_AS_EVIDENCE if excerpt in claim_text else R_NOT_IN_TEXT
    if isinstance(located, LocateFailure):
        return _LOCATE_REASON[located]
    absolute_start, absolute_end = shown.absolute(located)
    return VerifiedSpan(
        shown=shown, start=absolute_start, end=absolute_end, occurrence_count=located.occurrence_count,
        occurrence_index=located.occurrence_index, resolution=located.resolution, excerpt=excerpt,
    )


def make_ref(gap_run_id: UUID, claim_id: str, role: GapEvidenceRole, span: VerifiedSpan) -> GapEvidenceRef:
    item = span.shown.item
    return GapEvidenceRef(
        evidence_ref_id=gap_id(gap_run_id, claim_id, role.value, item.source_record_id, span.start, span.end),
        source_kind=item.source_kind,
        source_record_id=item.source_record_id,
        upstream_run_id=item.upstream_run_id,
        candidate_id=item.candidate_id,
        text_kind=item.text_kind,
        text_hash=item.text_hash,
        excerpt=span.excerpt,
        start=span.start,
        end=span.end,
        occurrence_count=span.occurrence_count,
        occurrence_index=span.occurrence_index,
        occurrence_resolution=span.resolution,  # type: ignore[arg-type]
        role=role,
        independence_basis=item.independence_basis,
        independence_key=item.independence_key,
        counts_as_independent=item.counts_as_independent,
        correlation_group_key=item.correlation_group_key,
        inherited_unit=item.inherited_unit,
        source_quality=item.source_quality,
        is_review_source=item.is_review_source,
        language=item.language,
    )


def shown_texts_of(by_token: dict[str, ShownText]) -> list[str]:
    return [t.shown for t in by_token.values()]


__all__ = [
    "FORBIDDEN_CONCLUSION_MARKERS",
    "VerifiedSpan",
    "discloses_system_prompt",
    "forbidden_conclusion",
    "OFF_CONTRACT_REASONS",
    "make_ref",
    "off_contract_issue",
    "rejection",
    "shown_texts_of",
    "verify_span",
]
