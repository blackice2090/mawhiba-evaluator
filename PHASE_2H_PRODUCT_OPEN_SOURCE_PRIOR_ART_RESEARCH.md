# PHASE 2H — PRODUCT + OPEN-SOURCE PRIOR-ART RESEARCH

## EXECUTION DISCIPLINE — APPLY TO THIS PHASE

Treat this as a high-trust prior-art discovery architecture + implementation phase.

Phase 2H extends prior-art research beyond patents into:
1. commercial/public product artifacts
2. public open-source repositories and implementation artifacts

It does NOT assess novelty, patentability, infringement, freedom to operate, project merit, plagiarism/copying, or official Mawhiba/Ibdaa scoring.

The goal is to discover, normalize, verify, deduplicate, preserve provenance for, and bound the search over relevant product and open-source artifacts so a later novelty/differentiation phase can compare the student's technical claims against a trustworthy candidate set.

---

# A. CONTEXT BUDGET DISCIPLINE — MANDATORY

The previous Phase consumed excessive context. Preserve all required testing while reducing redundant context.

Before starting:

`/clear`
`/model opus`

Use Opus for:
- provider-contract gate
- architecture gate
- identity/dedup semantics
- chronology semantics
- trust boundaries
- genuinely difficult integration/debugging only

Once architecture, schemas, identity contracts, and provider boundaries are stable, explicitly report:

`OPUS ARCHITECTURE COMPLETE — SAFE TO SWITCH TO SONNET`

if remaining work is primarily implementation/testing.

Do NOT remain on Opus merely because the Phase is long.

## Context checkpoints

Check context at these boundaries when available:
1. after provider-contract + architecture gate
2. after core schemas/providers/pipeline compile and targeted tests pass
3. before Gold/eval implementation if context has grown materially
4. before cross-phase regression
5. before final full-suite gate

Guideline:
- `<60%`: continue
- `60–70%`: minimize rereads and output
- `70–80%`: finish current logical block, checkpoint, then `/compact`
- `80–90%`: do not begin a large new block without compacting
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

Then wait for `/compact`.

Use concise test output. Do not dump large JSON, HTML, API payloads, or full Gold files unless a small targeted excerpt is required.

Required testing must NOT be reduced to save context.

---

# B. GENERAL EXECUTION RULES

- Keep scope strictly limited to Phase 2H.
- Use the primary Claude Code session.
- Do NOT delegate the complete Phase or major areas to Agents/Subagents.
- Do not create additional Git worktrees.
- Reuse existing ResearchRun, PRODUCT/OPEN_SOURCE branches, provider abstractions, safe fetch infrastructure, query planning, settings, serializer/checkpoint, and eval patterns where compatible.
- Reuse Phase 2G boundedness, chronology, provider-honesty, and candidate-vs-conclusion boundaries.
- Prefer the smallest correct architectural extension.
- Do not redesign Phases 2A–2G.
- Do not weaken tests, validators, schemas, referential integrity, metrics, eval denominators, gates, or assertions.
- Do not convert failures into skips.
- If a genuine architecture conflict appears, STOP and report it.
- Do not merge into `main`.
- Do not start novelty/differentiation assessment.
- Do not mutate ClaimRecord, canonical evidence, project scores, Phase 2C–2G artifacts, TrustGate, or evaluation status.
- Do not produce a similarity/novelty score in Phase 2H.

Required progression:

`provider-contract verification`
→ `architecture verification`
→ `implementation`
→ `smallest targeted tests`
→ `Phase 2H tests/eval`
→ `required cross-phase regression`
→ `one final full-suite release gate`
→ `Git verification`
→ `STOP`

---

# 1. BASELINE AND GIT

Expected baseline:
- branch: `main`
- Phase 2G merged and post-merge verified
- expected current main HEAD: `26e2fba`
- latest verified full-suite result:
  - 1897 passed
  - 29 skipped
  - 0 failed

Before modifying code:
1. verify branch
2. verify HEAD
3. verify tracked working tree is clean
4. inspect untracked tooling only if needed; do not automatically commit it
5. confirm Phase 2G structures exist
6. create:

`feat/phase2h-product-oss-prior-art`

Do not use another worktree.

---

# 2. PHASE OBJECTIVE

## Product track

