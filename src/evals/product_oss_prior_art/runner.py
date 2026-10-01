"""Phase 2H offline Gold runner.

Each case:

1. builds a populated upstream world through the real Phase 2E, 2F and 2G
   graphs (cached per claim set, deep-copied per case);
2. runs the real Phase 2H graph against the case's fakes (and, where asked,
   an interrupted-and-resumed run or a second invocation);
3. compares an observed summary with the authored expectations;
4. re-derives the safety facts **independently of the code it grades** --
   address safety from ``ipaddress``, GTIN validity from the check-digit
   arithmetic, relationships from the scripted provider metadata, chronology
   from the stored dates -- and tallies the 64 release-blocking gates;
5. applies negative controls: mutations of a finished run that the contract
   must refuse. An accepted mutation is a gate violation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from src.evals.product_oss_prior_art.dataset import CaseWorld, ProductOssGoldCase
from src.evals.product_oss_prior_art.world import build_phase2h_upstream, run_phase2h
from src.graph.workflow_state import EvaluationGraphState
from src.research.privacy import contains_pii
from src.schemas.discovery import DiscoveryProviderAccessStatus
from src.schemas.open_source_prior_art import OpenSourcePriorArtRun
from src.schemas.product_prior_art import ProductPriorArtRun
from src.schemas.research import ResearchRun

GATES: tuple[str, ...] = (
    "project_state_mutation", "claim_mutation", "claim_status_mutation", "claim_confidence_mutation",
    "evidence_reference_mutation", "project_score_mutation", "trust_gate_mutation", "evaluation_status_mutation",
    "phase2c_evidence_mutation", "phase2d_alignment_mutation", "phase2e_sufficiency_mutation",
    "phase2f_scorecard_mutation", "phase2g_patent_run_mutation", "pii_leaked_to_product_query",
    "pii_leaked_to_github_query", "invalid_query_dispatched", "observation_treated_as_verified_product",
    "observation_treated_as_verified_repository", "unsafe_url_fetched", "unsafe_redirect_followed",
    "oversized_artifact_silently_accepted", "marketplace_labeled_first_party", "third_party_labeled_first_party",
    "title_only_product_collapse", "probable_identity_destructively_merged", "duplicate_listing_inflated_count",
    "search_rank_as_novelty_score", "popularity_as_novelty_score", "dated_product_as_legal_prior_art",
    "current_page_as_historical_proof", "owner_name_instead_of_stable_id", "code_hits_inflated_repo_count",
    "fork_counted_as_independent_root", "mirror_counted_as_independent_root", "name_similarity_inferred_relation",
    "created_at_as_public_since", "commit_date_as_public_availability", "stars_as_novelty_strength",
    "code_snippet_as_full_snapshot", "license_as_reuse_permission", "provider_limit_silently_truncated",
    "partial_product_search_reported_complete", "partial_oss_search_reported_complete",
    "failed_query_reported_successful", "cross_run_query_accepted", "cross_run_product_artifact_accepted",
    "cross_run_product_entity_accepted", "cross_run_repository_accepted", "cross_run_network_accepted",
    "duplicate_product_candidate_accepted", "duplicate_oss_candidate_accepted", "novelty_score_produced",
    "novelty_verdict_produced", "same_invention_verdict_produced", "plagiarism_verdict_produced",
    "legal_prior_art_conclusion_produced", "patentability_infringement_fto_produced",
    "automatic_claim_status_update", "automatic_project_score_update", "phase2f_score_modified",
    "provider_credential_persisted", "documented_only_reported_live", "candidate_type_conflation",
    "unbounded_recursive_expansion",
    # Phase 2H.1: content equality is artifact duplication, never product identity.
    "content_hash_product_merge", "distinct_strong_ids_collapsed", "content_hash_as_verified_identity",
    "duplicate_content_relation_lost",
)
assert len(GATES) == 68

FORBIDDEN_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "novelty_score_produced": re.compile(r'"(novelty_score|novelty_strength|similarity(_score)?|relevance_score)"'),
    "novelty_verdict_produced": re.compile(r'"(not_novel|novel|novelty_verdict|novelty_destroyed)"\s*:'),
    "same_invention_verdict_produced": re.compile(r'"(same_invention|identical_invention)"\s*:'),
    "plagiarism_verdict_produced": re.compile(r'"(plagiari[sz]ed|plagiarism|copied|copying_detected)"\s*:'),
    "legal_prior_art_conclusion_produced": re.compile(r'"(legal_prior_art|invalidating|anticipates)"\s*:'),
    "patentability_infringement_fto_produced": re.compile(r'"(patentable|unpatentable|infringes|infringement|freedom_to_operate|fto)"\s*:'),
}
POPULARITY = re.compile(r'"(stargazers_count|forks_count|watchers_count|popularity|review_count|rating)"')
MARKETPLACE_SUFFIXES = ("amazon.com", "amazon.sa", "amazon.ae", "ebay.com", "aliexpress.com", "alibaba.com",
                        "noon.com", "etsy.com", "walmart.com", "bestbuy.com", "jarir.com", "extra.com")

_UPSTREAM_CACHE: dict[str, EvaluationGraphState] = {}


# ---------------------------------------------------------------------------
# Independent re-derivations
# ---------------------------------------------------------------------------


def independent_url_safe(url: str, resolver: dict[str, list[str]]) -> bool:
    """Re-derived from scratch: scheme, credentials, port, host, every address."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or "@" in parts.netloc:
        return False
    if port not in (None, 80, 443):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host and ":" not in host:
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = [ipaddress.ip_address(a) for a in resolver.get(host, ["93.184.216.34"])]
    for address in addresses:
        mapped = getattr(address, "ipv4_mapped", None)
        address = mapped or address
        if not address.is_global or address.is_private or address.is_loopback or address.is_link_local:
            return False
    return True


def independent_gtin_ok(value: str) -> bool:
    digits = value.strip()
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1].zfill(13), int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == check


def _date_of(dt: Any) -> str | None:
    return dt.date().isoformat() if dt is not None else None


def _expected_relationship(spec: dict[str, Any]) -> str:
    if spec.get("fork"):
        return "FORK"
    if spec.get("mirror_url"):
        return "MIRROR"
    if spec.get("template"):
        return "TEMPLATE_DERIVATIVE"
    return "ROOT_REPOSITORY"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    case: ProductOssGoldCase
    summary: dict[str, Any] = field(default_factory=dict)
    checks: list[tuple[str, str, bool, Any, Any]] = field(default_factory=list)
    """(family, key, ok, expected, actual)."""
    gates: dict[str, list[int]] = field(default_factory=lambda: {g: [0, 0] for g in GATES})
    controls: list[tuple[str, bool]] = field(default_factory=list)
    """(control name, rejected)."""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and all(ok for _, _, ok, _, _ in self.checks)
            and all(v[0] == 0 for v in self.gates.values())
            and all(rejected for _, rejected in self.controls)
        )

    def gate(self, name: str, violated: bool | int, opportunities: int = 1) -> None:
        self.gates[name][0] += int(violated)
        self.gates[name][1] += opportunities


