from __future__ import annotations

import os
from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.tools.diagnostics import DiagnosticsService

pytestmark = pytest.mark.integration


def test_explain_and_diagnostics_against_configured_database() -> None:
    config_path = os.environ.get("MARIADB_MCP_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path:
        pytest.skip("Set MARIADB_MCP_INTEGRATION=1 and MARIADB_MCP_CONFIG to opt in.")
    config = load_config(Path(config_path))
    service = QueryService(config, lambda: connection_scope(config))
    diagnostics = DiagnosticsService(config, lambda: connection_scope(config))

    assert service.explain("SELECT 1", [])["truncated"] is False
    assert diagnostics.diagnose()["status"] == "ok"
