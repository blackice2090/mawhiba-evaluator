# PHASE 2F — EVIDENCE-BASED CLAIM SCORING

## EXECUTION DISCIPLINE — APPLY TO THIS PHASE

Treat this as a high-trust scoring architecture + implementation phase.

This is the first phase allowed to derive numeric claim-level evidence indices.

The numbers produced here are NOT:
- probabilities that a claim is true
- final project scores
- Mawhiba/Ibdaa judging scores
- replacements for Phase 2E sufficiency outcomes
- TrustGate results
- claim-status mutations

The goal is to create a transparent, reproducible, policy-versioned claim evidence scorecard that downstream scoring/review phases can inspect without losing the structure established in Phases 2C–2E.

### Core execution rules
- Keep scope strictly limited to Phase 2F.
- Use the primary Claude Code session for architecture, implementation, testing, regression, Git verification, and reporting.
- Do NOT delegate the complete Phase or major Phase areas to Agents/Subagents.
- Do not create additional Git worktrees.
- Use a Subagent only for a narrowly scoped, read-only investigation that genuinely reduces context duplication.
- Inspect only repository surfaces required for Phase 2F.
- Prefer targeted search/navigation over broad recursive exploration.
- Reuse Phase 2C evidence, Phase 2D alignment, Phase 2E sufficiency/component-inventory/independence/source-quality contracts.
- Prefer the smallest correct architectural extension.
- Do not redesign Phase 2C, 2D, or 2E.
- Do not weaken tests, validators, assertions, schemas, referential integrity, metrics, eval denominators, safety gates, or release gates.
- Do not convert failures into skips.
- Do not silently broaden scope.
- If a genuine architecture conflict is found, STOP and report it.
- Do not merge into `main`.
- Do not start Phase 2G or project-level scoring.
- Do not mutate `ClaimRecord`.
- Do not mutate canonical `ProjectState.scores`.
- Do not mutate `TrustGate`, `evaluation_status`, or final project evaluation state.
- Do not present a numeric score as scientific truth.

### Required testing progression

`architecture verification`
→ `implementation`
→ `smallest targeted tests`
→ `fix targeted failures`
→ `rerun targeted tests`
→ `Phase 2F tests/eval`
→ `required cross-phase regression`
→ `one final full-suite release gate`
→ `Git verification`
→ `STOP`

Do not repeatedly run the full repository suite during implementation.

If the final full suite fails:
1. identify the first meaningful root cause
2. apply the smallest justified fix
3. rerun the smallest affected targeted tests
4. rerun affected Phase/eval tests
5. rerun the complete repository suite as the final release gate

Report only tests/evals actually executed.

---

# 1. BASELINE AND GIT

Expected baseline:
- branch: `main`
- Phase 2E + 2E.1 merged
- expected current main HEAD: `a2a272b`
- previous post-merge release gate:
  - 1556 passed
  - 24 skipped
  - 0 failed

Before modifying code:
1. verify current branch
2. verify working tree is clean
3. verify current HEAD
4. confirm Phase 2E `ClaimSufficiencyRun`, component inventory, evidence profiles, independence groups, and sufficiency assessments exist
5. create `feat/phase2f-evidence-based-claim-scoring`

Do not use an additional Git worktree.

If the baseline materially differs, STOP and report the mismatch.

---

# 2. ARCHITECTURE GATE — OPUS MUST RESOLVE BEFORE CODING

Before implementation, inspect only the minimum Phase 2E scoring inputs and produce a concise architecture decision covering:
1. exact semantics of every numeric field
2. claim-level scoring ownership
3. score vector vs scalar boundaries
4. support and contradiction channels
5. when a final scalar is allowed vs withheld
6. how component coverage affects score
7. how independence affects score without source-count gaming
8. how direct vs partial relationships affect score
9. how Phase 2E source-quality/unknown/scope limitations affect reliability without pretending to be truth probabilities
10. Decimal/integer arithmetic and rounding rules
11. score caps/floors, if any
12. monotonicity and anti-gaming invariants
13. versioning/reproducibility
14. immutability boundaries

Prefer a deterministic design.

Proceed directly if compatible with the current architecture.

