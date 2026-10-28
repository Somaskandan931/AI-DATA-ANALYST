"""Reproducible report assembly (EDA-09)."""

from ai_data_analyst.reporting.html_render import render_html
from ai_data_analyst.reporting.markdown_render import render_markdown
from ai_data_analyst.reporting.report import (
    DEFAULT_TITLE,
    REPORT_SCHEMA_VERSION,
    Report,
    ReportError,
    ReportMethod,
    ReportProvenance,
    ReportResult,
    ReportTable,
    ReportWarning,
    build_report,
)
from ai_data_analyst.reporting.svg import chart_svg

__all__ = [
    "DEFAULT_TITLE",
    "REPORT_SCHEMA_VERSION",
    "Report",
    "ReportError",
    "ReportMethod",
    "ReportProvenance",
    "ReportResult",
    "ReportTable",
    "ReportWarning",
    "build_report",
    "chart_svg",
    "render_html",
    "render_markdown",
]
