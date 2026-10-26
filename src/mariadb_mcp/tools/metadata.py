"""Permission-aware MariaDB metadata discovery tools."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Any, TypedDict

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from mariadb_mcp.config import AppConfig
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import (
    ErrorCode,
    MCPAppError,
    as_tool_error,
    log_database_failure,
)

logger = logging.getLogger("mariadb_mcp.metadata")

ConnectionFactory = Callable[[], AbstractContextManager[Any]]


class ListDatabasesResult(TypedDict):
    databases: list[str]
    partial: bool


class TablePageResult(TypedDict):
    database: str
    tables: list[str]
    has_more: bool
    next_offset: int | None
    partial: bool


class ColumnMetadata(TypedDict):
    name: str
    type: str
    nullable: bool


class IndexMetadata(TypedDict):
    name: str
    unique: bool
    columns: list[str]


class ForeignKeyColumn(TypedDict):
    local: str
    referenced: str


class ForeignKeyMetadata(TypedDict):
    name: str
    referenced_database: str
    referenced_table: str
    columns: list[ForeignKeyColumn]


class TableDescription(TypedDict):
    database: str
    table: str
    columns: list[ColumnMetadata]
    primary_key: list[str]
    indexes: list[IndexMetadata]
    foreign_keys: list[ForeignKeyMetadata]
    partial: bool


class MetadataService:
    """Read metadata visible to both the configured policy and DB account."""

    def __init__(
        self,
        config: AppConfig,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.config = config
        self.connection_factory = connection_factory or (
            lambda: connection_scope(config)
        )

    def list_databases(self) -> dict[str, Any]:
        allowed = self.config.access.allowed_databases
        if not allowed:
            return {"databases": [], "partial": False}

        databases: list[str] = []
        with self.connection_factory() as connection:
            for database in allowed:
                allowed_tables = self.config.access.allowed_tables.get(database)
                if (
                    self.config.access.table_allowlist_configured
                    and allowed_tables is None
                ):
                    continue
                query = (
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'"
                )
                parameters: tuple[Any, ...] = (database,)
                if allowed_tables is not None:
                    if not allowed_tables:
                        continue
                    placeholders = ", ".join("?" for _ in allowed_tables)
                    query += f" AND TABLE_NAME IN ({placeholders})"
                    parameters += allowed_tables
                query += " LIMIT 1"
                rows = self._fetchall(
                    connection,
                    query,
                    parameters,
                )
                if rows:
                    databases.append(database)
        return {
            "databases": databases,
            "partial": len(databases) < len(allowed),
        }

    def list_tables(
        self,
        database: str,
        page_size: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._require_database(database)
        size = self.config.limits.default_page_size if page_size is None else page_size
        if type(size) is not int or not 1 <= size <= self.config.limits.max_page_size:
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The page size is invalid.")
        if type(offset) is not int or not 0 <= offset <= 10_000_000:
            raise MCPAppError(ErrorCode.INVALID_INPUT, "The page offset is invalid.")

        allowed_tables = self.config.access.allowed_tables.get(database)
        if self.config.access.table_allowlist_configured and allowed_tables is None:
            return self._table_page(database, [], offset, size)
        query = (
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'"
        )
        parameters: tuple[Any, ...] = (database,)
        if allowed_tables is not None:
            if not allowed_tables:
                return self._table_page(database, [], offset, size)
            placeholders = ", ".join("?" for _ in allowed_tables)
            query += f" AND TABLE_NAME IN ({placeholders})"
            parameters += allowed_tables
        query += " ORDER BY TABLE_NAME LIMIT ? OFFSET ?"
        parameters += (size + 1, offset)

        with self.connection_factory() as connection:
            rows = self._fetchall(connection, query, parameters)
        names = [str(row[0]) for row in rows]
        expected_page_count = (
            min(size + 1, max(0, len(allowed_tables) - offset))
            if allowed_tables is not None
            else len(names)
        )
        partial = len(names) < expected_page_count
        return self._table_page(database, names, offset, size, partial)

    def describe_table(self, database: str, table: str) -> dict[str, Any]:
        self._require_table(database, table)
        with self.connection_factory() as connection:
            column_rows = self._fetchall(
                connection,
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, PRIVILEGES "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                "ORDER BY ORDINAL_POSITION",
                (database, table),
            )
            if not column_rows:
                raise MCPAppError(
                    ErrorCode.AUTHORIZATION_DENIED,
                    "The requested table is not available.",
                )

            columns: list[dict[str, Any]] = []
            allowed_column_names: set[str] = set()
            partial = False
            for name, data_type, column_type, nullable, privileges in column_rows:
                column_name = str(name)
                database_can_select = "select" in {
                    privilege.strip().casefold()
                    for privilege in str(privileges).split(",")
                }
                if not database_can_select:
                    partial = True
                    continue
                if not self.config.access.column_allowed(database, table, column_name):
                    partial = True
                    continue
                allowed_column_names.add(column_name)
                columns.append(
                    {
                        "name": column_name,
                        "type": str(column_type or data_type),
                        "nullable": str(nullable).upper() == "YES",
                    }
                )

            primary_key: list[str] = []
            foreign_key_groups: dict[str, dict[str, Any]] = {}
            try:
                key_rows = self._fetchall(
                    connection,
                    "SELECT CONSTRAINT_NAME, COLUMN_NAME, "
                    "REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, "
                    "REFERENCED_COLUMN_NAME, ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                    "ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION",
                    (database, table),
                )
                for (
                    constraint,
                    column,
                    ref_database,
                    ref_table,
                    ref_column,
                    _,
                ) in key_rows:
                    column_name = str(column)
                    if str(constraint) == "PRIMARY":
                        if column_name in allowed_column_names:
                            primary_key.append(column_name)
                        else:
                            partial = True
                        continue
                    if ref_database is None or ref_table is None or ref_column is None:
                        continue
                    ref_database_name = str(ref_database)
                    ref_table_name = str(ref_table)
                    ref_column_name = str(ref_column)
                    if (
                        column_name not in allowed_column_names
                        or not self.config.access.table_allowed(
                            ref_database_name, ref_table_name
                        )
                        or not self.config.access.column_allowed(
                            ref_database_name, ref_table_name, ref_column_name
                        )
                    ):
                        partial = True
                        continue
                    try:
                        referenced_privileges = self._fetchall(
                            connection,
                            "SELECT PRIVILEGES FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                            "AND COLUMN_NAME = ?",
                            (ref_database_name, ref_table_name, ref_column_name),
                        )
                    except MCPAppError:
                        partial = True
                        continue
                    if not referenced_privileges or "select" not in {
                        privilege.strip().casefold()
                        for privilege in str(referenced_privileges[0][0]).split(",")
                    }:
                        partial = True
                        continue
                    group = foreign_key_groups.setdefault(
                        str(constraint),
                        {
                            "name": str(constraint),
                            "referenced_database": ref_database_name,
                            "referenced_table": ref_table_name,
                            "columns": [],
                        },
                    )
                    group["columns"].append(
                        {"local": column_name, "referenced": ref_column_name}
                    )
            except MCPAppError:
                partial = True
                logger.warning("Table key metadata is incomplete")

            indexes: dict[str, dict[str, Any]] = {}
            try:
                index_rows = self._fetchall(
                    connection,
                    "SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX "
                    "FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                    "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
                    (database, table),
                )
                for index_name, non_unique, column, _ in index_rows:
                    column_name = str(column)
                    if column_name not in allowed_column_names:
                        partial = True
                        continue
                    index = indexes.setdefault(
                        str(index_name),
                        {
                            "name": str(index_name),
                            "unique": not bool(non_unique),
                            "columns": [],
                        },
                    )
                    index["columns"].append(column_name)
            except MCPAppError:
                partial = True
                logger.warning("Table index metadata is incomplete")

        return {
            "database": database,
            "table": table,
            "columns": columns,
            "primary_key": primary_key,
            "indexes": list(indexes.values()),
            "foreign_keys": list(foreign_key_groups.values()),
            "partial": partial,
        }

    def _require_database(self, database: str) -> None:
        if not self.config.access.database_allowed(database):
            raise MCPAppError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The requested database is not available.",
            )

    def _require_table(self, database: str, table: str) -> None:
        if not self.config.access.table_allowed(database, table):
            raise MCPAppError(
                ErrorCode.AUTHORIZATION_DENIED,
                "The requested table is not available.",
            )

    @staticmethod
    def _fetchall(
        connection: Any, query: str, parameters: Sequence[Any]
    ) -> list[tuple[Any, ...]]:
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(query, tuple(parameters))
            return list(cursor.fetchall())
        except MCPAppError:
            raise
        except Exception as error:
            log_database_failure(error)
            raise MCPAppError(
                ErrorCode.DATABASE_ERROR,
                "Database metadata could not be retrieved.",
            ) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as error:
                    log_database_failure(error)

    @staticmethod
    def _table_page(
        database: str,
        names: list[str],
        offset: int,
        page_size: int,
        partial: bool = False,
    ) -> dict[str, Any]:
        has_more = len(names) > page_size
        tables = names[:page_size]
        return {
            "database": database,
            "tables": tables,
            "has_more": has_more,
            "next_offset": offset + page_size if has_more else None,
            "partial": partial,
        }


def register_metadata_tools(server: MCPServer, service: MetadataService) -> None:
    """Register stable, read-only metadata tools on an MCP server."""

    annotations = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    @server.tool(
        name="list_databases",
        description="List databases authorized by policy and visible to the account.",
        annotations=annotations,
        structured_output=True,
    )
    def list_databases() -> ListDatabasesResult:
        """List only authorized, account-visible database/schema names."""

        try:
            return service.list_databases()
        except MCPAppError as error:
            raise as_tool_error(error) from None

    @server.tool(
        name="list_tables",
        description="List base tables authorized in one database, in pages.",
        annotations=annotations,
        structured_output=True,
    )
    def list_tables(
        database: str, page_size: int | None = None, offset: int = 0
    ) -> TablePageResult:
        """List authorized base tables with bounded pagination."""

        try:
            return service.list_tables(database, page_size, offset)
        except MCPAppError as error:
            raise as_tool_error(error) from None

    @server.tool(
        name="describe_table",
        description=(
            "Describe columns, keys, indexes, and visible foreign keys "
            "of an authorized table."
        ),
        annotations=annotations,
        structured_output=True,
    )
    def describe_table(database: str, table: str) -> TableDescription:
        """Return only authorized structure and relationship metadata."""

        try:
            return service.describe_table(database, table)
        except MCPAppError as error:
            raise as_tool_error(error) from None
