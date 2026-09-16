# Phase 2B Execution Specification
## Academic Research Connectors

You are continuing implementation of the **Mawhiba Project Evaluator Agent**.

Approved and merged phases:

- Phase 0 — Data Contracts
- Phase 1A — LangGraph Workflow Infrastructure
- Phase 1A.1 — Workflow Hardening
- Phase 1B — Trusted LLM Intake
- Phase 1C — Canonical Intake Model and Trust Evals
- Phase 2A — Research Foundation, Query Planning, Official Requirements
- Phase 2A.1 — Research Hardening

Current baseline:

```text
branch:
feat/phase2b-academic-research-connectors

starting commit:
a8aaca0

verified full-suite baseline:
961 passed
15 skipped
0 failed
```

Primary architecture source:

`docs/mawhiba_agent_system_architecture_v1.md`

Relevant Phase 2A documentation:

```text
docs/phase2a_research_foundation.md
docs/phase2a1_hardening.md
docs/phase2a_execution_spec.md
docs/adr/ADR-006-research-query-provenance.md
docs/adr/ADR-007-search-result-is-not-evidence.md
```

Read all of them before implementation.

Do not redesign previous phases.

---

# 1. Phase Goal

Implement:

> **Phase 2B — Academic Research Connectors**

The goal is to connect the trusted Phase 2A research foundation to multiple academic research providers while preserving strict source provenance, deterministic normalization, deduplication, provider isolation, and the trust boundary:

```text
Verified Query Plan
    ↓
Academic Retrieval
    ↓
SourceCandidate
    ↓
Source Verification / Normalization
    ↓
SourceRecord
```

Phase 2B must NOT yet perform scientific evidence extraction into `EvidenceRecord` or claim support.

That belongs to a later phase.

Hard rule:

```text
Academic Search Result ≠ Verified Source ≠ Evidence ≠ Supported Claim
```

---

# 2. Connectors in Scope

Implement first-class connector support for:

```text
Consensus
OpenAlex
Semantic Scholar
```

Each connector must have:

- its own provider module
- typed request/response boundary
- deterministic normalization into canonical `SourceCandidate`
- structured error semantics
- rate-limit handling
- timeout handling
- retry policy
- provider-specific identifiers preserved
- no hidden fallback into another provider

A provider failure must not corrupt or invalidate successful results from other providers.

---

# 3. Connector Architecture

Create a provider abstraction conceptually similar to:

```python
class AcademicSearchProvider(Protocol):
    provider_name: AcademicProvider

    def search(
        self,
        query: AcademicSearchQuery,
        *,
        limit: int,
    ) -> AcademicSearchResult:
        ...
```

The exact API may adapt to the existing codebase.

Do not over-generalize prematurely.

Provider-specific implementation details should remain provider-specific.

---

# 4. Academic Provider Enum

Introduce a stable enum such as:

```text
CONSENSUS
OPENALEX
SEMANTIC_SCHOLAR
```

Do not encode provider names as arbitrary strings across the system.

The enum should be reusable later for provenance and metrics.

---

# 5. Academic Query Input

Academic connectors may execute only verified query-plan entries from Phase 2A.

Do not allow arbitrary raw student text to bypass the verified query planner.

A connector call must preserve:

```text
research_run_id
query_id
branch
purpose
query
provider
requested_limit
```

Academic branch must be:

```text
ACADEMIC
```

---

# 6. Search Scope

Academic search should support queries relevant to:

```text
PROBLEM
EXISTING_SOLUTIONS
TECHNOLOGY
RECENT_WORK
LIMITATIONS
BENCHMARK
REVIEW
ALTERNATIVES
FAILURE_MODES
PRIOR_ART
```

Do NOT route:

```text
PATENT_FUNCTION
PATENT_MECHANISM
PRODUCT
OPEN_SOURCE
```

to academic connectors.

Those belong to later branches.

---

# 7. Provider Query Budgets

Do not execute every academic query against every provider without control.

Add configurable budgets for at least:

```text
max_academic_queries_per_run
max_results_per_query_per_provider
max_results_per_provider_per_run
max_total_academic_candidates
```

Use deterministic enforcement.

Record when results are truncated due to budget.

Budget exhaustion is not a provider failure.

---

# 8. Provider Isolation

One connector must never be able to cause the whole academic branch to fail by itself.

Example:

```text
Consensus      SUCCESS
OpenAlex       TIMEOUT
SemanticScholar SUCCESS
```

must produce:

```text
academic branch = PARTIAL
```

not:

```text
FAILED
```

if useful results were still obtained.

Define explicit branch aggregation semantics.

---

# 9. Retry Semantics

Reuse the shared retry/invocation philosophy introduced in Phase 2A.1.

Do not duplicate retry loops unnecessarily.

For HTTP/API retrieval, define explicit retryable vs non-retryable classes.

Typical retryable failures:

```text
timeout
connection reset
HTTP 429
HTTP 500
HTTP 502
HTTP 503
HTTP 504
```

Typical non-retryable failures:

```text
400 malformed request
401 unauthorized
403 forbidden unless explicitly documented as transient
404 endpoint/resource not found
schema incompatibility
invalid provider response
```

Bound retries.

No infinite retry.

---

# 10. Rate Limits

Represent rate limiting explicitly.

Do not treat HTTP 429 as generic provider error.

Capture at least:

```text
provider
status
retry_after if provided
attempts
```

Standard deterministic tests must not sleep in real time.

Use injectable clock/backoff/sleep seams where needed.

---

# 11. Credentials

No credentials may be stored or logged.

Use environment variables only.

Suggested names:

```text
CONSENSUS_API_KEY
SEMANTIC_SCHOLAR_API_KEY
```

OpenAlex may remain keyless unless the current API requires otherwise.

Do not print keys.

Do not include keys in exception text.

Do not serialize credentials into workflow state.

---

# 12. Live Tests

All normal tests must run offline.

Live connector tests must be opt-in only.

Suggested environment flags:

```text
RUN_CONSENSUS_TESTS=1
RUN_OPENALEX_TESTS=1
RUN_SEMANTIC_SCHOLAR_TESTS=1
```

Do not run live tests merely because credentials exist.

Do not make CI depend on live services.

---

# 13. SourceCandidate Contract

Extend or create canonical academic `SourceCandidate` support.

Every accepted candidate should preserve conceptually:

```text
source_id
provider
source_type

title
abstract
authors

publication_year
publication_date

venue
publisher

doi
openalex_id
semantic_scholar_id
pmid
arxiv_id

canonical_url
provider_url

citation_count if provider supplies it
is_open_access if known
is_retracted if known
publication_type if known

retrieved_at

query_id
research_run_id

raw_provider_metadata
```

Do not invent absent metadata.

Missing means `None`.

---

# 14. Source Type

Academic candidates should distinguish source types where provider metadata supports it, e.g.:

```text
JOURNAL_ARTICLE
CONFERENCE_PAPER
REVIEW
SYSTEMATIC_REVIEW
META_ANALYSIS
PREPRINT
BOOK_CHAPTER
THESIS
DATASET
OTHER_ACADEMIC
UNKNOWN
```

Do not infer exact source type from title wording alone.

If unknown, use `UNKNOWN`.

---

# 15. Identifier Normalization

Normalize identifiers deterministically.

At minimum:

```text
DOI
OpenAlex ID
Semantic Scholar Paper ID
PMID
arXiv ID
```

DOI normalization should handle common forms such as:

```text
https://doi.org/10.xxxx/abc
http://dx.doi.org/10.xxxx/abc
doi:10.xxxx/abc
10.xxxx/abc
```

Canonical DOI should be normalized to a consistent lowercase identifier.

Do not invent DOI from titles.

---

# 16. Cross-Provider Deduplication

Use the Phase 2A.1 `SourceFingerprint` foundation.

Cross-provider dedupe priority should prefer strong identifiers.

Conceptual identifier priority:

```text
DOI
PMID
OpenAlex ID
Semantic Scholar ID
arXiv ID
canonical URL
```

Do NOT dedupe solely by title.

Two papers with the same or very similar title are not automatically the same source.

If no trusted identifier exists, preserve both candidates.

---

# 17. Logical Source vs Provider Observation

Preserve the distinction between:

```text
logical source
```

and:

```text
provider observation
```

Example:

Consensus and OpenAlex may both return the same DOI.

That should become:

```text
one logical source
multiple provider observations
```

Do not discard provider provenance when deduplicating.

The system must be able to answer:

> Which providers independently returned this source?

---

# 18. Metadata Merge Rules

When multiple providers return the same logical source, merge conservatively.

Examples:

- DOI must agree after normalization.
- Conflicting publication years must not be silently overwritten.
- Missing metadata may be filled from another provider.
- Conflicting titles/authors should produce a recorded metadata conflict when materially inconsistent.
- Citation count is provider-specific and time-sensitive; do not silently collapse counts without preserving provider and retrieval time.

Create deterministic merge rules.

---

# 19. Source Verification

Phase 2B verifies source identity and metadata consistency.

It does NOT yet verify scientific claims inside the paper.

Verification may include:

```text
valid identifier format
canonical URL structure
provider provenance
required title presence
publication metadata sanity
deduplication integrity
cross-provider identifier consistency
```

Do not call a paper scientifically verified because its metadata was normalized.

---

# 20. Retractions

If a provider exposes retraction status, preserve it.

A retracted paper must not be discarded silently.

Represent clearly:

```text
is_retracted = True
```

and preserve the provider/source of that status.

If retraction status is unknown:

```text
None
```

not `False`.

---

# 21. Preprints

Preprints must remain distinguishable from peer-reviewed publications.

Do not automatically exclude them.

Do not automatically treat them as equivalent to peer-reviewed sources.

Preserve source type / publication status when available.

This distinction will matter later for evidence quality.

---

# 22. Citation Counts

Citation counts are metadata, not quality proof.

If stored, preserve:

```text
provider
count
retrieved_at
```

Do not convert citation count into SourceQuality automatically.

Do not use citation count as a hidden ranking score.

---

# 23. Search Ranking

Preserve provider ranking information if returned.

Do not treat provider rank as scientific validity.

Represent ranking only as retrieval metadata.

---

# 24. Abstract Handling

Abstracts may be stored as provider-supplied metadata.

Do not treat an abstract as equivalent to full-text evidence.

Phase 2B must not create claim-support EvidenceRecords from abstracts.

---

# 25. Full Text

Do NOT implement broad full-text paper downloading in Phase 2B unless strictly required for provider metadata verification.

No PDF scraping pipeline yet.

No OCR pipeline yet.

No publisher bypass.

No paywall circumvention.

Full-text evidence extraction belongs to later scope.

---

# 26. Academic Search Result Contract

Create a provider-neutral result envelope conceptually containing:

```text
provider
query_id
research_run_id

status
attempts

requested_limit
returned_count

candidates

rate_limit_info
errors

started_at
completed_at
```

Statuses should distinguish at least:

```text
SUCCESS
PARTIAL
EMPTY
RATE_LIMITED
AUTH_ERROR
PROVIDER_ERROR
INVALID_RESPONSE
TIMEOUT
```

Adapt names to existing conventions.

---

# 27. Empty Results

An empty result is not a provider failure.

Represent:

```text
EMPTY
```

distinctly.

The research branch should be able to distinguish:

```text
provider worked but found nothing
```

from:

```text
provider could not be queried
```

---

# 28. Provider Response Validation

Never trust raw provider JSON directly.

Each provider response must pass deterministic validation before becoming canonical candidates.

Malformed records should be rejected individually where possible.

One bad record should not necessarily discard the entire provider response.

Track:

```text
raw_count
accepted_count
rejected_count
rejection_reasons
```

---

# 29. Rejected Candidate Ledger

Create an auditable rejected academic candidate ledger.

Record at least:

```text
provider
query_id
reason
provider_record_identifier if available
safe summary of offending metadata
```

Do not store secrets.

Do not store hidden model reasoning.

---

# 30. Research Coverage Integration

Update Phase 2A research coverage for the `ACADEMIC` branch.

Track:

```text
required
planned
started
completed
failed

query_count
candidate_count
verified_source_count

provider_success_count
provider_failure_count
provider_empty_count
```

Coverage remains operational, not scientific evidence quality.

---

# 31. Academic Branch Graph

Implement the academic branch as a dedicated subgraph or clearly isolated graph section.

Conceptual flow:

```text
LOAD_VERIFIED_QUERY_PLAN
    ↓
SELECT_ACADEMIC_QUERIES
    ↓
ENFORCE_ACADEMIC_BUDGET
    ↓
DISPATCH_TO_ACADEMIC_PROVIDERS
    ↓
NORMALIZE_PROVIDER_RESULTS
    ↓
VERIFY_ACADEMIC_CANDIDATES
    ↓
DEDUPLICATE_LOGICAL_SOURCES
    ↓
MERGE_PROVIDER_OBSERVATIONS
    ↓
UPDATE_ACADEMIC_COVERAGE
    ↓
END
```

