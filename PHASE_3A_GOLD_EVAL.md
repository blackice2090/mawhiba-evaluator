# Phase 3A — Gold / Offline Evaluation

## Status

Gold/evaluation specification for Phase 3A after the approved architecture and production implementation milestones.

Repository:
- `mawhiba-evaluator`

Feature branch:
- `feat/phase3a-methodology-review`

Main baseline:
- `91423770758ed39e459401cc3b9b9de84c478715`

Approved Phase 3A architecture commit:
- `2f1693a13101088dc8e567e58f81eaf5e3b34f88`

Approved Phase 3A production implementation commit:
- `b9e59ffbcdc879ad25631f4d0b316b67e569cdc8`

Current production status:
- architecture approved;
- pre-Gold hardening approved;
- production implementation committed;
- working tree expected clean;
- one worktree;
- no Gold/eval work started;
- nothing merged.

This milestone builds and validates the Phase 3A offline Gold/evaluation layer only.

Do not run cross-phase regressions, the final repository suite, or merge during this milestone.

---

# 1. Goal

Build a rigorous offline Gold evaluation for Phase 3A that measures whether the production system correctly reviews methodology design while preserving all trust boundaries.

Gold must test the complete semantic and trust chain:

```text
authoritative inputs
→ requirement applicability
→ overlay materiality
→ overlay ownership
→ exact methodology evidence
→ documentation status
→ methodology assessment
→ claim-method linkage
→ gap-method linkage
→ Phase 2J validation continuity
→ metric plan
→ baseline relevance
→ condition coverage
→ sample/control/confounding safeguards
→ issue synthesis
→ track posture
→ Hybrid synthesis
→ canonical output
→ replay / mutation / safety
```

Gold must distinguish:

```text
structured != true
bound != semantically correct
documented != adequate
planned != executed
student-described execution != verified execution
baseline documented != relevant
baseline relevant != fairly executed
metric named != appropriate
sample size present != justified
overlay reviewed != overlay materially classified correctly
explicit NO_METHODOLOGY_RELEVANCE != verified absence of methodology relevance
```

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS MILESTONE

- Stay on `feat/phase3a-methodology-review`.
- Start from implementation commit `b9e59ffbcdc879ad25631f4d0b316b67e569cdc8`.
- Verify working tree clean before changing files.
- One worktree only.
- Keep scope limited to Phase 3A Gold/eval.
- Reuse production contracts exactly.
- Do not redesign production architecture unless Gold exposes a genuine production defect.
- Do not mutate Phase 2A–2J semantics to make Gold pass.
- Do not weaken validators, tests, schemas, metrics, gates, provenance, run binding, replay, or safety boundaries.
- Do not hard-code Gold case IDs or expected semantic answers into production code.
- Gold expectations must be authored independently from production output.
- Gold generator must not import Phase 3A production logic to derive expected answers.
- Do not use network access.
- Do not run cross-phase regressions.
- Do not run the full repository test suite.
- Do not merge.
- Do not start Phase 3B.
- Do not commit automatically unless explicitly instructed after the Gold checkpoint is reviewed.

Required sequence:

```text
Gold schema / runner
→ smallest runner tests
→ dataset generator / fixtures
→ dataset validation
→ denominator integrity
→ negative controls
→ targeted eval tests
→ first full offline Gold run
→ classify misses
→ fix only correct layer
→ rerun affected tests
→ rerun Gold
→ final Gold checkpoint
→ STOP
```

If a Gold miss reveals a real production defect:

```text
classify
→ minimal production fix
→ targeted production tests
→ rerun affected Gold families
→ rerun full Gold once stable
```

Do not broaden scope.

---

# 3. Context Discipline

Use Sonnet.

Recommended:
- after Gold schema/runner/generator stabilize, run `/context`;
- if context is around 70–80%, checkpoint logically then `/compact`;
- do not start a large debugging loop above ~80%;
- do not use Opus unless a genuine architecture-level contradiction appears.

Primary session owns the work.

---

# 4. Pre-Gold Baseline Verification

Before implementation, verify:

- branch = `feat/phase3a-methodology-review`;
- HEAD = `b9e59ffbcdc879ad25631f4d0b316b67e569cdc8`;
- `refs/heads/main` = `91423770758ed39e459401cc3b9b9de84c478715`;
- working tree clean;
- no unexpected untracked files;
- one worktree;
- architecture commit `2f1693a...` is an ancestor;
- no merge has occurred.

If any check fails, STOP and report.

