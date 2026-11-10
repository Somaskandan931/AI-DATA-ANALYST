"""Deterministic display formatting for UI tables and cards.

Numbers use thousands separators and two decimals; missing values become a dim en dash.
The functions are pure so they can be asserted without Streamlit.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from numbers import Integral, Real
from typing import Any, Final, cast

import pandas as pd
from pandas.io.formats.style import Styler

from .theme.tokens import PALETTE

MISSING: Final = "–"
_MUTED: Final = f"color: {PALETTE.ink_muted}"
# The reporting layer formats numbers to strings before they reach the UI; a plain
# decimal like "1121.197713" is re-rendered with two decimals, while dates, ids and
# text that merely contain digits are left alone.
_DECIMAL_TEXT: Final = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")


def is_missing(value: object) -> bool:
    """True for ``None``, NaN/NA and other pandas-style missing values."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(cast(Any, value)))
    except (TypeError, ValueError):
        return False


def format_cell(value: object) -> str:
    """Format one cell: integers with commas, floats with commas and two decimals."""
    if is_missing(value):
        return MISSING
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Integral):
        return f"{int(value):,}"
    if isinstance(value, Real):
        number = float(value)
        return MISSING if not math.isfinite(number) else f"{number:,.2f}"
    if (
        isinstance(value, str)
        and ("." in value or "e" in value.lower())
        and _DECIMAL_TEXT.match(value)
    ):
        number = float(value)
        return MISSING if not math.isfinite(number) else f"{number:,.2f}"
    return str(value)


def frame_from(
    rows: Iterable[Mapping[str, Any]] | Iterable[Sequence[Any]],
    columns: Sequence[str],
) -> pd.DataFrame:
    """A display frame whose cells are already formatted strings."""
    records: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, Mapping):
            records.append({name: format_cell(row.get(name)) for name in columns})
        else:
            records.append(
                {name: format_cell(value) for name, value in zip(columns, row, strict=False)}
            )
    return pd.DataFrame(records, columns=list(columns))


def columns_frame(data: Mapping[str, Sequence[Any]]) -> pd.DataFrame:
    """A display frame from named columns, formatted cell by cell."""
    return pd.DataFrame(
        {name: [format_cell(value) for value in values] for name, values in data.items()}
    )


def style_missing(frame: pd.DataFrame) -> Styler:
    """Dim every missing-value dash without touching the other cells."""
    return frame.style.map(lambda value: _MUTED if value == MISSING else "")
