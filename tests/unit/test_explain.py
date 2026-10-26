from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.sql_policy import TableSchema


class ExplainCursor:
    description = [
        ("id", "BIGINT", None, None, None, None, True),
        ("select_type", "VARCHAR", None, None, None, None, True),
    ]

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = list(rows)
        self.executed: tuple[str, tuple[Any, ...]] | None = None
        self.closed = False

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        self.executed = (sql, parameters)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None

    def close(self) -> None:
        self.closed = True


class ExplainConnection:
    def __init__(self, cursor: ExplainCursor) -> None:
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self, *, buffered: bool) -> ExplainCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def make_service(
    tmp_path: Path,
    rows: list[tuple[Any, ...]],
    *,
    max_rows: int = 1000,
) -> tuple[QueryService, ExplainConnection, ExplainCursor]:
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_ro"
        default_database = "appdb"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        [limits]
        max_rows = {max_rows}
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    cursor = ExplainCursor(rows)
    connection = ExplainConnection(cursor)

    @contextmanager
    def connection_factory() -> Iterator[ExplainConnection]:
        try:
            yield connection
        finally:
            connection.close()

    def schema_resolver(
        _connection: ExplainConnection, database: str, table: str
    ) -> TableSchema | None:
        if (database, table) == ("appdb", "orders"):
            return TableSchema(frozenset({"id"}))
        return None

    return (
        QueryService(config, connection_factory, schema_resolver=schema_resolver),
        connection,
        cursor,
    )


def test_explain_validates_then_runs_only_explain_with_bound_values(
    tmp_path: Path,
) -> None:
    service, connection, cursor = make_service(tmp_path, [(1, "SIMPLE")])
    sql = "SELECT id FROM appdb.orders WHERE id = ?"

    result = service.explain(sql, [5])

    assert cursor.executed == (f"EXPLAIN {sql}", (5,))
    assert result["plan"]["rows"] == [[1, "SIMPLE"]]
    assert result["truncated"] is False
    assert cursor.closed is True
    assert connection.closed is True


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM appdb.orders",
        "EXPLAIN DELETE FROM appdb.orders",
        "SELECT id FROM appdb.private",
        "SELECT id FROM appdb.orders UNION SELECT id FROM appdb.orders",
    ],
)
def test_explain_rejects_unsupported_or_unauthorized_inner_queries(
    tmp_path: Path, sql: str
) -> None:
    service, _, cursor = make_service(tmp_path, [])

    with pytest.raises(MCPAppError) as error:
        service.explain(sql, [])

    assert error.value.code in {
        ErrorCode.UNSUPPORTED_QUERY,
        ErrorCode.AUTHORIZATION_DENIED,
    }
    assert cursor.executed is None


def test_explain_plan_output_is_bounded(tmp_path: Path) -> None:
    service, _, _ = make_service(
        tmp_path,
        [(index, "SIMPLE") for index in range(4)],
        max_rows=2,
    )

    result = service.explain("SELECT id FROM appdb.orders", [])

    assert len(result["plan"]["rows"]) == 2
    assert result["truncated"] is True
