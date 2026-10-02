"""Phase 2I Gold eval runner.

Each case builds a populated world through the REAL Phase 2E, 2F, 2G and 2H
graphs, then runs the REAL Phase 2I graph against a scripted structured model.

The scorer is independent of the code it scores. Every release-blocking gate is
re-derived from the serialized Phase 2I run (a plain JSON dict -- never through
the Phase 2I validators or helpers) and from the upstream Phase 2G/2H records,
so a validator that wrongly accepts something cannot hide from the gate that
checks it. Negative controls tamper that same JSON and require either the
gate to fire or the contract to refuse it.
"""

from __future__ import annotations

import copy
import json
import traceback
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from src.evals.novelty_differentiation.dataset import NoveltyGoldCase
from src.evals.novelty_differentiation.world import ScriptedNoveltyModel, build_upstream, run_phase2i
from src.graph.workflow_state import EvaluationGraphState
from src.llm.prompts import PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1, NOVELTY_FEATURE_EXTRACTION_PROMPT_V1
from src.schemas.novelty_differentiation import NoveltyComparisonBounds, NoveltyDifferentiationRun
from src.schemas.research import ResearchRun

# ---------------------------------------------------------------------------
# Independent policy tables (re-stated from the policy text, not imported)
# ---------------------------------------------------------------------------

RANK = {"NON_MATERIAL": 0, "LIMITED": 1, "MATERIAL": 2}
REL_STRENGTH = {"RELATED_CONTEXT": 1, "PARTIALLY_DISCLOSED": 2, "DISCLOSED": 3}
CEILING = {"NON_MATERIAL": "RELATED_CONTEXT", "LIMITED": "PARTIALLY_DISCLOSED", "MATERIAL": "DISCLOSED"}
ANCHORED = {"DISCLOSED", "PARTIALLY_DISCLOSED", "RELATED_CONTEXT"}
OVERLAP = {"DISCLOSED", "PARTIALLY_DISCLOSED"}
OVERLAPPING = {"FULL_CLAIM_TECHNICAL_OVERLAP", "PARTIAL_CLAIM_TECHNICAL_OVERLAP", "COMPONENT_ONLY_OVERLAP"}
RELATIONAL = {"RELATIONSHIP", "SEQUENCE", "CONSTRAINT", "COMBINATION"}
TITLE_KINDS = {"PATENT_TITLE", "PRODUCT_PAGE_TITLE"}
OSS_METADATA_KINDS = {"OSS_DESCRIPTION", "OSS_TOPICS", "OSS_RELEASE_METADATA"}
TYPE_PREFIX = {"PATENT": "PATENT_", "PRODUCT": "PRODUCT_", "OPEN_SOURCE": "OSS_"}
TYPES = ("PATENT", "PRODUCT", "OPEN_SOURCE")

FORBIDDEN_VALUES = {
    "novel": {"NOVEL"},
    "not_novel": {"NOT_NOVEL"},
    "patentability": {"PATENTABLE", "UNPATENTABLE"},
    "infringement": {"INFRINGING", "INFRINGES", "FTO_CLEAR", "FREEDOM_TO_OPERATE", "FTO_BLOCKED"},
    "copying": {"COPIED", "PLAGIARIZED", "COPYING_FOUND", "PLAGIARISM_FOUND"},
    "legal": {"ANTICIPATED", "INVALIDATING_PRIOR_ART", "NOVELTY_DESTROYING", "LEGAL_PRIOR_ART", "INVALID"},
    "verdict": {"PASS", "FAIL", "ACCEPT", "REJECT"},
}
FORBIDDEN_KEYS = {
    "score": {"novelty_score", "novelty_percentage", "novelty_grade", "project_score", "score", "grade",
              "novelty_probability", "truth_probability", "percentage", "percent", "rank", "ranking"},
    "similarity": {"similarity", "similarity_score", "overlap_ratio", "probability", "confidence"},
    "rank": {"retrieval_rank", "provider_rank", "rank"},
    "popularity": {"stargazers_count", "forks_count", "watchers_count", "popularity", "stars"},
    "legal": {"anticipation", "legal_conclusion", "legally_novel", "patentable", "infringes"},
}


def walk(value: Any):
    """Yield (key, value) for every dict entry and (None, value) for list items."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from walk(item)


def has_value(d: Any, values: set[str]) -> bool:
    return any(isinstance(v, str) and v in values for _, v in walk(d))


def has_key(d: Any, keys: set[str]) -> bool:
    return any(k in keys for k, _ in walk(d) if k is not None)


def is_material_char(ch: str) -> bool:
    return not ch.isspace() and not unicodedata.category(ch).startswith(("P", "S"))


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    case: NoveltyGoldCase
    before: EvaluationGraphState
    after: EvaluationGraphState
    run: ResearchRun
    prior: ResearchRun
    d: dict[str, Any]
    claims: dict[str, str]
    model: ScriptedNoveltyModel | None
    provider: Any
    replay: dict[str, Any] = field(default_factory=dict)
    controls: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (attempts, accepted)
    synth_fn: Callable | None = None

    # -- upstream indexes (independent of the Phase 2I code) ----------------

    def upstream(self) -> dict[str, tuple[str, Any]]:
        out: dict[str, tuple[str, Any]] = {}
        r = self.run
        for c in (r.patent_prior_art.candidates if r.patent_prior_art else []):
            out[str(c.candidate_id)] = ("PATENT", c)
        for c in (r.product_prior_art.candidates if r.product_prior_art else []):
            out[str(c.candidate_id)] = ("PRODUCT", c)
        for c in (r.open_source_prior_art.candidates if r.open_source_prior_art else []):
            out[str(c.candidate_id)] = ("OPEN_SOURCE", c)
        return out

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

    def owned_record_ids(self, cid: str) -> set[str]:
        kind, cand = self.upstream()[cid]
        if kind == "PATENT":
            return {str(s) for s in cand.snapshot_ids} | {str(cand.candidate_id)}
        if kind == "PRODUCT":
            return {str(a.artifact_id) for a in cand.artifacts}
        return {str(s) for s in cand.snapshot_ids}

    def tag_map(self) -> dict[str, str]:
        """tag -> candidate_id, resolved from upstream records only."""
        out: dict[str, str] = {}
        for tag, value in self.case.tags.items():
            for cid, (kind, cand) in self.upstream().items():
                if kind == "PATENT" and cand.publication_key == value:
                    out[tag] = cid
                elif kind == "PRODUCT" and any(value in a.final_url for a in cand.artifacts):
                    out[tag] = cid
                elif kind == "OPEN_SOURCE" and (cand.full_name == value or value in cand.observed_full_names):
                    out[tag] = cid
        return out

    def comparisons(self) -> list[dict]:
        return self.d["comparisons"]

    def verified(self) -> list[dict]:
        return [c for c in self.d["comparisons"] if c["status"] == "VERIFIED"]

    def profile(self, profile_id: str) -> dict:
        return next(p for p in self.d["candidate_profiles"] if p["profile_id"] == profile_id)

    def inventory(self, inventory_id: str) -> dict:
        return next(i for i in self.d["inventories"] if i["inventory_id"] == inventory_id)

    def bucket(self, cid: str) -> str:
        """Chronology bucket re-derived from the candidate's own upstream dates."""
        kind, cand = self.upstream()[cid]
        r = self.run
        if kind == "PATENT":
            cutoff = r.patent_prior_art.search_cutoff.cutoff_date
            date = cand.dates.first_public_date
        elif kind == "PRODUCT":
            cutoff = r.product_prior_art.search_cutoff.cutoff_date
            date = cand.chronology.date_value
        else:
            cutoff = r.open_source_prior_art.search_cutoff.cutoff_date
            date = cand.chronology.date_value
        if cutoff is None:
            return "NO_CUTOFF"
        if date is None:
            return "DATE_UNKNOWN"
        return "BEFORE_CUTOFF" if date < cutoff else "ON_CUTOFF" if date == cutoff else "AFTER_CUTOFF"

    def independent_units(self, comps: list[dict], candidate_type: str) -> int:
        """Independent corroboration units among ``comps``, from upstream records."""
        up = self.upstream()
        r = self.run
        mine = [c for c in comps if c["candidate_ref"]["candidate_type"] == candidate_type]
        if candidate_type == "PATENT":
            keys = set()
            for c in mine:
                cand = up[c["candidate_ref"]["candidate_id"]][1]
                status = cand.family_status.value
                if status == "VERIFIED_FAMILY" and cand.family_group_id:
                    keys.add(f"F:{cand.family_group_id}")
                elif status == "SINGLETON_FAMILY":
                    keys.add(f"S:{cand.publication_key}")
            return len(keys)
        if candidate_type == "PRODUCT":
            entities = {up[c["candidate_ref"]["candidate_id"]][1].entity_id for c in mine}
            parent = {e.entity_id: e.entity_id for e in r.product_prior_art.entities}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for e in r.product_prior_art.entities:
                for link in e.probable_links:
                    parent[find(e.entity_id)] = find(link.other_entity_id)
            return len({find(e) for e in entities})
        nets = set()
        for c in mine:
            cand = up[c["candidate_ref"]["candidate_id"]][1]
            network = next(n for n in r.open_source_prior_art.networks if n.network_id == cand.network_id)
            if network.independent_root and cand.counts_as_independent_root:
                nets.add(str(cand.network_id))
        return len(nets)