STOP only for a genuine architectural conflict.

Do not spend context redesigning already-approved Phase 2E semantics.

---

# 3. PHASE OBJECTIVE

Implement a trustworthy claim-level evidence scorecard over Phase 2E.

Architecture:

`Verified Evidence`
→ `Verified Alignment`
→ `Claim Sufficiency Assessment`
→ `Claim Evidence Score Vector`
→ `Optional Final Support Index`
→ `STOP`

Phase 2F answers:

> How strong is the structured evidentiary support and contradiction posture for this claim under a transparent scoring policy?

Phase 2F does NOT answer:
- whether the claim is universally scientifically true
- what score the whole project should receive
- whether the project passes Mawhiba/Ibdaa judging criteria

Preserve:

`Evidence relationship ≠ Sufficiency`

`Sufficiency ≠ Numeric score`

`Numeric score ≠ Probability of truth`

`Claim evidence score ≠ Project merit`

`Claim evidence score ≠ Official judging score`

`Claim evidence score ≠ TrustGate result`

---

# 4. OWNERSHIP

Phase 2F output must remain on the research/evaluation execution layer.

Preferred ownership: `ResearchRun`

Add a dedicated Phase 2F scoring run/state.

Do NOT write Phase 2F values into:
- `ProjectState.scores`
- existing Phase 0 `ScoreRecord`
- `ClaimRecord.status`
- claim confidence
- claim evidence references
- claim counter-evidence references
- Phase 2C evidence
- Phase 2D alignments
- Phase 2E sufficiency assessments
- TrustGate
- evaluation_status

Do not reuse canonical `ScoreRecord` if its semantics are project-evaluation scoring.

Create a separate, explicit Phase 2F claim-evidence score contract.

---

# 5. INPUT CONTRACT

Phase 2F may consume only:
1. existing claims
2. trusted Phase 2E claim sufficiency assessments
3. Phase 2E component inventory
4. Phase 2E evidence weight profiles
5. Phase 2E independence groups
6. Phase 2E source-quality and limitation metadata
7. Phase 2D relationships only through verified Phase 2E references when needed for audit
8. policy/version metadata needed for reproducibility

Phase 2F must not:
- discover new sources
- extract new evidence
- create new alignments
- reclassify Phase 2D relationships
- change Phase 2E sufficiency outcomes
- infer missing publication/retraction facts
- use provider AI takeaways
- use cross-run records
- silently score incomplete/not-ready Phase 2E state

---

# 6. SCORE SEMANTICS — NOT A TRUTH PROBABILITY

Every numeric output must have explicit semantics.

The primary numeric index means:

> a deterministic index of structured evidentiary support for the claim under `CLAIM-EVIDENCE-SCORING-POLICY-V1`

It must NOT mean:
- 80% probability the claim is true
- 80% scientific confidence
- 80/100 project quality
- an official Mawhiba score

Document this in schema docstrings, ADR, report, and developer documentation.

Prefer field names such as `support_index` and `contradiction_index`.

Forbidden/misleading names include `truth_probability` and `confidence_percentage`.

---

# 7. SCORECARD — VECTOR FIRST, SCALAR SECOND

Create a decomposable `ClaimEvidenceScoreCard` or equivalent.

At minimum include:
- scorecard ID
- claim ID
- ResearchRun ID
- Phase 2E assessment ID
- scoring policy version
- score schema version
- input fingerprint/hash
- support channel
- contradiction channel
- component coverage dimension
- independence/corroboration dimension
- relation/directness dimension
- quality/reliability posture
- scope limitations
- unknown dimensions
- score disposition/status
- optional final support index
- deterministic reason codes
- score caps/withholding reasons if applicable

Do not store only one scalar.

The vector is canonical.

Any final scalar is derived and secondary.

---

# 8. SUPPORT AND CONTRADICTION MUST REMAIN SEPARATE

This is release-critical.

Compute separate channels:
- `support_index`
- `contradiction_index`

Both must be bounded and reproducible.

Do not produce a single net score by subtracting contradiction from support.

Forbidden:

`net_score = support - contradiction`

