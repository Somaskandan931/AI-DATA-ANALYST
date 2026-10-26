# Product Requirements Document (PRD)

## 1. Product overview

**Product name:** AI Data Analyst Agent  
**Version:** 0.1 (foundation draft)  
**Type:** Standalone application with two integrated modules  
**Collaborators:** Somaskandan and Nishi  
**Primary users:** Students, analysts, researchers, and developers who need to explore tabular data or query a database without writing every operation manually.

### Problem

Exploratory data analysis requires repetitive cleaning, profiling, visualization, and interpretation. Database users also need SQL knowledge to answer analytical questions. LLM-generated analysis can be inaccurate, and generated SQL can be incorrect or unsafe if executed without controls.

### Product vision

Let users upload a CSV or select an approved database, ask an analytical question in natural language, and receive reproducible results with visible evidence, explanations, and safety controls.

## 2. Goals

1. Produce deterministic, reproducible profiles for supported CSV datasets.
2. Generate useful analysis plans while restricting execution to reviewed operations.
3. Create charts and reports whose claims are grounded in computed outputs.
4. Translate natural-language questions into validated SQL for an approved schema.
5. Prevent write operations and constrain database resource consumption.
6. Evaluate analytical correctness, execution reliability, latency, and safety using a fixed benchmark.
7. Provide a repeatable local setup, sample dataset, tests, and documented limitations.

## 3. Non-goals for the first release

- Arbitrary execution of LLM-generated Python or shell commands.
- Unrestricted production database access or database write operations.
- Automatic data upload to third-party services without explicit configuration and disclosure.
- Guaranteed causal conclusions from observational data.
- Full support for every SQL dialect, file type, or document database.
- Multi-user enterprise authentication, billing, and cloud deployment before the local MVP is validated.

## 4. Target workflows

### Workflow A: CSV Auto-EDA
1. User uploads a CSV.
2. System validates extension/content, size, encoding, row/column limits, and parsing.
3. System computes a deterministic profile and stores it as structured JSON for the session.
4. User selects or asks for an analysis.
5. The model proposes a structured plan from an allow-list of supported operations.
6. The plan is validated and executed by deterministic code in a constrained process.
7. UI displays results, charts, caveats, and the exact columns/transformations used.
8. User downloads a report containing methods, computed values, and limitations.

### Workflow B: Natural-language-to-SQL
1. User selects a configured local database.
2. System retrieves only approved table names, columns, types, and foreign-key relationships.
3. User submits a natural-language question.
4. Model proposes one SQL query using the supported dialect.
5. Parser and policy layer validate the query and schema references.
6. Query runs using a read-only connection with timeout and row limits.
7. UI shows the SQL, returned rows, assumptions, and a grounded explanation.
8. Unsafe or ambiguous requests are rejected or clarified rather than executed.

## 5. MVP scope and functional requirements

### M1 — Auto-EDA

- **EDA-01:** Accept CSV files only in the MVP.
- **EDA-02:** Enforce configurable file-size, row, column, and execution limits.
- **EDA-03:** Report schema, inferred types, missing values, duplicate rows, cardinality, ranges, descriptive statistics, and candidate outliers.
- **EDA-04:** Preserve the original uploaded data; cleaning operations produce a separate working view and document changes.
- **EDA-05:** Export the profile as JSON.
- **EDA-06:** Support a controlled catalogue of operations: summary statistics, grouped aggregation, correlation, selected distributions, clustering, PCA, and outlier summaries where appropriate.
- **EDA-07:** Require explicit validated parameters for every operation; no arbitrary model-authored code execution.
- **EDA-08:** Generate charts with titles, column names, filters, and transformation details.
- **EDA-09:** Generate a downloadable report with dataset overview, methods, results, charts, warnings, and limitations.
- **EDA-10:** Answer dataset questions using computed profile/analysis artifacts. If the result was not computed, run a supported operation or explain the limitation.

### M2 — Natural-Language-to-SQL

- **SQL-01:** Start with SQLite; isolate dialect-specific behavior for future expansion.
- **SQL-02:** Ingest schema metadata and expose only allow-listed tables and columns to the query planner.
- **SQL-03:** Generate a single read-only SELECT or WITH...SELECT statement.
- **SQL-04:** Reject DDL, DML, multiple statements, disallowed tables/columns, and unsupported constructs.
- **SQL-05:** Bind user-supplied values as parameters rather than interpolating them into SQL.
- **SQL-06:** Execute with a read-only database identity/connection, query timeout, maximum returned rows, and configurable resource safeguards.
- **SQL-07:** Display generated SQL and query results before or alongside explanation.
- **SQL-08:** Handle NULLs, duplicates, joins, grouping, CTEs, and window functions in the test suite.
- **SQL-09:** Ask a clarifying question when a request is ambiguous; refuse unsafe operations.
- **SQL-10:** Log query metadata and validation outcomes without storing secrets or unnecessary sensitive data.

### Shared application

