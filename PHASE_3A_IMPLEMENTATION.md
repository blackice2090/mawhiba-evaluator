# Phase 3A — Production Implementation

## Status

Production implementation specification for Phase 3A after the approved architecture milestone.

Repository:
- `mawhiba-evaluator`

Current branch:
- `feat/phase3a-methodology-review`

Baseline main:
- `9142377`

Approved Phase 3A architecture commit:
- `2f1693a13101088dc8e567e58f81eaf5e3b34f88`
- `feat(methodology): establish Phase 3A architecture contracts`

Architecture status:
- Phase 3A Architecture Gate: APPROVED
- Phase 3A Architecture Hardening: APPROVED
- Architecture tests: 589 passed, 14 skipped, 0 failed
- Working tree after architecture commit: clean
- One worktree
- Main unchanged

This document governs production implementation only.

Do **not** build Phase 3A Gold/eval in this milestone.

---

# 1. Goal

Implement the Phase 3A production pipeline that reviews the student's documented methodology at the design level while preserving all approved architecture boundaries.

The production implementation must answer:

> Is the student's documented methodology designed in a defensible way to test the project's claims and Phase 2J gap?

It must not answer:

- whether the experiment was actually executed correctly;
- whether reported results are true;
- whether reported metrics were achieved;
- whether controls actually eliminated confounding;
- whether the test set was truly independent in execution;
- whether a comparison was fairly executed;
- whether the project is scientifically valid overall;
- whether the project is novel/patentable;
- project scoring;
- readiness;
- Red Team;
- Jury outcomes.

Those remain later-phase responsibilities.

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS PHASE

This section is mandatory.

## Scope

- Stay on `feat/phase3a-methodology-review`.
- Start from architecture commit `2f1693a`.
- Keep the implementation narrowly limited to Phase 3A production functionality.
- Reuse the approved contracts in `src/schemas/methodology_review.py`.
- Reuse existing Phase 2J/2I provenance, run-binding, deterministic-ID, serializer, graph and provider patterns where appropriate.
- Do not revisit architecture unless implementation reveals a genuine contradiction.
- Do not silently redesign approved contracts to make implementation easier.
- Do not mutate Phase 2A–2J semantics.
- Do not start Phase 3B.
- Do not add scoring, Red Team, readiness, reports, jury simulation, or legal novelty conclusions.
- Do not add new external search.

## Change discipline

- Make the smallest justified production changes.
- No unrelated refactors.
- No speculative abstractions.
- No weakening tests, validators, assertions, contracts, schemas, provenance checks, fingerprinting, release boundaries, or safety gates.
- Never hard-code case-specific semantic answers.
- Never convert student descriptions into verified execution facts.
- Never use later result success to repair methodology weaknesses.

## Test discipline

Use this order:

```text
implementation
→ smallest targeted tests
→ fix targeted failures
→ rerun targeted tests
→ Phase 3A production tests
→ Phase 3A architecture/guard tests
→ directly affected prior-phase contract tests
→ PRE-GOLD CHECKPOINT
→ STOP
```

Do not run:

- Gold/eval;
- cross-phase regressions;
- full repository suite;
- merge.

Only report tests actually executed.

## Context discipline

- Use Sonnet for production implementation.
- Use `/context` during long work.
- Around 70–80% context, finish a logical milestone and `/compact`.
- Do not begin a large new implementation block above ~80%.
- Do not spawn replacement agents for branch/worktree/tooling failures.
- Primary session owns the implementation.

---

# 3. Pre-Implementation Verification

Before changing code, verify:

- current branch is `feat/phase3a-methodology-review`;
- HEAD is architecture commit `2f1693a13101088dc8e567e58f81eaf5e3b34f88`;
- working tree is clean;
- one worktree only;
- main remains at `9142377`;
- no unexpected untracked files.

If any item differs, STOP and report.

---

# 4. Approved Architecture Is Authoritative

Read before coding:

- `PHASE_3A_METHODOLOGY_REVIEW.md`
- `PHASE_3A_ARCHITECTURE_HARDENING.md`
- `docs/phase3a_methodology_review.md`
- `docs/adr/ADR-022-methodology-review-is-a-design-level-posture.md`
- `src/schemas/methodology_review.py`
- Phase 2J production pipeline and graph patterns
- Phase 2I production pipeline patterns where directly relevant