because `90 support / 80 contradiction` must not become indistinguishable from `10 support / 0 contradiction`.

Conflicting evidence must remain visible.

---

# 9. CLAIM-EVIDENCE SCORING POLICY V1

Use a deterministic 0–100 index for each direction.

Canonical arithmetic must use `Decimal` or integer basis points, never binary floating-point as the source of truth.

## A. MATERIAL COMPONENT COVERAGE — 0 to 50 points

Measure how much of the complete Phase 2E material component inventory has adequate evidence in this direction.

Use the verified Phase 2E component inventory denominator.

Unexamined/no-evidence components remain in the denominator.

Do not use only aligned components.

Recommended formula:

`covered_material_components / total_material_components * 50`

where "covered" means adequate direct directional coverage under Phase 2E semantics.

If component weighting does not exist, treat material components equally.

Do not invent importance weights.

## B. INDEPENDENT CORROBORATION — 0 to 30 points

Use Phase 2E independence groups.

Do not reward unlimited source accumulation.

Recommended per-component corroboration level:
- NONE → 0.0
- SINGLE_GROUP → 0.5
- MULTIPLE_GROUPS → 1.0

Aggregate across material components and multiply by 30.

This intentionally treats 2 independent groups and 20 independent groups as the same maximum corroboration tier unless a later calibrated policy justifies more granularity.

Provider count, excerpt count, and duplicate source records must not increase this dimension.

## C. RELATION DIRECTNESS — 0 to 20 points

Use Phase 2D/2E contribution semantics.

Recommended directional factors:
- eligible direct support/contradiction → 1.0
- eligible partial support/contradiction → 0.5
- eligible mixed → count only in the appropriate directional components using Phase 2D component judgments
- context-only → 0.0
- insufficient → 0.0
- not relevant → 0.0
- disqualified → 0.0

Aggregate deterministically over the complete component inventory.

Do not infer directness with a new model call.

### Directional index

For each direction:

`coverage_points + corroboration_points + directness_points`

bounded to:

`0 <= index <= 100`

These numbers measure structured evidence posture only.

---

# 10. SOURCE QUALITY IS A RELIABILITY LAYER, NOT HIDDEN POINTS

Do not silently turn publication/retraction metadata into arbitrary hidden score bonuses.

Phase 2E source quality should produce an explicit `ScoreReliabilityProfile` or equivalent.

At minimum represent:
- retraction posture
- publication-status posture
- traceability
- content-scope ceiling
- preprint presence
- unknown publication status
- unknown retraction status
- abstract-only limitation
- disqualified group count
- contributing eligible group count

Use a finite reliability taxonomy, for example:
- HIGHER_RELIABILITY
- MODERATE_RELIABILITY
- LIMITED_RELIABILITY
- INDETERMINATE

Choose final names after inspecting repository conventions.

Do not call this "scientific confidence".

Do not infer peer review.

Do not turn UNKNOWN into favorable known quality.

---

# 11. SCORE DISPOSITION

Not every claim should receive an interpretable final scalar.

Create a finite score disposition/status.

At minimum distinguish:

### SCORED
A support index may be reported as the primary directional claim-evidence score.

### CONTESTED — FINAL SCALAR WITHHELD
Material support and contradiction coexist such that a single primary scalar would hide the conflict.

Both directional indices remain available.

`final_support_index = None`

### BLOCKED_SOURCE_QUALITY — FINAL SCALAR WITHHELD
Phase 2E is blocked by source-quality constraints.

Directional audit information may be retained, but no primary final score is issued.

### NOT_READY / INCOMPLETE_INPUT — FINAL SCALAR WITHHELD
Phase 2E state is incomplete/not-ready or required component completeness is unavailable.

### NO_DIRECT_EVIDENCE
A valid evaluated posture with no direct support or contradiction.

A numeric directional index of 0 is allowed if the contract clearly distinguishes this from "not evaluated".

Preserve:

`None = not scorable/not issued`

versus:

`0 = evaluated and no directional evidentiary support`

---

# 12. FINAL SUPPORT INDEX

The `final_support_index` is optional.

