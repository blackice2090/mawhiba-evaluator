"""Recursive discovery of the types that cross the checkpoint boundary.

LangGraph's msgpack serializer matches an allowlist of exact
``(module, type name)`` pairs. A type that is missing from the allowlist is
**silently blocked** on deserialization in strict mode -- it comes back as a
plain dictionary rather than raising. That failure mode is quiet and severe, so
registration must not depend on anyone remembering to maintain a list.

This module derives the registration set by walking the type graph of the
canonical checkpoint roots. A newly added model reachable from
``EvaluationGraphState`` is therefore registered automatically the moment it is
wired into the state; a model that is *not* reachable is caught by the
completeness tests instead of failing silently at runtime.
"""

from __future__ import annotations

from enum import Enum
from inspect import isclass
from typing import Any, get_args, get_origin

from pydantic import BaseModel

PROJECT_PACKAGE = "src."


def _is_project_type(candidate: Any) -> bool:
    """True for a Pydantic model or enum defined inside this project."""
    return (
        isclass(candidate)
        and issubclass(candidate, (BaseModel, Enum))
        and candidate.__module__.startswith(PROJECT_PACKAGE)
    )


def _annotation_candidates(annotation: Any) -> list[Any]:
    """Every type mentioned by an annotation, at any nesting depth.

    Covers unions, optionals, containers, Annotated metadata and Pydantic
    generics. ``Tracked[str]`` in particular is a real class whose ``__name__``
    is ``"Tracked[str]"``, so both it and its unparametrized origin are yielded.
    """
    found: list[Any] = []
    stack: list[Any] = [annotation]
    seen: set[int] = set()

    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        found.append(current)

        origin = get_origin(current)
        if origin is not None:
            stack.append(origin)
        stack.extend(get_args(current))

        # Pydantic generics: recover the origin class and its parameters, which
        # typing.get_origin / get_args do not expose for a parametrized model.
        metadata = getattr(current, "__pydantic_generic_metadata__", None)
        if metadata:
            if metadata.get("origin") is not None:
                stack.append(metadata["origin"])
            stack.extend(metadata.get("args", ()))

    return found


def discover_types_from(*roots: type) -> tuple[type, ...]:
    """Collect every project model and enum reachable from the given roots.

    Traversal is over declared field annotations, which is what the serializer
    actually encounters. The result is deterministic and ordered by discovery,
    so the allowlist does not churn between runs.
    """
    discovered: dict[tuple[str, str], type] = {}
    pending: list[type] = []

    def register(candidate: Any) -> None:
        if not _is_project_type(candidate):
            return
        key = (candidate.__module__, candidate.__name__)
        if key in discovered:
            return
        discovered[key] = candidate
        if issubclass(candidate, BaseModel):
            pending.append(candidate)

    for root in roots:
        register(root)

    while pending:
        model = pending.pop(0)
        for field in model.model_fields.values():
            for candidate in _annotation_candidates(field.annotation):
                register(candidate)
        # A parametrized generic keeps its origin's fields; make sure the
        # origin itself is registered too.
        metadata = getattr(model, "__pydantic_generic_metadata__", None)
        if metadata and metadata.get("origin") is not None:
            register(metadata["origin"])

    return tuple(discovered.values())


def type_keys(types: tuple[type, ...]) -> set[tuple[str, str]]:
    """The ``(module, name)`` allowlist keys for a set of types."""
    return {(t.__module__, t.__name__) for t in types}


__all__ = ["discover_types_from", "type_keys"]
