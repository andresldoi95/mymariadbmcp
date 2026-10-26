from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.server import create_server

pytestmark = pytest.mark.integration


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def test_runtime_account_is_independently_read_only() -> None:
    config_path = os.environ.get("MARIADB_MCP_CONFIG")
    table = os.environ.get("MARIADB_MCP_TEST_WRITE_PROBE_TABLE")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path or not table:
        pytest.skip(
            "Set integration opt-in, MARIADB_MCP_CONFIG, and "
            "MARIADB_MCP_TEST_WRITE_PROBE_TABLE for a disposable database."
        )
    config = load_config(Path(config_path))
    import mariadb

    if "." not in table:
        pytest.skip("The write-probe table must use database.table notation.")
    database, table_name = table.split(".", 1)
    if not config.access.table_allowed(database, table_name):
        pytest.skip(
            "The write-probe table must be inside the configured test allowlist."
        )

    service = QueryService(config, lambda: connection_scope(config))
    with pytest.raises(MCPAppError) as rejected:
        service.execute(f"DELETE FROM {table} WHERE 1 = 0", [])
    assert rejected.value.code is ErrorCode.UNSUPPORTED_QUERY

    # This zero-match statement is intentionally sent only to the disposable
    # test database; it proves MariaDB itself denies DML to the runtime account.
    with connection_scope(config) as connection:
        cursor = connection.cursor(buffered=True)
        try:
            qualified = f"{_quote_identifier(database)}.{_quote_identifier(table_name)}"
            with pytest.raises(mariadb.Error):
                cursor.execute(f"DELETE FROM {qualified} WHERE 1 = 0")
        finally:
            cursor.close()


def test_runtime_preflight_rejects_privileges_or_inherited_roles() -> None:
    config_path = os.environ.get("MARIADB_MCP_TEST_PRIVILEGED_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path:
        pytest.skip(
            "Set MARIADB_MCP_INTEGRATION=1 and "
            "MARIADB_MCP_TEST_PRIVILEGED_CONFIG to a disposable account config "
            "with a write-capable privilege or inherited role."
        )
    config = load_config(Path(config_path))

    with pytest.raises(MCPAppError) as rejected:
        with connection_scope(config):
            pytest.fail("the privileged disposable identity passed preflight")

    assert rejected.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_server_registers_data_tools_only_after_live_grant_preflight() -> None:
    readonly_path = os.environ.get("MARIADB_MCP_CONFIG")
    privileged_path = os.environ.get("MARIADB_MCP_TEST_PRIVILEGED_CONFIG")
    if (
        os.environ.get("MARIADB_MCP_INTEGRATION") != "1"
        or not readonly_path
        or not privileged_path
    ):
        pytest.skip(
            "Set integration opt-in, MARIADB_MCP_CONFIG, and "
            "MARIADB_MCP_TEST_PRIVILEGED_CONFIG for disposable accounts."
        )

    readonly = create_server(load_config(Path(readonly_path)))
    privileged = create_server(load_config(Path(privileged_path)))

    assert [tool.name for tool in asyncio.run(readonly.list_tools())] == [
        "list_databases",
        "list_tables",
        "describe_table",
        "query_read_only",
        "explain_read_only",
        "diagnose_connection",
    ]
    assert [tool.name for tool in asyncio.run(privileged.list_tools())] == [
        "diagnose_connection"
    ]
