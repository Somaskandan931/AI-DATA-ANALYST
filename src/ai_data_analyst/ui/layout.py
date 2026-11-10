"""Shared layout shell, editorial headers, evidence rendering and the inspector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ..analysis import ANALYSIS_SCHEMA_VERSION
from ..models import DatasetProfile
from ..reporting import REPORT_SCHEMA_VERSION
from ..security import AuditEvent, LimitsConfig
from ..visualization import CHART_SCHEMA_VERSION
from . import formatting
from .evidence import EvidenceSource, EvidenceView, render_evidence_view, source_chip
from .theme.html import escape_text
from .theme.tokens import CLASSES

_SHELL_MARKER: Final = '<span class="fn-shell-marker" aria-hidden="true"></span>'

_LIMIT_LABELS: Final[dict[str, str]] = {
    "max_upload_bytes": "Max upload bytes",
    "max_rows": "Max rows",
    "max_columns": "Max columns",
    "max_execution_seconds": "Max execution seconds",
    "sql_timeout_seconds": "SQL timeout seconds",
    "max_result_rows": "Max result rows",
}


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


def inspector(
    *,
    profile: DatasetProfile | None,
    cleaning_log: Sequence[str] = (),
    audit_events: Sequence[AuditEvent] = (),
    limits: LimitsConfig | None = None,
    m1_available: bool = True,
) -> None:
    """Collapsed provenance panel shared by both workspaces."""
    active = LimitsConfig.from_env() if limits is None else limits
    with st.expander("Inspector", expanded=False):
        fingerprint = profile.dataset_fingerprint if profile is not None else "Not available"
        st.text(f"Dataset fingerprint: {fingerprint}")

        st.text("Schema versions")
        versions = pd.DataFrame(
            {
                "Schema": ["Profile", "Analysis", "Chart", "Report"],
                "Version": [
                    profile.schema_version if profile is not None else "Not available",
                    ANALYSIS_SCHEMA_VERSION,
                    CHART_SCHEMA_VERSION,
                    REPORT_SCHEMA_VERSION,
                ],
            }
        )
        st.dataframe(versions, hide_index=True)

        st.text("Cleaning log")
        if cleaning_log:
            for line in cleaning_log:
                st.text(f"- {line}")
        else:
            st.text("- No cleaning applied.")

        st.text("Active limits")
        values = active.model_dump()
        st.dataframe(
            formatting.columns_frame(
                {
                    "Limit": [_LIMIT_LABELS[name] for name in values],
                    "Value": list(values.values()),
                }
            ),
            hide_index=True,
            width="stretch",
        )

        st.text("M1 audit events")
        if not m1_available:
            st.text("- Not available in this workspace.")
        else:
            counts = Counter(event.event_type.value for event in audit_events)
            if counts:
                for name in sorted(counts):
                    st.text(f"- {name}: {counts[name]}")
            else:
                st.text("- No events recorded.")

        st.text("SQL audit events: Not available")
        st.caption("M2 does not emit audit events yet, so this section stays empty.")
