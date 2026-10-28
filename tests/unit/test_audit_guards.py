from __future__ import annotations

import json
import types
from datetime import UTC, datetime
from enum import Enum
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ai_data_analyst.security import (
    AuditEvent,
    AuditEventType,
    AuditModule,
    AuditOutcome,
)

TIMESTAMP = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
FINGERPRINT = "a" * 64
SUBJECT_HASH = "b" * 64


def _event(**overrides: object) -> AuditEvent:
    fields: dict[str, object] = {
        "event_type": AuditEventType.UPLOAD_ACCEPTED,
        "module": AuditModule.M1,
        "outcome": AuditOutcome.OK,
        "timestamp": TIMESTAMP,
    }
    fields.update(overrides)
    return AuditEvent(**fields)


FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "sql",
        "query",
        "text",
        "message",
        "msg",
        "detail",
        "details",
        "error",
        "exception",
        "traceback",
        "params",
        "parameters",
        "values",
        "value",
        "row",
        "rows",
        "cell",
        "cells",
        "content",
        "contents",
        "data",
        "secret",
        "password",
        "token",
        "api_key",
        "credential",
        "question",
        "prompt",
        "path",
        "filename",
        "file_name",
    }
)


def test_no_forbidden_field_names():
    assert set(AuditEvent.model_fields).isdisjoint(FORBIDDEN_FIELD_NAMES)


def _annotation_involves_str(annotation: object) -> bool:
    if annotation is str:
        return True
    if getattr(annotation, "__metadata__", ()):
        return _annotation_involves_str(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return any(
            _annotation_involves_str(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    if origin is tuple:
        return any(
            _annotation_involves_str(argument)
            for argument in get_args(annotation)
            if argument is not Ellipsis
        )
    return False


def _has_pattern_metadata(metadata: object) -> bool:
    if not isinstance(metadata, (list, tuple)):
        return False
    for item in metadata:
        if getattr(item, "pattern", None) is not None:
            return True
        if _has_pattern_metadata(getattr(item, "metadata", ())):
            return True
    return False


def _is_constrained(annotation: object, field: FieldInfo | None = None) -> bool:
    if field is not None:
        if getattr(field, "pattern", None) is not None:
            return True
        if _has_pattern_metadata(field.metadata):
            return True
    if annotation is str:
        return False
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return True
    if get_origin(annotation) is Literal:
        return True
    metadata = getattr(annotation, "__metadata__", ())
    if metadata:
        if _has_pattern_metadata(metadata):
            return True
        return _is_constrained(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return all(
            _is_constrained(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    if origin is tuple:
        return all(
            _is_constrained(argument)
            for argument in get_args(annotation)
            if argument is not Ellipsis
        )
    return True


def _unconstrained_string_fields(model: type[BaseModel]) -> list[str]:
    return [
        name
        for name, field in model.model_fields.items()
        if _annotation_involves_str(field.annotation)
        and not _is_constrained(field.annotation, field)
    ]


def test_every_string_field_is_constrained():
    assert _unconstrained_string_fields(AuditEvent) == []


def test_guard_rejects_a_new_unconstrained_string_field():
    class UnsafeEvent(BaseModel):
        notes: str

    class UnsafeTupleEvent(BaseModel):
        notes: tuple[str, ...]

    assert _unconstrained_string_fields(UnsafeEvent) == ["notes"]
    assert _unconstrained_string_fields(UnsafeTupleEvent) == ["notes"]


def _worst_case_m1() -> AuditEvent:
    return _event(
        event_type=AuditEventType.REPORT_GENERATED,
        module=AuditModule.M1,
        outcome=AuditOutcome.OK,
        correlation_id="a" * 8,
        reason_codes=("report_ready",),
        operation="summary_stats",
        dataset_fingerprint=FINGERPRINT,
        subject_hash=SUBJECT_HASH,
        row_count=10,
        duration_ms=1.25,
    )


def _worst_case_m2() -> AuditEvent:
    return _event(
        event_type=AuditEventType.SQL_EXECUTED,
        module=AuditModule.M2,
        outcome=AuditOutcome.OK,
        correlation_id="b" * 8,
        reason_codes=("query_ok",),
        subject_hash=SUBJECT_HASH,
        referenced_tables=("customers", "orders"),
        row_count=10,
        duration_ms=2.5,
        truncated=False,
    )


def test_worst_case_events_do_not_contain_leak_sentinels():
    """M1 and M2 events together cover every optional field."""
    payload = json.dumps(
        [
            json.loads(_worst_case_m1().model_dump_json()),
            json.loads(_worst_case_m2().model_dump_json()),
        ]
    )
    for sentinel in ("SELECT", "DROP", "password", "api_key", "@", "/", "\\"):
        assert sentinel not in payload


PUBLIC_NAMES = {
    "AuditEvent",
    "AuditEventType",
    "AuditModule",
    "AuditOutcome",
    "AuditSink",
    "DEFAULT_LIMITS",
    "ENV_VARS",
    "InMemoryAuditSink",
    "LimitExceededError",
    "LimitsConfig",
    "NullAuditSink",
    "check_shape",
    "check_upload_size",
    "hash_canonical_json",
    "hash_text",
    "new_correlation_id",
    "safe_emit",
}


def test_public_names_are_exported():
    import ai_data_analyst.security as security

    assert set(security.__all__) == PUBLIC_NAMES
