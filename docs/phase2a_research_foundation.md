# Phase 2A — Research Foundation, Query Planning, Official Requirements

**Status:** Implemented
**Scope:** Research contracts, trusted query planning, deterministic query
verification, PII minimization, official Mawhiba requirements retrieval,
verification, snapshotting and extraction, research coverage, Gold evals.
**Decision records:** ADR-006 (query provenance), ADR-007 (search result is not evidence)
**Prior phases:** `docs/phase1c_intake_evals.md`, `docs/phase1b_trusted_intake.md`,
`docs/phase1a_workflow.md`, `docs/data_contracts.md`

Phase 2A does **not** implement academic, patent, product, open-source or
standards connectors. Those branches receive verified plans and coverage state
only.

---

## 1. Trust-state progression

```text
SEARCH RESULT      what a provider returned                 OfficialRetrievalResult
      |
SOURCE CANDIDATE   retrieved, untrusted                      SourceCandidate
      |            --- deterministic source verification ---
VERIFIED SOURCE    allowlisted, hashed, snapshotted          OfficialSourceSnapshot + SourceRecord
      |
EVIDENCE           a located statement in a source           (later phase)
      |
CLAIM SUPPORT      evidence linked to a claim                (later phase)
```

These states are not interchangeable (ADR-007). No Phase 2A module imports or
constructs `EvidenceRecord`, and a test enforces that.

The research pipeline end to end:

```text
Canonical ProjectState -> Research Query Planner -> Verified Query Plan
      -> Source Candidate -> Verified Source -> Evidence -> Claim Support
```

---

## 2. ResearchRun

`src/schemas/research.py`

| Field | Meaning |
|---|---|
| `research_run_id` | identity of one research execution |
| `project_id`, `project_version_id` | the project version researched |
| `planner_version` | `RESEARCH_QUERY_PLANNER_PROMPT_V1` |
| `versions` | planner and extractor prompt versions, research contract version, provider, model, web provider, dataset version |
| `status` | `ResearchRunStatus` |
| `research_input` | the PII-minimized snapshot the planner saw, with the canonical state hash |
| `query_plan` | the `VerifiedQueryPlan` (accepted and rejected queries) |
| `branch_coverage` | one `BranchExecutionCoverage` per branch |
| `official_requirements` | the `OfficialRequirementsResult` |
| `errors` | `ResearchIssue` records |
| `started_at`, `completed_at` | lifecycle |

### Ownership

A `ResearchRun` lives on `EvaluationGraphState.research_runs`, keyed by id, with
`active_research_run_id` pointing at the current one. It is deliberately **not** in
`ProjectState`: research reads canonical state and never writes to it (ADR-006).
This follows the intake precedent where `submission` and `verified_extraction`
are graph-state channels.

### Immutability

* `ResearchRun` is a frozen model; changes go through `evolve()`, which
  re-validates and refuses a terminal run.
* The `merge_research_runs` reducer never replaces a terminal run, so no later
  update can rewrite an older run.
* A new project version opens a new, independent run on the same thread; the
  earlier run is preserved unchanged (tested).
* A replayed `LOAD_PROJECT_STATE` reuses the in-progress run rather than minting a
  new id.

### Status

`NOT_STARTED`, `PLANNING`, `RUNNING`, `PARTIAL`, `COMPLETED`, `FAILED`. Separate from
`EvaluationStatus` and `WorkflowStatus`.

| Final status | When |
|---|---|
| `COMPLETED` | a verified plan with no plan issue **and** official requirements verified |
| `PARTIAL` | exactly one of the two succeeded |
| `FAILED` | neither succeeded |

`COMPLETED` never means novelty is proven or evidence is sufficient. The workflow
itself completes in all three cases; what did not succeed is recorded on the run.

---

## 3. Research branches and coverage

```text
OFFICIAL_REQUIREMENTS   ACADEMIC   PATENT   PRODUCT   OPEN_SOURCE   STANDARDS
```

The Phase 0 value `OFFICIAL` was renamed `OFFICIAL_REQUIREMENTS`; `OFFICIAL` remains
an enum alias, and the legacy serialized string loads through `_missing_`.
`STANDARDS` was added.

Only `OFFICIAL_REQUIREMENTS` retrieves in Phase 2A.

`BranchExecutionCoverage` records `required`, `planned`, `started`, `completed`,
`failed`, `query_count`, `candidate_count`, `verified_source_count`,
`failure_reason` and a `note`. Validators forbid impossible combinations
(completed and failed; started without a plan; failed without a reason; more
verified sources than candidates).

