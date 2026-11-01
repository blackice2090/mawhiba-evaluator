# Phase 3B — Experiment Review Production Implementation

## Status

Production implementation milestone only.

Architecture gate is already approved and committed.

Repository:

- `mawhiba-evaluator`

Branch:

- `feat/phase3b-experiment-review`

Main baseline:

- `9d9e64eb16acedcb85007112f874762336a20d74`

Approved Phase 3B architecture commit:

- `7641ef5` — `feat(experiments): establish Phase 3B architecture contracts`

Architecture authority:

- `PHASE_3B_EXPERIMENT_REVIEW_PLANNING.md`
- `docs/adr/ADR-023-experiment-review-is-a-protocol-level-posture.md`
- `docs/phase3b_experiment_review.md`
- `src/schemas/experiment_review.py`
- existing Phase 3B architecture tests

Do not redesign the approved architecture unless a real contradiction is discovered.

Do not build Gold in this milestone.

Do not merge.

Do not start Result Review.

---

# 1. Goal

Implement Phase 3B Experiment Review as the production runtime described by the approved architecture.

Phase 3B answers:

> Does the documented experiment/test protocol provide an adequate and auditable way to test the relevant claim?

It does **not** answer:

> Did the project succeed?

It does **not** verify reported results.

It does **not** verify execution authenticity.

It does **not** score the project.

It does **not** produce legal, novelty, readiness, or jury conclusions.

The implementation must preserve:

```text
Methodology Review != Experiment Review
Experiment Review != Result Review
Documented != Adequate
Adequate Protocol != Successful Result
Execution Described != Execution Verified
Metric Present != Metric Aligned
Baseline Present != Baseline Fair
Experiment Exists != Claim Tested
Claim Tested != Claim Supported
Result Reported != Result Verified
```

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS PHASE

- Stay on `feat/phase3b-experiment-review`.
- Start from architecture commit `7641ef5`.
- Keep scope limited to Phase 3B production implementation.
- Reuse approved Phase 3B contracts and existing repository abstractions.
- Make the smallest justified changes.
- Do not change Phase 2A–2J or Phase 3A semantics.
- Do not weaken validators, assertions, schemas, gates, provenance checks, checkpoint rules, language-policy guards, or historical tests.
- Do not redesign architecture merely for coding convenience.
- Do not implement future Result Review behavior.
- Do not create the Phase 3B Gold dataset.
- Do not add release gates or negative-control harnesses intended only for Gold unless required by production contracts.
- Do not run cross-phase regressions yet.
- Do not run the full repository suite.
- Do not merge.
- Do not push unless separately requested.
- Do not touch `homepage-preview/`.
- Do not add `Co-Authored-By` or other AI attribution lines.
- Do not automatically start a hardening or Gold phase after implementation.

Testing sequence:

```text
implementation slice
→ smallest targeted tests
→ fix
→ rerun targeted tests
→ Phase 3B production tests
→ architecture/guard tests
→ implementation checkpoint
→ STOP
```

Do not repeatedly run broad suites after small edits.

Only report tests actually executed.

If implementation reveals an architecture conflict, STOP and report it instead of silently broadening the design.

---

# 3. Context / Model

Use:

```text
/clear
/model sonnet
```

This milestone is implementation against an approved architecture.

Opus is not required unless a genuine architectural contradiction appears.

Do not `/clear` in the middle of unresolved implementation debugging.

Use `/context` if the session becomes long.

---

# 4. Source Requirements

The project master requires experiment review to examine, where applicable:

- objective;
- hypothesis;
- setup;
- inputs;
- outputs;
- variables;
- controls;
- baseline;
- sample size;
- repetitions;
- environment;
- measurement method;
- error sources;
- bias;
- metrics;
- statistical analysis;
- success criteria;
- reproducibility.

The production implementation must preserve the approved applicability matrix rather than requiring every item universally.

A statement such as:

```text
the device worked
```

is not sufficient experimental validation of a scientific or engineering claim.

The implementation must preserve the architecture rule:

> the experiment must test the claim that matters.

---

# 5. Approved State Ownership

Use the architecture-approved state location:

```text
ResearchRun.experiment_review
```

Do not write canonical Phase 3B conclusions into `ProjectState`.

