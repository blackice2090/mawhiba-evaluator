# PHASE 2G — PATENT PRIOR-ART RESEARCH FOUNDATION

## EXECUTION DISCIPLINE — APPLY TO THIS PHASE

Treat this as a high-trust patent-research architecture + implementation phase.

This Phase creates the patent prior-art research foundation. It does NOT decide novelty, patentability, infringement, freedom to operate, or legal prior-art status.

The goal is to create a reproducible, provenance-rich, family-aware patent search pipeline that discovers and verifies patent publications relevant to the student's technical claims without inflating duplicate family members or confusing dates.

### Core execution rules

- Keep scope strictly limited to Phase 2G.
- Use the primary Claude Code session for architecture, implementation, testing, regression, Git verification, and final reporting.
- Do NOT delegate the complete Phase or major Phase areas to Agents/Subagents.
- Do not create additional Git worktrees.
- Use a Subagent only for a narrowly scoped, read-only investigation that genuinely reduces context duplication.
- Inspect only repository surfaces required for this Phase.
- Prefer targeted search/navigation over broad recursive repository exploration.
- Reuse the existing ResearchRun, ResearchQueryRecord, provider abstractions, provenance patterns, source identity rules, serializer/checkpoint infrastructure, settings patterns, and eval architecture.
- Prefer the smallest correct architectural extension.
- Do not redesign Phase 2A–2F.
- Do not weaken tests, validators, assertions, schemas, referential integrity, metrics, eval denominators, safety gates, or release gates.
- Do not convert failures into skips.
- Do not silently broaden scope.
- If a genuine architecture conflict appears, STOP and report it.
- Do not merge into `main`.
- Do not start product/open-source prior-art research.
- Do not start novelty assessment.
- Do not produce legal conclusions.
- Do not mutate claim status, claim confidence, canonical evidence references, project scoring, Claim Evidence Scores, TrustGate, or final evaluation state.

### Required testing progression

`provider-contract verification`
→ `architecture verification`
→ `implementation`
→ `smallest targeted tests`
→ `fix targeted failures`
→ `rerun targeted tests`
→ `Phase 2G tests/eval`
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
- Phase 2F merged
- expected current main HEAD: `8165125`
- previous post-merge release gate:
  - 1771 passed
  - 25 skipped
  - 0 failed

Before modifying code:

1. verify current branch
2. verify working tree is clean
3. verify current HEAD
4. confirm the Phase 2A research foundation and PATENT branch taxonomy still exist
5. confirm Phase 2F contracts are present and untouched
6. create:

`feat/phase2g-patent-prior-art-research`

Do not use an additional worktree.

If the baseline materially differs, STOP and report the mismatch.

---

# 2. PROVIDER-CONTRACT GATE — VERIFY CURRENT OFFICIAL DOCUMENTATION FIRST

Patent APIs and access policies change.

Before coding a provider, verify its current contract against official provider documentation.

Record in developer documentation:

- provider
- official documentation URL
- verification date
- authentication method
- search endpoint/operation
- family endpoint/operation
- bibliographic endpoint/operation
- text/claims availability
- pagination/range semantics
- response format
- rate/fair-use constraints
- fields used by this Phase
- live contract actually observed vs documented-only

Do not rely on old blog posts, cached examples, third-party wrappers, or memory.

## Primary provider: EPO Open Patent Services (OPS)

Current official EPO documentation establishes that OPS:

- is an EPO machine-to-machine patent-data service
- uses REST-style services
- exposes raw EPO/DOCDB/INPADOC-related patent data
- uses OAuth credentials through the EPO developer portal
- supports bibliographic search and family services
- uses CQL for bibliographic searching
- returns XML
- has authority-dependent full-text/claims coverage

Verify the exact current endpoint paths and request/response contract from EPO official documentation before implementation.

Implement EPO OPS as the primary Phase 2G provider if the verified contract remains compatible.

## USPTO / PatentsView

Do NOT implement against an assumed legacy PatentsView API.

USPTO announced migration of PatentsView to the USPTO Open Data Portal in March 2026, with API/search functionality transitioning.

