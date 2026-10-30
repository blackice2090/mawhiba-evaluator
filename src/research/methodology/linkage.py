"""Target linkage: metric and baseline plans, claim/gap coverage, material conditions.

Two bounded model calls per claim. Structure is verified in code (run, claim,
hypothesis, requirement and condition ids; exact excerpts; permitted contexts);
the *semantics* of a relation stay a ``MODEL_ASSISTED_BOUNDED_JUDGMENT`` and are
never presented as verified (ADR-022).

Nothing is invented. A metric is a student excerpt or the bound Phase 2J
requirement; a baseline is a student excerpt; a condition is a Phase 2J id. A
target whose judgment could not be obtained is recorded as *unjudged* and gets
an INSUFFICIENT_LINKAGE_EVIDENCE link -- never a positive finding, and never a
negative one: absence of an answer is not an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.prompts import (
    METHODOLOGY_METRIC_BASELINE_PROMPT_V1,
    METHODOLOGY_TARGET_LINKAGE_PROMPT_V1,
    build_methodology_linkage_user_input,
    build_methodology_user_input,
)
from src.llm.provider import StructuredModelProvider
from src.research.methodology.dto import MetricBaselineResponse, TargetLinkageResponse
from src.research.methodology.evidence import _call
from src.research.methodology.inventory import gap_target_tracks
from src.research.methodology.verify import StageLedger, parse_enum
from src.schemas.gap_assessment import GapAssessmentRun, GapHypothesis
from src.schemas.methodology_review import (
    REQUIREMENT_CATALOG,
    BaselineComparatorRecord,
    BaselineRelevance,
    BaselineRelevanceContext,
    BoundGapTarget,
    ConditionCoverageStatus,
    CoverageRelation,
    CoverageTargetKind,
    DocumentationStatus,
    MaterialConditionCoverage,
    MethodologyCoverageLink,
    MethodologyReviewRun,
    MethodologyRunIssueCode,
    MethodologyTrack,
    MetricAlignment,
    MetricAlignmentStatus,
    MetricSource,
    OverlayMateriality,
    RequirementDocumentation,
    RequirementKind,
    methodology_id,
)

PLAN_NODE = "LINK_METHODOLOGY_TO_TARGETS"
_DOCUMENTED = (DocumentationStatus.EXPLICITLY_DOCUMENTED, DocumentationStatus.PARTIALLY_DOCUMENTED,
               DocumentationStatus.CONFLICTING_DOCUMENTATION)
_TESTING = (CoverageRelation.DIRECTLY_TESTS_TARGET, CoverageRelation.PARTIALLY_TESTS_TARGET)


@dataclass
class ClaimTargets:
    """One claim and the Phase 2J hypotheses (with a validation requirement) bound to it."""

    claim_id: str
    claim_text: str
    claim_hash: str
    gaps: list[tuple[str, BoundGapTarget]] = field(default_factory=list)  # (local label G1.., target)

    def key(self, target: BoundGapTarget | None) -> str:
        return self.claim_id if target is None else str(target.gap_hypothesis_id)


def targets_for(run: MethodologyReviewRun, claim_texts: dict[str, str]) -> list[ClaimTargets]:
    out = []
    for bound in sorted(run.bound_claims, key=lambda c: c.claim_id):
        gaps = sorted((t for t in run.bound_gap_targets if t.claim_id == bound.claim_id),
                      key=lambda t: str(t.gap_hypothesis_id))
        out.append(ClaimTargets(bound.claim_id, claim_texts[bound.claim_id], bound.claim_text_hash,
                                [(f"G{i}", t) for i, t in enumerate(gaps, 1)]))
    return out


# -- Phase 2J context shown to the model (verified upstream text, by reference) ----------


def _hypothesis(gap: GapAssessmentRun, target: BoundGapTarget) -> GapHypothesis | None:
    return next((h for h in gap.hypotheses if h.hypothesis_id == target.gap_hypothesis_id), None)


def _gap_line(gap: GapAssessmentRun, label: str, target: BoundGapTarget) -> str:
    h = _hypothesis(gap, target)
    if h is None or h.validation_requirement is None:
        return f"[{label}] gap hypothesis"
    refs = {r.evidence_ref_id: r.excerpt for r in h.evidence_refs}
    req = h.validation_requirement
    capabilities = [refs[i] for c in h.existing_capabilities for i in c.evidence_ref_ids if i in refs]
    limitations = [refs[i] for lim in h.limitations for i in lim.evidence_ref_ids if i in refs]
    return (f"[{label}] gap hypothesis; Phase 2J metric: {req.metric.text}; "
            f"Phase 2J baseline: {req.baseline.text if req.baseline else 'NONE'}; "
            f"existing capability: {' | '.join(capabilities) or 'NONE'}; "
            f"limitation: {' | '.join(limitations) or 'NONE'}")


def has_existing_capability(gap: GapAssessmentRun, target: BoundGapTarget) -> bool:
    h = _hypothesis(gap, target)
    return bool(h and h.existing_capabilities)


# -- metric and baseline plans ---------------------------------------------------------------


@dataclass
class PlanOutcome:
    metrics: list[MetricAlignment] = field(default_factory=list)
    baselines: list[BaselineComparatorRecord] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    model_called: bool = False
    model_succeeded: bool = False


def plan_claim(
    run: MethodologyReviewRun, gap: GapAssessmentRun, ct: ClaimTargets, ledger: StageLedger,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, *, may_call: bool,
) -> PlanOutcome:
    with_req = [(label, t) for label, t in ct.gaps if t.validation_requirement_id is not None]
    labelled: list[tuple[str, BoundGapTarget | None]] = [("T1", None), *with_req]
    out = PlanOutcome(unjudged=[ct.key(t) for _, t in labelled])
    if provider is None or not may_call:
        return out
    items = [f"[T1] the claim above", *(_gap_line(gap, label, t) for label, t in with_req)]
    shown = ledger.submission_text[: ledger.bounds.max_submission_chars]
    call = _call(provider, ModelTask.METHODOLOGY_METRIC_BASELINE, METHODOLOGY_METRIC_BASELINE_PROMPT_V1,
                 build_methodology_user_input(shown, [("T1", ct.claim_text)], items),
                 MetricBaselineResponse, llm_settings, ledger)
    out.model_called = True
    if not call.succeeded or not isinstance(call.parsed, MetricBaselineResponse):
        return out
    out.model_succeeded = True
    by_label = dict(labelled)
    metric_dtos, baseline_dtos = {}, {}
    for dto in sorted(call.parsed.metrics, key=lambda d: (d.target, d.status)):
        label = dto.target.strip().upper()
        if label in by_label and label not in metric_dtos:
            metric_dtos[label] = dto
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.target, off_contract=True)
    for dto in sorted(call.parsed.baselines, key=lambda d: (d.target, d.relevance)):
        label = dto.target.strip().upper()
        if label in by_label and label not in baseline_dtos:
            baseline_dtos[label] = dto
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.target, off_contract=True)
    unjudged = []
    for label, target in labelled:
        metric = _metric(run, ct, label, target, metric_dtos.get(label), ledger)
        if metric is None:
            unjudged.append(ct.key(target))
            continue
        out.metrics.append(metric)
        baseline = _baseline(run, gap, ct, target, baseline_dtos.get(label), ledger)
        if baseline is not None:
            out.baselines.append(baseline)
    out.unjudged = unjudged
    return out


def _metric(run, ct: ClaimTargets, label: str, target: BoundGapTarget | None, dto, ledger: StageLedger
            ) -> MetricAlignment | None:
    if dto is None:
        return None
    status = parse_enum(MetricAlignmentStatus, dto.status)
    if status is None:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.status, off_contract=True)
        return None
    if ledger.unsafe(PLAN_NODE, dto.outcome.rationale if dto.outcome else None,
                     dto.metric_excerpt.rationale if dto.metric_excerpt else None):
        return None
    outcome_id = ledger.anchor(dto.outcome)
    metric_id = ledger.anchor(dto.metric_excerpt)
    if dto.metric_excerpt is not None and metric_id is None:
        ledger.reject(MethodologyRunIssueCode.INVENTED_METRIC, dto.metric_excerpt.excerpt)
    req_id = target.validation_requirement_id if target is not None else None
    source: MetricSource | None = None
    if metric_id is not None:
        source = MetricSource.STUDENT_EXCERPT
    elif target is not None and status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT:
        source = MetricSource.PHASE_2J_VALIDATION_ANCHOR
    if status is MetricAlignmentStatus.ALIGNED_WITHIN_BOUND_INPUT and (outcome_id is None or source is None):
        status = MetricAlignmentStatus.METRIC_NOT_DEFINED  # alignment needs a bound outcome and a bound metric
    if status is MetricAlignmentStatus.METRIC_TARGET_MISMATCH and metric_id is None:
        status = MetricAlignmentStatus.METRIC_NOT_DEFINED  # a mismatch needs a student metric to mismatch
    if status in (MetricAlignmentStatus.METRIC_NOT_DEFINED, MetricAlignmentStatus.TARGET_NOT_MEASURABLE_AS_STATED):
        source, metric_id = None, None
    if source is MetricSource.PHASE_2J_VALIDATION_ANCHOR:
        metric_id = None
    return MetricAlignment(
        record_id=methodology_id(run.methodology_run_id, "metric", ct.claim_id, req_id or "claim"),
        methodology_run_id=run.methodology_run_id, target_claim_id=ct.claim_id, outcome_excerpt_id=outcome_id,
        metric_source=source, metric_excerpt_id=metric_id, gap_validation_requirement_id=req_id, status=status)


def _baseline(run, gap, ct: ClaimTargets, target: BoundGapTarget | None, dto, ledger: StageLedger
              ) -> BaselineComparatorRecord | None:
    requires = target is not None and target.requires_baseline
    req_id = target.validation_requirement_id if requires and target is not None else None
    record_id = methodology_id(run.methodology_run_id, "baseline", ct.claim_id, req_id or "claim")

    def bare(relevance: BaselineRelevance = BaselineRelevance.NO_BASELINE_DOCUMENTED) -> BaselineComparatorRecord:
        return BaselineComparatorRecord(
            record_id=record_id, methodology_run_id=run.methodology_run_id, target_claim_id=ct.claim_id,
            gap_validation_requirement_id=req_id, relevance=relevance)

    if dto is None or dto.baseline is None:
        return bare() if requires else None
    if ledger.unsafe(PLAN_NODE, dto.baseline.rationale,
                     dto.rationale_excerpt.rationale if dto.rationale_excerpt else None):
        return bare() if requires else None
    baseline_id = ledger.anchor(dto.baseline)
    if baseline_id is None:
        return bare() if requires else None
    relevance = parse_enum(BaselineRelevance, dto.relevance)
    if relevance is None or relevance is BaselineRelevance.NO_BASELINE_DOCUMENTED:
        if relevance is None:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.relevance, off_contract=True)
        relevance = BaselineRelevance.RELEVANCE_UNRESOLVED
    rationale_id = ledger.anchor(dto.rationale_excerpt)
    permitted = {BaselineRelevanceContext.TARGET_CLAIM_TEXT}
    if requires:
        permitted.add(BaselineRelevanceContext.PHASE_2J_VALIDATION_BASELINE)
    if target is not None and has_existing_capability(gap, target):
        permitted.add(BaselineRelevanceContext.PHASE_2J_EXISTING_CAPABILITY)
    context: list[BaselineRelevanceContext] = []
    for raw in dto.context:
        parsed = parse_enum(BaselineRelevanceContext, raw)
        if parsed is None:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, raw, off_contract=True)
        elif parsed in permitted and parsed not in context:
            context.append(parsed)  # a rationale context is added below, only if its excerpt is bound
    if rationale_id is not None:
        context.append(BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT)
    if relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT and not context:
        relevance = BaselineRelevance.RELEVANCE_UNRESOLVED  # the baseline's name alone is never relevance
    return BaselineComparatorRecord(
        record_id=record_id, methodology_run_id=run.methodology_run_id, target_claim_id=ct.claim_id,
        gap_validation_requirement_id=req_id, baseline_excerpt_ids=[baseline_id], relevance=relevance,
        relevance_context=context, rationale_excerpt_ids=[rationale_id] if rationale_id is not None else [])


# -- claim / gap coverage and material conditions --------------------------------------------


def visible_documentation(
    run: MethodologyReviewRun, documentation: list[RequirementDocumentation], track: MethodologyTrack,
) -> list[RequirementDocumentation]:
    """Documented requirements a track may cite: its own, and an overlay requirement its owner
    documents for a track the overlay serves. A track that is not served sees nothing of it."""
    owners = {o.overlay: o for o in run.overlays if o.materiality is OverlayMateriality.MATERIAL_TO_TARGET}
    out = []
    for d in documentation:
        if d.documentation not in _DOCUMENTED:
            continue
        overlay = REQUIREMENT_CATALOG[d.kind].overlay
        shared = overlay in owners and d.track is owners[overlay].owner_track and track in owners[overlay].served_tracks
        if d.track is track or shared:
            out.append(d)
    return out


@dataclass
class CoverageOutcome:
    links: list[MethodologyCoverageLink] = field(default_factory=list)
    conditions: list[MaterialConditionCoverage] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    model_called: bool = False
    model_succeeded: bool = False


def _link(run, ct: ClaimTargets, target: BoundGapTarget | None, track: MethodologyTrack,
          relation: CoverageRelation, excerpt_ids: list[UUID], kinds: list[RequirementKind]
          ) -> MethodologyCoverageLink:
    kind = CoverageTargetKind.CLAIM if target is None else CoverageTargetKind.GAP_HYPOTHESIS
    hid = None if target is None else target.gap_hypothesis_id
    return MethodologyCoverageLink(
        link_id=methodology_id(run.methodology_run_id, "link", kind.value, ct.claim_id, hid or "claim", track.value),
        methodology_run_id=run.methodology_run_id, target_kind=kind, claim_id=ct.claim_id,
        claim_text_hash=ct.claim_hash, gap_hypothesis_id=hid, track=track, excerpt_ids=excerpt_ids,
        requirement_kinds=kinds, relation=relation)


def link_claim(
    run: MethodologyReviewRun, gap: GapAssessmentRun, ct: ClaimTargets, documentation: list[RequirementDocumentation],
    ledger: StageLedger, provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
    *, may_call: bool, coverage_known: bool,
) -> CoverageOutcome:
    pairs: list[tuple[str, BoundGapTarget | None, MethodologyTrack]] = [
        ("T1", None, track) for track in run.tracks]
    for label, target in ct.gaps:
        pairs += [(label, target, track) for track in gap_target_tracks(run, target)]
    out = CoverageOutcome()

    def insufficient(unjudged: bool) -> CoverageOutcome:
        out.links = [_link(run, ct, t, track, CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE, [], [])
                     for _, t, track in pairs]
        if unjudged:
            out.unjudged = sorted({ct.key(t) for _, t, _ in pairs})
        return out

    documented = [d for d in documentation if d.documentation in _DOCUMENTED]
    cond_targets = [(label, t) for label, t in ct.gaps if t.material_condition_ids]
    if not coverage_known:
        return insufficient(True)  # the submission could not be read: nothing was judged
    if not documented:  # determinate: no methodology is documented in the bound input at all
        insufficient(False)
        out.conditions = [
            MaterialConditionCoverage(
                methodology_run_id=run.methodology_run_id, gap_hypothesis_id=t.gap_hypothesis_id, condition_id=c,
                status=ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT)
            for _, t in cond_targets for c in t.material_condition_ids]
        return out
    if provider is None or not may_call:
        return insufficient(True)

    excerpt_labels: dict[str, UUID] = {}
    shown: list[tuple[str, str, str]] = []
    seen: set[UUID] = set()
    for d in sorted(documented, key=lambda d: (d.track.value, d.kind.value)):
        for excerpt_id in d.excerpt_ids:
            if excerpt_id in seen:
                continue
            seen.add(excerpt_id)
            label = f"E{len(seen)}"
            excerpt_labels[label] = excerpt_id
            shown.append((label, f"{d.kind.value} / {d.track.value}", ledger.excerpts[excerpt_id].excerpt))
    condition_labels: dict[str, tuple[BoundGapTarget, UUID]] = {}
    items = []
    for label, track_target, track in pairs:
        items.append(f"JUDGE {label} on track {track.value}")
    for label, target in cond_targets:
        h = _hypothesis(gap, target)
        refs = {r.evidence_ref_id: r.excerpt for r in h.evidence_refs} if h else {}
        by_id = {c.condition_id: c for c in h.conditions} if h else {}
        for condition_id in target.material_condition_ids:
            k = f"K{len(condition_labels) + 1}"
            condition_labels[k] = (target, condition_id)
            cond = by_id.get(condition_id)
            text = refs.get(cond.evidence_ref_ids[0], "") if cond and cond.evidence_ref_ids else ""
            dimension = cond.dimension.value if cond else "UNKNOWN"
            items.append(f"[{k}] condition of {label} ({dimension}): {text}")
    targets_block = [f"[T1] {ct.claim_text}", *(_gap_line(gap, label, t) for label, t in ct.gaps)]
    call = _call(provider, ModelTask.METHODOLOGY_TARGET_LINKAGE, METHODOLOGY_TARGET_LINKAGE_PROMPT_V1,
                 build_methodology_linkage_user_input(targets_block, shown, items),
                 TargetLinkageResponse, llm_settings, ledger)
    out.model_called = True
    if not call.succeeded or not isinstance(call.parsed, TargetLinkageResponse):
        return insufficient(True)
    out.model_succeeded = True

    judged: dict[tuple[str, MethodologyTrack], object] = {}
    for dto in sorted(call.parsed.coverage, key=lambda d: (d.target, d.track, d.relation)):
        track = parse_enum(MethodologyTrack, dto.track)
        key = (dto.target.strip().upper(), track)
        if track is None or key[0] not in {p[0] for p in pairs} or key in judged \
                or (key[0], key[1]) not in {(p[0], p[2]) for p in pairs}:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.target, off_contract=True)
            continue
        judged[key] = dto
    unjudged: set[str] = set()
    for label, target, track in pairs:
        dto = judged.get((label, track))
        link = _verified_link(run, ct, target, track, dto, documentation, excerpt_labels, ledger)
        if link is None:
            link = _link(run, ct, target, track, CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE, [], [])
            unjudged.add(ct.key(target))
        out.links.append(link)
    judged_conditions: dict[str, object] = {}
    for dto in sorted(call.parsed.conditions, key=lambda d: (d.condition, d.status)):
        label = dto.condition.strip().upper()
        if label in condition_labels and label not in judged_conditions:
            judged_conditions[label] = dto
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.condition, off_contract=True)
    for label, (target, condition_id) in condition_labels.items():
        record = _condition(run, target, condition_id, judged_conditions.get(label), excerpt_labels, ledger)
        if record is None:
            unjudged.add(str(target.gap_hypothesis_id))
        else:
            out.conditions.append(record)
    out.unjudged = sorted(unjudged)
    return out


def _verified_link(run, ct, target, track, dto, documentation, excerpt_labels, ledger: StageLedger
                   ) -> MethodologyCoverageLink | None:
    if dto is None:
        return None
    relation = parse_enum(CoverageRelation, dto.relation)
    if relation is None:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.relation, off_contract=True)
        return None
    if ledger.unsafe(PLAN_NODE, dto.rationale):
        return None
    usable = visible_documentation(run, documentation, track)
    chosen: list[UUID] = []
    for raw in dict.fromkeys(l.strip().upper() for l in dto.excerpts):
        excerpt_id = excerpt_labels.get(raw)
        if excerpt_id is None:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, raw, off_contract=True)
        elif any(excerpt_id in d.excerpt_ids for d in usable):
            chosen.append(excerpt_id)  # an excerpt that documents nothing this track may cite is dropped
    kinds = sorted({d.kind for d in usable if any(i in d.excerpt_ids for i in chosen)}, key=lambda k: k.value)
    if relation in _TESTING and not chosen:
        relation = CoverageRelation.INSUFFICIENT_LINKAGE_EVIDENCE
    if relation is CoverageRelation.DIRECTLY_TESTS_TARGET and not any(REQUIREMENT_CATALOG[k].tests_target for k in kinds):
        relation = CoverageRelation.PARTIALLY_TESTS_TARGET  # unrelated text cannot carry strong coverage
    return _link(run, ct, target, track, relation, chosen, kinds)


def _condition(run, target: BoundGapTarget, condition_id: UUID, dto, excerpt_labels, ledger: StageLedger
               ) -> MaterialConditionCoverage | None:
    if dto is None:
        return None
    status = parse_enum(ConditionCoverageStatus, dto.status)
    if status is None:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.status, off_contract=True)
        return None
    if ledger.unsafe(PLAN_NODE, dto.rationale):
        return None
    ids = []
    for raw in dict.fromkeys(l.strip().upper() for l in dto.excerpts):
        if raw in excerpt_labels:
            ids.append(excerpt_labels[raw])
        else:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, raw, off_contract=True)
    if status is not ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT and not ids:
        status = ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT  # "addressed" needs an exact excerpt
    if status is ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT:
        ids = []
    return MaterialConditionCoverage(
        methodology_run_id=run.methodology_run_id, gap_hypothesis_id=target.gap_hypothesis_id,
        condition_id=condition_id, status=status, excerpt_ids=ids)


__all__ = [
    "ClaimTargets",
    "CoverageOutcome",
    "PLAN_NODE",
    "PlanOutcome",
    "has_existing_capability",
    "link_claim",
    "plan_claim",
    "targets_for",
    "visible_documentation",
]