Do not reinterpret the approved architecture from scratch.

The approved contracts and hardening decisions win.

---

# 5. Approved Trust Boundaries

Preserve exactly:

```text
Documented methodology != methodology actually executed
Planned experiment != completed experiment
Named method != correctly applied method
Named metric != appropriate metric
Sample size present != sample size justified
Baseline documented != baseline relevant
Baseline relevant != comparison fairly executed
Control documented != confounding eliminated
Dataset split described != leakage prevented in execution
Validation plan != validation success
Student execution description != verified execution fact
Good result != good methodology
Working prototype != adequate methodology
```

The implementation must enforce these distinctions structurally, not merely through prompt wording.

---

# 6. Production Pipeline Responsibilities

Implement a bounded Phase 3A pipeline with clear stages.

The exact file/module names may follow repository conventions, but the conceptual stages must be explicit and independently testable.

Recommended stage structure:

1. `bind_inputs`
2. `build_requirement_inventory`
3. `resolve_overlay_materiality_and_ownership`
4. `extract_methodology_evidence`
5. `resolve_conditional_applicability`
6. `assess_methodology_components`
7. `link_methodology_to_targets`
8. `evaluate_validation_continuity`
9. `synthesize_issues_and_postures`
10. `finalize_and_verify`

If existing graph conventions strongly favor a different decomposition, adapt minimally while preserving the same trust boundaries.

Every stage must be idempotent.

---

# 7. Input Binding

Bind only authoritative inputs approved by architecture.

Required bindings include:

- `research_id`
- canonical project type from Phase 2J and identity equality check
- canonical claims with text hashes
- Phase 2I context where permitted
- Phase 2J:
  - hypotheses
  - validation requirements
  - condition IDs
  - linkage
  - canonical project type
- student submission artifact:
  - artifact/source ID
  - exact text
  - content hash
- permitted intake metadata:
  - domain
  - technical block
  - canonical identity fields used by applicability rules

Explicitly do not bind experiment/result fields as methodology evidence.

At bind time compute deterministic fingerprints over all authoritative upstream inputs that Phase 3A relies on.

At finalize, recompute and compare.

Mutation:
- must invalidate the run;
- must not silently continue;
- must not produce strong methodology postures.

---

# 8. Submission Provenance

The student methodology source is the verbatim submission text.

Production must verify:

- artifact/source identity;
- content hash;
- exact excerpt;
- exact offsets;
- deterministic occurrence.

Repeated excerpt handling:

- never first-match guess;
- if the same text occurs more than once, the model/record must identify a verifiable occurrence or exact offsets;
- unresolved ambiguity must be rejected or marked unresolved according to the approved contract.

Model paraphrase must never replace canonical student text.

---

# 9. Deterministic Requirement Inventory

Build the requirement inventory from the approved closed catalog.

The model must not invent requirement kinds.

Inventory generation must be deterministic from:

- project type;
- approved catalog;
- overlay state;
- bounded project facts.

Preserve applicability states:

- REQUIRED
- CONDITIONAL
- OPTIONAL
- NOT_APPLICABLE

Required items cannot be downgraded by model output.

Conditional items remain conditional unless bounded evidence permits resolution.

---

# 10. Overlay Materiality and Ownership

Implement the hardened ownership rules.

## AI/ML

Domain words, "AI", "ML", or presence of a model are signals only.

They do not prove materiality.

Materiality must bind to:

- target claim(s) and/or Phase 2J hypothesis/hypotheses;
- exact student excerpts;
- approved bounded judgment.

Possible semantics must follow the architecture contract.

### Scientific Research
A materially applicable AI/ML overlay can be owned by the research track.

### Engineering Project
A materially applicable AI/ML overlay must be able to be owned by the engineering track.

An engineering-only AI project must not escape AI/ML methodology requirements.

### Hybrid
Ownership must follow the target served.

Do not use "research track if present" as a shortcut.

Requirements:
- count once in the owner track;
- may support coverage in another served track only if the approved contract allows it;
- may not be double-counted;
- may not be cited by an unserved track.

Unresolved ownership/materiality:
- stays bounded/unresolved;
- cannot support a `WELL_SPECIFIED` posture.

## Software/Systems