Do not consume or mutate legacy `ProjectState.experiments`.

Do not mutate:

- Phase 2J gap analysis;
- Phase 3A methodology review;
- claim state;
- ProjectState results.

Phase 3B is an additive downstream research-run layer.

---

# 6. Forbidden Inputs

Production logic must not consume:

- `ProjectState.results`;
- legacy `ProjectState.experiments`;
- Phase 2F scoring values as evidence;
- trust-gate output as evidence;
- future Result Review output;
- Red Team output;
- Score output;
- Readiness output.

If any existing helper exposes these fields, do not pass them into Phase 3B derivation functions.

Result content must never influence protocol adequacy.

---

# 7. Production Package

Implement a focused package under an architecture-consistent location, preferably:

```text
src/research/experiments/
```

or the exact location already defined by the architecture docs if different.

Keep modules small and responsibility-specific.

Expected responsibilities may include:

- source/run verification;
- experiment segmentation;
- protocol evidence extraction;
- requirement inventory/application;
- applicability resolution;
- measurement/metric assessment;
- baseline/comparator assessment;
- target linkage;
- Phase 2J continuity;
- result quarantine;
- synthesis;
- pipeline/orchestration.

Do not create one giant module.

Do not create speculative abstractions unused by Phase 3B.

Use the architecture docs and schema names as canonical. Do not invent duplicate DTOs when `src/schemas/experiment_review.py` already defines them.

---

# 8. Approved Graph

Implement the approved seven-stage graph:

```text
bind_inputs
→ segment_experiments
→ extract_protocol
→ resolve_applicability
→ link_targets
→ synthesize
→ finalize
```

Names may match the architecture's exact node names.

Do not add nodes unless required by a concrete contract.

Each stage must have one clear responsibility.

## bind_inputs

Deterministically verify and bind:

- run identity;
- authoritative submission artifact id/hash;
- claims;
- Phase 2J run;
- Phase 3A run context;
- upstream fingerprints.

Reject or fail closed on:

- mismatched run;
- stale artifact;
- missing required upstream state;
- cross-run references.

## segment_experiments

Model-assisted and bounded.

It may identify concrete experiment/test protocol descriptions.

It must return typed references to exact source spans.

No free-form canonical experiment prose.

Post-validate every span.

No first-match guessing.

No result content may become a defining protocol excerpt.

## extract_protocol

Model-assisted and bounded.

Extract only approved typed protocol fields.

Every evidence-bearing field must point to verified exact source excerpts.

Do not allow model prose to become canonical evidence.

## resolve_applicability

Apply the deterministic catalog first.

The model may resolve only architecture-approved conditional applicability.

A missing student field is never evidence that the requirement is not applicable.

Required cannot be lowered.

UNKNOWN experiment type must not become WELL_SPECIFIED.

## link_targets

Model-assisted semantic judgment with deterministic post-validation.

Bind each experiment to allowed claim/hypothesis/Phase 2J validation requirement IDs.

No unknown IDs.

No cross-run IDs.

No same-keyword shortcut.

No same-metric shortcut.

## synthesize

Deterministic.

Compute:

- documentation statuses;
- adequacy statuses;
- track postures;
- continuity coverage;
- unresolved propagation;
- project-level Phase 3B posture.

Do not use reported result values.

Do not use raw model prose.

## finalize

Deterministically verify:

- upstream fingerprint stability;
- canonical ordering;
- checkpoint-safe state;
- model-call bounds;
- external search attempts = 0;
- network attempts = 0;
- result-quarantine integrity.

Persist only validated canonical output.

---

# 9. Model Call Budget

Preserve the approved bound:

```text
1 + 3 per experiment
```

Default architecture:

- max experiments = 12;
- theoretical model calls = 37;
- configured hard budget = 40.

The implementation must enforce the hard bound.

If the bound is reached:

- do not silently skip safety validation;
- emit the approved bounded failure reason;
- propagate UNRESOLVED / INSUFFICIENT as defined by architecture.

Do not add hidden retry loops that can exceed the bound.

---

# 10. Experiment Identity

Implement the approved identity rule.

Canonical ID:

```text
uuid5(run, protocol_key)
```

where `protocol_key` is based on the defining protocol excerpt texts in document order.

Preserve approved behavior:

- offsets are not identity;
- target IDs are not identity;
- adding unrelated text elsewhere must not change experiment ID;
- same protocol text described in multiple locations collapses into one experiment record with multiple defining excerpts;
- a changed protocol is a new experiment;
- revisions use `revision_of`.

Add deterministic canonical ordering.

Test identity stability under unrelated-offset shifts.

---

# 11. Experiment Type and Family

Use only the architecture-approved closed experiment-type taxonomy.

Do not accept arbitrary canonical type strings.

Preserve:

- 16 approved experiment types;
- six approved families;
- UNKNOWN behavior.

The experiment family chooses applicability-table context.

It does not determine track ownership.

Do not collapse:

```text
AI/ML evaluation
```

into:

```text
software benchmark
```

or vice versa unless the architecture explicitly maps them.

---

# 12. Requirement Inventory

Implement the architecture-approved:

- 68 requirement kinds;
- 11 requirement groups;
- 25 conditional triggers.

Do not regenerate this inventory from model text.

Use deterministic catalog definitions.

Every requirement record must preserve:

- kind;
- applicability;
- documentation status;
- adequacy assessment;
- evidence refs;
- issue/failure reason;
- target/track binding where defined.

Do not collapse documentation and adequacy.

---

# 13. Applicability

Preserve:

- REQUIRED
- CONDITIONAL
- OPTIONAL
- NOT_APPLICABLE

Rules:

- deterministic table first;
- model only for unresolved conditional triggers;
- model must cite bound exact source;
- omission is not a reason for NOT_APPLICABLE;
- REQUIRED can never be lowered;
- invalid provider output fails closed.

Add tests for:

- control group conditionality;
- randomization conditionality;
- blinding conditionality;
- statistics conditionality;
- repetitions conditionality;
- external validation conditionality;
- UNKNOWN type.

---

# 14. Exact Source Anchoring

Every protocol evidence excerpt must be verified against the authoritative submission.

Required:

- artifact binding;
- hash binding;
- exact offsets;
- exact text match;
- deterministic repeated-text disambiguation.

Never use:

```text
str.find(first occurrence)
```

as an unqualified anchoring strategy.

If repeated text cannot be disambiguated safely, fail closed.

Add regression tests for repeated identical excerpts.

---

# 15. Result Quarantine

This is release-critical.

Implement `QuarantinedSpan` exactly as approved.

Result content must be represented only by bounded metadata such as:

- offsets;
- hash;

and not canonical result text.

Protocol excerpts must not overlap quarantined result spans.

No synthesis function may accept result text/value parameters.

Examples of result content that must not influence adequacy:

- accuracy values;
- F1 values;
- latency outcomes;
- improvement percentages;
- p-values as observed outcomes;
- effect-size results;
- result tables;
- conclusion statements;
- positive/negative outcome interpretation.

Required deterministic mutation test:

```text
protocol unchanged
reported result changed from X to Y
→ experiment adequacy fingerprint unchanged
→ track posture unchanged
→ project posture unchanged
```

If this invariant fails, implementation is not acceptable.

---

# 16. Execution Boundary

Preserve architecture constants:

```text
execution_verified = False
independently_reproduced = False
leakage_prevented_in_practice = False
```

Phase 3B may record execution as described by the student.

Do not add a raw-data authenticity verifier.

Do not add execution artifact ingestion.

Do not infer verified execution from:

- screenshots;
- logs mentioned in prose;
- notebook mentioned in prose;
- "we tested";
- "we ran";
- "we repeated".

If student prose describes execution, preserve the approved typed statement mode only.

---

# 17. Baseline / Comparator Layers

Implement all six approved layers separately:

1. documented;
2. relevant;
3. comparable by property;
4. execution described;
5. execution verified;
6. result.

Do not introduce a canonical boolean:

```text
fair = true
```

The architecture explicitly avoids a global fairness claim.

Only architecture-approved properties may be deterministic.

The checkpoint says:

> only "same metric" can be proven deterministically.

Preserve this unless ADR-023 says otherwise.

Comparator relevance and other comparability properties are bounded semantic judgments.

A baseline name alone must not imply relevance or comparability.

Improvement claims must still require baseline/comparator coverage where Phase 2J requires it.

---

# 18. Measurement / Metric Contract

