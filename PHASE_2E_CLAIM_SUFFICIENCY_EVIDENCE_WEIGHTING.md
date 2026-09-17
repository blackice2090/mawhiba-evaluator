# PHASE 2E — CLAIM SUFFICIENCY & EVIDENCE WEIGHTING

## EXECUTION DISCIPLINE — APPLY TO THIS PHASE

Treat this as a high-trust architecture + implementation phase.

The goal is NOT to produce a simplistic evidence score.

The goal is to create an auditable claim-level sufficiency layer that:
- consumes only trusted Phase 2C evidence and verified Phase 2D alignments
- separates evidence relationship from evidence sufficiency
- separates source quality from semantic support
- prevents duplicate evidence from being counted as independent corroboration
- represents uncertainty and unknowns explicitly
- preserves contradictory evidence
- does not mutate claim status, project scores, or TrustGate state
- remains suitable for later scoring/red-team/final-verification phases

### Core execution rules

- Keep scope strictly limited to Phase 2E.
- Use the primary Claude Code session for architecture, implementation, testing, regression, Git verification, and reporting.
- Do NOT delegate the complete Phase or major Phase areas to Agents/Subagents.
- Avoid creating worktree-based Agents.
- Use a Subagent only for a narrowly scoped, read-only investigation that genuinely reduces context duplication.
- Inspect only repository surfaces required for this Phase.
- Prefer targeted search/navigation over recursive repository exploration.
- Reuse existing schemas, graph conventions, serializer/checkpoint infrastructure, provenance models, source identity rules, and eval patterns.
- Prefer the smallest correct architectural extension.
- Do not refactor unrelated Phase 1 / 2A / 2B / 2C / 2D code.
- Do not weaken tests, validators, assertions, schemas, referential integrity, metrics, eval denominators, or safety gates.
- Do not convert failures into skips.
- Do not silently broaden scope.
- If the existing architecture materially conflicts with this specification, STOP and report the conflict.
- Do not merge into `main`.
- Do not start Phase 2F.
- Do not mutate claim status, claim confidence, claim evidence references, scores, evaluation status, or TrustGate.
- Do not claim scientific truth has been established.

### Required testing progression

`architecture verification`
→ `implementation`
→ `smallest targeted tests`
→ `fix targeted failures`
→ `rerun targeted tests`
→ `Phase 2E tests/eval`
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
- Phase 2D merged
- expected current main HEAD: `0a5d249`
- previous post-merge release gate:
  - 1333 passed
  - 24 skipped
  - 0 failed

Before modifying code:
1. verify current branch
2. verify working tree is clean
3. verify current HEAD
4. confirm Phase 2C evidence extraction structures exist
5. confirm Phase 2D claim-evidence alignment structures exist
6. create `feat/phase2e-claim-sufficiency-weighting`

Do not use an additional Git worktree.

If the baseline materially differs, STOP and report the mismatch.

---

# 2. ARCHITECTURE GATE — OPUS MUST RESOLVE BEFORE CODING

Before implementation, inspect only the minimum Phase 2C/2D schemas and produce a concise architecture decision covering:

1. owner of Phase 2E state
2. exact input contract
3. evidence-unit identity and independence grouping
4. source-quality dimensions actually observable from current trusted data
5. claim-component coverage model
6. contradiction handling
7. sufficiency outcome taxonomy
8. deterministic vs model-assisted responsibilities
9. unknown/not-measured semantics
10. immutability boundaries

Proceed directly if the design is compatible with the existing architecture.

STOP only if there is a genuine architectural conflict.

Do not spend context redesigning approved Phase 2C or 2D concepts.

---

# 3. PHASE OBJECTIVE

Implement a trustworthy claim-level sufficiency layer over Phase 2D alignments.

Architecture:

`Verified Source`
→ `ExtractedEvidence`
→ `Claim–Evidence Alignment`
→ `Evidence Weight Profile`
→ `Claim Sufficiency Assessment`
→ `STOP`

Phase 2E answers:

> Given all trusted aligned evidence currently available for this claim, what is the evidence posture, and is the available evidence sufficient under an explicit auditable policy?

Phase 2E does NOT answer:
- what project score this claim should produce
- whether the claim is universally scientifically proven
- whether TrustGate should pass

Preserve:

