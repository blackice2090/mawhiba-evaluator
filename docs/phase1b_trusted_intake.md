# Phase 1B — Trusted Project Intake

**Status:** Implemented
**Scope:** Text intake, project extraction, provenance verification, project type
and domain classification. The first phase that calls an LLM.
**Decision record:** `docs/adr/ADR-003-llm-extraction-trust-boundary.md`
**Prior phases:** `docs/phase1a_workflow.md`, `docs/data_contracts.md`

---

## 1. The priority

Not maximum extraction coverage.

> **High-precision extraction with explicit uncertainty and verifiable
> provenance.**

A false UNKNOWN is preferable to a fabricated KNOWN. A gap can be filled by
asking the student. A fabricated fact silently poisons every downstream judgement
— novelty, methodology, scoring — and nothing later in the pipeline is designed
to catch it, because everything later *trusts* the canonical state.

---

## 2. Trusted extraction architecture

```text
StudentSubmissionArtifact          original text, preserved verbatim
        |
        v
PROJECT_EXTRACTOR                  LLM -> ProjectExtraction
        |                          ^^^^^^^^^^^^^^^^^^^^^^^^
        |                          UNTRUSTED CANDIDATE
        v
PROJECT_EXTRACTOR_VERIFIER         deterministic code -> VerifiedExtraction
        |                          ================ TRUST BOUNDARY ============
        v
PROJECT_STATE_MERGE                validated merge -> ProjectState
        |
        v
PROJECT_TYPE_CLASSIFIER            LLM -> ProjectClassification (untrusted)
        |
        v
CLASSIFICATION_MERGE               verified -> ProjectState
```

Extraction and classification are separate calls with separate merges. Neither
can silently modify the other's output, which keeps a misclassification from
corrupting extracted facts and makes a failure attributable to one node.

### Module layout

| Module | Role |
|---|---|
| `src/schemas/submission.py` | `StudentSubmissionArtifact` — verbatim original |
| `src/schemas/extraction.py` | model-facing DTOs *and* verified contracts |
| `src/llm/contracts.py` | `ModelCallResult`, status vocabulary |
| `src/llm/provider.py` | `StructuredModelProvider` protocol |
| `src/llm/openai_provider.py` | Responses API implementation |
| `src/llm/fake_provider.py` | deterministic test double |
| `src/llm/prompts.py` | versioned English prompts |
| `src/intake/anchors.py` | deterministic provenance verification |
| `src/intake/verification.py` | candidate -> verdict |
| `src/intake/merge.py` | the only writer into `ProjectState` |
| `src/intake/extractor.py` | model routing, retry, escalation |
| `src/graph/intake_nodes.py` | the nodes |
| `src/graph/phase1b_graph.py` | `build_phase1b_intake_graph()` |

---

## 3. Provider abstraction

Business logic depends on a Protocol, never on the OpenAI SDK:

```python
class StructuredModelProvider(Protocol):
    name: str
    def parse(self, *, task, system_prompt, user_input,
              response_model, model) -> ModelCallResult[T]: ...
```

Two implementations: `OpenAIResponsesProvider` and
`FakeStructuredModelProvider`. The fake is what makes every trust rule testable
— you cannot reliably test "what happens when the model lies" against a real
model.

The provider is injected per run through
`config["configurable"]["structured_model_provider"]`, so graph construction
never touches credentials and a test supplies a fake with one line.

**No raw SDK object reaches domain logic.** Every call returns a
`ModelCallResult`, which carries `parsed`, `model`, `provider`, `task`,
`request_id`, `status`, `refusal`, `error`, `usage`, `attempts` and `latency_ms`.
It carries no reasoning trace, and a test asserts the model has no field named
`reasoning`, `chain_of_thought`, `thoughts` or `raw_response`.

---

## 4. Structured Outputs

```python
response = client.responses.parse(
    model=model_name,
    input=[{"role": "system", ...}, {"role": "user", ...}],
    text_format=ProjectExtraction,
)
parsed = response.output_parsed
```

