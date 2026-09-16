# ADR-013 — Abstract and full text are different evidence scopes

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2C (Trusted Evidence Extraction)
**Related:** `docs/phase2c_evidence_extraction.md`, ADR-010, ADR-011, ADR-012, architecture 11, 21

---

## Context

Phase 2C's production evidence comes from **abstracts**, because that is the
only source text Phase 2B actually retrieves. Abstracts are genuine source
content — the authors' own words — and an exact excerpt from one is properly
verified evidence under ADR-011.

But an abstract is not the paper, and the gap matters in specific, known ways:

* **An abstract is written to attract readers.** Positive findings are
  foregrounded; caveats, failed conditions and negative secondary results are
  frequently omitted entirely.
* **Method detail is absent.** Sample construction, controls, ablations and
  statistical procedure live in the body. An abstract's "we evaluated on
  greenhouse imagery" cannot tell you whether the evaluation was sound.
* **Limitations are systematically under-reported.** A Limitations section may
  say the opposite of what the abstract implies.

So a finding quoted from an abstract carries less evidentiary weight than the
same sentence quoted from Results, and considerably less than a finding drawn
from reading the whole paper. The verification is identical — an exact span in a
hashed snapshot — but what the evidence *licenses* is not.

If the record does not carry that distinction, a later phase cannot recover it.
Nothing about the excerpt's text says which part of the document it came from,
and a novelty or claim-support stage reading a bare excerpt would treat
abstract-only material as full-text-verified.

Phase 2C also has to avoid the opposite error: if scope is baked in implicitly
by assuming everything is an abstract, then adding full-text later would require
re-identifying every stored item.

---

## Decision

> **Evidence extracted from an abstract must remain explicitly abstract-scoped
> and may not be represented as full-text-verified evidence.**

1. **Content kind is recorded on the snapshot**, not inferred:
   `ABSTRACT`, `PARTIAL_TEXT`, `FULL_TEXT`. `METADATA_ONLY` exists as a *state*
   and can never be a snapshot — a validator refuses to construct one, so
   metadata has no path to becoming evidence.
2. **Scope travels with every evidence item.** `EvidenceScope` is
   `ABSTRACT_ONLY`, `PARTIAL_TEXT` or `FULL_TEXT`, and a validator enforces the
   mapping from content kind. Abstract content carrying `FULL_TEXT` scope raises.
3. **Scope is a usability ceiling, not a strength rating.** Phase 2C assigns no
   evidentiary weight (ADR-012). It records what the evidence rests on; a later
   phase decides what that is worth.
4. **The contracts are full-text-ready now.** Adding `PARTIAL_TEXT` or
   `FULL_TEXT` later changes no evidence identity: identity is
   `(source_id, content_hash, verified span, evidence_type)`, so richer content
   produces additional snapshots and additional evidence rather than
   invalidating what exists.
5. **Phase 2C does not acquire full text.** No PDF download, no scraping, no
   OCR, no paywall circumvention (ADR-010, §25 of the execution spec).

---

## Rejected alternatives

**Treating abstract evidence as ordinary evidence.** Rejected: it silently
inflates confidence, and the loss is unrecoverable because the excerpt's text
does not reveal its provenance within the document.

**Refusing to extract from abstracts until full text is available.** Rejected:
it would leave Phase 2C with nothing to do and no path to test the extraction
and verification machinery against real content. Abstract-scoped evidence is
genuinely useful for prior-art discovery and for locating relevant work; the
requirement is that it be labelled, not that it be withheld.

**A numeric confidence attached at extraction.** Rejected: it is an evidentiary
weight judgement, which ADR-012 places in a later phase, and a number invites
arithmetic that a scope label does not.

**Storing the section name instead of a scope enum.** Rejected as the primary
mechanism: a free-text section label from a provider is not a closed vocabulary
and cannot be validated. `section_hint` is kept as supplementary metadata.

---

## Consequences

**Positive**

* A later phase can weigh abstract-only findings differently, because it can
  tell which they are.
* The distinction is enforced by a validator, not by convention.
* Full-text arrives later without a migration: identity semantics are unchanged.
* Metadata-only sources are structurally excluded from producing evidence.

**Negative / accepted costs**

* **Production evidence in Phase 2C is abstract-only**, so coverage of
  limitations and methodology is systematically thin — the abstract's own bias
  is inherited by the evidence base.
* A source whose abstract is unavailable yields no evidence at all, even when
  the paper is highly relevant.
* Every consumer now has to handle scope, including consumers that would
  happily have ignored it.
* Two sources agreeing in their abstracts may still disagree in their bodies,
  and Phase 2C cannot see that.
