# ADR-019: Product and Open-Source Search Candidates Are Discovery Artifacts, Not Novelty Conclusions

## Status

Accepted (Phase 2H). Builds on ADR-006 (retrieval is not evidence), ADR-008
(provider isolation), ADR-009 (identity from strong identifiers only),
ADR-010 (research output lives on the `ResearchRun`) and ADR-018 (patent
candidates are research artifacts). Amends none of them.

## Context

Phase 2H extends prior-art discovery beyond patents to commercial products and
public open-source repositories. Both surfaces invite over-reading even more
than patents do, because their metadata is noisier and more abundant:

- a search hit reads as a product that exists;
- a snippet reads as what the manufacturer says;
- a marketplace listing reads as the manufacturer;
- twelve listings read as twelve products;
- two pages with the same title read as one product;
- ten code-search hits read as ten implementations;
- a fork reads as an independent implementation;
- a repository called `x-fork` reads as a fork of `x`;
- a repository's `created_at` reads as "public since";
- an old commit date reads as "publicly available since";
- a license reads as permission to reuse;
- a star count or a search rank reads as relevance, or worse, novelty;
- a dated artifact before the cutoff reads as "prior art that destroys novelty".

Every one of those is wrong. Several are legal or plagiarism conclusions this
system is not entitled to draw at all.

## Decision

**Two typed subruns on the `ResearchRun`.** `product_prior_art:
ProductPriorArtRun` and `open_source_prior_art: OpenSourcePriorArtRun`, never
in `ProjectState`, never flattened into one generic record. Shared discovery
vocabulary (purposes, error kinds, coverage, budget, provider honesty, cutoff,
universal limitations) lives once in `src/schemas/discovery.py`.

**Observation is not artifact; hit is not repository.** A web-search result is
a `ProductSearchObservation`. It becomes a `ProductSourceArtifact` only when the
page itself is fetched through the SSRF-safe fetcher, hashed and bounded. A
repository- or code-search hit is a `RepositoryObservation`; it becomes a
`VerifiedRepository` only when provider metadata for the *same numeric id* is
retrieved. Without a fetcher or a provider, hits stay observations.

**Source role from reviewed configuration only.** `FIRST_PARTY_*` requires a
reviewer-supplied `VendorDomain` for the page's final host. Title text, a
`brand` field or "official site" wording is never proof. Marketplace, review
and directory roles come from small host lists matched exactly or as a
dot-delimited subdomain (so `amazon.com.evil.io` is not Amazon). Everything else
is `UNKNOWN`, and unknown stays unknown.

**Strong product identity collapses; weak identity links.** Artifacts join one
`ProductEntity` only on a strong key read from the page's own structured data
(a GTIN with a valid check digit, an app package id, or an MPN/model number
qualified by a stated brand) or on byte-identical content. A shared retailer
SKU, the same stated brand and product name, or an unqualified model number is
a *probable link* between entities that stay separate. Two different keys of
the same kind in one group are ambiguous and never merge on identifiers. One
strong key is one entity, enforced by the run validator. The run reports an
upper bound (entities) and a lower bound (probable-link clusters):
`more listings != more products`.

**Stable repository identity.** `repository_key = "github:<numeric id>"`.
`owner/name` is mutable: every observed name is kept, a rename is one
repository with two names, and a name that now resolves to a different id is
recorded as an identity mismatch, never silently swapped.

**Provider-declared lineage only.** `fork` + `source`/`parent`, `mirror_url`
and `template_repository` decide `FORK`, `MIRROR` and `TEMPLATE_DERIVATIVE`.
Names never do. Networks are keyed on the stable root id; every member is kept
and gets its own candidate (forks may diverge), but only a `ROOT_REPOSITORY`
root counts as an independent root. Mirror networks never do.

**Chronology is descriptive.** Product dates (page published, vendor launch,
vendor availability, marketplace listing, search-provider date, retrieval date)
and repository dates (created, updated, pushed, release created/published,
commit authored/committed, retrieval) stay separate. A cutoff qualification
records the field it used. The retrieval date and the search-provider date are
never used. Every product date is source-reported, and no repository date
proves public availability; the candidate says so.

**Bounded, honest search.** Every query, page, execution, refusal and cut-off
is recorded. Coverage is one of `COMPLETE_WITHIN_CONFIGURED_BOUNDS`,
`PARTIAL_PROVIDER_LIMIT`, `PARTIAL_ERROR`, `BLOCKED_AUTH` and `NOT_EXECUTED`,
and the contract refuses complete coverage over any truncation, failure or
provider-reported remainder. Any stage that truncates downgrades coverage.

**Provider honesty.** GitHub, Brave and the safe fetcher are
`IMPLEMENTED_DOCUMENTED_ONLY`: contracts verified from official documentation
on 2026-10-01, with no live request observed. `IMPLEMENTED_AND_LIVE_VERIFIED`
is valid only with an observed live request. Code search is declared
authenticated-only and is refused at plan and dispatch time without credentials.
Credentials live on the connector instance only.

**Candidates, not conclusions.** `ProductPriorArtCandidate` and
`OpenSourcePriorArtCandidate` carry the universal limitations
(`NOVELTY_NOT_ASSESSED`, `SAME_INVENTION_NOT_DETERMINED`,
`LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED`, `BOUNDED_SEARCH_NOT_EXHAUSTIVE`,
`LATER_NOVELTY_COMPARISON_REQUIRED`, `NO_COPYING_DETERMINATION`) by validator.
They have no field that could hold a novelty score, a same-invention verdict, a
copying or plagiarism finding, a legal, patentability, infringement or FTO
conclusion, or a project-score effect. `extra="forbid"` refuses adding one.
Rank, stars, forks and watchers are metadata and never enter a candidate's
judgement fields.

## Consequences

- A later novelty/differentiation phase can consume patent, product and OSS
  candidates while preserving each type's identity and date semantics.
- Product identity is often `UNRESOLVED_IDENTITY`. That is the honest default
  for pages without structured identifiers.
- The SSRF check resolves names before connecting. A DNS answer that changes
  between check and connect (DNS rebinding) is not fully closed by this layer
  alone. This is documented as a remaining limitation.
- Forks are grouped for counting but preserved for inspection, because grouping
  is a counting rule, not a claim that the code is identical.

## Rejected alternatives

- **Merge on title or description similarity.** Fuzzy matching inflates and
  deflates counts unpredictably and cannot be audited. Rejected.
- **Infer first-party from page text or a brand field.** Anyone can write a
  vendor's name. Rejected.
- **Use `owner/name` as identity.** It is mutable and reusable. Rejected.
- **Infer forks from names.** Rejected. Provider-declared relations only.
- **Use `created_at` or commit dates as "public since".** Visibility can change.
  Rejected.
- **One generic "prior-art candidate" type for patents, products and repos.**
  It would flatten identity and date semantics into the weakest common form.
  Rejected.
- **A model-assisted relevance or similarity score.** That is novelty
  assessment by another name, and it belongs to a later reviewed phase. Rejected.