The model is never asked for free-form JSON, and no regex ever touches its
output. A shape the schema rejects becomes `PARSE_ERROR` — not something to
salvage by string surgery.

The model produces a **purpose-built intake DTO**, never a `ProjectState`. It
also never produces a `KnowledgeStatus`: deciding what is KNOWN is not the
model's job.

---

## 5. Provenance anchors

Every extracted value carries a **verbatim excerpt** from the submission:

```python
class ExtractedValue(ModelFacingModel):
    value: str
    excerpt: str      # copied character-for-character from the submission
    confidence: float # advisory only
```

The model is **never asked for character offsets**. A model can miscount, and a
miscounted offset would look exactly like verified provenance. Offsets are
derived deterministically by code.

### Deterministic verification

`verify_anchor()` escalates through three attempts, recording which succeeded:

| Method | Meaning |
|---|---|
| `EXACT` | byte-for-byte occurrence; offsets are exact |
| `NORMALIZED_UNICODE` | matched after line-ending, NFC and invisible-character folding |
| `NORMALIZED_WHITESPACE` | matched after additionally collapsing whitespace runs |
| `NOT_FOUND` | the excerpt is not in the submission |

Normalization is conservative and deliberately limited to transport-level
differences. There is **no** fuzzy matching, no semantic similarity, no
paraphrase tolerance, no translation. The method is recorded so a reader can
always tell an exact quote from one that only matched after folding.

### Multiple occurrences

An excerpt appearing more than once is not invalid. `VerifiedAnchor.matches`
records **every** matching range. Inventing one exact location would be
fabricated precision.

---

## 6. When a value becomes KNOWN

```text
model proposes value + excerpt
        |
        v
excerpt found in the artifact?        -> no: ANCHOR_NOT_FOUND, rejected
        |
        v
excerpt actually states the value?    -> no: VALUE_NOT_SUPPORTED_BY_ANCHOR, rejected
        |
        v
accepted -> eligible for KNOWN
        |
        v
merge rules (existing state, conflicts) decide the final status
```

**Anchor existence alone is not enough.** A model can pair a genuine quote with
an invented value — `value="YOLOv8"` anchored to `"uses a camera"`. The quote
verifies; the value is a fabrication.

`FieldKind` closes most of that gap deterministically:

* **`VERBATIM_TERM`** — named models, hardware, sensors, libraries, datasets,
  numbers. Every token of the value must appear in the excerpt. This is a
  containment check, not semantic entailment, but it is deterministic and it
  rejects the YOLOv8-from-a-camera case.
* **`NARRATIVE`** — problem statements, descriptions. The value is a legitimate
  summary, so only anchor existence is enforced. See the limitation in section 13.

**Model confidence never decides anything.** It is recorded for observability and
excluded from the accept decision by construction. A test asserts a hallucination
with confidence 0.99 is still rejected.

### KnowledgeStatus rules for Phase 1B

| Status | When |
|---|---|
| `KNOWN` | explicitly present **and** anchor verification succeeded |
| `UNKNOWN` | not present — the expected, correct outcome for anything unsaid |
| `CONFLICTED` | the submission states incompatible values for one material fact |
| `INFERRED_NON_CRITICAL` | **never** for extracted factual details — reserved for classification |

---

## 7. Student claim isolation

> A student statement is not independently verified evidence.

"Our model achieved 97% accuracy" means **the student claims 97% accuracy**. It
does not mean the model achieved it.

So intake distinguishes two things that are easy to conflate:

* **Submission provenance** — proof the student said X.
* **Scientific evidence** — proof X is true.

Phase 1B produces only the first. Concretely, the merge layer:

* creates a `ClaimRecord` with `origin=STUDENT` and `status=UNSUPPORTED`,
  `evidence_ids=[]`, `confidence=0.0`;
* creates **no** `EvidenceRecord` and **no** `SourceRecord`;
* never sets novelty, gap, scores, findings or the trust gate.

