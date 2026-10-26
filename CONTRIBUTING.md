# Contributing and collaboration

Two collaborators (Somaskandan and Nishi) build one platform from two independent modules.

## Proposed ownership (adjust together before P1)

| Area | Paths | Owner (proposed)                                           |
| --- | --- |------------------------------------------------------------|
| M1 Auto-EDA | `ingestion/`, `profiling/`, `analysis/`, `visualization/`, `reporting/`, `chat/` | Somaskandan                                                |
| M2 Text-to-SQL | `sql_agent/`, SQL benchmark in `data/expected/` | Nishi                                                      |
| Shared contracts | `models.py`, `security/`, `evaluation/` | Prathin                                                        |
| UI integration | `ui/`, `app.py` | Whoever finishes their module first; reviewed by the other |

`M1` and `M2` must not import each other. They share only `models.py`, `security/` and `evaluation/`.

## Branches and reviews

- `main` is always green. Protect it on GitHub: require a pull request, one approval, and passing CI.
- Branch names: `m1/<topic>`, `m2/<topic>`, `shared/<topic>`, `docs/<topic>`.
- Small pull requests that map to one PRD requirement ID (for example `EDA-03`, `SQL-04`); put the ID in the title.
- A change to `DatasetProfile` or any other shared contract must bump the schema version and update the fixture and its expected values.

## Definition of done for a change

1. Unit tests for new behavior, including rejection and failure paths.
2. `ruff check .`, `ruff format --check .`, `mypy` and `pytest` pass locally.
3. No credentials, raw sensitive data, or generated databases committed.
4. Docs updated if behavior or a contract changed.
5. Security-relevant changes (anything in `security/` or `sql_agent/`) include a test for the unsafe case.

## Rules that are never relaxed

- No model-generated code is executed.
- No raw data is sent to an external model without explicit configuration and disclosure.
- No accuracy or latency claim without the benchmark run that produced it.
