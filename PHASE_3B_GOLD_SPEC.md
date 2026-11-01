# Phase 3B — Gold / Offline Evaluation Specification

## Status

Gold / offline evaluation milestone only.

Repository:
- `mawhiba-evaluator`

Branch:
- `feat/phase3b-experiment-review`

Main baseline:
- `9d9e64eb16acedcb85007112f874762336a20d74`

Approved Phase 3B architecture commit:
- `7641ef5` — `feat(experiments): establish Phase 3B architecture contracts`

Approved Phase 3B implementation commit:
- `de1f734` — `feat(experiments): implement Phase 3B experiment review`

Approved Phase 3B pre-Gold hardening commit:
- `b6beaad` — `fix(experiments): harden Phase 3B pre-Gold trust boundaries`

Phase 3B architecture authority:
- `PHASE_3B_EXPERIMENT_REVIEW_PLANNING.md`
- `docs/adr/ADR-023-experiment-review-is-a-protocol-level-posture.md`
- `docs/phase3b_experiment_review.md`
- `src/schemas/experiment_review.py`

Phase 3B production trust statements:

```text
Structured != True
Documented != Adequate
Adequate Protocol != Successful Result
Execution Described != Execution Verified
Metric Present != Metric Aligned
Baseline Present != Baseline Fair
Sample Size Present != Sample Adequate
Repetition != Independent Replication
Experiment Exists != Claim Tested
Claim Tested != Claim Supported
Result Reported != Result Verified
Experiment Review != Result Review
```

Do not merge.
Do not run cross-phase regressions.
Do not run the final repository suite.
Do not start Result Review.

---

# 1. Goal

Build an independent Gold / offline evaluation harness that measures whether Phase 3B Experiment Review preserves its production contracts under:

- English;
- Arabic;
- mixed-language submissions;
- scientific experiments;
- engineering validation;
- AI/ML evaluation;
- software/system benchmarking;
- hybrid projects;
- malformed inputs;
- prompt injection;
- result leakage attempts;
- provider failures;
- replay/checkpoint scenarios;
- adversarial target/linkage conditions.

The Gold milestone must evaluate:

```text
source binding
experiment identity
experiment segmentation
protocol extraction
applicability
claim/experiment linkage
Phase 2J continuity
baseline/comparator boundaries
measurement/metric alignment
sample/repetition boundaries
statistics applicability
result quarantine
execution boundary
track ownership
deterministic posture
provider-failure semantics
replay/checkpoint determinism
```

The Gold milestone must **not** evaluate result correctness.

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS PHASE

- Stay on `feat/phase3b-experiment-review`.
- Start from `b6beaad`.
- Keep Gold authoring independent from production logic.
- Do not hard-code production answers into Gold expectations.
- Do not import production catalogs, posture functions, continuity functions, or validators to derive expected semantics.
- Production schemas may be imported only where necessary to execute production code, not to author expected Gold answers.
- Do not weaken production code merely to make Gold green.
- Do not weaken Gold expectations merely to make production green.
- Classify every miss before editing.
- Make the smallest justified fix at the correct layer.
- Do not repeatedly run the full Gold corpus during authoring.
- Use smoke subsets while developing the harness.
- Run one complete Gold evaluation only after the corpus/harness stabilizes.
- If production changes after a full Gold run, rerun directly affected production tests first and then rerun Gold.
- Do not run Phase 2J → Phase 1 regressions.
- Do not run the full repository pytest suite.
- Do not merge.
- Do not push.
- Do not start Result Review.
- Do not touch `homepage-preview/`.
- Do not automatically commit at the end.
- No `Co-Authored-By` or AI attribution in any later approved commit.

Required workflow:

```text
Gold schema
→ independent catalog/world model
→ case generator
→ smoke cases
→ quality metrics
→ release gates
→ negative controls
→ non-vacuity mutations
→ Gold tests
→ full Gold run
→ classify every miss
→ fix correct layer only
→ rerun affected tests
→ final Gold run
→ Gold checkpoint
→ STOP
```

---

# 3. Dataset Minimums

Final Gold dataset must contain at least:

```text
>= 450 total cases
>= 150 English
>= 150 Arabic
>= 150 mixed
>= 220 language-normalized semantic families
```

Use a language-neutral field such as:

```text
semantic_family_id
```

Translations of the same scenario share the same semantic family.

Do not count:

```text
same semantic case in en
same semantic case in ar
same semantic case in mixed
```

as three semantic families.

Report both:

- total case count;
- raw category count;
- normalized semantic-family count.

Exact duplicate cases must be zero.

---

# 4. Gold Authoring Independence

Gold expected semantics must be authored independently.

The Gold generator must not import Phase 3B production modules to derive:

- requirement applicability;
- expected posture;
- expected linkage;
- expected continuity coverage;
- expected baseline state;
- expected metric alignment;
- expected quarantine behavior;
- expected issue codes.

A test must scan Gold authoring code and reject imports from:

```text
src.research.experiments
```

except explicitly approved execution adapters that do not expose semantic answers.

Prefer a Gold-owned catalog/world model.

Gold-owned policy may duplicate approved contract semantics manually.

That duplication is intentional.

It prevents production logic from grading itself.

---

# 5. Dataset Schema

Create:

```text
evals/experiment_review/v1/cases.jsonl
evals/experiment_review/v1/schema.md
```

Each case should include enough independent expected data to evaluate production behavior.

Recommended fields:

```text
case_id
language
semantic_family_id
category
project_type
submission
claims
phase2j_world
phase3a_context
model_script
expected
negative_control_tags
notes
```

Do not persist hidden chain-of-thought.

Do not place secret provider prompts in Gold expected data.

---

# 6. Required Semantic Coverage

The corpus must cover at minimum the following families.

## A. Experiment segmentation / identity

- one experiment;
- no experiment;
- multiple experiments;
- same protocol repeated;
- same protocol described in two places;
- changed protocol revision;
- same metric but different experiment;
- same claim with multiple experiments;
- one experiment with multiple targets;
- unrelated text inserted before experiment;
- offset shifts with stable identity;
- repeated defining excerpts;
- experiment text near source-window boundary.

## B. Scientific experiments

- controlled experiment;
- observational study;
- missing control when required;
- control not applicable;
- randomization required;
- randomization not applicable;
- blinding required;
- blinding not applicable;
- independent/dependent variables;
- confounding;
- measurement bias;
- sample adequacy;
- inferential statistics trigger;
- descriptive-only study;
- reproducibility.

## C. Engineering experiments

- bench test;
- field test;
- stress test;
- edge-case test;
- requirement-to-test traceability;
- prototype turns on once;
- missing environmental conditions;
- missing calibration;
- relevant baseline;
- irrelevant baseline;
- tolerances;
- failure-mode test;
- repetitions.

## D. AI / ML experiments

- train/validation/test split;
- independent test set;
- train/test leakage;
- duplicate leakage;
- tuning on test;
- repeated seeds;
- cross-validation;
- external validation;
- class imbalance;
- metric appropriateness;
- baseline model;
- comparator tuning context;
- benchmark contamination;
- calibration;
- subgroup/error analysis;
- reported high accuracy but weak protocol;
- reported poor accuracy but adequate protocol.

## E. Software/system experiments

- latency benchmark;
- throughput benchmark;
- load test;
- security test;
- usability test;
- workload mismatch;
- different hardware comparator;
- missing warm-up;
- one run only;
- resource measurement;
- screenshot only;
- successful launch only;
- environment/version mismatch.

## F. Hybrid

- AI + engineering;
- engineering + software;
- scientific + AI;
- three-track project;
- ownership from Phase 2J facet;
- bounded model ownership;
- unresolved ownership;
- no double counting;
- strong track + weak track;
- track averaging forbidden.

---

# 7. Phase 2J Continuity Coverage

This is release-critical.

Gold must include cases for:

- exact validation requirement match;
- hypothesis without validation requirement;
- metric match same target;
- metric match wrong target;
- baseline match same target;
- baseline from another target;
- material condition covered;
- material condition omitted;
- requirement fully covered by one experiment;
- requirement partially covered;
- requirement not covered;
- requirement unresolved;
- mosaic attempt:
  - metric in experiment A;
  - baseline in experiment B;
  - condition in experiment C;
  - expected NOT COVERED / PARTIALLY_COVERED, never COVERED.

Gold must enforce:

```text
one Phase 2J requirement
must be satisfied by one experiment
for every required dimension
```

