# Phase 2F — Evidence-Based Claim Scoring

Phase 2F turns the Phase 2E sufficiency posture into a transparent, reproducible,
policy-versioned **claim evidence scorecard** that a later scoring or review
phase can inspect without losing the structure Phases 2C–2E established.

It answers exactly one question:

> How strong is the structured evidentiary support and contradiction posture for
> this claim, under a transparent scoring policy?

It does **not** answer whether the claim is scientifically true, what score the
project should receive, or whether the project passes Mawhiba/Ibdaa judging
criteria.

```
Verified Evidence (2C)
  -> Verified Alignment (2D)
    -> Claim Sufficiency Assessment (2E)
      -> Claim Evidence Score Vector (2F)
        -> Optional Final Support Index (2F)
          -> STOP
```

The chain of distinctions the earlier phases built is preserved in full:

```
Evidence relationship  !=  Sufficiency
Sufficiency            !=  Numeric score
Numeric score          !=  Probability of truth
Claim evidence score   !=  Project merit
Claim evidence score   !=  Official judging score
Claim evidence score   !=  TrustGate result
```

---

## 1. Score semantics: what the number is and is not

`support_index` is **a deterministic index of structured evidentiary support for
one claim under `CLAIM-EVIDENCE-SCORING-POLICY-V1`**, expressed on 0–100.

`support_index = 80` means: *this claim's evidence posture scores 80 out of 100
under a published, versioned point allocation.*

It does **not** mean:

- an 80% probability that the claim is true;
- 80% scientific confidence;
- 80/100 project quality;
- an official Mawhiba/Ibdaa score of 80.

`contradiction_index` is the same quantity in the opposite direction. It is not
an inverse probability, and it is never subtracted from support.

The contracts enforce the naming: a test asserts that no Phase 2F type has a
field called `truth_probability`, `probability`, `confidence`,
`confidence_percentage`, `certainty`, `likelihood`, `p_true` or `belief`. The
misreading this phase most fears is a naming mistake, so the names are a gate
(ADR-017).

---

## 2. Ownership

`ClaimEvidenceScoringRun` lives on `ResearchRun.claim_evidence_scoring`, never
in `ProjectState`, for the ownership reason every phase since 2B has followed:
this is research-evaluation truth, an auditable analytical artifact, not
canonical project truth (ADR-010).

It is deliberately **not** a `ScoreRecord`. The canonical `ScoreRecord` is
project-version rubric scoring — `RubricKind.OFFICIAL`/`ADVISORY`, named axes,
weights, a project total. Reusing it would make an evidence index
indistinguishable from a competition score at the type level, and one refactor
away from being summed into a project total.

Phase 2F writes nothing to: `ProjectState.scores`, any `ScoreRecord`,
`ClaimRecord.status`, claim confidence, `evidence_ids`,
`counter_evidence_ids`, Phase 2C evidence, Phase 2D alignments, Phase 2E
sufficiency assessments, `trust_gate`, or `evaluation_status`. None of those
fields exists on any Phase 2F type, so the boundary is structural rather than
procedural.

---

## 3. Input contract

Phase 2F consumes only a **trusted, `COMPLETED`** Phase 2E run:

- existing claims;
- `ClaimSufficiencyAssessment`s and their `ClaimComponentInventory`;
- `EvidenceWeightProfile`s (for reliability and duplicate-collapse facts);
- `IndependenceGroup` identities, through the group ids the assessment carries;
- Phase 2E source-quality and limitation metadata;
- policy and version metadata.

It never discovers sources, extracts evidence, creates alignments, reclassifies
a Phase 2D relation, changes a Phase 2E outcome, infers a missing
publication/retraction fact, reads a provider AI takeaway, or touches a
cross-run record.

