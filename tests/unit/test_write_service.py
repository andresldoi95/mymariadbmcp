from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.write_service import WriteService


class FakeConnection:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.events: list[str] = []
        self.commit_error = commit_error

    def begin(self) -> None:
        self.events.append("begin")

    def commit(self) -> None:
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def make_service(connection: FakeConnection) -> WriteService:
    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.close()

    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    return WriteService(config, connection_factory=connection_factory)


def test_write_transaction_commits_and_releases_connection() -> None:
    connection = FakeConnection()
    service = make_service(connection)

    result = service.execute_transaction("insert", lambda _connection: 1)

    assert result == {
        "operation": "insert",
        "status": "success",
        "affected_rows": 1,
    }
    assert connection.events == ["begin", "commit", "close"]


def test_write_transaction_rolls_back_application_errors() -> None:
    connection = FakeConnection()
    service = make_service(connection)

    def reject(_connection: Any) -> int:
        raise MCPAppError(ErrorCode.AUTHORIZATION_DENIED, "Safe rejection.")

    with pytest.raises(MCPAppError) as error:
        service.execute_transaction("update", reject)

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert connection.events == ["begin", "rollback", "close"]


def test_write_transaction_sanitizes_database_failure_and_rolls_back() -> None:
    connection = FakeConnection()
    service = make_service(connection)

    def fail(_connection: Any) -> int:
        raise RuntimeError("password=sentinel host=private-db")

    with pytest.raises(MCPAppError) as error:
        service.execute_transaction("delete", fail)

    assert error.value.code is ErrorCode.DATABASE_ERROR
    assert "sentinel" not in str(error.value)
    assert "private-db" not in str(error.value)
    assert connection.events == ["begin", "rollback", "close"]


def test_uncertain_commit_returns_unknown_without_retry_or_rollback() -> None:
    connection = FakeConnection(commit_error=ConnectionError("lost after commit"))
    service = make_service(connection)

    result = service.execute_transaction("delete", lambda _connection: 2)

    assert result == {
        "operation": "delete",
        "status": "unknown",
        "affected_rows": None,
    }
    assert connection.events == ["begin", "commit", "close"]