unless the approved architecture explicitly defines otherwise.

Do not create synthetic cross-experiment coverage.

---

# 8. Claim / Experiment Linkage

Measure model judgment for:

- DIRECTLY_TESTS;
- PARTIALLY_TESTS;
- SUPPORTING_VALIDATION;
- DOES_NOT_TEST;
- UNRESOLVED.

Required adversarial cases:

- same keyword, wrong claim;
- same metric, wrong claim;
- sophisticated experiment, unrelated target;
- correct target but weak protocol;
- supporting experiment that is not direct;
- one experiment linked to several claims;
- one omitted target;
- foreign target ID;
- cross-run target ID.

DIRECTLY_TESTS must require same-experiment aligned measurement.

---

# 9. Baseline / Comparator

Gold must test all separate layers:

```text
documented
relevant
comparability properties
execution described
execution verified
result
```

Required cases:

- baseline absent but not required;
- baseline absent for improvement claim;
- baseline name only;
- relevant baseline;
- irrelevant baseline;
- same metric;
- different metric;
- same hardware;
- different hardware;
- same dataset;
- different dataset;
- same preprocessing;
- different preprocessing;
- tuning asymmetry;
- execution described;
- execution verified must remain false;
- global "fair" conclusion must never be produced.

Do not treat:

```text
baseline present
```

as:

```text
fair comparison
```

---

# 10. Measurement / Metric

Gold must include:

- method + metric + target aligned;
- metric only;
- method only;
- metric with wrong target;
- method/metric from different experiments;
- unit mismatch;
- measurement resolution missing;
- calibration missing where material;
- success criterion present;
- success criterion missing;
- criterion set after observing result;
- criterion timing ambiguous.

Required semantic metric:

```text
metric_target_alignment
```

Report honestly.

Do not force it to 1.0.

---

# 11. Sample / Repetition

Required cases:

- `N=500` only;
- small but justified sample;
- large but unjustified sample;
- sample definition missing;
- rationale missing;
- repeated measurement;
- independent replication;
- repetition count only;
- repetitions not applicable;
- pseudoreplication;
- random seeds in AI/ML;
- repeated seeds absent where material.

Gold must enforce:

```text
sample size present != sample adequate
repetitions present != independent replication
```

---

# 12. Statistics

All statistics expectations are conditional.

Include cases where:

- no statistical analysis is needed;
- descriptive statistics are enough;
- uncertainty is expected;
- confidence interval is expected;
- inferential test is expected;
- p-value is irrelevant;
- p-value is present but protocol is poor;
- multiple comparisons matter;
- outlier handling matters;
- assumptions matter;
- statistical power/sample rationale matters;
- deterministic benchmark uses repeated distributions but no significance test.

A missing p-value must not automatically fail a case.

A present p-value must not automatically improve a posture.

---

# 13. Result Quarantine — Critical Gold Surface

This is one of the most important Phase 3B Gold areas.

Required deterministic families:

## Declared result spans

- one result sentence;
- repeated result sentence;
- long result sentence;
- result table;
- result near source-window boundary;
- result containing prompt injection;
- Arabic result;
- mixed result;
- positive result;
- negative result;
- neutral result.

## Quarantine correctness

- all exact occurrences quarantined;
- no first-match-only quarantine;
- result/protocol overlap rejected;
- result span offsets/hashes stable;
- no raw result prose in canonical state;
- result values not consumed by synthesis.

## Incomplete quarantine

- model-declared result cannot be located;
- empty declared result;
- excessive occurrence count;
- malformed declared result;
- provider partial result output.

Expected:

```text
fail closed
no WELL_SPECIFIED
no later model call that can consume the result as protocol evidence
```

## Result mutation invariance

Gold must include paired cases where only result values differ:

```text
97% vs 41%
improved vs worsened
positive vs negative
table values changed
```

Expected Phase 3B protocol adequacy must remain invariant.

Add a deterministic quality metric for result-mutation invariance.

---

# 14. Result Segmentation Recall

The pre-Gold hardening explicitly leaves one known limitation:

```text
quarantine complete
does not prove every real result was detected
```

Gold must measure this.

Add model-judgment metrics such as:

```text
result_span_recall
result_span_precision
```

or an equivalent well-defined pair.

