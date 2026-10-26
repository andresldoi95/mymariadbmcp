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
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.rowcount = 1
        self.closed = False

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        self.connection.calls.append((sql, parameters))
        if sql.startswith("SELECT "):
            self.rows = self.connection.keys
        else:
            self.rowcount = self.connection.affected_rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True
        self.connection.closed_cursors += 1


class FakeConnection:
    def __init__(
        self,
        *,
        keys: list[tuple[Any, ...]],
        affected_rows: int = 1,
    ) -> None:
        self.keys = keys
        self.affected_rows = affected_rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.events: list[str] = []
        self.closed_cursors = 0

    def begin(self) -> None:
        self.events.append("begin")

    def cursor(self, *, buffered: bool = True) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def make_service(
    tmp_path: Path,
    *,
    keys: list[tuple[Any, ...]] | None = None,
    affected_rows: int = 1,
) -> tuple[WriteService, FakeConnection]:
    path = tmp_path / "writer.toml"
    path.write_text(
        """
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = { "appdb.orders" = ["id", "label"] }
        [writes]
        max_affected_rows = 2
        delete_tables = ["appdb.orders"]
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    connection = FakeConnection(keys=keys or [], affected_rows=affected_rows)

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
    return service, connection


def test_delete_locks_matching_keys_then_deletes_only_locked_rows(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path, keys=[(7,)])

    result = service.delete("appdb", "orders", {"id": 7})

    assert result == {
        "operation": "delete",
        "status": "success",
        "affected_rows": 1,
    }
    assert connection.calls == [
        (
            "SELECT `id` FROM `appdb`.`orders` WHERE `id` = ? "
            "ORDER BY `id` LIMIT ? FOR UPDATE",
            (7, 3),
        ),
        ("DELETE FROM `appdb`.`orders` WHERE (`id` = ?)", (7,)),
    ]
    assert connection.events == ["begin", "commit", "close"]
    assert connection.closed_cursors == 2


def test_delete_rolls_back_when_matching_rows_exceed_cap(tmp_path: Path) -> None:
    service, connection = make_service(tmp_path, keys=[(1,), (2,), (3,)])

    with pytest.raises(MCPAppError) as error:
        service.delete("appdb", "orders", {"label": "fixture"})

    assert error.value.code is ErrorCode.RESULT_LIMIT
    assert len(connection.calls) == 1
    assert connection.events == ["begin", "rollback", "close"]


def test_delete_with_no_matches_returns_zero_without_running_dml(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path)

    result = service.delete("appdb", "orders", {"id": 99})

    assert result["status"] == "success"
    assert result["affected_rows"] == 0
    assert len(connection.calls) == 1
    assert connection.events == ["begin", "commit", "close"]


def test_delete_rejects_empty_filters_before_database_statement(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path, keys=[(1,)])

    with pytest.raises(MCPAppError) as error:
        service.delete("appdb", "orders", {})

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert connection.calls == []
    assert connection.events == ["begin", "rollback", "close"]
