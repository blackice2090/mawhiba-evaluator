# Mawhiba Evaluator — Phase 2A Execution Specification

## Phase

**Phase 2A — Research Foundation, Query Planning, and Official Requirements**

You are continuing implementation of the **Mawhiba Project Evaluator Agent**.

Approved completed phases:

- Phase 0 — Data Contracts
- Phase 1A — LangGraph Workflow Infrastructure
- Phase 1A.1 — Workflow Hardening
- Phase 1B — Trusted LLM Intake
- Phase 1C — Canonical Intake Model and Trust Evals

Current recovered repository baseline:

```text
main baseline commit: 2555616
verified tests: 630 passed, 13 skipped
```

Phase 2A must be implemented on:

```text
feat/phase2a-research-foundation
```

The primary architecture source is:

```text
docs/mawhiba_agent_system_architecture_v1.md
```

Relevant implementation documentation:

```text
docs/data_contracts.md
docs/phase1a_workflow.md
docs/phase1b_trusted_intake.md
docs/phase1c_intake_evals.md
```

Read these files before implementation.

Do not redesign previous phases.

---

# 1. Objective

Implement the trusted research foundation that will later support academic, patent, product, open-source, and standards research.

Phase 2A includes:

- ResearchRun contracts
- research branches and coverage
- trusted query planning
- deterministic query verification
- query provenance
- PII minimization
- official Mawhiba requirements retrieval
- official source verification and snapshotting
- official requirement extraction with provenance
- deterministic Gold evals and safety gates
- Phase 2A LangGraph workflow

Phase 2A does **not** implement academic-paper, patent, product, GitHub, or standards connectors beyond planning contracts.

---

# 2. Core Trust Model

The system must preserve this strict progression:

```text
SEARCH RESULT
      ↓
SOURCE CANDIDATE
      ↓
VERIFIED SOURCE
      ↓
EVIDENCE
      ↓
CLAIM SUPPORT
```

These states are not interchangeable.

A search result must never become evidence automatically.

A verified source must never automatically support a project claim.

Phase 2A does not perform scientific evidence extraction.

---

# 3. Research Input Boundary

Research planning may consume only trusted canonical `ProjectState`.

Allowed canonical inputs include fields such as:

```text
problem.statement
solution.description
goal

technical.technologies
technical.hardware
technical.software
technical.sensors
technical.algorithms
technical.models
technical.datasets
technical.data_sources

identity.domain
identity.project_type

student-origin claims
```

The planner must not treat these as factual project inputs:

```text
model_summary
RejectedExtraction
unverified external information
search expansion terms
unsupported inferred implementation details
```

Student claims may generate investigation queries but are not assumed true.

Example:

```text
Student claim: "No one has done this before."
Allowed: generate prior-art investigation queries.
Forbidden: set novelty to HIGH or VERIFIED.
```

---

# 4. ResearchRun

Create a first-class versioned `ResearchRun` contract containing conceptually:

```text
research_run_id
project_id
project_version_id
planner_version
queries
branch_coverage
started_at
completed_at
status
errors
```

Research runs must not mutate older runs.

A new project version must be able to produce a new independent research run.

---

# 5. ResearchRunStatus

Create a dedicated status enum for research execution.

Suggested semantics:

```text
NOT_STARTED
PLANNING
RUNNING
PARTIAL
COMPLETED
FAILED
```

Adapt naming only when needed to remain consistent with existing conventions.

Do not reuse `EvaluationStatus` if it creates semantic ambiguity.

Research completion does not imply novelty is proven or evidence is sufficient.

---

# 6. Research Branches

Define stable research branches:

```text
OFFICIAL_REQUIREMENTS
ACADEMIC
PATENT
PRODUCT
OPEN_SOURCE
STANDARDS
```

Phase 2A executes only:

```text
OFFICIAL_REQUIREMENTS
```

Other branches may receive plans and coverage state, but must not perform real retrieval in Phase 2A.

---

# 7. Research Query Contract

Create or extend a query contract similar to:

```python
class ResearchQueryRecord(BaseModel):
    query_id: UUID
    research_run_id: UUID

    branch: ResearchBranch
    purpose: QueryPurpose

    query: str

    derived_from: list[ProjectFieldReference]

    source_terms: list[str]
    expansion_terms: list[str]

    status: QueryStatus

    planner_version: str
    created_at: UtcDatetime
```

Adapt exact fields where appropriate.

