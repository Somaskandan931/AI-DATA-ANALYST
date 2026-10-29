"""Streamlit entry point: the Auto-EDA workspace (M1). The SQL Analyst workspace is M2's."""

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("Install app dependencies with: pip install -e '.[app,dev]'") from exc

from ai_data_analyst.ui.auto_eda import render

st.set_page_config(page_title="AI Data Analyst Agent", layout="wide")
st.title("AI Data Analyst Agent")
st.caption("Auto-EDA + Natural-Language-to-SQL")

auto_eda, sql_analyst = st.tabs(["Auto-EDA", "SQL Analyst"])
with auto_eda:
    render()
with sql_analyst:
    st.info("The SQL Analyst workspace is built by M2 and is not connected yet.")