Do not mix patent/product/open-source retrieval into this graph.

---

# 32. Parallelism

Provider searches may be designed for later parallel execution, but correctness must not depend on concurrency.

If implementing async execution in this phase would destabilize the established graph, keep deterministic sequential execution and document async as deferred technical debt.

Do not redesign the whole workflow merely to gain parallelism.

---

# 33. Consensus Connector

Implement the Consensus connector using its current documented API contract available to the environment/project.

Requirements:

- isolate provider-specific DTOs
- preserve paper identifiers returned by Consensus
- preserve Consensus-specific relevance/ranking metadata only as provider metadata
- normalize DOI and other strong identifiers where available
- map records into canonical candidates
- explicit auth/rate-limit/error handling
- fake provider/fixture support

Do not let Consensus summaries become scientific evidence.

If the API returns synthesized AI text, treat it as provider-generated secondary metadata, not as paper evidence.

---

# 34. OpenAlex Connector

Implement OpenAlex support.

Preserve when available:

```text
OpenAlex work ID
DOI
title
publication year/date
authorship
host venue/source
type
cited_by_count
open-access metadata
primary location
```

Normalize the OpenAlex identifier.

OpenAlex metadata is bibliographic metadata, not evidence.

---

# 35. Semantic Scholar Connector

Implement Semantic Scholar support.

Preserve when available:

```text
paperId
externalIds
title
abstract
authors
year
venue
publicationTypes
citationCount
url
```

Normalize external identifiers.

Semantic Scholar's citation metadata must remain provider-specific/time-sensitive.

---

# 36. Provider Capability Matrix

Document connector capabilities.

Do not hardcode unsupported assumptions about provider capabilities.

Document only what the implemented provider contract actually returns.

---

# 37. Search Query Sanitization

Reuse Phase 2A PII minimization and query verification.

Academic connectors must never reconstruct removed PII from ProjectState or other workflow state.

No connector may receive:

```text
student name
email
phone
national ID
school name
home address
```

unless a future explicit architecture decision allows it.

Add tests.

---

# 38. Prompt Injection

Academic API metadata is untrusted content.

Titles, abstracts, snippets, or provider-generated text containing:

```text
Ignore previous instructions
```

must remain data.

They must never mutate:

```text
ProjectState
ResearchRun control flow
scores
trust gate
system prompts
```

Add deterministic tests.

---

# 39. No ProjectState Mutation

Academic retrieval must not alter canonical project facts.

It may update research state and source registries only.

Add a hard test:

```text
ProjectState before academic search
==
ProjectState after academic search
```

---

# 40. No Evidence Creation

Phase 2B must create:

```text
SourceCandidate
SourceRecord / verified academic source metadata
provider observations
research coverage
```

Phase 2B must NOT create:

```text
EvidenceRecord
SUPPORTED ClaimRecord
VERIFIED ClaimRecord
Novelty conclusion
Research Gap conclusion
Score
Readiness classification
```

Add release-blocking tests.

---

# 41. SourceRecord Integration

Integrate verified academic logical sources with the existing canonical source registry in the research layer.

Do not duplicate source truth in multiple incompatible collections.

If `ProjectState.sources` remains intentionally separate by architecture, preserve that decision and document the integration boundary.

Do not silently change ownership.

---

# 42. Source Quality

Do not invent source quality merely because a record comes from an academic API.

Provider presence does not prove:

```text
peer reviewed
high quality
methodologically sound
relevant
non-retracted
```

Only populate source-quality fields when supported by explicit metadata and existing contracts.

Otherwise leave unknown.

---

# 43. Academic Research Eval Dataset

Create a deterministic Gold dataset with at least:

```text
40 cases
```

Suggested location:

```text
evals/academic_retrieval/v1/
```

Cover at least:

```text
same DOI returned by all three providers
same DOI with different DOI formatting
same title but different DOI
missing DOI
OpenAlex-only identifier
Semantic Scholar-only identifier
arXiv preprint
review article
conference paper
unknown source type
retracted source
retraction unknown
conflicting years
conflicting titles
citation-count disagreement
empty provider result
single provider timeout
single provider rate limit
single provider auth failure
all providers fail
malformed record among valid records
duplicate records inside one provider
PII contamination attempt
prompt injection inside abstract
Arabic-origin query
mixed-language query
budget truncation
provider result limit enforcement
ProjectState immutability
no EvidenceRecord creation
no claim-status mutation
```

