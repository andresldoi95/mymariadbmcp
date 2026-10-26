from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mariadb_mcp.config import load_config
from mariadb_mcp.server import create_server


class StartupCursor:
    def __init__(self, username: str, grants: list[tuple[str]]) -> None:
        self.username = username
        self.grants = grants

    def execute(self, _query: str) -> None:
        pass

    def fetchone(self) -> tuple[str, None]:
        return (f"{self.username}@localhost", None)

    def fetchall(self) -> list[tuple[str]]:
        return self.grants

    def close(self) -> None:
        pass


class StartupConnection:
    def __init__(self, username: str, grants: list[tuple[str]]) -> None:
        self.cursor_value = StartupCursor(username, grants)

    def cursor(self, *, buffered: bool = True) -> StartupCursor:
        return self.cursor_value

    def close(self) -> None:
        pass


class StartupDriver:
    def __init__(self, username: str, grants: list[tuple[str]]) -> None:
        self.username = username
        self.grants = grants

    def connect(self, **_kwargs: Any) -> StartupConnection:
        return StartupConnection(self.username, self.grants)


def make_config(tmp_path: Path, *, writes: str = "", username: str = "mcp_rw"):
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "{username}"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = {{ "appdb.orders" = ["id", "label"] }}
        {writes}
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_server_registers_only_configured_operation_and_preserves_read_tools(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path,
        writes="""
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        """,
    )
    driver = StartupDriver(
        "mcp_rw",
        [
            (
                "GRANT SELECT (`id`, `label`) ON `appdb`.`orders` "
                "TO `mcp_rw`@`localhost`",
            ),
            ("GRANT INSERT (`label`) ON `appdb`.`orders` TO `mcp_rw`@`localhost`",),
        ],
    )

    tools = asyncio.run(create_server(config, database_driver=driver).list_tools())
    names = [tool.name for tool in tools]

    assert names == [
        "list_databases",
        "list_tables",
        "describe_table",
        "query_read_only",
        "explain_read_only",
        "insert_record",
        "diagnose_connection",
    ]
    assert "update_records" not in names
    assert "delete_records" not in names


def test_server_without_write_policy_keeps_existing_read_only_tool_list() -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    driver = StartupDriver(
        "mcp_ro",
        [("GRANT SELECT ON `appdb`.* TO `mcp_ro`@`localhost`",)],
    )

    tools = asyncio.run(create_server(config, database_driver=driver).list_tools())

    assert [tool.name for tool in tools] == [
        "list_databases",
        "list_tables",
        "describe_table",
        "query_read_only",
        "explain_read_only",
        "diagnose_connection",
    ]
