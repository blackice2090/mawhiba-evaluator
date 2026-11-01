# Phase 3B: Experiment Review

The contracts are in `src/schemas/experiment_review.py`, the decision is in
ADR-023, and the architecture tests are in `tests/test_phase3b_architecture.py`.
The production runtime is described in section 12. No Gold dataset exists yet.

Phase 3B asks one question: *does the documented experiment / test protocol
provide an adequate and auditable way to test the claim that matters?* It never
asks whether the project succeeded or whether a result is true.

```text
Structured != True            Documented != Adequate        Adequate Protocol != Successful Result
Execution Described != Verified   Metric Present != Aligned   Baseline Present != Fair
Sample Size Present != Adequate   Repetition != Independent Replication
Experiment Exists != Claim Tested   Claim Tested != Claim Supported
Phase 2J Coverage != Experimental Success   Experiment Review != Result Review
```

## 1. Boundary (3A / 3B / Result Review)

| | Phase 3A Methodology | Phase 3B Experiment | Result Review (later) |
|---|---|---|---|
| Object | planned method / design | concrete protocol per experiment | observations, values, interpretation |
| Owns | design requirements, method-claim linkage | protocol requirements, experiment-target linkage, Phase 2J protocol coverage | result validity, support, causality, generalization |
| Execution | never | *described* only (`execution_verified=False`) | n/a |
| Results | none | quarantined, never consumed | owns them |

## 2. Inputs and forbidden inputs

`ExperimentUpstreamPhase` is the closed list of authoritative inputs:
`STUDENT_SUBMISSION` (artifact id, content hash, code-sliced excerpts),
`PROJECT_CLAIMS` (id plus text hash), `PHASE_2J_GAP` (canonical project type,
hypotheses, validation requirements, metric/baseline anchor hashes, condition
ids, limitation facets) and `PHASE_3A_METHODOLOGY` (context only). Each is
fingerprinted at bind and re-checked at finalize. A mismatch sets
`INVALIDATED_UPSTREAM_MUTATED`.

The following are structurally absent from the inputs: `ProjectState.results`,
`ProjectState.experiments` (the legacy `ExperimentRecord` carries
`supports_claim_ids` and `evidence_ids`), Phase 2F scores, the trust gate, and
anything from Result Review, Red Team, Score or Readiness. The schema module
imports no connector, graph or LLM module, and no field is typed with
`src.schemas.project` types.

## 3. State ownership

`ResearchRun.experiment_review: ExperimentReviewRun | None`. `ResearchRun`
validates that the review belongs to this research run, was built over this
Phase 2J run, and was built over this Phase 3A run. Phase 3B mutates neither
Phase 2J nor Phase 3A, and writes nothing into `ProjectState`.

## 4. Experiment model

**Identity (answers Q1 and Q2).** One experiment is one protocol: a distinct
procedure with its own setup, inputs and measurement, identified by the hash of
its defining excerpt texts (`protocol_key`). `experiment_id = uuid5(run,
protocol_key)` is stable on replay and does not depend on offsets. When the same
experiment is described in several places, it is one record with several
defining excerpts. When identical text is repeated, it is the same key and the
same experiment. A repeated *execution* of one protocol is that experiment's
`REPETITIONS` requirement. A *modified* protocol is a new experiment with
`revision_of`. Duplicate keys and shared defining excerpts are rejected.

**Targets (answers Q3 and Q4).** One claim can have zero or more experiments.
One experiment can link to one or more explicit targets. Several experiments may
*attempt* one Phase 2J requirement, and each experiment that covers it fully is
listed in `covering_experiment_ids`. No experiment's dimensions are pooled with
another's.

**Taxonomy.** There are 16 closed types: the 15 specified types plus `UNKNOWN`.
They fall into six families (SCIENTIFIC, ENGINEERING, AI_ML, SOFTWARE,
SIMULATION, OTHER). The family selects the matrix column. It never decides track
ownership.

