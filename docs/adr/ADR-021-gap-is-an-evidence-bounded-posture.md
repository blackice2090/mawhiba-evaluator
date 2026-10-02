# ADR-021 — Research / Engineering Gap Is an Evidence-Bounded Posture, Not an Absence Claim

Status: accepted (Phase 2J).

## Context

Phase 2I describes technical overlap and differentiation relative to a bounded
candidate set. A student project then needs to be asked a different question:
is there a defensible unmet research question or engineering shortfall that the
project actually targets? The tempting shortcuts all convert absence into a
finding: "no overlap found", "feature not mentioned", "no Arabic app", "different
architecture" are not limitations, and a difference is not a need.

## Decision

A gap is a bounded synthesis, derived in code, of:

1. an anchored **limitation** that a source *states* (admissible forms only);
2. an anchored **existing capability**;
3. an anchored **condition**, only when the limitation is condition-specific;
4. a **project linkage** — a typed, model-assisted judgment per (differentiating
   feature, limitation) pair, structurally bound;
5. a **validation requirement** sliced from the claim or a verified excerpt, with
   no threshold field;
6. **counterevidence** reviewed within the existing inventory, coverage recorded.

Rules that hold by construction:

* **Differentiation != gap.** A Phase 2I differentiating feature is a link
  target, never limitation evidence.
* **Absence != gap.** Absence bases live in a type no `GapLimitation` can hold.
* **Single-source limitation != field-wide gap.** `GapScope` has no field-wide
  value; every statement carries `BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED`.
* **Gap support != proof the project solves the gap.** Linkage is a judgment,
  never labelled verified; validated IDs prove binding only.
* **Gap assessment != methodology / result / score.** No such field exists on any
  Phase 2J type; a test forbids the field-name fragments.
* **Student claim != evidence.** `GapSourceKind` has no student value.
* Existence and linkage are separate derived values, so "no limitation" and "a
  limitation nobody targets" stay distinguishable on the claim record.
* Independence is inherited from Phase 2E / 2I, never recomputed; ungrouped
  academic evidence and unresolved patent families never corroborate.
* HYBRID needs two distinct limitation records (research and engineering), both
  materially linked; sharing a source or excerpt is allowed, copying a
  proposition is not (`proposition_key`).
* Phase 2J searches nothing and mutates no upstream record; upstream subruns are
  fingerprinted at bind and re-checked at finalize.

## Rejected alternatives

* **Let the model decide whether a gap is real.** Unauditable, and exactly the
  failure the rest of the system is built to avoid.
* **Treat a validated linkage record as a verified fact.** Referential integrity
  is not semantic correctness.
* **Require different sources for HYBRID.** One passage can legitimately state an
  open question and a measured shortfall.
* **Require a condition for every gap.** It forces invented conditions.
* **Reuse `ProjectState.gap`.** Same ownership argument as ADR-010: the
  evidence-bounded posture is an analytical artifact on the research run.

## Consequences

An unassessable claim is `INSUFFICIENT_INPUT` with its reason, never "no gap".
The semantic quality of the model-proposed pieces is measured by Gold, not
assumed from structural validity. See `docs/phase2j_research_engineering_gap.md`.
