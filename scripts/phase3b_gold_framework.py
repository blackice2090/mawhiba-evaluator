"""Phase 3B Gold scenario framework.

AUTHORING INDEPENDENCE: this module imports NOTHING from the Phase 3B production modules
(``src.research.experiments``, ``src.schemas.experiment_review``, the Phase 3B graph) and nothing that runs the
system (the Gold adapter, runner, quality, gates or controls). The only shared table is the Gold-side policy catalog
(``src/evals/experiment_review/catalog.py``), itself hand-transcribed from the specification.

A scenario (``Sc``) assembles a submission from sentences, builds the scripted UNTRUSTED model response from what
the scenario says the model did, and authors the expectations from the scenario's own facts and the catalog.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase3b_gold_lang import kind_text, t  # noqa: E402

from src.evals.experiment_review import catalog as cat  # noqa: E402

CLAIM = "A smart irrigation controller using soil moisture sensors and weather forecasts"
GAPS: dict[str, dict[str, Any]] = {  # authored from the Phase 2J gap variant definitions
    "default": {"req": True, "cond": True, "base": False, "facet": "ENGINEERING"},
    "baseline": {"req": True, "cond": True, "base": True, "facet": "ENGINEERING"},
    "no_condition": {"req": True, "cond": False, "base": False, "facet": "ENGINEERING"},
    "no_requirement": {"req": False, "cond": False, "base": False, "facet": "ENGINEERING"},
}
FLAVOR_TYPE = {"eng": "ENGINEERING_BENCH_TEST", "sci": "SCIENTIFIC_CONTROLLED_EXPERIMENT",
               "obs": "SCIENTIFIC_OBSERVATIONAL_STUDY", "ai": "AI_ML_MODEL_EVALUATION",
               "sw": "SOFTWARE_BENCHMARK", "sim": "SIMULATION", "field": "ENGINEERING_FIELD_TEST",
               "usab": "SOFTWARE_USABILITY_TEST"}
TYPE_FLAVOR = {"SCIENTIFIC_CONTROLLED_EXPERIMENT": "sci", "SCIENTIFIC_OBSERVATIONAL_STUDY": "obs",
               "ENGINEERING_BENCH_TEST": "eng", "ENGINEERING_FIELD_TEST": "field", "ENGINEERING_STRESS_TEST": "eng",
               "ENGINEERING_COMPARATIVE_TEST": "eng", "AI_ML_MODEL_EVALUATION": "ai", "AI_ML_ABLATION": "ai",
               "AI_ML_EXTERNAL_VALIDATION": "ai", "SOFTWARE_BENCHMARK": "sw", "SOFTWARE_LOAD_TEST": "sw",
               "SOFTWARE_SECURITY_TEST": "sw", "SOFTWARE_USABILITY_TEST": "usab", "SIMULATION": "sim",
               "OTHER_BOUNDED_EXPERIMENT": "eng"}
PTYPE_FOR_FAMILY = {"SCIENTIFIC": "SCIENTIFIC_RESEARCH", "ENGINEERING": "ENGINEERING_PROJECT",
                    "AI_ML": "ENGINEERING_PROJECT", "SOFTWARE": "ENGINEERING_PROJECT",
                    "SIMULATION": "ENGINEERING_PROJECT", "OTHER": "ENGINEERING_PROJECT"}
SINGLE_TRACK = {"SCIENTIFIC_RESEARCH": "SCIENTIFIC_RESEARCH", "ENGINEERING_PROJECT": "ENGINEERING"}
RESULT_KIND_DEFAULT = "REPORTED_METRIC_VALUE"
GOOD, ALIGNED = "ADEQUATELY_SPECIFIED_FOR_REVIEW", "ALIGNED_SAME_TARGET"


def post_from(issues: list[str], *, unresolved: bool = False, tested: bool = True, insufficient: bool = False) -> str:
    """The posture an experiment should get from the authored facts (contract section 26)."""
    if insufficient:
        return "INSUFFICIENT_EVIDENCE"
    if any(cat.is_major(i) for i in issues):
        return "MAJOR_GAPS"
    if unresolved:
        return "UNRESOLVED"
    if issues or not tested:
        return "PARTIALLY_SPECIFIED"
    return "WELL_SPECIFIED"


class Exp:
    """One experiment of a scenario: its sentences, what the scripted model said, and what that implies."""

    def __init__(self, sc: "Sc", n: int, flavor: str = "eng", etype: str | None = None, *, missing: tuple[str, ...] = (),
                 fired: dict[str, list[str]] | None = None, define: str | None = None, adequacy: dict[str, str] | None = None,
                 documentation: dict[str, str] | None = None, extra_docs: dict[str, list[str]] | None = None,
                 omit_app: bool = False, execution: str | None = None, v1: str = "DIRECTLY_TESTS") -> None:
        self.sc, self.n = sc, n
        self.type = etype or FLAVOR_TYPE[flavor]
        self.flavor = flavor if etype is None else TYPE_FLAVOR.get(etype, flavor)
        self.define = define or t("DEF_" + self.flavor, sc.lang, n=n)
        self.fired = {k: list(v) for k, v in (fired or {}).items()}
        for k in self.fired:  # only a CONDITIONAL cell is ever asked of the model
            assert cat.cell(k, self.type) == "C", f"{k} is not conditional for {self.type}"
        self.missing = set(missing)
        self.adequacy = adequacy or {}
        self.documentation = documentation or {}
        self.omit_app = omit_app
        self.execution = execution
        self.v1 = v1  # the relation the scripted model gives the Phase 2J requirement
        self.link: dict[str, Any] | None = None  # scripted link section (None: default)
        self.extract_extra: dict[str, Any] = {}
        self.link_state: dict[str, Any] = {"T1": ("DIRECTLY_TESTS", True), "V1": (v1, True)}
        self.meas_issue: list[str] = []
        self.extra_issues: list[str] = []
        self.unresolved = False
        self.tested = True
        facts = GAPS[sc.gap]
        testing_v = facts["req"] and v1 in cat.TESTING
        p2j: list[str] = []
        if testing_v and facts["cond"]:
            p2j.append("PHASE_2J_MATERIAL_CONDITION")
        if testing_v and facts["base"]:
            p2j.append("PHASE_2J_BASELINE_REQUIRED")
        self.p2j = tuple(p2j)
        self.required = cat.required_kinds(self.type, self.fired, self.p2j)
        self.docs: dict[str, list[str]] = {}
        for k in self.required:
            if k not in self.missing:
                self.docs[k] = [kind_text(k, sc.lang, n if sc.tagged else None)]
        for k, texts in (extra_docs or {}).items():
            self.docs[k] = texts
        self.app_override: dict[str, Any] | None = None
        self.raw_reqs: dict[str, Any] = {}
        self.inadequate = False
        degraded = bool({"METRIC", "MEASUREMENT_METHOD"} & self.missing)
        if degraded:  # a measurement without a method or a metric is never aligned, so DIRECTLY_TESTS is reduced
            self.link_state["T1"] = ("PARTIALLY_TESTS", False)
            self.link_state["V1"] = ("PARTIALLY_TESTS" if v1 == "DIRECTLY_TESTS" else v1, False)
            self.tested = False
        sc.parts.append(self.define)
        for k, texts in self.docs.items():
            for text in texts:
                if text not in sc.parts:
                    sc.parts.append(text)

    # -- helpers -----------------------------------------------------------------------

    def replace_doc(self, kind: str, new: str) -> None:
        """Documenting sentence of ``kind`` becomes ``new`` (in the submission and in the script)."""
        old = self.docs[kind][0]
        idx = self.sc.parts.index(old)
        self.sc.parts[idx] = new
        self.docs[kind] = [new]

    def text(self, kind: str) -> str | None:
        return self.docs[kind][0] if kind in self.docs else None

    def measured(self, **over: Any) -> dict[str, Any]:
        m = {"method": self.text("MEASUREMENT_METHOD"), "metric": self.text("METRIC"),
             "criterion": self.text("SUCCESS_CRITERION")}
        m = {k: v for k, v in m.items() if v is not None}
        m.update(over)
        return {k: v for k, v in m.items() if v is not None}

    def default_link(self) -> dict[str, Any]:
        facts = GAPS[self.sc.gap]
        targets: dict[str, Any] = {"T1": {"relation": "DIRECTLY_TESTS", "excerpts": [self.define],
                                          "measurement": self.measured()}}
        conditions: dict[str, Any] = {}
        if facts["req"]:
            targets["V1"] = {"relation": self.v1, "excerpts": [self.define], "measurement": self.measured()}
            if facts["base"] and self.text("BASELINE"):
                targets["V1"]["baseline"] = {
                    "excerpts": [self.text("BASELINE")], "relevance": "RELEVANT_TO_TARGET_WITHIN_BOUND_CONTEXT",
                    "context": ["PHASE_2J_VALIDATION_BASELINE"], "match": "SAME_AS_PHASE_2J"}
            if facts["cond"] and self.text("OPERATING_CONDITIONS"):
                conditions["K1"] = {"status": "ADDRESSED_IN_PROTOCOL", "excerpts": [self.text("OPERATING_CONDITIONS")]}
        return {"targets": targets, "conditions": conditions}

    # -- authored expectations ---------------------------------------------------------

    def issues(self) -> list[str]:
        out = {cat.missing_issue(k) for k in self.required if k not in self.docs}
        out |= set(self.meas_issue) | set(self.extra_issues)
        return sorted(out)

    def posture(self) -> str:
        return post_from(self.issues(), unresolved=self.unresolved or self.omit_app,
                         tested=self.tested and not self.inadequate)

    def covers_v1(self) -> bool:
        """Does this one experiment satisfy every dimension of the Phase 2J requirement (authored)?"""
        facts = GAPS[self.sc.gap]
        if not facts["req"]:
            return False
        rel, aligned = self.link_state["V1"]
        if rel != "DIRECTLY_TESTS" or not aligned or not self.link_state.get("match_ok", True):
            return False
        if facts["base"] and (self.text("BASELINE") is None or not self.link_state.get("baseline_ok", True)):
            return False
        if facts["cond"] and (self.text("OPERATING_CONDITIONS") is None or not self.link_state.get("cond_ok", True)):
            return False
        return self.posture() in ("WELL_SPECIFIED", "PARTIALLY_SPECIFIED")


class Sc:
    """A scenario: ordered submission sentences, scripted model sections, authored facts and expectations."""

    def __init__(self, lang: str, ptype: str = "ENGINEERING_PROJECT", gap: str = "default", claim: str | None = None,
                 tagged: bool = False):
        self.lang, self.ptype, self.gap, self.tagged = lang, ptype, gap, tagged
        self.claim = claim or CLAIM
        self.parts: list[str] = []
        self.exps: list[Exp] = []
        self.results: list[dict[str, Any]] = []
        self.declared: list[dict[str, Any]] = []
        self.script: dict[str, Any] = {}
        self.flags: dict[str, Any] = {}
        self.expected: dict[str, Any] = {}
        self.truth: dict[str, Any] = {}
        self.bounds: dict[str, Any] = {}
        self.extra: dict[str, Any] = {}
        self.segment_override: Any = None
        self.notes = ""
        self.domains: list[str] = []
        self.seg_extra: list[dict[str, Any]] = []
        self.extra_declared: list[tuple[str, str]] = []

    # -- composition -------------------------------------------------------------------

    def say(self, text: str) -> str:
        self.parts.append(text)
        return text

    def exp(self, flavor: str = "eng", etype: str | None = None, **kw: Any) -> Exp:
        e = Exp(self, len(self.exps) + 1, flavor, etype, **kw)
        self.exps.append(e)
        return e

    def result(self, sid: str, kind: str = RESULT_KIND_DEFAULT, *, declare: bool = True, text: str | None = None) -> str:
        sentence = text if text is not None else t(sid, self.lang)
        self.parts.append(sentence)
        self.results.append({"text": sentence, "kind": kind, "declared": declare})
        return sentence

    @property
    def submission(self) -> str:
        return " ".join(self.parts)

    def facts(self) -> dict[str, Any]:
        return GAPS[self.gap]

    # -- the scripted model ------------------------------------------------------------

    def build_script(self) -> dict[str, Any]:
        if self.segment_override is not None:
            seg = self.segment_override
        else:
            seg = {"experiments": [{"label": f"X{e.n}", "excerpts": [e.define]} for e in self.exps] + self.seg_extra,
                   "results": self._declared_specs()}
        extract: dict[str, Any] = {}
        app: dict[str, Any] = {}
        link: dict[str, Any] = {}
        for e in self.exps:
            reqs = {k: {"excerpts": list(texts), **({"adequacy": e.adequacy[k]} if k in e.adequacy else {}),
                        **({"documentation": e.documentation[k]} if k in e.documentation else {})}
                    for k, texts in e.docs.items()}
            reqs.update(copy.deepcopy(e.raw_reqs))
            spec: dict[str, Any] = {"type": e.type, "requirements": reqs}
            if e.execution:
                spec["execution"] = e.execution
            spec.update(e.extract_extra)
            extract[e.define] = spec
            if e.app_override is not None:
                app[e.define] = e.app_override
            elif e.fired:
                app[e.define] = {k: {"fired": v, "excerpts": ["E1"]} for k, v in e.fired.items()}
            link[e.define] = e.link if e.link is not None else e.default_link()
        out: dict[str, Any] = {"segment": seg, "extract": extract, "applicability": app, "link": link}
        if any(e.omit_app for e in self.exps):
            out["applicability_omit"] = True
        out.update(copy.deepcopy(self.script))
        return out

    def _declared_specs(self) -> list[dict[str, Any]]:
        seen, out = set(), []
        for r in self.results:
            if r["declared"] and r["text"] not in seen:
                seen.add(r["text"])
                out.append({"kind": r["kind"], "span": r["text"]})
        for text, kind in self.extra_declared:
            if text not in seen:
                seen.add(text)
                out.append({"kind": kind, "span": text})
        return out

    # -- expectations ------------------------------------------------------------------

    def expect(self, **kw: Any) -> None:
        self.expected.update({k.replace("__", "."): v for k, v in kw.items()})

    def standard_expectations(self) -> None:
        """Type, posture and issues of each experiment, the call count, the Phase 2J coverage and the roll-up."""
        postures = []
        for e in self.exps:
            self.expected.setdefault(f"x{e.n}.type", e.type)
            self.expected.setdefault(f"x{e.n}.posture", e.posture())
            self.expected.setdefault(f"x{e.n}.issues", e.issues())
            postures.append(e.posture())
        facts = self.facts()
        cov = None
        if facts["req"] and self.exps:
            if any(e.covers_v1() for e in self.exps):
                cov = "COVERED_BY_EXPERIMENT"
            elif any(e.link_state["V1"][0] in cat.TESTING for e in self.exps):
                cov = "PARTIALLY_COVERED"
            elif any(e.link_state["V1"][0] == "UNRESOLVED" for e in self.exps):
                cov = "UNRESOLVED"
            else:
                cov = "NOT_COVERED"
            self.expected.setdefault("cov.V1", cov)
        self.expected.setdefault("status", "COMPLETED")
        if self.ptype != "HYBRID" and self.exps:
            members = list(postures) + ([cat.COVERAGE_POSTURE[cov]] if cov else [])
            track = cat.worst(members)
            tested = any(e.link_state["T1"][0] in cat.TESTING or e.link_state["V1"][0] in cat.TESTING
                         for e in self.exps)
            self.expected.setdefault("track." + SINGLE_TRACK[self.ptype], track)
            self.expected.setdefault("posture", track if tested else cat.worst([track, "PARTIALLY_SPECIFIED"]))
        self.expected.setdefault("calls", self.calls())

    def calls(self) -> int:
        n = 1
        for e in self.exps:
            n += 1  # extraction
            if e.type != "UNKNOWN":
                n += 1  # applicability (every known type has a pending conditional row with a model trigger)
            n += 1  # linkage
        return n

    # -- output ------------------------------------------------------------------------

    def flag_results(self) -> None:
        true = list(dict.fromkeys(r["text"] for r in self.results))
        self.flags["results"] = true
        self.flags["result_kinds"] = {r["text"]: r["kind"] for r in self.results}
        self.flags["declared_results"] = [s["span"] for s in self._declared_specs()]
        self.flags["protocol"] = [p for p in dict.fromkeys(self.parts) if p not in set(true)]
        self.truth.setdefault("results", true)
        # model-judgment ground truth, authored from what each scenario's text says; a family overrides it
        self.truth.setdefault("experiments", [e.define for e in self.exps])
        self.truth.setdefault("types", {str(e.n): e.type for e in self.exps if cat.TYPE_FAMILY.get(e.type)})
        plain = [e for e in self.exps if e.link is None and not e.link_state.get("match_ok") is False]
        if len(self.exps) == 1 and plain and "METRIC" in plain[0].docs and "MEASUREMENT_METHOD" in plain[0].docs:
            facts = GAPS[self.gap]
            self.truth.setdefault("alignment", {"T1": ALIGNED, **({"V1": ALIGNED} if facts["req"] else {})})
            self.truth.setdefault("links", {"T1": "DIRECTLY_TESTS", **({"V1": plain[0].v1} if facts["req"] else {})})

    def finish(self, *, standard: bool = True, **extra: Any) -> dict[str, Any]:
        self.flag_results()
        if standard:
            self.standard_expectations()
        script = self.build_script()
        case = {"project_type": self.ptype, "submission": self.submission,
                "claims": [{"claim_id": "C-001", "claim": self.claim}],
                "phase2j_world": {"gap_variant": self.gap, "domains": list(self.domains)},
                "phase3a_context": {"provider": "none", "note": "Phase 3A is run without a model; context only"},
                "model_script": script, "bounds": dict(self.bounds), "flags": dict(self.flags),
                "truth": dict(self.truth), "expected": dict(self.expected), "notes": self.notes}
        case.update(self.extra)
        case.update(extra)
        return case


# -- the family registry ---------------------------------------------------------------------------------------

LANGS = ("en", "ar", "mixed")
REGISTRY: list[tuple[str, str, tuple[str, ...], Any]] = []


def family(fid: str, category: str, langs: tuple[str, ...] = LANGS):
    """Register a scenario family: ``fn(lang)`` returns the body of one case. Translations of one scenario share
    the family id, which is the language-neutral semantic identity."""
    def register(fn):
        assert all(f != fid for f, *_ in REGISTRY), fid
        REGISTRY.append((fid, category, tuple(langs), fn))
        return fn

    return register
