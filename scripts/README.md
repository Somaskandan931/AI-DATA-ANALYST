# Scripts

Repeatable developer scripts. Scripts must not bypass application security controls.

- `generate_fixture.py`: regenerates `data/sample/electricity_demand.csv` and `data/expected/electricity_demand_profile.json` deterministically. Run after any intentional fixture change and commit both outputs; `tests/unit/test_fixture.py` fails if they drift.

- `run_auto_eda_eval.py`: runs the Auto-EDA evaluation (profile correctness, coverage, answer correctness, grounding, refusal, operation reliability, latency) and writes `results/auto_eda_evaluation.json`. Exit code is non-zero if any case fails. Latency depends on the machine, so rerun it where the numbers will be cited.

Planned: SQL benchmark runner, report export.
