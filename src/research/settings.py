"""Research configuration: query budget and official retrieval seeds. No secrets."""

from __future__ import annotations

from pydantic import Field, field_validator

from src.research.official.allowlist import DEFAULT_OFFICIAL_SEED_URL, check_official_url
from src.schemas.common import MawhibaModel
from src.schemas.research import QueryPlanLimits


class OfficialRequirementsSettings(MawhibaModel):
    seed_urls: list[str] = Field(default_factory=lambda: [DEFAULT_OFFICIAL_SEED_URL], min_length=1)
    max_seed_urls: int = Field(default=10, ge=1, le=50)

    @field_validator("seed_urls")
    @classmethod
    def _seeds_are_official(cls, urls: list[str]) -> list[str]:
        for url in urls:
            reason = check_official_url(url)
            if reason is not None:
                raise ValueError(f"seed URL is not an allowlisted official URL: {url} ({reason.value})")
        return urls


class ResearchSettings(MawhibaModel):
    limits: QueryPlanLimits = Field(default_factory=QueryPlanLimits)
    official: OfficialRequirementsSettings = Field(default_factory=OfficialRequirementsSettings)


DEFAULT_RESEARCH_SETTINGS = ResearchSettings()