Treat USPTO ODP as a future/optional provider unless the current official API contract is clearly documented, stable, and useful for this Phase.

Do not block Phase 2G on USPTO ODP.

## WIPO PATENTSCOPE

Do NOT scrape or automate the public PATENTSCOPE search interface.

Official PATENTSCOPE guidance prohibits automated robots/bulk database downloading from the public search service, while separate programmatic data/document services have their own authorization/commercial terms.

PATENTSCOPE may be documented as a manual/reference research source but must not be implemented as an unauthorized automated search connector.

## Provider honesty

A provider must be classified as one of:

- IMPLEMENTED_AND_LIVE_VERIFIED
- IMPLEMENTED_DOCUMENTED_ONLY
- DEFERRED
- UNSUPPORTED_BY_ACCESS_POLICY

Never report a provider as live-tested unless a real authenticated request was executed successfully.

---

# 3. ARCHITECTURE GATE — OPUS MUST RESOLVE BEFORE CODING

Before implementation, inspect only the minimum relevant research schemas and produce a concise architecture decision covering:

1. Phase 2G state ownership
2. relationship to the existing PATENT research branch
3. query-planning ownership
4. provider observation vs logical patent publication identity
5. patent publication identity
6. patent family identity
7. text snapshot/provenance design
8. chronology/date semantics
9. time-qualification semantics
10. search-boundedness/completeness semantics
11. provider error/partial-result handling
12. exact boundary between candidate discovery and later novelty assessment
13. immutability boundaries

Proceed directly if compatible.

STOP only for a genuine architectural conflict.

---

# 4. PHASE OBJECTIVE

Implement:

`Technical Project Claims`
→ `Patent Search Query Plan`
→ `Provider Search Observations`
→ `Normalized Patent Publication Candidates`
→ `Verified Patent Publications`
→ `Patent Family Resolution`
→ `Chronology / Cutoff Qualification`
→ `Patent Prior-Art Candidates`
→ `STOP`

Phase 2G answers:

> What patent publications and patent families should a later novelty-analysis phase inspect, and what verified metadata/text/provenance do we have for them?

Phase 2G does NOT answer:

> Is the student's invention novel?

Phase 2G does NOT answer:

> Does a patent legally invalidate the student's invention?

Phase 2G does NOT answer:

> Is a claim patentable?

Preserve:

`Search hit ≠ Verified patent publication`

`Verified patent publication ≠ Same invention`

`Same patent family ≠ Multiple independent inventions`

`Similarity/relevance ≠ Novelty failure`

`Priority date ≠ Public availability date`

`Patent candidate ≠ Legal prior art conclusion`

---

# 5. OWNERSHIP

Phase 2G output must remain on the ResearchRun/research execution layer.

Use the existing PATENT research branch where compatible.

Create dedicated patent research state/run structures rather than writing patent candidates into canonical ProjectState evidence or scores.

Do NOT mutate:

- `ProjectState.claims`
- claim status/confidence
- claim evidence/counter-evidence references
- `ProjectState.evidence`
- `ProjectState.scores`
- Phase 2C evidence
- Phase 2D alignments
- Phase 2E sufficiency
- Phase 2F claim evidence scoring
- TrustGate
- evaluation_status

---

# 6. INPUT CONTRACT

Phase 2G may consume:

1. canonical project claims
2. Phase 2E claim component inventory where available
3. technical-domain information
4. canonical technical terms/technologies from intake
5. explicit search cutoff date if supplied by the research/evaluation workflow
6. existing ResearchQueryRecord conventions

Phase 2G must NOT:

- use Phase 2F score to decide whether a claim deserves patent search
- skip a technical claim merely because evidence support is low
- treat student novelty claims as established truth
- automatically infer a legal priority cutoff
- expose personal student data in provider queries

Every excluded claim/component must have an explicit machine-readable reason.

---

# 7. SEARCH CUTOFF SEMANTICS

Introduce an explicit optional:

`search_cutoff_date`

or repository-consistent equivalent.

This date means:

> the evaluation date before which publicly available patent publications are especially relevant for later comparison.

