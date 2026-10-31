# Phase 3A — Methodology Review

## Status

Architecture specification for Phase 3A.

Baseline:
- Repository: `mawhiba-evaluator`
- Main baseline commit: `9142377`
- Previous phase: Phase 2J — Research / Engineering Gap Assessment
- Phase 2J status: CLOSED & MERGED

Target feature branch:

`feat/phase3a-methodology-review`

---

# 1. Phase Purpose

Phase 3A answers:

> Is the student's documented methodology designed in a defensible way to test the project's claims and gap?

Phase 3A reviews methodology design only.

It does **not** determine:
- whether experiments were actually executed correctly;
- whether reported results are true;
- whether the results support the claims;
- whether the methodology succeeded in practice;
- whether the project is novel or patentable;
- legal prior-art conclusions;
- project scoring;
- readiness;
- Red Team conclusions;
- Jury conclusions.

Those belong to later phases.

The intended boundary is:

```text
Phase 2J
Research / Engineering Gap
        ↓
Phase 3A
Methodology Review
        ↓
Phase 3B
Experiment Review
        ↓
Phase 3C
Result Review
        ↓
Red Team
        ↓
Scoring / Readiness
```

# 2. Core Trust Principles

Preserve these distinctions throughout contracts and implementation:

```text
Documented methodology != methodology actually executed
Planned experiment != completed experiment
Named method != correctly applied method
Named metric != appropriate metric
Sample size present != sample size justified
Baseline present != baseline fair or relevant
Control present != confounding controlled
Dataset split described != leakage prevented
Validation plan present != validation succeeded
Reproducible description != reproduced result
Methodology completeness != scientific validity
No detected flaw != valid methodology
Student methodological claim != verified execution evidence
Methodology review != experiment review
Methodology review != result review
Good result != good methodology
Working prototype != adequate methodology
```

Phase 3A must never allow later-phase evidence to retroactively repair a weak methodology design.

# 3. Execution Discipline — Apply to This Phase

- Keep scope narrowly limited to Phase 3A.
- Start from `main` at commit `9142377`.
- Verify baseline before creating the feature branch.
- Use one normal feature branch in the existing worktree.
- Do not create secondary worktrees.
- Primary Claude session owns implementation.
- Do not delegate the whole phase to agents/subagents.
- Reuse existing contracts, provenance patterns, deterministic synthesis patterns, checkpoint registration, run-binding and immutable upstream references.
- Explore only the minimum repository areas needed.
- Do not perform unrelated refactors.
- Do not introduce speculative architecture.
- Do not weaken tests, validators, assertions, schemas, contracts, provenance, referential integrity, metrics, release gates or safety boundaries.
- Do not mutate Phase 2A–2J semantics merely to support Phase 3A.
- Do not start Phase 3B.
- Do not add project scoring, Red Team, or readiness classification.
- Do not perform new prior-art search.
- Do not infer execution/results from methodology descriptions.
- Run the smallest targeted tests during implementation.
- Do not repeatedly run the full repository suite.
- Do not begin Gold until production Phase 3A implementation is complete and the pre-Gold checkpoint is clean.
- Do not begin cross-phase regressions until Phase 3A Gold/eval is complete.
- Do not merge main until the final release gate is complete.
- If an architectural conflict appears, STOP and report it instead of silently broadening scope.

Required testing sequence:

```text
implementation
→ smallest targeted tests
→ fix targeted failures
→ rerun targeted tests
→ Phase 3A production tests
→ Phase 3A Gold/eval
→ required cross-phase regressions
→ ONE final full repository pytest suite
→ Git verification
→ STOP
```

Context discipline:
- use Opus for architecture only;
- switch to Sonnet after architecture gate;
- use `/context` during long runs;
- at a logical milestone around 70–80% context, checkpoint then `/compact`;
- do not start a large new block above ~80%.

# 4. Baseline and Branch Gate

Before changing files, verify:
- current branch is `main`;
- HEAD is `9142377`;
- working tree is clean;
- no untracked project-owned files;
- one worktree only.

