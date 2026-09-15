"""Phase 0 configuration.

Only contract-level, non-secret settings live here. API keys and provider
configuration arrive in Phase 2 (section 36: secrets stay in server env only).
"""

from __future__ import annotations

import os

from pydantic import Field

from src.schemas.common import MawhibaModel, OperatingMode
from src.scoring.models import ADVISORY_RUBRIC_V1, Rubric
from src.trust.models import DEFAULT_TRUST_POLICY, TrustPolicy

DEVELOPER_LANGUAGE = "en"
"""Language of every developer-facing surface.

Covers code identifiers, comments, docstrings, exception and log messages, test
names, CLI output, JSON keys, schema field names, enum names and values, API
paths, tracing metadata, and all internal agent prompts. Arabic never appears in
these positions -- mixed RTL/LTR text breaks terminals, logs and diffs.
"""

STUDENT_DEFAULT_LANGUAGE = "ar"
"""Default language of the student-facing presentation layer.

Student-supplied content is stored verbatim in value positions (claim text,
Tracked.value, EvidenceLocation.quote_or_extract) and is never translated for
storage. This constant is the default for ProjectIdentity.language, which
describes the student's project rather than the system.
"""


DEFAULT_EXTRACTION_MODEL = "gpt-5.6-terra"
DEFAULT_CLASSIFICATION_MODEL = "gpt-5.6-terra"
DEFAULT_ESCALATION_MODEL = "gpt-5.6-sol"
DEFAULT_RESEARCH_PLANNING_MODEL = "gpt-5.6-terra"
DEFAULT_OFFICIAL_EXTRACTION_MODEL = "gpt-5.6-terra"
DEFAULT_MAX_RETRIES = 2


class LLMSettings(MawhibaModel):
    """Model routing and retry policy for the intake layer.

    Read from the environment, but never a credential: the OpenAI SDK handles
    OPENAI_API_KEY itself, and nothing here reads, stores or logs it. Importing
    this module and running the unit suite require no key.
    """

    extraction_model: str = Field(default=DEFAULT_EXTRACTION_MODEL, min_length=1)
    classification_model: str = Field(default=DEFAULT_CLASSIFICATION_MODEL, min_length=1)
    escalation_model: str = Field(default=DEFAULT_ESCALATION_MODEL, min_length=1)
    research_planning_model: str = Field(default=DEFAULT_RESEARCH_PLANNING_MODEL, min_length=1)
    official_extraction_model: str = Field(
        default=DEFAULT_OFFICIAL_EXTRACTION_MODEL, min_length=1
    )

    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES,
        ge=0,
        le=5,
        description="Bounded on purpose. Retries cover transient transport faults "
        "and truncation only; refusals and schema errors are never retried.",
    )

    escalation_enabled: bool = Field(
        default=True,
        description="Whether a low-confidence classification may escalate once.",
    )
    classification_escalation_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Below this classifier confidence, the stronger model gets one "
        "additional attempt. Escalation improves reasoning on an ambiguous "
        "judgement; it never converts an UNKNOWN fact into a guess.",
    )

    @classmethod
    def from_env(cls) -> LLMSettings:
        """Build from environment variables, falling back to the defaults."""
        return cls(
            extraction_model=os.getenv("OPENAI_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL),
            classification_model=os.getenv(
                "OPENAI_CLASSIFICATION_MODEL", DEFAULT_CLASSIFICATION_MODEL
            ),
            escalation_model=os.getenv("OPENAI_ESCALATION_MODEL", DEFAULT_ESCALATION_MODEL),
            max_retries=int(os.getenv("OPENAI_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))),
        )


DEFAULT_LLM_SETTINGS = LLMSettings()


class ContractSettings(MawhibaModel):
    """Versioned bundle of the policies an evaluation run was executed under.

    Recording this alongside every run is what makes regression testing
    (section 34) meaningful: a score change is only interpretable if you know
    which rubric and trust policy produced it.
    """

    contracts_version: str = Field(default="PHASE0-V1")
    default_mode: OperatingMode = OperatingMode.EVALUATOR
    default_rubric: Rubric = Field(default=ADVISORY_RUBRIC_V1)
    trust_policy: TrustPolicy = Field(default=DEFAULT_TRUST_POLICY)
    llm: LLMSettings = Field(default=DEFAULT_LLM_SETTINGS)
    developer_language: str = Field(
        default=DEVELOPER_LANGUAGE,
        description="Language of all developer-facing and internal agent surfaces.",
    )
    student_default_language: str = Field(
        default=STUDENT_DEFAULT_LANGUAGE,
        description="Default language of the student-facing presentation layer.",
    )


DEFAULT_SETTINGS = ContractSettings()
