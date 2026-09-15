# ADR-003 — LLM output is an untrusted candidate until deterministic validation

**Status:** Accepted
**Date:** 2026-09-13
**Phase:** 1B (Trusted Project Intake)
**Related:** `docs/phase1b_trusted_intake.md`, ADR-001, ADR-002, architecture sections 2.1, 2.2, 2.6, N01, N02

---

## Context

Phase 1B introduces the first LLM call. Everything built so far — the
Zero-Assumption contracts, the claim/evidence rules, the trust gate — exists to
stop the system asserting more than its evidence supports. A model that can write
directly into `ProjectState` would defeat all of it in one step, because every
downstream component *trusts* the canonical state by design.

The failure mode is specific and well documented: a language model asked to
extract structured information will, when information is absent, supply
plausible information instead. Asked about "an AI system for plant disease
detection" it will readily produce a CNN, the PlantVillage dataset and a 95%
accuracy figure — none of which the student wrote. Structured Outputs guarantees
the *shape* of that answer. It guarantees nothing about its truth.

And the consequence is not a bad extraction. It is a fabricated fact that later
flows into novelty assessment, methodology review and scoring, each of which
treats the canonical state as ground truth. Nothing downstream is designed to
catch it.

---

## Decision

> **LLM output is an untrusted candidate extraction until deterministic
> provenance validation and domain merge validation succeed.**

Concretely:

1. The model produces a purpose-built intake DTO (`ProjectExtraction`,
   `ProjectClassification`), never a `ProjectState`, and never a
   `KnowledgeStatus`.
2. Every extracted value must carry a **verbatim excerpt** from the submission.
   The model is never asked for character offsets — it can miscount, and a
   miscounted offset would look like verified provenance. Code derives offsets.
3. `verify_anchor()` — pure, deterministic, no fuzzy or semantic matching —
   must find that excerpt in the student's actual text. Failure means the value
   is ineligible for `KNOWN`.
4. The excerpt must also **support the value**. For concrete terms
   (`VERBATIM_TERM`), every token of the value must appear in the excerpt, which
   rejects a real quote paired with an invented value.
5. Only `VerifiedExtraction` reaches the merge layer, which re-validates the whole
   `ProjectState`.
6. Model confidence is recorded and **never** participates in any accept
   decision.

The trust boundary is a **visible node** in the graph
(`PROJECT_EXTRACTOR_VERIFIER`), not a hidden step inside the extractor, so it can
be inspected, tested and reasoned about on its own.

---

## Rejected alternatives

**Trusting Structured Outputs alone.** Structured Outputs guarantees schema
conformance. A perfectly schema-valid response can state that the project uses
LiDAR when the student never mentioned it. Validating the shape of a claim is not
validating the claim — and conflating the two is exactly the mistake that makes
an evaluation system untrustworthy.

**Letting the model write `ProjectState` directly.** Tempting, because it removes
a mapping layer. It also removes every guarantee: the model would be choosing
`KnowledgeStatus` values, and nothing would stop `KNOWN` being asserted for an
invented value. It would additionally let the model overwrite prior turns, erase
`KNOWN` fields, and write claims, scores and novelty. Deciding what is *known* is
not a language task.

**Treating model confidence as truth.** A confidence score is the model's report
about its own state, produced by the same process that produced the value. A
hallucination frequently arrives with high confidence — a test in this repo
asserts exactly that case is still rejected at 0.99. Confidence is useful for
triage and observability; it is not evidence, and wiring it into the accept
decision would make the trust boundary a function of the thing it is checking.

**Treating student statements as scientific evidence.** "Our model achieved 97%
accuracy" is proof the student *said* that. Writing it into an `EvidenceRecord`
would let an unverified assertion support a `SUPPORTED` claim and eventually a
score, with the provenance chain reading as though something external had
confirmed it. Intake therefore creates claims with `origin=STUDENT` and
`status=UNSUPPORTED`, and creates no evidence and no sources at all.

**Retrying a refusal.** A refusal is a deliberate decision, not a transient
fault. Retrying it costs money and changes nothing, so `REFUSAL` and
`PARSE_ERROR` are never retried while transport faults and truncation are.

---

## Consequences

**Positive**

* A fabricated fact cannot enter canonical state through the intake path.
* Every accepted fact answers "where did this come from?" from the state alone —
  artifact id, verification method, match ranges.
* Rejections are recorded with a reason, so "the model proposed X and we refused
  it" is observable rather than invisible.
* The whole trust layer is testable with no key and no network, because the
  decision logic contains no model call.
* Prior turns are protected: a later extraction cannot erase or silently
  overwrite an established value.

**Negative / accepted costs**

* **Recall is lower than the model could achieve.** A correct extraction with a
  slightly paraphrased excerpt is rejected. This is the intended trade: a false
  UNKNOWN is preferable to a fabricated KNOWN, because the first can be fixed by
  asking the student and the second cannot be detected later.
* **A mapping layer must be maintained** between the intake DTO and
  `ProjectState`. Five verified fields currently have no Phase 0 destination and
  are reported rather than stored.
* **Semantic entailment is not fully proven.** `VERBATIM_TERM` containment closes
  the common gap; `NARRATIVE` fields accept any summary whose anchor exists. This
  residual gap is explicit, documented, and assigned to the evals as a measured
  **unsupported-field acceptance rate**.
* Two model calls per submission instead of one, since classification is
  deliberately separated from extraction.

---

## The limitation that must stay explicit

Exact text provenance proves:

```text
the student said X
```

It does **not** prove:

```text
X is true
```

Phase 1B is therefore the phase in which the system learns **what the student
said** — and explicitly not whether it is scientifically correct. That
distinction is the boundary between this phase and every phase that follows, and
it must not blur: the moment provenance is mistaken for validation, the
"why did you give this judgement?" chain becomes decorative.

Later evals must measure unsupported-field acceptance rate directly, alongside
the citation-integrity and novelty-safety metrics of architecture section 33.
