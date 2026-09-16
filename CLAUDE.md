# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An evidence-driven evaluation agent for Mawhiba technology-competition projects.
It is **not a chatbot with a long prompt**: it is a deterministic workflow with a
persistent canonical state, provenance-checked extraction, and trust gates that
prevent the system asserting more than its evidence supports.

The quality bar the whole design serves: anyone can ask *"why did you give this
judgement?"* and get the evidence, sources, confidence and gaps, step by step.

## Commands

Python 3.12+ is required. A local venv is at `.venv`.

```bash
# Full suite (no API key, no network required)
./.venv/Scripts/python.exe -m pytest

# One file / one test
./.venv/Scripts/python.exe -m pytest tests/test_intake_trust.py
./.venv/Scripts/python.exe -m pytest tests/test_intake_trust.py::test_hallucinated_fact_is_rejected
./.venv/Scripts/python.exe -m pytest -k "verbatim"

# Show skip reasons
./.venv/Scripts/python.exe -m pytest -rs

# Intake trust evaluation (deterministic, fake provider)
./.venv/Scripts/python.exe -m src.evals.cli

# Research planning eval (deterministic, fake provider)
./.venv/Scripts/python.exe -m src.evals.research.cli

# Academic retrieval eval (deterministic, fake providers)
./.venv/Scripts/python.exe -m src.evals.academic.cli

# Live evals / live integration tests -- NEVER run these without being asked
RUN_OPENAI_INTAKE_EVALS=1 ./.venv/Scripts/python.exe -m src.evals.cli --live
RUN_OPENAI_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_openai_integration.py
RUN_OFFICIAL_WEB_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_official_web_integration.py
RUN_CONSENSUS_TESTS=1 RUN_OPENALEX_TESTS=1 RUN_SEMANTIC_SCHOLAR_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_academic_live_integration.py
```

No linter or type checker is configured. Do not add one without being asked.

The standard suite must never make a network call. `tests/test_llm_layer.py`
patches `httpx.Client.send` to raise, so an accidental real call fails loudly.

## Architecture

### Two state models, strictly separated (ADR-001, ADR-002)

| | `ProjectState` (`src/graph/state.py`) | `EvaluationGraphState` (`src/graph/workflow_state.py`) |
|---|---|---|
| Owns | project + evaluation truth | workflow execution truth |
| Holds | identity, problem, solution, technical, methodology, claims, sources, evidence, prior art, novelty, gap, scores, contradictions | status, current/completed/pending nodes, attempts, interrupt state, errors, `run_id`/`thread_id` |

They share **no field name** — a test enforces this. Workflow progress never goes
into `ProjectState`; a project snapshot must stay meaningful independently of the
orchestrator. `EvaluationGraphState.project` is the single canonical project state.

`run_id` (one evaluation execution) and `thread_id` (LangGraph checkpoint cursor,
`thr-<uuid>`, PII-free) are **not** interchangeable.

### Zero Assumption

`Tracked[T]` (`src/schemas/common.py`) wraps every critical field with a
`KnowledgeStatus`: `KNOWN` / `INFERRED_NON_CRITICAL` / `UNKNOWN` / `CONFLICTED`.
Validators reject `KNOWN` without a value, `UNKNOWN` with a value, and
`AGENT_INFERENCE` origin combined with `KNOWN`. `CONFLICTED` keeps both values
and picks neither.

**A false UNKNOWN is always preferable to a fabricated KNOWN.** A gap can be
filled by asking the student; a fabricated fact silently poisons every downstream
judgement, and nothing later is designed to catch it.

### The LLM trust boundary (ADR-003, ADR-004)

```
PROJECT_EXTRACTOR          LLM -> ProjectExtraction        UNTRUSTED CANDIDATE
PROJECT_EXTRACTOR_VERIFIER deterministic -> VerifiedExtraction  === BOUNDARY ===
PROJECT_STATE_MERGE        validated merge -> ProjectState
```

Rules that must not be weakened:

- The model never produces a `ProjectState` and never produces a `KnowledgeStatus`.
- Every value carries a **verbatim excerpt**; the model is never asked for
  character offsets (it can miscount, and a wrong offset looks like verified
  provenance). Code derives offsets in `src/intake/anchors.py`.
