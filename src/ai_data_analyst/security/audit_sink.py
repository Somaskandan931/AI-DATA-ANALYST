"""Audit sinks and a failure-isolated emit helper."""

from __future__ import annotations

import secrets
import threading
from typing import Protocol, runtime_checkable

from ai_data_analyst.security.audit import AuditEvent


@runtime_checkable
class AuditSink(Protocol):
    """A destination for audit events."""

    def emit(self, event: AuditEvent) -> None:
        """Record *event*."""
        ...


class NullAuditSink:
    """An audit sink that deliberately discards every event."""

    def emit(self, event: AuditEvent) -> None:
        return None


class InMemoryAuditSink:
    """A thread-safe sink that keeps events in memory for tests and inspection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot of the recorded events."""
        with self._lock:
            return tuple(self._events)

    def clear(self) -> None:
        """Discard all recorded events."""
        with self._lock:
            self._events.clear()


def safe_emit(sink: AuditSink, event: AuditEvent) -> bool:
    """Emit *event*, returning False if the sink fails.

    A failing audit sink must never change a caller's validation or execution outcome.
    This helper catches ``Exception`` (not ``BaseException``) and never raises. It does not
    log the exception text or the event contents.
    """
    try:
        sink.emit(event)
    except Exception:
        return False
    return True


def new_correlation_id() -> str:
    """Return a fresh random correlation identifier."""
    return secrets.token_hex(16)
