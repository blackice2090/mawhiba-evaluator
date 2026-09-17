"""Scoring input fingerprint -- Phase 2F (section 17).

One sha256 over exactly the Phase 2E facts that can change a score, so a
scorecard is bound to the inputs it was computed from.

Two properties have to hold at once, and they pull against each other:

**Stability.** Identical scoring-relevant inputs must produce an identical
fingerprint, on any platform and on any rerun. So nothing unstable participates:
no timestamp, no ``uuid4``, no dict iteration order, no float. Every component
is either an id that Phase 2E derives deterministically (``uuid5``) or an enum
value, and every collection is sorted before it is written.

**Sensitivity.** Changing anything that can move a number must change the
fingerprint. So the digest covers the complete component inventory with each
component's exact anchor and coverage state, the independence group identity
behind every direction, the eligible/disqualified contribution class of every
profile, the source-quality and unknown dimensions the reliability layer reads,
and both policy versions.

What is deliberately *excluded* is as important as what is included. The claim's
prose is represented by its component anchors and the inventory's own
``claim_text_hash``, not pasted in again; profile ids are excluded because they
are derived from the sufficiency run id, which is included once. Adding a field
that cannot change a score would make the fingerprint churn without meaning,
and a fingerprint that changes for no reason teaches a reader to ignore it.
"""

from __future__ import annotations

import json
from hashlib import sha256

from src.schemas.claim_evidence_score import (
    CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
    SCORE_ARITHMETIC_VERSION,
)
from src.schemas.claim_sufficiency import (
    ClaimSufficiencyAssessment,
    EvidenceWeightProfile,
)


def scoring_input_digest(
    assessment: ClaimSufficiencyAssessment,
    profiles: list[EvidenceWeightProfile],
) -> str:
    """The sha256 hex digest of one claim's scoring-relevant inputs.

    ``profiles`` must be this claim's Phase 2E weight profiles. They are sorted
    by ``(claim_id, evidence_id)`` rather than taken in arrival order, so a
    reordered input list -- semantically irrelevant -- cannot change the digest
    (section 30, order invariance).
    """
    payload = {
        "claim_id": assessment.claim_id,
        "assessment_id": str(assessment.assessment_id),
        "sufficiency_run_id": str(assessment.sufficiency_run_id),
        "research_run_id": str(assessment.research_run_id),
        "sufficiency_outcome": assessment.outcome.value,
        "sufficiency_policy_version": assessment.policy_version,
        "sufficiency_contract_version": assessment.contract_version,
        "inventory": {
            "claim_text_hash": assessment.component_inventory.claim_text_hash,
            "claim_text_length": assessment.component_inventory.claim_text_length,
            "completeness": assessment.component_inventory.completeness.value,
            "strategy_version": assessment.component_inventory.strategy_version,
            "issues": sorted(
                issue.value for issue in assessment.component_inventory.issues
            ),
            "components": [
                {
                    "start": component.start,
                    "end": component.end,
                    "text": component.text,
                    "origin": component.origin.value,
                }
                for component in sorted(
                    assessment.component_inventory.components,
                    key=lambda c: (c.start, c.end),
                )
            ],
        },
        "components": [
            {
                "anchor": [component.anchor_start, component.anchor_end],
                "anchor_text": component.anchor_text,
                "origin": component.origin.value,
                "coverage": component.coverage.value,
                "corroboration": component.corroboration.value,
                "supporting_groups": sorted(
                    str(g) for g in component.supporting_group_ids
                ),
                "contradicting_groups": sorted(
                    str(g) for g in component.contradicting_group_ids
                ),
                "partial_supporting_groups": sorted(
                    str(g) for g in component.partial_supporting_group_ids
                ),
                "partial_contradicting_groups": sorted(
                    str(g) for g in component.partial_contradicting_group_ids
                ),
                "disqualified_groups": sorted(
                    str(g) for g in component.disqualified_group_ids
                ),
            }
            for component in sorted(
                assessment.components,
                key=lambda c: (c.anchor_start, c.anchor_end),
            )
        ],
        "profiles": [
            {
                "evidence_id": str(profile.evidence_id),
                "independence_group_id": str(profile.independence_group_id),
                "canonical_identity": profile.canonical_identity,
                "relation": profile.relation.value,
                "contribution": profile.contribution.value,
                "retraction_status": profile.retraction_status.value,
                "publication_status": profile.publication_status.value,
                "traceability": profile.traceability.value,
                "content_scope": profile.content_scope.value,
                "limitations": sorted(
                    limitation.value for limitation in profile.limitations
                ),
                "unknown_dimensions": sorted(
                    dimension.value for dimension in profile.unknown_dimensions
                ),
            }
            for profile in sorted(
                profiles, key=lambda p: (p.claim_id, str(p.evidence_id))
            )
        ],
        "blockers": sorted(blocker.value for blocker in assessment.blockers),
        "content_scope_ceiling": (
            assessment.content_scope_ceiling.value
            if assessment.content_scope_ceiling
            else None
        ),
        "unknown_dimensions": sorted(
            dimension.value for dimension in assessment.unknown_dimensions
        ),
        "scoring_policy_version": CLAIM_EVIDENCE_SCORING_POLICY_VERSION,
        "arithmetic_version": SCORE_ARITHMETIC_VERSION,
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["scoring_input_digest"]