Then create:

`feat/phase3a-methodology-review`

Do not modify main directly.

# 5. Architecture Gate Scope

During the Opus architecture gate, allowed work is limited to:
- inspect authoritative upstream contracts;
- identify canonical methodology inputs;
- design Phase 3A contracts/schemas;
- create focused contract tests;
- add the smallest required run-state field consistent with repository architecture;
- draft/update Phase 3A documentation.

Do **not** build during architecture gate:
- production pipeline;
- graph nodes;
- prompts/provider execution;
- Gold generator;
- eval runner;
- quality metrics;
- release gates;
- negative controls;
- external connectors.

At the end of the architecture gate, STOP.

# 6. Authoritative Input Inventory

Before finalizing contracts, inspect and report the authoritative source for:
1. canonical project type;
2. student-authored methodology/design text;
3. canonical claims;
4. Phase 2I differentiating features and comparison context;
5. Phase 2J gap hypotheses;
6. Phase 2J validation requirements;
7. Phase 2J material conditions;
8. Phase 2J project-gap linkage;
9. baseline/comparator information already represented;
10. AI/ML/data-specific project metadata;
11. software/engineering architecture metadata if already represented.

Do not invent a new authoritative source if a canonical upstream source already exists.

External academic/patent/product/OSS evidence may contextualize methodology but must never prove student execution.

# 7. Project Type Is Inherited

Canonical project type must be inherited, not reclassified by Phase 3A.

Tracks:
- `SCIENTIFIC_RESEARCH`
- `ENGINEERING_PROJECT`
- `HYBRID`

If canonical project type cannot be safely bound:
`INSUFFICIENT_INPUT`

For `HYBRID`:
- evaluate research methodology and engineering methodology separately;
- preserve both track postures;
- do not average them into one opaque score.

# 8. Methodology Requirement Catalog

Create a deterministic typed `MethodologyRequirement` catalog.

Each requirement must have applicability semantics such as:
- `REQUIRED`
- `CONDITIONAL`
- `OPTIONAL`
- `NOT_APPLICABLE`

Do not treat every item as universally required.

A model may assist only with bounded conditional applicability when:
- the requirement already exists in the deterministic catalog;
- relevant source/claim context is bound;
- the model cannot invent new requirement kinds.

Final applicability must be typed and bounded, not unconstrained prose.

# 9. Scientific Research Track

Support methodology requirements such as, when applicable:
- Research Question
- Hypothesis or explicit non-hypothesis design
- Independent Variable
- Dependent Variable
- Controlled Variables
- Operational Definitions
- Population / Sampling Frame
- Sample
- Sample Size Rationale
- Control / Comparison Group
- Randomization
- Blinding
- Experimental / Observational Design
- Data Collection Method
- Measurement Method
- Replication Plan
- Statistical Analysis Plan
- Confounder Handling
- Bias Mitigation
- Internal Validity Threats
- External Validity / Generalizability Boundaries
- Reproducibility Plan
- Ethical / consent requirements when applicable
- Stated limitations

Do not universally require:
- a hypothesis for all valid study designs;
- randomization for every study;
- blinding for every methodology;
- a control group merely because the word "experiment" exists.

# 10. Engineering Methodology Track

Support, when applicable:
- Problem / design objective
- Requirements
- Constraints
- Design rationale
- System boundaries
- Architecture / subsystem plan
- Inputs / outputs
- Sensors / data interfaces
- Algorithms / control strategy
- Baseline / alternative design
- Verification plan
- Validation plan
- Measurement plan
- Acceptance / success criteria
- Failure-mode consideration
- Reliability plan
- Safety plan
- Security/privacy validation when claim-relevant
- Performance benchmark plan
- Scalability validation when claimed
- Iteration strategy
- Configuration / reproducibility plan

Prototype, app, UI, or architecture diagram do not prove methodological adequacy.

# 11. AI / ML Methodology Overlay

