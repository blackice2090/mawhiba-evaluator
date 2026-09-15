"""Project sub-structures -- architecture 6 (Canonical PROJECT_STATE) and 16
(Experiment Reviewer).

Critical narrative fields are wrapped in ``Tracked`` so that "not provided",
"inferred", "unknown" and "conflicting" are all representable (2.1).
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.schemas.common import (
    EvaluationStatus,
    MawhibaModel,
    ProjectType,
    TechnicalDomain,
    Tracked,
    UnitInterval,
    migrate_domain,
)

ProjectDomain = TechnicalDomain
"""Backwards-compatible alias.

Phase 0 named the enum ``ProjectDomain``; Phase 1C unified it with the intake
classifier's taxonomy (ADR-005). The alias keeps older imports working while
there is exactly one enum behind both names.
"""


class ProjectIdentity(MawhibaModel):
    project_name: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    project_type: ProjectType = ProjectType.UNKNOWN
    project_type_confidence: UnitInterval | None = None
    domain: list[TechnicalDomain] = Field(
        default_factory=list,
        description="Canonical technical domains. Same enum the classifier emits.",
    )
    # Describes the student's project, not the system. Mirrors
    # config.settings.STUDENT_DEFAULT_LANGUAGE; the literal avoids a circular
    # import from schemas back into config.
    language: str = Field(default="ar", min_length=2, max_length=8)

    @field_validator("domain", mode="before")
    @classmethod
    def _migrate_legacy_domains(cls, value: object) -> object:
        """Accept Phase 0 / Phase 1B domain spellings from old snapshots.

        Migration happens here rather than in a separate script so a serialized
        state written before Phase 1C still loads. Unrecognized values are passed
        through so pydantic reports them instead of this validator guessing.
        """
        if isinstance(value, list):
            return [migrate_domain(item) for item in value]
        return value

    @model_validator(mode="after")
    def _unknown_type_has_no_confidence(self) -> ProjectIdentity:
        if (
            self.project_type == ProjectType.UNKNOWN
            and self.project_type_confidence is not None
        ):
            raise ValueError(
                "project_type=UNKNOWN must not carry a classification confidence (2.1)"
            )
        return self


class ProblemBlock(MawhibaModel):
    """N04 problem validation."""

    statement: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    beneficiaries: list[str] = Field(default_factory=list)
    importance_claims: list[str] = Field(
        default_factory=list, description="Claim ids (C-xxx) asserting importance."
    )
    validation_status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    validation_verdict: str | None = Field(
        default=None,
        description="REAL_PROBLEM | ASSUMED_PROBLEM | POORLY_DEFINED_PROBLEM (N04).",
    )
    evidence_ids: list[str] = Field(default_factory=list)


class SolutionBlock(MawhibaModel):
    description: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    technical_principle: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    claimed_innovation: list[str] = Field(default_factory=list)


class TechnicalBlock(MawhibaModel):
    """The project's technical content, as stated by the student.

    The collections are deliberately NOT interchangeable. ``technologies`` exists
    because a technology is frequently neither software nor hardware -- LoRa,
    Edge Computing, Kalman Filtering, Digital Twin, Computer Vision -- and
    Phase 1B's approximation of routing every technology into ``software`` was a
    lossy misclassification that later research routing would have inherited.
    """

    architecture: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    technologies: list[str] = Field(
        default_factory=list,
        description="General technologies and techniques that are not specifically "
        "hardware, software, a sensor, an algorithm, a model or a dataset.",
    )
    hardware: list[str] = Field(default_factory=list)
    software: list[str] = Field(default_factory=list)
    sensors: list[str] = Field(default_factory=list)
    algorithms: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(
        default_factory=list,
        description="Where the data came from, as stated. Distinct from `datasets`, "
        "which names the dataset itself.",
    )
    prototype_status: Tracked[str] = Field(
        default_factory=Tracked[str].unknown,
        description="What has actually been built, in the student's own words.",
    )


class MethodologyBlock(MawhibaModel):
    """N12. Baseline and metrics are the two fields most claims depend on."""

    research_question: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    hypothesis: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    variables: list[str] = Field(default_factory=list)
    baseline: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    experimental_design: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    statistics: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    review_status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED


class ExperimentRecord(MawhibaModel):
    """Section 16 Experiment Reviewer contract."""

    experiment_id: str = Field(pattern=r"^EXP-\d{2,}$", examples=["EXP-01"])
    objective: str = ""
    hypothesis: str | None = None
    setup: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    baseline: list[str] = Field(default_factory=list)
    sample_size: int | None = Field(default=None, ge=0)
    repetitions: int | None = Field(default=None, ge=0)
    measurement_method: str | None = None
    metrics: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(default_factory=list)
    error_sources: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    reproducibility: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    supports_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ResultRecord(MawhibaModel):
    """A reported measurement. ``value`` is a string so units stay attached and
    no numeric coercion invents precision."""

    result_id: str = Field(pattern=r"^R-\d{2,}$", examples=["R-01"])
    experiment_id: str | None = Field(default=None, pattern=r"^EXP-\d{2,}$")
    metric: str = Field(min_length=1)
    value: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    baseline_value: Tracked[str] = Field(default_factory=Tracked[str].unknown)
    conditions: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class RiskRecord(MawhibaModel):
    """Section 19 Red Team top risks, stored alongside their finding."""

    risk_id: str = Field(pattern=r"^RK-\d{2,}$", examples=["RK-01"])
    risk: str = Field(min_length=1)
    impact: str | None = None
    finding_id: str | None = Field(default=None, pattern=r"^F-\d{3,}$")
    rank: int | None = Field(default=None, ge=1)
