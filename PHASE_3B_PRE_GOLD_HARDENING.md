# Phase 3B — Pre-Gold Security & Trust Hardening

## Status

Narrow pre-Gold hardening pass only.

Repository:
- `mawhiba-evaluator`

Branch:
- `feat/phase3b-experiment-review`

Main baseline:
- `9d9e64eb16acedcb85007112f874762336a20d74`

Approved Phase 3B architecture commit:
- `7641ef5` — `feat(experiments): establish Phase 3B architecture contracts`

Current Phase 3B implementation commit:
- `de1f734` — `feat(experiments): implement Phase 3B experiment review`

The previous implementation approval is superseded by a post-commit security review that identified three real production defects:

1. prompt boundary leak in `protocol.py`;
2. displayed-vs-anchored range mismatch in `protocol.py`;
3. fail-open result quarantine in `segment.py`.

Issue #3 is blocking because an unquarantined result span can remain visible to later stages and the run can still reach a strong posture.

Do not begin Gold until this hardening checkpoint passes.

---

# 1. Goal

Close the three concrete security/trust defects without redesigning Phase 3B.

The hardening must restore these invariants:

```text
Student text is always untrusted data.

Model-visible text range == anchorable text range.

Result quarantine is fail-closed.

Unquarantined result evidence can never coexist with WELL_SPECIFIED.

Result content can never influence protocol adequacy.

Canonical evidence can never point outside text shown to the model.
```

---

# 2. EXECUTION DISCIPLINE — APPLY TO THIS PASS

- Stay on `feat/phase3b-experiment-review`.
- Start from `de1f734`.
- Keep scope limited to the three listed defects and directly required tests/docs.
- Do not redesign Phase 3B.
- Do not weaken any existing test, validator, assertion, schema rule, quarantine rule, Phase 2J continuity rule, posture rule, or prompt-safety boundary.
- Do not create Gold.
- Do not run cross-phase regressions.
- Do not run the full repository suite.
- Do not merge.
- Do not push.
- Do not touch `homepage-preview/`.
- Do not amend or rewrite `7641ef5` or `de1f734`.
- Do not create a commit automatically.
- Do not start Result Review.
- Do not add `Co-Authored-By` or any AI attribution if a later commit is explicitly approved.

Testing order:

```text
Fix defect 1
→ targeted regression

Fix defect 2
→ targeted regression

Fix defect 3
→ targeted regression

→ all Phase 3B production/architecture tests
→ required guards
→ trust audits A–H
→ dedicated security mutation checks
→ hardening checkpoint
→ STOP
```

Do not repeatedly run broad suites between small edits.

---

# 3. DEFECT 1 — Untrusted Prompt Boundary Leak

## Problem

`protocol.py` currently places student-owned experiment/defining excerpts outside the explicit untrusted-content boundary.

Even though output validation remains strict, the model sees student text outside the boundary and may interpret it as instruction-like content.

This violates:

```text
student text = data, never instruction
```

## Required fix

All student-controlled text shown to the model must appear only inside an explicit untrusted-data container.

This includes:

- submission text;
- defining excerpts;
- protocol excerpts;
- any student-originated text exposed from upstream context;
- student-supplied labels or names;
- any copied student prose in model task context.

Trusted code-built metadata may remain outside the untrusted block:

- experiment IDs;
- requirement enum names;
- claim IDs;
- hypothesis IDs;
- validation requirement IDs;
- closed enum values;
- code-generated labels that contain no student text.

## Marker sanitization

Before inserting any untrusted text into the prompt, neutralize or escape the exact boundary marker strings.

A student must not be able to include text equivalent to the actual end marker and break out of the untrusted block.

Do not solve this with a fragile English-only keyword blacklist.

Use structural escaping/encoding appropriate to the repository's prompt format.

Canonical source evidence must remain the original exact student text, not the escaped prompt representation.

## Required tests

Add targeted tests proving:

1. defining experiment excerpts appear only inside the untrusted block;
2. protocol excerpts appear only inside the untrusted block;
3. trusted prompt instructions contain no raw student prose;
4. a student excerpt containing the literal end-marker cannot close the untrusted block;
5. English prompt injection stays data;
6. Arabic prompt injection stays data;
7. mixed prompt injection stays data;
8. canonical source anchoring still uses the original unescaped text;
9. model output validation remains unchanged.

