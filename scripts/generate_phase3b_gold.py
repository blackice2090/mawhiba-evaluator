"""Phase 3B Gold generator -> evals/experiment_review/v1/cases.jsonl.

AUTHORING INDEPENDENCE: this file and the template modules it imports use NOTHING from the Phase 3B production
modules (src.research.experiments, src.schemas.experiment_review, the Phase 3B graph) and nothing that runs the
system (the Gold adapter, runner, quality, gates, controls). Every expectation is authored from the approved
specification (through the Gold-owned catalog) and from each case's own submission text; it is never produced by
running the system. Output is deterministic: running this twice produces byte-identical files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase3b_gold_templates  # noqa: E402,F401  (registers families)
import phase3b_gold_templates2  # noqa: E402,F401
import phase3b_gold_templates3  # noqa: E402,F401
import phase3b_gold_templates4  # noqa: E402,F401
from phase3b_gold_framework import REGISTRY  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "evals" / "experiment_review" / "v1" / "cases.jsonl"


def build_cases() -> list[dict]:
    cases = []
    for fid, category, langs, fn in REGISTRY:
        for lang in langs:
            body = fn(lang)
            case = {"case_id": f"GE-{len(cases) + 1:03d}", "language": lang, "semantic_family_id": fid,
                    "category": category, **body}
            case.setdefault("negative_control_tags", ["*"])
            cases.append(case)
    keys = [json.dumps({k: v for k, v in c.items() if k != "case_id"}, sort_keys=True, ensure_ascii=False)
            for c in cases]
    if len(set(keys)) != len(keys):
        raise SystemExit("exact duplicate cases were generated")
    return cases


def render(cases: list[dict]) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)


def main() -> int:
    cases = build_cases()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(cases), encoding="utf-8", newline="\n")
    fams = {c["semantic_family_id"] for c in cases}
    langs = {k: sum(1 for c in cases if c["language"] == k) for k in ("en", "ar", "mixed")}
    print(f"wrote {len(cases)} cases, {len(fams)} semantic families, {len({c['category'] for c in cases})} "
          f"categories, languages {langs} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