**Requirement inventory.** 68 kinds in 11 groups (A–K of the plan). Engineering
adds `REQUIREMENT_TRACEABILITY`, `TOLERANCE`, `STRESS_AND_EDGE_CASES` and
`FAILURE_MODES`. Software adds `WORKLOAD`, `WARM_UP` and
`SECURITY_TEST_CONDITIONS`. AI/ML adds the leakage group. Each row has one cell
per family (R/C/O/-), and every C row lists its triggers.

**Applicability matrix** (abridged; `EXPERIMENT_CATALOG` is canonical):

| kind | S | E | A | W | M | O | triggers |
|---|---|---|---|---|---|---|---|
| OBJECTIVE, TARGET_BINDING, HYPOTHESIS_OR_VALIDATION_OBJECTIVE, SUCCESS_CRITERION, SETUP, ENVIRONMENT, INPUTS, OUTPUTS, DEPENDENT_VARIABLE, SAMPLE_DEFINITION, SAMPLE_SIZE, MEASUREMENT_METHOD, METRIC, PROTOCOL_DETAIL | R | R | R | R | R | R | |
| BASELINE, BASELINE_CONFIGURATION | C | C | C | C | C | C | improvement/comparative claim, Phase 2J baseline |
| CONTROL_STRATEGY | C | C | - | - | - | C | assigned intervention, comparative claim |
| REPETITIONS | R | R | C | R | C | C | stochastic, quantitative |
| STATISTICAL_TEST, TEST_ASSUMPTIONS, CONFIDENCE_INTERVAL | C | C | C | C | C | C | statistical inference / generalization claimed |
| RANDOMIZATION | C | - | - | C | - | - | assigned intervention |
| BLINDING | C | C | - | C | - | C | subjective rating, human participants |
| TRAIN_TEST_SEPARATION, TEST_SET_INDEPENDENCE, DUPLICATE_LEAKAGE_CONTROL | - | - | R | - | - | - | |
| TUNING_ISOLATION / BENCHMARK_CONTAMINATION / CLASS_IMBALANCE | - | - | C | - | - | - | tuning / public benchmark / imbalance |
| WORKLOAD, WARM_UP | - | - | - | C | - | - | performance claimed |

Type overrides add requirements by type. A controlled experiment requires a
control strategy. A field test requires operating conditions. A stress test
requires edge cases and failure modes. A comparative engineering test requires a
baseline. An ablation requires independent and controlled variables. External
validation requires external validation. A benchmark or load test requires a
workload and warm-up. A security test requires security conditions. A usability
test requires inclusion/exclusion rules. An observational study makes
randomization not applicable.

**Applicability rules.** Every `ExperimentRequirement` records `applicability`,
`basis` and `triggers` separately from `documentation` and `adequacy`. A
`CATALOG_DEFAULT` or `CATALOG_TYPE_OVERRIDE` must equal what the catalog says.
Only a CONDITIONAL cell may be resolved, and only to REQUIRED (naming the trigger
that fired) or NOT_APPLICABLE. A model-assisted resolution must bind its judgment
excerpts, so omission is never a basis. An unresolved CONDITIONAL stays
CONDITIONAL and blocks `WELL_SPECIFIED`. An `UNKNOWN` type keeps the universal
rows REQUIRED and every other row CONDITIONAL. An assessed experiment resolves
the whole catalog in catalog order.

**Methodology relationship (Q5).** The reference is one-way. A Phase 3A
`RequirementKind` and a Phase 3B `ExperimentRequirementKind` are distinct closed
inventories. Phase 3A is shown to the model as context, and its run id is bound
and fingerprinted. Phase 3A documentation never satisfies, lowers or raises a
Phase 3B requirement.

**Track ownership (Q12).** Each experiment has one `track` or `None`.
`SINGLE_TRACK_PROJECT` is mandatory for, and only for, a single-track project.
HYBRID ownership uses `PHASE_2J_LIMITATION_FACET` (the bound hypotheses' single
facet) or `MODEL_ASSISTED_BOUNDED_JUDGMENT` (with excerpts). Otherwise ownership
is `UNRESOLVED`: the experiment is counted in no track, and the project is capped
at `UNRESOLVED`. A Phase 2J requirement belongs to the only track, or to its
single facet's track. Otherwise it is project-level coverage that no track owns.