`Evidence exists ≠ Evidence supports the claim`

`Alignment ≠ Claim verification`

`Support ≠ Sufficiency`

`Quantity ≠ Independence`

`Source prestige ≠ Scientific truth`

`Sufficiency assessment ≠ Final project score`

---

# 4. OWNERSHIP

Phase 2E output must remain on the research/evaluation execution layer.

Preferred ownership:
`ResearchRun`

following Phase 2C and Phase 2D ownership boundaries.

Add a dedicated Phase 2E run/state rather than writing sufficiency into `ClaimRecord`.

Do NOT mutate:
- `ProjectState.claims`
- `ClaimRecord.status`
- claim confidence
- `ClaimRecord.evidence_ids`
- `ClaimRecord.counter_evidence_ids`
- `ProjectState.evidence`
- Phase 2C `ExtractedEvidence`
- Phase 2D alignments
- scores
- TrustGate
- evaluation_status

The Phase 2E result is an auditable analytical artifact, not canonical project-state mutation.

---

# 5. INPUT CONTRACT

Phase 2E may consume only:
1. existing project claims
2. accepted Phase 2C `ExtractedEvidence`
3. verified Phase 2D claim-evidence alignments
4. trusted source/provider metadata already attached to the ResearchRun
5. canonical source identity / source fingerprint information from earlier phases

Do not:
- create claims
- extract new evidence
- reinterpret rejected Phase 2C evidence
- create new Phase 2D relationships
- use provider AI takeaways as evidence
- treat metadata-only records as scientific support
- use cross-run evidence
- infer unavailable source-quality facts

If required data is unknown, preserve `UNKNOWN` / `NOT_MEASURED`.

Never fabricate quality attributes.

---

# 6. NO SINGLE MAGIC WEIGHT

Do NOT create one opaque numeric evidence score such as:

`evidence_weight = 0.73`

that collapses all quality dimensions.

Phase 2E must use an explicit multi-dimensional weight/profile model.

A scalar score, if ever justified, belongs to a later scoring phase.

Phase 2E must preserve the reasons behind the sufficiency result.

---

# 7. EVIDENCE WEIGHT PROFILE

Create an `EvidenceWeightProfile` or equivalent for each evidence item used in a claim sufficiency assessment.

At minimum reference:
- claim ID
- evidence ID
- alignment ID
- source ID / canonical source identity
- independence group ID
- Phase 2D relationship
- component coverage
- source-status factors
- provenance/traceability state
- explicit limitations
- unknown dimensions
- contribution classification
- profile version

Do not duplicate canonical evidence text unnecessarily.

---

# 8. SOURCE-QUALITY DIMENSIONS

Evaluate only dimensions derivable from trusted current metadata.

## Retraction status

Conceptual values:
- RETRACTED
- NOT_RETRACTED
- UNKNOWN

Retracted evidence must never count as normal positive corroboration.

Preserve it for contradiction/context/audit purposes.

Do not silently delete it.

## Publication/review status

Use only metadata actually available.

Conceptual values may include:
- PEER_REVIEWED_OR_FORMALLY_PUBLISHED
- PREPRINT
- OTHER_PUBLISHED
- UNKNOWN

Do not infer peer review from venue prestige, title, provider, or URL.

## Source traceability

The source → evidence → alignment chain must be fully traceable.

Untraceable evidence cannot contribute to sufficiency.

## Content scope

Phase 2C currently uses abstract-level evidence.

Preserve this limitation explicitly.

Do not pretend abstract-only evidence provides full methodology verification.

## Provider observation diversity

Multiple provider observations of the same logical paper/source must not count as independent studies.

Use Phase 2B canonical source identity rules.

---

# 9. INDEPENDENCE AND DOUBLE-COUNTING

This is release-critical.

Create an explicit independence grouping mechanism.

Evidence items must be grouped as the same underlying source/study when they resolve to the same canonical logical source.

These must NOT count as independent corroboration:
- same DOI returned by different providers
- same paper observed through Consensus/OpenAlex/Semantic Scholar
- multiple excerpts from the same paper
- multiple provider records representing the same logical publication
- duplicate candidates merged under existing canonical source identity

Create deterministic `independence_group_id` or equivalent.

Use strong identifiers/canonical source identity.

