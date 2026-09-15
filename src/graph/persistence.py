"""Checkpointer construction and serializer registration.

Graph construction never names a concrete saver. ``build_phase1a_graph`` takes a
``BaseCheckpointSaver``; this module decides which one to build. A durable
PostgreSQL saver can therefore be injected later without touching graph code.

Phase 1A ships the in-memory saver only.

Serializer registration is derived by walking the type graph of the canonical
checkpoint roots (see ``src/graph/type_discovery.py``), not from a hand-written
module list. LangGraph silently blocks an unregistered type on deserialization,
and a silent gap in persistence is exactly the kind of failure this system must
not have.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.event_hooks import (
    SerdeEvent,
    register_serde_event_listener,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.graph.state import ProjectState
from src.graph.type_discovery import discover_types_from, type_keys
from src.graph.workflow_state import EvaluationGraphState, new_thread_id
from src.workflow.errors import WorkflowError, WorkflowErrorCode, WorkflowErrorReport


class CheckpointerKind(StrEnum):
    """Which checkpoint backend to build.

    POSTGRES is declared so that the injection point is visible in the contract,
    but it is not implemented in Phase 1A and requesting it fails loudly rather
    than silently degrading to memory.
    """

    IN_MEMORY = "IN_MEMORY"
    POSTGRES = "POSTGRES"


CHECKPOINT_ROOTS: tuple[type, ...] = (EvaluationGraphState, ProjectState)
"""The canonical roots of everything that crosses the checkpoint boundary.

``EvaluationGraphState`` is the LangGraph channel state and already contains
``ProjectState``; the domain root is listed explicitly so that the registration
set stays correct even if the graph state is ever restructured.
"""

CHECKPOINTED_TYPES: tuple[type, ...] = discover_types_from(*CHECKPOINT_ROOTS)
"""Every project model and enum reachable from the checkpoint roots.

Computed at import time by recursive annotation traversal. A model newly wired
into the state graph is registered automatically; a model that is never reached
is reported by the completeness tests rather than failing silently at runtime.
"""


def build_serializer() -> JsonPlusSerializer:
    """Serializer registered for exactly the checkpoint-reachable types.

    Built in strict mode (``allowed_msgpack_modules=None`` as the base), so the
    allowlist is the complete permission set rather than an addition to a
    permissive default.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=None).with_msgpack_allowlist(
        CHECKPOINTED_TYPES
    )


# ---------------------------------------------------------------------------
# Registration auditing
# ---------------------------------------------------------------------------

BLOCKING_SERDE_EVENT_KINDS = frozenset({"msgpack_blocked", "msgpack_unregistered_allowed"})
"""Serde events that mean a type was not properly registered."""


@contextmanager
def audit_serde_registration() -> Iterator[list[SerdeEvent]]:
    """Record serde allowlist events raised inside the block.

    Uses LangGraph's public event-hook API rather than parsing log output, so
    the check is deterministic. A non-empty result means some type crossed the
    boundary without being registered -- which, in strict mode, means it came
    back degraded.
    """
    events: list[SerdeEvent] = []

    def listener(event: SerdeEvent) -> None:
        if event.get("kind") in BLOCKING_SERDE_EVENT_KINDS:
            events.append(event)

    unregister: Callable[[], None] = register_serde_event_listener(listener)
    try:
        yield events
    finally:
        unregister()


def unregistered_type_keys(events: list[SerdeEvent]) -> set[tuple[str, str]]:
    """The ``(module, name)`` pairs reported by an audit."""
    return {(event["module"], event["name"]) for event in events}


# ---------------------------------------------------------------------------
# Checkpointer construction
# ---------------------------------------------------------------------------

def build_checkpointer(
    kind: CheckpointerKind = CheckpointerKind.IN_MEMORY,
) -> BaseCheckpointSaver:
    """Build a checkpoint saver.

    Returns the abstract base type on purpose: callers depend on the interface,
    never on the implementation.
    """
    if kind is CheckpointerKind.IN_MEMORY:
        return InMemorySaver(serde=build_serializer())
    raise WorkflowErrorReport(
        WorkflowError(
            code=WorkflowErrorCode.CHECKPOINTER_UNAVAILABLE,
            node="build_checkpointer",
            message=(
                f"checkpointer kind {kind.value} is declared but not implemented in "
                "Phase 1A; only IN_MEMORY is available"
            ),
            recoverable=False,
            metadata={"requested_kind": kind.value},
        )
    )


def thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    """LangGraph runtime config addressing one checkpoint thread."""
    return {"configurable": {"thread_id": thread_id}}


__all__ = [
    "BLOCKING_SERDE_EVENT_KINDS",
    "CHECKPOINTED_TYPES",
    "CHECKPOINT_ROOTS",
    "CheckpointerKind",
    "audit_serde_registration",
    "build_checkpointer",
    "build_serializer",
    "new_thread_id",
    "thread_config",
    "type_keys",
    "unregistered_type_keys",
]
