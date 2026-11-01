"""Shared Phase 3B production-test world.

The upstream state is built by the real Phase 2E-2J graphs and the real Phase 3A
graph (``tests.phase3a_support``); nothing upstream is hand-built.
``ScriptedExperimentModel`` plays the *untrusted* model for the four Phase 3B
tasks from a script, so a test can make it behave well, fabricate an excerpt,
invent a requirement, cite an unknown target, follow an injected instruction or
leak the system prompt. It cannot produce a posture: no DTO has a field for one.

This is a focused test helper, not a Gold fixture: no expectation here is a graded case.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.config.settings import LLMSettings
from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke
from src.graph.experiment_nodes import EXPERIMENT_MODEL_PROVIDER_KEY
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.persistence import build_checkpointer
from src.graph.phase3b_graph import build_phase3b_experiment_graph
from src.graph.workflow_state import EvaluationGraphState
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask, ModelUsage
from src.llm.fake_provider import FakeStructuredModelProvider
from src.llm.prompts import (
    EXPERIMENT_CLAIMS_MARKER,
    EXPERIMENT_END_MARKER,
    EXPERIMENT_EXCERPTS_MARKER,
    EXPERIMENT_ITEMS_MARKER,
    EXPERIMENT_SEGMENTATION_PROMPT_V1,
)
from src.research.experiments import pipeline as xp
from src.research.experiments.dto import (
    ApplicabilityJudgmentDTO,
    ApplicabilityResponse,
    BaselineDTO,
    ComparabilityDTO,
    ConditionJudgmentDTO,
    ExperimentSegmentDTO,
    LinkageResponse,
    MeasurementDTO,
    ProtocolExtractionResponse,
    ProtocolRequirementDTO,
    ResultSpanDTO,
    SegmentationResponse,
    SpanDTO,
    TargetJudgmentDTO,
)
from src.research.settings import ResearchSettings
from src.schemas.common import ProjectType
from src.schemas.experiment_review import (
    Applicability,
    ExperimentRequirementKind,
    ExperimentReviewBounds,
    ExperimentType,
    resolve_applicability,
)
from src.schemas.submission import StudentSubmissionArtifact
from tests import phase3a_support as p3a

# -- the protocol text -------------------------------------------------------------------------

P_DEFINE = "Experiment 1 bench tests the irrigation controller on 12 soil trays in the lab for 14 days."
P_OBJECTIVE = "The objective is to check that the controller keeps soil moisture inside the target band."
P_SETUP = "Setup: each tray has one moisture sensor, one valve and the controller firmware version 2.1."
P_ENV = "The lab is held at 24 C and 40 percent humidity under shaded grow lights."
P_INPUTS = "Inputs are hourly sensor readings and a recorded weather forecast file."
P_OUTPUTS = "Outputs are valve open times and logged moisture values."
P_VARIABLES = "The dependent variable is moisture error; tray soil type and light are held constant."
P_SAMPLE = "The sample is 12 trays of the same loam soil, chosen to cover the sensor range."
P_REPEAT = "The 14 day run is repeated three times with fresh soil each time."
P_METHOD = "Moisture error is measured by comparing sensor values with a calibrated reference probe every hour."
P_METRIC = "The metric is moisture accuracy, the share of hours inside the target band."
P_CRITERION = "Success criterion, fixed before the trial: accuracy of at least 90 percent."
P_DETAIL = "The full step list and firmware settings are given in the appendix."
P_TRACE = "This test checks requirement R1, keeping moisture inside the band."
P_CONDITION = "Low light conditions are covered by the shaded grow lights."
RESULT = "Result: the controller kept moisture within the band 97 percent of the time."

PROTOCOL = [P_DEFINE, P_OBJECTIVE, P_SETUP, P_ENV, P_INPUTS, P_OUTPUTS, P_VARIABLES, P_SAMPLE, P_REPEAT, P_METHOD,
            P_METRIC, P_CRITERION, P_DETAIL, P_TRACE, P_CONDITION]
SUBMISSION = " ".join([*PROTOCOL, RESULT])

KIND_TEXT = {
    "OBJECTIVE": P_OBJECTIVE, "TARGET_BINDING": P_TRACE, "HYPOTHESIS_OR_VALIDATION_OBJECTIVE": P_OBJECTIVE,
    "SUCCESS_CRITERION": P_CRITERION, "REQUIREMENT_TRACEABILITY": P_TRACE, "SETUP": P_SETUP, "ENVIRONMENT": P_ENV,
    "CONFIGURATION": P_SETUP, "OPERATING_CONDITIONS": P_CONDITION, "INPUTS": P_INPUTS, "OUTPUTS": P_OUTPUTS,
    "DEPENDENT_VARIABLE": P_VARIABLES, "CONTROLLED_VARIABLES": P_VARIABLES, "SAMPLE_DEFINITION": P_SAMPLE,
    "SAMPLE_SIZE": P_SAMPLE, "REPETITIONS": P_REPEAT, "MEASUREMENT_METHOD": P_METHOD, "INSTRUMENT": P_METHOD,
    "METRIC": P_METRIC, "PROTOCOL_DETAIL": P_DETAIL,
}


def required_kinds(xtype: ExperimentType) -> list[str]:
    return [k.value for k in ExperimentRequirementKind
            if resolve_applicability(k, xtype, None)[0] is Applicability.REQUIRED]


def documented(xtype: ExperimentType = ExperimentType.ENGINEERING_BENCH_TEST, *, missing: tuple[str, ...] = (),
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every REQUIRED kind of ``xtype`` explicitly documented and adequate, except ``missing``."""
    out = {k: {"excerpts": [KIND_TEXT.get(k, P_DETAIL)]} for k in required_kinds(xtype) if k not in missing}
    out.update(copy.deepcopy(extra or {}))
    return out


