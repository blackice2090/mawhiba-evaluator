# Phase 3B — Experiment Review Planning & Architecture Gate

## Status

Planning/architecture milestone only.

Do **not** implement Phase 3B in this pass.

Repository state entering Phase 3B:

- `main` = `9d9e64eb16acedcb85007112f874762336a20d74`
- Phase 3A — Methodology Review: CLOSED, MERGED & PUSHED
- `origin/main` = `9d9e64eb16acedcb85007112f874762336a20d74`
- unrelated local path `homepage-preview/` remains untracked and must stay untouched

Phase 3B follows:

```text
PRIOR ART
→ NOVELTY
→ RESEARCH / ENGINEERING GAP
→ METHODOLOGY REVIEW
→ EXPERIMENT REVIEW
→ RESULT REVIEW
→ RED TEAM
→ SCORE
→ READINESS
```

Phase 3B must remain strictly separate from later Result Review.

---

# 1. Phase Goal

Build the architecture for an evidence-driven **Experiment Review** layer that determines whether each experiment or validation activity is sufficiently designed, documented, controlled, measurable, reproducible, and properly connected to the project's claims and Phase 2J validation requirements.

Phase 3B must answer:

> Does the documented experiment/test protocol provide an adequate and auditable way to test the relevant scientific or engineering claim?

It must **not** answer:

> Did the project succeed?

It must **not** answer:

> Are the reported results true?

It must **not** produce project scores, legal conclusions, novelty conclusions, or final readiness conclusions.

---

# 2. Source Requirements From the Project Master

For each experiment, Phase 3B must be able to review, where applicable:

- Objective
- Hypothesis
- Setup
- Inputs
- Outputs
- Variables
- Controls
- Baseline
- Sample Size
- Number of Repetitions
- Environment
- Measurement Method
- Error Sources
- Bias
- Metrics
- Statistical Analysis
- Success Criteria
- Reproducibility

For quantitative experiments, statistical review may include when appropriate:

- Mean
- Median
- Standard Deviation
- Variance
- Confidence Interval
- Effect Size
- Statistical Significance
- Appropriate Statistical Test
- Number of Observations
- Outliers
- Multiple Comparisons
- Uncertainty

Do not impose advanced statistics when they are not appropriate.

Do not accept:

```text
"the device worked"
```

as sufficient experimental validation of a scientific or engineering claim.

The key question remains:

> Does the experiment test the claim that matters?

---

# 3. Fundamental Boundary: 3A vs 3B vs Result Review

## Phase 3A — Methodology Review

Evaluates the project's overall method and whether the planned methodology contains the elements needed to investigate or validate the project.

Examples:

- research design;
- engineering validation strategy;
- AI/ML methodology;
- software/system methodology;
- methodology-to-claim linkage;
- Phase 2J validation continuity.

Phase 3A does **not** verify experimental outcomes.

## Phase 3B — Experiment Review

Evaluates the concrete experiment/test protocol and its documented execution structure.

Examples:

- what was tested;
- under what setup;
- with which inputs;
- against which baseline/control;
- how many samples/repetitions;
- what was measured;
- under what environment;
- what uncertainty/error/bias exists;
- what success criterion was defined;
- whether the protocol is reproducible;
- whether the experiment actually targets the relevant claim/gap.

Phase 3B may record that the student **describes** an experiment as executed.

It must not convert a student statement into verified execution unless a later approved contract explicitly defines and validates execution evidence.

## Result Review — Later Phase

Owns:

- observations;
- measurements;
- reported result values;
- statistical results;
- interpretation;
- causality;
- generalization;
- negative results;
- whether results support claims.

Phase 3B must quarantine result content from experiment adequacy decisions.

Required invariant:

```text
good experiment design ≠ successful result

reported success ≠ adequate experiment design

reported metric value ≠ verified measurement

experiment execution statement ≠ verified execution
```

---

# 4. EXECUTION DISCIPLINE — APPLY TO THIS PHASE

This planning pass is architecture-only.

- Work from `main` at `9d9e64eb16acedcb85007112f874762336a20d74`.
- Create a dedicated feature branch for Phase 3B.
- Do not modify Phase 3A semantics unless an explicit architecture conflict is discovered.
- Do not implement production Phase 3B nodes during this planning pass.
- Do not create the Gold dataset during this planning pass.
- Do not modify historical Gold data.
- Do not run the full repository suite.
- Use only the smallest targeted architecture/contract tests required by the planning gate.
- Reuse established Phase 3A/Phase 2J architecture patterns where appropriate.
- No unrelated refactors.
- No speculative infrastructure.
- No automatic next milestone.
- No merge.
- No push unless separately requested.
- Do not touch `homepage-preview/`.
- Do not add `Co-Authored-By` or AI-attribution lines to commits.