Required-branch policy V1: `OFFICIAL_REQUIREMENTS`, `ACADEMIC` and `PATENT`
(architecture 2.3, 2.4, 13). Product, open-source and standards are
project-dependent and not required by default.

**Coverage describes execution, not evidence quality.** An academic branch with six
verified queries is `planned`, not `started`.

This is distinct from the Phase 0 `BranchCoverage` inside `NoveltyAssessment`,
which the novelty trust gate consumes and which Phase 2A does not touch.

---

## 4. The research input boundary

`src/research/inputs.py`

| Allowed input | Condition |
|---|---|
| `problem.statement`, `solution.description`, `goal` | `KNOWN` only |
| `technical.technologies`, `hardware`, `software`, `sensors`, `algorithms`, `models`, `datasets`, `data_sources` | intake-verified list values |
| `methodology.baseline`, `methodology.metrics` | intake-verified list values (benchmark queries) |
| `identity.domain`, `identity.project_type` | verified classification, excluding `UNKNOWN` |
| `claims.<C-id>` | `origin=STUDENT` claims only |

Never inputs: UNKNOWN, CONFLICTED or `INFERRED_NON_CRITICAL` values;
`identity.project_name`; `model_summary`; rejected extractions; agent-derived
claims; anything external.

`resolve_research_field()` returns `None` for an invalid reference and `[]` for a
valid path with no trusted value. Student claims generate investigation queries
but are never assumed true: a "no one has done this before" claim can drive
prior-art queries and never sets novelty.

---

## 5. Query planner

`src/research/planner.py`, prompt `RESEARCH_QUERY_PLANNER_PROMPT_V1`
(`src/llm/prompts.py`). Uses the existing `StructuredModelProvider`; no second
provider architecture. English only.

The planner is told to test the project rather than defend it, use only the input
fields, assume no missing facts, not evaluate novelty or quality, separate source
terms from expansion terms, avoid personal data, and respect the budget.

With no trusted input the model is **not called**.

### Query families

`QueryPurpose`: `PROBLEM`, `EXISTING_SOLUTIONS`, `TECHNOLOGY`, `RECENT_WORK`,
`LIMITATIONS`, `BENCHMARK`, `REVIEW`, `ALTERNATIVES`, `FAILURE_MODES`,
`COMPETING_METHODS`, `PRIOR_ART`, `PATENT_FUNCTION`, `PATENT_MECHANISM`, `PRODUCT`,
`OPEN_SOURCE`. No free-form purposes.

Purposes are constrained per branch (`ALLOWED_PURPOSES_BY_BRANCH`): patent purposes
only on `PATENT`, `PRODUCT` only on `PRODUCT`, `OPEN_SOURCE` only on `OPEN_SOURCE`,
and so on. `OFFICIAL_REQUIREMENTS` is not plannable — it is URL-seeded.

Relevance controls planning: no family is required for every project.

### Anti-confirmation-bias policy

* **Challenge families:** `LIMITATIONS`, `ALTERNATIVES`, `FAILURE_MODES`,
  `COMPETING_METHODS`, `BENCHMARK`.
* **Advocacy phrasing is rejected** (`CONFIRMATION_BIASED_PHRASING`): "advantages of",
  "benefits of", "why …", "proves", "best …", "superior", "better than", "success of".
  Declaring such a word as an expansion does not bypass the rule.
* **Plan-level check:** a plan containing any solution-oriented query
  (`TECHNOLOGY`, `EXISTING_SOLUTIONS`, `PRIOR_ART`, `RECENT_WORK`, `PRODUCT`,
  `OPEN_SOURCE`, `PATENT_*`) must contain at least one challenge query, or the plan
  carries `QUERY_PLAN_CONFIRMATION_ONLY` and the run cannot be `COMPLETED`. A
  problem-only plan is not confirmation bias.

---

## 6. Query provenance: source versus expansion terms

`ResearchQuery` carries `branch`, `purpose`, `query`, `normalized_query`,
`derived_from` (the canonical fields), `source_terms` (term + field),
`expansion_terms`, `status`, `rejection_reasons`, `planner_version`, `created_at`.

* **Source terms** originate in trusted canonical state. Every token of a source term
  must occur in the value of the field it names, and in the query text.
* **Expansion terms** are search vocabulary — synonyms, broader concepts, competing
  techniques. They need not exist in `ProjectState` and are explicitly not facts.
