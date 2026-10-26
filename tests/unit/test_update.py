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
    def __init__(
        self,
        connection: FakeConnection,
    ) -> None:
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
    primary_key: tuple[str, ...] = ("id",),
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
        allowed_columns = { "appdb.orders" = ["id", "part", "label"] }
        [writes]
        max_affected_rows = 2
        update_columns = { "appdb.orders" = ["label"] }
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

    columns = frozenset({"id", "part", "label"})
    service = WriteService(
        config,
        connection_factory=connection_factory,
        schema_resolver=lambda _connection, _database, _table: WriteTargetSchema(
            columns=columns,
            engine="InnoDB",
            primary_key=primary_key,
        ),
    )
    return service, connection


def test_update_locks_matching_keys_then_changes_only_locked_rows(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path, keys=[(7,)])

    result = service.update("appdb", "orders", {"label": "changed"}, {"id": 7})

    assert result == {
        "operation": "update",
        "status": "success",
        "affected_rows": 1,
    }
    assert connection.calls == [
        (
            "SELECT `id` FROM `appdb`.`orders` WHERE `id` = ? "
            "ORDER BY `id` LIMIT ? FOR UPDATE",
            (7, 3),
        ),
        (
            "UPDATE `appdb`.`orders` SET `label` = ? WHERE (`id` = ?)",
            ("changed", 7),
        ),
    ]
    assert connection.events == ["begin", "commit", "close"]
    assert connection.closed_cursors == 2


def test_update_rolls_back_without_mutation_when_candidates_exceed_cap(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path, keys=[(1,), (2,), (3,)])

    with pytest.raises(MCPAppError) as error:
        service.update("appdb", "orders", {"label": "changed"}, {"part": 1})

    assert error.value.code is ErrorCode.RESULT_LIMIT
    assert len(connection.calls) == 1
    assert connection.events == ["begin", "rollback", "close"]
    assert connection.closed_cursors == 1


def test_update_with_no_matches_returns_zero_without_running_dml(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path)

    result = service.update("appdb", "orders", {"label": "changed"}, {"id": 99})

    assert result["status"] == "success"
    assert result["affected_rows"] == 0
    assert len(connection.calls) == 1
    assert connection.events == ["begin", "commit", "close"]


def test_update_supports_composite_primary_keys_and_null_filters(
    tmp_path: Path,
) -> None:
    service, connection = make_service(
        tmp_path,
        keys=[(3, 8)],
        primary_key=("id", "part"),
    )

    result = service.update("appdb", "orders", {"label": "changed"}, {"label": None})

    assert result["affected_rows"] == 1
    assert connection.calls == [
        (
            "SELECT `id`, `part` FROM `appdb`.`orders` WHERE `label` IS NULL "
            "ORDER BY `id`, `part` LIMIT ? FOR UPDATE",
            (3,),
        ),
        (
            "UPDATE `appdb`.`orders` SET `label` = ? WHERE (`id` = ? AND `part` = ?)",
            ("changed", 3, 8),
        ),
    ]


def test_update_rejects_empty_filter_before_database_statement(
    tmp_path: Path,
) -> None:
    service, connection = make_service(tmp_path, keys=[(1,)])

    with pytest.raises(MCPAppError) as error:
        service.update("appdb", "orders", {"label": "changed"}, {})

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert connection.calls == []
    assert connection.events == ["begin", "rollback", "close"]
