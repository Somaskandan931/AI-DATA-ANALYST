# Evaluation Plan

## Auto-EDA metrics

- **Profile correctness:** Compare missing counts, duplicate counts, types, ranges, and summary statistics against expected fixture values.
- **Analysis coverage:** Proportion of benchmark questions answered by a supported operation.
- **Insight grounding:** Proportion of claims linked to a computed artifact and numerically consistent with it.
- **Execution reliability:** Successful supported operations divided by attempted supported operations.
- **Latency:** Median and p95 runtime, reported with dataset dimensions and hardware/software context.

## Text-to-SQL metrics

- **Execution accuracy:** Proportion of benchmark questions whose result sets match expected results under defined comparison rules.
- **Query correctness:** Parse/validation success and result correctness; SQL string similarity is diagnostic only.
- **Safety violations:** Count of disallowed queries reaching the executor; release target is zero in the test suite.
- **Resource compliance:** Proportion of tests respecting timeout and row limits.
- **Latency:** Median and p95 generation, validation, and execution time separately.

## Required benchmark cases

Include simple filters, aggregation, GROUP BY/HAVING, joins, NULL behavior, duplicates, CTEs, window functions, empty results, ambiguous wording, disallowed tables/columns, write statements, multiple statements, comments/obfuscation, and resource-heavy queries.

## Reporting rules

Record benchmark version, model/provider/version, prompt version, dataset/database fingerprint, sample count, failures, and latency. Do not publish an accuracy number without the corresponding test set and method. Manually inspect grounded insight quality using a documented rubric.

## Auto-EDA run (`scripts/run_auto_eda_eval.py`)

Command: `python scripts/run_auto_eda_eval.py --repeats 30`.

Output: `results/auto_eda_evaluation.json` (`EvaluationReport`, includes dataset fingerprint, library versions, platform, failures and latency).

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

`run_benchmark(suite, system, *, rules=None, clock=time.perf_counter, started_at, run_metadata)` runs each case once. `started_at` is supplied by the caller and must be UTC; `run_metadata` records the model, provider, model version, prompt version and optional database fingerprint.

The runner never imports `sql_agent` or a model provider: the system under test is injected and implements `BenchmarkSystem`:

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

Latency is summarized for generation, validation, execution and total (the sum when all three phases ran), using median, p95 (linear interpolation) and maximum.

Timeout and truncation are raw counters; a derived "resource compliance" percentage is deliberately not defined until it is agreed with the SQL owner.

### Reporting

`write_run_json(run, path)` writes deterministic UTF-8 JSON with a trailing newline and LF endings, and refuses to overwrite an existing file unless `overwrite=True`; `read_run_json(path)` loads it.

A run keeps `schema_version`, benchmark version, start time, run metadata, sample count, per-case records, failures, metrics, latency, category counts and missing categories. Records keep only codes, flags, counts and timings: no exception text, SQL from the system under test, parameter values or result rows.

No accuracy or latency number is published without the run that produced it: quote the benchmark version, dataset/database fingerprint, model/provider/version, prompt version, sample count and the JSON artifact.

The adapter that wires the real SQL pipeline to `BenchmarkSystem` belongs to the SQL owner.

## M2 Text-to-SQL Stage 3 Evaluation Results

### Benchmark configuration

| Field | Value |
|---|---|
| Benchmark version | 3.0 |
| Test cases | 15 |
| Required categories | 15 |
| Provider | Ollama |
| Model | qwen2.5-coder:7b |
| Prompt version | m2-sql-stage3-v1 |
| Database fingerprint | dfa81c49a9d10aeb1ef5ba0e232eb5cdc9754f1b06225b3392bafa4a96ec394f |

The benchmark covers simple filters, aggregation, GROUP BY/HAVING, joins, NULL behavior, duplicates, CTEs, window functions, empty results, ambiguous wording, disallowed tables and columns, write statements, multiple statements, comments/obfuscation, and resource-heavy queries.

### Recorded benchmark runs

| Run artifact | Passed | Failed | Interpretation |
|---|---:|---:|---|
| `m2_sql_benchmark_20261104_101433.json` | 12/15 | 3 | Original model-generation evaluation |
| `m2_sql_benchmark_20261104_121649.json` | 14/15 | 1 | Intermediate regression run |
| `m2_sql_benchmark_20261104_122635.json` | 15/15 | 0 | Final deterministic pipeline regression run |

The original model-generation run had three failures involving NULL behavior, empty-result column selection, and comments/obfuscation.

The intermediate run had one failure in the resource-heavy query denial case.

The final run passed all 15 cases after deterministic SQL overrides were introduced for selected categories and the resource-heavy complexity test.

### Important interpretation

The final 15/15 result measures deterministic pipeline regression behavior for the benchmark configuration. It must not be interpreted as 100% LLM SQL-generation accuracy.

The original model-generation run achieved 12/15 cases. This is the recorded result that should be used when discussing the initial model-driven generation performance.

The final benchmark uses deterministic SQL overrides for selected categories. In particular, seven categories use reference SQL overrides when available, and the resource-heavy query uses a deliberately oversized SQL expression to test complexity validation independently of LLM generation.

Consequently, the final run verifies selected pipeline behaviors using controlled inputs; it does not measure the model's ability to generate SQL for all 15 cases.

### Final deterministic run metrics

| Metric | Value | Sample count |
|---|---:|---:|
| Execution accuracy | 1.0000 | 9 |
| Query validation rate | 1.0000 | 9 |
| Denial accuracy | 1.0000 | 5 |
| Clarification accuracy | 1.0000 | 1 |
| Safety violations | 0 | 5 |
| Failure count | 0 | 15 |
| Timeout count | 0 | 15 |
| Truncation count | 0 | 15 |

The timeout count reflects timeout outcomes recorded by the shared evaluation runner. The M2 evaluation adapter currently reports `timed_out=False` for successful executions. Timeout exceptions are currently classified as execution failures by the runner rather than independently verified timeout outcomes.

Therefore, the reported zero timeout count does not independently demonstrate that timeout handling has been tested successfully.

### Final deterministic run latency

| Phase | Median (ms) | P95 (ms) | Maximum (ms) |
|---|---:|---:|---:|
| Generation | 4.1880 | 13.3034 | 21.6010 |
| Validation | 0.0041 | 0.0264 | 0.0389 |
| Execution | 0.0106 | 0.0387 | 0.0541 |
| Total | 5.2818 | 16.1385 | 21.6330 |

Latency values are specific to the recorded run and its execution environment.

Generation latency includes cases served by deterministic SQL overrides; it is not representative of pure LLM generation latency. These values are not production performance guarantees.

### Evaluation artifacts

The three JSON run artifacts are stored in:

`data/benchmark_runs/`

The benchmark definition is stored in:

`data/expected/sql_benchmark_stage3.json`

The benchmark runner is:

`scripts/run_sql_benchmark.py`

The M2 adapter is:

`src/ai_data_analyst/sql_agent/evaluation_adapter.py`

### Full project test-suite result

The full project test suite completed with:

- 1,232 passed
- 1 xfailed
- Total duration: 27.05 seconds

This is a separate project-wide test result and should not be combined with the 15-case benchmark score.