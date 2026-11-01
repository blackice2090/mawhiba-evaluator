"""Protocol extraction (``EXPERIMENT_EXTRACT_PROTOCOL``) and conditional applicability
(``EXPERIMENT_RESOLVE_APPLICABILITY``). One model call per experiment each, at most.

Extraction: the model sees the submission with every quarantined result withheld,
classifies the experiment into the closed type taxonomy and points at the exact
text documenting each requirement kind. Code re-slices every excerpt, refuses any
that overlaps a result span, and keeps documentation and adequacy on two fields
checked against ``ALLOWED_ADEQUACY``. A kind the catalog does not define is
``INVENTED_REQUIREMENT``. Applicability is never the model's: it comes from the
deterministic catalog (``resolve_applicability``) first.

Applicability: only a CONDITIONAL cell that the catalog could not settle is shown
to the model, only with its own closed trigger set (the Phase 2J triggers are
deterministic and withheld), and only resolved when the judgment cites verified
excerpt labels. A REQUIRED cell is never shown, so it can never be lowered; a
missing judgment leaves the cell CONDITIONAL, never NOT_APPLICABLE.
"""

from __future__ import annotations

from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.prompts import (
    EXPERIMENT_APPLICABILITY_PROMPT_V1,
    EXPERIMENT_PROTOCOL_EXTRACTION_PROMPT_V1,
    build_experiment_user_input,
)
from src.llm.provider import StructuredModelProvider
from src.research.experiments.calls import FAILURE_MESSAGES, CallOutcome, call_model
from src.research.experiments.dto import ApplicabilityResponse, ProtocolExtractionResponse
from src.research.experiments.verify import ExperimentLedger, parse_enum
from src.schemas.experiment_review import (
    ALLOWED_ADEQUACY,
    BARE_QUANTITY,
    EXPERIMENT_CATALOG,
    Applicability,
    ApplicabilityBasis,
    ExecutionStatus,
    ExperimentRecord,
    ExperimentRequirement,
    ExperimentRequirementKind,
    ExperimentRunIssueCode,
    ExperimentTrigger,
    ExperimentType,
    ProtocolAdequacy,
    TrackOwnershipBasis,
    TypeBasis,
    resolve_applicability,
)
from src.schemas.methodology_review import DocumentationStatus, MethodologyTrack

_C = ExperimentRunIssueCode
_DS, _PA = DocumentationStatus, ProtocolAdequacy
ERK = ExperimentRequirementKind
PHASE_2J_TRIGGERS = frozenset({ExperimentTrigger.PHASE_2J_BASELINE_REQUIRED,
                               ExperimentTrigger.PHASE_2J_MATERIAL_CONDITION})
_EXTRACTABLE = (_DS.EXPLICITLY_DOCUMENTED, _DS.PARTIALLY_DOCUMENTED, _DS.CONFLICTING_DOCUMENTATION)
_FALLBACK_ADEQUACY = {_DS.EXPLICITLY_DOCUMENTED: _PA.PARTIALLY_SPECIFIED, _DS.PARTIALLY_DOCUMENTED: _PA.PARTIALLY_SPECIFIED,
                      _DS.CONFLICTING_DOCUMENTATION: _PA.CONFLICTING_PROTOCOL}
Doc = tuple[DocumentationStatus, ProtocolAdequacy, list[UUID]]


def experiment_excerpt_ids(record: ExperimentRecord) -> list[UUID]:
    ids = [*record.defining_excerpt_ids, *record.ownership_excerpt_ids]
    for r in record.requirements:
        ids += [*r.excerpt_ids, *r.judgment_excerpt_ids]
    return list(dict.fromkeys(ids))


def excerpt_labels(ledger: ExperimentLedger, record: ExperimentRecord) -> dict[str, UUID]:
    """E1, E2, ... over the experiment's own verified excerpts, in document order."""
    return {f"E{n}": i for n, i in enumerate(ledger.ordered(experiment_excerpt_ids(record)), 1)}


def resolve_labels(ledger: ExperimentLedger, labels: dict[str, UUID], given: list[str]) -> list[UUID]:
    """Labels -> ids. An unknown label is refused (it is not a verified excerpt of this experiment)."""
    ids = []
    for label in given:
        excerpt_id = labels.get((label or "").strip().upper())
        if excerpt_id is None:
            ledger.reject(_C.EXACT_EXCERPT_MISMATCH, label, "a cited excerpt label is not an excerpt of this experiment")
        else:
            ids.append(excerpt_id)
    return ledger.ordered(ids) if ids else []


