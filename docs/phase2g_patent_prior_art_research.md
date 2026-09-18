# Phase 2G -- Patent Prior-Art Research Foundation

Phase 2G implements the PATENT research branch:

```
Technical project claims
  -> patent search query plan            (PLAN_PATENT_QUERIES)
  -> provider search observations        (EXECUTE_PATENT_SEARCH)
  -> verified patent publications        (VERIFY_PATENT_PUBLICATIONS)
  -> patent family resolution            (RESOLVE_PATENT_FAMILIES)
  -> patent text snapshots               (CAPTURE_PATENT_TEXT)
  -> chronology / cutoff qualification   (BUILD_PATENT_CANDIDATES)
  -> patent prior-art research candidates
  -> STOP                                (FINALIZE_PATENT_RESEARCH)
```

It answers: *which patent publications and families should a later
novelty-analysis phase inspect, and what verified metadata, text and provenance
do we hold for them?* It does **not** answer whether the invention is novel,
patentable, infringing or free to operate, and it makes no legal prior-art
determination. See ADR-018.

> This research is technical discovery, not a patentability or legal opinion.
> Student-facing output must say so.

## 1. Architecture decision

| Question | Decision |
|---|---|
| State ownership | `ResearchRun.patent_prior_art: PatentPriorArtRun`. Never `ProjectState` (ADR-010). |
| Relation to the PATENT branch | Reuses `ResearchBranch.PATENT` and the PATENT entry of `ALLOWED_PURPOSES_BY_BRANCH` (`PATENT_SEARCH_PURPOSES`). `NodeId.PATENT_RESEARCH` stays the nominal umbrella; Phase 2G adds eight concrete nodes. |
| Query planning | `src/research/patent/planner.py`. Reuses `QueryPurpose`; adds an orthogonal `PatentSearchStrategy` dimension (how a query is shaped). |
| Observation vs publication | `PatentSearchObservation` (one provider record) vs `VerifiedPatentPublication` (one canonical identity, every observation kept). |
| Publication identity | `authority.number.kind` (DOCDB shape); a missing kind is `-`, never a wildcard; no title. |
| Family identity | Provider family service only (EPO OPS INPADOC). `PatentFamilyGroup` over publications; members preserved. |
| Snapshots | `PatentTextSnapshot` per content type (`TITLE`/`ABSTRACT`/`CLAIMS`/`DESCRIPTION`), SHA-256 of the stored text, documented operation, declared language, scope. |
| Chronology | `PatentDateSet` with four distinct dates; public date = publication date, else a separately stated grant date. |
| Time qualification | Descriptive only, against an explicit `PatentSearchCutoff`; `NO_CUTOFF` otherwise. |
| Boundedness | `PatentBudgetReport` records every limit and what it cut; `PatentSearchCoverageStatus`. |
| Errors | `PatentErrorKind`; retry only transport faults, 429 and 5xx; never invalid queries or fair-use rejections. |
| Candidate vs novelty | Candidate stops at comparison-ready data; no score, no verdict, required limitations. |
| Immutability | Nodes replace only `ResearchRun.patent_prior_art`. |

Runtime inputs arrive through `config["configurable"]` and are never
checkpointed: `patent_search_provider`, `patent_search_cutoff`,
`structured_model_provider` (optional, for Arabic expansion), `research_privacy`,
`research_settings`.

## 2. Provider contract verification

Verification date for this phase: **2026-09-17**, re-checked **2026-09-19**.

### EPO Open Patent Services -- `IMPLEMENTED_DOCUMENTED_ONLY`

| Item | Contract |
|---|---|
| Documentation | https://developers.epo.org/ (OPS v3.2 reference guide) |
| Authentication | OAuth2 client credentials: consumer key + secret as HTTP Basic to `POST https://ops.epo.org/3.2/auth/accesstoken` with `grant_type=client_credentials`; the returned bearer token authorizes REST calls. Basic auth is used on the token endpoint only. |
| Search | `GET https://ops.epo.org/3.2/rest-services/published-data/search?q=<CQL>` |
| Pagination | HTTP `Range: items=<a>-<b>` header, one-based inclusive, at most 100 per window; never a query-string parameter. |
| Bibliographic | `GET .../published-data/publication/docdb/{ref}/biblio` |
| Abstract / claims / description | `GET .../published-data/publication/docdb/{ref}/{abstract,claims,description}`; claims and description coverage is authority-dependent. |
| Family | `GET .../family/publication/docdb/{ref}` (INPADOC extended family). `equivalents` is a `published-data` constituent (simple family) and is **not** used. |
| Response format | XML (`ops:world-patent-data`, exchange documents); faults as XML `<error><code/><message/></error>`, sometimes in a 200 body. |
| Fair use | Quota violations answer `403` with an `X-Rejection-Reason` header (e.g. `AnonymousQuotaPerDay`, `IndividualQuotaPerHour`); treated as `FAIR_USE_REJECTED` and not retried within the run. |
| Fields used | DOCDB `country`/`doc-number`/`kind`/`date` of publication, application and priority references; `family-id`; `invention-title` (+`lang`); applicants/inventors (`epodoc` format); IPCR text; CPC `patent-classification`; `total-result-count`. |
| Live contract observed | Unauthenticated only. On 2026-09-19 unauthenticated probes returned `403` with `X-Rejection-Reason: AnonymousQuotaPerDay` and an XML fault body, which confirms host, fault envelope and fair-use signalling. **No authenticated request has been executed**, so the provider stays documented-only. |

