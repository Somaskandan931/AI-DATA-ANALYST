import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation.metrics import LatencySummary, summarize_latency


def test_empty_samples_have_a_zero_count_and_no_values():
    summary = summarize_latency([])

    assert summary.count == 0
    assert summary.median_ms is None
    assert summary.p95_ms is None
    assert summary.max_ms is None


def test_single_sample():
    summary = summarize_latency([7.0])

    assert summary.count == 1
    assert summary.median_ms == 7.0
    assert summary.p95_ms == 7.0
    assert summary.max_ms == 7.0


def test_median_and_p95_use_linear_interpolation():
    summary = summarize_latency([1.0, 2.0, 3.0, 4.0])

    assert summary.count == 4
    assert summary.median_ms == pytest.approx(2.5)
    assert summary.p95_ms == pytest.approx(3.85)
    assert summary.max_ms == 4.0


def test_two_samples_interpolate_p95():
    summary = summarize_latency([1.0, 2.0])

    assert summary.median_ms == pytest.approx(1.5)
    assert summary.p95_ms == pytest.approx(1.95)
    assert summary.max_ms == 2.0


def test_samples_are_sorted_before_summarizing():
    assert summarize_latency([4.0, 1.0, 3.0, 2.0]) == summarize_latency([1.0, 2.0, 3.0, 4.0])


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_samples_are_rejected(value: float):
    with pytest.raises(ValueError):
        summarize_latency([1.0, value])


def test_count_and_values_must_agree():
    with pytest.raises(ValidationError):
        LatencySummary(count=0, median_ms=1.0)

    with pytest.raises(ValidationError):
        LatencySummary(count=2, median_ms=1.0, p95_ms=1.0)

    with pytest.raises(ValidationError):
        LatencySummary(count=2, median_ms=1.0, p95_ms=1.0, max_ms=None)


def test_summary_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        LatencySummary(count=0, surprise=True)

    summary = LatencySummary(count=0)
    with pytest.raises(ValidationError):
        summary.count = 1


def test_summary_json_round_trip():
    summary = summarize_latency([1.0, 2.0, 3.0])

    assert LatencySummary.model_validate_json(summary.model_dump_json()) == summary
