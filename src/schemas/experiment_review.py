"""Experiment review contracts -- Phase 3B (ADR-023).

Phase 3B answers one question: does the *documented* experiment / test protocol
provide an adequate and auditable way to test the claim that matters, and the
Phase 2J validation requirement bound to it? It reviews protocols only. It
never decides whether the project succeeded, whether a reported result is true,
whether a result supports a claim, or anything about novelty, legality,
scoring, Red Team or readiness. Result Review is a later, separate phase.

The record chain, one type per link:

    StudentExperimentExcerpt     an exact, code-sliced protocol span of the verbatim submission
    QuarantinedSpan              a result span: offsets + hash only, never text, never consumed
    ExperimentRequirement        a catalog requirement, resolved, documented and judged for one experiment
    MeasurementBinding           method -> metric -> target -> success criterion, same target only
    ExperimentBaselineRecord     documented != relevant != comparable != executed != verified
    ConditionCoverage            a Phase 2J material condition, covered by one experiment's protocol or not
    ExperimentTargetLink         experiment -> claim -> Phase 2J hypothesis -> validation requirement
    ExperimentRecord             one experiment: identity, type, track, issues and posture (derived)
    Phase2JCoverage              one Phase 2J validation requirement: covered by protocol or not (derived)
    TrackPostureRecord           one track's posture (derived, worst-wins, never averaged)
    ExperimentReviewRun          the run, bound to its upstream and to the submission

Distinctions this module refuses to collapse, each enforced structurally:

* **described vs verified execution.** ``execution_verified`` is a literal
  ``False`` everywhere. No execution-evidence field exists (ADR-023 section 10).
* **protocol vs result.** Result spans live only in ``quarantine`` as offsets
  and a hash; every derivation function takes no quarantine argument; a protocol
  excerpt may never overlap a quarantined span; ``adequacy_fingerprint`` excludes
  the quarantine, so a changed result value cannot change adequacy.
* **documentation vs adequacy.** Two fields on two enums, with a closed table of
  reachable pairs.
* **metric present vs metric aligned.** A ``DIRECTLY_TESTS`` link needs an
  aligned measurement binding for the *same* experiment and the *same* target.
* **baseline present vs baseline fair.** Comparability is per property, and the
  roll-up never reads ``FAIR``; ``comparison_result_evaluated`` is literal False.
* **tracks.** A HYBRID project gets one posture per track and a project posture
  that is the worst of them: there is nothing to average into.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.common import MawhibaModel, ProjectType, Severity, UtcDatetime
from src.schemas.discovery import CONTENT_HASH_PATTERN, MAX_SAFE_SUMMARY_LENGTH
from src.schemas.gap_assessment import GapFacet, GapHypothesis
from src.schemas.methodology_review import (
    Applicability,
    BaselineRelevance,
    BoundClaim,
    DocumentationStatus,
    MethodologyTrack,
    tracks_for,
)
from src.schemas.novelty_differentiation import OccurrenceResolution

EXPERIMENT_CONTRACT_VERSION = "EXPERIMENT-REVIEW-CONTRACT-V1"
EXPERIMENT_CATALOG_VERSION = "EXPERIMENT-REQUIREMENT-CATALOG-V1"
EXPERIMENT_ANCHOR_VERIFIER_VERSION = "EXPERIMENT-EXCERPT-ANCHOR-VERIFIER-V1"
EXPERIMENT_SYNTHESIS_POLICY_VERSION = "EXPERIMENT-POSTURE-SYNTHESIS-POLICY-V1"

EXPERIMENT_ID_NAMESPACE = UUID("3e9c5a71-8d24-5b6f-9a13-c47e2d8f0b65")

MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"

EXECUTION_BOUNDARY = "EXECUTION_DESCRIBED_IS_NOT_EXECUTION_VERIFIED"
"""Carried by every run: a student describing a run is a description, never execution evidence."""


def experiment_uuid(*parts: object) -> UUID:
    """A deterministic run-bound id. Same parts, same id, every rerun."""
    return uuid5(EXPERIMENT_ID_NAMESPACE, "|".join(str(p) for p in parts))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stages (graph design, section 33). Names only; no node is implemented here.
# ---------------------------------------------------------------------------


class ExperimentStage(StrEnum):
    BIND_INPUTS = "EXPERIMENT_BIND_INPUTS"
    SEGMENT_EXPERIMENTS = "EXPERIMENT_SEGMENT"
    EXTRACT_PROTOCOL = "EXPERIMENT_EXTRACT_PROTOCOL"
    RESOLVE_APPLICABILITY = "EXPERIMENT_RESOLVE_APPLICABILITY"
    LINK_TARGETS = "EXPERIMENT_LINK_TARGETS"
    SYNTHESIZE = "EXPERIMENT_SYNTHESIZE"
    FINALIZE = "EXPERIMENT_FINALIZE"


MODEL_ASSISTED_STAGES: frozenset[ExperimentStage] = frozenset(
    {
        ExperimentStage.SEGMENT_EXPERIMENTS,
        ExperimentStage.EXTRACT_PROTOCOL,
        ExperimentStage.RESOLVE_APPLICABILITY,
        ExperimentStage.LINK_TARGETS,
    }
)
"""Every other stage is deterministic and receives no model provider."""


# ---------------------------------------------------------------------------
# Experiment type taxonomy (section 9)
# ---------------------------------------------------------------------------


class ExperimentType(StrEnum):
    SCIENTIFIC_CONTROLLED_EXPERIMENT = "SCIENTIFIC_CONTROLLED_EXPERIMENT"
    SCIENTIFIC_OBSERVATIONAL_STUDY = "SCIENTIFIC_OBSERVATIONAL_STUDY"
    ENGINEERING_BENCH_TEST = "ENGINEERING_BENCH_TEST"
    ENGINEERING_FIELD_TEST = "ENGINEERING_FIELD_TEST"
    ENGINEERING_STRESS_TEST = "ENGINEERING_STRESS_TEST"
    ENGINEERING_COMPARATIVE_TEST = "ENGINEERING_COMPARATIVE_TEST"
    AI_ML_MODEL_EVALUATION = "AI_ML_MODEL_EVALUATION"
    AI_ML_ABLATION = "AI_ML_ABLATION"
    AI_ML_EXTERNAL_VALIDATION = "AI_ML_EXTERNAL_VALIDATION"
    SOFTWARE_BENCHMARK = "SOFTWARE_BENCHMARK"
    SOFTWARE_LOAD_TEST = "SOFTWARE_LOAD_TEST"
    SOFTWARE_SECURITY_TEST = "SOFTWARE_SECURITY_TEST"
    SOFTWARE_USABILITY_TEST = "SOFTWARE_USABILITY_TEST"
    SIMULATION = "SIMULATION"
    OTHER_BOUNDED_EXPERIMENT = "OTHER_BOUNDED_EXPERIMENT"
    UNKNOWN = "UNKNOWN"


class ExperimentFamily(StrEnum):
    """The column of the applicability matrix. Not a track: an AI/ML evaluation
    may serve a research hypothesis, so the family never decides ownership."""

    SCIENTIFIC = "SCIENTIFIC"
    ENGINEERING = "ENGINEERING"
    AI_ML = "AI_ML"
    SOFTWARE = "SOFTWARE"
    SIMULATION = "SIMULATION"
    OTHER = "OTHER"


_X = ExperimentType
_F = ExperimentFamily
TYPE_FAMILY: dict[ExperimentType, ExperimentFamily | None] = {
    _X.SCIENTIFIC_CONTROLLED_EXPERIMENT: _F.SCIENTIFIC,
    _X.SCIENTIFIC_OBSERVATIONAL_STUDY: _F.SCIENTIFIC,
    _X.ENGINEERING_BENCH_TEST: _F.ENGINEERING,
    _X.ENGINEERING_FIELD_TEST: _F.ENGINEERING,
    _X.ENGINEERING_STRESS_TEST: _F.ENGINEERING,
    _X.ENGINEERING_COMPARATIVE_TEST: _F.ENGINEERING,
    _X.AI_ML_MODEL_EVALUATION: _F.AI_ML,
    _X.AI_ML_ABLATION: _F.AI_ML,
    _X.AI_ML_EXTERNAL_VALIDATION: _F.AI_ML,
    _X.SOFTWARE_BENCHMARK: _F.SOFTWARE,
    _X.SOFTWARE_LOAD_TEST: _F.SOFTWARE,
    _X.SOFTWARE_SECURITY_TEST: _F.SOFTWARE,
    _X.SOFTWARE_USABILITY_TEST: _F.SOFTWARE,
    _X.SIMULATION: _F.SIMULATION,
    _X.OTHER_BOUNDED_EXPERIMENT: _F.OTHER,
    _X.UNKNOWN: None,
}

if set(TYPE_FAMILY) != set(ExperimentType):  # pragma: no cover - import-time guard
    raise RuntimeError("every experiment type has a family entry")


# ---------------------------------------------------------------------------
# Requirement inventory and applicability matrix (sections 10, 11, 15-19)
# ---------------------------------------------------------------------------


class RequirementGroup(StrEnum):
    PURPOSE_AND_TARGET = "PURPOSE_AND_TARGET"
    SETUP_AND_ENVIRONMENT = "SETUP_AND_ENVIRONMENT"
    INPUTS_AND_OUTPUTS = "INPUTS_AND_OUTPUTS"
    VARIABLES_AND_CONTROLS = "VARIABLES_AND_CONTROLS"
    BASELINE_AND_COMPARATOR = "BASELINE_AND_COMPARATOR"
    SAMPLE_AND_REPETITIONS = "SAMPLE_AND_REPETITIONS"
    MEASUREMENT = "MEASUREMENT"
    STATISTICS = "STATISTICS"
    BIAS_AND_LEAKAGE = "BIAS_AND_LEAKAGE"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    SAFETY_AND_ETHICS = "SAFETY_AND_ETHICS"


class ExperimentTrigger(StrEnum):
    """The closed set of facts that can turn a CONDITIONAL requirement on."""

    IMPROVEMENT_OR_COMPARATIVE_CLAIM = "IMPROVEMENT_OR_COMPARATIVE_CLAIM"
    PHASE_2J_BASELINE_REQUIRED = "PHASE_2J_BASELINE_REQUIRED"
    PHASE_2J_MATERIAL_CONDITION = "PHASE_2J_MATERIAL_CONDITION"
    ASSIGNED_INTERVENTION = "ASSIGNED_INTERVENTION"
    QUANTITATIVE_MEASUREMENT = "QUANTITATIVE_MEASUREMENT"
    STATISTICAL_INFERENCE_CLAIMED = "STATISTICAL_INFERENCE_CLAIMED"
    MULTIPLE_COMPARISONS_MADE = "MULTIPLE_COMPARISONS_MADE"
    STOCHASTIC_PROCESS = "STOCHASTIC_PROCESS"
    REPLICATION_RELIED_ON = "REPLICATION_RELIED_ON"
    SAMPLED_POPULATION = "SAMPLED_POPULATION"
    DATASET_USED = "DATASET_USED"
    PHYSICAL_INSTRUMENT = "PHYSICAL_INSTRUMENT"
    SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT = "SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT"
    HUMAN_PARTICIPANTS = "HUMAN_PARTICIPANTS"
    ANIMAL_SUBJECTS = "ANIMAL_SUBJECTS"
    PERSONAL_DATA_PROCESSED = "PERSONAL_DATA_PROCESSED"
    SAFETY_RELEVANT = "SAFETY_RELEVANT"
    MODEL_TUNING_PERFORMED = "MODEL_TUNING_PERFORMED"
    PUBLIC_BENCHMARK_USED = "PUBLIC_BENCHMARK_USED"
    IMBALANCED_LABELS = "IMBALANCED_LABELS"
    GENERALIZATION_CLAIMED = "GENERALIZATION_CLAIMED"
    PERFORMANCE_CLAIMED = "PERFORMANCE_CLAIMED"
    SECURITY_CLAIMED = "SECURITY_CLAIMED"
    RELIABILITY_CLAIMED = "RELIABILITY_CLAIMED"
    FIELD_CONDITIONS_MATERIAL = "FIELD_CONDITIONS_MATERIAL"


class ExperimentRequirementKind(StrEnum):
    # A. purpose and target
    OBJECTIVE = "OBJECTIVE"
    TARGET_BINDING = "TARGET_BINDING"
    HYPOTHESIS_OR_VALIDATION_OBJECTIVE = "HYPOTHESIS_OR_VALIDATION_OBJECTIVE"
    SUCCESS_CRITERION = "SUCCESS_CRITERION"
    REQUIREMENT_TRACEABILITY = "REQUIREMENT_TRACEABILITY"
    # B. setup and environment
    SETUP = "SETUP"
    ENVIRONMENT = "ENVIRONMENT"
    CONFIGURATION = "CONFIGURATION"
    CALIBRATION = "CALIBRATION"
    OPERATING_CONDITIONS = "OPERATING_CONDITIONS"
    # C. inputs and outputs
    INPUTS = "INPUTS"
    OUTPUTS = "OUTPUTS"
    INCLUSION_EXCLUSION_RULES = "INCLUSION_EXCLUSION_RULES"
    DATA_PROVENANCE = "DATA_PROVENANCE"
    SAMPLE_IDENTITY = "SAMPLE_IDENTITY"
    WORKLOAD = "WORKLOAD"
    # D. variables and controls
    INDEPENDENT_VARIABLE = "INDEPENDENT_VARIABLE"
    DEPENDENT_VARIABLE = "DEPENDENT_VARIABLE"
    CONTROLLED_VARIABLES = "CONTROLLED_VARIABLES"
    CONTROL_STRATEGY = "CONTROL_STRATEGY"
    CONFOUNDERS = "CONFOUNDERS"
    INTERVENTION_COMPARATOR_SEPARATION = "INTERVENTION_COMPARATOR_SEPARATION"
    # E. baseline / comparator
    BASELINE = "BASELINE"
    BASELINE_CONFIGURATION = "BASELINE_CONFIGURATION"
    # F. sample / repetitions
    SAMPLE_DEFINITION = "SAMPLE_DEFINITION"
    SAMPLE_SIZE = "SAMPLE_SIZE"
    SAMPLE_SIZE_RATIONALE = "SAMPLE_SIZE_RATIONALE"
    REPETITIONS = "REPETITIONS"
    REPETITION_INDEPENDENCE = "REPETITION_INDEPENDENCE"
    SEED_OR_REPEATABILITY = "SEED_OR_REPEATABILITY"
    WARM_UP = "WARM_UP"
    STRESS_AND_EDGE_CASES = "STRESS_AND_EDGE_CASES"
    # G. measurement
    MEASUREMENT_METHOD = "MEASUREMENT_METHOD"
    INSTRUMENT = "INSTRUMENT"
    UNITS = "UNITS"
    METRIC = "METRIC"
    MEASUREMENT_RESOLUTION = "MEASUREMENT_RESOLUTION"
    MEASUREMENT_UNCERTAINTY = "MEASUREMENT_UNCERTAINTY"
    TOLERANCE = "TOLERANCE"
    MISSING_DATA_HANDLING = "MISSING_DATA_HANDLING"
    # H. statistics (all conditional; section 15)
    DESCRIPTIVE_STATISTICS = "DESCRIPTIVE_STATISTICS"
    CONFIDENCE_INTERVAL = "CONFIDENCE_INTERVAL"
    EFFECT_SIZE = "EFFECT_SIZE"
    STATISTICAL_TEST = "STATISTICAL_TEST"
    TEST_ASSUMPTIONS = "TEST_ASSUMPTIONS"
    MULTIPLE_COMPARISONS = "MULTIPLE_COMPARISONS"
    OUTLIER_HANDLING = "OUTLIER_HANDLING"
    POWER_OR_SAMPLE_ADEQUACY = "POWER_OR_SAMPLE_ADEQUACY"
    # I. bias / leakage
    SELECTION_BIAS = "SELECTION_BIAS"
    MEASUREMENT_BIAS = "MEASUREMENT_BIAS"
    BLINDING = "BLINDING"
    RANDOMIZATION = "RANDOMIZATION"
    FAILURE_MODES = "FAILURE_MODES"
    TRAIN_TEST_SEPARATION = "TRAIN_TEST_SEPARATION"
    TEST_SET_INDEPENDENCE = "TEST_SET_INDEPENDENCE"
    DUPLICATE_LEAKAGE_CONTROL = "DUPLICATE_LEAKAGE_CONTROL"
    TUNING_ISOLATION = "TUNING_ISOLATION"
    BENCHMARK_CONTAMINATION = "BENCHMARK_CONTAMINATION"
    CLASS_IMBALANCE = "CLASS_IMBALANCE"
    CROSS_VALIDATION = "CROSS_VALIDATION"
    EXTERNAL_VALIDATION = "EXTERNAL_VALIDATION"
    ERROR_ANALYSIS = "ERROR_ANALYSIS"
    SECURITY_TEST_CONDITIONS = "SECURITY_TEST_CONDITIONS"
    # J. reproducibility
    PROTOCOL_DETAIL = "PROTOCOL_DETAIL"
    VERSION_INFORMATION = "VERSION_INFORMATION"
    # K. safety / ethics (never a legal or regulatory conclusion)
    SAFETY_CONTROLS = "SAFETY_CONTROLS"
    HUMAN_ANIMAL_DATA_CONSTRAINTS = "HUMAN_ANIMAL_DATA_CONSTRAINTS"
    PRIVACY_CONSTRAINTS = "PRIVACY_CONSTRAINTS"


FAMILY_COLUMNS: tuple[ExperimentFamily, ...] = (_F.SCIENTIFIC, _F.ENGINEERING, _F.AI_ML, _F.SOFTWARE,
                                                _F.SIMULATION, _F.OTHER)
_CELL = {"R": Applicability.REQUIRED, "C": Applicability.CONDITIONAL, "O": Applicability.OPTIONAL,
         "-": Applicability.NOT_APPLICABLE}


class ExperimentCatalogEntry(MawhibaModel):
    """One deterministic catalog row. Policy, constructed at import, never checkpointed."""

    kind: ExperimentRequirementKind
    group: RequirementGroup
    defaults: dict[ExperimentFamily, Applicability]
    triggers: tuple[ExperimentTrigger, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> ExperimentCatalogEntry:
        if set(self.defaults) != set(ExperimentFamily):
            raise ValueError("a catalog row states applicability for every family")
        conditional = Applicability.CONDITIONAL in self.defaults.values()
        if conditional != bool(self.triggers):
            raise ValueError("exactly the rows with a CONDITIONAL cell declare triggers")
        if all(a is Applicability.NOT_APPLICABLE for a in self.defaults.values()):
            raise ValueError("a catalog row applies to some family (no dead requirement)")
        return self

    @property
    def universally_required(self) -> bool:
        return all(a is Applicability.REQUIRED for a in self.defaults.values())


ERK = ExperimentRequirementKind
_G = RequirementGroup
_T = ExperimentTrigger


def _row(kind: ExperimentRequirementKind, group: RequirementGroup, cells: str,
         *triggers: ExperimentTrigger) -> ExperimentCatalogEntry:
    """``cells`` is one letter per FAMILY_COLUMNS entry: R, C, O or -."""
    if len(cells) != len(FAMILY_COLUMNS):  # pragma: no cover - authoring guard
        raise RuntimeError(f"{kind.value}: one cell per family")
    return ExperimentCatalogEntry(
        kind=kind, group=group, defaults={f: _CELL[c] for f, c in zip(FAMILY_COLUMNS, cells, strict=True)},
        triggers=tuple(triggers),
    )


#                                                        S E A W M O
EXPERIMENT_CATALOG: dict[ExperimentRequirementKind, ExperimentCatalogEntry] = {
    e.kind: e
    for e in (
        _row(ERK.OBJECTIVE, _G.PURPOSE_AND_TARGET,              "RRRRRR"),
        _row(ERK.TARGET_BINDING, _G.PURPOSE_AND_TARGET,         "RRRRRR"),
        _row(ERK.HYPOTHESIS_OR_VALIDATION_OBJECTIVE, _G.PURPOSE_AND_TARGET, "RRRRRR"),
        _row(ERK.SUCCESS_CRITERION, _G.PURPOSE_AND_TARGET,      "RRRRRR"),
        _row(ERK.REQUIREMENT_TRACEABILITY, _G.PURPOSE_AND_TARGET, "-RORO-"),
        _row(ERK.SETUP, _G.SETUP_AND_ENVIRONMENT,               "RRRRRR"),
        _row(ERK.ENVIRONMENT, _G.SETUP_AND_ENVIRONMENT,         "RRRRRR"),
        _row(ERK.CONFIGURATION, _G.SETUP_AND_ENVIRONMENT,       "ORRRRO"),
        _row(ERK.CALIBRATION, _G.SETUP_AND_ENVIRONMENT,         "CC---C", _T.PHYSICAL_INSTRUMENT),
        _row(ERK.OPERATING_CONDITIONS, _G.SETUP_AND_ENVIRONMENT, "CRCCRC",
             _T.PHASE_2J_MATERIAL_CONDITION, _T.FIELD_CONDITIONS_MATERIAL),
        _row(ERK.INPUTS, _G.INPUTS_AND_OUTPUTS,                 "RRRRRR"),
        _row(ERK.OUTPUTS, _G.INPUTS_AND_OUTPUTS,                "RRRRRR"),
        _row(ERK.INCLUSION_EXCLUSION_RULES, _G.INPUTS_AND_OUTPUTS, "C-CC-C",
             _T.SAMPLED_POPULATION, _T.HUMAN_PARTICIPANTS),
        _row(ERK.DATA_PROVENANCE, _G.INPUTS_AND_OUTPUTS,        "CCRCCC", _T.DATASET_USED),
        _row(ERK.SAMPLE_IDENTITY, _G.INPUTS_AND_OUTPUTS,        "ROO--O"),
        _row(ERK.WORKLOAD, _G.INPUTS_AND_OUTPUTS,               "---C--", _T.PERFORMANCE_CLAIMED),
        _row(ERK.INDEPENDENT_VARIABLE, _G.VARIABLES_AND_CONTROLS, "RCCCRC", _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM),
        _row(ERK.DEPENDENT_VARIABLE, _G.VARIABLES_AND_CONTROLS, "RRRRRR"),
        _row(ERK.CONTROLLED_VARIABLES, _G.VARIABLES_AND_CONTROLS, "RRCCRC", _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM),
        _row(ERK.CONTROL_STRATEGY, _G.VARIABLES_AND_CONTROLS,   "CC---C",
             _T.ASSIGNED_INTERVENTION, _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM),
        _row(ERK.CONFOUNDERS, _G.VARIABLES_AND_CONTROLS,        "RCCC-C", _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM),
        _row(ERK.INTERVENTION_COMPARATOR_SEPARATION, _G.VARIABLES_AND_CONTROLS, "CCCCCC",
             _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM),
        # Section 12: any improvement claim needs a comparator; so does a Phase 2J baseline.
        _row(ERK.BASELINE, _G.BASELINE_AND_COMPARATOR,          "CCCCCC",
             _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM, _T.PHASE_2J_BASELINE_REQUIRED),
        _row(ERK.BASELINE_CONFIGURATION, _G.BASELINE_AND_COMPARATOR, "CCCCCC",
             _T.IMPROVEMENT_OR_COMPARATIVE_CLAIM, _T.PHASE_2J_BASELINE_REQUIRED),
        _row(ERK.SAMPLE_DEFINITION, _G.SAMPLE_AND_REPETITIONS,  "RRRRRR"),
        _row(ERK.SAMPLE_SIZE, _G.SAMPLE_AND_REPETITIONS,        "RRRRRR"),
        _row(ERK.SAMPLE_SIZE_RATIONALE, _G.SAMPLE_AND_REPETITIONS, "COCCOC",
             _T.STATISTICAL_INFERENCE_CLAIMED, _T.SAMPLED_POPULATION, _T.HUMAN_PARTICIPANTS),
        _row(ERK.REPETITIONS, _G.SAMPLE_AND_REPETITIONS,        "RRCRCC",
             _T.STOCHASTIC_PROCESS, _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.REPETITION_INDEPENDENCE, _G.SAMPLE_AND_REPETITIONS, "CCCCCC",
             _T.REPLICATION_RELIED_ON, _T.STATISTICAL_INFERENCE_CLAIMED),
        _row(ERK.SEED_OR_REPEATABILITY, _G.SAMPLE_AND_REPETITIONS, "--RCC-", _T.STOCHASTIC_PROCESS),
        _row(ERK.WARM_UP, _G.SAMPLE_AND_REPETITIONS,            "---C--", _T.PERFORMANCE_CLAIMED),
        _row(ERK.STRESS_AND_EDGE_CASES, _G.SAMPLE_AND_REPETITIONS, "-C-C--",
             _T.RELIABILITY_CLAIMED, _T.SAFETY_RELEVANT),
        _row(ERK.MEASUREMENT_METHOD, _G.MEASUREMENT,            "RRRRRR"),
        _row(ERK.INSTRUMENT, _G.MEASUREMENT,                    "RROR-C", _T.PHYSICAL_INSTRUMENT),
        _row(ERK.UNITS, _G.MEASUREMENT,                         "CCCCCC", _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.METRIC, _G.MEASUREMENT,                        "RRRRRR"),
        _row(ERK.MEASUREMENT_RESOLUTION, _G.MEASUREMENT,        "CC---C", _T.PHYSICAL_INSTRUMENT),
        _row(ERK.MEASUREMENT_UNCERTAINTY, _G.MEASUREMENT,       "CCCCCC", _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.TOLERANCE, _G.MEASUREMENT,                     "-C----", _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.MISSING_DATA_HANDLING, _G.MEASUREMENT,         "C-CC-C",
             _T.SAMPLED_POPULATION, _T.DATASET_USED, _T.HUMAN_PARTICIPANTS),
        _row(ERK.DESCRIPTIVE_STATISTICS, _G.STATISTICS,         "CCCCCC", _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.CONFIDENCE_INTERVAL, _G.STATISTICS,            "CCCCCC",
             _T.STATISTICAL_INFERENCE_CLAIMED, _T.GENERALIZATION_CLAIMED),
        _row(ERK.EFFECT_SIZE, _G.STATISTICS,                    "CCCC-C",
             _T.STATISTICAL_INFERENCE_CLAIMED),
        _row(ERK.STATISTICAL_TEST, _G.STATISTICS,               "CCCCCC", _T.STATISTICAL_INFERENCE_CLAIMED),
        _row(ERK.TEST_ASSUMPTIONS, _G.STATISTICS,               "CCCCCC", _T.STATISTICAL_INFERENCE_CLAIMED),
        _row(ERK.MULTIPLE_COMPARISONS, _G.STATISTICS,           "CCCCCC", _T.MULTIPLE_COMPARISONS_MADE),
        _row(ERK.OUTLIER_HANDLING, _G.STATISTICS,               "CCCC-C", _T.QUANTITATIVE_MEASUREMENT),
        _row(ERK.POWER_OR_SAMPLE_ADEQUACY, _G.STATISTICS,       "COOO-O", _T.STATISTICAL_INFERENCE_CLAIMED),
        _row(ERK.SELECTION_BIAS, _G.BIAS_AND_LEAKAGE,           "C-CC-C",
             _T.SAMPLED_POPULATION, _T.DATASET_USED, _T.HUMAN_PARTICIPANTS),
        _row(ERK.MEASUREMENT_BIAS, _G.BIAS_AND_LEAKAGE,         "RCCC-C", _T.SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT),
        _row(ERK.BLINDING, _G.BIAS_AND_LEAKAGE,                 "CC-C-C",
             _T.SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT, _T.HUMAN_PARTICIPANTS),
        _row(ERK.RANDOMIZATION, _G.BIAS_AND_LEAKAGE,            "C--C--", _T.ASSIGNED_INTERVENTION),
        _row(ERK.FAILURE_MODES, _G.BIAS_AND_LEAKAGE,            "-C-C--", _T.RELIABILITY_CLAIMED, _T.SAFETY_RELEVANT),
        _row(ERK.TRAIN_TEST_SEPARATION, _G.BIAS_AND_LEAKAGE,    "--R---"),
        _row(ERK.TEST_SET_INDEPENDENCE, _G.BIAS_AND_LEAKAGE,    "--R---"),
        _row(ERK.DUPLICATE_LEAKAGE_CONTROL, _G.BIAS_AND_LEAKAGE, "--R---"),
        _row(ERK.TUNING_ISOLATION, _G.BIAS_AND_LEAKAGE,         "--C---", _T.MODEL_TUNING_PERFORMED),
        _row(ERK.BENCHMARK_CONTAMINATION, _G.BIAS_AND_LEAKAGE,  "--C---", _T.PUBLIC_BENCHMARK_USED),
        _row(ERK.CLASS_IMBALANCE, _G.BIAS_AND_LEAKAGE,          "--C---", _T.IMBALANCED_LABELS),
        _row(ERK.CROSS_VALIDATION, _G.BIAS_AND_LEAKAGE,         "--O---"),
        _row(ERK.EXTERNAL_VALIDATION, _G.BIAS_AND_LEAKAGE,      "C-C---", _T.GENERALIZATION_CLAIMED),
        _row(ERK.ERROR_ANALYSIS, _G.BIAS_AND_LEAKAGE,           "--O---"),
        _row(ERK.SECURITY_TEST_CONDITIONS, _G.BIAS_AND_LEAKAGE, "---C--", _T.SECURITY_CLAIMED),
        _row(ERK.PROTOCOL_DETAIL, _G.REPRODUCIBILITY,           "RRRRRR"),
        _row(ERK.VERSION_INFORMATION, _G.REPRODUCIBILITY,       "OORRRO"),
        _row(ERK.SAFETY_CONTROLS, _G.SAFETY_AND_ETHICS,         "CCCCCC", _T.SAFETY_RELEVANT),
        _row(ERK.HUMAN_ANIMAL_DATA_CONSTRAINTS, _G.SAFETY_AND_ETHICS, "CCCCCC",
             _T.HUMAN_PARTICIPANTS, _T.ANIMAL_SUBJECTS),
        _row(ERK.PRIVACY_CONSTRAINTS, _G.SAFETY_AND_ETHICS,     "CCCCCC", _T.PERSONAL_DATA_PROCESSED),
    )
}

if set(EXPERIMENT_CATALOG) != set(ExperimentRequirementKind):  # pragma: no cover - import-time guard
    raise RuntimeError("every requirement kind has exactly one catalog row")

TYPE_OVERRIDES: dict[ExperimentType, dict[ExperimentRequirementKind, Applicability]] = {
    _X.SCIENTIFIC_CONTROLLED_EXPERIMENT: {ERK.CONTROL_STRATEGY: Applicability.REQUIRED},
    _X.SCIENTIFIC_OBSERVATIONAL_STUDY: {ERK.RANDOMIZATION: Applicability.NOT_APPLICABLE},
    _X.ENGINEERING_FIELD_TEST: {ERK.OPERATING_CONDITIONS: Applicability.REQUIRED},
    _X.ENGINEERING_STRESS_TEST: {ERK.STRESS_AND_EDGE_CASES: Applicability.REQUIRED,
                                 ERK.FAILURE_MODES: Applicability.REQUIRED},
    _X.ENGINEERING_COMPARATIVE_TEST: {ERK.BASELINE: Applicability.REQUIRED,
                                      ERK.BASELINE_CONFIGURATION: Applicability.REQUIRED},
    _X.AI_ML_ABLATION: {ERK.INDEPENDENT_VARIABLE: Applicability.REQUIRED,
                        ERK.CONTROLLED_VARIABLES: Applicability.REQUIRED},
    _X.AI_ML_EXTERNAL_VALIDATION: {ERK.EXTERNAL_VALIDATION: Applicability.REQUIRED},
    _X.SOFTWARE_BENCHMARK: {ERK.WORKLOAD: Applicability.REQUIRED, ERK.WARM_UP: Applicability.REQUIRED},
    _X.SOFTWARE_LOAD_TEST: {ERK.WORKLOAD: Applicability.REQUIRED, ERK.WARM_UP: Applicability.REQUIRED},
    _X.SOFTWARE_SECURITY_TEST: {ERK.SECURITY_TEST_CONDITIONS: Applicability.REQUIRED},
    _X.SOFTWARE_USABILITY_TEST: {ERK.INCLUSION_EXCLUSION_RULES: Applicability.REQUIRED},
}
"""Type-specific catalog policy. An override never lowers a REQUIRED cell."""

for _type, _over in TYPE_OVERRIDES.items():  # pragma: no cover - import-time guard
    for _kind, _app in _over.items():
        _cell = EXPERIMENT_CATALOG[_kind].defaults[TYPE_FAMILY[_type]]  # type: ignore[index]
        if _cell is Applicability.REQUIRED and _app is not Applicability.REQUIRED:
            raise RuntimeError("a type override never lowers a REQUIRED cell")


class ApplicabilityBasis(StrEnum):
    CATALOG_DEFAULT = "CATALOG_DEFAULT"
    CATALOG_TYPE_OVERRIDE = "CATALOG_TYPE_OVERRIDE"
    DETERMINISTIC_TRIGGER = "DETERMINISTIC_TRIGGER"
    PHASE_2J_VALIDATION_REQUIREMENT = "PHASE_2J_VALIDATION_REQUIREMENT"
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    CONDITION_UNRESOLVED = "CONDITION_UNRESOLVED"
    EXPERIMENT_TYPE_UNKNOWN = "EXPERIMENT_TYPE_UNKNOWN"


def resolve_applicability(
    kind: ExperimentRequirementKind,
    experiment_type: ExperimentType,
    triggers: frozenset[ExperimentTrigger] | None,
) -> tuple[Applicability, ApplicabilityBasis]:
    """Deterministic applicability. ``triggers=None`` leaves a CONDITIONAL cell
    unresolved: never REQUIRED and never NOT_APPLICABLE by default. An UNKNOWN type
    keeps only the universally required rows REQUIRED; every other row stays
    CONDITIONAL, so a model can never make a row optional by misclassifying."""
    entry = EXPERIMENT_CATALOG[kind]
    family = TYPE_FAMILY[experiment_type]
    if family is None:
        if entry.universally_required:
            return Applicability.REQUIRED, ApplicabilityBasis.EXPERIMENT_TYPE_UNKNOWN
        return Applicability.CONDITIONAL, ApplicabilityBasis.EXPERIMENT_TYPE_UNKNOWN
    override = TYPE_OVERRIDES.get(experiment_type, {}).get(kind)
    if override is not None:
        return override, ApplicabilityBasis.CATALOG_TYPE_OVERRIDE
    cell = entry.defaults[family]
    if cell is not Applicability.CONDITIONAL:
        return cell, ApplicabilityBasis.CATALOG_DEFAULT
    if triggers is None:
        return Applicability.CONDITIONAL, ApplicabilityBasis.CONDITION_UNRESOLVED
    if set(entry.triggers) & triggers:
        return Applicability.REQUIRED, ApplicabilityBasis.DETERMINISTIC_TRIGGER
    return Applicability.NOT_APPLICABLE, ApplicabilityBasis.DETERMINISTIC_TRIGGER


# ---------------------------------------------------------------------------
# Source binding, the result quarantine and the execution boundary (sections 23, 24)
# ---------------------------------------------------------------------------


class ExecutionStatus(StrEnum):
    PLANNED_ONLY = "PLANNED_ONLY"
    EXECUTION_DESCRIBED = "EXECUTION_DESCRIBED"
    EXECUTION_STATUS_NOT_DOCUMENTED = "EXECUTION_STATUS_NOT_DOCUMENTED"


class StudentExperimentExcerpt(MawhibaModel):
    """An exact protocol span of the verbatim submission, sliced by code."""

    excerpt_id: UUID
    experiment_run_id: UUID
    submission_artifact_id: UUID
    submission_content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    excerpt: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    occurrence_index: int = Field(ge=1)
    occurrence_resolution: OccurrenceResolution
    execution_verified: Literal[False] = False
    verifier_version: str = EXPERIMENT_ANCHOR_VERIFIER_VERSION

    @model_validator(mode="after")
    def _exact(self) -> StudentExperimentExcerpt:
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


class QuarantineKind(StrEnum):
    REPORTED_METRIC_VALUE = "REPORTED_METRIC_VALUE"
    STATISTICAL_OUTCOME = "STATISTICAL_OUTCOME"
    RESULT_TABLE = "RESULT_TABLE"
    CONCLUSION = "CONCLUSION"
    SUCCESS_OR_FAILURE_STATEMENT = "SUCCESS_OR_FAILURE_STATEMENT"
    CAUSAL_OR_GENERALIZATION_STATEMENT = "CAUSAL_OR_GENERALIZATION_STATEMENT"
    NEGATIVE_OUTCOME_STATEMENT = "NEGATIVE_OUTCOME_STATEMENT"


class QuarantinedSpan(MawhibaModel):
    """A bounded reference for Result Review: offsets and a hash, never the text.

    Nothing in Phase 3B reads it. No derivation function takes it as an argument,
    and ``adequacy_fingerprint`` excludes it (section 23)."""

    span_id: UUID
    experiment_run_id: UUID
    kind: QuarantineKind
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    span_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    consumed_by_phase3b: Literal[False] = False

    @model_validator(mode="after")
    def _span(self) -> QuarantinedSpan:
        if self.end <= self.start:
            raise ValueError("a quarantined span is non-empty")
        return self


# ---------------------------------------------------------------------------
# Requirement documentation and protocol adequacy (sections 25, 14)
# ---------------------------------------------------------------------------


class ProtocolAdequacy(StrEnum):
    ADEQUATELY_SPECIFIED_FOR_REVIEW = "ADEQUATELY_SPECIFIED_FOR_REVIEW"
    PARTIALLY_SPECIFIED = "PARTIALLY_SPECIFIED"
    PROTOCOL_RISK_IDENTIFIED = "PROTOCOL_RISK_IDENTIFIED"
    CONFLICTING_PROTOCOL = "CONFLICTING_PROTOCOL"
    INSUFFICIENT_EVIDENCE_TO_ASSESS = "INSUFFICIENT_EVIDENCE_TO_ASSESS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_DS = DocumentationStatus
_PA = ProtocolAdequacy
_DOC_WITH_EXCERPTS = {_DS.EXPLICITLY_DOCUMENTED, _DS.PARTIALLY_DOCUMENTED}
_DOC_WITHOUT_EXCERPTS = {_DS.NOT_DOCUMENTED_IN_BOUND_INPUT, _DS.NOT_APPLICABLE, _DS.INSUFFICIENT_SOURCE_COVERAGE}
ALLOWED_ADEQUACY: dict[DocumentationStatus, frozenset[ProtocolAdequacy]] = {
    _DS.EXPLICITLY_DOCUMENTED: frozenset(
        {_PA.ADEQUATELY_SPECIFIED_FOR_REVIEW, _PA.PARTIALLY_SPECIFIED, _PA.PROTOCOL_RISK_IDENTIFIED}
    ),
    _DS.PARTIALLY_DOCUMENTED: frozenset({_PA.PARTIALLY_SPECIFIED, _PA.PROTOCOL_RISK_IDENTIFIED}),
    _DS.CONFLICTING_DOCUMENTATION: frozenset({_PA.CONFLICTING_PROTOCOL}),
    _DS.NOT_DOCUMENTED_IN_BOUND_INPUT: frozenset({_PA.INSUFFICIENT_EVIDENCE_TO_ASSESS, _PA.PROTOCOL_RISK_IDENTIFIED}),
    _DS.INSUFFICIENT_SOURCE_COVERAGE: frozenset({_PA.INSUFFICIENT_EVIDENCE_TO_ASSESS}),
    _DS.NOT_APPLICABLE: frozenset({_PA.NOT_APPLICABLE}),
}

BARE_QUANTITY = re.compile(r"^[\s\W\d_]*(?:n|N)?[\s\W\d_]*$")
"""An excerpt with no word other than an optional ``n``: "N = 500", "500", "(n=30)"."""


class ExperimentRequirement(MawhibaModel):
    """One catalog requirement for one experiment: applicability, documentation and
    adequacy on three separate fields. The kind is an enum member, so a model can
    never introduce a requirement the catalog does not define."""

    experiment_run_id: UUID
    experiment_id: UUID
    kind: ExperimentRequirementKind
    applicability: Applicability
    basis: ApplicabilityBasis
    triggers: list[ExperimentTrigger] = Field(default_factory=list)
    judgment_excerpt_ids: list[UUID] = Field(default_factory=list)
    documentation: DocumentationStatus
    adequacy: ProtocolAdequacy
    excerpt_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounded(self) -> ExperimentRequirement:
        entry = EXPERIMENT_CATALOG[self.kind]
        if self.basis is ApplicabilityBasis.CATALOG_DEFAULT and Applicability.CONDITIONAL is self.applicability:
            raise ValueError("a CATALOG_DEFAULT is never CONDITIONAL (that is CONDITION_UNRESOLVED)")
        resolving = (ApplicabilityBasis.DETERMINISTIC_TRIGGER, ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,
                     ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT)
        if self.basis in resolving:
            if self.applicability not in (Applicability.REQUIRED, Applicability.NOT_APPLICABLE):
                raise ValueError("a resolution ends REQUIRED or NOT_APPLICABLE")
            if not set(self.triggers) <= set(entry.triggers):
                raise ValueError("a trigger outside the requirement's catalog triggers")
            if (self.applicability is Applicability.REQUIRED) != bool(self.triggers):
                raise ValueError("REQUIRED by resolution names the trigger(s) that fired, and only then")
        elif self.triggers:
            raise ValueError("only a resolution names triggers")
        if self.basis is ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT and not self.judgment_excerpt_ids:
            raise ValueError("a model-assisted applicability judgment binds its source context (never omission)")
        if self.basis is ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT and not (
            set(self.triggers) & {_T.PHASE_2J_BASELINE_REQUIRED, _T.PHASE_2J_MATERIAL_CONDITION}
        ):
            raise ValueError("a Phase 2J resolution names a Phase 2J trigger")
        if self.basis is ApplicabilityBasis.CONDITION_UNRESOLVED and self.applicability is not Applicability.CONDITIONAL:
            raise ValueError("an unresolved condition stays CONDITIONAL")
        n = len(set(self.excerpt_ids))
        if n != len(self.excerpt_ids):
            raise ValueError("an excerpt is cited once")
        if (self.applicability is Applicability.NOT_APPLICABLE) != (self.documentation is _DS.NOT_APPLICABLE):
            raise ValueError("documentation is NOT_APPLICABLE exactly when the requirement is")
        if self.documentation in _DOC_WITH_EXCERPTS and n < 1:
            raise ValueError("documented requires a bound excerpt")
        if self.documentation is _DS.CONFLICTING_DOCUMENTATION and n < 2:
            raise ValueError("conflicting documentation cites both sides")
        if self.documentation in _DOC_WITHOUT_EXCERPTS and n:
            raise ValueError(f"{self.documentation.value} cites no excerpt")
        if self.adequacy not in ALLOWED_ADEQUACY[self.documentation]:
            raise ValueError(f"{self.adequacy.value} is not reachable from {self.documentation.value}")
        return self


# ---------------------------------------------------------------------------
# Measurement, baseline and condition records (sections 12, 13, 22)
# ---------------------------------------------------------------------------


class MetricTargetAlignment(StrEnum):
    ALIGNED_SAME_TARGET = "ALIGNED_SAME_TARGET"
    METRIC_TARGET_MISMATCH = "METRIC_TARGET_MISMATCH"
    METRIC_NOT_DEFINED = "METRIC_NOT_DEFINED"
    MEASUREMENT_METHOD_NOT_DEFINED = "MEASUREMENT_METHOD_NOT_DEFINED"
    ALIGNMENT_UNRESOLVED = "ALIGNMENT_UNRESOLVED"


class Phase2JAnchorMatch(StrEnum):
    """How an experiment's metric or baseline relates to the Phase 2J anchor of the same target."""

    SAME_AS_PHASE_2J = "SAME_AS_PHASE_2J"
    DIFFERENT_FROM_PHASE_2J = "DIFFERENT_FROM_PHASE_2J"
    NO_PHASE_2J_ANCHOR = "NO_PHASE_2J_ANCHOR"
    MATCH_UNRESOLVED = "MATCH_UNRESOLVED"


