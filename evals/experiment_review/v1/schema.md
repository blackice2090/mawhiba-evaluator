# Phase 3B Experiment Review Gold dataset (v1)

`cases.jsonl` holds one JSON object per line, regenerated deterministically by `scripts/generate_phase3b_gold.py`
(the template modules are `scripts/phase3b_gold_*.py`). Running the generator twice produces byte-identical output.
The loader and schema are `src/evals/experiment_review/dataset.py` (`ExperimentGoldCase`, `extra="forbid"`).

Gold expectations are AUTHORED from the approved specification (`src/evals/experiment_review/catalog.py`, a
hand-transcribed copy of the contract) and from each case's own submission text. They are never produced by running
Phase 3B and declaring the output correct. The generator imports nothing from the Phase 3B production modules.

## Fields

| field | meaning |
|---|---|
| `case_id` | `GE-NNN`, unique |
| `language` | `en`, `ar` or `mixed` (Arabic prose with English technical terms) |
| `semantic_family_id` | language-neutral scenario identity; translations of one scenario share it |
| `category` | raw category label (several families share one) |
| `project_type` | `SCIENTIFIC_RESEARCH`, `ENGINEERING_PROJECT`, `HYBRID` or `UNKNOWN` |
| `submission` | the verbatim student text (`null` for the no-submission binding case) |
| `claims` | the canonical claim bound by Phase 2J (`C-001`) |
| `phase2j_world` | which real Phase 2J gap variant the case runs over (`default`, `baseline`, `no_condition`, `no_requirement`) |
| `phase3a_context` | Phase 3A is run over the same submission without a model; it is context only |
| `model_script` | the SCRIPTED UNTRUSTED model: what a possibly-misbehaving model returns for segmentation, extraction, applicability and linkage. It may be wrong or hostile on purpose |
| `bounds` | `ExperimentReviewBounds` overrides (window, experiments, excerpts, calls, retries) |
| `expected` | authored deterministic expectations given that response (key grammar below) |
| `truth` | the separate MODEL-JUDGMENT ground truth (true experiments, types, links, alignment, baseline relevance, owners, result spans, ...), so a structurally valid but semantically wrong judgment is measured, not declared correct |
| `flags` | authored facts a release gate needs (the true result texts, the declared ones, injected markers, ...) |
| `negative_control_tags` | `["*"]`: every negative control that has an opportunity in the case |
| `rerun`, `interrupt_before`, `twin`, `twin_data`, `mutate`, `legacy_leak`, `no_model` | replay, checkpoint-resume, order / prefix / result-mutation twins, upstream mutation between bind and finalize, legacy `ProjectState.results/experiments`, and a missing provider |

## Expectation key grammar (read from the serialized run, never through a Phase 3B validator)

`status`, `posture`, `calls`, `search`, `network`, `socket_attempts`, `errors`, `rejected`, `n_exp`, `n_quar`,
`quar_texts`, `quar_kinds`, `untested`, `stages_called`, `exec_flags_false`, `later_prompt_leak`, `placeholder_shown`,
`track.<TRACK>`, `trackn.<TRACK>`, `ownedby.<TRACK>`, `cov.V1`, `covreasons.V1`, `covering.V1`, `attempting.V1`,
`run_issue_stage.<CODE>`, `replay.*`, `twin.*`, `legacy.*`, `mutation.*`, and per experiment (document order)
`x<i>.type|posture|track|ownbasis|exec|issues|ndef|nlinks|revision|cond`, `x<i>.app|basis|doc|adq|nex|judged|triggers.<KIND>`,
`x<i>.link|lnex|meas|match|timing|bl|blmatch.<T1|V1>`, `x<i>.blprop.<V1>.<PROPERTY>`.

## What the Gold measures

Deterministic families (exactly 1.0), model-judgment families (reported honestly, never forced), at least 150
release gates (each with a real, non-zero denominator and zero violations; thin gates are listed), and negative
controls (each refused for the intended reason, by the production run contract or by an independent Gold gate).
It never evaluates whether a reported result is correct: results are quarantined and never read.