Apply the same materiality discipline.

If software/systems methodology is materially relevant in a research-only project, ownership must still be representable according to the hardened architecture.

Do not force the overlay merely because software is used as a tool.

---

# 11. Methodology Evidence Extraction

Use model assistance only for bounded extraction/classification tasks.

The model may propose:

- requirement kind from the closed catalog;
- exact source excerpt with offsets/occurrence;
- documentation relationship;
- student-described execution wording;
- bounded classification fields explicitly permitted by the DTO.

The model may not provide:

- final methodology posture;
- project score;
- experiment verdict;
- result verdict;
- legal novelty;
- patentability;
- free-form canonical methodology summary;
- fabricated metric;
- fabricated baseline;
- fabricated condition;
- fabricated claim;
- fabricated Phase 2J requirement.

Every accepted excerpt must pass deterministic source verification.

Unverified model extraction must never enter canonical run state.

---

# 12. Model-Facing DTO Boundary

Create transient model-facing DTOs with `extra=forbid`.

They must not contain final deterministic outputs.

Model DTOs should use:
- IDs
- enum choices
- exact excerpts
- exact offsets
- bounded relations

Avoid unconstrained persisted prose.

If diagnostic/model prose is accepted at all:
- it is noncanonical;
- it must not affect deterministic output;
- it must not be checkpointed unless explicitly justified.

Provider refusal/error text must not be persisted verbatim.

Persist only safe structured error classification and/or digest/length where repository patterns require it.

Hidden prompt leakage must be redacted before persistence.

---

# 13. Conditional Applicability Resolution

Conditional applicability may use bounded model judgment only when deterministic triggers do not settle it.

The model can only resolve an existing conditional catalog item.

It cannot:

- invent a new requirement;
- suppress REQUIRED;
- promote OPTIONAL arbitrarily;
- attach a requirement to a nonexistent track.

Persist:
- requirement ID/kind;
- bounded applicability;
- basis;
- source/target references.

Final applicability is code-controlled.

---

# 14. Documentation Status

Compute/persist documentation status separately from adequacy.

Approved documentation semantics include:

- explicitly documented
- partially documented
- conflicting documentation
- not documented in bound input
- not applicable
- insufficient source coverage

Never convert:

`NOT_DOCUMENTED_IN_BOUND_INPUT`

into:

`student did not do it`

User-facing/canonical output must remain bounded to source coverage.

---

# 15. Methodology Assessment

Assess component design separately from documentation.

A documented component may still be:
- partial;
- conflicting;
- risky;
- insufficient to assess.

Do not issue authoritative "valid/invalid/scientifically proven" labels.

The final component assessment must be validated against the approved documentation-to-assessment compatibility table.

---

# 16. Student Execution Description Boundary

If a student says:

- "we randomized";
- "we tested on an independent set";
- "we repeated five times";

Phase 3A may capture that exact excerpt as a student-described execution statement.

It must keep:

`execution_verified = false`

or equivalent approved invariant.

No Phase 3A model or deterministic rule may promote it to verified execution.

Phase 3B owns execution verification.

---

# 17. Claim → Methodology Linkage

Implement bounded semantic linkage using the approved relation taxonomy.

Structural validation must verify:

- run identity;
- claim identity;
- claim hash;
- methodology requirement identity;
- track;
- source provenance.

Semantic relation remains:

`MODEL_ASSISTED_BOUNDED_JUDGMENT`

Strong claim coverage must require actual target-testing methodology according to the contract.

Valid IDs alone are never enough.

---

# 18. Phase 2J Gap → Methodology Linkage

Implement exact continuity with the bound Phase 2J hypothesis and validation requirement.

For a Phase 2J gap target:

- if a validation requirement exists, its metric is mandatory;
- baseline is mandatory only when the Phase 2J requirement contains one;
- material conditions are exactly the requirement's bound condition IDs;
- if no validation requirement exists, Phase 3A must not invent metric/baseline/condition prerequisites.

Strong coverage requires semantic methodology coverage, not merely the Phase 2J requirement ID.

---

# 19. Metric Plan

No free-text invented metric.

A methodology metric must be anchored to:

- exact student text; or
- the bound Phase 2J validation requirement according to approved semantics.

For Phase 2J gap targets:
- metric plan must align with the actual validation requirement.

