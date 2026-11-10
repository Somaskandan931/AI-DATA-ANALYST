"""Shared layout shell, editorial headers, evidence rendering and the inspector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ..analysis import ANALYSIS_SCHEMA_VERSION
from ..models import DatasetProfile
from ..reporting import REPORT_SCHEMA_VERSION
from ..security import AuditEvent, LimitsConfig
from ..visualization import CHART_SCHEMA_VERSION
from .evidence import EvidenceView, render_evidence_view
from .theme.html import escape_text

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


def section_label(text: str) -> None:
    """A small mono label above a block of content."""
    st.html(f'<p class="fn-section-label">{escape_text(text)}</p>')


def page_header(section: str, title: str, purpose: str) -> None:
    """The editorial header each inner tab starts with."""
    st.html(
        '<header class="fn-page-heading">'
        f'<p class="fn-section-label">{escape_text(section)}</p>'
        f'<h2 class="fn-page-title">{escape_text(title)}</h2>'
        f'<p class="fn-page-purpose">{escape_text(purpose)}</p>'
        "</header>"
    )


def evidence_view(view: EvidenceView, *, fresh: bool = False) -> None:
    """Render a group of evidence cards as one escaped fragment."""
    st.html(render_evidence_view(view, fresh=fresh))


def computed_from(rows: Sequence[tuple[str, str]], *, label: str = "Computed from") -> None:
    """A native details block for provenance; every field is escaped."""
    body = "".join(
        f"<dt>{escape_text(name)}</dt><dd>{escape_text(value)}</dd>" for name, value in rows
    )
    st.html(
        f'<details class="fn-computed-from"><summary>{escape_text(label)}</summary>'
        f"<dl>{body}</dl></details>"
    )


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
            pd.DataFrame(
                {
                    "Limit": [_LIMIT_LABELS[name] for name in values],
                    "Value": list(values.values()),
                }
            ),
            hide_index=True,
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
