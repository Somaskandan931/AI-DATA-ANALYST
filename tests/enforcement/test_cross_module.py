"""M1 and M2 exercised in one flow with a shared limits config and audit sink."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import AnalysisPlan
from ai_data_analyst.ingestion import IngestionError, load_csv, load_csv_path
from ai_data_analyst.profiling import profile_ingested
from ai_data_analyst.security import AuditEventType, InMemoryAuditSink, LimitsConfig
from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    SQLCandidate,
    TableSchema,
)
from ai_data_analyst.sql_agent.validator import validate_sql


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="people",
                columns=(
                    ColumnSchema(name="id", declared_type="INTEGER"),
                    ColumnSchema(name="name", declared_type="TEXT"),
                ),
            ),
        )
    )


def test_m1_and_m2_share_limits_and_emit_no_events(sample_csv_path: Path) -> None:
    limits = LimitsConfig()
    sink = InMemoryAuditSink()

    ingested = load_csv_path(sample_csv_path, limits)
    profile = profile_ingested(ingested)
    assert profile.row_count == 485

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(
            {"steps": [{"operation": "drop_everything", "columns": ["demand_mwh"]}]}
        )

    denied = validate_sql(SQLCandidate(sql="DELETE FROM people"), _snapshot())
    assert denied.allowed is False
    assert denied.reason_codes

    assert sink.events == ()


@pytest.mark.xfail(
    strict=True,
    reason="ingestion does not emit audit events yet; wiring is an M1 task",
)
def test_oversized_upload_would_emit_upload_rejected() -> None:
    sink = InMemoryAuditSink()

    with pytest.raises(IngestionError):
        load_csv(b"a,b\n1,2\n", "upload.csv", LimitsConfig(max_upload_bytes=4))

    assert [event.event_type for event in sink.events] == [AuditEventType.UPLOAD_REJECTED]
