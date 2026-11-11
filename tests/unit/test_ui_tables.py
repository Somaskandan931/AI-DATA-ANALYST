"""Escaped HTML tables and the single-row key/value layout (UI fix round three)."""

from __future__ import annotations

from ai_data_analyst.ui import tables

COLUMNS = ("name", "missing", "unique", "mean")
LABELS = {"name": "Column", "missing": "Missing", "unique": "Unique", "mean": "Mean"}
ROWS = [
    {"name": "demand_mwh", "missing": 4, "unique": 460, "mean": 1121.197713},
    {"name": "temperature_c", "missing": 12, "unique": 171, "mean": 19.528118},
]


def test_wide_table_keeps_real_headers_scope_and_number_alignment() -> None:
    # The layout now depends on the row count, not the column count: several rows keep
    # the table even when it is only a few columns wide (UI fix, item 4).
    html = tables.render_data(ROWS, COLUMNS, labels=LABELS)

    assert '<table class="fn-table">' in html
    assert html.count('<th scope="col"') == 4
    assert '<th scope="col">Column</th>' in html
    assert '<th scope="col" class="fn-num">Mean</th>' in html
    assert '<th scope="row">demand_mwh</th>' in html
    assert '<td class="fn-num">4</td>' in html
    assert '<td class="fn-num">1,121.20</td>' in html
    assert "fn-table-scroll" in html


def test_table_uses_short_labels_and_escapes_a_caption() -> None:
    html = tables.render_data(
        ROWS, COLUMNS, labels=LABELS, caption='Stats for <img src=x onerror="x">'
    )

    assert "<caption" in html
    assert "<img" not in html
    assert "&lt;img" in html


def test_a_single_row_becomes_a_stacked_key_value_list() -> None:
    html = tables.render_data(
        [("East", 879.756)],
        ("region", "mean of demand_mwh"),
    )

    assert "<table" not in html
    assert "fn-kv-list" in html
    assert 'class="fn-kv-title">East<' in html
    assert "<dt>mean of demand_mwh</dt>" in html
    assert '<dd class="fn-num">879.76</dd>' in html


def test_a_single_row_keeps_all_its_pairs_in_the_key_value_list() -> None:
    html = tables.render_data(
        [("demand_mwh", 1121.197713, 279.33)],
        ("Column", "Mean", "Std"),
    )

    assert "fn-kv-list" in html
    assert 'class="fn-kv-title">demand_mwh<' in html
    assert "<dt>Mean</dt>" in html and "<dt>Std</dt>" in html
    assert html.count('class="fn-kv-pair"') == 2


def test_several_rows_keep_the_table_even_with_two_columns() -> None:
    # Grouped aggregation with a single group key used to stack; it now keeps a table
    # because it carries more than one data row (UI fix, item 4).
    html = tables.render_data(
        [("East", 879.756), ("North", 1092.81)],
        ("region", "mean of demand_mwh"),
    )

    assert '<table class="fn-table">' in html
    assert "fn-kv-list" not in html
    assert '<th scope="row">East</th>' in html
    assert '<td class="fn-num">1,092.81</td>' in html


def test_several_rows_and_four_columns_keep_the_table_layout() -> None:
    html = tables.render_data(
        [
            ("demand_mwh", 481, 4, 1121.197713),
            ("temperature_c", 473, 12, 19.528118),
        ],
        ("Column", "Count", "Missing", "Mean"),
    )

    assert '<table class="fn-table">' in html
    assert "fn-kv-list" not in html


def test_wide_statistic_table_uses_the_dense_padding() -> None:
    # Nine statistic columns overflowed the 720px canvas at 1440 by 27px; the dense
    # scroll container trims the cell padding so the table fits without sideways scroll
    # (UI fix, item 2).
    wide = tables.render_data(
        [
            ("demand_mwh", 740.5, 3950.8, 1121.197713, 1106.7, 279.334266, 960.7, 1240.8, 3),
            ("temperature_c", 9.4, 31.3, 19.528118, 19.4, 4.564889, 16.1, 22.9, 0),
        ],
        ("Column", "Min", "Max", "Mean", "Median", "Std", "Q1", "Q3", "Outliers"),
    )
    narrow = tables.render_data(ROWS, COLUMNS, labels=LABELS)

    assert "fn-table-scroll--dense" in wide
    assert "fn-table-scroll--dense" not in narrow


def test_raw_mode_keeps_the_uploaded_text_in_the_table() -> None:
    # The preview must show the bytes as uploaded: no thousands separators and no
    # forced decimals (UI fix, item 1).
    html = tables.render_data(
        [
            ("R0001", "2025-01-01", "906.3", "14.7"),
            ("R0002", "2025-01-01", "1186.7", "13.1"),
        ],
        ("record_id", "date", "demand_mwh", "temperature_c"),
        format_values=False,
    )

    assert '<td class="fn-num">906.3</td>' in html
    assert '<td class="fn-num">1186.7</td>' in html
    assert '<td class="fn-num">906.30</td>' not in html
    assert '<td class="fn-num">1,186.70</td>' not in html


def test_raw_mode_leaves_an_empty_uploaded_cell_empty() -> None:
    html = tables.render_data(
        [("a", None), ("b", "x")],
        ("key", "value"),
        format_values=False,
    )

    assert "<td></td>" in html


def test_hostile_headers_and_values_are_escaped() -> None:
    header = '<script>alert("header")</script>'
    value = '<img src=x onerror="alert(1)">'
    html = tables.render_data(
        [(value, value, value, value), (value, value, value, value)],
        (header, header, header, header),
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert 'onerror="' not in html
    assert "&lt;img" in html


def test_single_column_with_one_row_becomes_a_plain_value_list() -> None:
    html = tables.render_data([("East",)], ("region",))

    assert "<table" not in html
    assert "fn-kv-values" in html
    assert "<li>East</li>" in html