# -- requirement assembly (deterministic) ------------------------------------------------


def build_requirements(record: ExperimentRecord, experiment_type: ExperimentType, docs: dict[ERK, Doc], *,
                       source_unread: bool) -> list[ExperimentRequirement]:
    """The whole catalog, in catalog order, applicability from the catalog alone.
    A kind the extraction did not document is NOT_DOCUMENTED_IN_BOUND_INPUT (absence
    is never NOT_APPLICABLE); an unread source is INSUFFICIENT_SOURCE_COVERAGE."""
    out = []
    for kind in ERK:
        applicability, basis = resolve_applicability(kind, experiment_type, None)
        if applicability is Applicability.NOT_APPLICABLE:
            doc: Doc = (_DS.NOT_APPLICABLE, _PA.NOT_APPLICABLE, [])
        elif source_unread:
            doc = (_DS.INSUFFICIENT_SOURCE_COVERAGE, _PA.INSUFFICIENT_EVIDENCE_TO_ASSESS, [])
        else:
            doc = docs.get(kind, (_DS.NOT_DOCUMENTED_IN_BOUND_INPUT, _PA.INSUFFICIENT_EVIDENCE_TO_ASSESS, []))
        out.append(ExperimentRequirement(
            experiment_run_id=record.experiment_run_id, experiment_id=record.experiment_id, kind=kind,
            applicability=applicability, basis=basis, documentation=doc[0], adequacy=doc[1], excerpt_ids=doc[2]))
    return out


def resolved(req: ExperimentRequirement, *, required_by: list[ExperimentTrigger], basis: ApplicabilityBasis,
             judgment: list[UUID]) -> ExperimentRequirement:
    """A CONDITIONAL requirement resolved to REQUIRED (documentation kept) or NOT_APPLICABLE."""
    if required_by:
        return req.model_copy(update={"applicability": Applicability.REQUIRED, "basis": basis,
                                      "triggers": sorted(set(required_by)), "judgment_excerpt_ids": judgment})
    return req.model_copy(update={
        "applicability": Applicability.NOT_APPLICABLE, "basis": basis, "triggers": [], "judgment_excerpt_ids": judgment,
        "documentation": _DS.NOT_APPLICABLE, "adequacy": _PA.NOT_APPLICABLE, "excerpt_ids": []})


def pending_conditionals(record: ExperimentRecord) -> list[ExperimentRequirement]:
    return [r for r in record.requirements if r.basis is ApplicabilityBasis.CONDITION_UNRESOLVED]


# -- extraction -------------------------------------------------------------------------


def _extraction_items(ledger: ExperimentLedger) -> list[str]:
    """Code-built items only: closed enum values. No student text may appear here."""
    tracks = ", ".join(t.value for t in ledger.run.tracks)
    return [
        f"PROJECT TRACKS: {tracks}",
        f"EXPERIMENT TYPES: {', '.join(t.value for t in ExperimentType)}",
        f"REQUIREMENT KINDS: {', '.join(k.value for k in ERK)}",
        "The experiment's defining excerpts are D1, D2, ... in the untrusted excerpts block above.",
    ]


def _document(ledger: ExperimentLedger, dto) -> Doc | None:  # noqa: ANN001
    documentation = parse_enum(DocumentationStatus, dto.documentation)
    if documentation not in _EXTRACTABLE:
        ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.documentation, "a documentation status outside the contract")
        return None
    ids = [i for i in (ledger.anchor(s) for s in dto.excerpts) if i is not None]
    kind = parse_enum(ERK, dto.kind)
    if kind is ERK.SAMPLE_SIZE_RATIONALE:  # a bare quantity ("N = 500") is never a rationale
        kept = [i for i in ids if not BARE_QUANTITY.match(ledger.excerpts[i].excerpt)]
        if len(kept) != len(ids):
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, kind.value, "a bare number was offered as a sample-size rationale")
        ids = kept
    ids = ledger.ordered(ids) if ids else []
    if documentation is _DS.CONFLICTING_DOCUMENTATION and len(ids) < 2:
        documentation = _DS.PARTIALLY_DOCUMENTED  # one side is all the bound input shows
    if not ids:
        return None
    adequacy = parse_enum(ProtocolAdequacy, dto.adequacy)
    if adequacy is None or adequacy not in ALLOWED_ADEQUACY[documentation]:
        adequacy = _FALLBACK_ADEQUACY[documentation]
    if adequacy is _PA.ADEQUATELY_SPECIFIED_FOR_REVIEW and all(
            BARE_QUANTITY.match(ledger.excerpts[i].excerpt) for i in ids):
        adequacy = _PA.PARTIALLY_SPECIFIED  # a number alone is never an adequate specification
    return documentation, adequacy, ids


