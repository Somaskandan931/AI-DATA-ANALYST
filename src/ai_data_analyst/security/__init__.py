"""Security primitives: limits, audit events, hashing, and audit sinks."""

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
from ai_data_analyst.security.hashing import hash_canonical_json, hash_text
from ai_data_analyst.security.limits import (
    DEFAULT_LIMITS,
    ENV_VARS,
    LimitExceededError,
    LimitsConfig,
    check_shape,
    check_upload_size,
)

__all__ = [
    "DEFAULT_LIMITS",
    "ENV_VARS",
    "AuditEvent",
    "AuditEventType",
    "AuditModule",
    "AuditOutcome",
    "AuditSink",
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
]
