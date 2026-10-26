import pytest
from pydantic import ValidationError

from ai_data_analyst.models import PROFILE_SCHEMA_VERSION, ColumnProfile, DatasetProfile


def _column(name: str = "a") -> ColumnProfile:
    return ColumnProfile(name=name, inferred_type="string", missing_count=0, unique_count=1)


def test_profile_defaults_to_current_schema_version():
    profile = DatasetProfile(
        dataset_fingerprint="x",
        row_count=1,
        column_count=1,
        duplicate_row_count=0,
        columns=[_column()],
    )
    assert profile.schema_version == PROFILE_SCHEMA_VERSION


def test_column_count_must_match_columns():
    with pytest.raises(ValidationError):
        DatasetProfile(
            dataset_fingerprint="x",
            row_count=1,
            column_count=2,
            duplicate_row_count=0,
            columns=[_column()],
        )


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ColumnProfile(name="a", inferred_type="string", missing_count=0, unique_count=1, surprise=1)
