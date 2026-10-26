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