KEY_FAMILY: dict[str, str] = {
    "purposes_includes": "query_provenance", "queries_planned": "query_provenance", "claims_searched": "query_provenance",
    "max_expansion_depth": "query_provenance", "queries_from_results": "query_provenance", "rejected_includes": "query_provenance",
    "languages_includes": "multilingual_query_plan",
    "observations_min": "observation_artifact_separation", "observations_max": "bounded_status",
    "artifacts": "observation_artifact_separation", "fetch_requests": "safe_fetch",
    "artifact_statuses": "safe_fetch", "redirects_recorded": "safe_fetch",
    "roles": "source_role", "first_party": "source_role",
    "entities": "product_identity", "strong": "product_identity", "conflicted": "product_identity",
    "grouping_bases_includes": "product_identity", "content_links": "weak_identity_non_collapse",
    "probable": "weak_identity_non_collapse", "unresolved": "weak_identity_non_collapse",
    "upper_bound": "listing_anti_inflation", "lower_bound": "listing_anti_inflation",
    "vendor_launch_dates": "product_chronology",
    "repositories": "repository_identity", "repository_keys": "repository_identity", "renamed": "repository_identity",
    "mismatches": "repository_identity", "unverified": "repository_identity",
    "code_hits": "code_hit_dedupe", "items_truncated": "code_hit_dedupe",
    "networks": "fork_network_grouping", "independent_roots": "fork_network_grouping", "relationships": "fork_network_grouping",
    "candidates": "candidate_traceability", "snapshot_kinds_includes": "snapshot_provenance",
    "truncated_snapshots": "snapshot_provenance", "licenses": "license_metadata", "archived": "repository_identity",
    "metadata_gaps": "provider_capability_error", "coverage": "bounded_status", "outcome": "bounded_status",
    "pages_executed": "bounded_status", "max_attempts": "provider_capability_error", "min_rank": "legal_novelty_boundary",
    "idempotent": "idempotency", "resume_equivalent": "idempotency",
    "negative_controls_rejected": "legal_novelty_boundary", "project_unchanged": "immutability",
    "upstream_unchanged": "immutability", "secret_absent": "provider_capability_error",
    "providers_documented_only": "provider_capability_error", "types_separate": "candidate_traceability",
}


def _family(key: str, expected: Any, case: ProductOssGoldCase) -> str:
    track, _, name = key.partition(".")
    base = name
    if name == "excluded":
        return "pii_minimization" if "PII_DETECTED" in (expected or []) else "query_provenance"
    if name in ("web_requests", "search_requests"):
        return "pii_minimization" if case.privacy or any(c.startswith("q-pii") for c in case.categories) else "bounded_status"
    if name in ("qualifications", "date_fields"):
        return "product_chronology" if track == "product" else "oss_chronology"
    return KEY_FAMILY.get(base, "candidate_traceability")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarize(after: EvaluationGraphState, world: CaseWorld) -> dict[str, Any]:
    run = after.active_research_run
    p = run.product_prior_art
    o = run.open_source_prior_art
    claims_text = [c.claim for c in world.case.claims]
    s: dict[str, Any] = {}
    if p is not None:
        fetched = [a for a in p.artifacts if a.fetched]
        s.update({
            "product.coverage": p.coverage_status.value,
            "product.outcome": p.outcome.value,
            "product.queries_planned": len(p.planned_queries),
            "product.purposes": sorted({q.purpose.value for q in p.planned_queries}),
            "product.languages": sorted({q.language.value for q in p.planned_queries}),
            "product.excluded": sorted(e.reason.value for e in p.excluded_claims),
            "product.rejected": sorted({r.reason.value for r in p.rejected_queries}),
            "product.claims_searched": sorted({c for q in p.planned_queries for c in q.claim_ids}),
            "product.max_expansion_depth": max((q.expansion_depth for q in p.planned_queries), default=0),
            "product.queries_from_results": sum(
                1 for q in p.planned_queries for t in q.terms if not any(t.original_text in c or c in t.original_text for c in claims_text)
            ),
            "product.web_requests": len(world.web.requests) if world.web else 0,
            "product.fetch_requests": len(world.transport.requests),
            "product.observations": len(p.observations),
            "product.artifacts": len(p.artifacts),
            "product.artifact_statuses": dict(Counter(a.fetch_status.value for a in p.artifacts)),
            "product.redirects_recorded": sum(1 for a in p.artifacts if a.redirect_chain and a.fetched),
            "product.roles": dict(Counter(a.source_role.value for a in fetched)),
            "product.first_party": sum(1 for a in fetched if a.source_role.value.startswith("FIRST_PARTY")),
            "product.entities": len(p.entities),
            "product.strong": sum(1 for e in p.entities if e.identity_status.value == "VERIFIED_STRONG_IDENTITY"),
            "product.probable": sum(1 for e in p.entities if e.identity_status.value == "PROBABLE_IDENTITY"),
            "product.unresolved": sum(1 for e in p.entities if e.identity_status.value == "UNRESOLVED_IDENTITY"),
            "product.conflicted": sum(1 for e in p.entities if e.conflicting_strong_keys),
            "product.grouping_bases": sorted({e.grouping_basis.value for e in p.entities}),
            "product.content_links": sum(
                1 for e in p.entities if any(l.basis.value == "IDENTICAL_CONTENT_HASH" for l in e.probable_links)
            ),
            "product.upper_bound": p.distinct_product_count_upper_bound,
            "product.lower_bound": p.distinct_product_count_lower_bound,
            "product.candidates": len(p.candidates),
            "product.qualifications": dict(Counter(c.chronology.qualification.value for c in p.candidates)),
            "product.date_fields": dict(Counter(c.chronology.date_field_used.value for c in p.candidates if c.chronology.date_field_used)),
            "product.vendor_launch_dates": sum(1 for a in p.artifacts if a.dates.vendor_launch_date),
            "product.min_rank": min((q.retrieval_rank for c in p.candidates for q in c.query_provenance), default=None),
            "product.max_attempts": max((e.attempts for e in p.executions), default=0),
            "product.pages_executed": max((e.page for e in p.executions), default=0),
        })
    if o is not None:
        s.update({
            "oss.coverage": o.coverage_status.value,
            "oss.outcome": o.outcome.value,
            "oss.queries_planned": len(o.planned_queries),
            "oss.purposes": sorted({q.purpose.value for q in o.planned_queries}),
            "oss.languages": sorted({q.language.value for q in o.planned_queries}),
            "oss.excluded": sorted(e.reason.value for e in o.excluded_claims),
            "oss.rejected": sorted({r.reason.value for r in o.rejected_queries}),
            "oss.search_requests": sum(1 for kind, _ in world.github.requests if kind in ("repo", "code")) if world.github else 0,
            "oss.observations": len(o.observations),
            "oss.repositories": len(o.repositories),
            "oss.repository_keys": sorted(r.repository_key for r in o.repositories),
            "oss.unverified": len(o.unverified_repositories),
            "oss.mismatches": sum(1 for u in o.unverified_repositories if u.identity_mismatch_repository_id),
            "oss.renamed": sum(1 for r in o.repositories if r.renamed_or_transferred),
            "oss.code_hits": sum(r.code_hit_count for r in o.repositories),
            "oss.items_truncated": o.budget.items_truncated_per_parent > 0,
            "oss.networks": len(o.networks),
            "oss.independent_roots": o.independent_root_count,
            "oss.relationships": dict(Counter(c.relationship.value for c in o.candidates)),
            "oss.candidates": len(o.candidates),
            "oss.qualifications": dict(Counter(c.chronology.qualification.value for c in o.candidates)),
            "oss.date_fields": dict(Counter(c.chronology.date_field_used.value for c in o.candidates if c.chronology.date_field_used)),
            "oss.snapshot_kinds": sorted({s.kind.value for s in o.snapshots}),
            "oss.truncated_snapshots": sum(1 for s in o.snapshots if s.truncated),
            "oss.licenses": dict(Counter(r.license.status.value for r in o.repositories)),
            "oss.archived": sum(1 for r in o.repositories if r.archived),
            "oss.metadata_gaps": sum(len(r.metadata_gaps) for r in o.repositories),
            "oss.max_attempts": max((e.attempts for e in o.executions), default=0),
            "oss.pages_executed": max((e.page for e in o.executions), default=0),
        })
    return s


