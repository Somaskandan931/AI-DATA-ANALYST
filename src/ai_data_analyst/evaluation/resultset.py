"""Deterministic result-set comparison for benchmark answers.

Comparison rules are explicit rather than implied:

- Column names compare case-insensitively in exact order.
- A truncated actual result never matches.
- ``int`` and ``float`` compare numerically under the tolerances. SQLite has no
  boolean type and returns ``1`` or ``0`` for a boolean expression, so by default
  (``bool_equals_int``) a bool equals the numerically equal number and is
  canonicalized as a number when ordering or de-duplicating rows. With
  ``bool_equals_int=False`` a bool never equals a number.
- ``None`` equals ``None`` only when ``null_equals_null`` is set.
- ``NaN`` and infinities are invalid values, reported as ``invalid_value``.
- Unordered comparison sorts both sides with a deterministic total order (None,
  bool, number, string) and compares pairwise. With a non-zero tolerance this
  can, in rare cases, pair two distinct rows that are closer than the tolerance
  and report a mismatch even though another pairing would have matched.
- With ``duplicates_matter=False`` rows are deduplicated and compared as sets,
  ignoring how often each distinct row occurs.

``examples`` holds 0-based positions of mismatched rows, capped at ten: the
original row index in ordered comparisons, the sorted position in unordered
multiset comparisons, and the index of the first occurrence of an unmatched
distinct row in set comparisons.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from ai_data_analyst.evaluation.benchmark import Scalar

ResultSetCode: TypeAlias = Literal[
    "truncated",
    "column_mismatch",
    "row_count_mismatch",
    "value_mismatch",
    "invalid_value",
]

_CODE_ORDER: dict[ResultSetCode, int] = {
    "truncated": 0,
    "column_mismatch": 1,
    "row_count_mismatch": 2,
    "value_mismatch": 3,
    "invalid_value": 4,
}


class ResultSetRules(BaseModel):
    """Comparison settings for :func:`compare_result_sets`."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    ordered: bool = False
    float_abs_tol: float = Field(default=1e-9, ge=0)
    float_rel_tol: float = Field(default=0.0, ge=0)
    null_equals_null: bool = True
    duplicates_matter: bool = True
    bool_equals_int: bool = True


