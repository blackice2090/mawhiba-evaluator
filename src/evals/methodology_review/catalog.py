"""Independent Gold-side policy tables for Phase 3A.

Hand-transcribed from the approved specification (PHASE_3A_METHODOLOGY_REVIEW.md sections 7-12), NOT
imported from ``src.schemas.methodology_review``. The scorer and the release gates read these tables so
that a defect in a production table cannot silently also be the definition of "correct".

Row shape: kind -> (overlay, home_track, default, triggers, tests_target)
    overlay   CORE | AI_ML | SOFTWARE_SYSTEMS
    home_track  R (SCIENTIFIC_RESEARCH) | E (ENGINEERING) | None (overlay row)
    default   REQ | COND | OPT
"""

from __future__ import annotations

R, E = "SCIENTIFIC_RESEARCH", "ENGINEERING"
TRACK_OF = {"R": R, "E": E}

_T = {
    "CD": "CONFIRMATORY_DESIGN", "CC": "COMPARATIVE_OR_CAUSAL_CLAIM", "AI": "ASSIGNED_INTERVENTION",
    "SR": "SUBJECTIVE_OR_HUMAN_RATED_MEASUREMENT", "HP": "HUMAN_PARTICIPANTS", "SI": "STATISTICAL_INFERENCE",
    "SP": "SAMPLED_POPULATION", "PB": "PHASE_2J_BASELINE_REQUIRED", "PC": "PHASE_2J_MATERIAL_CONDITION",
    "GR": "GROUPED_OR_REPEATED_SUBJECT_DATA", "TO": "TIME_ORDERED_DATA", "IL": "IMBALANCED_LABELS",
    "MT": "MODEL_TUNING_PERFORMED", "GC": "GENERALIZATION_CLAIMED", "SE": "SECURITY_CLAIMED",
    "PV": "PRIVACY_CLAIMED", "PF": "PERFORMANCE_CLAIMED", "SC": "SCALABILITY_CLAIMED", "RL": "RELIABILITY_CLAIMED",
    "SF": "SAFETY_RELEVANT", "US": "USABILITY_CLAIMED", "PD": "PERSONAL_DATA_PROCESSED",
}


def _r(overlay, track, default, trig="", tests=False):
    return (overlay, TRACK_OF.get(track), default, tuple(_T[t] for t in trig.split()) if trig else (), tests)


