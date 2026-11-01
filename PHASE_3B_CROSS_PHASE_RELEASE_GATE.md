# Phase 3B — Cross-Phase Release Gate

## Status

Final regression/release validation for Phase 3B before merge.

Repository:
- `mawhiba-evaluator`

Branch:
- `feat/phase3b-experiment-review`

Main baseline:
- `9d9e64eb16acedcb85007112f874762336a20d74`

Phase 3B milestones:
- Architecture: `7641ef5cde1957c06db0e6b93fb4ccbb6b0eab76`
- Implementation: `de1f734f9c9fdbfdce28b7740716488396034a7d`
- Pre-Gold hardening: `b6beaad929c015909e554c9ebd89909466c21351`
- Gold: `8c0a4e1cb6ec7d47b5b1b3f73413d307b6d3b914`

Phase 3A merged main:
- `9d9e64eb16acedcb85007112f874762336a20d74`

This gate validates that Phase 3B did not regress Phase 3A, Phase 2A–2J, or Phase 1.

Do not merge or push during this gate.

---

# 1. Goal

Prove all of the following before Phase 3B is eligible to merge:

1. Phase 3B targeted production, hardening, and Gold tests remain green.
2. Phase 3A remains green.
3. Phase 2J through Phase 2A remain green.
4. Phase 1 remains green.
5. Language/workflow/LLM/registry/shared guards remain green where applicable.
6. No cross-phase contract regression exists.
7. The full repository suite passes once at the final gate.
8. No code/test/fixture changes are made unless a real regression defect is proven.

The gate is validation-first, not implementation.

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS RELEASE GATE

- Stay on `feat/phase3b-experiment-review`.
- Start from `8c0a4e1cb6ec7d47b5b1b3f73413d307b6d3b914`.
- Main must remain `9d9e64eb16acedcb85007112f874762336a20d74`.
- Do not merge.
- Do not push.
- Do not modify code, tests, fixtures, Gold data, docs, schemas, prompts, or guards unless a real regression defect is first demonstrated and classified.
- Do not weaken tests, validators, assertions, schemas, referential integrity, release gates, metrics, or safety checks.
- Do not change expected outputs merely to make a regression disappear.
- Do not rerun historical suites repeatedly.
- Run each required suite once unless it fails or a justified fix is made.
- Run the full repository suite exactly once, at the final release gate, after all targeted/cross-phase suites pass.
- Keep shell output concise but preserve exact final counts.
- Only report tests/evals actually executed.
- No unrelated refactors.
- No speculative architecture changes.
- No automatic next phase.
- No Result Review.
- Do not touch `homepage-preview/`.
- No Co-Authored-By or AI attribution in any later fix commit.

Required sequence:

```text
preflight
→ Phase 3B sanity
→ Phase 3A regression
→ Phase 2J
→ Phase 2I
→ Phase 2H
→ Phase 2G
→ Phase 2F
→ Phase 2E
→ Phase 2D
→ Phase 2C
→ Phase 2B
→ Phase 2A
→ Phase 1
→ shared release guards
→ full repository suite exactly once
→ Git verification
→ release checkpoint
→ STOP
```

If any phase fails, stop the sequence after enough evidence is collected to classify the defect.

---

# 3. Context Discipline

Recommended:

```text
/clear
/model sonnet
```

Use Opus only if a real cross-phase architectural contradiction appears.

Use `/context` during the long gate and compact at a logical milestone around 70–80%.

---

# 4. Preflight Git Verification

Before tests, verify:

```text
git branch --show-current
git rev-parse HEAD
git rev-parse main
git status --short
git worktree list
git log --oneline --decorate -n 12
```

Required:

```text
branch = feat/phase3b-experiment-review
HEAD = 8c0a4e1cb6ec7d47b5b1b3f73413d307b6d3b914
main = 9d9e64eb16acedcb85007112f874762336a20d74
worktree count = 1
no tracked modifications
homepage-preview/ = untracked and untouched
```

Verify all Phase 3B milestones are ancestors of HEAD.

Do not begin release validation if tracked modifications exist.

