"""Phase 3B Gold runner: drives each case through the REAL upstream graphs and the REAL Phase 3B graph (scripted
untrusted model, no network), then reads the serialized run independently and compares it with the AUTHORED
expectations. The reader looks at the run as a plain JSON dict; it never calls a Phase 3B validator."""

from __future__ import annotations

import socket
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from unittest import mock

from src.evals.experiment_review import adapter as ad
from src.evals.experiment_review import context as c
from src.evals.experiment_review.context import ABSENT, Ctx
from src.evals.experiment_review.dataset import ExperimentGoldCase


@dataclass
class CaseResult:
    case: ExperimentGoldCase
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


class NetworkGuard:
    """No socket may be opened and no HTTP request sent while Phase 3B runs; attempts are counted."""

    def __init__(self) -> None:
        self.attempts = 0

    def __enter__(self):
        def count(*a, **k):
            self.attempts += 1
            raise OSError("network disabled for Phase 3B Gold")

        self._patches = [mock.patch.object(socket.socket, "connect", count), mock.patch("httpx.Client.send", count)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


# -- running ---------------------------------------------------------------------------------------------------


def _mutation_run(case: ExperimentGoldCase, state, provider, bounds):
    rr, project, submission = state.active_research_run, state.project, state.submission
    kw: dict[str, Any] = {}
    if case.mutate == "claim_edit":
        kw["final_project"] = project.model_copy(update={"claims": [
            x.model_copy(update={"claim": x.claim + " and a battery"}) for x in project.claims]})
    elif case.mutate == "upstream_2j":
        gap = rr.research_engineering_gap
        kw["final_research_run"] = rr.model_copy(update={
            "research_engineering_gap": gap.model_copy(update={"model_calls_performed": 999})})
    elif case.mutate == "upstream_3a":
        review = rr.methodology_review
        kw["final_research_run"] = rr.model_copy(update={
            "methodology_review": review.model_copy(update={"model_calls_performed": 999})})
    elif case.mutate == "submission_edit":
        kw["final_submission"] = ad.edited_submission(submission, " (edited)")
    elif case.mutate == "submission_removed":
        kw["final_submission"] = None
    return ad.run_stages(state, provider, bounds=bounds, **kw)


def _twin_script(case: ExperimentGoldCase) -> tuple[dict[str, Any], str | None]:
    """The script and submission of the case's twin, or (script, None) when the twin changes no text."""
    import json

    if case.twin == "order":
        return ad.reorder(case.model_script), case.submission
    if case.twin == "prefix":
        return case.model_script, case.twin_data["prefix"] + (case.submission or "")
    swap = case.twin_data["swap"]
    raw = json.dumps(case.model_script, ensure_ascii=False)
    text = case.submission or ""
    for old, new in swap.items():
        raw = raw.replace(json.dumps(old, ensure_ascii=False)[1:-1], json.dumps(new, ensure_ascii=False)[1:-1])
        text = text.replace(old, new)
    return json.loads(raw), text


def build_ctx(case: ExperimentGoldCase) -> Ctx:
    state = ad.build_state(case)
    model = None if case.no_model else ad.ScriptedModel(case.model_script)
    provider = model.provider() if model else None
    bounds = ad.bounds_of(case.bounds)
    mutated: dict[str, Any] = {}
    with NetworkGuard() as guard:
        if case.mutate:
            run = _mutation_run(case, state, provider, bounds)
            d = run.model_dump(mode="json")
            after = state
            mutated = {"status": d["status"], "kept": len(d["experiments"]) + len(d["links"]) + len(d["phase2j_coverage"]),
                       "posture": d["project_posture"], "codes": sorted({e["code"] for e in d["errors"]})}
        else:
            after = ad.run_graph(state, provider, bounds=bounds, interrupt_before=case.interrupt_before)
            d = ad.review_dict(after)
        ctx = Ctx(case=case, d=d, text=case.submission or "", claim=case.claims[0]["claim"], upstream=state,
                  after=after, model=model, mutated=mutated)
        if model:
            ctx.prompts = [(t.name, u) for t, u in model.calls]
            ctx.provider_requests = len(model.calls)
            from src.llm.contracts import ModelTask

            ctx.calls_by_task = {k: model.count(getattr(ModelTask, v)) for k, v in c.TASK_NAMES.items()}
        if case.rerun and not case.mutate:
            again = ad.ScriptedModel(case.model_script)
            second = ad.run_graph(after, again.provider(), bounds=bounds)
            ctx.replay = {"extra_calls": len(again.calls), "same": c.canonical(d) == c.canonical(ad.review_dict(second))}
        if case.interrupt_before and not case.mutate:
            plain = ad.ScriptedModel(case.model_script)
            uninterrupted = ad.run_graph(state, plain.provider(), bounds=bounds)
            ctx.replay["resume_same"] = c.canonical(d) == c.canonical(ad.review_dict(uninterrupted))
        if case.twin and not case.mutate:
            script, text = _twin_script(case)
            twin_model = ad.ScriptedModel(script)
            twin_state = ad.build_state(case, text=text)
            td = ad.review_dict(ad.run_graph(twin_state, twin_model.provider(), bounds=bounds))
            if case.twin == "order":
                ctx.twins["order"] = c.canonical(d) == c.canonical(td)
                ctx.twins["ids"] = ([e["experiment_id"] for e in d["experiments"]] ==
                                    [e["experiment_id"] for e in td["experiments"]])
            else:
                ctx.twins[case.twin] = c.adequacy_projection(d) == c.adequacy_projection(td)
                ctx.twins[case.twin + "_ids"] = (sorted(e["experiment_id"] for e in d["experiments"]) ==
                                                 sorted(e["experiment_id"] for e in td["experiments"]))
                ctx.twins[case.twin + "_keys"] = (sorted(e["protocol_key"] for e in d["experiments"]) ==
                                                  sorted(e["protocol_key"] for e in td["experiments"]))
                ctx.twins[case.twin + "_quarantine"] = len(d["quarantine"]) == len(td["quarantine"])
        if case.legacy_leak and not case.mutate:
            plain_model = ad.ScriptedModel(case.model_script)
            plain_state = ad.build_state(case, legacy=False)
            pd = ad.review_dict(ad.run_graph(plain_state, plain_model.provider(), bounds=bounds))
            ctx.legacy_twin = {"same": c.canonical(d) == c.canonical(pd),
                               "prompts_same": ctx.all_prompts() == [u for _, u in plain_model.calls]}
    ctx.network_attempts = guard.attempts
    return ctx


# -- independent reader ----------------------------------------------------------------------------------------


def read(ctx: Ctx, key: str) -> Any:  # noqa: C901 - one flat key grammar
    d = ctx.d
    if key == "status":
        return d["status"]
    if key == "posture":
        return d["project_posture"]
    if key == "calls":
        return d["model_calls_performed"]
    if key == "search":
        return d["external_search_calls"]
    if key == "network":
        return d["network_attempts"]
    if key == "socket_attempts":
        return ctx.network_attempts
    if key == "errors":
        return sorted({e["code"] for e in d["errors"]})
    if key == "rejected":
        return sorted({r["code"] for r in d["rejected_proposals"]})
    if key == "n_exp":
        return len(d["experiments"])
    if key == "n_quar":
        return len(d["quarantine"])
    if key == "quar_texts":
        return sorted(ctx.quarantine_texts())
    if key == "quar_kinds":
        return sorted(q["kind"] for q in d["quarantine"])
    if key == "later_prompt_leak":
        results = [r for r in ctx.case.flags.get("declared_results", []) if r.strip()]
        return any(r in p for r in results for p in ctx.later_prompts())
    if key == "placeholder_shown":
        return any(c.PLACEHOLDER in p for p in ctx.later_prompts())
    if key == "n_excerpts":
        return len(d["excerpts"])
    if key == "excerpt_texts":
        return sorted(e["excerpt"] for e in d["excerpts"])
    if key == "untested":
        return d["untested_claim_ids"]
    if key == "stages_called":
        return {k: v for k, v in ctx.calls_by_task.items() if v}
    if key == "exec_flags_false":
        return not (d["execution_verified"] or d["results_evaluated"] or any(
            e["execution_verified"] or e["independently_reproduced"] or e["leakage_prevented_in_practice"]
            for e in d["experiments"]))
    head, _, rest = key.partition(".")
    if head == "track":
        t = next((x for x in d["track_postures"] if x["track"] == rest), None)
        return t["posture"] if t else ABSENT
    if head == "trackn":
        t = next((x for x in d["track_postures"] if x["track"] == rest), None)
        return len(t["experiment_ids"]) if t else ABSENT
    if head == "has_issue":
        return any(rest in e["issues"] for e in d["experiments"])
    if head == "run_issue_stage":
        return sorted({c.STAGE_SHORT[e["node"]] for e in d["errors"] if e["code"] == rest})
    if head == "cov":
        cv = ctx.cov(rest)
        return cv["status"] if cv else ABSENT
    if head == "covreasons":
        cv = ctx.cov(rest)
        return cv["reasons"] if cv else ABSENT
    if head == "covering":
        cv = ctx.cov(rest)
        return len(cv["covering_experiment_ids"]) if cv else ABSENT
    if head == "attempting":
        cv = ctx.cov(rest)
        return len(cv["attempting_experiment_ids"]) if cv else ABSENT
    if head == "replay":
        return ctx.replay.get(rest)
    if head == "twin":
        return ctx.twins.get(rest)
    if head == "legacy":
        return ctx.legacy_twin.get(rest)
    if head == "mutation":
        return ctx.mutated.get(rest)
    if head == "bound":
        return {"claims": len(d["bound_claims"]), "targets": len(d["bound_validation_targets"])}.get(rest)
    if head == "ownedby":
        return sorted(e["ownership_basis"] for e in d["experiments"] if e["track"] == rest)
    m = c.re.match(r"^x(\d+)$", head)
    if m:
        return _read_exp(ctx, int(m.group(1)), rest)
    raise KeyError(key)


def _read_exp(ctx: Ctx, index: int, rest: str) -> Any:  # noqa: C901
    e = ctx.exp(index)
    if e is None:
        return ABSENT
    name, _, arg = rest.partition(".")
    if name == "type":
        return e["experiment_type"]
    if name == "posture":
        return e["posture"]
    if name == "track":
        return e["track"]
    if name == "ownbasis":
        return e["ownership_basis"]
    if name == "exec":
        return e["execution_status"]
    if name == "issues":
        return e["issues"]
    if name == "ndef":
        return len(e["defining_excerpt_ids"])
    if name == "nlinks":
        return len(ctx.links_of(e))
    if name == "revision":
        return e["revision_of"] is not None
    if name in ("app", "basis", "doc", "adq", "nex", "judged"):
        r = ctx.req(e, arg)
        if r is None:
            return ABSENT
        return {"app": r["applicability"], "basis": r["basis"], "doc": r["documentation"], "adq": r["adequacy"],
                "nex": len(r["excerpt_ids"]), "judged": bool(r["judgment_excerpt_ids"])}[name]
    if name == "triggers":
        r = ctx.req(e, arg)
        return r["triggers"] if r else ABSENT
    if name in ("link", "meas", "match", "timing", "bl", "blmatch", "lnex"):
        label = arg
        if name == "link":
            x = ctx.link_for(e, label)
            return x["relation"] if x else ABSENT
        if name == "lnex":
            x = ctx.link_for(e, label)
            return len(x["excerpt_ids"]) if x else ABSENT
        if name in ("meas", "match", "timing"):
            mm = ctx.meas_for(e, label)
            if mm is None:
                return ABSENT
            return {"meas": mm["alignment"], "match": mm["phase2j_metric_match"],
                    "timing": mm["success_criterion_timing"]}[name]
        b = ctx.baseline_for(e, label)
        if b is None:
            return ABSENT
        return {"bl": b["relevance"], "blmatch": b["phase2j_baseline_match"]}[name]
    if name == "blprop":
        label, _, prop = arg.partition(".")
        b = ctx.baseline_for(e, label)
        if b is None:
            return ABSENT
        hit = next((p for p in b["comparability"] if p["property"] == prop), None)
        return hit["status"] if hit else ABSENT
    if name == "blprop_basis":
        label, _, prop = arg.partition(".")
        b = ctx.baseline_for(e, label)
        hit = next((p for p in (b["comparability"] if b else []) if p["property"] == prop), None)
        return hit["basis"] if hit else ABSENT
    if name == "cond":
        cs = sorted(ctx.conds_of(e), key=lambda x: x["condition_id"])
        i = int(arg or 1) - 1
        return cs[i]["status"] if i < len(cs) else ABSENT
    if name == "defining":
        by_id = ctx.excerpt_by_id
        return [by_id[i]["excerpt"] for i in e["defining_excerpt_ids"]]
    raise KeyError(rest)


def check_expected(ctx: Ctx, key: str, expected: Any) -> tuple[bool, Any]:
    actual = read(ctx, key)
    return actual == expected, actual


# -- one case --------------------------------------------------------------------------------------------------


def run_case(case: ExperimentGoldCase) -> CaseResult:
    from src.evals.experiment_review.controls import ALL_CONTROLS, run_control
    from src.evals.experiment_review.gates import GATE_FUNCS, GATES
    from src.evals.experiment_review.quality import evaluate_quality

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
        tags = ALL_CONTROLS if "*" in case.negative_control_tags else case.negative_control_tags
        for name in tags:
            caught, how = run_control(ctx, name)
            result.controls.append((name, caught, how))
    except Exception:  # pragma: no cover - surfaced to the reviewer
        result.error = traceback.format_exc()
    return result


__all__ = ["CaseResult", "NetworkGuard", "build_ctx", "check_expected", "read", "run_case"]
