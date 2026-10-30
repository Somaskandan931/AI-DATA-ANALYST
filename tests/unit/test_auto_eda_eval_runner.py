"""The Auto-EDA runner must pass on the sample data AND fail when something is wrong."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_auto_eda_eval", ROOT / "scripts" / "run_auto_eda_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _metrics(report) -> dict[str, float]:  # type: ignore[no-untyped-def]
    return {m.metric_name: m.value for m in report.metrics}


def test_runner_passes_on_the_sample_dataset(runner: ModuleType) -> None:
    report = runner.run(repeats=1)
    assert report.failures == ()
    assert set(_metrics(report).values()) == {1.0}
    assert report.dataset.row_count == 485 and report.dataset.column_count == 6
    assert {"load_and_profile", "chat_answer", "op_pca"} <= set(report.latency)
    assert report.environment["repeats"] == "1"


def test_runner_covers_every_allow_listed_operation(runner: ModuleType) -> None:
    from ai_data_analyst.analysis import OPERATIONS

    assert {step.operation for step in runner.operation_steps()} == set(OPERATIONS)


def test_runner_detects_a_wrong_expected_profile(
    runner: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = json.loads(runner.EXPECTED_PROFILE.read_text(encoding="utf-8"))
    data["row_count"] += 1
    data["columns"][3]["mean"] += 1.0
    broken = tmp_path / "profile.json"
    broken.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(runner, "EXPECTED_PROFILE", broken)
    report = runner.run(repeats=1)
    metrics = _metrics(report)
    assert metrics["profile_exact_match"] == 0.0
    assert metrics["profile_field_accuracy"] < 1.0
    assert {f.case_id for f in report.failures} >= {"row_count", "columns[3].mean"}


def test_runner_detects_a_wrong_expected_answer(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = runner.in_scope_cases

    def wrong(raw):  # type: ignore[no-untyped-def]
        cases = original(raw)
        first = cases[0]
        cases[0] = runner.Case(first.case_id, first.question, first.status, (999999.0,))
        return cases

    monkeypatch.setattr(runner, "in_scope_cases", wrong)
    report = runner.run(repeats=1)
    assert _metrics(report)["answer_correctness"] < 1.0
    assert any(f.case_id == "in-01" for f in report.failures)


def test_runner_counts_an_answered_out_of_scope_question(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "OUT_OF_SCOPE", ("How many rows are there?",))
    report = runner.run(repeats=1)
    assert _metrics(report)["out_of_scope_refusal"] == 0.0
    assert any(f.metric_name == "out_of_scope_refusal" for f in report.failures)


def test_runner_rejects_non_positive_repeats(runner: ModuleType) -> None:
    with pytest.raises(ValueError):
        runner.run(repeats=0)


def test_main_writes_a_valid_report_and_returns_zero(runner: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "report.json"
    assert runner.main(["--repeats", "1", "--output", str(out)]) == 0
    from ai_data_analyst.evaluation import EvaluationReport

    report = EvaluationReport.model_validate_json(out.read_text(encoding="utf-8"))
    assert report.subject == "auto-eda" and report.benchmark_version == runner.BENCHMARK_VERSION
