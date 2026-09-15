"""Student submission artifacts -- the raw material of intake.

The original text is preserved exactly as supplied. Everything downstream --
extraction, provenance verification, and eventually the answer to "where did the
system get this?" -- is checked against this text, so normalizing it away would
destroy the only ground truth intake has.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.schemas.common import MawhibaModel, UtcDatetime, utc_now


class ArtifactType(StrEnum):
    """What kind of submission this is.

    Phase 1B supports TEXT only. The other members are declared so the contract
    does not change shape when file intake arrives, but nothing constructs them
    yet.
    """

    TEXT = "TEXT"
    FILE_PDF = "FILE_PDF"
    FILE_DOCX = "FILE_DOCX"
    FILE_IMAGE = "FILE_IMAGE"
    LINK = "LINK"


PHASE_1B_SUPPORTED_ARTIFACT_TYPES: frozenset[ArtifactType] = frozenset(
    {ArtifactType.TEXT}
)


class StudentSubmissionArtifact(MawhibaModel):
    """One thing the student submitted, stored verbatim.

    ``original_text`` is never rewritten, trimmed of meaning, translated or
    normalized. Anchor verification normalizes a *copy* for matching only.
    """

    artifact_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    artifact_type: ArtifactType = ArtifactType.TEXT
    original_text: str = Field(min_length=1)
    language: str | None = Field(
        default=None,
        description="BCP-47-ish tag if known. None means not determined -- never guessed.",
    )
    submitted_at: UtcDatetime = Field(default_factory=utc_now)
    sequence: int = Field(
        default=1,
        ge=1,
        description="Turn number within the intake conversation, for multi-turn intake.",
    )

    @model_validator(mode="after")
    def _phase_1b_supports_text_only(self) -> StudentSubmissionArtifact:
        if self.artifact_type not in PHASE_1B_SUPPORTED_ARTIFACT_TYPES:
            raise ValueError(
                f"artifact_type={self.artifact_type.value} is declared but not "
                "supported in Phase 1B; only TEXT is accepted"
            )
        return self

    @property
    def content_hash(self) -> str:
        """Stable digest of the original text.

        Logs and traces reference this instead of the submission body, so
        developer output never carries the student's full text by default.
        """
        return hashlib.sha256(self.original_text.encode("utf-8")).hexdigest()

    @property
    def short_hash(self) -> str:
        return self.content_hash[:12]
