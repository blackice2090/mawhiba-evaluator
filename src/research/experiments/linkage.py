"""Target linkage (``EXPERIMENT_LINK_TARGETS``). One model call per experiment.

The model sees ONE experiment's verified excerpts (E labels) and the closed target
set: every bound claim (T labels) and every bound Phase 2J validation requirement
(V labels, with its metric, baseline and material conditions as K labels). It
answers with labels only. Code then enforces, deterministically:

* an unknown target label is ``UNKNOWN_TARGET``; an id-shaped one is
  ``CROSS_RUN_REFERENCE``; an excerpt label outside this experiment is refused, so
  a metric can never come from another experiment;
* ``ALIGNED_SAME_TARGET`` needs both a method and a metric excerpt (a name is not a
  measurement), and ``SAME_AS_PHASE_2J`` needs alignment;
* ``DIRECTLY_TESTS`` survives only on an aligned measurement of the same experiment
  AND the same target (``directly_tests_supported``); otherwise it is at most
  ``PARTIALLY_TESTS`` -- a shared keyword or another target's metric never carries it;
* every target the model omits is an ``UNRESOLVED`` link, never "does not test";
* baseline relevance needs a permitted ground (a name alone is not relevance);
  comparability is per property, and only ``SAME_EVALUATION_METRIC`` may be set
  deterministically, from the experiment's own aligned metric binding;
* HYBRID ownership: the tested Phase 2J requirements' single facet first, then the
  extraction's bounded proposal, otherwise ``UNRESOLVED``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.prompts import EXPERIMENT_TARGET_LINKAGE_PROMPT_V1, build_experiment_user_input
from src.llm.provider import StructuredModelProvider
from src.research.experiments.calls import FAILURE_MESSAGES, CallOutcome, call_model
from src.research.experiments.dto import BaselineDTO, LinkageResponse, MeasurementDTO
from src.research.experiments.protocol import PHASE_2J_TRIGGERS, apply_phase2j_triggers, excerpt_labels, resolve_labels
from src.research.experiments.verify import ExperimentLedger, parse_enum
from src.schemas.experiment_review import (
    FACET_TRACK,
    TESTING_RELATIONS,
    BoundValidationTarget,
    ConditionCoverage,
    ConditionCoverageStatus,
    ExecutionStatus,
    ExperimentBaselineRecord,
    ExperimentRecord,
    ExperimentRunIssueCode,
    ExperimentTargetLink,
    ExperimentTrigger,
    FairnessBasis,
    FairnessProperty,
    FairnessPropertyAssessment,
    FairnessPropertyStatus,
    MeasurementBinding,
    MetricTargetAlignment,
    Phase2JAnchorMatch,
    SuccessCriterionTiming,
    TargetRelation,
    TrackOwnershipBasis,
    directly_tests_supported,
    experiment_uuid,
)
from src.schemas.methodology_review import BaselineRelevance, BaselineRelevanceContext

_C = ExperimentRunIssueCode
_M = MetricTargetAlignment
_UUID_SHAPE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass(frozen=True)
class Target:
    label: str
    claim_id: str
    validation: BoundValidationTarget | None = None

    @property
    def key(self) -> tuple[str, UUID | None, UUID | None]:
        v = self.validation
        return (self.claim_id, v.gap_hypothesis_id if v else None, v.validation_requirement_id if v else None)


@dataclass
class TargetText:
    """Bound Phase 2J text shown to the model as context (never persisted, never canonical)."""

    metric: dict[UUID, str] = field(default_factory=dict)
    baseline: dict[UUID, str] = field(default_factory=dict)
    condition: dict[UUID, str] = field(default_factory=dict)


@dataclass
class LinkageResult:
    record: ExperimentRecord
    links: list[ExperimentTargetLink]
    measurements: list[MeasurementBinding]
    baselines: list[ExperimentBaselineRecord]
    conditions: list[ConditionCoverage]
    outcome: CallOutcome


def target_set(ledger: ExperimentLedger) -> list[Target]:
    run = ledger.run
    claim_label = {c.claim_id: f"T{n}" for n, c in enumerate(sorted(run.bound_claims, key=lambda c: c.claim_id), 1)}
    out = [Target(label, cid) for cid, label in claim_label.items()]
    out += [Target(f"V{n}", t.claim_id, t) for n, t in enumerate(run.bound_validation_targets, 1)]
    return out


def condition_labels(ledger: ExperimentLedger) -> dict[str, tuple[UUID, UUID]]:
    """K1, K2, ... -> (validation requirement id, condition id), in bound order."""
    out, n = {}, 0
    for t in ledger.run.bound_validation_targets:
        for c in t.condition_ids:
            n += 1
            out[f"K{n}"] = (t.validation_requirement_id, c)
    return out


def _target_lines(targets: list[Target], claim_texts: dict[str, str], texts: TargetText,
                  conditions: dict[str, tuple[UUID, UUID]]) -> list[str]:
    claim_label = {t.claim_id: t.label for t in targets if t.validation is None}
    lines = [f"[{t.label}] claim: {claim_texts.get(t.claim_id, '')}" for t in targets if t.validation is None]
    for t in targets:
        v = t.validation
        if v is None:
            continue
        lines.append(f"[{t.label}] validation requirement of {claim_label.get(t.claim_id, '?')}; "
                     f"metric: {texts.metric.get(v.validation_requirement_id, '')}")
        if v.requires_baseline:
            lines.append(f"[{t.label}] baseline: {texts.baseline.get(v.validation_requirement_id, '')}")
        for label, (req, cond) in conditions.items():
            if req == v.validation_requirement_id:
                lines.append(f"[{label}] condition of {t.label}: {texts.condition.get(cond, '')}")
    return lines


def _measurement(ledger: ExperimentLedger, labels: dict[str, UUID], record: ExperimentRecord, target: Target,
                 dto: MeasurementDTO) -> MeasurementBinding:
    def one(label: str | None) -> UUID | None:
        ids = resolve_labels(ledger, labels, [label]) if label else []
        return ids[0] if ids else None

    method, metric, unit, criterion = one(dto.method), one(dto.metric), one(dto.unit), one(dto.success_criterion)
    alignment = parse_enum(_M, dto.alignment) or _M.ALIGNMENT_UNRESOLVED
    if alignment is _M.ALIGNED_SAME_TARGET and (method is None or metric is None):
        alignment = _M.METRIC_NOT_DEFINED if metric is None else _M.MEASUREMENT_METHOD_NOT_DEFINED
    if alignment is _M.METRIC_TARGET_MISMATCH and metric is None:
        alignment = _M.METRIC_NOT_DEFINED
    if alignment is _M.METRIC_NOT_DEFINED:
        metric = None
    if alignment is _M.MEASUREMENT_METHOD_NOT_DEFINED:
        method = None
    v = target.validation
    if v is None:
        match = Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR
    else:
        match = parse_enum(Phase2JAnchorMatch, dto.phase2j_metric_match)
        if match in (None, Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR) or (
                match is Phase2JAnchorMatch.SAME_AS_PHASE_2J and alignment is not _M.ALIGNED_SAME_TARGET):
            match = Phase2JAnchorMatch.MATCH_UNRESOLVED
    timing = parse_enum(SuccessCriterionTiming, dto.criterion_timing) or SuccessCriterionTiming.TIMING_NOT_DOCUMENTED
    if criterion is None:
        timing = SuccessCriterionTiming.TIMING_NOT_DOCUMENTED
    claim, hyp, req = target.key
    return MeasurementBinding(
        binding_id=experiment_uuid(record.experiment_run_id, "measurement", record.experiment_id, claim, hyp, req),
        experiment_run_id=record.experiment_run_id, experiment_id=record.experiment_id, target_claim_id=claim,
        gap_hypothesis_id=hyp, validation_requirement_id=req, method_excerpt_id=method, metric_excerpt_id=metric,
        unit_excerpt_id=unit, success_criterion_excerpt_id=criterion, success_criterion_timing=timing,
        alignment=alignment, phase2j_metric_match=match)


def _baseline(ledger: ExperimentLedger, labels: dict[str, UUID], record: ExperimentRecord, target: Target,
              dto: BaselineDTO, measurement: MeasurementBinding | None) -> ExperimentBaselineRecord | None:
    named = resolve_labels(ledger, labels, dto.excerpts)
    if not named:
        return None
    v = target.validation
    relevance = parse_enum(BaselineRelevance, dto.relevance)
    if relevance in (None, BaselineRelevance.NO_BASELINE_DOCUMENTED):
        relevance = BaselineRelevance.RELEVANCE_UNRESOLVED
    if relevance is BaselineRelevance.RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT:
        grounds = {parse_enum(BaselineRelevanceContext, c) for c in dto.context}
        permitted = {BaselineRelevanceContext.TARGET_CLAIM_TEXT}
        if v is not None and v.requires_baseline:
            permitted.add(BaselineRelevanceContext.PHASE_2J_VALIDATION_BASELINE)
        if resolve_labels(ledger, labels, dto.rationale_excerpts):
            permitted.add(BaselineRelevanceContext.STUDENT_RATIONALE_EXCERPT)
        if not grounds & permitted:  # a baseline's name alone is never relevance
            relevance = BaselineRelevance.RELEVANCE_UNRESOLVED
    if v is None or not v.requires_baseline:
        match = Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR
    else:
        match = parse_enum(Phase2JAnchorMatch, dto.phase2j_baseline_match)
        if match in (None, Phase2JAnchorMatch.NO_PHASE_2J_ANCHOR):
            match = Phase2JAnchorMatch.MATCH_UNRESOLVED
    props: dict[FairnessProperty, FairnessPropertyAssessment] = {}
    for c in sorted(dto.comparability, key=lambda c: (c.property, c.status)):
        prop = parse_enum(FairnessProperty, c.property)
        status = parse_enum(FairnessPropertyStatus, c.status)
        if prop is None or prop in props:
            continue
        if status in (None, FairnessPropertyStatus.NOT_APPLICABLE):  # inapplicability is never the model's to assert
            status = FairnessPropertyStatus.UNRESOLVED
        ids = resolve_labels(ledger, labels, c.excerpts)
        documented = status in (FairnessPropertyStatus.DOCUMENTED_SAME, FairnessPropertyStatus.DOCUMENTED_DIFFERENT)
        if documented and not ids:
            status = FairnessPropertyStatus.NOT_DOCUMENTED
        props[prop] = FairnessPropertyAssessment(
            property=prop, status=status,
            basis=FairnessBasis.NONE if status is FairnessPropertyStatus.NOT_DOCUMENTED
            else FairnessBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,
            excerpt_ids=ids if status in (FairnessPropertyStatus.DOCUMENTED_SAME,
                                          FairnessPropertyStatus.DOCUMENTED_DIFFERENT) else [])
    metric = FairnessProperty.SAME_EVALUATION_METRIC
    if (measurement is not None and measurement.alignment is _M.ALIGNED_SAME_TARGET
            and measurement.metric_excerpt_id is not None
            and (metric not in props or props[metric].status is not FairnessPropertyStatus.DOCUMENTED_DIFFERENT)):
        # The only deterministic comparability property: baseline and experiment are read
        # through the one aligned metric binding of this experiment and target.
        props[metric] = FairnessPropertyAssessment(
            property=metric, status=FairnessPropertyStatus.DOCUMENTED_SAME,
            basis=FairnessBasis.DETERMINISTIC_SHARED_METRIC_BINDING, excerpt_ids=[measurement.metric_excerpt_id])
    claim, hyp, req = target.key
    return ExperimentBaselineRecord(
        record_id=experiment_uuid(record.experiment_run_id, "baseline", record.experiment_id, claim, hyp, req),
        experiment_run_id=record.experiment_run_id, experiment_id=record.experiment_id, target_claim_id=claim,
        gap_hypothesis_id=hyp, validation_requirement_id=req, baseline_excerpt_ids=named, relevance=relevance,
        phase2j_baseline_match=match, comparability=[props[p] for p in FairnessProperty if p in props],
        execution_status=parse_enum(ExecutionStatus, dto.execution_status)
        or ExecutionStatus.EXECUTION_STATUS_NOT_DOCUMENTED)


def _link(record: ExperimentRecord, target: Target, claim_hash: str, relation: TargetRelation,
          excerpts: list[UUID]) -> ExperimentTargetLink:
    claim, hyp, req = target.key
    return ExperimentTargetLink(
        link_id=experiment_uuid(record.experiment_run_id, "link", record.experiment_id, claim, hyp, req),
        experiment_run_id=record.experiment_run_id, experiment_id=record.experiment_id, claim_id=claim,
        claim_text_hash=claim_hash, gap_hypothesis_id=hyp, validation_requirement_id=req, relation=relation,
        excerpt_ids=excerpts if relation in TESTING_RELATIONS else [])


def _ownership(ledger: ExperimentLedger, record: ExperimentRecord, links: list[ExperimentTargetLink]
               ) -> ExperimentRecord:
    if len(ledger.run.tracks) < 2:
        return record
    by_req = {t.validation_requirement_id: t for t in ledger.run.bound_validation_targets}
    tested = [by_req[link.validation_requirement_id] for link in links
              if link.relation in TESTING_RELATIONS and link.validation_requirement_id in by_req]
    owners = {FACET_TRACK[f] for t in tested for f in t.limitation_facets}
    if tested and len(owners) == 1 and all(t.limitation_facets for t in tested):
        return record.model_copy(update={
            "track": owners.pop(), "ownership_basis": TrackOwnershipBasis.PHASE_2J_LIMITATION_FACET,
            "ownership_gap_hypothesis_ids": sorted({t.gap_hypothesis_id for t in tested}, key=str)})
    if record.ownership_basis is TrackOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT:
        return record
    return record.model_copy(update={"track": None, "ownership_basis": TrackOwnershipBasis.UNRESOLVED,
                                     "ownership_gap_hypothesis_ids": []})


def phase2j_facts(targets: list[BoundValidationTarget]) -> frozenset[ExperimentTrigger]:
    facts = set()
    if any(t.requires_baseline for t in targets):
        facts.add(ExperimentTrigger.PHASE_2J_BASELINE_REQUIRED)
    if any(t.condition_ids for t in targets):
        facts.add(ExperimentTrigger.PHASE_2J_MATERIAL_CONDITION)
    return frozenset(facts) & PHASE_2J_TRIGGERS


def link_experiment(
    ledger: ExperimentLedger, record: ExperimentRecord, claim_texts: dict[str, str], texts: TargetText,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, performed: int,
) -> LinkageResult:
    targets = target_set(ledger)
    claim_hash = {c.claim_id: c.claim_text_hash for c in ledger.run.bound_claims}
    k_labels = condition_labels(ledger)
    labels = excerpt_labels(ledger, record)
    outcome = call_model(
        provider, task=ModelTask.EXPERIMENT_TARGET_LINKAGE, prompt=EXPERIMENT_TARGET_LINKAGE_PROMPT_V1,
        user_input=build_experiment_user_input(
            targets=_target_lines(targets, claim_texts, texts, k_labels),
            excerpts=[(label, ledger.excerpts[i].excerpt) for label, i in labels.items()],
            items=[f"Judge every target: {', '.join(t.label for t in targets)}."]),
        response_model=LinkageResponse, llm_settings=llm_settings, bounds=ledger.bounds, performed=performed)
    links: dict[str, ExperimentTargetLink] = {}
    measurements: list[MeasurementBinding] = []
    baselines: list[ExperimentBaselineRecord] = []
    conditions: dict[tuple[UUID, UUID], ConditionCoverage] = {}
    by_label = {t.label: t for t in targets}
    if not outcome.succeeded:
        ledger.emit(outcome.failure, FAILURE_MESSAGES[outcome.failure], record.experiment_id)  # type: ignore[index, arg-type]
    else:
        response: LinkageResponse = outcome.parsed
        for dto in sorted(response.targets, key=lambda d: (d.target, d.relation)):
            label = (dto.target or "").strip().upper()
            target = by_label.get(label)
            if target is None:
                code = _C.CROSS_RUN_REFERENCE if _UUID_SHAPE.search(dto.target or "") else _C.UNKNOWN_TARGET
                ledger.reject(code, dto.target, f"a linkage named a target outside the bound set ({code.value})")
                continue
            if label in links or ledger.unsafe(dto.rationale):
                continue
            relation = parse_enum(TargetRelation, dto.relation)
            if relation is None:
                ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.relation, "a relation outside the taxonomy")
                continue
            m = _measurement(ledger, labels, record, target, dto.measurement) if dto.measurement else None
            if m is not None:
                measurements.append(m)
            if dto.baseline is not None:
                b = _baseline(ledger, labels, record, target, dto.baseline, m)
                if b is not None:
                    baselines.append(b)
            cited = resolve_labels(ledger, labels, dto.excerpts)
            if relation in TESTING_RELATIONS and not cited:
                relation = TargetRelation.UNRESOLVED  # a testing relation cites the protocol that tests
            link = _link(record, target, claim_hash[target.claim_id], relation, cited)
            if relation is TargetRelation.DIRECTLY_TESTS and not directly_tests_supported(link, measurements):
                # the metric-target guard: no aligned measurement of this experiment AND this target
                link = _link(record, target, claim_hash[target.claim_id], TargetRelation.PARTIALLY_TESTS, cited)
            links[label] = link
        for dto in sorted(response.conditions, key=lambda d: (d.condition, d.status)):
            key = k_labels.get((dto.condition or "").strip().upper())
            status = parse_enum(ConditionCoverageStatus, dto.status)
            if key is None or status is None or key in conditions:
                ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.condition, "a condition judgment outside the bound set")
                continue
            ids = resolve_labels(ledger, labels, dto.excerpts)
            if status is not ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT and not ids:
                status = ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT
            conditions[key] = ConditionCoverage(
                experiment_run_id=record.experiment_run_id, experiment_id=record.experiment_id,
                validation_requirement_id=key[0], condition_id=key[1], status=status,
                excerpt_ids=ids if status is not ConditionCoverageStatus.NOT_ADDRESSED_IN_BOUND_INPUT else [])
    omitted = [t for t in targets if t.label not in links]
    if omitted and outcome.succeeded:
        ledger.emit(_C.PARTIAL_MODEL_OUTPUT, f"{len(omitted)} target(s) were left unjudged", record.experiment_id)
    for t in omitted:  # an unjudged target is UNRESOLVED, never DOES_NOT_TEST
        links[t.label] = _link(record, t, claim_hash[t.claim_id], TargetRelation.UNRESOLVED, [])
    ordered_links = sorted(links.values(), key=lambda link: str(link.link_id))
    owned = _ownership(ledger, record, ordered_links)
    tested_targets = [t.validation for t in targets if t.validation is not None and links[t.label].relation
                      in TESTING_RELATIONS]
    owned = apply_phase2j_triggers(owned, phase2j_facts(tested_targets))  # type: ignore[arg-type]
    return LinkageResult(owned, ordered_links, sorted(measurements, key=lambda m: str(m.binding_id)),
                         sorted(baselines, key=lambda b: str(b.record_id)),
                         sorted(conditions.values(), key=lambda c: (str(c.validation_requirement_id),
                                                                     str(c.condition_id))), outcome)


__all__ = ["LinkageResult", "Target", "TargetText", "condition_labels", "link_experiment", "phase2j_facts",
           "target_set"]