`Technical Claims / Components`
→ `Product Search Query Plan`
→ `Web Search Observations`
→ `Fetched Source Artifacts`
→ `Normalized Product Entities`
→ `Product Identity / Equivalence`
→ `Product Prior-Art Candidates`
→ `STOP`

## Open-source track

`Technical Claims / Components`
→ `Open-Source Query Plan`
→ `Repository / Code Search Observations`
→ `Verified Repository`
→ `Repository Content Snapshots`
→ `Fork / Mirror / Repository-Network Resolution`
→ `Open-Source Prior-Art Candidates`
→ `STOP`

Phase 2H answers:

> Which commercial/product artifacts and public open-source implementations should a later novelty/differentiation phase inspect, and what verified provenance and identity information do we have for them?

It does NOT answer whether the project is novel, whether two artifacts are the same invention, whether something legally destroys novelty, or whether project scoring should change.

Preserve:

`Search result ≠ Verified artifact`

`Product listing ≠ Independent product`

`Marketplace listing ≠ Manufacturer source`

`Repository search hit ≠ Verified implementation`

`Code-search hit ≠ Independent repository`

`Fork ≠ Independent implementation by default`

`Mirror ≠ Independent implementation by default`

`Retrieval rank ≠ Novelty score`

---

# 3. PROVIDER-CONTRACT GATE

Verify current official documentation before coding any provider.

Record:
- provider
- official docs URL
- verification date
- authentication
- operations/endpoints
- pagination
- limits
- response shape
- rate/fair-use constraints
- fields used
- documented-only vs live-observed

Do not rely on stale docs, blogs, memory, or unofficial wrappers.

---

# 4. OPEN-SOURCE PRIMARY PROVIDER — GITHUB

Use GitHub's current official REST API if verified compatible.

Verify:
- API version header
- repository search
- code search
- repository metadata
- README/content retrieval
- releases/tags where required
- fork/source metadata
- repository numeric IDs/node IDs
- license metadata
- pagination
- authentication behavior
- public unauthenticated behavior
- primary/secondary rate limits

Do not assume code-search auth behavior.

Provider status must be one of:
- IMPLEMENTED_AND_LIVE_VERIFIED
- IMPLEMENTED_DOCUMENTED_ONLY
- DEFERRED
- UNSUPPORTED

Live verified requires a real successful request.

---

# 5. PRODUCT DISCOVERY PRIMARY PROVIDER — WEB SEARCH

Use a documented web-search provider abstraction.

Brave Search API is the preferred provider if current official docs remain compatible.

Verify:
- Web Search endpoint
- API-key authentication
- query limits
- language/country parameters
- pagination/result count
- rate/quota errors
- returned URL/title/snippets/date fields
- response format

A Brave result is a discovery observation, NOT a verified product artifact.

Do not treat search snippets as manufacturer truth.

Keep provider abstraction replaceable.

---

# 6. SAFE WEB ARTIFACT FETCHING

Search discovery and artifact verification are separate.

Reuse existing safe web/source acquisition if suitable.

If a fetcher is needed:
- public HTTP(S) only
- bounded redirects
- revalidate every redirect
- block localhost, loopback, private networks, link-local, metadata endpoints
- reject embedded credentials
- enforce time/size limits
- record original/final URL and redirects
- record content type
- retrieval timestamp
- content hash
- do not execute JavaScript
- do not persist cookies/secrets

Do not build general browser automation.

Unavailable/blocked sources stay observation-only.

---

# 7. ARCHITECTURE GATE — OPUS

Decide before coding:

1. ResearchRun ownership
2. relationship to PRODUCT and OPEN_SOURCE research branches
3. product vs OSS state separation
4. later-phase handoff shape
5. product observation vs artifact vs entity
6. repository observation vs verified repository
7. product identity confidence
8. repository canonical identity
9. fork/mirror/network identity
10. snapshot design
11. date semantics
12. cutoff semantics
13. boundedness
14. failure semantics
15. query provenance
16. boundary before novelty assessment
17. immutability boundaries

Proceed if coherent. STOP on genuine conflict.

---

# 8. OWNERSHIP

Outputs remain on `ResearchRun`.

Prefer strongly typed product and OSS subruns.

Do NOT mutate:
- ProjectState claims
- claim status/confidence
- evidence refs
- project ScoreRecords
- Phase 2C evidence
- Phase 2D alignments
- Phase 2E sufficiency
- Phase 2F scorecards
- Phase 2G patent run
- TrustGate
- evaluation_status