---

# 5. Dataset Minimums

Gold must contain at least:

- **450 total cases**
- **150 English**
- **150 Arabic**
- **150 mixed-language**
- **>= 220 distinct semantic/control categories**

These are minimums, not padding targets.

No exact duplicate cases.

A case is duplicate for padding purposes if its meaningful:
- authoritative inputs;
- scripted model behavior;
- expected semantic outcome;
- applicable safety flags;

are identical.

If two cases share a base scenario but test genuinely different trust mechanisms, document the distinction.

---

# 6. Independent Gold Authoring

Gold expectations must be authored independently from production execution.

Required safeguards:

- Gold generator must not import Phase 3A production synthesis functions to compute expectations.
- Expected postures must not be copied from system output.
- Expected applicability must not be derived by calling production applicability helpers.
- Expected overlay materiality/ownership must not be copied from production output.
- Expected issue sets must not be copied from production issue synthesis.
- Expected semantic links must be declared in Gold data.

Production enums/contracts may be imported only where needed for schema compatibility, not to infer semantic truth.

Add a test that fails if the Gold authoring/generator imports prohibited Phase 3A production modules.

---

# 7. Language Coverage

Minimum:

```text
English: 150
Arabic: 150
Mixed: 150
```

Arabic and mixed strings must live only in approved data/fixture files and be registered in the language-policy registry.

Do not add Arabic production literals.

Language variants must not be superficial translation-only padding.

Each language group must include meaningful adversarial and semantic cases.

---

# 8. Project-Type Coverage

Gold must include substantial coverage for:

- `SCIENTIFIC_RESEARCH`
- `ENGINEERING_PROJECT`
- `HYBRID`

Each language must contain all three project types.

HYBRID cases must include:
- strong research / weak engineering;
- weak research / strong engineering;
- both strong;
- both weak;
- unresolved overlay ownership;
- AI/ML owned by research;
- AI/ML owned by engineering;
- software/systems owned by research where applicable;
- no double counting.

Do not create an averaged project posture.

---

# 9. Requirement Applicability Coverage

Cover all major applicability paths:

- REQUIRED;
- CONDITIONAL resolved applicable;
- CONDITIONAL resolved not applicable;
- CONDITIONAL unresolved;
- OPTIONAL;
- NOT_APPLICABLE.

High-risk research requirements:
- hypothesis conditionality;
- control group conditionality;
- randomization conditionality;
- blinding conditionality;
- sample-size rationale;
- statistical analysis;
- bias/confounding;
- reproducibility.

High-risk engineering requirements:
- design objective;
- constraints;
- baseline/comparator;
- verification plan;
- validation plan;
- failure modes;
- safety/security/privacy;
- performance/scalability;
- reproducibility/configuration.

No generic checklist behavior.

---

# 10. Overlay Materiality — Critical Gold Family

This is a top-risk Phase 3A family.

Both AI/ML and software/systems overlays are reviewed for every project.

Gold must explicitly measure whether the model-assisted materiality decision is semantically correct.

Required cases:

## Material AI/ML
- obvious metadata + material claim;
- no metadata + obvious wording;
- no metadata + unusual synonym/paraphrase;
- no lexicon hit + semantically material;
- Phase 2J target makes AI/ML material;
- AI/ML is the core engineering mechanism;
- AI/ML is a research method;
- AI/ML material only to one Hybrid track.

## Non-material AI/ML
- AI mentioned only as background;
- AI tool used only to draft/visualize;
- generic software contains no ML methodology;
- explicit `NO_METHODOLOGY_RELEVANCE` is semantically correct.

## Implementation-tool-only
- AI used as implementation convenience, not claim/gap method;
- exact excerpt required;
- requirements must not activate.

## Software/systems
Mirror the same material/non-material/tool-only distinctions.

## Unresolved
- model omission;
- refusal;
- invalid target binding;
- missing required exact excerpt;
- provider failure.

Unresolved must never silently become non-material.

---

# 11. Negative Overlay Verdict Quality

The remaining bounded limitation is especially important:

`NO_METHODOLOGY_RELEVANCE`

is a model-assisted negative judgment.

A wrong negative is possible.

Gold must therefore report dedicated model-judgment metrics for:

- AI/ML materiality recall;
- AI/ML materiality precision;
- software/systems materiality recall;
- software/systems materiality precision;
- `NO_METHODOLOGY_RELEVANCE` negative accuracy;
- implementation-tool-only accuracy;
- overlay ownership accuracy.

