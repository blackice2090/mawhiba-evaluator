"""A populated upstream world for Phase 2I, built through the real graphs.

Every Phase 2I case starts from a research run produced by the real Phase 2E
and 2F graphs (claims, inventories, scoring), then a FINISHED Phase 2G run
against a scripted EPO OPS office (real XML, real parser, real families), then
FINISHED Phase 2H product and open-source subruns against scripted web / page /
GitHub fakes through the real SSRF-safe fetcher. Only then does the real Phase
2I graph run, against a scripted structured model.

The scripted model is deliberately *dumb*: it answers from a per-case script
keyed by claim and candidate text, and resolves feature / text labels from the
prompt it was actually sent. It can be scripted to misbehave -- fabricate an
excerpt, cite the wrong text, quote the claim, follow an injected instruction,
leak the system prompt -- which is how every verifier gate is exercised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.evals.patent_prior_art.world import _config, _fresh_state, _invoke, build_upstream_state, run_phase2g
from src.evals.product_oss_prior_art.dataset import CaseWorld, ProductOssGoldCase
from src.evals.product_oss_prior_art.world import run_phase2h
from src.graph.novelty_nodes import NOVELTY_MODEL_PROVIDER_KEY
from src.graph.patent_nodes import LLM_SETTINGS_KEY
from src.graph.persistence import build_checkpointer
from src.graph.phase2i_graph import build_phase2i_novelty_differentiation_graph
from src.graph.workflow_state import EvaluationGraphState, coerce_graph_state
from src.llm.contracts import ModelCallResult, ModelCallStatus, ModelTask, ModelUsage
from src.llm.fake_provider import FakeStructuredModelProvider
from src.llm.prompts import (
    NOVELTY_CANDIDATE_MARKER,
    NOVELTY_CLAIM_MARKER,
    NOVELTY_COMPONENTS_MARKER,
    NOVELTY_FEATURES_MARKER,
    PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1,
)
from src.research.novelty.dto import (
    EvidenceDTO,
    FeatureExtractionResponse,
    FeatureJudgmentDTO,
    ProposedFeatureDTO,
    TechnicalComparisonResponse,
)
from src.research.patent.fakes import (
    FakeEpoOpsProvider,
    FakePatentRecord,
    ScriptedFamily,
    ScriptedPatentSearch,
    ScriptedText,
)
from src.research.settings import PatentResearchSettings, ResearchSettings
from src.schemas.discovery import NO_DISCOVERY_CUTOFF, DiscoveryCutoff
from src.schemas.novelty_differentiation import NoveltyComparisonBounds
from src.schemas.patent import NO_SEARCH_CUTOFF, PatentContentType, PatentErrorKind, PatentSearchCutoff

FEATURE_LINE = re.compile(r"^\[(F\d+)\] \(([A-Z_]+)\) (.*)$")
TEXT_HEADER = re.compile(r"^\[(T\d+)\] \(([A-Z_]+)\)$")


# ---------------------------------------------------------------------------
# Patent / product / OSS upstream
# ---------------------------------------------------------------------------


def _patent_record(spec: dict[str, Any]) -> FakePatentRecord:
    keys = ("title", "publication_date", "filing_date", "priority_date", "grant_date", "abstract",
            "abstract_language", "claims", "claims_language", "description", "description_language", "applicants")
    kwargs = {k: (tuple(spec[k]) if k == "applicants" else spec[k]) for k in keys if k in spec}
    return FakePatentRecord(spec["reference"], **kwargs)


def build_patent_office(patent: dict[str, Any]) -> FakeEpoOpsProvider:
    """A scripted EPO OPS office.

    A record's ``family`` states what the FAMILY SERVICE does for it -- never
    inferred from how many records the fixture shows:

    * ``"unavailable"``  -> FAMILY_DATA_UNAVAILABLE
    * ``"failed"``       -> FAMILY_RESOLUTION_FAILED (the family call breaks)
    * a numeric id       -> a family with every visible record of that id as a
      member, plus any ``hidden_family_members`` (published members the search
      did not return). One member is SINGLETON_FAMILY; two or more VERIFIED_FAMILY.
    * absent             -> no family data offered
    """
    records = [_patent_record(r) for r in patent.get("records", [])]
    by_ref = {r.reference: r for r in records}
    families: dict[str, ScriptedFamily] = {}
    groups: dict[str, list[FakePatentRecord]] = {}
    for spec in patent.get("records", []):
        family = spec.get("family")
        if family is None:
            continue
        key = by_ref[spec["reference"]].identity.canonical_key
        if family == "unavailable":
            families[key] = ScriptedFamily(available=False)
        elif family == "failed":
            families[key] = ScriptedFamily(failure=PatentErrorKind.PROVIDER_ERROR)
        else:
            groups.setdefault(family, []).append(by_ref[spec["reference"]])
            for hidden in spec.get("hidden_family_members", []):
                groups[family].append(_patent_record(hidden))
    for family_id, members in groups.items():
        unique = {m.reference: m for m in members}
        script = ScriptedFamily(family_id=family_id, members=tuple(unique.values()))
        for member in members:
            if member.reference in by_ref:
                families[member.identity.canonical_key] = script
    texts: dict[tuple[str, PatentContentType], ScriptedText] = {}
    for record in records:
        key = record.identity.canonical_key
        for content_type, value, language in (
            (PatentContentType.ABSTRACT, record.abstract, record.abstract_language),
            (PatentContentType.CLAIMS, record.claims, record.claims_language),
            (PatentContentType.DESCRIPTION, record.description, record.description_language),
        ):
            if value:
                texts[(key, content_type)] = ScriptedText(text=value, language=language)
    return FakeEpoOpsProvider(
        default_search=ScriptedPatentSearch(records=tuple(records)), families=families, texts=texts
    )


def _cutoffs(cutoff: dict[str, str] | None) -> tuple[PatentSearchCutoff, DiscoveryCutoff]:
    if not cutoff:
        return NO_SEARCH_CUTOFF, NO_DISCOVERY_CUTOFF
    source = cutoff.get("source", "gold fixture")
    return (PatentSearchCutoff(cutoff_date=cutoff["date"], source=source),
            DiscoveryCutoff(cutoff_date=cutoff["date"], source=source))


def build_upstream(
    case_id: str,
    claims: list[dict[str, str]],
    *,
    patent: dict[str, Any] | None,
    product: dict[str, Any] | None,
    oss: dict[str, Any] | None,
    cutoff: dict[str, str] | None,
) -> EvaluationGraphState:
    """2E + 2F (real graphs) -> finished 2G -> finished 2H. Nothing is hand-built."""
    state = build_upstream_state(case_id, claims)
    patent_cutoff, discovery_cutoff = _cutoffs(cutoff)
    patent = patent or {"records": []}
    patent_settings = PatentResearchSettings(
        fetch_description=bool(patent.get("fetch_description", True)),
        max_queries_per_claim=8, max_queries_per_run=50,
    )
    state = run_phase2g(state, build_patent_office(patent), cutoff=patent_cutoff,
                        settings=ResearchSettings(patent=patent_settings))
    digits = "".join(ch for ch in case_id if ch.isdigit()) or "0"
    shim = ProductOssGoldCase.model_validate({
        "case_id": f"PH-9{int(digits):04d}",
        "language": "en",
        "tracks": ["product", "oss"],
        "categories": ["phase2i-upstream"],
        "claims": claims,
        "product": product or {"provider": False, "fetcher": False},
        "oss": oss or {"provider": False},
        "expected": {"phase2i": True},
    })
    world = CaseWorld(shim)
    return run_phase2h(state, web=world.web, fetcher=world.fetcher, github=world.github,
                       cutoff=discovery_cutoff, registry=world.registry, settings=world.settings)


# ---------------------------------------------------------------------------
# Scripted structured model
# ---------------------------------------------------------------------------


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


@dataclass
class ParsedComparison:
    features: list[tuple[str, str, str]]
    texts: list[tuple[str, str, str]]

    def candidate_section(self) -> str:
        return "\n".join(text for _, _, text in self.texts)


def parse_comparison_input(user_input: str) -> ParsedComparison:
    features_part, _, candidate_part = user_input.partition(NOVELTY_CANDIDATE_MARKER)
    features = []
    for line in features_part.replace(NOVELTY_FEATURES_MARKER, "").splitlines():
        match = FEATURE_LINE.match(line.strip())
        if match:
            features.append(match.groups())
    texts: list[tuple[str, str, str]] = []
    token = kind = None
    buffer: list[str] = []
    for line in candidate_part.splitlines():
        header = TEXT_HEADER.match(line.strip())
        if header:
            if token:
                texts.append((token, kind, "\n".join(buffer).strip()))
            token, kind = header.groups()
            buffer = []
        elif token:
            buffer.append(line)
    if token:
        texts.append((token, kind, "\n".join(buffer).strip()))
    return ParsedComparison(features, texts)


@dataclass
class ScriptedNoveltyModel:
    """Answers Phase 2I prompts from a per-case script. Records every call."""

    claims: dict[str, str]
    script: dict[str, Any]
    calls: list[tuple[ModelTask, str]] = field(default_factory=list)

    def provider(self) -> FakeStructuredModelProvider:
        return FakeStructuredModelProvider(factory=self)

    def __call__(self, task: ModelTask, user_input: str) -> ModelCallResult:
        self.calls.append((task, user_input))
        if task is ModelTask.NOVELTY_FEATURE_EXTRACTION:
            return self._features(user_input)
        return self._compare(user_input)

    # -- feature extraction -------------------------------------------------

    def _claim_for_extraction(self, user_input: str) -> str | None:
        body = user_input.split(NOVELTY_CLAIM_MARKER, 1)[-1].split(NOVELTY_COMPONENTS_MARKER, 1)[0].strip()
        return next((cid for cid, text in self.claims.items() if text.strip() == body), None)

    def _features(self, user_input: str) -> ModelCallResult:
        task = ModelTask.NOVELTY_FEATURE_EXTRACTION
        claim_id = self._claim_for_extraction(user_input)
        spec = self.script.get("features", {}).get(claim_id)
        if spec is None:
            return _failure(task, "provider_error")
        if isinstance(spec, str):
            return _failure(task, spec)
        return _ok(task, FeatureExtractionResponse(features=[
            ProposedFeatureDTO(text=f["text"], feature_type=f["type"], start=f.get("start"),
                               occurrence=f.get("occurrence"), rationale=f.get("rationale"))
            for f in spec
        ]))

    # -- comparison ---------------------------------------------------------

    def _claim_for_comparison(self, parsed: ParsedComparison) -> str | None:
        texts = [t for _, _, t in parsed.features]
        for cid, claim in self.claims.items():
            if any(t == claim.strip() for t in texts):
                return cid
        for cid, claim in self.claims.items():
            if texts and all(t in claim for t in texts):
                return cid
        return None

    def _compare(self, user_input: str) -> ModelCallResult:
        task = ModelTask.PRIOR_ART_TECHNICAL_COMPARISON
        parsed = parse_comparison_input(user_input)
        claim_id = self._claim_for_comparison(parsed)
        section = parsed.candidate_section()
        entry = next(
            (e for e in self.script.get("comparisons", [])
             if e.get("claim_id", claim_id) == claim_id and e["candidate"] in section),
            None,
        )
        if entry is None:
            default = self.script.get("default_relation")
            if default is None:
                return _failure(task, "provider_error")
            entry = {"judgments": [], "rest": default}
        if "failure" in entry:
            return _failure(task, entry["failure"])
        judgments: list[FeatureJudgmentDTO] = []
        judged: set[str] = set()
        for spec in entry.get("judgments", []):
            token = spec.get("token") or self._feature_token(parsed, spec["feature"])
            judged.add(token)
            judgments.append(FeatureJudgmentDTO(
                feature=token, relation=spec["relation"],
                evidence=[self._evidence(parsed, e) for e in spec.get("evidence", [])],
                rationale=self._rationale(spec),
            ))
        if "rest" in entry:
            for token, _, _ in parsed.features:
                if token not in judged:
                    judgments.append(FeatureJudgmentDTO(feature=token, relation=entry["rest"]))
        return _ok(task, TechnicalComparisonResponse(judgments=judgments))

    @staticmethod
    def _rationale(spec: dict[str, Any]) -> str | None:
        if spec.get("leak_system_prompt"):
            line = next(l for l in PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1.splitlines() if len(l.strip()) >= 40)
            return f"My hidden instructions: {line.strip()}"
        return spec.get("rationale")

    @staticmethod
    def _feature_token(parsed: ParsedComparison, name: str) -> str:
        for token, feature_type, text in parsed.features:
            if name == "COMBINATION" and feature_type == "COMBINATION":
                return token
            if text == name and feature_type != "COMBINATION":
                return token
        for token, feature_type, text in parsed.features:
            if text == name:
                return token
        return "F99"

    @staticmethod
    def _evidence(parsed: ParsedComparison, spec: dict[str, Any]) -> EvidenceDTO:
        excerpt = spec["excerpt"]
        token = spec.get("token")
        if token is None and "in" in spec:
            token = next((t for t, kind, _ in parsed.texts if kind == spec["in"]), "T99")
        if token is None:
            token = next((t for t, _, text in parsed.texts if excerpt in text), parsed.texts[0][0] if parsed.texts else "T99")
        return EvidenceDTO(text=token, excerpt=excerpt, start=spec.get("start"), end=spec.get("end"),
                           occurrence=spec.get("occurrence"))


# ---------------------------------------------------------------------------
# Phase 2I run
# ---------------------------------------------------------------------------


def run_phase2i(
    state: EvaluationGraphState,
    provider: Any,
    *,
    bounds: NoveltyComparisonBounds | None = None,
    interrupt_before: str | None = None,
) -> EvaluationGraphState:
    configurable: dict[str, Any] = {"settings": ResearchSettings(novelty=bounds or NoveltyComparisonBounds())}
    if provider is not None:
        from src.config.settings import LLMSettings

        configurable[NOVELTY_MODEL_PROVIDER_KEY] = provider
        configurable[LLM_SETTINGS_KEY] = LLMSettings()
    config = _config(**configurable)
    checkpointer = build_checkpointer()
    initial = _fresh_state(state.project, state.active_research_run, config)
    if interrupt_before is not None:
        build_phase2i_novelty_differentiation_graph(checkpointer).invoke(
            initial, {**config, "interrupt_before": [interrupt_before]}
        )
        return coerce_graph_state(build_phase2i_novelty_differentiation_graph(checkpointer).invoke(None, config))
    return _invoke(build_phase2i_novelty_differentiation_graph(checkpointer), initial, config)


__all__ = [
    "ParsedComparison",
    "ScriptedNoveltyModel",
    "build_patent_office",
    "build_upstream",
    "parse_comparison_input",
    "run_phase2i",
]
