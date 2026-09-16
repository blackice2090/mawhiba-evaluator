# ADR-008 — Academic connectors are isolated providers

**Status:** Accepted
**Date:** 2026-09-16
**Phase:** 2B (Academic Research Connectors)
**Related:** `docs/phase2b_academic_research_connectors.md`, ADR-007, ADR-009, ADR-010, architecture 9, N06A, 27

---

## Context

Phase 2B queries three independent academic services — Consensus, OpenAlex and
Semantic Scholar — for the same research question. They fail in different ways
and at different times: one is rate limited, one is briefly down, one changes a
field name, one has no results for a legitimately narrow query.

The natural implementation runs them behind one call, collects the results into
one list, and lets an exception from any of them propagate. That choice quietly
decides something important: it makes the whole academic branch only as
available as its least available provider. On a morning when Semantic Scholar is
rate limiting, an evaluation would report *no academic literature* for a project
about which OpenAlex returned forty relevant papers.

That is not a retrieval bug, it is a false research conclusion. The novelty and
prior-art stages downstream cannot distinguish "nothing exists" from "nothing
was retrieved" unless this layer tells them the difference.

A second conflation is just as damaging in the other direction. A provider that
answers correctly with zero results is evidence about the literature; a provider
that could not be reached is evidence about the network. Reporting both as
"no results" loses the only piece of information that makes the first one
meaningful.

---

## Decision

> **Academic connectors are isolated providers. Failure, timeout, malformed data
> or rate limiting in one provider must not erase successful results from
> another provider.**

Concretely:

1. Each provider answers each query independently and produces its own
   `AcademicSearchResult`. A connector never raises for an API outcome; a
   failure is data on that one envelope.
2. The branch status is an aggregate over those envelopes:

   ```text
   no results at all                      -> NOT_RUN
   every provider failed                  -> FAILED
   at least one failed, at least one not  -> PARTIAL
   all answered, nothing found            -> EMPTY
   all answered, sources found            -> SUCCESS
   ```

   `EMPTY` is a research finding. `FAILED` is the only outage, and it requires
   every provider to have failed.
3. Statuses distinguish `SUCCESS`, `PARTIAL`, `EMPTY`, `RATE_LIMITED`,
   `AUTH_ERROR`, `PROVIDER_ERROR`, `INVALID_RESPONSE` and `TIMEOUT`, so
   "answered with nothing" is never stored as "could not be asked".
4. Validation is per record. One malformed record produces one ledger entry with
   a named reason; the rest of the response is normalized as usual.
5. Retry classification is a property of the failure kind and lives in one
   place. Timeouts, connection resets, 429 and 5xx are retried to a bound; 400,
   401, 403, 404, malformed JSON and schema incompatibility are not, because a
   second identical request cannot fix a contract problem.
6. Budget exhaustion is truncation, recorded as such, and is never counted as a
   provider failure.
7. Execution is sequential. Correctness does not depend on concurrency; parallel
   dispatch is a performance change for a later phase.

---

## Rejected alternatives

**One combined call that raises on any provider error.** Rejected: it makes the
branch as available as its worst provider and converts an outage into a false
statement about the literature.

**A fallback chain — try Consensus, else OpenAlex, else Semantic Scholar.**
Rejected: the providers have genuinely different coverage, so a "fallback" is a
silent change of what was searched. It also destroys the independent-confirmation
signal that ADR-009 exists to preserve: three providers returning one DOI is
worth more than one provider returning it, and a chain can never observe that.

**Treating 429 as a generic provider error.** Rejected: rate limiting is
recoverable and carries explicit guidance (`Retry-After`). Folding it into a
generic error loses both the recovery and the operational signal that the budget
is too aggressive.

**Treating an empty result as a failure.** Rejected: it is the single most
misleading simplification available here, because it makes a correct answer look
like a broken system, and — worse — makes a broken system look like a correct
answer about a project's novelty.

---

## Consequences

**Positive**

* A provider outage degrades coverage; it never fabricates a research conclusion.
* "Why is there no academic source for this query?" is answerable per provider,
  with status, attempts, rate-limit information and error kind.
* Adding a fourth provider later changes no other provider's behaviour.
* Retry semantics are stated once and tested once.

**Negative / accepted costs**

* Aggregation rules are extra code that would not exist in a fail-fast design,
  and they must be kept honest by tests rather than by exceptions.
* `PARTIAL` is a genuinely ambiguous state for a reader: it says coverage is
  incomplete without saying how incomplete. The coverage counters
  (`provider_success_count`, `provider_failure_count`, `provider_empty_count`)
  exist to make that inspectable rather than guessed.
* Sequential execution is slower than a parallel fan-out. Recorded as technical
  debt in `docs/phase2b_academic_research_connectors.md`.