---

# 9. INPUT CONTRACT

May consume:
- canonical technical claims
- Phase 2E component inventory
- technical domain
- technologies
- explicit cutoff date if supplied
- query-planning provenance conventions

Must NOT:
- use Phase 2F score to skip search
- treat student novelty claims as truth
- use patent candidates as automatic product/OSS matches
- send personal student data externally

---

# 10. QUERY PLANNING

Support purposes equivalent to:
- EXACT_TECHNICAL_PHRASE
- CORE_CONCEPT
- FUNCTION_MECHANISM
- COMPONENT_COMBINATION
- SYNONYM_VARIANT
- BROADER_CATEGORY
- PRODUCT_CATEGORY
- IMPLEMENTATION_TERM
- SOFTWARE_LIBRARY_TERM
- KNOWN_IDENTIFIER

Reuse existing taxonomy where compatible.

Every query references:
- claim/component source
- derivation purpose
- language
- provider
- stable query ID
- execution status

No uncontrolled recursive expansion.

---

# 11. MULTILINGUAL HANDLING

Support Arabic and mixed claims.

Preserve original text.

English expansion may use structured LLM only if needed.

Model output:
- is untrusted
- must preserve source anchor
- must be validated
- must pass PII and injection checks
- must not mutate claim
- must record prompt/version/provenance
- is not evidence

---

# 12. PII MINIMIZATION

Do not send unnecessary:
- student name
- school
- email
- phone
- national ID
- address
- personal metadata

Search technical content only.

Use deterministic PII checks before dispatch.

---

# 13. SEARCH BOUNDEDNESS

Record:
- planned/executed queries
- provider
- pages/results requested
- results returned
- provider total if supplied
- configured limits
- truncation
- failures/retries

Statuses:
- COMPLETE_WITHIN_CONFIGURED_BOUNDS
- PARTIAL_PROVIDER_LIMIT
- PARTIAL_ERROR
- BLOCKED_AUTH
- NOT_EXECUTED

Never claim exhaustive product/OSS coverage.

---

# 14. PRODUCT OBSERVATION

A search observation preserves:
- provider
- query ID
- retrieval rank
- URL
- title
- snippet
- provider date if any
- retrieval timestamp

It is NOT verified product existence, manufacturer truth, independent identity, or novelty evidence.

---

# 15. PRODUCT SOURCE ARTIFACT

Fetched artifact preserves:
- artifact ID
- original URL
- final canonicalized URL
- redirect chain
- host
- source role
- content type
- retrieval timestamp
- content hash
- bounded text snapshot
- deterministically extracted title/headings
- source-reported dates
- fetch status
- limitations

Suggested source roles:
- FIRST_PARTY_PRODUCT_PAGE
- FIRST_PARTY_DOCUMENTATION
- FIRST_PARTY_PRESS_RELEASE
- MARKETPLACE_LISTING
- THIRD_PARTY_REVIEW
- THIRD_PARTY_DIRECTORY
- UNKNOWN

Do not infer FIRST_PARTY merely from title/vendor text.

Unknown stays unknown.

---

# 16. PRODUCT IDENTITY

Prefer strong identifiers:
- manufacturer model number
- SKU/MPN
- app/package identifier
- official product ID
- stable canonical vendor/product identifier

Do NOT merge solely on:
- similar title
- similar description
- similar image
- marketplace title

Identity status:
- VERIFIED_STRONG_IDENTITY
- PROBABLE_IDENTITY
- UNRESOLVED_IDENTITY

Only strong identity auto-collapses.

Probable matches may be linked but not destructively merged.

---

# 17. PRODUCT LISTING ANTI-INFLATION

Same product across manufacturer/marketplaces/distributors/reviews must not automatically count as multiple independent products.

Preserve all artifacts.

Group only with justified identity.

`More listings ≠ More products`

---

# 18. PRODUCT DATE SEMANTICS

Keep distinct:
- source page publication date
- vendor-stated launch date
- vendor-stated availability date
- marketplace listing date
- search-provider date
- retrieval date

Current page existence does not prove historical availability.

Embedded dates remain source-reported unless independently verified.

---

# 19. PRODUCT CUTOFF QUALIFICATION

