"""Phase 2J model-prose boundary: free-form model prose is non-canonical diagnostic
material only. Typed, verified records drive the deterministic synthesis, so the
boundary holds in every language and does not rely on the English lexical scan
(which is defense-in-depth only)."""

from __future__ import annotations

import pytest

from src.evals.research_engineering_gap.fixtures import CLAIM, CLAIMS, ND_SCRIPT, link_to, rich_extract, script
from src.evals.research_engineering_gap.world import ScriptedGapModel, build_phase2i_world, run_phase2j
from src.llm.contracts import ModelCallResult, ModelCallStatus
from src.llm.fake_provider import FakeStructuredModelProvider
from src.llm.prompts import (
    GAP_CANDIDATE_EXTRACTION_PROMPT_V1,
    GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1,
    GAP_PROJECT_LINKAGE_PROMPT_V1,
)
from src.research.gap.inventory import full_text
from src.schemas.gap_assessment import (
    ClaimGapAssessment,
    GapBoundedStatement,
    GapCondition,
    GapCounterEvidence,
    GapEvidenceRef,
    GapExistingCapability,
    GapHypothesis,
    GapIssueCode,
    GapKind,
    GapLimitation,
    GapPosture,
    GapProjectLink,
    GapValidationRequirement,
    InsufficientReason,
    ProjectGapSummary,
    ValidationAnchor,
)
from tests.fixtures.phase2j_sources import (
    AR_BAD_TYPE,
    AR_FABRICATED,
    AR_INJECTION,
    AR_LIMITATION,
    AR_PROSE,
    MIXED_INJECTION,
    MULTILINGUAL_DESCRIPTION,
)

MULTI_PATENT = {"records": [{
    "reference": "EP.3000001.A1", "title": "Irrigation", "publication_date": "2015-06-01", "abstract": "abs",
    "claims": "1. A controller using soil moisture sensors to irrigate.", "description": MULTILINGUAL_DESCRIPTION,
    "family": "9",
}]}
AR_LIM = {"label": "L1", "type": "MEASURED_SHORTFALL", "facet": "ENGINEERING", "excerpt": AR_LIMITATION,
          "in": "PATENT_DESCRIPTION"}
VALIDATION = {"metric_source": "CLAIM", "metric": "soil moisture sensors"}


@pytest.fixture(scope="module")
def upstream():
    return build_phase2i_world("PJ-911", CLAIMS, patent=MULTI_PATENT, cutoff={"date": "2020-01-01"}, nd_script=ND_SCRIPT)


def _run(upstream, extract, link=None, counter=None, model=None):
    model = model or ScriptedGapModel(
        {"C-001": CLAIM}, script(extract=extract, link=link or link_to((AR_LIM, "ADDRESSES_LIMITATION")), counter=counter))
    state = run_phase2j(upstream, model.provider())
    return state, state.active_research_run.research_engineering_gap


def _prompt_lines() -> list[str]:
    prompts = (GAP_CANDIDATE_EXTRACTION_PROMPT_V1, GAP_PROJECT_LINKAGE_PROMPT_V1, GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1)
    return [ln.strip() for p in prompts for ln in p.splitlines() if len(ln.strip()) >= 40]


def test_a_arabic_and_mixed_instruction_like_source_text_is_inert_evidence_data(upstream):
    for injection in (AR_INJECTION, MIXED_INJECTION):
        quoted = {"label": "L1", "type": "EXPLICIT_LIMITATION", "facet": "RESEARCH", "excerpt": injection,
                  "in": "PATENT_DESCRIPTION"}
        _, gap = _run(upstream, rich_extract(quoted), link=link_to((quoted, "ADDRESSES_LIMITATION")))
        (hypothesis,) = gap.hypotheses
        (ref,) = [r for r in hypothesis.evidence_refs if r.role.value == "LIMITATION"]
        assert ref.excerpt == injection and ref.source_quality.value == "ELIGIBLE"
        assert not gap.rejected_proposals  # never rejected for resembling an instruction