It is NOT automatically a legal patent-law novelty date.

If no cutoff is supplied:

- search still runs
- chronology is preserved
- no publication may be labeled `PUBLIC_BEFORE_CUTOFF` or `PUBLIC_AFTER_CUTOFF`
- cutoff qualification is `NO_CUTOFF`

Do not silently substitute:
- current date
- student submission date
- patent priority date
- project creation date

unless that date was explicitly supplied by the calling workflow under a defined contract.

---

# 8. PATENT DATE SEMANTICS

Keep these dates distinct:

- priority date
- filing/application date
- publication date
- grant date

Never substitute one for another.

## Priority date

Useful for family chronology and patent-family history.

It must NOT be treated as proof that the invention was publicly available on that date.

## Publication date

Primary field for the descriptive public-before-cutoff qualification in this Phase.

## Filing date

Preserve as filing chronology only.

## Grant date

Preserve as grant chronology only.

Do not use grant date as the first public availability date when an earlier publication exists.

---

# 9. TIME QUALIFICATION

Create a finite descriptive status such as:

- PUBLIC_BEFORE_CUTOFF
- PUBLIC_ON_CUTOFF
- PUBLIC_AFTER_CUTOFF
- PUBLICATION_DATE_UNKNOWN
- NO_CUTOFF

The exact names may adapt to repository conventions.

This status is factual chronology only.

It must NOT be named:

- LEGAL_PRIOR_ART
- INVALIDATING_PRIOR_ART
- NOVELTY_DESTROYING

Phase 2G makes no jurisdiction-specific legal determination.

---

# 10. QUERY PLANNING

Build patent queries from the project's own technical content, not from student novelty wording alone.

Use deterministic and structured-model-assisted planning where justified.

The query plan must cover multiple search strategies.

At minimum support purposes conceptually equivalent to:

- EXACT_TECHNICAL_PHRASE
- CORE_TECHNICAL_CONCEPT
- MECHANISM_FUNCTION
- COMPONENT_COMBINATION
- SYNONYM_VARIANT
- BROADER_TECHNICAL_TERMS
- CLASSIFICATION_EXPANSION
- KNOWN_IDENTIFIER_LOOKUP

Reuse/extend the existing `QueryPurpose` taxonomy rather than creating an unrelated duplicate if compatible.

## Anti-confirmation-bias requirement

Do not search only exact student wording.

The plan must include:
- functional terms
- mechanism terms
- relevant technical synonyms
- broader concept combinations

Do not intentionally search only for documents supporting novelty.

The search objective is discovery of potentially similar earlier disclosures.

---

# 11. MULTILINGUAL QUERY PLANNING

Student claims may be Arabic or mixed Arabic/English.

Patent search plans should preserve the original claim/component text for provenance while producing provider-compatible technical search terms.

Where English expansion/translation is model-assisted:

- use the existing structured model-provider abstraction
- treat model output as untrusted
- preserve original text
- record query derivation provenance
- never fabricate a student claim
- never mutate the canonical claim
- prevent prompt injection from claim text
- validate query length and allowed syntax before provider execution

Do not interpret translation as scientific evidence.

---

# 12. PII MINIMIZATION

Provider search queries must not contain unnecessary personal information.

Do not send:

- student name
- school
- email
- phone
- national identifier
- personal address

unless an explicit future workflow intentionally searches inventor identity and has a separate privacy contract.

Phase 2G searches technical content.

Add a deterministic PII/query safety check using existing privacy patterns.

---

# 13. SEARCH BOUNDEDNESS AND COMPLETENESS

Patent search is bounded.

Never claim:

`all relevant patents were found`

unless the system genuinely performed an exhaustive corpus procedure, which Phase 2G does not.

Record:

- queries planned
- queries executed
- provider
- result range/pages requested
- results returned
- provider-reported total when available
- configured result limit
- truncation/partial-result status
- failed queries
- retried queries

Create an explicit search-coverage/completion status such as:

- COMPLETE_WITHIN_CONFIGURED_BOUNDS
- PARTIAL_PROVIDER_LIMIT
- PARTIAL_ERROR
- BLOCKED_AUTH
- NOT_EXECUTED

