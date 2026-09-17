# Phase 2D: Claim-Evidence Alignment

## Purpose

Phase 2D answers one narrow question: *what semantic relationship does this
specific verified Phase 2C evidence item have to this specific existing
claim?* It does not answer whether the claim is sufficiently proven -- that is
a later phase's job. See ADR-014 for the full architectural rationale.

Core invariants preserved throughout:

```
Evidence exists           != Evidence supports the claim
Structured                != True
Sourced                    != Verified
Verified Source            != Evidence
Evidence                    != Supported Claim
Alignment                    != Claim Verification
```

## Architecture

```
Verified Source -> SourceContentSnapshot -> Verified ExtractedEvidence
                                                      |
Existing ClaimRecord ---------------------------------+
                                                      |
                                     Claim-Evidence Alignment (Phase 2D)
                                                      |
                                                    STOP
```

`ClaimEvidenceAlignmentRun` lives on `ResearchRun.claim_evidence_alignment`
(`src/schemas/research.py`), never in `ProjectState`. This follows the exact
ownership pattern Phase 2C established for `EvidenceExtractionRun`: a
canonical `EvidenceRecord` must resolve inside `ProjectState.sources`, and
Phase 2D's evidence items still live on the research run (ADR-010), so an
alignment referencing them must live alongside them. `ProjectState` -- claims,
their status, confidence, `evidence_ids`, `counter_evidence_ids`, scores, the
trust gate, `evaluation_status` -- is read-only input to this phase and is
proven byte-identical before and after every graph run
(`tests/test_claim_alignment_graph.py::TestImmutability`).

## Relationship Taxonomy (`AlignmentRelation`)

| Relation | Semantics |
|---|---|
| `SUPPORTS` | The evidence directly supports the claim, with no material contradiction. |
| `CONTRADICTS` | The evidence directly conflicts with the claim. |
| `PARTIALLY_SUPPORTS` | Supports part of a compound claim; a remaining component is unresolved or out of scope. No contradicted component. |
| `PARTIALLY_CONTRADICTS` | Contradicts part of a compound claim; a remaining component is unresolved or out of scope. No supported component. |
| `MIXED` | Supports at least one component and contradicts at least one other. |
| `CONTEXT_ONLY` | Related background; does not directly establish or refute the claim. |
| `INSUFFICIENT` | Relevant, but too limited in scope/detail/comparator/population/strength to classify as supported or contradicted. |
| `NOT_RELEVANT` | No material semantic relationship to the claim. |

These classes are kept distinct by construction: `relation_is_consistent()`
(`src/schemas/claim_alignment.py`) is the single deterministic mapping from a
set of component judgments to the one relation each combination allows, and
`ClaimEvidenceAlignment`'s own validator calls it, so an inconsistent pair can
never be constructed, let alone stored.

## Claim Component Anchors

A compound claim's components are individually judged. Each
`ClaimComponentAnchor` carries `claim_id`, `start`, `end`, `text`, and the
verifier's only rule is: `claim.claim[start:end] == text`, character for
character. No punctuation, digit, unit, negation, mathematical symbol or
whitespace normalization is applied anywhere in the anchor path
(`src/research/alignment/verification.py::resolve_anchor`). A model-proposed
`claimed_start` is used only to disambiguate identical repeated substrings; it
never defines the span. A claimed anchor that is not a literal substring of
the claim is rejected as `FABRICATED_ANCHOR` and the whole candidate is
discarded -- no partial credit.

Pair-level/component-level consistency table (section 7 of the phase spec):

| Components | Relation |
|---|---|
| All `SUPPORTS` | `SUPPORTS` |
| Some `SUPPORTS`, rest `UNRESOLVED`/`CONTEXTUAL`, none `CONTRADICTS` | `PARTIALLY_SUPPORTS` |
| All `CONTRADICTS` | `CONTRADICTS` |
| Some `CONTRADICTS`, rest `UNRESOLVED`/`CONTEXTUAL`, none `SUPPORTS` | `PARTIALLY_CONTRADICTS` |
| At least one `SUPPORTS` and one `CONTRADICTS` | `MIXED` |
| All `CONTEXTUAL` | `CONTEXT_ONLY` |
| All `UNRESOLVED` | `INSUFFICIENT` |
| No components | `NOT_RELEVANT` |

Any other combination (for example, a mix of `CONTEXTUAL` and `UNRESOLVED`
with no support or contradiction) is not a legal state for any relation and is
rejected as `STRUCTURALLY_INCONSISTENT`.

## Deterministic Verification

