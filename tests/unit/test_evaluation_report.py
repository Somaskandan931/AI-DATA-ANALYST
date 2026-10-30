import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation import (
    CaseFailure,
    DatasetInfo,
    EvaluationReport,
    library_versions,
    ratio_result,
    summarize_latency,
)


def test_ratio_result_computes_value_and_sample_count() -> None:
    result = ratio_result("coverage", 3, 4, "v1")
    assert result.value == 0.75 and result.sample_count == 4 and result.benchmark_version == "v1"


@pytest.mark.parametrize(("passed", "total"), [(0, 0), (-1, 3), (4, 3)])
def test_ratio_result_rejects_undefined_or_out_of_range(passed: int, total: int) -> None:
    with pytest.raises(ValueError):
        ratio_result("coverage", passed, total, "v1")


def test_latency_summary_uses_median_and_nearest_rank_p95() -> None:
    summary = summarize_latency([float(n) for n in range(1, 101)])
    assert summary.median_ms == 50.5
    assert summary.p95_ms == 95.0  # ceil(0.95 * 100) = rank 95
    assert (summary.min_ms, summary.max_ms, summary.sample_count) == (1.0, 100.0, 100)


def test_latency_summary_single_sample_and_order_independence() -> None:
    assert summarize_latency([7.0]).p95_ms == 7.0
    assert summarize_latency([3.0, 1.0, 2.0]) == summarize_latency([1.0, 2.0, 3.0])


def test_latency_summary_rejects_empty() -> None:
    with pytest.raises(ValueError):
        summarize_latency([])


def test_library_versions_marks_missing_packages() -> None:
    found = library_versions(["pydantic", "definitely-not-a-real-package"])
    assert found["pydantic"] != "not installed"
    assert found["definitely-not-a-real-package"] == "not installed"


def test_report_round_trips_and_forbids_extra_fields() -> None:
    report = EvaluationReport(
        benchmark_version="v1",
        subject="demo",
        method="m",
        dataset=DatasetInfo(name="d.csv", fingerprint="f" * 64, row_count=1, column_count=1),
        environment={"python": "3.12"},
        metrics=(ratio_result("coverage", 1, 2, "v1"),),
        latency={"op": summarize_latency([1.0, 2.0])},
        failures=(CaseFailure(case_id="c1", metric_name="coverage", detail="refused"),),
    )
    assert EvaluationReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        CaseFailure(case_id="c1", metric_name="m", detail="d", extra="x")  # type: ignore[call-arg]
