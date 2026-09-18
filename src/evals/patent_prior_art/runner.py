"""Phase 2G Gold runner and independent scorer.

Each case is driven through the real Phase 2G graph over a populated upstream
state (real Phase 2E and 2F graphs, a canonical ``ScoreRecord``, a trust
verdict). The scorer then grades the result against expectations authored from
the case's records, and against its **own** re-derivations:

* publication identity is re-parsed from the Gold reference with a regex that
  shares no code with ``src.research.patent.identity``;
* chronology is re-derived from the Gold dates and cutoff (publication date,
  else grant date; never priority or filing) without calling
  ``src.research.patent.chronology``;
* the independent-family count is re-derived from the Gold family table.

Negative controls (``tamper``) mutate a finished run and require the contract
to refuse it, which proves the cross-run and honesty gates *can* fire.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.evals.patent_prior_art.dataset import (
    GoldRecord,
    PatentGoldCase,
    build_provider,
)
from src.evals.patent_prior_art.world import build_upstream_state, run_phase2g
from src.graph.workflow_state import EvaluationGraphState
from src.research.patent.cql import validate_cql
from src.research.privacy import ResearchPrivacyContext
from src.research.settings import PatentResearchSettings, ResearchSettings
from src.schemas.patent import (
    CUTOFF_RELATIVE_QUALIFICATIONS,
    PatentContentAvailability,
    PatentContentType,
    PatentFamilyStatus,
    PatentPriorArtRun,
    PatentProvider,
    PatentProviderAccessStatus,
    PatentSearchCoverageStatus,
    PatentSearchCutoff,
    PatentSearchStatus,
    PatentTimeQualification,
    UNIVERSAL_CANDIDATE_LIMITATIONS,
)

# ---------------------------------------------------------------------------
# Vocabulary the scorer scans for
# ---------------------------------------------------------------------------

FORBIDDEN_FIELD_PATTERN = re.compile(
    r"novelty|similarity|same_invention|invalidat|patentab|infring|freedom_to_operate",
    re.IGNORECASE,
)
"""Field names no Phase 2G contract may carry (sections 23, 24)."""

FORBIDDEN_LEGAL_VALUES = frozenset(
    {
        "LEGAL_PRIOR_ART",
        "INVALIDATING_PRIOR_ART",
        "INVALIDATING",
        "NOVELTY_DESTROYING",
        "DESTROYS_NOVELTY",
    }
)
FORBIDDEN_PATENTABILITY_VALUES = frozenset(
    {
        "PATENTABLE",
        "UNPATENTABLE",
        "NOVEL",
        "NOT_NOVEL",
        "SAME_INVENTION",
        "INFRINGES",
        "INFRINGEMENT",
        "FTO_CLEAR",
        "FREEDOM_TO_OPERATE",
    }
)
FORBIDDEN_PHRASES = (
    "legally invalidating",
    "invalidating prior art",
    "destroys novelty",
    "novelty-destroying",
    "is patentable",
    "is not patentable",
    "infringes",
    "freedom to operate is",
)
CREDENTIAL_PATTERNS = (
    re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"authorization\s*:", re.IGNORECASE),
    re.compile(r"access_token\s*[=:]", re.IGNORECASE),
    re.compile(r"(consumer|client)_secret\s*[=:]", re.IGNORECASE),
    re.compile(r"basic\s+[A-Za-z0-9+/]{12,}={0,2}", re.IGNORECASE),
)
"""Credential *material*, not vocabulary. The capability table legitimately
describes OAuth ("the returned bearer token authorizes ..."); what must never
appear is a token, a header or a secret assignment."""

_INDEPENDENT_REF = re.compile(r"^([A-Za-z]{2})[.\s]?([A-Za-z0-9 ,./-]+?)(?:[.\s]([A-Za-z]\d?))?$")


# ---------------------------------------------------------------------------
# Independent re-derivations (share no code with the graded modules)
# ---------------------------------------------------------------------------


def independent_key(ref: str) -> str | None:
    """``authority.number.kind`` from a Gold reference, re-derived here."""
    parts = [p for p in ref.strip().upper().split(".") if p]
    if len(parts) < 2 or len(parts) > 3:
        return None
    authority, number = parts[0], re.sub(r"[\s,/\-]", "", parts[1])
    kind = parts[2] if len(parts) == 3 else None
    if not re.fullmatch(r"[A-Z]{2}", authority):
        return None
    if not re.fullmatch(r"[A-Z0-9]{1,20}", number) or not any(c.isdigit() for c in number):
        return None
    if kind is not None and not re.fullmatch(r"[A-Z]\d?", kind):
        return None
    return f"{authority}.{number}.{kind or '-'}"


def _iso(value: str) -> str | None:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        from datetime import date

        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    return None


def independent_first_public(record: GoldRecord) -> str | None:
    """Publication date, else grant date. Never priority, never filing."""
    return _iso(record.publication_date) or _iso(record.grant_date)


def independent_qualification(record: GoldRecord, cutoff: str | None) -> str:
    if cutoff is None:
        return PatentTimeQualification.NO_CUTOFF.value
    public = independent_first_public(record)
    if public is None:
        return PatentTimeQualification.PUBLICATION_DATE_UNKNOWN.value
    if public < cutoff:
        return PatentTimeQualification.PUBLIC_BEFORE_CUTOFF.value
    if public == cutoff:
        return PatentTimeQualification.PUBLIC_ON_CUTOFF.value
    return PatentTimeQualification.PUBLIC_AFTER_CUTOFF.value


def independent_family_count(case: PatentGoldCase, keys: list[str]) -> int:
    """Families among the retrieved keys, from the Gold family table alone.

    A key whose family the office does not state (unavailable, failed, or a
    family that omits it) counts as its own family: an unknown family is not
    evidence of a shared one.
    """
    ref_by_key = {independent_key(r.ref): r.ref for r in case.records}
    groups: set[str] = set()
    alone = 0
    for key in keys:
        ref = ref_by_key.get(key)
        family = case.families.get(ref) if ref else None
        member_keys = (
            {independent_key(m) for m in family.members} if family is not None else set()
        )
        if (
            family is None
            or not family.available
            or family.failure is not None
            or not family.family_id
            or key not in member_keys
        ):
            alone += 1
            continue
        groups.add(family.family_id)
    return len(groups) + alone


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    case: PatentGoldCase
    before: EvaluationGraphState | None = None
    after: EvaluationGraphState | None = None
    rerun: EvaluationGraphState | None = None
    provider: Any = None
    error: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    """quality metric name -> passed, for the metrics this case exercises."""
    gates: dict[str, tuple[int, int]] = field(default_factory=dict)
    """gate name -> (violations, opportunities) for this case."""

    @property
    def patent(self) -> PatentPriorArtRun | None:
        if self.after is None or self.after.active_research_run is None:
            return None
        return self.after.active_research_run.patent_prior_art

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and all(self.checks.values())
            and all(v == 0 for v, _ in self.gates.values())
        )


def _settings(case: PatentGoldCase) -> ResearchSettings:
    return ResearchSettings(patent=PatentResearchSettings(**case.settings))


def _privacy(case: PatentGoldCase) -> ResearchPrivacyContext:
    return ResearchPrivacyContext.from_identity(
        person_names=tuple(case.privacy.get("person_names", [])),
        school_names=tuple(case.privacy.get("school_names", [])),
        emails=tuple(case.privacy.get("emails", [])),
        phone_numbers=tuple(case.privacy.get("phone_numbers", [])),
        national_ids=tuple(case.privacy.get("national_ids", [])),
    )


def _cutoff(case: PatentGoldCase) -> PatentSearchCutoff:
    if case.cutoff is None:
        return PatentSearchCutoff()
    return PatentSearchCutoff(cutoff_date=case.cutoff, source="phase2g-gold-eval")


class ScriptedExpansionProvider:
    """A structured-model fake returning the case's scripted expansion terms.

    Untrusted by construction: the planner re-validates every term, so a case
    can script a fabricated ``original_text`` or an injected term and require
    it to be refused.
    """

    def __init__(self, terms: list[dict[str, str]]) -> None:
        self._terms = terms
        self.calls = 0

    def parse(self, *, task, system_prompt, user_input, response_model, model):  # noqa: ANN001
        from src.llm.contracts import ModelCallResult, ModelCallStatus

        self.calls += 1
        parsed = response_model.model_validate({"terms": self._terms})
        return ModelCallResult(
            status=ModelCallStatus.SUCCESS,
            parsed=parsed,
            task=task,
            model=model,
            provider="phase2g-gold-scripted",
        )


def run_patent_case(case: PatentGoldCase) -> CaseResult:
    result = CaseResult(case=case)
    try:
        before = build_upstream_state(case.case_id, case.claims)
        provider = build_provider(case)
        model_provider = None
        llm = None
        if case.model_terms is not None:
            from src.config.settings import LLMSettings

            model_provider = ScriptedExpansionProvider(case.model_terms)
            llm = LLMSettings()
        after = run_phase2g(
            before,
            provider,
            cutoff=_cutoff(case),
            privacy=_privacy(case),
            settings=_settings(case),
            model_provider=model_provider,
            llm_settings=llm,
            interrupt_before=case.resume_before,
        )
        result.before, result.after, result.provider = before, after, provider
        if case.rerun:
            # Re-invoking the finished graph must not reopen the run.
            result.rerun = run_phase2g(
                after,
                provider,
                cutoff=_cutoff(case),
                privacy=_privacy(case),
                settings=_settings(case),
            )
    except Exception as exc:  # noqa: BLE001 -- an errored case is reported, never hidden
        result.error = f"{type(exc).__name__}: {exc}"
    return result


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _dump(model: Any) -> Any:
    return json.loads(model.model_dump_json()) if model is not None else None


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        out: list[str] = []
        for key, child in value.items():
            out.append(str(key))
            out.extend(_walk_keys(child))
        return out
    if isinstance(value, list):
        return [k for child in value for k in _walk_keys(child)]
    return []


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for child in value.values() for s in _walk_strings(child)]
    if isinstance(value, list):
        return [s for child in value for s in _walk_strings(child)]
    return [value] if isinstance(value, str) else []


def _tamper_refused(patent: PatentPriorArtRun, kind: str) -> bool:
    """Apply one negative control; True when the contract refuses it."""
    data = dict(patent)
    other = uuid4()
    try:
        if kind == "cross_run_query":
            if not patent.planned_queries:
                return True
            data["planned_queries"] = [
                *patent.planned_queries,
                patent.planned_queries[0].model_copy(
                    update={"research_run_id": other, "query_id": uuid4()}
                ),
            ]
        elif kind == "cross_run_observation":
            if not patent.observations:
                return True
            data["observations"] = [
                *patent.observations,
                patent.observations[0].model_copy(
                    update={"research_run_id": other, "observation_id": uuid4()}
                ),
            ]
        elif kind == "cross_run_publication":
            if not patent.publications:
                return True
            data["publications"] = [
                patent.publications[0].model_copy(update={"research_run_id": other}),
                *patent.publications[1:],
            ]
        elif kind == "cross_run_family":
            if not patent.families:
                return True
            data["families"] = [
                patent.families[0].model_copy(update={"research_run_id": other}),
                *patent.families[1:],
            ]
        elif kind == "unknown_family_reference":
            if not patent.publications:
                return True
            data["publications"] = [
                patent.publications[0].model_copy(update={"family_group_id": uuid4()}),
                *patent.publications[1:],
            ]
        elif kind == "fabricated_family_member":
            from src.schemas.patent import PatentFamilyMemberRef, PublicationIdentity

            if not patent.families:
                return True
            identity = PublicationIdentity(authority="ZZ", number="999999999", kind_code="A1")
            fabricated = PatentFamilyMemberRef(
                publication_key=identity.canonical_key,
                identity=identity,
                retrieved_in_run=True,
            )
            family = patent.families[0]
            data["families"] = [
                family.model_copy(update={"members": [*family.members, fabricated]}),
                *patent.families[1:],
            ]
        elif kind == "duplicate_candidate":
            if not patent.candidates:
                return True
            data["candidates"] = [
                *patent.candidates,
                patent.candidates[0].model_copy(update={"candidate_id": uuid4()}),
            ]
        elif kind == "complete_despite_failure":
            data["coverage_status"] = PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS
            if not any(r.failed for r in patent.provider_results) and not patent.budget.truncated:
                return True
        elif kind == "cutoff_label_without_cutoff":
            if not patent.candidates or patent.search_cutoff.supplied:
                return True
            candidate = patent.candidates[0]
            if not candidate.dates.has_public_date:
                return True
            data["candidates"] = [
                candidate.model_copy(
                    update={
                        "time_qualification": PatentTimeQualification.PUBLIC_BEFORE_CUTOFF,
                        "cutoff_date": "2000-01-01",
                    }
                ),
                *patent.candidates[1:],
            ]
        elif kind == "live_verified_without_request":
            from src.schemas.patent import PatentProviderCapability

            capability = patent.provider_capabilities[0]
            PatentProviderCapability.model_validate(
                {
                    **dict(capability),
                    "access_status": PatentProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED,
                    "live_request_observed": False,
                }
            )
            return False
        PatentPriorArtRun.model_validate(data)
    except ValueError:
        return True
    return False


def score_patent_case(result: CaseResult) -> CaseResult:
    case = result.case
    expected = case.expected
    checks = result.checks
    gates = result.gates
    patent = result.patent
    if result.error is not None or patent is None or result.before is None:
        result.error = result.error or "no patent run produced"
        return result
    before, after = result.before, result.after
    assert after is not None
    before_run = before.active_research_run
    after_run = after.active_research_run
    assert before_run is not None and after_run is not None

    def gate(name: str, violations: int, opportunities: int = 1) -> None:
        v, o = gates.get(name, (0, 0))
        gates[name] = (v + violations, o + opportunities)

    keys = [p.publication_key for p in patent.publications]
    candidates = {c.publication_key: c for c in patent.candidates}
    record_by_key = {independent_key(r.ref): r for r in case.records if not r.malformed}
    provider = result.provider
    sent = [expr for expr, _ in getattr(provider, "fetch_calls", [])]

    # ---- immutability (gates 1-12, 47, 48) ---------------------------------
    bp, ap = before.project, after.project
    gate("project_state_mutation", int(_dump(bp) != _dump(ap)))
    gate("claim_mutation", int(_dump_list(bp.claims) != _dump_list(ap.claims)))
    gate(
        "claim_status_mutation",
        int([c.status for c in bp.claims] != [c.status for c in ap.claims]),
    )
    gate(
        "claim_confidence_mutation",
        int([c.confidence for c in bp.claims] != [c.confidence for c in ap.claims]),
    )
    gate(
        "evidence_reference_mutation",
        int(
            [(c.evidence_ids, c.counter_evidence_ids) for c in bp.claims]
            != [(c.evidence_ids, c.counter_evidence_ids) for c in ap.claims]
            or _dump_list(bp.evidence) != _dump_list(ap.evidence)
        ),
    )
    gate("project_score_mutation", int(_dump_list(bp.scores) != _dump_list(ap.scores)))
    gate("trust_gate_mutation", int(_dump(bp.trust_gate) != _dump(ap.trust_gate)))
    gate("evaluation_status_mutation", int(bp.evaluation_status != ap.evaluation_status))
    gate(
        "phase2c_evidence_mutation",
        int(_dump(before_run.evidence_extraction) != _dump(after_run.evidence_extraction)),
    )
    gate(
        "phase2d_alignment_mutation",
        int(
            _dump(before_run.claim_evidence_alignment)
            != _dump(after_run.claim_evidence_alignment)
        ),
    )
    gate(
        "phase2e_sufficiency_mutation",
        int(_dump(before_run.claim_sufficiency) != _dump(after_run.claim_sufficiency)),
    )
    gate(
        "phase2f_scorecard_mutation",
        int(
            _dump(before_run.claim_evidence_scoring)
            != _dump(after_run.claim_evidence_scoring)
        ),
    )
    gate(
        "automatic_claim_status_update",
        int(
            [(c.claim_id, c.status, c.confidence) for c in bp.claims]
            != [(c.claim_id, c.status, c.confidence) for c in ap.claims]
        ),
    )
    gate(
        "automatic_score_update",
        int(
            _dump_list(bp.scores) != _dump_list(ap.scores)
            or _dump(before_run.claim_evidence_scoring)
            != _dump(after_run.claim_evidence_scoring)
        ),
    )

    # ---- queries (gates 13, 14) --------------------------------------------
    pii_values = [v.casefold() for values in case.privacy.values() for v in values if v]
    query_texts = [
        *sent,
        *(q.query_expression for q in patent.planned_queries),
        *(t.term for q in patent.planned_queries for t in q.terms),
    ]
    leaks = sum(
        1 for text in query_texts for value in pii_values if value in text.casefold()
    )
    gate("pii_query_leakage", leaks, max(1, len(query_texts)))
    invalid_sent = sum(1 for expr in sent if not validate_cql(expr).ok or _independently_invalid(expr))
    gate("invalid_query_accepted", invalid_sent, max(1, len(sent)))

    # ---- verification and identity (gates 15-20) ---------------------------
    valid_keys = {k for k in record_by_key if k is not None}
    malformed_keys = {
        independent_key(r.ref) for r in case.records if r.malformed
    } - {None}
    unverified = sum(
        1
        for p in patent.publications
        if p.publication_key not in valid_keys
        or any(o.research_run_id != patent.research_run_id for o in p.observations)
        or p.verification_status.value not in ("VERIFIED_METADATA", "VERIFIED_FULL_TEXT")
    )
    gate("unverified_observation_as_publication", unverified, max(1, len(keys)))
    gate(
        "invalid_identity_accepted",
        sum(1 for k in keys if k in malformed_keys or independent_key(k) is None),
        max(1, len(keys)),
    )
    expected_keys = set(expected.publication_keys)
    title_groups: dict[str, set[str]] = {}
    for key in expected_keys:
        record = record_by_key.get(key)
        if record is not None and record.title:
            title_groups.setdefault(record.title.casefold(), set()).add(key)
    collapsed_titles = sum(
        1 for group in title_groups.values() if len(group) > 1 and not group <= set(keys)
    )
    gate("title_only_publication_dedupe", collapsed_titles, max(1, len(title_groups)))
    kind_groups: dict[str, set[str]] = {}
    for key in expected_keys:
        kind_groups.setdefault(key.rsplit(".", 1)[0], set()).add(key)
    kind_collapsed = sum(
        1 for group in kind_groups.values() if len(group) > 1 and not group <= set(keys)
    )
    gate("kind_code_collapsed", kind_collapsed, max(1, len(kind_groups)))
    distinct_observed = {o.publication_key for o in patent.observations}
    inflation = max(0, len(keys) - len(distinct_observed)) + (len(keys) - len(set(keys)))
    gate("duplicate_observation_inflation", inflation, max(1, len(keys)))
    multi_query = len({o.query_id for o in patent.observations}) > 1
    gate(
        "duplicate_query_hit_inflation",
        inflation if multi_query else 0,
        max(1, len(keys)) if multi_query else 1,
    )

    # ---- families (gates 21-23) ---------------------------------------------
    independent_families = independent_family_count(case, keys)
    gate(
        "family_member_counted_independent",
        int(patent.independent_family_count > independent_families),
    )
    title_grouped = 0
    for family in patent.families:
        if family.status is not PatentFamilyStatus.VERIFIED_FAMILY:
            continue
        member_refs = {
            m.publication_key for m in family.members
        }
        gold_ids = {
            (case.families.get(record_by_key[k].ref).family_id if record_by_key.get(k) and case.families.get(record_by_key[k].ref) else None)
            for k in member_refs
            if k in keys
        }
        if len(gold_ids - {None}) > 1 or (None in gold_ids and len(member_refs & set(keys)) > 1):
            title_grouped += 1
    gate("title_only_family_grouping", title_grouped, max(1, len(patent.families)))
    fabricated = 0
    for publication in patent.publications:
        if publication.family_status in (
            PatentFamilyStatus.VERIFIED_FAMILY,
            PatentFamilyStatus.SINGLETON_FAMILY,
        ):
            family = patent.family_by_group_id(publication.family_group_id)
            record = record_by_key.get(publication.publication_key)
            gold = case.families.get(record.ref) if record else None
            gold_member_keys = (
                {independent_key(m) for m in gold.members} if gold else set()
            )
            siblings_gold = [
                case.families.get(record_by_key[m.publication_key].ref)
                for m in (family.members if family else [])
                if record_by_key.get(m.publication_key)
                and case.families.get(record_by_key[m.publication_key].ref)
            ]
            stated = (
                gold is not None
                and gold.available
                and gold.failure is None
                and publication.publication_key in gold_member_keys
            ) or any(
                g.available and g.failure is None and publication.publication_key
                in {independent_key(m) for m in g.members}
                for g in siblings_gold
                if g is not None
            )
            if family is None or not stated or publication.publication_key not in {
                m.publication_key for m in family.members
            }:
                fabricated += 1
    gate("fabricated_family_accepted", fabricated, max(1, len(keys)))

    # ---- chronology and cutoff (gates 24-29) --------------------------------
    priority_public = filing_public = grant_public = 0
    after_before = unknown_before = no_cutoff_labeled = 0
    for key, candidate in candidates.items():
        record = record_by_key.get(key)
        if record is None:
            continue
        truth = independent_first_public(record)
        actual = candidate.dates.first_public_date
        if actual != truth:
            if actual and actual == _iso(record.priority_date):
                priority_public += 1
            if actual and actual == _iso(record.filing_date):
                filing_public += 1
        if (
            _iso(record.publication_date)
            and _iso(record.grant_date)
            and actual == _iso(record.grant_date)
            and actual != _iso(record.publication_date)
        ):
            grant_public += 1
        independent = independent_qualification(record, case.cutoff)
        actual_q = candidate.time_qualification.value
        if (
            independent
            in (
                PatentTimeQualification.PUBLIC_AFTER_CUTOFF.value,
                PatentTimeQualification.PUBLIC_ON_CUTOFF.value,
            )
            and actual_q == PatentTimeQualification.PUBLIC_BEFORE_CUTOFF.value
        ):
            after_before += 1
        if (
            independent == PatentTimeQualification.PUBLICATION_DATE_UNKNOWN.value
            and actual_q == PatentTimeQualification.PUBLIC_BEFORE_CUTOFF.value
        ):
            unknown_before += 1
        if case.cutoff is None and candidate.time_qualification in CUTOFF_RELATIVE_QUALIFICATIONS:
            no_cutoff_labeled += 1
    n_candidates = max(1, len(candidates))
    gate("priority_date_as_public_date", priority_public, n_candidates)
    gate("filing_date_as_public_date", filing_public, n_candidates)
    gate("grant_date_as_first_public_date", grant_public, n_candidates)
    gate("after_cutoff_labeled_before", after_before, n_candidates)
    gate("unknown_date_labeled_before", unknown_before, n_candidates)
    gate("no_cutoff_run_labeled", no_cutoff_labeled, n_candidates)

    # ---- content (gates 30, 31) ---------------------------------------------
    claims_false = 0
    claims_substituted = 0
    for publication in patent.publications:
        record = record_by_key.get(publication.publication_key)
        if record is None:
            continue
        gold_text = case.texts.get(record.ref, {}).get(PatentContentType.CLAIMS)
        truly_available = bool(record.claims) and (
            gold_text is None or (gold_text.published and gold_text.failure is None)
        )
        if publication.content.claims_available and not truly_available:
            claims_false += 1
        for snapshot in patent.snapshots_for(publication.publication_key):
            if snapshot.content_type is PatentContentType.CLAIMS and (
                not record.claims
                or _norm(snapshot.text) in {_norm(record.title), _norm(record.abstract)}
                and _norm(snapshot.text) != _norm(record.claims)
            ):
                claims_substituted += 1
    gate("claims_unavailable_as_available", claims_false, max(1, len(keys)))
    gate("title_or_abstract_as_claims", claims_substituted, max(1, len(patent.snapshots)))

    # ---- terminology and legal boundary (gates 32-35) -----------------------
    patent_dump = _dump(patent)
    field_names = _walk_keys(patent_dump)
    strings = _walk_strings(patent_dump)
    summaries = [
        r.result.summary
        for r in after.node_results.values()
        if getattr(r, "result", None) is not None
    ] if hasattr(after, "node_results") else []
    candidate_fields = _walk_keys([_dump(c) for c in patent.candidates])
    gate(
        "provider_rank_as_novelty_score",
        sum(1 for name in candidate_fields if FORBIDDEN_FIELD_PATTERN.search(name)),
        max(1, len(candidate_fields)),
    )
    gate(
        "novelty_score_produced",
        sum(1 for name in field_names if FORBIDDEN_FIELD_PATTERN.search(name)),
        max(1, len(field_names)),
    )
    all_text = [*strings, *summaries]
    gate(
        "legal_prior_art_conclusion",
        sum(1 for s in strings if s in FORBIDDEN_LEGAL_VALUES)
        + sum(1 for s in all_text for phrase in FORBIDDEN_PHRASES if phrase in s.casefold()),
        max(1, len(all_text)),
    )
    gate(
        "patentability_conclusion",
        sum(1 for s in strings if s in FORBIDDEN_PATENTABILITY_VALUES),
        max(1, len(strings)),
    )

    # ---- provider honesty (gates 36-39) -------------------------------------
    capabilities = {c.provider: c for c in patent.provider_capabilities}
    wipo = capabilities.get(PatentProvider.WIPO_PATENTSCOPE)
    gate(
        "patentscope_automation_enabled",
        int(
            wipo is None
            or wipo.dispatchable
            or wipo.access_status is not PatentProviderAccessStatus.UNSUPPORTED_BY_ACCESS_POLICY
        )
        + len(patent.results_for(PatentProvider.WIPO_PATENTSCOPE)),
    )
    uspto = capabilities.get(PatentProvider.USPTO_ODP)
    gate(
        "legacy_patentsview_assumed",
        int(uspto is None or uspto.dispatchable or bool(uspto.operations))
        + len(patent.results_for(PatentProvider.USPTO_ODP))
        + sum(1 for s in strings if "patentsview.org/api" in s.casefold()),
    )
    gate(
        "documented_only_reported_live",
        sum(
            1
            for c in patent.provider_capabilities
            if c.access_status is PatentProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED
        ),
    )
    gate(
        "credentials_persisted",
        sum(1 for s in strings for pattern in CREDENTIAL_PATTERNS if pattern.search(s)),
        max(1, len(strings)),
    )

    # ---- boundedness (gates 40-42) ------------------------------------------
    budget = patent.budget
    complete = patent.coverage_status is PatentSearchCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS
    # Per logical query, across all of its Range windows: page one of a
    # paginated query is not truncated if page two fetched the rest.
    queries = {q.query_id: q for q in patent.planned_queries}
    fetched: dict[str, int] = {}
    reported: dict[str, int] = {}
    for r in patent.provider_results:
        query = queries.get(r.query_id)
        if query is None:
            continue
        intent = f"{query.provider.value}|{query.strategy.value}|{query.normalized_expression}"
        fetched[intent] = fetched.get(intent, 0) + r.accepted_count + r.rejected_count
        if r.provider_reported_total is not None:
            reported[intent] = max(reported.get(intent, 0), r.provider_reported_total)
    limit_hit = budget.truncated or any(
        reported[intent] > fetched.get(intent, 0) for intent in reported
    )
    gate("provider_limit_silently_truncated", int(limit_hit and complete))
    failed_any = any(r.failed for r in patent.provider_results)
    gate("partial_search_reported_complete", int(failed_any and complete))
    scripted_failures = [
        e for r in patent.provider_results for e in r.errors
    ]
    failed_as_success = sum(
        1
        for r in patent.provider_results
        if r.errors and r.status in (PatentSearchStatus.SUCCESS, PatentSearchStatus.EMPTY)
        and r.attempts <= len(r.errors)
    )
    gate("failed_query_reported_successful", failed_as_success, max(1, len(patent.provider_results)))
    _ = scripted_failures

    # ---- cross-run and duplicate candidates (gates 43-46) ------------------
    for name, kind in (
        ("cross_run_query_accepted", "cross_run_query"),
        ("cross_run_publication_accepted", "cross_run_publication"),
        ("cross_run_family_accepted", "cross_run_family"),
        ("incompatible_duplicate_candidate_accepted", "duplicate_candidate"),
    ):
        gate(name, int(not _tamper_refused(patent, kind)))

    # Case-specific negative controls, beyond the universal ones above.
    for kind in case.tamper:
        name = f"tamper_{kind}"
        ok = _tamper_refused(patent, kind)
        checks[f"negative_control:{kind}"] = ok

    # ---- quality checks ------------------------------------------------------
    _quality_checks(result, patent, keys, candidates, record_by_key, independent_families)
    return result


def _independently_invalid(expression: str) -> bool:
    """A second, independent opinion on a dispatched CQL expression."""
    lowered = f" {expression.casefold()} "
    return (
        " not " in lowered
        or any(ch in expression for ch in ";{}<>$`|\\")
        or expression.count('"') % 2 == 1
        or expression.count("(") != expression.count(")")
        or len(expression) > 500
    )


def _dump_list(items: Any) -> Any:
    return [json.loads(i.model_dump_json()) for i in items]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _quality_checks(
    result: CaseResult,
    patent: PatentPriorArtRun,
    keys: list[str],
    candidates: dict[str, Any],
    record_by_key: dict[str | None, GoldRecord],
    independent_families: int,
) -> None:
    case = result.case
    expected = case.expected
    checks = result.checks
    claim_texts = {c["claim_id"]: c["claim"] for c in case.claims}

    # Query provenance: every term traces to a claim; every candidate query is known.
    query_ids = {q.query_id for q in patent.planned_queries}
    provenance_ok = all(
        all(
            (t.claim_id is None or t.claim_id in claim_texts)
            and (
                t.derivation.value not in ("CANONICAL_PROJECT_TEXT",)
                or t.term in (claim_texts.get(t.claim_id or "", "") + " " + t.original_text)
            )
            and (
                t.derivation.value
                not in ("MODEL_ASSISTED_TRANSLATION", "MODEL_ASSISTED_EXPANSION")
                or t.original_text in claim_texts.get(t.claim_id or "", "")
            )
            for t in q.terms
        )
        for q in patent.planned_queries
    ) and all(
        p.query_id in query_ids for c in patent.candidates for p in c.query_provenance
    )
    checks["query_provenance_accuracy"] = provenance_ok
    checks["query_plan_contract_accuracy"] = (
        len(patent.planned_queries) >= expected.min_queries
        and (expected.max_queries is None or len(patent.planned_queries) <= expected.max_queries)
        and set(expected.required_strategies)
        <= {q.strategy.value for q in patent.planned_queries}
        and {c: r.value for c, r in ((e.claim_id, e.reason) for e in patent.excluded_claims)}
        == expected.excluded_claims
        and set(expected.rejected_query_reasons)
        <= {r.reason.value for r in patent.rejected_queries}
    )

    if case.language in ("ar", "mixed") or case.model_terms is not None:
        model_used = patent.planner_prompt_version is not None
        model_terms = [
            t for q in patent.planned_queries for t in q.terms
            if t.derivation.value.startswith("MODEL_ASSISTED")
        ]
        checks["multilingual_query_plan_accuracy"] = (
            model_used == expected.model_assisted
            and all(t.original_text and t.original_text in claim_texts.get(t.claim_id or "", "") for t in model_terms)
            and bool(model_terms) == expected.model_assisted
        )

    if case.privacy:
        pii_values = [v.casefold() for values in case.privacy.values() for v in values if v]
        sent = [expr for expr, _ in getattr(result.provider, "fetch_calls", [])]
        checks["pii_minimization_accuracy"] = not any(
            value in text.casefold()
            for text in [*sent, *(q.query_expression for q in patent.planned_queries)]
            for value in pii_values
        ) and all(
            not e.detail for e in patent.excluded_claims if e.reason.value == "PII_DETECTED"
        )

    independent_expected = {
        independent_key(ref)
        for ref in expected.publication_keys
    }
    checks["publication_identity_accuracy"] = (
        set(keys) == set(expected.publication_keys)
        and None not in independent_expected
        and independent_expected == set(expected.publication_keys)
    )
    checks["provider_observation_dedupe_accuracy"] = (
        len(keys) == len(set(keys)) == len(expected.publication_keys)
        and all(len({o.observation_id for o in p.observations}) == len(p.observations) for p in patent.publications)
    )
    statuses = {p.publication_key: p.family_status.value for p in patent.publications}
    checks["patent_family_grouping_accuracy"] = (
        patent.independent_family_count == expected.independent_family_count == independent_families
        and all(statuses.get(k) == v for k, v in expected.family_status.items())
    )
    if expected.family_members:
        members_ok = True
        for family_id, member_keys in expected.family_members.items():
            family = next((f for f in patent.families if f.family_id == family_id), None)
            if family is None:
                members_ok = False
                continue
            listed = {m.publication_key for m in family.members}
            members_ok = members_ok and set(member_keys) <= listed and all(
                patent.publication_by_key(m.publication_key) is not None
                for m in family.members
                if m.retrieved_in_run
            )
        checks["family_member_preservation_accuracy"] = members_ok

    chronology_ok = True
    cutoff_ok = True
    for key, candidate in candidates.items():
        record = record_by_key.get(key)
        if record is None:
            chronology_ok = False
            continue
        dates = candidate.dates
        chronology_ok = chronology_ok and (
            dates.publication_date == _iso(record.publication_date)
            and dates.filing_date == _iso(record.filing_date)
            and dates.grant_date == _iso(record.grant_date)
            and dates.earliest_priority_date == _iso(record.priority_date)
        )
        independent = independent_qualification(record, case.cutoff)
        cutoff_ok = cutoff_ok and (
            candidate.time_qualification.value
            == independent
            == expected.time_qualification.get(key, independent)
        )
    if candidates:
        checks["chronology_date_field_accuracy"] = chronology_ok
        checks["cutoff_qualification_accuracy"] = cutoff_ok and all(
            candidates.get(k) is not None for k in expected.time_qualification
        )

    if patent.snapshots:
        snapshots_ok = True
        for snapshot in patent.snapshots:
            record = record_by_key.get(snapshot.publication_key)
            source = {
                PatentContentType.ABSTRACT: record.abstract if record else "",
                PatentContentType.CLAIMS: record.claims if record else "",
                PatentContentType.DESCRIPTION: record.description if record else "",
            }.get(snapshot.content_type, "")
            snapshots_ok = snapshots_ok and (
                snapshot.content_hash == hashlib.sha256(snapshot.text.encode("utf-8")).hexdigest()
                and snapshot.provider_endpoint.startswith("GET /published-data/")
                and "token" not in snapshot.provider_endpoint.casefold()
                and snapshot.research_run_id == patent.research_run_id
                and patent.publication_by_key(snapshot.publication_key) is not None
                and _norm(snapshot.text).replace(" ", "") == _norm(source).replace(" ", "")
            )
        checks["text_snapshot_provenance_accuracy"] = snapshots_ok

    content = {p.publication_key: p.content for p in patent.publications}
    availability_checks = [
        (expected.claims_availability, "claims"),
        (expected.abstract_availability, "abstract"),
        (expected.description_availability, "description"),
    ]
    if any(table for table, _ in availability_checks) or expected.title_only:
        checks["claims_availability_accuracy"] = all(
            content.get(key) is not None and getattr(content[key], attr).value == value
            for table, attr in availability_checks
            for key, value in table.items()
        ) and all(content.get(k) is not None and content[k].title_only for k in expected.title_only)

    checks["bounded_search_status_accuracy"] = (
        patent.coverage_status.value == expected.coverage_status
        and patent.outcome.value == expected.outcome
        and patent.bounded_search
        and (expected.pages_requested is None or patent.budget.pages_requested == expected.pages_requested)
    )
    errors = [e.kind.value for r in patent.provider_results for e in r.errors]
    if expected.search_error_kinds or expected.max_attempts is not None or expected.retried is not None:
        checks["provider_error_handling_accuracy"] = (
            set(expected.search_error_kinds) <= set(errors)
            and (
                expected.max_attempts is None
                or all(r.attempts <= expected.max_attempts for r in patent.provider_results)
            )
            and (expected.retried is None or (patent.budget.queries_retried > 0) == expected.retried)
        )
    capabilities = {c.provider: c.access_status for c in patent.provider_capabilities}
    checks["provider_capability_handling_accuracy"] = capabilities == {
        PatentProvider.EPO_OPS: PatentProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY,
        PatentProvider.USPTO_ODP: PatentProviderAccessStatus.DEFERRED,
        PatentProvider.WIPO_PATENTSCOPE: PatentProviderAccessStatus.UNSUPPORTED_BY_ACCESS_POLICY,
    } and (
        case.provider != "WIPO_PATENTSCOPE"
        or (
            not patent.provider_results
            and any(r.reason.value == "PROVIDER_NOT_DISPATCHABLE" for r in patent.rejected_queries)
        )
    )

    if result.rerun is not None or case.resume_before is not None:
        idempotent = True
        if result.rerun is not None:
            again = result.rerun.active_research_run.patent_prior_art
            idempotent = _dump(again) == _dump(patent)
        sent = [expr for expr, _ in getattr(result.provider, "fetch_calls", [])]
        stable_keys = [q.stable_key for q in patent.planned_queries]
        checks["checkpoint_idempotency_accuracy"] = (
            idempotent
            and len(stable_keys) == len(set(stable_keys))
            and len(sent) == len(set(sent)) + sum(
                max(0, r.attempts - 1) for r in patent.provider_results
            )
            and len(patent.observations) == len({o.observation_id for o in patent.observations})
        )

    checks["candidate_traceability"] = (
        {c.publication_key for c in patent.candidates} == set(keys)
        and all(
            set(c.observation_ids) <= {o.observation_id for o in patent.observations}
            and set(c.snapshot_ids) <= {s.snapshot_id for s in patent.snapshots}
            for c in patent.candidates
        )
    )
    checks["legal_boundary_terminology_accuracy"] = all(
        set(UNIVERSAL_CANDIDATE_LIMITATIONS) <= set(c.limitations) for c in patent.candidates
    ) and not any(
        s in FORBIDDEN_LEGAL_VALUES | FORBIDDEN_PATENTABILITY_VALUES
        for s in _walk_strings(_dump(patent))
    )


def evaluate_case(case: PatentGoldCase) -> CaseResult:
    return score_patent_case(run_patent_case(case))


__all__ = [
    "CREDENTIAL_PATTERNS",
    "FORBIDDEN_FIELD_PATTERN",
    "FORBIDDEN_LEGAL_VALUES",
    "FORBIDDEN_PATENTABILITY_VALUES",
    "CaseResult",
    "ScriptedExpansionProvider",
    "evaluate_case",
    "independent_family_count",
    "independent_first_public",
    "independent_key",
    "independent_qualification",
    "run_patent_case",
    "score_patent_case",
]