---

# 4. DEFECT 2 — Model-Visible Range vs Anchorable Range Mismatch

## Problem

The current path is effectively:

```text
mask result spans
→ truncate masked text to model character limit
→ model sees truncated masked text
→ verifier can anchor against a broader/original source range
```

This creates a parser differential.

Required invariant:

```text
If the model can cite an excerpt,
that excerpt must have been inside the exact model-visible source window.
```

## Required fix

Define one deterministic model-visible source window before masking.

Correct order:

```text
authoritative source
→ choose deterministic source window
→ record original source window [start, end)
→ apply result masking inside that window
→ build model prompt
```

The verifier must only accept excerpt references wholly contained in the original unmasked source window.

Do not anchor against content outside the shown window.

## Requirements

The implementation must retain:

- exact original artifact coordinates;
- exact original text for canonical source evidence;
- model-visible masked representation separately;
- deterministic window boundaries.

The masked representation is for model input only.

The original representation is for exact-source verification.

## Required tests

Add tests proving:

1. excerpt fully inside visible window is accepted;
2. excerpt beginning before visible window is rejected;
3. excerpt ending after visible window is rejected;
4. excerpt fully outside visible window is rejected;
5. result masking does not shift canonical offsets;
6. truncation before masking preserves original coordinates;
7. repeated excerpt outside the window cannot be selected as a substitute;
8. model-list ordering cannot change window/anchor behavior;
9. replay produces the same source window.

---

# 5. DEFECT 3 — Fail-Open Result Quarantine

## Problem

This is blocking.

Current behavior can silently drop a model-reported result span when the code cannot locate the quoted result text.

A dropped result may remain visible to later protocol extraction/linkage and can contaminate adequacy.

## Required invariant

Result quarantine must be fail-closed:

```text
quarantine incomplete
→ affected experiment/run is UNRESOLVED or INSUFFICIENT_EVIDENCE
→ never WELL_SPECIFIED
```

Use the exact posture/failure semantics already approved by the architecture.

Do not invent a new architecture unless necessary.

---

# 6. Result-Span Location Rules

## Exact occurrence handling

When the segmentation model identifies result text:

1. verify the returned text is derived from the authoritative submission;
2. locate **all exact occurrences** inside the permitted source scope;
3. quarantine every matching occurrence conservatively;
4. store only approved canonical quarantine metadata:
   - offsets;
   - hash;
   - no canonical result prose.

If the same exact result sentence occurs multiple times, quarantine all occurrences.

Do not choose first occurrence only.

## No-match handling

If a model-declared result span cannot be safely located:

- do not silently discard it;
- record a deterministic incomplete-quarantine signal using existing run-issue/failure semantics where possible;
- preserve only a rejection digest or bounded diagnostic, not raw model prose;
- fail closed;
- ensure the run cannot reach `WELL_SPECIFIED`.

If the architecture already has a generic code such as `PARTIAL_MODEL_OUTPUT` that truthfully represents this condition and caps the posture correctly, reuse it.

If existing issue codes cannot truthfully represent incomplete quarantine, STOP and report an architecture contract gap before adding a new enum.

## Ambiguous/repeated result text

Repeated result text is not an error by itself.

Conservatively quarantine all exact occurrences inside the permitted source scope.

If an occurrence overlaps a defining/protocol excerpt:

- result quarantine wins;
- the protocol excerpt must be refused or the experiment must remain unresolved according to existing rules.

---

# 7. Quarantine Completeness State

The run must have a deterministic way to know whether result quarantine completed successfully.

Prefer reusing existing canonical fields if they already represent this.

If a new internal/non-persisted flag is sufficient, do not expand the public schema unnecessarily.

Possible invariant:

```text
quarantine_complete = true
```

is required before a strong posture can be produced.

If any of the following occurs:

- result span cannot be anchored;
- result span is outside allowed scope;
- model result output is structurally partial;
- result span verification fails;

then:

```text
quarantine_complete = false
```

and synthesis/finalize must fail closed.