It may be equal to `support_index` only when:
- score disposition is `SCORED`
- Phase 2E input is complete
- component inventory completeness is COMPLETE
- assessment is not CONTESTED
- assessment is not BLOCKED_SOURCE_QUALITY
- no release-critical provenance blocker exists

Do not calculate `support_index - contradiction_index` as the final score.

If contradiction exists below the Phase 2E CONTESTED threshold, retain it explicitly with a reason code/flag.

The final support index remains an evidentiary support index, not a truth probability.

---

# 13. PHASE 2E OUTCOME INTERACTION

Phase 2F must respect, not rewrite, Phase 2E.

Expected posture mapping:
- `SUFFICIENT_SUPPORT`
  - usually `SCORED`
  - support index available
  - contradiction index still computed/reported
- `SUFFICIENT_CONTRADICTION`
  - evaluated
  - support may legitimately be 0/low
  - contradiction index reflects contradictory coverage
  - claim status remains untouched
- `CONTESTED`
  - both directional indices reported
  - final scalar withheld
- `PARTIALLY_SUFFICIENT`
  - score may be issued if input is complete
  - uncovered material components stay in denominator
- `INSUFFICIENT_EVIDENCE`
  - directional indices may be low/zero
  - insufficiency remains explicit
- `NO_DIRECT_EVIDENCE`
  - directional indices = 0 where appropriate
  - distinguish from no assessment
- `BLOCKED_SOURCE_QUALITY`
  - final scalar withheld

Do not change the Phase 2E outcome.

---

# 14. ANTI-GAMING / MONOTONICITY INVARIANTS

Implement and test:

## Duplicate invariance
Adding another provider observation, excerpt, or duplicate logical source must NOT increase independence/corroboration points.

## Irrelevant-evidence invariance
Adding NOT_RELEVANT, CONTEXT_ONLY, or INSUFFICIENT evidence must NOT increase direct-support score.

## Positive monotonicity
Adding genuinely independent eligible direct supporting evidence to a supported component must not decrease support index.

## Negative monotonicity
Adding eligible contradictory evidence must not increase support index merely because more evidence exists.

## Retraction monotonicity
Marking a contributing supporting source as retracted must not increase support or reliability.

## Unknown monotonicity
Replacing known favorable metadata with UNKNOWN must not improve reliability.

## Coverage monotonicity
Adding an unexamined material component to the canonical component inventory must not increase support score.

## Conflict preservation
Adding material contradictory evidence must not be averaged away into a deceptively ordinary single score.

---

# 15. COMPONENT-LEVEL SCORE TRACE

For each material component record:
- component ID / anchor reference
- support coverage state
- contradiction coverage state
- supporting independence groups
- contradicting independence groups
- support corroboration level
- contradiction corroboration level
- direct/partial contribution factors
- component support points
- component contradiction points
- limitations/reason codes

Do not duplicate full claim text unnecessarily.

---

# 16. DETERMINISTIC ARITHMETIC

Use deterministic arithmetic.

Preferred:
- `Decimal`, or
- integer basis points

Define:
- precision
- rounding mode
- serialization format

Example acceptable contract:
- internal basis points: 0–10000
- display: two decimals

Identical inputs must produce byte-stable serialized numeric outputs.

---

# 17. INPUT FINGERPRINTING AND REPRODUCIBILITY

Bind each scorecard to the exact scoring-relevant Phase 2E inputs.

Fingerprint must include at least:
- claim ID
- claim/component-inventory identity
- Phase 2E assessment ID
- sufficiency policy version
- component coverage states
- independence group identities
- eligible/disqualified contribution classes
- relevant source-quality/unknown/scope fields
- Phase 2F scoring policy version

Do not include unstable timestamps.

Changing a scoring-relevant input must change the fingerprint.

Identical input must reproduce identical output.

---

# 18. SCORING VERSIONING

Create explicit:
- score schema version
- scoring policy version
- arithmetic/version contract
- reliability-profile version if separate

Recommended:
- `CLAIM-EVIDENCE-SCORE-SCHEMA-V1`
- `CLAIM-EVIDENCE-SCORING-POLICY-V1`

Any semantic change to point allocation, corroboration saturation, relation factors, disposition rules, conflict handling, or rounding requires a policy-version bump.

