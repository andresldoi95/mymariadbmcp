"""Bounded, parameterized read-query execution."""

from __future__ import annotations

import base64
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal
from typing import Any

from mariadb_mcp.config import AppConfig
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure
from mariadb_mcp.sql_policy import TableSchema, validate_read_query

logger = logging.getLogger("mariadb_mcp.query")
MAX_PARAMETER_COUNT = 128
MAX_PARAMETER_BYTES = 64 * 1024
_RESULT_TYPE_NAMES = {
    0: "DECIMAL",
    1: "TINYINT",
    2: "SMALLINT",
    3: "INT",
    4: "FLOAT",
    5: "DOUBLE",
    6: "NULL",
    7: "TIMESTAMP",
    8: "BIGINT",
    9: "MEDIUMINT",
    10: "DATE",
    11: "TIME",
    12: "DATETIME",
    13: "YEAR",
    14: "DATE",
    15: "VARCHAR",
    16: "BIT",
    17: "TIMESTAMP",
    18: "DATETIME",
    19: "TIME",
    245: "JSON",
    246: "DECIMAL",
    247: "ENUM",
    248: "SET",
    249: "TINYBLOB",
    250: "MEDIUMBLOB",
    251: "LONGBLOB",
    252: "BLOB",
    253: "VARCHAR",
    254: "CHAR",
    255: "GEOMETRY",
}

ConnectionFactory = Callable[[], AbstractContextManager[Any]]
ConnectionSchemaResolver = Callable[[Any, str, str], TableSchema | None]


