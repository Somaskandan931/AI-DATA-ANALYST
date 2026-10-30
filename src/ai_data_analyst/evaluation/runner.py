"""Benchmark runner: time an injected system, score it, and record a run.

The runner never imports ``sql_agent`` or a model provider. The system under test
implements :class:`BenchmarkSystem` and is supplied by the caller.

Per case the runner times generation, validation and execution separately. It
executes only after the validator allows the query, catches exceptions from each
phase and records only a stable code (never the exception text), and compares the
result set for cases that reached execution. A run keeps codes, flags, counts and
timings; it never keeps SQL from the system under test, parameter values or row
contents.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ai_data_analyst.evaluation.benchmark import (
    BenchmarkSuite,
    Scalar,
    category_counts,
    missing_categories,
)
from ai_data_analyst.evaluation.metrics import LatencySummary, summarize_latency
from ai_data_analyst.evaluation.results import EvaluationResult
from ai_data_analyst.evaluation.resultset import (
    ResultSetCode,
    ResultSetRules,
    compare_result_sets,
)

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_CODE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$"
_METADATA_PATTERN = r"^[A-Za-z0-9._:/ -]+$"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"

CaseId: TypeAlias = Annotated[str, Field(pattern=_ID_PATTERN)]
CategoryName: TypeAlias = Annotated[str, Field(pattern=_CODE_PATTERN)]
ReasonCode: TypeAlias = Annotated[str, Field(pattern=_CODE_PATTERN)]
BenchmarkVersion: TypeAlias = Annotated[
    str, Field(min_length=1, max_length=64, pattern=_VERSION_PATTERN)
]
ObservedOutcome: TypeAlias = Literal["allowed", "denied", "clarify", "error"]


class ValidationOutcome(BaseModel):
    """What the validator decided about one generated query."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    allowed: bool
    reason_codes: tuple[ReasonCode, ...] = ()
    normalized_sql: str | None = None


class ExecutionOutcome(BaseModel):
    """What the executor returned for one validated query."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    truncated: bool = False
    timed_out: bool = False


class RunMetadata(BaseModel):
    """Model/provider identity attached to every run."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        protected_namespaces=(),
    )

    model: str = Field(min_length=1, max_length=100, pattern=_METADATA_PATTERN)
    provider: str = Field(min_length=1, max_length=100, pattern=_METADATA_PATTERN)
    model_version: str = Field(min_length=1, max_length=100, pattern=_METADATA_PATTERN)
    prompt_version: str = Field(min_length=1, max_length=100, pattern=_METADATA_PATTERN)
    database_fingerprint: str | None = Field(
        default=None,
        pattern=_FINGERPRINT_PATTERN,
    )


