"""Phase 2F claim-evidence scoring graph.

A dedicated branch graph, following the Phase 2C/2D/2E shape exactly. It
consumes a research run that already carries a terminal, ``COMPLETED`` Phase 2E
sufficiency run, and it stops at auditable per-claim evidence scorecards.

Execution path::

    START
      -> LOAD_SCORING_RUN ------------(no open run)----------------> END
      -> VALIDATE_SCORING_INPUT             claims present? assessments trusted?
      -> DERIVE_COMPONENT_SCORE_TRACES      every inventory component, both ways
      -> CALCULATE_SUPPORT_CHANNEL          coverage + corroboration + directness
      -> CALCULATE_CONTRADICTION_CHANNEL    its own channel, never netted
      -> DERIVE_SCORE_RELIABILITY           posture beside the score, not in it
      -> APPLY_SCORE_DISPOSITION_POLICY     may a primary scalar be issued?
      -> BUILD_CLAIM_EVIDENCE_SCORECARDS    one card per scored claim
      -> FINALIZE_CLAIM_EVIDENCE_SCORING    terminal status; the run stays open
      -> END

**No model call.** There is no provider key for this graph and no classifier
node in the sequence: a model-generated score is forbidden, and Phase 2F is
deterministic by architecture (section 19). That is why graph construction needs
neither credentials nor a fake provider, and why identical Phase 2E state
produces byte-identical scorecards.

**Two channels, computed separately, in that order.** Support and contradiction
are separate nodes rather than one "compute indices" step, so the graph itself
shows that neither is derived from the other and no node ever holds a net
figure (section 8).

**Disposition after both channels.** Whether a single primary scalar may be
issued depends on the *conflict* between the channels, so the policy cannot run
until both exist. A graph that scored and then checked would have already
produced the number it was meant to withhold.

**No later phase.** ``SCORING``, ``TRUST_GATE``, ``RED_TEAM``, ``NOVELTY``,
``REPORT_GENERATOR`` and the rest are listed in ``FORBIDDEN_NODES`` so a test
can assert their absence rather than trusting review. ``SCORING`` in particular:
a claim evidence index is not a project rubric score and not an official
Mawhiba/Ibdaa judging score, and the boundary is structural (section 28,
ADR-017).

Every node guards on ``claim_evidence_scoring.is_terminal``, so once
``LOAD_SCORING_RUN`` marks the run terminal (Phase 2E not ready, or carrying no
assessment), every downstream node is a no-op rather than a special routing
case.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.scoring_nodes import (
    apply_score_disposition_policy,
    build_claim_evidence_scorecards,
    calculate_contradiction_channel,
    calculate_support_channel,
    derive_component_score_traces,
    derive_score_reliability,
    finalize_claim_evidence_scoring,
    load_scoring_run,
    validate_scoring_input,
)
from src.graph.workflow_state import EvaluationGraphState

PHASE_2F_GRAPH_NAME = "phase2f_claim_evidence_scoring"

PHASE_2F_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_SCORING_RUN,
    NodeId.VALIDATE_SCORING_INPUT,
    NodeId.DERIVE_COMPONENT_SCORE_TRACES,
    NodeId.CALCULATE_SUPPORT_CHANNEL,
    NodeId.CALCULATE_CONTRADICTION_CHANNEL,
    NodeId.DERIVE_SCORE_RELIABILITY,
    NodeId.APPLY_SCORE_DISPOSITION_POLICY,
    NodeId.BUILD_CLAIM_EVIDENCE_SCORECARDS,
    NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING,
)

FORBIDDEN_NODES: frozenset[NodeId] = frozenset(
    {
        NodeId.NOVELTY,
        NodeId.GAP,
        NodeId.SCORING,
        NodeId.TRUST_GATE,
        NodeId.FINAL_VERIFIER,
        NodeId.CLOSEST_PRIOR_ART,
        NodeId.RED_TEAM,
        NodeId.REPORT_GENERATOR,
        NodeId.CONTRADICTION_DETECTION,
        NodeId.CLAIM_EVIDENCE,
        NodeId.METHODOLOGY,
        NodeId.EXPERIMENT_REVIEW,
    }
)
"""Stages Phase 2F must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_SCORING_RUN: load_scoring_run,
    NodeId.VALIDATE_SCORING_INPUT: validate_scoring_input,
    NodeId.DERIVE_COMPONENT_SCORE_TRACES: derive_component_score_traces,
    NodeId.CALCULATE_SUPPORT_CHANNEL: calculate_support_channel,
    NodeId.CALCULATE_CONTRADICTION_CHANNEL: calculate_contradiction_channel,
    NodeId.DERIVE_SCORE_RELIABILITY: derive_score_reliability,
    NodeId.APPLY_SCORE_DISPOSITION_POLICY: apply_score_disposition_policy,
    NodeId.BUILD_CLAIM_EVIDENCE_SCORECARDS: build_claim_evidence_scorecards,
    NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING: finalize_claim_evidence_scoring,
}


def _after_load(state: EvaluationGraphState) -> str:
    """Continue only when there is an active research run to work from."""
    run = state.active_research_run
    if run is None:
        return END
    return NodeId.VALIDATE_SCORING_INPUT.value


def build_phase2f_claim_scoring_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2F graph. No model provider is needed or accepted."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2F_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_SCORING_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_SCORING_RUN.value,
        _after_load,
        {
            NodeId.VALIDATE_SCORING_INPUT.value: NodeId.VALIDATE_SCORING_INPUT.value,
            END: END,
        },
    )
    for source, target in zip(PHASE_2F_NODE_SEQUENCE[1:], PHASE_2F_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_CLAIM_EVIDENCE_SCORING.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2F_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2F_GRAPH_NAME",
    "PHASE_2F_NODE_SEQUENCE",
    "build_phase2f_claim_scoring_graph",
]
