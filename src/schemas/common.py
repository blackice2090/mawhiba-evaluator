"""Shared enums and primitives for all Mawhiba data contracts.

Architecture refs: 2.1 (Zero Assumption), 2.2 (No Evidence -> No Strong Claim),
2.6 (Abstention is a Feature).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Timestamps -- every timestamp in the system is timezone-aware UTC.
# ---------------------------------------------------------------------------

def _require_tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must be timezone-aware (UTC preferred)")
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_require_tz_aware)]


def utc_now() -> datetime:
    """Canonical clock for the whole system."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Bounded numerics
# ---------------------------------------------------------------------------

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
"""Normalized [0,1] value: confidence, coverage, quality, similarity."""

NoveltyLevel = Annotated[int, Field(ge=0, le=5)]
"""Section 13 novelty scale: 0 = No Clear Novelty ... 5 = Strong Novel Contribution."""


# ---------------------------------------------------------------------------
# Zero Assumption (2.1)
# ---------------------------------------------------------------------------

class KnowledgeStatus(StrEnum):
    """Epistemic status of a field. A missing critical field never silently
    becomes an assumption."""

    KNOWN = "KNOWN"
    INFERRED_NON_CRITICAL = "INFERRED_NON_CRITICAL"
    UNKNOWN = "UNKNOWN"
    CONFLICTED = "CONFLICTED"


class ValueOrigin(StrEnum):
    """Where a tracked value came from (N01: every extracted value carries
    source / certainty / location)."""

    STUDENT_MESSAGE = "STUDENT_MESSAGE"
    STUDENT_FILE = "STUDENT_FILE"
    EXTERNAL_SOURCE = "EXTERNAL_SOURCE"
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    UNKNOWN = "UNKNOWN"


