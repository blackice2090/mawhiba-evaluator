"""Deterministic offline providers for the three academic connectors.

These are not simplified stand-ins. A fake replaces exactly one thing -- the
HTTP attempt -- and then runs the real normalizer, the real identifier rules,
the real within-response duplicate check, the real result limit and the real
envelope assembly for its provider. A behaviour that passes here is the
behaviour the live connector has.

Scripting covers what a provider actually does:

* return records (raw provider JSON, so validation is exercised);
* return nothing, which is ``EMPTY`` and not a failure;
* fail, with a named ``AcademicErrorKind``;
* fail for the first N attempts and then succeed, which is how the retry and
  rate-limit paths are tested without a real second passing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from src.research.academic.consensus import (
    CONSENSUS_CONNECTOR_VERSION,
    normalize_consensus_response,
)
from src.research.academic.http import (
    DEFAULT_RETRY_POLICY,
    AcademicTransportError,
    RetryPolicy,
    Sleeper,
)
from src.research.academic.normalization import NormalizedResponse
from src.research.academic.openalex import (
    OPENALEX_CONNECTOR_VERSION,
    normalize_openalex_response,
)
from src.research.academic.provider import BaseAcademicProvider
from src.research.academic.semantic_scholar import (
    SEMANTIC_SCHOLAR_CONNECTOR_VERSION,
    normalize_semantic_scholar_response,
)
from src.schemas.academic import (
    AcademicErrorKind,
    AcademicProvider,
    AcademicSearchQuery,
)


@dataclass(frozen=True)
class ScriptedSearch:
    """What a fake provider does for one query.

    ``leading_failures`` fail the first attempts and then the payload is served,
    which is the only honest way to test that a bounded retry recovers.
    """

    records: list[Any] = field(default_factory=list)
    payload: Any = None
    failure: AcademicErrorKind | None = None
    leading_failures: tuple[AcademicErrorKind, ...] = ()
    http_status: int | None = None
    retry_after_seconds: float | None = None


def failure(
    kind: AcademicErrorKind,
    *,
    http_status: int | None = None,
    retry_after_seconds: float | None = None,
) -> ScriptedSearch:
    """A provider that cannot be asked."""
    return ScriptedSearch(
        failure=kind, http_status=http_status, retry_after_seconds=retry_after_seconds
    )


EMPTY = ScriptedSearch()
"""A provider that worked and found nothing."""


class _FakeAcademicProvider(BaseAcademicProvider):
    """Shared scripting. Subclasses supply the envelope shape and normalizer."""

    envelope_key: ClassVar[str]

    def __init__(
        self,
        responses: Mapping[str, ScriptedSearch] | None = None,
        *,
        default: ScriptedSearch | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleeper: Sleeper | None = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy, sleeper=sleeper)
        self._responses = dict(responses or {})
        self._default = default if default is not None else EMPTY
        self.fetch_calls: list[tuple[str, int]] = []
        self._attempts: dict[str, int] = {}

    def script_for(self, query_text: str) -> ScriptedSearch:
        return self._responses.get(query_text, self._default)

    @property
    def queries_seen(self) -> list[str]:
        """Every query text this provider was asked for, in order, once each."""
        return list(dict.fromkeys(text for text, _ in self.fetch_calls))

    def _fetch(self, query: AcademicSearchQuery, limit: int) -> Any:
        self.fetch_calls.append((query.query, limit))
        script = self.script_for(query.query)
        attempt = self._attempts.get(query.query, 0)
        self._attempts[query.query] = attempt + 1

        if attempt < len(script.leading_failures):
            kind = script.leading_failures[attempt]
            raise AcademicTransportError(
                kind,
                f"scripted {kind.value}",
                http_status=script.http_status,
                retry_after_seconds=script.retry_after_seconds,
            )
        if script.failure is not None:
            raise AcademicTransportError(
                script.failure,
                f"scripted {script.failure.value}",
                http_status=script.http_status,
                retry_after_seconds=script.retry_after_seconds,
            )
        if script.payload is not None:
            return script.payload
        return {self.envelope_key: list(script.records)}


class FakeConsensusProvider(_FakeAcademicProvider):
    provider_name: ClassVar[AcademicProvider] = AcademicProvider.CONSENSUS
    connector_version: ClassVar[str] = CONSENSUS_CONNECTOR_VERSION
    envelope_key: ClassVar[str] = "papers"

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_consensus_response(query, payload, retrieved_at=retrieved_at)


class FakeOpenAlexProvider(_FakeAcademicProvider):
    provider_name: ClassVar[AcademicProvider] = AcademicProvider.OPENALEX
    connector_version: ClassVar[str] = OPENALEX_CONNECTOR_VERSION
    envelope_key: ClassVar[str] = "results"

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_openalex_response(query, payload, retrieved_at=retrieved_at)


class FakeSemanticScholarProvider(_FakeAcademicProvider):
    provider_name: ClassVar[AcademicProvider] = AcademicProvider.SEMANTIC_SCHOLAR
    connector_version: ClassVar[str] = SEMANTIC_SCHOLAR_CONNECTOR_VERSION
    envelope_key: ClassVar[str] = "data"

    def _normalize(
        self, query: AcademicSearchQuery, payload: Any, retrieved_at: datetime
    ) -> NormalizedResponse:
        return normalize_semantic_scholar_response(
            query, payload, retrieved_at=retrieved_at
        )


FAKE_PROVIDER_CLASSES: dict[AcademicProvider, type[_FakeAcademicProvider]] = {
    AcademicProvider.CONSENSUS: FakeConsensusProvider,
    AcademicProvider.OPENALEX: FakeOpenAlexProvider,
    AcademicProvider.SEMANTIC_SCHOLAR: FakeSemanticScholarProvider,
}


def build_fake_providers(
    scripts: Mapping[AcademicProvider, Mapping[str, ScriptedSearch]] | None = None,
    *,
    sleeper: Sleeper | None = None,
) -> list[_FakeAcademicProvider]:
    """One fake per provider, in dispatch order. Unscripted queries return EMPTY."""
    scripts = scripts or {}
    return [
        cls(scripts.get(provider, {}), sleeper=sleeper)
        for provider, cls in FAKE_PROVIDER_CLASSES.items()
    ]


__all__ = [
    "EMPTY",
    "FAKE_PROVIDER_CLASSES",
    "FakeConsensusProvider",
    "FakeOpenAlexProvider",
    "FakeSemanticScholarProvider",
    "ScriptedSearch",
    "build_fake_providers",
    "failure",
]