Any Phase 2E status other than `COMPLETED` is a not-ready outcome
(`ClaimScoringStatus.NOT_READY`), and a `COMPLETED` run with no assessments is
`NO_SUFFICIENCY_ASSESSMENTS`. Neither produces a scorecard. A confident `0` over
an input nobody produced would be the worst available answer.

---

## 4. The score vector

`ClaimEvidenceScoreCard` carries, per claim:

| field | meaning |
|---|---|
| `scorecard_id` | `uuid5(scoring_run_id, claim_id)` — stable across reruns |
| `research_run_id` / `scoring_run_id` / `sufficiency_run_id` / `assessment_id` | the exact inputs this card was scored from |
| `sufficiency_outcome` | the Phase 2E outcome, carried unchanged |
| `inventory_completeness` | Phase 2E.1 completeness, carried with the denominator |
| `support` | a `DirectionalScore` |
| `contradiction` | a `DirectionalScore` |
| `component_traces` | one `ComponentScoreTrace` per material component |
| `reliability` | `ScoreReliabilityProfile` |
| `disposition` | `ScoreDisposition` |
| `final_support_index_bp` | the primary scalar, or `None` |
| `reason_codes` / `withheld_reasons` | the authoritative finite explanation |
| `unexamined_component_count` | material components no alignment anchored |
| `input_fingerprint` | sha256 over the scoring-relevant inputs |
| `schema_version` / `policy_version` / `arithmetic_version` | reproducibility |

Each `DirectionalScore` holds `dimensions` (`coverage_bp`,
`corroboration_bp`, `directness_bp`), `index_bp`, the covered/partial/total
component counts, the contributing independence groups, and how many components
were already at maximum corroboration.

**The vector is canonical.** `index_bp` is validated against
`dimensions.total_bp`, so a scalar that disagrees with its own vector is a
contract error, not a rounding quirk.

---

## 5. Support and contradiction are separate channels

Release-critical, and the reason the graph computes them in two separate nodes:

```
net_score = support - contradiction     # FORBIDDEN
```

`90 support / 80 contradiction` must not become indistinguishable from
`10 support / 0 contradiction`. Both would net to 10.

There is no `net` field on any Phase 2F contract, and a test asserts that no
field name contains `net`. When a primary scalar is issued it is *exactly*
`support.index_bp`, enforced in `ClaimEvidenceScoreCard`'s own validator.

---

## 6. `CLAIM-EVIDENCE-SCORING-POLICY-V1`

Each direction earns an index out of 100 points from three dimensions, computed
over the **complete** Phase 2E material component inventory.

### A. Material component coverage — 0 to 50 points

```
adequately_covered_components / total_material_components * 50
```

"Adequately covered" means the component's Phase 2E coverage is `SUPPORTED` for
the support channel or `CONTRADICTED` for the contradiction channel. A
`CONTESTED` component is adequately covered in **both** directions: a real
disagreement is two findings, not half of one.

The denominator is every material component of the claim, **including those no
Phase 2D alignment ever anchored** (ADR-016). This is the single arithmetic fact
that makes an unexamined component lower the score instead of vanishing from it.

### B. Independent corroboration — 0 to 30 points

Per component, from that direction's own independent group count:

| groups | factor |
|---|---|
| 0 | 0 |
| 1 (`SINGLE_GROUP`) | 0.5 |
| 2+ (`MULTIPLE_GROUPS`) | 1.0 |

Averaged over the complete inventory and scaled to 30.

**Deliberately saturating.** Two independent groups and twenty earn the
identical maximum. Going from one independent study to two is the
epistemically large step; two to twenty is mostly a search-effort artifact, and
rewarding it would make the index a measure of how hard somebody looked.

Provider count, excerpt count and duplicate source records cannot increase this
dimension — they collapsed into one `IndependenceGroup` in Phase 2E and arrive
here already collapsed.

The level is computed per direction from that direction's group ids rather than
read from Phase 2E's single `ClaimComponentSufficiency.corroboration` field.
That field cannot express a `CONTESTED` component — Phase 2E leaves it `NONE`
there, because one shared label cannot say "one independent group supports this
and one contradicts it". For an uncontested component the two agree exactly.

