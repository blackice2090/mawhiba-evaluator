"""Methodology review contracts -- Phase 3A (ADR-022).

Phase 3A answers one question: is the student's *documented* methodology
designed in a defensible way to test the project's claims and its Phase 2J
gap? It reviews design only. It never decides whether an experiment was run,
whether a result is true, whether a result supports a claim, or anything about
novelty, scoring, readiness, Red Team or jury conclusions.

The record chain, one type per link:

    StudentMethodologyExcerpt     an exact, code-sliced span of the verbatim submission
    RequirementApplicability      a catalog requirement, resolved for this project
    RequirementDocumentation      what the bound input documents, and its design adequacy
    BaselineComparatorRecord      baseline documented != baseline relevant != fair execution
    MetricAlignment               target -> measurable outcome -> metric, never invented
    MaterialConditionCoverage     a Phase 2J condition, addressed in design or not
    MethodologyCoverageLink       target <-> methodology relation, model-assisted and bounded
    MethodologyIssue              a typed issue, severity fixed by its class
    MethodologyTrackAssessment    one track's posture, decided in code
    MethodologyReviewRun          the run, bound to its upstream and to the submission

Distinctions this module refuses to collapse, each enforced structurally:

* **documented vs executed.** Every excerpt carries ``execution_verified=False``
  as a literal; a student sentence in the past tense is
  ``DESCRIBED_AS_EXECUTED``, never execution evidence (Phase 3B owns that).
* **not documented vs not done.** ``NOT_DOCUMENTED_IN_BOUND_INPUT`` qualifies the
  bound input, never the student; ``NOT_DOCUMENTED_MEANING`` says so on every run.
* **documentation vs adequacy.** Two separate fields on separate enums.
* **methodology vs results.** No type here has a result, outcome, accuracy or
  score field, and posture synthesis takes no result argument.
* **research vs engineering.** A HYBRID project carries two track assessments
  and no combined posture field: there is nothing to average into.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.common import MawhibaModel, ProjectType, Severity, TechnicalDomain, UtcDatetime
from src.schemas.discovery import CONTENT_HASH_PATTERN, MAX_SAFE_SUMMARY_LENGTH
from src.schemas.gap_assessment import GapFacet, GapHypothesis
from src.schemas.novelty_differentiation import OccurrenceResolution

METHODOLOGY_CONTRACT_VERSION = "METHODOLOGY-REVIEW-CONTRACT-V1"
METHODOLOGY_CATALOG_VERSION = "METHODOLOGY-REQUIREMENT-CATALOG-V1"
METHODOLOGY_ANCHOR_VERIFIER_VERSION = "METHODOLOGY-EXCERPT-ANCHOR-VERIFIER-V1"
METHODOLOGY_SYNTHESIS_POLICY_VERSION = "METHODOLOGY-POSTURE-SYNTHESIS-POLICY-V1"

METHODOLOGY_ID_NAMESPACE = UUID("8b4f1d27-3c6a-5e91-a0d8-6f2b9c3e7a14")

MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"

NOT_DOCUMENTED_MEANING = "NOT_DOCUMENTED_IN_BOUND_INPUT_IS_NOT_EVIDENCE_OF_NON_PERFORMANCE"
"""Carried by every run: absence from the bound input says nothing about what the student did."""


def methodology_id(*parts: object) -> UUID:
    """A deterministic run-bound id. Same parts, same id, every rerun."""
    return uuid5(METHODOLOGY_ID_NAMESPACE, "|".join(str(p) for p in parts))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tracks, overlays and the requirement catalog (sections 7-12)
# ---------------------------------------------------------------------------


class MethodologyTrack(StrEnum):
    SCIENTIFIC_RESEARCH = "SCIENTIFIC_RESEARCH"
    ENGINEERING = "ENGINEERING"


class RequirementOverlay(StrEnum):
    CORE = "CORE"
    AI_ML = "AI_ML"
    SOFTWARE_SYSTEMS = "SOFTWARE_SYSTEMS"


class Applicability(StrEnum):
    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    OPTIONAL = "OPTIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ApplicabilityBasis(StrEnum):
    CATALOG_DEFAULT = "CATALOG_DEFAULT"
    TRACK_NOT_ACTIVE = "TRACK_NOT_ACTIVE"
    OVERLAY_NOT_ACTIVE = "OVERLAY_NOT_ACTIVE"
    DETERMINISTIC_TRIGGER = "DETERMINISTIC_TRIGGER"
    PHASE_2J_VALIDATION_REQUIREMENT = "PHASE_2J_VALIDATION_REQUIREMENT"
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    CONDITION_UNRESOLVED = "CONDITION_UNRESOLVED"
    OVERLAY_OWNERSHIP_UNRESOLVED = "OVERLAY_OWNERSHIP_UNRESOLVED"


class ApplicabilityTrigger(StrEnum):
    """The closed set of facts that can turn a CONDITIONAL requirement on."""

    CONFIRMATORY_DESIGN = "CONFIRMATORY_DESIGN"
    COMPARATIVE_OR_CAUSAL_CLAIM = "COMPARATIVE_OR_CAUSAL_CLAIM"
    ASSIGNED_INTERVENTION = "ASSIGNED_INTERVENTION"
    SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT = "SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT"
    HUMAN_PARTICIPANTS = "HUMAN_PARTICIPANTS"
    STATISTICAL_INFERENCE = "STATISTICAL_INFERENCE"
    SAMPLED_POPULATION = "SAMPLED_POPULATION"
    PHASE_2J_BASELINE_REQUIRED = "PHASE_2J_BASELINE_REQUIRED"
    PHASE_2J_MATERIAL_CONDITION = "PHASE_2J_MATERIAL_CONDITION"
    GROUPED_OR_REPEATED_SUBJECT_DATA = "GROUPED_OR_REPEATED_SUBJECT_DATA"
    TIME_ORDERED_DATA = "TIME_ORDERED_DATA"
    IMBALANCED_LABELS = "IMBALANCED_LABELS"
    MODEL_TUNING_PERFORMED = "MODEL_TUNING_PERFORMED"
    GENERALIZATION_CLAIMED = "GENERALIZATION_CLAIMED"
    SECURITY_CLAIMED = "SECURITY_CLAIMED"
    PRIVACY_CLAIMED = "PRIVACY_CLAIMED"
    PERFORMANCE_CLAIMED = "PERFORMANCE_CLAIMED"
    SCALABILITY_CLAIMED = "SCALABILITY_CLAIMED"
    RELIABILITY_CLAIMED = "RELIABILITY_CLAIMED"
    SAFETY_RELEVANT = "SAFETY_RELEVANT"
    USABILITY_CLAIMED = "USABILITY_CLAIMED"
    PERSONAL_DATA_PROCESSED = "PERSONAL_DATA_PROCESSED"


class RequirementKind(StrEnum):
    # -- scientific research track (section 9) ------------------------------
    RESEARCH_QUESTION = "RESEARCH_QUESTION"
    HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN = "HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN"
    INDEPENDENT_VARIABLE = "INDEPENDENT_VARIABLE"
    DEPENDENT_VARIABLE = "DEPENDENT_VARIABLE"
    CONTROLLED_VARIABLES = "CONTROLLED_VARIABLES"
    OPERATIONAL_DEFINITIONS = "OPERATIONAL_DEFINITIONS"
    POPULATION_SAMPLING_FRAME = "POPULATION_SAMPLING_FRAME"
    SAMPLE = "SAMPLE"
    SAMPLE_SIZE_RATIONALE = "SAMPLE_SIZE_RATIONALE"
    CONTROL_OR_COMPARISON_GROUP = "CONTROL_OR_COMPARISON_GROUP"
    RANDOMIZATION = "RANDOMIZATION"
    BLINDING = "BLINDING"
    STUDY_DESIGN = "STUDY_DESIGN"
    DATA_COLLECTION_METHOD = "DATA_COLLECTION_METHOD"
    MEASUREMENT_METHOD = "MEASUREMENT_METHOD"
    REPLICATION_PLAN = "REPLICATION_PLAN"
    STATISTICAL_ANALYSIS_PLAN = "STATISTICAL_ANALYSIS_PLAN"
    CONFOUNDER_HANDLING = "CONFOUNDER_HANDLING"
    BIAS_MITIGATION = "BIAS_MITIGATION"
    INTERNAL_VALIDITY_THREATS = "INTERNAL_VALIDITY_THREATS"
    EXTERNAL_VALIDITY_BOUNDARIES = "EXTERNAL_VALIDITY_BOUNDARIES"
    RESEARCH_REPRODUCIBILITY_PLAN = "RESEARCH_REPRODUCIBILITY_PLAN"
    ETHICS_CONSENT = "ETHICS_CONSENT"
    STATED_LIMITATIONS = "STATED_LIMITATIONS"
    # -- engineering track (section 10) -------------------------------------
    DESIGN_OBJECTIVE = "DESIGN_OBJECTIVE"
    REQUIREMENTS = "REQUIREMENTS"
    CONSTRAINTS = "CONSTRAINTS"
    DESIGN_RATIONALE = "DESIGN_RATIONALE"
    SYSTEM_BOUNDARIES = "SYSTEM_BOUNDARIES"
    ARCHITECTURE_SUBSYSTEM_PLAN = "ARCHITECTURE_SUBSYSTEM_PLAN"
    INPUTS_OUTPUTS = "INPUTS_OUTPUTS"
    SENSORS_DATA_INTERFACES = "SENSORS_DATA_INTERFACES"
    ALGORITHM_CONTROL_STRATEGY = "ALGORITHM_CONTROL_STRATEGY"
    BASELINE_OR_ALTERNATIVE_DESIGN = "BASELINE_OR_ALTERNATIVE_DESIGN"
    VERIFICATION_PLAN = "VERIFICATION_PLAN"
    VALIDATION_PLAN = "VALIDATION_PLAN"
    MEASUREMENT_PLAN = "MEASUREMENT_PLAN"
    ACCEPTANCE_CRITERIA = "ACCEPTANCE_CRITERIA"
    FAILURE_MODE_CONSIDERATION = "FAILURE_MODE_CONSIDERATION"
    RELIABILITY_PLAN = "RELIABILITY_PLAN"
    SAFETY_PLAN = "SAFETY_PLAN"
    SECURITY_PRIVACY_VALIDATION = "SECURITY_PRIVACY_VALIDATION"
    PERFORMANCE_BENCHMARK_PLAN = "PERFORMANCE_BENCHMARK_PLAN"
    SCALABILITY_VALIDATION = "SCALABILITY_VALIDATION"
    ITERATION_STRATEGY = "ITERATION_STRATEGY"
    CONFIGURATION_REPRODUCIBILITY_PLAN = "CONFIGURATION_REPRODUCIBILITY_PLAN"
    # -- AI / ML overlay (section 11) ----------------------------------------
    DATA_SOURCE = "DATA_SOURCE"
    DATASET_SCOPE_SIZE = "DATASET_SCOPE_SIZE"
    DATA_QUALITY = "DATA_QUALITY"
    LABELS = "LABELS"
    LABELING_METHOD = "LABELING_METHOD"
    TRAIN_SPLIT = "TRAIN_SPLIT"
    VALIDATION_SPLIT = "VALIDATION_SPLIT"
    TEST_SPLIT = "TEST_SPLIT"
    GROUP_AWARE_SPLIT = "GROUP_AWARE_SPLIT"
    TEMPORAL_SPLIT = "TEMPORAL_SPLIT"
    DATA_LEAKAGE_PREVENTION = "DATA_LEAKAGE_PREVENTION"
    DUPLICATE_LEAKAGE_PREVENTION = "DUPLICATE_LEAKAGE_PREVENTION"
    CLASS_IMBALANCE_HANDLING = "CLASS_IMBALANCE_HANDLING"
    PREPROCESSING = "PREPROCESSING"
    FEATURE_ENGINEERING = "FEATURE_ENGINEERING"
    DATA_AUGMENTATION = "DATA_AUGMENTATION"
    BASELINE_MODEL = "BASELINE_MODEL"
    MODEL_SELECTION_PROCEDURE = "MODEL_SELECTION_PROCEDURE"
    HYPERPARAMETER_TUNING_PROCEDURE = "HYPERPARAMETER_TUNING_PROCEDURE"
    TEST_SET_ISOLATION_FROM_TUNING = "TEST_SET_ISOLATION_FROM_TUNING"
    CROSS_VALIDATION = "CROSS_VALIDATION"
    GENERALIZATION_PLAN = "GENERALIZATION_PLAN"
    EXTERNAL_VALIDATION_PLAN = "EXTERNAL_VALIDATION_PLAN"
    EVALUATION_METRICS = "EVALUATION_METRICS"
    ERROR_ANALYSIS_PLAN = "ERROR_ANALYSIS_PLAN"
    ML_REPRODUCIBILITY_SEEDS_VERSIONS = "ML_REPRODUCIBILITY_SEEDS_VERSIONS"
    # -- software / systems overlay (section 12) ----------------------------
    ARCHITECTURE_RATIONALE = "ARCHITECTURE_RATIONALE"
    BACKEND_DATA_LAYER_METHODOLOGY = "BACKEND_DATA_LAYER_METHODOLOGY"
    SECURITY_VALIDATION_PLAN = "SECURITY_VALIDATION_PLAN"
    PRIVACY_VALIDATION_PLAN = "PRIVACY_VALIDATION_PLAN"
    SYSTEM_PERFORMANCE_BENCHMARK_PLAN = "SYSTEM_PERFORMANCE_BENCHMARK_PLAN"
    SYSTEM_SCALABILITY_PLAN = "SYSTEM_SCALABILITY_PLAN"
    SYSTEM_RELIABILITY_PLAN = "SYSTEM_RELIABILITY_PLAN"
    USABILITY_METHODOLOGY = "USABILITY_METHODOLOGY"
    EXISTING_ALTERNATIVES_COMPARISON = "EXISTING_ALTERNATIVES_COMPARISON"


class CatalogEntry(MawhibaModel):
    """One deterministic catalog row. Policy, constructed at import, never checkpointed."""

    kind: RequirementKind
    overlay: RequirementOverlay
    home_track: MethodologyTrack | None = Field(
        description="The track a CORE requirement belongs to. None for an overlay requirement, "
        "whose owning track comes from the run's ``OverlayAssignment``."
    )
    default: Applicability
    triggers: tuple[ApplicabilityTrigger, ...] = ()
    tests_target: bool = Field(
        default=False,
        description="True when documenting this requirement can describe HOW a target is tested "
        "(design, measurement, metric, validation, comparison). Only such excerpts may carry "
        "strong claim / gap coverage.",
    )

    @model_validator(mode="after")
    def _shape(self) -> CatalogEntry:
        if (self.overlay is RequirementOverlay.CORE) != (self.home_track is not None):
            raise ValueError("a CORE requirement has a home track and an overlay requirement has none")
        if (self.default is Applicability.CONDITIONAL) != bool(self.triggers):
            raise ValueError("exactly the CONDITIONAL requirements declare triggers")
        if self.default is Applicability.NOT_APPLICABLE:
            raise ValueError("a catalog row is never NOT_APPLICABLE by default")
        return self


_R, _E = MethodologyTrack.SCIENTIFIC_RESEARCH, MethodologyTrack.ENGINEERING
_REQ, _COND, _OPT = Applicability.REQUIRED, Applicability.CONDITIONAL, Applicability.OPTIONAL
_T = ApplicabilityTrigger
K = RequirementKind


def _row(kind, overlay, track, default, *triggers, tests=False) -> CatalogEntry:  # noqa: ANN001
    return CatalogEntry(
        kind=kind, overlay=overlay, home_track=track, default=default, triggers=tuple(triggers), tests_target=tests
    )


def _core(kind, track, default, *triggers, tests=False) -> CatalogEntry:  # noqa: ANN001
    return _row(kind, RequirementOverlay.CORE, track, default, *triggers, tests=tests)


def _ai(kind, default, *triggers, tests=False) -> CatalogEntry:  # noqa: ANN001
    return _row(kind, RequirementOverlay.AI_ML, None, default, *triggers, tests=tests)


def _sw(kind, default, *triggers, tests=False) -> CatalogEntry:  # noqa: ANN001
    return _row(kind, RequirementOverlay.SOFTWARE_SYSTEMS, None, default, *triggers, tests=tests)


REQUIREMENT_CATALOG: dict[RequirementKind, CatalogEntry] = {
    e.kind: e
    for e in (
        # Scientific research. A hypothesis, randomization, blinding and a control
        # group are CONDITIONAL: descriptive and exploratory designs are legitimate
        # without them, and the word "experiment" is not a trigger (section 9).
        _core(K.RESEARCH_QUESTION, _R, _REQ),
        _core(K.HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN, _R, _COND, _T.CONFIRMATORY_DESIGN),
        _core(K.INDEPENDENT_VARIABLE, _R, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM, _T.ASSIGNED_INTERVENTION, tests=True),
        _core(K.DEPENDENT_VARIABLE, _R, _REQ, tests=True),
        _core(K.CONTROLLED_VARIABLES, _R, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM, tests=True),
        _core(K.OPERATIONAL_DEFINITIONS, _R, _REQ, tests=True),
        _core(K.POPULATION_SAMPLING_FRAME, _R, _COND, _T.SAMPLED_POPULATION, _T.HUMAN_PARTICIPANTS),
        _core(K.SAMPLE, _R, _REQ),
        _core(K.SAMPLE_SIZE_RATIONALE, _R, _COND, _T.STATISTICAL_INFERENCE, _T.SAMPLED_POPULATION),
        _core(K.CONTROL_OR_COMPARISON_GROUP, _R, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM, _T.PHASE_2J_BASELINE_REQUIRED,
              tests=True),
        _core(K.RANDOMIZATION, _R, _COND, _T.ASSIGNED_INTERVENTION),
        _core(K.BLINDING, _R, _COND, _T.SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT),
        _core(K.STUDY_DESIGN, _R, _REQ, tests=True),
        _core(K.DATA_COLLECTION_METHOD, _R, _REQ, tests=True),
        _core(K.MEASUREMENT_METHOD, _R, _REQ, tests=True),
        _core(K.REPLICATION_PLAN, _R, _OPT),
        _core(K.STATISTICAL_ANALYSIS_PLAN, _R, _COND, _T.STATISTICAL_INFERENCE, _T.COMPARATIVE_OR_CAUSAL_CLAIM,
              tests=True),
        _core(K.CONFOUNDER_HANDLING, _R, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM),
        _core(K.BIAS_MITIGATION, _R, _OPT),
        _core(K.INTERNAL_VALIDITY_THREATS, _R, _OPT),
        _core(K.EXTERNAL_VALIDITY_BOUNDARIES, _R, _COND, _T.GENERALIZATION_CLAIMED, _T.PHASE_2J_MATERIAL_CONDITION),
        _core(K.RESEARCH_REPRODUCIBILITY_PLAN, _R, _OPT),
        _core(K.ETHICS_CONSENT, _R, _COND, _T.HUMAN_PARTICIPANTS, _T.PERSONAL_DATA_PROCESSED),
        _core(K.STATED_LIMITATIONS, _R, _OPT),
        # Engineering. A prototype, app, UI or diagram is never itself a plan.
        _core(K.DESIGN_OBJECTIVE, _E, _REQ),
        _core(K.REQUIREMENTS, _E, _REQ),
        _core(K.CONSTRAINTS, _E, _OPT),
        _core(K.DESIGN_RATIONALE, _E, _OPT),
        _core(K.SYSTEM_BOUNDARIES, _E, _OPT),
        _core(K.ARCHITECTURE_SUBSYSTEM_PLAN, _E, _REQ),
        _core(K.INPUTS_OUTPUTS, _E, _OPT),
        _core(K.SENSORS_DATA_INTERFACES, _E, _OPT),
        _core(K.ALGORITHM_CONTROL_STRATEGY, _E, _OPT),
        _core(K.BASELINE_OR_ALTERNATIVE_DESIGN, _E, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM,
              _T.PHASE_2J_BASELINE_REQUIRED, tests=True),
        _core(K.VERIFICATION_PLAN, _E, _REQ, tests=True),
        _core(K.VALIDATION_PLAN, _E, _REQ, tests=True),
        _core(K.MEASUREMENT_PLAN, _E, _REQ, tests=True),
        _core(K.ACCEPTANCE_CRITERIA, _E, _REQ, tests=True),
        _core(K.FAILURE_MODE_CONSIDERATION, _E, _OPT),
        _core(K.RELIABILITY_PLAN, _E, _COND, _T.RELIABILITY_CLAIMED, _T.SAFETY_RELEVANT, tests=True),
        _core(K.SAFETY_PLAN, _E, _COND, _T.SAFETY_RELEVANT),
        _core(K.SECURITY_PRIVACY_VALIDATION, _E, _COND, _T.SECURITY_CLAIMED, _T.PRIVACY_CLAIMED, tests=True),
        _core(K.PERFORMANCE_BENCHMARK_PLAN, _E, _COND, _T.PERFORMANCE_CLAIMED, tests=True),
        _core(K.SCALABILITY_VALIDATION, _E, _COND, _T.SCALABILITY_CLAIMED, tests=True),
        _core(K.ITERATION_STRATEGY, _E, _OPT),
        _core(K.CONFIGURATION_REPRODUCIBILITY_PLAN, _E, _OPT),
        # AI / ML overlay -- active only when AI/ML is material to the project.
        _ai(K.DATA_SOURCE, _REQ),
        _ai(K.DATASET_SCOPE_SIZE, _REQ),
        _ai(K.DATA_QUALITY, _OPT),
        _ai(K.LABELS, _REQ),
        _ai(K.LABELING_METHOD, _REQ),
        _ai(K.TRAIN_SPLIT, _REQ, tests=True),
        _ai(K.VALIDATION_SPLIT, _COND, _T.MODEL_TUNING_PERFORMED, tests=True),
        _ai(K.TEST_SPLIT, _REQ, tests=True),
        _ai(K.GROUP_AWARE_SPLIT, _COND, _T.GROUPED_OR_REPEATED_SUBJECT_DATA, tests=True),
        _ai(K.TEMPORAL_SPLIT, _COND, _T.TIME_ORDERED_DATA, tests=True),
        _ai(K.DATA_LEAKAGE_PREVENTION, _REQ, tests=True),
        _ai(K.DUPLICATE_LEAKAGE_PREVENTION, _OPT, tests=True),
        _ai(K.CLASS_IMBALANCE_HANDLING, _COND, _T.IMBALANCED_LABELS),
        _ai(K.PREPROCESSING, _OPT),
        _ai(K.FEATURE_ENGINEERING, _OPT),
        _ai(K.DATA_AUGMENTATION, _OPT),
        _ai(K.BASELINE_MODEL, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM, _T.PHASE_2J_BASELINE_REQUIRED, tests=True),
        _ai(K.MODEL_SELECTION_PROCEDURE, _COND, _T.MODEL_TUNING_PERFORMED),
        _ai(K.HYPERPARAMETER_TUNING_PROCEDURE, _COND, _T.MODEL_TUNING_PERFORMED),
        _ai(K.TEST_SET_ISOLATION_FROM_TUNING, _REQ, tests=True),
        _ai(K.CROSS_VALIDATION, _OPT, tests=True),
        _ai(K.GENERALIZATION_PLAN, _COND, _T.GENERALIZATION_CLAIMED, _T.PHASE_2J_MATERIAL_CONDITION, tests=True),
        _ai(K.EXTERNAL_VALIDATION_PLAN, _COND, _T.GENERALIZATION_CLAIMED, tests=True),
        _ai(K.EVALUATION_METRICS, _REQ, tests=True),
        _ai(K.ERROR_ANALYSIS_PLAN, _OPT),
        _ai(K.ML_REPRODUCIBILITY_SEEDS_VERSIONS, _OPT),
        # Software / systems overlay.
        _sw(K.ARCHITECTURE_RATIONALE, _OPT),
        _sw(K.BACKEND_DATA_LAYER_METHODOLOGY, _OPT),
        _sw(K.SECURITY_VALIDATION_PLAN, _COND, _T.SECURITY_CLAIMED, tests=True),
        _sw(K.PRIVACY_VALIDATION_PLAN, _COND, _T.PRIVACY_CLAIMED, _T.PERSONAL_DATA_PROCESSED, tests=True),
        _sw(K.SYSTEM_PERFORMANCE_BENCHMARK_PLAN, _COND, _T.PERFORMANCE_CLAIMED, tests=True),
        _sw(K.SYSTEM_SCALABILITY_PLAN, _COND, _T.SCALABILITY_CLAIMED, tests=True),
        _sw(K.SYSTEM_RELIABILITY_PLAN, _COND, _T.RELIABILITY_CLAIMED, tests=True),
        _sw(K.USABILITY_METHODOLOGY, _COND, _T.USABILITY_CLAIMED, tests=True),
        _sw(K.EXISTING_ALTERNATIVES_COMPARISON, _COND, _T.COMPARATIVE_OR_CAUSAL_CLAIM, tests=True),
    )
}

if set(REQUIREMENT_CATALOG) != set(RequirementKind):  # pragma: no cover - import-time guard
    raise RuntimeError("every RequirementKind has exactly one catalog row")


AI_ML_DOMAINS: frozenset[TechnicalDomain] = frozenset(
    {
        TechnicalDomain.ARTIFICIAL_INTELLIGENCE,
        TechnicalDomain.MACHINE_LEARNING,
        TechnicalDomain.DEEP_LEARNING,
        TechnicalDomain.COMPUTER_VISION,
        TechnicalDomain.NATURAL_LANGUAGE_PROCESSING,
    }
)
SOFTWARE_SYSTEMS_DOMAINS: frozenset[TechnicalDomain] = frozenset(
    {
        TechnicalDomain.SOFTWARE_ENGINEERING,
        TechnicalDomain.CYBERSECURITY,
        TechnicalDomain.CLOUD_COMPUTING,
        TechnicalDomain.NETWORKS,
        TechnicalDomain.HUMAN_COMPUTER_INTERACTION,
    }
)


def tracks_for(project_type: ProjectType) -> tuple[MethodologyTrack, ...]:
    """Inherited project type -> tracks. UNKNOWN yields none (INSUFFICIENT_INPUT)."""
    return {
        ProjectType.SCIENTIFIC_RESEARCH: (_R,),
        ProjectType.ENGINEERING_PROJECT: (_E,),
        ProjectType.HYBRID: (_R, _E),
    }.get(project_type, ())


def resolve_applicability(
    kind: RequirementKind,
    tracks: tuple[MethodologyTrack, ...],
    overlay_owners: dict[RequirementOverlay, MethodologyTrack | None],
    triggers: frozenset[ApplicabilityTrigger] | None,
) -> tuple[MethodologyTrack | None, Applicability, ApplicabilityBasis]:
    """Deterministic applicability.

    ``overlay_owners`` holds only overlays whose ``OverlayAssignment`` is
    MATERIAL_TO_TARGET or MATERIALITY_UNRESOLVED, mapped to the owning track, or
    to None while materiality or HYBRID ownership is unresolved. An unresolved
    overlay requirement stays CONDITIONAL with no track. It is counted in no
    track and blocks a well-specified posture in every track (see
    ``MethodologyReviewRun``). ``triggers=None`` leaves a CONDITIONAL requirement
    unresolved: it is never REQUIRED and never NOT_APPLICABLE by default."""
    entry = REQUIREMENT_CATALOG[kind]
    if entry.overlay is RequirementOverlay.CORE:
        track = entry.home_track
    elif entry.overlay not in overlay_owners:
        return None, Applicability.NOT_APPLICABLE, ApplicabilityBasis.OVERLAY_NOT_ACTIVE
    else:
        track = overlay_owners[entry.overlay]
        if track is None:
            return None, Applicability.CONDITIONAL, ApplicabilityBasis.OVERLAY_OWNERSHIP_UNRESOLVED
    if track is None or track not in tracks:
        return None, Applicability.NOT_APPLICABLE, ApplicabilityBasis.TRACK_NOT_ACTIVE
    if entry.default is not Applicability.CONDITIONAL:
        return track, entry.default, ApplicabilityBasis.CATALOG_DEFAULT
    if triggers is None:
        return track, Applicability.CONDITIONAL, ApplicabilityBasis.CONDITION_UNRESOLVED
    if set(entry.triggers) & triggers:
        return track, Applicability.REQUIRED, ApplicabilityBasis.DETERMINISTIC_TRIGGER
    return track, Applicability.NOT_APPLICABLE, ApplicabilityBasis.DETERMINISTIC_TRIGGER


# ---------------------------------------------------------------------------
# Source binding (section 13) and the execution-claim boundary (section 27)
# ---------------------------------------------------------------------------


class StatementMode(StrEnum):
    PLANNED = "PLANNED"
    DESCRIBED_AS_EXECUTED = "DESCRIBED_AS_EXECUTED"
    MODE_NOT_DETERMINED = "MODE_NOT_DETERMINED"


class StudentMethodologyExcerpt(MawhibaModel):
    """An exact span of the verbatim submission, sliced by code, never a paraphrase.

    ``execution_verified`` is a literal ``False``: a student describing what they
    did is a student description, and Phase 3B alone owns execution evidence.
    """

    excerpt_id: UUID
    methodology_run_id: UUID
    submission_artifact_id: UUID
    submission_content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    excerpt: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    occurrence_index: int = Field(ge=1)
    occurrence_resolution: OccurrenceResolution
    statement_mode: StatementMode = StatementMode.MODE_NOT_DETERMINED
    execution_verified: Literal[False] = False
    language: str | None = None
    verifier_version: str = METHODOLOGY_ANCHOR_VERIFIER_VERSION

    @model_validator(mode="after")
    def _exact(self) -> StudentMethodologyExcerpt:
        if self.end - self.start != len(self.excerpt):
            raise ValueError("an excerpt's offsets must span exactly its text")
        if self.occurrence_index > self.occurrence_count:
            raise ValueError("occurrence_index exceeds occurrence_count")
        if self.occurrence_count > 1 and self.occurrence_resolution is OccurrenceResolution.UNIQUE_IN_TEXT:
            raise ValueError("a repeated excerpt is never UNIQUE_IN_TEXT (no first-occurrence guessing)")
        if self.occurrence_count == 1 and self.occurrence_index != 1:
            raise ValueError("a unique excerpt is occurrence 1")
        return self

    def matches(self, submission_text: str) -> bool:
        """True only if this excerpt is literally the submission slice it claims to be."""
        return (
            text_hash(submission_text) == self.submission_content_hash
            and submission_text[self.start : self.end] == self.excerpt
        )


# ---------------------------------------------------------------------------
# Documentation and adequacy -- separate on purpose (sections 14, 15)
# ---------------------------------------------------------------------------


class DocumentationStatus(StrEnum):
    EXPLICITLY_DOCUMENTED = "EXPLICITLY_DOCUMENTED"
    PARTIALLY_DOCUMENTED = "PARTIALLY_DOCUMENTED"
    CONFLICTING_DOCUMENTATION = "CONFLICTING_DOCUMENTATION"
    NOT_DOCUMENTED_IN_BOUND_INPUT = "NOT_DOCUMENTED_IN_BOUND_INPUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_SOURCE_COVERAGE = "INSUFFICIENT_SOURCE_COVERAGE"


class DesignAdequacy(StrEnum):
    ADEQUATELY_SPECIFIED_FOR_REVIEW = "ADEQUATELY_SPECIFIED_FOR_REVIEW"
    PARTIALLY_SPECIFIED = "PARTIALLY_SPECIFIED"
    DESIGN_RISK_IDENTIFIED = "DESIGN_RISK_IDENTIFIED"
    CONFLICTING_DESIGN = "CONFLICTING_DESIGN"
    INSUFFICIENT_EVIDENCE_TO_ASSESS = "INSUFFICIENT_EVIDENCE_TO_ASSESS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_DOC_WITH_EXCERPTS = {DocumentationStatus.EXPLICITLY_DOCUMENTED, DocumentationStatus.PARTIALLY_DOCUMENTED}
_DOC_WITHOUT_EXCERPTS = {
    DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT,
    DocumentationStatus.NOT_APPLICABLE,
    DocumentationStatus.INSUFFICIENT_SOURCE_COVERAGE,
}
_ALLOWED_ADEQUACY: dict[DocumentationStatus, frozenset[DesignAdequacy]] = {
    DocumentationStatus.EXPLICITLY_DOCUMENTED: frozenset(
        {DesignAdequacy.ADEQUATELY_SPECIFIED_FOR_REVIEW, DesignAdequacy.PARTIALLY_SPECIFIED,
         DesignAdequacy.DESIGN_RISK_IDENTIFIED}
    ),
    DocumentationStatus.PARTIALLY_DOCUMENTED: frozenset(
        {DesignAdequacy.PARTIALLY_SPECIFIED, DesignAdequacy.DESIGN_RISK_IDENTIFIED}
    ),
    DocumentationStatus.CONFLICTING_DOCUMENTATION: frozenset({DesignAdequacy.CONFLICTING_DESIGN}),
    DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT: frozenset(
        {DesignAdequacy.INSUFFICIENT_EVIDENCE_TO_ASSESS, DesignAdequacy.DESIGN_RISK_IDENTIFIED}
    ),
    DocumentationStatus.INSUFFICIENT_SOURCE_COVERAGE: frozenset({DesignAdequacy.INSUFFICIENT_EVIDENCE_TO_ASSESS}),
    DocumentationStatus.NOT_APPLICABLE: frozenset({DesignAdequacy.NOT_APPLICABLE}),
}

_BARE_QUANTITY = re.compile(r"^[\s\W\d_]*(?:n|N)?[\s\W\d_]*$")
"""An excerpt with no word other than an optional ``n``: "N = 500", "500", "(n=30)"."""

RATIONALE_KINDS: frozenset[RequirementKind] = frozenset(
    {K.SAMPLE_SIZE_RATIONALE, K.DESIGN_RATIONALE, K.ARCHITECTURE_RATIONALE}
)


class RequirementApplicability(MawhibaModel):
    """A catalog requirement resolved for this project. The kind is an enum member,
    so a model can never introduce a requirement the catalog does not define."""

    methodology_run_id: UUID
    kind: RequirementKind
    track: MethodologyTrack | None
    applicability: Applicability
    basis: ApplicabilityBasis
    triggers: list[ApplicabilityTrigger] = Field(default_factory=list)
    judgment_excerpt_ids: list[UUID] = Field(
        default_factory=list,
        description="Bound context for a MODEL_ASSISTED_BOUNDED_JUDGMENT resolution.",
    )

    @model_validator(mode="after")
    def _bounded(self) -> RequirementApplicability:
        entry = REQUIREMENT_CATALOG[self.kind]
        inactive = self.basis in (ApplicabilityBasis.TRACK_NOT_ACTIVE, ApplicabilityBasis.OVERLAY_NOT_ACTIVE)
        unowned = self.basis is ApplicabilityBasis.OVERLAY_OWNERSHIP_UNRESOLVED
        if (self.track is None) != (inactive or unowned):
            raise ValueError("only an inactive or unowned overlay, or an inactive track, leaves a requirement trackless")
        if inactive and self.applicability is not Applicability.NOT_APPLICABLE:
            raise ValueError("an inactive track or overlay makes a requirement NOT_APPLICABLE")
        if unowned and (entry.overlay is RequirementOverlay.CORE or self.applicability is not Applicability.CONDITIONAL):
            raise ValueError("an unowned overlay requirement stays CONDITIONAL")
        if entry.home_track is not None and self.track is not None and self.track is not entry.home_track:
            raise ValueError("a CORE requirement keeps its catalog track")
        if self.basis is ApplicabilityBasis.CATALOG_DEFAULT and self.applicability is not entry.default:
            raise ValueError("CATALOG_DEFAULT must equal the catalog default")
        resolving = (
            ApplicabilityBasis.DETERMINISTIC_TRIGGER,
            ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,
            ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT,
        )
        if self.basis in resolving:
            if entry.default is not Applicability.CONDITIONAL:
                raise ValueError("only a CONDITIONAL catalog requirement may be resolved; REQUIRED is never lowered")
            if self.applicability not in (Applicability.REQUIRED, Applicability.NOT_APPLICABLE):
                raise ValueError("a resolution ends REQUIRED or NOT_APPLICABLE")
            if not set(self.triggers) <= set(entry.triggers):
                raise ValueError("a trigger outside the requirement's catalog triggers")
            if (self.applicability is Applicability.REQUIRED) != bool(self.triggers):
                raise ValueError("REQUIRED by resolution names the trigger(s) that fired, and only then")
        if self.basis is ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT and not self.judgment_excerpt_ids:
            raise ValueError("a model-assisted applicability judgment must bind its source context")
        if self.basis is ApplicabilityBasis.CONDITION_UNRESOLVED and self.applicability is not Applicability.CONDITIONAL:
            raise ValueError("an unresolved condition stays CONDITIONAL")
        return self


class RequirementDocumentation(MawhibaModel):
    methodology_run_id: UUID
    kind: RequirementKind
    track: MethodologyTrack
    documentation: DocumentationStatus
    adequacy: DesignAdequacy
    excerpt_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _separate(self) -> RequirementDocumentation:
        n = len(set(self.excerpt_ids))
        if n != len(self.excerpt_ids):
            raise ValueError("an excerpt is cited once")
        if self.documentation in _DOC_WITH_EXCERPTS and n < 1:
            raise ValueError("documented requires a bound excerpt")
        if self.documentation is DocumentationStatus.CONFLICTING_DOCUMENTATION and n < 2:
            raise ValueError("conflicting documentation cites both sides")
        if self.documentation in _DOC_WITHOUT_EXCERPTS and n:
            raise ValueError(f"{self.documentation.value} cites no excerpt")
        if self.adequacy not in _ALLOWED_ADEQUACY[self.documentation]:
            raise ValueError(f"{self.adequacy.value} is not reachable from {self.documentation.value}")
        return self


# ---------------------------------------------------------------------------
# Baseline, metric, condition and target coverage (sections 16-22)
# ---------------------------------------------------------------------------


class BaselineRelevance(StrEnum):
    RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT = "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"
    RELEVANCE_UNRESOLVED = "RELEVANCE_UNRESOLVED"
    NOT_RELEVANT_TO_TARGET = "NOT_RELEVANT_TO_TARGET"
    NO_BASELINE_DOCUMENTED = "NO_BASELINE_DOCUMENTED"


class BaselineRelevanceContext(StrEnum):
    """The permitted context a relevance judgment may rest on, beyond the baseline's
    own identity. "The baseline's name" is deliberately not a member."""

    TARGET_CLAIM_TEXT = "TARGET_CLAIM_TEXT"
    PHASE_2J_VALIDATION_BASELINE = "PHASE_2J_VALIDATION_BASELINE"
    PHASE_2J_EXISTING_CAPABILITY = "PHASE_2J_EXISTING_CAPABILITY"
    STUDENT_RATIONALE_EXCERPT = "STUDENT_RATIONALE_EXCERPT"


class BaselineComparatorRecord(MawhibaModel):
    """Four layers, never collapsed:

        baseline documented              baseline_excerpt_ids (exact student source)
        baseline relevant to the target  relevance + relevance_context (bounded judgment)
        student explains the choice      rationale_excerpt_ids (optional, never fabricated)
        comparison fairly executed       comparison_fairness_assessed = False (Phase 3B)

    A rationale is not a prerequisite for relevance. One exact excerpt may carry
    both the baseline and its rationale, so the two id lists may overlap. The
    closest Phase 2G/2H/2I candidate is never required as the baseline, and no
    field here references a prior-art candidate.
    """

    record_id: UUID
    methodology_run_id: UUID
    target_claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    gap_validation_requirement_id: UUID | None = Field(
        default=None, description="The Phase 2J requirement whose baseline this record plans to cover."
    )
    baseline_excerpt_ids: list[UUID] = Field(default_factory=list)
    relevance: BaselineRelevance
    relevance_context: list[BaselineRelevanceContext] = Field(default_factory=list)
    rationale_excerpt_ids: list[UUID] = Field(default_factory=list)
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT
    comparison_fairness_assessed: Literal[False] = False

    @model_validator(mode="after")
    def _layers(self) -> BaselineComparatorRecord:
        named = bool(self.baseline_excerpt_ids)
        if (self.relevance is BaselineRelevance.NO_BASELINE_DOCUMENTED) == named:
            raise ValueError("NO_BASELINE_DOCUMENTED exactly when no baseline excerpt is bound")
        if not named and (self.relevance_context or self.rationale_excerpt_ids):
            raise ValueError("no relevance or rationale without a documented baseline")
        if self.relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT and not self.relevance_context:
            raise ValueError("relevance rests on bound context, never on the baseline's name alone")
        has_rationale = BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT in self.relevance_context
        if has_rationale != bool(self.rationale_excerpt_ids):
            raise ValueError("a student rationale is cited exactly when its excerpt is bound (never fabricated)")
        if (BaselineRelevanceContext.PHASE_2J_VALIDATION_BASELINE in self.relevance_context) and (
            self.gap_validation_requirement_id is None
        ):
            raise ValueError("Phase 2J baseline context names its validation requirement")
        return self

    @property
    def rationale_documented(self) -> bool:
        return bool(self.rationale_excerpt_ids)


class MetricAlignmentStatus(StrEnum):
    ALIGNED_WITHIN_BOUND_INPUT = "ALIGNED_WITHIN_BOUND_INPUT"
    METRIC_TARGET_MISMATCH = "METRIC_TARGET_MISMATCH"
    METRIC_NOT_DEFINED = "METRIC_NOT_DEFINED"
    TARGET_NOT_MEASURABLE_AS_STATED = "TARGET_NOT_MEASURABLE_AS_STATED"


class MetricSource(StrEnum):
    STUDENT_EXCERPT = "STUDENT_EXCERPT"
    PHASE_2J_VALIDATION_ANCHOR = "PHASE_2J_VALIDATION_ANCHOR"


class MetricAlignment(MawhibaModel):
    """target claim -> measurable outcome -> metric. Each link is an exact upstream
    span; there is no free-text metric field, so a vague claim cannot be given an
    invented one."""

    record_id: UUID
    methodology_run_id: UUID
    target_claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    outcome_excerpt_id: UUID | None = None
    metric_source: MetricSource | None = None
    metric_excerpt_id: UUID | None = None
    gap_validation_requirement_id: UUID | None = None
    status: MetricAlignmentStatus
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _no_invention(self) -> MetricAlignment:
        # A student metric may name the Phase 2J requirement it plans to cover;
        # a Phase 2J metric always does.
        if self.metric_source is MetricSource.STUDENT_EXCERPT and self.metric_excerpt_id is None:
            raise ValueError("a student metric is a bound student excerpt")
        if self.metric_source is MetricSource.PHASE_2J_VALIDATION_ANCHOR and (
            self.gap_validation_requirement_id is None or self.metric_excerpt_id is not None
        ):
            raise ValueError("a Phase 2J metric is a bound validation requirement")
        if self.metric_source is None and self.metric_excerpt_id:
            raise ValueError("a metric reference needs its source")
        has_metric = self.metric_source is not None
        if self.status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT and not (
            has_metric and self.outcome_excerpt_id is not None
        ):
            raise ValueError("alignment needs a bound measurable outcome and a bound metric")
        if self.status is MetricAlignmentStatus.METRIC_TARGET_MISMATCH and not has_metric:
            raise ValueError("a mismatch needs a metric to mismatch")
        if self.status is MetricAlignmentStatus.METRIC_NOT_DEFINED and has_metric:
            raise ValueError("METRIC_NOT_DEFINED binds no metric")
        return self


class ConditionCoverageStatus(StrEnum):
    ADDRESSED_IN_DESIGN = "ADDRESSED_IN_DESIGN"
    PARTIALLY_ADDRESSED = "PARTIALLY_ADDRESSED"
    NOT_ADDRESSED_IN_BOUND_INPUT = "NOT_ADDRESSED_IN_BOUND_INPUT"


class MaterialConditionCoverage(MawhibaModel):
    """A Phase 2J material condition, by id. No condition text is stored or
    synthesized here: the condition lives on its Phase 2J record."""

    methodology_run_id: UUID
    gap_hypothesis_id: UUID
    condition_id: UUID
    status: ConditionCoverageStatus
    excerpt_ids: list[UUID] = Field(default_factory=list)
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _bound(self) -> MaterialConditionCoverage:
        if (self.status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT) == bool(self.excerpt_ids):
            raise ValueError("an addressed condition cites its excerpt; an unaddressed one cites none")
        return self


class CoverageTargetKind(StrEnum):
    CLAIM = "CLAIM"
    GAP_HYPOTHESIS = "GAP_HYPOTHESIS"


class CoverageRelation(StrEnum):
    DIRECTLY_TESTS_TARGET = "DIRECTLY_TESTS_TARGET"
    PARTIALLY_TESTS_TARGET = "PARTIALLY_TESTS_TARGET"
    RELEVANT_BUT_NOT_TESTING = "RELEVANT_BUT_NOT_TESTING"
    DOES_NOT_TEST_TARGET = "DOES_NOT_TEST_TARGET"
    INSUFFICIENT_LINKAGE_EVIDENCE = "INSUFFICIENT_LINKAGE_EVIDENCE"


STRONG_COVERAGE = frozenset({CoverageRelation.DIRECTLY_TESTS_TARGET})


class MethodologyCoverageLink(MawhibaModel):
    """One target <-> methodology relation. IDs and hashes are verified; the
    relation's semantics are a bounded model judgment, never "verified"."""

    link_id: UUID
    methodology_run_id: UUID
    target_kind: CoverageTargetKind
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    gap_hypothesis_id: UUID | None = None
    track: MethodologyTrack
    excerpt_ids: list[UUID] = Field(default_factory=list)
    requirement_kinds: list[RequirementKind] = Field(default_factory=list)
    relation: CoverageRelation
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _shape(self) -> MethodologyCoverageLink:
        if (self.target_kind is CoverageTargetKind.GAP_HYPOTHESIS) != (self.gap_hypothesis_id is not None):
            raise ValueError("a gap target names its Phase 2J hypothesis and a claim target does not")
        testing = self.relation in (CoverageRelation.DIRECTLY_TESTS_TARGET, CoverageRelation.PARTIALLY_TESTS_TARGET)
        if testing and not self.excerpt_ids:
            raise ValueError("a testing relation cites the methodology excerpt that tests")
        if self.relation in STRONG_COVERAGE and not any(
            REQUIREMENT_CATALOG[k].tests_target for k in self.requirement_kinds
        ):
            raise ValueError(
                "strong coverage must rest on a design, measurement, metric or validation requirement; "
                "unrelated methodology text cannot carry it"
            )
        return self


