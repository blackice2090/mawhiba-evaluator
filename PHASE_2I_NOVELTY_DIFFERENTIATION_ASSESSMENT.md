# PHASE 2I — NOVELTY & DIFFERENTIATION ASSESSMENT

## EXECUTION DISCIPLINE — APPLY TO THIS PHASE

Treat this as a high-trust semantic comparison and synthesis phase.

Phase 2I consumes the bounded, provenance-preserving prior-art candidate sets produced by:
- Phase 2G — patent prior-art research
- Phase 2H — product + open-source prior-art research

and determines the technical overlap and differentiation posture of the student's existing technical claims against those candidates.

This Phase does NOT determine legal novelty, patentability, infringement, freedom to operate, copying/plagiarism, official Mawhiba/Ibdaa scoring, or final project quality.

Governing distinction:

`Technical comparison ≠ Legal novelty conclusion`

---

# A. CONTEXT BUDGET DISCIPLINE — MANDATORY

Before starting:

`/clear`
`/model opus`

Use Opus for:
- comparison architecture
- feature/claim decomposition semantics
- candidate-source trust semantics
- chronology/cutoff semantics
- candidate independence semantics
- overlap/differentiation taxonomy
- deterministic synthesis policy
- difficult semantic debugging only

Once the architecture, schemas, comparison taxonomy, source-trust rules, and deterministic synthesis policy are stable, explicitly report:

`OPUS ARCHITECTURE COMPLETE — SAFE TO SWITCH TO SONNET`

if remaining work is primarily implementation/testing.

Do not remain on Opus merely because the Phase is long.

Context checkpoints:
1. after architecture + source-trust gate
2. after schemas/comparison engine compile and targeted tests pass
3. before Gold/eval implementation if context has grown materially
4. before cross-phase regression
5. before final full-suite gate

Guideline:
- `<60%`: continue normally
- `60–70%`: minimize rereads and output
- `70–80%`: complete current logical block, checkpoint, then `/compact`
- `80–90%`: do not begin a substantial new block without compacting
- `>90%`: STOP at a safe checkpoint

If Claude cannot invoke `/compact`, print:

`CONTEXT CHECKPOINT — RUN /compact NOW`

with:
- branch
- HEAD
- implemented areas
- tests actually run
- remaining work
- modified files
- next exact step

Then wait for the user to run `/compact`.

Do not reduce required testing to save context.

Use concise test/eval output.
Do not dump large candidate payloads, Gold files, or full source snapshots.

---

# B. GENERAL EXECUTION RULES

- Keep scope strictly limited to Phase 2I.
- Use the primary Claude Code session.
- Do not delegate the complete Phase or major areas to Agents/Subagents.
- Do not create additional Git worktrees.
- Reuse existing ResearchRun, schemas, model abstraction, exact-anchor validators, serializer/checkpoint patterns, provenance contracts, and eval architecture.
- Reuse Phase 2E material component inventory where structurally appropriate.
- Reuse Phase 2G patent-family grouping and Phase 2H product/repository-network grouping.
- Do not redesign Phases 2A–2H.
- Use the smallest correct architectural extension.
- Do not weaken tests, validators, schemas, referential integrity, eval denominators, metrics, safety gates, or assertions.
- Do not convert failures into skips.
- If a genuine architecture conflict appears, STOP and report it.
- Do not merge into `main`.
- Do not start project-level scoring, methodology quality, red-team scoring, or final evaluation.
- Do not mutate claims, canonical evidence, project ScoreRecords, prior Phase outputs, TrustGate, or evaluation status.
- Do not produce a legal novelty verdict or legal prior-art conclusion.

Required progression:

`baseline verification`
→ `architecture/source-trust gate`
→ `implementation`
→ `smallest targeted tests`
→ `Phase 2I tests/eval`
→ `required cross-phase regression`
→ `one final full-suite release gate`
→ `Git verification`
→ `STOP`

---

# 1. BASELINE AND GIT

Before modifying code, verify:
1. current branch
2. current HEAD
3. tracked working tree state
4. worktrees
5. Phase 2H merge state
6. Phase 2H feature commit `6976fb8` is an ancestor of `main`
7. Phase 2G and Phase 2H schemas/runs exist
8. no unresolved Phase 2H release work remains

Expected release lineage includes:
- `83cb0cc` — Phase 2H implementation
- `a75df48` — Phase 2H.1 product identity + DNS-rebinding hardening
- `6976fb8` — Phase 2H.1A safety-gate denominator integrity

