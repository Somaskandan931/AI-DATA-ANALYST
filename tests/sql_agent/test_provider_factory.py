"""Provider selection and LLM configuration validation."""

import pytest

from ai_data_analyst.sql_agent import gemini_generator, ollama_generator, provider_factory
from ai_data_analyst.sql_agent.errors import LLMConfigurationError


class _FakeGemini:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeOllama:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(provider_factory, "load_dotenv", lambda: None)
    monkeypatch.setattr(gemini_generator, "load_dotenv", lambda: None)


def _patch_generators(monkeypatch):
    monkeypatch.setattr(gemini_generator, "GeminiSQLGenerator", _FakeGemini)
    monkeypatch.setattr(ollama_generator, "OllamaSQLGenerator", _FakeOllama)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_provider_defaults_to_gemini(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("LLM_PROVIDER", value)
    _patch_generators(monkeypatch)

    generator = provider_factory.create_sql_generator()

    assert isinstance(generator, _FakeGemini)


@pytest.mark.parametrize("value", ["Gemini", "GEMINI"])
def test_gemini_provider_is_case_insensitive(monkeypatch, value):
    monkeypatch.setenv("LLM_PROVIDER", value)
    _patch_generators(monkeypatch)

    generator = provider_factory.create_sql_generator()

    assert isinstance(generator, _FakeGemini)


@pytest.mark.parametrize("value", ["ollama", "OLLAMA", "Ollama"])
def test_ollama_provider_is_case_insensitive(monkeypatch, value):
    monkeypatch.setenv("LLM_PROVIDER", value)
    _patch_generators(monkeypatch)

    generator = provider_factory.create_sql_generator()

    assert isinstance(generator, _FakeOllama)
    assert generator.kwargs["model"] == "qwen2.5-coder:7b"


def test_unsupported_provider_raises_configuration_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bogus")

    with pytest.raises(LLMConfigurationError) as exc_info:
        provider_factory.create_sql_generator()

    assert isinstance(exc_info.value, ValueError)
    message = str(exc_info.value)
    assert "bogus" in message
    assert "gemini" in message
    assert "ollama" in message


@pytest.mark.parametrize("value", [None, "", "   "])
def test_gemini_requires_api_key(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("LLM_API_KEY", value)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(LLMConfigurationError) as exc_info:
        provider_factory.create_sql_generator()

    assert "LLM_API_KEY" in str(exc_info.value)


def test_api_key_never_appears_in_configuration_errors(monkeypatch):
    sentinel = "sk-sentinel-never-print-9f3c"
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    monkeypatch.setenv("LLM_API_KEY", sentinel)

    with pytest.raises(LLMConfigurationError) as exc_info:
        provider_factory.create_sql_generator()

    assert sentinel not in str(exc_info.value)
