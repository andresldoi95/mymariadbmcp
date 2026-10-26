"""Read-only query MCP tool registration."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from mariadb_mcp.errors import MCPAppError, as_tool_error
from mariadb_mcp.query_service import QueryService


class QueryColumn(TypedDict):
    name: str
    type: str


class QueryResult(TypedDict):
    columns: list[QueryColumn]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: int
    truncated: bool
    truncation_reason: Literal["row_limit", "byte_limit"] | None
    has_more: bool


class ExplainPlan(TypedDict):
    columns: list[QueryColumn]
    rows: list[list[Any]]


class ExplainResult(TypedDict):
    plan: ExplainPlan
    execution_time_ms: int
    truncated: bool


def register_query_tools(server: MCPServer, service: QueryService) -> None:
    """Register bounded read-only query execution."""

    @server.tool(
        name="query_read_only",
        description=(
            "Run one authorized read-only SELECT. Use WHERE, ORDER BY, LIMIT, and "
            "OFFSET for filtering, sorting, and pages. "
            "Server result and time limits apply."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        structured_output=True,
    )
    def query_read_only(sql: str, parameters: list[Any] | None = None) -> QueryResult:
        """Run a supported SELECT with bound values and bounded structured output."""

        try:
            return service.execute(sql, parameters)
        except MCPAppError as error:
            raise as_tool_error(error) from None

    @server.tool(
        name="explain_read_only",
        description=(
            "Return a bounded execution plan for one authorized SELECT without "
            "executing that SELECT."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        structured_output=True,
    )
    def explain_read_only(
        sql: str, parameters: list[Any] | None = None
    ) -> ExplainResult:
        """Explain a supported SELECT after the same policy checks as querying."""

        try:
            return service.explain(sql, parameters)
        except MCPAppError as error:
            raise as_tool_error(error) from None