The user previously verified Phase 2H feature-branch full suite:
- 2096 passed
- 31 skipped
- 0 failed

Do not assume Phase 2H is merged merely because feature commits exist.

If `main` does not contain `6976fb8`, STOP and report:

`BASELINE BLOCKED — PHASE 2H NOT MERGED INTO MAIN`

Do not merge it automatically.

If baseline is correct, create:

`feat/phase2i-novelty-differentiation`

Do not create another worktree.

---

# 2. PHASE OBJECTIVE

Implement:

`Existing Technical Claims`
+ `Phase 2E Material Component Inventory`
+ `Phase 2G Patent Candidates`
+ `Phase 2H Product Candidates`
+ `Phase 2H Open-Source Candidates`

→ `Comparison Feature Inventory`
→ `Candidate Disclosure Evidence`
→ `Claim–Candidate Technical Comparison`
→ `Independent Candidate Grouping`
→ `Differentiating Feature Analysis`
→ `Claim-Level Technical Novelty/Differentiation Posture`
→ `Project-Level Descriptive Synthesis`
→ `STOP`

Phase 2I answers:

> Within the bounded candidate set already discovered, which technical features and combinations appear disclosed, partially disclosed, unresolved, or not found, and what differentiating features remain relative to those candidates?

It does NOT answer:
- Is this invention legally novel?
- Is this patentable?
- Does this candidate invalidate a patent?
- Did the student copy this?
- Is this the same invention?
- What score should Mawhiba give?
- Should the project win?

---

# 3. CORE TRUST BOUNDARIES

`Candidate discovered ≠ Candidate technically relevant`

`Candidate technically relevant ≠ Feature disclosed`

`Feature disclosed ≠ Entire claim disclosed`

`Same component ≠ Same combination`

`Same goal ≠ Same mechanism`

`Same mechanism ≠ Same arrangement`

`Shared terminology ≠ Technical equivalence`

`High overlap ≠ Same invention`

`Material overlap ≠ Legal anticipation`

`No material overlap found ≠ Novel`

`No candidate found ≠ Novel`

`Bounded search ≠ Exhaustive search`

`Published before cutoff ≠ Legal prior-art ruling`

`Product available today ≠ Historically available before cutoff`

`Repository created_at ≠ Proven public-since`

`Commit date ≠ Proven public availability`

`Patent family members ≠ Independent inventions`

`Product listings ≠ Independent products`

`Repository forks/mirrors ≠ Independent root implementations`

`Technical overlap ratio ≠ Truth probability`

`Technical overlap ratio ≠ Patentability score`

`Technical overlap ratio ≠ Project score`

---

# 4. ARCHITECTURE GATE — OPUS MUST RESOLVE BEFORE CODING

Inspect only the minimum relevant architecture and resolve:
1. ResearchRun ownership
2. Phase 2I run structure
3. claim/component input contract
4. comparison feature inventory
5. candidate-source eligibility
6. candidate source-quality profile
7. exact candidate evidence-anchor contract
8. model-assisted semantic comparison contract
9. deterministic verification
10. full-claim vs component-level comparison
11. combination/relationship-feature semantics
12. overlap taxonomy
13. differentiation taxonomy
14. candidate independence groups
15. chronology/cutoff use
16. source-type differences
17. bounded comparison budget
18. deterministic synthesis
19. claim-level posture taxonomy
20. project-level descriptive synthesis
21. checkpoint/idempotency
22. immutability
23. exact boundary before scoring/legal conclusions

If coherent, proceed.

If resolving any of these requires modifying the meaning of Phase 2E, 2G, or 2H records, STOP and report the conflict instead of silently mutating old contracts.

---

# 5. OWNERSHIP

Phase 2I output belongs on `ResearchRun`.

Add a dedicated typed run, e.g.:
`novelty_differentiation`

with explicit schema/version.

Do NOT place Phase 2I results into:
- ClaimRecord status/confidence
- canonical EvidenceRecord
- ProjectState.scores
- TrustGate
- evaluation_status

Do NOT mutate Phase 2G or Phase 2H candidate records.

---

# 6. INPUT ELIGIBILITY

A claim is eligible only when:
- it exists canonically
- it has a stable claim ID
- provenance is valid
- Phase 2E component inventory is structurally usable, or the run records why component-level comparison is unavailable

Do not fabricate missing claims or repair upstream claim text.

If inventory is incomplete/unknown:
- permit conservative full-claim comparison where possible
- withhold strong differentiation synthesis
- record the limitation

---

# 7. COMPARISON FEATURE INVENTORY

Phase 2E's covering component inventory is the starting structural partition.

