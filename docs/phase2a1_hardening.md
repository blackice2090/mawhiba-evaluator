# Phase 2A.1 — Research Foundation Hardening

**Status:** Implemented
**Scope:** Official host coverage, seed strategy and currency, the baseline
test-count investigation, a shared LLM invocation layer, global source identity
and deduplication fingerprints, and multilingual research planning.
**Prior phase:** `docs/phase2a_research_foundation.md`
**Decision records:** ADR-006, ADR-007 (both unchanged and still binding)

Phase 2A was functionally complete but not approved for merge. This phase
resolves the review findings without weakening any Phase 2A guarantee and without
starting Phase 2B: there is still no academic, patent, product, open-source or
standards retrieval.

---

## 1. Official Mawhiba host coverage

Phase 2A allowed two hosts. The current Mawhiba service experience — including the
National Olympiad for Scientific Creativity service page — is served from
`mawhiba2.mawhiba.sa`, so a legitimate official source was being rejected.

Allowed hosts now:

```text
mawhiba.sa
www.mawhiba.sa
mawhiba2.mawhiba.sa
```

Matching stays **exact-host**. There is deliberately no `*.mawhiba.sa` rule: a
wildcard would admit any present or future subdomain — including one that is
delegated, parked or compromised — on nothing more than a name pattern. Adding a
confirmed host to a reviewed list is a cheap, auditable step; trusting a pattern
is not. Every redirect hop is still checked against the same list.

Still rejected, with tests:

```text
mawhiba.sa.example.com          mawhiba2.mawhiba.sa.example.com
mawhiba-login.sa                mawhiba2-mawhiba.sa
example.com?redirect=mawhiba.sa portal.mawhiba.sa   mawhiba3.mawhiba.sa
http://mawhiba2.mawhiba.sa/     https://mawhiba2.mawhiba.sa@evil.example/
```

---

## 2. Seed strategy: evergreen versus dated official pages

The Mawhiba root alone was not a sufficient default seed. Seeds are now typed
configuration (`OfficialSeed`), each carrying the role a reviewer assigned:

| Page kind | Meaning | Edition |
|---|---|---|
| `EVERGREEN_SERVICE_PAGE` | describes the programme, not one event | must not declare one |
| `CURRENT_EVENT_PAGE` | the event page for a stated edition | required |
| `HISTORICAL_EVENT_PAGE` | a past edition, kept deliberately | required |
| `DISCOVERY_PAGE` | entry point for finding pages, not a rules page | must not declare one |

Default seed (the only one shipped):

```text
https://mawhiba2.mawhiba.sa/services/the-national-olympiad-for-scientific-creativity-ibdaa/
    kind = EVERGREEN_SERVICE_PAGE
```

`OFFICIAL_ROOT_URL` remains available as an opt-in `DISCOVERY_PAGE` seed. **No
event page is shipped as a default**, so a dated registration page can never
become "the current rules" by accident. The settings model refuses any seed that
is not on the allowlist, and refuses an event page that does not declare its
edition.

---

## 3. Official source currency

Five things are now separate, and none implies another:

```text
official authority      -> the allowlisted domain and verified capture
publication date        -> only from explicit page metadata, else None
competition edition     -> from the seed declaration, or a single year in the page title
retrieval date          -> when we fetched it; never an input to currency
effective/current status -> OfficialCurrency, decided deterministically
```

`assess_currency()` decides, using no clock at all:

| Situation | Currency |
|---|---|
| evergreen service page, no year in title | `EVERGREEN` |
| evergreen page whose title names one year | `UNDETERMINED` (it is behaving like an event page) |
| historical event page | `HISTORICAL_EDITION` |
| event page, no configured `target_edition` | `UNDETERMINED` |
| event page, edition == target | `CURRENT_EDITION` |
| event page, edition < target | `HISTORICAL_EDITION` |
| page title contradicts the declared edition | `UNDETERMINED` |
| discovery page | `UNDETERMINED` |

Requirement status follows the snapshot's currency:

```text
CURRENT_EDITION    -> VERIFIED_CURRENT
EVERGREEN          -> VERIFIED_EVERGREEN
HISTORICAL_EDITION -> HISTORICAL
UNDETERMINED       -> VERIFIED_CURRENCY_UNKNOWN
```

