"""Deterministic evidence cards for computed results (PR2).

The mapping and the HTML builder are pure Python so they can be unit tested without a
browser. Every string that came from data (column names, values, questions, SQL) is
escaped before it enters a fragment; only our own static class names are trusted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import Final

from ..models import DatasetProfile
from ..sql_agent.executor import SQLExecutionResult
from .theme.tokens import CLASSES

_COLUMN_SUMMARY_LIMIT: Final = 12
_MISSING_NOTE: Final = "Interpretation not available."


class EvidenceSource(StrEnum):
    """Where a card's numbers came from; chips never rely on colour alone."""

    COMPUTED = "computed"
    QUERY_RESULT = "query-result"


SOURCE_LABELS: Final[dict[EvidenceSource, str]] = {
    EvidenceSource.COMPUTED: "COMPUTED",
    EvidenceSource.QUERY_RESULT: "QUERY RESULT",
}

_CHIP_CLASSES: Final[dict[EvidenceSource, str]] = {
    EvidenceSource.COMPUTED: CLASSES["source_chip_computed"],
    EvidenceSource.QUERY_RESULT: CLASSES["source_chip_query_result"],
}


@dataclass(frozen=True)
class OverviewFields:
    """The profile fields the overview cards are allowed to use."""

    row_count: int | None = None
    column_count: int | None = None
    missing_cells: int | None = None
    duplicate_rows: int | None = None
    numeric_columns: int | None = None
    text_columns: int | None = None
    date_columns: int | None = None
    logical_columns: int | None = None
    fingerprint: str | None = None
    columns: tuple[tuple[str, str], ...] = ()
    missing_by_column: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class EvidenceCard:
    """One label, value, interpretation and its provenance."""

    key: str
    label: str
    value: str | None
    interpretation: str | None
    source: EvidenceSource
    computed_from: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EvidenceView:
    """A group of cards rendered together, with a stable key for unique anchors."""

    cards: tuple[EvidenceCard, ...]
    key: str = "evidence"


def _count(value: int) -> str:
    return f"{value:,}"


def _maybe_count(value: int | None) -> str | None:
    return None if value is None else _count(value)


def _fingerprint(value: str | None) -> tuple[str, str]:
    return ("Dataset fingerprint", value or "Not available")


def overview_fields(profile: DatasetProfile) -> OverviewFields:
    """Read only the fields the overview needs from a profile."""
    kinds = Counter(column.inferred_type for column in profile.columns)
    return OverviewFields(
        row_count=profile.row_count,
        column_count=profile.column_count,
        missing_cells=sum(column.missing_count for column in profile.columns),
        duplicate_rows=profile.duplicate_row_count,
        numeric_columns=kinds["integer"] + kinds["float"],
        text_columns=kinds["string"],
        date_columns=kinds["date"],
        logical_columns=kinds["boolean"],
        fingerprint=profile.dataset_fingerprint,
        columns=tuple((column.name, column.inferred_type) for column in profile.columns),
        missing_by_column=tuple(
            (column.name, column.missing_count)
            for column in profile.columns
            if column.missing_count
        ),
    )


def interpret_rows(fields: OverviewFields) -> str | None:
    """One plain sentence, or ``None`` when the field is unknown."""
    if fields.row_count is None:
        return None
    if fields.row_count == 1:
        return "1 row was read."
    return f"{_count(fields.row_count)} rows were read."


def interpret_columns(fields: OverviewFields) -> str | None:
    """Describe the column count and its type split when every count is known."""
    if fields.column_count is None:
        return None
    noun = "column" if fields.column_count == 1 else "columns"
    counts = (
        fields.numeric_columns,
        fields.text_columns,
        fields.date_columns,
        fields.logical_columns,
    )
    if any(count is None for count in counts):
        return f"{_count(fields.column_count)} {noun}."
    labels = ("numeric", "text", "date", "logical")
    parts = [
        f"{count} {label}"
        for count, label in zip(counts, labels, strict=True)
        if count is not None and count > 0
    ]
    if not parts:
        return f"{_count(fields.column_count)} {noun}."
    return f"{_count(fields.column_count)} {noun}: {', '.join(parts)}."


def interpret_missing_cells(fields: OverviewFields) -> str | None:
    """State the empty-cell count and, when the shape is known, its share."""
    if fields.missing_cells is None:
        return None
    missing = fields.missing_cells
    noun = "cell" if missing == 1 else "cells"
    verb = "is" if missing == 1 else "are"
    if fields.row_count is not None and fields.column_count is not None:
        total = fields.row_count * fields.column_count
        if total:
            share = f"{missing / total:.1%}"
            return f"{_count(missing)} {noun} {verb} empty ({share} of {_count(total)})."
    return f"{_count(missing)} {noun} {verb} empty."


def interpret_duplicates(fields: OverviewFields) -> str | None:
    """State how many rows repeat an earlier row, without inferring a cause."""
    if fields.duplicate_rows is None:
        return None
    if fields.duplicate_rows == 0:
        return "No row repeats an earlier row."
    if fields.duplicate_rows == 1:
        return "1 row repeats an earlier row."
    return f"{_count(fields.duplicate_rows)} rows repeat an earlier row."


def _summarise_columns(columns: tuple[tuple[str, str], ...]) -> str:
    if not columns:
        return "Not available"
    shown = [f"{name} ({kind})" for name, kind in columns[:_COLUMN_SUMMARY_LIMIT]]
    extra = len(columns) - _COLUMN_SUMMARY_LIMIT
    summary = ", ".join(shown)
    return f"{summary}, … (+{extra} more)" if extra > 0 else summary


