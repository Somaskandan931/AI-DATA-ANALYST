"""Runtime sample-database bootstrap behind the SQL Analyst workspace."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("streamlit")

from ai_data_analyst.ui import sql_analyst  # noqa: E402

EXPECTED_COLUMNS = ["record_id", "date", "region", "demand_mwh", "temperature_c", "holiday"]

SAMPLE_ROWS = (
    "record_id,date,region,demand_mwh,temperature_c,holiday\n"
    "R0001,2025-01-01,North,906.3,14.7,yes\n"
    "R0002,2025-01-01,South,,14.4,no\n"
    "R0003,2025-01-02,North,1001.0,,no\n"
)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "electricity_demand.csv"
    path.write_text(SAMPLE_ROWS, encoding="utf-8")
    return path


def _configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_csv: Path
) -> tuple[Path, Path]:
    repo_db = tmp_path / "repo" / "electricity_demand.db"
    build_dir = tmp_path / "build"
    monkeypatch.setattr(sql_analyst, "SAMPLE_DB", repo_db)
    monkeypatch.setattr(sql_analyst, "SAMPLE_BUILD_DIR", build_dir)
    monkeypatch.setattr(sql_analyst, "SAMPLE_CSV", sample_csv)
    return repo_db, build_dir


def test_ensure_sample_database_builds_from_csv(
    tmp_path: Path, sample_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_db, build_dir = _configure(monkeypatch, tmp_path, sample_csv)

    built = sql_analyst._ensure_sample_database()

    assert built is not None
    assert built.is_file()
    assert built.parent == build_dir
    assert not repo_db.exists()
    assert not list(build_dir.glob("*.tmp"))

    with sqlite3.connect(built) as connection:
        columns = [
            row[1] for row in connection.execute(f'PRAGMA table_info("{sql_analyst.SAMPLE_TABLE}")')
        ]
        assert columns == EXPECTED_COLUMNS
        row_count = connection.execute(
            f'SELECT COUNT(*) FROM "{sql_analyst.SAMPLE_TABLE}"'
        ).fetchone()[0]
        assert row_count > 0
        null_count = connection.execute(
            f'SELECT COUNT(*) FROM "{sql_analyst.SAMPLE_TABLE}" '
            "WHERE demand_mwh IS NULL OR temperature_c IS NULL"
        ).fetchone()[0]
        assert null_count > 0

    modified = built.stat().st_mtime_ns

    assert sql_analyst._ensure_sample_database() == built
    assert built.stat().st_mtime_ns == modified

    uri = f"file:{quote(built.as_posix(), safe='/:')}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        observed = connection.execute(
            f'SELECT COUNT(*) FROM "{sql_analyst.SAMPLE_TABLE}"'
        ).fetchone()[0]

    assert observed == row_count
