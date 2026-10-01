# Phase 2H -- Product and Open-Source Prior-Art Research

Phase 2H discovers, normalizes, verifies, deduplicates and bounds commercial
product artifacts and public open-source repositories that a **later**
novelty/differentiation phase should inspect. It produces candidates and
nothing else: no novelty, same-invention, copying/plagiarism, legal,
patentability, infringement, FTO or project-score conclusion (ADR-019).

## 1. Pipelines

```
Product track                         Open-source track
claims / Phase 2E components          claims / Phase 2E components
  -> DiscoveryQuery (Brave)             -> DiscoveryQuery (GitHub repo / code / known id)
  -> ProductSearchObservation           -> RepositoryObservation
  -> ProductSourceArtifact (safe fetch) -> VerifiedRepository (metadata by stable id)
  -> ProductEntity (identity)           -> RepositorySnapshot (bounded)
  -> ProductPriorArtCandidate           -> RepositoryNetwork (declared lineage)
                                        -> OpenSourcePriorArtCandidate
```

Graph: `build_phase2h_product_oss_graph()` (`src/graph/phase2h_graph.py`),
nodes `LOAD_PRODUCT_OSS_RESEARCH_RUN` ... `FINALIZE_PRODUCT_OSS_RESEARCH`. It
consumes an open research run and leaves it non-terminal. `NOVELTY`,
`CLOSEST_PRIOR_ART`, `SCORING`, `TRUST_GATE` and every Phase 2G patent node are
in `FORBIDDEN_NODES`.

Runtime configuration (`config["configurable"]`, never checkpointed):

| key | meaning when absent |
|---|---|
| `product_search_provider` | product track `BLOCKED_AUTH`, nothing sent |
| `product_fetcher` | no page fetched; hits stay observations (recorded as truncation) |
| `product_host_registry` | no vendor domains: no page can be first-party |
| `github_provider` | OSS track `BLOCKED_AUTH`, nothing sent |
| `product_oss_cutoff` | every candidate `NO_CUTOFF` |
| `discovery_sleeper` | backoff waits are not performed (`NoSleep`) |

## 2. Ownership and immutability

Outputs live on `ResearchRun.product_prior_art` and
`ResearchRun.open_source_prior_art`. Nodes replace only those fields. The
`project` channel is never written. Claims, statuses, confidences, evidence
references, `ProjectState.scores`, `trust_gate`, `evaluation_status`, and the
Phase 2C-2G artifacts are untouched. The Gold eval checks this on fully
populated worlds (real 2E, 2F and 2G graphs).

## 3. Query planning

Planned from canonical claim text and the Phase 2E component inventory only
(`src/research/discovery/planner.py`). Purposes are `EXACT_TECHNICAL_PHRASE`,
`CORE_CONCEPT`, `FUNCTION_MECHANISM`, `COMPONENT_COMBINATION`,
`SYNONYM_VARIANT`, `BROADER_CATEGORY`, `PRODUCT_CATEGORY`,
`IMPLEMENTATION_TERM` (GitHub code search), `SOFTWARE_LIBRARY_TERM` and
`KNOWN_IDENTIFIER` (a `github.com/owner/name` in the claim becomes a metadata
lookup).

Every query carries a stable `query_id = uuid5(run, stable_key)`, the claim and
component ids, the language (`en`/`ar`/`mixed`), provider, operation, and term
derivations with the verbatim source text. `expansion_depth` is pinned to zero
because queries are never derived from results.

Refusals at plan time and again at dispatch:

- `PII_DETECTED`: the refusal retains no text.
- `SUSPECTED_PROMPT_INJECTION`.
- `PROVIDER_QUALIFIER_IN_TERM`: `site:`, `repo:`, `user:` or a leading `-`.
- `INVALID_QUERY`: control characters or an unbalanced quote.
- `QUERY_TOO_LONG` (more than 256 characters).
- `DUPLICATE_QUERY`.
- `QUERY_BUDGET_EXCEEDED`.
- `OPERATION_REQUIRES_AUTHENTICATION`: code search without credentials.