Primary session owns the work.

Do not delegate the whole phase to subagents.

If architecture conflicts with existing contracts, STOP and report instead of silently broadening scope.

---

# 5. Context / Model Discipline

Before substantial architecture work:

```text
/clear
/model opus
```

Use Opus for the architecture gate.

After the architecture milestone is approved and committed, implementation may switch to Sonnet.

During long work:

- use `/context`;
- compact at a logical milestone if context approaches ~70–80%;
- do not start a substantial new task above ~80%;
- do not `/clear` during an unfinished architecture decision.

---

# 6. Phase 3B Input Boundary

The architecture must explicitly define which upstream artifacts are authoritative inputs.

At minimum inspect and decide contracts for:

## From intake / canonical source

- authoritative student submission text;
- bound artifact identity/hash;
- exact source offsets/excerpts.

## From Phase 2J

- canonical project type;
- gap hypotheses;
- gap linkage;
- validation requirements;
- metric;
- baseline if present;
- conditions.

Phase 2J continuity is mandatory.

If a Phase 2J validation requirement exists, Phase 3B must preserve its exact target identity.

Do not allow an experiment for one claim/hypothesis to satisfy another merely because it uses a similar metric.

## From Phase 3A

Phase 3A methodology review may provide:

- methodology requirement inventory;
- applicability;
- documented methodology evidence;
- claim-method linkage;
- gap-method linkage;
- methodology issues/posture.

Phase 3B may use Phase 3A as context.

Phase 3A must not be treated as proof that the experiment was actually executed.

## From later phases

No input from future Result Review, Red Team, Score, or Readiness.

Result leakage must be structurally barred.

---

# 7. Experiment Identity

Phase 3B must define a canonical experiment/test identity.

Do not collapse distinct experiments simply because they share:

- the same metric;
- the same dataset;
- the same hardware;
- the same claim;
- similar wording.

Candidate identity should be based on a deterministic tuple such as:

```text
project/run
+ experiment source span
+ target claim/hypothesis
+ protocol identity
```

Architecture must decide:

- stable ID strategy;
- replay behavior;
- duplicate detection;
- repeated-description handling;
- whether one experiment can target multiple claims;
- whether one claim can have multiple experiments.

Expected relationship:

```text
one claim → zero, one, or many experiments
one experiment → one or more explicitly bound targets
```

No implicit cross-target substitution.

---

# 8. Experiment Record Contract

Design a typed canonical record for each experiment.

The architecture must decide exact fields, but it should cover at least:

## Identity / provenance

- experiment ID;
- research/run ID;
- source artifact ID/hash;
- exact source excerpts;
- target claim IDs;
- target Phase 2J hypothesis IDs;
- target Phase 2J validation requirement IDs if available.

## Experiment purpose

- objective;
- hypothesis or engineering validation objective;
- experiment type;
- applicability.

## Protocol

- setup;
- inputs;
- outputs;
- variables;
- controlled variables;
- control group or control strategy when applicable;
- baseline;
- sample;
- sample size;
- repetitions;
- environment;
- measurement method;
- metrics;
- statistical-analysis plan where applicable;
- success criteria;
- reproducibility information.

## Risks / limitations

- error sources;
- bias;
- uncertainty;
- confounding;
- leakage risk for AI/ML;
- measurement limitations;
- environmental limitations.

## Execution boundary

- described execution status;
- execution evidence references, if architecture supports them;
- `execution_verified` must default to false unless an explicit evidence-verification contract is approved.

## Assessment

Separate:

```text
DOCUMENTATION STATUS
```

from:

```text
EXPERIMENT ADEQUACY
```

and from:

```text
RESULT VALIDITY
```

Phase 3B owns only the first two.

---

# 9. Experiment Type Taxonomy

Architecture must define a closed typed taxonomy.

At minimum consider:

- SCIENTIFIC_CONTROLLED_EXPERIMENT
- SCIENTIFIC_OBSERVATIONAL_STUDY
- ENGINEERING_BENCH_TEST
- ENGINEERING_FIELD_TEST
- ENGINEERING_STRESS_TEST
- ENGINEERING_COMPARATIVE_TEST
- AI_ML_MODEL_EVALUATION
- AI_ML_ABLATION
- AI_ML_EXTERNAL_VALIDATION
- SOFTWARE_BENCHMARK
- SOFTWARE_LOAD_TEST
- SOFTWARE_SECURITY_TEST
- SOFTWARE_USABILITY_TEST
- SIMULATION
- OTHER_BOUNDED_EXPERIMENT
- UNKNOWN

Do not accept free-form experiment types as canonical state.

The architecture must decide which types require which fields.

---

# 10. Applicability

Every experiment requirement must have explicit applicability:

- REQUIRED
- CONDITIONAL
- OPTIONAL
- NOT_APPLICABLE

The model may help resolve bounded conditional applicability.

The model may not make a field optional merely because the student omitted it.

Examples:

- control group is not universal;
- randomization is not universal;
- blinding is not universal;
- statistical significance is not universal;
- cross-validation is not universal;
- external validation is not universal;
- repetitions may differ by experiment type;
- success criteria should normally be defined before result interpretation.

---

# 11. Core Requirement Inventory

Create a closed requirement inventory for Phase 3B.

The architecture must determine exact IDs and type-specific applicability.

Candidate requirement groups:

## A. Purpose and target

- objective defined
- target claim bound
- target Phase 2J validation requirement bound
- hypothesis / engineering validation objective appropriate
- success criterion defined

## B. Setup and environment

- setup documented
- environment documented
- hardware/software/material configuration documented
- calibration documented when material
- operating conditions documented

## C. Inputs and outputs

- inputs defined
- outputs defined
- inclusion/exclusion rules
- data provenance
- sample identity
- test-set independence where relevant

## D. Variables and controls

- independent variable
- dependent variable
- controlled variables
- control group/strategy
- confounders considered
- intervention/comparator separation

## E. Baseline / comparator

- baseline identified when improvement claim exists
- baseline relevance
- baseline fairness
- same evaluation conditions where required
- comparator version/configuration documented

Do not claim fair execution unless directly supported.

## F. Sample / repetitions

- sample defined
- sample size documented
- sample-size rationale where appropriate
- number of observations
- repetitions
- independent repetitions
- random seed / repeatability where appropriate

Bare sample numbers must not automatically imply adequacy.

## G. Measurement

- measurement method
- instrument/tool
- calibration
- units
- metric
- metric-target alignment
- measurement resolution
- error/uncertainty
- missing-data handling

## H. Statistics

Where applicable:

- descriptive statistics
- uncertainty
- confidence interval
- effect size
- statistical test
- assumptions
- multiple comparisons
- outliers
- statistical power / sample adequacy if appropriate

Do not impose statistical machinery that does not fit the experiment.

## I. Bias / leakage

- selection bias
- measurement bias
- observer bias
- confounding
- train/test leakage
- duplicate leakage
- tuning on test data
- benchmark contamination where relevant

## J. Reproducibility

- enough protocol detail
- environment/configuration
- seed/version information where relevant
- repeatability
- independent reproduction status if actually documented

`reproducible protocol` must not become `independently reproduced`.

## K. Safety / ethics where material

- safety controls
- human-subject/animal/data constraints when applicable
- privacy constraints

Do not make legal/regulatory conclusions.

---

# 12. Baseline Contract

Any improvement claim requires a comparator/baseline.

Examples:

```text
faster
more accurate
more efficient
lower cost
lower latency
lower energy
more reliable
```

must answer:

```text
compared with what?
```

Phase 3B must distinguish:

- baseline documented;
- baseline relevant;
- baseline configured comparably;
- baseline execution described;
- baseline execution verified;
- baseline result.

Phase 3B must not infer:

```text
baseline named → baseline fair
```

or:

```text
same metric used → fair comparison
```

Fairness may require:

- same input set;
- same environment;
- same hardware;
- same preprocessing;
- same evaluation metric;
- equivalent resource constraints;
- equivalent tuning opportunity.

Architecture must define which fairness properties can be deterministically proven and which remain model-assisted or unresolved.

---

# 13. Measurement Contract

A metric name is not enough.

Phase 3B must bind:

```text
measurement method
→ metric
→ target
→ success criterion
```

Required distinction:

```text
metric exists
≠ metric is aligned
≠ measurement is valid
≠ result supports claim
```

