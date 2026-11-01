"""Experiment segmentation and the result quarantine (``EXPERIMENT_SEGMENT``). One model call.

The model points at defining protocol spans and at result spans. Code then:

* locates every span exactly (``ExperimentLedger.locate_span``; repeated text needs
  a validated disambiguator, never a first-occurrence guess);
* stores each result span as a ``QuarantinedSpan`` -- offsets and a hash, never the
  text -- and refuses any defining span that overlaps one, so the quarantine wins;
* derives identity: ``protocol_key`` is the hash of the defining excerpt texts in
  document order and ``experiment_id = uuid5(run, protocol_key)``, so offsets and
  targets are not identity and unrelated text elsewhere cannot rename an experiment;
* de-duplicates: identical defining text is one experiment, and an excerpt defines
  one experiment only;
* bounds the set at ``max_experiments`` (``EXPERIMENT_BOUND_REACHED``).

Nothing the model wrote reaches the run except through those verified records.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.prompts import EXPERIMENT_SEGMENTATION_PROMPT_V1, build_experiment_user_input, unescape_untrusted
from src.llm.provider import StructuredModelProvider
from src.research.experiments.calls import FAILURE_MESSAGES, call_model
from src.research.experiments.dto import SegmentationResponse
from src.research.experiments.verify import ExperimentLedger, parse_enum
from src.research.novelty.anchoring import occurrences
from src.schemas.methodology_review import MethodologyTrack
from src.schemas.experiment_review import (
    ExperimentPosture,
    ExperimentRecord,
    ExperimentRunIssueCode,
    ExperimentType,
    QuarantinedSpan,
    QuarantineKind,
    TrackOwnershipBasis,
    TypeBasis,
    experiment_uuid,
    protocol_key,
    text_hash,
)

_C = ExperimentRunIssueCode


@dataclass
class SegmentationOutcome:
    quarantine: list[QuarantinedSpan]
    experiments: list[ExperimentRecord]
    attempts: int = 0


def _items(ledger: ExperimentLedger) -> list[str]:
    return [
        "Return EXPERIMENTS (label, defining_excerpts, revision_of) and RESULTS (kind, span).",
        f"RESULT KINDS: {', '.join(k.value for k in QuarantineKind)}",
        f"At most {ledger.bounds.max_experiments} experiments are reviewed.",
    ]


def placeholder_record(run_id: UUID, key: str, excerpt_ids: list[UUID], *, single_track: MethodologyTrack | None,
                       revision_of: UUID | None) -> ExperimentRecord:
    """A segmented, not yet assessed experiment: type UNKNOWN, no requirements. It carries
    no derived posture yet (the run validator derives one only once requirements exist)."""
    track = single_track
    return ExperimentRecord(
        experiment_id=experiment_uuid(run_id, key), experiment_run_id=run_id, protocol_key=key,
        defining_excerpt_ids=excerpt_ids, experiment_type=ExperimentType.UNKNOWN, type_basis=TypeBasis.UNRESOLVED,
        track=track,
        ownership_basis=TrackOwnershipBasis.SINGLE_TRACK_PROJECT if track is not None
        else TrackOwnershipBasis.UNRESOLVED,
        revision_of=revision_of, posture=ExperimentPosture.INSUFFICIENT_EVIDENCE)


def segment(
    ledger: ExperimentLedger, provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> SegmentationOutcome:
    run, bounds = ledger.run, ledger.bounds
    outcome = call_model(
        provider, task=ModelTask.EXPERIMENT_SEGMENTATION, prompt=EXPERIMENT_SEGMENTATION_PROMPT_V1,
        user_input=build_experiment_user_input(submission_text=ledger.window_text(), items=_items(ledger)),
        response_model=SegmentationResponse, llm_settings=llm_settings, bounds=bounds,
        performed=run.model_calls_performed)
    if not outcome.succeeded:
        ledger.emit(outcome.failure, FAILURE_MESSAGES[outcome.failure])  # type: ignore[index, arg-type]
        return SegmentationOutcome([], [], outcome.attempts)
    response: SegmentationResponse = outcome.parsed

    # -- the quarantine first: a result span always wins over a protocol span ----------
    # Fail closed. Every exact occurrence of a declared result inside the model-visible window is
    # quarantined (a repeated sentence is not an error, it is more to withhold). A declared span that
    # cannot be safely quarantined is never dropped silently: the run records an incomplete
    # quarantine and cannot reach a strong posture (``pipeline`` blocks later stages and finalize).
    quarantine: dict[tuple[int, int], QuarantinedSpan] = {}
    window = ledger.window_text()
    for dto in sorted(response.results, key=lambda r: (r.span.excerpt, r.kind)):
        kind = parse_enum(QuarantineKind, dto.kind)
        if kind is None:  # an unknown kind is still a result span; it is quarantined as a conclusion
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.kind, "an unknown result kind was quarantined as CONCLUSION")
            kind = QuarantineKind.CONCLUSION
        text = unescape_untrusted(dto.span.excerpt or "")
        positions = occurrences(window, text) if text.strip() else []
        if not positions and text != text.strip() and text.strip():
            text = text.strip()
            positions = occurrences(window, text)
        spans = [(p, p + len(text)) for p in positions]
        # a result cut by the window edge: its visible prefix is withheld too
        edge = next((k for k in range(min(len(text) - 1, len(window)), 0, -1) if window.endswith(text[:k])), 0)
        if edge:
            spans.append((len(window) - edge, len(window)))
        if not spans or len(spans) > bounds.max_excerpts:
            ledger.reject(_C.EXACT_EXCERPT_MISMATCH, text, "a declared result span could not be located exactly")
            ledger.mark_quarantine_incomplete()
            continue
        for lo, hi in spans:
            span_key = (ledger.window.start + lo, ledger.window.start + hi)
            quarantine.setdefault(span_key, QuarantinedSpan(
                span_id=experiment_uuid(run.experiment_run_id, "quarantine", *span_key),
                experiment_run_id=run.experiment_run_id, kind=kind, start=span_key[0], end=span_key[1],
                span_hash=text_hash(ledger.submission_text[span_key[0]:span_key[1]])))
    q_spans = sorted(quarantine.values(), key=lambda q: (q.start, q.end))
    ledger.run = run.model_copy(update={"quarantine": q_spans})

    # -- defining spans, verified and keyed -----------------------------------------------
    candidates: list[tuple[str, list[UUID], str | None]] = []
    for dto in sorted(response.experiments, key=lambda e: e.label):
        if ledger.unsafe(dto.rationale):
            continue
        ids = [i for i in (ledger.anchor(s) for s in dto.defining_excerpts) if i is not None]
        if not ids:
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.label, "an experiment had no verifiable defining excerpt")
            continue
        candidates.append((dto.label, ledger.ordered(ids), dto.revision_of))
    candidates.sort(key=lambda c: (ledger.excerpts[c[1][0]].start, c[0]))

    claimed: set[UUID] = set()
    keys: set[str] = set()
    kept: list[tuple[str, list[UUID], str | None, str]] = []
    for label, ids, revision in candidates:
        own = [i for i in ids if i not in claimed]  # an excerpt defines one experiment only
        if not own:
            continue
        key = protocol_key([ledger.excerpts[i].excerpt for i in own])
        if key in keys:  # identical defining text is the same experiment, recorded once
            continue
        if len(kept) >= bounds.max_experiments:
            ledger.emit(_C.EXPERIMENT_BOUND_REACHED,
                        f"more than {bounds.max_experiments} experiments were segmented; the rest are not reviewed")
            break
        claimed |= set(own)
        keys.add(key)
        kept.append((label, own, revision, key))

    by_label = {label: experiment_uuid(run.experiment_run_id, key) for label, _, _, key in kept}
    single = run.tracks[0] if len(run.tracks) == 1 else None
    records = []
    for label, ids, revision, key in kept:
        revision_of = by_label.get(revision) if revision else None
        if revision_of == by_label[label]:
            revision_of = None
        records.append(placeholder_record(run.experiment_run_id, key, ids, single_track=single,
                                          revision_of=revision_of))
    # excerpts the model offered for a dropped or merged experiment are not kept
    used = {i for r in records for i in r.defining_excerpt_ids}
    ledger.excerpts = {i: e for i, e in ledger.excerpts.items() if i in used or i in {x.excerpt_id for x in run.excerpts}}
    return SegmentationOutcome(q_spans, sorted(records, key=lambda r: str(r.experiment_id)), outcome.attempts)


__all__ = ["SegmentationOutcome", "placeholder_record", "segment"]
