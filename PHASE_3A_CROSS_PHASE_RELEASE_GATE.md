# Phase 3A — Cross-Phase Release Gate

## Status

Final release-gate specification for Phase 3A after the approved Gold/offline-eval milestone.

Repository:
- `mawhiba-evaluator`

Feature branch:
- `feat/phase3a-methodology-review`

Main baseline:
- `91423770758ed39e459401cc3b9b9de84c478715`

Approved Phase 3A architecture commit:
- `2f1693a13101088dc8e567e58f81eaf5e3b34f88`

Approved Phase 3A implementation commit:
- `b9e59ffbcdc879ad25631f4d0b316b67e569cdc8`

Approved Phase 3A Gold milestone commit:
- `99c2798fda02826bbf4dec139e1b4820318fb955`

Gold status:
- 789 cases
- en 262 / ar 264 / mixed 263
- 267 language-normalized semantic families
- 50 deterministic metric families at 1.0
- 16 model-judgment families measured honestly
- 209 release gates, zero violations, zero zero-denominator gates
- 769/769 negative controls caught
- 135 distinct negative-control mechanisms
- offline Gold `PASSED=True`

This milestone performs:
1. Phase 3A release verification,
2. cross-phase regressions in strict order,
3. exactly one final full repository pytest suite,
4. final Git verification.

It does **not** merge automatically.

---

# 1. Goal

Prove that Phase 3A is release-safe against all previously completed phases and against the repository-wide test suite.

The release gate must establish:

```text
Phase 3A Gold approved
+
Phase 2J → Phase 1 regressions pass
+
final repository suite passes
+
Git state is clean and controlled
=
READY TO MERGE PHASE 3A
```

Do not start Phase 3B.

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS RELEASE GATE

- Stay on `feat/phase3a-methodology-review`.
- Start from Gold commit `99c2798fda02826bbf4dec139e1b4820318fb955`.
- Do not merge main during this pass.
- Do not amend, squash, rebase, force-push, or rewrite history.
- Do not delete the feature branch.
- Do not create secondary worktrees.
- Keep `homepage-preview/` untouched and excluded. It is unrelated/untracked.
- Do not perform unrelated refactors.
- Do not weaken any historical test, validator, assertion, contract, schema, metric, release gate, provenance check, or safety boundary.
- Do not change historical Gold expectations merely to make regressions pass.
- Do not rerun Phase 3A Gold unless a later code change could affect Phase 3A behavior or Gold integrity.
- Do not repeatedly rerun already-passing historical regressions.
- Run the final full repository suite only after all required cross-phase regressions pass.
- Run the final full repository suite exactly once unless the first run cannot produce reliable counts without changing code; if a second invocation is needed solely to recover counts, state why and confirm no code changed.
- If any code changes after the final full suite, that suite is no longer valid and must be rerun once after fixes stabilize.
- Only report tests/evals actually executed.

Required execution order:

```text
preflight
→ Phase 3A release sanity
→ Phase 2J regression
→ Phase 2I regression
→ Phase 2H regression
→ Phase 2G regression
→ Phase 2F regression
→ Phase 2E regression
→ Phase 2D regression
→ Phase 2C regression
→ Phase 2B regression
→ Phase 2A regression
→ Phase 1 regression
→ ONE final full repository pytest suite
→ Git verification
→ FINAL REPORT
→ STOP
```

---

# 3. Preflight Verification

Before running tests, verify factually:

- current branch = `feat/phase3a-methodology-review`;
- feature HEAD = `99c2798fda02826bbf4dec139e1b4820318fb955`;
- `refs/heads/main` = `91423770758ed39e459401cc3b9b9de84c478715`;
- architecture commit `2f1693a...` is an ancestor of HEAD;
- implementation commit `b9e59ff...` is an ancestor of HEAD;
- Gold commit `99c2798...` is HEAD;
- one worktree;
- no staged files;
- no tracked modifications;
- the only allowed unrelated untracked path is `homepage-preview/`;
- nothing is merged.

If another unexpected path exists, STOP and report before running regressions.

Do not delete or modify `homepage-preview/`.

---

# 4. Phase 3A Release Sanity

Do not rerun the full 789-case Gold unless required.

Before historical regressions, run the smallest Phase 3A release sanity set that proves the committed Gold milestone is intact.

Use existing repository commands/tests, including at minimum:

- Phase 3A Gold/eval test file(s);
- Phase 3A language-neutral overlay-negative tests;
- Phase 3A production tests directly covering the Gold-discovered production fixes;
- language-policy guard only if needed to verify committed Gold files remain registered;
- workflow-hardening guard only if needed to verify committed Gold types.