def ok(task: ModelTask, parsed: Any) -> ModelCallResult:
    return ModelCallResult(status=ModelCallStatus.SUCCESS, parsed=parsed, model="fake-model", provider="fake",
                           task=task, request_id="fake-request",
                           usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0))


def failure(task: ModelTask, kind: str) -> ModelCallResult:
    status = {"refusal": ModelCallStatus.REFUSAL, "parse_error": ModelCallStatus.PARSE_ERROR,
              "incomplete": ModelCallStatus.INCOMPLETE_OUTPUT, "empty": ModelCallStatus.EMPTY_OUTPUT}.get(
        kind, ModelCallStatus.PROVIDER_ERROR)
    return ModelCallResult(status=status, model="fake-model", provider="fake", task=task,
                           refusal="I cannot help." if status is ModelCallStatus.REFUSAL else None,
                           error=None if status is ModelCallStatus.REFUSAL else "simulated failure")


def prompt_line() -> str:
    return next(ln.strip() for ln in EXPERIMENT_SEGMENTATION_PROMPT_V1.splitlines() if len(ln.strip()) >= 40)


def span(spec: Any) -> SpanDTO:
    if isinstance(spec, str):
        return SpanDTO(excerpt=spec)
    return SpanDTO(excerpt=spec["excerpt"], start=spec.get("start"), end=spec.get("end"),
                   occurrence=spec.get("occurrence"))


_DIRECT_KEYS = {"targets", "conditions", "requirements", "type", *(k.value for k in ExperimentRequirementKind)}
_LABEL_LINE = re.compile(r"^\[([A-Z]\d+)\] (.*)$")


def _block(user_input: str, marker: str) -> dict[str, str]:
    if marker not in user_input:
        return {}
    body = user_input.split(marker, 1)[1]
    for stop in (EXPERIMENT_CLAIMS_MARKER, EXPERIMENT_EXCERPTS_MARKER, EXPERIMENT_END_MARKER):
        body = body.split(stop, 1)[0]
    return {m.group(1): m.group(2) for line in body.split("\n") if (m := _LABEL_LINE.match(line))}


