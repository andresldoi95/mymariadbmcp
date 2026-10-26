from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.config import load_config
from mariadb_mcp.tools.write import register_write_tools


class InsertStub:
    def insert(
        self, database: str, table: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "operation": "insert",
            "status": "success",
            "affected_rows": 1,
        }


def make_config(tmp_path: Path, *, enabled: bool = True):
    path = tmp_path / "writer.toml"
    writes = (
        "[writes]\nmax_affected_rows = 10\n"
        'insert_columns = { "appdb.orders" = ["label"] }\n'
        if enabled
        else ""
    )
    path.write_text(
        """
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        """
        + writes,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_insert_tool_has_structured_arguments_and_destructive_annotations(
    tmp_path: Path,
) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, InsertStub(), config.writes)

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ["insert_record"]
    tool = tools[0]
    assert tool.input_schema["type"] == "object"
    assert set(tool.input_schema["properties"]) == {"database", "table", "values"}
    assert "sql" not in tool.input_schema["properties"]
    assert tool.output_schema is not None
    assert set(tool.output_schema["properties"]) == {
        "operation",
        "status",
        "affected_rows",
    }
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True


def test_insert_tool_returns_structured_result_without_client_controlled_cap(
    tmp_path: Path,
) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path)
    register_write_tools(server, InsertStub(), config.writes)

    tool = asyncio.run(server.list_tools())[0]
    result = asyncio.run(
        server.call_tool(
            "insert_record",
            {
                "database": "appdb",
                "table": "orders",
                "values": {"label": "new"},
            },
        )
    )

    assert "max_affected_rows" not in tool.input_schema["properties"]
    assert result.is_error is False
    assert result.structured_content == {
        "operation": "insert",
        "status": "success",
        "affected_rows": 1,
    }


def test_insert_tool_is_not_registered_without_insert_policy(tmp_path: Path) -> None:
    server = MCPServer(name="test")
    config = make_config(tmp_path, enabled=False)
    register_write_tools(server, InsertStub(), config.writes)

    assert asyncio.run(server.list_tools()) == []
