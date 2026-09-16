# Academic retrieval Gold dataset — v1 schema

One JSON object per line in `cases.jsonl`, so a case is reviewable in a diff.
The loader is `src/evals/academic/dataset.py`; the runner drives each case
through the real Phase 2B graph with the deterministic fake providers.

All data is synthetic. Identifiers, titles, venues and identity strings are
invented; none of them refers to a real paper, a real person or a real school.

---

## Case

```jsonc
{
  "case_id": "AR-001",              // ^AR-\d{3,}$, unique
  "language": "en",                 // en | ar | mixed
  "categories": ["cross_provider_dedup", "same_doi_all_providers"],
  "queries":   [ /* GoldPlannedQuery */ ],
  "privacy":   { /* synthetic identity, optional */ },
  "providers": { "CONSENSUS": { /* GoldProviderScript */ } },
  "budget":    { /* budget overrides, optional */ },
  "expected":  { /* AcademicGoldExpectation */ },
  "notes": "English only. What the case is for."
}
```

### `queries` — the verified query plan the case starts from

```jsonc
{
  "key": "q1",                      // stable local handle; the query_id is derived from it
  "purpose": "TECHNOLOGY",          // a QueryPurpose value
  "query": "YOLOv8 plant disease",
  "branch": "ACADEMIC",             // default; set to another branch to test routing
  "accepted": true,                 // false models a query the Phase 2A verifier rejected
  "source_term": ""                 // defaults to the first word of the query
}
```

Plans are constructed rather than produced by the planner. Phase 2B is what is
being measured; query provenance is measured by the research-planning eval.

### `providers` — raw provider JSON, keyed by `AcademicProvider`

```jsonc
{
  "records": [ /* raw provider records, in that provider's own shape */ ],
  "payload": null,                  // a whole response envelope, for malformed-envelope cases
  "failure": "TIMEOUT",             // an AcademicErrorKind; the provider cannot be asked
  "leading_failures": ["RATE_LIMITED"],  // fail these attempts, then serve the records
  "http_status": 429,
  "retry_after_seconds": 2.0
}
```

A provider with no entry answers `EMPTY` — it worked and found nothing, which is
not a failure. Records are raw on purpose: the case exercises the real
normalizer, including how it rejects a bad record.

### `budget` — optional overrides

```jsonc
{
  "enabled_providers": ["CONSENSUS"],
  "max_academic_queries_per_run": 1,
  "max_results_per_query_per_provider": 1,
  "max_results_per_provider_per_run": 1,
  "max_total_academic_candidates": 1
}
```

### `expected` — authored from the provider payloads alone

```jsonc
{
  "branch_outcome": "PARTIAL",      // AcademicBranchOutcome
  "logical_source_count": 1,
  "candidate_count": 2,             // optional
  "queries_executed": 1,            // optional
  "excluded_reasons": ["PII_DETECTED"],
  "rejection_reasons": ["MALFORMED_RECORD"],
  "provider_statuses": { "OPENALEX": ["TIMEOUT"] },
  "budget_truncated": true,         // optional
  "sources": [
    {
      "identifier_kind": "DOI",
      "identifier": "10.1234/aaaa",
      "providers": ["CONSENSUS", "OPENALEX"],
      "title": "…",                 // optional
      "publication_year": 2021,     // null means the merge must leave it unknown
      "source_type": "JOURNAL_ARTICLE",
      "is_retracted": false,        // null means unknown, which is not false
      "is_preprint": true,
      "citation_counts": { "CONSENSUS": 10, "OPENALEX": 12 },
      "conflict_fields": ["publication_year"]
    }
  ]
}
```

`excluded_reasons` and `rejection_reasons` are asserted as subsets: a case names
the reasons it is about, not every reason the run happens to produce.

---

## Authoring rules

1. **Never generate a run and declare it correct.** The expectation says what a
   correct normalizer, verifier, deduplicator and merger must produce from the
   payloads. If the code disagrees, one of the two is wrong and both are read.
2. **Synthetic data only.** No real student identity, no real institution, and
   no copied bibliographic record.
3. **English structure.** Case ids, categories, purposes and notes are English.
   Arabic and mixed-language text appears only in value positions — a query
   string or a paper title — and is stored verbatim, never transliterated.
4. **One case, one point.** A case names in `categories` what it exists to
   prove, and `notes` says it in one English sentence.

## Versioning

`v1` is the directory. A change that alters what an existing case asserts is a
new dataset version, not an edit: the metrics of a run are only comparable to
another run of the same dataset version, connector versions, normalizer version
and dedup version, all of which the eval report records.
