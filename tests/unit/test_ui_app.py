"""Smoke tests that drive the real Streamlit script headlessly (APP-01, APP-02)."""

from __future__ import annotations

import csv
import re
from html import escape
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from ai_data_analyst.sql_agent.errors import LLMConfigurationError  # noqa: E402
from ai_data_analyst.sql_agent.executor import SQLExecutionResult  # noqa: E402
from ai_data_analyst.sql_agent.pipeline import SQLPipelineResult  # noqa: E402
from ai_data_analyst.ui import sql_analyst  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app.py"
SAMPLE_PATH = Path(__file__).resolve().parents[2] / "data" / "sample" / "electricity_demand.csv"

_VISIBLE_TYPES = (
    "markdown",
    "caption",
    "text",
    "code",
    "info",
    "warning",
    "error",
    "success",
    "html",
    "expander",
    "button",
    "selectbox",
    "multiselect",
    "radio",
    "checkbox",
    "text_input",
    "text_area",
    "chat_input",
    "tabs",
    "number_input",
    "download_button",
    "file_uploader",
)
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
# Wording that once leaked module names and placeholder sections into the page.
_BANNED_VISIBLE = re.compile(r"\bM[12]\b|audit event|contract|stays empty|Not available", re.I)


def _visible_text(at: AppTest) -> str:
    """Every string a person can read; script and style bodies are not visible."""
    parts: list[str] = []
    for kind in _VISIBLE_TYPES:
        for element in at.get(kind):
            value = getattr(element, "value", None)
            if isinstance(value, str):
                parts.append(_SCRIPT_OR_STYLE.sub(" ", value))
            for attribute in ("label", "placeholder", "help"):
                text = getattr(element, attribute, None)
                if isinstance(text, str):
                    parts.append(text)
            options = getattr(element, "options", None)
            if options:
                parts.extend(str(option) for option in options)
    return "\n".join(parts)


def _assert_no_internal_jargon(at: AppTest) -> None:
    match = _BANNED_VISIBLE.search(_visible_text(at))
    assert match is None, f"internal jargon {match.group(0)!r} is visible"


def _raise_configuration_error() -> None:
    raise LLMConfigurationError("LLM_API_KEY is not configured.")


def _started() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    return at


def _sample(at: AppTest) -> AppTest:
    button = next(b for b in at.button if b.label == "Use the sample dataset")
    at = button.click().run()
    assert not at.exception
    return at


def test_starts_empty_with_both_workspaces() -> None:
    at = _started()
    assert [t.label for t in at.tabs][:2] == ["Auto-EDA", "SQL Analyst"]
    hero = next(h.value for h in at.html if "fn-empty-hero" in h.value)
    assert "Field Notes" in hero and "A quiet workspace for your data." in hero
    assert not any(
        "Upload a CSV file or use the sample dataset to begin." in i.value for i in at.info
    )


def test_sample_loads_overview_and_all_tabs() -> None:
    at = _sample(_started())
    overview = next(h.value for h in at.html if "fn-card-grid" in h.value)
    assert '<span class="fn-highlight">485</span>' in overview
    assert '<span class="fn-highlight">6</span>' in overview
    assert overview.count('class="fn-evidence-card"') == 4
    labels = [t.label for t in at.tabs]
    for name in ("Profile", "Cleaning", "Analysis", "Chat", "Report"):
        assert name in labels


def test_overview_and_inspector_show_provenance() -> None:
    at = _sample(_started())
    assert "Inspector" in [e.label for e in at.expander]
    # The inspector now renders stacked definition lists in one escaped HTML fragment,
    # so its fields are asserted on the fragment instead of on st.text lines.
    inspector = next(
        h.value for h in at.html if "fn-inspector" in h.value and "Dataset fingerprint" in h.value
    )
    fingerprint = re.search(r'title="([0-9a-f]{64})"', inspector)
    assert fingerprint is not None
    full = fingerprint.group(1)
    assert f">{full[:12]}<" in inspector
    assert f'title="{full}"' in inspector
    assert inspector.count(full) == 2  # the title attribute and the details block
    assert "<dt>Profile</dt>" in inspector
    assert "<dt>Max upload size</dt><dd>25 MB</dd>" in inspector
    assert "<dt>Upload accepted</dt><dd>1 time</dd>" in inspector
    assert "M1 audit events" not in inspector
    assert "SQL audit events" not in inspector


