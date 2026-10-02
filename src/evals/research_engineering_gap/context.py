"""Evaluation context for one Phase 2J Gold case, and the INDEPENDENT recomputation
helpers the scorer uses.

Everything here reads the serialized run (a plain JSON dict) and the upstream
records. It never calls the Phase 2J validators or its derive functions: each
rule below is re-implemented from the policy text, so a defect in production
cannot hide behind itself (the 2E-2I eval convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable

from src.evals.research_engineering_gap.dataset import GapGoldCase
from src.graph.workflow_state import EvaluationGraphState
from src.schemas.research import ResearchRun

ABSENCE_BASES = (
    "FEATURE_ABSENT", "NOT_MENTIONED", "NO_MATCH_FOUND", "TITLE_ONLY_DIFFERENCE", "STUDENT_ASSERTION_ONLY",
    "MARKETPLACE_ABSENCE_ONLY", "LANGUAGE_ABSENCE_ONLY", "FUTURE_WORK_ONLY", "DIFFERENTIATION_ONLY",
    "NO_OVERLAP_FOUND_ONLY",
)
LIMITATION_TYPES = (
    "EXPLICIT_LIMITATION", "MEASURED_SHORTFALL", "SCOPE_RESTRICTION", "UNMET_REQUIREMENT",
    "REPORTED_FAILURE_MODE", "TRADEOFF", "UNRESOLVED_QUESTION",
)
RESEARCH_TYPES = {"UNRESOLVED_QUESTION", "SCOPE_RESTRICTION", "EXPLICIT_LIMITATION"}
ENGINEERING_TYPES = {"MEASURED_SHORTFALL", "UNMET_REQUIREMENT", "REPORTED_FAILURE_MODE", "TRADEOFF",
                     "EXPLICIT_LIMITATION", "SCOPE_RESTRICTION"}
RELATIONS = ("ADDRESSES_LIMITATION", "PARTIALLY_ADDRESSES_LIMITATION", "RELEVANT_BUT_NOT_ADDRESSING", "UNRELATED",
             "INSUFFICIENT_LINKAGE_EVIDENCE")
MATERIAL_RELATIONS = {"ADDRESSES_LIMITATION", "PARTIALLY_ADDRESSES_LIMITATION"}
DIFFERENTIATING = {"NOT_FOUND_IN_COMPARED_CANDIDATE_TEXT", "PARTIALLY_DISCLOSED"}
TITLE_KINDS = {"PATENT_TITLE", "PRODUCT_PAGE_TITLE"}
REPO_METADATA_KINDS = {"OSS_DESCRIPTION", "OSS_TOPICS", "OSS_RELEASE_METADATA"}
INELIGIBLE_KINDS = TITLE_KINDS | REPO_METADATA_KINDS | {"OSS_MANIFEST"}
FORBIDDEN_KEYS = {
    "score": {"score", "scores", "project_score", "readiness", "readiness_score", "rank", "ranking", "probability",
              "confidence", "support_index", "contradiction_index", "novelty_score"},
    "legal": {"legal_novelty", "novelty", "novel", "patentable", "patentability", "anticipated", "verdict",
              "infringement", "methodology_valid", "result_valid"},
}
FORBIDDEN_VALUES = {"NOVEL", "NOT_NOVEL", "ANTICIPATED", "PATENTABLE", "UNPATENTABLE", "GAP_ESTABLISHED", "NO_GAP",
                    "FIELD_WIDE_GAP"}
ALLOWED_STRING_FIELDS = {
    "excerpt", "text", "text_hash", "independence_key", "correlation_group_key", "language", "verifier_version",
    "policy_version", "statement_qualifier", "qualifier", "claim_id", "claim_text_hash", "feature_text_hash",
    "message", "node", "safe_summary", "reason", "code", "upstream_basis", "chronology_basis", "fingerprint",
    "model_provider", "model_name", "contract_version", "anchor_verifier_version", "synthesis_policy_version",
    "candidate_prompt_version", "linkage_prompt_version", "counterevidence_prompt_version", "stage_markers",
    "started_at", "completed_at", "status",
}


def walk(value: Any):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from walk(v)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Ctx:
    case: GapGoldCase
    before: EvaluationGraphState
    after: EvaluationGraphState
    run: ResearchRun
    prior: ResearchRun
    d: dict[str, Any]
    claims: dict[str, str]
    model: Any
    provider: Any
    replay: dict[str, Any] = field(default_factory=dict)
    twins: dict[str, Any] = field(default_factory=dict)
    mutated: dict[str, Any] = field(default_factory=dict)
    controls: dict[str, tuple[int, int]] = field(default_factory=dict)
    nd: dict[str, Any] = field(default_factory=dict)
    nd_before: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        d = self.d
        self.hyps = {h["claim_id"]: h for h in d["hypotheses"]}
        self.assess = {a["claim_id"]: a for a in d["claim_assessments"]}
        self.inv = {(t["source_kind"], t["source_record_id"]): t for t in d["inventory_texts"]}
        self.coverage = {c["claim_id"]: c for c in d["counterevidence_coverage"]}
        self.nd = self.nd or (self.run.novelty_differentiation.model_dump(mode="json")
                              if self.run.novelty_differentiation else {})
        self.nd_inventory = {i["claim_id"]: i for i in self.nd.get("inventories", [])}
        self.nd_synthesis = {s["claim_id"]: s for s in self.nd.get("claim_syntheses", [])}
        self.nd_texts = {t["text_ref_id"]: t for p in self.nd.get("candidate_profiles", []) for t in p["texts"]}
        self.nd_profiles = {p["profile_id"]: p for p in self.nd.get("candidate_profiles", [])}

    def clone(self, **changes: Any) -> "Ctx":
        """A copy with some inputs replaced; the indexes are rebuilt from them."""
        from dataclasses import fields

        return Ctx(**{**{f.name: getattr(self, f.name) for f in fields(self)}, **changes})

    # -- upstream text, read from the records the texts came from -------------

    def src_text(self, kind: str, rid: str) -> str | None:
        r = self.run
        if kind == "PATENT_TEXT_SNAPSHOT" and r.patent_prior_art:
            return next((s.text for s in r.patent_prior_art.snapshots if str(s.snapshot_id) == rid), None)
        if kind == "PATENT_CANDIDATE_FIELD" and r.patent_prior_art:
            return next((c.title for c in r.patent_prior_art.candidates if str(c.candidate_id) == rid), None)
        if kind == "PRODUCT_SOURCE_ARTIFACT" and r.product_prior_art:
            return next((a.text_snapshot for a in r.product_prior_art.artifacts if str(a.artifact_id) == rid), None)
        if kind == "PRODUCT_ARTIFACT_FIELD" and r.product_prior_art:
            return next((a.title for a in r.product_prior_art.artifacts if str(a.artifact_id) == rid), None)
        if kind == "REPOSITORY_SNAPSHOT" and r.open_source_prior_art:
            return next((s.text for s in r.open_source_prior_art.snapshots if str(s.snapshot_id) == rid), None)
        return None

    def body(self, inv: dict[str, Any]) -> str | None:
        """The exact string an inventory text's offsets index into."""
        if inv["source_kind"] == "ACADEMIC_EVIDENCE":
            ex = self.run.evidence_extraction
            if ex is None:
                return None
            evidence = next((e for e in ex.verified_evidence if str(e.evidence_id) == inv["source_record_id"]), None)
            snap = next((s for s in ex.content_snapshots if evidence and s.content_id == evidence.content_id), None)
            return snap.text if snap else None
        meta = self.nd_texts.get(inv["source_record_id"])
        return self.src_text(meta["source_record_kind"], meta["source_record_id"]) if meta else None

    def all_refs(self):
        for h in self.d["hypotheses"]:
            for r in h["evidence_refs"]:
                yield h, r

    def refs_by_id(self, h: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {r["evidence_ref_id"]: r for r in h["evidence_refs"]}

    def lim_refs(self, h: dict[str, Any], lim: dict[str, Any]) -> list[dict[str, Any]]:
        by = self.refs_by_id(h)
        return [by[i] for i in lim["evidence_ref_ids"] if i in by]

    # -- scripted proposals: an independent ledger of what the model tried ----

    def proposals(self, cid: str, kind: str) -> list[dict[str, Any]]:
        script = self.case.script
        if kind == "limitations":
            spec = script.get("extract", {}).get(cid)
            return list(spec.get("limitations", [])) if isinstance(spec, dict) else []
        if kind == "capabilities":
            spec = script.get("extract", {}).get(cid)
            return list(spec.get("capabilities", [])) if isinstance(spec, dict) else []
        if kind == "conditions":
            return [c for lim in self.proposals(cid, "limitations") for c in lim.get("conditions", [])]
        if kind == "links":
            spec = script.get("link", {}).get(cid)
            return list(spec) if isinstance(spec, list) else []
        if kind == "counter":
            spec = script.get("counter", {}).get(cid)
            return list(spec) if isinstance(spec, list) else []
        raise KeyError(kind)

    def all_bodies(self) -> list[str]:
        return [b for b in (self.body(i) for i in self.inv.values()) if b]

    def shown_claim_ids(self) -> list[str]:
        return list(self.claims)


# ---------------------------------------------------------------------------
# Independent recomputation (policy text, not production code)
# ---------------------------------------------------------------------------


def link_is_material(link: dict[str, Any]) -> bool:
    return link["inherited_differentiation_status"] in DIFFERENTIATING and link["relation"] in MATERIAL_RELATIONS


def eligible_limitations(ctx: Ctx, h: dict[str, Any]) -> list[dict[str, Any]]:
    return [lim for lim in h["limitations"] if any(r["source_quality"] == "ELIGIBLE" for r in ctx.lim_refs(h, lim))]


def recompute_linkage(ctx: Ctx, h: dict[str, Any]) -> str:
    ids = {lim["limitation_id"] for lim in eligible_limitations(ctx, h)}
    material = [lk for lk in h["project_links"] if link_is_material(lk) and lk["limitation_id"] in ids]
    if any(lk["relation"] == "ADDRESSES_LIMITATION" for lk in material):
        return "FULL"
    return "PARTIAL" if material else "NONE_MATERIAL"


def recompute_existence(ctx: Ctx, h: dict[str, Any]) -> str:
    if eligible_limitations(ctx, h):
        return "LIMITATION_SUPPORTED"
    return "LIMITATION_BLOCKED_SOURCE_QUALITY" if h["limitations"] else "NO_ELIGIBLE_LIMITATION"


def narrowed(h: dict[str, Any]) -> bool:
    return any(c["condition_match"] == "DIFFERENT_CONDITION" for c in h["counterevidence"])


def recompute_materiality(ctx: Ctx, h: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for lim in eligible_limitations(ctx, h):
        bound = {c["dimension"] for c in h["conditions"] if lim["limitation_id"] in c["limitation_ids"]}
        dims = set(lim["condition_dimensions"])
        if dims:
            out[lim["limitation_id"]] = "CONDITION_REQUIRED_AND_BOUND" if dims <= bound else \
                "CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"
        elif narrowed(h):
            out[lim["limitation_id"]] = "CONDITION_REQUIRED_AND_BOUND" if bound else \
                "CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"
        else:
            out[lim["limitation_id"]] = "CONDITION_NOT_MATERIAL"
    return out


def linked_limitations(ctx: Ctx, h: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {lk["limitation_id"] for lk in h["project_links"] if link_is_material(lk)}
    return [lim for lim in eligible_limitations(ctx, h) if lim["limitation_id"] in ids]


def units_of(ctx: Ctx, refs: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Independent corroboration units over eligible limitation excerpts."""
    units: set[tuple[str, str]] = set()
    for r in refs:
        if not r["counts_as_independent"]:
            continue
        units.add(("corr", r["correlation_group_key"]) if r["correlation_group_key"]
                  else (r["source_kind"], r["independence_key"]))
    return units


def recompute_corroboration(ctx: Ctx, h: dict[str, Any]) -> str:
    refs = [r for lim in eligible_limitations(ctx, h) for r in ctx.lim_refs(h, lim) if r["source_quality"] == "ELIGIBLE"]
    if not refs:
        return "NO_DIRECT_SUPPORT"
    units = units_of(ctx, refs)
    if not units:
        return "UNRESOLVED_INDEPENDENCE"
    if len(units) == 1:
        return "SINGLE_SOURCE_DIRECT"
    kinds = {k for k, _ in units if k != "corr"} | ({"PRIOR_ART_TEXT"} if any(k == "corr" for k, _ in units) else set())
    return "MIXED_SOURCE_CORROBORATED" if len(kinds) > 1 else "MULTI_SOURCE_CORROBORATED"


def recompute_kind(ctx: Ctx, h: dict[str, Any]) -> str:
    linked = linked_limitations(ctx, h)
    research = {lim["limitation_id"] for lim in linked if lim["facet"] == "RESEARCH"}
    engineering = {lim["limitation_id"] for lim in linked if lim["facet"] == "ENGINEERING"}
    if research and engineering:
        return "HYBRID" if any(r != e for r in research for e in engineering) and not research & engineering \
            else "UNRESOLVED"
    return "RESEARCH" if research else "ENGINEERING" if engineering else "UNRESOLVED"


def recompute_missing(ctx: Ctx, h: dict[str, Any]) -> set[str]:
    missing: set[str] = set()
    if not h["existing_capabilities"]:
        missing.add("EXISTING_CAPABILITY")
    mat = recompute_materiality(ctx, h)
    if any(mat.get(lim["limitation_id"]) == "CONDITION_REQUIRED_BUT_MISSING_OR_UNRESOLVED"
           for lim in linked_limitations(ctx, h)):
        missing.add("MATERIAL_CONDITION")
    if recompute_linkage(ctx, h) != "FULL":
        missing.add("FULL_PROJECT_LINKAGE")
    if h["validation_requirement"] is None:
        missing.add("VALIDATION_REQUIREMENT")
    if recompute_kind(ctx, h) == "UNRESOLVED":
        missing.add("RESOLVED_GAP_KIND")
    if not h["counterevidence_review_complete"]:
        missing.add("COMPLETE_COUNTEREVIDENCE_REVIEW")
    return missing


def material_counter(h: dict[str, Any]) -> bool:
    return any(c["condition_match"] != "DIFFERENT_CONDITION" for c in h["counterevidence"])


def recompute_posture(ctx: Ctx, h: dict[str, Any]) -> str:
    existence = recompute_existence(ctx, h)
    if existence == "LIMITATION_BLOCKED_SOURCE_QUALITY":
        return "BLOCKED_SOURCE_QUALITY"
    if existence == "NO_ELIGIBLE_LIMITATION" or recompute_linkage(ctx, h) == "NONE_MATERIAL":
        return "NOT_ESTABLISHED_WITHIN_BOUNDS"
    if material_counter(h):
        return "COUNTEREVIDENCE_WEAKENS_GAP"
    return "PARTIALLY_SUPPORTED" if recompute_missing(ctx, h) else "SUPPORTED_WITHIN_BOUNDS"


def recompute_scope_effect(h: dict[str, Any]) -> str:
    if any(c["condition_match"] == "CONDITION_UNKNOWN" for c in h["counterevidence"]):
        return "CONDITION_RELATION_UNRESOLVED"
    return "NARROWED_BY_DIFFERENT_CONDITION" if narrowed(h) else "NO_SCOPE_NARROWING"


def claim_posture(ctx: Ctx, cid: str) -> str:
    a = ctx.assess[cid]
    if not a["inputs_bound"]:
        return "INSUFFICIENT_INPUT"
    h = ctx.hyps.get(cid)
    posture = recompute_posture(ctx, h) if h else None
    order = ["SUPPORTED_WITHIN_BOUNDS", "PARTIALLY_SUPPORTED", "COUNTEREVIDENCE_WEAKENS_GAP", "BLOCKED_SOURCE_QUALITY"]
    if posture in order:
        return posture
    return "DIFFERENTIATION_WITHOUT_DEFENSIBLE_GAP" if a["has_differentiating_feature"] else \
        "NOT_ESTABLISHED_WITHIN_BOUNDS"


def prompt_lines() -> list[str]:
    from src.llm.prompts import (
        GAP_CANDIDATE_EXTRACTION_PROMPT_V1,
        GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1,
        GAP_PROJECT_LINKAGE_PROMPT_V1,
    )

    prompts = (GAP_CANDIDATE_EXTRACTION_PROMPT_V1, GAP_PROJECT_LINKAGE_PROMPT_V1, GAP_COUNTEREVIDENCE_REVIEW_PROMPT_V1)
    return [ln.strip() for p in prompts for ln in p.splitlines() if len(ln.strip()) >= 40]


def strip_times(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: strip_times(v) for k, v in d.items() if k not in ("started_at", "completed_at")}
    if isinstance(d, list):
        return [strip_times(v) for v in d]
    return d


GateFn = Callable[["Ctx"], tuple[int, int]]
