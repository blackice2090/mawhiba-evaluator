"""Phase 2J graph, run binding, no-new-search, checkpoint and upstream immutability."""

from __future__ import annotations

import ast
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.evals.research_engineering_gap.fixtures import CLAIM, CLAIMS, ND_SCRIPT, PATENT, script
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.graph.phase2j_graph import FORBIDDEN_NODES, PHASE_2J_NODE_SEQUENCE
from src.graph.registry import NodeId
from src.research.gap import pipeline as gp
from src.schemas.common import ProjectType
from src.schemas.gap_assessment import (
    GapAssessmentBounds,
    GapAssessmentRun,
    GapIssueCode,
    GapPosture,
    GapRunStatus,
    InsufficientReason,
)
from src.schemas.research import ResearchRun

ROOT = Path(__file__).resolve().parents[1]
GAP_SOURCES = [*sorted((ROOT / "src" / "research" / "gap").glob("*.py")),
               ROOT / "src" / "graph" / "gap_nodes.py", ROOT / "src" / "graph" / "phase2j_graph.py"]


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-908", CLAIMS, patent=PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def _provider():
    return ScriptedGapModel({"C-001": CLAIM}, script()).provider()


def _stages(run: ResearchRun, claims, provider, until: str = "counterevidence") -> GapAssessmentRun:
    now = datetime.now(UTC)
    gap = gp.open_gap_run(run, claims, ProjectType.UNKNOWN, GapAssessmentBounds(), now)
    gap = gp.inventory_stage(gap, run)
    gap = gp.extraction_stage(gap, run, claims, provider, None)
    gap = gp.linkage_stage(gap, run, claims, provider, None)
    return gp.counterevidence_stage(gap, run, claims, provider, None)


def test_graph_wires_no_forbidden_node():
    assert not FORBIDDEN_NODES & set(PHASE_2J_NODE_SEQUENCE)
    assert NodeId.GAP in FORBIDDEN_NODES and NodeId.METHODOLOGY in FORBIDDEN_NODES
    assert NodeId.SCORING in FORBIDDEN_NODES and NodeId.NOVELTY in FORBIDDEN_NODES
    assert NodeId.EXECUTE_PATENT_SEARCH in FORBIDDEN_NODES and NodeId.EXECUTE_OPEN_SOURCE_SEARCH in FORBIDDEN_NODES
    assert [n.value for n in PHASE_2J_NODE_SEQUENCE][0] == "LOAD_GAP_ASSESSMENT_RUN"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    return names | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


def test_no_gap_module_imports_a_connector_a_network_client_or_scoring():
    forbidden = ("httpx", "requests", "socket", "urllib", "scoring", "connectors", "openalex", "consensus",
                 "semantic_scholar", "epo", "brave", "github", "safe_fetch", "discovery")
    for path in GAP_SOURCES:
        for module in _imports(path):
            if module.startswith("src.schemas."):
                continue  # pure contracts and shared constants; connectors live under src.research.*
            assert not any(f in module.casefold() for f in forbidden), (path.name, module)


def test_the_run_cannot_express_a_search_or_a_score():
    assert GapAssessmentRun.model_fields["external_search_calls"].annotation.__args__ == (0,)
    with pytest.raises(Exception):
        GapAssessmentRun(gap_run_id=CLAIM_UUID, research_run_id=CLAIM_UUID, started_at=datetime.now(UTC),
                         external_search_calls=1)


CLAIM_UUID = __import__("uuid").uuid4()


def test_the_whole_pipeline_runs_with_the_network_disabled(upstream, monkeypatch):
    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("Phase 2J attempted a network call")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    gap = run_phase2j(upstream, _provider()).active_research_run.research_engineering_gap
    assert gap.status is GapRunStatus.COMPLETED and gap.external_search_calls == 0


def test_a_populated_phase2j_state_survives_a_checkpoint_round_trip(upstream):
    from src.graph.persistence import audit_serde_registration, build_serializer, unregistered_type_keys

    after = run_phase2j(upstream, _provider())
    serde = build_serializer()
    with audit_serde_registration() as events:
        restored = serde.loads_typed(serde.dumps_typed(after))
    assert unregistered_type_keys(events) == set()
    assert restored.active_research_run.research_engineering_gap == after.active_research_run.research_engineering_gap


