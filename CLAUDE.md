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

# Evidence extraction eval (deterministic, fake provider)
./.venv/Scripts/python.exe -m src.evals.evidence.cli

# Claim-evidence alignment eval (deterministic, fake provider)
./.venv/Scripts/python.exe -m src.evals.claim_alignment.cli

# Claim sufficiency eval (deterministic, no model at all)
./.venv/Scripts/python.exe -m src.evals.claim_sufficiency.cli

# Live evals / live integration tests -- NEVER run these without being asked
RUN_OPENAI_INTAKE_EVALS=1 ./.venv/Scripts/python.exe -m src.evals.cli --live
RUN_OPENAI_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_openai_integration.py
RUN_OFFICIAL_WEB_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_official_web_integration.py
RUN_CONSENSUS_TESTS=1 RUN_OPENALEX_TESTS=1 RUN_SEMANTIC_SCHOLAR_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_academic_live_integration.py
RUN_EVIDENCE_LLM_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/test_evidence_llm_integration.py
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
- `build_phase2c_evidence_graph()` — trusted evidence extraction. One model call
  per content snapshot; everything it returns is verified deterministically
  against the snapshot text. Also leaves the run non-terminal.
- `build_phase2e_claim_sufficiency_graph()` — claim sufficiency and evidence
  weighting over Phase 2D alignments. Fully deterministic: it takes **no model
  provider**, makes no model call, and also leaves the run non-terminal.
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

`evals/evidence_extraction/v1/cases.jsonl` — 70 Gold cases. Each runs through
the real Phase 2C graph with a scripted fake provider; the scorer re-derives
every judgement from the snapshot text independently of the verifier, and
negative controls prove each gate can fire. Six quality metrics must be exactly
1.0, and eleven release-blocking metrics must be zero.

`evals/claim_sufficiency/v1/cases.jsonl` — 175 Gold cases, schema in
`evals/claim_sufficiency/v1/schema.md`. Each case describes a whole synthetic
upstream world (claims, Phase 2B sources with identifiers, Phase 2C evidence,
Phase 2D alignments) and is driven through the real Phase 2E graph. There is no
scripted model output because Phase 2E makes no model call; the adversarial
surface is the input *shape*. The scorer re-derives the independence partition
from the fixture's own identifiers, independently of the code it grades. Ten
quality metrics must be exactly 1.0 and thirty-eight release-blocking metrics
must be zero. Phase 2E.1 added the last five (claim-component completeness) and
four more required-perfect quality metrics; existing gates were preserved rather
than merged.

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
- `docs/phase2c_evidence_extraction.md` — content snapshots, verbatim verification, numeric fidelity, evidence evals
- `docs/phase2d_claim_evidence_alignment.md` — relationship taxonomy, claim anchors, alignment evals
- `docs/phase2e_claim_sufficiency.md` — independence grouping, evidence weight profiles, claim-component inventory, sufficiency policy, sufficiency evals
- `docs/adr/ADR-0{01..16}-*.md` — decisions and their rejected alternatives

## Phase discipline

Work has proceeded in reviewed phases (0, 1A, 1A.1, 1B, 1C, 2A, 2A.1, 2B, 2B.1,
2B.2, 2C, 2D, 2E, 2E.1). Phase 2A
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

Phase 2C added trusted evidence extraction. Source content snapshots are built
per provider observation from the paper's own abstract — never from a merged
string, never from a title, a citation count, a provider rank or a Consensus
`takeaway`. An LLM proposes candidates; deterministic code verifies them. The
stored excerpt is always `snapshot.text[start:end]`, sliced by code, so
*verbatim* holds by construction (ADR-011); model offsets are never trusted to
locate text, and a repeated sentence is refused as `AMBIGUOUS_SPAN` rather than
guessed. Numbers are re-checked against the verified excerpt, so 92.3% cannot
become 93.2% and 5 ms cannot become 5 s.

Extracted evidence lives on the `ResearchRun`, **not** in `ProjectState.evidence`:
a canonical `EvidenceRecord` must reference a source inside `ProjectState.sources`,
and verified academic sources deliberately live on the run (ADR-010). The
research-layer type has no `support_direction`, no `strength` and no `claim_id`,
so Phase 2C **cannot** express claim support even by accident (ADR-012). Evidence
from an abstract stays `ABSTRACT_ONLY` and is never presented as full-text
verified (ADR-013).

