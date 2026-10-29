# Architecture and Module Boundaries

## Dependency direction

The UI calls application services. Application services orchestrate domain modules. Domain modules do not import Streamlit. Model adapters return typed proposals; deterministic validators decide whether proposals may execute.

## Modules

- `ingestion/`: CSV validation and parsing.
- `profiling/`: deterministic schema and quality profile.
- `analysis/`: allow-listed Pandas/scikit-learn operations.
- `visualization/`: chart specifications and rendering.
- `chat/`: question routing and grounded answer composition.
- `sql_agent/`: schema retrieval, SQL generation interface, validation, execution, and result explanation.
- `security/`: common limits, policy types, and audit events.
- `evaluation/`: benchmark fixtures, scoring, and report generation.
- `reporting/`: reproducible report assembly.
- `ui/`: Streamlit pages and widgets only.

## Key interfaces (planned)

- `DatasetProfile`: versioned structured profile of a dataset.
- `AnalysisPlan`: typed list of allow-listed operations and validated parameters.
- `AnalysisArtifact`: operation, input columns, parameters, result reference, warnings, and provenance.
- `SQLCandidate`: SQL text plus dialect and parameter values.
- `SQLValidationResult`: allow/deny, normalized query metadata, and reasons.
- `EvaluationResult`: metric name, score/value, sample count, and benchmark version.

## Trust boundaries

Treat uploaded files, natural-language questions, model output, schema comments, and database content as untrusted input. Do not treat data or model text as instructions. Validate every boundary with code.

## Shared contract: `DatasetProfile`

Defined in `src/ai_data_analyst/models.py` as a frozen Pydantic model with `schema_version`. Profiling produces it; analysis, chat, reporting and evaluation consume it. Rules:

- `extra="forbid"` so unknown fields fail loudly.
- Any breaking change bumps `PROFILE_SCHEMA_VERSION` and regenerates the expected fixture values.
- Statistical conventions are fixed: sample standard deviation (ddof=1), linear-interpolation quartiles, IQR outlier rule with factor 1.5.

## Module independence

`ingestion/profiling/analysis/visualization/reporting/chat` (M1) and `sql_agent` (M2) must not import each other. Both may import `models`, `security` and `evaluation`.

## M1 analysis contracts: `AnalysisPlan` and `AnalysisArtifact`

Currently defined in `analysis/plan.py` and `analysis/artifact.py` (schema version `1.0`) and
exported from `ai_data_analyst.analysis`. They move to `models.py` once the contracts owner
agrees, since `chat/`, `reporting/` and `evaluation/` consume them.

- `AnalysisPlan`: 1 to 20 steps. Each step is one of the allow-listed operations, selected by
  the `operation` field: `summary_stats`, `grouped_aggregation`, `correlation`, `distribution`,
  `outlier_summary`, `clustering`, `pca`. Parameters are typed and bounded; unknown fields are
  rejected, and no field carries an expression or code.
- `validate_plan(plan, profile)` checks columns exist and their inferred types suit the
  operation. `execute_plan` validates the whole plan first, so nothing runs on a bad plan, and
  checks `max_execution_seconds` between steps (a single step is not interrupted).
- `AnalysisArtifact`: `operation`, `input_columns`, `parameters`, `result` (strict JSON, `None`
  for undefined values), `warnings`, and `provenance` (dataset fingerprint, rows in the frame,
  rows used, library versions, and the cleaning log).
- `typed_frame(ingested, profile)` builds the typed analysis view. It does not clean or impute.

### Clustering and PCA

- `clustering`: k-means (`k` 2 to 10, 2 to 10 numeric columns). `standardize` defaults to
  `true`; `random_state` is a bounded integer (default 0) that is always recorded in the
  artifact's `parameters`. Clusters are numbered largest first (ties broken by centroid), and
  centroids are reported in the original units. The result includes inertia, iterations and a
  silhouette score (estimated on a fixed-seed sample of 2,000 rows for larger inputs; absent
  when it is undefined).
- `pca`: 2 to 20 numeric columns, 1 to 10 components (never more than the columns). Reports
  explained variance, its ratio and cumulative ratio, and loadings. The sign of each component
  is fixed so its largest-magnitude loading is positive.
- Both use only rows with no missing value in the selected columns and warn how many rows were
  excluded. They fail closed (`OperationInputError`, carrying the step index) when the data
  cannot support the request: fewer complete or distinct rows than `k`, fewer rows than
  components, or only constant columns. A constant column among others produces a warning. With
  `standardize=false`, columns on very different scales produce a warning.
- Reproducibility: fixed seeds, `svd_solver="full"`, and BLAS/OpenMP threads pinned to one while
  the model runs, so a result does not depend on the machine's core count.
- Resource limits: the plan types bound `k`, the column count and the component count; the row
  count is bounded by the ingestion limit; `max_execution_seconds` is checked between steps.

### Cleaning working view (EDA-04)

