"""Evidence extraction eval runner.

Each Gold case is driven through the **real Phase 2C graph** with a scripted
fake provider, so what is measured is the shipped path: content snapshots,
extraction, deterministic verification, numeric fidelity, dedup and coverage,
through a checkpoint.

Scoring is implemented here, independently of the code it scores. The eval does
not ask the verifier whether it verified correctly; it re-derives every judgement
from the produced state and the source content -- re-searching the snapshot for
each accepted excerpt, recomputing traceability, and re-reading whether numbers
appear. That independence is what lets the negative controls prove the eval can
fail: breaking a rule in ``src/research/evidence`` does not break the metric
watching for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.evals.evidence.dataset import (
    EvidenceGoldCase,
    EvidenceGoldDataset,
    build_academic_result,
    gold_run_id,
)
from src.evals.evidence.metrics import EvidenceExtractionMetrics
from src.graph.evidence_nodes import (
    EVIDENCE_DATASET_VERSION_KEY,
    EVIDENCE_EXTRACTION_PROVIDER_KEY,
)
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2c_graph import build_phase2c_evidence_graph
from src.graph.research_nodes import RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import (
    EvaluationGraphState,
    coerce_graph_state,
    new_thread_id,
)
from src.llm.contracts import ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.research.coverage import initial_branch_coverage
from src.research.evidence.dto import EvidenceExtraction
from src.research.inputs import project_state_fingerprint
from src.research.planner import PLANNER_VERSION
from src.research.settings import ResearchSettings
from src.schemas.academic import AcademicSourceType
from src.schemas.evidence_extraction import (
    EvidenceExtractionRun,
    EvidenceScope,
    ExtractedEvidence,
)
from src.schemas.research import (
    ResearchRun,
    ResearchRunStatus,
    ResearchRunVersions,
)

logger = logging.getLogger(__name__)

FAILURE_BUILDERS = {
    "REFUSAL": refusal_result,
    "PROVIDER_ERROR": provider_error_result,
    "INCOMPLETE_OUTPUT": incomplete_result,
    "PARSE_ERROR": parse_error_result,
    "EMPTY_OUTPUT": empty_result,
}

PII_PROBE: tuple[str, ...] = (
    "Zayn Alqahtani",
    "zayn.alqahtani@example.edu",
    "Riyadh Model Secondary School",
)
"""Synthetic student identity planted in canonical state for every case.

Phase 2C reads provider content, never ``ProjectState``, so none of this should
be able to reach a content snapshot, an excerpt, a rejection summary or the
extraction run. Planting it gives the leakage metric a real denominator instead
of a vacuous one, and lets a negative control make it fire.
"""

CLAIM_RELATIONAL_FIELDS = (
    "support_direction",
    "supports_claim",
    "contradicts_claim",
    "claim_id",
    "claim_status",
    "support_strength",
    "strength",
)
"""Fields Phase 2C must not be able to set. Checked structurally, not by type.