A completed bounded search is not an exhaustive worldwide patent search.

---

# 14. PROVIDER INTERFACE

Create a patent-search provider interface following the Phase 2B provider-isolation pattern.

Conceptually support operations such as:

- search publications
- fetch bibliographic record
- fetch family
- fetch abstract/text where available
- fetch claims where available

Do not force every provider to implement unsupported operations.

Represent provider capabilities explicitly.

The Phase pipeline must degrade honestly when:

- claims unavailable
- abstract unavailable
- family service unavailable
- legal-status data unavailable

Unknown/unavailable must never become a favorable assumption.

---

# 15. PROVIDER OBSERVATION VS LOGICAL PATENT PUBLICATION

Keep provider observations separate from logical patent-publication records.

A provider response is an observation.

A logical patent publication is a normalized identity.

Do not let duplicate provider observations produce duplicate logical publications.

At minimum support canonical identifiers such as:

- publication authority/country code
- publication number
- kind code when available

Use established DOCDB/EPODOC normalization rules where provider documentation requires them.

Do not use title-only publication identity.

---

# 16. PUBLICATION IDENTITY

Create a deterministic canonical publication identity.

The identity must preserve kind-code semantics where needed.

Avoid accidental collapse of:

- application publication vs grant
- A1 vs B1/B2 stages
- different authorities
- different publication cycles

Store provider identifiers separately from canonical identity.

A publication identity must be stable and reproducible.

---

# 17. PATENT FAMILY RESOLUTION

Patent-family handling is release-critical.

Use the provider's verified family service/data when available.

Represent:

- family ID / canonical family identity
- family type/source when known
- family members
- earliest priority date if provided/verified
- provider family provenance
- family resolution status

## Family anti-inflation invariant

Multiple family members must not be represented as multiple independent inventions in later candidate counts.

However, do NOT discard family members.

Different family members may contain:
- different kind codes
- jurisdiction-specific text
- different claims
- different publication dates

Preserve publication-level records under a family-level grouping.

Do not derive family identity from title similarity.

---

# 18. FAMILY STATUS

Create explicit statuses such as:

- VERIFIED_FAMILY
- SINGLETON_FAMILY
- FAMILY_DATA_UNAVAILABLE
- FAMILY_RESOLUTION_FAILED

Do not fabricate family membership.

Unknown family membership remains unknown.

---

# 19. PATENT TEXT SNAPSHOTS

Phase 2G should preserve trustworthy patent text snapshots where the provider exposes them.

Supported content types may include:

- TITLE
- ABSTRACT
- CLAIMS
- DESCRIPTION

Each snapshot must include:

- publication ID
- provider
- content type
- language
- exact raw/normalized provider text as appropriate
- content hash
- retrieval timestamp
- provider endpoint/operation provenance
- text scope/coverage status

Do not call a provider-generated machine summary a patent abstract unless the provider contract identifies it as the official patent abstract.

---

# 20. CLAIMS AVAILABILITY

Patent claims are particularly important for later novelty comparison.

Retrieve claims when the provider officially exposes them.

However:

- claims availability varies by authority/provider
- absence of claims must be represented explicitly
- do not fail the entire search because claims are unavailable
- do not substitute title or abstract and call it "claims"

Use a finite content availability status.

Phase 2G does not yet semantically decompose patent claims.

It only acquires/verifies text for later phases.

---

# 21. ABSTRACT VS CLAIMS VS DESCRIPTION

Keep content scopes distinct.

Never treat:

- title
- abstract
- claims
- description

as interchangeable.

A candidate containing only title metadata must be marked accordingly.

A candidate with abstract but no claims must say so.

A later novelty phase may apply different evidentiary weight to these content types.

Phase 2G does not make that novelty judgment.

---

# 22. VERIFIED PATENT PUBLICATION

Create a verified publication record only after deterministic checks succeed.

At minimum verify:

- canonical publication identity
- provider/source provenance
- bibliographic parse
- date formats
- identifier normalization
- text snapshot linkage
- family linkage status
- no cross-run contamination