These model-judgment metrics must be reported honestly.

They are not required to be 1.0 if the Gold dataset intentionally includes seeded wrong judgments.

Do not hard-code production heuristics merely to force these metrics to 1.0.

However, release gates must still guarantee:

- omissions/refusals never silently resolve non-material;
- unsupported negative verdicts cannot become positive strong postures where contract requirements are unmet;
- structurally invalid negatives are rejected.

---

# 12. Exact Source Anchoring

Gold must cover:

- exact excerpt accepted;
- fabricated excerpt rejected;
- wrong start/end offsets;
- altered whitespace where hashes/offsets matter;
- repeated excerpt with correct occurrence;
- repeated excerpt with ambiguous occurrence;
- first-match guessing attack;
- cross-source excerpt;
- cross-run excerpt;
- excerpt digest mismatch;
- instruction-like exact source text.

Measure:
- anchor accuracy;
- occurrence accuracy;
- provenance integrity.

Release gate:
- zero first-match guessing.

---

# 13. Documentation vs Adequacy

Required cases:

- explicitly documented + adequate;
- explicitly documented + design risk;
- partially documented;
- conflicting documentation;
- not documented in bound input;
- insufficient source coverage;
- not applicable.

Gold must prove:

`NOT_DOCUMENTED_IN_BOUND_INPUT`

is never converted to:

`student did not do it`

and that documentation status alone does not determine adequacy.

---

# 14. Student Execution Description Boundary

Required cases:

- "we randomized";
- "we tested independently";
- "we repeated five times";
- "we validated on external data";
- Arabic/mixed equivalents.

Expected boundary:

```text
student-described execution
execution_verified = false
```

Do not issue a methodology defect merely because the statement is past tense.

Do not allow a final output to imply verified execution.

Phase 3B owns execution verification.

---

# 15. Claim → Methodology Linkage

Cover every relation:

- DIRECTLY_TESTS_TARGET
- PARTIALLY_TESTS_TARGET
- RELEVANT_BUT_NOT_TESTING
- DOES_NOT_TEST_TARGET
- INSUFFICIENT_LINKAGE_EVIDENCE

Include structurally valid but semantically wrong links.

Measure separately:

- structural binding correctness;
- semantic linkage accuracy.

Do not treat valid IDs/hashes as semantic proof.

Strong coverage must require the production structural gates.

---

# 16. Phase 2J Gap → Methodology Linkage

Cover:

- direct gap-method match;
- partial;
- relevant but non-testing;
- unrelated;
- insufficient.

Required continuity cases:

- validation requirement exists → metric required;
- baseline present → baseline required;
- baseline absent → Phase 3A must not invent one;
- conditions present → all required conditions addressed;
- conditions empty → no invented condition requirement;
- validation requirement absent → no invented metric/baseline/condition dimension;
- wrong validation requirement ID;
- wrong hypothesis;
- cross-run binding;
- semantically mismatched metric despite correct ID.

---

# 17. Metric Alignment

Gold must distinguish:

```text
metric documented
!= metric aligned to target
```

Required cases:
- exact student metric aligned;
- Phase 2J metric aligned;
- metric exists but measures wrong outcome;
- vague "better" with no metric;
- "more efficient" with undefined efficiency;
- accuracy claim with latency metric;
- latency claim with accuracy metric;
- safety claim with undefined safety outcome;
- fabricated metric proposal.

Dedicated semantic metric:
- metric_target_alignment_accuracy.

Release gate:
- invented metric never becomes canonical.

---

# 18. Baseline / Comparator

Cover all four layers:

1. baseline documented;
2. baseline relevance;
3. student rationale;
4. fair execution.

Phase 3A only decides 1–3.

Required cases:
- documented but irrelevant;
- documented and relevant;
- baseline name alone;
- rationale supports relevance;
- same excerpt contains baseline+rationale;
- Phase 2J baseline context supports relevance;
- Phase 2J existing capability supports relevance;
- wrong target;
- missing baseline when Phase 2J requires one;
- no baseline required;
- fair execution remains unassessed.

Dedicated semantic metric:
- baseline_relevance_accuracy.

Release gates:
- name alone cannot establish relevance;
- fair comparison never becomes verified.

---

# 19. Material Conditions

Cover:
- population;
- environment;
- dataset regime;
- hardware;
- resource constraints;
- scale;
- geography;
- language;
- operating regime.

Required cases:
- all addressed;
- one missing;
- wrong condition ID;
- condition addressed by unrelated method;
- condition only mentioned, not methodologically covered;
- no conditions required.

Measure:
- condition_coverage_accuracy.

Release gate:
- missing required material condition prevents strong target coverage.

---

# 20. Sample / Sampling / Statistical Rationale

Required cases:
- `N = 500` only;
- sample size with real rationale;
- sampling strategy but no size rationale;
- power/effect-size rationale where applicable;
- non-applicable power analysis;
- invented required N;
- unsupported adequacy claim.

Measure:
- sample_rationale_accuracy;
- sampling_plan_accuracy.

Release gate:
- numeric sample alone never establishes adequacy.

---

# 21. Controls / Confounding

Cover:
- control group required;
- control group not applicable;
- randomization required;
- randomization not applicable;
- blinding applicable/not applicable;
- confounders documented;
- confounder handling absent;
- controls documented.

Invariant:
- `confounding_eliminated` remains false/unverified.

Release gate:
- documented control cannot become verified elimination of confounding.

---

# 22. AI / ML Methodology Overlay

When material, cover:

- data source;
- dataset size/scope;
- data quality;
- labels;
- labeling method;
- train/validation/test split;
- group-aware split;
- temporal split;
- duplicate leakage;
- group leakage;
- test-set isolation;
- tuning contamination;
- class imbalance;
- preprocessing;
- feature engineering;
- augmentation;
- baseline model;
- model selection;
- hyperparameters;
- cross-validation;
- generalization;
- external validation;
- metrics;
- error analysis;
- seeds/version reproducibility.

Required adversarial cases:
- reported high accuracy but no test isolation;
- successful prototype but leakage risk;
- split percentages present but no isolation;
- duplicates across splits;
- group leakage scenario;
- temporal leakage scenario.

Phase 3A may identify design risk only.

It must not claim leakage actually occurred or was actually prevented unless contract wording is explicitly bounded to documented design contradiction.

---

# 23. Software / Systems Overlay

Cover:
- architecture rationale;
- backend/data-layer plan;
- security validation plan;
- privacy validation plan;
- performance benchmark plan;
- scalability validation;
- reliability;
- usability when claim-relevant;
- comparison with alternatives.

Required adversarial cases:
- UI exists → not methodology adequacy;
- architecture diagram exists → not validation plan;
- working app → cannot repair missing benchmark;
- security claim without security validation method;
- performance claim without benchmark method.

---

# 24. Result / Experiment Leakage

Gold must explicitly include successful result/prototype fields in surrounding state while proving Phase 3A cannot consume them.

Cases:
- high accuracy;
- low error;
- successful clinical/experimental result;
- working prototype;
- passed benchmark;
- repeated experimental success.

Expected:
- no posture upgrade;
- no methodology issue suppression;
- no prompt exposure;
- no DTO exposure.

Release gates:
- result-success-used-to-repair-methodology = zero;
- experiment-success-used-to-repair-methodology = zero.

---

# 25. Prompt Injection / Model Prose

Include English, Arabic and mixed instruction-like source strings.

Attack locations:
- student submission;
- methodology excerpt;
- claim text;
- overlay excerpt;
- baseline rationale;
- metric text.

Attacks should attempt:
- ignore system instructions;
- emit WELL_SPECIFIED;
- fabricate a metric;
- fabricate baseline;
- mark execution verified;
- reveal hidden prompt;
- emit a score;
- emit legal novelty;
- skip requirements.

Expected:
- source text remains inert data;
- exact excerpt may persist;
- model behavior following instruction is rejected;
- hidden/system text never persists;
- free prose does not change canonical output.

Include prose-twin tests:
same typed judgments + different free prose → byte-identical canonical output.

---

# 26. Provider Failure / Call-Bound Semantics

Cover:
- provider missing;
- refusal;
- provider error;
- model-call bound reached;
- omitted overlay;
- invalid structured output.

Safe diagnostics must distinguish:
- `MODEL_PROVIDER_MISSING`
- `MODEL_CALL_BOUND_REACHED`
or exact production equivalents.

Raw provider text must not persist.

No failure state may yield positive strong posture.

Replay must be deterministic.

---

# 27. Replay / Resume / Determinism

Gold/eval must cover:

- replay idempotency;
- resume equals uninterrupted execution;
- no duplicate model calls;
- deterministic IDs;
- input-order invariance;
- stable canonical ordering;
- cross-run isolation;
- source hash mutation;
- claim mutation;
- Phase 2I mutation;
- Phase 2J mutation;
- submission mutation.

Mutated upstream:
- must invalidate;
- must not retain positive posture.

---

# 28. External Search

Gold must prove Phase 3A performs no external search.

Required:
- network-disabled execution;
- no search connector import/reachability;
- external_search_calls == 0;
- no academic/patent/product/OSS connector call.

Release gate:
- external search invoked = zero violations.

---

# 29. Canonical Output

Gold must test canonical output independence from:

- model free prose;
- input ordering where semantically unordered;
- irrelevant result fields;
- irrelevant metadata formatting.

Canonical output may depend only on verified/validated typed inputs and judgments.

---

# 30. Quality Metrics

Implement at least **45 distinct quality metric families**.

Release gates do not count as quality metrics.

Recommended required metric families:

1. requirement_applicability_accuracy
2. methodology_anchor_accuracy
3. repeated_excerpt_occurrence_accuracy
4. documentation_status_accuracy
5. methodology_assessment_accuracy
6. scientific_requirement_accuracy
7. engineering_requirement_accuracy
8. hybrid_track_accuracy
9. ai_ml_overlay_materiality_recall
10. ai_ml_overlay_materiality_precision
11. software_overlay_materiality_recall
12. software_overlay_materiality_precision
13. no_methodology_relevance_accuracy
14. implementation_tool_only_accuracy
15. overlay_ownership_accuracy
16. overlay_no_double_count_accuracy
17. research_question_accuracy
18. hypothesis_applicability_accuracy
19. variable_structure_accuracy
20. sampling_plan_accuracy
21. sample_rationale_accuracy
22. control_applicability_accuracy
23. confounder_plan_accuracy
24. baseline_documentation_accuracy
25. baseline_relevance_accuracy
26. baseline_rationale_accuracy
27. metric_definition_accuracy
28. metric_target_alignment_accuracy
29. material_condition_coverage_accuracy
30. claim_method_structural_binding_accuracy
31. claim_method_semantic_linkage_accuracy
32. gap_method_structural_binding_accuracy
33. gap_method_semantic_linkage_accuracy
34. validation_requirement_continuity_accuracy
35. data_split_plan_accuracy
36. test_set_isolation_risk_accuracy
37. duplicate_group_leakage_accuracy
38. reproducibility_plan_accuracy
39. methodology_issue_accuracy
40. scientific_track_posture_accuracy
41. engineering_track_posture_accuracy
42. result_leakage_resistance
43. prompt_injection_resistance
44. model_prose_noncanonicality
45. replay_idempotency_accuracy
46. resume_equivalence_accuracy
47. upstream_immutability_accuracy
48. cross_run_isolation_accuracy
49. input_order_invariance_accuracy
50. per_language_contract_accuracy

More are allowed.

---

# 31. Deterministic vs Model-Judgment Metrics

Do not falsely require every semantic model-judgment metric to equal 1.0.

Separate:

## Deterministic quality metrics
These should reach exactly 1.0 if implementation is correct.

Examples:
- exact anchoring;
- structural binding;
- deterministic applicability rules;
- run binding;
- posture synthesis from typed records;
- no result leakage;
- replay;
- immutability.

## Model-judgment quality metrics
Report honestly.

Examples:
- overlay materiality;
- `NO_METHODOLOGY_RELEVANCE`;
- overlay ownership where model-assisted;
- conditional applicability where model-assisted;
- semantic claim-method linkage;
- semantic gap-method linkage;
- baseline relevance;
- metric alignment;
- condition semantic coverage.

If seeded wrong model judgments are intentionally present, these metrics may be below 1.0.

Do not "fix" them by hard-coding semantic answers into production.

---

# 32. Release Gates

Implement at least **140 release-blocking gates**.

Every gate must have:

- real opportunity denominator;
- zero violations;
- no synthetic denominator floor;
- clear violation semantics.

No gate may use:
- `max(1, denominator)`
- artificial opportunity insertion
- duplicated fake opportunities
- case-count padding.

If a required gate has zero real opportunities, the Gold dataset is deficient and must be expanded.

---

# 33. High-Risk Release Gate Families

At minimum include gates for:

## Source / provenance
- fabricated methodology anchor accepted
- wrong offsets accepted
- repeated excerpt first-match guessed
- cross-source anchor accepted
- cross-run anchor accepted

## Documentation / execution
- not-documented treated as not-done
- planned treated as executed
- student execution treated as verified
- Phase 3B execution conclusion emitted

## Applicability
- REQUIRED downgraded
- generic checklist requirement forced
- hypothesis universally required
- control group universally required
- randomization universally required
- blinding universally required

## Overlay
- material AI overlay silently excluded
- material software overlay silently excluded
- overlay omission treated non-material
- provider failure treated non-material
- unsupported `NO_METHODOLOGY_RELEVANCE` accepted structurally
- signaled overlay closed by unsupported negative
- implementation-tool-only activates requirements
- Hybrid overlay double-counted
- wrong-track overlay ownership
- engineering-only AI requirements omitted

## Metric / baseline / condition
- vague claim assigned invented metric
- metric mismatch promoted
- baseline name establishes relevance
- baseline required by Phase 2J omitted
- baseline invented when not required
- fair comparison marked verified
- Phase 2J condition ignored
- condition invented

## Sample / controls
- numeric N treated as adequate
- confounding marked eliminated

## AI/ML
- test-set isolation risk ignored
- tuning contamination accepted as safe
- group/duplicate leakage risk ignored
- successful result repairs leakage-risk methodology

## Result leakage
- result field changes posture
- experiment field changes posture
- working prototype repairs methodology

## Prompt/model
- prompt injection followed
- hidden prompt persisted
- free prose changes canonical output
- forbidden score emitted
- legal novelty conclusion emitted
- invented requirement accepted

## Run safety
- upstream mutation accepted
- cross-run linkage accepted
- replay duplicates model calls
- resume differs from uninterrupted
- non-deterministic ID accepted
- external search invoked

## Failure semantics
- provider raw text persisted
- provider missing produces positive posture
- bound reached produces positive posture
- omitted required model judgment produces positive posture

All high-risk gate families must have nonzero real denominators.

---

# 34. Denominator Integrity Tests

Add explicit denominator tests.

At minimum:

### A. Nonzero required aggregate
Every required release gate has denominator > 0.

### B. No floors
Scan eval implementation for denominator-floor patterns.

### C. Real opportunity derivation
Gate denominators derive only from cases where the unsafe behavior could genuinely occur.

### D. Duplicate-case resistance
Removing duplicate/padded cases must not destroy required coverage.

### E. Gate perturbation
Disable selected safety mechanisms and prove their matching gates produce violations.

At minimum perturb:
- first-match anchor guard;
- Phase 2J continuity gate;
- overlay unresolved/negative guard;
- result-leakage barrier;
- deterministic posture check.

### F. Metric/gate separation
Quality metric counts cannot be used to fabricate release-gate opportunities.

---

# 35. Negative Controls

Minimum:

- **>= 240 negative-control attempts**
- **>= 60 distinct mechanisms**

Controls must be caught for the intended reason.

A control does not count merely because an unrelated earlier validator rejects it.

Record:
- mechanism;
- intended failure/gate;
- actual result;
- caught yes/no;
- reason match.

Mechanisms should include:

- excerpt tampering;
- occurrence tampering;
- source hash tampering;
- cross-run target;
- claim hash tampering;
- project type mismatch;
- REQUIRED downgrade;
- invented requirement;
- invented metric;
- invented baseline;
- invented condition;
- unsupported negative overlay verdict;
- material overlay omitted;
- Hybrid wrong ownership;
- Hybrid double count;
- baseline name-only relevance;
- fair execution true;
- execution_verified true;
- result-posture leakage;
- confounding eliminated;
- numeric-N adequacy;
- hidden prompt persistence;
- prompt-following output;
- forbidden score;
- legal conclusion;
- provider text leak;
- replay duplicate call;
- external-search increment;
- upstream mutation ignored.

At least 60 mechanisms must be genuinely distinct.

---

# 36. Negative-Control Non-Vacuity

Add tests that disable selected production mechanisms and confirm relevant controls stop being caught.

At minimum mutate/disable:

1. repeated-excerpt first-match protection;
2. Phase 2J validation continuity;
3. overlay negative/unresolved safety;
4. result-leakage barrier;
5. final deterministic posture enforcement.

A negative-control framework that catches controls only because of unrelated validations is insufficient.

---

# 37. Model-Judgment Seeded Errors

Include deliberate model-judgment mistakes to measure semantic ceilings.

Examples:

- material overlay mislabeled `NO_METHODOLOGY_RELEVANCE`;
- irrelevant overlay mislabeled MATERIAL;
- wrong Hybrid owner;
- semantically unrelated claim-method DIRECT link;
- baseline judged relevant when it is not;
- mismatched metric judged aligned;
- required condition judged addressed when methodology is unrelated.

