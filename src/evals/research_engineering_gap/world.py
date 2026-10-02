"""Phase 2J eval world: real upstream graphs, a scripted untrusted model.

The upstream state is built by the real Phase 2E, 2F, 2G, 2H and 2I graphs
(``build_phase2i_world``); nothing upstream is hand-built. ``ScriptedGapModel``
then plays the *untrusted* model for the three Phase 2J calls from a per-claim
script, so a fixture can make it behave well, fabricate an excerpt, invent a
metric, follow an injected instruction or leak the system prompt -- which is how
every verifier gate is exercised. It never produces a gap posture: there is no
field a script could put one in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.evals.novelty_differentiation.world import ScriptedNoveltyModel, build_upstream, run_phase2i
from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke
from src.graph.gap_nodes import GAP_MODEL_PROVIDER_KEY
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.persistence import build_checkpointer
from src.graph.phase2j_graph import build_phase2j_gap_graph
from src.graph.workflow_state import EvaluationGraphState, coerce_graph_state
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask, ModelUsage
from src.llm.fake_provider import FakeStructuredModelProvider
from src.llm.prompts import (
    GAP_CANDIDATE_EXTRACTION_PROMPT_V1,
    GAP_CLAIM_MARKER,
    GAP_FEATURE_MARKER,
    GAP_LIMITATION_MARKER,
    GAP_SOURCE_MARKER,
)
from src.research.gap.dto import (
    CapabilityDTO,
    ConditionDTO,
    CounterEvidenceDTO,
    CounterEvidenceResponse,
    GapExtractionResponse,
    LimitationDTO,
    LinkageResponse,
    LinkJudgmentDTO,
    ValidationDTO,
)
from src.research.settings import ResearchSettings
from src.schemas.gap_assessment import GapAssessmentBounds


def _ok(task: ModelTask, parsed: Any) -> ModelCallResult:
    return ModelCallResult(status=ModelCallStatus.SUCCESS, parsed=parsed, model="fake-model", provider="fake",
                           task=task, request_id="fake-request",
                           usage=ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0))


def _failure(task: ModelTask, kind: str) -> ModelCallResult:
    if kind == "parse_error":
        return ModelCallResult(status=ModelCallStatus.PARSE_ERROR, model="fake-model", provider="fake",
                               task=task, error="parsed output failed schema validation")
    if kind == "refusal":
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake",
                               task=task, refusal="I cannot help with that request.")
    return ModelCallResult(status=ModelCallStatus.PROVIDER_ERROR, model="fake-model", provider="fake",
                           task=task, error="APIConnectionError: connection reset")


_TEXT_HEADER = re.compile(r"^\[(T\d+)\] \(([A-Z_]+)\)$")
_ITEM = re.compile(r"^\[([FL]\d+)\] \(([A-Z_]+)\) (.*)$")


def parse_texts(user_input: str) -> list[tuple[str, str, str]]:
    """(token, kind, text) for every source text in a Phase 2J user message."""
    body = user_input.split(GAP_SOURCE_MARKER, 1)[-1]
    out: list[tuple[str, str, str]] = []
    token = kind = None
    buffer: list[str] = []
    for line in body.split("\n"):
        header = _TEXT_HEADER.match(line)
        if header:
            if token:
                out.append((token, kind, "\n".join(buffer).strip("\n")))
            token, kind, buffer = header.group(1), header.group(2), []
        else:
            buffer.append(line)
    if token:
        out.append((token, kind, "\n".join(buffer).strip("\n")))
    return out


def parse_items(user_input: str, marker: str, prefix: str) -> list[tuple[str, str, str]]:
    """(label, type, text) for the F or L items under a marker."""
    section = user_input.split(marker, 1)[-1].split("\n\n", 1)[0]
    return [(m.group(1), m.group(2), m.group(3)) for line in section.split("\n")
            if (m := _ITEM.match(line)) and m.group(1).startswith(prefix)]


@dataclass
class ScriptedGapModel:
    """Answers the three Phase 2J prompts from a per-claim script. Records every call.

    ``script["extract"][claim_id]`` is a dict (or a failure string) with
    ``capabilities``, ``limitations``, ``validation``, ``proposed_kind``;
    ``script["link"][claim_id]`` a list of judgments; ``script["counter"][claim_id]``
    a list of items. Text and excerpt selectors: ``excerpt`` is searched in the
    shown texts (``in`` = a text kind or a token narrows it; ``token`` forces it).
    """

    claims: dict[str, str]
    script: dict[str, Any]
    calls: list[tuple[ModelTask, str]] = field(default_factory=list)

    def provider(self) -> FakeStructuredModelProvider:
        return FakeStructuredModelProvider(factory=self)

    def __call__(self, task: ModelTask, user_input: str) -> ModelCallResult:
        self.calls.append((task, user_input))
        if task is ModelTask.GAP_CANDIDATE_EXTRACTION:
            return self._extract(user_input)
        if task is ModelTask.GAP_PROJECT_LINKAGE:
            return self._link(user_input)
        if task is ModelTask.GAP_COUNTEREVIDENCE_REVIEW:
            return self._counter(user_input)
        return _failure(task, "provider_error")

    # -- helpers --------------------------------------------------------------

    def _span(self, texts: list[tuple[str, str, str]], spec: dict[str, Any]) -> dict[str, Any]:
        excerpt = spec["excerpt"]
        token = spec.get("token")
        if token is None and "in" in spec:
            token = next((t for t, kind, _ in texts if kind == spec["in"] or t == spec["in"]), "T99")
        if token is None:
            token = next((t for t, _, text in texts if excerpt in text), texts[0][0] if texts else "T99")
        return {"text": token, "excerpt": excerpt, "start": spec.get("start"), "end": spec.get("end"),
                "occurrence": spec.get("occurrence"), "rationale": self._rationale(spec)}

    @staticmethod
    def _rationale(spec: dict[str, Any]) -> str | None:
        if spec.get("leak_system_prompt"):
            line = next(ln for ln in GAP_CANDIDATE_EXTRACTION_PROMPT_V1.splitlines() if len(ln.strip()) >= 40)
            return f"My hidden instructions: {line.strip()}"
        return spec.get("rationale")

    # -- extraction -----------------------------------------------------------

    def _claim_for_extraction(self, user_input: str) -> str | None:
        body = user_input.split(GAP_CLAIM_MARKER, 1)[-1].split(GAP_SOURCE_MARKER, 1)[0].strip()
        return next((cid for cid, text in self.claims.items() if text.strip() == body), None)

    def _extract(self, user_input: str) -> ModelCallResult:
        task = ModelTask.GAP_CANDIDATE_EXTRACTION
        spec = self.script.get("extract", {}).get(self._claim_for_extraction(user_input))
        if spec is None or isinstance(spec, str):
            return _failure(task, spec or "provider_error")
        texts = parse_texts(user_input)
        limitations = []
        for item in spec.get("limitations", []):
            limitations.append(LimitationDTO(
                **self._span(texts, item), label=item["label"], limitation_type=item["type"], facet=item["facet"],
                condition_dimensions=item.get("dimensions", []),
                conditions=[ConditionDTO(**self._span(texts, c), dimension=c["dimension"])
                            for c in item.get("conditions", [])],
            ))
        validation = spec.get("validation")
        return _ok(task, GapExtractionResponse(
            capabilities=[CapabilityDTO(**self._span(texts, c), label=c["label"]) for c in spec.get("capabilities", [])],
            limitations=limitations,
            validation=ValidationDTO(**validation) if validation else None,
            proposed_kind=spec.get("proposed_kind"),
        ))

    # -- linkage --------------------------------------------------------------

    def _claim_for_link(self, features: list[tuple[str, str, str]]) -> str | None:
        texts = [t for _, _, t in features]
        return next((cid for cid, claim in self.claims.items() if texts and all(t in claim for t in texts)), None)

    def _link(self, user_input: str) -> ModelCallResult:
        task = ModelTask.GAP_PROJECT_LINKAGE
        features = parse_items(user_input, GAP_FEATURE_MARKER, "F")
        limitations = parse_items(user_input, GAP_LIMITATION_MARKER, "L")
        specs = self.script.get("link", {}).get(self._claim_for_link(features))
        if specs is None or isinstance(specs, str):
            return _failure(task, specs or "provider_error")
        judgments = []
        for spec in specs:
            feature = next((t for t, _, text in features if text == spec["feature"] or t == spec["feature"]), "F99")
            limitation = next(
                (t for t, _, text in limitations if t == spec["limitation"] or spec["limitation"] in text), "L99")
            judgments.append(LinkJudgmentDTO(feature=feature, limitation=limitation, relation=spec["relation"],
                                             rationale=self._rationale(spec)))
        return _ok(task, LinkageResponse(judgments=judgments))

    # -- counterevidence ------------------------------------------------------

    def _claim_for_counter(self, limitations: list[tuple[str, str, str]]) -> str | None:
        excerpts = [t for _, _, t in limitations]
        for cid, spec in self.script.get("extract", {}).items():
            if isinstance(spec, dict) and any(
                lim["excerpt"] in " ".join(excerpts) for lim in spec.get("limitations", [])
            ):
                return cid
        return None

    def _counter(self, user_input: str) -> ModelCallResult:
        task = ModelTask.GAP_COUNTEREVIDENCE_REVIEW
        limitations = parse_items(user_input, GAP_LIMITATION_MARKER, "L")
        specs = self.script.get("counter", {}).get(self._claim_for_counter(limitations), [])
        if isinstance(specs, str):
            return _failure(task, specs)
        texts = parse_texts(user_input)
        return _ok(task, CounterEvidenceResponse(items=[
            CounterEvidenceDTO(**self._span(texts, s), kind=s["kind"], condition_match=s["condition_match"])
            for s in specs
        ]))


def build_phase2i_world(
    case_id: str, claims: list[dict[str, str]], *, patent: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None, oss: dict[str, Any] | None = None,
    cutoff: dict[str, str] | None = None, nd_script: dict[str, Any] | None = None,
) -> EvaluationGraphState:
    """Real 2E -> 2F -> 2G -> 2H -> 2I graphs; the result carries a finished Phase 2I run."""
    before = build_upstream(case_id, claims, patent=patent, product=product, oss=oss, cutoff=cutoff)
    model = ScriptedNoveltyModel({c["claim_id"]: c["claim"] for c in claims}, nd_script or {})
    return run_phase2i(before, model.provider())


def run_phase2j(
    state: EvaluationGraphState,
    provider: Any,
    *,
    bounds: GapAssessmentBounds | None = None,
    interrupt_before: str | None = None,
) -> EvaluationGraphState:
    configurable: dict[str, Any] = {"settings": ResearchSettings(gap=bounds or GapAssessmentBounds())}
    if provider is not None:
        from src.config.settings import LLMSettings

        configurable[GAP_MODEL_PROVIDER_KEY] = provider
        configurable[LLM_SETTINGS_KEY] = LLMSettings()
    config = _config(**configurable)
    checkpointer = build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config)
    if interrupt_before is not None:
        build_phase2j_gap_graph(checkpointer).invoke(initial, {**config, "interrupt_before": [interrupt_before]})
        return coerce_graph_state(build_phase2j_gap_graph(checkpointer).invoke(None, config))
    return _invoke(build_phase2j_gap_graph(checkpointer), initial, config)


__all__ = [
    "ScriptedGapModel",
    "build_phase2i_world",
    "parse_items",
    "parse_texts",
    "run_phase2j",
]