def test_profile_splits_columns_and_numeric_summary_and_previews_html_rows() -> None:
    # The profile is now two HTML tables (Columns and Numeric summary) and the preview
    # is an HTML table too, so no st.dataframe remains on the Profile tab
    # (UI fix, items 2 and 3).
    at = _sample(_started())
    tables = [h.value for h in at.html if '<table class="fn-table">' in h.value]

    columns_table = next(table for table in tables if '<th scope="col">Range</th>' in table)
    assert '<th scope="col">Column</th>' in columns_table
    assert '<th scope="col">Type</th>' in columns_table
    assert '<th scope="col" class="fn-num">Missing</th>' in columns_table
    assert '<th scope="col" class="fn-num">Unique</th>' in columns_table
    assert "2025-01-01 – 2025-04-30" in columns_table
    assert "Mean" not in columns_table

    numeric_table = next(
        table for table in tables if '<th scope="col" class="fn-num">Outliers</th>' in table
    )
    for label in ("Min", "Max", "Mean", "Median", "Std", "Q1", "Q3"):
        assert f'<th scope="col" class="fn-num">{label}</th>' in numeric_table
    assert '<th scope="row">demand_mwh</th>' in numeric_table
    assert '<th scope="row">temperature_c</th>' in numeric_table
    assert '<th scope="row">date</th>' not in numeric_table
    assert '<td class="fn-num">1,121.20</td>' in numeric_table

    preview = next(table for table in tables if "First 10 rows, exactly as uploaded." in table)
    assert preview.count('<th scope="row">') == 10
    assert len(at.dataframe) == 0


def test_profile_preview_matches_the_raw_csv_cells() -> None:
    # Compare the preview against the sample bytes, not another formatted view: the
    # uploaded text "906.3"/"1186.7" must survive unchanged (UI fix, item 1).
    at = _sample(_started())
    preview = next(h.value for h in at.html if "First 10 rows, exactly as uploaded." in h.value)
    with SAMPLE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))[:11]  # header and the first ten data rows

    for row in rows:
        for cell in row:
            assert f">{escape(cell)}<" in preview

    assert ">906.3<" in preview and ">1186.7<" in preview
    assert "906.30" not in preview
    assert "1,186.70" not in preview


def test_sql_inspector_names_the_database_tables_and_query_limits() -> None:
    at = _started()
    inspector = next(
        h.value for h in at.html if "fn-inspector" in h.value and "fn-inspector-row" in h.value
    )

    assert "<dt>electricity_demand</dt><dd>6 columns</dd>" in inspector
    assert "<dt>SQL timeout</dt><dd>5 s</dd>" in inspector
    assert "<dt>Max result rows</dt><dd>1,000</dd>" in inspector
    # The rail's DATABASE section already names the database (UI fix, item 6).
    assert "Selected database" not in inspector
    assert "Electricity Demand Sample" not in inspector
    assert "Dataset fingerprint" not in inspector
    assert "Cleaning" not in inspector
    assert "<dt>Profile</dt>" not in inspector


def test_each_inner_tab_has_an_editorial_header() -> None:
    at = _sample(_started())
    headers = [h.value for h in at.html if "fn-page-heading" in h.value]
    for section in ("Profile", "Cleaning", "Analysis", "Chat", "Report"):
        assert any(f">{section}</p>" in header and "fn-page-title" in header for header in headers)


def test_overview_animates_only_on_first_render() -> None:
    at = _sample(_started())
    first = next(h.value for h in at.html if "fn-card-grid" in h.value)
    assert "fn-fresh" in first

    at = at.run()
    second = next(h.value for h in at.html if "fn-card-grid" in h.value)
    assert "fn-fresh" not in second