Synthetic data only.

No real student identity information.

---

# 44. Academic Retrieval Metrics

Measure at minimum:

```text
identifier_normalization_accuracy
cross_provider_dedup_accuracy
provider_observation_preservation
metadata_merge_accuracy
rejected_candidate_accuracy
provider_failure_isolation_accuracy
budget_enforcement_accuracy
source_traceability
project_state_mutation_rate
evidence_creation_violation_rate
claim_mutation_violation_rate
pii_leakage_rate
```

Each measurable metric should expose numerator/denominator.

Unmeasured metrics must return `None`, not zero.

---

# 45. Release-Blocking Safety Targets

Deterministic hard gates:

```text
PII leakage = 0
ProjectState mutation = 0
EvidenceRecord creation by Phase 2B = 0
Claim support/status mutation by Phase 2B = 0
Untraceable verified source = 0
Invalid strong-identifier merge = 0
Cross-provider provenance loss = 0
```

Any violation blocks the next phase.

---

# 46. Negative Controls

The eval must be capable of failing.

Add negative-control tests that deliberately demonstrate detection of at least:

```text
PII leakage
ProjectState mutation
Evidence creation
wrong DOI merge
provider provenance loss
```

A safety suite that cannot fail is not sufficient.

---

# 47. Offline Deterministic Providers

Create deterministic fakes/mocks for all three providers.

At minimum:

```text
FakeConsensusProvider
FakeOpenAlexProvider
FakeSemanticScholarProvider
```

Standard tests must require:

```text
no internet
no credentials
no API keys
```

---

# 48. Live Connector Smoke Tests

Live tests may exist but must be explicitly opt-in.

They should verify only basic compatibility and response parsing.

They must NOT become the Gold baseline.

Live API responses are non-deterministic and time-sensitive.

Record live status separately:

```text
NOT RUN
PASS
FAIL
```

Do not silently report skipped live tests as successful execution.

---

# 49. Versioning

Preserve versions for:

```text
academic_retrieval_contract_version
connector implementation version
normalizer version
deduplication version
eval dataset version
provider
retrieval timestamp
```

Later evaluations must be reproducible.

---

# 50. Observability

Add structured observability sufficient to answer:

```text
Which query was sent?
Which provider received it?
How many raw records came back?
How many were rejected?
How many canonical candidates remained?
Which logical sources were deduplicated?
Which providers observed each source?
Why did any provider fail?
```

Do not log credentials.

Do not log unnecessary PII.

---

# 51. Documentation

Create:

```text
docs/phase2b_academic_research_connectors.md
```

Document:

- connector architecture
- provider isolation
- query eligibility
- budgets
- retries
- rate limits
- credentials
- normalization
- identifier rules
- deduplication
- provider observations
- metadata merge policy
- retractions
- preprints
- citation metadata
- rejected candidate ledger
- coverage
- evals
- live-test policy
- known limitations

---

# 52. ADR — Academic Provider Isolation

Create:

```text
docs/adr/ADR-008-academic-provider-isolation.md
```

Decision:

> Academic connectors are isolated providers. Failure, timeout, malformed data, or rate limiting in one provider must not erase successful results from another provider.

---

# 53. ADR — Logical Source vs Provider Observation

Create:

```text
docs/adr/ADR-009-logical-source-provider-observation.md
```

Decision:

> Cross-provider deduplication creates one logical source while preserving every provider observation and provider-specific metadata.

Rejected design:

```text
first provider wins
```

because it destroys provenance and may discard useful metadata or disagreement.

---

# 54. ADR — Academic Retrieval Is Not Evidence

Create:

```text
docs/adr/ADR-010-academic-retrieval-is-not-evidence.md
```

Decision:

> Academic retrieval and bibliographic verification stop at verified source metadata. Scientific evidence extraction and claim support are separate later phases.

---

# 55. Architecture Update

Update architecture narrowly to show:

```text
Verified Academic Query
        ↓
Provider Dispatch
        ↓
Consensus / OpenAlex / Semantic Scholar
        ↓
Provider Results
        ↓
Canonical SourceCandidates
        ↓
Cross-Provider Identity Resolution
        ↓
Verified Academic Sources
        ↓
[LATER PHASE]
Evidence Extraction
```

Do not broadly rewrite previous architecture.

