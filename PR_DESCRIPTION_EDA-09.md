# EDA-09: downloadable report (HTML and Markdown)

**Branch:** `m1/report`, stacked on `m1/analysis-core` (needs its chart specs and artifacts)
**Requirement ID:** EDA-09
**Owner:** Somaskandan (M1) | **Reviewer:** Nishi or Prathin

## What this adds

| Area | Change |
| --- | --- |
| `reporting/report.py` (new) | `Report` model (schema `1.0`) and `build_report(profile, artifacts, charts=None, *, title, source_name, generated_at)`: overview, methods, results, charts, warnings, limitations, provenance |
| `reporting/html_render.py` (new) | `render_html`: one self-contained file, inline SVG charts, no scripts, no external requests, Content-Security-Policy meta tag |
| `reporting/markdown_render.py` (new) | `render_markdown`: charts as the table of values they plot |
| `reporting/svg.py` (new) | `chart_svg(spec)`: bar, histogram and heatmap from a `ChartSpec` |
| `reporting/_format.py` (new) | number formatting and HTML/Markdown escaping |
| `docs/ARCHITECTURE.md`, `README.md` | updated to match |

## How the report stays grounded

- Every number is copied from the `DatasetProfile` or an `AnalysisArtifact`. Nothing is recomputed from raw data and no model-written text is included; the wording around the numbers is fixed.
- `build_report` fails closed (`ReportError`) on: an artifact from a different dataset (fingerprint), an artifact that used more rows than the dataset has, more than 20 steps, a result whose shape does not match its operation, and a supplied chart that fails `validate_chart`.
- Deterministic: same inputs give the same report and byte-identical files. No timestamp unless `generated_at` is passed.
- Warnings: profile-derived data-quality warnings first (capped at 20 per kind), then each artifact's warnings labelled with their step. Limitations depend on the operations that ran and on whether cleaning was applied.
- Text from the uploaded file (column names, group keys, category values, file name) is escaped in both formats.

## Not in this PR (on purpose)

- The Streamlit download button. That is UI integration (`ui/`); it only needs `build_report` plus the two renderers.
- PDF output, row filters (still waiting on the filter contract), grounded chat (EDA-10).
- No change to `AnalysisPlan`, `AnalysisArtifact`, `DatasetProfile` or any existing behaviour.

## Results

Run on a clean copy of the `m1/analysis-core` tree with the patch applied (Python 3.12, pandas 3.0.2, numpy 2.4.4, scikit-learn 1.8.0):

- `pytest`: **620 passed** (561 before; 59 new in `tests/unit/test_reporting.py`).
- `ruff check`, `ruff format --check`, `mypy` (strict, 33 source files): clean.
- `pytest -W error` on the reporting tests: no warnings.

How it is checked:

- Overview rows, columns, duplicates, fingerprint and per-column missing, distinct, min, max, mean and outlier counts equal the independently computed `data/expected/` profile. The summary-statistics table repeats that profile's mean, median and std.
- Pair counts in the correlation step are recomputed from the raw, untyped cells. Histogram bins sum to the non-missing count; cluster sizes sum to the rows clustered; PCA ratios sum to 1.
- Hostile column names and values (`<script>`, `<img onerror>`, `[x](javascript:...)`, pipes, quotes, a newline in a header) give HTML with no script, image or `on*` attribute and only `#` links, SVGs that parse as XML, and Markdown with no unescaped `<` that renders to inert HTML.
- Mutation check: removing HTML escaping, removing Markdown escaping, and removing the fingerprint check each make tests fail.

## Review notes

- Library versions in the report come from the artifacts' provenance; if steps disagree, a warning says so.
- The method descriptions are fixed text. If an operation's algorithm changes (for example the clustering algorithm), the matching sentence in `report.py` must change with it.
- Heatmap cells show values rounded to two decimals so they fit; tooltips and the correlation tables hold the exact values.
- The HTML was looked at in a rendering engine (wkhtmltoimage) only. It uses a plain table for facts rather than CSS grid. Please open `sample_report.html` in your browser once.
- No benchmark or latency claim is made.

## Checklist

- [x] Unit tests for new behaviour, including rejection and failure paths
- [x] `ruff check`, `ruff format --check`, `mypy`, `pytest` pass
- [x] No credentials, raw sensitive data or generated databases committed
- [x] Docs updated
- [ ] Review feedback addressed
