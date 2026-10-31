# ADR-023: Experiment review is a protocol-level posture

Status: Accepted (Phase 3B architecture gate)

## Context

Phase 3A (ADR-022) reviews the *design* of the documented methodology. The
project master then asks, per experiment, whether the concrete test protocol is
specified, controlled, measurable and reproducible, and whether it tests the
claim that matters and the Phase 2J validation requirement bound to it.

The submissions carry three things the review must keep apart: the protocol, the
student's statement that it was run, and the reported results. A reviewer who
reads "97% accuracy" next to a thin protocol is pulled towards approving the
protocol. A reviewer who reads "the device worked" is pulled towards calling it
validation. Phase 3B exists to make both moves impossible.

## Decision

1. **State.** `ExperimentReviewRun` lives on `ResearchRun.experiment_review`. It
   is never written to `ProjectState.experiments` and never reads the legacy
   `ProjectState.experiments` prefill or `ProjectState.results`. The legacy
   `ExperimentRecord` has `supports_claim_ids`, `evidence_ids` and an integer
   `sample_size`, which are exactly the conflations Phase 3B forbids.
2. **Inputs.** The verbatim submission (artifact id and hash), the bound claims,
   the Phase 2J run, and the Phase 3A run *as context*. All four are
   fingerprinted at bind and re-checked at finalize. Phase 3A documentation never
   satisfies a Phase 3B requirement, and Phase 3B re-slices its own excerpts.
3. **Identity.** `experiment_id = uuid5(run, protocol_key)`, where
   `protocol_key` is the hash of the defining excerpt *texts* in document order.
   Offsets and targets are excluded. Identical defining text is one experiment.
   One experiment can bind many targets through separate links, and one target
   can have many experiments. A changed protocol is a new experiment that names
   the earlier one in `revision_of`.
4. **Closed vocabularies.** There are 16 experiment types (including `UNKNOWN`)
   in six families, 68 requirement kinds in 11 groups, a family-by-kind
   applicability matrix, a type-override table that never lowers a REQUIRED
   cell, and 25 triggers. A model can resolve only a CONDITIONAL cell, and only by
   binding context. A REQUIRED cell is never lowered.
5. **Result quarantine.** A result span is stored as a `QuarantinedSpan`
   (offsets plus a hash, no text, `consumed_by_phase3b=False`). A protocol excerpt
   may not overlap one. No derivation function accepts quarantine or result
   arguments. `adequacy_fingerprint` excludes the quarantine, so changing a
   result value while keeping the protocol identical leaves adequacy unchanged.
6. **Execution boundary.** `execution_verified`, `independently_reproduced` and
   `leakage_prevented_in_practice` are literal `False`. No execution-evidence
   field exists. Raw data artifacts are not inputs in Phase 3B.
7. **Same-target only.** A `DIRECTLY_TESTS` link needs an aligned measurement
   binding for the same experiment *and* the same (claim, hypothesis,
   requirement) tuple. Every Phase 2J reference must belong to the claim it is
   used with.
8. **Phase 2J continuity.** Each bound Phase 2J validation requirement is copied
   by id and anchor hash, never rewritten. A hypothesis without a requirement
   produces no target. Coverage is derived. `COVERED_BY_EXPERIMENT` needs one
   experiment that covers every dimension (metric, baseline if required,
   conditions, adequate protocol). Dimensions are never pooled across
   experiments.
9. **Baseline.** Documented, relevant, comparable per property, execution
   described, execution verified (literal False) and result
   (`comparison_result_evaluated=False`) are six separate layers. Only metric
   identity may be deterministic. The comparability roll-up has no `FAIR` value.
10. **Postures.** Issues and postures are derived in code at every level. The
    precedence is `INSUFFICIENT_EVIDENCE > MAJOR_GAPS > UNRESOLVED >
    PARTIALLY_SPECIFIED > WELL_SPECIFIED`. Every aggregate is the worst of its
    members, so HYBRID tracks are never averaged.
11. **No dead enums.** Every issue code is emitted by `derive_experiment_issues`,
    every continuity reason by `derive_phase2j_coverage`, and every run-issue code
    names its emitting stage in `RUN_ISSUE_EMITTERS`. Tests prove that each one
    is reachable.

## Rejected alternatives

- **Targets in experiment identity.** This splits one experiment testing two
  claims into two experiments, which double counts it, and lets a linkage change
  rename an experiment.
- **Offsets in identity.** Adding a paragraph above the protocol, or changing a
  result value, would change the experiment's id.
- **Pooled Phase 2J coverage.** A metric from experiment A combined with a
  baseline from experiment B is not one test of the requirement.
- **Execution evidence references now.** "Artifact exists" is not "artifact
  authentic", and Phase 3B has no verification contract for authenticity.
- **One project adequacy number.** This would average a strong AI evaluation
  with a weak engineering validation.
- **Reusing ProjectState.experiments.** That type carries claim support and
  evidence links by construction.

## Consequences

Model judgments (segmentation, type, conditional applicability, linkage,
alignment, relevance, comparability, track ownership) are bounded and measured
honestly in Gold, but not proven. A result statement can never improve or worsen
Phase 3B. Result Review, Red Team, scoring and readiness stay later phases.