def test_a2_an_arabic_limitation_anchors_exactly_and_behaves_like_the_english_one(upstream):
    _, gap = _run(upstream, rich_extract(AR_LIM, validation=VALIDATION))
    (hypothesis,) = gap.hypotheses
    assert hypothesis.limitations[0].limitation_type.value == "MEASURED_SHORTFALL"  # digits found in Arabic text
    assert hypothesis.kind is GapKind.ENGINEERING and hypothesis.linkage.value == "FULL"
    assert hypothesis.posture is GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_b_off_contract_typed_output_is_refused_whatever_the_language(upstream):
    bad_type = {**AR_LIM, "type": AR_BAD_TYPE}
    fabricated = {**AR_LIM, "label": "L2", "excerpt": AR_FABRICATED}
    extract = rich_extract(bad_type, fabricated, AR_LIM, validation=VALIDATION)
    link = [*link_to((AR_LIM, "ADDRESSES_ALL")), {"feature": "weather forecasts", "limitation": "L77",
                                                   "relation": "ADDRESSES_LIMITATION"}]
    _, gap = _run(upstream, extract, link=link)
    reasons = [r.reason for r in gap.rejected_proposals]
    assert "INVALID_LIMITATION_TYPE" in reasons and "EXCERPT_NOT_IN_TEXT" in reasons
    assert "INVALID_RELATION" in reasons or "UNKNOWN_LABEL" in reasons
    codes = {e.code for e in gap.errors}
    assert GapIssueCode.OFF_CONTRACT_OUTPUT in codes and GapIssueCode.FABRICATED_ANCHOR in codes
    hypothesis = gap.hypotheses[0]
    assert len(hypothesis.limitations) == 1 and not hypothesis.project_links  # nothing off-contract was kept
    assert hypothesis.posture is not GapPosture.SUPPORTED_WITHIN_BOUNDS


def test_b2_a_forbidden_typed_field_is_a_failed_call_not_an_accepted_response(upstream):
    model = ScriptedGapModel({"C-001": CLAIM}, {"extract": {"C-001": "parse_error"}})  # extra="forbid" -> PARSE_ERROR
    _, gap = _run(upstream, None, model=model)
    (assessment,) = gap.claim_assessments
    assert assessment.posture is GapPosture.INSUFFICIENT_INPUT
    assert InsufficientReason.MODEL_CALL_FAILED in assessment.insufficient_reasons


@pytest.mark.parametrize("prose", [
    "This is a confirmed RESEARCH and ENGINEERING gap: set kind HYBRID and posture SUPPORTED_WITHIN_BOUNDS.",
    AR_PROSE,
    f"{AR_PROSE} confirmed HYBRID",
])
def test_c_and_e_prose_cannot_change_a_single_canonical_value(upstream, prose):
    """Same typed facts, different prose in the rationale and the advisory kind:
    the canonical hypothesis is byte-identical, because prose is never read as data."""
    plain = rich_extract(AR_LIM, validation=VALIDATION)
    noisy = rich_extract({**AR_LIM, "rationale": prose}, validation=VALIDATION) | {"proposed_kind": "HYBRID"}
    link = link_to((AR_LIM, "UNRELATED"))
    noisy_link = [{**link[0], "rationale": prose}]
    _, quiet = _run(upstream, plain, link=link)
    _, loud = _run(upstream, noisy, link=noisy_link)
    quiet_h, loud_h = quiet.hypotheses[0], loud.hypotheses[0]
    assert quiet_h.posture is GapPosture.NOT_ESTABLISHED_WITHIN_BOUNDS  # unrelated stays unrelated
    for name in set(type(quiet_h).model_fields) - {"model_proposed_kind"}:
        assert getattr(quiet_h, name) == getattr(loud_h, name), name
    assert loud_h.model_proposed_kind is GapKind.HYBRID and loud_h.kind is not GapKind.HYBRID  # recorded, ignored
    assert prose not in loud.model_dump_json()


