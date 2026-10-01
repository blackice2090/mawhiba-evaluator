"""Open-source prior-art research contracts -- Phase 2H OSS track (ADR-019).

The trust progression is explicit in the types:

    RepositoryObservation          a repository-search or code-search hit
    VerifiedRepository             provider metadata keyed on the STABLE id
    RepositorySnapshot             bounded README / manifest / release / fragment
    RepositoryNetwork              provider-declared fork / mirror / template lineage
    OpenSourcePriorArtCandidate    a record for a LATER comparison phase

Distinctions this module refuses to collapse:

* **code hit vs repository.** Ten hits in one repository are one repository.
* **owner/name vs identity.** ``full_name`` is mutable (rename, transfer); the
  numeric repository id is the identity, and every observed name is kept.
* **fork vs root.** A fork, a mirror and a template derivative are preserved
  individually but never counted as an independent root implementation.
  Relationships come only from provider-declared metadata, never from names.
* **created_at vs public-since.** Visibility can change; a repository's
  ``created_at`` and an old commit date are not evidence of public availability.
* **license vs permission.** License metadata is recorded as metadata. It is
  never a reuse permission, a compliance finding or a copying conclusion.
* **fragment vs file.** A code-search fragment is never a full-file snapshot.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime
from src.schemas.discovery import (
    CONTENT_HASH_PATTERN,
    DATE_PATTERN,
    CandidateLimitation,
    CandidateQueryProvenance,
    DiscoveryBudget,
    DiscoveryCoverageStatus,
    DiscoveryCutoff,
    DiscoveryErrorKind,
    DiscoveryOperation,
    DiscoveryOutcome,
    DiscoveryProvider,
    DiscoveryProviderCapability,
    DiscoveryQuery,
    DiscoveryQueryExecution,
    DiscoveryTrack,
    ExcludedDiscoveryClaim,
    RejectedDiscoveryQuery,
    coverage_is_honest,
    outcome_is_honest,
    providers_are_honest,
    require_universal_limitations,
    stable_id,
)

OSS_CONTRACT_VERSION = "OPEN-SOURCE-PRIOR-ART-CONTRACT-V1"
OSS_IDENTITY_VERSION = "REPOSITORY-IDENTITY-V1"
OSS_NETWORK_VERSION = "REPOSITORY-NETWORK-V1"
OSS_CHRONOLOGY_VERSION = "REPOSITORY-CHRONOLOGY-V1"

MAX_FRAGMENT_CHARS = 2_000
MAX_SNAPSHOT_CHARS = 100_000


def repository_key(repository_id: int) -> str:
    """The canonical repository identity. Never owner/name."""
    return f"github:{repository_id}"


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


class RepositoryObservation(MawhibaModel):
    """One repository-search or code-search hit. Not a verified implementation."""

    observation_id: UUID
    research_run_id: UUID
    query_id: UUID
    provider: DiscoveryProvider
    operation: DiscoveryOperation
    repository_id: int = Field(ge=1)
    node_id: str | None = None
    full_name: str = Field(min_length=3, pattern=r"^[^/\s]+/[^/\s]+$")
    html_url: str = ""
    retrieval_rank: int = Field(ge=1, description="Provider order. Metadata only.")
    code_path: str | None = None
    code_blob_sha: str | None = None
    code_fragment: str | None = Field(default=None, max_length=MAX_FRAGMENT_CHARS)
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def _code_fields_only_for_code_hits(self) -> RepositoryObservation:
        code = self.operation is DiscoveryOperation.CODE_SEARCH
        if not code and (self.code_path or self.code_fragment or self.code_blob_sha):
            raise ValueError("only a code-search hit carries a code path or fragment")
        if code and not self.code_path:
            raise ValueError("a code-search hit records its path")
        return self


# ---------------------------------------------------------------------------
# Verified repository
# ---------------------------------------------------------------------------


class LicenseStatus(StrEnum):
    DECLARED = "DECLARED"
    UNRECOGNIZED_LICENSE = "UNRECOGNIZED_LICENSE"
    NO_LICENSE_DETECTED = "NO_LICENSE_DETECTED"
    UNKNOWN = "UNKNOWN"


class RepositoryLicense(MawhibaModel):
    """Provider license metadata, verbatim. Never a reuse permission (section 29)."""

    status: LicenseStatus = LicenseStatus.UNKNOWN
    spdx_id: str | None = Field(default=None, max_length=64)
    key: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    grants_reuse_permission: bool | None = Field(
        default=None,
        description="Always None: Phase 2H never interprets a license.",
    )

    @model_validator(mode="after")
    def _uninterpreted(self) -> RepositoryLicense:
        if self.grants_reuse_permission is not None:
            raise ValueError("license metadata is never interpreted as reuse permission")
        if self.status is LicenseStatus.DECLARED and (
            not self.spdx_id or self.spdx_id == "NOASSERTION"
        ):
            raise ValueError("DECLARED requires a concrete SPDX id")
        if self.status in (LicenseStatus.NO_LICENSE_DETECTED, LicenseStatus.UNKNOWN) and self.spdx_id:
            raise ValueError("no SPDX id is recorded without a detected license")
        return self


class RepositoryPopularity(MawhibaModel):
    """Metadata only. Never independence, novelty, truth or score (section 30)."""

    stargazers_count: int | None = Field(default=None, ge=0)
    forks_count: int | None = Field(default=None, ge=0)
    watchers_count: int | None = Field(default=None, ge=0)


class ReleaseFact(MawhibaModel):
    release_id: int = Field(ge=1)
    tag_name: str = Field(min_length=1, max_length=256)
    created_at: UtcDatetime | None = None
    published_at: UtcDatetime | None = None
    draft: bool = False
    prerelease: bool = False


class CommitDateFact(MawhibaModel):
    """One commit's own dates. Neither proves public availability (section 26)."""

    sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    authored_at: UtcDatetime | None = None
    committed_at: UtcDatetime | None = None


