"""Injectable clock for workflow timing.

Node timing has to be assertable without real sleeps, and a human pause between
an interrupt and a resume has to be simulable. Both need the workflow layer to
read time through one seam rather than calling ``utc_now()`` directly.

The domain layer keeps using ``src.schemas.common.utc_now`` -- this seam exists
only for workflow execution timing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Protocol

from src.schemas.common import utc_now


class Clock(Protocol):
    """Anything that can report the current UTC time."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock. Reads the real wall clock."""

    def now(self) -> datetime:
        return utc_now()


class ManualClock:
    """Deterministic test clock.

    Each read advances by ``tick``, so successive timestamps are ordered and
    distinct without any real waiting. ``advance()`` simulates a longer gap,
    such as a human taking minutes to answer an interrupt.
    """

    def __init__(
        self,
        start: datetime | None = None,
        tick: timedelta = timedelta(milliseconds=1),
    ) -> None:
        if start is None:
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if start.tzinfo is None:
            raise ValueError("ManualClock must start from a timezone-aware datetime")
        self._current = start
        self._tick = tick

    def now(self) -> datetime:
        self._current += self._tick
        return self._current

    def peek(self) -> datetime:
        """Current time without advancing."""
        return self._current

    def advance(self, seconds: float) -> None:
        """Jump forward, e.g. to simulate a human pause across an interrupt."""
        self._current += timedelta(seconds=seconds)


_active_clock: ContextVar[Clock] = ContextVar("_active_clock", default=SystemClock())


def workflow_now() -> datetime:
    """The current time, as the workflow layer sees it."""
    return _active_clock.get().now()


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    """Install a clock for the duration of the block."""
    token = _active_clock.set(clock)
    try:
        yield clock
    finally:
        _active_clock.reset(token)


__all__ = ["Clock", "ManualClock", "SystemClock", "use_clock", "workflow_now"]
