from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.tools.metadata import register_metadata_tools


class MetadataStub:
    def list_databases(self) -> dict[str, Any]:
        return {"databases": ["appdb"], "partial": False}

    def list_tables(
        self, database: str, page_size: int | None = None, offset: int = 0
    ) -> dict[str, Any]:
        return {
            "database": database,
            "tables": ["orders"],
            "has_more": False,
            "next_offset": None,
            "partial": False,
        }

    def describe_table(self, database: str, table: str) -> dict[str, Any]:
        return {
            "database": database,
            "table": table,
            "columns": [{"name": "id", "type": "BIGINT", "nullable": False}],
            "primary_key": ["id"],
            "indexes": [],
            "foreign_keys": [],
            "partial": False,
        }


def test_metadata_tools_have_contract_schemas_and_stable_names() -> None:
    server = MCPServer(name="test")
    register_metadata_tools(server, MetadataStub())

    tools = asyncio.run(server.list_tools())
    assert [tool.name for tool in tools] == [
        "list_databases",
        "list_tables",
        "describe_table",
    ]
    assert all(tool.input_schema["type"] == "object" for tool in tools)
    assert all(tool.output_schema is not None for tool in tools)
    assert set(tools[0].output_schema["properties"]) == {"databases", "partial"}
    assert set(tools[1].output_schema["properties"]) == {
        "database",
        "tables",
        "has_more",
        "next_offset",
        "partial",
    }


def test_metadata_tool_descriptions_explain_authorized_scope() -> None:
    server = MCPServer(name="test")
    register_metadata_tools(server, MetadataStub())

    tools = asyncio.run(server.list_tools())
    assert all("authorized" in tool.description.lower() for tool in tools)


def test_list_databases_returns_structured_mcp_content() -> None:
    server = MCPServer(name="test")
    register_metadata_tools(server, MetadataStub())

    result = asyncio.run(server.call_tool("list_databases", {}))

    assert result.is_error is False
    assert result.structured_content == {"databases": ["appdb"], "partial": False}
