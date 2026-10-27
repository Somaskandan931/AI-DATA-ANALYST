"""Deterministic dataset profiling (EDA-03).

Conventions are fixed by ``docs/ARCHITECTURE.md`` and ``data/expected/README.md``: missing
means an empty cell; sample standard deviation (ddof=1); linear-interpolation quartiles;
outliers lie outside ``[q1 - 1.5*IQR, q3 + 1.5*IQR]``; statistics are rounded to 6 decimals.

Type inference looks at the non-missing cells only, in this order:

* ``boolean``: every value is ``true`` or ``false`` (any case). Values such as ``yes``/``no``
  or ``0``/``1`` are deliberately *not* booleans; they stay ``string``/``integer``.
* ``date``: every value is an ISO 8601 calendar date (``YYYY-MM-DD``).
* ``integer``: every value is an optionally signed run of digits.
* ``float``: every value is a plain decimal or scientific number (``nan``/``inf`` excluded).
* ``string``: anything else, including a column with no values at all.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from ..ingestion import IngestedCSV
from ..models import ColumnProfile, DatasetProfile, InferredType

_INTEGER = re.compile(r"[+-]?\d+")
_FLOAT = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BOOLEAN = frozenset({"true", "false"})
_DECIMALS = 6
_IQR_FACTOR = 1.5


def _is_date(text: str) -> bool:
    if not _DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def infer_type(values: Sequence[str]) -> InferredType:
    """Infer a column type from its non-missing string values."""
    if not values:
        return "string"
    if all(v.lower() in _BOOLEAN for v in values):
        return "boolean"
    if all(_is_date(v) for v in values):
        return "date"
    if all(_INTEGER.fullmatch(v) for v in values):
        return "integer"
    if all(_FLOAT.fullmatch(v) for v in values):
        return "float"
    return "string"


def _round(value: float) -> float:
    return round(float(value), _DECIMALS)


def _numeric_profile(
    name: str, kind: InferredType, missing: int, values: Sequence[str]
) -> ColumnProfile:
    numbers = np.array([float(v) for v in values], dtype=np.float64)
    q1, median, q3 = (float(x) for x in np.percentile(numbers, [25, 50, 75]))
    spread = q3 - q1
    low, high = q1 - _IQR_FACTOR * spread, q3 + _IQR_FACTOR * spread
    std = float(np.std(numbers, ddof=1)) if numbers.size > 1 else None
    return ColumnProfile(
        name=name,
        inferred_type=kind,
        missing_count=missing,
        unique_count=int(np.unique(numbers).size),
        min=_round(numbers.min()),
        max=_round(numbers.max()),
        mean=_round(numbers.mean()),
        median=_round(median),
        std=None if std is None else _round(std),
        q1=_round(q1),
        q3=_round(q3),
        outlier_count=int(((numbers < low) | (numbers > high)).sum()),
    )


def _profile_column(name: str, cells: pd.Series) -> ColumnProfile:
    present = [str(v) for v in cells if v is not None]
    missing = len(cells) - len(present)
    kind = infer_type(present)
    if kind in ("integer", "float"):
        return _numeric_profile(name, kind, missing, present)
    unique = len(set(v.lower() for v in present) if kind == "boolean" else set(present))
    low_high = (min(present), max(present)) if kind == "date" else (None, None)
    return ColumnProfile(
        name=name,
        inferred_type=kind,
        missing_count=missing,
        unique_count=unique,
        min=low_high[0],
        max=low_high[1],
    )


def profile_ingested(ingested: IngestedCSV) -> DatasetProfile:
    """Build the :class:`DatasetProfile` for validated CSV content. Never mutates the data."""
    frame = ingested.frame
    columns = tuple(_profile_column(str(name), frame[name]) for name in frame.columns)
    return DatasetProfile(
        dataset_fingerprint=ingested.fingerprint,
        row_count=len(frame),
        column_count=len(columns),
        duplicate_row_count=int(frame.duplicated().sum()),
        columns=columns,
    )