class SuccessCriterionTiming(StrEnum):
    PRE_SPECIFIED_AS_DESCRIBED = "PRE_SPECIFIED_AS_DESCRIBED"
    POST_HOC_AS_DESCRIBED = "POST_HOC_AS_DESCRIBED"
    TIMING_NOT_DOCUMENTED = "TIMING_NOT_DOCUMENTED"


class MeasurementBinding(MawhibaModel):
    """method -> metric -> target -> success criterion, for ONE experiment and ONE target.

    There is no free-text metric field and no value field: each link is an exact
    excerpt id. Whether the metric is *aligned* is a bounded judgment; that it
    belongs to *this* target is structural (the run validator)."""

    binding_id: UUID
    experiment_run_id: UUID
    experiment_id: UUID
    target_claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    gap_hypothesis_id: UUID | None = None
    validation_requirement_id: UUID | None = None
    method_excerpt_id: UUID | None = None
    metric_excerpt_id: UUID | None = None
    unit_excerpt_id: UUID | None = None
    success_criterion_excerpt_id: UUID | None = None
    success_criterion_timing: SuccessCriterionTiming = SuccessCriterionTiming.TIMING_NOT_DOCUMENTED
    alignment: MetricTargetAlignment
    phase2j_metric_match: Phase2JAnchorMatch
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _chain(self) -> MeasurementBinding:
        if self.validation_requirement_id is not None and self.gap_hypothesis_id is None:
            raise ValueError("a Phase 2J requirement is reached through its hypothesis")
        if (self.validation_requirement_id is None) != (self.phase2j_metric_match is Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR):
            raise ValueError("NO_PHASE_2J_ANCHOR exactly when no Phase 2J requirement is bound")
        if self.alignment is MetricTargetAlignment.ALIGNED_SAME_TARGET and (
            self.method_excerpt_id is None or self.metric_excerpt_id is None
        ):
            raise ValueError("alignment needs a bound measurement method and a bound metric (a name is not enough)")
        if self.alignment is MetricTargetAlignment.METRIC_NOT_DEFINED and self.metric_excerpt_id is not None:
            raise ValueError("METRIC_NOT_DEFINED binds no metric")
        if self.alignment is MetricTargetAlignment.MEASUREMENT_METHOD_NOT_DEFINED and self.method_excerpt_id is not None:
            raise ValueError("MEASUREMENT_METHOD_NOT_DEFINED binds no method")
        if self.alignment is MetricTargetAlignment.METRIC_TARGET_MISMATCH and self.metric_excerpt_id is None:
            raise ValueError("a mismatch needs a metric to mismatch")
        if self.phase2j_metric_match is Phase2JAnchorMatch.SAME_AS_PHASE_2J and (
            self.alignment is not MetricTargetAlignment.ALIGNED_SAME_TARGET
        ):
            raise ValueError("the Phase 2J metric is matched only by an aligned metric of the same target")
        if self.success_criterion_excerpt_id is None and (
            self.success_criterion_timing is not SuccessCriterionTiming.TIMING_NOT_DOCUMENTED
        ):
            raise ValueError("a criterion's timing needs the criterion")
        return self