Use descriptive statuses:
- DATED_ARTIFACT_BEFORE_CUTOFF
- DATED_ARTIFACT_ON_CUTOFF
- DATED_ARTIFACT_AFTER_CUTOFF
- ARTIFACT_DATE_UNKNOWN
- NO_CUTOFF

This is chronology only, NOT a legal prior-art ruling.

---

# 20. PRODUCT PRIOR-ART CANDIDATE

Reference:
- claim/component provenance
- product entity identity/status
- artifacts
- source roles
- source-stated product/vendor names
- strong identifiers
- date facts
- cutoff qualification
- retrieval metadata
- limitations

Forbidden:
- novelty_score
- same_invention
- not_novel
- legal_prior_art
- project_score_penalty

---

# 21. GITHUB REPOSITORY OBSERVATION

Preserve:
- query ID
- provider
- repo numeric ID/node ID
- full name
- URL
- retrieval rank
- code match path/snippet where applicable
- retrieval timestamp

Code hit is not an independent implementation.

Multiple hits in one repo collapse at repo identity for independence.

---

# 22. VERIFIED OPEN-SOURCE REPOSITORY

Use stable provider identifiers:
- numeric repository ID
- node ID

Preserve mutable:
- owner
- name
- full_name
- URL

Do not use owner/name as canonical identity when stable ID exists.

Record:
- current visibility
- fork flag
- parent/source relation
- archived/disabled
- default branch
- license
- topics
- languages
- description
- created/updated/pushed timestamps
- provenance

---

# 23. REPOSITORY CONTENT SNAPSHOTS

Retrieve bounded:
- README
- description
- topics
- package/manifest files
- release metadata
- selected files returned by code search

Do not clone entire repositories by default.

Snapshot:
- repo ID
- path/content type
- ref/commit SHA if available
- hash
- retrieval time
- provider operation
- truncation
- language if known

Code-search snippet is not a full file snapshot.

---

# 24. FORK / MIRROR / NETWORK RESOLUTION

Relationship:
- ROOT_REPOSITORY
- FORK
- MIRROR
- TEMPLATE_DERIVATIVE
- RELATION_UNKNOWN

Use provider-declared relations when available.

Do not infer from names/titles.

Forks of one upstream do not count as independent root implementations by default.

Preserve forks individually because they may diverge.

Group under repository network/root identity.

Later novelty analysis may inspect divergence.

---

# 25. REPOSITORY NETWORK IDENTITY

Use stable root/source ID where available.

Record:
- network/root ID
- members
- relationship basis
- unresolved members

Multiple hits/branches/releases/forks do not automatically create independent implementations.

---

# 26. OPEN-SOURCE DATE SEMANTICS

Keep distinct:
- repo created_at
- updated_at
- pushed_at
- release created_at
- release published_at
- commit authored date
- commit committed date
- retrieval date

Critical:

`repository created_at ≠ proven public-since date`

because visibility can change.

`old commit date ≠ proof of public availability`

without independent visibility evidence.

---

# 27. OPEN-SOURCE CUTOFF QUALIFICATION

Use descriptive dated-artifact semantics:
- DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF
- DATED_REPOSITORY_ARTIFACT_ON_CUTOFF
- DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF
- ARTIFACT_DATE_UNKNOWN
- NO_CUTOFF

Record:
- date field used
- provider
- historical visibility limitation

---

# 28. OPEN-SOURCE PRIOR-ART CANDIDATE

Reference:
- claim/component provenance
- verified repository
- repository network
- observations/code hits
- bounded snapshots
- license
- topics/languages
- source-reported dates
- cutoff qualification
- relationship status
- limitations

Forbidden:
- novelty_score
- same_invention
- copying/plagiarism conclusion
- patent/legal conclusion
- project-score mutation

---

# 29. LICENSE SEMANTICS

Preserve GitHub license/SPDX metadata where supplied.

Unknown/no-license remains explicit.

Do not infer:
- reuse permission
- copyright compliance
- plagiarism
- FTO

---

# 30. POPULARITY / RANK

Stars, forks, watchers, reviews, marketplace popularity, search rank, and page rank are metadata only.

They must not:
- increase independence
- become novelty score
- become project score
- determine candidate truth

---

# 31. LATER-PHASE HANDOFF

Expose typed candidates:
- ProductPriorArtCandidate
- OpenSourcePriorArtCandidate

Do not flatten product/OSS identity/date semantics into a weak generic record.

Later novelty phase may consume patent + product + OSS candidates while preserving type.

