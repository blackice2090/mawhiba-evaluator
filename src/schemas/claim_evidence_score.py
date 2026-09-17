"""Claim-evidence scoring contracts -- Phase 2F (section 6, section 7, section 21).

The first phase permitted to derive a numeric claim-level index, and the whole
module is built around what that number is *not*.

``support_index`` is a deterministic index of structured evidentiary support for
one claim under ``CLAIM-EVIDENCE-SCORING-POLICY-V1``. It is not a probability
that the claim is true, not scientific confidence, not a project quality score
and not a Mawhiba/Ibdaa judging score. A reader who sees ``support_index = 80``
must read "this claim's evidence posture scores 80 out of 100 under a published,
versioned point allocation", never "this claim is 80% likely to be true"
(ADR-017).

Three structural rules make that readable rather than merely documented:

**The vector is canonical.** Every index is the sum of named dimensions that
stay individually visible -- component coverage, independent corroboration and
relation directness. ``index_bp`` is validated to equal that sum exactly, so
the scalar can never say something the dimensions do not.

**Support and contradiction never merge.** They are separate
``DirectionalScore`` records. There is no ``net_score`` field, and there is no
field anywhere on these contracts that could hold one: ``90 support / 80
contradiction`` must not become indistinguishable from ``10 support / 0
contradiction`` (section 8).

**Source quality is a reliability layer, never hidden points.**
``ScoreReliabilityProfile`` reports retraction, publication and scope posture as
a finite taxonomy beside the score. It adds no points and subtracts none, so a
preprint cannot be quietly discounted by an unpublished weight.

Everything here lives on the ``ResearchRun`` (section 4). No type in this module
has a ``claim_status``, ``confidence``, ``trust_gate`` or ``evaluation_status``
field, and none is a ``ScoreRecord``: canonical project scoring is a later,
explicitly reviewed phase (ADR-010, ADR-017).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.claim_component_inventory import ComponentInventoryCompleteness
from src.schemas.claim_sufficiency import (
    ContentScopeLimitation,
    CorroborationLevel,
    QualityDimension,
    SufficiencyOutcome,
)
from src.schemas.common import MawhibaModel, UtcDatetime, utc_now

CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION = "CLAIM-EVIDENCE-SCORE-SCHEMA-V1"
"""The shape of the records in this module."""

CLAIM_EVIDENCE_SCORING_POLICY_VERSION = "CLAIM-EVIDENCE-SCORING-POLICY-V1"
"""The point allocation, saturation rule, directness factors and disposition
policy. Any semantic change to any of those requires a bump here (section 18).
A silent retune would make two archived scorecards incomparable while both
claimed the same policy."""

SCORE_ARITHMETIC_VERSION = "SCORE-ARITHMETIC-V1"
"""Integer basis points, ``Decimal`` intermediates, ``ROUND_HALF_EVEN``
(section 16). Named separately because a rounding change alters stored numbers
without altering the policy that chose them."""

SCORE_RELIABILITY_PROFILE_VERSION = "SCORE-RELIABILITY-PROFILE-V1"
"""The reliability taxonomy and the facts it reads."""

INDEX_MAX_BP = 10_000
"""A directional index is an integer 0-10000 basis points: 10000 bp = 100.00."""

COVERAGE_DIMENSION_MAX_BP = 5_000
CORROBORATION_DIMENSION_MAX_BP = 3_000
DIRECTNESS_DIMENSION_MAX_BP = 2_000
"""The three dimensions of the 0-100 index: 50 + 30 + 20 points (section 9).
They sum to exactly ``INDEX_MAX_BP`` -- a test asserts it rather than trusting
the arithmetic to stay true through an edit."""

MAX_SCORECARD_COMPONENTS = 64
"""Mirrors ``MAX_CLAIM_COMPONENTS``: one trace per inventory component."""


def scorecard_id_for(scoring_run_id: UUID, claim_id: str) -> UUID:
    """Deterministic scorecard id: one claim, one scoring pass, one scorecard.

    ``uuid5`` rather than ``uuid4`` for the same reason Phase 2E derives its
    assessment ids that way: a replay or a checkpoint resume recomputes the same
    scorecard, and a random id would make one computation look like two findings
    (section 25).
    """
    return uuid5(NAMESPACE_URL, f"claim-evidence-scorecard:{scoring_run_id}:{claim_id}")


def index_display(index_bp: int) -> Decimal:
    """Basis points as the two-decimal display value (section 16).

    ``Decimal`` rather than ``float``: the stored integer is the source of
    truth, and this is the only permitted rendering of it. Returning a float
    here would reintroduce binary rounding at the last step.
    """
    return (Decimal(index_bp) / Decimal(100)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Taxonomies
# ---------------------------------------------------------------------------


class ScoreDirection(StrEnum):
    """The two channels, which are never combined into a third (section 8)."""

    SUPPORT = "SUPPORT"
    CONTRADICTION = "CONTRADICTION"


class DirectionalCoverageState(StrEnum):
    """How one material component is covered *in one direction*.

    Deliberately directional and deliberately not Phase 2E's
    ``ComponentCoverage``: a ``CONTESTED`` component is ``ADEQUATE`` in both
    directions at once, and a single shared state could not say that without
    picking a winner.
    """

    ADEQUATE = "ADEQUATE"
    PARTIAL = "PARTIAL"
    CONTEXTUAL = "CONTEXTUAL"
    NONE = "NONE"
    BLOCKED = "BLOCKED"


ADEQUATE_DIRECTIONAL_STATES: frozenset[DirectionalCoverageState] = frozenset(
    {DirectionalCoverageState.ADEQUATE}
)
"""States that earn component-coverage points. ``PARTIAL`` earns directness
credit at half factor but never counts as a covered component: half-covering a
component is not covering it (section 9A)."""


class ScoreDisposition(StrEnum):
    """Whether a single primary scalar may be reported at all (section 11).

    Not every claim should receive an interpretable final number. A disposition
    is the machine-readable reason a scalar was issued or withheld, so
    "withheld because the evidence conflicts" never reads as "scored low".
    """

    SCORED = "SCORED"
    CONTESTED_SCALAR_WITHHELD = "CONTESTED_SCALAR_WITHHELD"
    BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD = "BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD"
    INCOMPLETE_INPUT_SCALAR_WITHHELD = "INCOMPLETE_INPUT_SCALAR_WITHHELD"
    NO_DIRECT_EVIDENCE = "NO_DIRECT_EVIDENCE"


SCALAR_WITHHELD_DISPOSITIONS: frozenset[ScoreDisposition] = frozenset(
    {
        ScoreDisposition.CONTESTED_SCALAR_WITHHELD,
        ScoreDisposition.BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD,
        ScoreDisposition.INCOMPLETE_INPUT_SCALAR_WITHHELD,
        ScoreDisposition.NO_DIRECT_EVIDENCE,
    }
)
"""Dispositions that must carry ``final_support_index_bp = None``.

