"""Research planning eval runner.

Drives each Gold case through the real planning path (input projection ->
planner call -> deterministic verification) with a scripted fake provider, then
scores the result with checks that are implemented here independently of the
verifier. The independence is what lets negative controls prove the eval can fail:
disabling a verifier rule does not disable the metric that watches for it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from src.config.settings import LLMSettings
from src.evals.research.dataset import ResearchGoldCase, ResearchGoldDataset, build_project
from src.evals.research.metrics import ResearchPlanningMetrics
from src.graph.state import ProjectState
from src.llm.contracts import ModelTask
from src.llm.fake_provider import (
    FakeStructuredModelProvider,
    empty_result,
    incomplete_result,
    parse_error_result,
    provider_error_result,
    refusal_result,
)
from src.research import inputs as research_inputs
from src.research import planner as research_planner
from src.research import privacy as research_privacy
from src.research.vocabulary import ALL_QUERY_CONNECTOR_TOKENS
from src.schemas.research import CandidateQueryPlan, QueryPlanLimits, ResearchQuery, VerifiedQueryPlan

logger = logging.getLogger(__name__)

FAILURE_BUILDERS = {
    "REFUSAL": refusal_result,
    "PROVIDER_ERROR": provider_error_result,
    "INCOMPLETE_OUTPUT": incomplete_result,
    "PARSE_ERROR": parse_error_result,
    "EMPTY_OUTPUT": empty_result,
}

EVAL_LLM_SETTINGS = LLMSettings(escalation_enabled=False, max_retries=0)

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_EDGE = re.compile(r"^[^\w]+|[^\w]+$")


@dataclass
class ResearchCaseResult:
    case_id: str
    categories: list[str]
    language: str
    project: ProjectState | None = None
    plan: VerifiedQueryPlan | None = None
    planner_called: bool = False
    planner_input: str = ""
    mutated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _provider(case: ResearchGoldCase) -> FakeStructuredModelProvider:
    if case.scripted_failure is not None:
        return FakeStructuredModelProvider(
            result=FAILURE_BUILDERS[case.scripted_failure](ModelTask.RESEARCH_QUERY_PLANNING)
        )
    if case.scripted_plan is not None:
        return FakeStructuredModelProvider(
            responses=[CandidateQueryPlan.model_validate(case.scripted_plan)]
        )
    return FakeStructuredModelProvider()


def run_research_case(
    case: ResearchGoldCase, *, limits: QueryPlanLimits | None = None
) -> ResearchCaseResult:
    result = ResearchCaseResult(case.case_id, case.categories, case.language)
    try:
        project = build_project(case)
        result.project = project
        before = research_inputs.project_state_fingerprint(project)
        provider = _provider(case)
        outcome = research_planner.plan_research_queries(
            project,
            provider,
            research_run_id=uuid5(NAMESPACE_URL, f"research-gold:{case.case_id}:run"),
            llm_settings=EVAL_LLM_SETTINGS,
            limits=limits or QueryPlanLimits(),
            privacy=case.privacy.context(),
        )
        result.mutated = research_inputs.project_state_fingerprint(project) != before
        result.plan = outcome.plan
        result.planner_called = provider.call_count > 0
        result.planner_input = outcome.planner_input if result.planner_called else ""
    except Exception as exc:  # noqa: BLE001 -- an eval must never abort the run
        result.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        logger.warning("case %s failed: %s", case.case_id, result.error)
    return result


# ---------------------------------------------------------------------------
# Independent checks
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(research_privacy.normalize_unicode(text).casefold()))


def _contained(term: str, text: str) -> bool:
    wanted = _tokens(term)
    return bool(wanted) and wanted <= _tokens(text)


def _reference_valid(project: ProjectState, path: str) -> bool:
    return bool(research_inputs.resolve_research_field(project, path))


def query_is_traceable(project: ProjectState, query: ResearchQuery) -> bool:
    """Every source term sits in its trusted field and in the query, and every
    query word is a source-term, expansion-term or connector word."""
    if not query.source_terms or not query.query:
        return False
    allowed = set(ALL_QUERY_CONNECTOR_TOKENS)
    for source in query.source_terms:
        values = research_inputs.resolve_research_field(project, source.field_path) or []
        if not any(_contained(source.term, value) for value in values):
            return False
        if not _contained(source.term, query.query):
            return False
        allowed |= _tokens(source.term)
    for expansion in query.expansion_terms:
        allowed |= _tokens(expansion)
    return _tokens(query.query) <= allowed


def _pii_leaks(text: str, case: ResearchGoldCase) -> bool:
    if research_privacy.detect_pii(text, case.privacy.context()):
        return True
    folded = research_privacy.normalize_unicode(text).casefold()
    return any(v.casefold() in folded for v in case.privacy.values if v.strip())


def _dedup_key(query: ResearchQuery) -> tuple[str, str]:
    folded = " ".join(research_privacy.normalize_unicode(query.query).casefold().split())
    folded = re.sub(r"([^\w\s])\1+", r"\1", folded)
    return (str(query.branch), _EDGE.sub("", folded))


def score_research_case(
    case: ResearchGoldCase, result: ResearchCaseResult, metrics: ResearchPlanningMetrics
) -> None:
    if not result.ok or result.project is None:
        metrics.cases_errored += 1
        return
    metrics.cases_evaluated += 1
    expected = case.expected
    project = result.project
    plan = result.plan
    accepted = plan.accepted_queries if plan else []

    metrics.project_state_mutation_rate.record(result.mutated)
    metrics.planner_invocation_accuracy.add(result.planner_called == expected.planner_called)

    if result.planner_input:
        metrics.pii_leakage_rate.record(_pii_leaks(result.planner_input, case))

    seen: set[tuple[str, str]] = set()
    for query in accepted:
        traceable = query_is_traceable(project, query)
        metrics.query_source_traceability.add(traceable)
        metrics.untraceable_accepted_queries.record(not traceable)
        texts = [query.query, *(t.term for t in query.source_terms), *query.expansion_terms]
        metrics.pii_leakage_rate.record(any(_pii_leaks(text, case) for text in texts))
        for reference in query.derived_from:
            metrics.invalid_field_reference_rate.record(
                not _reference_valid(project, reference.field_path)
            )
        key = _dedup_key(query)
        metrics.duplicate_query_rate.record(key in seen)
        seen.add(key)

    if expected.accepted_queries is not None:
        metrics.accepted_query_set_accuracy.add(
            sorted(q.query for q in accepted) == sorted(expected.accepted_queries)
        )

    for query_text, reasons in expected.rejected.items():
        match = next(
            (q for q in (plan.rejected_queries if plan else []) if q.query == query_text), None
        )
        got = {r.value for r in match.rejection_reasons} if match else set()
        metrics.rejection_reason_accuracy.add(match is not None and set(reasons) <= got)

    purposes = {q.purpose.value for q in accepted if q.purpose is not None}
    for family in expected.required_families:
        metrics.required_query_family_coverage.add(family in purposes)

    if expected.anti_confirmation_satisfied is not None:
        got_anti = plan.anti_confirmation_satisfied if plan else False
        metrics.anti_confirmation_accuracy.add(got_anti == expected.anti_confirmation_satisfied)

    if expected.duplicates_removed is not None:
        got_dups = plan.duplicates_removed if plan else 0
        metrics.duplicate_removal_accuracy.add(got_dups == expected.duplicates_removed)

    if expected.plan_issues is not None:
        got_issues = sorted(i.value for i in plan.issues) if plan else []
        metrics.plan_issue_accuracy.add(got_issues == sorted(expected.plan_issues))


def run_research_dataset(
    dataset: ResearchGoldDataset, *, limits: QueryPlanLimits | None = None
) -> tuple[ResearchPlanningMetrics, list[ResearchCaseResult]]:
    metrics = ResearchPlanningMetrics()
    results: list[ResearchCaseResult] = []
    for case in dataset.cases:
        result = run_research_case(case, limits=limits)
        results.append(result)
        score_research_case(case, result, metrics)
    return metrics, results


def score_by_language(
    dataset: ResearchGoldDataset, results: list[ResearchCaseResult]
) -> dict[str, ResearchPlanningMetrics]:
    """Per-language metrics.

    An aggregate pass can hide a language that fails: Arabic and mixed-language
    planning must meet the same release-blocking targets as English, measured
    separately.
    """
    by_id = {case.case_id: case for case in dataset.cases}
    grouped: dict[str, ResearchPlanningMetrics] = {}
    for result in results:
        case = by_id.get(result.case_id)
        if case is None:
            continue
        score_research_case(case, result, grouped.setdefault(case.language, ResearchPlanningMetrics()))
    return grouped


@dataclass
class ResearchGateResult:
    passed: bool
    safety_clean: bool
    violations: dict[str, int] = field(default_factory=dict)
    cases_errored: int = 0

    def summary(self) -> str:
        return (
            f"{'PASS' if self.passed else 'FAIL'} safety_clean={self.safety_clean} "
            f"cases_errored={self.cases_errored}"
        )


def evaluate_research_gate(metrics: ResearchPlanningMetrics) -> ResearchGateResult:
    """Pass only with zero release-blocking violations and no errored case."""
    violations = {name: c.violations for name, c in metrics.safety_metrics.items()}
    return ResearchGateResult(
        passed=metrics.safety_clean and metrics.cases_errored == 0,
        safety_clean=metrics.safety_clean,
        violations=violations,
        cases_errored=metrics.cases_errored,
    )
