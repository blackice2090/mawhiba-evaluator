# Phase 1C — Canonical Intake Model, Verbatim Extraction, Trust Evals

**Status:** Implemented
**Scope:** Canonical intake destinations, one domain taxonomy, first-class
technologies, verbatim-first extraction, and the Gold evaluation dataset.
**Decision records:** ADR-004 (verbatim-first), ADR-005 (single taxonomy)
**Prior phases:** `docs/phase1b_trusted_intake.md`, `docs/data_contracts.md`

---

## 1. Why this phase exists

Phase 1B was approved with four structural issues recorded. Each of them would
have been inherited — silently — by every later phase, because research,
methodology review and scoring all read the canonical state as ground truth:

| Issue | Consequence if left |
|---|---|
| Five verified fields had no canonical destination | Verified facts discarded at merge |
| Domain taxonomy lossy between classifier and state | Research routing on a degraded signal |
| Technologies approximated as software | LoRa and LiDAR filed as software packages |
| No eval measuring unsupported-field acceptance | The core safety property unmeasured |

The core principle for this layer:

> The canonical intake layer answers **what exactly did the student provide?**
> It does not yet answer whether that is scientifically true. And it must never
> convert one technical concept into another merely because the schema lacked a
> destination.

---

## 2. Canonical field additions

Five previously orphaned fields now have semantic owners:

| Extraction field | Canonical destination | Why there |
|---|---|---|
| `goal` | `ProjectState.goal` | What the project sets out to achieve — distinct from `problem.statement` (what is wrong) and `solution.description` (what was built) |
| `student_contribution` | `ProjectState.student_contribution` | What the student personally did; feeds the Red Team integration-only question (architecture 19) |
| `current_stage` | `ProjectState.current_stage` | How far the project has progressed |
| `prototype_status` | `technical.prototype_status` | What has actually been built — a property of the artifact, not of the project's progress |
| `data_sources` | `technical.data_sources` | Where data came from — distinct from `datasets`, which names the dataset |

`current_stage` and `prototype_status` are deliberately separate: a project can
be at the testing stage with no prototype, or have a prototype while still in
design.

All five are Zero-Assumption aware: `Tracked[str]` defaulting to `UNKNOWN`, no
fake defaults, provenance preserved, serializing and checkpointing correctly.
`UNMAPPED_FIELDS` is now empty and a test asserts every extraction field is
mapped.

---

## 3. Technology model

Phase 1B routed every extracted technology into `technical.software`. That is
wrong for most of them:

```text
LoRa · LiDAR · BLE · MQTT · Edge Computing · Computer Vision
Kalman Filtering · Digital Twin · ROS · FPGA · AI
```

None of these is a software package. Filing them as software would have told
later research routing that a LoRa mesh project is a software project.

`technical.technologies` is now a first-class collection, and the technical
categories are distinct and non-overlapping:

```text
technologies   general technologies and techniques
hardware       physical components
software       named software, libraries, frameworks
sensors        sensing components
algorithms     named algorithms and models
models         trained models
datasets       named datasets
data_sources   where data came from
```

A test asserts no two extraction fields share one canonical destination, and a
parametrized test asserts that six representative technologies land in
`technologies` with `software` left empty.

---

## 4. Canonical domain taxonomy

One enum, `TechnicalDomain`, defined in `src/schemas/common.py` and shared by the
classifier DTO and `ProjectState.identity.domain`. The lossy projection is
deleted. Full rationale and the migration table are in ADR-005.

```text
ARTIFICIAL_INTELLIGENCE   MACHINE_LEARNING       DEEP_LEARNING
COMPUTER_VISION           NATURAL_LANGUAGE_PROCESSING
DATA_SCIENCE              CYBERSECURITY          INTERNET_OF_THINGS
ROBOTICS                  EMBEDDED_SYSTEMS       ELECTRONICS
SENSORS                   SMART_SYSTEMS          COMPUTER_SCIENCE
SOFTWARE_ENGINEERING      NETWORKS               EDGE_COMPUTING
CLOUD_COMPUTING           HUMAN_COMPUTER_INTERACTION
OTHER_TECHNICAL           UNKNOWN
```

Old spellings (`AI_ML`, `IOT`, `EMBEDDED`, `HCI`, `OTHER`, `NLP`, and the three
application areas) migrate through an explicit, tested table applied as a
pre-validator, so a Phase 0 or Phase 1B snapshot still loads. An unrecognized
value raises rather than being guessed at.

---

## 5. Verbatim-first extraction

The Phase 1B limitation this closes:

```text
Student wrote:  "The system detects smoke using optical measurements."
Model returned: "The system predicts fire before smoke appears"
                anchored to the real sentence above.
```

The anchor verifies. Phase 1B stored the model's sentence. A smoke detector
became a fire predictor, with provenance attached to the distortion.