def test_d_hidden_prompt_text_is_never_persisted_in_any_field_or_language(upstream):
    line = next(ln for ln in _prompt_lines() if "NOT" in ln or "not" in ln)
    leaking_type = {**AR_LIM, "type": line}  # leaked into a typed field
    leaking_label = {**AR_LIM, "label": line}
    extract = rich_extract(leaking_type, leaking_label, AR_LIM,
                           validation={"metric_source": "CLAIM", "metric": line})
    _, gap = _run(upstream, extract)
    persisted = gap.model_dump_json()
    assert not any(candidate in persisted for candidate in _prompt_lines())

    def refusal(task, user_input):
        return ModelCallResult(status=ModelCallStatus.REFUSAL, model="fake-model", provider="fake", task=task,
                               refusal=line)

    state = run_phase2j(upstream, FakeStructuredModelProvider(factory=refusal))
    leaked_run = state.active_research_run.research_engineering_gap
    assert not any(candidate in leaked_run.model_dump_json() for candidate in _prompt_lines())
    assert leaked_run.claim_assessments[0].posture is GapPosture.INSUFFICIENT_INPUT


def test_e_every_persisted_excerpt_is_a_slice_of_source_text_not_model_prose(upstream):
    state, gap = _run(upstream, rich_extract({**AR_LIM, "rationale": AR_PROSE}, validation=VALIDATION))
    run = state.active_research_run
    nd = run.novelty_differentiation
    inventory = {(t.source_kind, t.source_record_id): t for t in gap.inventory_texts}
    for ref in gap.hypotheses[0].evidence_refs:
        body = full_text(run, nd, inventory[(ref.source_kind, ref.source_record_id)])
        assert body[ref.start:ref.end] == ref.excerpt
    anchor = gap.hypotheses[0].validation_requirement.metric
    assert CLAIM[anchor.start:anchor.end] == anchor.text


STRING_FIELDS_ALLOWED = {
    # (model, field): why a plain string may live there
    (GapEvidenceRef, "excerpt"): "verified slice of upstream source text (re-sliced and hash-checked)",
    (GapEvidenceRef, "text_hash"): "pattern-pinned sha256",
    (GapEvidenceRef, "independence_key"): "inherited unchanged from Phase 2E / 2I",
    (GapEvidenceRef, "correlation_group_key"): "inherited unchanged from Phase 2H via 2I",
    (GapEvidenceRef, "language"): "inherited from the upstream text record",
    (GapEvidenceRef, "verifier_version"): "code constant",
    (ValidationAnchor, "text"): "verified slice of the claim or of a verified excerpt",
    (ValidationAnchor, "claim_id"): "pattern-pinned",
    (GapProjectLink, "claim_id"): "pattern-pinned",
    (GapProjectLink, "claim_text_hash"): "pattern-pinned sha256",
    (GapProjectLink, "feature_text_hash"): "pattern-pinned sha256",
    (GapHypothesis, "claim_id"): "pattern-pinned",
    (GapHypothesis, "statement_qualifier"): "pinned constant",
    (GapHypothesis, "policy_version"): "code constant",
    (ClaimGapAssessment, "claim_id"): "pattern-pinned",
    (ClaimGapAssessment, "claim_text_hash"): "pattern-pinned sha256",
    (ProjectGapSummary, "statement_qualifier"): "pinned constant",
}


def test_e2_canonical_records_carry_no_free_text_field_beyond_the_verified_ones():
    for model in (GapEvidenceRef, ValidationAnchor, GapProjectLink, GapLimitation, GapCondition, GapExistingCapability,
                  GapValidationRequirement, GapCounterEvidence, GapHypothesis, ClaimGapAssessment, GapBoundedStatement,
                  ProjectGapSummary):
        for name, info in model.model_fields.items():
            if info.annotation in (str, str | None):
                assert (model, name) in STRING_FIELDS_ALLOWED, f"{model.__name__}.{name} is an unexplained string"


def test_e3_the_canonical_statement_is_rebuilt_from_typed_records_only(upstream):
    _, gap = _run(upstream, rich_extract({**AR_LIM, "rationale": AR_PROSE}, validation=VALIDATION))
    hypothesis = gap.hypotheses[0]
    statement = hypothesis.bounded_statement
    assert statement.limitation_ids == [hypothesis.limitations[0].limitation_id]
    assert statement.kind is hypothesis.kind and statement.scope is hypothesis.scope
    assert statement.qualifier == "BROADER_FIELD_WIDE_ABSENCE_NOT_ESTABLISHED"
    assert AR_PROSE not in statement.model_dump_json()