* **Every query word** must be a source-term word, an expansion-term word, or one of
  the reviewed generic search words in `QUERY_CONNECTOR_TOKENS`
  (`src/research/vocabulary.py`). An undeclared implementation detail ("Jetson
  Nano") makes the query `UNTRACEABLE_QUERY_TOKEN`.

Expansion terms cannot mutate project facts **structurally**: `ResearchQuery` is not
reachable from `ProjectState`, and no model reachable from `ProjectState` has an
`expansion_terms` field (tested by walking the type graph). They cannot mutate it
**behaviourally** either: planning is a pure read, asserted by
before/after equality in unit tests, graph tests and a release-blocking eval metric.

---

## 7. Query budget

`QueryPlanLimits` (recorded on every plan):

| Limit | Default |
|---|---|
| `max_queries_per_branch` | 6 |
| `max_total_queries` | 24 |
| `max_expansion_terms_per_query` | 4 |
| `max_query_length` | 160 characters |

Budgets are applied deterministically in plan order after per-query validation;
overflow is rejected with `BRANCH_BUDGET_EXCEEDED` or `TOTAL_BUDGET_EXCEEDED`.

---

## 8. Query verification

`src/research/query_verification.py` — pure, no model, no `ProjectState` write.

| Rejection reason | Rule |
|---|---|
| `INVALID_BRANCH` / `BRANCH_NOT_PLANNABLE` | branch must be a plannable `ResearchBranch` |
| `INVALID_PURPOSE` / `PURPOSE_NOT_ALLOWED_FOR_BRANCH` | purpose must be a `QueryPurpose` allowed for the branch |
| `EMPTY_QUERY` / `QUERY_TOO_LONG` | non-empty, within `max_query_length` |
| `NO_SOURCE_TERMS` | at least one source term |
| `INVALID_FIELD_REFERENCE` | field must be an allowed research input (or a student claim) |
| `SOURCE_TERM_NOT_IN_FIELD` | the term's tokens must occur in the trusted field value |
| `SOURCE_TERM_NOT_IN_QUERY` | every declared term appears in the query |
| `UNTRACEABLE_QUERY_TOKEN` | every query word is accounted for |
| `TOO_MANY_EXPANSION_TERMS` / `EMPTY_EXPANSION_TERM` | expansion bounds |
| `PII_DETECTED` | no personal data in query, terms or expansions |
| `SUSPECTED_PROMPT_INJECTION` | no instruction-like text |
| `CONFIRMATION_BIASED_PHRASING` | no advocacy phrasing |
| `DUPLICATE_QUERY` | not a duplicate within its branch |
| `BRANCH_BUDGET_EXCEEDED` / `TOTAL_BUDGET_EXCEEDED` | budget |

### Deduplication

`normalize_query()`: Unicode NFC, whitespace trimming and folding, case folding,
repeated punctuation collapsed, punctuation at the ends removed. Different words are
never merged ("YOLOv8 limitations" and "YOLOv5 limitations" stay distinct). The
duplicate key is `(branch, normalized_query)`: the same query on two branches is two
searches against two provider types. `duplicates_removed` is recorded.

---

## 9. PII policy

`src/research/privacy.py`

Research queries are about the project, never the student. Detected:

| Kind | Detection |
|---|---|
| email | pattern |
| phone number | pattern: 9 or more digits, including Arabic-Indic digits |
| national ID | pattern: 10 digits starting with 1 or 2 |
| person name | identity context; any name token of 3+ characters, whole-token, case-insensitive |
| school name, address, other identifiers | identity context; phrase match |

Applied twice:

1. **Before the model call:** every value in the planner input is redacted
   (`[REDACTED]`), so identity does not reach the model provider.
2. **At verification:** a query, source term or expansion term containing PII is
   rejected, so identity does not reach a research provider.

`ResearchPrivacyContext` is a plain dataclass passed through runtime config. It is
never placed on graph state and therefore never checkpointed.

If a future research task genuinely needs identity, it requires its own explicit
architecture decision.

---

## 10. Official requirements architecture

### Provider abstraction

`src/research/official/provider.py`

```python
class OfficialWebProvider(Protocol):
    name: str
    def retrieve(self, url: str) -> OfficialRetrievalResult: ...
```

* `FakeOfficialWebProvider` — scripted pages, records calls, deliberately does not
  enforce the allowlist so the verifier's enforcement is exercised.
* `HttpOfficialWebProvider` (`http_provider.py`) — httpx, HTTPS only, manual
  redirect following with an allowlist check on every hop, size limit, content-type
  check, script/style-stripped text extraction, publication time only from an
  explicit timezone-aware `article:published_time`. Never raises for a retrieval
  outcome. Standard tests use `httpx.MockTransport` only.

Providers are injected through `config["configurable"]["official_web_provider"]`.

### Official-domain allowlist

`src/research/official/allowlist.py`

```text
mawhiba.sa
www.mawhiba.sa
```

Exact host match. No wildcard subdomains: `portal.mawhiba.sa` is not official until
it is confirmed and listed. Rejected: non-HTTPS schemes, lookalike hosts
(`mawhiba.sa.evil.example`, `evilmawhiba.sa`), userinfo tricks
(`https://www.mawhiba.sa@evil.example/`), backslashes and non-default ports. Both the
requested URL and the final URL after redirects must pass.

The only default seed is `https://www.mawhiba.sa/`. Specific National Olympiad for
Scientific Creativity page URLs must be added to `OfficialRequirementsSettings`
after a reviewer confirms them; they are never guessed, and the settings model
refuses a non-allowlisted seed.

### Source candidate boundary

```text
retrieve_official_candidates  -> SourceCandidate          (untrusted)
verify_official_candidates    -> SourceVerificationDecision
                              -> OfficialSourceSnapshot + SourceRecord
```

Candidate rejection reasons: `RETRIEVAL_FAILED`, `INSECURE_SCHEME`,
`DOMAIN_NOT_ALLOWLISTED`, `REDIRECT_NOT_ALLOWLISTED`, `EMPTY_CONTENT`,
`CONTENT_HASH_MISMATCH`.

### Snapshots and content hashes

`OfficialSourceSnapshot`: `source_id`, `url`, `canonical_url`, `domain`, `title`,
`retrieved_at`, `published_at`, `effective_at`, `content_hash`,
`hash_normalization`, `captured_text`, `verification_status`, `authority`.

* `content_hash` is SHA-256 over text normalized by `TEXT-NORMALIZATION-V1` (line
  endings, NFC, invisible characters, quote folding, whitespace runs). Transport
  noise does not change it; any change of wording does.
* `(canonical_url, content_hash)` identifies a requirements version. **The same URL
  with changed content is a different version.** The same version reached twice in a
  run is snapshotted once.
* Dates are never invented. Without explicit page metadata, `published_at` and
  `effective_at` are `None`.
* The snapshot's `SourceRecord` is `OFFICIAL_COMPETITION_SOURCE`, Tier A,
  `VERIFIED_FULL_TEXT`, provider `OFFICIAL_WEB`.

### Official requirement extraction and provenance

Prompt `OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT_V1`, one structured call per verified
snapshot, the page text after an explicit untrusted-content marker.

Categories: `ELIGIBILITY`, `PROJECT_CATEGORIES`, `SUBMISSION_REQUIREMENTS`,
`COMPETITION_STAGES`, `RESEARCH_ETHICS`, `EXPERIMENT_RESTRICTIONS`,
`JUDGING_CRITERIA`, `SCORING_WEIGHTS`, `DEADLINES`, `FORMS_AND_INSTRUCTIONS`.

The model output is an untrusted candidate. A requirement is accepted only when its
excerpt verifies inside the snapshot text with the intake anchor verifier. Each
accepted `OfficialRequirement` preserves `source_id`, `snapshot_id`,
`content_hash`, `retrieved_at`, the verified anchor with match ranges, and a
canonical `statement` equal to the verified excerpt (verbatim-first, as ADR-004).
The model's wording is kept only as `model_summary`.

Rejections: `INVALID_CATEGORY`, `EMPTY_SUBJECT`, `EMPTY_STATEMENT`, `EMPTY_EXCERPT`,
`ANCHOR_NOT_FOUND`, `SUSPECTED_PROMPT_INJECTION`.

### Requirement status

| Status | When |
|---|---|
| `VERIFIED_CURRENT` | verified, and the snapshot carries an explicit effective or publication date not after retrieval |
| `VERIFIED_BUT_DATE_UNKNOWN` | verified, with no explicit date (or only a future effective date) |
| `CONFLICTED` | in an unresolved conflict with another official source |
| `SUPERSEDED` | a dated newer official source was preferred |
| `UNVERIFIED` | never an accepted requirement; rejected candidates are ledgered instead |

Information is never called current merely because it was retrieved today.

### Conflicting official sources

Items from different sources with the same category and subject but different
statements or weights form an `OfficialRequirementConflict` that keeps **every
side**: requirement, source, statement, weight, effective and publication dates.
The newer source is preferred only when explicit dates on every side establish it
(`NEWER_EFFECTIVE_DATE`, then `NEWER_PUBLICATION_DATE`); the older side becomes
`SUPERSEDED`. Otherwise the conflict is `UNRESOLVED`, every side is `CONFLICTED`, and
the run records `OFFICIAL_SOURCE_CONFLICT`. Nothing is discarded.

### Official versus advisory criteria

A hard trust boundary (`CriteriaAuthority`):

```text
OFFICIAL_MAWHIBA_CRITERIA   only from verified official requirements
AGENT_ADVISORY_RUBRIC       the agent's own ADVISORY_RUBRIC_V1
```

* `official_weight` is accepted only for `JUDGING_CRITERIA` / `SCORING_WEIGHTS` and
  only when the exact weight text occurs inside the verified statement. Otherwise
  it is `None` and `weight_rejection` says why. The `OfficialRequirement` validator
  enforces this independently of the extraction code.
* An official requirement or snapshot can never carry advisory authority.
* `official_weights_are_available()` is true only when every current official
  criterion has a grounded weight and none is in unresolved conflict.
* Release-blocking tests: a model echoing the advisory rubric's weights produces no
  official weight, and `ADVISORY_RUBRIC_V1` is always classified as advisory.

---

## 11. Failure semantics

| Situation | Recorded outcome | Behaviour |
|---|---|---|
| invalid canonical `ProjectState` | `STATE_VALIDATION_FAILED` workflow error | graph ends; no research run is created |
| no trusted research input | `INSUFFICIENT_RESEARCH_INPUT` | planner not called |
| no model provider | `PLANNER_PROVIDER_MISSING` | planning skipped |
| planner refusal or failure | `PLANNER_MODEL_FAILED` | no plan; nothing guessed |
| empty plan / confirmation-only plan | `QUERY_PLAN_EMPTY` / `QUERY_PLAN_CONFIRMATION_ONLY` | run cannot be `COMPLETED` |
| no official web provider | `OFFICIAL_WEB_PROVIDER_MISSING` + `OFFICIAL_REQUIREMENTS_UNAVAILABLE` | no retrieval, no extraction call |
| every candidate fails verification | `OFFICIAL_REQUIREMENTS_UNAVAILABLE` | no extraction call |
| extraction fails for every snapshot | `OFFICIAL_REQUIREMENTS_EXTRACTION_FAILED` | snapshots kept, no requirements |
| unresolved official conflict | `OFFICIAL_SOURCE_CONFLICT` | both sides preserved |

When official retrieval fails the system **never falls back to model memory**.
`ResearchRun.official_requirements_checked` is true only for
`OFFICIAL_REQUIREMENTS_VERIFIED`, so a later trust gate can detect that official
verification did not complete.

### Web-content prompt injection

Page text is data. Instruction-like text cannot change the system prompt (passed as
a constant), the workflow path, `ProjectState`, scores or novelty, and cannot be
accepted as a requirement or as a query. A graph test runs the same project with and
without an injected page and asserts identical node paths, identical prompts and an
unchanged canonical state.

---

## 12. Research graph

`build_phase2a_research_graph()` — `src/graph/phase2a_graph.py`

```text
START
  -> LOAD_PROJECT_STATE ---------(invalid state)---> END
  -> VALIDATE_RESEARCH_INPUT
  -> RESEARCH_QUERY_PLANNER            model -> CandidateQueryPlan (untrusted)
  -> VERIFY_QUERY_PLAN                 deterministic -> VerifiedQueryPlan
  -> OFFICIAL_REQUIREMENTS_RETRIEVAL   provider -> SourceCandidate (untrusted)
  -> VERIFY_OFFICIAL_SOURCES           -> OfficialSourceSnapshot + SourceRecord
  -> EXTRACT_OFFICIAL_REQUIREMENTS     model -> anchor-verified OfficialRequirement
  -> UPDATE_RESEARCH_COVERAGE          coverage + terminal run status
  -> END
```

A node with nothing to do records `SKIPPED`. No node writes the `project` channel.
N03 (`OFFICIAL_REQUIREMENTS_CHECK`) is split into three visible nodes so the source
verification boundary is inspectable. New checkpoint-reachable types are registered
automatically by type discovery; provider DTOs and the privacy enum are declared
non-checkpointed with reasons.

Runtime config keys: `structured_model_provider`, `llm_settings`,
`official_web_provider`, `research_settings`, `research_privacy`,
`research_dataset_version`.

---

## 13. Evals

`evals/research_planning/v1/cases.jsonl` — 32 synthetic cases, schema in
`evals/research_planning/v1/schema.md`. 27 English, 2 Arabic, 3 mixed.

Categories: AI, machine learning, computer vision, IoT, robotics, embedded systems,
software, mixed domain, Arabic, mixed language, minimal description, novelty claim,
performance claim, missing technology, ambiguous technology, prompt injection, PII
contamination, confirmation bias, alternative methods, failure modes, query
duplication, invalid field reference, budget limits, provider failure,
branch/purpose rules, untraceable terms.

The runner (`src/evals/research/runner.py`) drives the real planning path with a
scripted fake provider, and scores it with checks implemented **independently** of
the verifier, so disabling a verifier rule cannot disable the metric watching it.

| Metric | Kind |
|---|---|
| `query_source_traceability` | matched / accepted queries |
| `required_query_family_coverage` | matched / expected families |
| `accepted_query_set_accuracy`, `rejection_reason_accuracy`, `anti_confirmation_accuracy`, `duplicate_removal_accuracy`, `plan_issue_accuracy`, `planner_invocation_accuracy` | matched / asserted |
| `duplicate_query_rate` | duplicates / accepted queries |
| `pii_leakage_rate` | **release-blocking** — violations / outbound texts (planner inputs and accepted queries) |
| `invalid_field_reference_rate` | **release-blocking** — violations / accepted-query references |
| `project_state_mutation_rate` | **release-blocking** — violations / cases |
| `untraceable_accepted_queries` | **release-blocking** — violations / accepted queries |

Every metric exposes numerator and denominator; an unmeasured metric reports `None`.
The gate passes only with zero release-blocking violations and no errored case.

Deterministic results (fake provider, 32 cases):

```text
query_source_traceability        82/82
required_query_family_coverage   71/71
accepted_query_set_accuracy      32/32
rejection_reason_accuracy        36/36
anti_confirmation_accuracy       31/31
duplicate_removal_accuracy        3/3
plan_issue_accuracy              32/32
planner_invocation_accuracy      32/32
duplicate_query_rate              0/82

pii_leakage_rate                  0 violations / 113 checked
invalid_field_reference_rate      0 violations / 129 checked
project_state_mutation_rate       0 violations /  32 checked
untraceable_accepted_queries      0 violations /  82 checked
```

### Negative controls

`tests/test_research_planning_evals.py` disables one protection at a time and
asserts the eval fails: PII detection off → PII leakage detected; field resolution
made permissive → invalid references detected; planning made to write into
`ProjectState` → mutation detected; query-token accounting off → untraceable
queries detected.

---

## 14. Running it

```bash
python -m pytest
python -m src.evals.research.cli            # deterministic research planning eval
python -m src.evals.research.cli --report   # also writes eval_reports/research_planning_<ts>.json

RUN_OFFICIAL_WEB_TESTS=1 python -m pytest tests/test_official_web_integration.py   # live, opt-in only
```

The standard suite needs no API key, no internet and no Mawhiba availability.

---

## 15. Current scope limitations

1. **No academic, patent, product, open-source or standards retrieval.** Plans and
   coverage only.
2. **Official sources are not merged into `ProjectState.sources`.** They live on the
   `ResearchRun`; merging them is a later, separately reviewed stage.
3. **Only the Mawhiba root is seeded by default.** Competition-specific page URLs
   require reviewer confirmation before configuration.
4. **Official conflict grouping depends on the model's `subject` label.** A mislabelled
   subject can hide a conflict or group unrelated items; both sides are always kept.
5. **Token containment is not entailment.** A traceable query can still be a weak one.
6. **The connector vocabulary is English-only**; Arabic function words must be
   declared as expansions.
7. **PII detection is pattern- and context-based.** A name not supplied in the
   identity context and not matching a pattern is not detected.
8. **HTML text extraction is minimal** (stdlib parser). JavaScript-rendered pages and
   PDFs are unsupported.
9. **No approved baseline file for research planning evals**; the gate is absolute
   (zero violations), not relative.
10. **No live planner eval.** All planning numbers come from scripted responses and
    measure the pipeline, not a model.
11. **Required-branch policy is static** (official, academic, patent), not derived
    from project type.
