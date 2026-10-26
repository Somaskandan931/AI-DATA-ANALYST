"""Field-by-field comparison of a computed profile against an expected profile.

Counts, inferred types, column names and strings compare exactly. Floats compare with
configurable absolute and relative tolerances. Every mismatch is collected instead of
raising on the first difference.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from ..models import ColumnProfile, DatasetProfile

ProfileValue = str | int | float | None


class Tolerances(BaseModel):
    """Absolute and relative tolerance used for float comparisons."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    absolute: float = Field(default=1e-6, ge=0)
    relative: float = Field(default=0.0, ge=0)


class ProfileMismatch(BaseModel):
    """One differing field, with the expected and actual values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str
    expected: ProfileValue
    actual: ProfileValue


class ProfileComparisonResult(BaseModel):
    """All mismatches found while comparing two profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mismatches: tuple[ProfileMismatch, ...]

    @property
    def matches(self) -> bool:
        return not self.mismatches


def _record(
    mismatches: list[ProfileMismatch],
    field_path: str,
    expected: ProfileValue,
    actual: ProfileValue,
) -> None:
    mismatches.append(ProfileMismatch(field_path=field_path, expected=expected, actual=actual))


def _floats_match(expected: float, actual: float, tolerances: Tolerances) -> bool:
    return math.isclose(
        expected,
        actual,
        rel_tol=tolerances.relative,
        abs_tol=tolerances.absolute,
    )


def _compare_float(
    mismatches: list[ProfileMismatch],
    field_path: str,
    expected: float | None,
    actual: float | None,
    tolerances: Tolerances,
) -> None:
    if expected is None or actual is None:
        if expected != actual:
            _record(mismatches, field_path, expected, actual)
    elif not _floats_match(expected, actual, tolerances):
        _record(mismatches, field_path, expected, actual)


def _compare_range(
    mismatches: list[ProfileMismatch],
    field_path: str,
    expected: float | str | None,
    actual: float | str | None,
    tolerances: Tolerances,
) -> None:
    if expected is None or actual is None:
        if expected != actual:
            _record(mismatches, field_path, expected, actual)
    elif isinstance(expected, int | float) and isinstance(actual, int | float):
        if not _floats_match(float(expected), float(actual), tolerances):
            _record(mismatches, field_path, expected, actual)
    elif expected != actual:
        _record(mismatches, field_path, expected, actual)


def _compare_column(
    mismatches: list[ProfileMismatch],
    index: int,
    expected: ColumnProfile,
    actual: ColumnProfile,
    tolerances: Tolerances,
) -> None:
    path = f"columns[{index}]"
    if actual.name != expected.name:
        _record(mismatches, f"{path}.name", expected.name, actual.name)
        return
    if actual.inferred_type != expected.inferred_type:
        _record(mismatches, f"{path}.inferred_type", expected.inferred_type, actual.inferred_type)
    if actual.missing_count != expected.missing_count:
        _record(mismatches, f"{path}.missing_count", expected.missing_count, actual.missing_count)
    if actual.unique_count != expected.unique_count:
        _record(mismatches, f"{path}.unique_count", expected.unique_count, actual.unique_count)
    _compare_range(mismatches, f"{path}.min", expected.min, actual.min, tolerances)
    _compare_range(mismatches, f"{path}.max", expected.max, actual.max, tolerances)
    _compare_float(mismatches, f"{path}.mean", expected.mean, actual.mean, tolerances)
    _compare_float(mismatches, f"{path}.median", expected.median, actual.median, tolerances)
    _compare_float(mismatches, f"{path}.std", expected.std, actual.std, tolerances)
    _compare_float(mismatches, f"{path}.q1", expected.q1, actual.q1, tolerances)
    _compare_float(mismatches, f"{path}.q3", expected.q3, actual.q3, tolerances)
    if actual.outlier_count != expected.outlier_count:
        _record(
            mismatches,
            f"{path}.outlier_count",
            expected.outlier_count,
            actual.outlier_count,
        )


def compare_profiles(
    actual: DatasetProfile,
    expected: DatasetProfile,
    tolerances: Tolerances | None = None,
) -> ProfileComparisonResult:
    """Compare *actual* with *expected* and return every mismatch."""
    tolerance = Tolerances() if tolerances is None else tolerances
    mismatches: list[ProfileMismatch] = []

    if actual.schema_version != expected.schema_version:
        _record(mismatches, "schema_version", expected.schema_version, actual.schema_version)
    if actual.dataset_fingerprint != expected.dataset_fingerprint:
        _record(
            mismatches,
            "dataset_fingerprint",
            expected.dataset_fingerprint,
            actual.dataset_fingerprint,
        )
    if actual.row_count != expected.row_count:
        _record(mismatches, "row_count", expected.row_count, actual.row_count)
    if actual.column_count != expected.column_count:
        _record(mismatches, "column_count", expected.column_count, actual.column_count)
    if actual.duplicate_row_count != expected.duplicate_row_count:
        _record(
            mismatches,
            "duplicate_row_count",
            expected.duplicate_row_count,
            actual.duplicate_row_count,
        )

    for index in range(max(len(actual.columns), len(expected.columns))):
        path = f"columns[{index}]"
        if index >= len(actual.columns):
            _record(mismatches, f"{path}.name", expected.columns[index].name, None)
        elif index >= len(expected.columns):
            _record(mismatches, f"{path}.name", None, actual.columns[index].name)
        else:
            _compare_column(
                mismatches,
                index,
                expected.columns[index],
                actual.columns[index],
                tolerance,
            )

    return ProfileComparisonResult(mismatches=tuple(mismatches))
