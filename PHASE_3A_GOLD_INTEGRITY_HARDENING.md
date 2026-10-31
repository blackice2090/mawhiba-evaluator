# Phase 3A — Gold Integrity Hardening

## Purpose

This is a narrow Gold-integrity hardening pass after the first approved-looking Phase 3A Gold run and before committing the Gold milestone.

The current Gold results are strong, but three integrity items must be closed before the milestone is committed:

1. overlay negative-verdict safety must be language-neutral;
2. language variants must not inflate semantic-category coverage;
3. exact final test counts must be captured.

Do not run cross-phase regressions, the final repository suite, merge, or Phase 3B.

---

# EXECUTION DISCIPLINE — APPLY TO THIS PASS

- Stay on `feat/phase3a-methodology-review`.
- Keep scope limited to this Gold-integrity pass.
- Do not redesign Phase 3A.
- Make the smallest justified production/eval/data changes.
- Do not mutate Phase 2A–2J semantics.
- Do not weaken any production validator, provenance rule, deterministic synthesis rule, run binding, checkpoint safety, gate, metric, or control.
- Do not hard-code Gold case IDs or semantic answers into production.
- Gold expectations remain independent from production.
- Do not run cross-phase regressions.
- Do not run the full repository suite.
- Do not commit automatically.
- Do not merge.
- Do not start Phase 3B.

Testing sequence:

```text
minimal integrity fix
→ directly affected tests
→ Gold integrity tests
→ all Phase 3A Gold tests
→ language/workflow guards as affected
→ one final full Phase 3A offline Gold run if code/data changed
→ final Gold integrity checkpoint
→ STOP
```

---

# 1. Make Overlay Negative-Verdict Semantics Language-Neutral

## Current problem

Both AI/ML and software/systems overlays are reviewed for every project, which correctly removed silent discovery misses.

However, the current contract still distinguishes a "signaled" overlay from an "unsignaled" overlay when validating a negative verdict.

The signal uses, among other things, an English lexicon.

This creates a language-dependent safety boundary:

```text
English wording recognized by lexicon
→ stricter negative-verdict path

Arabic or unseen wording with no metadata signal
→ may be treated as unsignaled
→ NO_METHODOLOGY_RELEVANCE can be accepted through a more permissive path
```

That is not acceptable.

A semantic trust rule must not become weaker merely because the project is written in Arabic, mixed language, or uses an unseen synonym.

## Required invariant

The acceptance contract for:

`NO_METHODOLOGY_RELEVANCE`

must be language-neutral.

Metadata or lexical signals may be retained for:
- diagnostics;
- test stratification;
- prompt context;
- cost/telemetry;

but they must not change the safety criteria required to accept a negative materiality verdict.

The same structured negative-verdict contract must apply to:
- English;
- Arabic;
- mixed;
- unseen synonym/paraphrase;
- metadata-present;
- metadata-absent.

## Recommended bounded contract

Because a negative absence claim cannot cite a positive methodology excerpt, require the model to explicitly demonstrate bounded review scope rather than fabricate evidence.

For each negative overlay verdict, require typed fields equivalent to:

- overlay kind;
- verdict = `NO_METHODOLOGY_RELEVANCE`;
- complete set of bound target claim IDs and/or Phase 2J hypothesis IDs that were considered;
- run/research binding;
- no free-form canonical rationale.

Deterministically verify:

1. the reviewed target IDs exist;
2. they belong to the current run/research;
3. the reviewed target set covers every Phase 3A target relevant to overlay materiality under the approved input contract;
4. no target from another run is included;
5. omission of a required target makes the negative unresolved/rejected;
6. the rule is identical across languages.

If the existing DTO already has equivalent complete-review fields, reuse them rather than adding redundant fields.

Do not require an invented "absence excerpt".

Do not make keyword presence or absence a proof of materiality/non-materiality.

## Positive/tool-only verdicts

Keep existing positive/tool-only evidence requirements:

- MATERIAL requires a bound target and verified exact excerpt;
- IMPLEMENTATION_TOOL_ONLY requires verified exact excerpt and approved typed semantics;
- omission/refusal/error/bound exhaustion remains UNRESOLVED.