Implement the approved binding:

```text
measurement method
→ metric
→ target
→ success criterion
```

A DIRECTLY_TESTS link requires:

- same experiment;
- same claim;
- same hypothesis;
- same Phase 2J validation requirement;
- aligned measurement;
- verified measurement-method excerpt;
- verified metric excerpt.

Do not allow:

- same metric from another experiment;
- metric from another target;
- metric with no measurement method;
- metric string alone.

Preserve same-target continuity.

---

# 19. Success Criterion Timing

Implement the approved boundary:

- criterion documented before/independent of result interpretation can be valid protocol evidence;
- criterion explicitly described as set after seeing results is a major gap;
- ambiguous timing remains unresolved if architecture says so.

Do not infer timing without evidence.

Do not consume the observed result when making the timing judgment.

---

# 20. Phase 2J Continuity

Implement exact continuity.

Copy or reference exact:

- validation requirement IDs;
- anchor hashes;
- target claim/hypothesis identity;
- metric;
- baseline if defined;
- material conditions.

A Phase 2J hypothesis without a validation requirement creates no Phase 3B continuity target.

Coverage statuses:

- COVERED
- PARTIALLY_COVERED
- NOT_COVERED
- UNRESOLVED

Critical approved rule:

```text
COVERED requires one experiment to cover every required dimension.
```

Do not combine:

- metric from experiment A;
- baseline from experiment B;
- condition from experiment C;

into a synthetic COVERED state.

No cross-experiment mosaic coverage for a single requirement.

Add explicit tests.

---

# 21. Claim / Experiment Linkage

Use only the approved typed relation taxonomy.

Preserve distinctions such as:

- DIRECTLY_TESTS;
- PARTIALLY_TESTS;
- SUPPORTING_VALIDATION;
- DOES_NOT_TEST;
- UNRESOLVED.

Do not infer validation from sophistication.

A technically advanced experiment may still:

```text
DOES_NOT_TEST
```

the relevant claim.

A poorly documented experiment may target the correct claim but remain inadequate.

Keep target correctness and protocol adequacy separate.

---

# 22. Statistics

All statistics requirements are conditional.

Do not globally require:

- p-value;
- significance test;
- confidence interval;
- effect size;
- cross-validation.

Use the approved trigger catalog.

When statistical inference is claimed, apply the relevant requirements.

Do not encode:

```text
p-value exists → strong experiment
```

or:

```text
p-value missing → invalid experiment
```

without applicable trigger.

Add targeted tests for:

- no statistical trigger;
- inferential-statistics trigger;
- uncertainty/repetition benchmark cases;
- inappropriate significance test.

---

# 23. Sample Size and Repetitions

Preserve separate dimensions:

- sample documented;
- sample size documented;
- rationale documented;
- adequacy;
- number of repetitions;
- independence of repetitions.

Do not accept:

```text
N=500
```

as automatically adequate.

Do not reject a small sample merely because it is numerically small.

Repeated measurements of the same unit must not automatically become independent replications.

Use architecture-approved semantic judgment where needed.

---

# 24. AI / ML Overlay

Implement relevant approved requirements for:

- train/validation/test separation;
- independent test set;
- duplicate leakage;
- data leakage;
- tuning on test;
- class imbalance where applicable;
- baseline model;
- comparator tuning context;
- repeated seeds;
- cross-validation where applicable;
- external validation where applicable;
- metric appropriateness;
- calibration where applicable;
- subgroup/error analysis;
- benchmark contamination;
- generalization boundary.

Do not consume reported model performance values as success evidence.

The protocol may be adequate even if the later result is poor.

The protocol may be inadequate even if reported accuracy is high.

---

# 25. Engineering Overlay

Implement requirements for applicable engineering experiment types:

- requirement under test;
- prototype/configuration;
- test conditions;
- stress/edge cases;
- instrumentation;
- calibration;
- comparator/control;
- repetitions;
- tolerances;
- failure modes;
- environment;
- safety;
- requirement-to-test traceability.

A one-time demonstration is not automatically validation.

---

# 26. Software / Systems Overlay

Implement applicable protocol requirements for:

- workload;
- benchmark;
- environment;
- hardware;
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

A screenshot or successful launch is not performance/scalability/security/usability evidence.

