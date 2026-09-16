# Phase 2B — Academic Research Connectors

**Status:** Implemented
**Scope:** Consensus, OpenAlex and Semantic Scholar connectors; academic query
eligibility and budgets; deterministic normalization, verification,
cross-provider identity resolution and conservative merging; the academic branch
graph; coverage; and a 51-case Gold evaluation.
**Amended by Phase 2B.1:** provider API contract verification and hardening
(section 2a).
**Prior phases:** `docs/phase2a_research_foundation.md`, `docs/phase2a1_hardening.md`
**Decision records:** ADR-008 (provider isolation), ADR-009 (logical source vs
provider observation), ADR-010 (academic retrieval is not evidence). ADR-006 and
ADR-007 are unchanged and still binding.

Phase 2B connects the trusted Phase 2A research foundation to real academic
providers. It does **not** implement evidence extraction, patent, product,
open-source or standards retrieval.

---

## 1. Trust-state progression

```text
Verified Query Plan          Phase 2A, ADR-006
        |
        v
Academic Retrieval           three isolated providers, ADR-008
        |
        v
AcademicSourceCandidate      one provider's untrusted record
        |
        v
Source Verification          deterministic, metadata only
        |
        v
LogicalAcademicSource        one work, every observation kept, ADR-009
        |
        v
SourceRecord                 Phase 0 contract, VERIFIED_METADATA, UNRATED
        |
        v
[LATER PHASE] Evidence Extraction  ADR-010
```

The hard rule, unchanged from ADR-007 and restated in ADR-010:

```text
Academic search result  !=  Verified source  !=  Evidence  !=  Supported claim
```

---

## 2. Connector architecture

```text
src/research/academic/
    identifiers.py      DOI / PMID / OpenAlex / S2 / arXiv / URL normalization
    http.py             failure kinds, retry classification, bounded backoff
    client.py           JSON HTTP, transport faults -> the project's vocabulary
    provider.py         the Protocol, plus the shared transport/limit/envelope base
    consensus.py        Consensus DTOs, mapping and live connector
    openalex.py         OpenAlex DTOs, mapping and live connector
    semantic_scholar.py Semantic Scholar DTOs, mapping and live connector
    fakes.py            deterministic offline providers
    normalization.py    provider-neutral cleaning, ledger, result envelope
    verification.py     deterministic source verification
    dedup.py            identity resolution and conservative merging
    dispatch.py         eligibility, budgets, fan-out, branch aggregation
    capabilities.py     what each connector actually reads
    credentials.py      environment-only key access
```

The seam is a Protocol:

```python
class AcademicSearchProvider(Protocol):
    provider_name: AcademicProvider
    connector_version: str

    def search(self, query: AcademicSearchQuery, *, limit: int) -> AcademicSearchResult: ...
```

`BaseAcademicProvider` owns what all three connectors share — bounded retries,
the per-query result limit, and envelope assembly. A connector module contains
only what is genuinely provider-specific: its request, its DTOs and its field
mapping.

The deterministic fakes derive from the same base and replace exactly one thing,
the HTTP attempt. An offline test therefore exercises the real normalizer, the
real identifier rules, the real duplicate check, the real limit and the real
envelope for that provider.

### Provider isolation

Each provider answers each query independently. A connector never raises for an
API outcome; a failure is data on that one `AcademicSearchResult`. Branch
aggregation (ADR-008):

| Situation | Branch outcome |
|---|---|
| no provider results at all | `NOT_RUN` |
| every provider failed | `FAILED` |
| at least one failed, at least one answered | `PARTIAL` |
| all answered, no verified source | `EMPTY` |
| all answered, verified sources | `SUCCESS` |

Worked example, exactly as the spec describes it:

```text
Consensus        SUCCESS
OpenAlex         TIMEOUT      ->  academic branch = PARTIAL
Semantic Scholar SUCCESS          1 logical source, 2 provider observations
```

### Supported providers

```text
CONSENSUS           OPENALEX           SEMANTIC_SCHOLAR
```

`AcademicProvider` is a stable enum. No provider name is a free string anywhere
in the system.

---

## 2a. Provider contract table