A component with only *partial* evidence scores `NONE` here: partial evidence
earns directness half-credit (C) and no corroboration credit.

### C. Relation directness — 0 to 20 points

Per component, per direction:

| state | factor |
|---|---|
| adequately covered (direct) | 1.0 |
| partially covered | 0.5 |
| context-only / insufficient / not-relevant / disqualified / none | 0 |

Averaged over the complete inventory and scaled to 20.

### The directional index

```
index = coverage + corroboration + directness      bounded to [0, 100]
```

The three ceilings sum to exactly 100, so the bound is structural rather than a
clamp that hides an overflow. A test asserts it.

### Worked examples

| world | coverage | corrob. | directness | index |
|---|---|---|---|---|
| 1 component, supported, 1 group | 50.00 | 15.00 | 20.00 | **85.00** |
| 1 component, supported, 2+ groups | 50.00 | 30.00 | 20.00 | **100.00** |
| 2 components, both supported, 1 group each | 50.00 | 15.00 | 20.00 | **85.00** |
| 2 components, one supported 1 group, other unexamined | 25.00 | 7.50 | 10.00 | **42.50** |
| 2 components, one 2 groups, one 1 group | 50.00 | 22.50 | 20.00 | **92.50** |
| 2 components, one partial only | 0.00 | 0.00 | 5.00 | **5.00** |
| 3 components, one supported 1 group, two contextual | 16.67 | 5.00 | 6.67 | **28.34** |

The 42.50 row is the Phase 2E.1 guarantee carried into the number: exactly half
of the fully-covered 85.00, because the half nobody examined stays in the
denominator.

---

## 7. Source quality is a reliability layer, not hidden points

`ScoreReliabilityProfile` reports what stands behind the score and **never moves
it**:

| posture | when |
|---|---|
| `INDETERMINATE` | nothing contributed, or nothing that contributed states its publication form |
| `LIMITED_RELIABILITY` | a contributing group is a preprint, or some group leaves publication or retraction status unknown |
| `MODERATE_RELIABILITY` | every contributing group states formal publication and a retraction fact, but the content is not full text |
| `HIGHER_RELIABILITY` | every contributing group is peer-reviewed or formally published, states a retraction fact, and the evidence rests on full text |

The ladder is ordered `INDETERMINATE < LIMITED < MODERATE < HIGHER` so
"`UNKNOWN` must not improve reliability" is a comparison a test can make.
`INDETERMINATE` is the *lowest* rank on purpose: it is the absence of the facts
the other values are made of, not a middle value.

Peer review is never inferred — not from venue, title, provider or URL — and
`ScoreReliabilityProfile` refuses `HIGHER_RELIABILITY` unless a contributing
group's metadata actually states formal publication.

It is not called "scientific confidence", and it is not a number. The temptation
this design refuses is multiplying the index by 0.8 for a preprint: the number
would move and the reason would be buried in a coefficient nobody can audit.
`LIMITED_RELIABILITY` beside an unchanged 85.00 is a statement a reviewer can
check against the metadata and disagree with.

The profile also counts, separately: retracted groups, untraceable profiles,
preprints, peer-reviewed groups, unknown-publication groups,
unknown-retraction groups, disqualified groups and contributing groups, plus the
content-scope ceiling (`None` when nothing contributed — never silently
`FULL_TEXT`).

---

## 8. Score disposition, and zero versus none

Not every claim should receive an interpretable primary scalar.

| disposition | scalar | when |
|---|---|---|
| `SCORED` | issued | input ready, inventory `COMPLETE`, outcome not contested or blocked |
| `INCOMPLETE_INPUT_SCALAR_WITHHELD` | `None` | Phase 2E input incomplete, or inventory not `COMPLETE` |
| `BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD` | `None` | Phase 2E blocked on source quality |
| `CONTESTED_SCALAR_WITHHELD` | `None` | Phase 2E `CONTESTED` |
| `NO_DIRECT_EVIDENCE` | `None` | an evaluated zero-directional posture |