# ---------------------------------------------------------------------------
# Issues, posture and deterministic synthesis (sections 23-26, 31)
# ---------------------------------------------------------------------------


class MethodologyIssueCode(StrEnum):
    TARGET_NOT_TESTABLE = "TARGET_NOT_TESTABLE"
    REQUIRED_COMPONENT_NOT_DOCUMENTED = "REQUIRED_COMPONENT_NOT_DOCUMENTED"
    CLAIM_METHOD_MISMATCH = "CLAIM_METHOD_MISMATCH"
    GAP_METHOD_MISMATCH = "GAP_METHOD_MISMATCH"
    BASELINE_NOT_DOCUMENTED = "BASELINE_NOT_DOCUMENTED"
    BASELINE_RELEVANCE_UNRESOLVED = "BASELINE_RELEVANCE_UNRESOLVED"
    METRIC_NOT_DEFINED = "METRIC_NOT_DEFINED"
    METRIC_TARGET_MISMATCH = "METRIC_TARGET_MISMATCH"
    MATERIAL_CONDITION_NOT_COVERED = "MATERIAL_CONDITION_NOT_COVERED"
    SAMPLE_RATIONALE_NOT_DOCUMENTED = "SAMPLE_RATIONALE_NOT_DOCUMENTED"
    CONTROL_STRATEGY_NOT_DOCUMENTED = "CONTROL_STRATEGY_NOT_DOCUMENTED"
    CONFOUNDER_HANDLING_NOT_DOCUMENTED = "CONFOUNDER_HANDLING_NOT_DOCUMENTED"
    DATA_LEAKAGE_RISK = "DATA_LEAKAGE_RISK"
    TEST_SET_ISOLATION_NOT_DOCUMENTED = "TEST_SET_ISOLATION_NOT_DOCUMENTED"
    DUPLICATE_OR_GROUP_LEAKAGE_RISK = "DUPLICATE_OR_GROUP_LEAKAGE_RISK"
    REPRODUCIBILITY_NOT_DOCUMENTED = "REPRODUCIBILITY_NOT_DOCUMENTED"
    CONFLICTING_METHOD_DESCRIPTION = "CONFLICTING_METHOD_DESCRIPTION"