Checked against the **extraction run** rather than the whole graph state: the
question is whether Phase 2C created a claim relationship, and canonical state
has long-standing unrelated fields (``gap.strength``) that a whole-state scan
would flag. Claim and score mutation are checked separately, by comparison.
"""


@dataclass
class EvidenceCaseResult:
    case_id: str
    categories: list[str]
    language: str
    extraction: EvidenceExtractionRun | None = None
    project_mutated: bool = False
    claims_mutated: bool = False
    scores_mutated: bool = False
    trust_gate_mutated: bool = False
    state_payload: dict[str, Any] = field(default_factory=dict)
    extraction_payload: str = ""
    snapshot_texts: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _project_with_identity() -> ProjectState:
    """Canonical state carrying synthetic student identity, for the PII probe."""
    from src.schemas.common import Tracked

    project = ProjectState()
    project.problem.statement = Tracked[str].known(
        f"Greenhouse disease detection submitted by {PII_PROBE[0]} "
        f"of {PII_PROBE[2]}, contact {PII_PROBE[1]}"
    )
    return project


def _provider(case: EvidenceGoldCase) -> FakeStructuredModelProvider:
    if case.scripted_failure is not None:
        return FakeStructuredModelProvider(
            result=FAILURE_BUILDERS[case.scripted_failure](ModelTask.EVIDENCE_EXTRACTION)
        )
    if case.scripted is not None:
        # One scripted response per possible snapshot: every content snapshot in
        # a case gets its own call, and a short queue would starve later ones.
        return FakeStructuredModelProvider(
            responses=[EvidenceExtraction.model_validate(case.scripted)] * 32
        )
    return FakeStructuredModelProvider(
        responses=[EvidenceExtraction(evidence=[])] * 32
    )


def _open_run(case: EvidenceGoldCase, project: ProjectState) -> ResearchRun:
    run = ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=PLANNER_VERSION,
            official_extractor_prompt_version=PLANNER_VERSION,
            dataset_version="evidence-gold",
        ),
        status=ResearchRunStatus.RUNNING,
        branch_coverage=initial_branch_coverage(),
    )
    return run.evolve(academic_research=build_academic_result(case))


def run_evidence_case(case: EvidenceGoldCase) -> EvidenceCaseResult:
    """Drive one Gold case through the real Phase 2C graph."""
    outcome = EvidenceCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = _project_with_identity()
        before = project_state_fingerprint(project)
        claims_before = [
            (c.claim_id, c.claim, c.status.value, tuple(c.evidence_ids))
            for c in project.claims
        ]
        scores_before = [s.model_dump() for s in project.scores]
        gate_before = project.trust_gate

        run = _open_run(case, project)
        run_id = uuid4()
        config = thread_config(new_thread_id(run_id))
        config["configurable"][EVIDENCE_EXTRACTION_PROVIDER_KEY] = _provider(case)
        config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings()
        config["configurable"][EVIDENCE_DATASET_VERSION_KEY] = "evidence-gold-v1"

        app = build_phase2c_evidence_graph(build_checkpointer())
        state = coerce_graph_state(
            app.invoke(
                EvaluationGraphState(
                    run_id=run_id,
                    thread_id=config["configurable"]["thread_id"],
                    project=project,
                    research_runs={str(run.research_run_id): run},
                    active_research_run_id=run.research_run_id,
                ),
                config,
            )
        )

        finished = state.active_research_run
        extraction = finished.evidence_extraction if finished else None
        outcome.extraction = extraction
        outcome.project_mutated = project_state_fingerprint(state.project) != before
        outcome.claims_mutated = [
            (c.claim_id, c.claim, c.status.value, tuple(c.evidence_ids))
            for c in state.project.claims
        ] != claims_before
        outcome.scores_mutated = [
            s.model_dump() for s in state.project.scores
        ] != scores_before
        outcome.trust_gate_mutated = state.project.trust_gate != gate_before
        outcome.state_payload = state.model_dump(mode="json")
        outcome.extraction_payload = (
            extraction.model_dump_json() if extraction is not None else ""
        )
        if extraction is not None:
            outcome.snapshot_texts = {
                str(s.content_id): s.text for s in extraction.content_snapshots
            }
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


# ---------------------------------------------------------------------------
# Independent checks
# ---------------------------------------------------------------------------


def _excerpt_is_real(evidence: ExtractedEvidence, texts: dict[str, str]) -> bool:
    """Re-derive the excerpt from the snapshot, without asking the verifier."""
    text = texts.get(str(evidence.content_id))
    if text is None:
        return False
    if not (0 <= evidence.verified_start < evidence.verified_end <= len(text)):
        return False
    return text[evidence.verified_start : evidence.verified_end] == evidence.excerpt


def _numbers_are_real(evidence: ExtractedEvidence) -> bool:
    """Every stated number must appear in the excerpt, checked here from scratch."""
    for observation in evidence.numeric_observations:
        raw = getattr(observation, "raw_text", None)
        if raw is None:  # a forged, unvalidated observation is not real evidence
            return False
        if raw not in evidence.excerpt:
            normalized = " ".join(raw.split())
            if normalized not in " ".join(evidence.excerpt.split()):
                return False
    return True


def _is_traceable(evidence: ExtractedEvidence, extraction: EvidenceExtractionRun) -> bool:
    known = {s.content_id: s for s in extraction.content_snapshots}
    snapshot = known.get(evidence.content_id)
    return bool(
        snapshot is not None
        and snapshot.source_id == evidence.source_id
        and snapshot.content_hash == evidence.content_hash
        and evidence.observations
        and all(o.content_id in known for o in evidence.observations)
        and evidence.research_run_id == extraction.research_run_id
        and evidence.extraction_run_id == extraction.evidence_extraction_run_id
        and evidence.extractor_version
        and evidence.verifier_version
    )


def _scope_matches_content(evidence: ExtractedEvidence) -> bool:
    """Scope must follow content kind, and a non-extractable kind has no scope."""
    kind = getattr(evidence.content_kind, "value", evidence.content_kind)
    expected = {
        "ABSTRACT": EvidenceScope.ABSTRACT_ONLY,
        "PARTIAL_TEXT": EvidenceScope.PARTIAL_TEXT,
        "FULL_TEXT": EvidenceScope.FULL_TEXT,
    }.get(kind)
    return expected is not None and evidence.evidence_scope is expected


def _leaks_identity(text: str) -> bool:
    """Any planted student identity reaching stored evidence is a leak."""
    return any(probe in (text or "") for probe in PII_PROBE)


def _claims_a_relationship(payload: Any) -> bool:
    """Anything anywhere in the state that looks like a claim judgement.

    Structural rather than type-based: a check that trusted the declared types
    would also trust the very thing it is meant to catch.
    """
    if isinstance(payload, dict):
        if any(field in payload for field in CLAIM_RELATIONAL_FIELDS):
            return True
        return any(_claims_a_relationship(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_claims_a_relationship(item) for item in payload)
    return False


def score_evidence_case(
    case: EvidenceGoldCase,
    outcome: EvidenceCaseResult,
    metrics: EvidenceExtractionMetrics,
) -> None:
    """Score one case, recomputing every judgement from the produced state."""
    if not outcome.ok or outcome.extraction is None:
        metrics.cases_errored += 1
        return
    metrics.cases_evaluated += 1
    expected = case.expected
    extraction = outcome.extraction
    evidence = list(extraction.verified_evidence)

    # -- release-blocking -------------------------------------------------
    metrics.project_state_mutation_rate.record(outcome.project_mutated)
    metrics.claim_mutation_rate.record(outcome.claims_mutated)
    metrics.score_mutation_rate.record(outcome.scores_mutated)
    metrics.trust_gate_mutation_rate.record(outcome.trust_gate_mutated)
    metrics.automatic_claim_support_rate.record(
        _claims_a_relationship(extraction.model_dump(mode="json"))
    )

    forbidden = list(expected.forbidden_excerpt_substrings)
    for item in evidence:
        real = _excerpt_is_real(item, outcome.snapshot_texts)
        metrics.hallucinated_excerpt_acceptance_rate.record(not real)
        metrics.span_resolution_accuracy.add(real)
        metrics.invalid_numeric_acceptance_rate.record(not _numbers_are_real(item))
        metrics.numeric_fidelity_accuracy.add(_numbers_are_real(item))
        traceable = _is_traceable(item, extraction)
        metrics.untraceable_evidence_rate.record(not traceable)
        metrics.source_traceability.add(traceable)
        metrics.content_scope_accuracy.add(_scope_matches_content(item))
        metrics.metadata_only_evidence_rate.record(
            getattr(item.content_kind, "value", item.content_kind)
            not in ("ABSTRACT", "PARTIAL_TEXT", "FULL_TEXT")
        )
        metrics.provider_synthesis_evidence_rate.record(
            any(text and text in item.excerpt for text in forbidden)
        )
        metrics.pii_leakage_rate.record(_leaks_identity(item.excerpt))

    for entry in extraction.rejected_candidates:
        metrics.pii_leakage_rate.record(_leaks_identity(entry.safe_summary))
    for snapshot in extraction.content_snapshots:
        metrics.pii_leakage_rate.record(_leaks_identity(snapshot.text))
    metrics.pii_leakage_rate.record(_leaks_identity(outcome.extraction_payload))

    # -- quality ----------------------------------------------------------
    if expected.accepted_excerpts is not None:
        produced = sorted(e.excerpt for e in evidence)
        wanted = sorted(expected.accepted_excerpts)
        metrics.exact_excerpt_acceptance_accuracy.add(produced == wanted)
        if not expected.accepted_excerpts:
            metrics.hallucinated_excerpt_rejection_accuracy.add(not evidence)

    if expected.rejection_reasons:
        got = {r.reason.value for r in extraction.rejected_candidates}
        matched = set(expected.rejection_reasons) <= got
        metrics.rejected_candidate_accuracy.add(matched)
        if {"EXCERPT_NOT_FOUND", "AMBIGUOUS_SPAN"} & set(expected.rejection_reasons):
            metrics.hallucinated_excerpt_rejection_accuracy.add(matched)
        if {"INVALID_NUMERIC_OBSERVATION", "INVALID_UNIT_FIDELITY"} & set(
            expected.rejection_reasons
        ):
            metrics.numeric_fidelity_accuracy.add(matched)

    if expected.ineligible_reasons:
        got_ineligible = {i.reason.value for i in extraction.ineligible_sources}
        metrics.rejected_candidate_accuracy.add(
            set(expected.ineligible_reasons) <= got_ineligible
        )

    if expected.accepted_count is not None:
        metrics.evidence_dedup_accuracy.add(len(evidence) == expected.accepted_count)

    if expected.evidence_types is not None:
        metrics.evidence_type_accuracy.add(
            sorted(e.evidence_type.value for e in evidence)
            == sorted(expected.evidence_types)
        )

    if expected.evidence_scopes is not None:
        metrics.content_scope_accuracy.add(
            sorted(e.evidence_scope.value for e in evidence)
            == sorted(expected.evidence_scopes)
        )

    if expected.content_snapshots is not None:
        metrics.failure_isolation_accuracy.add(
            len(extraction.content_snapshots) == expected.content_snapshots
        )
    if expected.status is not None:
        metrics.failure_isolation_accuracy.add(
            extraction.status.value == expected.status
        )

    if expected.retracted_evidence_count is not None:
        metrics.evidence_dedup_accuracy.add(
            sum(1 for e in evidence if e.is_retracted is True)
            == expected.retracted_evidence_count
        )
    if expected.preprint_evidence_count is not None:
        metrics.evidence_dedup_accuracy.add(
            sum(1 for e in evidence if e.source_type is AcademicSourceType.PREPRINT)
            == expected.preprint_evidence_count
        )
    if expected.numeric_raw_texts is not None:
        produced_numbers = sorted(
            n.raw_text for e in evidence for n in e.numeric_observations
        )
        metrics.numeric_fidelity_accuracy.add(
            produced_numbers == sorted(expected.numeric_raw_texts)
        )


def run_evidence_dataset(
    dataset: EvidenceGoldDataset,
) -> tuple[EvidenceExtractionMetrics, list[EvidenceCaseResult]]:
    metrics = EvidenceExtractionMetrics()
    results: list[EvidenceCaseResult] = []
    for case in dataset.cases:
        outcome = run_evidence_case(case)
        results.append(outcome)
        score_evidence_case(case, outcome, metrics)
    return metrics, results


def score_by_language(
    dataset: EvidenceGoldDataset, results: list[EvidenceCaseResult]
) -> dict[str, EvidenceExtractionMetrics]:
    """Per-language metrics, so an aggregate pass cannot hide a failing subgroup."""
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, EvidenceExtractionMetrics] = {}
    for outcome in results:
        case = by_id.get(outcome.case_id)
        if case is None:
            continue
        score_evidence_case(
            case, outcome, grouped.setdefault(case.language, EvidenceExtractionMetrics())
        )
    return grouped


@dataclass
class EvidenceGateResult:
    passed: bool
    safety_clean: bool
    thresholds_met: bool
    violations: dict[str, int] = field(default_factory=dict)
    cases_errored: int = 0

    def summary(self) -> str:
        return (
            f"{'PASS' if self.passed else 'FAIL'} safety_clean={self.safety_clean} "
            f"thresholds_met={self.thresholds_met} cases_errored={self.cases_errored}"
        )


def evaluate_evidence_gate(metrics: EvidenceExtractionMetrics) -> EvidenceGateResult:
    """Release requires zero violations, perfect required metrics, no errors (§64)."""
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return EvidenceGateResult(
        passed=metrics.safety_clean
        and metrics.thresholds_met
        and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        thresholds_met=metrics.thresholds_met,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )


__all__ = [
    "EvidenceCaseResult",
    "EvidenceGateResult",
    "evaluate_evidence_gate",
    "run_evidence_case",
    "run_evidence_dataset",
    "score_by_language",
    "score_evidence_case",
]