class RepositoryDateFacts(MawhibaModel):
    """Section 26. Every date kept separate; retrieval date is never historical."""

    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None
    pushed_at: UtcDatetime | None = None
    releases: list[ReleaseFact] = Field(default_factory=list)
    head_commit: CommitDateFact | None = None
    retrieved_at: UtcDatetime


class VerifiedRepository(MawhibaModel):
    """Provider metadata for one repository, keyed on its stable numeric id."""

    repository_key: str = Field(pattern=r"^github:[1-9][0-9]*$")
    repository_id: int = Field(ge=1)
    node_id: str = Field(min_length=1)
    research_run_id: UUID
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    full_name: str = Field(min_length=3)
    html_url: str = Field(min_length=1)
    observed_full_names: list[str] = Field(
        min_length=1,
        description="Every owner/name this id was seen under. More than one is "
        "a rename or transfer of ONE repository, not two repositories.",
    )
    visibility: str | None = None
    is_fork: bool
    parent_repository_id: int | None = Field(default=None, ge=1)
    parent_full_name: str | None = None
    source_repository_id: int | None = Field(default=None, ge=1)
    source_full_name: str | None = None
    mirror_url: str | None = None
    is_template: bool = False
    template_repository_id: int | None = Field(default=None, ge=1)
    archived: bool = False
    disabled: bool = False
    default_branch: str | None = None
    license: RepositoryLicense = Field(default_factory=RepositoryLicense)
    topics: list[str] = Field(default_factory=list)
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=2_000)
    popularity: RepositoryPopularity = Field(default_factory=RepositoryPopularity)
    dates: RepositoryDateFacts
    observation_ids: list[UUID] = Field(min_length=1)
    code_hit_count: int = Field(default=0, ge=0, description="Metadata only.")
    metadata_gaps: list[str] = Field(
        default_factory=list,
        description="Optional lookups (releases, head commit) that failed. A gap is "
        "recorded, never filled with a guess.",
    )
    metadata_operation: DiscoveryOperation = DiscoveryOperation.REPOSITORY_METADATA
    identity_version: str = OSS_IDENTITY_VERSION

    @model_validator(mode="after")
    def _identity_holds(self) -> VerifiedRepository:
        if self.repository_key != repository_key(self.repository_id):
            raise ValueError("repository_key must derive from the stable numeric id (section 22)")
        if self.full_name != f"{self.owner}/{self.name}":
            raise ValueError("full_name must be owner/name")
        if self.full_name not in self.observed_full_names:
            raise ValueError("the current full_name must be among the observed names")
        if self.is_fork and self.parent_repository_id is None:
            raise ValueError("a fork must carry its provider-declared parent")
        if not self.is_fork and (self.parent_repository_id or self.source_repository_id):
            raise ValueError("a non-fork carries no parent or source")
        if self.repository_id in (self.parent_repository_id, self.source_repository_id):
            raise ValueError("a repository cannot be its own parent or source")
        return self

    @property
    def renamed_or_transferred(self) -> bool:
        return len(self.observed_full_names) > 1