For claim targets:
- metric plan must align with the claim's measurable target.

Vague claims such as:
- better
- smarter
- more efficient

must not receive invented metrics.

If a measurable interpretation is not bounded:
- issue the appropriate methodology gap;
- do not infer one.

---

# 20. Baseline / Comparator Plan

Preserve all four layers:

1. baseline documented;
2. baseline relevance;
3. student rationale documented;
4. fair comparison execution.

Only layers 1–3 belong to Phase 3A.

Layer 4 remains false/unassessed.

## Baseline documented

Requires exact student-source evidence.

## Baseline relevance

Bounded semantic judgment.

Permitted context only as approved:
- target claim text;
- Phase 2J baseline;
- Phase 2J existing capability;
- exact student rationale excerpt.

The baseline name alone is insufficient evidence of relevance.

## Student rationale

Optional.

Do not fabricate it.

The same exact excerpt may legitimately support baseline identity and rationale when it contains both.

## Comparison fairness

Always unverified in Phase 3A.

---

# 21. Material Condition Coverage

For every Phase 2J condition required by the bound validation requirement:

- reference the condition by canonical ID;
- determine whether documented methodology addresses it;
- preserve bounded linkage.

Do not invent condition text.

If a required condition is not addressed:
- strong target coverage is blocked;
- a well-specified posture is blocked according to approved deterministic rules.

---

# 22. Sample Size / Sampling

Keep separate:

- sample;
- sample size;
- sampling strategy;
- sample-size rationale;
- power/effect-size rationale when applicable.

A number alone such as:

`N = 500`

must never establish sample-size adequacy.

Do not infer required N.

Do not invent power assumptions.

If domain assumptions needed for adequacy are unavailable:
- keep the conclusion unresolved/insufficient.

---

# 23. Controls / Confounding

Review design-level handling only.

Possible relevant components:
- controlled variables;
- control/comparator groups;
- confounders;
- randomization;
- blinding;
- leakage controls.

Never set an invariant equivalent to:

`confounding_eliminated = true`

in Phase 3A.

Actual success belongs to Phase 3B.

---

# 24. AI / ML Methodology Risks

Where the AI/ML overlay is materially applicable, support design-level risk detection for:

- data source not documented;
- labels/labeling not documented;
- train/validation/test split not documented;
- test set isolation not documented;
- tuning/test contamination risk;
- group leakage risk;
- duplicate leakage risk;
- temporal leakage risk where relevant;
- class imbalance handling;
- preprocessing;
- feature engineering;
- augmentation;
- baseline model;
- hyperparameter procedure;
- cross-validation where applicable;
- generalization plan;
- external validation plan;
- error analysis;
- reproducibility/seeds/versions.

These are methodology-design findings only.

Do not assert leakage actually occurred unless Phase 3A contract explicitly represents a documented design contradiction/risk.

Do not assert leakage was actually prevented.

---

# 25. Software / Systems Methodology Risks

Where material:

- architecture rationale;
- backend/data-layer methodology;
- security validation plan;
- privacy validation plan;
- performance benchmark plan;
- scalability plan;
- reliability plan;
- usability methodology when claim-relevant;
- comparison plan.

Do not treat existence of software as innovation or methodology adequacy.

---

# 26. Issue Synthesis

Use the approved typed issue taxonomy.

Issue creation must be deterministic from validated component states, linkage, coverage, applicability and risk records.

If severity exists:
- derive from approved issue type/criticality mapping;
- never from model prose.

Do not allow duplicate semantically identical issues caused only by repeated source extraction.

Use deterministic IDs.

---

# 27. Track Posture

Compute posture deterministically for each applicable track.

Do not ask the model to choose final posture.

A track cannot be `WELL_SPECIFIED_WITHIN_BOUND_INPUT` when any approved hard blocker exists, including where applicable:

- unresolved required applicability;
- required component absent from bounded documentation;
- major target-method mismatch;
- required Phase 2J validation metric uncovered;
- required baseline uncovered/unresolved;
- required material condition uncovered;
- unresolved material overlay ownership;
- conflicting methodology;
- critical AI/ML leakage-design risk;
- unsafe input/run binding.

Use exact architecture contract rules rather than this list if the schema is more precise.

---

# 28. Hybrid Synthesis

