# ADR-018: Patent Search Candidates Are Research Artifacts, Not Novelty or Legal Conclusions

## Status

Accepted (Phase 2G). Builds on ADR-006 (retrieval is not evidence), ADR-008
(provider isolation), ADR-009 (identity from strong identifiers only) and
ADR-010 (research output lives on the `ResearchRun`). Amends none of them.

## Context

Phase 2G adds the PATENT research branch: a bounded search of patent literature
for documents a later phase should compare against the student's project. The
branch has an unusually sharp failure mode. A patent search result *looks* like
an answer to the question every reader actually cares about -- "is this
invention new?" -- and every piece of patent metadata invites an over-reading:

- a hit reads as a match;
- five hits read as five prior inventions;
- a priority date reads as the day the idea became public;
- a date before the evaluation cutoff reads as "invalidating prior art";
- a provider's ranking reads as a similarity or novelty score;
- a shared CPC class reads as "the same invention";
- a finished search reads as "nothing else exists".

Each of those is wrong, several are legal conclusions this system is not
competent to draw, and none can be caught downstream once the data model has
let it be expressed. So the decision below is about what the contracts make
**unrepresentable**, not about what documentation discourages.

## Decision

A Phase 2G output is a `PatentPriorArtCandidate`: *a patent document that a
bounded, provenance-recorded search surfaced, whose bibliographic metadata was
verified, which has been placed in its patent family and on a date line, and
which a later phase should compare against the project.* Nothing more.

### 1. Search observation vs verified publication

Provider XML is untrusted. It becomes a `PatentSearchObservation` -- one
provider's record of one document -- and only deterministic verification turns
observations into a `VerifiedPatentPublication`: well-formed identity, parseable
and possible chronology, well-formed classifications, traceable to a query of
this run. A malformed record, an impossible date order or a record from another
run is refused with a named reason on the rejection ledger. *Verified* means
bibliographically verified; it says nothing about what the patent discloses.

### 2. Publication identity vs family identity

A publication is identified by authority, document number and kind code
(DOCDB shape) and by nothing else. The kind code is part of the identity: an
`A1` application publication and its `B1` grant are two publications, and a
missing kind code is never a wildcard. `PublicationIdentity` has no title field,
so title-based identity cannot be expressed.

A family is a separate, higher layer. Family identity comes from the provider's
family service (EPO OPS INPADOC family) and from nowhere else -- never a title,
never a shared classification. A family response that does not list the very
document it was asked about is refused as `FAMILY_RESOLUTION_FAILED`: accepting
it would be fabricated membership.

### 3. Why family grouping prevents inflation

One invention filed in five jurisdictions is five publications. Counted as five
candidates it would look like five teams independently reaching the same
result, which is a materially different picture from one applicant filing
abroad. `independent_family_count` therefore counts families: a resolved family
counts once however many members it has, and a publication whose family could
not be established counts once on its own -- an unknown family is not evidence
of a shared one, in either direction.

### 4. Why family members stay preserved

Grouping is a layer *over* publication records, never a replacement. Members
carry different kind codes, jurisdictions, publication dates and -- crucially --
different claim text. A later comparison phase needs every one of them, so all
are kept, each with its own snapshots, and a member the run never fetched is
still recorded as `retrieved_in_run=False`. A resolved family also carries
`FAMILY_SCOPE_VARIES_BY_JURISDICTION`: one family does not mean one claim scope.

### 5. Priority vs publication date

`PatentDateSet` keeps priority, filing, publication and grant dates as four
separate fields with no "effective date". Only the publication date -- or, when
there is none, a grant date stated by a *separate* grant reference -- is a
public-availability date. A priority date is family chronology; a filing date is
application chronology; neither is ever evidence of public availability. A grant
date is never inferred from a document's own kind code, because what a `B` kind
means is authority-dependent; an uninferable grant date stays unknown.

### 6. Cutoff qualification is descriptive chronology only