class UnverifiedRepository(MawhibaModel):
    """A repository that was observed but whose metadata could not be fetched.

    It stays an observation: no relationship, no network, no candidate.
    """

    repository_id: int = Field(ge=1)
    observed_full_names: list[str] = Field(min_length=1)
    observation_ids: list[UUID] = Field(min_length=1)
    reason: DiscoveryErrorKind | None = None
    budget_truncated: bool = False
    identity_mismatch_repository_id: int | None = Field(
        default=None,
        ge=1,
        description="The owner/name now resolves to a DIFFERENT repository id: the "
        "name was reused. The observed repository is not silently replaced.",
    )

    @model_validator(mode="after")
    def _has_reason(self) -> UnverifiedRepository:
        stated = sum(
            (self.reason is not None, self.budget_truncated, self.identity_mismatch_repository_id is not None)
        )
        if stated != 1:
            raise ValueError("an unverified repository states exactly one reason")
        if self.identity_mismatch_repository_id == self.repository_id:
            raise ValueError("an identity mismatch names a different repository id")
        return self


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


class RepositorySnapshotKind(StrEnum):
    README = "README"
    DESCRIPTION = "DESCRIPTION"
    TOPICS = "TOPICS"
    MANIFEST = "MANIFEST"
    RELEASE_METADATA = "RELEASE_METADATA"
    CODE_SEARCH_FRAGMENT = "CODE_SEARCH_FRAGMENT"


class RepositorySnapshot(MawhibaModel):
    snapshot_id: UUID
    research_run_id: UUID
    repository_key: str = Field(pattern=r"^github:[1-9][0-9]*$")
    kind: RepositorySnapshotKind
    path: str | None = None
    ref: str | None = None
    blob_sha: str | None = None
    operation: DiscoveryOperation
    text: str = Field(max_length=MAX_SNAPSHOT_CHARS)
    content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)
    original_byte_length: int | None = Field(default=None, ge=0)
    truncated: bool = False
    is_full_file: bool
    language: str | None = None
    retrieved_at: UtcDatetime

    @model_validator(mode="after")
    def _fragment_is_not_a_file(self) -> RepositorySnapshot:
        if self.kind is RepositorySnapshotKind.CODE_SEARCH_FRAGMENT and self.is_full_file:
            raise ValueError("a code-search fragment is never a full-file snapshot (section 23)")
        if self.truncated and self.is_full_file:
            raise ValueError("a truncated snapshot is not a full file")
        if self.kind in (RepositorySnapshotKind.README, RepositorySnapshotKind.MANIFEST) and not self.path:
            raise ValueError("a file snapshot records its path")
        return self


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------


class RepositoryRelationship(StrEnum):
    ROOT_REPOSITORY = "ROOT_REPOSITORY"
    FORK = "FORK"
    MIRROR = "MIRROR"
    TEMPLATE_DERIVATIVE = "TEMPLATE_DERIVATIVE"
    RELATION_UNKNOWN = "RELATION_UNKNOWN"


class RelationshipBasis(StrEnum):
    """Provider-declared fields only. Name similarity is never a basis."""

    NO_PROVIDER_DECLARED_RELATION = "NO_PROVIDER_DECLARED_RELATION"
    PROVIDER_DECLARED_SOURCE = "PROVIDER_DECLARED_SOURCE"
    PROVIDER_DECLARED_PARENT = "PROVIDER_DECLARED_PARENT"
    PROVIDER_DECLARED_MIRROR_URL = "PROVIDER_DECLARED_MIRROR_URL"
    PROVIDER_DECLARED_TEMPLATE = "PROVIDER_DECLARED_TEMPLATE"


