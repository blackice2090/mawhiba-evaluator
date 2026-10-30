# Phase 3A — Methodology Review (architecture)

Status: the architecture gate is complete. Contracts and contract tests exist. The
pipeline, graph, prompts and Gold/eval do not exist yet.
Specification: `PHASE_3A_METHODOLOGY_REVIEW.md`. Decision record: ADR-022.
Contracts: `src/schemas/methodology_review.py`.
Tests: `tests/test_phase3a_contracts.py`.

## 1. Question and boundary

Is the student's *documented* methodology designed in a defensible way to test
the project's claims and its Phase 2J gap? Phase 3A covers design only. Execution
belongs to Phase 3B, results to Phase 3C, and scoring, readiness, Red Team, jury,
novelty and legal conclusions belong to later phases.

## 2. State location

The review run is stored at `ResearchRun.methodology_review: MethodologyReviewRun | None`.
`ResearchRun._consistent` checks that the review uses this research run, this
Phase 2J `gap_run_id` and this Phase 2I `nd_run_id`. `ProjectState` is never
written. `ProjectState.methodology.review_status` stays `NOT_EVALUATED`.

## 3. Authoritative input inventory

| # | Input | Authoritative source |
|---|---|---|
| 1 | Project type | `GapAssessmentRun.canonical_project_type`, which must equal `ProjectState.identity.project_type`. UNKNOWN or a mismatch gives `INSUFFICIENT_INPUT`. |
| 2 | Student methodology text | `EvaluationGraphState.submission`. The run binds `submission_artifact_id` and `submission_content_hash`, and every excerpt is a code-sliced span. |
| 3 | Claims | `ProjectState.claims`, bound as `BoundClaim(claim_id, claim_text_hash)` |
| 4 | Differentiating features | `NoveltyDifferentiationRun` (`ComparisonFeatureInventory`), referenced via Phase 2J `GapProjectLink.feature_id`. It provides context only. |
| 5 | Gap hypotheses | `GapAssessmentRun.hypotheses`, bound as `BoundGapTarget` by id |
| 6 | Validation requirements | `GapHypothesis.validation_requirement` (`GapValidationRequirement`: metric, baseline, condition ids) |
| 7 | Material conditions | `GapHypothesis.conditions` together with `condition_materiality`. These are referenced by id only, and no text is re-synthesized. |
| 8 | Project-gap linkage | `GapHypothesis.project_links` and `.linkage` |
| 9 | Baseline / comparator | `MethodologyBlock.baseline`, intake `baseline_mentions` and the Phase 2J `ValidationAnchor` baseline. Phase 3A binds student baseline text as submission excerpts. |
| 10 | AI/ML metadata | `ProjectState.identity.domain` (`AI_ML_DOMAINS`), plus `TechnicalBlock.models` and `.datasets` |
| 11 | Software / architecture | `ProjectState.identity.domain` (`SOFTWARE_SYSTEMS_DOMAINS`), plus `TechnicalBlock.architecture` and `.software` |

Phase 3A excludes `ProjectState.results` and `ProjectState.experiments` as
inputs. They hold execution and outcome data, and they must never repair a design
(section 26). External academic, patent, product and OSS evidence reaches Phase 3A
only through Phase 2J/2I identifiers. It can add context but never proves
execution.

## 4. Tracks and overlays

- `tracks_for`: SCIENTIFIC_RESEARCH maps to research, ENGINEERING_PROJECT to
  engineering, HYBRID to both, and UNKNOWN to no tracks.
- Each overlay has exactly one canonical `OverlayAssignment` (architecture A, hardened).
- Domain, the word "AI" and the presence of a model are only `signal_domains`.
  They never decide whether an overlay is material or who owns it.
- `materiality` is one of three values:
  - `MATERIAL_TO_TARGET`: requires bound target claim or Phase 2J hypothesis ids
    and bound excerpts;
  - `IMPLEMENTATION_TOOL_ONLY`: no owner, and the overlay's requirements are
    NOT_APPLICABLE;
  - `MATERIALITY_UNRESOLVED`.
- **Ownership** depends on the project type:
  - SCIENTIFIC_RESEARCH: a material overlay is owned by the research track
    (`SINGLE_TRACK_PROJECT`).
  - ENGINEERING_PROJECT: a material overlay is owned by the engineering track
    (`SINGLE_TRACK_PROJECT`). An engineering-only AI project therefore gets every
    applicable AI/ML requirement.
  - HYBRID: the owner is the track whose target the overlay serves, decided by
    `PHASE_2J_LIMITATION_FACET` or by `MODEL_ASSISTED_BOUNDED_JUDGMENT`:
    - With the facet basis, every served hypothesis must have a single Phase 2J
      facet that maps to the owner.
    - `SINGLE_TRACK_PROJECT` is forbidden.
    - There is no blanket "research when present" rule, and `overlay_track` was
      removed.
- **Software/systems overlay:** the same rule applies. A research-only project
  whose software methodology is material to a target has the overlay owned by the
  research track, because no engineering track exists.