def _compare(expected: Any, actual: Any, key: str) -> bool:
    name = key.partition(".")[2]
    if name.endswith("_includes"):
        return set(expected) <= set(actual or [])
    if name.endswith("_min"):
        return actual is not None and actual >= expected
    if name.endswith("_max"):
        return actual is not None and actual <= expected
    if isinstance(expected, dict):
        return dict(actual or {}) == expected
    if isinstance(expected, list):
        return sorted(expected) == sorted(actual or [])
    return expected == actual


def _actual_for(key: str, summary: dict[str, Any]) -> Any:
    track, _, name = key.partition(".")
    for suffix in ("_includes", "_min", "_max"):
        if name.endswith(suffix):
            return summary.get(f"{track}.{name[: -len(suffix)]}")
    return summary.get(key)


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def _project_gates(result: CaseResult, before: EvaluationGraphState, after: EvaluationGraphState) -> None:
    b, a = before.project, after.project
    result.gate("project_state_mutation", a != b)
    claims_b = {c.claim_id: c for c in b.claims}
    claims_a = {c.claim_id: c for c in a.claims}
    n = max(len(claims_b), 1)
    result.gate("claim_mutation", sum(claims_a.get(k) is None or claims_a[k].claim != v.claim for k, v in claims_b.items()), n)
    result.gate("claim_status_mutation", sum(claims_a.get(k) is None or claims_a[k].status != v.status for k, v in claims_b.items()), n)
    result.gate("automatic_claim_status_update", sum(claims_a.get(k) is None or claims_a[k].status != v.status for k, v in claims_b.items()), n)
    result.gate("claim_confidence_mutation", sum(claims_a.get(k) is None or claims_a[k].confidence != v.confidence for k, v in claims_b.items()), n)
    result.gate("evidence_reference_mutation", sum(
        claims_a.get(k) is None or claims_a[k].evidence_ids != v.evidence_ids or claims_a[k].counter_evidence_ids != v.counter_evidence_ids
        for k, v in claims_b.items()) + int(a.evidence != b.evidence), n + 1)
    result.gate("project_score_mutation", a.scores != b.scores)
    result.gate("automatic_project_score_update", a.scores != b.scores)
    result.gate("trust_gate_mutation", a.trust_gate != b.trust_gate)
    result.gate("evaluation_status_mutation", a.evaluation_status != b.evaluation_status)
    rb, ra = before.active_research_run, after.active_research_run
    result.gate("phase2c_evidence_mutation", ra.evidence_extraction != rb.evidence_extraction)
    result.gate("phase2d_alignment_mutation", ra.claim_evidence_alignment != rb.claim_evidence_alignment)
    result.gate("phase2e_sufficiency_mutation", ra.claim_sufficiency != rb.claim_sufficiency)
    result.gate("phase2f_scorecard_mutation", ra.claim_evidence_scoring != rb.claim_evidence_scoring)
    result.gate("phase2f_score_modified", ra.claim_evidence_scoring != rb.claim_evidence_scoring)
    result.gate("phase2g_patent_run_mutation", ra.patent_prior_art != rb.patent_prior_art)