---

# 32. ERROR / RETRY

Classify:
- AUTHENTICATION_ERROR
- RATE_LIMITED
- QUOTA_LIMITED
- TIMEOUT
- CONNECTION_ERROR
- PROVIDER_ERROR
- PARSE_ERROR
- UNSUPPORTED_OPERATION
- INVALID_QUERY
- FETCH_BLOCKED
- FETCH_UNSAFE
- CONTENT_TOO_LARGE

Retry transient errors only.

One failure must not discard unrelated success.

---

# 33. SSRF / SAFE URL BOUNDARY

Reject:
- localhost
- loopback
- private networks
- link-local
- metadata endpoints
- non-HTTP(S)
- embedded credentials
- unsafe redirects

Revalidate every redirect target.

Add explicit tests.

---

# 34. EXECUTION LIMITS

At minimum:
- max queries per claim/component
- max results/query
- max pages
- max total observations
- max product fetches
- max artifact bytes
- max repo detail lookups
- max code hits/repo
- max README/content bytes
- max fork/network lookups
- retry limit
- timeouts
- rate backoff

Never silently truncate.

---

# 35. IDEMPOTENCY / CHECKPOINTING

Stable inputs produce stable query/candidate IDs.

Resume must not duplicate:
- observations
- artifacts
- entities
- repositories
- snapshots
- networks
- candidates

Finished run is not silently reopened.

---

# 36. CROSS-RUN ISOLATION

Reject:
- foreign query
- foreign artifact/repo
- unresolved foreign network member
- candidate with unknown refs
- cross-run product identity group

---

# 37. IMMUTABILITY

Verify populated before/after preservation of:

## ProjectState
- claims
- statuses/confidences
- evidence refs
- scores
- TrustGate
- evaluation_status

## Phases 2C–2G
- evidence
- alignments
- sufficiency
- scorecards
- patent prior-art run

Add negative controls.

---

# 38. LEGAL / EVALUATION BOUNDARY

Allowed:
- product candidate
- OSS candidate
- potentially relevant artifact
- verified repository
- unresolved product identity
- fork network
- dated artifact before cutoff
- later novelty comparison required

Forbidden conclusions:
- not novel
- novelty destroyed
- copied
- plagiarized
- same invention
- legally invalidating prior art
- infringement
- FTO
- patentable/unpatentable
- lower project score

---

# 39. OFFLINE PROVIDER FIXTURES

Create deterministic fixtures for:

## Brave/web search
- normal results
- multilingual
- duplicate URLs
- date present/absent
- quota/rate error
- pagination

## Product fetcher
- first-party-style page
- marketplace
- third-party
- redirect
- unsafe redirect
- oversized content
- malformed content
- duplicate content at multiple URLs

## GitHub
- repository search
- code search
- repo metadata
- fork/source
- README
- release
- license
- pagination
- rate limit
- auth failure
- archived repo
- renamed/transferred repo identity

Normal suite must be offline.

---

# 40. LIVE PROVIDER TESTING

Gate behind environment variables, e.g.:

`RUN_GITHUB_PRIOR_ART_TESTS=1`

`RUN_BRAVE_SEARCH_TESTS=1`

Use harmless public queries.

No live credentials required for normal release.

Skipped live test = NOT RUN, not PASS.

---

# 41. GOLD EVAL

Create dedicated offline Phase 2H Gold suite.

Suggested:
- `evals/product_oss_prior_art/v1/`
- `src/evals/product_oss_prior_art/`

Minimum:
- total >= 160
- Arabic >= 32
- mixed >= 24

Required coverage includes at least 78 categories spanning:

### Query/planning
- exact phrase
- function/mechanism
- product category
- implementation terms
- Arabic
- mixed
- prompt injection
- PII
- invalid query

### Product
- observation != artifact
- successful/failed fetch
- unsafe URL/redirect
- first-party verified/unresolved
- marketplace
- third-party
- strong-ID collapse
- title-only non-collapse
- probable identity non-destructive
- multi-listing anti-inflation
- date fields
- before/on/after/unknown/no cutoff
- rank metadata only
- no novelty/legal output

### OSS
- repository search
- code search
- same repo many hits
- stable ID
- rename/transfer identity
- same name/different IDs
- fork grouping/preservation
- mirror/unknown relation
- README/manifest
- snippet != full snapshot
- archived
- license known/unknown
- popularity irrelevant
- created_at/public-since separation
- commit-date/public-availability separation
- release date
- cutoff field provenance
- provider capability/rate/pagination
- network dedupe

