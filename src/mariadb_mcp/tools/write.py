"""MCP tool registration for explicitly configured database write operations."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from mariadb_mcp.config import WritePolicy
from mariadb_mcp.errors import MCPAppError, as_tool_error
from mariadb_mcp.write_service import WriteService


class WriteToolResult(TypedDict):
    operation: str
    status: str
    affected_rows: int | None


def register_write_tools(
    server: MCPServer, service: WriteService, policy: WritePolicy
) -> None:
    """Register only write operations explicitly enabled by configuration."""

    if any(policy.insert_columns.values()):

        @server.tool(
            name="insert_record",
            description=(
                "Insert one record into a configured table using only authorized "
                "columns. Values are bound; database and server write limits apply."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
            structured_output=True,
        )
        def insert_record(
            database: str, table: str, values: dict[str, Any]
        ) -> WriteToolResult:
            """Insert one record after operation and field authorization."""

            try:
                return service.insert(database, table, values)
            except MCPAppError as error:
                raise as_tool_error(error) from None

    if any(policy.update_columns.values()):

        @server.tool(
            name="update_records",
            description=(
                "Update authorized fields on records matching a non-empty set of "
                "equality filters. The configured affected-row limit applies."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
            structured_output=True,
        )
        def update_records(
            database: str,
            table: str,
            values: dict[str, Any],
            filters: dict[str, Any],
        ) -> WriteToolResult:
            """Update selected records after operation and field authorization."""

            try:
                return service.update(database, table, values, filters)
            except MCPAppError as error:
                raise as_tool_error(error) from None

    if policy.delete_tables:

        @server.tool(
            name="delete_records",
            description=(
                "Delete records from a configured table matching a non-empty set "
                "of equality filters. The configured affected-row limit applies."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
            structured_output=True,
        )
        def delete_records(
            database: str, table: str, filters: dict[str, Any]
        ) -> WriteToolResult:
            """Delete selected records after operation and table authorization."""

            try:
                return service.delete(database, table, filters)
            except MCPAppError as error:
                raise as_tool_error(error) from None