The Phase 0 contract already forbids `SUPPORTED` without evidence. Intake never
attempts it.

A student's novelty assertion — "no one has done this before" — is recorded as a
`NOVELTY` claim with status `UNSUPPORTED`. It is not a finding of novelty, and
`novelty.level` stays `None`.

---

## 8. Merge rules

`merge_intake_extraction()` is the only writer of intake data into
`ProjectState`, and raw model output never reaches it.

| Rule | Behaviour |
|---|---|
| Only supported fields change | an unmapped field is reported, never invented into the schema |
| KNOWN is never silently overwritten | a different verified value produces `CONFLICTED`, holding both values |
| UNKNOWN may become KNOWN | when a verified value supports it |
| KNOWN never reverts to UNKNOWN | a later turn that omits a field leaves it intact |
| Lists append, never replace | de-duplicated |
| Claims stay claims | student origin, unsupported |
| Result is re-validated | a merge cannot leave an invalid canonical state |

Each accepted value records its provenance on the `Tracked` value:

```text
artifact=<uuid> method=EXACT ranges=[12:36]
```

so "where did the system get this?" is answerable from the state alone.

### Multi-turn intake

Turn 1: `Project name: Sentinel` → `project_name = KNOWN("Sentinel")`.
Turn 2: `We use three microphones.` → hardware appended, **and the name survives**.

### Conflicts

Two different verified values for one KNOWN field produce a `CONFLICTED`
`Tracked` value holding both, with no winner chosen. Conflicts the model
identifies *within* one submission produce a `ContradictionRecord` with
`requires_student_clarification=True`. Neither is resolved automatically.

---

## 9. Classification

`PROJECT_TYPE_CLASSIFIER` returns a project type with a supporting excerpt, a
one-sentence rationale, and technical domains each with their own excerpt.

**Type** maps onto the existing `ProjectType` enum. A type whose excerpt does not
verify **falls back to UNKNOWN** — the classifier does not get to assert a type on
its own authority. An `UNKNOWN` type carries no confidence, which the Phase 0
`ProjectIdentity` validator independently enforces.

**Domains** use the Phase 1B `TechnicalDomain` taxonomy (20 members) and are
projected onto Phase 0's coarser `ProjectDomain` by an explicit, documented map.
Multiple domains are allowed when each is anchored.

Classification is the one place `INFERRED_NON_CRITICAL` reasoning is permitted,
because a domain label never appears verbatim in a submission. It is confined to
`identity.project_type` and `identity.domain`; a test asserts classification
touches no factual field. Over-classification is explicitly prompted against: a
CRUD application is `SOFTWARE_ENGINEERING`, not `ARTIFICIAL_INTELLIGENCE`.

`rationale` is bounded at 400 characters and prompted to be one sentence. It is a
justification, never a reasoning trace.

---

## 10. Model routing

| Setting | Default | Env var |
|---|---|---|
| extraction | `gpt-5.6-terra` | `OPENAI_EXTRACTION_MODEL` |
| classification | `gpt-5.6-terra` | `OPENAI_CLASSIFICATION_MODEL` |
| escalation | `gpt-5.6-sol` | `OPENAI_ESCALATION_MODEL` |
| retries | `2` | `OPENAI_MAX_RETRIES` |

No credential is read here — the OpenAI SDK handles `OPENAI_API_KEY` itself.
Importing the package and running the unit suite require no key.

### Escalation

Deliberately narrow: only when the classification call **structurally succeeded**
but returned a project type below `classification_escalation_threshold` (0.5) does
the stronger model get **one** additional attempt. A failed escalation keeps the
usable first answer.

Escalation buys reasoning quality on an ambiguous judgement. It is never used to
turn an UNKNOWN factual field into a guessed value.

---

## 11. Provider failure handling

Five distinct outcomes, because "refused", "truncated" and "the network broke"
need different handling:

| Status | Retried | Meaning |
|---|---|---|
| `SUCCESS` | — | parsed payload available |
| `REFUSAL` | **no** | a deliberate model decision; retrying burns money and changes nothing |
| `PARSE_ERROR` | **no** | the schema contract is wrong; no retry fixes a bad schema |
| `INCOMPLETE_OUTPUT` | yes | truncation, e.g. `max_output_tokens` |
| `PROVIDER_ERROR` | yes | transport or API fault |
| `EMPTY_OUTPUT` | yes | no parsed output returned |

Retries are bounded (default 2, capped at 5 by the schema).

A refusal:

* does **not** crash the workflow;
* does **not** become an empty successful extraction;
* produces a structured `MODEL_REFUSAL` workflow error;
* leaves `ProjectState` **unchanged**;
* is observable for a future UI.

> A refusal is a model execution outcome. It is **not** "the project information
> is unknown."

A **classification** failure is non-fatal: extraction already succeeded, and an
unclassified project is a legitimate `UNKNOWN`. The error is recorded and the run
continues.

---

## 12. Graph integration

`build_phase1b_intake_graph()` is a **separate graph** from the Phase 1A harness,
built from production `NodeId` identifiers. A test asserts the Phase 1A graph
still compiles with exactly its original nodes.

N01 is split into three nodes — propose, verify, merge — so the trust boundary is
a visible node in the graph rather than a hidden step inside the extractor.

Checkpointing, interrupt, resume, replay-safety and attempt timing are inherited
unchanged from Phase 1A/1A.1.

---

## 13. Current limitations

**1. Exact provenance proves attribution, not truth.**

```text
It proves:         the student said X.
It does NOT prove: X is true.
```

> **Resolved in Phase 1C.** Limitations 2 and 5 below, the lossy domain
> taxonomy and the technologies-as-software approximation are all corrected;
> the unsupported-field acceptance rate is now measured at zero by the Gold
> dataset. See `docs/phase1c_intake_evals.md`, ADR-004 and ADR-005.

**2. Semantic entailment is not fully proven.** `VERBATIM_TERM` containment
catches the common mismatch, but `NARRATIVE` fields accept any summary whose
anchor exists. A model could anchor a subtly wrong problem statement to a real
passage and it would be accepted. This is the known residual gap, and later evals
must measure **unsupported-field acceptance rate** directly.

**3. Whitespace-normalized matches have approximate offsets.** Collapsing changes
positions, so a collapsed match reports the region it can locate rather than a
fabricated exact range. `method` records that normalization was used.

**4. Conflict detection is model-proposed.** Code verifies both anchors, but
finding the conflict is the model's job, so a missed conflict is possible.

**5. Four extracted fields have no Phase 0 destination** (`goal`,
`student_contribution`, `current_stage`, `prototype_status`, `data_sources`).
They are verified and reported, not silently dropped, and not invented into the
schema.

**6. Text only.** No file, PDF, OCR or link intake.

**7. Domain taxonomy is lossy on merge.** 20 `TechnicalDomain` members project
onto 12 `ProjectDomain` members through an explicit map; the finer distinction
survives only on `VerifiedClassification`.

---

## 14. The evaluation boundary

At the end of Phase 1B the system knows:

```text
what the student said
```

It does **not** know:

```text
whether what the student said is scientifically correct
```

Nothing in Phase 1B evaluates novelty, checks a claim against literature,
validates a problem, reviews methodology or produces a score. If a student writes
"no one has done this before", that is stored as an unsupported student claim —
never as a novelty finding. Answering those questions is the job of later nodes,
with external sources and the trust gate.

---

## 15. Testing

The complete standard suite runs with **no `OPENAI_API_KEY` and no internet**. A
guard test patches `httpx.Client.send` to raise, so a unit test that ever tried to
make a real call would fail loudly.

The live integration test (`tests/test_openai_integration.py`) is skipped unless
`RUN_OPENAI_INTEGRATION_TESTS=1` is set explicitly — the presence of an API key
alone is deliberately not enough. It makes at most two calls on a two-sentence
submission and asserts structure and provenance, never the model's wording.
