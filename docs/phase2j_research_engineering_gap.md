# Phase 2J — Research / Engineering Gap Assessment

Status: implemented (production pipeline, graph, prompts, contracts) and evaluated offline
(Gold dataset, 45 deterministic quality families, 138 release gates, 55 negative controls).

Governing specification: `PHASE_2J_RESEARCH_ENGINEERING_GAP_ASSESSMENT.md`.
Decision record: `docs/adr/ADR-021-gap-is-an-evidence-bounded-posture.md`.

## What it is

Phase 2J decides, in Python, whether the bounded evidence earlier phases
already verified supports a defensible research gap, engineering gap or hybrid
gap that the student's project actually targets. It lives on
`ResearchRun.research_engineering_gap`, never in `ProjectState` and never in
`ProjectState.gap` (the `GAP` node stays unused, like `NOVELTY` in Phase 2I).

It is not a search, a methodology review, a result judgement, a novelty or
patentability conclusion, or a score. None of those has a field.

## The chain

```
existing capability   anchored excerpt of what existing work demonstrably does
limitation            anchored, ADMISSIBLE: stated, never an absence
condition             anchored; required only when the limitation is condition-specific
project linkage       one judgment per (differentiating feature, limitation)
validation requirement metric / baseline sliced from the claim or a verified excerpt
counterevidence       bounded review of the existing inventory, coverage recorded
```

Gap **existence** (`GapExistence`) and project–gap **linkage**
(`ProjectLinkageLevel`) are separate derived values. A real limitation is not a
project gap because the project has a differentiating feature.

## Trust boundary

| Layer | Decided by |
|---|---|
| Which excerpt, which limitation form, which facet, which condition dimension, which linkage relation, which counterevidence kind | the model *proposes* (three structured calls) |
| That the excerpt is literally in the shown text at one validated occurrence; run binding; hashes; independence; source quality; chronology; existence, linkage, kind, scope, corroboration, posture | deterministic code |

The model never sees or returns a posture, score, verdict or threshold; the DTOs
(`src/research/gap/dto.py`) are `extra="forbid"` and carry no such field.

`LinkageRelation` (`ADDRESSES_LIMITATION`, `PARTIALLY_ADDRESSES_LIMITATION`,
`RELEVANT_BUT_NOT_ADDRESSING`, `UNRELATED`, `INSUFFICIENT_LINKAGE_EVIDENCE`) is
`MODEL_ASSISTED_BOUNDED_JUDGMENT`. A validated link is *correctly bound* (claim,
claim hash, Phase 2I run, feature, feature hash, limitation on the same
hypothesis, no cross-claim or cross-run link, one judgment per pair); that does
not make the relation true. Its correctness is what the Gold eval measures.

## Inputs (all read-only, no new search)

* Phase 2C `ExtractedEvidence` — excerpts of content snapshots.
* Phase 2E `IndependenceGroup` — optional; an academic record with no group is
  `ACADEMIC_UNGROUPED` and is never independent corroboration (nothing inferred).
* Phase 2I run (must be `COMPLETED`) — claim inputs and hashes, feature
  inventories, `FeatureDifferentiation`, candidate profiles, texts, independence
  units, chronology. Texts are re-read from Phase 2G/2H through Phase 2I's
  `resolve_text` and hash-checked.
* Phase 2F scoring is deliberately **not** read: no score can reach a posture.

The inventory (`GapInventoryText`) is the no-new-evidence boundary: an excerpt
whose source text is not in it cannot exist, and it inherits that text's hash,
span, independence and quality unchanged (enforced by `GapAssessmentRun`).

Source quality is a deterministic verdict per text. Titles, repository metadata,
manifests and non-material-capacity texts are never limitation evidence;
retracted academic evidence is ineligible. A capability, condition or
counterevidence excerpt must come from an `ELIGIBLE` text; a limitation may cite
an ineligible one (so the outcome is visibly `BLOCKED_SOURCE_QUALITY`).

## Derived values

`derive_hypothesis_fields` is the single rule; the schema validator and the
pipeline builder both call it, so a stored value cannot drift.

* **existence** — `LIMITATION_SUPPORTED` / `LIMITATION_BLOCKED_SOURCE_QUALITY` / `NO_ELIGIBLE_LIMITATION`.
* **linkage** — `FULL` needs an `ADDRESSES_LIMITATION` link from a differentiating
  feature; `PARTIAL` only partially-addressing links; else `NONE_MATERIAL`.
* **condition materiality** — per limitation: `CONDITION_NOT_MATERIAL`,
  `CONDITION_REQUIRED_AND_BOUND`, `CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED`.
  Required only for dimensions the limitation is explicitly specific to
  (`SCOPE_RESTRICTION` always is). No condition is ever synthesized.
