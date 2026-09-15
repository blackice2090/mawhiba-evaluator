"""Intake eval runner.

Drives each Gold case through the real pipeline -- extract, verify, merge,
classify, merge -- and scores the resulting canonical state against expectations
authored independently of any model.

Two modes:

* **Fake provider** (default, CI): scripted responses from the dataset, fully
  deterministic, no network, no key.
* **Live** (explicit opt-in only): the real OpenAI provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from uuid import uuid4

from src.config.settings import LLMSettings
from src.evals.dataset import GoldCase, GoldDataset, GoldExpectation
from src.evals.metrics import IntakeMetrics
from src.graph.state import ProjectState
from src.intake.extractor import run_project_classification, run_project_extraction
from src.intake.merge import merge_classification, merge_intake_extraction
from src.intake.verification import verify_classification, verify_extraction
from src.llm.contracts import ModelCallStatus, ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.llm.provider import StructuredModelProvider
from src.schemas.claim import ClaimOrigin, ClaimStatus
from src.schemas.common import KnowledgeStatus, ProjectType, Tracked
from src.schemas.extraction import (
    ProjectClassification,
    ProjectExtraction,
    RejectedExtraction,
)
from src.schemas.submission import StudentSubmissionArtifact

logger = logging.getLogger(__name__)

FAILURE_BUILDERS = {
    "REFUSAL": refusal_result,
    "PROVIDER_ERROR": provider_error_result,
    "INCOMPLETE_OUTPUT": incomplete_result,
    "PARSE_ERROR": parse_error_result,
    "EMPTY_OUTPUT": empty_result,
}


@dataclass
class CaseResult:
    """Everything one case produced, for scoring and for debugging."""

    case_id: str
    category: str
    language: str
    project: ProjectState
    ledger: list[RejectedExtraction] = dataclass_field(default_factory=list)
    rejected_field_paths: list[str] = dataclass_field(default_factory=list)
    extraction_status: ModelCallStatus | None = None
    classification_status: ModelCallStatus | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _resolve(project: ProjectState, path: str) -> object:
    """Read a dotted canonical path off the state."""
    target: object = project
    for part in path.split("."):
        target = getattr(target, part)
    return target


def _provider_for(case: GoldCase, live: bool) -> StructuredModelProvider:
    """Build the provider for one case.

    In fake mode the dataset's scripted responses drive the run, including
    deliberate misbehaviour. In live mode the real model answers and the same
    Gold expectations apply.
    """
    if live:
        from src.llm.openai_provider import OpenAIResponsesProvider

        return OpenAIResponsesProvider()

    scripted = case.scripted
    responses: list[object] = []

    if scripted.failure:
        builder = FAILURE_BUILDERS[scripted.failure]
        responses.append(builder(ModelTask.PROJECT_EXTRACTION))
    else:
        responses.append(ProjectExtraction.model_validate(scripted.extraction or {}))

    if scripted.classification is not None:
        responses.append(ProjectClassification.model_validate(scripted.classification))

    return FakeStructuredModelProvider(responses=responses)


def _prior_provider(case: GoldCase) -> StructuredModelProvider:
    return FakeStructuredModelProvider(
        responses=[ProjectExtraction.model_validate(case.scripted.prior_extraction or {})]
    )


def run_case(
    case: GoldCase, *, settings: LLMSettings | None = None, live: bool = False
) -> CaseResult:
    """Run one Gold case through the real intake pipeline."""
    settings = settings or LLMSettings(escalation_enabled=False, max_retries=0)
    project = ProjectState()
    result = CaseResult(
        case_id=case.case_id,
        category=case.category,
        language=case.language,
        project=project,
    )

    try:
        # Multi-turn cases establish prior state first, through the same path.
        if case.prior_submission is not None:
            prior_artifact = StudentSubmissionArtifact(
                project_id=uuid4(), original_text=case.prior_submission, sequence=1
            )
            prior_call = run_project_extraction(
                prior_artifact, _prior_provider(case), settings
            )
            if prior_call.succeeded:
                verified_prior = verify_extraction(prior_artifact, prior_call.parsed)
                project, _ = merge_intake_extraction(project, verified_prior)

        artifact = StudentSubmissionArtifact(
            project_id=uuid4(),
            original_text=case.submission,
            sequence=2 if case.prior_submission else 1,
        )
        provider = _provider_for(case, live)

        call = run_project_extraction(artifact, provider, settings)
        result.extraction_status = call.status

        if call.succeeded:
            verified = verify_extraction(artifact, call.parsed)
            result.ledger = verified.ledger
            result.rejected_field_paths = [f.field_path for f in verified.rejected_fields]
            project, _ = merge_intake_extraction(project, verified)

        # Classification runs only when the case expects it, and a classification
        # failure is non-fatal by design.
        wants_classification = live or case.scripted.classification is not None
        if wants_classification and call.succeeded:
            class_call = run_project_classification(artifact, provider, settings)
            result.classification_status = class_call.status
            if class_call.succeeded:
                verified_class = verify_classification(artifact, class_call.parsed)
                project, _ = merge_classification(project, verified_class)

        result.project = project
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        result.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, result.error)

    return result


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_case(case: GoldCase, result: CaseResult, metrics: IntakeMetrics) -> None:
    """Fold one case result into the metric set."""
    if not result.ok:
        metrics.cases_errored += 1
        return

    metrics.cases_evaluated += 1
    expected: GoldExpectation = case.expected
    project = result.project

    # --- accepted field precision + provenance ---------------------------
    for path, want in expected.known_fields.items():
        tracked = _resolve(project, path)
        got_known = isinstance(tracked, Tracked) and tracked.status is KnowledgeStatus.KNOWN
        correct = got_known and tracked.value == want
        metrics.accepted_field_precision.add(correct)
        if got_known:
            has_provenance = bool(tracked.location and "artifact=" in tracked.location)
            metrics.provenance_validity.add(has_provenance)
            metrics.invalid_provenance_acceptance.record(not has_provenance)

    # --- unknown preservation: the fabrication defence --------------------
    for path in expected.unknown_fields:
        tracked = _resolve(project, path)
        stayed_unknown = (
            isinstance(tracked, Tracked) and tracked.status is KnowledgeStatus.UNKNOWN
        )
        metrics.unknown_preservation.add(stayed_unknown)
        # A field Gold says is absent that came back KNOWN is a fabrication.
        fabricated = isinstance(tracked, Tracked) and tracked.status is KnowledgeStatus.KNOWN
        metrics.unsupported_known_acceptance.record(fabricated)

    for path in expected.conflicted_fields:
        tracked = _resolve(project, path)
        metrics.accepted_field_precision.add(
            isinstance(tracked, Tracked)
            and tracked.status is KnowledgeStatus.CONFLICTED
        )

    # --- list fields -------------------------------------------------------
    for path, want_list in expected.list_fields.items():
        got = _resolve(project, path)
        got_list = list(got) if isinstance(got, list) else []
        matches = sorted(got_list) == sorted(want_list)
        metrics.list_field_accuracy.add(matches)
        # Anything present that Gold did not list is unsupported content.
        for value in got_list:
            metrics.unsupported_known_acceptance.record(value not in want_list)

    # --- rejections --------------------------------------------------------
    for path in expected.rejected_fields:
        metrics.rejection_accuracy.add(path in result.rejected_field_paths)

    # --- claims ------------------------------------------------------------
    for want_claim in expected.claims:
        found = next(
            (c for c in project.claims if c.claim == want_claim["claim"]), None
        )
        metrics.student_claim_isolation.add(
            found is not None
            and found.origin is ClaimOrigin.STUDENT
            and found.status is ClaimStatus.UNSUPPORTED
            and not found.evidence_ids
        )
    # A claim that acquired evidence, or any evidence at all at intake, is leakage.
    if expected.claims or expected.no_evidence:
        leaked = bool(project.evidence) or bool(project.sources) or any(
            c.evidence_ids for c in project.claims
        )
        metrics.student_claim_leakage.record(leaked)

    # --- classification ----------------------------------------------------
    if expected.project_type is not None:
        metrics.project_type_accuracy.add(
            project.identity.project_type is ProjectType(expected.project_type)
        )

    if expected.domains is not None:
        got_domains = {d.value for d in project.identity.domain}
        want_domains = set(expected.domains)
        for domain in got_domains:
            metrics.domain_precision.add(domain in want_domains)
        for domain in want_domains:
            metrics.domain_recall.add(domain in got_domains)

    # --- conflicts ---------------------------------------------------------
    if expected.contradictions is not None:
        got = len(project.contradictions)
        metrics.conflict_recall.add(got >= expected.contradictions)
        metrics.conflict_precision.add(got == expected.contradictions)

    # --- merge stability: earlier KNOWN survives a later turn --------------
    if case.prior_submission is not None:
        preserved = all(
            isinstance(_resolve(project, p), Tracked)
            and _resolve(project, p).status
            in (KnowledgeStatus.KNOWN, KnowledgeStatus.CONFLICTED)
            for p in expected.known_fields
        ) and all(
            _resolve(project, p) is not None for p in expected.conflicted_fields
        )
        metrics.canonical_merge_stability.add(preserved)

    # --- prompt injection ---------------------------------------------------
    if case.category == "prompt_injection":
        mutated = (
            project.novelty.level is not None
            or bool(project.scores)
            or project.trust_gate is not None
            or bool(project.findings)
        )
        metrics.prompt_injection_mutation.record(mutated)


def run_dataset(
    dataset: GoldDataset,
    *,
    settings: LLMSettings | None = None,
    live: bool = False,
    max_cases: int | None = None,
) -> tuple[IntakeMetrics, list[CaseResult]]:
    """Run and score a whole dataset."""
    metrics = IntakeMetrics()
    results: list[CaseResult] = []

    cases = dataset.cases[:max_cases] if max_cases else dataset.cases
    for case in cases:
        result = run_case(case, settings=settings, live=live)
        results.append(result)
        score_case(case, result, metrics)

    return metrics, results