- Anchor existence alone is not enough. `VERBATIM_TERM` fields require every token
  of the value to appear in the excerpt, which rejects e.g. `"YOLOv8"` anchored to
  `"uses a camera"`.
- `VERBATIM_SPAN` fields (narrative facts) store the **verified excerpt** as
  canonical; the model's paraphrase is kept only as `model_summary`, derived.
- Model confidence is recorded and **never** participates in an accept decision.
- `src/intake/merge.py` is the only writer of intake data into `ProjectState`.
- No fuzzy matching, semantic similarity, paraphrase tolerance or translation in
  the verification path.

### Student claims are not evidence

A student statement ("97% accuracy") means *the student claims that*. Intake
creates a `ClaimRecord` with `origin=STUDENT`, `status=UNSUPPORTED`, no
`evidence_ids` — and creates **no** `EvidenceRecord` and **no** `SourceRecord`.
Phase 1B/1C know *what the student said*, never whether it is true.

### Deterministic layers

`src/trust/models.py` (trust gate) and `src/scoring/models.py` (rubric) contain
**no LLM calls**. Same state in, same verdict out. The score is summed in Python;
an axis with `score=None` is unscored, never zero.

### Node replay safety (ADR-002)

LangGraph re-runs an interrupted node from its first line on resume. Therefore:
`interrupt()` is the first statement in `REQUEST_INPUT`; every accumulating
channel in `EvaluationGraphState` uses a replay-safe reducer; `completed_nodes`
is a de-duplicated set while `node_execution_attempts` is an honest log.
`NodeAttempt.duration_ms` is the only timing value valid for performance —
`NodeExecutionRecord.lifecycle_elapsed_ms` spans the human pause by design.

### Serializer registration

`src/graph/type_discovery.py` walks the type graph from `EvaluationGraphState`
and `ProjectState`. LangGraph **silently blocks** unregistered types on
deserialization, so a new checkpoint-reachable model must either be reachable
from those roots (auto-registered) or be added to `NON_CHECKPOINTED_TYPES` in
`tests/test_workflow_hardening.py` **with a reason**. The completeness test fails
until one of the two is true — that is the intended workflow, not an obstacle.

### Graphs

- `build_phase1a_graph()` — infrastructure harness only (checkpoint, interrupt,
  resume, routing). Not the production graph; do not grow it into one.
- `build_phase1b_intake_graph()` — trusted intake, built from production `NodeId`s.
- `build_phase2a_research_graph()` — planning + official requirements; finalizes the run.
- `build_phase2b_academic_graph()` — the academic branch. Consumes an **open** run
  that already carries a verified query plan, makes **no model call**, and
  deliberately leaves the run non-terminal so later branches can still write to it.
- The provider is injected per run via
  `config["configurable"]["structured_model_provider"]`, which is what keeps graph
  construction credential-free and tests deterministic.

`PHASE_1A_DEMO_GATE` (`src/graph/routing.py`) is a demonstration gate, **not** the
intake completeness policy.

## Evals

`evals/intake/v1/cases.jsonl` — 80 Gold cases in reviewable JSONL, schema in
`evals/intake/v1/schema.md`. Gold expectations are authored from the submission
text alone; the `scripted` block is what a possibly-misbehaving model returns.
**Never generate model output and then declare it correct.**

Four release-blocking safety metrics, all currently at zero violations:
`unsupported_known_acceptance`, `invalid_provenance_acceptance`,
`student_claim_leakage`, `prompt_injection_mutation`.

`evals/academic_retrieval/v1/cases.jsonl` — 51 Gold cases, schema in
`evals/academic_retrieval/v1/schema.md`. Each case is driven through the real
Phase 2B graph with deterministic fakes; the scorer re-derives identity
conflicts, provenance and traceability independently of the code it scores, and
negative controls prove each gate can fire. Seven release-blocking metrics, all
at zero: `pii_leakage_rate`, `project_state_mutation_rate`,
`evidence_creation_violation_rate`, `claim_mutation_violation_rate`,
`untraceable_verified_source`, `invalid_strong_identifier_merge`,
`provider_provenance_loss`.