CATALOG: dict[str, tuple] = {
    # scientific research
    "RESEARCH_QUESTION": _r("CORE", "R", "REQ"),
    "HYPOTHESIS_OR_NON_HYPOTHESIS_DESIGN": _r("CORE", "R", "COND", "CD"),
    "INDEPENDENT_VARIABLE": _r("CORE", "R", "COND", "CC AI", True),
    "DEPENDENT_VARIABLE": _r("CORE", "R", "REQ", "", True),
    "CONTROLLED_VARIABLES": _r("CORE", "R", "COND", "CC", True),
    "OPERATIONAL_DEFINITIONS": _r("CORE", "R", "REQ", "", True),
    "POPULATION_SAMPLING_FRAME": _r("CORE", "R", "COND", "SP HP"),
    "SAMPLE": _r("CORE", "R", "REQ"),
    "SAMPLE_SIZE_RATIONALE": _r("CORE", "R", "COND", "SI SP"),
    "CONTROL_OR_COMPARISON_GROUP": _r("CORE", "R", "COND", "CC PB", True),
    "RANDOMIZATION": _r("CORE", "R", "COND", "AI"),
    "BLINDING": _r("CORE", "R", "COND", "SR"),
    "STUDY_DESIGN": _r("CORE", "R", "REQ", "", True),
    "DATA_COLLECTION_METHOD": _r("CORE", "R", "REQ", "", True),
    "MEASUREMENT_METHOD": _r("CORE", "R", "REQ", "", True),
    "REPLICATION_PLAN": _r("CORE", "R", "OPT"),
    "STATISTICAL_ANALYSIS_PLAN": _r("CORE", "R", "COND", "SI CC", True),
    "CONFOUNDER_HANDLING": _r("CORE", "R", "COND", "CC"),
    "BIAS_MITIGATION": _r("CORE", "R", "OPT"),
    "INTERNAL_VALIDITY_THREATS": _r("CORE", "R", "OPT"),
    "EXTERNAL_VALIDITY_BOUNDARIES": _r("CORE", "R", "COND", "GC PC"),
    "RESEARCH_REPRODUCIBILITY_PLAN": _r("CORE", "R", "OPT"),
    "ETHICS_CONSENT": _r("CORE", "R", "COND", "HP PD"),
    "STATED_LIMITATIONS": _r("CORE", "R", "OPT"),
    # engineering
    "DESIGN_OBJECTIVE": _r("CORE", "E", "REQ"),
    "REQUIREMENTS": _r("CORE", "E", "REQ"),
    "CONSTRAINTS": _r("CORE", "E", "OPT"),
    "DESIGN_RATIONALE": _r("CORE", "E", "OPT"),
    "SYSTEM_BOUNDARIES": _r("CORE", "E", "OPT"),
    "ARCHITECTURE_SUBSYSTEM_PLAN": _r("CORE", "E", "REQ"),
    "INPUTS_OUTPUTS": _r("CORE", "E", "OPT"),
    "SENSORS_DATA_INTERFACES": _r("CORE", "E", "OPT"),
    "ALGORITHM_CONTROL_STRATEGY": _r("CORE", "E", "OPT"),
    "BASELINE_OR_ALTERNATIVE_DESIGN": _r("CORE", "E", "COND", "CC PB", True),
    "VERIFICATION_PLAN": _r("CORE", "E", "REQ", "", True),
    "VALIDATION_PLAN": _r("CORE", "E", "REQ", "", True),
    "MEASUREMENT_PLAN": _r("CORE", "E", "REQ", "", True),
    "ACCEPTANCE_CRITERIA": _r("CORE", "E", "REQ", "", True),
    "FAILURE_MODE_CONSIDERATION": _r("CORE", "E", "OPT"),
    "RELIABILITY_PLAN": _r("CORE", "E", "COND", "RL SF", True),
    "SAFETY_PLAN": _r("CORE", "E", "COND", "SF"),
    "SECURITY_PRIVACY_VALIDATION": _r("CORE", "E", "COND", "SE PV", True),
    "PERFORMANCE_BENCHMARK_PLAN": _r("CORE", "E", "COND", "PF", True),
    "SCALABILITY_VALIDATION": _r("CORE", "E", "COND", "SC", True),
    "ITERATION_STRATEGY": _r("CORE", "E", "OPT"),
    "CONFIGURATION_REPRODUCIBILITY_PLAN": _r("CORE", "E", "OPT"),
    # AI / ML overlay
    "DATA_SOURCE": _r("AI_ML", None, "REQ"),
    "DATASET_SCOPE_SIZE": _r("AI_ML", None, "REQ"),
    "DATA_QUALITY": _r("AI_ML", None, "OPT"),
    "LABELS": _r("AI_ML", None, "REQ"),
    "LABELING_METHOD": _r("AI_ML", None, "REQ"),
    "TRAIN_SPLIT": _r("AI_ML", None, "REQ", "", True),
    "VALIDATION_SPLIT": _r("AI_ML", None, "COND", "MT", True),
    "TEST_SPLIT": _r("AI_ML", None, "REQ", "", True),
    "GROUP_AWARE_SPLIT": _r("AI_ML", None, "COND", "GR", True),
    "TEMPORAL_SPLIT": _r("AI_ML", None, "COND", "TO", True),
    "DATA_LEAKAGE_PREVENTION": _r("AI_ML", None, "REQ", "", True),
    "DUPLICATE_LEAKAGE_PREVENTION": _r("AI_ML", None, "OPT", "", True),
    "CLASS_IMBALANCE_HANDLING": _r("AI_ML", None, "COND", "IL"),
    "PREPROCESSING": _r("AI_ML", None, "OPT"),
    "FEATURE_ENGINEERING": _r("AI_ML", None, "OPT"),
    "DATA_AUGMENTATION": _r("AI_ML", None, "OPT"),
    "BASELINE_MODEL": _r("AI_ML", None, "COND", "CC PB", True),
    "MODEL_SELECTION_PROCEDURE": _r("AI_ML", None, "COND", "MT"),
    "HYPERPARAMETER_TUNING_PROCEDURE": _r("AI_ML", None, "COND", "MT"),
    "TEST_SET_ISOLATION_FROM_TUNING": _r("AI_ML", None, "REQ", "", True),
    "CROSS_VALIDATION": _r("AI_ML", None, "OPT", "", True),
    "GENERALIZATION_PLAN": _r("AI_ML", None, "COND", "GC PC", True),
    "EXTERNAL_VALIDATION_PLAN": _r("AI_ML", None, "COND", "GC", True),
    "EVALUATION_METRICS": _r("AI_ML", None, "REQ", "", True),
    "ERROR_ANALYSIS_PLAN": _r("AI_ML", None, "OPT"),
    "ML_REPRODUCIBILITY_SEEDS_VERSIONS": _r("AI_ML", None, "OPT"),
    # software / systems overlay
    "ARCHITECTURE_RATIONALE": _r("SOFTWARE_SYSTEMS", None, "OPT"),
    "BACKEND_DATA_LAYER_METHODOLOGY": _r("SOFTWARE_SYSTEMS", None, "OPT"),
    "SECURITY_VALIDATION_PLAN": _r("SOFTWARE_SYSTEMS", None, "COND", "SE", True),
    "PRIVACY_VALIDATION_PLAN": _r("SOFTWARE_SYSTEMS", None, "COND", "PV PD", True),
    "SYSTEM_PERFORMANCE_BENCHMARK_PLAN": _r("SOFTWARE_SYSTEMS", None, "COND", "PF", True),
    "SYSTEM_SCALABILITY_PLAN": _r("SOFTWARE_SYSTEMS", None, "COND", "SC", True),
    "SYSTEM_RELIABILITY_PLAN": _r("SOFTWARE_SYSTEMS", None, "COND", "RL", True),
    "USABILITY_METHODOLOGY": _r("SOFTWARE_SYSTEMS", None, "COND", "US", True),
    "EXISTING_ALTERNATIVES_COMPARISON": _r("SOFTWARE_SYSTEMS", None, "COND", "CC", True),
}