Phase 2I may add a separate typed `ComparisonFeatureInventory` without mutating Phase 2E.

Distinguish where deterministically supported:
- COMPONENT
- FUNCTION
- MECHANISM
- RELATIONSHIP
- SEQUENCE
- CONSTRAINT
- COMBINATION
- OTHER_TECHNICAL_FEATURE

Every feature must have:
- feature ID
- claim ID
- feature type
- exact claim-text anchor(s)
- offsets / deterministic traceability
- source component IDs where applicable
- materiality status
- derivation provenance
- verification status

No free-floating paraphrases without exact claim anchors.

---

# 8. RELATIONSHIP / COMBINATION FEATURES

Novelty/differentiation cannot be reduced to a bag of components.

`A + B + C` is not necessarily equivalent to A, B, and C existing independently.

Explicitly represent materially stated relationships/arrangements.

A candidate that discloses all components independently but not the claimed relationship/combination must NOT be classified as full-claim disclosure.

Required invariant:

`All components found ≠ Claimed combination found`

---

# 9. MODEL-ASSISTED FEATURE EXTRACTION

If semantic feature decomposition uses an LLM:
- use existing trusted provider abstraction
- use Structured Outputs / typed schema
- model output is untrusted
- every feature maps to exact claim text
- reject fabricated anchors
- reject missing material text
- record prompt/version/model provenance
- treat prompt injection as inert data
- never mutate canonical claim

Deterministic validation decides admissibility.

---

# 10. CANDIDATE TYPES

Consume three distinct families:
1. PatentPriorArtCandidate
2. ProductPriorArtCandidate
3. OpenSourcePriorArtCandidate

Do not flatten them into a weak generic source type.

Preserve identity, chronology, source-content, independence-group, and limitation semantics.

---

# 11. CANDIDATE COMPARISON ELIGIBILITY

Explicit statuses should include concepts such as:
- ELIGIBLE_FOR_TECHNICAL_COMPARISON
- LIMITED_TEXT_COMPARISON
- METADATA_ONLY_NOT_COMPARABLE
- CONTENT_UNAVAILABLE
- BLOCKED_SOURCE_QUALITY
- INVALID_CANDIDATE_REFERENCE

Search snippets alone are not sufficient for material technical disclosure.

Titles alone are not sufficient.

Provider rank is irrelevant.

---

# 12. SOURCE-TYPE DISCLOSURE POLICY

## Patent
Preferred:
- claims
- description
- abstract
- title

Do not treat title-only text as material disclosure.

Abstract-only disclosure may support overlap with an abstract-scope limitation.

Patent-family identity prevents family inflation.

## Product
Preferred:
- verified first-party technical documentation
- first-party product page with technical details
- first-party press/release material
- marketplace/third-party content only with explicit limitations

Marketing text cannot silently become precise engineering disclosure.

Current availability does not prove historical availability.

## Open source
Preferred:
- verified full repository file snapshot
- relevant manifest/package metadata
- README/documentation
- release metadata
- code-search fragment

Code-search fragment is not a full-file disclosure.

README claims are documentation claims unless corroborated by implementation snapshots.

Repository-network grouping prevents fork/mirror inflation.

---

# 13. CANDIDATE SOURCE QUALITY PROFILE

Use a structured, non-scalar profile.

Example dimensions:
- identity_verified
- source_role
- content_scope
- exact_text_available
- full_vs_partial_snapshot
- chronology_known
- historical_visibility_proven
- candidate_group_resolved
- source_limitations

Do not create a source-quality score.

---

# 14. CANDIDATE EVIDENCE ANCHORS

Every material candidate-disclosure assertion requires exact source support.

Typed anchor should include:
- candidate ID
- candidate type
- snapshot/artifact ID
- content type
- exact source excerpt
- exact offsets or deterministic match location
- content hash
- provenance
- language
- truncation status
- verification status

No exact anchor → no verified disclosure assertion.

---

# 15. CLAIM–CANDIDATE FEATURE RELATION TAXONOMY

Use a finite taxonomy such as:
- DISCLOSED
- PARTIALLY_DISCLOSED
- RELATED_CONTEXT
- NOT_DISCLOSED
- INSUFFICIENT_SOURCE_TEXT
- NOT_COMPARABLE

`NOT_DISCLOSED` means not disclosed in the verified candidate text actually compared.

It does NOT mean absent from the real-world artifact in all forms.

---

# 16. FULL-CLAIM / COMBINATION RELATION