Now, for every factual narrative field, **the canonical value is the verified
source span**. The model locates; code decides. The model's phrasing survives as
`VerifiedField.model_summary` — derived, labelled, never canonical, never
overwriting the student's wording.

Student claims follow the same rule: `VerifiedClaim.statement` is the excerpt,
because attributing a paraphrase to a student misquotes them.

Full reasoning, costs and rejected alternatives in ADR-004.

### Extraction modes

| Mode | Canonical value | Applies to |
|---|---|---|
| `VERBATIM_SPAN` | the verified excerpt | `problem_statement`, `solution_description`, `goal`, `student_contribution`, `current_stage`, `prototype_status`, `architecture_description`, `beneficiaries`, `claimed_innovation` |
| `VERBATIM_TERM` | the value; every token must appear in the excerpt | `technologies`, `hardware`, `software`, `sensors`, `algorithms`, `datasets`, `data_sources`, `baseline_mentions`, `metric_mentions`, `project_name` |
| `CLASSIFICATION` | an inferred label with a verified anchor | project type, technical domain |
| `STUDENT_CLAIM` | the student's own words | attributed assertions |

A field arriving under an unsupported mode is rejected with
`UNSUPPORTED_EXTRACTION_MODE` rather than reinterpreted.

---

## 6. Conflict handling

**Singleton fields** (`project_name`, `problem.statement`, `goal`,
`solution.description`, …): a new verified value that differs from an existing
`KNOWN` value produces a `CONFLICTED` `Tracked` holding both, **and** a
`ContradictionRecord` with `requires_student_clarification=True`. The
`CONFLICTED` value records that a disagreement exists; the record is what makes
it actionable and what the trust gate can block on.

**List fields**: additions are additions. Turn 1 `Raspberry Pi` and turn 2
`ESP32` coexist — both boards can be in one project. Conflict is not
over-detected.

**Repeats**: an identical value is preservation, not conflict.

---

## 7. Rejected extraction ledger

`RejectedExtraction` is the audit record for a candidate deterministic code
refused:

```text
field · candidate_value · artifact_id · anchor · rejection_code · mode · model_confidence
```

Available as `VerifiedExtraction.ledger`. It is a **derived view** over
`rejected_fields`, which is already checkpointed — storing it separately would
duplicate persisted data and let the two disagree. It carries no hidden
reasoning, and it never touches `ProjectState`.

Rejection codes: `ANCHOR_NOT_FOUND`, `VALUE_NOT_SUPPORTED_BY_ANCHOR`,
`EMPTY_VALUE`, `EMPTY_EXCERPT`, `UNSUPPORTED_FIELD`, `NARRATIVE_NOT_VERBATIM`,
`UNSUPPORTED_EXTRACTION_MODE`, `INVALID_CANONICAL_DESTINATION`, `CONFLICT`.

---

## 8. Gold evaluation dataset

`evals/intake/v1/cases.jsonl` — **80 cases**, plain reviewable JSONL, schema
documented in `evals/intake/v1/schema.md`. All submissions are synthetic; no real
student data.

| | |
|---|---|
| Cases | 80 |
| Languages | 55 English, 18 Arabic, 7 mixed |
| Categories | 30 |

Categories cover complete and incomplete descriptions, missing information,
missing dataset and baseline, generic technology, multi-technology, AI, IoT,
robotics, embedded, software-only, research, engineering, hybrid, ambiguous,
performance and novelty claims, conflicting values, multi-turn updates, prompt
injection, fabricated anchors, valid-anchor/unsupported-value, repeated excerpts,
Unicode and whitespace normalization, technical abbreviations, domain and
project-type ambiguity, verbatim spans, and provider failures.

### Independence

Gold expectations are authored **from the submission text alone**. The `scripted`
block describes what a possibly-misbehaving model returns; `expected` describes
what the system must produce regardless. No model was run and then declared
correct — that measures agreement, not correctness.

---

## 9. Metrics

| Metric | Question |
|---|---|
| `accepted_field_precision` | Of fields that became KNOWN, how many are correct? |
| `unknown_preservation` | When Gold says absent, did it stay UNKNOWN? |
| `provenance_validity` | Do accepted facts carry valid anchors? |
| `list_field_accuracy` | Are list contents exactly right? |
| `project_type_accuracy` | Correct type on unambiguous cases |
| `domain_precision` / `domain_recall` | Multi-domain correctness |
| `conflict_precision` / `conflict_recall` | On explicit conflict cases |
| `canonical_merge_stability` | Does earlier KNOWN survive later turns? |
| `student_claim_isolation` | Do claims stay student-origin and unsupported? |
| `rejection_accuracy` | Were the right candidates refused? |

Every metric reports `matched/total`, never a bare rate — an unmeasured metric
returns `None`, which is not the same as zero.