Do not introduce title-only dedupe where the repository already forbids it.

Multiple excerpts from one group may improve component coverage but must not increase independent-source count.

---

# 10. RELATIONSHIP CONTRIBUTION

Use Phase 2D relationship without rewriting it.

Conceptually:
- `SUPPORTS` → direct positive evidence
- `PARTIALLY_SUPPORTS` → positive but incomplete evidence
- `CONTRADICTS` → direct negative evidence
- `PARTIALLY_CONTRADICTS` → negative but incomplete evidence
- `MIXED` → positive and negative across claim components
- `CONTEXT_ONLY` → contextual, not direct support/contradiction
- `INSUFFICIENT` → relevant but not enough for direct contribution
- `NOT_RELEVANT` → excluded from sufficiency contribution

Do not reinterpret `CONTEXT_ONLY` or `INSUFFICIENT` as weak support.

---

# 11. CLAIM-COMPONENT COVERAGE

Use exact claim component anchors from Phase 2D.

For each material claim component determine whether there is:
- independent supporting coverage
- independent contradicting coverage
- mixed coverage
- unresolved relevant evidence
- context-only evidence
- no evidence

Do not treat support for one component as support for the whole compound claim.

A compound claim cannot become fully supported if a material component lacks adequate supporting coverage.

---

# 12. SUFFICIENCY OUTCOME TAXONOMY

Create a finite claim-level sufficiency taxonomy.

Use these semantics unless existing conventions strongly require equivalent names:

## SUFFICIENT_SUPPORT

Trusted evidence provides adequate independent positive coverage for all material claim components under the versioned Phase 2E policy, with no unresolved material contradiction that prevents a support posture.

This is not universal scientific proof.

## SUFFICIENT_CONTRADICTION

Trusted evidence provides adequate independent contradictory coverage against the material claim proposition/component set.

This does not mutate claim status.

## CONTESTED

Material credible support and material credible contradiction exist from independent evidence groups.

Do not average the conflict away.

## PARTIALLY_SUFFICIENT

At least one material component has adequate evidence, but at least one other material component remains inadequately evidenced, and `CONTESTED` does not better describe the posture.

## INSUFFICIENT_EVIDENCE

Relevant evidence exists, but it does not meet the Phase 2E sufficiency policy for adequate support or contradiction.

## NO_DIRECT_EVIDENCE

No direct supporting/contradicting Phase 2D alignment is available.

Context-only / insufficient / not-relevant material may exist.

## BLOCKED_SOURCE_QUALITY

Direct evidence exists, but all otherwise-contributing evidence is disqualified from normal sufficiency contribution by critical quality constraints such as retraction or invalid traceability.

Keep these states distinct.

---

# 13. SUFFICIENCY IS NOT A SIMPLE STUDY COUNT

Do not implement:
- `2 papers = sufficient`
- `3 sources = strong`

without additional constraints.

At minimum sufficiency must account for:
- component coverage
- independence
- direction
- contradiction
- source traceability
- retraction status
- available publication-status metadata
- direct vs partial/contextual/insufficient relation
- abstract-only scope limitation
- unknown quality dimensions

Unknown must not silently become favorable.

---

# 14. DEFAULT VERSIONED SUFFICIENCY POLICY

Implement an explicit deterministic Phase 2E policy.

Recommended conservative policy:

### Positive sufficiency
For a material component:
- at least one eligible direct `SUPPORTS` contribution from a traceable non-retracted independence group is required for direct support
- a single independent group should normally remain limited unless the policy explicitly and transparently allows sufficiency
- two or more eligible independent groups provide stronger corroboration but do not override contradiction
- partial support alone cannot produce full component sufficiency

### Contradictory sufficiency
Mirror the same logic for direct contradiction.

### Conflict
If eligible independent groups provide material direct support and material direct contradiction, preserve conflict.

### Context/insufficient/not relevant
`CONTEXT_ONLY`, `INSUFFICIENT`, and `NOT_RELEVANT` do not count as direct corroborating groups.

### Retraction
Retracted evidence:
- remains visible
- does not count as normal positive corroboration
- may contribute to blocker reporting
- is never silently removed

Before finalizing exact thresholds, inspect current observable metadata.

If a recommended rule requires unavailable facts, use a more conservative explicit rule and document why.

