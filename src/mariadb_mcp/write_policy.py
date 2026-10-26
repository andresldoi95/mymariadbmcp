"""Structured write validation and fail-closed table metadata resolution."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from mariadb_mcp.config import AppConfig
from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure

logger = logging.getLogger("mariadb_mcp.write_policy")
MAX_WRITE_FIELDS = 128
MAX_WRITE_BYTES = 64 * 1024

WriteOperation = Literal["insert", "update", "delete"]
Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class WriteTargetSchema:
    columns: frozenset[str]
    engine: str
    primary_key: tuple[str, ...]
    is_base_table: bool = True
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ValidatedWriteRequest:
    operation: WriteOperation
    database: str
    table: str
    target: WriteTargetSchema
    values: tuple[tuple[str, Scalar], ...] = ()
    filters: tuple[tuple[str, Scalar], ...] = ()


def resolve_write_target(
    connection: Any, database: str, table: str
) -> WriteTargetSchema | None:
    """Read base-table engine, columns, and primary-key metadata fail-closed."""

    cursor = None
    try:
        cursor = connection.cursor(buffered=True)
        cursor.execute(
            "SELECT TABLE_TYPE, ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            (database, table),
        )
        table_row = cursor.fetchone()
        if not table_row or len(table_row) < 2:
            return None
        table_type = str(table_row[0]).upper()
        engine = "" if table_row[1] is None else str(table_row[1])

        cursor.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (database, table),
        )
        column_rows = cursor.fetchall()
        if not column_rows:
            return None
        columns = frozenset(str(row[0]) for row in column_rows if row)
        if len(columns) != len(column_rows):
            return None

        cursor.execute(
            "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION",
            (database, table),
        )
        primary_key_rows = cursor.fetchall()
        primary_key = tuple(str(row[0]) for row in primary_key_rows if row)
        if len(primary_key) != len(primary_key_rows):
            return None

        return WriteTargetSchema(
            columns=columns,
            engine=engine,
            primary_key=primary_key,
            is_base_table=table_type == "BASE TABLE",
            complete=True,
        )
    except Exception as error:
        log_database_failure(error)
        raise MCPAppError(
            ErrorCode.AUTHORIZATION_DENIED,
            "The write could not be authorized against database metadata.",
        ) from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception as error:
                log_database_failure(error)


def validate_insert_request(
    config: AppConfig,
    database: str,
    table: str,
    values: object,
    target: WriteTargetSchema | None,
) -> ValidatedWriteRequest:
    """Authorize one insert and canonicalize its fields and scalar values."""

    schema = _validate_target(config, database, table, target, "insert")
    permitted = config.writes.insert_columns_for(database, table)
    validated_values = _validate_values(values, schema, permitted)
    return ValidatedWriteRequest(
        operation="insert",
        database=database,
        table=table,
        target=schema,
        values=validated_values,
    )


def validate_update_request(
    config: AppConfig,
    database: str,
    table: str,
    values: object,
    filters: object,
    target: WriteTargetSchema | None,
) -> ValidatedWriteRequest:
    """Authorize update fields and non-empty readable equality filters."""

    schema = _validate_target(config, database, table, target, "update")
    permitted = config.writes.update_columns_for(database, table)
    validated_values = _validate_values(values, schema, permitted)
    validated_filters = _validate_filters(config, database, table, filters, schema)
    return ValidatedWriteRequest(
        operation="update",
        database=database,
        table=table,
        target=schema,
        values=validated_values,
        filters=validated_filters,
    )


def validate_delete_request(
    config: AppConfig,
    database: str,
    table: str,
    filters: object,
    target: WriteTargetSchema | None,
) -> ValidatedWriteRequest:
    """Authorize a delete and its non-empty readable equality filters."""

    schema = _validate_target(config, database, table, target, "delete")
    validated_filters = _validate_filters(config, database, table, filters, schema)
    return ValidatedWriteRequest(
        operation="delete",
        database=database,
        table=table,
        target=schema,
        filters=validated_filters,
    )


def _validate_target(
    config: AppConfig,
    database: object,
    table: object,
    target: WriteTargetSchema | None,
    operation: WriteOperation,
) -> WriteTargetSchema:
    if (
        not isinstance(database, str)
        or not database
        or not isinstance(table, str)
        or not table
    ):
        raise MCPAppError(ErrorCode.INVALID_INPUT, "The write target is invalid.")
    if not config.access.table_allowed(database, table):
        raise _denied()

    if operation == "insert":
        allowed = bool(config.writes.insert_columns_for(database, table))
    elif operation == "update":
        allowed = bool(config.writes.update_columns_for(database, table))
    else:
        allowed = config.writes.delete_allowed(database, table)
    if not allowed:
        raise _denied()
    if (
        target is None
        or not target.complete
        or not target.is_base_table
        or target.engine.casefold() != "innodb"
        or not target.columns
    ):
        raise _denied()
    if operation != "insert":
        if not target.primary_key:
            raise _denied()
        if any(
            _canonical_column(target.columns, key) is None for key in target.primary_key
        ):
            raise _denied()
        if any(
            not config.access.column_allowed(database, table, key)
            for key in target.primary_key
        ):
            raise _denied()
    return target


def _validate_values(
    values: object,
    target: WriteTargetSchema,
    permitted_columns: tuple[str, ...],
) -> tuple[tuple[str, Scalar], ...]:
    if not isinstance(values, Mapping) or not values or len(values) > MAX_WRITE_FIELDS:
        raise MCPAppError(ErrorCode.INVALID_INPUT, "The write values are invalid.")
    permitted = {column.casefold() for column in permitted_columns}
    result: list[tuple[str, Scalar]] = []
    for requested_column, value in values.items():
        if not isinstance(requested_column, str) or not requested_column:
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The write values are invalid.")
        column = _canonical_column(target.columns, requested_column)
        if column is None or column.casefold() not in permitted:
            raise _denied()
        if not _is_scalar(value):
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The write values are invalid.")
        result.append((column, value))
    _check_size(result)
    return tuple(sorted(result, key=lambda item: item[0].casefold()))


def _validate_filters(
    config: AppConfig,
    database: str,
    table: str,
    filters: object,
    target: WriteTargetSchema,
) -> tuple[tuple[str, Scalar], ...]:
    if (
        not isinstance(filters, Mapping)
        or not filters
        or len(filters) > MAX_WRITE_FIELDS
    ):
        raise MCPAppError(ErrorCode.INVALID_INPUT, "The write filters are invalid.")
    result: list[tuple[str, Scalar]] = []
    for requested_column, value in filters.items():
        if not isinstance(requested_column, str) or not requested_column:
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The write filters are invalid.")
        column = _canonical_column(target.columns, requested_column)
        if column is None or not config.access.column_allowed(database, table, column):
            raise _denied()
        if not _is_scalar(value):
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The write filters are invalid.")
        result.append((column, value))
    _check_size(result)
    return tuple(sorted(result, key=lambda item: item[0].casefold()))


def _is_scalar(value: object) -> bool:
    if value is None or isinstance(value, (str, int, bool)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _check_size(values: list[tuple[str, Scalar]]) -> None:
    try:
        size = len(
            json.dumps(
                values,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeEncodeError):
        raise MCPAppError(
            ErrorCode.INVALID_INPUT, "The write input is invalid."
        ) from None
    if size > MAX_WRITE_BYTES:
        raise MCPAppError(ErrorCode.INVALID_INPUT, "The write input is too large.")


def _canonical_column(columns: frozenset[str], requested: str) -> str | None:
    matches = [
        column for column in columns if column.casefold() == requested.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def _denied() -> MCPAppError:
    return MCPAppError(
        ErrorCode.AUTHORIZATION_DENIED,
        "The write request is outside the allowed data scope.",
    )
