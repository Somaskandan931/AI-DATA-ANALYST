"""Escaped HTML tables and key/value lists for small result sets.

Every header and cell is escaped before it enters the fragment. Tables keep their real
``table``/``th scope`` semantics, align numeric columns to the right and carry the first
column as a sticky row header. A table of three columns or fewer becomes a stacked
key/value list instead, so a single result never stretches into a wide strip.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from numbers import Integral, Real
from typing import Final

from . import formatting
from .theme.tokens import CLASSES

TRANSPOSE_AT: Final = 3
_DECIMAL_TEXT: Final = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")


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


def _render_table(
    matrix: Sequence[Sequence[object]],
    columns: Sequence[str],
    labels: Mapping[str, str] | Sequence[str] | None,
    caption: str | None,
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
            text = escape(formatting.format_cell(value))
            if index == 0:
                cells.append(f'<th scope="row">{text}</th>')
            else:
                cells.append(f"<td{_number_class(numeric[index])}>{text}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")

    return (
        f'<div class="{CLASSES["table_scroll"]}" role="region" tabindex="0" '
        f'aria-label="{escape(caption or "Data table")}">'
        f'<table class="{CLASSES["table"]}">{_caption(caption, tag="caption")}'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_key_values(
    matrix: Sequence[Sequence[object]],
    columns: Sequence[str],
    labels: Mapping[str, str] | Sequence[str] | None,
    caption: str | None,
) -> str:
    if len(columns) == 1:
        items = "".join(f"<li>{escape(formatting.format_cell(row[0]))}</li>" for row in matrix)
        body = f'<ul class="{CLASSES["kv_values"]}">{items}</ul>'
    else:
        numeric = _numeric_columns(matrix, len(columns))
        groups = []
        for row in matrix:
            pairs = "".join(
                f'<div class="{CLASSES["kv_pair"]}">'
                f"<dt>{escape(_label(labels, columns, index))}</dt>"
                f"<dd{_number_class(numeric[index])}>"
                f"{escape(formatting.format_cell(row[index]))}</dd></div>"
                for index in range(1, len(columns))
            )
            groups.append(
                f'<div class="{CLASSES["kv_item"]}">'
                f'<p class="{CLASSES["kv_title"]}">'
                f"{escape(formatting.format_cell(row[0]))}</p>"
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
) -> str:
    """Return a table, or a stacked key/value list when the table is three columns or fewer."""
    matrix = _raw_cells(rows, columns)
    if len(columns) <= TRANSPOSE_AT:
        return _render_key_values(matrix, columns, labels, caption)
    return _render_table(matrix, columns, labels, caption)
