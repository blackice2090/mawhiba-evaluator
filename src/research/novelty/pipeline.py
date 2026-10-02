"""Phase 2I stages over a ``NoveltyDifferentiationRun``.

Each stage takes the persisted run and returns a validated successor. A stage
that already ran is a no-op (``stage_markers``), so a LangGraph replay after an
interrupt never duplicates a comparison, and a finished run is never reopened
(section 30). No stage reads or writes anything but the Phase 2I run: claims,
the Phase 2E inventory and the Phase 2G/2H candidates are inputs only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from src.config.settings import LLMSettings
from src.llm.provider import StructuredModelProvider
from src.research.novelty.candidates import build_profiles, resolve_text
from src.research.novelty.comparison import ForeignTexts, compare_pair, unexecuted
from src.research.novelty.features import build_inventory
from src.research.novelty.synthesis import synthesize_claim, synthesize_project
from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import claim_text_digest, is_material_text
from src.schemas.novelty_differentiation import (
    CANDIDATE_TYPE_ORDER,
    COMPARABLE_ELIGIBILITY,
    CandidateComparisonProfile,
    CandidateType,
    ClaimCandidateComparison,
    ClaimEligibilityStatus,
    ClaimInput,
    ComparisonStatus,
    NoveltyComparisonBounds,
    NoveltyDifferentiationRun,
    NoveltyIssue,
    NoveltyIssueCode,
    NoveltyRunStatus,
    NoveltyRunVersions,
    novelty_id,
)
from src.schemas.research import ResearchRun

STAGE_CLAIMS = "CLAIM_INPUTS"
STAGE_INVENTORY = "FEATURE_INVENTORY"
STAGE_PROFILES = "CANDIDATE_PROFILES"
STAGE_COMPARE = "COMPARISON"
STAGE_SYNTHESIS = "CLAIM_SYNTHESIS"
STAGE_PROJECT = "PROJECT_SYNTHESIS"

_COMPLETE = "COMPLETE_WITHIN_CONFIGURED_BOUNDS"


def nd_run_id_for(research_run_id: UUID) -> UUID:
    return novelty_id(research_run_id, "novelty-differentiation")


def _evolve(run: NoveltyDifferentiationRun, **changes: Any) -> NoveltyDifferentiationRun:
    return NoveltyDifferentiationRun.model_validate({**dict(run), **changes})


def _marked(run: NoveltyDifferentiationRun, stage: str) -> list[str]:
    return [*run.stage_markers, stage]


def _issue(code: NoveltyIssueCode, node: str, message: str, **kw: Any) -> NoveltyIssue:
    return NoveltyIssue(code=code, node=node, message=message[:200], **kw)


def open_novelty_run(
    research_run: ResearchRun, bounds: NoveltyComparisonBounds, started_at: datetime,
    *, provider_name: str | None = None, model_name: str | None = None,
) -> NoveltyDifferentiationRun:
    """Bind the Phase 2I run to the finished prior-art subruns it will consume.

    A subrun that is not yet terminal is not consumed: comparing against a
    discovery still in progress would present an unfinished candidate set as
    the bounded set.
    """
    patent = research_run.patent_prior_art
    product = research_run.product_prior_art
    oss = research_run.open_source_prior_art
    errors: list[NoveltyIssue] = []
    consumed: dict[CandidateType, Any] = {}
    for candidate_type, subrun in (
        (CandidateType.PATENT, patent), (CandidateType.PRODUCT, product), (CandidateType.OPEN_SOURCE, oss),
    ):
        if subrun is None:
            continue
        if not subrun.is_terminal:
            errors.append(_issue(NoveltyIssueCode.INVALID_INPUT, "OPEN",
                                 f"{candidate_type.value} prior-art subrun is not finished; not consumed"))
            continue
        consumed[candidate_type] = subrun
    partial = [t for t in CANDIDATE_TYPE_ORDER if t in consumed and consumed[t].coverage_status.value != _COMPLETE]
    sufficiency = research_run.claim_sufficiency
    nd = nd_run_id_for(research_run.research_run_id)
    status = NoveltyRunStatus.RUNNING if consumed else NoveltyRunStatus.NO_PRIOR_ART_RUNS
    return NoveltyDifferentiationRun(
        nd_run_id=nd,
        research_run_id=research_run.research_run_id,
        status=status,
        versions=NoveltyRunVersions(model_provider=provider_name, model_name=model_name),
        bounds=bounds,
        patent_run_id=consumed[CandidateType.PATENT].patent_run_id if CandidateType.PATENT in consumed else None,
        product_run_id=consumed[CandidateType.PRODUCT].product_run_id if CandidateType.PRODUCT in consumed else None,
        oss_run_id=consumed[CandidateType.OPEN_SOURCE].oss_run_id if CandidateType.OPEN_SOURCE in consumed else None,
        sufficiency_run_id=sufficiency.sufficiency_run_id if sufficiency else None,
        upstream_search_partial=partial,
        errors=errors,
        started_at=started_at,
        completed_at=started_at if not consumed else None,
    )


def claims_stage(run: NoveltyDifferentiationRun, claims: list[ClaimRecord]) -> NoveltyDifferentiationRun:
    if STAGE_CLAIMS in run.stage_markers or run.is_terminal:
        return run
    seen: set[str] = set()
    inputs: list[ClaimInput] = []
    for claim in sorted(claims, key=lambda c: c.claim_id):
        if claim.claim_id in seen:
            continue
        seen.add(claim.claim_id)
        status = (
            ClaimEligibilityStatus.ELIGIBLE if is_material_text(claim.claim)
            else ClaimEligibilityStatus.INELIGIBLE_EMPTY_TEXT
        )
        inputs.append(ClaimInput(claim_id=claim.claim_id, claim_text_hash=claim_text_digest(claim.claim), status=status))
    return _evolve(run, claim_inputs=inputs, stage_markers=_marked(run, STAGE_CLAIMS))


def _eligible_claims(run: NoveltyDifferentiationRun, claims: list[ClaimRecord]) -> list[ClaimRecord]:
    eligible = {c.claim_id for c in run.claim_inputs if c.status is ClaimEligibilityStatus.ELIGIBLE}
    by_id: dict[str, ClaimRecord] = {}
    for claim in claims:
        if claim.claim_id in eligible and claim.claim_id not in by_id:
            by_id[claim.claim_id] = claim
    return [by_id[k] for k in sorted(by_id)]


def inventory_stage(
    run: NoveltyDifferentiationRun, research_run: ResearchRun, claims: list[ClaimRecord],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> NoveltyDifferentiationRun:
    if STAGE_INVENTORY in run.stage_markers or run.is_terminal:
        return run
    sufficiency = research_run.claim_sufficiency
    existing = {i.claim_id for i in run.inventories}
    inventories = list(run.inventories)
    errors = list(run.errors)
    for claim in _eligible_claims(run, claims):
        if claim.claim_id in existing:
            continue
        assessment = sufficiency.assessment_for(claim.claim_id) if sufficiency else None
        outcome = build_inventory(
            run.nd_run_id, run.research_run_id, claim,
            assessment.component_inventory if assessment else None, provider, llm_settings, run.bounds,
        )
        if outcome.model_failed or outcome.schema_error:
            errors.append(_issue(
                NoveltyIssueCode.MODEL_SCHEMA_ERROR if outcome.schema_error else NoveltyIssueCode.MODEL_ERROR,
                STAGE_INVENTORY, "feature extraction failed; full-claim fallback used", claim_id=claim.claim_id,
            ))
        inventories.append(outcome.inventory)
    if provider is None and not any(e.code is NoveltyIssueCode.MODEL_PROVIDER_MISSING for e in errors):
        errors.append(_issue(NoveltyIssueCode.MODEL_PROVIDER_MISSING, STAGE_INVENTORY,
                             "no structured model provider; nothing is compared"))
    status = run.status
    if not inventories and status is NoveltyRunStatus.RUNNING:
        status = NoveltyRunStatus.NO_ELIGIBLE_CLAIMS
    return _evolve(run, inventories=sorted(inventories, key=lambda i: i.claim_id), errors=errors,
                   status=status, stage_markers=_marked(run, STAGE_INVENTORY))


def profiles_stage(run: NoveltyDifferentiationRun, research_run: ResearchRun) -> NoveltyDifferentiationRun:
    if STAGE_PROFILES in run.stage_markers or run.is_terminal:
        return run
    known = {c.claim_id for c in run.claim_inputs if c.status is ClaimEligibilityStatus.ELIGIBLE}
    profiles = build_profiles(
        run.nd_run_id, research_run, known, run.bounds.max_texts_per_candidate,
        patent=run.patent_run_id is not None, product=run.product_run_id is not None,
        oss=run.oss_run_id is not None,
    )
    errors = list(run.errors)
    for profile in profiles:
        e = profile.eligibility.value
        if e == "INVALID_CANDIDATE_REFERENCE":
            errors.append(_issue(NoveltyIssueCode.INVALID_REFERENCE, STAGE_PROFILES,
                                 "candidate references unresolved records", candidate_id=profile.candidate_ref.candidate_id))
        elif e == "BLOCKED_SOURCE_QUALITY":
            errors.append(_issue(NoveltyIssueCode.SOURCE_QUALITY_BLOCKED, STAGE_PROFILES,
                                 "candidate blocked by source quality", candidate_id=profile.candidate_ref.candidate_id))
        elif e in ("CONTENT_UNAVAILABLE", "METADATA_ONLY_NOT_COMPARABLE"):
            errors.append(_issue(NoveltyIssueCode.SOURCE_CONTENT_UNAVAILABLE, STAGE_PROFILES,
                                 f"candidate not comparable: {e}", candidate_id=profile.candidate_ref.candidate_id))
    inputs = [
        c.model_copy(update={"linked_candidate_count": sum(1 for p in profiles if c.claim_id in p.linked_claim_ids)})
        for c in run.claim_inputs
    ]
    return _evolve(run, candidate_profiles=profiles, claim_inputs=inputs, errors=errors,
                   stage_markers=_marked(run, STAGE_PROFILES))


def _group_limit(bounds: NoveltyComparisonBounds, candidate_type: CandidateType) -> int:
    return {
        CandidateType.PATENT: bounds.max_patent_groups_per_claim,
        CandidateType.PRODUCT: bounds.max_product_groups_per_claim,
        CandidateType.OPEN_SOURCE: bounds.max_oss_networks_per_claim,
    }[candidate_type]


def select_for_claim(
    profiles: list[CandidateComparisonProfile], bounds: NoveltyComparisonBounds
) -> tuple[list[CandidateComparisonProfile], list[CandidateComparisonProfile]]:
    """Deterministic, type-diverse selection under the configured bounds.

    ``profiles`` are already in canonical order. Returns (selected, omitted).
    """
    per_type: dict[CandidateType, list[CandidateComparisonProfile]] = {t: [] for t in CANDIDATE_TYPE_ORDER}
    omitted: list[CandidateComparisonProfile] = []
    for candidate_type in CANDIDATE_TYPE_ORDER:
        mine = [p for p in profiles if p.candidate_ref.candidate_type is candidate_type]
        units: list[str] = []
        for profile in mine:
            key = profile.independence_unit.unit_key
            if key not in units:
                units.append(key)
        allowed = set(units[: _group_limit(bounds, candidate_type)])
        for profile in mine:
            (per_type[candidate_type] if profile.independence_unit.unit_key in allowed else omitted).append(profile)
    interleaved: list[CandidateComparisonProfile] = []
    depth = max((len(v) for v in per_type.values()), default=0)
    for index in range(depth):
        for candidate_type in CANDIDATE_TYPE_ORDER:
            if index < len(per_type[candidate_type]):
                interleaved.append(per_type[candidate_type][index])
    selected = interleaved[: bounds.max_candidates_per_claim]
    omitted.extend(interleaved[bounds.max_candidates_per_claim:])
    return selected, omitted


def compare_stage(
    run: NoveltyDifferentiationRun, research_run: ResearchRun, claims: list[ClaimRecord],
    provider: StructuredModelProvider | None, llm_settings: LLMSettings | None,
) -> NoveltyDifferentiationRun:
    if STAGE_COMPARE in run.stage_markers or run.is_terminal:
        return run
    claims_by_id = {c.claim_id: c for c in _eligible_claims(run, claims)}
    comparisons: dict[UUID, ClaimCandidateComparison] = {c.comparison_id: c for c in run.comparisons}
    performed = run.model_comparisons_performed
    errors = list(run.errors)
    nd, rid = run.nd_run_id, run.research_run_id
    all_texts: dict[UUID, list[str]] = {
        p.profile_id: [t for t in (resolve_text(research_run, m) for m in p.texts) if t]
        for p in run.candidate_profiles
    }
    limit_reported = False

    def put(comparison: ClaimCandidateComparison) -> None:
        comparisons.setdefault(comparison.comparison_id, comparison)

    for inventory in sorted(run.inventories, key=lambda i: i.claim_id):
        claim = claims_by_id.get(inventory.claim_id)
        if claim is None:
            continue
        linked = [p for p in run.candidate_profiles if inventory.claim_id in p.linked_claim_ids]
        comparable = [p for p in linked if p.eligibility in COMPARABLE_ELIGIBILITY]
        for profile in linked:
            if profile.eligibility not in COMPARABLE_ELIGIBILITY:
                put(unexecuted(nd, rid, inventory, profile, ComparisonStatus.NOT_COMPARED_INELIGIBLE,
                               profile.eligibility.value))
        selected, omitted = select_for_claim(comparable, run.bounds)
        for profile in omitted:
            put(unexecuted(nd, rid, inventory, profile, ComparisonStatus.OMITTED_BY_LIMIT,
                           "per-claim comparison bound reached"))
        for profile in selected:
            existing_id = next(
                (cid for cid, c in comparisons.items()
                 if c.claim_id == inventory.claim_id and c.candidate_ref == profile.candidate_ref), None)
            if existing_id is not None:
                continue
            if provider is None:
                put(unexecuted(nd, rid, inventory, profile, ComparisonStatus.NOT_EXECUTED_NO_PROVIDER,
                               "no structured model provider"))
                continue
            if performed >= run.bounds.max_model_comparisons:
                put(unexecuted(nd, rid, inventory, profile, ComparisonStatus.OMITTED_BY_LIMIT,
                               "run-wide model comparison bound reached"))
                if not limit_reported:
                    errors.append(_issue(NoveltyIssueCode.COMPARISON_LIMIT_REACHED, STAGE_COMPARE,
                                         "run-wide model comparison bound reached"))
                    limit_reported = True
                continue
            foreign = ForeignTexts(
                claim_text=claim.claim,
                other_candidate_texts=[t for pid, texts in all_texts.items() if pid != profile.profile_id for t in texts],
            )
            outcome = compare_pair(
                nd_run_id=nd, research_run=research_run, inventory=inventory, profile=profile,
                provider=provider, llm_settings=llm_settings, bounds=run.bounds, foreign=foreign,
            )
            performed += 1
            comparison = outcome.comparison
            if comparison.status is ComparisonStatus.FAILED_MODEL_ERROR:
                errors.append(_issue(NoveltyIssueCode.MODEL_ERROR, STAGE_COMPARE, comparison.issue_detail or "model error",
                                     claim_id=inventory.claim_id, candidate_id=profile.candidate_ref.candidate_id))
            elif comparison.status is ComparisonStatus.FAILED_SCHEMA_ERROR:
                errors.append(_issue(NoveltyIssueCode.MODEL_SCHEMA_ERROR, STAGE_COMPARE,
                                     comparison.issue_detail or "schema error",
                                     claim_id=inventory.claim_id, candidate_id=profile.candidate_ref.candidate_id))
            if outcome.fabricated_anchor_count:
                errors.append(_issue(NoveltyIssueCode.FABRICATED_ANCHOR, STAGE_COMPARE,
                                     f"{outcome.fabricated_anchor_count} unverifiable excerpt(s) rejected",
                                     claim_id=inventory.claim_id, candidate_id=profile.candidate_ref.candidate_id))
            put(comparison)
    ordered = sorted(comparisons.values(), key=lambda c: (c.claim_id, str(c.comparison_id)))
    return _evolve(run, comparisons=ordered, model_comparisons_performed=performed, errors=errors,
                   stage_markers=_marked(run, STAGE_COMPARE))


def synthesis_stage(run: NoveltyDifferentiationRun) -> NoveltyDifferentiationRun:
    if STAGE_SYNTHESIS in run.stage_markers or run.is_terminal:
        return run
    profiles = {p.profile_id: p for p in run.candidate_profiles}
    syntheses = [
        synthesize_claim(
            run.nd_run_id, run.research_run_id, inventory, run.comparisons_for(inventory.claim_id), profiles,
            upstream_search_partial=bool(run.upstream_search_partial),
        )
        for inventory in sorted(run.inventories, key=lambda i: i.claim_id)
    ]
    return _evolve(run, claim_syntheses=syntheses, stage_markers=_marked(run, STAGE_SYNTHESIS))


def project_stage(run: NoveltyDifferentiationRun) -> NoveltyDifferentiationRun:
    if STAGE_PROJECT in run.stage_markers or run.is_terminal:
        return run
    summary = synthesize_project(run.nd_run_id, run.claim_syntheses, run.comparisons)
    return _evolve(run, project_summary=summary, stage_markers=_marked(run, STAGE_PROJECT))


def finalize_stage(run: NoveltyDifferentiationRun, completed_at: datetime) -> NoveltyDifferentiationRun:
    if run.is_terminal:
        return run
    status = NoveltyRunStatus.COMPLETED if run.status is NoveltyRunStatus.RUNNING else run.status
    return _evolve(run, status=status, completed_at=max(completed_at, run.started_at))


__all__ = [
    "STAGE_CLAIMS",
    "STAGE_COMPARE",
    "STAGE_INVENTORY",
    "STAGE_PROFILES",
    "STAGE_PROJECT",
    "STAGE_SYNTHESIS",
    "claims_stage",
    "compare_stage",
    "finalize_stage",
    "inventory_stage",
    "nd_run_id_for",
    "open_novelty_run",
    "profiles_stage",
    "project_stage",
    "select_for_claim",
    "synthesis_stage",
]