Only `VERIFIED_CURRENT` and `VERIFIED_EVERGREEN` are *applicable*
(`OfficialRequirementsResult.applicable_requirements`, `official_judging_criteria`).
Historical and superseded requirements are **kept, never applied, never discarded** —
a 2025 rule stays available for comparison and audit.

Tested: an official 2025 page retrieved in 2026, a current evergreen service page,
an undated evergreen page, and two official pages from different editions.

---

## 4. Baseline test-count investigation (630 vs 631)

**Cause: a reporting artefact of a filesystem-driven parametrized test, not a code or
environment difference, and not a missing or extra test on `main`.**

Evidence, gathered with two throwaway git worktrees of `main` (`2555616`):

| Tree | Collected | Result |
|---|---|---|
| `main`, clean | 643 | **630 passed**, 13 skipped |
| `main` + untracked `PHASE_2A_EXECUTION.md` | 644 | **631 passed**, 13 skipped |

The single differing node id:

```text
tests/test_language_policy.py::test_developer_surfaces_contain_no_arabic[PHASE_2A_EXECUTION.md]
```

`test_developer_surfaces_contain_no_arabic` is parametrized over
`PROJECT_ROOT.rglob("*.py" | "*.md" | "*.toml")`, which walks the **filesystem**, not
git. The Phase 2A execution spec was placed in the repository root as an untracked
file before the Phase 2A baseline run, so it added exactly one parametrized case.
The manually verified 630 was measured before that file existed.

Consequences:

* No test was added, removed or renamed on `main`.
* No Python-version or environment behaviour is involved.
* The suite count legitimately moves with the number of scanned files on disk. That
  is intended: the guard must scan any file present, including untracked ones, or a
  developer could bypass the language policy simply by not committing a file yet.

`tests/test_phase2a1_hardening.py` pins this behaviour: it documents the cause and
proves that a new Markdown file on disk adds a case.

---

## 5. Shared LLM invocation layer

Phase 2A had `src/research/*` importing `_call_with_retries` from
`src/intake/extractor.py` — research depending on an intake private, the wrong
dependency direction.

The retry policy is a property of the LLM layer, so it now lives there:

```text
src/llm/invocation.py :: call_structured_model_with_retries(...)
```

```text
before:  research  ->  intake.extractor._call_with_retries
after:   intake    ->  llm.invocation.call_structured_model_with_retries
         research  ->  llm.invocation.call_structured_model_with_retries
```

Semantics are unchanged and re-tested at the shared layer: transport faults,
truncation and empty output are retried to the bound; refusals and parse errors are
never retried; attempt counts, prompts, model routing and fake-provider determinism
are identical. Tests assert that all three call sites resolve to the *same function
object*, that no `_call_with_retries` remains anywhere under `src`, that no module
under `src/research` imports `src.intake.extractor`, and that exactly one module
contains the retry loop.

---

## 6. Global source identity

Per-run sequence ids (`SRC-001`) were safe only while one branch produced sources.
With several branches and several runs they would collide on merge.

```text
source_id   SRC-<uuid4>   canonical, opaque, globally collision-resistant
display_id  SRC-001       human-readable sequence for reports; never identity
```

* `new_source_id()` is the only mint, and every Phase 2A+ contract
  (`OfficialSourceSnapshot`, `OfficialRequirement`, `ConflictSide`,
  `SourceVerificationDecision`) accepts **only** the canonical form.
* Phase 0 `SourceRecord`, `EvidenceRecord`, `PriorArtRecord` and `Rubric.source_id`
  accept canonical **or** legacy sequence ids, so existing snapshots and fixtures
  still validate. Legacy ids are never minted by new code.
* A `display_id` must match the sequence pattern, so a canonical id cannot be passed
  off as one.

---

## 7. Source deduplication identity

Global uniqueness is not deduplication, so identity is a separate contract:

```python
SourceFingerprint(identifier_kind, identifier, content_hash)
```

