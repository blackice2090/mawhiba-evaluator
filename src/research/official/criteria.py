"""Official Mawhiba criteria versus the agent's advisory rubric.

This is a hard trust boundary. Official criteria come only from verified official
requirements; the advisory rubric is the agent's own and is never presented as
official. Nothing here reads a weight from ``ADVISORY_RUBRIC_V1``.
"""

from __future__ import annotations

from src.schemas.official import (
    WEIGHT_BEARING_CATEGORIES,
    CriteriaAuthority,
    OfficialRequirement,
    OfficialRequirementsResult,
    OfficialRequirementStatus,
)
from src.schemas.score import RubricKind
from src.scoring.models import Rubric


def rubric_authority(rubric: Rubric) -> CriteriaAuthority:
    """An OFFICIAL rubric must cite a source; everything else is advisory."""
    if rubric.kind is RubricKind.OFFICIAL and rubric.source_id is not None:
        return CriteriaAuthority.OFFICIAL_MAWHIBA_CRITERIA
    return CriteriaAuthority.AGENT_ADVISORY_RUBRIC


def official_judging_criteria(result: OfficialRequirementsResult | None) -> list[OfficialRequirement]:
    """Verified official judging/scoring items that are not superseded."""
    if result is None or not result.official_requirements_checked:
        return []
    return [
        r
        for r in result.requirements
        if r.category in WEIGHT_BEARING_CATEGORIES
        and r.status is not OfficialRequirementStatus.SUPERSEDED
    ]


def official_weights_are_available(result: OfficialRequirementsResult | None) -> bool:
    """True only when every current official criterion carries a grounded weight
    and no criterion is in unresolved conflict. Otherwise the advisory rubric
    applies and must be labelled as advisory (architecture section 20)."""
    criteria = official_judging_criteria(result)
    return bool(criteria) and all(
        r.official_weight is not None and r.status is not OfficialRequirementStatus.CONFLICTED
        for r in criteria
    )
