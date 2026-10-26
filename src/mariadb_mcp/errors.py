"""Sanitized errors shared by database services and MCP tool handlers."""

from __future__ import annotations

import logging
from enum import StrEnum

from mcp.server.mcpserver.exceptions import ToolError

logger = logging.getLogger("mariadb_mcp")


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    AUTHORIZATION_DENIED = "authorization_denied"
    UNSUPPORTED_QUERY = "unsupported_query"
    CONNECTION_FAILED = "connection_failed"
    QUERY_TIMEOUT = "query_timeout"
    RESULT_LIMIT = "result_limit"
    DATABASE_ERROR = "database_error"
    CONFIGURATION_INVALID = "configuration_invalid"
    INTERNAL_ERROR = "internal_error"


class MCPAppError(Exception):
    """An exception containing only a safe, deliberate client-facing message."""

    def __init__(self, code: ErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


def log_database_failure(_error: BaseException) -> None:
    """Log a generic category; connector exception text can contain secrets."""

    logger.error("Database operation failed")


def safe_failure_message(code: ErrorCode) -> str:
    """Map an internal category to a curated message without exception details."""

    messages = {
        ErrorCode.INVALID_INPUT: "The request contains invalid input.",
        ErrorCode.AUTHORIZATION_DENIED: (
            "The request is outside the allowed data scope."
        ),
        ErrorCode.UNSUPPORTED_QUERY: "The query uses an unsupported SQL construct.",
        ErrorCode.CONNECTION_FAILED: "The database connection is unavailable.",
        ErrorCode.QUERY_TIMEOUT: "The query exceeded its configured time limit.",
        ErrorCode.RESULT_LIMIT: "The result exceeded a configured safety limit.",
        ErrorCode.DATABASE_ERROR: "The database operation failed.",
        ErrorCode.CONFIGURATION_INVALID: "The server configuration is invalid.",
        ErrorCode.INTERNAL_ERROR: "The request could not be completed safely.",
    }
    return messages[code]


def as_tool_error(error: MCPAppError) -> ToolError:
    """Convert an expected failure into a curated MCP tool error."""

    return ToolError(f"{error.code}: {error.safe_message}")
