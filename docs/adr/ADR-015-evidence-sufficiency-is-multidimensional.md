# ADR-015: Evidence Sufficiency Is Multi-Dimensional and Must Not Collapse Into an Opaque Weight

## Status

Accepted (Phase 2E). Amended by ADR-016 (Phase 2E.1), which replaces the
Phase-2D-derived material component set with a component inventory derived from
the claim's own text. Everything else here stands.

## Context

Phase 2D produces `ClaimEvidenceAlignment`: for one claim and one verified
Phase 2C evidence item, a finite semantic relation plus per-component
judgements at exact claim anchors. It deliberately stops there (ADR-014). It
cannot say how much evidence there is, whether that evidence is independent, or
whether the total is enough.

The next question is: *given all trusted aligned evidence currently available
for this claim, what is the evidence posture, and is the available evidence
sufficient under an explicit auditable policy?*

The obvious implementation is a number. Score each evidence item on quality,
weight it by relation strength, sum across items, threshold the total:
`evidence_weight = 0.73`, and a claim is "supported" above some bar. That
design is attractive because it composes trivially with a later scoring phase.

It is also the design that would destroy the property this whole system exists
to provide. The quality bar for this project is that anyone can ask *"why did
you give this judgement?"* and get the evidence, sources, confidence and gaps,
step by step. A scalar cannot answer that question. `0.73` cannot be
decomposed back into "one abstract-only preprint, retraction status unknown,
supporting two of three material components, observed by three providers that
are not three studies". Worse, a sum actively destroys distinctions that must
survive:

- Two independent supporting studies and one study cited twice reach the same
  total, when they are epistemically different situations.
- Material support plus material contradiction averages to a middling number
  that reads like weak support, rather than reading as the genuine scientific
  disagreement it is.
- An unknown quality dimension has to be given *some* numeric value to
  participate in a sum. Any value chosen is a fabrication: zero treats the
  unknown as bad, a neutral midpoint treats it as mediocre, and inheriting a
  default treats it as fine. The system's Zero Assumption rule says a false
  UNKNOWN is preferable to a fabricated KNOWN; a scalar cannot express UNKNOWN
  at all.

## Decision

Phase 2E produces a **multi-dimensional, reason-coded** sufficiency record and
no scalar anywhere. Specifically:

1. **`EvidenceWeightProfile` keeps every dimension readable as itself**: the
   Phase 2D relation, a deterministic `EvidenceContributionClass`, per-component
   coverage at exact anchors, `RetractionStatus`, `PublicationStatus`,
   `TraceabilityStatus`, `ContentScopeLimitation`, an explicit
   `EvidenceLimitation` list and an explicit `unknown_dimensions` list. There
   is no field that combines them, because any such field would be the one
   number that hides the nine facts a reviewer needs. A test asserts that no
   numeric field exists on the Phase 2E contracts beyond anchor offsets and a
   publication year.
2. **`ClaimSufficiencyAssessment` records a bounded `SufficiencyOutcome` plus
   the `SufficiencyReasonCode` set that produced it.** The reason codes are
   authoritative; the `audit_rationale` is template text generated from those
   structured facts, and no model writes it.
3. **Source quality and semantic relation stay separate.** Quality lives on
   `SourceQualityProfile`, attached to the logical source and claim-independent.
   Semantic contribution lives on the profile, and is claim-specific. Mixing
   them would create a global "support weight" that travels to claims it was
   never assessed against — the same evidence item legitimately `SUPPORTS` one
   claim and is `NOT_RELEVANT` to another.
4. **Corroboration is counted in independence groups, never in items.**
   `IndependenceGroup` is keyed on Phase 2B's `SourceFingerprint.logical_key`
   — a normalized strong identifier, never a title (ADR-009). Provider
   observations of one work, multiple excerpts from one abstract, and two source
   records sharing a DOI all collapse to one group. Multiple excerpts may
   improve *component coverage*; they can never increase the independent-source
   count. Group ids are `uuid5` over the run and the canonical identity, so a
   rerun or a checkpoint resume reproduces them exactly.
5. **Unknown stays explicit.** `RetractionStatus.UNKNOWN` and
   `PublicationStatus.UNKNOWN` are first-class and never folded into their
   favorable neighbours. An unknown retraction status does not disqualify
   evidence and does not clear it either: the evidence contributes, carrying
   `UNKNOWN_RETRACTION_STATUS` so the gap is visible.