Do not interpret `quarantine_complete=true` as proof that the segmentation model found every real result in the document.

It only means:

> every result span the segmentation output declared was safely processed.

The known limitation remains that the model may fail to identify a result span at all.

That is a model-recall limitation to measure in Gold.

---

# 8. Strong-Posture Safety Gate

Add a deterministic production guard:

```text
incomplete result quarantine
→ WELL_SPECIFIED impossible
```

Do not rely only on prompt instructions.

Do not rely only on model behavior.

This must be enforced in code.

Add a mutation/non-vacuity test:

- disable this guard;
- confirm a crafted incomplete-quarantine case can incorrectly reach a stronger posture;
- restore the guard;
- confirm the case fails closed.

---

# 9. Result Mutation Invariance

Re-run and strengthen Audit A.

Required cases:

## A1 — benign result mutation

```text
accuracy 97%
→ accuracy 41%
```

with protocol unchanged.

Expected:

- same experiment identity where result text is not identity;
- same adequacy fingerprint;
- same requirement assessments;
- same track posture;
- same project posture.

## A2 — positive to negative outcome

```text
improved by 20%
→ worsened by 20%
```

Expected same Phase 3B protocol adequacy.

## A3 — result table mutation

Change numeric table cells only.

Expected same protocol adequacy.

## A4 — adversarial result instruction

Result text contains an instruction telling the model to mark the protocol adequate.

Expected:
- quarantined/untrusted;
- no effect on adequacy;
- no raw result text in canonical state.

---

# 10. Prompt Boundary + Quarantine Interaction

Add an end-to-end regression where:

- a result sentence contains prompt injection;
- the same sentence is repeated;
- one occurrence is near the source-window boundary.

Expected:

- all model-declared exact result occurrences within scope are quarantined;
- none are available as protocol evidence;
- boundary markers cannot be escaped;
- out-of-window excerpt cannot be anchored;
- no strong posture if quarantine processing is incomplete.

---

# 11. Parser Differential Hardening

Ensure that every stage agrees on:

- source window;
- offset basis;
- artifact hash;
- masking transformation;
- exact-source verification scope.

Do not let prompt builder and verifier use different effective documents.

Add one shared deterministic source-window representation/helper rather than recomputing the range differently in multiple modules.

Reuse an existing abstraction if one already exists.

Avoid broad refactoring.

---

# 12. No Architecture Drift

The architecture checkpoint remains authoritative:

- seven graph stages;
- `ResearchRun.experiment_review`;
- result values never consumed;
- execution verification flags false;
- Phase 2J continuity per experiment;
- no mosaic coverage;
- deterministic final posture;
- max provider requests bounded by 40;
- external search/network attempts 0.

Do not change ADR-023 unless a genuine architecture contradiction is discovered.

If one is discovered, STOP and report:

```text
ARCHITECTURE_CONTRACT_DEFECT
```

before editing the ADR/schema.

---

# 13. Required Targeted Test Groups

After fixes stabilize, run exact counts for:

## Phase 3B
- `tests/test_phase3b_architecture.py`
- Phase 3B pipeline tests
- Phase 3B trust tests
- Phase 3B safety tests
- new hardening/security tests

## Shared guards affected by this change
- `tests/test_workflow_hardening.py`
- `tests/test_language_policy.py`
- `tests/test_llm_layer.py` if prompts/contracts changed
- relevant registry tests only if registry code changed

Do not run:
- cross-phase regressions;
- Phase 3A Gold;
- Phase 3B Gold;
- full repository suite.

---

# 14. Trust Audits A–H

Re-run all eight existing implementation trust audits:

A. Result mutation  
B. Cross-target metric  
C. Mosaic coverage  
D. Bare quantity  
E. Strong past-tense execution prose  
F. Baseline name only  
G. Provider omitted judgment  
H. Hybrid strong/weak tracks

All eight must still pass.

---

# 15. Additional Security Audits I–K

## I — Prompt Boundary Isolation

Confirm no raw student text appears outside the untrusted-content container in Phase 3B prompts.

## J — Visible Range / Anchor Parity

Confirm every accepted excerpt lies fully inside the exact source window shown to the model.

## K — Quarantine Fail-Closed