class FairnessProperty(StrEnum):
    SAME_INPUT_SET = "SAME_INPUT_SET"
    SAME_ENVIRONMENT = "SAME_ENVIRONMENT"
    SAME_HARDWARE = "SAME_HARDWARE"
    SAME_PREPROCESSING = "SAME_PREPROCESSING"
    SAME_EVALUATION_METRIC = "SAME_EVALUATION_METRIC"
    EQUIVALENT_RESOURCE_CONSTRAINTS = "EQUIVALENT_RESOURCE_CONSTRAINTS"
    EQUIVALENT_TUNING_OPPORTUNITY = "EQUIVALENT_TUNING_OPPORTUNITY"


class FairnessPropertyStatus(StrEnum):
    DOCUMENTED_SAME = "DOCUMENTED_SAME"
    DOCUMENTED_DIFFERENT = "DOCUMENTED_DIFFERENT"
    NOT_DOCUMENTED = "NOT_DOCUMENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class FairnessBasis(StrEnum):
    DETERMINISTIC_SHARED_METRIC_BINDING = "DETERMINISTIC_SHARED_METRIC_BINDING"
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    NONE = "NONE"


FAIRNESS_REQUIRED_BY_FAMILY: dict[ExperimentFamily, frozenset[FairnessProperty]] = {
    _F.SCIENTIFIC: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_ENVIRONMENT,
                              FairnessProperty.SAME_EVALUATION_METRIC}),
    _F.ENGINEERING: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_ENVIRONMENT,
                               FairnessProperty.SAME_HARDWARE, FairnessProperty.SAME_EVALUATION_METRIC}),
    _F.AI_ML: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_PREPROCESSING,
                         FairnessProperty.SAME_EVALUATION_METRIC, FairnessProperty.EQUIVALENT_TUNING_OPPORTUNITY}),
    _F.SOFTWARE: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_ENVIRONMENT,
                            FairnessProperty.SAME_HARDWARE, FairnessProperty.SAME_EVALUATION_METRIC,
                            FairnessProperty.EQUIVALENT_RESOURCE_CONSTRAINTS}),
    _F.SIMULATION: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_EVALUATION_METRIC}),
    _F.OTHER: frozenset({FairnessProperty.SAME_INPUT_SET, FairnessProperty.SAME_EVALUATION_METRIC}),
}