Precedence is most-fundamental-first: input readiness, then blocked, then
contested, then no-direct-evidence, then `SCORED`. Phase 2E's outcome is read,
never rewritten.

**`0` and `None` are different statements.**

```
0     = evaluated, and no directional evidentiary support
None  = no primary scalar issued
```

`NO_DIRECT_EVIDENCE` withholds the scalar although both indices are a real `0`,
because `0` presented as *the claim's score* invites reading as "scored low"
rather than "nothing direct was found". A fully contradicted claim, by contrast,
**is** `SCORED` with `final_support_index = 0.00` — its support genuinely was
evaluated and genuinely is zero.

### Phase 2E outcome interaction

| Phase 2E outcome | Phase 2F |
|---|---|
| `SUFFICIENT_SUPPORT` | `SCORED`; contradiction index still computed and reported |
| `SUFFICIENT_CONTRADICTION` | `SCORED`; support legitimately 0; claim status untouched |
| `CONTESTED` | both channels reported, scalar withheld |
| `PARTIALLY_SUFFICIENT` | `SCORED` when input is complete; uncovered components stay in the denominator |
| `INSUFFICIENT_EVIDENCE` | indices low or zero; the insufficiency stays explicit on the card |
| `NO_DIRECT_EVIDENCE` | indices 0, scalar withheld |
| `BLOCKED_SOURCE_QUALITY` | scalar withheld |

---

## 9. Deterministic arithmetic — `SCORE-ARITHMETIC-V1`

1. **Integer basis points are the source of truth.** An index is an integer in
   `[0, 10000]`; `10000 bp` is `100.00`. Nothing downstream stores a float.
2. **`Decimal` intermediates** at 28 digits of precision.
3. **`ROUND_HALF_EVEN` to whole basis points.** Chosen over half-up because it
   is unbiased: a scoring policy must not round in its own favour.
4. **Each dimension is rounded, then summed.** The total is the sum of the
   *stored* dimensions, never a separately rounded whole — otherwise a card's
   scalar could sit one basis point away from its own vector, and a reader who
   added the dimensions up would find the system disagreeing with itself.
5. **Display** is `bp / 100` as a two-decimal `Decimal`, never a float.

Identical inputs therefore produce byte-identical serialized numbers on any
platform.

---

## 10. Input fingerprinting

`input_fingerprint` is one sha256 over exactly the Phase 2E facts that can
change a score: claim id, assessment id, sufficiency/research run ids, the
Phase 2E outcome and policy version, the component inventory (its text hash,
length, completeness, strategy version, issues and every component with its
exact anchor and origin), every component's coverage/corroboration and group ids
per axis, every profile's relation, contribution class, retraction, publication,
traceability, scope, limitations and unknowns, the assessment's blockers, scope
ceiling and unknown dimensions, and both Phase 2F versions.

Two properties hold at once:

- **Stability.** No timestamp, no `uuid4`, no dict iteration order, no float
  participates, and every collection is sorted before it is written. The same
  Phase 2E state reproduces the same fingerprint.
- **Sensitivity.** Adding one genuinely independent study changes the
  fingerprint. A fingerprint that survived that would certify nothing.

Two *independent* Phase 2E passes over the same world legitimately produce
different fingerprints, because each mints a new sufficiency run id and
therefore new assessment ids — and the fingerprint covers assessment identity by
design. Content idempotency is checked separately, with the run-scoped ids
stripped.

---

## 11. Anti-gaming and monotonicity

Each is a metamorphic test: two worlds differing by exactly one thing.