When AI/ML is materially part of the project, support conditional requirements for:
- Data Source
- Dataset Scope / Size
- Data Quality
- Labels
- Labeling Method
- Train Split
- Validation Split
- Test Split
- Group-aware split where applicable
- Temporal split where applicable
- Data Leakage prevention
- Duplicate leakage prevention
- Class Imbalance handling
- Preprocessing
- Feature Engineering
- Data Augmentation
- Baseline model
- Model-selection procedure
- Hyperparameter tuning procedure
- Isolation of test set from tuning
- Cross-validation when applicable
- Generalization plan
- External validation plan
- Evaluation metrics
- Error-analysis plan
- Reproducibility / seeds / versions when material

Phase 3A reviews design, not actual execution.

# 12. Software / Systems Overlay

When materially relevant, support:
- architecture rationale;
- backend/data-layer methodology;
- security validation plan;
- privacy validation plan;
- performance benchmark plan;
- scalability plan;
- reliability plan;
- usability methodology only if usability is part of a claim;
- comparison with existing alternatives.

`planned validation != completed validation`

# 13. Methodology Source Binding

Each persisted methodology record should bind to:
- authoritative student source ID;
- source content hash;
- exact excerpt;
- exact validated offsets or deterministic occurrence;
- claim/project/run identity where relevant.

Repeated excerpts must never use first-occurrence guessing.

Do not canonicalize model paraphrases as student-authored methodology.

# 14. Documentation Status

Recommended taxonomy:
- `EXPLICITLY_DOCUMENTED`
- `PARTIALLY_DOCUMENTED`
- `CONFLICTING_DOCUMENTATION`
- `NOT_DOCUMENTED_IN_BOUND_INPUT`
- `NOT_APPLICABLE`
- `INSUFFICIENT_SOURCE_COVERAGE`

`NOT_DOCUMENTED_IN_BOUND_INPUT` must never mean "the student did not do this."

# 15. Methodological Adequacy Is Separate From Documentation

Recommended bounded assessment semantics:
- `ADEQUATELY_SPECIFIED_FOR_REVIEW`
- `PARTIALLY_SPECIFIED`
- `DESIGN_RISK_IDENTIFIED`
- `CONFLICTING_DESIGN`
- `INSUFFICIENT_EVIDENCE_TO_ASSESS`
- `NOT_APPLICABLE`

Avoid authoritative "VALID/PROVEN/CORRECT_METHOD" semantics.

# 16. Claim / Gap → Methodology Coverage

Create an explicit typed relation:
- `DIRECTLY_TESTS_TARGET`
- `PARTIALLY_TESTS_TARGET`
- `RELEVANT_BUT_NOT_TESTING`
- `DOES_NOT_TEST_TARGET`
- `INSUFFICIENT_LINKAGE_EVIDENCE`

The semantic relation is `MODEL_ASSISTED_BOUNDED_JUDGMENT`.

Structural validity of IDs/hashes does not prove semantic correctness.

# 17. Phase 2J Validation Requirement Continuity

Preserve:

```text
Phase 2J validation requirement
!= Phase 3A methodology adequacy
!= Phase 3B successful experiment
!= Phase 3C supported result
```

If Phase 2J requires metric/baseline/material condition and Phase 3A has no bounded plan covering it, the methodology posture must reflect that gap.

# 18. Material Condition Coverage

If Phase 2J established a material condition/context, Phase 3A must determine whether methodology meaningfully addresses it.

Examples:
- population
- environment
- dataset regime
- hardware
- resource constraint
- scale
- geography
- language
- operating regime

Do not synthesize missing condition text.

# 19. Baseline / Comparator Methodology

Separate:

```text
baseline documented
!= baseline appropriate
!= comparison fairly executed
```

Phase 3A handles documentation/relevance at design level.
Phase 3B handles execution fairness.

Do not automatically require the closest prior-art candidate itself as the experimental baseline.

# 20. Metric Appropriateness

`Named metric != appropriate metric`

Methodology should link:

```text
target claim
→ measurable outcome
→ metric
```

Do not convert vague claims into invented metrics.

