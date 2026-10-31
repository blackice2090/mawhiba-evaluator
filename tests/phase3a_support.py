"""Shared Phase 3A production-test world.

The upstream state is built by the real Phase 2E-2J graphs (``build_phase2i_world``
and ``run_phase2j``); nothing upstream is hand-built. ``ScriptedMethodologyModel``
plays the *untrusted* model for the five Phase 3A calls from a script, so a test
can make it behave well, fabricate an excerpt, invent a requirement, follow an
injected instruction or leak the system prompt. It cannot produce a posture:
there is no field a script could put one in.

This is a test helper, not a Gold fixture: no expectation here is a graded case.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.config.settings import LLMSettings
from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke
from src.evals.research_engineering_gap.fixtures import (
    CLAIMS, ND_SCRIPT, PATENT, extract_with, limitation_with, script,
)
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.graph.methodology_nodes import METHODOLOGY_MODEL_PROVIDER_KEY
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.persistence import build_checkpointer
from src.graph.phase3a_graph import build_phase3a_methodology_graph
from src.graph.workflow_state import EvaluationGraphState
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask, ModelUsage
from src.llm.fake_provider import FakeStructuredModelProvider
from src.llm.prompts import (
    METHODOLOGY_EXCERPTS_MARKER,
    METHODOLOGY_ITEMS_MARKER,
    METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1,
)
from src.research.methodology.dto import (
    ApplicabilityJudgmentDTO,
    ApplicabilityResponse,
    BaselineJudgmentDTO,
    ConditionJudgmentDTO,
    CoverageJudgmentDTO,
    EvidenceExtractionResponse,
    ExcerptDTO,
    MetricBaselineResponse,
    MetricJudgmentDTO,
    OverlayAssessmentResponse,
    OverlayJudgmentDTO,
    RequirementEvidenceDTO,
    SubmissionSpanDTO,
    TargetLinkageResponse,
)
from src.research.settings import ResearchSettings
from src.schemas.common import ProjectType, TechnicalDomain
from src.schemas.methodology_review import MethodologyReviewBounds, RequirementKind
from src.schemas.submission import StudentSubmissionArtifact

CLAIM_TEXT = CLAIMS[0]["claim"]

S_OBJECTIVE = "The design objective is to irrigate crops using soil moisture sensors and weather forecasts."
S_REQUIREMENTS = "Requirements: the controller must keep soil moisture inside a target range."
S_ARCHITECTURE = "The architecture has a sensor module, a decision module and a valve driver."
S_VERIFICATION = "Verification plan: each module is bench tested before integration."
S_VALIDATION = "Validation plan: a 30 day field trial on three plots compares moisture accuracy against a timer controller."
S_MEASUREMENT = "Measurement plan: moisture accuracy and water use are logged every hour."
S_ACCEPTANCE = "Acceptance criteria: moisture accuracy must exceed the timer controller."
S_CONDITION = "Low light conditions are covered by shaded plots."
ENGINEERING_TEXT = " ".join([S_OBJECTIVE, S_REQUIREMENTS, S_ARCHITECTURE, S_VERIFICATION, S_VALIDATION,
                              S_MEASUREMENT, S_ACCEPTANCE, S_CONDITION])

ENGINEERING_REQUIRED = {
    "DESIGN_OBJECTIVE": S_OBJECTIVE, "REQUIREMENTS": S_REQUIREMENTS, "ARCHITECTURE_SUBSYSTEM_PLAN": S_ARCHITECTURE,
    "VERIFICATION_PLAN": S_VERIFICATION, "MEASUREMENT_PLAN": S_MEASUREMENT, "ACCEPTANCE_CRITERIA": S_ACCEPTANCE,
}
ENGINEERING_CONDITIONALS = (
    "BASELINE_OR_ALTERNATIVE_DESIGN", "RELIABILITY_PLAN", "SAFETY_PLAN", "SECURITY_PRIVACY_VALIDATION",
    "PERFORMANCE_BENCHMARK_PLAN", "SCALABILITY_VALIDATION",
)


def ok(task: ModelTask, parsed: Any) -> ModelCallResult:
    return ModelCallResult(status=ModelCallStatus.SUCCESS, parsed=parsed, model="fake-model", provider="fake",
                           task=task, request_id="fake-request",
                           usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0))


def failure(task: ModelTask, kind: str) -> ModelCallResult:
    if kind == "refusal_leak":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake", task=task,
                               refusal=prompt_line())
    if kind == "error_leak":
        return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, model="fake-model", provider="fake",
                               task=task, error=prompt_line())
    if kind == "refusal":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake", task=task,
                               refusal="I cannot help with that request.")
    return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, model="fake-model", provider="fake", task=task,
                           error="APIConnectionError: connection reset")


def prompt_line() -> str:
    return next(ln.strip() for ln in METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1.splitlines() if len(ln.strip()) >= 40)


def span(spec: Any) -> SubmissionSpanDTO | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        return SubmissionSpanDTO(excerpt=spec)
    return SubmissionSpanDTO(excerpt=spec["excerpt"], start=spec.get("start"), end=spec.get("end"),
                             occurrence=spec.get("occurrence"), rationale=spec.get("rationale"))


_E_LINE = re.compile(r"^\[(E\d+)\] \(([A-Z_]+) / ([A-Z_]+)\) (.*)$")
_K_LINE = re.compile(r"^\[(K\d+)\] condition of (G\d+) ")


@dataclass
class ScriptedMethodologyModel:
    """Answers the five Phase 3A prompts from a script. Records every call."""

    script: dict[str, Any]
    calls: list[tuple[ModelTask, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.script = copy.deepcopy(self.script)

    def provider(self) -> FakeStructuredModelProvider:
        return FakeStructuredModelProvider(factory=self)

    def count(self, task: ModelTask) -> int:
        return sum(1 for t, _ in self.calls if t is task)

    def __call__(self, task: ModelTask, user_input: str) -> ModelCallResult:
        self.calls.append((task, user_input))
        raw = self.script.get("raw", {}).get(task.value)
        if raw is not None:
            return raw if isinstance(raw, ModelCallResult) else ok(task, raw)
        handler = {
            ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT: self._overlay,
            ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION: self._evidence,
            ModelTask.METHODOLOGY_APPLICABILITY: self._applicability,
            ModelTask.METHODOLOGY_METRIC_BASELINE: self._metric,
            ModelTask.METHODOLOGY_TARGET_LINKAGE: self._link,
        }.get(task)
        return handler(user_input) if handler else failure(task, "provider_error")

    # -- helpers -------------------------------------------------------------------------

    def _spec(self, key: str, task: ModelTask):
        spec = self.script.get(key)
        if spec is None or isinstance(spec, str):
            return None, failure(task, spec or "provider_error")
        return spec, None

    # -- calls ---------------------------------------------------------------------------

    def _overlay(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT
        spec, bad = self._spec("overlay", task) if "overlay" in self.script else ({}, None)
        if bad:
            return bad
        if not self.script.get("overlay_omit"):  # a well-behaved model answers every overlay it is asked about
            asked = re.findall(r"^OVERLAY: ([A-Z_]+)$", user_input, flags=re.M)
            claims = re.findall(r"^\[(C\d+)\] ", user_input, flags=re.M)
            hyps = re.findall(r"^\[(H\d+)\] ", user_input, flags=re.M)
            spec = {**{name: {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": claims, "hypotheses": hyps}
                       for name in asked}, **spec}
        return ok(task, OverlayAssessmentResponse(overlays=[
            OverlayJudgmentDTO(
                overlay=name, materiality=s["materiality"], claims=s.get("claims", []),
                hypotheses=s.get("hypotheses", []), excerpts=[span(e) for e in s.get("excerpts", [])],
                owner_track=s.get("owner_track"), served_tracks=s.get("served_tracks", []))
            for name, s in spec.items()]))

    def _evidence(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION
        spec, bad = self._spec("evidence", task)
        if bad:
            return bad
        reqs = []
        for kind, s in spec.items():
            reqs.append(RequirementEvidenceDTO(
                kind=kind, documentation=s.get("documentation", "EXPLICITLY_DOCUMENTED"),
                adequacy=s.get("adequacy", "ADEQUATELY_SPECIFIED_FOR_REVIEW"),
                excerpts=[ExcerptDTO(**{**(span(e).model_dump()), "statement_mode": s.get("mode", "PLANNED")})
                          for e in s["excerpts"]]))
        return ok(task, EvidenceExtractionResponse(requirements=reqs))

    def _applicability(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_APPLICABILITY
        spec, bad = self._spec("applicability", task)
        if bad:
            return bad
        return ok(task, ApplicabilityResponse(judgments=[
            ApplicabilityJudgmentDTO(kind=kind, fired_triggers=s.get("fired", []), excerpt=span(s.get("excerpt")))
            for kind, s in spec.items()]))

    def _metric(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_METRIC_BASELINE
        spec, bad = self._spec("metric", task)
        if bad:
            return bad
        baselines = self.script.get("baseline", {})
        return ok(task, MetricBaselineResponse(
            metrics=[MetricJudgmentDTO(target=t, status=s["status"], outcome=span(s.get("outcome")),
                                       metric_excerpt=span(s.get("metric"))) for t, s in spec.items()],
            baselines=[BaselineJudgmentDTO(
                target=t, baseline=span(s.get("baseline")), relevance=s.get("relevance", "RELEVANCE_UNRESOLVED"),
                context=s.get("context", []), rationale_excerpt=span(s.get("rationale")))
                for t, s in baselines.items()]))

    def _link(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_TARGET_LINKAGE
        spec, bad = self._spec("link", task)
        if bad:
            return bad
        excerpts = _excerpt_labels(user_input)

        def labels(snippets: list[str]) -> list[str]:
            out = []
            for snip in snippets:
                out.append(next((label for label, text in excerpts.items() if snip in text), snip))
            return out

        coverage = [CoverageJudgmentDTO(target=t, track=track, relation=s["relation"], excerpts=labels(s.get("excerpts", [])),
                                    rationale=s.get("rationale"))
                    for t, tracks in spec.items() for track, s in tracks.items()]
        conds = self.script.get("conditions", {})
        condition_labels = _condition_labels(user_input)
        judgments = [ConditionJudgmentDTO(condition=condition_labels.get(k, k), status=s["status"],
                                          excerpts=labels(s.get("excerpts", [])))
                     for k, s in conds.items()]
        return ok(task, TargetLinkageResponse(coverage=coverage, conditions=judgments))


def _excerpt_labels(user_input: str) -> dict[str, str]:
    block = user_input.split(METHODOLOGY_EXCERPTS_MARKER, 1)[-1].split(METHODOLOGY_ITEMS_MARKER, 1)[0]
    return {m.group(1): m.group(4) for line in block.split("\n") if (m := _E_LINE.match(line))}


def _condition_labels(user_input: str) -> dict[str, str]:
    """script key 'G1:1' -> the K label of the 1st condition of G1."""
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for line in user_input.split(METHODOLOGY_ITEMS_MARKER, 1)[-1].split("\n"):
        if m := _K_LINE.match(line):
            seen[m.group(2)] = seen.get(m.group(2), 0) + 1
            out[f"{m.group(2)}:{seen[m.group(2)]}"] = m.group(1)
    return out


# -- scripts -----------------------------------------------------------------------------------------


def well_engineering_script() -> dict[str, Any]:
    """A fully, honestly documented engineering project: every REQUIRED requirement documented and
    adequate, every conditional requirement resolved, one aligned metric, direct coverage."""
    evidence = {k: {"excerpts": [text]} for k, text in ENGINEERING_REQUIRED.items()}
    evidence["VALIDATION_PLAN"] = {"excerpts": [S_VALIDATION, S_CONDITION]}
    return {
        "evidence": evidence,
        "applicability": {k: {"fired": [], "excerpt": S_OBJECTIVE} for k in ENGINEERING_CONDITIONALS},
        "metric": {
            "T1": {"status": "ALIGNED_WITHIN_BOUND_INPUT", "outcome": S_MEASUREMENT,
                   "metric": "moisture accuracy and water use"},
            "G1": {"status": "ALIGNED_WITHIN_BOUND_INPUT", "outcome": S_MEASUREMENT},
        },
        "link": {"T1": {"ENGINEERING": {"relation": "DIRECTLY_TESTS_TARGET", "excerpts": [S_VALIDATION]}},
                 "G1": {"ENGINEERING": {"relation": "DIRECTLY_TESTS_TARGET", "excerpts": [S_VALIDATION]}}},
        "conditions": {"G1:1": {"status": "ADDRESSED_IN_DESIGN", "excerpts": [S_CONDITION]}},
    }


def edited(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out = copy.deepcopy(base)
    out.update(copy.deepcopy(changes))
    return out


# -- worlds ------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _phase2i_world() -> EvaluationGraphState:
    return build_phase2i_world("PJ-3A", CLAIMS, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def with_project(state: EvaluationGraphState, project_type: ProjectType,
                 domains: tuple[TechnicalDomain, ...] = ()) -> EvaluationGraphState:
    identity = state.project.identity.model_copy(update={"project_type": project_type, "domain": list(domains)})
    return state.model_copy(update={"project": state.project.model_copy(update={"identity": identity})})


def _gap_script(variant: str) -> dict[str, Any]:
    """Phase 2J extraction variants: which validation requirement the bound hypothesis carries."""
    if variant == "default":  # metric + one material condition, no baseline
        return script()
    if variant == "baseline":  # metric + a baseline + one material condition
        return script(extract_with(validation={"metric_source": "L1", "metric": "accuracy",
                                                "baseline_source": "C1", "baseline": "94%"}))
    if variant == "no_condition":  # metric, no material condition (empty condition_ids)
        return script(extract_with(limitations=[limitation_with(conditions=[])]))
    if variant == "no_requirement":  # a hypothesis with limitations but no validation requirement
        return script(extract_with(validation=None))
    raise ValueError(variant)


@lru_cache(maxsize=32)
def _phase2j_world(project_type: ProjectType, domains: tuple[TechnicalDomain, ...], variant: str
                   ) -> EvaluationGraphState:
    state = with_project(_phase2i_world(), project_type, domains)
    return run_phase2j(state, ScriptedGapModel({"C-001": CLAIM_TEXT}, _gap_script(variant)).provider())


def world(project_type: ProjectType = ProjectType.ENGINEERING_PROJECT, text: str | None = ENGINEERING_TEXT,
          domains: tuple[TechnicalDomain, ...] = (), gap_variant: str = "default") -> EvaluationGraphState:
    """A state carrying a finished Phase 2J run, the claims, and a verbatim submission."""
    state = _phase2j_world(project_type, domains, gap_variant)
    submission = None if text is None else StudentSubmissionArtifact(
        artifact_id=uuid5(NAMESPACE_URL, f"phase3a-test-submission:{text}"),
        project_id=state.project.project_id, original_text=text, language="en")
    return state.model_copy(update={"submission": submission})


def run_phase3a(
    state: EvaluationGraphState, provider: Any, *, bounds: MethodologyReviewBounds | None = None,
    interrupt_before: str | None = None, checkpointer: Any = None,
) -> EvaluationGraphState:
    configurable: dict[str, Any] = {"settings": ResearchSettings(methodology=bounds or MethodologyReviewBounds())}
    if provider is not None:
        configurable[METHODOLOGY_MODEL_PROVIDER_KEY] = provider
        configurable[LLM_SETTINGS_KEY] = LLMSettings()
    config = _config(**configurable)
    checkpointer = checkpointer or build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config).model_copy(
        update={"submission": state.submission})
    graph = build_phase3a_methodology_graph(checkpointer)
    if interrupt_before is not None:
        graph.invoke(initial, {**config, "interrupt_before": [interrupt_before]})
        return _invoke(build_phase3a_methodology_graph(checkpointer), None, config)
    return _invoke(graph, initial, config)


def run_stages(
    state: EvaluationGraphState, provider: Any, *, bounds: MethodologyReviewBounds | None = None,
    finalize: bool = True, final_research_run: Any = None, final_project: Any = None, final_submission: Any = ...,
):
    """The same stages the graph runs, driven directly so a test can change an upstream input between
    bind and finalize. Returns the Phase 3A run."""
    from datetime import UTC, datetime

    from src.research.methodology import pipeline as mp

    bounds = bounds or MethodologyReviewBounds()
    llm = LLMSettings()
    rr, project, submission = state.active_research_run, state.project, state.submission
    now = datetime.now(UTC)
    run = mp.open_run(rr, project, submission, now)
    if run.is_terminal:
        return run
    run = mp.inventory_stage(run)
    run = mp.overlay_stage(run, rr, project, submission, provider, llm, bounds)
    run = mp.evidence_stage(run, project, submission, provider, llm, bounds)
    run = mp.applicability_stage(run, project, submission, provider, llm, bounds)
    run = mp.assess_stage(run)
    run = mp.link_stage(run, rr, project, submission, provider, llm, bounds)
    run = mp.continuity_stage(run)
    run = mp.synthesis_stage(run)
    if not finalize:
        return run
    return mp.finalize_stage(
        run, final_research_run or rr, final_project or project,
        submission if final_submission is ... else final_submission, now)


def review(state: EvaluationGraphState):
    return state.active_research_run.methodology_review


__all__ = [name for name in dir() if not name.startswith("_")]