def extract_protocol(
    ledger: ExperimentLedger, record: ExperimentRecord, provider: StructuredModelProvider | None,
    llm_settings: LLMSettings | None, performed: int,
) -> tuple[ExperimentRecord, CallOutcome]:
    """Assess one segmented experiment. A failed call fails closed: type UNKNOWN and every
    applicable requirement INSUFFICIENT_SOURCE_COVERAGE (so never WELL_SPECIFIED)."""
    defining = [(f"D{n}", ledger.excerpts[i].excerpt) for n, i in enumerate(record.defining_excerpt_ids, 1)]
    outcome = call_model(
        provider, task=ModelTask.EXPERIMENT_PROTOCOL_EXTRACTION, prompt=EXPERIMENT_PROTOCOL_EXTRACTION_PROMPT_V1,
        user_input=build_experiment_user_input(submission_text=ledger.shown_text(), excerpts=defining,
                                               items=_extraction_items(ledger)),
        response_model=ProtocolExtractionResponse, llm_settings=llm_settings, bounds=ledger.bounds,
        performed=performed)
    if not outcome.succeeded:
        ledger.emit(outcome.failure, FAILURE_MESSAGES[outcome.failure], record.experiment_id)  # type: ignore[index, arg-type]
        reqs = build_requirements(record, ExperimentType.UNKNOWN, {}, source_unread=True)
        return record.model_copy(update={"requirements": reqs}), outcome
    response: ProtocolExtractionResponse = outcome.parsed
    experiment_type = parse_enum(ExperimentType, response.experiment_type)
    if experiment_type is None:
        ledger.reject(_C.PARTIAL_MODEL_OUTPUT, response.experiment_type, "an experiment type outside the taxonomy")
        experiment_type = ExperimentType.UNKNOWN
    execution = parse_enum(ExecutionStatus, response.execution_status) or ExecutionStatus.EXECUTION_STATUS_NOT_DOCUMENTED

    docs: dict[ERK, Doc] = {}
    for dto in sorted(response.requirements, key=lambda r: (r.kind, r.documentation, r.adequacy)):
        kind = parse_enum(ERK, dto.kind)
        if kind is None:
            ledger.reject(_C.INVENTED_REQUIREMENT, dto.kind, "a requirement kind outside the catalog")
            continue
        if kind in docs:
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, dto.kind, "a requirement kind was answered twice")
            continue
        if ledger.unsafe(dto.rationale):
            continue
        documented = _document(ledger, dto)
        if documented is not None:
            docs[kind] = documented

    update: dict = {"experiment_type": experiment_type, "execution_status": execution,
                    "type_basis": TypeBasis.UNRESOLVED if experiment_type is ExperimentType.UNKNOWN
                    else TypeBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT}
    if len(ledger.run.tracks) > 1 and response.owner_track is not None:  # HYBRID: a bounded proposal
        track = parse_enum(MethodologyTrack, response.owner_track)
        owner_ids = [i for i in (ledger.anchor(s) for s in response.owner_excerpts) if i is not None]
        if track in ledger.run.tracks and owner_ids:
            update |= {"track": track, "ownership_basis": TrackOwnershipBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,
                       "ownership_excerpt_ids": ledger.ordered(owner_ids)}
        else:
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, response.owner_track or "", "an owner track without verified basis")
    assessed = record.model_copy(update=update)
    reqs = build_requirements(assessed, experiment_type, docs, source_unread=False)
    return assessed.model_copy(update={"requirements": reqs}), outcome


# -- conditional applicability ------------------------------------------------------------


def model_triggers(kind: ERK) -> list[ExperimentTrigger]:
    return [t for t in EXPERIMENT_CATALOG[kind].triggers if t not in PHASE_2J_TRIGGERS]


