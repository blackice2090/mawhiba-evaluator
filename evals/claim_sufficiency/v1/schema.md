# Claim Sufficiency Gold Cases — v1 schema

One JSON object per line in `cases.jsonl`. Every field is reviewable as plain
text, which is the point: a reviewer must be able to read a case and decide
whether its expectation is right without running anything.

Phase 2E makes **no model call**, so there is no scripted model-output block
here and no possibly-misbehaving classifier to defend against. The adversarial
surface is the *input shape*: the same DOI under two source records, three
providers observing one paper, five excerpts from one abstract, a retracted
supporting paper, an alignment whose evidence is not in the run, a Phase 2D run
that never finished. Those are the shapes that would silently inflate
corroboration or assert sufficiency over evidence nobody examined.

## Claim-component completeness (Phase 2E.1)

Under `COMPONENT-PARTITION-STRATEGY-V1` the material component set is a covering
partition of the claim's own text, so a case's *claim text* and its *anchor
texts* together determine the denominator (ADR-016). Two consequences matter
when reading or writing a case:

- An anchor naming the whole proposition yields one material component, so a
  case about full sufficiency anchors the whole claim.
- A sub-phrase anchor leaves the rest of the claim as an
  `UNANCHORED_CLAIM_REMAINDER` component with `NO_EVIDENCE`, so the claim cannot
  be `SUFFICIENT_SUPPORT`. The compound claims here use a comma between
  components precisely so that both anchors together cover every material
  character and full coverage stays reachable.
- The partition cuts only at anchor boundaries, so two adjacent unexamined
  stretches merge into one remainder component. Coarser, never smaller.

**Expectations are authored from the described input alone** — what
`SUFFICIENCY-POLICY-V1` must conclude given these claims, these sources and
these relations. Never by running the code and blessing its answer.

All content is synthetic. No real paper, DOI, author, dataset or student
identity appears anywhere. Arabic appears only as **data**, in claim text and
excerpt value positions, and is never translated.

## Case

| Field | Type | Meaning |
|---|---|---|
| `case_id` | `CS-\d{3,}` | Unique. |
| `language` | `en` \| `ar` \| `mixed` | Drives the per-language metrics. |
| `categories` | `[str]`, ≥1 | Adversarial/behaviour tags. The required 48 are asserted present by `tests/test_phase2e_claim_sufficiency.py`. |
| `claims` | `[GoldClaim]`, ≥1 | The existing claims. |
| `sources` | `[GoldSource]` | Phase 2B logical sources. |
| `evidence` | `[GoldEvidence]` | Phase 2C verified evidence. |
| `alignments` | `[GoldAlignment]` | Phase 2D verified relations. |
| `alignment_status` | `ClaimAlignmentStatus` | Default `COMPLETED`. Anything else drives a not-ready path. |
| `direct_mode` | `bool` | Call the deterministic pipeline directly instead of the graph, for shapes a validated run record cannot hold. |
| `resume_after_node` | `NodeId` \| null | Interrupt before this node and resume from the checkpoint. |
| `rerun` | `bool` | Re-invoke the finished graph, and run a second independent pass. |
| `expected` | object | See below. |
| `notes` | `str` | Why this case exists, in prose. |

### GoldClaim

`claim_id` (`C-\d{3,}`), `claim` (the text), `claim_type` (a `ClaimType` name).

### GoldSource

| Field | Meaning |
|---|---|
| `key` | Stable local handle, e.g. `s1`. |
| `title` | Never participates in identity (ADR-009). Two sources may share a title. |
| `doi`, `pmid`, `openalex_id`, `semantic_scholar_id`, `arxiv_id`, `canonical_url` | At least one required. Canonical identity is built from the strongest present. **Two source entries sharing an identifier are deliberately the same underlying work seen twice.** |
| `source_type` | `AcademicSourceType` name. `PREPRINT` is the only value implying not-peer-reviewed. |
| `is_retracted` | `true` / `false` / omitted. Omitted means `UNKNOWN`, which is not `NOT_RETRACTED`. |
| `publication_year` | Omit (`null`) to exercise `PUBLICATION_YEAR_UNKNOWN`. |
| `providers` | Which providers returned this one work. More providers is never more studies. |
| `orphan` | Omit this source from the run, so its evidence has no resolvable canonical identity → `DISQUALIFIED_UNTRACEABLE`. |