# 21. Sample-Size Boundary

A numeric sample size is not automatically sufficient.

Phase 3A may assess:
- sample size documented;
- sampling strategy documented;
- sample-size rationale documented;
- power/effect-size rationale present if applicable.

Do not infer adequacy from N alone.

# 22. Control / Confounding Boundary

Separate:
`control mechanism documented`
from:
`confounding eliminated`

Review design-level handling only. Actual success belongs to later phases.

# 23. Methodology Issue Taxonomy

Support typed issues such as:
- `TARGET_NOT_TESTABLE`
- `REQUIRED_COMPONENT_NOT_DOCUMENTED`
- `CLAIM_METHOD_MISMATCH`
- `GAP_METHOD_MISMATCH`
- `BASELINE_NOT_DOCUMENTED`
- `BASELINE_RELEVANCE_UNRESOLVED`
- `METRIC_NOT_DEFINED`
- `METRIC_TARGET_MISMATCH`
- `MATERIAL_CONDITION_NOT_COVERED`
- `SAMPLE_RATIONALE_NOT_DOCUMENTED`
- `CONTROL_STRATEGY_NOT_DOCUMENTED`
- `CONFOUNDER_HANDLING_NOT_DOCUMENTED`
- `DATA_LEAKAGE_RISK`
- `TEST_SET_ISOLATION_NOT_DOCUMENTED`
- `DUPLICATE_OR_GROUP_LEAKAGE_RISK`
- `REPRODUCIBILITY_NOT_DOCUMENTED`
- `CONFLICTING_METHOD_DESCRIPTION`

There is no issue kind for student-described execution: student-described execution != verified execution, and that
boundary is carried by the excerpt's statement mode and the literal `execution_verified=False` (Phase 3B verifies
execution), never by a methodology defect.

Severity, if present, should be deterministic from issue class/criticality, not model prose.

# 24. Methodology Posture

Recommended non-scoring posture:
- `METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT`
- `METHODOLOGY_PARTIALLY_SPECIFIED`
- `METHODOLOGY_HAS_MAJOR_DESIGN_GAPS`
- `METHODOLOGY_CONFLICTING`
- `INSUFFICIENT_INPUT`

The model must never directly choose final posture.

# 25. Track-Specific Synthesis

For `SCIENTIFIC_RESEARCH`, derive research posture.
For `ENGINEERING_PROJECT`, derive engineering posture.
For `HYBRID`, preserve both separately.

Do not average them.

# 26. No Results Leakage

Successful outcomes must not repair weak methodology.

Examples:
- high accuracy != proof of test-set isolation
- working prototype != proof of adequate validation design

# 27. Student Claims About Execution

Student text describing execution may be persisted only as student-documented methodology/execution description.

It must not become verified execution fact.

Phase 3B owns execution verification.

# 28. Prompt Injection

Instruction-like source text is inert data.

Reject model behavior that fabricates IDs/excerpts, crosses runs/claims, breaks schemas, introduces forbidden score/verdict fields, or leaks hidden prompts.

Free model prose is noncanonical.

# 29. No New Search

Phase 3A initiates no academic/patent/product/OSS search.

# 30. Chronology / Legal / Novelty Separation

Phase 3A must not emit legal novelty, patentability, infringement, FTO, or project score.

# 31. Deterministic Synthesis

Requirement status, component assessment, missing requirements, issue inventory, track posture, project posture and canonical bounded summary must be computed deterministically from validated typed records.

# 32. Immutability / Run Binding / Replay

Preserve deterministic IDs, stable hashes, run binding, replay safety, resume equivalence, upstream immutability, claim/source mutation detection and input-order invariance where applicable.

# 33. Checkpoint Safety

Any Phase 3A type reachable from graph state must be serializer-safe.

Use existing checkpoint-registration guards.

# 34. Architecture-Level Contract Tests

During the Opus architecture gate include tests for at least:

A. planned methodology cannot become verified execution;
B. NOT_DOCUMENTED_IN_BOUND_INPUT cannot become "student did not do it";
C. applicability differs by project type;
D. conditional research requirement is not universally required;
E. HYBRID preserves separate tracks;
F. semantically unrelated methodology cannot produce strong coverage;
G. uncovered Phase 2J material condition prevents strong coverage;
H. vague "better" claim cannot receive invented metric;
I. numeric sample size alone cannot establish adequacy;
J. baseline existence alone cannot establish relevance;
K. missing AI/ML test-set isolation remains a risk even if result is successful;
L. result fields cannot upgrade posture;
M. repeated excerpt ambiguity is rejected;
N. model prose cannot override deterministic posture;
O. prompt-like source text remains inert;
P. hidden/system prompt text cannot persist;
Q. cross-run/cross-claim linkage rejected;
R. upstream mutation invalidates run;
S. replay idempotent;
T. no external-search connector reachable/imported.

# 35. Gold / Eval Requirements — Later Milestone

Do not build Gold during architecture.

Later minimums:
- >=360 cases
- >=120 English
- >=120 Arabic
- >=120 mixed
- >=160 semantic/control categories

# 36. Quality Metrics — Later Gold

Plan for at least 36 distinct quality metrics.
Do not count release gates as quality metrics.

# 37. Release Gates — Later Gold

Plan for at least 100 release-blocking gates.

Every required gate must eventually have a real non-zero aggregate denominator, zero violations, and no synthetic floor.

# 38. Negative Controls — Later Gold

Plan for:
- >=180 attempts
- >=45 distinct mechanisms

# 39. Later Regression Plan

After Phase 3A Gold/eval:

```text
Phase 2J
→ Phase 2I
→ Phase 2H
→ Phase 2G
→ Phase 2F
→ Phase 2E
→ Phase 2D
→ Phase 2C
→ Phase 2B
→ Phase 2A
→ Phase 1
→ ONE final full repository pytest suite
```

# 40. Architecture Decisions Claude Must Report

Report:
1. Phase 3A state location;
2. authoritative methodology source inventory;
3. project-type inheritance;
4. requirement catalog;
5. applicability semantics;
6. documentation taxonomy;
7. methodology-assessment taxonomy;
8. scientific track;
9. engineering track;
10. hybrid synthesis;
11. AI/ML overlay;
12. software/system overlay;
13. claim-method linkage;
14. Phase 2J gap-method linkage;
15. validation-requirement continuity;
16. material-condition coverage;
17. baseline/comparator semantics;
18. metric-alignment semantics;
19. sample-size boundary;
20. control/confounding semantics;
21. student execution-claim boundary;
22. result-leakage boundary;
23. prompt-injection/model-prose boundary;
24. deterministic posture;
25. replay/checkpoint/immutability plan;
26. planned Gold/eval structure;
27. conflicts.

# 41. Architecture Gate Validation

Run only:
- Phase 3A contract tests;
- test_language_policy.py;
- test_workflow_hardening.py;
- directly affected prior-phase contract guards, especially Phase 2J.

Do not run full suite, regressions, or Gold.

# 42. Architecture Checkpoint Output

Print:

```text
PHASE 3A ARCHITECTURE CHECKPOINT
```

Then, only if no blocking conflicts:

```text
PHASE 3A ARCHITECTURE COMPLETE — SAFE TO CONTINUE WITH SONNET
```

Then STOP.

# 43. Architecture Gate Definition of Done

Architecture gate is complete only when:
- baseline verified;
- feature branch created;
- methodology state location defined;
- authoritative inputs identified;
- research/engineering/hybrid semantics explicit;
- applicability explicit;
- documentation separated from adequacy;
- methodology separated from execution/results;
- claim/gap-method linkage explicit;
- Phase 2J condition/validation continuity explicit;
- baseline/metric/sample/confounding boundaries explicit;
- model judgments typed and bounded;
- deterministic posture rules defined;
- run-binding/replay/checkpoint strategy explicit;
- architecture tests pass;
- no blocking conflicts remain;
- no production pipeline/graph/Gold work started.
