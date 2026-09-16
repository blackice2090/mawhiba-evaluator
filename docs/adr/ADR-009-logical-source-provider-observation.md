# ADR-009 — One logical source, every provider observation

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2B (Academic Research Connectors)
**Related:** `docs/phase2b_academic_research_connectors.md`, ADR-007, ADR-008, ADR-010, `docs/phase2a1_hardening.md` §7, architecture N07

---

## Context

Three providers searching one question return overlapping results. The same
paper arrives as a Consensus record with a DOI, an OpenAlex work with a DOI, a
PubMed id and a work id, and a Semantic Scholar paper with a DOI, an arXiv id
and a paper id. Reported as three sources, one paper looks like three
independent pieces of prior art — which would directly distort a novelty
judgement.

So the records have to be deduplicated. The obvious implementation keeps the
first record and drops the rest. That loses three things that matter:

* **Independent confirmation.** Three providers returning one DOI is a
  materially stronger retrieval signal than one provider returning it, and the
  system should be able to say which providers those were.
* **Complementary metadata.** OpenAlex states retraction status; Semantic
  Scholar carries the arXiv id; Consensus carries its own relevance. Whichever
  record happens to arrive first decides what is known about the paper.
* **Disagreement.** When two providers state different publication years, a
  first-wins merge silently picks one. The disagreement is itself information —
  at least one record is wrong.

Deduplication also has to decide what *identity* means. Titles are the tempting
key because every record has one, and they are the one key that cannot be
trusted: distinct papers share titles, and one paper appears under variant
titles across providers.

---

## Decision

> **Cross-provider deduplication creates one logical source while preserving
> every provider observation and provider-specific metadata.**

1. **Identity is a strong identifier, never a title.** Candidates join a group
   when they share a DOI, PMID, OpenAlex id, Semantic Scholar id, arXiv id or
   canonical URL, in that priority order. `SourceIdentifierKind` has no title
   member, so title-based identity is not expressible.
2. **A conflicting identifier blocks a merge.** If two candidates share an arXiv
   id but state different DOIs, they are not merged. At least one record is
   wrong, and choosing between them would be a guess.
3. **With no shared identifier, both candidates survive.** A duplicate that
   survives is a cosmetic problem; a wrong merge fuses two works and corrupts
   every later judgement about either of them.
4. **Every member becomes a `ProviderObservation`** on the logical source,
   carrying that provider's record id, URL, identifiers, title, year, type,
   rank, relevance, citation count and retrieval time.
5. **Metadata merges conservatively.** Missing fields are filled from another
   provider; disagreeing fields are left unknown and recorded as a
   `MetadataConflict` holding every provider's reading. Two documented
   exceptions: a title is required so the primary observation's title is kept
   alongside the conflict, and retraction is sticky-true.
6. **Citation counts never merge.** They are stored as
   `CitationObservation(provider, count, retrieved_at)` — a provider's reading at
   a moment, not a property of the work.

---

## Rejected design

```text
first provider wins
```

Rejected because it destroys provenance and may discard useful metadata or
disagreement:

* the system can no longer answer "which providers independently returned this
  source?", so the strongest available retrieval signal is gone;
* a field the first provider left blank stays blank even though another provider
  supplied it;
* a contradiction between providers is resolved by arrival order, which is not a
  reason;
* the choice is invisible afterwards — nothing records that there was ever a
  second reading.

**Also rejected: deduplicating on a normalized title**, for the reasons above.
**Also rejected: merging citation counts into a maximum or an average**, which
produces a number no provider ever reported, at no particular time.

---

## Consequences

**Positive**

* "Which providers found this source, under which query, at which rank?" is
  answerable from stored data.
* A disagreement between providers is visible rather than silently resolved, and
  the merged field honestly reads unknown.
* A retraction reported by a single provider survives the merge.
* Provider-specific and time-sensitive metadata stays attributed.

**Negative / accepted costs**

* Duplicate logical sources when no provider supplies a shared identifier. This
  is the deliberate direction of the error.
* A merged record has more unknown fields than a first-wins record would, since
  disagreement blanks a field instead of choosing.
* The stored payload is larger: one logical source keeps up to three full
  observations plus its conflicts.
* Sticky-true retraction can flag a paper on one provider's say-so. Kept,
  because the opposite error — a retracted paper reading clean — is worse, and
  the conflict record makes the basis inspectable.