Create a segmentation output with a declared result span that cannot be located.

Expected:
- incomplete quarantine recorded;
- no silent drop;
- no WELL_SPECIFIED;
- later protocol extraction cannot consume that result as evidence.

---

# 16. Defect Classification

Classify all three findings as:

```text
PRODUCTION_IMPLEMENTATION_DEFECT
```

Finding 1:
student-controlled text escaped the approved untrusted prompt boundary.

Finding 2:
model-visible source scope and verifier anchor scope were inconsistent.

Finding 3:
result quarantine failed open when model-declared result text could not be anchored.

If testing reveals a schema/ADR limitation that prevents a truthful fail-closed representation, classify that separately as:

```text
ARCHITECTURE_CONTRACT_DEFECT
```

Do not hide an architecture defect inside implementation code.

---

# 17. Documentation

Update `docs/phase3b_experiment_review.md` only to describe implemented behavior.

Document:

- structural untrusted prompt boundary;
- source-window/anchor parity;
- fail-closed quarantine;
- conservative all-occurrence quarantine;
- incomplete quarantine posture effect;
- known limitation that undeclared/unrecognized results depend on segmentation recall.

Do not claim Gold-level coverage.

Do not claim result segmentation recall is perfect.

---

# 18. Git Discipline

Before hardening verify:

- branch = `feat/phase3b-experiment-review`;
- architecture commit `7641ef5` remains ancestor;
- implementation commit `de1f734` remains ancestor/current baseline;
- main remains `9d9e64eb16acedcb85007112f874762336a20d74`;
- one worktree;
- no unrelated tracked modifications;
- `homepage-preview/` untouched.

`PHASE_3B_IMPLEMENTATION_SPEC.md` may remain untracked from the previous milestone.

This hardening spec may also remain untracked until explicitly approved for commit.

Do not stage or commit automatically.

Do not amend `de1f734`.

---

# 19. Hardening Approval Conditions

Only approve pre-Gold hardening if all are true:

- no student text escapes the untrusted prompt boundary;
- prompt-boundary marker injection is structurally neutralized;
- model-visible source window and verifier anchor scope are identical;
- out-of-window excerpts are rejected;
- repeated result occurrences are all quarantined;
- unlocatable declared result spans fail closed;
- incomplete quarantine cannot produce WELL_SPECIFIED;
- result mutation invariance holds;
- all Phase 3B targeted tests pass;
- required guards pass;
- trust audits A–H pass;
- security audits I–K pass;
- no architecture contradiction remains;
- no Gold/full-suite/cross-phase run occurred.

---

# 20. Required Output

Print:

```text
PHASE 3B PRE-GOLD SECURITY HARDENING CHECKPOINT
```

Include:

## Git
- branch;
- main baseline;
- architecture commit;
- implementation commit;
- working tree;
- worktree count;
- untracked Phase 3B specs;
- `homepage-preview/`.

## Security finding 1 — prompt boundary
- old behavior;
- fix;
- exact files;
- structural invariant;
- tests.

## Security finding 2 — source range
- old behavior;
- fix;
- shared source-window representation;
- out-of-window behavior;
- tests.

## Security finding 3 — result quarantine
- old fail-open path;
- final fail-closed path;
- repeated occurrence handling;
- no-match handling;
- posture cap;
- tests.

## Tests actually run
For each group:
- passed;
- skipped;
- failed;
- errors;
- exit code.

## Trust audits
- A–H individually;
- I–K individually.

## Defects
For every defect:
- classification;
- root cause;
- production changed;
- architecture changed or not.

## Known limitations
Must include:
- segmentation recall is not proven;
- execution authenticity not verified;
- results not evaluated;
- model semantic judgments remain bounded;
- no external search;
- no legal/scoring/readiness conclusions.

Then print:

```text
PHASE 3B PRE-GOLD HARDENING COMPLETE
```

Only if every hardening condition passes, print exactly:

```text
PHASE 3B PRE-GOLD HARDENING APPROVED — READY FOR GOLD SPEC
```

Then STOP.

Do not commit automatically.
Do not generate Gold.
Do not run cross-phase regressions.
Do not run the full repository suite.
Do not merge.
Do not start Result Review.