Optional English expansion of Arabic claims is untrusted. Each term must quote
a verbatim claim substring and pass PII, injection and qualifier checks, and
the prompt version is recorded.

## 4. Safe fetching (SSRF)

`src/research/discovery/safe_fetch.py`. Before any connection it refuses:

- any scheme other than `http`/`https`;
- ports other than 80/443;
- embedded credentials;
- `localhost`, `*.local`, `*.internal`, single-label hosts and metadata hostnames;
- any host that is, or resolves to, a non-global address. That covers loopback,
  private, link-local (including `169.254.169.254`), CGNAT, multicast,
  reserved, unspecified and IPv4-mapped IPv6.

Redirects are manual. Every hop is rechecked and recorded, and the chain is
bounded. Bodies are read under a hard byte limit; an oversized body is
`CONTENT_TOO_LARGE`, never truncated and accepted. There is no JavaScript, no
cookie jar between requests (a fresh client per fetch), environment proxies
are ignored, and no credentials are sent.

DNS rebinding is closed at the connection (Phase 2H.1). The live transport
builds an `httpcore` connection pool around `PinnedNetworkBackend`, which is
the only code that chooses a destination IP: inside the connect step it
resolves the host once, refuses unless every answer is public, connects to a
validated IP literal (the socket layer never sees a hostname, so it cannot
re-resolve), and re-checks the connected peer address before any byte is sent.
TLS SNI and certificate verification (`check_hostname=True`, `CERT_REQUIRED`)
and the `Host` header still use the URL's hostname. Each redirect hop gets the
same preflight check and the same pinned connect. Offline tests drive the real
pool with a recording connector and prove a rebound private address is never
contacted (`tests/test_phase2h1_dns_pinning.py`).

## 5. Product identity and anti-inflation

See ADR-019. Identifiers are read only from schema.org JSON-LD
`Product`/`SoftwareApplication` objects. Strong keys are:

- `gtin:<14 digits>`, valid check digit only;
- `app:<package id>`;
- `manufacturer_part_number:<brand>:<mpn>` and
  `manufacturer_model_number:<brand>:<model>`, brand required.

Grouping happens only on a strong key. Byte-identical content is
artifact-level duplication, not product identity (Phase 2H.1): boilerplate,
placeholder pages and one template serving many products all hash alike, so
identical bytes become an `IDENTICAL_CONTENT_HASH` probable link between
entities that stay separate. Probable links are `IDENTICAL_CONTENT_HASH`,
`SHARED_RETAILER_SKU`, `SAME_STATED_BRAND_AND_PRODUCT_NAME` and
`SAME_UNQUALIFIED_MODEL_NUMBER`. A group whose members carry two different
strong keys of one kind is split back into single-artifact entities that
record the conflict. The entity validator requires a verified strong identity
for any multi-artifact entity; the run validator re-derives that every
multi-artifact entity is connected by strong keys alone, that no verified
entity spans conflicting keys, that one strong key is one entity, and that
separate entities holding byte-identical artifacts carry the duplicate-content
link (`PRODUCT-IDENTITY-V2`).

## 6. Product dates and cutoff

There are six separate date facts, all source-reported. `vendor_launch_date`
and `vendor_availability_date` are only filled for first-party pages. A
marketplace `releaseDate` is a `marketplace_listing_date`. The qualification
uses the earliest of page-published, vendor-launch, vendor-availability and
marketplace-listing across the entity's artifacts, and records the field, the
value and the artifact. The possible qualifications are
`DATED_ARTIFACT_BEFORE/ON/AFTER_CUTOFF`, `ARTIFACT_DATE_UNKNOWN` and
`NO_CUTOFF`. `proves_historical_availability` is always `False`.

## 7. Repository identity, snapshots and networks

- Identity is `github:<numeric id>`. `observed_full_names` keeps every name
  (rename/transfer), and a reused name pointing to another id is recorded as an
  `identity_mismatch_repository_id`.
- Code hits collapse at repository id, capped per repository
  (`max_code_hits_per_repository`), and the surplus is recorded.