---

# 19. NO LLM REQUIRED BY DEFAULT

Phase 2F should be fully deterministic if Phase 2E provides all required structured inputs.

Do not add a model call to choose:
- points
- weights
- caps
- disposition
- reliability

A model-generated score is forbidden.

If no model is needed, document that as intentional.

---

# 20. STRUCTURED REASON CODES

Use bounded reason codes, including concepts such as:
- FULL_COMPONENT_SUPPORT_COVERAGE
- PARTIAL_COMPONENT_SUPPORT_COVERAGE
- NO_DIRECT_SUPPORT
- FULL_COMPONENT_CONTRADICTION_COVERAGE
- PARTIAL_COMPONENT_CONTRADICTION_COVERAGE
- SINGLE_GROUP_CORROBORATION
- MULTIPLE_GROUP_CORROBORATION
- DUPLICATE_SOURCE_COLLAPSED
- DUPLICATE_EXCERPT_COLLAPSED
- DIRECT_RELATION_CREDIT
- PARTIAL_RELATION_CREDIT
- CONTESTED_FINAL_SCORE_WITHHELD
- BLOCKED_SOURCE_QUALITY_SCORE_WITHHELD
- INCOMPLETE_INPUT_SCORE_WITHHELD
- ABSTRACT_ONLY_RELIABILITY_LIMITATION
- PREPRINT_RELIABILITY_LIMITATION
- UNKNOWN_PUBLICATION_STATUS
- UNKNOWN_RETRACTION_STATUS
- RETRACTED_SOURCE_EXCLUDED
- CONTRADICTION_PRESENT

Use the smallest clean final set.

---

# 21. SCORE BOUNDS AND CONTRACT VALIDATION

Schemas must enforce:
- each directional index in [0, 100]
- each point dimension within its allowed range
- aggregate total exactly equals the dimension sum
- final_support_index is `None` or [0, 100]
- final_support_index cannot exist for a withheld disposition
- final_support_index matches support_index when policy says it is issuable
- contradiction is never silently subtracted from support
- disposition is consistent with Phase 2E outcome
- component traces reconcile with aggregate dimensions
- policy/schema versions are present
- input fingerprint is present and valid

Enforce impossible-state rejection in schema validators, not only policy code.

---

# 22. CLAIM / PROJECT IMMUTABILITY

Before and after a real Phase 2F graph run, verify preservation of:

## ProjectState
- claims
- claim status
- claim confidence
- evidence references
- counter-evidence references
- existing canonical ScoreRecords
- TrustGate
- evaluation_status

## Phase 2C
- evidence
- provenance
- verification versions

## Phase 2D
- alignments
- anchors
- relationships
- component judgments

## Phase 2E
- component inventory
- independence groups
- evidence weight profiles
- sufficiency assessments
- outcomes
- source-quality fields
- unknowns
- limitations

Use populated fixtures.

Add negative controls proving mutation guards are non-vacuous.

---

# 23. CROSS-CLAIM ISOLATION

Each scorecard is claim-specific.

The same evidence may contribute differently to different claims because alignment is claim-specific.

Do not create a global evidence support score independent of claim context.

Source quality may be shared; semantic contribution is claim-specific.

---

# 24. CROSS-RUN ISOLATION

Reject:
- Phase 2E assessments from another ResearchRun
- component inventories from another claim/run
- profiles/groups not traceable to current run
- scorecard references that cannot reconcile to current scoring inputs

No cross-run contamination.

---

# 25. IDEMPOTENCY / CHECKPOINTING

Verify:
- completed scoring run is not silently reopened
- rerunning completed graph does not duplicate scorecards
- scorecard IDs are stable for identical inputs
- fingerprints are stable
- checkpoint resume does not double-count points
- deterministic ordering is preserved
- identical inputs reproduce identical serialized scorecards
- incompatible duplicate scorecards are rejected

Reuse Phase 2C–2E hardening patterns.

---

# 26. GRAPH

Implement dedicated Phase 2F graph:

`START`
→ validate prerequisites
→ load complete Phase 2E state
→ derive deterministic directional component traces
→ calculate support channel
→ calculate contradiction channel
→ derive reliability profile
→ apply score-disposition policy
→ create claim evidence scorecards
→ finalize Phase 2F scoring run
→ `END`

Do not invoke project-level scoring, TrustGate, mentor behavior, or later phases.

Use existing serializer/checkpoint infrastructure.

---

# 27. NO-INPUT / NOT-READY BEHAVIOR

Handle explicitly:
- no claims → no-scorable-claims
- Phase 2E missing → not-ready
- Phase 2E incomplete → no final scalar
- component inventory incomplete/unknown → withhold final scalar
- Phase 2E contested → separate channels, final scalar withheld
- blocked source quality → final scalar withheld
- no direct evidence → evaluated zero-directional posture, not "not evaluated"

None may mutate canonical state.

---

# 28. OFFICIAL-JUDGING SEPARATION

Do not encode Mawhiba/Ibdaa official criterion weights in Phase 2F.

Do not map:

`support_index = 80`

to:

`project innovation score = 80`

or any competition score.

Official requirements/scoring belong to a later explicit project-evaluation scoring phase.

Document this separation prominently.

---

# 29. GOLD EVAL

Add dedicated offline Phase 2F scoring eval.

Suggested:
- `evals/claim_evidence_scoring/v1/`
- `src/evals/claim_scoring/`

Create at least `144 total Gold cases`.

Minimum language coverage:
- Arabic >= 28
- mixed Arabic/English >= 20

The suite must verify exact deterministic numeric outcomes.

Required categories include:
1. no direct evidence → support=0, contradiction=0
2. one fully supported component, single group
3. one fully supported component, multiple groups
4. partial support only
5. full multi-component support
6. one supported / one no-evidence component
7. full contradiction
8. partial contradiction
9. contested support + contradiction
10. MIXED alignment contribution
11. same DOI from multiple providers
12. multiple excerpts same paper
13. duplicate canonical source records
14. distinct DOI same title
15. context-only evidence
16. insufficient evidence
17. not-relevant evidence
18. retracted supporting source
19. retracted contradicting source
20. preprint limitation
21. unknown publication status
22. unknown retraction status
23. abstract-only limitation
24. complete inventory
25. incomplete inventory
26. unknown inventory
27. unexamined material component
28. single vs multiple-group saturation
29. 2 groups vs 20 groups cannot exceed corroboration max
30. duplicate provider leaves score unchanged
31. duplicate excerpt leaves score unchanged
32. NOT_RELEVANT leaves support unchanged
33. CONTEXT_ONLY leaves support unchanged
34. INSUFFICIENT leaves support unchanged
35. genuine independent support cannot lower support
36. contradiction cannot increase support
37. retraction cannot increase support/reliability
38. known favorable → UNKNOWN cannot improve reliability
39. extra uncovered component cannot increase support
40. contested final scalar withheld
41. blocked-source-quality scalar withheld
42. not-ready scalar withheld
43. zero vs None semantics
44. support/contradiction never collapsed into net
45. exact score arithmetic
46. rounding boundary
47. min bound
48. max bound
49. score vector reconciliation
50. fingerprint stability
51. fingerprint changes on relevant input
52. checkpoint resume
53. rerun idempotency
54. duplicate scorecard rejection
55. ProjectState immutability
56. canonical ScoreRecord immutability
57. Phase 2E immutability
58. cross-run rejection
59. cross-claim isolation
60. Arabic scientific claim
61. mixed Arabic/English claim
62. prompt-injection text has no effect on deterministic scoring
63. official project-score separation
64. policy-version correctness

Do not pad with trivial duplicates.

---

# 30. PROPERTY / METAMORPHIC TESTING

Add deterministic property-style tests for:
- duplicate invariance
- irrelevant-evidence invariance
- positive monotonicity
- contradiction non-improvement
- retraction non-improvement
- unknown non-improvement
- uncovered-component non-improvement
- boundedness
- exact reproducibility
- order invariance where order is semantically irrelevant

Do not introduce flaky random tests.

---

# 31. QUALITY METRICS

