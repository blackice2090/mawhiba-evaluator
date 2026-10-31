"""Deterministic Phase 3A synthesis: component completion, continuity, issues, posture.

Everything here is a pure function of validated records. There is no model call,
no result input and no model-proposed posture: ``derive_track_posture`` (the
single rule in the contract module) decides every track's posture, and an issue's
severity is fixed by its class. A good result, a working prototype or a model's
rationale has no channel into any function in this module (ADR-022).
"""

from __future__ import annotations

from src.research.methodology.inventory import gap_target_tracks
from src.schemas.methodology_review import (
    ISSUE_SEVERITY,
    REQUIREMENT_CATALOG,
    Applicability,
    BaselineComparatorRecord,
    BaselineRelevance,
    BoundGapTarget,
    ConditionCoverageStatus,
    CoverageRelation,
    DesignAdequacy,
    DocumentationStatus,
    MaterialConditionCoverage,
    MethodologyCoverageLink,
    MethodologyIssue,
    MethodologyIssueCode,
    MethodologyPosture,
    MethodologyReviewRun,
    MethodologyTrack,
    MethodologyTrackAssessment,
    MetricAlignment,
    MetricAlignmentStatus,
    RequirementApplicability,
    RequirementDocumentation,
    RequirementKind,
    _require_phase_2j_continuity,
    cap_for_unresolved_overlay,
    derive_track_posture,
    methodology_id,
)

K = RequirementKind
C = MethodologyIssueCode

NOT_DOCUMENTED_CODE: dict[RequirementKind, MethodologyIssueCode] = {
    K.SAMPLE_SIZE_RATIONALE: C.SAMPLE_RATIONALE_NOT_DOCUMENTED,
    K.CONTROL_OR_COMPARISON_GROUP: C.CONTROL_STRATEGY_NOT_DOCUMENTED,
    K.CONFOUNDER_HANDLING: C.CONFOUNDER_HANDLING_NOT_DOCUMENTED,
    K.CONTROLLED_VARIABLES: C.CONFOUNDER_HANDLING_NOT_DOCUMENTED,
    K.TEST_SET_ISOLATION_FROM_TUNING: C.TEST_SET_ISOLATION_NOT_DOCUMENTED,
    K.DATA_LEAKAGE_PREVENTION: C.DATA_LEAKAGE_RISK,
    K.DUPLICATE_LEAKAGE_PREVENTION: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
    K.GROUP_AWARE_SPLIT: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
    K.TEMPORAL_SPLIT: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
    K.BASELINE_OR_ALTERNATIVE_DESIGN: C.BASELINE_NOT_DOCUMENTED,
    K.BASELINE_MODEL: C.BASELINE_NOT_DOCUMENTED,
    K.EXISTING_ALTERNATIVES_COMPARISON: C.BASELINE_NOT_DOCUMENTED,
    K.EVALUATION_METRICS: C.METRIC_NOT_DEFINED,
    K.RESEARCH_REPRODUCIBILITY_PLAN: C.REPRODUCIBILITY_NOT_DOCUMENTED,
    K.CONFIGURATION_REPRODUCIBILITY_PLAN: C.REPRODUCIBILITY_NOT_DOCUMENTED,
    K.ML_REPRODUCIBILITY_SEEDS_VERSIONS: C.REPRODUCIBILITY_NOT_DOCUMENTED,
}
"""A required requirement that is absent from the bound input: the specific issue class
when the taxonomy has one, REQUIRED_COMPONENT_NOT_DOCUMENTED otherwise. It qualifies the
bound input, never the student (``NOT_DOCUMENTED_MEANING``)."""

DESIGN_RISK_CODE: dict[RequirementKind, MethodologyIssueCode] = {
    K.DATA_LEAKAGE_PREVENTION: C.DATA_LEAKAGE_RISK,
    K.TEST_SET_ISOLATION_FROM_TUNING: C.DATA_LEAKAGE_RISK,
    K.TRAIN_SPLIT: C.DATA_LEAKAGE_RISK,
    K.VALIDATION_SPLIT: C.DATA_LEAKAGE_RISK,
    K.TEST_SPLIT: C.DATA_LEAKAGE_RISK,
    K.DUPLICATE_LEAKAGE_PREVENTION: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
    K.GROUP_AWARE_SPLIT: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
    K.TEMPORAL_SPLIT: C.DUPLICATE_OR_GROUP_LEAKAGE_RISK,
}
"""A documented design that itself creates a leakage risk. A design-level finding only:
no code here asserts that leakage occurred or that it was prevented."""

_NOT_APPLICABLE = Applicability.NOT_APPLICABLE


# -- component completion (stage 6) ----------------------------------------------------------