The request contract is pinned by `tests/test_patent_provider_contracts.py`,
including a negative assertion over `STALE_EPO_PATHS` (`/3.1/rest-services`,
`search.json`, any `/equivalents`, pagination in the query string, a password
grant, Basic credentials on a REST call). `EPO_OPS_CAPABILITY` reads the
connector constants, so the table cannot drift from the code.

**Recovery correction (2026-09-19).** The recovered connector addressed the
family service as `/family/publication/docdb/{ref}/equivalents`, mixing the
INPADOC family service with the `published-data` `equivalents` constituent, and
labelled the result `DOCDB_SIMPLE`. It now calls `/family/publication/docdb/{ref}`
and labels the result `EXTENDED_INPADOC`.

### USPTO Open Data Portal -- `DEFERRED`

Documentation: https://data.uspto.gov/support/transition-guide/patentsview.
PatentsView moved to the USPTO Open Data Portal on 2026-03-20; the legacy
PatentSearch API was retired and its search functions are to be reintroduced
on ODP in updated form, with no launch date. No stable, documented search
contract is usable by this phase, so no connector exists, no operation is
declared, and no legacy PatentsView endpoint is assumed active. Phase 2G is not
blocked on it.

### WIPO PATENTSCOPE -- `UNSUPPORTED_BY_ACCESS_POLICY`

Documentation: https://www.wipo.int/en/web/patentscope/data/terms_patentscope.
The PATENTSCOPE terms forbid automated queries, robots, scraping and bulk
downloading from the public search service. PATENTSCOPE is documented as a
manual reference source only. The capability validator forbids this status from
declaring any operation, and the dispatch gate refuses any query addressed to
it (`PROVIDER_NOT_DISPATCHABLE`) before a request exists.

## 3. Query planning

- Built from canonical claim text and, where the run has one, the Phase 2E
  component inventory. Never from a claim's evidence, sufficiency or Phase 2F
  score -- the planner has no parameter through which one could arrive.
- Strategies: `EXACT_TECHNICAL_PHRASE`, `CORE_TECHNICAL_CONCEPT`,
  `MECHANISM_FUNCTION`, `COMPONENT_COMBINATION` (deterministic, always
  available) plus `SYNONYM_VARIANT` and `BROADER_TECHNICAL_TERMS` (model
  expansion). A plan must include a non-literal strategy (anti-confirmation).
  `CLASSIFICATION_EXPANSION` and `KNOWN_IDENTIFIER_LOOKUP` are supported by the
  builders; classification expansion is capped by
  `max_classification_expansions` (default 0).
- Student novelty wording (`novel`, `new`, `first`, `best` ...) is a stopword.
- The CQL grammar is an allowlist: known indexes, `and`/`or`, quoted phrases,
  no `not`, no escapes, at most 500 characters. Validation runs in the planner
  and again at the dispatch gate and in the request builder.

## 4. Multilingual planning

Arabic or mixed claims keep their original text on every term
(`PatentQueryTerm.original_text`). English expansion is model-assisted only when
the claim contains Arabic script and a structured model provider is supplied.
Model output is untrusted: each term must quote a substring of the claim it
derives from, must pass PII, injection and CQL checks, and is kept or refused
individually. The expansion kind the model declared selects the strategy
(`SYNONYM`/`TRANSLATION` -> `SYNONYM_VARIANT`, `BROADER` ->
`BROADER_TECHNICAL_TERMS`). `planner_prompt_version` is set only when a model
term was actually used. Translation is never evidence.

## 5. PII minimization

Claim text passes the shared research privacy layer (`src/research/privacy.py`)
before any query is built; a claim carrying PII is excluded with `PII_DETECTED`
and its text is not retained. Dispatch re-checks the final expression. Patent
parties (applicants, inventors) are document metadata, not student data, and are
not scanned; titles are.

