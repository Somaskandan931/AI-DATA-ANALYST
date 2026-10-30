"""Evaluation primitives: benchmarks, typed metrics and result comparison."""

from ai_data_analyst.evaluation.benchmark import (
    CATEGORY_ALIASES,
    REQUIRED_CATEGORIES,
    BenchmarkCase,
    BenchmarkSuite,
    Scalar,
    canonical_category,
    category_counts,
    load_benchmark,
    missing_categories,
)
from ai_data_analyst.evaluation.comparison import (
    ProfileComparisonResult,
    ProfileMismatch,
    Tolerances,
    compare_profiles,
)
from ai_data_analyst.evaluation.report import (
    REPORT_SCHEMA_VERSION,
    CaseFailure,
    DatasetInfo,
    EvaluationReport,
    LatencySummary,
    library_versions,
    ratio_result,
    summarize_latency,
)
from ai_data_analyst.evaluation.results import EvaluationResult
from ai_data_analyst.evaluation.resultset import (
    ResultSetCode,
    ResultSetComparison,
    ResultSetRules,
    compare_result_sets,
)

__all__ = [
    "CATEGORY_ALIASES",
    "REQUIRED_CATEGORIES",
    "BenchmarkCase",
    "BenchmarkSuite",
    "CaseFailure",
    "DatasetInfo",
    "EvaluationReport",
    "EvaluationResult",
    "LatencySummary",
    "ProfileComparisonResult",
    "ProfileMismatch",
    "REPORT_SCHEMA_VERSION",
    "ResultSetCode",
    "ResultSetComparison",
    "ResultSetRules",
    "Scalar",
    "Tolerances",
    "canonical_category",
    "category_counts",
    "compare_profiles",
    "compare_result_sets",
    "library_versions",
    "load_benchmark",
    "missing_categories",
    "ratio_result",
    "summarize_latency",
]
