# Phase 2H Gold Case Schema (`cases.jsonl`)

One JSON object per line, validated by
`src/evals/product_oss_prior_art/dataset.py::ProductOssGoldCase`. Regenerate
with `./.venv/Scripts/python.exe scripts/generate_phase2h_gold.py`. Never
generate expectations from system output.

| field | meaning |
|---|---|
| `case_id` | `PH-NNN` |
| `language` | `en`, `ar` or `mixed`: the claim text language |
| `tracks` | `product` and/or `oss`; a track not listed has its provider switched off |
| `categories` | coverage categories (at least 78 distinct across the file) |
| `claims` | canonical claims `{claim_id, claim}` fed through the real 2E, 2F and 2G graphs first |
| `privacy` | optional identity context (`person_names`, `school_names`, `emails`) |
| `cutoff` | optional `{date, source}`; absent means `NO_CUTOFF` |
| `product.provider` / `product.fetcher` | whether the web-search provider and the safe fetcher are configured |
| `product.web` | search script: key = exact query text, purpose, operation or `*`; `seq:<key>` consumes a list per call. A value is a hit list, `{"error": KIND}`, or `{"pages": [[...]], "more": bool}` |
| `product.pages` | URL to `{kind: html|redirect|error, title, body, json_ld[], meta_published, content_type, location, error, status, pad_bytes, raw}`, served through the real `SafeWebFetcher` |
| `product.resolver` | host to addresses for the fake resolver; any other host resolves to a public address |
| `product.vendors` | reviewed vendor domains `{host, vendor, kind}` |
| `product.settings` / `oss.settings` | `ProductResearchSettings` / `OpenSourceResearchSettings` overrides |
| `oss.provider` / `oss.authenticated` / `oss.token` | scripted GitHub; `token` is a credential-bearing attribute that must never be persisted |
| `oss.search` | key = query text, `repo:*`, `code:*` or `*`; a value is a hit list, `{"error": KIND}`, or `{"pages", "total", "incomplete"}` |
| `oss.repos` | full_name to `fakes.github_repo` keyword arguments (`rid`, `full_name`, `fork`, `parent`, `source`, `mirror_url`, `template`, ...) or `{"error": KIND}` |
| `oss.readmes` / `oss.contents` / `oss.releases` / `oss.commits` | scripted file, release and commit responses |
| `interrupt_before` | run once interrupted at this node and resumed; the result must equal the uninterrupted run |
| `rerun` | invoke the graph a second time; the subruns must be unchanged |
| `negative_controls` | named contract mutations that must be refused |
| `expected` | authored expectations: `product.*`, `oss.*`, `state.*`. A suffix `_includes` is a subset check, `_min` / `_max` are bounds, a dict is an exact count map, and anything else is equality |
