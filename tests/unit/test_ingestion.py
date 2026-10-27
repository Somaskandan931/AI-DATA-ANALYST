"""EDA-01 / EDA-02: uploads are validated before any parsing result is trusted."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_data_analyst.ingestion import IngestionError, load_csv, load_csv_path
from ai_data_analyst.security import LimitsConfig


def _limits(**overrides: int) -> LimitsConfig:
    values = {"max_upload_bytes": 1000, "max_rows": 5, "max_columns": 3}
    values.update(overrides)
    return LimitsConfig(**values)


def _code(content: bytes, name: str = "d.csv", limits: LimitsConfig | None = None) -> str:
    with pytest.raises(IngestionError) as info:
        load_csv(content, name, limits)
    return info.value.code


def test_valid_csv_keeps_raw_strings_and_marks_empty_cells_missing():
    result = load_csv(b"a,b\n1,\n,x\n", "d.csv")
    assert list(result.frame.columns) == ["a", "b"]
    assert result.frame.iloc[0].tolist() == ["1", None]
    assert result.frame.iloc[1].tolist() == [None, "x"]
    assert result.fingerprint == hashlib.sha256(b"a,b\n1,\n,x\n").hexdigest()


def test_leading_zeros_and_whitespace_are_preserved():
    frame = load_csv(b"zip,note\n00123, hi \n", "d.csv").frame
    assert frame.iloc[0].tolist() == ["00123", " hi "]


def test_utf8_bom_is_accepted_and_fingerprint_covers_raw_bytes():
    raw = b"\xef\xbb\xbfa,b\n1,2\n"
    result = load_csv(raw, "d.csv")
    assert list(result.frame.columns) == ["a", "b"]
    assert result.fingerprint == hashlib.sha256(raw).hexdigest()


def test_quoted_fields_with_commas_and_newlines():
    frame = load_csv(b'a,b\n"x,1","l1\nl2"\n', "d.csv").frame
    assert frame.iloc[0].tolist() == ["x,1", "l1\nl2"]


def test_blank_lines_are_ignored_and_header_only_is_allowed():
    assert len(load_csv(b"a,b\n1,2\n\n3,4\n", "d.csv").frame) == 2
    assert len(load_csv(b"a,b\n", "d.csv").frame) == 0


@pytest.mark.parametrize("name", ["d.txt", "d.xlsx", "d", "d.csv.exe", "d.json"])
def test_non_csv_extensions_are_rejected(name: str):
    assert _code(b"a\n1\n", name) == "unsupported_extension"


def test_extension_check_is_case_insensitive():
    assert len(load_csv(b"a\n1\n", "D.CSV").frame) == 1


def test_oversized_upload_is_rejected():
    assert _code(b"a\n" + b"1\n" * 600, limits=_limits(max_upload_bytes=100)) == "file_too_large"


@pytest.mark.parametrize("content", [b"", b"   \n\n"])
def test_empty_files_are_rejected(content: bytes):
    assert _code(content) == "empty_file"


def test_binary_content_is_rejected_even_with_csv_extension():
    assert _code(b"PK\x03\x04\x00\x00a,b\n1,2\n") == "not_text"


def test_non_utf8_is_rejected():
    assert _code("a\ncafé\n".encode("latin-1")) == "bad_encoding"


@pytest.mark.parametrize("content", [b",a\n1,2\n", b" ,\n1,2\n"])
def test_missing_column_names_are_rejected(content: bytes):
    assert _code(content) == "missing_header"


def test_duplicate_column_names_are_rejected():
    assert _code(b"a,b,a\n1,2,3\n") == "duplicate_column"


@pytest.mark.parametrize("content", [b"a,b\n1\n", b"a,b\n1,2,3\n"])
def test_ragged_rows_are_rejected(content: bytes):
    assert _code(content) == "ragged_row"


def test_unterminated_quote_is_a_parse_error():
    assert _code(b'a,b\n"1,2\n') == "parse_error"


def test_row_and_column_limits_are_enforced():
    assert _code(b"a\n" + b"1\n" * 6, limits=_limits()) == "too_many_rows"
    assert len(load_csv(b"a\n" + b"1\n" * 5, "d.csv", _limits()).frame) == 5
    assert _code(b"a,b,c,d\n1,2,3,4\n", limits=_limits()) == "too_many_columns"


def test_formula_like_cells_are_kept_as_inert_text():
    frame = load_csv(b"a\n=cmd|' /C calc'!A0\n", "d.csv").frame
    assert frame.iloc[0, 0] == "=cmd|' /C calc'!A0"


def test_load_csv_path_reads_sample_and_checks_size_first(sample_csv_path: Path, tmp_path: Path):
    assert len(load_csv_path(sample_csv_path).frame) == 485
    big = tmp_path / "big.csv"
    big.write_bytes(b"a\n" + b"1\n" * 600)
    with pytest.raises(IngestionError) as info:
        load_csv_path(big, _limits(max_upload_bytes=100))
    assert info.value.code == "file_too_large"