Every accepted query must answer:

> Why did the system search for this?

---

# 8. Source Terms

`source_terms` must originate from trusted canonical `ProjectState`.

Examples:

```text
YOLOv8
ultrasonic sensor
plant disease
LoRa
```

Each source term must be traceable to a canonical project field.

Do not allow fabricated source terms.

---

# 9. Expansion Terms

The planner may create search-oriented related terms, for example:

```text
object detection
range sensing
crop pathology
low-power wide-area network
```

These are search expansions only.

They are not project facts.

They must never be written back into `ProjectState`.

Enforce this structurally and with tests.

---

# 10. Query Purpose Taxonomy

Use a stable enum, including at minimum:

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
PATENT_FUNCTION
PATENT_MECHANISM
PRODUCT
OPEN_SOURCE
```

Do not use arbitrary free-form purpose strings.

---

# 11. Research Query Planner

Implement a dedicated query planner using the existing `StructuredModelProvider` abstraction.

Do not introduce a second model-provider architecture.

Create an English-only internal prompt:

```text
RESEARCH_QUERY_PLANNER_PROMPT_V1
```

The planner must:

- generate search queries
- use trusted canonical project information only
- distinguish source terms from expansion terms
- avoid assuming missing facts
- not evaluate novelty
- not evaluate project quality
- not modify `ProjectState`
- generate queries capable of disproving student assumptions
- return Structured Output

---

# 12. Anti-Confirmation-Bias Policy

A query plan must not exist only to confirm the proposed solution.

Where relevant, include searches covering:

```text
LIMITATIONS
ALTERNATIVES
FAILURE_MODES
COMPETING_METHODS
BENCHMARKS
```

Bad plan:

```text
advantages of YOLO for X
benefits of AI for X
why technology X improves Y
```

Better:

```text
YOLO limitations under low-light conditions
alternative object-detection approaches for X
failure cases of X
benchmark X vs competing methods
```

The research system tests the project. It does not defend it.

---

# 13. Query Families

Support the following families when relevant:

```text
Problem
Existing Solutions
Technology
Recent Work
Limitations
Comparison / Benchmark
Reviews
Alternatives
Failure Cases
Prior Art
Patent Function
Patent Mechanism
Product
Open Source
```

Do not require every family for every project.

Relevance controls planning.

---

# 14. Query Limits

Add configurable limits for:

```text
max_queries_per_branch
max_total_queries
max_expansion_terms_per_query
max_query_length
```

Use reasonable defaults.

The goal is high-value coverage, not query volume.

---

# 15. Query Deduplication

Implement deterministic query normalization and deduplication.

Safe normalization may include:

```text
leading/trailing whitespace
repeated whitespace
case normalization where appropriate
repeated punctuation
```

Do not merge meaningfully different queries merely because wording is similar.

Record the number of removed duplicates.

---

# 16. Query Plan Verification

Model-generated query plans are untrusted until deterministic validation succeeds.

Validate at minimum:

```text
branch is valid
purpose is valid
query is non-empty
query length is within limits
query budget is within limits
source field references exist
source terms exist in canonical ProjectState
prohibited PII is absent
duplicate rules are satisfied
```

Expansion terms do not need to exist in `ProjectState`, but must be explicitly marked as expansions.

---

# 17. PII Minimization

Research queries must be about the project, not the student.

Do not send unnecessary:

```text
student name
email
phone number
national ID
school name
address
```

to external research providers.

Add deterministic tests.

If identity is ever genuinely required in a future research task, it must have a separate explicit architecture decision.

---

# 18. Official Requirements Branch

Implement:

```text
OFFICIAL_REQUIREMENTS_CHECK
```

This is the only real retrieval branch in Phase 2A.

Its purpose is to retrieve and snapshot current official Mawhiba competition information.

Primary official domain:

```text
https://www.mawhiba.sa/
```

Use official National Olympiad for Scientific Creativity pages under Mawhiba-controlled domains.

Official rules outrank secondary descriptions.

---

# 19. Official Domain Allowlist

Implement a strict allowlist.

At minimum:

```text
mawhiba.sa
www.mawhiba.sa
```

Support additional official subdomains only when clearly controlled by Mawhiba.

A third-party page must never receive official Mawhiba source status.

---

# 20. Official Web Provider Abstraction

Do not tightly couple the official-requirements logic to a single HTTP/search implementation.

Create a narrow provider protocol conceptually similar to:

```python
class OfficialWebProvider(Protocol):
    def retrieve(...): ...