ISSUE_SEVERITY: dict[MethodologyIssueCode, Severity] = {
    MethodologyIssueCode.TARGET_NOT_TESTABLE: Severity.HIGH,
    MethodologyIssueCode.REQUIRED_COMPONENT_NOT_DOCUMENTED: Severity.HIGH,
    MethodologyIssueCode.CLAIM_METHOD_MISMATCH: Severity.HIGH,
    MethodologyIssueCode.GAP_METHOD_MISMATCH: Severity.HIGH,
    MethodologyIssueCode.BASELINE_NOT_DOCUMENTED: Severity.MEDIUM,
    MethodologyIssueCode.BASELINE_RELEVANCE_UNRESOLVED: Severity.MEDIUM,
    MethodologyIssueCode.METRIC_NOT_DEFINED: Severity.HIGH,
    MethodologyIssueCode.METRIC_TARGET_MISMATCH: Severity.HIGH,
    MethodologyIssueCode.MATERIAL_CONDITION_NOT_COVERED: Severity.HIGH,
    MethodologyIssueCode.SAMPLE_RATIONALE_NOT_DOCUMENTED: Severity.MEDIUM,
    MethodologyIssueCode.CONTROL_STRATEGY_NOT_DOCUMENTED: Severity.MEDIUM,
    MethodologyIssueCode.CONFOUNDER_HANDLING_NOT_DOCUMENTED: Severity.MEDIUM,
    MethodologyIssueCode.DATA_LEAKAGE_RISK: Severity.HIGH,
    MethodologyIssueCode.TEST_SET_ISOLATION_NOT_DOCUMENTED: Severity.HIGH,
    MethodologyIssueCode.DUPLICATE_OR_GROUP_LEAKAGE_RISK: Severity.HIGH,
    MethodologyIssueCode.REPRODUCIBILITY_NOT_DOCUMENTED: Severity.LOW,
    MethodologyIssueCode.CONFLICTING_METHOD_DESCRIPTION: Severity.HIGH,
}
"""Severity is a function of the issue class alone, never of model prose."""

