# Phase 1A — LangGraph Skeleton, State Persistence, Node Contracts

**Status:** Implemented
**Scope:** Workflow infrastructure only. No evaluation intelligence.
**Architecture source:** `docs/mawhiba_agent_system_architecture_v1.md`
**Contracts:** `docs/data_contracts.md`
**Decision record:** `docs/adr/ADR-001-langgraph-state-and-persistence.md`

---

## 1. Purpose

Phase 1A proves the workflow machinery is correct **before** any model call,
search provider or scoring logic is added. Once nodes start calling LLMs, a
checkpointing or replay bug becomes extremely hard to isolate from a reasoning
bug. So the infrastructure is proven first, in a harness that has no
intelligence at all.

What is proven here:

1. A LangGraph workflow compiles.
2. A run starts and carries canonical project state across node boundaries.
3. Checkpoints persist and can be read back.
4. The same thread resumes.
5. Execution interrupts when human input is required.
6. Resume applies the answer and the graph completes.
7. Routing is conditional and deterministic.
8. Node completion is tracked without duplication.
9. Node replay after an interrupt causes no duplicate side effects.
10. Node input/output contracts are stable and serializable.
11. The whole suite runs with no LLM, no network, no credentials.

---

## 2. The Phase 1A graph

`src/graph/phase1a_graph.py` -> `build_phase1a_graph()`

**This is not the production evaluation graph.** It is named
`phase1a_infrastructure_harness` so it cannot be confused with one. The
production graph is built from `NodeId` in a later phase.

```text
START
  |
  v
INITIALIZE_RUN                 stamp run identity, status -> RUNNING
  |
  v
VALIDATE_PROJECT_STATE  --(invalid)--> END        status -> FAILED
  |
  v
CHECK_CRITICAL_INPUT           evaluate PHASE_1A_DEMO_GATE
  |
  |-- gate satisfied --------------------> MARK_READY -----> END
  |                                        status -> COMPLETED
  |
  |-- input already requested -----------> MARK_BLOCKED ---> END
  |                                        status -> FAILED
  |
  `-- fields missing --------------------> REQUEST_INPUT
                                             |
                                             | interrupt()   <-- execution stops
                                             | ...
                                             | Command(resume=...)
                                             v
                                           APPLY_INPUT --(rejected)--> END
                                             |                  status -> FAILED
                                             v
                                           VALIDATE_PROJECT_STATE
                                             v
                                           CHECK_CRITICAL_INPUT  (second pass)
                                             v
                                           MARK_READY / MARK_BLOCKED -> END
