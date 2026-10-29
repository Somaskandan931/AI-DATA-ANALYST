# m1/analysis-core: clustering, PCA, cleaning view and chart specs

**Branch:** `m1/analysis-core` (off `main` = the uploaded baseline)
**Requirement IDs:** EDA-06 (clustering, PCA), EDA-04 (cleaning view), EDA-08 (chart specs)
**Owner:** Somaskandan (M1) | **Reviewer:** Nishi or Prathin

## What this adds

| Area | Change |
| --- | --- |
| `analysis/plan.py` | `ClusteringParams`, `PcaParams`; `clustering` and `pca` join `OperationName`; column/type and row-count checks in `validate_step` |
| `analysis/operations.py` | k-means and PCA (scikit-learn), `OperationInputError` (fails closed, carries the step index), `execute_plan_on_view` |
| `analysis/cleaning.py` (new) | `CleaningPlan` (`drop_duplicates`, `drop_missing_rows`, `impute` mean/median) applied to a copy; `CleanedView` with log and fingerprint |
| `analysis/artifact.py` | `Provenance.cleaning` (optional, defaults to empty) |
| `visualization/charts.py` (new) | `ChartSpec`, `charts_for_artifacts`, `validate_chart` (traceable by step index and SHA-256 digest) |
| `pyproject.toml` | declares `threadpoolctl`; mypy override for untyped scikit-learn |
| `docs/ARCHITECTURE.md`, `README.md` | updated to match |

## Not in this PR (on purpose)

- **Row filters.** Waiting on the filter contract with Prathin. No filter types or fields were added.
- `AnalysisPlan` / `AnalysisArtifact` stay in `analysis/`; nothing was moved into `models.py`.
- Reporting, grounded chat and chart *rendering* (specs are data only).

## Results

Run on the PR branch (Python 3.12, pandas 3.0.2, numpy 2.4.4, scikit-learn 1.8.0):

- `pytest`: **561 passed** (baseline: 468 passed). New tests: 93.
- `ruff check`, `ruff format --check`, `mypy` (strict, 28 source files): clean.
- `pytest -W error` on the analysis and chart test files: no warnings.

How correctness is checked (independent of the code under test):

- **PCA**: variance, ratios and loadings compared with a numpy `eigh` of the covariance matrix; loadings orthonormal; perfectly correlated columns give one component with ratio 1.0.
- **Clustering**: known blobs (30/20/10 points) are recovered with the expected centroids; inertia and the size of the first cluster are recomputed from the reported centroids on the real sample data.
- **Cleaning**: duplicates removed = the 5 in the expected profile; imputed values equal numpy mean/median of the raw strings; ingested and typed frames are unchanged afterwards.
- **Charts**: values equal the artifact's numbers; edited, relabelled or re-pointed specs raise `ChartTraceError`.
- Reproducibility: same seed gives identical results, also under `threadpool_limits(4)`.

## Review notes (self-review of the diff)

- Fixed during self-review: `execute_plan_on_view` first only compared row counts, so a view from a different dataset with the same row count was accepted. `CleanedView` now carries the dataset fingerprint and is rejected on mismatch (test added).
- `Provenance.rows_in_dataset` now means "rows in the frame the operation ran on (after any cleaning)". Without cleaning it is unchanged. A clearer name would be a contract change, so I left it.
- Resource limits: `k`, column and component counts are bounded by the plan types, rows by the ingestion limit, time by `max_execution_seconds` between steps. A single step is not interrupted. In an informal local run on one core, k=10 on 250,000 rows x 10 columns took about 11 s. That is not a benchmark and no latency claim is made.
- Silhouette is estimated on a fixed-seed sample of 2,000 rows for larger inputs, with a warning, and is `None` when undefined.

## Questions for Prathin

1. Where should `AnalysisPlan` / `AnalysisArtifact` live (stay in `analysis/` or move to `models.py`)? They now include `clustering`, `pca`, and `Provenance.cleaning`; schema version is still `1.0` (additive only).
2. Filter contract: proposed shape is `{column, op, value}` with `op` in `eq, ne, lt, le, gt, ge, in, is_null, not_null`, missing values never matching except `is_null`, validated against column types like the plan. OK to implement that next?
3. Is `rows_in_dataset` fine as redefined above?

## Checklist

- [x] Baseline and uploaded P2 ZIP verified (baseline: 468 tests, ruff, format and mypy green before any change)
- [x] Existing five operations and their tests untouched and green
- [x] Clustering and PCA with validation, limits, reproducibility, edge-case and correctness tests
- [x] EDA-04 cleaning view, raw data never modified
- [x] EDA-08 chart specifications
- [x] ARCHITECTURE.md updated
- [ ] Review feedback addressed (waiting for review)
- [ ] Filter contract and model placement agreed with Prathin