In addition to per-feature relations, determine whether a single candidate supports:
- FULL_CLAIM_TECHNICAL_OVERLAP
- PARTIAL_CLAIM_TECHNICAL_OVERLAP
- COMPONENT_ONLY_OVERLAP
- CONTEXT_ONLY
- NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT
- INSUFFICIENT_SOURCE_TEXT

Full-claim overlap requires material relationships/combination, not just matching nouns/components.

---

# 17. MODEL-ASSISTED SEMANTIC COMPARISON

Required chain:

`Verified Candidate Content`
+ `Exact Claim/Feature`
→ `Untrusted Structured Comparison`
→ `Deterministic Anchor/Reference Validation`
→ `Verified Comparison Record`

Model output must include exact candidate excerpts for every claimed disclosure.

Reject:
- fabricated excerpts
- wrong snapshot IDs
- text not present
- cross-candidate evidence mixing
- claim text used as candidate evidence
- unsupported full-overlap conclusion
- prompt-injection-following behavior

---

# 18. NUMERIC SIMILARITY / EMBEDDINGS

Do NOT introduce semantic similarity as a novelty score.

If embeddings/lexical similarity are used for bounded triage:
- record only as retrieval/triage metadata
- never call it novelty probability
- never let it become final posture directly
- never override verified disclosure anchors

Prefer provenance-linked candidate sets over opaque ranking.

---

# 19. COMPARISON BOUNDEDNESS

Create explicit settings for:
- max candidates per claim
- max patent groups per claim
- max product groups per claim
- max OSS networks per claim
- max snapshots per candidate
- max bytes/text per comparison
- max model comparisons
- timeout/retry limits

Selection must preserve provenance and candidate-type diversity.

Do not silently drop candidates.

Record:
- available candidates
- eligible candidates
- compared candidates
- omitted by limit
- blocked by source quality
- failed comparisons

Coverage concepts:
- COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS
- PARTIAL_COMPARISON_LIMIT
- PARTIAL_SOURCE_UNAVAILABLE
- PARTIAL_ERROR
- NOT_EXECUTED

Never call partial comparison complete.

---

# 20. CANDIDATE INDEPENDENCE GROUPS

## Patent
independence unit = verified patent family/group from Phase 2G.

## Product
independence unit = verified strong product entity where resolved.

Probable/duplicate-content relations must not be blindly counted as independent corroboration.

## Open source
independence unit = repository network/root from Phase 2H.

Do not create one cross-type independence count pretending these evidence classes are equivalent.

---

# 21. CHRONOLOGY AND CUTOFF

Technical comparison is separate from chronology.

Compare relevant candidates even if:
- before cutoff
- on cutoff
- after cutoff
- unknown date
- no cutoff

Preserve chronology buckets.

Later/unknown candidates can inform differentiation/current landscape but cannot support a before-cutoff disclosure statement.

---

# 22. HISTORICAL-VISIBILITY LIMITS

Carry forward:
- product current-page existence does not prove past availability
- GitHub created_at does not prove public visibility from creation
- commit date does not prove public availability
- patent publication date is chronology, but Phase 2I makes no legal invalidating-prior-art ruling

---

# 23. DIFFERENTIATING FEATURE ANALYSIS

For each claim identify features:
- DISCLOSED_BY_ONE_OR_MORE_COMPARED_CANDIDATES
- PARTIALLY_DISCLOSED
- NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT
- UNRESOLVED_DUE_TO_SOURCE_LIMITATIONS

Preferred wording:

`Differentiating relative to the compared bounded candidate set`

Do not label `NOT_FOUND...` as unique, novel, unprecedented, or first without explicit qualification.

---

# 24. CLAIM-LEVEL TECHNICAL POSTURE

Recommended descriptive taxonomy:
- MATERIAL_TECHNICAL_OVERLAP_FOUND
- PARTIAL_TECHNICAL_OVERLAP_ONLY
- NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS
- MIXED_OVERLAP_AND_DIFFERENTIATION
- INSUFFICIENT_COMPARISON_EVIDENCE
- BLOCKED_SOURCE_QUALITY

Do not use:
- NOVEL
- NOT_NOVEL
- ANTICIPATED
- INVALID
- PATENTABLE
- UNPATENTABLE

Posture must be deterministically synthesized from verified comparison records and coverage.

---

# 25. MATERIAL OVERLAP POLICY

`MATERIAL_TECHNICAL_OVERLAP_FOUND` requires:
- material claim features substantially disclosed
- material relationships/combination supported
- exact candidate anchors
- sufficient source-content eligibility
- no critical unresolved feature caused merely by unavailable source text

