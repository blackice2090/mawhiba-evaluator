"""Phase 3A Gold runner: drives each case through the REAL upstream graphs and the REAL Phase 3A graph
(scripted untrusted model, no network), then reads the serialized run independently and compares it with the
AUTHORED expectations.

The reader (``read``) looks at the run as a plain JSON dict. It never calls a Phase 3A validator, synthesis
or derivation function."""

from __future__ import annotations

import socket
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from src.evals.methodology_review import context as c
from src.evals.methodology_review.context import Ctx
from src.evals.methodology_review.dataset import MethodGoldCase
from src.evals.methodology_review.world import (
    ScriptedMethodologyModel,
    claim_text,
    phase2j_world,
    reorder,
    run_phase3a,
    run_stages,
    with_prose,
    with_submission,
)
from src.llm.contracts import ModelTask
from src.schemas.common import Tracked
from src.schemas.methodology_review import MethodologyReviewBounds
from src.schemas.project import ExperimentRecord, ResultRecord
from src.schemas.submission import StudentSubmissionArtifact

RESULT_TEXT = "SUCCESS-98.7-PERCENT-ACCURACY-PASSED-ALL-BENCHMARKS"
"""A marker no submission, claim or script contains: if it reaches a prompt or an output, a result leaked."""

TASK_KEY = {
    "overlay": ModelTask.METHODOLOGY_OVERLAY_ASSESSMENT, "evidence": ModelTask.METHODOLOGY_EVIDENCE_EXTRACTION,
    "applicability": ModelTask.METHODOLOGY_APPLICABILITY, "metric": ModelTask.METHODOLOGY_METRIC_BASELINE,
    "link": ModelTask.METHODOLOGY_TARGET_LINKAGE,
}


