# Phase 3A — Pre-Gold Hardening Pass

## Status

Narrow hardening pass after the Phase 3A production implementation checkpoint and before committing the production milestone or starting Gold/eval.

Current branch:

`feat/phase3a-methodology-review`

Approved architecture commit:

`2f1693a13101088dc8e567e58f81eaf5e3b34f88`

Current implementation status:

- Phase 3A production implementation complete
- targeted production tests passing
- Gold/eval not started
- cross-phase regressions not started
- full repository suite not run
- implementation not committed

This pass addresses three narrowly-scoped pre-Gold issues only.

---

# EXECUTION DISCIPLINE — APPLY TO THIS PASS

- Stay on `feat/phase3a-methodology-review`.
- Do not create another branch or worktree.
- Keep scope limited to the three issues below.
- Make only minimal, justified changes.
- Reuse the existing approved Phase 3A contracts.
- Do not redesign the architecture.
- Do not mutate Phase 2A–2J semantics.
- Do not weaken tests, validators, provenance, run binding, fingerprinting, deterministic synthesis, checkpoint guards, or safety boundaries.
- Do not hard-code Gold answers.
- Do not start Phase 3A Gold/eval.
- Do not run cross-phase regressions.
- Do not run the full repository suite.
- Do not commit.
- Do not merge.
- Do not start Phase 3B.
- If one of these corrections conflicts with an approved upstream contract, STOP and report the conflict instead of broadening scope.

Testing sequence:

```text
minimal hardening change
→ smallest targeted tests
→ fix targeted failure
→ rerun targeted tests
→ all Phase 3A tests
→ language/workflow guards
→ directly affected Phase 2J guards if required
→ PRE-GOLD HARDENING CHECKPOINT
→ STOP
```

---

# 1. Overlay Candidate Discovery Must Not Depend Only on Intake Metadata Signals

## Current risk

The production checkpoint reports that an overlay with no project signal such as:

- domain;
- model;
- dataset;
- software;
- architecture entry;

is never assessed.

This creates a false-negative path.

A project may materially depend on AI/ML or software/systems methodology even when intake metadata failed to tag it, while the canonical:

- student submission;
- claim;
- Phase 2J hypothesis/gap;
- Phase 2J validation requirement;

contains bounded evidence that should trigger overlay review.

The approved architecture already established:

```text
domain / "AI" / model presence = signal only
signal != materiality
```

Production must also preserve the converse:

```text
missing intake metadata signal
!= proof that overlay is not material
```

## Required correction

Separate:

1. overlay **candidate discovery**
2. overlay **materiality judgment**
3. overlay **track ownership**

Candidate discovery may use deterministic bounded evidence from authoritative inputs.

At minimum, an overlay must become a candidate when any approved bounded input indicates that its methodology could be relevant, including:

- domain/technical metadata signal;
- canonical claim semantics;
- Phase 2J target/hypothesis semantics;
- Phase 2J validation requirement;
- exact student methodology excerpts that map to overlay-specific catalog requirements.

Do not promote a candidate directly to materiality.

Candidate discovery only means:

> this overlay needs bounded materiality review.

Materiality must still be resolved by the existing typed bounded judgment and exact source/target binding.

## Forbidden shortcuts

Do not make materiality true solely because the submission contains:

- "AI";
- "machine learning";
- "model";
- "software";
- "application";
- equivalent Arabic/mixed-language words.

Keyword detection, if used at all, may only help candidate discovery and must never decide materiality or ownership.

Do not silently search externally.

## Required tests

Add tests proving:

1. engineering AI project with no intake metadata signal but with a bound claim + exact methodology excerpt still enters AI/ML overlay materiality review;
2. research AI project with no domain signal but a bound Phase 2J target still enters review;
3. software/system overlay can become a candidate from bound project/claim/methodology evidence even when the technical metadata is empty;
4. a keyword-only mention with no materially bound target does not become material;
5. an implementation-tool-only overlay remains implementation-only and does not activate methodology requirements;
6. absence of metadata signals alone cannot make an otherwise material overlay disappear;
7. overlay ownership and no-double-counting rules from the architecture hardening remain unchanged.

If the current implementation already has a safe non-metadata candidate path that the checkpoint merely described imprecisely, prove it with tests and update the report/docs instead of changing production code unnecessarily.

---

# 2. Resolve the Unused `STUDENT_EXECUTION_CLAIM_NOT_VERIFIED` Issue Kind

## Current state

The production checkpoint reports that:

`STUDENT_EXECUTION_CLAIM_NOT_VERIFIED`

is never emitted because treating every past-tense methodology/execution sentence as an issue would incorrectly block an otherwise well-specified track.

That reasoning is correct.

A student saying:

> We randomized participants.

must not automatically create a methodology defect merely because Phase 3A cannot verify execution.

The Phase 3A trust boundary already captures this safely through:

```text
statement_mode = described_as_executed
execution_verified = false
```

or the equivalent approved fields.

## Required correction

Do not turn normal student execution descriptions into methodology defects.

Choose the smallest clean contract resolution:

### Preferred option

If `STUDENT_EXECUTION_CLAIM_NOT_VERIFIED` has no valid deterministic emission condition and no required consumer:

- remove it from the active Phase 3A issue taxonomy;
- update Phase 3A docs/spec references if necessary;
- update tests;
- leave the execution-verification boundary represented by the excerpt/statement contract and safety tests.