class QueryService:
    """Validate and execute read-only queries with strict result budgets."""

    def __init__(
        self,
        config: AppConfig,
        connection_factory: ConnectionFactory | None = None,
        *,
        schema_resolver: ConnectionSchemaResolver | None = None,
    ) -> None:
        self.config = config
        self.connection_factory = connection_factory or (
            lambda: connection_scope(config)
        )
        self.schema_resolver = schema_resolver or self._resolve_schema
        self._semaphore = threading.BoundedSemaphore(
            config.limits.max_concurrent_queries
        )

    def execute(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        values = self._validate_parameters(parameters)
        if not self._semaphore.acquire(blocking=False):
            raise MCPAppError(
                ErrorCode.RESULT_LIMIT,
                "The server has reached its configured query capacity.",
            )
        try:
            with self.connection_factory() as connection:
                validated = validate_read_query(
                    sql,
                    self.config,
                    lambda database, table: self.schema_resolver(
                        connection, database, table
                    ),
                )
                if validated.parameter_count != len(values):
                    raise MCPAppError(
                        ErrorCode.INVALID_INPUT,
                        "The number of bound values does not match the query.",
                    )
                return self._execute_validated(connection, validated.sql, values)
        finally:
            self._semaphore.release()

    def explain(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        """Return a bounded EXPLAIN plan for a validated SELECT."""

        values = self._validate_parameters(parameters)
        if not self._semaphore.acquire(blocking=False):
            raise MCPAppError(
                ErrorCode.RESULT_LIMIT,
                "The server has reached its configured query capacity.",
            )
        try:
            with self.connection_factory() as connection:
                validated = validate_read_query(
                    sql,
                    self.config,
                    lambda database, table: self.schema_resolver(
                        connection, database, table
                    ),
                )
                if validated.parameter_count != len(values):
                    raise MCPAppError(
                        ErrorCode.INVALID_INPUT,
                        "The number of bound values does not match the query.",
                    )
                return self._execute_explain(connection, validated.sql, values)
        finally:
            self._semaphore.release()

    def _execute_validated(
        self, connection: Any, sql: str, parameters: tuple[Any, ...]
    ) -> dict[str, Any]:
        cursor = None
        started = time.monotonic()
        try:
            cursor = connection.cursor(buffered=False)
            cursor.execute(sql, parameters)
            columns = self._column_descriptions(cursor.description)
            empty_result = self._make_result(columns, [], started, False, None, False)
            base_size = self._serialized_size(empty_result)
            if base_size > self.config.limits.max_result_bytes:
                raise MCPAppError(
                    ErrorCode.RESULT_LIMIT,
                    "The result metadata exceeds the configured size limit.",
                )

            rows: list[list[Any]] = []
            truncated = False
            reason: str | None = None
            has_more = False
            row_budget = self.config.limits.max_rows
            byte_budget = self.config.limits.max_result_bytes
            row_bytes_total = 0

            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                if len(rows) >= row_budget:
                    truncated = True
                    reason = "row_limit"
                    has_more = True
                    break

                safe_row = [_json_value(value) for value in row]
                row_size = len(
                    json.dumps(
                        safe_row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
                separator_size = 1 if rows else 0
                projected_size = base_size + row_bytes_total + row_size + separator_size
                if projected_size > byte_budget:
                    truncated = True
                    reason = "byte_limit"
                    has_more = True
                    break
                rows.append(safe_row)
                row_bytes_total += row_size + separator_size

            result = self._make_result(
                columns,
                rows,
                started,
                truncated,
                reason,
                has_more,
            )
            if self._serialized_size(result) > byte_budget:
                raise MCPAppError(
                    ErrorCode.RESULT_LIMIT,
                    "The result exceeds the configured size limit.",
                )
            return result
        except MCPAppError:
            raise
        except TimeoutError:
            raise MCPAppError(
                ErrorCode.QUERY_TIMEOUT,
                "The query exceeded its configured time limit.",
            ) from None
        except Exception as error:
            if _is_timeout_error(error):
                raise MCPAppError(
                    ErrorCode.QUERY_TIMEOUT,
                    "The query exceeded its configured time limit.",
                ) from None
            log_database_failure(error)
            raise MCPAppError(
                ErrorCode.DATABASE_ERROR,
                "The database query failed.",
            ) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as error:
                    log_database_failure(error)

    def _execute_explain(
        self, connection: Any, sql: str, parameters: tuple[Any, ...]
    ) -> dict[str, Any]:
        cursor = None
        started = time.monotonic()
        try:
            cursor = connection.cursor(buffered=False)
            cursor.execute(f"EXPLAIN {sql}", parameters)
            columns = self._column_descriptions(cursor.description)
            plan_rows: list[list[Any]] = []
            truncated = False
            row_bytes = 0
            base_plan = {"columns": columns, "rows": []}
            base_result = {
                "plan": base_plan,
                "execution_time_ms": 0,
                "truncated": False,
            }
            base_size = self._serialized_size(base_result)
            byte_budget = self.config.limits.max_result_bytes
            if base_size > byte_budget:
                raise MCPAppError(
                    ErrorCode.RESULT_LIMIT,
                    "The execution plan exceeds the configured size limit.",
                )

            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                if len(plan_rows) >= self.config.limits.max_rows:
                    truncated = True
                    break
                safe_row = [_json_value(value) for value in row]
                encoded_size = len(
                    json.dumps(
                        safe_row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
                separator_size = 1 if plan_rows else 0
                projected_size = base_size + row_bytes + encoded_size + separator_size
                if projected_size > byte_budget:
                    truncated = True
                    break
                plan_rows.append(safe_row)
                row_bytes += encoded_size + separator_size

            result = {
                "plan": {"columns": columns, "rows": plan_rows},
                "execution_time_ms": max(0, round((time.monotonic() - started) * 1000)),
                "truncated": truncated,
            }
            if self._serialized_size(result) > byte_budget:
                raise MCPAppError(
                    ErrorCode.RESULT_LIMIT,
                    "The execution plan exceeds the configured size limit.",
                )
            return result
        except MCPAppError:
            raise
        except TimeoutError:
            raise MCPAppError(
                ErrorCode.QUERY_TIMEOUT,
                "The execution plan exceeded its configured time limit.",
            ) from None
        except Exception as error:
            if _is_timeout_error(error):
                raise MCPAppError(
                    ErrorCode.QUERY_TIMEOUT,
                    "The execution plan exceeded its configured time limit.",
                ) from None
            log_database_failure(error)
            raise MCPAppError(
                ErrorCode.DATABASE_ERROR,
                "The execution plan could not be retrieved.",
            ) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as error:
                    log_database_failure(error)

    def _resolve_schema(
        self, connection: Any, database: str, table: str
    ) -> TableSchema | None:
        table_rows = self._fetchall(
            connection,
            "SELECT TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            (database, table),
        )
        if not table_rows:
            return None
        table_type = str(table_rows[0][0]).upper()
        if table_type != "BASE TABLE":
            return TableSchema(frozenset(), is_base_table=False, complete=True)
        column_rows = self._fetchall(
            connection,
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (database, table),
        )
        if not column_rows:
            return None
        return TableSchema(
            frozenset(str(row[0]) for row in column_rows),
            is_base_table=True,
            complete=True,
        )

    @staticmethod
    def _fetchall(
        connection: Any, query: str, parameters: tuple[Any, ...]
    ) -> list[tuple[Any, ...]]:
        cursor = None
        try:
            cursor = connection.cursor(buffered=True)
            cursor.execute(query, parameters)
            return list(cursor.fetchall())
        except Exception as error:
            log_database_failure(error)
            raise MCPAppError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The query could not be authorized against database metadata.",
            ) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as error:
                    log_database_failure(error)

    def _validate_parameters(self, parameters: list[Any] | None) -> tuple[Any, ...]:
        if parameters is None:
            return ()
        if not isinstance(parameters, list) or len(parameters) > MAX_PARAMETER_COUNT:
            raise MCPAppError(
                ErrorCode.INVALID_INPUT, "The query parameters are invalid."
            )
        if any(not _is_json_value(value) for value in parameters):
            raise MCPAppError(
                ErrorCode.INVALID_INPUT, "The query parameters are invalid."
            )
        try:
            size = len(
                json.dumps(
                    parameters,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            raise MCPAppError(
                ErrorCode.INVALID_INPUT, "The query parameters are invalid."
            ) from None
        if size > MAX_PARAMETER_BYTES:
            raise MCPAppError(
                ErrorCode.INVALID_INPUT, "The query parameters are too large."
            )
        return tuple(parameters)

    @staticmethod
    def _column_descriptions(description: Any) -> list[dict[str, str]]:
        if not description:
            return []
        columns: list[dict[str, str]] = []
        for item in description:
            name = str(item[0])
            type_code = item[1] if len(item) > 1 else None
            columns.append(
                {
                    "name": name,
                    "type": _result_type_name(item, type_code),
                }
            )
        return columns

    @staticmethod
    def _make_result(
        columns: list[dict[str, str]],
        rows: list[list[Any]],
        started: float,
        truncated: bool,
        reason: str | None,
        has_more: bool,
    ) -> dict[str, Any]:
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": max(0, round((time.monotonic() - started) * 1000)),
            "truncated": truncated,
            "truncation_reason": reason,
            "has_more": has_more,
        }

    @staticmethod
    def _serialized_size(result: dict[str, Any]) -> int:
        return len(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(
        value, (str, int, bool, Decimal, date, datetime, datetime_time, timedelta)
    ):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, bytes):
        return True
    return False


def _is_timeout_error(error: Exception) -> bool:
    return (
        "timeout" in type(error).__name__.casefold()
        or getattr(error, "errno", None) == 1969
    )


def _result_type_name(description: Any, type_code: Any) -> str:
    if type_code is None:
        return "UNKNOWN"
    if not isinstance(type_code, int):
        return str(type_code).upper()
    type_name = _RESULT_TYPE_NAMES.get(type_code, "UNKNOWN")
    if type_name == "DECIMAL" and len(description) > 5:
        precision, scale = description[4], description[5]
        if isinstance(precision, int) and isinstance(scale, int):
            return f"DECIMAL({precision},{scale})"
    if type_name in {"CHAR", "VARCHAR"} and len(description) > 3:
        length = description[3] or description[2]
        if isinstance(length, int) and length > 0:
            return f"{type_name}({length})"
    return type_name


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, bytes):
        return "base64:" + base64.b64encode(value).decode("ascii")
    raise MCPAppError(
        ErrorCode.DATABASE_ERROR, "A result value could not be serialized safely."
    )
