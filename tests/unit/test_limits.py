import pytest
from pydantic import ValidationError

from ai_data_analyst.security import (
    DEFAULT_LIMITS,
    ENV_VARS,
    LimitExceededError,
    LimitsConfig,
    check_shape,
    check_upload_size,
)

LIMIT_FIELDS = [
    "max_upload_bytes",
    "max_rows",
    "max_columns",
    "max_execution_seconds",
    "sql_timeout_seconds",
    "max_result_rows",
]


def _limits(**overrides: object) -> LimitsConfig:
    fields: dict[str, object] = {
        "max_upload_bytes": 100,
        "max_rows": 10,
        "max_columns": 3,
        "max_execution_seconds": 1,
        "sql_timeout_seconds": 1,
        "max_result_rows": 5,
    }
    fields.update(overrides)
    return LimitsConfig(**fields)


def test_every_limit_has_one_default_and_one_env_var():
    assert set(LimitsConfig.model_fields) == set(DEFAULT_LIMITS) == set(ENV_VARS)


def test_defaults_are_positive():
    limits = LimitsConfig()
    for field_name in LIMIT_FIELDS:
        assert getattr(limits, field_name) == DEFAULT_LIMITS[field_name]
        assert getattr(limits, field_name) > 0


def test_limits_are_frozen():
    limits = LimitsConfig()
    with pytest.raises(ValidationError):
        limits.max_rows = 1


@pytest.mark.parametrize("field_name", LIMIT_FIELDS)
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_limits_are_rejected(field_name: str, value: int):
    with pytest.raises(ValidationError):
        LimitsConfig(**{field_name: value})


def test_from_env_uses_defaults_when_unset():
    assert LimitsConfig.from_env({}) == LimitsConfig()


def test_from_env_reads_all_overrides():
    environ = {env_name: str(index + 1) for index, env_name in enumerate(ENV_VARS.values())}
    limits = LimitsConfig.from_env(environ)
    for field_name, env_name in ENV_VARS.items():
        assert getattr(limits, field_name) == int(environ[env_name])


def test_from_env_ignores_unrelated_variables():
    assert LimitsConfig.from_env({"SOMETHING_ELSE": "1", "MAX_ROWS": "1"}) == LimitsConfig()


def test_from_env_reads_os_environ(monkeypatch):
    monkeypatch.setenv("AIDA_MAX_ROWS", "42")
    assert LimitsConfig.from_env().max_rows == 42


@pytest.mark.parametrize("field_name,env_name", ENV_VARS.items())
@pytest.mark.parametrize("raw", ["abc", "0", "-1", "1.5", "", "  "])
def test_bad_env_values_are_rejected_with_field_name(field_name: str, env_name: str, raw: str):
    with pytest.raises(ValueError) as exc_info:
        LimitsConfig.from_env({env_name: raw})
    message = str(exc_info.value)
    assert env_name in message
    assert field_name in message


def test_upload_size_at_limit_is_allowed():
    limits = _limits()
    check_upload_size(limits.max_upload_bytes, limits)


def test_upload_size_below_limit_is_allowed():
    limits = _limits()
    check_upload_size(1, limits)


def test_upload_size_over_limit_is_rejected():
    limits = _limits()
    with pytest.raises(LimitExceededError, match="max_upload_bytes=100"):
        check_upload_size(limits.max_upload_bytes + 1, limits)


def test_shape_at_limit_is_allowed():
    limits = _limits()
    check_shape(limits.max_rows, limits.max_columns, limits)


def test_shape_below_limit_is_allowed():
    limits = _limits()
    check_shape(1, 1, limits)


def test_rows_over_limit_are_rejected():
    limits = _limits()
    with pytest.raises(LimitExceededError, match="max_rows=10"):
        check_shape(limits.max_rows + 1, 1, limits)


def test_columns_over_limit_are_rejected():
    limits = _limits()
    with pytest.raises(LimitExceededError, match="max_columns=3"):
        check_shape(1, limits.max_columns + 1, limits)