def _product_gates(result: CaseResult, p: ProductPriorArtRun, world: CaseWorld) -> None:
    case = world.case
    # PII and dispatch validity: what actually reached the fake provider.
    dispatched = [text for text, _, _ in (world.web.requests if world.web else [])]
    result.gate("pii_leaked_to_product_query", sum(contains_pii(t, world.privacy) for t in dispatched), len(dispatched))
    planned = {q.query_text: q for q in p.planned_queries}
    invalid = sum(1 for t in dispatched if t not in planned or len(t) > 256 or re.search(r"(^|\s)-?[A-Za-z_]+:\S", t.replace('"', " ")))
    result.gate("invalid_query_dispatched", invalid, len(dispatched))
    # Observation vs artifact.
    by_artifact = {a.artifact_id: a for a in p.artifacts}
    entity_artifacts = [by_artifact[i] for e in p.entities for i in e.artifact_ids]
    result.gate("observation_treated_as_verified_product", sum(not a.fetched for a in entity_artifacts), max(len(p.observations), 1))
    # Safe fetch, independently.
    requested = world.transport.requests
    redirect_targets = {t for a in p.artifacts for t in a.redirect_chain}
    initial = [u for u in requested if u not in redirect_targets]
    result.gate("unsafe_url_fetched", sum(not independent_url_safe(u, case.product.resolver) for u in initial),
                len({o.url for o in p.observations}))
    result.gate("unsafe_redirect_followed",
                sum(not independent_url_safe(u, case.product.resolver) for u in requested if u in redirect_targets),
                max(len(redirect_targets), 1))
    limit = world.product_settings.max_artifact_bytes
    result.gate("oversized_artifact_silently_accepted", sum(a.fetched and (a.byte_length or 0) > limit for a in p.artifacts), len(p.artifacts))
    fetched = [a for a in p.artifacts if a.fetched]
    vendor_hosts = {v.host for v in case.product.vendors}
    on_marketplace = [a for a in fetched if any(a.host == m or a.host.endswith("." + m) for m in MARKETPLACE_SUFFIXES)]
    result.gate("marketplace_labeled_first_party", sum(a.source_role.value.startswith("FIRST_PARTY") for a in on_marketplace), max(len(on_marketplace), 1))
    result.gate("third_party_labeled_first_party",
                sum(a.source_role.value.startswith("FIRST_PARTY") and not any(a.host == h or a.host.endswith("." + h) for h in vendor_hosts) for a in fetched),
                len(fetched))
    # Identity, re-derived from the stored identifiers with an independent GTIN check.
    def keys(artifact) -> set[str]:
        out = set()
        for i in artifact.identifiers:
            if i.kind.value == "GTIN" and independent_gtin_ok(i.value):
                out.add("gtin:" + i.value.zfill(14))
            elif i.kind.value in ("MANUFACTURER_PART_NUMBER", "MANUFACTURER_MODEL_NUMBER") and i.brand:
                out.add(i.kind.value + ":" + re.sub(r"[^0-9a-z]", "", i.brand.casefold()) + ":" + re.sub(r"[^0-9a-z]", "", i.value.casefold()))
            elif i.kind.value == "APP_PACKAGE_ID":
                out.add("app:" + i.value.lower())
        return out

    unjustified = 0
    for entity in p.entities:
        members = [by_artifact[i] for i in entity.artifact_ids]
        if len(members) < 2:
            continue
        reached, frontier = {members[0].artifact_id}, [members[0]]
        while frontier:
            cur = frontier.pop()
            for other in members:
                if other.artifact_id not in reached and keys(cur) & keys(other):
                    reached.add(other.artifact_id)
                    frontier.append(other)
        unjustified += len(reached) != len(members)
    result.gate("title_only_product_collapse", unjustified, max(len(p.entities), 1))
    probable = [e for e in p.entities if e.identity_status.value == "PROBABLE_IDENTITY"]
    result.gate("probable_identity_destructively_merged",
                sum(len(e.artifact_ids) > 1 for e in probable), max(len(probable), 1))
    # Phase 2H.1, re-derived from bytes and independently validated keys only.
    dup_hashes = {h for h, n in Counter(a.content_hash for a in fetched).items() if h and n > 1}
    owner_of = {a: e.entity_id for e in p.entities for a in e.artifact_ids}
    by_entity = {e.entity_id: e for e in p.entities}
    content_merges = 0
    collapsed = 0
    for entity in p.entities:
        members = [by_artifact[i] for i in entity.artifact_ids]
        if len(members) < 2:
            continue
        key_linked, frontier = {members[0].artifact_id}, [members[0]]
        while frontier:
            cur = frontier.pop()
            for other in members:
                if other.artifact_id not in key_linked and keys(cur) & keys(other):
                    key_linked.add(other.artifact_id)
                    frontier.append(other)
        content_merges += len(key_linked) != len(members) and len({a.content_hash for a in members}) < len(members)
        all_keys = {k for a in members for k in keys(a)}
        collapsed += any(len({k for k in all_keys if k.startswith(kind)}) > 1
                         for kind in ("gtin:", "app:", "MANUFACTURER_PART_NUMBER:", "MANUFACTURER_MODEL_NUMBER:"))
    # Denominators below count real opportunities only; a case with none adds zero.
    result.gate("content_hash_product_merge", content_merges, len(dup_hashes))
    distinct_pairs = 0
    for kind in ("gtin:", "app:", "MANUFACTURER_PART_NUMBER:", "MANUFACTURER_MODEL_NUMBER:"):
        n_keys = len({k for a in fetched for k in keys(a) if k.startswith(kind)})
        distinct_pairs += n_keys * (n_keys - 1) // 2
    result.gate("distinct_strong_ids_collapsed", collapsed, distinct_pairs)
    verified = [e for e in p.entities if e.identity_status.value == "VERIFIED_STRONG_IDENTITY"]
    def backs(identifier, key: str | None) -> bool:
        """An identifier on the page that independently justifies ``key``."""
        if identifier.strong_key != key:
            return False
        if identifier.kind.value == "GTIN":
            return independent_gtin_ok(identifier.value)
        if identifier.kind.value in ("MANUFACTURER_PART_NUMBER", "MANUFACTURER_MODEL_NUMBER"):
            return bool(identifier.brand)
        return identifier.kind.value == "APP_PACKAGE_ID"

    result.gate("content_hash_as_verified_identity",
                sum(not any(backs(i, e.identity_key) for a in e.artifact_ids for i in by_artifact[a].identifiers)
                    for e in verified),
                len(verified))
    dup_pairs = lost = 0
    for h in sorted(dup_hashes):
        owners = sorted({owner_of[a.artifact_id] for a in fetched if a.content_hash == h and a.artifact_id in owner_of}, key=str)
        for i, x in enumerate(owners):
            for y in owners[i + 1:]:
                dup_pairs += 1
                lost += not any(l.other_entity_id == y and l.basis.value == "IDENTICAL_CONTENT_HASH"
                                for l in by_entity[x].probable_links)
    result.gate("duplicate_content_relation_lost", lost, dup_pairs)
    key_owner: dict[str, set] = defaultdict(set)
    for entity in p.entities:
        if entity.identity_status.value == "VERIFIED_STRONG_IDENTITY":
            for a in entity.artifact_ids:
                for k in keys(by_artifact[a]):
                    key_owner[k].add(entity.entity_id)
    result.gate("duplicate_listing_inflated_count", sum(len(v) > 1 for v in key_owner.values()), max(len(key_owner), 1))
    # Candidate content.
    for candidate in p.candidates:
        dump = candidate.model_dump_json()
        result.gate("search_rank_as_novelty_score", bool(FORBIDDEN_KEY_PATTERNS["novelty_score_produced"].search(dump)))
        result.gate("popularity_as_novelty_score", bool(POPULARITY.search(dump)))
        chronology = candidate.chronology
        dated = chronology.qualification.value.startswith("DATED_")
        result.gate("dated_product_as_legal_prior_art",
                    dated and "LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED" not in {l.value for l in candidate.limitations}
                    or bool(FORBIDDEN_KEY_PATTERNS["legal_prior_art_conclusion_produced"].search(dump)))
        # Independent chronology: earliest qualifying date of the candidate's own artifacts.
        dates = [d for s in candidate.artifacts for d in (s.dates.page_published_date, s.dates.vendor_launch_date,
                                                          s.dates.vendor_availability_date, s.dates.marketplace_listing_date) if d]
        expected_value = min(dates) if dates else None
        retrieval = {s.dates.retrieved_at.date().isoformat() for s in candidate.artifacts}
        result.gate("current_page_as_historical_proof",
                    chronology.proves_historical_availability or chronology.date_value != expected_value
                    or (chronology.date_value in retrieval and expected_value is None))
        result.gate("candidate_type_conflation", candidate.candidate_type != "PRODUCT")
        for gate, pattern in FORBIDDEN_KEY_PATTERNS.items():
            result.gate(gate, bool(pattern.search(dump)))
    # Boundedness.
    remainder = any(e.provider_reports_more or e.provider_incomplete_results for e in p.executions) or p.budget.truncated
    failed = any(e.failed for e in p.executions)
    complete = p.coverage_status.value == "COMPLETE_WITHIN_CONFIGURED_BOUNDS"
    result.gate("provider_limit_silently_truncated", complete and remainder, 1 if remainder else 0)
    result.gate("partial_product_search_reported_complete", complete and (remainder or failed or bool(p.excluded_claims and any(
        e.reason.value == "CLAIM_BUDGET_EXCEEDED" for e in p.excluded_claims))))
    errored = [e for e in p.executions if e.errors and e.errors[-1].attempt == e.attempts and not e.errors[-1].retryable or e.status.value == "FAILED"]
    result.gate("failed_query_reported_successful",
                sum(e.status.value != "FAILED" and bool(e.errors) and e.errors[-1].attempt == e.attempts for e in p.executions),
                max(len(errored), 1))
    result.gate("unbounded_recursive_expansion",
                sum(q.expansion_depth != 0 for q in p.planned_queries) + int(len(p.planned_queries) > p.budget.max_queries_per_run),
                max(len(p.planned_queries), 1))
    result.gate("documented_only_reported_live",
                sum(c.access_status is DiscoveryProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED for c in p.provider_capabilities),
                len(p.provider_capabilities))


