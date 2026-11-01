"""The per-case evaluation context: the serialized Phase 3B run, the upstream records and independent readers.

Everything here reads the run as a plain JSON dict. It never calls a Phase 3B validator, synthesis or derivation
function: the scorer re-implements the policy rules from ``catalog.py`` so a defect in production cannot also be
the definition of "correct".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.evals.experiment_review import catalog as cat
from src.evals.experiment_review.dataset import ExperimentGoldCase

MARKER_SUBMISSION = "=== STUDENT SUBMISSION (UNTRUSTED CONTENT) ==="
MARKER_CLAIMS = "=== PROJECT CLAIMS AND TARGETS (UNTRUSTED CONTENT) ==="
MARKER_EXCERPTS = "=== EXPERIMENT PROTOCOL EXCERPTS (UNTRUSTED CONTENT) ==="
MARKER_ITEMS = "=== ITEMS TO JUDGE ==="
MARKER_END = "=== END OF UNTRUSTED CONTENT ==="
CODE_MARKERS = (MARKER_SUBMISSION, MARKER_CLAIMS, MARKER_EXCERPTS, MARKER_ITEMS, MARKER_END)
PLACEHOLDER = "[RESULT WITHHELD]"
ZWSP = chr(0x200B)
ABSENT = "ABSENT"
BARE = re.compile(r"^[\s\W\d_]*(?:n|N)?[\s\W\d_]*$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ARABIC = re.compile("[" + chr(0x600) + "-" + chr(0x6FF) + chr(0x750) + "-" + chr(0x77F) + "]")
LEGAL_MARKERS = ("patentable", "not novel", "is novel", "anticipated", "infringes", "legally valid")

TASK_NAMES = {"segment": "EXPERIMENT_SEGMENTATION", "extract": "EXPERIMENT_PROTOCOL_EXTRACTION",
              "applicability": "EXPERIMENT_APPLICABILITY", "link": "EXPERIMENT_TARGET_LINKAGE"}
EMITTERS = {
    "PROJECT_TYPE_UNBOUND": ("BIND",), "SOURCE_BINDING_MISSING": ("BIND",),
    "EXACT_EXCERPT_MISMATCH": ("SEGMENT", "EXTRACT", "LINK"), "AMBIGUOUS_EXCERPT": ("SEGMENT", "EXTRACT", "LINK"),
    "CROSS_RUN_REFERENCE": ("LINK", "FINALIZE"), "UNKNOWN_TARGET": ("LINK",), "UPSTREAM_MUTATED": ("FINALIZE",),
    "RESULT_LEAKAGE_ATTEMPT": ("EXTRACT", "LINK"), "INVENTED_REQUIREMENT": ("EXTRACT", "APPLICABILITY"),
    "SOURCE_INSTRUCTION_FOLLOWED": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"),
    "PROMPT_LEAK_REDACTED": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"), "MODEL_PROVIDER_MISSING": ("SEGMENT",),
    "MODEL_CALL_BOUND_REACHED": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"),
    "MODEL_RESPONSE_INVALID": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"),
    "MODEL_REFUSED": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"),
    "PARTIAL_MODEL_OUTPUT": ("SEGMENT", "EXTRACT", "APPLICABILITY", "LINK"),
    "EXPERIMENT_BOUND_REACHED": ("SEGMENT",),
}
STAGE_SHORT = {"EXPERIMENT_BIND_INPUTS": "BIND", "EXPERIMENT_SEGMENT": "SEGMENT", "EXPERIMENT_EXTRACT_PROTOCOL": "EXTRACT",
               "EXPERIMENT_RESOLVE_APPLICABILITY": "APPLICABILITY", "EXPERIMENT_LINK_TARGETS": "LINK",
               "EXPERIMENT_SYNTHESIZE": "SYNTHESIZE", "EXPERIMENT_FINALIZE": "FINALIZE"}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def protocol_key_of(texts: list[str]) -> str:
    return digest(json.dumps(texts, ensure_ascii=False))


def strip_times(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_times(v) for k, v in value.items() if k not in ("started_at", "completed_at")}
    if isinstance(value, list):
        return [strip_times(v) for v in value]
    return value


def canonical(d: dict[str, Any]) -> Any:
    """What a run decides, without wall-clock time."""
    return strip_times(d)


def walk(value: Any):
    """Every (key, value) pair in a JSON structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def occurrences(text: str, needle: str) -> list[int]:
    out: list[int] = []
    if not needle:
        return out
    start = 0
    while (i := text.find(needle, start)) != -1:
        out.append(i)
        start = i + 1
    return out