# ---------------------------------------------------------------------------
# Independent capacity ceiling for an anchor
# ---------------------------------------------------------------------------


def indep_capacity(ctx: Ctx, anchor: dict) -> str:
    kind = anchor["text_kind"]
    ftype = anchor["feature_type"]
    r = ctx.run
    if kind in TITLE_KINDS or kind in OSS_METADATA_KINDS:
        return "NON_MATERIAL"
    if kind in ("PATENT_CLAIMS", "PATENT_DESCRIPTION"):
        return "MATERIAL"
    if kind == "PATENT_ABSTRACT":
        return "LIMITED"
    if kind == "PRODUCT_PAGE_TEXT":
        artifact = next((a for a in r.product_prior_art.artifacts if str(a.artifact_id) == anchor["source_record_id"]), None)
        return "MATERIAL" if artifact and artifact.source_role.value == "FIRST_PARTY_DOCUMENTATION" else "LIMITED"
    if kind in ("OSS_README", "OSS_CODE_FRAGMENT"):
        return "LIMITED"
    if kind == "OSS_MANIFEST":
        snap = next((s for s in r.open_source_prior_art.snapshots if str(s.snapshot_id) == anchor["source_record_id"]), None)
        full = bool(snap and snap.is_full_file and not snap.truncated)
        if ftype in ("COMPONENT", "CONSTRAINT"):
            return "MATERIAL" if full else "LIMITED"
        if ftype == "OTHER_TECHNICAL_FEATURE":
            return "LIMITED"
        return "NON_MATERIAL"
    return "NON_MATERIAL"


def complete_material_types(ctx: Ctx, profile: dict, max_chars: int) -> set[str]:
    """Feature types for which complete material text exists, from the profile."""
    types: set[str] = set()
    for text in profile["texts"]:
        if text["truncated_upstream"] or text["char_count"] > max_chars:
            continue
        for ftype in ("COMPONENT", "FUNCTION", "MECHANISM", "RELATIONSHIP", "SEQUENCE", "CONSTRAINT",
                      "COMBINATION", "OTHER_TECHNICAL_FEATURE"):
            probe = {"text_kind": text["text_kind"], "feature_type": ftype, "source_record_id": str(text["source_record_id"])}
            if indep_capacity(ctx, probe) == "MATERIAL":
                types.add(ftype)
    return types


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

GATE_FUNCS: dict[str, Callable[[Ctx], tuple[int, int]]] = {}
GATES: list[str] = []


def gate(name: str):
    def register(fn):
        GATE_FUNCS[name] = fn
        GATES.append(name)
        return fn

    return register