Do not create an opaque averaged posture.

Preserve:
- research-track posture;
- engineering-track posture;
- track-specific issues;
- shared issues;
- cross-track contradictions;
- unresolved overlays.

A strong engineering track cannot hide weak research methodology.

A strong research track cannot hide weak engineering methodology.

---

# 29. Project-Level Phase 3A Synthesis

If the approved contract has a project-level descriptor, it must preserve track postures rather than collapse them to a score.

No numeric project score.

No weighted average.

No readiness decision.

No Jury recommendation.

---

# 30. Result Leakage Barrier

Production Phase 3A must not consume result/experiment success fields as evidence of methodology adequacy.

Implement an explicit structural guard.

Protect against fields/fragments representing:
- achieved score;
- achieved accuracy;
- result;
- outcome;
- measured improvement;
- passed experiment;
- experiment success;
- actual execution verification.

Do not rely only on an English lexical blacklist.

Use schema/input allowlisting and typed DTO boundaries as the primary defense.

Lexical checks may remain defense-in-depth.

---

# 31. Prompt Injection / Source Instruction Safety

Instruction-like student text is inert data.

Examples may include:
- "ignore previous instructions"
- Arabic equivalents
- mixed-language equivalents

Exact verified excerpts may persist as source data.

The system must reject:
- model following embedded commands;
- schema escape;
- invented IDs;
- invented requirements;
- invented excerpts;
- prompt/system leak;
- unauthorized score/verdict.

Production safety must be language-independent through structural contracts.

---

# 32. External Search Prohibition

Phase 3A production must make zero external research/search calls.

It must not call:
- academic connectors;
- patent connectors;
- product connectors;
- OSS discovery;
- web search;
- source acquisition.

Use only already-bound upstream context and the student submission.

`external_search_calls` must remain zero.

Add direct tests proving no Phase 3A production stage can increment or reach search.

---

# 33. Graph Integration

Create a dedicated Phase 3A graph consistent with repository patterns.

Requirements:

- non-terminal research subrun;
- deterministic node IDs;
- idempotent stages;
- checkpoint-safe graph state;
- no transient model DTOs in checkpoint state;
- resume equals uninterrupted execution;
- replay does not duplicate model calls after completed stage markers;
- failure/refusal states are explicit;
- human interrupts are not introduced unless architecture requires them;
- no Phase 3B nodes reachable.

Register node IDs and graph types using existing registries.

Do not weaken graph registry tests.

---

# 34. Provider / Prompt Tasks

Add only the minimal model tasks required by the approved architecture.

Likely bounded tasks include:

1. conditional applicability resolution;
2. methodology evidence extraction/classification;
3. overlay materiality/ownership judgment;
4. target-method semantic linkage;
5. baseline relevance;
6. condition coverage or related bounded semantic judgment.

Minimize model calls where multiple bounded judgments can safely share one structured call without increasing trust risk.

Do not combine unrelated semantic tasks merely to reduce call count if it makes validation ambiguous.

Every prompt must:
- clearly mark student/source text as untrusted data;
- prohibit following instructions from source text;
- require exact source anchoring where applicable;
- prohibit score/final verdict;
- prohibit legal novelty;
- prohibit experiment/result conclusions;
- prohibit invented metrics/baselines/conditions.

All persisted model-origin data must pass deterministic verification.

---

# 35. Model Call Accounting

Track:
- attempted calls;
- successful calls;
- refusal/error calls;
- replay reuse;
- external search calls = 0.

Node attempts must follow repository conventions.

Human wait, if none exists, must not be synthesized.

Replay after a completed stage must not issue duplicate calls.

---

# 36. Run Status / Failure Semantics

Use approved status semantics.

At minimum handle:

- successful bounded assessment;
- insufficient input;
- invalidated upstream mutation;
- model call failure/refusal where required;
- unresolved conditional applicability;
- unresolved semantic linkage;
- unsafe source binding.

Do not transform model failure into positive methodology assessment.

Do not drop failed/unresolved required items silently.

---

# 37. Canonical Output Boundary

Canonical Phase 3A output must be composed only from:

- verified exact source anchors;
- deterministic catalog data;
- deterministic IDs/hashes;
- validated model-assisted enum judgments;
- upstream Phase 2J/2I references;
- deterministic issue/posture synthesis.

