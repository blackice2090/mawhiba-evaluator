# Phase 3A Gold case schema

One JSON object per line in `cases.jsonl` (model: `src/evals/methodology_review/dataset.py`).

- `case_id` `GM-NNN`, `language` (en / ar / mixed), `categories`.
- Input: `project_type`, `domains`, `gap_variant`, `claim_variant`, `submission`.
- `script`: what the untrusted scripted model returns (may be wrong or hostile on purpose).
- `expected`: deterministic behaviour that is correct given that script, authored from policy.
- `truth`: model-judgment ground truth, which seeded wrong judgments may contradict.
- `flags`: authored facts a release gate needs (signaled overlays, fabricated strings, ...).
- `bounds`, `no_model`, `results_leak`, `interrupt_before`, `rerun`, `twin`, `mutate`, `controls`.

Regenerate with `./.venv/Scripts/python.exe scripts/generate_phase3a_gold.py`.