class FairnessPropertyAssessment(MawhibaModel):
    property: FairnessProperty
    status: FairnessPropertyStatus
    basis: FairnessBasis
    excerpt_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> FairnessPropertyAssessment:
        documented = self.status in (FairnessPropertyStatus.DOCUMENTED_SAME, FairnessPropertyStatus.DOCUMENTED_DIFFERENT)
        if documented != bool(self.excerpt_ids):
            raise ValueError("a documented comparability property cites its excerpt, and only then")
        if self.basis is FairnessBasis.DETERMINISTIC_SHARED_METRIC_BINDING and (
            self.property is not FairnessProperty.SAME_EVALUATION_METRIC
        ):
            raise ValueError("only metric identity is deterministically provable; every other property is judged")
        if (self.basis is FairnessBasis.NONE) != (
            self.status in (FairnessPropertyStatus.NOT_DOCUMENTED, FairnessPropertyStatus.NOT_APPLICABLE)
        ):
            raise ValueError("an undocumented or inapplicable property has no basis, and only it")
        return self


class ComparabilityRollup(StrEnum):
    """Never ``FAIR``: documented comparability is not a fair execution."""

    NO_BASELINE_DOCUMENTED = "NO_BASELINE_DOCUMENTED"
    COMPARABILITY_DOCUMENTED_FOR_REQUIRED_PROPERTIES = "COMPARABILITY_DOCUMENTED_FOR_REQUIRED_PROPERTIES"
    COMPARABILITY_GAP_DOCUMENTED = "COMPARABILITY_GAP_DOCUMENTED"
    COMPARABILITY_NOT_ESTABLISHED = "COMPARABILITY_NOT_ESTABLISHED"


class ExperimentBaselineRecord(MawhibaModel):
    """Six layers, never collapsed (section 12):

        baseline documented            baseline_excerpt_ids
        baseline relevant              relevance (bounded judgment)
        configured comparably          comparability, per property
        baseline execution described   execution_status
        baseline execution verified    execution_verified = False (literal)
        baseline result                comparison_result_evaluated = False (Result Review)
    """

    record_id: UUID
    experiment_run_id: UUID
    experiment_id: UUID
    target_claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    gap_hypothesis_id: UUID | None = None
    validation_requirement_id: UUID | None = None
    baseline_excerpt_ids: list[UUID] = Field(default_factory=list)
    relevance: BaselineRelevance
    phase2j_baseline_match: Phase2JAnchorMatch
    comparability: list[FairnessPropertyAssessment] = Field(default_factory=list)
    execution_status: ExecutionStatus = ExecutionStatus.EXECUTION_STATUS_NOT_DOCUMENTED
    execution_verified: Literal[False] = False
    comparison_result_evaluated: Literal[False] = False
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _layers(self) -> ExperimentBaselineRecord:
        named = bool(self.baseline_excerpt_ids)
        if (self.relevance is BaselineRelevance.NO_BASELINE_DOCUMENTED) == named:
            raise ValueError("NO_BASELINE_DOCUMENTED exactly when no baseline excerpt is bound")
        if not named and self.comparability:
            raise ValueError("no comparability without a documented baseline")
        if len({p.property for p in self.comparability}) != len(self.comparability):
            raise ValueError("a comparability property is assessed once")
        if self.validation_requirement_id is not None and self.gap_hypothesis_id is None:
            raise ValueError("a Phase 2J requirement is reached through its hypothesis")
        if self.phase2j_baseline_match is Phase2JAnchorMatch.SAME_AS_PHASE_2J and not named:
            raise ValueError("matching the Phase 2J baseline needs a documented baseline")
        return self

    def rollup(self, family: ExperimentFamily | None) -> ComparabilityRollup:
        """Derived in code. Baseline named is never baseline fair."""
        if not self.baseline_excerpt_ids:
            return ComparabilityRollup.NO_BASELINE_DOCUMENTED
        statuses = {p.property: p.status for p in self.comparability}
        if FairnessPropertyStatus.DOCUMENTED_DIFFERENT in statuses.values():
            return ComparabilityRollup.COMPARABILITY_GAP_DOCUMENTED
        required = FAIRNESS_REQUIRED_BY_FAMILY[family] if family is not None else frozenset(FairnessProperty)
        if all(statuses.get(p) in (FairnessPropertyStatus.DOCUMENTED_SAME, FairnessPropertyStatus.NOT_APPLICABLE)
               for p in required):
            return ComparabilityRollup.COMPARABILITY_DOCUMENTED_FOR_REQUIRED_PROPERTIES
        return ComparabilityRollup.COMPARABILITY_NOT_ESTABLISHED


class ConditionCoverageStatus(StrEnum):
    ADDRESSED_IN_PROTOCOL = "ADDRESSED_IN_PROTOCOL"
    PARTIALLY_ADDRESSED = "PARTIALLY_ADDRESSED"
    NOT_ADDRESSED_IN_BOUND_INPUT = "NOT_ADDRESSED_IN_BOUND_INPUT"


class ConditionCoverage(MawhibaModel):
    """A Phase 2J material condition, by id, for one experiment. No condition text is stored."""

    experiment_run_id: UUID
    experiment_id: UUID
    validation_requirement_id: UUID
    condition_id: UUID
    status: ConditionCoverageStatus
    excerpt_ids: list[UUID] = Field(default_factory=list)
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _bound(self) -> ConditionCoverage:
        if (self.status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT) == bool(self.excerpt_ids):
            raise ValueError("an addressed condition cites its excerpt; an unaddressed one cites none")
        return self


# ---------------------------------------------------------------------------
# Target linkage (section 21)
# ---------------------------------------------------------------------------


class TargetRelation(StrEnum):
    DIRECTLY_TESTS = "DIRECTLY_TESTS"
    PARTIALLY_TESTS = "PARTIALLY_TESTS"
    SUPPORTING_VALIDATION = "SUPPORTING_VALIDATION"
    DOES_NOT_TEST = "DOES_NOT_TEST"
    UNRESOLVED = "UNRESOLVED"


TESTING_RELATIONS = frozenset({TargetRelation.DIRECTLY_TESTS, TargetRelation.PARTIALLY_TESTS})


class ExperimentTargetLink(MawhibaModel):
    """experiment -> claim -> Phase 2J hypothesis -> Phase 2J validation requirement.

    IDs and hashes are verified; the relation's semantics are a bounded model
    judgment. The run validator requires a ``DIRECTLY_TESTS`` link to rest on an
    aligned measurement binding of the same experiment AND the same target, so a
    shared keyword or a shared metric of another target can never carry it."""

    link_id: UUID
    experiment_run_id: UUID
    experiment_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    gap_hypothesis_id: UUID | None = None
    validation_requirement_id: UUID | None = None
    relation: TargetRelation
    excerpt_ids: list[UUID] = Field(default_factory=list)
    judgment_basis: Literal["MODEL_ASSISTED_BOUNDED_JUDGMENT"] = MODEL_ASSISTED_BOUNDED_JUDGMENT

    @model_validator(mode="after")
    def _shape(self) -> ExperimentTargetLink:
        if self.validation_requirement_id is not None and self.gap_hypothesis_id is None:
            raise ValueError("a Phase 2J requirement is reached through its hypothesis")
        if self.relation in TESTING_RELATIONS and not self.excerpt_ids:
            raise ValueError("a testing relation cites the protocol excerpt that tests")
        return self

    @property
    def target_key(self) -> tuple[str, UUID | None, UUID | None]:
        return (self.claim_id, self.gap_hypothesis_id, self.validation_requirement_id)


