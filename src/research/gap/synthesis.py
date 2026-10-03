"""Deterministic Phase 2J synthesis (no model, no search, no score).

A hypothesis is built from the verified draft through ``build_hypothesis``, the
one place every derived field (existence, linkage, condition materiality, kind,
corroboration, scope, missing components, posture) is computed -- the same
function the schema validator re-runs, so a stored posture cannot drift from
the rule. The claim posture then follows ``derive_claim_posture``.

Chronology is attached per excerpt from the Phase 2I profile, unchanged, in its
own records: it never enters gap support, and it proves neither historical
publicity nor legal prior art (section 12).
"""

from __future__ import annotations

from uuid import UUID

from src.schemas.common import ProjectType
from src.schemas.gap_assessment import (
    GapChronologyNote,
    GapCorroborationLevel,
    GapHypothesis,
    GapInventoryText,
    GapKind,
    GapPosture,
    ClaimGapAssessment,
    GapClaimDraft,
    InsufficientReason,
    MissingGapComponent,
    ProjectGapSummary,
    build_hypothesis,
    derive_claim_posture,
    gap_id,
)


def kind_mismatches_project_type(kind: GapKind, project_type: ProjectType) -> bool:
    """A research gap on an engineering project (or the reverse) is recorded as a
    note; the canonical project type is never rewritten (section 6)."""
    return (
        (kind is GapKind.RESEARCH and project_type is ProjectType.ENGINEERING_PROJECT)
        or (kind is GapKind.ENGINEERING and project_type is ProjectType.SCIENTIFIC_RESEARCH)
    )


def build_claim_hypothesis(
    *, gap_run_id: UUID, research_run_id: UUID, draft: GapClaimDraft,
    inventory: dict[tuple, GapInventoryText],
) -> GapHypothesis | None:
    """One hypothesis per claim, or None when no limitation survived verification."""
    if not draft.limitations or not draft.evidence_refs:
        return None
    notes = []
    for ref in draft.evidence_refs:
        text = inventory.get((ref.source_kind, ref.source_record_id))
        if text is not None and text.chronology_bucket is not None and text.chronology_basis is not None:
            notes.append(GapChronologyNote(
                evidence_ref_id=ref.evidence_ref_id, bucket=text.chronology_bucket,
                upstream_basis=text.chronology_basis,
            ))
    return build_hypothesis(
        hypothesis_id=gap_id(gap_run_id, draft.claim_id, "hypothesis"),
        gap_run_id=gap_run_id,
        research_run_id=research_run_id,
        claim_id=draft.claim_id,
        evidence_refs=draft.evidence_refs,
        existing_capabilities=draft.existing_capabilities,
        limitations=draft.limitations,
        conditions=draft.conditions,
        project_links=draft.project_links,
        validation_requirement=draft.validation_requirement,
        counterevidence=draft.counterevidence,
        chronology=sorted(notes, key=lambda n: str(n.evidence_ref_id)),
        counterevidence_review_complete=draft.counter_done and not draft.counter_omitted_text_ids,
        model_proposed_kind=draft.model_proposed_kind,
    )


def assess_claim(
    *, gap_run_id: UUID, research_run_id: UUID, draft: GapClaimDraft, hypothesis: GapHypothesis | None,
    project_type: ProjectType,
) -> ClaimGapAssessment:
    bound = not draft.insufficient_reasons
    hyp = hypothesis if bound else None
    postures = [hyp.posture] if hyp else []
    return ClaimGapAssessment(
        assessment_id=gap_id(gap_run_id, draft.claim_id, "assessment"),
        gap_run_id=gap_run_id,
        research_run_id=research_run_id,
        claim_id=draft.claim_id,
        claim_text_hash=draft.claim_text_hash,
        inputs_bound=bound,
        insufficient_reasons=sorted(set(draft.insufficient_reasons), key=lambda r: r.value),
        has_differentiating_feature=draft.has_differentiating_feature,
        hypothesis_ids=[hyp.hypothesis_id] if hyp else [],
        hypothesis_postures=postures,
        hypothesis_existence=[hyp.existence] if hyp else [],
        hypothesis_linkage=[hyp.linkage] if hyp else [],
        rejected_proposal_count=draft.rejected_count,
        canonical_project_type=project_type,
        kind_project_type_note=bool(hyp and kind_mismatches_project_type(hyp.kind, project_type)),
        posture=derive_claim_posture(
            inputs_bound=bound, hypothesis_postures=postures, has_differentiating_feature=draft.has_differentiating_feature
        ),
    )


def summarize(
    gap_run_id: UUID, assessments: list[ClaimGapAssessment], hypotheses: list[GapHypothesis]
) -> ProjectGapSummary:
    """Descriptive counts only. No score, readiness, ranking or verdict."""

    def count(values) -> dict[str, int]:
        out: dict[str, int] = {}
        for value in values:
            out[value.value] = out.get(value.value, 0) + 1
        return dict(sorted(out.items()))

    supported = [h for h in hypotheses if h.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS]
    corroborated = {GapCorroborationLevel.MULTI_SOURCE_CORROBORATED, GapCorroborationLevel.MIXED_SOURCE_CORROBORATED}
    return ProjectGapSummary(
        gap_run_id=gap_run_id,
        assessed_claim_count=len(assessments),
        hypothesis_count=len(hypotheses),
        kind_counts=count(h.kind for h in hypotheses),
        posture_counts=count(h.posture for h in hypotheses),
        claim_posture_counts=count(a.posture for a in assessments),
        single_source_supported_count=sum(1 for h in supported if h.corroboration is GapCorroborationLevel.SINGLE_SOURCE_DIRECT),
        corroborated_supported_count=sum(1 for h in supported if h.corroboration in corroborated),
        unresolved_independence_supported_count=sum(
            1 for h in supported if h.corroboration is GapCorroborationLevel.UNRESOLVED_INDEPENDENCE
        ),
        weakened_by_counterevidence_count=sum(1 for h in hypotheses if h.posture is GapPosture.COUNTEREVIDENCE_WEAKENS_GAP),
        lacking_validation_requirement_count=sum(
            1 for h in hypotheses if MissingGapComponent.VALIDATION_REQUIREMENT in h.missing_components
        ),
    )


def unbound_draft(claim_id: str, claim_text_hash: str, reason: InsufficientReason) -> GapClaimDraft:
    return GapClaimDraft(claim_id=claim_id, claim_text_hash=claim_text_hash, insufficient_reasons=[reason])


__all__ = ["assess_claim", "build_claim_hypothesis", "kind_mismatches_project_type", "summarize", "unbound_draft"]
