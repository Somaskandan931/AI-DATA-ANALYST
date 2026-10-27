# Architecture and Module Boundaries

## Dependency direction

The UI calls application services. Application services orchestrate domain modules. Domain modules do not import Streamlit. Model adapters return typed proposals; deterministic validators decide whether proposals may execute.

## Modules

- `ingestion/`: CSV validation and parsing.
- `profiling/`: deterministic schema and quality profile.
- `analysis/`: allow-listed Pandas/scikit-learn operations.
- `visualization/`: chart specifications and rendering.
- `chat/`: question routing and grounded answer composition.
- `sql_agent/`: schema retrieval, SQL generation interface, validation, execution, and result explanation.
- `security/`: common limits, policy types, and audit events.
- `evaluation/`: benchmark fixtures, scoring, and report generation.
- `reporting/`: reproducible report assembly.
- `ui/`: Streamlit pages and widgets only.

## Key interfaces (planned)

- `DatasetProfile`: versioned structured profile of a dataset.
- `AnalysisPlan`: typed list of allow-listed operations and validated parameters.
- `AnalysisArtifact`: operation, input columns, parameters, result reference, warnings, and provenance.
- `SQLCandidate`: SQL text plus dialect and parameter values.
- `SQLValidationResult`: allow/deny, normalized query metadata, and reasons.
- `EvaluationResult`: metric name, score/value, sample count, and benchmark version.

## Trust boundaries

Treat uploaded files, natural-language questions, model output, schema comments, and database content as untrusted input. Do not treat data or model text as instructions. Validate every boundary with code.

## Shared contract: `DatasetProfile`

Defined in `src/ai_data_analyst/models.py` as a frozen Pydantic model with `schema_version`. Profiling produces it; analysis, chat, reporting and evaluation consume it. Rules:

- `extra="forbid"` so unknown fields fail loudly.
- Any breaking change bumps `PROFILE_SCHEMA_VERSION` and regenerates the expected fixture values.
- Statistical conventions are fixed: sample standard deviation (ddof=1), linear-interpolation quartiles, IQR outlier rule with factor 1.5.

## Module independence

`ingestion/profiling/analysis/visualization/reporting/chat` (M1) and `sql_agent` (M2) must not import each other. Both may import `models`, `security` and `evaluation`.

## M1 analysis contracts: `AnalysisPlan` and `AnalysisArtifact`

Currently defined in `analysis/plan.py` and `analysis/artifact.py` (schema version `1.0`) and
exported from `ai_data_analyst.analysis`. They move to `models.py` once the contracts owner
agrees, since `chat/`, `reporting/` and `evaluation/` consume them.

- `AnalysisPlan`: 1 to 20 steps. Each step is one of the allow-listed operations, selected by
  the `operation` field: `summary_stats`, `grouped_aggregation`, `correlation`, `distribution`,
  `outlier_summary` (clustering and PCA are still to come). Parameters are typed and bounded;
  unknown fields are rejected, and no field carries an expression or code.
- `validate_plan(plan, profile)` checks columns exist and their inferred types suit the
  operation. `execute_plan` validates the whole plan first, so nothing runs on a bad plan, and
  checks `max_execution_seconds` between steps.
- `AnalysisArtifact`: `operation`, `input_columns`, `parameters`, `result` (strict JSON, `None`
  for undefined values), `warnings`, and `provenance` (dataset fingerprint, rows used, library
  versions).
- `typed_frame(ingested, profile)` builds the typed analysis view. It does not clean or impute;
  the cleaning working view (EDA-04) is separate and still to do.