Title/metadata/context-only matches cannot trigger material overlap.

---

# 26. NO-MATERIAL-OVERLAP POLICY

`NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS` only when:
- comparison coverage is sufficiently complete within configured bounds
- source text is adequate
- no candidate has verified material/full-claim overlap

It must still carry:
- bounded-search limitation
- bounded-comparison limitation
- no-legal-novelty limitation

Partial/weak coverage must yield an insufficient/blocked posture instead.

---

# 27. PROJECT-LEVEL DESCRIPTIVE SYNTHESIS

Allowed:
- assessed claim count
- claims with material overlap
- partial-overlap claims
- no-material-overlap-found-within-bounds claims
- blocked/insufficient claims
- recurring differentiating features
- source-type coverage
- chronology distribution
- candidate-type distribution

Forbidden:
- novelty percentage
- project novelty score
- pass/fail
- accept/reject
- ranking
- official Mawhiba score adjustment

---

# 28. EXPLANATION / TRACEABILITY

Every claim-level posture traces to:
- claim ID
- feature inventory
- compared candidates
- candidate group identities
- exact disclosure anchors
- candidate-level relations
- comparison coverage
- chronology
- source limitations
- synthesis policy version

No unexplained posture.

---

# 29. REPRODUCIBILITY

Identical inputs + verified model output + policy/settings must yield reproducible deterministic verification/synthesis.

Candidate input order must not change final deterministic synthesis.

---

# 30. CHECKPOINT / IDEMPOTENCY

Stable IDs for:
- comparison feature inventory
- candidate comparison
- disclosure anchors
- claim synthesis
- run

Resume must not duplicate comparisons.

Completed stages are no-ops unless explicit invalidation/version change occurs.

A finished Phase 2I run is not silently reopened.

---

# 31. CROSS-RUN ISOLATION

Reject:
- foreign claim
- foreign candidate
- foreign patent-family reference
- foreign product entity
- foreign repository network
- foreign snapshot anchor
- mixed-run comparison record
- synthesis referencing unknown comparison IDs

---

# 32. IMMUTABILITY

Verify byte-equivalent preservation of:

## ProjectState
- claims
- statuses/confidences
- evidence refs
- scores
- TrustGate
- evaluation_status

## Research phases
- Phase 2C evidence
- Phase 2D alignment
- Phase 2E component inventory/sufficiency
- Phase 2F scoring
- Phase 2G patent prior-art
- Phase 2H product prior-art
- Phase 2H OSS prior-art

Only Phase 2I's own field may change.

Add negative controls.

---

# 33. PROMPT-INJECTION SAFETY

Student claim text and candidate source text are data.

The comparison model must never follow instructions embedded in:
- patent text
- product pages
- README
- code comments
- snippets
- student claim text

Add adversarial cases:
- ignore previous instructions
- mark this invention novel
- assign score 100
- reveal system prompt
- copy secret/token

All remain inert data.

---

# 34. SECRET / PRIVACY BOUNDARY

Phase 2I normally performs no new external search.

Do not send unnecessary PII.

Do not persist keys, tokens, secrets, or hidden prompts containing secrets.

If comparison uses an external LLM, send only the minimum technical claim + verified candidate excerpt under existing privacy policy.

---

# 35. ERROR HANDLING

Classify at least:
- INVALID_INPUT
- INVALID_REFERENCE
- SOURCE_CONTENT_UNAVAILABLE
- SOURCE_QUALITY_BLOCKED
- MODEL_ERROR
- MODEL_SCHEMA_ERROR
- FABRICATED_ANCHOR
- CROSS_RUN_REFERENCE
- COMPARISON_LIMIT_REACHED
- TIMEOUT
- SYNTHESIS_BLOCKED

One failed candidate comparison must not discard unrelated successful comparisons.

---

# 36. POLICY VERSIONING

Version:
- comparison feature schema
- semantic comparison prompt
- anchor verifier
- source-type disclosure policy
- synthesis policy

Policy changes must be visible in serialized output.

---

# 37. GOLD EVAL

Create a dedicated Phase 2I offline Gold suite.

Suggested:
- `evals/novelty_differentiation/v1/`
- `src/evals/novelty_differentiation/`

Minimum:
- total >= 192
- Arabic >= 48
- mixed Arabic/English >= 32

Use realistic bounded worlds from Phase 2G + Phase 2H fixtures.

No ordinary eval may depend on live providers.

---

# 38. REQUIRED GOLD CATEGORIES

Cover at least 80 categories spanning:

## Feature inventory
1. simple component claim
2. function feature
3. mechanism feature
4. relationship feature
5. sequence feature
6. constraint feature
7. combination feature
8. incomplete Phase 2E inventory
9. fabricated feature anchor rejected
10. uncovered material relationship rejected
11. Arabic extraction
12. mixed-language extraction

## Patent
13. claims disclose component
14. description discloses mechanism
15. abstract-only partial overlap
16. title-only not material disclosure
17. family anti-inflation
18. pre-cutoff chronology
19. post-cutoff compared but isolated temporally
20. publication date unknown

## Product
21. first-party technical docs disclose component
22. marketing-only limited
23. marketplace limited
24. current page not historical proof
25. strong entity grouping
26. duplicate-content link no inflation
27. unresolved identity conservative
28. before/on/after cutoff

## Open source
29. full file discloses implementation
30. README-only limited
31. code fragment limited
32. manifest/package evidence
33. fork/network anti-inflation
34. mirror anti-inflation
35. rename preserves identity
36. created_at not public-since
37. commit date not public-availability proof
38. release chronology

## Technical semantics
39. same component different mechanism
40. same goal different mechanism
41. all components wrong relationship
42. all components wrong sequence
43. all components missing constraint
44. partial disclosure
45. context only
46. no material overlap in compared text
47. insufficient source text
48. contradictory/ambiguous candidate
49. cross-candidate mosaic not single-candidate full overlap
50. two candidates cover halves
51. one candidate covers whole combination
52. synonym with exact source anchor

## Differentiation
53. one differentiating feature
54. multiple differentiating features
55. all features materially overlap
56. unresolved due missing source
57. bounded no-overlap posture
58. partial coverage cannot become no-overlap posture
59. post-cutoff overlap not pre-cutoff disclosure
60. chronology unknown

## Safety/state
61. no NOVEL verdict
62. no NOT_NOVEL verdict
63. no patentability verdict
64. no infringement/FTO
65. no plagiarism/copying
66. no project score
67. no claim-status mutation
68. no Phase 2F mutation
69. no TrustGate mutation
70. no Phase 2G mutation
71. no Phase 2H mutation
72. prompt injection inert
73. fabricated candidate excerpt rejected
74. wrong snapshot rejected
75. cross-candidate evidence mixing rejected
76. cross-run candidate rejected
77. input-order invariance
78. checkpoint idempotency
79. comparison-limit partial status
80. source-quality blocked posture

Do not pad with trivial duplicates.

---

# 39. QUALITY METRICS

Measure at least:
- feature_inventory_traceability
- feature_inventory_material_coverage
- relationship_feature_accuracy
- candidate_eligibility_accuracy
- candidate_anchor_accuracy
- patent_disclosure_accuracy
- product_disclosure_accuracy
- oss_disclosure_accuracy
- source_scope_accuracy
- component_relation_accuracy
- combination_relation_accuracy
- full_claim_relation_accuracy
- candidate_independence_accuracy
- chronology_separation_accuracy
- cutoff_handling_accuracy
- differentiating_feature_accuracy
- claim_posture_accuracy
- boundedness_accuracy
- idempotency_accuracy
- cross_run_isolation_accuracy
- immutability_accuracy
- prompt_injection_resistance
- legal_boundary_accuracy
- per_language_contract_accuracy

No denominator → `None / not measured`.

Do not fabricate coverage.

---

# 40. RELEASE-BLOCKING SAFETY GATES

All must be zero.