Reviewed against the providers' own documentation on **2026-09-16** (Phase 2B.1).
The connector constants are the single source of truth; `ProviderCapability`
reads them rather than restating them, and
`tests/test_academic_provider_contracts.py` asserts that the request a connector
actually builds matches this table.

| | Consensus | OpenAlex | Semantic Scholar |
|---|---|---|---|
| Base URL | `https://api.consensus.app` | `https://api.openalex.org` | `https://api.semanticscholar.org/graph/v1` |
| Endpoint | `/v1/search` | `/works` | `/paper/search` |
| Method | `GET` | `GET` | `GET` |
| Authentication | `x-api-key` header, **required** | `api_key` query parameter, **optional** | `x-api-key` header, **optional** |
| Required parameter | `query` | `search` | `query` |
| Result-limit parameter | `page_size` | `per_page` | `limit` |
| Documented max | 1000 per query | 100 | 100 |
| Response envelope | `results` (+ `page`, `page_size`, `is_end`, `next_page`) | `{meta, results}` | `{total, offset, next, data}` |
| Other parameters sent | -- | `mailto` (polite pool, optional) | `fields` |
| Contract reviewed | 2026-09-16 | 2026-09-16 | 2026-09-16 |

### What Phase 2B.1 corrected

| Provider | Phase 2B sent | Verified contract | Impact |
|---|---|---|---|
| Consensus | `GET /v1/search/papers`, `size`, `X-API-Key` | `GET /v1/search`, `page_size`, `x-api-key` | **Blocking.** The path did not exist, so every live Consensus call would have failed. |
| Consensus | `year`, `journal`, `consensus_summary` | `publish_year`, `journal_name`, `takeaway` | Live records would have parsed with a missing year and venue. The old spellings are kept as tolerated aliases. |
| OpenAlex | `per-page` | `per_page` | Not broken -- `per-page` is still accepted as a legacy alias -- but undocumented, so the connector now sends the documented spelling. |
| OpenAlex | no key mechanism | optional `api_key` query parameter | The free tier stays keyless; a key is now supported and raises the limits. |
| Semantic Scholar | `/graph/v1/paper/search`, `query`, `limit`, `fields`, `x-api-key` | identical | **No change.** The audit confirmed the implementation. |

Verification method: the OpenAlex contract was confirmed against the published
API reference **and** against a live keyless call
(`/works?search=...&per_page=2` returned `{meta, results}` with
`meta.per_page == 2`). The Consensus and Semantic Scholar contracts were
confirmed against the providers' published documentation; `docs.consensus.app`
is not publicly fetchable, so the Consensus request contract comes from the
provider's own published API repository together with the documented endpoint
description.

### HTTP status semantics

| Status | Kind | Retried | Branch status |
|---|---|---|---|
| 400 | `BAD_REQUEST` | no | `PROVIDER_ERROR` |
| 401 | `AUTH_ERROR` | no | `AUTH_ERROR` |
| 402 | `PAYMENT_REQUIRED` | no | `AUTH_ERROR` |
| 403 | `FORBIDDEN` | no | `AUTH_ERROR` |
| 404 | `NOT_FOUND` | no | `PROVIDER_ERROR` |
| 422 | `UNPROCESSABLE_REQUEST` | no | `PROVIDER_ERROR` |
| 429 | `RATE_LIMITED` | yes, to the bound, honouring `Retry-After` | `RATE_LIMITED` |
| 5xx | `SERVER_ERROR` | yes, to the bound | `PROVIDER_ERROR` |

402 and 401 are deliberately distinct **kinds** while sharing a branch status: a
spent quota and a rejected key are different operational facts, and both mean
the provider cannot be used right now. The 402 and 422 mappings are this
project's defensive handling rather than a quoted provider error table -- neither
provider publishes one publicly -- so they are conservative: both are
non-retryable.

---

## 3. Query eligibility

Academic connectors execute only **accepted** entries of the Phase 2A verified
query plan. Raw student text has no path to a provider: the planner's provenance
rules (ADR-006) are upstream, and eligibility re-checks for personal data anyway
because the query is about to leave the system.

Routed to academic search:

```text
PROBLEM   EXISTING_SOLUTIONS   TECHNOLOGY   RECENT_WORK   LIMITATIONS
BENCHMARK REVIEW               ALTERNATIVES FAILURE_MODES PRIOR_ART
```

