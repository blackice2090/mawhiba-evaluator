# Data Contracts — Phase 0

**Status:** Implemented
**Source of truth:** `docs/mawhiba_agent_system_architecture_v1.md`
**Scope:** Contracts only. No workflow, no connectors, no UI.
**Language:** English (developer layer). See [Language Policy](#12-language-policy).

This document explains every schema built in Phase 0: what it is, why it exists,
and how it relates to the rest of the model. It is written so that anyone can
answer the question the architecture sets as the quality bar (section 43):

> "Why did you give this judgement?"

Section numbers below refer to the architecture document.

---

## 1. Overall Map

```text
SourceRecord ──(1:N)──▶ EvidenceRecord ──(N:M)──▶ ClaimRecord
     │                        │                        │
     │                        │                        ▼
     └──(1:N)──▶ PriorArtRecord                  FindingRecord
                        │                              │
                        ▼                              ▼
                 NoveltyAssessment ──────────────▶ ScoreRecord (axes)
                                                       │
              ContradictionRecord ─────┐               │
              MissingInformation ──────┼──────▶ TrustGateResult
                                       │               │
                                       └───────▶ finalization_allowed
```

The governing rule: **nothing reaches the report without a complete path back to
a source.**

---

## 2. Canonical State

### `ProjectState` — `src/graph/state.py`

**What it is:** the single authoritative state of one project version (section 6).

**Why it exists:** LangGraph owns execution, but `ProjectState` owns the truth.
The report (section 23), the score (section 20) and the trust gate (section 21)
are all **derived** from it and never add information of their own.

**What makes it canonical:**

1. Every record collection (sources / evidence / claims / prior_art / findings /
   scores) lives inside it as a list, not in scattered variables.
2. A single `model_validator` checks **referential integrity** across the whole
   graph: every `evidence.source_id` exists, every `claim.evidence_ids` exist,
   every `axis.finding_ids` exist, and no id is duplicated. This is the only
   place where the graph can be validated as a whole.
3. It round-trips to JSON without loss (tested), so it serves as
   `project_state_snapshots` in the database (section 28) and as the LangGraph
   checkpoint payload.
4. `project_version_id` is separate from `project_id`: a substantive edit creates
   a new version and never erases the previous evaluation (section 29).
5. Since Phase 1C it owns every canonical intake destination: `goal`,
   `student_contribution`, `current_stage` at the root, and `technologies`,
   `data_sources`, `prototype_status` under `technical`. Nothing a verified
   extraction produces is homeless (`docs/phase1c_intake_evals.md`).
6. `identity.domain` uses the single canonical `TechnicalDomain` taxonomy shared
   with the intake classifier (ADR-005). Legacy Phase 0 / Phase 1B spellings
   migrate through an explicit table, so old snapshots still load.
7. It carries **no workflow execution state**. Completed nodes, pending nodes,
   the current node, interrupt state, workflow errors and run identifiers belong
   to `EvaluationGraphState` alone (ADR-002). A project snapshot therefore stays
   meaningful independently of the orchestration engine that produced it.

**Derived views** (computed properties, not stored data):
`official_score`, `advisory_score`, `unresolved_critical_contradictions`,
`critical_missing_information`, `blocking_findings`, `sources_for_claim(claim_id)`.

`sources_for_claim` in particular implements the provenance chain:
**Claim → Evidence → Source**.

---

## 3. Zero Assumption — `Tracked[T]`

`src/schemas/common.py`

**The problem:** section 6 shows fields as `null`. But `null` cannot distinguish
three entirely different situations:

* the student never mentioned it;
* the model inferred it non-critically;
* two sources disagree about it.

**The solution:** every critical field is wrapped in `Tracked[T]`:

| Field | Meaning |
|---|---|
| `value` | the value, or `None` |
| `status` | `KNOWN` / `INFERRED_NON_CRITICAL` / `UNKNOWN` / `CONFLICTED` |
| `origin` | `STUDENT_MESSAGE` / `STUDENT_FILE` / `EXTERNAL_SOURCE` / `OFFICIAL_SOURCE` / `AGENT_INFERENCE` |
| `certainty` | optional `[0,1]` |
| `location` | where it was found: page, section, message id |
| `conflicting_values` | the competing values when `CONFLICTED` |

**Enforced constraints (section 2.1):**

* `KNOWN` without a value is rejected.
* `UNKNOWN` carrying a value is rejected. This is exactly what stops a guess from
  leaking into a field that is supposed to be unknown.
* `CONFLICTED` requires at least two conflicting values, and `value` stays `None`
  — the system **does not pick a side**.
* `origin=AGENT_INFERENCE` combined with `status=KNOWN` is rejected. A model
  inference is never promoted to knowledge.

Note on language: a `Tracked` **value** may hold Arabic text when it came from
the student. The field names, statuses and origins are always English. See
section 12.

---

## 4. Research and Evidence Contracts

### `SourceRecord` — `src/schemas/source.py`

**What it is:** an external source after retrieval and deduplication (section 7.1).

**Why:** every judgement must trace back to a source a reviewer can open and
verify.

**Critical fields:**

* `verification_status` — `UNVERIFIED` → `SEARCH_RESULT_ONLY` →
  `VERIFIED_METADATA` → `VERIFIED_FULL_TEXT`. A search hit alone is **not
  evidence** (node N06A), and the trust gate blocks finalization when a strong
  claim rests on an unverified source.
* `tier` — the section 11 classification (A/B/C/D). Tier D alone never supports a
  substantive judgement.
* `quality` — five `[0,1]` signals: authority, relevance, methodological_strength,
  recency_fit, independent_validation. An internal ranking number, explicitly not
  a scientific truth value.
* `content_hash` + `retrieved_at` + `version_or_publication_date` — mandatory for
  official competition sources (section 2.4): an official source without both
  `url` and `content_hash` is **rejected at construction time**.
* `duplicate_of` — the output of node N07, pointing at the surviving source.

### `ResearchQueryRecord`

The search coverage log (section 27). Its existence is what makes "is the search
complete?" a question answerable from data rather than from impression. A branch
is never complete on the strength of one query — `BranchCoverage` rejects
`COMPLETED` without `query_ids`.

### `EvidenceRecord` — `src/schemas/evidence.py`

**What it is:** an atomic statement extracted from a source (section 7.2).

**Why it is a first-class entity:** it is the only bridge between a source and a
claim. There is no free-floating evidence: `source_id` is **mandatory** in the
schema itself.

**Constraints:**

* Evidence marked `verified=True` must carry a location anchor (quote, section or
  page) — otherwise the word "verified" means nothing.
* `strength=STRONG` requires `verified=True`.
* `support_direction` distinguishes `SUPPORTS` / `CONTRADICTS` / `NEUTRAL` /
  `MIXED`, so counter-evidence is a first-class citizen of the model.
* `location.quote_or_extract` preserves the source text verbatim, including
  Arabic, without translation.

---

## 5. The Claim / Evidence / Source Relationship

### `ClaimRecord` — `src/schemas/claim.py`

**What it is:** any evaluable assertion (section 7.3).

**The relationship:**

```text
ClaimRecord.evidence_ids          ──▶ EvidenceRecord.evidence_id
ClaimRecord.counter_evidence_ids  ──▶ EvidenceRecord.evidence_id
EvidenceRecord.source_id          ──▶ SourceRecord.source_id
```

Claim-to-evidence is **N:M**: one piece of evidence may support several claims,
and one claim may require several pieces of evidence.

**Status rules (section 2.2, enforced in the schema rather than merely advised):**

| Status | Requirement |
|---|---|
| `VERIFIED` | `evidence_ids` non-empty **and** `missing_evidence` empty |
| `SUPPORTED` | same requirement |
| `PLAUSIBLE` | partial evidence, or none, is allowed |
| `UNSUPPORTED` | `evidence_ids` **must** be empty, and `confidence <= 0.25` |
| `CONTRADICTED` | requires `counter_evidence_ids` |

Additionally, the same evidence may not both support and contradict one claim.

**`required_evidence` / `missing_evidence`:** this is the section 17 mechanism.
The claim "the system is more accurate" requires
`BASELINE + TEST_DATA + METRIC + REPEATED_MEASUREMENTS`. As long as any of those
remains in `missing_evidence`, the status **cannot be raised to SUPPORTED** — the
schema rejects it.

**`is_traceable`:** a claim is traceable when its status is justified by evidence,
**or** when it honestly declares it has none. An `UNSUPPORTED` claim is traceable
— honesty is not a defect.

---

## 6. Prior Art and Novelty

### `PriorArtRecord` — `src/schemas/prior_art.py`

**Why:** section 12 rejects the naive question "does the same project exist?" and
replaces it with a multi-dimensional comparison.

`SimilarityDimensions` has ten dimensions, all **optional**, and the distinction
is deliberate:

* `None` = the dimension was not assessed.
* `0.0` = it was assessed and there is no similarity.

Conflating the two is precisely the kind of silent assumption section 2.1
forbids. Accordingly, a `HIGH`/`CRITICAL` `novelty_threat` requires at least one
assessed dimension.

### `NoveltyAssessment`

Carries `level` (0–5), `status`, `closest_prior_art_ids`, `differentiators` and
`branch_coverage`.

The schema enforces the structural minimum: `level` cannot be set while
`status=NOT_EVALUATED`, and a `FINAL` judgement at level 4 or above requires
identified prior art. The full section 13 preconditions for levels 4/5 (completed
academic and patent search, a clear differentiator) are enforced in the **trust
gate**, because they are tunable policy rather than a structural invariant.

### `GapAssessment`

Section 14. `FINAL` requires a written gap statement **and** `evidence_ids`.
Anything else stays `NOT_EVALUATED`, which is the explicit equivalent of
`GAP_NOT_ESTABLISHED`.

---

## 7. The Score / Findings Relationship

### `FindingRecord` — `src/schemas/finding.py`

**What it is:** a defect, risk or observation with an explicit reason
(section 7.5).

`reason` is a **mandatory** field: a label alone ("weak methodology") is not a
review. `origin` separates Red Team output (section 19) from the rest, because
Red Team independence is part of the acceptance criteria (section 39, item 9).

### `ScoreRecord` / `ScoreAxis` — `src/schemas/score.py`

**How the score links to findings:**

```text
ScoreAxis.evidence_ids ──▶ EvidenceRecord   (why it earned this score)
ScoreAxis.finding_ids  ──▶ FindingRecord    (why it did not earn more)
```

An axis without `evidence_ids` cannot carry `confidence=HIGH`. The score is
therefore **readable in reverse**: from the number to the findings, to the
evidence, to the sources.

**Arithmetic rules (section 20 — the LLM does not sum the score):**

* `score > max_score` is rejected.
* `score=None` is the default for an unscored axis. It is **not zero**. Zero is a
  judgement; absence is not.
* `total` is only accepted when **every** axis is scored, and it must equal their
  sum exactly. A partial sum misrepresents the evaluation.
* `status=FINAL` requires a `total` and rejects any provisional axis.
* `INSUFFICIENT_EVIDENCE` on an axis forbids a score entirely (section 2.6).

**Official versus advisory:** `official`, `rubric_kind` and `rubric_version` are
mutually constrained — `OFFICIAL-*` implies `official=True` and vice versa. A
`Rubric` of kind `OFFICIAL` requires a `source_id` proving the weights were
**retrieved and not invented** (section 2.4, node N03).

`ADVISORY_RUBRIC_V1` in `src/scoring/models.py` has 9 axes totalling exactly 100.

---

## 8. How the Trust Gate Works

`src/schemas/trust.py` (the contract) and `src/trust/models.py` (the policy).

**Design principle:** the trust gate contains **no LLM at all**. It is a pure
function:

```text
evaluate_trust_gate(ProjectState, TrustPolicy, stage_flags) -> TrustGateResult
```

The same state always produces the same result, and this is asserted explicitly
(`test_gate_is_deterministic`). The reason: this is the most important layer in
the system (section 21), and a layer that cannot be tested cannot be trusted.

### Inputs

Three metrics computed from the state:

| Metric | How it is computed |
|---|---|
| `search_coverage` | fraction of **required** branches that are satisfied (section 27) |
| `source_quality` | mean of the five quality signals over non-duplicate sources (section 11) |
| `claim_traceability` | fraction of claims whose status is justified by evidence (section 2.2) |

Plus stage flags that cannot be derived from the data alone and are passed in
explicitly by the workflow rather than guessed: `red_team_complete`,
`final_verifier_passed`, `official_requirements_checked`.

### Outputs

`TrustGateResult` carries the metrics, completion flags and counts, then:

* `score_status` — `FINAL` / `PROVISIONAL` / `INSUFFICIENT_EVIDENCE`
* `finalization_allowed`
* `blockers: list[TrustBlocker]` — each with a closed `BlockerCode`, a
  human-readable detail, and the record ids that triggered it.

**Structural invariant:** `finalization_allowed=True` alongside any blocker is
**rejected at the schema level**. A self-contradictory result cannot even be
constructed.

### Hard Blockers (section 21)

| Code | Triggered when |
|---|---|
| `INVENTED_OR_UNVERIFIED_CITATION` | a source cited by a strong claim is unverified |
| `UNRESOLVED_CRITICAL_CONTRADICTION` | a `CRITICAL` contradiction is unresolved |
| `NOVELTY_SEARCH_INCOMPLETE` | a required branch is incomplete, or level >= 4 without prior art / differentiator |
| `MISSING_EVIDENCE_FOR_HIGH_CONFIDENCE_CLAIM` | a claim is not traceable |
| `CLOSEST_PRIOR_ART_NOT_IDENTIFIED` | a novelty judgement precedes prior-art identification |
| `CRITICAL_INFORMATION_MISSING` | missing critical fields exceed the policy allowance |
| `SEARCH_COVERAGE_BELOW_THRESHOLD` | search coverage below threshold |
| `SOURCE_QUALITY_BELOW_THRESHOLD` | mean source quality below threshold |
| `CLAIM_TRACEABILITY_BELOW_THRESHOLD` | traceability below threshold (default 1.0) |
| `CRITICAL_FINDING_UNADDRESSED` | a `CRITICAL` finding, or one flagged as blocking |
| `METHODOLOGY_REVIEW_INCOMPLETE` | the methodology review has not reached `FINAL` |
| `RED_TEAM_INCOMPLETE` | the Red Team pass has not run |
| `OFFICIAL_RULE_ASSERTED_WITHOUT_OFFICIAL_EVIDENCE` | official requirements were never checked |
| `FINAL_VERIFIER_NOT_PASSED` | the final verifier has not passed |

### Policy Is Tunable and Versioned

`TrustPolicy` carries a `version` and adjustable thresholds. Changing a threshold
is a **reviewable, regression-testable event** (section 34), not a silent code
edit. The version in force is recorded in every `TrustGateResult`.

---

## 9. Fixtures

`tests/fixtures/projects.py` — entirely synthetic data. **No real student data is
used.**

### Fixture A — an AI project with incomplete information

A crop-disease detector. It proves the system represents **absence** honestly:

* `solution.technical_principle` is `UNKNOWN` with no invented value.
* `methodology.baseline` and `metrics` are empty, and the review status is
  `INSUFFICIENT_EVIDENCE`.
* Conflicting accuracy: 95% on the poster versus 87% in the report, stored as
  `CONFLICTED` with both values kept and `value=None`.
* An open `CRITICAL` contradiction awaiting the student.
* Two `UNSUPPORTED` claims with complete `missing_evidence` lists.
* Two critical missing fields, both not retrievable externally, which therefore
  warrant asking the student (section 24).

Result: the trust gate refuses finalization with at least four blocker types, and
`score_status = INSUFFICIENT_EVIDENCE`.

### Fixture B — a complete engineering project

An in-pipe water leak detector containing the full chain:
problem → solution → baseline → experiments → claims → evidence → sources → score.

* 3 verified sources (a peer-reviewed paper, a patent, a datasheet) across three
  completed research branches.
* 4 pieces of evidence, all location-anchored and verified.
* 3 claims: two `SUPPORTED`, and one `PLAUSIBLE` (battery life) because its
  measurement is missing.
* Ranked prior art (top 2) with assessed similarity dimensions.
* Novelty level 3 (measurable improvement) with `PROVISIONAL` status.
* Advisory score 68/100, every axis backed by evidence.

Result: the trust gate allows finalization once Red Team, the final verifier and
the official requirements check are reported complete; dropping any one of them
returns the project to `PROVISIONAL`.

---

## 10. Canonical Versus Derived

| Canonical (stored) | Derived (computed) |
|---|---|
| `ProjectState` and all its lists | `TrustGateResult` |
| `SourceRecord`, `EvidenceRecord` | `search_coverage`, `source_quality`, `claim_traceability` |
| `ClaimRecord` and its links | `ScoreRecord.total` |
| `FindingRecord`, `ContradictionRecord` | the entire final report (section 23) |
| `ScoreRecord.axes` (the assessments) | `official_score` / `advisory_score` / `blocking_findings` |
| `TrustPolicy` and `Rubric`, with versions | `ConfidenceLevel.from_score` |

Workflow execution state is canonical too, but it is owned by a different model:
`EvaluationGraphState` (see `docs/phase1a_workflow.md` and ADR-002). The two
never overlap -- a test asserts they share no field name.

The rule: **if it can be computed from the state, it is not stored as an
independent fact** — otherwise it will eventually contradict itself. The report in
particular never generates new information (section 23); it is a presentation
layer.

---

## 11. Phase 0 Boundaries

Deliberately not built yet:

* No LangGraph graph, no nodes, no router.
* No external API connectors.
* The scoring engine does not populate axes yet — `ScoringInput` is the contract
  only; the logic belongs to Phase 1.
* `src/config/settings.py` holds contract-level policy only. Secrets and provider
  keys arrive in Phase 2 (section 36).

---

## 12. Language Policy

The project separates layers strictly:

```text
Developer Layer            = English only
Internal Agent Layer       = English only
Structured Data Layer      = English only
Student Presentation Layer = Arabic-first
```

Declared in `src/config/settings.py` as `DEVELOPER_LANGUAGE = "en"` and
`STUDENT_DEFAULT_LANGUAGE = "ar"`, and exposed on `ContractSettings`.

**English only:** module, class, function and variable names; comments and
docstrings; exception and log messages; test names; JSON keys; schema field
names; enum names and enum values; API paths; database field names; tracing
metadata; internal prompts for every node (extraction, research planning,
academic and patent analysis, novelty, methodology, red team, claim-evidence,
final verification, jury orchestration); and all CLI and developer
documentation.

**Arabic is allowed only as data**, never as structure. When a student writes in
Arabic, the original text is preserved verbatim in value positions — claim text,
`Tracked.value`, `EvidenceLocation.quote_or_extract`, problem and solution
statements — and never translated for storage. `ProjectIdentity.language`
defaults to `"ar"` because it describes the student's project, not the system.

A valid record therefore looks like this:

```json
{
  "claim_id": "C-001",
  "claim": "النظام يقلل استهلاك الطاقة بنسبة 20%",
  "claim_type": "PERFORMANCE",
  "status": "UNSUPPORTED"
}
```

The value may be Arabic because it came from the student. The structure stays
English.

Internal prompts remain English even when the project under evaluation is
Arabic, for example:

```text
Analyze the student's project description.
Extract only explicitly supported information.
Do not infer missing critical facts.
Preserve Arabic source text when quoting student-provided content.
Return structured JSON matching ProjectState.
```

`docs/mawhiba_agent_system_architecture_v1.md` is the original architectural
source artifact and is exempt: it stays as authored. Implementation documentation
derived from it, including this file, is English.