At minimum:
1. ProjectState mutation
2. claim mutation
3. claim-status mutation
4. claim-confidence mutation
5. evidence-reference mutation
6. project-score mutation
7. TrustGate mutation
8. evaluation-status mutation
9. Phase 2C mutation
10. Phase 2D mutation
11. Phase 2E mutation
12. Phase 2F mutation
13. Phase 2G mutation
14. Phase 2H product mutation
15. Phase 2H OSS mutation
16. fabricated claim feature accepted
17. uncovered material relationship ignored
18. fabricated candidate excerpt accepted
19. wrong snapshot anchor accepted
20. search snippet used as material product disclosure
21. patent title used as material disclosure
22. product title used as material disclosure
23. OSS title/description alone used as implementation proof
24. code fragment treated as full-file disclosure
25. README treated as code implementation proof
26. candidate identity lost
27. patent family inflated count
28. product listing inflated count
29. fork inflated count
30. mirror inflated count
31. cross-candidate mosaic reported single-candidate full overlap
32. all-components-without-relationship reported full overlap
33. same-goal-only reported material overlap
34. shared-terminology-only reported material overlap
35. provider rank affects posture
36. popularity affects posture
37. numeric similarity represented as novelty probability
38. post-cutoff represented as pre-cutoff disclosure
39. unknown chronology represented before cutoff
40. current product page represented historical proof
41. GitHub created_at represented public-since
42. commit date represented public-availability proof
43. partial comparison reported complete
44. source-unavailable comparison reported negative disclosure
45. source-quality-blocked candidate reported full overlap
46. no-candidate-found reported NOVEL
47. bounded no-overlap reported worldwide novelty
48. material overlap reported legal anticipation
49. legal prior-art conclusion produced
50. NOVEL verdict produced
51. NOT_NOVEL verdict produced
52. patentability conclusion produced
53. infringement/FTO conclusion produced
54. copying/plagiarism conclusion produced
55. project novelty score produced
56. official/project score mutation
57. automatic claim-status update
58. automatic Phase 2F score update
59. cross-run claim accepted
60. cross-run patent candidate accepted
61. cross-run product candidate accepted
62. cross-run OSS candidate accepted
63. cross-run snapshot accepted
64. unknown comparison ID accepted in synthesis
65. duplicate comparison inflated synthesis
66. candidate input order changes synthesis
67. checkpoint replay duplicates comparison
68. prompt injection followed
69. candidate text treated as system instruction
70. student text treated as system instruction
71. provider credential persisted
72. hidden score/opaque scalar added
73. source quality collapsed into opaque numeric weight
74. candidate-type semantics conflated
75. bounded-comparison limitation omitted
76. no-legal-novelty limitation omitted
77. final posture without traceable basis
78. model relation accepted without deterministic anchor validation

Each gate must have:
- meaningful denominator
- zero fabricated denominator floors
- negative control where practicable

A case with zero opportunities contributes zero.

No no-op gates.

---

# 41. NEGATIVE CONTROLS

At minimum prove the eval catches tampering for:
- fabricated claim feature
- fabricated candidate excerpt
- wrong candidate snapshot
- cross-candidate evidence mixing
- family inflation
- product listing inflation
- fork inflation
- missing relationship feature
- false full overlap
- false no-overlap under partial coverage
- post-cutoff mislabeled pre-cutoff
- current product page treated historical
- GitHub created_at treated public-since
- legal novelty verdict inserted
- hidden project score inserted
- Phase 2F mutation
- TrustGate mutation
- prompt injection compliance
- cross-run reference
- duplicate comparison
- input-order instability

Negative controls must actually fire.

---

# 42. DETERMINISTIC SYNTHESIS

The final claim posture must be synthesized in Python from verified comparison records.

Do not ask the model:

`Is this claim novel?`

The model may classify feature relations under exact-evidence constraints.

Python policy decides the descriptive posture.

---

# 43. NO OPAQUE NOVELTY SCORE

Do not create:
- novelty_score
- novelty_probability
- similarity-to-prior-art verdict score
- 0–100 novelty grade

If a structural ratio is necessary for diagnostics, it must:
- be explicitly named coverage/overlap ratio
- be secondary metadata
- never determine legal novelty
- never become project score
- never hide unresolved features or source limits

Prefer categorical vectors/counts.

---

# 44. OPTIONAL COMPARISON VECTOR

If useful:
- material_features_disclosed
- material_features_partial
- material_features_not_disclosed_in_compared_text
- material_features_unresolved
- relationship_features_disclosed
- relationship_features_unresolved
- source_scope
- chronology_bucket

Do not combine into one opaque scalar.

---

# 45. PROJECT SYNTHESIS LIMITATIONS

Every project summary must include equivalents of:
- bounded prior-art discovery
- bounded comparison
- source text may be incomplete
- product historical availability may be unknown
- OSS historical public visibility may be unknown
- patent family grouping is not legal equivalence
- product identity may remain unresolved
- forks may materially diverge
- absence of a found match is not proof of novelty
- technical overlap is not legal anticipation
- no patentability/infringement/FTO/copying conclusion
- no official/project score

---

# 46. DOCUMENTATION

Add/update:
- Phase 2I architecture doc
- comparison policy doc
- source-type disclosure policy
- developer architecture overview
- `CLAUDE.md`
- ADR:

`Technical Overlap and Differentiation Are Descriptive Evidence Postures, Not Legal Novelty Conclusions`

Explain:
- discovery vs comparison
- component vs combination overlap
- exact-evidence anchoring
- source-type differences
- candidate independence
- chronology limits
- bounded comparison
- no novelty score
- no legal verdict
- deterministic Python synthesis

