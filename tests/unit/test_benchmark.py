import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation import (
    REQUIRED_CATEGORIES,
    BenchmarkCase,
    BenchmarkSuite,
    category_counts,
    load_benchmark,
    missing_categories,
)

ROOT = Path(__file__).resolve().parents[2]
SQL_BENCHMARK = ROOT / "data" / "expected" / "sql_benchmark.json"

EXPECTED_CATEGORIES = {
    "simple_filters",
    "aggregation",
    "group_by_having",
    "joins",
    "null_behavior",
    "duplicates",
    "ctes",
    "window_functions",
    "empty_results",
    "ambiguous_wording",
    "disallowed_tables_columns",
    "write_statements",
    "multiple_statements",
    "comments_obfuscation",
    "resource_heavy_queries",
}


def _case(**overrides: object) -> BenchmarkCase:
    fields: dict[str, object] = {
        "id": "case-1",
        "category": "simple_filters",
        "question": "How many rows are there?",
        "expected_columns": ("n",),
        "expected_rows": ((1,),),
    }
    fields.update(overrides)
    return BenchmarkCase(**fields)


def _suite(**overrides: object) -> BenchmarkSuite:
    fields: dict[str, object] = {
        "benchmark_version": "1.0",
        "cases": (_case(),),
    }
    fields.update(overrides)
    return BenchmarkSuite(**fields)


def test_allowed_case_parses_with_expected_rows():
    case = _case()
    assert case.expected_outcome == "allowed"
    assert case.expected_columns == ("n",)
    assert case.expected_rows == ((1,),)
    assert case.order_matters is False
    assert case.reference_sql is None


def test_allowed_case_may_have_no_rows():
    case = _case(expected_rows=())
    assert case.expected_columns == ("n",)
    assert case.expected_rows == ()


def test_allowed_case_requires_columns():
    with pytest.raises(ValidationError):
        _case(expected_columns=())


def test_allowed_case_requires_every_row_to_match_column_count():
    with pytest.raises(ValidationError):
        _case(expected_columns=("a", "b"), expected_rows=((1,),))


def test_denied_case_requires_a_reason_code():
    with pytest.raises(ValidationError):
        _case(expected_outcome="denied", expected_columns=(), expected_rows=())


def test_denied_case_rejects_expected_columns():
    with pytest.raises(ValidationError):
        _case(
            expected_outcome="denied",
            expected_reason_code="unknown_table",
        )


def test_denied_case_rejects_expected_rows():
    with pytest.raises(ValidationError):
        _case(
            expected_outcome="denied",
            expected_reason_code="unknown_table",
            expected_columns=(),
            expected_rows=((1,),),
        )


def test_denied_case_parses():
    case = _case(
        expected_outcome="denied",
        expected_reason_code="unknown_table",
        expected_columns=(),
        expected_rows=(),
    )
    assert case.expected_reason_code == "unknown_table"


def test_clarify_case_rejects_expected_columns():
    with pytest.raises(ValidationError):
        _case(expected_outcome="clarify", expected_columns=("a",), expected_rows=())


def test_clarify_case_rejects_expected_rows():
    with pytest.raises(ValidationError):
        _case(expected_outcome="clarify", expected_columns=(), expected_rows=((1,),))


def test_clarify_case_parses():
    case = _case(expected_outcome="clarify", expected_columns=(), expected_rows=())
    assert case.expected_outcome == "clarify"


@pytest.mark.parametrize("case_id", ["", "-case", "case id", "a" * 65, "a."])
def test_case_id_pattern_rejects_invalid_ids(case_id: str):
    with pytest.raises(ValidationError):
        _case(id=case_id)


@pytest.mark.parametrize("case_id", ["a", "SQL-BENCH-01", "case_1", "a" * 64])
def test_case_id_pattern_accepts_valid_ids(case_id: str):
    assert _case(id=case_id).id == case_id


@pytest.mark.parametrize("category", ["", "Simple", "1simple", "a" * 65, "a-b"])
def test_category_pattern_rejects_invalid_names(category: str):
    with pytest.raises(ValidationError):
        _case(category=category)