def _oss_gates(result: CaseResult, o: OpenSourcePriorArtRun, world: CaseWorld) -> None:
    case = world.case
    dispatched = [q for kind, q in (world.github.requests if world.github else []) if kind in ("repo", "code")]
    result.gate("pii_leaked_to_github_query", sum(contains_pii(t, world.privacy) for t in dispatched), len(dispatched))
    planned = {q.query_text for q in o.planned_queries}
    result.gate("invalid_query_dispatched", sum(t not in planned for t in dispatched), len(dispatched))
    specs = {spec.get("rid"): spec for spec in case.oss.repos.values() if "rid" in spec}
    # A verified repository must match scripted provider metadata BY ID.
    result.gate("observation_treated_as_verified_repository",
                sum(r.repository_id not in specs for r in o.repositories), max(len(o.observations), 1))
    result.gate("owner_name_instead_of_stable_id",
                sum(r.repository_key != f"github:{r.repository_id}" for r in o.repositories)
                + sum(c.repository_key != f"github:{c.repository_id}" for c in o.candidates),
                max(len(o.repositories) + len(o.candidates), 1))
    verified_obs_ids = {ob.repository_id for ob in o.observations if ob.repository_id in {r.repository_id for r in o.repositories}}
    code_obs = [ob for ob in o.observations if ob.operation.value == "CODE_SEARCH"]
    result.gate("code_hits_inflated_repo_count", int(len(o.repositories) != len(verified_obs_ids)), max(len(code_obs), 1))
    # Relationships re-derived from the scripted metadata.
    for candidate in o.candidates:
        spec = specs.get(candidate.repository_id, {})
        expected = _expected_relationship(spec)
        result.gate("name_similarity_inferred_relation", candidate.relationship.value != expected)
        if expected == "FORK":
            result.gate("fork_counted_as_independent_root", candidate.counts_as_independent_root)
        if expected == "MIRROR":
            result.gate("mirror_counted_as_independent_root", candidate.counts_as_independent_root)
        dump = candidate.model_dump_json()
        field = candidate.chronology.date_field_used
        limitations = {l.value for l in candidate.limitations}
        if field is not None and field.value == "REPOSITORY_CREATED_AT":
            result.gate("created_at_as_public_since",
                        candidate.chronology.proves_public_availability or "CREATED_AT_NOT_PROVEN_PUBLIC_SINCE" not in limitations)
        if field is not None and field.value.startswith("COMMIT_"):
            result.gate("commit_date_as_public_availability",
                        candidate.chronology.proves_public_availability or "COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY" not in limitations)
        result.gate("stars_as_novelty_strength", bool(POPULARITY.search(dump)))
        result.gate("license_as_reuse_permission",
                    candidate.license.grants_reuse_permission is not None or "LICENSE_IS_NOT_REUSE_PERMISSION" not in limitations)
        result.gate("candidate_type_conflation", candidate.candidate_type != "OPEN_SOURCE")
        for gate, pattern in FORBIDDEN_KEY_PATTERNS.items():
            result.gate(gate, bool(pattern.search(dump)))
        # Independent chronology value from the stored provider dates.
        repo = o.repository(candidate.repository_key)
        published = sorted(_date_of(r.published_at) for r in repo.dates.releases if r.published_at and not r.draft)
        value = published[0] if published else None
        if value is not None:
            result.gate("current_page_as_historical_proof", candidate.chronology.date_value != value)
    # Independent root count from scripted metadata.
    roots: set[int] = set()
    for repository in o.repositories:
        spec = specs.get(repository.repository_id, {})
        kind = _expected_relationship(spec)
        if kind == "FORK":
            roots.add((spec.get("source") or spec.get("parent"))[0])
        elif kind == "TEMPLATE_DERIVATIVE":
            roots.add(spec["template"][0])
        elif kind == "ROOT_REPOSITORY":
            roots.add(repository.repository_id)
    forks = [r for r in o.repositories if r.is_fork]
    result.gate("fork_counted_as_independent_root", int(o.independent_root_count > len(roots)), max(len(forks), 1))
    for snapshot in o.snapshots:
        result.gate("code_snippet_as_full_snapshot",
                    snapshot.kind.value == "CODE_SEARCH_FRAGMENT" and snapshot.is_full_file
                    or snapshot.content_hash != hashlib.sha256(snapshot.text.encode()).hexdigest())
    remainder = any(e.provider_reports_more or e.provider_incomplete_results for e in o.executions) or o.budget.truncated
    failed = any(e.failed for e in o.executions) or any(r.reason.value == "OPERATION_REQUIRES_AUTHENTICATION" for r in o.rejected_queries)
    complete = o.coverage_status.value == "COMPLETE_WITHIN_CONFIGURED_BOUNDS"
    result.gate("provider_limit_silently_truncated", complete and remainder, 1 if remainder else 0)
    result.gate("partial_oss_search_reported_complete", complete and (remainder or failed))
    result.gate("failed_query_reported_successful",
                sum(e.status.value != "FAILED" and bool(e.errors) and e.errors[-1].attempt == e.attempts for e in o.executions),
                max(sum(1 for e in o.executions if e.errors), 1))
    result.gate("unbounded_recursive_expansion",
                sum(q.expansion_depth != 0 for q in o.planned_queries) + int(len(o.planned_queries) > o.budget.max_queries_per_run),
                max(len(o.planned_queries), 1))
    result.gate("documented_only_reported_live",
                sum(c.access_status is DiscoveryProviderAccessStatus.IMPLEMENTED_AND_LIVE_VERIFIED for c in o.provider_capabilities),
                len(o.provider_capabilities))


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def _rejects(build: Callable[[], Any]) -> bool:
    try:
        build()
    except (ValueError, TypeError):
        return True
    return False


def _foreign() -> tuple[ProductPriorArtRun, OpenSourcePriorArtRun]:
    from src.research.discovery.fakes import (
        FakeFetchTransport, FakeGitHubProvider, FakeResolver, FakeWebSearchProvider, github_repo, html_page,
    )
    from src.research.discovery.safe_fetch import SafeWebFetcher
    from src.research.open_source.pipeline import run_oss_pipeline
    from src.research.patent.planner import PlannableClaim
    from src.research.product.pipeline import run_product_pipeline

    claim = [PlannableClaim("C-001", "A foreign soil moisture controller with sensors")]
    p = run_product_pipeline(
        uuid4(), claim, FakeWebSearchProvider({"*": [{"url": "https://foreign.example.com/x"}]}),
        SafeWebFetcher(FakeFetchTransport({"https://foreign.example.com/x": html_page(
            '<title>F</title><script type="application/ld+json">{"@type":"Product","gtin13":"4006381333931"}</script><p>f</p>')}),
            resolver=FakeResolver()),
    )
    o = run_oss_pipeline(uuid4(), claim, FakeGitHubProvider(search={"*": [{"id": 999, "full_name": "f/x"}]}, repos={"f/x": github_repo(999, "f/x")}))
    return p, o


def _with(model, **changes):
    return type(model).model_validate({**dict(model), **changes})


