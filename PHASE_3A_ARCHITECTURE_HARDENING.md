# Phase 3A — Architecture Hardening Pass

## Purpose

This is a narrow architecture-hardening pass before Phase 3A production implementation.

The Phase 3A Architecture Gate is broadly approved, but three architecture points must be clarified and locked before switching to Sonnet.

Do not start production implementation, graph nodes, prompts, provider execution, Gold/eval, regressions, or commits during this pass.

---

# EXECUTION DISCIPLINE — APPLY TO THIS PASS

- Stay on `feat/phase3a-methodology-review`.
- Keep scope limited to the three architecture corrections below.
- Reuse the existing Phase 3A contracts and abstractions.
- Make only minimal justified schema/test/documentation changes.
- Do not modify Phase 2A–2J semantics.
- Do not weaken any validator, assertion, provenance check, run binding, checkpoint guard, trust boundary, or prior-phase test.
- Run only the smallest targeted Phase 3A contract tests plus directly affected guards.
- Do not run Gold.
- Do not run cross-phase regressions.
- Do not run the full repository suite.
- Do not commit.
- If a correction conflicts with an existing upstream contract, STOP and report the conflict instead of broadening scope.

Testing sequence:

```text
minimal architecture correction
→ smallest targeted tests
→ fix targeted failures
→ rerun targeted tests
→ Phase 3A contract tests
→ directly affected guards
→ architecture-hardening checkpoint
→ STOP
```

---

# 1. AI / ML Overlay Track Ownership Must Be Complete and Deterministic

The current architecture report says:

> AI/ML overlay is switched on by the project's domains. It attaches to the research track when the project has one.

This is incomplete for an `ENGINEERING_PROJECT` whose core engineering method materially uses AI/ML.

Phase 3A must not allow an engineering-only AI/ML project to escape AI/ML methodology requirements simply because it has no research track.

Define and test an explicit ownership rule covering all canonical project types.

Minimum invariant:

- `SCIENTIFIC_RESEARCH`: materially applicable AI/ML methodology requirements can affect the research track.
- `ENGINEERING_PROJECT`: materially applicable AI/ML methodology requirements can affect the engineering track.
- `HYBRID`: an AI/ML requirement must be assigned to the track whose target claim/gap/methodological role it serves, without silently double-counting it.

For HYBRID, do not use "research track whenever one exists" as a blanket rule.

If one overlay requirement materially serves both tracks, choose one of these architectures and document it explicitly:

A. one canonical overlay assessment with explicit links to both tracks, while counting the requirement only once; or

B. separate track-scoped requirement instances with deterministic distinct identities and an explicit rule preventing accidental duplicate counting.

Do not infer track ownership merely from the word "AI", project domain, or presence of a model.

Add contract tests for:

1. engineering-only AI project receives applicable AI/ML methodology requirements;
2. scientific-research AI project receives applicable AI/ML requirements;
3. HYBRID AI requirement cannot be silently assigned to the wrong track;
4. HYBRID overlay requirement is not double-counted.

Apply the same completeness check to the software/systems overlay. A valid architecture must explain what happens if software/system methodology is materially relevant and the canonical project type does not have an engineering track.

Do not force an overlay where it is merely an implementation tool and not material to the evaluated claim/gap.

---

# 2. Strong Methodology Coverage Must Follow the Exact Phase 2J Validation Requirement

The current report says strong gap-method coverage requires:

- a requirement that tests the target;
- same-track documentation;
- an aligned metric;
- every material condition addressed.

Before implementation, inspect the exact Phase 2J validation-requirement schema and remove any blanket requirement that is not actually required by the bound Phase 2J object.

The key rule is:

```text
Phase 3A must cover what Phase 2J actually requires,
not a stronger generic template invented by Phase 3A.
```

Therefore:

- If the bound Phase 2J validation requirement requires a metric, Phase 3A must require a methodology plan covering that metric.
- If it requires a baseline/comparator, Phase 3A must require a methodology plan covering it.
- If it requires material conditions, Phase 3A must require those conditions to be addressed.
- If a dimension is genuinely absent / not applicable in the Phase 2J contract, Phase 3A must not manufacture it as a universal prerequisite for strong coverage.

