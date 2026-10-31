"""Phase 3A Gold generator -> evals/methodology_review/v1/cases.jsonl.

AUTHORING INDEPENDENCE: this file imports NOTHING from the Phase 3A production modules (src.research.methodology,
src.schemas.methodology_review, src.graph.methodology_nodes, src.graph.phase3a_graph) and nothing that runs the
system (the Gold world, runner, quality, gates, controls). Every expectation below is authored from the approved
specification and from each case's own submission text; it is never produced by running the system. The only
shared table is the Gold-side policy catalog (src/evals/methodology_review/catalog.py), itself hand-transcribed
from the specification.

A case keeps four things apart: the authoritative INPUT (project type, submission), the SCRIPTED model response
(which may be wrong or hostile on purpose), the EXPECTED deterministic behaviour given that response, and the
TRUTH (the model-judgment ground truth, which a seeded wrong judgment is allowed to contradict).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase3a_gold_lang import BANK, CLAIM_SUFFIX_INJECTION, IDX, LANGS  # noqa: E402

from src.evals.methodology_review import catalog as cat  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "evals" / "methodology_review" / "v1" / "cases.jsonl"
R, E = "SCIENTIFIC_RESEARCH", "ENGINEERING"
PTYPE = {"R": "SCIENTIFIC_RESEARCH", "E": "ENGINEERING_PROJECT", "H": "HYBRID"}
TRACKS = {"R": [R], "E": [E], "H": [R, E]}
OVERLAYS = ("AI_ML", "SOFTWARE_SYSTEMS")
OVERLAY_DOMAIN = {"AI_ML": "MACHINE_LEARNING", "SOFTWARE_SYSTEMS": "SOFTWARE_ENGINEERING"}
AI_REQUIRED = [("DATA_SOURCE", "DSRC"), ("DATASET_SCOPE_SIZE", "DSIZE"), ("LABELS", "LABELS"), ("LABELING_METHOD", "LABELING"),
               ("TRAIN_SPLIT", "TRAIN"), ("TEST_SPLIT", "TEST"), ("DATA_LEAKAGE_PREVENTION", "LEAK"),
               ("TEST_SET_ISOLATION_FROM_TUNING", "ISOL"), ("EVALUATION_METRICS", "EVALM"), ("GENERALIZATION_PLAN", "GEN")]
ENG_REQUIRED = [("DESIGN_OBJECTIVE", "OBJ"), ("REQUIREMENTS", "REQS"), ("ARCHITECTURE_SUBSYSTEM_PLAN", "ARCH"),
                ("VERIFICATION_PLAN", "VERIF"), ("VALIDATION_PLAN", "VALID"), ("MEASUREMENT_PLAN", "MEAS"),
                ("ACCEPTANCE_CRITERIA", "ACCEPT")]
RES_REQUIRED = [("RESEARCH_QUESTION", "RQ"), ("DEPENDENT_VARIABLE", "DV"), ("OPERATIONAL_DEFINITIONS", "OPDEF"),
                ("SAMPLE", "SAMPLE"), ("STUDY_DESIGN", "RDESIGN"), ("DATA_COLLECTION_METHOD", "COLLECT"),
                ("MEASUREMENT_METHOD", "RMEAS"), ("EXTERNAL_VALIDITY_BOUNDARIES", "EXT")]
# the issue code a REQUIRED requirement absent from the bound input raises (specification section 26)
MISSING_CODE = {
    "SAMPLE_SIZE_RATIONALE": "SAMPLE_RATIONALE_NOT_DOCUMENTED", "CONTROL_OR_COMPARISON_GROUP": "CONTROL_STRATEGY_NOT_DOCUMENTED",
    "CONFOUNDER_HANDLING": "CONFOUNDER_HANDLING_NOT_DOCUMENTED", "CONTROLLED_VARIABLES": "CONFOUNDER_HANDLING_NOT_DOCUMENTED",
    "TEST_SET_ISOLATION_FROM_TUNING": "TEST_SET_ISOLATION_NOT_DOCUMENTED", "DATA_LEAKAGE_PREVENTION": "DATA_LEAKAGE_RISK",
    "BASELINE_OR_ALTERNATIVE_DESIGN": "BASELINE_NOT_DOCUMENTED", "BASELINE_MODEL": "BASELINE_NOT_DOCUMENTED",
    "EXISTING_ALTERNATIVES_COMPARISON": "BASELINE_NOT_DOCUMENTED", "EVALUATION_METRICS": "METRIC_NOT_DEFINED",
}
MAJOR, PARTIAL, WELL, CONFLICT, INSUFF = (
    "METHODOLOGY_HAS_MAJOR_DESIGN_GAPS", "METHODOLOGY_PARTIALLY_SPECIFIED",
    "METHODOLOGY_WELL_SPECIFIED_WITHIN_BOUND_INPUT", "METHODOLOGY_CONFLICTING", "INSUFFICIENT_INPUT")
ADEQ, PSPEC, RISK = "ADEQUATELY_SPECIFIED_FOR_REVIEW", "PARTIALLY_SPECIFIED", "DESIGN_RISK_IDENTIFIED"
NO_DOC, EXPL, PART = "NOT_DOCUMENTED_IN_BOUND_INPUT", "EXPLICITLY_DOCUMENTED", "PARTIALLY_DOCUMENTED"
DIRECT, PARTIAL_REL = "DIRECTLY_TESTS_TARGET", "PARTIALLY_TESTS_TARGET"


def code_for_missing(kind: str) -> str:
    return MISSING_CODE.get(kind, "REQUIRED_COMPONENT_NOT_DOCUMENTED")


class C:
    """One Gold case under construction."""

    def __init__(self, lang: str, ptype: str, tag: str, *, domains=(), gap="default", claim="base", cats=()):
        self.lang, self.pt, self.tag = lang, ptype, tag
        self.tracks = TRACKS[ptype]
        self.domains, self.gap, self.claim = list(domains), gap, claim
        self.cats = [tag, *cats]
        self.docs: dict[str, dict] = {}
        self.extra: list[str] = []
        self.fired: dict[str, list[str]] = {}
        self.script: dict = {"overlay": {}, "evidence": {}, "applicability": {}, "metric": {}, "baseline": {}, "link": {},
                             "conditions": {}}
        self.exp: dict = {}
        self.truth: dict = {}
        self.flags: dict = {}
        self.extra_fields: dict = {}
        self.owned: dict[str, str | None] = {}  # active overlay -> owning track (None: unresolved)
        self.skip_auto: set[str] = set()
        self.desc = ""
        self.link_override: dict = {}
        self.tkey: str | None = None
        self.skip_app = False
        self.dupes: list[str] = []
        self.span_override: dict = {}

    # -- text ------------------------------------------------------------------------
    def s(self, key: str) -> str:
        return BANK[key][IDX[self.lang]]

    # -- documentation ----------------------------------------------------------------
    def doc(self, kind: str, *keys: str, documentation=EXPL, adequacy=ADEQ, mode="PLANNED", texts=(), ghost=()):
        self.docs[kind] = {"keys": list(keys), "texts": list(texts), "doc": documentation, "adq": adequacy, "mode": mode,
                           "ghost": list(ghost)}

    def drop(self, kind: str) -> None:
        self.docs.pop(kind, None)

    def home(self, kind: str) -> str | None:
        track = cat.HOME_TRACK[kind]
        if track:
            return track
        owner = self.owned.get(cat.OVERLAY_OF[kind])
        return owner

    # -- base documentation by project type ---------------------------------------------
    def base(self) -> C:
        if R in self.tracks:
            for kind, key in RES_REQUIRED:
                self.doc(kind, key)
            if self.gap in ("default", "baseline") and R == self.tracks[0] and len(self.tracks) == 1:
                self.docs["EXTERNAL_VALIDITY_BOUNDARIES"]["keys"] = ["EXT", "RCOND"]
        if E in self.tracks:
            for kind, key in ENG_REQUIRED:
                self.doc(kind, key)
            if self.gap in ("default", "baseline"):
                self.docs["VALIDATION_PLAN"]["keys"] = ["VALID", "COND"]
        if self.gap == "baseline":
            if R in self.tracks and len(self.tracks) == 1:
                self.doc("CONTROL_OR_COMPARISON_GROUP", "CTRL", "BASEL", "BASEL_RAT")
            if E in self.tracks:
                self.doc("BASELINE_OR_ALTERNATIVE_DESIGN", "BASEL", "BASEL_RAT")
        return self

    # -- the gap target's track and links ------------------------------------------------
    @property
    def gtrack(self) -> str:
        return R if self.tracks == [R] else E

    def testing_key(self, track: str) -> str:
        return self.tkey or ("VALID" if track == E else "RDESIGN")

    # -- overlays -----------------------------------------------------------------------
    def material(self, overlay: str, keys, *, owner=None, served=None, hyps=("H1",), claims=("C1",)) -> None:
        self.script["overlay"][overlay] = {
            "materiality": "MATERIAL_TO_TARGET", "claims": list(claims), "hypotheses": list(hyps),
            "excerpts": [self.s(k) for k in keys], "owner_track": owner, "served_tracks": list(served or [])}
        if len(self.tracks) == 1:
            self.owned[overlay] = self.tracks[0]
        elif hyps and owner is None:
            self.owned[overlay] = E  # Phase 2J facet of the default hypothesis is ENGINEERING
        else:
            self.owned[overlay] = owner
        self.flags.setdefault("valid_material", []).append(overlay)

    def tool_only(self, overlay: str, key: str) -> None:
        self.script["overlay"][overlay] = {"materiality": "IMPLEMENTATION_TOOL_ONLY", "excerpts": [self.s(key)]}

    def add_ai_docs(self, drop=()) -> None:
        for kind, key in AI_REQUIRED:
            if kind not in drop:
                self.doc(kind, key)

    # -- assemble -------------------------------------------------------------------------
    def pending(self) -> list[tuple[str, str]]:
        """CONDITIONAL requirements a model must resolve: (kind, track)."""
        out = []
        for kind in sorted(cat.CATALOG):
            track = self.home(kind)
            if track is None or track not in self.tracks or cat.DEFAULT[kind] != "COND":
                continue
            overlay = cat.OVERLAY_OF[kind]
            if overlay != "CORE" and self.owned.get(overlay) is None:
                continue
            if self.det_required(kind):
                continue
            out.append((kind, track))
        return out

    def det_required(self, kind: str) -> bool:
        trig = cat.TRIGGERS[kind]
        return (self.gap == "baseline" and "PHASE_2J_BASELINE_REQUIRED" in trig) or (
            self.gap in ("default", "baseline") and "PHASE_2J_MATERIAL_CONDITION" in trig)

    def anchor_sentence(self) -> str:
        for d in self.docs.values():
            if d["keys"]:
                return self.s(d["keys"][0])
        return self.s("OBJ") if E in self.tracks else self.s("RQ")

    def finish_script(self) -> None:
        sc = self.script
        for kind, d in self.docs.items():
            texts = [self.s(k) for k in d["keys"]] + list(d["texts"]) + list(d["ghost"])
            texts = [self.span_override.get((kind, t), t) for t in texts]
            sc["evidence"][kind] = {"excerpts": texts, "documentation": d["doc"], "adequacy": d["adq"], "mode": d["mode"]}
        anchor = self.anchor_sentence()
        for kind, _track in ([] if self.skip_app else self.pending()):
            if kind not in sc["applicability"]:
                sc["applicability"][kind] = {"fired": self.fired.get(kind, []), "excerpt": anchor}
        out = self.link_override
        if "metric" not in out:
            sc["metric"]["T1"] = {"status": "ALIGNED_WITHIN_BOUND_INPUT", "outcome": self.s("MEAS" if E in self.tracks else "RMEAS"),
                                  "metric": self.s("MEAS_METRIC" if E in self.tracks else "DV_METRIC")}
            if self.gap != "no_requirement":
                sc["metric"]["G1"] = {"status": "ALIGNED_WITHIN_BOUND_INPUT",
                                      "outcome": self.s("MEAS" if E in self.tracks else "RMEAS")}
        if self.gap == "baseline" and "baseline" not in out:
            sc["baseline"]["G1"] = {"baseline": self.s("BASEL"), "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                                    "context": ["PHASE_2J_VALIDATION_BASELINE"], "rationale": self.s("BASEL_RAT")}
        if "link" not in out:
            for track in self.tracks:
                sc["link"].setdefault("T1", {})[track] = {"relation": DIRECT, "excerpts": [self.s(self.testing_key(track))]}
            if True:
                sc["link"].setdefault("G1", {})[self.gtrack] = {"relation": DIRECT, "excerpts": [self.s(self.testing_key(self.gtrack))]}
        if "conditions" not in out and self.gap in ("default", "baseline"):
            sc["conditions"]["G1:1"] = {"status": "ADDRESSED_IN_DESIGN",
                                        "excerpts": [self.s("COND") if E in self.tracks else self.s("RCOND")]}

    def text(self) -> str:
        parts: list[str] = []
        for d in self.docs.values():
            for t in [self.s(k) for k in d["keys"]] + list(d["texts"]):
                if t not in parts:
                    parts.append(t)
        for t in self.extra:
            if t not in parts:
                parts.append(t)
        return " ".join(parts + list(self.dupes))

    def auto_expected(self) -> None:
        """Expectations that follow mechanically from the declared documentation (spec sections 9, 13)."""
        e = self.exp
        e.setdefault("status", "COMPLETED")
        for kind, d in ([] if "docs" in self.skip_auto else self.docs.items()):
            track = self.home(kind)
            if track is None or track not in self.tracks:
                continue
            e.setdefault(f"doc.{track}.{kind}", d["doc"])
            e.setdefault(f"adq.{track}.{kind}", d["adq"])
            if cat.DEFAULT[kind] == "REQ":
                e.setdefault(f"app.{track}.{kind}", "REQUIRED")
        for overlay in OVERLAYS:
            spec = self.script["overlay"].get(overlay)
            if spec is None:
                continue
        for kind, _track in ([] if "pending" in self.skip_auto else self.pending()):
            t = self.home(kind)
            fired = self.fired.get(kind, [])
            e.setdefault(f"app.{t}.{kind}", "REQUIRED" if fired else "NOT_APPLICABLE")

    def build(self, cid: int, *, posture=None, issues=None, **fields) -> dict:
        self.finish_script()
        self.auto_expected()
        if posture is not None:
            for track, p in (posture.items() if isinstance(posture, dict) else [(t, posture) for t in self.tracks]):
                self.exp[f"posture.{track}"] = p
        if issues is not None:
            union: set[str] = set()
            for track, codes in (issues.items() if isinstance(issues, dict) else [(t, issues) for t in self.tracks]):
                self.exp[f"issues.{track}"] = sorted(codes)
                union |= set(codes)
            for code in cat.SEVERITY:
                self.exp[f"has_issue.{code}"] = code in union
        text = self.text()
        flags = {**self.flags}
        case = {
            "case_id": f"GM-{cid:03d}", "language": self.lang, "categories": sorted(set(self.cats)),
            "description": self.desc or self.tag, "project_type": PTYPE[self.pt], "domains": self.domains,
            "gap_variant": self.gap, "claim_variant": self.claim, "submission": text, "script": self.script,
            "bounds": {}, "no_model": False, "results_leak": False, "interrupt_before": None, "rerun": False,
            "twin": None, "mutate": None, "prose": "", "flags": flags, "controls": [], "truth": self.truth,
            "expected": self.exp,
        }
        case.update(fields)
        return case


def lang_name(lang: str) -> str:
    return {"en": "english", "ar": "arabic", "mixed": "mixed"}[lang]


if __name__ == "__main__":
    from phase3a_gold_templates import main

    main()
