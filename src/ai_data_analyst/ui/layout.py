"""Shared layout shell, editorial headers, evidence rendering and the inspector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Final

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ..analysis import ANALYSIS_SCHEMA_VERSION
from ..models import DatasetProfile
from ..reporting import REPORT_SCHEMA_VERSION
from ..security import (
    AuditEvent,
    AuditEventType,
    AuditOutcome,
    LimitsConfig,
)
from ..visualization import CHART_SCHEMA_VERSION
from . import formatting, tables
from .evidence import EvidenceSource, EvidenceView, render_evidence_view, source_chip
from .theme.html import escape_text
from .theme.tokens import CLASSES

_SHELL_MARKER: Final = '<span class="fn-shell-marker" aria-hidden="true"></span>'


def shell() -> tuple[DeltaGenerator, DeltaGenerator]:
    """A narrow rail and a main canvas; the rail moves under the canvas when narrow."""
    rail, canvas = st.columns([1, 2.8], gap="large")
    with rail:
        st.markdown(_SHELL_MARKER, unsafe_allow_html=True)
    return rail, canvas


def app_header(wordmark: str, subtitle: str) -> None:
    """A compact masthead so the hero headline stays the only display heading."""
    st.html(
        '<header class="fn-app-header">'
        f'<p class="{CLASSES["app_wordmark"]}">{escape_text(wordmark)}</p>'
        f'<p class="{CLASSES["app_subtitle"]}">{escape_text(subtitle)}</p>'
        "</header>"
    )


def section_label(text: str, source: EvidenceSource | None = None) -> None:
    """A small mono label above a block, optionally carrying the group's single chip."""
    chip = source_chip(source) if source is not None else ""
    st.html(
        f'<div class="{CLASSES["section_head"]}">'
        f'<p class="{CLASSES["section_label"]}">{escape_text(text)}</p>{chip}</div>'
    )


def page_header(section: str, title: str, purpose: str) -> None:
    """The editorial header each inner tab starts with."""
    st.html(
        f'<header class="{CLASSES["page_heading"]}">'
        f'<p class="{CLASSES["section_label"]}">{escape_text(section)}</p>'
        f'<h2 class="{CLASSES["page_title"]}">{escape_text(title)}</h2>'
        f'<p class="{CLASSES["page_purpose"]}">{escape_text(purpose)}</p>'
        "</header>"
    )


def evidence_view(view: EvidenceView, *, fresh: bool = False) -> None:
    """Render a group of evidence cards as one escaped fragment."""
    st.html(render_evidence_view(view, fresh=fresh))


def result_marker(*, fresh: bool) -> None:
    """Marks the result block that follows; only a fresh result animates on arrival."""
    classes = CLASSES["result_marker"] + (f" {CLASSES['fresh']}" if fresh else "")
    st.html(f'<span class="{classes}" aria-hidden="true"></span>')


def table(
    rows: Sequence[Sequence[object]] | Sequence[Mapping[str, object]],
    columns: Sequence[str],
    *,
    caption: str | None = None,
) -> None:
    """A full-width table with formatted numbers and dim dashes for missing cells."""
    if caption is not None:
        st.caption(caption)
    frame = formatting.frame_from(rows, columns)
    st.dataframe(formatting.style_missing(frame), hide_index=True, width="stretch")


def data_table(
    rows: Iterable[Sequence[object]] | Iterable[Mapping[str, object]],
    columns: Sequence[str],
    *,
    labels: Mapping[str, str] | Sequence[str] | None = None,
    caption: str | None = None,
    format_values: bool = True,
) -> None:
    """A small escaped HTML table; a single row becomes a stacked key/value list."""
    st.html(
        tables.render_data(
            rows, columns, labels=labels, caption=caption, format_values=format_values
        )
    )


