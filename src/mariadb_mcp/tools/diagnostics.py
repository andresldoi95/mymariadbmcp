"""Connection diagnostics with deliberately limited output."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from typing_extensions import TypedDict

from mariadb_mcp.config import AppConfig
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure

logger = logging.getLogger("mariadb_mcp.diagnostics")
ConnectionFactory = Callable[[], AbstractContextManager[Any]]


class DiagnosticResult(TypedDict):
    status: Literal["ok", "unavailable", "misconfigured"]
    category: str
    message: str


class DiagnosticsService:
    """Test configured connectivity without returning connection details."""

    def __init__(
        self,
        config: AppConfig | None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.config = config
        self.connection_factory = connection_factory or (
            lambda: connection_scope(config)
        )

    def diagnose(self) -> DiagnosticResult:
        if self.config is None:
            return {
                "status": "misconfigured",
                "category": "configuration_invalid",
                "message": "Server configuration is missing or invalid.",
            }
        try:
            with self.connection_factory() as connection:
                cursor = None
                try:
                    cursor = connection.cursor(buffered=True)
                    cursor.execute("SELECT 1")
                    if cursor.fetchone() is None:
                        raise MCPAppError(
                            ErrorCode.DATABASE_ERROR,
                            "The database health check returned no result.",
                        )
                finally:
                    if cursor is not None:
                        try:
                            cursor.close()
                        except Exception as error:
                            log_database_failure(error)
        except MCPAppError as error:
            if error.code is ErrorCode.CONNECTION_FAILED:
                return _unavailable("connection_failed")
            logger.warning("Database diagnostic failed category=%s", error.code)
            return _unavailable(error.code.value)
        except ConnectionError:
            return _unavailable("connection_failed")
        except Exception as error:
            log_database_failure(error)
            return _unavailable("database_error")
        return {
            "status": "ok",
            "category": "connected",
            "message": "Database connection is available.",
        }


def _unavailable(category: str) -> DiagnosticResult:
    safe_categories = {
        "connection_failed",
        "database_error",
        "configuration_invalid",
        "authentication_failed",
    }
    if category not in safe_categories:
        category = "database_error"
    return {
        "status": "unavailable",
        "category": category,
        "message": (
            "Database connection is unavailable; check local configuration and grants."
        ),
    }


def register_diagnostics_tool(server: MCPServer, service: DiagnosticsService) -> None:
    """Register the secret-free connectivity diagnostic."""

    @server.tool(
        name="diagnose_connection",
        description="Check database connectivity without returning sensitive settings.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        structured_output=True,
    )
    def diagnose_connection() -> DiagnosticResult:
        """Return a curated connection state and safe failure category."""

        return service.diagnose()
