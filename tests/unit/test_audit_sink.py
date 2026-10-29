from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from ai_data_analyst.security.audit import (
    AuditEvent,
    AuditEventType,
    AuditModule,
    AuditOutcome,
)
from ai_data_analyst.security.audit_sink import (
    AuditSink,
    InMemoryAuditSink,
    NullAuditSink,
    new_correlation_id,
    safe_emit,
)

CORRELATION_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")


def _event() -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.UPLOAD_ACCEPTED,
        module=AuditModule.M1,
        outcome=AuditOutcome.OK,
        timestamp=datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
    )


def test_builtin_sinks_satisfy_the_protocol():
    assert isinstance(NullAuditSink(), AuditSink)
    assert isinstance(InMemoryAuditSink(), AuditSink)


def test_null_sink_discards_events():
    assert NullAuditSink().emit(_event()) is None


def test_safe_emit_records_event():
    sink = InMemoryAuditSink()
    event = _event()
    assert safe_emit(sink, event) is True
    assert sink.events == (event,)


def test_safe_emit_returns_false_when_sink_raises():
    class FailingSink:
        def emit(self, event: AuditEvent) -> None:
            raise RuntimeError("sink failure")

    assert safe_emit(FailingSink(), _event()) is False


def test_safe_emit_does_not_swallow_keyboard_interrupt():
    class InterruptingSink:
        def emit(self, event: AuditEvent) -> None:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        safe_emit(InterruptingSink(), _event())


def test_in_memory_sink_returns_an_immutable_snapshot_and_clears():
    sink = InMemoryAuditSink()
    event = _event()
    sink.emit(event)
    assert isinstance(sink.events, tuple)
    assert sink.events == (event,)
    sink.clear()
    assert sink.events == ()


def test_new_correlation_id_is_valid_and_unique():
    first = new_correlation_id()
    second = new_correlation_id()
    assert CORRELATION_PATTERN.fullmatch(first)
    assert CORRELATION_PATTERN.fullmatch(second)
    assert first != second