- **No double counting:**
  - An overlay requirement is instantiated only in `counts_in`, which is the owner
    track, and only once.
  - Another track listed in `served_tracks` may cite the owner's documented
    requirement in a coverage link, but it never counts that requirement.
  - A track that is not served can neither count nor cite it.
- **Unresolved materiality or HYBRID ownership:**
  - The overlay's requirements resolve to CONDITIONAL with
    `OVERLAY_OWNERSHIP_UNRESOLVED` and no track.
  - No track may be `METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT` while that
    holds.
  - This way an overlay can neither escape review nor be counted twice.

## 5. Requirement catalog and applicability

`REQUIREMENT_CATALOG` has one `CatalogEntry` per `RequirementKind`, and an
import-time guard enforces this. The kinds cover:

- 24 research kinds;
- 22 engineering kinds;
- 26 AI/ML kinds;
- 9 software/systems kinds.

Applicability values are REQUIRED, CONDITIONAL, OPTIONAL and NOT_APPLICABLE.
`resolve_applicability` works as follows:

- An inactive track or overlay makes a requirement NOT_APPLICABLE.
- A non-conditional entry keeps its catalog default.
- A CONDITIONAL entry with undetermined triggers stays CONDITIONAL with
  `CONDITION_UNRESOLVED`.
- Otherwise, a CONDITIONAL entry resolves to REQUIRED if a catalog trigger fired,
  and to NOT_APPLICABLE if none did.

Hypothesis, randomization, blinding and control group are CONDITIONAL. The word
"experiment" is not a trigger.

A model judgment (`MODEL_ASSISTED_BOUNDED_JUDGMENT`) has three limits:

- It may only resolve a CONDITIONAL entry.
- It must cite catalog triggers and bound excerpts.
- It cannot lower a REQUIRED entry or name a kind outside the enum.

## 6. Documentation vs adequacy

`DocumentationStatus` and `DesignAdequacy` are separate. `_ALLOWED_ADEQUACY` fixes
which adequacy values each documentation status can reach. For example,
NOT_DOCUMENTED can never be ADEQUATELY_SPECIFIED, and CONFLICTING documentation is
always CONFLICTING_DESIGN. Excerpt counts are enforced:

- documented: at least 1;
- conflicting: at least 2;
- not documented, insufficient coverage or not applicable: 0.

## 7. Boundaries

- **Execution claims.** `StatementMode` is PLANNED, DESCRIBED_AS_EXECUTED or
  MODE_NOT_DETERMINED. `execution_verified` is a literal `False`.
  `STUDENT_EXECUTION_CLAIM_NOT_VERIFIED` is an informational issue.
- **Baseline (hardened).** There are four layers, never collapsed:
  1. **Documented.** `baseline_excerpt_ids` holds exact student spans.
  2. **Relevant to the target.** `relevance` is a bounded judgment. Its
     `relevance_context` must cite permitted context:
     - `TARGET_CLAIM_TEXT`;
     - `PHASE_2J_VALIDATION_BASELINE`;
     - `PHASE_2J_EXISTING_CAPABILITY`;
     - `STUDENT_RATIONALE_EXCERPT`.

     The baseline's name is not a context value, so relevance can never rest on
     the name alone.
  3. **Student rationale.** `rationale_excerpt_ids` is optional and is not a
     prerequisite for relevance. It is cited exactly when bound, so it is never
     fabricated. One exact excerpt may carry both the baseline and its rationale.
  4. **Fair execution.** `comparison_fairness_assessed` is a literal `False`
     (Phase 3B).

  No field references a prior-art candidate.
- **Metric.** The chain is target claim, then `outcome_excerpt_id`, then the
  metric. The metric is a student excerpt or a Phase 2J `GapValidationRequirement`
  id. There is no free-text metric field, so a vague claim ends
  `METRIC_NOT_DEFINED` or `TARGET_NOT_MEASURABLE_AS_STATED`.
- **Sample size.** SAMPLE and SAMPLE_SIZE_RATIONALE are separate kinds. A
  rationale whose excerpts are all bare quantities ("N = 500") is rejected.
- **Control and confounding.** These are documentation-level only.
  `confounding_eliminated` is a literal `False`.
- **Material conditions.** `MaterialConditionCoverage` refers to a Phase 2J
  condition by id. An unaddressed condition blocks DIRECTLY_TESTS_TARGET for that
  hypothesis and blocks the well-specified posture.