## Wrong negative remains a model-judgment error

Even after complete target-set review, a semantically wrong negative is still possible.

That is acceptable as a measured model-judgment limitation.

The goal here is not to make semantic negatives infallible.

The goal is to ensure:

```text
wrong negative risk is bounded identically across languages
```

and never weakened by an English-only lexical gate.

## Required tests

Add tests proving:

1. English negative verdict uses the same validation contract as Arabic.
2. Arabic negative verdict uses the same validation contract as English.
3. Mixed-language negative verdict uses the same validation contract.
4. Unseen English synonym does not change negative-verdict safety.
5. Lexicon hit does not impose a different trust contract.
6. Missing metadata does not impose a different trust contract.
7. Negative verdict omitting one bound target is rejected/unresolved.
8. Negative verdict using a cross-run target is rejected.
9. Complete bounded negative can resolve non-material in all three language modes.
10. Keyword-only text still cannot establish MATERIAL.
11. Wrong but structurally valid negative remains measurable as `MODEL_JUDGMENT_ERROR`, not silently reclassified as deterministic truth.
12. provider omission/refusal/error remains UNRESOLVED.
13. engineering-only and Hybrid ownership behavior remains unchanged.

## Gold metric requirement

Keep reporting:

- AI/ML materiality recall/precision;
- software materiality recall/precision;
- NO_METHODOLOGY_RELEVANCE accuracy.

Add or confirm a language-parity metric/table for negative overlay judgments:

- English negative accuracy;
- Arabic negative accuracy;
- mixed negative accuracy.

These are model-judgment metrics, not forced to 1.0.

---

# 2. Prove Semantic Category Coverage Is Not Translation Padding

## Current concern

The dataset has:

- 777 cases;
- 258 English;
- 260 Arabic;
- 259 mixed;
- 469 categories.

The checkpoint also states that many templates are rendered in all three languages and translation-only padding is only partly addressed.

Language variants are useful for multilingual invariance and prompt-injection testing, but they must not artificially inflate the claimed count of distinct semantic/control categories.

## Required correction

Introduce or derive a language-neutral:

`semantic_family_id`

or equivalent normalized category identity.

The identity must describe the mechanism/scenario independent of language.

English/Arabic/mixed versions of the same semantic scenario must share the same semantic-family identity.

## Required dataset reporting

Report both:

- total cases;
- raw category labels if retained;
- **language-normalized distinct semantic families**.

The Phase 3A Gold requirement of `>=220 distinct semantic/control categories` must be satisfied by language-normalized semantic families, not by counting translations as separate semantics.

## Language-specific value

Also report:

- number of English-specific semantic cases;
- number of Arabic-specific semantic cases;
- number of mixed-specific semantic cases;
- number of multilingual parity families intentionally rendered in multiple languages.

Do not require every case to be language-unique.

Multilingual versions are valid when they test:
- language parity;
- Arabic/mixed prompt injection;
- exact anchoring;
- language-independent safety;
- model semantic behavior.

They simply must not inflate semantic diversity counts.

## Required tests

Add tests proving:

1. semantic-family ID is language-neutral;
2. translated variants share one semantic-family ID;
3. normalized semantic-family count is >=220;
4. each language still has >=150 cases;
5. each language contains meaningful non-translation-specific cases;
6. duplicate detector still reports zero exact duplicates;
7. category minimum cannot be satisfied by renaming the same semantic family per language.

If current data already satisfies these requirements, update the harness/report without inventing unnecessary cases.

---

# 3. Capture Exact Final Test Counts

The current checkpoint says the Gold/language-policy tests passed but did not capture exact skip counts.

Before committing Gold, capture exact counts for every final test group actually used as release evidence.

At minimum report exact:

- passed;
- skipped;
- failed;
- errors;
- exit code where available;

for:

1. Phase 3A Gold/eval tests;
2. all `tests/test_phase3a_*.py`;
3. language-policy guard;
4. workflow-hardening guard if run;
5. directly affected production/LLM tests after the language-neutral negative-verdict change.