def test_loaded_dataset_replaces_the_primary_cta_with_a_quiet_action() -> None:
    at = _sample(_started())
    labels = [b.label for b in at.button]

    assert "Replace dataset" in labels
    assert "Use the sample dataset" not in labels


def test_overview_group_announces_one_shared_source() -> None:
    at = _sample(_started())
    overview = next(h.value for h in at.html if "fn-card-grid" in h.value)
    heads = [h.value for h in at.html if "fn-section-head" in h.value]

    assert any("Overview" in head and "COMPUTED" in head for head in heads)
    assert 'class="fn-chip-shape"' not in overview


def test_hero_intro_runs_once_per_session() -> None:
    at = _started()
    first = next(h.value for h in at.html if "fn-empty-hero" in h.value)
    assert "fn-intro" in first

    at = at.run()
    second = next(h.value for h in at.html if "fn-empty-hero" in h.value)
    assert "fn-intro" not in second


def test_analysis_result_shows_computed_from() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    next(m for m in at.multiselect if m.label == "Numeric columns").select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()

    assert not at.exception
    computed = next(h.value for h in at.html if "<dt>Operation</dt>" in h.value)
    assert "<summary>Computed from</summary>" in computed
    assert "<dd>summary_stats</dd>" in computed
    assert "Analyses: 1" in [t.value for t in at.text]


def test_chat_answers_from_computed_results() -> None:
    at = _sample(_started())
    at.chat_input[0].set_value("average demand_mwh by region").run()
    assert not at.exception
    texts = [t.value for t in at.text]
    assert any(t.startswith("demand_mwh by region") and "East: mean" in t for t in texts)
    assert any("1 analyses included" in t for t in texts)


def test_unsupported_question_is_explained_not_an_error() -> None:
    at = _sample(_started())
    at.chat_input[0].set_value("what is the weather").run()
    assert not at.exception and not at.error
    assert any("Supported questions" in t.value for t in at.text)


def test_grouped_aggregation_uses_the_table_and_one_compact_count_line() -> None:
    # Several group rows keep the standard table, and the two count facts collapse into
    # one compact line (UI fix, item 4).
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("grouped_aggregation").run()
    next(m for m in at.multiselect if m.label == "Group by (up to 3)").select("region")
    next(s for s in at.selectbox if s.label == "Value column").select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()

    assert not at.exception
    table = next(h.value for h in at.html if "Aggregations of demand_mwh" in h.value)
    assert '<table class="fn-table">' in table
    assert "fn-kv-list" not in table
    assert '<th scope="row">East</th>' in table
    assert '<td class="fn-num">879.76</td>' in table

    line = next(h.value for h in at.html if "fn-result-line" in h.value)
    assert "4 groups · 4 shown" in line
    assert not any(t.value.startswith("Total groups:") for t in at.text)
    assert not any(t.value.startswith("Groups shown:") for t in at.text)


def test_summary_statistics_with_several_columns_keep_the_html_table() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    numeric = next(m for m in at.multiselect if m.label == "Numeric columns")
    numeric.select("demand_mwh")
    numeric.select("temperature_c")
    next(b for b in at.button if b.label == "Run").click().run()

    assert not at.exception
    table = next(h.value for h in at.html if "Statistics over non-missing values" in h.value)
    assert '<table class="fn-table">' in table
    assert '<th scope="col">Column</th>' in table
    assert '<th scope="col" class="fn-num">Mean</th>' in table
    assert '<th scope="row">demand_mwh</th>' in table
    assert '<th scope="row">temperature_c</th>' in table
    assert '<td class="fn-num">1,121.20</td>' in table


def test_sql_page_names_the_database_once() -> None:
    # The rail's DATABASE section is the only place the human database name appears;
    # the old "Selected database:" line and Inspector row are gone (UI fix, item 6).
    at = _started()
    assert _visible_text(at).count("Electricity Demand Sample") == 1


