"""The per-case evaluation context: the serialized Phase 3A run, the upstream records, and independent readers.

Everything here reads the run as a plain JSON dict. It never calls a Phase 3A validator, synthesis or
derivation function: the scorer re-implements the policy rules from ``catalog.py`` so a defect in production
cannot also be the definition of "correct".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from src.evals.methodology_review import catalog as cat
from src.evals.methodology_review.dataset import MethodGoldCase


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


@dataclass
class Ctx:
    case: MethodGoldCase
    d: dict[str, Any]                       # the serialized MethodologyReviewRun
    text: str                               # the verbatim bound submission ("" when none)
    claim: str                              # the canonical claim text
    upstream: Any                           # state before Phase 3A
    after: Any = None
    model: Any = None
    prompts: str = ""                       # every user input the model was shown
    calls_by_task: dict[str, int] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    twins: dict[str, Any] = field(default_factory=dict)
    mutated: dict[str, Any] = field(default_factory=dict)
    results_twin: dict[str, Any] = field(default_factory=dict)
    network_attempts: int = 0
    project_unchanged: bool = True
    controls: dict[str, tuple[int, int]] = field(default_factory=dict)

    # -- structure ---------------------------------------------------------------------

    @property
    def tracks(self) -> list[dict[str, Any]]:
        return self.d["track_assessments"]

    def track(self, name: str) -> dict[str, Any] | None:
        return next((t for t in self.tracks if t["track"] == name), None)

    @property
    def excerpts(self) -> list[dict[str, Any]]:
        return self.d["excerpts"]

    @property
    def excerpt_by_id(self) -> dict[str, dict[str, Any]]:
        return {e["excerpt_id"]: e for e in self.excerpts}

    @property
    def overlays(self) -> dict[str, dict[str, Any]]:
        return {o["overlay"]: o for o in self.d["overlays"]}

    @property
    def gap_targets(self) -> list[dict[str, Any]]:
        return self.d["bound_gap_targets"]

    def all_docs(self):
        return [(t["track"], x) for t in self.tracks for x in t["documentation"]]

    def all_apps(self):
        return [(t["track"], x) for t in self.tracks for x in t["applicability"]]

    def all_links(self):
        return [(t["track"], x) for t in self.tracks for x in t["coverage"]]

    def all_conditions(self):
        return [(t["track"], x) for t in self.tracks for x in t["conditions"]]

    def all_issues(self):
        return [(t["track"], x) for t in self.tracks for x in t["issues"]]

    def children(self) -> list[dict[str, Any]]:
        """Every record (at any depth, inside lists too) that carries a methodology_run_id."""
        out: list[dict[str, Any]] = []

        def collect(node: Any) -> None:
            if isinstance(node, dict):
                if "methodology_run_id" in node:
                    out.append(node)
                for v in node.values():
                    collect(v)
            elif isinstance(node, list):
                for v in node:
                    collect(v)

        collect(self.d)
        return out

    def is_terminal_completed(self) -> bool:
        return self.d["status"] == "COMPLETED"

    @property
    def injected(self) -> bool:
        return bool(self.case.flags.get("attack"))

    def scripted_mode(self, excerpt: str) -> str | None:
        """The statement mode the script assigned to an excerpt of this exact text (None: not scripted)."""
        for spec in self.case.script.get("evidence", {}).values():
            for e in spec.get("excerpts", []):
                if (e["excerpt"] if isinstance(e, dict) else e) == excerpt:
                    return spec.get("mode", "PLANNED")
        return None

    def output_text(self) -> str:
        """The whole serialized run, for leak scans."""
        import json

        return json.dumps(self.d, ensure_ascii=False, default=str)


# -- independent posture derivation (re-implemented from the specification) ---------------------------


def derive_posture(ta: dict[str, Any]) -> str:
    if not ta["inputs_bound"]:
        return cat.POSTURE_INSUFFICIENT
    required = {a["kind"] for a in ta["applicability"] if a["applicability"] == "REQUIRED"}
    docs = {x["kind"]: x for x in ta["documentation"]}
    req_docs = [docs[k] for k in required if k in docs]
    if required and len(req_docs) == len(required) and all(
            x["documentation"] == "INSUFFICIENT_SOURCE_COVERAGE" for x in req_docs):
        return cat.POSTURE_INSUFFICIENT
    issues = ta["issues"]
    if any(i["code"] == "CONFLICTING_METHOD_DESCRIPTION" for i in issues) or any(
            x["documentation"] == "CONFLICTING_DOCUMENTATION" for x in req_docs):
        return cat.POSTURE_CONFLICT
    if (any(cat.SEVERITY[i["code"]] in cat.MAJOR_SEVERITIES for i in issues) or any(k not in docs for k in required)
            or any(x["documentation"] == "NOT_DOCUMENTED_IN_BOUND_INPUT" for x in req_docs)):
        return cat.POSTURE_MAJOR
    well = (not issues and all(x["adequacy"] == "ADEQUATELY_SPECIFIED_FOR_REVIEW" for x in req_docs)
            and not any(a["applicability"] == "CONDITIONAL" for a in ta["applicability"])
            and bool(ta["coverage"]) and all(c["relation"] in cat.STRONG for c in ta["coverage"])
            and all(c["status"] == "ADDRESSED_IN_DESIGN" for c in ta["conditions"]))
    posture = cat.POSTURE_WELL if well else cat.POSTURE_PARTIAL
    if ta.get("overlay_blocked") and posture == cat.POSTURE_WELL:
        posture = cat.POSTURE_PARTIAL
    return posture


_BARE = re.compile(r"[\s\W\d_]*[nN]?[\s\W\d_]*")


def is_bare_quantity(excerpt: str) -> bool:
    """No word other than an optional lone n: "N = 500", "500", "(n=30)" carry no rationale."""
    return _BARE.fullmatch(excerpt) is not None


def occurrences(text: str, needle: str) -> int:
    n = start = 0
    while (i := text.find(needle, start)) != -1:
        n += 1
        start = i + 1
    return n


__all__ = ["Ctx", "canonical", "derive_posture", "digest", "is_bare_quantity", "occurrences", "strip_times", "walk"]
