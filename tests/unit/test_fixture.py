"""Guards the sample dataset and its independently computed expected profile."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from ai_data_analyst.models import DatasetProfile


def test_generator_is_deterministic_and_matches_committed_files(
    fixture_generator, sample_csv_path: Path, expected_profile_path: Path, tmp_path: Path
):
    csv_out, expected_out = tmp_path / "s.csv", tmp_path / "e.json"
    fixture_generator.build(csv_out, expected_out)
    assert csv_out.read_bytes() == sample_csv_path.read_bytes()
    assert expected_out.read_bytes() == expected_profile_path.read_bytes()


def test_expected_profile_matches_contract_and_fingerprint(expected_profile, sample_csv_path: Path):
    profile = DatasetProfile.model_validate(expected_profile)
    assert profile.dataset_fingerprint == hashlib.sha256(sample_csv_path.read_bytes()).hexdigest()


def test_planted_data_quality_cases_are_present(expected_profile):
    profile = DatasetProfile.model_validate(expected_profile)
    cols = {c.name: c for c in profile.columns}
    assert profile.row_count == 485
    assert profile.duplicate_row_count == 5
    assert cols["temperature_c"].missing_count == 12
    assert cols["demand_mwh"].missing_count == 4
    assert (cols["demand_mwh"].outlier_count or 0) >= 3


def test_expected_values_agree_with_pandas(expected_profile, sample_csv_path: Path):
    """Cross-check the stdlib-computed expectations against pandas (a second, independent tool)."""
    df = pd.read_csv(sample_csv_path)
    profile = DatasetProfile.model_validate(expected_profile)
    assert len(df) == profile.row_count
    assert int(df.duplicated().sum()) == profile.duplicate_row_count
    for col in profile.columns:
        assert int(df[col.name].isna().sum()) == col.missing_count
        assert df[col.name].nunique() == col.unique_count
        if col.inferred_type in ("integer", "float"):
            s = df[col.name]
            assert s.mean() == pytest.approx(col.mean, abs=1e-6)
            assert s.median() == pytest.approx(col.median, abs=1e-6)
            assert s.std() == pytest.approx(col.std, abs=1e-6)
            assert s.quantile(0.25) == pytest.approx(col.q1, abs=1e-6)
            assert s.quantile(0.75) == pytest.approx(col.q3, abs=1e-6)
            iqr = s.quantile(0.75) - s.quantile(0.25)
            low, high = s.quantile(0.25) - 1.5 * iqr, s.quantile(0.75) + 1.5 * iqr
            assert int(((s < low) | (s > high)).sum()) == col.outlier_count