`analysis/cleaning.py`. A `CleaningPlan` is a list of up to 10 allow-listed steps
(`drop_duplicates`, `drop_missing_rows`, `impute` with `mean` or `median` on a numeric column).
`apply_cleaning` / `cleaned_view` work on a copy of the typed frame, so neither the ingested
strings nor the typed frame change, and return a `CleanedView` with the cleaned frame, a
human-readable log and the row counts before and after. A step that cannot work (nothing to
impute, or every row removed) raises `CleaningError`. Run a plan on a view with
`execute_plan_on_view` (it rejects a view built for another dataset, by fingerprint); each artifact
then records the log in `provenance.cleaning`. Without a
cleaning plan, `execute_plan` behaves as before and records an empty log.

### Chart specifications (EDA-08)

`visualization/charts.py`. `charts_for_artifacts(artifacts)` returns `ChartSpec` objects: plain,
JSON-serialisable data (kind, title, subtitle, axis labels, labels, values or matrix) with no
rendering code. Histograms, bar charts (categories, grouped aggregations, outlier fractions,
cluster sizes, PCA variance) and correlation heatmaps are supported; `summary_stats` is a table
and gets no chart. Each spec records its artifact's step index and SHA-256 digest, the source
columns, the cleaning log and the artifact's warnings. `validate_chart(spec, artifacts)` rebuilds
the charts for that artifact and requires an exact match, so an edited or mismatched spec raises
`ChartTraceError`.

### Report assembly (EDA-09)

`reporting/`. `build_report(profile, artifacts, charts=None, *, title, source_name, generated_at)`
returns a frozen `Report` (schema version `1.0`) with seven parts: dataset overview (from the
`DatasetProfile`), methods and results (one of each per artifact, in plan order), charts, warnings,
limitations and provenance. `render_html(report)` and `render_markdown(report)` turn it into files;
`chart_svg(spec)` draws a `ChartSpec`.

- **Grounding.** Every number is copied from the profile or an artifact; nothing is recomputed
  from raw data, and no model-written text is included. The wording around the numbers is fixed.
  Percentages in the overview and warnings are `count / row_count`, shown to one decimal.
- **Fail closed (`ReportError`).** An artifact whose dataset fingerprint differs from the
  profile's, one that used more rows than the dataset has, more than 20 steps, a result whose
  shape is not what its operation produces, or a supplied chart that does not pass
  `validate_chart`. When `charts` is omitted they are derived from the artifacts.
- **Warnings.** Data-quality warnings from the profile (duplicates, missing values, candidate
  outliers, constant or empty columns; at most 20 per kind, the rest summarised) come first,
  then each artifact's own warnings labelled with their step. Limitations depend on which
  operations ran and on whether cleaning was applied.
- **Deterministic.** The same inputs give the same report and byte-identical files. No timestamp
  is added unless the caller passes `generated_at`.
- **HTML.** One self-contained file: no scripts, no external requests, charts as inline SVG, and
  a Content-Security-Policy meta tag allowing only inline styles and `data:` images. All text from
  the uploaded file (column names, group keys, category values, file name) is HTML-escaped.
- **Markdown.** Charts appear as the table of values they plot, with title, source columns and
  source artifact. Text from the file is backslash-escaped, so it cannot become formatting, a
  link or raw HTML, and each table row stays on one line.
- **Heatmap cells** show values rounded to two decimals so they fit; tooltips and the
  correlation tables hold the exact values.

### Grounded chat (EDA-10)

`chat/`. `answer_question(question, profile, *, artifacts=(), data=None, proposer=None)` returns a
frozen `ChatAnswer` (`status`, `text`, `evidence`, `assumptions`, `warnings`, and the new
`artifact` when one was computed).

- **Routing.** `route_question` uses fixed rules only: the question is matched against column
  names and a closed vocabulary, and is never executed or echoed. It yields a `Lookup` (answer
  from the `DatasetProfile`: counts, duplicates, missing values, per-column statistics, outlier
  counts, column list), a `Propose` (one typed, allow-listed analysis step: summary statistics,
  grouped aggregation, correlation, distribution, clustering, PCA) or `Unsupported` with the
  list of supported questions. Defaults the router fills in (k=3, two components, the mean, all
  numeric columns) are listed in `assumptions`.
- **Answering.** A profile lookup needs nothing computed (`status="profile"`). A proposed step
  is validated against the profile; if an artifact with the same parameters (and the same
  cleaning log) exists it is reused (`"artifact"`), otherwise the step is run on `data`, the typed
  frame or a `CleanedView`, and returned (`"computed"`). With no data, or when the data cannot
  support the operation, the answer says so (`"unsupported"`).
- **Grounding.** Text is built only through a writer that formats a value and records an
  `Evidence` entry (profile field or artifact result path) in one step. A final check,
  `ungrounded_numbers`, fails closed: an answer containing a number without evidence is replaced
  by an `unsupported` answer. No model-written text is shown.
- **Model use.** Optional and narrow: a `StepProposer` may return a typed `AnalysisStep` for a
  question the rules do not cover. The step goes through the same validation as any other and
  the adapter's text is never shown. No provider is imported by `chat/`.
- **Fail closed (`ChatError`).** An artifact or cleaned view from another dataset, a frame whose
  row count differs from the profile, or a question over 2,000 characters.
- Text from the uploaded file (column names, group keys) appears verbatim in answers; the UI
  must render it as text, not markup.

### Not yet implemented

Row filters are deliberately absent until the filter contract is agreed with the contracts
owner. The Streamlit download button for the report belongs to the UI integration (`ui/`), which
calls `build_report` and the two renderers.