def is_bare_quantity(excerpt: str) -> bool:
    return BARE.match(excerpt) is not None


def tail_of(prompt: str) -> str:
    """The trusted tail: everything after the code's end marker."""
    i = prompt.find(MARKER_END)
    return prompt[i + len(MARKER_END):] if i >= 0 else ""


def marker_lines(prompt: str) -> int:
    """Lines that are exactly a code boundary marker. A forged marker inside a student sentence is not one."""
    return sum(1 for line in prompt.split(chr(10)) if line in CODE_MARKERS)


def untrusted_part(prompt: str) -> str:
    i = prompt.find(MARKER_END)
    return prompt[:i] if i >= 0 else prompt


def adequacy_projection(d: dict[str, Any]) -> Any:
    """What a run decided about protocol adequacy: no ids, offsets, hashes, quarantine or times. Used by the
    result-mutation and prefix twins. Experiments are keyed by their defining text, not by position."""
    texts = {e["excerpt_id"]: e["excerpt"] for e in d["excerpts"]}

    def names(ids: list[str]) -> list[str]:
        return sorted(texts.get(i, "?") for i in ids)

    exps = {}
    for e in d["experiments"]:
        key = "|".join(texts[i] for i in e["defining_excerpt_ids"])
        exps[key] = {"type": e["experiment_type"], "track": e["track"], "posture": e["posture"], "issues": e["issues"],
                     "requirements": [(r["kind"], r["applicability"], r["basis"], r["triggers"], r["documentation"],
                                       r["adequacy"], names(r["excerpt_ids"])) for r in e["requirements"]]}
    owner = {e["experiment_id"]: "|".join(texts[i] for i in e["defining_excerpt_ids"]) for e in d["experiments"]}
    return {"experiments": exps,
            "links": sorted((owner[x["experiment_id"]], x["claim_id"], x["validation_requirement_id"] is None,
                             x["relation"]) for x in d["links"]),
            "measurements": sorted((owner[m["experiment_id"]], m["validation_requirement_id"] is None, m["alignment"],
                                    m["phase2j_metric_match"], m["success_criterion_timing"]) for m in d["measurements"]),
            "baselines": sorted((owner[b["experiment_id"]], b["relevance"], b["phase2j_baseline_match"])
                                for b in d["baselines"]),
            "coverage": [(c["status"], c["reasons"]) for c in d["phase2j_coverage"]],
            "tracks": [(t["track"], t["posture"]) for t in d["track_postures"]],
            "project": d["project_posture"], "status": d["status"]}