Developer docs English.

Arabic only in student/source/eval data.

---

# 47. TARGETED TEST STRATEGY

Run smallest relevant tests first:
- feature inventory
- relationship/combination features
- exact anchors
- candidate eligibility
- patent/product/OSS source-scope policies
- candidate disclosure anchors
- model-output verification
- feature taxonomy
- full-claim relation
- independence grouping
- chronology/cutoff
- bounded comparison
- differentiation synthesis
- claim posture
- project descriptive synthesis
- prompt injection
- idempotency
- cross-run isolation
- immutability
- Gold invariants
- safety gates

Do not start with full suite.

---

# 48. PHASE-SPECIFIC RELEASE GATE

After targeted tests:
1. complete Phase 2I tests
2. Phase 2I offline Gold eval
3. model/provider contract tests if Phase 2I adds any prompt/provider contract

No live prior-art provider search is required in Phase 2I.

Required:
- eval PASS
- 0 errored Gold cases
- all quality thresholds met
- all gates zero
- negative controls fire
- dataset/language/category minimums met

---

# 49. REQUIRED CROSS-PHASE REGRESSION

After Phase 2I passes, run once:

1. Phase 2H product + OSS prior-art eval
2. Phase 2G patent prior-art eval
3. Phase 2F claim evidence scoring eval
4. Phase 2E sufficiency eval
5. Phase 2D alignment eval
6. Phase 2C evidence eval
7. Phase 2B academic eval
8. Phase 2A research eval
9. Phase 1 intake eval

All PASS.

Do not repeatedly rerun historical evals during implementation.

---

# 50. FINAL FULL-SUITE RELEASE GATE

Only after Phase 2I + regressions:

`.venv\Scripts\python.exe -m pytest`

Required:
- 0 failed

Report exact:
- passed
- skipped
- failed

Do not predict counts.

---

# 51. GIT DISCIPLINE

Work only on:

`feat/phase2i-novelty-differentiation`

Do not merge into main.
Do not force-push.
Do not rewrite Phase 2H history.
Do not create another worktree.

Do not commit:
- `.agents/`
- `.codex/`
- `AGENTS.md` unless explicitly project-owned
- `.idea/`
- `.claude/`
- graphify output
- caches
- temp logs
- API keys/tokens
- unrelated files

Verify branch/status/log/diff/worktrees before completion.

---

# 52. FINAL REPORT

Return final report in English only with exactly:

## Phase 2I Result

## Starting Git State

## Context / Model Usage

Report model usage and `/compact` checkpoints. Do not estimate token counts.

## Architecture Implemented

## Input Eligibility

## Comparison Feature Inventory

## Relationship / Combination Features

## Candidate Eligibility

## Source-Type Disclosure Policy

Separate patent/product/open source.

## Candidate Evidence Anchors

## Semantic Comparison

## Deterministic Verification

## Candidate Independence

## Chronology / Cutoff Handling

## Comparison Boundedness

## Differentiating Feature Analysis

## Claim-Level Technical Posture

## Project-Level Descriptive Synthesis

## Prompt-Injection Safety

## Checkpoint / Idempotency

## Cross-Run Isolation

## Immutability

## Gold Dataset

Report total, English, Arabic, mixed, category coverage, and patent/product/OSS coverage.

## Per-Language Metrics

## Quality Metrics

## Safety Gates

List every gate individually:
- violations
- actual denominator
- rate

No synthetic denominator floors.

## Negative Controls

## Phase 2I Eval

## Cross-Phase Regression

Report 2H, 2G, 2F, 2E, 2D, 2C, 2B, 2A, Phase 1 separately.

## Tests

Report exact passed/skipped/failed.

## Files Modified

## Git End State

Include branch, status, latest commits, `git diff --stat main...HEAD`, worktrees.

## Remaining Limitations

Explicitly include:
- bounded search is not exhaustive
- bounded comparison is not exhaustive
- no found overlap does not prove novelty
- technical overlap is not legal anticipation
- source content may be incomplete
- product historical availability may be unknown
- OSS historical public visibility may be unknown
- patent-family grouping is not legal equivalence
- product identity may be unresolved
- forks may materially diverge
- no patentability assessment
- no infringement/FTO assessment
- no copying/plagiarism assessment
- no project/official scoring

## Regression Status

## Status

Use exactly one:

`READY TO MERGE PHASE 2I`

or

`BLOCKED`

Then STOP.

Do not merge into main.

Do not start methodology assessment, red-team scoring, project-level scoring, or final evaluation.
