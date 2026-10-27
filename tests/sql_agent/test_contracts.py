import pytest
from pydantic import ValidationError

from ai_data_analyst.sql_agent.contracts import (
    MAX_SQL_LENGTH,
    ColumnSchema,
    SchemaSnapshot,
    SQLCandidate,
    TableSchema,
)


def _table(name="customers", cols=("id", "name")):
    return TableSchema(name=name, columns=tuple(ColumnSchema(name=c) for c in cols))


def test_sql_candidate_valid():
    candidate = SQLCandidate(sql="SELECT 1", question="how many?")
    assert candidate.sql == "SELECT 1"


@pytest.mark.parametrize("sql", ["", "   ", "\n\t"])
def test_sql_candidate_rejects_blank(sql):
    with pytest.raises(ValidationError):
        SQLCandidate(sql=sql)


def test_sql_candidate_rejects_oversized():
    with pytest.raises(ValidationError):
        SQLCandidate(sql="x" * (MAX_SQL_LENGTH + 1))


def test_contracts_are_frozen_and_forbid_extras():
    candidate = SQLCandidate(sql="SELECT 1")
    with pytest.raises(ValidationError):
        candidate.sql = "DROP TABLE x"
    with pytest.raises(ValidationError):
        SQLCandidate(sql="SELECT 1", unexpected="x")


def test_column_requires_name():
    with pytest.raises(ValidationError):
        ColumnSchema(name="")


def test_table_requires_columns():
    with pytest.raises(ValidationError):
        TableSchema(name="t", columns=())


def test_table_rejects_duplicate_columns_case_insensitive():
    with pytest.raises(ValidationError):
        _table(cols=("id", "ID"))


def test_snapshot_rejects_duplicate_tables_case_insensitive():
    with pytest.raises(ValidationError):
        SchemaSnapshot(tables=(_table("Orders"), _table("orders")))


def test_snapshot_lookups_are_case_insensitive():
    snapshot = SchemaSnapshot(tables=(_table(),))
    assert snapshot.has_table("CUSTOMERS")
    assert snapshot.has_column("Customers", "NAME")
    assert not snapshot.has_table("orders")
    assert not snapshot.has_column("customers", "email")
    assert not snapshot.has_column("orders", "id")
    assert snapshot.get_table("nope") is None


def test_empty_snapshot_allows_nothing():
    snapshot = SchemaSnapshot()
    assert snapshot.tables == ()
    assert not snapshot.has_table("anything")


# --- SQLValidationResult / ValidationViolation (Stage 2) ---------------------

from ai_data_analyst.sql_agent.contracts import (  # noqa: E402
    SQLValidationResult,
    ValidationViolation,
    ViolationCode,
)


def _violation(code=ViolationCode.NOT_SELECT):
    return ValidationViolation(code=code, message="Only a SELECT statement is allowed.")


def test_allowed_result_requires_sql_and_no_violations():
    ok = SQLValidationResult(allowed=True, normalized_sql="SELECT 1", referenced_tables=("t",))
    assert ok.allowed and ok.reason_codes == ()
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=True)
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=True, normalized_sql="  ")
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=True, normalized_sql="SELECT 1", violations=(_violation(),))


def test_denied_result_requires_violation_and_no_sql():
    denied = SQLValidationResult(allowed=False, violations=(_violation(),))
    assert denied.reason_codes == (ViolationCode.NOT_SELECT,)
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=False)
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=False, normalized_sql="SELECT 1", violations=(_violation(),))
    with pytest.raises(ValidationError):
        SQLValidationResult(allowed=False, referenced_tables=("t",), violations=(_violation(),))


def test_violation_message_must_be_non_empty_and_bounded():
    with pytest.raises(ValidationError):
        ValidationViolation(code=ViolationCode.PARSE_ERROR, message="")
    with pytest.raises(ValidationError):
        ValidationViolation(code=ViolationCode.PARSE_ERROR, message="x" * 201)
    with pytest.raises(ValidationError):
        ValidationViolation(code="not_a_code", message="m")