## 5. Trust boundaries

**Execution evidence (Q6, Q7, Q19).** `ExecutionStatus` ∈ {`PLANNED_ONLY`,
`EXECUTION_DESCRIBED`, `EXECUTION_STATUS_NOT_DOCUMENTED`}.
`execution_verified`, `independently_reproduced` and
`leakage_prevented_in_practice` are literal False. There is no execution-evidence
field, and raw data, logs and media are not inputs in Phase 3B. A later reviewed
contract would add them. A negative or failed experiment is assessed on its
protocol exactly like any other, and its outcome text is quarantined.

**Result leakage (Q8, Q18).** A result span (reported metric value, statistical
outcome, result table, conclusion, success/failure, causal or generalization
statement, negative outcome) becomes a `QuarantinedSpan`. It keeps offsets and a
hash only, never text. Protocol excerpts may not overlap a quarantined span: the
segmenter must cut "tested 30 samples" out of "tested 30 samples and got 95%". No
derivation function has a quarantine or result parameter.
`adequacy_fingerprint` excludes the quarantine, offsets, the submission hash and
timestamps. Mutation test: change 97% to 41% with the protocol unchanged, and the
fingerprint and postures stay identical. **A student result statement can never
affect Phase 3B adequacy.**

**Phase 2J continuity (Q15, Q16).** `BoundValidationTarget` copies
`validation_requirement_id`, `gap_hypothesis_id`, `claim_id`, the metric anchor
hash, the baseline anchor hash (if any), condition ids and facets. It is `None`
for a hypothesis without a requirement, so nothing is invented. `Phase2JCoverage`
is derived by `derive_phase2j_coverage`:

- no testing link and no unresolved link → `NOT_COVERED`
  (`PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED`);
- only unresolved links → `UNRESOLVED` (`LINKAGE_UNRESOLVED`);
- otherwise, for each testing experiment, check: `DIRECTLY_TESTS`; an aligned
  measurement for *this requirement* with `SAME_AS_PHASE_2J` (otherwise
  `METRIC_TARGET_MISMATCH`, which also covers Q15, a different metric); if the
  requirement has a baseline, a relevant baseline matching it (otherwise
  `BASELINE_TARGET_MISMATCH`); every condition `ADDRESSED_IN_PROTOCOL`
  (otherwise `MATERIAL_CONDITION_UNCOVERED`); and an experiment posture of
  WELL or PARTIALLY (otherwise `COVERING_PROTOCOL_INADEQUATE`, which also covers
  Q14);
- if any experiment passes every check → `COVERED_BY_EXPERIMENT`. Otherwise
  `PARTIALLY_COVERED` with the union of reasons.

When Phase 2J has no baseline (Q16), coverage adds no baseline prerequisite. A
baseline is still REQUIRED in the protocol when an improvement or comparative
claim triggers it.

**Baseline / comparator.** `ExperimentBaselineRecord` keeps six layers apart:
documented, relevant (a bounded judgment that reuses Phase 3A
`BaselineRelevance`), comparability per `FairnessProperty` (same input set,
environment, hardware, preprocessing, metric, resources, tuning), execution
described, `execution_verified=False`, and `comparison_result_evaluated=False`.
Only `SAME_EVALUATION_METRIC` may have a deterministic basis
(`DETERMINISTIC_SHARED_METRIC_BINDING`). Every other property is judged on
excerpts. `rollup()` is derived. It requires the family's property set and never
reports `FAIR`. A documented difference emits `BASELINE_COMPARABILITY_GAP`.

**Measurement / metric (Q15).** `MeasurementBinding` links method → metric → unit
→ success criterion, each as an excerpt id, for one experiment and one target.
`ALIGNED_SAME_TARGET` needs both a method and a metric excerpt. A metric name
alone is not enough. `SAME_AS_PHASE_2J` needs alignment. The metric-target guard
(`directly_tests_supported`) is the only gate for `DIRECTLY_TESTS`.

