"""Evaluation primitives: typed metrics and profile comparison."""

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

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "CaseFailure",
    "DatasetInfo",
    "EvaluationReport",
    "EvaluationResult",
    "LatencySummary",
    "ProfileComparisonResult",
    "ProfileMismatch",
    "Tolerances",
    "compare_profiles",
    "library_versions",
    "ratio_result",
    "summarize_latency",
]
