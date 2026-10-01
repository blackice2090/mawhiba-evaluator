"""The Phase 2H open-source stage pipeline.

    open_oss_run        capabilities, budget, cutoff, auth flag -- nothing searched
    plan_oss_stage      DiscoveryQuery list; code search refused without auth
    search_oss_stage    executions + RepositoryObservation (code hits capped per repo)
    verify_oss_stage    VerifiedRepository keyed on the numeric id; renames kept
    snapshot_oss_stage  README / description / topics / manifests / releases / fragments
    network_oss_stage   provider-declared fork / mirror / template networks
    candidate_oss_stage OpenSourcePriorArtCandidate with chronology
    finalize_oss_stage  coverage re-derived; run closed

Relationships are read from provider fields only (``fork``, ``parent``,
``source``, ``mirror_url``, ``template_repository``). A repository called
``x-fork`` or ``x-mirror`` is classified by its metadata, never its name.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from src.llm.provider import StructuredModelProvider
from src.research.academic.http import Sleeper
from src.research.discovery.capabilities import GITHUB_CAPABILITY, OPEN_SOURCE_CAPABILITIES
from src.research.discovery.execution import SearchPage, derive_coverage, derive_outcome, execute_search
from src.research.discovery.planner import plan_discovery_queries
from src.research.discovery.transport import DiscoveryTransportError, call_with_retries
from src.research.open_source.github import FileContent, GitHubProvider, RepositoryHit
from src.research.patent.planner import PlannableClaim
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext
from src.research.settings import OpenSourceResearchSettings
from src.schemas.discovery import (
    DISCOVERY_PLANNER_VERSION,
    NO_DISCOVERY_CUTOFF,
    UNIVERSAL_DISCOVERY_LIMITATIONS,
    CandidateLimitation,
    CandidateQueryProvenance,
    DiscoveryBudget,
    DiscoveryCoverageStatus,
    DiscoveryCutoff,
    DiscoveryErrorKind,
    DiscoveryOperation,
    DiscoveryOutcome,
    DiscoveryQuery,
    DiscoveryQueryRejectionReason,
    DiscoveryTrack,
    stable_id,
)
from src.schemas.open_source_prior_art import (
    MAX_SNAPSHOT_CHARS,
    CommitDateFact,
    LicenseStatus,
    OpenSourcePriorArtCandidate,
    OpenSourcePriorArtRun,
    RelationshipBasis,
    ReleaseFact,
    RepositoryChronology,
    RepositoryCutoffQualification,
    RepositoryDateFacts,
    RepositoryDateField,
    RepositoryLicense,
    RepositoryNetwork,
    RepositoryNetworkMember,
    RepositoryObservation,
    RepositoryPopularity,
    RepositoryRelationship,
    RepositorySnapshot,
    RepositorySnapshotKind,
    UnverifiedRepository,
    VerifiedRepository,
    repository_date_value,
    repository_key,
)
from src.workflow.clock import workflow_now

OSS_PIPELINE_VERSION = "OPEN-SOURCE-PIPELINE-V1"

DATE_FIELD_PRECEDENCE: tuple[RepositoryDateField, ...] = (
    RepositoryDateField.RELEASE_PUBLISHED_AT,
    RepositoryDateField.RELEASE_CREATED_AT,
    RepositoryDateField.REPOSITORY_CREATED_AT,
    RepositoryDateField.COMMIT_COMMITTED_AT,
    RepositoryDateField.COMMIT_AUTHORED_AT,
)
"""Which provider date a cutoff qualification uses, recorded on the candidate.

