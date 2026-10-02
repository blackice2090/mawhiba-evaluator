# Phase 2I — Novelty & Differentiation Assessment

Phase 2I compares the student's existing technical claims against the bounded,
provenance-preserving prior-art candidates found by Phase 2G (patents) and
Phase 2H (products, open source), and describes each claim's **technical overlap
and differentiation posture relative to that bounded candidate set**.

It does **not** determine legal novelty, patentability, infringement, freedom to
operate, copying/plagiarism, an official Mawhiba/Ibdaa score, or project
quality. The governing distinction is

> Technical comparison ≠ legal novelty conclusion.

Decision record: `docs/adr/ADR-020-technical-overlap-is-a-descriptive-evidence-posture.md`.

## 1. Architecture

```
Existing claims + Phase 2E component inventory
  + Phase 2G patent candidates + Phase 2H product / open-source candidates
 -> ComparisonFeatureInventory      exact claim anchors; deterministic COMBINATION feature
 -> CandidateComparisonProfile      eligibility, disclosure capacity, independence unit, chronology
 -> ClaimCandidateComparison        untrusted model relations -> deterministic anchor verification
 -> ClaimDifferentiationSynthesis   posture decided in Python (never by the model)
 -> ProjectDifferentiationSummary   descriptive counts only
 -> STOP
```

Graph: `build_phase2i_novelty_differentiation_graph()` (`src/graph/phase2i_graph.py`),
nodes in `src/graph/novelty_nodes.py`. It consumes an open `ResearchRun` whose
Phase 2G/2H subruns are **finished**, performs no new search, and leaves the run
non-terminal. `NOVELTY`, `CLOSEST_PRIOR_ART`, `SCORING`, `TRUST_GATE`, `RED_TEAM`
and every Phase 2G/2H discovery node are in `FORBIDDEN_NODES`.

Output lives on `ResearchRun.novelty_differentiation` (`NoveltyDifferentiationRun`),
never in `ProjectState`. It cannot hold a claim status, confidence, evidence
reference, score, trust verdict, novelty verdict or legal conclusion: no such
field exists on any Phase 2I type, and a test asserts it.

Developer file map: `src/schemas/novelty_differentiation.py` (contracts),
`src/research/novelty/{features,candidates,anchoring,comparison,synthesis,pipeline,dto}.py`,
`src/llm/prompts.py` (two prompts), `src/evals/novelty_differentiation/` (Gold eval).

## 2. Boundaries enforced by the types

```
Candidate discovered ≠ feature disclosed        Same component ≠ same combination
Feature disclosed ≠ entire claim disclosed      All components found ≠ claimed combination found
High overlap ≠ same invention                   Material overlap ≠ legal anticipation
No material overlap found ≠ novel               No candidate found ≠ novel
Bounded search ≠ exhaustive search              Technical overlap ratio ≠ novelty probability
```

## 3. Input eligibility and the feature inventory

A claim is eligible when it exists canonically with a stable id and material text.
Claims are bound by the sha256 of their exact text; nothing is repaired.

The model proposes typed features (COMPONENT, FUNCTION, MECHANISM, RELATIONSHIP,
SEQUENCE, CONSTRAINT, OTHER_TECHNICAL_FEATURE) with **verbatim** claim text. Code
locates every anchor (`src/research/novelty/anchoring.py`); model offsets are never
trusted. Rejected: text not in the claim, ambiguous repeated text, invalid
offsets/occurrence, immaterial text, duplicates, unknown types, and `COMBINATION`.

* **Combination invariant.** `COMBINATION` is reserved for code. With two or more
  elements, a deterministic whole-claim `COMBINATION` feature is always added, so
  all components found can never stand in for the combination found.
* **Coverage.** Material claim text no accepted feature covers becomes an
  `UNCOVERED_CLAIM_REMAINDER` feature (in the denominator) and the inventory is
  `INCOMPLETE`.
* **Fallback.** When the Phase 2E inventory is missing / incomplete / hash-mismatched,
  there is no model provider, or extraction fails, the claim becomes
  `FULL_CLAIM_ONLY`: one whole-claim feature, the reason recorded, and
  differentiation withheld.

## 4. Candidate profiles and disclosure policy

Each candidate is profiled from its own phase records: eligibility
(`ELIGIBLE_FOR_TECHNICAL_COMPARISON`, `LIMITED_TEXT_COMPARISON`,
`METADATA_ONLY_NOT_COMPARABLE`, `CONTENT_UNAVAILABLE`, `BLOCKED_SOURCE_QUALITY`,
`INVALID_CANDIDATE_REFERENCE`), a structured source-quality profile (no score), the
texts it offers, an independence unit and chronology. Search snippets and provider
rank are never comparable text.

Each text has a **disclosure capacity**: `MATERIAL` (can support `DISCLOSED`),
`LIMITED` (at most `PARTIALLY_DISCLOSED`), `NON_MATERIAL` (at most
`RELATED_CONTEXT`). Capacity depends on the source **and the feature type**:

| Source | Capacity |
|---|---|
| Patent claims, description | MATERIAL |
| Patent abstract | LIMITED (abstract scope only) |
| Patent title | NON_MATERIAL |
| Product first-party **documentation** | MATERIAL |
| Product first-party page / press release, marketplace, review, directory, unknown role | LIMITED |
| Product page title | NON_MATERIAL |
| OSS README, code-search fragment | LIMITED (documentation / fragment is not implementation proof) |
| OSS **full-file manifest** | MATERIAL for COMPONENT and CONSTRAINT only; LIMITED for OTHER; NON_MATERIAL for mechanism, function, sequence, relationship and combination |
| OSS repository description, topics, release metadata | NON_MATERIAL |
| Any truncated or bounded text | cannot ground a negative |

A manifest listing `OpenCV` can disclose the **component** "uses OpenCV"; it can
never establish a mechanism or the claimed combination. Phase 2H captures no
source-code file kind, so an open-source candidate can currently reach at most a
partial-claim or component-only overlap.

## 5. Candidate evidence anchors and the comparison

One model call per (claim, candidate). The model sees short labels (F1…, T1…) and
returns a per-feature relation (`DISCLOSED`, `PARTIALLY_DISCLOSED`,
`RELATED_CONTEXT`, `NOT_DISCLOSED`, `INSUFFICIENT_SOURCE_TEXT`, `NOT_COMPARABLE`)
with quoted excerpts. It is never asked about novelty and returns no overall verdict.

Deterministic verification (`src/research/novelty/comparison.py`):

* every excerpt is located in the exact text the model was shown, under the label
  it named. A repeated excerpt binds only through validated offsets or a validated
  occurrence index; otherwise it is rejected as ambiguous. **No first-occurrence
  guessing.** The anchor stores the slice, offsets, occurrence index/count and how
  it was resolved, the content hash and text digest, language, truncation and the
  capacity;
* fabricated excerpts, unknown text labels, excerpts belonging to another candidate,
  and claim text used as evidence are rejected;
* a disclosure with no verified anchor becomes `NOT_COMPARABLE` (never a negative);
  verification can only lower a relation, never raise it;
* `NOT_DISCLOSED` is accepted only when **complete MATERIAL text for that feature
  type** was compared; otherwise it becomes `INSUFFICIENT_SOURCE_TEXT`;
* a model response that discloses the system prompt is refused (the feature becomes
  `NOT_COMPARABLE`) and the leaked text is **not persisted** (redacted in the ledger).