def complete_documentation(
    applicability: list[RequirementApplicability], extracted: list[RequirementDocumentation], run: MethodologyReviewRun,
    *, source_unread: bool, source_truncated: bool,
) -> list[RequirementDocumentation]:
    """One documentation record for every applicable requirement a track owns.

    A requirement the model found nothing for is NOT_DOCUMENTED_IN_BOUND_INPUT only when
    the whole submission was shown; if it was not read, or only a prefix was shown, absence
    proves nothing and the record says INSUFFICIENT_SOURCE_COVERAGE instead."""
    found = {d.kind: d for d in extracted}
    out: list[RequirementDocumentation] = []
    for a in applicability:
        if a.track is None or a.applicability is _NOT_APPLICABLE:
            continue
        if a.kind in found and found[a.kind].track is a.track and not source_unread:
            out.append(found[a.kind])
            continue
        status = (DocumentationStatus.INSUFFICIENT_SOURCE_COVERAGE if source_unread or source_truncated
                  else DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT)
        out.append(RequirementDocumentation(
            methodology_run_id=run.methodology_run_id, kind=a.kind, track=a.track, documentation=status,
            adequacy=DesignAdequacy.INSUFFICIENT_EVIDENCE_TO_ASSESS))
    return out


# -- validation continuity (stage 8) -----------------------------------------------------------


def evaluate_continuity(
    run: MethodologyReviewRun, coverage: list[MethodologyCoverageLink],
    conditions: list[MaterialConditionCoverage], metrics: list[MetricAlignment],
    baselines: list[BaselineComparatorRecord],
) -> tuple[list[MethodologyCoverageLink], int]:
    """Downgrade a DIRECT link to PARTIAL when the target's required continuity is not met.

    A claim target needs an aligned metric. A gap target needs exactly what its bound Phase 2J
    requirement asks for -- the metric plan, the baseline only if the requirement has one, and
    every material condition -- and nothing Phase 3A invents. A valid id is never enough."""
    targets = {t.gap_hypothesis_id: t for t in run.bound_gap_targets}
    out, downgraded = [], 0
    for link in coverage:
        if link.relation is CoverageRelation.DIRECTLY_TESTS_TARGET and not _continuity_met(
                link, targets, conditions, metrics, baselines):
            link = link.model_copy(update={"relation": CoverageRelation.PARTIALLY_TESTS_TARGET})
            downgraded += 1
        out.append(link)
    return out, downgraded


def _continuity_met(link, targets, conditions, metrics, baselines) -> bool:
    if link.gap_hypothesis_id is None:
        return any(m.target_claim_id == link.claim_id and m.status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT
                   for m in metrics)
    target = targets.get(link.gap_hypothesis_id)
    if target is None:
        return False
    try:
        _require_phase_2j_continuity(
            target, [c for c in conditions if c.gap_hypothesis_id == target.gap_hypothesis_id], metrics, baselines)
    except ValueError:
        return False
    return True


# -- issues (stage 9) ----------------------------------------------------------------------------


class _Issues:
    def __init__(self, run: MethodologyReviewRun, track: MethodologyTrack) -> None:
        self.run, self.track = run, track
        self.items: dict = {}

    def add(self, code: MethodologyIssueCode, *, kind: RequirementKind | None = None, claim_id: str | None = None,
            gap_id=None, condition_id=None) -> None:
        issue_id = methodology_id(self.run.methodology_run_id, "issue", self.track.value, code.value,
                                  kind.value if kind else "", claim_id or "", gap_id or "", condition_id or "")
        self.items[issue_id] = MethodologyIssue(
            issue_id=issue_id, methodology_run_id=self.run.methodology_run_id, code=code, severity=ISSUE_SEVERITY[code],
            track=self.track, requirement_kind=kind, claim_id=claim_id, gap_hypothesis_id=gap_id,
            condition_id=condition_id)

    def sorted(self) -> list[MethodologyIssue]:
        return sorted(self.items.values(), key=lambda i: (i.code.value, str(i.requirement_kind or ""),
                                                          i.claim_id or "", str(i.gap_hypothesis_id or ""),
                                                          str(i.condition_id or "")))


def _component_issues(bag: _Issues, applicability, docs) -> None:
    required = {a.kind for a in applicability if a.applicability is Applicability.REQUIRED}
    for d in sorted(docs, key=lambda d: d.kind.value):
        if d.documentation is DocumentationStatus.CONFLICTING_DOCUMENTATION:
            bag.add(C.CONFLICTING_METHOD_DESCRIPTION, kind=d.kind)
        elif d.documentation is DocumentationStatus.NOT_DOCUMENTED_IN_BOUND_INPUT and d.kind in required:
            bag.add(NOT_DOCUMENTED_CODE.get(d.kind, C.REQUIRED_COMPONENT_NOT_DOCUMENTED), kind=d.kind)
        elif (d.documentation in (DocumentationStatus.EXPLICITLY_DOCUMENTED, DocumentationStatus.PARTIALLY_DOCUMENTED)
              and d.adequacy is DesignAdequacy.DESIGN_RISK_IDENTIFIED and d.kind in DESIGN_RISK_CODE):
            bag.add(DESIGN_RISK_CODE[d.kind], kind=d.kind)