def apply_controls(result: CaseResult, run: ResearchRun) -> None:
    p, o = run.product_prior_art, run.open_source_prior_art
    names = result.case.negative_controls
    controls: list[tuple[str, str, Callable[[], Any]]] = []
    if "cross_run" in names:
        fp, fo = _foreign()
        controls += [
            ("cross_run_query", "cross_run_query_accepted", lambda: _with(p, planned_queries=[*p.planned_queries, *fp.planned_queries])),
            ("cross_run_query_oss", "cross_run_query_accepted", lambda: _with(o, planned_queries=[*o.planned_queries, *fo.planned_queries])),
            ("cross_run_artifact", "cross_run_product_artifact_accepted", lambda: _with(p, artifacts=[*p.artifacts, *fp.artifacts])),
            ("cross_run_entity", "cross_run_product_entity_accepted", lambda: _with(p, entities=[*p.entities, *fp.entities])),
            ("cross_run_repository", "cross_run_repository_accepted", lambda: _with(o, repositories=[*o.repositories, *fo.repositories])),
            ("cross_run_network", "cross_run_network_accepted", lambda: _with(o, networks=[*o.networks, *fo.networks])),
            ("cross_run_subrun", "cross_run_query_accepted", lambda: _with(run, product_prior_art=fp)),
        ]
    if "duplicate_candidate" in names:
        controls += [
            ("duplicate_product_candidate", "duplicate_product_candidate_accepted", lambda: _with(p, candidates=p.candidates * 2)),
            ("duplicate_oss_candidate", "duplicate_oss_candidate_accepted", lambda: _with(o, candidates=o.candidates * 2)),
            ("duplicate_repository", "code_hits_inflated_repo_count", lambda: _with(o, repositories=o.repositories * 2)),
            ("duplicate_strong_entity", "duplicate_listing_inflated_count", lambda: _split_strong(p)),
        ]
    if "fork_independent" in names:
        fork = next(c for c in o.candidates if c.relationship.value == "FORK")
        controls.append(("fork_independent", "fork_counted_as_independent_root",
                         lambda: type(fork).model_validate({**fork.model_dump(), "counts_as_independent_root": True})))
        root = next(r for r in o.repositories if not r.is_fork)
        controls.append(("mirror_without_basis", "mirror_counted_as_independent_root", lambda: _with(
            o, networks=[n.model_copy(update={"members": [m.model_copy(update={"relationship": m.relationship.MIRROR, "basis": m.basis.PROVIDER_DECLARED_MIRROR_URL})
                                                         if m.repository_key == root.repository_key else m for m in n.members]}) for n in o.networks])))
        controls.append(("name_inferred_fork", "name_similarity_inferred_relation", lambda: _with(
            o, networks=[n.model_copy(update={"members": [m.model_copy(update={"relationship": m.relationship.FORK, "basis": m.basis.PROVIDER_DECLARED_PARENT})
                                                         if m.repository_key == root.repository_key else m for m in n.members]}) for n in o.networks])))
    if "first_party_marketplace" in names:
        listing = next(a for a in p.artifacts if a.source_role.value == "MARKETPLACE_LISTING")
        controls.append(("first_party_marketplace", "marketplace_labeled_first_party",
                         lambda: type(listing).model_validate({**listing.model_dump(), "source_role": "FIRST_PARTY_PRODUCT_PAGE"})))
        controls.append(("third_party_first_party", "third_party_labeled_first_party",
                         lambda: type(listing).model_validate({**listing.model_dump(), "source_role": "FIRST_PARTY_DOCUMENTATION", "source_role_basis": "KNOWN_MARKETPLACE_HOST"})))
        controls.append(("observation_as_artifact", "observation_treated_as_verified_product",
                         lambda: type(listing).model_validate({**listing.model_dump(), "fetch_status": "FETCH_BLOCKED", "error_kind": "FETCH_BLOCKED"})))
    if "title_merge" in names:
        controls.append(("title_merge", "title_only_product_collapse", lambda: _merge_unrelated(p)))
        controls.append(("probable_merge", "probable_identity_destructively_merged", lambda: _merge_unrelated(p)))
    if "content_merge" in names:
        controls.append(("content_merge", "content_hash_product_merge", lambda: _merge_duplicates(p, verified=False)))
        controls.append(("content_verified", "content_hash_as_verified_identity", lambda: _merge_duplicates(p, verified=True)))
        controls.append(("duplicate_link_dropped", "duplicate_content_relation_lost", lambda: _drop_content_links(p)))
    if "distinct_ids_merge" in names:
        controls.append(("distinct_ids_merge", "distinct_strong_ids_collapsed",
                         lambda: _merge_duplicates(p, verified=True, conflicted=True)))
    if "complete_with_truncation" in names:
        truncated_p = p.budget.model_copy(update={"results_truncated": 1})
        truncated_o = o.budget.model_copy(update={"pages_truncated": 1})
        controls += [
            ("complete_product", "partial_product_search_reported_complete",
             lambda: _with(p, budget=truncated_p, coverage_status="COMPLETE_WITHIN_CONFIGURED_BOUNDS")),
            ("complete_oss", "partial_oss_search_reported_complete",
             lambda: _with(o, budget=truncated_o, coverage_status="COMPLETE_WITHIN_CONFIGURED_BOUNDS")),
            ("silent_truncation", "provider_limit_silently_truncated",
             lambda: _with(o, executions=[e.model_copy(update={"provider_reports_more": True}) for e in o.executions],
                           coverage_status="COMPLETE_WITHIN_CONFIGURED_BOUNDS")),
            ("failed_as_success", "failed_query_reported_successful",
             lambda: type(o.executions[0]).model_validate({**o.executions[0].model_dump(), "status": "FAILED", "errors": []})),
            ("recursive_expansion", "unbounded_recursive_expansion",
             lambda: type(o.planned_queries[0]).model_validate({**o.planned_queries[0].model_dump(), "expansion_depth": 1})),
        ]
    if "owner_name_key" in names:
        repo = o.repositories[0]
        controls.append(("owner_name_key", "owner_name_instead_of_stable_id",
                         lambda: type(repo).model_validate({**repo.model_dump(), "repository_key": f"github:{repo.full_name}"})))
        controls.append(("observation_as_repository", "observation_treated_as_verified_repository",
                         lambda: type(repo).model_validate({**repo.model_dump(), "observation_ids": []})))
    if "fragment_full_file" in names:
        fragment = next(s for s in o.snapshots if s.kind.value == "CODE_SEARCH_FRAGMENT")
        controls.append(("fragment_full_file", "code_snippet_as_full_snapshot",
                         lambda: type(fragment).model_validate({**fragment.model_dump(), "is_full_file": True})))
    if "license_permission" in names:
        candidate = o.candidates[0]
        controls.append(("license_permission", "license_as_reuse_permission",
                         lambda: type(candidate.license).model_validate({**candidate.license.model_dump(), "grants_reuse_permission": True})))
    if "created_at_public" in names:
        chronology = o.candidates[0].chronology
        controls.append(("created_at_public", "created_at_as_public_since",
                         lambda: type(chronology).model_validate({**chronology.model_dump(), "proves_public_availability": True})))
        controls.append(("commit_public", "commit_date_as_public_availability",
                         lambda: type(chronology).model_validate({**chronology.model_dump(), "date_field_used": "COMMIT_COMMITTED_AT", "proves_public_availability": True})))
        product_chronology = p.candidates[0].chronology
        controls.append(("historical_proof", "current_page_as_historical_proof",
                         lambda: type(product_chronology).model_validate({**product_chronology.model_dump(), "proves_historical_availability": True})))
    if "verdict_field" in names:
        pc, oc = p.candidates[0], o.candidates[0]
        for field_name, gate in (("novelty_score", "novelty_score_produced"), ("not_novel", "novelty_verdict_produced"),
                                 ("same_invention", "same_invention_verdict_produced"), ("copied", "plagiarism_verdict_produced"),
                                 ("legal_prior_art", "legal_prior_art_conclusion_produced"), ("infringes", "patentability_infringement_fto_produced"),
                                 ("project_score_penalty", "automatic_project_score_update"), ("stars_weight", "stars_as_novelty_strength"),
                                 ("rank_score", "search_rank_as_novelty_score"), ("popularity_weight", "popularity_as_novelty_score")):
            controls.append((f"verdict_{field_name}", gate, lambda f=field_name: type(pc).model_validate({**pc.model_dump(), f: 1})))
            controls.append((f"verdict_oss_{field_name}", gate, lambda f=field_name: type(oc).model_validate({**oc.model_dump(), f: 1})))
        controls.append(("type_conflation", "candidate_type_conflation", lambda: _with(o, candidates=[*o.candidates, pc])))
        controls.append(("type_label", "candidate_type_conflation",
                         lambda: type(pc).model_validate({**pc.model_dump(), "candidate_type": "OPEN_SOURCE"})))
        controls.append(("dated_legal", "dated_product_as_legal_prior_art",
                         lambda: type(pc).model_validate({**pc.model_dump(), "limitations": [l for l in pc.limitations if l.value != "LEGAL_PRIOR_ART_STATUS_NOT_DETERMINED"]})))
        controls.append(("pii_rejection_text", "pii_leaked_to_product_query",
                         lambda: type(_pii_rejection()).model_validate({**_pii_rejection().model_dump(), "query_text": "Noura Alqahtani soil"})))
        controls.append(("pii_rejection_text_oss", "pii_leaked_to_github_query",
                         lambda: type(_pii_rejection()).model_validate({**_pii_rejection().model_dump(), "track": "OPEN_SOURCE", "detail": "a@b.example"})))
        controls.append(("invalid_dispatch", "invalid_query_dispatched",
                         lambda: type(o.planned_queries[0]).model_validate({**o.planned_queries[0].model_dump(), "query_text": "x" * 300})))
        controls.append(("oversized", "oversized_artifact_silently_accepted",
                         lambda: type(p.artifacts[0]).model_validate({**p.artifacts[0].model_dump(), "text_snapshot": "x" * 60_000})))
        controls.append(("unsafe_fetched", "unsafe_url_fetched",
                         lambda: type(p.artifacts[0]).model_validate({**p.artifacts[0].model_dump(), "fetch_status": "FETCH_UNSAFE", "error_kind": "FETCH_UNSAFE"})))
        controls.append(("unsafe_redirect", "unsafe_redirect_followed",
                         lambda: type(p.artifacts[0]).model_validate({**p.artifacts[0].model_dump(), "fetch_status": "FETCH_UNSAFE", "error_kind": None})))
    if "live_status" in names:
        capability = o.provider_capabilities[0]
        controls.append(("live_status", "documented_only_reported_live",
                         lambda: type(capability).model_validate({**capability.model_dump(), "access_status": "IMPLEMENTED_AND_LIVE_VERIFIED"})))
    for name, gate, build in controls:
        rejected = _rejects(build)
        result.controls.append((name, rejected))
        result.gate(gate, not rejected)