A cutoff is optional, must be supplied explicitly by the calling workflow, and
must name the contract that supplied it. Without one the answer is `NO_CUTOFF`:
no current date, submission date or priority date is ever substituted. The
qualifications -- `PUBLIC_BEFORE_CUTOFF`, `PUBLIC_ON_CUTOFF`,
`PUBLIC_AFTER_CUTOFF`, `PUBLICATION_DATE_UNKNOWN`, `NO_CUTOFF` -- are statements
about dates. `LEGAL_PRIOR_ART`, `INVALIDATING_PRIOR_ART` and
`NOVELTY_DESTROYING` do not exist, and a test asserts their absence.

### 7. Bounded search limitations

Every search is bounded by a recorded budget (queries per claim and per run,
results per query, Range windows, total results, verified publications, family
lookups). Hitting any limit is recorded with the count it removed and forces a
partial coverage status; a failed or refused query forces `PARTIAL_ERROR`; no
credentials forces `BLOCKED_AUTH`. The strongest statement available is
`COMPLETE_WITHIN_CONFIGURED_BOUNDS`, which means every planned query ran within
budget -- not that all relevant patents were found. No enum member can say that,
and every candidate carries `BOUNDED_SEARCH_NOT_EXHAUSTIVE`.

### 8. Provider access-policy constraints

Providers are classified honestly and the classification is enforced by a
validator: `IMPLEMENTED_AND_LIVE_VERIFIED` requires an observed authenticated
request. EPO OPS is `IMPLEMENTED_DOCUMENTED_ONLY` until such a request succeeds.
USPTO is `DEFERRED`: PatentsView's search API was retired in the move to the
USPTO Open Data Portal and no replacement search contract is published, so no
connector is written against a legacy endpoint. WIPO PATENTSCOPE is
`UNSUPPORTED_BY_ACCESS_POLICY`: its terms forbid automated querying of the
public search service, and the capability validator forbids that status from
exposing any operation, so there is nothing for a connector to call.

### 9. Why novelty is deferred

Novelty is a comparison between what a document *discloses* and what the
project *claims*, element by element. Phase 2G acquires the documents and their
text; it does not decompose patent claims and does not compare them. A novelty
judgement made from titles, ranks or classification overlap would be exactly
the over-reading this ADR exists to prevent. `PatentPriorArtCandidate` has no
`novelty_score`, no `similarity`, no `same_invention`; a provider's retrieval
rank is stored as `provider_rank` on query provenance and nowhere else.

### 10. Why legal conclusions are out of scope

Patentability, infringement, freedom to operate and legal prior-art status are
jurisdiction-specific legal determinations that depend on grace periods,
claim construction, legal status and much else this system does not model.
They are not a later *phase* of this system; they are outside it. Every
candidate states `NOVELTY_NOT_ASSESSED`, `PATENTABILITY_NOT_ASSESSED` and
`LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED`, and the contract validator refuses a
candidate that omits them.

### Ownership

`PatentPriorArtRun` lives on `ResearchRun.patent_prior_art`, never in
`ProjectState`. It cannot mutate a claim, its status, confidence or evidence
references, a project score, Phase 2C-2F output, the trust gate or the
evaluation status: none of those fields exists on any Phase 2G type, and the
graph nodes replace only `patent_prior_art`.

## Consequences

- A later novelty phase receives families, publications, text snapshots per
  content type and a date line, each with provenance and explicit limitations,
  and must do its own comparison.
- Student-facing output must present patent candidates as technical discovery,
  never as a patentability or legal opinion.
- Recall is deliberately bounded. More candidates require a larger, recorded
  budget, never a silent one.

## Rejected alternatives

- **A relevance or similarity score on the candidate.** It would be read as a
  novelty score within one report cycle.
- **Title- or classification-based family grouping.** Plausible and wrong:
  unrelated inventions share titles and classes routinely.
- **Using the priority date for the cutoff.** It would place documents years
  before anyone could read them.
- **Collapsing kind codes into one "patent".** It would make a document look
  like independent corroboration of itself, and lose the grant's claim text.
- **Scraping PATENTSCOPE or assuming the legacy PatentsView API.** Forbidden by
  access policy and unverifiable respectively.