```

The cycle is bounded by `MAX_INPUT_REQUESTS` (currently 1): the graph asks once,
and if the answer still leaves the gate unmet it terminates at `MARK_BLOCKED`
rather than looping.

### PHASE_1A_DEMO_GATE

`src/graph/routing.py` requires three fields to be `KNOWN`:

* `identity.project_name`
* `problem.statement`
* `solution.description`

**This is `PHASE_1A_DEMO_GATE` and NOT the final project-intake completeness
policy.** It exists purely to drive the conditional branch and the interrupt with
a rule that depends only on Phase 0 contracts. The real policy belongs to N00/N01
and to section 24 (ask only when MISSING + CRITICAL + NOT_RETRIEVABLE_EXTERNALLY).

The gate is Zero-Assumption aware: `UNKNOWN`, `CONFLICTED` and
`INFERRED_NON_CRITICAL` all count as missing. Only a genuinely `KNOWN` value
satisfies a requirement.

---

## 3. State ownership

### ProjectState versus EvaluationGraphState

| | `ProjectState` | `EvaluationGraphState` |
|---|---|---|
| Module | `src/graph/state.py` | `src/graph/workflow_state.py` |
| Role | canonical domain state | LangGraph channel state |
| Owns | the project and its evaluation | execution bookkeeping |
| Phase | 0 | 1A |
| Lifetime | versioned, durable | one run |

There is **exactly one** canonical project state, and it lives at
`EvaluationGraphState.project`. The wrapper does not copy or shadow any
ProjectState field — a test asserts the two models share no field name at all.
This is the single most important structural rule of Phase 1A: two competing
canonical state models would make "what is actually true about this project?"
unanswerable.

The converse holds symmetrically since Phase 1A.1 (ADR-002): **`ProjectState`
carries no workflow execution state.** The operational `workflow` block that the
original architecture placed inside it has been removed rather than
synchronized — synchronization would have preserved the second source of truth
while hiding it. A UI needing progress reads `EvaluationGraphState`, or a
dedicated persisted workflow view built from it.

`EvaluationGraphState` adds only execution concerns:

```text
project                   the canonical domain state
run_id, thread_id         identity
status, current_node      lifecycle
completed_nodes           ordered, duplicate-safe
pending_nodes
node_results              NodeExecutionRecord keyed by node id
node_execution_attempts   every entry, including replays
interrupt_request         the outstanding human request
pending_input             raw, still-unvalidated resume payload
input_requests            bounds the ask/apply cycle
errors, audit_events      structured, de-duplicated
run_started_at            run-level clocks, named distinctly from
run_updated_at            ProjectState.updated_at
```

`coerce_graph_state()` is the one place that converts a LangGraph result or
checkpoint snapshot (plain dictionaries) back into the model, dropping the
`__interrupt__` channel that LangGraph adds to a result but which is not part of
the state schema.

---

## 4. run_id versus thread_id

These are **not** interchangeable.

| | `thread_id` | `run_id` |
|---|---|---|
| What it is | the LangGraph checkpoint cursor | the identity of one evaluation execution |
| Owned by | LangGraph | the domain |
| Used for | addressing a checkpoint, resuming | tracing, audit events, reporting |
| Format | `thr-<uuid>` | `UUID` |
| Lifetime | can outlive a single run | exactly one run |

A resume addresses a `thread_id`. Everything recorded about *why* a decision was
made is keyed by `run_id`. Over time one thread may carry more than one run (a
re-evaluation of the same project version), while a run is always pinned to
exactly one thread.

### thread_id safety

`new_thread_id(run_id)` produces `thr-<uuid>` — opaque, and derived from a UUID
so it can never carry PII. Student names, project titles and email addresses are
explicitly rejected by `is_safe_thread_id()`, which is asserted against a
parametrized list of such values. The id is also stable for a given `run_id`,
which keeps resume deterministic.

---

## 5. Checkpoint behavior

Checkpoints are written by LangGraph after each superstep. After an interrupt the
checkpoint holds:

* the full canonical `ProjectState` as of that moment;
* `completed_nodes` up to but **not including** the interrupting node;
* every `NodeExecutionRecord` recorded so far;
* the audit events emitted so far.

`app.get_state(config)` returns the snapshot; `snapshot.next` names the node
that will run when the thread resumes. `app.get_state_history(config)` walks the
accumulated checkpoints.

### Serialization (hardened in Phase 1A.1)

Every model and enum that crosses the checkpoint boundary must be registered with
the serializer. LangGraph matches an allowlist of exact `(module, type name)`
pairs, and an omitted type is **silently blocked** on deserialization in strict
mode — it comes back as a plain dictionary rather than raising.

Phase 1A used a hand-maintained `CHECKPOINTED_MODULES` list, which would rot the
moment someone added a schema module and forgot to list it. That mechanism has
been **removed**. Registration is now derived by recursively walking the type
graph of the canonical checkpoint roots:

```python
CHECKPOINT_ROOTS   = (EvaluationGraphState, ProjectState)
CHECKPOINTED_TYPES = discover_types_from(*CHECKPOINT_ROOTS)
```

`src/graph/type_discovery.py` traverses declared field annotations through
unions, optionals, containers, `Annotated` metadata and Pydantic generics.
Generics matter concretely: `Tracked[str]` is a real class whose `__name__` is
`"Tracked[str]"`, distinct from `Tracked`, and both must be registered.

A model newly wired into the state graph is therefore registered automatically.
Three tests close the remaining gap:

1. **Package completeness** — every Pydantic model and enum defined anywhere under
   `src` must be either checkpoint-reachable or listed in an explicit
   `NON_CHECKPOINTED_TYPES` set with a reason. A new unreachable schema fails the
   suite until someone states which it is.
2. **Stale-exclusion** — a type that later becomes reachable must leave that set.
3. **Registration audit** — a fully populated state and a complete interrupt/resume
   cycle are serialized while listening on LangGraph's public serde event hook
   (`register_serde_event_listener`), asserting zero `msgpack_blocked` events.

The audit matters because round-trip equality alone is **not** sufficient: a
blocked enum silently re-validates from its string value, so the object compares
equal while having bypassed registration. A negative-control test proves the
audit detects a deliberately removed type where equality does not.

---

## 6. Interrupt behavior

`REQUEST_INPUT` calls LangGraph's `interrupt()` with a JSON-serializable payload
built from `InterruptRequest`:

```json
{
  "type": "MISSING_CRITICAL_INFORMATION",
  "node": "REQUEST_INPUT",
  "fields": ["identity.project_name", "problem.statement", "solution.description"],
  "message": "Additional project information is required.",
  "questions": ["Provide a value for 'identity.project_name'.", "..."],
  "requested_at": "2026-09-13T13:06:48.240195Z"
}
```

The message is the **developer-facing English** form. The student presentation
layer adapts and translates it later; nothing in the workflow layer emits Arabic.

`InterruptType` covers the five human-interrupt conditions of architecture
section 25 (H1-H5); Phase 1A exercises `MISSING_CRITICAL_INFORMATION`.

---

## 7. Resume behavior

```python
app.invoke(initial_state, config)              # -> interrupt
app.invoke(Command(resume=answer), config)     # -> completes
```

Resume uses the same `thread_id` and LangGraph's supported `Command(resume=...)`
mechanism. The answer reaches `APPLY_INPUT` as `pending_input`, deliberately
typed as raw untrusted data, and is then forced through the patch boundary.

### The patch boundary

`src/workflow/patches.py` is the only way human input reaches `ProjectState`.
It is explicitly **not** a generic JSON Patch endpoint:

1. Only fields in the `PatchableField` allowlist can be set. Anything else —
   `scores`, `claims`, `trust_gate`, `project_id` — is refused with an
   `UNSUPPORTED_PATCH_FIELD` error. A human answer may fill inputs; it may never
   write evaluation conclusions.
2. Values must be non-blank strings.
3. `apply_project_patch()` deep-copies, writes through `Tracked[str].known(...)`,
   and re-validates the entire `ProjectState`. The input state is never mutated.
4. Zero-Assumption is preserved: applied values are recorded as `KNOWN` with a
   student origin. A patch carrying `AGENT_INFERENCE` origin is rejected outright,
   because inference is never knowledge.
5. Student text is stored verbatim, including Arabic. The structure around it —
   field names, statuses, origins — stays English.

Invalid input never corrupts state: it produces a structured `WorkflowError`,
the run ends `FAILED`, and the canonical project is left untouched.

---

## 8. Idempotency rule

> **A node may execute more than once. Its effects may not accumulate.**

LangGraph re-executes an interrupted node **from its first line** on resume. This
is verified behavior, not an assumption — a probe confirmed `REQUEST_INPUT`
re-entering after `Command(resume=...)`. Three protections follow.

**1. Interrupt first.** `REQUEST_INPUT` calls `interrupt()` as its first
statement. Nothing above it can run twice, because nothing is above it. A test
asserts that after the first pass the node has recorded no completion, no audit
event and no increment to `input_requests`.

**2. Replay-safe channel reducers.** Every accumulating channel in
`EvaluationGraphState` is annotated with a reducer that absorbs repetition:

| Channel | Reducer | Behavior on replay |
|---|---|---|
| `completed_nodes` | `merge_unique_ordered` | appears once, in original position |
| `node_results` | `merge_node_records` | keyed by node; record is overwritten |
| `errors` | `merge_unique_errors` | de-duplicated by `error_key` |
| `audit_events` | `merge_unique_events` | de-duplicated by deterministic `event_key` |
| `node_execution_attempts` | `append_attempts` | appended on purpose (see below) |


`AuditEvent.event_key` is derived from `(run_id, node, event_type, subject)` —
never from a timestamp or a counter — so the same event re-emitted on a replay
collapses instead of duplicating.

**3. Completion is a set; attempts are a log.** These are separate channels
because they answer different questions. After a resume in the harness graph,
`VALIDATE_PROJECT_STATE` appears **once** in `completed_nodes` and **twice** in
`node_execution_attempts`, the second entry flagged `replayed=True`. Neither
record is a lie: the node completed once, and it ran twice.

---

## 8b. Timing semantics (hardened in Phase 1A.1)

> **A human pause must never be reportable as node compute latency.**

Phase 1A carried a replayed node's `started_at` over from its first attempt, so
the recorded duration spanned the human pause. That is fixed, and the two kinds
of timing are now named so they cannot be confused.

| | `NodeAttempt` | `NodeExecutionRecord` |
|---|---|---|
| Grain | one individual execution | the node's whole lifecycle |
| Timestamps | `started_at`, `completed_at` | `first_started_at`, `last_completed_at` |
| Identity | `attempt_id` (UUID), `attempt` index, `replayed` | keyed by node, with an `attempts` count |
| Duration | `duration_ms` — **the only value valid for performance measurement** | `lifecycle_elapsed_ms` — includes the pause, by design |

Each entry into a node captures its own `started_at`. A replay never inherits the
earlier timestamp, so `NodeAttempt.duration_ms` measures that pass alone.
`NodeExecutionRecord` deliberately exposes **no** `duration_ms`: publishing that
number would invite it being read as latency when for a replayed node it spans
the human pause. The lifecycle value it does expose is named
`lifecycle_elapsed_ms` so the meaning is unmissable at the call site.

`REQUEST_INPUT` captures its attempt start *before* `interrupt()`. Reading the
clock is not a side effect, and because the line re-executes on resume the
timestamp belongs to the resumed pass. The interrupted pass commits nothing, so
exactly one attempt is recorded for that node — the resumed one.

### The injectable clock

`src/workflow/clock.py` gives the workflow layer one seam for reading time:
`SystemClock` in production, `ManualClock` in tests. `ManualClock` advances a
fixed tick per read (so timestamps are ordered and distinct with no real waiting)
and exposes `advance(seconds)` to simulate a human pause. The timing tests
simulate a 15-minute pause and assert every attempt duration stays far below it,
with **no real sleeps anywhere**. The domain layer continues to use
`src.schemas.common.utc_now` directly; this seam is for execution timing only.

`INITIALIZE_RUN` is idempotent in the same spirit — a replay keeps the existing
`thread_id` rather than minting a new one, which would orphan the checkpoint.

---

## 9. Persistence abstraction

`src/graph/persistence.py`

```python
def build_checkpointer(kind: CheckpointerKind = ...) -> BaseCheckpointSaver: ...
```

`build_phase1a_graph(checkpointer)` accepts the **abstract** `BaseCheckpointSaver`
and never constructs one inline. Graph construction is therefore decoupled from
the saver implementation, and a durable PostgreSQL saver can be injected later
without touching graph code.

`CheckpointerKind.POSTGRES` is declared so the injection point is visible in the
contract, but it is not implemented. Requesting it raises a structured
`CHECKPOINTER_UNAVAILABLE` error rather than silently degrading to memory — a
silent downgrade to an in-memory saver in production would lose every checkpoint
without anyone noticing.

### What InMemorySaver does and does not prove

```text
InMemorySaver validates checkpoint semantics,
not durable production persistence.
```

**Proven:** state is written after each superstep; an interrupted run's state is
restored on resume; threads are isolated from one another; the serializer handles
every checkpointed type.

**Not proven:** durability across process restarts, concurrent writers, crash
recovery, retention, or migration. Those require the PostgreSQL checkpointer and
are out of Phase 1A scope.

---

## 10. Node contracts

`src/graph/contracts.py` defines the shapes every node reports through. They are
domain-neutral: nothing here knows about academic search, novelty or scoring.

| Model | Purpose |
|---|---|
| `WorkflowStatus` | run lifecycle: NOT_STARTED / RUNNING / INTERRUPTED / COMPLETED / FAILED |
| `NodeStatus` | one execution's outcome |
| `NodeResult` | what a node reports: changed paths, summary, warnings, errors, metadata |
| `NodeExecutionRecord` | the durable per-node record, keyed in graph state, with `attempts` |
| `NodeAttempt` | one entry, including replays |
| `AuditEvent` | append-only event, de-duplicated by `event_key` |
| `InterruptRequest` | JSON-serializable human-input request |
| `WorkflowError` | code / node / message / recoverable / timestamp / metadata |

`WorkflowStatus` is deliberately **separate from `EvaluationStatus`**. The Phase 0
enum describes how well evidence supports a judgement; this one describes whether
the machine is still running. A run can be `COMPLETED` while its evaluation is
`INSUFFICIENT_EVIDENCE` — conflating the two would be a category error.

`NodeResult.state_changes` lists dotted paths a node touched. It is a summary for
traceability, never a copy of the data and never a dump of model reasoning
(architecture section 35: internal chain-of-thought is not exposed).

### Errors

`WorkflowError` carries a closed `WorkflowErrorCode`, the node, an English
message, a `recoverable` flag, a timestamp and flat string metadata.
`WorkflowErrorReport` is the exception wrapper, so callers receive structured data
rather than parsing an exception string.

**Tracebacks never enter domain state.** They belong in developer logs and test
output. A test asserts no error message in graph state contains a traceback or
even a newline.

---

## 11. Node registry

`src/graph/registry.py` declares two separate namespaces:

* **`NodeId`** — all 24 production nodes from architecture sections 8-23
  (`INTAKE_GUARD` ... `REPORT_GENERATOR`), plus `PRODUCTION_NODE_ORDER` and
  `PARALLEL_RESEARCH_NODES`. Declared now so no node name is ever a free-form
  string duplicated across modules. **None of them execute in Phase 1A.**
* **`Phase1ANode`** — the 7 infrastructure nodes of the harness.

A test asserts the two sets are disjoint, so the harness can never be mistaken
for the production workflow.

---

## 12. Node purity

Every Phase 1A node is `state in -> deterministic transformation -> state
update`. No model call, no network, no filesystem. The only non-determinism is
timestamping, which never affects routing — routing functions are pure functions
of state and are tested directly, without running the graph.

Future external side effects (search providers, model calls) will be isolated
behind adapters so this property survives.

---

## 13. Current limitations

1. `MAX_INPUT_REQUESTS = 1`. A real intake loop will need a considered policy for
   repeated clarification rounds.
2. `PatchableField` has three entries. Widening it is a deliberate, reviewable
   decision, not an accident of a permissive API.
3. `pending_nodes` exists on the state but the harness does not populate it; the
   production scheduler will.
4. `InterruptType` declares H1-H5; only `MISSING_CRITICAL_INFORMATION` is exercised.
5. No async execution path. The graph is invoked synchronously.
6. Serving workflow progress over an API will need either the live graph state or
   a purpose-built projection; no such view exists yet (ADR-002 consequence).

### Explicitly deferred (not Phase 1A.1 scope)

7. PostgreSQL checkpointer, and therefore durability, concurrency and
   crash-recovery coverage.
8. Async graph execution.
9. Production pending-node scheduler.
10. H2-H5 interrupt flows.
11. Expanded `PatchableField` intake coverage.
12. Performance optimization of full `ProjectState` re-validation.
13. Research connectors, LLM integration, and the scoring engine.

### Resolved in Phase 1A.1

* The duplicated `ProjectState.workflow` block — removed (ADR-002, section 3).
* Misleading replay timing — attempt-level timing (section 8b).
* The manual `CHECKPOINTED_MODULES` list — recursive discovery (section 5).

---

## 14. What Phase 1A explicitly does NOT implement

Not in scope, and deliberately absent:

* OpenAI API calls, or any LLM call
* Consensus, OpenAlex, Semantic Scholar, EPO OPS, Tavily, GitHub, web search
* Academic, patent, product or open-source research
* Novelty, gap, methodology, experiment or claim-evidence reasoning
* Red Team
* Scoring logic (the Phase 0 rubric contract exists; no engine fills it)
* Trust gate execution inside the graph (the Phase 0 policy exists and is tested
  standalone; no node calls it yet)
* Report generation
* PostgreSQL checkpointer, database migrations, Supabase
* FastAPI endpoints, UI
* Jury Mode, Mentor Mode
* Langfuse tracing

---

## 15. Running it

```bash
pytest
```

The entire suite runs with no OpenAI key, no internet and no external
credentials. If any test ever needs one, Phase 1A has been incorrectly scoped.

**Resolved LangGraph version:** 1.2.11 (`langgraph>=1.2,<2.0`), with
`langgraph-checkpoint` 4.2.0.
