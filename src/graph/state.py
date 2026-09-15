"""PROJECT_STATE -- architecture 6. The canonical state of one project version.

This object is the single source of truth for an evaluation run. Reports,
scores and the trust gate are all derived from it and never add information of
their own (23, 43).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.claim import ClaimRecord
from src.schemas.common import (
    EvaluationStatus,
    MawhibaModel,
    OperatingMode,
    Severity,
    Tracked,
    UtcDatetime,
    utc_now,
)
from src.schemas.evidence import EvidenceRecord
from src.schemas.finding import (
    ContradictionRecord,
    FindingRecord,
    MissingInformationRecord,
)
from src.schemas.prior_art import GapAssessment, NoveltyAssessment, PriorArtRecord
from src.schemas.project import (
    ExperimentRecord,
    MethodologyBlock,
    ProblemBlock,
    ProjectIdentity,
    ResultRecord,
    RiskRecord,
    SolutionBlock,
    TechnicalBlock,
)
from src.schemas.score import ScoreRecord
from src.schemas.source import ResearchQueryRecord, SourceRecord
from src.schemas.trust import TrustGateResult


class ProjectState(MawhibaModel):
    """Canonical PROJECT_STATE (6).

    Referential integrity between the record collections is validated here --
    this is the only place where the graph as a whole can be checked.
    """

    project_id: UUID = Field(default_factory=uuid4)
    project_version_id: UUID = Field(default_factory=uuid4)
    version_label: str | None = Field(
        default=None,
        description="29: a substantive student edit creates a new PROJECT_VERSION.",
    )
    current_mode: OperatingMode = OperatingMode.EVALUATOR
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    identity: ProjectIdentity = Field(default_factory=ProjectIdentity)
    problem: ProblemBlock = Field(default_factory=ProblemBlock)
    solution: SolutionBlock = Field(default_factory=SolutionBlock)

    # -- Phase 1C canonical intake destinations --------------------------------
    # Added so that verified intake facts have a semantic owner instead of being
    # dropped. Each is Zero-Assumption aware: UNKNOWN is the default and no fake
    # value is ever substituted.
    goal: Tracked[str] = Field(
        default_factory=Tracked[str].unknown,
        description="What the project sets out to achieve, in the student's wording. "
        "Distinct from problem.statement (what is wrong) and from "
        "solution.description (what was built).",
    )
    student_contribution: Tracked[str] = Field(
        default_factory=Tracked[str].unknown,
        description="What the student states they personally did. Central to the "
        "Red Team question of integration-only work (section 19); recorded at "
        "intake, judged much later.",
    )
    current_stage: Tracked[str] = Field(
        default_factory=Tracked[str].unknown,
        description="How far the project has progressed, as stated. Distinct from "
        "technical.prototype_status, which describes the artifact itself.",
    )

    technical: TechnicalBlock = Field(default_factory=TechnicalBlock)
    methodology: MethodologyBlock = Field(default_factory=MethodologyBlock)

    experiments: list[ExperimentRecord] = Field(default_factory=list)
    results: list[ResultRecord] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    prior_art: list[PriorArtRecord] = Field(default_factory=list)
    research_queries: list[ResearchQueryRecord] = Field(default_factory=list)

    novelty: NoveltyAssessment = Field(default_factory=NoveltyAssessment)
    gap: GapAssessment = Field(default_factory=GapAssessment)

    findings: list[FindingRecord] = Field(default_factory=list)
    risks: list[RiskRecord] = Field(default_factory=list)
    scores: list[ScoreRecord] = Field(default_factory=list)

    missing_critical_information: list[MissingInformationRecord] = Field(
        default_factory=list
    )
    contradictions: list[ContradictionRecord] = Field(default_factory=list)

    trust_gate: TrustGateResult | None = None
    evaluation_status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED

    # Workflow execution state (completed/pending nodes, current node, interrupt
    # state, workflow errors) deliberately does NOT live here. It is owned
    # exclusively by EvaluationGraphState -- see ADR-002. A project snapshot must
    # stay independent of the orchestration engine that produced it.

    # -- referential integrity -------------------------------------------------

    @model_validator(mode="after")
    def _check_referential_integrity(self) -> ProjectState:
        source_ids = {s.source_id for s in self.sources}
        evidence_ids = {e.evidence_id for e in self.evidence}
        claim_ids = {c.claim_id for c in self.claims}
        finding_ids = {f.finding_id for f in self.findings}
        query_ids = {q.query_id for q in self.research_queries}

        _require_unique("source_id", [s.source_id for s in self.sources])
        _require_unique("evidence_id", [e.evidence_id for e in self.evidence])
        _require_unique("claim_id", [c.claim_id for c in self.claims])
        _require_unique("finding_id", [f.finding_id for f in self.findings])
        _require_unique("prior_art_id", [p.prior_art_id for p in self.prior_art])
        _require_unique("score_id", [s.score_id for s in self.scores])
        _require_unique("query_id", [q.query_id for q in self.research_queries])

        for ev in self.evidence:
            if ev.source_id not in source_ids:
                raise ValueError(
                    f"{ev.evidence_id} references unknown source {ev.source_id}"
                )

        for src in self.sources:
            if src.query_id is not None and src.query_id not in query_ids:
                raise ValueError(
                    f"{src.source_id} references unknown query {src.query_id}"
                )
            if src.duplicate_of is not None and src.duplicate_of not in source_ids:
                raise ValueError(
                    f"{src.source_id} is marked duplicate of unknown {src.duplicate_of}"
                )

        for claim in self.claims:
            _require_subset(
                claim.claim_id, "evidence_ids", claim.evidence_ids, evidence_ids
            )
            _require_subset(
                claim.claim_id,
                "counter_evidence_ids",
                claim.counter_evidence_ids,
                evidence_ids,
            )

        for pa in self.prior_art:
            if pa.source_id not in source_ids:
                raise ValueError(
                    f"{pa.prior_art_id} references unknown source {pa.source_id}"
                )
            _require_subset(pa.prior_art_id, "evidence_ids", pa.evidence_ids, evidence_ids)

        for finding in self.findings:
            _require_subset(
                finding.finding_id, "evidence_ids", finding.evidence_ids, evidence_ids
            )
            _require_subset(
                finding.finding_id,
                "affected_claim_ids",
                finding.affected_claim_ids,
                claim_ids,
            )

        for contradiction in self.contradictions:
            _require_subset(
                contradiction.contradiction_id,
                "affected_claim_ids",
                contradiction.affected_claim_ids,
                claim_ids,
            )

        for risk in self.risks:
            if risk.finding_id is not None and risk.finding_id not in finding_ids:
                raise ValueError(
                    f"{risk.risk_id} references unknown finding {risk.finding_id}"
                )

        prior_art_ids = {p.prior_art_id for p in self.prior_art}
        _require_subset(
            "novelty", "closest_prior_art_ids", self.novelty.closest_prior_art_ids,
            prior_art_ids,
        )
        _require_subset("novelty", "evidence_ids", self.novelty.evidence_ids, evidence_ids)
        _require_subset("gap", "evidence_ids", self.gap.evidence_ids, evidence_ids)

        for score in self.scores:
            for axis in score.axes:
                _require_subset(
                    f"{score.score_id}:{axis.axis}",
                    "evidence_ids",
                    axis.evidence_ids,
                    evidence_ids,
                )
                _require_subset(
                    f"{score.score_id}:{axis.axis}",
                    "finding_ids",
                    axis.finding_ids,
                    finding_ids,
                )

        experiment_ids = {e.experiment_id for e in self.experiments}
        for result in self.results:
            if result.experiment_id is not None and result.experiment_id not in experiment_ids:
                raise ValueError(
                    f"{result.result_id} references unknown experiment "
                    f"{result.experiment_id}"
                )

        return self

    # -- derived views used by the trust gate and the scorer -------------------

    @property
    def official_score(self) -> ScoreRecord | None:
        return next((s for s in self.scores if s.official), None)

    @property
    def advisory_score(self) -> ScoreRecord | None:
        return next((s for s in self.scores if not s.official), None)

    @property
    def unresolved_critical_contradictions(self) -> list[ContradictionRecord]:
        return [c for c in self.contradictions if c.is_unresolved_critical]

    @property
    def critical_missing_information(self) -> list[MissingInformationRecord]:
        return [m for m in self.missing_critical_information if m.is_critical]

    @property
    def blocking_findings(self) -> list[FindingRecord]:
        return [f for f in self.findings if f.is_blocking]

    @property
    def critical_claims(self) -> list[ClaimRecord]:
        return [c for c in self.claims if c.is_critical]

    def evidence_by_id(self, evidence_id: str) -> EvidenceRecord | None:
        return next((e for e in self.evidence if e.evidence_id == evidence_id), None)

    def source_by_id(self, source_id: str) -> SourceRecord | None:
        return next((s for s in self.sources if s.source_id == source_id), None)

    def claim_by_id(self, claim_id: str) -> ClaimRecord | None:
        return next((c for c in self.claims if c.claim_id == claim_id), None)

    def sources_for_claim(self, claim_id: str) -> list[SourceRecord]:
        """Claim -> Evidence -> Source: the full provenance chain (43)."""
        claim = self.claim_by_id(claim_id)
        if claim is None:
            return []
        wanted = set(claim.evidence_ids) | set(claim.counter_evidence_ids)
        source_ids = {
            e.source_id for e in self.evidence if e.evidence_id in wanted
        }
        return [s for s in self.sources if s.source_id in source_ids]

    def max_open_severity(self) -> Severity | None:
        severities = [f.severity for f in self.findings] + [
            c.severity for c in self.unresolved_critical_contradictions
        ]
        for level in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
            if level in severities:
                return level
        return None


def _require_unique(label: str, values: list[str]) -> None:
    duplicates = {v for v in values if values.count(v) > 1}
    if duplicates:
        raise ValueError(f"duplicate {label}: {sorted(duplicates)}")


def _require_subset(
    owner: str, field: str, values: list[str], allowed: set[str]
) -> None:
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ValueError(f"{owner}.{field} references unknown ids: {sorted(unknown)}")