Never routed here (later branches):

```text
PATENT_FUNCTION   PATENT_MECHANISM   PRODUCT   OPEN_SOURCE
```

`AcademicSearchQuery` refuses to be constructed with a non-academic branch or an
unrouted purpose, so the rule is a contract rather than a convention. Every
request preserves `research_run_id`, `query_id`, `branch`, `purpose`, `query`,
`provider` and `requested_limit`.

Exclusion reasons, all recorded:

```text
QUERY_NOT_ACCEPTED   NOT_ACADEMIC_BRANCH   PURPOSE_NOT_ROUTED_TO_ACADEMIC
EMPTY_QUERY          PII_DETECTED          DUPLICATE_QUERY
QUERY_BUDGET_EXCEEDED
```

A query excluded for `PII_DETECTED` is recorded **without its text**; a model
validator enforces it, so the ledger cannot become the place the personal data
survives.

---

## 4. Budgets

Configured on `ResearchSettings.academic` (`AcademicSearchSettings`):

| Setting | Default | Enforced in |
|---|---|---|
| `max_academic_queries_per_run` | 4 | `ENFORCE_ACADEMIC_BUDGET` |
| `max_results_per_query_per_provider` | 10 | the provider base class |
| `max_results_per_provider_per_run` | 30 | `NORMALIZE_ACADEMIC_RESULTS` |
| `max_total_academic_candidates` | 90 | `NORMALIZE_ACADEMIC_RESULTS` |
| `enabled_providers` | all three | dispatch |

Deliberately small. The goal is high-value coverage of a few well-provenanced
queries, not volume.

Every limit is enforced by this project rather than trusted to the provider: a
provider that ignores `limit` has its extra records truncated and recorded, and
does not get to widen the budget. Truncation is reported on
`AcademicBudgetReport` (`queries_truncated`, `candidates_truncated_per_provider`,
`candidates_truncated_total`, and the derived `truncated`) and as ledger entries
with `PROVIDER_RESULT_LIMIT_EXCEEDED` / `TOTAL_CANDIDATE_LIMIT_EXCEEDED` at
stage `BUDGET`.

**Budget exhaustion is not a provider failure.** A provider result reports what
that one call produced; the run-level caps are applied when candidates are
accumulated for the branch, so the per-call record stays an honest account of
the call.

---

## 5. Retries and rate limits

One retry policy, in `src/research/academic/http.py`, reusing the Phase 2A.1
philosophy: retry what a retry can plausibly fix, and nothing else.

```text
retried       TIMEOUT  CONNECTION_ERROR  RATE_LIMITED (429)  SERVER_ERROR (5xx)
not retried   BAD_REQUEST (400)  AUTH_ERROR (401)  FORBIDDEN (403)
              NOT_FOUND (404)  INVALID_RESPONSE  SCHEMA_INCOMPATIBLE
```

403 is deliberately non-retryable: a provider that documents it as transient
would need its own reviewed decision, and guessing turns an authorization
problem into a retry storm.

Retries are bounded (`RetryPolicy.max_attempts`, default 3). Backoff is
exponential, capped, and has **no jitter**, so identical inputs produce identical
waits and the deterministic suite can assert them.

Rate limiting is represented explicitly, never as a generic error.
`RateLimitInfo` records `provider`, `limited`, `http_status`,
`retry_after_seconds` and `attempts`. `Retry-After` is honoured in its seconds
form only — the HTTP-date form needs a clock, and a wrong clock turns a short
pause into a long stall — and is capped at 60 seconds.

Waiting is injected through a `Sleeper`. The default is `NoSleep`, which records
the waits it was asked for and performs none, so the standard suite exercises
the full backoff path, `Retry-After` included, without a single real second
passing.

---

## 6. Credentials

```text
CONSENSUS_API_KEY           required by the Consensus connector (x-api-key header)
SEMANTIC_SCHOLAR_API_KEY    optional; the public endpoint works without one
OPENALEX_API_KEY            optional; raises the OpenAlex limits (api_key parameter)
OPENALEX_CONTACT_EMAIL      optional, not a secret (OpenAlex polite pool)
```