A search result is not automatically a verified publication.

---

# 23. PATENT PRIOR-ART CANDIDATE

The final Phase 2G candidate is a research candidate for later technical comparison.

At minimum reference:

- candidate ID
- ResearchRun ID
- claim/component query provenance
- verified publication ID
- family ID/status
- title
- publication identifiers
- priority date(s)
- filing date
- publication date
- grant date if available
- time qualification
- inventors/applicant/assignee metadata where supplied
- IPC/CPC classifications where supplied
- text availability
- text snapshot references
- provider observations
- retrieval rank/order as provider metadata
- explicit limitations

Do not store a `novelty_score`.

Do not store:
- SAME_INVENTION
- NOVEL
- NOT_NOVEL
- INVALIDATING

Those belong to later phases or legal analysis outside this system.

---

# 24. CANDIDATE RELEVANCE

Phase 2G may record:

- which query found the publication
- query purpose
- provider rank
- matched search fields if provider supplies them

Do not create a semantic similarity/novelty score in this Phase.

If the provider supplies a relevance score/rank:
- store it explicitly as provider-generated retrieval metadata
- do not rename it novelty score
- do not use it as scientific truth

---

# 25. CLASSIFICATIONS

Preserve IPC/CPC classifications where available.

Classification codes are metadata.

Do not treat shared CPC/IPC as proof of same invention.

Classification may support later query expansion.

If implementing classification expansion:

- derive it only from verified patent records
- record the source query/candidate that introduced the class
- cap expansion
- avoid recursive uncontrolled query explosion

---

# 26. QUERY EXECUTION LIMITS

Define explicit Phase 2G settings.

At minimum:

- max queries per claim/component
- max results per query
- max pages/ranges
- max total provider results per run
- max verified publications per run
- max family lookups
- retry limit
- timeout
- rate-limit/backoff settings

Never silently truncate.

When a limit is reached:

- mark partial/bounded state
- preserve counts
- do not report complete search coverage

---

# 27. RATE LIMIT / FAIR USE

Respect provider fair-use and authentication requirements.

For EPO OPS:

- use documented OAuth authentication
- implement bounded rate behavior/backoff
- do not evade provider limits
- do not parallelize aggressively merely for speed
- do not log secrets/tokens

Credentials must come from environment/settings using existing secret-handling patterns.

Never commit credentials.

---

# 28. ERROR ISOLATION

One provider/query failure must not corrupt unrelated successful observations.

Record provider/query-specific failures.

Classify at least:

- AUTHENTICATION_ERROR
- RATE_LIMITED
- TIMEOUT
- PROVIDER_ERROR
- PARSE_ERROR
- UNSUPPORTED_OPERATION
- INVALID_QUERY

Use established repository error conventions if available.

Retry only appropriate transient errors.

Do not retry deterministic invalid queries endlessly.

---

# 29. QUERY IDEMPOTENCY

Stable query plans should generate stable query identities.

Checkpoint/resume must not:

- duplicate search observations
- duplicate verified publications
- duplicate family members
- rerun successful immutable queries unnecessarily unless policy explicitly allows refresh
- lose partial query status

Use established run/attempt/checkpoint conventions.

---

# 30. CROSS-RUN ISOLATION

Reject:

- observation from another ResearchRun
- verified publication attached to another run without explicit import contract
- family references that cannot resolve inside the current run
- candidate references to unknown query/publication/family IDs

No cross-run contamination.

---

# 31. IMMUTABILITY

Before and after a real Phase 2G run, verify complete preservation of:

## ProjectState
- claims
- claim status
- claim confidence
- evidence refs
- counter-evidence refs
- canonical scores
- TrustGate
- evaluation_status

## Phase 2C–2F
- extracted evidence
- alignments
- sufficiency
- component inventory
- claim evidence scorecards

Patent research is additive to the ResearchRun only.

Use populated fixtures.

Add negative controls proving mutation guards detect real mutation.

---

# 32. LEGAL-SAFETY BOUNDARY

The system must use careful terminology.

Allowed:

- patent search candidate
- verified patent publication
- family member
- publication before cutoff
- publication after cutoff
- potentially relevant patent document
- later novelty comparison required

