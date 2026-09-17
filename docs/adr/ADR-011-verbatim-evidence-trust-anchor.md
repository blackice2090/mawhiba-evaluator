# ADR-011 — A verbatim excerpt is the evidence trust anchor

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2C (Trusted Evidence Extraction)
**Related:** `docs/phase2c_evidence_extraction.md`, ADR-003, ADR-004, ADR-012, ADR-013, architecture 2.1, 2.2, 7.2, N06A

---

## Context

Phase 2C is the first time a language model is asked to read a *third party's*
text and report what it says. Phase 1B faced the same shape of problem with a
student's submission and answered it with anchor verification. The academic case
is harder in one specific way: the source text is far more fluent than a student
submission, and a model summarising it produces output that reads exactly like a
quotation.

The tempting implementation stores what the model returned:

```python
EvidenceRecord(statement=item.summary, source_id=source.id, verified=True)
```

That is wrong in a way no amount of downstream care recovers from, because the
failure is silent and the artefact is convincing. Three concrete failure modes,
all observed behaviour of good models:

**Strengthening.** A source says "may reduce latency in some configurations". A
summary says "reduces latency". Nothing in the stored record shows the hedge was
dropped, and a later novelty or claim-support stage sees a firm finding.

**Negation loss.** "The model did not improve recall" becomes "recall
improvement was limited" or, worse, "the model improved recall". This is the
single most damaging paraphrase error available, because it inverts the meaning
while preserving every keyword.

**Fluent fabrication.** A model asked for evidence about a topic the abstract
does not cover will sometimes produce a plausible sentence that is not in the
text at all. It will be well-formed, on-topic, and completely invented.

A fourth problem is subtler: even when a model quotes correctly, it miscounts
offsets. A stored `start`/`end` that the model supplied *looks* like verified
provenance while pointing at the wrong place, which is worse than having no
offsets at all.

---

## Decision

> **Every accepted evidence item must be anchored by an exact excerpt verified
> against a versioned source content snapshot.**

Implemented so that the guarantee is structural rather than procedural:

1. **The stored excerpt is sliced from the snapshot by code.**
   `ExtractedEvidence.excerpt` is always `snapshot.text[start:end]`. There is no
   code path that stores the model's string. "Verbatim" is therefore true by
   construction, not by review.
2. **Code locates the text; the model never does.** Verification searches the
   snapshot itself and derives the offsets. A model-supplied offset is used for
   exactly one narrow purpose — choosing between occurrences that code has
   *already* proven are exact matches — and never to find text.
3. **A validator enforces the span.** `len(excerpt) == end - start`, and
   `end > start`, checked on the contract.
4. **Ambiguity is refused.** One sentence appearing twice with nothing
   deterministic to separate the occurrences yields `AMBIGUOUS_SPAN`. Taking the
   first would produce evidence pointing somewhere the model may not have meant.
5. **Tolerance is limited to transport noise (tightened in Phase 2C.1).**
   Only CRLF/LF line-ending differences and whitespace-run/line-break
   differences may vary between excerpt and source. Typographic quote and
   dash variants, minus signs, scientific symbols, digits, decimal
   separators, units, comparison operators and negation are never folded or
   equated — a candidate that only matches after such a substitution is
   rejected as `EXCERPT_NOT_FOUND`, not accepted. Trust prefers rejection
   over an uncertain match. Nothing folds case, strips negation, normalizes
   digits or touches units — and the accepted excerpt is still the
   snapshot's own text, so tolerance affects the *search*, never the result.
6. **Numbers are re-checked against the verified excerpt.** A stated value must
   appear as written, and a unit must appear as its own token, so 92.3% cannot
   become 93.2% and 5 ms cannot become 5 s.
7. **The model's wording survives only as `candidate_interpretation`**,
   explicitly advisory, never the evidence and never a claim.

---

## Rejected design

```text
LLM paraphrase as evidence
```

Rejected because it destroys the one property that makes evidence auditable:

* **"Why did you say that?" stops being answerable.** The chain
  claim → evidence → source reads as confirmed while the middle link is
  something a model wrote.
* **Strengthening and negation loss are undetectable after the fact.** Once the
  paraphrase is stored, no later stage can tell it apart from a faithful one.
* **Fabrication is indistinguishable from quotation.** Both are fluent sentences
  attached to a real source id.
* **It would contradict Phase 1B.** Intake already refuses to let a paraphrase
  become a canonical value (ADR-004). Accepting one here would mean the system
  trusts a model more about someone else's paper than about the student's own
  words.

**Also rejected: semantic-faithfulness scoring of the paraphrase.** A model
judging whether another model's summary is faithful is not deterministic
verification, and a confident wrong judgement reintroduces the whole problem
with an extra layer of false assurance. §22 permits an interpretation only as
untrusted advisory metadata, which is what this ADR stores.

**Also rejected: trusting model offsets.** Cheaper, and wrong for the reason
above — a precise-looking offset is worse than none.

---

## Consequences

**Positive**

* An accepted excerpt provably exists in a hashed snapshot, at known offsets.
* Negation, hedging, units and statistical qualifiers survive intact, because
  the text is never rewritten.
* A hallucinated quote cannot be accepted, whatever the model's confidence.
* The same anchor discipline now runs from intake through to evidence.

**Negative / accepted costs**

* **Recall is lower.** A model that paraphrases slightly loses that evidence
  entirely rather than having it repaired. This is the deliberate direction of
  the error.
* A genuinely repeated sentence is refused rather than attributed, even when a
  human could guess which occurrence was meant.
* Evidence is limited to what the source literally says, so a finding spread
  across two sentences must be captured as two items or not at all.
* Storing offsets and hashes makes the payload larger than storing summaries.
