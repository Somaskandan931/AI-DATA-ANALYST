"""Optional shared-password gate for hosted deployments.

When ``APP_PASSWORD`` is unset or blank the gate is off and the app is open (local use).
When it is set, nothing else renders until the visitor enters the matching password.
The password is compared in constant time and is never written to the page or logs.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st

PASSWORD_ENV_VAR = "APP_PASSWORD"
_AUTHENTICATED_KEY = "access_granted"


def configured_password() -> str:
    """Return the configured password, or an empty string when the gate is off."""
    return os.environ.get(PASSWORD_ENV_VAR, "").strip()


def password_matches(candidate: str, expected: str) -> bool:
    """Compare two passwords in constant time. An empty *expected* never matches."""
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def require_access() -> None:
    """Stop the script run unless the visitor is allowed in."""
    expected = configured_password()
    if not expected or st.session_state.get(_AUTHENTICATED_KEY):
        return

    st.title("AI Data Analyst Agent")
    st.caption("This deployment is password protected.")
    entered = st.text_input("Password", type="password", key="access_password")
    if entered:
        if password_matches(entered, expected):
            st.session_state[_AUTHENTICATED_KEY] = True
            st.rerun()
        st.error("Incorrect password.")
    st.stop()