Do not substitute a new test plan for the repository's established test files.

Report exact:
- passed;
- skipped;
- failed;
- errors.

If this sanity set fails on the clean Gold commit, STOP and classify before cross-phase regression.

---

# 5. Required Cross-Phase Regression Order

Run in this exact order:

1. Phase 2J
2. Phase 2I
3. Phase 2H
4. Phase 2G
5. Phase 2F
6. Phase 2E
7. Phase 2D
8. Phase 2C
9. Phase 2B
10. Phase 2A
11. Phase 1

For each phase, use the existing phase-specific:
- pytest files;
- eval CLI;
- safety/negative controls;
- contract/regression commands;

already established in the repository.

Do not invent replacement regression commands if canonical commands exist.

For each phase, record:

- PASS / FAIL;
- tests executed;
- skipped;
- failed;
- errors;
- eval result;
- controls/gates summary where that phase has them.

Keep shell output concise.

---

# 6. Regression Failure Protocol

If any historical regression fails:

1. STOP the ordered regression sequence at that phase.
2. Classify the failure before editing anything.

Allowed classifications:

- `REGRESSION_HARNESS_DEFECT`
- `HISTORICAL_TEST_FIXTURE_DEFECT`
- `PHASE3A_PRODUCTION_REGRESSION`
- `SHARED_CONTRACT_REGRESSION`
- `ENVIRONMENT_OR_COMMAND_DEFECT`

3. Identify whether the failure is caused by:
   - Phase 3A shared-file additions;
   - an actual historical semantic regression;
   - test/eval harness assumptions;
   - environment/command invocation.

4. Make the smallest justified fix only if needed.

5. Never weaken the historical contract to accommodate Phase 3A.

6. Rerun only:
   - the failing historical phase regression;
   - directly affected Phase 3A tests;
   - Phase 3A Gold only if the change can affect Phase 3A semantics, Gold metrics, gates, controls, canonical output, model DTOs, prompts, graph behavior, or deterministic synthesis.

7. Once the failing phase passes again, continue from the next phase.
   Do not restart all previously passing phases unless the fix could affect them.

8. Record every fix in the final report.

If a failure reveals an architecture conflict that cannot be fixed narrowly:
- STOP;
- do not continue to final suite;
- do not merge.

---

# 7. Shared-File Sensitivity

Phase 3A changed shared areas including:
- graph registry;
- LLM contracts/prompts;
- research settings;
- ResearchRun schema;
- workflow hardening registrations;
- language policy registry.

Be especially alert for regressions involving:

- checkpoint serialization;
- graph node registration;
- provider structured-output contracts;
- prompt isolation;
- ProjectState immutability;
- ResearchRun backward compatibility;
- historical language-policy assumptions;
- Phase 2J model-prose boundary;
- Phase 2I/2J run binding.

Do not assume additive changes are harmless merely because schemas validate.

---

# 8. Historical Trust Boundaries That Must Remain Intact

The release gate must not weaken or regress:

## Phase 2J
- gap existence vs project linkage;
- condition materiality;
- exact validation continuity;
- bounded gap statements;
- no field-wide/legal claims;
- prompt/model prose noncanonicality;
- external search = 0.

## Phase 2I
- descriptive technical overlap only;
- unresolved patent family not independently corroborating;
- ProductEntity identity separation;
- OSS disclosure-capacity semantics;
- exact repeated-excerpt anchoring;
- no legal novelty/patentability/FTO.

## Phase 2H
- product identity rules;
- weak/duplicate links do not collapse identity;
- SSRF/DNS-rebinding safety;
- denominator integrity.

## Phase 2G
- patent identity/family/date separation;
- no legal prior-art conclusion;
- verified patent != same invention.

## Phase 2F
- support and contradiction remain separate;
- `0` vs `None`;
- no net truth score.

## Phase 2E
- component inventory completeness;
- uncovered remainder;
- source independence grouping;
- support != sufficiency.

## Phase 2D
- alignment != verification;
- bounded relation taxonomy.

## Phase 2C
- exact evidence spans/numeric fidelity;
- source snapshot verification;
- synthesis/abstract restrictions.

## Phase 2B / 2A / Phase 1
- connector/research contracts;
- official requirements;
- checkpoint/replay;
- trusted intake;
- human interrupt semantics;
- ProjectState and serializer integrity.

If a Phase 3A change conflicts with one of these, the historical boundary wins unless explicitly redesigned in a later approved phase.

---

# 9. Final Full Repository Suite

Only after all 11 cross-phase regressions pass, run exactly one final repository suite using the repository virtual environment.

Preferred Windows command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Capture exact:

- passed;
- skipped;
- failed;
- errors;
- exit code.

If repository pytest configuration suppresses the summary:

- first try to recover the summary from the completed process/output without rerunning;
- if impossible, one second invocation solely for exact counts is acceptable;
- clearly state why;
- confirm no code changed between runs.

Do not run the full suite a third time unless code changed after it.

---

# 10. Final Git Verification

After all tests pass, verify:

- current branch = `feat/phase3a-methodology-review`;
- HEAD includes:
  - `2f1693a13101088dc8e567e58f81eaf5e3b34f88`
  - `b9e59ffbcdc879ad25631f4d0b316b67e569cdc8`
  - `99c2798fda02826bbf4dec139e1b4820318fb955`
- main remains exactly:
  - `91423770758ed39e459401cc3b9b9de84c478715`
- feature branch is ahead of main by the expected Phase 3A commits;
- one worktree;
- no staged files;
- no tracked modifications;
- `homepage-preview/` remains unrelated/untracked and untouched;
- no unrelated files are part of Phase 3A commits;
- nothing merged.

If a regression fix required a new commit:
- report it explicitly;
- verify commit lineage;
- do not merge automatically.

If fixes remain uncommitted:
- final release cannot be declared merge-ready;
- report that and STOP.

---

# 11. Final Release Conditions

Print `READY TO MERGE PHASE 3A` only if all are true:

- Phase 3A Gold milestone remains valid;
- Phase 3A release sanity passes;
- Phase 2J regression passes;
- Phase 2I regression passes;
- Phase 2H regression passes;
- Phase 2G regression passes;
- Phase 2F regression passes;
- Phase 2E regression passes;
- Phase 2D regression passes;
- Phase 2C regression passes;
- Phase 2B regression passes;
- Phase 2A regression passes;
- Phase 1 regression passes;
- final full repository pytest exits 0;
- 0 failed;
- 0 errors;
- Git state is clean except the pre-existing unrelated `homepage-preview/`;
- all Phase 3A release changes are committed;
- main remains unchanged;
- no merge has occurred.

Skipped live-integration tests are allowed only if they are the repository's expected credential-gated skips. Report them exactly.

---

# 12. Required Final Report

Print:

```text
PHASE 3A FINAL RELEASE REPORT
```

Include:

## Git
- branch;
- main baseline;
- Phase 3A commit lineage;
- additional regression-fix commits, if any;
- working-tree status;
- untracked paths;
- worktree count;
- merge status.

## Phase 3A Gold
Restate:
- 789 cases;
- language distribution;
- normalized semantic-family count;
- deterministic metric families;
- model-judgment families;
- release gates;
- negative controls;
- mechanisms;
- known semantic model-judgment ceilings.

Do not claim Gold was rerun unless it actually was.

## Phase 3A release sanity
- exact test groups;
- passed/skipped/failed/errors.

## Cross-phase regressions
For each:
- Phase 2J
- Phase 2I
- Phase 2H
- Phase 2G
- Phase 2F
- Phase 2E
- Phase 2D
- Phase 2C
- Phase 2B
- Phase 2A
- Phase 1

Report:
- PASS / FAIL;
- tests;
- skips;
- failures;
- eval/controls result where applicable.

## Regression defects
For every issue found:
- classification;
- root cause;
- fix;
- tests rerun;
- whether Phase 3A Gold was rerun.

If none:
- state none.

## Final repository pytest
- passed;
- skipped;
- failed;
- errors;
- exit code;
- number of full-suite invocations and why.

## Known limitations
Include:
- model-judgment semantic ceilings;
- thin Gold gate `invented_sample_size_requirement` if still applicable;
- Gold runtime;
- no legal/scoring/result/execution conclusions;
- any expected credential-gated skips;
- unrelated `homepage-preview/`.

Then, only if every release condition passes, print exactly:

```text
READY TO MERGE PHASE 3A
```

Then STOP.

Do not merge automatically.
Do not start Phase 3B.
Do not delete the feature branch.

---

# 13. No Automatic Commit

Do not create a commit merely because regression tests pass.

A commit is allowed only if a regression requires a real code/test fix and the fix has been fully validated.

If a fix is needed:
- do not amend `2f1693a`, `b9e59ff`, or `99c2798`;
- create a new normal commit only after the fix is validated;
- use no `Co-Authored-By` or AI-attribution lines;
- report the commit in the final release report.

If no fix is needed:
- create no new commit.

---

# 14. Stop Condition

This milestone ends at:

```text
PHASE 3A FINAL RELEASE REPORT
```

and, if all release conditions pass:

```text
READY TO MERGE PHASE 3A
```

Then STOP.
