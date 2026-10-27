"""Typed, read-only analysis view of ingested data.

``load_csv`` keeps every cell as a string (EDA-04: the upload is preserved). Analysis needs
real types, so :func:`typed_frame` builds a *separate* frame using the types already recorded
in the :class:`~ai_data_analyst.models.DatasetProfile`. It does not clean or impute anything:
missing cells stay missing. Numeric columns (integer and float) become ``float64``.
"""

from __future__ import annotations

import pandas as pd

from ..ingestion import IngestedCSV
from ..models import DatasetProfile


def typed_frame(ingested: IngestedCSV, profile: DatasetProfile) -> pd.DataFrame:
    """Return a new typed frame; *ingested* is not modified."""
    if ingested.fingerprint != profile.dataset_fingerprint:
        raise ValueError("profile does not describe this dataset (fingerprint mismatch)")
    raw = ingested.frame
    columns: dict[str, pd.Series] = {}
    for column in profile.columns:
        cells = raw[column.name]
        match column.inferred_type:
            case "integer" | "float":
                columns[column.name] = pd.to_numeric(cells, errors="raise").astype("float64")
            case "boolean":
                lowered = cells.map(lambda v: None if v is None else str(v).lower() == "true")
                columns[column.name] = lowered.astype("boolean")
            case "date":
                columns[column.name] = pd.to_datetime(cells, format="%Y-%m-%d", errors="raise")
            case "string":
                columns[column.name] = cells.copy()
    return pd.DataFrame(columns)