if set(ISSUE_SEVERITY) != set(MethodologyIssueCode):  # pragma: no cover - import-time guard
    raise RuntimeError("every issue code has a fixed severity")


class MethodologyIssue(MawhibaModel):
    issue_id: UUID
    methodology_run_id: UUID
    code: MethodologyIssueCode
    severity: Severity
    track: MethodologyTrack
    requirement_kind: RequirementKind | None = None
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID_PATTERN)
    gap_hypothesis_id: UUID | None = None
    condition_id: UUID | None = None

    @model_validator(mode="after")
    def _fixed_severity(self) -> MethodologyIssue:
        if self.severity is not ISSUE_SEVERITY[self.code]:
            raise ValueError("severity is fixed by the issue class")
        return self


class MethodologyPosture(StrEnum):
    METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT = "METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT"
    METHODOLOGY_PARTIALLY_SPECIFIED = "METHODOLOGY_PARTIALLY_SPECIFIED"
    METHODOLOGY_HAS_MAJOR_DESIGN_GAPS = "METHODOLOGY_HAS_MAJOR_DESIGN_GAPS"
    METHODOLOGY_CONFLICTING = "METHODOLOGY_CONFLICTING"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


_MAJOR = frozenset({Severity.CRITICAL, Severity.HIGH})


def derive_track_posture(
    *,
    inputs_bound: bool,
    applicability: list[RequirementApplicability],
    documentation: list[RequirementDocumentation],
    coverage: list[MethodologyCoverageLink],
    conditions: list[MaterialConditionCoverage],
    issues: list[MethodologyIssue],
) -> MethodologyPosture:
    """The single posture rule. It takes no result, outcome or model-proposed posture:
    nothing measured after the design can repair the design (section 26)."""
    if not inputs_bound:
        return MethodologyPosture.INSUFFICIENT_INPUT
    required = {a.kind for a in applicability if a.applicability is Applicability.REQUIRED}
    docs = {d.kind: d for d in documentation}
    req_docs = [docs[k] for k in required if k in docs]
    if required and all(d.documentation is DocumentationStatus.INSUFFICIENT_SOURCE_COVERAGE for d in req_docs) \
            and len(req_docs) == len(required):
        return MethodologyPosture.INSUFFICIENT_INPUT
    if any(i.code is MethodologyIssueCode.CONFLICTING_METHOD_DESCRIPTION for i in issues) or any(
        d.documentation is DocumentationStatus.CONFLICTING_DOCUMENTATION for d in req_docs
    ):
        return MethodologyPosture.METHODOLOGY_CONFLICTING
    if any(i.severity in _MAJOR for i in issues) or any(k not in docs for k in required) or any(
        d.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT for d in req_docs
    ):
        return MethodologyPosture.METHODOLOGY_HAS_MAJOR_DESIGN_GAPS
    well = (
        not issues
        and all(d.adequacy is DesignAdequacy.ADEQUATELY_SPECIFIED_FOR_REVIEW for d in req_docs)
        and not any(a.applicability is Applicability.CONDITIONAL for a in applicability)
        and bool(coverage)
        and all(c.relation in STRONG_COVERAGE for c in coverage)
        and all(c.status is ConditionCoverageStatus.ADDRESSED_IN_DESIGN for c in conditions)
    )
    return (
        MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
        if well
        else MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED
    )


def cap_for_unresolved_overlay(posture: MethodologyPosture, overlay_blocked: bool) -> MethodologyPosture:
    """An overlay whose materiality or HYBRID ownership is unresolved has no owner track, so none of its
    requirements sits in a track's applicability list for ``derive_track_posture`` to see. This is the one
    place that rule is applied: such a track is never better than PARTIALLY_SPECIFIED."""
    if overlay_blocked and posture is MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT:
        return MethodologyPosture.METHODOLOGY_PARTIALLY_SPECIFIED
    return posture


class MethodologyTrackAssessment(MawhibaModel):
    """One track's posture. ``posture`` must equal ``derive_track_posture`` over the
    records it names; ``model_proposed_posture`` is recorded and never trusted."""

    methodology_run_id: UUID
    track: MethodologyTrack
    inputs_bound: bool
    applicability: list[RequirementApplicability] = Field(default_factory=list)
    documentation: list[RequirementDocumentation] = Field(default_factory=list)
    coverage: list[MethodologyCoverageLink] = Field(default_factory=list)
    conditions: list[MaterialConditionCoverage] = Field(default_factory=list)
    issues: list[MethodologyIssue] = Field(default_factory=list)
    model_proposed_posture: MethodologyPosture | None = Field(default=None, description="Recorded, never trusted.")
    overlay_blocked: bool = Field(
        default=False,
        description="True while any overlay's materiality or HYBRID ownership is unresolved. Such an overlay "
        "has no owner track, so none of its requirements sits in a track's applicability list; this flag is how "
        "the unresolved requirement still blocks a well-specified posture in every track.",
    )
    posture: MethodologyPosture
    execution_verified: Literal[False] = False
    confounding_eliminated: Literal[False] = False
    leakage_prevented_in_practice: Literal[False] = False
    policy_version: str = METHODOLOGY_SYNTHESIS_POLICY_VERSION

    @model_validator(mode="after")
    def _derived(self) -> MethodologyTrackAssessment:
        for group in (self.applicability, self.documentation, self.coverage, self.issues):
            if any(r.track is not self.track for r in group):
                raise ValueError("a track assessment holds only its own track's records")
        required = {a.kind for a in self.applicability if a.applicability is not Applicability.NOT_APPLICABLE}
        if not {d.kind for d in self.documentation} <= required:
            raise ValueError("documentation is recorded only for an applicable requirement")
        derived = cap_for_unresolved_overlay(
            derive_track_posture(
                inputs_bound=self.inputs_bound,
                applicability=self.applicability,
                documentation=self.documentation,
                coverage=self.coverage,
                conditions=self.conditions,
                issues=self.issues,
            ),
            self.overlay_blocked,
        )
        if self.posture is not derived:
            raise ValueError(f"posture must be derived in code ({derived.value}), never chosen")
        return self


# ---------------------------------------------------------------------------
# The run (sections 29, 32, 33)
# ---------------------------------------------------------------------------


class MethodologyUpstreamPhase(StrEnum):
    STUDENT_SUBMISSION = "STUDENT_SUBMISSION"
    PROJECT_CLAIMS = "PROJECT_CLAIMS"
    PHASE_2I_NOVELTY_DIFFERENTIATION = "PHASE_2I_NOVELTY_DIFFERENTIATION"
    PHASE_2J_GAP = "PHASE_2J_GAP"


class MethodologyUpstreamBinding(MawhibaModel):
    """A fingerprint taken at bind and re-checked at finalize. A mismatch is an
    upstream mutation and invalidates the run."""

    phase: MethodologyUpstreamPhase
    upstream_id: UUID
    fingerprint: str = Field(pattern=CONTENT_HASH_PATTERN)


class BoundClaim(MawhibaModel):
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)


class BoundGapTarget(MawhibaModel):
    """A Phase 2J hypothesis as Phase 3A sees it: ids only, no re-derived text.

    The dimensions mirror the bound ``GapValidationRequirement`` exactly (see
    ``from_hypothesis``). Its ``metric`` is mandatory in the Phase 2J schema, so
    a requirement always demands a metric plan. ``baseline`` is optional there,
    and so is the baseline plan here. Its ``condition_ids`` are the conditions
    to address. With no requirement, Phase 3A adds no metric, baseline or
    condition prerequisite of its own.
    """

    gap_hypothesis_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    validation_requirement_id: UUID | None = None
    requires_metric: bool = False
    requires_baseline: bool = False
    material_condition_ids: list[UUID] = Field(default_factory=list)
    limitation_facets: list[GapFacet] = Field(
        default_factory=list, description="The Phase 2J facets of the hypothesis's limitations, copied unchanged."
    )

    @model_validator(mode="after")
    def _mirrors_phase_2j(self) -> BoundGapTarget:
        has_requirement = self.validation_requirement_id is not None
        if self.requires_metric != has_requirement:
            raise ValueError("a Phase 2J requirement always carries a metric, and only a requirement does")
        if not has_requirement and (self.requires_baseline or self.material_condition_ids):
            raise ValueError("baseline and condition prerequisites come only from a bound Phase 2J requirement")
        return self

    @classmethod
    def from_hypothesis(cls, hypothesis: GapHypothesis) -> BoundGapTarget:
        req = hypothesis.validation_requirement
        return cls(
            gap_hypothesis_id=hypothesis.hypothesis_id,
            claim_id=hypothesis.claim_id,
            validation_requirement_id=req.requirement_id if req else None,
            requires_metric=req is not None,
            requires_baseline=req is not None and req.baseline is not None,
            material_condition_ids=list(req.condition_ids) if req else [],
            limitation_facets=sorted({lim.facet for lim in hypothesis.limitations}),
        )


class OverlayMateriality(StrEnum):
    MATERIAL_TO_TARGET = "MATERIAL_TO_TARGET"
    IMPLEMENTATION_TOOL_ONLY = "IMPLEMENTATION_TOOL_ONLY"
    MATERIALITY_UNRESOLVED = "MATERIALITY_UNRESOLVED"


class OverlayOwnershipBasis(StrEnum):
    SINGLE_TRACK_PROJECT = "SINGLE_TRACK_PROJECT"
    PHASE_2J_LIMITATION_FACET = "PHASE_2J_LIMITATION_FACET"
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    NOT_MATERIAL = "NOT_MATERIAL"
    UNRESOLVED = "UNRESOLVED"


class OverlayAssignment(MawhibaModel):
    """One canonical assignment per overlay (architecture A).

    Domain, the word "AI" or the presence of a model is only a *signal*
    (``signal_domains``), never materiality and never ownership. Materiality
    rests on bound targets and excerpts. The overlay's requirements are
    instantiated once, in ``owner_track``. Another track in ``served_tracks``
    may cite them for coverage but never counts them.

    Ownership:
    * a single-track project: the overlay is owned by the only track, so an
      engineering-only AI project gets the AI/ML requirements and a
      research-only project with material software gets the software requirements;
    * a HYBRID project: the owner is the track whose target the overlay serves,
      decided by a Phase 2J limitation facet or a bounded judgment, never by a
      blanket preference. Until it is decided, the owner is None, the
      requirements stay CONDITIONAL, and no track may be well specified.
    """

    methodology_run_id: UUID
    overlay: RequirementOverlay
    signal_domains: list[TechnicalDomain] = Field(default_factory=list)
    materiality: OverlayMateriality
    material_claim_ids: list[str] = Field(default_factory=list)
    material_gap_hypothesis_ids: list[UUID] = Field(default_factory=list)
    excerpt_ids: list[UUID] = Field(default_factory=list)
    owner_track: MethodologyTrack | None = None
    ownership_basis: OverlayOwnershipBasis
    served_tracks: list[MethodologyTrack] = Field(default_factory=list)

    @model_validator(mode="after")
    def _owned_once(self) -> OverlayAssignment:
        if self.overlay is RequirementOverlay.CORE:
            raise ValueError("CORE is not an overlay")
        if len(set(self.served_tracks)) != len(self.served_tracks):
            raise ValueError("a served track is listed once")
        material = self.materiality is OverlayMateriality.MATERIAL_TO_TARGET
        if material and not (
            (self.material_claim_ids or self.material_gap_hypothesis_ids) and self.excerpt_ids
        ):
            raise ValueError("materiality rests on bound targets and excerpts, never on domain alone")
        if self.materiality is OverlayMateriality.IMPLEMENTATION_TOOL_ONLY and (
            self.owner_track is not None or self.ownership_basis is not OverlayOwnershipBasis.NOT_MATERIAL
            or self.served_tracks
        ):
            raise ValueError("an implementation-only overlay is owned by no track")
        if self.materiality is OverlayMateriality.MATERIALITY_UNRESOLVED and (
            self.owner_track is not None or self.ownership_basis is not OverlayOwnershipBasis.UNRESOLVED
        ):
            raise ValueError("unresolved materiality has no owner")
        if material:
            if (self.owner_track is None) != (self.ownership_basis is OverlayOwnershipBasis.UNRESOLVED):
                raise ValueError("a material overlay has an owner unless its ownership is UNRESOLVED")
            if self.ownership_basis is OverlayOwnershipBasis.NOT_MATERIAL:
                raise ValueError("a material overlay is not NOT_MATERIAL")
            if self.owner_track is not None and self.owner_track not in self.served_tracks:
                raise ValueError("the owner track is one of the served tracks")
        return self

    @property
    def counts_in(self) -> MethodologyTrack | None:
        """The one track whose posture counts this overlay's requirements."""
        return self.owner_track if self.materiality is OverlayMateriality.MATERIAL_TO_TARGET else None

    @property
    def blocks_well_specified(self) -> bool:
        return self.materiality is OverlayMateriality.MATERIALITY_UNRESOLVED or (
            self.materiality is OverlayMateriality.MATERIAL_TO_TARGET and self.owner_track is None
        )


def _require_phase_2j_continuity(
    target: BoundGapTarget,
    conditions: list[MaterialConditionCoverage],
    metrics: list[MetricAlignment],
    baselines: list[BaselineComparatorRecord],
) -> None:
    """Strong gap coverage covers exactly what the bound Phase 2J requirement asks
    for, and nothing Phase 3A invents. A structural reference to the requirement
    is not enough: each dimension needs a semantic plan (an aligned metric with a
    bound outcome, a documented and relevant baseline, an addressed condition)."""
    req = target.validation_requirement_id
    if target.requires_metric and not any(
        m.gap_validation_requirement_id == req and m.status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT
        for m in metrics
    ):
        raise ValueError("strong gap coverage needs a methodology plan aligned to the Phase 2J required metric")
    if target.requires_baseline and not any(
        b.gap_validation_requirement_id == req
        and b.relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT
        for b in baselines
    ):
        raise ValueError("strong gap coverage needs a relevant documented plan for the Phase 2J required baseline")
    addressed = {
        c.condition_id for c in conditions
        if c.gap_hypothesis_id == target.gap_hypothesis_id and c.status is ConditionCoverageStatus.ADDRESSED_IN_DESIGN
    }
    if set(target.material_condition_ids) - addressed:
        raise ValueError("an uncovered Phase 2J material condition prevents strong coverage")


class MethodologyRunStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    INVALIDATED_UPSTREAM_MUTATED = "INVALIDATED_UPSTREAM_MUTATED"


class MethodologyRunIssueCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    PROJECT_TYPE_UNBOUND = "PROJECT_TYPE_UNBOUND"
    CROSS_RUN_REFERENCE = "CROSS_RUN_REFERENCE"
    CROSS_CLAIM_REFERENCE = "CROSS_CLAIM_REFERENCE"
    UPSTREAM_MUTATED = "UPSTREAM_MUTATED"
    FABRICATED_REFERENCE = "FABRICATED_REFERENCE"
    FABRICATED_EXCERPT = "FABRICATED_EXCERPT"
    AMBIGUOUS_EXCERPT = "AMBIGUOUS_EXCERPT"
    INVENTED_REQUIREMENT = "INVENTED_REQUIREMENT"
    INVENTED_METRIC = "INVENTED_METRIC"
    FORBIDDEN_CONCLUSION = "FORBIDDEN_CONCLUSION"
    SOURCE_INSTRUCTION_FOLLOWED = "SOURCE_INSTRUCTION_FOLLOWED"
    OFF_CONTRACT_OUTPUT = "OFF_CONTRACT_OUTPUT"
    PROMPT_LEAK_REDACTED = "PROMPT_LEAK_REDACTED"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"
    MODEL_CALL_BOUND_REACHED = "MODEL_CALL_BOUND_REACHED"


class MethodologyRunIssue(MawhibaModel):
    code: MethodologyRunIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)
    claim_id: str | None = None


class RejectedMethodologyProposal(MawhibaModel):
    """A refused model proposal. Only a digest of the model text is persisted, so
    neither model prose nor a leaked hidden prompt can reach a stored record."""

    claim_id: str | None = Field(default=None, pattern=CLAIM_ID_PATTERN)
    code: MethodologyRunIssueCode
    response_digest: str = Field(pattern=CONTENT_HASH_PATTERN)


class MethodologyRunVersions(MawhibaModel):
    contract_version: str = METHODOLOGY_CONTRACT_VERSION
    catalog_version: str = METHODOLOGY_CATALOG_VERSION
    anchor_verifier_version: str = METHODOLOGY_ANCHOR_VERIFIER_VERSION
    synthesis_policy_version: str = METHODOLOGY_SYNTHESIS_POLICY_VERSION
    model_provider: str | None = None
    model_name: str | None = None


class MethodologyReviewBounds(MawhibaModel):
    """Every dimension of a run is bounded; a bounded run never reads complete."""

    max_submission_chars: int = Field(default=60_000, ge=1_000, le=400_000)
    max_excerpt_chars: int = Field(default=1_500, ge=50, le=10_000)
    max_excerpts: int = Field(default=300, ge=1, le=2_000)
    max_model_calls: int = Field(default=80, ge=0, le=2_000)
    model_retry_limit: int = Field(default=1, ge=0, le=5)


class MethodologyDraft(MawhibaModel):
    """Verified records carried between stages until synthesis builds the track
    assessments. Everything here already passed deterministic verification; no
    model text, rationale or unverified proposal is stored. The draft is a
    working ledger, not a result: it holds no posture and no issue."""

    methodology_run_id: UUID
    applicability: list[RequirementApplicability] = Field(default_factory=list)
    documentation: list[RequirementDocumentation] = Field(default_factory=list)
    coverage: list[MethodologyCoverageLink] = Field(default_factory=list)
    conditions: list[MaterialConditionCoverage] = Field(default_factory=list)
    unjudged_targets: list[str] = Field(
        default_factory=list,
        description="Claim ids and Phase 2J hypothesis ids a required model judgment could not be obtained for. "
        "Such a target gets an INSUFFICIENT_LINKAGE_EVIDENCE link, never a positive or a negative finding.",
    )
    source_truncated: bool = Field(
        default=False, description="The submission exceeded the bound shown to the model: absence proves nothing."
    )
    source_unread: bool = Field(
        default=False,
        description="No model read the submission (no provider, or the call failed): nothing is documented "
        "and nothing is undocumented -- every requirement is INSUFFICIENT_SOURCE_COVERAGE.",
    )
    model_calls_succeeded: int = Field(default=0, ge=0)
    model_calls_failed: int = Field(default=0, ge=0)