def resolve_conditionals(
    ledger: ExperimentLedger, record: ExperimentRecord, claims: list[tuple[str, str]],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, performed: int,
    phase2j_facts: frozenset[ExperimentTrigger],
) -> tuple[ExperimentRecord, CallOutcome | None]:
    """Resolve the experiment's still-CONDITIONAL requirements through their closed triggers."""
    pending = [r for r in pending_conditionals(record) if model_triggers(r.kind)]
    if record.experiment_type is ExperimentType.UNKNOWN or not pending:
        return record, None
    labels = excerpt_labels(ledger, record)
    items = [f"[R{n}] {r.kind.value}; triggers: {', '.join(t.value for t in model_triggers(r.kind))}"
             for n, r in enumerate(pending, 1)]
    outcome = call_model(
        provider, task=ModelTask.EXPERIMENT_APPLICABILITY, prompt=EXPERIMENT_APPLICABILITY_PROMPT_V1,
        user_input=build_experiment_user_input(
            targets=[f"[{label}] {text}" for label, text in claims],
            excerpts=[(label, ledger.excerpts[i].excerpt) for label, i in labels.items()], items=items),
        response_model=ApplicabilityResponse, llm_settings=llm_settings, bounds=ledger.bounds, performed=performed)
    if not outcome.succeeded:
        ledger.emit(outcome.failure, FAILURE_MESSAGES[outcome.failure], record.experiment_id)  # type: ignore[index, arg-type]
        return record, outcome
    by_kind = {r.kind: r for r in pending}
    decided: dict[ERK, ExperimentRequirement] = {}
    for dto in sorted(outcome.parsed.judgments, key=lambda j: (j.kind, sorted(j.fired_triggers))):
        kind = parse_enum(ERK, dto.kind)
        if kind is None or kind not in by_kind:
            ledger.reject(_C.INVENTED_REQUIREMENT, dto.kind, "a judgment for a requirement that was not asked")
            continue
        if kind in decided or ledger.unsafe(dto.rationale):
            continue
        fired = [parse_enum(ExperimentTrigger, t) for t in dto.fired_triggers]
        allowed = set(model_triggers(kind))
        if any(t is None or t not in allowed for t in fired):
            ledger.reject(_C.PARTIAL_MODEL_OUTPUT, ",".join(dto.fired_triggers), "a trigger outside the closed set")
            continue
        judgment = resolve_labels(ledger, labels, dto.excerpts)
        if not judgment:
            continue  # no bound context, no resolution: omission is never NOT_APPLICABLE
        req = by_kind[kind]
        if not fired and set(EXPERIMENT_CATALOG[kind].triggers) & phase2j_facts:
            # The model found none of its own triggers, but a Phase 2J trigger may still apply once
            # the experiment's targets are linked: the cell stays CONDITIONAL until then.
            decided[kind] = req.model_copy(update={"judgment_excerpt_ids": judgment})
            continue
        decided[kind] = resolved(req, required_by=fired, basis=ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,  # type: ignore[arg-type]
                                 judgment=judgment)
    if len(decided) < len(pending):
        ledger.emit(_C.PARTIAL_MODEL_OUTPUT, "a conditional requirement was left unjudged", record.experiment_id)
    reqs = [decided.get(r.kind, r) for r in record.requirements]
    return record.model_copy(update={"requirements": reqs}), outcome


def apply_phase2j_triggers(record: ExperimentRecord, linked_facts: frozenset[ExperimentTrigger]
                           ) -> ExperimentRecord:
    """Deterministic: a Phase 2J baseline or material condition of a target this experiment
    tests makes its CONDITIONAL baseline / operating-condition rows REQUIRED. A row the model
    judged free of its own triggers, and no Phase 2J trigger reaches, becomes NOT_APPLICABLE on
    that judgment's excerpts. Anything else stays CONDITIONAL."""
    if record.experiment_type is ExperimentType.UNKNOWN:
        return record
    out = []
    for r in record.requirements:
        if r.basis is not ApplicabilityBasis.CONDITION_UNRESOLVED or not set(EXPERIMENT_CATALOG[r.kind].triggers) & PHASE_2J_TRIGGERS:
            out.append(r)
            continue
        fired = sorted(set(EXPERIMENT_CATALOG[r.kind].triggers) & linked_facts)
        if fired:
            out.append(resolved(r, required_by=fired, basis=ApplicabilityBasis.PHASE_2J_VALIDATION_REQUIREMENT,
                                judgment=[]))
        elif r.judgment_excerpt_ids:
            out.append(resolved(r, required_by=[], basis=ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT,
                                judgment=r.judgment_excerpt_ids))
        else:
            out.append(r)
    return record.model_copy(update={"requirements": out})


__all__ = [
    "PHASE_2J_TRIGGERS",
    "apply_phase2j_triggers",
    "build_requirements",
    "excerpt_labels",
    "experiment_excerpt_ids",
    "extract_protocol",
    "model_triggers",
    "pending_conditionals",
    "resolve_conditionals",
    "resolve_labels",
    "resolved",
]
