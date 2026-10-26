from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.write_policy import WriteTargetSchema
from mariadb_mcp.write_service import WriteService


class FakeCursor:
    def __init__(self, *, execute_error: Exception | None = None) -> None:
        self.execute_error = execute_error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rowcount = 1
        self.closed = False

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        self.calls.append((sql, parameters))
        if self.execute_error is not None:
            raise self.execute_error

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor
        self.events: list[str] = []

    def begin(self) -> None:
        self.events.append("begin")

    def cursor(self, *, buffered: bool = True) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def make_service(
    tmp_path: Path,
    *,
    insert_columns: str = '["label"]',
    cursor: FakeCursor | None = None,
) -> tuple[WriteService, FakeConnection, FakeCursor]:
    path = tmp_path / "writer.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = {{ "appdb.orders" = ["id", "label"] }}
        [writes]
        max_affected_rows = 10
        insert_columns = {{ "appdb.orders" = {insert_columns} }}
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    test_cursor = cursor or FakeCursor()
    connection = FakeConnection(test_cursor)

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.close()

    service = WriteService(
        config,
        connection_factory=connection_factory,
        schema_resolver=lambda _connection, _database, _table: WriteTargetSchema(
            columns=frozenset({"id", "label"}),
            engine="InnoDB",
            primary_key=("id",),
        ),
    )
    return service, connection, test_cursor


def test_insert_binds_values_and_commits_one_authorized_record(
    tmp_path: Path,
) -> None:
    service, connection, cursor = make_service(tmp_path)

    result = service.insert("appdb", "orders", {"label": "new order"})

    assert result == {
        "operation": "insert",
        "status": "success",
        "affected_rows": 1,
    }
    assert cursor.calls == [
        (
            "INSERT INTO `appdb`.`orders` (`label`) VALUES (?)",
            ("new order",),
        )
    ]
    assert connection.events == ["begin", "commit", "close"]
    assert cursor.closed is True


def test_insert_rejects_unapproved_field_without_executing_sql(
    tmp_path: Path,
) -> None:
    service, connection, cursor = make_service(tmp_path)

    with pytest.raises(MCPAppError) as error:
        service.insert("appdb", "orders", {"id": 99})

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert cursor.calls == []
    assert connection.events == ["begin", "rollback", "close"]


def test_insert_rejects_nested_values_and_rolls_back(tmp_path: Path) -> None:
    service, connection, cursor = make_service(tmp_path)

    with pytest.raises(MCPAppError) as error:
        service.insert("appdb", "orders", {"label": ["not", "scalar"]})

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert cursor.calls == []
    assert connection.events == ["begin", "rollback", "close"]


def test_insert_database_failure_is_sanitized_and_rolled_back(
    tmp_path: Path,
) -> None:
    cursor = FakeCursor(execute_error=RuntimeError("password=sentinel private-db"))
    service, connection, cursor = make_service(tmp_path, cursor=cursor)

    with pytest.raises(MCPAppError) as error:
        service.insert("appdb", "orders", {"label": "valid"})

    assert error.value.code is ErrorCode.DATABASE_ERROR
    assert "sentinel" not in str(error.value)
    assert "private-db" not in str(error.value)
    assert connection.events == ["begin", "rollback", "close"]
    assert cursor.closed is True