**Success-criterion timing (Q17).** `SuccessCriterionTiming` ∈
{`PRE_SPECIFIED_AS_DESCRIBED`, `POST_HOC_AS_DESCRIBED`, `TIMING_NOT_DOCUMENTED`}.
A post-hoc criterion emits `SUCCESS_CRITERION_POST_HOC` (HIGH), so the experiment
is `MAJOR_GAPS`.

**Statistics (Q10).** Every statistics row is CONDITIONAL. With no trigger it
resolves to NOT_APPLICABLE ("no p-value" is not invalid). With
`STATISTICAL_INFERENCE_CLAIMED` it resolves to REQUIRED. No field holds a
p-value, an effect size or a significance value.

**Sample (section 14).** `SAMPLE_SIZE` documented is not adequacy. A bare number
("N = 500") can never document `SAMPLE_SIZE_RATIONALE`. No numeric sample field
exists.

**AI/ML leakage (Q11).** Train/test separation, test-set independence and
duplicate leakage are REQUIRED for AI_ML. Tuning isolation, benchmark
contamination and class imbalance are conditional. Missing controls emit
`ML_LEAKAGE_CONTROL_MISSING` (HIGH). `leakage_prevented_in_practice=False`.

**Provider failure semantics.** A missing provider, refusal, invalid output,
exhausted call bound or partial output each have a run-issue code with named
emitting stages. Each fails closed: the requirement becomes
`INSUFFICIENT_SOURCE_COVERAGE`, the type `UNKNOWN`, the link `UNRESOLVED`. Only a
digest of refused model text is persisted (`RejectedExperimentProposal`).

## 6. Postures and failure taxonomy

**Experiment posture** (`derive_experiment_posture`), checked worst first:

1. `INSUFFICIENT_EVIDENCE`: every applicable requirement is
   `INSUFFICIENT_SOURCE_COVERAGE`.
2. `MAJOR_GAPS`: any HIGH or CRITICAL issue.
3. `UNRESOLVED`: the type is UNKNOWN, a CONDITIONAL requirement is unresolved,
   there are no links, or every link is unresolved.
4. `PARTIALLY_SPECIFIED`: any issue, any REQUIRED requirement that is not
   adequate, or no aligned `DIRECTLY_TESTS`.
5. `WELL_SPECIFIED`: none of the above.

**Off-target and poorly documented experiments (Q13, Q14).** An experiment that
is well documented but links only `DOES_NOT_TEST` gets
`EXPERIMENT_DOES_NOT_TEST_TARGET`, is capped at PARTIALLY, and covers nothing.
The requirement becomes `NOT_COVERED` and the project `MAJOR_GAPS`. An
experiment that targets the claim but is poorly documented is `MAJOR_GAPS`, and
its coverage is only `PARTIALLY_COVERED`.

**Track posture** is the worst of its experiments and its owned coverage
(COVERED→WELL, PARTIAL→PARTIALLY, NOT→MAJOR, UNRESOLVED→UNRESOLVED). An empty
track is `INSUFFICIENT_EVIDENCE`. **Project posture** is the worst of the tracks
and of any unowned coverage. An unowned experiment caps it at UNRESOLVED, and an
untested bound claim caps it at PARTIALLY.

**Q20, the conditions for WELL_SPECIFIED.** The run is COMPLETED with tracks.
Every experiment is track-owned and WELL. Every bound Phase 2J requirement is
`COVERED_BY_EXPERIMENT`. Every bound claim has at least one testing link. No
issue exists anywhere. Every posture is derived, so a forged label is rejected.

**Failure reasons.** These are three closed enums, each with a proven emission
path:

- `ExperimentIssueCode` (28 codes, each with a fixed severity), emitted only by
  `derive_experiment_issues`. A missing REQUIRED requirement maps through
  `MISSING_REQUIREMENT_ISSUE`; any unmapped kind maps to
  `REQUIRED_PROTOCOL_ELEMENT_MISSING`. The others are
  `CONFLICTING_PROTOCOL_DESCRIPTION`, `PROTOCOL_RISK_IDENTIFIED`,
  `METRIC_TARGET_MISMATCH`, `SUCCESS_CRITERION_POST_HOC`,
  `BASELINE_NOT_RELEVANT`, `BASELINE_COMPARABILITY_GAP` and
  `EXPERIMENT_DOES_NOT_TEST_TARGET`.
