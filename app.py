"""Streamlit entry point placeholder. UI implementation is scheduled after core services."""

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("Install app dependencies with: pip install -e '.[app,dev]'") from exc

st.set_page_config(page_title="AI Data Analyst Agent", layout="wide")
st.title("AI Data Analyst Agent")
st.caption("Auto-EDA + Natural-Language-to-SQL")
st.info("Foundation scaffold created. Implement deterministic ingestion and profiling first.")
