"""Phase 3A input binding and the deterministic requirement inventory.

Nothing here calls a model. The inventory is a pure function of the inherited
project type, the closed ``REQUIREMENT_CATALOG``, the overlay assignments and the
bound Phase 2J facts, so a model can neither invent a requirement kind nor lower
a REQUIRED one (ADR-022).

Only authoritative inputs are bound: the verbatim submission, the claims (by
text hash), the Phase 2J run and the Phase 2I run (as context). ``ProjectState.
results`` and ``ProjectState.experiments`` are never read: they hold execution
and outcome data and must not repair a design.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import UUID

from src.graph.state import ProjectState
from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import claim_text_digest
from src.schemas.common import KnowledgeStatus, ProjectType, TechnicalDomain
from src.schemas.gap_assessment import GapFacet
from src.schemas.methodology_review import (
    AI_ML_DOMAINS,
    REQUIREMENT_CATALOG,
    SOFTWARE_SYSTEMS_DOMAINS,
    Applicability,
    ApplicabilityBasis,
    ApplicabilityTrigger,
    BoundClaim,
    BoundGapTarget,
    MethodologyDraft,
    MethodologyReviewBounds,
    MethodologyReviewRun,
    MethodologyRunIssue,
    MethodologyRunIssueCode,
    MethodologyRunStatus,
    MethodologyRunVersions,
    MethodologyTrack,
    MethodologyUpstreamBinding,
    MethodologyUpstreamPhase,
    OverlayMateriality,
    RequirementApplicability,
    RequirementKind,
    RequirementOverlay,
    methodology_id,
    resolve_applicability,
    text_hash,
    tracks_for,
    upstream_fingerprint,
)
from src.schemas.research import ResearchRun
from src.schemas.submission import StudentSubmissionArtifact

FACET_TRACK: dict[GapFacet, MethodologyTrack] = {
    GapFacet.RESEARCH: MethodologyTrack.SCIENTIFIC_RESEARCH,
    GapFacet.ENGINEERING: MethodologyTrack.ENGINEERING,
}

DETERMINISTIC_TRIGGERS = (
    ApplicabilityTrigger.PHASE_2J_BASELINE_REQUIRED,
    ApplicabilityTrigger.PHASE_2J_MATERIAL_CONDITION,
)
"""The only triggers settled without a model: they read the bound Phase 2J requirement."""


def methodology_run_id_for(research_run_id: UUID) -> UUID:
    return methodology_id("run", research_run_id)


def claims_fingerprint(bound: list[BoundClaim]) -> str:
    canonical = json.dumps([[c.claim_id, c.claim_text_hash] for c in sorted(bound, key=lambda c: c.claim_id)],
                           separators=(",", ":"), ensure_ascii=False)
    return text_hash(canonical)


def current_fingerprints(
    research_run: ResearchRun, submission: StudentSubmissionArtifact | None, bound: list[BoundClaim],
) -> dict[MethodologyUpstreamPhase, tuple[UUID, str]]:
    """Every authoritative upstream Phase 3A relies on, fingerprinted. Absent ones are omitted."""
    out: dict[MethodologyUpstreamPhase, tuple[UUID, str]] = {}
    if submission is not None:
        out[MethodologyUpstreamPhase.STUDENT_SUBMISSION] = (submission.artifact_id, submission.content_hash)
    out[MethodologyUpstreamPhase.PROJECT_CLAIMS] = (
        methodology_id("claims", research_run.research_run_id), claims_fingerprint(bound))
    nd = research_run.novelty_differentiation
    if nd is not None:
        out[MethodologyUpstreamPhase.PHASE_2I_NOVELTY_DIFFERENTIATION] = (nd.nd_run_id, upstream_fingerprint(nd))
    gap = research_run.research_engineering_gap
    if gap is not None:
        out[MethodologyUpstreamPhase.PHASE_2J_GAP] = (gap.gap_run_id, upstream_fingerprint(gap))
    return out


def bind_claims(claims: list[ClaimRecord]) -> list[BoundClaim]:
    seen: dict[str, ClaimRecord] = {}
    for claim in sorted(claims, key=lambda c: c.claim_id):
        seen.setdefault(claim.claim_id, claim)
    return [BoundClaim(claim_id=c.claim_id, claim_text_hash=claim_text_digest(c.claim)) for c in seen.values()]


def _issue(code: MethodologyRunIssueCode, node: str, message: str) -> MethodologyRunIssue:
    return MethodologyRunIssue(code=code, node=node, message=message[:200])


def open_methodology_run(
    research_run: ResearchRun, project: ProjectState, submission: StudentSubmissionArtifact | None,
    started_at: datetime, *, provider_name: str | None = None, model_name: str | None = None,
) -> MethodologyReviewRun:
    """Bind the run to its authoritative inputs, or end it INSUFFICIENT_INPUT with the reason stated."""
    node = "LOAD_METHODOLOGY_REVIEW_RUN"
    gap = research_run.research_engineering_gap
    project_type = project.identity.project_type
    errors: list[MethodologyRunIssue] = []
    if gap is None or gap.research_run_id != research_run.research_run_id or not gap.is_terminal:
        errors.append(_issue(MethodologyRunIssueCode.INVALID_INPUT, node, "no finished Phase 2J run on this research run"))
    elif project_type is ProjectType.UNKNOWN or gap.canonical_project_type is ProjectType.UNKNOWN:
        errors.append(_issue(MethodologyRunIssueCode.PROJECT_TYPE_UNBOUND, node, "the canonical project type is UNKNOWN"))
    elif gap.canonical_project_type is not project_type:
        errors.append(_issue(MethodologyRunIssueCode.PROJECT_TYPE_UNBOUND, node,
                             "the Phase 2J project type differs from the project identity"))
    if submission is None:
        errors.append(_issue(MethodologyRunIssueCode.INVALID_INPUT, node, "no student submission is bound"))
    if not project.claims:
        errors.append(_issue(MethodologyRunIssueCode.INVALID_INPUT, node, "the project has no claims to review against"))

    type_ok = not any(e.code is MethodologyRunIssueCode.PROJECT_TYPE_UNBOUND for e in errors) and gap is not None \
        and gap.research_run_id == research_run.research_run_id and gap.is_terminal
    canonical = project_type if type_ok else ProjectType.UNKNOWN
    bound_claims = bind_claims(list(project.claims))
    claim_ids = {c.claim_id for c in bound_claims}
    targets = (
        [BoundGapTarget.from_hypothesis(h) for h in sorted(gap.hypotheses, key=lambda h: str(h.hypothesis_id))
         if h.claim_id in claim_ids]
        if gap is not None and type_ok else []
    )
    nd = research_run.novelty_differentiation
    bindings = [
        MethodologyUpstreamBinding(phase=phase, upstream_id=upstream_id, fingerprint=fingerprint)
        for phase, (upstream_id, fingerprint) in current_fingerprints(research_run, submission, bound_claims).items()
    ]
    run = MethodologyReviewRun(
        methodology_run_id=methodology_run_id_for(research_run.research_run_id),
        research_run_id=research_run.research_run_id,
        gap_run_id=gap.gap_run_id if gap is not None and type_ok else None,
        nd_run_id=nd.nd_run_id if nd is not None and gap is not None and type_ok else None,
        status=MethodologyRunStatus.RUNNING if not errors else MethodologyRunStatus.INSUFFICIENT_INPUT,
        versions=MethodologyRunVersions(model_provider=provider_name, model_name=model_name),
        canonical_project_type=canonical,
        tracks=list(tracks_for(canonical)),
        submission_artifact_id=submission.artifact_id if submission is not None else None,
        submission_content_hash=submission.content_hash if submission is not None else None,
        upstream_bindings=bindings,
        draft=MethodologyDraft(methodology_run_id=methodology_run_id_for(research_run.research_run_id)),
        bound_claims=bound_claims,
        bound_gap_targets=targets,
        errors=errors,
        started_at=started_at,
    )
    return run


# -- overlay signals (signals only: never materiality, never ownership) --------


def overlay_signals(project: ProjectState) -> dict[RequirementOverlay, list[TechnicalDomain]]:
    """Overlays the project merely hints at. A hint is the reason to ask the question,
    never the answer: materiality and ownership rest on bound targets and excerpts."""
    domains = set(project.identity.domain)
    technical = project.technical
    signals: dict[RequirementOverlay, list[TechnicalDomain]] = {}
    if domains & AI_ML_DOMAINS or technical.models or technical.datasets:
        signals[RequirementOverlay.AI_ML] = sorted(domains & AI_ML_DOMAINS)
    architecture_known = technical.architecture.status is KnowledgeStatus.KNOWN
    if domains & SOFTWARE_SYSTEMS_DOMAINS or technical.software or architecture_known:
        signals[RequirementOverlay.SOFTWARE_SYSTEMS] = sorted(domains & SOFTWARE_SYSTEMS_DOMAINS)
    return signals


_AI_TERMS = re.compile(
    r"(?<!\w)(?:ai|artificial intelligence|machine learning|deep learning|neural|classifier|classification|"
    r"train(?:ed|ing)?|dataset|test set|training set|model|models|prediction|predict|nlp|computer vision)(?!\w)", re.I)
_SOFTWARE_TERMS = re.compile(
    r"(?<!\w)(?:software|application|app|database|backend|server|api|cloud|web|security|encryption|latency|"
    r"throughput|scalab\w*|network|interface)(?!\w)", re.I)
_LEXICON = {RequirementOverlay.AI_ML: _AI_TERMS, RequirementOverlay.SOFTWARE_SYSTEMS: _SOFTWARE_TERMS}


def overlay_candidates(project: ProjectState) -> dict[RequirementOverlay, list[TechnicalDomain]]:
    """Every overlay is reviewed for every project: candidate discovery is complete by construction.

    No metadata tag and no lexicon can exclude an overlay, because no finite lexicon can know every way a student
    words a method. The signals below decide only what a *negative* verdict needs (see ``signaled_overlays``)."""
    signals = overlay_signals(project)
    return {overlay: signals.get(overlay, []) for overlay in (RequirementOverlay.AI_ML,
                                                              RequirementOverlay.SOFTWARE_SYSTEMS)}


def signaled_overlays(
    project: ProjectState, claim_texts: dict[str, str], submission: StudentSubmissionArtifact,
    bound_texts: list[str],
) -> set[RequirementOverlay]:
    """Overlays the bounded inputs hint at: intake metadata, or a bounded English term in the claims, the submission
    or the bound Phase 2J metric/baseline text. A hint never makes an overlay material. It only means a non-material
    verdict needs an exact excerpt (IMPLEMENTATION_TOOL_ONLY) instead of being accepted as 'no relevance'."""
    signaled = set(overlay_signals(project))
    haystack = [*claim_texts.values(), submission.original_text, *bound_texts]
    for overlay, pattern in _LEXICON.items():
        if any(pattern.search(t) for t in haystack):
            signaled.add(overlay)
    return signaled


# -- track membership ------------------------------------------------------------


def gap_target_tracks(run: MethodologyReviewRun, target: BoundGapTarget) -> list[MethodologyTrack]:
    """The tracks a Phase 2J hypothesis belongs to: those its limitation facets map to,
    or every track when no facet maps onto one the project has."""
    mapped = {FACET_TRACK[f] for f in target.limitation_facets} & set(run.tracks)
    return [t for t in run.tracks if t in mapped] or list(run.tracks)


# -- deterministic applicability ----------------------------------------------------


def deterministic_triggers(run: MethodologyReviewRun) -> frozenset[ApplicabilityTrigger]:
    fired: set[ApplicabilityTrigger] = set()
    if any(t.requires_baseline for t in run.bound_gap_targets):
        fired.add(ApplicabilityTrigger.PHASE_2J_BASELINE_REQUIRED)
    if any(t.material_condition_ids for t in run.bound_gap_targets):
        fired.add(ApplicabilityTrigger.PHASE_2J_MATERIAL_CONDITION)
    return frozenset(fired)


def overlay_owners(run: MethodologyReviewRun) -> dict[RequirementOverlay, MethodologyTrack | None]:
    """Overlays that are material or unresolved, mapped to their owner (None while unresolved)."""
    return {
        o.overlay: (o.owner_track if o.materiality is OverlayMateriality.MATERIAL_TO_TARGET else None)
        for o in run.overlays
        if o.materiality is not OverlayMateriality.IMPLEMENTATION_TOOL_ONLY
    }


def compute_applicability(
    run: MethodologyReviewRun, model_resolved: dict[RequirementKind, RequirementApplicability] | None = None,
) -> list[RequirementApplicability]:
    """Every catalog requirement, resolved for this project. Deterministic and idempotent.

    A CONDITIONAL requirement becomes REQUIRED without a model only when a bound
    Phase 2J fact fires one of its triggers. Otherwise it stays CONDITIONAL unless a
    verified model judgment (``model_resolved``) resolved it. REQUIRED is never lowered."""
    owners = overlay_owners(run)
    fired = deterministic_triggers(run)
    tracks = tuple(run.tracks)
    out: list[RequirementApplicability] = []
    for kind in RequirementKind:
        entry = REQUIREMENT_CATALOG[kind]
        track, applicability, basis = resolve_applicability(kind, tracks, owners, None)
        triggers: list[ApplicabilityTrigger] = []
        judgment: list[UUID] = []
        if basis is ApplicabilityBasis.CONDITION_UNRESOLVED:
            hit = sorted(set(entry.triggers) & fired)
            if hit:
                applicability, basis, triggers = (
                    Applicability.REQUIRED, ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT, hit)
            elif model_resolved and kind in model_resolved:
                prior = model_resolved[kind]
                applicability, basis = prior.applicability, prior.basis
                triggers, judgment = list(prior.triggers), list(prior.judgment_excerpt_ids)
        out.append(RequirementApplicability(
            methodology_run_id=run.methodology_run_id, kind=kind, track=track, applicability=applicability,
            basis=basis, triggers=triggers, judgment_excerpt_ids=judgment))
    return out


def conditional_unresolved(applicability: list[RequirementApplicability]) -> list[RequirementApplicability]:
    """Track-bearing CONDITIONAL requirements still waiting on a bounded judgment."""
    return [a for a in applicability
            if a.track is not None and a.basis is ApplicabilityBasis.CONDITION_UNRESOLVED]


def active(applicability: list[RequirementApplicability]) -> list[RequirementApplicability]:
    """Requirements a track owns and counts: anything with a track that is not NOT_APPLICABLE."""
    return [a for a in applicability if a.track is not None and a.applicability is not Applicability.NOT_APPLICABLE]


__all__ = [
    "DETERMINISTIC_TRIGGERS",
    "FACET_TRACK",
    "active",
    "bind_claims",
    "claims_fingerprint",
    "compute_applicability",
    "conditional_unresolved",
    "current_fingerprints",
    "deterministic_triggers",
    "gap_target_tracks",
    "methodology_run_id_for",
    "open_methodology_run",
    "overlay_candidates",
    "signaled_overlays",
    "overlay_owners",
    "overlay_signals",
]