# ---------------------------------------------------------------------------
# Issues, experiment identity, posture and deterministic synthesis (sections 26, 27)
# ---------------------------------------------------------------------------


class ExperimentIssueCode(StrEnum):
    OBJECTIVE_MISSING = "OBJECTIVE_MISSING"
    TARGET_NOT_BOUND = "TARGET_NOT_BOUND"
    SETUP_MISSING = "SETUP_MISSING"
    INPUTS_MISSING = "INPUTS_MISSING"
    OUTPUTS_MISSING = "OUTPUTS_MISSING"
    VARIABLES_MISSING = "VARIABLES_MISSING"
    CONTROL_MISSING_WHEN_REQUIRED = "CONTROL_MISSING_WHEN_REQUIRED"
    BASELINE_MISSING_WHEN_REQUIRED = "BASELINE_MISSING_WHEN_REQUIRED"
    SAMPLE_MISSING = "SAMPLE_MISSING"
    REPETITIONS_MISSING_WHEN_REQUIRED = "REPETITIONS_MISSING_WHEN_REQUIRED"
    ENVIRONMENT_MISSING = "ENVIRONMENT_MISSING"
    MEASUREMENT_METHOD_MISSING = "MEASUREMENT_METHOD_MISSING"
    METRIC_MISSING = "METRIC_MISSING"
    SUCCESS_CRITERION_MISSING = "SUCCESS_CRITERION_MISSING"
    ERROR_SOURCES_MISSING_WHEN_REQUIRED = "ERROR_SOURCES_MISSING_WHEN_REQUIRED"
    BIAS_NOT_ADDRESSED_WHEN_REQUIRED = "BIAS_NOT_ADDRESSED_WHEN_REQUIRED"
    ML_LEAKAGE_CONTROL_MISSING = "ML_LEAKAGE_CONTROL_MISSING"
    STATISTICS_MISSING_WHEN_REQUIRED = "STATISTICS_MISSING_WHEN_REQUIRED"
    SAFETY_OR_ETHICS_CONTROL_MISSING = "SAFETY_OR_ETHICS_CONTROL_MISSING"
    REPRODUCIBILITY_INSUFFICIENT = "REPRODUCIBILITY_INSUFFICIENT"
    REQUIRED_PROTOCOL_ELEMENT_MISSING = "REQUIRED_PROTOCOL_ELEMENT_MISSING"
    PROTOCOL_RISK_IDENTIFIED = "PROTOCOL_RISK_IDENTIFIED"
    CONFLICTING_PROTOCOL_DESCRIPTION = "CONFLICTING_PROTOCOL_DESCRIPTION"
    METRIC_TARGET_MISMATCH = "METRIC_TARGET_MISMATCH"
    BASELINE_NOT_RELEVANT = "BASELINE_NOT_RELEVANT"
    BASELINE_COMPARABILITY_GAP = "BASELINE_COMPARABILITY_GAP"
    SUCCESS_CRITERION_POST_HOC = "SUCCESS_CRITERION_POST_HOC"
    EXPERIMENT_DOES_NOT_TEST_TARGET = "EXPERIMENT_DOES_NOT_TEST_TARGET"


ISSUE_SEVERITY: dict[ExperimentIssueCode, Severity] = {
    ExperimentIssueCode.OBJECTIVE_MISSING: Severity.HIGH,
    ExperimentIssueCode.TARGET_NOT_BOUND: Severity.HIGH,
    ExperimentIssueCode.SETUP_MISSING: Severity.HIGH,
    ExperimentIssueCode.INPUTS_MISSING: Severity.HIGH,
    ExperimentIssueCode.OUTPUTS_MISSING: Severity.MEDIUM,
    ExperimentIssueCode.VARIABLES_MISSING: Severity.HIGH,
    ExperimentIssueCode.CONTROL_MISSING_WHEN_REQUIRED: Severity.HIGH,
    ExperimentIssueCode.BASELINE_MISSING_WHEN_REQUIRED: Severity.HIGH,
    ExperimentIssueCode.SAMPLE_MISSING: Severity.HIGH,
    ExperimentIssueCode.REPETITIONS_MISSING_WHEN_REQUIRED: Severity.HIGH,
    ExperimentIssueCode.ENVIRONMENT_MISSING: Severity.MEDIUM,
    ExperimentIssueCode.MEASUREMENT_METHOD_MISSING: Severity.HIGH,
    ExperimentIssueCode.METRIC_MISSING: Severity.HIGH,
    ExperimentIssueCode.SUCCESS_CRITERION_MISSING: Severity.HIGH,
    ExperimentIssueCode.ERROR_SOURCES_MISSING_WHEN_REQUIRED: Severity.MEDIUM,
    ExperimentIssueCode.BIAS_NOT_ADDRESSED_WHEN_REQUIRED: Severity.MEDIUM,
    ExperimentIssueCode.ML_LEAKAGE_CONTROL_MISSING: Severity.HIGH,
    ExperimentIssueCode.STATISTICS_MISSING_WHEN_REQUIRED: Severity.MEDIUM,
    ExperimentIssueCode.SAFETY_OR_ETHICS_CONTROL_MISSING: Severity.HIGH,
    ExperimentIssueCode.REPRODUCIBILITY_INSUFFICIENT: Severity.LOW,
    ExperimentIssueCode.REQUIRED_PROTOCOL_ELEMENT_MISSING: Severity.MEDIUM,
    ExperimentIssueCode.PROTOCOL_RISK_IDENTIFIED: Severity.MEDIUM,
    ExperimentIssueCode.CONFLICTING_PROTOCOL_DESCRIPTION: Severity.HIGH,
    ExperimentIssueCode.METRIC_TARGET_MISMATCH: Severity.HIGH,
    ExperimentIssueCode.BASELINE_NOT_RELEVANT: Severity.MEDIUM,
    ExperimentIssueCode.BASELINE_COMPARABILITY_GAP: Severity.MEDIUM,
    ExperimentIssueCode.SUCCESS_CRITERION_POST_HOC: Severity.HIGH,
    ExperimentIssueCode.EXPERIMENT_DOES_NOT_TEST_TARGET: Severity.MEDIUM,
}
"""Severity is a function of the issue class alone, never of model prose."""

if set(ISSUE_SEVERITY) != set(ExperimentIssueCode):  # pragma: no cover - import-time guard
    raise RuntimeError("every issue code has a fixed severity")

_I = ExperimentIssueCode
MISSING_REQUIREMENT_ISSUE: dict[ExperimentRequirementKind, ExperimentIssueCode] = {
    ERK.OBJECTIVE: _I.OBJECTIVE_MISSING,
    ERK.HYPOTHESIS_OR_VALIDATION_OBJECTIVE: _I.OBJECTIVE_MISSING,
    ERK.TARGET_BINDING: _I.TARGET_NOT_BOUND,
    ERK.REQUIREMENT_TRACEABILITY: _I.TARGET_NOT_BOUND,
    ERK.SUCCESS_CRITERION: _I.SUCCESS_CRITERION_MISSING,
    ERK.SETUP: _I.SETUP_MISSING,
    ERK.CONFIGURATION: _I.SETUP_MISSING,
    ERK.ENVIRONMENT: _I.ENVIRONMENT_MISSING,
    ERK.OPERATING_CONDITIONS: _I.ENVIRONMENT_MISSING,
    ERK.INPUTS: _I.INPUTS_MISSING,
    ERK.WORKLOAD: _I.INPUTS_MISSING,
    ERK.OUTPUTS: _I.OUTPUTS_MISSING,
    ERK.INDEPENDENT_VARIABLE: _I.VARIABLES_MISSING,
    ERK.DEPENDENT_VARIABLE: _I.VARIABLES_MISSING,
    ERK.CONTROLLED_VARIABLES: _I.VARIABLES_MISSING,
    ERK.CONTROL_STRATEGY: _I.CONTROL_MISSING_WHEN_REQUIRED,
    ERK.INTERVENTION_COMPARATOR_SEPARATION: _I.CONTROL_MISSING_WHEN_REQUIRED,
    ERK.BASELINE: _I.BASELINE_MISSING_WHEN_REQUIRED,
    ERK.BASELINE_CONFIGURATION: _I.BASELINE_MISSING_WHEN_REQUIRED,
    ERK.SAMPLE_DEFINITION: _I.SAMPLE_MISSING,
    ERK.SAMPLE_SIZE: _I.SAMPLE_MISSING,
    ERK.REPETITIONS: _I.REPETITIONS_MISSING_WHEN_REQUIRED,
    ERK.REPETITION_INDEPENDENCE: _I.REPETITIONS_MISSING_WHEN_REQUIRED,
    ERK.MEASUREMENT_METHOD: _I.MEASUREMENT_METHOD_MISSING,
    ERK.INSTRUMENT: _I.MEASUREMENT_METHOD_MISSING,
    ERK.METRIC: _I.METRIC_MISSING,
    ERK.MEASUREMENT_UNCERTAINTY: _I.ERROR_SOURCES_MISSING_WHEN_REQUIRED,
    ERK.CALIBRATION: _I.ERROR_SOURCES_MISSING_WHEN_REQUIRED,
    ERK.MEASUREMENT_RESOLUTION: _I.ERROR_SOURCES_MISSING_WHEN_REQUIRED,
    ERK.CONFOUNDERS: _I.BIAS_NOT_ADDRESSED_WHEN_REQUIRED,
    ERK.SELECTION_BIAS: _I.BIAS_NOT_ADDRESSED_WHEN_REQUIRED,
    ERK.MEASUREMENT_BIAS: _I.BIAS_NOT_ADDRESSED_WHEN_REQUIRED,
    ERK.BLINDING: _I.BIAS_NOT_ADDRESSED_WHEN_REQUIRED,
    ERK.RANDOMIZATION: _I.BIAS_NOT_ADDRESSED_WHEN_REQUIRED,
    ERK.TRAIN_TEST_SEPARATION: _I.ML_LEAKAGE_CONTROL_MISSING,
    ERK.TEST_SET_INDEPENDENCE: _I.ML_LEAKAGE_CONTROL_MISSING,
    ERK.DUPLICATE_LEAKAGE_CONTROL: _I.ML_LEAKAGE_CONTROL_MISSING,
    ERK.TUNING_ISOLATION: _I.ML_LEAKAGE_CONTROL_MISSING,
    ERK.BENCHMARK_CONTAMINATION: _I.ML_LEAKAGE_CONTROL_MISSING,
    ERK.DESCRIPTIVE_STATISTICS: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.CONFIDENCE_INTERVAL: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.EFFECT_SIZE: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.STATISTICAL_TEST: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.TEST_ASSUMPTIONS: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.MULTIPLE_COMPARISONS: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.OUTLIER_HANDLING: _I.STATISTICS_MISSING_WHEN_REQUIRED,
    ERK.SAFETY_CONTROLS: _I.SAFETY_OR_ETHICS_CONTROL_MISSING,
    ERK.HUMAN_ANIMAL_DATA_CONSTRAINTS: _I.SAFETY_OR_ETHICS_CONTROL_MISSING,
    ERK.PRIVACY_CONSTRAINTS: _I.SAFETY_OR_ETHICS_CONTROL_MISSING,
    ERK.PROTOCOL_DETAIL: _I.REPRODUCIBILITY_INSUFFICIENT,
    ERK.VERSION_INFORMATION: _I.REPRODUCIBILITY_INSUFFICIENT,
    ERK.SEED_OR_REPEATABILITY: _I.REPRODUCIBILITY_INSUFFICIENT,
}
"""A REQUIRED requirement NOT_DOCUMENTED_IN_BOUND_INPUT emits this code; any kind absent
here emits REQUIRED_PROTOCOL_ELEMENT_MISSING. This table is the emission path."""


class ExperimentPosture(StrEnum):
    WELL_SPECIFIED = "WELL_SPECIFIED"
    PARTIALLY_SPECIFIED = "PARTIALLY_SPECIFIED"
    MAJOR_GAPS = "MAJOR_GAPS"
    UNRESOLVED = "UNRESOLVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


POSTURE_PRECEDENCE: tuple[ExperimentPosture, ...] = (
    ExperimentPosture.INSUFFICIENT_EVIDENCE,
    ExperimentPosture.MAJOR_GAPS,
    ExperimentPosture.UNRESOLVED,
    ExperimentPosture.PARTIALLY_SPECIFIED,
    ExperimentPosture.WELL_SPECIFIED,
)
"""Worst first. Every aggregate is the worst member: there is no averaging."""


def worst(postures: list[ExperimentPosture]) -> ExperimentPosture:
    return min(postures, key=POSTURE_PRECEDENCE.index)


_MAJOR = frozenset({Severity.CRITICAL, Severity.HIGH})


def derive_experiment_issues(
    *,
    experiment_type: ExperimentType,
    requirements: list[ExperimentRequirement],
    measurements: list[MeasurementBinding],
    baselines: list[ExperimentBaselineRecord],
    links: list[ExperimentTargetLink],
) -> list[ExperimentIssueCode]:
    """The single issue rule for one experiment. It takes no quarantine, result or
    model-proposed issue argument: a reported value cannot raise or lower an issue."""
    codes: set[ExperimentIssueCode] = set()
    for r in requirements:
        if r.documentation is _DS.CONFLICTING_DOCUMENTATION:
            codes.add(_I.CONFLICTING_PROTOCOL_DESCRIPTION)
        if r.applicability is Applicability.REQUIRED and r.documentation is _DS.NOT_DOCUMENTED_IN_BOUND_INPUT:
            codes.add(MISSING_REQUIREMENT_ISSUE.get(r.kind, _I.REQUIRED_PROTOCOL_ELEMENT_MISSING))
        if r.applicability is not Applicability.NOT_APPLICABLE and r.adequacy is _PA.PROTOCOL_RISK_IDENTIFIED:
            codes.add(_I.PROTOCOL_RISK_IDENTIFIED)
    for m in measurements:
        if m.alignment is MetricTargetAlignment.METRIC_TARGET_MISMATCH:
            codes.add(_I.METRIC_TARGET_MISMATCH)
        if m.success_criterion_timing is SuccessCriterionTiming.POST_HOC_AS_DESCRIBED:
            codes.add(_I.SUCCESS_CRITERION_POST_HOC)
    family = TYPE_FAMILY[experiment_type]
    for b in baselines:
        if b.relevance is BaselineRelevance.NOT_RELEVANT_TO_TARGET:
            codes.add(_I.BASELINE_NOT_RELEVANT)
        if b.rollup(family) is ComparabilityRollup.COMPARABILITY_GAP_DOCUMENTED:
            codes.add(_I.BASELINE_COMPARABILITY_GAP)
    if links and all(link.relation is TargetRelation.DOES_NOT_TEST for link in links):
        codes.add(_I.EXPERIMENT_DOES_NOT_TEST_TARGET)
    return sorted(codes)


