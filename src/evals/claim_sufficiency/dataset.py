"""Claim sufficiency Gold dataset -- Phase 2E.

``evals/claim_sufficiency/<version>/cases.jsonl``. Each case describes a
complete, synthetic upstream world: existing claims, Phase 2B logical sources
with their canonical identifiers, Phase 2C verified evidence over those
sources, and the Phase 2D alignments relating the two.

Phase 2E makes no model call, so there is no "scripted model output" block here
and no possibly-misbehaving classifier to defend against. The adversarial
surface is the *input shape* instead: the same DOI under two source records,
three providers observing one paper, five excerpts from one abstract, a
retracted supporting paper, an alignment whose evidence is not in the run, a
Phase 2D run that never finished. Those are the shapes that would silently
inflate corroboration or assert sufficiency over evidence nobody examined.

Gold expectations are authored from the described input alone -- what a correct
policy must conclude given these claims, these sources and these relations --
never by running the code and blessing its answer.

All content is synthetic. No real paper, DOI, author, dataset or student
identity appears anywhere. Arabic and mixed-language cases carry Arabic only as
*data*, in claim text and excerpt value positions, never translated.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from src.schemas.academic import (
    AcademicBranchOutcome,
    AcademicBudgetReport,
    AcademicIdentifiers,
    AcademicProvider,
    AcademicRetrievalResult,
    AcademicSourceType,
    LogicalAcademicSource,
    ProviderObservation,
)
from src.schemas.claim import ClaimRecord, ClaimType
from src.schemas.claim_alignment import (
    AlignmentReasonCode,
    AlignmentRelation,
    ClaimComponentAnchor,
    ClaimEvidenceAlignment,
    ClaimEvidenceAlignmentRun,
    ComponentAlignmentJudgment,
    ComponentJudgment,
)
from src.schemas.common import MawhibaModel
from src.schemas.evidence_extraction import (
    ContentKind,
    EvidenceContentObservation,
    EvidenceExtractionRun,
    EvidenceExtractionStatus,
    EvidenceScope,
    ExtractedEvidence,
    ExtractedEvidenceType,
    ExtractionMethod,
    SourceContentSnapshot,
    SpanMatchMethod,
    content_hash,
)
from src.schemas.source import SourceFingerprint, SourceIdentifierKind

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "claim_sufficiency"
DEFAULT_SUFFICIENCY_DATASET_VERSION = "v1"

GOLD_RETRIEVED_AT_ISO = "2026-09-01T09:00:00+00:00"
GOLD_EXTRACTION_DONE_ISO = "2026-09-01T09:05:00+00:00"
GOLD_ALIGNMENT_DONE_ISO = "2026-09-01T09:10:00+00:00"

CONTENT_SCOPE = {
    ContentKind.ABSTRACT: EvidenceScope.ABSTRACT_ONLY,
    ContentKind.PARTIAL_TEXT: EvidenceScope.PARTIAL_TEXT,
    ContentKind.FULL_TEXT: EvidenceScope.FULL_TEXT,
}


# ---------------------------------------------------------------------------
# Case schema
# ---------------------------------------------------------------------------


class GoldClaim(MawhibaModel):
    claim_id: str = Field(default="C-001", pattern=r"^C-\d{3,}$")
    claim: str = Field(min_length=1)
    claim_type: str = Field(default="OTHER")

    @model_validator(mode="after")
    def _known_type(self) -> GoldClaim:
        if self.claim_type not in ClaimType.__members__:
            raise ValueError(f"unknown claim type {self.claim_type}")
        return self


class GoldSource(MawhibaModel):
    """One Phase 2B logical source, described by its real identity facts.

    ``doi``/``openalex_id``/``arxiv_id``/``pmid`` are what canonical identity is
    built from. Two source entries sharing one identifier are deliberately the
    *same* underlying work seen twice -- that is the duplicate-collapse case,
    and the title is never what decides it (ADR-009).
    """

    key: str = Field(min_length=1, description="Stable local handle, e.g. 's1'.")
    title: str = Field(default="Synthetic study record")
    doi: str | None = None
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    canonical_url: str | None = None
    source_type: str = Field(default="JOURNAL_ARTICLE")
    is_retracted: bool | None = None
    publication_year: int | None = 2024
    providers: list[str] = Field(default_factory=lambda: ["CONSENSUS"], min_length=1)
    orphan: bool = Field(
        default=False,
        description="Omit this source from the run's verified sources, so its "
        "evidence has no resolvable canonical identity. Drives the "
        "untraceable-evidence category.",
    )

    @model_validator(mode="after")
    def _known_enums(self) -> GoldSource:
        if self.source_type not in AcademicSourceType.__members__:
            raise ValueError(f"unknown source type {self.source_type}")
        for provider in self.providers:
            if provider not in AcademicProvider.__members__:
                raise ValueError(f"unknown provider {provider}")
        if not any(
            (
                self.doi,
                self.openalex_id,
                self.semantic_scholar_id,
                self.arxiv_id,
                self.pmid,
                self.canonical_url,
            )
        ):
            raise ValueError("a logical source needs at least one strong identifier")
        return self


class GoldEvidence(MawhibaModel):
    key: str = Field(min_length=1, description="Stable local handle, e.g. 'e1'.")
    source: str = Field(min_length=1, description="A GoldSource key.")
    excerpt: str = Field(min_length=1)
    evidence_type: str = Field(default="EXPERIMENTAL_RESULT")
    content_kind: str = Field(default="ABSTRACT")
    is_retracted: bool | None = None
    missing_from_run: bool = Field(
        default=False,
        description="Build the evidence id but do not add the item to the run, "
        "so an alignment references evidence that is not there. Drives the "
        "cross-run / untraceable evidence categories.",
    )

    @model_validator(mode="after")
    def _known_enums(self) -> GoldEvidence:
        if self.evidence_type not in ExtractedEvidenceType.__members__:
            raise ValueError(f"unknown evidence type {self.evidence_type}")
        if self.content_kind not in ContentKind.__members__:
            raise ValueError(f"unknown content kind {self.content_kind}")
        return self


class GoldComponent(MawhibaModel):
    """One claim-component judgement, anchored by a verbatim claim substring.

    ``text`` must occur in the claim; offsets are derived by code, never
    authored, so a Gold case cannot encode an anchor that does not exist.
    """

    text: str = Field(min_length=1)
    judgment: str = Field(default="SUPPORTS")

    @model_validator(mode="after")
    def _known_judgment(self) -> GoldComponent:
        if self.judgment not in ComponentJudgment.__members__:
            raise ValueError(f"unknown component judgment {self.judgment}")
        return self


class GoldAlignment(MawhibaModel):
    claim_id: str = Field(default="C-001", pattern=r"^C-\d{3,}$")
    evidence: str = Field(min_length=1, description="A GoldEvidence key.")
    relation: str = Field(default="SUPPORTS")
    components: list[GoldComponent] = Field(default_factory=list)
    foreign_run: bool = Field(
        default=False,
        description="Build this alignment under a different research run id. "
        "Only valid in direct mode: a run record cannot hold one.",
    )
    hash_mismatch: bool = Field(
        default=False,
        description="Record a content hash that does not match the evidence, so "
        "the alignment was verified against different bytes.",
    )

    @model_validator(mode="after")
    def _known_relation(self) -> GoldAlignment:
        if self.relation not in AlignmentRelation.__members__:
            raise ValueError(f"unknown relation {self.relation}")
        return self


class SufficiencyGoldExpectation(MawhibaModel):
    """What a correct sufficiency pass must produce, from the input alone."""

    status: str | None = None
    outcomes: dict[str, str] = Field(
        default_factory=dict, description="claim_id -> SufficiencyOutcome."
    )
    independence_groups: int | None = Field(default=None, ge=0)
    supporting_groups: dict[str, int] = Field(default_factory=dict)
    contradicting_groups: dict[str, int] = Field(default_factory=dict)
    component_coverage: dict[str, list[str]] = Field(
        default_factory=dict,
        description="claim_id -> ComponentCoverage values, in component order.",
    )
    contributions: list[str] = Field(
        default_factory=list,
        description="Sorted EvidenceContributionClass values across all profiles.",
    )
    reason_codes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="claim_id -> reason codes that must all be present.",
    )
    forbidden_reason_codes: dict[str, list[str]] = Field(default_factory=dict)
    blockers: dict[str, list[str]] = Field(default_factory=dict)
    unknown_dimensions: dict[str, list[str]] = Field(default_factory=dict)
    limitations: dict[str, list[str]] = Field(default_factory=dict)
    content_scope_ceiling: dict[str, str] = Field(default_factory=dict)
    duplicate_evidence_collapsed: int | None = Field(default=None, ge=0)
    assessments_total: int | None = Field(default=None, ge=0)


class SufficiencyGoldCase(MawhibaModel):
    case_id: str = Field(pattern=r"^CS-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)
    claims: list[GoldClaim] = Field(min_length=1)
    sources: list[GoldSource] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)
    alignments: list[GoldAlignment] = Field(default_factory=list)
    alignment_status: str = Field(default="COMPLETED")
    direct_mode: bool = Field(
        default=False,
        description="Call the deterministic pipeline directly instead of the "
        "graph, for shapes a validated run record cannot hold (a foreign-run "
        "alignment). Still production code, entered below the graph.",
    )
    resume_after_node: str | None = Field(
        default=None,
        description="Interrupt the graph before this node and resume from the "
        "checkpoint, to prove a resume neither duplicates nor loses work.",
    )
    rerun: bool = Field(
        default=False, description="Invoke the finished graph a second time."
    )
    expected: SufficiencyGoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _references_resolve(self) -> SufficiencyGoldCase:
        from src.schemas.claim_alignment import ClaimAlignmentStatus

        if self.alignment_status not in ClaimAlignmentStatus.__members__:
            raise ValueError(f"unknown alignment status {self.alignment_status}")
        source_keys = {s.key for s in self.sources}
        if len(source_keys) != len(self.sources):
            raise ValueError("source keys must be unique")
        evidence_keys = {e.key for e in self.evidence}
        if len(evidence_keys) != len(self.evidence):
            raise ValueError("evidence keys must be unique")
        claim_ids = {c.claim_id for c in self.claims}
        if len(claim_ids) != len(self.claims):
            raise ValueError("claim ids must be unique")
        for item in self.evidence:
            if item.source not in source_keys:
                raise ValueError(f"evidence {item.key} names unknown source {item.source}")
        claim_text = {c.claim_id: c.claim for c in self.claims}
        for alignment in self.alignments:
            if alignment.evidence not in evidence_keys:
                raise ValueError(
                    f"alignment names unknown evidence {alignment.evidence}"
                )
            if alignment.claim_id not in claim_ids:
                raise ValueError(f"alignment names unknown claim {alignment.claim_id}")
            for component in alignment.components:
                if component.text not in claim_text[alignment.claim_id]:
                    raise ValueError(
                        f"component anchor {component.text!r} is not verbatim in "
                        f"claim {alignment.claim_id}"
                    )
            if alignment.foreign_run and not self.direct_mode:
                raise ValueError("a foreign-run alignment requires direct_mode")
        pairs = [(a.claim_id, a.evidence) for a in self.alignments]
        if len(set(pairs)) != len(pairs):
            raise ValueError("a claim/evidence pair cannot carry two alignments")
        return self


class SufficiencyGoldDataset(MawhibaModel):
    version: str
    cases: list[SufficiencyGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> SufficiencyGoldDataset:
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

    @property
    def outcome_counts(self) -> dict[str, int]:
        return dict(
            Counter(
                outcome
                for case in self.cases
                for outcome in case.expected.outcomes.values()
            )
        )


# ---------------------------------------------------------------------------
# Deterministic materialization
# ---------------------------------------------------------------------------


def gold_run_id(case: SufficiencyGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"sufficiency-gold:{case.case_id}:run")


def gold_foreign_run_id(case: SufficiencyGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"sufficiency-gold:{case.case_id}:other-run")


def gold_extraction_run_id(case: SufficiencyGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"sufficiency-gold:{case.case_id}:extraction")


def gold_alignment_run_id(case: SufficiencyGoldCase) -> UUID:
    return uuid5(NAMESPACE_URL, f"sufficiency-gold:{case.case_id}:alignment")


def _uid(case: SufficiencyGoldCase, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sufficiency-gold:{case.case_id}:" + ":".join(parts))


def source_id_for(case: SufficiencyGoldCase, key: str) -> str:
    return f"SRC-{_uid(case, 'source', key)}"


def evidence_id_for(case: SufficiencyGoldCase, key: str) -> UUID:
    return _uid(case, "evidence", key)


def build_claims(case: SufficiencyGoldCase) -> list[ClaimRecord]:
    return [
        ClaimRecord(claim_id=c.claim_id, claim=c.claim, claim_type=ClaimType(c.claim_type))
        for c in case.claims
    ]


def _identifiers(spec: GoldSource) -> AcademicIdentifiers:
    return AcademicIdentifiers(
        doi=spec.doi,
        pmid=spec.pmid,
        openalex_id=spec.openalex_id,
        semantic_scholar_id=spec.semantic_scholar_id,
        arxiv_id=spec.arxiv_id,
    )


def build_logical_sources(case: SufficiencyGoldCase) -> list[LogicalAcademicSource]:
    """Materialize the Phase 2B state a case starts from.

    Built directly rather than through the Phase 2B graph: Phase 2E is what is
    being measured, and the academic-retrieval eval already covers retrieval.
    The fingerprint is derived exactly as Phase 2B derives it -- from the
    strongest identifier -- so canonical identity here is the real thing.
    """
    run_id = gold_run_id(case)
    sources: list[LogicalAcademicSource] = []
    for spec in case.sources:
        if spec.orphan:
            continue
        identifiers = _identifiers(spec)
        strongest = identifiers.strongest()
        if strongest is None:
            strongest = (SourceIdentifierKind.CANONICAL_URL, spec.canonical_url)
        kind, value = strongest
        observations = [
            ProviderObservation(
                provider=AcademicProvider(provider),
                candidate_id=_uid(case, "candidate", spec.key, provider),
                query_id=_uid(case, "query"),
                research_run_id=run_id,
                identifiers=identifiers,
                title=spec.title,
                publication_year=spec.publication_year,
                source_type=AcademicSourceType(spec.source_type),
                is_retracted=spec.is_retracted,
                retrieved_at=GOLD_RETRIEVED_AT_ISO,
            )
            for provider in spec.providers
        ]
        sources.append(
            LogicalAcademicSource(
                logical_source_id=source_id_for(case, spec.key),
                research_run_id=run_id,
                fingerprint=SourceFingerprint.create(kind, value),
                identifiers=identifiers,
                title=spec.title,
                authors=[],
                publication_year=spec.publication_year,
                source_type=AcademicSourceType(spec.source_type),
                is_retracted=spec.is_retracted,
                canonical_url=spec.canonical_url,
                observations=observations,
                first_retrieved_at=GOLD_RETRIEVED_AT_ISO,
            )
        )
    return sources


def build_academic_result(case: SufficiencyGoldCase) -> AcademicRetrievalResult:
    sources = build_logical_sources(case)
    return AcademicRetrievalResult(
        research_run_id=gold_run_id(case),
        outcome=(
            AcademicBranchOutcome.SUCCESS if sources else AcademicBranchOutcome.EMPTY
        ),
        providers=list(AcademicProvider),
        budget=AcademicBudgetReport(
            max_queries_per_run=4,
            max_results_per_query_per_provider=10,
            max_results_per_provider_per_run=30,
            max_total_candidates=90,
        ),
        logical_sources=sources,
        verified_sources=[s.to_source_record() for s in sources],
    )


def build_snapshots(case: SufficiencyGoldCase) -> list[SourceContentSnapshot]:
    run_id = gold_run_id(case)
    by_key = {s.key: s for s in case.sources}
    snapshots: list[SourceContentSnapshot] = []
    for item in case.evidence:
        spec = by_key[item.source]
        if spec.orphan or item.missing_from_run:
            continue
        kind = ContentKind(item.content_kind)
        snapshots.append(
            SourceContentSnapshot(
                content_id=_uid(case, "content", item.key),
                source_id=source_id_for(case, item.source),
                research_run_id=run_id,
                content_kind=kind,
                text=item.excerpt,
                content_hash=content_hash(item.excerpt),
                provider=AcademicProvider(spec.providers[0]),
                retrieved_at=GOLD_RETRIEVED_AT_ISO,
                publication_year=spec.publication_year,
                source_type=AcademicSourceType(spec.source_type),
                is_retracted=(
                    item.is_retracted if item.is_retracted is not None else spec.is_retracted
                ),
            )
        )
    return snapshots


def build_evidence(case: SufficiencyGoldCase) -> list[ExtractedEvidence]:
    """One evidence item per spec, each excerpt its own whole snapshot.

    ``missing_from_run`` items are skipped, so an alignment can reference
    evidence the run does not hold -- what an untraceable or cross-run
    reference looks like from Phase 2E's side.
    """
    run_id = gold_run_id(case)
    extraction_run_id = gold_extraction_run_id(case)
    by_key = {s.key: s for s in case.sources}
    items: list[ExtractedEvidence] = []
    for item in case.evidence:
        spec = by_key[item.source]
        if spec.orphan or item.missing_from_run:
            continue
        kind = ContentKind(item.content_kind)
        digest = content_hash(item.excerpt)
        content_id = _uid(case, "content", item.key)
        items.append(
            ExtractedEvidence(
                evidence_id=evidence_id_for(case, item.key),
                research_run_id=run_id,
                extraction_run_id=extraction_run_id,
                source_id=source_id_for(case, item.source),
                content_id=content_id,
                content_hash=digest,
                content_kind=kind,
                evidence_scope=CONTENT_SCOPE[kind],
                evidence_type=ExtractedEvidenceType(item.evidence_type),
                excerpt=item.excerpt,
                verified_start=0,
                verified_end=len(item.excerpt),
                match_method=SpanMatchMethod.EXACT,
                observations=[
                    EvidenceContentObservation(
                        content_id=content_id,
                        provider=AcademicProvider(provider),
                        content_hash=digest,
                        content_kind=kind,
                        retrieved_at=GOLD_RETRIEVED_AT_ISO,
                    )
                    for provider in spec.providers
                ],
                publication_year=spec.publication_year,
                source_type=AcademicSourceType(spec.source_type),
                is_retracted=(
                    item.is_retracted if item.is_retracted is not None else spec.is_retracted
                ),
                extraction_method=ExtractionMethod.DETERMINISTIC_FIXTURE,
            )
        )
    return items


def build_extraction_run(case: SufficiencyGoldCase) -> EvidenceExtractionRun:
    return EvidenceExtractionRun(
        research_run_id=gold_run_id(case),
        evidence_extraction_run_id=gold_extraction_run_id(case),
        status=EvidenceExtractionStatus.COMPLETED,
        content_snapshots=build_snapshots(case),
        verified_evidence=build_evidence(case),
        completed_at=GOLD_EXTRACTION_DONE_ISO,
    )


_REASON_FOR_JUDGMENT = {
    ComponentJudgment.SUPPORTS: AlignmentReasonCode.DIRECT_SUPPORT,
    ComponentJudgment.CONTRADICTS: AlignmentReasonCode.DIRECT_CONTRADICTION,
    ComponentJudgment.CONTEXTUAL: AlignmentReasonCode.BACKGROUND_CONTEXT_ONLY,
    ComponentJudgment.UNRESOLVED: AlignmentReasonCode.INSUFFICIENT_DETAIL,
}


def build_alignments(case: SufficiencyGoldCase) -> list[ClaimEvidenceAlignment]:
    """Materialize the verified Phase 2D relations the case starts from.

    Anchor offsets are derived from the claim text by ``str.index``, so every
    anchor satisfies ``claim.claim[start:end] == anchor_text`` by construction
    -- the property Phase 2D proved and Phase 2E consumes unchanged.
    """
    run_id = gold_run_id(case)
    alignment_run_id = gold_alignment_run_id(case)
    claim_text = {c.claim_id: c.claim for c in case.claims}
    by_evidence_key = {e.key: e for e in case.evidence}
    alignments: list[ClaimEvidenceAlignment] = []
    for spec in case.alignments:
        item = by_evidence_key[spec.evidence]
        digest = (
            content_hash(item.excerpt + "-divergent")
            if spec.hash_mismatch
            else content_hash(item.excerpt)
        )
        text = claim_text[spec.claim_id]
        components = []
        for component in spec.components:
            start = text.index(component.text)
            judgment = ComponentJudgment(component.judgment)
            components.append(
                ComponentAlignmentJudgment(
                    anchor=ClaimComponentAnchor(
                        claim_id=spec.claim_id,
                        start=start,
                        end=start + len(component.text),
                        text=component.text,
                    ),
                    judgment=judgment,
                    reason_codes=[_REASON_FOR_JUDGMENT[judgment]],
                )
            )
        alignments.append(
            ClaimEvidenceAlignment(
                alignment_id=_uid(case, "alignment", spec.claim_id, spec.evidence),
                research_run_id=(
                    gold_foreign_run_id(case) if spec.foreign_run else run_id
                ),
                alignment_run_id=alignment_run_id,
                claim_id=spec.claim_id,
                evidence_id=evidence_id_for(case, spec.evidence),
                evidence_content_hash=digest,
                relation=AlignmentRelation(spec.relation),
                components=components,
            )
        )
    return alignments


def build_alignment_run(case: SufficiencyGoldCase) -> ClaimEvidenceAlignmentRun:
    """The Phase 2D run, holding only alignments a real run could hold.

    A foreign-run alignment is filtered out here because
    ``ClaimEvidenceAlignmentRun`` rejects it -- correctly. Such a case runs in
    ``direct_mode`` instead, where the pipeline is called with the alignment
    directly.
    """
    from src.schemas.claim_alignment import ClaimAlignmentStatus

    run_id = gold_run_id(case)
    alignments = [a for a in build_alignments(case) if a.research_run_id == run_id]
    status = ClaimAlignmentStatus(case.alignment_status)
    still_open = status in {
        ClaimAlignmentStatus.NOT_STARTED,
        ClaimAlignmentStatus.RUNNING,
    }
    if status is ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED:
        alignments = []
    return ClaimEvidenceAlignmentRun(
        alignment_run_id=gold_alignment_run_id(case),
        research_run_id=run_id,
        status=status,
        alignments=alignments,
        completed_at=None if still_open else GOLD_ALIGNMENT_DONE_ISO,
    )


def sufficiency_dataset_path(
    version: str = DEFAULT_SUFFICIENCY_DATASET_VERSION,
) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_sufficiency_dataset(
    version: str = DEFAULT_SUFFICIENCY_DATASET_VERSION,
) -> SufficiencyGoldDataset:
    path = sufficiency_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"claim sufficiency dataset not found: {path}")
    cases: list[SufficiencyGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(SufficiencyGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {number}: {str(exc).splitlines()[0]}"
            ) from exc
    return SufficiencyGoldDataset(version=version, cases=cases)


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_SUFFICIENCY_DATASET_VERSION",
    "GoldAlignment",
    "GoldClaim",
    "GoldComponent",
    "GoldEvidence",
    "GoldSource",
    "SufficiencyGoldCase",
    "SufficiencyGoldDataset",
    "SufficiencyGoldExpectation",
    "build_academic_result",
    "build_alignment_run",
    "build_alignments",
    "build_claims",
    "build_evidence",
    "build_extraction_run",
    "build_logical_sources",
    "build_snapshots",
    "evidence_id_for",
    "gold_alignment_run_id",
    "gold_extraction_run_id",
    "gold_foreign_run_id",
    "gold_run_id",
    "load_sufficiency_dataset",
    "source_id_for",
    "sufficiency_dataset_path",
]
