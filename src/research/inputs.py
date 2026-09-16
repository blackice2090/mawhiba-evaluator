"""The research input boundary.

Research planning may read only trusted canonical ``ProjectState`` fields:
``KNOWN`` tracked values, intake-verified lists, the verified classification and
student-origin claims. Anything else -- model summaries, rejected extractions,
UNKNOWN / CONFLICTED / inferred values -- is not a research input.
"""

from __future__ import annotations

import hashlib

from src.graph.state import ProjectState
from src.research.privacy import EMPTY_PRIVACY_CONTEXT, ResearchPrivacyContext, redact_pii
from src.schemas.claim import ClaimOrigin
from src.schemas.common import KnowledgeStatus, ProjectType, TechnicalDomain, Tracked
from src.schemas.research import ResearchInputClaim, ResearchInputField, ResearchInputSnapshot

TRACKED_RESEARCH_FIELDS: tuple[str, ...] = (
    "problem.statement",
    "solution.description",
    "goal",
)

LIST_RESEARCH_FIELDS: tuple[str, ...] = (
    "technical.technologies",
    "technical.hardware",
    "technical.software",
    "technical.sensors",
    "technical.algorithms",
    "technical.models",
    "technical.datasets",
    "technical.data_sources",
    "methodology.baseline",
    "methodology.metrics",
)

IDENTITY_RESEARCH_FIELDS: tuple[str, ...] = ("identity.domain", "identity.project_type")

CLAIM_FIELD_PREFIX = "claims."

RESEARCH_INPUT_FIELDS: tuple[str, ...] = (
    *TRACKED_RESEARCH_FIELDS,
    *LIST_RESEARCH_FIELDS,
    *IDENTITY_RESEARCH_FIELDS,
)
"""Every non-claim canonical path a research query may be derived from."""


def _attribute(project: ProjectState, path: str) -> object:
    target: object = project
    for part in path.split("."):
        target = getattr(target, part)
    return target


def resolve_research_field(project: ProjectState, path: str) -> list[str] | None:
    """Trusted values at a research input path.

    ``None`` means the reference itself is invalid (not an allowed input, or a
    claim that does not exist or is not student-origin). ``[]`` means a valid
    path with no trusted value -- UNKNOWN stays unusable.
    """
    if path.startswith(CLAIM_FIELD_PREFIX):
        claim_id = path.removeprefix(CLAIM_FIELD_PREFIX)
        claim = project.claim_by_id(claim_id)
        if claim is None or claim.origin is not ClaimOrigin.STUDENT:
            return None
        return [claim.claim]

    if path not in RESEARCH_INPUT_FIELDS:
        return None

    if path == "identity.domain":
        return [d.value for d in project.identity.domain if d is not TechnicalDomain.UNKNOWN]
    if path == "identity.project_type":
        kind = project.identity.project_type
        return [] if kind is ProjectType.UNKNOWN else [kind.value]

    value = _attribute(project, path)
    if isinstance(value, Tracked):
        if value.status is KnowledgeStatus.KNOWN and value.value is not None:
            return [str(value.value)]
        return []
    return [str(item) for item in value]


def project_state_fingerprint(project: ProjectState) -> str:
    """Deterministic content hash of the canonical state."""
    return hashlib.sha256(project.model_dump_json().encode("utf-8")).hexdigest()


def build_research_input(
    project: ProjectState, privacy: ResearchPrivacyContext = EMPTY_PRIVACY_CONTEXT
) -> ResearchInputSnapshot:
    """The PII-minimized projection of trusted state that the planner may see.

    Pure: reads ``project`` and never writes to it.
    """
    redactions = 0
    fields: list[ResearchInputField] = []
    for path in RESEARCH_INPUT_FIELDS:
        values = resolve_research_field(project, path) or []
        cleaned: list[str] = []
        for value in values:
            text, count = redact_pii(value, privacy)
            redactions += count
            cleaned.append(text)
        if cleaned:
            fields.append(ResearchInputField(field_path=path, values=cleaned))

    claims: list[ResearchInputClaim] = []
    for claim in project.claims:
        if claim.origin is not ClaimOrigin.STUDENT:
            continue
        text, count = redact_pii(claim.claim, privacy)
        redactions += count
        claims.append(
            ResearchInputClaim(
                claim_id=claim.claim_id, claim_type=claim.claim_type.value, text=text
            )
        )

    return ResearchInputSnapshot(
        project_id=project.project_id,
        project_version_id=project.project_version_id,
        project_state_hash=project_state_fingerprint(project),
        fields=fields,
        claims=claims,
        redaction_count=redactions,
    )
