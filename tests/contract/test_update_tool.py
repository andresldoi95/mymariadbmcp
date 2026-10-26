from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.config import load_config
from mariadb_mcp.tools.write import register_write_tools


class UpdateStub:
    def update(
        self,
        database: str,
        table: str,
        values: dict[str, Any],
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        return {"operation": "update", "status": "success", "affected_rows": 2}


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
        update_columns = { "appdb.orders" = ["label"] }
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_update_tool_requires_structured_values_and_nonempty_filters(
    tmp_path: Path,
) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, UpdateStub(), config.writes)

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ["update_records"]
    tool = tools[0]
    assert set(tool.input_schema["properties"]) == {
        "database",
        "table",
        "values",
        "filters",
    }
    assert "sql" not in tool.input_schema["properties"]
    assert "max_affected_rows" not in tool.input_schema["properties"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True


def test_update_tool_returns_structured_changed_row_count(tmp_path: Path) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, UpdateStub(), config.writes)

    result = asyncio.run(
        server.call_tool(
            "update_records",
            {
                "database": "appdb",
                "table": "orders",
                "values": {"label": "changed"},
                "filters": {"id": 7},
            },
        )
    )

    assert result.is_error is False
    assert result.structured_content == {
        "operation": "update",
        "status": "success",
        "affected_rows": 2,
    }