- Snapshots: README (contents API, base64), description, topics, up to N
  manifests, release metadata and code-search fragments. Each is hashed, with
  ref/path/sha and truncation recorded. A fragment is never `is_full_file`.
- Networks:
  - A fork's root is its declared `source` (otherwise its `parent`, marked
    `root_chain_complete=False`).
  - A mirror roots its own network.
  - A template derivative groups under its template.
  - `independent_root` holds only for a `ROOT_REPOSITORY` root.
  - Root metadata may be looked up within `max_network_lookups`.

## 8. Repository dates and cutoff

The precedence is `RELEASE_PUBLISHED_AT`, `RELEASE_CREATED_AT`,
`REPOSITORY_CREATED_AT`, `COMMIT_COMMITTED_AT`, then `COMMIT_AUTHORED_AT`.
Draft releases are ignored. Every candidate records the field used and a
historical-visibility limitation. Created-at and commit-dated candidates carry
`CREATED_AT_NOT_PROVEN_PUBLIC_SINCE` or
`COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY`.

## 9. Boundedness, errors and retry

`DiscoveryBudget` records each limit beside what it cut. The limits are
queries per claim and per run, results per query, pages, total observations,
fetches or metadata lookups, artifact/content bytes, code hits per repository,
network lookups, retries and the timeout. The error kinds are
`AUTHENTICATION_ERROR`, `RATE_LIMITED`, `QUOTA_LIMITED`, `TIMEOUT`,
`CONNECTION_ERROR`, `PROVIDER_ERROR`, `PARSE_ERROR`, `UNSUPPORTED_OPERATION`,
`INVALID_QUERY`, `FETCH_BLOCKED`, `FETCH_UNSAFE` and `CONTENT_TOO_LARGE`. Only
rate-limit, timeout, connection and provider errors are retried, with bounded
backoff that honours `retry-after`. A failure is a recorded execution, never an
exception, so one failing query never discards another's results.

## 10. Idempotency

Query, observation, artifact, entity, network, snapshot and candidate ids are
deterministic `uuid5`s of stable inputs. Executed pages are keyed
`<stable key>#p<page>` and never re-sent. Each stage is recorded in
`stage_markers` and is a no-op when replayed. A finished subrun is never
reopened. The interrupted-and-resumed graph yields the same candidates.

## 11. Provider status

| provider | status | notes |
|---|---|---|
| GitHub REST | `IMPLEMENTED_DOCUMENTED_ONLY` | see `phase2h_github_provider_contract.md` |
| Brave Web Search | `IMPLEMENTED_DOCUMENTED_ONLY` | see `phase2h_product_web_provider_contract.md` |
| Safe web fetcher | `IMPLEMENTED_DOCUMENTED_ONLY` | project-owned |

Live tests: `RUN_GITHUB_PRIOR_ART_TESTS=1` and `RUN_BRAVE_SEARCH_TESTS=1`
(`tests/test_product_oss_live_integration.py`). A skipped test is NOT RUN.

## 12. Gold eval

`evals/product_oss_prior_art/v1/cases.jsonl` holds 250 cases (118 en, 78 ar,
54 mixed; 134 categories). The schema is in
`evals/product_oss_prior_art/v1/schema.md`, and the file is regenerated by
`scripts/generate_phase2h_gold.py`. Run it with
`./.venv/Scripts/python.exe -m src.evals.product_oss_prior_art.cli`.

Each case runs the real Phase 2E, 2F and 2G graphs and then the real Phase 2H
graph against scripted fakes. The scorer independently re-derives URL safety
(via `ipaddress`), GTIN validity, relationships from the scripted metadata,
root counts and chronology. It tallies 68 release-blocking gates (Phase 2H.1 added
`content_hash_product_merge`, `distinct_strong_ids_collapsed`,
`content_hash_as_verified_identity` and `duplicate_content_relation_lost`), all of which
must be zero with non-zero denominators. 23 quality families must be exactly
1.0. Negative controls mutate finished runs and must all be rejected.
