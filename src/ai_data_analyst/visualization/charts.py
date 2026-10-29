"""Chart specifications built from analysis artifacts (EDA-08).

A :class:`ChartSpec` is plain, JSON-serialisable data: a title, axis labels, the plotted
numbers, the dataset columns they came from, and any cleaning that was applied. It says
*what* to draw and never *how*, so the UI can render it with any library.

Traceability (PRD acceptance criterion 5): every spec records the position and SHA-256
digest of the artifact it was built from, and its numbers are copied from that artifact and
nowhere else. :func:`validate_chart` rebuilds the charts for the referenced artifact and
requires an exact match, so a spec whose data or labels were edited cannot pass.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..analysis import AnalysisArtifact, OperationName

CHART_SCHEMA_VERSION: Final = "1.0"
MAX_CATEGORIES: Final = 100

ChartKind = Literal["bar", "histogram", "heatmap"]


class ChartTraceError(ValueError):
    """A chart spec does not match the artifact it claims to come from."""


class ChartSpec(BaseModel):
    """What to draw, with enough provenance to trace every number back to an artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = CHART_SCHEMA_VERSION
    kind: ChartKind
    title: str = Field(min_length=1)
    subtitle: str = Field(description="Source columns and any cleaning applied")
    x_label: str
    y_label: str
    labels: tuple[str, ...] = Field(max_length=MAX_CATEGORIES)
    values: tuple[float | None, ...] | None = None
    matrix: tuple[tuple[float | None, ...], ...] | None = None
    bin_edges: tuple[float, ...] | None = None
    source_step: int = Field(ge=0, description="Index of the artifact in the executed plan")
    operation: OperationName
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_columns: tuple[str, ...]
    cleaning: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Self:
        if self.kind == "heatmap":
            size = len(self.labels)
            if self.values is not None or self.bin_edges is not None or self.matrix is None:
                raise ValueError("a heatmap needs a matrix and nothing else")
            if len(self.matrix) != size or any(len(row) != size for row in self.matrix):
                raise ValueError("heatmap matrix must be square, one row per label")
            return self
        if self.matrix is not None or self.values is None:
            raise ValueError(f"a {self.kind} chart needs values and no matrix")
        if len(self.values) != len(self.labels):
            raise ValueError("values and labels must have the same length")
        if self.kind == "histogram":
            if self.bin_edges is None or len(self.bin_edges) != len(self.values) + 1:
                raise ValueError("a histogram needs one more bin edge than bins")
        elif self.bin_edges is not None:
            raise ValueError("only histograms have bin edges")
        return self


def artifact_digest(artifact: AnalysisArtifact) -> str:
    """SHA-256 of the artifact's canonical JSON, used to bind a chart to its source."""
    text = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _truncate(
    labels: list[str], values: list[float | None]
) -> tuple[list[str], list[float | None]]:
    return labels[:MAX_CATEGORIES], values[:MAX_CATEGORIES]


class _Base:
    """Fields shared by every chart built from one artifact."""

    def __init__(self, artifact: AnalysisArtifact, index: int) -> None:
        self.artifact = artifact
        columns = ", ".join(artifact.input_columns)
        notes = artifact.provenance.cleaning
        self.subtitle = f"Columns: {columns}" + (
            f" | Cleaning: {'; '.join(notes)}" if notes else ""
        )
        self.common: dict[str, Any] = {
            "subtitle": self.subtitle,
            "source_step": index,
            "operation": artifact.operation,
            "artifact_digest": artifact_digest(artifact),
            "source_columns": artifact.input_columns,
            "cleaning": artifact.provenance.cleaning,
            "warnings": artifact.warnings,
        }


def _distribution(base: _Base) -> list[ChartSpec]:
    result = base.artifact.result
    column = str(result.get("column"))
    if result.get("kind") == "histogram":
        edges = [float(e) for e in _list(result.get("bin_edges")) if _number(e) is not None]
        counts = [_number(c) for c in _list(result.get("counts"))]
        if not counts or len(edges) != len(counts) + 1:
            return []
        labels = [f"{edges[i]:g} to {edges[i + 1]:g}" for i in range(len(counts))]
        return [
            ChartSpec(
                kind="histogram",
                title=f"Distribution of {column}",
                x_label=column,
                y_label="Rows",
                labels=tuple(labels),
                values=tuple(counts),
                bin_edges=tuple(edges),
                **base.common,
            )
        ]
    entries = [_dict(v) for v in _list(result.get("values"))]
    if not entries:
        return []
    labels = [str(e.get("value")) for e in entries]
    counts = [_number(e.get("count")) for e in entries]
    labels, counts = _truncate(labels, counts)
    return [
        ChartSpec(
            kind="bar",
            title=f"Most frequent values of {column}",
            x_label=column,
            y_label="Rows",
            labels=tuple(labels),
            values=tuple(counts),
            **base.common,
        )
    ]


