"""Deterministic verification shared by every Phase 3B model stage.

The model only ever points at text or at labels. ``ExperimentLedger`` decides, in
code, whether a pointer is real: an excerpt must be a literal slice of the bound
submission at exactly one validated occurrence (``locate``: no first-occurrence
guessing, no fuzzy matching), and it must not overlap a quarantined result span.
The stored text is always ``submission[start:end]``, never the model's string.

Nothing the model wrote is persisted. A refusal is recorded as a code and a
sha256 digest of the model's text, so neither prose nor a leaked hidden prompt
can reach a checkpoint, in any language (ADR-023).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.llm.prompts import (
    EXPERIMENT_APPLICABILITY_PROMPT_V1,
    EXPERIMENT_PROTOCOL_EXTRACTION_PROMPT_V1,
    EXPERIMENT_SEGMENTATION_PROMPT_V1,
    EXPERIMENT_TARGET_LINKAGE_PROMPT_V1,
)
from src.research.experiments.dto import SpanDTO
from src.research.methodology.verify import METHODOLOGY_FORBIDDEN_MARKERS
from src.research.novelty.anchoring import Located, LocateFailure, locate
from src.schemas.discovery import MAX_SAFE_SUMMARY_LENGTH
from src.schemas.experiment_review import (
    RUN_ISSUE_EMITTERS,
    ExperimentReviewBounds,
    ExperimentReviewRun,
    ExperimentRunIssue,
    ExperimentRunIssueCode,
    ExperimentStage,
    QuarantinedSpan,
    RejectedExperimentProposal,
    StudentExperimentExcerpt,
    _overlaps,
    experiment_uuid,
    text_hash,
)

MAX_RECORDED_REJECTIONS = 500
QUARANTINE_PLACEHOLDER = "[RESULT WITHHELD]"

_C = ExperimentRunIssueCode
_FRAGMENT_MIN_CHARS = 40
_PROMPT_FRAGMENTS: tuple[str, ...] = tuple(
    line.strip().casefold()
    for prompt in (
        EXPERIMENT_SEGMENTATION_PROMPT_V1,
        EXPERIMENT_PROTOCOL_EXTRACTION_PROMPT_V1,
        EXPERIMENT_APPLICABILITY_PROMPT_V1,
        EXPERIMENT_TARGET_LINKAGE_PROMPT_V1,
    )
    for line in prompt.splitlines()
    if len(line.strip()) >= _FRAGMENT_MIN_CHARS
)

EXPERIMENT_FORBIDDEN_MARKERS: tuple[str, ...] = (
    *METHODOLOGY_FORBIDDEN_MARKERS,
    "well specified",
    "well_specified",
    "execution verified",
    "execution was verified",
    "result verified",
    "results are verified",
    "claim is supported",
    "baseline is fair",
    "the comparison is fair",
)
"""English phrases an advisory rationale must never carry. One that does is the
model following an instruction rather than classifying text; the item is refused.
Nothing from a rationale is ever persisted. Defense in depth only: the typed
contract (no free-text canonical field) is the language-independent defense."""


def discloses_system_prompt(text: str | None, submission_text: str) -> bool:
    if not text:
        return False
    folded, source = text.casefold(), submission_text.casefold()
    return any(f in folded and f not in source for f in _PROMPT_FRAGMENTS)


def forbidden_conclusion(text: str | None) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in EXPERIMENT_FORBIDDEN_MARKERS)


def parse_enum(enum_type, value: str | None):  # noqa: ANN001
    try:
        return enum_type((value or "").strip().upper())
    except ValueError:
        return None


def masked_submission(text: str, quarantine: list[QuarantinedSpan]) -> str:
    """The submission with every quarantined result span withheld. Later model calls
    see this text only, so a reported value cannot steer a protocol judgment."""
    merged: list[list[int]] = []
    for q in sorted(quarantine, key=lambda q: (q.start, q.end)):
        if merged and q.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], q.end)
        else:
            merged.append([q.start, q.end])
    out, cursor = [], 0
    for start, end in merged:
        out += [text[cursor:start], QUARANTINE_PLACEHOLDER]
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


@dataclass
class ExperimentLedger:
    """One stage's working set. Created from the persisted run, folded back into it."""

    run: ExperimentReviewRun
    submission_text: str
    bounds: ExperimentReviewBounds
    stage: ExperimentStage
    excerpts: dict[UUID, StudentExperimentExcerpt] = field(default_factory=dict)
    rejected: list[RejectedExperimentProposal] = field(default_factory=list)
    issues: dict[ExperimentRunIssueCode, ExperimentRunIssue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.excerpts = {e.excerpt_id: e for e in self.run.excerpts}

    # -- rejection and issues -------------------------------------------------------

    def emit(self, code: ExperimentRunIssueCode, message: str, experiment_id: UUID | None = None) -> None:
        """One run issue per code per stage. A code this stage cannot emit is reported as
        PARTIAL_MODEL_OUTPUT (part of the response was refused); the precise code stays in
        the rejection digest."""
        if self.stage not in RUN_ISSUE_EMITTERS[code]:
            code = _C.PARTIAL_MODEL_OUTPUT
        if code not in self.issues:
            self.issues[code] = ExperimentRunIssue(
                code=code, node=self.stage, message=message[:MAX_SAFE_SUMMARY_LENGTH], experiment_id=experiment_id)

    def reject(self, code: ExperimentRunIssueCode, model_text: str = "", message: str | None = None) -> None:
        self.rejected.append(RejectedExperimentProposal(
            code=code, stage=self.stage, response_digest=text_hash(model_text or code.value)))
        self.emit(code, message or f"model output refused: {code.value}")

    def unsafe(self, *texts: str | None) -> bool:
        """True (and recorded) when model prose discloses a hidden prompt or carries a
        forbidden conclusion. The carrying item is refused by the caller."""
        for text in texts:
            if discloses_system_prompt(text, self.submission_text):
                self.reject(_C.PROMPT_LEAK_REDACTED, text or "", "hidden prompt disclosure redacted")
                return True
            if forbidden_conclusion(text):
                self.reject(_C.SOURCE_INSTRUCTION_FOLLOWED, text or "", "model prose followed a source instruction")
                return True
        return False

    # -- anchoring ----------------------------------------------------------------

    def locate_span(self, span: SpanDTO | None) -> Located | None:
        if span is None:
            return None
        text = span.excerpt or ""
        if not text.strip():
            self.reject(_C.EXACT_EXCERPT_MISMATCH, text)
            return None
        if len(text) > self.bounds.max_excerpt_chars:
            self.reject(_C.PARTIAL_MODEL_OUTPUT, text, "an excerpt exceeds the excerpt bound")
            return None
        located = locate(self.submission_text, text, start=span.start, end=span.end, occurrence=span.occurrence)
        if isinstance(located, LocateFailure):
            self.reject(_C.AMBIGUOUS_EXCERPT if located is LocateFailure.AMBIGUOUS else _C.EXACT_EXCERPT_MISMATCH,
                        text)
            return None
        return located

    def anchor(self, span: SpanDTO | None) -> UUID | None:
        """The id of the verified protocol excerpt for ``span``, or None (and a recorded
        rejection). A span overlapping a quarantined result is refused: result text can
        never become protocol evidence."""
        located = self.locate_span(span)
        if located is None:
            return None
        if any(_overlaps(located.start, located.end, q.start, q.end) for q in self.run.quarantine):
            self.reject(_C.RESULT_LEAKAGE_ATTEMPT, span.excerpt, "a protocol excerpt overlapped a quarantined result")
            return None
        excerpt_id = experiment_uuid(self.run.experiment_run_id, "excerpt", located.start, located.end)
        if excerpt_id in self.excerpts:
            return excerpt_id
        if len(self.excerpts) >= self.bounds.max_excerpts:
            self.reject(_C.PARTIAL_MODEL_OUTPUT, span.excerpt, "the excerpt bound was reached")
            return None
        self.excerpts[excerpt_id] = StudentExperimentExcerpt(
            excerpt_id=excerpt_id, experiment_run_id=self.run.experiment_run_id,
            submission_artifact_id=self.run.submission_artifact_id,  # type: ignore[arg-type]
            submission_content_hash=self.run.submission_content_hash,  # type: ignore[arg-type]
            excerpt=self.submission_text[located.start:located.end], start=located.start, end=located.end,
            occurrence_count=located.occurrence_count, occurrence_index=located.occurrence_index,
            occurrence_resolution=located.resolution,
        )
        return excerpt_id

    def ordered(self, ids: list[UUID]) -> list[UUID]:
        """A set in document order: the model's list order is never canonical."""
        return sorted(dict.fromkeys(ids), key=lambda i: (self.excerpts[i].start, self.excerpts[i].end, str(i)))

    # -- fold back ----------------------------------------------------------------

    def run_issues(self) -> list[ExperimentRunIssue]:
        return [*self.run.errors, *(self.issues[c] for c in sorted(self.issues))]

    def merged_rejections(self) -> list[RejectedExperimentProposal]:
        return [*self.run.rejected_proposals, *self.rejected][:MAX_RECORDED_REJECTIONS]

    def sorted_excerpts(self) -> list[StudentExperimentExcerpt]:
        return sorted(self.excerpts.values(), key=lambda e: (e.start, e.end, str(e.excerpt_id)))


__all__ = [
    "EXPERIMENT_FORBIDDEN_MARKERS",
    "MAX_RECORDED_REJECTIONS",
    "QUARANTINE_PLACEHOLDER",
    "ExperimentLedger",
    "discloses_system_prompt",
    "forbidden_conclusion",
    "masked_submission",
    "parse_enum",
]
