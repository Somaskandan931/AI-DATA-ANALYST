"""EDA-08: chart specs are complete, JSON-safe and traceable to their source artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import (
    AnalysisArtifact,
    AnalysisPlan,
    ClusteringParams,
    CorrelationParams,
    DistributionParams,
    DropMissingRowsStep,
    GroupedAggregationParams,
    OutlierSummaryParams,
    PcaParams,
    SummaryStatsParams,
    cleaned_view,
    execute_plan,
    execute_plan_on_view,
    typed_frame,
)
from ai_data_analyst.analysis.cleaning import CleaningPlan
from ai_data_analyst.ingestion import IngestedCSV, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested
from ai_data_analyst.visualization import (
    ChartSpec,
    ChartTraceError,
    artifact_digest,
    charts_for_artifact,
    charts_for_artifacts,
    validate_chart,
)

_NUMERIC = ("demand_mwh", "temperature_c")


@pytest.fixture(scope="module")
def ingested(sample_csv_path: Path) -> IngestedCSV:
    return load_csv_path(sample_csv_path)


@pytest.fixture(scope="module")
def profile(ingested: IngestedCSV) -> DatasetProfile:
    return profile_ingested(ingested)


@pytest.fixture(scope="module")
def artifacts(ingested: IngestedCSV, profile: DatasetProfile) -> tuple[AnalysisArtifact, ...]:
    plan = AnalysisPlan(
        steps=(
            SummaryStatsParams(columns=_NUMERIC),
            DistributionParams(column="demand_mwh", bins=8),
            DistributionParams(column="region"),
            GroupedAggregationParams(
                group_by=("region",), value_column="demand_mwh", aggregations=("mean", "count")
            ),
            CorrelationParams(columns=_NUMERIC),
            OutlierSummaryParams(columns=_NUMERIC),
            ClusteringParams(columns=_NUMERIC, k=3),
            PcaParams(columns=_NUMERIC),
        )
    )
    return execute_plan(plan, typed_frame(ingested, profile), profile)


def _specs(artifacts: tuple[AnalysisArtifact, ...], step: int) -> tuple[ChartSpec, ...]:
    return charts_for_artifact(artifacts[step], step)


# --- every operation maps to the right chart --------------------------------------------


def test_summary_stats_is_a_table_not_a_chart(artifacts: tuple[AnalysisArtifact, ...]):
    assert _specs(artifacts, 0) == ()


def test_histogram_uses_the_artifacts_bins_and_counts(artifacts: tuple[AnalysisArtifact, ...]):
    (spec,) = _specs(artifacts, 1)
    result = artifacts[1].result
    assert spec.kind == "histogram"
    assert spec.values == tuple(float(c) for c in result["counts"])  # type: ignore[attr-defined]
    assert spec.bin_edges == tuple(result["bin_edges"])  # type: ignore[arg-type]
    assert len(spec.labels) == 8 and len(spec.bin_edges) == 9  # type: ignore[arg-type]
    assert sum(v for v in spec.values if v is not None) == 481  # 485 rows, 4 missing
    assert spec.title == "Distribution of demand_mwh"
    assert (spec.x_label, spec.y_label) == ("demand_mwh", "Rows")


def test_category_distribution_is_a_bar_chart(artifacts: tuple[AnalysisArtifact, ...]):
    (spec,) = _specs(artifacts, 2)
    assert spec.kind == "bar" and spec.bin_edges is None
    assert len(spec.labels) == 4 and sum(v for v in spec.values or () if v) == 485
    assert "region" in spec.title


def test_grouped_aggregation_gets_one_chart_per_aggregation(
    artifacts: tuple[AnalysisArtifact, ...],
):
    mean, count = _specs(artifacts, 3)
    assert mean.title == "Mean of demand_mwh by region" and mean.y_label == "mean of demand_mwh"
    assert count.y_label == "count of demand_mwh"
    groups = artifacts[3].result["groups"]
    assert mean.labels == tuple(g["keys"]["region"] for g in groups)  # type: ignore[index, union-attr]
    assert mean.values == tuple(g["mean"] for g in groups)  # type: ignore[index, union-attr]
    assert count.values == tuple(float(g["count"]) for g in groups)  # type: ignore[index, union-attr]


def test_correlation_is_a_square_heatmap(artifacts: tuple[AnalysisArtifact, ...]):
    (spec,) = _specs(artifacts, 4)
    assert spec.kind == "heatmap" and spec.values is None
    assert spec.labels == _NUMERIC
    assert spec.matrix is not None and len(spec.matrix) == 2
    assert spec.matrix[0][0] == 1.0 and spec.matrix[0][1] == spec.matrix[1][0]
    assert spec.title == "Pearson correlation"


def test_outlier_chart_shows_the_fraction_per_column(artifacts: tuple[AnalysisArtifact, ...]):
    (spec,) = _specs(artifacts, 5)
    assert spec.labels == _NUMERIC
    report = artifacts[5].result["columns"]
    assert spec.values == tuple(report[n]["outlier_fraction"] for n in _NUMERIC)  # type: ignore[index]
    assert "IQR factor 1.5" in spec.title


def test_clustering_and_pca_charts(artifacts: tuple[AnalysisArtifact, ...]):
    (clusters,) = _specs(artifacts, 6)
    assert clusters.labels == ("Cluster 0", "Cluster 1", "Cluster 2")
    assert sum(v for v in clusters.values or () if v) == 469
    assert clusters.title == "Cluster sizes (k=3)"
    (pca,) = _specs(artifacts, 7)
    assert pca.labels == ("PC1", "PC2")
    assert sum(v for v in pca.values or () if v) == pytest.approx(1.0, abs=1e-5)


def test_all_charts_are_titled_labelled_and_name_their_source_columns(
    artifacts: tuple[AnalysisArtifact, ...],
):
    specs = charts_for_artifacts(artifacts)
    assert len(specs) == 8  # 0 + 1 + 1 + 2 + 1 + 1 + 1 + 1
    for spec in specs:
        assert spec.title and spec.x_label and spec.y_label
        assert spec.source_columns == artifacts[spec.source_step].input_columns
        assert all(column in spec.subtitle for column in spec.source_columns)
        assert spec.operation == artifacts[spec.source_step].operation


# --- traceability -----------------------------------------------------------------------


def test_every_generated_chart_validates_against_its_artifact(
    artifacts: tuple[AnalysisArtifact, ...],
):
    for spec in charts_for_artifacts(artifacts):
        validate_chart(spec, artifacts)


def test_chart_specs_are_deterministic_and_strict_json(artifacts: tuple[AnalysisArtifact, ...]):
    first, second = charts_for_artifacts(artifacts), charts_for_artifacts(artifacts)
    assert first == second
    for spec in first:
        json.dumps(spec.model_dump(mode="json"), allow_nan=False)
        assert ChartSpec.model_validate_json(spec.model_dump_json()) == spec


def test_digest_changes_when_the_artifact_changes(artifacts: tuple[AnalysisArtifact, ...]):
    digest = artifact_digest(artifacts[1])
    assert digest == artifact_digest(artifacts[1])
    assert digest != artifact_digest(artifacts[2])
    changed = artifacts[1].model_copy(update={"warnings": ("extra",)})
    assert digest != artifact_digest(changed)


@pytest.mark.parametrize(
    "update",
    [
        {"values": (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)},  # edited numbers
        {"title": "Distribution of something else"},  # edited text is not derivable
        {"labels": ("a", "b", "c", "d", "e", "f", "g", "h")},
        {"artifact_digest": "0" * 64},  # claims a different artifact
        {"source_step": 99},  # refers to nothing
    ],
)
def test_tampered_charts_are_rejected(
    artifacts: tuple[AnalysisArtifact, ...], update: dict[str, Any]
):
    (spec,) = _specs(artifacts, 1)
    tampered = spec.model_copy(update=update)  # model_copy skips validators, as a forgery would
    with pytest.raises(ChartTraceError):
        validate_chart(tampered, artifacts)


def test_a_chart_is_rejected_against_a_different_artifact_list(
    artifacts: tuple[AnalysisArtifact, ...],
):
    (spec,) = _specs(artifacts, 1)
    swapped = (artifacts[0], artifacts[2], *artifacts[2:])
    with pytest.raises(ChartTraceError, match="digest differs"):
        validate_chart(spec, swapped)


# --- cleaning travels with the chart ----------------------------------------------------


def test_chart_subtitle_and_metadata_carry_the_cleaning_log(
    ingested: IngestedCSV, profile: DatasetProfile
):
    view = cleaned_view(
        ingested, profile, CleaningPlan(steps=(DropMissingRowsStep(columns=("demand_mwh",)),))
    )
    plan = AnalysisPlan(steps=(DistributionParams(column="demand_mwh"),))
    artifacts = execute_plan_on_view(plan, view, profile)
    (spec,) = charts_for_artifacts(artifacts)
    assert spec.cleaning == view.log
    assert "Cleaning: Removed 4 rows with a missing value in: demand_mwh" in spec.subtitle
    validate_chart(spec, artifacts)


def test_artifact_warnings_are_carried_into_the_chart(artifacts: tuple[AnalysisArtifact, ...]):
    (spec,) = _specs(artifacts, 1)
    assert spec.warnings == artifacts[1].warnings
    assert any("missing values excluded" in w for w in spec.warnings)


# --- spec shape rules -------------------------------------------------------------------


def _bar(**overrides: Any) -> ChartSpec:
    fields: dict[str, Any] = {
        "kind": "bar",
        "title": "t",
        "subtitle": "s",
        "x_label": "x",
        "y_label": "y",
        "labels": ("a", "b"),
        "values": (1.0, 2.0),
        "source_step": 0,
        "operation": "distribution",
        "artifact_digest": "a" * 64,
        "source_columns": ("c",),
    }
    return ChartSpec(**{**fields, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"values": (1.0,)},  # length mismatch
        {"values": None},
        {"matrix": ((1.0, 2.0), (3.0, 4.0))},  # a bar chart has no matrix
        {"bin_edges": (0.0, 1.0, 2.0)},  # only histograms have edges
        {"title": ""},
        {"artifact_digest": "xyz"},
        {"values": (float("nan"), 1.0)},
        {"labels": tuple(str(i) for i in range(101)), "values": (1.0,) * 101},
        {"unexpected": 1},
    ],
)
def test_malformed_chart_specs_are_rejected(overrides: dict[str, Any]):
    with pytest.raises(ValidationError):
        _bar(**overrides)


def test_histogram_and_heatmap_shape_rules():
    with pytest.raises(ValidationError):
        _bar(kind="histogram", bin_edges=(0.0, 1.0))  # needs bins + 1 edges
    with pytest.raises(ValidationError):
        _bar(kind="heatmap", values=None, matrix=((1.0, 0.0),))  # not square
    with pytest.raises(ValidationError):
        _bar(kind="heatmap")  # heatmaps carry a matrix, not values