Phase 2J metric continuity is important.

If Phase 2J requires a metric for a given target, Phase 3B may only satisfy that continuity when the experiment metric is bound to the same target and semantically aligned.

A metric from another claim must never substitute.

---

# 14. Sample and Repetition Boundary

Phase 3B must avoid both extremes:

- accepting `N=500` as automatically adequate;
- declaring a small sample invalid without experiment context.

Architecture must separate:

- sample size documented;
- sample-size rationale documented;
- adequacy assessment;
- statistical power if applicable;
- number of repetitions;
- independence of repetitions.

No numeric sample size should become a truth or adequacy probability.

---

# 15. Statistical Review Boundary

Statistics are conditional.

The architecture must support:

```text
NOT_APPLICABLE
```

where appropriate.

For quantitative experiments, evaluate only what is relevant.

Examples:

- a deterministic latency benchmark may need repeated runs and distribution/uncertainty;
- a controlled biological experiment may need stronger inferential statistics;
- a prototype functional test may not require a p-value;
- an ML benchmark may need confidence intervals, repeated seeds, or external validation depending on the claim.

Prohibited:

```text
has p-value → strong experiment
```

and:

```text
no p-value → invalid experiment
```

---

# 16. AI / ML Experiment Overlay

For AI/ML experiments, architecture must consider where applicable:

- train/validation/test separation;
- test independence;
- duplicate leakage;
- data leakage;
- class imbalance;
- baseline model;
- comparator tuning fairness;
- hyperparameter selection boundary;
- repeated seeds;
- cross-validation;
- external validation;
- evaluation metrics;
- calibration if relevant;
- subgroup/error analysis;
- benchmark contamination;
- generalization boundary.

Phase 3B must not consume reported accuracy as evidence of success.

It may assess whether accuracy is an appropriate metric and whether the evaluation protocol is adequate.

---

# 17. Engineering Experiment Overlay

For engineering validation, consider:

- requirement under test;
- prototype/configuration;
- test conditions;
- stress/edge cases;
- instrumentation;
- calibration;
- control/comparator;
- repetitions;
- tolerance;
- failure modes;
- environmental conditions;
- safety;
- requirement-to-test traceability.

A demonstration is not automatically an experiment.

A prototype operating once is not automatically validation.

---

# 18. Software / Systems Experiment Overlay

Where applicable:

- workload;
- benchmark;
- hardware/environment;
- software version/configuration;
- warm-up;
- repetitions;
- latency distribution;
- throughput;
- resource use;
- failure rate;
- security test conditions;
- usability sample;
- comparator configuration.

A screenshot or successful launch is not evidence of performance, scalability, security, or usability.

---

# 19. Scientific Research Experiment Overlay

Where applicable:

- experimental design;
- sample;
- sampling;
- randomization;
- control;
- blinding;
- independent/dependent variables;
- confounders;
- repetitions;
- measurement;
- uncertainty;
- bias;
- statistical plan;
- validity;
- reproducibility.

Do not impose randomization/blinding when inappropriate.

---

# 20. HYBRID Ownership

Hybrid projects may have multiple experimental tracks.

Example:

```text
hardware sensor test
+
AI model evaluation
+
software latency benchmark
```

Architecture must avoid:

- double-counting the same experiment;
- letting a strong AI evaluation hide a weak engineering validation;
- averaging unrelated tracks into one adequacy number.

Each experiment belongs to an explicit track.

Track ownership must be deterministic when upstream evidence is sufficient.

Otherwise use bounded model judgment or unresolved ownership.

No silent averaging.

---

# 21. Claim / Gap / Experiment Linkage

Experiment linkage is a high-risk semantic step.

Architecture must define typed relations such as:

- DIRECTLY_TESTS
- PARTIALLY_TESTS
- SUPPORTING_VALIDATION
- DOES_NOT_TEST
- UNRESOLVED

The relation must bind:

```text
experiment
→ claim
→ Phase 2J gap hypothesis
→ Phase 2J validation requirement
```

where those upstream objects exist.

Prohibited:

```text
same keyword → directly tests
```

Prohibited:

```text
same metric → same target
```

Prohibited:

```text
experiment exists → claim validated
```

---

# 22. Phase 2J Continuity

This is a release-critical invariant.

For every Phase 2J validation requirement:

- preserve exact target identity;
- preserve metric if defined;
- preserve baseline if defined;
- preserve material conditions;
- record which experiment(s) attempt to satisfy it;
- record uncovered validation requirements.

Do not invent missing Phase 2J validation requirements.

Do not silently rewrite them.

Required output should distinguish:

- COVERED_BY_EXPERIMENT
- PARTIALLY_COVERED
- NOT_COVERED
- UNRESOLVED

Coverage is about protocol coverage, not result success.

---

# 23. Result Leakage Barrier

Phase 3B must structurally reject or quarantine:

- reported accuracy;
- measured improvement;
- p-values as outcomes;
- observed effect sizes;
- result tables;
- conclusions;
- success/failure interpretations;
- causality statements;
- generalization claims;
- negative-result interpretation.

Result values may exist in the student submission, but they must not drive experiment adequacy.

If result text must be preserved for later phases, store only bounded references in a separate non-consumed channel.

Phase 3B canonical assessment must not use result content.

Required mutation test:

> If reported result values are changed while the experiment protocol remains identical, Phase 3B experiment adequacy must remain unchanged.

---

# 24. Execution Evidence Boundary

Architecture must decide this explicitly.

Default safe posture:

```text
student says experiment was run
→ EXECUTION_DESCRIBED
→ execution_verified = false
```

Possible execution evidence types, if supported later:

- timestamped logs;
- raw data file references;
- instrument export;
- test script artifact;
- reproducible notebook/run artifact;
- versioned configuration;
- media showing setup.

Even then:

```text
artifact exists ≠ artifact authentic
artifact exists ≠ result correct
```

Unless a deterministic verification contract exists, keep execution verification false.

Do not build forensic authenticity verification in Phase 3B.

---

# 25. Documentation vs Adequacy vs Verification

Maintain separate dimensions.

Example:

```text
sample size = 30
```

may mean:

- documented = yes;
- adequacy = unresolved/insufficient/context-dependent;
- execution verified = false.

Example:

```text
baseline = XGBoost
```

may mean:

- documented = yes;
- relevance = maybe;
- fairness = unresolved;
- execution verified = false;
- result = not evaluated.

Never collapse these dimensions into one status.

---

# 26. Canonical Posture

Design deterministic experiment postures.

Candidate track-level postures:

- WELL_SPECIFIED
- PARTIALLY_SPECIFIED
- MAJOR_GAPS
- INSUFFICIENT_EVIDENCE
- UNRESOLVED

Do not encode truth probability.

Do not encode project score.

Do not average tracks.

Final project-level Phase 3B posture must be deterministic from track postures and uncovered material validation requirements.

Architecture must define exact precedence.

---

# 27. Failure Reasons

Use closed typed failure reasons.

Candidate groups:

## Source/provenance
- SOURCE_BINDING_MISSING
- EXACT_EXCERPT_MISMATCH
- CROSS_RUN_REFERENCE
- UNKNOWN_TARGET

## Protocol
- OBJECTIVE_MISSING
- TARGET_NOT_BOUND
- SETUP_MISSING
- INPUTS_MISSING
- OUTPUTS_MISSING
- VARIABLES_MISSING
- CONTROL_MISSING_WHEN_REQUIRED
- BASELINE_MISSING_WHEN_REQUIRED
- SAMPLE_MISSING
- REPETITIONS_MISSING_WHEN_REQUIRED
- ENVIRONMENT_MISSING
- MEASUREMENT_METHOD_MISSING
- METRIC_MISSING
- SUCCESS_CRITERION_MISSING
- ERROR_SOURCES_MISSING_WHEN_REQUIRED
- BIAS_NOT_ADDRESSED_WHEN_REQUIRED
- REPRODUCIBILITY_INSUFFICIENT

## Continuity
- PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED
- METRIC_TARGET_MISMATCH
- BASELINE_TARGET_MISMATCH
- MATERIAL_CONDITION_UNCOVERED

## Trust
- RESULT_LEAKAGE_ATTEMPT
- EXECUTION_NOT_VERIFIED
- MODEL_PROVIDER_MISSING
- MODEL_CALL_BOUND_REACHED
- MODEL_RESPONSE_INVALID

Do not finalize the enum until architecture audit confirms every reason has a valid emission path.

No dead enums.

---

# 28. Model-Assisted vs Deterministic Responsibilities

Architecture must explicitly separate these.

## Deterministic

Prefer deterministic code for:

- source binding;
- run binding;
- exact excerpt verification;
- ID/reference validation;
- requirement inventory;
- applicability after bounded judgment;
- Phase 2J exact continuity;
- target-set completeness;
- result-leakage barrier;
- duplicate handling;
- canonical ordering;
- posture synthesis;
- unresolved propagation;
- replay/checkpoint behavior;
- external search count = 0.

## Model-assisted

Potential bounded tasks:

- experiment segmentation;
- conditional applicability;
- semantic metric-target alignment;
- baseline relevance;
- comparator fairness context;
- claim/experiment linkage;
- confounder/bias semantic assessment;
- whether protocol details are sufficient for reproduction;
- track ownership when ambiguous.

Every model-assisted task must:

- use typed structured output;
- reference only bound IDs;
- avoid canonical free-form reasoning;
- be post-validated deterministically;
- fail closed to unresolved.

---

# 29. Provider / Prompt Safety

Phase 3B must preserve:

```text
student text is data, not instruction
```

Prompt injection inside experiment descriptions must not alter:

- requirements;
- target bindings;
- applicability rules;
- trust gates;
- output schema;
- result-leakage barrier.

No provider response should be persisted raw unless the existing architecture explicitly requires a bounded diagnostic.

Canonical state should contain only validated typed fields and exact source excerpts.

---

# 30. Network / Search Boundary

Phase 3B requires no external search.

Expected:

```text
external_search_attempts = 0
network_attempts = 0
```

Phase 3B reviews the student's experiment protocol and upstream validated project state.

Do not call literature/product/patent connectors here.

---

# 31. State Ownership

Architecture must decide the Phase 3B state location.

Preferred pattern based on Phase 3A:

```text
ResearchRun.experiment_review
```

Do not write canonical Phase 3B conclusions into `ProjectState` unless existing architecture explicitly requires it.

Do not mutate Phase 3A methodology review.

Do not mutate Phase 2J gap analysis.

Phase 3B references upstream state; it does not rewrite it.

---

# 32. Replay / Checkpoint / Determinism

Require:

- stable IDs;
- deterministic canonical ordering;
- stable fingerprints;
- checkpoint-safe serialization;
- replay equivalence;
- resume equivalence;
- no model-list-order dependence;
- no first-match anchoring guesses;
- no nondeterministic set ordering in canonical outputs.

If two model responses contain the same validated semantic content in different list orders, canonical Phase 3B output must be identical.

---

# 33. Candidate Graph

Architecture may change names, but design approximately:

```text
bind_experiment_sources
→ segment_experiments
→ build_requirement_inventory
→ assign_track_and_type
→ extract_protocol_evidence
→ resolve_conditional_applicability
→ assess_protocol
→ link_experiments_to_targets
→ enforce_phase2j_continuity
→ synthesize_track_postures
→ finalize_experiment_review
```

The architecture gate must justify every node.

Avoid unnecessary graph fragmentation.

Bound model calls.

---

# 34. Architecture Questions That Must Be Resolved

The planning pass must answer explicitly:

1. What exactly counts as one experiment?
2. How are repeated versions/runs of the same experiment represented?
3. Can one experiment target multiple claims?
4. Can multiple experiments satisfy one Phase 2J requirement?
5. What is the canonical relationship between experiment and methodology requirement?
6. What is the exact execution-evidence boundary?
7. Can raw data artifacts be inputs now, or only later?
8. How are result values quarantined?
9. How is baseline fairness represented without pretending execution was verified?
10. Which statistical requirements are conditional by experiment type?
11. How is AI/ML leakage review represented?
12. How is Hybrid ownership resolved?
13. What happens when an experiment is well documented but does not test the target claim?
14. What happens when an experiment targets the claim but is poorly documented?
15. What happens when Phase 2J has a required metric but the experiment uses another metric?
16. What happens when Phase 2J baseline is absent?
17. What happens when success criteria were written only after results?
18. Can a student result statement ever affect Phase 3B adequacy? Expected answer: no.
19. How are negative/failed experiments represented without evaluating results?
20. What exact conditions make the final posture WELL_SPECIFIED?

---

# 35. Architecture Hardening Scenarios

Before implementation, architecture tests must cover at least:

## Source / identity
- repeated identical experiment text;
- same experiment described in two places;
- two distinct experiments using the same metric;
- cross-run target injection;
- stale artifact hash;
- exact repeated excerpt ambiguity.