def test_sql_result_survives_an_unrelated_rerun_and_clears_on_source_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The workspace shell must not lose the last query when another tab reruns, and
    # must drop it as soon as the analyst is pointed at a different source.
    details = SQLPipelineResult(
        normalized_sql="SELECT 1 AS x",
        execution=SQLExecutionResult(columns=("x",), rows=((1,),), truncated=False),
    )
    monkeypatch.setattr(sql_analyst, "create_sql_generator", lambda: object())
    monkeypatch.setattr(sql_analyst, "run_sql_pipeline_with_details", lambda **_kwargs: details)

    at = _started()
    next(t for t in at.text_area if t.label == "Ask a question about your database").set_value(
        "How many rows?"
    ).run()
    next(b for b in at.button if b.label == "Generate SQL and Run").click().run()

    assert not at.exception
    assert "Query executed successfully." in _visible_text(at)
    assert "Question: How many rows?" in _visible_text(at)

    # Loading the Auto-EDA sample is an unrelated widget rerun for the SQL tab.
    at = _sample(at)
    assert "Query executed successfully." in _visible_text(at)
    assert "Question: How many rows?" in _visible_text(at)

    next(r for r in at.radio if r.label == "Choose database source").set_value(
        "Upload SQLite database"
    ).run()

    assert not at.exception
    assert "Query executed successfully." not in _visible_text(at)
    assert "Question: How many rows?" not in _visible_text(at)


def test_no_internal_jargon_is_visible_in_empty_loaded_and_error_states(monkeypatch) -> None:
    empty = _started()
    _assert_no_internal_jargon(empty)
    next(r for r in empty.radio if r.label == "Choose database source").set_value(
        "Upload SQLite database"
    ).run()
    _assert_no_internal_jargon(empty)

    loaded = _sample(_started())
    _assert_no_internal_jargon(loaded)

    analysis_error = _sample(_started())
    next(s for s in analysis_error.selectbox if s.label == "Analysis").select("correlation").run()
    next(b for b in analysis_error.button if b.label == "Run").click().run()
    assert analysis_error.error
    _assert_no_internal_jargon(analysis_error)

    monkeypatch.setattr(sql_analyst, "create_sql_generator", _raise_configuration_error)
    provider_error = _started()
    next(
        t for t in provider_error.text_area if t.label == "Ask a question about your database"
    ).set_value("How many rows?").run()
    next(b for b in provider_error.button if b.label == "Generate SQL and Run").click().run()
    assert provider_error.error
    assert "SQL generation is not set up yet" in provider_error.error[0].value
    _assert_no_internal_jargon(provider_error)


def test_analysis_form_runs_a_step_and_shows_errors() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    form_columns = next(m for m in at.multiselect if m.label == "Numeric columns")
    form_columns.select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()
    assert not at.exception
    # "Rows used" is now a provenance field, so the figure appears once inside
    # "Computed from" instead of also being repeated as a standalone fact line.
    computed = next(h.value for h in at.html if "<dt>Rows used</dt>" in h.value)
    assert computed.count("<dt>Rows used</dt>") == 1
    assert '<dd><span class="fn-highlight">485 of 485</span></dd>' in computed
    assert not any("Rows used:" in t.value for t in at.text)
    # a step the dataset cannot support is reported, not raised
    next(s for s in at.selectbox if s.label == "Analysis").select("correlation").run()
    next(b for b in at.button if b.label == "Run").click().run()
    assert not at.exception and at.error


def test_analysis_result_arrival_is_not_replayed_on_a_harmless_rerun() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    next(m for m in at.multiselect if m.label == "Numeric columns").select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()

    first = next(h.value for h in at.html if "fn-result-marker" in h.value)
    assert "fn-fresh" in first

    at = at.run()
    second = next(h.value for h in at.html if "fn-result-marker" in h.value)
    assert "fn-fresh" not in second


def test_chat_error_stays_visible() -> None:
    at = _sample(_started())
    at.chat_input[0].set_value("x" * 2500).run()
    assert not at.exception
    assert any("longer than 2000" in e.value for e in at.error)


def test_result_heading_has_one_step_prefix() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    next(m for m in at.multiselect if m.label == "Numeric columns").select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()
    labels = [e.label for e in at.expander if "Summary statistics" in e.label]
    assert labels == ["Step 1: Summary statistics"]
