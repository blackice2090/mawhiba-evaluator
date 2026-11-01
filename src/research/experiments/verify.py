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

from dataclasses import dataclass, field, replace
from uuid import UUID

from src.llm.prompts import (
    EXPERIMENT_APPLICABILITY_PROMPT_V1,
    EXPERIMENT_PROTOCOL_EXTRACTION_PROMPT_V1,
    EXPERIMENT_SEGMENTATION_PROMPT_V1,
    EXPERIMENT_TARGET_LINKAGE_PROMPT_V1,
    unescape_untrusted,
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


@dataclass(frozen=True)
class SourceWindow:
    """The one deterministic model-visible slice of the submission, in ORIGINAL coordinates.

    Everything that shows text to the model (segmentation, extraction) and everything that
    accepts an excerpt (the ledger, finalize) uses this same window, so a canonical excerpt
    can never point outside the text the model was shown. It is a pure function of the
    submission text and the run bounds, so a replay reproduces it exactly. Result masking
    happens INSIDE the window and only in the model's copy: offsets never shift."""

    start: int
    end: int

    @classmethod
    def of(cls, text: str, bounds: ExperimentReviewBounds) -> SourceWindow:
        return cls(0, min(len(text), bounds.max_submission_chars))

    def text(self, source: str) -> str:
        return source[self.start:self.end]

    def contains(self, start: int, end: int) -> bool:
        return self.start <= start < end <= self.end


def masked_submission(text: str, quarantine: list[QuarantinedSpan], window: SourceWindow | None = None) -> str:
    """The window of the submission with every quarantined result span withheld. Later model
    calls see this text only, so a reported value cannot steer a protocol judgment."""
    window = window or SourceWindow(0, len(text))
    merged: list[list[int]] = []
    for q in sorted(quarantine, key=lambda q: (q.start, q.end)):
        lo, hi = max(q.start, window.start) - window.start, min(q.end, window.end) - window.start
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    shown = window.text(text)
    out, cursor = [], 0
    for lo, hi in merged:
        out += [shown[cursor:lo], QUARANTINE_PLACEHOLDER]
        cursor = hi
    out.append(shown[cursor:])
    return "".join(out)


INCOMPLETE_QUARANTINE_MESSAGE = "result quarantine incomplete: a declared result span could not be safely quarantined"


def quarantine_incomplete(run: ExperimentReviewRun) -> bool:
    """True when segmentation declared a result span that could not be safely processed.
    It rests on persisted run issues, so it survives a checkpoint and a replay. It is NOT a
    claim that every real result was found: an undeclared result is a model-recall limit."""
    return any(e.node is ExperimentStage.SEGMENT_EXPERIMENTS and e.code is _C.PARTIAL_MODEL_OUTPUT
               and e.message == INCOMPLETE_QUARANTINE_MESSAGE for e in run.errors)


@dataclass
class ExperimentLedger:
    """One stage's working set. Created from the persisted run, folded back into it."""

    run: ExperimentReviewRun
    submission_text: str
    bounds: ExperimentReviewBounds
    stage: ExperimentStage
    excerpts: dict[UUID, StudentExperimentExcerpt] = field(default_factory=dict)
    rejected: list[RejectedExperimentProposal] = field(default_factory=list)
    issues: dict[tuple[str, str], ExperimentRunIssue] = field(default_factory=dict)
    window: SourceWindow = field(init=False)

    def __post_init__(self) -> None:
        self.excerpts = {e.excerpt_id: e for e in self.run.excerpts}
        self.window = SourceWindow.of(self.submission_text, self.bounds)

    def window_text(self) -> str:
        return self.window.text(self.submission_text)

    def shown_text(self) -> str:
        """What the model sees in extraction: the window, results withheld."""
        return masked_submission(self.submission_text, self.run.quarantine, self.window)

    # -- rejection and issues -------------------------------------------------------

    def emit(self, code: ExperimentRunIssueCode, message: str, experiment_id: UUID | None = None) -> None:
        """One run issue per code per stage. A code this stage cannot emit is reported as
        PARTIAL_MODEL_OUTPUT (part of the response was refused); the precise code stays in
        the rejection digest."""
        if self.stage not in RUN_ISSUE_EMITTERS[code]:
            code = _C.PARTIAL_MODEL_OUTPUT
        key = (code.value, message[:MAX_SAFE_SUMMARY_LENGTH])
        if key not in self.issues:
            self.issues[key] = ExperimentRunIssue(
                code=code, node=self.stage, message=key[1], experiment_id=experiment_id)

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
        """Exact location inside the model-visible window only. The model quotes the escaped
        prompt text; its quote is unescaped before matching, and the stored text is always the
        original slice. Text outside the window cannot be found, so it cannot be anchored."""
        if span is None:
            return None
        text = unescape_untrusted(span.excerpt or "")
        if not text.strip():
            self.reject(_C.EXACT_EXCERPT_MISMATCH, text)
            return None
        if len(text) > self.bounds.max_excerpt_chars:
            self.reject(_C.PARTIAL_MODEL_OUTPUT, text, "an excerpt exceeds the excerpt bound")
            return None
        w = self.window

        def shift(v: int | None) -> int | None:
            return None if v is None else v - w.start

        found = locate(w.text(self.submission_text), text, start=shift(span.start), end=shift(span.end),
                       occurrence=span.occurrence)
        if isinstance(found, LocateFailure):
            self.reject(_C.AMBIGUOUS_EXCERPT if found is LocateFailure.AMBIGUOUS else _C.EXACT_EXCERPT_MISMATCH, text)
            return None
        return replace(found, start=found.start + w.start, end=found.end + w.start)

    def mark_quarantine_incomplete(self) -> None:
        self.emit(_C.PARTIAL_MODEL_OUTPUT, INCOMPLETE_QUARANTINE_MESSAGE)

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
        return [*self.run.errors, *(self.issues[k] for k in sorted(self.issues))]

    def merged_rejections(self) -> list[RejectedExperimentProposal]:
        return [*self.run.rejected_proposals, *self.rejected][:MAX_RECORDED_REJECTIONS]

    def sorted_excerpts(self) -> list[StudentExperimentExcerpt]:
        return sorted(self.excerpts.values(), key=lambda e: (e.start, e.end, str(e.excerpt_id)))


__all__ = [
    "EXPERIMENT_FORBIDDEN_MARKERS",
    "MAX_RECORDED_REJECTIONS",
    "INCOMPLETE_QUARANTINE_MESSAGE",
    "QUARANTINE_PLACEHOLDER",
    "SourceWindow",
    "ExperimentLedger",
    "discloses_system_prompt",
    "forbidden_conclusion",
    "masked_submission",
    "parse_enum",
    "quarantine_incomplete",
]