class ResultSetComparison(BaseModel):
    """Outcome of comparing two result sets, with stable reason codes."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    matches: bool
    codes: tuple[ResultSetCode, ...] = ()
    actual_row_count: int = Field(ge=0)
    expected_row_count: int = Field(ge=0)
    examples: tuple[int, ...] = Field(default=(), max_length=10)


def compare_result_sets(
    actual_columns: Sequence[str],
    actual_rows: Sequence[Sequence[Scalar]],
    expected_columns: Sequence[str],
    expected_rows: Sequence[Sequence[Scalar]],
    rules: ResultSetRules | None = None,
    *,
    actual_truncated: bool = False,
) -> ResultSetComparison:
    """Compare an actual result set with an expected one under ``rules``."""
    effective_rules = rules or ResultSetRules()
    codes: set[ResultSetCode] = set()
    examples: list[int] = []

    if actual_truncated:
        codes.add("truncated")

    columns_match = len(actual_columns) == len(expected_columns) and all(
        actual.casefold() == expected.casefold()
        for actual, expected in zip(actual_columns, expected_columns, strict=True)
    )
    if not columns_match:
        codes.add("column_mismatch")

    invalid = _has_invalid_value(actual_rows) or _has_invalid_value(expected_rows)
    if invalid:
        codes.add("invalid_value")

    if effective_rules.duplicates_matter:
        if len(actual_rows) != len(expected_rows):
            codes.add("row_count_mismatch")
        if columns_match and not invalid:
            _compare_rows(
                actual_rows,
                expected_rows,
                effective_rules,
                codes,
                examples,
            )
    else:
        actual_unique = _unique_rows(actual_rows, effective_rules)
        expected_unique = _unique_rows(expected_rows, effective_rules)
        if len(actual_unique) != len(expected_unique):
            codes.add("row_count_mismatch")
        if columns_match and not invalid:
            _compare_unique_rows(
                actual_unique,
                expected_unique,
                effective_rules,
                codes,
                examples,
            )

    return ResultSetComparison(
        matches=not codes,
        codes=tuple(sorted(codes, key=lambda code: _CODE_ORDER[code])),
        actual_row_count=len(actual_rows),
        expected_row_count=len(expected_rows),
        examples=tuple(examples[:10]),
    )


def _compare_rows(
    actual_rows: Sequence[Sequence[Scalar]],
    expected_rows: Sequence[Sequence[Scalar]],
    rules: ResultSetRules,
    codes: set[ResultSetCode],
    examples: list[int],
) -> None:
    if rules.ordered:
        pairs = list(zip(actual_rows, expected_rows, strict=False))
    else:
        pairs = list(
            zip(
                sorted(actual_rows, key=lambda row: _row_order_key(row, rules)),
                sorted(expected_rows, key=lambda row: _row_order_key(row, rules)),
                strict=False,
            )
        )
    for index, (actual_row, expected_row) in enumerate(pairs):
        if not _rows_equal(actual_row, expected_row, rules):
            codes.add("value_mismatch")
            examples.append(index)


def _compare_unique_rows(
    actual_rows: Sequence[tuple[int, Sequence[Scalar]]],
    expected_rows: Sequence[tuple[int, Sequence[Scalar]]],
    rules: ResultSetRules,
    codes: set[ResultSetCode],
    examples: list[int],
) -> None:
    unmatched = [row for _, row in expected_rows]
    for original_index, actual_row in actual_rows:
        matched = next(
            (
                position
                for position, expected_row in enumerate(unmatched)
                if _rows_equal(actual_row, expected_row, rules)
            ),
            None,
        )
        if matched is None:
            codes.add("value_mismatch")
            examples.append(original_index)
        else:
            unmatched.pop(matched)


def _unique_rows(
    rows: Sequence[Sequence[Scalar]],
    rules: ResultSetRules,
) -> list[tuple[int, Sequence[Scalar]]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique: list[tuple[int, Sequence[Scalar]]] = []
    for index, row in enumerate(rows):
        key = _canonical_row(row, rules)
        if key in seen:
            continue
        seen.add(key)
        unique.append((index, row))
    unique.sort(key=lambda item: _row_order_key(item[1], rules))
    return unique


def _rows_equal(
    actual: Sequence[Scalar],
    expected: Sequence[Scalar],
    rules: ResultSetRules,
) -> bool:
    return len(actual) == len(expected) and all(
        _values_equal(actual_value, expected_value, rules)
        for actual_value, expected_value in zip(actual, expected, strict=True)
    )


def _values_equal(
    actual: Scalar,
    expected: Scalar,
    rules: ResultSetRules,
) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None and rules.null_equals_null
    if isinstance(actual, bool) or isinstance(expected, bool):
        if rules.bool_equals_int:
            if isinstance(actual, bool) and isinstance(expected, (int, float)):
                return _numbers_close(float(actual), expected, rules)
            if isinstance(expected, bool) and isinstance(actual, (int, float)):
                return _numbers_close(actual, float(expected), rules)
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return _numbers_close(actual, expected, rules)
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    return False


def _numbers_close(
    actual: int | float,
    expected: int | float,
    rules: ResultSetRules,
) -> bool:
    try:
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=rules.float_rel_tol,
            abs_tol=rules.float_abs_tol,
        )
    except OverflowError:
        return actual == expected


def _has_invalid_value(rows: Sequence[Sequence[Scalar]]) -> bool:
    return any(
        isinstance(value, float) and not math.isfinite(value) for row in rows for value in row
    )


def _row_order_key(
    row: Sequence[Scalar],
    rules: ResultSetRules,
) -> tuple[tuple[int, float | str], ...]:
    return tuple(_order_key(value, rules) for value in row)


def _order_key(value: Scalar, rules: ResultSetRules) -> tuple[int, float | str]:
    if value is None:
        return (0, 0.0)
    if isinstance(value, bool) and not rules.bool_equals_int:
        return (1, float(value))
    if isinstance(value, (int, float)):
        return (2, _as_float(value))
    return (3, value)


def _as_float(value: int | float) -> float:
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def _canonical_row(
    row: Sequence[Scalar],
    rules: ResultSetRules,
) -> tuple[tuple[str, str], ...]:
    return tuple(_canonical_value(value, rules) for value in row)


def _canonical_value(value: Scalar, rules: ResultSetRules) -> tuple[str, str]:
    if value is None:
        return ("none", "")
    if isinstance(value, bool) and not rules.bool_equals_int:
        return ("bool", "1" if value else "0")
    if isinstance(value, (int, float)):
        number = _as_float(value)
        if number == 0:
            number = 0.0
        return ("number", repr(number))
    return ("string", value)
