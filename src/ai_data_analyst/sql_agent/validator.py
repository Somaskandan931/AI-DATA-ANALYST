"""Deterministic, default-deny validation of untrusted SQL (Stage 2).

``validate_sql`` parses a ``SQLCandidate`` with sqlglot (SQLite dialect),
inspects the syntax tree, and checks every table and column against a
``SchemaSnapshot``. It never executes SQL and never touches a database.

How it decides:
  1. Parse exactly one statement whose root is a plain SELECT.
  2. Allow only explicitly reviewed syntax-tree node types and options.
  3. Check every physical table against the schema snapshot.
  4. Resolve columns against the snapshot and independently re-check them.
  5. Re-validate normalized SQL and require a stable fixed point.

Denial messages never echo the candidate SQL.
"""

from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
    ValidationViolation,
    ViolationCode,
    fold_identifier,
)

_DIALECT = "sqlite"
MAX_AST_NODES = 2_000

_ALLOWED_NODES: frozenset[type[exp.Expr]] = frozenset(
    {
        # Structure
        exp.Select,
        exp.From,
        exp.Table,
        exp.TableAlias,
        exp.Join,
        exp.Where,
        exp.Group,
        exp.Having,
        exp.Order,
        exp.Ordered,
        exp.Limit,
        exp.Offset,
        exp.With,
        exp.CTE,
        exp.Subquery,
        exp.Distinct,
        # Names and values
        exp.Identifier,
        exp.Column,
        exp.Alias,
        exp.Star,
        exp.Literal,
        exp.Boolean,
        exp.Null,
        exp.Placeholder,
        exp.Tuple,
        exp.Paren,
        # Operators
        exp.EQ,
        exp.NEQ,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.And,
        exp.Or,
        exp.Not,
        exp.Is,
        exp.In,
        exp.Between,
        exp.Exists,
        exp.Like,
        exp.Glob,
        exp.Escape,
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Neg,
        exp.DPipe,
        # Expressions
        exp.Window,
        exp.Case,
        exp.If,
        exp.Cast,
        exp.DataType,
        # Functions
        exp.Count,
        exp.Sum,
        exp.Avg,
        exp.Min,
        exp.Max,
        exp.Abs,
        exp.Round,
        exp.Length,
        exp.Lower,
        exp.Upper,
        exp.Substring,
        exp.Trim,
        exp.Replace,
        exp.Coalesce,
        exp.Nullif,
    }
)

_ALLOWED_ARGS: dict[type[exp.Expr], frozenset[str]] = {
    exp.Select: frozenset(
        {
            "expressions",
            "from",
            "from_",
            "joins",
            "where",
            "group",
            "having",
            "order",
            "limit",
            "offset",
            "with",
            "with_",
            "distinct",
        }
    ),
    exp.Join: frozenset({"this", "side", "kind", "on"}),
    exp.Table: frozenset({"this", "alias"}),
    exp.With: frozenset({"expressions"}),
    exp.CTE: frozenset({"this", "alias"}),
    exp.Subquery: frozenset({"this", "alias"}),
    exp.Group: frozenset({"expressions"}),
    exp.Order: frozenset({"expressions"}),
}

_MESSAGES = {
    "parse": "The SQL could not be parsed.",
    "none": "No SQL statement was found.",
    "multi": "Only one SQL statement is allowed.",
    "not_select": "Only a SELECT statement is allowed.",
    "setop": "Set operations (UNION, INTERSECT, EXCEPT) are not supported.",
    "nul": "The SQL contains a NUL character.",
    "complex": "The SQL is too large or too deeply nested.",
    "table": "The query references a table that is not allowed.",
    "qualified": "Schema-qualified table names are not allowed.",
    "column": ("The query references a column that is unknown, not allowed, or ambiguous."),
    "star": "Unexpanded wildcard (*) is not allowed.",
    "func": "A function or expression that is not on the allow-list was used.",
    "internal": "The query could not be verified and was denied.",
}


class _Analysis:
    def __init__(self) -> None:
        self.violations: list[ValidationViolation] = []
        self.normalized_sql: str | None = None
        self.tables: tuple[str, ...] = ()

    def deny(self, code: ViolationCode, message: str) -> None:
        violation = ValidationViolation(code=code, message=message)
        if violation not in self.violations and len(self.violations) < 20:
            self.violations.append(violation)


def validate_sql(
    candidate: SQLCandidate,
    snapshot: SchemaSnapshot,
) -> SQLValidationResult:
    """Return an allow/deny decision for ``candidate`` under ``snapshot``.

    Any unexpected error inside the validator results in a denial.
    """
    try:
        first = _analyze(candidate.sql, snapshot, final=False)
        if first.violations or first.normalized_sql is None:
            return _denied(first)

        # Fixed-point check: what would run must itself validate, unchanged.
        second = _analyze(first.normalized_sql, snapshot, final=True)
        if second.violations or second.normalized_sql != first.normalized_sql:
            denied = _Analysis()
            denied.deny(
                ViolationCode.INTERNAL_CHECK_FAILED,
                _MESSAGES["internal"],
            )
            return _denied(denied)

        return SQLValidationResult(
            allowed=True,
            normalized_sql=first.normalized_sql,
            referenced_tables=first.tables,
        )
    except Exception:
        # Default deny: never let a validator bug allow SQL.
        failed = _Analysis()
        failed.deny(
            ViolationCode.INTERNAL_CHECK_FAILED,
            _MESSAGES["internal"],
        )
        return _denied(failed)