def test_the_research_run_refuses_a_gap_run_bound_to_another_run(upstream):
    run = upstream.active_research_run
    gap = gp.open_gap_run(run, list(upstream.project.claims), ProjectType.UNKNOWN, GapAssessmentBounds(),
                          datetime.now(UTC))
    foreign = gap.model_copy(update={"research_run_id": __import__("uuid").uuid4()})
    with pytest.raises(ValueError, match="different research run"):
        ResearchRun.model_validate({**dict(run), "research_engineering_gap": foreign})
    wrong_nd = gap.model_copy(update={"nd_run_id": __import__("uuid").uuid4()})
    with pytest.raises(ValueError, match="different Phase 2I run"):
        ResearchRun.model_validate({**dict(run), "research_engineering_gap": wrong_nd})


def test_a_mutated_upstream_subrun_downgrades_the_whole_run(upstream):
    run, claims = upstream.active_research_run, list(upstream.project.claims)
    gap = _stages(run, claims, _provider())
    tampered_nd = run.novelty_differentiation.model_copy(update={"model_comparisons_performed": 999})
    tampered = run.model_copy(update={"novelty_differentiation": tampered_nd})
    final = gp.finalize_stage(gp.project_stage(gp.synthesis_stage(gap, run)), tampered, claims, datetime.now(UTC))
    assert final.status is GapRunStatus.INSUFFICIENT_INPUT and final.is_terminal
    assert not final.hypotheses
    assert all(InsufficientReason.UPSTREAM_MUTATED in a.insufficient_reasons for a in final.claim_assessments)
    assert any(e.code is GapIssueCode.UPSTREAM_MUTATED for e in final.errors)


def test_a_claim_changed_after_binding_is_no_longer_assessed(upstream):
    run, claims = upstream.active_research_run, list(upstream.project.claims)
    gap = gp.synthesis_stage(_stages(run, claims, _provider()), run)
    assert gap.claim_assessments[0].posture is GapPosture.SUPPORTED_WITHIN_BOUNDS or gap.hypotheses
    edited = [claims[0].model_copy(update={"claim": claims[0].claim + " and a battery"})]
    final = gp.finalize_stage(gp.project_stage(gap), run, edited, datetime.now(UTC))
    assert final.status is GapRunStatus.COMPLETED
    (assessment,) = final.claim_assessments
    assert assessment.posture is GapPosture.INSUFFICIENT_INPUT
    assert InsufficientReason.CLAIM_TEXT_HASH_MISMATCH in assessment.insufficient_reasons
    assert not final.hypotheses


def test_stages_never_repeat_a_model_call(upstream):
    run, claims = upstream.active_research_run, list(upstream.project.claims)
    model = ScriptedGapModel({"C-001": CLAIM}, script())
    provider = model.provider()
    gap = _stages(run, claims, provider)
    calls = len(model.calls)
    again = gp.counterevidence_stage(gp.linkage_stage(gp.extraction_stage(gap, run, claims, provider, None),
                                                      run, claims, provider, None), run, claims, provider, None)
    assert len(model.calls) == calls and again == gap


def test_the_run_wide_model_call_bound_is_honoured(upstream):
    run, claims = upstream.active_research_run, list(upstream.project.claims)
    model = ScriptedGapModel({"C-001": CLAIM}, script())
    now = datetime.now(UTC)
    gap = gp.open_gap_run(run, claims, ProjectType.UNKNOWN, GapAssessmentBounds(max_model_calls=0), now)
    gap = gp.extraction_stage(gp.inventory_stage(gap, run), run, claims, model.provider(), None)
    assert not model.calls
    assert InsufficientReason.MODEL_CALL_BOUND_REACHED in gap.drafts[0].insufficient_reasons


def test_a_claim_edited_before_binding_is_unbound_with_a_stated_reason(upstream):
    run, claims = upstream.active_research_run, list(upstream.project.claims)
    edited = [claims[0].model_copy(update={"claim": claims[0].claim + " and a battery"})]
    gap = gp.open_gap_run(run, edited, ProjectType.UNKNOWN, GapAssessmentBounds(), datetime.now(UTC))
    assert gap.drafts[0].insufficient_reasons == [InsufficientReason.CLAIM_TEXT_HASH_MISMATCH]
    final = gp.finalize_stage(gp.project_stage(gp.synthesis_stage(gap, run)), run, edited, datetime.now(UTC))
    assert final.claim_assessments[0].posture is GapPosture.INSUFFICIENT_INPUT and not final.hypotheses