@dataclass
class CaseResult:
    case: MethodGoldCase
    quality: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    gates: dict[str, tuple[int, int]] = field(default_factory=dict)
    controls: list[tuple[str, bool | None, str]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    contract_ok: int = 0
    contract_total: int = 0
    model_calls: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    ctx: Any = None

    def bump(self, family: str, ok: bool, n: int = 1) -> None:
        self.quality[family][1] += n
        self.quality[family][0] += n if ok else 0


# -- running ---------------------------------------------------------------------------------------------


def _bounds(case: MethodGoldCase) -> MethodologyReviewBounds | None:
    return MethodologyReviewBounds(**case.bounds) if case.bounds else None


def _review_dict(state) -> dict[str, Any]:
    return state.active_research_run.methodology_review.model_dump(mode="json")


def _state(case: MethodGoldCase, *, with_results: bool | None = None):
    base = phase2j_world(case.project_type, tuple(case.domains), case.gap_variant, case.claim_variant)
    state = with_submission(base, case.submission, case.language)
    if with_results is None:
        with_results = case.results_leak
    if with_results:
        fields = case.flags.get("leak_fields", ["results", "experiments"])
        update: dict[str, Any] = {}
        if "results" in fields:
            update["results"] = [ResultRecord(result_id="R-01", metric="accuracy", value=Tracked[str].known(RESULT_TEXT))]
        if "experiments" in fields:
            update["experiments"] = [ExperimentRecord(experiment_id="EXP-01", objective=RESULT_TEXT,
                                                      success_criteria=[RESULT_TEXT])]
        state = state.model_copy(update={"project": state.project.model_copy(update=update)})
    return state


class _NetworkGuard:
    """No socket may be opened and no HTTP request sent while Phase 3A runs; attempts are counted."""

    def __init__(self) -> None:
        self.attempts = 0

    def __enter__(self):
        def count(*a, **k):
            self.attempts += 1
            raise OSError("network disabled for Phase 3A Gold")

        self._patches = [mock.patch.object(socket.socket, "connect", count),
                         mock.patch("httpx.Client.send", count)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _mutation_run(case: MethodGoldCase, state, provider, bounds):
    rr, project, submission = state.active_research_run, state.project, state.submission
    kw: dict[str, Any] = {}
    if case.mutate == "claim_edit":
        kw["final_project"] = project.model_copy(update={"claims": [
            x.model_copy(update={"claim": x.claim + " and a battery"}) for x in project.claims]})
    elif case.mutate == "upstream_2i":
        nd = rr.novelty_differentiation
        kw["final_research_run"] = rr.model_copy(update={
            "novelty_differentiation": nd.model_copy(update={"model_comparisons_performed": 999})})
    elif case.mutate == "upstream_2j":
        gap = rr.research_engineering_gap
        kw["final_research_run"] = rr.model_copy(update={
            "research_engineering_gap": gap.model_copy(update={"model_calls_performed": 999})})
    elif case.mutate == "submission_edit":
        kw["final_submission"] = StudentSubmissionArtifact(
            artifact_id=submission.artifact_id, project_id=submission.project_id,
            original_text=submission.original_text + " (edited)", language=submission.language)
    elif case.mutate == "submission_removed":
        kw["final_submission"] = None
    return run_stages(state, provider, bounds=bounds, **kw)


def build_ctx(case: MethodGoldCase) -> Ctx:
    state = _state(case)
    plain_state = _state(case, with_results=False) if case.results_leak else None
    model = None if case.no_model else ScriptedMethodologyModel(case.script)
    provider = model.provider() if model else None
    bounds = _bounds(case)
    claim = claim_text(case.claim_variant)
    mutated: dict[str, Any] = {}
    with _NetworkGuard() as guard:
        if case.mutate:
            run = _mutation_run(case, state, provider, bounds)
            d = run.model_dump(mode="json")
            after = state
            mutated = {"status": d["status"], "assessments": len(d["track_assessments"]),
                       "detected": d["status"] == "INVALIDATED_UPSTREAM_MUTATED" and not d["track_assessments"]}
        else:
            after = run_phase3a(state, provider, bounds=bounds, interrupt_before=case.interrupt_before)
            d = _review_dict(after)
    ctx = Ctx(case=case, d=d, text=case.submission or "", claim=claim, upstream=state, after=after, model=model,
              prompts=model.user_inputs() if model else "", mutated=mutated, network_attempts=guard.attempts)
    if model:
        ctx.calls_by_task = {k: model.count(t) for k, t in TASK_KEY.items()}
    ctx.project_unchanged = (
        [x.model_dump() for x in state.project.claims] ==
        [x.model_dump() for x in (after.project.claims if not case.mutate else state.project.claims)]
        and state.project.results == (after.project.results if not case.mutate else state.project.results))
    if case.rerun and not case.mutate:
        again = ScriptedMethodologyModel(case.script)
        second = run_phase3a(after, again.provider(), bounds=bounds)
        ctx.replay = {"extra_calls": len(again.calls), "same": c.canonical(d) == c.canonical(_review_dict(second))}
    if case.interrupt_before and not case.mutate:
        plain = ScriptedMethodologyModel(case.script)
        uninterrupted = run_phase3a(_state(case), plain.provider(), bounds=bounds)
        ctx.replay["resume_same"] = c.canonical(d) == c.canonical(_review_dict(uninterrupted))
    if case.twin == "prose":
        twin = ScriptedMethodologyModel(with_prose(case.script, case.prose))
        td = _review_dict(run_phase3a(_state(case), twin.provider(), bounds=bounds))
        ctx.twins["prose"] = c.canonical(d) == c.canonical(td)
    if case.twin == "order":
        twin = ScriptedMethodologyModel(reorder(case.script))
        td = _review_dict(run_phase3a(_state(case), twin.provider(), bounds=bounds))
        ctx.twins["order"] = c.canonical(d) == c.canonical(td)
        ctx.twins["ids"] = ([e["excerpt_id"] for e in d["excerpts"]] == [e["excerpt_id"] for e in td["excerpts"]]
                            and [i["issue_id"] for t in d["track_assessments"] for i in t["issues"]] ==
                            [i["issue_id"] for t in td["track_assessments"] for i in t["issues"]])
    if plain_state is not None:
        twin = ScriptedMethodologyModel(case.script)
        td = _review_dict(run_phase3a(plain_state, twin.provider(), bounds=bounds))
        ctx.results_twin = {"same": c.canonical(d) == c.canonical(td)}
    return ctx


# -- independent reader ----------------------------------------------------------------------------------

ABSENT = "ABSENT"


def _target(link_or_rec: dict[str, Any]) -> str:
    return "gap" if (link_or_rec.get("gap_hypothesis_id") or link_or_rec.get("gap_validation_requirement_id")) else "claim"


def overlay_class(o: dict[str, Any] | None) -> str:
    if o is None:
        return ABSENT
    m = o["materiality"]
    if m == "MATERIAL_TO_TARGET":
        return "MATERIAL"
    if m == "MATERIALITY_UNRESOLVED":
        return "UNRESOLVED"
    return "TOOL_ONLY" if o["excerpt_ids"] else "NO_RELEVANCE"


def read(ctx: Ctx, key: str) -> Any:  # noqa: C901 - one flat key grammar
    d = ctx.d
    head, _, rest = key.partition(".")
    if key == "status":
        return d["status"]
    if key == "calls":
        return d["model_calls_performed"]
    if key == "search_calls":
        return d["external_search_calls"]
    if key == "errors":
        return sorted({e["code"] for e in d["errors"]})
    if key == "rejected":
        return sorted({r["code"] for r in d["rejected_proposals"]})
    if key == "n_excerpts":
        return len(d["excerpts"])
    if key == "excerpts":
        return sorted(e["excerpt"] for e in d["excerpts"])
    if key == "exec_modes":
        return sorted({e["statement_mode"] for e in d["excerpts"]})
    if key == "overlay_blocked":
        return any(t["overlay_blocked"] for t in ctx.tracks)
    if key == "exec_verified_any":
        return any(e["execution_verified"] for e in d["excerpts"]) or any(t["execution_verified"] for t in ctx.tracks)
    if key == "confounding_any":
        return any(t["confounding_eliminated"] for t in ctx.tracks)
    if key == "leakage_any":
        return any(t["leakage_prevented_in_practice"] for t in ctx.tracks)
    if key == "fairness_any":
        return any(b["comparison_fairness_assessed"] for b in d["baselines"])
    if head == "calls":
        return ctx.calls_by_task.get(rest, 0)
    if head == "posture":
        t = ctx.track(rest)
        return t["posture"] if t else ABSENT
    if head == "issues":
        t = ctx.track(rest)
        return sorted(i["code"] for i in t["issues"]) if t else ABSENT
    if head == "has_issue":
        return any(i["code"] == rest for _, i in ctx.all_issues())
    if head in ("app", "doc", "adq"):
        track, _, kind = rest.partition(".")
        t = ctx.track(track)
        if t is None:
            return ABSENT
        if head == "app":
            hit = next((a for a in t["applicability"] if a["kind"] == kind), None)
            return hit["applicability"] if hit else ABSENT
        hit = next((x for x in t["documentation"] if x["kind"] == kind), None)
        return (hit["documentation"] if head == "doc" else hit["adequacy"]) if hit else ABSENT
    if head == "basis":
        track, _, kind = rest.partition(".")
        t = ctx.track(track)
        hit = next((a for a in (t["applicability"] if t else []) if a["kind"] == kind), None)
        return hit["basis"] if hit else ABSENT
    if head in ("overlay", "owner", "ownbasis", "overlay_class", "overlay_excerpts"):
        o = ctx.overlays.get(rest)
        if o is None:
            return ABSENT
        return {"overlay": o["materiality"], "owner": o["owner_track"], "ownbasis": o["ownership_basis"],
                "overlay_class": overlay_class(o), "overlay_excerpts": bool(o["excerpt_ids"])}[head]
    if head == "overlay_instances":  # in how many tracks is this overlay requirement instantiated
        return sum(1 for t in ctx.tracks if any(a["kind"] == rest for a in t["applicability"]))
    if head == "link":
        track, _, tgt = rest.partition(".")
        t = ctx.track(track)
        hit = next((x for x in (t["coverage"] if t else []) if _target(x) == tgt), None)
        return hit["relation"] if hit else ABSENT
    if head == "cont":
        return "STRONG" if any(_target(x) == rest and x["relation"] in ("DIRECTLY_TESTS_TARGET",)
                               for _, x in ctx.all_links()) else "NOT_STRONG"
    if head in ("metric", "msrc"):
        hit = next((m for m in d["metric_alignments"] if _target(m) == rest), None)
        if hit is None:
            return ABSENT
        return hit["status"] if head == "metric" else hit["metric_source"]
    if head in ("baseline", "brat", "bctx"):
        hit = next((b for b in d["baselines"] if _target(b) == rest), None)
        if hit is None:
            return ABSENT if head == "baseline" else (False if head == "brat" else [])
        return {"baseline": hit["relevance"], "brat": bool(hit["rationale_excerpt_ids"]),
                "bctx": sorted(hit["relevance_context"])}[head]
    if head == "cond":
        conds = sorted((x for _, x in ctx.all_conditions()), key=lambda x: x["condition_id"])
        i = int(rest) - 1
        return conds[i]["status"] if i < len(conds) else ABSENT
    if key.startswith("occ:"):
        hit = next((e for e in d["excerpts"] if e["excerpt"] == key[4:]), None)
        return f'{hit["occurrence_count"]}/{hit["occurrence_index"]}/{hit["occurrence_resolution"]}' if hit else ABSENT
    if head == "replay":
        return ctx.replay.get(rest)
    if head == "twin":
        return ctx.twins.get(rest)
    if key == "results.same":
        return ctx.results_twin.get("same")
    if head == "mutation":
        return ctx.mutated.get(rest)
    if key == "immut.upstream":
        return ctx.project_unchanged
    if key == "network_attempts":
        return ctx.network_attempts
    raise KeyError(key)


def check_expected(ctx: Ctx, key: str, expected: Any) -> tuple[bool, Any]:
    actual = read(ctx, key)
    return actual == expected, actual


# -- one case ---------------------------------------------------------------------------------------------


def run_case(case: MethodGoldCase) -> CaseResult:
    from src.evals.methodology_review.controls import run_control
    from src.evals.methodology_review.gates import GATE_FUNCS, GATES
    from src.evals.methodology_review.quality import evaluate_quality

    result = CaseResult(case=case)
    try:
        ctx = build_ctx(case)
        result.ctx = ctx
        result.model_calls = dict(ctx.calls_by_task)
        for key, expected in case.expected.items():
            ok, actual = check_expected(ctx, key, expected)
            result.contract_total += 1
            result.contract_ok += int(ok)
            if not ok:
                result.failures.append({"case": case.case_id, "key": key, "expected": expected, "actual": actual})
        evaluate_quality(ctx, result)
        for name in GATES:
            result.gates[name] = GATE_FUNCS[name](ctx)
        from src.evals.methodology_review.controls import ALL_CONTROLS

        for name in (ALL_CONTROLS if "*" in case.controls else case.controls):
            caught, how = run_control(ctx, name)
            result.controls.append((name, caught, how))
    except Exception:  # pragma: no cover - surfaced to the reviewer
        result.error = traceback.format_exc()
    return result


__all__ = ["ABSENT", "CaseResult", "RESULT_TEXT", "build_ctx", "check_expected", "overlay_class", "read", "run_case"]