---

# 5. Phase 3B Release Sanity

Run the focused Phase 3B validation first.

At minimum include:
- Phase 3B architecture tests
- pipeline tests
- trust tests
- safety tests
- hardening tests
- Gold regression tests
- Gold eval tests
- language policy
- workflow hardening
- LLM layer if Phase 3B changed prompts/contracts
- registry/NodeId completeness if relevant

Do not rerun the full Gold CLI if nothing changed since `8c0a4e1`.

Capture exact passed/skipped/failed/errors/exit code.

If summary flags hide exact counts, rerun the same sanity command only for counts, with no code changes.

---

# 6. Phase 3A Regression

Run all Phase 3A suites needed to prove Phase 3B did not affect methodology review.

Include:
- architecture/contract tests
- hardening tests
- Gold/overlay/family tests
- language-neutral overlay regression
- checkpoint/replay guards relevant to Phase 3A
- dedicated Phase 3A offline eval if historically part of the release gate

Do not modify historical Phase 3A Gold expectations.

Required:
```text
0 failed
0 errors
```

Historical intentional skips are acceptable only if unchanged and understood.

---

# 7. Phase 2J Regression

Run Phase 2J Research / Engineering Gap regression and eval.

Validate:
- exact upstream target continuity
- gap hypotheses
- validation requirements
- metric/baseline/conditions
- release gates
- negative controls
- model-judgment metrics for regression comparison

Historical sub-perfect semantic metrics are not regressions unless they changed.

Required:
```text
release gates: zero violations
negative controls: all caught
PASSED=True
```

---

# 8. Phase 2I Regression

Run Phase 2I novelty/differentiation regression and controls.

Required:
```text
0 failed
0 errors
all required controls caught
```

---

# 9. Phase 2H Regression

Run Phase 2H product + OSS prior-art regression.

Required:
```text
0 failed
0 errors
```

---

# 10. Phase 2G Regression

Run Phase 2G patent prior-art regression.

Validate language parity if reported.

Required:
```text
0 failed
0 errors
```

---

# 11. Phase 2F Regression

Run Phase 2F evidence-based claim scoring regression.

Required:
```text
0 failed
0 errors
zero required gate violations
```

---

# 12. Phase 2E Regression

Run Phase 2E sufficiency/weighting regression.

Required:
```text
0 failed
0 errors
zero required gate violations
```

---

# 13. Phase 2D Regression

Run Phase 2D claim-evidence alignment regression.

Required:
```text
0 failed
0 errors
zero required gate violations
```

---

# 14. Phase 2C Regression

Run Phase 2C evidence extraction regression.

Record exact passed/skipped counts.

---

# 15. Phase 2B Regression

Run Phase 2B academic connector regression.

Live credential-gated skips are acceptable only if expected.

Record exact passed/skipped counts.

---

# 16. Phase 2A Regression

Run Phase 2A research/query planning regression.

Record exact passed/skipped counts.

---

# 17. Phase 1 Regression

Run Phase 1A/B/C intake/canonical-intake regression.

Validate:
- authoritative source binding
- canonical intake
- no hidden assumptions
- safety metrics
- checkpoint/replay where relevant

Required:
```text
all intake safety metrics = zero violations
0 failed
0 errors
```

---

# 18. Shared Release Guards

After phase regressions, run only shared guard suites not already covered, as needed:
- workflow hardening
- language policy
- LLM layer
- registry completeness
- schema/privacy/checkpoint
- ResearchRun serialization

Avoid duplicate reruns if the exact same command already passed and nothing changed.

---

# 19. Regression Defect Classification

If anything fails, classify before editing.

Allowed classifications:

```text
PHASE3B_PRODUCTION_REGRESSION
CROSS_PHASE_CONTRACT_REGRESSION
TEST_FIXTURE_DEFECT
TEST_EXPECTATION_DEFECT
WORKFLOW_GUARD_DEFECT
LANGUAGE_POLICY_REGISTRATION
EVAL_HARNESS_DEFECT
HISTORICAL_FLAKE_OR_ENVIRONMENT
LIVE_INTEGRATION_SKIP_OR_FAILURE
ARCHITECTURE_CONTRACT_DEFECT
```