def _eq_dump(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _project_dump(state: EvaluationGraphState) -> str:
    return state.project.model_dump_json()


@gate("project_state_mutation")
def g_project(ctx):
    return (0 if _project_dump(ctx.before) == _project_dump(ctx.after) else 1), 1


@gate("claim_mutation")
def g_claim(ctx):
    old = {c.claim_id: c.claim for c in ctx.before.project.claims}
    new = {c.claim_id: c.claim for c in ctx.after.project.claims}
    return sum(1 for k, v in old.items() if new.get(k) != v) + (len(new) - len(old)), len(old)


def _claim_attr_gate(name: str, attr: Callable[[Any], Any]):
    def fn(ctx):
        old = {c.claim_id: attr(c) for c in ctx.before.project.claims}
        new = {c.claim_id: attr(c) for c in ctx.after.project.claims}
        return sum(1 for k, v in old.items() if new.get(k) != v), len(old)

    gate(name)(fn)


_claim_attr_gate("claim_status_mutation", lambda c: c.status.value)
_claim_attr_gate("claim_confidence_mutation", lambda c: c.confidence)
_claim_attr_gate("evidence_reference_mutation", lambda c: (tuple(c.evidence_ids), tuple(c.counter_evidence_ids)))


@gate("project_score_mutation")
def g_scores(ctx):
    a = ctx.before.project.model_dump(mode="json")["scores"]
    b = ctx.after.project.model_dump(mode="json")["scores"]
    return (0 if _eq_dump(a, b) else 1), 1


@gate("trust_gate_mutation")
def g_trust(ctx):
    a = ctx.before.project.model_dump(mode="json")["trust_gate"]
    b = ctx.after.project.model_dump(mode="json")["trust_gate"]
    return (0 if _eq_dump(a, b) else 1), 1


@gate("evaluation_status_mutation")
def g_status(ctx):
    return (0 if ctx.before.project.evaluation_status == ctx.after.project.evaluation_status else 1), 1


def _subrun_gate(name: str, field_name: str):
    def fn(ctx):
        old, new = getattr(ctx.prior, field_name), getattr(ctx.run, field_name)
        if old is None and new is None:
            return 0, 0
        return (0 if old == new else 1), 1

    gate(name)(fn)


_subrun_gate("phase2c_mutation", "evidence_extraction")
_subrun_gate("phase2d_mutation", "claim_evidence_alignment")
_subrun_gate("phase2e_mutation", "claim_sufficiency")
_subrun_gate("phase2f_mutation", "claim_evidence_scoring")
_subrun_gate("phase2g_mutation", "patent_prior_art")
_subrun_gate("phase2h_product_mutation", "product_prior_art")
_subrun_gate("phase2h_oss_mutation", "open_source_prior_art")


@gate("fabricated_claim_feature_accepted")
def g_fab_feature(ctx):
    v = n = 0
    for inv in ctx.d["inventories"]:
        text = ctx.claims.get(inv["claim_id"])
        for f in inv["features"]:
            n += 1
            if text is None or text[f["start"]:f["end"]] != f["text"]:
                v += 1
    return v, n


@gate("uncovered_material_relationship_ignored")
def g_uncovered(ctx):
    v = n = 0
    for inv in ctx.d["inventories"]:
        if inv["mode"] != "COMPONENT_LEVEL":
            continue
        text = ctx.claims[inv["claim_id"]]
        covered = [False] * len(text)
        for f in inv["features"]:
            if f["feature_type"] != "COMBINATION":
                for i in range(f["start"], min(f["end"], len(text))):
                    covered[i] = True
        n += 1
        if any(not covered[i] and is_material_char(text[i]) for i in range(len(text))):
            v += 1
        elements = [f for f in inv["features"] if f["feature_type"] != "COMBINATION"]
        n += 1
        if len(elements) >= 2 and not any(f["feature_type"] == "COMBINATION" for f in inv["features"]):
            v += 1
    return v, n


def _anchor_ok(ctx: Ctx, a: dict) -> bool:
    text = ctx.src_text(a["source_record_kind"], a["source_record_id"])
    return text is not None and text[a["start"]:a["end"]] == a["excerpt"]


@gate("fabricated_candidate_excerpt_accepted")
def g_fab_excerpt(ctx):
    anchors = [a for c in ctx.comparisons() for a in c["anchors"]]
    return sum(1 for a in anchors if not _anchor_ok(ctx, a)), len(anchors)


@gate("wrong_snapshot_anchor_accepted")
def g_wrong_snapshot(ctx):
    v = n = 0
    up = ctx.upstream()
    for c in ctx.comparisons():
        owned = ctx.owned_record_ids(c["candidate_ref"]["candidate_id"]) if c["candidate_ref"]["candidate_id"] in up else set()
        for a in c["anchors"]:
            n += 1
            if a["source_record_id"] not in owned or a["candidate_ref"]["candidate_id"] != c["candidate_ref"]["candidate_id"]:
                v += 1
    return v, n


@gate("search_snippet_used_as_material_product_disclosure")
def g_snippet(ctx):
    ok_kinds = {"PRODUCT_SOURCE_ARTIFACT", "PRODUCT_ARTIFACT_FIELD"}
    v = n = 0
    for p in ctx.d["candidate_profiles"]:
        if p["candidate_ref"]["candidate_type"] == "PRODUCT":
            for t in p["texts"]:
                n += 1
                if t["source_record_kind"] not in ok_kinds or ctx.src_text(t["source_record_kind"], str(t["source_record_id"])) is None:
                    v += 1
    for c in ctx.comparisons():
        if c["candidate_ref"]["candidate_type"] == "PRODUCT":
            for a in c["anchors"]:
                n += 1
                if a["source_record_kind"] not in ok_kinds:
                    v += 1
    return v, n


def _metadata_gate(name: str, ctype: str, kinds: set[str]):
    def fn(ctx):
        v = n = 0
        for c in ctx.comparisons():
            if c["candidate_ref"]["candidate_type"] != ctype:
                continue
            by_id = {a["anchor_id"]: a for a in c["anchors"]}
            for rec in c["feature_records"]:
                anchors = [by_id[i] for i in rec["anchor_ids"]]
                if not any(a["text_kind"] in kinds for a in anchors):
                    continue
                n += 1
                bad_capacity = any(a["text_kind"] in kinds and a["capacity"] != "NON_MATERIAL" for a in anchors)
                only_metadata = all(a["text_kind"] in kinds for a in anchors)
                if bad_capacity or (only_metadata and rec["relation"] in OVERLAP):
                    v += 1
        return v, n

    gate(name)(fn)


_metadata_gate("patent_title_used_as_material_disclosure", "PATENT", {"PATENT_TITLE"})
_metadata_gate("product_title_used_as_material_disclosure", "PRODUCT", {"PRODUCT_PAGE_TITLE"})
_metadata_gate("oss_metadata_alone_used_as_implementation_proof", "OPEN_SOURCE", OSS_METADATA_KINDS)


def _only_kind_gate(name: str, kind: str, forbid_material: bool):
    def fn(ctx):
        v = n = 0
        for c in ctx.comparisons():
            by_id = {a["anchor_id"]: a for a in c["anchors"]}
            for rec in c["feature_records"]:
                anchors = [by_id[i] for i in rec["anchor_ids"]]
                if not any(a["text_kind"] == kind for a in anchors):
                    continue
                n += 1
                if rec["relation"] == "DISCLOSED" and all(a["text_kind"] == kind for a in anchors):
                    v += 1
                elif forbid_material and any(a["text_kind"] == kind and a["capacity"] == "MATERIAL" for a in anchors):
                    v += 1
        return v, n

    gate(name)(fn)


_only_kind_gate("code_fragment_treated_as_full_file_disclosure", "OSS_CODE_FRAGMENT", True)
_only_kind_gate("readme_treated_as_code_implementation_proof", "OSS_README", True)


@gate("candidate_identity_lost")
def g_identity(ctx):
    up = ctx.upstream()
    v = n = 0
    for c in ctx.comparisons():
        n += 1
        ref = c["candidate_ref"]
        entry = up.get(ref["candidate_id"])
        if entry is None or entry[0] != ref["candidate_type"]:
            v += 1
            continue
        kind, cand = entry
        expected = (
            cand.publication_key if kind == "PATENT"
            else (cand.identity_key or f"entity:{cand.entity_id}") if kind == "PRODUCT"
            else cand.repository_key
        )
        if ref["identity_key"] != expected:
            v += 1
    return v, n


@gate("patent_family_inflated_count")
def g_family(ctx):
    v = n = 0
    up = ctx.upstream()
    for c in ctx.comparisons():
        if c["candidate_ref"]["candidate_type"] != "PATENT" or c["status"] != "VERIFIED":
            continue
        n += 1
        cand = up[c["candidate_ref"]["candidate_id"]][1]
        resolved = cand.family_status.value in ("VERIFIED_FAMILY", "SINGLETON_FAMILY")
        if c["independence_unit"]["counts_as_independent"] and not resolved:
            v += 1
    for s in ctx.d["claim_syntheses"]:
        mine = [c for c in ctx.comparisons() if c["claim_id"] == s["claim_id"] and c["status"] == "VERIFIED"]
        if not any(c["candidate_ref"]["candidate_type"] == "PATENT" for c in mine):
            continue
        n += 1
        full = [c for c in mine if c["full_claim_relation"] == "FULL_CLAIM_TECHNICAL_OVERLAP"]
        if s["type_summaries"][0]["full_overlap_independent_units"] > ctx.independent_units(full, "PATENT"):
            v += 1
    return v, n


@gate("product_listing_inflated_count")
def g_product(ctx):
    v = n = 0
    up = ctx.upstream()
    products = [c for c in ctx.comparisons() if c["candidate_ref"]["candidate_type"] == "PRODUCT"]
    by_unit: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in products:
        by_unit[(c["claim_id"], c["independence_unit"]["unit_key"])].add(up[c["candidate_ref"]["candidate_id"]][1].entity_id.__str__())
    for c in products:
        n += 1
        if len(by_unit[(c["claim_id"], c["independence_unit"]["unit_key"])]) > 1:
            v += 1  # separate Phase 2H entities merged into one Phase 2I unit
    for s in ctx.d["claim_syntheses"]:
        mine = [c for c in products if c["claim_id"] == s["claim_id"] and c["status"] == "VERIFIED"]
        if not mine:
            continue
        n += 1
        full = [c for c in mine if c["full_claim_relation"] == "FULL_CLAIM_TECHNICAL_OVERLAP"]
        if s["type_summaries"][1]["full_overlap_independent_units"] > ctx.independent_units(full, "PRODUCT"):
            v += 1
    return v, n


def _fork_gate(name: str, relations: set[str]):
    def fn(ctx):
        v = n = 0
        up = ctx.upstream()
        for c in ctx.comparisons():
            if c["candidate_ref"]["candidate_type"] != "OPEN_SOURCE":
                continue
            cand = up[c["candidate_ref"]["candidate_id"]][1]
            if cand.relationship.value not in relations:
                continue
            n += 1
            if c["independence_unit"]["counts_as_independent"]:
                v += 1
        if "FORK" in relations:
            for s in ctx.d["claim_syntheses"]:
                mine = [c for c in ctx.comparisons() if c["claim_id"] == s["claim_id"] and c["status"] == "VERIFIED"
                        and c["candidate_ref"]["candidate_type"] == "OPEN_SOURCE"]
                if not mine:
                    continue
                n += 1
                full = [c for c in mine if c["full_claim_relation"] == "FULL_CLAIM_TECHNICAL_OVERLAP"]
                if s["type_summaries"][2]["full_overlap_independent_units"] > ctx.independent_units(full, "OPEN_SOURCE"):
                    v += 1
        return v, n

    gate(name)(fn)


_fork_gate("fork_inflated_count", {"FORK", "TEMPLATE_DERIVATIVE"})
_fork_gate("mirror_inflated_count", {"MIRROR"})


@gate("cross_candidate_mosaic_reported_single_candidate_full_overlap")
def g_mosaic(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        mine = [c for c in ctx.verified() if c["claim_id"] == s["claim_id"]]
        if len(mine) < 2:
            continue
        n += 1
        single_full = any(all(r["relation"] == "DISCLOSED" for r in c["feature_records"]) for c in mine)
        if s["posture"] == "MATERIAL_TECHNICAL_OVERLAP_FOUND" and not single_full:
            v += 1
    return v, n


@gate("all_components_without_relationship_reported_full_overlap")
def g_components_only(ctx):
    v = n = 0
    for c in ctx.verified():
        if all(r["relation"] == "DISCLOSED" for r in c["feature_records"]):
            continue
        n += 1
        if c["full_claim_relation"] == "FULL_CLAIM_TECHNICAL_OVERLAP":
            v += 1
    return v, n


def _proposal_gate(name: str, category: str):
    def fn(ctx):
        if category not in ctx.case.categories:
            return 0, 0
        v = n = 0
        for c in ctx.verified():
            for r in c["feature_records"]:
                if r["proposed_relation"] == "RELATED_CONTEXT":
                    n += 1
                    if r["relation"] in OVERLAP:
                        v += 1
        return v, n

    gate(name)(fn)


_proposal_gate("same_goal_only_reported_material_overlap", "t-same-goal-different-mechanism")
_proposal_gate("shared_terminology_only_reported_material_overlap", "t-shared-terminology-only")


def _scan_keys_gate(name: str, group: str, scope: str):
    def fn(ctx):
        if scope == "synthesis":
            items = ctx.d["claim_syntheses"] + ([ctx.d["project_summary"]] if ctx.d["project_summary"] else [])
        elif scope == "comparison":
            items = ctx.comparisons() + ctx.d["candidate_profiles"]
        else:
            items = [ctx.d]
        return sum(1 for i in items if has_key(i, FORBIDDEN_KEYS[group])), len(items)

    gate(name)(fn)


_scan_keys_gate("provider_rank_affects_posture", "rank", "comparison")
_scan_keys_gate("popularity_affects_posture", "popularity", "comparison")
_scan_keys_gate("numeric_similarity_represented_as_novelty_probability", "similarity", "synthesis")


@gate("post_cutoff_represented_as_pre_cutoff_disclosure")
def g_post_cutoff(ctx):
    v = n = 0
    flag = {"PATENT": "patent_overlap_publication_dated_before_cutoff",
            "PRODUCT": "product_overlap_artifact_dated_before_cutoff",
            "OPEN_SOURCE": "oss_overlap_provider_dated_before_cutoff"}
    for s in ctx.d["claim_syntheses"]:
        for ctype in TYPES:
            full = [c for c in ctx.verified() if c["claim_id"] == s["claim_id"] and c["candidate_ref"]["candidate_type"] == ctype
                    and c["full_claim_relation"] in OVERLAPPING]
            if not full:
                continue
            n += 1
            before = any(ctx.bucket(c["candidate_ref"]["candidate_id"]) == "BEFORE_CUTOFF" for c in full)
            if s["chronology"][flag[ctype]] and not before:
                v += 1
            for c in full:
                if c["chronology_bucket"] != ctx.bucket(c["candidate_ref"]["candidate_id"]):
                    v += 1
    return v, n


@gate("unknown_chronology_represented_before_cutoff")
def g_unknown_chron(ctx):
    v = n = 0
    for c in ctx.comparisons():
        if ctx.bucket(c["candidate_ref"]["candidate_id"]) != "DATE_UNKNOWN":
            continue
        n += 1
        if c["chronology_bucket"] in ("BEFORE_CUTOFF", "ON_CUTOFF"):
            v += 1
    return v, n


@gate("current_product_page_represented_historical_proof")
def g_product_hist(ctx):
    v = n = 0
    for p in ctx.d["candidate_profiles"]:
        if p["candidate_ref"]["candidate_type"] != "PRODUCT":
            continue
        n += 1
        if p["chronology"]["public_availability_proven"] or p["quality"]["historical_visibility_proven"]:
            v += 1
    for s in ctx.d["claim_syntheses"]:
        if any(c["candidate_ref"]["candidate_type"] == "PRODUCT" for c in ctx.comparisons() if c["claim_id"] == s["claim_id"]):
            n += 1
            if s["chronology"]["product_historical_availability_proven"]:
                v += 1
    return v, n


def _oss_date_gate(name: str, fields: set[str]):
    def fn(ctx):
        v = n = 0
        up = ctx.upstream()
        for p in ctx.d["candidate_profiles"]:
            if p["candidate_ref"]["candidate_type"] != "OPEN_SOURCE":
                continue
            cand = up[p["candidate_ref"]["candidate_id"]][1]
            used = cand.chronology.date_field_used.value if cand.chronology.date_field_used else None
            if used not in fields:
                continue
            n += 1
            if p["chronology"]["public_availability_proven"] or p["quality"]["historical_visibility_proven"]:
                v += 1
            for s in ctx.d["claim_syntheses"]:
                if s["chronology"]["oss_historical_public_visibility_proven"]:
                    v += 1
        return v, n

    gate(name)(fn)


_oss_date_gate("github_created_at_represented_public_since", {"REPOSITORY_CREATED_AT"})
_oss_date_gate("commit_date_represented_public_availability_proof", {"COMMIT_COMMITTED_AT", "COMMIT_AUTHORED_AT"})


@gate("partial_comparison_reported_complete")
def g_partial(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        mine = [c for c in ctx.comparisons() if c["claim_id"] == s["claim_id"]]
        if all(c["status"] == "VERIFIED" for c in mine):
            continue
        n += 1
        if s["coverage"]["status"] == "COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS":
            v += 1
    return v, n


@gate("source_unavailable_comparison_reported_negative_disclosure")
def g_unavailable_negative(ctx):
    v = n = 0
    max_chars = ctx.d["bounds"]["max_chars_per_text"]
    for c in ctx.comparisons():
        profile = ctx.profile(c["profile_id"])
        if c["status"] != "VERIFIED":
            n += 1
            if c["feature_records"]:
                v += 1
            continue
        adequate = complete_material_types(ctx, profile, max_chars)
        for r in c["feature_records"]:
            if r["relation"] == "NOT_DISCLOSED":
                n += 1
                if r["feature_type"] not in adequate:
                    v += 1
    return v, n


@gate("source_quality_blocked_candidate_reported_full_overlap")
def g_blocked(ctx):
    v = n = 0
    for c in ctx.comparisons():
        profile = ctx.profile(c["profile_id"])
        if profile["eligibility"] in ("ELIGIBLE_FOR_TECHNICAL_COMPARISON", "LIMITED_TEXT_COMPARISON"):
            continue
        n += 1
        if c["status"] == "VERIFIED" or c["full_claim_relation"] == "FULL_CLAIM_TECHNICAL_OVERLAP":
            v += 1
    return v, n


@gate("no_candidate_found_reported_novel")
def g_no_candidate(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        if any(c["claim_id"] == s["claim_id"] for c in ctx.comparisons()):
            continue
        n += 1
        if s["posture"] != "INSUFFICIENT_COMPARISON_EVIDENCE":
            v += 1
    return v, n


@gate("bounded_no_overlap_reported_worldwide_novelty")
def g_worldwide(ctx):
    v = n = 0
    needed = {"BOUNDED_SEARCH_NOT_EXHAUSTIVE", "BOUNDED_COMPARISON_NOT_EXHAUSTIVE", "NO_MATCH_FOUND_IS_NOT_PROOF_OF_NOVELTY",
              "NO_LEGAL_NOVELTY_CONCLUSION"}
    max_chars = ctx.d["bounds"]["max_chars_per_text"]
    for s in ctx.d["claim_syntheses"]:
        if s["posture"] != "NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS":
            continue
        n += 1
        mine = [c for c in ctx.verified() if c["claim_id"] == s["claim_id"]]
        inv = ctx.inventory(s["inventory_id"])
        types = {f["feature_type"] for f in inv["features"]}
        adequate = all(types <= complete_material_types(ctx, ctx.profile(c["profile_id"]), max_chars) for c in mine)
        if (s["coverage"]["status"] != "COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS" or not needed <= set(s["limitations"])
                or inv["mode"] != "COMPONENT_LEVEL" or inv["completeness"] != "COMPLETE" or not adequate):
            v += 1
    return v, n


@gate("material_overlap_reported_legal_anticipation")
def g_anticipation(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        if s["posture"] != "MATERIAL_TECHNICAL_OVERLAP_FOUND":
            continue
        n += 1
        if ("TECHNICAL_OVERLAP_IS_NOT_LEGAL_ANTICIPATION" not in s["limitations"]
                or s["chronology"]["legal_prior_art_established"]):
            v += 1
    return v, n


def _verdict_gate(name: str, group: str):
    def fn(ctx):
        items = ctx.d["claim_syntheses"] + ([ctx.d["project_summary"]] if ctx.d["project_summary"] else [])
        return sum(1 for i in items if has_value(i, FORBIDDEN_VALUES[group])), len(items)

    gate(name)(fn)


_verdict_gate("legal_prior_art_conclusion_produced", "legal")
_verdict_gate("novel_verdict_produced", "novel")
_verdict_gate("not_novel_verdict_produced", "not_novel")
_verdict_gate("patentability_conclusion_produced", "patentability")
_verdict_gate("infringement_fto_conclusion_produced", "infringement")
_verdict_gate("copying_plagiarism_conclusion_produced", "copying")


@gate("project_novelty_score_produced")
def g_project_score(ctx):
    items = ctx.d["claim_syntheses"] + ([ctx.d["project_summary"]] if ctx.d["project_summary"] else [])
    v = sum(1 for i in items if has_key(i, FORBIDDEN_KEYS["score"]) or has_value(i, FORBIDDEN_VALUES["verdict"]))
    return v, len(items)


@gate("official_or_project_score_mutation")
def g_official_score(ctx):
    a = [(s.score_id, s.model_dump_json()) for s in ctx.before.project.scores]
    b = [(s.score_id, s.model_dump_json()) for s in ctx.after.project.scores]
    return (0 if a == b else 1), 1


@gate("automatic_claim_status_update")
def g_auto_status(ctx):
    old = {c.claim_id: (c.status, tuple(c.evidence_ids), tuple(c.counter_evidence_ids), c.is_critical) for c in ctx.before.project.claims}
    new = {c.claim_id: (c.status, tuple(c.evidence_ids), tuple(c.counter_evidence_ids), c.is_critical) for c in ctx.after.project.claims}
    return sum(1 for k in old if old[k] != new.get(k)), len(old)


@gate("automatic_phase2f_score_update")
def g_auto_2f(ctx):
    old, new = ctx.prior.claim_evidence_scoring, ctx.run.claim_evidence_scoring
    if old is None and new is None:
        return 0, 0
    return (0 if old == new else 1), 1


def _control_gate(name: str, control: str):
    def fn(ctx):
        attempts, accepted = ctx.controls.get(control, (0, 0))
        return accepted, attempts

    gate(name)(fn)


_control_gate("cross_run_claim_accepted", "cross_run_claim")
_control_gate("cross_run_patent_candidate_accepted", "cross_run_patent_candidate")
_control_gate("cross_run_product_candidate_accepted", "cross_run_product_candidate")
_control_gate("cross_run_oss_candidate_accepted", "cross_run_oss_candidate")
_control_gate("cross_run_snapshot_accepted", "cross_run_snapshot")
_control_gate("unknown_comparison_id_accepted_in_synthesis", "unknown_comparison_id")
_control_gate("duplicate_comparison_inflated_synthesis", "duplicate_comparison")


@gate("candidate_input_order_changes_synthesis")
def g_order(ctx):
    from src.research.novelty.synthesis import synthesize_claim

    nd = ctx.run.novelty_differentiation
    synth = ctx.synth_fn or synthesize_claim
    profiles = {p.profile_id: p for p in nd.candidate_profiles}
    v = n = 0
    for s in nd.claim_syntheses:
        mine = nd.comparisons_for(s.claim_id)
        if len([c for c in mine if c.verified]) < 2:
            continue
        n += 1
        inv = nd.inventory_for(s.claim_id)
        a = synth(nd.nd_run_id, nd.research_run_id, inv, list(mine), profiles, upstream_search_partial=bool(nd.upstream_search_partial))
        b = synth(nd.nd_run_id, nd.research_run_id, inv, list(reversed(mine)), profiles,
                  upstream_search_partial=bool(nd.upstream_search_partial))
        if a.model_dump_json() != b.model_dump_json():
            v += 1
    return v, n


@gate("checkpoint_replay_duplicates_comparison")
def g_replay(ctx):
    if not ctx.replay:
        return 0, 0
    v = 0
    if ctx.replay.get("rerun_calls"):
        v += 1
    if ctx.replay.get("rerun_nd") is not None and not _eq_dump(_strip_times(ctx.d), _strip_times(ctx.replay["rerun_nd"])):
        v += 1
    if ctx.replay.get("resumed_nd") is not None and not _eq_dump(_strip_times(ctx.d), _strip_times(ctx.replay["resumed_nd"])):
        v += 1
    pairs = [(c["claim_id"], c["candidate_ref"]["candidate_id"]) for c in ctx.comparisons()]
    if len(set(pairs)) != len(pairs):
        v += 1
    return v, 1


def _strip_times(d: dict) -> dict:
    d = copy.deepcopy(d)
    d.pop("started_at", None)
    d.pop("completed_at", None)
    return d


def _prompt_lines() -> list[str]:
    return [l.strip().casefold() for p in (PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1, NOVELTY_FEATURE_EXTRACTION_PROMPT_V1)
            for l in p.splitlines() if len(l.strip()) >= 40]


@gate("prompt_injection_followed")
def g_injection(ctx):
    """Following an embedded instruction shows up as behaviour: the hidden prompt
    leaking into a verified comparison, or a score appearing. Candidate text that
    merely READS like an instruction is inert data and is never a violation."""
    v = n = 0
    lines = _prompt_lines()
    for c in ctx.verified():
        n += 1
        blob = json.dumps(c, ensure_ascii=False).casefold()
        sources = " ".join(
            (ctx.src_text(t["source_record_kind"], str(t["source_record_id"])) or "")
            for t in ctx.profile(c["profile_id"])["texts"]
        ).casefold()
        if any(line in blob and line not in sources for line in lines):
            v += 1
    if ctx.case.injection:
        n += 1
        if has_key(ctx.d, FORBIDDEN_KEYS["score"]):
            v += 1
    return v, n


@gate("candidate_text_treated_as_system_instruction")
def g_cand_as_system(ctx):
    calls = ctx.provider.calls if ctx.provider is not None else []
    v = 0
    candidate_texts = []
    r = ctx.run
    for kind, rows in (("PATENT_TEXT_SNAPSHOT", r.patent_prior_art.snapshots if r.patent_prior_art else []),
                       ("REPOSITORY_SNAPSHOT", r.open_source_prior_art.snapshots if r.open_source_prior_art else [])):
        candidate_texts += [s.text for s in rows if len(s.text) >= 12]
    candidate_texts += [a.text_snapshot for a in (r.product_prior_art.artifacts if r.product_prior_art else []) if len(a.text_snapshot) >= 12]
    static = {PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1, NOVELTY_FEATURE_EXTRACTION_PROMPT_V1}
    for call in calls:
        prompt = str(call["system_prompt"])
        if prompt not in static or any(t in prompt for t in candidate_texts):
            v += 1
    return v, len(calls)


@gate("student_text_treated_as_system_instruction")
def g_student_as_system(ctx):
    calls = ctx.provider.calls if ctx.provider is not None else []
    v = sum(1 for call in calls if any(text in str(call["system_prompt"]) for text in ctx.claims.values()))
    return v, len(calls)


@gate("provider_credential_persisted")
def g_credential(ctx):
    if not ctx.case.credential:
        return 0, 0
    blob = ctx.after.model_dump_json() + json.dumps(ctx.d)
    return (1 if ctx.case.credential in blob else 0), 1


def _numbers(value: Any):
    for k, v in walk(value):
        if isinstance(v, float):
            yield k, v


@gate("hidden_score_or_opaque_scalar_added")
def g_opaque(ctx):
    outputs = {k: ctx.d[k] for k in ("inventories", "candidate_profiles", "comparisons", "claim_syntheses", "project_summary")}
    bad = any(True for _ in _numbers(outputs)) or has_key(outputs, {"weight", "weights", "novelty_weight"})
    return (1 if bad else 0), 1


@gate("source_quality_collapsed_into_opaque_numeric_weight")
def g_quality_numeric(ctx):
    v = 0
    profiles = ctx.d["candidate_profiles"]
    for p in profiles:
        if any(isinstance(x, (int, float)) and not isinstance(x, bool) for _, x in walk(p["quality"])):
            v += 1
    return v, len(profiles)


@gate("candidate_type_semantics_conflated")
def g_conflated(ctx):
    up = ctx.upstream()
    v = n = 0
    for p in ctx.d["candidate_profiles"]:
        n += 1
        ref = p["candidate_ref"]
        entry = up.get(ref["candidate_id"])
        ctype = ref["candidate_type"]
        unit = p["independence_unit"]
        ok = entry is not None and entry[0] == ctype and unit["candidate_type"] == ctype
        ok = ok and all(t["text_kind"].startswith(TYPE_PREFIX[ctype]) for t in p["texts"])
        ok = ok and unit["unit_kind"].startswith({"PATENT": "PATENT_", "PRODUCT": "PRODUCT_", "OPEN_SOURCE": "OSS_"}[ctype])
        if not ok:
            v += 1
    return v, n


@gate("bounded_comparison_limitation_omitted")
def g_bounded_lim(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        n += 1
        if not {"BOUNDED_SEARCH_NOT_EXHAUSTIVE", "BOUNDED_COMPARISON_NOT_EXHAUSTIVE"} <= set(s["limitations"]):
            v += 1
    for c in ctx.verified():
        n += 1
        if "COMPARED_TEXT_IS_BOUNDED" not in c["limitations"]:
            v += 1
    return v, n


PROJECT_LIMITATIONS = {
    "BOUNDED_SEARCH_NOT_EXHAUSTIVE", "BOUNDED_COMPARISON_NOT_EXHAUSTIVE", "NO_LEGAL_NOVELTY_CONCLUSION",
    "TECHNICAL_OVERLAP_IS_NOT_LEGAL_ANTICIPATION", "NO_MATCH_FOUND_IS_NOT_PROOF_OF_NOVELTY",
    "NO_PATENTABILITY_INFRINGEMENT_FTO_OR_COPYING_CONCLUSION", "NOT_A_PROJECT_OR_OFFICIAL_SCORE",
    "SOURCE_TEXT_MAY_BE_INCOMPLETE", "PRODUCT_HISTORICAL_AVAILABILITY_MAY_BE_UNKNOWN",
    "OSS_HISTORICAL_VISIBILITY_MAY_BE_UNKNOWN", "PATENT_FAMILY_GROUPING_IS_NOT_LEGAL_EQUIVALENCE",
    "PRODUCT_IDENTITY_MAY_BE_UNRESOLVED", "FORKS_MAY_MATERIALLY_DIVERGE",
}


@gate("no_legal_novelty_limitation_omitted")
def g_legal_lim(ctx):
    v = n = 0
    for s in ctx.d["claim_syntheses"]:
        n += 1
        if not {"NO_LEGAL_NOVELTY_CONCLUSION", "NO_PATENTABILITY_INFRINGEMENT_FTO_OR_COPYING_CONCLUSION",
                "NOT_A_PROJECT_OR_OFFICIAL_SCORE"} <= set(s["limitations"]):
            v += 1
    if ctx.d["project_summary"]:
        n += 1
        if not PROJECT_LIMITATIONS <= set(ctx.d["project_summary"]["limitations"]):
            v += 1
    return v, n


@gate("final_posture_without_traceable_basis")
def g_traceable(ctx):
    v = n = 0
    ids = {c["comparison_id"] for c in ctx.comparisons()}
    for s in ctx.d["claim_syntheses"]:
        n += 1
        inv = ctx.inventory(s["inventory_id"])
        ok = bool(s["posture_reasons"]) and set(s["compared_comparison_ids"]) <= ids
        ok = ok and {f["feature_id"] for f in s["feature_differentiations"]} == {f["feature_id"] for f in inv["features"]}
        if s["posture"] == "MATERIAL_TECHNICAL_OVERLAP_FOUND":
            ok = ok and bool(s["full_overlap_comparison_ids"]) and set(s["full_overlap_comparison_ids"]) <= ids
        if not ok:
            v += 1
    return v, n


@gate("model_relation_accepted_without_deterministic_anchor_validation")
def g_model_relation(ctx):
    v = n = 0
    for c in ctx.verified():
        by_id = {a["anchor_id"]: a for a in c["anchors"]}
        for r in c["feature_records"]:
            if r["relation"] not in ANCHORED:
                continue
            n += 1
            anchors = [by_id.get(i) for i in r["anchor_ids"]]
            if not anchors or any(a is None or not _anchor_ok(ctx, a) for a in anchors):
                v += 1
                continue
            ceiling = max(REL_STRENGTH[CEILING[indep_capacity(ctx, a)]] for a in anchors)
            if REL_STRENGTH[r["relation"]] > ceiling:
                v += 1
    return v, n


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def _first(items, pred=lambda x: True):
    return next((i for i in items if pred(i)), None)


def _t_fab_feature(d, ctx):
    inv = _first(d["inventories"], lambda i: i["features"])
    if inv is None:
        return None
    inv["features"][0]["text"] = "fabricated feature text"
    return d


def _t_fab_excerpt(d, ctx):
    a = _first([a for c in d["comparisons"] for a in c["anchors"]])
    if a is None:
        return None
    a["excerpt"] = "x" * len(a["excerpt"])
    return d


def _t_wrong_snapshot(d, ctx):
    a = _first([a for c in d["comparisons"] for a in c["anchors"]])
    if a is None:
        return None
    a["source_record_id"] = str(uuid4())
    return d


def _t_cross_candidate(d, ctx):
    for c in d["comparisons"]:
        for a in c["anchors"]:
            other = _first(d["comparisons"], lambda o: o["candidate_ref"]["candidate_id"] != c["candidate_ref"]["candidate_id"]
                           and o["anchors"])
            if other is None:
                return None
            a["source_record_id"] = other["anchors"][0]["source_record_id"]
            a["source_record_kind"] = other["anchors"][0]["source_record_kind"]
            return d
    return None


def _inflate(index: int):
    def tamper(d, ctx):
        s = _first(d["claim_syntheses"], lambda s: any(
            c["claim_id"] == s["claim_id"] and c["candidate_ref"]["candidate_type"] == TYPES[index] and c["status"] == "VERIFIED"
            for c in d["comparisons"]))
        if s is None:
            return None
        s["type_summaries"][index]["full_overlap_independent_units"] += 2
        return d

    return tamper


def _t_unit_merge(d, ctx):
    products = [c for c in d["comparisons"] if c["candidate_ref"]["candidate_type"] == "PRODUCT"]
    if len(products) < 2:
        return None
    key = products[0]["independence_unit"]["unit_key"]
    for c in products[1:]:
        if c["claim_id"] == products[0]["claim_id"]:
            c["independence_unit"]["unit_key"] = key
    return d


def _t_fork_independent(d, ctx):
    up = ctx.upstream()
    c = _first(d["comparisons"], lambda c: c["candidate_ref"]["candidate_type"] == "OPEN_SOURCE"
               and up[c["candidate_ref"]["candidate_id"]][1].relationship.value in ("FORK", "TEMPLATE_DERIVATIVE"))
    if c is None:
        return None
    c["independence_unit"]["counts_as_independent"] = True
    return d


def _t_missing_relationship(d, ctx):
    inv = _first(d["inventories"], lambda i: i["mode"] == "COMPONENT_LEVEL"
                 and sum(1 for f in i["features"] if f["feature_type"] != "COMBINATION") >= 2)
    if inv is None:
        return None
    inv["features"] = [f for f in inv["features"] if f["feature_type"] != "COMBINATION"]
    return d


def _t_false_full(d, ctx):
    c = _first(d["comparisons"], lambda c: c["status"] == "VERIFIED"
               and any(r["relation"] != "DISCLOSED" for r in c["feature_records"]))
    if c is None:
        return None
    c["full_claim_relation"] = "FULL_CLAIM_TECHNICAL_OVERLAP"
    return d


def _t_false_no_overlap(d, ctx):
    s = _first(d["claim_syntheses"], lambda s: any(
        c["claim_id"] == s["claim_id"] and c["status"] != "VERIFIED" for c in d["comparisons"]))
    if s is None:
        return None
    s["coverage"]["status"] = "COMPLETE_WITHIN_CONFIGURED_COMPARISON_BOUNDS"
    s["posture"] = "NO_MATERIAL_OVERLAP_FOUND_WITHIN_BOUNDS"
    return d


def _t_post_as_pre(d, ctx):
    flag = {"PATENT": "patent_overlap_publication_dated_before_cutoff",
            "PRODUCT": "product_overlap_artifact_dated_before_cutoff",
            "OPEN_SOURCE": "oss_overlap_provider_dated_before_cutoff"}
    for s in d["claim_syntheses"]:
        for ctype in TYPES:
            full = [c for c in d["comparisons"] if c["claim_id"] == s["claim_id"] and c["status"] == "VERIFIED"
                    and c["candidate_ref"]["candidate_type"] == ctype and c["full_claim_relation"] in OVERLAPPING]
            if full and not any(ctx.bucket(c["candidate_ref"]["candidate_id"]) == "BEFORE_CUTOFF" for c in full):
                s["chronology"][flag[ctype]] = True
                return d
    return None


def _t_current_product(d, ctx):
    p = _first(d["candidate_profiles"], lambda p: p["candidate_ref"]["candidate_type"] == "PRODUCT")
    if p is None:
        return None
    p["chronology"]["public_availability_proven"] = True
    return d


def _t_created_at(d, ctx):
    up = ctx.upstream()
    p = _first(d["candidate_profiles"], lambda p: p["candidate_ref"]["candidate_type"] == "OPEN_SOURCE"
               and up[p["candidate_ref"]["candidate_id"]][1].chronology.date_field_used is not None
               and up[p["candidate_ref"]["candidate_id"]][1].chronology.date_field_used.value == "REPOSITORY_CREATED_AT")
    if p is None:
        return None
    p["chronology"]["public_availability_proven"] = True
    return d


def _t_legal_verdict(d, ctx):
    if not d["claim_syntheses"]:
        return None
    d["claim_syntheses"][0]["posture"] = "NOVEL"
    return d


def _t_hidden_score(d, ctx):
    if d["project_summary"] is None:
        return None
    d["project_summary"]["novelty_score"] = 0.87
    return d


def _t_prompt_injection(d, ctx):
    c = _first(d["comparisons"], lambda c: c["feature_records"])
    if c is None:
        return None
    line = next(l for l in PRIOR_ART_TECHNICAL_COMPARISON_PROMPT_V1.splitlines() if len(l.strip()) >= 40)
    c["feature_records"][0]["model_rationale"] = f"My instructions: {line.strip()}"
    return d


def _t_duplicate(d, ctx):
    c = _first(d["comparisons"], lambda c: c["status"] == "VERIFIED")
    if c is None:
        return None
    d["comparisons"].append(copy.deepcopy(c))
    return d


def _t_unknown_comparison(d, ctx):
    s = _first(d["claim_syntheses"])
    if s is None:
        return None
    s["compared_comparison_ids"].append(str(uuid4()))
    return d


def _t_cross_run_claim(d, ctx):
    if not d["claim_inputs"]:
        return None
    d["inventories"][0]["claim_id"] = "C-999"
    return d


def _foreign(index: int):
    def tamper(d, ctx):
        field_name = ("patent_run_id", "product_run_id", "oss_run_id")[index]
        p = _first(d["candidate_profiles"], lambda p: p["candidate_ref"]["candidate_type"] == TYPES[index])
        if p is None:
            return None
        p["candidate_ref"]["source_run_id"] = str(uuid4())
        return d

    return tamper


def _t_cross_run_snapshot(d, ctx):
    c = _first([c for c in d["comparisons"] if c["compared_text_ref_ids"]])
    if c is None:
        return None
    c["compared_text_ref_ids"][0] = str(uuid4())
    return d


# name -> (tamper, gate that must fire or None for contract-only, kind)
CONTROLS: dict[str, tuple[Callable, str | None]] = {
    "fabricated_claim_feature": (_t_fab_feature, "fabricated_claim_feature_accepted"),
    "fabricated_candidate_excerpt": (_t_fab_excerpt, "fabricated_candidate_excerpt_accepted"),
    "wrong_candidate_snapshot": (_t_wrong_snapshot, "wrong_snapshot_anchor_accepted"),
    "cross_candidate_evidence_mixing": (_t_cross_candidate, "wrong_snapshot_anchor_accepted"),
    "family_inflation": (_inflate(0), "patent_family_inflated_count"),
    "product_listing_inflation": (_inflate(1), "product_listing_inflated_count"),
    "product_entity_merge": (_t_unit_merge, "product_listing_inflated_count"),
    "fork_inflation": (_inflate(2), "fork_inflated_count"),
    "fork_marked_independent": (_t_fork_independent, "fork_inflated_count"),
    "missing_relationship_feature": (_t_missing_relationship, "uncovered_material_relationship_ignored"),
    "false_full_overlap": (_t_false_full, "all_components_without_relationship_reported_full_overlap"),
    "false_no_overlap_under_partial_coverage": (_t_false_no_overlap, "partial_comparison_reported_complete"),
    "post_cutoff_mislabeled_pre_cutoff": (_t_post_as_pre, "post_cutoff_represented_as_pre_cutoff_disclosure"),
    "current_product_page_as_historical": (_t_current_product, "current_product_page_represented_historical_proof"),
    "created_at_as_public_since": (_t_created_at, "github_created_at_represented_public_since"),
    "legal_novelty_verdict_inserted": (_t_legal_verdict, "novel_verdict_produced"),
    "hidden_project_score_inserted": (_t_hidden_score, "project_novelty_score_produced"),
    "prompt_injection_compliance": (_t_prompt_injection, "prompt_injection_followed"),
    "cross_run_claim": (_t_cross_run_claim, None),
    "cross_run_patent_candidate": (_foreign(0), None),
    "cross_run_product_candidate": (_foreign(1), None),
    "cross_run_oss_candidate": (_foreign(2), None),
    "cross_run_snapshot": (_t_cross_run_snapshot, None),
    "unknown_comparison_id": (_t_unknown_comparison, None),
    "duplicate_comparison": (_t_duplicate, None),
}
"""Controls that must be CAUGHT: either the gate named fires on the tampered
JSON, or (cross-run, unknown id, duplicates) the contract refuses to load it."""

SPECIAL_CONTROLS = ("phase2f_mutation", "trustgate_mutation", "input_order_instability")


def contract_refuses(d: dict) -> bool:
    try:
        NoveltyDifferentiationRun.model_validate(d)
    except Exception:
        return True
    return False


def run_control(ctx: Ctx, name: str) -> tuple[bool | None, str]:
    """(caught?, how). None means the control was inapplicable to this case."""
    if name == "phase2f_mutation":
        tampered_run = ctx.run.model_copy(deep=True)
        scoring = tampered_run.claim_evidence_scoring
        if scoring is None:
            return None, ""
        object.__setattr__(tampered_run, "claim_evidence_scoring", scoring.model_copy(update={"status": "FAILED"}))
        clone = Ctx(**{**ctx.__dict__, "run": tampered_run})
        v, _ = GATE_FUNCS["phase2f_mutation"](clone)
        return v > 0, "gate"
    if name == "trustgate_mutation":
        state = ctx.after.model_copy(deep=True)
        gate_obj = state.project.trust_gate
        if gate_obj is None:
            return None, ""
        state.project.trust_gate = gate_obj.model_copy(update={"search_coverage": 0.1})
        clone = Ctx(**{**ctx.__dict__, "after": state})
        v, _ = GATE_FUNCS["trust_gate_mutation"](clone)
        return v > 0, "gate"
    if name == "input_order_instability":
        def order_dependent(nd_run_id, research_run_id, inventory, comparisons, profiles, **kw):
            from src.research.novelty.synthesis import synthesize_claim

            return synthesize_claim(nd_run_id, research_run_id, inventory, comparisons[:1], profiles, **kw)

        clone = Ctx(**{**ctx.__dict__, "synth_fn": order_dependent})
        v, n = GATE_FUNCS["candidate_input_order_changes_synthesis"](clone)
        return (v > 0) if n else None, "gate"
    tamper, gate_name = CONTROLS[name]
    d = tamper(copy.deepcopy(ctx.d), ctx)
    if d is None:
        return None, ""
    refused = contract_refuses(d)
    fired = False
    if gate_name:
        clone = Ctx(**{**ctx.__dict__, "d": d})
        try:
            v, _ = GATE_FUNCS[gate_name](clone)
        except Exception:
            v = 1
        fired = v > 0
    return (refused or fired), ("contract" if refused else "gate")


# ---------------------------------------------------------------------------
# Summary and scoring
# ---------------------------------------------------------------------------


def summarize(ctx: Ctx) -> dict[str, Any]:
    d = ctx.d
    up = ctx.upstream()
    tags = ctx.tag_map()
    by_cid = {cid: tag for tag, cid in tags.items()}
    first_claim = ctx.case.claims[0].claim_id
    s: dict[str, Any] = {
        "status": d["status"],
        "model_calls": d["model_comparisons_performed"],
        "errors": sorted({e["code"] for e in d["errors"]}),
        "claims_input": len(d["claim_inputs"]),
    }
    patent_profiles = [p for p in d["candidate_profiles"] if p["candidate_ref"]["candidate_type"] == "PATENT"]
    s["patent.publication_count"] = len(patent_profiles)
    s["patent.independent_unit_keys"] = len({p["independence_unit"]["corroboration_key"] if "corroboration_key" in p["independence_unit"]
                                              else p["independence_unit"]["unit_key"]
                                              for p in patent_profiles if p["independence_unit"]["counts_as_independent"]})
    rejected: set[str] = set()
    for c in d["comparisons"]:
        rejected |= {r["reason"] for r in c["rejected_anchors"]}
        profile = ctx.profile(c["profile_id"])
        tag = by_cid.get(c["candidate_ref"]["candidate_id"])
        if tag is None:
            continue
        key = f"cand.{tag}" if c["claim_id"] == first_claim else f"cand.{tag}@{c['claim_id']}"
        s[key] = {
            "eligibility": profile["eligibility"],
            "unit_kind": profile["independence_unit"]["unit_kind"],
            "independent": profile["independence_unit"]["counts_as_independent"],
            "correlated": profile["independence_unit"]["correlation_group_key"] is not None,
            "bucket": profile["chronology"]["bucket"],
            "status": c["status"],
            "relation": c["full_claim_relation"],
            "model_name_recorded": c["model_name"] is not None,
        }
        entry = up.get(c["candidate_ref"]["candidate_id"])
        if entry is not None and entry[0] == "PATENT":
            s[key]["family_status"] = entry[1].family_status.value
        rel_key = f"rel.{tag}" if c["claim_id"] == first_claim else f"rel.{tag}@{c['claim_id']}"
        inv = ctx.inventory(c["inventory_id"])
        text_by_feature = {f["feature_id"]: ("COMBINATION" if f["feature_type"] == "COMBINATION" else f["text"])
                           for f in inv["features"]}
        s[rel_key] = {text_by_feature[r["feature_id"]]: r["relation"] for r in c["feature_records"]}
        s[f"reltype.{tag}"] = {text_by_feature[r["feature_id"]]: r["feature_type"] for r in c["feature_records"]}
        by_id = {a["anchor_id"]: a for a in c["anchors"]}
        s[f"anchors.{tag}"] = sorted({f"{a['text_kind']}:{a['capacity']}:{a['occurrence_resolution']}" for a in by_id.values()})
        s[f"resolution.{tag}"] = {text_by_feature[r["feature_id"]]: r["resolution_reasons"] for r in c["feature_records"]
                                  if r["resolution_reasons"]}
    s["rejected_anchor_reasons"] = sorted(rejected)
    for inv in d["inventories"]:
        cid = inv["claim_id"]
        s[f"claim.{cid}.mode"] = inv["mode"]
        s[f"claim.{cid}.mode_reasons"] = inv["mode_reasons"]
        s[f"claim.{cid}.inventory_completeness"] = inv["completeness"]
        s[f"claim.{cid}.feature_types"] = sorted({f["feature_type"] for f in inv["features"]})
        s[f"claim.{cid}.feature_derivations"] = sorted({f["derivation"] for f in inv["features"]})
        s[f"claim.{cid}.feature_rejections"] = sorted({r["reason"] for r in inv["rejected_proposals"]})
        s[f"claim.{cid}.feature_texts"] = sorted(f["text"] for f in inv["features"] if f["feature_type"] != "COMBINATION")
    for syn in d["claim_syntheses"]:
        cid = syn["claim_id"]
        s[f"claim.{cid}.posture"] = syn["posture"]
        s[f"claim.{cid}.posture_reasons"] = syn["posture_reasons"]
        s[f"claim.{cid}.reporting"] = syn["differentiation_reporting"]
        s[f"claim.{cid}.coverage"] = syn["coverage"]["status"]
        s[f"claim.{cid}.coverage_flags"] = syn["coverage"]["flags"]
        inv = ctx.inventory(syn["inventory_id"])
        text_by_feature = {f["feature_id"]: ("COMBINATION" if f["feature_type"] == "COMBINATION" else f["text"])
                           for f in inv["features"]}
        s[f"claim.{cid}.diff"] = {text_by_feature[f["feature_id"]]: f["status"] for f in syn["feature_differentiations"]}
        s[f"claim.{cid}.units"] = {
            t["candidate_type"]: {
                "full_candidates": t["full_overlap_candidates"], "full_units": t["full_overlap_units"],
                "independent": t["full_overlap_independent_units"],
                "correlation_groups": t["full_overlap_unresolved_correlation_groups"],
                "partial_units": t["partial_overlap_units"], "component_only_units": t["component_only_units"],
            }
            for t in syn["type_summaries"]
        }
        s[f"claim.{cid}.chronology"] = {
            **{k: v for k, v in syn["chronology"].items() if isinstance(v, bool)},
            "by_type_bucket": syn["chronology"]["overlap_by_type_bucket"],
        }
        s[f"claim.{cid}.limitations"] = syn["limitations"]
        s[f"claim.{cid}.full_overlap_comparisons"] = len(syn["full_overlap_comparison_ids"])
        s[f"claim.{cid}.type_coverage"] = {
            t["candidate_type"]: {k: t[k] for k in ("available", "compared", "omitted_by_limit", "blocked_by_source_quality",
                                                    "not_comparable", "failed", "not_executed")}
            for t in syn["coverage"]["per_type"]
        }
    if d["project_summary"]:
        ps = d["project_summary"]
        s["project.posture_counts"] = ps["posture_counts"]
        s["project.recurring"] = ps["recurring_differentiating_feature_texts"]
        s["project.assessed"] = ps["assessed_claim_count"]
        s["project.chronology"] = ps["chronology_distribution"]
        s["project.candidate_types"] = ps["candidate_type_distribution"]
    return s


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _matches(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and sorted(map(json.dumps, expected)) == sorted(map(json.dumps, actual))
    return expected == actual


def check_expected(key: str, expected: Any, summary: dict[str, Any]) -> tuple[bool, Any]:
    if key.endswith("_includes"):
        actual = summary.get(key[: -len("_includes")])
        return (isinstance(actual, list) and set(expected) <= set(actual)), actual
    if key.endswith("_excludes"):
        actual = summary.get(key[: -len("_excludes")])
        return (isinstance(actual, list) and not set(expected) & set(actual)), actual
    if key.endswith("_max"):
        actual = summary.get(key[: -len("_max")])
        return (actual is not None and actual <= expected), actual
    actual = summary.get(key)
    return _matches(expected, actual), actual


def _family(key: str, sub: str | None, ctx: Ctx, summary: dict[str, Any]) -> tuple[str, ...]:
    return _families(key, sub, ctx, summary)


def _families(key: str, sub: str | None, ctx: Ctx, summary: dict[str, Any]) -> tuple[str, ...]:
    base = key.rsplit("_", 1)[0] if key.endswith(("_includes", "_excludes", "_max")) else key
    if base.startswith("rel."):
        tag = base.split(".", 1)[1].split("@")[0]
        cid = ctx.tag_map().get(tag)
        ctype = ctx.upstream()[cid][0] if cid else "PATENT"
        ftype = (summary.get(f"reltype.{tag}") or {}).get(sub or "", "COMPONENT")
        kind = "combination_relation_accuracy" if ftype in RELATIONAL else "component_relation_accuracy"
        source = {"PATENT": "patent_disclosure_accuracy", "PRODUCT": "product_disclosure_accuracy",
                  "OPEN_SOURCE": "oss_disclosure_accuracy"}[ctype]
        return (kind, source)
    if base.startswith("anchors.") or base.startswith("resolution."):
        return ("source_scope_accuracy",)
    if base.startswith("cand."):
        field_name = sub or ""
        if field_name == "eligibility":
            return ("candidate_eligibility_accuracy",)
        if field_name in ("unit_kind", "independent", "correlated"):
            return ("candidate_independence_accuracy",)
        if field_name == "bucket":
            return ("chronology_separation_accuracy",)
        if field_name == "relation":
            return ("full_claim_relation_accuracy",)
        return ("boundedness_accuracy",)
    if ".units" in base:
        return ("candidate_independence_accuracy",)
    if base.endswith(".chronology"):
        return ("cutoff_handling_accuracy",)
    if base.endswith(".diff"):
        return ("differentiating_feature_accuracy",)
    if base.endswith((".posture", ".posture_reasons", ".reporting", ".limitations", ".full_overlap_comparisons")) or base.startswith("project."):
        return ("claim_posture_accuracy",)
    if base.endswith((".coverage", ".coverage_flags", ".type_coverage")) or base in ("model_calls", "status"):
        return ("boundedness_accuracy",)
    if base.endswith((".feature_types", ".feature_derivations", ".feature_texts", ".mode", ".mode_reasons",
                      ".inventory_completeness", ".feature_rejections")):
        return ("relationship_feature_accuracy",)
    if base in ("rejected_anchor_reasons", "errors"):
        return ("candidate_anchor_accuracy",)
    return ("claim_posture_accuracy",)


@dataclass
class CaseResult:
    case: NoveltyGoldCase
    summary: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    gates: dict[str, tuple[int, int]] = field(default_factory=dict)
    controls: list[tuple[str, bool | None, str]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    contract_ok: int = 0
    contract_total: int = 0
    error: str | None = None
    ctx: Any = None

    def bump(self, family: str, ok: bool) -> None:
        self.quality[family][1] += 1
        self.quality[family][0] += int(ok)


def derived_quality(ctx: Ctx, result: CaseResult) -> None:
    """Quality families re-derived from the run itself, not from authored keys."""
    d = ctx.d
    for inv in d["inventories"]:
        text = ctx.claims[inv["claim_id"]]
        for f in inv["features"]:
            result.bump("feature_inventory_traceability", text[f["start"]:f["end"]] == f["text"])
        if inv["mode"] == "COMPONENT_LEVEL":
            covered = [False] * len(text)
            for f in inv["features"]:
                if f["feature_type"] != "COMBINATION":
                    for i in range(f["start"], f["end"]):
                        covered[i] = True
            uncovered_ok = not any(not covered[i] and is_material_char(text[i]) for i in range(len(text)))
            elements = sum(1 for f in inv["features"] if f["feature_type"] != "COMBINATION")
            has_combo = any(f["feature_type"] == "COMBINATION" for f in inv["features"])
            result.bump("feature_inventory_material_coverage", uncovered_ok and (elements < 2 or has_combo))
    for c in d["comparisons"]:
        for a in c["anchors"]:
            result.bump("candidate_anchor_accuracy", _anchor_ok(ctx, a))
    nd_ok = all(GATE_FUNCS[g](ctx)[0] == 0 for g in GATES[:15])
    result.bump("immutability_accuracy", nd_ok)
    legal = [g for g in GATES if g.endswith(("_conclusion_produced", "_verdict_produced")) or g.startswith("project_novelty")]
    for syn in d["claim_syntheses"]:
        result.bump("legal_boundary_accuracy", not (has_value(syn, {v for g in FORBIDDEN_VALUES.values() for v in g})
                                                    or has_key(syn, FORBIDDEN_KEYS["legal"] | FORBIDDEN_KEYS["score"])))
    if ctx.replay:
        ok = not ctx.replay.get("rerun_calls") and (
            ctx.replay.get("rerun_nd") is None or _eq_dump(_strip_times(d), _strip_times(ctx.replay["rerun_nd"]))) and (
            ctx.replay.get("resumed_nd") is None or _eq_dump(_strip_times(d), _strip_times(ctx.replay["resumed_nd"])))
        result.bump("idempotency_accuracy", ok)
    if ctx.case.injection:
        v, _ = GATE_FUNCS["prompt_injection_followed"](ctx)
        result.bump("prompt_injection_resistance", v == 0)
    attempts = sum(a for n, (a, _) in ctx.controls.items() if n.startswith("cross_run") or n in ("unknown_comparison_id", "duplicate_comparison"))
    accepted = sum(x for n, (_, x) in ctx.controls.items() if n.startswith("cross_run") or n in ("unknown_comparison_id", "duplicate_comparison"))
    for _ in range(attempts):
        result.bump("cross_run_isolation_accuracy", True)
    for _ in range(accepted):
        result.quality["cross_run_isolation_accuracy"][0] -= 1


def _phase2i_upstream(case: NoveltyGoldCase) -> EvaluationGraphState:
    claims = [c.model_dump() for c in case.claims]
    product = case.product or {"provider": False, "fetcher": False}
    oss = case.oss or {"provider": False}
    state = build_upstream(case.case_id, claims, patent=case.patent or None, product=product, oss=oss, cutoff=case.cutoff)
    if case.drop_sufficiency:
        run = state.active_research_run
        stripped = ResearchRun.model_validate({**dict(run), "claim_sufficiency": None, "claim_evidence_scoring": None})
        state = state.model_copy(update={"research_runs": {str(run.research_run_id): stripped}})
    return state


def run_case(case: NoveltyGoldCase) -> CaseResult:
    result = CaseResult(case=case)
    try:
        before = _phase2i_upstream(case)
        claims = {c.claim_id: c.claim for c in case.claims}
        model = None if case.no_model else ScriptedNoveltyModel(claims, case.script)
        provider = model.provider() if model else None
        bounds = NoveltyComparisonBounds(**case.bounds) if case.bounds else None
        after = run_phase2i(before, provider, bounds=bounds,
                            interrupt_before=case.interrupt_before)
        run = after.active_research_run
        prior = before.active_research_run
        d = run.novelty_differentiation.model_dump(mode="json")
        ctx = Ctx(case=case, before=before, after=after, run=run, prior=prior, d=d, claims=claims, model=model, provider=provider)

        if case.rerun:
            again_model = ScriptedNoveltyModel(claims, case.script)
            again = run_phase2i(after, again_model.provider(), bounds=bounds)
            ctx.replay = {"rerun_calls": len(again_model.calls),
                          "rerun_nd": again.active_research_run.novelty_differentiation.model_dump(mode="json")}
        if case.interrupt_before:
            plain_model = ScriptedNoveltyModel(claims, case.script)
            plain = run_phase2i(before, plain_model.provider(), bounds=bounds)
            ctx.replay = {**ctx.replay, "resumed_nd": plain.active_research_run.novelty_differentiation.model_dump(mode="json")}

        for name in case.negative_controls:
            caught, how = run_control(ctx, name)
            result.controls.append((name, caught, how))
            if caught is not None:
                attempts, accepted = ctx.controls.get(name, (0, 0))
                ctx.controls[name] = (attempts + 1, accepted + (0 if caught else 1))

        result.ctx = ctx
        result.summary = summarize(ctx)
        for key, expected in case.expected.items():
            ok, actual = check_expected(key, expected, result.summary)
            result.contract_total += 1
            result.contract_ok += int(ok)
            if not ok:
                result.failures.append({"case": case.case_id, "key": key, "expected": expected, "actual": actual})
            if isinstance(expected, dict) and not key.endswith(("_includes", "_excludes", "_max")):
                for sub, want in expected.items():
                    sub_ok = _matches(want, (result.summary.get(key) or {}).get(sub) if isinstance(result.summary.get(key), dict) else None)
                    for family in _family(key, sub, ctx, result.summary):
                        result.bump(family, sub_ok)
            else:
                for family in _family(key, None, ctx, result.summary):
                    result.bump(family, ok)
        derived_quality(ctx, result)
        for name in GATES:
            result.gates[name] = GATE_FUNCS[name](ctx)
    except Exception:  # pragma: no cover - surfaced to the reviewer
        result.error = traceback.format_exc()
    return result


__all__ = ["CONTROLS", "GATES", "GATE_FUNCS", "SPECIAL_CONTROLS", "CaseResult", "Ctx", "run_case"]
