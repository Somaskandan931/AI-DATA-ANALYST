"""Report assembly (EDA-09): dataset overview, methods, results, charts, warnings, limitations.

A :class:`Report` is built only from a :class:`~ai_data_analyst.models.DatasetProfile`, executed
:class:`~ai_data_analyst.analysis.AnalysisArtifact` objects and the chart specs derived from
them. Every number it carries is copied from one of those; the text around the numbers is
fixed wording chosen by this module. No model output is involved, and nothing is computed
from the raw data here.

The builder fails closed (:class:`ReportError`) when its inputs do not belong together: an
artifact from another dataset, a chart that does not trace to its artifact, or a result whose
shape is not what its operation produces. A report is deterministic: the same inputs give
the same report, and no timestamp is added unless the caller supplies one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..analysis import ANALYSIS_SCHEMA_VERSION, AnalysisArtifact, OperationName
from ..analysis.plan import MAX_STEPS
from ..models import PROFILE_SCHEMA_VERSION, DatasetProfile
from ..visualization import (
    CHART_SCHEMA_VERSION,
    ChartSpec,
    ChartTraceError,
    charts_for_artifacts,
    validate_chart,
)
from ..visualization.charts import MAX_CATEGORIES
from ._format import MISSING, fmt_value

REPORT_SCHEMA_VERSION: Final = "1.0"
DEFAULT_TITLE: Final = "Auto-EDA report"
MAX_TITLE_LENGTH: Final = 200
MAX_SOURCE_NAME_LENGTH: Final = 255
MAX_GENERATED_AT_LENGTH: Final = 64
MAX_PROFILE_WARNINGS: Final = 20  # per kind; the rest are summarised in one line

_TITLES: Final[dict[OperationName, str]] = {
    "summary_stats": "Summary statistics",
    "grouped_aggregation": "Grouped aggregation",
    "correlation": "Correlation",
    "distribution": "Distribution",
    "outlier_summary": "Outlier summary",
    "clustering": "K-means clustering",
    "pca": "Principal component analysis",
}


class ReportError(ValueError):
    """The report cannot be built from the given inputs."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ReportTable(_Frozen):
    """A table of already-formatted cells."""

    caption: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @model_validator(mode="after")
    def _rows_match_headers(self) -> Self:
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("every row must have one cell per header")
        return self


class ReportMethod(_Frozen):
    """How one analysis step was computed."""

    step: int = Field(ge=0)
    operation: OperationName
    title: str
    description: str
    parameters: tuple[tuple[str, str], ...]
    input_columns: tuple[str, ...]
    cleaning: tuple[str, ...]
    rows_in_dataset: int = Field(ge=0, description="Rows in the frame the step ran on")
    rows_used: int = Field(ge=0, description="Rows that contributed to the result")


class ReportResult(_Frozen):
    """The numbers one analysis step produced, plus the charts drawn from them."""

    step: int = Field(ge=0)
    operation: OperationName
    title: str
    facts: tuple[tuple[str, str], ...]
    tables: tuple[ReportTable, ...]
    chart_indices: tuple[int, ...] = Field(description="Positions in Report.charts")


class ReportWarning(_Frozen):
    scope: str
    message: str


class ReportProvenance(_Frozen):
    """What the report was built from, for reproducibility (APP-04)."""

    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_name: str | None
    report_schema_version: str
    profile_schema_version: str
    analysis_schema_version: str
    chart_schema_version: str
    library_versions: dict[str, str]
    generated_at: str | None


class Report(_Frozen):
    schema_version: str = REPORT_SCHEMA_VERSION
    title: str
    provenance: ReportProvenance
    overview_facts: tuple[tuple[str, str], ...]
    column_table: ReportTable
    methods: tuple[ReportMethod, ...]
    results: tuple[ReportResult, ...]
    charts: tuple[ChartSpec, ...]
    warnings: tuple[ReportWarning, ...]
    limitations: tuple[str, ...]


# --- reading artifact results strictly ----------------------------------------------------