``NO_DIRECT_EVIDENCE`` is in this set on purpose. Its directional indices are a
real evaluated ``0``, and issuing ``0`` as the claim's *primary score* would
invite reading it as a low score rather than as "nothing direct was found"
(section 11, section 31)."""


class ReliabilityPosture(StrEnum):
    """A finite reliability taxonomy over Phase 2E source-quality facts.

    Deliberately **not** called scientific confidence, and deliberately not a
    number: it reports the form and traceability of what stands behind the
    score, and it never moves the score itself (section 10).

    ``INDETERMINATE`` is the honest answer when the contributing sources state
    nothing about publication form or retraction. It is not a middle value
    between higher and limited -- it is the absence of the facts the other
    values are made of.
    """

    HIGHER_RELIABILITY = "HIGHER_RELIABILITY"
    MODERATE_RELIABILITY = "MODERATE_RELIABILITY"
    LIMITED_RELIABILITY = "LIMITED_RELIABILITY"
    INDETERMINATE = "INDETERMINATE"


class ScoreReasonCode(StrEnum):
    """The authoritative, finite explanation vocabulary for a scorecard.

    Structured codes rather than prose, for the Phase 2E reason: a report has to
    be able to say *why* a number came out as it did mechanically, and free text
    invites an explanation nobody computed (section 20).
    """

    FULL_COMPONENT_SUPPORT_COVERAGE = "FULL_COMPONENT_SUPPORT_COVERAGE"
    PARTIAL_COMPONENT_SUPPORT_COVERAGE = "PARTIAL_COMPONENT_SUPPORT_COVERAGE"
    NO_DIRECT_SUPPORT = "NO_DIRECT_SUPPORT"
    FULL_COMPONENT_CONTRADICTION_COVERAGE = "FULL_COMPONENT_CONTRADICTION_COVERAGE"
    PARTIAL_COMPONENT_CONTRADICTION_COVERAGE = (
        "PARTIAL_COMPONENT_CONTRADICTION_COVERAGE"
    )
    NO_DIRECT_CONTRADICTION = "NO_DIRECT_CONTRADICTION"
    SINGLE_GROUP_CORROBORATION = "SINGLE_GROUP_CORROBORATION"
    MULTIPLE_GROUP_CORROBORATION = "MULTIPLE_GROUP_CORROBORATION"
    CORROBORATION_SATURATED = "CORROBORATION_SATURATED"
    DUPLICATE_SOURCE_COLLAPSED = "DUPLICATE_SOURCE_COLLAPSED"
    DUPLICATE_EXCERPT_COLLAPSED = "DUPLICATE_EXCERPT_COLLAPSED"
    DIRECT_RELATION_CREDIT = "DIRECT_RELATION_CREDIT"
    PARTIAL_RELATION_CREDIT = "PARTIAL_RELATION_CREDIT"
    CONTEXT_ONLY_NO_CREDIT = "CONTEXT_ONLY_NO_CREDIT"
    NOT_RELEVANT_NO_CREDIT = "NOT_RELEVANT_NO_CREDIT"
    INSUFFICIENT_NO_CREDIT = "INSUFFICIENT_NO_CREDIT"
    CONTRADICTION_PRESENT = "CONTRADICTION_PRESENT"
    CONTESTED_FINAL_SCORE_WITHHELD = "CONTESTED_FINAL_SCORE_WITHHELD"
    BLOCKED_SOURCE_QUALITY_SCORE_WITHHELD = "BLOCKED_SOURCE_QUALITY_SCORE_WITHHELD"
    INCOMPLETE_INPUT_SCORE_WITHHELD = "INCOMPLETE_INPUT_SCORE_WITHHELD"
    UNEXAMINED_MATERIAL_COMPONENT_IN_DENOMINATOR = (
        "UNEXAMINED_MATERIAL_COMPONENT_IN_DENOMINATOR"
    )
    ABSTRACT_ONLY_RELIABILITY_LIMITATION = "ABSTRACT_ONLY_RELIABILITY_LIMITATION"
    PREPRINT_RELIABILITY_LIMITATION = "PREPRINT_RELIABILITY_LIMITATION"
    UNKNOWN_PUBLICATION_STATUS = "UNKNOWN_PUBLICATION_STATUS"
    UNKNOWN_RETRACTION_STATUS = "UNKNOWN_RETRACTION_STATUS"
    RETRACTED_SOURCE_EXCLUDED = "RETRACTED_SOURCE_EXCLUDED"
    UNTRACEABLE_SOURCE_EXCLUDED = "UNTRACEABLE_SOURCE_EXCLUDED"


# ---------------------------------------------------------------------------
# The score vector
# ---------------------------------------------------------------------------


class ScoreDimensions(MawhibaModel):
    """The three named dimensions of one directional index (section 9).

    Stored in integer basis points, each bounded to its own ceiling. Keeping
    them as fields rather than as a derivation is the point: a reader can see
    that an index of 6500 is "every component covered, one group each, all
    direct" and not "most components covered by many independent studies".
    """

    coverage_bp: int = Field(default=0, ge=0, le=COVERAGE_DIMENSION_MAX_BP)
    corroboration_bp: int = Field(default=0, ge=0, le=CORROBORATION_DIMENSION_MAX_BP)
    directness_bp: int = Field(default=0, ge=0, le=DIRECTNESS_DIMENSION_MAX_BP)

    @property
    def total_bp(self) -> int:
        return self.coverage_bp + self.corroboration_bp + self.directness_bp


class DirectionalScore(MawhibaModel):
    """One channel's index, with the arithmetic that produced it.

    ``index_bp`` is validated against ``dimensions.total_bp``, so the scalar and
    the vector cannot drift apart -- the reconciliation the specification
    requires in schema validation rather than in policy code (section 21).

    ``covered_components``/``total_components`` are carried so the coverage
    fraction is auditable without recomputing it, and so an inflated
    denominator is visible: ``total_components`` is the *complete* Phase 2E
    inventory, including material components no alignment ever anchored.
    """

    direction: ScoreDirection
    dimensions: ScoreDimensions = Field(default_factory=ScoreDimensions)
    index_bp: int = Field(default=0, ge=0, le=INDEX_MAX_BP)

    covered_components: int = Field(default=0, ge=0)
    partial_components: int = Field(default=0, ge=0)
    total_components: int = Field(default=0, ge=0)
    contributing_group_ids: list[UUID] = Field(
        default_factory=list,
        description="Independence groups that earned credit in this direction. "
        "Group ids, never evidence items, provider observations or excerpts.",
    )
    saturated_components: int = Field(
        default=0,
        ge=0,
        description="Components already at maximum corroboration, where a "
        "further independent group adds nothing (section 9B).",
    )

    @model_validator(mode="after")
    def _arithmetic_reconciles(self) -> DirectionalScore:
        if self.index_bp != self.dimensions.total_bp:
            raise ValueError(
                f"{self.direction.value} index_bp {self.index_bp} does not equal "
                f"the dimension sum {self.dimensions.total_bp}; a scalar that "
                "disagrees with its own vector is exactly what section 7 forbids"
            )
        if self.covered_components > self.total_components:
            raise ValueError(
                "covered_components cannot exceed the complete component inventory"
            )
        if self.partial_components > self.total_components:
            raise ValueError(
                "partial_components cannot exceed the complete component inventory"
            )
        if self.saturated_components > self.total_components:
            raise ValueError(
                "saturated_components cannot exceed the complete component inventory"
            )
        if len(set(self.contributing_group_ids)) != len(self.contributing_group_ids):
            raise ValueError(
                "contributing_group_ids must be distinct; a repeated group would "
                "be one study counted twice"
            )
        if self.total_components == 0 and self.index_bp:
            raise ValueError(
                "an index cannot be positive with no material component to score"
            )
        return self

    @property
    def index(self) -> Decimal:
        """The two-decimal display value. Never a probability (section 6)."""
        return index_display(self.index_bp)


class ComponentScoreTrace(MawhibaModel):
    """Per-component arithmetic for one claim component, in both directions.

    The anchor is an exact span of the claim's own text, taken from the verified
    Phase 2E ``ClaimComponentInventory``. The claim text is not duplicated
    beyond that anchor (section 15): two copies of a claim are two things that
    can disagree.
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    anchor_start: int = Field(ge=0)
    anchor_end: int = Field(ge=1)
    anchor_text: str = Field(min_length=1)

    support_state: DirectionalCoverageState = DirectionalCoverageState.NONE
    contradiction_state: DirectionalCoverageState = DirectionalCoverageState.NONE

    supporting_group_ids: list[UUID] = Field(default_factory=list)
    contradicting_group_ids: list[UUID] = Field(default_factory=list)
    disqualified_group_ids: list[UUID] = Field(default_factory=list)

    support_corroboration: CorroborationLevel = CorroborationLevel.NONE
    contradiction_corroboration: CorroborationLevel = CorroborationLevel.NONE

    support_directness_factor_bp: int = Field(default=0, ge=0, le=10_000)
    contradiction_directness_factor_bp: int = Field(default=0, ge=0, le=10_000)

    support_points_bp: int = Field(default=0, ge=0, le=INDEX_MAX_BP)
    contradiction_points_bp: int = Field(default=0, ge=0, le=INDEX_MAX_BP)

    reason_codes: list[ScoreReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _trace_holds(self) -> ComponentScoreTrace:
        if self.anchor_end <= self.anchor_start:
            raise ValueError("anchor_end must be after anchor_start")
        if len(self.anchor_text) != self.anchor_end - self.anchor_start:
            raise ValueError("anchor text length must match the span")
        for name in (
            "supporting_group_ids",
            "contradicting_group_ids",
            "disqualified_group_ids",
        ):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must hold distinct independence groups")
        # Corroboration is a label over a group count, so the two must agree or
        # the saturation rule could be stated without being applied.
        for groups, level, label in (
            (self.supporting_group_ids, self.support_corroboration, "support"),
            (
                self.contradicting_group_ids,
                self.contradiction_corroboration,
                "contradiction",
            ),
        ):
            expected = {0: CorroborationLevel.NONE, 1: CorroborationLevel.SINGLE_GROUP}.get(
                len(groups), CorroborationLevel.MULTIPLE_GROUPS
            )
            if level is not expected:
                raise ValueError(
                    f"{label} corroboration {level.value} disagrees with "
                    f"{len(groups)} independent group(s)"
                )
        if (
            self.support_state is DirectionalCoverageState.ADEQUATE
            and not self.supporting_group_ids
        ):
            raise ValueError(
                "an ADEQUATE support state needs at least one eligible supporting "
                "independence group"
            )
        if (
            self.contradiction_state is DirectionalCoverageState.ADEQUATE
            and not self.contradicting_group_ids
        ):
            raise ValueError(
                "an ADEQUATE contradiction state needs at least one eligible "
                "contradicting independence group"
            )
        return self

    @property
    def component_key(self) -> tuple[int, int, str]:
        return (self.anchor_start, self.anchor_end, self.anchor_text)


class ScoreReliabilityProfile(MawhibaModel):
    """What stands behind the score, as facts and a posture -- never as points.

    Every field here is read from Phase 2E's trusted metadata and none of it
    moves an index (section 10). That separation is the whole design: a hidden
    "preprint penalty" would be a score change nobody could audit, while
    ``LIMITED_RELIABILITY`` beside an unchanged index is a statement a reviewer
    can check and disagree with.

    ``UNKNOWN`` is never read as favorable, and there is no field that could
    make it so: the unknown counts are their own dimensions.
    """

    posture: ReliabilityPosture = ReliabilityPosture.INDETERMINATE

    retracted_group_count: int = Field(default=0, ge=0)
    untraceable_profile_count: int = Field(default=0, ge=0)
    preprint_group_count: int = Field(default=0, ge=0)
    peer_reviewed_group_count: int = Field(default=0, ge=0)
    unknown_publication_group_count: int = Field(default=0, ge=0)
    unknown_retraction_group_count: int = Field(default=0, ge=0)
    disqualified_group_count: int = Field(default=0, ge=0)
    contributing_group_count: int = Field(default=0, ge=0)

    content_scope_ceiling: ContentScopeLimitation | None = Field(
        default=None,
        description="The strongest scope any contributing evidence had. ``None`` "
        "when nothing contributed -- never silently FULL_TEXT.",
    )
    unknown_dimensions: list[QualityDimension] = Field(default_factory=list)
    reason_codes: list[ScoreReasonCode] = Field(default_factory=list)
    profile_version: str = SCORE_RELIABILITY_PROFILE_VERSION

    @model_validator(mode="after")
    def _posture_is_earned(self) -> ScoreReliabilityProfile:
        if (
            self.posture is not ReliabilityPosture.INDETERMINATE
            and self.contributing_group_count == 0
        ):
            raise ValueError(
                f"posture {self.posture.value} claims more than INDETERMINATE with "
                "no contributing independence group; nothing stands behind it"
            )
        if (
            self.posture is ReliabilityPosture.HIGHER_RELIABILITY
            and self.peer_reviewed_group_count == 0
        ):
            raise ValueError(
                "HIGHER_RELIABILITY requires at least one contributing group whose "
                "metadata states formal publication; it is never inferred "
                "(section 10)"
            )
        return self


# ---------------------------------------------------------------------------
# The scorecard
# ---------------------------------------------------------------------------


class ClaimEvidenceScoreCard(MawhibaModel):
    """The Phase 2F evidence scorecard for ONE claim.

    **Not a claim mutation and not a project score.** This record sits beside
    the claim and references it by id. It has no claim status, no confidence, no
    ``ScoreRecord``, no rubric axis, no trust gate and no evaluation status, so
    promoting an evidence index into canonical project truth is a later reviewed
    phase and cannot happen here by accident (ADR-017).

    **The vector is canonical, the scalar is secondary.** ``support`` and
    ``contradiction`` are always present and always computed.
    ``final_support_index_bp`` is optional, equals ``support.index_bp`` when it
    is issued at all, and is ``None`` whenever a single number would hide the
    posture -- a conflict, a source-quality block, or an incomplete input.

    **``None`` and ``0`` mean different things** (section 11). ``0`` is an
    evaluated index with no directional evidentiary support. ``None`` is no
    scalar issued. A reader must never have to guess which one they are looking
    at, so the disposition states it.
    """

    scorecard_id: UUID
    research_run_id: UUID
    scoring_run_id: UUID
    sufficiency_run_id: UUID
    assessment_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)

    sufficiency_outcome: SufficiencyOutcome = Field(
        description="The Phase 2E outcome, carried unchanged. Phase 2F respects "
        "it and never rewrites it (section 13)."
    )
    inventory_completeness: ComponentInventoryCompleteness = Field(
        description="Phase 2E.1 component completeness, carried so the "
        "denominator's own status travels with the score (ADR-016)."
    )

    support: DirectionalScore
    contradiction: DirectionalScore
    component_traces: list[ComponentScoreTrace] = Field(default_factory=list)
    reliability: ScoreReliabilityProfile = Field(
        default_factory=ScoreReliabilityProfile
    )

    disposition: ScoreDisposition
    final_support_index_bp: int | None = Field(default=None, ge=0, le=INDEX_MAX_BP)

    reason_codes: list[ScoreReasonCode] = Field(default_factory=list)
    withheld_reasons: list[ScoreReasonCode] = Field(
        default_factory=list,
        description="Why no primary scalar was issued. Empty exactly when one "
        "was.",
    )
    unexamined_component_count: int = Field(
        default=0,
        ge=0,
        description="Material claim components no alignment anchored, kept in "
        "the score denominator (ADR-016, section 14).",
    )

    input_fingerprint: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="sha256 over the exact scoring-relevant Phase 2E inputs "
        "(section 17). No timestamp participates, so identical inputs reproduce "
        "an identical fingerprint and a changed input cannot keep one.",
    )

    schema_version: str = CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION
    policy_version: str = CLAIM_EVIDENCE_SCORING_POLICY_VERSION
    arithmetic_version: str = SCORE_ARITHMETIC_VERSION
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _consistent(self) -> ClaimEvidenceScoreCard:
        if self.support.direction is not ScoreDirection.SUPPORT:
            raise ValueError("the support channel must carry direction SUPPORT")
        if self.contradiction.direction is not ScoreDirection.CONTRADICTION:
            raise ValueError(
                "the contradiction channel must carry direction CONTRADICTION"
            )
        if self.support.total_components != self.contradiction.total_components:
            raise ValueError(
                "both channels must score the same complete component inventory; "
                "a direction with its own denominator could be made to look "
                "better by shrinking it"
            )

        if any(t.claim_id != self.claim_id for t in self.component_traces):
            raise ValueError(
                "a component trace belongs to a different claim; cross-claim "
                "scorecard contamination is refused (section 23)"
            )
        keys = [t.component_key for t in self.component_traces]
        if len(set(keys)) != len(keys):
            raise ValueError("a component anchor appears twice in one scorecard")
        if len(keys) > MAX_SCORECARD_COMPONENTS:
            raise ValueError(
                f"a scorecard may hold at most {MAX_SCORECARD_COMPONENTS} traces"
            )
        if len(keys) != self.support.total_components:
            raise ValueError(
                f"the scorecard holds {len(keys)} component trace(s) but scores a "
                f"denominator of {self.support.total_components}; the traces must "
                "reconcile with the aggregate dimensions (section 21)"
            )

        # Aggregate coverage counts must equal what the traces actually say.
        for channel, state_attr, label in (
            (self.support, "support_state", "support"),
            (self.contradiction, "contradiction_state", "contradiction"),
        ):
            adequate = sum(
                1
                for t in self.component_traces
                if getattr(t, state_attr) in ADEQUATE_DIRECTIONAL_STATES
            )
            partial = sum(
                1
                for t in self.component_traces
                if getattr(t, state_attr) is DirectionalCoverageState.PARTIAL
            )
            if channel.covered_components != adequate:
                raise ValueError(
                    f"{label} covered_components {channel.covered_components} does "
                    f"not match the {adequate} adequately covered trace(s)"
                )
            if channel.partial_components != partial:
                raise ValueError(
                    f"{label} partial_components {channel.partial_components} does "
                    f"not match the {partial} partially covered trace(s)"
                )

        # The release-critical rule: a scalar exists exactly when it is issuable.
        if self.disposition in SCALAR_WITHHELD_DISPOSITIONS:
            if self.final_support_index_bp is not None:
                raise ValueError(
                    f"disposition {self.disposition.value} withholds the primary "
                    "scalar; final_support_index_bp must be None, because a "
                    "number here would hide exactly what the disposition records"
                )
            if not self.withheld_reasons:
                raise ValueError(
                    f"disposition {self.disposition.value} must state why the "
                    "scalar was withheld"
                )
        else:
            if self.final_support_index_bp is None:
                raise ValueError(
                    "disposition SCORED must issue final_support_index_bp"
                )
            if self.final_support_index_bp != self.support.index_bp:
                raise ValueError(
                    "final_support_index_bp must equal support.index_bp; it is the "
                    "support index reported as primary, never a net of support "
                    "and contradiction (section 12)"
                )
            if self.withheld_reasons:
                raise ValueError(
                    "a SCORED card cannot state withheld reasons"
                )
            if self.inventory_completeness is not ComponentInventoryCompleteness.COMPLETE:
                raise ValueError(
                    f"a SCORED card requires a COMPLETE component inventory; "
                    f"completeness={self.inventory_completeness.value} means part "
                    "of the material proposition was never accounted for "
                    "(ADR-016, section 12)"
                )
            if self.sufficiency_outcome in (
                SufficiencyOutcome.CONTESTED,
                SufficiencyOutcome.BLOCKED_SOURCE_QUALITY,
            ):
                raise ValueError(
                    f"Phase 2E outcome {self.sufficiency_outcome.value} withholds a "
                    "primary scalar; the disposition must agree with it "
                    "(section 13)"
                )

        # Disposition must agree with the Phase 2E outcome it was derived from.
        if (
            self.disposition is ScoreDisposition.CONTESTED_SCALAR_WITHHELD
            and self.sufficiency_outcome is not SufficiencyOutcome.CONTESTED
        ):
            raise ValueError(
                "CONTESTED_SCALAR_WITHHELD requires the Phase 2E CONTESTED outcome"
            )
        if (
            self.disposition
            is ScoreDisposition.BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD
            and self.sufficiency_outcome
            is not SufficiencyOutcome.BLOCKED_SOURCE_QUALITY
        ):
            raise ValueError(
                "BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD requires the Phase 2E "
                "BLOCKED_SOURCE_QUALITY outcome"
            )
        if self.disposition is ScoreDisposition.NO_DIRECT_EVIDENCE and (
            self.support.index_bp or self.contradiction.index_bp
        ):
            raise ValueError(
                "NO_DIRECT_EVIDENCE is an evaluated zero-directional posture; a "
                "positive index contradicts it"
            )

        if self.unexamined_component_count > self.support.total_components:
            raise ValueError(
                "more unexamined components than the inventory holds"
            )
        return self

    @property
    def support_index(self) -> Decimal:
        """The support index, 0.00-100.00. An evidence index, not a probability."""
        return self.support.index

    @property
    def contradiction_index(self) -> Decimal:
        return self.contradiction.index

    @property
    def final_support_index(self) -> Decimal | None:
        """``None`` when no primary scalar was issued -- never ``0`` instead."""
        if self.final_support_index_bp is None:
            return None
        return index_display(self.final_support_index_bp)

    @property
    def scalar_withheld(self) -> bool:
        return self.final_support_index_bp is None

    @property
    def has_contradiction(self) -> bool:
        return bool(self.contradiction.index_bp) or bool(
            self.contradiction.contributing_group_ids
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class ClaimScoringStatus(StrEnum):
    """Execution state of one scoring pass.

    The not-ready values are outcomes rather than crashes (section 27), and they
    stay distinct so "Phase 2E never ran" can never be reported as "this
    project's claims scored zero".
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_SCORABLE_CLAIMS = "NO_SCORABLE_CLAIMS"
    NO_SUFFICIENCY_ASSESSMENTS = "NO_SUFFICIENCY_ASSESSMENTS"
    NOT_READY = "NOT_READY"


TERMINAL_SCORING_STATUSES: frozenset[ClaimScoringStatus] = frozenset(
    {
        ClaimScoringStatus.COMPLETED,
        ClaimScoringStatus.FAILED,
        ClaimScoringStatus.NO_SCORABLE_CLAIMS,
        ClaimScoringStatus.NO_SUFFICIENCY_ASSESSMENTS,
        ClaimScoringStatus.NOT_READY,
    }
)


NOT_READY_SCORING_STATUSES: frozenset[ClaimScoringStatus] = frozenset(
    {
        ClaimScoringStatus.NOT_READY,
        ClaimScoringStatus.NO_SCORABLE_CLAIMS,
        ClaimScoringStatus.NO_SUFFICIENCY_ASSESSMENTS,
    }
)
"""Statuses where the pass stopped before any scoring happened."""


class ScoringIssueCode(StrEnum):
    NO_CLAIMS = "NO_CLAIMS"
    SUFFICIENCY_NOT_READY = "SUFFICIENCY_NOT_READY"
    NO_SUFFICIENCY_ASSESSMENTS = "NO_SUFFICIENCY_ASSESSMENTS"
    INCOMPLETE_SUFFICIENCY_INPUT = "INCOMPLETE_SUFFICIENCY_INPUT"
    CROSS_RUN_ASSESSMENT_EXCLUDED = "CROSS_RUN_ASSESSMENT_EXCLUDED"
    INCOMPLETE_COMPONENT_INVENTORY = "INCOMPLETE_COMPONENT_INVENTORY"


class ScoringIssue(MawhibaModel):
    code: ScoringIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1)
    claim_id: str | None = None


class ScoringCoverage(MawhibaModel):
    """Operational counters for the pass.

    ``scalars_issued`` and ``scalars_withheld`` are both reported: their split
    is the honesty of the phase, and a report that showed only the issued ones
    would describe a suspiciously decisive system.
    """

    claims_total: int = Field(default=0, ge=0)
    assessments_total: int = Field(default=0, ge=0)
    scorecards_total: int = Field(default=0, ge=0)
    scalars_issued: int = Field(default=0, ge=0)
    scalars_withheld: int = Field(default=0, ge=0)
    components_scored: int = Field(default=0, ge=0)
    unexamined_components_total: int = Field(default=0, ge=0)
    contested_total: int = Field(default=0, ge=0)
    blocked_source_quality_total: int = Field(default=0, ge=0)
    incomplete_input_total: int = Field(default=0, ge=0)
    disposition_counts: dict[str, int] = Field(default_factory=dict)
    reliability_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_agree(self) -> ScoringCoverage:
        if self.scalars_issued + self.scalars_withheld != self.scorecards_total:
            raise ValueError(
                "every scorecard either issued a primary scalar or withheld one"
            )
        return self


class ClaimEvidenceScoringRun(MawhibaModel):
    """Everything one claim-evidence scoring pass produced.

    Lives on the ``ResearchRun`` (section 4), never in ``ProjectState``, for the
    ownership reason Phases 2B-2E established: this is research-evaluation
    truth, an auditable analytical artifact over Phase 2E, not canonical project
    truth. In particular it is **not** ``ProjectState.scores`` and not a
    ``ScoreRecord``: those are project-version rubric scoring, and mapping an
    evidence index onto a competition axis is a later explicit phase
    (section 28, ADR-017).

    **Fully deterministic, by design** (section 19). There is no model provider,
    no prompt version and no classifier version here, because a model-generated
    score is forbidden: every number follows from Phase 2E's structured output
    under a published point allocation, and an LLM would add a trust boundary
    with nothing to decide behind it.
    """

    scoring_run_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    sufficiency_run_id: UUID | None = None
    status: ClaimScoringStatus = ClaimScoringStatus.NOT_STARTED

    schema_version: str = CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION
    policy_version: str = CLAIM_EVIDENCE_SCORING_POLICY_VERSION
    arithmetic_version: str = SCORE_ARITHMETIC_VERSION
    reliability_profile_version: str = SCORE_RELIABILITY_PROFILE_VERSION
    dataset_version: str | None = None

    scorecards: list[ClaimEvidenceScoreCard] = Field(default_factory=list)
    coverage: ScoringCoverage = Field(default_factory=ScoringCoverage)
    errors: list[ScoringIssue] = Field(default_factory=list)

    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ClaimEvidenceScoringRun:
        claim_ids = [card.claim_id for card in self.scorecards]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError(
                "a claim cannot carry two scorecards in one run; a rerun must not "
                "duplicate them (section 25)"
            )
        ids = [card.scorecard_id for card in self.scorecards]
        if len(set(ids)) != len(ids):
            raise ValueError("scorecard ids must be unique")
        for card in self.scorecards:
            if card.research_run_id != self.research_run_id:
                raise ValueError(
                    "a scorecard belongs to a different research run; cross-run "
                    "contamination is refused (section 24)"
                )
            if card.scoring_run_id != self.scoring_run_id:
                raise ValueError("a scorecard belongs to a different scoring run")
            if (
                self.sufficiency_run_id is not None
                and card.sufficiency_run_id != self.sufficiency_run_id
            ):
                raise ValueError(
                    "a scorecard was scored from a different sufficiency run"
                )
            expected = scorecard_id_for(self.scoring_run_id, card.claim_id)
            if card.scorecard_id != expected:
                raise ValueError(
                    "scorecard_id must be derived from the scoring run and the "
                    "claim, not minted; a stable id is what makes a rerun "
                    "checkable (section 25)"
                )
            if card.policy_version != self.policy_version:
                raise ValueError(
                    "a scorecard was produced under a different scoring policy "
                    "version than the run declares"
                )
        if self.status in TERMINAL_SCORING_STATUSES and self.completed_at is None:
            raise ValueError("a terminal scoring run must record completed_at")
        if self.status not in TERMINAL_SCORING_STATUSES and self.completed_at is not None:
            raise ValueError("a non-terminal scoring run cannot be completed")
        if self.status in NOT_READY_SCORING_STATUSES and self.scorecards:
            raise ValueError(
                f"status {self.status.value} stopped before scoring; such a run "
                "cannot hold scorecards"
            )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_SCORING_STATUSES

    @property
    def scorecard_count(self) -> int:
        return len(self.scorecards)

    def scorecard_for(self, claim_id: str) -> ClaimEvidenceScoreCard | None:
        return next((c for c in self.scorecards if c.claim_id == claim_id), None)



__all__ = [
    "ADEQUATE_DIRECTIONAL_STATES",
    "CLAIM_EVIDENCE_SCORE_SCHEMA_VERSION",
    "CLAIM_EVIDENCE_SCORING_POLICY_VERSION",
    "CORROBORATION_DIMENSION_MAX_BP",
    "COVERAGE_DIMENSION_MAX_BP",
    "DIRECTNESS_DIMENSION_MAX_BP",
    "INDEX_MAX_BP",
    "MAX_SCORECARD_COMPONENTS",
    "NOT_READY_SCORING_STATUSES",
    "SCALAR_WITHHELD_DISPOSITIONS",
    "SCORE_ARITHMETIC_VERSION",
    "SCORE_RELIABILITY_PROFILE_VERSION",
    "TERMINAL_SCORING_STATUSES",
    "ClaimEvidenceScoreCard",
    "ClaimEvidenceScoringRun",
    "ClaimScoringStatus",
    "ComponentScoreTrace",
    "DirectionalCoverageState",
    "DirectionalScore",
    "ReliabilityPosture",
    "ScoreDimensions",
    "ScoreDirection",
    "ScoreDisposition",
    "ScoreReasonCode",
    "ScoreReliabilityProfile",
    "ScoringCoverage",
    "ScoringIssue",
    "ScoringIssueCode",
    "index_display",
    "scorecard_id_for",
]