At minimum measure:
- exact support-index accuracy
- exact contradiction-index accuracy
- coverage-dimension accuracy
- corroboration-dimension accuracy
- directness-dimension accuracy
- score-disposition accuracy
- final-scalar issuance/withholding accuracy
- reliability-profile accuracy
- duplicate-invariance accuracy
- monotonicity-invariant accuracy
- score-bound accuracy
- arithmetic-reconciliation accuracy
- input-fingerprint accuracy
- idempotency accuracy
- score traceability
- policy-version accuracy
- per-language exact-score accuracy

No-denominator subgroup metrics must report `None` / `not measured`, not zero.

Provide per-language metrics for English, Arabic, and mixed.

---

# 32. RELEASE-BLOCKING SAFETY GATES

All must be zero.

At minimum include:

1. ProjectState mutation
2. claim mutation
3. claim-status mutation
4. claim-confidence mutation
5. claim evidence-reference mutation
6. claim counter-evidence-reference mutation
7. canonical ScoreRecord mutation
8. TrustGate mutation
9. evaluation-status mutation
10. Phase 2C evidence mutation
11. Phase 2D alignment mutation
12. Phase 2E sufficiency mutation
13. automatic project-score update
14. automatic claim-status update
15. invalid Phase 2E assessment acceptance
16. cross-run assessment acceptance
17. cross-claim scorecard contamination
18. duplicate logical source inflated support
19. duplicate logical source inflated contradiction
20. duplicate excerpt inflated support
21. duplicate excerpt inflated contradiction
22. provider observation inflated support
23. provider observation inflated contradiction
24. context-only counted as direct support
25. insufficient counted as direct support
26. not-relevant counted as direct support
27. retracted source counted as eligible positive support
28. unknown quality treated as favorable known quality
29. unexamined component omitted from score denominator
30. incomplete inventory received full scalar
31. contested claim received final scalar
32. blocked-source-quality claim received final scalar
33. not-ready claim received final scalar
34. support/contradiction collapsed into misleading net score
35. contradiction increased support index
36. duplicate evidence increased support index
37. irrelevant evidence increased support index
38. retraction increased support/reliability
39. unknown metadata improved reliability
40. out-of-range score accepted
41. aggregate score arithmetic mismatch accepted
42. invalid score disposition accepted
43. missing/invalid scoring policy version accepted
44. unstable identical-input fingerprint
45. scoring-relevant input change failed to change fingerprint
46. incompatible duplicate scorecard accepted
47. Phase 2F score written into official/project scoring
48. Phase 2F score presented/typed as truth probability

If any gate is nonzero: `BLOCKED`.

Report every gate individually.

---

# 33. CRITICAL INVARIANTS

`Support score ≠ truth probability`

`Contradiction score ≠ inverse truth probability`

`Support - contradiction ≠ valid net truth score`

`Duplicate source ≠ more corroboration`

`More providers ≠ more studies`

`More excerpts ≠ more independence`

`Context ≠ direct support`

`Relevant ≠ support`

`Unknown ≠ favorable`

`Retracted ≠ eligible positive corroboration`

`Unexamined components stay in the denominator`

`Contested evidence cannot be hidden behind one scalar`

`0 ≠ not evaluated`

`None = scalar not issued`

`Claim evidence score ≠ project score`

`Claim evidence score ≠ official judging score`

`Claim evidence score ≠ TrustGate`

---

# 34. DOCUMENTATION

Add/update:
- Phase 2F architecture documentation
- developer architecture overview
- one ADR establishing:

`Claim Evidence Scores Are Deterministic Evidence Indices, Not Truth Probabilities or Project Scores`

Explain:
- separate support/contradiction channels
- why net subtraction is forbidden
- why score vector is canonical
- why final scalar is optional
- why contested cases withhold a scalar
- why source quality is reliability, not hidden points
- why corroboration saturates
- deterministic arithmetic/versioning
- why Phase 2F does not write `ProjectState.scores`
- why official Mawhiba/Ibdaa scoring is out of scope

Use English for developer documentation.

Arabic is allowed as source/student/eval data.

Preserve language policy.

---

# 35. TARGETED TEST STRATEGY

