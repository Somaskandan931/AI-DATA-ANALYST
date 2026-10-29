from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ai_data_analyst.security.audit import (
    AuditEvent,
    AuditEventType,
    AuditModule,
    AuditOutcome,
)

TIMESTAMP = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
FINGERPRINT = "a" * 64


def _event(**overrides: object) -> AuditEvent:
    fields: dict[str, object] = {
        "event_type": AuditEventType.UPLOAD_ACCEPTED,
        "module": AuditModule.M1,
        "outcome": AuditOutcome.OK,
        "timestamp": TIMESTAMP,
    }
    fields.update(overrides)
    return AuditEvent(**fields)


@pytest.mark.parametrize(
    ("event_type", "module", "outcome", "extra"),
    [
        (AuditEventType.UPLOAD_ACCEPTED, AuditModule.M1, AuditOutcome.OK, {}),
        (
            AuditEventType.UPLOAD_REJECTED,
            AuditModule.M1,
            AuditOutcome.DENIED,
            {"reason_codes": ("file_too_large",)},
        ),
        (
            AuditEventType.PLAN_REJECTED,
            AuditModule.M1,
            AuditOutcome.DENIED,
            {"reason_codes": ("unknown_column",)},
        ),
        (
            AuditEventType.PLAN_STEP_EXECUTED,
            AuditModule.M1,
            AuditOutcome.OK,
            {"operation": "summary_stats"},
        ),
        (AuditEventType.REPORT_GENERATED, AuditModule.M1, AuditOutcome.OK, {}),
        (AuditEventType.SQL_VALIDATED, AuditModule.M2, AuditOutcome.OK, {}),
        (
            AuditEventType.SQL_EXECUTED,
            AuditModule.M2,
            AuditOutcome.ERROR,
            {"reason_codes": ("query_timeout",), "row_count": 0, "duration_ms": 12.5},
        ),
        (
            AuditEventType.LIMIT_EXCEEDED,
            AuditModule.M1,
            AuditOutcome.DENIED,
            {"reason_codes": ("max_rows",)},
        ),
        (
            AuditEventType.LIMIT_EXCEEDED,
            AuditModule.M2,
            AuditOutcome.DENIED,
            {"reason_codes": ("max_result_rows",)},
        ),
    ],
)
def test_valid_event_for_every_type(
    event_type: AuditEventType,
    module: AuditModule,
    outcome: AuditOutcome,
    extra: dict[str, object],
):
    event = _event(event_type=event_type, module=module, outcome=outcome, **extra)
    assert event.event_type is event_type
    assert event.module is module
    assert event.outcome is outcome


def test_event_type_requires_matching_module():
    with pytest.raises(ValidationError, match="requires module 'm1'"):
        _event(event_type=AuditEventType.UPLOAD_ACCEPTED, module=AuditModule.M2)
    with pytest.raises(ValidationError, match="requires module 'm2'"):
        _event(event_type=AuditEventType.SQL_VALIDATED, module=AuditModule.M1)


def test_m1_fields_are_rejected_for_m2():
    with pytest.raises(ValidationError, match="dataset_fingerprint"):
        _event(
            event_type=AuditEventType.SQL_VALIDATED,
            module=AuditModule.M2,
            dataset_fingerprint=FINGERPRINT,
        )
    with pytest.raises(ValidationError, match="operation"):
        _event(
            event_type=AuditEventType.SQL_VALIDATED,
            module=AuditModule.M2,
            operation="summary_stats",
        )


def test_m2_fields_are_rejected_for_m1():
    with pytest.raises(ValidationError, match="referenced_tables"):
        _event(referenced_tables=("customers",))
    with pytest.raises(ValidationError, match="truncated"):
        _event(truncated=True)


def test_plan_step_executed_requires_operation():
    with pytest.raises(ValidationError, match="operation is required"):
        _event(event_type=AuditEventType.PLAN_STEP_EXECUTED)


@pytest.mark.parametrize(
    ("event_type", "module", "outcome", "extra"),
    [
        (AuditEventType.UPLOAD_REJECTED, AuditModule.M1, AuditOutcome.OK, {}),
        (AuditEventType.UPLOAD_REJECTED, AuditModule.M1, AuditOutcome.ERROR, {}),
        (AuditEventType.PLAN_REJECTED, AuditModule.M1, AuditOutcome.OK, {}),
        (AuditEventType.LIMIT_EXCEEDED, AuditModule.M1, AuditOutcome.OK, {}),
        (AuditEventType.UPLOAD_ACCEPTED, AuditModule.M1, AuditOutcome.DENIED, {}),
        (
            AuditEventType.PLAN_STEP_EXECUTED,
            AuditModule.M1,
            AuditOutcome.DENIED,
            {"operation": "summary_stats"},
        ),
        (AuditEventType.REPORT_GENERATED, AuditModule.M1, AuditOutcome.DENIED, {}),
        (AuditEventType.SQL_EXECUTED, AuditModule.M2, AuditOutcome.DENIED, {}),
        (AuditEventType.SQL_VALIDATED, AuditModule.M2, AuditOutcome.ERROR, {}),
    ],
)
def test_invalid_outcome_is_rejected(
    event_type: AuditEventType,
    module: AuditModule,
    outcome: AuditOutcome,
    extra: dict[str, object],
):
    with pytest.raises(ValidationError, match="does not allow outcome"):
        _event(event_type=event_type, module=module, outcome=outcome, **extra)