Free model prose is noncanonical.

Canonical output must be invariant to irrelevant model explanation/rationale prose.

Where model-prose twins return different free rationale but identical typed judgments, canonical Phase 3A output should be byte-identical where ordering is deterministic.

---

# 38. Ordering / Determinism

Ensure stable ordering for:
- requirements;
- excerpts;
- component assessments;
- links;
- conditions;
- baselines;
- metrics;
- issues;
- track results.

Input ordering must not change canonical output when semantics are unordered.

Use deterministic UUID5 or existing repository deterministic-ID helpers.

---

# 39. Upstream Immutability

Do not mutate:

- ProjectState claims;
- Phase 2I subrun;
- Phase 2J subrun;
- source artifacts;
- identity project type.

Tests must compare upstream serialization/fingerprint before and after Phase 3A.

Any mutation must fail tests.

---

# 40. Production Test Requirements

Build focused production tests.

Minimum production families:

## Input binding
- correct research/run binding;
- wrong research rejected;
- claim hash mismatch rejected;
- submission hash mismatch rejected;
- project type mismatch rejected;
- upstream mutation detected.

## Source anchoring
- exact span accepted;
- fabricated span rejected;
- wrong offset rejected;
- repeated excerpt ambiguity rejected;
- deterministic occurrence accepted;
- instruction-like source text accepted as inert data.

## Requirement inventory
- catalog closed;
- no invented kinds;
- project-type-specific applicability;
- conditional unresolved path;
- REQUIRED cannot be downgraded.

## Overlay ownership
- engineering-only AI/ML;
- research AI/ML;
- hybrid owner research;
- hybrid owner engineering;
- hybrid no double count;
- implementation-only overlay;
- unresolved ownership blocks well-specified posture;
- software/systems material research-only case.

## Documentation / assessment
- documented vs adequate separated;
- not documented remains bounded;
- conflicting documentation;
- insufficient source coverage.

## Target linkage
- valid semantic direct coverage;
- partial coverage;
- unrelated but structurally valid link;
- insufficient semantic linkage;
- wrong claim rejected;
- wrong gap rejected.

## Phase 2J continuity
- metric requirement enforced when validation requirement exists;
- optional baseline only when present;
- empty condition list accepted;
- conditions exact;
- no validation requirement → no invented validation dimension.

## Baseline
- documented only;
- relevant with permitted context;
- baseline name alone insufficient;
- optional rationale;
- same excerpt baseline+rationale;
- fair execution always unverified.

## Metrics
- student metric exact anchor;
- Phase 2J metric reference;
- mismatched metric;
- vague improvement no invented metric.

## Sample / controls
- numeric sample alone insufficient;
- sample rationale accepted when real;
- confounding elimination never inferred.

## AI/ML risks
- test isolation missing remains a design risk;
- successful result cannot repair it;
- leakage-risk design fields.

## Result leakage
- result fields cannot enter methodology evidence;
- result success cannot upgrade posture;
- prototype success cannot upgrade posture.

## Prompt/model safety
- English injection;
- Arabic injection;
- mixed injection;
- hidden prompt leak redacted;
- provider refusal/error not persisted verbatim;
- free prose cannot change canonical output.

## Replay/checkpoint
- serializer round-trip;
- replay idempotent;
- resume equals uninterrupted;
- no duplicate model calls;
- stable IDs;
- input-order invariance.

## Search
- zero external search;
- no search connector reachable.

---

# 41. Language Policy

Developer-facing:
- code;
- identifiers;
- schemas;
- enums;
- prompts;
- docs;
- CLI output;
- error messages;

must follow the repository's English developer-language policy.

Arabic/mixed student/source/eval strings belong in approved data/test fixture registries according to repository policy.

Do not add arbitrary Arabic production literals.

Run language-policy guard after relevant prompt/docs/test changes.

---

# 42. Documentation

Update:

- `docs/phase3a_methodology_review.md`
- ADR only if implementation materially clarifies an approved decision; do not create unnecessary ADRs.
- `CLAUDE.md` only if there is a durable repo-level command/convention/gotcha that belongs there.

Do not bloat `CLAUDE.md` with milestone narration.

Do not modify root architecture specs except to correct an actual approved architecture inconsistency.

