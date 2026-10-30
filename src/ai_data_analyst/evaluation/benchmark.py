"""Benchmark suite models and loading.

A suite is a versioned list of cases, each with one expected outcome: an allowed
query with its expected columns and rows, a denied query with its reason code, or
a question the system must clarify.

Coverage mapping uses :data:`CATEGORY_ALIASES` before comparing names. Benchmark
files may use their own category names; names with no alias simply count as
"other" rather than against a required category, and :func:`category_counts`
lists every observed name. The alias map is expected to shrink as the SQL owner
adopts the canonical names.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar: TypeAlias = bool | int | float | str | None

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_CODE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

REQUIRED_CATEGORIES: tuple[str, ...] = (
    "simple_filters",
    "aggregation",
    "group_by_having",
    "joins",
    "null_behavior",
    "duplicates",
    "ctes",
    "window_functions",
    "empty_results",
    "ambiguous_wording",
    "disallowed_tables_columns",
    "write_statements",
    "multiple_statements",
    "comments_obfuscation",
    "resource_heavy_queries",
)

# Names used by the existing benchmark file that mean a required category.
CATEGORY_ALIASES: Mapping[str, str] = {
    "basic_filter": "simple_filters",
    "join": "joins",
    "null_values": "null_behavior",
}


def canonical_category(name: str) -> str:
    """Return the canonical category name, or ``name`` when it has no alias."""
    return CATEGORY_ALIASES.get(name, name)


class BenchmarkCase(BaseModel):
    """One benchmark question and the outcome it expects."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(pattern=_ID_PATTERN)
    category: str = Field(pattern=_CODE_PATTERN)
    question: str = Field(min_length=1, max_length=1000)
    reference_sql: str | None = None
    expected_outcome: Literal["allowed", "denied", "clarify"] = "allowed"
    expected_reason_code: str | None = Field(default=None, pattern=_CODE_PATTERN)
    expected_columns: tuple[str, ...] = ()
    expected_rows: tuple[tuple[Scalar, ...], ...] = ()
    order_matters: bool = False

    @model_validator(mode="after")
    def _outcome_consistency(self) -> Self:
        if self.expected_outcome == "allowed":
            if not self.expected_columns:
                raise ValueError("an allowed case needs expected_columns")
            width = len(self.expected_columns)
            for index, row in enumerate(self.expected_rows):
                if len(row) != width:
                    raise ValueError(
                        f"expected_rows[{index}] has {len(row)} values, expected {width}"
                    )
        elif self.expected_outcome == "denied":
            if self.expected_reason_code is None:
                raise ValueError("a denied case needs expected_reason_code")
            if self.expected_columns or self.expected_rows:
                raise ValueError("a denied case carries no expected columns or rows")
        elif self.expected_columns or self.expected_rows:
            raise ValueError("a clarify case carries no expected columns or rows")
        return self


class BenchmarkSuite(BaseModel):
    """A versioned benchmark suite with at least one uniquely identified case."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    benchmark_version: str = Field(min_length=1)
    description: str = ""
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"duplicate case id: {case.id}")
            seen.add(case.id)
        return self


def category_counts(suite: BenchmarkSuite) -> dict[str, int]:
    """Return case counts per canonical category name, sorted by name.

    Aliased names are counted under their canonical name. Names without an alias
    still count as "other" and appear under their own name.
    """
    counts = Counter(canonical_category(case.category) for case in suite.cases)
    return dict(sorted(counts.items()))


def missing_categories(suite: BenchmarkSuite) -> tuple[str, ...]:
    """Return the required categories with no case, in ``REQUIRED_CATEGORIES`` order.

    Aliased names are matched under their canonical name. Names without an alias
    count as "other" and never satisfy a required category.
    """
    present = {canonical_category(case.category) for case in suite.cases}
    return tuple(name for name in REQUIRED_CATEGORIES if name not in present)


def load_benchmark(path: str | Path) -> BenchmarkSuite:
    """Load a UTF-8 JSON benchmark suite."""
    text = Path(path).read_text(encoding="utf-8")
    return BenchmarkSuite.model_validate_json(text)
