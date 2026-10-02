# ADR-020 — Technical Overlap and Differentiation Are Descriptive Evidence Postures, Not Legal Novelty Conclusions

Status: accepted (Phase 2I)

## Context

Phases 2G and 2H end at bounded prior-art *candidates*. Phase 2I must say what those
candidates technically disclose relative to the student's claims. The two obvious
shortcuts are both unsafe: asking a model "is this claim novel?", and collapsing the
comparison to a similarity number. Either produces an authoritative-sounding verdict
from evidence that is bounded, partly unreadable, and legally uninterpreted.

## Decision

1. **Technical overlap is a descriptive posture relative to a bounded candidate set.**
   The postures are `MATERIAL_TECHNICAL_OVERLAP_FOUND`, `PARTIAL_TECHNICAL_OVERLAP_ONLY`,
   `NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS`, `MIXED_OVERLAP_AND_DIFFERENTIATION`,
   `INSUFFICIENT_COMPARISON_EVIDENCE`, `BLOCKED_SOURCE_QUALITY`. `NOVEL`, `NOT_NOVEL`,
   `ANTICIPATED`, `INVALID`, `PATENTABLE` and `UNPATENTABLE` do not exist anywhere.
2. **Discovery and comparison stay separate.** A candidate being found says nothing
   about what it discloses; a disclosure exists only as an exact excerpt of verified
   candidate text located by code.
3. **The model classifies per-feature relations under exact-evidence constraints
   and nothing more.** It is never asked about novelty and returns no overall
   verdict. Every disclosure assertion is verified deterministically; the final
   posture is synthesized in Python from verified records and coverage.
4. **Component overlap is not combination overlap.** A deterministic `COMBINATION`
   feature covers the whole claim; full-claim overlap needs one candidate to disclose
   it. Capacity is source- and feature-sensitive (a manifest discloses a component,
   never a mechanism or the combination).
5. **Independence is taken from existing groupings and never inflated.** Unresolved
   patent families are never independent; product entities are never merged (a
   correlation group only caps corroboration); forks and mirrors are never roots.
6. **Chronology is source-type specific and proves no publicity.** A date places a
   candidate on a timeline; it never establishes historical availability or public
   visibility and never a legal prior-art status.
7. **No numeric novelty score.** There is no novelty score, probability, similarity
   verdict, percentage or opaque weight on any Phase 2I type.
8. **Candidate text is data.** Instruction-like source wording stays admissible
   evidence; model *behaviour* that follows it (prompt disclosure, fabricated or
   foreign evidence, schema escape) is what is refused, and a disclosed prompt is
   never persisted.

## Alternatives rejected

* *Ask the model for a novelty judgement.* A fluent verdict with no auditable basis;
  it would also make the legal boundary a prompt-engineering matter.
* *A technical-overlap ratio or similarity score.* It reads as a probability, hides
  unresolved features and source limits, and invites use as a project score.
* *Merge probable or duplicate-content product links into one identity.* Undoes the
  Phase 2H.1 hardening; identical bytes are duplication, not identity.
* *Treat any manifest, README or title as disclosure.* Presence of a package name is
  not a mechanism; documentation is not implementation; a title is not a disclosure.
* *Reject source text that resembles prompt injection.* It discards genuine technical
  evidence (for example a prompt-injection-defense patent) and confuses data with
  behaviour.
* *Bind a repeated excerpt to its first occurrence.* A silent guess that looks like
  verified provenance.
* *Infer a singleton patent family from a one-publication fixture.* Family status is
  established by the family service, not by counting what a search returned.

## Consequences

* Phase 2I cannot express, by construction, any legal or scoring conclusion; a test
  asserts the absence of such fields and values.
* A claim with thin or partial evidence resolves to `INSUFFICIENT_COMPARISON_EVIDENCE`
  rather than to an optimistic or pessimistic posture.
* Open-source candidates can currently reach only a partial or component-only
  overlap, because Phase 2H captures no source-code file kind. This is recorded as a
  limitation, not worked around.
* The Gold eval re-derives every gate from the serialized run and the upstream
  records, so a validator that wrongly accepts something cannot hide from the gate
  that checks it. It caught one real defect during development: a rejected
  system-prompt disclosure was being persisted in the rejection ledger.
