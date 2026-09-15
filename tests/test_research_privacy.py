"""PII minimization: research queries are about the project, never the student.

Arabic sample values are built from code points so this file stays English-only.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from src.graph.workflow_state import EvaluationGraphState
from src.research.privacy import (
    REDACTION_TOKEN,
    PiiKind,
    ResearchPrivacyContext,
    contains_pii,
    detect_pii,
    redact_pii,
)

CONTEXT = ResearchPrivacyContext.from_identity(
    person_names=("Sara Alqahtani",),
    school_names=("Al Waha Secondary School",),
    emails=("sara.alq@example.com",),
    phone_numbers=("+966 55 123 4567",),
    national_ids=("1098765432",),
    addresses=("12 Palm Street",),
)

ARABIC_NAME = "".join(chr(c) for c in (0x0646, 0x0648, 0x0631, 0x0629))


def _kinds(text: str, context: ResearchPrivacyContext = CONTEXT) -> set[PiiKind]:
    return {finding.kind for finding in detect_pii(text, context)}


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("contact sara.alq@example.com", PiiKind.EMAIL),
        ("call +966 55 123 4567", PiiKind.PHONE_NUMBER),
        ("id 1098765432", PiiKind.NATIONAL_ID),
        ("results by ALQAHTANI", PiiKind.PERSON_NAME),
        ("students at al waha secondary school", PiiKind.SCHOOL_NAME),
        ("flood on 12 Palm Street", PiiKind.ADDRESS),
    ],
)
def test_detects_each_kind_of_personal_data(text: str, kind: PiiKind) -> None:
    assert kind in _kinds(text)


def test_patterns_work_without_an_identity_context() -> None:
    empty = ResearchPrivacyContext()
    assert contains_pii("mail someone@example.org", empty)
    assert contains_pii("phone 0551234567", empty)


@pytest.mark.parametrize(
    "text",
    ["YOLOv8 plant disease limitations", "LSTM electricity demand 2024 2025", "Saratoga sensor",
     "MQ-135 vs electrochemical sensors", "random forest 97% accuracy"],
)
def test_ordinary_project_text_is_not_flagged(text: str) -> None:
    assert detect_pii(text, CONTEXT) == []


def test_redaction_removes_every_finding() -> None:
    text = ("Sara Alqahtani from Al Waha Secondary School (sara.alq@example.com, "
            "+966 55 123 4567, 12 Palm Street) built a leak sensor")
    redacted, count = redact_pii(text, CONTEXT)
    assert detect_pii(redacted, CONTEXT) == []
    assert REDACTION_TOKEN in redacted
    assert count >= 5
    assert "leak sensor" in redacted


def test_arabic_name_is_detected_and_redacted() -> None:
    context = ResearchPrivacyContext.from_identity(person_names=(ARABIC_NAME,))
    text = f"{ARABIC_NAME} gas leak"
    assert PiiKind.PERSON_NAME in _kinds(text, context)
    redacted, _ = redact_pii(text, context)
    assert ARABIC_NAME not in redacted
    assert detect_pii(redacted, context) == []


def test_arabic_indic_digits_are_detected_and_left_intact_elsewhere() -> None:
    phone = "".join(chr(0x0660 + int(d)) for d in "0551234567")
    assert PiiKind.PHONE_NUMBER in _kinds(f"call {phone}", ResearchPrivacyContext())
    short = "".join(chr(0x0660 + int(d)) for d in "20")
    redacted, count = redact_pii(f"weight {short}", ResearchPrivacyContext())
    assert count == 0 and short in redacted


def test_identity_context_never_enters_checkpointed_state() -> None:
    assert not issubclass(ResearchPrivacyContext, BaseModel)
    for name, field in EvaluationGraphState.model_fields.items():
        assert "privacy" not in name
        assert "ResearchPrivacyContext" not in str(field.annotation)