Do not weaken Phase 2J. This correction is about exact continuity, not permissiveness.

Add contract tests proving:

1. a required Phase 2J metric cannot be omitted;
2. a required baseline cannot be omitted;
3. a required material condition cannot be ignored;
4. Phase 3A does not invent an extra validation dimension that the bound Phase 2J requirement does not require;
5. structural binding to a Phase 2J requirement is insufficient without semantic methodology coverage.

If the current Phase 2J schema always requires a metric and/or baseline by contract, state that explicitly in the checkpoint and keep the stricter rule. Do not assume it without inspecting the actual schema.

---

# 3. Baseline Relevance Must Not Require an Invented Student Rationale Contract

The current architecture report says:

> baseline relevance needs its own rationale excerpt.

Review this carefully.

The project requirement is that an improvement claim needs a defensible comparison. That does not necessarily mean the student must provide a separately labeled rationale sentence for the baseline.

Preserve these distinct concepts:

```text
baseline documented
!= baseline semantically relevant to target
!= student explicitly explains why baseline is relevant
!= comparison fairly executed
```

Recommended architecture:

- `baseline documented` requires exact student-source evidence;
- `baseline relevance` is a bounded semantic judgment using the bound baseline evidence plus the target claim/gap and permitted upstream context;
- `baseline rationale documented` may be a separate documentation property if the student explicitly explains the choice;
- `comparison fairness` remains outside Phase 3A and must stay unverified.

Do not make a separate rationale excerpt a universal prerequisite for baseline relevance unless an existing authoritative contract explicitly requires it.

A single exact excerpt may legitimately contain both the baseline and its rationale. Do not require two artificial excerpts.

Add tests for:

1. baseline can be documented without relevance being established;
2. relevance can be established only through bounded permitted context, never from the baseline name alone;
3. explicit student rationale can support relevance but is not fabricated when absent;
4. same exact source excerpt may support baseline identity and rationale when it actually contains both;
5. no baseline-relevance judgment can imply fair execution.

---

# 4. Preserve Existing Good Decisions

Do not regress these approved architecture properties:

- `ResearchRun.methodology_review` remains the Phase 3A state location unless a real architectural conflict is found.
- `ProjectState.methodology.review_status` is not mutated by Phase 3A.
- canonical project type is inherited and cannot be silently rewritten.
- documentation status remains separate from methodological assessment.
- student execution descriptions never become verified execution.
- result/experiment data cannot upgrade methodology posture.
- exact source anchoring is required.
- repeated excerpt first-match guessing is forbidden.
- model prose remains noncanonical.
- final posture is deterministic.
- upstream fingerprints are rechecked.
- cross-run/cross-claim links are rejected.
- external search remains zero.
- Phase 3B execution conclusions remain out of scope.

---

# 5. Untracked Root Specification

`PHASE_3A_METHODOLOGY_REVIEW.md` is currently untracked in the repository root.

Do not delete it and do not commit it during this hardening pass.

At the checkpoint, report it explicitly so it can be included deliberately when the architecture milestone is approved.

---

# 6. Targeted Validation

Run:

- Phase 3A contract tests;
- `test_language_policy.py`;
- `test_workflow_hardening.py`;
- only directly affected Phase 2J/2I contract tests if the changes interact with their contracts.

Do not run the full suite.

Report exact counts actually executed.

---

# 7. Required Output

Print:

```text
PHASE 3A ARCHITECTURE HARDENING CHECKPOINT
```

Report:

1. AI/ML overlay ownership rule for Scientific Research, Engineering, and Hybrid;
2. software/systems overlay ownership rule;
3. exact Phase 2J validation-requirement continuity rule;
4. whether metric/baseline are universally required by the actual Phase 2J schema or only conditionally required;
5. final baseline relevance/rationale semantics;
6. files changed;
7. targeted tests executed and results;
8. whether any Phase 2A–2J semantics were changed;
9. Git branch/status and whether the root specification remains untracked;
10. any remaining blocking conflict.

Only if no blocking conflict remains, print exactly:

```text
PHASE 3A ARCHITECTURE HARDENED — READY FOR SONNET IMPLEMENTATION
```

Then STOP.

Do not begin implementation automatically.
