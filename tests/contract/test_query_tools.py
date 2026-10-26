from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.tools.query import register_query_tools


class QueryStub:
    def execute(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0,
            "truncated": False,
            "truncation_reason": None,
            "has_more": False,
        }


def test_query_tool_schema_is_structured_bounded_and_read_only() -> None:
    server = MCPServer(name="test")
    register_query_tools(server, QueryStub())

    tools = asyncio.run(server.list_tools())

    by_name = {tool.name: tool for tool in tools}
    assert "query_read_only" in by_name
    tool = by_name["query_read_only"]
    assert tool.input_schema["type"] == "object"
    assert "sql" in tool.input_schema["properties"]
    assert tool.output_schema is not None
    assert set(tool.output_schema["properties"]) == {
        "columns",
        "rows",
        "row_count",
        "execution_time_ms",
        "truncated",
        "truncation_reason",
        "has_more",
    }
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True


def test_query_tool_schema_never_allows_client_to_raise_server_caps() -> None:
    server = MCPServer(name="test")
    register_query_tools(server, QueryStub())

    tool = next(
        tool
        for tool in asyncio.run(server.list_tools())
        if tool.name == "query_read_only"
    )

    assert "max_rows" not in tool.input_schema["properties"]
    assert "timeout" not in tool.input_schema["properties"]


def test_query_tool_returns_structured_mcp_content() -> None:
    server = MCPServer(name="test")
    register_query_tools(server, QueryStub())

    result = asyncio.run(
        server.call_tool("query_read_only", {"sql": "SELECT 1", "parameters": []})
    )

    assert result.is_error is False
    assert result.structured_content["row_count"] == 0
    assert result.structured_content["truncated"] is False