---

# 56. Existing Trust Guarantees

The following must remain intact:

```text
Zero Assumption
verbatim-first intake
student claim isolation
ProjectState / EvaluationGraphState ownership
checkpoint integrity
query provenance
PII minimization
anti-confirmation-bias planning
search-result-is-not-evidence
official/advisory separation
canonical source identity
English-only developer surfaces
offline deterministic standard tests
```

No existing validator or safety gate may be weakened.

---

# 57. Regression Requirements

All prior tests must pass.

Reference baseline:

```text
961 passed
15 skipped
0 failed
```

The final count should increase.

Do not delete prior tests.

Do not weaken test assertions merely to accommodate provider integration.

---

# 58. Before Coding

Before implementation:

1. Read `docs/mawhiba_agent_system_architecture_v1.md`.
2. Read all Phase 2A and 2A.1 docs.
3. Inspect source identity contracts.
4. Inspect `SourceFingerprint`.
5. Inspect research graph/state.
6. Inspect research eval architecture.
7. Inspect shared LLM invocation/retry patterns for architectural consistency.
8. Inspect config/settings.
9. Inspect existing source registry ownership.
10. Confirm Git starting state.
11. Present a concise implementation plan.
12. Identify any blocking architecture conflicts.

If no blocking conflict exists, proceed.

Do not ask for confirmation for minor choices.

---

# 59. Git Discipline

Work only on:

```text
feat/phase2b-academic-research-connectors
```

Before implementation confirm:

```text
git status
git branch --show-current
git log -1 --oneline
```

Expected:

```text
branch:
feat/phase2b-academic-research-connectors

starting commit:
a8aaca0 merge: Phase 2A research foundation

working tree:
clean
```

Do not rewrite `main`.

Do not merge into `main` automatically.

Do not force-push.

At the end, commit Phase 2B separately and leave it on the feature branch for review.

---

# 60. Run

Run the full deterministic suite:

```powershell
python -m pytest
```

Run the new academic retrieval eval command.

Do not run live integrations automatically.

If live tests exist, report them as skipped unless explicitly opted in.

---

# 61. Final Report

Respond in English only.

Use exactly these sections:

## Phase 2B Result

## Starting Git State

Include:
- branch
- starting commit
- working-tree state

## Academic Connector Architecture

Explain:
- provider abstraction
- connector isolation
- supported providers

## Query Eligibility and Budgets

Explain:
- which query purposes route to academic search
- query/result budgets

## Provider Implementations

Separate:

### Consensus

### OpenAlex

### Semantic Scholar

For each explain:
- request model
- response validation
- identifiers
- errors
- rate-limit behavior

## Source Candidate Boundary

Confirm academic retrieval still does not create EvidenceRecords.

## Identifier Normalization

Show supported canonical identifiers.

## Cross-Provider Deduplication

Explain:
- logical source
- provider observations
- strong identifier priority
- title-only dedup is forbidden

## Metadata Merge Rules

Explain conflict handling.

## Retractions and Preprints

Explain exact semantics.

## Provider Failure Isolation

Show deterministic examples/results.

## Privacy / PII

Confirm query minimization remains enforced.

## Prompt Injection Resistance

Confirm academic metadata is treated as data.

## Research Coverage

Show academic branch counters.

## Academic Gold Dataset

Provide:
- number of cases
- languages/categories
- major edge cases

## Academic Retrieval Metrics

Provide exact deterministic metrics.

## Safety Gates

Provide exact results for:

```text
PII leakage
ProjectState mutation
Evidence creation violations
Claim mutation violations
Untraceable verified sources
Invalid identifier merges
Provider provenance loss
```

## Negative Controls

Confirm deliberately injected failures are detected.

## Files Created

## Files Modified

## Tests

Provide exact:

```text
passed
skipped
failed
```

Separate:
- deterministic tests
- skipped live tests
- live tests actually executed

## Git End State

Provide:

```text
git status
git branch --show-current
git log -3 --oneline
git diff --stat main...HEAD
```

Do NOT merge.

## Remaining Limitations

## Technical Debt

## Regression Status

Confirm all previous trust gates and tests remain intact.

## Status

Use exactly one:

`READY FOR EVIDENCE EXTRACTION PHASE`

or:

`BLOCKED`

Do NOT implement evidence extraction.
Do NOT implement patent/product/open-source connectors.
Do NOT implement Phase 2C automatically.