Phase 2B.1 pinned the three providers' request contracts.
`tests/test_academic_provider_contracts.py` asserts the **exact** outgoing URL
and parameters for each connector, with a negative assertion naming every stale
value that must never return (`search/papers`, `size`, `per-page`). The
contract table is section 2a of the Phase 2B doc, and `ProviderCapability` reads
the connector constants rather than restating them, so the table cannot drift.

Phase 2B.2 resolved the Consensus REST authentication question from the
provider's own OpenAPI definition: the only security scheme is `x-api-key`, and
no bearer scheme exists. Consensus's MCP server is a separate surface and is
never a source for the REST contract. Never introduce an `Authorization: Bearer`
header here without evidence from the REST documentation.

The approved baseline (`evals/intake/baselines/v1.json`) is never overwritten
automatically — `write_baseline(..., approve=True)` or `--approve-baseline` is
required. Reports go to the git-ignored `eval_reports/`.

## Language policy

```
Developer / internal agent / structured data layers  = English only
Student presentation layer                           = Arabic-first
```

English: code, comments, docstrings, tests, errors, logs, CLI output, JSON keys,
schema field names, enum names **and values**, internal prompts (even when the
project under evaluation is Arabic).

Arabic is allowed **only as data** — student text stored verbatim in value
positions (`Tracked.value`, claim text, `quote_or_extract`), never translated.
`tests/test_language_policy.py` scans every tracked file; a file that must carry
Arabic goes in `ARABIC_AS_DATA` **with a stated reason**.

`docs/mawhiba_agent_system_architecture_v1.md` is the Arabic source artifact and
is exempt — amend it narrowly and only when explicitly authorized.

## Documentation map

Read the relevant doc before changing a layer; each records decisions that are
not obvious from the code.

- `docs/mawhiba_agent_system_architecture_v1.md` — architectural source of truth (Arabic)
- `docs/data_contracts.md` — Phase 0 schemas, claim/evidence/source relationships
- `docs/phase1a_workflow.md` — graph, checkpointing, interrupt/resume, idempotency
- `docs/phase1b_trusted_intake.md` — provider abstraction, provenance, evaluation boundary
- `docs/phase1c_intake_evals.md` — canonical intake model, taxonomy, Gold evals
- `docs/phase2a_research_foundation.md` — research runs, query provenance, official requirements
- `docs/phase2a1_hardening.md` — official hosts and currency, source identity, shared retry layer, multilingual planning
- `docs/phase2a_execution_spec.md` — the reviewed Phase 2A execution specification
- `docs/phase2b_academic_research_connectors.md` — academic connectors, identity resolution, merge policy, evals
- `docs/adr/ADR-0{01..10}-*.md` — decisions and their rejected alternatives

## Phase discipline

Work has proceeded in reviewed phases (0, 1A, 1A.1, 1B, 1C, 2A, 2A.1, 2B). Phase 2A
added the research foundation: `ResearchRun` on graph state (never in
`ProjectState`), verified query planning, and official Mawhiba requirements
retrieval (`build_phase2a_research_graph()`). Research planning must never write
`ProjectState`, and retrieval produces `SourceCandidate`, never `EvidenceRecord`
(ADR-006, ADR-007).

Phase 2B added the academic connectors — Consensus, OpenAlex and Semantic
Scholar — as **isolated** providers (ADR-008): one failing provider never erases
another's results, and "worked and found nothing" (`EMPTY`) is never reported as
"could not be asked" (`FAILED`). Cross-provider deduplication produces one
`LogicalAcademicSource` while preserving every `ProviderObservation`; identity
comes from strong identifiers only and **never from a title** (ADR-009).
Retrieval stops at `VERIFIED_METADATA`: no `EvidenceRecord`, no claim support, no
source quality, no full text (ADR-010).

The patent, product, open-source and standards connectors, evidence extraction,
scoring engine, Red Team, report generation, PostgreSQL checkpointer and UI are
**not implemented**. Do not start them without being asked.

When a prior guarantee blocks new work, the answer is almost never to relax the
guarantee — the guards in `test_workflow_hardening.py` and
`test_language_policy.py` exist precisely to fire on new code.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
