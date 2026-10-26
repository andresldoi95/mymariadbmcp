from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.config import load_config
from mariadb_mcp.tools.write import register_write_tools


class DeleteStub:
    def delete(
        self, database: str, table: str, filters: dict[str, Any]
    ) -> dict[str, Any]:
        return {"operation": "delete", "status": "success", "affected_rows": 1}


def make_config(tmp_path: Path):
    path = tmp_path / "writer.toml"
    path.write_text(
        """
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = { "appdb.orders" = ["id", "label"] }
        [writes]
        max_affected_rows = 10
        delete_tables = ["appdb.orders"]
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_delete_tool_requires_structured_filters_and_is_destructive(
    tmp_path: Path,
) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, DeleteStub(), config.writes)

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ["delete_records"]
    tool = tools[0]
    assert set(tool.input_schema["properties"]) == {"database", "table", "filters"}
    assert "sql" not in tool.input_schema["properties"]
    assert "max_affected_rows" not in tool.input_schema["properties"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True


def test_delete_tool_returns_structured_affected_row_count(tmp_path: Path) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, DeleteStub(), config.writes)

    result = asyncio.run(
        server.call_tool(
            "delete_records",
            {"database": "appdb", "table": "orders", "filters": {"id": 7}},
        )
    )

    assert result.is_error is False
    assert result.structured_content == {
        "operation": "delete",
        "status": "success",
        "affected_rows": 1,
    }
