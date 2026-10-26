from __future__ import annotations

import logging

from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure


def test_safe_error_message_does_not_include_cause_or_secret() -> None:
    error = MCPAppError(ErrorCode.DATABASE_ERROR, "Database operation failed safely.")
    error.__cause__ = RuntimeError("password=sentinel host=db.internal")

    assert error.code is ErrorCode.DATABASE_ERROR
    assert "sentinel" not in str(error)
    assert "db.internal" not in str(error)


def test_database_failure_logs_only_safe_category(caplog) -> None:
    caplog.set_level(logging.ERROR)

    log_database_failure(RuntimeError("password=sentinel"))

    assert "sentinel" not in caplog.text
    assert "Database operation failed" in caplog.text
    assert "RuntimeError" not in caplog.text
