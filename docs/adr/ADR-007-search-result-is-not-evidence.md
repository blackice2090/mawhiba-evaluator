# ADR-007 — A search result is not evidence

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2A (Research Foundation)
**Related:** `docs/phase2a_research_foundation.md`, ADR-003, architecture 2.2, 2.4, N03, N06A, 21

---

## Context

Phase 2A adds the first real retrieval: official Mawhiba competition pages. Phase
2B will add academic, patent, product and open-source connectors. Every one of
them returns "results", and the tempting implementation turns a result straight
into the evidence model the claim engine and trust gate already consume.

That shortcut collapses four different statements into one:

```text
a provider returned this              (search result)
this page/record really is what it says (verified source)
this source states X at location L     (evidence)
X supports or contradicts claim C      (claim support)
```

Each step can fail independently. A search hit can be a spoofed domain, a mirror,
a stale copy or a hallucinated citation. A genuine source can say nothing
relevant. A relevant statement can fail to support the specific claim.

---

## Decision

> **Retrieval produces candidate sources. Verification produces sources.
> Evidence extraction and claim support are separate later stages.**

```text
SEARCH RESULT  ->  SOURCE CANDIDATE  ->  VERIFIED SOURCE  ->  EVIDENCE  ->  CLAIM SUPPORT
                   (SourceCandidate)     (OfficialSourceSnapshot
                                          + SourceRecord)
```

In Phase 2A:

1. A web provider returns an `OfficialRetrievalResult`, which becomes a
   `SourceCandidate`. A candidate is untrusted and is not a source.
2. Deterministic source verification — successful retrieval, HTTPS, exact
   allowlisted host for both the requested and final URL, non-empty content and a
   recomputed content hash — produces an `OfficialSourceSnapshot` and its Phase 0
   `SourceRecord` (`OFFICIAL_COMPETITION_SOURCE`, Tier A).
3. Official requirement extraction yields `OfficialRequirement` records anchored
   to the snapshot text. They describe the competition's rules; they are not
   scientific evidence about the project and do not support any project claim.
4. No Phase 2A code imports or constructs `EvidenceRecord`. A test enforces it.

---

## Rejected architecture

```text
search result -> EvidenceRecord
```

Rejected because it destroys the trust boundary:

* **Provenance becomes decorative.** An `EvidenceRecord` has a `source_id`; if the
  source was never verified, the chain claim -> evidence -> source reads as
  confirmed while resting on an unverified hit.
* **The trust gate is bypassed.** `INVENTED_OR_UNVERIFIED_CITATION` blocks strong
  claims on unverified sources. Evidence minted at retrieval time arrives already
  looking verified.
* **Failure is invisible.** A spoofed or mirrored official page would produce
  official-looking rules with nothing recording that it was never checked.
* **Relevance is conflated with existence.** A real page saying nothing about a
  claim would still have become evidence for it.

---

## Consequences

**Positive**

* Each stage has its own contract, its own failure reasons and its own tests.
* A third-party page can never become an official source, whatever a provider
  returns.
* "Which official rules did this evaluation use?" is answered by
  `(canonical_url, content_hash)` on a verified snapshot.
* Phase 2B connectors inherit the same boundary instead of re-deciding it.

**Negative / accepted costs**

* More types and more steps before anything reaches the claim engine.
* Official sources are recorded on the `ResearchRun`, not yet merged into
  `ProjectState.sources`; that merge is a later, separately reviewed stage.
