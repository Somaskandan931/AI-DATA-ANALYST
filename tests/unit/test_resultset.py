import math

import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation import (
    ResultSetComparison,
    ResultSetRules,
    compare_result_sets,
)


def _compare(
    actual_rows,
    expected_rows,
    *,
    actual_columns=("a",),
    expected_columns=None,
    rules=None,
    actual_truncated=False,
):
    if expected_columns is None:
        expected_columns = actual_columns
    return compare_result_sets(
        actual_columns,
        actual_rows,
        expected_columns,
        expected_rows,
        rules,
        actual_truncated=actual_truncated,
    )


@pytest.mark.parametrize("ordered", [True, False])
def test_identical_rows_match(ordered: bool):
    result = _compare([[1], [2]], [[1], [2]], rules=ResultSetRules(ordered=ordered))

    assert result.matches
    assert result.codes == ()
    assert result.examples == ()
    assert result.actual_row_count == 2
    assert result.expected_row_count == 2


def test_unordered_comparison_ignores_row_order():
    assert _compare([[2], [1]], [[1], [2]]).matches


def test_ordered_comparison_reports_every_mismatched_position():
    result = _compare([[2], [1]], [[1], [2]], rules=ResultSetRules(ordered=True))

    assert not result.matches
    assert result.codes == ("value_mismatch",)
    assert result.examples == (0, 1)


def test_duplicate_rows_matter_by_default():
    result = _compare([[1], [1]], [[1]])

    assert not result.matches
    assert result.codes == ("row_count_mismatch",)


def test_duplicate_rows_are_ignored_in_set_mode():
    rules = ResultSetRules(duplicates_matter=False)

    assert _compare([[1], [1]], [[1]], rules=rules).matches
    assert _compare([[1]], [[1], [1]], rules=rules).matches
    assert _compare([[1], [1], [2]], [[1], [2]], rules=rules).matches


def test_int_and_float_compare_numerically():
    assert _compare([[1]], [[1.0]]).matches
    assert _compare([[1.0]], [[1]]).matches


@pytest.mark.parametrize("ordered", [True, False])
def test_bool_equals_int_by_default(ordered: bool):
    rules = ResultSetRules(ordered=ordered)

    assert _compare([[True]], [[1]], rules=rules).matches
    assert _compare([[False]], [[0]], rules=rules).matches
    assert _compare([[True]], [[1.0]], rules=rules).matches
    assert _compare([[1]], [[True]], rules=rules).matches


@pytest.mark.parametrize("ordered", [True, False])
def test_bool_does_not_equal_int_when_disabled(ordered: bool):
    rules = ResultSetRules(ordered=ordered, bool_equals_int=False)

    assert _compare([[True]], [[1]], rules=rules).codes == ("value_mismatch",)
    assert _compare([[False]], [[0]], rules=rules).codes == ("value_mismatch",)


@pytest.mark.parametrize("bool_equals_int", [True, False])
@pytest.mark.parametrize("ordered", [True, False])
def test_true_never_equals_two(bool_equals_int: bool, ordered: bool):
    rules = ResultSetRules(ordered=ordered, bool_equals_int=bool_equals_int)

    assert _compare([[True]], [[2]], rules=rules).codes == ("value_mismatch",)
    assert _compare([[2]], [[True]], rules=rules).codes == ("value_mismatch",)


def test_unordered_sort_treats_bool_as_a_number_by_default():
    assert _compare([[True], [2]], [[1], [2]]).matches


def test_unordered_sort_keeps_bool_separate_when_disabled():
    rules = ResultSetRules(bool_equals_int=False)

    assert _compare([[True], [2]], [[1], [2]], rules=rules).codes == ("value_mismatch",)


def test_set_mode_canonicalizes_bools_as_numbers_by_default():
    rules = ResultSetRules(duplicates_matter=False)

    assert _compare([[True], [1]], [[1]], rules=rules).matches
    assert _compare([[False], [0]], [[0]], rules=rules).matches


def test_set_mode_keeps_bools_distinct_when_disabled():
    rules = ResultSetRules(duplicates_matter=False, bool_equals_int=False)

    assert _compare([[True], [1]], [[1]], rules=rules).codes == (
        "row_count_mismatch",
        "value_mismatch",
    )


def test_float_within_absolute_tolerance_matches():
    assert _compare([[1.0 + 5e-10]], [[1.0]]).matches


def test_float_just_outside_absolute_tolerance_is_a_mismatch():
    result = _compare([[1.0 + 2e-9]], [[1.0]])

    assert result.codes == ("value_mismatch",)


def test_zero_tolerance_requires_exact_numbers():
    result = _compare([[1.0 + 5e-10]], [[1.0]], rules=ResultSetRules(float_abs_tol=0.0))

    assert result.codes == ("value_mismatch",)


def test_relative_tolerance_boundary():
    within = ResultSetRules(float_abs_tol=0.0, float_rel_tol=0.005)
    outside = ResultSetRules(float_abs_tol=0.0, float_rel_tol=0.004)

    assert _compare([[1005.0]], [[1000.0]], rules=within).matches
    assert _compare([[1005.0]], [[1000.0]], rules=outside).codes == ("value_mismatch",)