A published release is the nearest thing to a public act a repository record
carries, so it comes first. None of these proves public availability; the
candidate says so whichever is used (section 26).
"""


def _successor(run: OpenSourcePriorArtRun, stage: str, **changes: Any) -> OpenSourcePriorArtRun:
    """The validated successor; truncation by any stage (lookup budget,
    network budget, code-hit cap) downgrades complete coverage here."""
    markers = [*run.stage_markers, stage] if stage not in run.stage_markers else run.stage_markers
    merged = {**dict(run), **changes, "stage_markers": markers}
    if merged["coverage_status"] is DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS and merged["budget"].truncated:
        merged["coverage_status"] = DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return OpenSourcePriorArtRun.model_validate(merged)


def _budget(run: OpenSourcePriorArtRun, **changes: Any) -> DiscoveryBudget:
    return DiscoveryBudget.model_validate({**run.budget.model_dump(), **changes})


def oss_budget(settings: OpenSourceResearchSettings) -> DiscoveryBudget:
    return DiscoveryBudget(
        max_queries_per_claim=settings.max_queries_per_claim,
        max_queries_per_run=settings.max_queries_per_run,
        max_results_per_query=settings.max_results_per_query,
        max_pages_per_query=settings.max_pages_per_query,
        max_total_observations=settings.max_total_observations,
        max_detail_lookups=settings.max_repository_lookups,
        max_artifact_bytes=settings.max_content_bytes,
        max_items_per_parent=settings.max_code_hits_per_repository,
        max_network_lookups=settings.max_network_lookups,
        retry_limit=settings.retry_limit,
        timeout_seconds=settings.timeout_seconds,
    )


def open_oss_run(
    research_run_id: UUID,
    *,
    settings: OpenSourceResearchSettings,
    cutoff: DiscoveryCutoff = NO_DISCOVERY_CUTOFF,
    authenticated: bool = False,
) -> OpenSourcePriorArtRun:
    return OpenSourcePriorArtRun(
        oss_run_id=stable_id(research_run_id, "oss-run"),
        research_run_id=research_run_id,
        planner_version=DISCOVERY_PLANNER_VERSION,
        provider_capabilities=list(OPEN_SOURCE_CAPABILITIES),
        authenticated=authenticated,
        search_cutoff=cutoff,
        budget=oss_budget(settings),
        started_at=workflow_now(),
    )


def plan_oss_stage(
    run: OpenSourcePriorArtRun,
    claims: list[PlannableClaim],
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    model_provider: StructuredModelProvider | None = None,
    model: str = "",
) -> OpenSourcePriorArtRun:
    if "PLAN" in run.stage_markers:
        return run
    plan = plan_discovery_queries(
        claims,
        track=DiscoveryTrack.OPEN_SOURCE,
        research_run_id=run.research_run_id,
        max_queries_per_claim=run.budget.max_queries_per_claim,
        max_queries_per_run=run.budget.max_queries_per_run,
        results_per_query=run.budget.max_results_per_query,
        code_search_available=run.authenticated,
        privacy=privacy,
        model_provider=model_provider,
        model=model,
    )
    return _successor(
        run,
        "PLAN",
        planned_queries=plan.queries,
        rejected_queries=plan.rejected,
        excluded_claims=plan.excluded_claims,
        planner_prompt_version=next((q.model_prompt_version for q in plan.queries if q.model_prompt_version), None),
        budget=_budget(
            run,
            claims_considered=plan.claims_considered,
            claims_excluded=len(plan.excluded_claims),
            queries_planned=len(plan.queries),
            queries_rejected=len(plan.rejected),
            queries_truncated=plan.budget_rejections,
        ),
    )


def _request(provider: GitHubProvider):
    def request(query: DiscoveryQuery, page: int, count: int) -> SearchPage:
        if query.operation is DiscoveryOperation.CODE_SEARCH:
            return provider.search_code(query.query_text, page=page, count=count)
        if query.operation is DiscoveryOperation.REPOSITORY_METADATA:
            payload = provider.get_repository(query.query_text)
            rid = payload.get("id")
            name = payload.get("full_name")
            if not isinstance(rid, int) or not isinstance(name, str):
                raise DiscoveryTransportError(DiscoveryErrorKind.PARSE_ERROR, "repository has no id")
            return SearchPage(
                items=[RepositoryHit(rid, payload.get("node_id"), name, str(payload.get("html_url") or ""))]
            )
        return provider.search_repositories(query.query_text, page=page, count=count)

    return request


def _observation_factory(run: OpenSourcePriorArtRun, truncated: list[int]):
    code_hits: dict[int, int] = defaultdict(int)
    for observation in run.observations:
        if observation.operation is DiscoveryOperation.CODE_SEARCH:
            code_hits[observation.repository_id] += 1
    cap = run.budget.max_items_per_parent

    def make(query: DiscoveryQuery, page: SearchPage, first_rank: int, now: datetime) -> list[RepositoryObservation]:
        out: list[RepositoryObservation] = []
        for offset, hit in enumerate(page.items):
            code = query.operation is DiscoveryOperation.CODE_SEARCH
            if code:
                if not hit.code_path:
                    # A code hit without a path cannot be located or snapshotted;
                    # it is not accepted (returned, not accepted, is recorded).
                    continue
                if code_hits[hit.repository_id] >= cap:
                    truncated[0] += 1
                    continue
                code_hits[hit.repository_id] += 1
            rank = first_rank + offset
            out.append(
                RepositoryObservation(
                    observation_id=stable_id(run.research_run_id, "oss-obs", query.query_id, rank),
                    research_run_id=run.research_run_id,
                    query_id=query.query_id,
                    provider=query.provider,
                    operation=DiscoveryOperation.CODE_SEARCH if code else (
                        DiscoveryOperation.REPOSITORY_METADATA
                        if query.operation is DiscoveryOperation.REPOSITORY_METADATA
                        else DiscoveryOperation.REPOSITORY_SEARCH
                    ),
                    repository_id=hit.repository_id,
                    node_id=hit.node_id,
                    full_name=hit.full_name,
                    html_url=hit.html_url,
                    retrieval_rank=rank,
                    code_path=hit.code_path if code else None,
                    code_blob_sha=hit.code_sha if code else None,
                    code_fragment=hit.fragment if code else None,
                    retrieved_at=now,
                )
            )
        return out

    return make


def search_oss_stage(
    run: OpenSourcePriorArtRun,
    provider: GitHubProvider | None,
    *,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    sleeper: Sleeper | None = None,
) -> OpenSourcePriorArtRun:
    if "SEARCH" in run.stage_markers:
        return run
    if not run.planned_queries:
        return _successor(run, "SEARCH")
    if provider is None:
        return _successor(run, "SEARCH", coverage_status=DiscoveryCoverageStatus.BLOCKED_AUTH)
    truncated = [0]
    outcome = execute_search(
        run.planned_queries,
        executed_keys=run.executed_query_keys,
        budget=run.budget,
        capability=GITHUB_CAPABILITY,
        authenticated=run.authenticated,
        privacy=privacy,
        request_page=_request(provider),
        make_observations=_observation_factory(run, truncated),
        now=workflow_now,
        research_run_id=run.research_run_id,
        sleeper=sleeper,
        existing_observation_count=len(run.observations),
    )
    budget = DiscoveryBudget.model_validate(
        {**outcome.budget.model_dump(), "items_truncated_per_parent": outcome.budget.items_truncated_per_parent + truncated[0]}
    )
    executions = [*run.executions, *outcome.executions]
    # A code-search shape the planner refused for missing credentials is a part
    # of the search that never ran: it keeps coverage from reading complete.
    unauthenticated = [
        r for r in run.rejected_queries
        if r.reason is DiscoveryQueryRejectionReason.OPERATION_REQUIRES_AUTHENTICATION
    ]
    return _successor(
        run,
        "SEARCH",
        executions=executions,
        observations=[*run.observations, *outcome.observations],
        executed_query_keys=outcome.executed_keys,
        rejected_queries=[*run.rejected_queries, *outcome.refused],
        budget=budget,
        coverage_status=derive_coverage(executions, budget, [*outcome.refused, *unauthenticated]),
        outcome=derive_outcome(executions),
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def _license(raw: Any) -> RepositoryLicense:
    if raw is None:
        return RepositoryLicense(status=LicenseStatus.NO_LICENSE_DETECTED)
    if not isinstance(raw, dict):
        return RepositoryLicense(status=LicenseStatus.UNKNOWN)
    spdx = raw.get("spdx_id") if isinstance(raw.get("spdx_id"), str) else None
    key = raw.get("key") if isinstance(raw.get("key"), str) else None
    name = raw.get("name") if isinstance(raw.get("name"), str) else None
    if spdx and spdx != "NOASSERTION":
        return RepositoryLicense(status=LicenseStatus.DECLARED, spdx_id=spdx, key=key, name=name)
    return RepositoryLicense(status=LicenseStatus.UNRECOGNIZED_LICENSE, spdx_id=spdx, key=key, name=name)


def _related(raw: Any) -> tuple[int | None, str | None]:
    if isinstance(raw, dict) and isinstance(raw.get("id"), int) and raw["id"] >= 1:
        return raw["id"], raw.get("full_name") if isinstance(raw.get("full_name"), str) else None
    return None, None


def _releases(raw: list[dict[str, Any]]) -> list[ReleaseFact]:
    facts: list[ReleaseFact] = []
    for item in raw:
        rid = item.get("id")
        tag = item.get("tag_name")
        if not isinstance(rid, int) or rid < 1 or not isinstance(tag, str) or not tag:
            continue
        facts.append(
            ReleaseFact(
                release_id=rid,
                tag_name=tag[:256],
                created_at=_ts(item.get("created_at")),
                published_at=_ts(item.get("published_at")),
                draft=bool(item.get("draft")),
                prerelease=bool(item.get("prerelease")),
            )
        )
    return sorted(facts, key=lambda f: f.release_id)


def _commit(raw: dict[str, Any] | None) -> CommitDateFact | None:
    if not raw or not isinstance(raw.get("sha"), str) or len(raw["sha"]) != 40:
        return None
    commit = raw.get("commit") if isinstance(raw.get("commit"), dict) else {}
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    return CommitDateFact(
        sha=raw["sha"].lower(),
        authored_at=_ts(author.get("date")),
        committed_at=_ts(committer.get("date")),
    )


def build_verified_repository(
    payload: dict[str, Any],
    observations: list[RepositoryObservation],
    research_run_id: UUID,
    *,
    releases: list[ReleaseFact],
    head_commit: CommitDateFact | None,
    gaps: list[str],
    retrieved_at: datetime,
) -> VerifiedRepository:
    rid = payload["id"]
    full_name = payload["full_name"]
    owner, _, name = full_name.partition("/")
    is_fork = bool(payload.get("fork"))
    parent_id, parent_name = _related(payload.get("parent"))
    source_id, source_name = _related(payload.get("source"))
    template_id, _ = _related(payload.get("template_repository"))
    languages = [payload["language"]] if isinstance(payload.get("language"), str) else []
    return VerifiedRepository(
        repository_key=repository_key(rid),
        repository_id=rid,
        node_id=str(payload.get("node_id") or f"unknown-{rid}"),
        research_run_id=research_run_id,
        owner=owner,
        name=name,
        full_name=full_name,
        html_url=str(payload.get("html_url") or f"https://github.com/{full_name}"),
        observed_full_names=sorted({full_name, *(o.full_name for o in observations)}),
        visibility=payload.get("visibility") if isinstance(payload.get("visibility"), str) else None,
        is_fork=is_fork,
        parent_repository_id=parent_id if is_fork else None,
        parent_full_name=parent_name if is_fork else None,
        source_repository_id=source_id if is_fork else None,
        source_full_name=source_name if is_fork else None,
        mirror_url=payload.get("mirror_url") if isinstance(payload.get("mirror_url"), str) and payload.get("mirror_url") else None,
        is_template=bool(payload.get("is_template")),
        template_repository_id=template_id,
        archived=bool(payload.get("archived")),
        disabled=bool(payload.get("disabled")),
        default_branch=payload.get("default_branch") if isinstance(payload.get("default_branch"), str) else None,
        license=_license(payload.get("license")),
        topics=sorted(t for t in payload.get("topics") or [] if isinstance(t, str))[:50],
        primary_language=languages[0] if languages else None,
        languages=languages,
        description=str(payload["description"])[:2000] if isinstance(payload.get("description"), str) else None,
        popularity=RepositoryPopularity(
            stargazers_count=payload.get("stargazers_count") if isinstance(payload.get("stargazers_count"), int) else None,
            forks_count=payload.get("forks_count") if isinstance(payload.get("forks_count"), int) else None,
            watchers_count=payload.get("watchers_count") if isinstance(payload.get("watchers_count"), int) else None,
        ),
        dates=RepositoryDateFacts(
            created_at=_ts(payload.get("created_at")),
            updated_at=_ts(payload.get("updated_at")),
            pushed_at=_ts(payload.get("pushed_at")),
            releases=releases,
            head_commit=head_commit,
            retrieved_at=retrieved_at,
        ),
        observation_ids=sorted((o.observation_id for o in observations), key=str),
        code_hit_count=sum(1 for o in observations if o.operation is DiscoveryOperation.CODE_SEARCH),
        metadata_gaps=gaps,
    )


def verify_oss_stage(
    run: OpenSourcePriorArtRun,
    provider: GitHubProvider | None,
    *,
    settings: OpenSourceResearchSettings | None = None,
    sleeper: Sleeper | None = None,
) -> OpenSourcePriorArtRun:
    """Observations -> repositories verified by provider metadata, keyed on id."""
    if "VERIFY" in run.stage_markers:
        return run
    settings = settings or OpenSourceResearchSettings()
    grouped: dict[int, list[RepositoryObservation]] = defaultdict(list)
    for observation in sorted(run.observations, key=lambda o: (o.retrieval_rank, str(o.query_id), o.observation_id.int)):
        grouped[observation.repository_id].append(observation)
    repositories: list[VerifiedRepository] = []
    unverified: list[UnverifiedRepository] = []
    performed = 0
    truncated = 0
    for rid, observations in grouped.items():
        names = sorted({o.full_name for o in observations})
        ids = [o.observation_id for o in observations]
        if provider is None or performed >= run.budget.max_detail_lookups:
            truncated += 1
            unverified.append(UnverifiedRepository(repository_id=rid, observed_full_names=names, observation_ids=ids, budget_truncated=True))
            continue
        performed += 1
        latest = observations[-1].full_name
        outcome = call_with_retries(lambda: provider.get_repository(latest), max_attempts=run.budget.retry_limit, sleeper=sleeper)
        if not outcome.succeeded:
            unverified.append(UnverifiedRepository(repository_id=rid, observed_full_names=names, observation_ids=ids, reason=outcome.errors[-1].kind))
            continue
        payload = outcome.payload
        if not isinstance(payload.get("id"), int) or not isinstance(payload.get("full_name"), str):
            unverified.append(UnverifiedRepository(repository_id=rid, observed_full_names=names, observation_ids=ids, reason=DiscoveryErrorKind.PARSE_ERROR))
            continue
        if payload["id"] != rid:
            # The name now belongs to another repository. Identity is the id:
            # the observed repository is not silently swapped for a stranger.
            unverified.append(
                UnverifiedRepository(repository_id=rid, observed_full_names=names, observation_ids=ids, identity_mismatch_repository_id=payload["id"])
            )
            continue
        gaps: list[str] = []
        releases: list[ReleaseFact] = []
        head: CommitDateFact | None = None
        full_name = payload["full_name"]
        branch = payload.get("default_branch") if isinstance(payload.get("default_branch"), str) else None
        if settings.fetch_releases:
            got = call_with_retries(lambda: provider.list_releases(full_name, count=10), max_attempts=run.budget.retry_limit, sleeper=sleeper)
            if got.succeeded:
                releases = _releases(got.payload)
            else:
                gaps.append(f"RELEASES:{got.errors[-1].kind.value}")
        if settings.fetch_head_commit:
            got = call_with_retries(lambda: provider.get_head_commit(full_name, branch), max_attempts=run.budget.retry_limit, sleeper=sleeper)
            if got.succeeded:
                head = _commit(got.payload)
            else:
                gaps.append(f"HEAD_COMMIT:{got.errors[-1].kind.value}")
        repositories.append(
            build_verified_repository(
                payload, observations, run.research_run_id,
                releases=releases, head_commit=head, gaps=gaps, retrieved_at=workflow_now(),
            )
        )
    # Two observed ids can resolve to one current repository only through the
    # id check above, so keys stay unique; a duplicate here is a defect.
    return _successor(
        run,
        "VERIFY",
        repositories=repositories,
        unverified_repositories=unverified,
        budget=_budget(run, detail_lookups_performed=performed, detail_lookups_truncated=truncated),
    )


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _snapshot(
    run: OpenSourcePriorArtRun,
    repository: VerifiedRepository,
    kind: RepositorySnapshotKind,
    text: str,
    *,
    operation: DiscoveryOperation,
    is_full_file: bool,
    path: str | None = None,
    ref: str | None = None,
    blob_sha: str | None = None,
    original_bytes: int | None = None,
    limit: int,
) -> RepositorySnapshot:
    cap = min(limit, MAX_SNAPSHOT_CHARS)
    truncated = len(text) > cap or (original_bytes is not None and original_bytes > limit)
    stored = text[:cap]
    return RepositorySnapshot(
        snapshot_id=stable_id(run.research_run_id, "oss-snapshot", repository.repository_key, kind.value, path or "", ref or ""),
        research_run_id=run.research_run_id,
        repository_key=repository.repository_key,
        kind=kind,
        path=path,
        ref=ref,
        blob_sha=blob_sha,
        operation=operation,
        text=stored,
        content_hash=hashlib.sha256(stored.encode("utf-8")).hexdigest(),
        original_byte_length=original_bytes,
        truncated=truncated,
        is_full_file=is_full_file and not truncated,
        language=repository.primary_language if kind is RepositorySnapshotKind.CODE_SEARCH_FRAGMENT else None,
        retrieved_at=workflow_now(),
    )


def snapshot_oss_stage(
    run: OpenSourcePriorArtRun,
    provider: GitHubProvider | None,
    *,
    settings: OpenSourceResearchSettings | None = None,
    sleeper: Sleeper | None = None,
) -> OpenSourcePriorArtRun:
    if "SNAPSHOT" in run.stage_markers:
        return run
    settings = settings or OpenSourceResearchSettings()
    limit = run.budget.max_artifact_bytes
    snapshots: list[RepositorySnapshot] = []
    content_truncated = 0
    by_observation = {o.observation_id: o for o in run.observations}
    for repository in run.repositories:
        ref = repository.default_branch
        if repository.description:
            snapshots.append(_snapshot(run, repository, RepositorySnapshotKind.DESCRIPTION, repository.description,
                                       operation=DiscoveryOperation.REPOSITORY_METADATA, is_full_file=False, limit=limit))
        if repository.topics:
            snapshots.append(_snapshot(run, repository, RepositorySnapshotKind.TOPICS, ", ".join(repository.topics),
                                       operation=DiscoveryOperation.REPOSITORY_METADATA, is_full_file=False, limit=limit))
        if repository.dates.releases:
            text = json.dumps(
                [
                    {"tag": r.tag_name, "created_at": r.created_at.isoformat() if r.created_at else None,
                     "published_at": r.published_at.isoformat() if r.published_at else None}
                    for r in repository.dates.releases
                ],
                sort_keys=True,
            )
            snapshots.append(_snapshot(run, repository, RepositorySnapshotKind.RELEASE_METADATA, text,
                                       operation=DiscoveryOperation.REPOSITORY_RELEASES, is_full_file=False, limit=limit))
        if provider is not None:
            got = call_with_retries(lambda: provider.get_readme(repository.full_name, ref), max_attempts=run.budget.retry_limit, sleeper=sleeper)
            if got.succeeded and isinstance(got.payload, FileContent) and got.payload.text is not None:
                snap = _snapshot(run, repository, RepositorySnapshotKind.README, got.payload.text,
                                 operation=DiscoveryOperation.REPOSITORY_README, is_full_file=True,
                                 path=got.payload.path, ref=ref, blob_sha=got.payload.sha,
                                 original_bytes=got.payload.size, limit=limit)
                content_truncated += int(snap.truncated)
                snapshots.append(snap)
            manifests = 0
            for path in settings.manifest_paths:
                if manifests >= settings.max_manifests_per_repository:
                    break
                got = call_with_retries(lambda: provider.get_content(repository.full_name, path, ref), max_attempts=1, sleeper=sleeper)
                if not got.succeeded or not isinstance(got.payload, FileContent) or got.payload.text is None:
                    continue
                manifests += 1
                snap = _snapshot(run, repository, RepositorySnapshotKind.MANIFEST, got.payload.text,
                                 operation=DiscoveryOperation.REPOSITORY_CONTENT, is_full_file=True,
                                 path=got.payload.path, ref=ref, blob_sha=got.payload.sha,
                                 original_bytes=got.payload.size, limit=limit)
                content_truncated += int(snap.truncated)
                snapshots.append(snap)
        for observation_id in repository.observation_ids:
            observation = by_observation[observation_id]
            if observation.code_fragment:
                snapshots.append(
                    _snapshot(run, repository, RepositorySnapshotKind.CODE_SEARCH_FRAGMENT, observation.code_fragment,
                              operation=DiscoveryOperation.CODE_SEARCH, is_full_file=False,
                              path=observation.code_path, blob_sha=observation.code_blob_sha, limit=limit)
                )
    unique = list({s.snapshot_id: s for s in snapshots}.values())
    return _successor(run, "SNAPSHOT", snapshots=unique, budget=_budget(run, content_truncated=run.budget.content_truncated + content_truncated))


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------


def _relationship(repository: VerifiedRepository) -> tuple[RepositoryRelationship, RelationshipBasis, int, bool]:
    """(relationship, basis, network root id, root chain complete)."""
    if repository.is_fork:
        if repository.source_repository_id is not None:
            return RepositoryRelationship.FORK, RelationshipBasis.PROVIDER_DECLARED_SOURCE, repository.source_repository_id, True
        assert repository.parent_repository_id is not None
        return RepositoryRelationship.FORK, RelationshipBasis.PROVIDER_DECLARED_PARENT, repository.parent_repository_id, False
    if repository.mirror_url:
        return RepositoryRelationship.MIRROR, RelationshipBasis.PROVIDER_DECLARED_MIRROR_URL, repository.repository_id, True
    if repository.template_repository_id is not None:
        return (RepositoryRelationship.TEMPLATE_DERIVATIVE, RelationshipBasis.PROVIDER_DECLARED_TEMPLATE,
                repository.template_repository_id, True)
    return RepositoryRelationship.ROOT_REPOSITORY, RelationshipBasis.NO_PROVIDER_DECLARED_RELATION, repository.repository_id, True


def network_oss_stage(
    run: OpenSourcePriorArtRun,
    provider: GitHubProvider | None,
    *,
    sleeper: Sleeper | None = None,
) -> OpenSourcePriorArtRun:
    if "NETWORK" in run.stage_markers:
        return run
    members: dict[int, list[RepositoryNetworkMember]] = defaultdict(list)
    complete: dict[int, bool] = defaultdict(lambda: True)
    by_id = {r.repository_id: r for r in run.repositories}
    root_names: dict[int, str] = {}
    for repository in sorted(run.repositories, key=lambda r: r.repository_id):
        relationship, basis, root_id, chain_complete = _relationship(repository)
        members[root_id].append(
            RepositoryNetworkMember(
                repository_key=repository.repository_key,
                relationship=relationship,
                basis=basis,
                root_chain_complete=chain_complete,
            )
        )
        complete[root_id] = complete[root_id] and chain_complete
        if repository.is_fork:
            root_names.setdefault(root_id, repository.source_full_name or repository.parent_full_name or "")

    lookups = 0
    truncated = 0
    networks: list[RepositoryNetwork] = []
    for root_id in sorted(members):
        root = by_id.get(root_id)
        checked = root is not None
        root_kind: RepositoryRelationship
        if root is not None:
            kind, _, _, _ = _relationship(root)
            root_kind = RepositoryRelationship.MIRROR if kind is RepositoryRelationship.MIRROR else RepositoryRelationship.ROOT_REPOSITORY
        else:
            root_kind = RepositoryRelationship.ROOT_REPOSITORY if complete[root_id] else RepositoryRelationship.RELATION_UNKNOWN
            name = root_names.get(root_id)
            if provider is not None and name:
                if lookups < run.budget.max_network_lookups:
                    lookups += 1
                    got = call_with_retries(lambda: provider.get_repository(name), max_attempts=run.budget.retry_limit, sleeper=sleeper)
                    if got.succeeded and got.payload.get("id") == root_id:
                        checked = True
                        if got.payload.get("fork"):
                            root_kind = RepositoryRelationship.RELATION_UNKNOWN
                        elif got.payload.get("mirror_url"):
                            root_kind = RepositoryRelationship.MIRROR
                        else:
                            root_kind = RepositoryRelationship.ROOT_REPOSITORY
                else:
                    truncated += 1
        unresolved = [m.repository_key for m in members[root_id] if not m.root_chain_complete]
        networks.append(
            RepositoryNetwork(
                network_id=stable_id(run.research_run_id, "network", repository_key(root_id)),
                research_run_id=run.research_run_id,
                root_repository_id=root_id,
                root_repository_key=repository_key(root_id),
                root_retrieved_in_run=root is not None,
                root_metadata_checked=checked,
                root_kind=root_kind,
                members=members[root_id],
                unresolved_member_keys=unresolved,
                independent_root=root_kind is RepositoryRelationship.ROOT_REPOSITORY,
            )
        )
    return _successor(
        run,
        "NETWORK",
        networks=networks,
        budget=_budget(run, network_lookups_performed=lookups, network_lookups_truncated=truncated),
    )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def qualify_repository(repository: VerifiedRepository, cutoff: DiscoveryCutoff) -> RepositoryChronology:
    field = next((f for f in DATE_FIELD_PRECEDENCE if repository_date_value(repository, f) is not None), None)
    value = repository_date_value(repository, field) if field else None
    Q = RepositoryCutoffQualification
    if not cutoff.supplied:
        qualification = Q.NO_CUTOFF
    elif value is None:
        qualification = Q.ARTIFACT_DATE_UNKNOWN
    elif value < cutoff.cutoff_date:
        qualification = Q.DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF
    elif value == cutoff.cutoff_date:
        qualification = Q.DATED_REPOSITORY_ARTIFACT_ON_CUTOFF
    else:
        qualification = Q.DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF
    return RepositoryChronology(
        qualification=qualification,
        date_field_used=field,
        date_value=value,
        cutoff_date=cutoff.cutoff_date,
    )


def candidate_oss_stage(run: OpenSourcePriorArtRun) -> OpenSourcePriorArtRun:
    if "CANDIDATES" in run.stage_markers:
        return run
    by_observation = {o.observation_id: o for o in run.observations}
    by_query = {q.query_id: q for q in run.planned_queries}
    network_of = {m.repository_key: n for n in run.networks for m in n.members}
    snapshots_of: dict[str, list[UUID]] = defaultdict(list)
    for snapshot in run.snapshots:
        snapshots_of[snapshot.repository_key].append(snapshot.snapshot_id)
    candidates: list[OpenSourcePriorArtCandidate] = []
    for repository in run.repositories:
        network = network_of[repository.repository_key]
        member = next(m for m in network.members if m.repository_key == repository.repository_key)
        provenance: dict[UUID, CandidateQueryProvenance] = {}
        for observation_id in repository.observation_ids:
            observation = by_observation[observation_id]
            query = by_query[observation.query_id]
            existing = provenance.get(query.query_id)
            if existing is None or observation.retrieval_rank < existing.retrieval_rank:
                provenance[query.query_id] = CandidateQueryProvenance(
                    query_id=query.query_id,
                    purpose=query.purpose,
                    operation=query.operation,
                    language=query.language,
                    claim_ids=query.claim_ids,
                    component_ids=query.component_ids,
                    retrieval_rank=observation.retrieval_rank,
                )
        chronology = qualify_repository(repository, run.search_cutoff)
        independent = network.independent_root and member.relationship is RepositoryRelationship.ROOT_REPOSITORY
        limitations = list(UNIVERSAL_DISCOVERY_LIMITATIONS) + [CandidateLimitation.LICENSE_IS_NOT_REUSE_PERMISSION]
        if repository.license.status is not LicenseStatus.DECLARED:
            limitations.append(CandidateLimitation.LICENSE_UNKNOWN)
        if member.relationship is not RepositoryRelationship.ROOT_REPOSITORY:
            limitations.append(CandidateLimitation.NOT_AN_INDEPENDENT_ROOT)
        if member.relationship is RepositoryRelationship.FORK:
            limitations.append(CandidateLimitation.FORK_MAY_DIVERGE_FROM_ROOT)
        if chronology.date_field_used is RepositoryDateField.REPOSITORY_CREATED_AT:
            limitations.append(CandidateLimitation.CREATED_AT_NOT_PROVEN_PUBLIC_SINCE)
        if chronology.date_field_used in (RepositoryDateField.COMMIT_COMMITTED_AT, RepositoryDateField.COMMIT_AUTHORED_AT):
            limitations.append(CandidateLimitation.COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY)
        if any(by_observation[o].code_fragment for o in repository.observation_ids):
            limitations.append(CandidateLimitation.CODE_FRAGMENT_NOT_FULL_FILE)
        if repository.archived:
            limitations.append(CandidateLimitation.ARCHIVED_REPOSITORY)
        if not run.search_cutoff.supplied:
            limitations.append(CandidateLimitation.NO_CUTOFF_SUPPLIED)
        if chronology.date_value is None:
            limitations.append(CandidateLimitation.ARTIFACT_DATE_UNKNOWN)
        used = list(provenance.values())
        candidates.append(
            OpenSourcePriorArtCandidate(
                candidate_id=stable_id(run.research_run_id, "oss-candidate", repository.repository_key),
                research_run_id=run.research_run_id,
                repository_key=repository.repository_key,
                repository_id=repository.repository_id,
                full_name=repository.full_name,
                observed_full_names=repository.observed_full_names,
                network_id=network.network_id,
                network_root_key=network.root_repository_key,
                relationship=member.relationship,
                counts_as_independent_root=independent,
                archived=repository.archived,
                license=repository.license,
                topics=repository.topics,
                languages=repository.languages,
                dates=repository.dates,
                chronology=chronology,
                observation_ids=repository.observation_ids,
                code_hit_count=repository.code_hit_count,
                snapshot_ids=sorted(snapshots_of[repository.repository_key], key=str),
                query_provenance=sorted(used, key=lambda p: str(p.query_id)),
                claim_ids=sorted({c for p in used for c in p.claim_ids}),
                component_ids=sorted({c for p in used for c in p.component_ids}),
                limitations=limitations,
            )
        )
    return _successor(run, "CANDIDATES", candidates=candidates)


def finalize_oss_stage(run: OpenSourcePriorArtRun) -> OpenSourcePriorArtRun:
    if run.is_terminal:
        return run
    coverage = run.coverage_status
    if coverage is DiscoveryCoverageStatus.COMPLETE_WITHIN_CONFIGURED_BOUNDS and run.budget.truncated:
        coverage = DiscoveryCoverageStatus.PARTIAL_PROVIDER_LIMIT
    return _successor(run, "FINALIZE", coverage_status=coverage, completed_at=workflow_now())


def run_oss_pipeline(
    research_run_id: UUID,
    claims: list[PlannableClaim],
    provider: GitHubProvider | None,
    *,
    settings: OpenSourceResearchSettings | None = None,
    cutoff: DiscoveryCutoff = NO_DISCOVERY_CUTOFF,
    privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT,
    resume_from: OpenSourcePriorArtRun | None = None,
) -> OpenSourcePriorArtRun:
    settings = settings or OpenSourceResearchSettings()
    run = resume_from or open_oss_run(
        research_run_id, settings=settings, cutoff=cutoff,
        authenticated=bool(provider is not None and provider.authenticated),
    )
    run = plan_oss_stage(run, claims, privacy=privacy)
    run = search_oss_stage(run, provider, privacy=privacy)
    run = verify_oss_stage(run, provider, settings=settings)
    run = snapshot_oss_stage(run, provider, settings=settings)
    run = network_oss_stage(run, provider)
    run = candidate_oss_stage(run)
    return finalize_oss_stage(run)


__all__ = [
    "DATE_FIELD_PRECEDENCE",
    "OSS_PIPELINE_VERSION",
    "build_verified_repository",
    "candidate_oss_stage",
    "finalize_oss_stage",
    "network_oss_stage",
    "open_oss_run",
    "oss_budget",
    "plan_oss_stage",
    "qualify_repository",
    "run_oss_pipeline",
    "search_oss_stage",
    "snapshot_oss_stage",
    "verify_oss_stage",
]
