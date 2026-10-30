import json
import types
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from ai_data_analyst.evaluation import (
    BenchmarkCase,
    BenchmarkSuite,
    CaseRecord,
    EvaluationRun,
    ExecutionOutcome,
    RunMetadata,
    ValidationOutcome,
    load_benchmark,
    read_run_json,
    run_benchmark,
    write_run_json,
)

ROOT = Path(__file__).resolve().parents[2]
SQL_BENCHMARK = ROOT / "data" / "expected" / "sql_benchmark.json"

STARTED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _metadata(**overrides: object) -> RunMetadata:
    fields: dict[str, object] = {
        "model": "fake-model",
        "provider": "fake-provider",
        "model_version": "1.0",
        "prompt_version": "p1",
    }
    fields.update(overrides)
    return RunMetadata(**fields)


RUN_METADATA = _metadata()


class FakeClock:
    def __init__(self, step: float = 1.0) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        self._now += self._step
        return self._now


class FakeSystem:
    def __init__(self) -> None:
        self.sql: str | None = "SELECT n FROM t"
        self.validation = ValidationOutcome(allowed=True, normalized_sql="SELECT n FROM t")
        self.execution = ExecutionOutcome(columns=("n",), rows=((1,),))
        self.generate_error: Exception | None = None
        self.validate_error: Exception | None = None
        self.execute_error: Exception | None = None
        self.generate_calls = 0
        self.validate_calls = 0
        self.execute_calls = 0

    def generate(self, question: str) -> str | None:
        self.generate_calls += 1
        if self.generate_error is not None:
            raise self.generate_error
        return self.sql

    def validate(self, sql: str) -> ValidationOutcome:
        self.validate_calls += 1
        if self.validate_error is not None:
            raise self.validate_error
        return self.validation

    def execute(self, normalized_sql: str) -> ExecutionOutcome:
        self.execute_calls += 1
        if self.execute_error is not None:
            raise self.execute_error
        return self.execution


class ReferenceSystem:
    """Returns each real case's reference SQL and expected result."""

    def __init__(self, suite: BenchmarkSuite) -> None:
        self._by_question = {case.question: case for case in suite.cases}
        self._by_sql = {case.reference_sql: case for case in suite.cases}

    def generate(self, question: str) -> str | None:
        return self._by_question[question].reference_sql

    def validate(self, sql: str) -> ValidationOutcome:
        return ValidationOutcome(allowed=True, normalized_sql=sql)

    def execute(self, normalized_sql: str) -> ExecutionOutcome:
        case = self._by_sql[normalized_sql]
        return ExecutionOutcome(columns=case.expected_columns, rows=case.expected_rows)


def _case(**overrides: object) -> BenchmarkCase:
    fields: dict[str, object] = {
        "id": "case-1",
        "category": "simple_filters",
        "question": "How many rows are there?",
        "expected_columns": ("n",),
        "expected_rows": ((1,),),
    }
    fields.update(overrides)
    return BenchmarkCase(**fields)


def _denied_case(**overrides: object) -> BenchmarkCase:
    fields: dict[str, object] = {
        "expected_outcome": "denied",
        "expected_reason_code": "unknown_table",
        "expected_columns": (),
        "expected_rows": (),
    }
    fields.update(overrides)
    return _case(**fields)


def _clarify_case(**overrides: object) -> BenchmarkCase:
    fields: dict[str, object] = {
        "expected_outcome": "clarify",
        "expected_columns": (),
        "expected_rows": (),
    }
    fields.update(overrides)
    return _case(**fields)


def _suite(*cases: BenchmarkCase) -> BenchmarkSuite:
    return BenchmarkSuite(benchmark_version="1.0", cases=cases)


def _run(suite, system, *, rules=None, clock=None):
    return run_benchmark(
        suite,
        system,
        rules=rules,
        clock=clock or FakeClock(),
        started_at=STARTED_AT,
        run_metadata=RUN_METADATA,
    )


def _metric(run: EvaluationRun, name: str):
    for result in run.results:
        if result.metric_name == name:
            return result
    raise AssertionError(f"metric {name} is missing")


def _metric_names(run: EvaluationRun) -> set[str]:
    return {result.metric_name for result in run.results}


def test_allowed_case_passes_and_is_timed_per_phase():
    system = FakeSystem()

    run = _run(_suite(_case()), system)

    record = run.records[0]
    assert record.passed
    assert record.observed_outcome == "allowed"
    assert record.reason_codes == ()
    assert record.result_codes == ()
    assert record.generate_ms == pytest.approx(1.0)
    assert record.validate_ms == pytest.approx(1.0)
    assert record.execute_ms == pytest.approx(1.0)
    assert system.generate_calls == 1
    assert system.validate_calls == 1
    assert system.execute_calls == 1
    assert _metric(run, "execution_accuracy").value == 1.0
    assert _metric(run, "query_validation_rate").value == 1.0
    assert run.failures == ()


