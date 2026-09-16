# ADR-012 — Evidence extraction does not support claims

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2C (Trusted Evidence Extraction)
**Related:** `docs/phase2c_evidence_extraction.md`, ADR-007, ADR-010, ADR-011, architecture 2.2, 7.2, 7.3, N13, 21

---

## Context

ADR-007 and ADR-010 each drew a line one step earlier in the same chain: a
search result is not a verified source, and a verified source is not evidence.
Phase 2C sits at the last of those lines, and it is the one most likely to be
crossed by accident, because at this point the system is holding two things at
once:

```text
ClaimRecord:      "our detector improves recall by 40%"
ExtractedEvidence: "The model did not improve recall over the strong baseline (p = 0.42)."
```

Those two strings are in memory in the same process, and the canonical
`EvidenceRecord` already has a `support_direction` field with a `CONTRADICTS`
member. Setting it would be one line, would look obviously correct, and would be
wrong for reasons that only surface much later.

**Relevance is not support.** The excerpt is about a different detector, on a
different dataset, in a different deployment. Whether it bears on the student's
claim is a judgement requiring the project's own context — exactly the judgement
a later phase exists to make carefully.

**One excerpt is not sufficiency.** A claim contradicted by one abstract and
supported by three others is not "contradicted". Sufficiency is a property of
the evidence *set*, and the set does not exist yet while extraction is still
running source by source.

**Source weight has not been assessed.** The excerpt might come from a retracted
paper or a preprint. Phase 2C records those flags precisely so a later stage can
weigh them; deciding support here would use them at the moment they are least
understood.

**The trust gate would be bypassed.** `INVENTED_OR_UNVERIFIED_CITATION` and the
claim-status machinery exist to stop a claim being marked supported without a
properly assessed evidence chain. Evidence that arrives already labelled
`SUPPORTS` presents as having passed a check that never ran.

There is also an ownership question. A canonical `EvidenceRecord` must reference
a `SourceRecord` inside `ProjectState.sources`, and Phase 2B deliberately keeps
verified academic sources on the `ResearchRun` instead (ADR-010). Writing Phase
2C output into `ProjectState.evidence` would therefore have required either
breaking referential integrity or moving source ownership.

---

## Decision

> **Phase 2C extracts and verifies evidence provenance. Claim support,
> contradiction and sufficiency are separate later decisions.**

1. **Extracted evidence lives on the `ResearchRun`**, as
   `ResearchRun.evidence_extraction`, not in `ProjectState.evidence`. This
   preserves both Phase 0 referential integrity and the Phase 2B source-ownership
   decision, neither of which is weakened. `ProjectState` is byte-identical
   before and after.
2. **The contracts cannot express a claim relationship.** `ExtractedEvidence`,
   `EvidenceCandidate` and the model-facing DTO have no `support_direction`, no
   `strength`, no `claim_id`, no `supports_claim` and no `claim_status`. The
   forbidden statement is *unrepresentable*, which is a stronger guarantee than
   leaving a field unset.
3. **The prompt forbids the judgement**, and the DTO gives the model nowhere to
   put one even if the source text asks it to.
4. **Claims are snapshotted and compared.** Claim ids, text, statuses, evidence
   links and counter-evidence links are identical before and after; any change is
   release-blocking.
5. **No score, no novelty conclusion, no gap conclusion, no trust-gate change.**
   Each is checked independently.
6. **A promotion boundary is documented rather than implemented:**

   ```text
   ExtractedEvidence  ->  [LATER REVIEWED PHASE]  ->  Supported / Contradicted / Insufficient
                          Claim-Evidence Alignment
   ```

---

## Rejected alternatives

**Setting `support_direction` while extracting.** Rejected: it decides relevance
and sufficiency at the moment the system knows least, and it does so invisibly.

**Writing into `ProjectState.evidence` and adding the academic sources to
`ProjectState.sources` to satisfy referential integrity.** Rejected: it silently
reverses the Phase 2B ownership decision and mutates canonical state during a
research phase, breaking two standing guarantees to gain nothing Phase 2C needs.

**Reusing the canonical `EvidenceRecord` on the research run.** Rejected on two
counts: its `evidence_id` is the `E-\d{3,}` per-project sequence, which is not
globally unique across research runs — the same defect Phase 2A.1 fixed for
`source_id` — and it carries the very claim-relational fields this ADR exists to
exclude.

**A "provisional" support field to be confirmed later.** Rejected: a provisional
judgement is read as a judgement by everything downstream, and nothing forces
the confirmation step to happen.

---

## Consequences

**Positive**

* Relevance, sufficiency and source weight stay one explicit, reviewable stage.
* `ProjectState`, claims, scores and the trust gate are provably untouched.
* Phase 2B's source ownership and Phase 0's referential integrity both hold
  unchanged.
* A later phase receives evidence with its integrity flags and provenance
  intact, rather than a verdict it has to unpick.

**Negative / accepted costs**

* **Phase 2C produces nothing the claim engine or scorer can consume yet.**
  Verified evidence sits on the `ResearchRun` waiting for a stage that does not
  exist.
* Two evidence shapes now exist — canonical `EvidenceRecord` and research-layer
  `ExtractedEvidence` — and the promotion between them is unwritten work.
* Someone reading the code may reasonably ask why evidence is not "in the
  project"; the answer is this ADR, and it needs to stay discoverable.
