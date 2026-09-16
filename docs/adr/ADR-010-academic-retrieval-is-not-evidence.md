# ADR-010 — Academic retrieval stops at verified source metadata

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2B (Academic Research Connectors)
**Related:** `docs/phase2b_academic_research_connectors.md`, ADR-007, ADR-008, ADR-009, architecture 2.2, 11, 21, N06A, N07

---

## Context

ADR-007 established the boundary for Phase 2A's official web retrieval: a search
result is not evidence. Phase 2B is where that boundary is genuinely tested,
because academic records *look* like evidence in a way official pages never did.

A normalized Semantic Scholar record has a title, an abstract, authors, a
venue, a year, a DOI and a citation count. It is trivially available at exactly
the moment the code is holding a `ClaimRecord` that says "97% accuracy", and the
abstract frequently contains a number. Writing

```text
EvidenceRecord(source_id=..., statement=abstract, verified=True)
```

is a three-line change that would appear to work immediately.

It would be wrong at four separate steps, each of which can fail on its own:

```text
a provider returned this record          retrieval
the record describes a real work         bibliographic verification
that work states X, at location L        evidence extraction
X supports or contradicts claim C        claim support
```

A verified DOI proves the second. It says nothing about the third or fourth. An
abstract is a summary written to attract readers, not a located quotation, and
the Phase 1B/1C trust model is built on the principle that a statement is
evidence only when a verbatim span at a known location can be shown.

There is also a quality temptation. A high citation count, an open-access flag
and a journal venue are all available at merge time, and turning them into a
`SourceQuality` or a `SourceTier` would produce plausible numbers immediately.
They would be numbers about popularity and metadata completeness, presented as
numbers about methodological strength.

---

## Decision

> **Academic retrieval and bibliographic verification stop at verified source
> metadata. Scientific evidence extraction and claim support are separate later
> phases.**

Phase 2B creates:

```text
AcademicSourceCandidate      one provider's untrusted record
LogicalAcademicSource        one work, VERIFIED_METADATA, every observation kept
SourceRecord                 the Phase 0 contract, Tier UNRATED, quality unset
ProviderObservation          which provider said what, under which query
AcademicRetrievalResult      coverage, budgets, ledgers, provider outcomes
```

Phase 2B does **not** create:

```text
EvidenceRecord
a SUPPORTED or VERIFIED ClaimRecord
a novelty conclusion
a research gap conclusion
a score
a readiness classification
```

Enforced by:

1. `verification_status` on a logical source can only be `VERIFIED_METADATA`; a
   validator refuses `VERIFIED_FULL_TEXT`, because Phase 2B never reads full
   text.
2. No module under `src/research/academic`, `src/graph/academic_nodes.py`,
   `src/graph/phase2b_graph.py` or `src/schemas/academic.py` imports or
   constructs `EvidenceRecord`. A test enforces it.
3. An abstract is stored as provider metadata and is never a claim-support
   statement. Consensus's synthesized text is stored only as provider-generated
   secondary metadata and never becomes a paper's abstract.
4. `SourceRecord.tier` stays `UNRATED` and `SourceQuality` stays at its default.
   `peer_review_status` is set only where the publication form states it —
   `PREPRINT` implies not peer reviewed, the journal/conference/review family
   implies peer reviewed, everything else stays `UNKNOWN`.
5. No full-text download, no PDF extraction, no OCR, no paywall circumvention.
6. The academic branch makes no model call at all, so no model can be talked
   into summarizing a paper into a conclusion.
7. A release-blocking eval metric counts evidence creation and claim mutation,
   with negative controls proving the metric fires.

---

## Rejected alternatives

**Abstract as evidence.** Rejected: an abstract is a promotional summary without
a located span. Claim support needs a quotation at a known location that a human
can check, which requires full text.

**Citation count as source quality.** Rejected: it measures attention, is
provider-specific, is time-sensitive, and correlates with field size and paper
age far more than with methodological strength. Stored as an attributed,
time-stamped observation instead.

**Provider presence as peer review.** Rejected: OpenAlex and Semantic Scholar
index preprints, theses, reports and datasets. Being in an academic index proves
indexing.

**Excluding preprints and retracted papers at retrieval.** Rejected in both
directions. A preprint can be the closest prior art and must be retrievable
while remaining distinguishable. A retracted paper is exactly what a novelty
review needs to see, and dropping it silently would hide the most important
fact about it.

---

## Consequences

**Positive**

* The four failure modes stay separately visible and separately testable.
* An evaluation can say "we found and verified this paper" without implying
  anything about what it shows.
* Retraction, preprint status and metadata disagreement reach the later phase
  intact, where they change how much weight a source can carry.
* The trust gate keeps working: nothing arrives pre-labelled as verified
  evidence.

**Negative / accepted costs**

* Phase 2B produces nothing the scoring engine can consume yet. Verified sources
  sit on the `ResearchRun` waiting for a stage that does not exist.
* More types and more steps before anything reaches the claim engine.
* Source quality is unpopulated, so any ranking a later phase needs must be
  built deliberately rather than inherited from a citation count.
