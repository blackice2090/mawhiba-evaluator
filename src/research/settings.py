"""Research configuration: query budget, official seeds and the target edition.

No secrets. Seeds are reviewed configuration: each one names a URL that must be on
the official allowlist, and the role a reviewer assigned to it.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.research.official.allowlist import (
    OFFICIAL_IBDAA_SERVICE_URL,
    OFFICIAL_ROOT_URL,
    check_official_url,
)
from src.schemas.academic import ACADEMIC_PROVIDER_ORDER, AcademicProvider
from src.schemas.common import MawhibaModel
from src.schemas.evidence_extraction import (
    MAX_EVIDENCE_EXCERPT_CHARS,
    MIN_EVIDENCE_EXCERPT_CHARS,
)
from src.schemas.official import (
    MAX_COMPETITION_EDITION,
    MIN_COMPETITION_EDITION,
    OfficialPageKind,
    OfficialSeed,
)
from src.schemas.gap_assessment import GapAssessmentBounds
from src.schemas.methodology_review import MethodologyReviewBounds
from src.schemas.novelty_differentiation import NoveltyComparisonBounds
from src.schemas.research import QueryPlanLimits

IBDAA_SERVICE_SEED = OfficialSeed(
    url=OFFICIAL_IBDAA_SERVICE_URL,
    kind=OfficialPageKind.EVERGREEN_SERVICE_PAGE,
    note="National Olympiad for Scientific Creativity service page.",
)

DISCOVERY_ROOT_SEED = OfficialSeed(
    url=OFFICIAL_ROOT_URL,
    kind=OfficialPageKind.DISCOVERY_PAGE,
    note="Mawhiba home page. Optional discovery entry point, not a rules page.",
)

DEFAULT_OFFICIAL_SEEDS: tuple[OfficialSeed, ...] = (IBDAA_SERVICE_SEED,)
"""Only the evergreen service page by default.

