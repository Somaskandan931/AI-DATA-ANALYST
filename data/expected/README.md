# Expected results

`electricity_demand_profile.json` is the expected `DatasetProfile` for the sample CSV.

## How it is computed
Computed from the written CSV using only the Python standard library (`csv`, `statistics`),
independent of pandas and of the application's profiling code.

## Comparison rules
- Counts and strings: exact match.
- Floats: compare with absolute tolerance 1e-6 (values are stored rounded to 6 decimals).
- Standard deviation: sample (ddof=1). Quartiles: linear interpolation (pandas default,
  `statistics.quantiles(..., method="inclusive")`).
- Outliers: values outside `[q1 - 1.5*IQR, q3 + 1.5*IQR]`, computed on non-missing values.
- `duplicate_row_count`: rows identical to an earlier row (equals `DataFrame.duplicated().sum()`).
- `dataset_fingerprint`: SHA-256 of the raw file bytes (line endings pinned to LF).
- Missing values: empty cells.

SQL benchmark expected result sets will be added here when P4 starts.
