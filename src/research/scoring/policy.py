"""``CLAIM-EVIDENCE-SCORING-POLICY-V1`` -- Phase 2F (section 9, section 11).

The policy in full, so an archived scorecard stays readable against the exact
rules that produced it.

Each direction (support, contradiction) earns an index out of 100 points, held
as integer basis points, from three dimensions over the **complete** Phase 2E
material component inventory:

``A. MATERIAL COMPONENT COVERAGE -- 0 to 50 points``
    ``adequately_covered_components / total_material_components * 50``.
    The denominator is every material component of the claim, including those
    no Phase 2D alignment ever anchored (ADR-016). "Adequately covered" means
    the component's Phase 2E coverage is ``SUPPORTED`` for the support channel
    or ``CONTRADICTED`` for the contradiction channel; a ``CONTESTED``
    component is adequately covered in *both* directions, because a real
    disagreement is two findings and not half of one.

``B. INDEPENDENT CORROBORATION -- 0 to 30 points``
    Per component, from Phase 2E's ``CorroborationLevel``: ``NONE`` 0,
    ``SINGLE_GROUP`` half, ``MULTIPLE_GROUPS`` full. Averaged over the complete
    inventory and scaled to 30.
    **Deliberately saturating.** Two independent groups and twenty independent
    groups earn the identical maximum. Going from one independent study to two
    is the epistemically large step; going from two to twenty is mostly a
    search-effort artifact, and rewarding it would make the score a measure of
    how hard someone looked. A later calibrated policy may add granularity --
    under a new policy version, never a silent retune.
    Because the level is computed from *direct* group ids, a component with only
    partial evidence scores ``NONE`` here: partial evidence earns directness
    half-credit (C) and no corroboration credit.

``C. RELATION DIRECTNESS -- 0 to 20 points``
    Per component: an adequately covered component earns the full factor, a
    partially covered one half, and ``CONTEXT_ONLY``, ``INSUFFICIENT``,
    ``NOT_RELEVANT`` and every ``DISQUALIFIED_*`` class earn nothing. Averaged
    over the complete inventory and scaled to 20.

``index = coverage + corroboration + directness``, bounded to ``[0, 100]``.
The three ceilings sum to exactly 100, so the bound is structural rather than a
clamp that hides an overflow.

**What the policy never does.** It never subtracts contradiction from support.
It never turns publication or retraction metadata into points (that is
``ScoreReliabilityProfile``, section 10). It never counts a provider
observation, an excerpt or a duplicate source record as corroboration -- those
collapsed into one ``IndependenceGroup`` in Phase 2E and arrive here already
collapsed. And it never calls a model: every number follows from Phase 2E's
structured output (section 19).
"""

from __future__ import annotations

from uuid import UUID

from src.research.scoring.arithmetic import (
    bounded,
    scaled_basis_points,
    weighted_basis_points,
)
from src.schemas.claim_evidence_score import (
    CORROBORATION_DIMENSION_MAX_BP,
    COVERAGE_DIMENSION_MAX_BP,
    DIRECTNESS_DIMENSION_MAX_BP,
    INDEX_MAX_BP,
    ComponentScoreTrace,
    DirectionalCoverageState,
    DirectionalScore,
    ScoreDimensions,
    ScoreDirection,
    ScoreDisposition,
    ScoreReasonCode,
)
from src.schemas.claim_component_inventory import ComponentInventoryCompleteness
from src.schemas.claim_sufficiency import (
    ClaimComponentSufficiency,
    ClaimSufficiencyAssessment,
    ComponentCoverage,
    CorroborationLevel,
    SufficiencyOutcome,
)

FULL_FACTOR_BP = 10_000
"""One whole component's worth of credit."""

HALF_FACTOR_BP = 5_000
"""Half credit, for a partial relation. Exact in basis points, which is why
factors are integers here rather than ``0.5`` floats."""