Do not force them to 1.0.

Seed:

- easy results;
- paraphrased results;
- tables;
- Arabic results;
- mixed results;
- short statements;
- repeated results;
- adversarial result-like protocol text;
- protocol text containing numbers that are not results.

This metric is important because the safety system only fails closed for declared spans; model omission remains a semantic-recall limitation.

---

# 15. Prompt Boundary / Injection

Gold must test the hardened prompt isolation.

Include:

- forged end marker;
- repeated end marker;
- student text resembling SYSTEM/DEVELOPER instructions;
- English injection;
- Arabic injection;
- mixed injection;
- result-text injection;
- protocol-text injection;
- defining-excerpt injection;
- zero-width/marker edge cases.

Deterministic gates must verify:

```text
student prose never appears in trusted tail
exactly one real end marker
canonical source uses original unescaped text
```

No English-only safety assumption.

---

# 16. Source Window / Anchor Parity

Gold must test:

- excerpt fully inside visible window;
- starts before window;
- ends after window;
- fully outside window;
- repeated text inside and outside window;
- result masking near boundary;
- replay;
- checkpoint resume;
- model list reordering.

Required deterministic invariant:

```text
accepted excerpt ⊆ model-visible original source window
```

Add a release gate with real denominator.

---

# 17. Execution Boundary

Cases:

- "we ran the experiment";
- "we repeated it 20 times";
- "the test passed";
- "we reproduced the experiment";
- logs mentioned in prose;
- notebook mentioned in prose;
- raw data mentioned in prose;
- screenshot mentioned in prose.

Expected:

```text
execution described may be recorded
execution_verified = false
independently_reproduced = false
leakage_prevented_in_practice = false
```

No case may turn prose into verified execution.

---

# 18. Provider Failure Semantics

Gold must include independent cases for:

- provider missing;
- refusal;
- invalid structured output;
- partial output;
- call bound reached;
- segmentation failure;
- extraction failure;
- applicability failure;
- linkage failure.

Expected failure semantics must be stage-specific.

No provider failure may produce WELL_SPECIFIED.

No provider raw text may become canonical state.

---

# 19. Model Call Bound

Gold must verify:

```text
1 + 3 per experiment
hard budget = 40
```

or the exact currently approved runtime values.

Cases:

- one experiment;
- max experiments;
- retries;
- refusal;
- partial response;
- budget exhausted.

Count provider requests, including retries.

No hidden retry may exceed the bound.

---

# 20. Canonical Determinism

Required cases:

- reordered model lists;
- reordered excerpt lists;
- reordered target lists;
- reordered baseline/comparability fields;
- repeated exact evidence;
- replay;
- resume after checkpoint;
- same semantic model output in different order.

Expected canonical output must be identical.

Add deterministic quality metrics for:

- canonical ordering;
- replay equivalence;
- checkpoint/resume equivalence;
- stable experiment IDs.

---

# 21. Required Quality Metrics

Create at least:

```text
>= 45 metric families total
```

Separate:

## Deterministic quality metrics

All deterministic metrics must be exactly:

```text
1.0
```

Suggested deterministic families:

- source binding accuracy;
- run binding;
- exact excerpt validity;
- visible-window containment;
- result-quarantine occurrence completeness;
- incomplete-quarantine fail-closed;
- result mutation invariance;
- execution flags invariant;
- Phase 2J ID continuity;
- no mosaic coverage;
- stable experiment identity;
- canonical ordering;
- deterministic posture;
- provider-failure fail-closed;
- call-budget enforcement;
- external search zero;
- network attempts zero;
- prompt trusted-tail isolation;
- marker neutralization;
- replay equivalence;
- checkpoint equivalence.

## Model-judgment metrics

Measure honestly, do not require 1.0.

At minimum report:

- experiment segmentation precision;
- experiment segmentation recall;
- experiment type accuracy;
- conditional applicability accuracy;
- claim-experiment semantic linkage;
- metric-target alignment;
- baseline relevance;
- comparator comparability judgment;
- confounder/bias recognition;
- reproducibility sufficiency;
- Hybrid ownership;
- result-span precision;
- result-span recall;
- criterion timing judgment.

If a metric has no denominator, the Gold corpus is incomplete.

Do not hide zero denominators.

---

# 22. Release Gates