Do not rerun unrelated historical phases.

If code/data changes in this hardening pass, run the complete Phase 3A offline Gold once after all targeted fixes stabilize.

---

# 4. Re-validate Gold Integrity

After the corrections, verify:

## Dataset
- >=450 total cases;
- >=150 English;
- >=150 Arabic;
- >=150 mixed;
- >=220 **language-normalized semantic families**;
- zero exact duplicates;
- authoring independence intact.

## Quality
- all deterministic metric families = 1.0;
- no unmeasured required metric;
- model-judgment metrics reported honestly;
- negative overlay quality reported per language.

## Release gates
- >=140 gates;
- every required gate has real denominator > 0;
- zero violations;
- no denominator floors;
- thin gates explicitly listed.

## Negative controls
- >=240 attempts;
- >=60 distinct mechanisms;
- all caught for intended reason;
- five non-vacuity mutation checks still pass.

## Safety
- language-neutral overlay negative contract;
- no result/experiment leakage;
- execution never verified;
- exact anchoring;
- Phase 2J continuity;
- replay/immutability;
- external search = 0;
- prompt injection safe across English/Arabic/mixed.

---

# 5. Production Change Classification

If the language-neutral negative-verdict correction changes production code, classify it honestly in the Gold report as:

`PRODUCTION_IMPLEMENTATION_DEFECT`

with root cause:

> Overlay negative-verdict acceptance depended on a language-sensitive signal/lexicon path.

Add a targeted regression test.

Do not amend `b9e59ff`.

Keep the fix as part of the later Gold milestone commit after approval.

---

# 6. Git Hygiene

Before the final checkpoint:

- remain on `feat/phase3a-methodology-review`;
- verify main remains `91423770758ed39e459401cc3b9b9de84c478715`;
- one worktree;
- do not stage or commit;
- do not include unrelated `homepage-preview/`;
- leave unrelated untracked paths untouched.

Report `homepage-preview/` explicitly as unrelated and excluded.

---

# 7. Required Output

Print:

```text
PHASE 3A GOLD INTEGRITY HARDENING CHECKPOINT
```

Include:

## Language-neutral overlay negative semantics
- old rule;
- final rule;
- whether production changed;
- exact DTO/validator change;
- English/Arabic/mixed parity tests;
- negative accuracy by language.

## Semantic diversity
- total cases;
- English/Arabic/mixed counts;
- raw category count;
- normalized semantic-family count;
- language-specific semantic-case counts;
- multilingual parity-family count;
- duplicate count.

## Quality
- deterministic metric count/result;
- model-judgment metric count/results;
- negative overlay metrics per language.

## Gates
- total gates;
- zero violations;
- zero-denominator count;
- thin gates;
- no-floor confirmation.

## Negative controls
- attempts;
- caught;
- mechanisms;
- non-vacuity results.

## Tests actually run
Exact:
- passed;
- skipped;
- failed;
- errors;
- exit code where available.

## Bugs/fixes
List any new:
- production defect;
- Gold fixture defect;
- expectation defect;
- harness defect;
- gate predicate defect;
- model judgment error.

## Git
- branch;
- implementation baseline;
- main SHA;
- working tree status;
- worktree count;
- unrelated `homepage-preview/` excluded;
- no commit;
- no merge.

## Remaining limitations
List bounded limitations only.

Then print:

```text
PHASE 3A GOLD CHECKPOINT COMPLETE
```

Only if:
- overlay negative safety is language-neutral;
- normalized semantic families >=220;
- all deterministic metrics pass;
- all release gates have real nonzero denominators and zero violations;
- all negative controls pass for intended reasons;
- no blocking production/Gold integrity defect remains;

print exactly:

```text
PHASE 3A GOLD / OFFLINE EVAL APPROVED — SAFE TO COMMIT GOLD MILESTONE
```

Then STOP.

Do not commit automatically.
Do not run cross-phase regressions.
Do not run the full repository suite.
Do not merge.
Do not start Phase 3B.
