# ADR-002 — Workflow execution state belongs to EvaluationGraphState alone

**Status:** Accepted
**Date:** 2026-09-13
**Phase:** 1A.1 (Workflow Hardening)
**Amends:** ADR-001, and architecture section 6
**Related:** `docs/phase1a_workflow.md`, `docs/data_contracts.md`

---

## Context

The original architecture (section 6) placed an operational `workflow` block
inside the canonical `PROJECT_STATE`:

```json
"workflow": {
  "completed_nodes": [],
  "pending_nodes": [],
  "blocked_reason": null
}
```

That was written before an orchestrator was chosen. Phase 1A then introduced
`EvaluationGraphState` as the LangGraph channel state, which necessarily tracks
the same things — completed nodes, the current node, interrupt state, workflow
errors — because that is what an execution engine has to track in order to
checkpoint and resume.

The result was two mutable structures describing the same runtime facts.
Phase 1A shipped with only one of them populated and logged the divergence as
technical debt. That was acceptable while no node did real work; it is not
acceptable before intelligent extraction begins, because once nodes start
writing to `ProjectState` the two copies will drift, and "which nodes have
actually run?" becomes a question with two answers.

The usual fix — synchronize them — is the wrong one. Synchronization does not
remove the second source of truth, it just adds code whose job is to hide that
there is one, and it fails silently the moment someone writes to one copy
without going through the sync.

---

## Decision

**`EvaluationGraphState` exclusively owns workflow execution state.**

**`ProjectState` exclusively owns project and evaluation domain state.**

The duplicated `WorkflowBlock` has been **removed** from `ProjectState`. No
synchronization logic was written, and no second mutable workflow projection
remains inside the canonical project model.

```text
ProjectState            =  project / evaluation truth
EvaluationGraphState    =  workflow / runtime truth
```

### Ownership split

| Owned by `EvaluationGraphState` | Owned by `ProjectState` |
|---|---|
| workflow status | project identity |
| current node | problem |
| completed nodes | solution |
| pending nodes | technical content |
| node execution attempts | methodology |
| node execution records | experiments, results |
| interrupt state | claims, sources, evidence |
| workflow errors | prior art, novelty, gap |
| run identifiers (`run_id`, `thread_id`) | risks, scores |
| checkpoint / resume execution metadata | missing critical information, contradictions |
| | operating mode, domain information |

The split is enforced by test, not only by convention: `ProjectState` must expose
none of the workflow execution fields, no nested block of `ProjectState` may
re-introduce them under a different name, and the two models must share no field
name at all.

---

## Consequences

**Positive**

* **No synchronization problem.** There is nothing to synchronize, so there is no
  sync to forget, mis-order, or partially apply.
* **No workflow divergence.** One writer, one reader, one answer.
* **Cleaner checkpoint semantics.** A checkpoint captures runtime state in
  `EvaluationGraphState` and domain state in `ProjectState`, with no overlap and
  therefore no possibility of the two disagreeing inside a single checkpoint.
* **Project snapshots stay independent of orchestration.** A `ProjectState`
  serialized today remains meaningful if the orchestrator is ever replaced,
  upgraded, or run differently. Versioned project snapshots (architecture
  section 29) no longer carry LangGraph-shaped execution residue.
* **Evaluation and execution stay conceptually separate**, matching the existing
  separation of `EvaluationStatus` (how well evidence supports a judgement) from
  `WorkflowStatus` (whether the machine is running).

**Negative / accepted costs**

* **UI progress must derive from workflow state.** A dashboard showing "node 7 of
  20" reads `EvaluationGraphState`, or a dedicated persisted workflow view built
  from it — not `ProjectState`. A consumer holding only a project snapshot cannot
  tell how far the run got, which is correct: that is not a property of the
  project.
* **A future workflow-history view is additional work.** Serving progress over an
  API will need either the live graph state or a projection built for that
  purpose. Deferred, and recorded as such.
* The architecture document required an authorized amendment (section 6), since
  it was the original source of the duplicated field.

---

## Alternatives rejected

**Synchronize the two copies.** Rejected above: it preserves the second source of
truth and adds a silent failure mode.

**Make `ProjectState.workflow` read-only / derived.** Better, but a derived copy
inside a serialized snapshot still ages: the snapshot would assert a node
progress that was true only at write time, and readers cannot tell. It also
re-couples the domain model to the orchestrator's node vocabulary.

**Move everything into `ProjectState` and drop the graph state.** Not possible:
LangGraph requires a channel state, and forcing the domain model into that role
would let the engine's serialization and reducer requirements dictate the shape
of the canonical evaluation record.

---

## Preserved decisions

This ADR changes state ownership only. Every Phase 1A decision stands unchanged:
LangGraph remains the workflow owner; `InMemorySaver` remains the development and
test saver; there is no silent production fallback from PostgreSQL to memory;
`thread_id` remains opaque and PII-free; `run_id` and `thread_id` remain
separate; resume still goes through the validated `ProjectPatch` boundary, which
still cannot write claims, scores, trust results or any evaluation conclusion;
`PHASE_1A_DEMO_GATE` remains demo-only; completion tracking remains replay-safe.