def derive_experiment_posture(
    *,
    experiment_type: ExperimentType,
    requirements: list[ExperimentRequirement],
    issues: list[ExperimentIssueCode],
    measurements: list[MeasurementBinding],
    links: list[ExperimentTargetLink],
) -> ExperimentPosture:
    """Exact precedence (section 26), worst first:

    1. INSUFFICIENT_EVIDENCE  every applicable requirement is INSUFFICIENT_SOURCE_COVERAGE
    2. MAJOR_GAPS             any HIGH/CRITICAL issue
    3. UNRESOLVED             UNKNOWN type, an unresolved CONDITIONAL requirement,
                              or only UNRESOLVED / ALIGNMENT_UNRESOLVED linkage
    4. PARTIALLY_SPECIFIED    any issue, any applicable REQUIRED requirement not
                              ADEQUATELY_SPECIFIED_FOR_REVIEW, or no aligned testing link
    5. WELL_SPECIFIED         otherwise
    """
    applicable = [r for r in requirements if r.applicability is not Applicability.NOT_APPLICABLE]
    if not applicable or all(r.documentation is _DS.INSUFFICIENT_SOURCE_COVERAGE for r in applicable):
        return ExperimentPosture.INSUFFICIENT_EVIDENCE
    if any(ISSUE_SEVERITY[i] in _MAJOR for i in issues):
        return ExperimentPosture.MAJOR_GAPS
    if (
        experiment_type is ExperimentType.UNKNOWN
        or any(r.applicability is Applicability.CONDITIONAL for r in requirements)
        or not links
        or all(link.relation is TargetRelation.UNRESOLVED for link in links)
    ):
        return ExperimentPosture.UNRESOLVED
    aligned_targets = {
        (m.target_claim_id, m.gap_hypothesis_id, m.validation_requirement_id)
        for m in measurements
        if m.alignment is MetricTargetAlignment.ALIGNED_SAME_TARGET
    }
    tested = any(
        link.relation is TargetRelation.DIRECTLY_TESTS and link.target_key in aligned_targets for link in links
    )
    if issues or not tested or any(
        r.applicability is Applicability.REQUIRED and r.adequacy is not _PA.ADEQUATELY_SPECIFIED_FOR_REVIEW
        for r in requirements
    ):
        return ExperimentPosture.PARTIALLY_SPECIFIED
    return ExperimentPosture.WELL_SPECIFIED


class TypeBasis(StrEnum):
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    UNRESOLVED = "UNRESOLVED"


class TrackOwnershipBasis(StrEnum):
    SINGLE_TRACK_PROJECT = "SINGLE_TRACK_PROJECT"
    PHASE_2J_LIMITATION_FACET = "PHASE_2J_LIMITATION_FACET"
    MODEL_ASSISTED_BOUNDED_JUDGMENT = "MODEL_ASSISTED_BOUNDED_JUDGMENT"
    UNRESOLVED = "UNRESOLVED"


def protocol_key(defining_texts: list[str]) -> str:
    """Identity of a protocol: the hash of its defining excerpt texts in document order.

    Offsets are excluded on purpose, so text added elsewhere in the submission (a
    changed result value, an extra paragraph) cannot change an experiment's identity.
    Identical defining text described twice is one experiment, never two."""
    return text_hash(json.dumps(defining_texts, ensure_ascii=False))


class ExperimentRecord(MawhibaModel):
    """One experiment. ``experiment_id = experiment_uuid(run, protocol_key)``.

    Targets are *not* part of identity: they are bound by separate links, so one
    experiment testing two claims stays one experiment (no double counting), and
    a later linkage change cannot rename an experiment. ``issues`` and ``posture``
    must equal the derivation over the records named here."""

    experiment_id: UUID
    experiment_run_id: UUID
    protocol_key: str = Field(pattern=CONTENT_HASH_PATTERN)
    defining_excerpt_ids: list[UUID] = Field(min_length=1)
    experiment_type: ExperimentType
    type_basis: TypeBasis
    track: MethodologyTrack | None
    ownership_basis: TrackOwnershipBasis
    ownership_excerpt_ids: list[UUID] = Field(default_factory=list)
    ownership_gap_hypothesis_ids: list[UUID] = Field(default_factory=list)
    revision_of: UUID | None = Field(
        default=None, description="A changed protocol of an earlier experiment is a new experiment that names it."
    )
    execution_status: ExecutionStatus = ExecutionStatus.EXECUTION_STATUS_NOT_DOCUMENTED
    execution_verified: Literal[False] = False
    independently_reproduced: Literal[False] = False
    leakage_prevented_in_practice: Literal[False] = False
    requirements: list[ExperimentRequirement] = Field(default_factory=list)
    issues: list[ExperimentIssueCode] = Field(default_factory=list)
    posture: ExperimentPosture
    policy_version: str = EXPERIMENT_SYNTHESIS_POLICY_VERSION

    @model_validator(mode="after")
    def _identity_and_derivation(self) -> ExperimentRecord:
        if self.experiment_id != experiment_uuid(self.experiment_run_id, self.protocol_key):
            raise ValueError("experiment_id is derived from the run and the protocol key, never chosen")
        if len(set(self.defining_excerpt_ids)) != len(self.defining_excerpt_ids):
            raise ValueError("a defining excerpt is listed once")
        if (self.type_basis is TypeBasis.UNRESOLVED) != (self.experiment_type is ExperimentType.UNKNOWN):
            raise ValueError("an UNKNOWN type is exactly an unresolved type judgment")
        if (self.track is None) != (self.ownership_basis is TrackOwnershipBasis.UNRESOLVED):
            raise ValueError("an experiment has one owner track unless its ownership is UNRESOLVED")
        if self.ownership_basis is TrackOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT and not self.ownership_excerpt_ids:
            raise ValueError("a judged ownership binds its excerpts")
        if self.ownership_basis is TrackOwnershipBasis.PHASE_2J_LIMITATION_FACET and not self.ownership_gap_hypothesis_ids:
            raise ValueError("facet ownership names the hypotheses whose facet decides it")
        if self.revision_of == self.experiment_id:
            raise ValueError("an experiment is not a revision of itself")
        kinds = [r.kind for r in self.requirements]
        if sorted(kinds, key=list(ExperimentRequirementKind).index) != kinds or len(set(kinds)) != len(kinds):
            raise ValueError("requirements are canonical: once each, in catalog order")
        if self.requirements and set(kinds) != set(ExperimentRequirementKind):
            raise ValueError("an assessed experiment resolves the whole catalog (no silently dropped requirement)")
        for r in self.requirements:
            if r.experiment_id != self.experiment_id or r.experiment_run_id != self.experiment_run_id:
                raise ValueError("a requirement belongs to a different experiment")
            expected = resolve_applicability(r.kind, self.experiment_type, None)
            if r.basis in (ApplicabilityBasis.CATALOG_DEFAULT, ApplicabilityBasis.CATALOG_TYPE_OVERRIDE,
                           ApplicabilityBasis.EXPERIMENT_TYPE_UNKNOWN) and (r.applicability, r.basis) != expected:
                raise ValueError(f"{r.kind.value}: catalog applicability is fixed by the catalog, never chosen")
            if r.basis not in (ApplicabilityBasis.CATALOG_DEFAULT, ApplicabilityBasis.CATALOG_TYPE_OVERRIDE,
                               ApplicabilityBasis.EXPERIMENT_TYPE_UNKNOWN) and (
                expected[1] is not ApplicabilityBasis.CONDITION_UNRESOLVED
            ):
                raise ValueError(f"{r.kind.value}: only a CONDITIONAL cell may be resolved; REQUIRED is never lowered")
        if self.issues != sorted(set(self.issues)):
            raise ValueError("issues are canonical: sorted and unique")
        return self


def _coverage_posture(status: CoverageStatus) -> ExperimentPosture:
    return {
        CoverageStatus.COVERED_BY_EXPERIMENT: ExperimentPosture.WELL_SPECIFIED,
        CoverageStatus.PARTIALLY_COVERED: ExperimentPosture.PARTIALLY_SPECIFIED,
        CoverageStatus.NOT_COVERED: ExperimentPosture.MAJOR_GAPS,
        CoverageStatus.UNRESOLVED: ExperimentPosture.UNRESOLVED,
    }[status]


# ---------------------------------------------------------------------------
# Phase 2J continuity (section 22)
# ---------------------------------------------------------------------------


class BoundValidationTarget(MawhibaModel):
    """A Phase 2J validation requirement as Phase 3B sees it: ids and anchor hashes
    copied exactly, never re-derived and never rewritten. A hypothesis without a
    requirement yields no target: Phase 3B never invents one."""

    validation_requirement_id: UUID
    gap_hypothesis_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    metric_anchor_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    baseline_anchor_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    condition_ids: list[UUID] = Field(default_factory=list)
    limitation_facets: list[GapFacet] = Field(default_factory=list)

    @property
    def requires_baseline(self) -> bool:
        return self.baseline_anchor_hash is not None

    @classmethod
    def from_hypothesis(cls, hypothesis: GapHypothesis) -> BoundValidationTarget | None:
        req = hypothesis.validation_requirement
        if req is None:
            return None
        return cls(
            validation_requirement_id=req.requirement_id,
            gap_hypothesis_id=hypothesis.hypothesis_id,
            claim_id=hypothesis.claim_id,
            metric_anchor_hash=text_hash(req.metric.text),
            baseline_anchor_hash=text_hash(req.baseline.text) if req.baseline is not None else None,
            condition_ids=sorted(req.condition_ids, key=str),
            limitation_facets=sorted({lim.facet for lim in hypothesis.limitations}),
        )


class CoverageStatus(StrEnum):
    """Protocol coverage, never result success."""

    COVERED_BY_EXPERIMENT = "COVERED_BY_EXPERIMENT"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    NOT_COVERED = "NOT_COVERED"
    UNRESOLVED = "UNRESOLVED"


class ContinuityReason(StrEnum):
    PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED = "PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"
    METRIC_TARGET_MISMATCH = "METRIC_TARGET_MISMATCH"
    BASELINE_TARGET_MISMATCH = "BASELINE_TARGET_MISMATCH"
    MATERIAL_CONDITION_UNCOVERED = "MATERIAL_CONDITION_UNCOVERED"
    COVERING_PROTOCOL_INADEQUATE = "COVERING_PROTOCOL_INADEQUATE"
    LINKAGE_UNRESOLVED = "LINKAGE_UNRESOLVED"


def derive_phase2j_coverage(
    target: BoundValidationTarget,
    *,
    experiment_postures: dict[UUID, ExperimentPosture],
    links: list[ExperimentTargetLink],
    measurements: list[MeasurementBinding],
    baselines: list[ExperimentBaselineRecord],
    conditions: list[ConditionCoverage],
) -> tuple[CoverageStatus, list[UUID], list[ContinuityReason]]:
    """The single continuity rule. Only records bound to this exact requirement id
    count. COVERED needs ONE experiment that covers every dimension: metrics,
    baselines and conditions from different experiments are never pooled."""
    req = target.validation_requirement_id
    own = [link for link in links if link.validation_requirement_id == req
           and link.gap_hypothesis_id == target.gap_hypothesis_id and link.claim_id == target.claim_id]
    testing = sorted({link.experiment_id for link in own if link.relation in TESTING_RELATIONS}, key=str)
    if not testing:
        if any(link.relation is TargetRelation.UNRESOLVED for link in own):
            return CoverageStatus.UNRESOLVED, [], [ContinuityReason.LINKAGE_UNRESOLVED]
        return CoverageStatus.NOT_COVERED, [], [ContinuityReason.PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED]
    covering: list[UUID] = []
    reasons: set[ContinuityReason] = set()
    for exp in testing:
        missing: set[ContinuityReason] = set()
        if not any(link.experiment_id == exp and link.relation is TargetRelation.DIRECTLY_TESTS for link in own):
            missing.add(ContinuityReason.PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED)
        if not any(m.experiment_id == exp and m.validation_requirement_id == req
                   and m.alignment is MetricTargetAlignment.ALIGNED_SAME_TARGET
                   and m.phase2j_metric_match is Phase2JAnchorMatch.SAME_AS_PHASE_2J for m in measurements):
            missing.add(ContinuityReason.METRIC_TARGET_MISMATCH)
        if target.requires_baseline and not any(
            b.experiment_id == exp and b.validation_requirement_id == req
            and b.relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT
            and b.phase2j_baseline_match is Phase2JAnchorMatch.SAME_AS_PHASE_2J for b in baselines
        ):
            missing.add(ContinuityReason.BASELINE_TARGET_MISMATCH)
        addressed = {c.condition_id for c in conditions if c.experiment_id == exp and c.validation_requirement_id == req
                     and c.status is ConditionCoverageStatus.ADDRESSED_IN_PROTOCOL}
        if set(target.condition_ids) - addressed:
            missing.add(ContinuityReason.MATERIAL_CONDITION_UNCOVERED)
        if experiment_postures.get(exp) not in (ExperimentPosture.WELL_SPECIFIED, ExperimentPosture.PARTIALLY_SPECIFIED):
            missing.add(ContinuityReason.COVERING_PROTOCOL_INADEQUATE)
        if missing:
            reasons |= missing
        else:
            covering.append(exp)
    if covering:
        return CoverageStatus.COVERED_BY_EXPERIMENT, covering, []
    return CoverageStatus.PARTIALLY_COVERED, [], sorted(reasons)


class Phase2JCoverage(MawhibaModel):
    experiment_run_id: UUID
    validation_requirement_id: UUID
    gap_hypothesis_id: UUID
    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    attempting_experiment_ids: list[UUID] = Field(default_factory=list)
    covering_experiment_ids: list[UUID] = Field(default_factory=list)
    status: CoverageStatus
    reasons: list[ContinuityReason] = Field(default_factory=list)
    result_success_evaluated: Literal[False] = False


# ---------------------------------------------------------------------------
# Track and project postures (sections 20, 26)
# ---------------------------------------------------------------------------