| invariant | holds because |
|---|---|
| **Duplicate invariance** — another provider, excerpt or duplicate source record cannot raise corroboration | Phase 2E collapsed them into one `IndependenceGroup`; Phase 2F counts group ids |
| **Irrelevant-evidence invariance** — `NOT_RELEVANT`, `CONTEXT_ONLY`, `INSUFFICIENT` cannot raise direct support | those classes earn no coverage, no corroboration and no directness |
| **Positive monotonicity** — a genuine independent supporting study cannot lower support | corroboration is monotone in the group count |
| **Negative monotonicity** — contradiction cannot raise support | the channels are computed from disjoint trace fields |
| **Retraction monotonicity** — marking a contributing source retracted cannot raise support or reliability | Phase 2E disqualifies it, so it leaves the contributing set |
| **Unknown monotonicity** — replacing known favorable metadata with `UNKNOWN` cannot improve reliability | the ladder ranks `UNKNOWN` states strictly lower |
| **Coverage monotonicity** — adding an unexamined material component cannot raise support | it grows the denominator and contributes nothing |
| **Conflict preservation** — material contradiction cannot be averaged into an ordinary single score | a contested claim withholds the scalar and reports both channels |
| **Boundedness** | dimension ceilings sum to the index maximum |
| **Order invariance** | the pipeline sorts components and profiles deterministically |

---

## 12. Component-level score trace

Per material component: the claim id and exact anchor (`claim.claim[start:end]
== anchor_text`), the support and contradiction states, supporting /
contradicting / disqualified group ids, per-direction corroboration levels,
per-direction directness factors, per-component point shares, and reason codes.

The claim text is not duplicated beyond the anchor: two copies of a claim are
two things that can disagree.

The per-component point fields are that component's *share* of the claim's
index — audit values. The claim-level dimensions are computed from the aggregate
factor sums, so a rounding difference in one component's share cannot corrupt
the aggregate.

---

## 13. Graph

```
START
  -> LOAD_SCORING_RUN --------------(no open run)---------------> END
  -> VALIDATE_SCORING_INPUT              claims present? assessments trusted?
  -> DERIVE_COMPONENT_SCORE_TRACES       every inventory component, both ways
  -> CALCULATE_SUPPORT_CHANNEL           coverage + corroboration + directness
  -> CALCULATE_CONTRADICTION_CHANNEL     its own channel, never netted
  -> DERIVE_SCORE_RELIABILITY            posture beside the score, not in it
  -> APPLY_SCORE_DISPOSITION_POLICY      may a primary scalar be issued?
  -> BUILD_CLAIM_EVIDENCE_SCORECARDS     one card per scored claim
  -> FINALIZE_CLAIM_EVIDENCE_SCORING     terminal status; the run stays open
  -> END
```

`build_phase2f_claim_scoring_graph()` takes **no model provider**: a
model-generated score is forbidden, so there is nothing for one to decide
(section 19). Construction needs no credentials and no fake provider.

The two channels are separate nodes rather than one "compute indices" step, so
the graph itself shows that neither is derived from the other and no node ever
holds a net figure. The disposition policy runs *after* both, because whether a
scalar may be issued depends on the conflict between them — a graph that scored
and then checked would already have produced the number it was meant to
withhold.

`FORBIDDEN_NODES` lists `SCORING`, `TRUST_GATE`, `RED_TEAM`, `NOVELTY`, `GAP`,
`METHODOLOGY`, `EXPERIMENT_REVIEW`, `CLOSEST_PRIOR_ART`,
`CONTRADICTION_DETECTION`, `CLAIM_EVIDENCE`, `FINAL_VERIFIER` and
`REPORT_GENERATOR`, and a test asserts none is wired in. `SCORING` in
particular: a claim evidence index is not a project rubric score, and the
boundary is structural.

Every node guards on `claim_evidence_scoring.is_terminal`, so once
`LOAD_SCORING_RUN` marks the run terminal every downstream node is a no-op
rather than a special routing case. Nodes recompute from state rather than
threading intermediate values, which is what makes an interrupted node
replay-safe (ADR-002).