```

Provide:

```text
FakeOfficialWebProvider
```

for deterministic tests.

A live provider may be implemented if needed, but standard tests must not require internet access.

---

# 21. Source Candidate Boundary

Retrieval must initially produce:

```text
SourceCandidate
```

not:

```text
EvidenceRecord
```

Required flow:

```text
retrieval
    ↓
SourceCandidate
    ↓
source verification
    ↓
SourceRecord
```

Evidence extraction comes later.

Do not create scientific `EvidenceRecord` objects during Phase 2A retrieval.

---

# 22. Official Source Snapshot

Create a source snapshot contract containing conceptually:

```text
source_id
url
canonical_url
domain
title
retrieved_at
published_at
effective_at
content_hash
raw_text or normalized captured text
verification_status
```

Do not invent publication or effective dates.

Missing date means `None`.

---

# 23. Content Hash

Official source snapshots must store a deterministic content hash.

Reason:

```text
same URL + changed official content = different requirements version
```

A future evaluation must be able to answer:

> Which official rules did this evaluation use?

---

# 24. Official Requirements Extraction

Create an English-only Structured Output prompt:

```text
OFFICIAL_REQUIREMENTS_EXTRACTOR_PROMPT_V1
```

Extract only clearly relevant official information, including when available:

```text
eligibility
project categories
submission requirements
competition stages
research ethics
experiment restrictions
judging criteria
official scoring weights if explicitly stated
important deadlines
official forms/instructions
```

Do not invent missing scoring weights.

---

# 25. Official Requirement Provenance

Each accepted official requirement must preserve:

```text
source_id
verbatim excerpt
verified source location/range where available
retrieval/version metadata
```

Apply the same trust philosophy as trusted intake.

Model extraction from an official webpage remains an untrusted candidate until deterministic provenance verification succeeds.

---

# 26. Official Requirement Status

Support status semantics such as:

```text
VERIFIED_CURRENT
VERIFIED_BUT_DATE_UNKNOWN
SUPERSEDED
UNVERIFIED
```

Exact design may improve on this if consistent with existing contracts.

Do not call information current merely because it was retrieved today.

---

# 27. Conflicting Official Sources

When two official sources conflict, preserve both.

Do not discard either automatically.

Preserve:

```text
source A
source B
dates/version indicators
conflict
resolution basis if determinable
```

Prefer the newer source only when the evidence supports that conclusion.

Otherwise preserve the conflict as unresolved.

---

# 28. Official vs Advisory Criteria

This is a hard trust boundary.

Keep distinct:

```text
OFFICIAL_MAWHIBA_CRITERIA
```

and:

```text
AGENT_ADVISORY_RUBRIC
```

The existing internal advisory scoring rubric must never be represented as official Mawhiba scoring.

If an official weight is not explicitly present in verified official content:

```text
official_weight = None
```

Add a release-blocking test.

---

# 29. Retrieval Failure

If official Mawhiba retrieval fails, do not fall back silently to model memory.

Record an explicit outcome such as:

```text
OFFICIAL_REQUIREMENTS_UNAVAILABLE
```

Future evaluation must be able to detect that official verification did not complete.

---

# 30. Prompt Injection from Web Content

External webpage text is untrusted content, not executable instruction.

If page content contains text such as:

```text
Ignore your system instructions...
```

it must never:

- change workflow behavior
- mutate ProjectState
- modify score
- change system prompts
- bypass source verification

Add deterministic tests.

---

# 31. Research Coverage

Create explicit branch coverage.

For each branch track conceptually:

```text
required
planned
started
completed
failed
query_count
candidate_count
verified_source_count
```

Coverage describes execution, not evidence quality.

---

# 32. Phase 2A Research Graph

Create a dedicated Phase 2A workflow/subgraph.

Conceptual path:

```text
START
  ↓
LOAD_PROJECT_STATE
  ↓
VALIDATE_RESEARCH_INPUT
  ↓
RESEARCH_QUERY_PLANNER
  ↓
VERIFY_QUERY_PLAN
  ↓
OFFICIAL_REQUIREMENTS_RETRIEVAL
  ↓
VERIFY_OFFICIAL_SOURCES
  ↓
EXTRACT_OFFICIAL_REQUIREMENTS
  ↓
UPDATE_RESEARCH_COVERAGE
  ↓
