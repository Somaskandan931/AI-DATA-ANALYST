"""Draw a :class:`~ai_data_analyst.visualization.ChartSpec` with Plotly for the app.

The report keeps its standalone SVG (see ``reporting.svg``); this module is the app-only
adapter. Every number drawn comes from the spec, every string is escaped before it becomes
page text, and a chart with no data shows a deliberate empty state instead of a broken
trace.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from typing import Final

import plotly.graph_objects as go  # type: ignore[import-untyped]
import streamlit as st

from ..visualization import ChartSpec
from . import tables
from .theme.plotly_template import apply_template
from .theme.tokens import CLASSES, FONT_MONO, PALETTE

MISSING: Final = "\u2014"
_TICK_LIMIT: Final = 28
_EMPTY_TEXT: Final = "No data to draw"
# A heatmap annotation needs a readable colour on every possible fill. The warm ink
# and canvas pair cannot clear 4.5:1 across the whole diverging ramp (the mid-sage
# band fails for both), while black and white do, so the annotation swaps between
# these two page-neutral poles. White is the same value as ``on_persimmon``.
_HEATMAP_TEXT_LIGHT: Final = "#FFFFFF"
_HEATMAP_TEXT_DARK: Final = "#000000"


def format_number(value: float | None) -> str:
    """A direct label: two decimals and thousands separators, or an em dash."""
    if value is None:
        return MISSING
    return f"{value:,.2f}"


def _channels(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _relative_luminance(colour: str) -> float:
    """WCAG relative luminance of an ``#RRGGBB`` colour."""
    linear = []
    for channel in _channels(colour):
        value = channel / 255
        linear.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two ``#RRGGBB`` colours."""
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _mix(first: str, second: str, weight: float) -> str:
    """Linear sRGB interpolation, matching how Plotly blends adjacent colours."""
    low, high = _channels(first), _channels(second)
    return "#" + "".join(
        f"{round(start + (end - start) * weight):02X}" for start, end in zip(low, high, strict=True)
    )


def heatmap_cell_colour(value: float | None, bound: float) -> str:
    """The fill Plotly draws for *value* on the persimmon-paper-sage scale.

    A missing value has no fill, so the canvas shows through.
    """
    if value is None:
        return PALETTE.canvas
    position = (value + bound) / (2 * bound) if bound else 0.5
    position = min(max(position, 0.0), 1.0)
    if position <= 0.5:
        return _mix(PALETTE.persimmon, PALETTE.canvas, position * 2)
    return _mix(PALETTE.canvas, PALETTE.sage_text, (position - 0.5) * 2)


def heatmap_text_colour(value: float | None, bound: float) -> str:
    """Black or white, whichever clears a higher contrast ratio on the cell fill."""
    fill = heatmap_cell_colour(value, bound)
    light = contrast_ratio(_HEATMAP_TEXT_LIGHT, fill)
    dark = contrast_ratio(_HEATMAP_TEXT_DARK, fill)
    return _HEATMAP_TEXT_LIGHT if light >= dark else _HEATMAP_TEXT_DARK


def _short(label: str, limit: int = _TICK_LIMIT) -> str:
    text = " ".join(label.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def label_colors(labels: Sequence[str], *, highlight: str | None = None) -> dict[str, str]:
    """Map every label to sage, except the one highlighted mark (persimmon).

    The mapping is keyed by label, not position, so the same category keeps its colour
    when the rows are reordered. Categories are never coloured individually.
    """
    return {
        label: PALETTE.persimmon if label == highlight else PALETTE.sage_text for label in labels
    }


def highlight_label(spec: ChartSpec) -> str | None:
    """The single largest bar, highlighted only when values actually differ."""
    values = spec.values or ()
    present = [
        (value, label)
        for label, value in zip(spec.labels, values, strict=True)
        if value is not None
    ]
    if len(present) < 2:
        return None
    values_only = [value for value, _ in present]
    if min(values_only) == max(values_only):
        return None
    return max(present, key=lambda pair: pair[0])[1]


def chart_is_empty(spec: ChartSpec) -> bool:
    """True when the spec has nothing that can be drawn."""
    if spec.kind == "heatmap":
        matrix = spec.matrix or ()
        return not spec.labels or len(matrix) != len(spec.labels)
    return not spec.labels or not spec.values


def _empty_figure() -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": _EMPTY_TEXT,
                "showarrow": False,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "font": {"family": FONT_MONO, "size": 11, "color": PALETTE.ink_muted},
            }
        ],
    )
    return apply_template(figure)


def _bar_figure(spec: ChartSpec) -> go.Figure:
    labels = list(spec.labels)
    values = list(spec.values or ())
    labels_text = [format_number(value) for value in values]
    # Outside labels need room; without it the largest value is clipped at the card edge.
    label_room = max(16, 8 + 7 * max((len(text) for text in labels_text), default=0))
    negative = any(value is not None and value < 0 for value in values)
    highlight = highlight_label(spec)
    colours = label_colors(labels, highlight=highlight)
    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={"color": [colours[label] for label in labels], "line": {"width": 0}},
            text=labels_text,
            textposition="outside",
            cliponaxis=False,
            textfont={"family": FONT_MONO, "size": 11, "color": PALETTE.ink},
            hovertemplate="%{y}<br>%{x:,.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        bargap=0.35,
        margin={"l": label_room if negative else 8, "r": label_room},
        xaxis={"title": spec.y_label, "rangemode": "tozero"},
        yaxis={
            "title": spec.x_label,
            "type": "category",
            "autorange": "reversed",
            "tickmode": "array",
            "tickvals": labels,
            "ticktext": [_short(label) for label in labels],
        },
    )
    return apply_template(figure)


