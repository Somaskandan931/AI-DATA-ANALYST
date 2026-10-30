# Row-filter contract (proposed, agreed in principle, not implemented)

## Ownership

The filter type and all filter code belong to M1 (`analysis/`); this document is the contract the
shared-infrastructure owner reviews against. Cleaning stays dataset-wide. Filters are per step and
apply after cleaning, to the working view, before the operation. Original data is never modified.

Chat understanding of filter questions is out of scope. Chat keeps refusing subset questions until
the typed filter works through the plan.

## Shape

Each analysis step gets an optional `filters` tuple (default empty, at most 5). A filter is
`column`, `operator`, `value`.

## Operators

`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `is_null`, `not_null`. Filters combine with AND only.
A range is `gte` plus `lt` on the same column. Exact duplicate filters are rejected.

## Validation against the `DatasetProfile`

- The column must exist.
- `gt`, `gte`, `lt`, `lte` only on integer, float and date columns.
- Values are typed to the column; dates are `YYYY-MM-DD`.
- `in` takes 1 to 20 unique values.
- `is_null` and `not_null` take no value.

## Missing values

Every comparison operator, including `ne`, excludes rows where the column is missing. `is_null`
is the only way to select them.

## Not allowed

Expressions, column-to-column comparison, regex or `like`, free text, anything executed as code.
Filters are applied as boolean masks built from typed values.

## Empty result

Not an error. The step returns an artifact with zero rows used and a warning.

## Provenance

The artifact's `parameters` echoes the filters. `rows_in_dataset` is the pre-filter row count;
`rows_used` is post-filter.

## Display

Chart subtitles and report text render from the typed filter, never from user text.

## Audit

Events carry only a `subject_hash` of the canonical filters (use
`security.hashing.hash_canonical_json`), never values. Rejection reason codes:
`filter_unknown_column`, `filter_bad_operator`, `filter_type_mismatch`, `filter_bad_value`,
`filter_too_many`.

## Versioning

Adding the field bumps `ANALYSIS_SCHEMA_VERSION`. No plans are persisted yet.

## Required tests (for the M1 owner's PR)

- Each rejection code.
- NULL semantics for every operator.
- Empty result with a warning.
- Provenance counts.
- Chart subtitle and report text rendering.
- Chat still refusing subset questions.
