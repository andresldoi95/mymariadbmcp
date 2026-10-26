from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.write_policy import WriteTargetSchema
from mariadb_mcp.write_service import WriteService


class SpyConnection:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.statements: list[str] = []

    def begin(self) -> None:
        self.events.append("begin")

    def cursor(self, *, buffered: bool = True) -> Any:
        raise AssertionError("unauthorized operation executed a statement")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def make_service(
    tmp_path: Path, write_policy: str
) -> tuple[WriteService, SpyConnection]:
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = {{ "appdb.orders" = ["id", "label"] }}
        {write_policy}
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    connection = SpyConnection()

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


def test_insert_permission_does_not_enable_update_or_delete(tmp_path: Path) -> None:
    service, connection = make_service(
        tmp_path,
        """
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        """,
    )

    for operation in (
        lambda: service.update("appdb", "orders", {"label": "x"}, {"id": 1}),
        lambda: service.delete("appdb", "orders", {"id": 1}),
    ):
        with pytest.raises(MCPAppError) as error:
            operation()
        assert error.value.code is ErrorCode.AUTHORIZATION_DENIED

    assert connection.statements == []
    assert connection.events == [
        "begin",
        "rollback",
        "close",
        "begin",
        "rollback",
        "close",
    ]


def test_update_permission_does_not_enable_insert(tmp_path: Path) -> None:
    service, connection = make_service(
        tmp_path,
        """
        [writes]
        max_affected_rows = 10
        update_columns = { "appdb.orders" = ["label"] }
        """,
    )

    with pytest.raises(MCPAppError) as error:
        service.insert("appdb", "orders", {"label": "x"})

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert connection.statements == []
    assert connection.events == ["begin", "rollback", "close"]


def test_update_cannot_change_a_field_not_allowed_for_update(tmp_path: Path) -> None:
    service, connection = make_service(
        tmp_path,
        """
        [writes]
        max_affected_rows = 10
        update_columns = { "appdb.orders" = ["label"] }
        """,
    )

    with pytest.raises(MCPAppError) as error:
        service.update("appdb", "orders", {"id": 7}, {"id": 1})

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert connection.statements == []
