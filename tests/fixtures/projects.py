"""Synthetic project fixtures.

Fixture A -- an AI project with critically incomplete information.
Fixture B -- an engineering project with problem, solution, baseline,
             experiments, claims, evidence and a score.

All data here is invented for testing. No real student submissions are used.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.graph.state import ProjectState
from src.schemas.claim import (
    ClaimOrigin,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    RequiredEvidenceKind,
)
from src.schemas.common import (
    ConfidenceLevel,
    TechnicalDomain,
    EvaluationStatus,
    KnowledgeStatus,
    ProjectType,
    ResearchBranch,
    BranchStatus,
    Severity,
    Tracked,
    ValueOrigin,
)
from src.schemas.evidence import (
    EvidenceLocation,
    EvidenceRecord,
    EvidenceStrength,
    EvidenceType,
    SupportDirection,
)
from src.schemas.finding import (
    ContradictionRecord,
    ContradictionStatus,
    FindingCategory,
    FindingOrigin,
    FindingRecord,
    MissingInformationRecord,
    RecommendedActionType,
)
from src.schemas.prior_art import (
    BranchCoverage,
    GapAssessment,
    NoveltyAssessment,
    PriorArtKind,
    PriorArtRecord,
    SimilarityDimensions,
)
from src.schemas.project import (
    ExperimentRecord,
    MethodologyBlock,
    ProblemBlock,
    ProjectIdentity,
    ResultRecord,
    SolutionBlock,
    TechnicalBlock,
)
from src.schemas.score import RubricKind, ScoreAxis, ScoreAxisName, ScoreRecord
from src.schemas.source import (
    PeerReviewStatus,
    ResearchQueryRecord,
    SourceProvider,
    SourceQuality,
    SourceRecord,
    SourceTier,
    SourceType,
    VerificationStatus,
)
from src.scoring.models import ADVISORY_RUBRIC_V1

FIXED_TIME = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)

FIXTURE_A_PROJECT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
FIXTURE_B_PROJECT_ID = UUID("bbbbbbbb-0000-4000-8000-000000000002")


# ---------------------------------------------------------------------------
# Fixture A -- AI project, critically incomplete
# ---------------------------------------------------------------------------

def fixture_a_incomplete_ai_project() -> ProjectState:
    """An AI project where the student gave a name and a vague claim only.

    This fixture exists to prove the system can represent *absence* honestly:
    no baseline, no dataset, no metric, one CONFLICTED accuracy figure, and an
    UNSUPPORTED performance claim.
    """
    return ProjectState(
        project_id=FIXTURE_A_PROJECT_ID,
        project_version_id=UUID("aaaaaaaa-0000-4000-8000-00000000000a"),
        version_label="v1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
        identity=ProjectIdentity(
            project_name=Tracked[str].known(
                "Smart Crop Disease Detector",
                origin=ValueOrigin.STUDENT_MESSAGE,
                location="chat:message-1",
            ),
            project_type=ProjectType.UNKNOWN,
            domain=[TechnicalDomain.ARTIFICIAL_INTELLIGENCE],
            language="ar",
        ),
        problem=ProblemBlock(
            statement=Tracked[str].known(
                "Farmers cannot identify crop disease early.",
                origin=ValueOrigin.STUDENT_MESSAGE,
                location="chat:message-1",
            ),
            beneficiaries=["farmers"],
            validation_status=EvaluationStatus.NOT_EVALUATED,
        ),
        solution=SolutionBlock(
            description=Tracked[str].known(
                "A mobile app that classifies leaf photos.",
                origin=ValueOrigin.STUDENT_MESSAGE,
            ),
            # The student never explained *how* it works.
            technical_principle=Tracked[str].unknown(
                "student did not describe the model or the technical principle"
            ),
            claimed_innovation=["first Arabic-language crop disease app"],
        ),
        technical=TechnicalBlock(
            architecture=Tracked[str].unknown("no architecture provided"),
            software=["Python", "TensorFlow"],
        ),
        methodology=MethodologyBlock(
            research_question=Tracked[str].unknown(),
            hypothesis=Tracked[str].unknown(),
            # No baseline and no metric at all -- represented as empty, and
            # separately recorded in missing_critical_information.
            baseline=[],
            metrics=[],
            experimental_design=Tracked[str].unknown(),
            review_status=EvaluationStatus.INSUFFICIENT_EVIDENCE,
        ),
        results=[
            ResultRecord(
                result_id="R-01",
                metric="accuracy",
                # Two student artifacts disagree: 95% in the poster, 87% in the
                # report. Neither is adopted as truth.
                value=Tracked[str].conflicted(
                    ["95%", "87%"],
                    note="poster says 95%, written report says 87%",
                ),
                baseline_value=Tracked[str].unknown("no baseline reported"),
            )
        ],
        claims=[
            ClaimRecord(
                claim_id="C-001",
                claim="The system is more accurate than existing solutions.",
                claim_type=ClaimType.PERFORMANCE,
                origin=ClaimOrigin.STUDENT,
                status=ClaimStatus.UNSUPPORTED,
                evidence_ids=[],
                required_evidence=[
                    RequiredEvidenceKind.BASELINE,
                    RequiredEvidenceKind.TEST_DATA,
                    RequiredEvidenceKind.METRIC,
                    RequiredEvidenceKind.REPEATED_MEASUREMENTS,
                ],
                missing_evidence=[
                    RequiredEvidenceKind.BASELINE,
                    RequiredEvidenceKind.TEST_DATA,
                    RequiredEvidenceKind.METRIC,
                    RequiredEvidenceKind.REPEATED_MEASUREMENTS,
                ],
                confidence=0.0,
                is_critical=True,
            ),
            ClaimRecord(
                claim_id="C-002",
                claim="No similar Arabic-language application exists.",
                claim_type=ClaimType.NOVELTY,
                origin=ClaimOrigin.STUDENT,
                status=ClaimStatus.UNSUPPORTED,
                required_evidence=[RequiredEvidenceKind.PRIOR_ART_SEARCH],
                missing_evidence=[RequiredEvidenceKind.PRIOR_ART_SEARCH],
                is_critical=True,
            ),
        ],
        novelty=NoveltyAssessment(
            level=None,
            status=EvaluationStatus.NOT_EVALUATED,
            branch_coverage=[
                BranchCoverage(
                    branch=ResearchBranch.ACADEMIC,
                    required=True,
                    status=BranchStatus.NOT_STARTED,
                ),
                BranchCoverage(
                    branch=ResearchBranch.PATENT,
                    required=True,
                    status=BranchStatus.NOT_STARTED,
                ),
                BranchCoverage(
                    branch=ResearchBranch.OPEN_SOURCE,
                    required=True,
                    status=BranchStatus.NOT_STARTED,
                ),
            ],
        ),
        gap=GapAssessment(status=EvaluationStatus.NOT_EVALUATED),
        contradictions=[
            ContradictionRecord(
                contradiction_id="CT-001",
                description="Reported accuracy differs between poster and report.",
                severity=Severity.CRITICAL,
                status=ContradictionStatus.AWAITING_STUDENT,
                conflicting_statements=[
                    "poster: accuracy 95%",
                    "report: accuracy 87%",
                ],
                affected_claim_ids=["C-001"],
                requires_student_clarification=True,
            )
        ],
        missing_critical_information=[
            MissingInformationRecord(
                field_path="methodology.baseline",
                description="No baseline was reported for the accuracy comparison.",
                severity=Severity.CRITICAL,
                retrievable_externally=False,
                question_for_student="What baseline did you compare against?",
                blocks_axes=[ScoreAxisName.RESULTS.value],
            ),
            MissingInformationRecord(
                field_path="technical.datasets",
                description="Dataset source, size and splits are unknown.",
                severity=Severity.CRITICAL,
                retrievable_externally=False,
                question_for_student="Which dataset did you use, and how was it split?",
                blocks_axes=[ScoreAxisName.EXPERIMENTS.value],
            ),
        ],
        evaluation_status=EvaluationStatus.INSUFFICIENT_EVIDENCE,
    )


# ---------------------------------------------------------------------------
# Fixture B -- engineering project, complete chain
# ---------------------------------------------------------------------------

def fixture_b_complete_engineering_project() -> ProjectState:
    """A water-leak detection device with a full evidence chain.

    Problem -> solution -> baseline -> experiments -> claims -> evidence ->
    sources -> score. Used to test the happy path and the score arithmetic.
    """
    sources = [
        SourceRecord(
            source_id="SRC-001",
            source_type=SourceType.ACADEMIC_PAPER,
            title="Acoustic Leak Detection in Municipal Water Networks",
            authors_or_org=["Rivera, K.", "Osei, D."],
            year=2024,
            journal_or_venue="Journal of Water Infrastructure",
            doi="10.9999/jwi.2024.0142",
            url="https://example.org/jwi/2024/0142",
            provider=SourceProvider.OPENALEX,
            retrieved_at=FIXED_TIME,
            peer_review_status=PeerReviewStatus.PEER_REVIEWED,
            query_id="Q-001",
            branch=ResearchBranch.ACADEMIC,
            content_hash="sha256:5f1c0a",
            quality=SourceQuality(
                authority=0.9,
                relevance=0.9,
                methodological_strength=0.8,
                recency_fit=0.9,
                independent_validation=0.6,
            ),
            tier=SourceTier.TIER_A,
            verification_status=VerificationStatus.VERIFIED_FULL_TEXT,
        ),
        SourceRecord(
            source_id="SRC-002",
            source_type=SourceType.PATENT,
            title="Pipeline leak detection apparatus using pressure transients",
            authors_or_org=["Hydrosense Ltd."],
            year=2021,
            url="https://example.org/patents/EP1234567",
            provider=SourceProvider.EPO_OPS,
            retrieved_at=FIXED_TIME,
            peer_review_status=PeerReviewStatus.NOT_APPLICABLE,
            query_id="Q-002",
            branch=ResearchBranch.PATENT,
            content_hash="sha256:9ab3f1",
            quality=SourceQuality(
                authority=0.8,
                relevance=0.7,
                methodological_strength=0.6,
                recency_fit=0.7,
                independent_validation=0.5,
            ),
            tier=SourceTier.TIER_A,
            verification_status=VerificationStatus.VERIFIED_METADATA,
        ),
        SourceRecord(
            source_id="SRC-003",
            source_type=SourceType.DATASHEET,
            title="MX-770 Piezo Vibration Sensor Datasheet",
            authors_or_org=["MicroX"],
            year=2023,
            url="https://example.org/microx/mx770",
            provider=SourceProvider.TAVILY,
            retrieved_at=FIXED_TIME,
            peer_review_status=PeerReviewStatus.NOT_APPLICABLE,
            query_id="Q-003",
            branch=ResearchBranch.PRODUCT,
            content_hash="sha256:1de044",
            quality=SourceQuality(
                authority=0.7,
                relevance=0.8,
                methodological_strength=0.5,
                recency_fit=0.8,
                independent_validation=0.4,
            ),
            tier=SourceTier.TIER_B,
            verification_status=VerificationStatus.VERIFIED_METADATA,
        ),
    ]

    evidence = [
        EvidenceRecord(
            evidence_id="E-001",
            source_id="SRC-001",
            evidence_type=EvidenceType.BASELINE,
            statement=(
                "Commercial acoustic correlators detect leaks at 0.35 L/min with "
                "a 12% false positive rate under comparable pipe conditions."
            ),
            support_direction=SupportDirection.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            location=EvidenceLocation(
                page=7,
                section="Table 3",
                quote_or_extract="0.35 L/min detection threshold; FPR 12%",
            ),
            verified=True,
            verified_at=FIXED_TIME,
        ),
        EvidenceRecord(
            evidence_id="E-002",
            source_id="SRC-001",
            evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
            statement=(
                "Prototype detected leaks at 0.18 L/min across 40 repeated runs "
                "on the same test rig used for the baseline."
            ),
            support_direction=SupportDirection.SUPPORTS,
            strength=EvidenceStrength.STRONG,
            location=EvidenceLocation(section="Experiment EXP-01 log"),
            verified=True,
            verified_at=FIXED_TIME,
        ),
        EvidenceRecord(
            evidence_id="E-003",
            source_id="SRC-002",
            evidence_type=EvidenceType.PRIOR_ART,
            statement=(
                "Prior patent covers pressure-transient detection, not "
                "piezo vibration signatures with on-device filtering."
            ),
            support_direction=SupportDirection.NEUTRAL,
            strength=EvidenceStrength.MODERATE,
            location=EvidenceLocation(section="Claims 1-4"),
            verified=True,
            verified_at=FIXED_TIME,
        ),
        EvidenceRecord(
            evidence_id="E-004",
            source_id="SRC-003",
            evidence_type=EvidenceType.TECHNICAL_SPECIFICATION,
            statement="MX-770 sensitivity is 12 mV/g across 10 Hz - 2 kHz.",
            support_direction=SupportDirection.SUPPORTS,
            strength=EvidenceStrength.MODERATE,
            location=EvidenceLocation(page=2, section="Electrical characteristics"),
            verified=True,
            verified_at=FIXED_TIME,
        ),
    ]

    claims = [
        ClaimRecord(
            claim_id="C-001",
            claim=(
                "The prototype detects smaller leaks than commercial acoustic "
                "correlators under the same test conditions."
            ),
            claim_type=ClaimType.PERFORMANCE,
            origin=ClaimOrigin.STUDENT,
            status=ClaimStatus.SUPPORTED,
            evidence_ids=["E-001", "E-002"],
            required_evidence=[
                RequiredEvidenceKind.BASELINE,
                RequiredEvidenceKind.TEST_DATA,
                RequiredEvidenceKind.METRIC,
                RequiredEvidenceKind.REPEATED_MEASUREMENTS,
                RequiredEvidenceKind.SAME_EVALUATION_SETTING,
            ],
            missing_evidence=[],
            confidence=0.72,
            is_critical=True,
        ),
        ClaimRecord(
            claim_id="C-002",
            claim=(
                "Using piezo vibration signatures with on-device filtering is a "
                "different mechanism from the closest prior patent."
            ),
            claim_type=ClaimType.NOVELTY,
            origin=ClaimOrigin.AGENT_DERIVED,
            status=ClaimStatus.SUPPORTED,
            evidence_ids=["E-003"],
            required_evidence=[RequiredEvidenceKind.PRIOR_ART_SEARCH],
            missing_evidence=[],
            confidence=0.6,
            is_critical=True,
        ),
        ClaimRecord(
            claim_id="C-003",
            claim="The device can run for a full year on one battery charge.",
            claim_type=ClaimType.FEASIBILITY,
            origin=ClaimOrigin.STUDENT,
            status=ClaimStatus.PLAUSIBLE,
            evidence_ids=["E-004"],
            required_evidence=[RequiredEvidenceKind.REPEATED_MEASUREMENTS],
            missing_evidence=[RequiredEvidenceKind.REPEATED_MEASUREMENTS],
            confidence=0.3,
        ),
    ]

    prior_art = [
        PriorArtRecord(
            prior_art_id="PA-001",
            source_id="SRC-002",
            kind=PriorArtKind.PATENT,
            title="Pipeline leak detection apparatus using pressure transients",
            similarity_dimensions=SimilarityDimensions(
                problem=0.9,
                method=0.4,
                architecture=0.35,
                algorithm=0.3,
                deployment=0.6,
                evaluation=0.5,
            ),
            shared_features=["same problem domain", "in-pipe deployment"],
            different_features=["pressure transients vs piezo vibration signature"],
            novelty_threat=Severity.MEDIUM,
            rank=1,
            evidence_ids=["E-003"],
        ),
        PriorArtRecord(
            prior_art_id="PA-002",
            source_id="SRC-001",
            kind=PriorArtKind.ACADEMIC,
            title="Acoustic Leak Detection in Municipal Water Networks",
            similarity_dimensions=SimilarityDimensions(
                problem=0.95, method=0.55, evaluation=0.8
            ),
            shared_features=["acoustic sensing", "municipal networks"],
            different_features=["no on-device filtering"],
            novelty_threat=Severity.HIGH,
            rank=2,
            evidence_ids=["E-001"],
        ),
    ]

    findings = [
        FindingRecord(
            finding_id="F-001",
            category=FindingCategory.EXPERIMENTS,
            severity=Severity.MEDIUM,
            finding="Battery-life claim rests on a datasheet figure, not a measurement.",
            reason=(
                "A year-long duty cycle was never measured; the datasheet only "
                "gives sensor sensitivity, not system power draw."
            ),
            evidence_ids=["E-004"],
            affected_claim_ids=["C-003"],
            recommended_action_type=RecommendedActionType.REQUIRES_ADDITIONAL_EXPERIMENT,
            confidence=ConfidenceLevel.HIGH,
            origin=FindingOrigin.RED_TEAM,
        )
    ]

    score = ScoreRecord(
        score_id="SC-001",
        rubric_version=ADVISORY_RUBRIC_V1.version,
        rubric_kind=RubricKind.ADVISORY,
        official=False,
        max_total=ADVISORY_RUBRIC_V1.max_total,
        status=EvaluationStatus.PROVISIONAL,
        computed_at=FIXED_TIME,
        axes=[
            ScoreAxis(
                axis=ScoreAxisName.PROBLEM_AND_IMPORTANCE.value,
                score=8.0,
                max_score=10,
                evidence_ids=["E-001"],
                completeness=0.9,
                confidence=ConfidenceLevel.HIGH,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.SCIENTIFIC_TECHNICAL_BASE.value,
                score=7.0,
                max_score=10,
                evidence_ids=["E-004"],
                completeness=0.8,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.LITERATURE.value,
                score=6.0,
                max_score=10,
                evidence_ids=["E-001", "E-003"],
                completeness=0.7,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.NOVELTY.value,
                score=9.0,
                max_score=15,
                evidence_ids=["E-003"],
                finding_ids=[],
                completeness=0.75,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.GAP.value,
                score=6.0,
                max_score=10,
                evidence_ids=["E-001"],
                completeness=0.7,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.METHODOLOGY.value,
                score=11.0,
                max_score=15,
                evidence_ids=["E-002"],
                completeness=0.85,
                confidence=ConfidenceLevel.HIGH,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.EXPERIMENTS.value,
                score=11.0,
                max_score=15,
                evidence_ids=["E-002"],
                finding_ids=["F-001"],
                completeness=0.8,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.RESULTS.value,
                score=7.0,
                max_score=10,
                evidence_ids=["E-002"],
                completeness=0.8,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
            ScoreAxis(
                axis=ScoreAxisName.JURY_DEFENSIBILITY.value,
                score=3.0,
                max_score=5,
                evidence_ids=["E-002"],
                completeness=0.7,
                confidence=ConfidenceLevel.MEDIUM,
                provisional=True,
                status=EvaluationStatus.PROVISIONAL,
            ),
        ],
        total=68.0,
    )

    return ProjectState(
        project_id=FIXTURE_B_PROJECT_ID,
        project_version_id=UUID("bbbbbbbb-0000-4000-8000-00000000000b"),
        version_label="v2",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
        identity=ProjectIdentity(
            project_name=Tracked[str].known("PiezoLeak: in-pipe leak detector"),
            project_type=ProjectType.ENGINEERING_PROJECT,
            project_type_confidence=0.88,
            domain=[TechnicalDomain.INTERNET_OF_THINGS, TechnicalDomain.EMBEDDED_SYSTEMS],
            language="ar",
        ),
        problem=ProblemBlock(
            statement=Tracked[str].known(
                "Small municipal water leaks go undetected for weeks, wasting "
                "water and eroding pipe beds.",
                origin=ValueOrigin.STUDENT_FILE,
                location="report.pdf p.2",
            ),
            beneficiaries=["municipal water utilities", "residents"],
            importance_claims=["C-001"],
            validation_status=EvaluationStatus.FINAL,
            validation_verdict="REAL_PROBLEM",
            evidence_ids=["E-001"],
        ),
        solution=SolutionBlock(
            description=Tracked[str].known(
                "A battery-powered in-pipe node that classifies piezo vibration "
                "signatures on-device and reports leaks over LoRaWAN.",
                origin=ValueOrigin.STUDENT_FILE,
                location="report.pdf p.4",
            ),
            technical_principle=Tracked[str].known(
                "Leak turbulence produces a characteristic 200-800 Hz vibration "
                "band distinguishable from pump noise.",
                origin=ValueOrigin.STUDENT_FILE,
                location="report.pdf p.5",
            ),
            claimed_innovation=["on-device band filtering to cut false positives"],
        ),
        technical=TechnicalBlock(
            architecture=Tracked[str].known(
                "MX-770 piezo -> analog band-pass -> STM32 feature extraction -> "
                "threshold classifier -> LoRaWAN uplink",
                origin=ValueOrigin.STUDENT_FILE,
                location="report.pdf p.6",
            ),
            hardware=["STM32L4", "MX-770 piezo sensor", "LoRaWAN module"],
            software=["C", "CMSIS-DSP"],
            sensors=["MX-770 piezo vibration"],
            algorithms=["band-pass filtering", "threshold classifier"],
        ),
        methodology=MethodologyBlock(
            research_question=Tracked[str].known(
                "Can on-device band filtering lower the minimum detectable leak "
                "rate relative to commercial acoustic correlators?"
            ),
            hypothesis=Tracked[str].known(
                "Filtering the 200-800 Hz band lowers the detection threshold "
                "below 0.35 L/min."
            ),
            variables=["leak rate", "pipe pressure", "pump noise level"],
            baseline=["commercial acoustic correlator (SRC-001, Table 3)"],
            metrics=["minimum detectable leak rate (L/min)", "false positive rate"],
            experimental_design=Tracked[str].known(
                "Controlled test rig, 40 runs per condition, 4 leak rates, "
                "randomized order, same rig for baseline and prototype."
            ),
            statistics=Tracked[str].known("Welch t-test on detection thresholds"),
            review_status=EvaluationStatus.FINAL,
        ),
        experiments=[
            ExperimentRecord(
                experiment_id="EXP-01",
                objective="Determine minimum detectable leak rate versus baseline.",
                hypothesis="Prototype detects below 0.35 L/min.",
                setup="Closed-loop PVC rig, 3 bar, calibrated needle-valve leak.",
                inputs=["leak rate setpoint", "pump noise level"],
                outputs=["detection flag", "signal band energy"],
                variables=["leak rate"],
                controls=["pipe pressure", "ambient temperature"],
                baseline=["commercial acoustic correlator"],
                sample_size=40,
                repetitions=40,
                measurement_method="Reference flow meter, class 1 accuracy.",
                metrics=["minimum detectable leak rate", "false positive rate"],
                statistics=["Welch t-test"],
                error_sources=["pump vibration coupling", "valve hysteresis"],
                success_criteria=["threshold below 0.35 L/min at FPR <= 12%"],
                reproducibility=Tracked[str].known(
                    "Rig schematic and firmware commit hash included in the report."
                ),
                supports_claim_ids=["C-001"],
                evidence_ids=["E-002"],
            )
        ],
        results=[
            ResultRecord(
                result_id="R-01",
                experiment_id="EXP-01",
                metric="minimum detectable leak rate",
                value=Tracked[str].known("0.18 L/min"),
                baseline_value=Tracked[str].known("0.35 L/min"),
                conditions="3 bar, pump running, 40 runs",
                evidence_ids=["E-001", "E-002"],
            )
        ],
        sources=sources,
        evidence=evidence,
        claims=claims,
        prior_art=prior_art,
        research_queries=[
            ResearchQueryRecord(
                query_id="Q-001",
                branch=ResearchBranch.ACADEMIC,
                query="acoustic leak detection minimum detectable leak rate baseline",
                provider=SourceProvider.OPENALEX,
                started_at=FIXED_TIME,
                completed_at=FIXED_TIME,
                result_count=25,
                selected_count=7,
                status=BranchStatus.COMPLETED,
            ),
            ResearchQueryRecord(
                query_id="Q-002",
                branch=ResearchBranch.PATENT,
                query="pipeline leak detection vibration signature apparatus",
                provider=SourceProvider.EPO_OPS,
                started_at=FIXED_TIME,
                completed_at=FIXED_TIME,
                result_count=18,
                selected_count=3,
                status=BranchStatus.COMPLETED,
            ),
            ResearchQueryRecord(
                query_id="Q-003",
                branch=ResearchBranch.PRODUCT,
                query="piezo vibration sensor datasheet sensitivity mV/g",
                provider=SourceProvider.TAVILY,
                started_at=FIXED_TIME,
                completed_at=FIXED_TIME,
                result_count=11,
                selected_count=2,
                status=BranchStatus.COMPLETED,
            ),
        ],
        novelty=NoveltyAssessment(
            level=3,
            status=EvaluationStatus.PROVISIONAL,
            confidence=0.62,
            confidence_level=ConfidenceLevel.MEDIUM,
            rationale=(
                "Measurable improvement over a verified baseline; mechanism "
                "differs from the closest patent but the combination is not new."
            ),
            closest_prior_art_ids=["PA-001", "PA-002"],
            differentiators=["on-device 200-800 Hz band filtering"],
            evidence_ids=["E-001", "E-002", "E-003"],
            branch_coverage=[
                BranchCoverage(
                    branch=ResearchBranch.ACADEMIC,
                    required=True,
                    status=BranchStatus.COMPLETED,
                    query_ids=["Q-001"],
                    source_count=1,
                    coverage=0.8,
                ),
                BranchCoverage(
                    branch=ResearchBranch.PATENT,
                    required=True,
                    status=BranchStatus.COMPLETED,
                    query_ids=["Q-002"],
                    source_count=1,
                    coverage=0.75,
                ),
                BranchCoverage(
                    branch=ResearchBranch.PRODUCT,
                    required=True,
                    status=BranchStatus.COMPLETED,
                    query_ids=["Q-003"],
                    source_count=1,
                    coverage=0.7,
                ),
                BranchCoverage(
                    branch=ResearchBranch.OPEN_SOURCE,
                    required=False,
                    status=BranchStatus.NOT_REQUIRED,
                ),
            ],
        ),
        gap=GapAssessment(
            engineering_gap=(
                "Existing correlators detect down to 0.35 L/min but degrade under "
                "pump noise; the project tests whether on-device band filtering "
                "lowers that threshold, measured as minimum detectable leak rate."
            ),
            status=EvaluationStatus.FINAL,
            strength=ConfidenceLevel.MEDIUM,
            confidence=0.65,
            evidence_ids=["E-001", "E-002"],
        ),
        findings=findings,
        scores=[score],
        evaluation_status=EvaluationStatus.PROVISIONAL,
    )