- **APP-01:** Provide a Streamlit interface with distinct Auto-EDA and SQL Analyst workspaces.
- **APP-02:** Show clear errors for invalid files, unsupported operations, SQL validation failures, timeouts, and model errors.
- **APP-03:** Keep model-provider calls behind an interface and validate all model output against typed schemas.
- **APP-04:** Make outputs reproducible where practical by recording dataset fingerprint, operation parameters, library versions, and query text.
- **APP-05:** Provide sample data, expected answers, tests, setup instructions, and an evaluation report.

## 6. Non-functional requirements

- **Correctness:** Facts and numbers shown to users originate from executed code or query results.
- **Security:** Fail closed on invalid plans and unsafe SQL; do not rely on the LLM as the security boundary.
- **Reliability:** Errors must not silently produce fabricated results; operations should have time/resource limits.
- **Maintainability:** Separate UI, orchestration, deterministic analytics, model adapters, SQL policy, and evaluation.
- **Usability:** Show assumptions, warnings, source columns, and the SQL used.
- **Privacy:** Use local sample data by default; document whether prompts or data are sent to any external model provider.
- **Portability:** Support repeatable local setup on Windows, macOS, and Linux where dependencies permit.

## 7. Proposed architecture

`Streamlit UI → application services/orchestrator → deterministic tools + model adapter → validated artifacts/results`

For SQL, use a separate path: `question → schema retriever → model-generated SQL candidate → parser/policy validation → read-only executor → result formatter`.

The model must not call arbitrary system tools. It may select only named operations registered by the application. The security layer, not the prompt, enforces policy.

## 8. Initial data strategy

Begin with one small, fixed, non-sensitive CSV and a small catalogue of questions with independently computed expected answers. Candidate public-style domains include groundwater levels, commodity prices, and electricity demand. **Decision (P0):** the first implementation uses a synthetic, seeded electricity-demand dataset (`data/sample/electricity_demand.csv`, generated by `scripts/generate_fixture.py`). It plants known data-quality cases (missing values, duplicates, outliers) so expected answers are exact and there are no licensing constraints. Expected profile values are computed independently of the application (standard library) and cross-checked with pandas. A real public dataset can be added after P1 passes; do not support multiple datasets before then.

For SQL evaluation, create a small SQLite database with a documented schema and deterministic seed data. Include rows that test NULLs, duplicate values, one-to-many joins, empty result sets, and boundary conditions.

## 9. Evaluation and acceptance criteria

The MVP is accepted only when all of the following are demonstrated:

1. Invalid file types and configured size/shape violations are rejected with useful messages.
2. Profiling output is deterministic on the fixed fixture and matches expected values.
3. Every supported analysis operation has unit tests and validates its parameters.
4. No model-generated arbitrary Python is executed.
5. Every chart and report insight can be traced to a computed artifact.
6. Valid benchmark SQL questions return expected results, comparing result sets rather than SQL string similarity alone.
7. Unsafe SQL test cases are blocked before execution.
8. SQL execution enforces the configured read-only policy, timeout, and row cap.
9. The benchmark reports execution accuracy, result correctness, safety violations, latency, and failures.
10. A new developer can follow the README to set up the project and run tests.

Targets for accuracy and latency will be set after a baseline run on the selected dataset and local hardware. Do not claim a percentage before measuring it.

## 10. Risks and mitigations

- **Hallucinated insights:** ground explanations in structured computed artifacts; show evidence and caveats.
- **Unsafe SQL:** parser plus allow-lists plus read-only access plus resource limits; adversarial tests.
- **Incorrect data-type inference:** show inferred types and allow explicit user overrides in a later iteration.
- **Large or malformed files:** enforce resource limits and fail clearly.
- **Model/provider variability:** version prompts and models; benchmark by model; retain deterministic fallback operations.
- **Scope creep:** complete and evaluate M1 MVP before expanding database support or advanced ML features.

## 11. Milestones

- **P0 — Foundation (complete):** PRD, architecture, repository scaffold, CI, shared `DatasetProfile` contract, fixed sample dataset with expected values.
- **P1 — Data ingestion and profiling:** CSV validation, schema, profile JSON, fixture tests.
- **P2 — Controlled Auto-EDA:** allow-listed operations, charts, report generation.
- **P3 — Grounded dataset chat:** question routing to computed artifacts and approved operations.
- **P4 — Safe Text-to-SQL:** schema retrieval, generation, validation, read-only execution.
- **P5 — Evaluation and integration:** benchmark suite, security tests, latency report, Streamlit integration.
- **P6 — Release readiness:** documentation, clean setup, reproducibility, limitations, demo.

## 12. Decisions to keep configurable

- LLM provider/model.
- File and execution limits.
- Supported SQL dialects beyond SQLite.
- Additional public datasets beyond the synthetic fixture (after P1).
- Numeric acceptance thresholds after baseline measurement.

## 13. Release definition

The first release is a local, single-user research/portfolio MVP. It demonstrates deterministic analytics, grounded explanations, safe SQL execution, benchmark-based evaluation, and documented limitations. It is not represented as production-ready for untrusted public uploads or arbitrary enterprise databases.
