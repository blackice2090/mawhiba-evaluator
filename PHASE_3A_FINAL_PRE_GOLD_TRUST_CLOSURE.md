# Phase 3A — Final Pre-Gold Trust Closure

## Purpose

This is the final narrow trust-closure pass before committing the Phase 3A production implementation milestone.

Do not start Gold/eval, regressions, the full repository suite, merge, or Phase 3B.

The previous hardening pass is accepted except for one remaining trust hole and two consistency checks.

---

# EXECUTION DISCIPLINE — APPLY TO THIS PASS

- Stay on `feat/phase3a-methodology-review`.
- Keep scope limited to the three items in this file.
- Make minimal justified changes only.
- Do not redesign the approved architecture.
- Do not mutate Phase 2A–2J semantics.
- Do not weaken any validator, provenance rule, run-binding check, deterministic posture rule, checkpoint guard, or safety boundary.
- Do not hard-code case-specific answers.
- Run smallest targeted tests first.
- Then run all Phase 3A tests and directly affected guards once.
- Do not run Gold/eval.
- Do not run cross-phase regressions.
- Do not run the full repository suite.
- Do not commit automatically.
- STOP after the required checkpoint.

---

# 1. Eliminate the Remaining English Overlay False-Negative

## Current known limitation

The current candidate discovery still admits this false-negative:

> An English project with no intake metadata signal and none of the bounded lexicon terms can still be missed.

That is not acceptable as a known pre-Gold trust hole because:

```text
missing metadata signal
+ missing lexical trigger
!= evidence that AI/ML or software/systems methodology is non-material
```

A semantically material overlay must not disappear merely because the project described it with an unexpected synonym or phrasing.

## Required invariant

Overlay **candidate discovery** must be complete with respect to the bounded Phase 3A inputs.

Candidate discovery must not depend on a finite English keyword lexicon as the last gate.

The final design must guarantee:

```text
No overlay is silently excluded solely because:
- intake metadata did not tag it; and
- deterministic lexical detection did not recognize its wording.
```

## Preferred implementation direction

Use a conservative bounded review policy:

- deterministic metadata/lexicon/catalog signals may still identify obvious candidates cheaply;
- but absence of those signals must not permanently exclude an overlay when the canonical student submission, claims, or Phase 2J target could contain material evidence;
- ensure a bounded overlay-materiality decision path exists for both AI/ML and software/systems before an overlay can be finalized as non-material.

The materiality judgment must still require the existing safeguards:

- typed structured output;
- a bound claim and/or Phase 2J hypothesis;
- exact student-source excerpt for MATERIAL or IMPLEMENTATION_TOOL_ONLY;
- verified excerpt offsets/content;
- no keyword-only promotion;
- no external search;
- no invented target.

A negative/non-material decision may be accepted only according to an explicit safe contract. Do not persist unsupported free prose.

## Provider-failure behavior

Do not turn every project into a false positive.

If an overlay must be reviewed but the provider is unavailable/refuses/fails:

- do not assume MATERIAL;
- do not assume NOT_MATERIAL;
- use the existing bounded unresolved/failure semantics;
- do not produce a `WELL_SPECIFIED` posture if the unresolved overlay could materially affect the target under the approved rules.

If the architecture can deterministically prove the overlay is not applicable from canonical typed facts, it may skip model review. Document the exact proof rule.

## Required tests

Add tests proving:

1. English AI/ML project with no metadata and no lexicon trigger, but semantically material bounded text, cannot be silently excluded.
2. English software/systems project with no metadata and no lexicon trigger, but semantically material bounded text, cannot be silently excluded.
3. unusual synonym/paraphrase does not create a silent false-negative.
4. keyword-only text still cannot establish materiality.
5. plain non-overlay project can still resolve safely without activating overlay requirements.
6. provider failure on a genuinely review-required overlay cannot produce a positive well-specified posture.
7. engineering-only ownership remains correct.
8. HYBRID ownership/no-double-counting remains correct.
9. implementation-tool-only semantics remain correct.

If the cleanest safe solution is to review both overlays for every project using the bounded materiality task, that is acceptable only if:
- model-call accounting remains explicit;
- failure semantics remain conservative;
- no new trust boundary is weakened;
- tests show irrelevant overlays can be safely resolved as non-material without fabricated evidence.