- `ContinuityReason` (6 reasons), emitted only by `derive_phase2j_coverage`.
- `ExperimentRunIssueCode` (17 codes), each mapped to its emitting stage(s) in
  `RUN_ISSUE_EMITTERS`. `ExperimentRunIssue` rejects a code from a stage that
  cannot emit it.

Dropped as dead: `EXECUTION_NOT_VERIFIED` is a constant (a literal False on every
record), not an event. `STALE_ARTIFACT_HASH` is `EXACT_EXCERPT_MISMATCH` at
binding or `UPSTREAM_MUTATED` at finalize.

## 7. Graph

| stage | kind | model calls |
|---|---|---|
| `EXPERIMENT_BIND_INPUTS` | deterministic: bind submission, claims, Phase 2J targets, Phase 3A; fingerprint | 0 |
| `EXPERIMENT_SEGMENT` | model: experiment spans and quarantine spans; code slices, verifies, keys and de-duplicates | 1 |
| `EXPERIMENT_EXTRACT_PROTOCOL` | model: type, track proposal, per-requirement excerpts, execution status, timing | 1 per experiment |
| `EXPERIMENT_RESOLVE_APPLICABILITY` | deterministic catalog; model only for unresolved triggers | ≤1 per experiment |
| `EXPERIMENT_LINK_TARGETS` | model: links, measurement alignment, baseline relevance and comparability, conditions | 1 per experiment |
| `EXPERIMENT_SYNTHESIZE` | deterministic: issues, postures, Phase 2J coverage, track/project postures | 0 |
| `EXPERIMENT_FINALIZE` | deterministic: upstream re-fingerprint, terminal status | 0 |

The bound is `1 + 3 × max_experiments ≤ max_model_calls` (defaults 12 → 37 ≤ 40),
and `ExperimentReviewBounds` enforces it. Each stage exists because its output is
a distinct verified record type. Collapsing segmentation into extraction would
let a model choose identities while it extracts. The search budget is zero:
`external_search_calls` and `network_attempts` are `Literal[0]`.

**Deterministic responsibilities:** source, run and excerpt binding; ID and
reference validation; the catalog and applicability after judgment; Phase 2J
continuity; target-set completeness; the result-leakage barrier; duplicates;
canonical ordering; issues; postures; unresolved propagation; fingerprints.

**Model-assisted (bounded, typed, ID-only, post-validated, fail-closed):**
segmentation, type, conditional applicability, linkage, metric-target alignment,
baseline relevance, comparability, conditions, track ownership when HYBRID,
success-criterion timing, and quarantine tagging.

## 8. Replay, checkpoint and fingerprint

IDs come from uuid5 over run-scoped content. `canonicalize()` defines the single
ordering, and the run validator rejects any non-canonical list, so the order of
a model's list never reaches state. `adequacy_fingerprint` gives stable,
offset-free and result-free equality. `upstream_fingerprint` covers bind and
finalize. `ExperimentReviewRun` is reachable from `EvaluationGraphState` and is
registered automatically. Catalog-only types are listed in
`NON_CHECKPOINTED_TYPES` with reasons. JSON round-trips are equal.

## 9. Architecture tests

`tests/test_phase3b_architecture.py` has 55 tests. They cover the reference
world; the taxonomy and catalog; statistics, baseline-trigger and UNKNOWN-type
applicability; never-lower and never-drop; identity, offset independence,
duplicates and repeated excerpts; stale hashes and cross-run records; same-metric
wrong-target, cross-target substitution, multi-target and multi-experiment
cases; off-target and poorly documented experiments; Phase 2J
`from_hypothesis`, different metric, absent or different baseline, conditions,
no pooling, reason reachability and forged coverage; baseline layers; bare N;
post-hoc criteria; one-shot demos; ML leakage; quarantine overlap; the
result-change mutation; derivation signatures; the execution literals;
issue-code and run-issue reachability; precedence; HYBRID tracks without
averaging; forged postures; WELL conditions; canonical ordering; replay and
round-trip; `ResearchRun` binding and type registration; forbidden fields,
inputs and imports; call bounds; and EN/AR/mixed injection.