class CaseRecord(BaseModel):
    """The scored outcome of one benchmark case."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    case_id: CaseId
    category: CategoryName
    expected_outcome: Literal["allowed", "denied", "clarify"]
    observed_outcome: ObservedOutcome
    passed: bool
    reason_codes: tuple[ReasonCode, ...] = ()
    result_codes: tuple[ResultSetCode, ...] = ()
    generate_ms: float | None = Field(default=None, ge=0)
    validate_ms: float | None = Field(default=None, ge=0)
    execute_ms: float | None = Field(default=None, ge=0)


class EvaluationRun(BaseModel):
    """A complete, reproducible benchmark run."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["1.0"] = "1.0"
    benchmark_version: BenchmarkVersion
    started_at: AwareDatetime
    run_metadata: RunMetadata
    sample_count: int = Field(ge=0)
    records: tuple[CaseRecord, ...]
    failures: tuple[CaseRecord, ...]
    results: tuple[EvaluationResult, ...]
    latency: dict[str, LatencySummary]
    category_counts: dict[str, int]
    missing_categories: tuple[CategoryName, ...]

    @field_validator("started_at")
    @classmethod
    def _utc_only(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("started_at must be UTC")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.sample_count != len(self.records):
            raise ValueError("sample_count must equal the number of records")
        failed = tuple(record for record in self.records if not record.passed)
        if self.failures != failed:
            raise ValueError("failures must list the failed records in order")
        return self


class BenchmarkSystem(Protocol):
    """The pipeline under test, injected so the runner imports no provider."""

    def generate(self, question: str) -> str | None:
        """Return SQL, or ``None`` when the system asks a clarifying question."""

    def validate(self, sql: str) -> ValidationOutcome:
        """Validate one generated query."""

    def execute(self, normalized_sql: str) -> ExecutionOutcome:
        """Execute the validator's normalized query."""


def run_benchmark(
    suite: BenchmarkSuite,
    system: BenchmarkSystem,
    *,
    rules: ResultSetRules | None = None,
    clock: Callable[[], float] = time.perf_counter,
    started_at: AwareDatetime,
    run_metadata: RunMetadata,
) -> EvaluationRun:
    """Run every case once against ``system`` and return the scored run."""
    if started_at.utcoffset() != timedelta(0):
        raise ValueError("started_at must be UTC")

    benchmark_version = suite.benchmark_version
    records: list[CaseRecord] = []
    generation_samples: list[float] = []
    validation_samples: list[float] = []
    execution_samples: list[float] = []
    total_samples: list[float] = []

    allowed_expected = 0
    allowed_expected_allowed = 0
    allowed_expected_passed = 0
    denied_expected = 0
    denied_correct = 0
    clarify_expected = 0
    clarify_correct = 0
    safety_violations = 0
    errors = 0
    timeouts = 0
    truncations = 0

    for case in suite.cases:
        expected = case.expected_outcome
        if expected == "allowed":
            allowed_expected += 1
        elif expected == "denied":
            denied_expected += 1
        else:
            clarify_expected += 1

        observed: ObservedOutcome = "error"
        passed = False
        reason_codes: tuple[ReasonCode, ...] = ()
        result_codes: tuple[ResultSetCode, ...] = ()
        generate_ms: float | None = None
        validate_ms: float | None = None
        execute_ms: float | None = None

        generated: str | None = None
        generate_started = clock()
        generation_ok = False
        try:
            generated = system.generate(case.question)
            generation_ok = True
        except Exception:
            reason_codes = ("generate_error",)
            errors += 1
        generate_ms = _elapsed(clock(), generate_started)
        generation_samples.append(generate_ms)

        if generation_ok and generated is None:
            observed = "clarify"
            passed = expected == "clarify"
            if passed:
                clarify_correct += 1
        elif generation_ok and generated is not None:
            validation: ValidationOutcome | None = None
            validation_ok = False
            validate_started = clock()
            try:
                validation = system.validate(generated)
                validation_ok = True
            except Exception:
                reason_codes = reason_codes + ("validate_error",)
                errors += 1
            validate_ms = _elapsed(clock(), validate_started)
            validation_samples.append(validate_ms)

            if validation_ok and validation is not None:
                reason_codes = validation.reason_codes
                if validation.allowed:
                    if expected == "allowed":
                        allowed_expected_allowed += 1
                    if expected == "denied":
                        safety_violations += 1
                    execution: ExecutionOutcome | None = None
                    execution_ok = False
                    execute_started = clock()
                    normalized_sql = validation.normalized_sql
                    try:
                        if normalized_sql is None:
                            raise ValueError("an allowed validation needs normalized_sql")
                        execution = system.execute(normalized_sql)
                        execution_ok = True
                    except Exception:
                        reason_codes = reason_codes + ("execute_error",)
                        errors += 1
                    execute_ms = _elapsed(clock(), execute_started)
                    execution_samples.append(execute_ms)

                    if execution_ok and execution is not None:
                        if execution.timed_out:
                            timeouts += 1
                        if execution.truncated:
                            truncations += 1
                        comparison = compare_result_sets(
                            execution.columns,
                            execution.rows,
                            case.expected_columns,
                            case.expected_rows,
                            rules,
                            actual_truncated=execution.truncated,
                        )
                        result_codes = comparison.codes
                        observed = "allowed"
                        passed = (
                            expected == "allowed" and not execution.timed_out and comparison.matches
                        )
                        if passed:
                            allowed_expected_passed += 1
                else:
                    observed = "denied"
                    passed = expected == "denied" and (
                        case.expected_reason_code is None
                        or case.expected_reason_code in reason_codes
                    )
                    if passed:
                        denied_correct += 1

        records.append(
            CaseRecord(
                case_id=case.id,
                category=case.category,
                expected_outcome=expected,
                observed_outcome=observed,
                passed=passed,
                reason_codes=reason_codes,
                result_codes=result_codes,
                generate_ms=generate_ms,
                validate_ms=validate_ms,
                execute_ms=execute_ms,
            )
        )
        if generate_ms is not None and validate_ms is not None and execute_ms is not None:
            total_samples.append(generate_ms + validate_ms + execute_ms)

    results: list[EvaluationResult] = []
    for metric in (
        _ratio_metric(
            "execution_accuracy",
            allowed_expected_passed,
            allowed_expected,
            benchmark_version,
        ),
        _ratio_metric(
            "query_validation_rate",
            allowed_expected_allowed,
            allowed_expected,
            benchmark_version,
        ),
        _ratio_metric("denial_accuracy", denied_correct, denied_expected, benchmark_version),
        _ratio_metric(
            "clarification_accuracy",
            clarify_correct,
            clarify_expected,
            benchmark_version,
        ),
    ):
        if metric is not None:
            results.append(metric)
    if denied_expected:
        results.append(
            _count_metric(
                "safety_violations",
                safety_violations,
                denied_expected,
                benchmark_version,
            )
        )
    results.extend(
        [
            _count_metric("failure_count", errors, len(records), benchmark_version),
            _count_metric("timeout_count", timeouts, len(records), benchmark_version),
            _count_metric("truncation_count", truncations, len(records), benchmark_version),
        ]
    )

    return EvaluationRun(
        benchmark_version=benchmark_version,
        started_at=started_at,
        run_metadata=run_metadata,
        sample_count=len(records),
        records=tuple(records),
        failures=tuple(record for record in records if not record.passed),
        results=tuple(results),
        latency={
            "generation": summarize_latency(generation_samples),
            "validation": summarize_latency(validation_samples),
            "execution": summarize_latency(execution_samples),
            "total": summarize_latency(total_samples),
        },
        category_counts=category_counts(suite),
        missing_categories=missing_categories(suite),
    )


def write_run_json(
    run: EvaluationRun,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> None:
    """Write deterministic UTF-8 JSON with a trailing newline and LF endings."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {target}")
    text = run.model_dump_json(indent=2) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")


def read_run_json(path: str | Path) -> EvaluationRun:
    """Load a run written by :func:`write_run_json`."""
    text = Path(path).read_text(encoding="utf-8")
    return EvaluationRun.model_validate_json(text)


def _elapsed(end: float, start: float) -> float:
    return max(0.0, end - start)


def _ratio_metric(
    name: str,
    numerator: int,
    denominator: int,
    benchmark_version: str,
) -> EvaluationResult | None:
    if denominator == 0:
        return None
    return EvaluationResult(
        metric_name=name,
        value=numerator / denominator,
        sample_count=denominator,
        benchmark_version=benchmark_version,
    )


def _count_metric(
    name: str,
    count: int,
    sample_count: int,
    benchmark_version: str,
) -> EvaluationResult:
    return EvaluationResult(
        metric_name=name,
        value=float(count),
        sample_count=sample_count,
        benchmark_version=benchmark_version,
    )
