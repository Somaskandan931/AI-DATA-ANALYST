"""Generate the synthetic electricity-demand fixture and its expected profile.

Fully deterministic (fixed seed). The expected profile is computed from the written CSV with
only the standard library (csv/statistics), so it is independent of pandas and of the
application's own profiling code.

Usage:  python scripts/generate_fixture.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

SEED = 20260101
ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "sample" / "electricity_demand.csv"
EXPECTED_PATH = ROOT / "data" / "expected" / "electricity_demand_profile.json"

HEADER = ["record_id", "date", "region", "demand_mwh", "temperature_c", "holiday"]
REGIONS = {"North": 950.0, "South": 1200.0, "East": 800.0, "West": 1050.0}
N_DAYS = 120
START = date(2025, 1, 1)
HOLIDAY_DAYS = {0, 25, 72, 107}
N_MISSING_TEMPERATURE = 12
N_MISSING_DEMAND = 4
N_OUTLIERS = 3
N_DUPLICATES = 5
OUTLIER_FACTOR = 3.5
PROFILE_SCHEMA_VERSION = "1.0"


def build_rows() -> list[list[str]]:
    rng = random.Random(SEED)
    rows: list[list[str]] = []
    n = 0
    for day in range(N_DAYS):
        for region, base in REGIONS.items():
            n += 1
            holiday = day in HOLIDAY_DAYS
            seasonal = 1 + 0.15 * math.sin(2 * math.pi * day / 365)
            demand = base * seasonal * (0.92 if holiday else 1.0) + rng.gauss(0, 40)
            temp = 22 + 8 * math.sin(2 * math.pi * (day - 80) / 365) + rng.gauss(0, 2.5)
            rows.append(
                [
                    f"R{n:04d}",
                    (START + timedelta(days=day)).isoformat(),
                    region,
                    f"{demand:.1f}",
                    f"{temp:.1f}",
                    "yes" if holiday else "no",
                ]
            )

    picks = rng.sample(range(len(rows)), N_MISSING_TEMPERATURE + N_MISSING_DEMAND + N_OUTLIERS)
    temp_missing = picks[:N_MISSING_TEMPERATURE]
    demand_missing = picks[N_MISSING_TEMPERATURE : N_MISSING_TEMPERATURE + N_MISSING_DEMAND]
    outliers = picks[N_MISSING_TEMPERATURE + N_MISSING_DEMAND :]
    for i in temp_missing:
        rows[i][4] = ""
    for i in demand_missing:
        rows[i][3] = ""
    for i in outliers:
        rows[i][3] = f"{float(rows[i][3]) * OUTLIER_FACTOR:.1f}"

    for i in rng.sample(range(len(rows)), N_DUPLICATES):
        rows.append(list(rows[i]))
    return rows


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)


def _is_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _infer_type(values: list[str]) -> str:
    if values and all(_is_date(v) for v in values):
        return "date"
    if values and all(_is_float(v) for v in values):
        return "integer" if all(v.lstrip("-").isdigit() for v in values) else "float"
    return "string"


def compute_expected(csv_path: Path) -> dict[str, object]:
    raw = csv_path.read_bytes()
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)

    columns = []
    for idx, name in enumerate(header):
        cells = [r[idx] for r in rows]
        present = [c for c in cells if c != ""]
        col: dict[str, object] = {
            "name": name,
            "inferred_type": _infer_type(present),
            "missing_count": len(cells) - len(present),
            "unique_count": len(set(present)),
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "std": None,
            "q1": None,
            "q3": None,
            "outlier_count": None,
        }
        if col["inferred_type"] == "date":
            col["min"], col["max"] = min(present), max(present)
        elif col["inferred_type"] in ("integer", "float"):
            nums = [float(c) for c in present]
            q1, _, q3 = statistics.quantiles(nums, n=4, method="inclusive")
            iqr = q3 - q1
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            col.update(
                min=round(min(nums), 6),
                max=round(max(nums), 6),
                mean=round(statistics.fmean(nums), 6),
                median=round(statistics.median(nums), 6),
                std=round(statistics.stdev(nums), 6),
                q1=round(q1, 6),
                q3=round(q3, 6),
                outlier_count=sum(1 for v in nums if v < low or v > high),
            )
        columns.append(col)

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "dataset_fingerprint": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
        "column_count": len(header),
        "duplicate_row_count": len(rows) - len({tuple(r) for r in rows}),
        "columns": columns,
    }


def build(csv_path: Path = CSV_PATH, expected_path: Path = EXPECTED_PATH) -> None:
    write_csv(csv_path, build_rows())
    expected = compute_expected(csv_path)
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build()
    sys.stdout.write(f"Wrote {CSV_PATH} and {EXPECTED_PATH}\n")