**Mutation checks run** (each disables one mechanism and shows that the input a
targeted test rejects is then accepted):

1. exact anchoring (`protocol_key`);
2. Phase 2J continuity (`derive_phase2j_coverage`);
3. the result-leakage barrier (`_overlaps`);
4. the metric-target guard (`directly_tests_supported`);
5. posture precedence (`worst`);
6. the baseline requirement for improvement claims (`MISSING_REQUIREMENT_ISSUE`).

**Reserved production test families:** DTO, source binding, identity,
duplicates, applicability, type, HYBRID, protocol extraction, baseline, sample,
repetition, measurement, statistics, AI/ML leakage, software benchmark,
engineering, scientific control, linkage, Phase 2J continuity, result leakage,
execution, injection, provider failures, ordering, replay/checkpoint, graph
integration, language policy, workflow hardening.

## 10. Gold plan (not built here)

- ≥450 cases: ≥150 en, ≥150 ar, ≥150 mixed; ≥220 language-normalized semantic
  families; zero exact duplicates; expectations authored from input text,
  independent of production code (`scripts/generate_phase3b_gold.py`, later).
- **Deterministic quality families (= 1.0):** source anchoring, run binding,
  identity, Phase 2J continuity, result leakage, deterministic posture, canonical
  ordering, replay, checkpoint, zero search.
- **Model-judgment families (reported honestly, not forced):** segmentation,
  type, conditional applicability, linkage, metric-target alignment, baseline
  relevance, comparability, confounder/bias, reproducibility sufficiency, HYBRID
  ownership.
- **≥150 release gates:** each has a real non-zero denominator, no floor and zero
  violations.
- **≥300 negative-control attempts over ≥70 mechanisms**, including non-vacuity
  checks for anchoring, continuity, the leakage barrier, the metric-target guard,
  the baseline-required guard and posture precedence.
- The scorer re-derives every gate from the serialized run, never through the
  Phase 3B validators.

## 11. Known limitations

- Model judgments (segmentation, type, applicability triggers, linkage,
  alignment, relevance, comparability, ownership, quarantine tagging, criterion
  timing) are bounded and verified by ID, but their semantics are not proven.
  Quarantine tagging depends on the model. The structural guarantee is that
  nothing quarantined is consumed. Correct tagging is not guaranteed.
- Execution authenticity is never verified, and no execution evidence is
  accepted.
- Results are not evaluated. Protocol coverage is not experimental success.
- Phase 3B reaches no legal, regulatory, novelty, scoring or readiness
  conclusion.
- A hypothesis without a Phase 2J validation requirement is reachable only
  through its claim.
- `TIMING_NOT_DOCUMENTED` does not block WELL. Only a criterion the student
  describes as post hoc does.

## 12. Production implementation

**Modules** (`src/research/experiments/`, one responsibility each):

| module | responsibility |
|---|---|
| `binding.py` | bind run, submission (id + hash), claims, Phase 2J targets, Phase 3A context; fingerprints |
| `calls.py` | the single bounded model-call path and its failure-code mapping |
| `verify.py` | `ExperimentLedger`: exact anchoring, quarantine overlap refusal, rejection digests, prompt-leak and forbidden-prose checks, the masked submission |
| `segment.py` | segmentation, the result quarantine, protocol identity and de-duplication, the experiment bound |
| `protocol.py` | protocol extraction, catalog assembly, conditional applicability, the deterministic Phase 2J triggers |
| `linkage.py` | target links, measurement bindings, baselines, comparability, conditions, HYBRID ownership |
| `synthesis.py` | issues and postures (via the schema derivations), Phase 2J coverage, track and project postures |
| `pipeline.py` | the seven stages, idempotent and replay-safe |

