"""Shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def sample_csv_path() -> Path:
    return ROOT / "data" / "sample" / "electricity_demand.csv"


@pytest.fixture(scope="session")
def expected_profile_path() -> Path:
    return ROOT / "data" / "expected" / "electricity_demand_profile.json"


@pytest.fixture(scope="session")
def expected_profile(expected_profile_path: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(expected_profile_path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="session")
def fixture_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_fixture", ROOT / "scripts" / "generate_fixture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