Candidate text that merely *reads like* an instruction ("ignore previous
instructions") is inert data and remains admissible when exactly anchored. What is
refused is model **behaviour**, not source wording.

The single-candidate **full-claim relation** is derived in Python: `FULL` only when
every feature, the combination included, is `DISCLOSED` by that one candidate;
`PARTIAL` when a relationship-bearing feature overlaps; `COMPONENT_ONLY` for
standalone elements (a mechanism or function overlap is labelled component-only, a
documented simplification); then `CONTEXT_ONLY`, `NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT`,
`INSUFFICIENT_SOURCE_TEXT`.

`COMPONENT_ONLY_OVERLAP` is a relation-taxonomy label, not a `FeatureType`: one or
more individual claim features are materially disclosed, no relationship-bearing
feature (relationship, sequence, constraint) overlaps, and the claim-level
combination is not established. A disclosed component, function, mechanism or other
feature contributes to it; matching every component while the `COMBINATION` feature
is not disclosed is still component-only. Overlap on a relationship-bearing feature
is `PARTIAL_CLAIM_TECHNICAL_OVERLAP`. Chronology qualification applies to exactly
`FULL`, `PARTIAL` and `COMPONENT_ONLY`; `CONTEXT_ONLY`, `NO_MATERIAL_OVERLAP_IN_COMPARED_TEXT`
and `INSUFFICIENT_SOURCE_TEXT` are never technical overlap
(`tests/test_phase2i_relation_semantics.py`).

## 6. Candidate independence

Independence is taken from the existing grouping, separately per type, never summed
across types.

* **Patent.** `VERIFIED_FAMILY` → `PATENT_FAMILY`; `SINGLETON_FAMILY` (only when
  Phase 2G established it) → `PATENT_SINGLETON_FAMILY`; every other family status
  (unavailable, failed, not requested) → `PATENT_INDEPENDENCE_UNRESOLVED`, **never
  independent**. Such a publication is still compared. `publication_count ≠ family
  independence status`: one visible publication in a verified family is not a
  singleton, and two unresolved publications are zero independent units.
* **Product.** Every `ProductEntity` stays its own unit (`PRODUCT_STRONG_ENTITY` only
  for a Phase 2H `VERIFIED_STRONG_IDENTITY`, else `PRODUCT_UNRESOLVED_ENTITY`).
  Entities linked by a probable or identical-content link share a namespaced
  **unresolved correlation group** that caps their joint corroboration at one. It
  never merges entities, never asserts they are one product, and never mutates
  Phase 2H identity.
* **Open source.** The unit key is the repository network. A candidate is independent
  only when it is itself the independent root; forks, mirrors and template
  derivatives share their network key but never count as independent roots.

## 7. Chronology

Technical comparison is separate from chronology: every candidate is compared
whether before, on, after, unknown or without a cutoff. The chronology statement is
**per type** and never one generic flag:

* patent: "technical overlap found in a patent publication dated before cutoff";
* product: "the overlapping artifact carries a source-reported date before cutoff" —
  not historical availability;
* open source: "the overlapping repository carries a provider date before cutoff" —
  `created_at`, release and commit dates never prove public visibility.

`product_historical_availability_proven`, `oss_historical_public_visibility_proven`
and `legal_prior_art_established` are pinned to false. Post-cutoff and
unknown-date overlaps never support a before-cutoff statement.

## 8. Boundedness

`NoveltyComparisonBounds` limits candidates per claim, groups per type, texts and
characters per comparison, features per claim, model comparisons and retries.
Selection is deterministic and type-diverse. Nothing is dropped silently: each
available candidate is compared, omitted by limit, blocked, not comparable, failed
or not executed, exactly once. Coverage is `COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS`,
`PARTIAL_COMPARISON_LIMIT`, `PARTIAL_SOURCE_UNAVAILABLE`, `PARTIAL_ERROR` or
`NOT_EXECUTED`; partial can never read complete. One failed comparison never
discards another.

## 9. Deterministic synthesis (`TECHNICAL-OVERLAP-SYNTHESIS-POLICY-V1`)

Rules apply in order: all linked candidates blocked → `BLOCKED_SOURCE_QUALITY`; one
candidate discloses the full combination → `MATERIAL_TECHNICAL_OVERLAP_FOUND`; no
verified comparison → `INSUFFICIENT_COMPARISON_EVIDENCE`; some feature
(partially) disclosed → `MIXED_OVERLAP_AND_DIFFERENTIATION` when differentiation is
reportable and a feature is not found, else `PARTIAL_TECHNICAL_OVERLAP_ONLY`;
nothing disclosed → `NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS` only when
differentiation is reportable and every feature is not found, else
`INSUFFICIENT_COMPARISON_EVIDENCE`.

Differentiation is reportable only with a component-level, complete inventory,
complete comparison coverage, and complete MATERIAL text for every feature type in
the claim in every verified comparison. A not-found feature is
`NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT`, qualified "relative to the compared bounded
candidate set"; it is never "unique", "novel" or "first". `NOVEL`, `NOT_NOVEL`,
`ANTICIPATED`, `INVALID`, `PATENTABLE` and `UNPATENTABLE` do not exist.

Every posture carries its limitations (bounded search, bounded comparison, no legal
novelty conclusion, technical overlap is not anticipation, no match is not proof of
novelty, no patentability/infringement/FTO/copying conclusion, not a score). The
project summary carries all twelve required limitations and reports only counts and
distributions: no percentage, score, pass/fail or ranking.

## 10. Idempotency, isolation, immutability

Every id is `uuid5` over stable parts. Each stage records a marker, so a replayed
node is a no-op; a finished run is never reopened; one claim/candidate pair is
compared once. A Phase 2I run is bound to the patent/product/OSS/sufficiency runs
it consumed, and any foreign claim, candidate, family, entity, network, snapshot or
comparison id is refused. Phase 2C–2H artifacts and `ProjectState` are byte-equivalent
before and after, which the eval checks on populated worlds.

## 11. Gold eval

`evals/novelty_differentiation/v1/cases.jsonl` (schema in `schema.md`, regenerated by
`scripts/generate_phase2i_gold.py`): 301 cases (en 102, ar 100, mixed 99), 145
categories. Each case runs the real 2E → 2F → 2G → 2H → 2I graphs against scripted
providers and a scripted structured model that can be made to misbehave.

```bash
./.venv/Scripts/python.exe -m src.evals.novelty_differentiation.cli
```

* 23 quality families exactly 1.0 plus per-language contract accuracy;
* 78 release-blocking gates at zero, each with a real non-zero denominator;
* 28 distinct negative controls, each caught by a gate or by the contract.

The scorer is independent of the code it scores: gates are re-derived from the
serialized run (a plain JSON dict) and the upstream records, never through the
Phase 2I validators. Quality families may overlap (one relation feeds relation-kind
and source-disclosure accuracy); gate denominators are gate-specific and exact, and
are tested to be unaffected by that overlap, by candidate order, or by any floor.

## 12. Limitations

Bounded search and bounded comparison are not exhaustive; no found overlap does not
prove novelty; technical overlap is not legal anticipation; source text may be
incomplete; product historical availability and open-source historical visibility
may be unknown; patent-family grouping is not legal equivalence; product identity may
be unresolved; forks may materially diverge; and there is no patentability,
infringement, FTO, copying or project/official scoring assessment.
