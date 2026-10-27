"""Validated CSV ingestion (EDA-01, EDA-02).

``load_csv`` is the only way uploaded bytes enter the system. It checks the file name,
size, content and shape, then returns the data exactly as written: every cell is kept as a
string and an empty cell is ``None``. No type conversion or cleaning happens here, so the
uploaded data is preserved (EDA-04) and the fingerprint always describes the raw bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from ..security import LimitExceededError, LimitsConfig, check_shape, check_upload_size

IngestionErrorCode = Literal[
    "unsupported_extension",
    "file_too_large",
    "empty_file",
    "not_text",
    "bad_encoding",
    "parse_error",
    "missing_header",
    "duplicate_column",
    "ragged_row",
    "too_many_rows",
    "too_many_columns",
]


class IngestionError(ValueError):
    """Raised when an upload is rejected. ``code`` is stable; the message is for people."""

    def __init__(self, code: IngestionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: IngestionErrorCode = code


@dataclass(frozen=True)
class IngestedCSV:
    """Raw, validated CSV content.

    ``frame`` holds ``str`` cells and ``None`` for empty cells; treat it as read-only.
    ``fingerprint`` is the lowercase hex SHA-256 of the uploaded bytes.
    """

    fingerprint: str
    frame: pd.DataFrame


def _limit_code(error: LimitExceededError) -> IngestionErrorCode:
    return "too_many_rows" if "row_count" in str(error) else "too_many_columns"


def _decode(raw: bytes) -> str:
    if b"\x00" in raw:
        raise IngestionError("not_text", "file contains NUL bytes, so it is not a text CSV file")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError(
            "bad_encoding", f"file is not valid UTF-8 (byte offset {exc.start})"
        ) from None


def _parse(text: str, limits: LimitsConfig) -> tuple[list[str], list[list[str | None]]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise IngestionError("empty_file", "file has no header row") from None
    except csv.Error as exc:
        raise IngestionError("parse_error", f"cannot parse header: {exc}") from None

    if not any(name.strip() for name in header):
        raise IngestionError("missing_header", "header row is empty")
    if any(not name.strip() for name in header):
        raise IngestionError("missing_header", "header contains an empty column name")
    if len(set(header)) != len(header):
        repeated = sorted({name for name in header if header.count(name) > 1})
        raise IngestionError("duplicate_column", f"duplicate column names: {repeated}")
    try:
        check_shape(0, len(header), limits)
    except LimitExceededError as exc:
        raise IngestionError(_limit_code(exc), str(exc)) from None

    rows: list[list[str | None]] = []
    try:
        for row in reader:
            if not row:  # csv yields [] for blank lines; they carry no data
                continue
            if len(row) != len(header):
                raise IngestionError(
                    "ragged_row",
                    f"line {reader.line_num} has {len(row)} fields, expected {len(header)}",
                )
            try:
                check_shape(len(rows) + 1, len(header), limits)
            except LimitExceededError as exc:
                raise IngestionError(_limit_code(exc), str(exc)) from None
            rows.append([cell if cell != "" else None for cell in row])
    except csv.Error as exc:
        raise IngestionError("parse_error", f"line {reader.line_num}: {exc}") from None
    return header, rows


def load_csv(
    content: bytes,
    filename: str,
    limits: LimitsConfig | None = None,
) -> IngestedCSV:
    """Validate and parse an uploaded CSV. Raises :class:`IngestionError` on any problem."""
    active = LimitsConfig() if limits is None else limits

    if Path(filename).suffix.lower() != ".csv":
        raise IngestionError("unsupported_extension", f"only .csv files are accepted: {filename!r}")
    try:
        check_upload_size(len(content), active)
    except LimitExceededError as exc:
        raise IngestionError("file_too_large", str(exc)) from None
    if not content.strip():
        raise IngestionError("empty_file", "file is empty")

    header, rows = _parse(_decode(content), active)
    frame = pd.DataFrame(rows, columns=pd.Index(header), dtype=object)
    return IngestedCSV(fingerprint=hashlib.sha256(content).hexdigest(), frame=frame)


def load_csv_path(path: Path, limits: LimitsConfig | None = None) -> IngestedCSV:
    """Read *path* and ingest it. The size limit is checked before the file is read."""
    active = LimitsConfig() if limits is None else limits
    if path.suffix.lower() == ".csv":
        try:
            check_upload_size(path.stat().st_size, active)
        except LimitExceededError as exc:
            raise IngestionError("file_too_large", str(exc)) from None
    return load_csv(path.read_bytes(), path.name, active)