def test_non_ok_outcome_requires_reason_codes():
    with pytest.raises(ValidationError, match="reason_codes"):
        _event(event_type=AuditEventType.UPLOAD_REJECTED, outcome=AuditOutcome.DENIED)
    with pytest.raises(ValidationError, match="reason_codes"):
        _event(
            event_type=AuditEventType.SQL_EXECUTED,
            module=AuditModule.M2,
            outcome=AuditOutcome.ERROR,
        )


def test_timestamp_is_required():
    with pytest.raises(ValidationError):
        AuditEvent(
            event_type=AuditEventType.UPLOAD_ACCEPTED,
            module=AuditModule.M1,
            outcome=AuditOutcome.OK,
        )


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        _event(timestamp=datetime(2025, 1, 2, 3, 4, 5))


def test_non_utc_timestamp_is_rejected():
    with pytest.raises(ValidationError, match="zero UTC offset"):
        _event(
            timestamp=datetime(
                2025,
                1,
                2,
                3,
                4,
                5,
                tzinfo=timezone(timedelta(hours=2)),
            )
        )


@pytest.mark.parametrize("code", ["Upper", "has space", 'has"quote', "a" * 65])
def test_bad_reason_code_is_rejected(code: str):
    with pytest.raises(ValidationError):
        _event(
            event_type=AuditEventType.UPLOAD_REJECTED,
            outcome=AuditOutcome.DENIED,
            reason_codes=(code,),
        )


def test_more_than_ten_reason_codes_are_rejected():
    with pytest.raises(ValidationError):
        _event(
            event_type=AuditEventType.UPLOAD_REJECTED,
            outcome=AuditOutcome.DENIED,
            reason_codes=tuple(f"code_{index}" for index in range(11)),
        )


@pytest.mark.parametrize("operation", ["SummaryStats", "bad operation"])
def test_bad_operation_is_rejected(operation: str):
    with pytest.raises(ValidationError):
        _event(event_type=AuditEventType.PLAN_STEP_EXECUTED, operation=operation)


@pytest.mark.parametrize("correlation_id", ["abc", "A" * 8, "a" * 65])
def test_bad_correlation_id_is_rejected(correlation_id: str):
    with pytest.raises(ValidationError):
        _event(correlation_id=correlation_id)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("dataset_fingerprint", "A" * 64),
        ("dataset_fingerprint", "a" * 63),
        ("subject_hash", "g" * 64),
    ],
)
def test_bad_hash_is_rejected(field_name: str, value: str):
    with pytest.raises(ValidationError):
        _event(**{field_name: value})


@pytest.mark.parametrize("table", ["1customers", "customer-names", "a" * 65])
def test_bad_referenced_table_is_rejected(table: str):
    with pytest.raises(ValidationError):
        _event(
            event_type=AuditEventType.SQL_VALIDATED,
            module=AuditModule.M2,
            referenced_tables=(table,),
        )


def test_more_than_twenty_referenced_tables_are_rejected():
    with pytest.raises(ValidationError):
        _event(
            event_type=AuditEventType.SQL_VALIDATED,
            module=AuditModule.M2,
            referenced_tables=tuple(f"table_{index}" for index in range(21)),
        )


def test_negative_counts_are_rejected():
    with pytest.raises(ValidationError):
        _event(row_count=-1)
    with pytest.raises(ValidationError):
        _event(duration_ms=-0.1)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_duration_is_rejected(duration: float):
    with pytest.raises(ValidationError):
        _event(duration_ms=duration)


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        _event(notes="not allowed")


def test_invalid_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        _event(schema_version="2.0")


def test_event_is_frozen():
    event = _event()
    with pytest.raises(ValidationError):
        event.outcome = AuditOutcome.DENIED
    with pytest.raises(ValidationError):
        event.reason_codes = ()


def test_json_round_trip_is_lossless():
    event = _event(
        event_type=AuditEventType.SQL_EXECUTED,
        module=AuditModule.M2,
        outcome=AuditOutcome.OK,
        correlation_id="a" * 8,
        reason_codes=("query_ok",),
        subject_hash="b" * 64,
        referenced_tables=("customers",),
        row_count=10,
        duration_ms=1.25,
        truncated=False,
    )
    assert AuditEvent.model_validate_json(event.model_dump_json()) == event
