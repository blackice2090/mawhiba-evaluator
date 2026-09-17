"""Claim-evidence scoring Gold dataset -- Phase 2F (section 29).

``evals/claim_evidence_scoring/<version>/cases.jsonl``. Each case describes a
complete synthetic upstream world -- claims, Phase 2B logical sources with their
canonical identifiers, Phase 2C verified evidence, Phase 2D alignments -- and
the **exact** numbers a correct scoring pass must produce from it.

The world builders are reused from the Phase 2E dataset rather than
reimplemented. Phase 2F consumes Phase 2E, so a Phase 2F case *is* a Phase 2E
world plus score expectations, and building the world twice would create two
things that can disagree about what the fixture says.

Phase 2F makes no model call, so there is no scripted model output here and no
misbehaving scorer to defend against. The adversarial surface is the input
*shape* and the arithmetic: the same DOI under two source records, twenty
independent groups where two would saturate, a retracted supporting paper, a
component no alignment anchored, evidence that is only context, a claim whose
support and contradiction are both material.

**Expectations are authored from the input, never from output.** Every
``support_index_bp`` in this dataset was derived by applying the published point
allocation to the described world by hand -- component count, which components
are adequately covered in which direction, how many independent groups back
each -- and the numbers are exact rather than tolerances. When the engine
disagreed with an expectation during development the input was re-examined and
the discrepancy explained before either side changed; an expectation was never
edited to match a computed number.

All content is synthetic. No real paper, DOI, author, dataset or student
identity appears anywhere. Arabic and mixed-language cases carry Arabic only as
*data*, in claim text and excerpt value positions, never translated.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from pydantic import Field, model_validator

from src.evals.claim_sufficiency.dataset import (
    GoldAlignment,
    GoldClaim,
    GoldEvidence,
    GoldSource,
    SufficiencyGoldCase,
    build_academic_result,
    build_alignment_run,
    build_claims,
    build_extraction_run,
    gold_run_id,
)
from src.schemas.claim_evidence_score import (
    ReliabilityPosture,
    ScoreDisposition,
    ScoreReasonCode,
)
from src.schemas.common import MawhibaModel

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evals" / "claim_evidence_scoring"
DEFAULT_SCORING_DATASET_VERSION = "v1"


class ScoringGoldExpectation(MawhibaModel):
    """The exact scorecard a correct pass must produce, from the input alone.

    Numbers are in basis points, because that is what the contract stores and a
    display value would hide a one-basis-point disagreement -- exactly the kind
    of arithmetic drift this dataset exists to catch (section 29, section 16).
    """

    status: str | None = None
    scorecards_total: int | None = Field(default=None, ge=0)

    support_index_bp: dict[str, int] = Field(
        default_factory=dict, description="claim_id -> exact support index in bp."
    )
    contradiction_index_bp: dict[str, int] = Field(default_factory=dict)
    support_dimensions_bp: dict[str, list[int]] = Field(
        default_factory=dict,
        description="claim_id -> [coverage, corroboration, directness] in bp.",
    )
    contradiction_dimensions_bp: dict[str, list[int]] = Field(default_factory=dict)

    disposition: dict[str, str] = Field(default_factory=dict)
    final_support_index_bp: dict[str, int] = Field(
        default_factory=dict,
        description="claim_id -> the issued primary scalar. A claim listed in "
        "``final_withheld`` must NOT appear here: the two fields are how the "
        "dataset states the difference between 0 and None (section 11).",
    )
    final_withheld: list[str] = Field(
        default_factory=list, description="claim_ids that must issue no scalar."
    )

    reliability: dict[str, str] = Field(default_factory=dict)
    covered_components: dict[str, int] = Field(default_factory=dict)
    contradicted_components: dict[str, int] = Field(default_factory=dict)
    total_components: dict[str, int] = Field(default_factory=dict)
    unexamined_components: dict[str, int] = Field(default_factory=dict)
    saturated_components: dict[str, int] = Field(default_factory=dict)
    contributing_groups: dict[str, int] = Field(default_factory=dict)

    reason_codes: dict[str, list[str]] = Field(
        default_factory=dict, description="claim_id -> codes that must be present."
    )
    forbidden_reason_codes: dict[str, list[str]] = Field(default_factory=dict)
    withheld_reasons: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_values(self) -> ScoringGoldExpectation:
        for claim_id, value in self.disposition.items():
            if value not in ScoreDisposition.__members__:
                raise ValueError(f"unknown disposition {value} for {claim_id}")
        for claim_id, value in self.reliability.items():
            if value not in ReliabilityPosture.__members__:
                raise ValueError(f"unknown reliability posture {value} for {claim_id}")
        for mapping in (
            self.reason_codes,
            self.forbidden_reason_codes,
            self.withheld_reasons,
        ):
            for claim_id, codes in mapping.items():
                for code in codes:
                    if code not in ScoreReasonCode.__members__:
                        raise ValueError(f"unknown reason code {code} for {claim_id}")
        overlap = set(self.final_support_index_bp) & set(self.final_withheld)
        if overlap:
            raise ValueError(
                f"claims {sorted(overlap)} both issue and withhold a scalar; a "
                "scorecard does exactly one of the two"
            )
        for claim_id, dimensions in {
            **self.support_dimensions_bp,
            **self.contradiction_dimensions_bp,
        }.items():
            if len(dimensions) != 3:
                raise ValueError(
                    f"{claim_id} dimensions must be [coverage, corroboration, "
                    f"directness]; got {len(dimensions)} value(s)"
                )
        return self


class ScoringGoldCase(MawhibaModel):
    """One Gold case: a synthetic world plus the exact scores it must produce."""

    case_id: str = Field(pattern=r"^CES-\d{3,}$")
    language: str = Field(pattern=r"^(ar|en|mixed)$")
    categories: list[str] = Field(min_length=1)

    claims: list[GoldClaim] = Field(min_length=1)
    sources: list[GoldSource] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)
    alignments: list[GoldAlignment] = Field(default_factory=list)
    alignment_status: str = Field(default="COMPLETED")

    sufficiency_not_ready: bool = Field(
        default=False,
        description="Run Phase 2F against a research run whose Phase 2E pass "
        "never completed, to prove the not-ready path reports itself instead of "
        "scoring an absent input (section 27).",
    )
    direct_kind: str | None = Field(
        default=None,
        description="Which below-the-graph shape this case exercises. "
        "``cross_run`` offers the pipeline an assessment built under a different "
        "research run id (section 24). ``unknown_inventory`` offers an "
        "assessment whose component inventory is UNKNOWN -- unreachable through "
        "the graph, because the graph only assesses claims it could resolve, so "
        "the only honest way to exercise it is to build it directly "
        "(section 27). Requires ``direct_mode``.",
    )
    direct_mode: bool = Field(
        default=False,
        description="Call the deterministic pipeline directly instead of the "
        "graph, for shapes a validated run record cannot hold. Still production "
        "code, entered below the graph.",
    )
    resume_after_node: str | None = Field(
        default=None,
        description="Interrupt the Phase 2F graph before this node and resume "
        "from the checkpoint, to prove a resume neither duplicates nor loses "
        "scorecards (section 25).",
    )
    rerun: bool = Field(
        default=False, description="Invoke the finished graph a second time."
    )
    fingerprint_pair: str | None = Field(
        default=None,
        description="Another case id this one must share (``same``) or differ "
        "from (``differ``) in input fingerprint, written as '<case_id>:<mode>'. "
        "Drives the fingerprint stability and sensitivity gates (section 17).",
    )

    expected: ScoringGoldExpectation
    notes: str = ""

    @model_validator(mode="after")
    def _references_resolve(self) -> ScoringGoldCase:
        # Validate the embedded world by building the Phase 2E case from it:
        # one validator, one set of rules, no second opinion about whether an
        # anchor is verbatim or a claim reference resolves.
        self.as_sufficiency_case()
        if self.direct_kind is not None:
            if self.direct_kind not in {"cross_run", "unknown_inventory"}:
                raise ValueError(f"unknown direct_kind {self.direct_kind}")
            if not self.direct_mode:
                raise ValueError(f"direct_kind {self.direct_kind} requires direct_mode")
        if self.direct_mode and self.direct_kind is None:
            raise ValueError("direct_mode requires an explicit direct_kind")
        if self.fingerprint_pair is not None:
            parts = self.fingerprint_pair.split(":")
            if len(parts) != 2 or parts[1] not in {"same", "differ"}:
                raise ValueError(
                    "fingerprint_pair must be '<case_id>:same' or "
                    "'<case_id>:differ'"
                )
        return self

    def as_sufficiency_case(self) -> SufficiencyGoldCase:
        """This case's world, as a Phase 2E Gold case.

        The world is deliberately keyed on the Phase 2F ``case_id`` so two
        Phase 2F cases never share synthetic ids, and so a fingerprint-pair
        case differs from its partner only in what the case actually changed.
        """
        return SufficiencyGoldCase.model_validate(
            {
                "case_id": _sufficiency_case_id(self.case_id),
                "language": self.language,
                "categories": list(self.categories),
                "claims": [c.model_dump() for c in self.claims],
                "sources": [s.model_dump() for s in self.sources],
                "evidence": [e.model_dump() for e in self.evidence],
                "alignments": [a.model_dump() for a in self.alignments],
                "alignment_status": self.alignment_status,
                "expected": {},
            }
        )


def _sufficiency_case_id(case_id: str) -> str:
    """Map ``CES-007`` onto the ``CS-`` id space the Phase 2E builders expect.

    Offset by 500 so a Phase 2F world can never collide with a real Phase 2E
    Gold case's synthetic ids if both datasets are ever loaded together.
    """
    number = int(case_id.split("-")[1])
    return f"CS-{number + 500:03d}"


class ScoringGoldDataset(MawhibaModel):
    version: str
    cases: list[ScoringGoldCase]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> ScoringGoldDataset:
        ids = [c.case_id for c in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        known = set(ids)
        for case in self.cases:
            if case.fingerprint_pair is None:
                continue
            partner = case.fingerprint_pair.split(":")[0]
            if partner not in known:
                raise ValueError(
                    f"{case.case_id} names unknown fingerprint partner {partner}"
                )
        return self

    @property
    def language_counts(self) -> dict[str, int]:
        return dict(Counter(c.language for c in self.cases))

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(Counter(cat for c in self.cases for cat in c.categories))

    @property
    def disposition_counts(self) -> dict[str, int]:
        return dict(
            Counter(
                value
                for case in self.cases
                for value in case.expected.disposition.values()
            )
        )

    @property
    def reliability_counts(self) -> dict[str, int]:
        return dict(
            Counter(
                value
                for case in self.cases
                for value in case.expected.reliability.values()
            )
        )

    def by_id(self, case_id: str) -> ScoringGoldCase | None:
        return next((c for c in self.cases if c.case_id == case_id), None)


# ---------------------------------------------------------------------------
# Deterministic materialization
# ---------------------------------------------------------------------------


def scoring_run_id_for(case: ScoringGoldCase) -> UUID:
    """A stable scoring run id per case, so scorecard ids are reproducible.

    ``uuid5`` from the case id rather than ``uuid4``: the whole point of the
    idempotency gates is that two runs over one case produce identical
    scorecard ids, and a random run id would make that untestable.
    """
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, f"scoring-gold:{case.case_id}:scoring-run")


def world_run_id(case: ScoringGoldCase) -> UUID:
    return gold_run_id(case.as_sufficiency_case())


def build_world(case: ScoringGoldCase) -> dict[str, object]:
    """The Phase 2B/2C/2D state this case starts from, via the Phase 2E builders."""
    suff = case.as_sufficiency_case()
    return {
        "claims": build_claims(suff),
        "academic_research": build_academic_result(suff),
        "evidence_extraction": build_extraction_run(suff),
        "claim_evidence_alignment": build_alignment_run(suff),
    }


def scoring_dataset_path(version: str = DEFAULT_SCORING_DATASET_VERSION) -> Path:
    return DATASET_ROOT / version / "cases.jsonl"


def load_scoring_dataset(
    version: str = DEFAULT_SCORING_DATASET_VERSION,
) -> ScoringGoldDataset:
    path = scoring_dataset_path(version)
    if not path.exists():
        raise FileNotFoundError(f"claim scoring dataset not found: {path}")
    cases: list[ScoringGoldCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(ScoringGoldCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(
                f"{path.name} line {number}: {str(exc).splitlines()[0]}"
            ) from exc
    return ScoringGoldDataset(version=version, cases=cases)


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_SCORING_DATASET_VERSION",
    "ScoringGoldCase",
    "ScoringGoldDataset",
    "ScoringGoldExpectation",
    "build_world",
    "load_scoring_dataset",
    "scoring_dataset_path",
    "scoring_run_id_for",
    "world_run_id",
]
