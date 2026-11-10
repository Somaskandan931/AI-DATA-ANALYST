"""Streamlit entry point for the Auto-EDA and SQL Analyst workspaces."""

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("Install app dependencies with: pip install -e '.[app,dev]'") from exc

from ai_data_analyst.ui import layout
from ai_data_analyst.ui.access import require_access
from ai_data_analyst.ui.auto_eda import render as render_auto_eda
from ai_data_analyst.ui.sql_analyst import render as render_sql_analyst
from ai_data_analyst.ui.theme import apply_theme

st.set_page_config(page_title="AIDA", layout="wide")
apply_theme()
require_access()
layout.app_header("AIDA", "AI Data Analyst Agent: Auto-EDA + Natural-Language-to-SQL")

auto_eda, sql_analyst = st.tabs(["Auto-EDA", "SQL Analyst"])

with auto_eda:
    render_auto_eda()

with sql_analyst:
    render_sql_analyst()