---

# 15. EVIDENCE CONTRIBUTION CLASS

Create a bounded deterministic contribution classification, conceptually:

- ELIGIBLE_DIRECT_SUPPORT
- ELIGIBLE_PARTIAL_SUPPORT
- ELIGIBLE_DIRECT_CONTRADICTION
- ELIGIBLE_PARTIAL_CONTRADICTION
- ELIGIBLE_MIXED
- CONTEXT_ONLY
- RELEVANT_BUT_INSUFFICIENT
- NOT_RELEVANT
- DISQUALIFIED_RETRACTED
- DISQUALIFIED_UNTRACEABLE
- UNKNOWN_QUALITY_LIMITATION

Use the smallest clean taxonomy compatible with the architecture.

Derive it deterministically from:
- Phase 2D relation
- source-quality metadata
- provenance
- Phase 2E policy

Do not ask an LLM to invent a category that structured data can determine.

---

# 16. DETERMINISTIC VS MODEL-ASSISTED RESPONSIBILITIES

Prefer deterministic computation for:
- identity
- independence grouping
- source traceability
- retraction/preprint flags
- provider-observation dedupe
- claim/evidence/alignment references
- component coverage aggregation
- contribution class
- independent source counts
- contradiction/support counts
- final policy application
- sufficiency outcome when structured inputs are enough

Use a model only if a genuinely required semantic decision cannot be derived from existing Phase 2D structured output.

Do not add an LLM call merely because this is an AI system.

If Phase 2E can be fully deterministic, document that as intentional and preferred.

---

# 17. CLAIM SUFFICIENCY ASSESSMENT RECORD

Create a canonical Phase 2E claim-level assessment record.

At minimum reference:
- assessment ID
- claim ID
- ResearchRun ID
- schema version
- policy version
- sufficiency outcome
- component sufficiency records
- evidence weight/profile references
- independence-group counts
- supporting independent groups
- contradicting independent groups
- contextual/insufficient groups
- disqualified groups
- explicit blockers
- explicit unknowns
- deterministic reason codes
- audit rationale derived from structured facts
- timestamps consistent with repository conventions

Do not duplicate entire evidence/source objects.

---

# 18. STRUCTURED REASON CODES

Prefer deterministic bounded reason codes over free-form model rationale.

At minimum support concepts such as:
- FULL_COMPONENT_COVERAGE
- PARTIAL_COMPONENT_COVERAGE
- SINGLE_INDEPENDENT_SOURCE_ONLY
- MULTIPLE_INDEPENDENT_SUPPORTING_SOURCES
- MULTIPLE_INDEPENDENT_CONTRADICTING_SOURCES
- MATERIAL_CONTRADICTION_PRESENT
- SUPPORT_AND_CONTRADICTION_PRESENT
- RETRACTED_SOURCE_EXCLUDED
- PREPRINT_LIMITATION
- ABSTRACT_ONLY_SCOPE
- TRACEABILITY_FAILURE
- NO_DIRECT_ALIGNMENT
- CONTEXT_ONLY_AVAILABLE
- RELEVANT_BUT_INSUFFICIENT
- INDEPENDENCE_COLLAPSED_DUPLICATES
- UNKNOWN_PUBLICATION_STATUS
- UNKNOWN_RETRACTION_STATUS

Use the smallest clean final set.

---

# 19. UNKNOWN / NOT-MEASURED SEMANTICS

Unknown is first-class.

Do not map unknown to:
- zero quality
- full quality
- peer-reviewed
- non-retracted
- independent
- sufficient

Use explicit `UNKNOWN`, `None`, or established equivalent.

Metrics with no denominator must report:
`None` / `not measured`

not zero.

---

# 20. RETRACTED AND PREPRINT EVIDENCE

## Retracted
Must:
- remain traceable
- remain visible
- not count as normal positive sufficiency
- be represented explicitly as disqualified/blocked contribution
- never be silently deleted

## Preprint
Must:
- remain usable if otherwise valid
- carry explicit limitation/status
- not automatically equal peer-reviewed/formally published evidence
- not automatically be rejected

Do not invent a universal numeric penalty.

---

# 21. ABSTRACT-ONLY LIMITATION

Phase 2C evidence is currently abstract-level.

