"""MCP server construction and transport entry point."""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import Any

from mcp.server import MCPServer

from mariadb_mcp.config import AppConfig
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import MCPAppError
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.tools.diagnostics import DiagnosticsService, register_diagnostics_tool
from mariadb_mcp.tools.metadata import MetadataService, register_metadata_tools
from mariadb_mcp.tools.query import register_query_tools

logger = logging.getLogger("mariadb_mcp.server")


def create_server(
    config: AppConfig | None = None,
    *,
    database_driver: Any | None = None,
) -> MCPServer:
    """Register data tools only after the configured runtime identity passes."""

    server = MCPServer(
        name="MariaDB MCP Server",
        title="MariaDB MCP Server",
        instructions=(
            "Discover and query only database objects authorized by the server's "
            "configured access policy and MariaDB account."
        ),
        log_level="WARNING",
    )
    if config is not None:

        def connection_factory() -> AbstractContextManager[Any]:
            return connection_scope(config, driver=database_driver)

        try:
            with connection_factory():
                pass
        except MCPAppError:
            logger.warning(
                "Runtime identity preflight failed; data tools are disabled."
            )
            diagnostics = DiagnosticsService(config, connection_factory)
            register_diagnostics_tool(server, diagnostics)
            return server

        register_metadata_tools(
            server,
            MetadataService(config, connection_factory),
        )
        register_query_tools(server, QueryService(config, connection_factory))
        diagnostics = DiagnosticsService(config, connection_factory)
    else:
        diagnostics = DiagnosticsService(None)
    register_diagnostics_tool(server, diagnostics)
    return server