def computed_from(rows: Sequence[tuple[str, str]], *, label: str = "Computed from") -> None:
    """A native details block for provenance; every field is escaped."""
    body = "".join(
        f"<dt>{escape_text(name)}</dt><dd>{_provenance_value(name, value)}</dd>"
        for name, value in rows
    )
    st.html(
        f'<details class="fn-computed-from"><summary>{escape_text(label)}</summary>'
        f"<dl>{body}</dl></details>"
    )


def _provenance_value(name: str, value: str) -> str:
    """Escape a value; the key row count also carries the arrival highlight."""
    escaped = escape_text(value)
    if name == "Rows used":
        return f'<span class="{CLASSES["highlight"]}">{escaped}</span>'
    return escaped


@dataclass(frozen=True)
class InspectorSection:
    """One titled block of a stacked definition list; empty blocks are not drawn."""

    title: str
    rows: tuple[tuple[str, str], ...] = ()
    fingerprint: str | None = None


def _activity_label(event: AuditEvent) -> str:
    return _ACTIVITY_LABELS.get(
        (event.event_type, event.outcome),
        event.event_type.value.replace("_", " ").capitalize(),
    )


def _format_megabytes(value: int) -> str:
    return f"{value / (1024 * 1024):g} MB"


def _format_count(value: int) -> str:
    return f"{value:,}"


def _format_seconds(value: int) -> str:
    return f"{value:,} s"


_ACTIVITY_LABELS: Final[dict[tuple[AuditEventType, AuditOutcome], str]] = {
    (AuditEventType.UPLOAD_ACCEPTED, AuditOutcome.OK): "Upload accepted",
    (AuditEventType.UPLOAD_ACCEPTED, AuditOutcome.ERROR): "Upload failed",
    (AuditEventType.UPLOAD_REJECTED, AuditOutcome.DENIED): "Upload rejected",
    (AuditEventType.PLAN_REJECTED, AuditOutcome.DENIED): "Cleaning plan rejected",
    (AuditEventType.PLAN_STEP_EXECUTED, AuditOutcome.OK): "Cleaning step applied",
    (AuditEventType.PLAN_STEP_EXECUTED, AuditOutcome.ERROR): "Cleaning step failed",
    (AuditEventType.REPORT_GENERATED, AuditOutcome.OK): "Report generated",
    (AuditEventType.REPORT_GENERATED, AuditOutcome.ERROR): "Report failed",
    (AuditEventType.SQL_VALIDATED, AuditOutcome.OK): "Query approved",
    (AuditEventType.SQL_VALIDATED, AuditOutcome.DENIED): "Query blocked",
    (AuditEventType.SQL_EXECUTED, AuditOutcome.OK): "Query executed",
    (AuditEventType.SQL_EXECUTED, AuditOutcome.ERROR): "Query failed",
    (AuditEventType.LIMIT_EXCEEDED, AuditOutcome.DENIED): "Limit reached",
}

_LIMIT_FORMATTERS: Final[dict[str, tuple[str, Callable[[int], str]]]] = {
    "max_upload_bytes": ("Max upload size", _format_megabytes),
    "max_rows": ("Max rows", _format_count),
    "max_columns": ("Max columns", _format_count),
    "max_execution_seconds": ("Max execution time", _format_seconds),
    "sql_timeout_seconds": ("SQL timeout", _format_seconds),
    "max_result_rows": ("Max result rows", _format_count),
}


def _limit_rows(limits: LimitsConfig, names: Sequence[str]) -> tuple[tuple[str, str], ...]:
    values = limits.model_dump()
    return tuple(
        (_LIMIT_FORMATTERS[name][0], _LIMIT_FORMATTERS[name][1](values[name])) for name in names
    )