## 6. Search boundedness

`PatentResearchSettings` (`ResearchSettings.patent`): `max_queries_per_claim` 4,
`max_queries_per_run` 12, `max_results_per_query` 10, `max_pages_per_query` 1,
`max_total_provider_results` 100, `max_verified_publications` 50,
`max_family_lookups` 25, `max_classification_expansions` 0, `retry_limit` 3,
`timeout_seconds` 30, `base_backoff_seconds` 0.5, `fetch_description` false.

Coverage: `NOT_EXECUTED`, `COMPLETE_WITHIN_CONFIGURED_BOUNDS`,
`PARTIAL_PROVIDER_LIMIT` (a budget cut, or a provider total above what was
fetched), `PARTIAL_ERROR` (a failed or refused query), `BLOCKED_AUTH`. The run
validator refuses `COMPLETE_...` with any truncation or failure.

## 7. Identity, families, dates, snapshots

- Identity normalization: upper case, grouping separators removed, no padding,
  no leading-zero stripping, kind code kept; a stated but malformed kind code is
  refused rather than dropped.
- Families: one lookup per family; siblings already in hand are assigned from
  the same response; `VERIFIED_FAMILY`, `SINGLETON_FAMILY`,
  `FAMILY_DATA_UNAVAILABLE`, `FAMILY_RESOLUTION_FAILED`, `NOT_REQUESTED`.
- Dates: parsed from the element that means that date, no fallback chain. The
  publication date comes only from the document's own reference; a grant date
  only from a separate grant reference.
- Snapshots: whitespace-normalized provider text, bounded at 200,000 characters
  with `TRUNCATED` recorded, hashed after normalization. A claims request that
  returns nothing records an absence and never falls back to the abstract.
  Availability: `AVAILABLE`, `NOT_PUBLISHED_BY_AUTHORITY`,
  `NOT_SUPPORTED_BY_PROVIDER`, `RETRIEVAL_FAILED`, `NOT_REQUESTED`, `UNKNOWN`.
- Provider XML declaring a `DOCTYPE` or `ENTITY` is refused before parsing.

## 8. Candidate contract

`PatentPriorArtCandidate` carries the run id, publication id/key/identity,
family group, family id and status, title, the four dates, time qualification
and the cutoff it was qualified against, applicants, inventors, IPC/CPC,
content availability, snapshot ids, query provenance (query, provider, purpose,
strategy, provider rank, claim and component ids), observation ids and
limitations. The four universal limitations are required by the validator. One
candidate per publication per run.

## 9. Errors, retries, idempotency, isolation

- Retried: `TIMEOUT`, `CONNECTION_ERROR`, `RATE_LIMITED` (429), `SERVER_ERROR`.
  Not retried: `INVALID_QUERY`, `AUTHENTICATION_ERROR`, `FORBIDDEN`,
  `FAIR_USE_REJECTED`, `PARSE_ERROR`, `UNSUPPORTED_OPERATION`. One failing query
  never discards another's observations.
- Every stage is a no-op once its output exists; execution skips any query
  whose `stable_key` is already executed; a finished patent run is never
  reopened; follow-up Range windows get deterministic `uuid5` ids.
- The run validator refuses items from another research run, references to
  unknown queries, observations, publications, families or snapshots, a family
  member marked retrieved without a publication, and a second candidate for a
  publication.

## 10. Evaluation

`evals/patent_prior_art/v1/cases.jsonl` (schema: `evals/patent_prior_art/v1/schema.md`),
regenerated by `scripts/generate_phase2g_gold.py`. Each case builds a populated
upstream state through the real Phase 2E and 2F graphs, runs the real Phase 2G
graph against a scripted EPO OPS office (real XML, real parser), and is scored
against authored expectations and independent re-derivations of identity,
chronology and family counts. 18 quality metrics must be 1.0; 48
release-blocking gates must be zero; negative controls must fire.

```
.venv/Scripts/python.exe -m src.evals.patent_prior_art.cli [--report] [--verbose]
RUN_EPO_OPS_TESTS=1 EPO_OPS_CONSUMER_KEY=... EPO_OPS_CONSUMER_SECRET=... \
  .venv/Scripts/python.exe -m pytest tests/test_epo_ops_live_integration.py
```

## 11. Limitations

- Bounded search is not an exhaustive worldwide search.
- Text coverage (claims, description, languages) varies by authority and provider.
- Publication-before-cutoff is descriptive chronology, not a legal prior-art ruling.
- Phase 2G does not assess novelty, patentability, infringement or freedom to operate.
- Family grouping does not prove identical claim scope across jurisdictions.
- Legal status data is not fetched.
- EPO OPS has not been verified with an authenticated live request.