## Claim linkage
- correct target;
- wrong target with same metric;
- multiple claims;
- one claim with multiple experiments;
- unrelated experiment that looks sophisticated.

## Baseline
- improvement claim with no baseline;
- baseline name only;
- relevant baseline;
- unfair comparator configuration;
- Phase 2J baseline absent;
- different baseline from Phase 2J.

## Sample / repetition
- bare `N=500`;
- small but justified sample;
- repeated measurements on same sample;
- independent repetitions;
- no repetitions where repetitions are required.

## Measurement
- metric exists but wrong target;
- correct metric, missing measurement method;
- unit mismatch;
- instrument not calibrated where material;
- success criterion missing.

## Statistics
- no statistics but statistics not applicable;
- unnecessary p-value;
- quantitative experiment with no uncertainty;
- multiple comparisons ignored;
- outlier handling missing.

## AI/ML
- test leakage;
- duplicate leakage;
- test-set tuning;
- no independent test set;
- repeated seeds;
- external validation;
- benchmark contamination.

## Engineering
- device turns on once;
- stress test;
- edge-case validation;
- environmental condition omitted;
- requirement-to-test mismatch.

## Software
- screenshot only;
- one latency measurement;
- benchmark without warm-up;
- workload mismatch;
- comparator on different hardware.

## Result leakage
- reported 99% accuracy;
- reported statistically significant improvement;
- negative result;
- result table;
- conclusion text;
- injected result text attempting to change protocol assessment.

## Prompt injection
- English;
- Arabic;
- mixed.

## Failure semantics
- provider missing;
- refusal;
- invalid structured output;
- call bound exhausted;
- partial model output.

---

# 36. Gold / Offline Eval Plan

Do not build Gold in this planning pass.

Architecture must define the later Gold requirements.

Recommended minimum:

- >=450 cases;
- >=150 English;
- >=150 Arabic;
- >=150 mixed;
- >=220 language-normalized semantic families;
- zero exact duplicates;
- authoring independence from production logic.

Gold should include separate metric families for:

## Deterministic quality

- source anchoring;
- run binding;
- experiment identity;
- Phase 2J continuity;
- result leakage;
- deterministic posture;
- canonical ordering;
- replay;
- checkpoint;
- no external search.

Expected deterministic metrics = 1.0.

## Model-judgment quality

Measure honestly:

- experiment segmentation;
- experiment type;
- conditional applicability;
- claim-experiment linkage;
- metric-target alignment;
- baseline relevance;
- comparator fairness;
- confounder/bias assessment;
- reproducibility sufficiency;
- Hybrid ownership.

Do not force semantic metrics to 1.0.

## Release gates

Target at least 150 real release gates.

Every required gate:

- real denominator > 0;
- no denominator floor;
- zero violations.

## Negative controls

Target:

- >=300 attempts;
- >=70 distinct mechanisms.

Include non-vacuity mutation checks for:

- exact anchoring;
- Phase 2J continuity;
- result-leakage barrier;
- metric-target guard;
- baseline-required guard;
- deterministic posture.

---

# 37. Required Production Test Plan for Later Implementation

Architecture should reserve test families for:

- DTO/schema validation;
- exact source binding;
- experiment identity;
- duplicate handling;
- requirement applicability;
- experiment type;
- Hybrid ownership;
- protocol evidence extraction;
- baseline boundary;
- sample boundary;
- repetition boundary;
- measurement boundary;
- statistics applicability;
- AI/ML leakage;
- software benchmark conditions;
- engineering validation;
- scientific control requirements;
- claim linkage;
- Phase 2J continuity;
- result leakage;
- execution boundary;
- prompt injection;
- provider failures;
- canonical ordering;
- replay/checkpoint;
- graph integration;
- language policy;
- workflow hardening.

---

# 38. Architecture Mutation Tests

At least five architecture non-vacuity checks should be planned before implementation.

Disable one safety mechanism and confirm a targeted test fails.

Recommended:

1. disable exact excerpt anchoring;
2. disable Phase 2J target continuity;
3. allow result values into adequacy synthesis;
4. disable metric-target alignment;
5. disable deterministic posture precedence;
6. optionally disable baseline requirement for improvement claims.

The mutation test must fail for the intended reason.

---

# 39. Git Discipline

Create:

```text
feat/phase3b-experiment-review
```

from:

```text
main@9d9e64eb16acedcb85007112f874762336a20d74
```

Before any commit verify:

- branch;
- main SHA;
- status;
- diff;
- one worktree;
- `homepage-preview/` excluded.

Do not commit local tooling such as:

- `.agents/`
- `.codex/`
- `.idea/`
- `.claude/`
- graphify caches

unless deliberately project-owned.

No force push.

No rebase.

No history rewrite.

No `Co-Authored-By`.

---

# 40. Architecture Milestone Commit

Only after architecture review passes.

Suggested commit message:

```text
feat(experiments): establish Phase 3B architecture contracts
```

Do not include implementation.

Do not include Gold.

Do not merge.

---

# 41. Required Architecture Deliverables

The planning pass must produce:

1. final architecture decision record;
2. Phase 3B DTO/schema proposal;
3. closed experiment-type taxonomy;
4. closed requirement inventory;
5. applicability matrix by project/experiment type;
6. state ownership decision;
7. graph/node design;
8. model-assisted task inventory;
9. deterministic responsibility inventory;
10. execution-evidence boundary;
11. result-leakage architecture;
12. Phase 2J continuity contract;
13. baseline/comparator contract;
14. measurement/metric contract;
15. statistics applicability contract;
16. Hybrid ownership contract;
17. failure reason taxonomy with valid emission paths;
18. replay/checkpoint/fingerprint design;
19. architecture test plan;
20. Gold plan;
21. mutation/non-vacuity plan;
22. known limitations.

---

# 42. Architecture Review Checklist

Before approval, explicitly confirm:

- Phase 3B does not evaluate results;
- Phase 3B does not infer success from reported metrics;
- Phase 3B does not verify execution from student prose;
- Phase 3B cannot consume future Result Review state;
- Phase 2J target identity is preserved;
- metric continuity is same-target only;
- baseline fairness is not inferred from baseline presence;
- bare sample size is not adequacy;
- statistics are conditional;
- AI/ML leakage is represented;
- engineering demonstrations are not automatically validation;
- screenshots are not software performance evidence;
- Hybrid tracks are not averaged;
- model output is post-validated;
- result leakage is structurally barred;
- external search = 0;
- canonical ordering is deterministic;
- replay/checkpoint invariants are explicit;
- no dead failure enums;
- no unrelated architecture changes.

---

# 43. Required Output

At the end of the planning/architecture pass print:

```text
PHASE 3B EXPERIMENT REVIEW — ARCHITECTURE CHECKPOINT
```

Include:

## Git
- branch;
- main baseline;
- working tree;
- worktree count;
- unrelated `homepage-preview/`.

## Scope boundary
- 3A vs 3B vs Result Review;
- inputs;
- forbidden inputs;
- state ownership.

## Experiment model
- identity;
- experiment types;
- requirement inventory;
- applicability;
- track ownership.

## Trust boundaries
- execution evidence;
- result leakage;
- Phase 2J continuity;
- baseline/comparator;
- measurement/metric;
- statistics;
- provider failure semantics.

## Graph
- nodes;
- model-call count/bounds;
- deterministic stages;
- model-assisted stages.

## Testing
- architecture tests actually run;
- mutation checks planned/run;
- language-policy/workflow guards if applicable.

## Gold plan
- case minimums;
- language distribution;
- semantic-family minimum;
- deterministic/model metric separation;
- release gates;
- negative controls.

## Known limitations
- bounded model semantic judgments;
- execution authenticity not verified;
- results not evaluated;
- no legal/scoring/readiness conclusions.

Then, only if the architecture is internally coherent and targeted architecture tests pass, print:

```text
PHASE 3B ARCHITECTURE APPROVED — READY FOR IMPLEMENTATION SPEC
```

Then STOP.

Do not implement Phase 3B.

Do not generate Gold.

Do not merge.

Do not start Result Review.

---

# 44. Phase 3B Core Trust Statements

Keep these explicit throughout the phase:

```text
Structured ≠ True

Documented ≠ Adequate

Adequate Protocol ≠ Successful Result

Execution Described ≠ Execution Verified

Metric Present ≠ Metric Aligned

Baseline Present ≠ Baseline Fair

Sample Size Present ≠ Sample Adequate

Repetition ≠ Independent Replication

Statistical Significance ≠ Practical Importance

Experiment Exists ≠ Claim Tested

Claim Tested ≠ Claim Supported

Result Reported ≠ Result Verified

Phase 2J Coverage ≠ Experimental Success

Experiment Review ≠ Result Review
```
