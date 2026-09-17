"""Phase 2E claim-sufficiency graph.

A dedicated branch graph, following the Phase 2C/2D shape exactly. It consumes
a research run that already carries a terminal, complete Phase 2D alignment
run, and it stops at auditable claim-level sufficiency assessments.

Execution path::

    START
      -> LOAD_SUFFICIENCY_RUN --------(no open run)----------------> END
      -> VALIDATE_SUFFICIENCY_INPUT          claims, evidence, sources present?
      -> BUILD_INDEPENDENCE_GROUPS           canonical identity; duplicate collapse
      -> BUILD_EVIDENCE_WEIGHT_PROFILES      multi-dimensional, no scalar score
      -> BUILD_CLAIM_COMPONENT_INVENTORY     complete material component set
      -> AGGREGATE_CLAIM_COMPONENT_COVERAGE  every inventory component
      -> APPLY_SUFFICIENCY_POLICY            SUFFICIENCY-POLICY-V1, deterministic
      -> FINALIZE_CLAIM_SUFFICIENCY          terminal status; the run stays open
      -> END

**No model call.** There is no provider key for this graph and no classifier
node in the sequence: Phase 2E is deterministic by architecture (section 16).
That is why graph construction here needs neither credentials nor a fake
provider, and why an identical input produces an identical assessment.

**Completeness before sufficiency.** ``BUILD_CLAIM_COMPONENT_INVENTORY`` runs
before coverage is aggregated, so the denominator is settled from the claim's
own text before any verdict is formed. A full-sufficiency outcome over an
inventory that is not ``COMPLETE`` is refused by the assessment schema itself,
not only by the policy node (ADR-016).

**No later phase.** ``SCORING``, ``TRUST_GATE``, ``RED_TEAM``, ``NOVELTY`` and
the rest are listed in ``FORBIDDEN_NODES`` so a test can assert their absence
rather than trusting review. A sufficiency posture is not a score and not a
trust verdict (ADR-015).

Every node guards on ``claim_sufficiency.is_terminal``, so once
``LOAD_SUFFICIENCY_RUN`` marks the run terminal (Phase 2D not ready, incomplete,
or carrying no verified alignment), every downstream node is a no-op rather
than a special routing case.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.persistence import build_checkpointer
from src.graph.registry import NodeId
from src.graph.sufficiency_nodes import (
    aggregate_claim_component_coverage,
    apply_sufficiency_policy,
    build_claim_component_inventory,
    build_evidence_weight_profiles,
    build_independence_group_set,
    finalize_claim_sufficiency,
    load_sufficiency_run,
    validate_sufficiency_input,
)
from src.graph.workflow_state import EvaluationGraphState

PHASE_2E_GRAPH_NAME = "phase2e_claim_sufficiency"

PHASE_2E_NODE_SEQUENCE: tuple[NodeId, ...] = (
    NodeId.LOAD_SUFFICIENCY_RUN,
    NodeId.VALIDATE_SUFFICIENCY_INPUT,
    NodeId.BUILD_INDEPENDENCE_GROUPS,
    NodeId.BUILD_EVIDENCE_WEIGHT_PROFILES,
    NodeId.BUILD_CLAIM_COMPONENT_INVENTORY,
    NodeId.AGGREGATE_CLAIM_COMPONENT_COVERAGE,
    NodeId.APPLY_SUFFICIENCY_POLICY,
    NodeId.FINALIZE_CLAIM_SUFFICIENCY,
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
    }
)
"""Stages Phase 2E must not perform. A test asserts none is wired in."""

_NODE_FUNCTIONS = {
    NodeId.LOAD_SUFFICIENCY_RUN: load_sufficiency_run,
    NodeId.VALIDATE_SUFFICIENCY_INPUT: validate_sufficiency_input,
    NodeId.BUILD_INDEPENDENCE_GROUPS: build_independence_group_set,
    NodeId.BUILD_EVIDENCE_WEIGHT_PROFILES: build_evidence_weight_profiles,
    NodeId.BUILD_CLAIM_COMPONENT_INVENTORY: build_claim_component_inventory,
    NodeId.AGGREGATE_CLAIM_COMPONENT_COVERAGE: aggregate_claim_component_coverage,
    NodeId.APPLY_SUFFICIENCY_POLICY: apply_sufficiency_policy,
    NodeId.FINALIZE_CLAIM_SUFFICIENCY: finalize_claim_sufficiency,
}


def _after_load(state: EvaluationGraphState) -> str:
    """Continue only when there is an active research run to work from."""
    run = state.active_research_run
    if run is None:
        return END
    return NodeId.VALIDATE_SUFFICIENCY_INPUT.value


def build_phase2e_claim_sufficiency_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the Phase 2E graph. No model provider is needed or accepted."""
    builder: StateGraph = StateGraph(EvaluationGraphState)
    for node in PHASE_2E_NODE_SEQUENCE:
        builder.add_node(node.value, _NODE_FUNCTIONS[node])

    builder.add_edge(START, NodeId.LOAD_SUFFICIENCY_RUN.value)
    builder.add_conditional_edges(
        NodeId.LOAD_SUFFICIENCY_RUN.value,
        _after_load,
        {
            NodeId.VALIDATE_SUFFICIENCY_INPUT.value: (
                NodeId.VALIDATE_SUFFICIENCY_INPUT.value
            ),
            END: END,
        },
    )
    for source, target in zip(PHASE_2E_NODE_SEQUENCE[1:], PHASE_2E_NODE_SEQUENCE[2:]):
        builder.add_edge(source.value, target.value)
    builder.add_edge(NodeId.FINALIZE_CLAIM_SUFFICIENCY.value, END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else build_checkpointer(),
        name=PHASE_2E_GRAPH_NAME,
    )


__all__ = [
    "FORBIDDEN_NODES",
    "PHASE_2E_GRAPH_NAME",
    "PHASE_2E_NODE_SEQUENCE",
    "build_phase2e_claim_sufficiency_graph",
]