Edition-specific pages are never shipped as defaults: a page for one year's event
must be configured deliberately, with its edition declared, so it can never be
mistaken for the current rules.
"""


class OfficialRequirementsSettings(MawhibaModel):
    seeds: list[OfficialSeed] = Field(
        default_factory=lambda: list(DEFAULT_OFFICIAL_SEEDS), min_length=1
    )
    target_edition: int | None = Field(
        default=None,
        ge=MIN_COMPETITION_EDITION,
        le=MAX_COMPETITION_EDITION,
        description="The competition edition under evaluation. Without it, an "
        "edition-specific page is UNDETERMINED rather than current -- the "
        "retrieval date is never used to guess the edition.",
    )
    max_seed_urls: int = Field(default=10, ge=1, le=50)

    @field_validator("seeds")
    @classmethod
    def _seeds_are_official(cls, seeds: list[OfficialSeed]) -> list[OfficialSeed]:
        for seed in seeds:
            reason = check_official_url(seed.url)
            if reason is not None:
                raise ValueError(
                    f"seed URL is not an allowlisted official URL: {seed.url} ({reason.value})"
                )
        return seeds

    @property
    def seed_urls(self) -> list[str]:
        return [seed.url for seed in self.seeds]


class AcademicSearchSettings(MawhibaModel):
    """Phase 2B academic retrieval policy: which providers, and how much.

    Budgets are deliberately small. The goal is high-value coverage of a few
    well-provenanced queries, not volume: every extra query is a third-party
    request, a cost, and more material for a later phase to weigh.

    Every limit is enforced deterministically, and hitting one is recorded as
    truncation -- never as a provider failure.
    """

    enabled_providers: list[AcademicProvider] = Field(
        default_factory=lambda: list(ACADEMIC_PROVIDER_ORDER),
        min_length=1,
        description="Providers to dispatch to, deduplicated and run in the "
        "canonical order regardless of how they are listed here.",
    )
    max_academic_queries_per_run: int = Field(default=4, ge=1, le=50)
    max_results_per_query_per_provider: int = Field(default=10, ge=1, le=100)
    max_results_per_provider_per_run: int = Field(default=30, ge=1, le=500)
    max_total_academic_candidates: int = Field(default=90, ge=1, le=2000)

    @field_validator("enabled_providers")
    @classmethod
    def _canonical_provider_order(
        cls, providers: list[AcademicProvider]
    ) -> list[AcademicProvider]:
        chosen = set(providers)
        return [p for p in ACADEMIC_PROVIDER_ORDER if p in chosen]

    @model_validator(mode="after")
    def _limits_are_coherent(self) -> AcademicSearchSettings:
        if self.max_results_per_provider_per_run < self.max_results_per_query_per_provider:
            raise ValueError(
                "max_results_per_provider_per_run cannot be below the per-query limit"
            )
        if self.max_total_academic_candidates < self.max_results_per_provider_per_run:
            raise ValueError(
                "max_total_academic_candidates cannot be below the per-provider limit"
            )
        return self


class EvidenceExtractionSettings(MawhibaModel):
    """Phase 2C extraction policy.

    Excerpt bounds are policy, not taste: a fragment too short to carry meaning
    verifies trivially, and an unbounded passage is quotation rather than
    evidence. Both are reviewable here rather than hard-coded in the verifier.
    """

    min_evidence_excerpt_chars: int = Field(
        default=MIN_EVIDENCE_EXCERPT_CHARS, ge=1, le=1000
    )
    max_evidence_excerpt_chars: int = Field(
        default=MAX_EVIDENCE_EXCERPT_CHARS, ge=50, le=20000
    )
    max_sources_per_run: int = Field(
        default=25,
        ge=1,
        le=500,
        description="Bounds how many verified sources one extraction pass calls "
        "the model for. Every call is a cost and a third-party request.",
    )
    max_candidates_per_snapshot: int = Field(
        default=12,
        ge=1,
        le=100,
        description="A model returning fifty excerpts from one abstract is "
        "over-extracting; the surplus is truncated and recorded.",
    )

    @model_validator(mode="after")
    def _bounds_are_coherent(self) -> EvidenceExtractionSettings:
        if self.max_evidence_excerpt_chars <= self.min_evidence_excerpt_chars:
            raise ValueError(
                "max_evidence_excerpt_chars must exceed min_evidence_excerpt_chars"
            )
        return self


class ClaimAlignmentSettings(MawhibaModel):
    """Phase 2D pairing policy: the hard safety limit against Cartesian growth.

    Hitting the limit never truncates silently (section 12): the run is marked
    ``BLOCKED_PAIR_LIMIT_EXCEEDED`` and the required count is recorded.
    """

    max_pairs_per_run: int = Field(default=500, ge=1, le=20000)


class ClaimSufficiencySettings(MawhibaModel):
    """Phase 2E policy knobs.

    Deliberately tiny. The sufficiency thresholds themselves are NOT settings:
    they are the versioned policy in ``src.research.sufficiency.policy``, and
    making them tunable per run would mean two archived assessments could carry
    the same ``policy_version`` while having applied different bars (section 28).
    """

    max_claims_per_run: int = Field(
        default=200,
        ge=1,
        le=5000,
        description="Safety bound on how many claims one pass assesses. The pass "
        "is deterministic and makes no model call, so this guards state size "
        "rather than cost.",
    )


class PatentResearchSettings(MawhibaModel):
    """Phase 2G patent search budget (section 26).

    Every limit is recorded on the run's ``PatentBudgetReport`` beside the count
    it cut off, so reaching one is never silent and never reported as complete
    coverage. Small by default: EPO OPS is a fair-use limited service, and Phase
    2G aims at well-provenanced candidates rather than volume (section 27).
    """

    max_queries_per_claim: int = Field(default=4, ge=1, le=16)
    max_queries_per_run: int = Field(default=12, ge=1, le=100)
    max_results_per_query: int = Field(default=10, ge=1, le=100)
    max_pages_per_query: int = Field(
        default=1,
        ge=1,
        le=5,
        description="OPS Range windows requested per query. One window by "
        "default; a provider-reported total above it is recorded, not chased.",
    )
    max_total_provider_results: int = Field(default=100, ge=1, le=2000)
    max_verified_publications: int = Field(default=50, ge=1, le=1000)
    max_family_lookups: int = Field(default=25, ge=0, le=500)
    max_classification_expansions: int = Field(default=0, ge=0, le=10)
    retry_limit: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    base_backoff_seconds: float = Field(default=0.5, ge=0.0, le=30.0)
    fetch_description: bool = Field(
        default=False,
        description="Also fetch the full description. Off by default: it is "
        "large, costly against a fair-use limit, and only useful once a later "
        "phase has narrowed the candidates. Absence is recorded as NOT_REQUESTED.",
    )


class ProductResearchSettings(MawhibaModel):
    """Phase 2H product-track budget (section 34). Small by default."""

    max_queries_per_claim: int = Field(default=4, ge=1, le=16)
    max_queries_per_run: int = Field(default=12, ge=1, le=100)
    max_results_per_query: int = Field(default=10, ge=1, le=20)
    max_pages_per_query: int = Field(default=1, ge=1, le=10)
    max_total_observations: int = Field(default=80, ge=1, le=1000)
    max_product_fetches: int = Field(default=20, ge=0, le=200)
    max_artifact_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    max_redirects: int = Field(default=3, ge=0, le=10)
    retry_limit: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=60.0)


class OpenSourceResearchSettings(MawhibaModel):
    """Phase 2H open-source budget (section 34). GitHub search is rate-limited."""

    max_queries_per_claim: int = Field(default=4, ge=1, le=16)
    max_queries_per_run: int = Field(default=12, ge=1, le=100)
    max_results_per_query: int = Field(default=10, ge=1, le=100)
    max_pages_per_query: int = Field(default=1, ge=1, le=10)
    max_total_observations: int = Field(default=100, ge=1, le=1000)
    max_repository_lookups: int = Field(default=25, ge=0, le=500)
    max_code_hits_per_repository: int = Field(default=5, ge=1, le=100)
    max_content_bytes: int = Field(default=200_000, ge=1_000, le=1_000_000)
    max_network_lookups: int = Field(default=10, ge=0, le=200)
    fetch_releases: bool = True
    fetch_head_commit: bool = True
    manifest_paths: tuple[str, ...] = (
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "Cargo.toml",
        "pom.xml",
        "go.mod",
    )
    max_manifests_per_repository: int = Field(default=2, ge=0, le=10)
    retry_limit: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=20.0, gt=0.0, le=60.0)


class ResearchSettings(MawhibaModel):
    limits: QueryPlanLimits = Field(default_factory=QueryPlanLimits)
    official: OfficialRequirementsSettings = Field(default_factory=OfficialRequirementsSettings)
    academic: AcademicSearchSettings = Field(default_factory=AcademicSearchSettings)
    evidence: EvidenceExtractionSettings = Field(
        default_factory=EvidenceExtractionSettings
    )
    alignment: ClaimAlignmentSettings = Field(default_factory=ClaimAlignmentSettings)
    sufficiency: ClaimSufficiencySettings = Field(
        default_factory=ClaimSufficiencySettings
    )
    patent: PatentResearchSettings = Field(default_factory=PatentResearchSettings)
    product: ProductResearchSettings = Field(default_factory=ProductResearchSettings)
    open_source: OpenSourceResearchSettings = Field(default_factory=OpenSourceResearchSettings)
    novelty: NoveltyComparisonBounds = Field(default_factory=NoveltyComparisonBounds)
    gap: GapAssessmentBounds = Field(default_factory=GapAssessmentBounds)
    methodology: MethodologyReviewBounds = Field(default_factory=MethodologyReviewBounds)


DEFAULT_RESEARCH_SETTINGS = ResearchSettings()
