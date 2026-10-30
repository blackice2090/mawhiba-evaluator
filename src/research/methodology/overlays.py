"""Overlay materiality and ownership (hardened architecture A).

A domain word, the word "AI" or the presence of a model is a *signal* that a
question must be asked, never its answer. Materiality rests on bound targets and
exact submission excerpts; ownership follows the project type, then the Phase 2J
limitation facet, then a bounded judgment, and is otherwise left UNRESOLVED -- in
which case the overlay's requirements stay CONDITIONAL and block a well-specified
posture, so an overlay can neither escape review nor be counted twice.

There is no "research track if present" shortcut anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1, build_methodology_user_input
from src.llm.provider import StructuredModelProvider
from src.research.methodology.dto import OverlayAssessmentResponse, OverlayJudgmentDTO
from src.research.methodology.inventory import FACET_TRACK
from src.research.methodology.verify import StageLedger, parse_enum
from src.schemas.common import TechnicalDomain
from src.schemas.methodology_review import (
    MethodologyReviewRun,
    MethodologyRunIssueCode,
    MethodologyTrack,
    OverlayAssignment,
    OverlayMateriality,
    OverlayOwnershipBasis,
    RequirementOverlay,
)

NODE = "RESOLVE_METHODOLOGY_OVERLAYS"
SUBJECT_OVERLAYS = (RequirementOverlay.AI_ML, RequirementOverlay.SOFTWARE_SYSTEMS)


@dataclass
class OverlayOutcome:
    assignments: list[OverlayAssignment]
    model_called: bool = False
    model_succeeded: bool = False
    failure: str | None = None
    labels: dict[str, object] = field(default_factory=dict)


def _unresolved(run: MethodologyReviewRun, overlay: RequirementOverlay, domains: list[TechnicalDomain]
                ) -> OverlayAssignment:
    return OverlayAssignment(
        methodology_run_id=run.methodology_run_id, overlay=overlay, signal_domains=domains,
        materiality=OverlayMateriality.MATERIALITY_UNRESOLVED, ownership_basis=OverlayOwnershipBasis.UNRESOLVED)


def claim_labels(run: MethodologyReviewRun) -> dict[str, str]:
    return {f"C{i}": c.claim_id for i, c in enumerate(sorted(run.bound_claims, key=lambda c: c.claim_id), 1)}


def hypothesis_labels(run: MethodologyReviewRun) -> dict[str, object]:
    ordered = sorted(run.bound_gap_targets, key=lambda t: str(t.gap_hypothesis_id))
    return {f"H{i}": t.gap_hypothesis_id for i, t in enumerate(ordered, 1)}


def assess_overlays(
    run: MethodologyReviewRun, signals: dict[RequirementOverlay, list[TechnicalDomain]], ledger: StageLedger,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
    claim_texts: dict[str, str], *, signaled: set[RequirementOverlay] | None = None,
) -> OverlayOutcome:
    if not signals:
        return OverlayOutcome([])
    overlays = sorted(signals, key=lambda o: o.value)
    fallback = {o: _unresolved(run, o, signals[o]) for o in overlays}
    if provider is None:
        return OverlayOutcome(list(fallback.values()), failure="no structured model provider")
    c_labels, h_labels = claim_labels(run), hypothesis_labels(run)
    targets = {t.gap_hypothesis_id: t for t in run.bound_gap_targets}
    items = [f"OVERLAY: {o.value}" for o in overlays]
    for label, hid in h_labels.items():
        t = targets[hid]
        facets = ",".join(f.value for f in t.limitation_facets) or "NONE"
        claim_label = next(cl for cl, cid in c_labels.items() if cid == t.claim_id)
        items.append(f"[{label}] hypothesis of claim {claim_label}; facets: {facets}")
    tracks = ",".join(t.value for t in run.tracks)
    items.append(f"PROJECT TRACKS: {tracks}")
    shown = ledger.submission_text[: ledger.bounds.max_submission_chars]
    call = call_structured_model_with_retries(
        provider, task=ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT,
        system_prompt=METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1,
        user_input=build_methodology_user_input(shown, [(l, claim_texts[c]) for l, c in c_labels.items()], items),
        response_model=OverlayAssessmentResponse, model=(llm_settings or LLMSettings()).extraction_model,
        max_retries=ledger.bounds.model_retry_limit,
    )
    if not call.succeeded or not isinstance(call.parsed, OverlayAssessmentResponse):
        return OverlayOutcome(list(fallback.values()), model_called=True, failure=call.status.value)
    done: dict[RequirementOverlay, OverlayAssignment] = {}
    for dto in sorted(call.parsed.overlays, key=lambda d: (d.overlay, d.materiality)):
        overlay = parse_enum(RequirementOverlay, dto.overlay)
        if overlay not in signals or overlay in done:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.overlay, off_contract=True)
            continue
        done[overlay] = _judge(run, overlay, signals[overlay], dto, ledger, c_labels, h_labels, targets,
                               overlay in (signaled if signaled is not None else set(signals)))
    assignments = [done.get(o, fallback[o]) for o in overlays]
    return OverlayOutcome(assignments, model_called=True, model_succeeded=True)


NO_RELEVANCE = "NO_METHODOLOGY_RELEVANCE"


def _judge(run, overlay, domains, dto: OverlayJudgmentDTO, ledger: StageLedger, c_labels, h_labels, targets,
           signaled: bool) -> OverlayAssignment:
    unresolved = _unresolved(run, overlay, domains)
    if ledger.unsafe(NODE, *(s.rationale for s in dto.excerpts)):
        return unresolved
    if dto.materiality.strip().upper() == NO_RELEVANCE:
        # The explicit negative contract. It is accepted only when nothing in the bounded inputs hints at the overlay;
        # it is stored as a non-material assignment with no excerpt and no prose, so the review stays auditable. A hinted
        # overlay needs an exact-excerpt IMPLEMENTATION_TOOL_ONLY verdict instead, and otherwise stays UNRESOLVED.
        if signaled:
            ledger.reject(MethodologyRunIssueCode.INVALID_INPUT, NO_RELEVANCE)
            return unresolved
        return OverlayAssignment(
            methodology_run_id=run.methodology_run_id, overlay=overlay, signal_domains=domains,
            materiality=OverlayMateriality.IMPLEMENTATION_TOOL_ONLY, ownership_basis=OverlayOwnershipBasis.NOT_MATERIAL)
    materiality = parse_enum(OverlayMateriality, dto.materiality)
    if materiality is None:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.materiality, off_contract=True)
        return unresolved
    if materiality is OverlayMateriality.MATERIALITY_UNRESOLVED:
        return unresolved
    claim_ids, hypothesis_ids = [], []
    for label in dict.fromkeys(l.strip().upper() for l in dto.claims):
        if label in c_labels:
            claim_ids.append(c_labels[label])
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, label, off_contract=True)
    for label in dict.fromkeys(l.strip().upper() for l in dto.hypotheses):
        if label in h_labels:
            hypothesis_ids.append(h_labels[label])
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, label, off_contract=True)
    excerpt_ids = list(dict.fromkeys(i for i in (ledger.anchor(s) for s in dto.excerpts) if i is not None))
    if not excerpt_ids:
        return unresolved  # materiality and a tool-only verdict both need exact source evidence
    if materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY:
        return OverlayAssignment(
            methodology_run_id=run.methodology_run_id, overlay=overlay, signal_domains=domains,
            materiality=materiality, excerpt_ids=excerpt_ids, ownership_basis=OverlayOwnershipBasis.NOT_MATERIAL)
    if not (claim_ids or hypothesis_ids):
        return unresolved
    claim_ids = sorted(set(claim_ids))
    hypothesis_ids = sorted(set(hypothesis_ids), key=str)
    owner, basis, served = _ownership(run, dto, hypothesis_ids, targets)
    return OverlayAssignment(
        methodology_run_id=run.methodology_run_id, overlay=overlay, signal_domains=domains,
        materiality=materiality, material_claim_ids=claim_ids, material_gap_hypothesis_ids=hypothesis_ids,
        excerpt_ids=excerpt_ids, owner_track=owner, ownership_basis=basis, served_tracks=served)


def _ownership(run, dto: OverlayJudgmentDTO, hypothesis_ids, targets):
    """Owner track, basis and served tracks for a MATERIAL overlay. Never a blanket preference."""
    tracks = list(run.tracks)
    if len(tracks) == 1:
        return tracks[0], OverlayOwnershipBasis.SINGLE_TRACK_PROJECT, [tracks[0]]
    facets = [targets[h].limitation_facets for h in hypothesis_ids]
    if hypothesis_ids and all(facets):
        owners = {FACET_TRACK[f] for fs in facets for f in fs}
        if len(owners) == 1:
            owner = next(iter(owners))
            return owner, OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET, _served(tracks, dto, owner)
    owner = parse_enum(MethodologyTrack, dto.owner_track)
    if owner in tracks:
        return owner, OverlayOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT, _served(tracks, dto, owner)
    return None, OverlayOwnershipBasis.UNRESOLVED, tracks


def _served(tracks, dto: OverlayJudgmentDTO, owner: MethodologyTrack) -> list[MethodologyTrack]:
    named = {parse_enum(MethodologyTrack, t) for t in dto.served_tracks}
    return [t for t in tracks if t is owner or t in named]


__all__ = ["NODE", "OverlayOutcome", "assess_overlays", "claim_labels", "hypothesis_labels"]