* **kind** — over eligible, materially linked limitations: `RESEARCH`,
  `ENGINEERING`, `HYBRID` (a research and a separate engineering limitation,
  different records, both linked; a source or excerpt may be shared) or
  `UNRESOLVED`. `proposition_key` (type + exact upstream spans, facet excluded)
  must be unique per hypothesis, so a relabelled copy cannot manufacture HYBRID.
* **corroboration** — from inherited units: one verified patent family is one
  unit; unresolved families, forks and mirrors contribute nothing; a Phase 2H
  correlation group counts once; ungrouped academic evidence is never
  independent. Never a probability.
* **scope** — `SINGLE_SOURCE_BOUNDED`, `MULTI_SOURCE_BOUNDED`,
  `CANDIDATE_SET_BOUNDED`, `REVIEW_SYNTHESIS_BOUNDED`, `INSUFFICIENT_SCOPE`.
  There is no field-wide value; every statement carries
  `BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED`.
* **posture** (per hypothesis, in order): blocked source quality →
  `BLOCKED_SOURCE_QUALITY`; no eligible limitation or no material link →
  `NOT_ESTABLISHED_WITHIN_BOUNDS`; material counterevidence →
  `COUNTEREVIDENCE_WEAKENS_GAP`; any missing component (existing capability,
  material condition, full linkage, validation requirement, resolved kind,
  complete counterevidence review) → `PARTIALLY_SUPPORTED`; else
  `SUPPORTED_WITHIN_BOUNDS`.

## Claim posture

`INSUFFICIENT_INPUT` — the claim could not be assessed (stated in
`insufficient_reasons`: no/incomplete Phase 2I, claim hash mismatch, no feature
inventory, no provider, failed or unaffordable model call, upstream mutated).
It is never reported as "no gap".

`DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP` — assessed; no hypothesis is supported,
partial, weakened or blocked; Phase 2I shows a differentiating feature. Covers
both "no eligible limitation" and "a limitation exists but nothing targets it";
`hypothesis_existence` and `hypothesis_linkage` stay on the claim record to
tell them apart.

`NOT_ESTABLISHED_WITHIN_BOUNDS` — the same, with no differentiating feature.

## Counterevidence

Same- or unknown-condition counterevidence weakens the gap. Different-condition
counterevidence does not defeat it, but narrows its safe scope, and that effect
is stored explicitly, separate from `GapScope` (which is the breadth of the
supporting evidence set). After-cutoff counterevidence affects the current
posture only (`WEAKENS_CURRENT_POSTURE_ONLY`).

`CounterevidenceScopeEffect` is derived from the verified condition relations:
`NO_SCOPE_NARROWING` (none, or same-condition only), `NARROWED_BY_DIFFERENT_CONDITION`,
or `CONDITION_RELATION_UNRESOLVED` (an unknown relation outranks the label; the
narrowing ids stay listed). `narrowing_counter_ids` are the exact records that
narrowed; `narrowing_current_only` is true when every narrowing record is after
the cutoff. Narrowing shows the limitation may hold only under some condition,
so a materially linked limitation with no anchored condition bound to it becomes
`CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED` and the hypothesis cannot stay
`SUPPORTED_WITHIN_BOUNDS`; no condition is ever invented for it. With the
condition bound it may stay supported, and the typed `GapBoundedStatement` names
the condition ids it is bounded to. Chronology stays in its own records.

`GapBoundedStatement` is the canonical Phase 2J conclusion for a hypothesis:
kind, scope, corroboration, the eligible linked limitation ids, the bound
condition ids, the scope effect and the narrowing ids, plus the pinned
`BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED` qualifier. It has no prose field;
any sentence shown to a user is composed from these values.

The review is shown every inventory text visible to the claim, within bounds.
`CounterevidenceCoverage` accounts for each text as examined or omitted
(bound reached, truncated, unreadable). An incomplete review, or one that
failed, can never reach `SUPPORTED_WITHIN_BOUNDS`.

## Chronology

Copied per excerpt from the Phase 2I profile into `GapChronologyNote`, apart from
gap support. `historical_publicity_inferred` and `legal_prior_art_established`
are `Literal[False]`.

## Model prose boundary

```
MODEL FREE PROSE   -> untrusted, non-canonical diagnostic material only
TYPED + VERIFIED   -> deterministic synthesis -> canonical Phase 2J conclusion
```

