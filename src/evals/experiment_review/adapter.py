"""The narrow execution adapter: the ONLY Phase 3B Gold module allowed to import Phase 3B production code.

It drives the system and exposes no semantic answer. It builds the upstream state through the REAL Phase 2E-2J
graphs and the real Phase 3A graph, plays the UNTRUSTED model from a per-case JSON script (so a case can make it
behave well, fabricate an excerpt, invent a requirement, cite an unknown target, follow an injected instruction,
leak the system prompt or fail), and runs the REAL Phase 3B graph or its stages. It cannot produce a posture:
no model-facing DTO has a field a script could put one in.

Nothing here decides what the correct answer is. The independent reader (``context.py``) and the authored
expectations do that.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from src.config.settings import LLMSettings
from src.evals.methodology_review.world import run_phase3a, with_submission
from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke
from src.evals.research_engineering_gap.fixtures import (
    CLAIM,
    CLAIMS,
    ND_SCRIPT,
    PATENT,
    extract_with,
    limitation_with,
    script,
)
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
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
    EXPERIMENT_SEGMENTATION_PROMPT_V1,
    escape_untrusted,
    unescape_untrusted,
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
from src.schemas.common import ProjectType, TechnicalDomain
from src.schemas.experiment_review import ExperimentReviewBounds, ExperimentReviewRun
from src.schemas.project import ExperimentRecord as LegacyExperimentRecord
from src.schemas.project import ResultRecord
from src.schemas.common import Tracked
from src.schemas.submission import StudentSubmissionArtifact

BASE_CLAIM = CLAIM
LEGACY_MARKER = "LEGACY-RESULT-SUCCESS-98.7-PERCENT-ACCURACY-PASSED-ALL"
"""A marker no submission, claim or script contains: if it reaches a prompt or an output, legacy state leaked."""

GAP_VARIANTS = ("default", "baseline", "no_condition", "no_requirement")
_ARGS = (ProjectType, TechnicalDomain)


# -- the scripted untrusted model ---------------------------------------------------------------------------


def _ok(task: ModelTask, parsed: Any) -> ModelCallResult:
    return ModelCallResult(status=ModelCallStatus.SUCCESS, parsed=parsed, model="fake-model", provider="fake",
                           task=task, request_id="fake-request",
                           usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0))


def prompt_line() -> str:
    """A line of a hidden Phase 3B prompt, used by scripts that leak it."""
    return next(ln.strip() for ln in EXPERIMENT_SEGMENTATION_PROMPT_V1.splitlines() if len(ln.strip()) >= 40)


def _failure(task: ModelTask, kind: str) -> ModelCallResult:
    base = {"model": "fake-model", "provider": "fake", "task": task}
    if kind == "refusal_leak":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, refusal=prompt_line(), **base)
    if kind == "error_leak":
        return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, error=prompt_line(), **base)
    if kind == "refusal":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, refusal="I cannot help with that request.", **base)
    if kind == "parse_error":
        return ModelCallResult(status=ModelCallStatus.PARSE_ERROR, error="parsed output failed schema validation",
                               **base)
    if kind == "incomplete":
        return ModelCallResult(status=ModelCallStatus.INCOMPLETE_OUTPUT, error="output truncated", **base)
    if kind == "empty":
        return ModelCallResult(status=ModelCallStatus.EMPTY_OUTPUT, error="empty output", **base)
    return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, error="APIConnectionError: connection reset", **base)


def _expand_leaks(value: Any) -> Any:
    if isinstance(value, str):
        return prompt_line() if value == "$LEAK" else value
    if isinstance(value, list):
        return [_expand_leaks(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_leaks(v) for k, v in value.items()}
    return value


def _span(spec: Any) -> SpanDTO:
    if isinstance(spec, str):
        return SpanDTO(excerpt=spec)
    return SpanDTO(excerpt=spec["excerpt"], start=spec.get("start"), end=spec.get("end"),
                   occurrence=spec.get("occurrence"))


_LABEL_LINE = re.compile(r"^\[([A-Z]\d+)\] (.*)$")
_DIRECT_KEYS = {"targets", "conditions", "requirements", "type"}


def _block(user_input: str, marker: str) -> dict[str, str]:
    if marker not in user_input:
        return {}
    body = user_input.split(marker, 1)[1]
    for stop in (EXPERIMENT_CLAIMS_MARKER, EXPERIMENT_EXCERPTS_MARKER, EXPERIMENT_END_MARKER):
        body = body.split(stop, 1)[0]
    return {m.group(1): unescape_untrusted(m.group(2)) for line in body.split("\n")
            if (m := _LABEL_LINE.match(line))}


@dataclass
class ScriptedModel:
    """Answers the four Phase 3B prompts from a JSON script. Records every provider request.

    Per-experiment sections are keyed by a snippet of that experiment's first defining excerpt; ``"*"`` applies to
    every experiment. A section that is a string is a provider failure of that kind."""

    script: dict[str, Any]
    calls: list[tuple[ModelTask, str]] = field(default_factory=list)
    fails: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.script = _expand_leaks(copy.deepcopy(self.script))

    def provider(self) -> FakeStructuredModelProvider:
        return FakeStructuredModelProvider(factory=self)

    def _sp(self, spec: Any) -> SpanDTO:
        """A span; with ``quote_escaped`` the model copies from the ESCAPED prompt text, as a real model would."""
        span = _span(spec)
        if self.script.get("quote_escaped"):
            span = span.model_copy(update={"excerpt": escape_untrusted(span.excerpt)})
        return span

    def count(self, task: ModelTask) -> int:
        return sum(1 for t, _ in self.calls if t is task)

    def user_inputs(self) -> list[str]:
        return [u for _, u in self.calls]

    def __call__(self, task: ModelTask, user_input: str) -> ModelCallResult:
        self.calls.append((task, user_input))
        key = {ModelTask.EXPERIMENT_SEGMENTATION: "segment", ModelTask.EXPERIMENT_PROTOCOL_EXTRACTION: "extract",
               ModelTask.EXPERIMENT_APPLICABILITY: "applicability", ModelTask.EXPERIMENT_TARGET_LINKAGE: "link"}[task]
        if self.fails.get(key, 0) < int(self.script.get("fail_first", {}).get(key, 0)):
            self.fails[key] = self.fails.get(key, 0) + 1
            return _failure(task, "provider_error")  # a transient fault: the bounded retry may recover
        handler = {ModelTask.EXPERIMENT_SEGMENTATION: self._segment,
                   ModelTask.EXPERIMENT_PROTOCOL_EXTRACTION: self._extract,
                   ModelTask.EXPERIMENT_APPLICABILITY: self._applicability,
                   ModelTask.EXPERIMENT_TARGET_LINKAGE: self._link}[task]
        return handler(task, user_input)

    def _for(self, section: str, user_input: str, excerpts: dict[str, str]) -> Any:
        spec = self.script.get(section, {})
        if isinstance(spec, str) or set(spec) & _DIRECT_KEYS:
            return spec
        texts = list(excerpts.values()) or [user_input]
        for key, value in spec.items():
            if key != "*" and key in texts[0]:
                return value
        for key, value in spec.items():
            if key != "*" and any(key in t for t in texts):
                return value
        return spec.get("*")

    @staticmethod
    def _labels(excerpts: dict[str, str], snippets: list[str]) -> list[str]:
        return [next((label for label, text in excerpts.items() if snip in text), snip) for snip in snippets]

    def _segment(self, task: ModelTask, user_input: str) -> ModelCallResult:
        spec = self.script.get("segment", {"experiments": [], "results": []})
        if isinstance(spec, str):
            return _failure(task, spec)
        return _ok(task, SegmentationResponse(
            experiments=[ExperimentSegmentDTO(label=e["label"], defining_excerpts=[self._sp(x) for x in e["excerpts"]],
                                              revision_of=e.get("revision_of"), rationale=e.get("rationale"))
                         for e in spec.get("experiments", [])],
            results=[ResultSpanDTO(kind=r["kind"], span=self._sp(r["span"])) for r in spec.get("results", [])]))

    def _extract(self, task: ModelTask, user_input: str) -> ModelCallResult:
        defining = {m.group(1): unescape_untrusted(m.group(2)) for line in user_input.split("\n")
                    if (m := re.match(r"^\[(D\d+)\] (.*)$", line))}
        spec = self._for("extract", user_input, defining)
        if isinstance(spec, str):
            return _failure(task, spec)
        spec = spec or {"type": "UNKNOWN", "requirements": {}}
        reqs: list[ProtocolRequirementDTO] = []
        for kind, raw in spec.get("requirements", {}).items():
            for s in (raw if isinstance(raw, list) else [raw]):
                reqs.append(ProtocolRequirementDTO(
                    kind=kind, documentation=s.get("documentation", "EXPLICITLY_DOCUMENTED"),
                    adequacy=s.get("adequacy", "ADEQUATELY_SPECIFIED_FOR_REVIEW"),
                    excerpts=[self._sp(x) for x in s.get("excerpts", [])], rationale=s.get("rationale")))
        return _ok(task, ProtocolExtractionResponse(
            experiment_type=spec.get("type", "UNKNOWN"),
            execution_status=spec.get("execution", "EXECUTION_STATUS_NOT_DOCUMENTED"),
            owner_track=spec.get("owner"), owner_excerpts=[self._sp(x) for x in spec.get("owner_excerpts", [])],
            requirements=list(reversed(reqs)) if self.script.get("reverse") else reqs))

    def _applicability(self, task: ModelTask, user_input: str) -> ModelCallResult:
        excerpts = _block(user_input, EXPERIMENT_EXCERPTS_MARKER)
        spec = self._for("applicability", user_input, excerpts)
        if isinstance(spec, str):
            return _failure(task, spec)
        spec = spec or {}
        asked = re.findall(r"^\[R\d+\] ([A-Z_]+);", user_input, flags=re.M)
        default = None if self.script.get("applicability_omit") else {"fired": [], "excerpts": ["E1"]}
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
        return _ok(task, ApplicabilityResponse(judgments=judgments))

    def _link(self, task: ModelTask, user_input: str) -> ModelCallResult:
        excerpts = _block(user_input, EXPERIMENT_EXCERPTS_MARKER)
        spec = self._for("link", user_input, excerpts)
        if isinstance(spec, str):
            return _failure(task, spec)
        spec = spec or {}

        def lab(xs: list[str] | None) -> list[str]:
            return self._labels(excerpts, xs or [])

        targets = []
        for target, s in spec.get("targets", {}).items():
            m, b = s.get("measurement"), s.get("baseline")
            targets.append(TargetJudgmentDTO(
                target=target, relation=s["relation"], excerpts=lab(s.get("excerpts")), rationale=s.get("rationale"),
                measurement=None if m is None else MeasurementDTO(
                    method=(lab([m["method"]]) or [None])[0] if m.get("method") else None,
                    metric=(lab([m["metric"]]) or [None])[0] if m.get("metric") else None,
                    unit=(lab([m["unit"]]) or [None])[0] if m.get("unit") else None,
                    success_criterion=(lab([m["criterion"]]) or [None])[0] if m.get("criterion") else None,
                    alignment=m.get("alignment", "ALIGNED_SAME_TARGET"),
                    phase2j_metric_match=m.get("match", "SAME_AS_PHASE_2J"),
                    criterion_timing=m.get("timing", "PRE_SPECIFIED_AS_DESCRIBED")),
                baseline=None if b is None else BaselineDTO(
                    excerpts=lab(b.get("excerpts")), relevance=b.get("relevance", "RELEVANCE_UNRESOLVED"),
                    context=b.get("context", []), rationale_excerpts=lab(b.get("rationale_excerpts")),
                    phase2j_baseline_match=b.get("match", "MATCH_UNRESOLVED"),
                    execution_status=b.get("execution", "EXECUTION_STATUS_NOT_DOCUMENTED"),
                    comparability=[ComparabilityDTO(property=p, status=st, excerpts=lab(xs))
                                   for p, (st, xs) in b.get("comparability", {}).items()])))
        conditions = [ConditionJudgmentDTO(condition=k, status=s["status"], excerpts=lab(s.get("excerpts")))
                      for k, s in spec.get("conditions", {}).items()]
        if self.script.get("reverse"):
            targets.reverse()
            conditions.reverse()
        return _ok(task, LinkageResponse(targets=targets, conditions=conditions))


def reorder(model_script: dict[str, Any]) -> dict[str, Any]:
    """The same semantic answers, listed in the opposite order."""
    out = copy.deepcopy(model_script)
    out["reverse"] = True
    seg = out.get("segment")
    if isinstance(seg, dict):
        seg["experiments"] = list(reversed(seg.get("experiments", [])))
        seg["results"] = list(reversed(seg.get("results", [])))
        for e in seg["experiments"]:
            e["excerpts"] = list(reversed(e["excerpts"]))
    return out


# -- worlds -------------------------------------------------------------------------------------------------


_I_WORLDS: dict[str, EvaluationGraphState] = {}
_WORLDS: dict[tuple, EvaluationGraphState] = {}
_P3A: dict[tuple, EvaluationGraphState] = {}


def claim_text(claim_variant: str) -> str:
    return CLAIMS[0]["claim"] if claim_variant == "base" else CLAIM + " " + claim_variant


def claim_variant_of(text: str) -> str:
    return "base" if text == CLAIM else text[len(CLAIM) + 1:]


def _gap_script(variant: str) -> dict[str, Any]:
    if variant == "default":
        return script()
    if variant == "baseline":
        return script(extract_with(validation={"metric_source": "L1", "metric": "accuracy",
                                                "baseline_source": "C1", "baseline": "94%"}))
    if variant == "no_condition":
        return script(extract_with(limitations=[limitation_with(conditions=[])]))
    if variant == "no_requirement":
        return script(extract_with(validation=None))
    raise ValueError(variant)


def _phase2i_world(claim_variant: str) -> EvaluationGraphState:
    if claim_variant not in _I_WORLDS:
        claims = CLAIMS if claim_variant == "base" else [{"claim_id": "C-001", "claim": claim_text(claim_variant)}]
        _I_WORLDS[claim_variant] = build_phase2i_world(
            "PJ-3B-GOLD", claims, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)
    return _I_WORLDS[claim_variant]


def phase2j_world(project_type: str, domains: tuple[str, ...], gap_variant: str, claim_variant: str = "base"
                  ) -> EvaluationGraphState:
    """A state carrying a finished Phase 2J run (real 2E-2J graphs), cached per upstream shape."""
    key = (project_type, tuple(domains), gap_variant, claim_variant)
    if key not in _WORLDS:
        state = _phase2i_world(claim_variant)
        identity = state.project.identity.model_copy(update={
            "project_type": ProjectType(project_type), "domain": [TechnicalDomain(d) for d in domains]})
        state = state.model_copy(update={"project": state.project.model_copy(update={"identity": identity})})
        _WORLDS[key] = run_phase2j(
            state, ScriptedGapModel({"C-001": claim_text(claim_variant)}, _gap_script(gap_variant)).provider())
    return _WORLDS[key]


def build_state(case, *, text: str | None = ..., legacy: bool | None = None) -> EvaluationGraphState:
    """The state Phase 3B is run over: a finished Phase 2J run, a finished Phase 3A run over the SAME
    submission (Phase 3A is run without a model: it is context only), the claims and the submission."""
    world = case.phase2j_world
    claim = case.claims[0]["claim"]
    base = phase2j_world(case.project_type, tuple(world.get("domains", ())), world.get("gap_variant", "default"),
                         claim_variant_of(claim))
    submission_text = case.submission if text is ... else text
    state = with_submission(base, submission_text, case.language)
    key = (case.project_type, tuple(world.get("domains", ())), world.get("gap_variant", "default"),
           claim_variant_of(claim), submission_text, case.language)
    if key not in _P3A:
        _P3A[key] = run_phase3a(state, None)
    state = _P3A[key]
    if (case.legacy_leak if legacy is None else legacy):
        project = state.project.model_copy(update={
            "results": [ResultRecord(result_id="R-01", metric="accuracy", value=Tracked[str].known(LEGACY_MARKER))],
            "experiments": [LegacyExperimentRecord(experiment_id="EXP-01", objective=LEGACY_MARKER,
                                                   success_criteria=[LEGACY_MARKER])]})
        state = state.model_copy(update={"project": project})
    return state


# -- running the real Phase 3B -----------------------------------------------------------------------------


def bounds_of(raw: dict[str, Any]) -> ExperimentReviewBounds | None:
    return ExperimentReviewBounds(**raw) if raw else None


def run_graph(state: EvaluationGraphState, provider: Any, *, bounds: ExperimentReviewBounds | None = None,
              interrupt_before: str | None = None) -> EvaluationGraphState:
    """The REAL Phase 3B graph."""
    configurable: dict[str, Any] = {"settings": ResearchSettings(experiment=bounds or ExperimentReviewBounds())}
    if provider is not None:
        configurable[EXPERIMENT_MODEL_PROVIDER_KEY] = provider
        configurable[LLM_SETTINGS_KEY] = LLMSettings()
    config = _config(**configurable)
    checkpointer = build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config).model_copy(
        update={"submission": state.submission})
    graph = build_phase3b_experiment_graph(checkpointer)
    if interrupt_before is not None:
        graph.invoke(initial, {**config, "interrupt_before": [interrupt_before]})
        return _invoke(build_phase3b_experiment_graph(checkpointer), None, config)
    return _invoke(graph, initial, config)


def run_stages(state: EvaluationGraphState, provider: Any, *, bounds: ExperimentReviewBounds | None = None,
               final_research_run: Any = None, final_project: Any = None, final_submission: Any = ...
               ) -> ExperimentReviewRun:
    """The same production stages the graph runs, driven directly so a case can change an upstream input
    between bind and finalize."""
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


def review_dict(state: EvaluationGraphState) -> dict[str, Any]:
    return state.active_research_run.experiment_review.model_dump(mode="json")


def edited_submission(sub: StudentSubmissionArtifact | None, suffix: str) -> StudentSubmissionArtifact | None:
    if sub is None:
        return None
    return StudentSubmissionArtifact(artifact_id=sub.artifact_id, project_id=sub.project_id,
                                     original_text=sub.original_text + suffix, language=sub.language)


def validate_run(d: dict[str, Any]) -> str | None:
    """The production run contract applied to a serialized (possibly mutated) run: None when it validates,
    otherwise the validation error text. Used by negative controls to learn WHY a mutation was refused."""
    try:
        ExperimentReviewRun.model_validate(d)
    except ValidationError as exc:
        return str(exc)
    return None


__all__ = [name for name in dir() if not name.startswith("_")]