The run is left **non-terminal** deliberately, exactly as Phases 2B–2E do, so
later reviewed branches can still write to the same `ResearchRun`.

---

## 14. Official-judging separation

Phase 2F encodes **no** Mawhiba/Ibdaa official criterion weights, and nothing
maps `support_index = 80` onto a project innovation score of 80 or any other
competition figure.

Official requirements and official scoring belong to a later, explicitly
reviewed project-evaluation phase. `SCORING` remains a distinct node later in
`PRODUCTION_NODE_ORDER`, and a test asserts both that it sits after Phase 2F's
nodes and that it is not one of them.

---

## 15. Evals

`evals/claim_evidence_scoring/v1/cases.jsonl` — **145 Gold cases** (en 55, ar
45, mixed 45; 81 distinct categories), schema in
`evals/claim_evidence_scoring/v1/schema.md`, regenerated by
`scripts/generate_phase2f_gold.py`.

Each case describes a whole synthetic upstream world and is driven through the
**real Phase 2E graph and then the real Phase 2F graph**. There is no scripted
model output, because Phase 2F makes no model call; the adversarial surface is
the input *shape* and the arithmetic.

Expectations are exact integer basis points, authored from the described world by
applying the published allocation by hand. The scorer in
`src/evals/claim_scoring/runner.py` is independent of the code it grades: it
re-derives the material component denominator from the claim's own text with its
own materiality rule, re-implements the point allocation in
`recomputed_channel_bp` from the policy text above, recomputes each channel from
that channel's traces alone (which is what proves the contradiction index did
not leak into the support index), re-checks every anchor, and diffs the whole
project state, the canonical score records, the Phase 2C evidence, the Phase 2D
alignments and the Phase 2E sufficiency run before and after.

**Seventeen quality metrics must be exactly 1.0** and **48 release-blocking
metrics must be zero**, with per-language subgroups for English, Arabic and
mixed. A subgroup with no cases reports `None`, not `0.0`.

```bash
./.venv/Scripts/python.exe -m src.evals.claim_scoring.cli
```

Two granularity properties are worth knowing when reading a card, both
inherited from ADR-016:

- the component partition is only as fine as Phase 2D's anchor boundaries, so
  two adjacent unanchored stretches merge into one remainder —
  `unexamined_component_count` is a *lower bound* on unexamined propositions;
- `UNKNOWN` inventory completeness cannot arise through the graph (the graph only
  assesses claims it resolved), so the Gold suite reaches it below the graph,
  where it must still withhold the scalar.

---

## 16. Limitations

- **The index is a policy-defined evidence index.** Not a truth probability,
  not scientific confidence, not a project score, not an official judging
  score. The 50/30/20 split, the half-credit for partial relations and the
  saturation tier are defensible judgements, not derived constants.
- **100.00 is hard to reach on purpose.** It requires every material component
  covered by at least two independent studies. A reader expecting good claims
  to cluster in the 80s will find the distribution surprising.
- **Content scope stays abstract-level** unless trusted full text is added
  later (ADR-013), which is why `HIGHER_RELIABILITY` is rare.
- **Publication and retraction metadata may remain `UNKNOWN`**, and `UNKNOWN` is
  never read as favorable — so many honest claims carry `LIMITED_RELIABILITY`
  or `INDETERMINATE` simply because no provider stated a fact.
- **Phase 2F produces no project scoring and no official Mawhiba/Ibdaa
  scoring.**
- **Future calibration requires an explicit policy-version bump**, never a
  silent retune of a constant.
- Everything ADR-014, ADR-015 and ADR-016 limit still holds: Phase 2D's
  semantic correctness is unproven, sufficiency is versioned policy rather than
  proof, and component completeness is structural rather than a guaranteed
  perfect semantic decomposition.
