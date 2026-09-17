"""Claim-evidence alignment Gold dataset.

``evals/claim_evidence_alignment/<version>/cases.jsonl``. Each case describes
one or more existing claims, one or more verified Phase 2C evidence items, what
a possibly-misbehaving classifier returns for each generated pair, and what the
system must produce regardless.

Expectations are authored from the claim text and evidence excerpt alone: given
this claim and this verified excerpt, is the proposed relationship internally
consistent, and does every proposed claim anchor actually exist in the claim?
The scripted classifier output is what a model might say, never what is
correct -- a case that scripts a fabricated anchor expects a rejection, and a
case that scripts an inconsistent relation/component combination expects a
structural rejection, whatever the model's confidence.

All content is synthetic. No real paper, dataset, author or student identity
appears anywhere.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.academic import AcademicProvider, AcademicSourceType
from src.schemas.claim import ClaimRecord, ClaimType
from src.schemas.common import MawhibaModel
from src.schemas.evidence_extraction import (
    ContentKind,
    EvidenceContentObservation,
    EvidenceScope,
    ExtractedEvidence,
    ExtractedEvidenceType,
    ExtractionMethod,
    SourceContentSnapshot,
    SpanMatchMethod,
    content_hash,
)
from src.schemas.source import PeerReviewStatus

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "claim_evidence_alignment"
DEFAULT_ALIGNMENT_DATASET_VERSION = "v1"

GOLD_RETRIEVED_AT_ISO = "2026-09-01T09:00:00+00:00"
SCRIPTED_FAILURES = frozenset(
    {"REFUSAL", "PROVIDER_ERROR", "INCOMPLETE_OUTPUT", "PARSE_ERROR", "EMPTY_OUTPUT"}
)


class GoldClaim(MawhibaModel):
    claim_id: str = Field(default="C-001", pattern=r"^C-\d{3,}$")
    claim: str = Field(min_length=1)
    claim_type: str = Field(default="OTHER")

    @model_validator(mode="after")
    def _known_type(self) -> GoldClaim:
        if self.claim_type not in ClaimType.__members__:
            raise ValueError(f"unknown claim type {self.claim_type}")
        return self


class GoldEvidenceItem(MawhibaModel):
    key: str = Field(min_length=1, description="Stable local handle, e.g. 'e1'.")
    excerpt: str = Field(min_length=1)
    evidence_type: str = Field(default="OTHER")
    source_type: str = Field(default="JOURNAL_ARTICLE")
    is_retracted: bool | None = None
    content_kind: str = Field(default="ABSTRACT")

    @model_validator(mode="after")
    def _known_enums(self) -> GoldEvidenceItem:
        if self.evidence_type not in ExtractedEvidenceType.__members__:
            raise ValueError(f"unknown evidence type {self.evidence_type}")
        if self.source_type not in AcademicSourceType.__members__:
            raise ValueError(f"unknown source type {self.source_type}")
        if self.content_kind not in ContentKind.__members__:
            raise ValueError(f"unknown content kind {self.content_kind}")
        return self


class GoldComponent(MawhibaModel):
    """One proposed component judgment in a scripted classifier response."""

    claimed_text: str = Field(default="")
    judgment: str = Field(default="SUPPORTS")
    reason_codes: list[str] = Field(default_factory=lambda: ["DIRECT_SUPPORT"])
    rationale: str | None = None


class GoldScriptedResponse(MawhibaModel):
    """What the classifier returns for one generated pair."""

    relation: str = Field(default="NOT_RELEVANT")
    components: list[GoldComponent] = Field(default_factory=list)
    rationale: str | None = None


class AlignmentGoldExpectation(MawhibaModel):
    """What a correct alignment pass must produce, from the input alone."""

    status: str | None = None
    pairs_required: int | None = Field(default=None, ge=0)
    accepted_count: int | None = Field(default=None, ge=0)
    relations: list[str] | None = Field(
        default=None, description="Sorted accepted relations, order-insensitive."
    )
    rejection_reasons: list[str] = Field(default_factory=list)
    forbidden_claim_substrings: list[str] = Field(
        default_factory=list,
        description="Text that must never appear in an accepted claim anchor -- "
        "text not verbatim in the claim.",
    )


class AlignmentGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^CA-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)
    claims: list[GoldClaim] = Field(min_length=1)
    evidence: list[GoldEvidenceItem] = Field(default_factory=list)
    scripted: list[GoldScriptedResponse] | None = Field(
        default=None,
        description="One entry per generated pair, in claim-major order. A "
        "single entry is reused for every pair when only one is given.",
    )
    scripted_failure: str | None = None
    max_pairs_per_run: int | None = Field(default=None, ge=1)
    direct_candidate: dict | None = Field(
        default=None,
        description="For structural-reference categories unreachable through "
        "deterministic pairing (invalid or cross-run references): a raw "
        "AlignmentCandidate payload fed straight to the verifier, bypassing the "
        "classifier and the pairing step. The candidate's own claim_id/"
        "evidence_id may be deliberately invalid.",
    )
    expected: AlignmentGoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _one_script(self) -> AlignmentGoldCase:
        if self.scripted is not None and self.scripted_failure is not None:
            raise ValueError("a case scripts either output or a failure, not both")
        if self.scripted_failure is not None and self.scripted_failure not in SCRIPTED_FAILURES:
            raise ValueError(f"unknown scripted failure {self.scripted_failure}")
        return self


class AlignmentGoldDataset(MawhibaModel):
    version: str
    cases: list[AlignmentGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> AlignmentGoldDataset:
        ids = [c.case_id for c in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self

    @property
    def language_counts(self) -> dict[str, int]:
        return dict(Counter(c.language for c in self.cases))

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(Counter(cat for c in self.cases for cat in c.categories))


# ---------------------------------------------------------------------------
# Deterministic materialization
# ---------------------------------------------------------------------------


def gold_run_id(case: AlignmentGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"alignment-gold:{case.case_id}:run")


def gold_extraction_run_id(case: AlignmentGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"alignment-gold:{case.case_id}:extraction")


def _source_id(case: AlignmentGoldCase, item: GoldEvidenceItem) -> str:
    return f"SRC-{uuid5(NAMESPACE_URL, f'alignment-gold:{case.case_id}:{item.key}')}"


def _content_id(case: AlignmentGoldCase, item: GoldEvidenceItem) -> UUID:
    return uuid5(NAMESPACE_URL, f"alignment-gold:{case.case_id}:{item.key}:content")


def _evidence_id(case: AlignmentGoldCase, item: GoldEvidenceItem) -> UUID:
    return uuid5(NAMESPACE_URL, f"alignment-gold:{case.case_id}:{item.key}:evidence")


def build_claims(case: AlignmentGoldCase) -> list[ClaimRecord]:
    return [
        ClaimRecord(claim_id=c.claim_id, claim=c.claim, claim_type=ClaimType(c.claim_type))
        for c in case.claims
    ]


def build_evidence(case: AlignmentGoldCase) -> list[ExtractedEvidence]:
    """Materialize the terminal Phase 2C state a case starts from.

    Built directly, exactly as ``evals/evidence_extraction`` builds its Phase 2B
    fixture: Phase 2D is what is being measured here, not evidence extraction,
    which the Phase 2C eval already covers. Each excerpt is its own snapshot's
    entire text, so the excerpt trivially verifies as a substring at [0, len).
    """
    run_id = gold_run_id(case)
    extraction_run_id = gold_extraction_run_id(case)
    items: list[ExtractedEvidence] = []
    for item in case.evidence:
        content_id = _content_id(case, item)
        source_id = _source_id(case, item)
        digest = content_hash(item.excerpt)
        content_kind = ContentKind(item.content_kind)
        scope = {
            ContentKind.ABSTRACT: EvidenceScope.ABSTRACT_ONLY,
            ContentKind.PARTIAL_TEXT: EvidenceScope.PARTIAL_TEXT,
            ContentKind.FULL_TEXT: EvidenceScope.FULL_TEXT,
        }[content_kind]
        items.append(
            ExtractedEvidence(
                evidence_id=_evidence_id(case, item),
                research_run_id=run_id,
                extraction_run_id=extraction_run_id,
                source_id=source_id,
                content_id=content_id,
                content_hash=digest,
                content_kind=content_kind,
                evidence_scope=scope,
                evidence_type=ExtractedEvidenceType(item.evidence_type),
                excerpt=item.excerpt,
                verified_start=0,
                verified_end=len(item.excerpt),
                match_method=SpanMatchMethod.EXACT,
                observations=[
                    EvidenceContentObservation(
                        content_id=content_id,
                        provider=AcademicProvider.CONSENSUS,
                        content_hash=digest,
                        content_kind=content_kind,
                        retrieved_at=GOLD_RETRIEVED_AT_ISO,
                    )
                ],
                source_type=AcademicSourceType(item.source_type),
                is_retracted=item.is_retracted,
                peer_review_status=PeerReviewStatus.UNKNOWN,
                extraction_method=ExtractionMethod.DETERMINISTIC_FIXTURE,
            )
        )
    return items


def build_snapshots(case: AlignmentGoldCase) -> list[SourceContentSnapshot]:
    run_id = gold_run_id(case)
    snapshots: list[SourceContentSnapshot] = []
    for item in case.evidence:
        content_id = _content_id(case, item)
        source_id = _source_id(case, item)
        digest = content_hash(item.excerpt)
        snapshots.append(
            SourceContentSnapshot(
                source_id=source_id,
                research_run_id=run_id,
                content_id=content_id,
                content_kind=ContentKind(item.content_kind),
                text=item.excerpt,
                content_hash=digest,
                provider=AcademicProvider.CONSENSUS,
                retrieved_at=GOLD_RETRIEVED_AT_ISO,
            )
        )
    return snapshots


def alignment_dataset_path(version: str = DEFAULT_ALIGNMENT_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_alignment_dataset(
    version: str = DEFAULT_ALIGNMENT_DATASET_VERSION,
) -> AlignmentGoldDataset:
    path = alignment_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"claim alignment dataset not found: {path}")
    cases: list[AlignmentGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(AlignmentGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {number}: {str(exc).splitlines()[0]}"
            ) from exc
    return AlignmentGoldDataset(version=version, cases=cases)


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_ALIGNMENT_DATASET_VERSION",
    "AlignmentGoldCase",
    "AlignmentGoldDataset",
    "AlignmentGoldExpectation",
    "GoldClaim",
    "GoldComponent",
    "GoldEvidenceItem",
    "GoldScriptedResponse",
    "build_claims",
    "build_evidence",
    "build_snapshots",
    "alignment_dataset_path",
    "gold_extraction_run_id",
    "gold_run_id",
    "load_alignment_dataset",
]