`SourceIdentifierKind` covers `CANONICAL_URL` today and `DOI`, `OPENALEX_ID`,
`SEMANTIC_SCHOLAR_ID`, `PMID`, `ARXIV_ID`, `PATENT_PUBLICATION_NUMBER` and
`REPOSITORY_ID` for later branches — the contract does not block Phase 2B. There is
deliberately **no title kind**: titles collide across works and vary within one work,
so deduplicating on a title is not expressible.

Identifiers are normalized on construction (URL canonicalization; DOI lower-cased and
stripped of an `https://doi.org/` prefix), and a fingerprint whose identifier is not
already normalized is rejected.

Two keys, two questions:

```text
logical_key  = kind:identifier            "is this the same source?"
version_key  = (logical_key, content_hash) "is this the same version of it?"
```

Proven for official web sources:

* same canonical URL + same content hash → same content version (one snapshot, even
  when reached through two seeds);
* same canonical URL + different content hash → different version, still the **same
  logical source**;
* a capture without a hash is never "the same version" as anything.

---

## 8. Multilingual research planning

**Vocabulary policy: Option A.** A query word must come from a verified source term,
an explicit expansion term, or a *small reviewed language-specific* list of generic
search words. There is no large uncontrolled stopword list, and deterministic code
does not compose queries (Option B), which keeps Phase 2A's provenance model intact.

* English list stays in `src/research/vocabulary.py`.
* Arabic list lives in `src/research/data/search_vocabulary_ar.json`
  (`AR-SEARCH-VOCABULARY-V1`): generic search words only — no technology names, no
  domain terms, no project facts. It is data, not developer prose, which is why it is
  a JSON file rather than Python (language policy), and it is size-capped and tested.
* Arabic confirmation-bias markers and Arabic injection markers were added, so
  advocacy phrasing and instruction-like text are refused in Arabic exactly as in
  English — including inside official Arabic page content.

### Gold dataset

| | Phase 2A | Phase 2A.1 |
|---|---|---|
| English | 27 | 27 |
| Arabic | 2 | **12** |
| Mixed | 3 | **8** |
| Total | 32 | **47** |

New coverage: Arabic problem statement, Arabic solution with English technology
names, Arabic novelty claim, Arabic performance claim, Arabic IoT / AI / robotics /
embedded projects, Arabic ambiguous technology, Arabic prompt injection, Arabic PII,
Arabic confirmation bias (both satisfied and violated), mixed YOLO / Raspberry Pi
text, and mixed-domain terminology.

### Multilingual safety gates

Release-blocking metrics are now reported **per language**, so an aggregate pass
cannot hide a failing subgroup. Deterministic results (fake provider):

```text
             cases  traceability   pii  invalid-ref  mutation  untraceable
en              27      67/67       0/93     0/107      0/27       0/67
ar              12      36/36       0/48      0/44      0/12       0/36
mixed            8      24/24       0/32      0/42       0/8       0/24
```

---

## 9. Execution file resolution

`PHASE_2A_EXECUTION.md` was an untracked file in the repository root. It is the
reviewed specification Phase 2A was built against, so it is kept as documentation and
committed at:

```text
docs/phase2a_execution_spec.md
```

The working tree is clean at the end of this phase.

---

## 10. What did not change

Every Phase 2A guarantee is intact and still tested: query provenance, search result
is not evidence, PII minimization, anti-confirmation bias, official versus advisory
rubric separation, exact requirement provenance, content hashes, `ProjectState`
immutability during planning, deterministic no-network tests, and official retrieval
failing without any fallback to model memory.

---

## 11. Remaining limitations

1. Legacy `SRC-001` ids remain loadable for Phase 0 data; merging such data with
   canonical ids needs a remap step.
2. Competition edition comes from a reviewer's declaration or a single year in a page
   title; no other detection is attempted.
3. `target_edition` is configuration. Without it, event pages are `UNDETERMINED`
   rather than current — deliberately conservative.
4. Arabic matching is exact: no alef/ya normalization, no diacritic folding, in line
   with the no-fuzzy-matching rule.
5. The Arabic vocabulary is reviewed but small; a legitimate Arabic query word outside
   it must be declared as an expansion term.
6. Official sources are still not merged into `ProjectState.sources`.
7. No live planner eval; all planning numbers come from scripted responses.
