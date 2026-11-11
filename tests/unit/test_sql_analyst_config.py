"""SQL Analyst provider error messages and configuration-driven upload cap."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ai_data_analyst.sql_agent.errors import LLMConfigurationError  # noqa: E402
from ai_data_analyst.sql_agent.schema import SchemaError  # noqa: E402
from ai_data_analyst.ui import sql_analyst  # noqa: E402


@dataclass
class _FakeUpload:
    name: str
    size: int
    content: bytes

    def getvalue(self) -> bytes:
        return self.content


def test_provider_error_message_names_provider_setting() -> None:
    message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("Unsupported LLM_PROVIDER value 'bogus'.")
    )

    assert "LLM_PROVIDER" in message
    assert "gemini" in message
    assert "ollama" in message


def test_api_key_error_message_names_api_key_setting() -> None:
    message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("LLM_API_KEY is not configured.")
    )

    assert "LLM_API_KEY" in message
    assert "LLM_PROVIDER" not in message


def test_configuration_messages_are_distinct_and_hide_secrets() -> None:
    provider_message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("Unsupported LLM_PROVIDER value 'bogus'.")
    )
    key_message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("LLM_API_KEY is not configured.")
    )
    secret = "sk-secret-value-123"
    leaked_message = sql_analyst._configuration_failure_message(
        LLMConfigurationError(f"LLM_API_KEY is not configured: {secret}")
    )

    assert provider_message != key_message
    for message in (provider_message, key_message, leaked_message):
        assert secret not in message


def test_configuration_messages_are_friendly_and_actionable() -> None:
    provider_message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("Unsupported LLM_PROVIDER value 'bogus'.")
    )
    key_message = sql_analyst._configuration_failure_message(
        LLMConfigurationError("LLM_API_KEY is not configured.")
    )

    # The page used to say the provider was "not yet implemented"; it now tells the
    # person which setting to change and that a restart is needed.
    for message in (provider_message, key_message):
        assert message.startswith("SQL generation is not set up yet.")
        assert message.endswith("and restart.")
        assert "not yet implemented" not in message.lower()
        assert "unavailable" not in message.lower()


def test_upload_over_configured_cap_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("AIDA_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024))
    monkeypatch.setattr(sql_analyst.st, "session_state", {})
    upload = _FakeUpload(
        name="too-big.db",
        size=2 * 1024 * 1024 + 1,
        content=b"x" * (2 * 1024 * 1024 + 1),
    )

    with pytest.raises(SchemaError) as exc_info:
        sql_analyst._save_uploaded_database(upload)

    assert "2 MB" in str(exc_info.value)


def test_upload_under_configured_cap_is_accepted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIDA_MAX_UPLOAD_BYTES", str(1024 * 1024))
    monkeypatch.setattr(sql_analyst.st, "session_state", {})
    database = tmp_path / "small.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records (id INTEGER)")
    content = database.read_bytes()
    upload = _FakeUpload(name="small.db", size=len(content), content=content)

    saved = sql_analyst._save_uploaded_database(upload)

    try:
        assert saved.is_file()
    finally:
        saved.unlink(missing_ok=True)