def test_allowed_case_with_wrong_result_fails():
    system = FakeSystem()
    system.execution = ExecutionOutcome(columns=("n",), rows=((2,),))

    run = _run(_suite(_case()), system)

    assert not run.records[0].passed
    assert run.records[0].observed_outcome == "allowed"
    assert run.records[0].result_codes == ("value_mismatch",)
    assert _metric(run, "execution_accuracy").value == 0.0


def test_denied_case_passes_when_the_reason_matches_and_execute_is_skipped():
    system = FakeSystem()
    system.validation = ValidationOutcome(
        allowed=False,
        reason_codes=("unknown_table",),
    )

    run = _run(_suite(_denied_case()), system)

    record = run.records[0]
    assert record.passed
    assert record.observed_outcome == "denied"
    assert record.reason_codes == ("unknown_table",)
    assert system.validate_calls == 1
    assert system.execute_calls == 0
    assert _metric(run, "denial_accuracy").value == 1.0


def test_denied_case_fails_when_the_reason_differs():
    system = FakeSystem()
    system.validation = ValidationOutcome(
        allowed=False,
        reason_codes=("unknown_table",),
    )

    run = _run(_suite(_denied_case(expected_reason_code="not_select")), system)

    assert not run.records[0].passed
    assert run.records[0].observed_outcome == "denied"
    assert _metric(run, "denial_accuracy").value == 0.0


def test_allowing_a_denied_case_is_a_safety_violation():
    system = FakeSystem()

    run = _run(_suite(_denied_case()), system)

    record = run.records[0]
    assert not record.passed
    assert record.observed_outcome == "allowed"
    assert system.execute_calls == 1
    safety = _metric(run, "safety_violations")
    assert safety.value == 1.0
    assert safety.sample_count == 1


def test_clarify_case_passes_when_generate_returns_none():
    system = FakeSystem()
    system.sql = None

    run = _run(_suite(_clarify_case()), system)

    record = run.records[0]
    assert record.passed
    assert record.observed_outcome == "clarify"
    assert system.generate_calls == 1
    assert system.validate_calls == 0
    assert system.execute_calls == 0
    assert _metric(run, "clarification_accuracy").value == 1.0


def test_clarify_case_fails_when_sql_is_returned():
    system = FakeSystem()

    run = _run(_suite(_clarify_case()), system)

    record = run.records[0]
    assert not record.passed
    assert record.observed_outcome == "allowed"
    assert _metric(run, "clarification_accuracy").value == 0.0


def test_generate_error_is_recorded_without_text_and_skips_later_phases():
    system = FakeSystem()
    system.generate_error = RuntimeError("SECRET-GENERATE")

    run = _run(_suite(_case()), system)

    record = run.records[0]
    assert not record.passed
    assert record.observed_outcome == "error"
    assert record.reason_codes == ("generate_error",)
    assert record.generate_ms is not None
    assert record.validate_ms is None
    assert record.execute_ms is None
    assert system.validate_calls == 0
    assert system.execute_calls == 0
    assert _metric(run, "failure_count").value == 1.0
    assert "SECRET-GENERATE" not in run.model_dump_json()


def test_validate_error_is_recorded_without_text_and_skips_execution():
    system = FakeSystem()
    system.validate_error = RuntimeError("SECRET-VALIDATE")

    run = _run(_suite(_case()), system)

    record = run.records[0]
    assert record.observed_outcome == "error"
    assert record.reason_codes == ("validate_error",)
    assert record.execute_ms is None
    assert system.execute_calls == 0
    assert _metric(run, "failure_count").value == 1.0
    assert _metric(run, "query_validation_rate").value == 0.0
    assert "SECRET-VALIDATE" not in run.model_dump_json()


def test_execute_error_is_recorded_without_text():
    system = FakeSystem()
    system.execute_error = RuntimeError("SECRET-EXECUTE")

    run = _run(_suite(_case()), system)

    record = run.records[0]
    assert record.observed_outcome == "error"
    assert record.reason_codes == ("execute_error",)
    assert record.execute_ms is not None
    assert _metric(run, "failure_count").value == 1.0
    assert _metric(run, "query_validation_rate").value == 1.0
    assert _metric(run, "execution_accuracy").value == 0.0
    assert "SECRET-EXECUTE" not in run.model_dump_json()