FACET_TRACK: dict[GapFacet, MethodologyTrack] = {
    GapFacet.RESEARCH: MethodologyTrack.SCIENTIFIC_RESEARCH,
    GapFacet.ENGINEERING: MethodologyTrack.ENGINEERING,
}


def coverage_track(target: BoundValidationTarget, tracks: list[MethodologyTrack]) -> MethodologyTrack | None:
    """A single-track project owns every requirement; a HYBRID one by its one Phase 2J facet, else none."""
    if len(tracks) == 1:
        return tracks[0]
    owners = {FACET_TRACK[f] for f in target.limitation_facets}
    return owners.pop() if len(owners) == 1 else None


def derive_track_posture(
    experiment_postures: list[ExperimentPosture], coverage: list[CoverageStatus]
) -> ExperimentPosture:
    """Worst-wins over the track's experiments and its Phase 2J coverage. No experiment
    and no coverage is INSUFFICIENT_EVIDENCE. Nothing is averaged."""
    members = [*experiment_postures, *(_coverage_posture(c) for c in coverage)]
    return worst(members) if members else ExperimentPosture.INSUFFICIENT_EVIDENCE


def derive_project_posture(
    track_postures: list[ExperimentPosture],
    *,
    unowned_experiments: bool,
    unowned_coverage: list[CoverageStatus],
    untested_claims: bool,
) -> ExperimentPosture:
    """Worst of the tracks and of any coverage no track owns. An experiment or a
    requirement with unresolved ownership caps the project at UNRESOLVED; a bound
    claim no experiment tests caps it at PARTIALLY_SPECIFIED."""
    if not track_postures:
        return ExperimentPosture.INSUFFICIENT_EVIDENCE
    posture = worst([*track_postures, *(_coverage_posture(c) for c in unowned_coverage)])
    if unowned_experiments:
        posture = worst([posture, ExperimentPosture.UNRESOLVED])
    if untested_claims:
        posture = worst([posture, ExperimentPosture.PARTIALLY_SPECIFIED])
    return posture


class TrackPostureRecord(MawhibaModel):
    experiment_run_id: UUID
    track: MethodologyTrack
    experiment_ids: list[UUID] = Field(default_factory=list)
    validation_requirement_ids: list[UUID] = Field(default_factory=list)
    posture: ExperimentPosture
    policy_version: str = EXPERIMENT_SYNTHESIS_POLICY_VERSION


# ---------------------------------------------------------------------------
# Run issues and their emitters (section 27: no dead enums)
# ---------------------------------------------------------------------------


class ExperimentRunIssueCode(StrEnum):
    PROJECT_TYPE_UNBOUND = "PROJECT_TYPE_UNBOUND"
    SOURCE_BINDING_MISSING = "SOURCE_BINDING_MISSING"
    EXACT_EXCERPT_MISMATCH = "EXACT_EXCERPT_MISMATCH"
    AMBIGUOUS_EXCERPT = "AMBIGUOUS_EXCERPT"
    CROSS_RUN_REFERENCE = "CROSS_RUN_REFERENCE"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    UPSTREAM_MUTATED = "UPSTREAM_MUTATED"
    RESULT_LEAKAGE_ATTEMPT = "RESULT_LEAKAGE_ATTEMPT"
    INVENTED_REQUIREMENT = "INVENTED_REQUIREMENT"
    SOURCE_INSTRUCTION_FOLLOWED = "SOURCE_INSTRUCTION_FOLLOWED"
    PROMPT_LEAK_REDACTED = "PROMPT_LEAK_REDACTED"
    MODEL_PROVIDER_MISSING = "MODEL_PROVIDER_MISSING"
    MODEL_CALL_BOUND_REACHED = "MODEL_CALL_BOUND_REACHED"
    MODEL_RESPONSE_INVALID = "MODEL_RESPONSE_INVALID"
    MODEL_REFUSED = "MODEL_REFUSED"
    PARTIAL_MODEL_OUTPUT = "PARTIAL_MODEL_OUTPUT"
    EXPERIMENT_BOUND_REACHED = "EXPERIMENT_BOUND_REACHED"


_S = ExperimentStage
_MODEL_FAILURES = (_S.SEGMENT_EXPERIMENTS, _S.EXTRACT_PROTOCOL, _S.RESOLVE_APPLICABILITY, _S.LINK_TARGETS)
RUN_ISSUE_EMITTERS: dict[ExperimentRunIssueCode, tuple[ExperimentStage, ...]] = {
    ExperimentRunIssueCode.PROJECT_TYPE_UNBOUND: (_S.BIND_INPUTS,),
    ExperimentRunIssueCode.SOURCE_BINDING_MISSING: (_S.BIND_INPUTS,),
    ExperimentRunIssueCode.EXACT_EXCERPT_MISMATCH: (_S.SEGMENT_EXPERIMENTS, _S.EXTRACT_PROTOCOL, _S.LINK_TARGETS),
    ExperimentRunIssueCode.AMBIGUOUS_EXCERPT: (_S.SEGMENT_EXPERIMENTS, _S.EXTRACT_PROTOCOL, _S.LINK_TARGETS),
    ExperimentRunIssueCode.CROSS_RUN_REFERENCE: (_S.LINK_TARGETS, _S.FINALIZE),
    ExperimentRunIssueCode.UNKNOWN_TARGET: (_S.LINK_TARGETS,),
    ExperimentRunIssueCode.UPSTREAM_MUTATED: (_S.FINALIZE,),
    ExperimentRunIssueCode.RESULT_LEAKAGE_ATTEMPT: (_S.EXTRACT_PROTOCOL, _S.LINK_TARGETS),
    ExperimentRunIssueCode.INVENTED_REQUIREMENT: (_S.EXTRACT_PROTOCOL, _S.RESOLVE_APPLICABILITY),
    ExperimentRunIssueCode.SOURCE_INSTRUCTION_FOLLOWED: _MODEL_FAILURES,
    ExperimentRunIssueCode.PROMPT_LEAK_REDACTED: _MODEL_FAILURES,
    ExperimentRunIssueCode.MODEL_PROVIDER_MISSING: (_S.SEGMENT_EXPERIMENTS,),
    ExperimentRunIssueCode.MODEL_CALL_BOUND_REACHED: _MODEL_FAILURES,
    ExperimentRunIssueCode.MODEL_RESPONSE_INVALID: _MODEL_FAILURES,
    ExperimentRunIssueCode.MODEL_REFUSED: _MODEL_FAILURES,
    ExperimentRunIssueCode.PARTIAL_MODEL_OUTPUT: _MODEL_FAILURES,
    ExperimentRunIssueCode.EXPERIMENT_BOUND_REACHED: (_S.SEGMENT_EXPERIMENTS,),
}
"""Every run-issue code has a named emitting stage. A code a stage cannot emit is dead."""

if set(RUN_ISSUE_EMITTERS) != set(ExperimentRunIssueCode):  # pragma: no cover - import-time guard
    raise RuntimeError("every run-issue code has an emitter")


class ExperimentRunIssue(MawhibaModel):
    code: ExperimentRunIssueCode
    node: ExperimentStage
    message: str = Field(min_length=1, max_length=MAX_SAFE_SUMMARY_LENGTH)
    experiment_id: UUID | None = None

    @model_validator(mode="after")
    def _emitter(self) -> ExperimentRunIssue:
        if self.node not in RUN_ISSUE_EMITTERS[self.code]:
            raise ValueError(f"{self.code.value} is not emitted by {self.node.value}")
        return self


class RejectedExperimentProposal(MawhibaModel):
    """A refused model proposal. Only a digest of the model text is persisted."""

    code: ExperimentRunIssueCode
    stage: ExperimentStage
    response_digest: str = Field(pattern=CONTENT_HASH_PATTERN)


# ---------------------------------------------------------------------------
# The run (sections 6, 30-32)
# ---------------------------------------------------------------------------


class ExperimentUpstreamPhase(StrEnum):
    """Authoritative inputs. Result Review, Red Team, Score and Readiness are
    deliberately absent, and so are ``ProjectState.results`` and the legacy
    ``ProjectState.experiments`` prefill (ADR-023 section 3)."""

    STUDENT_SUBMISSION = "STUDENT_SUBMISSION"
    PROJECT_CLAIMS = "PROJECT_CLAIMS"
    PHASE_2J_GAP = "PHASE_2J_GAP"
    PHASE_3A_METHODOLOGY = "PHASE_3A_METHODOLOGY"


class ExperimentUpstreamBinding(MawhibaModel):
    phase: ExperimentUpstreamPhase
    upstream_id: UUID
    fingerprint: str = Field(pattern=CONTENT_HASH_PATTERN)


class ExperimentRunStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    INVALIDATED_UPSTREAM_MUTATED = "INVALIDATED_UPSTREAM_MUTATED"


class ExperimentRunVersions(MawhibaModel):
    contract_version: str = EXPERIMENT_CONTRACT_VERSION
    catalog_version: str = EXPERIMENT_CATALOG_VERSION
    anchor_verifier_version: str = EXPERIMENT_ANCHOR_VERIFIER_VERSION
    synthesis_policy_version: str = EXPERIMENT_SYNTHESIS_POLICY_VERSION
    model_provider: str | None = None
    model_name: str | None = None


class ExperimentReviewBounds(MawhibaModel):
    """Every dimension of a run is bounded; a bounded run never reads complete.

    Model calls: 1 segmentation + per experiment 1 extraction + at most 1
    applicability + 1 linkage, so ``1 + 3 * max_experiments`` <= ``max_model_calls``."""

    max_submission_chars: int = Field(default=60_000, ge=1_000, le=400_000)
    max_excerpt_chars: int = Field(default=1_500, ge=50, le=10_000)
    max_excerpts: int = Field(default=400, ge=1, le=2_000)
    max_experiments: int = Field(default=12, ge=1, le=50)
    max_model_calls: int = Field(default=40, ge=0, le=2_000)
    model_retry_limit: int = Field(default=1, ge=0, le=5)

    @model_validator(mode="after")
    def _calls_cover_experiments(self) -> ExperimentReviewBounds:
        if self.max_model_calls and self.max_model_calls < 1 + 3 * self.max_experiments:
            raise ValueError("the call bound must cover one segmentation and three calls per experiment")
        return self


def directly_tests_supported(link: ExperimentTargetLink, measurements: list[MeasurementBinding]) -> bool:
    """The metric-target guard: an aligned measurement of the same experiment AND the same target."""
    return any(
        m.experiment_id == link.experiment_id
        and (m.target_claim_id, m.gap_hypothesis_id, m.validation_requirement_id) == link.target_key
        and m.alignment is MetricTargetAlignment.ALIGNED_SAME_TARGET
        for m in measurements
    )


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


