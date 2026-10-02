# Phase 2I Gold Case Schema (`cases.jsonl`)

One JSON object per line, validated by
`src/evals/novelty_differentiation/dataset.py::NoveltyGoldCase`. Regenerate with
`./.venv/Scripts/python.exe scripts/generate_phase2i_gold.py`. Expectations are
authored from each case's own source text and the policy documents; never generate
them from system output.

| field | meaning |
|---|---|
| `case_id` | `NI-NNN` |
| `language` | `en`, `ar` or `mixed`: the claim text language |
| `categories` | coverage categories (at least 80 distinct across the file) |
| `claims` | canonical claims `{claim_id, claim}` fed through the real 2E and 2F graphs first |
| `cutoff` | optional `{date, source}`; absent means `NO_CUTOFF` |
| `patent.records` | scripted EPO OPS publications. `family` states what the FAMILY SERVICE does: `"unavailable"` (FAMILY_DATA_UNAVAILABLE), `"failed"` (FAMILY_RESOLUTION_FAILED), or a numeric id (one member = SINGLETON_FAMILY, two or more = VERIFIED_FAMILY); `hidden_family_members` adds published members the search did not return. A singleton is never inferred from a record count |
| `product` / `oss` | the Phase 2H Gold shapes (`pages`, `vendors`, `repos`, `readmes`, `contents`, ...) |
| `tags` | tag -> patent publication key, product URL fragment or repository full name; resolved from upstream records only |
| `script` | what the structured model returns: `features` per claim (a string names a failure) and `comparisons` (candidate marker, per-feature judgments with evidence, `rest`, `failure`, `claim_id`). It can fabricate, mis-cite, follow an injected instruction or leak the system prompt |
| `bounds` | `NoveltyComparisonBounds` overrides |
| `no_model` | run with no structured model provider |
| `drop_sufficiency` | remove the Phase 2E run so the claim has no usable inventory |
| `interrupt_before` / `rerun` | resume-after-interrupt and replay idempotency checks |
| `injection` / `credential` | enable the injection and credential-persistence gates |
| `negative_controls` | named tamperings that must be caught (by a gate or by the contract) |
| `expected` | authored expectations, dotted keys: `claim.<id>.posture` / `.diff` / `.units` / `.chronology` / ..., `cand.<tag>`, `rel.<tag>`, `anchors.<tag>`, `resolution.<tag>`, `patent.publication_count`, `project.*`. A suffix `_includes` / `_excludes` is a subset check; a dict is a subset match; anything else is equality |

Quality families may overlap (a relation feeds relation-kind and source-disclosure
accuracy). Gate denominators never do: each is the exact count of that gate's real
opportunities.