OpenAlex is the one provider whose documented mechanism puts the credential in
the URL. That is honoured because it is the provider's contract, and it is safe
here for a specific reason: nothing in this project logs, stores or echoes a
request URL. Error messages are composed from the status code alone, and only
response bodies reach `raw_provider_metadata`. A contract test asserts the key
never reaches the stored result.

Keys are read from the process environment when a live connector is constructed
and held in a private attribute. Nothing stores a key in a settings model, on
graph state, in a checkpoint, in an error message, in a rejection ledger or in a
log line. Error messages are composed from the status code alone; a provider
body is never echoed, because a body can repeat the request and a request can
carry a key.

The only thing another layer can ask is whether a key is present
(`provider.has_credentials`). A missing required key is an `AUTH_ERROR` naming
the environment variable, never the value.

---

## 7. Normalization

Provider JSON is never read directly. Each connector declares typed DTOs
(`ProviderFacingModel`, `extra="ignore"`): an academic API adds fields without
warning, and a connector that breaks on an unknown key breaks in production.
Ignoring is not trusting — every field this project uses is declared, typed and
re-validated downstream.

Records are validated **one at a time**. A malformed record produces one ledger
entry; the rest of the response is normalized as usual. Every response reports
`raw_count`, `accepted_count`, `rejected_count` and per-record reasons.

Envelope status for a provider that answered:

```text
raw_count == 0                 -> EMPTY
accepted == 0, raw_count > 0   -> INVALID_RESPONSE
accepted > 0, rejected == 0    -> SUCCESS
accepted > 0, rejected > 0     -> PARTIAL
```

Shared cleaning rules: whitespace collapse (`None` when empty), a year that is
outside the contract range or unparseable is *invalid* rather than missing, a
date is accepted only as ISO `YYYY-MM-DD`, a flag is honoured only when it is a
real boolean, and a negative or unparseable count becomes `None`.

**Nothing absent is invented. Missing means `None`.**

---

## 8. Identifier rules

| Kind | Canonical form | Accepted input |
|---|---|---|
| DOI | `10.1234/abcd` | `https://doi.org/…`, `http://dx.doi.org/…`, `doi:…`, bare, any case |
| PMID | `32123456` | bare digits, `pmid:…`, a PubMed URL |
| OpenAlex | `w2741809807` | `https://openalex.org/W…`, `https://api.openalex.org/works/W…` |
| Semantic Scholar | 40 hex chars, or `corpusid:123` | paper id, `CorpusID:…`, a paper URL |
| arXiv | `2103.00020`, `math.gt/0309136` | `arXiv:…v2`, an abs/pdf URL, bare |
| Canonical URL | scheme and host lowercased, default port and fragment dropped | any http(s) URL |

Rules:

* An identifier that does not match its canonical format is **invalid**, which
  is a different fact from **absent**. Only the first is a rejection.
* No identifier is ever derived from a title, an author list or a URL guess.
* The arXiv version suffix is dropped for identity: `2103.00020v2` and
  `2103.00020` are the same work at two revisions, and the provider's original
  string stays in `raw_provider_metadata`.
* Verification re-checks idempotence: a stored identifier must already be its
  own normal form, so nothing downstream can be comparing two spellings.

---

## 9. Deduplication and provider observations

Full rationale in ADR-009.

Identity priority:

```text
DOI  >  PMID  >  OPENALEX_ID  >  SEMANTIC_SCHOLAR_ID  >  ARXIV_ID  >  CANONICAL_URL
```

* **Title-only deduplication is forbidden and unrepresentable.**
  `SourceIdentifierKind` has no title member, so it cannot be expressed.
* A **conflicting** strong identifier blocks a merge: shared arXiv id but
  different DOIs means at least one record is wrong, and neither wins.
* With **no shared identifier, both candidates survive**. An avoidable duplicate
  is cosmetic; a wrong merge fuses two works and corrupts every later judgement.
* Grouping is deterministic and order-stable, so the same candidates always
  produce the same primary observation and the same merged record.

Each member becomes a `ProviderObservation` carrying that provider's record id,
URL, identifiers, title, year, type, retraction and open-access flags, rank,
relevance, citation count and retrieval time. The system can therefore answer:

> Which providers independently returned this source, under which query, at
> which rank?

---

## 10. Metadata merge policy

