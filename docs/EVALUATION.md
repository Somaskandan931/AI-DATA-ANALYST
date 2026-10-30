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