CORROBORATION_FACTOR_BP: dict[CorroborationLevel, int] = {
    CorroborationLevel.NONE: 0,
    CorroborationLevel.SINGLE_GROUP: HALF_FACTOR_BP,
    CorroborationLevel.MULTIPLE_GROUPS: FULL_FACTOR_BP,
}
"""The saturation rule, as data. ``MULTIPLE_GROUPS`` is the ceiling however many
groups there actually are (section 9B)."""

_SUPPORT_ADEQUATE_COVERAGE: frozenset[ComponentCoverage] = frozenset(
    {ComponentCoverage.SUPPORTED, ComponentCoverage.CONTESTED}
)
_CONTRADICTION_ADEQUATE_COVERAGE: frozenset[ComponentCoverage] = frozenset(
    {ComponentCoverage.CONTRADICTED, ComponentCoverage.CONTESTED}
)
"""``CONTESTED`` appears in both: the component is directly and independently
covered in each direction, and the conflict is preserved by scoring both rather
than by averaging them into one middling number (section 14)."""


def _sorted_unique(values: list[UUID]) -> list[UUID]:
    return sorted(set(values), key=str)


def support_state(component: ClaimComponentSufficiency) -> DirectionalCoverageState:
    """The support-direction state of one Phase 2E component.

    Derived from Phase 2E's coverage rather than recomputed from evidence: this
    phase respects the sufficiency verdict and never reclassifies it
    (section 5, section 13).
    """
    if component.coverage in _SUPPORT_ADEQUATE_COVERAGE:
        return DirectionalCoverageState.ADEQUATE
    if component.coverage is ComponentCoverage.BLOCKED_SOURCE_QUALITY:
        return DirectionalCoverageState.BLOCKED
    if component.partial_supporting_group_ids:
        return DirectionalCoverageState.PARTIAL
    if component.coverage is ComponentCoverage.CONTEXT_ONLY:
        return DirectionalCoverageState.CONTEXTUAL
    if component.coverage is ComponentCoverage.UNRESOLVED_RELEVANT:
        return DirectionalCoverageState.CONTEXTUAL
    return DirectionalCoverageState.NONE


def contradiction_state(
    component: ClaimComponentSufficiency,
) -> DirectionalCoverageState:
    """The contradiction-direction state of one Phase 2E component."""
    if component.coverage in _CONTRADICTION_ADEQUATE_COVERAGE:
        return DirectionalCoverageState.ADEQUATE
    if component.coverage is ComponentCoverage.BLOCKED_SOURCE_QUALITY:
        return DirectionalCoverageState.BLOCKED
    if component.partial_contradicting_group_ids:
        return DirectionalCoverageState.PARTIAL
    if component.coverage is ComponentCoverage.CONTEXT_ONLY:
        return DirectionalCoverageState.CONTEXTUAL
    if component.coverage is ComponentCoverage.UNRESOLVED_RELEVANT:
        return DirectionalCoverageState.CONTEXTUAL
    return DirectionalCoverageState.NONE


def directness_factor_bp(state: DirectionalCoverageState) -> int:
    """Relation-directness credit for one component in one direction (9C)."""
    if state is DirectionalCoverageState.ADEQUATE:
        return FULL_FACTOR_BP
    if state is DirectionalCoverageState.PARTIAL:
        return HALF_FACTOR_BP
    return 0


def corroboration_level(group_ids: list[UUID]) -> CorroborationLevel:
    """The corroboration level for one direction, from that direction's groups.

    Derived per direction here rather than read from Phase 2E's single
    ``ClaimComponentSufficiency.corroboration`` field, because that field cannot
    express a ``CONTESTED`` component: Phase 2E leaves it ``NONE`` there, since
    one shared label cannot say "one independent group supports this and one
    independent group contradicts it". Phase 2F needs both sides, so it counts
    each side's own groups.

    For an uncontested component this returns exactly what Phase 2E recorded --
    the same rule over the same group ids -- so the two layers agree wherever
    they can both speak.

    The count saturates at ``MULTIPLE_GROUPS``: two groups and twenty groups are
    the same tier (section 9B).
    """
    count = len(set(group_ids))
    if count == 0:
        return CorroborationLevel.NONE
    if count == 1:
        return CorroborationLevel.SINGLE_GROUP
    return CorroborationLevel.MULTIPLE_GROUPS