| Field | Rule on disagreement |
|---|---|
| identifiers | union; a conflict blocks the merge upstream |
| `title` | required, so the primary observation's title is kept **and** a conflict is recorded. Case, punctuation and spacing differences are not material |
| `authors` | primary observation's list kept, conflict recorded when the name sets differ |
| `publication_year` | left **unknown**, conflict recorded |
| `publication_date`, `venue`, `publisher`, `is_open_access` | left **unknown**, conflict recorded |
| `source_type` | `UNKNOWN` counts as "not stated" and never overrides a real type; a genuine disagreement leaves `UNKNOWN` and records a conflict |
| `is_retracted` | **sticky-true**: any provider reporting `True` makes it `True`, with the conflict recorded and `resolved_value="True"` |
| `abstract` | first available; providers legitimately hold different lengths of one text, so no conflict is raised |
| `citation_count` | **never merged**; kept per provider with its retrieval time |

Missing metadata is filled from another provider. One provider contradicting
itself across two of its own records keeps the first reading rather than
inventing a cross-provider conflict.

Every `MetadataConflict` holds every provider's reading, so a disagreement is
visible rather than resolved by arrival order.

---

## 11. Source verification

Deterministic, metadata only:

```text
every stored identifier is already in its canonical form
a canonical URL, if present, is a real http(s) URL
the record has at least one identity
the record traces to a research run and a planned query
the record carries no student identity
```

Rejection reasons are named (`INVALID_DOI`, `MISSING_IDENTIFIER`,
`INVALID_URL`, `PII_DETECTED`, …) and one unverifiable record never invalidates
another.

**Normalizing metadata does not make a paper scientifically verified.** A logical
source can only carry `VERIFIED_METADATA`; a validator refuses
`VERIFIED_FULL_TEXT`, because Phase 2B never reads full text.

---

## 12. Retractions

* A provider that states retraction status has it preserved in both directions:
  `True` and `False` are both real answers.
* A provider that says nothing leaves `is_retracted = None`. **Unknown is never
  coerced to `False`.**
* A retracted paper is **never discarded silently**. It is stored, flagged, and
  the provider that flagged it is recorded on its observation.
* On disagreement the merge is sticky-true, with the conflict preserved.

Of the three implemented providers, only OpenAlex exposes retraction status. A
Consensus-only or Semantic-Scholar-only source therefore reports `None`, which
is the honest answer.

---

## 13. Preprints

* A preprint is stored with `source_type = PREPRINT` and
  `peer_review_status = NOT_PEER_REVIEWED`.
* Preprints are **not** excluded: one can be the closest prior art.
* Preprints are **not** treated as equivalent to peer-reviewed work: the
  distinction survives into `SourceRecord.source_type` (`PREPRINT`) for the
  later phase that weighs it.
* Source type is never inferred from title wording, and an arXiv identifier
  alone does not make a record a preprint — a paper can hold an arXiv preprint
  *and* a journal publication.

---

## 14. Citation counts and ranking

Citation counts are metadata, not quality proof. They are stored as
`CitationObservation(provider, count, retrieved_at)`, never merged into a single
number, never converted into `SourceQuality`, and never used as a hidden ranking
score.

Provider ranking (`provider_rank`) and Consensus's relevance score
(`provider_relevance`) are preserved as **retrieval metadata only**. Rank is
where a provider placed a result; it is not scientific validity.

Consensus's synthesized text is provider-generated secondary metadata. It is
kept in `raw_provider_metadata`, and it never becomes a paper's `abstract`,
never the paper's own words, and never evidence.

---

## 15. Abstracts and full text

An abstract is provider-supplied metadata. It is stored, preserved verbatim, and
is **not** full-text evidence. Phase 2B creates no claim-support
`EvidenceRecord` from an abstract (ADR-010).

There is no full-text pipeline: no PDF download, no scraping, no OCR, no
publisher bypass, no paywall circumvention. OpenAlex's inverted abstract index is
reconstructed by word position — a deterministic re-ordering of words the
provider supplied, bounded in length, with gaps left as gaps.

---

## 16. Rejected candidate ledger

Every refused provider record produces a `RejectedAcademicCandidate`:

```text
provider   query_id   stage   reason   provider_record_identifier   safe_summary
```

