"""Smoke tests that drive the real Streamlit script headlessly (APP-01, APP-02)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app.py"


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
    assert any("Upload a CSV" in i.value for i in at.info)


def test_sample_loads_profile_and_all_tabs() -> None:
    at = _sample(_started())
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Rows"] == "485" and metrics["Columns"] == "6"
    labels = [t.label for t in at.tabs]
    for name in ("Profile", "Cleaning", "Analysis", "Chat", "Report"):
        assert name in labels


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


def test_analysis_form_runs_a_step_and_shows_errors() -> None:
    at = _sample(_started())
    next(s for s in at.selectbox if s.label == "Analysis").select("summary_stats").run()
    form_columns = next(m for m in at.multiselect if m.label == "Numeric columns")
    form_columns.select("demand_mwh")
    next(b for b in at.button if b.label == "Run").click().run()
    assert not at.exception
    assert any("Rows used: 485 of 485" in t.value for t in at.text)
    # a step the dataset cannot support is reported, not raised
    next(s for s in at.selectbox if s.label == "Analysis").select("correlation").run()
    next(b for b in at.button if b.label == "Run").click().run()
    assert not at.exception and at.error


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
