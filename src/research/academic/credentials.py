"""Academic provider credentials.

Keys are read from the process environment at the moment a live connector is
constructed and are held nowhere else. Nothing in this project stores a key in a
settings model, on graph state, in a checkpoint, in an error message, in a
rejection ledger or in a log line -- the value never leaves the connector that
holds it, and the only thing any other layer can ask is whether one is present.

OpenAlex needs no key. It asks for a contact address in the ``User-Agent`` so
requests land in its polite pool; that address is configuration, not a secret,
and defaults to nothing.
"""

from __future__ import annotations

import os

CONSENSUS_API_KEY_ENV = "CONSENSUS_API_KEY"
SEMANTIC_SCHOLAR_API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"
OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"
OPENALEX_CONTACT_EMAIL_ENV = "OPENALEX_CONTACT_EMAIL"

ACADEMIC_CREDENTIAL_ENV_VARS: tuple[str, ...] = (
    CONSENSUS_API_KEY_ENV,
    SEMANTIC_SCHOLAR_API_KEY_ENV,
    OPENALEX_API_KEY_ENV,
)
"""Every environment variable this project treats as a secret."""


def read_api_key(env_name: str) -> str | None:
    """The key, or ``None``. Absence is a normal, reportable state."""
    value = os.getenv(env_name, "").strip()
    return value or None


def has_api_key(env_name: str) -> bool:
    """Whether a key is configured, without revealing it."""
    return read_api_key(env_name) is not None


def read_contact_email() -> str | None:
    """Optional OpenAlex contact address. Configuration, not a credential."""
    value = os.getenv(OPENALEX_CONTACT_EMAIL_ENV, "").strip()
    return value or None


__all__ = [
    "ACADEMIC_CREDENTIAL_ENV_VARS",
    "CONSENSUS_API_KEY_ENV",
    "OPENALEX_API_KEY_ENV",
    "OPENALEX_CONTACT_EMAIL_ENV",
    "SEMANTIC_SCHOLAR_API_KEY_ENV",
    "has_api_key",
    "read_api_key",
    "read_contact_email",
]
