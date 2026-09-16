"""Node identifier registry.

Two distinct namespaces:

``NodeId``
    Stable identifiers for the future production evaluation nodes described in
    sections 8-23 of the architecture. Declared now so that no node name is ever
    a free-form string duplicated across modules. Almost none of these execute
    in Phase 1A.

``Phase1ANode``
    The infrastructure nodes of the Phase 1A test graph. These are deliberately
    a separate enum so nobody mistakes the infrastructure harness for the real
    evaluation workflow.
"""

from __future__ import annotations

from enum import StrEnum


class NodeId(StrEnum):
    """Production evaluation nodes (architecture sections 8-23).

    Phase 1A declares these identifiers only. Implementations arrive in later
    phases.
    """

    # Intake and understanding (N00-N04)
    INTAKE_GUARD = "INTAKE_GUARD"
    PROJECT_EXTRACTOR = "PROJECT_EXTRACTOR"
    # Phase 1B splits N01 into propose / verify / merge so the trust boundary is
    # a visible node rather than a hidden step inside the extractor.
    PROJECT_EXTRACTOR_VERIFIER = "PROJECT_EXTRACTOR_VERIFIER"
    PROJECT_STATE_MERGE = "PROJECT_STATE_MERGE"
    PROJECT_TYPE_CLASSIFIER = "PROJECT_TYPE_CLASSIFIER"
    CLASSIFICATION_MERGE = "CLASSIFICATION_MERGE"
    OFFICIAL_REQUIREMENTS_CHECK = "OFFICIAL_REQUIREMENTS_CHECK"
    # Phase 2A splits N03 into retrieve / verify / extract so the source
    # verification boundary is a visible node. OFFICIAL_REQUIREMENTS_CHECK names
    # the branch as a whole.
    OFFICIAL_REQUIREMENTS_RETRIEVAL = "OFFICIAL_REQUIREMENTS_RETRIEVAL"
    VERIFY_OFFICIAL_SOURCES = "VERIFY_OFFICIAL_SOURCES"
    EXTRACT_OFFICIAL_REQUIREMENTS = "EXTRACT_OFFICIAL_REQUIREMENTS"
    PROBLEM_VALIDATION = "PROBLEM_VALIDATION"

    # Research planning and parallel branches (N05, N06A-N06D)
    LOAD_PROJECT_STATE = "LOAD_PROJECT_STATE"
    VALIDATE_RESEARCH_INPUT = "VALIDATE_RESEARCH_INPUT"
    RESEARCH_QUERY_PLANNER = "RESEARCH_QUERY_PLANNER"
    VERIFY_QUERY_PLAN = "VERIFY_QUERY_PLAN"
    UPDATE_RESEARCH_COVERAGE = "UPDATE_RESEARCH_COVERAGE"
    ACADEMIC_RESEARCH = "ACADEMIC_RESEARCH"
    PATENT_RESEARCH = "PATENT_RESEARCH"
    PRODUCT_RESEARCH = "PRODUCT_RESEARCH"
    OPEN_SOURCE_RESEARCH = "OPEN_SOURCE_RESEARCH"

    # Source handling (N07, N08)
    SOURCE_NORMALIZATION = "SOURCE_NORMALIZATION"
    SOURCE_QUALITY = "SOURCE_QUALITY"

    # Analysis (N09-N15)
    CLOSEST_PRIOR_ART = "CLOSEST_PRIOR_ART"
    NOVELTY = "NOVELTY"
    GAP = "GAP"
    METHODOLOGY = "METHODOLOGY"
    EXPERIMENT_REVIEW = "EXPERIMENT_REVIEW"
    CLAIM_EVIDENCE = "CLAIM_EVIDENCE"
    CONTRADICTION_DETECTION = "CONTRADICTION_DETECTION"

    # Adversarial review and finalization (N16-N20)
    RED_TEAM = "RED_TEAM"
    SCORING = "SCORING"
    TRUST_GATE = "TRUST_GATE"
    FINAL_VERIFIER = "FINAL_VERIFIER"
    REPORT_GENERATOR = "REPORT_GENERATOR"


class Phase1ANode(StrEnum):
    """Infrastructure nodes of the Phase 1A harness graph.

    This graph proves checkpointing, interrupt, resume and routing. It performs
    no evaluation and calls no model or external service.
    """

    INITIALIZE_RUN = "INITIALIZE_RUN"
    VALIDATE_PROJECT_STATE = "VALIDATE_PROJECT_STATE"
    CHECK_CRITICAL_INPUT = "CHECK_CRITICAL_INPUT"
    REQUEST_INPUT = "REQUEST_INPUT"
    APPLY_INPUT = "APPLY_INPUT"
    MARK_READY = "MARK_READY"
    MARK_BLOCKED = "MARK_BLOCKED"


PRODUCTION_NODE_ORDER: tuple[NodeId, ...] = (
    NodeId.INTAKE_GUARD,
    NodeId.PROJECT_EXTRACTOR,
    NodeId.PROJECT_EXTRACTOR_VERIFIER,
    NodeId.PROJECT_STATE_MERGE,
    NodeId.PROJECT_TYPE_CLASSIFIER,
    NodeId.CLASSIFICATION_MERGE,
    NodeId.OFFICIAL_REQUIREMENTS_CHECK,
    NodeId.PROBLEM_VALIDATION,
    NodeId.LOAD_PROJECT_STATE,
    NodeId.VALIDATE_RESEARCH_INPUT,
    NodeId.RESEARCH_QUERY_PLANNER,
    NodeId.VERIFY_QUERY_PLAN,
    NodeId.OFFICIAL_REQUIREMENTS_RETRIEVAL,
    NodeId.VERIFY_OFFICIAL_SOURCES,
    NodeId.EXTRACT_OFFICIAL_REQUIREMENTS,
    NodeId.ACADEMIC_RESEARCH,
    NodeId.PATENT_RESEARCH,
    NodeId.PRODUCT_RESEARCH,
    NodeId.OPEN_SOURCE_RESEARCH,
    NodeId.UPDATE_RESEARCH_COVERAGE,
    NodeId.SOURCE_NORMALIZATION,
    NodeId.SOURCE_QUALITY,
    NodeId.CLOSEST_PRIOR_ART,
    NodeId.NOVELTY,
    NodeId.GAP,
    NodeId.METHODOLOGY,
    NodeId.EXPERIMENT_REVIEW,
    NodeId.CLAIM_EVIDENCE,
    NodeId.CONTRADICTION_DETECTION,
    NodeId.RED_TEAM,
    NodeId.SCORING,
    NodeId.TRUST_GATE,
    NodeId.FINAL_VERIFIER,
    NodeId.REPORT_GENERATOR,
)
"""Nominal execution order of the production graph.

Declared for planning. Runtime progress is tracked by EvaluationGraphState
(ADR-002), never inside ProjectState.
It is not an executable schedule: the research branches run in parallel
(section 9), and routing is conditional.
"""

PARALLEL_RESEARCH_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.ACADEMIC_RESEARCH,
        NodeId.PATENT_RESEARCH,
        NodeId.PRODUCT_RESEARCH,
        NodeId.OPEN_SOURCE_RESEARCH,
    }
)
"""Section 9: these branches fan out in parallel after the query planner."""