class Tracked(BaseModel, Generic[T]):
    """A field value that knows whether it is actually known.

    This is the concrete enforcement of Zero Assumption. ``value is None``
    alone cannot distinguish "not provided", "not extractable" and "two
    sources disagree" -- ``status`` can.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    value: T | None = None
    status: KnowledgeStatus = KnowledgeStatus.UNKNOWN
    origin: ValueOrigin = ValueOrigin.UNKNOWN
    certainty: UnitInterval | None = None
    location: str | None = Field(
        default=None,
        description="Where the value was found: file page, section, message id.",
    )
    conflicting_values: list[str] = Field(
        default_factory=list,
        description="Populated when status is CONFLICTED (N15 contradiction detector).",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Tracked[T]:
        if self.status in (
            KnowledgeStatus.KNOWN,
            KnowledgeStatus.INFERRED_NON_CRITICAL,
        ) and self.value is None:
            raise ValueError(f"status={self.status} requires a value")
        if self.status == KnowledgeStatus.UNKNOWN and self.value is not None:
            raise ValueError(
                "status=UNKNOWN must not carry a value; use "
                "INFERRED_NON_CRITICAL or CONFLICTED instead"
            )
        if self.status == KnowledgeStatus.CONFLICTED and len(self.conflicting_values) < 2:
            raise ValueError("status=CONFLICTED requires at least 2 conflicting_values")
        if (
            self.origin == ValueOrigin.AGENT_INFERENCE
            and self.status == KnowledgeStatus.KNOWN
        ):
            raise ValueError(
                "agent inference can never be KNOWN; use INFERRED_NON_CRITICAL (2.1)"
            )
        return self

    # -- ergonomic constructors ------------------------------------------------

    @classmethod
    def unknown(cls, note: str | None = None) -> Tracked[T]:
        return cls(status=KnowledgeStatus.UNKNOWN, note=note)

    @classmethod
    def known(
        cls,
        value: T,
        origin: ValueOrigin = ValueOrigin.STUDENT_MESSAGE,
        location: str | None = None,
        certainty: float | None = None,
    ) -> Tracked[T]:
        return cls(
            value=value,
            status=KnowledgeStatus.KNOWN,
            origin=origin,
            location=location,
            certainty=certainty,
        )

    @classmethod
    def inferred(cls, value: T, note: str | None = None) -> Tracked[T]:
        return cls(
            value=value,
            status=KnowledgeStatus.INFERRED_NON_CRITICAL,
            origin=ValueOrigin.AGENT_INFERENCE,
            note=note,
        )

    @classmethod
    def conflicted(
        cls, conflicting_values: list[str], note: str | None = None
    ) -> Tracked[T]:
        return cls(
            status=KnowledgeStatus.CONFLICTED,
            conflicting_values=conflicting_values,
            note=note,
        )

    @property
    def is_known(self) -> bool:
        return self.status == KnowledgeStatus.KNOWN


# ---------------------------------------------------------------------------
# Evaluation vocabulary
# ---------------------------------------------------------------------------

class EvaluationStatus(StrEnum):
    """Status of an evaluated axis, engine output, or score (2.6, 40)."""

    NOT_EVALUATED = "NOT_EVALUATED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConfidenceLevel(StrEnum):
    """Qualitative confidence used by FindingRecord (7.5) and ScoreAxis (7.6).

    The architecture mixes numeric confidence (7.3 ClaimRecord) with this
    categorical form; both are kept and ``from_score`` bridges them.
    """

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceLevel:
        if not 0.0 <= score <= 1.0:
            raise ValueError("confidence score must be within [0,1]")
        if score < 0.25:
            return cls.VERY_LOW
        if score < 0.50:
            return cls.LOW
        if score < 0.75:
            return cls.MEDIUM
        return cls.HIGH


class ProjectType(StrEnum):
    SCIENTIFIC_RESEARCH = "SCIENTIFIC_RESEARCH"
    ENGINEERING_PROJECT = "ENGINEERING_PROJECT"
    HYBRID = "HYBRID"
    UNKNOWN = "UNKNOWN"


class TechnicalDomain(StrEnum):
    """The single canonical technical-domain taxonomy (ADR-005).

    One enum, shared by the classifier DTO and by ``ProjectState.identity.domain``.
    Phase 1B briefly had two taxonomies with a lossy projection between them;
    that is resolved here, because research routing in later phases will key off
    the domain and a lossy mapping would silently misroute a project.

    Names are spelled out rather than abbreviated so a value read in a log,
    a trace or a report is unambiguous.
    """

    ARTIFICIAL_INTELLIGENCE = "ARTIFICIAL_INTELLIGENCE"
    MACHINE_LEARNING = "MACHINE_LEARNING"
    DEEP_LEARNING = "DEEP_LEARNING"
    COMPUTER_VISION = "COMPUTER_VISION"
    NATURAL_LANGUAGE_PROCESSING = "NATURAL_LANGUAGE_PROCESSING"
    DATA_SCIENCE = "DATA_SCIENCE"
    CYBERSECURITY = "CYBERSECURITY"
    INTERNET_OF_THINGS = "INTERNET_OF_THINGS"
    ROBOTICS = "ROBOTICS"
    EMBEDDED_SYSTEMS = "EMBEDDED_SYSTEMS"
    ELECTRONICS = "ELECTRONICS"
    SENSORS = "SENSORS"
    SMART_SYSTEMS = "SMART_SYSTEMS"
    COMPUTER_SCIENCE = "COMPUTER_SCIENCE"
    SOFTWARE_ENGINEERING = "SOFTWARE_ENGINEERING"
    NETWORKS = "NETWORKS"
    EDGE_COMPUTING = "EDGE_COMPUTING"
    CLOUD_COMPUTING = "CLOUD_COMPUTING"
    HUMAN_COMPUTER_INTERACTION = "HUMAN_COMPUTER_INTERACTION"
    OTHER_TECHNICAL = "OTHER_TECHNICAL"
    UNKNOWN = "UNKNOWN"


LEGACY_DOMAIN_MIGRATION: dict[str, TechnicalDomain] = {
    # Phase 0 ProjectDomain members, kept loadable so existing serialized
    # ProjectState snapshots still validate (ADR-005 migration).
    "AI_ML": TechnicalDomain.ARTIFICIAL_INTELLIGENCE,
    "SOFTWARE": TechnicalDomain.SOFTWARE_ENGINEERING,
    "IOT": TechnicalDomain.INTERNET_OF_THINGS,
    "EMBEDDED": TechnicalDomain.EMBEDDED_SYSTEMS,
    "HCI": TechnicalDomain.HUMAN_COMPUTER_INTERACTION,
    "OTHER": TechnicalDomain.OTHER_TECHNICAL,
    # Phase 1B TechnicalDomain spellings that were renamed.
    "NLP": TechnicalDomain.NATURAL_LANGUAGE_PROCESSING,
    # Phase 0 application areas with no technical-domain equivalent. They
    # describe what the project is *about*, not which technical field it sits
    # in, so they migrate to OTHER_TECHNICAL rather than being dropped.
    "ENERGY": TechnicalDomain.OTHER_TECHNICAL,
    "HEALTH_TECH": TechnicalDomain.OTHER_TECHNICAL,
    "ENVIRONMENT": TechnicalDomain.OTHER_TECHNICAL,
}
"""Legacy domain spellings and the canonical member each migrates to.