No model-written string reaches a canonical record. Excerpts and metric/baseline
text are persisted only after being re-found in, and sliced from, the source or
the claim; kind, linkage, scope, corroboration and posture are computed from
typed records; rationales, labels and the advisory `proposed_kind` are never
read as data (`proposed_kind` is recorded and ignored). Rejections persist a
digest and a length of any model text, never the text, and provider error or
refusal text is never persisted, so a leaked hidden prompt cannot reach a
checkpoint through any field, in any language.

Instruction-following is detected structurally, not by reading prose: a value no
enum holds, a label or text that was never shown, an unasked pair or an absence
basis is refused and raises `OFF_CONTRACT_OUTPUT`; a fabricated or ambiguous
anchor raises `FABRICATED_ANCHOR` / `AMBIGUOUS_ANCHOR`; a forbidden extra field
fails the schema (`extra="forbid"`) and the call is `MODEL_CALL_FAILED`. The
English lexical scan of rationales (hidden-prompt lines, forbidden conclusions)
is defense-in-depth only; the structural defences are language-independent.
A test pins every plain-string field on the canonical records to a stated reason.

## Prompt injection

Instruction-like source text is inert data and stays admissible when correctly
anchored. Model behaviour that follows it is refused: a reproduced hidden-prompt
line (never persisted — `[redacted: system prompt disclosure]`), a forbidden
conclusion in prose, an invented excerpt, ID or metric. Rationales are scanned
and never stored.

## Pipeline and graph

```
LOAD_GAP_ASSESSMENT_RUN       bind claims by hash, fingerprint upstream subruns
BUILD_GAP_EVIDENCE_INVENTORY  existing texts only
EXTRACT_GAP_CANDIDATES        call 1 + exact anchor verification (one boundary)
VERIFY_GAP_PROJECT_LINKAGE    call 2 over verified limitations x differentiating features
REVIEW_GAP_COUNTEREVIDENCE    call 3 + coverage
SYNTHESIZE_CLAIM_GAPS         build_hypothesis / claim posture, in Python
SYNTHESIZE_PROJECT_GAPS       descriptive counts, no score
FINALIZE_GAP_ASSESSMENT       re-check upstream fingerprints and claim hashes
```

Anchor verification and deterministic classification run inside the nodes that
receive untrusted output, so unverified model output never reaches a checkpoint
(a deliberate merge of the spec's separate `gap_anchor_verify` /
`gap_deterministic_classification` nodes). Stages are idempotent
(`stage_markers`), ids are deterministic and run-bound, inventory selection is
ordered by content first, and a replay makes no model call.

`FORBIDDEN_NODES` lists `GAP`, `METHODOLOGY`, `EXPERIMENT_REVIEW`, `NOVELTY`,
`SCORING`, `TRUST_GATE`, `RED_TEAM` and every discovery node.

## Deferred

Methodology adequacy, experiment and result validity, mapping a gap onto an
official Mawhiba/Ibdaa criterion, `ProjectState.gap`, and any score or
readiness: Phase 3A/3B and later reviewed phases.

## Known limits

* Linkage relation, limitation facet and condition match are model judgments,
  bounded by exact anchors; semantic correctness is measured by the Gold eval.
* The lexical scan of model prose is English-only (the language policy keeps
  Arabic as data). It is defense-in-depth; the structural defences above do not
  depend on it.
* Whether two limitation records over the same span (different admissible types)
  are really two propositions is not provable in code; only a duplicated
  proposition key is refused.

## Gold requirements recorded before Gold

* **Same-span HYBRID inflation.** Same exact span, two different admissible
  limitation types, a model that reads one proposition as two, attempted HYBRID.
  Gold must distinguish a genuinely dual-proposition passage (one passage that
  states an open question and, separately, a measured shortfall; HYBRID may be
  derived) from a single proposition mislabeled twice (HYBRID must not be
  manufactured), and must report the second as a measured model-judgment rate,
  not assume the proposition-key rule closes it.
* Different-condition counterevidence with and without the condition bound,
  after-cutoff narrowing, and unknown-relation counterevidence.
* Arabic and mixed-language instruction-like source text as inert evidence, and
  off-contract typed output in each language.

## Gold eval

`evals/research_engineering_gap/v1/cases.jsonl` (schema in `schema.md`, regenerated by
`scripts/generate_phase2j_gold.py`). Run `./.venv/Scripts/python.exe -m src.evals.research_engineering_gap.cli`.
Each case is driven through the real Phase 2E-2I graphs and the real Phase 2J graph with a scripted
untrusted model and no network. The scorer re-derives every gate from the serialized run and the upstream
records, never through the Phase 2J validators. Model-judgment families (semantic linkage, same-span
proposition judgment, semantic admissibility, counterevidence recall) are reported honestly; seeded wrong
judgments are in the dataset on purpose and are not required to be perfect.
