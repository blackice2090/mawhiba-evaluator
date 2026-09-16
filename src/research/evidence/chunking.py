"""Deterministic content chunking.

Long content is split so an extractor sees a manageable window, but the split is
purely a delivery detail: every chunk records its offsets into the parent
snapshot, and an accepted excerpt is always re-verified against the **parent**
text, never against the chunk it happened to arrive in (§34, §35).

That ordering is what makes chunk boundaries safe. A finding that straddles a
boundary either verifies against the parent -- in which case the boundary was
irrelevant -- or it does not verify at all. Nothing is silently truncated to fit.

Abstracts sit far below the chunk size in practice, so production Phase 2C
produces exactly one chunk per snapshot. The machinery exists so that
``PARTIAL_TEXT`` and ``FULL_TEXT`` can arrive later without changing evidence
identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from src.schemas.evidence_extraction import (
    EVIDENCE_CHUNKER_VERSION,
    SourceContentSnapshot,
)

DEFAULT_CHUNK_CHARS = 6000
DEFAULT_CHUNK_OVERLAP_CHARS = 400
"""Overlap so a sentence spanning a boundary appears whole in one chunk.

Overlap is a recall aid only. Correctness does not depend on it, because the
parent snapshot is the thing an excerpt must verify against.
"""


@dataclass(frozen=True)
class ContentChunk:
    """One window into a snapshot, with its offsets into the parent."""

    chunk_id: UUID
    content_id: UUID
    start_offset: int
    end_offset: int
    text: str
    content_hash: str
    chunker_version: str = EVIDENCE_CHUNKER_VERSION

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset


def chunk_snapshot(
    snapshot: SourceContentSnapshot,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[ContentChunk]:
    """Split a snapshot deterministically. Same input, same chunks, always."""
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be positive")
    overlap = max(0, min(overlap_chars, chunk_chars - 1))

    text = snapshot.text
    if len(text) <= chunk_chars:
        return [
            ContentChunk(
                chunk_id=uuid4(),
                content_id=snapshot.content_id,
                start_offset=0,
                end_offset=len(text),
                text=text,
                content_hash=snapshot.content_hash,
            )
        ]

    chunks: list[ContentChunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        chunks.append(
            ContentChunk(
                chunk_id=uuid4(),
                content_id=snapshot.content_id,
                start_offset=start,
                end_offset=end,
                text=text[start:end],
                content_hash=snapshot.content_hash,
            )
        )
        if end == len(text):
            break
        start = end - overlap
    return chunks


__all__ = [
    "DEFAULT_CHUNK_CHARS",
    "DEFAULT_CHUNK_OVERLAP_CHARS",
    "ContentChunk",
    "chunk_snapshot",
]