class ExperimentReviewRun(MawhibaModel):
    experiment_run_id: UUID
    research_run_id: UUID
    gap_run_id: UUID | None = None
    methodology_run_id: UUID | None = None
    status: ExperimentRunStatus = ExperimentRunStatus.NOT_STARTED
    versions: ExperimentRunVersions = Field(default_factory=ExperimentRunVersions)
    bounds: ExperimentReviewBounds = Field(default_factory=ExperimentReviewBounds)
    canonical_project_type: ProjectType = ProjectType.UNKNOWN
    tracks: list[MethodologyTrack] = Field(default_factory=list)
    submission_artifact_id: UUID | None = None
    submission_content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    upstream_bindings: list[ExperimentUpstreamBinding] = Field(default_factory=list)
    bound_claims: list[BoundClaim] = Field(default_factory=list)
    bound_validation_targets: list[BoundValidationTarget] = Field(default_factory=list)
    excerpts: list[StudentExperimentExcerpt] = Field(default_factory=list)
    quarantine: list[QuarantinedSpan] = Field(default_factory=list)
    experiments: list[ExperimentRecord] = Field(default_factory=list)
    measurements: list[MeasurementBinding] = Field(default_factory=list)
    baselines: list[ExperimentBaselineRecord] = Field(default_factory=list)
    conditions: list[ConditionCoverage] = Field(default_factory=list)
    links: list[ExperimentTargetLink] = Field(default_factory=list)
    phase2j_coverage: list[Phase2JCoverage] = Field(default_factory=list)
    track_postures: list[TrackPostureRecord] = Field(default_factory=list)
    project_posture: ExperimentPosture | None = None
    untested_claim_ids: list[str] = Field(default_factory=list)
    rejected_proposals: list[RejectedExperimentProposal] = Field(default_factory=list)
    execution_boundary: Literal["EXECUTION_DESCRIBED_IS_NOT_EXECUTION_VERIFIED"] = EXECUTION_BOUNDARY
    execution_verified: Literal[False] = False
    results_evaluated: Literal[False] = False
    model_calls_performed: int = Field(default=0, ge=0)
    external_search_calls: Literal[0] = 0
    network_attempts: Literal[0] = 0
    errors: list[ExperimentRunIssue] = Field(default_factory=list)
    stage_markers: list[ExperimentStage] = Field(default_factory=list)
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _bound_and_consistent(self) -> ExperimentReviewRun:  # noqa: C901 - one invariant per block
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if len({b.phase for b in self.upstream_bindings}) != len(self.upstream_bindings):
            raise ValueError("one binding per upstream phase")
        if list(self.tracks) != list(tracks_for(self.canonical_project_type)):
            raise ValueError("tracks are inherited from the canonical project type, never reclassified")
        completed = self.status is ExperimentRunStatus.COMPLETED
        if completed and not self.tracks:
            raise ValueError("an unbound project type is INSUFFICIENT_INPUT, never COMPLETED")
        if self.model_calls_performed > self.bounds.max_model_calls:
            raise ValueError("model calls exceed the run bound")
        if len(self.experiments) > self.bounds.max_experiments:
            raise ValueError("experiments exceed the run bound")
        if (self.excerpts or self.quarantine) and (self.submission_artifact_id is None
                                                   or self.submission_content_hash is None):
            raise ValueError("excerpts and quarantined spans require a bound submission")

        own = self.experiment_run_id
        children = [*self.excerpts, *self.quarantine, *self.experiments, *self.measurements, *self.baselines,
                    *self.conditions, *self.links, *self.phase2j_coverage, *self.track_postures]
        for e in self.experiments:
            children += e.requirements
        if any(c.experiment_run_id != own for c in children):
            raise ValueError("a record belongs to a different experiment run (cross-run mixing)")

        # -- source binding and the result quarantine --------------------------
        excerpts = {e.excerpt_id: e for e in self.excerpts}
        if len(excerpts) != len(self.excerpts):
            raise ValueError("excerpt ids are unique; a replay must not duplicate them")
        if any(e.submission_artifact_id != self.submission_artifact_id
               or e.submission_content_hash != self.submission_content_hash for e in self.excerpts):
            raise ValueError("an excerpt cut from a different submission (stale artifact hash)")
        for q in self.quarantine:
            for e in self.excerpts:
                if _overlaps(e.start, e.end, q.start, q.end):
                    raise ValueError("a protocol excerpt overlaps a quarantined result span (result leakage)")

        def _cited(ids: list[UUID]) -> None:
            if any(i not in excerpts for i in ids):
                raise ValueError("a record cites an excerpt outside the run (fabricated reference)")

        # -- targets -----------------------------------------------------------
        claims = {c.claim_id: c.claim_text_hash for c in self.bound_claims}
        if len(claims) != len(self.bound_claims):
            raise ValueError("a claim is bound once")
        targets = {t.validation_requirement_id: t for t in self.bound_validation_targets}
        if len(targets) != len(self.bound_validation_targets):
            raise ValueError("a Phase 2J validation requirement is bound once")
        if any(t.claim_id not in claims for t in self.bound_validation_targets):
            raise ValueError("a validation target names an unbound claim")
        hypothesis_claim = {t.gap_hypothesis_id: t.claim_id for t in self.bound_validation_targets}

        def _target(claim_id: str, hyp: UUID | None, req: UUID | None, what: str) -> None:
            if claim_id not in claims:
                raise ValueError(f"a {what} targets an unbound claim")
            if hyp is not None and hypothesis_claim.get(hyp) != claim_id:
                raise ValueError(f"a {what} crosses to another claim's Phase 2J hypothesis (cross-target)")
            if req is not None and (req not in targets or targets[req].gap_hypothesis_id != hyp):
                raise ValueError(f"a {what} cites a Phase 2J requirement of another target (no substitution)")

        # -- experiments: identity, duplicates, ownership, derivation ---------
        by_id = {e.experiment_id: e for e in self.experiments}
        if len(by_id) != len(self.experiments) or len({e.protocol_key for e in self.experiments}) != len(by_id):
            raise ValueError("an experiment is recorded once (duplicate protocol)")
        defining = [i for e in self.experiments for i in e.defining_excerpt_ids]
        if len(set(defining)) != len(defining):
            raise ValueError("a defining excerpt belongs to one experiment only")
        single = len(self.tracks) == 1
        for e in self.experiments:
            _cited([*e.defining_excerpt_ids, *e.ownership_excerpt_ids])
            for r in e.requirements:
                _cited([*r.excerpt_ids, *r.judgment_excerpt_ids])
                if r.kind is ERK.SAMPLE_SIZE_RATIONALE and r.documentation in _DOC_WITH_EXCERPTS and all(
                    BARE_QUANTITY.match(excerpts[i].excerpt) for i in r.excerpt_ids
                ):
                    raise ValueError("a bare number is not a sample-size rationale")
            if e.protocol_key != protocol_key([excerpts[i].excerpt for i in e.defining_excerpt_ids]):
                raise ValueError("the protocol key is the hash of the defining excerpt texts")
            if e.revision_of is not None and e.revision_of not in by_id:
                raise ValueError("a revision names an experiment of this run")
            if e.track is not None:
                if e.track not in self.tracks:
                    raise ValueError("an experiment is owned by a track the project type does not have")
                if single != (e.ownership_basis is TrackOwnershipBasis.SINGLE_TRACK_PROJECT):
                    raise ValueError("a single-track project owns its experiments by that track; HYBRID never does")
                if e.ownership_basis is TrackOwnershipBasis.PHASE_2J_LIMITATION_FACET:
                    by_hyp = {t.gap_hypothesis_id: t for t in self.bound_validation_targets}
                    facets = {f for h in e.ownership_gap_hypothesis_ids for f in by_hyp[h].limitation_facets} \
                        if all(h in by_hyp for h in e.ownership_gap_hypothesis_ids) else set()
                    if {FACET_TRACK[f] for f in facets} != {e.track}:
                        raise ValueError("facet ownership follows the hypotheses' one Phase 2J facet")
            if completed and not e.requirements:
                raise ValueError("a completed run resolves every experiment's requirements")

        def _of(records: list, exp: UUID) -> list:  # noqa: ANN001
            return [r for r in records if r.experiment_id == exp]

        for m in self.measurements:
            if m.experiment_id not in by_id:
                raise ValueError("a measurement binding names an unknown experiment")
            _cited([i for i in (m.method_excerpt_id, m.metric_excerpt_id, m.unit_excerpt_id,
                                m.success_criterion_excerpt_id) if i is not None])
            _target(m.target_claim_id, m.gap_hypothesis_id, m.validation_requirement_id, "measurement binding")
        for b in self.baselines:
            if b.experiment_id not in by_id:
                raise ValueError("a baseline names an unknown experiment")
            _cited([*b.baseline_excerpt_ids, *(i for p in b.comparability for i in p.excerpt_ids)])
            _target(b.target_claim_id, b.gap_hypothesis_id, b.validation_requirement_id, "baseline")
            if b.validation_requirement_id is not None:
                has_2j = targets[b.validation_requirement_id].requires_baseline
                if has_2j == (b.phase2j_baseline_match is Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR):
                    raise ValueError("NO_PHASE_2J_ANCHOR exactly when the Phase 2J requirement has no baseline")
            elif b.phase2j_baseline_match is not Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR:
                raise ValueError("a baseline with no Phase 2J requirement has no Phase 2J anchor")
        for c in self.conditions:
            if c.experiment_id not in by_id:
                raise ValueError("a condition coverage names an unknown experiment")
            _cited(c.excerpt_ids)
            if c.validation_requirement_id not in targets or c.condition_id not in (
                targets[c.validation_requirement_id].condition_ids
            ):
                raise ValueError("a condition coverage names a condition its Phase 2J requirement does not carry")
        for link in self.links:
            if link.experiment_id not in by_id:
                raise ValueError("a link names an unknown experiment")
            _cited(link.excerpt_ids)
            if claims.get(link.claim_id) != link.claim_text_hash:
                raise ValueError("a link binds an unbound or stale claim")
            _target(link.claim_id, link.gap_hypothesis_id, link.validation_requirement_id, "link")
            if link.relation is TargetRelation.DIRECTLY_TESTS and not directly_tests_supported(link, self.measurements):
                raise ValueError(
                    "DIRECTLY_TESTS needs an aligned measurement of the same experiment and the same target "
                    "(same keyword or same metric is never same target)"
                )

        postures: dict[UUID, ExperimentPosture] = {}
        for e in self.experiments:
            if not e.requirements:
                continue
            ms, bs, ls = _of(self.measurements, e.experiment_id), _of(self.baselines, e.experiment_id), \
                _of(self.links, e.experiment_id)
            issues = derive_experiment_issues(experiment_type=e.experiment_type, requirements=e.requirements,
                                              measurements=ms, baselines=bs, links=ls)
            if e.issues != issues:
                raise ValueError("experiment issues must be derived in code, never chosen")
            posture = derive_experiment_posture(experiment_type=e.experiment_type, requirements=e.requirements,
                                                issues=issues, measurements=ms, links=ls)
            if e.posture is not posture:
                raise ValueError(f"experiment posture must be derived in code ({posture.value}), never chosen")
            postures[e.experiment_id] = posture

        # -- Phase 2J continuity (derived) -------------------------------------
        if completed and {c.validation_requirement_id for c in self.phase2j_coverage} != set(targets):
            raise ValueError("a completed run records coverage for every bound Phase 2J requirement")
        coverage_by_req: dict[UUID, CoverageStatus] = {}
        for cov in self.phase2j_coverage:
            target = targets.get(cov.validation_requirement_id)
            if target is None or (cov.gap_hypothesis_id, cov.claim_id) != (target.gap_hypothesis_id, target.claim_id):
                raise ValueError("coverage preserves the exact Phase 2J target identity")
            status, covering, reasons = derive_phase2j_coverage(
                target, experiment_postures=postures, links=self.links, measurements=self.measurements,
                baselines=self.baselines, conditions=self.conditions)
            attempting = sorted({link.experiment_id for link in self.links
                                 if link.validation_requirement_id == target.validation_requirement_id
                                 and link.relation in TESTING_RELATIONS}, key=str)
            if (cov.status, cov.covering_experiment_ids, cov.reasons, cov.attempting_experiment_ids) != (
                status, covering, reasons, attempting
            ):
                raise ValueError("Phase 2J coverage must be derived in code, never chosen")
            coverage_by_req[cov.validation_requirement_id] = status

        # -- track and project postures (derived, worst-wins) ------------------
        if completed and [t.track for t in self.track_postures] != self.tracks:
            raise ValueError("a completed run has one posture per inherited track (HYBRID keeps both)")
        unowned_cov: list[CoverageStatus] = []
        owned_cov: dict[MethodologyTrack, list[UUID]] = {t: [] for t in self.tracks}
        for req_id in sorted(coverage_by_req, key=str):
            owner = coverage_track(targets[req_id], self.tracks)
            if owner is None:
                unowned_cov.append(coverage_by_req[req_id])
            else:
                owned_cov[owner].append(req_id)
        for tp in self.track_postures:
            exps = sorted((e.experiment_id for e in self.experiments if e.track is tp.track), key=str)
            if tp.experiment_ids != exps or tp.validation_requirement_ids != owned_cov.get(tp.track):
                raise ValueError("a track posture names exactly its own experiments and requirements")
            derived = derive_track_posture([postures[x] for x in exps if x in postures],
                                           [coverage_by_req[r] for r in tp.validation_requirement_ids])
            if tp.posture is not derived:
                raise ValueError(f"track posture must be derived in code ({derived.value}), never chosen")
        tested = {link.claim_id for link in self.links if link.relation in TESTING_RELATIONS}
        untested = sorted(set(claims) - tested)
        if completed and self.untested_claim_ids != untested:
            raise ValueError("untested claims are derived, never chosen")
        if completed:
            derived_project = derive_project_posture(
                [tp.posture for tp in self.track_postures],
                unowned_experiments=any(e.track is None for e in self.experiments),
                unowned_coverage=unowned_cov, untested_claims=bool(untested))
            if self.project_posture is not derived_project:
                raise ValueError(f"project posture must be derived in code ({derived_project.value}), never chosen")
        elif self.project_posture is not None:
            raise ValueError("only a completed run carries a project posture")

        # -- canonical ordering (section 32) ------------------------------------
        if self != canonicalize(self):
            raise ValueError("canonical ordering violated: model list order must never reach canonical state")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ExperimentRunStatus.COMPLETED,
            ExperimentRunStatus.INSUFFICIENT_INPUT,
            ExperimentRunStatus.INVALIDATED_UPSTREAM_MUTATED,
        ) and self.completed_at is not None


def _sorted(items: list, key) -> list:  # noqa: ANN001
    return sorted(items, key=key)


def canonicalize(run: ExperimentReviewRun) -> ExperimentReviewRun:
    """The one canonical ordering. Same validated content in any list order -> same run."""
    return run.model_construct(
        **{
            **dict(run),
            "bound_claims": _sorted(run.bound_claims, lambda c: c.claim_id),
            "bound_validation_targets": _sorted(run.bound_validation_targets,
                                                lambda t: str(t.validation_requirement_id)),
            "excerpts": _sorted(run.excerpts, lambda e: (e.start, e.end, str(e.excerpt_id))),
            "quarantine": _sorted(run.quarantine, lambda q: (q.start, q.end, str(q.span_id))),
            "experiments": _sorted(run.experiments, lambda e: str(e.experiment_id)),
            "measurements": _sorted(run.measurements, lambda m: str(m.binding_id)),
            "baselines": _sorted(run.baselines, lambda b: str(b.record_id)),
            "conditions": _sorted(run.conditions, lambda c: (str(c.experiment_id), str(c.validation_requirement_id),
                                                             str(c.condition_id))),
            "links": _sorted(run.links, lambda link: str(link.link_id)),
            "phase2j_coverage": _sorted(run.phase2j_coverage, lambda c: str(c.validation_requirement_id)),
            "track_postures": _sorted(run.track_postures, lambda t: list(MethodologyTrack).index(t.track)),
        }
    )


def adequacy_fingerprint(run: ExperimentReviewRun) -> str:
    """The adequacy-relevant content of a run. It excludes the quarantine, offsets,
    the submission hash and timestamps, so a changed result value with an identical
    protocol yields the same fingerprint (section 23 mutation test)."""
    text_of = {e.excerpt_id: text_hash(e.excerpt) for e in run.excerpts}

    def ids(xs: list[UUID]) -> list[str]:
        return sorted(text_of.get(x, "?") for x in xs)

    payload = {
        "experiments": [
            {"key": e.protocol_key, "type": e.experiment_type, "track": e.track, "posture": e.posture,
             "issues": e.issues,
             "requirements": [(r.kind, r.applicability, r.basis, r.triggers, r.documentation, r.adequacy,
                               ids(r.excerpt_ids)) for r in e.requirements]}
            for e in run.experiments
        ],
        "links": sorted((str(link.experiment_id), link.claim_id, str(link.gap_hypothesis_id),
                         str(link.validation_requirement_id), link.relation) for link in run.links),
        "coverage": [(str(c.validation_requirement_id), c.status, c.reasons) for c in run.phase2j_coverage],
        "tracks": [(t.track, t.posture) for t in run.track_postures],
        "project": run.project_posture,
    }
    return text_hash(json.dumps(payload, default=str, sort_keys=True))


def upstream_fingerprint(record: MawhibaModel) -> str:
    """The fingerprint compared at bind and at finalize."""
    return text_hash(record.model_dump_json())


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
    "accuracy",
    "p_value",
    "significan",
    "observed",
    "measured_value",
    "reported_value",
    "red_team",
    "jury",
    "proven",
    "is_fair",
    "fairness_verified",
)
"""No Phase 3B field name may contain any of these. ``result`` appears only in the
literal-False guards (``results_evaluated``, ``comparison_result_evaluated``,
``result_success_evaluated``), which ``ALLOWED_RESULT_FIELDS`` names exactly."""

ALLOWED_RESULT_FIELDS: frozenset[str] = frozenset(
    {"results_evaluated", "comparison_result_evaluated", "result_success_evaluated"}
)