`src/research/alignment/pipeline.py::verify_candidate` proves, in order:

1. The claim id and evidence id both resolve inside the current project and
   research run (`UNKNOWN_CLAIM`, `UNKNOWN_EVIDENCE`).
2. The evidence belongs to the current research run
   (`EVIDENCE_OUTSIDE_RUN`) and carries valid Phase 2C provenance --
   observations, extractor/verifier version, an extractable content kind
   (`EVIDENCE_PROVENANCE_INVALID`, `METADATA_ONLY_EVIDENCE`).
3. Every proposed component anchor exists verbatim in the claim
   (`FABRICATED_ANCHOR`), and carries at least one reason code.
4. The relation is consistent with its components
   (`STRUCTURALLY_INCONSISTENT`).
5. The claim/evidence pair has not already been decided with an incompatible
   relation (`DUPLICATE_INCOMPATIBLE_PAIR`); an identical re-derivation is a
   silent no-op, not an error.

**What verification proves**: the candidate is structurally and
provenance-valid. **What it does not prove**: that the underlying scientific
relationship is correct. No deterministic check can validate a semantic
judgement; that is exactly why Phase 2D never turns a verified alignment into
a claim verdict (ADR-014).

## Pair Generation

`src/research/alignment/pairing.py::generate_pairs` builds every
`(claim, accepted evidence item)` pair, in stable claim-major order, with no
title-only or embedding-only preselection -- completeness over heuristic
ranking, so contradictory evidence is never silently filtered out before a
model even sees it.

A hard safety limit (`ResearchSettings.alignment.max_pairs_per_run`, default
500) guards against pathological Cartesian growth. Hitting it never truncates
silently: the run status becomes `BLOCKED_PAIR_LIMIT_EXCEEDED`, the required
pair count is recorded, and zero alignments are produced. There is no partial,
best-effort pass under the limit.

## Prompt-Injection Resistance

The claim text and the evidence excerpt are both untrusted data as far as the
classifier prompt is concerned (`ALIGNMENT_INPUT_BOUNDARY` in
`src/llm/prompts.py`): the model is explicitly told that either may contain
embedded instructions and that such instructions must never be followed, and
that it has no authority over claim status, confidence, scores or workflow
state. Because the schema itself has no field for any of those things, even a
successful injection attempt has nothing to write to --
`tests/test_claim_alignment_graph.py::TestPromptInjectionResistance` and the
Gold dataset's `prompt_injection_in_claim` / `prompt_injection_in_evidence`
categories exercise this with injected text that a scripted "misbehaving"
classifier still must resolve through the same anchor and consistency rules.

## No-Input Behavior

| Condition | Result |
|---|---|
| No existing claims | `ClaimAlignmentStatus.NO_ALIGNABLE_CLAIMS`, no `ProjectState` mutation |
| No accepted Phase 2C evidence | `ClaimAlignmentStatus.NO_ALIGNABLE_EVIDENCE` |
| Evidence extraction not yet terminal | `ClaimAlignmentStatus.NOT_READY` -- alignment never proceeds as though unverified evidence were trusted |
| Required pairs exceed the safety limit | `ClaimAlignmentStatus.BLOCKED_PAIR_LIMIT_EXCEEDED` |

None of these conditions writes `ProjectState`.

## Idempotency

`LOAD_ALIGNMENT_RUN` checks whether `ResearchRun.claim_evidence_alignment` is
already terminal before doing anything else; if so, it is never reopened, so
a re-invocation on an already-finished run cannot reprocess candidates or
duplicate alignments (`tests/test_claim_alignment_graph.py::TestCheckpointIdempotency`).
Independently, `verify_candidate` treats an identical repeated candidate for
the same claim/evidence pair as a no-op rather than a second record, and an
*incompatible* repeat is rejected rather than silently overwriting the first.

## Graph

`build_phase2d_claim_alignment_graph()` (`src/graph/phase2d_graph.py`):

```
START
  -> LOAD_ALIGNMENT_RUN --------(no active research run)-----------> END
  -> VALIDATE_ALIGNMENT_INPUT
  -> GENERATE_ALIGNMENT_PAIRS
  -> CLASSIFY_ALIGNMENT_CANDIDATES   (the one model call per pair. UNTRUSTED)
  -> VERIFY_ALIGNMENT_CANDIDATES     (deterministic trust boundary)
  -> UPDATE_ALIGNMENT_COVERAGE
  -> FINALIZE_CLAIM_EVIDENCE_ALIGNMENT
  -> END
```

