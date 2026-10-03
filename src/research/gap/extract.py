"""Gap candidate extraction and exact anchor verification (one claim, one call).

The untrusted ``GapExtractionResponse`` is verified here, in the same stage
boundary that receives it, so unverified model output never reaches a
checkpoint (ADR-021). What survives is a ``GapClaimDraft`` holding only
code-verified records:

* capabilities, limitations and conditions are exact excerpts of texts the
  model was shown, at one validated occurrence;
* limitation form and facet are typed enums; an absence basis is refused and
  the refusal recorded;
* a metric or baseline is an exact slice of the student claim or of a verified
  excerpt -- a metric the sources do not contain is ``INVENTED_METRIC``;
* the model's proposed gap kind is recorded and never used.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import LLMSettings
from src.llm.contracts import ModelCallStatus, ModelTask
from src.llm.invocation import call_structured_model_with_retries
from src.llm.prompts import GAP_CANDIDATE_EXTRACTION_PROMPT_V1, build_gap_extraction_user_input
from src.llm.provider import StructuredModelProvider
from src.research.gap import verify as v
from src.research.gap.dto import GapExtractionResponse, LimitationDTO
from src.research.gap.inventory import ShownText
from src.research.novelty.anchoring import LocateFailure, locate
from src.schemas.claim import ClaimRecord
from src.schemas.gap_assessment import (
    FACET_ELIGIBLE_TYPES,
    NUMERIC_LIMITATION_TYPES,
    ConditionDimension,
    GapAssessmentBounds,
    GapAssessmentIssue,
    GapClaimDraft,
    GapCondition,
    GapEvidenceRef,
    GapEvidenceRole,
    GapExistingCapability,
    GapFacet,
    GapIssueCode,
    GapKind,
    GapLimitation,
    GapLimitationType,
    GapValidationRequirement,
    InadmissibleLimitationBasis,
    InsufficientReason,
    RejectedGapProposal,
    SourceQualityVerdict,
    ValidationAnchor,
    ValidationAnchorOrigin,
    gap_id,
    proposition_key,
)

NODE = "EXTRACT_GAP_CANDIDATES"


@dataclass
class StageOutcome:
    draft: GapClaimDraft
    rejected: list[RejectedGapProposal]
    issues: list[GapAssessmentIssue]
    model_called: bool = False


def _issue(code: GapIssueCode, message: str, claim_id: str) -> GapAssessmentIssue:
    return GapAssessmentIssue(code=code, node=NODE, message=message[:200], claim_id=claim_id)


def _enum(enum_type, value: str | None):
    try:
        return enum_type((value or "").strip().upper())
    except ValueError:
        return None


def _is_basis(value: str | None) -> InadmissibleLimitationBasis | None:
    return _enum(InadmissibleLimitationBasis, value)


def extract_claim(
    *, gap_run_id, claim: ClaimRecord, draft: GapClaimDraft, shown: list[ShownText],
    provider: StructuredModelProvider, llm_settings: LLMSettings | None, bounds: GapAssessmentBounds,
) -> StageOutcome:
    """One model call for one claim, then deterministic verification."""
    model = (llm_settings or LLMSettings()).extraction_model
    texts = [(t.token, (t.item.text_kind.value if t.item.text_kind else "ACADEMIC_EXCERPT"), t.shown) for t in shown]
    call = call_structured_model_with_retries(
        provider,
        task=ModelTask.GAP_CANDIDATE_EXTRACTION,
        system_prompt=GAP_CANDIDATE_EXTRACTION_PROMPT_V1,
        user_input=build_gap_extraction_user_input(claim.claim, texts),
        response_model=GapExtractionResponse,
        model=model,
        max_retries=bounds.model_retry_limit,
    )
    if not call.succeeded or not isinstance(call.parsed, GapExtractionResponse):
        detail = f"model call did not yield a usable response: {call.status.value}"  # provider text is never persisted
        code = GapIssueCode.MODEL_ERROR
        failed = draft.model_copy(update={
            "insufficient_reasons": [*draft.insufficient_reasons, InsufficientReason.MODEL_CALL_FAILED],
            "extraction_done": True,
        })
        return StageOutcome(failed, [], [_issue(code, detail, claim.claim_id)], model_called=True)
    return verify_extraction(
        gap_run_id=gap_run_id, claim=claim, draft=draft, shown=shown, response=call.parsed, bounds=bounds,
    )


def verify_extraction(
    *, gap_run_id, claim: ClaimRecord, draft: GapClaimDraft, shown: list[ShownText],
    response: GapExtractionResponse, bounds: GapAssessmentBounds,
) -> StageOutcome:
    cid = claim.claim_id
    by_token = {t.token: t for t in shown}
    shown_strings = v.shown_texts_of(by_token)
    rejected: list[RejectedGapProposal] = []
    issues: list[GapAssessmentIssue] = []
    refs: dict = {}
    leaked = False

    def reject(reason: str, model_text: str = "", basis=None, note: str = "") -> None:
        rejected.append(v.rejection(cid, reason, model_text=model_text, note=note, basis=basis))

    def unsafe(*texts: str | None) -> str | None:
        """A reason when model prose follows an instruction; the item is refused."""
        nonlocal leaked
        if any(v.discloses_system_prompt(t, shown_strings) for t in texts):
            if not leaked:
                issues.append(_issue(GapIssueCode.PROMPT_LEAK_REDACTED, "hidden prompt disclosure redacted", cid))
                leaked = True
            return v.R_PROMPT_DISCLOSURE
        if any(v.forbidden_conclusion(t) for t in texts):
            issues.append(_issue(GapIssueCode.FORBIDDEN_CONCLUSION, "forbidden conclusion in model prose", cid))
            return v.R_FORBIDDEN_CONCLUSION
        return None

    def span_ref(dto, role: GapEvidenceRole, *, need_eligible: bool) -> GapEvidenceRef | None:
        verdict = v.verify_span(
            by_token, dto.text, (dto.excerpt or "").strip(), start=dto.start, end=dto.end,
            occurrence=dto.occurrence, claim_text=claim.claim,
        )
        if isinstance(verdict, str):
            if verdict in (v.R_NOT_IN_TEXT, v.R_CLAIM_AS_EVIDENCE, v.R_UNKNOWN_TEXT):
                issues.append(_issue(GapIssueCode.FABRICATED_ANCHOR, "unverifiable excerpt rejected", cid))
            elif verdict == v.R_AMBIGUOUS:
                issues.append(_issue(GapIssueCode.AMBIGUOUS_ANCHOR, "repeated excerpt without disambiguator", cid))
            reject(verdict, dto.excerpt or "")
            return None
        if need_eligible and verdict.shown.item.source_quality is not SourceQualityVerdict.ELIGIBLE:
            reject(v.R_INELIGIBLE_SOURCE, note=f"{role.value} from {verdict.shown.item.source_quality.value}")
            return None
        ref = v.make_ref(gap_run_id, cid, role, verdict)
        refs[ref.evidence_ref_id] = ref
        return ref

    # -- capabilities ---------------------------------------------------------
    capabilities: list[GapExistingCapability] = []
    capability_refs: dict[str, GapEvidenceRef] = {}
    for dto in response.capabilities[: bounds.max_capabilities_per_claim]:
        label = (dto.label or "").strip().upper()
        if (reason := unsafe(dto.rationale, dto.excerpt)) or label in capability_refs:
            reject(reason or v.R_DUPLICATE_LABEL, dto.excerpt or "")
            continue
        ref = span_ref(dto, GapEvidenceRole.EXISTING_CAPABILITY, need_eligible=True)
        if ref is not None:
            capability_refs[label] = ref
            capabilities.append(GapExistingCapability(
                capability_id=gap_id(gap_run_id, cid, "capability", ref.evidence_ref_id),
                evidence_ref_ids=[ref.evidence_ref_id],
            ))
    if len(response.capabilities) > bounds.max_capabilities_per_claim:
        reject(v.R_BOUND, note="capabilities")

    # -- limitations ----------------------------------------------------------
    limitations: list[GapLimitation] = []
    conditions: list[GapCondition] = []
    limitation_refs: dict[str, GapEvidenceRef] = {}
    limitation_conditions: dict[str, list[GapCondition]] = {}
    seen_keys: set = set()
    for dto in response.limitations[: bounds.max_limitations_per_claim]:
        built = _limitation(dto, gap_run_id, cid, span_ref, unsafe, reject, bounds, limitation_refs, seen_keys)
        if built is None:
            continue
        limitation, ref, own_conditions = built
        limitations.append(limitation)
        limitation_refs[(dto.label or "").strip().upper()] = ref
        limitation_conditions[(dto.label or "").strip().upper()] = own_conditions
        conditions.extend(own_conditions)
    if len(response.limitations) > bounds.max_limitations_per_claim:
        reject(v.R_BOUND, note="limitations")

    # -- validation requirement -----------------------------------------------
    requirement = _validation(
        response, claim, gap_run_id, limitation_refs, capability_refs, limitation_conditions, reject, issues, cid
    )
    if not limitations:
        requirement = None

    kept_refs = _referenced(refs, capabilities, limitations, conditions)
    updated = draft.model_copy(update={
        "evidence_refs": sorted(kept_refs.values(), key=lambda r: str(r.evidence_ref_id)),
        "existing_capabilities": sorted(capabilities, key=lambda c: str(c.capability_id)),
        "limitations": sorted(limitations, key=lambda x: str(x.limitation_id)),
        "conditions": sorted(conditions, key=lambda c: str(c.condition_id)),
        "validation_requirement": requirement,
        "model_proposed_kind": _enum(GapKind, response.proposed_kind),
        "rejected_count": draft.rejected_count + len(rejected),
        "extraction_done": True,
    })
    return StageOutcome(updated, rejected, issues, model_called=True)


def _referenced(refs: dict, capabilities, limitations, conditions) -> dict:
    """Only excerpts a surviving record actually cites stay on the draft."""
    wanted = {i for c in capabilities for i in c.evidence_ref_ids}
    wanted |= {i for x in limitations for i in x.evidence_ref_ids}
    wanted |= {i for c in conditions for i in c.evidence_ref_ids}
    return {k: r for k, r in refs.items() if k in wanted}


def _limitation(
    dto: LimitationDTO, gap_run_id, cid: str, span_ref, unsafe, reject, bounds, limitation_refs, seen_keys,
):
    label = (dto.label or "").strip().upper()
    if label in limitation_refs:
        reject(v.R_DUPLICATE_LABEL, dto.excerpt or "")
        return None
    if reason := unsafe(dto.rationale, dto.excerpt, *(c.rationale for c in dto.conditions)):
        reject(reason, dto.excerpt or "")
        return None
    if (basis := _is_basis(dto.limitation_type)) is not None:
        reject(v.R_INADMISSIBLE_BASIS, dto.excerpt or "", basis=basis)
        return None
    ltype = _enum(GapLimitationType, dto.limitation_type)
    facet = _enum(GapFacet, dto.facet)
    if ltype is None:
        reject(v.R_INVALID_TYPE, dto.limitation_type or "")
        return None
    if facet is None:
        reject(v.R_INVALID_FACET, dto.facet or "")
        return None
    if ltype not in FACET_ELIGIBLE_TYPES[facet]:
        reject(v.R_FACET_TYPE, note=f"{ltype.value}/{facet.value}")
        return None
    dimensions = [_enum(ConditionDimension, d) for d in dto.condition_dimensions]
    if any(d is None for d in dimensions):
        reject(v.R_INVALID_DIMENSION, ",".join(dto.condition_dimensions))
        return None
    dims = list(dict.fromkeys(d for d in dimensions if d is not None))
    if ltype is GapLimitationType.SCOPE_RESTRICTION and not dims:
        reject(v.R_SCOPE_NEEDS_DIMENSION, dto.excerpt or "")
        return None
    ref = span_ref(dto, GapEvidenceRole.LIMITATION, need_eligible=False)
    if ref is None:
        return None
    if ltype in NUMERIC_LIMITATION_TYPES and not any(ch.isdigit() for ch in ref.excerpt):
        reject(v.R_SHORTFALL_NO_NUMBER, ref.excerpt)
        return None
    limitation_id = gap_id(gap_run_id, cid, "limitation", ltype.value, ref.source_record_id, ref.start, ref.end)
    limitation = GapLimitation(
        limitation_id=limitation_id, limitation_type=ltype, facet=facet,
        evidence_ref_ids=[ref.evidence_ref_id], condition_dimensions=dims,
    )
    key = proposition_key(limitation, {ref.evidence_ref_id: ref})
    if key in seen_keys:
        reject(v.R_DUPLICATE_PROPOSITION, ref.excerpt)
        return None
    seen_keys.add(key)
    own: list[GapCondition] = []
    for cdto in dto.conditions[: bounds.max_conditions_per_limitation]:
        dimension = _enum(ConditionDimension, cdto.dimension)
        if dimension is None:
            reject(v.R_INVALID_DIMENSION, cdto.dimension or "")
            continue
        cref = span_ref(cdto, GapEvidenceRole.CONDITION, need_eligible=True)
        if cref is None:
            continue
        own.append(GapCondition(
            condition_id=gap_id(gap_run_id, cid, "condition", limitation_id, dimension.value, cref.evidence_ref_id),
            dimension=dimension, limitation_ids=[limitation_id], evidence_ref_ids=[cref.evidence_ref_id],
        ))
    return limitation, ref, own


def _slice(text: str, needle: str, start: int | None, occurrence: int | None):
    located = locate(text, needle, start=start, occurrence=occurrence)
    return None if isinstance(located, LocateFailure) else located


def _anchor(source: str | None, text: str | None, start, occurrence, claim, gap_refs, role_origin):
    """A ``ValidationAnchor`` sliced from the claim or one verified excerpt, or None."""
    if not text:
        return None
    label = (source or "").strip().upper()
    if label == "CLAIM":
        located = _slice(claim.claim, text, start, occurrence)
        if located is None:
            return None
        return ValidationAnchor(
            origin=ValidationAnchorOrigin.STUDENT_CLAIM_TEXT, text=text, claim_id=claim.claim_id,
            start=located.start, end=located.end,
        )
    ref = gap_refs.get(label)
    if ref is None or ref.source_quality is not SourceQualityVerdict.ELIGIBLE:
        return None
    located = _slice(ref.excerpt, text, start, occurrence)
    if located is None:
        return None
    return ValidationAnchor(
        origin=role_origin, text=text, evidence_ref_id=ref.evidence_ref_id,
        start=ref.start + located.start, end=ref.start + located.end,
    )


def _validation(response, claim, gap_run_id, limitation_refs, capability_refs, limitation_conditions, reject, issues, cid):
    dto = response.validation
    if dto is None:
        return None
    metric = _anchor(
        dto.metric_source, dto.metric, dto.metric_start, dto.metric_occurrence, claim, limitation_refs,
        ValidationAnchorOrigin.LIMITATION_EVIDENCE,
    )
    if metric is None:
        reject(v.R_INVENTED_METRIC, dto.metric or "")
        issues.append(_issue(GapIssueCode.INVENTED_METRIC, "metric not found in the named source", cid))
        return None
    baseline = None
    if dto.baseline:
        baseline = _anchor(
            dto.baseline_source, dto.baseline, dto.baseline_start, dto.baseline_occurrence, claim, capability_refs,
            ValidationAnchorOrigin.EXISTING_CAPABILITY_EVIDENCE,
        )
        if baseline is None:
            reject(v.R_INVENTED_BASELINE, dto.baseline)
            issues.append(_issue(GapIssueCode.INVENTED_METRIC, "baseline not found in the named source", cid))
    condition_ids = []
    if metric.evidence_ref_id is not None:
        label = (dto.metric_source or "").strip().upper()
        condition_ids = [c.condition_id for c in limitation_conditions.get(label, [])]
    return GapValidationRequirement(
        requirement_id=gap_id(gap_run_id, cid, "validation-requirement", metric.start, metric.end),
        metric=metric, baseline=baseline, condition_ids=condition_ids,
    )


__all__ = ["NODE", "StageOutcome", "extract_claim", "verify_extraction"]
