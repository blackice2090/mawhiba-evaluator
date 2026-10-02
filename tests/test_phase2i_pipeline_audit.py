"""Phase 2I stale-semantics audit: serialization, immutability and an end-to-end
run through the real 2E -> 2F -> 2G -> 2H -> 2I graphs."""

from __future__ import annotations

import pytest

from src.evals.novelty_differentiation.world import ScriptedNoveltyModel, build_upstream, run_phase2i
from src.schemas.novelty_differentiation import (
    ClaimTechnicalPosture,
    IndependenceUnitKind,
    NoveltyDifferentiationRun,
)

CLAIM = "A smart irrigation controller using soil moisture sensors and weather forecasts"
PATENT = {"records": [{
    "reference": "EP.1000001.A1", "title": "Irrigation", "publication_date": "2015-06-01", "abstract": "abs",
    "claims": "1. A controller using soil moisture sensors and weather forecasts to irrigate.", "family": "F1",
}]}
SCRIPT = {
    "features": {"C-001": [{"text": "soil moisture sensors", "type": "COMPONENT"},
                           {"text": "weather forecasts", "type": "COMPONENT"}]},
    "comparisons": [{"candidate": "soil moisture", "judgments": [
        {"feature": "soil moisture sensors", "relation": "DISCLOSED",
         "evidence": [{"excerpt": "soil moisture sensors", "in": "PATENT_CLAIMS"}]},
        {"feature": "weather forecasts", "relation": "DISCLOSED",
         "evidence": [{"excerpt": "weather forecasts", "in": "PATENT_CLAIMS"}]},
    ], "rest": "NOT_DISCLOSED"}],
}


@pytest.fixture(scope="module")
def world():
    claims = [{"claim_id": "C-001", "claim": CLAIM}]
    before = build_upstream("PI-901", claims, patent=PATENT, product=None, oss=None, cutoff={"date": "2020-01-01"})
    model = ScriptedNoveltyModel({"C-001": CLAIM}, SCRIPT)
    after = run_phase2i(before, model.provider())
    return before, after


def test_all_components_found_without_the_combination_is_not_full_overlap(world):
    nd = world[1].active_research_run.novelty_differentiation
    comparison = nd.comparisons[0]
    assert comparison.verified
    assert comparison.full_claim_relation.value == "COMPONENT_ONLY_OVERLAP"
    assert nd.claim_syntheses[0].posture is ClaimTechnicalPosture.PARTIAL_TECHNICAL_OVERLAP_ONLY


def test_unresolved_family_patent_is_compared_but_not_independent(world):
    nd = world[1].active_research_run.novelty_differentiation
    profile = nd.candidate_profiles[0]
    assert profile.comparable
    kind = profile.independence_unit.unit_kind
    if kind is IndependenceUnitKind.PATENT_INDEPENDENCE_UNRESOLVED:
        assert nd.claim_syntheses[0].type_summaries[0].full_overlap_independent_units == 0


def test_phase2i_run_round_trips_through_serialization(world):
    nd = world[1].active_research_run.novelty_differentiation
    again = NoveltyDifferentiationRun.model_validate_json(nd.model_dump_json())
    assert again == nd


def test_phase2i_mutates_nothing_upstream(world):
    before, after = world
    old, new = before.active_research_run, after.active_research_run
    for field in ("patent_prior_art", "product_prior_art", "open_source_prior_art", "claim_sufficiency",
                  "claim_evidence_scoring", "claim_evidence_alignment", "evidence_extraction"):
        assert getattr(new, field) == getattr(old, field), field
    assert before.project.model_dump_json() == after.project.model_dump_json()
    assert old.novelty_differentiation is None and new.novelty_differentiation is not None
    assert not new.is_terminal


def test_a_replayed_graph_does_not_duplicate_comparisons(world):
    before, after = world
    model = ScriptedNoveltyModel({"C-001": CLAIM}, SCRIPT)
    again = run_phase2i(after, model.provider())
    assert again.active_research_run.novelty_differentiation == after.active_research_run.novelty_differentiation
    assert not model.calls


