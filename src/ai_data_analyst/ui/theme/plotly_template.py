"""Field Notes look for Plotly figures drawn inside the app.

The template is data-independent: paper-coloured canvas, hairline axes, no gridlines,
Inter for UI text and JetBrains Mono for hover readouts. Charts always use it with
Streamlit's own theme disabled, so the app and the figure cannot disagree about colour.
"""

from __future__ import annotations

from typing import Final

import plotly.graph_objects as go  # type: ignore[import-untyped]

from .tokens import FONT_MONO, FONT_UI, PALETTE

# Within the requested 280-320px band, and stable at both 1440 and 390.
CHART_HEIGHT: Final = 300

_AXIS: Final = {
    "showgrid": False,
    "zeroline": False,
    "showline": True,
    "linecolor": PALETTE.rule,
    "linewidth": 1,
    "ticks": "",
    "automargin": True,
    "tickfont": {"family": FONT_UI, "size": 11, "color": PALETTE.ink_muted},
    "title": {"font": {"family": FONT_MONO, "size": 10, "color": PALETTE.ink_muted}},
}

FIELD_NOTES_TEMPLATE: Final = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=PALETTE.canvas,
        plot_bgcolor=PALETTE.canvas,
        colorway=[PALETTE.sage_text],
        font={"family": FONT_UI, "size": 12, "color": PALETTE.ink},
        hoverlabel={
            "bgcolor": PALETTE.canvas,
            "bordercolor": PALETTE.rule,
            "font": {"family": FONT_MONO, "size": 11, "color": PALETTE.ink},
        },
        margin={"l": 8, "r": 16, "t": 8, "b": 8},
        height=CHART_HEIGHT,
        showlegend=False,
        transition={"duration": 0},
        xaxis=_AXIS,
        yaxis=_AXIS,
    )
)


def apply_template(figure: go.Figure) -> go.Figure:
    """Apply the Field Notes template and make sure no transition animates the marks."""
    figure.update_layout(
        template=FIELD_NOTES_TEMPLATE, transition={"duration": 0}, height=CHART_HEIGHT
    )
    return figure
