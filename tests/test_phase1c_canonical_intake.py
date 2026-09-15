"""Phase 1C: canonical intake model, single taxonomy, verbatim-first extraction.

Three structural corrections under test:

A. Every verified intake field has a canonical destination.
B. Generic technologies are first-class, not approximated as software.
C. One domain taxonomy, shared by classifier and canonical state.

Plus the verbatim-first trust rule (ADR-004) and old-state compatibility.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.graph.state import ProjectState
from src.intake.merge import (
    LIST_FIELD_TARGETS,
    TRACKED_FIELD_TARGETS,
    UNMAPPED_FIELDS,
    merge_classification,
    merge_intake_extraction,
)
from src.intake.verification import (
    ALL_EXTRACTION_FIELDS,
    LIST_VALUE_FIELDS,
    SINGLE_VALUE_FIELDS,
    verify_classification,
    verify_extraction,
)
from src.schemas.common import (
    LEGACY_DOMAIN_MIGRATION,
    ExtractionMode,
    KnowledgeStatus,
    ProjectType,
    TechnicalDomain,
    Tracked,
    migrate_domain,
)
from src.schemas.extraction import (
    FieldKind,
    ProjectClassification,
    ProjectExtraction,
    RejectedExtraction,
    RejectionReason,
)
from src.schemas.project import ProjectDomain, TechnicalBlock
from tests.fixtures import submissions as fx

# ===========================================================================
# A. Canonical destinations
# ===========================================================================

NEW_CANONICAL_FIELDS = {
    "goal": ("goal", None),
    "student_contribution": ("student_contribution", None),
    "current_stage": ("current_stage", None),
    "prototype_status": ("prototype_status", "technical"),
    "data_sources": ("data_sources", "technical"),
}


@pytest.mark.parametrize(
    ("attribute", "block"),
    [(a, b) for a, b in NEW_CANONICAL_FIELDS.values()],
)
def test_new_canonical_field_exists(attribute: str, block: str | None) -> None:
    project = ProjectState()
    target = project if block is None else getattr(project, block)
    assert hasattr(target, attribute)


@pytest.mark.parametrize(
    "attribute", ["goal", "student_contribution", "current_stage"]
)
def test_new_root_fields_default_to_unknown(attribute: str) -> None:
    """Zero Assumption: a new field defaults to UNKNOWN, never a fake value."""
    tracked = getattr(ProjectState(), attribute)
    assert isinstance(tracked, Tracked)
    assert tracked.status is KnowledgeStatus.UNKNOWN
    assert tracked.value is None


def test_prototype_status_defaults_to_unknown() -> None:
    tracked = ProjectState().technical.prototype_status
    assert tracked.status is KnowledgeStatus.UNKNOWN


def test_data_sources_defaults_to_empty() -> None:
    assert ProjectState().technical.data_sources == []


def test_no_verified_field_is_left_homeless() -> None:
    """The Phase 1B gap: five fields had no canonical owner."""
    assert UNMAPPED_FIELDS == frozenset()
    mapped = set(TRACKED_FIELD_TARGETS) | set(LIST_FIELD_TARGETS)
    assert set(ALL_EXTRACTION_FIELDS) <= mapped


def test_previously_orphaned_fields_now_merge(project_b) -> None:
    text = (
        "Our goal is to cut water use. I wrote the firmware myself. "
        "We are at the testing stage. We have a working prototype. "
        "Readings come from the campus weather station."
    )
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(
        goal=fx.value("Cut water use", "Our goal is to cut water use"),
        student_contribution=fx.value("Firmware", "I wrote the firmware myself"),
        current_stage=fx.value("Testing", "We are at the testing stage"),
        prototype_status=fx.value("Working prototype", "We have a working prototype"),
        data_sources=[fx.value("campus weather station", "from the campus weather station")],
    )
    project, report = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )

    assert project.goal.status is KnowledgeStatus.KNOWN
    assert project.student_contribution.status is KnowledgeStatus.KNOWN
    assert project.current_stage.status is KnowledgeStatus.KNOWN
    assert project.technical.prototype_status.status is KnowledgeStatus.KNOWN
    assert project.technical.data_sources == ["campus weather station"]
    assert report.unmapped_fields == []


def test_new_fields_carry_provenance() -> None:
    artifact = fx.make_artifact("Our goal is to cut water use.")
    extraction = ProjectExtraction(
        goal=fx.value("Cut water use", "Our goal is to cut water use")
    )
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )
    assert "artifact=" in project.goal.location
    assert "method=EXACT" in project.goal.location


def test_new_fields_serialize_and_round_trip() -> None:
    project = ProjectState()
    project.goal = Tracked[str].known("A stated goal")
    project.technical.prototype_status = Tracked[str].known("A built prototype")
    restored = ProjectState.model_validate_json(project.model_dump_json())
    assert restored.goal.value == "A stated goal"
    assert restored.technical.prototype_status.value == "A built prototype"


def test_new_fields_survive_a_checkpoint(project_b) -> None:
    from src.graph.persistence import build_serializer
    from src.graph.workflow_state import EvaluationGraphState, new_thread_id
    from uuid import uuid4

    project = project_b
    project.goal = Tracked[str].known("A stated goal")
    project.technical.data_sources = ["a source"]
    state = EvaluationGraphState(
        run_id=uuid4(), thread_id=new_thread_id(), project=project
    )
    serde = build_serializer()
    restored = serde.loads_typed(serde.dumps_typed(state))
    assert restored.project.goal.value == "A stated goal"
    assert restored.project.technical.data_sources == ["a source"]


# ===========================================================================
# B. Generic technology
# ===========================================================================


def test_technologies_is_a_first_class_field() -> None:
    assert "technologies" in TechnicalBlock.model_fields
    assert ProjectState().technical.technologies == []


def test_technology_no_longer_merges_into_software() -> None:
    """The Phase 1B approximation: every technology became software."""
    assert LIST_FIELD_TARGETS["technologies"] == ("technical", "technologies")
    assert LIST_FIELD_TARGETS["software"] == ("technical", "software")


@pytest.mark.parametrize(
    ("term", "excerpt", "text"),
    [
        ("LoRa", "sends readings over LoRa", "The node sends readings over LoRa."),
        ("LiDAR", "The rover uses LiDAR", "The rover uses LiDAR."),
        ("Edge Computing", "We use Edge Computing", "We use Edge Computing."),
        ("ROS", "The robot runs ROS", "The robot runs ROS."),
        ("BLE", "uses BLE for the link", "The node uses BLE for the link."),
        ("FPGA", "an FPGA-backed board", "It runs on an FPGA-backed board."),
    ],
)
def test_a_technology_is_not_filed_as_software(
    term: str, excerpt: str, text: str
) -> None:
    """None of these are software, and calling them software would mislead
    every later research and routing decision."""
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(technologies=[fx.value(term, excerpt)])
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )
    assert project.technical.technologies == [term]
    assert project.technical.software == []


def test_software_and_technology_coexist_without_duplication() -> None:
    text = "We wrote it in Python and deployed on an FPGA-backed board."
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(
        software=[fx.value("Python", "We wrote it in Python")],
        technologies=[fx.value("FPGA", "an FPGA-backed board")],
    )
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )
    assert project.technical.software == ["Python"]
    assert project.technical.technologies == ["FPGA"]


def test_every_technical_category_has_a_distinct_destination() -> None:
    technical_targets = {
        path: target
        for path, target in LIST_FIELD_TARGETS.items()
        if target[0] == "technical"
    }
    attributes = [attribute for _, attribute in technical_targets.values()]
    assert len(attributes) == len(set(attributes)), (
        "two extraction fields share one canonical technical destination"
    )


# ===========================================================================
# C. Single domain taxonomy
# ===========================================================================


def test_there_is_one_domain_enum() -> None:
    from src.schemas.extraction import TechnicalDomain as ExtractionDomain

    assert ExtractionDomain is TechnicalDomain
    assert ProjectDomain is TechnicalDomain


def test_taxonomy_covers_the_declared_scope() -> None:
    expected = {
        "ARTIFICIAL_INTELLIGENCE", "MACHINE_LEARNING", "DEEP_LEARNING",
        "COMPUTER_VISION", "NATURAL_LANGUAGE_PROCESSING", "DATA_SCIENCE",
        "CYBERSECURITY", "INTERNET_OF_THINGS", "ROBOTICS", "EMBEDDED_SYSTEMS",
        "ELECTRONICS", "SENSORS", "SMART_SYSTEMS", "COMPUTER_SCIENCE",
        "SOFTWARE_ENGINEERING", "NETWORKS", "EDGE_COMPUTING", "CLOUD_COMPUTING",
        "HUMAN_COMPUTER_INTERACTION", "OTHER_TECHNICAL", "UNKNOWN",
    }
    assert {d.value for d in TechnicalDomain} == expected


def test_classifier_domain_reaches_state_unchanged() -> None:
    """No projection, so nothing is lost between classifier and state."""
    artifact = fx.make_artifact(fx.AI_IOT_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.ai_iot_classification())
    project, _ = merge_classification(ProjectState(), verified)

    assert set(project.identity.domain) == set(verified.accepted_domains)
    assert TechnicalDomain.MACHINE_LEARNING in project.identity.domain


def test_distinct_domains_are_no_longer_collapsed() -> None:
    """Phase 1B mapped CV, NLP, ML and DS all onto one coarse member."""
    artifact = fx.make_artifact(
        "The system reads scanned forms and answers questions about them."
    )
    classification = ProjectClassification(
        project_type=ProjectType.UNKNOWN,
        project_type_confidence=0.0,
        project_type_excerpt="",
        rationale="Mixed capabilities.",
        domains=[
            {"domain": "COMPUTER_VISION", "excerpt": "reads scanned forms", "confidence": 0.8},
            {"domain": "NATURAL_LANGUAGE_PROCESSING",
             "excerpt": "answers questions about them", "confidence": 0.8},
        ],
    )
    verified = verify_classification(artifact, classification)
    project, _ = merge_classification(ProjectState(), verified)

    assert set(project.identity.domain) == {
        TechnicalDomain.COMPUTER_VISION,
        TechnicalDomain.NATURAL_LANGUAGE_PROCESSING,
    }


# ===========================================================================
# Backward compatibility
# ===========================================================================


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("AI_ML", TechnicalDomain.ARTIFICIAL_INTELLIGENCE),
        ("SOFTWARE", TechnicalDomain.SOFTWARE_ENGINEERING),
        ("IOT", TechnicalDomain.INTERNET_OF_THINGS),
        ("EMBEDDED", TechnicalDomain.EMBEDDED_SYSTEMS),
        ("HCI", TechnicalDomain.HUMAN_COMPUTER_INTERACTION),
        ("OTHER", TechnicalDomain.OTHER_TECHNICAL),
        ("NLP", TechnicalDomain.NATURAL_LANGUAGE_PROCESSING),
        ("ENERGY", TechnicalDomain.OTHER_TECHNICAL),
        ("HEALTH_TECH", TechnicalDomain.OTHER_TECHNICAL),
        ("ENVIRONMENT", TechnicalDomain.OTHER_TECHNICAL),
    ],
)
def test_legacy_domain_migrates(legacy: str, canonical: TechnicalDomain) -> None:
    assert migrate_domain(legacy) is canonical


def test_every_legacy_spelling_is_documented() -> None:
    """Migration is explicit; nothing is silently reinterpreted."""
    for legacy in LEGACY_DOMAIN_MIGRATION:
        assert legacy not in TechnicalDomain.__members__


def test_an_unknown_domain_string_is_not_guessed() -> None:
    """A value with no mapping must raise, not become a plausible substitute."""
    with pytest.raises(ValidationError):
        ProjectState.model_validate({"identity": {"domain": ["QUANTUM_ALCHEMY"]}})


def test_a_phase_0_serialized_state_still_loads() -> None:
    """An old snapshot validates and migrates without a separate script."""
    old_state = {
        "identity": {
            "project_name": {"value": "Legacy", "status": "KNOWN",
                             "origin": "STUDENT_MESSAGE"},
            "project_type": "ENGINEERING_PROJECT",
            "project_type_confidence": 0.8,
            "domain": ["AI_ML", "IOT", "EMBEDDED"],
            "language": "ar",
        },
    }
    restored = ProjectState.model_validate(old_state)
    assert restored.identity.domain == [
        TechnicalDomain.ARTIFICIAL_INTELLIGENCE,
        TechnicalDomain.INTERNET_OF_THINGS,
        TechnicalDomain.EMBEDDED_SYSTEMS,
    ]
    assert restored.identity.project_name.value == "Legacy"
    # New fields appear with honest defaults, not invented values.
    assert restored.goal.status is KnowledgeStatus.UNKNOWN
    assert restored.technical.technologies == []


def test_a_phase_1b_state_without_new_fields_still_loads(project_b) -> None:
    payload = json.loads(project_b.model_dump_json())
    for removed in ("goal", "student_contribution", "current_stage"):
        payload.pop(removed, None)
    payload["technical"].pop("technologies", None)
    payload["technical"].pop("data_sources", None)
    payload["technical"].pop("prototype_status", None)

    restored = ProjectState.model_validate(payload)
    assert restored.goal.status is KnowledgeStatus.UNKNOWN
    assert restored.technical.technologies == []
    assert restored.identity.project_name.value == project_b.identity.project_name.value


# ===========================================================================
# Verbatim-first extraction (ADR-004)
# ===========================================================================


def test_extraction_modes_are_declared() -> None:
    assert {m.value for m in ExtractionMode} == {
        "VERBATIM_SPAN", "VERBATIM_TERM", "CLASSIFICATION", "STUDENT_CLAIM"
    }
    assert FieldKind is ExtractionMode


def test_narrative_fields_use_verbatim_span() -> None:
    for path in (
        "problem_statement", "solution_description", "goal",
        "architecture_description", "student_contribution", "current_stage",
        "prototype_status",
    ):
        assert SINGLE_VALUE_FIELDS[path] is ExtractionMode.VERBATIM_SPAN


def test_atomic_terms_use_verbatim_term() -> None:
    for path in ("technologies", "hardware", "software", "sensors", "algorithms",
                 "datasets", "data_sources"):
        assert LIST_VALUE_FIELDS[path] is ExtractionMode.VERBATIM_TERM


def test_a_paraphrase_never_becomes_canonical() -> None:
    """The exact ADR-004 scenario: a real anchor with a wrong summary."""
    text = "The system detects smoke using optical measurements."
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(
        solution_description=fx.value(
            "The system predicts fire before smoke appears", text
        )
    )
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )
    assert project.solution.description.value == text
    assert "predicts fire" not in project.solution.description.value


def test_the_model_summary_is_retained_as_derived_metadata() -> None:
    text = "The system detects smoke using optical measurements."
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(
        solution_description=fx.value("A smoke detector", text)
    )
    verified = verify_extraction(artifact, extraction)
    field = verified.accepted_for("solution_description")[0]

    assert field.value == text                    # canonical: the source span
    assert field.model_summary == "A smoke detector"  # derived, clearly labelled


def test_a_verbatim_span_value_equals_its_excerpt() -> None:
    text = "Our goal is to reduce collisions in public corridors."
    artifact = fx.make_artifact(text)
    excerpt = "Our goal is to reduce collisions"
    extraction = ProjectExtraction(goal=fx.value("Reduce collisions", excerpt))
    verified = verify_extraction(artifact, extraction)
    assert verified.accepted_for("goal")[0].value == excerpt


def test_a_student_claim_is_recorded_in_the_students_words() -> None:
    """Attributing a paraphrase to the student would misquote them."""
    text = "Our system is 40% faster than existing solutions."
    artifact = fx.make_artifact(text)
    extraction = ProjectExtraction(
        result_claims=[
            {"statement": "It is much quicker", "excerpt": text,
             "claim_type": "PERFORMANCE", "confidence": 0.9}
        ]
    )
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )
    assert project.claims[0].claim == text


def test_verbatim_term_containment_still_applies() -> None:
    artifact = fx.make_artifact(fx.CAMERA_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.mismatched_anchor_extraction())
    assert verified.rejected_fields[0].rejection_reason is (
        RejectionReason.VALUE_NOT_SUPPORTED_BY_ANCHOR
    )


# ===========================================================================
# Conflict handling
# ===========================================================================


def test_a_singleton_conflict_produces_a_contradiction_record() -> None:
    project = ProjectState()
    project.goal = Tracked[str].known("Our goal is to reduce cost")

    artifact = fx.make_artifact("Our goal is to increase accuracy")
    extraction = ProjectExtraction(
        goal=fx.value("Increase accuracy", "Our goal is to increase accuracy")
    )
    project, report = merge_intake_extraction(
        project, verify_extraction(artifact, extraction)
    )

    assert project.goal.status is KnowledgeStatus.CONFLICTED
    assert len(project.contradictions) == 1
    assert project.contradictions[0].requires_student_clarification
    assert report.created_contradictions


def test_additive_list_values_are_not_a_conflict() -> None:
    """Two boards can coexist; that is not a contradiction."""
    project = ProjectState()
    project.technical.hardware = ["Raspberry Pi"]

    artifact = fx.make_artifact("We added an ESP32 module.")
    extraction = ProjectExtraction(
        hardware=[fx.value("ESP32", "We added an ESP32 module")]
    )
    project, report = merge_intake_extraction(
        project, verify_extraction(artifact, extraction)
    )

    assert project.technical.hardware == ["Raspberry Pi", "ESP32"]
    assert project.contradictions == []
    assert report.conflicted_fields == []


def test_repeating_the_same_value_is_not_a_conflict() -> None:
    project = ProjectState()
    project.goal = Tracked[str].known("Our goal is to reduce cost")

    artifact = fx.make_artifact("Our goal is to reduce cost")
    extraction = ProjectExtraction(
        goal=fx.value("Reduce cost", "Our goal is to reduce cost")
    )
    project, report = merge_intake_extraction(
        project, verify_extraction(artifact, extraction)
    )
    assert project.goal.status is KnowledgeStatus.KNOWN
    assert project.contradictions == []
    assert "goal" in report.preserved_fields


# ===========================================================================
# Rejected extraction ledger
# ===========================================================================


def test_the_ledger_records_refused_candidates() -> None:
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())
    ledger = verified.ledger

    assert len(ledger) == 1
    entry = ledger[0]
    assert entry.field == "sensors"
    assert entry.candidate_value == "LiDAR"
    assert entry.rejection_code is RejectionReason.ANCHOR_NOT_FOUND
    assert entry.artifact_id == artifact.artifact_id
    assert entry.mode is ExtractionMode.VERBATIM_TERM


def test_the_ledger_never_reaches_canonical_state() -> None:
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.technical.sensors == []
    assert "ledger" not in ProjectState.model_fields


def test_the_ledger_stores_no_hidden_reasoning() -> None:
    banned = {"reasoning", "chain_of_thought", "thoughts", "rationale"}
    assert banned & set(RejectedExtraction.model_fields) == set()


def test_only_a_rejected_field_can_enter_the_ledger() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    with pytest.raises(ValueError, match="only a rejected field"):
        RejectedExtraction.from_field(verified.accepted_fields[0])
