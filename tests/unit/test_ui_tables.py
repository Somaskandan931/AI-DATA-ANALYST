"""Escaped HTML tables and the transposed key/value layout (UI polish round two)."""

from __future__ import annotations

from ai_data_analyst.ui import tables

COLUMNS = ("name", "missing", "unique", "mean")
LABELS = {"name": "Column", "missing": "Missing", "unique": "Unique", "mean": "Mean"}
ROW = {"name": "demand_mwh", "missing": 4, "unique": 460, "mean": 1121.197713}


def test_wide_table_keeps_real_headers_scope_and_number_alignment() -> None:
    html = tables.render_data([ROW], COLUMNS, labels=LABELS)

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
        [ROW], COLUMNS, labels=LABELS, caption='Stats for <img src=x onerror="x">'
    )

    assert "<caption" in html
    assert "<img" not in html
    assert "&lt;img" in html


def test_three_or_fewer_columns_become_a_stacked_key_value_list() -> None:
    html = tables.render_data(
        [("East", 879.756), ("North", 1092.81)],
        ("region", "mean of demand_mwh"),
    )

    assert "<table" not in html
    assert "fn-kv-list" in html
    assert 'class="fn-kv-title">East<' in html
    assert "<dt>mean of demand_mwh</dt>" in html
    assert '<dd class="fn-num">879.76</dd>' in html


def test_three_columns_keep_their_labels_in_the_key_value_list() -> None:
    html = tables.render_data(
        [("demand_mwh", 1121.197713, 279.33)],
        ("Column", "Mean", "Std"),
    )

    assert "fn-kv-list" in html
    assert 'class="fn-kv-title">demand_mwh<' in html
    assert "<dt>Mean</dt>" in html and "<dt>Std</dt>" in html
    assert html.count('class="fn-kv-pair"') == 2


def test_four_columns_keep_the_table_layout() -> None:
    html = tables.render_data(
        [("demand_mwh", 481, 4, 1121.197713)],
        ("Column", "Count", "Missing", "Mean"),
    )

    assert '<table class="fn-table">' in html
    assert "fn-kv-list" not in html


def test_hostile_headers_and_values_are_escaped() -> None:
    header = '<script>alert("header")</script>'
    value = '<img src=x onerror="alert(1)">'
    html = tables.render_data(
        [(value, value, value, value)],
        (header, header, header, header),
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert 'onerror="' not in html
    assert "&lt;img" in html


def test_single_column_becomes_a_plain_value_list() -> None:
    html = tables.render_data([("East",), ("North",)], ("region",))

    assert "<table" not in html
    assert "fn-kv-values" in html
    assert "<li>East</li>" in html
