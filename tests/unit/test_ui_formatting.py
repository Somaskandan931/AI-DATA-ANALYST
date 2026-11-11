"""Display formatting checks: two decimals, thousands separators, no "None"."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("streamlit")

from ai_data_analyst.ui.formatting import (  # noqa: E402
    MISSING,
    columns_frame,
    format_cell,
    frame_from,
    is_missing,
    style_missing,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (485, "485"),
        (1234567, "1,234,567"),
        (0.5, "0.50"),
        (1121.197713, "1,121.20"),
        (2.675, "2.67"),
        (-1234.5, "-1,234.50"),
        (True, "true"),
        (False, "false"),
        ("East", "East"),
        ("2024-01-31", "2024-01-31"),
        ("batch-0042", "batch-0042"),
        ("1121.197713", "1,121.20"),
        ("1,121", "1,121"),
    ],
)
def test_cells_use_two_decimals_and_thousands_separators(value: object, expected: str) -> None:
    assert format_cell(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), -float("inf")],
)
def test_missing_and_non_finite_values_become_a_dash(value: object) -> None:
    assert format_cell(value) == MISSING
    assert "None" not in format_cell(value)


def test_is_missing_recognises_none_nan_and_pandas_na() -> None:
    assert is_missing(None)
    assert is_missing(float("nan"))
    assert not is_missing(0)
    assert not is_missing("")


def test_frames_never_contain_the_word_none() -> None:
    frame = frame_from(
        [{"name": "a", "mean": 12.3456, "note": None}],
        ["name", "mean", "note"],
    )

    assert frame.iloc[0].tolist() == ["a", "12.35", MISSING]
    assert "None" not in frame.to_string()
    assert math.isclose(float(frame.iloc[0, 1].replace(",", "")), 12.35)


def test_columns_frame_and_style_missing_dim_only_dashes() -> None:
    frame = columns_frame({"region": ["East", None], "mean": [1.5, 2.25]})
    styled = style_missing(frame)

    assert frame["region"].tolist() == ["East", MISSING]
    assert frame["mean"].tolist() == ["1.50", "2.25"]
    rendered = styled.to_html()
    assert frame.stack().tolist().count(MISSING) == 1
    assert "color: #5B5F57" in rendered