---

# 43. Graphify / Generated Architecture Artifacts

If the repository's established phase workflow requires Graphify or equivalent generated architecture output after adding graph nodes, update it once after the graph stabilizes.

Do not repeatedly regenerate it during each small implementation edit.

Do not commit caches or incidental generated files that are not project-owned.

---

# 44. Targeted Test Strategy

During implementation:

1. run the smallest test file for the component being implemented;
2. fix;
3. rerun that file;
4. proceed to the next component.

At production completion, run:

- all `tests/test_phase3a_*.py`;
- `test_language_policy.py`;
- `test_workflow_hardening.py`;
- Phase 2J contracts;
- Phase 2I contracts only if directly touched/referenced in changed production paths;
- any serializer/graph registry tests directly affected.

Do not run Phase 2A–Phase 1 regressions yet.

Do not run the full repo suite.

---

# 45. Pre-Gold Stale/Trust Audit

Before declaring PRE-GOLD ready, perform one narrow audit for:

- any model prose persisted canonically;
- result/experiment leakage;
- source excerpt first-match guessing;
- provider refusal/error text persistence;
- invented metric/baseline/condition;
- incorrect Hybrid overlay ownership;
- overlay double counting;
- missing engineering-only AI/ML coverage;
- Phase 2J validation continuity mismatch;
- baseline relevance inferred from name alone;
- student execution promoted to verified;
- sample N promoted to adequacy;
- confounding marked eliminated;
- external search reachability;
- non-deterministic IDs/order;
- upstream mutation;
- checkpointed transient DTOs;
- Phase 3B conclusion leakage.

If the audit finds a real defect:
- fix minimally;
- rerun only directly affected tests;
- rerun the complete Phase 3A targeted production/guard set once after fixes stabilize.

---

# 46. Production Implementation Checkpoint

At the end, print:

```text
PHASE 3A PRODUCTION IMPLEMENTATION / PRE-GOLD CHECKPOINT
```

Report:

## Git
- branch;
- baseline architecture commit;
- working tree status;
- worktree count;
- changed/new files;
- whether any commit was created.

## Implementation
- pipeline stages;
- graph nodes;
- model tasks/call plan;
- authoritative inputs;
- source verification;
- overlay materiality/ownership;
- requirement inventory/applicability;
- documentation status;
- methodology assessment;
- claim linkage;
- gap linkage;
- Phase 2J validation continuity;
- baseline semantics;
- metric semantics;
- condition coverage;
- sample/control boundaries;
- issue synthesis;
- track posture;
- hybrid synthesis;
- replay/checkpoint/immutability;
- prompt/model-prose safety;
- result-leakage barrier;
- external-search prohibition.

## Tests actually run
For every test group:
- passed;
- skipped;
- failed;
- errors.

## Trust audit
State findings for every item in section 45.

## Upstream impact
Explicitly state:
- whether Phase 2A–2J production semantics changed;
- whether upstream runs are byte-identical before/after;
- whether ProjectState was mutated.

## Known limitations
Report bounded limitations honestly.

Then, only if:
- all required Phase 3A production tests pass;
- guards pass;
- no blocking trust defect remains;
- no Gold/eval work has started;

print exactly:

```text
PHASE 3A PRODUCTION IMPLEMENTATION COMPLETE — READY FOR GOLD
```

Then STOP.

Do not begin Gold automatically.

---

# 47. Commit Discipline

Do not commit automatically unless explicitly instructed after the PRE-GOLD report is reviewed.

At this milestone:
- implementation may remain uncommitted;
- working tree may contain only approved Phase 3A implementation changes.

Do not merge.

---

# 48. Explicit Out-of-Scope Items

Do not implement in this pass:

- Phase 3A Gold dataset;
- Gold generator;
- Gold runner;
- quality metrics;
- release gates;
- negative-control framework;
- cross-phase regressions;
- final full repository suite;
- merge;
- Phase 3B Experiment Review;
- Phase 3C Result Review;
- Red Team;
- scoring;
- readiness;
- jury simulation;
- mentor mode.

---

# 49. Stop Condition

This milestone ends at:

```text
PHASE 3A PRODUCTION IMPLEMENTATION COMPLETE — READY FOR GOLD
```

Do not continue beyond it without explicit instruction.