Rules:
- Do not modify historical tests merely because Phase 3B changed.
- Do not weaken Phase 3B safety to satisfy an old test.
- Do not rewrite architecture silently.
- Do not alter Gold expected results unless proven wrong.
- Credential-gated skips are not product regressions.
- If a real Phase 3B production regression is found, fix minimally, add targeted regression coverage, rerun the affected targeted test, Phase 3B sanity, and affected historical phase before continuing.
- If architecture conflict appears, STOP before changing ADR/contracts.

---

# 20. Full Repository Suite — FINAL GATE ONLY

Only after every targeted/cross-phase suite is green, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run it exactly once.

Do not use flags that hide the final summary.

Capture:
- passed
- skipped
- failed
- errors
- duration if shown
- exit code

Required:
```text
0 failed
0 errors
exit code 0
```

Skips are acceptable only if understood and supported by the test source/output.

---

# 21. Post-Test Git Verification

After all tests:

```text
git status --short
git rev-parse HEAD
git rev-parse main
git worktree list
git diff --stat main...HEAD
```

Required:
- HEAD unchanged unless an explicitly justified regression fix was committed
- main unchanged
- no tracked modifications
- homepage-preview/ untouched
- one worktree
- nothing merged
- nothing pushed

---

# 22. Release-Gate Spec Commit Policy

`PHASE_3B_CROSS_PHASE_RELEASE_GATE.md` is project-owned documentation.

Do not commit it during execution unless explicitly instructed after the report.

If it is the only project-owned untracked file after successful validation, report that.

---

# 23. Required Final Report

Print exactly:

```text
PHASE 3B CROSS-PHASE RELEASE GATE
```

Include:

## Git
- branch
- HEAD
- main SHA
- architecture SHA
- implementation SHA
- hardening SHA
- Gold SHA
- worktree count
- tracked working-tree status
- release-gate spec status
- homepage-preview/ status

## Phase 3B sanity
- exact tests/evals run
- passed
- skipped
- failed
- errors
- exit code

## Phase 3A
- exact tests/eval counts
- gates/eval result
- skips
- regressions

## Phase 2J
- exact tests
- release gates
- negative controls
- semantic metrics relevant to regression interpretation
- PASSED state

## Phase 2I
- exact tests/controls
- result

## Phase 2H
- exact tests/controls
- result

## Phase 2G
- exact tests
- language parity if reported
- result

## Phase 2F
- exact tests
- gate violations
- result

## Phase 2E
- exact tests
- gate violations
- result

## Phase 2D
- exact tests
- gate violations
- result

## Phase 2C
- exact passed/skipped
- result

## Phase 2B
- exact passed/skipped
- result

## Phase 2A
- exact passed/skipped
- result

## Phase 1
- exact passed/skipped
- intake safety violations
- result

## Shared guards
- exact commands/counts not already included
- result

## Regression defects
For each:
- classification
- root cause
- files changed
- tests added/changed
- architecture changed yes/no

If none:
```text
Regression defects: NONE
```

## Final repository suite
- exact passed
- skipped
- failed
- errors
- exit code
- duration if shown
- skip categories supported by evidence

## Known limitations
At minimum preserve:
- result segmentation recall is model-dependent
- execution authenticity is not verified
- results are not evaluated
- semantic model judgments remain bounded
- Phase 2J historical semantic metrics may remain below perfect
- any thin Phase 3B Gold gates
- no legal/scoring/readiness conclusions
- live integrations not run where credentials/flags are absent

## Final Git state
- current branch
- HEAD
- main
- tracked status
- untracked files
- one worktree
- nothing merged
- nothing pushed

Then print:

```text
PHASE 3B CROSS-PHASE RELEASE GATE COMPLETE
```

Only if every required regression and the final full repository suite pass, print exactly:

```text
READY TO MERGE PHASE 3B
```

Then STOP.

Do not merge.
Do not push.
Do not start Result Review.
