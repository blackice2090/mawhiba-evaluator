"""Research configuration: query budget, official seeds and the target edition.

No secrets. Seeds are reviewed configuration: each one names a URL that must be on
the official allowlist, and the role a reviewer assigned to it.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from src.research.official.allowlist import (
    OFFICIAL_IBDAA_SERVICE_URL,
    OFFICIAL_ROOT_URL,
    check_official_url,
)
from src.schemas.common import MawhibaModel
from src.schemas.official import (
    MAX_COMPETITION_EDITION,
    MIN_COMPETITION_EDITION,
    OfficialPageKind,
    OfficialSeed,
)
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


class ResearchSettings(MawhibaModel):
    limits: QueryPlanLimits = Field(default_factory=QueryPlanLimits)
    official: OfficialRequirementsSettings = Field(default_factory=OfficialRequirementsSettings)


DEFAULT_RESEARCH_SETTINGS = ResearchSettings()