def test_timeout_prevents_a_pass_and_is_counted():
    system = FakeSystem()
    system.execution = ExecutionOutcome(columns=("n",), rows=((1,),), timed_out=True)

    run = _run(_suite(_case()), system)

    assert not run.records[0].passed
    assert run.records[0].observed_outcome == "allowed"
    assert _metric(run, "timeout_count").value == 1.0
    assert _metric(run, "truncation_count").value == 0.0
    assert _metric(run, "execution_accuracy").value == 0.0


def test_truncation_is_counted_and_never_matches():
    system = FakeSystem()
    system.execution = ExecutionOutcome(columns=("n",), rows=((1,),), truncated=True)

    run = _run(_suite(_case()), system)

    assert not run.records[0].passed
    assert run.records[0].result_codes == ("truncated",)
    assert _metric(run, "truncation_count").value == 1.0
    assert _metric(run, "timeout_count").value == 0.0


def test_zero_denominator_metrics_are_omitted():
    run = _run(_suite(_case()), FakeSystem())

    names = _metric_names(run)
    assert "execution_accuracy" in names
    assert "query_validation_rate" in names
    assert "denial_accuracy" not in names
    assert "clarification_accuracy" not in names
    assert "safety_violations" not in names
    assert {"failure_count", "timeout_count", "truncation_count"} <= names


def test_latency_summaries_cover_every_phase():
    run = _run(_suite(_case()), FakeSystem())

    assert set(run.latency) == {"generation", "validation", "execution", "total"}
    assert run.latency["generation"].count == 1
    assert run.latency["generation"].median_ms == pytest.approx(1.0)
    assert run.latency["total"].median_ms == pytest.approx(3.0)


def test_phases_that_never_ran_have_zero_count_latency():
    system = FakeSystem()
    system.sql = None

    run = _run(_suite(_clarify_case()), system)

    assert run.latency["generation"].count == 1
    assert run.latency["validation"].count == 0
    assert run.latency["execution"].count == 0
    assert run.latency["total"].count == 0
    assert run.latency["total"].median_ms is None


def test_write_run_json_is_deterministic(tmp_path: Path):
    first = _run(_suite(_case()), FakeSystem())
    second = _run(_suite(_case()), FakeSystem())
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    write_run_json(first, first_path)
    write_run_json(second, second_path)

    first_bytes = first_path.read_bytes()
    assert first_bytes == second_path.read_bytes()
    assert first_bytes.endswith(b"\n")
    assert b"\r" not in first_bytes
    assert json.loads(first_bytes)["schema_version"] == "1.0"


def test_write_run_json_refuses_to_overwrite(tmp_path: Path):
    run = _run(_suite(_case()), FakeSystem())
    path = tmp_path / "run.json"

    write_run_json(run, path)
    with pytest.raises(FileExistsError):
        write_run_json(run, path)

    write_run_json(run, path, overwrite=True)


def test_run_json_round_trip(tmp_path: Path):
    run = _run(_suite(_case()), FakeSystem())
    path = tmp_path / "run.json"

    write_run_json(run, path)

    assert read_run_json(path) == run


def test_run_over_the_real_benchmark_passes_every_allowed_case():
    suite = load_benchmark(SQL_BENCHMARK)

    run = _run(suite, ReferenceSystem(suite))

    assert run.sample_count == len(suite.cases) == 8
    assert all(record.passed for record in run.records)
    assert _metric(run, "execution_accuracy").value == 1.0
    assert run.category_counts == {
        "boundary": 2,
        "duplicates": 1,
        "empty_results": 1,
        "joins": 1,
        "null_behavior": 2,
        "simple_filters": 1,
    }
    assert len(run.missing_categories) == 10


def test_run_rejects_a_naive_started_at():
    with pytest.raises(ValueError):
        run_benchmark(
            _suite(_case()),
            FakeSystem(),
            clock=FakeClock(),
            started_at=datetime(2026, 1, 2, 3, 4, 5),
            run_metadata=RUN_METADATA,
        )


def test_run_rejects_a_non_utc_started_at():
    with pytest.raises(ValueError):
        run_benchmark(
            _suite(_case()),
            FakeSystem(),
            clock=FakeClock(),
            started_at=datetime(
                2026,
                1,
                2,
                3,
                4,
                5,
                tzinfo=timezone(timedelta(hours=2)),
            ),
            run_metadata=RUN_METADATA,
        )


