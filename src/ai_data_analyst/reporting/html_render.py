"""Render a :class:`~ai_data_analyst.reporting.Report` as one self-contained HTML file.

The page has no scripts, no external requests and no web fonts; charts are inline SVG. A
Content-Security-Policy meta tag forbids everything except inline styles and ``data:`` images,
as a second line of defence. Every piece of text goes through :func:`escape_html`, because
column names, group keys and category values come from the uploaded file.
"""

from __future__ import annotations

from typing import Final

from ..visualization import ChartSpec
from ._format import escape_html as esc
from .report import Report, ReportTable
from .svg import chart_svg

_CSP: Final = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"

_STYLE: Final = """
:root { color-scheme: light; }
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Arial, sans-serif; color: #222;
  background: #fff; margin: 0 auto; padding: 24px 20px 48px; max-width: 980px; }
h1 { font-size: 1.8em; margin: 0 0 4px; }
h2 { font-size: 1.3em; margin: 2em 0 .5em; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
h3 { font-size: 1.05em; margin: 1.4em 0 .4em; }
.meta, .caption { color: #555; font-size: .9em; }
.scroll { overflow-x: auto; margin: .4em 0 1em; }
table { border-collapse: collapse; font-size: .88em; }
th, td { border: 1px solid #ccc; padding: 3px 8px; text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { background: #f2f2f2; }
caption { text-align: left; padding-bottom: 3px; }
table.facts th { background: none; border: 0; color: #555; text-align: left; font-weight: normal;
  padding: 1px 16px 1px 0; }
table.facts td { border: 0; text-align: left; padding: 1px 0; white-space: normal; }
figure { margin: 1em 0 1.6em; break-inside: avoid; }
figcaption { font-size: .9em; color: #333; }
code { font-size: .9em; word-break: break-all; }
nav ol { margin: .3em 0; padding-left: 1.4em; }
.warn li { margin: .2em 0; }
@media print { body { max-width: none; padding: 0; } a { color: inherit; text-decoration: none; } }
"""


def _facts(facts: tuple[tuple[str, str], ...]) -> str:
    rows = "".join(f'<tr><th scope="row">{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in facts)
    return f'<div class="scroll"><table class="facts"><tbody>{rows}</tbody></table></div>'


def _table(table: ReportTable) -> str:
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in table.headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in table.rows
    )
    return (
        f'<div class="scroll"><table><caption class="caption">{esc(table.caption)}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _figure(number: int, spec: ChartSpec) -> str:
    source = (
        f"Source: step {spec.source_step + 1} ({esc(spec.operation)}), "
        f'artifact <code title="{esc(spec.artifact_digest)}">'
        f"{esc(spec.artifact_digest[:12])}</code>"
    )
    notes = "".join(f"<br>Warning: {esc(w)}" for w in spec.warnings)
    return (
        f'<figure id="figure-{number}">{chart_svg(spec)}<figcaption>'
        f"<strong>Figure {number}. {esc(spec.title)}</strong><br>{esc(spec.subtitle)}<br>"
        f"{source}{notes}</figcaption></figure>"
    )


def render_html(report: Report) -> str:
    """The report as an HTML document string."""
    prov = report.provenance
    meta = [f"Dataset fingerprint (SHA-256): <code>{esc(prov.dataset_fingerprint)}</code>"]
    if prov.source_name:
        meta.insert(0, f"Source file: {esc(prov.source_name)}")
    if prov.generated_at:
        meta.append(f"Generated: {esc(prov.generated_at)}")
    meta.append(f"{len(report.warnings)} warnings (see section 5)")

    out = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{esc(_CSP)}">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(report.title)}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{esc(report.title)}</h1>",
        '<p class="meta">' + "<br>".join(meta) + "</p>",
        '<nav aria-label="Contents"><ol>'
        '<li><a href="#overview">Dataset overview</a></li>'
        '<li><a href="#methods">Methods</a></li>'
        '<li><a href="#results">Results</a></li>'
        '<li><a href="#charts">Charts</a></li>'
        '<li><a href="#warnings">Warnings</a></li>'
        '<li><a href="#limitations">Limitations</a></li>'
        '<li><a href="#provenance">Reproducibility</a></li></ol></nav>',
        '<section id="overview"><h2>1. Dataset overview</h2>',
        _facts(report.overview_facts),
        _table(report.column_table),
        "</section>",
        '<section id="methods"><h2>2. Methods</h2>',
    ]
    if not report.methods:
        out.append("<p>No analyses were run.</p>")
    for method in report.methods:
        out.append(f'<h3 id="method-{method.step + 1}">{esc(method.title)}</h3>')
        out.append(f"<p>{esc(method.description)}</p>")
        facts = [
            ("Columns", ", ".join(method.input_columns)),
            *method.parameters,
            ("Rows in the analysed data", str(method.rows_in_dataset)),
            ("Rows contributing", str(method.rows_used)),
        ]
        out.append(_facts(tuple(facts)))
        if method.cleaning:
            out.append("<p>Cleaning applied before this step:</p><ul>")
            out.extend(f"<li>{esc(note)}</li>" for note in method.cleaning)
            out.append("</ul>")
        else:
            out.append("<p>No cleaning was applied before this step.</p>")
    out.append('</section><section id="results"><h2>3. Results</h2>')
    for result in report.results:
        out.append(f'<h3 id="step-{result.step + 1}">{esc(result.title)}</h3>')
        out.append(_facts(result.facts))
        out.extend(_table(table) for table in result.tables)
        if result.chart_indices:
            links = ", ".join(
                f'<a href="#figure-{i + 1}">Figure {i + 1}</a>' for i in result.chart_indices
            )
            out.append(f'<p class="caption">Charts for this step: {links}</p>')
    out.append('</section><section id="charts"><h2>4. Charts</h2>')
    if not report.charts:
        out.append("<p>No charts were produced for these analyses.</p>")
    out.extend(_figure(number, spec) for number, spec in enumerate(report.charts, start=1))
    out.append('</section><section id="warnings"><h2>5. Warnings</h2>')
    if report.warnings:
        out.append('<ul class="warn">')
        out.extend(
            f"<li><strong>{esc(w.scope)}:</strong> {esc(w.message)}</li>" for w in report.warnings
        )
        out.append("</ul>")
    else:
        out.append("<p>No warnings.</p>")
    out.append('</section><section id="limitations"><h2>6. Limitations</h2><ul>')
    out.extend(f"<li>{esc(note)}</li>" for note in report.limitations)
    out.append("</ul></section>")
    libs = ", ".join(f"{name} {version}" for name, version in prov.library_versions.items())
    out.append(
        '<section id="provenance"><h2>7. Reproducibility</h2>'
        + _facts(
            (
                ("Dataset fingerprint", prov.dataset_fingerprint),
                ("Report schema", prov.report_schema_version),
                ("Profile schema", prov.profile_schema_version),
                ("Analysis schema", prov.analysis_schema_version),
                ("Chart schema", prov.chart_schema_version),
                ("Libraries", libs or "none (no analyses were run)"),
            )
        )
        + "<p>Re-running the same plan on the same file with the same library versions "
        "gives the same numbers.</p></section></body></html>"
    )
    return "\n".join(out)