@pytest.mark.parametrize("reason_code", ["", "Unknown", "1unknown", "a" * 65])
def test_reason_code_pattern_rejects_invalid_codes(reason_code: str):
    with pytest.raises(ValidationError):
        _case(
            expected_outcome="denied",
            expected_reason_code=reason_code,
            expected_columns=(),
            expected_rows=(),
        )


@pytest.mark.parametrize("question", ["", "x" * 1001])
def test_question_length_is_bounded(question: str):
    with pytest.raises(ValidationError):
        _case(question=question)


def test_question_may_be_1000_characters():
    assert len(_case(question="x" * 1000).question) == 1000


def test_expected_outcome_is_closed():
    with pytest.raises(ValidationError):
        _case(expected_outcome="maybe")


def test_scalar_values_keep_their_types():
    case = _case(
        expected_columns=("none", "bool", "int", "float", "str"),
        expected_rows=((None, True, 7, 7.5, "x"),),
    )
    row = case.expected_rows[0]
    assert row[0] is None
    assert type(row[1]) is bool
    assert type(row[2]) is int
    assert type(row[3]) is float
    assert type(row[4]) is str


def test_case_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        _case(surprise=1)

    case = _case()
    with pytest.raises(ValidationError):
        case.question = "other"


def test_suite_requires_at_least_one_case():
    with pytest.raises(ValidationError):
        _suite(cases=())


def test_suite_requires_a_version():
    with pytest.raises(ValidationError):
        _suite(benchmark_version="")


def test_suite_rejects_duplicate_case_ids():
    with pytest.raises(ValidationError):
        _suite(cases=(_case(), _case()))


def test_suite_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        _suite(surprise=1)

    suite = _suite()
    with pytest.raises(ValidationError):
        suite.description = "other"


def test_required_categories_are_the_expected_snake_case_names():
    assert len(REQUIRED_CATEGORIES) == 15
    assert set(REQUIRED_CATEGORIES) == EXPECTED_CATEGORIES
    assert len(set(REQUIRED_CATEGORIES)) == len(REQUIRED_CATEGORIES)
    for name in REQUIRED_CATEGORIES:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name)


def test_category_counts_and_missing_categories_use_exact_names():
    suite = _suite(
        cases=(
            _case(id="a", category="simple_filters"),
            _case(id="b", category="custom_name"),
        )
    )

    assert category_counts(suite) == {"custom_name": 1, "simple_filters": 1}
    missing = missing_categories(suite)
    assert missing[0] == "aggregation"
    assert "simple_filters" not in missing
    assert len(missing) == len(REQUIRED_CATEGORIES) - 1


def test_load_benchmark_reads_the_existing_sql_benchmark():
    suite = load_benchmark(SQL_BENCHMARK)

    assert suite.benchmark_version == "1.0"
    assert suite.cases
    assert {case.expected_outcome for case in suite.cases} == {"allowed"}


def test_load_benchmark_accepts_a_string_path(tmp_path: Path):
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "benchmark_version": "1.0",
                "cases": [
                    {
                        "id": "case-1",
                        "category": "simple_filters",
                        "question": "How many rows?",
                        "expected_columns": ["n"],
                        "expected_rows": [[1]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    suite = load_benchmark(str(path))

    assert suite.cases[0].expected_rows == ((1,),)


def test_load_benchmark_rejects_unknown_case_fields(tmp_path: Path):
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "benchmark_version": "1.0",
                "cases": [
                    {
                        "id": "case-1",
                        "category": "simple_filters",
                        "question": "How many rows?",
                        "expected_columns": ["n"],
                        "surprise": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_benchmark(path)


def test_case_and_suite_json_round_trip():
    case = _case(
        id="case-2",
        category="null_behavior",
        expected_columns=("a", "b"),
        expected_rows=((None, 1.5), (2, "x")),
        order_matters=True,
    )
    suite = _suite(cases=(case,))

    assert BenchmarkCase.model_validate_json(case.model_dump_json()) == case
    assert BenchmarkSuite.model_validate_json(suite.model_dump_json()) == suite