RELATION_BASES: dict[RepositoryRelationship, frozenset[RelationshipBasis]] = {
    RepositoryRelationship.ROOT_REPOSITORY: frozenset({RelationshipBasis.NO_PROVIDER_DECLARED_RELATION}),
    RepositoryRelationship.FORK: frozenset(
        {RelationshipBasis.PROVIDER_DECLARED_SOURCE, RelationshipBasis.PROVIDER_DECLARED_PARENT}
    ),
    RepositoryRelationship.MIRROR: frozenset({RelationshipBasis.PROVIDER_DECLARED_MIRROR_URL}),
    RepositoryRelationship.TEMPLATE_DERIVATIVE: frozenset({RelationshipBasis.PROVIDER_DECLARED_TEMPLATE}),
    RepositoryRelationship.RELATION_UNKNOWN: frozenset({RelationshipBasis.NO_PROVIDER_DECLARED_RELATION}),
}


class RepositoryNetworkMember(MawhibaModel):
    repository_key: str = Field(pattern=r"^github:[1-9][0-9]*$")
    relationship: RepositoryRelationship
    basis: RelationshipBasis
    root_chain_complete: bool = Field(
        default=True,
        description="False when only the immediate parent was declared, so the "
        "ultimate root is the parent's id rather than a provider-declared source.",
    )

    @model_validator(mode="after")
    def _basis_matches(self) -> RepositoryNetworkMember:
        if self.basis not in RELATION_BASES[self.relationship]:
            raise ValueError(f"{self.relationship.value} cannot rest on {self.basis.value}")
        return self


class RepositoryNetwork(MawhibaModel):
    """One lineage, keyed on the stable root id (section 25).

    ``independent_root`` is true only for a network whose root is a declared
    non-fork, non-mirror, non-template repository -- or the upstream a fork
    points to. Mirror-only networks never count as an independent root.
    """

    network_id: UUID
    research_run_id: UUID
    root_repository_id: int = Field(ge=1)
    root_repository_key: str = Field(pattern=r"^github:[1-9][0-9]*$")
    root_retrieved_in_run: bool
    root_metadata_checked: bool = Field(
        default=False,
        description="True when the root's own metadata was looked up (as a member "
        "or a bounded network lookup), so root_kind rests on provider data.",
    )
    root_kind: RepositoryRelationship
    members: list[RepositoryNetworkMember] = Field(min_length=1)
    unresolved_member_keys: list[str] = Field(default_factory=list)
    independent_root: bool
    network_version: str = OSS_NETWORK_VERSION

    @model_validator(mode="after")
    def _consistent(self) -> RepositoryNetwork:
        if self.root_repository_key != repository_key(self.root_repository_id):
            raise ValueError("network root key must derive from the root id")
        if self.network_id != stable_id(self.research_run_id, "network", self.root_repository_key):
            raise ValueError("network_id must be the stable id of its root")
        keys = [m.repository_key for m in self.members]
        if len(set(keys)) != len(keys):
            raise ValueError("a repository is a member of a network once")
        if any(k not in keys for k in self.unresolved_member_keys):
            raise ValueError("an unresolved member must be a member")
        roots = [m for m in self.members if m.relationship is RepositoryRelationship.ROOT_REPOSITORY]
        if roots and (len(roots) > 1 or roots[0].repository_key != self.root_repository_key):
            raise ValueError("only the network root may be its ROOT_REPOSITORY member")
        if self.root_retrieved_in_run != (self.root_repository_key in keys):
            raise ValueError("root_retrieved_in_run must match root membership")
        if self.root_kind is RepositoryRelationship.FORK:
            raise ValueError("a fork is never a network root")
        expected_independent = self.root_kind is RepositoryRelationship.ROOT_REPOSITORY
        if self.independent_root != expected_independent:
            raise ValueError(
                "only a ROOT_REPOSITORY-rooted network is an independent root; a "
                "mirror or template lineage is not, by default (section 24)"
            )
        return self


# ---------------------------------------------------------------------------
# Chronology and candidate
# ---------------------------------------------------------------------------


class RepositoryCutoffQualification(StrEnum):
    DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF = "DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF"
    DATED_REPOSITORY_ARTIFACT_ON_CUTOFF = "DATED_REPOSITORY_ARTIFACT_ON_CUTOFF"
    DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF = "DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF"
    ARTIFACT_DATE_UNKNOWN = "ARTIFACT_DATE_UNKNOWN"
    NO_CUTOFF = "NO_CUTOFF"


REPOSITORY_CUTOFF_RELATIVE: frozenset[RepositoryCutoffQualification] = frozenset(
    {
        RepositoryCutoffQualification.DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF,
        RepositoryCutoffQualification.DATED_REPOSITORY_ARTIFACT_ON_CUTOFF,
        RepositoryCutoffQualification.DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF,
    }
)