### Deterministic results (fake provider, 80 cases)

```text
accepted_field_precision   31/31   = 1.000
unknown_preservation       60/60   = 1.000
provenance_validity        30/30   = 1.000
list_field_accuracy        77/77   = 1.000
project_type_accuracy      16/16   = 1.000
domain_precision           22/22   = 1.000
domain_recall              22/22   = 1.000
conflict_precision          6/6    = 1.000
conflict_recall             6/6    = 1.000
canonical_merge_stability   5/5    = 1.000
student_claim_isolation     9/9    = 1.000
rejection_accuracy          7/7    = 1.000
```

---

## 10. Safety targets

Four release-blocking rules, target zero:

```text
unsupported_known_acceptance   0 violations / 102 checked
invalid_provenance_acceptance  0 violations /  30 checked
student_claim_leakage          0 violations /  16 checked
prompt_injection_mutation      0 violations /   4 checked
```

Counted rather than rated: the target is zero, and a rate would dilute a single
violation into a reassuring percentage.

### The eval can fail

A suite that always passes measures nothing. Two negative-control tests disable a
trust gate and assert the metrics catch it:

* value-support check disabled → 3 unsupported-known violations, `safety_clean` False
* anchor verification disabled → 4 unsupported-known violations, `safety_clean` False

---

## 11. Baseline and regression gate

`evals/intake/baselines/v1.json` holds the approved snapshot. Every result
records its provenance — dataset version, extractor and classifier prompt
versions, provider, model, mode, code version when available — because a score
without those is not reproducible.

`evaluate_gate()` classifies every metric as `IMPROVED`, `UNCHANGED`,
`REGRESSED` or `NEW`, and fails on either of two independent conditions:

1. any safety violation at all, regardless of the baseline;
2. a regression in a critical safety metric relative to the baseline.

A **quality** regression is reported but does not block: a deliberate
precision/recall trade is a reviewer's decision, not a gate's.

The approved baseline is **never** overwritten automatically. `write_baseline()`
marks a file as a draft unless `approve=True` is passed explicitly, and the CLI
requires `--approve-baseline`. A baseline that silently tracks current behaviour
records nothing.

---

## 12. Live eval policy

```bash
python -m src.evals.cli                    # deterministic, CI default
python -m src.evals.cli --live             # needs RUN_OPENAI_INTAKE_EVALS=1
python -m src.evals.cli --approve-baseline
```

Live mode never runs implicitly. **An API key being present is deliberately not
sufficient** — a developer with a key in their environment must not incur cost by
running the suite. Without the flag the CLI prints `Live intake eval: NOT RUN`
and exits 0; that is not a failure.

Cost safety: live runs default to `DEFAULT_LIVE_CASE_CAP` (10) cases, adjustable
with `OPENAI_EVAL_MAX_CASES`; the model is set with `OPENAI_EVAL_MODEL`;
escalation is **disabled**, so a low-confidence classification can never silently
reach the stronger model during a sweep.

Reports are written to `eval_reports/intake_<timestamp>.json`, which is
git-ignored: a generated measurement is not a source artifact.

---

## 13. Intake completeness

`INTAKE_MINIMUM_FIELDS_V1` is **not** defined in this phase. `PHASE_1A_DEMO_GATE`
remains exactly what it was — an infrastructure demonstration gate, unchanged and
clearly separate.

Intake completeness is not project quality, and conflating them would produce a
readiness score that measures how much a student typed.

---

## 14. Limitations

1. **Span relevance is not verified.** A `VERBATIM_SPAN` value is guaranteed to be
   the student's words; it is not guaranteed to be the *right* words for that
   field. A model can anchor a real but irrelevant sentence to `goal`. The
   failure mode is now "quoted accurately, filed under the wrong heading" —
   visible and correctable — rather than fabrication.
2. **Conflict detection is model-proposed.** Code verifies both anchors, but
   finding the conflict is the model's job; a missed conflict is possible.
3. **Numeric conflicts are not detected deterministically.** "2,000 images" and
   "5,000 images" conflict only if the model reports it. No numeric reconciliation
   exists.
4. **Three application areas were lost in migration** (`ENERGY`, `HEALTH_TECH`,
   `ENVIRONMENT` → `OTHER_TECHNICAL`). If application area matters, it needs its
   own field.
5. **`model_summary` is stored but unused.** Deliberate headroom, currently dead
   weight.
6. **The Gold dataset is English-heavy** (55/18/7). Arabic and mixed coverage is
   adequate for the trust properties but thinner for classification nuance.
7. **Live model performance is unmeasured.** Every number here is from scripted
   responses. They measure the *pipeline*, not the model.
8. **`ProjectDomain` remains as an alias** — mild debt.
9. **Text only.** No file, PDF, OCR or link intake.