Run smallest relevant tests first:
- schemas
- exact arithmetic
- support/contradiction separation
- component coverage
- independence saturation
- directness factors
- score disposition
- contested withholding
- blocked-source-quality withholding
- zero vs None
- reliability profile
- duplicate/provider/excerpt invariance
- monotonicity
- fingerprinting
- versioning
- cross-run/cross-claim isolation
- ProjectState / ScoreRecord immutability
- Phase 2E immutability
- checkpoint/idempotency
- Gold invariants
- per-language exact-score metrics
- safety gates

Do not start with the full repository suite.

---

# 36. PHASE-SPECIFIC RELEASE TEST

After targeted tests pass:
1. run all Phase 2F test modules
2. run Phase 2F offline eval CLI

Required:
- Phase 2F eval = PASS
- all safety gates = zero
- no errored Gold cases
- all coverage minimums satisfied
- exact-score metrics meet thresholds
- anti-gaming/property invariants pass

---

# 37. REQUIRED CROSS-PHASE REGRESSION

Run once after Phase 2F passes:

1. Phase 2E claim sufficiency eval
2. Phase 2D claim-evidence alignment eval
3. Phase 2C evidence extraction eval
4. Phase 2B academic research eval
5. Phase 2A research eval
6. Phase 1 eval

All must PASS.

Do not rerun repeatedly unless a later fix could reasonably affect them.

---

# 38. FINAL FULL-SUITE RELEASE GATE

Only after targeted, Phase 2F, and regression gates pass, run the full suite once.

On Windows:

`.venv\Scripts\python.exe -m pytest`

Required:
- 0 failed

Report exact passed/skipped/failed counts.

Do not invent expected counts.

---

# 39. GIT DISCIPLINE

Work only on:

`feat/phase2f-evidence-based-claim-scoring`

Do not merge into `main`.

Do not force-push.

Do not rewrite Phase 2E history.

Do not create an additional worktree.

Do not commit:
- `.idea/`
- `.claude/`
- Graphify output
- caches
- temporary logs
- unrelated files

Prefer one clean implementation commit or a small number of justified commits.

Before completion verify:
- branch
- status
- recent log
- diff
- working tree cleanliness

---

# 40. FINAL REPORT

Return the final report in English only.

Use exactly:

## Phase 2F Result

## Starting Git State

## Architecture Implemented

## Score Semantics

State exactly what numeric indices mean and do NOT mean.

## Score Vector

## Support / Contradiction Separation

## Scoring Policy

State exact point allocations, factors, saturation rules, rounding, and policy version.

## Component Coverage

## Independence / Anti-Gaming

## Reliability Profile

## Score Disposition

## Zero vs None Semantics

## Deterministic Arithmetic

## Input Fingerprinting

## Monotonicity / Property Invariants

## Immutability

Report ProjectState, canonical ScoreRecord, Phase 2C, Phase 2D, and Phase 2E preservation.

## Checkpoint / Idempotency

## Gold Dataset

Report:
- total
- English
- Arabic
- mixed
- per-disposition coverage
- score-boundary coverage
- adversarial/property categories

## Per-Language Metrics

## Quality Metrics

## Safety Gates

List every gate individually with:
- metric name
- numerator
- denominator
- violation count/rate

## Phase 2F Eval

## Cross-Phase Regression

Report Phase 2E, 2D, 2C, 2B, 2A, and Phase 1 separately.

## Tests

Report exactly:
- passed
- skipped
- failed
- live tests actually executed
- live tests not executed

## Files Modified

## Git End State

Include:
- branch
- status
- latest commits
- `git diff --stat main...HEAD`

## Remaining Limitations

Explicitly include:
- score is a policy-defined evidence index, not a truth probability
- current scientific content remains abstract-level unless trusted full text is added later
- publication/retraction metadata may remain unknown
- Phase 2F does not produce official Mawhiba/Ibdaa scoring
- Phase 2F does not produce final project scoring
- future calibration requires explicit policy-version changes, never silent retuning

## Regression Status

## Status

Use exactly one:

`READY TO MERGE PHASE 2F`

or

`BLOCKED`

Then STOP.

Do not merge into main.

Do not start Phase 2G or project-level scoring.
