# Scripts

Repeatable developer scripts. Scripts must not bypass application security controls.

- `generate_fixture.py`: regenerates `data/sample/electricity_demand.csv` and `data/expected/electricity_demand_profile.json` deterministically. Run after any intentional fixture change and commit both outputs; `tests/unit/test_fixture.py` fails if they drift.

Planned: benchmark runner, report export.
