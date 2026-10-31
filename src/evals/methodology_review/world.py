"""Phase 3A Gold world: real upstream graphs, a scripted UNTRUSTED model, the real Phase 3A graph.

The upstream state is built by the real Phase 2E-2J graphs (``build_phase2i_world`` and
``run_phase2j``); nothing upstream is hand-built. ``ScriptedMethodologyModel`` plays the
untrusted model for the five Phase 3A calls from a per-case JSON script, so a case can make
it behave well, fabricate an excerpt, follow an injected instruction or leak the system
prompt. It cannot produce a posture: there is no field a script could put one in.

This module drives the system. It never decides what the correct answer is.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.config.settings import LLMSettings
from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke
from src.evals.research_engineering_gap.fixtures import (
    CLAIM, CLAIMS, ND_SCRIPT, PATENT, extract_with, limitation_with, script,
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
from src.schemas.methodology_review import MethodologyReviewBounds
from src.schemas.submission import StudentSubmissionArtifact

BASE_CLAIM = CLAIM
GAP_VARIANTS = ("default", "baseline", "no_condition", "no_requirement")


def _ok(task: ModelTask, parsed: Any) -> ModelCallResult:
    return ModelCallResult(status=ModelCallStatus.SUCCESS, parsed=parsed, model="fake-model", provider="fake",
                           task=task, request_id="fake-request",
                           usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0))


def prompt_line() -> str:
    """A line of a hidden Phase 3A prompt, used by scripts that leak it."""
    return next(ln.strip() for ln in METHODOLOGY_OVERLAY_ASSESSMENT_PROMPT_V1.splitlines() if len(ln.strip()) >= 40)


def _failure(task: ModelTask, kind: str) -> ModelCallResult:
    if kind == "refusal_leak":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake", task=task,
                               refusal=prompt_line())
    if kind == "error_leak":
        return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, model="fake-model", provider="fake",
                               task=task, error=prompt_line())
    if kind == "parse_error":
        return ModelCallResult(status=ModelCallStatus.PARSE_ERROR, model="fake-model", provider="fake", task=task,
                               error="parsed output failed schema validation")
    if kind == "refusal":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake", task=task,
                               refusal="I cannot help with that request.")
    return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, model="fake-model", provider="fake", task=task,
                           error="APIConnectionError: connection reset")


def _expand_leaks(value: Any) -> Any:
    """Every script string equal to ``$LEAK`` becomes a hidden-prompt line."""
    if isinstance(value, str):
        return prompt_line() if value == "$LEAK" else value
    if isinstance(value, list):
        return [_expand_leaks(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_leaks(v) for k, v in value.items()}
    return value


def span(spec: Any) -> SubmissionSpanDTO | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        return SubmissionSpanDTO(excerpt=spec)
    return SubmissionSpanDTO(excerpt=spec["excerpt"], start=spec.get("start"), end=spec.get("end"),
                             occurrence=spec.get("occurrence"), rationale=spec.get("rationale"))


_E_LINE = re.compile(r"^\[(E\d+)\] \(([A-Z_]+) / ([A-Z_]+)\) (.*)$")
_K_LINE = re.compile(r"^\[(K\d+)\] condition of (G\d+) ")


def _excerpt_labels(user_input: str) -> dict[str, str]:
    block = user_input.split(METHODOLOGY_EXCERPTS_MARKER, 1)[-1].split(METHODOLOGY_ITEMS_MARKER, 1)[0]
    return {m.group(1): m.group(4) for line in block.split("\n") if (m := _E_LINE.match(line))}


def _condition_labels(user_input: str) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for line in user_input.split(METHODOLOGY_ITEMS_MARKER, 1)[-1].split("\n"):
        if m := _K_LINE.match(line):
            seen[m.group(2)] = seen.get(m.group(2), 0) + 1
            out[f"{m.group(2)}:{seen[m.group(2)]}"] = m.group(1)
    return out


@dataclass
class ScriptedMethodologyModel:
    """Answers the five Phase 3A prompts from a JSON script. Records every call."""

    script: dict[str, Any]
    calls: list[tuple[ModelTask, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.script = _expand_leaks(copy.deepcopy(self.script))

    def provider(self) -> FakeStructuredModelProvider:
        return FakeStructuredModelProvider(factory=self)

    def count(self, task: ModelTask) -> int:
        return sum(1 for t, _ in self.calls if t is task)

    def user_inputs(self) -> str:
        return "\n".join(u for _, u in self.calls)

    def __call__(self, task: ModelTask, user_input: str) -> ModelCallResult:
        self.calls.append((task, user_input))
        failing = self.script.get("fail", {}).get(task.value)
        if failing:
            return _failure(task, failing)
        raw = self.script.get("raw", {}).get(task.value)
        if raw is not None:
            return _ok(task, _raw(task, raw))
        handler = {
            ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT: self._overlay,
            ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION: self._evidence,
            ModelTask.METHODOLOGY_APPLICABILITY: self._applicability,
            ModelTask.METHODOLOGY_METRIC_BASELINE: self._metric,
            ModelTask.METHODOLOGY_TARGET_LINKAGE: self._link,
        }.get(task)
        return handler(user_input) if handler else _failure(task, "provider_error")

    def _spec(self, key: str, task: ModelTask):
        spec = self.script.get(key)
        if spec is None:
            return None, _failure(task, "provider_error")
        return spec, None

    def _overlay(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT
        spec = dict(self.script.get("overlay", {}))
        if not self.script.get("overlay_omit"):  # a well-behaved model answers every overlay it is asked about
            asked = re.findall(r"^OVERLAY: ([A-Z_]+)$", user_input, flags=re.M)
            claims = re.findall(r"^\[(C\d+)\] ", user_input, flags=re.M)
            hyps = re.findall(r"^\[(H\d+)\] ", user_input, flags=re.M)
            spec = {**{name: {"materiality": "NO_METHODOLOGY_RELEVANCE", "claims": claims, "hypotheses": hyps}
                       for name in asked}, **spec}
        return _ok(task, OverlayAssessmentResponse(overlays=[
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
        return _ok(task, EvidenceExtractionResponse(requirements=reqs))

    def _applicability(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_APPLICABILITY
        spec, bad = self._spec("applicability", task)
        if bad:
            return bad
        return _ok(task, ApplicabilityResponse(judgments=[
            ApplicabilityJudgmentDTO(kind=kind, fired_triggers=s.get("fired", []), excerpt=span(s.get("excerpt")))
            for kind, s in spec.items()]))

    def _metric(self, user_input: str) -> ModelCallResult:
        task = ModelTask.METHODOLOGY_METRIC_BASELINE
        spec, bad = self._spec("metric", task)
        if bad:
            return bad
        baselines = self.script.get("baseline", {})
        return _ok(task, MetricBaselineResponse(
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
            return [next((label for label, text in excerpts.items() if snip in text), snip) for snip in snippets]

        coverage = [CoverageJudgmentDTO(target=t, track=track, relation=s["relation"],
                                        excerpts=labels(s.get("excerpts", [])), rationale=s.get("rationale"))
                    for t, tracks in spec.items() for track, s in tracks.items()]
        condition_labels = _condition_labels(user_input)
        judgments = [ConditionJudgmentDTO(condition=condition_labels.get(k, k), status=s["status"],
                                          excerpts=labels(s.get("excerpts", [])), rationale=s.get("rationale"))
                     for k, s in self.script.get("conditions", {}).items()]
        return _ok(task, TargetLinkageResponse(coverage=coverage, conditions=judgments))


def _raw(task: ModelTask, raw: Any) -> Any:
    """A raw typed response a script supplies verbatim (an off-contract or fabricated one)."""
    response = {
        ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT: OverlayAssessmentResponse,
        ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION: EvidenceExtractionResponse,
        ModelTask.METHODOLOGY_APPLICABILITY: ApplicabilityResponse,
        ModelTask.METHODOLOGY_METRIC_BASELINE: MetricBaselineResponse,
        ModelTask.METHODOLOGY_TARGET_LINKAGE: TargetLinkageResponse,
    }[task]
    return response.model_validate(raw)


def reorder(script_: dict[str, Any]) -> dict[str, Any]:
    """The same typed judgments with every unordered collection reversed (an input-order twin)."""
    out = copy.deepcopy(script_)
    for key in ("evidence", "applicability", "metric", "baseline", "conditions", "overlay"):
        if isinstance(out.get(key), dict):
            out[key] = dict(reversed(list(out[key].items())))
    for spec in out.get("evidence", {}).values():
        spec["excerpts"] = list(reversed(spec.get("excerpts", [])))
    return out


def with_prose(script_: dict[str, Any], prose: str) -> dict[str, Any]:
    """The same TYPED judgments with different free prose injected everywhere prose can go."""
    out = copy.deepcopy(script_)
    for spec in out.get("overlay", {}).values():
        spec["excerpts"] = [{**(e if isinstance(e, dict) else {"excerpt": e}), "rationale": prose}
                            for e in spec.get("excerpts", [])]
    for spec in out.get("evidence", {}).values():
        spec["excerpts"] = [{**(e if isinstance(e, dict) else {"excerpt": e}), "rationale": prose}
                            for e in spec.get("excerpts", [])]
    for spec in out.get("applicability", {}).values():
        if spec.get("excerpt") is not None:
            e = spec["excerpt"]
            spec["excerpt"] = {**(e if isinstance(e, dict) else {"excerpt": e}), "rationale": prose}
    for tracks in out.get("link", {}).values():
        for s in tracks.values():
            s["rationale"] = prose
    for s in out.get("conditions", {}).values():
        s["rationale"] = prose
    return out


# -- worlds ------------------------------------------------------------------------------------------


def _with_project(state: EvaluationGraphState, project_type: ProjectType,
                  domains: tuple[TechnicalDomain, ...]) -> EvaluationGraphState:
    identity = state.project.identity.model_copy(update={"project_type": project_type, "domain": list(domains)})
    return state.model_copy(update={"project": state.project.model_copy(update={"identity": identity})})


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


_I_WORLDS: dict[str, EvaluationGraphState] = {}
_WORLDS: dict[tuple, EvaluationGraphState] = {}


def claim_text(claim_variant: str) -> str:
    return CLAIMS[0]["claim"] if claim_variant == "base" else CLAIM + " " + claim_variant


def _phase2i_world(claim_variant: str) -> EvaluationGraphState:
    if claim_variant not in _I_WORLDS:
        claims = CLAIMS if claim_variant == "base" else [{"claim_id": "C-001", "claim": claim_text(claim_variant)}]
        _I_WORLDS[claim_variant] = build_phase2i_world(
            "PJ-3A-GOLD", claims, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)
    return _I_WORLDS[claim_variant]


def phase2j_world(project_type: str, domains: tuple[str, ...], gap_variant: str, claim_variant: str = "base"
                  ) -> EvaluationGraphState:
    """A state carrying a finished Phase 2J run (real 2E-2J graphs), cached per upstream shape."""
    key = (project_type, tuple(domains), gap_variant, claim_variant)
    if key not in _WORLDS:
        state = _with_project(_phase2i_world(claim_variant), ProjectType(project_type),
                              tuple(TechnicalDomain(d) for d in domains))
        _WORLDS[key] = run_phase2j(
            state, ScriptedGapModel({"C-001": claim_text(claim_variant)}, _gap_script(gap_variant)).provider())
    return _WORLDS[key]


def with_submission(state: EvaluationGraphState, text: str | None, language: str = "en"
                    ) -> EvaluationGraphState:
    submission = None if text is None else StudentSubmissionArtifact(
        artifact_id=uuid5(NAMESPACE_URL, f"phase3a-gold-submission:{text}"),
        project_id=state.project.project_id, original_text=text, language=language)
    return state.model_copy(update={"submission": submission})


def run_phase3a(state: EvaluationGraphState, provider: Any, *, bounds: MethodologyReviewBounds | None = None,
                interrupt_before: str | None = None, checkpointer: Any = None) -> EvaluationGraphState:
    """The REAL Phase 3A graph."""
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


def run_stages(state: EvaluationGraphState, provider: Any, *, bounds: MethodologyReviewBounds | None = None,
               final_research_run: Any = None, final_project: Any = None, final_submission: Any = ...):
    """The same production stages the graph runs, driven directly so a case can change an upstream input
    between bind and finalize. Returns the Phase 3A run."""
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
    return mp.finalize_stage(run, final_research_run or rr, final_project or project,
                             submission if final_submission is ... else final_submission, now)


__all__ = [
    "BASE_CLAIM", "GAP_VARIANTS", "ScriptedMethodologyModel", "claim_text", "phase2j_world", "prompt_line",
    "reorder", "run_phase3a", "run_stages", "span", "with_prose", "with_submission",
]