def test_phase2i_graph_wires_only_its_own_nodes() -> None:
    from src.graph.persistence import build_checkpointer
    from src.graph.phase2i_graph import FORBIDDEN_NODES, PHASE_2I_NODE_SEQUENCE, build_phase2i_novelty_differentiation_graph
    from src.graph.registry import PRODUCTION_NODE_ORDER, NodeId

    wired = set(build_phase2i_novelty_differentiation_graph(build_checkpointer()).get_graph().nodes)
    assert not {n.value for n in FORBIDDEN_NODES} & wired
    assert {n.value for n in PHASE_2I_NODE_SEQUENCE} <= wired
    order = list(PRODUCTION_NODE_ORDER)
    assert order.index(NodeId.FINALIZE_NOVELTY_DIFFERENTIATION) < order.index(NodeId.NOVELTY)


def test_no_synthesis_or_summary_type_can_hold_a_verdict_or_score() -> None:
    from src.schemas import novelty_differentiation as m

    forbidden = {"novelty_score", "novelty_probability", "score", "probability", "confidence", "verdict",
                 "novel", "patentable", "anticipated", "pass_fail", "rank", "percentage"}
    for name in ("ClaimDifferentiationSynthesis", "ProjectDifferentiationSummary", "ClaimCandidateComparison",
                 "ComparisonVector", "NoveltyDifferentiationRun"):
        assert not forbidden & set(getattr(m, name).model_fields), name
    assert not {"NOVEL", "NOT_NOVEL", "ANTICIPATED", "PATENTABLE", "UNPATENTABLE", "INVALID"} & set(
        m.ClaimTechnicalPosture.__members__
    )


# ---------------------------------------------------------------------------
# Regression and integration tests found by the Gold eval and the audit
# ---------------------------------------------------------------------------


def _case(category: str, lang: str = "en"):
    from src.evals.novelty_differentiation.dataset import load_cases

    return next(c for c in load_cases() if category in c.categories and c.language == lang)


def test_a_leaked_system_prompt_is_refused_and_never_persisted() -> None:
    """Regression: the injection gate found that a rejected system-prompt
    disclosure was being stored in the rejection ledger."""
    import json

    from src.evals.novelty_differentiation.runner import _prompt_lines, run_case

    result = run_case(_case("s-prompt-injection-inert"))
    assert result.error is None
    blob = json.dumps(result.ctx.d, ensure_ascii=False).casefold()
    assert not any(line in blob for line in _prompt_lines())
    reasons = {r["reason"] for c in result.ctx.d["comparisons"] for r in c["rejected_anchors"]}
    assert "SYSTEM_PROMPT_DISCLOSURE" in reasons
    assert "[redacted: system prompt disclosure]" in blob
    assert result.gates["prompt_injection_followed"] == (0, result.gates["prompt_injection_followed"][1])


@pytest.mark.parametrize("lang", ["en", "ar", "mixed"])
def test_instruction_like_candidate_text_is_admissible_source_data(lang: str) -> None:
    from src.evals.novelty_differentiation.runner import run_case

    case = _case("s-prompt-injection-defense-project-instruction-text-admissible", lang)
    result = run_case(case)
    assert result.error is None and not result.failures
    # The authored excerpt (read from the case data) is the instruction-like
    # candidate sentence; it must be accepted as an exact anchor, not refused.
    wanted = case.script["comparisons"][0]["judgments"][1]["evidence"][0]["excerpt"]
    anchors = [a for c in result.ctx.d["comparisons"] for a in c["anchors"]]
    assert any(a["excerpt"] == wanted for a in anchors)
    assert not any(c["rejected_anchors"] for c in result.ctx.d["comparisons"])


def test_a_novelty_run_cannot_be_bound_to_another_runs_subrun(world) -> None:
    before, after = world
    run = after.active_research_run
    from uuid import uuid4

    from src.schemas.research import ResearchRun

    tampered = run.novelty_differentiation.model_copy(update={"patent_run_id": uuid4()})
    with pytest.raises(ValueError, match="foreign prior-art subrun|different patent run"):
        ResearchRun.model_validate({**dict(run), "novelty_differentiation": tampered})


def test_a_populated_phase2i_state_survives_a_checkpoint_round_trip(world) -> None:
    """LangGraph silently blocks unregistered types on deserialization; a
    populated Phase 2I run must round-trip with no registration gap."""
    from src.graph.persistence import audit_serde_registration, build_serializer, unregistered_type_keys

    _, after = world
    serde = build_serializer()
    with audit_serde_registration() as events:
        restored = serde.loads_typed(serde.dumps_typed(after))
    assert unregistered_type_keys(events) == set()
    assert restored.active_research_run.novelty_differentiation == after.active_research_run.novelty_differentiation