@dataclass
class ScriptedExperimentModel:
    """Answers the four Phase 3B prompts from a script. Records every call.

    Per-experiment script sections are keyed by a snippet of that experiment's first
    defining excerpt; ``"*"`` applies to every experiment."""

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
        handler = {
            ModelTask.EXPERIMENT_SEGMENTATION: self._segment,
            ModelTask.EXPERIMENT_PROTOCOL_EXTRACTION: self._extract,
            ModelTask.EXPERIMENT_APPLICABILITY: self._applicability,
            ModelTask.EXPERIMENT_TARGET_LINKAGE: self._link,
        }[task]
        return handler(task, user_input)

    # -- helpers ------------------------------------------------------------------------------

    def _for(self, section: str, user_input: str, excerpts: dict[str, str]) -> Any:
        spec = self.script.get(section, {})
        if isinstance(spec, str) or set(spec) & _DIRECT_KEYS:
            return spec
        texts = [t for t in excerpts.values()] or [user_input]
        for key, value in spec.items():
            if key != "*" and any(key in t for t in texts[:1]):
                return value
        for key, value in spec.items():
            if key != "*" and any(key in t for t in texts):
                return value
        return spec.get("*")

    @staticmethod
    def _labels(excerpts: dict[str, str], snippets: list[str]) -> list[str]:
        out = []
        for snip in snippets:
            out.append(next((label for label, text in excerpts.items() if snip in text), snip))
        return out

    # -- calls ------------------------------------------------------------------------------

    def _segment(self, task: ModelTask, user_input: str) -> ModelCallResult:
        spec = self.script.get("segment", {"experiments": [{"label": "X1", "excerpts": [P_DEFINE]}],
                                           "results": [{"kind": "REPORTED_METRIC_VALUE", "span": RESULT}]})
        if isinstance(spec, str):
            return failure(task, spec)
        return ok(task, SegmentationResponse(
            experiments=[ExperimentSegmentDTO(label=e["label"], defining_excerpts=[span(x) for x in e["excerpts"]],
                                              revision_of=e.get("revision_of"), rationale=e.get("rationale"))
                         for e in spec.get("experiments", [])],
            results=[ResultSpanDTO(kind=r["kind"], span=span(r["span"])) for r in spec.get("results", [])]))

    def _extract(self, task: ModelTask, user_input: str) -> ModelCallResult:
        defining = {m.group(1): m.group(2) for line in user_input.split("\n")
                    if (m := re.match(r"^\[(D\d+)\] (.*)$", line))}
        spec = self._for("extract", user_input, defining)
        if spec is None:
            spec = {"type": "ENGINEERING_BENCH_TEST", "requirements": documented()}
        if isinstance(spec, str):
            return failure(task, spec)
        reqs = [ProtocolRequirementDTO(kind=k, documentation=s.get("documentation", "EXPLICITLY_DOCUMENTED"),
                                       adequacy=s.get("adequacy", "ADEQUATELY_SPECIFIED_FOR_REVIEW"),
                                       excerpts=[span(x) for x in s["excerpts"]], rationale=s.get("rationale"))
                for k, s in spec.get("requirements", {}).items()]
        return ok(task, ProtocolExtractionResponse(
            experiment_type=spec.get("type", "ENGINEERING_BENCH_TEST"),
            execution_status=spec.get("execution", "EXECUTION_STATUS_NOT_DOCUMENTED"),
            owner_track=spec.get("owner"), owner_excerpts=[span(x) for x in spec.get("owner_excerpts", [])],
            requirements=list(reversed(reqs)) if self.script.get("reverse") else reqs))

    def _applicability(self, task: ModelTask, user_input: str) -> ModelCallResult:
        excerpts = _block(user_input, EXPERIMENT_EXCERPTS_MARKER)
        spec = self._for("applicability", user_input, excerpts)
        if isinstance(spec, str):
            return failure(task, spec)
        spec = spec or {}
        asked = re.findall(r"^\[R\d+\] ([A-Z_]+);", user_input, flags=re.M)
        default = None if self.script.get("applicability_omit") else {"fired": [], "excerpts": [P_DEFINE]}
        judgments = []
        for kind in asked:
            s = spec.get(kind, default)
            if s is None:
                continue
            judgments.append(ApplicabilityJudgmentDTO(kind=kind, fired_triggers=s.get("fired", []),
                                                      excerpts=self._labels(excerpts, s.get("excerpts", [])),
                                                      rationale=s.get("rationale")))
        judgments += [ApplicabilityJudgmentDTO(kind=k, fired_triggers=s.get("fired", []),
                                               excerpts=self._labels(excerpts, s.get("excerpts", [])))
                      for k, s in spec.items() if k not in asked]
        if self.script.get("reverse"):
            judgments.reverse()
        return ok(task, ApplicabilityResponse(judgments=judgments))

    def _link(self, task: ModelTask, user_input: str) -> ModelCallResult:
        excerpts = _block(user_input, EXPERIMENT_EXCERPTS_MARKER)
        spec = self._for("link", user_input, excerpts)
        if spec is None:
            spec = well_link()
        if isinstance(spec, str):
            return failure(task, spec)
        lab = lambda xs: self._labels(excerpts, xs or [])  # noqa: E731
        targets = []
        for target, s in spec.get("targets", {}).items():
            m = s.get("measurement")
            b = s.get("baseline")
            targets.append(TargetJudgmentDTO(
                target=target, relation=s["relation"], excerpts=lab(s.get("excerpts")), rationale=s.get("rationale"),
                measurement=None if m is None else MeasurementDTO(
                    method=(lab([m["method"]]) or [None])[0] if m.get("method") else None,
                    metric=(lab([m["metric"]]) or [None])[0] if m.get("metric") else None,
                    success_criterion=(lab([m["criterion"]]) or [None])[0] if m.get("criterion") else None,
                    alignment=m.get("alignment", "ALIGNED_SAME_TARGET"),
                    phase2j_metric_match=m.get("match", "SAME_AS_PHASE_2J"),
                    criterion_timing=m.get("timing", "PRE_SPECIFIED_AS_DESCRIBED")),
                baseline=None if b is None else BaselineDTO(
                    excerpts=lab(b.get("excerpts")), relevance=b.get("relevance", "RELEVANCE_UNRESOLVED"),
                    context=b.get("context", []), rationale_excerpts=lab(b.get("rationale_excerpts")),
                    phase2j_baseline_match=b.get("match", "MATCH_UNRESOLVED"),
                    comparability=[ComparabilityDTO(property=p, status=st, excerpts=lab(xs))
                                   for p, (st, xs) in b.get("comparability", {}).items()])))
        conditions = [ConditionJudgmentDTO(condition=k, status=s["status"], excerpts=lab(s.get("excerpts")))
                      for k, s in spec.get("conditions", {}).items()]
        if self.script.get("reverse"):
            targets.reverse()
            conditions.reverse()
        return ok(task, LinkageResponse(targets=targets, conditions=conditions))


