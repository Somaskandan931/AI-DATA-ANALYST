"""Workspace-specific Inspector sections and stacked definition lists."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_data_analyst.models import ColumnProfile, DatasetProfile
from ai_data_analyst.security import (
    AuditEvent,
    AuditEventType,
    AuditModule,
    AuditOutcome,
    LimitsConfig,
)
from ai_data_analyst.ui import layout

pytest.importorskip("streamlit")

FINGERPRINT = "e0b688d65789cee9cd2f0bee7581a9d4339d5b29a1a902501eb5f20b052a5354"
PROFILE = DatasetProfile(
    dataset_fingerprint=FINGERPRINT,
    row_count=2,
    column_count=1,
    duplicate_row_count=0,
    columns=(ColumnProfile(name="x", inferred_type="float", missing_count=0, unique_count=2),),
)


def _event(
    event_type: AuditEventType,
    outcome: AuditOutcome,
    module: AuditModule,
    reason_codes: tuple[str, ...] = (),
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        module=module,
        outcome=outcome,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        reason_codes=reason_codes,
    )


def _auto_eda(cleaning_log: tuple[str, ...] = (), audit_events: tuple[AuditEvent, ...] = ()) -> str:
    sections = layout.auto_eda_inspector_sections(
        profile=PROFILE,
        cleaning_log=cleaning_log,
        audit_events=audit_events,
        limits=LimitsConfig(),
    )
    return layout.render_inspector(sections)


def test_auto_eda_inspector_has_its_fields_and_human_limits() -> None:
    html = _auto_eda(cleaning_log=("Removed 5 duplicate rows",))

    assert "<table" not in html
    assert "Dataset fingerprint" in html
    assert f">{FINGERPRINT[:12]}<" in html
    assert f'title="{FINGERPRINT}"' in html
    assert html.count(FINGERPRINT) == 2  # the title attribute and the details block
    assert "<dt>Profile</dt>" in html and "<dt>Report</dt>" in html
    assert "Step 1" in html and "Removed 5 duplicate rows" in html
    assert "<dt>Max upload size</dt><dd>25 MB</dd>" in html
    assert "<dt>Max rows</dt><dd>250,000</dd>" in html
    assert "<dt>Max execution time</dt><dd>30 s</dd>" in html
    assert "SQL timeout" not in html
    assert "Max result rows" not in html


def test_sql_inspector_omits_eda_fields_and_shows_query_limits() -> None:
    # The rail's DATABASE section is the single place that names the database, so the
    # Inspector no longer repeats it (UI fix, item 6).
    sections = layout.sql_inspector_sections(
        tables=(("electricity_demand", 6),),
        limits=LimitsConfig(),
    )
    html = layout.render_inspector(sections)

    assert "Selected database" not in html
    assert "Electricity Demand Sample" not in html
    assert ">Database<" not in html
    assert "<dt>electricity_demand</dt><dd>6 columns</dd>" in html
    assert "<dt>SQL timeout</dt><dd>5 s</dd>" in html
    assert "<dt>Max execution time</dt><dd>30 s</dd>" in html
    assert "<dt>Max result rows</dt><dd>1,000</dd>" in html
    assert "Dataset fingerprint" not in html
    assert "Cleaning" not in html
    assert "<dt>Profile</dt>" not in html


def test_empty_rows_and_sections_are_omitted() -> None:
    html = layout.render_inspector(
        (
            layout.InspectorSection("Nothing here"),
            layout.InspectorSection("Values", rows=(("Blank", ""), ("Kept", "x"))),
        )
    )

    assert "Nothing here" not in html
    assert ">Blank<" not in html
    assert ">Kept<" in html and ">x<" in html
    assert layout.render_inspector(()) == ""
    assert layout.render_inspector((layout.InspectorSection("Empty"),)) == ""


def test_inspector_escapes_hostile_labels_and_values() -> None:
    html = layout.render_inspector(
        (
            layout.InspectorSection(
                "<script>title</script>",
                rows=(('<img src=x onerror="a">', "<script>value</script>"),),
            ),
        )
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert "&lt;img" in html


def test_activity_appears_only_when_real_events_exist() -> None:
    without_events = _auto_eda()
    assert "Activity" not in without_events

    with_events = _auto_eda(
        audit_events=(
            _event(AuditEventType.UPLOAD_ACCEPTED, AuditOutcome.OK, AuditModule.M1),
            _event(AuditEventType.UPLOAD_ACCEPTED, AuditOutcome.OK, AuditModule.M1),
            _event(
                AuditEventType.SQL_VALIDATED,
                AuditOutcome.DENIED,
                AuditModule.M2,
                ("unsafe",),
            ),
        )
    )

    assert "Activity" in with_events
    assert "<dt>Upload accepted</dt><dd>2 times</dd>" in with_events
    assert "<dt>Query blocked</dt><dd>1 time</dd>" in with_events
    assert "No events recorded" not in with_events


def test_inspector_never_prints_placeholder_jargon() -> None:
    html = _auto_eda()

    for phrase in ("Not available", "M1", "M2", "audit event", "stays empty", "contract"):
        assert phrase not in html