`stage` is `NORMALIZATION`, `BUDGET` or `VERIFICATION`. `safe_summary` is a
single line, collapsed and length-bounded — an audit trail, not a second copy of
the provider response. A `PII_DETECTED` rejection stores **no** summary, enforced
by a validator. No credentials and no model reasoning appear (there is no model
in this branch).

---

## 17. The academic branch graph

`build_phase2b_academic_graph()` — a dedicated branch graph, with no patent,
product, open-source or standards retrieval and **no model call anywhere**.

```text
START
  -> LOAD_VERIFIED_QUERY_PLAN ------(no open run / no plan)---> END
  -> SELECT_ACADEMIC_QUERIES        eligibility: branch, purpose, PII
  -> ENFORCE_ACADEMIC_BUDGET        query budget -> one request per provider
  -> DISPATCH_ACADEMIC_PROVIDERS    isolated provider calls (ADR-008)
  -> NORMALIZE_ACADEMIC_RESULTS     candidates under the run-level budgets
  -> VERIFY_ACADEMIC_CANDIDATES     deterministic metadata verification
  -> DEDUPLICATE_ACADEMIC_SOURCES   strong-identifier identity (ADR-009)
  -> MERGE_PROVIDER_OBSERVATIONS    conservative merge + branch outcome
  -> UPDATE_ACADEMIC_COVERAGE       coverage counters; the run stays open
  -> END
```

Every node stores its output on the `AcademicRetrievalResult` carried by the
`ResearchRun`, so a replay after an interrupt recomputes from data already on
the state rather than from anything held in memory between nodes.

The run is deliberately left **non-terminal**. Phase 2A's
`UPDATE_RESEARCH_COVERAGE` is what makes a run terminal; the academic branch is
one of several, and freezing the run here would block every branch that comes
after it. The two graphs are therefore run separately today.

`AcademicRetrievalResult` lives on the `ResearchRun`, never in `ProjectState`
(ADR-006). Providers are injected per run through
`config["configurable"]["academic_search_providers"]`, which is what keeps graph
construction credential-free and tests deterministic.

### Parallelism

Dispatch is sequential. Correctness does not depend on concurrency, and
redesigning the established workflow to gain it would risk the guarantees this
phase exists to hold. Parallel provider execution is **deferred technical debt**.

---

## 18. Research coverage

`BranchExecutionCoverage` for the `ACADEMIC` branch now reports:

```text
required  planned  started  completed  failed
query_count  candidate_count  verified_source_count
provider_success_count  provider_failure_count  provider_empty_count
```

Provider counters are per provider **per query**, so a two-query branch across
three providers has six provider executions. `failed` is true only when the
branch outcome is `FAILED` — that is, only when no provider could be asked.

Coverage remains operational. `verified_source_count` counts logical sources
whose metadata verified; it says nothing about relevance, soundness or support.

---

## 19. Privacy

Query minimization is Phase 2A's and is unchanged. Phase 2B adds two checks
because this is the layer where a query actually leaves the system:

1. **Eligibility re-checks the query text** against the injected identity
   context. A match excludes the query with `PII_DETECTED` and stores no text.
2. **Verification re-checks provider text.** Student identity never reaches a
   provider, so a provider cannot echo it back — and if one ever did, the
   candidate is rejected rather than stored.

No connector may receive a student name, email, phone number, national id,
school name or home address. The academic branch reads the verified query plan
and never reconstructs removed identity from `ProjectState` or any other
workflow state. A release-blocking eval metric counts leakage across dispatched
queries, the exclusion ledger and the rejection ledger.

---

## 20. Prompt injection

Academic API metadata is untrusted content. A title, abstract or snippet
containing `Ignore previous instructions` stays **data**: it is stored verbatim
and interpreted by nothing.

The structural guarantee is stronger than a filter: **the academic branch makes
no model call**, so there is no prompt to inject into. Retrieval is fully
deterministic, and a test proves that an injected abstract changes no branch
outcome, no source count, no node path, no coverage counter and no byte of
`ProjectState`.

---

## 21. Evals

```text
evals/academic_retrieval/v1/cases.jsonl     51 Gold cases
evals/academic_retrieval/v1/schema.md       the case contract
src/evals/academic/{dataset,metrics,runner,cli}.py
```

Run it:

```bash
./.venv/Scripts/python.exe -m src.evals.academic.cli
./.venv/Scripts/python.exe -m src.evals.academic.cli --report
```

Every case is driven through the **real Phase 2B graph** with the deterministic
fakes, through a checkpoint. Scoring is implemented independently of the code it
scores: the eval recomputes identity conflicts, provenance counts and
traceability from the produced state rather than asking the deduplicator whether
it deduplicated correctly. That independence is what lets the negative controls
prove the eval can fail.

Coverage: 51 cases (48 en, 2 ar, 1 mixed) over cross-provider dedup, DOI
formatting, title-is-not-identity, missing DOI, provider-only identifiers,
preprints, reviews, conference papers, unknown types, retractions and unknown
retraction, conflicting years / titles / venues / open-access flags, citation
disagreement, empty results, timeout, rate limit, auth failure, total outage,
malformed records and envelopes, within-provider duplicates, PII contamination,
prompt injection, Arabic and mixed-language queries, budget truncation, result
limits, provider field aliases, and the three standing safety gates.

Metrics (numerator/denominator, `None` when unmeasured):

```text
identifier_normalization_accuracy    cross_provider_dedup_accuracy
provider_observation_preservation    metadata_merge_accuracy
rejected_candidate_accuracy          provider_failure_isolation_accuracy
budget_enforcement_accuracy          source_traceability
```

Release-blocking (target: exactly zero):

```text
pii_leakage_rate                  project_state_mutation_rate
evidence_creation_violation_rate  claim_mutation_violation_rate
untraceable_verified_source       invalid_strong_identifier_merge
provider_provenance_loss
```

Reported per language as well as in aggregate, so a passing total cannot hide a
failing subgroup.

### Negative controls

`tests/test_academic_retrieval_evals.py` corrupts a known-good result and asserts
each gate fires: injected PII in a dispatched query, a mutated `ProjectState`, a
smuggled evidence-shaped record, a mutated claim set, a merge of two different
DOIs, a dropped provider observation, and an untraceable source. A control case
first proves the uncorrupted result is clean.

---

## 22. Live-test policy

```text
RUN_CONSENSUS_TESTS=1          tests/test_academic_live_integration.py
RUN_OPENALEX_TESTS=1
RUN_SEMANTIC_SCHOLAR_TESTS=1
```

Each provider has its own flag and is skipped unless that flag is `1`. Having
credentials is deliberately not enough, and network access is deliberately not
enough. The converse also holds: a flag alone does not start a test that needs a
credential. With `RUN_CONSENSUS_TESTS=1` and no `CONSENSUS_API_KEY`, the
Consensus test **skips** -- a connector answering `AUTH_ERROR` satisfies every
structural assertion, so passing it would report a provider as verified when it
was never contacted. Live assertions are structural only — the request is accepted, the
response parses, and whatever comes back obeys this project's contracts — so
they never become a Gold baseline and CI never depends on a third-party service.

The standard suite runs with **no internet, no credentials and no API keys**, and
a test patches `httpx.Client.send` to fail loudly if anything tries.

Skipped live tests are reported as skipped, never as passed.

---

## 23. Versioning

Recorded on every `AcademicRetrievalResult`, so a later evaluation is
reproducible:

```text
ACADEMIC-CONTRACT-V1              contract_version
ACADEMIC-NORMALIZER-V1            normalizer_version
ACADEMIC-DEDUP-V1                 dedup_version
CONSENSUS-CONNECTOR-V2            connector_versions[CONSENSUS]
OPENALEX-CONNECTOR-V2             connector_versions[OPENALEX]
SEMANTIC-SCHOLAR-CONNECTOR-V1     connector_versions[SEMANTIC_SCHOLAR]
```

Plus, per record: the provider, the query id, the research run id and
`retrieved_at` on every candidate and observation. The eval report additionally
records the dataset version.

---

## 24. Observability

The stored result answers, without a log file:

| Question | Where |
|---|---|
| Which query was sent? | `AcademicRetrievalResult.selected_queries` |
| Which provider received it? | `AcademicSearchQuery.provider` |
| How many raw records came back? | `AcademicSearchResult.raw_count` |
| How many were rejected, and why? | `rejected_count`, `rejected_candidates` |
| How many canonical candidates remained? | `accepted_count`, `candidates` |
| Which logical sources were deduplicated? | `logical_sources` + `decisions` |
| Which providers observed each source? | `LogicalAcademicSource.providers` |
| Why did any provider fail? | `errors`, `rate_limit`, `attempts` |
| What was cut by budget? | `AcademicBudgetReport`, `BUDGET`-stage rejections |
| Which queries never ran, and why? | `excluded_queries` |

Debug logging names the provider, attempts and failure kind. No credentials and
no unnecessary personal data are logged.

---

## 25. Source registry boundary

Verified academic sources are stored as Phase 0 `SourceRecord`s on
`AcademicRetrievalResult.verified_sources`, one per logical source, alongside the
richer `LogicalAcademicSource`. They are **not** merged into `ProjectState.sources`.

That preserves the Phase 2A decision deliberately: research results live on the
`ResearchRun` and canonical project state has one writer. Merging research
sources into `ProjectState` is a later, separately reviewed stage — the same open
item Phase 2A.1 recorded for official sources. Ownership has not changed
silently.

`SourceRecord.query_id` is left unset for academic sources: the Phase 0 field is
the `Q-001` execution-log form, while academic provenance is the UUID-keyed
observations on the logical source.

---

## 26. What Phase 2B does not do

```text
no EvidenceRecord                no SUPPORTED or VERIFIED ClaimRecord
no novelty conclusion            no research gap conclusion
no score                         no readiness classification
no patent / product / open-source / standards retrieval
no full text, no PDF, no OCR, no paywall circumvention
no source quality, no tier assignment
```

---

## 27. Known limitations

1. **`COMPETING_METHODS` is not routed to academic search.** The execution
   specification lists ten routed purposes and it is not among them. It is a
   challenge-family purpose, so excluding it slightly narrows anti-confirmation
   coverage on this branch. Routing it needs a reviewed decision.
2. **Consensus carries only a DOI.** A Consensus record without one can be
   deduplicated only on its canonical URL, so a DOI-less Consensus paper and the
   same paper from another provider may remain two logical sources.
3. **Only OpenAlex exposes retraction status.** A source seen only by Consensus
   or Semantic Scholar reports `is_retracted = None`.
4. **Semantic Scholar has no preprint publication type**, so an arXiv paper it
   returns is `UNKNOWN` unless another provider states the type.
5. **Dispatch is sequential.** Three providers times four queries is twelve
   serial HTTP calls in production.
6. **The same scripted response applies to every query of a Gold case**, which
   keeps the dataset compact but means per-query response variation is not
   exercised.
7. **No live eval.** Every number in this document comes from scripted responses.
8. **Verified academic sources are not merged into `ProjectState.sources`** (§25).
9. **The connector contracts are the ones this project implements.** They tolerate
   unknown fields, but a provider renaming a field this project reads would
   surface as `INVALID_RESPONSE` rather than as a silent gap — which is the
   intended direction, and is why `raw_provider_metadata` is preserved.
   Contracts were reviewed on 2026-09-16 and carry that date; they are not
   self-checking and will need re-review.
10. **The Consensus and Semantic Scholar response schemas are documented, not
    observed.** Only OpenAlex has been exercised against the live API from this
    environment. A response differing from its published schema would surface as
    rejected records with named reasons rather than as bad data, but it has not
    been proven end to end.
11. **The 402 and 422 mappings are defensive**, not quoted from a provider error
    table; neither provider publishes one publicly.
12. **Arabic matching stays exact**, inherited from Phase 2A.1: no alef/ya
    normalization and no diacritic folding, in line with the no-fuzzy-matching
    rule.

---

## 28. Technical debt

1. Parallel provider dispatch (§17).
2. `SELECT_ACADEMIC_QUERIES` and `ENFORCE_ACADEMIC_BUDGET` both run the
   eligibility pass. It keeps each node a pure function of state and costs a
   repeated in-memory computation; a shared cached selection channel would remove
   it.
3. A single research run cannot yet flow through the Phase 2A graph and then the
   Phase 2B graph, because Phase 2A finalizes the run. A composite production
   graph needs a reviewed decision about where a run becomes terminal.
4. No baseline file for the academic eval, unlike intake's approved baseline.
   The gate is currently "zero release-blocking violations and no errored case".