class RepositoryDateField(StrEnum):
    RELEASE_PUBLISHED_AT = "RELEASE_PUBLISHED_AT"
    RELEASE_CREATED_AT = "RELEASE_CREATED_AT"
    REPOSITORY_CREATED_AT = "REPOSITORY_CREATED_AT"
    COMMIT_COMMITTED_AT = "COMMIT_COMMITTED_AT"
    COMMIT_AUTHORED_AT = "COMMIT_AUTHORED_AT"


VISIBILITY_UNPROVEN_FIELDS: frozenset[RepositoryDateField] = frozenset(RepositoryDateField)
"""Every repository date field: none proves when the artifact became public."""


class RepositoryChronology(MawhibaModel):
    qualification: RepositoryCutoffQualification
    date_field_used: RepositoryDateField | None = None
    date_value: str | None = Field(default=None, pattern=DATE_PATTERN)
    cutoff_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    provider: DiscoveryProvider = DiscoveryProvider.GITHUB_REST
    historical_visibility_limitation: str = Field(
        default="Repository visibility can change; no provider date here proves "
        "when the artifact became publicly available.",
        min_length=1,
    )
    proves_public_availability: bool = Field(default=False, description="Always false.")

    @model_validator(mode="after")
    def _consistent(self) -> RepositoryChronology:
        if self.proves_public_availability:
            raise ValueError("no repository date proves public availability (section 26)")
        dated = self.date_field_used is not None
        if dated != (self.date_value is not None):
            raise ValueError("a used date carries its field and value together")
        if self.qualification in REPOSITORY_CUTOFF_RELATIVE:
            if self.cutoff_date is None or not dated:
                raise ValueError("a cutoff-relative qualification needs a cutoff and a dated field")
            Q = RepositoryCutoffQualification
            expected = (
                Q.DATED_REPOSITORY_ARTIFACT_BEFORE_CUTOFF
                if self.date_value < self.cutoff_date
                else Q.DATED_REPOSITORY_ARTIFACT_ON_CUTOFF
                if self.date_value == self.cutoff_date
                else Q.DATED_REPOSITORY_ARTIFACT_AFTER_CUTOFF
            )
            if expected is not self.qualification:
                raise ValueError("the qualification contradicts the dates it was derived from")
        if self.qualification is RepositoryCutoffQualification.NO_CUTOFF and self.cutoff_date:
            raise ValueError("NO_CUTOFF carries no cutoff date")
        if self.qualification is RepositoryCutoffQualification.ARTIFACT_DATE_UNKNOWN and (
            dated or self.cutoff_date is None
        ):
            raise ValueError("ARTIFACT_DATE_UNKNOWN means a cutoff exists and no artifact date does")
        return self