OVERLAY_OF = {k: v[0] for k, v in CATALOG.items()}
HOME_TRACK = {k: v[1] for k, v in CATALOG.items()}
DEFAULT = {k: v[2] for k, v in CATALOG.items()}
TRIGGERS = {k: set(v[3]) for k, v in CATALOG.items()}
TESTS_TARGET = {k for k, v in CATALOG.items() if v[4]}
KINDS = frozenset(CATALOG)
SCI_KINDS = frozenset(k for k, v in CATALOG.items() if v[1] == R)
ENG_KINDS = frozenset(k for k, v in CATALOG.items() if v[1] == E)
AI_KINDS = frozenset(k for k, v in CATALOG.items() if v[0] == "AI_ML")
SW_KINDS = frozenset(k for k, v in CATALOG.items() if v[0] == "SOFTWARE_SYSTEMS")
ALWAYS_REQUIRED = {k for k, v in CATALOG.items() if v[2] == "REQ"}

SEVERITY = {
    "TARGET_NOT_TESTABLE": "HIGH", "REQUIRED_COMPONENT_NOT_DOCUMENTED": "HIGH", "CLAIM_METHOD_MISMATCH": "HIGH",
    "GAP_METHOD_MISMATCH": "HIGH", "BASELINE_NOT_DOCUMENTED": "MEDIUM", "BASELINE_RELEVANCE_UNRESOLVED": "MEDIUM",
    "METRIC_NOT_DEFINED": "HIGH", "METRIC_TARGET_MISMATCH": "HIGH", "MATERIAL_CONDITION_NOT_COVERED": "HIGH",
    "SAMPLE_RATIONALE_NOT_DOCUMENTED": "MEDIUM", "CONTROL_STRATEGY_NOT_DOCUMENTED": "MEDIUM",
    "CONFOUNDER_HANDLING_NOT_DOCUMENTED": "MEDIUM", "DATA_LEAKAGE_RISK": "HIGH",
    "TEST_SET_ISOLATION_NOT_DOCUMENTED": "HIGH", "DUPLICATE_OR_GROUP_LEAKAGE_RISK": "HIGH",
    "REPRODUCIBILITY_NOT_DOCUMENTED": "LOW", "CONFLICTING_METHOD_DESCRIPTION": "HIGH",
}
MAJOR_SEVERITIES = {"CRITICAL", "HIGH"}

ALLOWED_ADEQUACY = {
    "EXPLICITLY_DOCUMENTED": {"ADEQUATELY_SPECIFIED_FOR_REVIEW", "PARTIALLY_SPECIFIED", "DESIGN_RISK_IDENTIFIED"},
    "PARTIALLY_DOCUMENTED": {"PARTIALLY_SPECIFIED", "DESIGN_RISK_IDENTIFIED"},
    "CONFLICTING_DOCUMENTATION": {"CONFLICTING_DESIGN"},
    "NOT_DOCUMENTED_IN_BOUND_INPUT": {"INSUFFICIENT_EVIDENCE_TO_ASSESS", "DESIGN_RISK_IDENTIFIED"},
    "INSUFFICIENT_SOURCE_COVERAGE": {"INSUFFICIENT_EVIDENCE_TO_ASSESS"},
    "NOT_APPLICABLE": {"NOT_APPLICABLE"},
}
DOC_WITH_EXCERPTS = {"EXPLICITLY_DOCUMENTED", "PARTIALLY_DOCUMENTED"}

POSTURE_WELL = "METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT"
POSTURE_PARTIAL = "METHODOLOGY_PARTIALLY_SPECIFIED"
POSTURE_MAJOR = "METHODOLOGY_HAS_MAJOR_DESIGN_GAPS"
POSTURE_CONFLICT = "METHODOLOGY_CONFLICTING"
POSTURE_INSUFFICIENT = "INSUFFICIENT_INPUT"
STRONG = {"DIRECTLY_TESTS_TARGET"}

FORBIDDEN_KEY_FRAGMENTS = ("score", "probability", "confidence", "readiness", "novel", "patentab", "infring",
                           "legal", "verdict", "threshold", "red_team", "jury", "experiment_valid", "proven",
                           "valid_method", "execution_result", "outcome_value")
"""A run's serialized KEYS must never contain these. (``result`` and ``accuracy`` are checked on keys separately.)"""
FORBIDDEN_KEY_EXACT = ("result", "results", "accuracy", "rank")

BARE_QUANTITY_CHARS = set(" \t\n.,;:()[]{}=<>-_/\\0123456789nN")
"""An excerpt made only of these characters carries no rationale (it is a bare quantity such as N = 500)."""

__all__ = [name for name in dir() if name.isupper()]