def component_trace(
    claim_id: str, component: ClaimComponentSufficiency
) -> ComponentScoreTrace:
    """The per-component score trace for one material claim component (section 15).

    Every material component of the claim gets a trace, including one no
    alignment anchored: it arrives with ``NO_EVIDENCE`` coverage and leaves with
    ``NONE`` in both directions, contributing 0 to both numerators while
    counting 1 in both denominators. That is how an unexamined component lowers
    the score instead of vanishing from it (section 14, ADR-016).

    The per-component point fields are the component's own *share* of the
    claim's index, i.e. what this component would contribute if every component
    were identical. They are audit values: the claim-level dimensions are
    computed from the factor sums directly, so a rounding difference between one
    component's share and the aggregate cannot corrupt the aggregate.
    """
    start, end, text = component.component_key
    s_state = support_state(component)
    c_state = contradiction_state(component)
    s_corr = corroboration_level(list(component.supporting_group_ids))
    c_corr = corroboration_level(list(component.contradicting_group_ids))
    s_direct = directness_factor_bp(s_state)
    c_direct = directness_factor_bp(c_state)

    reasons: list[ScoreReasonCode] = []
    if s_state is DirectionalCoverageState.ADEQUATE:
        reasons.append(ScoreReasonCode.DIRECT_RELATION_CREDIT)
    elif s_state is DirectionalCoverageState.PARTIAL:
        reasons.append(ScoreReasonCode.PARTIAL_RELATION_CREDIT)
    elif s_state is DirectionalCoverageState.CONTEXTUAL:
        reasons.append(
            ScoreReasonCode.CONTEXT_ONLY_NO_CREDIT
            if component.coverage is ComponentCoverage.CONTEXT_ONLY
            else ScoreReasonCode.INSUFFICIENT_NO_CREDIT
        )
    if c_state is DirectionalCoverageState.ADEQUATE:
        reasons.append(ScoreReasonCode.CONTRADICTION_PRESENT)
    if s_corr is CorroborationLevel.SINGLE_GROUP or (
        c_corr is CorroborationLevel.SINGLE_GROUP
    ):
        reasons.append(ScoreReasonCode.SINGLE_GROUP_CORROBORATION)
    if s_corr is CorroborationLevel.MULTIPLE_GROUPS or (
        c_corr is CorroborationLevel.MULTIPLE_GROUPS
    ):
        reasons.append(ScoreReasonCode.MULTIPLE_GROUP_CORROBORATION)
        reasons.append(ScoreReasonCode.CORROBORATION_SATURATED)
    if component.disqualified_group_ids:
        reasons.append(ScoreReasonCode.RETRACTED_SOURCE_EXCLUDED)
    if s_state is DirectionalCoverageState.BLOCKED:
        reasons.append(ScoreReasonCode.BLOCKED_SOURCE_QUALITY_SCORE_WITHHELD)

    return ComponentScoreTrace(
        claim_id=claim_id,
        anchor_start=start,
        anchor_end=end,
        anchor_text=text,
        support_state=s_state,
        contradiction_state=c_state,
        supporting_group_ids=_sorted_unique(list(component.supporting_group_ids)),
        contradicting_group_ids=_sorted_unique(list(component.contradicting_group_ids)),
        disqualified_group_ids=_sorted_unique(list(component.disqualified_group_ids)),
        support_corroboration=s_corr,
        contradiction_corroboration=c_corr,
        support_directness_factor_bp=s_direct,
        contradiction_directness_factor_bp=c_direct,
        support_points_bp=_component_share_bp(s_state, s_corr, s_direct),
        contradiction_points_bp=_component_share_bp(c_state, c_corr, c_direct),
        reason_codes=list(dict.fromkeys(reasons)),
    )