def _summarise_missing(columns: tuple[tuple[str, int], ...]) -> str:
    if not columns:
        return "No column has missing values."
    return "; ".join(f"{name}: {_count(count)}" for name, count in columns)


def overview_view(profile: DatasetProfile) -> EvidenceView:
    """The four overview cards for a profiled dataset."""
    return overview_view_from(overview_fields(profile))


def overview_view_from(fields: OverviewFields) -> EvidenceView:
    """Map known (and missing) fields onto the four overview cards."""
    fingerprint = _fingerprint(fields.fingerprint)
    cards = (
        EvidenceCard(
            key="rows",
            label="Rows",
            value=_maybe_count(fields.row_count),
            interpretation=interpret_rows(fields),
            source=EvidenceSource.COMPUTED,
            computed_from=(("Profile field", "row_count"), fingerprint),
        ),
        EvidenceCard(
            key="columns",
            label="Columns",
            value=_maybe_count(fields.column_count),
            interpretation=interpret_columns(fields),
            source=EvidenceSource.COMPUTED,
            computed_from=(
                ("Profile field", "column_count"),
                ("Columns", _summarise_columns(fields.columns)),
                fingerprint,
            ),
        ),
        EvidenceCard(
            key="missing",
            label="Missing cells",
            value=_maybe_count(fields.missing_cells),
            interpretation=interpret_missing_cells(fields),
            source=EvidenceSource.COMPUTED,
            computed_from=(
                ("Profile field", "sum(columns[].missing_count)"),
                ("Missing by column", _summarise_missing(fields.missing_by_column)),
                fingerprint,
            ),
        ),
        EvidenceCard(
            key="duplicates",
            label="Duplicate rows",
            value=_maybe_count(fields.duplicate_rows),
            interpretation=interpret_duplicates(fields),
            source=EvidenceSource.COMPUTED,
            computed_from=(
                ("Profile field", "duplicate_row_count"),
                (
                    "Definition",
                    "Rows identical to an earlier row; the first occurrence is not counted.",
                ),
                fingerprint,
            ),
        ),
    )
    return EvidenceView(cards=cards, key="overview")


def query_result_view(
    question: str,
    sql: str,
    result: SQLExecutionResult,
    *,
    max_rows: int,
) -> EvidenceView:
    """One QUERY RESULT card for an executed SQL statement."""
    interpretation = (
        f"The result reached the {_count(max_rows)}-row display limit."
        if result.truncated
        else "Every returned row is shown."
    )
    card = EvidenceCard(
        key="rows-returned",
        label="Rows returned",
        value=_count(len(result.rows)),
        interpretation=interpretation,
        source=EvidenceSource.QUERY_RESULT,
        computed_from=(
            ("Question", question or "Not available"),
            ("Validated SQL", sql),
            ("Result limit", f"{_count(max_rows)} rows"),
        ),
    )
    return EvidenceView(cards=(card,), key="query-result")


def _source_chip(card: EvidenceCard) -> str:
    classes = f"{CLASSES['source_chip']} {_CHIP_CLASSES[card.source]}"
    shape = f'<span class="{CLASSES["chip_shape"]}" aria-hidden="true"></span>'
    return f'<p class="{classes}">{shape}{escape(SOURCE_LABELS[card.source])}</p>'


def _render_card(view_key: str, card: EvidenceCard, position: int) -> str:
    details_id = f"fn-computed-from-{escape(view_key)}-{position}"
    if card.value is None:
        value = (
            f'<p class="{CLASSES["evidence_value"]} {CLASSES["evidence_value_missing"]}">'
            "Not available</p>"
        )
    else:
        value = (
            f'<p class="{CLASSES["evidence_value"]}">'
            f'<span class="{CLASSES["highlight"]}">{escape(card.value)}</span></p>'
        )
    if card.interpretation is None:
        note = f'<p class="{CLASSES["evidence_note"]}">{_MISSING_NOTE}</p>'
    else:
        marker = (
            f' <sup class="{CLASSES["footnote"]}">'
            f'<a href="#{details_id}" aria-label="Computed from">{position}</a></sup>'
        )
        note = f'<p class="{CLASSES["evidence_note"]}">{escape(card.interpretation)}{marker}</p>'
    provenance = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(text)}</dd>" for label, text in card.computed_from
    )
    return (
        f'<article class="{CLASSES["evidence_card"]}" '
        f'id="fn-card-{escape(view_key)}-{position}">'
        f'<p class="{CLASSES["evidence_label"]}">{escape(card.label)}</p>'
        f"{value}{note}{_source_chip(card)}"
        f'<details class="{CLASSES["computed_from"]}" id="{details_id}">'
        f"<summary>Computed from</summary><dl>{provenance}</dl>"
        "</details></article>"
    )


def render_evidence_view(view: EvidenceView, *, fresh: bool = False) -> str:
    """Return the complete fragment; *fresh* animates only the first render."""
    classes = [CLASSES["card_grid"]]
    if fresh:
        classes.append(CLASSES["fresh"])
    cards = "".join(
        _render_card(view.key, card, position) for position, card in enumerate(view.cards, 1)
    )
    return f'<section class="{" ".join(classes)}">{cards}</section>'