def _pii_rejection():
    from src.schemas.discovery import DiscoveryQueryRejectionReason, DiscoveryTrack, RejectedDiscoveryQuery

    return RejectedDiscoveryQuery(track=DiscoveryTrack.PRODUCT, reason=DiscoveryQueryRejectionReason.PII_DETECTED)


def _split_strong(p: ProductPriorArtRun) -> Any:
    """Split one verified multi-listing entity into two that both claim its key."""
    entity = next(e for e in p.entities if e.identity_key and len(e.artifact_ids) > 1)
    first = entity.model_copy(update={"artifact_ids": entity.artifact_ids[:1], "grouping_basis": "SINGLE_ARTIFACT"})
    second = entity.model_copy(update={"entity_id": uuid4(), "artifact_ids": entity.artifact_ids[1:2], "grouping_basis": "SINGLE_ARTIFACT"})
    others = [e for e in p.entities if e.entity_id != entity.entity_id]
    return _with(p, entities=[*others, first, second], candidates=[])


def _merge_unrelated(p: ProductPriorArtRun) -> Any:
    """Merge two entities whose artifacts share no strong key and no content."""
    by_artifact = {a.artifact_id: a for a in p.artifacts}
    entities = list(p.entities)
    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            ka = {k for x in a.artifact_ids for k in by_artifact[x].strong_keys}
            kb = {k for x in b.artifact_ids for k in by_artifact[x].strong_keys}
            ha = {by_artifact[x].content_hash for x in a.artifact_ids}
            hb = {by_artifact[x].content_hash for x in b.artifact_ids}
            if not ka & kb and not ha & hb:
                merged = a.model_copy(update={"artifact_ids": [*a.artifact_ids, *b.artifact_ids],
                                              "grouping_basis": "SHARED_STRONG_IDENTIFIER", "identity_status": "UNRESOLVED_IDENTITY",
                                              "identity_key": None, "strong_identifiers": [], "probable_links": []})
                return _with(p, entities=[merged], candidates=[])
    # No unrelated pair: forge one from a single entity and a fabricated artifact id.
    forged = entities[0].model_copy(update={"artifact_ids": [*entities[0].artifact_ids, uuid4()], "grouping_basis": "SHARED_STRONG_IDENTIFIER"})
    return _with(p, entities=[forged], candidates=[])


def _merge_duplicates(p: ProductPriorArtRun, *, verified: bool, conflicted: bool = False) -> Any:
    """Collapse two separate entities whose artifacts are byte-identical (Phase 2H.1).

    ``verified`` forges a strong identity for the merge, borrowing a member's
    key when one exists; ``conflicted`` picks a pair carrying different strong
    keys of one kind.
    """
    by_artifact = {a.artifact_id: a for a in p.artifacts}
    entities = list(p.entities)
    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            ha = {by_artifact[x].content_hash for x in a.artifact_ids}
            hb = {by_artifact[x].content_hash for x in b.artifact_ids}
            if not ha & hb or (conflicted and not (a.conflicting_strong_keys or b.conflicting_strong_keys)):
                continue
            ids = [*a.artifact_ids, *b.artifact_ids]
            update: dict[str, Any] = {"artifact_ids": ids, "probable_links": []}
            if verified:
                keys = sorted({k for x in ids for k in by_artifact[x].strong_keys})
                key = keys[0] if keys else "gtin:00000000000000"
                found = [ident for x in ids for ident in by_artifact[x].identifiers if ident.strong_key == key][:1]
                update.update({"identity_status": "VERIFIED_STRONG_IDENTITY", "identity_key": key, "strong_identifiers": found,
                               "conflicting_strong_keys": [], "grouping_basis": "STRONG_IDENTIFIER_AND_IDENTICAL_CONTENT"})
            else:
                update.update({"identity_status": "UNRESOLVED_IDENTITY", "identity_key": None, "strong_identifiers": [],
                               "grouping_basis": "SHARED_STRONG_IDENTIFIER"})
            others = [e for e in entities if e.entity_id not in (a.entity_id, b.entity_id)]
            return _with(p, entities=[*others, a.model_copy(update=update)], candidates=[])
    raise AssertionError("negative control needs two byte-identical entities")