def _obj(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportError(f"{where} is malformed: expected an object")
    return value


def _seq(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReportError(f"{where} is malformed: expected a list")
    return value


def _names(value: object, where: str) -> list[str]:
    return [str(item) for item in _seq(value, where)]


def _cell(value: object) -> str:
    return fmt_value(value)


# --- per-operation tables ----------------------------------------------------------------


def _summary_stats(
    result: dict[str, Any], where: str
) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    keys = ("count", "missing", "mean", "std", "min", "q1", "median", "q3", "max")
    rows = []
    for name, entry in _obj(result.get("columns"), f"{where}.columns").items():
        stats = _obj(entry, f"{where}.columns[{name!r}]")
        rows.append((name, *(_cell(stats.get(key)) for key in keys)))
    table = ReportTable(
        caption="Statistics over non-missing values",
        headers=("Column", "Count", "Missing", "Mean", "Std", "Min", "Q1", "Median", "Q3", "Max"),
        rows=tuple(rows),
    )
    return [], [table]


def _grouped(result: dict[str, Any], where: str) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    keys = _names(result.get("group_by"), f"{where}.group_by")
    value = str(result.get("value_column"))
    aggregations = _names(result.get("aggregations"), f"{where}.aggregations")
    groups = _seq(result.get("groups"), f"{where}.groups")
    rows = []
    for position, raw in enumerate(groups):
        group = _obj(raw, f"{where}.groups[{position}]")
        labels = _obj(group.get("keys"), f"{where}.groups[{position}].keys")
        rows.append(
            (
                *(_cell(labels.get(key)) for key in keys),
                *(_cell(group.get(agg)) for agg in aggregations),
            )
        )
    facts = [
        ("Total groups", _cell(result.get("total_groups"))),
        ("Groups shown", str(len(groups))),
    ]
    table = ReportTable(
        caption=f"Aggregations of {value}, sorted by group key",
        headers=(*keys, *(f"{agg} of {value}" for agg in aggregations)),
        rows=tuple(rows),
    )
    return facts, [table]


def _square(names: list[str], raw: object, where: str, caption: str) -> ReportTable:
    lines = _seq(raw, where)
    if len(lines) != len(names):
        raise ReportError(f"{where} is malformed: expected one row per column")
    rows = []
    for name, line in zip(names, lines, strict=True):
        cells = _seq(line, where)
        if len(cells) != len(names):
            raise ReportError(f"{where} is malformed: expected one cell per column")
        rows.append((name, *(_cell(cell) for cell in cells)))
    return ReportTable(caption=caption, headers=("", *names), rows=tuple(rows))


def _correlation(
    result: dict[str, Any], where: str
) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    names = _names(result.get("columns"), f"{where}.columns")
    method = str(result.get("method")).capitalize()
    tables = [
        _square(names, result.get("matrix"), f"{where}.matrix", f"{method} correlation"),
        _square(
            names, result.get("pair_counts"), f"{where}.pair_counts", "Rows where both values exist"
        ),
    ]
    return [("Method", method)], tables


def _distribution(
    result: dict[str, Any], where: str
) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    column = str(result.get("column"))
    facts = [("Column", column), ("Missing values excluded", _cell(result.get("missing")))]
    if result.get("kind") == "histogram":
        edges = _seq(result.get("bin_edges"), f"{where}.bin_edges")
        counts = _seq(result.get("counts"), f"{where}.counts")
        if len(edges) != len(counts) + 1:
            raise ReportError(f"{where} is malformed: a histogram needs one more edge than bins")
        rows = tuple(
            (f"{_cell(edges[i])} to {_cell(edges[i + 1])}", _cell(count))
            for i, count in enumerate(counts)
        )
        caption = "Equal-width bins; the last bin includes its upper edge"
        return facts, [ReportTable(caption=caption, headers=("Bin", "Rows"), rows=rows)]
    entries = [_obj(v, f"{where}.values") for v in _seq(result.get("values"), f"{where}.values")]
    facts.append(("Distinct values", _cell(result.get("distinct"))))
    rows = tuple((_cell(e.get("value")), _cell(e.get("count"))) for e in entries)
    caption = "Most frequent values"
    return facts, [ReportTable(caption=caption, headers=(column, "Rows"), rows=rows)]


def _outliers(
    result: dict[str, Any], where: str
) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    keys = (
        "count",
        "q1",
        "q3",
        "lower_bound",
        "upper_bound",
        "below_lower",
        "above_upper",
        "outlier_count",
        "outlier_fraction",
    )
    rows = []
    for name, entry in _obj(result.get("columns"), f"{where}.columns").items():
        stats = _obj(entry, f"{where}.columns[{name!r}]")
        rows.append((name, *(_cell(stats.get(key)) for key in keys)))
    table = ReportTable(
        caption="Candidate outliers by the IQR rule (nothing is removed)",
        headers=(
            "Column",
            "Count",
            "Q1",
            "Q3",
            "Lower bound",
            "Upper bound",
            "Below",
            "Above",
            "Outliers",
            "Fraction",
        ),
        rows=tuple(rows),
    )
    return [("IQR factor", _cell(result.get("iqr_factor")))], [table]


def _clustering(
    result: dict[str, Any], where: str
) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    columns = _names(result.get("columns"), f"{where}.columns")
    clusters = [
        _obj(c, f"{where}.clusters") for c in _seq(result.get("clusters"), f"{where}.clusters")
    ]
    rows = []
    for cluster in clusters:
        centroid = _obj(cluster.get("centroid"), f"{where}.clusters.centroid")
        rows.append(
            (
                _cell(cluster.get("cluster")),
                _cell(cluster.get("size")),
                _cell(cluster.get("fraction")),
                *(_cell(centroid.get(name)) for name in columns),
            )
        )
    facts = [
        ("Clusters (k)", _cell(result.get("k"))),
        ("Rows clustered", _cell(result.get("rows_clustered"))),
        ("Columns standardized", _cell(result.get("standardized"))),
        ("Random seed", _cell(result.get("random_state"))),
        (f"Inertia ({result.get('inertia_space')} units)", _cell(result.get("inertia"))),
        ("Iterations", _cell(result.get("iterations"))),
        ("Silhouette", _cell(result.get("silhouette"))),
    ]
    table = ReportTable(
        caption="Clusters, largest first; centroids are column means in original units",
        headers=("Cluster", "Size", "Fraction", *(f"Mean of {name}" for name in columns)),
        rows=tuple(rows),
    )
    return facts, [table]


def _pca(result: dict[str, Any], where: str) -> tuple[list[tuple[str, str]], list[ReportTable]]:
    columns = _names(result.get("columns"), f"{where}.columns")
    components = [
        _obj(c, f"{where}.components")
        for c in _seq(result.get("components"), f"{where}.components")
    ]
    variance_rows = tuple(
        (
            _cell(c.get("component")),
            _cell(c.get("explained_variance")),
            _cell(c.get("explained_variance_ratio")),
            _cell(c.get("cumulative_ratio")),
        )
        for c in components
    )
    loadings = [_obj(c.get("loadings"), f"{where}.components.loadings") for c in components]
    loading_rows = tuple(
        (name, *(_cell(entry.get(name)) for entry in loadings)) for name in columns
    )
    facts = [
        ("Components", _cell(result.get("n_components"))),
        ("Rows used", _cell(result.get("rows_used"))),
        ("Columns standardized", _cell(result.get("standardized"))),
        ("Total variance", _cell(result.get("total_variance"))),
    ]
    tables = [
        ReportTable(
            caption="Variance explained",
            headers=("Component", "Explained variance", "Ratio", "Cumulative ratio"),
            rows=variance_rows,
        ),
        ReportTable(
            caption="Loadings (weight of each column in each component)",
            headers=("Column", *(_cell(c.get("component")) for c in components)),
            rows=loading_rows,
        ),
    ]
    return facts, tables


_Builder = Callable[[dict[str, Any], str], tuple[list[tuple[str, str]], list[ReportTable]]]

_BUILDERS: Final[dict[OperationName, _Builder]] = {
    "summary_stats": _summary_stats,
    "grouped_aggregation": _grouped,
    "correlation": _correlation,
    "distribution": _distribution,
    "outlier_summary": _outliers,
    "clustering": _clustering,
    "pca": _pca,
}


# --- methods ------------------------------------------------------------------------------


def _description(artifact: AnalysisArtifact, where: str) -> str:
    match artifact.operation:
        case "summary_stats":
            return (
                "For each selected numeric column: count, missing count, mean, sample standard "
                "deviation (ddof=1), minimum, quartiles (linear interpolation) and maximum, "
                "computed over the non-missing values."
            )
        case "grouped_aggregation":
            return (
                "Rows are grouped by the key columns (rows with a missing key are excluded) and "
                "the chosen aggregations of the value column are computed for each group."
            )
        case "correlation":
            return (
                "Pairwise correlation (Pearson or Spearman, as set in the parameters) between the "
                "selected numeric columns; each pair uses the rows where both values exist."
            )
        case "distribution":
            if artifact.result.get("kind") == "histogram":
                return (
                    "Histogram of a numeric column with equal-width bins from minimum to maximum."
                )
            return "Counts of the most frequent values of a non-numeric column."
        case "outlier_summary":
            return (
                "Values outside [Q1 - f x IQR, Q3 + f x IQR] are counted as candidate outliers, "
                "with f set in the parameters and quartiles by linear interpolation. "
                "Nothing is removed."
            )
        case "clustering":
            return (
                "k-means clustering (Lloyd's algorithm, scikit-learn) of the rows with no missing "
                "value in the selected columns. Columns are standardized first unless disabled; "
                "clusters are numbered largest first and centroids are reported in original units."
            )
        case "pca":
            return (
                "Principal component analysis (scikit-learn, full SVD) of the rows with no "
                "missing value in the selected columns. Columns are standardized first unless "
                "disabled. The sign of each component is fixed so that its largest-magnitude "
                "loading is positive."
            )
    raise ReportError(f"{where}: unsupported operation {artifact.operation!r}")  # pragma: no cover


def _parameter_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(fmt_value(item) for item in value)
    return fmt_value(value)


def _method(index: int, artifact: AnalysisArtifact) -> ReportMethod:
    where = f"step {index} ({artifact.operation})"
    return ReportMethod(
        step=index,
        operation=artifact.operation,
        title=f"Step {index + 1}: {_TITLES[artifact.operation]}",
        description=_description(artifact, where),
        parameters=tuple(
            (key, _parameter_text(value))
            for key, value in artifact.parameters.items()
            if key not in ("operation", "columns")  # the columns are listed separately
        ),
        input_columns=artifact.input_columns,
        cleaning=artifact.provenance.cleaning,
        rows_in_dataset=artifact.provenance.rows_in_dataset,
        rows_used=artifact.provenance.rows_used,
    )


def _result(index: int, artifact: AnalysisArtifact, chart_indices: tuple[int, ...]) -> ReportResult:
    where = f"step {index} ({artifact.operation}): result"
    facts, tables = _BUILDERS[artifact.operation](artifact.result, where)
    return ReportResult(
        step=index,
        operation=artifact.operation,
        title=f"Step {index + 1}: {_TITLES[artifact.operation]}",
        facts=(
            *facts,
            ("Rows used", str(artifact.provenance.rows_used)),
        ),
        tables=tuple(tables),
        chart_indices=chart_indices,
    )


# --- overview, warnings, limitations -------------------------------------------------------


def _percent(part: int, whole: int) -> str:
    return MISSING if whole == 0 else f"{part / whole * 100:.1f}"


def _overview(profile: DatasetProfile) -> tuple[tuple[tuple[str, str], ...], ReportTable]:
    facts = (
        ("Rows", str(profile.row_count)),
        ("Columns", str(profile.column_count)),
        ("Duplicate rows", str(profile.duplicate_row_count)),
    )
    rows = tuple(
        (
            c.name,
            c.inferred_type,
            str(c.missing_count),
            _percent(c.missing_count, profile.row_count),
            str(c.unique_count),
            fmt_value(c.min),
            fmt_value(c.max),
            fmt_value(c.mean),
            fmt_value(c.median),
            fmt_value(c.std),
            fmt_value(c.q1),
            fmt_value(c.q3),
            fmt_value(c.outlier_count),
        )
        for c in profile.columns
    )
    table = ReportTable(
        caption="Schema and quality profile of the uploaded data",
        headers=(
            "Column",
            "Type",
            "Missing",
            "Missing (%)",
            "Distinct",
            "Min",
            "Max",
            "Mean",
            "Median",
            "Std",
            "Q1",
            "Q3",
            "Outliers (IQR)",
        ),
        rows=rows,
    )
    return facts, table


def _capped(messages: list[str], what: str) -> list[str]:
    if len(messages) <= MAX_PROFILE_WARNINGS:
        return messages
    hidden = len(messages) - MAX_PROFILE_WARNINGS
    return [*messages[:MAX_PROFILE_WARNINGS], f"{hidden} more columns have {what}"]


def _dataset_warnings(profile: DatasetProfile) -> list[ReportWarning]:
    notes: list[str] = []
    rows = profile.row_count
    if rows == 0:
        notes.append("The dataset has no rows")
    if profile.duplicate_row_count:
        share = _percent(profile.duplicate_row_count, rows)
        notes.append(f"{profile.duplicate_row_count} duplicate rows ({share}% of rows) are present")
    missing = [
        f"Column '{c.name}' has {c.missing_count} missing values "
        f"({_percent(c.missing_count, rows)}%)"
        for c in profile.columns
        if c.missing_count
    ]
    outliers = [
        f"Column '{c.name}' has {c.outlier_count} candidate outliers by the IQR rule"
        for c in profile.columns
        if c.outlier_count
    ]
    constant = [
        f"Column '{c.name}' has a single distinct value"
        for c in profile.columns
        if c.unique_count == 1
    ]
    empty = [
        f"Column '{c.name}' has no values" for c in profile.columns if rows and c.unique_count == 0
    ]
    notes += (
        _capped(missing, "missing values")
        + _capped(outliers, "candidate outliers")
        + _capped(constant, "a single distinct value")
        + _capped(empty, "no values")
    )
    return [ReportWarning(scope="Dataset", message=note) for note in notes]


def _step_warnings(index: int, artifact: AnalysisArtifact) -> list[ReportWarning]:
    scope = f"Step {index + 1} ({_TITLES[artifact.operation]})"
    return [ReportWarning(scope=scope, message=text) for text in artifact.warnings]


def _limitations(
    operations: set[OperationName], cleaned: bool, truncated_charts: bool
) -> tuple[str, ...]:
    notes = [
        "All numbers describe this one uploaded file. They say nothing about data that was "
        "not uploaded, and they do not show that one thing causes another.",
        "Column types are inferred from the text in the file, and units are not known. "
        "Check that each inferred type matches what the column means.",
        "Values are rounded to six decimal places where they were computed.",
    ]
    if cleaned:
        notes.append(
            "Results for the steps that list cleaning were computed on a cleaned copy of the "
            "data, not on the data as uploaded. Dropping rows can change who is represented, "
            "and filling in missing values makes a column look less variable than it is."
        )
    else:
        notes.append(
            "No cleaning was applied. Each operation excludes missing values as its warnings "
            "describe, so different steps can use different numbers of rows."
        )
    if "correlation" in operations:
        notes.append(
            "Correlation measures one kind of association between two columns (linear for "
            "Pearson, monotonic for Spearman). A value near zero does not rule out other "
            "relationships."
        )
    if "outlier_summary" in operations:
        notes.append(
            "Outliers here are values outside the IQR bounds. They are candidates to look "
            "at, not errors, and they were not removed."
        )
    if "clustering" in operations:
        notes.append(
            "k-means assumes compact, similarly sized groups and is sensitive to column scale "
            "and to the chosen k. Cluster numbers are only labels, and the clusters are not "
            "validated against any ground truth."
        )
    if "pca" in operations:
        notes.append(
            "PCA finds linear combinations of the selected columns. Components are summaries "
            "of variance, not necessarily meaningful quantities, and standardizing or not "
            "changes the result."
        )
    if "grouped_aggregation" in operations or "distribution" in operations:
        notes.append(
            "Grouped results and category counts can be cut to the largest or first entries; "
            "a warning says so whenever that happened."
        )
    if truncated_charts:
        notes.append(f"A chart shows at most {MAX_CATEGORIES} categories.")
    notes.append(
        "The report is generated by fixed code from computed results. It contains no model-written "
        "text, and it does not interpret the findings."
    )
    return tuple(notes)


# --- assembly -----------------------------------------------------------------------------


def _check_text(name: str, value: str | None, limit: int, required: bool = False) -> None:
    if value is None:
        return
    if required and not value.strip():
        raise ReportError(f"{name} must not be empty")
    if len(value) > limit:
        raise ReportError(f"{name} must be at most {limit} characters")


def _library_versions(artifacts: Sequence[AnalysisArtifact]) -> tuple[dict[str, str], bool]:
    merged: dict[str, str] = {}
    mixed = False
    for artifact in artifacts:
        for name, version in artifact.provenance.library_versions.items():
            if merged.setdefault(name, version) != version:
                mixed = True
    return dict(sorted(merged.items())), mixed


def _checked_artifacts(profile: DatasetProfile, artifacts: Sequence[AnalysisArtifact]) -> None:
    if len(artifacts) > MAX_STEPS:
        raise ReportError(f"a report holds at most {MAX_STEPS} analysis steps")
    for index, artifact in enumerate(artifacts):
        where = f"step {index} ({artifact.operation})"
        if artifact.provenance.dataset_fingerprint != profile.dataset_fingerprint:
            raise ReportError(f"{where} was computed on a different dataset (fingerprint differs)")
        if artifact.provenance.rows_in_dataset > profile.row_count:
            raise ReportError(f"{where} used more rows than the dataset has")


def _checked_charts(
    artifacts: Sequence[AnalysisArtifact], charts: Sequence[ChartSpec] | None
) -> tuple[ChartSpec, ...]:
    if charts is None:
        return charts_for_artifacts(artifacts)
    for position, spec in enumerate(charts):
        try:
            validate_chart(spec, artifacts)
        except ChartTraceError as error:
            raise ReportError(
                f"chart {position + 1} does not trace to its artifact: {error}"
            ) from None
    return tuple(charts)


def build_report(
    profile: DatasetProfile,
    artifacts: Sequence[AnalysisArtifact],
    charts: Sequence[ChartSpec] | None = None,
    *,
    title: str = DEFAULT_TITLE,
    source_name: str | None = None,
    generated_at: str | None = None,
) -> Report:
    """Assemble a report from a profile, executed artifacts and (optionally) chart specs.

    *charts* defaults to the specs derived from *artifacts*. When given, every chart must
    trace to one of the artifacts (:func:`~ai_data_analyst.visualization.validate_chart`).
    *source_name* is the uploaded file's name and *generated_at* an optional timestamp text;
    both are only printed. Raises :class:`ReportError` when the inputs do not fit together.
    """
    _check_text("title", title, MAX_TITLE_LENGTH, required=True)
    _check_text("source_name", source_name, MAX_SOURCE_NAME_LENGTH)
    _check_text("generated_at", generated_at, MAX_GENERATED_AT_LENGTH)
    _checked_artifacts(profile, artifacts)
    specs = _checked_charts(artifacts, charts)

    methods = tuple(_method(i, a) for i, a in enumerate(artifacts))
    results = tuple(
        _result(
            i,
            a,
            tuple(position for position, spec in enumerate(specs) if spec.source_step == i),
        )
        for i, a in enumerate(artifacts)
    )
    versions, mixed = _library_versions(artifacts)
    facts, column_table = _overview(profile)

    warnings = _dataset_warnings(profile)
    if not artifacts:
        warnings.append(ReportWarning(scope="Report", message="No analyses were run"))
    for index, artifact in enumerate(artifacts):
        warnings.extend(_step_warnings(index, artifact))
    if mixed:
        warnings.append(
            ReportWarning(
                scope="Report", message="Steps were computed with different library versions"
            )
        )

    return Report(
        title=title,
        provenance=ReportProvenance(
            dataset_fingerprint=profile.dataset_fingerprint,
            source_name=source_name,
            report_schema_version=REPORT_SCHEMA_VERSION,
            profile_schema_version=PROFILE_SCHEMA_VERSION,
            analysis_schema_version=ANALYSIS_SCHEMA_VERSION,
            chart_schema_version=CHART_SCHEMA_VERSION,
            library_versions=versions,
            generated_at=generated_at,
        ),
        overview_facts=facts,
        column_table=column_table,
        methods=methods,
        results=results,
        charts=specs,
        warnings=tuple(warnings),
        limitations=_limitations(
            {a.operation for a in artifacts},
            cleaned=any(a.provenance.cleaning for a in artifacts),
            truncated_charts=any(len(s.labels) >= MAX_CATEGORIES for s in specs),
        ),
    )
