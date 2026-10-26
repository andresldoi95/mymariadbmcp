from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.tools.diagnostics import register_diagnostics_tool
from mariadb_mcp.tools.query import register_query_tools


class QueryStub:
    def execute(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        return {"columns": [], "rows": [], "row_count": 0}

    def explain(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        return {"plan": {"rows": []}, "execution_time_ms": 0, "truncated": False}


class DiagnosticsStub:
    def diagnose(self) -> dict[str, str]:
        return {
            "status": "ok",
            "category": "connected",
            "message": "Database connection is available.",
        }


def test_analysis_and_diagnostics_tools_have_stable_structured_contracts() -> None:
    server = MCPServer(name="test")
    register_query_tools(server, QueryStub())
    register_diagnostics_tool(server, DiagnosticsStub())

    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert "explain_read_only" in by_name
    assert "diagnose_connection" in by_name
    assert by_name["explain_read_only"].output_schema is not None
    assert by_name["diagnose_connection"].output_schema is not None
    assert by_name["explain_read_only"].annotations.read_only_hint is True


def test_diagnostics_schema_contains_no_connection_secret_fields() -> None:
    server = MCPServer(name="test")
    register_diagnostics_tool(server, DiagnosticsStub())

    tool = asyncio.run(server.list_tools())[0]
    properties = tool.output_schema["properties"]

    assert set(properties) == {"status", "category", "message"}
    assert not {"host", "port", "username", "database", "password"}.intersection(
        properties
    )
