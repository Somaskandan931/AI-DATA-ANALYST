"""Evidence mapping, interpretation, provenance, and escaping checks (PR2)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ai_data_analyst.models import ColumnProfile, DatasetProfile
from ai_data_analyst.sql_agent.executor import SQLExecutionResult
from ai_data_analyst.ui.evidence import (
    SOURCE_LABELS,
    EvidenceSource,
    EvidenceView,
    OverviewFields,
    interpret_columns,
    interpret_duplicates,
    interpret_missing_cells,
    interpret_rows,
    overview_view,
    overview_view_from,
    query_result_view,
    render_evidence_view,
)

FIELDS = OverviewFields(
    row_count=485,
    column_count=6,
    missing_cells=16,
    duplicate_rows=5,
    numeric_columns=2,
    text_columns=3,
    date_columns=1,
    logical_columns=0,
    fingerprint="a" * 64,
    columns=(("demand_mwh", "float"), ("region", "string")),
    missing_by_column=(("demand_mwh", 4), ("temperature_c", 12)),
)


def test_sources_are_only_computed_and_query_result() -> None:
    assert {source.value for source in EvidenceSource} == {"computed", "query-result"}
    assert set(SOURCE_LABELS) == set(EvidenceSource)
    assert "AI EXPLANATION" not in SOURCE_LABELS.values()


def test_overview_view_maps_known_fields_and_interpretations() -> None:
    view = overview_view_from(FIELDS)

    assert [(card.label, card.value) for card in view.cards] == [
        ("Rows", "485"),
        ("Columns", "6"),
        ("Missing cells", "16"),
        ("Duplicate rows", "5"),
    ]
    assert [card.interpretation for card in view.cards] == [
        "Read from the uploaded file.",
        "6 columns: 2 numeric, 3 text, 1 date.",
        "16 cells are empty (0.5% of 2,910).",
        "5 rows repeat an earlier row.",
    ]
    assert all(card.source is EvidenceSource.COMPUTED for card in view.cards)


def test_rows_interpretation_names_the_source_without_repeating_the_count() -> None:
    view = overview_view_from(OverviewFields(row_count=485, source_name="sample_demand.csv"))

    assert view.cards[0].value == "485"
    assert view.cards[0].interpretation == "Read from sample_demand.csv."


def test_missing_fields_have_no_value_or_interpretation() -> None:
    view = overview_view_from(OverviewFields())

    assert [card.value for card in view.cards] == [None, None, None, None]
    assert [card.interpretation for card in view.cards] == [None, None, None, None]
    rendered = render_evidence_view(view)
    assert rendered.count("Not available") >= 4
    assert 'class="fn-footnote"' not in rendered


def test_interpretations_are_deterministic_one_liners() -> None:
    assert interpret_rows(OverviewFields(row_count=1)) == "Read from the uploaded file."
    assert interpret_columns(OverviewFields(column_count=None)) is None
    assert interpret_columns(OverviewFields(column_count=1)) == "1 column."
    assert (
        interpret_missing_cells(OverviewFields(missing_cells=1, row_count=1, column_count=4))
        == "1 cell is empty (25.0% of 4)."
    )
    assert interpret_duplicates(OverviewFields(duplicate_rows=0)) == (
        "No row repeats an earlier row."
    )
    assert interpret_duplicates(OverviewFields(duplicate_rows=1)) == (
        "1 row repeats an earlier row."
    )


def test_cards_use_one_highlight_and_a_linked_footnote_each() -> None:
    rendered = render_evidence_view(overview_view_from(FIELDS))
    articles = rendered.split("<article")[1:]

    assert len(articles) == 4
    assert all(article.count('class="fn-highlight"') == 1 for article in articles)
    for position in range(1, 5):
        assert f'id="fn-computed-from-overview-{position}"' in rendered
        assert f'href="#fn-computed-from-overview-{position}"' in rendered
    # One shared source is announced once beside the group label (layout.section_label),
    # so repeating a chip on all four cards would only add noise.
    assert rendered.count('class="fn-chip-shape"') == 0
    assert "COMPUTED" not in rendered


def test_mixed_sources_keep_one_chip_per_card() -> None:
    view = overview_view_from(FIELDS)
    mixed = EvidenceView(
        cards=(
            view.cards[0],
            replace(view.cards[1], source=EvidenceSource.QUERY_RESULT),
        ),
        key="mixed",
    )

    rendered = render_evidence_view(mixed)

    assert rendered.count('class="fn-chip-shape"') == 2
    assert "COMPUTED" in rendered and "QUERY RESULT" in rendered


def test_query_result_card_uses_query_result_chip() -> None:
    result = SQLExecutionResult(
        columns=("region", "rows"),
        rows=(("East", 3),),
        truncated=True,
    )
    view = query_result_view("count by region", "SELECT 1", result, max_rows=1000)

    card = view.cards[0]
    assert card.value == "1"
    assert card.source is EvidenceSource.QUERY_RESULT
    assert card.interpretation == "The result reached the 1,000-row display limit."
    rendered = render_evidence_view(view)
    assert "QUERY RESULT" in rendered
    assert "fn-source-chip--query-result" in rendered


def test_hostile_column_names_are_escaped() -> None:
    script = "<script>alert('x')</script>"
    image = '<img src=x onerror="alert(1)">'
    profile = DatasetProfile(
        dataset_fingerprint="b" * 64,
        row_count=1,
        column_count=2,
        duplicate_row_count=0,
        columns=(
            ColumnProfile(name=script, inferred_type="string", missing_count=0, unique_count=1),
            ColumnProfile(name=image, inferred_type="string", missing_count=1, unique_count=0),
        ),
    )

    rendered = render_evidence_view(overview_view(profile))

    assert "<script>" not in rendered
    assert script not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<img" not in rendered
    assert 'onerror="alert(1)"' not in rendered
    assert "&lt;img" in rendered


def test_hostile_question_and_sql_are_escaped() -> None:
    result = SQLExecutionResult(columns=("x",), rows=((1,),), truncated=False)
    rendered = render_evidence_view(
        query_result_view("<script>q</script>", '<img onerror="x">', result, max_rows=10)
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<img" not in rendered
    assert "&lt;img" in rendered


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (OverviewFields(column_count=0), "0 columns."),
        (OverviewFields(column_count=2, numeric_columns=2), "2 columns."),
    ],
)
def test_column_interpretation_handles_partial_type_counts(
    fields: OverviewFields, expected: str
) -> None:
    assert interpret_columns(fields) == expected
