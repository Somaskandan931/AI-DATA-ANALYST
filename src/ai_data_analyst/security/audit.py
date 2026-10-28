"""Typed audit events shared by M1 and M2.

An event carries only enums, patterned codes, hashes, counts and durations. It has no
free-text field, so it cannot carry SQL, parameter values, cell values, file contents,
credentials or error messages.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

_CODE_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{0,63}$"
_TABLE_PATTERN: Final[str] = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
_HASH_PATTERN: Final[str] = r"^[0-9a-f]{64}$"
_CORRELATION_PATTERN: Final[str] = r"^[0-9a-f]{8,64}$"

ReasonCode = Annotated[str, Field(pattern=_CODE_PATTERN)]
ReferencedTable = Annotated[str, Field(pattern=_TABLE_PATTERN)]


class AuditEventType(StrEnum):
    """The auditable action that occurred."""

    UPLOAD_ACCEPTED = "upload_accepted"
    UPLOAD_REJECTED = "upload_rejected"
    PLAN_REJECTED = "plan_rejected"
    PLAN_STEP_EXECUTED = "plan_step_executed"
    REPORT_GENERATED = "report_generated"
    SQL_VALIDATED = "sql_validated"
    SQL_EXECUTED = "sql_executed"
    LIMIT_EXCEEDED = "limit_exceeded"


class AuditModule(StrEnum):
    """The module family that produced the event."""

    M1 = "m1"
    M2 = "m2"


class AuditOutcome(StrEnum):
    """The result of the audited action."""

    OK = "ok"
    DENIED = "denied"
    ERROR = "error"


_M1_EVENT_TYPES = frozenset(
    {
        AuditEventType.UPLOAD_ACCEPTED,
        AuditEventType.UPLOAD_REJECTED,
        AuditEventType.PLAN_REJECTED,
        AuditEventType.PLAN_STEP_EXECUTED,
        AuditEventType.REPORT_GENERATED,
    }
)
_M2_EVENT_TYPES = frozenset(
    {
        AuditEventType.SQL_VALIDATED,
        AuditEventType.SQL_EXECUTED,
    }
)
_ALLOWED_OUTCOMES: Final[dict[AuditEventType, frozenset[AuditOutcome]]] = {
    AuditEventType.UPLOAD_ACCEPTED: frozenset({AuditOutcome.OK, AuditOutcome.ERROR}),
    AuditEventType.UPLOAD_REJECTED: frozenset({AuditOutcome.DENIED}),
    AuditEventType.PLAN_REJECTED: frozenset({AuditOutcome.DENIED}),
    AuditEventType.PLAN_STEP_EXECUTED: frozenset({AuditOutcome.OK, AuditOutcome.ERROR}),
    AuditEventType.REPORT_GENERATED: frozenset({AuditOutcome.OK, AuditOutcome.ERROR}),
    AuditEventType.SQL_VALIDATED: frozenset({AuditOutcome.OK, AuditOutcome.DENIED}),
    AuditEventType.SQL_EXECUTED: frozenset({AuditOutcome.OK, AuditOutcome.ERROR}),
    AuditEventType.LIMIT_EXCEEDED: frozenset({AuditOutcome.DENIED}),
}


class AuditEvent(BaseModel):
    """One immutable, privacy-preserving audit record."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["1.0"] = "1.0"
    event_type: AuditEventType
    module: AuditModule
    outcome: AuditOutcome
    timestamp: AwareDatetime
    correlation_id: str | None = Field(default=None, pattern=_CORRELATION_PATTERN)
    reason_codes: tuple[ReasonCode, ...] = Field(default=(), max_length=10)
    operation: str | None = Field(default=None, pattern=_CODE_PATTERN)
    dataset_fingerprint: str | None = Field(default=None, pattern=_HASH_PATTERN)
    subject_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    referenced_tables: tuple[ReferencedTable, ...] = Field(default=(), max_length=20)
    row_count: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    truncated: bool | None = None

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must have a zero UTC offset")
        return value

    @model_validator(mode="after")
    def _validate_event_rules(self) -> Self:
        if self.event_type in _M1_EVENT_TYPES and self.module is not AuditModule.M1:
            raise ValueError(f"{self.event_type.value} requires module 'm1'")
        if self.event_type in _M2_EVENT_TYPES and self.module is not AuditModule.M2:
            raise ValueError(f"{self.event_type.value} requires module 'm2'")

        if self.module is AuditModule.M2:
            if self.dataset_fingerprint is not None:
                raise ValueError("dataset_fingerprint is only allowed for module 'm1'")
            if self.operation is not None:
                raise ValueError("operation is only allowed for module 'm1'")
        if self.module is AuditModule.M1:
            if self.referenced_tables:
                raise ValueError("referenced_tables is only allowed for module 'm2'")
            if self.truncated is not None:
                raise ValueError("truncated is only allowed for module 'm2'")

        if self.event_type is AuditEventType.PLAN_STEP_EXECUTED and self.operation is None:
            raise ValueError("operation is required for plan_step_executed")

        if self.outcome not in _ALLOWED_OUTCOMES[self.event_type]:
            raise ValueError(
                f"{self.event_type.value} does not allow outcome {self.outcome.value!r}"
            )
        if self.outcome is not AuditOutcome.OK and not self.reason_codes:
            raise ValueError("reason_codes must be non-empty when outcome is not 'ok'")
        return self