### GoldEvidence

| Field | Meaning |
|---|---|
| `key` | Stable local handle, e.g. `e1`. |
| `source` | A `GoldSource` key. Several evidence entries may share one. |
| `excerpt` | The verbatim text. Each excerpt is its own whole snapshot. |
| `evidence_type` | `ExtractedEvidenceType` name. |
| `content_kind` | `ABSTRACT` (default), `PARTIAL_TEXT` or `FULL_TEXT`. Drives the scope limitation and ceiling. |
| `is_retracted` | Overrides the source's flag for this item. |
| `missing_from_run` | Build the evidence id but omit the item, so an alignment references evidence the run does not hold. |

### GoldAlignment

| Field | Meaning |
|---|---|
| `claim_id` | A claim in this case. |
| `evidence` | A `GoldEvidence` key. |
| `relation` | An `AlignmentRelation` name, used as given. |
| `components` | `[{text, judgment}]`. **`text` must occur verbatim in the claim**; offsets are derived by code, so a case cannot encode an anchor that does not exist. Component judgments must satisfy Phase 2D's own relation-consistency rule. |
| `foreign_run` | Build the alignment under a different research run id. Requires `direct_mode`, because a run record rightly refuses it. |
| `hash_mismatch` | Record a content hash that does not match the evidence, so the alignment was verified against different bytes. |
| `fabricated_anchor` | Claim text that does **not** occur in the claim, recorded as a component anchor at offset 0. Phase 2D could not produce this; Phase 2E.1 must refuse it rather than assume upstream verification held (ADR-016). |

One `(claim_id, evidence)` pair may carry at most one alignment.

## Expectation

Every field is optional; a field left out is simply not asserted, so a case
asserts exactly what it was written to assert.

| Field | Meaning |
|---|---|
| `status` | Expected `ClaimSufficiencyStatus`. |
| `outcomes` | `claim_id -> SufficiencyOutcome`. |
| `independence_groups` | Expected group count for the run. |
| `supporting_groups` / `contradicting_groups` | `claim_id -> count of independent groups`. **Group counts, never item counts.** |
| `component_coverage` | `claim_id -> [ComponentCoverage]`, in component order (sorted by anchor span). |
| `contributions` | The sorted set of `EvidenceContributionClass` values across all profiles. |
| `reason_codes` | `claim_id -> codes that must all be present` (subset check). |
| `forbidden_reason_codes` | `claim_id -> codes that must be absent`. This is how a case asserts that e.g. `MULTIPLE_INDEPENDENT_SUPPORTING_SOURCES` did *not* fire. |
| `blockers` | `claim_id -> exact sorted SufficiencyBlocker list`. |
| `unknown_dimensions` / `limitations` | `claim_id -> values that must be present`. |
| `content_scope_ceiling` | `claim_id -> scope value, or the string `NONE`` when nothing contributed. |
| `duplicate_evidence_collapsed` | Expected collapse count: evidence items beyond the first in their group. |
| `assessments_total` | Expected number of assessments. |
| `inventory_completeness` | `claim_id -> COMPLETE` \| `INCOMPLETE` \| `UNKNOWN`. `UNKNOWN` is never interchangeable with `COMPLETE`. |
| `unexamined_components` | `claim_id -> count of material claim components no alignment anchor reached`. Zero is an assertion, not a default. |
| `component_origins` | `claim_id -> [ComponentOrigin]`, in component order. |

## Coverage minimums (asserted by tests)

- ≥ 120 cases total
- ≥ 24 Arabic, ≥ 16 mixed
- every `SufficiencyOutcome` value covered
- each of the 48 required adversarial/behaviour categories present
- each of the 20 required Phase 2E.1 claim-component-completeness categories
  present

## What the eval proves, and what it does not

It proves policy behaviour, independence handling, duplicate control,
sufficiency-contract correctness, provenance safety, immutability of
`ProjectState` / Phase 2C / Phase 2D, deterministic aggregation, versioning and
language/data handling.

It does **not** prove scientific validity. A deterministic policy test says the
policy was applied correctly to the given relations; it says nothing about
whether those relations are scientifically right, which Phase 2D already
declines to claim (ADR-014).