Forbidden as Phase 2G conclusions:

- legally invalidating prior art
- destroys novelty
- patent infringement
- freedom to operate
- patentable / unpatentable
- legally novel / not legally novel

Documentation and student-facing output must state that this research is technical discovery, not a patentability/legal opinion.

---

# 33. OFFLINE PROVIDER FIXTURES

Create deterministic offline fixtures modeled on the verified EPO OPS response contract.

Cover:

- bibliographic search response
- publication identifiers
- multiple kind codes
- abstract
- claims when available
- family response
- multilingual text
- missing fields
- malformed XML
- duplicate observations
- pagination/result ranges
- provider error payloads

Do not call the network during ordinary unit/eval suites.

---

# 34. LIVE PROVIDER TESTING

Gate EPO OPS live tests behind an explicit environment variable such as:

`RUN_EPO_OPS_TESTS=1`

and required credentials.

A live test should verify a harmless known-publication query/search and parse path.

Do not require credentials for the normal repository suite.

Report separately:

- documented contract
- mocked/offline contract tests
- live authenticated tests actually executed

No live execution means `NOT RUN`, never PASS.

---

# 35. GOLD EVAL

Add a dedicated Phase 2G offline eval.

Suggested locations:

`evals/patent_prior_art/v1/`

`src/evals/patent_prior_art/`

Create at least:

`128 total Gold cases`

Minimum language coverage:

- Arabic >= 24
- mixed Arabic/English >= 16

The remaining cases may be English.

The Gold suite should evaluate trust/provenance/search mechanics, not claim patent-law novelty.

Required categories include at least:

1. exact technical phrase query
2. core technical concept query
3. mechanism/function query
4. synonym expansion
5. broader concept query
6. Arabic claim → English patent query
7. mixed Arabic/English query
8. prompt injection inside claim
9. PII omitted from query
10. invalid CQL/query rejected
11. search result != verified publication
12. publication identity normalization
13. authority distinction
14. kind-code distinction
15. same publication from repeated query deduped
16. same publication from multiple observations deduped
17. equivalent normalized publication identifiers
18. same patent family multiple members grouped
19. family members preserved individually
20. title similarity does not create family identity
21. family data unavailable
22. family lookup failure
23. earliest priority preserved
24. priority date not used as public date
25. publication before cutoff
26. publication on cutoff
27. publication after cutoff
28. no cutoff
29. unknown publication date
30. filing date distinct
31. grant date distinct
32. abstract available
33. claims available
34. claims unavailable
35. title-only candidate
36. description available
37. multilingual abstract
38. content hash stability
39. snapshot/provider provenance
40. provider retrieval rank stored only as metadata
41. CPC/IPC preserved
42. shared classification does not imply same invention
43. bounded query limit
44. bounded result limit
45. provider-reported total greater than fetched range
46. partial-provider-limit status
47. partial-error status
48. auth blocked status
49. timeout
50. rate-limited response
51. transient retry
52. deterministic invalid query no repeated retry
53. pagination/range handling
54. stable query ID
55. rerun idempotency
56. checkpoint resume
57. duplicate observation prevention
58. duplicate publication prevention
59. duplicate family inflation prevention
60. cross-run query rejection
61. cross-run publication rejection
62. cross-run family rejection
63. ProjectState immutability
64. Phase 2C–2F immutability
65. no novelty score
66. no legal prior-art conclusion
67. no automatic claim status mutation
68. no project-score mutation
69. provider capability unavailable handled honestly
70. PATENTSCOPE automated connector remains unsupported unless authorized contract exists
71. legacy PatentsView assumptions not used
72. documented-only provider not reported live-verified

Do not pad with trivial duplicates.

---

# 36. QUALITY METRICS

At minimum measure:

- query provenance accuracy
- multilingual query-plan contract accuracy
- PII-minimization accuracy
- publication identity normalization accuracy
- provider-observation dedupe accuracy
- patent-family grouping accuracy
- family-member preservation accuracy
- chronology/date-field accuracy
- cutoff qualification accuracy
- text-snapshot provenance accuracy
- claims-availability accuracy
- bounded-search status accuracy
- provider-capability handling accuracy
- checkpoint/idempotency accuracy
- candidate traceability
- legal-boundary terminology accuracy
- per-language contract accuracy