def _drop_content_links(p: ProductPriorArtRun) -> Any:
    """Erase the duplicate-content relation between separate entities."""
    stripped = [
        e.model_copy(update={
            "probable_links": (kept := [l for l in e.probable_links if l.basis.value != "IDENTICAL_CONTENT_HASH"]),
            "identity_status": e.identity_status if kept or e.identity_key else "UNRESOLVED_IDENTITY",
        })
        for e in p.entities
    ]
    if stripped == list(p.entities):
        raise AssertionError("negative control needs a duplicate-content link")
    return _with(p, entities=stripped, candidates=[])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _upstream(case: ProductOssGoldCase) -> EvaluationGraphState:
    claims = [{"claim_id": c.claim_id, "claim": c.claim} for c in case.claims]
    key = json.dumps(claims, sort_keys=True, ensure_ascii=False)
    if key not in _UPSTREAM_CACHE:
        _UPSTREAM_CACHE[key] = build_phase2h_upstream(case.case_id, claims)
    return _UPSTREAM_CACHE[key].model_copy(deep=True)


def _invoke(state: EvaluationGraphState, world: CaseWorld, **kwargs: Any) -> EvaluationGraphState:
    return run_phase2h(
        state, web=world.web, fetcher=world.fetcher, github=world.github, cutoff=world.cutoff,
        registry=world.registry, privacy=world.privacy, settings=world.settings, **kwargs,
    )


def run_case(case: ProductOssGoldCase) -> CaseResult:
    result = CaseResult(case=case)
    try:
        before = _upstream(case)
        snapshot = before.model_copy(deep=True)
        world = CaseWorld(case)
        after = _invoke(before, world)
        result.summary = summarize(after, world)
        _project_gates(result, snapshot, after)
        run = after.active_research_run
        if run.product_prior_art is not None:
            _product_gates(result, run.product_prior_art, world)
        if run.open_source_prior_art is not None:
            _oss_gates(result, run.open_source_prior_art, world)
        dumped = after.model_dump_json()
        if case.oss.token:
            result.gate("provider_credential_persisted", case.oss.token in dumped)
        else:
            result.gate("provider_credential_persisted", 0)
        state: dict[str, Any] = {
            "state.project_unchanged": after.project == snapshot.project,
            "state.upstream_unchanged": all(
                getattr(run, f) == getattr(snapshot.active_research_run, f)
                for f in ("evidence_extraction", "claim_evidence_alignment", "claim_sufficiency", "claim_evidence_scoring", "patent_prior_art")
            ),
            "state.secret_absent": not (case.oss.token and case.oss.token in dumped),
            "state.types_separate": all(c.candidate_type == "PRODUCT" for c in run.product_prior_art.candidates)
            and all(c.candidate_type == "OPEN_SOURCE" for c in run.open_source_prior_art.candidates),
            "state.providers_documented_only": all(
                c.access_status is DiscoveryProviderAccessStatus.IMPLEMENTED_DOCUMENTED_ONLY
                for c in [*run.product_prior_art.provider_capabilities, *run.open_source_prior_art.provider_capabilities]
            ),
        }
        if case.rerun:
            again = _invoke(after, CaseWorld(case))
            state["state.idempotent"] = (
                again.active_research_run.product_prior_art == run.product_prior_art
                and again.active_research_run.open_source_prior_art == run.open_source_prior_art
            )
        if case.interrupt_before:
            resumed = _invoke(_upstream(case), CaseWorld(case), interrupt_before=case.interrupt_before).active_research_run
            state["state.resume_equivalent"] = (
                [c.candidate_id for c in resumed.product_prior_art.candidates] == [c.candidate_id for c in run.product_prior_art.candidates]
                and [c.candidate_id for c in resumed.open_source_prior_art.candidates] == [c.candidate_id for c in run.open_source_prior_art.candidates]
                and len(resumed.open_source_prior_art.observations) == len(run.open_source_prior_art.observations)
                and len(resumed.product_prior_art.observations) == len(run.product_prior_art.observations)
            )
        if case.negative_controls:
            apply_controls(result, run)
            state["state.negative_controls_rejected"] = all(rejected for _, rejected in result.controls)
        result.summary.update(state)
        for key, expected in case.expected.items():
            actual = _actual_for(key, result.summary)
            result.checks.append((_family(key, expected, case), key, _compare(expected, actual, key), expected, actual))
        _derived_checks(result, run, world)
    except Exception as exc:  # noqa: BLE001 -- an errored case is reported, never hidden
        import traceback

        result.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"
    return result


def _derived_checks(result: CaseResult, run: ResearchRun, world: CaseWorld) -> None:
    """Independent quality checks that do not need an authored expectation."""
    p, o = run.product_prior_art, run.open_source_prior_art
    claim_ids = {c.claim_id for c in world.case.claims}
    for query in [*p.planned_queries, *o.planned_queries]:
        result.checks.append(("query_provenance", "derived.query_traces_to_claim",
                              set(query.claim_ids) <= claim_ids and all(t.claim_id in claim_ids for t in query.terms), True, True))
    for candidate in p.candidates:
        result.checks.append(("candidate_traceability", "derived.product_candidate_refs",
                              all(q.query_id in {x.query_id for x in p.planned_queries} for q in candidate.query_provenance)
                              and set(candidate.claim_ids) <= claim_ids, True, True))
    for candidate in o.candidates:
        result.checks.append(("candidate_traceability", "derived.oss_candidate_refs",
                              set(candidate.claim_ids) <= claim_ids and o.repository(candidate.repository_key) is not None, True, True))
    fork_keys = {r.repository_key for r in o.repositories if r.is_fork}
    candidate_keys = {c.repository_key for c in o.candidates}
    for key in fork_keys:
        result.checks.append(("fork_preservation", "derived.fork_preserved", key in candidate_keys, True, True))
    for snapshot in o.snapshots:
        result.checks.append(("snapshot_provenance", "derived.snapshot_hash",
                              snapshot.content_hash == hashlib.sha256(snapshot.text.encode()).hexdigest()
                              and o.repository(snapshot.repository_key) is not None, True, True))
    for entity in p.entities:
        result.checks.append(("observation_artifact_separation", "derived.entity_artifacts_fetched",
                              all(a.fetched for a in p.artifacts if a.artifact_id in set(entity.artifact_ids)), True, True))
    for execution in [*p.executions, *o.executions]:
        result.checks.append(("provider_capability_error", "derived.failure_classified",
                              (not execution.failed) or bool(execution.errors), True, True))


__all__ = ["GATES", "CaseResult", "independent_gtin_ok", "independent_url_safe", "run_case", "summarize"]
