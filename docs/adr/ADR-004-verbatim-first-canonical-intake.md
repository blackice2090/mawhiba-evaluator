# ADR-004 — Canonical factual intake stores source-backed wording, not LLM paraphrase

**Status:** Accepted
**Date:** 2026-09-14
**Phase:** 1C
**Related:** ADR-003, `docs/phase1c_intake_evals.md`, architecture sections 2.1, 2.2, N01

---

## Context

Phase 1B established that model output is an untrusted candidate until
deterministic provenance validation succeeds. It closed most of the gap, and
documented one that remained:

> A real anchor may exist while the model's narrative summary is subtly wrong.

Concretely:

```text
Student wrote:  "The system detects smoke using optical measurements."
Model returned: value  = "The system predicts fire before smoke appears"
                excerpt = "The system detects smoke using optical measurements."
```

The excerpt verifies — it is a genuine, exact quote. Phase 1B then stored the
model's **value** as canonical. So a project that detects smoke became a project
that predicts fire, with perfect provenance attached to the distortion.

This is worse than an obvious hallucination. A fabricated sensor is caught by
anchor verification. A fabricated *meaning*, wrapped in a real quote, passes
every check and arrives in canonical state carrying a provenance record that
makes it look verified.

Phase 1B mitigated this for atomic terms (`VERBATIM_TERM` containment rejects
"YOLOv8" anchored to "uses a camera") but left narrative fields —
`problem_statement`, `solution_description`, and the newly added `goal`,
`student_contribution`, `current_stage`, `prototype_status` — accepting any
summary. Those are exactly the fields that later novelty, gap and methodology
reasoning will read.

---

## Decision

> **For canonical factual narrative fields, the accepted value is the verified
> source span. The LLM locates it; it does not write it.**

Mechanically:

1. A new shared vocabulary, `ExtractionMode`, replaces the two-member
   `FieldKind`:

   | Mode | Canonical value | Used for |
   |---|---|---|
   | `VERBATIM_SPAN` | the verified excerpt | narrative factual fields |
   | `VERBATIM_TERM` | the value, every token of which must appear in the excerpt | named terms, numbers |
   | `CLASSIFICATION` | an inferred label | project type, domain |
   | `STUDENT_CLAIM` | the student's own words | attributed assertions |

2. Every factual narrative field is `VERBATIM_SPAN`. On acceptance the
   candidate's `value` is **discarded as canonical** and replaced by
   `excerpt.strip()`.

3. The model's phrasing is not thrown away — it is retained as
   `VerifiedField.model_summary`, explicitly labelled derived. It is available
   for debugging and for future search or presentation, and it can never
   overwrite the student's wording.

4. Student claims follow the same rule: `VerifiedClaim.statement` is the
   verified excerpt, because attributing a paraphrase to a student misquotes
   them. The model's rendering is kept as `model_summary`.

5. A field arriving under an unsupported mode is rejected with
   `UNSUPPORTED_EXTRACTION_MODE` rather than quietly reinterpreted.

---

## Consequences

**Positive**

* The residual Phase 1B hallucination channel is closed for canonical factual
  fields: there is no longer a position in which a model sentence becomes a
  project fact.
* Provenance becomes exact rather than approximate. The stored value *is* the
  quoted span, so "where did this come from?" resolves to a character range that
  contains the answer verbatim.
* Arabic and mixed-language submissions benefit disproportionately: the student's
  exact wording survives with no translation or normalization pressure.
* The rule is testable. Gold cases INTAKE-026, INTAKE-027 and INTAKE-068 script a
  model that paraphrases wrongly and assert the span wins.

**Negative / accepted costs**

* **Canonical values are less tidy.** `problem.statement` may read
  "helps visually impaired users avoid obstacles" — a sentence fragment lifted
  from context — rather than a clean summary. A presentation layer that wants
  polished prose must derive it, and label it derived.
* **Span selection quality now matters more.** The model's remaining job is
  choosing *which* span to quote, and a badly chosen span yields a technically
  true but unhelpful canonical value. That is a recall and usefulness problem,
  not a truth problem, which is the trade we want.
* `model_summary` is stored but not yet consumed anywhere. It is deliberate
  headroom, and currently dead weight.
* Multiple spans about one field cannot be merged into a single fluent statement;
  the first verified span wins and a second different span conflicts.

---

## Rejected alternatives

**Keep free summaries and measure the damage in evals.** Measurement is
necessary but not sufficient: an eval tells you the rate at which meaning was
distorted, it does not prevent any individual distortion from reaching the
report. Given the choice between detecting the problem and not having it, not
having it is better.

**Require the model to quote entire paragraphs as the value.** This is what
`VERBATIM_SPAN` achieves without asking the model to do anything unnatural — it
supplies a normal excerpt, and code promotes it.

**Semantic entailment checking (NLI) between value and excerpt.** This would
allow good summaries while rejecting bad ones, which is the ideal. It also means
a second model in the trust path, judging the first — non-deterministic,
unauditable, and itself capable of error. Not acceptable inside a boundary whose
whole purpose is determinism. It remains a candidate for a *reporting* layer.

**Storing only the offsets and resolving text lazily.** Compact, but it makes the
canonical state unreadable on its own and couples every consumer to the artifact
store. Provenance already records the ranges; the text is stored too.

---

## Remaining limitation

The span is guaranteed to be the student's words. It is **not** guaranteed to be
the *right* words for the field: a model can anchor a real but irrelevant
sentence to `goal`. Deterministic code cannot detect that without semantic
judgement.

What this ADR changes is the severity. The failure mode is no longer "the system
asserts something the student never said"; it is "the system quoted the student
accurately but filed the quote under the wrong heading" — visible on inspection,
correctable, and never a fabrication.

The Gold dataset measures the first class of error at zero. The second is
tracked as a documented limitation.