For a subgroup with no denominator:

`None` / `not measured`

not zero.

---

# 37. RELEASE-BLOCKING SAFETY GATES

All release-blocking gates must be zero.

At minimum include:

1. ProjectState mutation
2. claim mutation
3. claim-status mutation
4. claim-confidence mutation
5. canonical evidence-reference mutation
6. canonical project-score mutation
7. TrustGate mutation
8. evaluation-status mutation
9. Phase 2C evidence mutation
10. Phase 2D alignment mutation
11. Phase 2E sufficiency mutation
12. Phase 2F scorecard mutation
13. PII leakage into patent query
14. invalid query accepted for provider execution
15. search observation treated as verified publication without verification
16. invalid publication identity accepted
17. title-only publication dedupe
18. kind-code-distinct publication incorrectly collapsed
19. duplicate provider observation inflated publication count
20. duplicate query hit inflated publication count
21. family member counted as independent family
22. title-only family grouping
23. fabricated family membership accepted
24. priority date treated as publication/public date
25. filing date treated as publication/public date
26. grant date treated as first public date when earlier publication exists
27. after-cutoff publication labeled before cutoff
28. unknown publication date labeled before cutoff
29. no-cutoff run labeled before/after cutoff
30. claims-unavailable record represented as claims-available
31. title/abstract represented as patent claims
32. provider retrieval rank represented as novelty score
33. semantic novelty score produced in Phase 2G
34. legal invalidating-prior-art conclusion produced
35. patentability conclusion produced
36. unauthorized PATENTSCOPE automation enabled
37. legacy/unverified PatentsView API assumed active
38. documented-only provider reported live-verified
39. provider credentials/token persisted in logs/state
40. provider limit silently truncated
41. partial search reported complete
42. failed query reported successful
43. cross-run query accepted
44. cross-run publication accepted
45. cross-run family accepted
46. incompatible duplicate candidate accepted
47. automatic claim status update
48. automatic Phase 2F/official/project score update

If any release-blocking gate is nonzero:

`BLOCKED`

Report every gate individually.

---

# 38. CRITICAL INVARIANTS

`Search result ≠ Verified publication`

`Verified publication ≠ Same invention`

`Patent family member ≠ Independent invention`

`Title similarity ≠ Family identity`

`Priority date ≠ Public availability date`

`Publication date ≠ Filing date`

`Publication date ≠ Grant date`

`Provider rank ≠ Novelty score`

`Shared CPC/IPC ≠ Same invention`

`Publication before cutoff ≠ Legal invalidating prior art`

`Bounded search ≠ Exhaustive worldwide search`

`Patent research ≠ Patentability opinion`

`Patent research ≠ Infringement/FTO opinion`

`Patent candidate ≠ Claim-status mutation`

`Patent candidate ≠ Project score`

---

# 39. DOCUMENTATION

Add/update:

- Phase 2G architecture documentation
- provider contract documentation
- developer architecture overview
- one ADR establishing:

`Patent Search Candidates Are Research Artifacts, Not Novelty or Legal Conclusions`

The ADR must explain:

- search observation vs verified publication
- publication vs family identity
- why family grouping prevents inflation
- why family members remain preserved
- priority vs publication-date semantics
- cutoff qualification as descriptive chronology only
- bounded search limitations
- provider access-policy constraints
- why novelty is deferred
- why legal conclusions are out of scope

Use English for developer documentation.

Arabic is allowed only as student/source/eval data.

Preserve language policy.

---

# 40. TARGETED TEST STRATEGY

During implementation run the smallest relevant tests first.

Expected targeted areas:

- provider contract/parser
- query planner
- CQL/query validation
- multilingual query planning
- PII minimization
- publication identity
- family grouping
- family-member preservation
- chronology/date semantics
- cutoff qualification
- patent text snapshots
- abstract/claims distinction
- provider capability handling
- bounded search
- errors/retries
- checkpoint/idempotency
- cross-run isolation
- immutability
- Gold dataset invariants
- per-language metrics
- all safety gates