def measured(**over: Any) -> dict[str, Any]:
    return {"method": P_METHOD, "metric": P_METRIC, "criterion": P_CRITERION, **over}


def well_link() -> dict[str, Any]:
    """T1 (the claim) and V1 (its Phase 2J requirement) directly tested; K1 addressed."""
    return {
        "targets": {
            "T1": {"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE], "measurement": measured()},
            "V1": {"relation": "DIRECTLY_TESTS", "excerpts": [P_DEFINE], "measurement": measured()},
        },
        "conditions": {"K1": {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [P_CONDITION]}},
    }


def edited(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out = copy.deepcopy(base)
    out.update(copy.deepcopy(changes))
    return out


# -- worlds -------------------------------------------------------------------------------------


@lru_cache(maxsize=16)
def _phase3a_world(project_type: ProjectType, gap_variant: str, text: str) -> EvaluationGraphState:
    state = p3a.world(project_type, text=text, gap_variant=gap_variant)
    return p3a.run_phase3a(state, None)


def world(text: str = SUBMISSION, project_type: ProjectType = ProjectType.ENGINEERING_PROJECT,
          gap_variant: str = "default") -> EvaluationGraphState:
    """A state carrying finished Phase 2J and Phase 3A runs over this exact submission."""
    return _phase3a_world(project_type, gap_variant, text)


def resubmit(state: EvaluationGraphState, text: str) -> EvaluationGraphState:
    sub = StudentSubmissionArtifact(artifact_id=uuid5(NAMESPACE_URL, f"phase3b-resubmit:{text}"),
                                    project_id=state.project.project_id, original_text=text, language="en")
    return state.model_copy(update={"submission": sub})


def run_phase3b(state: EvaluationGraphState, provider: Any, *, bounds: ExperimentReviewBounds | None = None,
                interrupt_before: str | None = None, checkpointer: Any = None) -> EvaluationGraphState:
    configurable: dict[str, Any] = {"settings": ResearchSettings(experiment=bounds or ExperimentReviewBounds())}
    if provider is not None:
        configurable[EXPERIMENT_MODEL_PROVIDER_KEY] = provider
        configurable[LLM_SETTINGS_KEY] = LLMSettings()
    config = _config(**configurable)
    checkpointer = checkpointer or build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config).model_copy(
        update={"submission": state.submission})
    graph = build_phase3b_experiment_graph(checkpointer)
    if interrupt_before is not None:
        graph.invoke(initial, {**config, "interrupt_before": [interrupt_before]})
        return _invoke(build_phase3b_experiment_graph(checkpointer), None, config)
    return _invoke(graph, initial, config)


def run_stages(state: EvaluationGraphState, provider: Any, *, bounds: ExperimentReviewBounds | None = None,
               final_research_run: Any = None, final_project: Any = None, final_submission: Any = ...):
    """The same stages the graph runs, driven directly so a test can change an upstream input
    between bind and finalize. Returns the Phase 3B run."""
    bounds = bounds or ExperimentReviewBounds()
    llm = LLMSettings()
    rr, project, submission = state.active_research_run, state.project, state.submission
    now = datetime(2026, 10, 31, tzinfo=UTC)
    run = xp.open_run(rr, project, submission, now, bounds=bounds)
    if run.is_terminal:
        return run
    run = xp.segment_stage(run, submission, provider, llm, bounds)
    run = xp.extract_stage(run, submission, provider, llm, bounds)
    run = xp.applicability_stage(run, project, submission, provider, llm, bounds)
    run = xp.link_stage(run, rr, project, submission, provider, llm, bounds)
    run = xp.synthesis_stage(run)
    return xp.finalize_stage(run, final_research_run or rr, final_project or project,
                             submission if final_submission is ... else final_submission, now)


def review(state: EvaluationGraphState):
    return state.active_research_run.experiment_review


__all__ = [name for name in dir() if not name.startswith("_")]
