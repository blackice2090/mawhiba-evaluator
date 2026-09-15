# ADR-001 — LangGraph owns workflow execution; ProjectState stays canonical

**Status:** Accepted
**Date:** 2026-09-13
**Phase:** 1A
**Supersedes:** none
**Related:** `docs/phase1a_workflow.md`, `docs/data_contracts.md`, architecture sections 4, 6, 25, 28, 29

---

## Context

The Phase 0 contracts gave the system one canonical domain model, `ProjectState`,
with referential integrity enforced across the whole record graph. Phase 1A adds
an execution engine on top of it.

Two questions had to be settled before any node was written:

1. Which component owns workflow execution, checkpointing and resumption?
2. Where does the truth about a project live once a workflow engine is in the
   picture?

The second question is the dangerous one. Workflow engines want their own state,
and it is easy to end up with the engine's state and the domain's state both
claiming to describe the project — at which point "why did you give this
judgement?" becomes unanswerable, because the answer depends on which copy you
read.

---

## Decision

**LangGraph owns workflow execution and checkpointing.**

**The Phase 0 `ProjectState` remains the single canonical domain state.**

Concretely:

* `EvaluationGraphState` (`src/graph/workflow_state.py`) is the LangGraph channel
  state. It carries `project: ProjectState` plus execution bookkeeping only.
* It copies **no** ProjectState field. A test asserts the two models share no
  field name, and the run-level timestamps are named `run_started_at` /
  `run_updated_at` precisely so they cannot be confused with
  `ProjectState.updated_at`.
* Nothing outside `src/workflow/patches.py` writes human input into
  `ProjectState`.
* Graph construction depends on the abstract `BaseCheckpointSaver`, never on a
  concrete saver.

---

## Why LangGraph

Architecture section 4 already names LangGraph as the workflow owner, with the
rule that only one runtime manages state in v1. Phase 1A confirms that choice
against what the system actually needs:

**Persistence.** Every superstep is checkpointed. An evaluation that spans
research branches, a human clarification and a scoring pass cannot be a single
in-process call; it needs durable resumable state.

**Interruption.** Architecture section 25 defines five human-interrupt conditions
(H1-H5). LangGraph's `interrupt()` / `Command(resume=...)` implements them
natively against the checkpoint, rather than requiring a hand-rolled suspend
protocol.

**Deterministic routing.** Conditional edges are pure functions of state, so
routing can be unit-tested without executing the graph. This matters
disproportionately here: the architecture's guarantees are mostly about
*refusing* to proceed (novelty gating, trust-gate blockers), and a refusal path
that cannot be tested cannot be trusted.

**Fault recovery.** Retries, per-node error handling and state inspection come
from the engine instead of being reinvented per node.

**Avoiding competing canonical state models.** This is the decisive one. A single
owner for *execution* is what makes a single owner for *truth* possible. If
LangGraph and some other orchestrator both managed state, the domain model would
inevitably be duplicated into whichever one happened to be authoritative at a
given step.

### Why not the alternatives

* **A second orchestrator inside nodes** (OpenAI Agents SDK, or similar) — the
  architecture explicitly forbids mixing orchestrators in v1. Two state owners
  multiply debugging cost without buying anything Phase 1A needs.
* **A hand-rolled state machine** — would mean reimplementing checkpointing,
  resume and interrupt, the three things most likely to contain subtle bugs.
* **Flattening ProjectState into graph channels** — would let the engine's
  serialization shape dictate the domain model, and would discard the Phase 0
  cross-record validation that only runs on a whole `ProjectState`.

---

## Consequences

**Positive**

* One answer to "what is true about this project?", at `state.project`.
* Phase 0 validators keep running unchanged; the workflow layer adapted to the
  domain contracts rather than the reverse.
* Human input has exactly one entry point, allowlisted and validated.
* Node replay after an interrupt is handled structurally, by channel reducers,
  rather than by each node remembering to be careful.

**Negative / accepted costs**

* Every model and enum crossing the checkpoint boundary must be registered with
  the serializer. LangGraph matches exact `(module, type name)` pairs and
  **silently blocks** unregistered types in strict mode. *Superseded in Phase
  1A.1:* registration is now derived by recursive type-graph traversal from the
  canonical roots, backed by a package-completeness test and a serde-event audit.
* `ProjectState` is re-validated on each pass through `VALIDATE_PROJECT_STATE`.
  Correct, and currently cheap; it will need measuring once the state carries
  hundreds of sources and claims.
* Node progress was initially tracked in two places:
  `EvaluationGraphState.completed_nodes` and the Phase 0 `ProjectState.workflow`
  block. *Resolved in Phase 1A.1 by ADR-002:* the duplicated block was removed
  rather than synchronized, leaving `EvaluationGraphState` as the sole owner of
  workflow execution state.

---

## Current persistence

**`InMemorySaver`**, built by `build_checkpointer(CheckpointerKind.IN_MEMORY)`
with a serializer that registers this project's checkpointed types.

Used for Phase 1A tests and local development.

```text
InMemorySaver validates checkpoint semantics,
not durable production persistence.
```

It proves that state is written after each superstep, restored on resume,
isolated per thread, and fully serializable. It proves nothing about durability
across process restarts, concurrent writers or crash recovery.

---

## Future

A persistent **PostgreSQL checkpointer**, injected through the same
`build_checkpointer()` factory. `CheckpointerKind.POSTGRES` is already declared so
the injection point is visible in the contract; requesting it today raises a
structured `CHECKPOINTER_UNAVAILABLE` error rather than silently degrading to an
in-memory saver — a silent downgrade in production would lose every checkpoint
without anyone noticing.

**PostgreSQL is not implemented now.** It arrives with the database work in a
later phase (architecture section 28), together with durability tests that
`InMemorySaver` cannot provide.

---

## Compliance

Phase 0 contracts and validators were not modified or relaxed to accommodate
LangGraph. All pre-existing tests passed unchanged at the time of this decision.

**Amended by ADR-002 (Phase 1A.1)** on the question of workflow state ownership.