Phase 2E must preserve this as an explicit limitation.

Do not claim assessment of:
- full methods
- complete statistical analysis
- supplementary material
- full-text limitations

unless those data actually exist.

Distinguish:

`evidence sufficiency under currently available trusted content`

from:

`complete scientific review of the underlying paper`.

---

# 22. CROSS-CLAIM ISOLATION

Evidence aligned to one claim must not automatically affect another.

Each assessment uses only verified Phase 2D alignments for that claim.

The same evidence may align differently to different claims.

Do not create a global semantic "support weight" independent of claim context.

Source quality can be source-level.

Semantic contribution is claim-specific.

---

# 23. CROSS-RUN ISOLATION

Reject:
- alignment from another ResearchRun
- evidence from another ResearchRun
- source/evidence/alignment references not traceable to current run

No cross-run contamination.

---

# 24. IDEMPOTENCY

Verify:
- rerunning a completed Phase does not duplicate assessments
- independence groups remain stable
- identical inputs produce equivalent deterministic results
- checkpoint resume does not double-count evidence
- terminal runs are not silently reopened
- incompatible duplicate assessments are rejected

Reuse Phase 2C/2D hardening patterns.

---

# 25. IMMUTABILITY

Before and after a real Phase 2E graph run, verify complete preservation of populated:

## ProjectState
- claims
- claim status
- claim confidence
- claim evidence references
- claim counter-evidence references
- ProjectState evidence
- scores
- TrustGate
- evaluation_status

## Phase 2C state
- ExtractedEvidence
- provenance
- verification/version data

## Phase 2D state
- alignments
- relationships
- exact anchors
- component judgments
- alignment provenance

Use populated fixtures.

Do not rely on empty-state tests.

Add negative controls proving guards detect mutation of existing values.

---

# 26. GRAPH

Implement dedicated Phase 2E graph:

`START`
→ validate prerequisites
→ load trusted Phase 2C evidence + Phase 2D alignments
→ build deterministic independence groups
→ build evidence weight profiles
→ aggregate claim-component coverage
→ apply versioned sufficiency policy
→ create claim sufficiency assessments
→ finalize Phase 2E run
→ `END`

Do not invoke later scoring/red-team/trust phases.

Use existing checkpoint/serializer infrastructure.

---

# 27. NO-INPUT / NOT-READY BEHAVIOR

Handle explicitly:

### No claims
Return explicit no-assessable-claims state.

### No accepted Phase 2C evidence
Return no-evidence/not-ready state.

### No verified Phase 2D alignments
Return no-direct-alignment state.

### Phase 2D incomplete
Do not proceed as if complete.

### Phase 2D pair-limit blocked
Do not claim sufficiency from an incomplete alignment universe.

### All direct evidence retracted/untraceable
Return an explicit blocked-source-quality posture where appropriate.

None may mutate ProjectState.

---

# 28. POLICY VERSIONING

Create explicit:
- assessment schema version
- sufficiency policy version
- evidence-weight profile version

A semantic policy change must require a version change.

Do not reuse Phase 2C verifier or Phase 2D alignment versions.

Serialized assessments must expose relevant versions.

---

# 29. GOLD EVAL

Add dedicated offline Phase 2E Gold suite.

Suggested locations:
- `evals/claim_sufficiency/v1/`
- `src/evals/claim_sufficiency/`

Adapt naming only if established conventions strongly justify an equivalent.

Create at least:
`120 total Gold cases`

Minimum language coverage:
- Arabic >= 24
- mixed Arabic/English >= 16

The rest may be English.

All sufficiency outcomes must have meaningful coverage.

Required adversarial/behavior categories include:

1. one direct supporting source only
2. two independent supporting sources
3. same paper from two providers counts once
4. multiple excerpts from same paper count once for independence
5. DOI duplicate collapse
6. strong-identifier duplicate collapse
7. title similarity alone does not collapse distinct canonical identities
8. direct contradiction from one independent source
9. multiple contradictory sources
10. support + contradiction → contested
11. compound claim full coverage
12. compound claim partial coverage
13. partial support only
14. partial contradiction only
15. MIXED Phase 2D relation
16. context-only evidence
17. insufficient relationship only
18. not-relevant evidence only
19. no direct evidence
20. retracted supporting paper
21. retracted contradicting paper
22. preprint-only support
23. preprint + formally published independent support
24. unknown publication status
25. unknown retraction status
26. abstract-only limitation preservation
27. untraceable evidence rejection
28. cross-run evidence rejection
29. cross-run alignment rejection
30. incomplete Phase 2D run
31. Phase 2D pair-limit blocked
32. checkpoint resume
33. rerun idempotency
34. duplicate assessment prevention
35. ProjectState immutability
36. Phase 2C immutability
37. Phase 2D immutability
38. Arabic scientific evidence
39. mixed Arabic/English technical evidence
40. same evidence aligned differently to different claims
41. contradiction only on one claim component
42. support on one component, missing evidence on another
43. all components supported by same single source
44. all components supported across independent sources
45. source with multiple provider observations
46. missing DOI but same canonical source identity
47. unknown quality must not become favorable
48. deterministic reason-code correctness

Do not pad with trivial duplicates.

---

# 30. EVAL HONESTY

Offline Gold tests may use synthetic structured Phase 2C/2D records.

Do not report deterministic policy tests as proof of scientific validity.

The eval proves:
- policy behavior
- independence handling
- duplicate control
- sufficiency contract correctness
- provenance safety
- immutability
- deterministic aggregation
- versioning
- language/data handling

If no live model call is required by architecture, no Phase 2E live LLM eval is necessary.

Do not invent one for completeness.

---

# 31. QUALITY METRICS

At minimum measure:
- canonical independence grouping accuracy
- duplicate-source collapse accuracy
- claim-component coverage accuracy
- contribution classification accuracy
- sufficiency outcome contract accuracy
- contradiction preservation accuracy
- retraction handling accuracy
- unknown-state preservation accuracy
- assessment traceability
- deterministic rerun/idempotency accuracy
- per-language outcome accuracy

No-denominator subgroup metrics must be `None` / `not measured`.

Provide per-language metrics for:
- English
- Arabic
- mixed

---

# 32. RELEASE-BLOCKING SAFETY GATES

All applicable gates must be zero.

At minimum include:

1. ProjectState mutation
2. claim mutation
3. claim-status mutation
4. claim-confidence mutation
5. claim evidence-reference mutation
6. claim counter-evidence-reference mutation
7. score mutation
8. TrustGate mutation
9. evaluation-status mutation
10. Phase 2C ExtractedEvidence mutation
11. Phase 2D alignment mutation
12. automatic claim-status update
13. automatic score update
14. invalid claim-reference acceptance
15. invalid evidence-reference acceptance
16. invalid alignment-reference acceptance
17. cross-run evidence acceptance
18. cross-run alignment acceptance
19. untraceable evidence contribution
20. retracted evidence counted as normal positive corroboration
21. duplicate logical source counted as independent corroboration
22. duplicate excerpt counted as independent corroboration
23. provider observation counted as independent study
24. context-only evidence counted as direct support
25. insufficient evidence counted as direct support
26. not-relevant evidence counted as direct support
27. unknown quality treated as favorable known quality
28. incomplete Phase 2D run treated as complete
29. pair-limit-blocked Phase 2D treated as complete
30. contradictory evidence silently discarded
31. incompatible duplicate assessment acceptance
32. sufficiency assessment used to mutate TrustGate
33. sufficiency assessment used to mutate final project score

If any release-blocking gate is nonzero:
`BLOCKED`

Report every gate individually in the final report.

---

# 33. CRITICAL INVARIANTS

`More excerpts ≠ More independent sources`

`More providers ≠ More independent studies`

`Same source twice ≠ Corroboration`

`Context ≠ Support`

`Relevant ≠ Sufficient`

`Preprint ≠ Peer-reviewed by assumption`

`Unknown ≠ Favorable`

`Retracted ≠ Normal positive evidence`

`Contradiction must not be averaged away`

`Compound claim support requires component coverage`

`Claim sufficiency ≠ Claim status mutation`

`Claim sufficiency ≠ Project score`

`Claim sufficiency ≠ TrustGate result`

---

# 34. DOCUMENTATION

Add/update:
- Phase 2E architecture documentation
- system architecture overview
- one ADR establishing:

`Evidence Sufficiency Is Multi-Dimensional and Must Not Collapse Into an Opaque Weight`