def auto_eda_inspector_sections(
    *,
    profile: DatasetProfile,
    cleaning_log: Sequence[str] = (),
    audit_events: Sequence[AuditEvent] = (),
    limits: LimitsConfig | None = None,
) -> tuple[InspectorSection, ...]:
    """Dataset, schema, cleaning, limits and real activity for the Auto-EDA tab."""
    active = LimitsConfig.from_env() if limits is None else limits
    sections = [
        InspectorSection("Dataset", fingerprint=profile.dataset_fingerprint),
        InspectorSection(
            "Schema versions",
            rows=(
                ("Profile", profile.schema_version),
                ("Analysis", ANALYSIS_SCHEMA_VERSION),
                ("Chart", CHART_SCHEMA_VERSION),
                ("Report", REPORT_SCHEMA_VERSION),
            ),
        ),
    ]
    if cleaning_log:
        sections.append(
            InspectorSection(
                "Cleaning",
                rows=tuple(
                    (f"Step {position}", line) for position, line in enumerate(cleaning_log, 1)
                ),
            )
        )
    sections.append(
        InspectorSection(
            "Limits",
            rows=_limit_rows(
                active,
                (
                    "max_upload_bytes",
                    "max_rows",
                    "max_columns",
                    "max_execution_seconds",
                ),
            ),
        )
    )
    counts = Counter(_activity_label(event) for event in audit_events)
    if counts:
        sections.append(
            InspectorSection(
                "Activity",
                rows=tuple(
                    (label, "1 time" if counts[label] == 1 else f"{counts[label]:,} times")
                    for label in sorted(counts)
                ),
            )
        )
    return tuple(sections)


def sql_inspector_sections(
    *,
    tables: Sequence[tuple[str, int]] = (),
    limits: LimitsConfig | None = None,
) -> tuple[InspectorSection, ...]:
    """The available tables and the query limits; the rail already names the database."""
    active = LimitsConfig.from_env() if limits is None else limits
    sections: list[InspectorSection] = []
    if tables:
        sections.append(
            InspectorSection(
                "Tables",
                rows=tuple(
                    (name, f"{count:,} column" if count == 1 else f"{count:,} columns")
                    for name, count in tables
                ),
            )
        )
    sections.append(
        InspectorSection(
            "Query limits",
            rows=_limit_rows(
                active,
                ("sql_timeout_seconds", "max_execution_seconds", "max_result_rows"),
            ),
        )
    )
    return tuple(sections)


def render_inspector(sections: Sequence[InspectorSection]) -> str:
    """Stack every label above its value; empty rows and sections are omitted."""
    blocks: list[str] = []
    for section in sections:
        rows = [(label, value) for label, value in section.rows if value not in (None, "")]
        if not rows and not section.fingerprint:
            continue

        items = "".join(
            f'<div class="{CLASSES["inspector_row"]}"><dt>{escape(label)}</dt>'
            f"<dd>{escape(value)}</dd></div>"
            for label, value in rows
        )
        details = ""
        if section.fingerprint:
            full = section.fingerprint
            short = full[:12]
            items = (
                f'<div class="{CLASSES["inspector_row"]}"><dt>Dataset fingerprint</dt>'
                f'<dd><span class="{CLASSES["mono"]} {CLASSES["fingerprint"]}" '
                f'title="{escape(full)}">{escape(short)}</span></dd></div>{items}'
            )
            details = (
                f'<details class="{CLASSES["computed_from"]}"><summary>Computed from</summary>'
                f"<dl><dt>Dataset fingerprint</dt><dd>{escape(full)}</dd></dl></details>"
            )

        blocks.append(
            f'<section class="{CLASSES["inspector_section"]}">'
            f'<h4 class="{CLASSES["inspector_title"]}">{escape(section.title)}</h4>'
            f'<dl class="{CLASSES["inspector_list"]}">{items}</dl>{details}</section>'
        )

    if not blocks:
        return ""
    return f'<div class="{CLASSES["inspector"]}">{"".join(blocks)}</div>'


def inspector(sections: Sequence[InspectorSection]) -> None:
    """A collapsed panel of stacked definition lists; nothing is drawn when it is empty."""
    fragment = render_inspector(sections)
    if not fragment:
        return
    with st.expander("Inspector", expanded=False):
        st.html(fragment)
