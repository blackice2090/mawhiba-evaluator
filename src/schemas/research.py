"""Research foundation contracts -- Phase 2A, architecture N05, 9 and 27.

``ResearchRun`` is a first-class versioned record, deliberately kept OUT of
``ProjectState``: research planning reads canonical state and never writes to it
(ADR-006). Expansion terms therefore have no field anywhere in ``ProjectState``.

``ResearchQuery`` is distinct from the Phase 0 ``ResearchQueryRecord``. The
Phase 0 record is the execution log of a query that ran against a provider; a
``ResearchQuery`` is a verified statement of *why* the system intends to search.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, model_validator

from src.schemas.academic import AcademicRetrievalResult
from src.schemas.claim_alignment import ClaimEvidenceAlignmentRun
from src.schemas.evidence_extraction import EvidenceExtractionRun
from src.schemas.common import (
    MawhibaModel,
    QueryPurpose,
    ResearchBranch,
    UtcDatetime,
    utc_now,
)
from src.schemas.extraction import ModelFacingModel
from src.schemas.official import OfficialRequirementsResult

# ``QueryPurpose`` now lives in ``src.schemas.common``: the branch contracts that
# need the vocabulary (academic retrieval first) cannot import this module,
# because this module embeds their results. It is imported above so that every
# existing ``from src.schemas.research import QueryPurpose`` keeps working.

RESEARCH_CONTRACT_VERSION = "RESEARCH-CONTRACT-V1"


class ResearchRunStatus(StrEnum):
    """Execution state of a research run.

    Separate from ``EvaluationStatus`` on purpose: COMPLETED means the Phase 2A
    work ran, never that novelty is proven or evidence is sufficient.
    """

    NOT_STARTED = "NOT_STARTED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_RESEARCH_RUN_STATUSES: frozenset[ResearchRunStatus] = frozenset(
    {ResearchRunStatus.PARTIAL, ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED}
)


CHALLENGE_PURPOSES: frozenset[QueryPurpose] = frozenset(
    {
        QueryPurpose.LIMITATIONS,
        QueryPurpose.ALTERNATIVES,
        QueryPurpose.FAILURE_MODES,
        QueryPurpose.COMPETING_METHODS,
        QueryPurpose.BENCHMARK,
    }
)
"""Query families that test the project rather than defend it (anti-confirmation bias)."""


class QueryStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class QueryRejectionReason(StrEnum):
    INVALID_BRANCH = "INVALID_BRANCH"
    BRANCH_NOT_PLANNABLE = "BRANCH_NOT_PLANNABLE"
    INVALID_PURPOSE = "INVALID_PURPOSE"
    PURPOSE_NOT_ALLOWED_FOR_BRANCH = "PURPOSE_NOT_ALLOWED_FOR_BRANCH"
    EMPTY_QUERY = "EMPTY_QUERY"
    QUERY_TOO_LONG = "QUERY_TOO_LONG"
    NO_SOURCE_TERMS = "NO_SOURCE_TERMS"
    INVALID_FIELD_REFERENCE = "INVALID_FIELD_REFERENCE"
    SOURCE_TERM_NOT_IN_FIELD = "SOURCE_TERM_NOT_IN_FIELD"
    SOURCE_TERM_NOT_IN_QUERY = "SOURCE_TERM_NOT_IN_QUERY"
    UNTRACEABLE_QUERY_TOKEN = "UNTRACEABLE_QUERY_TOKEN"
    TOO_MANY_EXPANSION_TERMS = "TOO_MANY_EXPANSION_TERMS"
    EMPTY_EXPANSION_TERM = "EMPTY_EXPANSION_TERM"
    PII_DETECTED = "PII_DETECTED"
    CONFIRMATION_BIASED_PHRASING = "CONFIRMATION_BIASED_PHRASING"
    SUSPECTED_PROMPT_INJECTION = "SUSPECTED_PROMPT_INJECTION"
    DUPLICATE_QUERY = "DUPLICATE_QUERY"
    BRANCH_BUDGET_EXCEEDED = "BRANCH_BUDGET_EXCEEDED"
    TOTAL_BUDGET_EXCEEDED = "TOTAL_BUDGET_EXCEEDED"


class ResearchIssueCode(StrEnum):
    INSUFFICIENT_RESEARCH_INPUT = "INSUFFICIENT_RESEARCH_INPUT"
    PLANNER_PROVIDER_MISSING = "PLANNER_PROVIDER_MISSING"
    PLANNER_MODEL_FAILED = "PLANNER_MODEL_FAILED"
    QUERY_PLAN_EMPTY = "QUERY_PLAN_EMPTY"
    QUERY_PLAN_CONFIRMATION_ONLY = "QUERY_PLAN_CONFIRMATION_ONLY"
    OFFICIAL_WEB_PROVIDER_MISSING = "OFFICIAL_WEB_PROVIDER_MISSING"
    OFFICIAL_REQUIREMENTS_UNAVAILABLE = "OFFICIAL_REQUIREMENTS_UNAVAILABLE"
    OFFICIAL_EXTRACTION_FAILED = "OFFICIAL_EXTRACTION_FAILED"
    OFFICIAL_SOURCE_CONFLICT = "OFFICIAL_SOURCE_CONFLICT"


# ---------------------------------------------------------------------------
# Model-facing planner DTOs -- untrusted candidates
# ---------------------------------------------------------------------------


class CandidateSourceTerm(ModelFacingModel):
    term: str = Field(description="A term copied from the named canonical project field.")
    field_path: str = Field(description="The canonical field the term was taken from.")


class CandidateQuery(ModelFacingModel):
    branch: str = Field(description="ACADEMIC, PATENT, PRODUCT, OPEN_SOURCE or STANDARDS.")
    purpose: str = Field(description="One QueryPurpose value.")
    query: str = Field(description="The search string.")
    source_terms: list[CandidateSourceTerm] = Field(default_factory=list)
    expansion_terms: list[str] = Field(
        default_factory=list,
        description="Related search vocabulary that is NOT a project fact.",
    )


class CandidateQueryPlan(ModelFacingModel):
    queries: list[CandidateQuery] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Verified contracts
# ---------------------------------------------------------------------------


class QueryPlanLimits(MawhibaModel):
    """Query budget. High-value coverage, not query volume."""

    max_queries_per_branch: int = Field(default=6, ge=1, le=50)
    max_total_queries: int = Field(default=24, ge=1, le=200)
    max_expansion_terms_per_query: int = Field(default=4, ge=0, le=20)
    max_query_length: int = Field(default=160, ge=20, le=500)

    @model_validator(mode="after")
    def _total_covers_a_branch(self) -> QueryPlanLimits:
        if self.max_total_queries < self.max_queries_per_branch:
            raise ValueError("max_total_queries cannot be below max_queries_per_branch")
        return self


class ProjectFieldReference(MawhibaModel):
    """A canonical ProjectState path a query was derived from."""

    field_path: str = Field(min_length=1, examples=["technical.algorithms", "claims.C-001"])


class SourceTerm(MawhibaModel):
    term: str = Field(min_length=1)
    field_path: str = Field(min_length=1)


class ResearchQuery(MawhibaModel):
    """One planned query after deterministic verification.

    An accepted query answers "why did the system search for this?" from its
    ``purpose``, its ``derived_from`` references and its ``source_terms``.
    """

    query_id: UUID = Field(default_factory=uuid4)
    research_run_id: UUID
    branch: ResearchBranch | None = None
    candidate_branch: str = ""
    purpose: QueryPurpose | None = None
    candidate_purpose: str = ""
    query: str = ""
    normalized_query: str = ""
    derived_from: list[ProjectFieldReference] = Field(default_factory=list)
    source_terms: list[SourceTerm] = Field(default_factory=list)
    expansion_terms: list[str] = Field(default_factory=list)
    status: QueryStatus
    rejection_reasons: list[QueryRejectionReason] = Field(default_factory=list)
    planner_version: str = Field(min_length=1)
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _accepted_queries_are_traceable(self) -> ResearchQuery:
        if self.status is QueryStatus.ACCEPTED:
            if self.rejection_reasons:
                raise ValueError("an accepted query cannot carry rejection reasons")
            if self.branch is None or self.purpose is None or not self.query:
                raise ValueError("an accepted query needs a branch, a purpose and a query")
            if not self.source_terms:
                raise ValueError("an accepted query must trace to at least one source term")
            if {r.field_path for r in self.derived_from} != {t.field_path for t in self.source_terms}:
                raise ValueError("derived_from must list exactly the source-term fields")
        elif not self.rejection_reasons:
            raise ValueError("a rejected query must state at least one reason")
        return self


class VerifiedQueryPlan(MawhibaModel):
    """The deterministic verdict on a candidate plan. The only plan anything uses."""

    research_run_id: UUID
    planner_version: str = Field(min_length=1)
    limits: QueryPlanLimits
    queries: list[ResearchQuery] = Field(default_factory=list)
    duplicates_removed: int = Field(default=0, ge=0)
    challenge_query_count: int = Field(default=0, ge=0)
    anti_confirmation_satisfied: bool = False
    issues: list[ResearchIssueCode] = Field(default_factory=list)

    @property
    def accepted_queries(self) -> list[ResearchQuery]:
        return [q for q in self.queries if q.status is QueryStatus.ACCEPTED]

    @property
    def rejected_queries(self) -> list[ResearchQuery]:
        return [q for q in self.queries if q.status is QueryStatus.REJECTED]

    def accepted_for(self, branch: ResearchBranch) -> list[ResearchQuery]:
        return [q for q in self.accepted_queries if q.branch is branch]


class ResearchInputField(MawhibaModel):
    field_path: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)


class ResearchInputClaim(MawhibaModel):
    claim_id: str = Field(pattern=r"^C-\d{3,}$")
    claim_type: str
    text: str = Field(min_length=1)


class ResearchInputSnapshot(MawhibaModel):
    """The PII-minimized projection of canonical state the planner may see."""

    project_id: UUID
    project_version_id: UUID
    project_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fields: list[ResearchInputField] = Field(default_factory=list)
    claims: list[ResearchInputClaim] = Field(default_factory=list)
    redaction_count: int = Field(default=0, ge=0)

    @property
    def is_empty(self) -> bool:
        return not self.fields and not self.claims


class BranchExecutionCoverage(MawhibaModel):
    """Per-branch execution coverage. Describes execution, not evidence quality."""

    branch: ResearchBranch
    required: bool = False
    planned: bool = False
    started: bool = False
    completed: bool = False
    failed: bool = False
    query_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    verified_source_count: int = Field(default=0, ge=0)
    provider_success_count: int = Field(
        default=0,
        ge=0,
        description="Provider executions that returned at least one usable record. "
        "Counted per provider per query, so the same provider can appear more "
        "than once in a multi-query branch.",
    )
    provider_failure_count: int = Field(default=0, ge=0)
    provider_empty_count: int = Field(
        default=0,
        ge=0,
        description="Provider executions that answered with no records. An empty "
        "result is not a failure.",
    )
    failure_reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> BranchExecutionCoverage:
        if self.completed and self.failed:
            raise ValueError("a branch cannot be both completed and failed")
        if (self.completed or self.failed) and not self.started:
            raise ValueError("a completed or failed branch must have started")
        if self.started and not self.planned:
            raise ValueError("a branch cannot start without a plan")
        if self.failed and not self.failure_reason:
            raise ValueError("a failed branch must state a failure_reason")
        if self.verified_source_count > self.candidate_count:
            raise ValueError("verified_source_count cannot exceed candidate_count")
        return self


class ResearchIssue(MawhibaModel):
    code: ResearchIssueCode
    node: str = Field(min_length=1)
    message: str = Field(min_length=1)
    branch: ResearchBranch | None = None


class ResearchRunVersions(MawhibaModel):
    """Everything needed to reproduce a run (section 34)."""

    research_contract_version: str = RESEARCH_CONTRACT_VERSION
    planner_prompt_version: str = Field(min_length=1)
    official_extractor_prompt_version: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    official_web_provider: str | None = None
    dataset_version: str | None = None


class ResearchRun(MawhibaModel):
    """One research execution over one project version. Immutable once terminal."""

    model_config = ConfigDict(frozen=True)

    research_run_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    project_version_id: UUID
    planner_version: str = Field(min_length=1)
    versions: ResearchRunVersions
    status: ResearchRunStatus = ResearchRunStatus.NOT_STARTED
    research_input: ResearchInputSnapshot | None = None
    query_plan: VerifiedQueryPlan | None = None
    branch_coverage: list[BranchExecutionCoverage] = Field(default_factory=list)
    official_requirements: OfficialRequirementsResult | None = None
    academic_research: AcademicRetrievalResult | None = Field(
        default=None,
        description="Phase 2B ACADEMIC branch result. On the run, never in "
        "ProjectState: retrieval reads canonical state through the verified "
        "query plan and writes none of it (ADR-006, ADR-010).",
    )
    evidence_extraction: EvidenceExtractionRun | None = Field(
        default=None,
        description="Phase 2C extracted evidence. Also on the run rather than in "
        "ProjectState.evidence: a canonical EvidenceRecord must reference a "
        "source inside ProjectState.sources, and verified academic sources "
        "deliberately live here instead (ADR-010, ADR-012).",
    )
    claim_evidence_alignment: ClaimEvidenceAlignmentRun | None = Field(
        default=None,
        description="Phase 2D claim/evidence relationship classification. Lives "
        "on the run, never in ProjectState: it references existing claims and "
        "Phase 2C evidence without mutating either, and without deciding claim "
        "sufficiency (ADR-014).",
    )
    errors: list[ResearchIssue] = Field(default_factory=list)
    started_at: UtcDatetime = Field(default_factory=utc_now)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ResearchRun:
        terminal = self.status in TERMINAL_RESEARCH_RUN_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError("completed_at is set exactly when the run is terminal")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        branches = [c.branch for c in self.branch_coverage]
        if len(set(branches)) != len(branches):
            raise ValueError("branch_coverage must have one entry per branch")
        if self.research_input is not None and (
            self.research_input.project_id != self.project_id
            or self.research_input.project_version_id != self.project_version_id
        ):
            raise ValueError("research_input belongs to a different project version")
        if self.query_plan is not None:
            if self.query_plan.research_run_id != self.research_run_id:
                raise ValueError("query_plan belongs to a different research run")
            if any(q.research_run_id != self.research_run_id for q in self.query_plan.queries):
                raise ValueError("a query belongs to a different research run")
        if (
            self.academic_research is not None
            and self.academic_research.research_run_id != self.research_run_id
        ):
            raise ValueError("academic_research belongs to a different research run")
        if (
            self.evidence_extraction is not None
            and self.evidence_extraction.research_run_id != self.research_run_id
        ):
            raise ValueError("evidence_extraction belongs to a different research run")
        if (
            self.claim_evidence_alignment is not None
            and self.claim_evidence_alignment.research_run_id != self.research_run_id
        ):
            raise ValueError(
                "claim_evidence_alignment belongs to a different research run"
            )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RESEARCH_RUN_STATUSES

    @property
    def queries(self) -> list[ResearchQuery]:
        return self.query_plan.accepted_queries if self.query_plan else []

    @property
    def official_requirements_checked(self) -> bool:
        return bool(
            self.official_requirements
            and self.official_requirements.official_requirements_checked
        )

    @property
    def academic_retrieval_ran(self) -> bool:
        """True once the ACADEMIC branch executed, whatever it found."""
        from src.schemas.academic import AcademicBranchOutcome

        return bool(
            self.academic_research
            and self.academic_research.outcome is not AcademicBranchOutcome.NOT_RUN
        )

    @property
    def evidence_extraction_ran(self) -> bool:
        """True once evidence extraction executed, whatever it found."""
        from src.schemas.evidence_extraction import EvidenceExtractionStatus

        return bool(
            self.evidence_extraction
            and self.evidence_extraction.status is not EvidenceExtractionStatus.NOT_STARTED
        )

    @property
    def claim_alignment_ran(self) -> bool:
        """True once claim-evidence alignment executed, whatever it found."""
        from src.schemas.claim_alignment import ClaimAlignmentStatus

        return bool(
            self.claim_evidence_alignment
            and self.claim_evidence_alignment.status
            is not ClaimAlignmentStatus.NOT_STARTED
        )

    def coverage_for(self, branch: ResearchBranch) -> BranchExecutionCoverage | None:
        return next((c for c in self.branch_coverage if c.branch is branch), None)

    def evolve(self, **changes: Any) -> ResearchRun:
        """A validated successor of an in-progress run. A terminal run is frozen."""
        if self.is_terminal:
            raise ValueError("a terminal research run is immutable")
        return ResearchRun.model_validate({**dict(self), **changes})