_METRIC_CODE = {
    MetricAlignmentStatus.METRIC_NOT_DEFINED: C.METRIC_NOT_DEFINED,
    MetricAlignmentStatus.METRIC_TARGET_MISMATCH: C.METRIC_TARGET_MISMATCH,
    MetricAlignmentStatus.TARGET_NOT_MEASURABLE_AS_STATED: C.TARGET_NOT_TESTABLE,
}


def _target_issues(run, bag: _Issues, links, metrics, baselines, conditions, targets_by_req) -> None:
    track = bag.track
    for link in links:
        if link.relation in (CoverageRelation.DOES_NOT_TEST_TARGET, CoverageRelation.RELEVANT_BUT_NOT_TESTING):
            bag.add(C.CLAIM_METHOD_MISMATCH if link.gap_hypothesis_id is None else C.GAP_METHOD_MISMATCH,
                    claim_id=link.claim_id, gap_id=link.gap_hypothesis_id)
    for m in metrics:
        target = targets_by_req.get(m.gap_validation_requirement_id)
        if target is not None and track not in gap_target_tracks(run, target):
            continue
        code = _METRIC_CODE.get(m.status)
        if code is not None:
            bag.add(code, claim_id=m.target_claim_id, gap_id=target.gap_hypothesis_id if target else None)
    for b in baselines:
        target = targets_by_req.get(b.gap_validation_requirement_id)
        if target is not None and track not in gap_target_tracks(run, target):
            continue
        gap_id = target.gap_hypothesis_id if target else None
        if b.relevance is BaselineRelevance.NO_BASELINE_DOCUMENTED:
            bag.add(C.BASELINE_NOT_DOCUMENTED, claim_id=b.target_claim_id, gap_id=gap_id)
        elif b.relevance is BaselineRelevance.RELEVANCE_UNRESOLVED:
            bag.add(C.BASELINE_RELEVANCE_UNRESOLVED, claim_id=b.target_claim_id, gap_id=gap_id)
        elif b.relevance is BaselineRelevance.NOT_RELEVANT_TO_TARGET:
            bag.add(C.CLAIM_METHOD_MISMATCH if gap_id is None else C.GAP_METHOD_MISMATCH,
                    claim_id=b.target_claim_id, gap_id=gap_id)
    claim_of = {t.gap_hypothesis_id: t.claim_id for t in run.bound_gap_targets}
    for c in conditions:
        if c.status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT:
            bag.add(C.MATERIAL_CONDITION_NOT_COVERED, claim_id=claim_of.get(c.gap_hypothesis_id),
                    gap_id=c.gap_hypothesis_id, condition_id=c.condition_id)


# -- track assessments (stage 9) -------------------------------------------------------------------


def insufficient_assessments(run: MethodologyReviewRun) -> list[MethodologyTrackAssessment]:
    """Unbound inputs: every inherited track is INSUFFICIENT_INPUT, with nothing asserted."""
    return [
        MethodologyTrackAssessment(
            methodology_run_id=run.methodology_run_id, track=track, inputs_bound=False,
            posture=MethodologyPosture.INSUFFICIENT_INPUT)
        for track in run.tracks
    ]


def build_track_assessments(
    run: MethodologyReviewRun, applicability: list[RequirementApplicability],
    documentation: list[RequirementDocumentation], coverage: list[MethodologyCoverageLink],
    conditions: list[MaterialConditionCoverage],
) -> list[MethodologyTrackAssessment]:
    """One assessment per inherited track. HYBRID keeps both; nothing is averaged."""
    targets = {t.gap_hypothesis_id: t for t in run.bound_gap_targets}
    by_req = {t.validation_requirement_id: t for t in run.bound_gap_targets if t.validation_requirement_id}
    blocked = any(o.blocks_well_specified for o in run.overlays)
    out = []
    for track in run.tracks:
        own_apps = [a for a in applicability if a.track is track]
        applicable = {a.kind for a in own_apps if a.applicability is not _NOT_APPLICABLE}
        docs = [d for d in documentation if d.track is track and d.kind in applicable]
        links = [c for c in coverage if c.track is track]
        member = {h for h, t in targets.items() if track in gap_target_tracks(run, t)}
        conds = [c for c in conditions if c.gap_hypothesis_id in member]
        bag = _Issues(run, track)
        _component_issues(bag, own_apps, docs)
        _target_issues(run, bag, links, run.metric_alignments, run.baselines, conds, by_req)
        issues = bag.sorted()
        posture = cap_for_unresolved_overlay(derive_track_posture(
            inputs_bound=True, applicability=own_apps, documentation=docs, coverage=links, conditions=conds,
            issues=issues), blocked)
        out.append(MethodologyTrackAssessment(
            methodology_run_id=run.methodology_run_id, track=track, inputs_bound=True, applicability=own_apps,
            documentation=docs, coverage=links, conditions=conds, issues=issues, overlay_blocked=blocked,
            posture=posture))
    return out


__all__ = [
    "DESIGN_RISK_CODE",
    "NOT_DOCUMENTED_CODE",
    "build_track_assessments",
    "complete_documentation",
    "evaluate_continuity",
    "insufficient_assessments",
]