Migration is explicit and lossy only where the old value had no technical
meaning. Nothing is silently reinterpreted: every entry is listed here and
covered by a test.
"""


def migrate_domain(value: object) -> object:
    """Map a legacy domain spelling onto the canonical enum.

    Applied as a pre-validator so an old serialized snapshot loads without a
    separate migration script. Unknown strings are passed through untouched so
    pydantic raises a normal validation error rather than this function
    inventing a plausible substitute.
    """
    if isinstance(value, TechnicalDomain):
        return value
    if isinstance(value, str) and value not in TechnicalDomain.__members__:
        return LEGACY_DOMAIN_MIGRATION.get(value, value)
    return value


class ExtractionMode(StrEnum):
    """How an extracted value relates to the student's source text (ADR-004).

    The mode decides what code will accept as canonical, which is why it lives
    in the shared vocabulary rather than inside the intake package.
    """

    VERBATIM_SPAN = "VERBATIM_SPAN"
    """A factual narrative field. The canonical value IS the source span; an
    LLM paraphrase never replaces it."""

    VERBATIM_TERM = "VERBATIM_TERM"
    """An atomic technical term (YOLOv8, Raspberry Pi, LoRaWAN). Every token of
    the value must appear in the supporting excerpt."""

    CLASSIFICATION = "CLASSIFICATION"
    """A non-critical inference: project type, technical domain. Requires
    submission support but never appears verbatim."""

    STUDENT_CLAIM = "STUDENT_CLAIM"
    """An assertion attributed to the student. Never verified evidence."""


class OperatingMode(StrEnum):
    """Default mode is EVALUATOR; the rest are declared future modes."""

    EVALUATOR = "EVALUATOR"
    MENTOR = "MENTOR"
    JURY = "JURY"
    RESEARCH = "RESEARCH"
    NOVELTY = "NOVELTY"
    METHODOLOGY = "METHODOLOGY"
    SCORE = "SCORE"


class ResearchBranch(StrEnum):
    """Section 9 parallel research branches, plus the official-requirements branch (N03).

    Phase 2A renamed ``OFFICIAL`` to ``OFFICIAL_REQUIREMENTS`` and added
    ``STANDARDS``. ``OFFICIAL`` remains an alias of the same member, and the
    legacy serialized value is migrated by ``_missing_`` so old snapshots load.
    """

    OFFICIAL_REQUIREMENTS = "OFFICIAL_REQUIREMENTS"
    ACADEMIC = "ACADEMIC"
    PATENT = "PATENT"
    PRODUCT = "PRODUCT"
    OPEN_SOURCE = "OPEN_SOURCE"
    STANDARDS = "STANDARDS"
    OFFICIAL = "OFFICIAL_REQUIREMENTS"

    @classmethod
    def _missing_(cls, value: object) -> ResearchBranch | None:
        if value == "OFFICIAL":
            return cls.OFFICIAL_REQUIREMENTS
        return None


class BranchStatus(StrEnum):
    """Coverage state of a research branch (27)."""

    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MawhibaModel(BaseModel):
    """Base for every contract: strict, forbids silent extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )
