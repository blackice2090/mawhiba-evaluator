# Phase 2E — Claim Sufficiency and Evidence Weighting

Phase 2E answers one question:

> Given all trusted aligned evidence currently available for this claim, what is
> the evidence posture, and is the available evidence sufficient under an
> explicit auditable policy?

It does **not** answer what project score the claim should produce, whether the
claim is universally scientifically proven, or whether the trust gate should
pass. See ADR-015 for the decisions behind this and the alternatives rejected.

The distinctions the phase exists to preserve:

```
Evidence exists          != Evidence supports the claim
Alignment                != Claim verification
Support                  != Sufficiency
Quantity                 != Independence
Source prestige          != Scientific truth
Sufficiency assessment   != Final project score
```

## 1. Position in the trust chain

```
LogicalAcademicSource      Phase 2B  verified bibliographic record
SourceContentSnapshot      Phase 2C  real source text, hashed, provider-attributed
ExtractedEvidence          Phase 2C  an exact span, verbatim by construction
ClaimEvidenceAlignment     Phase 2D  a verified claim/evidence relation
IndependenceGroup          Phase 2E  one underlying study, canonically keyed
EvidenceWeightProfile      Phase 2E  one item's auditable quality/contribution
ClaimComponentSufficiency  Phase 2E  coverage of one exact claim-component anchor
ClaimSufficiencyAssessment Phase 2E  the claim-level posture under a versioned policy
```

## 2. Ownership

`ClaimSufficiencyRun` lives on `ResearchRun.claim_sufficiency`. It is never
written into `ProjectState`, for the same reason Phase 2C evidence and Phase 2D
alignments are not (ADR-010): this is research-evaluation truth — an auditable
analytical artifact over canonical state — not canonical project truth.

Phase 2E mutates none of:

`ProjectState.claims`, `ClaimRecord.status`, `ClaimRecord.confidence`,
`ClaimRecord.evidence_ids`, `ClaimRecord.counter_evidence_ids`,
`ProjectState.evidence`, `ProjectState.scores`, `ProjectState.trust_gate`,
`ProjectState.evaluation_status`, Phase 2C `ExtractedEvidence`, Phase 2D
alignments.

None of those fields exists on any Phase 2E type, and the graph never writes the
`project` channel. The guarantee is structural, not procedural.

## 3. Determinism — no model call, deliberately

Phase 2E makes **no** model call. Every judgement follows from Phase 2D's
structured output plus trusted metadata, so an LLM would add a trust boundary
with nothing behind it to decide (specification section 16). Consequences:

- `ClaimSufficiencyRun` has no `model_name`, no `provider_name`, no prompt
  version and no classifier version. A test asserts those fields do not exist.
- `build_phase2e_claim_sufficiency_graph()` takes no provider and needs no
  credentials or fake provider.
- The offline eval runs with no model at all, not even a fake one, and there is
  no Phase 2E live LLM eval because the architecture does not require one.

Determinism is checkable, not assumed: `independence_group_id`, the profile id
and the assessment id are all `uuid5` over stable inputs, so two independent
passes over the same input produce equal records.

## 4. Input contract

Phase 2E consumes only:

1. `state.project.claims` — existing claims, read-only.
2. `run.evidence_extraction.verified_evidence` — accepted Phase 2C evidence.
3. `run.claim_evidence_alignment.alignments` — verified Phase 2D alignments.
4. `run.academic_research.logical_sources` — trusted Phase 2B source metadata
   and canonical identity.

It creates no claims, extracts no evidence, reinterprets no rejected Phase 2C
candidate, creates no Phase 2D relation, and never reads a provider AI takeaway.
Anything unknown stays `UNKNOWN`.

## 5. Independence grouping — the release-critical step

The unit of corroboration is the `IndependenceGroup`, keyed on Phase 2B's
`SourceFingerprint.logical_key` (`KIND:normalized-identifier`). Because that key
is built from strong identifiers only and can never be a title (ADR-009),
title-similarity collapse is not merely avoided — it is unexpressible.

These do **not** count as independent corroboration:

| Shape | Groups |
|---|---|
| Same DOI returned by Consensus, OpenAlex and Semantic Scholar | 1 |
| Five excerpts from one abstract | 1 |
| Two Phase 2B source records sharing a DOI | 1 |
| Two source records sharing an OpenAlex / arXiv / PMID identifier | 1 |
| Two records with identical titles and different DOIs | 2 |

`SufficiencyCoverage.duplicate_evidence_collapsed` reports exactly the
corroboration inflation that did not happen, and
`INDEPENDENCE_COLLAPSED_DUPLICATES` puts it on the assessment.

Evidence whose source does not resolve to a logical source **in this run** is
given no group at all. That enforces cross-run isolation for free, and turns an
unresolvable chain into `DISQUALIFIED_UNTRACEABLE` rather than an invented group.

## 6. Source-quality dimensions

Only dimensions trusted metadata actually states.

| Dimension | Values | Source |
|---|---|---|
| Retraction | `RETRACTED` / `NOT_RETRACTED` / `UNKNOWN` | `is_retracted` on the logical source and on the evidence; `True` from either marks `RETRACTED` |
| Publication | `PEER_REVIEWED_OR_FORMALLY_PUBLISHED` / `PREPRINT` / `OTHER_PUBLISHED` / `UNKNOWN` | publication *form* only |
| Traceability | `TRACEABLE` or one of five named failures | source → evidence → alignment → claim chain, plus the evidence content hash |
| Content scope | `ABSTRACT_ONLY` / `PARTIAL_TEXT` / `FULL_TEXT` | Phase 2C `EvidenceScope` |
| Provider diversity | observation count, recorded for audit | `LogicalAcademicSource.providers` |

Publication status is never inferred from venue prestige, title wording,
provider identity or a URL: those correlate with quality without evidencing it.
The retraction asymmetry is deliberate — a missed retraction is the expensive
error, so the strictest available signal wins, and `UNKNOWN` survives only when
neither record states anything.

Provider observation count is recorded and is **not** a corroboration
multiplier.

## 7. Contribution classification

Derived deterministically. The Phase 2D relation sets a starting class, and
quality can only ever *downgrade* it to a `DISQUALIFIED_*` value — nothing can
promote `CONTEXT_ONLY` into weak support.

```
traceability != TRACEABLE   -> DISQUALIFIED_UNTRACEABLE   (checked first)
retraction   == RETRACTED   -> DISQUALIFIED_RETRACTED
SUPPORTS                    -> ELIGIBLE_DIRECT_SUPPORT
PARTIALLY_SUPPORTS          -> ELIGIBLE_PARTIAL_SUPPORT
CONTRADICTS                 -> ELIGIBLE_DIRECT_CONTRADICTION
PARTIALLY_CONTRADICTS       -> ELIGIBLE_PARTIAL_CONTRADICTION
MIXED                       -> ELIGIBLE_MIXED
CONTEXT_ONLY                -> CONTEXT_ONLY
INSUFFICIENT                -> RELEVANT_BUT_INSUFFICIENT
NOT_RELEVANT                -> NOT_RELEVANT
```

Traceability is checked before retraction because evidence we cannot trace is
not evidence whose retraction status means anything.

A disqualified item still gets a profile. Dropping it would make the refusal
invisible, and "we looked at this and refused it" must read differently from
"we never saw it".

## 8. Claim-component coverage

Material components are the distinct exact anchors Phase 2D produced for the
claim, carried over verbatim — Phase 2D already proved
`claim.claim[start:end] == anchor_text`, and re-deriving them here would be a
second, weaker source of truth.

A component is *adequately evidenced* only by **direct** coverage from eligible
independence groups. A `SUPPORTS` component judgement inside a
`PARTIALLY_SUPPORTS` or `MIXED` pair is partial coverage, never full: the
evidence did not settle the component, which is why Phase 2D refused to call the
pair a plain `SUPPORTS`.

| Coverage | Condition |
|---|---|
| `SUPPORTED` | ≥1 eligible group directly supports, none directly contradicts |
| `CONTRADICTED` | the mirror image |
| `CONTESTED` | eligible groups do both at the same component |
| `PARTIAL_SUPPORT_ONLY` / `PARTIAL_CONTRADICTION_ONLY` / `PARTIAL_MIXED` | only partial contributions reach it |
| `UNRESOLVED_RELEVANT` | only `RELEVANT_BUT_INSUFFICIENT` |
| `CONTEXT_ONLY` | only contextual |
| `BLOCKED_SOURCE_QUALITY` | every group with a *direct* relation was disqualified |
| `NO_EVIDENCE` | nothing |

`CorroborationLevel` (`NONE` / `SINGLE_GROUP` / `MULTIPLE_GROUPS`) is reported
rather than scored, because a single supporting study is a materially different
epistemic situation from two and the distinction must survive into the report.

## 9. SUFFICIENCY-POLICY-V1

Applied per claim, in this order:

1. `BLOCKED_SOURCE_QUALITY` — direct alignments exist, but every one was
   disqualified. The blocker names why: `ALL_DIRECT_EVIDENCE_RETRACTED`,
   `ALL_DIRECT_EVIDENCE_UNTRACEABLE` or `ALL_DIRECT_EVIDENCE_DISQUALIFIED`.
2. `CONTESTED` — some component is `CONTESTED`, or one component is `SUPPORTED`
   while another is `CONTRADICTED`. Never averaged away.
3. `SUFFICIENT_SUPPORT` — every material component is `SUPPORTED`.
4. `SUFFICIENT_CONTRADICTION` — every material component is `CONTRADICTED`.
5. `PARTIALLY_SUFFICIENT` — at least one material component adequately
   evidenced, at least one not.
6. `NO_DIRECT_EVIDENCE` — no direct supporting or contradicting alignment at
   all. Contextual, insufficient and not-relevant material may exist.
7. `INSUFFICIENT_EVIDENCE` — relevant evidence exists but meets no bar above.

A single eligible independent group satisfies the component bar, and the
assessment carries `SINGLE_INDEPENDENT_SOURCE_ONLY` so the fact that it stood
alone survives. Refusing single-source sufficiency outright was considered and
rejected in ADR-015: it would make an honest single-study finding
indistinguishable from no finding.

The run contract enforces the policy's own limits independently of the policy
code: `SUFFICIENT_SUPPORT` without full component coverage,
`SUFFICIENT_CONTRADICTION` without a contradicting group, `CONTESTED` from one
side only, `BLOCKED_SOURCE_QUALITY` without a blocker, and
`NO_DIRECT_EVIDENCE` carrying direct groups are all rejected by validators.

## 10. Reason codes

`SufficiencyReasonCode` is the authoritative explanation vocabulary. The
`audit_rationale` field is bounded template text assembled from the structured
facts — convenience for a reader, never authoritative, and never model prose.

## 11. Not-ready behaviour

Each cause keeps its own status, so a pipeline gap can never read as an evidence
finding.

| Phase 2D state | Phase 2E status |
|---|---|
| `COMPLETED` with alignments | proceeds |
| `COMPLETED` with none, `NO_ALIGNABLE_CLAIMS`, `NO_ALIGNABLE_EVIDENCE` | `NO_VERIFIED_ALIGNMENTS` |
| `PARTIAL`, `BLOCKED_PAIR_LIMIT_EXCEEDED` | `BLOCKED_ALIGNMENT_INCOMPLETE` |
| not terminal, `FAILED`, `NOT_READY` | `NOT_READY` |

Only a `COMPLETED` Phase 2D run yields assessments. `PARTIAL` means some
required pair was never classified, so sufficiency over it would be a claim
about evidence nobody examined. A not-ready run carries no groups, no profiles
and no assessments, and mutates no `ProjectState`.

## 12. Graph

```
START
  -> LOAD_SUFFICIENCY_RUN --------(no active run)--------------> END
  -> VALIDATE_SUFFICIENCY_INPUT          claims, evidence, sources present?
  -> BUILD_INDEPENDENCE_GROUPS           canonical identity; duplicate collapse
  -> BUILD_EVIDENCE_WEIGHT_PROFILES      multi-dimensional, no scalar
  -> AGGREGATE_CLAIM_COMPONENT_COVERAGE  exact Phase 2D anchors
  -> APPLY_SUFFICIENCY_POLICY            SUFFICIENCY-POLICY-V1
  -> FINALIZE_CLAIM_SUFFICIENCY          terminal status; the run stays open
  -> END
```

Every node guards on `claim_sufficiency.is_terminal`, so a terminal run makes
each downstream node a no-op rather than a routing special case. Nodes recompute
from state rather than threading intermediate values, which is what makes them
replay-safe under LangGraph's re-run-from-first-line semantics (ADR-002). The
research run is left non-terminal so later reviewed branches can still write to
it.

`FORBIDDEN_NODES` lists `SCORING`, `TRUST_GATE`, `RED_TEAM`, `NOVELTY`, `GAP`,
`FINAL_VERIFIER`, `CLOSEST_PRIOR_ART`, `REPORT_GENERATOR`,
`CONTRADICTION_DETECTION` and `CLAIM_EVIDENCE`; a test asserts none is wired in.

## 13. Idempotency

- A terminal sufficiency run is never reopened; re-invoking the finished graph
  is a no-op that preserves the same `sufficiency_run_id` and assessment ids.
- Group, profile and assessment ids are `uuid5` over stable inputs, so a
  checkpoint resume recomputes identical values.
- The run contract rejects two assessments for one claim and two profiles for
  one claim/evidence pair.
- Grouping, profiling and coverage are pure functions whose outputs are
  *assigned*, never appended, so a replay cannot double-count.

## 14. Versioning

| Version | Covers |
|---|---|
| `CLAIM-SUFFICIENCY-CONTRACT-V1` | the record shapes |
| `SUFFICIENCY-POLICY-V1` | the decision policy |
| `EVIDENCE-WEIGHT-PROFILE-V1` | the profile shape and dimension set |
| `SUFFICIENCY-AGGREGATOR-V1` | grouping and coverage computation |

None reuses a Phase 2C or Phase 2D version; a test asserts the sets are
disjoint. A semantic policy change requires bumping the policy version, so an
archived assessment stays readable against the exact policy that produced it.

## 15. Gold eval

`evals/claim_sufficiency/v1/cases.jsonl`, schema in
`evals/claim_sufficiency/v1/schema.md`, harness in
`src/evals/claim_sufficiency/`.

Each case describes a complete synthetic upstream world — claims, Phase 2B
sources with their identifiers, Phase 2C evidence, Phase 2D alignments — and is
driven through the real Phase 2E graph through a real checkpointer. Because
Phase 2E makes no model call there is no scripted model output; the adversarial
surface is the *input shape* instead.

Scoring is implemented independently of the code it scores: the eval re-derives
the independence partition from the fixture's own identifiers, re-derives which
contribution class each input shape permits, re-checks every claim anchor
against the claim text from scratch, and diffs the whole project state, the
Phase 2C evidence and the Phase 2D alignments before and after. Negative
controls prove each gate can fire.

Run it with:

```bash
./.venv/Scripts/python.exe -m src.evals.claim_sufficiency.cli
```

## 16. Remaining limitations

- **Abstract-only.** Phase 2C evidence is abstract-level, so an assessment is
  evidence sufficiency *under currently available trusted content*, not a
  complete scientific review of the paper. `content_scope_ceiling` and
  `ABSTRACT_ONLY_SCOPE` carry this on every record, and the ceiling is `None`
  when nothing contributed — never silently `FULL_TEXT`.
- **The material component set comes from Phase 2D.** A claim component no
  alignment ever anchored is invisible here. Enumerating components
  independently would require semantic decomposition — a model call this phase
  deliberately does not make.
- **Policy-based, not proof.** `SUFFICIENT_SUPPORT` means this versioned
  policy's bar was met by the evidence currently available.
- **Unknown metadata stays unknown.** Phase 2E resolves no missing retraction or
  publication fact; it reports the gap.
- **No project scoring.** Phase 2E produces an input a later reviewed scoring
  phase may weigh, never a score.