Phase 2D added claim-evidence alignment. `ClaimEvidenceAlignmentRun` lives on
the `ResearchRun`, never in `ProjectState`, for the same ownership reason as
Phase 2C's evidence (ADR-010). A finite `AlignmentRelation` taxonomy
(`SUPPORTS`, `CONTRADICTS`, `PARTIALLY_SUPPORTS`, `PARTIALLY_CONTRADICTS`,
`MIXED`, `CONTEXT_ONLY`, `INSUFFICIENT`, `NOT_RELEVANT`) classifies the
relationship between one existing claim and one verified Phase 2C evidence
item; a deterministic verifier proves exact claim-anchor text
(`claim.claim[start:end] == anchor_text`, no normalization), taxonomy
consistency, and provenance, but never the underlying semantic correctness.
Phase 2D **cannot** mutate a claim's status, confidence, `evidence_ids` or
`counter_evidence_ids` — those fields do not exist on `ClaimEvidenceAlignment`
(ADR-014). Claim-evidence alignment is not claim verification.

Phase 2E added claim sufficiency and evidence weighting. `ClaimSufficiencyRun`
lives on the `ResearchRun`, never in `ProjectState` (ADR-010). Sufficiency is
**multi-dimensional and never one opaque scalar** — there is no
`evidence_weight: float` anywhere, and a test asserts no numeric field appears
on the Phase 2E contracts (ADR-015). Corroboration is counted in
`IndependenceGroup`s keyed on Phase 2B's `SourceFingerprint.logical_key`, so
three providers returning one DOI is one study and five excerpts from one
abstract is one study; multiple excerpts may improve component coverage but can
never raise the independent-source count. Source quality (retraction,
publication form, traceability, scope) stays separate from semantic relation,
which is claim-specific. `UNKNOWN` retraction and publication status are
first-class and never read as favorable. Retracted evidence stays visible as
`DISQUALIFIED_RETRACTED` and never corroborates. Phase 2E **cannot** mutate
claim status, confidence, `evidence_ids`, `counter_evidence_ids`, scores,
`trust_gate` or `evaluation_status` — none of those fields exists on any
Phase 2E type. It is **fully deterministic by design**: no model call, no
provider seam, no prompt version, documented as intentional in ADR-015. Only a
`COMPLETED` Phase 2D run yields assessments; `PARTIAL` and
`BLOCKED_PAIR_LIMIT_EXCEEDED` become `BLOCKED_ALIGNMENT_INCOMPLETE` rather than
sufficiency over an alignment universe nobody examined.

Phase 2E.1 closed a false-sufficiency path in that design (ADR-016). Phase 2E
originally took the material component set to be the union of the anchors
Phase 2D happened to produce, so a part of a compound claim nobody anchored was
absent from the denominator: a claim could reach `SUFFICIENT_SUPPORT` on the
anchored half while the other half was never examined. The material component
set now comes from the claim's **own text**. `ClaimComponentInventory` is a
verified covering partition of the claim — disjoint components at exact anchors
(`claim.claim[start:end] == text`), plus recorded whitespace/punctuation spans,
together accounting for every character — and `completeness` is arithmetic over
the claim rather than a label a caller may assert. A part no alignment anchored
is a first-class `UNANCHORED_CLAIM_REMAINDER` component with `NO_EVIDENCE`
coverage, so unexamined claim content stays in the denominator and stays
visible. `SUFFICIENT_SUPPORT` and `SUFFICIENT_CONTRADICTION` require
`completeness == COMPLETE`, enforced by `ClaimSufficiencyAssessment`'s own
validator and not only by policy code; the assessment's component set must also
*equal* the inventory's, so a component cannot be dropped from a verdict.
`UNKNOWN` completeness is never read as `COMPLETE`. Still **no model call**:
`COMPONENT-PARTITION-STRATEGY-V1` cuts at boundaries Phase 2D already
established and proves coverage of the claim separately, and it never splits on
conjunctions or punctuation — "black and white image" is one component. What is
proven is structural (exact anchors, disjointness, full coverage); a
guaranteed-perfect semantic decomposition is **not** claimed, and ADR-016 states
what that leaves. Every claim anchor is also re-sliced from the claim here, so a
fabricated anchor makes its pair `CLAIM_ANCHOR_NOT_VERIFIABLE` and untraceable
even when its span coincides with a real component.

Novelty analysis, the scoring engine, Red Team, report generation, the patent
/ product / open-source / standards connectors, full-text acquisition, the
PostgreSQL checkpointer and the UI are **not implemented**. Do not start them
without being asked.

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
