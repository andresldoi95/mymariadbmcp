from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from mariadb_mcp.config import load_config
from mariadb_mcp.server import create_server


class StartupCursor:
    def __init__(self, grants: list[tuple[str]] | None = None) -> None:
        self.grants = grants or [("GRANT SELECT ON `appdb`.* TO `mcp_ro`@`localhost`",)]

    def execute(self, _query: str) -> None:
        pass

    def fetchone(self) -> tuple[str, None]:
        return ("mcp_ro@localhost", None)

    def fetchall(self) -> list[tuple[str]]:
        return self.grants

    def close(self) -> None:
        pass


class StartupConnection:
    def __init__(self, grants: list[tuple[str]] | None = None) -> None:
        self.grants = grants

    def cursor(self, *, buffered: bool = True) -> StartupCursor:
        return StartupCursor(self.grants)

    def close(self) -> None:
        pass


class StartupDriver:
    def __init__(self, grants: list[tuple[str]] | None = None) -> None:
        self.grants = grants

    def connect(self, **_kwargs: object) -> StartupConnection:
        return StartupConnection(self.grants)


def make_config():
    return load_config(
        Path("tests/fixtures/local.toml"),
        environ={"MARIADB_MCP_PASSWORD": "test-secret"},
    )


def test_mcp_tools_list_is_deterministic_and_contains_contract_tools() -> None:
    server = create_server(make_config(), database_driver=StartupDriver())

    first = asyncio.run(server.list_tools())
    second = asyncio.run(server.list_tools())

    names = [tool.name for tool in first]
    assert names == [
        "list_databases",
        "list_tables",
        "describe_table",
        "query_read_only",
        "explain_read_only",
        "diagnose_connection",
    ]
    assert [tool.name for tool in second] == names


def test_missing_configuration_exposes_only_safe_diagnostics() -> None:
    server = create_server()

    tools = asyncio.run(server.list_tools())
    result = asyncio.run(server.call_tool("diagnose_connection", {}))

    assert [tool.name for tool in tools] == ["diagnose_connection"]
    assert tools[0].output_schema is not None
    assert result.structured_content == {
        "status": "misconfigured",
        "category": "configuration_invalid",
        "message": "Server configuration is missing or invalid.",
    }


def test_tool_schemas_are_objects_and_use_stable_descriptions() -> None:
    server = create_server(make_config(), database_driver=StartupDriver())
    tools = asyncio.run(server.list_tools())

    for tool in tools:
        assert tool.input_schema["type"] == "object"
        assert tool.description


def test_privileged_identity_is_rejected_before_data_tools_are_registered() -> None:
    server = create_server(
        make_config(),
        database_driver=StartupDriver(
            [("GRANT SELECT, INSERT ON `appdb`.* TO `mcp_ro`",)]
        ),
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ["diagnose_connection"]


def test_native_module_exits_cleanly_on_stdio_eof_without_stdout(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mcp.toml"
    config_path.write_text(
        """
        [database]
        host = "localhost"
        username = "mcp_ro"
        [access]
        allowed_databases = []
        """,
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["MARIADB_MCP_CONFIG"] = str(config_path)
    environment["MARIADB_MCP_PASSWORD"] = "startup-sentinel"

    result = subprocess.run(
        [sys.executable, "-m", "mariadb_mcp"],
        input="",
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "startup-sentinel" not in result.stderr


def test_native_module_keeps_stdio_available_when_configuration_is_missing(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["MARIADB_MCP_CONFIG"] = str(tmp_path / "missing.toml")
    environment.pop("MARIADB_MCP_PASSWORD", None)

    result = subprocess.run(
        [sys.executable, "-m", "mariadb_mcp"],
        input="",
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "configuration is invalid" in result.stderr
