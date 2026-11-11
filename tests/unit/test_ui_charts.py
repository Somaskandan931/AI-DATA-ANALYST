"""UI-CHARTS: the app adapter draws the numbers and labels its spec carries."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

plotly = pytest.importorskip("plotly")

from ai_data_analyst.ui import charts  # noqa: E402
from ai_data_analyst.ui.theme.plotly_template import CHART_HEIGHT  # noqa: E402
from ai_data_analyst.ui.theme.tokens import PALETTE  # noqa: E402
from ai_data_analyst.visualization import ChartSpec  # noqa: E402

_DIGEST = "a" * 64
_LABELS = ("North", "South", "East", "West")
_VALUES = (1186.7, 772.8, None, 985.7)


def _spec(**overrides: Any) -> ChartSpec:
    fields: dict[str, Any] = {
        "kind": "bar",
        "title": "Counts by region",
        "subtitle": "Columns: region",
        "x_label": "region",
        "y_label": "Rows",
        "labels": _LABELS,
        "values": _VALUES,
        "source_step": 0,
        "operation": "distribution",
        "artifact_digest": _DIGEST,
        "source_columns": ("region",),
    }
    fields.update(overrides)
    return ChartSpec(**fields)


def _histogram() -> ChartSpec:
    return _spec(
        kind="histogram",
        title="Distribution of demand_mwh",
        x_label="demand_mwh",
        labels=("0 to 500", "500 to 1000"),
        values=(3.0, 5.0),
        bin_edges=(0.0, 500.0, 1000.0),
    )


def _heatmap() -> ChartSpec:
    return _spec(
        kind="heatmap",
        title="Pearson correlation",
        x_label="Column",
        y_label="Column",
        labels=("demand_mwh", "temperature_c"),
        values=None,
        matrix=((-1.0, 0.25), (0.25, 1.0)),
    )


def _figures() -> Iterator[Any]:
    for spec in (_spec(), _histogram(), _heatmap()):
        yield charts.figure_for(spec)


def test_bar_is_horizontal_and_keeps_the_spec_labels_and_values() -> None:
    trace = charts.figure_for(_spec()).data[0]

    assert trace.orientation == "h"
    assert list(trace.y) == list(_LABELS)
    assert list(trace.x) == list(_VALUES)


def test_direct_labels_use_two_decimals_and_thousands_separators() -> None:
    assert charts.format_number(1186.7) == "1,186.70"
    assert charts.format_number(-3.5) == "-3.50"
    assert charts.format_number(None) == "\u2014"

    trace = charts.figure_for(_spec()).data[0]
    assert list(trace.text) == ["1,186.70", "772.80", "\u2014", "985.70"]


def test_bar_reserves_room_for_the_outer_value_labels() -> None:
    # The largest label is drawn outside the bar, so the right margin must fit the
    # longest formatted value or the card clips it (found at 1440 and 390).
    spec = _spec()
    figure = charts.figure_for(spec)
    longest = max(len(charts.format_number(value)) for value in spec.values)

    assert figure.layout.margin.r >= 8 + 7 * longest


def test_horizontal_bar_axis_titles_keep_the_label_meaning() -> None:
    layout = charts.figure_for(_spec()).layout

    # Categories sit on y, so the spec's x_label titles the category axis and the
    # measured y_label titles the value axis.
    assert layout.yaxis.title.text == "region"
    assert layout.xaxis.title.text == "Rows"


def test_only_one_mark_is_persimmon_and_colour_follows_the_label() -> None:
    spec = _spec()
    trace = charts.figure_for(spec).data[0]
    colours = list(trace.marker.color)

    assert colours.count(PALETTE.persimmon) == 1
    assert colours[0] == PALETTE.persimmon  # North is the largest value
    assert set(colours[1:]) == {PALETTE.sage_text}

    # Reordering rows does not change what colour a category has.
    reordered = _spec(labels=tuple(reversed(_LABELS)), values=tuple(reversed(_VALUES)))
    other = charts.figure_for(reordered).data[0]
    before = dict(zip(trace.y, colours, strict=True))
    after = dict(zip(other.y, other.marker.color, strict=True))
    assert before == after


def test_label_colours_are_keyed_by_label_not_position() -> None:
    first = charts.label_colors(("East", "West"), highlight="West")
    second = charts.label_colors(("West", "East"), highlight="West")

    assert first == second == {"East": PALETTE.sage_text, "West": PALETTE.persimmon}


def test_histogram_draws_one_bar_per_bin_between_its_edges() -> None:
    trace = charts.figure_for(_histogram()).data[0]

    assert list(trace.x) == [250.0, 750.0]
    assert list(trace.width) == [500.0, 500.0]
    assert list(trace.y) == [3.0, 5.0]
    assert trace.marker.color == PALETTE.sage_text


def test_heatmap_is_diverging_persimmon_paper_sage_with_cell_annotations() -> None:
    figure = charts.figure_for(_heatmap())
    trace = figure.data[0]

    assert trace.colorscale == (
        (0.0, PALETTE.persimmon),
        (0.5, PALETTE.canvas),
        (1.0, PALETTE.sage_text),
    )
    assert trace.zmid == 0.0
    assert list(trace.x) == ["demand_mwh", "temperature_c"]
    assert list(trace.y) == ["demand_mwh", "temperature_c"]
    assert [list(row) for row in trace.z] == [[-1.0, 0.25], [0.25, 1.0]]
    # Plotly paints every heatmap text run in one colour, so the values are annotations
    # that can each carry their own readable colour.
    assert trace.text is None
    assert trace.texttemplate is None

    cells = [
        (annotation.y, annotation.x, annotation.text) for annotation in figure.layout.annotations
    ]
    assert cells == [
        ("demand_mwh", "demand_mwh", "-1.00"),
        ("demand_mwh", "temperature_c", "0.25"),
        ("temperature_c", "demand_mwh", "0.25"),
        ("temperature_c", "temperature_c", "1.00"),
    ]


def test_heatmap_annotation_text_clears_wcag_aa_on_every_fill() -> None:
    matrix = ((-1.0, 0.25), (0.25, 1.0))
    bound = 1.0

    # The darkest fills are the ends of the ramp, so their text must switch pole:
    # black on persimmon and white on the sage diagonal.
    assert charts.heatmap_text_colour(-1.0, bound) == "#000000"
    assert charts.heatmap_text_colour(1.0, bound) == "#FFFFFF"

    for row in matrix:
        for value in row:
            fill = charts.heatmap_cell_colour(value, bound)
            text = charts.heatmap_text_colour(value, bound)
            assert charts.contrast_ratio(text, fill) >= 4.5


def test_heatmap_diagonal_and_lightest_cell_contrast_ratios() -> None:
    # The two ratios the UI review asked for: the 1.00 diagonal and the lightest
    # off-diagonal cell (0.25, nearest paper on the sage side).
    bound = 1.0
    diagonal = charts.contrast_ratio(
        charts.heatmap_text_colour(1.0, bound), charts.heatmap_cell_colour(1.0, bound)
    )
    lightest = charts.contrast_ratio(
        charts.heatmap_text_colour(0.25, bound), charts.heatmap_cell_colour(0.25, bound)
    )

    assert diagonal == pytest.approx(5.48, abs=0.01)
    assert lightest == pytest.approx(13.44, abs=0.01)
    assert diagonal >= 4.5 and lightest >= 4.5


def test_empty_spec_has_no_traces_and_a_quiet_message() -> None:
    figure = charts.figure_for(_spec(labels=(), values=()))

    assert len(figure.data) == 0
    assert figure.layout.annotations[0].text == "No data to draw"
    assert figure.layout.xaxis.visible is False
    assert figure.layout.yaxis.visible is False


def test_figures_serialise_without_nan_and_keep_the_field_notes_height() -> None:
    for figure in _figures():
        # allow_nan=False raises if a trace carries a NaN, which Plotly cannot render.
        json.dumps(figure.to_plotly_json(), allow_nan=False)
        assert figure.layout.height == CHART_HEIGHT
        assert 280 <= figure.layout.height <= 320


def test_chart_card_places_titles_above_and_the_numbers_below(monkeypatch) -> None:
    class _Container:
        def __enter__(self) -> _Container:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    html: list[str] = []
    plotted: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(charts.st, "container", lambda: _Container())
    monkeypatch.setattr(charts.st, "html", html.append)
    monkeypatch.setattr(
        charts.st, "plotly_chart", lambda figure, **kwargs: plotted.append((figure, kwargs))
    )

    charts.chart_card(
        _spec(title="<b>Counts</b>", warnings=("<script>x</script>",)),
    )
    page = "".join(html)

    assert 'class="fn-chart-title"' in page and "&lt;b&gt;Counts&lt;/b&gt;" in page
    assert "<b>Counts</b>" not in page
    assert "fn-chart-subtitle" in page and "Columns: region" in page
    assert "fn-visually-hidden" in page and "Chart: &lt;b&gt;Counts&lt;/b&gt;" in page
    assert "fn-chart-caption" in page and "Warning: &lt;script&gt;x&lt;/script&gt;" in page
    assert "Chart data" in page and '<table class="fn-table">' in page
    assert "North" in page and "1,186.70" in page

    ((figure, kwargs),) = plotted
    assert figure is not None
    assert kwargs == {"theme": None, "width": "stretch", "config": {"displayModeBar": False}}


def test_empty_chart_card_omits_the_chart_data_details(monkeypatch) -> None:
    class _Container:
        def __enter__(self) -> _Container:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    html: list[str] = []
    monkeypatch.setattr(charts.st, "container", lambda: _Container())
    monkeypatch.setattr(charts.st, "html", html.append)
    monkeypatch.setattr(charts.st, "plotly_chart", lambda figure, **kwargs: None)

    charts.chart_card(_spec(labels=(), values=()))

    assert "Chart data" not in "".join(html)