def _denied(analysis: _Analysis) -> SQLValidationResult:
    violations = analysis.violations or [
        ValidationViolation(
            code=ViolationCode.INTERNAL_CHECK_FAILED,
            message=_MESSAGES["internal"],
        )
    ]
    return SQLValidationResult(
        allowed=False,
        violations=tuple(violations),
    )


def _analyze(
    sql: str,
    snapshot: SchemaSnapshot,
    final: bool,
) -> _Analysis:
    result = _Analysis()

    if "\x00" in sql:
        result.deny(ViolationCode.PARSE_ERROR, _MESSAGES["nul"])
        return result

    root = _parse_single_statement(sql, result)
    if root is None:
        return result

    if not _check_root(root, result):
        return result
    if not _check_nodes(root, result, allow_projection_star=not final):
        return result

    tables = _check_tables(root, snapshot, result)
    if result.violations:
        return result

    qualified = _qualify(root, snapshot, result)
    if qualified is None:
        return result
    if not _check_nodes(qualified, result, allow_projection_star=False):
        return result
    if not _check_columns(qualified, snapshot, result):
        return result

    try:
        result.normalized_sql = qualified.sql(
            dialect=_DIALECT,
            comments=False,
        )
    except Exception:
        result.deny(
            ViolationCode.INTERNAL_CHECK_FAILED,
            _MESSAGES["internal"],
        )
        return result

    result.tables = tuple(sorted(tables, key=fold_identifier))
    return result


def _parse_single_statement(
    sql: str,
    result: _Analysis,
) -> exp.Expr | None:
    try:
        statements = sqlglot.parse(sql, read=_DIALECT)
    except RecursionError:
        result.deny(ViolationCode.TOO_COMPLEX, _MESSAGES["complex"])
        return None
    except Exception:
        result.deny(ViolationCode.PARSE_ERROR, _MESSAGES["parse"])
        return None

    statements = [statement for statement in statements if statement is not None]
    if not statements:
        result.deny(ViolationCode.PARSE_ERROR, _MESSAGES["none"])
        return None
    if len(statements) > 1:
        result.deny(ViolationCode.MULTIPLE_STATEMENTS, _MESSAGES["multi"])
        return None

    return statements[0]


def _check_root(root: exp.Expr, result: _Analysis) -> bool:
    if type(root) is exp.Select:
        return True

    if isinstance(root, exp.SetOperation):
        result.deny(ViolationCode.UNSUPPORTED_SYNTAX, _MESSAGES["setop"])
    else:
        result.deny(ViolationCode.NOT_SELECT, _MESSAGES["not_select"])

    return False


def _present(value: object) -> bool:
    return not (
        value is None
        or value is False
        or value == ""
        or (isinstance(value, (list, tuple)) and not value)
    )


def _check_nodes(
    root: exp.Expr,
    result: _Analysis,
    allow_projection_star: bool,
) -> bool:
    count = 0

    for node in root.walk():
        count += 1
        if count > MAX_AST_NODES:
            result.deny(ViolationCode.TOO_COMPLEX, _MESSAGES["complex"])
            return False

        kind = type(node)
        if kind not in _ALLOWED_NODES:
            if kind is exp.Anonymous:
                result.deny(ViolationCode.UNSUPPORTED_SYNTAX, _MESSAGES["func"])
            else:
                result.deny(
                    ViolationCode.UNSUPPORTED_SYNTAX,
                    f"Unsupported SQL construct: {kind.__name__}.",
                )
            continue

        allowed_args = _ALLOWED_ARGS.get(kind)
        if allowed_args is not None:
            for key, value in node.args.items():
                if not _present(value) or key in allowed_args:
                    continue

                if kind is exp.Table and key in ("db", "catalog"):
                    result.deny(
                        ViolationCode.UNSUPPORTED_SYNTAX,
                        _MESSAGES["qualified"],
                    )
                else:
                    result.deny(
                        ViolationCode.UNSUPPORTED_SYNTAX,
                        f"Unsupported option '{key}' on {kind.__name__}.",
                    )

        if kind is exp.Table:
            if type(node.this) is not exp.Identifier:
                result.deny(
                    ViolationCode.UNSUPPORTED_SYNTAX,
                    _MESSAGES["func"],
                )

            alias = node.args.get("alias")
            if alias is not None and _present(alias.args.get("columns")):
                result.deny(
                    ViolationCode.UNSUPPORTED_SYNTAX,
                    "Column aliases on a table are not supported.",
                )

        elif kind is exp.TableAlias:
            present_args = {key for key, value in node.args.items() if _present(value)}
            if not present_args <= {"this", "columns"}:
                result.deny(
                    ViolationCode.UNSUPPORTED_SYNTAX,
                    "Unsupported table alias form.",
                )

        elif kind is exp.Star:
            parent_type = type(node.parent)
            allowed = parent_type is exp.Count or (
                allow_projection_star and parent_type in (exp.Select, exp.Column)
            )
            if not allowed:
                result.deny(
                    ViolationCode.UNSUPPORTED_SYNTAX,
                    _MESSAGES["star"],
                )

    return not result.violations


