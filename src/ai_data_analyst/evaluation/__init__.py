"""Evaluation primitives: typed metrics and profile comparison."""

from ai_data_analyst.evaluation.comparison import (
    ProfileComparisonResult,
    ProfileMismatch,
    Tolerances,
    compare_profiles,
)
from ai_data_analyst.evaluation.results import EvaluationResult

__all__ = [
    "EvaluationResult",
    "ProfileComparisonResult",
    "ProfileMismatch",
    "Tolerances",
    "compare_profiles",
]