- **Phase 2J continuity.** The four stages stay distinct:
  1. Phase 2J validation requirement;
  2. Phase 3A planned coverage (`MetricAlignment.gap_validation_requirement_id`
     and `BoundGapTarget.requires_baseline`);
  3. Phase 3B execution;
  4. Phase 3C result.

  A requirement with no bounded plan raises METRIC_NOT_DEFINED,
  BASELINE_NOT_DOCUMENTED or MATERIAL_CONDITION_NOT_COVERED.

  The rule follows the inspected schema exactly. In `GapValidationRequirement`,
  `metric: ValidationAnchor` is **mandatory**, `baseline` is **optional**, and
  `condition_ids` may be empty. `GapHypothesis.validation_requirement` is itself
  optional. `BoundGapTarget.from_hypothesis` copies these properties unchanged:
  - `requires_metric` is true exactly when a requirement exists;
  - `requires_baseline` is true exactly when the requirement has a baseline;
  - `material_condition_ids` equals the requirement's `condition_ids`.

  Strong coverage of a gap target (`_require_phase_2j_continuity`) then needs:
  - an ALIGNED metric plan bound to that requirement id, with a bound outcome
    excerpt, whenever a requirement exists;
  - a documented and relevant baseline for that requirement id, only if the
    requirement has a baseline;
  - every condition in `condition_ids` addressed in design.

  Phase 3A adds no dimension of its own. A gap target with no requirement needs no
  metric, baseline or condition plan. Binding to the requirement by id alone, a
  mismatched metric or an unresolved baseline is not enough. Strong coverage of a
  claim target still needs an aligned claim metric (section 20).

## 8. Claim and gap coverage

`MethodologyCoverageLink` targets a CLAIM or a GAP_HYPOTHESIS. Its relation is a
bounded model judgment. The relation values are:

- DIRECTLY_TESTS_TARGET;
- PARTIALLY_TESTS_TARGET;
- RELEVANT_BUT_NOT_TESTING;
- DOES_NOT_TEST_TARGET;
- INSUFFICIENT_LINKAGE_EVIDENCE.

Strong (direct) coverage is structurally gated. It needs all of the following:

- a `tests_target` requirement kind;
- that kind documented in the same track, or an overlay kind that its owner
  documents for a served track;
- for a claim target, an aligned metric;
- for a gap target, the exact Phase 2J continuity rule in section 7.

Text unrelated to testing therefore cannot carry strong coverage. The gate does
not prove that the semantic judgment is correct.

## 9. Deterministic posture

`derive_track_posture`, applied in order:

1. If inputs are unbound, or every REQUIRED requirement is
   INSUFFICIENT_SOURCE_COVERAGE, the posture is `INSUFFICIENT_INPUT`.
2. If a CONFLICTING_METHOD_DESCRIPTION issue exists, or a REQUIRED requirement
   has conflicting documentation, the posture is `METHODOLOGY_CONFLICTING`.
3. If any HIGH/CRITICAL issue exists, or a REQUIRED requirement is missing or not
   documented, the posture is `METHODOLOGY_HAS_MAJOR_DESIGN_GAPS`.
4. Otherwise the posture is `METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT` only
   if all of these hold:
   - there are no issues;
   - every REQUIRED requirement is ADEQUATELY_SPECIFIED;
   - no CONDITIONAL requirement is unresolved;
   - there is at least one coverage link, and all links are direct;
   - every condition is addressed.
5. Anything else is `METHODOLOGY_PARTIALLY_SPECIFIED`.

`MethodologyTrackAssessment` rejects any posture that differs from the derived
one, and `model_proposed_posture` is only recorded. `ISSUE_SEVERITY` fixes the
severity of each issue code.

## 10. Prompt injection and model prose

- Instruction-like submission text is an ordinary excerpt and has no effect on
  synthesis.
- A rejected model output persists only a sha256 `response_digest`.
- A persisted excerpt must equal `submission[start:end]` under the bound hash
  (`StudentMethodologyExcerpt.matches`).
- No assessment type has a free-prose rationale or summary field.

## 11. Replay, checkpoint and immutability

- Ids come from `methodology_id(...)` (uuid5), so a replay builds identical
  records. Duplicate excerpt ids are rejected.
- Upstream bindings are taken at bind time and re-checked at finalize with
  `upstream_fingerprint`. `mutated_bindings` reports any upstream whose content
  changed, and the run then ends `INVALIDATED_UPSTREAM_MUTATED`.
- Every Phase 3A record carries `methodology_run_id`. The run validator rejects:
  - cross-run records;
  - excerpts from a different submission;
  - fabricated excerpt references;
  - stale claim hashes;
  - cross-claim gap, metric and condition references.
- Every type is checkpoint-reachable through `ResearchRun`. `CatalogEntry` is
  import-time policy and is listed in `NON_CHECKPOINTED_TYPES` with its reason.
- `external_search_calls` is a literal 0. The schema module imports no connector.

## 12. Planned Gold / eval (later milestone)

- At least 360 cases: at least 120 English, 120 Arabic and 120 mixed, with at
  least 160 semantic and control categories.
- The cases will be generated by `scripts/generate_phase3a_gold.py` into
  `evals/methodology_review/v1/`.
- Each case drives the real Phase 2E–2J graphs, then the real Phase 3A graph
  against a scripted untrusted model.
- Each case has two parts:
  - `expected`: what is correct given the scripted response;
  - `truth`: the separate semantic ground truth.
- Targets: at least 36 quality metrics, at least 100 release gates (each with a
  real non-zero denominator and no floors) and at least 180 negative-control
  attempts across at least 45 mechanisms.
- Model-judgment families (coverage relation, conditional applicability, metric
  alignment, baseline relevance) are reported honestly and are not required to be
  perfect.
