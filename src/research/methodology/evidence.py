"""Methodology evidence extraction and conditional-applicability resolution.

One model call locates, for the applicable requirement kinds, the exact submission
text that documents each. Every excerpt is then re-derived by code as
``submission[start:end]`` (``StageLedger.anchor``); what the model said about
it -- its string, its rationale -- is never stored. Documentation status and
adequacy are two enum fields on two enums, checked against the approved
compatibility table, and a student's past tense stays a ``StatementMode`` on the
excerpt: ``execution_verified`` is not a thing this phase can set (ADR-022).

The applicability judgment can only resolve an existing CONDITIONAL catalog
requirement, only through that requirement's own closed trigger set, and only
with an exact excerpt. It cannot lower a REQUIRED requirement or add one.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import LLMSettings
from src.llm.contracts import ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import (
    METHODOLOGY_APPLICABILITY_PROMPT_V1,
    METHODOLOGY_EVIDENCE_EXTRACTION_PROMPT_V1,
    build_methodology_user_input,
)
from src.llm.provider import StructuredModelProvider
from src.research.methodology.dto import ApplicabilityResponse, EvidenceExtractionResponse
from src.research.methodology.overlays import claim_labels
from src.research.methodology.verify import StageLedger, parse_enum
from src.schemas.methodology_review import (
    _ALLOWED_ADEQUACY,
    _BARE_QUANTITY,
    RATIONALE_KINDS,
    REQUIREMENT_CATALOG,
    Applicability,
    ApplicabilityBasis,
    ApplicabilityTrigger,
    DesignAdequacy,
    DocumentationStatus,
    MethodologyReviewRun,
    MethodologyRunIssueCode,
    RequirementApplicability,
    RequirementDocumentation,
    RequirementKind,
    StatementMode,
)

EVIDENCE_NODE = "EXTRACT_METHODOLOGY_EVIDENCE"
APPLICABILITY_NODE = "RESOLVE_METHODOLOGY_APPLICABILITY"

_EXTRACTABLE = (
    DocumentationStatus.EXPLICITLY_DOCUMENTED,
    DocumentationStatus.PARTIALLY_DOCUMENTED,
    DocumentationStatus.CONFLICTING_DOCUMENTATION,
)
_FALLBACK_ADEQUACY = {
    DocumentationStatus.EXPLICITLY_DOCUMENTED: DesignAdequacy.PARTIALLY_SPECIFIED,
    DocumentationStatus.PARTIALLY_DOCUMENTED: DesignAdequacy.PARTIALLY_SPECIFIED,
    DocumentationStatus.CONFLICTING_DOCUMENTATION: DesignAdequacy.CONFLICTING_DESIGN,
}


@dataclass
class ModelStageOutcome:
    model_called: bool = False
    model_succeeded: bool = False
    failure: str | None = None


def _call(provider: StructuredModelProvider, task: ModelTask, prompt: str, user_input: str, response_model,
          llm_settings: LLMSettings | None, ledger: StageLedger):
    return call_structured_model_with_retries(
        provider, task=task, system_prompt=prompt, user_input=user_input, response_model=response_model,
        model=(llm_settings or LLMSettings()).extraction_model, max_retries=ledger.bounds.model_retry_limit)


# -- evidence extraction --------------------------------------------------------------


def extract_evidence(
    run: MethodologyReviewRun, applicability: list[RequirementApplicability], ledger: StageLedger,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, claim_texts: dict[str, str],
) -> tuple[list[RequirementDocumentation], ModelStageOutcome]:
    candidates = {a.kind: a for a in applicability
                  if a.track is not None and a.applicability is not Applicability.NOT_APPLICABLE}
    if not candidates:
        return [], ModelStageOutcome()
    if provider is None:
        return [], ModelStageOutcome(failure="no structured model provider")
    ordered = [k for k in RequirementKind if k in candidates]
    items = [f"[R{i}] {k.value} ({candidates[k].applicability.value}; {candidates[k].track.value})"  # type: ignore[union-attr]
             for i, k in enumerate(ordered, 1)]
    shown = ledger.submission_text[: ledger.bounds.max_submission_chars]
    c_labels = claim_labels(run)
    call = _call(
        provider, ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION, METHODOLOGY_EVIDENCE_EXTRACTION_PROMPT_V1,
        build_methodology_user_input(shown, [(l, claim_texts[c]) for l, c in c_labels.items()], items),
        EvidenceExtractionResponse, llm_settings, ledger)
    if not call.succeeded or not isinstance(call.parsed, EvidenceExtractionResponse):
        return [], ModelStageOutcome(model_called=True, failure=call.status.value)
    docs: dict[RequirementKind, RequirementDocumentation] = {}
    for dto in sorted(call.parsed.requirements, key=lambda r: (r.kind, r.documentation)):
        kind = parse_enum(RequirementKind, dto.kind)
        if kind is None or kind not in candidates:
            ledger.reject(MethodologyRunIssueCode.INVENTED_REQUIREMENT, dto.kind, off_contract=True)
            continue
        if kind in docs:
            ledger.reject(MethodologyRunIssueCode.INVALID_INPUT, dto.kind)
            continue
        built = _document(kind, candidates[kind], dto, ledger)
        if built is not None:
            docs[kind] = built
    return [docs[k] for k in ordered if k in docs], ModelStageOutcome(model_called=True, model_succeeded=True)


def _document(kind: RequirementKind, applicability: RequirementApplicability, dto, ledger: StageLedger
              ) -> RequirementDocumentation | None:
    if ledger.unsafe(EVIDENCE_NODE, *(e.rationale for e in dto.excerpts)):
        return None
    documentation = parse_enum(DocumentationStatus, dto.documentation)
    if documentation not in _EXTRACTABLE:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.documentation, off_contract=True)
        return None
    ids: list = []
    for span in dto.excerpts:
        mode = parse_enum(StatementMode, span.statement_mode)
        if mode is None:
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, span.statement_mode, off_contract=True)
            mode = StatementMode.MODE_NOT_DETERMINED
        excerpt_id = ledger.anchor(span, mode)
        if excerpt_id is not None and excerpt_id not in ids:
            ids.append(excerpt_id)
    if kind in RATIONALE_KINDS:  # a bare quantity ("N = 500") is never a rationale
        kept = [i for i in ids if not _BARE_QUANTITY.match(ledger.excerpts[i].excerpt)]
        if len(kept) != len(ids):
            ledger.reject(MethodologyRunIssueCode.INVALID_INPUT, kind.value)
        ids = kept
    if documentation is DocumentationStatus.CONFLICTING_DOCUMENTATION and len(ids) < 2:
        documentation = DocumentationStatus.PARTIALLY_DOCUMENTED  # one side is all the bound input shows
    if not ids:
        return None
    adequacy = parse_enum(DesignAdequacy, dto.adequacy)
    if adequacy is None:
        ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, dto.adequacy, off_contract=True)
    if adequacy is None or adequacy not in _ALLOWED_ADEQUACY[documentation]:
        adequacy = _FALLBACK_ADEQUACY[documentation]
    if adequacy is DesignAdequacy.ADEQUATELY_SPECIFIED_FOR_REVIEW and all(
            _BARE_QUANTITY.match(ledger.excerpts[i].excerpt) for i in ids):
        adequacy = DesignAdequacy.PARTIALLY_SPECIFIED  # a number alone is never an adequate specification
    return RequirementDocumentation(
        methodology_run_id=ledger.run.methodology_run_id, kind=kind, track=applicability.track,  # type: ignore[arg-type]
        documentation=documentation, adequacy=adequacy, excerpt_ids=ids)


# -- conditional applicability --------------------------------------------------------


def resolve_conditionals(
    run: MethodologyReviewRun, pending: list[RequirementApplicability], ledger: StageLedger,
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None, claim_texts: dict[str, str],
) -> tuple[dict[RequirementKind, RequirementApplicability], ModelStageOutcome]:
    """Resolve CONDITIONAL requirements the deterministic triggers could not settle."""
    if not pending:
        return {}, ModelStageOutcome()
    if provider is None:
        return {}, ModelStageOutcome(failure="no structured model provider")
    by_kind = {a.kind: a for a in pending}
    ordered = [k for k in RequirementKind if k in by_kind]
    items = [
        f"[R{i}] {k.value}; triggers: {', '.join(t.value for t in REQUIREMENT_CATALOG[k].triggers)}"
        for i, k in enumerate(ordered, 1)
    ]
    shown = ledger.submission_text[: ledger.bounds.max_submission_chars]
    c_labels = claim_labels(run)
    call = _call(
        provider, ModelTask.METHODOLOGY_APPLICABILITY, METHODOLOGY_APPLICABILITY_PROMPT_V1,
        build_methodology_user_input(shown, [(l, claim_texts[c]) for l, c in c_labels.items()], items),
        ApplicabilityResponse, llm_settings, ledger)
    if not call.succeeded or not isinstance(call.parsed, ApplicabilityResponse):
        return {}, ModelStageOutcome(model_called=True, failure=call.status.value)
    resolved: dict[RequirementKind, RequirementApplicability] = {}
    for dto in sorted(call.parsed.judgments, key=lambda j: j.kind):
        kind = parse_enum(RequirementKind, dto.kind)
        if kind is None or kind not in by_kind or kind in resolved:
            ledger.reject(MethodologyRunIssueCode.INVENTED_REQUIREMENT, dto.kind, off_contract=True)
            continue
        if ledger.unsafe(APPLICABILITY_NODE, dto.excerpt.rationale if dto.excerpt else None):
            continue
        fired = [parse_enum(ApplicabilityTrigger, t) for t in dto.fired_triggers]
        allowed = set(REQUIREMENT_CATALOG[kind].triggers)
        if any(t is None or t not in allowed for t in fired):
            ledger.reject(MethodologyRunIssueCode.OFF_CONTRACT_OUTPUT, ",".join(dto.fired_triggers), off_contract=True)
            continue
        excerpt_id = ledger.anchor(dto.excerpt)
        if excerpt_id is None:
            continue  # no exact excerpt, no resolution: the requirement stays CONDITIONAL
        triggers = sorted(set(fired))  # type: ignore[type-var]
        resolved[kind] = RequirementApplicability(
            methodology_run_id=run.methodology_run_id, kind=kind, track=by_kind[kind].track,
            applicability=Applicability.REQUIRED if triggers else Applicability.NOT_APPLICABLE,
            basis=ApplicabilityBasis.MODEL_ASSISTED_BOUNDED_JUDGMENT, triggers=triggers,
            judgment_excerpt_ids=[excerpt_id])
    return resolved, ModelStageOutcome(model_called=True, model_succeeded=True)


__all__ = ["APPLICABILITY_NODE", "EVIDENCE_NODE", "ModelStageOutcome", "extract_evidence", "resolve_conditionals"]