### State/safety
- bounded partial status
- no silent completeness
- checkpoint/rerun
- duplicate candidate rejection
- cross-run rejection
- ProjectState immutability
- Phase 2C–2G immutability
- no status/score/TrustGate mutation
- provider honesty
- no secret persistence
- candidate type separation
- no novelty/differentiation verdict

Do not pad with trivial duplicates.

---

# 42. QUALITY METRICS

At minimum:
- query provenance
- multilingual query plan
- PII minimization
- observation/artifact separation
- safe fetch
- product identity
- weak-identity non-collapse
- listing anti-inflation
- product chronology
- repository identity
- code-hit dedupe
- fork/network grouping
- fork preservation
- OSS chronology
- snapshot provenance
- provider capability/error
- bounded status
- idempotency
- candidate traceability
- legal/novelty boundary
- per-language contract accuracy

No denominator => `None / not measured`.

---

# 43. RELEASE-BLOCKING SAFETY GATES

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
9. Phase 2C evidence mutation
10. Phase 2D alignment mutation
11. Phase 2E sufficiency mutation
12. Phase 2F scorecard mutation
13. Phase 2G patent-run mutation
14. PII leaked to product query
15. PII leaked to GitHub query
16. invalid query dispatched
17. search observation treated as verified product
18. search observation treated as verified repository
19. unsafe URL fetched
20. unsafe redirect followed
21. oversized artifact silently accepted
22. marketplace labeled first-party without proof
23. third-party page labeled first-party without proof
24. title-only product identity collapse
25. probable identity destructively merged
26. duplicate listing inflated product count
27. search rank represented as novelty score
28. popularity represented as novelty score
29. dated product artifact represented as legal prior art
30. current product page represented as historical availability proof
31. owner/name used instead of stable repo ID when stable ID exists
32. multiple code hits inflated repo count
33. fork counted as independent root
34. mirror counted as independent root without basis
35. name similarity used to infer fork/mirror
36. repo created_at represented as proven public-since
37. commit date represented as proven public availability
38. stars/forks/watchers represented as novelty strength
39. code snippet represented as full source snapshot
40. license metadata interpreted as reuse permission
41. provider limit silently truncated
42. partial product search reported complete
43. partial OSS search reported complete
44. failed query reported successful
45. cross-run query accepted
46. cross-run product artifact accepted
47. cross-run product entity accepted
48. cross-run repository accepted
49. cross-run repository network accepted
50. incompatible duplicate product candidate accepted
51. incompatible duplicate OSS candidate accepted
52. novelty score produced
53. novelty verdict produced
54. same-invention verdict produced
55. plagiarism/copying verdict produced
56. legal prior-art conclusion produced
57. patentability/infringement/FTO conclusion produced
58. automatic claim-status update
59. automatic official/project score update
60. Phase 2F score modified
61. provider credential/token persisted
62. documented-only provider reported live-verified
63. product/OSS candidate-type conflation
64. unbounded recursive query expansion

Every gate needs a meaningful denominator and, where practicable, a negative control.

---

# 44. CRITICAL INVARIANTS

`Search hit ≠ Verified artifact`

`Search snippet ≠ Product truth`

`Marketplace listing ≠ Manufacturer source`

`More listings ≠ More products`

`Title similarity ≠ Product identity`

`Code hit ≠ Repository`

`More code hits ≠ More implementations`

`Fork ≠ Independent root implementation`

`Mirror ≠ Independent implementation by default`

`Repository created_at ≠ Proven public-since`

`Commit date ≠ Proven public availability`

`Popularity ≠ Novelty`

`Retrieval rank ≠ Novelty`

`Current availability ≠ Historical availability`

`Dated artifact before cutoff ≠ Legal prior art`

`Candidate ≠ Same invention`

`Candidate ≠ Novelty verdict`

`Candidate ≠ Project-score mutation`

---

# 45. DOCUMENTATION

Add/update:
- Phase 2H architecture doc
- product/web provider contract doc
- GitHub provider contract doc
- developer architecture overview
- ADR:

`Product and Open-Source Search Candidates Are Discovery Artifacts, Not Novelty Conclusions`

