"""Render a :class:`~ai_data_analyst.reporting.Report` as Markdown.

Markdown cannot draw charts, so each chart appears as the table of numbers it plots, with its
title, source columns and source artifact. Text that came from the uploaded file is escaped so
it cannot become formatting, a link or raw HTML, and cell text is kept on one line.
"""

from __future__ import annotations

from ..visualization import ChartSpec
from ._format import escape_markdown as esc
from ._format import fmt_value
from .report import Report, ReportTable


def _facts(facts: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"- **{esc(k)}:** {esc(v)}" for k, v in facts]


def _table(table: ReportTable) -> list[str]:
    lines = [f"*{esc(table.caption)}*", ""]
    lines.append("| " + " | ".join(esc(h) for h in table.headers) + " |")
    lines.append("|" + "|".join(" --- " for _ in table.headers) + "|")
    lines.extend("| " + " | ".join(esc(cell) for cell in row) + " |" for row in table.rows)
    return lines


def _chart_table(spec: ChartSpec) -> ReportTable:
    if spec.kind == "heatmap":
        matrix = spec.matrix or ()
        rows = tuple(
            (name, *(fmt_value(v) for v in line))
            for name, line in zip(spec.labels, matrix, strict=True)
        )
        return ReportTable(
            caption=f"Plotted values ({spec.y_label} by {spec.x_label})",
            headers=("", *spec.labels),
            rows=rows,
        )
    values = spec.values or ()
    rows = tuple((label, fmt_value(v)) for label, v in zip(spec.labels, values, strict=True))
    return ReportTable(
        caption=f"Plotted values (x: {spec.x_label}; y: {spec.y_label})",
        headers=(spec.x_label, spec.y_label),
        rows=rows,
    )


def render_markdown(report: Report) -> str:
    """The report as a Markdown document string."""
    prov = report.provenance
    out: list[str] = [f"# {esc(report.title)}", ""]
    if prov.source_name:
        out.append(f"Source file: {esc(prov.source_name)}  ")
    out.append(f"Dataset fingerprint (SHA-256): `{prov.dataset_fingerprint}`  ")
    if prov.generated_at:
        out.append(f"Generated: {esc(prov.generated_at)}  ")
    out.append(f"{len(report.warnings)} warnings (see section 5)")
    out += ["", "## 1. Dataset overview", "", *_facts(report.overview_facts), ""]
    out += [*_table(report.column_table), "", "## 2. Methods", ""]
    if not report.methods:
        out += ["No analyses were run.", ""]
    for method in report.methods:
        out += [f"### {esc(method.title)}", "", esc(method.description), ""]
        facts = (
            ("Columns", ", ".join(method.input_columns)),
            *method.parameters,
            ("Rows in the analysed data", str(method.rows_in_dataset)),
            ("Rows contributing", str(method.rows_used)),
        )
        out += [*_facts(facts), ""]
        if method.cleaning:
            out += ["Cleaning applied before this step:", ""]
            out += [f"- {esc(note)}" for note in method.cleaning] + [""]
        else:
            out += ["No cleaning was applied before this step.", ""]
    out += ["## 3. Results", ""]
    for result in report.results:
        out += [f"### {esc(result.title)}", "", *_facts(result.facts), ""]
        for table in result.tables:
            out += [*_table(table), ""]
        if result.chart_indices:
            figures = ", ".join(f"Figure {i + 1}" for i in result.chart_indices)
            out += [f"Charts for this step: {figures}", ""]
    out += ["## 4. Charts", ""]
    if not report.charts:
        out += ["No charts were produced for these analyses.", ""]
    for number, spec in enumerate(report.charts, start=1):
        out += [f"### Figure {number}. {esc(spec.title)}", "", esc(spec.subtitle), ""]
        out += [
            f"Source: step {spec.source_step + 1} ({esc(spec.operation)}), "
            f"artifact `{spec.artifact_digest[:12]}`",
            "",
        ]
        out += [f"Warning: {esc(w)}  " for w in spec.warnings]
        out += [*_table(_chart_table(spec)), ""]
    out += ["## 5. Warnings", ""]
    if report.warnings:
        out += [f"- **{esc(w.scope)}:** {esc(w.message)}" for w in report.warnings]
    else:
        out.append("No warnings.")
    out += ["", "## 6. Limitations", ""]
    out += [f"- {esc(note)}" for note in report.limitations]
    libs = ", ".join(f"{name} {version}" for name, version in prov.library_versions.items())
    out += ["", "## 7. Reproducibility", ""]
    out += _facts(
        (
            ("Report schema", prov.report_schema_version),
            ("Profile schema", prov.profile_schema_version),
            ("Analysis schema", prov.analysis_schema_version),
            ("Chart schema", prov.chart_schema_version),
            ("Libraries", libs or "none (no analyses were run)"),
        )
    )
    out += [
        "",
        "Re-running the same plan on the same file with the same library versions gives the "
        "same numbers.",
        "",
    ]
    return "\n".join(out)
