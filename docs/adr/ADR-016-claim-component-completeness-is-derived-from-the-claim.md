# ADR-016: Claim-Component Completeness Is Derived From the Claim, Not From the Alignment Anchors

## Status

Accepted (Phase 2E.1). Amends ADR-015.

## Context

Phase 2E decided sufficiency per material claim component, and took the material
component set to be the union of the exact anchors Phase 2D produced for that
claim. ADR-015 recorded the consequence as a limitation:

> **The material component set comes from Phase 2D.** A claim component that no
> alignment ever anchored is invisible to Phase 2E.

On review that is not a limitation, it is a **false-sufficiency path**, and it
had to be closed before Phase 2E could merge. Concretely, for the claim

```
The detector reaches 94% accuracy, runs in 5 ms on embedded hardware.
```

with a single Phase 2D alignment anchored at `The detector reaches 94% accuracy`,
the anchor union was one component, that component was `SUPPORTED`, "every
material component is supported" held vacuously, and the claim reached
`SUFFICIENT_SUPPORT` — while nothing whatsoever had been examined about the
latency half of the very same claim. The denominator was defined by what the
evidence happened to be aimed at, so evidence could never fail to cover it.

That contradicts the guarantee the phase exists to provide. `SUFFICIENT_SUPPORT`
is read by a later scoring phase and by a human report; it has to mean *the
material proposition this claim states has been accounted for*, not *the part of
it somebody looked at checked out*.

## Decision

The material component set is derived from the **canonical claim's own text**,
independently of whether any evidence exists for any part of it, and is carried
in a new contract that the assessment must agree with.

1. **`ClaimComponentInventory`** (`src/schemas/claim_component_inventory.py`) is
   a *complete covering partition of the claim text*: pairwise disjoint
   components, each with an exact anchor (`claim.claim[start:end] == text`,
   character for character), plus explicitly recorded `immaterial_spans`, such
   that every character of the claim belongs to exactly one of the two. It
   carries `claim_text_hash`, so it is bound to the exact claim it describes.

2. **`completeness` is a finite taxonomy** — `COMPLETE`, `INCOMPLETE`,
   `UNKNOWN` — and it is *arithmetic, not a label*: `COMPLETE` requires no
   issues, at least one material component, and the spans to cover
   `[0, len(claim))` exactly. `UNKNOWN` (the claim could not be resolved or its
   text does not match the recorded hash) is never read as `COMPLETE`.

3. **A part of the claim no alignment anchored is a first-class component** with
   `origin = UNANCHORED_CLAIM_REMAINDER` and `NO_EVIDENCE` coverage. It counts
   in the denominator exactly like an anchored component. `origin` is audit
   information only; it never changes how coverage is computed, because a
   component nobody aimed at must count like one somebody did.

4. **`SUFFICIENT_SUPPORT` and `SUFFICIENT_CONTRADICTION` require a `COMPLETE`
   inventory**, enforced in `ClaimSufficiencyAssessment`'s own validator and not
   only in `decide_outcome`. The assessment's component set must also *equal*
   the inventory's, so a component present in the inventory and missing from the
   verdict is refused rather than silently dropped — the release blocker itself,
   caught by the contract.

5. **`COMPONENT-PARTITION-STRATEGY-V1`** chooses the cut points: verify every
   Phase 2D anchor against the claim, cut at each surviving boundary plus `0`
   and `len(claim)`, and classify each segment. The strategy version is separate
   from the contract version so a future strategy can be swapped in against the
   same verified contract.

6. **Materiality is whitespace and punctuation only.** A segment is material
   when it holds at least one character that is neither whitespace nor in
   Unicode's punctuation or symbol categories. There is no stopword list, in any
   language. The rule can only ever err by calling filler *material*, which
   leaves an extra component in the denominator and makes sufficiency harder to
   reach; it can never drop a content word.

7. **Anchors are re-verified, and an unverifiable anchor makes its pair
   untraceable.** `TraceabilityStatus.CLAIM_ANCHOR_NOT_VERIFIABLE` is new. A
   fabricated anchor is therefore refused twice over: it cannot become an
   inventory component, it leaves the inventory `INCOMPLETE`, and its pair
   contributes nothing — the last part matters because a fabricated anchor's
   *span* can coincide with a real component, and offsets alone would have let
   invented claim text vouch for it.

8. **No model call.** Phase 2E remains fully deterministic, with no provider
   seam and no prompt version, exactly as ADR-015 decided.

