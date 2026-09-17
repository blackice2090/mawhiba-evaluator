# ADR-017: Claim Evidence Scores Are Deterministic Evidence Indices, Not Truth Probabilities or Project Scores

## Status

Accepted (Phase 2F). Builds on ADR-015 and ADR-016; does not amend them.

## Context

Every phase up to 2E deliberately refused to produce a number. ADR-015 went
further and forbade one outright: sufficiency is multi-dimensional, there is no
`evidence_weight: float` anywhere, and a test asserts that no numeric field
appears on the Phase 2E contracts. The reason was that a single scalar would be
the one number that hides the nine facts a reviewer needs.

That refusal cannot hold forever. A later scoring phase, a report, and a human
reviewer all need to compare claims, and "this claim is `PARTIALLY_SUFFICIENT`
with four components, two supported by one independent group each, one
contradicted, and one unexamined" is not comparable across a hundred claims by
inspection. Something has to reduce the posture to an ordered quantity.

So Phase 2F is the first phase permitted to derive a numeric claim-level index.
The question this ADR settles is not *whether* to produce a number — the
specification requires one — but **what a reader is allowed to conclude from
it**, and which structural guarantees make the wrong conclusion impossible
rather than merely discouraged.

The failure mode is specific and well-documented in evidence-assessment
systems: a number produced by a transparent, defensible procedure gets read as
a probability. `support_index = 80` becomes "80% likely true", then "80%
confidence", then a project score, then a judging score. Each step is a small
misreading and the last one is a real decision about a real student's project.
Nothing in the arithmetic prevents any of it.

## Decision

A Phase 2F number is **a deterministic index of structured evidentiary support
for one claim under `CLAIM-EVIDENCE-SCORING-POLICY-V1`**, and the architecture
is arranged so it cannot be mistaken for anything else.

1. **`ClaimEvidenceScoringRun` lives on the `ResearchRun`**, never in
   `ProjectState`, and is emphatically **not** a `ScoreRecord`. The canonical
   `ScoreRecord` is project-version rubric scoring with axes, weights and an
   official/advisory distinction; reusing it would make an evidence index
   indistinguishable from a competition score at the type level. Phase 2F
   writes nothing to `ProjectState.scores` (ADR-010, section 4, section 28).

2. **The vector is canonical; the scalar is derived and secondary.** Every
   index is the sum of three named dimensions that stay individually visible —
   component coverage, independent corroboration, relation directness — and
   `DirectionalScore` validates `index_bp == coverage + corroboration +
   directness` exactly. The scalar can never say something the dimensions do
   not.

3. **Support and contradiction are separate channels and are never merged.**
   There is no `net_score` field, no field that could hold one, and a test
   asserts no field name on any Phase 2F contract contains `net`.
   `90 support / 80 contradiction` must not become indistinguishable from
   `10 support / 0 contradiction`.

4. **A primary scalar is optional, and withheld when one number would mislead.**
   `ScoreDisposition` records why: `CONTESTED_SCALAR_WITHHELD`,
   `BLOCKED_SOURCE_QUALITY_SCALAR_WITHHELD`,
   `INCOMPLETE_INPUT_SCALAR_WITHHELD`, `NO_DIRECT_EVIDENCE`, or `SCORED`. When
   issued, `final_support_index_bp` **equals** `support.index_bp` — never a
   difference of the two channels — and the schema enforces both halves of
   that.

5. **`None` and `0` mean different things.** `0` is an evaluated index with no
   directional evidentiary support. `None` is no scalar issued. The disposition
   states which, so a reader never has to guess.

6. **Source quality is a reliability layer, never hidden points.**
   `ScoreReliabilityProfile` reports retraction, publication form, traceability
   and content scope as a finite posture beside the index. It adds no points and
   subtracts none.

7. **Integer basis points, `Decimal` intermediates, `ROUND_HALF_EVEN`.** The
   stored integer is the source of truth; nothing downstream holds a float.
   Each dimension is rounded once and the total is the sum of the stored
   dimensions.

8. **The Phase 2E.1 denominator survives into the score.** The component
   denominator is the complete `ClaimComponentInventory`, including material
   components no alignment ever anchored. An unexamined component lowers the
   index instead of vanishing from it, and a non-`COMPLETE` inventory withholds
   the primary scalar (ADR-016).

9. **No model call.** A model-generated score is forbidden. There is no
   provider seam, no prompt version and no classifier version on any Phase 2F
   type.

10. **Corroboration saturates.** Two independent groups and twenty earn the
    identical maximum.

## Rejected alternatives

