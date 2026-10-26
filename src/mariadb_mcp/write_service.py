"""Atomic, bounded execution of structured database write requests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Literal

from typing_extensions import TypedDict

from mariadb_mcp.config import AppConfig
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure
from mariadb_mcp.write_policy import (
    WriteOperation,
    WriteTargetSchema,
    resolve_write_target,
    validate_delete_request,
    validate_insert_request,
    validate_update_request,
)

logger = logging.getLogger("mariadb_mcp.write")
ConnectionFactory = Callable[[], AbstractContextManager[Any]]
SchemaResolver = Callable[[Any, str, str], WriteTargetSchema | None]
WriteAction = Callable[[Any], int]


class WriteResult(TypedDict):
    operation: WriteOperation
    status: Literal["success", "unknown"]
    affected_rows: int | None


class WriteService:
    """Run one validated write in an explicit request-scoped transaction."""

    def __init__(
        self,
        config: AppConfig,
        connection_factory: ConnectionFactory | None = None,
        *,
        schema_resolver: SchemaResolver | None = None,
    ) -> None:
        self.config = config
        self.connection_factory = connection_factory or (
            lambda: connection_scope(config)
        )
        self.schema_resolver = schema_resolver or resolve_write_target

    def insert(self, database: str, table: str, values: object) -> WriteResult:
        """Insert one validated record into one explicitly authorized table."""

        def action(connection: Any) -> int:
            target = self.schema_resolver(connection, database, table)
            request = validate_insert_request(
                self.config, database, table, values, target
            )
            columns = [column for column, _ in request.values]
            bound_values = tuple(value for _, value in request.values)
            sql = (
                f"INSERT INTO {_quote_identifier(database)}."
                f"{_quote_identifier(table)} "
                f"({', '.join(_quote_identifier(column) for column in columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})"
            )
            cursor = None
            try:
                cursor = connection.cursor(buffered=True)
                cursor.execute(sql, bound_values)
                if cursor.rowcount != 1:
                    raise MCPAppError(
                        ErrorCode.DATABASE_ERROR,
                        "The database did not confirm the inserted record.",
                    )
                return 1
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception as error:
                        log_database_failure(error)

        return self.execute_transaction("insert", action)

    def update(
        self,
        database: str,
        table: str,
        values: object,
        filters: object,
    ) -> WriteResult:
        """Update only the bounded, locked set selected by validated filters."""

        def action(connection: Any) -> int:
            target = self.schema_resolver(connection, database, table)
            request = validate_update_request(
                self.config, database, table, values, filters, target
            )
            cap = self.config.writes.max_affected_rows
            if cap is None:
                raise MCPAppError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "The write request is outside the allowed data scope.",
                )
            where_sql, filter_values = _filter_clause(request.filters)
            primary_key_sql = ", ".join(
                _quote_identifier(column) for column in request.target.primary_key
            )
            select_sql = (
                f"SELECT {primary_key_sql} FROM "
                f"{_quote_identifier(database)}.{_quote_identifier(table)} "
                f"WHERE {where_sql} ORDER BY {primary_key_sql} "
                "LIMIT ? FOR UPDATE"
            )
            keys = self._select_locked_keys(
                connection,
                select_sql,
                filter_values + (cap + 1,),
                len(request.target.primary_key),
                cap,
            )
            if not keys:
                return 0

            set_sql = ", ".join(
                f"{_quote_identifier(column)} = ?" for column, _ in request.values
            )
            key_sql, key_values = _key_clause(request.target.primary_key, keys)
            sql = (
                f"UPDATE {_quote_identifier(database)}.{_quote_identifier(table)} "
                f"SET {set_sql} WHERE {key_sql}"
            )
            cursor = None
            try:
                cursor = connection.cursor(buffered=True)
                cursor.execute(
                    sql,
                    tuple(value for _, value in request.values) + key_values,
                )
                return _validated_rowcount(cursor.rowcount, len(keys))
            finally:
                _close_cursor(cursor)

        return self.execute_transaction("update", action)

    def delete(
        self,
        database: str,
        table: str,
        filters: object,
    ) -> WriteResult:
        """Delete only the bounded, locked set selected by validated filters."""

        def action(connection: Any) -> int:
            target = self.schema_resolver(connection, database, table)
            request = validate_delete_request(
                self.config, database, table, filters, target
            )
            cap = self.config.writes.max_affected_rows
            if cap is None:
                raise MCPAppError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "The write request is outside the allowed data scope.",
                )
            where_sql, filter_values = _filter_clause(request.filters)
            primary_key_sql = ", ".join(
                _quote_identifier(column) for column in request.target.primary_key
            )
            select_sql = (
                f"SELECT {primary_key_sql} FROM "
                f"{_quote_identifier(database)}.{_quote_identifier(table)} "
                f"WHERE {where_sql} ORDER BY {primary_key_sql} "
                "LIMIT ? FOR UPDATE"
            )
            keys = self._select_locked_keys(
                connection,
                select_sql,
                filter_values + (cap + 1,),
                len(request.target.primary_key),
                cap,
            )
            if not keys:
                return 0

            key_sql, key_values = _key_clause(request.target.primary_key, keys)
            sql = (
                f"DELETE FROM {_quote_identifier(database)}.{_quote_identifier(table)} "
                f"WHERE {key_sql}"
            )
            cursor = None
            try:
                cursor = connection.cursor(buffered=True)
                cursor.execute(sql, key_values)
                return _validated_rowcount(cursor.rowcount, len(keys))
            finally:
                _close_cursor(cursor)

        return self.execute_transaction("delete", action)

    def _select_locked_keys(
        self,
        connection: Any,
        sql: str,
        parameters: tuple[Any, ...],
        key_count: int,
        cap: int,
    ) -> list[tuple[Any, ...]]:
        cursor = None
        try:
            cursor = connection.cursor(buffered=True)
            cursor.execute(sql, parameters)
            rows = cursor.fetchall()
            if not isinstance(rows, list):
                raise MCPAppError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "The write target could not be safely selected.",
                )
            if len(rows) > cap:
                raise MCPAppError(
                    ErrorCode.RESULT_LIMIT,
                    "The write exceeds the configured affected-record limit.",
                )
            keys: list[tuple[Any, ...]] = []
            for row in rows:
                if not isinstance(row, (tuple, list)) or len(row) != key_count:
                    raise MCPAppError(
                        ErrorCode.AUTHORIZATION_DENIED,
                        "The write target could not be safely identified.",
                    )
                keys.append(tuple(row))
            return keys
        finally:
            _close_cursor(cursor)

    def execute_transaction(
        self, operation: WriteOperation, action: WriteAction
    ) -> WriteResult:
        """Execute one internal action, never retrying an uncertain commit."""

        if operation not in {"insert", "update", "delete"}:
            raise MCPAppError(
                ErrorCode.INVALID_INPUT, "The write operation is invalid."
            )
        try:
            with self.connection_factory() as connection:
                transaction_started = False
                try:
                    connection.begin()
                    transaction_started = True
                    affected_rows = action(connection)
                    if type(affected_rows) is not int or affected_rows < 0:
                        raise MCPAppError(
                            ErrorCode.INTERNAL_ERROR,
                            "The write result could not be established safely.",
                        )
                    try:
                        connection.commit()
                    except Exception as error:
                        log_database_failure(error)
                        return {
                            "operation": operation,
                            "status": "unknown",
                            "affected_rows": None,
                        }
                    return {
                        "operation": operation,
                        "status": "success",
                        "affected_rows": affected_rows,
                    }
                except MCPAppError:
                    if transaction_started:
                        _rollback_safely(connection)
                    raise
                except Exception as error:
                    if transaction_started:
                        _rollback_safely(connection)
                    if _is_timeout_error(error):
                        raise MCPAppError(
                            ErrorCode.QUERY_TIMEOUT,
                            "The write exceeded its configured time limit.",
                        ) from None
                    log_database_failure(error)
                    raise MCPAppError(
                        ErrorCode.DATABASE_ERROR,
                        "The database write failed.",
                    ) from None
        except MCPAppError:
            raise
        except Exception as error:
            if _is_timeout_error(error):
                raise MCPAppError(
                    ErrorCode.QUERY_TIMEOUT,
                    "The write exceeded its configured time limit.",
                ) from None
            log_database_failure(error)
            raise MCPAppError(
                ErrorCode.DATABASE_ERROR,
                "The database write failed.",
            ) from None


def _rollback_safely(connection: Any) -> None:
    try:
        connection.rollback()
    except Exception as error:
        log_database_failure(error)


def _is_timeout_error(error: Exception) -> bool:
    return (
        "timeout" in type(error).__name__.casefold()
        or getattr(error, "errno", None) == 1969
    )


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def _filter_clause(filters: tuple[tuple[str, Any], ...]) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    for column, value in filters:
        identifier = _quote_identifier(column)
        if value is None:
            clauses.append(f"{identifier} IS NULL")
        else:
            clauses.append(f"{identifier} = ?")
            parameters.append(value)
    return " AND ".join(clauses), tuple(parameters)


def _key_clause(
    primary_key: tuple[str, ...], keys: list[tuple[Any, ...]]
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    for key in keys:
        if len(key) != len(primary_key):
            raise MCPAppError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The write target could not be safely identified.",
            )
        clauses.append(
            "("
            + " AND ".join(f"{_quote_identifier(column)} = ?" for column in primary_key)
            + ")"
        )
        parameters.extend(key)
    return " OR ".join(clauses), tuple(parameters)


def _validated_rowcount(rowcount: object, max_rows: int) -> int:
    if type(rowcount) is not int or not 0 <= rowcount <= max_rows:
        raise MCPAppError(
            ErrorCode.DATABASE_ERROR,
            "The database write result could not be established safely.",
        )
    return rowcount


def _close_cursor(cursor: Any | None) -> None:
    if cursor is not None:
        try:
            cursor.close()
        except Exception as error:
            log_database_failure(error)