Do not optimize model-call count at the cost of recall/trust.

---

# 2. Synchronize the Root Architecture Specification

The active contract removed:

`STUDENT_EXECUTION_CLAIM_NOT_VERIFIED`

because it had no valid deterministic emission rule and would incorrectly convert normal student execution descriptions into methodology defects.

The root file:

`PHASE_3A_METHODOLOGY_REVIEW.md`

still lists that obsolete issue kind.

Update the root specification minimally so it matches the approved architecture and production contract.

The specification should clearly preserve:

```text
student-described execution
!= verified execution
```

but should not list the removed issue as an active methodology defect.

Do not rewrite unrelated sections.

Also ensure:
- `PHASE_3A_ARCHITECTURE_HARDENING.md`
- `PHASE_3A_IMPLEMENTATION.md`
- `PHASE_3A_PRE_GOLD_HARDENING.md`
- docs/phase3a_methodology_review.md

do not materially contradict the final active contract.

Only change files where a real contradiction exists.

Run the language-policy guard after docs/spec edits.

---

# 3. Re-verify Git Baseline Factually

Do not infer main state from earlier session history.

Run commands that explicitly establish:

- current branch;
- current feature HEAD;
- `refs/heads/main` exact commit;
- working tree status;
- untracked files;
- worktree count;
- merge-base/ancestor relationship to architecture commit;
- no commits created during implementation/hardening.

Expected main remains:

`9142377`

If main is not exactly the expected baseline, STOP and report before any commit.

Do not use an ambiguous `git rev-parse --short HEAD main` invocation that can fail to report both refs.

Use separate unambiguous Git commands.

---

# 4. Targeted Validation

After the correction:

1. run the new directly affected overlay tests;
2. run all `tests/test_phase3a_*.py`;
3. run `test_language_policy.py`;
4. run `test_workflow_hardening.py`;
5. run Phase 2J contract/graph guards only if shared boundaries were touched;
6. run directly affected LLM/provider tests if overlay-call routing/failure handling changed.

Do not run:
- Gold/eval;
- cross-phase regressions;
- full repository suite.

Report exact counts actually executed.

---

# 5. Final Trust Recheck

Confirm all of the following:

- no metadata-only overlay false-negative;
- no lexicon-only overlay false-negative;
- keyword-only text cannot establish materiality;
- overlay materiality requires bounded typed judgment and verified binding;
- irrelevant overlay can resolve safely;
- provider failure cannot create a positive posture;
- implementation-tool-only stays non-material;
- engineering-only AI/ML remains covered;
- HYBRID ownership/no-double-counting remains correct;
- root spec matches active execution-description taxonomy;
- student execution is never verified in Phase 3A;
- no Phase 2A–2J semantics changed;
- ProjectState unchanged;
- Phase 2I/2J inputs remain immutable;
- external search remains zero;
- no Gold work started.

---

# 6. Required Output

Print:

```text
PHASE 3A FINAL PRE-GOLD TRUST CLOSURE CHECKPOINT
```

Report:

## Overlay discovery/materiality
- previous false-negative path;
- final rule;
- why an unseen English synonym can no longer silently bypass review;
- materiality proof requirements;
- provider-failure behavior;
- test results.

## Specification consistency
- exact root-spec correction;
- any other spec/doc contradictions found and corrected;
- confirmation active issue taxonomy matches documentation.

## Git verification
- feature branch;
- feature HEAD;
- main exact SHA;
- working tree status;
- untracked files;
- worktree count;
- confirmation no implementation commit exists yet.

## Tests actually run
- passed;
- skipped;
- failed;
- errors;
for each test group.

## Upstream impact
- Phase 2A–2J semantics changed? yes/no;
- ProjectState changed? yes/no;
- Phase 2I/2J byte-identical? yes/no.

## Remaining limitations
List only bounded limitations that remain after this closure.

Only if there is no remaining silent overlay false-negative, no spec contradiction, main is verified at `9142377`, all targeted tests pass, and no blocking trust issue remains, print exactly:

```text
PHASE 3A FINAL PRE-GOLD TRUST CLOSURE COMPLETE — SAFE TO COMMIT IMPLEMENTATION MILESTONE
```

Then STOP.

Do not commit automatically.
Do not start Gold automatically.