@dataclass
class Ctx:
    case: ExperimentGoldCase
    d: dict[str, Any]
    text: str
    claim: str
    upstream: Any = None
    after: Any = None
    model: Any = None
    prompts: list[tuple[str, str]] = field(default_factory=list)
    calls_by_task: dict[str, int] = field(default_factory=dict)
    provider_requests: int = 0
    replay: dict[str, Any] = field(default_factory=dict)
    twins: dict[str, Any] = field(default_factory=dict)
    mutated: dict[str, Any] = field(default_factory=dict)
    network_attempts: int = 0
    legacy_twin: dict[str, Any] = field(default_factory=dict)
    window_override: int | None = None

    # -- structure ---------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self.d["experiment_run_id"]

    @property
    def window_end(self) -> int:
        limit = self.window_override or int(self.d["bounds"]["max_submission_chars"])
        return min(len(self.text), limit)

    @property
    def excerpts(self) -> list[dict[str, Any]]:
        return self.d["excerpts"]

    @property
    def excerpt_by_id(self) -> dict[str, dict[str, Any]]:
        return {e["excerpt_id"]: e for e in self.excerpts}

    @property
    def exps(self) -> list[dict[str, Any]]:
        """Experiments in document order (first defining excerpt)."""
        by_id = self.excerpt_by_id
        return sorted(self.d["experiments"], key=lambda e: (by_id[e["defining_excerpt_ids"][0]]["start"],
                                                            e["experiment_id"]))

    def exp(self, i: int) -> dict[str, Any] | None:
        exps = self.exps
        return exps[i - 1] if 0 < i <= len(exps) else None

    def req(self, e: dict[str, Any], kind: str) -> dict[str, Any] | None:
        return next((r for r in e["requirements"] if r["kind"] == kind), None)

    def links_of(self, e: dict[str, Any]) -> list[dict[str, Any]]:
        return [x for x in self.d["links"] if x["experiment_id"] == e["experiment_id"]]

    def link_for(self, e: dict[str, Any], label: str) -> dict[str, Any] | None:
        want_req = label.startswith("V")
        return next((x for x in self.links_of(e) if (x["validation_requirement_id"] is not None) == want_req), None)

    def meas_for(self, e: dict[str, Any], label: str) -> dict[str, Any] | None:
        want_req = label.startswith("V")
        return next((m for m in self.d["measurements"] if m["experiment_id"] == e["experiment_id"]
                     and (m["validation_requirement_id"] is not None) == want_req), None)

    def baseline_for(self, e: dict[str, Any], label: str) -> dict[str, Any] | None:
        want_req = label.startswith("V")
        return next((b for b in self.d["baselines"] if b["experiment_id"] == e["experiment_id"]
                     and (b["validation_requirement_id"] is not None) == want_req), None)

    def conds_of(self, e: dict[str, Any]) -> list[dict[str, Any]]:
        return [c for c in self.d["conditions"] if c["experiment_id"] == e["experiment_id"]]

    def cov(self, label: str) -> dict[str, Any] | None:
        covs = self.d["phase2j_coverage"]
        return covs[int(label[1:]) - 1] if label[1:].isdigit() and 0 < int(label[1:]) <= len(covs) else None

    @property
    def targets(self) -> list[dict[str, Any]]:
        return self.d["bound_validation_targets"]

    @property
    def tracks(self) -> list[str]:
        return self.d["tracks"]

    def quarantine_texts(self) -> list[str]:
        return [self.text[q["start"]:q["end"]] for q in self.d["quarantine"]]

    def output_text(self) -> str:
        return json.dumps(self.d, ensure_ascii=False, default=str)

    def all_prompts(self) -> list[str]:
        return [p for _, p in self.prompts]

    def later_prompts(self) -> list[str]:
        return [p for t, p in self.prompts if t != TASK_NAMES["segment"]]

    @property
    def flags(self) -> dict[str, Any]:
        return self.case.flags

    @property
    def completed(self) -> bool:
        return self.d["status"] == "COMPLETED"

    @property
    def project_type(self) -> str:
        return self.case.project_type

    @property
    def expected_tracks(self) -> list[str]:
        return cat.PROJECT_TRACKS[self.case.project_type]


# -- independent derivations (re-implemented from the contract) ------------------------------------------------


def _aligned_targets(ms: list[dict[str, Any]]) -> set[tuple]:
    return {(m["target_claim_id"], m["gap_hypothesis_id"], m["validation_requirement_id"]) for m in ms
            if m["alignment"] == "ALIGNED_SAME_TARGET"}