**A single net truth score.** The obvious design, and the one the
specification names as forbidden. `net = support - contradiction` is not just
lossy, it is actively misleading in the most important case: a claim with
strong evidence on both sides — precisely the claim a reviewer most needs to
look at — nets to the same figure as a claim nobody studied. Two separate
bounded channels cost one extra field and preserve the distinction exactly.

**A calibrated probability.** Tempting, because a probability is what a reader
wants. Rejected because nothing in this system licenses one. A probability
would need a reference class, a base rate and a validated likelihood model over
claim/evidence relations; we have abstract-level evidence, a synthetic Gold
suite, and no outcome data at all. Producing a number *shaped* like a
probability without any of that would be the single most dishonest thing this
architecture could do, and it would be indistinguishable from the honest
version at the point of use. `support_index` is named the way it is so the type
itself refuses the reading.

**Folding source quality into the score as weights.** The intuitive move: a
preprint contributes 0.8 of a journal article. Rejected because it makes the
score unauditable. The number moves and the reason is buried in a coefficient
nobody can see; a reviewer who disagrees with the discount has nothing to
disagree with. `LIMITED_RELIABILITY` printed beside an unchanged index is a
statement that can be checked against the metadata and argued with. This also
keeps `UNKNOWN` honest: an unknown publication status lowers the posture and
leaves the index alone, where a multiplicative weight would have had to invent
a number for "we do not know".

**Unbounded corroboration.** Rewarding the twentieth independent study would
make the index partly a measure of how hard somebody searched, which is a
property of the search, not of the claim. Going from one independent study to
two is the epistemically large step; two to twenty is mostly retrieval effort.
A later policy may add tiers — under a new policy version, never a silent
retune.

**Reusing the canonical `ScoreRecord`.** Considered for economy, rejected on
semantics: its `RubricKind.OFFICIAL`/`ADVISORY` distinction, axis names and
weights are the vocabulary of project judging. An evidence index sitting in a
`ScoreAxis` would be one refactor away from being summed into a project total.

**Refusing any scalar unless everything is perfect.** Rejected as throwing away
real findings. A claim whose inventory is incomplete still has meaningful
directional indices; what it must not have is a *primary* number presented as
the claim's score.

## Consequences

Good:

- A claim's evidence posture is comparable across claims without losing the
  structure that produced it: the vector is still there, and the reason codes
  are still authoritative.
- The false-sufficiency path ADR-016 closed stays closed numerically. A
  compound claim half of which nobody examined scores exactly half.
- Conflict is impossible to hide. A contested claim reports both channels and
  no primary scalar, so a report cannot render it as an ordinary middling
  result.
- Anti-gaming is arithmetic rather than review: duplicates collapsed in
  Phase 2E arrive already collapsed, saturation caps corroboration, and
  non-supporting relations earn nothing. Adding sources cannot raise a score.
- Every number is reproducible from its `input_fingerprint`, and a
  scoring-relevant change to the input changes the fingerprint.

Costs, accepted deliberately:

- **The maximum is hard to reach, on purpose.** 100.00 requires every material
  component of the claim covered by at least two independent studies. Most
  real claims will land well below that, and the index must be read as "posture
  under this policy", not as a grade. A reader who expects most good claims to
  score in the 80s will find the distribution surprising.
- **Two numbers per claim, not one.** Every consumer must handle the
  contradiction channel and the `None` case. That is more work than a single
  float, and it is the point.
- **The policy is a judgement, not a measurement.** The 50/30/20 split, the
  half-credit for partial relations and the saturation tier are defensible
  choices, not derived constants. They are versioned so an archived scorecard
  stays readable, and changing any of them requires a policy-version bump.

Limitations, stated rather than hidden:

- **The index is a policy-defined evidence index, not a truth probability, not
  scientific confidence, and not a project or official Mawhiba/Ibdaa judging
  score.** It says how well the structured, verified evidence currently
  available covers the claim under one published allocation. It does not say
  the claim is true, and two claims with the same index can differ in every way
  that matters scientifically.
- Everything ADR-013 says about scope still holds: the content behind these
  numbers is abstract-level unless trusted full text is added later, and
  `HIGHER_RELIABILITY` is consequently rare.
- Publication and retraction metadata may remain `UNKNOWN`, and `UNKNOWN` is
  never read as favorable — so many honest claims will carry
  `LIMITED_RELIABILITY` or `INDETERMINATE` simply because no provider stated a
  fact.
- Phase 2F produces no project scoring and no official judging score. Mapping
  an evidence index onto a competition criterion is a later, explicitly
  reviewed phase, and this ADR is not authority for it.
- Future calibration — against real judging outcomes, if that data ever exists
  — requires an explicit policy-version change and a re-authored Gold suite.
  Never a silent retune of a constant in `policy.py`.