class MethodologyReviewRun(MawhibaModel):
    methodology_run_id: UUID
    research_run_id: UUID
    gap_run_id: UUID | None = None
    nd_run_id: UUID | None = None
    status: MethodologyRunStatus = MethodologyRunStatus.NOT_STARTED
    versions: MethodologyRunVersions = Field(default_factory=MethodologyRunVersions)
    canonical_project_type: ProjectType = ProjectType.UNKNOWN
    tracks: list[MethodologyTrack] = Field(default_factory=list)
    overlays: list[OverlayAssignment] = Field(default_factory=list)
    submission_artifact_id: UUID | None = None
    submission_content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    upstream_bindings: list[MethodologyUpstreamBinding] = Field(default_factory=list)
    draft: MethodologyDraft | None = None
    bound_claims: list[BoundClaim] = Field(default_factory=list)
    bound_gap_targets: list[BoundGapTarget] = Field(default_factory=list)
    excerpts: list[StudentMethodologyExcerpt] = Field(default_factory=list)
    baselines: list[BaselineComparatorRecord] = Field(default_factory=list)
    metric_alignments: list[MetricAlignment] = Field(default_factory=list)
    track_assessments: list[MethodologyTrackAssessment] = Field(default_factory=list)
    rejected_proposals: list[RejectedMethodologyProposal] = Field(default_factory=list)
    not_documented_meaning: Literal["NOT_DOCUMENTED_IN_BOUND_INPUT_IS_NOT_EVIDENCE_OF_NON_PERFORMANCE"] = (
        NOT_DOCUMENTED_MEANING
    )
    model_calls_performed: int = Field(default=0, ge=0)
    external_search_calls: Literal[0] = 0
    errors: list[MethodologyRunIssue] = Field(default_factory=list)
    stage_markers: list[str] = Field(default_factory=list)
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _bound_and_consistent(self) -> MethodologyReviewRun:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if len({b.phase for b in self.upstream_bindings}) != len(self.upstream_bindings):
            raise ValueError("one binding per upstream phase")
        if list(self.tracks) != list(tracks_for(self.canonical_project_type)):
            raise ValueError("tracks are inherited from the canonical project type, never reclassified")
        if not self.tracks and self.status is MethodologyRunStatus.COMPLETED:
            raise ValueError("an unbound project type is INSUFFICIENT_INPUT, never COMPLETED")
        if self.status is MethodologyRunStatus.COMPLETED and [a.track for a in self.track_assessments] != self.tracks:
            raise ValueError("a completed run has exactly one assessment per inherited track (HYBRID keeps both)")
        if self.excerpts and (self.submission_artifact_id is None or self.submission_content_hash is None):
            raise ValueError("excerpts require a bound submission")
        own = self.methodology_run_id
        children = [*self.excerpts, *self.baselines, *self.metric_alignments, *self.track_assessments, *self.overlays]
        for ta in self.track_assessments:
            children += [*ta.applicability, *ta.documentation, *ta.coverage, *ta.conditions, *ta.issues]
        if self.draft is not None:
            children += [self.draft, *self.draft.applicability, *self.draft.documentation, *self.draft.coverage,
                         *self.draft.conditions]
        if any(c.methodology_run_id != own for c in children):
            raise ValueError("a record belongs to a different methodology run (cross-run mixing)")
        excerpts = {e.excerpt_id: e for e in self.excerpts}
        if len(excerpts) != len(self.excerpts):
            raise ValueError("excerpt ids are unique; a replay must not duplicate them")
        if any(
            e.submission_artifact_id != self.submission_artifact_id
            or e.submission_content_hash != self.submission_content_hash
            for e in self.excerpts
        ):
            raise ValueError("an excerpt cut from a different submission")
        claims = {c.claim_id: c.claim_text_hash for c in self.bound_claims}
        if len(claims) != len(self.bound_claims):
            raise ValueError("a claim is bound once")
        targets = {t.gap_hypothesis_id: t for t in self.bound_gap_targets}
        if any(t.claim_id not in claims for t in self.bound_gap_targets):
            raise ValueError("a gap target names an unbound claim")

        def _cited(ids: list[UUID]) -> None:
            if any(i not in excerpts for i in ids):
                raise ValueError("a record cites an excerpt outside the run (fabricated reference)")

        def _own_requirement(claim_id: str, req_id: UUID | None, what: str) -> None:
            if req_id is not None and req_id not in {
                t.validation_requirement_id for t in self.bound_gap_targets if t.claim_id == claim_id
            }:
                raise ValueError(f"a {what} cites a Phase 2J requirement of another claim (cross-claim)")

        for b in self.baselines:
            _cited([*b.baseline_excerpt_ids, *b.rationale_excerpt_ids])
            if b.target_claim_id not in claims:
                raise ValueError("a baseline targets an unbound claim")
            _own_requirement(b.target_claim_id, b.gap_validation_requirement_id, "baseline")
        for m in self.metric_alignments:
            _cited([i for i in (m.outcome_excerpt_id, m.metric_excerpt_id) if i is not None])
            if m.target_claim_id not in claims:
                raise ValueError("a metric alignment targets an unbound claim")
            _own_requirement(m.target_claim_id, m.gap_validation_requirement_id, "metric")

        # -- overlay ownership: one assignment per overlay, counted in one track only --
        assignments = {o.overlay: o for o in self.overlays}
        if len(assignments) != len(self.overlays):
            raise ValueError("one assignment per overlay")
        single = len(self.tracks) == 1
        facet_track = {GapFacet.RESEARCH: _R, GapFacet.ENGINEERING: _E}
        for o in self.overlays:
            _cited(o.excerpt_ids)
            if not set(o.served_tracks) <= set(self.tracks):
                raise ValueError("an overlay serves a track the project type does not have")
            if any(c not in claims for c in o.material_claim_ids) or any(
                h not in targets for h in o.material_gap_hypothesis_ids
            ):
                raise ValueError("an overlay's materiality cites an unbound target")
            if o.owner_track is not None:
                if single != (o.ownership_basis is OverlayOwnershipBasis.SINGLE_TRACK_PROJECT):
                    raise ValueError("a single-track project owns its overlays by that track; HYBRID never does")
                if o.ownership_basis is OverlayOwnershipBasis.PHASE_2J_LIMITATION_FACET:
                    facets = {f for h in o.material_gap_hypothesis_ids for f in targets[h].limitation_facets}
                    if not o.material_gap_hypothesis_ids or {facet_track[f] for f in facets} != {o.owner_track}:
                        raise ValueError("facet ownership follows the served hypotheses' one Phase 2J facet")
                if o.ownership_basis is OverlayOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT and not o.excerpt_ids:
                    raise ValueError("a judged ownership binds its excerpts")
        instantiated: dict[RequirementKind, MethodologyTrack] = {}
        for ta in self.track_assessments:
            for a in ta.applicability:
                overlay = REQUIREMENT_CATALOG[a.kind].overlay
                if overlay is RequirementOverlay.CORE or a.track is None:
                    continue
                owner = assignments[overlay].counts_in if overlay in assignments else None
                if a.track is not owner:
                    raise ValueError("an overlay requirement is counted only in its owner track")
                if instantiated.setdefault(a.kind, a.track) is not a.track or sum(
                    1 for x in ta.applicability if x.kind is a.kind
                ) != 1:
                    raise ValueError("an overlay requirement is counted once (no double counting)")
        if any(o.blocks_well_specified for o in self.overlays) and any(
            ta.posture is MethodologyPosture.METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT
            for ta in self.track_assessments
        ):
            raise ValueError("an unresolved overlay materiality or ownership forbids a well-specified track")
        documented_anywhere = {
            (d.kind, ta.track)
            for ta in self.track_assessments
            for d in ta.documentation
            if d.documentation in _DOC_WITH_EXCERPTS
        }

        for ta in self.track_assessments:
            for d in ta.documentation:
                _cited(d.excerpt_ids)
                if d.kind in RATIONALE_KINDS and d.documentation in _DOC_WITH_EXCERPTS and all(
                    _BARE_QUANTITY.match(excerpts[i].excerpt) for i in d.excerpt_ids
                ):
                    raise ValueError("a bare number is not a rationale (sample size alone is not justified)")
            for a in ta.applicability:
                _cited(a.judgment_excerpt_ids)
            documented = {d.kind for d in ta.documentation if d.documentation in _DOC_WITH_EXCERPTS}
            for link in ta.coverage:
                _cited(link.excerpt_ids)
                if claims.get(link.claim_id) != link.claim_text_hash:
                    raise ValueError("a coverage link binds an unbound or stale claim")
                if link.gap_hypothesis_id is not None:
                    target = targets.get(link.gap_hypothesis_id)
                    if target is None or target.claim_id != link.claim_id:
                        raise ValueError("a coverage link crosses to another claim's gap (cross-claim)")
                if link.relation in STRONG_COVERAGE:
                    for kind in link.requirement_kinds:
                        overlay = REQUIREMENT_CATALOG[kind].overlay
                        shared = overlay in assignments and ta.track in assignments[overlay].served_tracks and (
                            kind, assignments[overlay].counts_in) in documented_anywhere
                        if kind not in documented and not shared:
                            raise ValueError(
                                "strong coverage rests only on requirements this track documents "
                                "(or an overlay requirement documented by its owner for a served track)"
                            )
                    if link.gap_hypothesis_id is not None:
                        _require_phase_2j_continuity(targets[link.gap_hypothesis_id], ta.conditions,
                                                     self.metric_alignments, self.baselines)
                    elif not any(
                        m.target_claim_id == link.claim_id
                        and m.status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT
                        for m in self.metric_alignments
                    ):
                        raise ValueError("strong claim coverage needs an aligned metric for the target")
            for c in ta.conditions:
                _cited(c.excerpt_ids)
                target = targets.get(c.gap_hypothesis_id)
                if target is None or c.condition_id not in target.material_condition_ids:
                    raise ValueError("a condition coverage names a condition its Phase 2J hypothesis does not carry")
            for i in ta.issues:
                if i.claim_id is not None and i.claim_id not in claims:
                    raise ValueError("an issue names an unbound claim")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            MethodologyRunStatus.COMPLETED,
            MethodologyRunStatus.INSUFFICIENT_INPUT,
            MethodologyRunStatus.INVALIDATED_UPSTREAM_MUTATED,
        ) and self.completed_at is not None

    def assessment_for(self, track: MethodologyTrack) -> MethodologyTrackAssessment | None:
        return next((a for a in self.track_assessments if a.track is track), None)


def upstream_fingerprint(record: MawhibaModel) -> str:
    """The fingerprint compared at bind and at finalize."""
    return text_hash(record.model_dump_json())


def mutated_bindings(
    run: MethodologyReviewRun, current: dict[MethodologyUpstreamPhase, MawhibaModel]
) -> list[MethodologyUpstreamPhase]:
    """Every bound upstream whose current fingerprint differs (or that vanished)."""
    return [
        b.phase
        for b in run.upstream_bindings
        if b.phase not in current or upstream_fingerprint(current[b.phase]) != b.fingerprint
    ]


FORBIDDEN_FIELD_FRAGMENTS: tuple[str, ...] = (
    "score",
    "probability",
    "confidence",
    "readiness",
    "novel",
    "patentab",
    "infring",
    "legal",
    "verdict",
    "rank",
    "threshold",
    "result",
    "outcome_value",
    "accuracy",
    "red_team",
    "jury",
    "experiment_valid",
    "proven",
    "valid_method",
)
"""No Phase 3A field name may contain any of these (sections 26, 30)."""

