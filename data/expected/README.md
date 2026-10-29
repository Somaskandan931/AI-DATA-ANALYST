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


## SQL benchmark

The M2 text-to-SQL benchmark consists of:

- `sql_benchmark_seed.sql` — deterministic SQLite schema and sample data.
- `sql_benchmark.json` — benchmark questions and expected result sets.
- `tests/sql_agent/test_benchmark_fixtures.py` — automated checks for benchmark structure and seed data (path relative to the repository root).

### Coverage

The benchmark includes:

- Basic filtering
- NULL values
- Duplicate values
- Table joins
- Empty result sets
- Boundary comparisons

### Verification

Expected result sets have been checked against SQLite independently of the SQL generator. The fixture tests verify required coverage, unique case IDs, and the seeded database structure.

**Important:** These fixture tests do not measure model accuracy or latency. Those metrics require the evaluation runner and an actual benchmark run.