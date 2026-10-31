# ADR-022 — Methodology Review Is a Design-Level Posture, Not Execution or Result Evidence

Status: accepted (Phase 3A architecture gate).

## Context

After Phase 2J establishes an evidence-bounded gap, the next question is whether
the student's *documented* methodology is designed to test the claims and that
gap. The easy shortcuts all overstate: a methodology sentence in the past tense
reads like execution evidence; a missing paragraph reads like "the student did not
do it"; a named metric, a sample size or a baseline reads like adequacy; a good
result reads like a good design; a HYBRID project invites one averaged verdict.

## Decision

1. **State location.** `MethodologyReviewRun` lives on
   `ResearchRun.methodology_review`, never in `ProjectState.methodology`, for the
   same ownership reason as every phase since 2B (ADR-010). The research run
   validator rejects a review bound to another research run, Phase 2J run or
   Phase 2I run.
2. **Authoritative source.** Student methodology text is the verbatim
   `EvaluationGraphState.submission.original_text`, bound by `artifact_id` and
   `content_hash`. Phase 1B intake extracts no methodology fields except baseline
   and metric mentions, so `ProjectState.methodology` cannot be the anchor source.
   Every excerpt is a code-sliced span located with the Phase 2I `locate`
   function. A repeated excerpt binds only by validated offsets or occurrence
   index.
3. **Project type is inherited**, from Phase 2J's `canonical_project_type`, which
   must equal `ProjectState.identity.project_type`. `tracks_for` maps it to tracks.
   UNKNOWN yields no tracks and `INSUFFICIENT_INPUT`.
4. **Requirement catalog.** A closed `RequirementKind` enum and one
   `CatalogEntry` per kind give the home track or overlay, the default
   applicability and, for CONDITIONAL entries, a closed trigger set. Resolution is
   deterministic. A model may only resolve a CONDITIONAL entry to REQUIRED or
   NOT_APPLICABLE, with bound context and catalog triggers. It can never lower a
   REQUIRED entry or invent a kind.
5. **Documentation is separate from adequacy.** These are two enums, and
   `_ALLOWED_ADEQUACY` sets which adequacy values each documentation status can
   reach. `NOT_DOCUMENTED_IN_BOUND_INPUT` qualifies the input. Every run carries
   `NOT_DOCUMENTED_MEANING` to say so.
6. **Execution and results are out of scope by construction.**
   `execution_verified`, `confounding_eliminated`,
   `leakage_prevented_in_practice` and `comparison_fairness_assessed` are literal
   `False`. No Phase 3A type has a result, accuracy, score or verdict field.
   `derive_track_posture` takes no result argument.
7. **Coverage is model-assisted and bounded.** `MethodologyCoverageLink`,
   `MetricAlignment`, `BaselineComparatorRecord` and `MaterialConditionCoverage`
   carry `MODEL_ASSISTED_BOUNDED_JUDGMENT`. Their IDs, hashes and spans are
   verified, but their semantics are not. Strong coverage additionally requires:
   - a target-testing requirement kind that the track documents;
   - an aligned metric for the target;
   - every Phase 2J material condition addressed in design.
8. **Overlay ownership (hardening).** Each overlay has one canonical
   `OverlayAssignment`:
   - Materiality rests on bound targets and excerpts, never on domain alone.
   - The owner is the only track for a single-track project.
   - For HYBRID, the owner is the track served, decided by Phase 2J facet or
     bounded judgment.
   - Unresolved materiality or ownership leaves the requirements CONDITIONAL and
     forbids a well-specified track.
   - Requirements are counted only in the owner track. Served tracks may cite them
     but never count them.
9. **Exact Phase 2J continuity (hardening).** Strong gap coverage covers the bound
   `GapValidationRequirement` exactly:
   - the metric is always required, because the Phase 2J schema makes it
     mandatory;
   - the baseline only when Phase 2J has one;
   - its `condition_ids`.

   Each needs a semantic plan, not just an id reference.
10. **Baseline relevance (hardening).** Relevance is a bounded judgment over
    permitted context and is never inferred from the name. A student rationale is
    optional, never fabricated, and may share the baseline's excerpt. Fairness
    stays unassessed.
11. **Posture is derived in code, per track.** For HYBRID, both track assessments
   are kept and there is no combined posture field. Issue severity is a fixed
   function of the issue class.

## Rejected alternatives

- *Write into `ProjectState.methodology.review_status`.* Rejected because it mixes
  run-scoped review with canonical project truth, and Phase 3A would become a
  `ProjectState` writer.
- *Anchor to `ProjectState.methodology` Tracked fields.* Rejected because they
  have no offsets or hash and intake never populates most of them.
- *One project posture for HYBRID.* Rejected because averaging hides a weak track.
- *A numeric methodology score.* Rejected because scoring belongs to a later,
  explicitly reviewed phase.
