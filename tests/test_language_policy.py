"""Guards for the project language policy.

Developer layer, internal agent layer and structured data layer are English
only; Arabic is permitted only as student-supplied data in value positions.
These tests exist so that a regression is caught by pytest rather than by a
broken terminal rendering.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.config.settings import (
    DEFAULT_SETTINGS,
    DEVELOPER_LANGUAGE,
    STUDENT_DEFAULT_LANGUAGE,
)
from src.graph.state import ProjectState
from src.schemas.claim import ClaimRecord, ClaimStatus, ClaimType
from src.schemas.common import KnowledgeStatus, Tracked, ValueOrigin
from src.schemas.evidence import (
    EvidenceLocation,
    EvidenceRecord,
    EvidenceType,
)
from src.schemas.source import SourceRecord, SourceType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

# The original architecture document is a source artifact and stays as authored.
EXEMPT_PATHS = {PROJECT_ROOT / "docs" / "mawhiba_agent_system_architecture_v1.md"}

# Arabic is permitted only as DATA, never as developer prose. Each entry states
# why that file legitimately carries Arabic characters, so the exemption is a
# reviewed decision rather than a growing escape hatch.
ARABIC_AS_DATA: dict[Path, str] = {
    PROJECT_ROOT / "scripts" / "phase3a_gold_lang.py": "Phase 3A Gold student methodology sentences in Arabic and mixed language, including instruction-like ones kept as inert exact-excerpt data",
    PROJECT_ROOT / "scripts" / "phase3a_gold_templates2.py": "Phase 3A Gold templates carrying a diacritized Arabic sentence and Arabic prose-twin text as data",
    PROJECT_ROOT / "scripts" / "phase3a_gold_templates3.py": "Phase 3A Gold templates carrying Arabic prose-twin text as data",
    PROJECT_ROOT / "evals" / "methodology_review" / "v1" / "cases.jsonl": "synthetic Arabic and mixed-language student methodology text, including instruction-like sentences that must stay inert data",
    Path(__file__).resolve(): "Arabic sample values proving source preservation",
    PROJECT_ROOT
    / "docs"
    / "data_contracts.md": "one JSON example with an Arabic claim value",
    PROJECT_ROOT
    / "src"
    / "intake"
    / "anchors.py": "invisible-character table contains bidi and BOM code points "
                    "that fall inside the scanned ranges; they are data, not prose",
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "submissions.py": "synthetic Arabic student submissions",
    PROJECT_ROOT / "tests" / "test_phase3b_architecture.py": "Arabic and mixed-language prompt-injection "
    "sentences appended to a student protocol excerpt, proving Phase 3B rules and postures do not change "
    "with the language or content of inert source text",
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "phase3a_submissions.py": "Arabic and mixed-language student methodology sentences, including "
                                "instruction-like ones, proving Phase 3A treats source text in any "
                                "language as inert exact-excerpt data and that safety rests on the "
                                "typed contract, not on recognising words",
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "phase2j_sources.py": "Arabic and mixed-language source text, including instruction-like "
                            "sentences, proving Phase 2J treats it as inert evidence data and "
                            "that model prose in any language cannot reach a canonical record",
    PROJECT_ROOT
    / "scripts"
    / "generate_phase2j_gold_core.py": "one-off generator language packs: the Arabic and mixed-language Gold "
                                       "claims and source text (limitations, capabilities, conditions, "
                                       "counterevidence, absence sentences and an instruction-like phrase "
                                       "as inert evidence data) it writes out",
    PROJECT_ROOT
    / "evals"
    / "research_engineering_gap"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language claims and patent, product and repository source "
                     "text, including Arabic instruction-like phrases that must stay inert evidence data",
    PROJECT_ROOT
    / "tests"
    / "test_intake_trust.py": "Arabic extraction and anchor test data",
    PROJECT_ROOT / "tests" / "test_llm_layer.py": "Arabic range in a prompt-language check",
    PROJECT_ROOT
    / "tests"
    / "test_phase1b_graph.py": "Arabic values asserted through the intake graph",
    PROJECT_ROOT
    / "evals"
    / "intake"
    / "v1"
    / "cases.jsonl": "synthetic Arabic Gold submissions and expected values",
    PROJECT_ROOT
    / "evals"
    / "research_planning"
    / "v1"
    / "cases.jsonl": "synthetic Arabic project values, source terms and synthetic names",
    PROJECT_ROOT
    / "evals"
    / "academic_retrieval"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language academic queries and paper titles",
    PROJECT_ROOT
    / "tests"
    / "test_phase2c_evidence_extraction.py": "synthetic Arabic source content proving "
                                             "an Arabic excerpt verifies to exact offsets",
    PROJECT_ROOT
    / "evals"
    / "evidence_extraction"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language source abstracts",
    PROJECT_ROOT
    / "evals"
    / "claim_evidence_alignment"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language claims and evidence excerpts",
    PROJECT_ROOT
    / "scripts"
    / "generate_phase2d_gold.py": "one-off generator embedding the Arabic and "
                                  "mixed-language Gold claim/evidence literals it writes out",
    PROJECT_ROOT
    / "scripts"
    / "generate_phase2f_gold.py": "one-off generator embedding the Arabic and "
                                  "mixed-language Gold claim/excerpt literals it writes out",
    PROJECT_ROOT
    / "scripts"
    / "generate_phase2g_gold.py": "one-off generator embedding the Arabic and "
                                  "mixed-language Gold claim, injection and patent "
                                  "abstract literals it writes out",
    PROJECT_ROOT
    / "evals"
    / "patent_prior_art"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language claims, injection "
                     "attempts and patent abstracts",
    PROJECT_ROOT
    / "evals"
    / "product_oss_prior_art"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language claims and an Arabic "
                     "injection attempt for product/open-source discovery",
    PROJECT_ROOT
    / "scripts"
    / "generate_phase2i_gold.py": "one-off generator embedding the Arabic and "
                                  "mixed-language Gold claims and candidate source "
                                  "text it writes out",
    PROJECT_ROOT
    / "evals"
    / "novelty_differentiation"
    / "v1"
    / "cases.jsonl": "synthetic Arabic and mixed-language claims, patent, product "
                     "and repository source text, and an Arabic instruction-like "
                     "phrase appearing as inert candidate data",
}

FILES_ALLOWED_TO_QUOTE_ARABIC = set(ARABIC_AS_DATA)


GENERATED_OUTPUT_DIRS = frozenset({".venv", ".pytest_cache", "graphify-out"})
"""Directories that hold generated output rather than authored source.

The language policy governs surfaces a developer writes. A tool's own output --
a virtualenv, a pytest cache, a code-graph report that quotes the Arabic
architecture document back at us -- is not one of them, and is not in the
repository either. Every *authored* file on disk is still scanned, including
untracked ones, so the policy cannot be bypassed by not committing a file yet.
"""


def _tracked_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.py", "*.md", "*.toml"):
        for path in PROJECT_ROOT.rglob(pattern):
            if GENERATED_OUTPUT_DIRS & set(path.parts):
                continue
            files.append(path)
    return files


# --- configuration ---------------------------------------------------------

def test_language_constants_are_declared() -> None:
    assert DEVELOPER_LANGUAGE == "en"
    assert STUDENT_DEFAULT_LANGUAGE == "ar"


def test_settings_expose_both_languages() -> None:
    assert DEFAULT_SETTINGS.developer_language == "en"
    assert DEFAULT_SETTINGS.student_default_language == "ar"


def test_project_identity_defaults_to_the_student_language() -> None:
    assert ProjectState().identity.language == STUDENT_DEFAULT_LANGUAGE


# --- developer surfaces stay English ---------------------------------------

@pytest.mark.parametrize(
    "path",
    [p for p in _tracked_source_files() if p not in EXEMPT_PATHS],
    ids=lambda p: str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"),
)
def test_developer_surfaces_contain_no_arabic(path: Path) -> None:
    """Code, tests, config and developer docs must be English only."""
    if path.resolve() in FILES_ALLOWED_TO_QUOTE_ARABIC:
        pytest.skip("file intentionally quotes an Arabic sample value")
    assert not ARABIC.search(path.read_text(encoding="utf-8")), (
        f"{path} contains Arabic text in a developer-facing surface"
    )


def test_no_python_module_contains_arabic() -> None:
    offenders = [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if ".venv" not in path.parts
        and path.resolve() not in FILES_ALLOWED_TO_QUOTE_ARABIC
        and ARABIC.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_enum_values_are_ascii_upper_snake_case() -> None:
    """Enum values travel into JSON, logs and traces, so they stay ASCII."""
    from src.schemas.claim import ClaimStatus as _ClaimStatus
    from src.schemas.common import EvaluationStatus, ProjectType, Severity
    from src.schemas.trust import BlockerCode

    for enum_cls in (_ClaimStatus, EvaluationStatus, Severity, ProjectType, BlockerCode):
        for member in enum_cls:
            assert member.value.isascii(), f"{enum_cls.__name__}.{member.name}"
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", member.value), (
                f"{enum_cls.__name__}.{member.name} = {member.value!r}"
            )


def test_schema_field_names_are_ascii_snake_case() -> None:
    for model in (ProjectState, ClaimRecord, EvidenceRecord, SourceRecord):
        for name in model.model_fields:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{model.__name__}.{name}"


# --- Arabic is allowed as data ---------------------------------------------

def test_arabic_claim_text_is_stored_verbatim() -> None:
    """The value may be Arabic; the structure stays English."""
    arabic_claim = "النظام يقلل استهلاك الطاقة بنسبة 20%"
    claim = ClaimRecord(
        claim_id="C-001",
        claim=arabic_claim,
        claim_type=ClaimType.PERFORMANCE,
        status=ClaimStatus.UNSUPPORTED,
    )
    assert claim.claim == arabic_claim
    dumped = claim.model_dump()
    assert dumped["claim"] == arabic_claim
    assert dumped["status"] is ClaimStatus.UNSUPPORTED
    assert all(key.isascii() for key in dumped)


def test_arabic_source_quote_is_not_translated() -> None:
    arabic_quote = "الدقة ٨٧٪"
    evidence = EvidenceRecord(
        evidence_id="E-001",
        source_id="SRC-001",
        evidence_type=EvidenceType.STUDENT_STATEMENT,
        statement=arabic_quote,
        location=EvidenceLocation(page=3, quote_or_extract=arabic_quote),
        verified=True,
    )
    assert evidence.location.quote_or_extract == arabic_quote


def test_arabic_tracked_value_keeps_its_english_status() -> None:
    arabic_name = "كاشف أمراض"
    field = Tracked[str].known(arabic_name, origin=ValueOrigin.STUDENT_FILE)
    assert field.value == arabic_name
    assert field.status is KnowledgeStatus.KNOWN
    assert field.origin.value.isascii()


def test_arabic_survives_the_human_input_patch_boundary() -> None:
    """Student text applied on resume is stored as written, never translated."""
    from src.workflow.patches import (
        PatchableField,
        ProjectPatch,
        apply_project_patch,
    )

    arabic = "تسرب المياه لا يكتشف مبكرا"
    updated = apply_project_patch(
        ProjectState(),
        ProjectPatch(values={PatchableField.PROBLEM_STATEMENT: arabic}),
    )
    assert updated.problem.statement.value == arabic
    assert updated.problem.statement.status.value.isascii()
    assert updated.problem.statement.origin.value.isascii()


def test_workflow_enum_values_are_ascii() -> None:
    """Workflow enums reach logs, traces and checkpoints, so they stay ASCII."""
    from src.graph.contracts import InterruptType, NodeStatus, WorkflowStatus
    from src.graph.registry import NodeId, Phase1ANode
    from src.workflow.errors import WorkflowErrorCode

    for enum_cls in (
        WorkflowStatus,
        NodeStatus,
        InterruptType,
        WorkflowErrorCode,
        NodeId,
        Phase1ANode,
    ):
        for member in enum_cls:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", member.value), (
                f"{enum_cls.__name__}.{member.name} = {member.value!r}"
            )


def test_intake_enum_values_are_ascii() -> None:
    """Phase 1B enums reach JSON, logs and checkpoints, so they stay ASCII."""
    from src.llm.contracts import ModelCallStatus, ModelTask
    from src.schemas.extraction import (
        AnchorVerificationMethod,
        FieldKind,
        RejectionReason,
        TechnicalDomain,
    )
    from src.schemas.submission import ArtifactType

    for enum_cls in (
        ModelCallStatus,
        ModelTask,
        TechnicalDomain,
        AnchorVerificationMethod,
        FieldKind,
        RejectionReason,
        ArtifactType,
    ):
        for member in enum_cls:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", member.value), (
                f"{enum_cls.__name__}.{member.name} = {member.value!r}"
            )


def test_internal_prompts_are_english_only() -> None:
    """Internal prompts stay English even when the project is Arabic."""
    from src.llm.prompts import (
        PROJECT_CLASSIFIER_PROMPT_V1,
        PROJECT_EXTRACTOR_PROMPT_V1,
    )

    for prompt in (PROJECT_EXTRACTOR_PROMPT_V1, PROJECT_CLASSIFIER_PROMPT_V1):
        assert not ARABIC.search(prompt)
        assert "PRESERVE THE ORIGINAL LANGUAGE" in prompt


def test_extraction_schema_field_names_are_ascii() -> None:
    from src.schemas.extraction import ProjectExtraction, VerifiedExtraction
    from src.schemas.submission import StudentSubmissionArtifact

    for model in (ProjectExtraction, VerifiedExtraction, StudentSubmissionArtifact):
        for name in model.model_fields:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{model.__name__}.{name}"


def test_phase1c_enum_values_are_ascii() -> None:
    """The canonical taxonomy and extraction modes reach JSON, logs and reports."""
    from src.schemas.common import ExtractionMode, TechnicalDomain

    for enum_cls in (TechnicalDomain, ExtractionMode):
        for member in enum_cls:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", member.value), (
                f"{enum_cls.__name__}.{member.name} = {member.value!r}"
            )


def test_gold_dataset_structure_is_english() -> None:
    """Arabic is allowed in submissions and values, never in dataset structure."""
    from src.evals.dataset import load_gold_dataset

    dataset = load_gold_dataset()
    for case in dataset.cases:
        assert case.case_id.isascii()
        assert case.category.isascii()
        assert case.notes.isascii(), f"{case.case_id} notes must be English"
        for path in case.expected.known_fields:
            assert path.isascii(), "canonical field paths are English"
        for path in case.expected.list_fields:
            assert path.isascii()


def test_eval_metric_names_are_english() -> None:
    from src.evals.metrics import IntakeMetrics

    for name in IntakeMetrics.model_fields:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_interrupt_payload_message_is_english() -> None:
    """Developer-facing interrupt text stays English; the UI adapts it later."""
    from src.graph.contracts import InterruptRequest, InterruptType

    payload = InterruptRequest(
        type=InterruptType.MISSING_CRITICAL_INFORMATION,
        node="REQUEST_INPUT",
        fields=["problem.statement"],
        message="Additional project information is required.",
    ).to_payload()
    assert not ARABIC.search(str(payload))


def test_arabic_values_survive_a_json_round_trip() -> None:
    arabic_statement = "مشكلة حقيقية"
    state = ProjectState()
    state.problem.statement = Tracked[str].known(
        arabic_statement, origin=ValueOrigin.STUDENT_MESSAGE
    )
    restored = ProjectState.model_validate_json(state.model_dump_json())
    assert restored.problem.statement.value == arabic_statement
