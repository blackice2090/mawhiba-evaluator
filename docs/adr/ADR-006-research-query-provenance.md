# ADR-006 — Every research query is traceable to canonical ProjectState

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2A (Research Foundation)
**Related:** `docs/phase2a_research_foundation.md`, ADR-002, ADR-003, ADR-004, architecture N05, 27, 36

---

## Context

Phase 2A introduces the research query planner: a model reads the canonical
project and writes search queries for academic, patent, product, open-source and
standards providers. Two failure modes follow directly from how language models
write queries.

**Fabricated project facts inside queries.** Asked to research "an AI system for
plant disease", a model will readily search for "ResNet-50 PlantVillage Jetson
Nano", none of which the student wrote. The query then retrieves literature about
a project that does not exist, and every downstream judgement — prior art,
novelty, methodology — is made against the wrong project.

**Search vocabulary leaking back into facts.** Good research needs synonyms and
broader concepts ("object detection" for YOLOv8, "low-power wide-area network"
for LoRa). If that vocabulary is ever stored where facts live, the next reader of
`ProjectState` cannot tell what the student built from what the planner guessed.

A third concern is privacy: a query leaves the system. Anything in it is sent to
a third party.

---

## Decision

> **Every accepted research query must be traceable to trusted canonical
> ProjectState. Generated synonyms and related terminology are search expansions
> only and never become project facts.**

Concretely:

1. The planner reads a **PII-minimized projection** of trusted state only: `KNOWN`
   tracked values, intake-verified lists, the verified classification and
   student-origin claims. UNKNOWN, CONFLICTED and inferred values, model summaries
   and rejected extractions are not inputs.
2. The model returns a candidate plan. Each query declares `source_terms` (each
   with the canonical `field_path` it came from) and, separately,
   `expansion_terms`.
3. Deterministic verification accepts a query only when:
   - every source term's tokens occur in the value of an allowlisted, trusted
     field it names;
   - every source term occurs in the query text;
   - every word of the query is a source-term word, an expansion-term word, or a
     reviewed generic search word (`QUERY_CONNECTOR_TOKENS`);
   - no personal data, injection text or advocacy phrasing is present;
   - branch, purpose, length, budget and duplicate rules hold.
4. `ResearchQuery` and `ResearchRun` live on the graph state, **not** in
   `ProjectState`. No model reachable from `ProjectState` has a field that can hold
   expansion terms; a test walks the type graph to prove it.
5. Query planning is a pure read of `ProjectState`. A release-blocking test and a
   release-blocking eval metric assert the canonical state is byte-identical
   before and after planning.

---

## Rejected alternatives

**Extending the Phase 0 `ResearchQueryRecord`.** It already lives in
`ProjectState.research_queries`. Adding expansion terms to it would put search
vocabulary inside canonical state — the exact leak this ADR exists to prevent. It
remains the execution-log contract for queries that actually run (Phase 2B).

**Trusting the model to label terms honestly.** Labels are produced by the same
process that invents terms. Code must re-derive where each word came from.

**Fuzzy or semantic matching of terms to fields.** "Convolutional network" is
semantically close to "AI"; accepting it would re-admit exactly the fabricated
specificity described above. Containment is strict and deterministic; the model
can always move a related concept into `expansion_terms`, where it is explicitly
not a fact.

**Letting the planner add discovered terms to `ProjectState`.** A term the
planner "discovered" is not something the student said. Canonical intake has one
writer (`src/intake/merge.py`) and research does not become a second one.

---

## Consequences

**Positive**

* "Why did the system search for this?" is answerable from data: purpose, source
  terms, their canonical fields, and explicitly marked expansions.
* A fabricated implementation detail cannot enter a query as a project fact.
* Canonical state cannot be changed by research planning, structurally and by test.
* Queries sent to providers never carry detected student identity.

**Negative / accepted costs**

* **Recall is lower.** A useful query containing an undeclared word is rejected
  rather than repaired. The model can declare the word as an expansion.
* **The connector vocabulary is English-only.** Arabic function words must be
  declared as expansions or omitted.
* **Token containment is not entailment.** A source term can be a real phrase from
  the field and still be a poor choice for the query; that is a quality question,
  not a provenance one.
* **Name detection is token-level** and can reject a legitimate word that equals a
  student's name. Rejection is the safe direction.
