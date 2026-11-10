"""Escaped HTML tables and key/value lists for small result sets.

Every header and cell is escaped before it enters the fragment. Tables keep their real
``table``/``th scope`` semantics, align numeric columns to the right and carry the first
column as a sticky row header. A result with exactly one data row becomes a stacked
key/value list instead, so a single result never stretches into a wide strip; results
with several rows always keep the table. ``format_values=False`` renders the uploaded
cell text unchanged, for the raw first-rows preview.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from numbers import Integral, Real
from typing import Final

from . import formatting
from .theme.tokens import CLASSES

_DECIMAL_TEXT: Final = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")
# A wide statistic table must still fit the canvas at 1440, so it trims its cell padding.
_DENSE_COLUMNS: Final = 8


def _raw_cells(
    rows: Iterable[Mapping[str, object]] | Iterable[Sequence[object]],
    columns: Sequence[str],
) -> list[list[object]]:
    matrix: list[list[object]] = []
    for row in rows:
        if isinstance(row, Mapping):
            matrix.append([row.get(name) for name in columns])
            continue
        values = list(row)
        matrix.append(values + [None] * (len(columns) - len(values)))
    return matrix


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or formatting.is_missing(value):
        return False
    if isinstance(value, (Integral, Real)):
        return True
    return isinstance(value, str) and bool(_DECIMAL_TEXT.match(value.strip()))


def _numeric_columns(matrix: Sequence[Sequence[object]], width: int) -> list[bool]:
    numeric = []
    for index in range(width):
        present = [
            row[index]
            for row in matrix
            if not formatting.is_missing(row[index]) and row[index] != ""
        ]
        numeric.append(bool(present) and all(_is_number(value) for value in present))
    return numeric


def _label(
    labels: Mapping[str, str] | Sequence[str] | None, columns: Sequence[str], index: int
) -> str:
    if labels is None:
        return columns[index]
    if isinstance(labels, Mapping):
        return labels.get(columns[index], columns[index])
    return labels[index] if index < len(labels) else columns[index]


def _caption(text: str | None, *, tag: str) -> str:
    if not text:
        return ""
    return f'<{tag} class="{CLASSES["table_caption"]}">{escape(text)}</{tag}>'


def _number_class(is_numeric: bool) -> str:
    return f' class="{CLASSES["table_num"]}"' if is_numeric else ""


def _cell_text(value: object, *, format_values: bool) -> str:
    """Escape one cell; raw mode keeps the uploaded text and leaves empty cells empty."""
    if not format_values:
        return "" if formatting.is_missing(value) else escape(str(value))
    return escape(formatting.format_cell(value))


def _render_table(
    matrix: Sequence[Sequence[object]],
    columns: Sequence[str],
    labels: Mapping[str, str] | Sequence[str] | None,
    caption: str | None,
    *,
    format_values: bool = True,
) -> str:
    numeric = _numeric_columns(matrix, len(columns))
    head = "".join(
        f'<th scope="col"{_number_class(numeric[index])}>'
        f"{escape(_label(labels, columns, index))}</th>"
        for index in range(len(columns))
    )
    body = []
    for row in matrix:
        cells = []
        for index, value in enumerate(row):
            text = _cell_text(value, format_values=format_values)
            if index == 0:
                cells.append(f'<th scope="row">{text}</th>')
            else:
                cells.append(f"<td{_number_class(numeric[index])}>{text}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")

    dense = " fn-table-scroll--dense" if len(columns) >= _DENSE_COLUMNS else ""
    return (
        f'<div class="{CLASSES["table_scroll"]}{dense}" role="region" tabindex="0" '
        f'aria-label="{escape(caption or "Data table")}">'
        f'<table class="{CLASSES["table"]}">{_caption(caption, tag="caption")}'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_key_values(
    matrix: Sequence[Sequence[object]],
    columns: Sequence[str],
    labels: Mapping[str, str] | Sequence[str] | None,
    caption: str | None,
    *,
    format_values: bool = True,
) -> str:
    if len(columns) == 1:
        items = "".join(
            f"<li>{_cell_text(row[0], format_values=format_values)}</li>" for row in matrix
        )
        body = f'<ul class="{CLASSES["kv_values"]}">{items}</ul>'
    else:
        numeric = _numeric_columns(matrix, len(columns))
        groups = []
        for row in matrix:
            pairs = "".join(
                f'<div class="{CLASSES["kv_pair"]}">'
                f"<dt>{escape(_label(labels, columns, index))}</dt>"
                f"<dd{_number_class(numeric[index])}>"
                f"{_cell_text(row[index], format_values=format_values)}</dd></div>"
                for index in range(1, len(columns))
            )
            groups.append(
                f'<div class="{CLASSES["kv_item"]}">'
                f'<p class="{CLASSES["kv_title"]}">'
                f"{_cell_text(row[0], format_values=format_values)}</p>"
                f'<dl class="{CLASSES["kv_pairs"]}">{pairs}</dl></div>'
            )
        body = f'<div class="{CLASSES["kv_list"]}">{"".join(groups)}</div>'

    return (
        f'<figure class="{CLASSES["kv_figure"]}">{_caption(caption, tag="figcaption")}'
        f"{body}</figure>"
    )


def render_data(
    rows: Iterable[Mapping[str, object]] | Iterable[Sequence[object]],
    columns: Sequence[str],
    *,
    labels: Mapping[str, str] | Sequence[str] | None = None,
    caption: str | None = None,
    format_values: bool = True,
) -> str:
    """Return a table, or a stacked key/value list when the result is a single row."""
    matrix = _raw_cells(rows, columns)
    if len(matrix) == 1:
        return _render_key_values(matrix, columns, labels, caption, format_values=format_values)
    return _render_table(matrix, columns, labels, caption, format_values=format_values)