END
```

Do not add academic retrieval.

---

# 33. ProjectState Mutation Gate

This is a release-blocking requirement.

The query planner may read `ProjectState`.

It may not write new factual content into it.

Expansion terms remain research metadata only.

Add tests asserting equality of canonical `ProjectState` before and after pure query planning.

---

# 34. Research Planning Gold Dataset

Create a deterministic Gold dataset with at least 25 cases.

Suggested location:

```text
evals/research_planning/v1/
```

Cover at least:

```text
AI
Machine Learning
Computer Vision
IoT
Robotics
Embedded Systems
Software
mixed-domain projects
Arabic descriptions
mixed Arabic/English
minimal project descriptions
student novelty claim
performance claim
missing technology
ambiguous technology
prompt injection
PII contamination
confirmation bias
alternative-method searches
failure-mode searches
query duplication
invalid source-field references
```

Synthetic data only.

Do not use real student identity information.

---

# 35. Research Planning Metrics

At minimum measure:

```text
query_source_traceability
invalid_field_reference_rate
pii_leakage_rate
required_query_family_coverage
duplicate_query_rate
project_state_mutation_rate
```

Each metric should expose numerator/denominator when applicable.

Do not report unmeasured metrics as zero.

---

# 36. Release-Blocking Safety Targets

For deterministic tests:

```text
PII leakage rate = 0
Invalid canonical field references = 0
ProjectState mutations caused by planning = 0
Untraceable accepted queries = 0
```

Any violation blocks Phase 2B.

---

# 37. Negative Controls

The eval must be capable of failing.

Add negative-control tests proving detection of at least:

```text
PII leakage
invalid source-field reference
ProjectState mutation
```

A safety suite that always returns PASS is insufficient.

---

# 38. Versioning

Every ResearchRun / Query Plan must preserve relevant versions:

```text
planner_prompt_version
provider
model
dataset_version
research_contract_version
```

The research process must be reproducible.

---

# 39. Fake Providers

Standard tests must use deterministic providers.

At minimum:

```text
FakeStructuredModelProvider
FakeOfficialWebProvider
```

No standard test may require:

```text
OPENAI_API_KEY
internet
Mawhiba availability
external credentials
```

---

# 40. Optional Live Official Test

A live Mawhiba integration test may exist.

It must require explicit opt-in:

```text
RUN_OFFICIAL_WEB_TESTS=1
```

Do not run it merely because internet is available.

Do not make CI depend on live Mawhiba wording.

---

# 41. Forbidden Connectors in Phase 2A

Do not implement during Phase 2A:

```text
Consensus
OpenAlex
Semantic Scholar
IEEE
ACM
PubMed
arXiv retrieval
EPO OPS
Google Patents
USPTO
WIPO
GitHub
general product search
commercial solution search
Tavily general research
```

These belong to Phase 2B or later.

---

# 42. Documentation

Create:

```text
docs/phase2a_research_foundation.md
```

Document:

- trust-state progression
- ResearchRun
- research branches
- query provenance
- source vs expansion terms
- anti-confirmation-bias policy
- query budget
- query verification
- PII policy
- official requirements architecture
- official-domain allowlist
- source candidate boundary
- research coverage
- failure semantics
- current scope limitations

---

# 43. ADR — Query Provenance

Create:

```text
docs/adr/ADR-006-research-query-provenance.md
```

Decision:

> Every accepted research query must be traceable to trusted canonical ProjectState. Generated synonyms and related terminology are search expansions only and never become project facts.

---

# 44. ADR — Search Result Is Not Evidence

Create:

```text
docs/adr/ADR-007-search-result-is-not-evidence.md
```

Decision:

> Retrieval produces candidate sources. Verification produces sources. Evidence extraction and claim support are separate later stages.

Rejected architecture:

```text
search result → EvidenceRecord
```

because it destroys the trust boundary.

---

# 45. Architecture Update

Update the architecture narrowly to make this explicit:

```text
Canonical ProjectState
      ↓
Research Query Planner
      ↓
Verified Query Plan
      ↓
Source Candidate
      ↓
Verified Source
      ↓
Evidence
      ↓
