"""Fail-closed parser and object/column authorization for read queries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from mariadb_mcp.config import AppConfig
from mariadb_mcp.errors import ErrorCode, MCPAppError

MAX_QUERY_BYTES = 16 * 1024
ALLOWED_FUNCTIONS = frozenset(
    {
        "ABS",
        "AVG",
        "COALESCE",
        "COUNT",
        "LOWER",
        "MAX",
        "MIN",
        "NULLIF",
        "ROUND",
        "SUM",
        "UPPER",
    }
)


@dataclass(frozen=True, slots=True)
class TableSchema:
    columns: frozenset[str]
    is_base_table: bool = True
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    tables: tuple[tuple[str, str], ...]
    columns: tuple[tuple[str, str, str], ...]
    parameter_count: int
    statement_count: int = 1


SchemaResolver = Callable[[str, str], TableSchema | None]


@dataclass(frozen=True, slots=True)
class _Source:
    database: str
    table: str
    schema: TableSchema


def _unsupported(
    message: str = "The query uses an unsupported SQL construct.",
) -> MCPAppError:
    return MCPAppError(ErrorCode.UNSUPPORTED_QUERY, message)


def _denied() -> MCPAppError:
    return MCPAppError(
        ErrorCode.AUTHORIZATION_DENIED,
        "The query references data outside the allowed scope.",
    )


def _reject_comments(sql: str) -> None:
    """Reject MariaDB comment tokens without mistaking quoted text for comments."""

    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is None:
            if char == '"':
                # ANSI_QUOTES changes whether double quotes are strings or identifiers.
                raise _unsupported()
            if char in ("'", "`"):
                quote = char
                index += 1
                continue
            if char == "#" or sql.startswith("/*", index):
                raise _unsupported()
            if sql.startswith("--", index) and (
                index + 2 == len(sql) or sql[index + 2].isspace()
            ):
                raise _unsupported()
            index += 1
            continue

        if char == "\\":
            # Backslash escaping depends on SQL_MODE; reject instead of guessing.
            raise _unsupported()
        if char == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                index += 2
                continue
            quote = None
        index += 1


def _parse(sql: str) -> exp.Select:
    if not isinstance(sql, str) or not sql.strip():
        raise MCPAppError(
            ErrorCode.INVALID_INPUT, "The SQL input is empty or too large."
        )
    try:
        query_size = len(sql.encode("utf-8"))
    except UnicodeEncodeError:
        raise MCPAppError(
            ErrorCode.INVALID_INPUT, "The SQL input contains invalid text."
        ) from None
    if query_size > MAX_QUERY_BYTES:
        raise MCPAppError(
            ErrorCode.INVALID_INPUT, "The SQL input is empty or too large."
        )
    _reject_comments(sql)
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except (sqlglot.errors.ParseError, ValueError):
        raise _unsupported("The SQL statement could not be safely analyzed.") from None
    if len(statements) != 1 or statements[0] is None:
        raise _unsupported()
    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise _unsupported()
    return statement


def _validate_ast(statement: exp.Select) -> None:
    disallowed_types = tuple(
        node_type
        for node_type in (
            getattr(exp, "Subquery", None),
            getattr(exp, "CTE", None),
            getattr(exp, "Union", None),
            getattr(exp, "Intersect", None),
            getattr(exp, "Except", None),
            getattr(exp, "Lock", None),
            getattr(exp, "Into", None),
            getattr(exp, "Var", None),
            getattr(exp, "Parameter", None),
            getattr(exp, "Command", None),
            getattr(exp, "PropertyEQ", None),
        )
        if node_type is not None
    )
    if any(isinstance(node, disallowed_types) for node in statement.walk()):
        raise _unsupported()

    scopes = list(traverse_scope(statement))
    if (
        len(scopes) != 1
        or not scopes
        or not isinstance(scopes[0].expression, exp.Select)
    ):
        raise _unsupported()

    for function in statement.find_all(exp.Func):
        if function.sql_name().upper() not in ALLOWED_FUNCTIONS:
            raise _unsupported()

    # A qualified function name may be represented as a dotted expression
    # instead of a Func node by the parser; reject every such expression.
    if any(isinstance(node, exp.Dot) for node in statement.walk()):
        raise _unsupported()

    for join in statement.find_all(exp.Join):
        if (
            join.args.get("using")
            or str(join.args.get("method", "")).upper() == "NATURAL"
        ):
            # SQLGlot does not expose USING/NATURAL join columns through scope.columns.
            # Reject them until both sides can be proven against the column policy.
            raise _unsupported()

    if (
        statement.args.get("locks")
        or statement.args.get("into")
        or statement.args.get("procedure")
    ):
        raise _unsupported()


def validate_read_query(
    sql: str,
    config: AppConfig,
    schema_resolver: SchemaResolver,
) -> ValidatedQuery:
    """Parse one SELECT, resolve each table and column, and fail closed."""

    statement = _parse(sql)
    _validate_ast(statement)
    scopes = list(traverse_scope(statement))
    scope: Scope = scopes[0]

    sources: dict[str, _Source] = {}
    physical_sources: list[_Source] = []
    tables: list[tuple[str, str]] = []
    for alias, (table_node, source) in scope.selected_sources.items():
        if not isinstance(table_node, exp.Table) or not isinstance(source, exp.Table):
            raise _unsupported()
        if table_node.catalog:
            raise _unsupported()
        table_name = table_node.name
        database = table_node.db or config.database.default_database
        if not database or not table_name:
            raise _denied()
        if not config.access.table_allowed(database, table_name):
            raise _denied()
        schema = schema_resolver(database, table_name)
        if schema is None or not schema.complete or not schema.is_base_table:
            raise _denied()
        item = _Source(database, table_name, schema)
        sources[alias.casefold()] = item
        # Accept the base table qualifier only if no alias shadows it.
        if table_node.args.get("alias") is None:
            sources[table_name.casefold()] = item
        physical_sources.append(item)
        tables.append((database, table_name))

    columns: set[tuple[str, str, str]] = set()
    output_aliases = {
        expression.alias.casefold()
        for expression in statement.expressions
        if isinstance(expression, exp.Alias)
    }
    for column in scope.columns:
        if column.is_star:
            continue
        if column.catalog:
            raise _unsupported()
        column_name = column.name
        if not column_name:
            raise _unsupported()
        if column.table:
            source = sources.get(column.table.casefold())
            if source is None:
                raise _denied()
            if column.db and column.db.casefold() != source.database.casefold():
                raise _denied()
            candidates = (
                [source]
                if column_name.casefold() in _casefold_names(source.schema.columns)
                else []
            )
        else:
            candidates = [
                source
                for source in physical_sources
                if column_name.casefold() in _casefold_names(source.schema.columns)
            ]
            if not candidates and column_name.casefold() in output_aliases:
                continue
        if len(candidates) != 1:
            raise _denied()
        source = candidates[0]
        canonical_column = _canonical_name(source.schema.columns, column_name)
        if canonical_column is None or not config.access.column_allowed(
            source.database, source.table, canonical_column
        ):
            raise _denied()
        columns.add((source.database, source.table, canonical_column))

    for star in statement.find_all(exp.Star):
        if isinstance(star.parent, exp.Count):
            continue
        if not physical_sources:
            raise _unsupported()
        if isinstance(star.parent, exp.Column) and star.parent.table:
            star_source = sources.get(star.parent.table.casefold())
            if star_source is None:
                raise _denied()
            if (
                star.parent.db
                and star.parent.db.casefold() != star_source.database.casefold()
            ):
                raise _denied()
        elif star.parent is not statement:
            raise _unsupported()
        if any(
            f"{source.database}.{source.table}" in config.access.allowed_columns
            for source in physical_sources
        ):
            raise _unsupported()
        for source in physical_sources:
            for column_name in source.schema.columns:
                if not config.access.column_allowed(
                    source.database, source.table, column_name
                ):
                    raise _denied()
                columns.add((source.database, source.table, column_name))

    placeholders = sum(
        1 for node in statement.walk() if isinstance(node, exp.Placeholder)
    )
    return ValidatedQuery(
        sql=sql,
        tables=tuple(dict.fromkeys(tables)),
        columns=tuple(sorted(columns)),
        parameter_count=placeholders,
    )


def _casefold_names(names: frozenset[str]) -> set[str]:
    return {name.casefold() for name in names}


def _canonical_name(names: frozenset[str], requested: str) -> str | None:
    for name in names:
        if name.casefold() == requested.casefold():
            return name
    return None
