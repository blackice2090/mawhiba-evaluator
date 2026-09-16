"""Academic retrieval eval runner.

Each Gold case is driven through the **real Phase 2B graph** with the
deterministic fake providers, so what is measured is the shipped path:
eligibility, budget, dispatch, normalization, verification, identity resolution,
merge and coverage, through a checkpoint.

Scoring is implemented here, independently of the code it scores. The eval does
not ask the deduplicator whether it deduplicated correctly; it recomputes
identity conflicts, provenance counts and traceability from the produced state.
That independence is what lets the negative controls prove the eval can fail:
breaking a rule in ``src/research/academic`` does not break the metric watching
for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.evals.academic.dataset import (
    AcademicGoldCase,
    AcademicGoldDataset,
    build_query_plan,
    gold_run_id,
)
from src.evals.academic.metrics import AcademicRetrievalMetrics
from src.graph.academic_nodes import ACADEMIC_PROVIDERS_KEY
from src.graph.persistence import build_checkpointer, thread_config
from src.graph.phase2b_graph import build_phase2b_academic_graph
from src.graph.research_nodes import RESEARCH_PRIVACY_KEY, RESEARCH_SETTINGS_KEY
from src.graph.state import ProjectState
from src.graph.workflow_state import EvaluationGraphState, coerce_graph_state, new_thread_id
from src.research import privacy as research_privacy
from src.research.academic.fakes import FAKE_PROVIDER_CLASSES, ScriptedSearch
from src.research.academic.identifiers import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_pmid,
    normalize_semantic_scholar_id,
    normalize_url,
)
from src.research.coverage import initial_branch_coverage
from src.research.inputs import project_state_fingerprint
from src.research.settings import ResearchSettings
from src.schemas.academic import (
    AcademicErrorKind,
    AcademicProvider,
    AcademicRetrievalResult,
    LogicalAcademicSource,
)
from src.schemas.research import (
    ResearchRun,
    ResearchRunStatus,
    ResearchRunVersions,
)

logger = logging.getLogger(__name__)

EVAL_PLANNER_VERSION = "ACADEMIC-GOLD-PLAN-V1"

_IDENTIFIER_NORMALIZERS = {
    "DOI": normalize_doi,
    "PMID": normalize_pmid,
    "OPENALEX_ID": normalize_openalex_id,
    "SEMANTIC_SCHOLAR_ID": normalize_semantic_scholar_id,
    "ARXIV_ID": normalize_arxiv_id,
    "CANONICAL_URL": normalize_url,
}


@dataclass
class AcademicCaseResult:
    case_id: str
    categories: list[str]
    language: str
    result: AcademicRetrievalResult | None = None
    dispatched_queries: list[str] = field(default_factory=list)
    project_mutated: bool = False
    claims_mutated: bool = False
    state_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _scripts(case: AcademicGoldCase) -> dict[AcademicProvider, dict[str, ScriptedSearch]]:
    """One scripted response per provider, applied to every query of the case."""
    scripts: dict[AcademicProvider, dict[str, ScriptedSearch]] = {}
    for name, script in case.providers.items():
        provider = AcademicProvider(name)
        scripted = ScriptedSearch(
            records=list(script.records),
            payload=script.payload,
            failure=AcademicErrorKind(script.failure) if script.failure else None,
            leading_failures=tuple(
                AcademicErrorKind(kind) for kind in script.leading_failures
            ),
            http_status=script.http_status,
            retry_after_seconds=script.retry_after_seconds,
        )
        scripts[provider] = {planned.query: scripted for planned in case.queries}
    return scripts


def _providers(case: AcademicGoldCase) -> list[Any]:
    scripts = _scripts(case)
    return [
        cls(scripts.get(provider, {}))
        for provider, cls in FAKE_PROVIDER_CLASSES.items()
        if provider in case.settings().enabled_providers
    ]


def _open_run(case: AcademicGoldCase, project: ProjectState) -> ResearchRun:
    plan = build_query_plan(case)
    return ResearchRun(
        research_run_id=gold_run_id(case),
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        planner_version=EVAL_PLANNER_VERSION,
        versions=ResearchRunVersions(
            planner_prompt_version=EVAL_PLANNER_VERSION,
            official_extractor_prompt_version=EVAL_PLANNER_VERSION,
            dataset_version="academic-gold",
        ),
        status=ResearchRunStatus.RUNNING,
        query_plan=plan,
        branch_coverage=initial_branch_coverage(),
    )


def run_academic_case(case: AcademicGoldCase) -> AcademicCaseResult:
    """Drive one Gold case through the real Phase 2B graph."""
    outcome = AcademicCaseResult(case.case_id, list(case.categories), case.language)
    try:
        project = ProjectState()
        before = project_state_fingerprint(project)
        claims_before = [
            (c.claim_id, c.claim, c.status.value) for c in project.claims
        ]
        run = _open_run(case, project)
        providers = _providers(case)

        run_id = uuid4()
        config = thread_config(new_thread_id(run_id))
        config["configurable"][RESEARCH_SETTINGS_KEY] = ResearchSettings(
            academic=case.settings()
        )
        config["configurable"][RESEARCH_PRIVACY_KEY] = case.privacy.context()
        config["configurable"][ACADEMIC_PROVIDERS_KEY] = providers

        app = build_phase2b_academic_graph(build_checkpointer())
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
        outcome.result = finished.academic_research if finished else None
        outcome.dispatched_queries = [
            text for provider in providers for text, _ in provider.fetch_calls
        ]
        outcome.project_mutated = project_state_fingerprint(state.project) != before
        outcome.claims_mutated = [
            (c.claim_id, c.claim, c.status.value) for c in state.project.claims
        ] != claims_before
        outcome.state_payload = state.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        outcome.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, outcome.error)
    return outcome


# ---------------------------------------------------------------------------
# Independent checks
# ---------------------------------------------------------------------------


def _pii_leaks(text: str, case: AcademicGoldCase) -> bool:
    if research_privacy.detect_pii(text, case.privacy.context()):
        return True
    folded = research_privacy.normalize_unicode(text).casefold()
    return any(v.casefold() in folded for v in case.privacy.values if v.strip())


def _contains_evidence(payload: Any) -> bool:
    """True if anything anywhere in the state looks like an evidence record.

    Structural, not type-based: a check that trusted the declared types would
    also trust the very thing it is meant to catch.
    """
    if isinstance(payload, dict):
        if "evidence_id" in payload or "evidence_type" in payload:
            return True
        return any(_contains_evidence(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_evidence(item) for item in payload)
    return False


def _source_identity_is_consistent(source: LogicalAcademicSource) -> bool:
    """No two observations of one logical source may state different identifiers."""
    for kind in ("doi", "pmid", "openalex_id", "semantic_scholar_id", "arxiv_id"):
        stated = {
            getattr(o.identifiers, kind)
            for o in source.observations
            if getattr(o.identifiers, kind)
        }
        if len(stated) > 1:
            return False
    return True


def _is_traceable(source: LogicalAcademicSource, result: AcademicRetrievalResult) -> bool:
    dispatched = {q.query_id for q in result.selected_queries}
    return bool(
        source.observations
        and all(o.query_id in dispatched for o in source.observations)
        and all(o.research_run_id == result.research_run_id for o in source.observations)
        and source.fingerprint.identifier
    )


def _expected_source(
    result: AcademicRetrievalResult, kind: str, identifier: str
) -> LogicalAcademicSource | None:
    normalizer = _IDENTIFIER_NORMALIZERS[kind]
    wanted = normalizer(identifier).value
    return next(
        (
            s
            for s in result.logical_sources
            if s.fingerprint.identifier_kind.value == kind
            and s.fingerprint.identifier == wanted
        ),
        None,
    )


def score_academic_case(
    case: AcademicGoldCase,
    outcome: AcademicCaseResult,
    metrics: AcademicRetrievalMetrics,
) -> None:
    """Score one case. Every check is recomputed here from the produced state."""
    if not outcome.ok or outcome.result is None:
        metrics.cases_errored += 1
        return
    metrics.cases_evaluated += 1
    expected = case.expected
    result = outcome.result

    # -- release-blocking -------------------------------------------------
    metrics.project_state_mutation_rate.record(outcome.project_mutated)
    metrics.claim_mutation_violation_rate.record(outcome.claims_mutated)
    metrics.evidence_creation_violation_rate.record(
        _contains_evidence(outcome.state_payload)
    )

    for text in outcome.dispatched_queries:
        metrics.pii_leakage_rate.record(_pii_leaks(text, case))
    for excluded in result.excluded_queries:
        metrics.pii_leakage_rate.record(_pii_leaks(excluded.query, case))
    for rejected in result.rejected_candidates:
        metrics.pii_leakage_rate.record(_pii_leaks(rejected.safe_summary, case))

    observed = 0
    for source in result.logical_sources:
        metrics.untraceable_verified_source.record(not _is_traceable(source, result))
        metrics.invalid_strong_identifier_merge.record(
            not _source_identity_is_consistent(source)
        )
        metrics.source_traceability.add(_is_traceable(source, result))
        observed += len(source.observations)

    accepted = sum(1 for d in result.decisions if d.accepted)
    metrics.provider_provenance_loss.record(observed != accepted)

    # -- quality ----------------------------------------------------------
    metrics.cross_provider_dedup_accuracy.add(
        len(result.logical_sources) == expected.logical_source_count
    )
    metrics.provider_failure_isolation_accuracy.add(
        result.outcome.value == expected.branch_outcome
        and all(
            sorted(r.status.value for r in result.results_for(AcademicProvider(name)))
            == sorted(statuses)
            for name, statuses in expected.provider_statuses.items()
        )
    )

    if expected.rejection_reasons:
        got = {r.reason.value for r in result.rejected_candidates}
        metrics.rejected_candidate_accuracy.add(set(expected.rejection_reasons) <= got)
    if expected.excluded_reasons:
        got_excluded = {e.reason.value for e in result.excluded_queries}
        metrics.rejected_candidate_accuracy.add(set(expected.excluded_reasons) <= got_excluded)

    budget_ok = True
    if expected.queries_executed is not None:
        budget_ok &= result.budget.queries_executed == expected.queries_executed
    if expected.candidate_count is not None:
        budget_ok &= len(result.candidates) == expected.candidate_count
    if expected.budget_truncated is not None:
        budget_ok &= result.budget.truncated == expected.budget_truncated
    if (
        expected.queries_executed is not None
        or expected.candidate_count is not None
        or expected.budget_truncated is not None
    ):
        metrics.budget_enforcement_accuracy.add(budget_ok)

    for wanted in expected.sources:
        source = _expected_source(result, wanted.identifier_kind, wanted.identifier)
        metrics.identifier_normalization_accuracy.add(source is not None)
        if source is None:
            metrics.provider_observation_preservation.add(False)
            metrics.metadata_merge_accuracy.add(False)
            continue

        metrics.provider_observation_preservation.add(
            sorted(p.value for p in source.providers) == sorted(wanted.providers)
            and {
                AcademicProvider(p).value: c
                for p, c in wanted.citation_counts.items()
            }
            == {o.provider.value: o.count for o in source.citation_observations}
        )

        merge_ok = source.publication_year == wanted.publication_year
        if wanted.title is not None:
            merge_ok &= source.title == wanted.title
        if wanted.source_type is not None:
            merge_ok &= source.source_type.value == wanted.source_type
        if wanted.is_retracted is not None or "is_retracted" in wanted.conflict_fields:
            merge_ok &= source.is_retracted == wanted.is_retracted
        if wanted.is_preprint is not None:
            merge_ok &= source.is_preprint == wanted.is_preprint
        merge_ok &= sorted(c.field_name for c in source.conflicts) == sorted(
            wanted.conflict_fields
        )
        metrics.metadata_merge_accuracy.add(merge_ok)


def run_academic_dataset(
    dataset: AcademicGoldDataset,
) -> tuple[AcademicRetrievalMetrics, list[AcademicCaseResult]]:
    metrics = AcademicRetrievalMetrics()
    results: list[AcademicCaseResult] = []
    for case in dataset.cases:
        outcome = run_academic_case(case)
        results.append(outcome)
        score_academic_case(case, outcome, metrics)
    return metrics, results


def score_by_language(
    dataset: AcademicGoldDataset, results: list[AcademicCaseResult]
) -> dict[str, AcademicRetrievalMetrics]:
    """Per-language metrics.

    An aggregate pass can hide a failing subgroup, so Arabic and mixed-language
    cases are held to the same release-blocking targets, measured separately.
    """
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, AcademicRetrievalMetrics] = {}
    for outcome in results:
        case = by_id.get(outcome.case_id)
        if case is None:
            continue
        score_academic_case(
            case, outcome, grouped.setdefault(case.language, AcademicRetrievalMetrics())
        )
    return grouped


@dataclass
class AcademicGateResult:
    passed: bool
    safety_clean: bool
    violations: dict[str, int] = field(default_factory=dict)
    cases_errored: int = 0

    def summary(self) -> str:
        return (
            f"{'PASS' if self.passed else 'FAIL'} safety_clean={self.safety_clean} "
            f"cases_errored={self.cases_errored}"
        )


def evaluate_academic_gate(metrics: AcademicRetrievalMetrics) -> AcademicGateResult:
    """Pass only with zero release-blocking violations and no errored case."""
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return AcademicGateResult(
        passed=metrics.safety_clean and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )


__all__ = [
    "AcademicCaseResult",
    "AcademicGateResult",
    "evaluate_academic_gate",
    "run_academic_case",
    "run_academic_dataset",
    "score_academic_case",
    "score_by_language",
]
