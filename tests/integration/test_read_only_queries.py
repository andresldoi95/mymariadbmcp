from __future__ import annotations

import os
from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.query_service import QueryService

pytestmark = pytest.mark.integration


def test_authorized_read_and_write_rejection_against_mariadb() -> None:
    config_path = os.environ.get("MARIADB_MCP_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path:
        pytest.skip("Set MARIADB_MCP_INTEGRATION=1 and MARIADB_MCP_CONFIG to opt in.")
    config = load_config(Path(config_path))
    service = QueryService(config, lambda: connection_scope(config))

    result = service.execute("SELECT 1 AS value", [])

    assert result["rows"] == [[1]]
    with pytest.raises(MCPAppError) as error:
        service.execute("DELETE FROM mcp_test.sample_records", [])
    assert error.value.code is ErrorCode.UNSUPPORTED_QUERY
