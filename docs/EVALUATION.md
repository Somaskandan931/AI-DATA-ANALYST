# Evaluation Plan

## Auto-EDA metrics

- **Profile correctness:** compare missing counts, duplicate counts, types, ranges, and summary statistics against expected fixture values.
- **Analysis coverage:** proportion of benchmark questions answered by a supported operation.
- **Insight grounding:** proportion of claims linked to a computed artifact and numerically consistent with it.
- **Execution reliability:** successful supported operations divided by attempted supported operations.
- **Latency:** median and p95 runtime, reported with dataset dimensions and hardware/software context.

## Text-to-SQL metrics

- **Execution accuracy:** proportion of benchmark questions whose result sets match expected results under defined comparison rules.
- **Query correctness:** parse/validation success and result correctness; SQL string similarity is diagnostic only.
- **Safety violations:** count of disallowed queries reaching the executor; release target is zero in the test suite.
- **Resource compliance:** proportion of tests respecting timeout and row limits.
- **Latency:** median and p95 generation, validation, and execution time separately.

## Required benchmark cases

Include simple filters, aggregation, GROUP BY/HAVING, joins, NULL behavior, duplicates, CTEs, window functions, empty results, ambiguous wording, disallowed tables/columns, write statements, multiple statements, comments/obfuscation, and resource-heavy queries.

## Reporting rules

Record benchmark version, model/provider/version, prompt version, dataset/database fingerprint, sample count, failures, and latency. Do not publish an accuracy number without the corresponding test set and method. Manually inspect grounded insight quality using a documented rubric.

## Auto-EDA run (`scripts/run_auto_eda_eval.py`)

Command: `python scripts/run_auto_eda_eval.py --repeats 30`. Output: `results/auto_eda_evaluation.json` (`EvaluationReport`, includes dataset fingerprint, library versions, platform, failures and latency).

| Metric | Definition |
| --- | --- |
| `profile_exact_match`, `profile_field_accuracy` | Computed profile vs `data/expected/electricity_demand_profile.json` via `compare_profiles` (field accuracy counts 5 dataset fields + 12 per column). |
| `analysis_coverage` | In-scope questions answered (not refused) / in-scope questions (19). |
| `answer_correctness` | Answered in-scope questions whose shown numbers contain every expected value (relative tolerance 1e-6), expected values computed from the raw CSV with pandas/scipy. |
| `insight_grounding` | Answers with evidence and no number outside that evidence / answered questions. |
| `out_of_scope_refusal` | Out-of-scope questions (12) refused with no evidence and no artifact. |
| `execution_reliability` | Each of the 7 allow-listed operations run as a one-step plan / operations attempted. |
| Latency | One untimed warm-up, then N timed runs; median and nearest-rank p95. |

Limits of this run: one small synthetic dataset (485 rows x 6 columns); rule-based routing only, no model proposer; questions were written by the same team that wrote the router, so 1.0 means "no known regression", not general accuracy; latency is for the machine that ran it. Insight quality still needs the manual rubric review required above. The runner's own tests (`tests/unit/test_auto_eda_eval_runner.py`) check that it reports failures when the expected profile or answer is wrong.

## Benchmark runner (`evaluation/runner.py`)

`run_benchmark(suite, system, *, rules=None, clock=time.perf_counter, started_at, run_metadata)` runs each case once. `started_at` is supplied by the caller and must be UTC; `run_metadata` records the model, provider, model version, prompt version and optional database fingerprint. The runner never imports `sql_agent` or a model provider: the system under test is injected and implements `BenchmarkSystem`:

- `generate(question) -> str | None` — SQL, or `None` when the system asks a clarifying question.
- `validate(sql) -> ValidationOutcome` — allow/deny with reason codes and the normalized SQL.
- `execute(normalized_sql) -> ExecutionOutcome` — columns, rows, truncation and timeout flags.

Each phase is timed separately. Execution is called only after validation allows the query. Exceptions from any phase become a case failure with the code `generate_error`, `validate_error` or `execute_error`; the exception text is never stored.

### Metrics

Counts are reported as `EvaluationResult.value` equal to the count; ratios use the case denominator below as `sample_count`. A metric with a zero denominator is omitted rather than reported as 0 or 1.

| Metric | Definition | Denominator |
| --- | --- | --- |
| `execution_accuracy` | Allowed-expected cases that passed (validation allowed, execution did not time out, result set matched) | Allowed-expected cases |
| `query_validation_rate` | Allowed-expected cases the validator allowed, whether or not execution succeeded | Allowed-expected cases |
| `denial_accuracy` | Denied-expected cases the validator denied, with the expected reason code among the observed codes when one is set | Denied-expected cases |
| `clarification_accuracy` | Clarify-expected cases where `generate` returned `None` | Clarify-expected cases |
| `safety_violations` | Denied-expected cases the validator allowed (target 0; no percentage is derived) | Denied-expected cases |
| `failure_count` | Cases where a phase raised an exception | All cases |
| `timeout_count` | Executions that timed out | All cases |
| `truncation_count` | Executions that were truncated | All cases |

Latency is summarized for generation, validation, execution and total (the sum when all three phases ran), using median, p95 (linear interpolation) and maximum. Timeout and truncation are raw counters; a derived "resource compliance" percentage is deliberately not defined until it is agreed with the SQL owner.

### Reporting

`write_run_json(run, path)` writes deterministic UTF-8 JSON with a trailing newline and LF endings, and refuses to overwrite an existing file unless `overwrite=True`; `read_run_json(path)` loads it. A run keeps `schema_version`, benchmark version, start time, run metadata, sample count, per-case records, failures, metrics, latency, category counts and missing categories. Records keep only codes, flags, counts and timings: no exception text, SQL from the system under test, parameter values or result rows.

No accuracy or latency number is published without the run that produced it: quote the benchmark version, dataset/database fingerprint, model/provider/version, prompt version, sample count and the JSON artifact.

The adapter that wires the real SQL pipeline to `BenchmarkSystem` belongs to the SQL owner.
