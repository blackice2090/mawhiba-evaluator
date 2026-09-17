# ADR-014: Claim-Evidence Alignment Is Not Claim Verification

## Status

Accepted (Phase 2D).

## Context

Phase 2C produces `ExtractedEvidence`: verbatim excerpts from real source
content, proven to exist at exact offsets. It deliberately says nothing about
whether any of that evidence bears on a specific student claim (ADR-012).

The next question the system must answer is: *what semantic relationship does
this specific verified evidence item have to this specific existing claim?*
That is a narrower question than "is the claim proven?", and the two must not
be conflated. A claim can be materially supported by one piece of evidence and
still be far from sufficiently proven -- sufficiency depends on the number,
independence, and strength of all aligned evidence, which is a later phase's
job (scoring, red-teaming, the trust gate).

## Decision

Phase 2D classifies the relationship between one claim and one verified
evidence item into a finite taxonomy (`AlignmentRelation`: `SUPPORTS`,
`CONTRADICTS`, `PARTIALLY_SUPPORTS`, `PARTIALLY_CONTRADICTS`, `MIXED`,
`CONTEXT_ONLY`, `INSUFFICIENT`, `NOT_RELEVANT`) and stores the result as a
`ClaimEvidenceAlignment` record on the `ResearchRun`, never in `ProjectState`.

Consequences of this split, enforced structurally rather than by convention:

1. **No claim mutation.** `ClaimEvidenceAlignment` has no `claim_status`, no
   `confidence`, no `evidence_ids` and no `counter_evidence_ids` field. The
   Phase 2D graph never writes the `project` channel. A verified alignment
   record cannot cause `ClaimStatus.SUPPORTED`, a confidence increase, or an
   `evidence_ids` mutation even by accident -- the fields do not exist to be
   set, mirroring how ADR-012 kept `support_direction` out of Phase 2C.
2. **Ownership stays with the research execution layer.** Like
   `EvidenceExtractionRun` before it, `ClaimEvidenceAlignmentRun` lives on
   `ResearchRun.claim_evidence_alignment`. `ClaimRecord.evidence_ids` requires
   an `EvidenceRecord` inside `ProjectState.evidence`, and Phase 2D evidence
   items still live on the research run (ADR-010) -- writing an alignment
   into `ProjectState` would have meant breaking that referential integrity or
   moving evidence ownership, both out of scope here.
3. **Verification proves structure and provenance, not science.** The
   deterministic verifier proves: the claim and evidence exist and are
   eligible; every proposed claim anchor is an exact substring of the claim's
   own text; the pair-level relation is consistent with its component
   judgments; the pair has not already been decided incompatibly. It never
   proves that the model's semantic classification is scientifically correct
   -- there is no way to prove that deterministically, and Phase 2D does not
   pretend otherwise (mirrors ADR-011's "verified" meaning "verbatim", not
   "true").
4. **A verified alignment is not a verified claim.** The one-sentence
   invariant, repeated in the schema docstring and the graph module docstring
   so it cannot be missed: "this verified evidence item has been classified as
   having this semantic relationship to this existing claim, and the
   relationship record passed deterministic structural/provenance
   verification" -- never "the claim is verified."

## Rejected Alternatives

- **Writing alignment results directly onto `ClaimRecord.evidence_ids`.**
  Rejected: it would silently promote "evidence exists and was classified as
  relevant" into "the claim is supported," collapsing the very distinction
  this phase exists to preserve, and it would require Phase 2D evidence to
  live in `ProjectState.evidence`, breaking ADR-010's ownership boundary.
- **A confidence score per alignment instead of a taxonomy.** Rejected: a
  single number invites exactly the sufficiency judgement this phase must not
  make, and it cannot express the compound-claim cases (`PARTIALLY_SUPPORTS`,
  `MIXED`) that a scalar collapses into an average.
- **Auto-updating claim status when `SUPPORTS` alignments accumulate.**
  Rejected: sufficiency requires more context than one evidence item's
  relationship -- independence, evidence strength, contradicting evidence
  elsewhere, source quality -- all reserved for the scoring and trust-gate
  phases that come later.

## Consequences

- Downstream phases (claim sufficiency scoring, the trust gate, red-teaming)
  read `ClaimEvidenceAlignmentRun` as an input signal, never as a verdict.
- A claim can carry `CONTRADICTS` alignments from several evidence items and
  still show `ClaimStatus.UNSUPPORTED` in `ProjectState`, because nothing in
  this phase is authorized to change it. That is a feature: the audit trail
  says what evidence says, and a separate phase says what it means for the
  claim.
- `evals/claim_evidence_alignment` measures alignment behaviour in isolation:
  taxonomy consistency, anchor exactness, provenance, and safety gates. It
  says nothing about whether the *scientific* classification a live model
  would produce is correct, which no offline scripted eval can prove (see
  `docs/phase2d_claim_evidence_alignment.md`, Eval Honesty).