---

# 27. Scientific Research Overlay

Implement applicability for:

- experimental design;
- sampling;
- randomization;
- controls;
- blinding;
- variables;
- confounders;
- repetitions;
- measurement;
- uncertainty;
- bias;
- statistical plan;
- reproducibility.

Do not make randomization/blinding universal.

---

# 28. Hybrid Track Ownership

Preserve approved behavior.

Single-track:

```text
all experiments → that track
```

Hybrid:

1. use Phase 2J limitation facet where sufficient;
2. otherwise bounded model judgment;
3. otherwise UNRESOLVED.

Unresolved ownership:

- counts in no track;
- caps project posture at UNRESOLVED.

Do not double-count.

Do not average tracks.

A strong AI evaluation must not hide a weak engineering validation.

---

# 29. Canonical Postures

Use only architecture-approved posture enum and deterministic precedence.

Expected set:

- WELL_SPECIFIED
- PARTIALLY_SPECIFIED
- MAJOR_GAPS
- INSUFFICIENT_EVIDENCE
- UNRESOLVED

Use the exact schema enum if names differ.

Posture synthesis must be deterministic.

No model may directly choose final project posture.

No numeric truth probability.

No project score.

No averaging tracks.

Worst-first precedence must match architecture tests.

---

# 30. Issue / Failure Codes

Use only approved issue codes.

The architecture checkpoint reports:

- 28 issue codes;
- 6 continuity reasons;
- 17 run-issue codes.

Do not add duplicate/dead enums casually.

Every code must have at least one valid emission path.

If implementation proves a code cannot be emitted legitimately:

- stop;
- document architecture conflict;
- do not leave dead enum just for apparent completeness.

Preserve removal of:

- `EXECUTION_NOT_VERIFIED` as an event code;
- `STALE_ARTIFACT_HASH` if existing codes already cover it.

---

# 31. Provider Failure Semantics

Handle separately and deterministically:

- provider missing;
- refusal;
- invalid structured output;
- partial output;
- call budget exhausted.

Do not collapse all failures into one generic message if architecture has distinct run issues.

All failures fail closed.

No provider failure can produce WELL_SPECIFIED.

No raw provider text in canonical state.

---

# 32. Prompt Safety

Implement bounded structured prompts for the approved model-assisted stages.

Student text is untrusted data.

Prompt injection must not alter:

- schema;
- requirement inventory;
- applicability rules;
- target set;
- Phase 2J continuity;
- result quarantine;
- model-call budget;
- posture synthesis.

Include injection tests in:

- English;
- Arabic;
- mixed.

No free-form model explanation should be canonical evidence.

---

# 33. LLM Contracts

Add only the structured-output contracts required by the approved model tasks.

Likely tasks include:

- experiment segmentation/type;
- protocol extraction;
- conditional applicability;
- target linkage / semantic alignment.

Use the architecture's exact task decomposition if documented differently.

Every contract must:

- reference bound IDs only;
- reject unknown IDs;
- reject cross-run IDs;
- use closed enums;
- avoid arbitrary canonical prose;
- validate exact excerpt references;
- tolerate provider failure by failing closed.

Do not reuse a Phase 3A DTO merely because it looks similar if semantics differ.

Do reuse infrastructure patterns.

---

# 34. Settings / Registry

Add the minimal Phase 3B settings needed for:

- model-call bound;
- max experiments;
- graph registration;
- checkpoint behavior.

Default expected architecture values:

```text
max_experiments = 12
max_model_calls = 40
```

Use actual architecture constants if already defined.

Do not expose settings that have no runtime use.

Register graph/nodes consistently with existing research phases.

---

# 35. Checkpoint / Replay / Determinism

Production implementation must pass:

- checkpoint serialization;
- resume equivalence;
- replay equivalence;
- stable IDs;
- canonical ordering;
- upstream fingerprint verification;
- no model-list-order dependence.

Add tests that reorder model-provided lists and confirm canonical output is unchanged.

If provider outputs semantically identical entries in different order:

```text
canonical Phase 3B state must be identical
```

---

# 36. External Search / Network

Phase 3B must not call external research connectors.

Enforce:

```text
external_search_attempts = 0
network_attempts = 0
```

Do not add web/patent/product/literature connectors.

