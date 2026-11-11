"""Small HTML helpers for the theme.

Anything that shows data through HTML must pass through :func:`escape_text`; use native
Streamlit elements for interactive content.
"""

from __future__ import annotations

from html import escape

import streamlit as st


def escape_text(value: object) -> str:
    """Escape arbitrary text for safe insertion into an HTML fragment."""
    return escape(str(value), quote=True)


def render_escaped_text(text: str, *, class_name: str = "fn-prose") -> None:
    """Render plain text in a paragraph without allowing it to become markup."""
    st.html(f'<p class="{escape_text(class_name)}">{escape_text(text)}</p>')