def _check_tables(
    root: exp.Expr,
    snapshot: SchemaSnapshot,
    result: _Analysis,
) -> set[str]:
    physical: set[str] = set()
    seen_ids: set[int] = set()

    try:
        scopes = traverse_scope(root)
    except Exception:
        result.deny(
            ViolationCode.INTERNAL_CHECK_FAILED,
            _MESSAGES["internal"],
        )
        return physical

    for scope in scopes:
        cte_names = {fold_identifier(name) for name in scope.cte_sources}

        for table in scope.tables:
            seen_ids.add(id(table))

            if fold_identifier(table.name) in cte_names:
                continue

            real = snapshot.get_table(table.name)
            if real is None:
                result.deny(ViolationCode.UNKNOWN_TABLE, _MESSAGES["table"])
            else:
                physical.add(real.name)

    # Default deny: any table node the scope analysis did not account for.
    if any(id(table) not in seen_ids for table in root.find_all(exp.Table)):
        result.deny(
            ViolationCode.INTERNAL_CHECK_FAILED,
            _MESSAGES["internal"],
        )

    return physical


def _qualify(
    root: exp.Expr,
    snapshot: SchemaSnapshot,
    result: _Analysis,
) -> exp.Expr | None:
    schema_dict: dict[str, dict[str, object]] = {
        table.name: {column.name: "UNKNOWN" for column in table.columns}
        for table in snapshot.tables
    }

    try:
        return qualify(
            root.copy(),
            schema=cast(dict[str, object], schema_dict),
            dialect=_DIALECT,
            expand_stars=True,
            validate_qualify_columns=True,
            identify=True,
        )
    except RecursionError:
        result.deny(ViolationCode.TOO_COMPLEX, _MESSAGES["complex"])
    except Exception:
        result.deny(ViolationCode.UNRESOLVED_COLUMN, _MESSAGES["column"])

    return None


def _lookup_source(scope: Scope, alias: str) -> object:
    current: Scope | None = scope

    while current is not None:
        if alias in current.sources:
            return current.sources[alias]
        current = current.parent

    return None


def _clause_of(
    column: exp.Expr,
    select: exp.Expr,
) -> type[exp.Expr] | None:
    """Return the direct child type of ``select`` containing ``column``."""
    node = column

    while node.parent is not None and node.parent is not select:
        node = node.parent

    return type(node) if node.parent is select else None


def _check_columns(
    root: exp.Expr,
    snapshot: SchemaSnapshot,
    result: _Analysis,
) -> bool:
    """Independently re-verify every column that ``qualify`` resolved."""
    try:
        scopes = traverse_scope(root)
    except Exception:
        result.deny(
            ViolationCode.INTERNAL_CHECK_FAILED,
            _MESSAGES["internal"],
        )
        return False

    for scope in scopes:
        explicit_aliases = {
            fold_identifier(item.alias)
            for item in getattr(scope.expression, "expressions", [])
            if isinstance(item, exp.Alias)
        }

        for column in scope.columns:
            name = column.name
            qualifier = column.table

            if not qualifier:
                # After qualification, an unqualified column is permitted
                # only for an explicit alias in ORDER BY, GROUP BY, or HAVING.
                clause_type = _clause_of(column, scope.expression)
                is_alias_reference = (
                    clause_type in (exp.Order, exp.Group, exp.Having)
                    and fold_identifier(name) in explicit_aliases
                )
                if not is_alias_reference:
                    result.deny(
                        ViolationCode.UNRESOLVED_COLUMN,
                        _MESSAGES["column"],
                    )
                continue

            source = _lookup_source(scope, qualifier)

            if isinstance(source, exp.Table):
                if not snapshot.has_column(source.name, name):
                    result.deny(
                        ViolationCode.UNRESOLVED_COLUMN,
                        _MESSAGES["column"],
                    )

            elif isinstance(source, Scope):
                outputs = {
                    fold_identifier(output_name)
                    for output_name in getattr(
                        source.expression,
                        "named_selects",
                        [],
                    )
                }
                if fold_identifier(name) not in outputs:
                    result.deny(
                        ViolationCode.UNRESOLVED_COLUMN,
                        _MESSAGES["column"],
                    )

            else:
                result.deny(
                    ViolationCode.UNRESOLVED_COLUMN,
                    _MESSAGES["column"],
                )

    return not result.violations