Explain:
- observation vs verified artifact
- strong vs weak product identity
- non-destructive weak matching
- listing anti-inflation
- stable repo identity
- fork/network anti-inflation
- chronology/public-availability limitations
- bounded search
- provider honesty
- no novelty/legal/project-score conclusions

Developer docs English; Arabic only source/student/eval data.

---

# 46. TARGETED TEST STRATEGY

Run smallest relevant tests first:
- provider contracts
- query planning
- multilingual
- PII
- safe fetch/SSRF
- product identity
- anti-inflation
- dates/cutoff
- repo identity
- code-hit dedupe
- fork/network
- snapshots
- limits/errors
- idempotency
- cross-run
- immutability
- Gold invariants
- metrics
- gates

Do not start with full suite.

---

# 47. PHASE-SPECIFIC RELEASE TEST

After targeted tests:
1. complete Phase 2H tests
2. Phase 2H offline eval
3. provider-contract tests
4. live tests only if explicitly enabled and available

Required:
- Phase 2H eval PASS
- all gates zero
- zero errored Gold cases
- minimums met

Live credentials are not a release requirement if status is honestly documented-only.

---

# 48. REQUIRED CROSS-PHASE REGRESSION

After Phase 2H passes, run once:

1. Phase 2G patent prior-art eval
2. Phase 2F claim evidence scoring eval
3. Phase 2E sufficiency eval
4. Phase 2D alignment eval
5. Phase 2C evidence eval
6. Phase 2B academic eval
7. Phase 2A research eval
8. Phase 1 eval

All PASS.

---

# 49. FINAL FULL-SUITE RELEASE GATE

Only after Phase 2H + regressions:

`.venv\Scripts\python.exe -m pytest`

Required:
- 0 failed

Report exact counts.

---

# 50. GIT DISCIPLINE

Work only on:

`feat/phase2h-product-oss-prior-art`

Do not merge main.
Do not force-push.
Do not rewrite Phase 2G history.
Do not create another worktree.

Do not commit:
- `.agents/`
- `.codex/`
- `AGENTS.md` unless explicitly established as project-owned
- `.idea/`
- `.claude/`
- graphify output
- caches
- API keys/tokens
- temp logs
- unrelated files

Verify branch/status/log/diff/worktrees before completion.

---

# 51. FINAL REPORT

Return final report in English only with exactly:

## Phase 2H Result

## Starting Git State

## Context / Model Usage

Report architecture model, switch-to-Sonnet point if any, and `/compact` checkpoints. Do not estimate token counts.

## Provider Contract Verification

Separate GitHub, product/web-search provider, web fetcher.

## Architecture Implemented

## Product Query Planning

## Open-Source Query Planning

## Multilingual Handling

## PII Minimization

## Search Boundedness

## Product Observation / Artifact Separation

## Product Identity

## Product Listing Anti-Inflation

## Product Date / Cutoff Semantics

## GitHub Repository Identity

## Code Search Handling

## Fork / Mirror / Repository Network Resolution

## Open-Source Date / Cutoff Semantics

## Content Snapshots

## Candidate Contracts

## Safe Fetch / SSRF

## Provider Error / Retry Handling

## Checkpoint / Idempotency

## Immutability

## Gold Dataset

Report total, English, Arabic, mixed, product/OSS coverage, required categories.

## Per-Language Metrics

## Quality Metrics

## Safety Gates

List every gate individually with numerator, denominator, rate.

## Phase 2H Eval

## Live Provider Tests

## Cross-Phase Regression

Report 2G, 2F, 2E, 2D, 2C, 2B, 2A, Phase 1 separately.

## Tests

Exact passed/skipped/failed and live test status.

## Files Modified

## Git End State

Branch, status, commits, `git diff --stat main...HEAD`, worktrees.

## Remaining Limitations

Explicitly include:
- bounded discovery not exhaustive
- product identity may remain unresolved
- current product availability does not prove historical availability
- GitHub created/commit dates do not prove historical public visibility
- forks may materially diverge despite grouping
- provider/web content can change
- Phase 2H does not assess novelty
- Phase 2H does not assess copying/plagiarism
- Phase 2H produces no legal conclusions
- Phase 2H produces no official/project scoring

## Regression Status

## Status

Use exactly:

`READY TO MERGE PHASE 2H`

or

`BLOCKED`

Then STOP.

Do not merge into main.

Do not start novelty/differentiation assessment.
