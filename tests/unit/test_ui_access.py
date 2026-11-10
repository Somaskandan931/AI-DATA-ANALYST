"""The optional password gate: off by default, closed when a password is configured."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from ai_data_analyst.ui.access import password_matches  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app.py"


def _run() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=60).run()


def test_gate_is_off_without_a_password(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    at = _run()
    assert not at.exception
    assert len(at.tabs) == 2
    assert len(at.text_input) == 0 or all(box.label != "Password" for box in at.text_input)


def test_blank_password_leaves_the_gate_off(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "   ")
    at = _run()
    assert not at.exception
    assert len(at.tabs) == 2


def test_gate_hides_the_app_until_the_password_is_entered(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret-value")
    at = _run()
    assert not at.exception
    assert len(at.tabs) == 0
    assert [box.label for box in at.text_input] == ["Password"]

    at.text_input[0].input("wrong").run()
    assert len(at.tabs) == 0
    assert [e.value for e in at.error] == ["Incorrect password."]
    assert "s3cret-value" not in str(at.main)

    at.text_input[0].input("s3cret-value").run()
    assert not at.exception
    assert len(at.tabs) == 2


@pytest.mark.parametrize(
    ("candidate", "expected", "result"),
    [("abc", "abc", True), ("abd", "abc", False), ("", "abc", False), ("", "", False)],
)
def test_password_matches(candidate, expected, result):
    assert password_matches(candidate, expected) is result