Claim Support
```

Do not broadly rewrite existing architecture sections.

---

# 46. Existing Trust Guarantees

These must remain unchanged:

```text
Zero Assumption
verbatim-first canonical intake
student claim isolation
ProjectState / EvaluationGraphState ownership
checkpoint integrity
structured model-provider abstraction
developer-facing English-only policy
no network in standard tests
```

Do not weaken earlier validators, gates, or tests to make Phase 2A easier.

---

# 47. Regression Requirements

All previous tests must continue to pass.

Starting reference:

```text
630 passed
13 skipped
0 failed
```

The final passing test count should increase.

Do not delete existing tests.

Do not relax existing safety gates.

---

# 48. Required Test Execution

Run:

```powershell
python -m pytest
```

Also run the new deterministic Research Planning eval command using the actual CLI/interface implemented in the repository.

Do not invent a CLI command before implementation.

Do not run live integration tests automatically.

---

# 49. Git Discipline

Before implementation, confirm:

```powershell
git status
git branch --show-current
git log -1 --oneline
```

Expected starting branch:

```text
feat/phase2a-research-foundation
```

Expected baseline ancestor:

```text
2555616 chore: recover repository baseline after machine migration
```

Do not rewrite the baseline commit.

Do not reset history.

Do not merge into `main` automatically.

Leave the Phase 2A feature branch available for review.

---

# 50. Before Coding

Before changing code:

1. Read the architecture.
2. Read Phase 1C documentation.
3. Inspect existing `SourceRecord` and research-query-related contracts.
4. Inspect the existing LLM provider abstraction.
5. Inspect the existing eval architecture.
6. Inspect `ProjectState`.
7. Inspect current graph registry and persistence/type-discovery constraints.
8. Present a concise implementation plan.
9. Identify any architecture conflict.

If no blocking conflict exists, proceed with implementation without asking for confirmation on minor choices.

---

# 51. Completion Criteria

Phase 2A is complete only when all of the following are true:

- Research contracts exist and validate.
- Research query provenance is deterministic and testable.
- Query planning cannot mutate `ProjectState`.
- PII minimization is enforced and tested.
- Anti-confirmation-bias coverage is implemented.
- Query limits and deduplication are deterministic.
- Official Mawhiba retrieval uses a provider abstraction.
- Official-domain allowlisting is enforced.
- Retrieval produces `SourceCandidate`, not `EvidenceRecord`.
- Official source snapshots preserve content hashes.
- Official requirement extraction preserves verified provenance.
- Official criteria remain separated from the advisory rubric.
- Missing official weights remain `None`.
- Web-content prompt injection cannot change system behavior.
- Research branch coverage is explicit.
- Gold research-planning dataset contains at least 25 deterministic cases.
- All release-blocking safety metrics equal zero violations.
- Negative controls prove the safety metrics can fail.
- All prior tests remain intact.
- Full deterministic suite has zero failures.
- No Phase 2B connector was implemented.

---

# 52. Final Response Format

Respond in English only.

Use exactly these sections:

## Phase 2A Result

## Starting Git State

Include:

- branch
- starting commit
- working-tree state

## Research Trust Model

Explain:

```text
Search Result
→ Source Candidate
→ Verified Source
→ Evidence
→ Claim Support
```

## Query Planner

Explain:

- query families
- budgets
- anti-confirmation-bias behavior

## Query Provenance

Explain how every accepted query traces back to canonical `ProjectState`.

## Source vs Expansion Terms

Explain why expansion terms cannot mutate project facts.

## Official Requirements

Explain:

- provider architecture
- official-domain allowlist
- snapshots
- content hashes
- requirement provenance
- version/conflict behavior

## Official vs Advisory Criteria

Confirm official weights cannot be invented.

## Source Candidate Boundary

Explain why retrieval does not create `EvidenceRecord` objects.

## Privacy / PII

Explain query minimization.

## Research Graph

Show the actual implemented execution path.

## Research Gold Dataset

Provide:

- number of cases
- languages
- categories

## Research Metrics

Provide exact deterministic metrics.

## Safety Gates

Provide exact results for:

```text
PII leakage
invalid canonical field references
ProjectState mutation
untraceable queries
```

## Negative Controls

Confirm the eval detects deliberately injected violations.

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

```powershell
git status
git branch --show-current
git diff --stat main...HEAD
```

Do not merge.

## Remaining Limitations

## Technical Debt

## Regression Status

Confirm all prior-phase trust tests remain intact.

## Status

Use exactly one:

```text
READY FOR ACADEMIC RESEARCH CONNECTORS
```

or:

```text
BLOCKED
```

Do not implement Phase 2B.