`src/graph/experiment_nodes.py` and `src/graph/phase3b_graph.py`
(`build_phase3b_experiment_graph()`) wrap the stages as the seven `NodeId`s
`EXPERIMENT_BIND_INPUTS` ... `EXPERIMENT_FINALIZE`, whose values equal
`ExperimentStage`. The graph leaves the research run non-terminal. Every Phase 3A
node, `EXPERIMENT_REVIEW`, `METHODOLOGY`, `SCORING`, `TRUST_GATE`, `RED_TEAM`
and every discovery node are in its `FORBIDDEN_NODES`. Bounds come from
`ResearchSettings.experiment`. The provider comes from
`config["configurable"]["structured_model_provider"]`.

**Model tasks.** There are four structured tasks: `EXPERIMENT_SEGMENTATION`,
`EXPERIMENT_PROTOCOL_EXTRACTION`, `EXPERIMENT_APPLICABILITY` and
`EXPERIMENT_TARGET_LINKAGE`. Each has a V1 prompt sharing
`EXPERIMENT_INPUT_BOUNDARY`. Only segmentation and extraction point at new
submission text. Applicability and linkage cite labels (E, T, V, K) of records
code has already verified, so they cannot introduce an excerpt or an id. An
excerpt label outside the experiment's own excerpts is refused, so a metric
cannot be borrowed from another experiment.

**Call bound.** `model_calls_performed` counts provider requests with retries
included. A call is made only while budget remains, and its retry limit is cut
to the remaining budget. At most there is 1 segmentation call and, per
experiment, 1 extraction, at most 1 applicability and 1 linkage call. No call is
made for an UNKNOWN type's applicability.

**Result quarantine.** Segmentation tags result spans. They are stored as
`QuarantinedSpan` (offsets + hash). A defining or protocol span overlapping one
is refused (`RESULT_LEAKAGE_ATTEMPT` in the rejection digest). Extraction is
shown the submission with every quarantined span replaced by `[RESULT WITHHELD]`,
and applicability and linkage see only verified protocol excerpts. A reported
value therefore cannot steer a later model judgment, and no synthesis function
takes a result argument. At segmentation, where the run-issue table does not list
`RESULT_LEAKAGE_ATTEMPT`, the refusal is reported as `PARTIAL_MODEL_OUTPUT` with
the precise code kept in the digest. Finalize re-checks that every excerpt and
quarantined span still slices to its stored text or hash.

**Applicability.** The catalog decides first (`resolve_applicability`). Only a
`CONDITION_UNRESOLVED` cell is shown to the model, with its own triggers minus
the two Phase 2J triggers, which are deterministic. A resolution needs at least
one cited excerpt label. A missing judgment leaves the cell CONDITIONAL. The
Phase 2J baseline and material-condition triggers are applied in the link stage,
only for an experiment that test-links a requirement carrying them. Until then a
row the model judged free of its own triggers stays CONDITIONAL with the
judgment's excerpts recorded. It becomes NOT_APPLICABLE on that judgment only if
no Phase 2J trigger reaches it.

**Phase 2J continuity.** Every bound requirement is judged as a V target with
its metric, baseline and condition dimensions shown as context. Coverage is
`derive_phase2j_coverage` over records of one experiment at a time. An omitted
target is an `UNRESOLVED` link, never `DOES_NOT_TEST`.

**Linkage guards.** `ALIGNED_SAME_TARGET` needs a method and a metric excerpt.
`DIRECTLY_TESTS` without an aligned measurement of the same experiment and
target is reduced to `PARTIALLY_TESTS`. A testing relation with no cited
protocol is `UNRESOLVED`. Baseline relevance needs a permitted ground. A
comparability `NOT_APPLICABLE` from the model is read as `UNRESOLVED`.
`SAME_EVALUATION_METRIC` is set deterministically only from the experiment's own
aligned metric binding for that target.

**HYBRID ownership.** The tested requirements' single facet decides first
(`PHASE_2J_LIMITATION_FACET`), then the extraction's bounded proposal with
excerpts, otherwise `UNRESOLVED`.