The ADR must explain:
- why source quality and semantic relation remain separate
- why independence grouping is required
- why provider duplication cannot increase corroboration
- why unknowns remain explicit
- why Phase 2E does not mutate ClaimRecord
- why Phase 2E does not produce project scoring
- current abstract-only limitation

Use English for developer documentation.

Arabic is allowed as student/source/eval data.

Preserve language policy.

---

# 35. TARGETED TEST STRATEGY

During implementation run only the smallest relevant tests first.

Expected targeted areas:
- Phase 2E schemas
- source-quality profile
- independence grouping
- DOI/strong-identifier duplicate collapse
- provider-observation duplicate handling
- same-source multiple-excerpt handling
- contribution classification
- component coverage
- sufficiency policy
- contradiction preservation
- unknown handling
- retraction/preprint behavior
- cross-run isolation
- no-input/not-ready states
- ProjectState immutability
- Phase 2C immutability
- Phase 2D immutability
- checkpoint/idempotency
- Gold dataset invariants
- per-language metrics
- all release-blocking gates

Do not start with the full repository suite.

---

# 36. PHASE-SPECIFIC RELEASE TEST

After targeted tests pass:

1. run all Phase 2E test modules
2. run Phase 2E offline eval CLI

Required:
- Phase 2E eval = PASS
- all release-blocking safety gates = zero
- no errored Gold cases
- all Gold coverage minimums satisfied

---

# 37. REQUIRED CROSS-PHASE REGRESSION

After Phase 2E passes, run once:

1. Phase 2D claim-evidence alignment eval
2. Phase 2C evidence extraction eval
3. Phase 2B academic research eval
4. Phase 2A research eval
5. Phase 1 eval

Do not rerun repeatedly unless a subsequent fix could reasonably affect them.

All required regressions must PASS.

---

# 38. FINAL FULL-SUITE RELEASE GATE

Only after:
- targeted tests pass
- Phase 2E tests pass
- Phase 2E eval passes
- cross-phase regressions pass

run the full repository suite once.

On Windows use the repository venv interpreter if PowerShell activation is blocked:

`.venv\Scripts\python.exe -m pytest`

Required:
- 0 failed

Report exact passed/skipped/failed counts.

Do not invent an expected count.

---

# 39. GIT DISCIPLINE

Work only on:
`feat/phase2e-claim-sufficiency-weighting`

Do not merge into `main`.

Do not force-push.

Do not rewrite Phase 2D history.

Do not create an additional worktree.

Do not commit:
- `.idea/`
- `.claude/`
- Graphify output
- caches
- temporary logs
- unrelated files

Prefer one clean implementation commit or a small number of logically justified commits.

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

## Phase 2E Result

## Starting Git State

## Architecture Implemented

Explain ownership and why canonical claims/project state are not mutated.

## Evidence Weight Model

List dimensions and explain why no opaque scalar is used.

## Source Quality

Report retraction, publication/preprint, traceability, and abstract-only handling.

## Independence / Duplicate Control

Explain canonical grouping and how provider/excerpt duplication cannot inflate corroboration.

## Contribution Classification

## Claim Component Coverage

## Sufficiency Policy

State exact versioned deterministic policy.

## Sufficiency Outcomes

List final taxonomy and semantics.

## Unknown / Not-Measured Handling

## Retracted / Preprint Handling

## Immutability

Report populated ProjectState, Phase 2C, and Phase 2D preservation.

## Checkpoint / Idempotency

## Gold Dataset

Report:
- total
- English
- Arabic
- mixed
- per-outcome coverage
- adversarial category coverage

## Per-Language Metrics

## Quality Metrics

## Safety Gates

List every release-blocking gate individually with:
- metric name
- numerator
- denominator
- violation count/rate

## Phase 2E Eval

## Cross-Phase Regression

Report Phase 2D, 2C, 2B, 2A, and Phase 1 separately.

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
- abstract-only scientific-content limitation
- sufficiency is policy-based and auditable, not universal scientific proof
- unknown metadata remains unknown
- Phase 2E does not produce final project scoring

## Regression Status

## Status

Use exactly one:

`READY TO MERGE PHASE 2E`

or

`BLOCKED`

Then STOP.

Do not merge into main.

Do not start Phase 2F.