def derive_issues(e: dict[str, Any], ms: list[dict[str, Any]], bs: list[dict[str, Any]],
                  links: list[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()
    for r in e["requirements"]:
        if r["documentation"] == "CONFLICTING_DOCUMENTATION":
            codes.add("CONFLICTING_PROTOCOL_DESCRIPTION")
        if r["applicability"] == "REQUIRED" and r["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT":
            codes.add(cat.missing_issue(r["kind"]))
        if r["applicability"] != "NOT_APPLICABLE" and r["adequacy"] == "PROTOCOL_RISK_IDENTIFIED":
            codes.add("PROTOCOL_RISK_IDENTIFIED")
    for m in ms:
        if m["alignment"] == "METRIC_TARGET_MISMATCH":
            codes.add("METRIC_TARGET_MISMATCH")
        if m["success_criterion_timing"] == "POST_HOC_AS_DESCRIBED":
            codes.add("SUCCESS_CRITERION_POST_HOC")
    for b in bs:
        if b["relevance"] == "NOT_RELEVANT_TO_TARGET":
            codes.add("BASELINE_NOT_RELEVANT")
        if b["baseline_excerpt_ids"] and any(p["status"] == "DOCUMENTED_DIFFERENT" for p in b["comparability"]):
            codes.add("BASELINE_COMPARABILITY_GAP")
    if links and all(x["relation"] == "DOES_NOT_TEST" for x in links):
        codes.add("EXPERIMENT_DOES_NOT_TEST_TARGET")
    return sorted(codes)


def derive_exp_posture(e: dict[str, Any], issues: list[str], ms: list[dict[str, Any]],
                       links: list[dict[str, Any]]) -> str:
    applicable = [r for r in e["requirements"] if r["applicability"] != "NOT_APPLICABLE"]
    if not applicable or all(r["documentation"] == "INSUFFICIENT_SOURCE_COVERAGE" for r in applicable):
        return "INSUFFICIENT_EVIDENCE"
    if any(cat.is_major(i) for i in issues):
        return "MAJOR_GAPS"
    if (e["experiment_type"] == "UNKNOWN" or any(r["applicability"] == "CONDITIONAL" for r in e["requirements"])
            or not links or all(x["relation"] == "UNRESOLVED" for x in links)):
        return "UNRESOLVED"
    aligned = _aligned_targets(ms)
    tested = any(x["relation"] == "DIRECTLY_TESTS"
                 and (x["claim_id"], x["gap_hypothesis_id"], x["validation_requirement_id"]) in aligned for x in links)
    if issues or not tested or any(r["applicability"] == "REQUIRED" and r["adequacy"] != "ADEQUATELY_SPECIFIED_FOR_REVIEW"
                                   for r in e["requirements"]):
        return "PARTIALLY_SPECIFIED"
    return "WELL_SPECIFIED"


def exp_records(d: dict[str, Any], e: dict[str, Any]):
    eid = e["experiment_id"]
    return ([m for m in d["measurements"] if m["experiment_id"] == eid],
            [b for b in d["baselines"] if b["experiment_id"] == eid],
            [x for x in d["links"] if x["experiment_id"] == eid])


def single_experiment_covers(d: dict[str, Any], target: dict[str, Any], e: dict[str, Any]) -> tuple[bool, set[str]]:
    """Does ONE experiment satisfy every dimension of the Phase 2J requirement? Returns (covers, missing reasons)."""
    req = target["validation_requirement_id"]
    ms, bs, links = exp_records(d, e)
    own = [x for x in links if x["validation_requirement_id"] == req]
    missing: set[str] = set()
    if not any(x["relation"] == "DIRECTLY_TESTS" for x in own):
        missing.add("PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED")
    if not any(m["validation_requirement_id"] == req and m["alignment"] == "ALIGNED_SAME_TARGET"
               and m["phase2j_metric_match"] == "SAME_AS_PHASE_2J" for m in ms):
        missing.add("METRIC_TARGET_MISMATCH")
    if target["baseline_anchor_hash"] is not None and not any(
            b["validation_requirement_id"] == req and b["relevance"] == "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT"
            and b["phase2j_baseline_match"] == "SAME_AS_PHASE_2J" for b in bs):
        missing.add("BASELINE_TARGET_MISMATCH")
    addressed = {c["condition_id"] for c in d["conditions"] if c["experiment_id"] == e["experiment_id"]
                 and c["validation_requirement_id"] == req and c["status"] == "ADDRESSED_IN_PROTOCOL"}
    if set(target["condition_ids"]) - addressed:
        missing.add("MATERIAL_CONDITION_UNCOVERED")
    if e["posture"] not in ("WELL_SPECIFIED", "PARTIALLY_SPECIFIED"):
        missing.add("COVERING_PROTOCOL_INADEQUATE")
    return not missing, missing


def derive_coverage(d: dict[str, Any], target: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    req = target["validation_requirement_id"]
    own = [x for x in d["links"] if x["validation_requirement_id"] == req]
    testing = sorted({x["experiment_id"] for x in own if x["relation"] in cat.TESTING})
    if not testing:
        if any(x["relation"] == "UNRESOLVED" for x in own):
            return "UNRESOLVED", [], ["LINKAGE_UNRESOLVED"]
        return "NOT_COVERED", [], ["PHASE2J_VALIDATION_REQUIREMENT_UNCOVERED"]
    exps = {e["experiment_id"]: e for e in d["experiments"]}
    covering: list[str] = []
    reasons: set[str] = set()
    for eid in testing:
        ok, missing = single_experiment_covers(d, target, exps[eid])
        if ok:
            covering.append(eid)
        else:
            reasons |= missing
    if covering:
        return "COVERED_BY_EXPERIMENT", covering, []
    return "PARTIALLY_COVERED", [], sorted(reasons)


def coverage_owner(target: dict[str, Any], tracks: list[str]) -> str | None:
    if len(tracks) == 1:
        return tracks[0]
    owners = {cat.FACET_TRACK[f] for f in target["limitation_facets"]}
    return next(iter(owners)) if len(owners) == 1 else None


def derive_track_posture(d: dict[str, Any], track: str) -> str:
    exps = [e for e in d["experiments"] if e["track"] == track and e["requirements"]]
    targets = {t["validation_requirement_id"]: t for t in d["bound_validation_targets"]}
    members = [e["posture"] for e in exps]
    for c in d["phase2j_coverage"]:
        if coverage_owner(targets[c["validation_requirement_id"]], d["tracks"]) == track:
            members.append(cat.COVERAGE_POSTURE[c["status"]])
    return cat.worst(members) if members else "INSUFFICIENT_EVIDENCE"


def derive_project_posture(d: dict[str, Any]) -> str:
    tracks = [derive_track_posture(d, t) for t in d["tracks"]]
    if not tracks:
        return "INSUFFICIENT_EVIDENCE"
    targets = {t["validation_requirement_id"]: t for t in d["bound_validation_targets"]}
    members = list(tracks)
    for c in d["phase2j_coverage"]:
        if coverage_owner(targets[c["validation_requirement_id"]], d["tracks"]) is None:
            members.append(cat.COVERAGE_POSTURE[c["status"]])
    posture = cat.worst(members)
    if any(e["track"] is None for e in d["experiments"]):
        posture = cat.worst([posture, "UNRESOLVED"])
    tested = {x["claim_id"] for x in d["links"] if x["relation"] in cat.TESTING}
    if {c["claim_id"] for c in d["bound_claims"]} - tested:
        posture = cat.worst([posture, "PARTIALLY_SPECIFIED"])
    return posture


__all__ = [name for name in dir() if not name.startswith("_")]