### Acceptable alternative

If there is a genuine narrow case where this issue is needed, define that exact case.

It must **not** be emitted merely because a statement is past tense.

It may only represent a real Phase 3A design-level problem, not the ordinary fact that Phase 3B has not yet verified execution.

Do not create an informational issue if the deterministic posture treats every issue as a blocker unless the posture architecture already distinguishes informational/nonblocking issues.

Avoid expanding the posture architecture solely to keep an unnecessary enum.

## Required tests

Prove:

1. ordinary student-described execution remains unverified but does not automatically create a methodology defect;
2. execution_verified can never become true in Phase 3A;
3. a well-specified methodology is not downgraded merely because its source describes planned/performed actions in past tense;
4. no Phase 3A canonical output implies verified execution;
5. Phase 3B remains the owner of execution verification.

---

# 3. Separate `BOUND_REACHED` and `NO_PROVIDER` Failure Semantics

## Current state

The production checkpoint reports:

> bound-reached and no-provider failures share one message.

This is not a major trust defect, but it creates avoidable diagnostic ambiguity before Gold.

## Required correction

If the implementation currently has distinct underlying conditions, expose distinct typed failure codes/status reasons.

Examples:

- `MODEL_CALL_BOUND_REACHED`
- `MODEL_PROVIDER_UNAVAILABLE`

or equivalent repository-consistent names.

Requirements:

- do not persist raw provider error/refusal text;
- keep provider text redaction/digest behavior unchanged;
- do not change positive assessment semantics;
- do not change retry policy unless required;
- do not expand model call counts.

If the two conditions intentionally share one higher-level run status, they may still share the status while preserving distinct safe reason codes.

## Required tests

Prove:

1. bound reached and provider unavailable are distinguishable in safe structured diagnostics;
2. raw provider text is not persisted;
3. neither failure can produce a positive methodology posture;
4. replay behavior remains deterministic.

---

# 4. Preserve Existing Approved Production Decisions

Do not regress:

- `ResearchRun.methodology_review` state location;
- no ProjectState mutation;
- exact submission slicing;
- no first-match excerpt guessing;
- closed requirement catalog;
- deterministic applicability boundaries;
- engineering-only AI/ML ownership;
- HYBRID no-double-counting;
- Phase 2J exact validation continuity;
- optional Phase 2J baseline semantics;
- exact material-condition coverage;
- baseline documentation/relevance/rationale/fair-execution separation;
- no invented metric;
- sample N not equal to sample adequacy;
- confounding never marked eliminated;
- student execution never verified;
- result/experiment leakage barrier;
- model prose noncanonicality;
- upstream fingerprint recheck;
- deterministic IDs/order;
- external search calls equal zero;
- no Phase 3B conclusion.

---

# 5. Targeted Validation

After the minimal hardening changes stabilize, run:

1. directly affected Phase 3A test files;
2. all `tests/test_phase3a_*.py`;
3. `test_language_policy.py`;
4. `test_workflow_hardening.py`;
5. Phase 2J contract/graph guards only if the implementation changes a shared boundary used by Phase 2J;
6. directly affected LLM/provider tests if failure semantics changed.

Do not run:

- Gold/eval;
- cross-phase regressions;
- full repository pytest suite.

Report exact counts actually executed.

---

# 6. Trust Recheck

Before the checkpoint, confirm:

- overlay candidate discovery is not metadata-only;
- keyword-only text cannot establish overlay materiality;
- implementation-tool-only overlay remains non-material;
- no overlay double counting;
- student execution descriptions remain unverified without becoming automatic defects;
- no dead/ambiguous execution issue remains in the active taxonomy;
- failure reasons are safely distinguishable;
- provider error/refusal text remains noncanonical;
- no Phase 2A–2J semantics changed;
- upstream objects remain immutable;
- no Gold implementation was started.

---

# 7. Required Output

Print:

```text
PHASE 3A PRE-GOLD HARDENING CHECKPOINT
```

Include:

## Overlay discovery
- previous behavior;
- final candidate-discovery rule;
- materiality rule;
- ownership rule;
- tests proving no metadata-only false negative;
- tests proving keyword-only false positives are rejected.

## Execution-description taxonomy
- final treatment of `STUDENT_EXECUTION_CLAIM_NOT_VERIFIED`;
- whether it was removed, retained, or narrowed;
- why;
- posture impact.

## Failure semantics
- final bound-reached reason;
- final no-provider reason;
- confirmation raw provider text is not persisted.

## Files changed
List only files changed by this hardening pass.

## Tests actually run
Report:
- passed;
- skipped;
- failed;
- errors.

## Git
- branch;
- architecture baseline commit;
- working tree state;
- no commit created;
- main unchanged;
- worktree count.

## Upstream impact
Explicitly state:
- whether Phase 2A–2J semantics changed;
- whether ProjectState changed;
- whether Phase 2I/2J inputs remained byte-identical.

## Remaining limitations
Report any bounded limitation honestly.

Only if all hardening tests pass and no blocking issue remains, print exactly:

```text
PHASE 3A PRE-GOLD HARDENING COMPLETE — SAFE TO COMMIT IMPLEMENTATION MILESTONE
```

Then STOP.

Do not commit automatically.
Do not start Gold automatically.