def _component_share_bp(
    state: DirectionalCoverageState, level: CorroborationLevel, directness_bp: int
) -> int:
    """One component's share of a directional index, as if it stood alone.

    Audit information: the claim-level index is computed from the aggregate
    factor sums, not by adding these up (see ``component_trace``).
    """
    coverage = (
        COVERAGE_DIMENSION_MAX_BP
        if state is DirectionalCoverageState.ADEQUATE
        else 0
    )
    corroboration = weighted_basis_points(
        CORROBORATION_FACTOR_BP[level], 1, CORROBORATION_DIMENSION_MAX_BP
    )
    directness = weighted_basis_points(directness_bp, 1, DIRECTNESS_DIMENSION_MAX_BP)
    return bounded(coverage + corroboration + directness, INDEX_MAX_BP)


def directional_score(
    direction: ScoreDirection, traces: list[ComponentScoreTrace]
) -> DirectionalScore:
    """One channel's index over the complete component inventory (section 9).

    ``len(traces)`` is the denominator for all three dimensions, and it is the
    complete Phase 2E inventory rather than the covered subset -- the single
    arithmetic fact that makes an unexamined material component lower the score
    (section 14).
    """
    total = len(traces)
    is_support = direction is ScoreDirection.SUPPORT
    state_of = (
        (lambda t: t.support_state) if is_support else (lambda t: t.contradiction_state)
    )
    level_of = (
        (lambda t: t.support_corroboration)
        if is_support
        else (lambda t: t.contradiction_corroboration)
    )
    directness_of = (
        (lambda t: t.support_directness_factor_bp)
        if is_support
        else (lambda t: t.contradiction_directness_factor_bp)
    )
    groups_of = (
        (lambda t: t.supporting_group_ids)
        if is_support
        else (lambda t: t.contradicting_group_ids)
    )

    covered = sum(
        1 for t in traces if state_of(t) is DirectionalCoverageState.ADEQUATE
    )
    partial = sum(1 for t in traces if state_of(t) is DirectionalCoverageState.PARTIAL)
    saturated = sum(
        1 for t in traces if level_of(t) is CorroborationLevel.MULTIPLE_GROUPS
    )
    corroboration_sum = sum(CORROBORATION_FACTOR_BP[level_of(t)] for t in traces)
    directness_sum = sum(directness_of(t) for t in traces)

    dimensions = ScoreDimensions(
        coverage_bp=bounded(
            scaled_basis_points(covered, total, COVERAGE_DIMENSION_MAX_BP),
            COVERAGE_DIMENSION_MAX_BP,
        ),
        corroboration_bp=bounded(
            weighted_basis_points(
                corroboration_sum, total, CORROBORATION_DIMENSION_MAX_BP
            ),
            CORROBORATION_DIMENSION_MAX_BP,
        ),
        directness_bp=bounded(
            weighted_basis_points(
                directness_sum, total, DIRECTNESS_DIMENSION_MAX_BP
            ),
            DIRECTNESS_DIMENSION_MAX_BP,
        ),
    )
    contributing: list[UUID] = []
    for trace in traces:
        contributing.extend(groups_of(trace))

    return DirectionalScore(
        direction=direction,
        dimensions=dimensions,
        index_bp=dimensions.total_bp,
        covered_components=covered,
        partial_components=partial,
        total_components=total,
        contributing_group_ids=_sorted_unique(contributing),
        saturated_components=saturated,
    )


def channel_reasons(
    direction: ScoreDirection, score: DirectionalScore
) -> list[ScoreReasonCode]:
    """Claim-level coverage reason codes for one channel."""
    is_support = direction is ScoreDirection.SUPPORT
    full = (
        ScoreReasonCode.FULL_COMPONENT_SUPPORT_COVERAGE
        if is_support
        else ScoreReasonCode.FULL_COMPONENT_CONTRADICTION_COVERAGE
    )
    part = (
        ScoreReasonCode.PARTIAL_COMPONENT_SUPPORT_COVERAGE
        if is_support
        else ScoreReasonCode.PARTIAL_COMPONENT_CONTRADICTION_COVERAGE
    )
    none = (
        ScoreReasonCode.NO_DIRECT_SUPPORT
        if is_support
        else ScoreReasonCode.NO_DIRECT_CONTRADICTION
    )
    if score.total_components and score.covered_components == score.total_components:
        return [full]
    if score.covered_components:
        return [part]
    return [none]


