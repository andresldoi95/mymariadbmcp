from __future__ import annotations

import os
from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.tools.metadata import MetadataService

pytestmark = pytest.mark.integration


def test_runtime_account_lists_only_configured_metadata() -> None:
    config_path = os.environ.get("MARIADB_MCP_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path:
        pytest.skip("Set MARIADB_MCP_INTEGRATION=1 and MARIADB_MCP_CONFIG to opt in.")
    config = load_config(Path(config_path))
    service = MetadataService(config, lambda: connection_scope(config))

    result = service.list_databases()

    assert set(result["databases"]).issubset(config.access.allowed_databases)