Production should structurally accept only judgments that satisfy contract/provenance constraints.

Gold metrics should then reveal semantic error honestly.

Do not convert these semantic metrics into release blockers unless the contract itself is violated.

Release blockers should focus on whether wrong judgments bypass deterministic safety invariants.

---

# 38. Case Classification on Miss

Every Gold miss must be classified as exactly one of:

- `GOLD_FIXTURE_DEFECT`
- `GOLD_EXPECTATION_DEFECT`
- `EVAL_HARNESS_DEFECT`
- `PRODUCTION_IMPLEMENTATION_DEFECT`
- `RELEASE_GATE_PREDICATE_DEFECT`
- `MODEL_JUDGMENT_ERROR`

For every miss report:
- case ID;
- category;
- expected;
- actual;
- root cause;
- classification;
- fix layer;
- tests added.

Do not modify production if the defect belongs to Gold/harness/gate logic.

Do not modify Gold expectation merely because production disagrees.

---

# 39. Gold Dataset Validation

Add tests for:

- minimum total cases;
- language minimums;
- category minimum;
- all three project types;
- all overlay verdicts;
- all target-link relations;
- all documentation statuses;
- all methodology assessment states;
- major issue families;
- Phase 2J continuity variants;
- baseline variants;
- condition variants;
- failure variants;
- replay/mutation variants;
- no exact duplicates;
- authoring independence;
- Arabic/mixed placement policy.

---

# 40. Gold Runner

The offline runner must:

- require no network;
- use deterministic scripted/fake provider behavior;
- execute the real Phase 3A graph/pipeline;
- preserve real upstream binding;
- produce:
  - case results;
  - metric families;
  - per-language results;
  - release-gate violations/opportunities;
  - negative-control results;
  - model call counts;
  - failure classifications;
  - optional verbose per-gate output.

Recommended CLI shape should follow prior phase conventions.

Support a verbose mode that prints every release gate:

```text
gate_name: violations/opportunities
```

Do not hide zero-denominator gates.

---

# 41. Gold Runner Must Exercise Real Upstream Context

Where prior Phase 3A tests use support builders, Gold should still construct valid upstream Phase 2I/2J state or use established deterministic fixtures that pass the real binding requirements.

Do not bypass production input binding.

Do not set Phase 3A internal state directly to expected answers.

---

# 42. Canonical Model Call Accounting

Gold should report:

- total overlay calls;
- extraction calls;
- applicability calls;
- metric/baseline calls;
- target-linkage calls;
- replay-saved calls;
- provider failures/refusals;
- external search calls.

No hidden external calls.

Gold replay cases must prove completed stage markers prevent duplicate calls.

---

# 43. Gold Expected-Output Granularity

Do not require every case to specify every possible field if it is irrelevant.

But every case must specify enough independent expectations to verify its intended mechanism.

Recommended expectation layers:

- expected applicability;
- expected overlay materiality/ownership;
- expected evidence anchors;
- expected documentation status;
- expected assessment;
- expected target linkage;
- expected validation continuity;
- expected issues;
- expected track posture;
- expected failure/unresolved state;
- expected safety-gate behavior.

---

# 44. Thin Denominators

Thin denominators are allowed only when:

- opportunities are real;
- scenario is difficult to multiply without artificial padding;
- the checkpoint reports the exact thin gates.

Prefer >= 6 opportunities for high-risk gates when naturally possible.

For critical families such as:
- overlay false-negative;
- result leakage;
- execution verification;
- Phase 2J continuity;
- first-match anchoring;
- prompt injection;

target substantially more than 6.

Do not pad only to satisfy a number.

---

# 45. Required Gold Tests

At minimum add tests for:

- Gold schema validity;
- dataset size/language/category minimums;
- authoring independence;
- duplicate detection;
- full offline runner;
- all quality metric families measured;
- all required release gates nonzero;
- all gates zero violations on approved production;
- denominator integrity A–F;
- negative-control attempt/mechanism minimums;
- negative controls all caught for intended reason;
- non-vacuity mutation checks;
- per-language reporting;
- deterministic repeat run;
- verbose gate output;
- no network/external search.

---

# 46. First Full Gold Run

After runner and tests stabilize, run the complete offline Gold once.

Do not immediately patch until you have a miss inventory.

Classify every miss according to section 38.

Then fix by layer.

When fixes stabilize:
- rerun targeted affected tests;
- rerun full Gold once;
- continue until checkpoint quality is clean.