def decide_disposition(
    assessment: ClaimSufficiencyAssessment,
    support: DirectionalScore,
    contradiction: DirectionalScore,
    *,
    input_ready: bool = True,
) -> tuple[ScoreDisposition, list[ScoreReasonCode]]:
    """Whether a primary scalar may be issued, and why not when it may not.

    Precedence, most fundamental first:

    1. **Input not ready, or the component inventory is not ``COMPLETE``.**
       Part of the material proposition was never accounted for, so no number
       over that denominator can be reported as the claim's score (ADR-016).
    2. **Phase 2E blocked on source quality.** Direct evidence existed and none
       of it survived; a scalar would describe evidence that was refused.
    3. **Phase 2E ``CONTESTED``.** Both channels stay available and the scalar
       is withheld, because one number cannot carry a real disagreement
       (section 8, section 14).
    4. **Phase 2E ``NO_DIRECT_EVIDENCE``.** An evaluated zero-directional
       posture. Both indices are a real ``0``; the *primary scalar* is still
       withheld so ``0`` is never mistaken for a low score (section 11).
    5. Otherwise ``SCORED``.

    Phase 2E's outcome is read, never rewritten (section 13).
    """
    withheld: list[ScoreReasonCode] = []

    if (
        not input_ready
        or assessment.inventory_completeness
        is not ComponentInventoryCompleteness.COMPLETE
    ):
        withheld.append(ScoreReasonCode.INCOMPLETE_INPUT_SCORE_WITHHELD)
        if assessment.unexamined_component_count:
            withheld.append(
                ScoreReasonCode.UNEXAMINED_MATERIAL_COMPONENT_IN_DENOMINATOR
            )
        if contradiction.covered_components:
            withheld.append(ScoreReasonCode.CONTRADICTION_PRESENT)
        return ScoreDisposition.INCOMPLETE_INPUT_SCALAR_WITHHELD, withheld

    if assessment.outcome is SufficiencyOutcome.BLOCKED_SOURCE_QUALITY:
        withheld.append(ScoreReasonCode.BLOCKED_SOURCE_QUALITY_SCORE_WITHHELD)
        return ScoreDisposition.BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD, withheld

    if assessment.outcome is SufficiencyOutcome.CONTESTED:
        withheld.append(ScoreReasonCode.CONTESTED_FINAL_SCORE_WITHHELD)
        withheld.append(ScoreReasonCode.CONTRADICTION_PRESENT)
        return ScoreDisposition.CONTESTED_SCALAR_WITHHELD, withheld

    if assessment.outcome is SufficiencyOutcome.NO_DIRECT_EVIDENCE:
        withheld.append(ScoreReasonCode.NO_DIRECT_SUPPORT)
        return ScoreDisposition.NO_DIRECT_EVIDENCE, withheld

    return ScoreDisposition.SCORED, []


def final_support_index_bp(
    disposition: ScoreDisposition, support: DirectionalScore
) -> int | None:
    """The primary scalar, or ``None``.

    When issued it is *exactly* ``support.index_bp``. It is never
    ``support - contradiction``: a net would make ``90/80`` read the same as
    ``10/0``, and the contradiction channel exists precisely so it cannot
    (section 12).
    """
    if disposition is ScoreDisposition.SCORED:
        return support.index_bp
    return None


__all__ = [
    "CORROBORATION_FACTOR_BP",
    "corroboration_level",
    "FULL_FACTOR_BP",
    "HALF_FACTOR_BP",
    "channel_reasons",
    "component_trace",
    "contradiction_state",
    "decide_disposition",
    "directional_score",
    "directness_factor_bp",
    "final_support_index_bp",
    "support_state",
]
