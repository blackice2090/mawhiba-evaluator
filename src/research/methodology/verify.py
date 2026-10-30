"""Deterministic verification shared by every Phase 3A model stage.

The model only ever points at text. ``StageLedger`` decides, in code, whether a
pointer is real: an excerpt must be a literal slice of the bound submission at
exactly one validated occurrence. Nothing is fuzzy-matched, paraphrased,
translated or first-occurrence guessed, and the stored text is always
``submission[start:end]``, never the model's string (ADR-022).

Nothing the model wrote is persisted. A refusal is recorded as a code and a
sha256 digest of the model's text, so neither prose nor a leaked hidden prompt
can reach a checkpoint, in any language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.llm.prompts import (
    METHODOLOGY_APPLICABILITY_PROMPT_V1,
    METHODOLOGY_EVIDENCE_EXTRACTION_PROMPT_V1,
    METHODOLOGY_METRIC_BASELINE_PROMPT_V1,
    METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1,
    METHODOLOGY_TARGET_LINKAGE_PROMPT_V1,
)
from src.research.gap.verify import FORBIDDEN_CONCLUSION_MARKERS
from src.research.methodology.dto import SubmissionSpanDTO
from src.research.novelty.anchoring import LocateFailure, locate
from src.schemas.discovery import MAX_SAFE_SUMMARY_LENGTH
from src.schemas.methodology_review import (
    MethodologyReviewBounds,
    MethodologyReviewRun,
    MethodologyRunIssue,
    MethodologyRunIssueCode,
    RejectedMethodologyProposal,
    StatementMode,
    StudentMethodologyExcerpt,
    methodology_id,
    text_hash,
)

MAX_RECORDED_REJECTIONS = 500

_FRAGMENT_MIN_CHARS = 40
_PROMPT_FRAGMENTS: tuple[str, ...] = tuple(
    line.strip().casefold()
    for prompt in (
        METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1,
        METHODOLOGY_EVIDENCE_EXTRACTION_PROMPT_V1,
        METHODOLOGY_APPLICABILITY_PROMPT_V1,
        METHODOLOGY_METRIC_BASELINE_PROMPT_V1,
        METHODOLOGY_TARGET_LINKAGE_PROMPT_V1,
    )
    for line in prompt.splitlines()
    if len(line.strip()) >= _FRAGMENT_MIN_CHARS
)

METHODOLOGY_FORBIDDEN_MARKERS: tuple[str, ...] = (
    *FORBIDDEN_CONCLUSION_MARKERS,
    "experiment succeeded",
    "results confirm",
    "the control worked",
    "confounding was eliminated",
    "leakage was prevented",
    "methodology is sound",
    "methodology is flawless",
)
"""English phrases an advisory rationale must never carry. One that does is the
model following an instruction rather than classifying text; the item is refused.
Nothing from a rationale is ever persisted. This is defense in depth: the typed
contract (no free-text canonical field) is the language-independent defense."""


def discloses_system_prompt(text: str | None, submission_text: str) -> bool:
    """Model output reproducing a line of a hidden prompt that the submission itself
    does not contain: that is instruction-following, not source data."""
    if not text:
        return False
    folded, source = text.casefold(), submission_text.casefold()
    return any(f in folded and f not in source for f in _PROMPT_FRAGMENTS)


def forbidden_conclusion(text: str | None) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in METHODOLOGY_FORBIDDEN_MARKERS)


def parse_enum(enum_type, value: str | None):  # noqa: ANN001
    try:
        return enum_type((value or "").strip().upper())
    except ValueError:
        return None


@dataclass
class StageLedger:
    """One stage's working set. Created from the persisted run, folded back into it."""

    run: MethodologyReviewRun
    submission_text: str
    bounds: MethodologyReviewBounds
    language: str | None = None
    excerpts: dict[UUID, StudentMethodologyExcerpt] = field(default_factory=dict)
    rejected: list[RejectedMethodologyProposal] = field(default_factory=list)
    issues: list[MethodologyRunIssue] = field(default_factory=list)
    off_contract: int = 0
    leaked: bool = False
    forbidden: bool = False

    def __post_init__(self) -> None:
        self.excerpts = {e.excerpt_id: e for e in self.run.excerpts}

    # -- rejection ------------------------------------------------------------

    def reject(self, code: MethodologyRunIssueCode, model_text: str = "", *, claim_id: str | None = None,
               off_contract: bool = False) -> None:
        if off_contract:
            self.off_contract += 1
        self.rejected.append(RejectedMethodologyProposal(
            claim_id=claim_id, code=code, response_digest=text_hash(model_text or code.value)))

    def unsafe(self, node: str, *texts: str | None) -> bool:
        """True (and recorded) when model prose discloses a hidden prompt or carries a
        forbidden conclusion. The carrying item is refused by the caller."""
        for text in texts:
            if discloses_system_prompt(text, self.submission_text):
                if not self.leaked:
                    self.issues.append(MethodologyRunIssue(
                        code=MethodologyRunIssueCode.PROMPT_LEAK_REDACTED, node=node,
                        message="hidden prompt disclosure redacted"))
                    self.leaked = True
                self.reject(MethodologyRunIssueCode.PROMPT_LEAK_REDACTED, text or "")
                return True
            if forbidden_conclusion(text):
                if not self.forbidden:
                    self.issues.append(MethodologyRunIssue(
                        code=MethodologyRunIssueCode.FORBIDDEN_CONCLUSION, node=node,
                        message="forbidden conclusion in model prose"))
                    self.forbidden = True
                self.reject(MethodologyRunIssueCode.FORBIDDEN_CONCLUSION, text or "")
                return True
        return False

    # -- anchoring ------------------------------------------------------------

    def anchor(self, span: SubmissionSpanDTO | None, mode: StatementMode = StatementMode.MODE_NOT_DETERMINED
               ) -> UUID | None:
        """The id of the verified excerpt for ``span``, or None (and a recorded rejection)."""
        if span is None:
            return None
        text = (span.excerpt or "").strip()
        if not text:
            self.reject(MethodologyRunIssueCode.FABRICATED_EXCERPT, span.excerpt or "")
            return None
        if len(text) > self.bounds.max_excerpt_chars:
            self.reject(MethodologyRunIssueCode.INVALID_INPUT, text)
            return None
        located = locate(self.submission_text, text, start=span.start, end=span.end, occurrence=span.occurrence)
        if isinstance(located, LocateFailure):
            code = (MethodologyRunIssueCode.AMBIGUOUS_EXCERPT if located is LocateFailure.AMBIGUOUS
                    else MethodologyRunIssueCode.FABRICATED_EXCERPT)
            self.reject(code, text)
            return None
        excerpt_id = methodology_id(self.run.methodology_run_id, "excerpt", located.start, located.end)
        if excerpt_id in self.excerpts:
            return excerpt_id
        if len(self.excerpts) >= self.bounds.max_excerpts:
            self.reject(MethodologyRunIssueCode.INVALID_INPUT, text)
            return None
        self.excerpts[excerpt_id] = StudentMethodologyExcerpt(
            excerpt_id=excerpt_id, methodology_run_id=self.run.methodology_run_id,
            submission_artifact_id=self.run.submission_artifact_id,  # type: ignore[arg-type]
            submission_content_hash=self.run.submission_content_hash,  # type: ignore[arg-type]
            excerpt=self.submission_text[located.start:located.end], start=located.start, end=located.end,
            occurrence_count=located.occurrence_count, occurrence_index=located.occurrence_index,
            occurrence_resolution=located.resolution, statement_mode=mode, language=self.language,
        )
        return excerpt_id

    # -- fold back ------------------------------------------------------------

    def run_issues(self, node: str) -> list[MethodologyRunIssue]:
        out = list(self.issues)
        if self.off_contract:
            out.append(MethodologyRunIssue(
                code=MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, node=node,
                message=f"{self.off_contract} model output(s) outside the typed contract were refused"[
                    :MAX_SAFE_SUMMARY_LENGTH]))
        return out

    def merged_rejections(self) -> list[RejectedMethodologyProposal]:
        return [*self.run.rejected_proposals, *self.rejected][:MAX_RECORDED_REJECTIONS]

    def sorted_excerpts(self) -> list[StudentMethodologyExcerpt]:
        return sorted(self.excerpts.values(), key=lambda e: (e.start, e.end))


__all__ = [
    "MAX_RECORDED_REJECTIONS",
    "METHODOLOGY_FORBIDDEN_MARKERS",
    "StageLedger",
    "discloses_system_prompt",
    "forbidden_conclusion",
    "parse_enum",
]
