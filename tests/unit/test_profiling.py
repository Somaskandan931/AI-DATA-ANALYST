"""EDA-03 / EDA-05: profiling is deterministic and matches independently computed values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_data_analyst.evaluation import compare_profiles
from ai_data_analyst.ingestion import load_csv, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import (
    infer_type,
    profile_ingested,
    profile_to_json,
    write_profile_json,
)


def _profile(text: str) -> DatasetProfile:
    return profile_ingested(load_csv(text.encode(), "d.csv"))


def test_sample_profile_matches_independent_expected_values(
    sample_csv_path: Path, expected_profile: dict[str, object]
):
    actual = profile_ingested(load_csv_path(sample_csv_path))
    result = compare_profiles(actual, DatasetProfile.model_validate(expected_profile))
    assert result.mismatches == ()


def test_profiling_is_deterministic(sample_csv_path: Path):
    first = profile_to_json(profile_ingested(load_csv_path(sample_csv_path)))
    second = profile_to_json(profile_ingested(load_csv_path(sample_csv_path)))
    assert first == second


def test_profiling_does_not_modify_ingested_data(sample_csv_path: Path):
    ingested = load_csv_path(sample_csv_path)
    before = ingested.frame.copy(deep=True)
    profile_ingested(ingested)
    assert ingested.frame.equals(before)


def test_json_export_roundtrips_and_matches_expected_file(
    sample_csv_path: Path, expected_profile: dict[str, object], tmp_path: Path
):
    profile = profile_ingested(load_csv_path(sample_csv_path))
    out = tmp_path / "nested" / "profile.json"
    write_profile_json(profile, out)
    assert json.loads(out.read_text(encoding="utf-8")) == expected_profile
    assert DatasetProfile.model_validate_json(out.read_text(encoding="utf-8")) == profile


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "-2", "+3", "007"], "integer"),
        (["1", "2.5"], "float"),
        (["1e3", ".5", "3."], "float"),
        (["2025-01-31", "2024-02-29"], "date"),
        (["2025-02-30"], "string"),
        (["20250131"], "integer"),
        (["True", "false"], "boolean"),
        (["yes", "no"], "string"),
        (["0", "1"], "integer"),
        (["nan"], "string"),
        (["inf", "1"], "string"),
        (["1", "x"], "string"),
        (["1,000"], "string"),
        ([], "string"),
    ],
)
def test_type_inference(values: list[str], expected: str):
    assert infer_type(values) == expected


def test_numeric_statistics_use_documented_conventions():
    column = _profile("x\n1\n2\n3\n4\n100\n").columns[0]
    assert column.inferred_type == "integer"
    assert (column.min, column.max) == (1.0, 100.0)
    assert column.mean == 22.0
    assert column.median == 3.0
    assert (column.q1, column.q3) == (2.0, 4.0)
    assert column.std == pytest.approx(43.617657, abs=1e-6)  # sample std (ddof=1)
    assert column.outlier_count == 1  # 100 > 4 + 1.5 * 2


def test_single_value_numeric_column_has_no_std():
    column = _profile("x\n5\n").columns[0]
    assert column.std is None
    assert column.mean == 5.0
    assert column.outlier_count == 0


def test_all_missing_column_is_string_with_no_statistics():
    profile = _profile("a,b\n1,\n2,\n")
    column = profile.columns[1]
    assert column.inferred_type == "string"
    assert column.missing_count == 2
    assert column.unique_count == 0
    assert column.min is None and column.mean is None


def test_numeric_unique_count_treats_equal_numbers_as_equal():
    assert _profile("x\n1\n1.0\n2\n").columns[0].unique_count == 2


def test_boolean_unique_count_ignores_case():
    column = _profile("x\nTrue\ntrue\nfalse\n").columns[0]
    assert column.inferred_type == "boolean"
    assert column.unique_count == 2


def test_duplicates_count_repeats_not_first_occurrences():
    assert _profile("a,b\n1,x\n1,x\n1,x\n2,y\n").duplicate_row_count == 2


def test_duplicate_rows_with_missing_cells_are_detected():
    assert _profile("a,b\n1,\n1,\n").duplicate_row_count == 1


def test_header_only_file_profiles_to_zero_rows():
    profile = _profile("a,b\n")
    assert profile.row_count == 0
    assert profile.duplicate_row_count == 0
    assert [c.inferred_type for c in profile.columns] == ["string", "string"]


def test_date_range_is_chronological():
    column = _profile("d\n2025-03-01\n2024-12-31\n2025-01-15\n").columns[0]
    assert (column.min, column.max) == ("2024-12-31", "2025-03-01")