@pytest.mark.parametrize("field_name", ["model", "provider", "model_version", "prompt_version"])
def test_run_metadata_rejects_empty_and_overlong_values(field_name: str):
    with pytest.raises(ValidationError):
        _metadata(**{field_name: ""})
    with pytest.raises(ValidationError):
        _metadata(**{field_name: "x" * 101})


def test_run_metadata_rejects_unsupported_characters():
    with pytest.raises(ValidationError):
        _metadata(model="model@host")


def test_run_metadata_validates_the_database_fingerprint():
    assert _metadata(database_fingerprint="a" * 64).database_fingerprint == "a" * 64
    with pytest.raises(ValidationError):
        _metadata(database_fingerprint="A" * 64)
    with pytest.raises(ValidationError):
        _metadata(database_fingerprint="a" * 63)


def test_case_record_rejects_extra_fields_and_is_frozen():
    record = _run(_suite(_case()), FakeSystem()).records[0]

    with pytest.raises(ValidationError):
        CaseRecord(**record.model_dump(), surprise=True)
    with pytest.raises(ValidationError):
        record.passed = False


def test_evaluation_run_rejects_extra_fields_and_is_frozen():
    run = _run(_suite(_case()), FakeSystem())

    with pytest.raises(ValidationError):
        EvaluationRun(**run.model_dump(), surprise=True)
    with pytest.raises(ValidationError):
        run.sample_count = 0


def test_run_does_not_contain_sql_or_exception_text():
    system = FakeSystem()
    system.sql = "SELECT secret_column FROM secret_table"
    system.validation = ValidationOutcome(
        allowed=True,
        normalized_sql="SELECT secret_column FROM secret_table",
    )
    system.execution = ExecutionOutcome(columns=("other",), rows=((99,),))

    run = _run(_suite(_case()), system)
    payload = run.model_dump_json()

    for sentinel in ("SELECT", "secret_column", "secret_table", "RuntimeError"):
        assert sentinel not in payload


FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "sql",
        "query",
        "text",
        "message",
        "msg",
        "detail",
        "details",
        "error",
        "exception",
        "traceback",
        "params",
        "parameters",
        "value",
        "row",
        "rows",
        "cell",
        "cells",
        "content",
        "contents",
        "data",
        "secret",
        "password",
        "token",
        "api_key",
        "credential",
        "question",
        "prompt",
        "path",
        "filename",
        "file_name",
    }
)


def test_run_and_record_have_no_forbidden_field_names():
    for model in (EvaluationRun, CaseRecord):
        assert set(model.model_fields).isdisjoint(FORBIDDEN_FIELD_NAMES)


def _annotation_involves_str(annotation: object) -> bool:
    if annotation is str:
        return True
    if getattr(annotation, "__metadata__", ()):
        return _annotation_involves_str(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return any(
            _annotation_involves_str(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    if origin is tuple:
        return any(
            _annotation_involves_str(argument)
            for argument in get_args(annotation)
            if argument is not Ellipsis
        )
    return False


def _has_pattern_metadata(metadata: object) -> bool:
    if not isinstance(metadata, (list, tuple)):
        return False
    for item in metadata:
        if getattr(item, "pattern", None) is not None:
            return True
        if _has_pattern_metadata(getattr(item, "metadata", ())):
            return True
    return False


def _is_constrained(annotation: object, field: FieldInfo | None = None) -> bool:
    if field is not None:
        if getattr(field, "pattern", None) is not None:
            return True
        if _has_pattern_metadata(field.metadata):
            return True
    if annotation is str:
        return False
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return True
    if get_origin(annotation) is Literal:
        return True
    metadata = getattr(annotation, "__metadata__", ())
    if metadata:
        if _has_pattern_metadata(metadata):
            return True
        return _is_constrained(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return all(
            _is_constrained(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    if origin is tuple:
        return all(
            _is_constrained(argument)
            for argument in get_args(annotation)
            if argument is not Ellipsis
        )
    return True


def _unconstrained_string_fields(model: type[BaseModel]) -> list[str]:
    return [
        name
        for name, field in model.model_fields.items()
        if _annotation_involves_str(field.annotation)
        and not _is_constrained(field.annotation, field)
    ]


@pytest.mark.parametrize("model", [EvaluationRun, CaseRecord, RunMetadata])
def test_every_string_field_is_constrained(model):
    assert _unconstrained_string_fields(model) == []


def test_guard_rejects_a_new_unconstrained_string_field():
    class UnsafeRecord(BaseModel):
        notes: str

    class UnsafeTupleRecord(BaseModel):
        notes: tuple[str, ...]

    assert _unconstrained_string_fields(UnsafeRecord) == ["notes"]
    assert _unconstrained_string_fields(UnsafeTupleRecord) == ["notes"]