**Provider failures.** Each failure has its own code and fails closed:
`MODEL_PROVIDER_MISSING` (segmentation), `MODEL_CALL_BOUND_REACHED`,
`MODEL_REFUSED`, `MODEL_RESPONSE_INVALID` (parse, empty or provider error) and
`PARTIAL_MODEL_OUTPUT` (incomplete output or unjudged items). A failed extraction
leaves the experiment UNKNOWN with every applicable requirement
`INSUFFICIENT_SOURCE_COVERAGE`. A failed linkage leaves every target
`UNRESOLVED`. A failed applicability call leaves the cells CONDITIONAL.

**Finalize.** It compares fingerprints and checks source integrity. A mismatch
gives `INVALIDATED_UPSTREAM_MUTATED` with no experiment, coverage or posture
kept. A run whose experiment set hit `max_experiments` ends `INSUFFICIENT_INPUT`
with no project posture, because a truncated set is never read as complete.
Otherwise the run is `COMPLETED` with the derived project posture.

**Production tests.** `tests/test_phase3b_pipeline.py`,
`tests/test_phase3b_trust.py` and `tests/test_phase3b_safety.py` run focused
fixtures (`tests/phase3b_support.py`, a scripted untrusted model) over a real
Phase 2E-3A upstream. They are not Gold.

**Pre-Gold security hardening.** A post-commit review found three production defects, all
fixed without changing the architecture, the schema or ADR-023.

- *Untrusted prompt boundary.* Every student-controlled string (the submission, claims,
  Phase 2J anchor text, the experiment's defining excerpts and protocol excerpts) is rendered
  only inside the untrusted blocks, before `EXPERIMENT_END_MARKER`. The trusted tail carries
  only code-built labels and closed enum values. Before insertion `escape_untrusted` puts a
  zero-width space between every two adjacent `=`, so no `===` (and so no boundary marker)
  can occur in escaped student text, in any language. The escape is structural, not a keyword
  list, and reversible: the model's quote is unescaped before matching, and the stored excerpt
  is always the original slice of the submission. Text that already contains the escape
  sequence fails closed (the quote does not match).
- *Source-window parity.* `SourceWindow` (in `verify.py`) is the one deterministic
  model-visible slice, `[0, min(len, max_submission_chars))` in original coordinates. The order
  is window first, then masking inside the window, then the prompt. Segmentation, extraction,
  the ledger's anchoring and finalize all use the same window, so an excerpt that starts,
  ends or lies outside it cannot be located, and a repeat outside it cannot substitute for an
  occurrence inside it. Masking changes only the model's copy and never shifts an offset.
  Finalize also rejects any stored excerpt or quarantined span outside the window.
- *Fail-closed result quarantine.* For every declared result span, every exact occurrence in the
  window is quarantined (offsets and a hash only), whatever its length. A result cut by the
  window edge has its visible prefix withheld. A declared span that cannot be located (or is
  empty, or matches more than `max_excerpts` times) is never dropped silently: the run records
  `PARTIAL_MODEL_OUTPUT` at `EXPERIMENT_SEGMENT` with a fixed incomplete-quarantine message, plus
  the precise rejection digest. Stages after segmentation then make no model call, and finalize
  ends the run `INSUFFICIENT_INPUT` with no experiment, link, coverage or posture, so it cannot
  reach `WELL_SPECIFIED`. The flag is derived from persisted run issues, so it survives a
  checkpoint and a replay. Where a result and a protocol excerpt overlap, the result wins.

`quarantine complete` means only that every result span the segmentation output declared was
safely processed. It is not proof that segmentation found every real result.

**Implementation limitations** (in addition to section 11):

- Quarantine completeness depends on the segmentation model's recall. A result sentence it never
  declares could be cited as protocol text. The structural guarantee covers only declared spans;
  recall is a model limitation to be measured in Gold, not a proven property.
- The forbidden-prose check on advisory rationales is an English lexicon and
  defense in depth only. The language-independent defense is that no rationale
  is persisted and every canonical field is typed.
- Phase 2J condition text is not stored upstream. The linkage model sees only
  each condition's dimension.