def test_null_equals_null_when_enabled():
    assert _compare([[None]], [[None]]).matches


def test_null_does_not_equal_null_when_disabled():
    result = _compare([[None]], [[None]], rules=ResultSetRules(null_equals_null=False))

    assert result.codes == ("value_mismatch",)


def test_null_never_equals_a_value():
    result = _compare([[None]], [[1]])

    assert result.codes == ("value_mismatch",)


def test_column_names_compare_case_insensitively():
    assert _compare([[1]], [[1]], actual_columns=("A",), expected_columns=("a",)).matches


def test_column_order_is_exact():
    result = _compare(
        [[1, 2]],
        [[1, 2]],
        actual_columns=("a", "b"),
        expected_columns=("b", "a"),
    )

    assert result.codes == ("column_mismatch",)


def test_column_count_mismatch_is_reported():
    result = _compare([[1]], [[1]], actual_columns=("a",), expected_columns=("a", "b"))

    assert result.codes == ("column_mismatch",)


def test_row_count_mismatch_is_reported_without_value_mismatch():
    result = _compare([[1], [2]], [[1]])

    assert result.codes == ("row_count_mismatch",)
    assert result.actual_row_count == 2
    assert result.expected_row_count == 1


def test_truncated_result_never_matches():
    result = _compare([[1]], [[1]], actual_truncated=True)

    assert not result.matches
    assert result.codes == ("truncated",)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_invalid(bad: float):
    assert _compare([[bad]], [[1.0]]).codes == ("invalid_value",)
    assert _compare([[1.0]], [[bad]]).codes == ("invalid_value",)


def test_empty_results_match_each_other():
    result = _compare([], [])

    assert result.matches
    assert result.actual_row_count == 0
    assert result.expected_row_count == 0


def test_empty_actual_against_non_empty_expected_is_a_mismatch():
    assert _compare([], [[1]]).codes == ("row_count_mismatch",)


def test_examples_are_capped_at_ten():
    actual = [[index] for index in range(12)]
    expected = [[index + 100] for index in range(12)]

    result = _compare(actual, expected)

    assert result.codes == ("value_mismatch",)
    assert result.examples == tuple(range(10))


def test_rows_of_different_width_are_a_value_mismatch():
    result = _compare([[1]], [[1, 2]], actual_columns=("a", "b"))

    assert result.codes == ("value_mismatch",)


def test_set_mode_applies_the_float_tolerance():
    rules = ResultSetRules(duplicates_matter=False)

    assert _compare([[1.0 + 1e-12], [2.0]], [[2.0], [1.0]], rules=rules).matches


def test_codes_are_reported_in_a_stable_order():
    result = _compare(
        [[1], [2]],
        [[9]],
        actual_columns=("a",),
        expected_columns=("b",),
    )

    assert result.codes == ("column_mismatch", "row_count_mismatch")


@pytest.mark.parametrize("field_name", ["float_abs_tol", "float_rel_tol"])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_rules_reject_invalid_tolerances(field_name: str, value: float):
    with pytest.raises(ValidationError):
        ResultSetRules(**{field_name: value})


def test_rules_reject_unknown_fields_and_are_frozen():
    with pytest.raises(ValidationError):
        ResultSetRules(surprise=True)

    rules = ResultSetRules()
    with pytest.raises(ValidationError):
        rules.ordered = True


def test_comparison_model_rejects_unknown_codes():
    with pytest.raises(ValidationError):
        ResultSetComparison(
            matches=False,
            codes=("not_a_code",),
            actual_row_count=1,
            expected_row_count=1,
        )


def test_comparison_model_caps_examples_at_ten():
    with pytest.raises(ValidationError):
        ResultSetComparison(
            matches=False,
            actual_row_count=11,
            expected_row_count=11,
            examples=tuple(range(11)),
        )


def test_comparison_model_rejects_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        ResultSetComparison(
            matches=True,
            actual_row_count=0,
            expected_row_count=0,
            surprise=True,
        )

    comparison = ResultSetComparison(matches=True, actual_row_count=0, expected_row_count=0)
    with pytest.raises(ValidationError):
        comparison.matches = False


def test_rules_and_comparison_json_round_trip():
    rules = ResultSetRules(ordered=True, float_rel_tol=0.01, duplicates_matter=False)
    comparison = ResultSetComparison(
        matches=False,
        codes=("value_mismatch",),
        actual_row_count=2,
        expected_row_count=1,
        examples=(0,),
    )

    assert ResultSetRules.model_validate_json(rules.model_dump_json()) == rules
    assert ResultSetComparison.model_validate_json(comparison.model_dump_json()) == comparison


def test_nan_is_detected_before_comparison():
    result = _compare([[math.nan], [1.0]], [[1.0]])

    assert result.codes == ("row_count_mismatch", "invalid_value")
