# ADR-005 — One canonical technical-domain taxonomy

**Status:** Accepted
**Date:** 2026-09-14
**Phase:** 1C
**Amends:** Phase 0 `ProjectDomain`, Phase 1B `TechnicalDomain`
**Related:** `docs/phase1c_intake_evals.md`, architecture section N02

---

## Context

Two domain enums existed:

* **Phase 0 `ProjectDomain`** (13 members) — written before intake existed, mixing
  technical fields (`AI_ML`, `ROBOTICS`) with application areas (`ENERGY`,
  `HEALTH_TECH`, `ENVIRONMENT`).
* **Phase 1B `TechnicalDomain`** (20 members) — a finer taxonomy for the intake
  classifier, projected onto the Phase 0 enum by an explicit map at merge time.

The projection was lossy by construction:

```text
COMPUTER_VISION  ─┐
NLP              ─┼─▶ AI_ML
MACHINE_LEARNING ─┤
DATA_SCIENCE     ─┘

SOFTWARE_ENGINEERING ─┐
COMPUTER_SCIENCE     ─┼─▶ SOFTWARE
NETWORKS             ─┤
CLOUD_COMPUTING      ─┘
```

The classifier could determine that a project was specifically computer vision,
and the canonical state would record only "AI_ML". The distinction was computed
and then discarded.

That was tolerable while nothing read the domain. It stops being tolerable now,
because the next phase routes research on it: an academic search for a computer
vision project and one for an NLP project are not the same search, and neither
resembles a data science search. A lossy taxonomy at intake would silently
misroute every downstream query — and the failure would be invisible, since the
state would look perfectly well-formed.

Two enums also meant two places to edit, with no mechanism to keep them
consistent.

---

## Decision

> **The intake classifier and `ProjectState.identity.domain` share one canonical
> technical-domain taxonomy.**

* `TechnicalDomain` (21 members) is defined once, in `src/schemas/common.py`,
  alongside the rest of the shared vocabulary.
* `src/schemas/extraction.py` imports it rather than declaring its own.
* `ProjectDomain` remains as an alias of the same object, so Phase 0 imports keep
  working against one enum rather than a parallel copy.
* The projection map is **deleted**. A domain the classifier emits is the domain
  the state stores.

Names are spelled out — `INTERNET_OF_THINGS`, not `IOT`;
`NATURAL_LANGUAGE_PROCESSING`, not `NLP`; `HUMAN_COMPUTER_INTERACTION`, not
`HCI` — so a value read in a log, a trace or a student-facing report is
unambiguous without a decoder.

### Migration

Old serialized state stays loadable. `LEGACY_DOMAIN_MIGRATION` lists every
superseded spelling and its canonical target, applied by a `mode="before"`
field validator on `ProjectIdentity.domain`:

| Legacy | Canonical |
|---|---|
| `AI_ML` | `ARTIFICIAL_INTELLIGENCE` |
| `SOFTWARE` | `SOFTWARE_ENGINEERING` |
| `IOT` | `INTERNET_OF_THINGS` |
| `EMBEDDED` | `EMBEDDED_SYSTEMS` |
| `HCI` | `HUMAN_COMPUTER_INTERACTION` |
| `OTHER` | `OTHER_TECHNICAL` |
| `NLP` | `NATURAL_LANGUAGE_PROCESSING` |
| `ENERGY`, `HEALTH_TECH`, `ENVIRONMENT` | `OTHER_TECHNICAL` |

Two properties of this migration matter:

1. **Nothing is silently reinterpreted.** Every mapping is listed in one table
   and covered by a parametrized test. A string with no entry is passed through
   untouched so pydantic rejects it, rather than the migrator inventing a
   plausible substitute.
2. **The three application areas are an acknowledged loss.** `ENERGY`,
   `HEALTH_TECH` and `ENVIRONMENT` describe what a project is *about*, not which
   technical field it sits in, so they have no technical-domain equivalent. They
   migrate to `OTHER_TECHNICAL`. If application area turns out to matter for
   evaluation, it belongs in a separate field with its own taxonomy — not smuggled
   into the technical one.

---

## Consequences

**Positive**

* Research routing in the next phase reads the domain the classifier actually
  determined. A computer vision project is routed as computer vision.
* One enum, one place to edit, no drift.
* `DEEP_LEARNING` becomes expressible, which the Phase 0 taxonomy could not
  represent at all.
* Fewer moving parts in merge: the classification merge is now an append with
  de-duplication.

**Negative / accepted costs**

* A wider enum invites over-classification — 21 options make it easier for a
  model to reach for a specific one. Countered by the prompt ("do not
  over-classify", "do not add a domain for technology you assume would be
  needed"), by the requirement that every domain carry a verified anchor, and by
  Gold cases INTAKE-050, INTAKE-055 and INTAKE-071 asserting that a CRUD
  application does not become an AI project.
* Old snapshots carrying `ENERGY`, `HEALTH_TECH` or `ENVIRONMENT` lose that
  information on load. Explicit, documented, tested — not silent.
* The `ProjectDomain` alias is a compatibility affordance that should eventually
  be retired; keeping two names for one enum is mild debt.

---

## Rejected alternatives

**Keep both enums and improve the mapping.** No mapping from 20 members to 12 is
lossless. Improving it means choosing which distinctions to destroy more
carefully, which is not a solution to destroying distinctions.

**Collapse to the Phase 0 taxonomy.** Simpler, and it discards exactly the
information research routing needs.

**Keep the fine taxonomy only on `VerifiedClassification`, leave the coarse one
canonical.** This is what Phase 1B did. It means the useful value exists but is
not the one anything downstream reads — the distinction is computed, stored
somewhere, and then not used.