def _grouped(base: _Base) -> list[ChartSpec]:
    result = base.artifact.result
    group_by = [str(g) for g in _list(result.get("group_by"))]
    value = str(result.get("value_column"))
    groups = [_dict(g) for g in _list(result.get("groups"))]
    if not groups:
        return []
    charts: list[ChartSpec] = []
    for agg in (str(a) for a in _list(result.get("aggregations"))):
        labels = [" / ".join(str(_dict(g.get("keys")).get(k)) for k in group_by) for g in groups]
        values = [_number(g.get(agg)) for g in groups]
        labels, values = _truncate(labels, values)
        charts.append(
            ChartSpec(
                kind="bar",
                title=f"{agg.capitalize()} of {value} by {', '.join(group_by)}",
                x_label=", ".join(group_by),
                y_label=f"{agg} of {value}",
                labels=tuple(labels),
                values=tuple(values),
                **base.common,
            )
        )
    return charts


def _correlation(base: _Base) -> list[ChartSpec]:
    result = base.artifact.result
    names = [str(c) for c in _list(result.get("columns"))]
    matrix = tuple(tuple(_number(c) for c in _list(row)) for row in _list(result.get("matrix")))
    return [
        ChartSpec(
            kind="heatmap",
            title=f"{str(result.get('method')).capitalize()} correlation",
            x_label="Column",
            y_label="Column",
            labels=tuple(names),
            matrix=matrix,
            **base.common,
        )
    ]


def _outliers(base: _Base) -> list[ChartSpec]:
    result = base.artifact.result
    report = _dict(result.get("columns"))
    names = list(report)
    values = [_number(_dict(report[n]).get("outlier_fraction")) for n in names]
    if not names:
        return []
    labels, values = _truncate(names, values)
    return [
        ChartSpec(
            kind="bar",
            title=f"Outlier fraction by column (IQR factor {result.get('iqr_factor')})",
            x_label="Column",
            y_label="Fraction of rows outside the IQR bounds",
            labels=tuple(labels),
            values=tuple(values),
            **base.common,
        )
    ]


def _clustering(base: _Base) -> list[ChartSpec]:
    result = base.artifact.result
    clusters = [_dict(c) for c in _list(result.get("clusters"))]
    if not clusters:
        return []
    return [
        ChartSpec(
            kind="bar",
            title=f"Cluster sizes (k={result.get('k')})",
            x_label="Cluster (largest first)",
            y_label="Rows",
            labels=tuple(f"Cluster {c.get('cluster')}" for c in clusters),
            values=tuple(_number(c.get("size")) for c in clusters),
            **base.common,
        )
    ]


def _pca(base: _Base) -> list[ChartSpec]:
    components = [_dict(c) for c in _list(base.artifact.result.get("components"))]
    if not components:
        return []
    return [
        ChartSpec(
            kind="bar",
            title="Variance explained by each principal component",
            x_label="Component",
            y_label="Share of total variance",
            labels=tuple(str(c.get("component")) for c in components),
            values=tuple(_number(c.get("explained_variance_ratio")) for c in components),
            **base.common,
        )
    ]


def charts_for_artifact(artifact: AnalysisArtifact, index: int = 0) -> tuple[ChartSpec, ...]:
    """Chart specs for one artifact (none for ``summary_stats``, which is a table)."""
    base = _Base(artifact, index)
    match artifact.operation:
        case "distribution":
            return tuple(_distribution(base))
        case "grouped_aggregation":
            return tuple(_grouped(base))
        case "correlation":
            return tuple(_correlation(base))
        case "outlier_summary":
            return tuple(_outliers(base))
        case "clustering":
            return tuple(_clustering(base))
        case "pca":
            return tuple(_pca(base))
        case "summary_stats":
            return ()


def charts_for_artifacts(artifacts: Sequence[AnalysisArtifact]) -> tuple[ChartSpec, ...]:
    """Chart specs for every artifact of an executed plan, in plan order."""
    return tuple(
        spec
        for index, artifact in enumerate(artifacts)
        for spec in charts_for_artifact(artifact, index)
    )


def validate_chart(spec: ChartSpec, artifacts: Sequence[AnalysisArtifact]) -> None:
    """Raise :class:`ChartTraceError` unless *spec* is exactly derivable from its artifact."""
    if spec.source_step >= len(artifacts):
        raise ChartTraceError(f"chart refers to artifact {spec.source_step}, which does not exist")
    artifact = artifacts[spec.source_step]
    if spec.artifact_digest != artifact_digest(artifact):
        raise ChartTraceError("chart does not match its source artifact (digest differs)")
    if spec not in charts_for_artifact(artifact, spec.source_step):
        raise ChartTraceError("chart data or labels differ from what its artifact produces")
