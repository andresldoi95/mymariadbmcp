from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mariadb_mcp.config import load_config
from mariadb_mcp.server import create_server


class LeakyConnectorFailure:
    def __init__(self) -> None:
        self.calls = 0

    def connect(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls == 1:
            return StartupConnection()
        raise RuntimeError(
            "password=sentinel-password dsn=mariadb://private-host/private-db"
        )


class StartupCursor:
    def execute(self, _query: str) -> None:
        pass

    def fetchone(self) -> tuple[str, None]:
        return ("mcp_ro@localhost", None)

    def fetchall(self) -> list[tuple[str]]:
        return [("GRANT SELECT ON `appdb`.* TO `mcp_ro`@`localhost`",)]

    def close(self) -> None:
        pass


class StartupConnection:
    def cursor(self, *, buffered: bool = True) -> StartupCursor:
        return StartupCursor()

    def close(self) -> None:
        pass


def test_database_failure_secrets_do_not_cross_mcp_or_log_boundaries(
    tmp_path: Path, caplog
) -> None:
    path = tmp_path / "mcp.toml"
    path.write_text(
        """
        [database]
        host = "localhost"
        username = "private-user"
        [access]
        allowed_databases = ["appdb"]
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "sentinel-password"})
    server = create_server(config, database_driver=LeakyConnectorFailure())

    with pytest.raises(ToolError) as query_error:
        asyncio.run(
            server.call_tool("query_read_only", {"sql": "SELECT 1", "parameters": []})
        )
    diagnostics_result = asyncio.run(server.call_tool("diagnose_connection", {}))
    exposed = str(query_error.value) + repr(diagnostics_result) + caplog.text

    assert "password=sentinel-password" not in exposed
    assert "private-host" not in exposed
    assert "private-db" not in exposed
    assert "private-user" not in exposed
