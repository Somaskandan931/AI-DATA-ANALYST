"""Draw a :class:`~ai_data_analyst.visualization.ChartSpec` as a standalone SVG string.

The output has no scripts, no external references and no fonts to load, so it can sit inside
a report that is opened offline. Every string that came from the data (labels, titles) is
escaped. The drawing shows only numbers that are in the spec.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from ..visualization import ChartSpec
from ._format import MISSING, escape_html, fmt_value

WIDTH: Final = 720
_FONT: Final = 'font-family="system-ui, -apple-system, Segoe UI, Arial, sans-serif"'
_INK: Final = "#222222"
_MUTED: Final = "#666666"
_POSITIVE: Final = (59, 110, 165)
_NEGATIVE: Final = (181, 82, 59)
_LABEL_LIMIT: Final = 36


def _short(label: str) -> str:
    text = " ".join(label.split())
    return text if len(text) <= _LABEL_LIMIT else text[: _LABEL_LIMIT - 1] + "\u2026"


def _text(
    x: float,
    y: float,
    content: str,
    *,
    anchor: str = "start",
    size: int = 11,
    fill: str = _INK,
    extra: str = "",
    tooltip: str | None = None,
) -> str:
    inner = escape_html(content) + (f"<title>{escape_html(tooltip)}</title>" if tooltip else "")
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{size}" '
        f'fill="{fill}" {_FONT}{" " + extra if extra else ""}>{inner}</text>'
    )


def _frame(spec: ChartSpec, height: float, body: Sequence[str]) -> str:
    label = f"{spec.title}. {spec.subtitle}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:.0f}" '
        f'width="100%" style="max-width:{WIDTH}px" role="img" aria-label="{escape_html(label)}">'
        f"<title>{escape_html(spec.title)}</title>" + "".join(body) + "</svg>"
    )


def _empty(spec: ChartSpec) -> str:
    return _frame(spec, 40, [_text(10, 24, "No data to draw", fill=_MUTED)])


def _bar(spec: ChartSpec) -> str:
    labels, values = spec.labels, spec.values or ()
    if not labels:
        return _empty(spec)
    row, top, bottom, right = 22, 22, 46, 76
    left = int(min(240, max(60, 6.6 * max(len(_short(x)) for x in labels) + 14)))
    plot = WIDTH - left - right
    height = top + row * len(labels) + bottom
    present = [v for v in values if v is not None]
    low = min(0.0, min(present)) if present else 0.0
    high = max(0.0, max(present)) if present else 1.0
    if high == low:
        high = low + 1.0

    def at(value: float) -> float:
        return left + (value - low) / (high - low) * plot

    zero = at(0.0)
    body = [_text(left, 13, spec.x_label, fill=_MUTED)]
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        y = top + i * row
        body.append(_text(left - 6, y + 15, _short(label), anchor="end", tooltip=label))
        if value is None:
            body.append(_text(zero + 4, y + 15, MISSING, fill=_MUTED))
            continue
        start, end = sorted((zero, at(value)))
        colour = _POSITIVE if value >= 0 else _NEGATIVE
        body.append(
            f'<rect x="{start:.1f}" y="{y + 3}" width="{max(end - start, 0.5):.1f}" '
            f'height="{row - 6}" fill="rgb{colour}"><title>{escape_html(label)}: '
            f"{escape_html(fmt_value(value))}</title></rect>"
        )
        body.append(_text(max(zero, end) + 4, y + 15, fmt_value(value)))
    base = top + row * len(labels)
    body.append(f'<line x1="{zero:.1f}" y1="{top}" x2="{zero:.1f}" y2="{base}" stroke="#888888"/>')
    body.append(_text(left, base + 16, fmt_value(low), fill=_MUTED))
    body.append(_text(left + plot, base + 16, fmt_value(high), anchor="end", fill=_MUTED))
    body.append(_text(left + plot / 2, base + 36, spec.y_label, anchor="middle", fill=_MUTED))
    return _frame(spec, height, body)


def _histogram(spec: ChartSpec) -> str:
    values, edges = spec.values or (), spec.bin_edges or ()
    if not values or len(edges) != len(values) + 1:
        return _empty(spec)
    left, right, top, plot_h = 60, 16, 22, 220
    plot = WIDTH - left - right
    peak = max((v for v in values if v is not None), default=0.0)
    if peak <= 0:
        peak = 1.0
    width = plot / len(values)
    body = [
        _text(
            12,
            top + plot_h / 2,
            spec.y_label,
            anchor="middle",
            fill=_MUTED,
            extra=f'transform="rotate(-90 12 {top + plot_h / 2:.1f})"',
        )
    ]
    for i, (label, value) in enumerate(zip(spec.labels, values, strict=True)):
        bar = (value or 0.0) / peak * plot_h
        body.append(
            f'<rect x="{left + i * width:.1f}" y="{top + plot_h - bar:.1f}" '
            f'width="{max(width - 1, 0.5):.1f}" height="{bar:.1f}" '
            f'fill="rgb{_POSITIVE}"><title>{escape_html(label)}: '
            f"{escape_html(fmt_value(value))}</title></rect>"
        )
    base = top + plot_h
    body.append(f'<line x1="{left}" y1="{base}" x2="{left + plot}" y2="{base}" stroke="#888888"/>')
    body.append(_text(left - 6, base, "0", anchor="end", fill=_MUTED))
    body.append(_text(left - 6, top + 8, fmt_value(peak), anchor="end", fill=_MUTED))
    for tick in sorted({round(k * len(values) / 4) for k in range(5)}):
        anchor = "end" if tick == len(values) else "middle"  # keep the last label inside
        label = fmt_value(edges[tick])
        body.append(_text(left + tick * width, base + 16, label, anchor=anchor, fill=_MUTED))
    body.append(_text(left + plot / 2, base + 40, spec.x_label, anchor="middle", fill=_MUTED))
    return _frame(spec, base + 50, body)


def _mix(value: float) -> str:
    """White to blue for positive values and to red for negative ones; |value| is clamped to 1."""
    weight = min(abs(value), 1.0)
    target = _POSITIVE if value >= 0 else _NEGATIVE
    red, green, blue = (round(255 + (c - 255) * weight) for c in target)
    return f"rgb({red},{green},{blue})"


def _cell_colour(value: float | None) -> str:
    return "#dddddd" if value is None else _mix(value)


def _heatmap(spec: ChartSpec) -> str:
    """Cell text is rounded to 2 decimals to fit; tooltips and the tables hold exact values."""
    matrix, labels = spec.matrix or (), spec.labels
    if not labels:
        return _empty(spec)
    size = max(16.0, min(52.0, 560.0 / len(labels)))
    left = min(220.0, max(60.0, 6.6 * max(len(_short(x)) for x in labels) + 14))
    top = min(150.0, max(40.0, 5.6 * max(len(_short(x)) for x in labels) + 20))
    height = top + size * len(labels) + 16
    body: list[str] = []
    for j, label in enumerate(labels):
        x = left + j * size + size / 2
        body.append(
            _text(
                x,
                top - 6,
                _short(label),
                size=10,
                tooltip=label,
                extra=f'transform="rotate(-50 {x:.1f} {top - 6:.1f})"',
            )
        )
    for i, label in enumerate(labels):
        y = top + i * size
        body.append(_text(left - 6, y + size / 2 + 4, _short(label), anchor="end", tooltip=label))
        for j, value in enumerate(matrix[i]):
            x = left + j * size
            body.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{size:.1f}" height="{size:.1f}" '
                f'fill="{_cell_colour(value)}" stroke="#ffffff"><title>{escape_html(label)} / '
                f"{escape_html(labels[j])}: {escape_html(fmt_value(value))}</title></rect>"
            )
            if size >= 30:
                dark = value is not None and abs(value) > 0.6
                body.append(
                    _text(
                        x + size / 2,
                        y + size / 2 + 4,
                        fmt_value(round(value, 2)) if value is not None else MISSING,
                        anchor="middle",
                        size=10,
                        fill="#ffffff" if dark else _INK,
                    )
                )
    return _frame(spec, height, body)


def chart_svg(spec: ChartSpec) -> str:
    """Return *spec* drawn as an SVG document string."""
    match spec.kind:
        case "bar":
            return _bar(spec)
        case "histogram":
            return _histogram(spec)
        case "heatmap":
            return _heatmap(spec)