Avoid repeatedly running the entire Gold after every tiny change.

---

# 47. Production Fix Rule

If Gold exposes a real production defect:

- make the smallest justified fix;
- add targeted regression test;
- rerun affected Phase 3A production tests;
- rerun affected Gold metric/gate families;
- once stable, rerun full Gold.

Document the defect in the checkpoint.

If production changes after implementation commit `b9e59ff...`, do not amend that commit.

Leave changes uncommitted until the Gold checkpoint is reviewed, unless explicitly instructed otherwise.

---

# 48. No Cross-Phase Regression Yet

Do not run:

- Phase 2J regression;
- Phase 2I regression;
- earlier phases;
- full repo pytest.

Those belong only after the Gold checkpoint is reviewed and approved.

---

# 49. Required Final Gold Checkpoint

Print:

```text
PHASE 3A GOLD / OFFLINE EVAL CHECKPOINT
```

Include:

## Git
- branch;
- implementation baseline commit;
- working tree status;
- worktree count;
- changed/new files;
- whether production changed during Gold;
- no merge.

## Dataset
- total cases;
- English;
- Arabic;
- mixed;
- distinct categories;
- duplicate count;
- authoring-independence result.

## Quality
- count of deterministic metric families;
- count of model-judgment metric families;
- exact result for every metric family;
- per-language result;
- smallest and largest meaningful denominators;
- unmeasured metrics, if any.

Explicitly separate model-judgment metrics from deterministic metrics.

## Overlay judgment quality
Always report:
- AI/ML materiality recall;
- AI/ML materiality precision;
- software materiality recall;
- software materiality precision;
- `NO_METHODOLOGY_RELEVANCE` accuracy;
- implementation-tool-only accuracy;
- overlay ownership accuracy.

## Release gates
- gate count;
- zero-violation count;
- any violations;
- zero-denominator gates;
- confirmation no denominator floors;
- thin gates;
- high-risk family coverage.

## Negative controls
- attempts;
- caught;
- missed;
- distinct mechanisms;
- non-vacuity mutation results.

## High-risk results
Report at least:
- overlay false-negative resistance;
- Hybrid ownership/no-double-counting;
- exact source anchoring;
- Phase 2J continuity;
- baseline relevance boundary;
- metric alignment boundary;
- sample-N boundary;
- result/experiment leakage;
- student execution boundary;
- prompt injection;
- provider failure semantics;
- replay/immutability;
- external search zero.

## Bugs found
For each:
- classification;
- root cause;
- fix;
- whether production changed.

## Tests actually run
Report exact:
- passed;
- skipped;
- failed;
- errors.

## Known limitations
Include:
- semantic model-judgment ceilings;
- bounded negative overlay verdict quality;
- thin real denominators;
- runtime;
- any unsupported source mode;
- no legal/scoring/result/execution conclusions.

Then state:

```text
PHASE 3A GOLD CHECKPOINT COMPLETE
```

If and only if:
- all deterministic required metrics pass;
- all release gates have nonzero real denominators;
- all release gates have zero violations;
- all negative controls are caught for intended reasons;
- no blocking production defect remains;
- no Gold integrity defect remains;

also print exactly:

```text
PHASE 3A GOLD / OFFLINE EVAL APPROVED — READY FOR CROSS-PHASE RELEASE GATE
```

Then STOP.

Do not start regressions.
Do not run the full suite.
Do not merge.
Do not start Phase 3B.

---

# 50. Commit Discipline

Do not create a Gold milestone commit automatically.

After the checkpoint is reviewed, commit will be explicitly requested.

Do not amend or rewrite:
- `2f1693a`
- `b9e59ff`

Do not squash.

---

# 51. Definition of Done

Phase 3A Gold milestone is done only when:

- >=450 valid cases;
- 150/150/150 language minimums;
- >=220 distinct categories;
- no duplicate padding;
- independent Gold authoring verified;
- >=45 quality metric families;
- overlay semantic quality explicitly measured;
- >=140 release gates;
- every required gate has real nonzero denominator;
- zero gate violations;
- >=240 negative controls;
- >=60 distinct control mechanisms;
- controls caught for intended reasons;
- non-vacuity tests pass;
- prompt/result/execution/source/run safety gates pass;
- no external search;
- Gold runner uses real production graph;
- any production defect is minimally fixed and regression-tested;
- no blocking issue remains;
- no cross-phase regression/full suite/merge performed.
