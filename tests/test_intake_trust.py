"""Phase 1B trust-boundary tests: anchors, verification and merge.

These are the tests that decide whether the system can be trusted not to invent
project facts. Every one runs with no API key and no network.

The governing rule under test: **a false UNKNOWN is preferable to a fabricated
KNOWN.**
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.graph.state import ProjectState
from src.intake.anchors import (
    collapse_whitespace,
    normalize_unicode,
    value_supported_by_anchor,
    verify_anchor,
)
from src.intake.merge import merge_classification, merge_intake_extraction
from src.intake.verification import verify_classification, verify_extraction
from src.schemas.claim import ClaimOrigin, ClaimStatus
from src.schemas.common import KnowledgeStatus, ProjectType, Tracked, ValueOrigin
from src.schemas.extraction import (
    AnchorVerificationMethod,
    FieldKind,
    ProjectExtraction,
    RejectionReason,
    TechnicalDomain,
)
from tests.fixtures import submissions as fx


# ===========================================================================
# Anchor verification
# ===========================================================================


def test_exact_excerpt_verifies_with_exact_offsets() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    anchor = verify_anchor(
        artifact.artifact_id, artifact.original_text, "three ultrasonic sensors"
    )
    assert anchor.verified
    assert anchor.method is AnchorVerificationMethod.EXACT
    start, end = anchor.matches[0].start, anchor.matches[0].end
    assert artifact.original_text[start:end] == "three ultrasonic sensors"


def test_absent_excerpt_does_not_verify() -> None:
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    anchor = verify_anchor(
        artifact.artifact_id, artifact.original_text, "using a LiDAR sensor array"
    )
    assert not anchor.verified
    assert anchor.method is AnchorVerificationMethod.NOT_FOUND
    assert anchor.matches == []


def test_empty_excerpt_does_not_verify() -> None:
    artifact = fx.make_artifact(fx.MINIMAL_PROJECT_TEXT)
    anchor = verify_anchor(artifact.artifact_id, artifact.original_text, "   ")
    assert not anchor.verified


def test_multiple_occurrences_are_all_recorded() -> None:
    """An excerpt appearing twice is not invalid, and code must not pick one."""
    artifact = fx.make_artifact("sensor here and sensor there")
    anchor = verify_anchor(artifact.artifact_id, artifact.original_text, "sensor")
    assert anchor.occurrence_count == 2
    assert [m.start for m in anchor.matches] == [0, 16]


def test_whitespace_normalization_is_recorded_as_such() -> None:
    """A match that needed folding must not masquerade as an exact quote."""
    artifact = fx.make_artifact(fx.WHITESPACE_PROJECT_TEXT)
    anchor = verify_anchor(
        artifact.artifact_id, artifact.original_text, "Our project uses a pressure sensor"
    )
    assert anchor.verified
    assert anchor.method is AnchorVerificationMethod.NORMALIZED_WHITESPACE


def test_line_ending_differences_do_not_break_matching() -> None:
    artifact = fx.make_artifact("line one\r\nline two")
    assert verify_anchor(artifact.artifact_id, artifact.original_text, "line one\nline two").verified


def test_arabic_excerpt_verifies_without_translation() -> None:
    artifact = fx.make_artifact(fx.ARABIC_PROJECT_TEXT)
    anchor = verify_anchor(
        artifact.artifact_id, artifact.original_text, "مشروعنا اسمه حارس النخيل"
    )
    assert anchor.verified
    assert anchor.method is AnchorVerificationMethod.EXACT


def test_mixed_language_excerpt_verifies() -> None:
    artifact = fx.make_artifact(fx.MIXED_LANGUAGE_TEXT)
    assert verify_anchor(
        artifact.artifact_id, artifact.original_text, "استخدمنا YOLOv8 مع Raspberry Pi"
    ).verified


def test_unicode_normalization_preserves_arabic_content() -> None:
    text = "سوسة النخيل"
    assert normalize_unicode(text) == text
    assert collapse_whitespace("a   b") == "a b"


# ===========================================================================
# Value-to-anchor support
# ===========================================================================


def test_verbatim_value_present_in_anchor_is_supported() -> None:
    assert value_supported_by_anchor(
        "YOLOv8", "We trained YOLOv8 on 4,000 images", FieldKind.VERBATIM_TERM
    )


def test_verbatim_value_absent_from_anchor_is_unsupported() -> None:
    """The subtle attack: a real quote attached to an invented value."""
    assert not value_supported_by_anchor(
        "YOLOv8", "uses a camera", FieldKind.VERBATIM_TERM
    )


def test_verbatim_span_accepts_any_non_empty_excerpt() -> None:
    """VERBATIM_SPAN replaces the value with the excerpt, so containment is moot."""
    assert value_supported_by_anchor(
        "Visually impaired users need obstacle detection",
        "to detect obstacles for visually impaired users",
        FieldKind.VERBATIM_SPAN,
    )
    assert not value_supported_by_anchor("anything", "   ", FieldKind.VERBATIM_SPAN)


def test_verbatim_support_is_case_insensitive() -> None:
    assert value_supported_by_anchor(
        "raspberry pi", "connected to a Raspberry Pi", FieldKind.VERBATIM_TERM
    )


def test_verbatim_support_works_for_arabic_values() -> None:
    assert value_supported_by_anchor(
        "كاميرا", "نستخدم كاميرا لمراقبة أشجار النخيل", FieldKind.VERBATIM_TERM
    )


# ===========================================================================
# Extraction verification
# ===========================================================================


def test_explicit_fact_is_accepted() -> None:
    """Stated in the submission, anchored, and the anchor states the value."""
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())

    sensors = verified.accepted_for("sensors")
    assert len(sensors) == 1
    assert sensors[0].value == "three ultrasonic sensors"
    assert sensors[0].anchor.verified


def test_hallucinated_fact_is_rejected() -> None:
    """Fabricated value AND fabricated excerpt."""
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())

    assert verified.accepted_fields == []
    rejected = verified.rejected_fields[0]
    assert rejected.value == "LiDAR"
    assert rejected.rejection_reason is RejectionReason.ANCHOR_NOT_FOUND


def test_high_model_confidence_does_not_rescue_a_hallucination() -> None:
    """Model confidence never participates in the accept decision."""
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())
    rejected = verified.rejected_fields[0]
    assert rejected.model_confidence == pytest.approx(0.99)
    assert rejected.accepted is False


def test_valid_anchor_with_unsupported_value_is_rejected() -> None:
    """Anchor existence alone is not enough."""
    artifact = fx.make_artifact(fx.CAMERA_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.mismatched_anchor_extraction())

    rejected = verified.rejected_fields[0]
    assert rejected.value == "YOLOv8"
    assert rejected.anchor.verified, "the excerpt itself does exist"
    assert rejected.rejection_reason is RejectionReason.VALUE_NOT_SUPPORTED_BY_ANCHOR


def test_rejections_are_recorded_rather_than_dropped() -> None:
    """'The model proposed X and we refused it' stays observable."""
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())
    assert len(verified.rejected_fields) == 1
    assert verified.rejected_fields[0].rejection_reason is not None


def test_out_of_range_confidence_is_dropped_not_clipped() -> None:
    artifact = fx.make_artifact(fx.CAMERA_PROJECT_TEXT)
    extraction = ProjectExtraction(
        hardware=[fx.value("camera", "uses a camera", confidence=1.7)]
    )
    verified = verify_extraction(artifact, extraction)
    assert verified.accepted_fields[0].model_confidence is None


def test_arabic_extraction_is_accepted_and_preserved() -> None:
    artifact = fx.make_artifact(fx.ARABIC_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.arabic_extraction())

    names = verified.accepted_for("project_name")
    assert names[0].value == "حارس النخيل"
    assert verified.accepted_for("hardware")[0].value == "كاميرا"


def test_mixed_language_technical_terms_survive_verification() -> None:
    artifact = fx.make_artifact(fx.MIXED_LANGUAGE_TEXT)
    verified = verify_extraction(artifact, fx.mixed_language_extraction())
    values = {f.value for f in verified.accepted_fields}
    assert {"YOLOv8", "Raspberry Pi"} <= values


def test_conflict_requires_both_sides_anchored() -> None:
    artifact = fx.make_artifact(fx.CONFLICTING_DATASET_TEXT)
    verified = verify_extraction(artifact, fx.conflicting_dataset_extraction())
    assert len(verified.accepted_conflicts) == 1
    assert verified.accepted_conflicts[0].subject == "dataset size"


# ===========================================================================
# Merge into canonical state
# ===========================================================================


def test_verified_field_becomes_known() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, report = merge_intake_extraction(ProjectState(), verified)

    assert project.identity.project_name.value == "Sentinel"
    assert project.identity.project_name.status is KnowledgeStatus.KNOWN
    assert project.identity.project_name.origin is ValueOrigin.STUDENT_MESSAGE
    assert "project_name" in report.applied_fields


def test_merge_records_provenance_on_the_tracked_value() -> None:
    """'Where did the system get this?' must be answerable from the state."""
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)

    location = project.identity.project_name.location
    assert str(artifact.artifact_id) in location
    assert "method=EXACT" in location
    assert "ranges=[" in location


def test_rejected_field_never_reaches_canonical_state() -> None:
    artifact = fx.make_artifact(fx.OBSTACLE_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.hallucinated_sensor_extraction())
    project, report = merge_intake_extraction(ProjectState(), verified)

    assert project.technical.sensors == []
    assert report.applied_fields == []
    assert "sensors" in report.rejected_fields


def test_missing_information_stays_unknown() -> None:
    """No dataset, no accuracy, no baseline -- and no guesses."""
    artifact = fx.make_artifact(fx.MINIMAL_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.minimal_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.technical.datasets == []
    assert project.methodology.baseline == []
    assert project.methodology.metrics == []
    assert project.identity.project_name.status is KnowledgeStatus.UNKNOWN
    assert project.methodology.hypothesis.status is KnowledgeStatus.UNKNOWN


def test_merge_returns_a_fully_validated_state() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)
    assert ProjectState.model_validate(project.model_dump()) == project


def test_merge_does_not_mutate_the_input_state() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    original = ProjectState()
    merge_intake_extraction(original, verified)
    assert original.identity.project_name.status is KnowledgeStatus.UNKNOWN


# ===========================================================================
# Existing-state protection (multi-turn intake)
# ===========================================================================


def test_later_turn_does_not_erase_an_earlier_known_value() -> None:
    """Turn 1 names the project; turn 2 omits it. The name must survive."""
    turn1 = fx.make_artifact("Project name: Sentinel", sequence=1)
    verified1 = verify_extraction(
        turn1, fx.named_project_extraction("Sentinel", "Project name: Sentinel")
    )
    project, _ = merge_intake_extraction(ProjectState(), verified1)
    assert project.identity.project_name.value == "Sentinel"

    turn2 = fx.make_artifact("We use three microphones.", sequence=2)
    verified2 = verify_extraction(
        turn2,
        ProjectExtraction(
            hardware=[fx.value("three microphones", "We use three microphones")]
        ),
    )
    project, _ = merge_intake_extraction(project, verified2)

    assert project.identity.project_name.value == "Sentinel"
    assert project.identity.project_name.status is KnowledgeStatus.KNOWN
    assert "three microphones" in project.technical.hardware


def test_identical_repeat_value_is_preserved_not_duplicated() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)
    project, report = merge_intake_extraction(project, verified)

    assert project.technical.sensors == ["three ultrasonic sensors"]
    assert "project_name" in report.preserved_fields


def test_a_different_value_for_a_known_field_creates_a_conflict() -> None:
    """Never last-writer-wins on a KNOWN field."""
    project = ProjectState()
    project.identity.project_name = Tracked[str].known("Sentinel")

    turn2 = fx.make_artifact("Project name: Guardian")
    verified = verify_extraction(
        turn2, fx.named_project_extraction("Guardian", "Project name: Guardian")
    )
    project, report = merge_intake_extraction(project, verified)

    assert project.identity.project_name.status is KnowledgeStatus.CONFLICTED
    assert project.identity.project_name.value is None
    assert set(project.identity.project_name.conflicting_values) == {
        "Sentinel",
        "Guardian",
    }
    assert "project_name" in report.conflicted_fields


def test_conflicting_dataset_sizes_are_not_silently_resolved() -> None:
    artifact = fx.make_artifact(fx.CONFLICTING_DATASET_TEXT)
    verified = verify_extraction(artifact, fx.conflicting_dataset_extraction())
    project, report = merge_intake_extraction(ProjectState(), verified)

    assert len(project.contradictions) == 1
    contradiction = project.contradictions[0]
    assert "2,000 images" in contradiction.conflicting_statements[0]
    assert "5,000 images" in contradiction.conflicting_statements[1]
    assert contradiction.requires_student_clarification
    assert report.created_contradictions == ["CT-001"]


# ===========================================================================
# Student claim isolation
# ===========================================================================


def test_student_performance_statement_becomes_an_unsupported_claim() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, report = merge_intake_extraction(ProjectState(), verified)

    assert len(project.claims) == 1
    claim = project.claims[0]
    assert claim.origin is ClaimOrigin.STUDENT
    assert claim.status is ClaimStatus.UNSUPPORTED
    assert claim.evidence_ids == []
    assert claim.confidence == 0.0
    assert report.created_claims == ["C-001"]


def test_intake_creates_no_evidence_and_no_sources() -> None:
    """A student statement is not independently verified evidence."""
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.evidence == []
    assert project.sources == []


def test_intake_never_sets_novelty_gap_or_scores() -> None:
    """Phase 1B knows what the student said, not whether it is true."""
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)

    assert project.novelty.level is None
    assert project.scores == []
    assert project.trust_gate is None
    assert project.findings == []


def test_a_student_novelty_assertion_stays_a_claim() -> None:
    """'No one has done this before' is a claim, not a novelty finding."""
    text = "No one has done this before in our region."
    artifact = fx.make_artifact(text)
    from src.schemas.extraction import ExtractedClaim

    extraction = ProjectExtraction(
        result_claims=[
            ExtractedClaim(
                statement="No one has done this before.",
                excerpt="No one has done this before",
                claim_type="NOVELTY",
                confidence=0.9,
            )
        ]
    )
    project, _ = merge_intake_extraction(
        ProjectState(), verify_extraction(artifact, extraction)
    )

    assert project.claims[0].status is ClaimStatus.UNSUPPORTED
    assert project.novelty.level is None


def test_duplicate_claims_are_not_recreated() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_extraction(artifact, fx.sensor_project_extraction())
    project, _ = merge_intake_extraction(ProjectState(), verified)
    project, report = merge_intake_extraction(project, verified)

    assert len(project.claims) == 1
    assert report.created_claims == []


# ===========================================================================
# Classification
# ===========================================================================


def test_engineering_project_is_classified_and_merged() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.engineering_classification())
    project, report = merge_classification(ProjectState(), verified)

    assert project.identity.project_type is ProjectType.ENGINEERING_PROJECT
    assert project.identity.project_type_confidence == pytest.approx(0.88)
    assert "identity.project_type" in report.applied_fields


def test_scientific_research_is_classified() -> None:
    artifact = fx.make_artifact(fx.RESEARCH_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.research_classification())
    assert verified.project_type is ProjectType.SCIENTIFIC_RESEARCH


def test_hybrid_project_is_classified() -> None:
    artifact = fx.make_artifact(fx.HYBRID_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.hybrid_classification())
    assert verified.project_type is ProjectType.HYBRID


def test_ambiguous_project_stays_unknown_with_no_confidence() -> None:
    artifact = fx.make_artifact(fx.AMBIGUOUS_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.unknown_classification())
    assert verified.project_type is ProjectType.UNKNOWN
    assert verified.project_type_confidence is None


def test_unanchored_classification_falls_back_to_unknown() -> None:
    """A confident type whose excerpt does not exist is not accepted."""
    artifact = fx.make_artifact(fx.AMBIGUOUS_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.unanchored_type_classification())

    assert verified.project_type is ProjectType.UNKNOWN
    assert verified.project_type_confidence is None
    assert verified.type_anchor is None


def test_multi_domain_project_records_both_domains() -> None:
    artifact = fx.make_artifact(fx.AI_IOT_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.ai_iot_classification())
    project, _ = merge_classification(ProjectState(), verified)

    assert TechnicalDomain.INTERNET_OF_THINGS in verified.accepted_domains
    assert TechnicalDomain.MACHINE_LEARNING in verified.accepted_domains
    # One taxonomy end to end: what the classifier emits is what the state stores.
    assert set(project.identity.domain) == {
        TechnicalDomain.INTERNET_OF_THINGS,
        TechnicalDomain.MACHINE_LEARNING,
    }


def test_plain_software_project_does_not_become_ai() -> None:
    """A CRUD application must not be over-classified."""
    artifact = fx.make_artifact(fx.CRUD_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.software_only_classification())
    project, _ = merge_classification(ProjectState(), verified)

    assert TechnicalDomain.ARTIFICIAL_INTELLIGENCE not in verified.accepted_domains
    assert project.identity.domain == [TechnicalDomain.SOFTWARE_ENGINEERING]


def test_hallucinated_domain_is_rejected() -> None:
    artifact = fx.make_artifact(fx.CAMERA_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.hallucinated_domain_classification())
    project, _ = merge_classification(ProjectState(), verified)

    assert verified.accepted_domains == []
    assert project.identity.domain == []


def test_classification_does_not_touch_factual_fields() -> None:
    """Inference is confined to type and domain."""
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.engineering_classification())
    project, _ = merge_classification(ProjectState(), verified)

    assert project.identity.project_name.status is KnowledgeStatus.UNKNOWN
    assert project.technical.sensors == []
    assert project.claims == []


def test_existing_classification_is_not_silently_changed() -> None:
    project = ProjectState()
    project.identity.project_type = ProjectType.SCIENTIFIC_RESEARCH
    project.identity.project_type_confidence = 0.9

    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.engineering_classification())
    project, report = merge_classification(project, verified)

    assert project.identity.project_type is ProjectType.SCIENTIFIC_RESEARCH
    assert "identity.project_type" in report.conflicted_fields


def test_rationale_is_short_and_not_a_reasoning_trace() -> None:
    artifact = fx.make_artifact(fx.SENSOR_PROJECT_TEXT)
    verified = verify_classification(artifact, fx.engineering_classification())
    assert len(verified.rationale) < 200
    assert verified.rationale == "Includes a prototype build and a corridor test."