class OpenSourcePriorArtCandidate(MawhibaModel):
    """A repository a LATER novelty phase should inspect. Not a verdict of any kind."""

    candidate_id: UUID
    research_run_id: UUID
    candidate_type: str = Field(default="OPEN_SOURCE", pattern=r"^OPEN_SOURCE$")
    repository_key: str = Field(pattern=r"^github:[1-9][0-9]*$")
    repository_id: int = Field(ge=1)
    full_name: str
    observed_full_names: list[str] = Field(min_length=1)
    network_id: UUID
    network_root_key: str
    relationship: RepositoryRelationship
    counts_as_independent_root: bool
    archived: bool
    license: RepositoryLicense
    topics: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    dates: RepositoryDateFacts
    chronology: RepositoryChronology
    observation_ids: list[UUID] = Field(min_length=1)
    code_hit_count: int = Field(ge=0)
    snapshot_ids: list[UUID] = Field(default_factory=list)
    query_provenance: list[CandidateQueryProvenance] = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    component_ids: list[str] = Field(default_factory=list)
    limitations: list[CandidateLimitation] = Field(min_length=6)
    contract_version: str = OSS_CONTRACT_VERSION

    @model_validator(mode="after")
    def _limitations_hold(self) -> OpenSourcePriorArtCandidate:
        require_universal_limitations(self.limitations)
        if self.candidate_id != stable_id(self.research_run_id, "oss-candidate", self.repository_key):
            raise ValueError("candidate_id must be the stable id of its repository")
        if self.repository_key != repository_key(self.repository_id):
            raise ValueError("candidate repository_key must derive from the stable id")
        if CandidateLimitation.LICENSE_IS_NOT_REUSE_PERMISSION not in self.limitations:
            raise ValueError("an OSS candidate must state that license metadata is not permission")
        if self.relationship is not RepositoryRelationship.ROOT_REPOSITORY and self.counts_as_independent_root:
            raise ValueError("a fork, mirror or template derivative is not an independent root")
        if self.relationship is not RepositoryRelationship.ROOT_REPOSITORY and (
            CandidateLimitation.NOT_AN_INDEPENDENT_ROOT not in self.limitations
        ):
            raise ValueError("a non-root candidate must state NOT_AN_INDEPENDENT_ROOT")
        used = self.chronology.date_field_used
        if used in (RepositoryDateField.REPOSITORY_CREATED_AT,) and (
            CandidateLimitation.CREATED_AT_NOT_PROVEN_PUBLIC_SINCE not in self.limitations
        ):
            raise ValueError("a created_at-dated candidate must state it is not proven public-since")
        if used in (
            RepositoryDateField.COMMIT_COMMITTED_AT,
            RepositoryDateField.COMMIT_AUTHORED_AT,
        ) and CandidateLimitation.COMMIT_DATE_NOT_PROVEN_PUBLIC_AVAILABILITY not in self.limitations:
            raise ValueError("a commit-dated candidate must state it is not proven public availability")
        return self


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class OpenSourcePriorArtRun(MawhibaModel):
    """Everything the OPEN_SOURCE track produced. Lives on the ResearchRun only."""

    oss_run_id: UUID
    research_run_id: UUID
    track: DiscoveryTrack = DiscoveryTrack.OPEN_SOURCE
    outcome: DiscoveryOutcome = DiscoveryOutcome.NOT_RUN
    coverage_status: DiscoveryCoverageStatus = DiscoveryCoverageStatus.NOT_EXECUTED
    contract_version: str = OSS_CONTRACT_VERSION
    identity_version: str = OSS_IDENTITY_VERSION
    network_version: str = OSS_NETWORK_VERSION
    chronology_version: str = OSS_CHRONOLOGY_VERSION
    planner_version: str = Field(min_length=1)
    planner_prompt_version: str | None = None
    provider_capabilities: list[DiscoveryProviderCapability] = Field(min_length=1)
    authenticated: bool = Field(
        default=False,
        description="Whether the connector held credentials. The credential itself is never stored.",
    )
    search_cutoff: DiscoveryCutoff
    budget: DiscoveryBudget

    planned_queries: list[DiscoveryQuery] = Field(default_factory=list)
    executed_query_keys: list[str] = Field(default_factory=list)
    rejected_queries: list[RejectedDiscoveryQuery] = Field(default_factory=list)
    excluded_claims: list[ExcludedDiscoveryClaim] = Field(default_factory=list)
    executions: list[DiscoveryQueryExecution] = Field(default_factory=list)
    observations: list[RepositoryObservation] = Field(default_factory=list)
    repositories: list[VerifiedRepository] = Field(default_factory=list)
    unverified_repositories: list[UnverifiedRepository] = Field(default_factory=list)
    snapshots: list[RepositorySnapshot] = Field(default_factory=list)
    networks: list[RepositoryNetwork] = Field(default_factory=list)
    candidates: list[OpenSourcePriorArtCandidate] = Field(default_factory=list)
    stage_markers: list[str] = Field(default_factory=list)

    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _internally_consistent(self) -> OpenSourcePriorArtRun:
        run_id = self.research_run_id
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        for label, items in (
            ("query", self.planned_queries),
            ("execution", self.executions),
            ("observation", self.observations),
            ("repository", self.repositories),
            ("snapshot", self.snapshots),
            ("network", self.networks),
            ("candidate", self.candidates),
        ):
            if any(item.research_run_id != run_id for item in items):
                raise ValueError(f"a {label} belongs to a different research run (section 36)")
        if any(q.track is not DiscoveryTrack.OPEN_SOURCE for q in self.planned_queries):
            raise ValueError("an OSS run holds only open-source queries")

        query_ids = [q.query_id for q in self.planned_queries]
        if len(set(query_ids)) != len(query_ids):
            raise ValueError("query ids must be unique")
        known_queries = set(query_ids)
        if any(e.query_id not in known_queries for e in self.executions):
            raise ValueError("an execution references an unknown query")
        if any(o.query_id not in known_queries for o in self.observations):
            raise ValueError("an observation references an unknown query")
        observation_ids = [o.observation_id for o in self.observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("observation ids must be unique")
        by_observation = {o.observation_id: o for o in self.observations}

        keys = [r.repository_key for r in self.repositories]
        if len(set(keys)) != len(keys):
            raise ValueError(
                "a repository id is verified once; many hits are one repository (section 21)"
            )
        by_key = {r.repository_key: r for r in self.repositories}
        for repository in self.repositories:
            for observation_id in repository.observation_ids:
                observation = by_observation.get(observation_id)
                if observation is None:
                    raise ValueError("a repository references an unknown observation")
                if observation.repository_id != repository.repository_id:
                    raise ValueError("a repository groups observations of a different repository id")
            names = {by_observation[o].full_name for o in repository.observation_ids}
            if not names <= set(repository.observed_full_names):
                raise ValueError("every observed name must be preserved on the repository")
        verified_ids = {r.repository_id for r in self.repositories}
        for unverified in self.unverified_repositories:
            if unverified.repository_id in verified_ids:
                raise ValueError("a repository cannot be both verified and unverified")
            if any(o not in by_observation for o in unverified.observation_ids):
                raise ValueError("an unverified repository references an unknown observation")

        if any(s.repository_key not in by_key for s in self.snapshots):
            raise ValueError("a snapshot references an unverified repository")
        if len({s.snapshot_id for s in self.snapshots}) != len(self.snapshots):
            raise ValueError("snapshot ids must be unique")
        snapshot_ids = {s.snapshot_id for s in self.snapshots}

        member_of: dict[str, UUID] = {}
        network_ids = [n.network_id for n in self.networks]
        if len(set(network_ids)) != len(network_ids):
            raise ValueError("network ids must be unique")
        for network in self.networks:
            for member in network.members:
                if member.repository_key not in by_key:
                    raise ValueError(
                        "a network member must be a repository verified in this run (section 36)"
                    )
                if member.repository_key in member_of:
                    raise ValueError("a repository belongs to exactly one network")
                member_of[member.repository_key] = network.network_id
                _member_matches_metadata(member, by_key[member.repository_key], network)
        if self.networks and set(member_of) != set(by_key):
            raise ValueError("every verified repository belongs to exactly one network")
        by_network = {n.network_id: n for n in self.networks}

        repo_candidates = [c.repository_key for c in self.candidates]
        if len(set(repo_candidates)) != len(repo_candidates):
            raise ValueError("a repository has at most one candidate per run (section 35)")
        for candidate in self.candidates:
            repository = by_key.get(candidate.repository_key)
            if repository is None:
                raise ValueError("a candidate references an unverified repository")
            network = by_network.get(candidate.network_id)
            if network is None or member_of.get(candidate.repository_key) != candidate.network_id:
                raise ValueError("a candidate references a network it is not a member of")
            member = next(m for m in network.members if m.repository_key == candidate.repository_key)
            if candidate.relationship is not member.relationship:
                raise ValueError("a candidate must carry its network relationship unchanged")
            if candidate.counts_as_independent_root and not (
                network.independent_root
                and member.relationship is RepositoryRelationship.ROOT_REPOSITORY
            ):
                raise ValueError("only an independent network's root counts as an independent root")
            if (
                candidate.dates != repository.dates
                or candidate.license != repository.license
                or candidate.observed_full_names != repository.observed_full_names
            ):
                raise ValueError("a candidate must carry its repository's dates, license and names unchanged")
            if any(s not in snapshot_ids for s in candidate.snapshot_ids):
                raise ValueError("a candidate references an unknown snapshot")
            if any(p.query_id not in known_queries for p in candidate.query_provenance):
                raise ValueError("a candidate references an unknown query")
            if sorted(candidate.observation_ids) != sorted(repository.observation_ids):
                raise ValueError("a candidate carries exactly its repository's observations")
            chronology = candidate.chronology
            if chronology.cutoff_date not in (None, self.search_cutoff.cutoff_date):
                raise ValueError("a candidate was qualified against a different cutoff")
            if not self.search_cutoff.supplied and chronology.qualification.value != "NO_CUTOFF":
                raise ValueError("a run with no supplied cutoff can only produce NO_CUTOFF")
            if self.search_cutoff.supplied and chronology.qualification.value == "NO_CUTOFF":
                raise ValueError("a supplied cutoff must be applied")
            if chronology.date_field_used is not None and (
                repository_date_value(repository, chronology.date_field_used) != chronology.date_value
            ):
                raise ValueError("a chronology date must equal the repository's provider date")

        coverage_is_honest(self.coverage_status, self.budget, self.executions)
        outcome_is_honest(self.outcome, self.executions, bool(self.observations))
        providers_are_honest(self.provider_capabilities, {e.provider for e in self.executions})
        return self

    @property
    def is_terminal(self) -> bool:
        return self.completed_at is not None

    @property
    def independent_root_count(self) -> int:
        """Lineages, not repositories, hits, branches, releases or forks."""
        return sum(1 for n in self.networks if n.independent_root)

    def repository(self, key: str) -> VerifiedRepository | None:
        return next((r for r in self.repositories if r.repository_key == key), None)


def repository_date_value(repository: VerifiedRepository, field: RepositoryDateField) -> str | None:
    """The calendar date of one provider date field, or None."""
    dates = repository.dates
    published = [r.published_at for r in dates.releases if r.published_at and not r.draft]
    created = [r.created_at for r in dates.releases if r.created_at and not r.draft]
    value = {
        RepositoryDateField.RELEASE_PUBLISHED_AT: min(published) if published else None,
        RepositoryDateField.RELEASE_CREATED_AT: min(created) if created else None,
        RepositoryDateField.REPOSITORY_CREATED_AT: dates.created_at,
        RepositoryDateField.COMMIT_COMMITTED_AT: dates.head_commit.committed_at if dates.head_commit else None,
        RepositoryDateField.COMMIT_AUTHORED_AT: dates.head_commit.authored_at if dates.head_commit else None,
    }[field]
    return value.date().isoformat() if value is not None else None


def _member_matches_metadata(
    member: RepositoryNetworkMember, repository: VerifiedRepository, network: RepositoryNetwork
) -> None:
    """A relationship must be exactly what provider metadata declares (section 24)."""
    relationship = member.relationship
    if relationship is RepositoryRelationship.FORK:
        if not repository.is_fork:
            raise ValueError("FORK requires the provider's fork flag")
        declared_root = repository.source_repository_id or repository.parent_repository_id
        if declared_root != network.root_repository_id:
            raise ValueError("a fork's network root must be its provider-declared source or parent")
    elif repository.is_fork:
        raise ValueError("a provider-declared fork must be recorded as FORK")
    elif relationship is RepositoryRelationship.MIRROR:
        if not repository.mirror_url:
            raise ValueError("MIRROR requires the provider's mirror_url")
    elif relationship is RepositoryRelationship.TEMPLATE_DERIVATIVE:
        if repository.template_repository_id != network.root_repository_id:
            raise ValueError("a template derivative's root must be its provider-declared template")
    elif relationship is RepositoryRelationship.ROOT_REPOSITORY:
        if repository.mirror_url or repository.template_repository_id:
            raise ValueError("a repository with a declared mirror or template is not a plain root")
    elif relationship is RepositoryRelationship.RELATION_UNKNOWN:
        raise ValueError("a verified repository always has provider metadata to classify")


__all__ = [
    "MAX_FRAGMENT_CHARS",
    "MAX_SNAPSHOT_CHARS",
    "OSS_CHRONOLOGY_VERSION",
    "OSS_CONTRACT_VERSION",
    "OSS_IDENTITY_VERSION",
    "OSS_NETWORK_VERSION",
    "RELATION_BASES",
    "REPOSITORY_CUTOFF_RELATIVE",
    "VISIBILITY_UNPROVEN_FIELDS",
    "CommitDateFact",
    "LicenseStatus",
    "OpenSourcePriorArtCandidate",
    "OpenSourcePriorArtRun",
    "RelationshipBasis",
    "ReleaseFact",
    "RepositoryChronology",
    "RepositoryCutoffQualification",
    "RepositoryDateFacts",
    "RepositoryDateField",
    "RepositoryLicense",
    "RepositoryNetwork",
    "RepositoryNetworkMember",
    "RepositoryObservation",
    "RepositoryPopularity",
    "RepositoryRelationship",
    "RepositorySnapshot",
    "RepositorySnapshotKind",
    "UnverifiedRepository",
    "VerifiedRepository",
    "repository_date_value",
    "repository_key",
]