def _histogram_figure(spec: ChartSpec) -> go.Figure:
    counts = list(spec.values or ())
    edges = list(spec.bin_edges or ())
    centres = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
    widths = [edges[i + 1] - edges[i] for i in range(len(counts))]
    figure = go.Figure(
        go.Bar(
            x=centres,
            y=counts,
            width=widths,
            marker={"color": PALETTE.sage_text, "line": {"color": PALETTE.canvas, "width": 1}},
            customdata=[[edges[i], edges[i + 1]] for i in range(len(counts))],
            hovertemplate=(
                "%{customdata[0]:,.2f} to %{customdata[1]:,.2f}<br>%{y:,.0f} rows<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        xaxis={"title": spec.x_label},
        yaxis={"title": spec.y_label, "rangemode": "tozero"},
    )
    return apply_template(figure)


def _heatmap_figure(spec: ChartSpec) -> go.Figure:
    labels = list(spec.labels)
    matrix = [list(row) for row in spec.matrix or ()]
    bound = max((abs(value) for row in matrix for value in row if value is not None), default=1.0)
    bound = bound or 1.0
    # Plotly draws every heatmap cell text in one colour, so the values are placed as
    # annotations instead: each cell can then pick black or white from its own fill.
    annotations = [
        {
            "x": column,
            "y": row_label,
            "text": format_number(value),
            "showarrow": False,
            "xref": "x",
            "yref": "y",
            "xanchor": "center",
            "yanchor": "middle",
            "font": {
                "family": FONT_MONO,
                "size": 11,
                "color": heatmap_text_colour(value, bound),
            },
        }
        for row_label, row in zip(labels, matrix, strict=True)
        for column, value in zip(labels, row, strict=True)
    ]
    figure = go.Figure(
        go.Heatmap(
            z=matrix,
            x=labels,
            y=labels,
            colorscale=[
                [0.0, PALETTE.persimmon],
                [0.5, PALETTE.canvas],
                [1.0, PALETTE.sage_text],
            ],
            zmid=0.0,
            zmin=-bound,
            zmax=bound,
            showscale=False,
            xgap=1,
            ygap=1,
            hovertemplate="%{y} \u00d7 %{x}<br>%{z:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        xaxis={"title": spec.x_label, "side": "top"},
        yaxis={"title": spec.y_label, "type": "category", "autorange": "reversed"},
        annotations=annotations,
    )
    return apply_template(figure)


def figure_for(spec: ChartSpec) -> go.Figure:
    """Build the Plotly figure for one spec; an empty spec yields an empty figure."""
    if chart_is_empty(spec):
        return _empty_figure()
    match spec.kind:
        case "bar":
            return _bar_figure(spec)
        case "histogram":
            return _histogram_figure(spec)
        case "heatmap":
            return _heatmap_figure(spec)
    raise ValueError(f"unsupported chart kind {spec.kind!r}")


def _data_rows(spec: ChartSpec) -> tuple[Sequence[Sequence[object]], Sequence[str]]:
    if spec.kind == "heatmap":
        matrix = spec.matrix or ()
        rows = [
            (label, *(None if value is None else value for value in row))
            for label, row in zip(spec.labels, matrix, strict=True)
        ]
        return rows, (spec.y_label, *spec.labels)
    return list(zip(spec.labels, spec.values or (), strict=True)), (
        spec.x_label,
        spec.y_label,
    )


def _caption(spec: ChartSpec) -> str:
    parts = [f"Columns: {', '.join(spec.source_columns) or 'none'}"]
    parts.extend(f"Warning: {warning}" for warning in spec.warnings)
    return " \u00b7 ".join(parts)


def _alt_text(spec: ChartSpec) -> str:
    parts = [f"Chart: {spec.title}.", spec.subtitle]
    parts.extend(f"Warning: {warning}" for warning in spec.warnings)
    return " ".join(parts)


def chart_card(spec: ChartSpec) -> None:
    """A figure with its title above, source note below and the numbers behind it."""
    with st.container():
        st.html(f'<span class="{CLASSES["chart_marker"]}" aria-hidden="true"></span>')
        st.html(
            '<div class="fn-chart-head">'
            f'<p class="fn-chart-title">{escape(spec.title)}</p>'
            f'<p class="fn-chart-subtitle">{escape(spec.subtitle)}</p>'
            "</div>"
        )
        st.html(f'<p class="fn-visually-hidden">{escape(_alt_text(spec))}</p>')
        st.plotly_chart(
            figure_for(spec),
            theme=None,
            width="stretch",
            config={"displayModeBar": False},
        )
        st.html(f'<p class="{CLASSES["mono"]} fn-chart-caption">{escape(_caption(spec))}</p>')
        if not chart_is_empty(spec):
            rows, columns = _data_rows(spec)
            detail = tables.render_data(rows, columns)
            st.html(
                f'<details class="fn-chart-data"><summary>Chart data</summary>{detail}</details>'
            )
