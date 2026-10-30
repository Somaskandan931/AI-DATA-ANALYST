import numpy as np
import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation.metrics import (
    PhaseLatency,
    _percentile,
    linear_percentile,
    summarize_phase_latency,
)


def test_empty_samples_have_a_zero_count_and_no_values():
    summary = summarize_phase_latency([])

    assert summary.count == 0
    assert summary.median_ms is None
    assert summary.p95_ms is None
    assert summary.max_ms is None


def test_single_sample():
    summary = summarize_phase_latency([7.0])

    assert summary.count == 1
    assert summary.median_ms == 7.0
    assert summary.p95_ms == 7.0
    assert summary.max_ms == 7.0


def test_median_and_p95_use_linear_interpolation():
    summary = summarize_phase_latency([1.0, 2.0, 3.0, 4.0])

    assert summary.count == 4
    assert summary.median_ms == pytest.approx(2.5)
    assert summary.p95_ms == pytest.approx(3.85)
    assert summary.max_ms == 4.0


def test_two_samples_interpolate_p95():
    summary = summarize_phase_latency([1.0, 2.0])

    assert summary.median_ms == pytest.approx(1.5)
    assert summary.p95_ms == pytest.approx(1.95)
    assert summary.max_ms == 2.0


def test_samples_are_sorted_before_summarizing():
    assert summarize_phase_latency([4.0, 1.0, 3.0, 2.0]) == summarize_phase_latency(
        [1.0, 2.0, 3.0, 4.0]
    )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_samples_are_rejected(value: float):
    with pytest.raises(ValueError):
        summarize_phase_latency([1.0, value])


def test_count_and_values_must_agree():
    with pytest.raises(ValidationError):
        PhaseLatency(count=0, median_ms=1.0)

    with pytest.raises(ValidationError):
        PhaseLatency(count=2, median_ms=1.0, p95_ms=1.0)

    with pytest.raises(ValidationError):
        PhaseLatency(count=2, median_ms=1.0, p95_ms=1.0, max_ms=None)


def test_summary_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        PhaseLatency(count=0, surprise=True)

    summary = PhaseLatency(count=0)
    with pytest.raises(ValidationError):
        summary.count = 1


def test_summary_json_round_trip():
    summary = summarize_phase_latency([1.0, 2.0, 3.0])

    assert PhaseLatency.model_validate_json(summary.model_dump_json()) == summary


def test_public_names_are_exported():
    import ai_data_analyst.evaluation.metrics as metrics

    assert set(metrics.__all__) == {
        "PhaseLatency",
        "linear_percentile",
        "summarize_phase_latency",
    }


def test_linear_percentile_hand_computed():
    assert linear_percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert linear_percentile([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)
    assert linear_percentile([1.0, 2.0], 95) == pytest.approx(1.95)


def test_linear_percentile_endpoints_are_min_and_max():
    assert linear_percentile([3.0, 1.0, 2.0], 0) == 1.0
    assert linear_percentile([3.0, 1.0, 2.0], 100) == 3.0


@pytest.mark.parametrize("percent", [0.0, 37.5, 100.0])
def test_linear_percentile_single_sample(percent: float):
    assert linear_percentile([7.0], percent) == 7.0


def test_linear_percentile_ignores_order_and_does_not_mutate():
    values = [4.0, 1.0, 3.0, 2.0]

    assert linear_percentile(values, 50) == linear_percentile([1.0, 2.0, 3.0, 4.0], 50)
    assert values == [4.0, 1.0, 3.0, 2.0]


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
@pytest.mark.parametrize("percent", [0.0, 5.0, 50.0, 95.0, 100.0])
def test_linear_percentile_matches_numpy(seed: int, size: int, percent: float):
    data = np.random.default_rng(seed).random(size) * 1000
    expected = float(np.percentile(data, percent, method="linear"))

    assert linear_percentile([float(value) for value in data], percent) == pytest.approx(
        expected, abs=1e-9
    )


@pytest.mark.parametrize(
    "values",
    [[], [1.0, float("nan")], [1.0, float("inf")], [1.0, float("-inf")]],
)
def test_linear_percentile_rejects_bad_values(values: list[float]):
    with pytest.raises(ValueError):
        linear_percentile(values, 50)


@pytest.mark.parametrize("percent", [-1.0, 100.1, float("nan"), float("inf")])
def test_linear_percentile_rejects_bad_percent(percent: float):
    with pytest.raises(ValueError):
        linear_percentile([1.0, 2.0], percent)


@pytest.mark.parametrize("fraction", [1.5, -0.5])
def test_percentile_rejects_fraction_outside_unit_interval(fraction: float):
    with pytest.raises(ValueError):
        _percentile([1.0, 2.0, 3.0], fraction)


@pytest.mark.parametrize(
    ("values", "percent", "expected"),
    [
        ([1, 2, 3], 50, 2.0),
        ([7], 10, 7.0),
        ([1, 2, 3], 0, 1.0),
        ([1, 2, 3], 100, 3.0),
    ],
)
def test_linear_percentile_returns_float_for_int_input(
    values: list[int], percent: float, expected: float
):
    result = linear_percentile(values, percent)

    assert isinstance(result, float)
    assert result == expected


def test_linear_percentile_returns_float_for_float_input():
    result = linear_percentile([1.0, 2.0], 95)

    assert isinstance(result, float)
    assert result == pytest.approx(1.95)