6. **Phase 2E cannot mutate a `ClaimRecord`.** There is no `claim_status`, no
   `confidence`, no `evidence_ids`, no `counter_evidence_ids`, no `score` and no
   `trust_gate` field anywhere in `src/schemas/claim_sufficiency.py`, and the
   Phase 2E graph never writes the `project` channel. `ClaimSufficiencyRun`
   lives on `ResearchRun.claim_sufficiency`, the same ownership boundary
   Phase 2C and 2D established (ADR-010).
7. **Phase 2E produces no project score and no trust verdict.** `SCORING`,
   `TRUST_GATE`, `RED_TEAM` and the rest are listed in the Phase 2E graph's
   `FORBIDDEN_NODES` so a test asserts their absence. A sufficiency posture is
   an input a later scoring phase may weigh; it is not itself a score.
8. **Phase 2E is fully deterministic and makes no model call.** Every judgement
   follows from Phase 2D's structured output plus trusted metadata, so an LLM
   would add a trust boundary with nothing behind it to decide.
   `ClaimSufficiencyRun` carries no `model_name`, no `provider_name` and no
   prompt version, and a test asserts those fields do not exist.

## Rejected alternatives

**A single weighted score (`evidence_weight: float`).** Rejected for the
reasons above: it cannot be decomposed, it cannot represent unknown, and it
averages real disagreement into apparent weak support. If a scalar is ever
justified it belongs to the scoring phase, computed *from* these dimensions and
displayed alongside them, never in place of them.

**Per-dimension numeric penalties (a preprint multiplier, a retraction
multiplier).** Rejected as the same mistake in smaller pieces. A "preprint
penalty of 0.7" is an unevidenced quantification of how much less a preprint is
worth, and multiplying penalties silently nets a preprint read only through its
abstract against a corroborating second source. Phase 2E accumulates
limitations instead, and never cancels one against another.

**Counting evidence items as studies.** Rejected: this is the specific failure
the independence grouping exists to prevent. Three providers returning one DOI
is one study.

**Deciding sufficiency with a model.** Rejected under section 16 of the phase
specification: everything needed is already structured, and asking a model to
re-decide it would introduce an unverifiable judgement where a deterministic one
is available.

**Refusing sufficiency from a single independent source.** Considered and
rejected. It would make an honest single-study finding indistinguishable from no
finding at all, which is its own form of dishonesty. Instead a single group
satisfies the component bar and the assessment carries
`SINGLE_INDEPENDENT_SOURCE_ONLY`, so a later phase can weigh that explicitly and
a report can state it.

**Letting Phase 2E decompose claims into components itself.** Rejected here as
out of scope and as a hidden model call, on the reasoning that the material
component set is exactly what Phase 2D anchored. **Revised by ADR-016**: the
component set is now derived from the claim text, but still without a model
call -- the inventory proves *coverage* of the claim arithmetically instead of
proposing a semantic decomposition.

## Consequences

Good:

- "Why is this claim `PARTIALLY_SUFFICIENT`?" is answerable from the stored
  record alone, without re-running anything.
- Contradiction survives into the report as `CONTESTED` instead of being
  averaged away.
- Duplicate control is arithmetic rather than aspiration: the group count *is*
  the corroboration count.
- A semantic policy change requires bumping `SUFFICIENCY_POLICY_VERSION`, so an
  archived assessment stays readable against the exact policy that produced it.

Costs, accepted deliberately:

- The record is larger and more verbose than a number.
- A later scoring phase must do real work to consume it, rather than reading one
  field. That work is where the weighting judgement belongs, and it will be
  reviewed as such.

Limitations, stated rather than hidden:

- **Abstract-only.** Phase 2C evidence is currently abstract-level, so a
  sufficiency assessment is evidence sufficiency *under currently available
  trusted content*, not a complete scientific review of the underlying paper.
  `content_scope_ceiling` and `ABSTRACT_ONLY_SCOPE` carry this on every record.
- **The material component set came from Phase 2D. Superseded by ADR-016.**
  This was originally recorded here as a limitation: a claim component no
  alignment ever anchored was invisible to Phase 2E, so a compound claim could
  reach `SUFFICIENT_SUPPORT` on the components Phase 2D identified while an
  unanchored component went unexamined. On review that was a false-sufficiency
  path rather than an acceptable limitation, and Phase 2E.1 closed it:
  `ClaimComponentInventory` derives the material component set from the claim's
  own text as a verified covering partition, an unanchored part is a first-class
  `NO_EVIDENCE` component, and a full-sufficiency outcome requires a `COMPLETE`
  inventory. See ADR-016, including what the partition does and does not prove.
- **Sufficiency is policy-based, not proof.** `SUFFICIENT_SUPPORT` means this
  versioned policy's bar was met by the evidence currently available. It is not
  universal scientific proof, and it does not change a claim's status.