---

# 37. Production Tests Required

Implement comprehensive targeted production tests.

At minimum include dedicated tests for:

## Graph / pipeline
- happy path;
- no experiments;
- multiple experiments;
- max experiment bound;
- model-call bound;
- provider missing;
- partial failure;
- checkpoint/resume.

## Binding
- run mismatch;
- artifact hash mismatch;
- unknown claim;
- unknown hypothesis;
- cross-run reference;
- upstream fingerprint drift.

## Identity
- stable ID;
- offset shift stability;
- repeated text;
- multiple defining excerpts;
- revision identity.

## Applicability
- required cannot be lowered;
- missing field not NOT_APPLICABLE;
- conditional resolution;
- UNKNOWN type cap.

## Evidence
- exact excerpt;
- repeated excerpt;
- overlap with result quarantine;
- invalid offsets;
- wrong artifact.

## Result leakage
- outcome-value mutation invariance;
- result table;
- conclusion text;
- result-overlap rejection;
- no result parameter in synthesis.

## Execution
- past-tense execution statement;
- execution described;
- execution_verified always false;
- independently_reproduced false;
- leakage_prevented_in_practice false.

## Baseline
- missing baseline for improvement target;
- baseline name only;
- relevant baseline;
- comparator property assessment;
- same metric deterministic property only;
- no global fairness.

## Measurement
- method + metric;
- metric only;
- wrong target;
- wrong experiment;
- success criterion;
- post-result criterion timing.

## Sample/repetition
- bare N;
- rationale;
- repeated measurement;
- independent replication.

## Statistics
- not applicable;
- triggered inference;
- missing uncertainty where applicable.

## Linkage
- direct;
- partial;
- supporting;
- does not test;
- unresolved;
- same metric wrong target.

## Phase 2J continuity
- full coverage one experiment;
- partial;
- absent;
- unresolved;
- mosaic across experiments must not become COVERED;
- metric mismatch;
- baseline mismatch;
- condition mismatch.

## Hybrid
- deterministic single-track;
- Phase 2J facet;
- model judgment;
- unresolved;
- no double count;
- no averaging.

## Safety
- English injection;
- Arabic injection;
- mixed injection;
- unknown IDs;
- result-leak attempt.

## Determinism
- model list reordering;
- stable canonical sorting;
- replay;
- checkpoint.

---

# 38. Architecture Mutation Guards

Preserve and extend the six approved architecture non-vacuity checks.

Confirm targeted failures when disabling:

1. exact anchoring;
2. Phase 2J continuity;
3. result-leakage overlap guard;
4. metric-target alignment;
5. deterministic worst-first posture;
6. baseline requirement for improvement claims.

These may remain architecture tests if already sufficient.

Do not duplicate them unnecessarily.

---

# 39. Language Policy

All developer-facing:

- code;
- enum values;
- schema keys;
- prompts;
- comments where practical;
- test names;
- docs;
- CLI output;
- failure messages;

should be English.

Arabic is allowed as student/source/evaluation data and in explicit multilingual safety fixtures.

Register Arabic-bearing files with the repository language-policy mechanism, with a reason.

Do not suppress the language policy globally.

---

# 40. Workflow Hardening

Update workflow-hardening registrations only where justified.

Checkpointed canonical types must be registered correctly.

Non-checkpointed catalog/policy types must have explicit reasons.

Do not add types to exclusion lists simply to make tests pass.

---

# 41. Implementation Documentation

Update `docs/phase3b_experiment_review.md` only to reflect implemented reality.

Do not convert future Gold plans into claims of completed evaluation.

Document:

- production modules;
- graph;
- model calls;
- state ownership;
- result quarantine;
- Phase 2J continuity;
- provider failure behavior;
- known limitations.

Keep ADR-023 unchanged unless a true architecture decision changes.

If ADR must change, STOP and report before modifying it.

---

# 42. No Gold Yet

Do not create:

- `evals/experiment_review/...`;
- Phase 3B Gold generator;
- Phase 3B Gold metrics;
- release gate harness;
- Gold negative-control suite.

Gold is the next milestone after implementation and hardening.

Production tests may use focused fixtures.

Do not inflate production tests into a pseudo-Gold corpus.

---

# 43. Required Test Execution

During implementation:

1. run smallest targeted test file(s);
2. fix;
3. rerun targeted;
4. after implementation stabilizes run all Phase 3B production/architecture tests;
5. run required guards:
   - workflow hardening;
   - language policy;
   - LLM-layer tests if changed;
   - ResearchRun/schema/privacy/checkpoint tests if changed.

Do not run:

- Phase 2J → Phase 1 regressions;
- full repository pytest;
- Phase 3A Gold;
- Phase 3B Gold.

Those belong to later gates.

Capture exact final counts for the implementation checkpoint.

---

# 44. Implementation Trust Audit

Before declaring implementation ready, manually inspect at least these risk paths:

## Audit A — Result mutation

Change only reported result values.

Confirm Phase 3B adequacy/postures do not change.

## Audit B — Cross-target metric

Give an experiment the correct metric for another claim.

Confirm no direct linkage / continuity coverage.

## Audit C — Mosaic continuity

Split metric/baseline/condition across multiple experiments.

Confirm the Phase 2J requirement does not become COVERED.

## Audit D — Bare quantity

Use a large sample number with no adequacy rationale where rationale is material.

Confirm it does not become adequate automatically.

## Audit E — Execution prose

Use strong past-tense execution language.

Confirm execution remains unverified.

## Audit F — Baseline name

Name a baseline but omit comparability details.

Confirm no global fairness conclusion.

## Audit G — Provider omission

Omit one required model judgment.

Confirm unresolved/insufficient propagation.

## Audit H — Hybrid

Give one track a strong experiment and another a major gap.

Confirm no averaging hides the gap.

Report these audits in the checkpoint.

---

# 45. Implementation Milestone Commit

Only after:

- production implementation is complete;
- targeted tests are green;
- architecture tests are green;
- required guards are green;
- no blocking trust defect remains.

Suggested message:

```text
feat(experiments): implement Phase 3B experiment review
```

Before committing verify:

- branch = `feat/phase3b-experiment-review`;
- main still = `9d9e64eb16acedcb85007112f874762336a20d74`;
- architecture commit `7641ef5` is ancestor;
- one worktree;
- no unrelated paths staged;
- `homepage-preview/` excluded;
- no AI attribution.

Do not amend `7641ef5`.

If a blocking defect remains, do not commit.

---

# 46. Required Final Output

Print:

```text
PHASE 3B EXPERIMENT REVIEW — IMPLEMENTATION CHECKPOINT
```

Include:

## Git
- branch;
- main baseline;
- architecture commit;
- implementation commit if created;
- worktree count;
- status;
- `homepage-preview/` status.

## Production implementation
- modules added/changed;
- graph nodes/stages;
- model-assisted tasks;
- deterministic tasks;
- model-call bounds;
- state ownership.

## Trust boundaries
- result quarantine;
- execution boundary;
- Phase 2J continuity;
- baseline/comparator;
- metric-target;
- sample/repetition;
- statistics;
- Hybrid ownership;
- provider failures.

## Tests
For every final test group:
- passed;
- skipped;
- failed;
- errors;
- exit code where available.

## Trust audit
Report Audits A–H and result.

## Defects found
Classify every real issue found as one of:

- `ARCHITECTURE_CONTRACT_DEFECT`
- `PRODUCTION_IMPLEMENTATION_DEFECT`
- `TEST_FIXTURE_DEFECT`
- `TEST_EXPECTATION_DEFECT`
- `WORKFLOW_GUARD_DEFECT`
- `LANGUAGE_POLICY_REGISTRATION`
- `MODEL_JUDGMENT_LIMITATION`

State whether architecture changed.

## Known limitations
At minimum:
- execution authenticity not verified;
- results not evaluated;
- semantic model judgments bounded, not proven;
- no external search;
- no legal/scoring/readiness conclusions.

Then, only if:
- implementation matches the approved architecture;
- targeted production tests pass;
- architecture tests pass;
- guards pass;
- audits A–H pass;
- no blocking defect remains;

print exactly:

```text
PHASE 3B IMPLEMENTATION APPROVED — READY FOR PRE-GOLD HARDENING
```

Then STOP.

Do not generate Gold.
Do not run cross-phase regressions.
Do not run the full repository suite.
Do not merge.
Do not start Result Review.