Every node past `LOAD_ALIGNMENT_RUN` guards on `alignment.is_terminal`, so a
run that stopped early (no claims, no evidence, not ready, or blocked) makes
every downstream node a no-op rather than requiring special routing.
`FORBIDDEN_NODES` in `phase2d_graph.py` lists `NOVELTY`, `GAP`, `SCORING`,
`TRUST_GATE`, `FINAL_VERIFIER`, `CLOSEST_PRIOR_ART`, `RED_TEAM`,
`REPORT_GENERATOR` and `CONTRADICTION_DETECTION`; a test asserts none of them
is wired into `PHASE_2D_NODE_SEQUENCE`.

The research run itself stays open on completion, exactly as Phase 2C leaves
it, so a later branch can still write to it.

## Offline Gold Evaluation

`evals/claim_evidence_alignment/v1/cases.jsonl` -- 96 Gold cases across 32
adversarial categories (3 cases each): direct support/contradiction, compound
partial support/contradiction, mixed, unrelated/contextual/insufficient
evidence, numeric/percentage/threshold/inequality/unit mismatch, negation,
comparator/metric/population/deployment-context mismatch, causal overreach,
correlation-vs-causation, hedging/modal-strength mismatch, source
limitation-vs-result, prompt injection (in the claim and in the evidence),
Arabic scientific text, mixed Arabic/English terminology, retracted/preprint
provenance preservation, fabricated claim anchors, invalid references,
cross-run reference attempts, multiple evidence items aligned differently to
one claim, and one evidence item aligned differently to two claims.

Languages: 59 English, 20 Arabic, 17 mixed (`>= 20` Arabic and `>= 12` mixed
required; both exceeded). All content is synthetic; no real paper, dataset,
or student identity appears anywhere. Generated reproducibly by
`scripts/generate_phase2d_gold.py`.

Each case is driven through the **real Phase 2D graph** (or, for
`invalid_references` / `cross_run_reference_attempts`, directly through the
real `verify_candidate` with a deliberately invalid candidate, since
deterministic pairing can never itself produce an invalid or cross-run
reference). The scorer (`src/evals/claim_alignment/runner.py`) re-derives
every judgement independently: it re-checks every accepted claim anchor
against the claim text from scratch, re-evaluates taxonomy consistency with
the same pure function the schema uses, diffs the full project state before
and after, and re-verifies the candidate set a second time to check
idempotency -- none of this trusts the verifier it is scoring.

### Eval Honesty

The offline suite uses the deterministic fake structured-model provider only.
It verifies alignment contract behaviour, taxonomy handling, the deterministic
verifier, provenance integrity, pipeline handling and safety gates -- **not**
the scientific accuracy of a live model's semantic judgement. No live
`RUN_PHASE2D_LIVE=1` eval exists in this phase; none is reported as executed.
A scripted "misbehaving" classifier response is never presented as proof that
a real model would classify a real claim/evidence pair correctly.

## Quality Metrics

`src/evals/claim_alignment/metrics.py` (`REQUIRED_PERFECT_METRICS`, must equal
1.0): `valid_alignment_reference_accuracy`, `exact_claim_anchor_accuracy`,
`relationship_taxonomy_contract_accuracy`, `component_pair_consistency_accuracy`,
`alignment_traceability`. Also reported, not required perfect:
`deterministic_pair_coverage`, `checkpoint_idempotency_accuracy`,
`rejected_candidate_accuracy`, `relation_accuracy`. Every metric with no
denominator reports `None` ("not measured"), never zero.

## Release-Blocking Safety Gates

All twenty gates in `RELEASE_BLOCKING_ALIGNMENT_METRICS` must be zero:
`ProjectState`/claim/claim-status/claim-confidence/claim-evidence-reference/
claim-counter-evidence-reference/score/trust-gate/evaluation-status/
`ExtractedEvidence` mutation; automatic claim-support mutation; invalid
claim-reference acceptance; invalid evidence-reference acceptance; unverified
evidence alignment acceptance; cross-run evidence alignment acceptance;
fabricated claim-anchor acceptance; untraceable alignment acceptance;
metadata-only alignment acceptance; provider-AI-synthesis alignment
acceptance; structurally inconsistent relationship acceptance; incompatible
duplicate-pair acceptance.

## Versioning

`CLAIM_ALIGNMENT_CONTRACT_VERSION`, `ALIGNMENT_CLASSIFIER_VERSION`,
`ALIGNMENT_VERIFIER_VERSION` (`src/schemas/claim_alignment.py`) are distinct
from the Phase 2C evidence-extraction version identifiers -- a semantic
contract change here is never conflated with an evidence-extraction contract
change.