Create at least:

```text
>= 150 release gates
```

Every required release gate must have:

```text
real denominator > 0
zero violations
```

No denominator floors.

Do not write:

```python
denominator = max(actual, 1)
```

or any equivalent artificial floor.

Add a test scanning eval code for denominator floors.

Required gate families include:

- cross-run references;
- unknown IDs;
- exact anchoring;
- first-match guesses;
- visible-window mismatch;
- prompt trusted-tail leakage;
- forged marker escape;
- result text persisted canonically;
- unquarantined declared result;
- incomplete quarantine accepted;
- result value affects adequacy;
- execution verified from prose;
- independent reproduction inferred;
- leakage-prevented inferred;
- metric wrong target;
- cross-experiment mosaic;
- baseline name implies relevance;
- global fairness claim;
- bare sample N adequate;
- repetition implies independent replication;
- inappropriate statistics requirement;
- provider failure yields strong posture;
- unresolved Hybrid ownership counted;
- track averaging;
- external search/network activity;
- result/experiment legacy ProjectState input use.

---

# 23. Thin Gates

Report all gates with fewer than:

```text
6 real opportunities
```

Do not fail Gold solely because a legitimate rare gate is thin.

But:

- list it explicitly;
- provide denominator;
- confirm it is a real opportunity;
- do not pad with duplicate cases merely to inflate denominator.

---

# 24. Negative Controls

Create at least:

```text
>= 300 negative-control attempts
>= 70 distinct mechanisms
```

Every control must be caught for the intended reason.

Do not count:

```text
same mutation in 20 cases
```

as 20 mechanisms.

Mechanisms should include:

- remove exact anchoring;
- allow first-match anchoring;
- allow out-of-window excerpt;
- disable marker escaping;
- move student excerpts into trusted prompt tail;
- quarantine first result occurrence only;
- silently drop unlocatable result;
- allow incomplete quarantine strong posture;
- allow result value into synthesis;
- set execution_verified from prose;
- allow metric wrong target;
- allow mosaic continuity;
- accept baseline name as relevance;
- infer global fair comparator;
- accept bare sample number;
- treat repetitions as independent;
- weaken UNKNOWN type cap;
- average Hybrid tracks;
- accept foreign target;
- accept cross-run target;
- ignore provider partial output;
- allow hidden retry over call budget;
- allow external search/network.

---

# 25. Non-Vacuity Mutation Tests

At least six permanent non-vacuity checks are required.

Disable one production mechanism and confirm the intended gate/control fails.

Required:

1. exact anchoring;
2. Phase 2J continuity;
3. result-quarantine fail-closed;
4. metric-target alignment;
5. deterministic posture precedence;
6. baseline-required guard for improvement claim.

Additionally strongly recommended:

7. prompt trusted-tail isolation;
8. visible-window containment;
9. all-occurrence result quarantine.

The test must fail for the intended reason.

---

# 26. Gold Miss Classification

Every failed Gold case or gate must be classified before editing.

Allowed classifications:

```text
GOLD_FIXTURE_DEFECT
GOLD_EXPECTATION_DEFECT
EVAL_HARNESS_DEFECT
PRODUCTION_IMPLEMENTATION_DEFECT
RELEASE_GATE_PREDICATE_DEFECT
MODEL_JUDGMENT_ERROR
ARCHITECTURE_CONTRACT_DEFECT
```

Rules:

- Do not change production for a Gold fixture defect.
- Do not weaken expected semantics for a production defect.
- Do not rewrite architecture silently.
- Model judgment misses are allowed if deterministic contracts remain safe and the metric is reported honestly.

Maintain a miss ledger.

---

# 27. Gold Case Design Principles

Avoid trivial padding.

A strong case should isolate a specific semantic or trust boundary.

Prefer case families with meaningful variations:

```text
same protocol
different result

same metric
different target

same baseline name
different comparison context

same experiment
different language

same result sentence
different occurrence structure

same protocol
different source-window position
```

Do not generate thousands of near-identical cases merely to inflate counts.

---

# 28. Language Distribution

Final corpus must be at least:

```text
English >= 150
Arabic >= 150
mixed >= 150
```

Arabic/mixed cases must exercise actual semantic/safety behavior, not only literal translation.

Include Arabic-specific cases for:

- experiment wording;
- result wording;
- prompt injection;
- baseline phrasing;
- execution statements;
- statistical claims;
- measurement descriptions.

Include mixed-language cases where technical terms remain English within Arabic prose.

---

# 29. Language Policy

Developer-facing Gold code must remain English.

Arabic is permitted only as:

- test/source data;
- Gold submission content;
- multilingual injection fixtures;
- expected source text.

Register Arabic-bearing files with the repository language-policy mechanism with explicit reasons.

Do not globally suppress the language guard.

---

# 30. Gold Package

Prefer:

```text
src/evals/experiment_review/
```

with focused modules such as:

```text
world.py
catalog.py
context.py
runner.py
quality.py
gates.py
controls.py
metrics.py
cli.py
```

Use the repository's existing Phase 2J/Phase 3A eval patterns where appropriate.

Do not copy production logic into Gold.

The Gold harness should call production through a narrow execution adapter.

---

# 31. Generator

Create a generator under:

```text
scripts/
```

Use multiple focused template/language modules if needed.

Example:

```text
scripts/generate_phase3b_gold.py
scripts/phase3b_gold_lang.py
scripts/phase3b_gold_templates.py
scripts/phase3b_gold_templates2.py
...
```

Do not create unmaintainable single-file giant template logic.

Generator output must be deterministic.

Running the generator twice must produce byte-identical dataset output.

Add a determinism test.

---

# 32. Gold Tests

Create dedicated tests, including at minimum:

- schema validation;
- minimum case counts;
- per-language minimums;
- normalized semantic-family minimum;
- exact duplicate detection;
- generator determinism;
- authoring independence;
- no production semantic imports;
- metric-family minimum;
- no unmeasured required metrics;
- deterministic metrics = 1.0;
- gate minimum;
- all gate denominators > 0;
- no denominator floors;
- zero gate violations;
- negative-control attempt minimum;
- mechanism minimum;
- every control caught for intended reason;
- non-vacuity mutations;
- verbose CLI output;
- external search/network zero.

---

# 33. Model-Judgment Metrics Must Be Honest

Do not force semantic metrics to 1.0 by:

- rewriting cases to match the model;
- deleting hard cases;
- routing all uncertain cases to deterministic UNRESOLVED merely to improve accuracy;
- using production output as expected output.

A semantic metric below 1.0 is acceptable if:

- deterministic safety boundaries hold;
- release gates remain zero violation;
- model error is measured and reported;
- no unsafe strong posture is produced.

---

# 34. Gold CLI

Provide an offline CLI such as:

```text
python -m src.evals.experiment_review.cli
```

Support a verbose mode that prints:

- case counts;
- language distribution;
- semantic-family count;
- deterministic metric families;
- model-judgment metrics;
- release gate denominators/violations;
- thin gates;
- negative controls;
- mechanisms;
- final PASS/FAIL.

Do not hide failed cases.

---

# 35. No External Search

Gold and production Phase 3B must remain:

```text
external_search_attempts = 0
network_attempts = 0
```

The Gold harness must not call web, literature, patent, product, or live provider APIs.

Use deterministic scripted/fake model providers.

---

# 36. Provider Simulation

Gold should use deterministic scripted model behavior.

Seed:

- correct response;
- wrong semantic response;
- omitted target;
- unknown target;
- refusal;
- invalid JSON/structured output;
- partial response;
- reordered list;
- repeated excerpt;
- result omission;
- wrong result span;
- cross-run ID;
- call-budget exhaustion.

Do not rely on a live model for Gold.

---

# 37. Required High-Risk Gold Scenarios

The final Gold report must explicitly call out results for:

- prompt boundary isolation;
- source-window/anchor parity;
- result-span all-occurrence quarantine;
- incomplete quarantine fail-closed;
- result mutation invariance;
- result segmentation recall/precision;
- Phase 2J continuity;
- mosaic coverage refusal;
- metric-target alignment;
- baseline relevance;
- comparator comparability;
- bare sample-N boundary;
- repetition/replication boundary;
- statistics applicability;
- execution verification boundary;
- Hybrid no-average/no-double-count;
- provider failure semantics;
- replay/checkpoint determinism;
- external search/network zero.

---

# 38. Final Gold Run Requirements

Before the final full Gold run:

- corpus stable;
- no duplicate padding;
- all Gold tests pass;
- smoke subset clean;
- no unresolved harness defect.

Then run the complete Gold evaluation once.

If misses occur:

1. classify every miss;
2. fix correct layer;
3. run affected targeted tests;
4. rerun full Gold.

Do not print approval until:

```text
PASSED=True
```

and every required release gate has:

```text
denominator > 0
violations = 0
```

---

# 39. Production Changes During Gold

Production changes are allowed only if Gold proves a real production defect.

If production changes:

- classify as `PRODUCTION_IMPLEMENTATION_DEFECT`;
- add targeted production regression test;
- run affected Phase 3B production tests;
- rerun hardening/security tests if relevant;
- rerun Gold.

Do not amend:

- `7641ef5`
- `de1f734`
- `b6beaad`

Leave production changes uncommitted until the Gold checkpoint is reviewed unless explicitly instructed otherwise.

---

# 40. Tests During Gold

Run:

- Gold-specific tests;
- language-policy guard when Gold files contain Arabic;
- workflow-hardening guard if new canonical/checkpointed DTOs are introduced;
- affected Phase 3B production tests only when production changes.

Do not run:

- Phase 2J → Phase 1 regressions;
- full repository pytest;
- Phase 3A Gold;
- release-merge gate.

Those happen after Gold approval and milestone commit.

---

# 41. Git Discipline

Remain on:

```text
feat/phase3b-experiment-review
```

Before final checkpoint verify:

- main still `9d9e64eb16acedcb85007112f874762336a20d74`;
- architecture commit `7641ef5` remains ancestor;
- implementation commit `de1f734` remains ancestor;
- hardening commit `b6beaad` remains ancestor;
- one worktree;
- no unrelated staged files;
- `homepage-preview/` untouched;
- Gold changes uncommitted unless separately instructed.

Do not merge.

Do not push.

---

# 42. Required Final Checkpoint

Print:

```text
PHASE 3B GOLD / OFFLINE EVAL CHECKPOINT
```

Include:

## Git
- branch;
- main baseline;
- architecture commit;
- implementation commit;
- hardening commit;
- production changes during Gold;
- working tree;
- worktree count;
- `homepage-preview/`.

## Dataset
- total cases;
- English;
- Arabic;
- mixed;
- raw categories;
- normalized semantic families;
- duplicates;
- generator determinism;
- authoring-independence result.

## Quality
- deterministic metric family count;
- confirmation all deterministic metrics = 1.0;
- model-judgment metric family count;
- every model-judgment metric and numerator/denominator;
- unmeasured metrics.

## Result segmentation
- precision;
- recall;
- per-language results;
- repeated-result behavior;
- table-result behavior;
- known misses.

## Release gates
- total gates;
- zero-denominator count;
- total violations;
- thin gates and denominators;
- no-floor confirmation.

## Negative controls
- attempts;
- caught;
- mechanisms;
- intended-reason verification;
- non-vacuity results.

## High-risk results
Report explicitly:
- prompt boundary;
- source-window parity;
- quarantine fail-closed;
- result mutation;
- Phase 2J continuity;
- mosaic refusal;
- metric alignment;
- baseline/comparator;
- sample/repetition;
- statistics;
- execution boundary;
- Hybrid ownership;
- provider failures;
- replay/checkpoint;
- external search/network zero.

## Bugs found
For every issue:
- classification;
- root cause;
- fix;
- production changed yes/no;
- architecture changed yes/no.

## Tests actually run
Exact:
- passed;
- skipped;
- failed;
- errors;
- exit code where available.

## Known limitations
At minimum:
- result segmentation recall is model-dependent;
- execution authenticity is not verified;
- results are not evaluated;
- semantic model judgments are bounded;
- no external search;
- no legal/scoring/readiness conclusions;
- any thin Gold gates.

Then print:

```text
PHASE 3B GOLD CHECKPOINT COMPLETE
```

Only if all required conditions pass, print exactly:

```text
PHASE 3B GOLD / OFFLINE EVAL APPROVED — READY FOR CROSS-PHASE RELEASE GATE
```

Then STOP.

Do not commit automatically.
Do not run cross-phase regressions.
Do not run the full repository suite.
Do not merge.
Do not start Result Review.
