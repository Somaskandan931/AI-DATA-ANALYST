"""Clustering and PCA (EDA-06): correctness against independent computations, edge cases,
reproducibility and resource limits."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from threadpoolctl import threadpool_limits

from ai_data_analyst.analysis import (
    AnalysisArtifact,
    AnalysisPlan,
    ClusteringParams,
    OperationInputError,
    PcaParams,
    PlanValidationError,
    execute_plan,
    typed_frame,
    validate_plan,
)
from ai_data_analyst.ingestion import IngestedCSV, load_csv, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested


def _dataset(text: str) -> tuple[pd.DataFrame, DatasetProfile]:
    ingested = load_csv(text.encode(), "d.csv")
    profile = profile_ingested(ingested)
    return typed_frame(ingested, profile), profile


def _run(frame: pd.DataFrame, profile: DatasetProfile, *steps: Any) -> tuple[AnalysisArtifact, ...]:
    return execute_plan(AnalysisPlan(steps=steps), frame, profile)


def _blobs() -> str:
    """Three tight, well-separated groups of 30, 20 and 10 points around known centres."""
    rng = np.random.default_rng(7)
    rows: list[tuple[float, float]] = []
    for size, (cx, cy) in ((30, (0.0, 0.0)), (20, (50.0, 50.0)), (10, (100.0, 0.0))):
        points = rng.normal(0.0, 0.5, size=(size, 2)) + (cx, cy)
        rows.extend((round(float(x), 3), round(float(y), 3)) for x, y in points)
    return "x,y\n" + "\n".join(f"{x},{y}" for x, y in rows) + "\n"


@pytest.fixture(scope="module")
def sample(sample_csv_path: Path) -> tuple[pd.DataFrame, DatasetProfile, IngestedCSV]:
    ingested = load_csv_path(sample_csv_path)
    profile = profile_ingested(ingested)
    return typed_frame(ingested, profile), profile, ingested


def _result(artifact: AnalysisArtifact) -> dict[str, Any]:
    return typing.cast(dict[str, Any], artifact.result)


# --- plan parameters and validation -----------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: ClusteringParams(columns=("a", "b"), k=1),
        lambda: ClusteringParams(columns=("a", "b"), k=11),
        lambda: ClusteringParams(columns=("a",), k=2),
        lambda: ClusteringParams(columns=("a", "a"), k=2),
        lambda: ClusteringParams(columns=tuple("abcdefghijk"), k=2),
        lambda: ClusteringParams(columns=("a", "b"), k=2, random_state=-1),
        lambda: ClusteringParams(columns=("a", "b"), k=2, init="random"),  # type: ignore[call-arg]
        lambda: PcaParams(columns=("a",)),
        lambda: PcaParams(columns=("a", "b"), n_components=3),
        lambda: PcaParams(columns=("a", "b"), n_components=0),
        lambda: PcaParams(columns=("a", "a")),
    ],
)
def test_invalid_ml_parameters_are_rejected(build: Any):
    with pytest.raises(ValidationError):
        build()


def test_ml_steps_round_trip_through_json_and_reject_code_fields():
    plan = AnalysisPlan(
        steps=(ClusteringParams(columns=("a", "b"), k=3), PcaParams(columns=("a", "b")))
    )
    assert AnalysisPlan.model_validate_json(plan.model_dump_json()) == plan
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(
            {"steps": [{"operation": "clustering", "columns": ["a", "b"], "k": 2, "fn": "x"}]}
        )


@pytest.mark.parametrize(
    ("step", "fragment"),
    [
        (ClusteringParams(columns=("demand_mwh", "nope"), k=2), "unknown column"),
        (ClusteringParams(columns=("demand_mwh", "region"), k=2), "expected a numeric column"),
        (ClusteringParams(columns=("demand_mwh", "temperature_c"), k=10), None),
        (PcaParams(columns=("demand_mwh", "date")), "expected a numeric column"),
        (PcaParams(columns=("demand_mwh", "holiday")), "expected a numeric column"),
    ],
)
def test_validate_plan_checks_ml_columns(
    sample: tuple[pd.DataFrame, DatasetProfile, IngestedCSV], step: Any, fragment: str | None
):
    _, profile, _ = sample
    plan = AnalysisPlan(steps=(step,))
    if fragment is None:
        validate_plan(plan, profile)
        return
    with pytest.raises(PlanValidationError, match=fragment):
        validate_plan(plan, profile)


def test_validate_plan_rejects_more_clusters_than_rows():
    _, profile = _dataset("a,b\n1,2\n3,4\n")
    with pytest.raises(PlanValidationError, match="exceeds the dataset's 2 rows"):
        validate_plan(AnalysisPlan(steps=(ClusteringParams(columns=("a", "b"), k=3),)), profile)


# --- clustering correctness -------------------------------------------------------------


def test_clustering_recovers_known_blobs():
    frame, profile = _dataset(_blobs())
    (artifact,) = _run(frame, profile, ClusteringParams(columns=("x", "y"), k=3))
    result = _result(artifact)
    clusters = result["clusters"]
    assert [c["size"] for c in clusters] == [30, 20, 10]  # numbered largest first
    assert [c["cluster"] for c in clusters] == [0, 1, 2]
    for cluster, centre in zip(clusters, [(0, 0), (50, 50), (100, 0)], strict=True):
        assert cluster["centroid"]["x"] == pytest.approx(centre[0], abs=0.6)
        assert cluster["centroid"]["y"] == pytest.approx(centre[1], abs=0.6)
    assert sum(c["fraction"] for c in clusters) == pytest.approx(1.0, abs=1e-5)
    assert result["silhouette"] > 0.9
    assert result["rows_clustered"] == 60
    assert artifact.provenance.rows_used == 60


def test_clustering_centroids_and_inertia_match_an_independent_computation(
    sample: tuple[pd.DataFrame, DatasetProfile, IngestedCSV],
):
    frame, profile, _ = sample
    (artifact,) = _run(
        frame, profile, ClusteringParams(columns=("demand_mwh", "temperature_c"), k=3)
    )
    result = _result(artifact)
    complete = frame[["demand_mwh", "temperature_c"]].dropna().to_numpy(dtype=float)
    assert result["rows_clustered"] == len(complete) == 469
    centroids = np.array(
        [[c["centroid"]["demand_mwh"], c["centroid"]["temperature_c"]] for c in result["clusters"]]
    )
    # Every row belongs to its nearest centroid in standardised space: recompute inertia.
    mean, std = complete.mean(axis=0), complete.std(axis=0)  # population std, like StandardScaler
    z, zc = (complete - mean) / std, (centroids - mean) / std
    distances = ((z[:, None, :] - zc[None, :, :]) ** 2).sum(axis=2)
    assert distances.min(axis=1).sum() == pytest.approx(result["inertia"], rel=1e-4)
    assert distances.argmin(axis=1).tolist().count(0) == result["clusters"][0]["size"]
    sizes = [c["size"] for c in result["clusters"]]
    assert sizes == sorted(sizes, reverse=True) and sum(sizes) == 469
    assert any("16 rows with a missing value" in w for w in artifact.warnings)


def test_clustering_is_reproducible_and_independent_of_thread_count():
    frame, profile = _dataset(_blobs())
    step = ClusteringParams(columns=("x", "y"), k=3, random_state=11)
    first = _run(frame, profile, step)[0]
    again = _run(frame, profile, step)[0]
    with threadpool_limits(limits=4):
        threaded = _run(frame, profile, step)[0]
    assert first.result == again.result == threaded.result
    assert first.parameters["random_state"] == 11


def test_different_seeds_are_recorded_and_still_find_separated_groups():
    frame, profile = _dataset(_blobs())
    for seed in (0, 1, 2**31 - 1):
        (artifact,) = _run(
            frame, profile, ClusteringParams(columns=("x", "y"), k=3, random_state=seed)
        )
        assert [c["size"] for c in _result(artifact)["clusters"]] == [30, 20, 10]
        assert artifact.parameters["random_state"] == seed


def test_standardize_false_uses_original_units_and_warns_on_scale_mismatch():
    csv = "small,large\n" + "\n".join(f"{i % 5},{1000 * (i % 7) + i}" for i in range(60)) + "\n"
    frame, profile = _dataset(csv)
    (artifact,) = _run(
        frame, profile, ClusteringParams(columns=("small", "large"), k=2, standardize=False)
    )
    assert _result(artifact)["inertia_space"] == "original"
    assert _result(artifact)["standardized"] is False
    assert any("very different scales" in w for w in artifact.warnings)
    (scaled,) = _run(frame, profile, ClusteringParams(columns=("small", "large"), k=2))
    assert not any("very different scales" in w for w in scaled.warnings)


def test_constant_column_is_reported_not_hidden():
    frame, profile = _dataset("a,b\n" + "\n".join(f"{i},5" for i in range(20)) + "\n")
    (artifact,) = _run(frame, profile, ClusteringParams(columns=("a", "b"), k=2))
    assert "b: all values are identical" in artifact.warnings


def test_clustering_fails_closed_when_data_cannot_support_k():
    few, profile = _dataset("a,b\n1,1\n2,2\n3,\n4,\n")
    with pytest.raises(OperationInputError, match="step 0: .*at least 3 complete rows, found 2"):
        _run(few, profile, ClusteringParams(columns=("a", "b"), k=3))
    same, profile = _dataset("a,b\n1,1\n1,1\n1,1\n2,2\n")
    with pytest.raises(OperationInputError, match="at least 3 distinct rows, found 2"):
        _run(same, profile, ClusteringParams(columns=("a", "b"), k=3))


def test_a_failing_step_reports_its_index_and_returns_nothing():
    frame, profile = _dataset("a,b\n1,1\n2,2\n3,\n")
    steps = (
        PcaParams(columns=("a", "b"), n_components=1),
        ClusteringParams(columns=("a", "b"), k=3),
    )
    with pytest.raises(OperationInputError, match="^step 1: ") as raised:
        _run(frame, profile, *steps)
    assert raised.value.step == 1


def test_one_row_per_cluster_has_no_silhouette():
    frame, profile = _dataset("a,b\n1,1\n5,9\n")
    (artifact,) = _run(frame, profile, ClusteringParams(columns=("a", "b"), k=2))
    assert _result(artifact)["silhouette"] is None
    assert [c["size"] for c in _result(artifact)["clusters"]] == [1, 1]


def test_clustering_artifact_is_strict_json_with_provenance():
    frame, profile = _dataset(_blobs())
    (artifact,) = _run(frame, profile, ClusteringParams(columns=("x", "y"), k=2))
    json.dumps(artifact.model_dump(mode="json"), allow_nan=False)
    assert AnalysisArtifact.model_validate_json(artifact.model_dump_json()) == artifact
    assert artifact.operation == "clustering"
    assert artifact.input_columns == ("x", "y")
    assert artifact.provenance.dataset_fingerprint == profile.dataset_fingerprint
    assert "scikit-learn" in artifact.provenance.library_versions


def test_ml_steps_respect_the_execution_time_limit_between_steps(
    monkeypatch: pytest.MonkeyPatch,
):
    from ai_data_analyst.analysis import operations
    from ai_data_analyst.security import LimitsConfig

    frame, profile = _dataset(_blobs())
    ticks = iter([0.0, 0.5, 100.0, 100.0, 100.0])  # deadline is 1s: the second step is too late
    monkeypatch.setattr(operations.time, "monotonic", lambda: next(ticks))
    plan = AnalysisPlan(
        steps=(ClusteringParams(columns=("x", "y"), k=3), PcaParams(columns=("x", "y")))
    )
    with pytest.raises(operations.ExecutionTimeError):
        execute_plan(plan, frame, profile, LimitsConfig(max_execution_seconds=1))


def test_ml_parameter_bounds_cap_the_work_a_plan_can_request():
    biggest = ClusteringParams(columns=tuple("abcdefghij"), k=10)
    assert (len(biggest.columns), biggest.k) == (10, 10)
    with pytest.raises(ValidationError):
        ClusteringParams(columns=tuple("abcdefghijk"), k=10)
    with pytest.raises(ValidationError):
        PcaParams(columns=tuple("abcdefghijklmnopqrstu"), n_components=10)
    with pytest.raises(ValidationError):
        AnalysisPlan(steps=(biggest,) * 21)


# --- PCA correctness --------------------------------------------------------------------


def test_pca_matches_an_eigendecomposition_of_the_covariance_matrix(
    sample: tuple[pd.DataFrame, DatasetProfile, IngestedCSV],
):
    frame, profile, _ = sample
    names = ("demand_mwh", "temperature_c")
    (artifact,) = _run(frame, profile, PcaParams(columns=names, n_components=2))
    result = _result(artifact)
    complete = frame[list(names)].dropna().to_numpy(dtype=float)
    z = (complete - complete.mean(axis=0)) / complete.std(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(z, rowvar=False))
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    for index, component in enumerate(result["components"]):
        assert component["explained_variance"] == pytest.approx(eigenvalues[index], abs=1e-5)
        assert component["explained_variance_ratio"] == pytest.approx(
            eigenvalues[index] / eigenvalues.sum(), abs=1e-5
        )
        got = np.array([component["loadings"][n] for n in names])
        assert np.abs(got) == pytest.approx(np.abs(eigenvectors[:, index]), abs=1e-5)
    assert result["rows_used"] == 469
    assert result["total_variance"] == pytest.approx(eigenvalues.sum(), abs=1e-5)
    assert result["components"][-1]["cumulative_ratio"] == pytest.approx(1.0, abs=1e-5)


def test_pca_loadings_are_orthonormal_with_a_fixed_sign_convention():
    rng = np.random.default_rng(3)
    base = rng.normal(size=200)
    csv = "a,b,c\n" + "\n".join(
        f"{x:.4f},{(2 * x + rng.normal(scale=0.3)):.4f},{rng.normal():.4f}" for x in base
    )
    frame, profile = _dataset(csv + "\n")
    (artifact,) = _run(frame, profile, PcaParams(columns=("a", "b", "c"), n_components=3))
    components = _result(artifact)["components"]
    matrix = np.array([[c["loadings"][n] for n in "abc"] for c in components])
    assert matrix @ matrix.T == pytest.approx(np.eye(3), abs=1e-4)
    for row in matrix:  # the largest-magnitude loading of every component is positive
        assert row[int(np.argmax(np.abs(row)))] > 0
    ratios = [c["explained_variance_ratio"] for c in components]
    assert ratios == sorted(ratios, reverse=True)
    assert components[0]["explained_variance_ratio"] > 0.6


def test_perfectly_correlated_columns_put_all_variance_in_one_component():
    frame, profile = _dataset("x,y\n" + "\n".join(f"{i},{2 * i}" for i in range(30)) + "\n")
    (artifact,) = _run(frame, profile, PcaParams(columns=("x", "y"), n_components=2))
    first, second = _result(artifact)["components"]
    assert first["explained_variance_ratio"] == pytest.approx(1.0, abs=1e-6)
    assert second["explained_variance_ratio"] == pytest.approx(0.0, abs=1e-6)


def test_pca_is_reproducible_and_artifact_is_strict_json():
    frame, profile = _dataset(_blobs())
    step = PcaParams(columns=("x", "y"))
    first, second = _run(frame, profile, step)[0], _run(frame, profile, step)[0]
    assert first.result == second.result
    json.dumps(first.model_dump(mode="json"), allow_nan=False)
    assert first.provenance.rows_used == 60


def test_pca_standardize_false_warns_on_scale_mismatch_and_keeps_original_units():
    csv = "small,large\n" + "\n".join(f"{i % 5},{1000 * (i % 7) + i}" for i in range(60)) + "\n"
    frame, profile = _dataset(csv)
    (artifact,) = _run(frame, profile, PcaParams(columns=("small", "large"), standardize=False))
    assert any("very different scales" in w for w in artifact.warnings)
    first = _result(artifact)["components"][0]
    assert first["explained_variance_ratio"] > 0.99  # the large-scale column dominates
    assert abs(first["loadings"]["large"]) > 0.99


def test_pca_fails_closed_on_unusable_data():
    frame, profile = _dataset("a,b\n1,2\n3,\n,4\n")
    with pytest.raises(OperationInputError, match="needs at least 2 complete rows, found 1"):
        _run(frame, profile, PcaParams(columns=("a", "b")))
    frame, profile = _dataset("a,b\n1,5\n1,5\n1,5\n")
    with pytest.raises(OperationInputError, match="every selected column is constant"):
        _run(frame, profile, PcaParams(columns=("a", "b")))


def test_pca_with_one_constant_column_still_runs_and_warns():
    frame, profile = _dataset("a,b\n" + "\n".join(f"{i},7" for i in range(10)) + "\n")
    (artifact,) = _run(frame, profile, PcaParams(columns=("a", "b"), n_components=1))
    assert "b: all values are identical" in artifact.warnings
    assert _result(artifact)["components"][0]["explained_variance_ratio"] == pytest.approx(1.0)