Do not start with the full repository suite.

---

# 41. PHASE-SPECIFIC RELEASE TEST

After targeted tests pass:

1. run all Phase 2G test modules
2. run Phase 2G offline eval CLI
3. run documented provider contract tests
4. run live OPS test only if `RUN_EPO_OPS_TESTS=1` and credentials are actually available

Required:

- Phase 2G offline eval = PASS
- all release-blocking gates = zero
- no errored Gold cases
- all required coverage minimums satisfied

Do not block normal release on unavailable live credentials if the provider is honestly reported as documented-only rather than live-verified.

---

# 42. REQUIRED CROSS-PHASE REGRESSION

After Phase 2G passes, run once:

1. Phase 2F claim evidence scoring eval
2. Phase 2E claim sufficiency eval
3. Phase 2D claim alignment eval
4. Phase 2C evidence extraction eval
5. Phase 2B academic research eval
6. Phase 2A research eval
7. Phase 1 eval

Do not rerun repeatedly unless a later fix can reasonably affect them.

All required regressions must PASS.

---

# 43. FINAL FULL-SUITE RELEASE GATE

Only after:

- targeted tests pass
- Phase 2G tests pass
- Phase 2G eval passes
- required cross-phase regressions pass

run the complete repository suite once.

On Windows use:

`.venv\Scripts\python.exe -m pytest`

if PowerShell activation is blocked.

Required:

- 0 failed

Report exact passed/skipped/failed counts.

Do not invent an expected final count.

---

# 44. GIT DISCIPLINE

Work only on:

`feat/phase2g-patent-prior-art-research`

Do not merge into `main`.

Do not force-push.

Do not rewrite Phase 2F history.

Do not create an additional worktree.

Do not commit:

- `.idea/`
- `.claude/`
- Graphify output
- caches
- provider tokens/secrets
- temporary logs
- unrelated files

Prefer one clean Phase 2G implementation commit or a small number of logically justified commits.

Before completion verify:

- branch
- status
- recent log
- diff
- working tree cleanliness

---

# 45. FINAL REPORT

Return the final report in English only.

Use exactly:

## Phase 2G Result

## Starting Git State

## Provider Contract Verification

For each provider:
- status
- official documentation
- verification date
- auth
- operations implemented
- response format
- documented-only vs live-observed

## Architecture Implemented

## Patent Query Planning

## Multilingual Query Handling

## PII Minimization

## Search Boundedness

## Publication Identity

## Patent Family Resolution

## Patent Date Semantics

## Cutoff Qualification

## Patent Text Snapshots

## Claims / Abstract / Description Availability

## Prior-Art Candidate Contract

State explicitly why this is not a novelty or legal conclusion.

## Provider Error / Retry Handling

## Checkpoint / Idempotency

## Immutability

Report ProjectState and Phases 2C–2F preservation.

## Gold Dataset

Report:
- total
- English
- Arabic
- mixed
- required category coverage

## Per-Language Metrics

## Quality Metrics

## Safety Gates

List every release-blocking gate individually with:
- metric name
- numerator
- denominator
- violation count/rate

## Phase 2G Eval

## Live Provider Tests

Report exactly what was actually run.

## Cross-Phase Regression

Report Phase 2F, 2E, 2D, 2C, 2B, 2A, and Phase 1 separately.

## Tests

Report:
- passed
- skipped
- failed
- live tests executed
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
- bounded search is not exhaustive worldwide search
- provider/authority text coverage can vary
- publication-before-cutoff is descriptive chronology, not a legal prior-art ruling
- Phase 2G does not assess novelty
- Phase 2G does not assess patentability/infringement/FTO
- family grouping does not prove identical claim scope across jurisdictions

## Regression Status

## Status

Use exactly one:

`READY TO MERGE PHASE 2G`

or:

`BLOCKED`

Then STOP.

Do not merge into main.

Do not start product/open-source prior-art research.

Do not start novelty assessment.