## Rejected alternatives

**Keeping the anchor union and documenting the gap.** That is what Phase 2E did,
and it is what this ADR exists to reverse. A limitation is acceptable when the
system's output stays honest; here the output was `SUFFICIENT_SUPPORT` for a
proposition half of which was never examined.

**A model-assisted semantic decomposition.** The Phase 2E.1 specification
explicitly authorised a structured model call for this, and it would give finer
components — "reaches 94% accuracy" as a proposition rather than a span. It was
rejected because a smaller sound solution exists. A model call here would add a
trust boundary (untrusted candidate components, deterministic anchor
verification, prompt-injection resistance for claim text that is *already* fed
in as data), a provider seam to a phase that has none, a prompt version to
archive, and a class of failure — a plausible decomposition that omits a
component — that verification could not catch, because verification can prove an
anchor exists but not that the set of anchors is exhaustive. The partition
approach gets exhaustiveness *by construction*: it is checked against the claim
text by counting characters. That is a stronger completeness guarantee than a
verified model decomposition could offer, and it needs no model.

**Punctuation or conjunction splitting as a substitute for decomposition.**
Rejected, and the specification forbids it. "black and white image" is one
component and no deterministic rule distinguishes it from "is fast and is
accurate". This strategy therefore does not split on conjunctions at all; it
uses boundaries Phase 2D already established and proves *coverage* separately.

**A single whole-claim component.** Sound, and the smallest possible inventory,
but it collapses `PARTIALLY_SUFFICIENT` into unreachability: with one component
a claim is either fully covered or has no coverage, so "one component supported,
another unexamined" — the posture this phase most needs to express — could not
be represented.

**Refusing any outcome when the inventory is not `COMPLETE`.** Rejected as
throwing away real findings. An `INCOMPLETE` inventory still supports
`PARTIALLY_SUFFICIENT`, `CONTESTED`, `BLOCKED_SOURCE_QUALITY` and the rest; what
it must not support is a *full* outcome. Reporting "one component is supported,
and the inventory could not be completed" is more useful than reporting nothing.

## Consequences

Good:

- The false-sufficiency path is closed, and closed structurally: a component
  cannot leave the denominator, because the denominator is computed from the
  claim rather than from the evidence aimed at it.
- The report can point at the exact unexamined claim text, in Arabic, English or
  mixed script, because the component is a real span of the real claim.
- A prompt injection inside claim text is not merely inert (there is no model to
  inject) — it is material claim text, so it becomes an unexamined component and
  makes sufficiency *harder* to reach.
- `unexamined_component_count` and `inventory_completeness` are on the
  assessment, so "how much of this claim did we actually look at?" is answerable
  from the stored record.

Costs, accepted deliberately:

- **`SUFFICIENT_SUPPORT` now means more, and is reached less often.** It requires
  Phase 2D's anchors to collectively cover every material character of the
  claim. In the Gold suite that is reachable and exercised; in production it
  depends on Phase 2D anchor granularity, and claims whose anchors are narrow
  sub-phrases will land on `PARTIALLY_SUFFICIENT` with the uncovered text named.
  That is the conservative direction and the intended one, but it is a real
  behaviour change: existing Gold expectations were re-authored against the
  amended policy, not flipped to match output.
- The partition is only as fine as the anchor boundaries, so two adjacent
  unexamined components merge into one remainder. Coarser, never smaller: all
  the unexamined text is still in the denominator, but the count of unexamined
  components is a lower bound on the number of unexamined propositions.

Limitations, stated rather than hidden:

- **Verified exact component anchors are not a guaranteed-perfect semantic
  decomposition.** What is proven is structural: each component is exact claim
  text, the components are disjoint, and together they account for every
  material character of the claim. What is *not* proven is that the partition
  cuts the claim where a scientist would cut it. A component may bundle two
  propositions that deserved separate treatment (whenever no anchor fell between
  them), and the conjunction joining two clauses is attached to one of them
  rather than analysed. Completeness here means *no material claim text is
  unaccounted for*; it does not mean *the proposition has been ideally
  decomposed*. A later reviewed phase may refine the strategy — the contract is
  versioned for exactly that — and this ADR should be read as closing the
  false-sufficiency path, not as claiming semantic perfection.
- Everything ADR-015 lists still holds: abstract-only content scope, sufficiency
  as versioned policy rather than proof, and no project score or claim-status
  change from this phase.
